"""Re-run the algorithm steps of a past chat turn (改进清单-3 · S5).

Used when a turn's result data is gone (cleaned up, or produced before the
storage rework): the turn's successful `run_tool` calls are replayed IN ORDER on
the original dataset(s), with the same pipeline semantics the agent uses
(working copy per dataset + frame history un-shadowing), and the new results are
materialised as fresh derived datasets. No LLM is involved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..algorithms import registry
from ..db.models import Conversation, Dataset
from .algo_store import find_algorithm
from .artifacts import discard_scratch
from .chat_agent import _read_frame_for_tool
from .datasets import _persist_dataset
from .storage import scrub


@dataclass
class Step:
    slug: str
    params: Dict[str, Any]
    dataset_ref: Optional[str]          # args.dataset (name or id) as the agent passed it


@dataclass
class Plan:
    steps: List[Step] = field(default_factory=list)
    blocked: Optional[str] = None       # human-readable reason when the turn can't be re-run


def steps_from_events(events: List[Dict[str, Any]]) -> List[Step]:
    """The turn's run_tool calls whose result came back ok, in order."""
    out: List[Step] = []
    pending: Optional[Dict[str, Any]] = None
    for ev in events or []:
        kind = ev.get("kind")
        payload = ev.get("payload") or {}
        if kind == "tool_call":
            pending = payload if payload.get("action") == "run_tool" else None
        elif kind == "tool_result" and pending is not None:
            res = payload.get("result") or {}
            if payload.get("action") == "run_tool" and res.get("status") == "ok":
                args = pending.get("args") or {}
                if args.get("slug"):
                    ref = args.get("dataset")
                    out.append(Step(slug=str(args["slug"]), params=dict(args.get("params") or {}),
                                    dataset_ref=None if ref is None else str(ref)))
            pending = None
    return out


async def _user_datasets(session: AsyncSession, owner_id: int) -> List[Dataset]:
    return list((await session.execute(
        select(Dataset).where(Dataset.owner_id == owner_id).order_by(Dataset.id)
    )).scalars().all())


def _match(datasets: List[Dataset], ref: Optional[str], primary: Optional[Dataset]) -> Optional[Dataset]:
    if ref is None:
        return primary
    for d in datasets:
        if d.name == ref or str(d.id) == ref:
            return d
    return None


async def plan_rerun(session: AsyncSession, owner_id: int, conv: Conversation,
                     events: List[Dict[str, Any]]) -> Tuple[Plan, Dict[int, Dataset]]:
    """Work out whether the turn can be replayed, and on which datasets."""
    plan = Plan(steps=steps_from_events(events))
    if not plan.steps:
        plan.blocked = "这一轮没有可以重新运行的算法步骤（例如只有画图）。"
        return plan, {}
    datasets = await _user_datasets(session, owner_id)
    primary = next((d for d in datasets if d.id == conv.dataset_id), None)
    resolved: Dict[int, Dataset] = {}
    for i, st in enumerate(plan.steps):
        ds = _match(datasets, st.dataset_ref, primary)
        if ds is None:
            plan.blocked = f"第 {i + 1} 步用到的原始数据「{st.dataset_ref or '对话主数据集'}」已删除，无法重新运行。"
            return plan, {}
        resolved[i] = ds
        if not registry.get_builtin(st.slug):
            row = await find_algorithm(session, st.slug, owner_id)
            if row is None:
                plan.blocked = f"第 {i + 1} 步的算法「{st.slug}」已删除，无法重新运行。"
                return plan, {}
            if not row.is_verified:
                plan.blocked = f"第 {i + 1} 步的算法「{row.name}」是尚未确认保留的 AI 草稿，请先在算法库确认后再重新运行。"
                return plan, {}
    return plan, resolved


async def execute_rerun(session: AsyncSession, owner_id: int, plan: Plan,
                        resolved: Dict[int, Dataset], conversation_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Replay the plan; returns chat-style events (tool_call / tool_result)."""
    events: List[Dict[str, Any]] = []
    working: Dict[int, Any] = {}
    frames: Dict[int, List[Any]] = {}
    lineage: Dict[int, Tuple[int, str]] = {}
    refs: Dict[int, Tuple[Any, Dict[str, Any]]] = {}   # id(frame) → (frame, input ref) — same as the agent
    from .runs import finish_group, new_group, record_run, root_name
    group = await new_group(session, owner_id, "chat", conversation_id=conversation_id)
    step_runs: Dict[int, Tuple[int, Optional[int]]] = {}
    statuses: List[str] = []
    for i, st in enumerate(plan.steps):
        ds = resolved[i]
        args = {"slug": st.slug, "params": st.params}
        if st.dataset_ref is not None:
            args["dataset"] = st.dataset_ref
        events.append({"kind": "tool_call", "payload": {"action": "run_tool", "args": args}})
        df, note = _read_frame_for_tool(ds, working, frames, st.params)
        hit = refs.get(id(df))
        input_ref = dict(hit[1]) if hit is not None and hit[0] is df else {"kind": "dataset", "dataset_id": ds.id}
        spec = registry.get_builtin(st.slug)
        row = None
        if spec:
            from .dataset_params import resolve_dataset_params
            result = registry.execute_builtin(st.slug, df, st.params,
                                              frames=await resolve_dataset_params(session, owner_id, st.slug, st.params))
            label = spec.name
            algo_info: Dict[str, Any] = {"slug": st.slug, "source": "builtin"}
        else:
            row = await find_algorithm(session, st.slug, owner_id)
            result = registry.execute_code(row.code, df, st.params)  # type: ignore[union-attr]
            label = row.name  # type: ignore[union-attr]
            algo_info = {"slug": st.slug, "source": row.source, "id": row.id, "version": row.version,  # type: ignore[union-attr]
                         "verified": bool(row.is_verified)}  # type: ignore[union-attr]
        result["provenance"] = {"step": i, "input": input_ref, "dataset_id": ds.id, "algorithm": algo_info,
                                "label": label, "params": st.params, "output_role": None}
        if note and result.get("status") == "ok":
            result.setdefault("summary", {})["ran_on"] = note
        if result.get("status") == "ok" and result.get("result_path"):
            out_df = pd.read_parquet(result["result_path"])
            discard_scratch(result)
            is_report = len(out_df) < len(df) and len(out_df) <= max(int(df.shape[1]), 12)
            result["provenance"]["output_role"] = "report" if is_report else "data"
            refs[id(out_df)] = (out_df, {"kind": "step", "step": i})
            working[ds.id] = out_df
            frames.setdefault(ds.id, []).append((label, out_df))
            parent_id, parent_name = lineage.get(ds.id, (ds.id, ds.name))
            d = await _persist_dataset(
                session, owner_id=owner_id, df=out_df,
                name=f"{await root_name(session, ds)} · {label}", filename=f"{st.slug}.parquet",
                file_format="derived", description=f"由「{parent_name}」经『{label}』得到（重新运行）",
                kind="derived", derived_from=parent_id,
                lineage={"from": parent_id, "from_name": parent_name,
                         "op": {"slug": st.slug, "label": label, "params": st.params}},
            )
            await session.commit()
            lineage[ds.id] = (d.id, d.name)
            result["derived_dataset"] = {"id": d.id, "name": d.name}
        if input_ref.get("kind") == "step" and input_ref.get("step") in step_runs:
            r_in, r_ds = {"kind": "run", "run_id": step_runs[input_ref["step"]][0]}, step_runs[input_ref["step"]][1]
        else:
            r_in, r_ds = {"kind": "dataset", "dataset_id": ds.id}, ds.id
        derived = (result.get("derived_dataset") or {}).get("id")
        run = await record_run(session, group, seq=len(step_runs) + 1, slug=st.slug, label=label, result=result,
                               params=st.params, input_ref=r_in, dataset_id=r_ds, algorithm=row,
                               result_dataset_id=derived, output_role=result["provenance"].get("output_role"))
        step_runs[i] = (run.id, derived)
        statuses.append(run.status)
        result["provenance"]["run_id"] = run.id
        result["provenance"]["run_code"] = f"R-{group.seq_no:04d}.{run.seq}"
        await session.commit()
        events.append({"kind": "tool_result", "payload": {"action": "run_tool", "result": scrub(result)}})
        if result.get("status") != "ok":
            break   # later steps depend on this one — stop, the event shows the error
    finish_group(group, statuses)
    await session.commit()
    return events
