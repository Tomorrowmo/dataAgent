"""跨车次趋势与离群检测。

对同一特征在多个车次上的取值序列，用三个检测器分别回答三个不同的问题，
并且只在检验本身显著时才升级为告警，其余结果作为背景信息列出。

mann_kendall
    整条序列是否存在单调漂移。Mann–Kendall 检验统计同向与反向的数据对，
    换算为 z 值，不要求数据服从某种分布，对个别离群点不敏感；配合 Theil–Sen
    斜率给出“每车次漂移多少个特征单位”，据此判断漂移是否会在序列结束前越限。

hampel
    某一个车次是否偏离其相邻车次。以移动中位数为基准，按 k·1.4826·MAD 判定。
    中位数与 MAD 都是稳健统计量，离群点不会掩盖自己；移动窗口又保证真实趋势
    不会被报成一串离群点。

nelson
    是否出现游程规则违例，且次数多于随机序列的期望。采用 Nelson 规则 3，
    窗口取 7，同时报告“观测次数/期望次数”，使读者能判断违例是否有意义。

不用“序列中任意位置出现长度≥5 的单调段即告警”的原因：对长度为 n 的随机
序列，某位置起始一个长度为 k 的单调段的概率每个方向为 1/k!，n 个点中期望
出现约 (n−k+1)·2/k! 段。n=100、k=5 时约为 1.6 段，即纯随机数据平均也会触发
一到两次，这样的告警没有信息量。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

REFS = {
    "mk": ("Mann, H.B. (1945) Nonparametric tests against trend, Econometrica 13(3); "
           "Kendall, M.G. (1975) Rank Correlation Methods"),
    "sen": ("Theil, H. (1950); Sen, P.K. (1968) Estimates of the regression coefficient "
            "based on Kendall's tau, JASA 63(324)"),
    "hampel": ("Davies, L. & Gather, U. (1993) The identification of multiple outliers, "
               "JASA 88(423); NIST/SEMATECH e-Handbook §1.3.5.17"),
    "nelson": ("Nelson, L.S. (1984) The Shewhart Control Chart — Tests for Special Causes, "
               "Journal of Quality Technology 16(4), rule 3; "
               "Western Electric Statistical Quality Control Handbook (1956)"),
}


# ── normal distribution tail (no scipy dependency in this path) ─────────────
def _norm_sf(z: float) -> float:
    """Upper-tail probability of the standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def mann_kendall(values: Sequence[float], *, alpha: float = 0.05) -> Dict[str, Any]:
    """Nonparametric monotone-trend test with a Theil–Sen slope.

    Returns z, two-sided p, the Sen slope (units per run), and a verdict. Ties
    are handled with the standard tie correction so a feature that is constant
    over stretches (common for quantised readings) is not called a trend.
    """
    n = len(values)
    if n < 4:
        return {"applicable": False, "reason": f"样本量 {n} < 4，趋势检验不适用"}

    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            d = values[j] - values[i]
            s += (d > 0) - (d < 0)

    # Variance with tie correction.
    counts: Dict[float, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    tie_term = sum(t * (t - 1) * (2 * t + 5) for t in counts.values() if t > 1)
    var = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if var <= 0:
        return {"applicable": False, "reason": "序列全为同一数值，无趋势可言"}

    if s > 0:
        z = (s - 1) / math.sqrt(var)
    elif s < 0:
        z = (s + 1) / math.sqrt(var)
    else:
        z = 0.0
    p = 2.0 * _norm_sf(abs(z))

    slopes = [(values[j] - values[i]) / (j - i)
              for i in range(n - 1) for j in range(i + 1, n)]
    slopes.sort()
    m = len(slopes)
    sen = slopes[m // 2] if m % 2 else 0.5 * (slopes[m // 2 - 1] + slopes[m // 2])

    direction = "上升" if s > 0 else ("下降" if s < 0 else "无")
    return {
        "applicable": True,
        "S": s, "z": round(z, 4), "p": round(p, 6),
        "sen_slope_per_run": sen,
        "direction": direction,
        "significant": bool(p < alpha and s != 0),
        "alpha": alpha,
        "reference": REFS["mk"] + "；斜率：" + REFS["sen"],
    }


def hampel(values: Sequence[float], *, window: int = 7, k: float = 3.0) -> Dict[str, Any]:
    """Moving-median outlier identifier. Returns indices and scores.

    ``1.4826`` rescales the MAD to a standard-deviation equivalent for normal
    data, so ``k`` reads like a sigma multiplier.
    """
    n = len(values)
    if n < 5:
        return {"applicable": False, "reason": f"样本量 {n} < 5，离群识别不适用",
                "outliers": []}
    half = max(1, window // 2)
    out: List[Dict[str, Any]] = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        win = sorted(values[lo:hi])
        med = win[len(win) // 2] if len(win) % 2 else 0.5 * (win[len(win) // 2 - 1] + win[len(win) // 2])
        dev = sorted(abs(v - med) for v in values[lo:hi])
        mad = dev[len(dev) // 2] if len(dev) % 2 else 0.5 * (dev[len(dev) // 2 - 1] + dev[len(dev) // 2])
        sigma = 1.4826 * mad
        if sigma <= 0:
            continue
        score = abs(values[i] - med) / sigma
        if score > k:
            out.append({"index": i, "value": values[i], "median": med,
                        "score": round(score, 2)})
    return {"applicable": True, "window": window, "k": k, "outliers": out,
            "reference": REFS["hampel"]}


def nelson_runs(values: Sequence[float], *, window: int = 7) -> Dict[str, Any]:
    """Count Nelson-rule-3 violations and compare with chance.

    Reporting *expected* alongside *observed* is the whole point: on a long
    series a couple of runs are normal, and only a clear excess is evidence.
    """
    n = len(values)
    if n < window:
        return {"applicable": False,
                "reason": f"样本量 {n} < 判据窗口 {window}", "observed": 0}
    obs = 0
    longest = 1
    run_up = run_down = 1
    for i in range(1, n):
        if values[i] > values[i - 1]:
            run_up, run_down = run_up + 1, 1
        elif values[i] < values[i - 1]:
            run_down, run_up = run_down + 1, 1
        else:
            run_up = run_down = 1
        longest = max(longest, run_up, run_down)
        if run_up == window or run_down == window:
            obs += 1
    # P(a given position starts a strictly monotone run of length `window`)
    # = 1/window! per direction, for exchangeable data.
    p_start = 2.0 / math.factorial(window)
    expected = max(0.0, (n - window + 1)) * p_start
    return {
        "applicable": True, "window": window,
        "observed": obs, "expected": round(expected, 3),
        "longest_monotone_run": longest,
        "excess": bool(obs > 0 and obs >= max(2.0, 3.0 * expected)),
        "reference": REFS["nelson"],
    }


@dataclass
class TrendReport:
    feature: str
    name: str
    unit: str
    runs: List[str]
    values: List[float]
    mk: Dict[str, Any] = field(default_factory=dict)
    hp: Dict[str, Any] = field(default_factory=dict)
    nl: Dict[str, Any] = field(default_factory=dict)
    flagged: bool = False
    headline: str = ""
    outlier_runs: List[Dict[str, Any]] = field(default_factory=list)
    #: Practical-significance bookkeeping (see analyse_series).
    projected_drift: Optional[float] = None
    rule_threshold: Optional[float] = None
    drift_fraction_of_limit: Optional[float] = None
    practically_negligible: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature, "name": self.name, "unit": self.unit,
            "runs": self.runs, "values": self.values,
            "mann_kendall": self.mk, "hampel": self.hp, "nelson": self.nl,
            "flagged": self.flagged, "headline": self.headline,
            "outlier_runs": self.outlier_runs,
            "projected_drift": self.projected_drift,
            "rule_threshold": self.rule_threshold,
            "drift_fraction_of_limit": self.drift_fraction_of_limit,
            "practically_negligible": self.practically_negligible,
            # 兼容旧版界面使用的字段。
            "trend": self.mk.get("direction", "无") if self.mk.get("significant") else "无显著趋势",
            "monotone_run": self.nl.get("longest_monotone_run", 0),
            "note": self.headline,
            "reference": "；".join(
                x for x in (self.mk.get("reference") if self.mk.get("significant") else "",
                            self.hp.get("reference") if self.outlier_runs else "",
                            self.nl.get("reference") if self.nl.get("excess") else "")
                if x),
        }


def analyse_series(
    feature: str, name: str, unit: str,
    runs: Sequence[str], values: Sequence[float],
    *, alpha: float = 0.05, hampel_k: float = 3.0, nelson_window: int = 7,
    practical_limit: Optional[float] = None, practical_fraction: float = 0.1,
) -> TrendReport:
    """Analyse one feature's series.

    ``practical_limit`` is the smallest magnitude at which the governing rule
    stops calling the value normal. A drift is only escalated when it is BOTH
    statistically significant AND large enough to matter against that limit:
    例如某特征的漂移在统计上非常确定（p = 0.0005），但累计漂移量只有首级
    报警阈值的 8 %。对这种情形报警，只会让操作人员习惯性忽略报警。
    The outlier and run-rule components are judged separately, so a negligible
    drift never suppresses a genuine outlier.
    """
    vals = list(values)
    rep = TrendReport(feature=feature, name=name, unit=unit,
                      runs=list(runs), values=[round(v, 8) for v in vals])
    rep.mk = mann_kendall(vals, alpha=alpha)
    rep.hp = hampel(vals, k=hampel_k)
    rep.nl = nelson_runs(vals, window=nelson_window)

    rep.outlier_runs = [
        {"run_no": rep.runs[o["index"]], "value": o["value"],
         "median": round(o["median"], 8), "score": o["score"]}
        for o in rep.hp.get("outliers", []) if o["index"] < len(rep.runs)
    ]

    parts: List[str] = []
    trend_matters = False
    if rep.mk.get("significant"):
        slope = rep.mk["sen_slope_per_run"]
        span = slope * max(1, len(vals) - 1)
        trend_matters = True
        text = (f"全序列存在显著{rep.mk['direction']}趋势"
                f"（Mann-Kendall z={rep.mk['z']:.2f}, p={rep.mk['p']:.2g} < {alpha}），"
                f"Sen 斜率 {slope:+.4g} {unit}/车次，本批次累计变化约 {span:+.4g} {unit}")
        if practical_limit:
            frac = abs(span) / practical_limit
            rep.projected_drift = abs(span)
            rep.rule_threshold = practical_limit
            rep.drift_fraction_of_limit = round(frac, 4)
            if frac < practical_fraction:
                trend_matters = False
                rep.practically_negligible = True
                text += (f"；但累计漂移仅为该项首档阈值（{practical_limit:g} {unit}）的 "
                         f"{frac:.1%}，统计显著而工程上可忽略，不作告警")
            else:
                text += f"，相当于首档阈值（{practical_limit:g} {unit}）的 {frac:.0%}"
        parts.append(text)
    if rep.outlier_runs:
        worst = max(rep.outlier_runs, key=lambda x: x["score"])
        parts.append(
            f"{len(rep.outlier_runs)} 个车次偏离邻域中位数超过 {hampel_k}σ"
            f"（最显著：车次 {worst['run_no']}，{worst['score']:.1f}σ）"
        )
    if rep.nl.get("excess"):
        parts.append(
            f"连续{nelson_window}点单调的游程出现 {rep.nl['observed']} 次，"
            f"显著多于随机期望 {rep.nl['expected']:.2f} 次"
        )
    rep.flagged = bool(trend_matters or rep.outlier_runs or rep.nl.get("excess"))
    rep.headline = "；".join(parts) if parts else (
        f"无显著趋势（Mann-Kendall p={rep.mk.get('p', float('nan')):.2g}），无离群车次"
        if rep.mk.get("applicable") else (rep.mk.get("reason", "样本不足，未做趋势判定"))
    )
    return rep
