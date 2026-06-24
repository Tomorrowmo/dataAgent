"""Chat agent: orchestrates the LLM, the algorithm registry, and code-gen.

Single-step JSON-action protocol — simpler than tool-call schemas and works
with any OpenAI-compatible endpoint, including DeepSeek.

Each turn the LLM returns:
  { "thought": "...", "action": "...", "args": {...} }

Actions:
  - "answer"          : final answer to the user (args.text)
  - "list_tools"      : list available tools (filter by args.category?)
  - "describe_tool"   : args.slug -> the params schema
  - "run_tool"        : args.slug, args.params -> execute against current dataset
  - "generate_tool"   : args.description -> LLM writes + tests a new algorithm
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..algorithms import registry
from ..db.models import Algorithm, Dataset, Message
from ..sandbox import executor as sandbox_executor
from .codegen import generate_algorithm, parse_meta
from .datasets import _persist_dataset, load_dataset_df
from .llm import LLMClient

SYSTEM_PROMPT = """You are RLab Cortex, a verifiable data-analysis agent for engineers and scientists. You help users explore, clean, and analyze tabular / time-series data by invoking curated algorithms (preferred) or, when no suitable one exists, generating a new one for the user to approve.

You ALWAYS respond with a single JSON object — nothing outside it. Schema:
{
  "thought": "<one sentence reasoning>",
  "action": "answer | list_tools | describe_tool | run_tool | generate_tool | visualize | visualize_batch | generate_viz",
  "args": { ... }
}

Action contracts:
- answer         : args = { "text": "<markdown answer to the user>" }
- list_tools     : args = { "category": "<optional filter>" }
- describe_tool  : args = { "slug": "<algorithm slug>" }
- run_tool       : args = { "slug": "<algorithm slug>", "params": { ... }, "dataset": "<dataset name, optional — defaults to PRIMARY>" }
- generate_tool  : args = { "description": "<plain-language spec for a new algorithm>" }
- visualize      : args = { "chart_type": "line | scatter | bar", "x": "<column>", "y": ["<column>", ...], "title": "<short title>", "dataset": "<name, optional — defaults to PRIMARY>", "datasets": ["<name>", "<name>"] (optional — overlay the SAME column(s) from 2+ datasets on ONE chart for comparison) }
- visualize_batch: args = { "chart_type": "line|scatter|bar", "x": "<column>", "y": ["<column>", ...], "per": "dataset | column", "datasets": ["<name>", ...] (optional — defaults to ALL loaded), "title": "<prefix>" }
- generate_viz   : args = { "description": "<precise spec of the chart to build>", "dataset": "<name, optional — defaults to PRIMARY>" }

Guidance:
- Prefer existing tools. Only call `generate_tool` when nothing in the registry fits.
- The "Available tools" list below is EXHAUSTIVE — those are the ONLY tools that exist. NEVER name, describe, recommend, or ask for the parameters of a tool whose slug is NOT in that list (do not invent slugs like `fft_frequency_analysis`, `low_pass_filter`, etc.). If the user wants a capability that isn't in the list, say plainly it's not yet in the library and OFFER to build it — or call `generate_tool` to create it — rather than pretending it exists. When you list "available" algorithms, list ONLY real slugs from below.
- For ANY plotting / charting request (画图, 画曲线, 可视化, "plot", "chart", "show me ... vs ..."), use `visualize`. Pick sensible default columns from the schema (e.g. a time/index column for x). The user gets an INTERACTIVE chart and can change axes, series, and chart type themselves afterwards — so just pick a good starting view; do NOT ask them which columns unless the dataset has no obvious choice. After the chart result, give a one-line `answer` pointing out what to look at.
- To COMPARE / OVERLAY multiple loaded datasets on one chart (对比, 叠加, "A vs B"), call `visualize` with `datasets`: [the names] and the shared column(s) in `y` — the tool aligns them and draws one series per dataset.
- BATCH plotting — when the user wants SEVERAL SEPARATE charts at once (批量出图, 分别出图, 每个文件/每个参数各一张图, "one chart per file/column", "plot all of them separately"), use `visualize_batch` — ONE call produces ALL the charts. Set `per: "dataset"` for one chart per dataset (defaults to every loaded dataset; pass `datasets` to limit), or `per: "column"` for one chart per y-column of a single dataset. NEVER loop `visualize` once per item, and NEVER claim in an `answer` that you produced multiple charts unless you actually called `visualize`/`visualize_batch` THIS turn — emit the action, then interpret its result.
- When `visualize` CAN'T express the chart you need, use `generate_viz` with a precise description — it WRITES the chart on demand and can render ESSENTIALLY ANY chart type: radar / polar, heatmap, contour, 3D surface/scatter, box, violin, histogram, parallel-coordinates, pie, error bars, raw-points-plus-fitted-curve, custom transforms, anything bespoke. So NEVER tell the user a chart type is "unsupported" or that the system "only supports line/scatter/bar" — if `visualize` can't do it, call `generate_viz`. It's slower than `visualize`, so use `visualize` for plain line/scatter/bar and `generate_viz` for everything else.
- When the user uploads or selects a dataset, the schema and head are in the system context. Reference exact column names.
- COLUMN HONESTY: only use column names that actually appear in the selected dataset's schema. If the user asks about a column or quantity that is NOT in the data (e.g. they ask to plot/fit `voltage_v` but the dataset only has `a1, b2, c2`, or they ask for `SoC` / `内阻` / a cycle that the data doesn't contain), NEVER silently substitute a different column as a stand-in and proceed — that fabricates a result. Instead say plainly the requested column/quantity is not in this dataset, list what IS available, and ask the user to confirm a real column or switch datasets. Same rule for `generate_viz` descriptions: do not name a column the data doesn't have.
- 极值图 / PEAK-OVERLAY: to draw the extrema ON the signal curve (极值图, 标出峰值/极值), run `mark_peaks` (column=the signal) — it keeps the signal and adds a `<col>_peak` column — then `visualize` with y=[the signal, `<col>_peak`] (or `generate_viz` for line+markers). Use `find_peaks` only when the user just wants to COUNT peaks or a peaks-only table; never try to plot the raw signal FROM a find_peaks result (it has no signal column).
- RESHAPED-DATA RECOVERY: if a prior pipeline step reshaped the data (find_peaks → peak_index/…, group_aggregate → value2_mean/…), the original columns (signal, value2, …) are NOT in that result. For PLOTTING this is handled automatically (visualize falls back to the original data and the result's `plotted_from` says which data was used — mention it). For a TOOL that needs an original column, set `dataset` to the original dataset by name, or tell the user to click 重置流水线 — do NOT loop re-asking.
- ACT, don't pre-narrate. When the user asks for a concrete action (画热力图/生成某图, 计算, 检测异常, 运行某算法…), emit that action (visualize / generate_viz / run_tool) IMMEDIATELY. Do NOT first send an `answer` that explains the concept or announces "我将为你生成…" — just do it. Pre-explaining a concept the user already asked for wastes a whole slow LLM round-trip and reads as stalling; the result plus a SHORT interpretation afterward IS the answer.
- After `run_tool`, you'll receive a tool-result message. ALWAYS interpret the result for the user with a final `answer` action — never leave them hanging on raw numbers.
- PIPELINES compose automatically: when a tool outputs a transformed table (filter/normalize/fill_missing/etc. that adds or changes columns), the NEXT `run_tool` in this same turn operates on that transformed result — NOT the original. So for a multi-step request (e.g. 去噪→检测异常→插值→归一化) just call the tools in order; the new columns from step N (e.g. `voltage_v_gauss`) ARE available to step N+1. Read each tool-result's summary for the exact new column names.
- Each transforming step is auto-saved as an inspectable DERIVED dataset (the tool-result includes `derived_dataset`). In your final answer you MAY tell the user that each stage (去噪后/检测后/…) is viewable in 数据集 → 中间结果.
- Keep `thought` to ONE sentence. Write `answer.text` as detailed and well-structured as the question deserves — give real interpretation, the relevant numbers, and useful next steps; do NOT artificially truncate an analysis. The reply streams out to the user token-by-token, so a longer answer is fine — they watch it being written. The only thing to cut is EMPTY boilerplate: don't open a simple greeting with a self-introduction or feature tour ("你好,我是 RLab Cortex…") — get straight to the content. Reference numbers from results explicitly.
- LANGUAGE: Write `answer.text` ENTIRELY in the same language as the user's most recent message — all Chinese if they wrote Chinese, all English if they wrote English. NEVER mix two languages within one answer. (Technical tokens like column names, slugs, and numbers stay verbatim.)
- If parameters are unclear, ask the user via `answer` rather than guessing."""


# 流式事件单元:run_turn 不"返回结果",而是持续 yield 一串 AgentStep,
# 前端据此实时渲染。kind 决定事件类型,payload 是其数据。
# 这是"没有静默步骤"原则的载体 —— 每个 LLM 调用/工具执行/错误都对应一个事件。
@dataclass
class AgentStep:
    # "progress" | "thought" | "tool_call" | "tool_result" | "final"
    # "progress" is a heartbeat — phase ∈ {llm_call, llm_done, tool_start, tool_done}.
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)


# ── 流式半成品解析:对"还没收完"的字符串做正则,边流边显示 ──
# 关键技巧:实时显示用宽松正则抠半成品,最终动作判定用严格 JSON 解析,两套并行。
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
# Captures the (possibly still-streaming) value of the "thought" field — used to
# show the agent's reasoning live, token by token, instead of a blank spinner.
_THOUGHT_PARTIAL_RE = re.compile(r'"thought"\s*:\s*"((?:[^"\\]|\\.)*)', re.DOTALL)


def _extract_partial_thought(raw: str) -> str:
    m = _THOUGHT_PARTIAL_RE.search(raw)
    if not m:
        return ""
    s = m.group(1)
    # Best-effort unescape for live display (full JSON parse happens later).
    return s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")


# Streams the answer text as it forms inside {"args":{"text":"..."}} — gives the
# final reply a Claude-Code-style typewriter feed instead of popping in at once.
_ANSWER_PARTIAL_RE = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)', re.DOTALL)


def _extract_partial_answer(raw: str) -> str:
    m = _ANSWER_PARTIAL_RE.search(raw)
    if not m:
        return ""
    s = m.group(1)
    return s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")


def _safe_parse_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text)
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if m:
            return json.loads(m.group(0))
        raise


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "tool"


def _param_hints(schema: Optional[Dict[str, Any]]) -> List[str]:
    """One token per param, surfacing enum values so the agent picks a VALID
    value instead of guessing (e.g. method∈{iqr|zscore|dixon}, not 'z_score')."""
    hints: List[str] = []
    for name, spec in (schema or {}).items():
        if isinstance(spec, dict) and spec.get("enum"):
            hints.append(f"{name}∈{{{'|'.join(str(v) for v in spec['enum'])}}}")
        else:
            hints.append(str(name))
    return hints


def _registry_index(user_algorithms: List[Algorithm]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for spec in registry.list_builtins():
        out.append({
            "slug": spec.slug,
            "name": spec.name,
            "category": spec.category,
            "description": spec.description,
            "params": _param_hints(spec.params_schema),
            "source": "builtin",
        })
    for a in user_algorithms:
        out.append({
            "slug": a.slug,
            "name": a.name,
            "category": a.category,
            "description": a.description,
            "params": _param_hints(a.params_schema),
            "source": a.source,
            "verified": bool(a.is_verified),
        })
    return out


def _format_one_dataset(ds: Dataset, *, primary: bool, brief: bool = False) -> str:
    schema = ds.schema_json or {}
    cols = schema.get("columns", [])
    tag = "  [PRIMARY / default]" if primary else ""
    if brief:
        names = ", ".join(str(c["name"]) for c in cols)
        return f"Dataset '{ds.name}' (id={ds.id}, {ds.rows}×{ds.columns}){tag} — columns: {names}"
    head = schema.get("head", [])
    col_lines = [f"  - {c['name']} ({c['dtype']}, n_unique={c.get('n_unique')}, n_missing={c.get('n_missing')})" for c in cols]
    return (
        f"Dataset '{ds.name}' (id={ds.id}, rows={ds.rows}, columns={ds.columns}){tag}\n"
        f"Schema:\n" + "\n".join(col_lines) + "\n"
        f"First rows: {json.dumps(head[:5], default=str)}"
    )


def _format_dataset_context(datasets: List[Dataset]) -> str:
    if not datasets:
        return "No dataset is currently selected. Ask the user to upload one or pick from their library."
    if len(datasets) == 1:
        return _format_one_dataset(datasets[0], primary=True)
    # With many datasets (e.g. every sheet of one Excel), give full schema+head
    # for the first few and a one-line column list for the rest, so the prompt
    # stays manageable. The agent can still target any of them by name.
    full_n = 3
    parts = [
        f"{len(datasets)} datasets are loaded. To run a tool / chart against a "
        f"specific one, set the `dataset` arg to its exact name; if omitted, the "
        f"PRIMARY dataset is used. To analyze them all, run the tool on each by "
        f"name. (Full schema shown for the first {min(full_n, len(datasets))}; the rest list columns only.)"
    ]
    for i, ds in enumerate(datasets):
        parts.append(_format_one_dataset(ds, primary=(i == 0), brief=(i >= full_n)))
    return "\n\n".join(parts)


def _resolve_dataset(datasets: List[Dataset], args: Dict[str, Any]) -> Optional[Dataset]:
    """Pick which loaded dataset a tool runs against. `args.dataset` may be a
    name or id; defaults to the primary (first) dataset."""
    if not datasets:
        return None
    want = args.get("dataset")
    if want is not None:
        w = str(want).strip()
        for ds in datasets:
            if ds.name == w or str(ds.id) == w:
                return ds
    return datasets[0]


def _load_df(ds: Optional[Dataset], working: Dict[int, Any]):
    """Load the dataframe for a tool. Uses the turn's WORKING copy if a previous
    step already transformed this dataset — so a pipeline (去噪→检测→插值→归一化)
    actually composes instead of every step re-reading the original data."""
    if ds is None:
        return None
    if ds.id in working:
        return working[ds.id]
    return load_dataset_df(ds)


def _read_frame_for_viz(
    ds: Dataset,
    datasets: List[Dataset],
    working: Dict[int, Any],
    *,
    x: Optional[str],
    y: Optional[Any],
):
    """Pick the dataframe a PLOT should read from, so a reshaping step can't hide
    the column the user actually asked for.

    A cross-turn pipeline head SHADOWS a dataset's original columns: after a
    reshaping step (find_peaks → peak_index/…; group_aggregate → value2_mean/…)
    the working copy no longer carries `signal`/`value2`, so a plain plot of the
    raw column looked 'missing' even though the data is right there on disk —
    and every later turn re-seeded that head, so the agent could never recover.

    For a READ this is unambiguous (no substitution risk): plot from whichever
    frame genuinely has the requested columns. Preference order:
      1) the working/head copy of the target ds (so 去噪后画 signal_gauss works),
      2) the target ds's ORIGINAL on-disk data (un-shadow it),
      3) any OTHER loaded dataset that has them.
    Returns (df, source_note). `source_note` is set only when we had to leave the
    target's working copy, so the caller can tell the user which data was used."""
    needed: List[str] = []
    yy = [y] if isinstance(y, str) else list(y or [])
    for c in yy + ([x] if x else []):
        if c and c not in needed:
            needed.append(c)
    head = _load_df(ds, working)
    # No explicit columns, or the head already has them → keep current behavior.
    if head is None or not needed or all(c in head.columns for c in needed):
        return head, None
    # Head (a pipeline stage) lacks the requested columns — find the real source.
    # 1) the target dataset's ORIGINAL data (only meaningful if the head differs).
    if ds.id in working:
        try:
            orig = load_dataset_df(ds)
            if all(c in orig.columns for c in needed):
                return orig, f"「{ds.name}」原始数据(当前流水线结果里没有该列)"
        except Exception:
            pass
    # 2) any OTHER loaded dataset that has every requested column.
    for other in datasets:
        if other.id == ds.id:
            continue
        try:
            odf = load_dataset_df(other)
        except Exception:
            continue
        if all(c in odf.columns for c in needed):
            return odf, f"「{other.name}」(目标数据集里没有该列)"
    # Nothing has them → return head so the honesty guard fires with its column list.
    return head, None


# ═══════════════════════════════════════════════════════════════════════════
# 动作分发中枢:把 LLM 返回的 action 字符串路由到具体实现。
# 这是一个大 if/elif 分发器,本身不流式 —— 一次执行完返回 dict 结果。
# run_turn 的主循环每收到一个非 answer 动作,就调用它一次。
# ═══════════════════════════════════════════════════════════════════════════
async def _execute_action(
    *,
    session: AsyncSession,
    llm: LLMClient,
    owner_id: int,
    datasets: List[Dataset],
    parsed: Dict[str, Any],
    working: Dict[int, Any],          # 本轮各数据集的"已变换副本"(流水线接力用)
    lineage_state: Dict[int, Any],    # 各数据集的血缘链头部(原始→去噪→…)
    pipeline_state: Dict[str, Any],   # 跨轮流水线状态(由调用方持久化)
) -> Dict[str, Any]:
    action = parsed.get("action", "answer")
    args = parsed.get("args", {}) or {}

    # ── 动作①:列出工具(可按 category 过滤)。内置 + 用户/公开算法 ──
    if action == "list_tools":
        result = await session.execute(
            select(Algorithm).where(
                (Algorithm.owner_id == owner_id) | (Algorithm.is_public == True)  # noqa: E712
            )
        )
        user_algos = list(result.scalars().all())
        index = _registry_index(user_algos)
        cat = args.get("category")
        if cat:
            index = [t for t in index if t["category"] == cat]
        return {"tools": index, "count": len(index)}

    # ── 动作②:查某个工具的完整参数 schema(供 LLM 调用前确认参数) ──
    if action == "describe_tool":
        slug = args.get("slug")
        spec = registry.get_builtin(slug)
        if spec:
            return {
                "slug": spec.slug, "name": spec.name, "category": spec.category,
                "description": spec.description, "params_schema": spec.params_schema,
                "returns": spec.returns, "tags": spec.tags, "source": "builtin",
            }
        row = (await session.execute(select(Algorithm).where(Algorithm.slug == slug))).scalar_one_or_none()
        if row is None:
            return {"error": f"tool not found: {slug}"}
        return {
            "slug": row.slug, "name": row.name, "category": row.category,
            "description": row.description, "params_schema": row.params_schema,
            "returns": row.returns, "source": row.source, "verified": bool(row.is_verified),
        }

    # ── 动作③:执行算法(核心)。先内置注册表,再用户/AI 生成的算法表 ──
    if action == "run_tool":
        slug = args.get("slug")
        params = args.get("params", {}) or {}
        ds = _resolve_dataset(datasets, args)   # 选数据集:args.dataset 名/id,默认第一个
        df = _load_df(ds, working)              # 优先取本轮已变换副本 → 流水线自动接力

        spec = registry.get_builtin(slug)
        if spec:
            result = registry.execute_builtin(slug, df, params)
            label = spec.name
        else:
            # 不是内置 → 查用户/AI 生成的算法,沙箱里跑它的源码
            row = (await session.execute(select(Algorithm).where(Algorithm.slug == slug))).scalar_one_or_none()
            if row is None:
                return {"status": "error", "error": f"tool not found: {slug}"}
            result = registry.execute_code(row.code, df, params)
            label = row.name

        # ★流水线三件事(去噪→检测→插值→归一化能自动接力的关键):
        #   1) 把输出写进 working[ds.id] → 同轮下一个 run_tool 自动读到它(轮内组合)
        #   2) 物化成一个 derived dataset 并记血缘 → 用户能在「中间结果」里逐阶段检查
        #   3) 推进 pipeline_state 头部 → 下一轮("再插值一下")继续在此结果上接力(跨轮)
        # A DataFrame output → thread into the working copy (pipeline composition)
        # AND materialize it as a derived dataset, so the user can inspect every
        # stage (e.g. "去噪后的数据") in 数据集 → 中间结果.
        if ds is not None and result.get("status") == "ok" and result.get("result_path"):
            try:
                out_df = pd.read_parquet(result["result_path"])
                working[ds.id] = out_df
                parent_id, parent_name = lineage_state.get(ds.id, (ds.id, ds.name))
                d = await _persist_dataset(
                    session, owner_id=owner_id, df=out_df,
                    name=f"{ds.name} · {label}", filename=f"{slug}.parquet",
                    file_format="derived", description=f"由「{parent_name}」经『{label}』得到",
                    kind="derived", derived_from=parent_id,
                    lineage={"from": parent_id, "from_name": parent_name,
                             "op": {"slug": slug, "label": label, "params": params}},
                )
                await session.commit()
                lineage_state[ds.id] = (d.id, d.name)
                # Advance the cross-turn pipeline head so the NEXT turn keeps
                # composing on this result instead of re-reading the original.
                prev = pipeline_state.get(str(ds.id)) or {}
                pipeline_state[str(ds.id)] = {
                    "head_id": d.id, "head_name": d.name,
                    "steps": int(prev.get("steps", 0)) + 1,
                }
                result["derived_dataset"] = {"id": d.id, "name": d.name}
            except Exception:
                pass
        return result

    # ── 动作④:画图(line/scatter/bar)。支持多数据集叠加对比 ──
    if action == "visualize":
        # Overlay: args.datasets = [names] → plot the same column(s) from each
        # dataset on ONE chart for comparison (e.g. cell A vs B voltage).
        want_multi = args.get("datasets")
        if isinstance(want_multi, list) and len(want_multi) >= 2:
            frames: List[tuple] = []
            seen: set = set()
            for nm in want_multi:
                w = str(nm).strip()
                for ds in datasets:
                    if (ds.name == w or str(ds.id) == w) and ds.id not in seen:
                        seen.add(ds.id)
                        frames.append((ds.name, load_dataset_df(ds)))
                        break
            if len(frames) >= 2:
                return _build_chart_overlay(
                    frames,
                    chart_type=args.get("chart_type", "line"),
                    x=args.get("x"),
                    y=args.get("y"),
                    title=args.get("title", ""),
                )
        ds = _resolve_dataset(datasets, args)
        if ds is None:
            return {"status": "error", "error": "no dataset selected — ask the user to pick one before plotting."}
        df, src_note = _read_frame_for_viz(ds, datasets, working, x=args.get("x"), y=args.get("y"))
        res = _build_chart(
            df,
            chart_type=args.get("chart_type", "line"),
            x=args.get("x"),
            y=args.get("y"),
            title=args.get("title", ""),
        )
        # Tell the user (via the LLM summary) when we plotted from un-shadowed data.
        if src_note and isinstance(res, dict) and res.get("status") == "ok":
            res.setdefault("summary", {})["plotted_from"] = src_note
        return res

    # ── 动作⑤:批量出图 —— 一次动作产出多张图(每数据集/每列一张) ──
    if action == "visualize_batch":
        # Produce MANY charts in ONE action (批量出图) — far more reliable than
        # asking a weak model to loop `visualize` (which it often skips, then
        # hallucinates a "done" answer). `per`='dataset' → one chart per dataset;
        # `per`='column' → one chart per y-column of a single dataset.
        if not datasets:
            return {"status": "error", "error": "no dataset selected to plot."}
        chart_type = args.get("chart_type", "line")
        x = args.get("x")
        y = args.get("y")
        if isinstance(y, str):
            y = [y]
        per = str(args.get("per") or args.get("split") or "dataset").lower()
        title_prefix = (args.get("title") or "").strip()

        # Resolve target datasets: explicit names (in order), else ALL loaded.
        targets: List[Dataset] = []
        want = args.get("datasets")
        if isinstance(want, list) and want:
            seen_ids: set = set()
            for nm in want:
                w = str(nm).strip()
                for ds in datasets:
                    if (ds.name == w or str(ds.id) == w) and ds.id not in seen_ids:
                        seen_ids.add(ds.id)
                        targets.append(ds)
                        break
        if not targets:
            targets = list(datasets)

        def _pfx(label: str) -> str:
            return (f"{title_prefix} · {label}" if title_prefix else label)

        charts: List[Dict[str, Any]] = []
        chart_labels: List[str] = []
        if per == "column":
            # One chart per y-column on the first target dataset.
            ds = targets[0]
            df, _ = _read_frame_for_viz(ds, datasets, working, x=x, y=y)
            if df is None:
                return {"status": "error", "error": f"could not load dataset '{ds.name}'."}
            ycols = [c for c in (y or []) if c in df.columns]
            if not ycols:
                ycols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != x]
            for col in ycols:
                r = _build_chart(df, chart_type=chart_type, x=x, y=[col], title=_pfx(f"{ds.name}:{col}"))
                if r.get("status") == "ok":
                    charts.append(r["chart"])
                    chart_labels.append(f"{ds.name}:{col}")
        else:  # per dataset
            for ds in targets:
                df, _ = _read_frame_for_viz(ds, datasets, working, x=x, y=y)
                if df is None:
                    continue
                r = _build_chart(df, chart_type=chart_type, x=x, y=y, title=_pfx(ds.name))
                if r.get("status") == "ok":
                    charts.append(r["chart"])
                    chart_labels.append(ds.name)

        if not charts:
            return {"status": "error",
                    "error": "批量出图没有产生任何图 —— 检查列名是否存在、所选数据集是否有数值列。"}
        return {
            "status": "ok", "kind": "chart_batch", "charts": charts,
            "summary": {"type": "chart_batch", "n_charts": len(charts), "per": per,
                        "labels": chart_labels},
        }

    # ── 动作⑥:AI 现写图表代码 —— visualize 表达不了的图(雷达/热力/3D…) ──
    if action == "generate_viz":
        ds = _resolve_dataset(datasets, args)
        if ds is None:
            return {"status": "error", "error": "no dataset selected for visualization."}
        description = args.get("description", "")
        if not description.strip():
            return {"status": "error", "error": "generate_viz requires a 'description' of the chart to build."}
        return await _generate_viz(description, _load_df(ds, working), ds, llm)

    # ── 动作⑦:自扩展 —— LLM 写一个新算法 + 自测,通过即注册、本轮可用 ──
    #    这是 RLab Cortex「自扩展可验证 agent」的核心:缺工具就现造,造完即用。
    if action == "generate_tool":
        description = args.get("description", "")
        if not description.strip():
            return {"error": "generate_tool requires a non-empty 'description'."}
        schema_hint = _format_dataset_context(datasets) if datasets else None
        gen = await generate_algorithm(description, llm=llm, schema_hint=schema_hint)
        passed = bool(gen.get("all_tests_passed"))
        result: Dict[str, Any] = {
            "code": gen["code"],
            "meta": gen["meta"],
            "tests": gen["tests"],
            "all_tests_passed": passed,
        }
        if not passed:
            # Don't register a tool that failed its tests; tell the agent to
            # report the failure instead of trying (and re-trying) to run it.
            result["note"] = (
                "The generated tool FAILED its tests, so it was NOT registered and "
                "CANNOT be run. Tell the user it failed and summarize the error; do "
                "NOT call run_tool, do NOT regenerate the same tool again."
            )
            return result
        # Tests passed → register it immediately so it's runnable THIS turn and
        # persists for later. This is the core of the self-extending vision: the
        # AI writes a missing tool and can use it right away — no separate
        # approval round-trip (the loop that wedged the FFT case came from the
        # agent trying to run_tool a tool that was never registered).
        try:
            meta = parse_meta(gen["code"])
        except Exception:
            meta = gen.get("meta") or {}
        slug = _slugify(meta.get("slug") or meta.get("name") or description[:40])
        existing = (await session.execute(
            select(Algorithm).where(Algorithm.slug == slug, Algorithm.owner_id == owner_id)
        )).scalar_one_or_none()
        report = {"tests": gen["tests"], "all_tests_passed": passed}
        if existing:
            existing.code = gen["code"]
            existing.name = meta.get("name") or existing.name
            existing.description = meta.get("description") or existing.description
            existing.params_schema = meta.get("params_schema") or existing.params_schema or {}
            existing.returns = meta.get("returns") or existing.returns or "dataframe"
            existing.test_report = report
            existing.is_verified = False  # draft until the user keeps it
            existing.version = (existing.version or 1) + 1
            await session.commit()
            slug = existing.slug
        else:
            row = Algorithm(
                owner_id=owner_id, slug=slug,
                name=meta.get("name") or slug,
                category=meta.get("category") or "custom",
                description=meta.get("description") or "",
                source="ai", code=gen["code"],
                params_schema=meta.get("params_schema") or {},
                returns=meta.get("returns") or "dataframe",
                is_public=False, is_verified=False, test_report=report, version=1,
            )
            session.add(row)
            await session.commit()
        result["registered_slug"] = slug
        result["note"] = (
            f"Tool registered as a DRAFT and ready to use now (slug '{slug}'): call "
            f"run_tool with {{\"slug\": \"{slug}\", \"params\": {{...}}}}. The UI shows "
            f"the user a 保存到工具库 / 丢弃 (keep / discard) card, so you do NOT need to "
            f"ask them about saving — just use it and explain the analysis."
        )
        return result

    # answer (or unknown) — pass through
    return {"text": args.get("text", "")}


_CHART_MAX_POINTS = 1500

VIZ_SYSTEM_PROMPT = """You write Python that builds a chart spec from a pandas DataFrame.

Define exactly ONE top-level function:
    def run(df, **params) -> dict

Return ONE of these two dict shapes (nothing printed, nothing else):

(A) For a plain LINE / SCATTER / BAR chart — the lightweight series spec:
{
  "chart_type": "line",          # or "scatter" or "bar"
  "mode": "series",
  "x_label": "<x axis label>",
  "title": "<short title>",
  "series": [ {"label": "<series name>", "points": [{"x": <float>, "y": <float or None>}, ...]} ]
}

(B) For ANYTHING ELSE — radar / polar, heatmap, contour, 3D surface/scatter, box,
    violin, histogram, parallel-coordinates, pie, sankey, error bars, … — return a
    PLOTLY figure (this can express essentially ANY chart):
{
  "plotly": {
    "data":   [ { ...one or more Plotly traces... } ],
    "layout": { "title": "<short title>", ... }
  }
}
    Example radar trace: {"type":"scatterpolar","r":[1,0.5,0.8,1],"theta":["v","i","t","v"],"fill":"toself","name":"Obs 1"}
    Example heatmap:     {"type":"heatmap","z":[[..],[..]],"x":[...],"y":[...]}

RULES:
- Allowed imports: numpy, pandas, math, statistics ONLY. Do NOT import plotly or
  matplotlib — for shape (B) just BUILD the plain dict of traces + layout yourself.
- ALL numbers must be native Python float/int (float(...) / int(...)); all arrays
  must be plain Python lists — NEVER numpy types/arrays (they won't survive JSON).
- Downsample large data to <= 2000 points per trace/series.
- Use the EXACT column names from the schema given. Do not invent columns.
- No file/network access, no print(). Just compute and return the dict.
- Use (A) for plain line/scatter/bar; use (B) for every other chart type.

Reply with ONLY a single ```python fenced code block."""

_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def _extract_code_block(text: str) -> str:
    m = _CODE_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _coerce_series_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """numpy floats get stringified crossing the sandbox JSON boundary; coerce
    every point's x/y back to float (or None) so the chart renders numerically."""
    for s in spec.get("series", []) or []:
        for p in s.get("points", []) or []:
            for k in ("x", "y"):
                v = p.get(k)
                if isinstance(v, str):
                    try:
                        p[k] = float(v)
                    except ValueError:
                        p[k] = None
    return spec


async def _generate_viz(description: str, df: pd.DataFrame, ds: Dataset, llm: LLMClient) -> Dict[str, Any]:
    """AI-written visualization: the model writes `run(df) -> chart-spec`, we run
    it in the sandbox and hand the spec to the same interactive ChartPanel. Lets
    the agent build charts the fixed `visualize` tool can't express."""
    schema_ctx = _format_one_dataset(ds, primary=True)
    prev_err = ""
    for attempt in range(2):
        user = (
            f"Dataset schema:\n{schema_ctx}\n\n"
            f"Build this chart: {description}\n\n"
            "Return ONLY a ```python``` block defining run(df, **params) that returns the chart-spec dict."
        )
        if prev_err:
            user += f"\n\nYOUR PREVIOUS ATTEMPT FAILED: {prev_err[:600]}\nFix it; try a different approach."
        try:
            raw = await llm.chat(
                [{"role": "system", "content": VIZ_SYSTEM_PROMPT}, {"role": "user", "content": user}],
                temperature=0.2 + 0.15 * attempt, max_tokens=2500,
            )
        except Exception as e:
            return {"status": "error", "error": f"viz codegen LLM failed: {type(e).__name__}: {e}"}

        code = _extract_code_block(raw)
        # mode="viz": run the chart code WITHOUT requiring a META dict (the viz
        # prompt produces a chart builder, not a library algorithm). Validating
        # it as an algorithm rejected any attempt where the LLM omitted META —
        # the intermittent "missing top-level META dict" failure on box/violin/…
        res = sandbox_executor.execute(code, {}, input_df=df, save_result=False, mode="viz")
        if res.status != "ok":
            prev_err = res.error
            continue
        spec = (res.summary or {}).get("value")
        if not isinstance(spec, dict):
            prev_err = f"run() must return a dict; got {str(res.summary)[:300]}"
            continue
        # Shape (B): a Plotly figure — renders essentially any chart type.
        pf = spec.get("plotly")
        if isinstance(pf, dict) and pf.get("data"):
            return {"status": "ok", "kind": "chart", "generated_viz": True, "code": code,
                    "chart": {"plotly": {"data": pf.get("data", []), "layout": pf.get("layout", {})}}}
        # Shape (A): the lightweight line/scatter/bar series spec.
        if not spec.get("series"):
            prev_err = f"run() must return either a 'plotly' figure or a non-empty 'series' list; got {str(res.summary)[:300]}"
            continue
        spec = _coerce_series_spec(spec)
        spec.setdefault("mode", "series")
        spec.setdefault("chart_type", "line")
        return {"status": "ok", "kind": "chart", "chart": spec, "generated_viz": True, "code": code}

    return {"status": "error", "error": f"could not generate a working chart after 2 attempts. Last error: {prev_err[:600]}"}


def _build_chart(
    df: pd.DataFrame,
    *,
    chart_type: str = "line",
    x: Optional[str] = None,
    y: Optional[Any] = None,
    title: str = "",
) -> Dict[str, Any]:
    """Turn a request into a self-contained, INTERACTIVE chart spec.

    We ship the (downsampled) data inline alongside the full list of plottable
    columns, so the frontend can let the user re-map axes / series / chart type
    entirely client-side without another backend round-trip. That is the whole
    point of the feature: the visualization dialog is generated from the data,
    not hard-coded, and the user drives it.
    """
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return {"status": "error", "error": "no numeric columns to plot in this dataset."}

    # Normalize y to a list and validate against real columns.
    if isinstance(y, str):
        y = [y]
    requested_y = list(y or [])
    valid_y = [c for c in requested_y if c in df.columns]
    # HONESTY GUARD: if the caller explicitly named column(s) and NONE of them
    # exist, do NOT silently plot a different column — that misrepresents the
    # data as if it were the requested quantity (the "c2 用作 voltage_v 的替代"
    # failure). Surface it so the agent tells the user the column is missing
    # instead of substituting a stand-in.
    if requested_y and not valid_y:
        return {
            "status": "error",
            "error": (
                f"requested column(s) not in this dataset: {', '.join(requested_y)}. "
                f"available numeric columns: {', '.join(numeric_cols)}. "
                f"Do NOT substitute another column — tell the user the requested "
                f"column isn't in this data, or switch to a dataset that has it."
            ),
        }
    missing_y = [c for c in requested_y if c not in df.columns]
    y = valid_y or [c for c in numeric_cols if c != x][:1] or numeric_cols[:1]

    # x defaults to the first non-y numeric column (often time/index); fall back
    # to the row index so we always have an axis.
    if x not in df.columns:
        x = next((c for c in numeric_cols if c not in y), None)

    # Columns we actually ship: x (if real) + all y + remaining numerics so the
    # user can switch series client-side. Bounded list keeps the payload small.
    ship_cols: List[str] = []
    for c in ([x] if x in df.columns else []) + list(y) + numeric_cols:
        if c not in ship_cols and c in df.columns:
            ship_cols.append(c)
    ship_cols = ship_cols[:12]

    sub = df[ship_cols].dropna(how="all")
    n = len(sub)
    if n > _CHART_MAX_POINTS:
        idx = np.linspace(0, n - 1, _CHART_MAX_POINTS).astype(int)
        sub = sub.iloc[idx]

    if x is None:
        sub = sub.reset_index().rename(columns={"index": "_row"})
        x = "_row"
        ship_cols = ["_row"] + ship_cols

    data = json.loads(sub.to_json(orient="records"))  # JSON-safe (NaN -> null)

    return {
        "status": "ok",
        "kind": "chart",
        "chart": {
            "chart_type": chart_type if chart_type in ("line", "scatter", "bar") else "line",
            "x": x,
            "y": list(y),
            "title": title,
            "columns": ship_cols,
            "numeric_columns": [c for c in ship_cols if c == "_row" or pd.api.types.is_numeric_dtype(df.get(c, pd.Series(dtype=float)))],
            "data": data,
            "downsampled_from": n if n > _CHART_MAX_POINTS else None,
        },
        "summary": {"type": "chart", "points": len(data), "series": list(y),
                    **({"missing_columns": missing_y} if missing_y else {})},
    }


def _build_chart_overlay(
    frames: List[Any],
    *,
    chart_type: str = "line",
    x: Optional[str] = None,
    y: Optional[Any] = None,
    title: str = "",
) -> Dict[str, Any]:
    """Overlay the same column(s) from several datasets onto ONE chart.

    `frames` is a list of (label, DataFrame). Each dataset has its own x-grid,
    so we interpolate every series onto a shared grid over the overlapping
    x-range (falling back to normalized row-position if the ranges don't
    overlap). Series are labelled '<dataset>:<column>' so the legend stays clear.
    The frontend ChartPanel renders multiple series unchanged.
    """
    def numcols(df: pd.DataFrame) -> List[str]:
        return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    common = set(numcols(frames[0][1]))
    for _, df in frames[1:]:
        common &= set(numcols(df))
    common = [c for c in numcols(frames[0][1]) if c in common]
    if not common:
        return {"status": "error", "error": "所选数据集没有共同的数值列,无法叠加对比。"}

    if x not in common:
        x = common[0]
    if isinstance(y, str):
        y = [y]
    ycols = [c for c in (y or []) if c in common and c != x] or [c for c in common if c != x][:1]
    if not ycols:
        return {"status": "error", "error": "没有可叠加的数值列。"}

    # Emit INDEPENDENT series — each keeps its own (x, y) points, so series of
    # different lengths / x-grids (e.g. 3 raw points vs a 10-point interpolated
    # curve) coexist on one chart without resampling. The frontend draws each
    # series from its own data array over a shared numeric x-axis.
    multi_label = len(frames) > 1 or len(ycols) > 1
    series: List[Dict[str, Any]] = []
    for lbl, df in frames:
        sub = df[[x] + ycols].dropna().sort_values(x)
        if len(sub) > _CHART_MAX_POINTS:
            idx = np.linspace(0, len(sub) - 1, _CHART_MAX_POINTS).astype(int)
            sub = sub.iloc[idx]
        xs = sub[x].to_numpy(dtype=float)
        for c in ycols:
            ys = sub[c].to_numpy(dtype=float)
            pts = [{"x": float(xx), "y": (None if np.isnan(yy) else float(yy))}
                   for xx, yy in zip(xs, ys)]
            series.append({"label": f"{lbl}:{c}" if multi_label else lbl, "points": pts})

    return {
        "status": "ok",
        "kind": "chart",
        "chart": {
            "chart_type": chart_type if chart_type in ("line", "scatter", "bar") else "line",
            "mode": "series",
            "x_label": x,
            "title": title or ("叠加对比:" + " / ".join(lbl for lbl, _ in frames)),
            "series": series,
            "overlay": True,
        },
        "summary": {"type": "chart", "series": [s["label"] for s in series],
                    "datasets": [lbl for lbl, _ in frames]},
    }


def _format_tools_brief(tools: List[Dict[str, Any]]) -> str:
    """One-line per tool, grouped by category. Goes in the system prompt so the
    agent picks a REAL slug instead of guessing — guessing was the #1 cause
    of wasted round-trips in the wedge validation (S1 hallucinated
    'low_pass_filter' on its first attempt instead of 'savgol_filter')."""
    if not tools:
        return "(no tools registered — only generate_tool will work)"
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for t in tools:
        by_cat.setdefault(t["category"], []).append(t)
    out: List[str] = []
    for cat in sorted(by_cat):
        out.append(f"### {cat}")
        for t in sorted(by_cat[cat], key=lambda x: x["slug"]):
            params = ", ".join(t.get("params", [])[:8])
            out.append(f"- `{t['slug']}` — {t['description']}  (params: {params})")
    return "\n".join(out)


# "双视图"模式:前端拿完整结果(含上千个点),LLM 只拿瘦身后的 summary。
# 避免大数组浪费 context、且被 8000 字符上限截断成坏 JSON 喂给模型。
def _llm_result_view(result: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a tool result before feeding it back to the LLM. Chart results carry
    big inline point-data arrays that (a) waste context and (b) get truncated
    mid-JSON by the 8000-char cap, handing the model malformed JSON. The frontend
    still receives the FULL result via the tool_result event — only the LLM's
    copy is trimmed to its summary."""
    if not isinstance(result, dict):
        return result
    kind = result.get("kind")
    if kind == "chart":
        ch = result.get("chart") or {}
        return {"status": result.get("status"), "kind": "chart",
                "chart_title": ch.get("title"), "x": ch.get("x"), "y": ch.get("y"),
                "summary": result.get("summary")}
    if kind == "chart_batch":
        s = result.get("summary") or {}
        return {"status": result.get("status"), "kind": "chart_batch",
                "n_charts": s.get("n_charts") or len(result.get("charts") or []),
                "per": s.get("per"), "labels": s.get("labels"),
                "note": "已为用户渲染了这些图,请用一句话总结要点,不要声称还要再画。"}
    return result


async def run_turn(
    *,
    session: AsyncSession,
    llm: LLMClient,
    owner_id: int,
    datasets: Optional[List[Dataset]] = None,
    history: List[Dict[str, str]],
    user_message: str,
    max_steps: int = 8,
    pipeline_state: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[AgentStep]:
    """Execute one chat turn: keep looping until the agent produces an `answer`
    action or exhausts max_steps. Yields a sequence of AgentStep events.

    `datasets` is the set of datasets loaded into the conversation; the first is
    the PRIMARY/default. Tools target a specific one via their `dataset` arg.

    `pipeline_state` (mutable; persisted by the caller across turns) maps
    str(dataset_id) -> {head_id, head_name, steps}. When a dataset has a head,
    this turn SEEDS its working copy from that derived dataset so a multi-turn
    pipeline keeps composing instead of resetting. It is mutated in place as new
    stages are produced, so the caller persists continuity automatically."""
    # ── 三级流水线状态:轮内(working)/ 血缘(lineage)/ 跨轮(pipeline_state)──
    datasets = list(datasets or [])
    pipeline_state = pipeline_state if isinstance(pipeline_state, dict) else {}
    # Per-turn working copy of each dataset: a tool that outputs a transformed
    # DataFrame updates it, and the next tool reads it — so a pipeline composes.
    working: Dict[int, Any] = {}
    # Lineage chain head per dataset id — so each materialized stage points at
    # the previous one (原始 → 去噪 → 检测 → …).
    lineage_state: Dict[int, Any] = {}

    # ── Cross-turn continuation ──────────────────────────────────────────────
    # Seed working/lineage from a prior turn's pipeline head so "再插值一下"
    # operates on the 检测后 result, not the original data. A head that was
    # deleted/GC'd is dropped silently (the pipeline just restarts from source).
    pipeline_notes: List[str] = []
    resumed: List[Dict[str, Any]] = []
    for ds in datasets:
        entry = pipeline_state.get(str(ds.id))
        head_id = (entry or {}).get("head_id")
        if not head_id:
            continue
        head_ds = (await session.execute(
            select(Dataset).where(Dataset.id == head_id, Dataset.owner_id == owner_id)
        )).scalar_one_or_none()
        if head_ds is None:
            pipeline_state.pop(str(ds.id), None)  # stale head — forget it
            continue
        try:
            df_head = load_dataset_df(head_ds)
        except Exception:
            pipeline_state.pop(str(ds.id), None)
            continue
        working[ds.id] = df_head
        lineage_state[ds.id] = (head_ds.id, head_ds.name)
        cols = ", ".join(map(str, df_head.columns))
        pipeline_notes.append(
            f"- 「{ds.name}」上几轮已处理到第 {entry.get('steps', '?')} 步(当前结果数据集:"
            f"「{entry.get('head_name', head_ds.name)}」)。后续 run_tool 默认在这个**已处理结果**"
            f"上继续(不是原始数据);当前工作表的列:{cols[:400]}。"
            f"若用户想从原始数据重新开始,提醒他在对话顶部点「重置流水线」。"
        )
        resumed.append({"dataset_id": ds.id, "name": ds.name,
                        "head_id": head_ds.id, "head_name": head_ds.name,
                        "steps": int(entry.get("steps", 0))})
    if resumed:
        yield AgentStep(kind="pipeline", payload={"resumed": resumed})

    user_algo_rows = (await session.execute(
        select(Algorithm).where(
            (Algorithm.owner_id == owner_id) | (Algorithm.is_public == True)  # noqa: E712
        )
    )).scalars().all()
    tools_index = _registry_index(list(user_algo_rows))
    tools_brief = _format_tools_brief(tools_index)

    # ── 拼 system prompt:协议规则 + 数据集上下文 + 真实工具清单 ──
    #    把真实 slug 灌进 prompt 是抑制弱模型「幻觉出不存在工具」的关键手段。
    system_msg = (
        SYSTEM_PROMPT
        + "\n\n## Dataset context\n" + _format_dataset_context(datasets)
        + "\n\n## Available tools (use the exact slug — do NOT invent names)\n"
        + tools_brief
        + "\n\nIf none of the above fits, use `generate_tool` with a precise description."
    )
    if pipeline_notes:
        system_msg += (
            "\n\n## Pipeline continuation (跨轮流水线)\n"
            "This conversation already ran a pipeline on the dataset(s) below in earlier turns. "
            "The working table now carries those prior stages' columns, and run_tool continues on it:\n"
            + "\n".join(pipeline_notes)
        )
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_msg}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    model_label = getattr(llm, "model", None) or "LLM"
    # Tracks whether we've already nudged the model to reformat a non-JSON
    # reply. We only spend ONE self-heal round-trip before falling back to
    # presenting the prose verbatim, so a chatty model can't loop forever.
    reformat_attempted = False
    # Tracks whether we've already nudged the model after it returned an EMPTY
    # answer (a contentless `{"action":"answer"}` with no/blank text — common on
    # weak models facing a vague follow-up). One retry, then a friendly fallback
    # so the user never sees a blank bubble.
    empty_answer_retried = False
    # Circuit-breaker: count failures per (action, slug). When a tool keeps
    # failing the SAME way we escalate a warning, then stop — the #1 cause of
    # "hit step limit with no answer" was the agent re-calling a broken tool.
    fail_counts: Dict[str, int] = {}

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 主循环(ReAct):最多 max_steps 步,每步 = 想→做→观察。            ║
    # ║   阶段1 心跳   → 阶段2 流式收 LLM → 阶段3 解析 JSON                  ║
    # ║   阶段4 若 answer 则收尾返回 → 阶段5 否则执行动作 → 阶段6 回灌结果   ║
    # ║ LLM 只要不输出 answer,循环就把工具结果喂回去继续 —— 这就是自主性。 ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    for step_no in range(max_steps):
        # 阶段1 ── 心跳:在调用 LLM 之前就发,UI 立刻显示"正在调用",
        #          即使模型要 5-30s 才吐第一个 token 也不会是死寂的转圈。
        yield AgentStep(kind="progress", payload={
            "phase": "llm_call", "step": step_no + 1, "model": model_label,
            "msg": f"calling {model_label} (step {step_no + 1})",
        })
        t0 = time.monotonic()
        raw = ""
        last_thought = ""
        last_answer = ""
        try:
            # 阶段2 ── 流式收取:边收边用正则抠出半成品 thought / answer.text,
            #          实时推给前端做打字机效果;同时累积完整文本待会儿严格解析。
            # Stream tokens so the agent's reasoning shows up live (no blank
            # "思考中" spinner). We still accumulate the full text and parse the
            # JSON action exactly as before once the stream completes.
            async for delta in llm.stream(messages, temperature=0.2, max_tokens=2000):
                raw += delta
                partial = _extract_partial_thought(raw)
                if partial and partial != last_thought:
                    last_thought = partial
                    yield AgentStep(kind="thought_delta", payload={"text": partial, "step": step_no + 1})
                ans = _extract_partial_answer(raw)
                if ans and ans != last_answer:
                    last_answer = ans
                    yield AgentStep(kind="answer_delta", payload={"text": ans, "step": step_no + 1})
        except Exception as e:
            dt = time.monotonic() - t0
            yield AgentStep(kind="progress", payload={
                "phase": "llm_done", "step": step_no + 1, "model": model_label,
                "ok": False, "duration_s": round(dt, 2), "error": f"{type(e).__name__}: {e}",
                "msg": f"{model_label} failed after {dt:.1f}s: {type(e).__name__}",
            })
            yield AgentStep(kind="final", payload={
                "text": f"**LLM call failed:** {type(e).__name__}: {e}\n\n"
                        f"Check your provider settings (DeepSeek / Qwen / OpenAI key & base URL) in the Settings page.",
                "error": True,
            })
            return

        dt = time.monotonic() - t0
        yield AgentStep(kind="progress", payload={
            "phase": "llm_done", "step": step_no + 1, "model": model_label,
            "ok": True, "duration_s": round(dt, 2), "chars": len(raw or ""),
            "msg": f"{model_label} returned {len(raw or '')} chars in {dt:.1f}s",
        })

        # 阶段3 ── 解析 JSON。失败时进入「自愈第①②层」(纯散文 / 半结构化)。
        try:
            parsed = _safe_parse_json(raw)
        except Exception:
            # Fast path: if the reply is plainly a natural-language answer (no JSON
            # object, no tool-call intent), just use it — skip the reformat round-
            # trip entirely. Models that don't strictly follow the JSON protocol
            # (e.g. deepseek-flash) answer conversational questions in prose, and
            # re-asking only burns a whole slow LLM call of latency.
            if "{" not in raw and not re.search(
                r"\b(run_tool|generate_tool|generate_viz|visualize|list_tools|describe_tool)\b", raw,
            ):
                yield AgentStep(kind="final", payload={"text": raw.strip()})
                return
            # 自愈第②层:看起来像坏掉的结构化输出 —— 只催一次重发 JSON,
            #   还坏就把散文原样给用户(reformat_attempted 保证最多自愈一次,不死循环)。
            # Otherwise it looks half-structured — self-heal:
            #   1st offence → nudge it once to resend as JSON (a visible llm_call step).
            #   still broken → present the prose verbatim rather than an error.
            if not reformat_attempted:
                reformat_attempted = True
                yield AgentStep(kind="progress", payload={
                    "phase": "tool_done", "step": step_no + 1, "ok": True,
                    "msg": "reply was not JSON — asking model to reformat",
                })
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": (
                    "Your previous reply was not the required single JSON object. "
                    "Resend the SAME content (same language) as: "
                    '{"thought":"...","action":"answer","args":{"text":"<your answer>"}} '
                    "— output ONLY that JSON object, nothing else."
                )})
                continue
            yield AgentStep(kind="final", payload={"text": raw.strip()})
            return

        action = parsed.get("action", "answer")
        thought = parsed.get("thought", "")
        if thought:
            yield AgentStep(kind="thought", payload={"text": thought, "step": step_no + 1})

        # 阶段4 ── 终止条件:LLM 给出 answer 就收尾。空答案进入「自愈第③层」。
        if action == "answer":
            answer_text = (parsed.get("args", {}) or {}).get("text", "") or ""
            if not answer_text.strip():
                # The model produced a contentless answer (blank bubble). Nudge it
                # ONCE for a real reply; if it's still empty, emit a helpful
                # fallback instead of an empty bubble.
                if not empty_answer_retried:
                    empty_answer_retried = True
                    yield AgentStep(kind="progress", payload={
                        "phase": "tool_done", "step": step_no + 1, "ok": True,
                        "msg": "模型返回了空答案 —— 让它重新作答",
                    })
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": (
                        "你上一条回复的 answer.text 是空的。请用与用户相同的语言,给出一个"
                        "有实际内容的回答(JSON: {\"thought\":\"...\",\"action\":\"answer\","
                        "\"args\":{\"text\":\"...\"}})。如果用户的需求不清楚,就在 text 里"
                        "用一句话反问澄清。只输出该 JSON。"
                    )})
                    continue
                yield AgentStep(kind="final", payload={"text": (
                    "我没能理解你想要什么 —— 能再说具体点吗?比如想看哪一列、做哪种分析或图表。"
                )})
                return
            yield AgentStep(kind="final", payload={"text": answer_text})
            return

        # 阶段5 ── 执行动作:非 answer 的动作都交给 _execute_action 分发器。
        #          全程发 tool_call / tool_start / tool_done / tool_result 事件,
        #          对应记忆里的铁律「没有静默步骤」。
        yield AgentStep(kind="tool_call", payload={"action": action, "args": parsed.get("args", {})})
        yield AgentStep(kind="progress", payload={
            "phase": "tool_start", "step": step_no + 1, "action": action,
            "msg": f"running {action}…",
        })
        t1 = time.monotonic()
        try:
            tool_result = await _execute_action(
                session=session, llm=llm, owner_id=owner_id, datasets=datasets, parsed=parsed,
                working=working, lineage_state=lineage_state, pipeline_state=pipeline_state,
            )
        except Exception as e:
            tdt = time.monotonic() - t1
            yield AgentStep(kind="progress", payload={
                "phase": "tool_done", "step": step_no + 1, "action": action,
                "ok": False, "duration_s": round(tdt, 2), "error": f"{type(e).__name__}: {e}",
                "msg": f"{action} crashed after {tdt:.1f}s",
            })
            tool_result = {"status": "error", "error": f"{type(e).__name__}: {e}"}
        else:
            tdt = time.monotonic() - t1
            yield AgentStep(kind="progress", payload={
                "phase": "tool_done", "step": step_no + 1, "action": action,
                "ok": True, "duration_s": round(tdt, 2),
                "msg": f"{action} finished in {tdt:.1f}s",
            })
        yield AgentStep(kind="tool_result", payload={"action": action, "result": tool_result})

        # 断路器:按 (action, slug) 统计"同一种失败"的次数 —— 第2次给 LLM
        # 警告别用同参数重试,第3次直接停。防止 agent 反复调坏工具空转把步数耗光
        # (这正是过去"达到步数上限却没答案"的头号原因)。
        # Circuit-breaker on repeated identical failures: escalate a warning at 2,
        # stop at 3 — so the agent can't burn the whole step budget re-calling a
        # tool that keeps erroring the same way.
        nudge = ""
        if isinstance(tool_result, dict) and tool_result.get("status") == "error":
            _slug = (parsed.get("args") or {}).get("slug") or action
            fkey = f"{action}:{(parsed.get('args') or {}).get('slug') or ''}"
            fail_counts[fkey] = fail_counts.get(fkey, 0) + 1
            if fail_counts[fkey] >= 3:
                yield AgentStep(kind="final", payload={
                    "text": (
                        f"「{_slug}」连续失败了 {fail_counts[fkey]} 次"
                        f"({str(tool_result.get('error', ''))[:120]}),我先停下来避免空转。"
                        "可能这个工具不适合当前数据,或参数对不上 —— 换个问法,或告诉我更具体的目标再试。"
                    ),
                    "error": True,
                })
                return
            if fail_counts[fkey] >= 2:
                nudge = (
                    f"\n\n⚠ `{_slug}` 已用同样方式失败 {fail_counts[fkey]} 次。不要再用相同参数重试 —— "
                    "换个工具、大改参数,或直接基于已有结果作答。"
                )

        # 阶段6 ── 回灌:把(瘦身后的)工具结果作为 user 消息塞回对话,
        #          _llm_result_view 把图表的大数组裁成 summary,避免撑爆/截断 context;
        #          截断到 8000 字符 + 可能附带断路器警告 nudge,然后进入下一步循环。
        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": "Tool result:\n" + json.dumps(_llm_result_view(tool_result), default=str)[:8000]
                       + nudge + "\n\nNow respond with the next JSON action.",
        })

    # 循环跑满 max_steps 仍没拿到 answer → 兜底收尾(通常是某工具反复失败)。
    yield AgentStep(kind="final", payload={
        "text": (
            "我执行了多步但还没给出最终结论(达到步数上限)。这通常说明某个工具反复"
            "失败——右侧工作台的步骤详情能看到卡在哪。可以换个问法,或确认所需数据/工具已就绪后重试。"
        ),
        "error": True,
    })
