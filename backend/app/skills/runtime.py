"""Execute a skill pack's tool and return a result shaped like every other tool
result in the app (status / error / duration_ms / summary / logs / result_path /
result_rows), so the chat agent, the REST API and template replay never have to
branch on where a tool came from.

Two runtimes:

  python  — `entry: module:function` inside the pack, run in the sandbox
            subprocess (network blocked, wall-clock timeout, pack root on
            sys.path so it can import its own modules).
  command — the pack ships its own executable/script; we hand it the input as a
            file and read the output back from a file. Nothing about that code
            can be checked statically, so it is gated: SKILLS_ALLOW_COMMAND_RUNTIME
            must be on AND the installer marks the pack trust="command".
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from ..algorithms.registry import coerce_params
from ..core.config import get_settings
from ..sandbox import executor as sandbox_executor

_PLACEHOLDER_HELP = (
    "command 可用的占位符:{input}(输入数据 parquet)、{input_csv}(同一份数据的 csv)、"
    "{output}(工具应把结果写到这里,支持 .parquet/.csv/.json)、{params_json}(参数 json 文件)、"
    "{pack}(技能包根目录)"
)


def _error(msg: str, *, logs: str = "", duration_ms: int = 0) -> Dict[str, Any]:
    return {
        "status": "error", "error": msg, "duration_ms": duration_ms,
        "summary": {}, "logs": logs, "result_path": None, "result_rows": 0,
    }


def _missing_required(tool: Dict[str, Any], params: Dict[str, Any]) -> Optional[str]:
    schema = tool.get("params_schema") or {}
    missing = [
        n for n, ps in schema.items()
        if isinstance(ps, dict) and ps.get("required") and n not in (params or {})
        and "default" not in ps
    ]
    if not missing:
        return None
    return (
        f"缺少必填参数:{'、'.join(missing)}。"
        f"这个工具的参数是:{'、'.join(schema.keys()) or '(无)'}"
    )


def _apply_defaults(tool: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(params or {})
    for name, ps in (tool.get("params_schema") or {}).items():
        if isinstance(ps, dict) and name not in out and "default" in ps:
            out[name] = ps["default"]
    return out


def _clean_error(result: Dict[str, Any], df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """把 traceback 从错误信息里拆走。

    技能包工具抛的异常信息通常是作者精心写的人话("数据里没有这些列:…,实际有:…"),
    但沙箱把整个 traceback 一起塞进了 error,于是用户看到的第一屏是 20 行文件路径。
    这里只留第一段人话给用户/AI,traceback 挪进 logs(界面上折叠着,排查时才看)。
    """
    if result.get("status") != "error":
        return result
    raw = str(result.get("error") or "")
    head = raw.split("Traceback (most recent call last):", 1)[0].strip() or raw[:300]
    # 去掉 "SomeError: " 这层对用户没意义的类名前缀(作者自定义异常尤其明显)
    head = re.sub(r"^[A-Za-z_][A-Za-z0-9_.]*Error:\s*", "", head).strip() or head
    if head != raw:
        result["error"] = head[:1200]
        result["logs"] = (raw + "\n" + str(result.get("logs") or ""))[:200_000]
    if df is not None and ("列" in head or "column" in head.lower()):
        result.setdefault("hint", "")
        cols = "、".join(str(c) for c in list(df.columns)[:20])
        result["hint"] = (result["hint"] + f" 这份数据实际的列是:{cols}。"
                          "换一份对得上的数据,或把参数改成真实列名。").strip()
    return result


def run_tool(
    *,
    root: str,
    tool: Dict[str, Any],
    df: Optional[pd.DataFrame],
    params: Optional[Dict[str, Any]] = None,
    allow_command: Optional[bool] = None,
) -> Dict[str, Any]:
    """Run one tool of an installed pack. `tool` is the normalized spec dict
    stored on the SkillPack row."""
    settings = get_settings()
    pack_dir = Path(root)
    if not pack_dir.is_dir():
        return _error(f"技能包目录不存在:{root}(可能被移动或删除了,请重新安装)")

    params = _apply_defaults(tool, params or {})
    # Same container-slip healing the builtin registry does: the LLM writes
    # `columns: "signal"` when the tool wants `["signal"]`.
    params = coerce_params(tool.get("params_schema") or {}, params)
    miss = _missing_required(tool, params)
    if miss:
        return _error(miss)

    needs_data = bool(tool.get("needs_data", True))
    if needs_data and df is None:
        return _error("这个工具需要一份数据才能运行 —— 请先让用户上传或选择一个数据集。")

    runtime = (tool.get("runtime") or "python").lower()
    timeout = tool.get("timeout_seconds") or settings.skill_timeout_seconds

    if runtime == "python":
        module, _, func = (tool.get("entry") or "").partition(":")
        if not module or not func:
            return _error(f"工具 `{tool.get('name')}` 的 entry 不合法:{tool.get('entry')!r}")
        res = sandbox_executor.execute_skill(
            pack_dir=str(pack_dir),
            entry_module=module,
            entry_func=func,
            params=params,
            input_df=df if needs_data else None,
            needs_data=needs_data,
            timeout_seconds=int(timeout),
        )
        return _clean_error(res.to_dict(), df)

    if runtime == "script":
        # 通用 skill 包:SKILL.md 里写着"运行 scripts/xxx.py",这里如实照做。
        allow = settings.skills_allow_command_runtime if allow_command is None else allow_command
        if not allow:
            return _error(
                "这一步要运行技能包自带的脚本,而服务端没有开启该能力。"
                "管理员在配置里打开 SKILLS_ALLOW_COMMAND_RUNTIME=true 并重启后端即可。"
                "(这个包的知识部分不受影响,AI 仍然能读它的 SKILL.md。)"
            )
        return _run_script(pack_dir, params, df, int(timeout))

    if runtime == "command":
        allow = settings.skills_allow_command_runtime if allow_command is None else allow_command
        if not allow:
            return _error(
                "这个工具要直接运行技能包自带的可执行程序(runtime: command),"
                "而服务端没有开启该能力。管理员可在配置里打开 SKILLS_ALLOW_COMMAND_RUNTIME=true "
                "后重启后端 —— 打开前请确认这个包的来源可信:自带程序不受静态检查约束。"
            )
        return _run_command(pack_dir, tool, df, params, int(timeout))

    return _error(f"未知的 runtime:{runtime}")



# ── script runtime(通用 skill 包)──────────────────────────────────────────
# 通用包的脚本不遵守本系统的 --in/--out 约定:它们是给"有 shell 的 agent"写的,
# 结果通常打在 stdout 上,顺带可能写出文件。所以这里就按那个真实用法来:
# 跑它、把 stdout 原样带回、把它写出的表格文件读回来。

_TEXT_CAP = 24000


def _run_script(pack_dir: Path, params: Dict[str, Any], df: Optional[pd.DataFrame],
                timeout: int) -> Dict[str, Any]:
    settings = get_settings()
    rel = str(params.get("script") or "").strip().replace("\\", "/")
    if not rel:
        return _error("没说要跑哪个脚本。script 参数填包内相对路径,例如 scripts/search.py")

    target = (pack_dir / rel).resolve()
    root = pack_dir.resolve()
    if root != target and root not in target.parents:
        return _error(f"脚本路径越界:{rel} —— 只能运行技能包目录内的脚本。")
    if not target.is_file():
        return _error(f"包里没有这个脚本:{rel}")
    if target.suffix.lower() != ".py":
        return _error(f"目前只能运行包内的 .py 脚本(收到 {target.name})。")

    raw_args = params.get("args") or []
    if isinstance(raw_args, str):
        raw_args = [raw_args]
    args = [str(a) for a in raw_args]

    workdir = Path(tempfile.mkdtemp(prefix="da_skillscript_"))
    started = time.perf_counter()
    try:
        # 脚本可能想读当前数据 —— 给它一份 csv,并通过环境变量告诉它在哪。
        input_csv = ""
        if df is not None:
            input_csv = str(workdir / "input.csv")
            df.to_csv(input_csv, index=False)
        mapping = {"input_csv": input_csv, "output_dir": str(workdir), "pack": str(root)}
        args = [_fill(a, mapping) for a in args]

        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(root),
            "SKILL_PACK_DIR": str(root),
            "SKILL_OUTPUT_DIR": str(workdir),
            "SKILL_INPUT_CSV": input_csv,
        }
        proc = subprocess.run(
            [sys.executable, str(target), *args],
            cwd=str(root), env=env, capture_output=True, timeout=timeout, shell=False,
            input=(str(params["stdin"]).encode("utf-8") if params.get("stdin") else None),
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.perf_counter() - started) * 1000)

        if proc.returncode != 0:
            tail = (stderr or stdout).strip().splitlines()
            msg = "\n".join(tail[-6:]) if tail else "(脚本没有任何输出)"
            return _error(f"脚本 {rel} 退出码 {proc.returncode}:\n{msg}",
                          logs=(stdout + stderr)[:200_000], duration_ms=duration_ms)

        # 脚本写出来的表格,读回来接进流水线
        produced = [q for q in sorted(workdir.rglob("*"))
                    if q.is_file() and q.suffix.lower() in (".csv", ".parquet", ".json", ".md")]
        table: Optional[pd.DataFrame] = None
        for q in produced:
            if q.suffix.lower() in (".csv", ".parquet"):
                try:
                    table = pd.read_csv(q) if q.suffix.lower() == ".csv" else pd.read_parquet(q)
                    break
                except Exception:
                    continue

        result_path, result_rows = None, 0
        if table is not None:
            dest = settings.upload_path / "results"
            dest.mkdir(parents=True, exist_ok=True)
            final = dest / f"skillscript_{workdir.name}.parquet"
            table.to_parquet(final, index=False)
            result_path, result_rows = str(final), int(len(table))

        summary: Dict[str, Any] = {
            "type": "script_output",
            "script": rel,
            "args": args,
            "stdout": stdout[:_TEXT_CAP],
            "stdout_truncated": len(stdout) > _TEXT_CAP,
            "files": [str(q.relative_to(workdir)).replace("\\", "/") for q in produced],
        }
        if table is not None:
            summary["table"] = {
                "rows": int(len(table)),
                "columns": [str(c) for c in table.columns],
                "head": json.loads(table.head(10).to_json(orient="records", date_format="iso")),
            }
        if not stdout.strip() and table is None:
            summary["note"] = "脚本跑完了,但既没有输出也没写出文件 —— 确认一下参数是不是对的。"

        return {
            "status": "ok", "error": "", "duration_ms": duration_ms,
            "summary": summary, "logs": (stdout + stderr)[:200_000],
            "result_path": result_path, "result_rows": result_rows,
        }
    except subprocess.TimeoutExpired:
        return _error(f"脚本 {rel} 超时({timeout}s)没结束。", duration_ms=timeout * 1000)
    except Exception as e:  # noqa: BLE001
        return _error(f"{type(e).__name__}: {e}", logs=traceback.format_exc()[:8000])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _fill(token: str, mapping: Dict[str, str]) -> str:
    for key, val in mapping.items():
        token = token.replace("{" + key + "}", val)
    return token


# ── command runtime ──────────────────────────────────────────────────────────

def _read_output(path: Path) -> Any:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in (".csv", ".txt"):
        return pd.read_csv(path)
    if suffix == ".json":
        text = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(text)
        if isinstance(data, list):
            try:
                return pd.DataFrame(data)
            except Exception:
                return data
        return data
    if suffix in (".md", ".markdown"):
        return {"markdown": path.read_text(encoding="utf-8", errors="replace")}
    raise ValueError(f"不认识的输出文件类型:{path.name}(支持 .parquet/.csv/.json/.md)")


def _summarize(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, pd.DataFrame):
        return {
            "type": "dataframe",
            "rows": int(len(obj)),
            "columns": [str(c) for c in obj.columns],
            "dtypes": {str(c): str(t) for c, t in obj.dtypes.items()},
            "head": json.loads(obj.head(10).to_json(orient="records", date_format="iso")),
        }
    if isinstance(obj, dict):
        return {"type": "dict", "value": json.loads(json.dumps(obj, default=str))}
    if isinstance(obj, list):
        return {"type": "list", "value": json.loads(json.dumps(obj, default=str))}
    return {"type": type(obj).__name__, "value": str(obj)[:1000]}


def _run_command(pack_dir: Path, tool: Dict[str, Any], df: Optional[pd.DataFrame],
                 params: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    settings = get_settings()
    workdir = Path(tempfile.mkdtemp(prefix="da_skillcmd_"))
    started = time.perf_counter()
    try:
        in_parquet = workdir / "input.parquet"
        in_csv = workdir / "input.csv"
        params_json = workdir / "params.json"
        if df is not None:
            df.to_parquet(in_parquet, index=False)
            df.to_csv(in_csv, index=False)
        params_json.write_text(json.dumps(params, ensure_ascii=False, default=str), encoding="utf-8")

        # The output extension is the author's choice; default parquet.
        out_name = str(tool.get("output_file") or "output.parquet")
        out_path = workdir / out_name

        mapping = {
            "input": str(in_parquet), "input_csv": str(in_csv),
            "output": str(out_path), "params_json": str(params_json),
            "pack": str(pack_dir),
        }
        argv: list[str] = []
        for raw in tool.get("command") or []:
            token = str(raw)
            for key, val in mapping.items():
                token = token.replace("{" + key + "}", val)
            # a bare `python` means THIS interpreter, not whatever is on PATH
            if not argv and token in ("python", "python3", "py"):
                token = sys.executable
            argv.append(token)
        if not argv:
            return _error("command 为空。" + _PLACEHOLDER_HELP)

        # Resolve a pack-relative script/executable to an absolute path so the
        # command works regardless of cwd, and never resolves to something
        # outside the pack.
        for i, token in enumerate(argv[1:], start=1):
            cand = (pack_dir / token)
            if cand.exists() and pack_dir.resolve() in cand.resolve().parents:
                argv[i] = str(cand.resolve())

        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "SKILL_PACK_DIR": str(pack_dir),
            "SKILL_PARAMS": str(params_json),
        }
        proc = subprocess.run(
            argv, cwd=str(pack_dir), env=env, capture_output=True,
            timeout=timeout, shell=False,
        )
        logs = (proc.stdout.decode("utf-8", errors="replace")
                + proc.stderr.decode("utf-8", errors="replace"))[:200_000]
        duration_ms = int((time.perf_counter() - started) * 1000)

        if proc.returncode != 0:
            return _error(
                f"技能包自带程序退出码 {proc.returncode}。最后的输出:"
                + (logs[-600:] or "(没有任何输出)"),
                logs=logs, duration_ms=duration_ms,
            )
        if not out_path.exists():
            return _error(
                f"程序跑完了但没有写出结果文件 {out_name} —— 它必须把结果写到 {{output}} 指向的路径。"
                + _PLACEHOLDER_HELP,
                logs=logs, duration_ms=duration_ms,
            )

        result = _read_output(out_path)
        result_path = None
        result_rows = 0
        if isinstance(result, pd.DataFrame):
            dest = settings.upload_path / "results"
            dest.mkdir(parents=True, exist_ok=True)
            final = dest / f"skillcmd_{workdir.name}.parquet"
            result.to_parquet(final, index=False)
            result_path = str(final)
            result_rows = int(len(result))
        return {
            "status": "ok", "error": "", "duration_ms": duration_ms,
            "summary": _summarize(result), "logs": logs,
            "result_path": result_path, "result_rows": result_rows,
        }
    except subprocess.TimeoutExpired:
        return _error(f"超时({timeout}s)——技能包自带程序没有在限定时间内结束。",
                      duration_ms=timeout * 1000)
    except FileNotFoundError as e:
        return _error(f"找不到要执行的程序:{e}。检查 command 第一项是否是包内的脚本或系统里的可执行文件。")
    except Exception as e:  # noqa: BLE001
        return _error(f"{type(e).__name__}: {e}", logs=traceback.format_exc()[:8000])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
