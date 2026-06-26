"""Code-defined seed examples — a small, characteristic set of datasets and
flow templates that EVERY account gets, on every environment.

Why this lives in code (not a shipped parquet/JSON bundle): the old seed bundle
sat under data/ (excluded from the tree, present only on the deployed server),
so locally — and on any fresh snapshot — new accounts started empty and the
"示例" data appeared to vanish. Generating a curated baseline deterministically
in code makes it impossible to lose: it is versioned, identical for everyone,
and self-consistent (each template references columns the seed datasets really
have, so a one-click apply actually runs).

Column conventions and names are kept ALIGNED with the frontend one-click
STARTERS (web/lib/recipes.ts): same dataset name → same columns, so the seeds
and the starters reinforce each other instead of creating same-named-but-
different-shaped duplicates.

Determinism: every generator seeds its own RNG, so the bytes are identical for
every user (and reproducible across runs). Keep this set SMALL and
characteristic — it is the first thing a new user sees, not a data dump.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd


# ── characteristic datasets ────────────────────────────────────────────────
# Each is one distinct data SHAPE the product is good at, chosen so the
# auto-profile + recipes + the seed templates below all have something real to
# act on: a noisy time series, a multi-variable DOE, a messy process table, a
# scatter to fit, and blobs to cluster.

def _signal() -> pd.DataFrame:
    """A noisy 1-D signal with a few spikes — the 去噪 / 找异常 / 找周期 case.
    Columns match the '示例·周期信号' starter (time_s, signal)."""
    import numpy as np
    rng = np.random.default_rng(11)
    n = 400
    t = np.linspace(0, 20, n)
    signal = 2 * np.sin(2 * np.pi * 0.5 * t) + 0.5 * np.sin(2 * np.pi * 2 * t) + 0.25 * rng.normal(0, 1, n)
    for i in rng.choice(n, 5, replace=False):
        signal[i] += rng.choice([-1, 1]) * rng.uniform(4, 7)
    return pd.DataFrame({"time_s": t.round(4), "signal": signal.round(4)})


def _doe() -> pd.DataFrame:
    """A 60-run design-of-experiments table — the 找主因/敏感性/相关 case.
    Columns match the '示例·参数优化DOE' starter: drag is driven by thickness &
    aoa, sweep is near-noise."""
    import numpy as np
    rng = np.random.default_rng(23)
    n = 60
    thickness = 8 + rng.uniform(0, 8, n)
    camber = rng.uniform(0, 4, n)
    aoa = -2 + rng.uniform(0, 10, n)
    sweep = rng.uniform(0, 30, n)
    drag = 0.015 * thickness ** 2 + 0.6 * aoa ** 2 + 0.05 * camber + rng.normal(0, 1.5, n)
    lift = 1.3 * aoa + 0.9 * camber - 0.08 * thickness + rng.normal(0, 0.5, n)
    mass = 2.2 * thickness + rng.normal(0, 0.8, n)
    return pd.DataFrame({
        "thickness": thickness.round(3), "camber": camber.round(3), "aoa": aoa.round(3),
        "sweep": sweep.round(3), "drag": drag.round(3), "lift": lift.round(3), "mass": mass.round(3),
    })


def _quality() -> pd.DataFrame:
    """A messy process-quality table: grouped by batch, with missing values AND
    outliers — the 清洗 / 分组对比 case."""
    import numpy as np
    rng = np.random.default_rng(37)
    n = 120
    batch = rng.choice(["A", "B", "C"], n)
    base = {"A": 10.0, "B": 12.0, "C": 9.0}
    value1 = np.array([base[b] for b in batch]) + rng.normal(0, 0.6, n)
    value2 = 0.8 * value1 + rng.normal(0, 0.5, n)
    value1[rng.choice(n, 9, replace=False)] = np.nan
    value2[rng.choice(n, 6, replace=False)] = np.nan
    for i in rng.choice(n, 4, replace=False):
        value1[i] += rng.choice([-1, 1]) * rng.uniform(5, 9)
    return pd.DataFrame({"batch": batch, "value1": value1.round(3), "value2": value2.round(3)})


def _scatter() -> pd.DataFrame:
    """Unevenly sampled x/y around a smooth curve — the 拟合 / 插值 case.
    Columns match the '示例·散点曲线' starter (x, y)."""
    import numpy as np
    rng = np.random.default_rng(5)
    x = np.sort(rng.uniform(0, 10, 40))
    y = np.sin(x) + 0.15 * rng.normal(0, 1, 40)
    return pd.DataFrame({"x": x.round(4), "y": y.round(4)})


def _blobs() -> pd.DataFrame:
    """Three Gaussian blobs in 3 features — the 自动分组/聚类 case.
    Columns match the '示例·分组数据' starter (f1, f2, f3)."""
    import numpy as np
    rng = np.random.default_rng(7)
    centers = [(0, 0), (6, 6), (0, 7)]
    rows = []
    for cx, cy in centers:
        for _ in range(40):
            rows.append([cx + 0.6 * rng.normal(), cy + 0.6 * rng.normal(), rng.normal()])
    return pd.DataFrame(rows, columns=["f1", "f2", "f3"]).round(4)


# (name, description, file_format, builder) — name is the idempotency key, kept
# in sync with the frontend STARTERS so seeds and starters never diverge.
SEED_DATASETS: List[Tuple[str, str, str, Any]] = [
    ("示例·周期信号", "带噪声和突变尖峰的一维信号:用来试 去噪 / 找异常 / 找周期。", "csv", _signal),
    ("示例·参数优化DOE", "60 组气动设计实验(DOE):thickness/camber/aoa/sweep 等输入对 drag 的影响——试 找主因 / 相关性 / 降维。", "csv", _doe),
    ("示例·质量过程数据", "按 batch 分组的质量数据,故意带缺失值和异常点:用来试 清洗 / 分组对比。", "csv", _quality),
    ("示例·散点曲线", "采样不均匀的 x/y 散点,围绕一条光滑曲线:用来试 拟合 / 插值。", "csv", _scatter),
    ("示例·分组数据", "三簇高斯分布的点(f1/f2/f3):用来试 自动分组 / 聚类。", "csv", _blobs),
]


# ── characteristic flow templates ──────────────────────────────────────────
# Each step's columns reference one of the seed datasets above, so applying the
# template to that dataset just runs.

def _linear_graph(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the canvas graph for a straight pipeline: 原始数据 → step0 → step1 …
    Matches the node/edge shape the FlowCanvas already renders."""
    nodes: List[Dict[str, Any]] = [
        {"id": "input", "kind": "input", "params": {}, "label": "原始数据", "position": {"x": 40, "y": 120}},
    ]
    edges: List[Dict[str, Any]] = []
    prev = "input"
    for i, s in enumerate(steps):
        nid = f"n{i}"
        nodes.append({
            "id": nid, "kind": "step", "slug": s["slug"], "params": s.get("params", {}),
            "label": s.get("label", s["slug"]), "position": {"x": 40 + 344 * (i + 1), "y": 120},
        })
        edges.append({"source": prev, "target": nid})
        prev = nid
    return {"nodes": nodes, "edges": edges, "runtime": []}


def _tmpl(name: str, description: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"name": name, "description": description, "steps": steps, "graph": _linear_graph(steps)}


SEED_TEMPLATES: List[Dict[str, Any]] = [
    _tmpl(
        "【示例】标准去噪流水线",
        "去噪 → 找异常 → 归一化。一套基础信号处理流程,套到「示例·周期信号」就能跑。",
        [
            {"action": "run_tool", "slug": "savgol_filter", "params": {"window_length": 11, "polyorder": 3, "columns": ["signal"]}, "label": "去噪 (Savitzky-Golay)"},
            {"action": "run_tool", "slug": "outlier_detect", "params": {"method": "iqr", "columns": ["signal"], "iqr_k": 1.5}, "label": "找异常 (IQR)"},
            {"action": "run_tool", "slug": "normalize", "params": {"method": "minmax", "columns": ["signal"]}, "label": "归一化 (Min-Max)"},
        ],
    ),
    _tmpl(
        "【示例】DOE 设计参数敏感性",
        "对一份 DOE 自动找出哪个设计参数对结果(drag)影响最大。套到「示例·参数优化DOE」。",
        [
            {"action": "run_tool", "slug": "sensitivity", "params": {"inputs": ["thickness", "camber", "aoa", "sweep"], "output": "drag", "method": "correlation"}, "label": "敏感性分析"},
        ],
    ),
    _tmpl(
        "【示例】质量清洗 + 相关分析",
        "补缺失 → 找异常 → 相关性。同样的算法换不同流程,解决不同问题。套到「示例·质量过程数据」。",
        [
            {"action": "run_tool", "slug": "fill_missing", "params": {"method": "linear"}, "label": "补缺失值 (线性)"},
            {"action": "run_tool", "slug": "outlier_detect", "params": {"method": "iqr"}, "label": "找异常 (IQR)"},
            {"action": "run_tool", "slug": "correlation", "params": {"method": "pearson"}, "label": "相关性分析"},
        ],
    ),
]
