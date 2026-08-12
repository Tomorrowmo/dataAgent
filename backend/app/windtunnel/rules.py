"""Rule engine — the *judgement* half of a quality check.

A rule is DATA, not code
------------------------
Each rule binds one feature key to an ordered list of bands. A band is a
half-open numeric interval plus the verdict, severity and recommended action
that apply inside it::

    Rule(
      rule_id="rule_01_balance_zero_drift",
      feature="balance_zero_drift",
      bands=[
        Band(lo=0.012, level="critical", verdict="天平零飘严重超限", action="停止试验并维修天平"),
        Band(lo=0.008, hi=0.012, level="warning", verdict="天平零飘偏大", action="检查天平"),
        Band(lo=0.005, hi=0.008, level="notice",  verdict="天平零飘略有增大", action="引起注意"),
        Band(hi=0.005, level="ok", verdict="天平零飘正常"),
      ],
    )

Consequences that matter for this product:

* **Changing a limit is a data edit**, doable from the UI by a test engineer,
  with no redeploy and no Python.
* **A reading cannot be diagnosed by the wrong rule** — the binding is by key,
  not by text similarity. (The demo this replaces reported a 天平零飘 value
  under 「天平回零异常诊断」 at "50.51% match".)
* **Every verdict is auditable**: the finding carries the measured value, the
  band that matched, the extraction method, and the citations behind the
  threshold.

Severity ladder
---------------
``ok`` < ``notice`` (引起注意) < ``warning`` (需检查) < ``critical`` (停止试验).
This mirrors the four-tier wording used throughout the customer's rule book and
maps cleanly onto the report's 合格 / 关注 / 不合格 grading.

Citation policy
---------------
``refs`` records where a threshold comes from. Three provenance classes are
used, in descending authority for this deployment:

1. ``甲方规则书`` — the twelve Markdown rules supplied by the customer. These
   are engineering agreements for THIS tunnel and are never silently altered.
2. Public standards — AIAA S-071A-1999 (wind-tunnel测量不确定度评定),
   AIAA R-091-2003 (内式应变天平校准与使用), ASME PTC 19.1 (Test Uncertainty),
   GJB 1179A-2012 (高速风洞流场品质), ISO 5725 (准确度: 正确度与精密度).
3. Classical method references — NIST/SEMATECH e-Handbook §1.3.5.17 (Grubbs /
   Dixon outlier tests), Nelson (1984) control-chart rules, Savitzky & Golay
   (1964). These back the *generic* detectors a user adds later, not the
   customer's fixed limits.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .features import FEATURE_SPECS, FeatureValue

LEVELS = ("ok", "notice", "warning", "critical")
LEVEL_RANK = {lv: i for i, lv in enumerate(LEVELS)}
LEVEL_LABEL = {
    "ok": "正常",
    "notice": "引起注意",
    "warning": "需检查",
    "critical": "停止试验",
}


@dataclass
class Band:
    """A half-open interval ``[lo, hi)`` and the verdict inside it.

    ``lo``/``hi`` may be None for an open end. Bands are evaluated in order and
    the first match wins, so an author can write them most-severe-first and not
    worry about touching boundaries.
    """

    level: str = "ok"
    lo: Optional[float] = None
    hi: Optional[float] = None
    verdict: str = ""
    action: str = ""
    cause: str = ""      # 原因分析
    impact: str = ""     # 影响评估

    def matches(self, v: float) -> bool:
        if self.lo is not None and not (v > self.lo or math.isclose(v, self.lo)):
            return False
        if self.lo is not None and math.isclose(v, self.lo) and self.hi is not None:
            # Boundary belongs to the band whose lo it is (>= lo, < hi).
            pass
        if self.hi is not None and not (v < self.hi):
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level, "lo": self.lo, "hi": self.hi,
            "verdict": self.verdict, "action": self.action,
            "cause": self.cause, "impact": self.impact,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Band":
        return cls(
            level=d.get("level", "ok"),
            lo=None if d.get("lo") in (None, "") else float(d["lo"]),
            hi=None if d.get("hi") in (None, "") else float(d["hi"]),
            verdict=d.get("verdict", ""), action=d.get("action", ""),
            cause=d.get("cause", ""), impact=d.get("impact", ""),
        )


@dataclass
class Rule:
    rule_id: str
    name: str
    feature: str
    bands: List[Band]
    object_: str = ""        # 【对象】
    note: str = ""           # 【工程说明】
    refs: List[str] = field(default_factory=list)
    enabled: bool = True
    source: str = "builtin"  # builtin | user | ai
    #: Optional gate — only evaluate when this Mach condition holds. Written as
    #: a comparison against the run's nominal Mach, e.g. ``"<2.9"`` / ``">=2.9"``.
    #: Rule 06 needs it: the tunnel allows a looser Mach tolerance above Ma 2.9.
    applies_when_mach: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id, "name": self.name, "feature": self.feature,
            "object": self.object_, "note": self.note, "refs": list(self.refs),
            "enabled": self.enabled, "source": self.source,
            "applies_when_mach": self.applies_when_mach,
            "bands": [b.to_dict() for b in self.bands],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Rule":
        return cls(
            rule_id=d["rule_id"], name=d.get("name", d["rule_id"]),
            feature=d["feature"],
            bands=[Band.from_dict(b) for b in d.get("bands", [])],
            object_=d.get("object", ""), note=d.get("note", ""),
            refs=list(d.get("refs", [])), enabled=bool(d.get("enabled", True)),
            source=d.get("source", "user"),
            applies_when_mach=d.get("applies_when_mach", ""),
        )

    def validate(self) -> List[str]:
        problems: List[str] = []
        if not self.rule_id.strip():
            problems.append("规则 ID 不能为空")
        if self.feature not in FEATURE_SPECS:
            problems.append(
                f"特征「{self.feature}」不存在。可用特征："
                + "、".join(sorted(FEATURE_SPECS))
            )
        if not self.bands:
            problems.append("至少要有一个区间(band)")
        for i, b in enumerate(self.bands, 1):
            if b.level not in LEVELS:
                problems.append(f"第 {i} 个区间的等级「{b.level}」无效，应为 {'/'.join(LEVELS)}")
            if b.lo is not None and b.hi is not None and b.lo >= b.hi:
                problems.append(f"第 {i} 个区间的下限 {b.lo} 不小于上限 {b.hi}")
            if b.level != "ok" and not b.verdict:
                problems.append(f"第 {i} 个区间缺少判定结论(verdict)")
        if self.applies_when_mach and not re.match(
            r"^\s*(<=|>=|<|>|==)\s*-?\d+(\.\d+)?\s*$", self.applies_when_mach
        ):
            problems.append("Mach 适用条件格式应形如 '<2.9' 或 '>=2.9'")
        return problems

    def gate_passes(self, mach: Optional[float]) -> bool:
        if not self.applies_when_mach:
            return True
        if mach is None:
            return False
        m = re.match(r"^\s*(<=|>=|<|>|==)\s*(-?\d+(?:\.\d+)?)\s*$", self.applies_when_mach)
        if not m:
            return True
        op, num = m.group(1), float(m.group(2))
        return {
            "<": mach < num, "<=": mach <= num, ">": mach > num,
            ">=": mach >= num, "==": math.isclose(mach, num),
        }[op]


@dataclass
class Finding:
    """One rule's verdict on one run — the atomic unit of the report."""

    rule_id: str
    rule_name: str
    feature: str
    feature_name: str
    level: str
    value: Optional[float]
    unit: str
    verdict: str
    action: str = ""
    cause: str = ""
    impact: str = ""
    detail: str = ""
    method: str = ""
    refs: List[str] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)
    #: "evaluated" — a band matched; "unavailable" — the feature could not be
    #: measured; "skipped" — a Mach/shape gate excluded the rule.
    status: str = "evaluated"

    @property
    def is_problem(self) -> bool:
        return self.status == "evaluated" and self.level in ("warning", "critical")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id, "rule_name": self.rule_name,
            "feature": self.feature, "feature_name": self.feature_name,
            "level": self.level, "level_label": LEVEL_LABEL.get(self.level, self.level),
            "value": self.value, "unit": self.unit, "verdict": self.verdict,
            "action": self.action, "cause": self.cause, "impact": self.impact,
            "detail": self.detail, "method": self.method, "refs": list(self.refs),
            "extras": self.extras, "status": self.status,
        }


def evaluate(
    rules: List[Rule],
    features: Dict[str, FeatureValue],
    *,
    mach: Optional[float] = None,
) -> List[Finding]:
    """Apply every enabled rule to the measured features.

    A rule whose feature is unavailable produces an ``unavailable`` finding
    carrying the reason — it is NEVER dropped and never defaults to "normal".
    Silently omitting an unmeasurable check is how a report ends up claiming
    twelve passes when only ten ran.
    """
    out: List[Finding] = []
    for rule in rules:
        if not rule.enabled:
            continue
        fv = features.get(rule.feature)
        spec = FEATURE_SPECS.get(rule.feature)
        fname = fv.name if fv else (spec.name if spec else rule.feature)
        funit = fv.unit if fv else (spec.unit if spec else "")

        if not rule.gate_passes(mach):
            out.append(Finding(
                rule_id=rule.rule_id, rule_name=rule.name, feature=rule.feature,
                feature_name=fname, level="ok", value=fv.value if fv else None,
                unit=funit, verdict="本车次不满足该规则的适用条件，未评定",
                detail=f"适用条件：马赫数 {rule.applies_when_mach}（本车次 Ma={mach}）",
                refs=list(rule.refs), status="skipped",
            ))
            continue

        if fv is None or not fv.available:
            out.append(Finding(
                rule_id=rule.rule_id, rule_name=rule.name, feature=rule.feature,
                feature_name=fname, level="ok", value=None, unit=funit,
                verdict="未评定——所需数据不可用",
                detail=(fv.detail if fv else "特征未计算"),
                method=(fv.method if fv else ""), refs=list(rule.refs),
                status="unavailable",
            ))
            continue

        band = next((b for b in rule.bands if b.matches(fv.value)), None)
        if band is None:
            out.append(Finding(
                rule_id=rule.rule_id, rule_name=rule.name, feature=rule.feature,
                feature_name=fname, level="ok", value=fv.value, unit=funit,
                verdict="未评定——测量值不落在任何已定义区间内",
                detail=f"实测 {fv.value:g} {funit}；请检查规则区间是否覆盖完整",
                method=fv.method, refs=list(rule.refs), extras=fv.extras,
                status="unavailable",
            ))
            continue

        out.append(Finding(
            rule_id=rule.rule_id, rule_name=rule.name, feature=rule.feature,
            feature_name=fname, level=band.level, value=fv.value, unit=funit,
            verdict=band.verdict or f"{fname}{LEVEL_LABEL.get(band.level, '')}",
            action=band.action, cause=band.cause, impact=band.impact,
            detail=fv.detail, method=fv.method, refs=list(rule.refs),
            extras=fv.extras,
        ))
    return out


def worst_level(findings: List[Finding]) -> str:
    lv = "ok"
    for f in findings:
        if f.status != "evaluated":
            continue
        if LEVEL_RANK[f.level] > LEVEL_RANK[lv]:
            lv = f.level
    return lv


def grade(findings: List[Finding]) -> str:
    """Overall grade for a run — the line the shift record leads with."""
    lv = worst_level(findings)
    if lv == "critical":
        return "不合格"
    if lv == "warning":
        return "有条件合格"
    if lv == "notice":
        return "合格(需关注)"
    return "合格"
