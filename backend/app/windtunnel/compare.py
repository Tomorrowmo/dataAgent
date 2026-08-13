"""Multi-run comparison — the analysis mode wind-tunnel work actually lives in.

The single-run view answers "is this run good?". Everything else an
aerodynamicist does is a *comparison*: this configuration against that one,
this Mach against that one, this control deflection against the undeflected
baseline. The customer's own desktop tool is built entirely around that, and
their 20260225 requirement note asks for it explicitly.

Four capabilities, all built on one primitive (put runs on a common abscissa,
then subtract if asked):

``curves_by_run``
    Y(X) for a set of runs on one chart, X being α or **any coefficient** —
    because ``CD`` versus ``CN`` is the drag polar and ``MZ`` versus ``CN`` is
    the longitudinal stability plot whose slope is the static margin. Those are
    not "a different x-axis", they are two standard deliverables.

``curves_by_state``
    Y versus a *state* variable (Mach, β, φ, δz, δy, δx) at selected angles of
    attack. The requirement note's "随马赫数、模型状态变化". The chosen α values
    generally do not sit on the measured grid, so values are interpolated —
    never extrapolated.

``delta`` / ``ratio`` modes
    Everything above can be referenced to a baseline run: ``Y − Y_base`` or
    ``Y / Y_base``. For this dataset — a control-effectiveness matrix where each
    run deflects one surface away from a δ=0 baseline — the delta IS the
    control increment, which is the quantity the test exists to measure.

``control_effectiveness``
    Automates that pairing: for each (Mach, β) block, take the δ=0 run as
    baseline and report ΔY and ΔY/Δδ per deflected run.

Interpolation policy: linear, and **never extrapolating**. A comparison built
partly from extrapolated values would silently invent data — the same class of
error as the legacy tool's absolute-value extrapolation metric.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .parsers import RunBundle

#: State variables offerable as an abscissa, with display labels. These mirror
#: the buttons on the customer's own tool (D5–D8 / φ / β / M).
STATE_VARS: Dict[str, str] = {
    "M": "马赫数 M",
    "BETA": "侧滑角 β (°)",
    "PHI": "滚转角 φ (°)",
    "dz": "升降舵 δz (°)",
    "dy": "方向舵 δy (°)",
    "dx": "副翼 δx (°)",
}

MODES = ("value", "delta", "ratio")


def _interp(xs: Sequence[float], ys: Sequence[float], xt: float) -> Optional[float]:
    """Linear interpolation with NO extrapolation."""
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    pts = sorted(zip(xs[:n], ys[:n]))
    lo, hi = pts[0][0], pts[-1][0]
    if xt < lo - 1e-9 or xt > hi + 1e-9:
        return None
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 - 1e-9 <= xt <= x1 + 1e-9:
            if abs(x1 - x0) < 1e-12:
                return y0
            return y0 + (y1 - y0) * (xt - x0) / (x1 - x0)
    return None


def run_state(b: RunBundle) -> Dict[str, Optional[float]]:
    """The legend row for a run — what distinguishes it from its neighbours."""
    st = (b.da.state if (b.da and b.da.state) else {})
    return {
        "M": round(b.mach, 4) if b.mach else None,
        "BETA": st.get("BETA"),
        "PHI": st.get("PHI"),
        "dz": st.get("dz"),
        "dy": st.get("dy"),
        "dx": st.get("dx"),
        "XU": st.get("XU"),
    }


def state_text(b: RunBundle) -> str:
    s = run_state(b)
    bits = [f"Ma={s['M']:g}"] if s["M"] is not None else []
    for k, sym in (("BETA", "β"), ("PHI", "φ"), ("dz", "δz"), ("dy", "δy"), ("dx", "δx")):
        if s[k] is not None:
            bits.append(f"{sym}={s[k]:g}")
    return " ".join(bits)


def available_columns(bundles: Sequence[RunBundle]) -> List[Dict[str, str]]:
    """Every coefficient present in ALL selected runs — a column that only some
    runs have would silently drop curves from the chart."""
    sets = [set(b.da.columns) for b in bundles if b.da and b.da.ok]
    if not sets:
        return []
    common = set.intersection(*sets)
    from .pipeline import COLUMN_LABELS
    ordered = [c for c in (bundles[0].da.columns if bundles[0].da else []) if c in common]
    return [{"key": c, "label": COLUMN_LABELS.get(c, c)} for c in ordered]


def sort_runs(bundles: Sequence[RunBundle], keys: Sequence[str]) -> List[RunBundle]:
    """Order runs by state — the requirement note's 「根据侧滑滚转舵偏角排序」.

    Reading a 13-curve chart depends entirely on the curves being in a
    meaningful order; run number is chronological, not physical.
    """
    order = [k for k in keys if k in STATE_VARS] or ["M", "BETA", "PHI", "dz", "dy", "dx"]

    def key(b: RunBundle):
        s = run_state(b)
        return tuple((s.get(k) is None, s.get(k) if s.get(k) is not None else 0.0)
                     for k in order) + (b.run_no,)

    return sorted(bundles, key=key)


# ══════════════════════════════════════════════════════════════════════════
#  1. Y(X) per run
# ══════════════════════════════════════════════════════════════════════════
def curves_by_run(
    bundles: Sequence[RunBundle],
    *,
    x: str = "ALPHA",
    ys: Sequence[str] = ("CN",),
    baseline: Optional[str] = None,
    mode: str = "value",
    sort_by: Sequence[str] = (),
) -> Dict[str, Any]:
    """One curve per (run, coefficient).

    ``x`` may be ``ALPHA`` or any coefficient (drag polar: x=CN, y=CD).
    ``mode='delta'|'ratio'`` references every run to ``baseline``; the baseline
    is resampled onto each run's own abscissa so runs with different sweep
    schedules still subtract correctly.
    """
    if mode not in MODES:
        return {"ok": False, "error": f"未知的对比模式「{mode}」"}
    usable = [b for b in bundles if b.da and b.da.ok]
    if not usable:
        return {"ok": False, "error": "所选车次都没有可用的 da 结果文件"}

    base = None
    if mode in ("delta", "ratio"):
        base = next((b for b in usable if b.run_no == baseline), None)
        if base is None:
            return {"ok": False, "error": f"基准车次 {baseline} 不在所选车次中"}

    usable = sort_runs(usable, sort_by)
    missing_x = [b.run_no for b in usable if x not in b.da.columns]
    if missing_x:
        return {"ok": False,
                "error": f"横轴列「{x}」在这些车次中不存在：{'、'.join(missing_x[:6])}"}

    series: List[Dict[str, Any]] = []
    notes: List[str] = []
    for b in usable:
        xs = b.da.series(x)
        for c in ys:
            if c not in b.da.columns:
                notes.append(f"车次 {b.run_no} 没有 {c} 列，已跳过")
                continue
            raw = b.da.series(c)
            n = min(len(xs), len(raw))
            xv, yv = list(xs[:n]), list(raw[:n])
            if base is not None:
                if b.run_no == base.run_no and mode == "ratio":
                    continue  # baseline / baseline == 1, adds nothing
                bx, by = base.da.series(x), base.da.series(c)
                out_x, out_y = [], []
                for xi, yi in zip(xv, yv):
                    bi = _interp(bx, by, xi)
                    if bi is None:
                        continue  # outside the baseline's range — do not invent
                    if mode == "delta":
                        out_x.append(xi)
                        out_y.append(yi - bi)
                    elif abs(bi) > 1e-12:
                        out_x.append(xi)
                        out_y.append(yi / bi)
                if len(out_x) < len(xv):
                    notes.append(
                        f"车次 {b.run_no} 有 {len(xv) - len(out_x)} 个点超出基准车次的"
                        f"{x} 范围，按“不外插”原则舍弃")
                xv, yv = out_x, out_y
            if not xv:
                continue
            series.append({
                "run_no": b.run_no,
                "coefficient": c,
                "label": f"{b.run_no} · {c}" + (f" − {base.run_no}" if mode == "delta"
                                                else (f" / {base.run_no}" if mode == "ratio" else "")),
                "state": run_state(b),
                "state_text": state_text(b),
                "x": xv, "y": yv,
            })

    from .pipeline import COLUMN_LABELS
    return {
        "ok": True,
        "mode": mode,
        "baseline": base.run_no if base else None,
        "x_key": x,
        "x_label": COLUMN_LABELS.get(x, x),
        "y_keys": list(ys),
        "series": series,
        "legend": [{"run_no": b.run_no, **run_state(b)} for b in usable],
        "available_columns": available_columns(usable),
        "notes": sorted(set(notes)),
    }


# ══════════════════════════════════════════════════════════════════════════
#  2. Y(state) at selected angles of attack
# ══════════════════════════════════════════════════════════════════════════
def curves_by_state(
    bundles: Sequence[RunBundle],
    *,
    state_var: str = "M",
    ys: Sequence[str] = ("CN",),
    alphas: Sequence[float] = (0.0,),
    baseline: Optional[str] = None,
    mode: str = "value",
    group_label: str = "",
) -> Dict[str, Any]:
    """Y versus Mach / β / φ / δz / δy / δx, one curve per (coefficient, α).

    Each point is that run's coefficient **interpolated to the requested α**;
    runs whose sweep does not cover the α are omitted rather than extrapolated,
    and the omission is reported.
    """
    if state_var not in STATE_VARS:
        return {"ok": False,
                "error": f"未知的状态横轴「{state_var}」，可选：{'、'.join(STATE_VARS)}"}
    usable = [b for b in bundles if b.da and b.da.ok]
    if not usable:
        return {"ok": False, "error": "所选车次都没有可用的 da 结果文件"}

    base = None
    if mode in ("delta", "ratio"):
        base = next((b for b in usable if b.run_no == baseline), None)
        if base is None:
            return {"ok": False, "error": f"基准车次 {baseline} 不在所选车次中"}

    series: List[Dict[str, Any]] = []
    notes: List[str] = []
    for c in ys:
        for a in alphas:
            pts: List[Tuple[float, float, str]] = []
            for b in usable:
                sv = run_state(b).get(state_var)
                if sv is None or c not in b.da.columns:
                    continue
                v = _interp(b.da.series("ALPHA"), b.da.series(c), a)
                if v is None:
                    notes.append(f"车次 {b.run_no} 的攻角范围不含 α={a:g}°，已跳过（不外插）")
                    continue
                if base is not None:
                    bv = _interp(base.da.series("ALPHA"), base.da.series(c), a)
                    if bv is None:
                        continue
                    if mode == "delta":
                        v = v - bv
                    elif abs(bv) > 1e-12:
                        v = v / bv
                    else:
                        continue
                pts.append((float(sv), v, b.run_no))
            if not pts:
                continue
            pts.sort(key=lambda t: t[0])
            series.append({
                "coefficient": c,
                "alpha": a,
                "label": (f"{group_label}·" if group_label else "") + f"{c} @ α={a:g}°",
                "group": group_label,
                "x": [p[0] for p in pts],
                "y": [p[1] for p in pts],
                "runs": [p[2] for p in pts],
            })

    from .pipeline import COLUMN_LABELS
    return {
        "ok": True,
        "mode": mode,
        "baseline": base.run_no if base else None,
        "x_key": state_var,
        "x_label": STATE_VARS[state_var],
        "alphas": list(alphas),
        "series": series,
        "available_columns": available_columns(usable),
        "notes": sorted(set(notes)),
    }


# ══════════════════════════════════════════════════════════════════════════
#  3. Control-surface effectiveness
# ══════════════════════════════════════════════════════════════════════════
#: Which coefficient each surface primarily drives — used to pick the headline
#: derivative. Elevator → pitching moment / normal force; rudder → yawing;
#: aileron → rolling.
SURFACE_PRIMARY: Dict[str, Tuple[str, ...]] = {
    "dz": ("CN", "MZG1"),
    "dy": ("CZ", "MYG1"),
    "dx": ("MXG1",),
}


def control_effectiveness(
    bundles: Sequence[RunBundle],
    *,
    surface: str = "dz",
    alphas: Sequence[float] = (0.0,),
    coeffs: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Baseline-referenced control increments and their derivatives.

    For each (Mach, β) block the run with all deflections zero is the baseline;
    every run that deflects ONLY ``surface`` contributes
    ``ΔY = Y(δ) − Y(0)`` and ``ΔY/Δδ`` at the requested angles of attack.

    Runs that move more than one surface are excluded — mixing them in would
    attribute another surface's effect to this one.
    """
    if surface not in ("dz", "dy", "dx"):
        return {"ok": False, "error": f"未知舵面「{surface}」"}
    wanted = list(coeffs or SURFACE_PRIMARY.get(surface, ("CN",)))
    usable = [b for b in bundles if b.da and b.da.ok]
    others = [s for s in ("dz", "dy", "dx") if s != surface]

    blocks: Dict[Tuple[Any, Any], List[RunBundle]] = {}
    for b in usable:
        s = run_state(b)
        blocks.setdefault((s["M"], s["BETA"]), []).append(b)

    rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    for (mach, beta), group in sorted(blocks.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0)):
        base = next((b for b in group
                     if all((run_state(b).get(s) or 0.0) == 0.0 for s in ("dz", "dy", "dx"))), None)
        if base is None:
            notes.append(f"Ma={mach:g} β={beta:g} 区块没有 δ 全零的基准车次，跳过")
            continue
        for b in group:
            st = run_state(b)
            d = st.get(surface) or 0.0
            if d == 0.0:
                continue
            if any((st.get(o) or 0.0) != 0.0 for o in others):
                continue  # multi-surface run — not attributable to this surface
            for c in wanted:
                if c not in b.da.columns or c not in base.da.columns:
                    continue
                for a in alphas:
                    v = _interp(b.da.series("ALPHA"), b.da.series(c), a)
                    bv = _interp(base.da.series("ALPHA"), base.da.series(c), a)
                    if v is None or bv is None:
                        continue
                    rows.append({
                        "mach": mach, "beta": beta, "alpha": a,
                        "surface": surface, "deflection": d,
                        "run_no": b.run_no, "baseline_run": base.run_no,
                        "coefficient": c,
                        "value": round(v, 8), "baseline_value": round(bv, 8),
                        "delta": round(v - bv, 8),
                        "derivative_per_deg": round((v - bv) / d, 8),
                    })
    return {
        "ok": True, "surface": surface, "coefficients": wanted,
        "alphas": list(alphas), "rows": rows, "notes": sorted(set(notes)),
        "method": "ΔY = Y(δ) − Y(δ=0) 于同一 (Ma, β) 区块内，攻角处线性插值，不外插；"
                  "导数 = ΔY/Δδ",
    }


def symmetry_check(
    bundles: Sequence[RunBundle],
    *,
    surface: str = "dz",
    alphas: Sequence[float] = (0.0,),
    coeffs: Optional[Sequence[str]] = None,
    k_mad: float = 3.0,
) -> Dict[str, Any]:
    """Compare +delta and -delta increments across the entry.

    A symmetric model on a symmetric sting gives mirror increments:
    dY(+delta) ~= -dY(-delta). Asymmetry points at model build, surface rigging
    or installation alignment — an error class no single-run check can see, and
    one that a +/-deflection matrix is laid out to expose.

    The comparison is deliberately **against the other pairs in this entry**,
    not against zero. Real configurations are never perfectly symmetric, so a
    fixed "15 % is bad" threshold flagged 13 of 30 pairs here — noise. What
    carries information is a pair far more asymmetric than its siblings, so
    each pair is scored against the median and MAD of all pairs (Hampel's
    robust identifier; Davies & Gather 1993). Every pair's raw asymmetry is
    returned either way: the engineer should see the distribution, not just
    the tail.
    """
    eff = control_effectiveness(bundles, surface=surface, alphas=alphas, coeffs=coeffs)
    if not eff.get("ok"):
        return eff
    by_key: Dict[Tuple[Any, Any, Any, str, float], Dict[float, Dict[str, Any]]] = {}
    for r in eff["rows"]:
        k = (r["mach"], r["beta"], r["alpha"], r["coefficient"], abs(r["deflection"]))
        by_key.setdefault(k, {})[r["deflection"]] = r

    pairs: List[Dict[str, Any]] = []
    for (mach, beta, alpha, c, mag), d in sorted(by_key.items(), key=lambda kv: str(kv[0])):
        pos, neg = d.get(mag), d.get(-mag)
        if pos is None or neg is None:
            continue
        tot = pos["delta"] + neg["delta"]          # 0 if perfectly antisymmetric
        scale = 0.5 * (abs(pos["delta"]) + abs(neg["delta"]))
        asym = abs(tot) / scale if scale > 1e-12 else 0.0
        pairs.append({
            "mach": mach, "beta": beta, "alpha": alpha, "coefficient": c,
            "deflection": mag,
            "run_pos": pos["run_no"], "run_neg": neg["run_no"],
            "delta_pos": pos["delta"], "delta_neg": neg["delta"],
            "sum": round(tot, 8),
            "asymmetry": round(asym, 4),
            "flagged": False, "score": None,
        })

    vals = sorted(x["asymmetry"] for x in pairs)
    med = mad = 0.0
    if vals:
        n = len(vals)
        med = vals[n // 2] if n % 2 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])
        devs = sorted(abs(v - med) for v in vals)
        mad = devs[n // 2] if n % 2 else 0.5 * (devs[n // 2 - 1] + devs[n // 2])
    sigma = 1.4826 * mad
    for item in pairs:
        if sigma > 0:
            item["score"] = round((item["asymmetry"] - med) / sigma, 2)
            item["flagged"] = bool(item["score"] > k_mad)
    flagged = [x for x in pairs if x["flagged"]]
    return {
        "ok": True, "surface": surface, "k_mad": k_mad,
        "median_asymmetry": round(med, 4),
        "robust_sigma": round(sigma, 4),
        "pairs": pairs, "flagged": flagged,
        "method": ("对称性指标 = |dY(+d)+dY(-d)| / mean(|dY(+d)|,|dY(-d)|)，理想反对称时为 0。"
                   "判异不与 0 比，而与本批次全部 +/-d 组合的中位数/MAD 比"
                   "（Hampel 稳健识别，Davies & Gather 1993）——真实构型从不完全对称，"
                   "与 0 比会把正常的构型不对称当成故障。"),
        "note": ((f"本批次 {len(pairs)} 个 +/-{surface} 组合的不对称度中位数 {med:.1%}；"
                  f"其中 {len(flagged)} 个显著高于同批次水平（>{k_mad} sigma），建议优先复查。")
                 if flagged else
                 (f"本批次 {len(pairs)} 个 +/-{surface} 组合的不对称度中位数 {med:.1%}，"
                  f"没有任何组合显著偏离同批次水平。")),
    }


def deflection_response(
    bundles: Sequence[RunBundle],
    *,
    surface: str = "dz",
    alphas: Sequence[float] = (0.0,),
    coeffs: Optional[Sequence[str]] = None,
    linear_range: float = 15.0,
) -> Dict[str, Any]:
    """The delta-Y versus deflection response curve, per (Mach, beta) block.

    DELIBERATELY DESCRIPTIVE, NOT AN ALARM. An earlier version fitted a line
    through every deflection and flagged the residuals; on this entry it
    reported 87 of 372 points as suspect, with "scores" up to 132 sigma. Both
    halves of that were wrong:

    * Control effectiveness **saturates** at large deflection — the +/-25 deg
      points departing from a line through +/-5 and +/-15 is real aerodynamics,
      not a data defect.
    * With three sibling points the residual scatter has one degree of freedom,
      so the sigma it produces is meaningless and the score explodes.

    What is genuinely useful is the curve itself plus two honest descriptors:
    the **linear-range derivative** (fitted only over |delta| <= linear_range,
    through the origin, since dY(0)=0 by construction) and a **saturation
    ratio** — how much of the linear-range prediction the largest deflection
    actually delivers. An engineer reads those in a second; a threshold on them
    would be inventing a standard nobody wrote.
    """
    eff = control_effectiveness(bundles, surface=surface, alphas=alphas, coeffs=coeffs)
    if not eff.get("ok"):
        return eff

    groups: Dict[Tuple[Any, Any, Any, str], List[Dict[str, Any]]] = {}
    for r in eff["rows"]:
        groups.setdefault((r["mach"], r["beta"], r["alpha"], r["coefficient"]), []).append(r)

    blocks: List[Dict[str, Any]] = []
    for (mach, beta, alpha, c), rows in sorted(groups.items(), key=lambda kv: str(kv[0])):
        rows.sort(key=lambda r: r["deflection"])
        lin = [r for r in rows if abs(r["deflection"]) <= linear_range]
        slope = None
        if len(lin) >= 2:
            num = sum(r["deflection"] * r["delta"] for r in lin)
            den = sum(r["deflection"] ** 2 for r in lin)
            slope = num / den if den else None      # through the origin
        biggest = max(rows, key=lambda r: abs(r["deflection"]))
        sat = None
        if slope not in (None, 0.0):
            pred = slope * biggest["deflection"]
            if abs(pred) > 1e-12:
                sat = biggest["delta"] / pred
        blocks.append({
            "mach": mach, "beta": beta, "alpha": alpha, "coefficient": c,
            "baseline_run": rows[0]["baseline_run"],
            "deflections": [r["deflection"] for r in rows],
            "deltas": [r["delta"] for r in rows],
            "runs": [r["run_no"] for r in rows],
            "linear_slope_per_deg": (round(slope, 8) if slope is not None else None),
            "linear_range_deg": linear_range,
            "max_deflection": biggest["deflection"],
            "saturation_ratio": (round(sat, 4) if sat is not None else None),
        })
    return {
        "ok": True, "surface": surface, "blocks": blocks,
        "method": (f"dY = Y(delta) - Y(0) 同区块内；线性段导数为过原点最小二乘拟合，"
                   f"仅用 |delta| <= {linear_range:g} 度；饱和比 = 最大舵偏实测 dY / 线性段外推值。"
                   "本项为描述性输出，不设告警阈值——大舵偏饱和是真实气动现象。"),
    }


# ══════════════════════════════════════════════════════════════════════════
#  4. Export
# ══════════════════════════════════════════════════════════════════════════
def export_rows(payload: Dict[str, Any]) -> Tuple[List[str], List[List[Any]]]:
    """Flatten a chart payload into a table for CSV / Excel download.

    The requirement note asks for 「保存数据至 excel」 — plotting without being
    able to hand someone the numbers is half a feature.
    """
    series = payload.get("series") or []
    if not series:
        return [], []
    xkey = payload.get("x_label") or payload.get("x_key") or "X"
    header = [xkey]
    cols: List[Dict[float, float]] = []
    xs_all: List[float] = []
    for s in series:
        header.append(s.get("label") or s.get("coefficient") or "Y")
        m = {round(x, 6): y for x, y in zip(s["x"], s["y"])}
        cols.append(m)
        xs_all.extend(m.keys())
    grid = sorted(set(xs_all))
    rows = [[x] + [c.get(x, "") for c in cols] for x in grid]
    return header, rows


def to_csv(payload: Dict[str, Any]) -> str:
    import csv
    import io
    header, rows = export_rows(payload)
    buf = io.StringIO()
    w = csv.writer(buf)
    meta = []
    if payload.get("mode") and payload["mode"] != "value":
        meta.append(f"对比模式={payload['mode']}  基准车次={payload.get('baseline')}")
    for s in payload.get("series", []):
        if s.get("state_text"):
            meta.append(f"{s.get('label')}: {s['state_text']}")
    for m in dict.fromkeys(meta):
        w.writerow([f"# {m}"])
    if header:
        w.writerow(header)
        w.writerows(rows)
    return buf.getvalue()
