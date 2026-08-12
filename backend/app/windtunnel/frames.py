"""Canonical tidy frame — the contract every *custom* check is written against.

Why a tidy frame
----------------
The platform already has a sandbox whose contract is ``run(df, **params)``, a
codegen service that writes to that contract, a 20-algorithm builtin library
that consumes it, and a flow-template engine that chains it. If a wind-tunnel
check had to be written against bespoke ``CaFile`` / ``PaFile`` objects, none of
that would be reusable and every user-authored check would need a new plumbing
path.

So one function flattens a run into a single long-form DataFrame:

    ==========  ======  =======  ==========  =========  ============
    table       row     alpha    variable    value      unit
    ==========  ======  =======  ==========  =========  ============
    ca          0       -0.037   My          -0.041592  code
    ca          0       -0.037   PL          10369.9    mmH2O
    elastic     3       -0.985   alpha_e     0.001      deg
    da          0       -2.0     CN          -0.1252    -
    ==========  ======  =======  ==========  =========  ============

``point`` marks the acquisition role of a ``ca``/``ca_echo`` row:
``zero_start`` / ``blow`` / ``zero_end`` — so a custom rule can say
"only the blow points" without re-deriving that convention.

Pressures are pre-converted to **mmH2O**, angles to degrees. A user writing a
new detector never has to know that the raw file is in MPa — the unit bug that
plagued the legacy scripts simply cannot recur through this path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .parsers import BALANCE_UNITS, CA_COLUMNS, RunBundle
from .units import mach_from_pressure_ratio, mpa_to_mmh2o

#: Unit tag per ca column, used to label rows and to decide what to convert.
_CA_UNITS: Dict[str, str] = {
    "ALPHA": "deg", "My": "code", "Z": "code", "Mz": "code", "Y": "code",
    "Mx": "code", "Q": "code", "PL": "mmH2O", "P2": "mmH2O", "PR": "mmH2O",
    "To": "degC", "t": "degC", "Pa": "mmH2O", "P8": "mmH2O", "P0": "mmH2O",
    "Ma": "-",
}
_CA_PRESSURE_COLS = {"PL", "P2", "PR", "Pa", "P8", "P0"}


def _row_role(i: int, n: int) -> str:
    if i == 0:
        return "zero_start"
    if i == n - 1:
        return "zero_end"
    return "blow"


def bundle_to_frame(bundle: RunBundle) -> pd.DataFrame:
    """Flatten one run into the canonical long-form frame."""
    recs: List[Dict[str, Any]] = []

    def emit(table: str, row: int, alpha: Optional[float], var: str,
             value: Any, unit: str, point: str = "") -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        recs.append({
            "run_no": bundle.run_no, "table": table, "row": row,
            "point": point, "alpha": alpha, "variable": var,
            "value": v, "unit": unit,
        })

    # ── ca: raw acquisition, pressures converted to mmH2O ────────────────
    if bundle.ca is not None and bundle.ca.rows:
        rows = bundle.ca.rows
        n = len(rows)
        for i, r in enumerate(rows):
            role = _row_role(i, n)
            alpha = r[0] if r else None
            for j, name in enumerate(CA_COLUMNS):
                if j >= len(r):
                    break
                v = mpa_to_mmh2o(r[j]) if name in _CA_PRESSURE_COLS else r[j]
                emit("ca", i, alpha, name, v, _CA_UNITS.get(name, "-"), role)
            # Derived: isentropic Mach from the measured total/static pair.
            if len(r) > 14 and r[13] > 0:
                emit("ca", i, alpha, "Ma_isentropic",
                     mach_from_pressure_ratio(r[14], r[13]), "-", role)

    # ── pa tables ────────────────────────────────────────────────────────
    pa = bundle.pa
    if pa is not None:
        if pa.ca_echo.rows:
            n = len(pa.ca_echo.rows)
            names = pa.ca_echo.header or list(CA_COLUMNS)
            for i, r in enumerate(pa.ca_echo.rows):
                role = _row_role(i, n)
                for j, v in enumerate(r):
                    name = names[j] if j < len(names) else f"c{j}"
                    unit = "mmH2O" if name.upper() in {"PL", "P2", "PR", "PA", "P8", "P0"} \
                        else ("deg" if name.upper() == "ALPHA"
                              else ("degC" if name in ("To", "t") else "code"))
                    emit("ca_echo", i, r[0], name, v, unit, role)
        for tbl, names, unit in (
            (pa.elastic, ["ALPHA", "alpha_e", "beta_e", "gamma_e", "dAlphaMe", "dBetaMe"], "deg"),
            (pa.attitude_measured, pa.attitude_measured.header, "deg"),
            (pa.attitude_interp, pa.attitude_interp.header, "deg"),
        ):
            if not tbl.rows:
                continue
            label = ("elastic" if tbl is pa.elastic else
                     "attitude_measured" if tbl is pa.attitude_measured else
                     "attitude_interp")
            for i, r in enumerate(tbl.rows):
                for j, v in enumerate(r):
                    name = names[j] if j < len(names) else f"c{j}"
                    emit(label, i, r[0], name, v, unit)
        if pa.aero_loads.rows:
            names = ["ALPHA"] + list(BALANCE_UNITS)
            for i, r in enumerate(pa.aero_loads.rows):
                for j, v in enumerate(r):
                    name = names[j] if j < len(names) else f"c{j}"
                    emit("aero_loads", i, r[0], name, v,
                         "deg" if name == "ALPHA" else "load")

    # ── da: aerodynamic coefficients ─────────────────────────────────────
    if bundle.da is not None and bundle.da.ok:
        da = bundle.da
        ai = da.columns.index("ALPHA") if "ALPHA" in da.columns else 0
        for i, r in enumerate(da.rows):
            alpha = r[ai] if len(r) > ai else None
            for j, name in enumerate(da.columns):
                if j >= len(r):
                    break
                emit("da", i, alpha, name, r[j],
                     "deg" if name in ("ALPHA", "Bs", "GAMA", "At", "BETA") else "-")

    if not recs:
        return pd.DataFrame(columns=["run_no", "table", "row", "point", "alpha",
                                     "variable", "value", "unit"])
    return pd.DataFrame.from_records(recs)


def frame_schema_hint(bundle: RunBundle) -> str:
    """A compact description of the frame, fed to the LLM before it writes a
    custom extractor. Concrete counts and the real variable names beat any
    amount of prose about the format."""
    df = bundle_to_frame(bundle)
    if df.empty:
        return "（本车次没有可用数据）"
    lines = [
        "长表 DataFrame，列：run_no, table, row, point, alpha, variable, value, unit",
        f"总行数：{len(df)}",
        "",
        "各 table 的含义与可用 variable：",
    ]
    for tbl, sub in df.groupby("table", sort=False):
        vars_ = sorted(sub["variable"].unique().tolist())
        pts = sorted(x for x in sub["point"].unique().tolist() if x)
        lines.append(
            f"- {tbl}（{len(sub)} 行，{sub['row'].nunique()} 个采集点"
            + (f"，point 取值 {'/'.join(pts)}" if pts else "") + "）："
            + "、".join(vars_[:40]) + ("…" if len(vars_) > 40 else "")
        )
    lines += [
        "",
        "单位约定：所有压力已换算为 mmH2O(等于 kgf/m²)，角度为度，温度为摄氏度，"
        "天平原始读数单位为“码”。",
    ]
    return "\n".join(lines)


def wide_table(bundle: RunBundle, table: str = "ca") -> pd.DataFrame:
    """Pivot one logical table back to wide form — handy for plotting and for
    users who prefer a familiar column layout."""
    df = bundle_to_frame(bundle)
    sub = df[df["table"] == table]
    if sub.empty:
        return pd.DataFrame()
    wide = sub.pivot_table(index=["row", "point", "alpha"], columns="variable",
                           values="value", aggfunc="first").reset_index()
    wide.columns.name = None
    return wide.sort_values("row").reset_index(drop=True)
