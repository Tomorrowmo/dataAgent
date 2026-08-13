"""Repeatability — the quality metric that only a multi-run entry can give.

WHY THIS EXISTS
---------------
A single-run check answers "is this run's equipment healthy?". It cannot answer
the question a tunnel's quality department is actually judged on: **if we fly
the same condition twice, do we get the same numbers?** That is *repeatability*
(重复性精度), and it is the headline figure in every wind-tunnel data-quality
standard:

* AIAA S-071A-1999, *Assessment of Experimental Uncertainty with Application to
  Wind Tunnel Testing* — random (precision) error is estimated from repeated
  measurements under nominally identical conditions.
* ASME PTC 19.1, *Test Uncertainty* — the random standard uncertainty ``s_x̄``.
* ISO 5725-2 — the repeatability standard deviation ``s_r``, pooled across
  groups measured under repeatability conditions.
* GJB 1179A-2012 — 高速风洞试验数据精度指标, expressed as a per-coefficient
  standard deviation at matched conditions.

It also fixes a problem the trend detector cannot solve. Quantities that depend
on the test condition (loads, base pressures, elastic deflection) vary by an
order of magnitude across a control-deflection matrix, so trending them over a
mixed entry measures the *test schedule*. The right comparison for those is not
"run 5 vs run 4" but "this run vs the OTHER runs at the same condition" — which
is exactly what a repeat group provides, and it is a far stronger statement:
a run that disagrees with its own repeats is bad on evidence, not on a
threshold someone chose.

Definitions used here
---------------------
Runs are grouped by their **state signature** — Mach, sideslip, and the three
control deflections, rounded to the precision the tunnel commands them at. For
a group of ``n ≥ 2`` runs:

``s_r`` (per coefficient, per angle of attack)
    Sample standard deviation across the repeats at that α, computed on a
    common α grid so runs with different sweep schedules are still comparable.

``s_r`` (per coefficient, pooled)
    ``sqrt( Σ (n_i − 1)·s_i² / Σ (n_i − 1) )`` over all groups and angles —
    the ISO 5725-2 pooled estimate, with the correct degrees of freedom.

``2·s_r``
    The interval within which ~95 % of repeated measurements fall; this is the
    number most tunnels quote as their precision index.

Outliers within a group use the Grubbs test (Grubbs 1969, *Technometrics* 11(1);
NIST/SEMATECH e-Handbook §1.3.5.17) with a two-sided critical value; with the
tiny ``n`` typical of repeat groups, a run must disagree strongly to be called.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .parsers import RunBundle

#: Coefficients worth a repeatability figure. Restricted to the primary
#: aerodynamic outputs — quoting a precision index for a padding column would
#: be noise.
DEFAULT_COEFFS: Tuple[str, ...] = (
    "CN", "CA", "CAF", "CZ", "CAB", "CL", "CD", "CLF", "CDF", "CC",
    "MZG1", "MYG1", "MXG1", "XCP",
)

GRUBBS_REF = ("Grubbs, F.E. (1969) Procedures for detecting outlying observations, "
              "Technometrics 11(1); NIST/SEMATECH e-Handbook §1.3.5.17")
ISO_REF = ("ISO 5725-2 重复性标准差 s_r 的合并估计；AIAA S-071A-1999；ASME PTC 19.1")


def state_signature(b: RunBundle, *, ndigits: int = 2) -> Tuple[Any, ...]:
    """The condition a run was flown at — what makes two runs *repeats*."""
    mach = round(b.mach, 3) if b.mach else None
    st = (b.da.state if (b.da and b.da.state) else {})
    def g(k: str) -> Optional[float]:
        v = st.get(k)
        return round(float(v), ndigits) if v is not None else None
    return (mach, g("BETA"), g("PHI"), g("dz"), g("dy"), g("dx"))


def signature_label(sig: Sequence[Any]) -> str:
    mach, beta, phi, dz, dy, dx = sig
    parts = [f"Ma={mach:g}" if mach is not None else "Ma=?"]
    for name, v in (("β", beta), ("φ", phi), ("δz", dz), ("δy", dy), ("δx", dx)):
        if v is not None:
            parts.append(f"{name}={v:g}")
    return " ".join(parts)


def _grubbs_critical(n: int, alpha: float = 0.05) -> float:
    """Two-sided Grubbs critical value.

    Uses the exact formula with a Student-t quantile; the t quantile itself is
    obtained by a bisection on the incomplete-beta-based CDF so this module
    stays dependency-free (it runs in the same process as the sandboxless
    pipeline).
    """
    if n < 3:
        return float("inf")
    p = alpha / (2.0 * n)
    t = _t_ppf(1.0 - p, n - 2)
    return ((n - 1) / math.sqrt(n)) * math.sqrt(t * t / (n - 2 + t * t))


def _t_cdf(t: float, df: int) -> float:
    x = df / (df + t * t)
    ib = _betainc(df / 2.0, 0.5, x)
    return 1.0 - 0.5 * ib if t > 0 else 0.5 * ib


def _t_ppf(p: float, df: int) -> float:
    lo, hi = -1e3, 1e3
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b) via the continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    f, c, d = 1.0, 1.0, 0.0
    for i in range(0, 300):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        d = 1e-30 if abs(d) < 1e-30 else d
        d = 1.0 / d
        c = 1.0 + num / c
        c = 1e-30 if abs(c) < 1e-30 else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-12:
            break
    result = front * (f - 1.0)
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _betainc(b, a, 1 - x)
    return min(1.0, max(0.0, result))


def _interp(x: Sequence[float], y: Sequence[float], xt: float) -> Optional[float]:
    """Linear interpolation, no extrapolation (returns None outside the range).

    Refusing to extrapolate is deliberate: a repeatability figure built partly
    from extrapolated values would flatter the tunnel.
    """
    n = min(len(x), len(y))
    if n < 2 or xt < min(x[:n]) - 1e-9 or xt > max(x[:n]) + 1e-9:
        return None
    pts = sorted(zip(x[:n], y[:n]))
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 - 1e-9 <= xt <= x1 + 1e-9:
            if abs(x1 - x0) < 1e-12:
                return y0
            return y0 + (y1 - y0) * (xt - x0) / (x1 - x0)
    return None


@dataclass
class RepeatGroup:
    label: str
    signature: Tuple[Any, ...]
    runs: List[str]
    #: {coefficient: {"alphas": [...], "mean": [...], "sd": [...], "n": [...]}}
    per_coeff: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    #: {coefficient: pooled sd within this group}
    sd: Dict[str, float] = field(default_factory=dict)
    outliers: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label, "runs": self.runs,
            "n": len(self.runs),
            "sd": {k: round(v, 8) for k, v in self.sd.items()},
            "per_coeff": self.per_coeff,
            "outliers": self.outliers,
        }


@dataclass
class RepeatabilityReport:
    groups: List[RepeatGroup]
    #: Pooled s_r per coefficient across all repeat groups (ISO 5725-2).
    pooled_sd: Dict[str, float] = field(default_factory=dict)
    pooled_dof: Dict[str, int] = field(default_factory=dict)
    #: Runs that disagree with their own repeats — the strongest evidence a
    #: single run is bad.
    outliers: List[Dict[str, Any]] = field(default_factory=list)
    singletons: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "pooled_sd": {k: round(v, 8) for k, v in self.pooled_sd.items()},
            "pooled_2sd": {k: round(2 * v, 8) for k, v in self.pooled_sd.items()},
            "pooled_dof": self.pooled_dof,
            "outliers": self.outliers,
            "singleton_runs": self.singletons,
            "group_count": len(self.groups),
            "repeated_group_count": sum(1 for g in self.groups if len(g.runs) >= 2),
            "notes": self.notes,
            "reference": ISO_REF,
        }


def analyse_repeatability(
    bundles: Sequence[RunBundle],
    *,
    coeffs: Sequence[str] = DEFAULT_COEFFS,
    alpha_tol: float = 0.05,
    grubbs_alpha: float = 0.05,
) -> RepeatabilityReport:
    """Group runs by condition and quantify run-to-run scatter."""
    by_sig: Dict[Tuple[Any, ...], List[RunBundle]] = {}
    for b in bundles:
        if b.da is None or not b.da.ok:
            continue
        by_sig.setdefault(state_signature(b), []).append(b)

    rep = RepeatabilityReport(groups=[])
    if not by_sig:
        rep.notes.append("没有可用的 da 结果文件，无法评估重复性。")
        return rep

    # Numerator / denominator of the pooled variance, per coefficient.
    acc: Dict[str, List[float]] = {c: [0.0, 0.0] for c in coeffs}

    for sig, group in sorted(by_sig.items(), key=lambda kv: str(kv[0])):
        runs = sorted(group, key=lambda b: b.run_no)
        g = RepeatGroup(label=signature_label(sig), signature=sig,
                        runs=[b.run_no for b in runs])
        if len(runs) < 2:
            rep.singletons.append(runs[0].run_no)
            rep.groups.append(g)
            continue

        # Common α grid: angles present (within tolerance) in EVERY repeat.
        grids = [b.da.series("ALPHA") for b in runs]
        base = grids[0]
        common = [a for a in base
                  if all(any(abs(a - x) <= alpha_tol for x in grid) for grid in grids[1:])]
        if not common:
            g.per_coeff = {}
            rep.groups.append(g)
            rep.notes.append(f"{g.label}: 重复车次之间没有公共攻角点，未评估。")
            continue

        for c in coeffs:
            if not all(c in b.da.columns for b in runs):
                continue
            alphas, means, sds, ns = [], [], [], []
            for a in common:
                vals = []
                for b in runs:
                    xs, ys = b.da.series("ALPHA"), b.da.series(c)
                    v = _interp(xs, ys, a)
                    if v is not None:
                        vals.append(v)
                if len(vals) < 2:
                    continue
                m = sum(vals) / len(vals)
                var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
                alphas.append(a)
                means.append(m)
                sds.append(math.sqrt(var))
                ns.append(len(vals))
                acc[c][0] += (len(vals) - 1) * var
                acc[c][1] += (len(vals) - 1)
            if not alphas:
                continue
            g.per_coeff[c] = {
                "alphas": [round(x, 4) for x in alphas],
                "mean": [round(x, 8) for x in means],
                "sd": [round(x, 8) for x in sds],
                "n": ns,
            }
            dof = sum(n - 1 for n in ns)
            ssq = sum((n - 1) * s * s for n, s in zip(ns, sds))
            g.sd[c] = math.sqrt(ssq / dof) if dof else 0.0

        # Grubbs on the per-run mean deviation from the group mean, using CN as
        # the primary indicator (the largest, best-conditioned coefficient).
        primary = "CN" if "CN" in g.per_coeff else (next(iter(g.per_coeff), None))
        if primary and len(runs) >= 3:
            scores = []
            for b in runs:
                xs, ys = b.da.series("ALPHA"), b.da.series(primary)
                devs = []
                for a, m in zip(g.per_coeff[primary]["alphas"], g.per_coeff[primary]["mean"]):
                    v = _interp(xs, ys, a)
                    if v is not None:
                        devs.append(v - m)
                scores.append(sum(devs) / len(devs) if devs else 0.0)
            mu = sum(scores) / len(scores)
            sd = math.sqrt(sum((s - mu) ** 2 for s in scores) / (len(scores) - 1)) if len(scores) > 1 else 0.0
            if sd > 0:
                crit = _grubbs_critical(len(scores), grubbs_alpha)
                for b, s in zip(runs, scores):
                    gstat = abs(s - mu) / sd
                    if gstat > crit:
                        item = {
                            "run_no": b.run_no, "group": g.label,
                            "coefficient": primary,
                            "G": round(gstat, 3), "G_critical": round(crit, 3),
                            "mean_deviation": round(s, 8),
                            "reference": GRUBBS_REF,
                            "note": (f"车次 {b.run_no} 的 {primary} 相对同状态重复车次"
                                     f"系统性偏离 {s:+.5g}，Grubbs G={gstat:.2f} > "
                                     f"临界值 {crit:.2f}（α={grubbs_alpha}），"
                                     f"该车次与自身重复不一致，建议复查。"),
                        }
                        g.outliers.append(item)
                        rep.outliers.append(item)
        rep.groups.append(g)

    for c, (num, den) in acc.items():
        if den > 0:
            rep.pooled_sd[c] = math.sqrt(num / den)
            rep.pooled_dof[c] = int(den)

    nrep = sum(1 for g in rep.groups if len(g.runs) >= 2)
    rep.notes.append(
        f"共 {len(rep.groups)} 个试验状态，其中 {nrep} 个状态有重复车次；"
        f"{len(rep.singletons)} 个状态只做了一次，无法参与重复性评估。"
    )
    return rep


def repeatability_table(rep: RepeatabilityReport,
                        coeffs: Sequence[str] = DEFAULT_COEFFS) -> List[Dict[str, Any]]:
    """Flatten the pooled figures into the table a report prints."""
    out = []
    for c in coeffs:
        if c not in rep.pooled_sd:
            continue
        s = rep.pooled_sd[c]
        out.append({
            "coefficient": c,
            "s_r": round(s, 8),
            "two_s_r": round(2 * s, 8),
            "dof": rep.pooled_dof.get(c, 0),
        })
    return out
