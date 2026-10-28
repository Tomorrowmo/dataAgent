"""判据常量与共用计算。

单独放一个模块,是为了演示技能包可以是**一个包**:tools/ 里的工具 import 这里的
lib/,安装时会把 lib 认成包内模块,不会被 import 白名单拦下来。
改判据只改这一个文件,三个工具同时生效。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ── 判级阈值(改这里就改了全包口径)────────────────────────────────────────
FADE_A_MAX = 2.0          # 每百圈衰减 < 2.0% → 有资格评 A
FADE_C_MIN = 4.0          # 每百圈衰减 ≥ 4.0% → 直接 C
EOL_A_MIN = 1000.0        # 外推 EOL ≥ 1000 圈 → 有资格评 A
EOL_C_MAX = 500.0         # 外推 EOL < 500 圈 → 直接 C
CLIFF_WINDOW = 10         # 跳水检测窗口(圈)
CLIFF_DROP_PCT = 3.0      # 窗口内保持率跌幅 > 3% 即判跳水
MIN_CYCLES_FOR_GRADE = 30 # 少于这个圈数不给分级
MAX_MISSING_RATIO = 0.10  # 容量列缺失超过 10% 不出结论


class DataInsufficient(ValueError):
    """数据不足以支撑结论 —— 工具宁可报错也不猜。"""


def require_columns(df: pd.DataFrame, wanted: Dict[str, str]) -> None:
    """wanted: {用途: 列名}。缺列时把真实列名一起报出来,让用户/AI 能直接改对。"""
    if df is None or len(df) == 0:
        raise DataInsufficient("这份数据是空的。")
    missing = {k: v for k, v in wanted.items() if v not in df.columns}
    if missing:
        have = "、".join(map(str, df.columns[:30]))
        want = "、".join(f"{k}={v}" for k, v in missing.items())
        raise DataInsufficient(f"数据里没有这些列:{want}。这份数据实际有的列是:{have}")


def clean_series(df: pd.DataFrame, cycle_col: str, value_col: str) -> pd.DataFrame:
    out = df[[cycle_col, value_col]].copy()
    out[cycle_col] = pd.to_numeric(out[cycle_col], errors="coerce")
    out[value_col] = pd.to_numeric(out[value_col], errors="coerce")
    missing_ratio = float(out[value_col].isna().mean())
    if missing_ratio > MAX_MISSING_RATIO:
        raise DataInsufficient(
            f"列 `{value_col}` 有 {missing_ratio:.0%} 是空的(超过 {MAX_MISSING_RATIO:.0%} 的上限),"
            "先补齐或换一份数据再判。"
        )
    out = out.dropna().sort_values(cycle_col).reset_index(drop=True)
    if len(out) < 3:
        raise DataInsufficient("有效循环点少于 3 个,算不出趋势。")
    return out


def baseline_capacity(caps: pd.Series, baseline_cycles: int = 5) -> float:
    """基准容量 = 前 N 圈中位数。不取首圈:化成/活化会让首圈偏低,拿它当基准会整体抬高保持率。"""
    n = max(1, min(int(baseline_cycles), len(caps)))
    base = float(np.median(caps.iloc[:n]))
    if not np.isfinite(base) or base <= 0:
        raise DataInsufficient("基准容量算出来是 0 或非法值,检查容量列的量纲和缺失。")
    return base


def fade_rate_pct_per_100(cycles: pd.Series, retention: pd.Series) -> float:
    """对保持率做一次线性拟合,换算成"每百圈掉几个百分点"(正数=在衰减)。"""
    if len(cycles) < 3:
        return float("nan")
    slope = float(np.polyfit(cycles.astype(float), retention.astype(float), 1)[0])
    return -slope * 100.0


def detect_cliff(cycles: pd.Series, retention: pd.Series,
                 window: int = CLIFF_WINDOW, drop_pct: float = CLIFF_DROP_PCT) -> Optional[Dict[str, float]]:
    """跳水:任意 window 圈内保持率跌幅超过 drop_pct。返回最早的一处。"""
    c = cycles.to_numpy(dtype=float)
    r = retention.to_numpy(dtype=float)
    for i in range(len(r)):
        j_candidates = np.where((c > c[i]) & (c <= c[i] + window))[0]
        if len(j_candidates) == 0:
            continue
        j = int(j_candidates[-1])
        drop = float(r[i] - r[j])
        if drop > drop_pct:
            return {"start_cycle": float(c[i]), "end_cycle": float(c[j]), "drop_pct": round(drop, 2)}
    return None


def extrapolate_eol(cycles: pd.Series, retention: pd.Series, eol_retention: float = 80.0) -> Optional[float]:
    """按线性拟合外推到 eol_retention%。已经跌破就返回实测圈数;斜率不衰减则返回 None。"""
    r = retention.astype(float)
    c = cycles.astype(float)
    if float(r.min()) <= eol_retention:
        below = c[r <= eol_retention]
        return float(below.iloc[0])
    slope, intercept = np.polyfit(c, r, 1)
    if slope >= -1e-9:  # 没有下降趋势 → 外推没有意义
        return None
    return float((eol_retention - intercept) / slope)


def grade(fade_per_100: float, eol_cycle: Optional[float], cliff: Optional[Dict]) -> Dict[str, object]:
    """唯一的判级入口。返回等级 + 触发它的那条判据(evidence),便于回答时说人话。"""
    reasons: List[str] = []
    if cliff:
        return {
            "grade": "C",
            "evidence": (f"第 {cliff['start_cycle']:.0f}–{cliff['end_cycle']:.0f} 圈保持率跌了 "
                         f"{cliff['drop_pct']:.1f}%,超过 {CLIFF_DROP_PCT}% 的跳水阈值 —— 跳水直接判 C。"),
        }
    if fade_per_100 >= FADE_C_MIN:
        reasons.append(f"每百圈衰减 {fade_per_100:.2f}% ≥ {FADE_C_MIN}%")
    if eol_cycle is not None and eol_cycle < EOL_C_MAX:
        reasons.append(f"外推 EOL 仅 {eol_cycle:.0f} 圈 < {EOL_C_MAX:.0f} 圈")
    if reasons:
        return {"grade": "C", "evidence": ";".join(reasons)}

    if fade_per_100 < FADE_A_MAX and (eol_cycle is None or eol_cycle >= EOL_A_MIN):
        return {
            "grade": "A",
            "evidence": (f"每百圈衰减 {fade_per_100:.2f}% < {FADE_A_MAX}%"
                         + (f",外推 EOL {eol_cycle:.0f} 圈 ≥ {EOL_A_MIN:.0f} 圈" if eol_cycle else "")),
        }
    return {
        "grade": "B",
        "evidence": (f"每百圈衰减 {fade_per_100:.2f}%(介于 {FADE_A_MAX}%–{FADE_C_MIN}% 之间)"
                     + (f",外推 EOL {eol_cycle:.0f} 圈" if eol_cycle else "")),
    }
