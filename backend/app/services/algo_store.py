"""Library-side helpers for user / AI algorithms: lookup, versioning, source.

One row in `algorithms` per (owner, slug) = the CURRENT version; history lives in
`algorithm_versions`. Everything that resolves a slug to user code goes through
`find_algorithm` so the access rule (own first, then public) lives in one place.
"""

from __future__ import annotations

import ast
import inspect
import pprint
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.base import SessionLocal
from ..db.models import Algorithm, AlgorithmVersion


def static_meta(code: str) -> Dict[str, Any]:
    """Read the top-level META dict WITHOUT executing the code (ast.literal_eval).
    Same contract parse_meta used to enforce by exec'ing the module in-process."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"SyntaxError: {e}") from e
    meta_node = None
    has_run = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "META" for t in node.targets
        ):
            meta_node = node.value
        elif isinstance(node, ast.FunctionDef) and node.name == "run":
            has_run = True
    if meta_node is None:
        raise ValueError("code is missing a top-level META dict")
    try:
        meta = ast.literal_eval(meta_node)
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"META must be a literal dict (no variables / calls), line {meta_node.lineno}") from e
    if not isinstance(meta, dict):
        raise ValueError("META must be a dict")
    for k in ("name", "slug", "category", "description"):
        if not meta.get(k):
            raise ValueError(f"META.{k} is missing")
    if not has_run:
        raise ValueError("code is missing a `run` function")
    return meta


async def find_algorithm(session: AsyncSession, slug: str, owner_id: int) -> Optional[Algorithm]:
    """Resolve a slug the caller may use: their own algorithm first, else a public
    one. Newest row wins if legacy duplicates are still around."""
    own = (await session.execute(
        select(Algorithm).where(Algorithm.slug == slug, Algorithm.owner_id == owner_id)
        .order_by(Algorithm.id.desc()).limit(1)
    )).scalar_one_or_none()
    if own is not None:
        return own
    return (await session.execute(
        select(Algorithm).where(Algorithm.slug == slug, Algorithm.is_public == True)  # noqa: E712
        .order_by(Algorithm.id.desc()).limit(1)
    )).scalar_one_or_none()


def _version_from(row: Algorithm, *, note: str, user_id: Optional[int]) -> AlgorithmVersion:
    return AlgorithmVersion(
        algorithm_id=row.id, version=row.version or 1, code=row.code or "",
        name=row.name or "", description=row.description or "", category=row.category or "custom",
        params_schema=row.params_schema or {}, is_verified=bool(row.is_verified),
        test_report=row.test_report or {}, note=note, created_by=user_id,
    )


async def ensure_history(session: AsyncSession, row: Algorithm, user_id: Optional[int]) -> None:
    """Rows saved before versioning existed have no snapshot of their current
    state — take one before the first edit so it can be restored."""
    n = (await session.execute(
        select(func.count()).select_from(AlgorithmVersion).where(AlgorithmVersion.algorithm_id == row.id)
    )).scalar_one()
    if not n:
        session.add(_version_from(row, note="初始版本", user_id=user_id))


def snapshot(session: AsyncSession, row: Algorithm, *, note: str, user_id: Optional[int]) -> None:
    session.add(_version_from(row, note=note, user_id=user_id))


async def delete_algorithm(session: AsyncSession, row: Algorithm) -> None:
    # sqlite doesn't enforce ON DELETE CASCADE unless the pragma is on — delete
    # the history explicitly.
    for v in await list_versions(session, row.id):
        await session.delete(v)
    await session.delete(row)


async def list_versions(session: AsyncSession, algorithm_id: int) -> List[AlgorithmVersion]:
    return list((await session.execute(
        select(AlgorithmVersion).where(AlgorithmVersion.algorithm_id == algorithm_id)
        .order_by(AlgorithmVersion.id.desc())
    )).scalars().all())


async def dedupe_algorithms() -> int:
    """Collapse legacy duplicate (owner, slug) rows — the old /save inserted a new
    row per version — into one live row (the newest) plus version history.
    Idempotent; returns how many rows were folded."""
    folded = 0
    async with SessionLocal() as session:
        dups = (await session.execute(
            select(Algorithm.owner_id, Algorithm.slug)
            .where(Algorithm.owner_id.is_not(None))
            .group_by(Algorithm.owner_id, Algorithm.slug)
            .having(func.count() > 1)
        )).all()
        for owner_id, slug in dups:
            rows = list((await session.execute(
                select(Algorithm).where(Algorithm.owner_id == owner_id, Algorithm.slug == slug)
                .order_by(Algorithm.id)
            )).scalars().all())
            keeper = rows[-1]
            for old in rows[:-1]:
                v = _version_from(old, note="合并的旧版本", user_id=owner_id)
                v.algorithm_id = keeper.id
                session.add(v)
                await session.delete(old)
                folded += 1
            snapshot(session, keeper, note="合并时的当前版本", user_id=owner_id)
        await session.commit()
    return folded


# ── built-in source (read-only) + "copy as my algorithm" ────────────────────────

def builtin_source(slug: str) -> Dict[str, Any]:
    from ..algorithms import registry  # heavy (pandas) — keep out of startup imports

    spec = registry.get_builtin(slug)
    if spec is None:
        raise KeyError(slug)
    fn = registry._BUILTINS[spec.slug].fn
    code = textwrap.dedent(inspect.getsource(fn))
    file = inspect.getsourcefile(fn) or ""
    try:
        file = str(Path(file).resolve().relative_to(Path(__file__).resolve().parents[2]))
    except ValueError:
        pass
    return {
        "slug": spec.slug, "name": spec.name, "code": code,
        "file": file.replace("\\", "/"), "line": inspect.getsourcelines(fn)[1],
        "entry": f"{fn.__name__}(df, **params)",
    }


def _bound_names(node: ast.stmt) -> List[str]:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [(a.asname or a.name).split(".")[0] for a in node.names]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _used_names(node: ast.AST) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def fork_code(slug: str) -> str:
    """Turn a built-in into a sandbox-ready custom algorithm: META from its spec,
    its function renamed to `run`, plus the module-level helpers / constants /
    imports it (transitively) uses. Best effort — the user debugs the result in
    the editor like any other custom algorithm."""
    from ..algorithms import registry

    spec = registry.get_builtin(slug)
    if spec is None:
        raise KeyError(slug)
    fn = registry._BUILTINS[spec.slug].fn
    mod = sys.modules[fn.__module__]
    src = inspect.getsource(mod)
    tree = ast.parse(src)

    defs: Dict[str, ast.stmt] = {}
    imports: List[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and (node.level or node.module == "__future__"):
                continue  # relative (registry) / __future__ imports don't belong in a sandbox module
            imports.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
            for name in _bound_names(node):
                defs.setdefault(name, node)

    entry = defs.get(fn.__name__)
    if entry is None:
        raise KeyError(slug)
    needed: List[ast.stmt] = []
    seen = {fn.__name__}
    queue = list(_used_names(entry))
    while queue:
        name = queue.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        node = defs[name]
        if node not in needed:
            needed.append(node)
            queue.extend(_used_names(node))

    body_names = set().union(*(_used_names(n) for n in [entry, *needed]))
    used_imports = [n for n in imports if set(_bound_names(n)) & body_names]

    seg = lambda n: ast.get_source_segment(src, n) or ""  # noqa: E731
    run_src = seg(entry).replace(f"def {fn.__name__}(", "def run(", 1)
    meta = {
        "name": f"{spec.name}（副本）",
        "slug": f"{spec.slug}_custom",
        "category": spec.category,
        "description": spec.description,
        "params_schema": spec.params_schema,
        "returns": spec.returns,
        "tags": list(spec.tags),
    }
    helpers = [n for n in tree.body if n in needed]  # keep original module order
    parts = [
        f'"""基于内置算法「{spec.name}」({spec.slug}) 复制的自定义算法。\n'
        f'在沙箱中运行；修改后点「调试运行」验证，再保存为新版本。"""',
        "\n".join(seg(n) for n in used_imports),
        "META = " + pprint.pformat(meta, indent=1, width=100, sort_dicts=False),
        *[seg(n) for n in helpers],
        run_src,
    ]
    return "\n\n\n".join(p for p in parts if p.strip()) + "\n"
