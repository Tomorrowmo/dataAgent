"""Orchestration — turn a folder of run files into checked, comparable results.

Two things here are easy to get wrong and are therefore handled explicitly.

**The zero-drift chain.** 天平零飘 is defined against the *previous* run, so a
batch of runs forms a chain: 91836 → 91837 → 91838 … The first run of a batch
has no predecessor and the check is reported as *unavailable*, not as "normal".
When a run's ``ca`` file fails to parse the chain BREAKS: the next run is
compared against the last run that actually parsed, and the report says which
run it was compared with. (The legacy script reset ``prev_ca`` to None on
failure, silently turning the next run's drift check off.)

**Cross-run trend.** A single run in isolation cannot tell you that the balance
zero has been walking in one direction for five runs — which is the earliest
observable signature of a failing balance. :func:`aggregate` therefore emits a
per-feature series across the batch so the UI can plot it, and flags monotone
runs using the classic control-chart trend rule (Nelson rule 3: seven or more
consecutive points steadily increasing or decreasing — Nelson, L.S., *Journal
of Quality Technology* 16(4), 1984; also Western Electric Handbook, 1956). The
window is configurable because a wind-tunnel entry is often shorter than seven
runs; the default is 5 with the reference stated in the finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .balance import BalanceLibrary, default_library
from .features import FEATURE_SPECS, FeatureValue, extract_features
from .parsers import RunBundle, group_by_run, load_bundle
from .rules import Finding, Rule, evaluate, grade, worst_level
from .seed_rules import seed_rules


@dataclass
class CheckConfig:
    """Everything a user can choose before pressing 开始检查."""

    #: Rule ids to run. Empty means "all enabled rules".
    rule_ids: List[str] = field(default_factory=list)
    #: 尾部收缩外形 — disables the base-pressure-vs-static comparison (rule 07b),
    #: exactly as the customer's ``sql_features`` flag did.
    tail_contracted: bool = False
    #: Per-batch override of the balance rated ranges, when the balance is not
    #: in the library and the user types them in.
    balance_ranges: Dict[str, float] = field(default_factory=dict)
    #: Nelson-rule window for the cross-run trend flag.
    trend_window: int = 5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_ids": list(self.rule_ids),
            "tail_contracted": self.tail_contracted,
            "balance_ranges": dict(self.balance_ranges),
            "trend_window": self.trend_window,
        }


@dataclass
class RunResult:
    run_no: str
    meta: Dict[str, Any]
    features: Dict[str, FeatureValue]
    findings: List[Finding]
    grade: str
    level: str
    compared_with: Optional[str] = None
    chain_broken: bool = False

    @property
    def problems(self) -> List[Finding]:
        return [f for f in self.findings if f.is_problem]

    @property
    def unavailable(self) -> List[Finding]:
        return [f for f in self.findings if f.status == "unavailable"]

    def counts(self) -> Dict[str, int]:
        c = {"critical": 0, "warning": 0, "notice": 0, "ok": 0,
             "unavailable": 0, "skipped": 0}
        for f in self.findings:
            if f.status == "evaluated":
                c[f.level] += 1
            else:
                c[f.status] += 1
        return c

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_no": self.run_no,
            "meta": self.meta,
            "grade": self.grade,
            "level": self.level,
            "compared_with": self.compared_with,
            "chain_broken": self.chain_broken,
            "counts": self.counts(),
            "features": {k: v.to_dict() for k, v in self.features.items()},
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class BatchResult:
    runs: List[RunResult]
    config: CheckConfig
    trends: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runs": [r.to_dict() for r in self.runs],
            "config": self.config.to_dict(),
            "trends": self.trends,
            "notes": self.notes,
            "summary": self.summary(),
        }

    def summary(self) -> Dict[str, Any]:
        total = {"critical": 0, "warning": 0, "notice": 0, "unavailable": 0}
        bad, warn = [], []
        for r in self.runs:
            c = r.counts()
            for k in total:
                total[k] += c.get(k, 0)
            if c["critical"] > 0:
                bad.append(r.run_no)
            elif c["warning"] > 0:
                warn.append(r.run_no)
        return {
            "run_count": len(self.runs),
            "totals": total,
            "failed_runs": bad,
            "warned_runs": warn,
            "grade": ("不合格" if bad else "有条件合格" if warn else "合格"),
        }


# ══════════════════════════════════════════════════════════════════════════
def active_rules(config: CheckConfig, all_rules: Optional[List[Rule]] = None) -> List[Rule]:
    rules = all_rules if all_rules is not None else seed_rules()
    if config.rule_ids:
        wanted = set(config.rule_ids)
        rules = [r for r in rules if r.rule_id in wanted]
    return [r for r in rules if r.enabled]


def check_run(
    bundle: RunBundle,
    prev: Optional[RunBundle],
    *,
    config: Optional[CheckConfig] = None,
    rules: Optional[List[Rule]] = None,
    library: Optional[BalanceLibrary] = None,
    custom_extractors: Optional[Dict[str, Dict[str, str]]] = None,
) -> RunResult:
    """Check one 车次 against the rule set."""
    cfg = config or CheckConfig()
    rs = active_rules(cfg, rules)
    lib = library or default_library()

    needed = sorted({r.feature for r in rs})
    feats = extract_features(
        bundle, prev, keys=needed, library=lib,
        tail_contracted=cfg.tail_contracted,
        balance_ranges=cfg.balance_ranges or None,
        custom_extractors=custom_extractors,
    )
    findings = evaluate(rs, feats, mach=bundle.mach)
    return RunResult(
        run_no=bundle.run_no,
        meta=bundle.meta(),
        features=feats,
        findings=findings,
        grade=grade(findings),
        level=worst_level(findings),
        compared_with=prev.run_no if prev else None,
    )


def check_batch(
    bundles: Sequence[RunBundle],
    *,
    config: Optional[CheckConfig] = None,
    rules: Optional[List[Rule]] = None,
    library: Optional[BalanceLibrary] = None,
    custom_extractors: Optional[Dict[str, Dict[str, str]]] = None,
) -> BatchResult:
    """Check a chain of runs in ascending run-number order."""
    cfg = config or CheckConfig()
    ordered = sorted(bundles, key=lambda b: (len(b.run_no), b.run_no))
    results: List[RunResult] = []
    notes: List[str] = []
    prev: Optional[RunBundle] = None

    for b in ordered:
        res = check_run(b, prev, config=cfg, rules=rules, library=library,
                        custom_extractors=custom_extractors)
        if prev is None and len(ordered) > 1:
            res.chain_broken = True
            notes.append(f"车次 {b.run_no} 是本批次第一个车次，无上一车次可比，天平零飘未评定。")
        elif prev is None:
            res.chain_broken = True
        results.append(res)
        # Only advance the chain when this run's ca actually parsed — otherwise
        # the next run must be told which run it was really compared against.
        if b.ca is not None and b.ca.ok:
            prev = b
        else:
            notes.append(f"车次 {b.run_no} 的 ca 文件不可用，零飘比对链在此保持指向车次 "
                         f"{prev.run_no if prev else '—'}。")

    batch = BatchResult(runs=results, config=cfg, notes=notes)
    batch.trends = build_trends(results, window=cfg.trend_window)
    return batch


def load_batch(paths: Sequence[Path | str]) -> List[RunBundle]:
    """Group a mixed drop of files into per-run bundles."""
    return [load_bundle(files) for _, files in group_by_run(paths).items()]


# ══════════════════════════════════════════════════════════════════════════
#  Cross-run trend
# ══════════════════════════════════════════════════════════════════════════
_NELSON_REF = ("Nelson, L.S. (1984), 'The Shewhart Control Chart — Tests for "
               "Special Causes', Journal of Quality Technology 16(4), rule 3；"
               "Western Electric Statistical Quality Control Handbook (1956)")


def build_trends(results: Sequence[RunResult], *, window: int = 5) -> List[Dict[str, Any]]:
    """Per-feature series across the batch, with a monotone-run flag.

    The point of this view is the thing no single-run check can see: a
    quantity that is still inside limits but has moved in one direction for
    several consecutive runs. That is the classic "special cause" signature.
    """
    if not results:
        return []
    keys = sorted({k for r in results for k in r.features})
    out: List[Dict[str, Any]] = []
    for key in keys:
        spec = FEATURE_SPECS.get(key)
        pts = [(r.run_no, r.features[key].value)
               for r in results if key in r.features and r.features[key].available]
        if len(pts) < 2:
            continue
        vals = [v for _, v in pts]
        rising = falling = 1
        best_rise = best_fall = 1
        for i in range(1, len(vals)):
            if vals[i] > vals[i - 1]:
                rising += 1
                falling = 1
            elif vals[i] < vals[i - 1]:
                falling += 1
                rising = 1
            else:
                rising = falling = 1
            best_rise = max(best_rise, rising)
            best_fall = max(best_fall, falling)
        run_len = max(best_rise, best_fall)
        flagged = run_len >= window and len(vals) >= window
        out.append({
            "feature": key,
            "name": spec.name if spec else key,
            "unit": spec.unit if spec else "",
            "runs": [rn for rn, _ in pts],
            "values": [round(v, 6) for v in vals],
            "monotone_run": run_len,
            "trend": ("上升" if best_rise >= best_fall else "下降") if flagged else "无显著趋势",
            "flagged": flagged,
            "reference": _NELSON_REF if flagged else "",
            "note": (f"连续 {run_len} 个车次单调"
                     f"{'上升' if best_rise >= best_fall else '下降'}，"
                     f"达到趋势判据窗口({window})，建议在超限前介入。") if flagged else "",
        })
    return out


# ══════════════════════════════════════════════════════════════════════════
#  Aerodynamic curves (from the da result file)
# ══════════════════════════════════════════════════════════════════════════
#: The default plot the spec asks for: "通常画 CAF 至 MZ 随第一列攻角变化".
DEFAULT_Y_COLUMNS = ("CAF", "CN", "CZ", "CAB", "MX", "MY", "MZ")

#: Chinese labels for the coefficients the UI offers by default.
COLUMN_LABELS: Dict[str, str] = {
    "ALPHA": "攻角 α (°)", "Bs": "侧滑角 β (°)", "GAMA": "滚转角 γ (°)",
    "CAF": "前体轴向力系数 CAF", "CN": "法向力系数 CN", "CZ": "侧向力系数 CZ",
    "CAB": "底部阻力系数 CAB", "MX": "滚转力矩系数 MX", "MY": "偏航力矩系数 MY",
    "MZ": "俯仰力矩系数 MZ", "CA": "轴向力系数 CA", "CD": "阻力系数 CD",
    "CLF": "升力系数 CLF", "CDF": "阻力系数 CDF", "CLCDF": "升阻比 L/D",
    "XCP": "压心位置 XCP", "XCPI": "压心位置(插值) XCPI",
    "CC": "横向力系数 CC", "At": "气动攻角 At (°)", "M": "马赫数 M",
    "Re": "雷诺数 Re (×10⁶)", "CNa": "法向力系数导数 CNα",
    "MZa": "俯仰力矩系数导数 MZα", "CZa": "侧向力系数导数 CZα",
}


def curve_data(
    bundle: RunBundle,
    *,
    x: str = "ALPHA",
    ys: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build a plot payload from the da result file."""
    if bundle.da is None or not bundle.da.ok:
        return {"ok": False, "error": "本车次没有可用的 da(气动结果) 文件"}
    da = bundle.da
    available = da.numeric_columns()
    if x not in da.columns:
        return {"ok": False, "error": f"横轴列「{x}」不存在。可用列：{'、'.join(available)}"}
    wanted = [c for c in (ys or DEFAULT_Y_COLUMNS) if c in da.columns]
    if not wanted:
        return {"ok": False, "error": "没有任何可绘制的纵轴列"}
    xs = da.series(x)
    series = []
    for c in wanted:
        vals = da.series(c)
        n = min(len(xs), len(vals))
        series.append({
            "key": c,
            "label": COLUMN_LABELS.get(c, c),
            "x": xs[:n],
            "y": vals[:n],
        })
    return {
        "ok": True,
        "run_no": bundle.run_no,
        "x_key": x,
        "x_label": COLUMN_LABELS.get(x, x),
        "series": series,
        "available_columns": [{"key": c, "label": COLUMN_LABELS.get(c, c)} for c in available],
        "flow": da.flow,
        "mach": da.mach,
        "model": da.model_name,
    }


def curve_statistics(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic descriptors of each curve — computed, not guessed.

    These are what the LLM is later asked to *narrate*; the numbers themselves
    never come from the model. Slope is an ordinary least-squares fit, which for
    CN(α) and MZ(α) over a linear range is the standard way the derivatives
    CNα / MZα are reported (and the ``da`` file carries the tunnel's own CNa /
    MZa for cross-check).
    """
    out: List[Dict[str, Any]] = []
    for s in payload.get("series", []):
        xs, ys = s["x"], s["y"]
        n = min(len(xs), len(ys))
        if n < 2:
            continue
        xs, ys = xs[:n], ys[:n]
        mx = sum(xs) / n
        my = sum(ys) / n
        sxx = sum((v - mx) ** 2 for v in xs)
        sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
        slope = sxy / sxx if sxx else 0.0
        intercept = my - slope * mx
        ss_tot = sum((v - my) ** 2 for v in ys)
        ss_res = sum((ys[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
        r2 = 1.0 - ss_res / ss_tot if ss_tot else 1.0
        imax = max(range(n), key=lambda i: ys[i])
        imin = min(range(n), key=lambda i: ys[i])
        # Largest deviation from the straight-line fit — where the curve departs
        # from linearity (stall onset, shock-induced break, …).
        dev = [(abs(ys[i] - (slope * xs[i] + intercept)), i) for i in range(n)]
        dmax, idev = max(dev)
        out.append({
            "key": s["key"], "label": s["label"],
            "n": n,
            "slope_per_deg": round(slope, 6),
            "r2": round(r2, 5),
            "min": {"x": xs[imin], "y": round(ys[imin], 6)},
            "max": {"x": xs[imax], "y": round(ys[imax], 6)},
            "range": round(max(ys) - min(ys), 6),
            "max_nonlinearity": {"x": xs[idev], "deviation": round(dmax, 6)},
            "monotone": all(ys[i] <= ys[i + 1] for i in range(n - 1))
                        or all(ys[i] >= ys[i + 1] for i in range(n - 1)),
        })
    return out
