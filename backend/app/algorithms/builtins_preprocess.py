"""Preprocessing / transform algorithms."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .registry import AlgorithmSpec, register_builtin


def _numeric_cols(df: pd.DataFrame, columns: Optional[List[str]]) -> List[str]:
    if columns:
        return columns
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


# ---------------------------------------------------------------- normalize
def _normalize(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    method: str = "minmax",
) -> pd.DataFrame:
    """method: minmax | zscore | maxabs"""
    cols = _numeric_cols(df, columns)
    out = df.copy()
    for c in cols:
        s = df[c].astype(float)
        if method == "minmax":
            lo, hi = s.min(), s.max()
            rng = hi - lo
            out[c] = (s - lo) / rng if rng else 0.0
        elif method == "zscore":
            mu, sd = s.mean(), s.std(ddof=0)
            out[c] = (s - mu) / sd if sd else 0.0
        elif method == "maxabs":
            mx = s.abs().max()
            out[c] = s / mx if mx else 0.0
        else:
            raise ValueError(f"unknown method '{method}'")
    return out


register_builtin(
    AlgorithmSpec(
        slug="normalize",
        name="Normalize / scale",
        category="preprocess",
        description="Use when columns have different units/ranges and you need them on the same scale (to compare them, or feed a model) — Min-Max, Z-score, or Max-Abs scaling.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "method": {"type": "string", "enum": ["minmax", "zscore", "maxabs"], "default": "minmax"},
        },
        returns="dataframe",
        tags=["preprocess", "scale"],
    ),
    _normalize,
)


# ---------------------------------------------------------------- fill missing
def _fill_missing(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    method: str = "linear",
    value: Optional[float] = None,
) -> pd.DataFrame:
    """method: linear | ffill | bfill | mean | median | value"""
    cols = _numeric_cols(df, columns)
    out = df.copy()
    for c in cols:
        s = out[c]
        if method == "linear":
            out[c] = s.interpolate(method="linear", limit_direction="both")
        elif method == "ffill":
            out[c] = s.ffill()
        elif method == "bfill":
            out[c] = s.bfill()
        elif method == "mean":
            out[c] = s.fillna(s.mean())
        elif method == "median":
            out[c] = s.fillna(s.median())
        elif method == "value":
            if value is None:
                raise ValueError("method=value requires the 'value' parameter")
            out[c] = s.fillna(value)
        else:
            raise ValueError(f"unknown method '{method}'")
    return out


register_builtin(
    AlgorithmSpec(
        slug="fill_missing",
        name="Fill missing values",
        category="preprocess",
        description="Use when the data has missing / blank values (gaps, dropped readings) you need to fill in sensibly — linear / ffill / bfill / mean / median / constant imputation.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "method": {
                "type": "string",
                "enum": ["linear", "ffill", "bfill", "mean", "median", "value"],
                "default": "linear",
            },
            "value": {"type": "number", "required": False},
        },
        returns="dataframe",
        tags=["preprocess", "missing", "imputation"],
    ),
    _fill_missing,
)


# ---------------------------------------------------------------- outlier detection
def _outliers(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    method: str = "iqr",
    iqr_k: float = 1.5,
    z_threshold: float = 3.0,
) -> pd.DataFrame:
    """Add an `<col>_outlier` boolean column for each selected column.

    Methods:
      - iqr    : Tukey's fences (default, robust)
      - zscore : |z| > threshold
      - dixon  : Dixon's Q test for small samples (n in [3, 30])
    """
    cols = _numeric_cols(df, columns)
    out = df.copy()

    def _dixon(values: np.ndarray) -> np.ndarray:
        flags = np.zeros(len(values), dtype=bool)
        n = len(values)
        if n < 3 or n > 30:
            return flags
        # Conservative critical values for Q at 95% confidence, n=3..30
        Q95 = {3: 0.970, 4: 0.829, 5: 0.710, 6: 0.625, 7: 0.568, 8: 0.526, 9: 0.493,
               10: 0.466, 11: 0.444, 12: 0.426, 13: 0.410, 14: 0.396, 15: 0.384,
               16: 0.374, 17: 0.365, 18: 0.356, 19: 0.349, 20: 0.342, 21: 0.337,
               22: 0.331, 23: 0.326, 24: 0.321, 25: 0.317, 26: 0.312, 27: 0.308,
               28: 0.305, 29: 0.301, 30: 0.290}
        crit = Q95.get(n, 0.290)
        order = np.argsort(values)
        sorted_vals = values[order]
        rng = sorted_vals[-1] - sorted_vals[0]
        if rng == 0:
            return flags
        q_low = (sorted_vals[1] - sorted_vals[0]) / rng
        q_high = (sorted_vals[-1] - sorted_vals[-2]) / rng
        if q_low > crit:
            flags[order[0]] = True
        if q_high > crit:
            flags[order[-1]] = True
        return flags

    for c in cols:
        s = out[c].astype(float)
        arr = s.to_numpy()
        if method == "iqr":
            q1, q3 = np.nanpercentile(arr, 25), np.nanpercentile(arr, 75)
            iqr = q3 - q1
            lo, hi = q1 - iqr_k * iqr, q3 + iqr_k * iqr
            out[f"{c}_outlier"] = (arr < lo) | (arr > hi)
        elif method == "zscore":
            mu = np.nanmean(arr)
            sd = np.nanstd(arr)
            z = (arr - mu) / (sd if sd > 0 else 1.0)
            out[f"{c}_outlier"] = np.abs(z) > z_threshold
        elif method == "dixon":
            out[f"{c}_outlier"] = _dixon(arr[~np.isnan(arr)])
            if out[f"{c}_outlier"].dtype != bool:
                out[f"{c}_outlier"] = out[f"{c}_outlier"].astype(bool)
        else:
            raise ValueError(f"unknown method '{method}'")
    return out


register_builtin(
    AlgorithmSpec(
        slug="outlier_detect",
        name="Outlier detection",
        category="preprocess",
        description="Use to find abnormal / bad data points (sensor glitches, recording errors) before they corrupt downstream results — flags outliers per column via Tukey IQR, Z-score, or Dixon's Q-test.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "method": {"type": "string", "enum": ["iqr", "zscore", "dixon"], "default": "iqr"},
            "iqr_k": {"type": "number", "default": 1.5},
            "z_threshold": {"type": "number", "default": 3.0},
        },
        returns="dataframe",
        tags=["preprocess", "outlier", "quality"],
    ),
    _outliers,
)


# ---------------------------------------------------------------- prep
def _prep(df: pd.DataFrame, *, drop_na: bool = True, drop_dup: bool = True) -> pd.DataFrame:
    out = df.copy()
    if drop_dup:
        out = out.drop_duplicates()
    if drop_na:
        out = out.dropna()
    return out.reset_index(drop=True)


register_builtin(
    AlgorithmSpec(
        slug="data_prep",
        name="Data preparation",
        category="preprocess",
        description="Use to tidy a messy table first — drops duplicate rows and/or rows with missing values, then resets the index.",
        params_schema={
            "drop_na": {"type": "boolean", "default": True},
            "drop_dup": {"type": "boolean", "default": True},
        },
        returns="dataframe",
        tags=["preprocess", "cleaning"],
    ),
    _prep,
)
