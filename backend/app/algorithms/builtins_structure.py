"""Structural & columnar operations."""

from __future__ import annotations

import ast
import re
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
# Functions the fallback evaluator exposes. Casting matters most: pandas' eval
# has no `int()`, so "make an integer channel number out of a string field" —
# a completely ordinary request — used to be impossible here, and the agent
# would retry the same rejected expression until the circuit-breaker fired.
_SAFE_FUNCS: Dict[str, Any] = {
    "int": lambda s: (pd.to_numeric(s, errors="coerce").astype("Int64")
                      if isinstance(s, pd.Series) else int(s)),
    "float": lambda s: (pd.to_numeric(s, errors="coerce").astype(float)
                        if isinstance(s, pd.Series) else float(s)),
    "str": lambda s: (s.astype(str) if isinstance(s, pd.Series) else str(s)),
    "round": lambda s, n=0: np.round(s, int(n)),
    "abs": np.abs, "sqrt": np.sqrt, "exp": np.exp, "log": np.log, "log10": np.log10,
    "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "floor": np.floor, "ceil": np.ceil, "sign": np.sign,
    "min": np.minimum, "max": np.maximum, "where": np.where,
}

_SAFE_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _safe_eval(expression: str, df: pd.DataFrame):
    """Whitelist-only evaluator: arithmetic/comparison over columns plus the
    functions in `_SAFE_FUNCS`. Walks the AST and REJECTS anything not
    explicitly allowed — no attribute access, no subscripting, no name that
    isn't a column or a whitelisted function, so there is no route to an
    import, a dunder, or an arbitrary call."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str, bool)):
                return node.value
            raise ValueError("unsupported constant")
        if isinstance(node, ast.Name):
            if node.id in df.columns:
                return df[node.id]
            if node.id in _SAFE_FUNCS:
                return _SAFE_FUNCS[node.id]
            raise ValueError(f"unknown name '{node.id}' — not a column of this data")
        if isinstance(node, ast.BinOp) and isinstance(node.op, _SAFE_BINOPS):
            l, r = ev(node.left), ev(node.right)
            return {
                ast.Add: lambda: l + r, ast.Sub: lambda: l - r, ast.Mult: lambda: l * r,
                ast.Div: lambda: l / r, ast.FloorDiv: lambda: l // r,
                ast.Mod: lambda: l % r, ast.Pow: lambda: l ** r,
            }[type(node.op)]()
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return +v
            if isinstance(node.op, ast.Not):
                return ~v if isinstance(v, pd.Series) else (not v)
            raise ValueError("unsupported unary operator")
        if isinstance(node, ast.Compare):
            # Chains like `0 <= alpha_deg <= 12` = pairwise comparisons AND-ed together.
            def cmp(op, l, r):
                for t, fn in ((ast.Eq, lambda: l == r), (ast.NotEq, lambda: l != r),
                              (ast.Lt, lambda: l < r), (ast.LtE, lambda: l <= r),
                              (ast.Gt, lambda: l > r), (ast.GtE, lambda: l >= r)):
                    if isinstance(op, t):
                        return fn()
                raise ValueError("unsupported comparison")
            left = ev(node.left)
            acc = None
            for op, comp in zip(node.ops, node.comparators):
                right = ev(comp)
                part = cmp(op, left, right)
                acc = part if acc is None else (acc & part)
                left = right
            return acc
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            acc = vals[0]
            for v in vals[1:]:
                acc = (acc & v) if isinstance(node.op, ast.And) else (acc | v)
            return acc
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCS:
                raise ValueError(
                    f"function not allowed here. supported: {', '.join(sorted(_SAFE_FUNCS))}"
                )
            if node.keywords:
                raise ValueError("keyword arguments are not supported")
            return _SAFE_FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"unsupported expression element: {type(node).__name__}")

    return ev(ast.parse(expression, mode="eval"))


_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _derived_column(df: pd.DataFrame, *, name: str, expression: str) -> pd.DataFrame:
    """Evaluate an expression in the context of the existing columns.

    `_safe_eval` is the ONLY evaluator. pandas' `eval` used to run first, on the
    belief that its DSL forbids attribute access — it does not. `q.to_csv('…')`
    evaluated happily and WROTE THE FILE, so any caller of this tool (the chat
    agent, or any authenticated user via the run-algorithm API) could write to
    an arbitrary path the server process can reach. The `__`/import token
    blacklist never saw it: no dunder is involved. Blacklisting tokens on a
    permissive evaluator is the wrong shape of defence; the AST whitelist —
    which has no rule for Attribute or Subscript and so rejects them by
    construction — is the right one.

    It also fixes the capability gap that surfaced this: pandas eval has no
    `int()`, and the bare "'int' is not a supported function" gave the agent
    nothing to act on, so it re-sent the same expression until the breaker
    fired. The error now names every supported function and column.

    Columns whose names aren't Python identifiers are still reachable with
    pandas' backtick syntax (`` `my col` ``); they're aliased before parsing.
    """
    if not name or not name.isidentifier():
        raise ValueError("name must be a valid identifier")
    out = df.copy()

    # `col name` → __c0 alias, so non-identifier columns stay usable.
    aliases: Dict[str, Any] = {}
    frame = out

    def _alias(m: "re.Match[str]") -> str:
        col = m.group(1)
        key = f"bt_{len(aliases)}"
        aliases[key] = col
        return key

    expr = _BACKTICK_RE.sub(_alias, expression)
    if aliases:
        frame = out.rename(columns={v: k for k, v in aliases.items()})

    try:
        out[name] = _safe_eval(expr, frame)
    except Exception as err:
        raise ValueError(
            f"could not evaluate expression `{expression}`: {err}. "
            f"supported functions: {', '.join(sorted(_SAFE_FUNCS))}. "
            f"columns available: {', '.join(str(c) for c in df.columns)}."
        ) from err
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


# ---------------------------------------------------------------- bin a column
def _bin_column(
    df: pd.DataFrame,
    *,
    column: str,
    bins: int = 5,
    method: str = "quantile",
    name: Optional[str] = None,
) -> pd.DataFrame:
    """Cut a continuous column into ordered bands, so it can be grouped by.

    "按网格质量分档统计残差" is an everyday request and there was no tool for it:
    the agent's only option was to group by the raw continuous column, which
    yields one group per row. `quantile` gives equal-COUNT bands (每档样本数相
    等,适合分布很偏的数据); `uniform` gives equal-WIDTH bands.
    """
    if column not in df.columns:
        raise ValueError(f"column not found: {column}. available: {list(df.columns)}")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise ValueError(f"column '{column}' is not numeric — nothing to bin")
    bins = int(bins)
    if not 2 <= bins <= 50:
        raise ValueError("bins must be between 2 and 50")
    out = df.copy()
    target = name or f"{column}_bin"
    series = out[column]
    if method == "uniform":
        cat = pd.cut(series, bins=bins, duplicates="drop")
    elif method == "quantile":
        cat = pd.qcut(series, q=bins, duplicates="drop")
    else:
        raise ValueError("method must be 'quantile' or 'uniform'")
    # A readable, SORTABLE label: "1: (0.148, 0.62]" keeps the band order in any
    # later group-by / plot instead of scrambling it alphabetically.
    codes = cat.cat.codes
    labels = {i: f"{i + 1}: {iv}" for i, iv in enumerate(cat.cat.categories)}
    out[target] = codes.map(lambda c: labels.get(c, "NA"))
    return out


register_builtin(
    AlgorithmSpec(
        slug="bin_column",
        name="Bin a continuous column",
        category="structure",
        description=(
            "Use BEFORE grouping by a continuous quantity — cut it into ordered bands "
            "(分档/分箱) so group_aggregate has something to group on. "
            "'quantile' = equal count per band, 'uniform' = equal width."
        ),
        params_schema={
            "column": {"type": "string", "required": True},
            "bins": {"type": "integer", "default": 5, "minimum": 2, "maximum": 50},
            "method": {"type": "string", "default": "quantile", "enum": ["quantile", "uniform"]},
            "name": {"type": "string", "required": False,
                     "description": "output column name (default <column>_bin)"},
        },
        returns="dataframe",
        tags=["structure", "bin", "分档"],
        aliases=["cut", "bucket", "discretize", "bin"],
    ),
    _bin_column,
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

    # Grouping by a CONTINUOUS column silently does nothing: 69328 mesh cells
    # grouped by Orthogonal_Quality (68542 distinct values) returned 69328 rows
    # — one group per row — and the answer still claimed the data had been
    # "分档统计". Refuse it, and say exactly how to fix it, because the tool that
    # does fix it (bin_column) is one call away.
    if len(df) >= 20:
        n_groups = int(df.groupby(by, dropna=False).ngroups)
        if n_groups > 0.5 * len(df):
            raise ValueError(
                f"分组键 {by} 有 {n_groups} 个不同取值、而数据只有 {len(df)} 行 —— "
                f"这样分组等于每行一组,不会产生任何汇总。"
                f"这些列是连续值,不能直接当分组键:请先用 `bin_column` 把它分成若干档"
                f"(例如 bins=5),再按生成的档位列分组。"
            )

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
                "values": "array",  # each value is a LIST of func names — see _coerce_params
                "required": True,
                "description": "Mapping of column → list of aggregation function names",
            },
        },
        returns="dataframe",
        tags=["structure", "aggregate"],
    ),
    _group_aggregate,
)


# ---------------------------------------------------------------- filter rows by a condition
def _filter_rows(df: pd.DataFrame, *, condition: str) -> pd.DataFrame:
    """Keep the rows where `condition` holds, e.g. `alpha_deg >= 0 and alpha_deg <= 12`
    or `0 <= alpha_deg <= 12`. Same whitelist evaluator as derived_column."""
    if not condition or not str(condition).strip():
        raise ValueError("参数 condition 不能为空，例如 alpha_deg >= 0 and alpha_deg <= 12")
    aliases: Dict[str, Any] = {}

    def _alias(m: "re.Match[str]") -> str:
        key = f"bt_{len(aliases)}"
        aliases[key] = m.group(1)
        return key

    expr = _BACKTICK_RE.sub(_alias, condition)
    frame = df
    if aliases:
        frame = df.rename(columns={v: k for k, v in aliases.items()})
    try:
        mask = _safe_eval(expr, frame)
    except Exception as err:
        raise ValueError(
            f"条件「{condition}」没法计算：{err}。可用的列：{', '.join(str(c) for c in df.columns)}。"
        ) from err
    if not isinstance(mask, pd.Series):
        raise ValueError(f"条件「{condition}」没有用到任何列，算出来是一个固定值，不能用来筛选行。")
    out = df[mask.fillna(False).astype(bool)].reset_index(drop=True)
    if out.empty:
        ranges = [f"{c} ∈ [{df[c].min():g}, {df[c].max():g}]" for c in df.columns
                  if pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().any()][:8]
        raise ValueError(f"条件「{condition}」把所有行都筛掉了。各数值列的范围：{'；'.join(ranges) or '（没有数值列）'}。")
    return out


register_builtin(
    AlgorithmSpec(
        slug="filter_rows",
        name="Filter rows",
        category="preprocess",
        description="Use to keep only the rows that satisfy a condition — e.g. a range of one column (`0 <= alpha_deg <= 12`), "
                    "or several conditions joined with and/or. Run it BEFORE fitting / summarizing a sub-range.",
        params_schema={
            "condition": {"type": "string", "required": True,
                          "description": "Row condition over column names, e.g. `alpha_deg >= 0 and alpha_deg <= 12`"},
        },
        returns="dataframe",
        tags=["preprocess", "filter", "subset"],
        aliases=["filter", "select_rows", "subset_rows", "row_filter"],
    ),
    _filter_rows,
)


# ---------------------------------------------------------------- align two datasets on a key column
def _align_datasets(df: pd.DataFrame, *, other: Any, on: Any, columns: Optional[List[str]] = None,
                    how: str = "inner") -> pd.DataFrame:
    """Join the input (A) with a second dataset (B) on key column(s). Each compared
    column appears twice: `<col>_A` and `<col>_B`. `other` is a dataset name / id that
    the caller has already loaded into a DataFrame (param type "dataset")."""
    if not isinstance(other, pd.DataFrame):
        raise ValueError(f"参数 other 要填第二份数据的名称或编号：没有找到「{other}」这份数据。")
    keys = [on] if isinstance(on, str) else list(on or [])
    if not keys:
        raise ValueError("参数 on 不能为空：填两份数据共有的对齐列，例如 alpha_deg")
    for k in keys:
        if k not in df.columns or k not in other.columns:
            side = "第一份" if k not in df.columns else "第二份"
            raise ValueError(f"对齐列「{k}」在{side}数据里不存在。两份数据共有的列：{', '.join(c for c in df.columns if c in other.columns) or '（没有）'}。")
    shared = [c for c in df.columns if c in other.columns and c not in keys]
    cols = list(columns) if columns else shared
    missing = [c for c in cols if c not in df.columns or c not in other.columns]
    if missing:
        raise ValueError(f"列「{'、'.join(missing)}」不是两份数据都有。两份数据共有的列：{', '.join(shared) or '（没有）'}。")
    if how not in ("inner", "outer", "left"):
        raise ValueError("参数 how 只能是 inner（只保留两边都有的点）、outer 或 left")
    a = df[keys + cols].rename(columns={c: f"{c}_A" for c in cols})
    b = other[keys + cols].rename(columns={c: f"{c}_B" for c in cols})
    out = pd.merge(a, b, on=keys, how=how)
    if out.empty:
        raise ValueError(f"两份数据在「{'、'.join(keys)}」上没有一个相同的值，对不齐。检查对齐列的取值是否一致（例如单位、小数位）。")
    order = keys + [f"{c}_{s}" for c in cols for s in ("A", "B")]
    return out[order].sort_values(keys).reset_index(drop=True)


register_builtin(
    AlgorithmSpec(
        slug="align_datasets",
        name="Align two datasets",
        category="structure",
        description="Use to COMPARE TWO DATASETS point by point (重复性 / 两次试验 / 两个版本): joins the input with a second dataset "
                    "on a key column (e.g. alpha_deg); every compared column comes out as <col>_A (input) and <col>_B (other). "
                    "Then compute differences with derived_column (e.g. dCL = CL_A - CL_B) and segment them with bin_column + group_aggregate.",
        params_schema={
            "other": {"type": "dataset", "required": True, "description": "Name (or id) of the second dataset"},
            "on": {"type": "string", "required": True, "description": "Key column present in both, e.g. alpha_deg"},
            "columns": {"type": "array", "items": "string", "required": False,
                        "description": "Columns to compare; default = all columns the two share"},
            "how": {"type": "string", "default": "inner", "enum": ["inner", "outer", "left"], "required": False},
        },
        returns="dataframe",
        tags=["structure", "compare", "join"],
        aliases=["merge_datasets", "join_datasets", "compare_datasets"],
    ),
    _align_datasets,
)
