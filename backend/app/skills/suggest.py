"""给技能包工具推荐参数 —— 确定性的,不花 LLM 的钱、不等网络。

出发点是试跑面板上那个真实的坑:工具的默认参数写的是作者数据里的列名(`cycle`、
`discharge_capacity_ah`),而用户手上这份数据的列可能叫 `Cycle Index`、`Cap_Ah`,甚至
根本是另一个领域的数据。让用户自己把列名敲对,是把作者的私有约定摊派给了用户。

所以这里做三件事:
  1. 认出哪些参数其实是"选一列"(名字像 `*_col`、描述里写着列);
  2. 从这份数据真实存在的列里挑一个最像的填进去,并说清为什么这么填;
  3. 挑不出来时**明说这份数据不适合这个工具**,而不是填一个能跑但没意义的值。

第 3 条是重点:宁可空着并说明,也不要静默替换 —— 和 agent 那条"列名诚实"是同一条规矩。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 参数名长这样 → 它要的是一列(或几列)
_COL_NAME_RE = re.compile(r"(^|_)(col|cols|column|columns)$|_col$|_column$|^[xy]$", re.I)
_COL_DESC_RE = re.compile(r"列名|哪一列|某一列|column name|the column|which column", re.I)
# 常见量纲/领域词 → 用于给候选列加分(作者的默认值本身就是最好的线索)
_NUMERIC_HINT = re.compile(r"value|capacity|voltage|current|temp|time|cycle|index|freq|rate|容量|电压|电流|温度|时间|循环",
                           re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]", "", str(s).lower())


def _tokens(s: str) -> List[str]:
    parts = re.split(r"[^a-zA-Z0-9一-鿿]+", str(s).lower())
    return [p for p in parts if p]


def is_column_param(name: str, spec: Dict[str, Any]) -> bool:
    """这个参数是不是在选列。"""
    if _COL_NAME_RE.search(name or ""):
        return True
    desc = str((spec or {}).get("description") or "")
    if _COL_DESC_RE.search(desc):
        return True
    # 默认值本身就是个列名样式的字符串,且类型是 string/array
    t = (spec or {}).get("type")
    return t in ("string", "array") and bool(re.search(r"_(col|column)$", str((spec or {}).get("default") or "")))


def score_column(candidate: str, want: str, *, dtype: str = "") -> float:
    """候选列和"作者想要的那个列名"有多像。0~100。"""
    if not want:
        return 0.0
    c_norm, w_norm = _norm(candidate), _norm(want)
    if not c_norm or not w_norm:
        return 0.0
    if c_norm == w_norm:
        return 100.0
    c_tok, w_tok = set(_tokens(candidate)), set(_tokens(want))
    score = 0.0
    if w_norm in c_norm or c_norm in w_norm:
        score = 85.0                                  # Cycle Index ⊃ cycle
    elif w_tok and c_tok:
        overlap = len(w_tok & c_tok) / len(w_tok)
        score = 70.0 * overlap                        # discharge_capacity_ah ∩ capacity
    # 单位后缀常被作者写进默认值(_ah/_v/_mohm),对不上不该扣太狠
    if score == 0.0:
        stripped = re.sub(r"(ah|_v|mohm|mv|degc|_s|_ms)$", "", w_norm)
        if stripped and (stripped in c_norm or c_norm in stripped):
            score = 60.0
    if score and dtype and _NUMERIC_HINT.search(want) and not str(dtype).startswith(("int", "float")):
        score -= 25.0                                  # 想要数值列,却匹配到文本列
    return max(0.0, score)


MATCH_THRESHOLD = 55.0


def effective_role(name: str, spec: Dict[str, Any]) -> str:
    """这个参数在要哪个"量"。

    作者显式写了 `role` 就用它;没写就拿默认列名当伪 role(`cycle_col` 默认 `cycle`
    → role `cycle`)。有了这个键,用户教过的映射才能跨包复用 —— 否则每个包的私有列名
    约定各说各话,教一百次也攒不出东西。"""
    r = (spec or {}).get("role")
    if r:
        return _norm(str(r))
    default = (spec or {}).get("default")
    base = str(default) if default not in (None, "", [], {}) else re.sub(r"_(col|column)s?$", "", name)
    return _norm(base)


def suggest_params(
    tool: Dict[str, Any],
    columns: Sequence[Dict[str, Any]],
    *,
    dataset_name: str = "",
    role_columns: Optional[Dict[str, List[str]]] = None,
    role_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """按这份数据的真实列,给工具参数一套推荐值。

    columns:      [{"name": ..., "dtype": ...}, ...](数据集 schema_json 里的那份)
    role_columns: {物理量 role: [这份数据里被判定为该 role 的列]} —— 由用户教过的
                  映射规则(MappingRule)算出来。它排在字面匹配**之前**:用户亲口说过
                  「U(V) 是电压」,就不该再让字面相似度去猜。
    """
    role_columns = {_norm(k): list(v) for k, v in (role_columns or {}).items()}
    # 内部用规范化键匹配,给人看的一律用规则里人写的名字(「循环号」而不是 cycleindex)
    role_labels = {_norm(k): str(v) for k, v in (role_labels or {}).items()}
    schema: Dict[str, Any] = tool.get("params_schema") or {}
    col_names = [str(c.get("name")) for c in columns]
    col_dtypes = {str(c.get("name")): str(c.get("dtype") or "") for c in columns}
    numeric_first = sorted(
        col_names,
        key=lambda n: (0 if col_dtypes.get(n, "").startswith(("int", "float")) else 1, col_names.index(n)),
    )

    params: Dict[str, Any] = {}
    options: Dict[str, List[str]] = {}
    used_rules: List[str] = []
    teachable: List[Dict[str, Any]] = []
    explanations: Dict[str, str] = {}
    missing: List[str] = []
    matched_cols = 0
    total_cols = 0

    for name, spec in schema.items():
        spec = spec if isinstance(spec, dict) else {}
        default = spec.get("default")

        if not is_column_param(name, spec):
            if default is not None:
                params[name] = default
                # 空默认值(空串/空数组)挂一句"用默认值"是纯噪音 —— 面板上那一行
                # 什么也没告诉用户,只是把真正重要的提示挤下去。
                if default not in ("", [], {}, None):
                    explanations[name] = f"默认值 {default}。"
            continue

        total_cols += 1
        options[name] = numeric_first
        want = str(default or name)
        role = effective_role(name, spec)
        # 存进规则库、显示给用户的用原样(cycle_index),匹配时才规范化(cycleindex)——
        # 规则是给人看的知识,不该被压成一串没有分隔的字母。
        raw_role = str(spec.get("role") or (default if default not in (None, "", [], {}) else name))

        # 第一层:用户教过的映射规则(跨包、跨数据集复用的那一层)
        taught = [c for c in role_columns.get(role, []) if c in col_names]
        if taught:
            params[name] = [taught[0]] if spec.get("type") == "array" else taught[0]
            matched_cols += 1
            used_rules.append(role)
            shown = role_labels.get(role) or raw_role
            explanations[name] = f"按你(或团队)教过的映射:这份数据的「{taught[0]}」就是{shown}。"
            continue

        ranked: List[Tuple[float, str]] = sorted(
            ((score_column(c, want, dtype=col_dtypes.get(c, "")), c) for c in col_names),
            reverse=True,
        )
        best_score, best_col = ranked[0] if ranked else (0.0, "")

        if best_score >= MATCH_THRESHOLD:
            value = [best_col] if spec.get("type") == "array" else best_col
            params[name] = value
            matched_cols += 1
            if _norm(best_col) == _norm(want):
                explanations[name] = f"这份数据里正好有列「{best_col}」。"
            else:
                explanations[name] = f"这份数据没有「{want}」,最接近的是「{best_col}」——不对就自己换。"
        else:
            missing.append(f"{name}(工具想要类似「{want}」的列)")
            explanations[name] = (
                f"这份数据里找不到像「{want}」的列。真实的列是:"
                + "、".join(col_names[:12]) + ("…" if len(col_names) > 12 else "")
            )
            # 猜不出来不是终点:让用户指一次,把它沉淀成一条映射规则,
            # 以后任何包、任何数据集遇到同名列都自动认(这才是"教一次"的价值)。
            teachable.append({
                "param": name, "role": raw_role, "match_key": role, "wanted": want,
                "label": str(spec.get("description") or want),
            })

    if total_cols == 0:
        fit, note = "good", "这个工具不需要指定列,直接跑就行。"
    elif matched_cols == total_cols:
        fit = "good"
        note = f"已按{f'「{dataset_name}」' if dataset_name else '这份数据'}的真实列名填好,确认一下就能跑。"
    elif matched_cols == 0:
        fit = "mismatch"
        note = ("这份数据看起来**不是这个工具要的数据** —— 一个需要的列都没匹配上。"
                "换一份数据,或确认列名后手动填。")
    else:
        fit = "partial"
        note = f"有 {len(missing)} 个参数没能从这份数据里找到对应的列,需要你手动确认。"

    if used_rules:
        note += f"(其中 {len(used_rules)} 项用了你教过的列映射)"

    return {
        "params": params,
        "options": options,
        "explanations": explanations,
        "missing": missing,
        "fit": fit,
        "note": note,
        "columns": col_names,
        # 没认出来的量:界面据此提供"告诉系统哪一列是它"的入口
        "teachable": teachable,
        "used_rules": used_rules,
    }
