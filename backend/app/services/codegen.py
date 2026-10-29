"""Natural-language → algorithm code generation with auto-test.

The model is forced to emit a self-contained module with a `run(df, **params)`
function, a `META` dict describing the algorithm, and a `test_cases` list of
synthetic inputs we can execute in the sandbox to prove the code runs.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ..sandbox import executor as sandbox_executor
from .llm import LLMClient

CODEGEN_SYSTEM = """You are an expert Python data-engineering author writing safe, focused, single-purpose algorithms for a curated tool library.

OUTPUT FORMAT — STRICTLY a single fenced ```python``` block containing:
1. A top-level `META` dict with keys: name, slug, category, description, params_schema, returns, tags.
   - `slug`  : snake_case identifier, max 60 chars
   - `category` : one of regression | filter | preprocess | structure | reduce | custom
   - `params_schema` : {param_name: {type, default?, required?, description, enum?}}
   - `returns` : 'dataframe' | 'dict' | 'series' | 'scalar'
2. A `run(df, **params)` function. It MUST take a pandas DataFrame `df` as the first argument (may be None for purely generative algorithms) and keyword parameters.
3. A `test_cases` list. Each item is {'df': <DataFrame or None>, 'params': <dict>}. Provide 1–3 synthetic cases the sandbox will execute to prove correctness.

HARD RULES — code that violates these will be rejected:
- Allowed imports ONLY: numpy, pandas, scipy (and submodules), sklearn (and submodules), math, statistics, itertools, functools, operator, collections, typing, dataclasses, enum, copy, re, json, datetime.
- Every third-party module referenced anywhere in the file (top-level META, test_cases, OR inside run()) MUST be imported at the very top of the file. If you use `pd.DataFrame(...)` or `np.array(...)` anywhere — including in `test_cases` — you MUST emit `import pandas as pd` and/or `import numpy as np` at the top. Do not rely on implicit availability.
- NO file I/O, NO network, NO subprocess, NO eval/exec/compile, NO open(), NO __import__.
- NO global side effects outside META / run / test_cases.
- Validate parameters explicitly inside run() and raise ValueError with a clear message on bad input.
- Comments and docstrings are welcome but keep them short and useful.

LIBRARY PREFERENCE — picking lighter libraries makes the sandbox much faster:
- **Prefer numpy / scipy over sklearn whenever they can do the job.** Polynomial fit is `np.polyfit(x, y, deg)`. Linear regression is `np.linalg.lstsq`. Curve fitting is `scipy.optimize.curve_fit`. Stats tests are `scipy.stats`. Use sklearn ONLY when you genuinely need its ML-specific APIs (Pipeline, cross_val_score, GridSearchCV, specific estimators with no direct numpy/scipy equivalent).
- Why: sklearn pulls in joblib / threadpoolctl / huge module trees that take many seconds to cold-import in the sandbox subprocess. numpy + scipy are already pre-warmed.

Reply with nothing outside the fenced code block."""


CODEGEN_REPAIR_TEMPLATE = """Your previous attempt FAILED at stage: {stage}.

Error:
{error}

Your previous code was:
```python
{prev_code}
```

Diagnose the root cause and emit a CORRECTED, self-contained module that obeys every rule in the system message. Common failure modes to check before you reply:
- Forgot `import pandas as pd` / `import numpy as np` at the top — required even if pd/np only appear inside `test_cases`.
- `run(df, **params)` raised on the test input because of wrong column names, type assumptions, or unhandled NaN/empty cases.
- `META` missing required keys, or a `params_schema` field referenced by run() but not declared.
- A test case's `df` schema does not match what `run()` actually reads.

Reply with the FULL corrected module in a single ```python``` fenced block. No prose outside the block."""


# Modules safe to inject into the parse-time namespace. The model SHOULD import
# these explicitly, but we provide them defensively so a trivial NameError in
# top-level `test_cases` doesn't waste a retry slot.
_SAFE_NS_MODULES: Dict[str, Any] = {"pd": pd, "np": np}


# Smoke-test timeout: fresh subprocess + cold-import numpy/pandas/sklearn can
# easily eat the default 30 s on Windows with AV scanning .pyc files. Bump for
# codegen specifically so the LLM doesn't get blamed for OS slowness.
_SMOKE_TEST_TIMEOUT_SECONDS = 90


# --- Diagnostic hints ----------------------------------------------------------
#
# Every entry maps a regex (matched against the full sandbox error string) to a
# human-readable explanation and a `fatal` flag.
#
#   fatal=True  -> the LLM CANNOT fix this by rewriting code; we short-circuit
#                  the retry loop and surface the hint instead of burning more
#                  LLM calls. Examples: sandbox timeout, AST validator rejecting
#                  a forbidden import, OOM kill.
#
#   fatal=False -> the LLM has a reasonable chance to self-correct on retry,
#                  but we still attach the hint to the attempt_log so the
#                  frontend can show "we noticed X; the model is trying again".
#
# Order matters — the FIRST matching rule wins. Put more-specific patterns above
# generic ones.
_HINT_RULES: List[Dict[str, Any]] = [
    {
        "pattern": r"NameError: name 'pd' is not defined",
        "cause":   "代码顶部缺少 `import pandas as pd`（即使 pd 只出现在 test_cases 里也必须 import）。",
        "fatal":   False,
    },
    {
        "pattern": r"NameError: name 'np' is not defined",
        "cause":   "代码顶部缺少 `import numpy as np`。",
        "fatal":   False,
    },
    {
        "pattern": r"NameError: name '([A-Za-z_][A-Za-z0-9_]*)' is not defined",
        "cause":   "代码引用了未定义的名字 '{0}'。可能是变量名拼写错误，或顶部 import 缺失。",
        "fatal":   False,
    },
    {
        "pattern": r"function\(\) argument 'code' must be code, not str",
        "cause":   "（已修复的老 bug）sandbox 的网络拦截破坏了 ssl 继承链。如果还看到这条，说明你跑的是旧版后端 —— 重启 uvicorn。",
        "fatal":   True,
    },
    {
        "pattern": r"^validation failed:.*import not allowed: ([\w.]+)",
        "cause":   "AST 静态检查拒绝了 import '{0}'。沙箱只允许 numpy / pandas / scipy / sklearn 子模块 / math / statistics / itertools / functools / collections / typing / dataclasses / enum / copy / re / json / datetime。",
        "fatal":   True,
    },
    {
        "pattern": r"^validation failed:.*use of '([\w_]+)' is not allowed",
        "cause":   "AST 静态检查拒绝使用 '{0}'。沙箱禁用了 eval / exec / compile / __import__ / open / globals / locals / vars / input。",
        "fatal":   True,
    },
    {
        "pattern": r"^validation failed:",
        "cause":   "AST 静态检查未通过 —— 代码触犯了沙箱的硬规则。LLM 重试也救不回来，需要换思路。",
        "fatal":   True,
    },
    {
        "pattern": r"^timeout after \d+s",
        "cause":   "代码或其依赖在沙箱里执行/加载超时。常见原因：(1) 在 Windows 上首次冷启 sklearn/scipy 时 AV 扫描 .pyc 拖慢导入；(2) run() 里有死循环 / 极慢的算法。如果是 (1)，重跑一次通常就好；如果是 (2)，LLM 重写也不一定救得回来。",
        "fatal":   True,
    },
    {
        "pattern": r"^memory limit exceeded",
        "cause":   "代码超出沙箱内存上限。可能是创建了过大的中间数组，或没有分块/迭代处理大 DataFrame。",
        "fatal":   True,
    },
    {
        "pattern": r"KeyError: '([^']+)'",
        "cause":   "代码引用了不存在的字典/列名 '{0}'。检查列名拼写、大小写、以及 params_schema 是否声明完整。",
        "fatal":   False,
    },
    {
        "pattern": r"ModuleNotFoundError: No module named '([\w.]+)'",
        "cause":   "找不到模块 '{0}'。如果它是 numpy/pandas/scipy/sklearn 的子模块，检查路径拼写；否则不在沙箱白名单里。",
        "fatal":   False,  # might be a typo the LLM can fix
    },
    {
        "pattern": r"TypeError:.*missing \d+ required positional argument",
        "cause":   "run() 签名与 params_schema 声明的参数不匹配。检查必填参数是否齐全。",
        "fatal":   False,
    },
    {
        "pattern": r"AttributeError: 'NoneType' object has no attribute",
        "cause":   "run(df, ...) 收到了 None 但代码没有先判空。在函数开头加 `if df is None: raise ValueError(...)`。",
        "fatal":   False,
    },
]


def diagnose(error: str) -> List[Dict[str, Any]]:
    """Return a list of {cause, fatal} hints describing likely root causes of
    a sandbox/codegen error string. Empty list if no rule matches — that means
    the error is novel or generic and the caller should surface it verbatim."""
    if not error:
        return []
    hints: List[Dict[str, Any]] = []
    for rule in _HINT_RULES:
        m = re.search(rule["pattern"], error, flags=re.MULTILINE)
        if m:
            try:
                cause = rule["cause"].format(*m.groups())
            except (IndexError, KeyError):
                cause = rule["cause"]
            hints.append({"cause": cause, "fatal": bool(rule["fatal"])})
            # First match wins — don't double-up with generic fallbacks below.
            break
    return hints


def _is_fatal(error: str) -> bool:
    return any(h["fatal"] for h in diagnose(error))


_CODE_RE = re.compile(r"```python\s*(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    m = _CODE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def parse_meta(code: str) -> Dict[str, Any]:
    """Read META statically (ast.literal_eval) — user / AI code is never exec'd in
    the server process; only the sandbox runs it."""
    from .algo_store import static_meta

    return static_meta(code)


def _extract_test_cases_serialized(code: str) -> List[Dict[str, Any]]:
    """Pull out test_cases by evaluating the module and serialising the test data."""
    ns: Dict[str, Any] = dict(_SAFE_NS_MODULES)
    try:
        exec(compile(code, "<test-extract>", "exec"), ns, ns)
    except Exception:
        return []
    raw = ns.get("test_cases") or []
    cases: List[Dict[str, Any]] = []
    for c in raw[:3]:
        df = c.get("df") if isinstance(c, dict) else None
        params = c.get("params", {}) if isinstance(c, dict) else {}
        cases.append({
            "df": df if isinstance(df, pd.DataFrame) else None,
            "params": params or {},
        })
    return cases


def _short_reason(error: str) -> str:
    """The last line of an error / traceback, trimmed — enough for a status chip."""
    lines = [ln.strip() for ln in (error or "").strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "")[:160]


def _build_repair_messages(
    user_msg: str,
    prev_code: str,
    stage: str,
    error: str,
) -> List[Dict[str, str]]:
    """Construct a follow-up prompt that hands the failing code + error back to
    the model so it can self-correct. We keep the original task in `user` and
    inject the repair instruction in a second `user` turn — this matches how
    DeepSeek/OpenAI chat models handle iterative correction better than
    stuffing it all into one message."""
    return [
        {"role": "system", "content": CODEGEN_SYSTEM},
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": f"```python\n{prev_code}\n```"},
        {
            "role": "user",
            "content": CODEGEN_REPAIR_TEMPLATE.format(
                stage=stage, error=error[:2000], prev_code=prev_code,
            ),
        },
    ]


def _smoke_test(code: str) -> tuple[List[Dict[str, Any]], bool, Optional[str]]:
    """Run the code's `test_cases` (or a fallback) through the sandbox.

    Returns (reports, all_passed, first_error). Each report now carries a
    `hints` list — see `diagnose()` — so the caller (and ultimately the
    frontend) can show the user what likely went wrong without making them
    parse a raw Python traceback."""
    cases = _extract_test_cases_serialized(code)
    if not cases:
        df_fallback = pd.DataFrame(
            {"x": [1.0, 2.0, 3.0, 4.0, 5.0], "y": [2.1, 3.9, 6.2, 8.1, 9.8]}
        )
        cases = [{"df": df_fallback, "params": {}}]

    reports: List[Dict[str, Any]] = []
    all_ok = True
    first_err: Optional[str] = None
    for i, c in enumerate(cases):
        result = sandbox_executor.execute(
            code, c["params"], input_df=c["df"], save_result=False,
            timeout_seconds=_SMOKE_TEST_TIMEOUT_SECONDS,
        )
        hints = diagnose(result.error) if result.status != "ok" else []
        reports.append({
            "case": i + 1,
            "status": result.status,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "summary": result.summary,
            "hints": hints,
        })
        if result.status != "ok":
            all_ok = False
            if first_err is None:
                first_err = result.error or "test case failed without an error message"
    return reports, all_ok, first_err


async def generate_algorithm(
    prompt: str,
    *,
    llm: LLMClient,
    schema_hint: Optional[str] = None,
    max_attempts: int = 3,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Ask the model for code, parse META, run sandboxed tests, return a bundle.

    Self-healing: if META parsing fails OR any sandbox test fails, we feed the
    error + previous code back to the model and let it correct itself, up to
    `max_attempts` total attempts. This is the system's autonomy contract — the
    user should not have to look at codegen internals when the LLM makes a
    one-off mistake (forgotten import, bad column name, etc.).
    """
    user_msg = prompt.strip()
    if schema_hint:
        user_msg = f"Schema of the user's current dataset:\n{schema_hint}\n\nTask:\n{user_msg}"

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": CODEGEN_SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    attempt_log: List[Dict[str, Any]] = []
    code: str = ""
    meta: Dict[str, Any] = {}
    test_reports: List[Dict[str, Any]] = []
    last_error: Optional[str] = None
    last_stage: str = ""

    def progress(stage: str, **kw: Any) -> None:
        # Stage events for the chat UI (写代码 → 沙箱自测 → 自动修复 → 完成).
        if on_progress is not None:
            try:
                on_progress({"stage": stage, "max_attempts": max_attempts, **kw})
            except Exception:  # noqa: BLE001 — progress must never break codegen
                pass

    for attempt in range(1, max_attempts + 1):
        progress("write", attempt=attempt)
        text = await llm.chat(messages, temperature=0.2, max_tokens=4000)
        code = extract_code(text)

        # Stage 1: META + run() must be parseable.
        try:
            meta = parse_meta(code)
        except Exception as e:
            last_error = str(e)
            last_stage = "parse_meta"
            hints = diagnose(last_error)
            attempt_log.append({
                "attempt": attempt,
                "stage":   last_stage,
                "error":   last_error,
                "hints":   hints,
            })
            # If parse failure is fatal (e.g. SyntaxError from a violated hard
            # rule), don't burn LLM calls trying to fix the unfixable.
            if any(h["fatal"] for h in hints):
                break
            if attempt < max_attempts:
                progress("repair", attempt=attempt, reason=_short_reason(last_error))
                messages = _build_repair_messages(user_msg, code, last_stage, last_error)
            continue

        # Stage 2: sandboxed smoke test of every test_case. The sandbox runs a
        # blocking subprocess — off the event loop, so the server stays
        # responsive and progress events actually reach the client meanwhile.
        progress("test", attempt=attempt, name=str(meta.get("name") or ""))
        test_reports, all_ok, first_err = await asyncio.to_thread(_smoke_test, code)
        attempt_log.append({
            "attempt": attempt,
            "stage":   "smoke_test",
            "passed":  all_ok,
            "reports": test_reports,
        })
        if all_ok:
            progress("done", attempt=attempt, passed=True,
                     tests=len(test_reports), name=str(meta.get("name") or ""))
            return {
                "code": code,
                "meta": meta,
                "tests": test_reports,
                "all_tests_passed": True,
                "attempts": attempt,
                "attempt_log": attempt_log,
            }

        last_error = first_err or "one or more test cases failed"
        last_stage = "smoke_test"

        # Short-circuit: if the error is sandbox infrastructure (timeout,
        # validation reject, OOM, etc.), the LLM rewriting code won't help.
        # Surfacing the hints once is far more useful than 2 more failed
        # attempts that say the same thing.
        if _is_fatal(last_error):
            break

        if attempt < max_attempts:
            progress("repair", attempt=attempt, reason=_short_reason(last_error))
            messages = _build_repair_messages(user_msg, code, last_stage, last_error)

    progress("done", attempt=len(attempt_log) or max_attempts, passed=False,
             reason=_short_reason(last_error or ""))
    # Exhausted retries (or short-circuited on a fatal infra error) — return
    # the last attempt so the caller can show the code, the failing report,
    # and the diagnostic hints to the user. all_tests_passed=False signals
    # this is unverified.
    final_hints = diagnose(last_error or "")
    return {
        "code": code,
        "meta": meta,
        "tests": test_reports,
        "all_tests_passed": False,
        "attempts": len(attempt_log) or max_attempts,
        "attempt_log": attempt_log,
        "final_error": last_error,
        "final_stage": last_stage,
        "final_hints": final_hints,
    }
