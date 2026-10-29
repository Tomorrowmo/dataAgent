"""User skills: import a skill package, draft its description card, wire it into chat.

A skill package is the Agent Skills layout — a folder (uploaded as .zip) with a
SKILL.md (YAML frontmatter `name` / `description` + markdown instructions), plus
optional `scripts/*.py` and reference documents. A bare SKILL.md / .md also works.

  import  → extract safely, parse SKILL.md, validate scripts against the
            algorithm contract (META + run(df, **params)), keep text references
  card    → the LLM reads everything and drafts a description / configuration
            card the user reviews and edits (deterministic fallback without LLM)
  confirm → conformant scripts become sandboxed tools (Algorithm rows, source
            "skill"); the skill turns `active` and is selectable in chat
  chat    → selected skills are injected into the system prompt; the others are
            listed as a catalog the agent may RECOMMEND (never silently use)
"""

from __future__ import annotations

import io
import json
import re
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import Algorithm, Skill
from ..sandbox.validator import validate_algorithm_code
from . import algo_store
from .llm import LLMClient

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_EXTRACT_BYTES = 40 * 1024 * 1024
MAX_FILES = 300
TEXT_EXTS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}
SCRIPT_EXTS = {".py"}
# Prompt budget for the selected skills (instructions + reference excerpts).
PROMPT_BUDGET = 16000


class SkillImportError(ValueError):
    pass


# ── import ──────────────────────────────────────────────────────────────────

def _safe_member(name: str) -> Optional[PurePosixPath]:
    """Zip member → safe relative path, or None (absolute / traversal / junk)."""
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        return None
    if any(part.startswith(".") or part == "__MACOSX" for part in p.parts):
        return None
    return p


def extract_package(data: bytes, filename: str, dest: Path) -> List[Path]:
    """Write the package's usable files under `dest`; returns their paths.
    Zip-slip safe, size / count capped, only text + .py files kept."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise SkillImportError(f"文件太大（上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB）")
    dest.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    if ext in (".md", ".txt"):
        out = dest / "SKILL.md"
        out.write_bytes(data)
        return [out]
    if ext != ".zip":
        raise SkillImportError("请上传 skill 文件夹打包的 .zip，或单个 SKILL.md")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise SkillImportError("zip 文件损坏或不是 zip") from e
    members: List[Tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        rel = _safe_member(info.filename)
        if rel is None or rel.suffix.lower() not in TEXT_EXTS | SCRIPT_EXTS:
            continue
        members.append((info, rel))
    if not members:
        raise SkillImportError("zip 里没有找到 SKILL.md / 文档 / Python 脚本")
    if len(members) > MAX_FILES:
        raise SkillImportError(f"文件太多（上限 {MAX_FILES} 个）")
    if sum(i.file_size for i, _ in members) > MAX_EXTRACT_BYTES:
        raise SkillImportError("解压后体积过大")
    # A zip of the folder itself has one common top directory — drop it.
    tops = {rel.parts[0] for _, rel in members if len(rel.parts) > 1}
    strip = len(tops) == 1 and all(len(rel.parts) > 1 for _, rel in members)
    written = []
    for info, rel in members:
        parts = rel.parts[1:] if strip else rel.parts
        target = dest.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src:
            target.write_bytes(src.read(info.file_size + 1)[: info.file_size])
        written.append(target)
    return written


def _read_text(p: Path, limit: int = 2_000_000) -> str:
    raw = p.read_bytes()[:limit]
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), m.group(2)


# Imports that mark a script as written for its original environment (CLI,
# network, file system, processes) rather than as a data algorithm.
_ENV_MODULES = {"argparse", "sys", "os", "subprocess", "socket", "urllib", "requests", "http", "ssl",
                "secrets", "shutil", "pathlib", "getpass", "httpx", "aiohttp", "smtplib", "ftplib", "glob"}


def classify_script(rel: str, code: str) -> Dict[str, Any]:
    """How the platform can use a skill's script:
      tool      — follows the algorithm contract → registered as a sandboxed tool
      reference — anything else; kept and shown to the agent as reference only.
    `note` is the user-facing one-liner; `errors` the raw validator detail."""
    v = validate_algorithm_code(code)
    base = {"path": rel, "ok": v.ok, "errors": v.errors[:8], "tool_slug": "", "chars": len(code)}
    if v.ok:
        return {**base, "kind": "tool", "note": "符合平台算法规范，启用后注册为平台工具，智能体可在沙箱中调用。"}
    roots = {i.split(".")[0] for i in v.imports}
    env = sorted(roots & _ENV_MODULES)
    if env:
        note = (f"这是在原环境里运行的脚本（用到 {', '.join(env[:5])} 等命令行 / 网络 / 文件功能），"
                "平台的安全沙箱不运行这类脚本；它的内容会作为参考提供给智能体。")
    elif not v.has_run_function or not v.has_meta:
        note = "不是平台算法的格式（缺少 META 或 run(df, **params)），作为参考资料提供给智能体。"
    else:
        note = "用到了平台沙箱不允许的写法，作为参考资料提供给智能体，不会被直接运行。"
    return {**base, "kind": "reference", "note": note}


def parse_package(root: Path, files: List[Path]) -> Dict[str, Any]:
    """Locate SKILL.md, read frontmatter + body, classify the rest."""
    mds = sorted((f for f in files if f.suffix.lower() == ".md"), key=lambda f: len(f.relative_to(root).parts))
    skill_md = next((f for f in mds if f.name.lower() == "skill.md"), None)
    if skill_md is None and len(mds) == 1:
        skill_md = mds[0]
    if skill_md is None:
        raise SkillImportError("没有找到 SKILL.md（skill 的说明文件）")
    fm, body = _split_frontmatter(_read_text(skill_md))

    refs, scripts = [], []
    for f in files:
        if f == skill_md:
            continue
        rel = f.relative_to(root).as_posix()
        if f.suffix.lower() in SCRIPT_EXTS:
            code = _read_text(f)
            scripts.append(classify_script(rel, code))
        else:
            refs.append({"path": rel, "chars": len(_read_text(f))})
    return {
        "name": str(fm.get("name") or skill_md.parent.name or "skill").strip(),
        "description": str(fm.get("description") or "").strip(),
        "instructions": body.strip(),
        "references": refs,
        "scripts": scripts,
    }


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or f"skill_{int(time.time()) % 100000}"


def skill_dir(owner_id: int, slug: str) -> Path:
    return get_settings().upload_path / f"user_{owner_id}" / "skills" / f"{slug}_{int(time.time() * 1000)}"


# ── description / configuration card ────────────────────────────────────────

CARD_PROMPT = """你是数据分析平台的 skill 审核助手。用户上传了一个 skill（技能包），下面是它的 SKILL.md、附带脚本的校验结果和参考资料列表。
请为它写一张「说明与配置卡」，让用户一眼看懂这个 skill 能做什么、什么时候用、需要什么数据，并确认是否接入平台。

只输出一个 JSON 对象，字段：
{
  "name": "简短中文名（可保留原英文名）",
  "summary": "一两句话说明它做什么",
  "when_to_use": ["适用场景/触发条件，2-4 条"],
  "inputs": ["需要的数据或列（如：含 cycle 与容量列的电池循环数据），没有就写空数组"],
  "steps": ["它会按什么步骤分析，3-6 条，忠实于 SKILL.md，不要编造 SKILL.md 里没有的步骤"],
  "outputs": ["产出什么结果/图表/结论"],
  "tools": [{"file": "脚本路径", "purpose": "这个脚本做什么"}],
  "cautions": ["使用注意事项/局限，没有就写空数组"],
  "platform_fit": {
    "level": "full | partial | low",
    "summary": "一句话：这个 skill 在本平台上能发挥到什么程度",
    "missing": ["SKILL.md 依赖、但本平台没有的工具/服务/数据（如外部 API、专用命令），每条说明是什么；全都具备就写空数组"]
  }
}
只能根据给出的内容写，不确定的不要猜；SKILL.md 没提到的数据要求不要编。
platform_fit 的判断依据：本平台是表格数据分析平台，智能体能用下面列出的内置算法、skill 自带的「平台工具」脚本，以及按需生成新算法；不能联网、不能调用外部服务、不能运行命令行脚本。
- full：步骤都能用平台能力完成；partial：部分步骤依赖平台没有的东西；low：核心步骤依赖外部服务/工具，平台上基本无法执行。"""


def fallback_card(parsed: Dict[str, Any]) -> Dict[str, Any]:
    body = parsed.get("instructions") or ""
    steps = [ln.strip("-*0123456789. 　").strip() for ln in body.splitlines()
             if re.match(r"^\s*(\d+[.)]|[-*])\s+\S", ln)][:6]
    return {
        "name": parsed.get("name") or "skill",
        "summary": parsed.get("description") or (body.strip().splitlines() or [""])[0][:160],
        "when_to_use": [parsed["description"]] if parsed.get("description") else [],
        "inputs": [], "steps": steps, "outputs": [],
        "tools": [{"file": s["path"], "purpose": ""} for s in parsed.get("scripts", []) if s.get("ok")],
        "cautions": [],
    }


def platform_tools_brief() -> str:
    from ..algorithms import registry  # heavy import, only when drafting a card
    return "、".join(f"{s.slug}（{s.name}）" for s in registry.list_builtins())


async def _chat_json(llm: LLMClient, messages: List[Dict[str, Any]], max_tokens: int) -> Dict[str, Any]:
    """LLM call that must return a JSON object. Card text is full of quotes and
    brackets, so an occasional malformed reply gets ONE repair round with the
    parser's error fed back."""
    raw = await llm.chat(messages, temperature=0.2, max_tokens=max_tokens, json_mode=True)
    for attempt in range(2):
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            obj = json.loads(m.group(0) if m else raw)
            if isinstance(obj, dict):
                return obj
            raise ValueError("not a JSON object")
        except (ValueError, json.JSONDecodeError) as e:
            if attempt == 1:
                raise
            raw = await llm.chat(messages + [
                {"role": "assistant", "content": raw[:6000]},
                {"role": "user", "content": f"上面的输出不是合法 JSON（{e}）。请重新输出完整、合法的 JSON 对象；"
                                            "字符串里的双引号要写成 \\\" 或改用「」。只输出 JSON。"},
            ], temperature=0.1, max_tokens=max_tokens, json_mode=True)
    raise ValueError("unreachable")


async def draft_card(llm: LLMClient, parsed: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """(card, source) — source is "ai" or "fallback" (no key / LLM failed)."""
    if not llm.is_configured:
        return fallback_card(parsed), "fallback"
    scripts = "\n".join(
        f"- {s['path']}：{'平台工具（可在沙箱运行）' if s.get('kind', 'tool' if s.get('ok') else 'reference') == 'tool' else '参考脚本（平台不运行）：' + s.get('note', '')}"
        for s in parsed.get("scripts", [])
    ) or "（无）"
    refs = "\n".join(f"- {r['path']}（{r['chars']} 字）" for r in parsed.get("references", [])) or "（无）"
    user = (
        f"## SKILL.md frontmatter\nname: {parsed.get('name')}\ndescription: {parsed.get('description')}\n\n"
        f"## SKILL.md 正文\n{(parsed.get('instructions') or '')[:12000]}\n\n"
        f"## 附带脚本\n{scripts}\n\n## 参考资料\n{refs}\n\n"
        f"## 本平台的内置算法\n{platform_tools_brief()}"
    )
    try:
        card = await _chat_json(llm, [{"role": "system", "content": CARD_PROMPT}, {"role": "user", "content": user}], 2000)
    except Exception:  # noqa: BLE001 — a card is still useful without the LLM
        return fallback_card(parsed), "fallback"
    base = fallback_card(parsed)
    for k, v in base.items():
        card.setdefault(k, v)
    return normalize_card(card), "ai"


def normalize_card(card: Dict[str, Any]) -> Dict[str, Any]:
    def strs(v: Any) -> List[str]:
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in (v or []) if str(x).strip()][:12]
    tools = [{"file": str(t.get("file", "")), "purpose": str(t.get("purpose", ""))}
             for t in (card.get("tools") or []) if isinstance(t, dict)]
    return {
        "name": str(card.get("name") or "").strip()[:120],
        "summary": str(card.get("summary") or "").strip()[:600],
        "when_to_use": strs(card.get("when_to_use")),
        "inputs": strs(card.get("inputs")),
        "steps": strs(card.get("steps")),
        "outputs": strs(card.get("outputs")),
        "tools": tools,
        "cautions": strs(card.get("cautions")),
        "platform_fit": _fit(card.get("platform_fit")),
    }


def _fit(v: Any) -> Dict[str, Any]:
    v = v if isinstance(v, dict) else {}
    level = str(v.get("level") or "").strip().lower()
    missing = v.get("missing") or []
    return {
        "level": level if level in ("full", "partial", "low") else "",
        "summary": str(v.get("summary") or "").strip()[:300],
        "missing": [str(x).strip() for x in (missing if isinstance(missing, list) else [missing]) if str(x).strip()][:10],
    }


ADJUST_PROMPT = """你在帮用户调整一个 skill 的「说明与配置卡」。下面给出当前卡片（JSON）和 skill 的 SKILL.md。
按用户的要求修改卡片，没被要求改的字段保持原样；内容必须忠实于 SKILL.md，不能编造它没有的能力。
只输出一个 JSON 对象：{"reply": "一两句话告诉用户改了什么", "card": {完整的新卡片，字段同输入}}"""


async def adjust_card(llm: LLMClient, skill: Skill, instruction: str) -> Tuple[Dict[str, Any], str]:
    """(new card, reply) — the user's plain-language edit applied by the LLM."""
    user = (
        f"当前卡片：\n{json.dumps(skill.config or {}, ensure_ascii=False)}\n\n"
        f"SKILL.md 正文：\n{(skill.instructions or '')[:10000]}\n\n用户的要求：{instruction.strip()}"
    )
    obj = await _chat_json(llm, [{"role": "system", "content": ADJUST_PROMPT}, {"role": "user", "content": user}], 2500)
    card = {**(skill.config or {}), **(obj.get("card") or {})}
    return normalize_card(card), str(obj.get("reply") or "已按要求修改。")


# ── confirm: scripts → sandboxed tools ──────────────────────────────────────

async def register_tools(session: AsyncSession, skill: Skill) -> List[Dict[str, Any]]:
    """Turn each conformant script into an Algorithm row (source "skill") the
    agent can run in the sandbox. Re-confirming updates them as new versions."""
    from ..algorithms import registry  # heavy import, only on confirm

    root = Path(skill.files_dir)
    out = []
    for s in skill.scripts or []:
        s = dict(s)
        if s.get("ok"):
            code = _read_text(root / s["path"])
            try:
                meta = algo_store.static_meta(code)
            except ValueError as e:
                s.update(ok=False, errors=[str(e)], kind="reference", note="META 无法读取，作为参考资料提供给智能体。")
                out.append(s)
                continue
            slug = slugify(meta.get("slug") or Path(s["path"]).stem)
            if registry.get_builtin(slug):
                slug = f"{skill.slug}_{slug}"
            row = (await session.execute(
                select(Algorithm).where(Algorithm.slug == slug, Algorithm.owner_id == skill.owner_id)
                .order_by(Algorithm.id.desc()).limit(1)
            )).scalar_one_or_none()
            fields = dict(
                name=str(meta.get("name") or slug), category=str(meta.get("category") or "skill"),
                description=f"[skill:{skill.name}] " + str(meta.get("description") or ""),
                code=code, params_schema=meta.get("params_schema") or {},
                returns=str(meta.get("returns") or "dataframe"), is_verified=True,
                test_report={"source": "skill", "skill_id": skill.id},
            )
            if row is None:
                row = Algorithm(owner_id=skill.owner_id, slug=slug, source="skill", version=1, **fields)
                session.add(row)
                await session.flush()
            else:
                await algo_store.ensure_history(session, row, skill.owner_id)
                for k, v in fields.items():
                    setattr(row, k, v)
                row.version = (row.version or 1) + 1
            algo_store.snapshot(session, row, note=f"来自 skill「{skill.name}」", user_id=skill.owner_id)
            s["tool_slug"] = slug
        out.append(s)
    return out


# ── platform default skills ─────────────────────────────────────────────────

DEFAULTS_DIR = Path(__file__).resolve().parents[1] / "skills_builtin"


async def ensure_defaults(session: AsyncSession, owner_id: int) -> None:
    """Give the user every shipped default skill (active), and keep their
    instructions in sync with the package. The user's status / card edits stay."""
    if not DEFAULTS_DIR.exists():
        return
    have = {s.slug: s for s in (await session.execute(
        select(Skill).where(Skill.owner_id == owner_id, Skill.is_default == True)  # noqa: E712
    )).scalars().all()}
    changed = False
    for pkg in sorted(p for p in DEFAULTS_DIR.iterdir() if (p / "SKILL.md").exists()):
        fm, body = _split_frontmatter(_read_text(pkg / "SKILL.md"))
        slug = slugify(str(fm.get("name") or pkg.name))
        row = have.get(slug)
        if row is None:
            card_file = pkg / "card.json"
            card = normalize_card(json.loads(_read_text(card_file))) if card_file.exists() else fallback_card(
                {"name": fm.get("name"), "description": fm.get("description"), "instructions": body, "scripts": []})
            session.add(Skill(
                owner_id=owner_id, slug=slug, name=card.get("name") or str(fm.get("name") or slug),
                description=str(fm.get("description") or ""), instructions=body.strip(), config=card,
                references=[], scripts=[], files_dir=str(pkg), source_filename="平台默认",
                status="active", is_default=True,
            ))
            changed = True
        elif row.instructions != body.strip():
            row.instructions = body.strip()
            row.description = str(fm.get("description") or row.description)
            changed = True
    if changed:
        await session.commit()


async def remove_skill(session: AsyncSession, skill: Skill) -> None:
    for s in skill.scripts or []:
        if s.get("tool_slug"):
            row = await algo_store.find_algorithm(session, s["tool_slug"], skill.owner_id)
            if row is not None and row.owner_id == skill.owner_id and row.source == "skill":
                await algo_store.delete_algorithm(session, row)
    if skill.files_dir and not skill.is_default:  # a default's dir is the shipped package
        shutil.rmtree(skill.files_dir, ignore_errors=True)
    await session.delete(skill)


# ── chat integration ────────────────────────────────────────────────────────

def _references_text(skill: Skill, budget: int) -> str:
    root = Path(skill.files_dir)
    parts, used = [], 0
    for r in skill.references or []:
        if used >= budget:
            break
        p = root / r["path"]
        if not p.exists() or p.suffix.lower() not in (".md", ".txt"):
            continue
        txt = _read_text(p)[: max(0, budget - used)]
        used += len(txt)
        parts.append(f"--- {r['path']} ---\n{txt}")
    return "\n".join(parts)


def prompt_section(selected: List[Skill], catalog: List[Skill]) -> str:
    """System-prompt block: full text of the user-selected skills, a one-line
    catalog of the others (for recommendation only)."""
    out = []
    if selected:
        per = max(2000, PROMPT_BUDGET // len(selected))
        out.append(
            "## Active skills (selected by the user for this conversation)\n"
            "Follow these skills' instructions when the request falls in their scope — they are the user's own "
            "domain procedures and take precedence over your generic approach. Use the tools they list (by slug) "
            "where they fit. The other rules above (number provenance, column honesty, …) still apply.\n"
        )
        for s in selected:
            c = s.config or {}
            tools = [x.get("tool_slug") for x in (s.scripts or []) if x.get("tool_slug")]
            instr = (s.instructions or "")[: per]
            refs = _references_text(s, max(0, per - len(instr)))
            refs_scripts = ""
            root = Path(s.files_dir or ".")
            for x in (s.scripts or []):
                if x.get("kind") == "reference" and (root / x["path"]).exists() and len(refs_scripts) < 3000:
                    refs_scripts += f"--- {x['path']} (reference only — NOT runnable on this platform) ---\n" \
                                    + _read_text(root / x["path"])[:1500] + "\n"
            fit = c.get("platform_fit") or {}
            out.append(
                f"### Skill「{c.get('name') or s.name}」(slug `{s.slug}`)\n"
                f"Summary: {c.get('summary') or s.description}\n"
                + (f"When to use: {'；'.join(c.get('when_to_use') or [])}\n" if c.get("when_to_use") else "")
                + (f"Tools from this skill: {', '.join(f'`{t}`' for t in tools)}\n" if tools else "")
                + f"Instructions:\n{instr}\n"
                + (f"Reference material:\n{refs}\n" if refs else "")
                + (f"Not available on this platform (tell the user plainly if a step needs them; never pretend "
                   f"to run them): {'；'.join(fit.get('missing') or [])}\n" if fit.get("missing") else "")
                + (f"Reference scripts:\n{refs_scripts}" if refs_scripts else "")
            )
    if catalog:
        out.append(
            "## Other skills the user has (NOT enabled for this turn)\n"
            "Do NOT follow them. If one of these would clearly help with the user's request, finish your answer "
            "normally and add its slug to `args.suggest_skills` (e.g. \"suggest_skills\": [\"battery_soh\"]) — the UI "
            "then offers the user a one-click 启用. Only suggest a skill whose summary actually matches the request.\n"
            + "\n".join(
                f"- `{s.slug}`：{(s.config or {}).get('name') or s.name} — {(s.config or {}).get('summary') or s.description}"
                for s in catalog
            )
        )
    return "\n\n".join(out)


def skill_view(s: Skill) -> Dict[str, Any]:
    return {
        "id": s.id, "slug": s.slug, "name": s.name, "description": s.description,
        "status": s.status, "is_default": bool(s.is_default), "config": s.config or {}, "references": s.references or [],
        "scripts": s.scripts or [], "source_filename": s.source_filename,
        "instructions": s.instructions or "",
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
