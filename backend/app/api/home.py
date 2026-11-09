"""Home-page example questions (改进清单-4 · 第 3 步).

All users read the same config; only administrators change it. A question the
admin adds may carry an example result COPIED from one of the admin's own runs
(a snapshot): run results are owner-scoped (第 0 步), so other users could not
read the original file, and a copy also survives the run being cleaned.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AppSetting, Dataset, Run, RunGroup, User
from .deps import current_user, get_db

router = APIRouter(prefix="/home", tags=["home"])

KEY = "home_examples"
MAX_TABS = 8
MAX_QUESTIONS = 12
MAX_BYTES = 200_000
MAX_POINTS = 500


def _admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(403, "only an administrator can change the home examples")


@router.get("/examples")
async def get_examples(user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    """`{"tabs": null}` means "not configured" — the client shows its built-in defaults."""
    row = await session.get(AppSetting, KEY)
    if row is None or not row.value:
        return {"tabs": None}
    try:
        return json.loads(row.value)
    except ValueError:
        return {"tabs": None}


# ── validation ────────────────────────────────────────────────────────────

class Kpi(BaseModel):
    label: str = Field(max_length=40)
    value: str = Field(max_length=40)
    unit: Optional[str] = Field(default=None, max_length=16)
    note: Optional[str] = Field(default=None, max_length=60)


class Series(BaseModel):
    name: str = Field(max_length=80)
    values: List[Optional[float]]


class Snapshot(BaseModel):
    title: str = Field(max_length=80)
    code: Optional[str] = Field(default=None, max_length=40)
    x: Series
    ys: List[Series] = Field(min_length=1, max_length=3)
    chain: List[str] = Field(default_factory=list, max_length=12)
    run_id: Optional[int] = None


class Question(BaseModel):
    id: str = Field(max_length=40)
    text: str = Field(min_length=1, max_length=120)
    needs: Optional[str] = Field(default=None, max_length=120)
    builtin_key: Optional[str] = Field(default=None, max_length=40)
    samples: Optional[List[str]] = Field(default=None, max_length=4)
    snapshot: Optional[Snapshot] = None
    kpis: Optional[List[Kpi]] = Field(default=None, max_length=4)
    methods: Optional[str] = Field(default=None, max_length=120)
    hidden: bool = False


class Tab(BaseModel):
    id: str = Field(max_length=40)
    name: str = Field(min_length=1, max_length=20)
    hidden: bool = False
    questions: List[Question] = Field(max_length=MAX_QUESTIONS)


class ExamplesReq(BaseModel):
    tabs: Optional[List[Tab]] = Field(default=None, max_length=MAX_TABS)


@router.put("/examples")
async def put_examples(body: ExamplesReq, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    """Save the config; `{"tabs": null}` restores the built-in defaults."""
    _admin(user)
    row = await session.get(AppSetting, KEY)
    if body.tabs is None:
        if row is not None:
            await session.delete(row)
            await session.commit()
        return {"tabs": None}
    for t in body.tabs:
        for q in t.questions:
            if q.snapshot is not None and any(len(s.values) != len(q.snapshot.x.values) for s in q.snapshot.ys):
                raise HTTPException(400, f"「{q.text}」的示例结果数据长度不一致")
    value = json.dumps(body.model_dump(exclude_none=True), ensure_ascii=False, separators=(",", ":"))
    if len(value.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(400, f"配置过大（{len(value.encode('utf-8')) // 1000} KB，上限 {MAX_BYTES // 1000} KB），请减少示例结果")
    if row is None:
        session.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
    await session.commit()
    return json.loads(value)


# ── picking an example result from the admin's own runs ──────────────────

async def _result_df(session: AsyncSession, run: Run, owner_id: int) -> Optional[pd.DataFrame]:
    """The run's output table, if it produced one and it is still on disk."""
    if run.result_dataset_id:
        ds = await session.get(Dataset, run.result_dataset_id)
        if ds is not None and ds.owner_id == owner_id and getattr(ds, "state", "active") != "cleaned":
            from ..services.datasets import load_dataset_df
            try:
                return load_dataset_df(ds)
            except Exception:
                pass
    if run.artifact_id:
        from ..services.artifacts import file_of, get_owned
        a = await get_owned(session, run.artifact_id, owner_id)
        if a is not None:
            try:
                return pd.read_parquet(file_of(a))
            except Exception:
                pass
    return None


def _numeric_cols(df: pd.DataFrame) -> List[str]:
    return [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


@router.get("/examples/runs")
async def example_runs(user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    """The admin's recent runs that produced a table, with their numeric columns."""
    _admin(user)
    from ..services.runs import run_code
    rows = (await session.execute(
        select(Run, RunGroup).join(RunGroup, RunGroup.id == Run.group_id)
        .where(Run.owner_id == user.id, Run.status == "ok")
        .order_by(Run.id.desc()).limit(80)
    )).all()
    out: List[Dict[str, Any]] = []
    for run, g in rows:
        if not (run.result_dataset_id or run.artifact_id):
            continue
        df = await _result_df(session, run, user.id)
        if df is None:
            continue
        cols = _numeric_cols(df)
        if len(cols) < 2:
            continue
        out.append({"id": run.id, "code": run_code(g, run), "slug": run.algorithm_slug, "label": run.label,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "rows": int(len(df)), "columns": cols})
        if len(out) >= 30:
            break
    return out


class SnapshotReq(BaseModel):
    run_id: int
    x: str
    ys: List[str] = Field(min_length=1, max_length=3)
    title: Optional[str] = Field(default=None, max_length=80)


def _thin(n: int) -> np.ndarray:
    return np.arange(n) if n <= MAX_POINTS else np.unique(np.linspace(0, n - 1, MAX_POINTS).round().astype(int))


def _vals(s: pd.Series) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for v in pd.to_numeric(s, errors="coerce").tolist():
        out.append(None if v is None or not np.isfinite(v) else float(round(v, 6)))
    return out


@router.post("/examples/snapshot")
async def example_snapshot(body: SnapshotReq, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    _admin(user)
    run = await session.get(Run, body.run_id)
    if run is None or run.owner_id != user.id:
        raise HTTPException(404, "运行记录不存在")
    df = await _result_df(session, run, user.id)
    if df is None:
        raise HTTPException(409, "这条运行记录的结果已不可用（可能已被清理）")
    missing = [c for c in [body.x, *body.ys] if c not in df.columns]
    if missing:
        raise HTTPException(400, f"列不存在：{', '.join(missing)}")
    sub = df[[body.x, *body.ys]].copy()
    sub = sub.iloc[_thin(len(sub))]
    g = await session.get(RunGroup, run.group_id)
    from ..services.runs import root_name, run_code
    # 处理链路: input → each step of the batch up to this run.
    chain: List[str] = []
    if run.dataset_id:
        ds = await session.get(Dataset, run.dataset_id)
        if ds is not None:
            chain.append(await root_name(session, ds))
    steps = (await session.execute(
        select(Run).where(Run.group_id == run.group_id, Run.seq <= run.seq).order_by(Run.seq)
    )).scalars().all()
    for st in steps:
        label = st.algorithm_slug + (f" v{st.algorithm_version}" if st.algorithm_version else "")
        ps = ", ".join(f"{k}={v}" for k, v in list((st.params or {}).items())[:3] if not isinstance(v, (list, dict)))
        chain.append(f"{label} {ps}".strip()[:60])
    return {
        "title": (body.title or run.label or run.algorithm_slug)[:80],
        "code": run_code(g, run) if g else None,
        "x": {"name": body.x, "values": _vals(sub[body.x])},
        "ys": [{"name": c, "values": _vals(sub[c])} for c in body.ys],
        "chain": chain[:12],
        "run_id": run.id,
    }
