"""Run records (改进清单-3 · D1/D2) and re-run / reproduce (V1).

Every algorithm execution started from the chat, the library or a flow is a
`Run`; the runs started by one user action form a `RunGroup` (R-<seq_no>,
runs R-<seq_no>.<seq>). Editor debug runs are not recorded.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..algorithms import registry
from ..db.models import Algorithm, AlgorithmVersion, Conversation, Dataset, FlowTemplate, Run, RunGroup
from ..version import APP_VERSION

PREVIEW_ROWS = 20


_SEQ_LOCK = None


async def _next_seq(owner_id: int) -> int:
    """Per-user batch number from a counter row, incremented and COMMITTED in
    its own short transaction — so concurrent requests can never get the same
    number (a max()+1 inside the caller's open transaction could)."""
    import asyncio
    from sqlalchemy import text
    from ..db.base import SessionLocal
    global _SEQ_LOCK
    if _SEQ_LOCK is None:
        _SEQ_LOCK = asyncio.Lock()
    key = f"run_seq:{int(owner_id)}"
    async with _SEQ_LOCK:
        async with SessionLocal() as s:
            res = await s.execute(text("UPDATE app_settings SET value = CAST(value AS INTEGER) + 1 WHERE key = :k"), {"k": key})
            if res.rowcount == 0:
                cur = (await s.execute(select(func.max(RunGroup.seq_no)).where(RunGroup.owner_id == owner_id))).scalar()
                await s.execute(text("INSERT INTO app_settings (key, value) VALUES (:k, :v)"), {"k": key, "v": str(int(cur or 0) + 1)})
            val = (await s.execute(text("SELECT value FROM app_settings WHERE key = :k"), {"k": key})).scalar()
            await s.commit()
            return int(val)


async def new_group(session: AsyncSession, owner_id: int, entry: str, target: str = "algorithm", *,
                    conversation_id: Optional[int] = None, template_id: Optional[int] = None) -> RunGroup:
    g = RunGroup(owner_id=owner_id, seq_no=await _next_seq(owner_id), entry=entry, target=target,
                 conversation_id=conversation_id, template_id=template_id, status="running")
    session.add(g)
    await session.flush()
    return g


def _trim_summary(summary: Any) -> Dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    out = dict(summary)
    head = out.get("head")
    if isinstance(head, list):
        out["head"] = head[:PREVIEW_ROWS]
    return out


async def record_run(session: AsyncSession, group: RunGroup, *, seq: int, slug: str, label: str,
                     result: Dict[str, Any], params: Dict[str, Any], input_ref: Dict[str, Any],
                     dataset_id: Optional[int], algorithm: Optional[Algorithm] = None,
                     version: Optional[int] = None, result_dataset_id: Optional[int] = None,
                     output_role: Optional[str] = None) -> Run:
    status = result.get("status") or "error"
    run = Run(
        owner_id=group.owner_id, group_id=group.id, seq=seq,
        algorithm_id=algorithm.id if algorithm is not None else None,
        algorithm_slug=slug, algorithm_source=(algorithm.source if algorithm is not None else "builtin"),
        algorithm_version=(version if version is not None else (algorithm.version if algorithm is not None else None)),
        app_version=APP_VERSION, label=label or slug, params=params or {}, input_ref=input_ref or {},
        dataset_id=dataset_id, result_dataset_id=result_dataset_id,
        artifact_id=result.get("artifact_id"), output_role=output_role,
        status=status if status in ("ok", "error", "cancelled") else "error",
        error=str(result.get("error") or "")[:4000], duration_ms=int(result.get("duration_ms") or 0),
        result_summary=_trim_summary(result.get("summary")),
    )
    session.add(run)
    await session.flush()
    if result_dataset_id is not None:
        ds = await session.get(Dataset, result_dataset_id)
        if ds is not None:
            ds.run_id = run.id
    if run.artifact_id:
        from ..db.models import Artifact
        a = await session.get(Artifact, run.artifact_id)
        if a is not None:
            a.run_id = run.id
    return run


def finish_group(group: RunGroup, statuses: List[str]) -> None:
    if not statuses:
        group.status = "ok"
    elif all(s == "ok" for s in statuses):
        group.status = "ok"
    elif any(s == "ok" for s in statuses):
        group.status = "partial"
    elif any(s == "cancelled" for s in statuses):
        group.status = "cancelled"
    else:
        group.status = "error"


def run_code(group: RunGroup, run: Optional[Run] = None) -> str:
    return f"R-{group.seq_no:04d}" + (f".{run.seq}" if run is not None else "")


async def describe_origin(session: AsyncSession, run: Run) -> Dict[str, Any]:
    """Where a run came from, for the "产生于" card."""
    g = await session.get(RunGroup, run.group_id)
    out: Dict[str, Any] = {"code": run_code(g, run) if g else f"run-{run.id}", "entry": g.entry if g else "",
                           "created_at": run.created_at.isoformat() if run.created_at else None}
    if g and g.conversation_id:
        c = await session.get(Conversation, g.conversation_id)
        out["conversation"] = {"id": g.conversation_id, "title": c.title if c else "（已删除的对话）", "exists": c is not None}
    elif g and g.entry == "chat":
        # The conversation was deleted (its id is cleared on delete).
        out["conversation"] = {"id": None, "title": "（已删除的对话）", "exists": False}
    if g and g.template_id:
        t = await session.get(FlowTemplate, g.template_id)
        out["template"] = {"id": g.template_id, "name": t.name if t else "（已删除的流程）", "exists": t is not None}
    return out


# ── re-run (current version) vs reproduce (the version used then) ──────────

class RunActionError(Exception):
    pass


async def _input_df(session: AsyncSession, run: Run) -> Dataset:
    from .datasets import load_dataset_df  # noqa: F401
    if not run.dataset_id:
        raise RunActionError("这次运行的输入数据已删除。")
    ds = await session.get(Dataset, run.dataset_id)
    if ds is None or ds.owner_id != run.owner_id:
        raise RunActionError("这次运行的输入数据已删除。")
    if ds.state == "cleaned":
        raise RunActionError("这次运行的输入数据已被清理，无法完整复现。")
    return ds


async def availability(session: AsyncSession, run: Run) -> Dict[str, Any]:
    """Can this run be re-run / reproduced? Reasons when not (V1)."""
    rerun_reason = reproduce_reason = None
    try:
        await _input_df(session, run)
    except RunActionError as e:
        rerun_reason = reproduce_reason = str(e)
    if registry.get_builtin(run.algorithm_slug):
        if reproduce_reason is None and run.app_version and run.app_version != APP_VERSION:
            reproduce_reason = None  # allowed, but flagged
    else:
        row = await session.get(Algorithm, run.algorithm_id) if run.algorithm_id else None
        if row is None:
            rerun_reason = rerun_reason or "算法已不存在。"
            reproduce_reason = reproduce_reason or "算法已不存在。"
        else:
            if row.deleted_at is not None:
                rerun_reason = rerun_reason or "算法已删除，无法用当前版本重跑。"
            if run.algorithm_version and run.algorithm_version != row.version:
                snap = (await session.execute(select(AlgorithmVersion).where(
                    AlgorithmVersion.algorithm_id == row.id, AlgorithmVersion.version == run.algorithm_version))).scalar_one_or_none()
                if snap is None:
                    reproduce_reason = reproduce_reason or f"当时的算法版本 v{run.algorithm_version} 已不存在。"
    warn = None
    if registry.get_builtin(run.algorithm_slug) and run.app_version and run.app_version != APP_VERSION:
        warn = f"内置算法随软件升级可能有变化：当时 {run.app_version}，现在 {APP_VERSION}。"
    return {"rerun": rerun_reason is None, "rerun_reason": rerun_reason,
            "reproduce": reproduce_reason is None, "reproduce_reason": reproduce_reason, "warning": warn}


async def execute_again(session: AsyncSession, run: Run, *, reproduce: bool) -> Dict[str, Any]:
    """Run the algorithm again on the run's input. reproduce=True uses the
    version recorded then; False uses the current version. The output becomes a
    new derived dataset and a new run (entry 'library')."""
    from .artifacts import discard_scratch
    from .datasets import _persist_dataset, load_dataset_df
    av = await availability(session, run)
    if reproduce and not av["reproduce"]:
        raise RunActionError(av["reproduce_reason"])
    if not reproduce and not av["rerun"]:
        raise RunActionError(av["rerun_reason"])
    ds = await _input_df(session, run)
    df = load_dataset_df(ds)
    row: Optional[Algorithm] = None
    version: Optional[int] = None
    if registry.get_builtin(run.algorithm_slug):
        from .dataset_params import resolve_dataset_params
        res = registry.execute_builtin(run.algorithm_slug, df, run.params or {},
                                       frames=await resolve_dataset_params(session, ds.owner_id, run.algorithm_slug, run.params or {}))
    else:
        row = await session.get(Algorithm, run.algorithm_id)
        from .flow_runner import code_for
        version = run.algorithm_version if reproduce else row.version  # type: ignore[union-attr]
        res = registry.execute_code(await code_for(session, row, version), df, run.params or {})  # type: ignore[arg-type]
    group = await new_group(session, run.owner_id, "library")
    derived_id = None
    if res.get("status") == "ok" and res.get("result_path"):
        out_df = pd.read_parquet(res["result_path"])
        discard_scratch(res)
        root = await root_name(session, ds)
        d = await _persist_dataset(
            session, owner_id=run.owner_id, df=out_df, name=f"{root} · {run.label}",
            filename=f"{run.algorithm_slug}.parquet", file_format="derived",
            description=("复现" if reproduce else "重跑") + f" {run.label}（原运行 #{run.id}）",
            kind="derived", derived_from=ds.id,
            lineage={"from": ds.id, "from_name": ds.name, "op": {"slug": run.algorithm_slug, "label": run.label, "params": run.params}},
        )
        derived_id = d.id
    new = await record_run(session, group, seq=1, slug=run.algorithm_slug, label=run.label, result=res,
                           params=run.params or {}, input_ref={"kind": "dataset", "dataset_id": ds.id},
                           dataset_id=ds.id, algorithm=row, version=version, result_dataset_id=derived_id)
    finish_group(group, [new.status])
    await session.commit()
    return {"run_id": new.id, "code": run_code(group, new), "status": new.status,
            "error": new.error, "dataset_id": derived_id, "warning": av.get("warning")}


async def root_name(session: AsyncSession, ds: Dataset) -> str:
    """The ORIGINAL (source) dataset's name — derived names don't chain."""
    cur, guard = ds, 0
    while cur is not None and cur.kind == "derived" and cur.derived_from and guard < 50:
        nxt = await session.get(Dataset, cur.derived_from)
        if nxt is None:
            break
        cur, guard = nxt, guard + 1
    return (cur or ds).name


def default_expiry(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)
