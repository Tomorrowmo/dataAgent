"""Self-healing format adapter service.

When a user uploads a file whose extension neither built-in pandas readers
nor any saved adapter can parse, this service:
  1. Stages the bytes
  2. Asks the LLM to write a parser (`def parse(path) -> pd.DataFrame`)
  3. Runs that parser against the actual file in the sandbox
  4. Returns the proposed code + preview to the UI for user approval
  5. On approval, saves the parser as a FormatAdapter so subsequent uploads
     of the same extension parse silently.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import FormatAdapter
from ..sandbox import executor as sandbox_executor
from ..sandbox.validator import validate_algorithm_code
from .llm import LLMClient


PARSER_SYSTEM_PROMPT = """You are a Python expert writing safe, focused file-format parsers for a curated tool library.

The user has uploaded a file whose format is not natively supported. Your job is to write a Python function that reads the file and returns a pandas DataFrame.

OUTPUT FORMAT — STRICTLY a single fenced ```python``` block containing:
1. Optional imports (numpy, pandas, struct, io, gzip, zipfile, bz2, binascii, csv, xml.etree.ElementTree, configparser, math, statistics, itertools, functools, operator, collections, typing, datetime, re, json — that's the full allowlist)
2. A top-level function `parse(path: str) -> pandas.DataFrame`
3. Optional: a META dict at the top with {"name": "...", "extension": ".xxx", "description": "..."}

HARD RULES:
- NO file I/O outside the `path` parameter passed in
- NO network access (no requests / urllib / socket)
- NO subprocess / shell / eval / exec / compile
- The function MUST handle errors gracefully — raise ValueError with a clear message if the format is wrong
- Return a tidy DataFrame: one row per observation, one column per measured variable
- If the file has multiple sheets/sections, pick the most useful one and document the choice in a comment
- Use `open(path, 'rb')` for binary, `open(path, 'r', encoding=...)` for text

USEFUL HEURISTICS:
- If the first few bytes look like ZIP magic (PK\\x03\\x04), try `zipfile` — many lab tools wrap CSVs / XML in zip
- If the file starts with XML declaration or `<`, use `xml.etree.ElementTree`
- If it looks like binary with a fixed header, use `struct.unpack`
- If it looks like CSV with non-standard delimiters or encoding, use pandas with explicit args

Reply with nothing outside the fenced code block."""


_CODE_RE = re.compile(r"```python\s*(.*?)```", re.DOTALL)


@dataclass
class ParserBundle:
    code: str
    meta: Dict[str, Any]
    status: str   # "ok" | "error"
    error: str
    summary: Dict[str, Any]
    duration_ms: int
    result_rows: int
    result_path: Optional[str]


def _extract_code(text: str) -> str:
    m = _CODE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _extract_meta(code: str) -> Dict[str, Any]:
    """Best-effort META extraction — never raise; sandbox does the real validation."""
    try:
        ns: Dict[str, Any] = {}
        exec(compile(code, "<meta-extract>", "exec"), ns, ns)
        meta = ns.get("META")
        if isinstance(meta, dict):
            return meta
    except Exception:
        pass
    return {}


def _peek(path: Path, max_bytes: int = 8192) -> str:
    """Return a short hex+ascii preview of the file head, for the LLM prompt."""
    try:
        raw = path.read_bytes()[:max_bytes]
    except Exception as e:
        return f"(could not read file: {e})"
    hex_part = raw[:512].hex()
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in raw[:512])
    return f"size={path.stat().st_size} bytes\nfirst 512 bytes (hex):\n{hex_part}\n\nfirst 512 bytes (ascii view):\n{ascii_part}"


async def generate_parser_stream(
    *,
    file_path: Path,
    extension: str,
    llm: LLMClient,
    max_attempts: int = 3,
) -> AsyncIterator[Dict[str, Any]]:
    """Streaming variant — yields step events as it generates, validates, and
    sandbox-tests successive parser attempts. Auto-retries up to max_attempts
    times, feeding the previous failure back to the model so it tries a
    different approach. The final event is either `success` or `give_up`."""
    head_preview = _peek(file_path)
    previous_errors: List[str] = []
    last_code: str = ""

    for attempt_n in range(1, max_attempts + 1):
        yield {"event": "attempt_start", "n": attempt_n, "max": max_attempts}

        user_msg = (
            f"Write a parser for files with extension `{extension}`.\n\n"
            f"Sample file head:\n{head_preview}\n\n"
            f"Return ONLY a fenced ```python``` block with the META dict + parse(path) function."
        )
        if previous_errors:
            user_msg += "\n\nPREVIOUS ATTEMPT(S) FAILED — DO NOT repeat the same code. Try a different approach:\n"
            for i, err in enumerate(previous_errors[-2:], 1):
                user_msg += f"\n--- Attempt {i} error ---\n{err[:600]}\n"
            if last_code:
                user_msg += f"\n--- Previous code (do not repeat verbatim) ---\n{last_code[:1500]}\n"

        # 1. LLM call — STREAM the tokens so the UI shows the parser being
        # written live (a contentless spinner was the #1 complaint). We still
        # accumulate the full text for extraction/validation exactly as before.
        t0 = time.perf_counter()
        text = ""
        try:
            async for delta in llm.stream(
                [
                    {"role": "system", "content": PARSER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2 + 0.15 * (attempt_n - 1),  # nudge diversity on retries
                max_tokens=3000,
            ):
                text += delta
                yield {"event": "token", "n": attempt_n, "delta": delta}
        except Exception as e:
            err = f"LLM call failed: {type(e).__name__}: {e}"
            yield {"event": "attempt_failed", "n": attempt_n, "stage": "llm", "error": err}
            previous_errors.append(err)
            continue
        if not text.strip():
            err = "LLM returned an empty response"
            yield {"event": "attempt_failed", "n": attempt_n, "stage": "llm", "error": err}
            previous_errors.append(err)
            continue
        llm_ms = int((time.perf_counter() - t0) * 1000)

        code = _extract_code(text)
        meta = _extract_meta(code)
        meta.setdefault("extension", extension)
        meta.setdefault("name", f"Parser for {extension}")
        meta.setdefault("description", "")
        last_code = code

        yield {
            "event": "code_ready",
            "n": attempt_n,
            "duration_ms": llm_ms,
            "code": code,
            "meta": meta,
            "size": len(code),
        }

        # 2. AST validation
        validation = validate_algorithm_code(code, mode="parser")
        if not validation.ok:
            err = "validation failed: " + "; ".join(validation.errors[:5])
            yield {"event": "attempt_failed", "n": attempt_n, "stage": "validation", "error": err}
            previous_errors.append(err)
            continue
        yield {"event": "validated", "n": attempt_n, "imports": validation.imports}

        # 3. Sandbox execution
        t1 = time.perf_counter()
        try:
            result = sandbox_executor.execute(
                code, params={}, input_df=None,
                save_result=True,
                mode="parser", parser_file=str(file_path),
            )
        except Exception as e:
            err = f"sandbox crashed: {type(e).__name__}: {e}"
            yield {"event": "attempt_failed", "n": attempt_n, "stage": "sandbox", "error": err}
            previous_errors.append(err)
            continue
        sandbox_ms = int((time.perf_counter() - t1) * 1000)

        if result.status != "ok":
            err = result.error or "unknown sandbox error"
            yield {
                "event": "attempt_failed",
                "n": attempt_n, "stage": "sandbox", "duration_ms": sandbox_ms,
                "error": err[:1500],
            }
            previous_errors.append(err)
            continue

        # Read preview from the parquet the parser wrote
        preview: List[Dict[str, Any]] = []
        if result.result_path:
            try:
                df = pd.read_parquet(result.result_path)
                preview = df.head(10).to_dict(orient="records")
            except Exception:
                pass

        yield {
            "event": "success",
            "n": attempt_n,
            "duration_ms": sandbox_ms,
            "code": code,
            "meta": meta,
            "summary": result.summary,
            "result_rows": result.result_rows,
            "result_path": result.result_path,
            "preview": preview,
            "staging_path": str(file_path),
        }
        return

    # All attempts exhausted
    yield {
        "event": "give_up",
        "attempts": max_attempts,
        "errors": previous_errors,
        "last_code": last_code,
    }


CLEANER_SYSTEM_PROMPT = """You write Python that turns a MESSY pandas DataFrame into a TIDY one.

Define exactly ONE top-level function:
    def run(df, **params) -> pandas.DataFrame

The input `df` was read from a spreadsheet/table with structural problems — the
real header may NOT be row 0; there may be unit rows or description text mixed
in; columns may be named 'Unnamed: N'; numeric values may be stored as text.

Your job:
- Detect the real header row, promote it to column names, drop rows above it.
- Drop fully-empty rows and columns, and pure description/unit rows.
- Give columns clean names (no 'Unnamed'); coerce numeric-looking columns to numbers (pd.to_numeric(errors='coerce')).
- Return a TIDY DataFrame: one row per observation, one column per variable. Keep ALL real data rows.

Allowed imports: numpy, pandas, re, math. No file/network access, no print().
Reply with ONLY a single ```python fenced code block."""


def _df_preview_text(df: pd.DataFrame, max_rows: int = 15) -> str:
    cols = ", ".join(str(c) for c in df.columns)
    dtypes = ", ".join(f"{c}:{t}" for c, t in df.dtypes.items())
    try:
        body = df.head(max_rows).to_string(max_cols=20)
    except Exception:
        body = str(df.head(max_rows))
    return (f"shape: {df.shape[0]} rows x {df.shape[1]} cols\n"
            f"columns: {cols}\ndtypes: {dtypes}\n\nfirst rows:\n{body}")


async def generate_cleaner_stream(
    *,
    df: pd.DataFrame,
    llm: LLMClient,
    max_attempts: int = 2,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream an AI 'data cleaner': the model writes run(df)->tidy_df, we run it
    in the sandbox against the messy frame, and yield the same step events as
    the parser flow (so the UI can reuse the live-code view)."""
    preview = _df_preview_text(df)
    previous_errors: List[str] = []

    for attempt_n in range(1, max_attempts + 1):
        yield {"event": "attempt_start", "n": attempt_n, "max": max_attempts}

        user_msg = (
            f"Here is the messy table:\n{preview}\n\n"
            "Write run(df, **params) that returns a tidy DataFrame. Return ONLY a "
            "```python``` block."
        )
        if previous_errors:
            user_msg += "\n\nPREVIOUS ATTEMPT FAILED — try a different approach:\n" + previous_errors[-1][:600]

        t0 = time.perf_counter()
        text = ""
        try:
            async for delta in llm.stream(
                [{"role": "system", "content": CLEANER_SYSTEM_PROMPT},
                 {"role": "user", "content": user_msg}],
                temperature=0.2 + 0.15 * (attempt_n - 1), max_tokens=2500,
            ):
                text += delta
                yield {"event": "token", "n": attempt_n, "delta": delta}
        except Exception as e:
            err = f"LLM call failed: {type(e).__name__}: {e}"
            yield {"event": "attempt_failed", "n": attempt_n, "stage": "llm", "error": err}
            previous_errors.append(err)
            continue
        llm_ms = int((time.perf_counter() - t0) * 1000)

        code = _extract_code(text)
        yield {"event": "code_ready", "n": attempt_n, "duration_ms": llm_ms, "code": code, "meta": {}, "size": len(code)}

        validation = validate_algorithm_code(code, mode="algorithm")
        if not validation.ok:
            err = "validation failed: " + "; ".join(validation.errors[:5])
            yield {"event": "attempt_failed", "n": attempt_n, "stage": "validation", "error": err}
            previous_errors.append(err)
            continue
        yield {"event": "validated", "n": attempt_n, "imports": validation.imports}

        t1 = time.perf_counter()
        result = sandbox_executor.execute(code, params={}, input_df=df, save_result=True, mode="algorithm")
        sandbox_ms = int((time.perf_counter() - t1) * 1000)
        if result.status != "ok" or not result.result_path:
            err = result.error or "cleaner did not return a DataFrame"
            yield {"event": "attempt_failed", "n": attempt_n, "stage": "sandbox", "duration_ms": sandbox_ms, "error": err[:1500]}
            previous_errors.append(err)
            continue

        preview_rows: List[Dict[str, Any]] = []
        try:
            out_df = pd.read_parquet(result.result_path)
            preview_rows = out_df.head(10).to_dict(orient="records")
        except Exception:
            pass

        yield {
            "event": "success", "n": attempt_n, "duration_ms": sandbox_ms,
            "code": code, "meta": {}, "summary": result.summary,
            "result_rows": result.result_rows, "result_path": result.result_path,
            "preview": preview_rows,
        }
        return

    yield {"event": "give_up", "attempts": max_attempts, "errors": previous_errors}


async def generate_parser(
    *,
    file_path: Path,
    extension: str,
    llm: LLMClient,
) -> ParserBundle:
    """Non-streaming wrapper kept for back-compat (drains the stream and
    returns the final bundle). Prefer `generate_parser_stream` from the UI."""
    final_event: Optional[Dict[str, Any]] = None
    last_failed_error: str = ""
    async for ev in generate_parser_stream(file_path=file_path, extension=extension, llm=llm):
        if ev.get("event") == "success":
            return ParserBundle(
                code=ev["code"], meta=ev["meta"], status="ok", error="",
                summary=ev.get("summary", {}), duration_ms=ev.get("duration_ms", 0),
                result_rows=ev.get("result_rows", 0), result_path=ev.get("result_path"),
            )
        if ev.get("event") == "give_up":
            final_event = ev
        if ev.get("event") == "attempt_failed":
            last_failed_error = ev.get("error", "")
    return ParserBundle(
        code="", meta={}, status="error",
        error=f"all {final_event['attempts'] if final_event else '?'} attempts failed; last: {last_failed_error[:300]}",
        summary={}, duration_ms=0, result_rows=0, result_path=None,
    )


async def save_adapter(
    session: AsyncSession,
    *,
    owner_id: int,
    extension: str,
    code: str,
    meta: Dict[str, Any],
    sample_size_bytes: int,
    test_report: Dict[str, Any],
) -> FormatAdapter:
    """Persist a verified parser so future uploads of the same extension use it."""
    ext = _normalize_ext(extension)

    # If user already has an adapter for this extension, overwrite (latest wins).
    existing = (await session.execute(
        select(FormatAdapter).where(
            FormatAdapter.owner_id == owner_id, FormatAdapter.extension == ext,
        )
    )).scalar_one_or_none()
    if existing:
        existing.code = code
        existing.name = meta.get("name") or existing.name
        existing.description = meta.get("description") or existing.description
        existing.test_report = test_report
        existing.is_verified = True
        existing.sample_size_bytes = sample_size_bytes
        await session.commit()
        await session.refresh(existing)
        return existing

    adapter = FormatAdapter(
        owner_id=owner_id,
        extension=ext,
        name=meta.get("name") or f"Parser for {ext}",
        description=meta.get("description") or "",
        code=code,
        is_verified=True,
        sample_size_bytes=sample_size_bytes,
        test_report=test_report,
    )
    session.add(adapter)
    await session.commit()
    await session.refresh(adapter)
    return adapter


async def try_saved_adapter(
    session: AsyncSession,
    *,
    owner_id: int,
    extension: str,
    file_path: Path,
) -> Optional[Dict[str, Any]]:
    """Run a previously-saved adapter against a fresh upload. Returns a dict
    with the parsed DataFrame's parquet path + summary, or None if no adapter
    exists / the run failed."""
    ext = _normalize_ext(extension)
    adapter = (await session.execute(
        select(FormatAdapter).where(
            FormatAdapter.owner_id == owner_id, FormatAdapter.extension == ext,
        )
    )).scalar_one_or_none()
    if adapter is None:
        return None

    result = sandbox_executor.execute(
        adapter.code, params={}, input_df=None,
        save_result=True,
        mode="parser", parser_file=str(file_path),
    )
    if result.status != "ok" or not result.result_path:
        return None
    return {
        "adapter_id": adapter.id,
        "adapter_name": adapter.name,
        "result_path": result.result_path,
        "result_rows": result.result_rows,
        "summary": result.summary,
    }


def _normalize_ext(extension: str) -> str:
    e = (extension or "").lower().strip()
    if not e.startswith("."):
        e = "." + e
    return e


def stage_upload(file_bytes: bytes, filename: str, owner_id: int) -> Path:
    """Save a not-yet-ingestable upload to the staging dir, returning the
    absolute path. Used when native parsers fail and we need an LLM-written
    one before promoting to a Dataset."""
    settings = get_settings()
    staging = settings.upload_path / f"user_{owner_id}" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    safe = filename.replace("/", "_").replace("\\", "_")
    out = staging / f"{int(time.time() * 1000)}_{safe}"
    out.write_bytes(file_bytes)
    return out
