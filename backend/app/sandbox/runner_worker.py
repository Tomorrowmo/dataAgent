"""Worker that runs inside the sandbox subprocess.

Protocol (stdio):
  - parent writes a single JSON line on stdin with: {code, params, input_path, output_path}
  - worker imports the code, calls `run(df, **params)`, writes parquet result
  - worker prints a single JSON line on stdout with: {status, summary, error, logs}

Resource limits are applied here for POSIX (setrlimit). On Windows the parent
process enforces a wall-clock timeout via process.kill().
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict


def _apply_posix_limits(cpu_seconds: int, memory_mb: int) -> None:
    try:
        import resource  # POSIX-only
    except ImportError:
        return
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    except Exception:
        pass
    try:
        bytes_ = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (bytes_, bytes_))
    except Exception:
        pass
    try:
        # Disallow forking new processes from inside user code.
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except Exception:
        pass


def _summarize(obj: Any) -> Dict[str, Any]:
    import numpy as np
    import pandas as pd

    if isinstance(obj, pd.DataFrame):
        return {
            "type": "dataframe",
            "rows": int(len(obj)),
            "columns": list(map(str, obj.columns)),
            "dtypes": {str(c): str(t) for c, t in obj.dtypes.items()},
            "head": json.loads(obj.head(10).to_json(orient="records", date_format="iso")),
        }
    if isinstance(obj, pd.Series):
        return {
            "type": "series",
            "name": str(obj.name),
            "length": int(len(obj)),
            "head": json.loads(obj.head(20).to_json(orient="records", date_format="iso")),
        }
    if isinstance(obj, np.ndarray):
        return {
            "type": "ndarray",
            "shape": list(obj.shape),
            "dtype": str(obj.dtype),
            "preview": obj.flatten()[:20].tolist(),
        }
    if isinstance(obj, dict):
        try:
            return {"type": "dict", "value": json.loads(json.dumps(obj, default=str))}
        except Exception:
            return {"type": "dict", "value": {str(k): str(v) for k, v in obj.items()}}
    if isinstance(obj, (list, tuple)):
        try:
            return {"type": "list", "value": json.loads(json.dumps(list(obj), default=str))}
        except Exception:
            return {"type": "list", "value": [str(x) for x in obj]}
    return {"type": type(obj).__name__, "value": str(obj)[:1000]}


def main() -> int:
    raw = sys.stdin.read()
    req = json.loads(raw)

    mode: str = req.get("mode", "algorithm")  # "algorithm" | "parser"
    code: str = req["code"]
    params: Dict[str, Any] = req.get("params", {}) or {}
    input_path: str = req.get("input_path", "")
    output_path: str = req.get("output_path", "")
    parser_file: str = req.get("parser_file", "")  # input file for parser mode
    cpu_seconds: int = int(req.get("cpu_seconds", 10))
    memory_mb: int = int(req.get("memory_mb", 512))

    _apply_posix_limits(cpu_seconds, memory_mb)

    # Block network — best-effort, the AST validator already disallows `socket`.
    #
    # We CANNOT replace `socket.socket` with a function: ssl.py does
    # `from socket import socket` and then `class SSLSocket(socket):`, and
    # inheriting from a function raises a cryptic
    # "TypeError: function() argument 'code' must be code, not str".
    # That breaks asyncio -> ssl, which breaks joblib, which breaks sklearn,
    # which breaks every AI-generated algorithm that touches sklearn.
    #
    # Instead, leave `socket.socket` as the real class so subclassing works,
    # and only block the methods that actually establish a connection. Plus
    # we replace `socket.create_connection` (a function -> function swap is fine).
    try:
        import socket  # noqa: F401

        def _blocked(*_a, **_kw):
            raise RuntimeError("network access is not allowed in the sandbox")

        socket.socket.connect = _blocked  # type: ignore[assignment]
        socket.socket.connect_ex = _blocked  # type: ignore[assignment]
        socket.create_connection = _blocked  # type: ignore[assignment]
    except Exception:
        pass

    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    started = time.perf_counter()
    status, error = "ok", ""
    summary: Dict[str, Any] = {}
    result_rows = 0

    try:
        import pandas as pd

        df = None
        if input_path and os.path.exists(input_path):
            if input_path.endswith(".parquet"):
                df = pd.read_parquet(input_path)
            elif input_path.endswith(".csv"):
                df = pd.read_csv(input_path)
            elif input_path.endswith(".json"):
                df = pd.read_json(input_path)

        # User code namespace — explicitly minimal builtins
        builtin_names = [
            "abs", "all", "any", "bool", "bytes", "callable", "chr", "complex",
            "dict", "divmod", "enumerate", "filter", "float", "frozenset",
            "hash", "hex", "int", "isinstance", "issubclass", "iter", "len",
            "list", "map", "max", "min", "next", "oct", "ord", "pow", "print",
            "range", "repr", "reversed", "round", "set", "slice", "sorted",
            "str", "sum", "tuple", "type", "zip",
            "True", "False", "None",
            "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
            "ZeroDivisionError", "ArithmeticError", "RuntimeError",
            "memoryview", "bytearray",
            "__import__",  # required so `import numpy as np` works
        ]
        if mode == "parser":
            builtin_names.append("open")  # parsers need to read binary files
        safe_builtins = {
            n: __builtins__[n] if isinstance(__builtins__, dict) else getattr(__builtins__, n)
            for n in builtin_names
        }
        ns: Dict[str, Any] = {"__builtins__": safe_builtins, "__name__": "__sandbox__"}
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compile(code, "<algorithm>", "exec"), ns, ns)
            if mode == "parser":
                if "parse" not in ns or not callable(ns["parse"]):
                    raise RuntimeError("parser must define a top-level `parse(path)` function")
                if not parser_file:
                    raise RuntimeError("parser_file path missing in sandbox request")
                result = ns["parse"](parser_file, **params)
            else:
                if "run" not in ns or not callable(ns["run"]):
                    raise RuntimeError("algorithm must define a top-level `run(df, **params)` function")
                result = ns["run"](df, **params)

        summary = _summarize(result)

        if isinstance(result, pd.DataFrame) and output_path:
            result.to_parquet(output_path, index=False)
            result_rows = int(len(result))
        elif hasattr(result, "to_frame") and output_path:
            result.to_frame().to_parquet(output_path, index=False)
            result_rows = int(len(result))

    except MemoryError:
        status, error = "error", "memory limit exceeded"
    except Exception as e:
        status, error = "error", f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    logs = (stdout_buf.getvalue() + stderr_buf.getvalue())[:200_000]

    sys.stdout.write("\n__SANDBOX_RESULT__\n")
    sys.stdout.write(json.dumps({
        "status": status,
        "error": error,
        "duration_ms": duration_ms,
        "summary": summary,
        "logs": logs,
        "result_rows": result_rows,
    }, default=str))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
