"""LLM-facing capabilities for the wind-tunnel workflow.

The contract, stated once because it governs every function here:

    **The model decides wording and structure. It never produces a number
    that reaches a report.**

* :func:`draft_rule` — natural language → a *validated* rule object. The model
  picks an existing feature key and proposes bands; the thresholds it suggests
  are shown to the user as a draft, previewed against real runs, and only take
  effect once the user saves them.
* :func:`plan_custom_check` — decides whether a request maps onto an existing
  feature or needs a new extractor, so the UI knows which path to offer.
* :func:`generate_extractor` — natural language → sandboxed feature-extractor
  code, via the platform's existing codegen + AST validation + smoke test.
* :func:`aero_conclusion` — narrates curve statistics that were computed
  deterministically. The numbers are handed to the model; it may not invent
  new ones.
* :func:`explain_findings` — turns a finished check into a shift-record-style
  paragraph, again from computed findings only.

Everything degrades cleanly when no API key is configured: each function
returns a structured "unavailable" result and the deterministic pipeline keeps
working. That is deliberate — a quality check must not depend on a network
call.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from ..services.codegen import generate_algorithm
from ..services.llm import LLMClient, LLMError
from .features import FEATURE_SPECS
from .knowledge import (
    cite_hint,
    extractor_context,
    feature_catalog,
    rule_drafting_context,
)
from .rules import Rule


def _extract_json(text: str) -> Dict[str, Any]:
    """Pull the first JSON object out of a model reply, fences or not."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    depth, start = 0, -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(s[start:i + 1])
                except json.JSONDecodeError:
                    start = -1
    raise ValueError("模型没有返回可解析的 JSON")


# ══════════════════════════════════════════════════════════════════════════
#  1. natural language → rule
# ══════════════════════════════════════════════════════════════════════════
_RULE_SYSTEM = """你是风洞试验数据质量检查领域的规则工程师。
用户用自然语言描述一条“希望系统帮我盯住的异常”，你要把它翻译成一条结构化规则。

绝对要求：
1. 只输出一个 JSON 对象，不要任何解释文字、不要 Markdown 代码围栏。
2. `feature` 字段必须严格取自给定的 feature key 列表；如果列表里没有任何一个能测量
   用户想要的量，则把 `feature` 设为 null，并在 `needs_new_feature` 里说明需要新增
   什么测量量（用一句话描述它怎么从数据里算出来）。**绝不允许发明 feature key。**
3. 阈值优先采用用户明确给出的数字。用户没给数字时，你可以给一个建议值，但必须在
   `threshold_source` 里如实写明“AI 建议值，需人工确认”。**不要假装它来自某个标准。**
4. bands 必须覆盖整个数值范围且从最严重往下排列，最后一条是 level="ok"。
5. 每个非 ok 区间都要写 verdict / cause / impact / action 四项，面向一线试验人员，
   用中文，具体、可执行，不要空话。
6. verdict 文字里如果要带单位，必须用 feature 清单中该 feature 的单位原文
   （例如天平类特征的单位是「码」，不是 mmH2O）。**不要臆造单位。**

输出 JSON 结构：
{
  "rule_id": "rule_custom_<英文小写下划线>",
  "name": "中文规则名",
  "feature": "feature key 或 null",
  "needs_new_feature": "" 或 "需要新增的测量量描述",
  "object": "监测对象",
  "note": "工程说明：为什么这么判",
  "applies_when_mach": "" 或 "<2.9" 之类,
  "refs": ["依据出处"],
  "threshold_source": "阈值来源说明",
  "bands": [ {"level","lo","hi","verdict","cause","impact","action"}, ... ],
  "reasoning": "一句话说明你为什么选这个 feature"
}"""


async def draft_rule(
    request: str,
    *,
    llm: LLMClient,
    existing_rule_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Turn a plain-language request into a validated draft rule."""
    if not llm.is_configured:
        return {"ok": False, "error": "未配置大模型 API Key，无法使用 AI 规则起草。"
                                      "你仍可以在规则库里手工新增规则。"}
    taken = "、".join(existing_rule_ids or []) or "（暂无）"
    user = (
        f"{rule_drafting_context()}\n\n"
        f"已存在的 rule_id（不要重复）：{taken}\n\n"
        f"{cite_hint()}\n\n"
        f"用户的需求：\n{request.strip()}"
    )
    try:
        text = await llm.chat(
            [{"role": "system", "content": _RULE_SYSTEM}, {"role": "user", "content": user}],
            temperature=0.1, max_tokens=2600, json_mode=True,
        )
    except LLMError as e:
        return {"ok": False, "error": f"大模型调用失败：{e}"}

    try:
        data = _extract_json(text)
    except ValueError as e:
        return {"ok": False, "error": str(e), "raw": text[:2000]}

    needs_new = (data.get("needs_new_feature") or "").strip()
    feature = data.get("feature")
    if not feature:
        return {
            "ok": False,
            "needs_new_feature": needs_new or "模型认为现有特征无法测量该需求",
            "draft": data,
            "error": "现有特征无法测量这个需求，需要先新增一个自定义特征算子。",
            "next_action": "generate_extractor",
        }
    if feature not in FEATURE_SPECS and not str(feature).startswith("custom:"):
        return {
            "ok": False,
            "error": f"模型选择的特征「{feature}」不存在。可用特征见规则库的特征清单。",
            "draft": data,
        }

    payload = {
        "rule_id": data.get("rule_id") or "rule_custom_unnamed",
        "name": data.get("name") or "未命名规则",
        "feature": feature,
        "object": data.get("object", ""),
        "note": data.get("note", ""),
        "applies_when_mach": data.get("applies_when_mach", "") or "",
        "refs": list(data.get("refs") or []),
        "bands": data.get("bands") or [],
        "enabled": True,
        "source": "ai",
    }
    src = (data.get("threshold_source") or "").strip()
    if src:
        payload["refs"] = payload["refs"] + [f"阈值来源：{src}"]

    try:
        rule = Rule.from_dict(payload)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"草稿结构不合法：{type(e).__name__}: {e}",
                "draft": data}
    problems = rule.validate()
    return {
        "ok": not problems,
        "rule": rule.to_dict(),
        "problems": problems,
        "reasoning": data.get("reasoning", ""),
        "threshold_source": src,
        "raw": data,
    }


# ══════════════════════════════════════════════════════════════════════════
#  2. route a request: existing feature vs new extractor
# ══════════════════════════════════════════════════════════════════════════
_PLAN_SYSTEM = """你是风洞数据质量检查系统的分诊员。用户描述一个想监测的现象，
你判断现有特征清单里是否已经有能测量它的量。

只输出 JSON：
{"matched": true/false,
 "feature": "匹配到的 feature key 或 null",
 "confidence": 0.0-1.0,
 "why": "一句话理由",
 "new_feature_brief": "若 matched=false，用一句话描述需要新增的测量量及其算法"}

判定要严格：物理含义必须真正一致才算匹配。
「一致性」不同于「突变」，「左右之差」不同于「与平均值之差」，
「零点漂移(跨车次)」不同于「回零量(同车次首末)」。宁可 matched=false，
也不要把用户的需求硬塞给一个含义不同的特征——错配的诊断比没有诊断更危险。"""


async def plan_custom_check(request: str, *, llm: LLMClient) -> Dict[str, Any]:
    if not llm.is_configured:
        return {"ok": False, "error": "未配置大模型 API Key。"}
    user = (f"可用特征清单：\n{feature_catalog()}\n\n用户需求：\n{request.strip()}")
    try:
        text = await llm.chat(
            [{"role": "system", "content": _PLAN_SYSTEM}, {"role": "user", "content": user}],
            temperature=0.0, max_tokens=800, json_mode=True,
        )
        data = _extract_json(text)
    except (LLMError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    feat = data.get("feature")
    if data.get("matched") and feat not in FEATURE_SPECS and not str(feat or "").startswith("custom:"):
        data["matched"] = False
        data["why"] = (data.get("why", "") + "（模型给出的特征名不存在，已按“需要新增”处理）").strip()
    data["ok"] = True
    return data


# ══════════════════════════════════════════════════════════════════════════
#  3. natural language → sandboxed feature extractor
# ══════════════════════════════════════════════════════════════════════════
async def generate_extractor(
    request: str,
    *,
    llm: LLMClient,
    schema_hint: str = "",
    max_attempts: int = 3,
) -> Dict[str, Any]:
    """Write a custom feature extractor, then prove it runs in the sandbox.

    Delegates to the platform's own codegen service, so the extractor inherits
    the same guarantees as every other user algorithm: AST whitelist, no file
    or network access, wall-clock timeout, and a smoke test that must pass
    before the code is offered for approval.
    """
    if not llm.is_configured:
        return {"ok": False, "error": "未配置大模型 API Key，无法使用 AI 生成算法。"}
    prompt = (
        f"{extractor_context()}\n\n"
        f"请按上述契约编写一个风洞质量检查的**特征算子**。\n"
        f"用户需求：{request.strip()}\n\n"
        f"注意：`run()` 必须返回含 value / unit 的 dict；只负责测量，不要写任何阈值判定；"
        f"`category` 固定填 \"custom\"；test_cases 里构造的 DataFrame 必须符合长表列结构。"
    )
    hint = schema_hint or ""
    result = await generate_algorithm(prompt, llm=llm, schema_hint=hint,
                                      max_attempts=max_attempts)
    result["ok"] = bool(result.get("all_tests_passed"))
    meta = result.get("meta") or {}
    slug = meta.get("slug") or ""
    result["feature_key"] = f"custom:{slug}" if slug else ""
    if not result["ok"]:
        result.setdefault("error", result.get("final_error") or "沙箱测试未通过")
    return result


# ══════════════════════════════════════════════════════════════════════════
#  4. aerodynamic narrative from computed statistics
# ══════════════════════════════════════════════════════════════════════════
_AERO_SYSTEM = """你是资深气动试验分析工程师。给你的是**已经算好的**曲线特征量，
请写一段中文气动规律结论。

硬性要求：
1. 只能使用给定的数字。**不得自己编造、推算或“大约估计”任何新数值。**
2. 先说规律（线性段、斜率量级、单调性、非线性起始位置），再说物理解释，
   最后指出需要复核的地方。
3. 若某系数 R² 很低且量值本身很小（例如 1e-4 量级），要明确指出这属于零位噪声量级，
   不应过度解读——这是最常见的误读。
4. 300~450 字，分 2~3 段，不要用 Markdown 标题，不要罗列公式。
5. 不确定的地方就说不确定，不要为了流畅而下断言。"""


async def aero_conclusion(
    *,
    llm: LLMClient,
    stats: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not llm.is_configured:
        return {"ok": False, "error": "未配置大模型 API Key，未生成气动规律结论。"}
    if not stats:
        return {"ok": False, "error": "没有可用的曲线统计量。"}
    payload = {"来流与模型": meta or {}, "曲线特征量": stats}
    try:
        text = await llm.chat(
            [{"role": "system", "content": _AERO_SYSTEM},
             {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
            temperature=0.3, max_tokens=1200,
        )
    except LLMError as e:
        return {"ok": False, "error": f"大模型调用失败：{e}"}
    return {"ok": True, "text": text.strip()}


# ══════════════════════════════════════════════════════════════════════════
#  5. narrate a finished check
# ══════════════════════════════════════════════════════════════════════════
_SUMMARY_SYSTEM = """你是风洞试验跟班工程师，正在写本车次的质量小结。
给你的是**已经判定完成**的检查结果清单。

要求：
1. 只使用给定的结论与数值，不得新增判断、不得改变等级、不得编造数值。
2. 提到某一项的等级时，必须原样使用它的 level_label（严重·停止试验 / 警告·需检查 /
   注意·跟踪 / 正常）。**不得把「警告」写成「严重」**——等级是判定结论的一部分，
   写错等级等于改判。
3. 结构：先一句话给总体结论；再按严重→警告→关注的顺序说清每个问题
   （现象、可能原因、要做什么）；最后单独一段说明哪些项没能评定、为什么、怎么补齐。
3. 中文，务实，面向要立刻动手的试验人员，不要客套话，不要重复罗列正常项。
4. 250~400 字。"""


async def explain_findings(
    *,
    llm: LLMClient,
    run_result_dict: Dict[str, Any],
) -> Dict[str, Any]:
    if not llm.is_configured:
        return {"ok": False, "error": "未配置大模型 API Key。"}
    slim = {
        "车次": run_result_dict.get("run_no"),
        "评级": run_result_dict.get("grade"),
        "基本信息": run_result_dict.get("meta", {}),
        "检查结果": [
            {k: f.get(k) for k in
             ("rule_name", "feature_name", "value", "unit", "level_label",
              "verdict", "cause", "impact", "action", "detail", "status")}
            for f in run_result_dict.get("findings", [])
            if f.get("status") != "evaluated" or f.get("level") != "ok"
        ],
        "正常项数": sum(1 for f in run_result_dict.get("findings", [])
                        if f.get("status") == "evaluated" and f.get("level") == "ok"),
    }
    try:
        text = await llm.chat(
            [{"role": "system", "content": _SUMMARY_SYSTEM},
             {"role": "user", "content": json.dumps(slim, ensure_ascii=False, indent=2)}],
            temperature=0.3, max_tokens=1200,
        )
    except LLMError as e:
        return {"ok": False, "error": f"大模型调用失败：{e}"}
    return {"ok": True, "text": text.strip()}


# ══════════════════════════════════════════════════════════════════════════
#  6. free-form Q&A grounded in one run's computed results
# ══════════════════════════════════════════════════════════════════════════
_QA_SYSTEM = """你是风洞试验数据分析助手。只根据给定的本车次计算结果回答问题。
给定材料里没有的信息，明确回答“这份数据里没有这一项”，并说明需要什么数据才能回答。
绝不猜测数值。中文回答，简洁、直接。"""


async def answer_question(
    *,
    llm: LLMClient,
    question: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    if not llm.is_configured:
        return {"ok": False, "error": "未配置大模型 API Key。"}
    try:
        text = await llm.chat(
            [{"role": "system", "content": _QA_SYSTEM},
             {"role": "user", "content":
                 f"本车次计算结果：\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
                 f"问题：{question.strip()}"}],
            temperature=0.2, max_tokens=1500,
        )
    except LLMError as e:
        return {"ok": False, "error": f"大模型调用失败：{e}"}
    return {"ok": True, "text": text.strip()}
