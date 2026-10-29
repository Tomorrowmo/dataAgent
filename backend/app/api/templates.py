"""Flow templates — reusable multi-step pipelines.

A template is the ordered tool chain captured from a conversation's flow graph.
Replaying it on a new dataset re-runs each algorithm in order, THREADING each
step's DataFrame output into the next (a true pipeline: 去噪 → 检测异常 → 插值 → …),
and optionally registers the final result as a new dataset.
"""

from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..algorithms import registry
from ..db.models import Algorithm, Dataset, FlowTemplate, User
from ..services.algo_store import find_algorithm
from ..services.datasets import _persist_dataset, gc_derived_datasets, load_dataset_df
from .deps import current_user, get_db

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateStep(BaseModel):
    action: str = "run_tool"
    slug: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    label: Optional[str] = None


class CreateTemplateReq(BaseModel):
    name: str
    description: str = ""
    steps: List[TemplateStep]
    graph: Dict[str, Any] = Field(default_factory=dict)


class TemplateResp(BaseModel):
    id: int
    name: str
    description: str
    steps: List[Dict[str, Any]]
    n_steps: int
    graph: Dict[str, Any] = Field(default_factory=dict)


def _to_resp(tpl: FlowTemplate) -> TemplateResp:
    steps = tpl.steps or []
    tool_steps = [s for s in steps if s.get("action", "run_tool") == "run_tool" and s.get("slug")]
    return TemplateResp(id=tpl.id, name=tpl.name, description=tpl.description, steps=steps,
                        n_steps=len(tool_steps), graph=getattr(tpl, "graph", {}) or {})


@router.post("", response_model=TemplateResp)
async def create_template(
    body: CreateTemplateReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    steps = [s.model_dump() for s in body.steps]
    tpl = FlowTemplate(owner_id=user.id, name=body.name.strip() or "未命名流程",
                       description=body.description, steps=steps, graph=body.graph or {})
    session.add(tpl)
    await session.commit()
    await session.refresh(tpl)
    return _to_resp(tpl)


class UpdateTemplateReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[List[TemplateStep]] = None
    graph: Optional[Dict[str, Any]] = None


@router.put("/{template_id}", response_model=TemplateResp)
async def update_template(
    template_id: int,
    body: UpdateTemplateReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Edit a template — rename, re-order/add/remove steps, or change a step's
    params. The flow canvas saves through here."""
    tpl = (await session.execute(
        select(FlowTemplate).where(FlowTemplate.id == template_id, FlowTemplate.owner_id == user.id)
    )).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(404, "template not found")
    if body.name is not None:
        tpl.name = body.name.strip() or tpl.name
    if body.description is not None:
        tpl.description = body.description
    if body.steps is not None:
        tpl.steps = [s.model_dump() for s in body.steps]
    if body.graph is not None:
        tpl.graph = body.graph
    await session.commit()
    await session.refresh(tpl)
    return _to_resp(tpl)


@router.get("", response_model=List[TemplateResp])
async def list_templates(user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(
        select(FlowTemplate).where(FlowTemplate.owner_id == user.id).order_by(FlowTemplate.id.desc())
    )).scalars().all()
    return [_to_resp(t) for t in rows]


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    tpl = (await session.execute(
        select(FlowTemplate).where(FlowTemplate.id == template_id, FlowTemplate.owner_id == user.id)
    )).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(404, "template not found")
    await session.delete(tpl)
    await session.commit()
    return {"ok": True}


class RunTemplateReq(BaseModel):
    dataset_id: int
    save_result: bool = True
    # Runtime parameter overrides, keyed by step index (as a string, JSON-safe):
    # {"1": {"window": 9}}. Merged over that step's saved params before running,
    # so one template is reusable across cases without editing it. The values come
    # from the replay-time form the user fills for params marked "回放时填".
    param_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


@router.post("/{template_id}/run")
async def run_template(
    template_id: int,
    body: RunTemplateReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Replay the pipeline on a dataset: each step runs on the PREVIOUS step's
    DataFrame output (threaded), so the algorithms genuinely compose."""
    tpl = (await session.execute(
        select(FlowTemplate).where(FlowTemplate.id == template_id, FlowTemplate.owner_id == user.id)
    )).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(404, "template not found")
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")

    df = load_dataset_df(ds)
    step_results: List[Dict[str, Any]] = []
    derived_chain: List[Dict[str, Any]] = []
    parent_id, parent_name = ds.id, ds.name

    for i, step in enumerate(tpl.steps or []):
        action = step.get("action", "run_tool")
        slug = step.get("slug")
        params = {**(step.get("params", {}) or {}), **(body.param_overrides.get(str(i)) or {})}
        label = step.get("label") or slug or action
        if action != "run_tool" or not slug:
            step_results.append({"i": i, "label": label, "slug": slug, "status": "skipped",
                                 "note": "非 run_tool 步骤,已跳过"})
            continue

        if registry.get_builtin(slug):
            res = registry.execute_builtin(slug, df, params)
        else:
            row = await find_algorithm(session, slug, user.id)
            if row is None:
                step_results.append({"i": i, "label": label, "slug": slug, "status": "error",
                                     "error": f"工具未找到: {slug}（可能已删除）"})
                continue
            res = registry.execute_code(row.code, df, params)

        ok = res.get("status") == "ok"
        entry: Dict[str, Any] = {
            "i": i, "label": label, "slug": slug, "status": res.get("status", "error"),
            "error": res.get("error", ""), "rows": res.get("result_rows", 0),
            "summary": _light_summary(res.get("summary", {})),
        }
        # A DataFrame output is materialized as a lineage-tracked derived dataset.
        # But only TRANSFORMED DATA threads into the next step — a REPORT (stats /
        # correlation / sensitivity: collapses many rows to ~one-per-column) is a
        # side output and must NOT become the next step's input (that was the
        # "calculate_basic_statistics in the middle silently breaks the pipeline"
        # bug). Heuristic: an output with FEWER rows than its input AND only a
        # handful of rows (≤ max(#input-cols, 12)) is a report; everything else
        # (filters/normalize/interpolate/pca — same or more rows, or wide) threads.
        rp = res.get("result_path")
        if ok and rp:
            in_rows, in_cols = int(len(df)), int(df.shape[1])
            try:
                out_df = pd.read_parquet(rp)
            except Exception:
                out_df = None
            if out_df is not None:
                is_report = len(out_df) < in_rows and len(out_df) <= max(in_cols, 12)
                entry["report"] = is_report
                if body.save_result:
                    d = await _persist_dataset(
                        session, owner_id=user.id, df=out_df,
                        name=f"{ds.name} · {label}", filename=f"{label}.parquet",
                        file_format="derived", description=f"流程「{tpl.name}」第 {i + 1} 步:{label}"
                                    + ("（报告,不参与后续数据流）" if is_report else ""),
                        idx=i, kind="derived", derived_from=parent_id,
                        lineage={"from": parent_id, "from_name": parent_name,
                                 "op": {"slug": slug, "label": label, "params": params}},
                    )
                    entry["dataset_id"] = d.id
                    derived_chain.append({"id": d.id, "name": d.name, "label": label,
                                          "rows": d.rows, "columns": d.columns, "report": is_report})
                # Thread forward only real transformed data; a report leaves the
                # main data flow on the PRIOR stage so the next step composes on it.
                if not is_report:
                    df = out_df
                    if body.save_result and entry.get("dataset_id"):
                        parent_id, parent_name = entry["dataset_id"], f"{ds.name} · {label}"
        step_results.append(entry)

    if derived_chain:
        await session.commit()

    # Opportunistic auto-GC of OLD un-kept intermediates (this run's fresh ones
    # are inside the grace window, so they're safe). Best-effort.
    try:
        await gc_derived_datasets(session, owner_id=user.id)
    except Exception:
        pass

    return {
        "steps": step_results,
        "final": {
            "rows": int(len(df)),
            "columns": list(map(str, df.columns)),
            "preview": _df_head(df, 10),
        },
        "derived_chain": derived_chain,
        "new_dataset": derived_chain[-1] if derived_chain else None,
    }


def _light_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Trim a step summary for transport (drop big heads)."""
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
