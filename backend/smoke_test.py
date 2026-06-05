"""Quick local sanity test — runs the algorithm registry + sandbox end-to-end
without spinning up the HTTP server. Run from backend dir:
    ./.venv/Scripts/python.exe smoke_test.py
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd

from app.algorithms import bootstrap, registry  # noqa: F401
from app.sandbox import executor as sbx


def banner(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> int:
    banner("1. Algorithm registry loaded")
    cats = registry.all_categories()
    specs = registry.list_builtins()
    print(f"  categories: {cats}")
    print(f"  total built-in algorithms: {len(specs)}")
    for s in specs:
        print(f"   - [{s.category}] {s.slug} :: {s.name}")
    if len(specs) < 10:
        print("FAIL: expected at least 10 built-ins")
        return 1

    banner("2. Built-in: linear_regression on synthetic data")
    np.random.seed(0)
    n = 200
    x1 = np.random.randn(n)
    x2 = np.random.randn(n)
    y = 1.5 * x1 - 2.0 * x2 + 0.3 + 0.1 * np.random.randn(n)
    df = pd.DataFrame({"x1": x1, "x2": x2, "y": y})
    r = registry.execute_builtin("linear_regression", df, {"x": ["x1", "x2"], "y": "y"})
    print(json.dumps(r["summary"], indent=2, default=str)[:1500])
    assert r["status"] == "ok", r["error"]
    coeffs = r["summary"]["value"]["coefficients"]
    assert abs(coeffs["x1"] - 1.5) < 0.1
    assert abs(coeffs["x2"] - (-2.0)) < 0.1

    banner("3. Built-in: savgol_filter on noisy sine")
    t = np.linspace(0, 4 * np.pi, 500)
    y_noisy = np.sin(t) + 0.3 * np.random.randn(len(t))
    df = pd.DataFrame({"t": t, "y": y_noisy})
    r = registry.execute_builtin("savgol_filter", df, {"columns": ["y"], "window_length": 31, "polyorder": 3})
    assert r["status"] == "ok", r["error"]
    print(f"  ok, output rows={r['result_rows']}, parquet={r['result_path']}")

    banner("4. Built-in: outlier_detect with Dixon on small sample")
    df = pd.DataFrame({"x": [10.1, 10.2, 10.0, 10.3, 25.0]})  # 25.0 is the outlier
    r = registry.execute_builtin("outlier_detect", df, {"columns": ["x"], "method": "dixon"})
    assert r["status"] == "ok", r["error"]
    print(f"  Dixon flagged: {r['summary']['head'][-1]}")

    banner("5. Built-in: sensitivity (morris) ranks inputs correctly")
    df = pd.DataFrame({
        "a": np.random.randn(500),
        "b": np.random.randn(500),
        "c": np.random.randn(500),
    })
    df["y"] = 5 * df["a"] + 0.1 * df["b"] + 0.0 * df["c"] + 0.05 * np.random.randn(500)
    r = registry.execute_builtin("sensitivity", df, {"inputs": ["a", "b", "c"], "output": "y", "method": "morris"})
    assert r["status"] == "ok", r["error"]
    top = r["summary"]["head"][0]
    print(f"  top input: {top['input']} (norm={top['normalized']:.3f})")
    assert top["input"] == "a"

    banner("6. Sandbox: run a tiny user algorithm")
    user_code = '''
import numpy as np
import pandas as pd

def run(df, *, scale: float = 1.0):
    if df is None:
        raise ValueError("df is required")
    out = df.copy()
    for c in df.select_dtypes(include="number").columns:
        out[c + "_scaled"] = df[c] * scale
    return out
'''
    result = sbx.execute(user_code, {"scale": 2.5}, input_df=pd.DataFrame({"a": [1, 2, 3], "b": [10, 20, 30]}))
    print(f"  status={result.status} duration={result.duration_ms}ms rows={result.result_rows}")
    print(f"  summary: {json.dumps(result.summary, default=str)[:300]}")
    assert result.status == "ok", result.error

    banner("7. Sandbox: reject malicious code at validation time")
    bad_code = '''
import os
def run(df, **kwargs):
    os.system("echo pwn")
    return df
'''
    bad_result = sbx.execute(bad_code, {}, input_df=pd.DataFrame({"a": [1]}))
    print(f"  status={bad_result.status} error={bad_result.error[:200]}")
    assert bad_result.status == "error" and "validation" in bad_result.error.lower()

    banner("8. Sandbox: enforce wall-clock timeout")
    spin_code = '''
def run(df, **kwargs):
    x = 0
    while True:
        x += 1
    return x
'''
    started = time.time()
    spin = sbx.execute(spin_code, {}, input_df=None)
    elapsed = time.time() - started
    print(f"  status={spin.status} elapsed={elapsed:.1f}s error={spin.error[:120]}")
    assert spin.status == "error" and "timeout" in spin.error.lower()

    banner("ALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
