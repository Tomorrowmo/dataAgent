"""Install a skill pack: extract → manifest → static check → smoke test →
place on disk → register in the DB.

Every stage appends to an install report that is stored on the row and shown in
the UI. A pack that fails at stage 3 must never look like a pack that simply
wasn't used yet — "no silent steps" applies to installation exactly as it does
to a chat turn.

The report is also the honest answer to "is this thing trustworthy?":
  static_check  — did every python file stay inside the pack's permission box
  smoke_test    — did each tool actually import, and pass the tests it declared
  trust         — sandbox (checked python) vs command (ships its own binary)
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import SkillPack
from ..sandbox import executor as sandbox_executor
from .checks import check_pack
from .manifest import ManifestError, SkillManifest, find_doc, load_manifest

SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "node_modules", ".venv", "venv"}
DANGEROUS_SUFFIXES = {".lnk"}


class InstallError(RuntimeError):
    """Install refused. Message is user-facing (中文) and actionable."""


@dataclass
class Stage:
    stage: str
    ok: bool
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"stage": self.stage, "ok": self.ok, "detail": self.detail, "data": self.data}


@dataclass
class InstallReport:
    ok: bool = True
    stages: List[Stage] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def add(self, stage: str, ok: bool, detail: str = "", **data: Any) -> Stage:
        st = Stage(stage=stage, ok=ok, detail=detail, data=data)
        self.stages.append(st)
        if not ok:
            self.ok = False
        return st

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "stages": [s.to_dict() for s in self.stages],
            "warnings": list(self.warnings),
            "duration_s": round(time.time() - self.started_at, 2),
        }


# ── extraction ───────────────────────────────────────────────────────────────

def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> List[str]:
    """Extract with the three zip hazards handled explicitly: path traversal,
    symlinks, and a bomb. A malicious member is a hard refusal, not a warning."""
    settings = get_settings()
    max_bytes = settings.skills_max_pack_mb * 1024 * 1024
    total = 0
    names: List[str] = []
    dest_resolved = dest.resolve()

    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > settings.skills_max_files:
        raise InstallError(f"压缩包里文件太多({len(infos)} 个,上限 {settings.skills_max_files})。")

    for info in infos:
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise InstallError(f"压缩包里有非法路径:{name}(不允许绝对路径或 ..)")
        if (info.external_attr >> 16) & 0o120000 == 0o120000:
            raise InstallError(f"压缩包里有符号链接:{name} —— 不接受。")
        if Path(name).suffix.lower() in DANGEROUS_SUFFIXES:
            raise InstallError(f"不接受这种文件:{name}")
        if any(part in SKIP_DIRS for part in Path(name).parts):
            continue
        total += info.file_size
        if total > max_bytes:
            raise InstallError(f"技能包解压后超过 {settings.skills_max_pack_mb} MB,拒绝安装。")

        target = (dest / name).resolve()
        if dest_resolved not in target.parents and target != dest_resolved:
            raise InstallError(f"压缩包成员越界:{name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        names.append(name)
    return names


def _descend_single_root(root: Path) -> Path:
    """A zip made by right-clicking a folder wraps everything in one directory.
    Descend into it (up to 2 levels) so the user doesn't have to re-zip."""
    cur = root
    for _ in range(2):
        if find_doc(cur) is not None:
            return cur
        entries = [p for p in cur.iterdir() if p.name not in SKIP_DIRS and not p.name.startswith("__MACOSX")]
        dirs = [p for p in entries if p.is_dir()]
        if len(entries) == 1 and len(dirs) == 1:
            cur = dirs[0]
            continue
        if len(dirs) == 1 and not any(p.is_file() for p in entries):
            cur = dirs[0]
            continue
        break
    return cur


def _copy_tree(src: Path, dest: Path) -> None:
    shutil.copytree(
        src, dest,
        ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.pyc"),
        dirs_exist_ok=True,
    )


def _list_files(root: Path) -> List[str]:
    out: List[str] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            out.append(str(p.relative_to(root)).replace("\\", "/"))
    return out


def _checksum(root: Path, files: List[str]) -> str:
    h = hashlib.sha256()
    for rel in files:
        h.update(rel.encode("utf-8"))
        try:
            h.update((root / rel).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:32]


# ── smoke test ───────────────────────────────────────────────────────────────

def _frame_from_test(case: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """Build the test dataframe from a declared test case.

    Supported (author picks whichever is least annoying):
      data: {col: [values], ...}
      csv:  "a,b\\n1,2"           (inline csv text)
      file: "tests/sample.csv"    (resolved by the caller, passed in as `data`)
    """
    if "data" in case and isinstance(case["data"], dict) and case["data"]:
        return pd.DataFrame(case["data"])
    if case.get("csv"):
        return pd.read_csv(io.StringIO(str(case["csv"])))
    return None


def _check_expectations(case: Dict[str, Any], result: Dict[str, Any]) -> Optional[str]:
    """Verify the declared expectations against the tool result summary.

    Deliberately small: rows / columns / keys / non_empty. A test language that
    can express anything ends up untestable itself."""
    exp = case.get("expect") or {}
    if not isinstance(exp, dict):
        return None
    summary = result.get("summary") or {}
    problems: List[str] = []

    if "rows" in exp and int(summary.get("rows", -1)) != int(exp["rows"]):
        problems.append(f"期望 {exp['rows']} 行,实际 {summary.get('rows')} 行")
    if exp.get("min_rows") is not None and int(summary.get("rows", 0)) < int(exp["min_rows"]):
        problems.append(f"期望至少 {exp['min_rows']} 行,实际 {summary.get('rows')} 行")
    want_cols = exp.get("columns") or exp.get("has_columns")
    if want_cols:
        got = set(map(str, summary.get("columns") or []))
        missing = [c for c in want_cols if str(c) not in got]
        if missing:
            problems.append(f"结果里缺少列:{'、'.join(map(str, missing))}(实际有:{'、'.join(sorted(got)) or '无'})")
    want_keys = exp.get("keys")
    if want_keys:
        val = summary.get("value")
        got_keys = set(val.keys()) if isinstance(val, dict) else set()
        missing = [k for k in want_keys if k not in got_keys]
        if missing:
            problems.append(f"返回的字典里缺少键:{'、'.join(map(str, missing))}")
    if exp.get("non_empty") and not (summary.get("rows") or summary.get("value") or summary.get("length")):
        problems.append("结果是空的")
    return "; ".join(problems) or None


def smoke_test_pack(root: Path, manifest: SkillManifest, *, allow_command: bool) -> Tuple[bool, List[Dict[str, Any]]]:
    """Import-probe every python tool, then run whatever tests it declared."""
    reports: List[Dict[str, Any]] = []
    all_ok = True

    for tool in manifest.tools:
        entry_reports: List[Dict[str, Any]] = []
        if tool.runtime == "python":
            probe = sandbox_executor.execute_skill(
                pack_dir=str(root), entry_module=tool.module, entry_func=tool.func,
                params={}, input_df=None, needs_data=False, probe=True, save_result=False,
                timeout_seconds=get_settings().skill_timeout_seconds,
            )
            ok = probe.status == "ok"
            entry_reports.append({
                "kind": "import", "ok": ok,
                "detail": "入口可导入" if ok else (probe.error or "导入失败")[:800],
                "duration_ms": probe.duration_ms,
            })
            if not ok:
                all_ok = False
        elif tool.runtime == "script":
            # 通用包的脚本要带参数才跑得动,安装时无从构造 —— 只确认脚本文件在。
            missing = [sc for sc in (tool.params_schema.get("script", {}).get("enum") or [])
                       if not (Path(root) / sc).is_file()]
            entry_reports.append({
                "kind": "import", "ok": not missing,
                "detail": ("包内脚本已就位;运行需要服务端开启 SKILLS_ALLOW_COMMAND_RUNTIME"
                           if not missing else f"清单里的脚本找不到:{'、'.join(missing[:5])}"),
            })
            if missing:
                all_ok = False
        else:
            entry_reports.append({
                "kind": "import", "ok": bool(allow_command),
                "detail": ("自带可执行程序,已按管理员配置放行(不做静态检查)"
                           if allow_command else
                           "自带可执行程序,但服务端未开启 command runtime —— 工具不可运行"),
            })
            if not allow_command:
                all_ok = False

        for i, case in enumerate(tool.tests or []):
            df = _frame_from_test(case)
            file_rel = case.get("file")
            if df is None and file_rel:
                fp = root / str(file_rel)
                if fp.is_file():
                    df = pd.read_csv(fp) if fp.suffix.lower() == ".csv" else pd.read_parquet(fp)
            if df is None and tool.needs_data:
                entry_reports.append({
                    "kind": "test", "name": case.get("name") or f"test{i + 1}", "ok": False,
                    "detail": "这个测试没给数据(需要 data / csv / file 之一),无法执行。",
                })
                all_ok = False
                continue
            from .runtime import run_tool as _run  # local import: avoids a cycle
            res = _run(root=str(root), tool=tool.to_dict(), df=df,
                       params=case.get("params") or {}, allow_command=allow_command)
            ok = res.get("status") == "ok"
            detail = res.get("error", "")[:800] if not ok else "通过"
            if ok:
                problem = _check_expectations(case, res)
                if problem:
                    ok, detail = False, problem
            entry_reports.append({
                "kind": "test", "name": case.get("name") or f"test{i + 1}", "ok": ok,
                "detail": detail, "duration_ms": res.get("duration_ms", 0),
                "summary": res.get("summary", {}),
            })
            if not ok:
                all_ok = False

        reports.append({
            "tool": tool.name, "runtime": tool.runtime,
            "ok": all(r["ok"] for r in entry_reports),
            "checks": entry_reports,
        })
    return all_ok, reports


# ── install ──────────────────────────────────────────────────────────────────

def pack_root_for(owner_id: int, slug: str) -> Path:
    return get_settings().skills_path / str(owner_id) / slug


def build_verdict(manifest: SkillManifest, check, tool_reports: List[Dict[str, Any]],
                  tests_ok: bool) -> Dict[str, Any]:
    """One plain-language answer to "这个包能不能用",for the 验一下 panel.

    Deliberately separates the three things a user conflates:
      能装吗      — 硬性拦截(静态检查/清单)
      AI 能拿到啥 — 知识 / 工具 / 两者都有
      要改什么    — 具体到文件和字段的下一步
    """
    python_tools = [t for t in manifest.tools if t.runtime == "python"]
    cmd_tools = [t for t in manifest.tools if t.runtime == "command"]
    ok_tools = [r["tool"] for r in tool_reports if r.get("ok")]
    bad_tools = [r["tool"] for r in tool_reports if not r.get("ok")]

    script_tools = [t for t in manifest.tools if t.runtime == "script"]
    if script_tools:
        gives = f"知识 + 包内脚本({len(manifest.scripts)} 个,AI 用 run_script 调)"
    elif manifest.tools:
        gives = "知识 + 工具" if manifest.doc_body else "工具"
    else:
        gives = "只有知识(SKILL.md),没有可执行工具"

    fixes: List[str] = []
    if script_tools:
        fixes.append("要真正执行包里的脚本,需要管理员开启 SKILLS_ALLOW_COMMAND_RUNTIME;"
                     "不开也不影响 AI 读它的知识。")
    if not manifest.when_to_use:
        fixes.append("补一句 `when_to_use`(什么情况下该用它)—— AI 靠它决定要不要打开这个包。")
    if not manifest.tools:
        fixes.append("想让它能算东西:加一个 skill.yaml 声明 tools,入口写成 `模块:函数`。")
    if not manifest.triggers:
        fixes.append("加几个 `triggers`(用户会怎么说这件事),命中率会高不少。")
    for r in tool_reports:
        for c in r.get("checks", []):
            if not c.get("ok"):
                fixes.append(f"工具 `{r['tool']}` 的{'导入' if c.get('kind') == 'import' else '自测'}"
                             f"没过:{str(c.get('detail'))[:200]}")
    if python_tools and not script_tools and not any(t.tests for t in python_tools):
        fixes.append("给每个工具至少写一个 `tests` —— 否则只能验证「能导入」,验证不了「算得对」。")

    return {
        "installable": bool(check.ok),
        "blockers": list(check.errors[:12]),
        "gives": gives,
        "knowledge_only": not manifest.tools,
        "doc_chars": len(manifest.doc_body),
        "tools_total": len(manifest.tools),
        "tools_ok": ok_tools,
        "tools_failed": bad_tools,
        "command_tools": [t.name for t in cmd_tools],
        "kind": manifest.kind,
        "scripts": list(manifest.scripts[:20]),
        "self_check_passed": bool(tests_ok and check.ok),
        "warnings": list(check.warnings)[:12],
        "fixes": fixes[:8],
    }


async def install_pack(
    session: AsyncSession,
    owner_id: int,
    *,
    zip_bytes: Optional[bytes] = None,
    src_dir: Optional[str] = None,
    enable: Optional[bool] = None,
    allow_command: bool = False,
    dry_run: bool = False,
) -> Tuple[Optional[SkillPack], Dict[str, Any]]:
    """Install (or upgrade) a skill pack for one user.

    Returns (row, report). `dry_run=True` runs every check and returns the report
    WITHOUT writing anything — that's the "先验一下" button in the UI.

    `enable=None` means "don't decide": a fresh install lands enabled, an upgrade
    KEEPS whatever the user had chosen. Re-installing a pack you had switched off
    must not quietly switch it back on — that would put a pack back in front of
    the agent behind the user's back.
    """
    settings = get_settings()
    report = InstallReport()
    staging = Path(tempfile.mkdtemp(prefix="da_skill_install_"))

    try:
        # 1 ── get the files into staging
        if zip_bytes is not None:
            if len(zip_bytes) > settings.skills_max_pack_mb * 1024 * 1024:
                raise InstallError(f"压缩包超过 {settings.skills_max_pack_mb} MB。")
            try:
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    names = _safe_extract(zf, staging)
            except zipfile.BadZipFile as e:
                raise InstallError(f"这不是一个有效的 zip 文件:{e}") from e
            report.add("extract", True, f"解压 {len(names)} 个文件", files=len(names))
        elif src_dir:
            src = Path(src_dir).expanduser()
            if not src.is_dir():
                raise InstallError(f"目录不存在:{src_dir}")
            _copy_tree(src, staging)
            report.add("extract", True, f"从目录导入:{src}", source=str(src))
        else:
            raise InstallError("既没有上传 zip,也没有给目录路径。")

        root = _descend_single_root(staging)

        # 2 ── manifest
        try:
            manifest, warnings = load_manifest(root)
        except ManifestError as e:
            report.add("manifest", False, str(e))
            raise InstallError(str(e)) from e
        report.warnings.extend(warnings)
        report.add("manifest", True,
                   f"{manifest.name} v{manifest.version} — {len(manifest.tools)} 个工具",
                   slug=manifest.slug, version=manifest.version,
                   tools=[t.name for t in manifest.tools], warnings=warnings)

        # 3 ── static check of every python file
        check = check_pack(
            root,
            requires=set(manifest.requires),
            entry_modules={t.module for t in manifest.tools if t.runtime == "python"},
        )
        report.add("static_check", check.ok,
                   "全部通过" if check.ok else "; ".join(check.errors[:6]),
                   result=check.to_dict())
        if not check.ok:
            raise InstallError(
                "静态检查没通过 —— 技能包里的代码触碰了不允许的能力:\n"
                + "\n".join(f"· {e}" for e in check.errors[:12])
                + "\n\n(技能包可以读写自己的目录、用 numpy/pandas/scipy 等库;"
                "不能联网、不能起子进程、不能删除文件。详见《技能包接入规范》。)"
            )

        wants_command = manifest.trust == "command"   # 自带 exe:仅管理员
        if manifest.kind == "generic":
            report.add(
                "compat", True,
                ("通用 skill 包(标准 SKILL.md 格式)。知识部分立刻可用" +
                 (f";自动识别 {len(manifest.scripts)} 个脚本,已配 run_script 工具"
                  if manifest.scripts else ";没有可运行脚本,纯知识")),
                kind="generic", scripts=manifest.scripts[:20],
                allowed_tools=manifest.allowed_tools,
            )
        effective_allow_command = bool(allow_command and settings.skills_allow_command_runtime)
        if wants_command:
            report.add(
                "trust", effective_allow_command,
                ("包含自带可执行程序,已按管理员授权放行" if effective_allow_command else
                 "包含自带可执行程序(runtime: command),但未获授权 —— "
                 "需要管理员安装并开启 SKILLS_ALLOW_COMMAND_RUNTIME"),
                runtime="command",
            )

        # 4 ── smoke test (import probe + declared tests), from the staging copy
        t0 = time.time()
        tests_ok, tool_reports = smoke_test_pack(root, manifest, allow_command=effective_allow_command)
        report.add("smoke_test", tests_ok,
                   ("全部工具可用" if tests_ok else "有工具没通过 —— 见详情"),
                   tools=tool_reports, duration_s=round(time.time() - t0, 2))

        files = _list_files(root)
        checksum = _checksum(root, files)
        verdict = build_verdict(manifest, check, tool_reports, tests_ok)

        if dry_run:
            report.add("install", True, "试运行:没有写入任何文件")
            return None, {**report.to_dict(), "manifest": manifest.to_dict(),
                          "verified": bool(tests_ok and check.ok), "verdict": verdict}

        # 5 ── place on disk (previous version moved aside, restored on failure)
        dest = pack_root_for(owner_id, manifest.slug)
        backup: Optional[Path] = None
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            backup = dest.with_name(dest.name + f".bak{int(time.time())}")
            dest.rename(backup)
        try:
            _copy_tree(root, dest)
        except Exception:
            if backup is not None:
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                backup.rename(dest)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        report.add("install", True, f"已安装到 {dest}", path=str(dest), files=len(files))

        # 6 ── register / upgrade the row
        existing = (await session.execute(
            select(SkillPack).where(SkillPack.owner_id == owner_id,
                                    SkillPack.slug == manifest.slug)
        )).scalar_one_or_none()

        verified = bool(tests_ok and check.ok)
        payload = dict(
            name=manifest.name, version=manifest.version,
            description=manifest.description, when_to_use=manifest.when_to_use,
            triggers=manifest.triggers, category=manifest.category,
            root=str(dest), manifest=manifest.to_dict(),
            tools=[t.to_dict() for t in manifest.tools],
            doc_chars=len(manifest.doc_body), files=files,
            trust=manifest.trust, is_verified=verified,
            install_report=report.to_dict(), checksum=checksum,
        )
        if existing is not None:
            was_enabled = bool(existing.enabled)
            for k, v in payload.items():
                setattr(existing, k, v)
            existing.enabled = was_enabled if enable is None else bool(enable)
            row = existing
            kept = enable is None and not was_enabled
            report.add(
                "register", True,
                f"升级已有技能包(id={existing.id})" + ("(保持你之前的「停用」状态)" if kept else ""),
                upgraded=True, enabled=bool(existing.enabled),
            )
        else:
            row = SkillPack(owner_id=owner_id, slug=manifest.slug,
                            enabled=True if enable is None else bool(enable), **payload)
            session.add(row)
            report.add("register", True, "新装技能包", upgraded=False, enabled=bool(row.enabled))

        row.install_report = {**report.to_dict(), "verdict": verdict}
        await session.commit()
        await session.refresh(row)
        return row, {**report.to_dict(), "manifest": manifest.to_dict(),
                     "verified": verified, "verdict": verdict}

    except InstallError:
        raise
    except Exception as e:  # noqa: BLE001
        report.add("error", False, f"{type(e).__name__}: {e}")
        raise InstallError(f"安装失败:{type(e).__name__}: {e}") from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def remove_pack(session: AsyncSession, row: SkillPack, *, delete_files: bool = True) -> None:
    root = Path(row.root) if row.root else None
    await session.delete(row)
    await session.commit()
    if delete_files and root is not None and root.is_dir():
        # Only ever delete inside the managed skills directory.
        if get_settings().skills_path.resolve() in root.resolve().parents:
            shutil.rmtree(root, ignore_errors=True)
