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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    #: Nelson run-rule window for the cross-run trend flag (Nelson's own value
    #: is 7; see app.windtunnel.trend for why a smaller window over-fires).
    trend_window: int = 7

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
    batch.trends = build_trends(results, window=cfg.trend_window,
                                rules=active_rules(cfg, rules))
    return batch


def load_batch(paths: Sequence[Path | str]) -> List[RunBundle]:
    """Group a mixed drop of files into per-run bundles."""
    return [load_bundle(files) for _, files in group_by_run(paths).items()]


# ══════════════════════════════════════════════════════════════════════════
#  Cross-run trend
# ══════════════════════════════════════════════════════════════════════════
def _first_threshold(rules: Optional[Sequence[Rule]], feature: str) -> Optional[float]:
    """Smallest magnitude at which the rule set stops calling a value normal.

    Used as the yardstick for PRACTICAL significance. A drift can be
    statistically certain and still be irrelevant: on this entry the balance
    return-to-zero trend is significant at p=0.0005, yet the whole 130-run
    drift is 0.00024 码 against a first-alarm threshold of 0.003 — 8 % of the
    limit. Reporting that as an alarm trains the operator to ignore alarms.
    """
    if not rules:
        return None
    edges: List[float] = []
    for r in rules:
        if r.feature != feature or not r.enabled:
            continue
        for b in r.bands:
            if b.level == "ok":
                continue
            for v in (b.lo, b.hi):
                if v is not None and abs(v) > 0:
                    edges.append(abs(v))
    return min(edges) if edges else None


def build_trends(
    results: Sequence[RunResult],
    *,
    window: int = 7,
    alpha: float = 0.05,
    hampel_k: float = 3.0,
    rules: Optional[Sequence[Rule]] = None,
    practical_fraction: float = 0.1,
) -> List[Dict[str, Any]]:
    """Per-feature series across the batch, with statistically honest flags.

    See :mod:`app.windtunnel.trend` for why this is a Mann–Kendall /
    Hampel / calibrated-Nelson combination rather than "longest monotone run".
    In short: on the customer's real 130-run entry the naive rule flagged 15 of
    17 features, because a long random series always contains some monotone
    stretch. An alarm that always fires is worse than none.
    """
    from .trend import analyse_series

    if not results:
        return []
    keys = sorted({k for r in results for k in r.features})
    out: List[Dict[str, Any]] = []

    def mach_of(r: RunResult) -> Optional[float]:
        m = r.meta.get("mach")
        return round(float(m), 3) if m else None

    machs = sorted({m for m in (mach_of(r) for r in results) if m is not None})
    multi_mach = len(machs) > 1

    # Does the model configuration itself change across the batch? Grouping by
    # Mach alone is NOT enough: inside one Mach block this entry sweeps the
    # elevator from −25° to +25°, which moves the balance loads by an order of
    # magnitude. Trending a load-driven quantity over that measures the
    # deflection schedule, exactly as trending it over the Mach sweep measured
    # the Mach schedule. When the configuration varies, a state-dependent
    # quantity gets NO trend verdict — its series is still returned for
    # plotting, and the user is pointed at the comparison view, where the
    # configuration is held fixed on purpose.
    config_keys = set()
    for r in results:
        st = r.meta.get("state") if isinstance(r.meta.get("state"), dict) else {}
        if not st:
            continue          # state unknown (no da file) — cannot claim it differs
        config_keys.add(tuple(st.get(k) for k in ("BETA", "dz", "dy", "dx")))
    config_varies = len(config_keys) > 1

    for key in keys:
        spec = FEATURE_SPECS.get(key)
        name = spec.name if spec else key
        unit = spec.unit if spec else ""
        dependent = spec.state_dependent if spec else True

        if dependent and config_varies:
            pts = [(r.run_no, r.features[key].value)
                   for r in results if key in r.features and r.features[key].available]
            if len(pts) >= 2:
                out.append({
                    "feature": key, "name": name, "unit": unit,
                    "runs": [rn for rn, _ in pts],
                    "values": [round(v, 8) for _, v in pts],
                    "scope": "全批次", "state_dependent": True, "analysed": False,
                    "flagged": False, "trend": "未判定", "monotone_run": 0,
                    "outlier_runs": [], "reference": "",
                    "headline": (
                        f"本批次包含 {len(config_keys)} 种模型状态（侧滑角/舵偏角不同），"
                        f"{name}本身就随状态变化，跨车次趋势无法与试验计划区分，"
                        f"故不做趋势判定。请在「多车次对比」中固定状态后比较。"),
                    "note": "",
                    "scope_note": "状态相关量 + 多构型批次 → 不做趋势判定（避免把试验计划当成设备漂移）",
                    "mann_kendall": {}, "hampel": {}, "nelson": {},
                })
            continue

        # A state-dependent quantity in a single-configuration batch may still
        # only be trended within one Mach.
        groups: List[Tuple[str, List[RunResult]]]
        if dependent and multi_mach:
            groups = [(f"Ma={m:g}", [r for r in results if mach_of(r) == m]) for m in machs]
        else:
            groups = [("全批次", list(results))]

        for scope, subset in groups:
            pts = [(r.run_no, r.features[key].value)
                   for r in subset if key in r.features and r.features[key].available]
            if len(pts) < 4:
                # Say so rather than dropping the series. A quantity that
                # silently vanishes from the trend view is indistinguishable
                # from one that was checked and found clean.
                if pts:
                    out.append({
                        "feature": key, "name": name, "unit": unit,
                        "runs": [rn for rn, _ in pts],
                        "values": [round(v, 8) for _, v in pts],
                        "scope": scope, "state_dependent": dependent,
                        "analysed": False, "flagged": False,
                        "trend": "未判定", "monotone_run": 0, "outlier_runs": [],
                        "reference": "",
                        "headline": (f"{scope} 内只有 {len(pts)} 个可用车次，"
                                     f"少于趋势检验所需的 4 个，未做判定。"),
                        "note": "", "scope_note": "样本不足，未做趋势判定",
                        "mann_kendall": {}, "hampel": {}, "nelson": {},
                    })
                continue
            rep = analyse_series(
                key, name, unit, [rn for rn, _ in pts], [v for _, v in pts],
                alpha=alpha, hampel_k=hampel_k, nelson_window=window,
                practical_limit=_first_threshold(rules, key),
                practical_fraction=practical_fraction,
            )
            d = rep.to_dict()
            d["scope"] = scope
            d["state_dependent"] = dependent
            d["analysed"] = True

            d["scope_note"] = (
                "零点类量与试验状态无关，可在全批次上直接比较。" if not dependent else
                (f"本量随试验状态变化，趋势仅在同一马赫数分组（{scope}）内有意义。"
                 if multi_mach else "本批次为单一马赫数，可直接比较。")
            )
            out.append(d)
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
