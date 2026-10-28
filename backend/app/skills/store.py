"""Everything the rest of the app needs from installed skill packs: query them,
turn them into a tool index the agent can call, and read their docs on demand.

Naming: a skill tool's slug is `<pack-slug>.<tool-name>` (e.g.
`battery-health.capacity_fade`). The dot makes the origin obvious in the
workbench and keeps two packs from colliding on a common name like `check`.
`resolve_tool` accepts the near-misses an LLM actually emits (bare tool name,
`__` instead of `.`, wrong case) — same self-healing principle as the builtin
registry's alias table.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import SkillPack

MAX_DOC_CHARS = 16000
MAX_REF_CHARS = 20000


async def list_packs(session: AsyncSession, owner_id: int, *,
                     enabled_only: bool = False) -> List[SkillPack]:
    stmt = select(SkillPack).where(
        (SkillPack.owner_id == owner_id) | (SkillPack.is_public == True)  # noqa: E712
    )
    if enabled_only:
        stmt = stmt.where(SkillPack.enabled == True)  # noqa: E712
    rows = list((await session.execute(stmt)).scalars().all())
    return sorted(rows, key=lambda r: (r.name or r.slug))


async def get_pack(session: AsyncSession, owner_id: int, slug: str) -> Optional[SkillPack]:
    stmt = select(SkillPack).where(
        SkillPack.slug == slug,
        (SkillPack.owner_id == owner_id) | (SkillPack.is_public == True),  # noqa: E712
    )
    return (await session.execute(stmt)).scalars().first()


def tool_slug(pack: SkillPack, tool: Dict[str, Any]) -> str:
    return f"{pack.slug}.{tool.get('name')}"


def usable_tools(pack: SkillPack) -> List[Dict[str, Any]]:
    return [t for t in (pack.tools or []) if isinstance(t, dict) and t.get("name")]


def tool_index(packs: Sequence[SkillPack]) -> List[Dict[str, Any]]:
    """Flatten enabled packs into the same shape `_registry_index` produces for
    builtins, so skill tools show up in the agent's tool list unchanged."""
    out: List[Dict[str, Any]] = []
    for pack in packs:
        for tool in usable_tools(pack):
            schema = tool.get("params_schema") or {}
            params = [
                f"{n}:{(ps or {}).get('type', 'string')}" + ("*" if (ps or {}).get("required") else "")
                for n, ps in schema.items()
            ]
            out.append({
                "slug": tool_slug(pack, tool),
                "name": tool.get("title") or tool.get("name"),
                "category": f"skill:{pack.slug}",
                "description": (tool.get("description") or "").strip()
                               or f"{pack.name} 提供的工具",
                "params": params,
                "source": "skill",
                "skill": pack.slug,
                "skill_name": pack.name,
                "verified": bool(pack.is_verified),
                "runtime": tool.get("runtime", "python"),
            })
    return out


def resolve_tool(packs: Sequence[SkillPack], slug: str) -> Optional[Tuple[SkillPack, Dict[str, Any]]]:
    """Find (pack, tool) for a slug the agent emitted, tolerating near-misses."""
    if not slug:
        return None
    want = str(slug).strip()
    candidates: List[Tuple[SkillPack, Dict[str, Any], str]] = [
        (p, t, tool_slug(p, t)) for p in packs for t in usable_tools(p)
    ]

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    # 1) exact, then case/separator-insensitive full slug
    for pack, tool, full in candidates:
        if full == want:
            return pack, tool
    for pack, tool, full in candidates:
        if norm(full) == norm(want):
            return pack, tool
    # 2) bare tool name — only when it is unambiguous across installed packs
    bare = want.split(".")[-1].split("__")[-1]
    hits = [(p, t) for p, t, _f in candidates if norm(t.get("name", "")) == norm(bare)]
    if len(hits) == 1:
        return hits[0]
    # 3) a declared alias
    for pack, tool, _full in candidates:
        if any(norm(a) == norm(want) or norm(a) == norm(bare) for a in (tool.get("aliases") or [])):
            return pack, tool
    return None


# ── prompt surfaces ──────────────────────────────────────────────────────────

def prompt_block(packs: Sequence[SkillPack]) -> str:
    """Level 1 disclosure: what the agent always sees. Identity + when_to_use +
    tool one-liners, never the SKILL.md body — that costs a `read_skill`."""
    if not packs:
        return ""
    lines: List[str] = []
    for pack in packs:
        head = f"- `{pack.slug}` — **{pack.name}**:{(pack.description or '').strip()}"
        lines.append(head)
        if pack.when_to_use:
            lines.append(f"  - 什么时候用:{pack.when_to_use.strip()}")
        tools = usable_tools(pack)
        if tools:
            lines.append("  - 工具:" + "、".join(
                f"`{tool_slug(pack, t)}`({(t.get('description') or t.get('title') or '').strip()[:40]})"
                for t in tools[:8]
            ) + ("…" if len(tools) > 8 else ""))
        if pack.doc_chars:
            lines.append(f"  - 用法细则写在这个包的 SKILL.md 里({pack.doc_chars} 字):"
                         f"动手前先 `read_skill` 打开它。")
        if any(t.get("runtime") == "script" for t in tools):
            # 通用 skill 包:SKILL.md 里的指令常常是"运行 scripts/xxx.py --foo"。
            # 明确告诉 AI 那种指令要落到 run_script 上,否则它会以为自己有 shell。
            lines.append(
                f"  - 这是通用 skill 包:它的 SKILL.md 里若让你**执行某个命令/脚本**,"
                f"用 `run_tool` 调 `{pack.slug}.run_script`(script=脚本相对路径,args=参数数组),"
                "不要假装自己能开终端。")
        if not pack.is_verified:
            lines.append("  - ⚠ 这个包安装时没能全部通过自检,工具可能跑不通;失败就如实告诉用户。")
    return "\n".join(lines)


def trigger_hits(packs: Sequence[SkillPack], message: str) -> List[SkillPack]:
    """Cheap keyword routing: which packs claim to cover what the user just
    asked. Used as a HINT (not an auto-load) so the agent still decides."""
    text = (message or "").lower()
    if not text:
        return []
    hits: List[SkillPack] = []
    for pack in packs:
        words = [w for w in (list(pack.triggers or []) + [pack.name, pack.slug]) if w]
        if any(str(w).lower() in text for w in words):
            hits.append(pack)
    return hits


# ── document reading (level 2 / 3 disclosure) ────────────────────────────────

def _safe_pack_file(pack: SkillPack, rel: str) -> Optional[Path]:
    """Resolve a file INSIDE the pack. Anything that escapes the pack root — via
    .., an absolute path, or a symlink — returns None."""
    root = Path(pack.root or "")
    if not root.is_dir():
        return None
    try:
        target = (root / str(rel)).resolve()
    except (OSError, ValueError):
        return None
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        return None
    return target if target.is_file() else None


def read_doc(pack: SkillPack, file: Optional[str] = None) -> Dict[str, Any]:
    """Return SKILL.md's body (default) or one reference file from the pack."""
    manifest = pack.manifest or {}
    refs = list(manifest.get("references") or [])
    if file:
        target = _safe_pack_file(pack, file)
        if target is None:
            return {
                "error": f"技能包 `{pack.slug}` 里没有这个文件:{file}",
                "available_files": refs or [f for f in (pack.files or []) if f.endswith(".md")],
            }
        if target.suffix.lower() not in (".md", ".markdown", ".txt", ".yaml", ".yml", ".json", ".csv"):
            return {"error": f"只能读文本类文件(.md/.txt/.yaml/.json/.csv),不能读 {target.name}"}
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > MAX_REF_CHARS
        return {
            "skill": pack.slug, "file": file, "content": text[:MAX_REF_CHARS],
            "truncated": truncated,
        }

    doc_name = manifest.get("doc_file") or "SKILL.md"
    target = _safe_pack_file(pack, doc_name)
    body = ""
    if target is not None:
        from .manifest import split_frontmatter
        _fm, body = split_frontmatter(target.read_text(encoding="utf-8", errors="replace"))
    return {
        "skill": pack.slug,
        "name": pack.name,
        "version": pack.version,
        "when_to_use": pack.when_to_use,
        "content": body.strip()[:MAX_DOC_CHARS],
        "truncated": len(body.strip()) > MAX_DOC_CHARS,
        "tools": [
            {"slug": tool_slug(pack, t), "description": t.get("description", ""),
             "params_schema": t.get("params_schema") or {}, "returns": t.get("returns", "dataframe"),
             "needs_data": t.get("needs_data", True), "examples": t.get("examples") or []}
            for t in usable_tools(pack)
        ],
        "references": refs,
        "verified": bool(pack.is_verified),
    }


def summarize(pack: SkillPack) -> Dict[str, Any]:
    """Row → API/list payload."""
    return {
        "id": pack.id,
        "slug": pack.slug,
        "name": pack.name,
        "version": pack.version,
        "description": pack.description,
        "when_to_use": pack.when_to_use,
        "triggers": list(pack.triggers or []),
        "category": pack.category,
        "enabled": bool(pack.enabled),
        "is_public": bool(pack.is_public),
        "is_verified": bool(pack.is_verified),
        "trust": pack.trust,
        "doc_chars": pack.doc_chars,
        "tool_count": len(usable_tools(pack)),
        "tools": [
            {"slug": tool_slug(pack, t), "name": t.get("title") or t.get("name"),
             "description": t.get("description", ""), "runtime": t.get("runtime", "python"),
             "needs_data": t.get("needs_data", True),
             "params_schema": t.get("params_schema") or {},
             "returns": t.get("returns", "dataframe")}
            for t in usable_tools(pack)
        ],
        "files": list(pack.files or []),
        "root": pack.root,
        "created_at": pack.created_at.isoformat() if pack.created_at else None,
        "updated_at": pack.updated_at.isoformat() if pack.updated_at else None,
    }
