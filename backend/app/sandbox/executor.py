"""Cross-platform sandbox: spawn a Python subprocess, feed it code+data via
stdio, enforce a wall-clock timeout, and parse a delimited JSON result."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from ..core.config import get_settings
from .validator import ValidationResult, validate_algorithm_code

_WORKER = Path(__file__).resolve().parent / "runner_worker.py"
_RESULT_DELIM = "\n__SANDBOX_RESULT__\n"


@dataclass
class ExecutionResult:
    status: str  # "ok" | "error"
    error: str
    duration_ms: int
    summary: Dict[str, Any]
    logs: str
    result_path: Optional[str]
    result_rows: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "summary": self.summary,
            "logs": self.logs,
            "result_path": self.result_path,
            "result_rows": self.result_rows,
        }


class SandboxError(RuntimeError):
    pass


def _spawn(req: Dict[str, Any], workdir: Path, output_path: str,
           save_result: bool, effective_timeout: int) -> ExecutionResult:
    """Run the worker subprocess for an already-built request and parse its
    delimited JSON result. Shared by every sandbox mode (algorithm / parser /
    viz / skill) so timeout, network scrubbing and result handling behave
    identically no matter who is calling."""
    settings = get_settings()
    env = os.environ.copy()
    # Block well-known proxy / network helpers in user code (best-effort)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(_WORKER)],
            input=json.dumps(req).encode("utf-8"),
            capture_output=True,
            timeout=effective_timeout,
            env=env,
            cwd=str(workdir),
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            status="error",
            error=f"timeout after {effective_timeout}s",
            duration_ms=effective_timeout * 1000,
            summary={},
            logs="",
            result_path=None,
            result_rows=0,
        )

    stdout = proc.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stderr = proc.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")

    if _RESULT_DELIM not in stdout:
        return ExecutionResult(
            status="error",
            error=f"worker did not return a result.\nstderr:\n{stderr[:2000]}",
            duration_ms=0,
            summary={},
            logs=stdout[:2000],
            result_path=None,
            result_rows=0,
        )

    _, payload = stdout.rsplit(_RESULT_DELIM, 1)
    try:
        parsed = json.loads(payload.strip())
    except json.JSONDecodeError as e:
        return ExecutionResult(
            status="error",
            error=f"worker returned invalid JSON: {e}",
            duration_ms=0,
            summary={},
            logs=stdout[:2000],
            result_path=None,
            result_rows=0,
        )

    result_path: Optional[str] = None
    if save_result and parsed.get("status") == "ok" and os.path.exists(output_path):
        # Persist the result inside the upload dir so the API can read it later.
        dest = settings.upload_path / "results"
        dest.mkdir(parents=True, exist_ok=True)
        final = dest / f"{Path(workdir).name}.parquet"
        shutil.copy(output_path, final)
        result_path = str(final)

    return ExecutionResult(
        status=parsed.get("status", "error"),
        error=parsed.get("error", ""),
        duration_ms=int(parsed.get("duration_ms", 0)),
        summary=parsed.get("summary") or {},
        logs=parsed.get("logs", ""),
        result_path=result_path,
        result_rows=int(parsed.get("result_rows", 0)),
    )


def execute(
    code: str,
    params: Optional[Dict[str, Any]] = None,
    input_df: Optional[pd.DataFrame] = None,
    *,
    save_result: bool = True,
    mode: str = "algorithm",
    parser_file: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> ExecutionResult:
    """Run user code in a sandboxed subprocess.

    mode='algorithm' : code defines run(df, **params)
    mode='parser'    : code defines parse(path, **kwargs); `parser_file` is
                       the input file the parser opens.

    timeout_seconds  : per-call override of settings.sandbox_timeout_seconds.
                       Used by codegen smoke-tests, which must absorb a cold
                       import of numpy/pandas/sklearn in a fresh subprocess —
                       on Windows that alone can take 30-60 s the first time
                       (AV scanning .pyc files), so the default 30 s is far
                       too tight for unverified AI code.
    """
    settings = get_settings()
    effective_timeout = int(timeout_seconds if timeout_seconds is not None else settings.sandbox_timeout_seconds)

    validation = validate_algorithm_code(code, mode=mode)
    if not validation.ok:
        return ExecutionResult(
            status="error",
            error="validation failed: " + "; ".join(validation.errors),
            duration_ms=0,
            summary={},
            logs="",
            result_path=None,
            result_rows=0,
        )

    workdir = Path(tempfile.mkdtemp(prefix="da_sbox_"))
    try:
        input_path = ""
        if input_df is not None:
            input_path = str(workdir / "input.parquet")
            input_df.to_parquet(input_path, index=False)

        output_path = str(workdir / "output.parquet") if save_result else ""

        req = {
            "mode": mode,
            "code": code,
            "params": params or {},
            "input_path": input_path,
            "output_path": output_path,
            "parser_file": parser_file or "",
            "cpu_seconds": settings.sandbox_cpu_seconds,
            "memory_mb": settings.sandbox_memory_mb,
            "wall_seconds": effective_timeout,
        }

        return _spawn(req, workdir, output_path, save_result, effective_timeout)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def validate(code: str, mode: str = "algorithm") -> ValidationResult:
    return validate_algorithm_code(code, mode=mode)


def execute_skill(
    *,
    pack_dir: str,
    entry_module: str,
    entry_func: str,
    params: Optional[Dict[str, Any]] = None,
    input_df: Optional[pd.DataFrame] = None,
    needs_data: bool = True,
    probe: bool = False,
    save_result: bool = True,
    timeout_seconds: Optional[int] = None,
) -> ExecutionResult:
    """Run one tool from an installed skill pack.

    Unlike `execute()` there is no code STRING to validate here — the pack was
    statically checked file-by-file at install time (see skills/checks.py), and
    what runs is the pack on disk. The worker puts `pack_dir` on sys.path so the
    pack can import its own modules, then calls `entry_module:entry_func`.

    probe=True imports and resolves the entry point WITHOUT calling it — the
    installer uses this to prove a tool is wired up before declaring it verified.
    """
    settings = get_settings()
    effective_timeout = int(timeout_seconds or settings.skill_timeout_seconds)

    workdir = Path(tempfile.mkdtemp(prefix="da_skill_"))
    try:
        input_path = ""
        if input_df is not None:
            input_path = str(workdir / "input.parquet")
            input_df.to_parquet(input_path, index=False)
        output_path = str(workdir / "output.parquet") if save_result else ""

        req: Dict[str, Any] = {
            "mode": "skill",
            "code": "",
            "params": params or {},
            "input_path": input_path,
            "output_path": output_path,
            "pack_dir": str(Path(pack_dir).resolve()),
            "entry_module": entry_module,
            "entry_func": entry_func,
            "needs_data": bool(needs_data),
            "probe": bool(probe),
            "cpu_seconds": max(settings.sandbox_cpu_seconds, effective_timeout),
            "memory_mb": settings.sandbox_memory_mb,
            "wall_seconds": effective_timeout,
        }
        return _spawn(req, workdir, output_path, save_result, effective_timeout)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
