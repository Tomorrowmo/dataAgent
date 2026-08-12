"""Report assembly — sectioned, selectable, editable, exportable.

The specification asks for four things the legacy tool does not do:
选择报告内容 / 预览可编辑 / 导出 / 命名为「车次号_跟班记录」. All four fall out
of one decision: a report is a **list of sections**, each rendered to Markdown
independently, and the assembled Markdown is what the user edits and exports.
Nothing about the pipeline needs to know which sections a user picked.

Two output shapes are produced from the same findings:

* :func:`build_report` — the full quality report (概况 / 明细 / 曲线 / 趋势 / 判据附录).
* :func:`build_shift_record` — the 跟班记录, reproducing the numbered
  plain-sentence format the tunnel's engineers already hand in, so the output
  drops into their existing paperwork unchanged.

Every finding printed carries its measured value, the band that matched, how
the value was computed, and the citation behind the threshold. A reviewer can
therefore audit a verdict without opening the source — which is the whole
argument for using this tool instead of a chat model that "looks confident".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .pipeline import BatchResult, RunResult
from .rules import LEVEL_LABEL, Finding

LEVEL_ICON = {"critical": "■ 严重", "warning": "▲ 警告", "notice": "◆ 注意", "ok": "● 正常"}

#: Report sections a user can tick on/off, in render order.
SECTIONS: List[Dict[str, str]] = [
    {"key": "overview", "name": "车次基本信息", "desc": "车次号、马赫数、模型、天平、文件齐套情况"},
    {"key": "verdict", "name": "总体质量评估", "desc": "评级与问题计数"},
    {"key": "problems", "name": "异常项明细", "desc": "逐条列出原因分析、影响评估、处理建议"},
    {"key": "all_items", "name": "全部检查项", "desc": "含正常项与未评定项的完整清单"},
    {"key": "unavailable", "name": "未评定项说明", "desc": "缺哪些数据、如何补齐"},
    {"key": "curves", "name": "气动曲线与规律结论", "desc": "曲线特征量与结论"},
    {"key": "trends", "name": "多车次趋势", "desc": "跨车次特征量走势与趋势告警"},
    {"key": "shift_record", "name": "跟班记录正文", "desc": "沿用现行编号叙述格式"},
    {"key": "basis", "name": "判据与依据附录", "desc": "每条规则的阈值出处与引用标准"},
]

DEFAULT_SECTIONS = ["overview", "verdict", "problems", "unavailable",
                    "curves", "shift_record", "basis"]


@dataclass
class ReportOptions:
    sections: List[str] = field(default_factory=lambda: list(DEFAULT_SECTIONS))
    title: str = ""
    author: str = ""
    #: Optional LLM-written narrative blocks, keyed by section ("curves", …).
    narratives: Dict[str, str] = field(default_factory=dict)

    def wants(self, key: str) -> bool:
        return key in self.sections


def _fmt(value: Optional[float], unit: str) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000 or (value != 0 and abs(value) < 1e-3):
        s = f"{value:.6g}"
    else:
        s = f"{value:.6g}"
    return f"{s} {unit}".strip()


def _now() -> str:
    return datetime.now().strftime("%Y年%m月%d日 %H:%M")


# ══════════════════════════════════════════════════════════════════════════
#  sections
# ══════════════════════════════════════════════════════════════════════════
def _sec_overview(run: RunResult) -> str:
    m = run.meta
    rows = [
        ("车次号", m.get("run_no", "")),
        ("马赫数", f"{m.get('mach')}" if m.get("mach") else "—"),
        ("模型", m.get("model") or "—"),
        ("天平型式", m.get("balance_type") or "—"),
        ("天平弹性角公式", m.get("balance_formula") or "—"),
        ("试验类型", "测力试验" if m.get("is_force_test") else "非测力试验（部分检查不适用）"),
        ("吹风点数", str(m.get("n_blow_points", 0))),
        ("导入文件", "、".join(m.get("files", [])) or "—"),
        ("零飘比对车次", run.compared_with or "无（本批次首车次）"),
    ]
    out = ["## 一、车次基本信息", "", "| 项目 | 内容 |", "| --- | --- |"]
    out += [f"| {k} | {v} |" for k, v in rows]
    warns = m.get("warnings") or []
    if warns:
        out += ["", "> 导入提示：" + "；".join(warns)]
    return "\n".join(out)


def _sec_verdict(run: RunResult) -> str:
    c = run.counts()
    return "\n".join([
        "## 二、总体质量评估", "",
        f"- **本车次评级：{run.grade}**",
        f"- 严重问题 {c['critical']} 项，警告 {c['warning']} 项，需关注 {c['notice']} 项，"
        f"正常 {c['ok']} 项，未评定 {c['unavailable']} 项，不适用 {c['skipped']} 项。",
        "",
        "> 评级口径：出现任一「严重」判定为**不合格**；仅有「警告」为**有条件合格**；"
        "仅有「需关注」为**合格(需关注)**；其余为**合格**。未评定项不计入合格判定，"
        "但必须在报告中如实列出。",
    ])


def _finding_block(i: int, f: Finding) -> str:
    lines = [
        f"### {i}. {f.rule_name} — {LEVEL_ICON.get(f.level, f.level)}",
        "",
        f"- **监测特征**：{f.feature_name}",
        f"- **实测值**：{_fmt(f.value, f.unit)}",
        f"- **判定结论**：{f.verdict}",
    ]
    if f.detail:
        lines.append(f"- **测量说明**：{f.detail}")
    if f.cause:
        lines.append(f"- **原因分析**：{f.cause}")
    if f.impact:
        lines.append(f"- **影响评估**：{f.impact}")
    if f.action:
        lines.append(f"- **处理建议**：{f.action}")
    if f.method:
        lines.append(f"- **计算方法**：`{f.method}`")
    per_unit = f.extras.get("per_unit") or f.extras.get("per_sensor")
    if isinstance(per_unit, dict) and per_unit:
        detail = "、".join(f"{k}={v:g}" for k, v in per_unit.items())
        lines.append(f"- **分量明细**：{detail}")
    if f.refs:
        lines.append("- **判据依据**：")
        lines += [f"  - {r}" for r in f.refs]
    return "\n".join(lines)


def _sec_problems(run: RunResult) -> str:
    probs = sorted(run.problems, key=lambda f: 0 if f.level == "critical" else 1)
    if not probs:
        return "## 三、异常项明细\n\n本车次未发现警告及以上级别的异常项。"
    out = ["## 三、异常项明细", ""]
    for i, f in enumerate(probs, 1):
        out += [_finding_block(i, f), ""]
    return "\n".join(out).rstrip()


def _sec_all_items(run: RunResult) -> str:
    out = ["## 附：全部检查项一览", "",
           "| # | 检查项 | 监测特征 | 实测值 | 结论 | 等级 |",
           "| --- | --- | --- | --- | --- | --- |"]
    for i, f in enumerate(run.findings, 1):
        lv = LEVEL_ICON.get(f.level, f.level) if f.status == "evaluated" else \
            ("○ 未评定" if f.status == "unavailable" else "– 不适用")
        out.append(f"| {i} | {f.rule_name} | {f.feature_name} | {_fmt(f.value, f.unit)} "
                   f"| {f.verdict} | {lv} |")
    return "\n".join(out)


def _sec_unavailable(run: RunResult) -> str:
    items = run.unavailable
    if not items:
        return "## 四、未评定项说明\n\n本车次所有检查项均已完成评定，无缺数据项。"
    out = ["## 四、未评定项说明", "",
           "以下检查项因所需数据不可用而**未做评定**。未评定不等于合格，请按“补齐方式”处理后重跑。",
           "", "| 检查项 | 缺失原因 / 补齐方式 |", "| --- | --- |"]
    for f in items:
        out.append(f"| {f.rule_name} | {f.detail} |")
    return "\n".join(out)


def _sec_curves(curve: Optional[Dict[str, Any]], stats: Optional[List[Dict[str, Any]]],
                narrative: str) -> str:
    if not curve or not curve.get("ok"):
        return "## 五、气动曲线与规律结论\n\n本车次没有可用的 da(气动结果) 文件，未绘制气动曲线。"
    out = ["## 五、气动曲线与规律结论", "",
           f"横轴：{curve.get('x_label')}；纵轴：" +
           "、".join(s["label"] for s in curve.get("series", [])), ""]
    if curve.get("flow"):
        flow = curve["flow"]
        out += ["**来流条件**：" + "，".join(f"{k}={v:g}" for k, v in flow.items()), ""]
    if stats:
        out += ["| 系数 | 线性斜率 (每度) | 线性度 R² | 最小值 | 最大值 | 单调 | 最大偏离线性处 |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for s in stats:
            out.append(
                f"| {s['label']} | {s['slope_per_deg']:.6g} | {s['r2']:.4f} "
                f"| {s['min']['y']:.6g} @ α={s['min']['x']:g}° "
                f"| {s['max']['y']:.6g} @ α={s['max']['x']:g}° "
                f"| {'是' if s['monotone'] else '否'} "
                f"| α={s['max_nonlinearity']['x']:g}°，偏离 {s['max_nonlinearity']['deviation']:.4g} |"
            )
        out += ["", "> 斜率为最小二乘线性拟合值；R² 越接近 1 表示该系数在本攻角段越接近线性。"
                    "力矩系数的非线性通常对应压心迁移或分离/激波状态变化。", ""]
    if narrative:
        out += ["**气动规律结论**", "", narrative, ""]
    return "\n".join(out).rstrip()


def _sec_trends(batch: Optional[BatchResult]) -> str:
    if batch is None or not batch.trends:
        return "## 六、多车次趋势\n\n本次仅处理单个车次，未做跨车次趋势分析。"
    out = ["## 六、多车次趋势", "",
           "| 特征量 | 车次序列 | 数值 | 趋势 | 判定 |", "| --- | --- | --- | --- | --- |"]
    flagged = []
    for t in batch.trends:
        mark = "⚠ 趋势告警" if t["flagged"] else "—"
        if t["flagged"]:
            flagged.append(t)
        out.append(f"| {t['name']} ({t['unit']}) | {'→'.join(t['runs'])} "
                   f"| {', '.join(f'{v:g}' for v in t['values'])} | {t['trend']} | {mark} |")
    if flagged:
        out += ["", "**趋势告警说明**", ""]
        for t in flagged:
            out += [f"- {t['name']}：{t['note']}", f"  - 判据依据：{t['reference']}"]
    else:
        out += ["", "> 未发现达到趋势判据窗口的单调走势。"]
    return "\n".join(out)


def _sec_basis(run: RunResult) -> str:
    out = ["## 附录：判据与依据", "",
           "本报告的每一条判定都由「特征量 → 规则区间」显式绑定产生，不使用文本相似度匹配。",
           "各规则的阈值出处如下。", ""]
    seen = set()
    for f in run.findings:
        if f.rule_id in seen:
            continue
        seen.add(f.rule_id)
        out.append(f"**{f.rule_name}**（特征：{f.feature_name}；计算：`{f.method or '—'}`）")
        for r in f.refs:
            out.append(f"- {r}")
        out.append("")
    return "\n".join(out).rstrip()


# ══════════════════════════════════════════════════════════════════════════
#  the 跟班记录 — the tunnel's own paperwork format
# ══════════════════════════════════════════════════════════════════════════
def build_shift_record(run: RunResult, *, date: Optional[str] = None) -> str:
    """Reproduce the numbered plain-sentence shift record.

    Format mirrors the customer's existing ``NNNNN车次跟班记录.txt`` so the
    output can be filed without re-typing: a date header, the run number in
    brackets, then one numbered sentence per check. Items that failed carry the
    ``- P`` marker their downstream tooling looks for.
    """
    d = date or datetime.now().strftime("%Y年%m月%d日")
    lines = [f"{d} 跟班记录", "", f"【车次 {run.run_no}】"]
    n = 0
    for f in run.findings:
        if f.status == "skipped":
            continue
        n += 1
        if f.status == "unavailable":
            lines.append(f"{n}. {f.feature_name}：未评定（{f.detail}）")
            continue
        val = _fmt(f.value, f.unit)
        tail = " - P" if f.is_problem else ""
        sentence = f"{n}. {f.feature_name}为{val}"
        if f.is_problem:
            sentence += f"，{f.verdict}；建议：{f.action}"
        elif f.level == "notice":
            sentence += f"，{f.verdict}"
        lines.append(sentence + tail)
    lines += ["", f"本车次评级：{run.grade}"]
    if run.compared_with:
        lines.append(f"零飘比对车次：{run.compared_with}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
#  public builders
# ══════════════════════════════════════════════════════════════════════════
def build_report(
    run: RunResult,
    *,
    options: Optional[ReportOptions] = None,
    curve: Optional[Dict[str, Any]] = None,
    curve_stats: Optional[List[Dict[str, Any]]] = None,
    batch: Optional[BatchResult] = None,
) -> str:
    opts = options or ReportOptions()
    title = opts.title or f"风洞试验过程质量检查报告 — 车次 {run.run_no}"
    head = [f"# {title}", "",
            f"生成时间：{_now()}" + (f"　编制：{opts.author}" if opts.author else ""), ""]

    body: List[str] = []
    if opts.wants("overview"):
        body.append(_sec_overview(run))
    if opts.wants("verdict"):
        body.append(_sec_verdict(run))
    if opts.wants("problems"):
        body.append(_sec_problems(run))
    if opts.wants("unavailable"):
        body.append(_sec_unavailable(run))
    if opts.wants("curves"):
        body.append(_sec_curves(curve, curve_stats, opts.narratives.get("curves", "")))
    if opts.wants("trends"):
        body.append(_sec_trends(batch))
    if opts.wants("shift_record"):
        body.append("## 七、跟班记录正文\n\n```\n" + build_shift_record(run) + "\n```")
    if opts.wants("all_items"):
        body.append(_sec_all_items(run))
    if opts.wants("basis"):
        body.append(_sec_basis(run))

    return "\n".join(head) + "\n\n".join(body) + "\n"


def build_batch_summary(batch: BatchResult, *, title: str = "") -> str:
    """The multi-run 汇总报告."""
    s = batch.summary()
    out = [f"# {title or '风洞试验数据质量监测汇总报告'}", "",
           f"生成时间：{_now()}", "",
           f"- 车次数：**{s['run_count']}**",
           f"- 严重问题合计：**{s['totals']['critical']}**，警告合计：**{s['totals']['warning']}**，"
           f"需关注合计：**{s['totals']['notice']}**，未评定合计：**{s['totals']['unavailable']}**",
           f"- 存在严重问题的车次：{'、'.join(s['failed_runs']) or '无'}",
           f"- 存在警告的车次：{'、'.join(s['warned_runs']) or '无'}",
           f"- **批次总体评级：{s['grade']}**", "",
           "## 各车次评级", "",
           "| 车次 | 评级 | 严重 | 警告 | 关注 | 未评定 | 零飘比对 |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in batch.runs:
        c = r.counts()
        out.append(f"| {r.run_no} | {r.grade} | {c['critical']} | {c['warning']} "
                   f"| {c['notice']} | {c['unavailable']} | {r.compared_with or '—'} |")
    out += ["", _sec_trends(batch)]
    if batch.notes:
        out += ["", "## 处理提示", ""] + [f"- {n}" for n in batch.notes]

    # Aggregate the distinct problems so a reader sees the batch's real story.
    out += ["", "## 本批次问题汇总", ""]
    any_problem = False
    for r in batch.runs:
        if not r.problems:
            continue
        any_problem = True
        out.append(f"**车次 {r.run_no}**")
        for f in r.problems:
            out.append(f"- {LEVEL_ICON.get(f.level)} {f.rule_name}："
                       f"{_fmt(f.value, f.unit)} — {f.verdict}；建议：{f.action}")
        out.append("")
    if not any_problem:
        out.append("本批次未发现警告及以上级别的问题。")
    return "\n".join(out) + "\n"


def report_filename(run_no: str, kind: str = "shift", ext: str = "txt") -> str:
    """``246490_跟班记录.txt`` — the naming the specification mandates."""
    stem = {"shift": "跟班记录", "report": "质量检查报告", "summary": "质量监测汇总报告"}
    return f"{run_no}_{stem.get(kind, '报告')}.{ext}"
