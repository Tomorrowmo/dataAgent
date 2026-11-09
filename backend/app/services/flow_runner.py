"""Flow (template) validation and execution — 改进清单-3 · L2b / L2c / L2d / E2.

A flow step (stored JSON):
    {"action": "run_tool", "slug": str, "params": {...}, "label": str,
     "algorithm_id": int | None,   # custom / AI algorithms only
     "version": int | None,        # pinned algorithm version
     "input": "start" | int,       # explicit input: the start dataset, or the output of step <int>
     "output_role": "data" | "report" | None}

Steps without "input" (older flows, canvas-built flows) keep the legacy linear
rule: each step reads the previous step's output, except that a REPORT output
(fewer rows than its input AND only a handful) does not thread forward.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..algorithms import registry
from ..db.models import Algorithm, AlgorithmVersion, Dataset
from .algo_store import find_algorithm
from .artifacts import discard_scratch
from .datasets import _persist_dataset, load_dataset_df
from .storage import scrub


class FlowError(Exception):
    """A flow that may not be saved / run, with a user-facing reason."""


def _is_tool(step: Dict[str, Any]) -> bool:
    return step.get("action", "run_tool") == "run_tool" and bool(step.get("slug"))


async def _algo_row(session: AsyncSession, owner_id: int, step: Dict[str, Any]) -> Optional[Algorithm]:
    aid = step.get("algorithm_id")
    if aid:
        row = await session.get(Algorithm, int(aid))
        if row is not None and (row.owner_id == owner_id or row.is_public):
            return row
        return None
    return await find_algorithm(session, str(step["slug"]), owner_id)


async def validate_steps(session: AsyncSession, owner_id: int, steps: List[Dict[str, Any]]) -> None:
    """Raise FlowError when any step can't legally be part of a flow."""
    for i, st in enumerate(steps):
        if not _is_tool(st):
            continue
        n = i + 1
        label = st.get("label") or st.get("slug")
        inp = st.get("input")
        if inp is not None and inp != "start":
            if not isinstance(inp, int) or inp < 0 or inp >= i or not _is_tool(steps[inp]):
                raise FlowError(f"第 {n} 步「{label}」的输入引用无效（只能是起始数据或前面的算法步骤）。")
        if registry.get_builtin(str(st["slug"])):
            continue
        row = await _algo_row(session, owner_id, st)
        if row is None:
            raise FlowError(f"第 {n} 步的算法「{label}」不存在或无权使用。")
        if row.deleted_at is not None:
            raise FlowError(f"第 {n} 步的算法「{row.original_slug or label}」已删除。")
        if not row.is_verified:
            raise FlowError(f"第 {n} 步的算法「{row.name}」是尚未确认保留的 AI 草稿，请先在算法库确认保留。")
        v = st.get("version")
        if v is not None and int(v) != int(row.version or 1):
            snap = (await session.execute(select(AlgorithmVersion).where(
                AlgorithmVersion.algorithm_id == row.id, AlgorithmVersion.version == int(v)))).scalar_one_or_none()
            if snap is None:
                raise FlowError(f"第 {n} 步锁定的算法版本 v{v} 已不存在。")


async def pin_versions(session: AsyncSession, owner_id: int, steps: List[Dict[str, Any]],
                       old_steps: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Fill algorithm_id/version for custom-algorithm steps that don't carry one.
    A step that already had a pinned version (same slug at the same position in
    the previous save) keeps it — re-saving the canvas never silently upgrades."""
    out = []
    for i, st in enumerate(steps):
        st = dict(st)
        if _is_tool(st) and not registry.get_builtin(str(st["slug"])) and st.get("version") is None:
            prev = (old_steps or [])[i] if old_steps and i < len(old_steps) else None
            if prev and prev.get("slug") == st.get("slug") and prev.get("version") is not None:
                st["algorithm_id"] = prev.get("algorithm_id")
                st["version"] = prev.get("version")
            else:
                row = await _algo_row(session, owner_id, st)
                if row is not None:
                    st["algorithm_id"] = row.id
                    st["version"] = row.version or 1
        out.append(st)
    return out


async def code_for(session: AsyncSession, row: Algorithm, version: Optional[int]) -> str:
    """The algorithm's code at `version` (current code when not pinned / same)."""
    if version is None or int(version) == int(row.version or 1):
        return row.code
    snap = (await session.execute(select(AlgorithmVersion).where(
        AlgorithmVersion.algorithm_id == row.id, AlgorithmVersion.version == int(version)))).scalar_one_or_none()
    if snap is None:
        raise FlowError(f"算法「{row.name}」的 v{version} 已不存在。")
    return snap.code


def _is_report(out_df: pd.DataFrame, in_df: pd.DataFrame) -> bool:
    return len(out_df) < len(in_df) and len(out_df) <= max(int(in_df.shape[1]), 12)


async def newer_versions(session: AsyncSession, owner_id: int, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Steps whose pinned version is behind the algorithm's current version."""
    out = []
    for i, st in enumerate(steps):
        if not _is_tool(st) or st.get("version") is None or not st.get("algorithm_id"):
            continue
        row = await session.get(Algorithm, int(st["algorithm_id"]))
        if row is not None and row.deleted_at is None and int(row.version or 1) > int(st["version"]):
            out.append({"i": i, "label": st.get("label") or st.get("slug"), "pinned": st["version"], "current": row.version})
    return out


async def run_flow(session: AsyncSession, owner_id: int, tpl_name: str, steps: List[Dict[str, Any]],
                   ds: Dataset, *, overrides: Optional[Dict[str, Dict[str, Any]]] = None,
                   save_result: bool = True, template_id: Optional[int] = None,
                   entry: str = "flow", conversation_id: Optional[int] = None) -> Dict[str, Any]:
    """Execute a flow on `ds`. Stops at the first failing step (status
    'partial'). Returns step results, the derived chain, the final frame and
    chat-style events (tool_call / tool_result) for writing into a conversation."""
    await validate_steps(session, owner_id, steps)
    overrides = overrides or {}
    start_df = load_dataset_df(ds)
    cur_df = start_df                       # legacy linear threading
    cur_ref: Dict[str, Any] = {"kind": "dataset", "dataset_id": ds.id}
    outputs: Dict[int, pd.DataFrame] = {}   # step index → its DataFrame output
    out_ds: Dict[int, Tuple[int, str]] = {}  # step index → derived dataset (id, name)
    step_results: List[Dict[str, Any]] = []
    derived_chain: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    parent_id, parent_name = ds.id, ds.name
    status = "ok"
    # 改进清单-3 · D2: one run group per flow execution, one run per step.
    from .runs import finish_group, new_group, record_run, root_name
    group = await new_group(session, owner_id, entry, "flow", template_id=template_id, conversation_id=conversation_id)
    root = await root_name(session, ds)
    run_of_step: Dict[int, int] = {}
    statuses: List[str] = []

    for i, st in enumerate(steps):
        slug = st.get("slug")
        label = st.get("label") or slug or st.get("action")
        if not _is_tool(st):
            step_results.append({"i": i, "label": label, "slug": slug, "status": "skipped", "note": "非算法步骤,已跳过"})
            continue
        params = {**(st.get("params") or {}), **(overrides.get(str(i)) or {})}
        inp = st.get("input")
        if inp is None:
            in_df, in_parent, in_ref = cur_df, (parent_id, parent_name), dict(cur_ref)
        elif inp == "start":
            in_df, in_parent, in_ref = start_df, (ds.id, ds.name), {"kind": "dataset", "dataset_id": ds.id}
        else:
            if inp not in outputs:
                step_results.append({"i": i, "label": label, "slug": slug, "status": "error",
                                     "error": f"依赖的第 {inp + 1} 步没有产出数据"})
                status = "partial"
                break
            in_df = outputs[inp]
            in_parent = out_ds.get(inp, (parent_id, parent_name))
            in_ref = {"kind": "step", "step": inp}

        algo_info: Dict[str, Any] = {"slug": slug}
        row = None
        if registry.get_builtin(str(slug)):
            res = registry.execute_builtin(str(slug), in_df, params)
            algo_info["source"] = "builtin"
        else:
            row = await _algo_row(session, owner_id, st)
            code = await code_for(session, row, st.get("version"))  # type: ignore[arg-type]
            res = registry.execute_code(code, in_df, params)
            algo_info.update({"source": row.source, "id": row.id, "version": st.get("version") or row.version})  # type: ignore[union-attr]

        ok = res.get("status") == "ok"
        entry: Dict[str, Any] = {
            "i": i, "label": label, "slug": slug, "status": res.get("status", "error"),
            "error": res.get("error", ""), "rows": res.get("result_rows", 0),
            "summary": _light_summary(res.get("summary", {})),
        }
        call_args = {"slug": slug, "params": params}
        events.append({"kind": "tool_call", "payload": {"action": "run_tool", "args": call_args}})
        rp = res.get("result_path")
        role: Optional[str] = None
        if ok and rp:
            out_df = pd.read_parquet(rp)
            discard_scratch(res)
            role = st.get("output_role") or ("report" if _is_report(out_df, in_df) else "data")
            entry["report"] = role == "report"
            outputs[i] = out_df
            if save_result:
                d = await _persist_dataset(
                    session, owner_id=owner_id, df=out_df,
                    name=f"{root} · {label}", filename=f"{label}.parquet",
                    file_format="derived", description=f"流程「{tpl_name}」第 {i + 1} 步:{label}"
                                + ("（报告,不参与后续数据流）" if role == "report" else ""),
                    idx=i, kind="derived", derived_from=in_parent[0],
                    lineage={"from": in_parent[0], "from_name": in_parent[1],
                             "op": {"slug": slug, "label": label, "params": params}},
                )
                entry["dataset_id"] = d.id
                out_ds[i] = (d.id, d.name)
                res["derived_dataset"] = {"id": d.id, "name": d.name}
                derived_chain.append({"id": d.id, "name": d.name, "label": label,
                                      "rows": d.rows, "columns": d.columns, "report": role == "report"})
            if inp is None and role != "report":
                cur_df = out_df
                cur_ref = {"kind": "step", "step": i}
                if i in out_ds:
                    parent_id, parent_name = out_ds[i]
        res["provenance"] = {"step": i, "input": in_ref, "dataset_id": ds.id, "algorithm": algo_info,
                             "label": label, "params": params, "output_role": role}
        if in_ref.get("kind") == "step" and in_ref.get("step") in run_of_step:
            r_in, r_ds = {"kind": "run", "run_id": run_of_step[in_ref["step"]]}, out_ds.get(in_ref["step"], (None,))[0]
        else:
            r_in = {"kind": "dataset", "dataset_id": in_parent[0]}
            r_ds = in_parent[0]
        run = await record_run(session, group, seq=len(run_of_step) + 1, slug=str(slug), label=str(label), result=res,
                               params=params, input_ref=r_in, dataset_id=r_ds, algorithm=row,
                               version=st.get("version"), result_dataset_id=out_ds.get(i, (None,))[0], output_role=role)
        run_of_step[i] = run.id
        statuses.append(run.status)
        res["provenance"]["run_id"] = run.id
        res["provenance"]["run_code"] = f"R-{group.seq_no:04d}.{run.seq}"
        entry["run_code"] = res["provenance"]["run_code"]
        events.append({"kind": "tool_result", "payload": {"action": "run_tool", "result": scrub(res)}})
        step_results.append(entry)
        if not ok:
            status = "partial" if any(r.get("status") == "ok" for r in step_results) else "error"
            break   # 改进清单-3 · L2c: later steps depend on this one — stop here

    finish_group(group, statuses)
    await session.commit()
    final_df = cur_df if any(s.get("input") is None for s in steps if _is_tool(s)) else (
        outputs[max(outputs)] if outputs else start_df)
    return {
        "status": status,
        "steps": step_results,
        "final": {"rows": int(len(final_df)), "columns": list(map(str, final_df.columns)), "preview": _df_head(final_df, 10)},
        "derived_chain": derived_chain,
        "new_dataset": derived_chain[-1] if derived_chain else None,
        "events": events,
        "run_group_code": f"R-{group.seq_no:04d}",
    }


def _light_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    out = {k: v for k, v in summary.items() if k != "head"}
    if summary.get("type") == "dataframe":
        out["rows"] = summary.get("rows")
    return out


def _df_head(df: pd.DataFrame, n: int) -> List[Dict[str, Any]]:
    import json
    try:
        return json.loads(df.head(n).to_json(orient="records", date_format="iso"))
    except Exception:
        return []
