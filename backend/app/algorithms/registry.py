"""Unified algorithm registry.

Built-in algorithms are trusted in-process Python callables exposed via a
common signature `fn(df, **params) -> result`. User-uploaded and AI-generated
algorithms are stored as source strings and executed inside the sandbox.

The registry is the single source of truth the chat agent and the REST API
talk to when they need to discover or invoke a tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from ..sandbox import executor as sandbox_executor


@dataclass
class AlgorithmSpec:
    slug: str
    name: str
    category: str
    description: str
    params_schema: Dict[str, Any]  # {name: {type, default, required, description, enum?}}
    returns: str = "dataframe"  # dataframe | series | dict | scalar | artifact
    tags: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)  # alt names the LLM may guess


@dataclass
class _Builtin:
    spec: AlgorithmSpec
    fn: Callable[..., Any]


_BUILTINS: Dict[str, _Builtin] = {}
# Alias → canonical slug. The chat LLM sometimes emits a near-miss name
# (e.g. "peak_detector" for find_peaks, "kmeans_clustering" for kmeans_cluster);
# resolving aliases makes that self-healing instead of a "tool not found".
_ALIASES: Dict[str, str] = {}


def _resolve(slug: str) -> str:
    return _ALIASES.get(slug, slug)


def register_builtin(spec: AlgorithmSpec, fn: Callable[..., Any]) -> None:
    if spec.slug in _BUILTINS:
        raise RuntimeError(f"duplicate algorithm slug: {spec.slug}")
    _BUILTINS[spec.slug] = _Builtin(spec=spec, fn=fn)
    for a in spec.aliases:
        _ALIASES.setdefault(a, spec.slug)


def list_builtins(category: Optional[str] = None) -> List[AlgorithmSpec]:
    out = [b.spec for b in _BUILTINS.values()]
    if category:
        out = [s for s in out if s.category == category]
    return sorted(out, key=lambda s: (s.category, s.name))


def get_builtin(slug: str) -> Optional[AlgorithmSpec]:
    b = _BUILTINS.get(slug) or _BUILTINS.get(_resolve(slug))
    return b.spec if b else None


def all_categories() -> List[str]:
    return sorted({b.spec.category for b in _BUILTINS.values()})


def _humanize_error(exc: Exception, df: Optional[pd.DataFrame]) -> Optional[str]:
    """Translate the most common raw exceptions into a plain-language Chinese
    message that BOTH the user and the agent (on retry) can act on.

    The key win is naming the *real* cause (e.g. "these columns don't exist")
    and listing the columns that actually ARE in the data — far more useful
    than a pandas `KeyError: None of [Index([...])]` traceback or an unrelated
    enum hint. Returns None when no friendly translation applies, so the caller
    falls back to the raw message.
    """
    import re

    name = type(exc).__name__
    raw = str(exc)
    cols = [str(c) for c in df.columns] if df is not None else []
    colset = set(cols)
    col_preview = "、".join(cols[:30]) + ("…" if len(cols) > 30 else "") if cols else "（这份数据没有任何列）"

    # 1) df[[...]] with columns that don't exist → pandas "None of [Index([...])]"
    m = re.search(r"None of \[Index\(\[(.*?)\]", raw)
    if m:
        wanted = [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
        missing = [w for w in wanted if w not in colset] or wanted
        return (
            f"用到的列「{'、'.join(missing)}」在这份数据里不存在。"
            f"这份数据真正有的列是：{col_preview}。请改用真实存在的列名再试。"
        )

    # 2) single-column lookup miss → KeyError: 'colname'
    if name == "KeyError":
        bad = raw.strip().strip("'\"")
        if bad and bad not in colset:
            return (
                f"列「{bad}」在这份数据里不存在。"
                f"这份数据真正有的列是：{col_preview}。"
            )

    # 3) trying to do math on a text column
    if "could not convert string to float" in raw or "invalid literal for" in raw \
            or ("must be a string or a number" in raw):
        return (
            "有一列是文本(非数值),没法做数值计算。"
            f"这份数据的列是：{col_preview}。请只选数值列。"
        )

    # 4) empty input after filtering
    if name in ("ValueError",) and ("empty" in raw.lower() or "0 sample" in raw or "n_samples=0" in raw):
        return "处理后没有可用数据(可能被某一步过滤光了),请放宽条件或换一份数据再试。"

    return None


def coerce_params(schema: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce LLM-supplied params to the types the function actually expects.

    The LLM emits JSON by hand and routinely gets the *container* wrong even
    when the value is right: `columns: "signal"` instead of `columns:
    ["signal"]`. That single-string slipped straight through to
    `for c in columns`, which iterates a str CHARACTER-BY-CHARACTER — so the
    tool reported `column not found: s` (the first letter of "signal"), the
    agent had no way to read that as "wrap it in a list", and it burned its
    3-strike budget re-emitting the same shape.

    Coercing here (rather than in each of the ~19 array-typed builtins) keeps
    every caller — chat agent, REST run endpoints, template replay — healed by
    one rule, per the "defensive layers, not per-symptom patches" principle.
    """
    schema = schema or {}
    out: Dict[str, Any] = {}
    for k, v in (params or {}).items():
        t = (schema.get(k) or {}).get("type") if isinstance(schema.get(k), dict) else None
        if v is None or t is None:
            out[k] = v
            continue
        try:
            if t == "object" and isinstance(v, dict) and \
                    (schema.get(k) or {}).get("values") == "array":
                # `{col: "mean"}` → `{col: ["mean"]}`. Same container slip as
                # below, one level down: group_aggregate's `agg` maps a column
                # to a LIST of function names, and iterating the bare string
                # yielded 'm' → "agg func 'm' not allowed".
                out[k] = {
                    kk: ([p.strip() for p in vv.split(",") if p.strip()] if "," in vv else [vv])
                    if isinstance(vv, str) else (list(vv) if isinstance(vv, (list, tuple)) else [vv])
                    for kk, vv in v.items()
                }
            elif t == "array" and not isinstance(v, (list, tuple)):
                # "signal" → ["signal"];  "a, b" → ["a", "b"] (the LLM's other
                # favourite shorthand). Scalars just get wrapped.
                if isinstance(v, str):
                    out[k] = [p.strip() for p in v.split(",") if p.strip()] if "," in v else [v]
                else:
                    out[k] = [v]
            elif t == "array":
                out[k] = list(v)
            elif t == "integer" and isinstance(v, str):
                out[k] = int(float(v.strip()))
            elif t == "number" and isinstance(v, str):
                out[k] = float(v.strip())
            elif t == "boolean" and isinstance(v, str):
                out[k] = v.strip().lower() in ("true", "1", "yes", "y", "是")
            else:
                out[k] = v
        except (TypeError, ValueError):
            out[k] = v  # leave it alone; the tool's own error is more informative
    return out


def _coerce_params(spec: AlgorithmSpec, params: Dict[str, Any]) -> Dict[str, Any]:
    return coerce_params(spec.params_schema or {}, params)


def execute_builtin(
    slug: str,
    df: Optional[pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a trusted built-in algorithm in-process.

    Returns a result dict shaped like the sandbox result so the chat agent
    doesn't need to branch on source.
    """
    import json
    import time
    import traceback

    from ..sandbox.runner_worker import _summarize  # reuse the summarizer

    slug = _resolve(slug)  # LLM may emit a near-miss alias; map it to the real slug
    if slug not in _BUILTINS:
        return {
            "status": "error",
            "error": f"unknown algorithm: {slug}",
            "duration_ms": 0,
            "summary": {},
            "logs": "",
            "result_path": None,
            "result_rows": 0,
        }
    fn = _BUILTINS[slug].fn
    # Tolerate extra / hallucinated kwargs from the LLM: drop any param the
    # function doesn't declare, so a stray argument is IGNORED rather than raising
    # TypeError — which used to send the agent into a repair spiral (generate_tool
    # + flailing retries) instead of just running the tool.
    import inspect
    try:
        _sig = inspect.signature(fn)
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _sig.parameters.values()):
            _allowed = {n for n, p in _sig.parameters.items()
                        if p.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)}
            params = {k: v for k, v in (params or {}).items() if k in _allowed}
    except (ValueError, TypeError):
        pass
    # Right shape, wrong container: fix `columns: "signal"` → `["signal"]` etc.
    params = _coerce_params(_BUILTINS[slug].spec, params)
    started = time.perf_counter()
    try:
        result = fn(df, **(params or {}))
        summary = _summarize(result)
        result_rows = int(len(result)) if isinstance(result, pd.DataFrame) else 0

        result_path: Optional[str] = None
        if isinstance(result, pd.DataFrame):
            from ..core.config import get_settings

            settings = get_settings()
            out_dir = settings.upload_path / "results"
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = f"builtin_{slug}_{int(time.time() * 1000)}.parquet"
            out_path = out_dir / fname
            result.to_parquet(out_path, index=False)
            result_path = str(out_path)

        return {
            "status": "ok",
            "error": "",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "summary": summary,
            "logs": "",
            "result_path": result_path,
            "result_rows": result_rows,
        }
    except Exception as e:
        # Prefer a plain-language explanation of the real cause (e.g. "these
        # columns don't exist; the data actually has a/b/c"). Both the user and
        # the agent-on-retry can act on that. Only when no friendly translation
        # applies do we fall back to the raw error + the tool's valid enum values
        # (so the agent can self-correct a bad `method`, etc.).
        human = _humanize_error(e, df)
        if human:
            msg = human
        else:
            msg = f"{type(e).__name__}: {e}"
            try:
                spec = _BUILTINS[slug].spec
                enum_hints = [
                    f"{n}∈{{{'|'.join(str(v) for v in ps['enum'])}}}"
                    for n, ps in (spec.params_schema or {}).items()
                    if isinstance(ps, dict) and ps.get("enum")
                ]
                if enum_hints:
                    msg += f"  (valid: {', '.join(enum_hints)})"
            except Exception:
                pass
        return {
            "status": "error",
            "error": msg,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "summary": {},
            "logs": traceback.format_exc()[:8000],
            "result_path": None,
            "result_rows": 0,
        }


def execute_code(
    code: str,
    df: Optional[pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run untrusted user/AI code in the sandbox."""
    result = sandbox_executor.execute(code, params, input_df=df, save_result=True)
    return result.to_dict()
