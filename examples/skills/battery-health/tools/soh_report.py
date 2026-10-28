"""健康度总评:SOH + 衰减速率 + EOL 外推 + A/B/C 分级。

返回 dict(returns: dict)。dict 会原样进 AI 的上下文,所以字段名要自解释,
并且**把不确定性也写进去** —— data_sufficient / extrapolated 让 AI 没法把外推
当实测来说。
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from lib import criteria


def run(df: pd.DataFrame,
        cycle_col: str = "cycle",
        capacity_col: str = "discharge_capacity_ah",
        baseline_cycles: int = 5,
        eol_retention: float = 80.0) -> Dict[str, Any]:
    criteria.require_columns(df, {"循环号": cycle_col, "放电容量": capacity_col})
    clean = criteria.clean_series(df, cycle_col, capacity_col)

    base = criteria.baseline_capacity(clean[capacity_col], baseline_cycles)
    retention = clean[capacity_col] / base * 100.0
    cycles = clean[cycle_col]

    fade = criteria.fade_rate_pct_per_100(cycles, retention)
    cliff = criteria.detect_cliff(cycles, retention)
    eol = criteria.extrapolate_eol(cycles, retention, eol_retention)
    verdict = criteria.grade(fade, eol, cliff)

    n_cycles = int(cycles.max() - cycles.min() + 1)
    enough = n_cycles >= criteria.MIN_CYCLES_FOR_GRADE
    extrapolated = eol is not None and eol > float(cycles.max())
    far_extrapolation = bool(eol is not None and eol > 3.0 * float(cycles.max()))

    out: Dict[str, Any] = {
        "soh_pct": round(float(retention.iloc[-1]), 2),
        "baseline_capacity": round(float(base), 6),
        "last_cycle": int(cycles.iloc[-1]),
        "n_cycles": n_cycles,
        "fade_pct_per_100cyc": round(float(fade), 3),
        "eol_retention_pct": float(eol_retention),
        "eol_cycle_est": None if eol is None else round(float(eol)),
        "extrapolated": bool(extrapolated),
        "far_extrapolation": far_extrapolation,
        "cliff": cliff,
        "grade": verdict["grade"],
        "evidence": verdict["evidence"],
        "data_sufficient": bool(enough),
    }
    notes = []
    if not enough:
        notes.append(
            f"只有 {n_cycles} 圈(< {criteria.MIN_CYCLES_FOR_GRADE} 圈),按本包口径**不能给分级**,"
            "上面的 grade 仅供参考,回答时必须说明数据不足。"
        )
    if far_extrapolation:
        notes.append(
            f"EOL 是从 {int(cycles.max())} 圈实测外推到 {out['eol_cycle_est']} 圈的(超过实测 3 倍),"
            "不确定性很大,回答时必须写明这是外推。"
        )
    if cliff:
        notes.append(f"第 {cliff['start_cycle']:.0f} 圈附近出现跳水,建议查该圈的电压曲线。")
    out["notes"] = notes
    return out
