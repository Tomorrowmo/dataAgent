"""Parameters of type "dataset": a built-in that needs a SECOND table (e.g.
align_datasets) declares a param `{"type": "dataset"}` whose value is a dataset
name or id. Callers resolve those to DataFrames right before running — the
run record keeps the plain name / id, so a re-run fetches the data again.

Only the caller's own, not-cleaned datasets are searched. Unknown names are
left as-is; the algorithm then raises a plain message naming the value.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Dataset


def dataset_param_names(slug: str) -> list[str]:
    from ..algorithms import registry
    spec = registry.get_builtin(slug)
    if not spec:
        return []
    return [n for n, ps in (spec.params_schema or {}).items() if isinstance(ps, dict) and ps.get("type") == "dataset"]


async def find_dataset(session: AsyncSession, owner_id: int, ref: Any) -> Dataset | None:
    """By id (int or digit string), else by exact name — newest active one wins."""
    rows = []
    if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
        rows = (await session.execute(select(Dataset).where(
            Dataset.id == int(ref), Dataset.owner_id == owner_id))).scalars().all()
    if not rows and isinstance(ref, str) and ref.strip():
        rows = (await session.execute(select(Dataset).where(
            Dataset.name == ref.strip(), Dataset.owner_id == owner_id).order_by(Dataset.id.desc()))).scalars().all()
    rows = [d for d in rows if (d.state or "active") != "cleaned"]
    return rows[0] if rows else None


async def resolve_dataset_params(session: AsyncSession, owner_id: int, slug: str,
                                 params: Dict[str, Any] | None) -> Dict[str, Any]:
    """{param name: DataFrame} for every dataset-typed param that resolves.
    Pass the result to registry.execute_builtin(..., frames=...)."""
    names = dataset_param_names(slug)
    if not names:
        return {}
    from .datasets import load_dataset_df
    out: Dict[str, Any] = {}
    for n in names:
        ref = (params or {}).get(n)
        if ref in (None, ""):
            continue
        ds = await find_dataset(session, owner_id, ref)
        if ds is None:
            continue
        try:
            out[n] = load_dataset_df(ds)
        except FileNotFoundError:
            continue
    return out
