"""Plain-language checks for algorithm code — both static, neither executes it.

  admission_check(code)  — "can this .py join the platform?" as a checklist the
                           studio shows right after an upload (what's missing,
                           on which line), before any debug run.
  diagnose_run(...)      — turn a failed debug run into ONE category the user
                           can act on: 参数 / 数据 / 代码 / 规范 / 超时, with the
                           likely cause and the next step.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Optional

from ..sandbox.validator import validate_algorithm_code
from .algo_store import static_meta


def _item(key: str, label: str, ok: bool, detail: str = "", level: str = "required") -> Dict[str, Any]:
    return {"key": key, "label": label, "ok": ok, "detail": detail, "level": level}


def admission_check(code: str) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        items.append(_item("syntax", "Python 语法正确", False, f"第 {e.lineno} 行：{e.msg}"))
        return {"ok": False, "items": items}
    items.append(_item("syntax", "Python 语法正确", True))

    v = validate_algorithm_code(code)
    run_fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"), None)
    other_fns = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    items.append(_item(
        "entry", "有入口函数 run(df, **params)", run_fn is not None,
        "" if run_fn else ("没有名为 run 的顶级函数" + (f"（现有函数：{', '.join(other_fns[:5])}）" if other_fns else "")),
    ))

    meta: Dict[str, Any] = {}
    try:
        meta = static_meta(code)
        items.append(_item("meta", "有 META 说明（名称、标识、分类、描述）", True, f"「{meta.get('name')}」 · {meta.get('slug')}"))
    except ValueError as e:
        msg = str(e)
        zh = ("没有顶级的 META 字典" if "missing a top-level META" in msg
              else "META 必须直接写成字典（不能用变量或函数调用）" if "literal dict" in msg
              else f"META 缺少「{msg.split('.')[-1].split()[0]}」字段" if msg.startswith("META.")
              else "没有 run 函数，读不到完整的 META" if "missing a `run`" in msg else msg)
        items.append(_item("meta", "有 META 说明（名称、标识、分类、描述）", False, zh))

    imports = [e for e in v.errors if e.startswith("import not allowed") or e.startswith("relative imports")]
    items.append(_item(
        "imports", "只用平台允许的库（numpy / pandas / scipy / sklearn / 标准库）", not imports,
        "；".join(_zh(e) for e in imports[:6]),
    ))
    unsafe = [e for e in v.errors if "is not allowed" in e and not e.startswith("import") or e.startswith("access to")]
    items.append(_item("safety", "没有禁止的写法（eval / exec / open / 访问内部属性）", not unsafe,
                       "；".join(_zh(e) for e in unsafe[:6])))

    # Every run() parameter should be declared, or the run-settings form can't offer it.
    if run_fn is not None and meta:
        declared = set((meta.get("params_schema") or {}).keys())
        args = [a.arg for a in run_fn.args.args[1:] + run_fn.args.kwonlyargs]
        undeclared = [a for a in args if a not in declared]
        items.append(_item("params", "run 的参数都在 META.params_schema 里声明", not undeclared,
                           f"未声明：{', '.join(undeclared)}" if undeclared else "", level="recommended"))

    has_tests = any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "test_cases" for t in n.targets)
                    for n in tree.body)
    items.append(_item("tests", "带自测用例 test_cases", has_tests, "" if has_tests else "没有也能接入，但有了可以自动验证", level="optional"))
    return {"ok": all(i["ok"] for i in items if i["level"] == "required"), "items": items}


def _zh(e: str) -> str:
    m = re.match(r"import not allowed: (\S+) \(line (\d+)\)", e)
    if m:
        return f"第 {m.group(2)} 行 import {m.group(1)}（平台沙箱不允许）"
    m = re.match(r"use of '(\w+)' is not allowed \(line (\d+)\)", e)
    if m:
        return f"第 {m.group(2)} 行使用了 {m.group(1)}"
    m = re.match(r"access to '(\w+)' is not allowed \(line (\d+)\)", e)
    if m:
        return f"第 {m.group(2)} 行访问了 {m.group(1)}"
    return e


# ── failed debug run → one actionable category ──────────────────────────────

def _code_line(error: str) -> int:
    frames = re.findall(r'File "<algorithm>", line (\d+)', error or "")
    return int(frames[-1]) if frames else 0


def diagnose_run(
    error: str, *, code: str, params: Dict[str, Any], columns: Optional[List[str]], has_df: bool,
) -> Dict[str, Any]:
    """{category, title, detail, action, line}. category ∈ param | data | code | rule | timeout."""
    err = (error or "").strip()
    last = (err.splitlines() or [""])[-1].strip()
    line = _code_line(err)
    src = ""
    if line:
        lines = code.splitlines()
        src = lines[line - 1].strip() if 0 < line <= len(lines) else ""
    at = f"（代码第 {line} 行：{src[:80]}）" if line else ""
    cols = columns or []

    if err.startswith("validation failed"):
        return {"category": "rule", "title": "不符合平台规范，还没开始运行",
                "detail": err.replace("validation failed: ", ""), "action": "让 AI 按平台规范修正", "line": 0}
    if err.startswith("timeout"):
        return {"category": "timeout", "title": "运行超时",
                "detail": "代码在限定时间内没有跑完，常见原因是逐行循环处理大数据或死循环。",
                "action": "让 AI 改成向量化写法，或换一份小一些的数据试", "line": line}

    # Parameters: wrong keyword, missing argument, or the code's own check names a param.
    m = re.search(r"got an unexpected keyword argument '(\w+)'", err)
    if m:
        return {"category": "param", "title": f"参数问题：run 不接受参数 {m.group(1)}",
                "detail": f"传入了 run 没有声明的参数 {m.group(1)}。", "action": "在「运行设置」里去掉它，或让 AI 给 run 加上这个参数", "line": line}
    m = re.search(r"missing \d+ required (?:positional|keyword-only) arguments?: (.+)$", last)
    if m:
        return {"category": "param", "title": f"参数问题：缺少 {m.group(1)}",
                "detail": f"run 需要参数 {m.group(1)}，但这次没有传。", "action": "在「运行设置」里填上它", "line": line}
    named = [k for k in params if re.search(rf"\b{re.escape(k)}\b", last)]
    if named and re.match(r"(ValueError|TypeError)", last):
        k = named[0]
        return {"category": "param", "title": f"参数问题：{k} 的值不对",
                "detail": f"算法检查参数时报错：{last.split(':', 1)[-1].strip()}（这次传的是 {k} = {params[k]!r}）。",
                "action": f"在「运行设置」里修改 {k}", "line": line}

    # Data: no dataset, missing column, non-numeric values, empty table. Without a
    # dataset almost every failure is just that (whatever wording the code's own
    # guard uses), so it's checked before any message matching.
    if not has_df:
        return {"category": "data", "title": "数据问题：没有选择数据集",
                "detail": f"这次调试运行没有选数据集，算法收到的 df 是空的（None）。算法报错：{last}",
                "action": "在「运行设置」里选一个数据集", "line": line}
    m = re.search(r"KeyError: ['\"]([^'\"]+)['\"]", last) or re.search(r"(?:列|column)\s*['\"]?([\w.\-]+)['\"]?\s*(?:不存在|not found|not in)", last)
    if m:
        c = m.group(1)
        if cols and c not in cols:
            return {"category": "data", "title": f"数据问题：数据集里没有列「{c}」",
                    "detail": f"代码要读取列 {c}，但当前数据集的列是：{', '.join(cols[:20])}。{at}",
                    "action": "在「运行设置」里把对应参数改成真实的列名，或换一个数据集", "line": line}
    if re.search(r"could not convert string to float|invalid literal for int|Unable to parse string|unsupported operand type", last):
        return {"category": "data", "title": "数据问题：列里有不是数字的值",
                "detail": f"计算时遇到了文本或缺失值：{last}{at}", "action": "先用「数据清洗」处理这列，或让 AI 在代码里跳过非数字值", "line": line}
    if re.search(r"empty|zero-size|at least \d+ (?:rows|samples)|n_samples=0", last, re.I):
        return {"category": "data", "title": "数据问题：可用的数据太少或为空",
                "detail": f"{last}{at}", "action": "检查筛选条件和缺失值，或换一份数据", "line": line}

    # Everything else is the code itself.
    kind = last.split(":", 1)[0] if ":" in last else last
    explain = {
        "NameError": "用到了没有定义的变量或函数",
        "AttributeError": "对象上没有这个属性或方法（常见于把 Series 当成 DataFrame 用，或 pandas 版本差异）",
        "IndexError": "下标越界", "ZeroDivisionError": "除以零", "TypeError": "类型不匹配",
        "ValueError": "值不合法", "KeyError": "字典 / 列名里没有这个键",
    }.get(kind, "代码运行出错")
    return {"category": "code", "title": f"代码问题：{explain}",
            "detail": f"{last}{at}", "action": "让 AI 修这个错误，或直接改右侧代码", "line": line}
