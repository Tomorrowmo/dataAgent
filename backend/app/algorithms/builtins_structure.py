"""Structural & columnar operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .registry import AlgorithmSpec, register_builtin


# ---------------------------------------------------------------- transpose
def _transpose(df: pd.DataFrame, *, set_index: Optional[str] = None) -> pd.DataFrame:
    if set_index:
        if set_index not in df.columns:
            raise ValueError(f"set_index column not found: {set_index}")
        out = df.set_index(set_index).T.reset_index().rename(columns={"index": "variable"})
    else:
        out = df.T.reset_index().rename(columns={"index": "variable"})
    out.columns = [str(c) for c in out.columns]
    return out


register_builtin(
    AlgorithmSpec(
        slug="transpose",
        name="Transpose",
        category="structure",
        description="Use to flip a table's orientation (rows↔columns), e.g. wide↔long — optionally set a column as the new header.",
        params_schema={"set_index": {"type": "string", "required": False}},
        returns="dataframe",
        tags=["structure"],
    ),
    _transpose,
)


# ---------------------------------------------------------------- derived column from expression
def _derived_column(df: pd.DataFrame, *, name: str, expression: str) -> pd.DataFrame:
    """Evaluate a pandas expression in the context of the existing columns.

    Safety: pandas' `eval` engine accepts a constrained DSL (no attribute access,
    no calls, no `__`); it's the right tool here.
    """
    if not name or not name.isidentifier():
        raise ValueError("name must be a valid identifier")
    if any(b in expression for b in ("__", "import", "open(", "exec(", "eval(")):
        raise ValueError("expression contains forbidden token")
    out = df.copy()
    out[name] = out.eval(expression)
    return out


register_builtin(
    AlgorithmSpec(
        slug="derived_column",
        name="Expression-derived column",
        category="structure",
        description="Use to compute a new column from existing ones with a formula (e.g. `(price * qty) / tax`) — derive a metric, unit-convert, combine columns.",
        params_schema={
            "name": {"type": "string", "required": True},
            "expression": {"type": "string", "required": True},
        },
        returns="dataframe",
        tags=["structure", "derive"],
    ),
    _derived_column,
)


# ---------------------------------------------------------------- drop columns
def _drop_columns(df: pd.DataFrame, *, columns: List[str]) -> pd.DataFrame:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"columns not found: {missing}")
    return df.drop(columns=columns)


register_builtin(
    AlgorithmSpec(
        slug="drop_columns",
        name="Drop columns",
        category="structure",
        description="Use to drop columns you don't need (irrelevant, redundant, or sensitive) from the table.",
        params_schema={"columns": {"type": "array", "items": "string", "required": True}},
        returns="dataframe",
        tags=["structure"],
    ),
    _drop_columns,
)


# ---------------------------------------------------------------- group aggregate
def _group_aggregate(
    df: pd.DataFrame,
    *,
    by: List[str],
    agg: Dict[str, List[str]],
) -> pd.DataFrame:
    """`by`: grouping columns. `agg`: {column: [funcs]} where funcs ∈ mean,median,sum,min,max,std,var,count."""
    allowed = {"mean", "median", "sum", "min", "max", "std", "var", "count", "first", "last"}
    for col, funcs in agg.items():
        for f in funcs:
            if f not in allowed:
                raise ValueError(f"agg func '{f}' not allowed. choose from {allowed}")
    grouped = df.groupby(by).agg(agg)
    grouped.columns = [f"{col}_{f}" for col, f in grouped.columns]
    return grouped.reset_index()


register_builtin(
    AlgorithmSpec(
        slug="group_aggregate",
        name="Group & aggregate",
        category="structure",
        description="Use to summarize data by category — group rows by one or more columns and apply mean/median/sum/min/max/std/var/count per column.",
        params_schema={
            "by": {"type": "array", "items": "string", "required": True},
            "agg": {
                "type": "object",
                "required": True,
                "description": "Mapping of column → list of aggregation function names",
            },
        },
        returns="dataframe",
        tags=["structure", "aggregate"],
    ),
    _group_aggregate,
)
