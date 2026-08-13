"""Offline regression suite for the wind-tunnel module — no server, no LLM.

The valuable assertions here are the ones that pin our numbers to the
**customer's own production output**. Their existing tool shipped
``跟班记录`` files for runs 91836–91840; those files state, in plain text:

    91837:  天平零漂为 0.0989 大于 0.012
            天平最大不回零量为 0.1002 大于 0.01
            MZ 单元载荷最大跑码量占天平量程的 28.902%
    汇总:   91836 优秀 / 91837 不合格(2) / 91838 不合格(1) / 91839 优秀 / 91840 优秀

If a refactor ever moves one of those numbers, this suite fails. That is the
point: a rewrite of a quality-control tool is only trustworthy if it first
reproduces the tool it replaces, digit for digit.

The suite also locks the three defects that were fixed relative to the legacy
scripts (unit consistency, signed extrapolation, honest "unavailable"), so a
future change cannot silently reintroduce them.

Run::

    ./.venv/Scripts/python.exe wt_smoke_test.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.windtunnel.balance import BalanceLibrary, default_library  # noqa: E402
from app.windtunnel.features import FEATURE_SPECS, extract_features  # noqa: E402
from app.windtunnel.frames import bundle_to_frame, wide_table  # noqa: E402
from app.windtunnel.parsers import (  # noqa: E402
    detect_kind, detect_run_no, load_bundle, parse_ca, parse_da, parse_pa,
)
from app.windtunnel.pipeline import (  # noqa: E402
    CheckConfig, check_batch, curve_data, curve_statistics, load_batch,
)
from app.windtunnel.report import (  # noqa: E402
    build_batch_summary, build_report, build_shift_record, report_filename,
)
from app.windtunnel.rules import Band, Rule, evaluate  # noqa: E402
from app.windtunnel.seed_rules import seed_rules  # noqa: E402
from app.windtunnel.units import MMH2O_PER_MPA, mach_from_pressure_ratio  # noqa: E402
from app.windtunnel import compare as CMP  # noqa: E402
from app.windtunnel.repeatability import analyse_repeatability  # noqa: E402
from app.windtunnel.trend import hampel, mann_kendall, nelson_runs  # noqa: E402

TESTDATA = Path(os.environ.get("WT_TESTDATA",
                               r"d:/Git/Personal/WTDataAgent/FromC/testdata"))

FROMC = Path(os.environ.get(
    "WT_FROMC",
    r"d:/Git/Personal/WTDataAgent/FromC/20260129风洞试验过程质量检查智能体",
))
INPUT_DIR = FROMC / "输入"
CA_DIR = FROMC / "Agent1风洞试验数据监测智能体-2-发锋哥版本" / \
    "场景一风洞试验数据监测智能体-2-发锋哥版本" / "data" / "ca模板(公开)"
PA_DIR = FROMC / "Agent1风洞试验数据监测智能体-2-发锋哥版本" / \
    "场景一风洞试验数据监测智能体-2-发锋哥版本" / "data" / "TEMP模板(公开)"
DA_DIR = FROMC / "Agent2质量检测代码生成" / "Agent2质量检测代码生成-9-发锋哥" / \
    "Data" / "list模板(公开)"

PASSED: List[str] = []
FAILED: List[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name if cond else f"{name} — {detail}")
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def close(a: float, b: float, tol: float) -> bool:
    return a is not None and abs(a - b) <= tol


def section(t: str) -> None:
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


# ══════════════════════════════════════════════════════════════════════════
def t_units() -> None:
    section("1. 单位与物理关系")
    check("1 MPa = 101971.62 mmH2O", close(MMH2O_PER_MPA, 101971.62, 0.01),
          f"{MMH2O_PER_MPA:.2f}")
    # Isentropic check: p0/p for M=1.741 with gamma=1.4 is (1+0.2*1.741^2)^3.5.
    ratio = (1 + 0.2 * 1.741 ** 2) ** 3.5
    m = mach_from_pressure_ratio(ratio, 1.0)
    check("等熵马赫数反算自洽（NACA TR-1135 eq.44）", close(m, 1.741, 1e-6), f"{m:.9f}")
    check("非物理压力比返回 0 而不是抛异常",
          mach_from_pressure_ratio(1.0, 2.0) == 0.0)


def t_parsers() -> None:
    section("2. 解析器")
    check("按前缀识别文件类型",
          detect_kind("ca246490") == "ca" and detect_kind("pa91837模板(公开)") == "pa"
          and detect_kind("da91836模板(公开)") == "da" and detect_kind("readme.txt") is None)
    check("提取车次号", detect_run_no("ca246490") == "246490")

    ca = parse_ca(INPUT_DIR / "ca246490")
    check("ca 解析：19 行 × 16 列", len(ca.rows) == 19 and len(ca.rows[0]) == 16)
    check("ca 尾部元信息", ca.nominal_mach == 1.741 and ca.n_points == 17
          and len(ca.alpha_targets) == 17, f"M={ca.nominal_mach} N6={ca.n_points}")
    check("初零/末零/吹风点切分", len(ca.blow_rows) == 17
          and ca.zero_start is ca.rows[0] and ca.zero_end is ca.rows[-1])

    pa = parse_pa(INPUT_DIR / "pa246490")
    check("pa 识别为测力试验", pa.is_force_test)
    check("pa 天平信息", pa.balance_type == "TP202126" and pa.balance_formula == "N636CB01",
          f"{pa.balance_type}/{pa.balance_formula}")
    check("pa 五张关键表全部解析出",
          len(pa.ca_echo.rows) == 19 and len(pa.elastic.rows) == 17
          and len(pa.attitude_measured.rows) == 17 and len(pa.attitude_interp.rows) == 17
          and len(pa.aero_loads.rows) == 17)
    check("pa 标定矩阵主对角线", close(pa.balance_sensitivity.get("Y", 0), 349.32999, 1e-4))
    # The legacy script anchored on an exact-spacing header string that does NOT
    # match this file. Robust token matching is what makes 攻角外插 computable.
    check("姿态角表用词元匹配而非精确空格（甲方脚本在此失配）",
          pa.attitude_measured.header[:5] == ["Am", "Bm", "Rm", "At", "Bs"])

    da = parse_da(INPUT_DIR / "da246490")
    check("da 解析：10 行 × 59 列", len(da.rows) == 10 and len(da.columns) == 59)
    check("da 来流条件块", close(da.flow.get("Po", 0), 187218.12, 0.01))
    check("da 只把有变化的列列为可绘制", "ALPHA" in da.numeric_columns()
          and "D5" not in da.numeric_columns())

    for n in ("91836", "91837", "91838", "91839", "91840"):
        c = parse_ca(CA_DIR / f"ca{n}模板(公开)")
        p = parse_pa(PA_DIR / f"pa{n}模板(公开)")
        if not (c.ok and p.ok):
            check(f"模板车次 {n} 可解析", False, f"ca.ok={c.ok} pa.ok={p.ok}")
            return
    check("5 个模板车次全部可解析", True)


def t_customer_ground_truth() -> None:
    section("3. 复现甲方生产结果（最关键的一组断言）")
    files = ([p for p in CA_DIR.iterdir() if p.is_file()]
             + [p for p in PA_DIR.iterdir() if p.is_file()]
             + [p for p in DA_DIR.iterdir() if p.is_file()])
    batch = check_batch(load_batch(files))
    by = {r.run_no: r for r in batch.runs}
    check("批次含 5 个车次", len(by) == 5, "、".join(sorted(by)))

    zd = by["91837"].features["balance_zero_drift"].value
    check("91837 天平零飘 = 0.0989（甲方跟班记录同值）", close(zd, 0.0989, 5e-5), f"{zd:.6f}")
    rz = by["91837"].features["balance_return_zero"].value
    check("91837 最大不回零 = 0.1002（甲方跟班记录同值）", close(rz, 0.1002, 5e-5), f"{rz:.6f}")
    mz = by["91837"].features["balance_load_ratio"].extras["per_unit"]["Mz"]
    check("91837 MZ 载荷占量程 = 28.902%（甲方跟班记录同值）",
          close(mz, 28.902, 5e-3), f"{mz:.3f}%")
    q = by["91837"].features["balance_load_ratio"].extras["per_unit"]["Q"]
    check("91837 Q 载荷占量程 = 25.128%（甲方跟班记录同值）",
          close(q, 25.128, 5e-3), f"{q:.3f}%")
    y = by["91837"].features["balance_load_ratio"].extras["per_unit"]["Y"]
    check("91837 Y 载荷占量程 = 10.112%（甲方跟班记录同值）",
          close(y, 10.112, 5e-3), f"{y:.3f}%")

    grades = {k: v.grade for k, v in sorted(by.items())}
    check("五车次合格判定与甲方汇总报告一致",
          grades["91836"].startswith("合格") and grades["91837"] == "不合格"
          and grades["91838"] == "不合格" and grades["91839"].startswith("合格")
          and grades["91840"].startswith("合格"),
          str(grades))
    check("91837 恰好 2 个严重问题（甲方汇总：2）",
          by["91837"].counts()["critical"] == 2, str(by["91837"].counts()))
    check("91838 恰好 1 个严重问题（甲方汇总：1）",
          by["91838"].counts()["critical"] == 1, str(by["91838"].counts()))


def t_fixed_defects() -> None:
    section("4. 相对甲方脚本修复的三个缺陷（锁死，防回归）")
    bundles = load_batch(sorted(INPUT_DIR.iterdir()))
    res = check_batch(bundles)
    r = res.runs[0]

    # (1) unit consistency: legacy compared a raw MPa number against an mmH2O
    #     threshold, so the printed value was ~1e5 times too small.
    lr = r.features["base_pressure_lr_diff"]
    check("左右底压差已换算到 mmH2O（甲方脚本停留在 MPa）",
          lr.available and 1.0 < lr.value < 1e4, f"{lr.value:.4f} {lr.unit}")

    # (2) signed extrapolation: legacy used abs() and reported pure
    #     interpolation as a 5.35° extrapolation.
    ex = r.features["alpha_extrapolation"]
    check("纯内插时外插量为 0（甲方脚本会报 5.352）",
          ex.available and ex.value == 0.0, f"{ex.value}")

    # (3) honest unavailable: legacy crashed with IndexError, swallowed as
    #     "PA 分析失败", indistinguishable from a parsing bug. N636CB01 is now
    #     in the shipped library, so provoke the condition with an empty one.
    empty_lib = BalanceLibrary()
    lo = extract_features(bundles[0], None, keys=["balance_load_ratio"],
                          library=empty_lib)["balance_load_ratio"]
    check("天平不在载荷库时报未评定并给出补齐方式（甲方脚本崩溃）",
          lo.status == "unavailable" and "载荷库" in lo.detail, lo.detail[:50])
    lo_ok = r.features["balance_load_ratio"]
    check("载荷库中有该天平时正常评定", lo_ok.status == "ok",
          f"{lo_ok.value:.4f}% (N636CB01)")

    zd = r.features["balance_zero_drift"]
    check("无上一车次时零飘报未评定，绝不默认为正常",
          zd.status == "unavailable" and "上一车次" in zd.detail)


def t_rule_engine() -> None:
    section("5. 规则引擎")
    rules = seed_rules()
    check("内置规则数量", len(rules) == 18, f"{len(rules)} 条")
    bad = [r.rule_id for r in rules if r.validate()]
    check("全部内置规则通过自校验", not bad, str(bad))
    check("全部内置规则都带判据出处", all(r.refs for r in rules))
    check("每条规则的每个非 ok 区间都写了处理建议",
          all(b.action for r in rules for b in r.bands if b.level != "ok"))

    r = Rule(rule_id="t", name="t", feature="balance_return_zero", bands=[
        Band(level="critical", lo=0.01), Band(level="warning", lo=0.006, hi=0.01),
        Band(level="notice", lo=0.003, hi=0.006), Band(level="ok", hi=0.003)])
    from app.windtunnel.features import FeatureValue
    for v, want in ((0.02, "critical"), (0.008, "warning"), (0.004, "notice"),
                    (0.001, "ok"), (0.01, "critical"), (0.003, "notice")):
        f = evaluate([r], {"balance_return_zero": FeatureValue(
            key="balance_return_zero", name="x", unit="码", value=v)})[0]
        check(f"区间匹配 {v} → {want}", f.level == want, f.level)

    # A rule bound to a nonexistent feature must be rejected, not guessed at.
    bad_rule = Rule(rule_id="x", name="x", feature="nope", bands=[Band(level="ok")])
    check("绑定不存在的特征被校验拒绝", bool(bad_rule.validate()))

    # Mach gating (rule 06 splits at Ma 2.9).
    g = Rule(rule_id="g", name="g", feature="mach_deviation",
             applies_when_mach="<2.9", bands=[Band(level="ok")])
    check("马赫数门控生效", g.gate_passes(1.741) and not g.gate_passes(3.5))

    # Unavailable features must still produce a finding.
    f = evaluate([r], {})[0]
    check("特征缺失时仍产出「未评定」条目而不是被丢弃",
          f.status == "unavailable" and not f.is_problem)


def t_balance_library() -> None:
    section("6. 天平载荷库")
    lib = default_library()
    check("公开模板 N628E 已内置", lib.lookup("N628E") is not None)
    check("大小写不敏感", lib.lookup("n628e") is not None)
    check("宽松匹配（天平名在长串中）", lib.lookup("N628E-支杆") is not None)
    check("查不到就返回 None，不猜", lib.lookup("TP999999") is None)
    lib2 = BalanceLibrary.from_text(lib.to_text())
    check("序列化往返一致", lib2.lookup("N628E").ranges == lib.lookup("N628E").ranges)
    try:
        BalanceLibrary().add("bad", {"My": 1.0})
        check("缺分量时拒绝入库", False)
    except ValueError:
        check("缺分量时拒绝入库", True)


def t_frames_and_curves() -> None:
    section("7. 长表与气动曲线")
    b = load_batch(sorted(INPUT_DIR.iterdir()))[0]
    df = bundle_to_frame(b)
    check("长表非空且列齐全",
          not df.empty and set(df.columns) >= {"table", "row", "point", "alpha",
                                               "variable", "value", "unit"},
          f"{df.shape}")
    check("长表标出初零/吹风/末零",
          set(df[df.table == "ca"]["point"].unique()) ==
          {"zero_start", "blow", "zero_end"})
    pl = df[(df.table == "ca") & (df.variable == "PL")]["value"]
    check("长表中的压力已是 mmH2O（不会再有量纲坑）", pl.max() > 1000, f"max={pl.max():.1f}")
    check("宽表可还原", not wide_table(b, "ca").empty)

    cd = curve_data(b)
    check("默认绘制 CAF~MZ 七条曲线", cd["ok"] and len(cd["series"]) == 7)
    st = {s["key"]: s for s in curve_statistics(cd)}
    check("CN 在本攻角段高度线性", st["CN"]["r2"] > 0.999, f"R²={st['CN']['r2']}")
    # Independent cross-check: the da file carries the tunnel's own CNa.
    cna = b.da.series("CNa")[0]
    rel = abs(st["CN"]["slope_per_deg"] - cna) / abs(cna)
    check("CN 拟合斜率与 da 自带 CNα 相符(<5%)", rel < 0.05,
          f"拟合 {st['CN']['slope_per_deg']:.5f} vs 文件 {cna:.5f}（差 {rel*100:.2f}%）")
    check("坏横轴列被拒绝", curve_data(b, x="NOPE")["ok"] is False)


def t_report() -> None:
    section("8. 报告")
    bundles = load_batch(sorted(INPUT_DIR.iterdir()))
    res = check_batch(bundles)
    r = res.runs[0]
    cd = curve_data(bundles[0])
    md = build_report(r, curve=cd, curve_stats=curve_statistics(cd), batch=res)
    for name in ("车次基本信息", "总体质量评估", "异常项明细", "未评定项说明",
                 "气动曲线与规律结论", "跟班记录正文", "判据与依据"):
        check(f"报告含章节「{name}」", name in md)
    check("报告写出计算方法（可审计）", "计算方法" in md)

    from app.windtunnel.report import ReportOptions
    slim = build_report(r, options=ReportOptions(sections=["overview", "verdict"]))
    check("章节可裁剪", "异常项明细" not in slim and "车次基本信息" in slim)

    sr = build_shift_record(r)
    check("跟班记录沿用现行编号叙述格式",
          sr.startswith("2") and "【车次 246490】" in sr and "\n1. " in sr)
    check("异常项带 - P 标记（下游工具依赖）", " - P" in sr)
    check("命名符合车次号_跟班记录",
          report_filename("246490") == "246490_跟班记录.txt")

    files = ([p for p in CA_DIR.iterdir() if p.is_file()]
             + [p for p in PA_DIR.iterdir() if p.is_file()])
    bres = check_batch(load_batch(files))
    summ = build_batch_summary(bres)
    check("汇总报告列出各车次评级", "各车次评级" in summ and "91837" in summ)
    check("汇总报告点名不合格车次", "91837" in summ.split("存在严重问题的车次")[1][:60])


def t_trend() -> None:
    section("9. 跨车次趋势")
    files = ([p for p in CA_DIR.iterdir() if p.is_file()]
             + [p for p in PA_DIR.iterdir() if p.is_file()])
    res = check_batch(load_batch(files), config=CheckConfig(trend_window=3))
    check("产出多条特征序列", len(res.trends) >= 10, f"{len(res.trends)} 条")
    analysed = [t for t in res.trends if t.get("analysed") is not False]
    short = [t for t in res.trends if t.get("analysed") is False]
    check("5 个零点类特征全部完成趋势判定",
          len(analysed) >= 5 and all(not t["state_dependent"] for t in analysed),
          f"{len(analysed)} 条已判定")
    check("样本不足的分组如实说明而非静默丢弃",
          all(t["headline"] for t in short),
          f"{len(short)} 条注明原因，例：" + (short[0]["headline"][:44] if short else "—"))
    zd = next((t for t in res.trends if t["feature"] == "balance_zero_drift"), None)
    check("零飘序列只含有值的车次（首车次不参与）",
          zd is not None and "91836" not in zd["runs"], str(zd["runs"]) if zd else "")
    check("趋势告警带判据引用",
          all(t["reference"] for t in res.trends if t["flagged"]) or
          not any(t["flagged"] for t in res.trends))


def t_custom_extractor() -> None:
    section("10. 自定义特征算子（沙箱路径，不依赖大模型）")
    code = '''
import pandas as pd
import numpy as np

META = {"name": "总压波动系数", "slug": "tp_cv", "category": "custom",
        "description": "吹风段来流总压变异系数", "params_schema": {}, "returns": "dict"}

def run(df, **params):
    s = df[(df.table == "ca") & (df.point == "blow") & (df.variable == "P0")]["value"]
    if len(s) < 2:
        raise ValueError("吹风点不足")
    return {"value": float(s.std(ddof=1) / s.mean() * 100.0), "unit": "%",
            "detail": f"基于 {len(s)} 个吹风点", "extras": {"mean": float(s.mean())}}

test_cases = [{"df": pd.DataFrame({"run_no": ["t"]*3, "table": ["ca"]*3,
    "row": [1,2,3], "point": ["blow"]*3, "alpha": [0.0,1.0,2.0],
    "variable": ["P0"]*3, "value": [1.0,2.0,3.0], "unit": ["mmH2O"]*3}), "params": {}}]
'''
    b = load_batch(sorted(INPUT_DIR.iterdir()))[0]
    from app.windtunnel.features import extract_custom
    fv = extract_custom(b, "custom:tp_cv", code, "总压波动系数")
    check("自定义算子在沙箱中跑出数值", fv.status == "ok" and fv.value > 0,
          f"{fv.value:.4f}{fv.unit} — {fv.detail}")

    rule = Rule(rule_id="r_cv", name="来流总压稳定性", feature="custom:tp_cv", bands=[
        Band(level="warning", lo=1.0, verdict="波动过大", action="检查总压控制"),
        Band(level="ok", hi=1.0, verdict="来流总压稳定")])
    check("规则可绑定自定义特征", not rule.validate(), str(rule.validate()))
    res = check_batch([b], config=CheckConfig(rule_ids=["r_cv"]), rules=[rule],
                      custom_extractors={"custom:tp_cv": {"code": code, "name": "总压波动系数"}})
    f = res.runs[0].findings[0]
    check("自定义特征参与完整检查流程", f.status == "evaluated",
          f"{f.value:.4f}{f.unit} → {f.verdict}")

    # A malicious / broken extractor must fail closed.
    bad = "import os\nMETA={}\ndef run(df, **p):\n    return {'value':1,'unit':'x'}\n"
    fv2 = extract_custom(b, "custom:bad", bad, "bad")
    check("越权代码被沙箱拒绝（fail-closed）", fv2.status == "unavailable",
          fv2.detail[:60])


def _matrix_bundles():
    files = [p for sub in ("ca", "da", "temp") for p in (TESTDATA / sub).iterdir()
             if p.is_file()]
    return load_batch(files)


def t_printed_da() -> None:
    section("11. da 打印式格式（生产环境真实格式）")
    d = parse_da(TESTDATA / "da" / "da246490")
    check("识别为打印式布局", d.layout == "printed", d.layout)
    check("三个分块拼接成 19 列 x 10 行",
          len(d.columns) == 19 and len(d.rows) == 10,
          f"{len(d.columns)}x{len(d.rows)}")
    check("解析出模型状态 PHI/BETA/dz/dy/dx",
          {"PHI", "BETA", "dz", "dy", "dx"} <= set(d.state), str(d.state))
    check("解析出风洞自带导数 CNa", close(d.derivatives.get("CNa", 0), 0.09655, 1e-6))
    check("解析出来流条件", close(d.flow.get("Po", 0), 187218.1, 0.1))
    lst = parse_da(INPUT_DIR / "da246490")
    same = all(abs(a - b) < 1e-12
               for c in ("CN", "CAF", "CZ", "CAB", "CA", "CD", "CLF", "CDF", "XCP")
               if c in d.columns and c in lst.columns
               for a, b in zip(d.series(c), lst.series(c)))
    check("与机读 59 列格式逐位一致", same, "两种布局同一车次系数完全相同")
    bad = [q.name for q in sorted((TESTDATA / "da").iterdir()) if not parse_da(q).ok]
    check("130 个真实 da 文件全部解析成功", not bad, str(bad[:5]))


def t_recovered_balance() -> None:
    section("12. N636CB01 天平量程（由甲方报告占比反推）")
    lib = default_library()
    e = lib.lookup("N636CB01")
    check("已内置", e is not None)
    if e:
        check("量程为整数设计值",
              e.ranges == {"My": 10.0, "Z": 150.0, "Mz": 20.0,
                           "Y": 350.0, "Mx": 4.0, "Q": 50.0}, str(e.ranges))
        check("注明出处（非实测常数）", "反推" in e.note, e.note[:40])
    for run, want in (("246490", {"Y": 61.076, "Mz": 28.71, "Q": 34.032}),
                      ("246492", {"Y": 25.248, "Mz": 37.52, "Q": 39.461})):
        b = load_bundle([TESTDATA / "ca" / ("ca" + run), TESTDATA / "temp" / ("pa" + run),
                         TESTDATA / "da" / ("da" + run)])
        fv = extract_features(b, None, keys=["balance_load_ratio"], library=lib)
        per = fv["balance_load_ratio"].extras["per_unit"]
        ok = all(abs(per[u] - v) < 0.02 for u, v in want.items())
        check(run + " 各单元占比复现甲方报告", ok,
              " ".join(f"{u}={per[u]:.3f}%(报告{v})" for u, v in want.items()))


def t_trend_stats() -> None:
    section("13. 趋势统计量（Mann-Kendall / Hampel / Nelson）")
    rising = [float(i) for i in range(20)]
    mk = mann_kendall(rising)
    check("单调序列被判为显著上升", mk["significant"] and mk["direction"] == "上升",
          f"z={mk['z']} p={mk['p']}")
    check("Sen 斜率等于真实斜率", close(mk["sen_slope_per_run"], 1.0, 1e-9))
    flat = [1.0, 1.2, 0.9, 1.1, 1.0, 1.05, 0.95, 1.02, 0.98, 1.01]
    check("平稳序列不被判为趋势", not mann_kendall(flat)["significant"])
    spiked = flat[:5] + [9.0] + flat[5:]
    hp = hampel(spiked, k=3.0)
    check("Hampel 命中人为插入的尖峰",
          any(o["index"] == 5 for o in hp["outliers"]), str(hp["outliers"]))
    check("Hampel 不误报平稳序列", not hampel(flat, k=3.0)["outliers"])
    nl = nelson_runs([float(i) for i in range(130)], window=7)
    check("Nelson 报告实测与随机期望", nl["observed"] > 0 and nl["expected"] < 0.2,
          f"实测 {nl['observed']} / 期望 {nl['expected']}")


def t_trend_on_matrix() -> None:
    section("14. 130 车次上的趋势判定（防误报回归）")
    res = check_batch(_matrix_bundles(), library=default_library())
    trends = res.trends
    not_analysed = [t for t in trends if t.get("analysed") is False]
    analysed = [t for t in trends if t.get("analysed") is not False]
    flagged = [t for t in trends if t["flagged"]]
    check("状态相关量在多构型批次中不做趋势判定",
          len(not_analysed) >= 10 and all(t["state_dependent"] for t in not_analysed),
          f"{len(not_analysed)} 条未判定")
    check("未判定项写明理由",
          all("不做趋势判定" in t["headline"] for t in not_analysed))
    check("仅零点类量参与全批次趋势",
          all(not t["state_dependent"] for t in analysed), f"{len(analysed)} 条")
    check("告警数量远低于早期实现（曾 15/17 全报）",
          len(flagged) <= 5, f"{len(flagged)}/{len(trends)} 条告警")
    rz = next((t for t in trends if t["feature"] == "balance_return_zero"), None)
    check("统计显著但工程可忽略的漂移被明确标注",
          rz is not None and "工程上可忽略" in rz["headline"],
          (rz["headline"][-45:] if rz else ""))


def t_compare() -> None:
    section("15. 多车次对比引擎")
    bs = _matrix_bundles()
    sel = [b for b in bs if CMP.run_state(b)["M"] == 1.741
           and CMP.run_state(b)["BETA"] == 0
           and (CMP.run_state(b)["dy"] or 0) == 0 and (CMP.run_state(b)["dx"] or 0) == 0]
    check("筛出 Ma1.741/beta0 的 dz 系列 7 个车次", len(sel) == 7, str(len(sel)))

    r = CMP.curves_by_run(sel, x="ALPHA", ys=["CN"], sort_by=["dz"])
    dzs = [l["dz"] for l in r["legend"]]
    check("按舵偏角排序", dzs == sorted(dzs), str(dzs))
    check("图例携带完整状态", all({"M", "BETA", "PHI", "dz", "dy", "dx"} <= set(l)
                                  for l in r["legend"]))

    polar = CMP.curves_by_run(sel[:1], x="CN", ys=["CD"])
    check("以 CN 为横轴（阻力极曲线）", polar["ok"] and polar["x_key"] == "CN")

    d = CMP.curves_by_run(sel, x="ALPHA", ys=["CN"], baseline="246490", mode="delta",
                          sort_by=["dz"])
    at0 = {}
    for s_ in d["series"]:
        for x, y in zip(s_["x"], s_["y"]):
            if abs(x) < 1e-9:
                at0[s_["state"]["dz"]] = y
    vals = [at0[k] for k in sorted(at0)]
    check("dCN 随 dz 单调递增", all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)),
          " ".join(f"{k:+g}:{at0[k]:+.4f}" for k in sorted(at0)))
    check("基准车次自身差量恒为 0", abs(at0[0.0]) < 1e-12)

    baselines = [b for b in bs
                 if all((CMP.run_state(b).get(k) or 0) == 0 for k in ("dz", "dy", "dx"))
                 and CMP.run_state(b)["BETA"] == 0]
    m = CMP.curves_by_state(baselines, state_var="M", ys=["CAF"], alphas=[0.0])
    pts = dict(zip(m["series"][0]["x"], m["series"][0]["y"]))
    check("跨声速阻力上升（CAF Ma0.8 -> Ma1.05）", pts[1.05] > 1.8 * pts[0.8],
          f"{pts[0.8]:.4f} -> {pts[1.05]:.4f}")

    eff = CMP.control_effectiveness(bs, surface="dz", alphas=[0.0], coeffs=["CN"])
    by = {}
    for row in eff["rows"]:
        by.setdefault(row["mach"], []).append(row["derivative_per_deg"])
    avg = {k: sum(v) / len(v) for k, v in by.items()}
    check("舵效随马赫数下降（超声速 < 跨声速）", avg[1.741] < avg[1.05],
          " ".join(f"Ma{k:g}:{v:+.5f}" for k, v in sorted(avg.items())))

    resp = CMP.deflection_response(bs, surface="dz", alphas=[0.0], coeffs=["CN"])
    check("舵偏响应为描述性输出（无告警阈值）",
          "不设告警阈值" in resp["method"] and len(resp["blocks"]) == 12)

    sym = CMP.symmetry_check(bs, surface="dz", alphas=[0.0, 2.0, 4.0], coeffs=["CN"])
    check("对称性判异与同批次水平比而非与 0 比",
          "与本批次全部" in sym["method"] and len(sym["flagged"]) < 0.2 * len(sym["pairs"]),
          f"{len(sym['flagged'])}/{len(sym['pairs'])} 命中，中位数 {sym['median_asymmetry']:.1%}")

    header, rows_ = CMP.export_rows(d)
    check("导出表格结构正确", len(header) == len(d["series"]) + 1 and len(rows_) > 5,
          f"{len(header)} 列 x {len(rows_)} 行")
    check("CSV 含状态注释行", "# " in CMP.to_csv(d))


def t_repeatability_honest() -> None:
    section("16. 重复性（参数矩阵无重复车次时必须如实报告）")
    rep = analyse_repeatability(_matrix_bundles()).to_dict()
    check("识别出 130 个各不相同的状态", rep["group_count"] == 130, str(rep["group_count"]))
    check("重复组数为 0，不编造精度指标",
          rep["repeated_group_count"] == 0 and not rep["pooled_sd"])
    check("说明原因", any("只做了一次" in n for n in rep["notes"]), str(rep["notes"])[:80])
    one = load_bundle([TESTDATA / "ca" / "ca246490", TESTDATA / "temp" / "pa246490",
                       TESTDATA / "da" / "da246490"])
    twin = load_bundle([TESTDATA / "ca" / "ca246490", TESTDATA / "temp" / "pa246490",
                        TESTDATA / "da" / "da246490"])
    twin.run_no = "246490B"
    rep2 = analyse_repeatability([one, twin]).to_dict()
    check("给定重复车次时能算出 s_r（此处两份相同数据 -> s_r=0）",
          rep2["repeated_group_count"] == 1 and rep2["pooled_sd"].get("CN") == 0.0,
          f"CN s_r={rep2['pooled_sd'].get('CN')}")


def main() -> int:
    if not INPUT_DIR.exists():
        print(f"找不到测试数据目录：{INPUT_DIR}\n请设置环境变量 WT_FROMC 指向 FromC 下的场景目录。")
        return 2
    suites = [t_units, t_parsers, t_customer_ground_truth, t_fixed_defects,
              t_rule_engine, t_balance_library, t_frames_and_curves,
              t_report, t_trend, t_custom_extractor]
    if TESTDATA.exists():
        suites += [t_printed_da, t_recovered_balance, t_trend_stats,
                   t_trend_on_matrix, t_compare, t_repeatability_honest]
    else:
        print("（跳过 130 车次相关用例：找不到 " + str(TESTDATA) + "）")
    for fn in suites:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            check(f"{fn.__name__} 执行异常", False, f"{type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n{'=' * 72}")
    print(f"离线回归：通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
