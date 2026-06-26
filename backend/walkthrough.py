"""RLab Cortex end-to-end walkthrough on a real battery-test dataset.

Replays the full agent trajectory — schema discovery → registry lookup →
built-in algorithm → wrong-slug recovery → built-in IQR outlier detection →
codegen for a NOT-in-catalog request → self-healing on a missing-import
failure → sandboxed execution — using a FakeLLM so no DeepSeek key is needed.

This is the "one example I can actually watch go through" demo. Run from the
backend directory:
    ./.venv/Scripts/python.exe walkthrough.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from app.algorithms import bootstrap, registry  # noqa: F401  (bootstrap registers builtins)
from app.sandbox import executor as sbx
from app.services import codegen


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

DATA_PARQUET = Path("data/uploads/user_1/test_data_1779981019673.parquet")


def banner(n: int, title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  STEP {n}: {title}")
    print("=" * 72)


def show(label: str, value: Any, *, indent: int = 2) -> None:
    pad = " " * indent
    if isinstance(value, dict):
        print(f"{pad}{label}:")
        for k, v in value.items():
            print(f"{pad}  {k}: {v}")
    elif isinstance(value, list):
        print(f"{pad}{label}: {value}")
    else:
        print(f"{pad}{label}: {value}")


# A FakeLLM that returns canned replies, one per chat() call. We use it to
# drive the codegen step deterministically and to demonstrate that the
# self-healing retry loop recovers from a real failure mode (missing import).
class FakeLLM:
    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.calls = 0

    @property
    def is_configured(self) -> bool:
        return True

    async def chat(self, messages, *, temperature=0.2, max_tokens=4000, json_mode=False) -> str:
        self.calls += 1
        if not self.responses:
            raise RuntimeError("FakeLLM out of canned responses")
        return self.responses.pop(0)


def _wrap(code: str) -> str:
    return f"```python\n{code.strip()}\n```"


# ---------------------------------------------------------------------------
#  Canned LLM responses — first one is broken (forgot `import pandas as pd`),
#  second one is corrected. The retry loop should fix the first attempt.
# ---------------------------------------------------------------------------

BROKEN_CODE = """
META = {
    "name": "Cumulative capacity (Ah)",
    "slug": "cumulative_capacity",
    "category": "custom",
    "description": "Integrate current over time (trapezoidal) to produce cumulative capacity in Ah.",
    "params_schema": {
        "time_col":    {"type": "string", "default": "time_s",    "description": "Time column (seconds)"},
        "current_col": {"type": "string", "default": "current_a", "description": "Current column (amperes)"},
    },
    "returns": "dataframe",
    "tags": ["battery", "integration"],
}

def run(df, *, time_col="time_s", current_col="current_a"):
    if df is None:
        raise ValueError("df is required")
    if time_col not in df.columns or current_col not in df.columns:
        raise ValueError(f"missing column(s): need {time_col} and {current_col}")
    t = df[time_col].to_numpy()
    i = df[current_col].to_numpy()
    # Trapezoidal integral of i dt, converted from A*s to Ah
    cum_as = np.zeros_like(i, dtype=float)
    cum_as[1:] = np.cumsum(0.5 * (i[1:] + i[:-1]) * (t[1:] - t[:-1]))
    out = df.copy()
    out["capacity_ah"] = cum_as / 3600.0
    return out

# NB: forgot `import pandas as pd` and `import numpy as np` at the top.
test_cases = [
    {"df": pd.DataFrame({"time_s": [0, 1, 2, 3], "current_a": [1.0, 1.0, 1.0, 1.0]}), "params": {}},
]
"""

FIXED_CODE = """
import numpy as np
import pandas as pd

META = {
    "name": "Cumulative capacity (Ah)",
    "slug": "cumulative_capacity",
    "category": "custom",
    "description": "Integrate current over time (trapezoidal) to produce cumulative capacity in Ah.",
    "params_schema": {
        "time_col":    {"type": "string", "default": "time_s",    "description": "Time column (seconds)"},
        "current_col": {"type": "string", "default": "current_a", "description": "Current column (amperes)"},
    },
    "returns": "dataframe",
    "tags": ["battery", "integration"],
}

def run(df, *, time_col="time_s", current_col="current_a"):
    if df is None:
        raise ValueError("df is required")
    if time_col not in df.columns or current_col not in df.columns:
        raise ValueError(f"missing column(s): need {time_col} and {current_col}")
    t = df[time_col].to_numpy()
    i = df[current_col].to_numpy()
    cum_as = np.zeros_like(i, dtype=float)
    cum_as[1:] = np.cumsum(0.5 * (i[1:] + i[:-1]) * (t[1:] - t[:-1]))
    out = df.copy()
    out["capacity_ah"] = cum_as / 3600.0
    return out

test_cases = [
    {"df": pd.DataFrame({"time_s": [0.0, 1.0, 2.0, 3.0], "current_a": [1.0, 1.0, 1.0, 1.0]}), "params": {}},
]
"""


# ---------------------------------------------------------------------------
#  The walkthrough
# ---------------------------------------------------------------------------

async def main() -> int:
    # ---------- 1. Load the dataset ------------------------------------------------
    banner(1, "Load real battery-test dataset (500 rows, 4 cols)")
    if not DATA_PARQUET.exists():
        print(f"  [FAIL] missing test dataset at {DATA_PARQUET}")
        return 1
    df = pd.read_parquet(DATA_PARQUET)
    print(f"  loaded {len(df)} rows x {len(df.columns)} cols")
    print(f"  columns: {list(df.columns)}")
    print(f"  time range: {df['time_s'].min():.3f}s -> {df['time_s'].max():.3f}s")
    print(f"  voltage range: {df['voltage_v'].min():.3f}V -> {df['voltage_v'].max():.3f}V")
    print(f"  temp range: {df['temp_c'].min():.2f}C -> {df['temp_c'].max():.2f}C")

    # ---------- 2. Tool discovery -------------------------------------------------
    banner(2, "Agent discovers available tools via registry")
    specs = registry.list_builtins(category="regression")
    print(f"  found {len(specs)} regression tools:")
    for s in specs:
        print(f"   - {s.slug:<24}  {s.description[:60]}")

    # ---------- 3. Polynomial regression, degree 2 --------------------------------
    banner(3, "Run polynomial_regression on temp_c ~ time_s, degree=2")
    r2 = registry.execute_builtin(
        "polynomial_regression", df,
        {"x": "time_s", "y": "temp_c", "degree": 2},
    )
    assert r2["status"] == "ok", r2["error"]
    s2 = r2["summary"]["value"]
    coeffs2 = s2["coefficients"]  # highest order first: c2*x^2 + c1*x + c0
    show("R^2",          f"{s2['r_squared']:.6f}")
    show("RMSE",         f"{s2['rmse']:.6f}")
    show("coefficients", [f"{c:+.6g}" for c in coeffs2])
    show("equation",     f"y = {coeffs2[0]:+.4g}*x^2 {coeffs2[1]:+.4g}*x {coeffs2[2]:+.4g}")
    show("duration_ms",  r2["duration_ms"])

    # ---------- 4. Polynomial regression, degree 3 --------------------------------
    banner(4, "Run polynomial_regression on temp_c ~ time_s, degree=3")
    r3 = registry.execute_builtin(
        "polynomial_regression", df,
        {"x": "time_s", "y": "temp_c", "degree": 3},
    )
    assert r3["status"] == "ok", r3["error"]
    s3 = r3["summary"]["value"]
    coeffs3 = s3["coefficients"]
    show("R^2",          f"{s3['r_squared']:.6f}")
    show("RMSE",         f"{s3['rmse']:.6f}")
    show("coefficients", [f"{c:+.6g}" for c in coeffs3])
    show("equation",
         f"y = {coeffs3[0]:+.4g}*x^3 {coeffs3[1]:+.4g}*x^2 {coeffs3[2]:+.4g}*x {coeffs3[3]:+.4g}")

    # ---------- 5. Comparison (the user's original question) ----------------------
    banner(5, "Compare degree=2 vs degree=3")
    delta_r2 = s3["r_squared"] - s2["r_squared"]
    delta_rmse = s2["rmse"] - s3["rmse"]
    print(f"  degree=2  R^2={s2['r_squared']:.6f}  RMSE={s2['rmse']:.6f}")
    print(f"  degree=3  R^2={s3['r_squared']:.6f}  RMSE={s3['rmse']:.6f}")
    print(f"  delta     R^2={delta_r2:+.6f}  RMSE={delta_rmse:+.6f}")
    if delta_r2 > 1e-3:
        print("  -> degree=3 fits noticeably better")
    elif delta_r2 > 0:
        print("  -> degree=3 is marginally better; degree=2 preferred for simplicity")
    else:
        print("  -> degree=2 wins (degree=3 brings no improvement, risk of overfitting)")

    # ---------- 6. Wrong-slug recovery (the user's IQR mistake) -------------------
    banner(6, "Agent calls wrong slug 'iqr_outlier_detection' -> falls back to list_tools")
    bad = registry.execute_builtin("iqr_outlier_detection", df, {})
    assert bad["status"] == "error" and "unknown algorithm" in bad["error"], bad
    print(f"  registry returned error as expected: {bad['error']}")

    print("  agent now lists preprocess tools to find a real IQR implementation:")
    pre = registry.list_builtins(category="preprocess")
    for s in pre:
        marker = "  <-- USE THIS" if s.slug == "outlier_detect" else ""
        print(f"   - {s.slug:<24}  {s.description[:50]}{marker}")

    # ---------- 7. Built-in IQR outlier detection --------------------------------
    banner(7, "Run outlier_detect (method=iqr) on all numeric columns")
    iqr = registry.execute_builtin(
        "outlier_detect", df,
        {"columns": ["voltage_v", "current_a", "temp_c"], "method": "iqr"},
    )
    assert iqr["status"] == "ok", iqr["error"]
    iqr_summary = iqr["summary"]
    iqr_out_rows = iqr_summary["rows"]
    iqr_out_cols = iqr_summary["columns"]
    # Read the actual parquet to count flagged-per-column (the summary only has head)
    iqr_counts: Dict[str, int] = {}
    if iqr.get("result_path") and Path(iqr["result_path"]).exists():
        flag_df = pd.read_parquet(iqr["result_path"])
        for col in ["voltage_v", "current_a", "temp_c"]:
            flag_col = f"{col}_outlier"
            if flag_col in flag_df.columns:
                iqr_counts[col] = int(flag_df[flag_col].sum())
    show("output rows",       iqr_out_rows)
    show("added flag columns", [c for c in iqr_out_cols if c.endswith("_outlier")])
    show("outliers per column (count of rows flagged True)", iqr_counts)
    show("duration_ms",       iqr["duration_ms"])

    # ---------- 8. The novel request — codegen via FakeLLM ----------------------
    banner(8, "Novel request: 'compute cumulative capacity (Ah) from current'")
    print("  this is NOT in the built-in catalog -> agent escalates to generate_tool")
    print("  using FakeLLM: response 1 = broken (forgot pd import), response 2 = fixed")
    print("  expect the retry loop to recover...")

    fake = FakeLLM([_wrap(BROKEN_CODE), _wrap(FIXED_CODE)])
    bundle = await codegen.generate_algorithm(
        "Add a column 'capacity_ah' that is the trapezoidal integral of current_a over time_s, "
        "converted to ampere-hours.",
        llm=fake,
    )
    show("attempts",          bundle["attempts"])
    show("all_tests_passed",  bundle["all_tests_passed"])
    show("LLM calls made",    fake.calls)
    print("  attempt log:")
    for entry in bundle.get("attempt_log", []):
        if entry["stage"] == "parse_meta":
            print(f"    attempt {entry['attempt']}  stage=parse_meta  error={entry['error']}")
        else:
            print(f"    attempt {entry['attempt']}  stage=smoke_test  passed={entry['passed']}")
            for rpt in entry.get("reports", []):
                print(f"      case {rpt['case']}: status={rpt['status']}  err={rpt['error'][:120]}")
    if not bundle["all_tests_passed"]:
        print("  [FAIL] codegen did not recover")
        print(f"  final_error: {bundle.get('final_error')}")
        return 1

    # ---------- 9. Run the auto-generated algorithm on the real dataset ---------
    banner(9, "Run the auto-generated cumulative_capacity tool on the real dataset")
    final_code = bundle["code"]
    result = sbx.execute(final_code, {}, input_df=df, save_result=True)
    assert result.status == "ok", result.error
    show("status",      result.status)
    show("duration_ms", result.duration_ms)
    show("rows out",    result.result_rows)
    # The summary should now include the new capacity_ah column.
    s = result.summary
    if s.get("type") == "dataframe":
        print(f"  output columns: {s['columns']}")
        # Pick out the final capacity number from the parquet we just wrote
        if result.result_path and Path(result.result_path).exists():
            out_df = pd.read_parquet(result.result_path)
            final_cap = out_df["capacity_ah"].iloc[-1]
            print(f"  final cumulative capacity: {final_cap:.6f} Ah")
            print(f"  (sanity check: ~mean current {df['current_a'].mean():.3f} A "
                  f"x {df['time_s'].iloc[-1]/3600:.5f} h = {df['current_a'].mean() * df['time_s'].iloc[-1]/3600:.6f} Ah)")

    # ---------- 10. Final report ------------------------------------------------
    banner(10, "Walkthrough complete — recap")
    total_flagged = sum(iqr_counts.values()) if iqr_counts else 0
    recap = [
        ("polynomial_regression (deg 2)",  "ok",
         f"R^2={s2['r_squared']:.4f}, RMSE={s2['rmse']:.4f}"),
        ("polynomial_regression (deg 3)",  "ok",
         f"R^2={s3['r_squared']:.4f}, RMSE={s3['rmse']:.4f}"),
        ("outlier_detect (iqr)",           "ok",
         f"{total_flagged} cell-level flags across {len(iqr_counts)} cols"),
        ("codegen self-healing",
         f"recovered in {bundle['attempts']} attempts",
         f"{fake.calls} LLM calls (first one had missing-import bug)"),
        ("sandboxed run of new tool",      "ok",
         f"{result.result_rows} rows out, {result.duration_ms}ms"),
    ]
    print(f"  {'pipeline step':<34}  {'status':<28}  {'detail'}")
    print(f"  {'-'*34}  {'-'*28}  {'-'*40}")
    for name, status, detail in recap:
        print(f"  {name:<34}  {status:<28}  {detail}")

    print("\nAll steps executed end-to-end. Self-healing retry confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
