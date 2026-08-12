"""Feature extractors — the *measurement* half of a quality check.

THE CENTRAL DESIGN DECISION
---------------------------
In the customer's existing scripts, the measured quantity and its pass/fail
threshold live in the same Python file (``mark1 = 0.005``). Changing a limit
therefore means editing code, and the twelve Markdown "rule" documents are
decoration — they are only consulted afterwards, by a similarity search, to
*explain* a verdict that was already made. That similarity search is how the
demo ended up filing a 天平零飘 reading under 「天平回零异常诊断」 with a
"50.51% match".

Here the two halves are split:

* **this module** turns files into named, unit-carrying numbers and nothing
  else — no thresholds, no verdicts;
* :mod:`app.windtunnel.rules` maps a feature key to bands and verdicts, as
  *data* the user can edit.

A rule therefore references a feature by key. That binding is explicit, so a
reading can never be diagnosed against the wrong rule.

Feature values are reported in the unit the rule book uses:

* balance raw codes — dimensionless counts, as recorded
* pressures — **mmH2O** (== kgf/m^2); see :mod:`app.windtunnel.units`
* angles — degrees
* temperatures — degC
* loads — percent of the balance's rated range
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .balance import BalanceLibrary
from .parsers import BALANCE_UNITS, PRESSURE_ZERO_COLS, RunBundle
from .units import mach_from_pressure_ratio, mpa_to_mmh2o


@dataclass
class FeatureSpec:
    """Static description of one measurable quantity."""

    key: str
    name: str
    unit: str
    #: Which source files must be present for this feature to be computable.
    requires: List[str] = field(default_factory=list)
    #: True when the value can only be produced by comparing with the previous
    #: run (balance zero drift). Callers must supply ``prev``.
    needs_prev_run: bool = False
    description: str = ""
    #: How the number is obtained — shown in the report so a reviewer can audit
    #: the verdict without reading source.
    method: str = ""


@dataclass
class FeatureValue:
    key: str
    name: str
    unit: str
    value: Optional[float]
    #: "ok" — computed; "unavailable" — inputs missing (never silently 0).
    status: str = "ok"
    detail: str = ""
    #: Extra numbers worth showing (per-unit breakdown, the row it came from…).
    extras: Dict[str, Any] = field(default_factory=dict)
    method: str = ""

    @property
    def available(self) -> bool:
        return self.status == "ok" and self.value is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "unit": self.unit,
            "value": self.value,
            "status": self.status,
            "detail": self.detail,
            "extras": self.extras,
            "method": self.method,
        }


FEATURE_SPECS: Dict[str, FeatureSpec] = {}


def _spec(**kw) -> FeatureSpec:
    s = FeatureSpec(**kw)
    FEATURE_SPECS[s.key] = s
    return s


_spec(
    key="balance_zero_drift", name="天平零飘量", unit="码",
    requires=["ca"], needs_prev_run=True,
    description="本车次初零与上一车次初零在六个天平单元上的最大差值。",
    method="max over units of |zero_start(this)[u] - zero_start(prev)[u]|",
)
_spec(
    key="balance_zero_near_17", name="天平零点接近满码(17)的最大接近度", unit="码",
    requires=["ca"],
    description="任一天平单元初零绝对值与 17 的接近程度，用于识别信号线断。",
    method="max over units of |zero_start[u]| where ||zero_start[u]|-17| < 1",
)
_spec(
    key="balance_code_jump", name="天平最大跑码跳动量", unit="码",
    requires=["ca"],
    description="相邻攻角点之间六个天平单元读数增量的最大绝对值。",
    method="max over blow points j, units u of |code[j+1][u] - code[j][u]|",
)
_spec(
    key="balance_code_span_min", name="天平跑码量最小单元幅值", unit="码",
    requires=["ca"],
    description="各单元相对零点基线的最大偏移中的最小值——用于识别单元电源线断。",
    method="min over units u of max_j |code[j][u] - (zero_start[u]+zero_end[u])/2|",
)
_spec(
    key="balance_return_zero", name="天平最大不回零量", unit="码",
    requires=["ca"],
    description="试验前后两次零点读数在六个单元上的最大差值。",
    method="max over units of |zero_start[u] - zero_end[u]|",
)
_spec(
    key="base_pressure_lr_diff", name="左右底压差最大值", unit="mmH2O",
    requires=["ca"],
    description="吹风段左右底压读数之差的最大绝对值。",
    method="max over blow points of |PL - PR|, MPa→mmH2O",
)
_spec(
    key="pressure_zero_spread", name="压力传感器零点最大偏差", unit="mmH2O",
    requires=["ca"],
    description="五个压力传感器初零读数与其平均值的最大偏差。",
    method="max over sensors of |p0[i] - mean(p0)|, MPa→mmH2O",
)
_spec(
    key="mach_deviation", name="实际与名义马赫数最大偏差", unit="-",
    requires=["ca"],
    description="按等熵关系由总/静压算出的马赫数与名义马赫数的最大偏差。",
    method="max over blow points of |M(P0/P8) - M_nominal|, NACA TR-1135 eq.(44)",
)
_spec(
    key="base_vs_atm_min_gap", name="底压与大气压最小差值", unit="mmH2O",
    requires=["pa"],
    description="左右底压与同点大气压差值的最大值中的较小者；过小说明底压管堵或未接。",
    method="min(max_j|PL-Pa|, max_j|PR-Pa|) over blow points",
)
_spec(
    key="base_vs_static_min_gap", name="底压与来流静压最小差值", unit="mmH2O",
    requires=["pa"],
    description="左右底压与来流静压差值的最大值中的较小者；过小说明底压管漏或未接。仅适用于尾部非收缩外形。",
    method="min(max_j|PL-P8|, max_j|PR-P8|) over blow points",
)
_spec(
    key="base_pressure_gradient", name="底压跑码最大突变率", unit="mmH2O/deg",
    requires=["pa"],
    description="左右底压对攻角的最大变化率（跨两个采集点差分，规避攻角间隔不均导致的误报）。",
    method="max over j of |P[j+2]-P[j]| / |alpha[j+2]-alpha[j]|",
)
_spec(
    key="elastic_alpha", name="攻角方向弹性变形最大值", unit="deg",
    requires=["pa"], description="模型-支杆系统在攻角方向的最大弹性角。",
    method="max_j |alpha_e[j]| from 弹性角修正 table",
)
_spec(
    key="elastic_beta", name="侧滑方向弹性变形最大值", unit="deg",
    requires=["pa"], description="模型-支杆系统在侧滑方向的最大弹性角。",
    method="max_j |beta_e[j]|",
)
_spec(
    key="elastic_gamma", name="滚转方向弹性变形最大值", unit="deg",
    requires=["pa"], description="模型-支杆系统在滚转方向的最大弹性角。",
    method="max_j |gamma_e[j]|",
)
_spec(
    key="alpha_extrapolation", name="攻角外插最大角度", unit="deg",
    requires=["pa"],
    description="插值输出攻角超出实测攻角范围的最大量；0 表示全部为内插。",
    method="max(0, alpha_meas_min - alpha_out_min, alpha_out_max - alpha_meas_max)",
)
_spec(
    key="balance_load_ratio", name="天平载荷占量程最大比例", unit="%",
    requires=["pa"],
    description="六个天平单元气动载荷峰值占各自额定量程的最大百分比。",
    method="max over units of 100 * max_j|load[j][u]| / rated_range[u]",
)
_spec(
    key="total_temp_zero_diff", name="总温与室温零点差", unit="degC",
    requires=["ca"], description="试验前总温传感器与室温传感器读数之差。",
    method="|To - t| on the pre-run zero row",
)


# ══════════════════════════════════════════════════════════════════════════
#  helpers
# ══════════════════════════════════════════════════════════════════════════
def _unavailable(key: str, why: str) -> FeatureValue:
    s = FEATURE_SPECS[key]
    return FeatureValue(key=key, name=s.name, unit=s.unit, value=None,
                        status="unavailable", detail=why, method=s.method)


def _ok(key: str, value: float, detail: str = "", **extras) -> FeatureValue:
    s = FEATURE_SPECS[key]
    return FeatureValue(key=key, name=s.name, unit=s.unit, value=float(value),
                        detail=detail, extras=extras, method=s.method)


def _pa_ca_echo_cols(pa) -> Optional[Dict[str, List[float]]]:
    """Pull the pressure/alpha series out of the pa report's CA echo.

    The echo block is already in kgf/m^2 (== mmH2O), and it excludes nothing —
    row 0 is the pre-run zero and the last row is the post-run zero, matching
    the raw ca file. Blow points are the rows in between.
    """
    if pa is None or not pa.ca_echo.rows:
        return None
    rows = pa.ca_echo.rows
    blow = rows[1:-1] if len(rows) >= 3 else rows
    if not blow:
        return None
    return {
        "alpha": [r[0] for r in blow],
        "PL": [r[7] for r in blow],
        "PR": [r[9] for r in blow],
        "Pa": [r[12] for r in blow],
        "P8": [r[13] for r in blow],
    }


# ══════════════════════════════════════════════════════════════════════════
#  extractors — one per feature key
# ══════════════════════════════════════════════════════════════════════════
def f_balance_zero_drift(b: RunBundle, prev: Optional[RunBundle], **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("balance_zero_drift", "缺少可用的 ca 文件")
    if prev is None or prev.ca is None or not prev.ca.ok:
        return _unavailable(
            "balance_zero_drift",
            "零飘需与上一车次比对；本次未提供上一车次的 ca 文件（连续车次链在此断开）",
        )
    cur, old = b.ca.zero_start, prev.ca.zero_start
    per_unit = {}
    for i, u in enumerate(BALANCE_UNITS, start=1):
        if len(cur) > i and len(old) > i:
            per_unit[u] = abs(cur[i] - old[i])
    if not per_unit:
        return _unavailable("balance_zero_drift", "零点行列数不足")
    worst = max(per_unit, key=per_unit.get)
    return _ok("balance_zero_drift", per_unit[worst],
               detail=f"最大零飘出现在 {worst} 单元（对比车次 {prev.run_no}）",
               per_unit={k: round(v, 6) for k, v in per_unit.items()},
               prev_run=prev.run_no, worst_unit=worst)


def f_balance_zero_near_17(b: RunBundle, prev=None, **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("balance_zero_near_17", "缺少可用的 ca 文件")
    z = b.ca.zero_start
    best: Optional[float] = None
    unit = ""
    for i, u in enumerate(BALANCE_UNITS, start=1):
        if len(z) <= i:
            continue
        v = abs(z[i])
        if abs(v - 17.0) < 1.0 and (best is None or v > best):
            best, unit = v, u
    if best is None:
        return _ok("balance_zero_near_17", 0.0, detail="没有任何单元的初零接近满码 17")
    return _ok("balance_zero_near_17", best, detail=f"{unit} 单元初零为 {best:.4f}，接近满码 17",
               unit_name=unit)


def f_balance_code_jump(b: RunBundle, prev=None, **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("balance_code_jump", "缺少可用的 ca 文件")
    blow = b.ca.blow_rows
    if len(blow) < 2:
        return _unavailable("balance_code_jump", "吹风点不足 2 个，无法计算相邻增量")
    worst, worst_unit, worst_at = 0.0, "", 0
    for j in range(len(blow) - 1):
        for i, u in enumerate(BALANCE_UNITS, start=1):
            if len(blow[j]) <= i or len(blow[j + 1]) <= i:
                continue
            t = abs(blow[j + 1][i] - blow[j][i])
            if t > worst:
                worst, worst_unit, worst_at = t, u, j
    return _ok("balance_code_jump", worst,
               detail=f"最大跳动出现在 {worst_unit} 单元，攻角 {blow[worst_at][0]:.2f}° → "
                      f"{blow[worst_at + 1][0]:.2f}°",
               worst_unit=worst_unit)


def f_balance_code_span_min(b: RunBundle, prev=None, **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("balance_code_span_min", "缺少可用的 ca 文件")
    rows, z0, z1 = b.ca.rows, b.ca.zero_start, b.ca.zero_end
    if len(rows) < 3:
        return _unavailable("balance_code_span_min", "数据行不足")
    per_unit: Dict[str, float] = {}
    for i, u in enumerate(BALANCE_UNITS, start=1):
        if len(z0) <= i or len(z1) <= i:
            continue
        base = (z0[i] + z1[i]) / 2.0
        per_unit[u] = max((abs(r[i] - base) for r in rows[1:-1] if len(r) > i), default=0.0)
    if not per_unit:
        return _unavailable("balance_code_span_min", "列数不足")
    weakest = min(per_unit, key=per_unit.get)
    return _ok("balance_code_span_min", per_unit[weakest],
               detail=f"跑码幅值最小的是 {weakest} 单元",
               per_unit={k: round(v, 6) for k, v in per_unit.items()}, worst_unit=weakest)


def f_balance_return_zero(b: RunBundle, prev=None, **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("balance_return_zero", "缺少可用的 ca 文件")
    z0, z1 = b.ca.zero_start, b.ca.zero_end
    per_unit = {u: abs(z0[i] - z1[i]) for i, u in enumerate(BALANCE_UNITS, start=1)
                if len(z0) > i and len(z1) > i}
    if not per_unit:
        return _unavailable("balance_return_zero", "零点行列数不足")
    worst = max(per_unit, key=per_unit.get)
    return _ok("balance_return_zero", per_unit[worst],
               detail=f"最大不回零出现在 {worst} 单元",
               per_unit={k: round(v, 6) for k, v in per_unit.items()}, worst_unit=worst)


def f_base_pressure_lr_diff(b: RunBundle, prev=None, **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("base_pressure_lr_diff", "缺少可用的 ca 文件")
    blow = b.ca.blow_rows
    if not blow:
        return _unavailable("base_pressure_lr_diff", "没有吹风点")
    worst, at = 0.0, 0.0
    for r in blow:
        if len(r) <= 9:
            continue
        t = abs(mpa_to_mmh2o(r[7]) - mpa_to_mmh2o(r[9]))
        if t > worst:
            worst, at = t, r[0]
    return _ok("base_pressure_lr_diff", worst, detail=f"最大差值出现在攻角 {at:.2f}°", alpha=at)


def f_pressure_zero_spread(b: RunBundle, prev=None, **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("pressure_zero_spread", "缺少可用的 ca 文件")
    z = b.ca.zero_start
    if len(z) <= max(PRESSURE_ZERO_COLS):
        return _unavailable("pressure_zero_spread", "零点行列数不足 15 列")
    names = ["左底压PL", "右底压PR", "大气压Pa", "来流静压P8", "来流总压P0"]
    vals = [mpa_to_mmh2o(z[i]) for i in PRESSURE_ZERO_COLS]
    mean = sum(vals) / len(vals)
    devs = {n: abs(v - mean) for n, v in zip(names, vals)}
    worst = max(devs, key=devs.get)
    return _ok("pressure_zero_spread", devs[worst],
               detail=f"偏差最大的是 {worst}（零点平均值 {mean:.1f} mmH2O）",
               per_sensor={k: round(v, 2) for k, v in devs.items()}, mean=round(mean, 2))


def f_mach_deviation(b: RunBundle, prev=None, **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("mach_deviation", "缺少可用的 ca 文件")
    nominal = b.ca.nominal_mach
    if nominal is None:
        return _unavailable("mach_deviation", "ca 文件中没有名义马赫数 (M=)")
    worst, at, m_at = 0.0, 0.0, 0.0
    for r in b.ca.blow_rows:
        if len(r) <= 14 or r[13] <= 0:
            continue
        m = mach_from_pressure_ratio(r[14], r[13])
        t = abs(m - nominal)
        if t > worst:
            worst, at, m_at = t, r[0], m
    return _ok("mach_deviation", worst,
               detail=f"名义 Ma={nominal:.3f}，实测最大偏离点 Ma={m_at:.4f}（攻角 {at:.2f}°）",
               nominal=nominal, measured=round(m_at, 4), alpha=at)


def f_base_vs_atm_min_gap(b: RunBundle, prev=None, **kw) -> FeatureValue:
    cols = _pa_ca_echo_cols(b.pa)
    if cols is None:
        return _unavailable("base_vs_atm_min_gap", "缺少 pa 文件或其中的 CA 回显表")
    dl = max(abs(l - a) for l, a in zip(cols["PL"], cols["Pa"]))
    dr = max(abs(r - a) for r, a in zip(cols["PR"], cols["Pa"]))
    return _ok("base_vs_atm_min_gap", min(dl, dr),
               detail=f"左底压-大气压最大差 {dl:.1f}，右底压-大气压最大差 {dr:.1f} mmH2O",
               left=round(dl, 2), right=round(dr, 2))


def f_base_vs_static_min_gap(b: RunBundle, prev=None, *, tail_contracted: bool = False, **kw) -> FeatureValue:
    if tail_contracted:
        return _unavailable("base_vs_static_min_gap",
                            "模型尾部为收缩外形，按规程不与来流静压比较")
    cols = _pa_ca_echo_cols(b.pa)
    if cols is None:
        return _unavailable("base_vs_static_min_gap", "缺少 pa 文件或其中的 CA 回显表")
    dl = max(abs(l - s) for l, s in zip(cols["PL"], cols["P8"]))
    dr = max(abs(r - s) for r, s in zip(cols["PR"], cols["P8"]))
    return _ok("base_vs_static_min_gap", min(dl, dr),
               detail=f"左底压-静压最大差 {dl:.1f}，右底压-静压最大差 {dr:.1f} mmH2O",
               left=round(dl, 2), right=round(dr, 2))


def f_base_pressure_gradient(b: RunBundle, prev=None, **kw) -> FeatureValue:
    cols = _pa_ca_echo_cols(b.pa)
    if cols is None:
        return _unavailable("base_pressure_gradient", "缺少 pa 文件或其中的 CA 回显表")
    alpha = cols["alpha"]
    if len(alpha) < 3:
        return _unavailable("base_pressure_gradient", "吹风点不足 3 个")
    best = {"L": 0.0, "R": 0.0}
    at = 0.0
    for side, key in (("L", "PL"), ("R", "PR")):
        series = cols[key]
        for j in range(len(series) - 2):
            da = abs(alpha[j + 2] - alpha[j])
            if da <= 1e-9:
                continue
            t = abs(series[j + 2] - series[j]) / da
            if t > best[side]:
                best[side] = t
                at = alpha[j]
    worst = max(best["L"], best["R"])
    return _ok("base_pressure_gradient", worst,
               detail=f"左侧最大 {best['L']:.2f}、右侧最大 {best['R']:.2f} mmH2O/deg（起始攻角 {at:.2f}°）",
               left=round(best["L"], 2), right=round(best["R"], 2))


def _elastic(b: RunBundle, key: str, col: int, label: str) -> FeatureValue:
    if b.pa is None or not b.pa.elastic.rows:
        return _unavailable(key, "缺少 pa 文件或其中的弹性角修正表")
    vals = [abs(r[col]) for r in b.pa.elastic.rows if len(r) > col]
    if not vals:
        return _unavailable(key, "弹性角修正表列数不足")
    peak = max(vals)
    alphas = [r[0] for r in b.pa.elastic.rows if len(r) > col]
    at = alphas[vals.index(peak)] if alphas else 0.0
    return _ok(key, peak, detail=f"{label}最大弹性角出现在攻角 {at:.2f}°", alpha=at)


def f_elastic_alpha(b, prev=None, **kw):
    return _elastic(b, "elastic_alpha", 1, "攻角方向")


def f_elastic_beta(b, prev=None, **kw):
    return _elastic(b, "elastic_beta", 2, "侧滑方向")


def f_elastic_gamma(b, prev=None, **kw):
    return _elastic(b, "elastic_gamma", 3, "滚转方向")


def f_alpha_extrapolation(b: RunBundle, prev=None, **kw) -> FeatureValue:
    """Extrapolation is SIGNED: an output angle outside the measured range.

    The legacy script printed ``max(|meas_min - out_min|, |out_max - meas_max|)``
    which reports a large number for pure *interpolation* (targets comfortably
    inside the measured range). Only the positive parts count.
    """
    if b.pa is None or not b.pa.attitude_measured.rows:
        return _unavailable("alpha_extrapolation", "缺少 pa 文件或其中的实测姿态角表")
    meas = [r[3] for r in b.pa.attitude_measured.rows if len(r) > 3]
    # Output grid: prefer the delivered da result grid; fall back to pa's
    # post-interpolation attitude table.
    out_grid: List[float] = []
    source = ""
    if b.da is not None and b.da.ok:
        out_grid = b.da.series("ALPHA")
        source = "da 结果文件"
    if not out_grid and b.pa.attitude_interp.rows:
        out_grid = [r[3] for r in b.pa.attitude_interp.rows if len(r) > 3]
        source = "pa 插值后姿态角表"
    if not meas or not out_grid:
        return _unavailable("alpha_extrapolation", "实测或输出攻角序列为空")
    low = min(meas) - min(out_grid)
    high = max(out_grid) - max(meas)
    extrap = max(0.0, low, high)
    side = "下端" if low >= high else "上端"
    return _ok("alpha_extrapolation", extrap,
               detail=(f"实测攻角 [{min(meas):.3f}, {max(meas):.3f}]°，输出攻角 "
                       f"[{min(out_grid):.3f}, {max(out_grid):.3f}]°"
                       + (f"，{side}外插" if extrap > 0 else "，全部为内插")
                       + f"（输出网格来自 {source}）"),
               measured_range=[round(min(meas), 3), round(max(meas), 3)],
               output_range=[round(min(out_grid), 3), round(max(out_grid), 3)],
               source=source)


def f_balance_load_ratio(b: RunBundle, prev=None, *, library: Optional[BalanceLibrary] = None,
                         ranges: Optional[Dict[str, float]] = None, **kw) -> FeatureValue:
    if b.pa is None or not b.pa.aero_loads.rows:
        return _unavailable("balance_load_ratio", "缺少 pa 文件或其中的气动载荷表")
    rated = dict(ranges) if ranges else {}
    if not rated:
        name = b.pa.balance_formula or b.pa.balance_type
        entry = library.lookup(name) if library else None
        if entry is None:
            return _unavailable(
                "balance_load_ratio",
                f"天平「{name or '未知'}」不在载荷库中，无法换算量程占比。"
                f"请在「天平载荷库」中补录该天平的六分量额定量程后重跑。",
            )
        rated = entry.ranges
    peaks: Dict[str, float] = {}
    for i, u in enumerate(BALANCE_UNITS, start=1):
        vals = [abs(r[i]) for r in b.pa.aero_loads.rows if len(r) > i]
        if vals:
            peaks[u] = max(vals)
    ratios = {u: 100.0 * peaks[u] / rated[u] for u in peaks
              if rated.get(u) and rated[u] > 0}
    if not ratios:
        return _unavailable("balance_load_ratio", "载荷库条目中没有有效的量程值")
    worst = max(ratios, key=ratios.get)
    return _ok("balance_load_ratio", ratios[worst],
               detail=f"占比最高的是 {worst} 单元（峰值 {peaks[worst]:.4f} / 量程 {rated[worst]:g}）",
               per_unit={k: round(v, 3) for k, v in ratios.items()},
               peaks={k: round(v, 5) for k, v in peaks.items()},
               rated={k: v for k, v in rated.items()}, worst_unit=worst)


def f_total_temp_zero_diff(b: RunBundle, prev=None, **kw) -> FeatureValue:
    if b.ca is None or not b.ca.ok:
        return _unavailable("total_temp_zero_diff", "缺少可用的 ca 文件")
    z = b.ca.zero_start
    if len(z) <= 11:
        return _unavailable("total_temp_zero_diff", "零点行列数不足 12 列")
    return _ok("total_temp_zero_diff", abs(z[10] - z[11]),
               detail=f"总温 {z[10]:.2f} ℃，室温 {z[11]:.2f} ℃")


EXTRACTORS: Dict[str, Callable[..., FeatureValue]] = {
    "balance_zero_drift": f_balance_zero_drift,
    "balance_zero_near_17": f_balance_zero_near_17,
    "balance_code_jump": f_balance_code_jump,
    "balance_code_span_min": f_balance_code_span_min,
    "balance_return_zero": f_balance_return_zero,
    "base_pressure_lr_diff": f_base_pressure_lr_diff,
    "pressure_zero_spread": f_pressure_zero_spread,
    "mach_deviation": f_mach_deviation,
    "base_vs_atm_min_gap": f_base_vs_atm_min_gap,
    "base_vs_static_min_gap": f_base_vs_static_min_gap,
    "base_pressure_gradient": f_base_pressure_gradient,
    "elastic_alpha": f_elastic_alpha,
    "elastic_beta": f_elastic_beta,
    "elastic_gamma": f_elastic_gamma,
    "alpha_extrapolation": f_alpha_extrapolation,
    "balance_load_ratio": f_balance_load_ratio,
    "total_temp_zero_diff": f_total_temp_zero_diff,
}


def extract_custom(bundle: RunBundle, key: str, code: str, name: str = "") -> FeatureValue:
    """Run a user- or AI-authored extractor in the sandbox.

    The extractor sees the canonical tidy frame (see :mod:`app.windtunnel.frames`)
    and must return ``{"value": float, "unit": str, ...}``. Everything the
    platform already guarantees for user algorithms applies unchanged: AST
    whitelist, no filesystem or network, wall-clock timeout, memory cap.

    A custom feature is registered in :data:`FEATURE_SPECS` on first use so the
    rest of the system (rule validation, report appendix, feature catalogue)
    treats it exactly like a built-in one.
    """
    from ..sandbox import executor as sandbox_executor  # local: keeps import light
    from .frames import bundle_to_frame

    label = name or key
    if key not in FEATURE_SPECS:
        FEATURE_SPECS[key] = FeatureSpec(
            key=key, name=label, unit="", requires=[],
            description="用户/AI 自定义特征算子", method="sandboxed custom extractor",
        )

    df = bundle_to_frame(bundle)
    if df.empty:
        return _unavailable(key, "本车次没有可解析的数据，自定义算子无法执行")

    res = sandbox_executor.execute(code, {}, input_df=df, save_result=False)
    if res.status != "ok":
        return _unavailable(key, f"自定义算子执行失败：{res.error[:300]}")

    summary = res.summary or {}
    if summary.get("type") != "dict":
        return _unavailable(
            key, f"自定义算子应返回 dict(含 value/unit)，实际返回 {summary.get('type')}")
    payload = summary.get("value") or {}
    if "value" not in payload:
        return _unavailable(key, "自定义算子返回的 dict 里没有 value 字段")
    try:
        value = float(payload["value"])
    except (TypeError, ValueError):
        return _unavailable(key, f"自定义算子返回的 value 不是数值：{payload.get('value')!r}")

    unit = str(payload.get("unit", ""))
    spec = FEATURE_SPECS[key]
    spec.unit = unit or spec.unit
    spec.name = label or spec.name
    return FeatureValue(
        key=key, name=spec.name, unit=unit, value=value,
        detail=str(payload.get("detail", "")),
        extras=payload.get("extras") if isinstance(payload.get("extras"), dict) else {},
        method="沙箱内执行的自定义特征算子",
    )


def extract_features(
    bundle: RunBundle,
    prev: Optional[RunBundle] = None,
    *,
    keys: Optional[List[str]] = None,
    library: Optional[BalanceLibrary] = None,
    tail_contracted: bool = False,
    balance_ranges: Optional[Dict[str, float]] = None,
    custom_extractors: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, FeatureValue]:
    """Compute every requested feature. Missing inputs yield an *unavailable*
    value, never a silent zero — a zero that means "not measured" is exactly
    how a fault gets reported as normal.

    ``custom_extractors`` maps a ``custom:<slug>`` key to
    ``{"code": <source>, "name": <display name>}``.
    """
    wanted = keys or list(EXTRACTORS.keys())
    customs = custom_extractors or {}
    out: Dict[str, FeatureValue] = {}
    for k in wanted:
        if k.startswith("custom:"):
            spec = customs.get(k)
            if not spec or not spec.get("code"):
                out[k] = _unavailable(k, f"自定义特征「{k}」未在算法库中找到，或代码为空") \
                    if k in FEATURE_SPECS else FeatureValue(
                        key=k, name=k, unit="", value=None, status="unavailable",
                        detail=f"自定义特征「{k}」未在算法库中找到，或代码为空")
                continue
            try:
                out[k] = extract_custom(bundle, k, spec["code"], spec.get("name", ""))
            except Exception as e:  # noqa: BLE001
                out[k] = FeatureValue(key=k, name=spec.get("name", k), unit="", value=None,
                                      status="unavailable",
                                      detail=f"自定义算子调用失败：{type(e).__name__}: {e}")
            continue
        fn = EXTRACTORS.get(k)
        if fn is None:
            continue
        try:
            out[k] = fn(bundle, prev, library=library, tail_contracted=tail_contracted,
                        ranges=balance_ranges)
        except Exception as e:  # noqa: BLE001 — one bad feature must not kill the run
            out[k] = _unavailable(k, f"计算失败：{type(e).__name__}: {e}")
    return out
