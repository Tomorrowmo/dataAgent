"""Regression & fitting algorithms."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .registry import AlgorithmSpec, register_builtin


def _require_cols(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}. available: {list(df.columns)}")


# ---------------------------------------------------------------- linear regression
def _linear_regression(df: pd.DataFrame, *, x: List[str], y: str, fit_intercept: bool = True) -> Dict[str, Any]:
    from sklearn.linear_model import LinearRegression

    _require_cols(df, x + [y])
    sub = df[x + [y]].dropna()
    model = LinearRegression(fit_intercept=fit_intercept)
    model.fit(sub[x].values, sub[y].values)
    yhat = model.predict(sub[x].values)
    ss_res = float(np.sum((sub[y].values - yhat) ** 2))
    ss_tot = float(np.sum((sub[y].values - sub[y].mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rmse = float(np.sqrt(ss_res / len(sub))) if len(sub) else float("nan")
    return {
        "coefficients": {xi: float(c) for xi, c in zip(x, model.coef_)},
        "intercept": float(model.intercept_),
        "r_squared": r2,
        "rmse": rmse,
        "n_samples": int(len(sub)),
    }


register_builtin(
    AlgorithmSpec(
        slug="linear_regression",
        name="Linear regression",
        category="regression",
        description="Use to find how an output is driven by several inputs together (linearly), how much each weighs, and to predict it — ordinary least squares; returns coefficients, R² and RMSE.",
        params_schema={
            "x": {"type": "array", "items": "string", "required": True, "description": "Feature column(s)"},
            "y": {"type": "string", "required": True, "description": "Target column"},
            "fit_intercept": {"type": "boolean", "default": True},
        },
        returns="dict",
        tags=["regression", "fit"],
    ),
    _linear_regression,
)


# ---------------------------------------------------------------- polynomial regression
def _poly_regression(df: pd.DataFrame, *, x: str, y: str, degree: int = 2) -> Dict[str, Any]:
    _require_cols(df, [x, y])
    sub = df[[x, y]].dropna()
    coeffs = np.polyfit(sub[x].values, sub[y].values, deg=degree)
    yhat = np.polyval(coeffs, sub[x].values)
    ss_res = float(np.sum((sub[y].values - yhat) ** 2))
    ss_tot = float(np.sum((sub[y].values - sub[y].mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "coefficients": [float(c) for c in coeffs],
        "degree": int(degree),
        "r_squared": r2,
        "rmse": float(np.sqrt(ss_res / len(sub))),
        "n_samples": int(len(sub)),
    }


register_builtin(
    AlgorithmSpec(
        slug="polynomial_regression",
        name="Polynomial regression",
        category="regression",
        description="Use when one quantity varies with another along a curve (not a straight line) and you want to fit that trend — polynomial least-squares of degree N.",
        params_schema={
            "x": {"type": "string", "required": True},
            "y": {"type": "string", "required": True},
            "degree": {"type": "integer", "default": 2, "minimum": 1, "maximum": 10},
        },
        returns="dict",
        tags=["regression", "fit"],
    ),
    _poly_regression,
)


# ---------------------------------------------------------------- curve fit
def _curve_fit(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    model: str = "exponential",
    p0: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Fit common closed-form models: exponential | logarithmic | power | sigmoid."""
    from scipy.optimize import curve_fit

    _require_cols(df, [x, y])
    sub = df[[x, y]].dropna()
    xv, yv = sub[x].values.astype(float), sub[y].values.astype(float)

    def exponential(t, a, b, c):
        return a * np.exp(b * t) + c

    def logarithmic(t, a, b):
        return a * np.log(np.abs(t) + 1e-12) + b

    def power(t, a, b):
        return a * np.power(np.abs(t) + 1e-12, b)

    def sigmoid(t, a, b, c, d):
        return a / (1 + np.exp(-b * (t - c))) + d

    fmap = {
        "exponential": (exponential, [1.0, 0.01, 0.0]),
        "logarithmic": (logarithmic, [1.0, 0.0]),
        "power": (power, [1.0, 1.0]),
        "sigmoid": (sigmoid, [float(yv.max() - yv.min()), 1.0, float(np.median(xv)), float(yv.min())]),
    }
    if model not in fmap:
        raise ValueError(f"unknown model '{model}'. choose from {list(fmap)}")
    fn, default_p0 = fmap[model]
    popt, _ = curve_fit(fn, xv, yv, p0=p0 or default_p0, maxfev=10000)
    yhat = fn(xv, *popt)
    ss_res = float(np.sum((yv - yhat) ** 2))
    ss_tot = float(np.sum((yv - yv.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "model": model,
        "parameters": [float(p) for p in popt],
        "r_squared": r2,
        "rmse": float(np.sqrt(ss_res / len(sub))),
        "n_samples": int(len(sub)),
    }


register_builtin(
    AlgorithmSpec(
        slug="curve_fit",
        name="Non-linear curve fit",
        category="regression",
        description="Use when the data follows a known shape — exponential growth/decay, logarithmic, power-law, or S-shaped saturation — and you want the fitted parameters.",
        params_schema={
            "x": {"type": "string", "required": True},
            "y": {"type": "string", "required": True},
            "model": {"type": "string", "enum": ["exponential", "logarithmic", "power", "sigmoid"], "default": "exponential"},
            "p0": {"type": "array", "items": "number", "required": False, "description": "Initial parameter guess"},
        },
        returns="dict",
        tags=["regression", "fit", "nonlinear"],
    ),
    _curve_fit,
)


# ---------------------------------------------------------------- correlation
def _correlation(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    method: str = "pearson",
) -> pd.DataFrame:
    if method not in ("pearson", "spearman", "kendall"):
        raise ValueError("method must be one of pearson | spearman | kendall")
    sub = df[columns] if columns else df.select_dtypes(include="number")
    return sub.corr(method=method).reset_index().rename(columns={"index": "variable"})


register_builtin(
    AlgorithmSpec(
        slug="correlation",
        name="Correlation matrix",
        category="regression",
        description="Use to find which variables move together / are related (and how strongly) — pairwise Pearson / Spearman / Kendall correlations.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False, "description": "If empty, uses all numeric columns"},
            "method": {"type": "string", "enum": ["pearson", "spearman", "kendall"], "default": "pearson"},
        },
        returns="dataframe",
        tags=["correlation", "statistics"],
    ),
    _correlation,
)


# ---------------------------------------------------------------- interpolation
def _interpolate(
    df: pd.DataFrame,
    *,
    x: str,
    y,
    method: str = "linear",
    x_new: Optional[List[float]] = None,
    n_points: int = 200,
) -> pd.DataFrame:
    """Interpolate one or more y columns as a function of x onto a shared x-grid.

    `y` may be a single column name OR a list of column names (a pipeline step
    after a multi-column filter naturally hands several columns through — e.g.
    voltage_v_gauss / current_a_gauss / …). method: linear | cubic | quadratic |
    nearest.
    """
    from scipy.interpolate import interp1d

    ys = [y] if isinstance(y, str) else [str(c) for c in (y or [])]
    if not ys:
        raise ValueError("interpolate requires at least one y column")
    _require_cols(df, [x, *ys])
    sub = df[[x, *ys]].dropna().sort_values(by=x)
    xs = sub[x].to_numpy(dtype=float)
    if xs.size < 2:
        raise ValueError("need at least 2 non-missing rows to interpolate")
    if x_new is None:
        x_new = list(np.linspace(float(xs.min()), float(xs.max()), n_points))
    xn = np.asarray(x_new, dtype=float)
    out: Dict[str, Any] = {x: list(map(float, xn))}
    for col in ys:
        yv = sub[col].to_numpy(dtype=float)
        if method == "rbf":
            # Radial-basis interpolation — smooth fit through uneven / scattered
            # samples (no requirement that x be on a regular grid).
            from scipy.interpolate import Rbf

            out[col] = list(map(float, Rbf(xs, yv, function="multiquadric")(xn)))
        else:
            f = interp1d(xs, yv, kind=method, fill_value="extrapolate", assume_sorted=True)
            out[col] = list(map(float, f(xn)))
    return pd.DataFrame(out)


register_builtin(
    AlgorithmSpec(
        slug="interpolate",
        name="1D interpolation",
        category="regression",
        description=(
            "Resample/interpolate y vs x onto a smooth curve — fill in missing points, align "
            "different sampling rates, or smooth out an unevenly-sampled signal. Use linear/cubic "
            "for regular evenly-spaced data; use rbf (radial basis function) when the samples are "
            "uneven/scattered or you want a smoother fit through noisy scatter."
        ),
        params_schema={
            "x": {"type": "string", "required": True},
            # array → the UI offers a multi-column picker; a single column also works.
            "y": {"type": "array", "items": "string", "required": True,
                  "description": "一个或多个要插值的列"},
            "method": {"type": "string", "enum": ["linear", "cubic", "quadratic", "nearest", "rbf"], "default": "linear"},
            "x_new": {"type": "array", "items": "number", "required": False},
            "n_points": {"type": "integer", "default": 200, "minimum": 2},
        },
        returns="dataframe",
        tags=["interpolation"],
    ),
    _interpolate,
)
