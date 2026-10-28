#!/usr/bin/env python
"""算法 CLI 化 —— 验收脚本。

用法(在 backend 目录下跑,用 venv 的 python):

    ./.venv/Scripts/python.exe ../tools/verify_cli.py
    ./.venv/Scripts/python.exe ../tools/verify_cli.py --baseline 网页端导出的.csv

被验收的 CLI 约定接口:
    python -m app.cli list
    python -m app.cli describe <slug>
    python -m app.cli run <slug> --in <路径|-> --out <路径|-> [--param k=v ...]

这个脚本不依赖后端服务、不依赖数据库、不需要 LLM key —— 因为被测的 CLI 也不该依赖。
每项检查独立,一项失败不影响后面继续跑,最后出汇总表。
标 [红线] 的项目失败 = 本任务判不通过。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BACKEND = REPO / "backend"

# 用来做检查的算法:滤波类,行数不变、会新增一列,好断言。
SLUG = "savgol_filter"
PARAMS = ["window=11", "polyorder=3"]

results: List[Tuple[str, bool, bool, str]] = []  # (名称, 通过, 是否红线, 说明)


def record(name: str, ok: bool, note: str = "", redline: bool = False) -> None:
    results.append((name, ok, redline, note))
    mark = "PASS" if ok else ("FAIL[红线]" if redline else "FAIL")
    print(f"  [{mark}] {name}" + (f" — {note}" if note else ""))


def run_cli(
    args: List[str],
    *,
    stdin_data: Optional[bytes] = None,
    env_overrides: Optional[dict] = None,
    cli_cmd: List[str],
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(env_overrides or {})
    return subprocess.run(
        cli_cmd + args,
        cwd=str(BACKEND),
        input=stdin_data,
        capture_output=True,
        env=env,
        timeout=180,
    )


def make_fixture(path: Path) -> pd.DataFrame:
    """确定性的测试数据 —— 固定种子,每次跑都一样。"""
    rng = np.random.default_rng(20260810)
    n = 500
    t = np.linspace(0, 20, n)
    df = pd.DataFrame({
        "t": t,
        "signal": np.sin(t) + 0.15 * rng.standard_normal(n),
        "temp_c": 25 + 0.02 * t + 0.05 * rng.standard_normal(n),
        "label": ["a", "b"] * (n // 2),
    })
    df.to_csv(path, index=False)
    return df


def snapshot(d: Path) -> set:
    return set(p.name for p in d.iterdir()) if d.is_dir() else set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", default="python -m app.cli",
                    help="CLI 调用命令(默认 'python -m app.cli')")
    ap.add_argument("--baseline", default=None,
                    help="网页端对同一数据、同一参数导出的 CSV,用于一致性比对")
    ap.add_argument("--source", default="backend/app/cli.py",
                    help="CLI 源码路径,用于薄壳检查(可以是目录)")
    args = ap.parse_args()

    cli_cmd = args.cli.split()
    # 用当前解释器替换裸 'python',保证走的是同一个 venv
    if cli_cmd and cli_cmd[0] == "python":
        cli_cmd[0] = sys.executable

    tmp = Path(tempfile.mkdtemp(prefix="verify_cli_"))
    src_csv = tmp / "demo.csv"
    df_in = make_fixture(src_csv)
    results_dir = BACKEND / "data" / "uploads" / "results"
    before = snapshot(results_dir)

    print(f"\n工作目录: {BACKEND}")
    print(f"测试数据: {src_csv}  ({len(df_in)} 行 × {df_in.shape[1]} 列)")
    print(f"CLI 命令: {' '.join(cli_cmd)}\n")
    print("=" * 72)

    # ---------------------------------------------------------------- 1. list
    print("\n[1] 基本命令")
    p = run_cli(["list"], cli_cmd=cli_cmd)
    out = p.stdout.decode("utf-8", "replace")
    n_slugs = sum(1 for s in ("savgol_filter", "moving_average", "pca",
                              "linear_regression", "normalize", "find_peaks")
                  if s in out)
    record("list 退出码为 0", p.returncode == 0, f"退出码={p.returncode}")
    record("list 列出了内置算法", n_slugs >= 5, f"已知算法命中 {n_slugs}/6")

    p = run_cli(["describe", SLUG], cli_cmd=cli_cmd)
    out = p.stdout.decode("utf-8", "replace")
    record("describe 退出码为 0", p.returncode == 0, f"退出码={p.returncode}")
    record("describe 打印了参数名", "window" in out and "polyorder" in out)

    # ------------------------------------------------------------- 2. 正常执行
    print("\n[2] 正常执行")
    out_csv = tmp / "out.csv"
    argv = ["run", SLUG, "--in", str(src_csv), "--out", str(out_csv)]
    for kv in PARAMS:
        argv += ["--param", kv]
    p = run_cli(argv, cli_cmd=cli_cmd)
    ok_run = p.returncode == 0 and out_csv.exists()
    record("run 退出码为 0 且产出文件存在", ok_run,
           f"退出码={p.returncode} stderr={p.stderr.decode('utf-8','replace')[:120]}")

    df_out = None
    if out_csv.exists():
        df_out = pd.read_csv(out_csv)
        record("行数保持不变", len(df_out) == len(df_in),
               f"{len(df_in)} → {len(df_out)}")
        new_cols = [c for c in df_out.columns if c not in df_in.columns]
        record("产生了新列(滤波结果)", len(new_cols) >= 1, f"新列={new_cols}")
        record("原始列没被丢掉",
               all(c in df_out.columns for c in df_in.columns))

    # ---------------------------------------------- 3. 脱离服务器/数据库/密钥 [红线]
    print("\n[3] 独立运行 [红线]")
    out2 = tmp / "out_isolated.csv"
    argv2 = ["run", SLUG, "--in", str(src_csv), "--out", str(out2)]
    for kv in PARAMS:
        argv2 += ["--param", kv]
    p = run_cli(argv2, cli_cmd=cli_cmd, env_overrides={
        "DEEPSEEK_API_KEY": "",
        "OPENAI_API_KEY": "",
        # 指向一个不存在的目录 —— 一旦 CLI 真去连库就会炸
        "DATABASE_URL": "sqlite+aiosqlite:////nonexistent/nope/x.db",
    })
    record("无 LLM key + 数据库不可用时仍能执行", p.returncode == 0 and out2.exists(),
           f"退出码={p.returncode} stderr={p.stderr.decode('utf-8','replace')[:160]}",
           redline=True)

    # ------------------------------------------------------- 4. 与网页端一致 [红线]
    print("\n[4] 与网页端结果一致 [红线]")
    if args.baseline and df_out is not None:
        base = pd.read_csv(args.baseline)
        same_shape = base.shape == df_out.shape
        same_cols = list(base.columns) == list(df_out.columns)
        same_vals = False
        if same_shape and same_cols:
            num = base.select_dtypes(include=[np.number]).columns
            same_vals = (
                np.allclose(base[num].values, df_out[num].values,
                            rtol=0, atol=1e-9, equal_nan=True)
                and base.drop(columns=list(num)).equals(
                    df_out.drop(columns=list(num)))
            )
        record("CLI 结果与网页端导出完全一致", same_shape and same_cols and same_vals,
               f"shape {base.shape} vs {df_out.shape}, 列一致={same_cols}",
               redline=True)
    else:
        record("CLI 结果与网页端导出完全一致", False,
               "未提供 --baseline,请在网页端用同样的数据和参数导出 CSV 后重跑",
               redline=True)

    # -------------------------------------------------------- 5. 失败必须失败 [红线]
    print("\n[5] 错误处理 [红线]")
    bad = ["run", SLUG, "--in", str(src_csv), "--out", str(tmp / "bad.csv"),
           "--param", "window=2", "--param", "polyorder=3"]  # window < polyorder,非法
    p = run_cli(bad, cli_cmd=cli_cmd)
    msg = (p.stderr + p.stdout).decode("utf-8", "replace")
    record("非法参数 → 非零退出码", p.returncode != 0,
           f"退出码={p.returncode}", redline=True)
    record("非法参数 → 报错里提到了出问题的参数",
           "window" in msg.lower() or "polyorder" in msg.lower(),
           f"报错前120字: {msg.strip()[:120]}")
    record("非法参数 → 不产出结果文件", not (tmp / "bad.csv").exists(),
           redline=True)

    p = run_cli(["run", "不存在的算法", "--in", str(src_csv),
                 "--out", str(tmp / "x.csv")], cli_cmd=cli_cmd)
    record("未知算法名 → 非零退出码", p.returncode != 0,
           f"退出码={p.returncode}", redline=True)

    p = run_cli(["run", SLUG, "--in", str(tmp / "根本没这个文件.csv"),
                 "--out", str(tmp / "y.csv")], cli_cmd=cli_cmd)
    record("输入文件不存在 → 非零退出码", p.returncode != 0, f"退出码={p.returncode}")

    # ------------------------------------------------------------- 6. 管道
    print("\n[6] 标准输入输出 / 管道")
    p1 = run_cli(["run", "normalize", "--in", "-", "--out", "-"],
                 stdin_data=src_csv.read_bytes(), cli_cmd=cli_cmd)
    ok1 = p1.returncode == 0 and len(p1.stdout) > 0
    record("stdin → stdout 单级可用", ok1, f"退出码={p1.returncode}")
    if ok1:
        p2 = run_cli(["run", "moving_average", "--in", "-", "--out", "-",
                      "--param", "window=5"],
                     stdin_data=p1.stdout, cli_cmd=cli_cmd)
        ok2 = p2.returncode == 0 and len(p2.stdout) > 0
        record("两级管道串联可用", ok2, f"退出码={p2.returncode}")
        if ok2:
            try:
                import io
                dfp = pd.read_csv(io.BytesIO(p2.stdout))
                record("管道输出是合法 CSV 且行数正确", len(dfp) == len(df_in),
                       f"{len(dfp)} 行")
            except Exception as e:
                record("管道输出是合法 CSV 且行数正确", False, f"{type(e).__name__}: {e}")
        # stdout 模式下不许把日志混进数据
        first = p1.stdout.decode("utf-8", "replace").splitlines()[:1]
        record("--out - 时 stdout 只有数据、没有日志",
               bool(first) and "," in first[0] and "INFO" not in first[0].upper(),
               f"首行: {first[0][:80] if first else '(空)'}")

    # ------------------------------------------------------------- 7. 确定性
    print("\n[7] 可重复")
    out3 = tmp / "out_again.csv"
    argv3 = ["run", SLUG, "--in", str(src_csv), "--out", str(out3)]
    for kv in PARAMS:
        argv3 += ["--param", kv]
    run_cli(argv3, cli_cmd=cli_cmd)
    if out_csv.exists() and out3.exists():
        record("两次运行结果逐字节相同",
               out_csv.read_bytes() == out3.read_bytes())

    # --------------------------------------------------- 8. 薄壳检查 [红线]
    print("\n[8] 薄壳检查 [红线] —— CLI 不许自己实现算法")
    srcp = REPO / args.source
    files = ([p for p in srcp.rglob("*.py")] if srcp.is_dir()
             else ([srcp] if srcp.exists() else []))
    if not files:
        record("找到 CLI 源码", False, f"{srcp} 不存在,用 --source 指定")
    else:
        text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files)
        loc = sum(1 for ln in text.splitlines() if ln.strip()
                  and not ln.strip().startswith("#"))
        banned = [m for m in ("scipy", "sklearn", "statsmodels")
                  if f"import {m}" in text or f"from {m}" in text]
        record("CLI 里没有 scipy/sklearn/statsmodels", not banned,
               f"发现: {banned}", redline=True)
        record("CLI 调用了 registry(而不是复制实现)",
               "execute_builtin" in text or "registry" in text,
               redline=True)
        record("CLI 体量是薄壳(有效行 < 400)", loc < 400, f"{loc} 行")

    # ------------------------------------------- 9. 不往数据目录里丢垃圾
    print("\n[9] 副作用")
    after = snapshot(results_dir)
    leaked = after - before
    record("没有在 data/uploads/results 里留下临时文件", not leaked,
           f"新增 {len(leaked)} 个: {sorted(leaked)[:3]}")

    # ---------------------------------------------------------------- 汇总
    print("\n" + "=" * 72)
    total = len(results)
    passed = sum(1 for _, ok, _, _ in results if ok)
    red_fail = [n for n, ok, red, _ in results if red and not ok]
    print(f"通过 {passed}/{total}")
    if red_fail:
        print(f"\n❌ 红线未通过 {len(red_fail)} 项 —— 本任务判不通过:")
        for n in red_fail:
            print(f"   · {n}")
    elif passed < total:
        print("\n⚠ 红线全过,但有非红线项失败,让他修完再合并:")
        for n, ok, _, note in results:
            if not ok:
                print(f"   · {n}" + (f" — {note}" if note else ""))
    else:
        print("\n✅ 全部通过")

    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if red_fail else 0


if __name__ == "__main__":
    sys.exit(main())
