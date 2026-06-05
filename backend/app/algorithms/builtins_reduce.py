"""Reduction & sensitivity algorithms."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .registry import AlgorithmSpec, register_builtin


# ---------------------------------------------------------------- PCA
def _pca(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    n_components: int = 2,
    kernel: Optional[str] = None,
) -> Dict[str, Any]:
    """Linear or kernel PCA. kernel ∈ {None, 'linear', 'rbf', 'poly', 'sigmoid', 'cosine'}.

    Returns a dict with the projected DataFrame and explained-variance metadata,
    matching the sandbox `summary` shape so the result can be saved.
    """
    cols = columns or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    sub = df[cols].dropna()
    X = sub.values.astype(float)

    if kernel is None or kernel == "linear":
        from sklearn.decomposition import PCA

        model = PCA(n_components=min(n_components, len(cols), len(sub)))
        proj = model.fit_transform(X)
        explained = [float(v) for v in model.explained_variance_ratio_]
    else:
        from sklearn.decomposition import KernelPCA

        model = KernelPCA(n_components=n_components, kernel=kernel)
        proj = model.fit_transform(X)
        explained = []  # KernelPCA doesn't expose explained_variance_ratio_

    return pd.DataFrame(
        proj,
        columns=[f"PC{i+1}" for i in range(proj.shape[1])],
    ).assign(_explained_variance=lambda d: [explained] * len(d) if explained else None)


register_builtin(
    AlgorithmSpec(
        slug="pca",
        name="PCA / Kernel PCA",
        category="reduce",
        description="Use when there are too many columns to make sense of and you want to collapse them into 2-3 main dimensions to see the overall structure / clustering — PCA (optional kernel: RBF, poly, sigmoid, cosine).",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "n_components": {"type": "integer", "default": 2, "minimum": 1, "maximum": 50},
            "kernel": {
                "type": "string",
                "enum": ["linear", "rbf", "poly", "sigmoid", "cosine"],
                "required": False,
            },
        },
        returns="dataframe",
        tags=["reduce", "pca", "dimensionality"],
    ),
    _pca,
)


# ---------------------------------------------------------------- sensitivity
def _sensitivity(
    df: pd.DataFrame,
    *,
    inputs: List[str],
    output: str,
    method: str = "morris",
) -> pd.DataFrame:
    """Approximate per-input sensitivity of `output` to `inputs`.

    Methods:
      - 'correlation' : abs(Pearson) — cheap, assumes monotonic
      - 'morris'      : standardized regression coefficients (β·σ_x/σ_y) — common practical proxy
      - 'variance'    : Sobol-like first-order via variance of conditional means
    """
    for c in inputs + [output]:
        if c not in df.columns:
            raise ValueError(f"column not found: {c}")
    sub = df[inputs + [output]].dropna()
    y = sub[output].astype(float).to_numpy()
    rows: List[Dict[str, Any]] = []

    if method == "correlation":
        for v in inputs:
            x = sub[v].astype(float).to_numpy()
            r = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 else 0.0
            rows.append({"input": v, "sensitivity": float(abs(r)), "method": "correlation"})
    elif method == "morris":
        from sklearn.linear_model import LinearRegression

        X = sub[inputs].astype(float).values
        std_x = X.std(axis=0, ddof=0)
        std_y = y.std(ddof=0) or 1.0
        model = LinearRegression().fit(X, y)
        for v, beta, sx in zip(inputs, model.coef_, std_x):
            rows.append({
                "input": v,
                "sensitivity": float(abs(beta) * (sx / std_y)),
                "method": "morris",
            })
    elif method == "variance":
        var_y = float(np.var(y, ddof=0)) or 1.0
        for v in inputs:
            x = sub[v].astype(float).to_numpy()
            try:
                bins = np.quantile(x, np.linspace(0, 1, 11))
                bin_idx = np.digitize(x, bins[1:-1])
                conditional = [y[bin_idx == k].mean() for k in range(len(bins) - 1) if (bin_idx == k).any()]
                s1 = float(np.var(conditional, ddof=0) / var_y)
            except Exception:
                s1 = 0.0
            rows.append({"input": v, "sensitivity": s1, "method": "variance"})
    else:
        raise ValueError(f"unknown method '{method}'")

    out = pd.DataFrame(rows).sort_values("sensitivity", ascending=False).reset_index(drop=True)
    total = out["sensitivity"].sum() or 1.0
    out["normalized"] = out["sensitivity"] / total
    return out


register_builtin(
    AlgorithmSpec(
        slug="sensitivity",
        name="Sensitivity analysis",
        category="reduce",
        description="Use to find which input variables most affect a chosen output and which barely matter (a ranked list) — correlation / Morris-like / variance-based sensitivity.",
        params_schema={
            "inputs": {"type": "array", "items": "string", "required": True},
            "output": {"type": "string", "required": True},
            "method": {"type": "string", "enum": ["correlation", "morris", "variance"], "default": "morris"},
        },
        returns="dataframe",
        tags=["reduce", "sensitivity"],
    ),
    _sensitivity,
)


# ---------------------------------------------------------------- clustering
def _kmeans_cluster(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    n_clusters: int = 3,
) -> pd.DataFrame:
    """Group rows into k clusters via KMeans on the numeric columns. Adds a
    `cluster` label column to the rows used."""
    from sklearn.cluster import KMeans

    cols = columns or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not cols:
        raise ValueError("no numeric columns to cluster")
    sub = df[cols].dropna().copy()
    if len(sub) < n_clusters:
        raise ValueError(f"need at least n_clusters={n_clusters} rows, got {len(sub)}")
    km = KMeans(n_clusters=int(n_clusters), n_init=10, random_state=0)
    sub["cluster"] = km.fit_predict(sub.values.astype(float)).astype(int)
    return sub.reset_index(drop=True)


register_builtin(
    AlgorithmSpec(
        slug="kmeans_cluster",
        name="K-means clustering",
        category="reduce",
        description="Use to automatically group similar rows into clusters when you have no labels — find natural segments / groupings in the data. KMeans on the numeric columns; adds a `cluster` column.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "n_clusters": {"type": "integer", "default": 3, "minimum": 2, "maximum": 20},
        },
        returns="dataframe",
        tags=["reduce", "cluster", "kmeans", "unsupervised"],
        aliases=["kmeans_clustering", "kmeans", "clustering", "cluster"],
    ),
    _kmeans_cluster,
)
