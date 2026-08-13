"""Parsers for the three wind-tunnel file kinds a test run produces.

A "车次" (test run) is delivered as three sibling files named ``<kind><run_no>``
with **no extension** and **GBK** text encoding:

===========  ====================================================================
``ca246490``  raw acquisition table — 16 numeric columns, pressures in **MPa**
``pa246490``  the process report — a sectioned, human-readable GBK listing
``da246490``  the aerodynamic result ("list") — 59 named coefficient columns
===========  ====================================================================

Design notes
------------
* **Never trust exact whitespace.** The legacy scripts anchored on literal
  header strings such as ``'AM    At     Bs     rc    CAF …'``; the real
  ``pa246490`` writes the same header with different padding, so that anchor
  silently matched nothing. Every anchor here is matched on a *token sequence*
  or a substring that survives re-padding.
* **Never guess the encoding.** ``read_text`` tries UTF-8 first (the templates
  the customer re-exported) then GBK (everything produced by the tunnel).
* **Parsing never judges.** These functions return numbers and metadata only.
  Thresholds live in the rule engine, so a user can change a limit without
  touching code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── CA column layout ────────────────────────────────────────────────────────
# Confirmed against the ``============CA文件===`` echo block inside the pa
# report, which prints the same table with a header row.
CA_COLUMNS: Tuple[str, ...] = (
    "ALPHA",  # 0  机构攻角 (deg)
    "My",     # 1  天平原始码 — 偏航力矩单元
    "Z",      # 2                侧向力单元
    "Mz",     # 3                俯仰力矩单元
    "Y",      # 4                法向力单元
    "Mx",     # 5                滚转力矩单元
    "Q",      # 6                轴向力单元
    "PL",     # 7  左底压  (MPa)
    "P2",     # 8  备用底压(MPa)
    "PR",     # 9  右底压  (MPa)
    "To",     # 10 总温    (degC)
    "t",      # 11 室温    (degC)
    "Pa",     # 12 大气压  (MPa)
    "P8",     # 13 来流静压(MPa)
    "P0",     # 14 来流总压(MPa)
    "Ma",     # 15 记录马赫数
)

#: The six balance measuring units, in the column order used everywhere
#: (raw codes, load library, calibration matrix).
BALANCE_UNITS: Tuple[str, ...] = ("My", "Z", "Mz", "Y", "Mx", "Q")

#: Indices into a ``ca`` row for the five pressure transducers whose zeros must
#: agree (左底压 / 右底压 / 大气压 / 来流静压 / 来流总压).
PRESSURE_ZERO_COLS: Tuple[int, ...] = (7, 9, 12, 13, 14)


def read_text(path: Path | str) -> str:
    """Decode a tunnel file. UTF-8 first, then GBK, then GBK with replacement."""
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("gbk", errors="replace")


def detect_kind(filename: str) -> Optional[str]:
    """``ca246490`` → ``"ca"``.  Returns None when the name is not a run file.

    The tunnel writes files with no extension, so the *prefix* is the only type
    marker. ``da``-family files are also seen as ``list``-prefixed exports.
    """
    stem = Path(filename).name.strip().lower()
    m = re.match(r"^(ca|pa|da)(\d{3,})", stem)
    if m:
        return m.group(1)
    return None


def detect_run_no(filename: str) -> Optional[str]:
    """``ca246490模板(公开)`` → ``"246490"``."""
    stem = Path(filename).name.strip().lower()
    m = re.match(r"^(?:ca|pa|da)(\d{3,})", stem)
    return m.group(1) if m else None


def _floats(line: str) -> Optional[List[float]]:
    """Parse a whitespace-separated all-numeric line, else None."""
    parts = line.split()
    if not parts:
        return None
    out: List[float] = []
    for p in parts:
        try:
            out.append(float(p))
        except ValueError:
            return None
    return out


def _tokens(line: str) -> List[str]:
    return line.split()


# ══════════════════════════════════════════════════════════════════════════
#  CA — raw acquisition table
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class CaFile:
    """The raw acquisition table.

    ``rows`` is every numeric row before the ``N5=`` terminator. By tunnel
    convention the **first** row is the pre-run zero (初零) and the **last**
    row is the post-run zero (末零); everything between is a blow point.
    """

    path: str = ""
    run_no: str = ""
    rows: List[List[float]] = field(default_factory=list)
    nominal_mach: Optional[float] = None
    alpha_targets: List[float] = field(default_factory=list)
    n_points: Optional[int] = None

    @property
    def zero_start(self) -> List[float]:
        return self.rows[0] if self.rows else []

    @property
    def zero_end(self) -> List[float]:
        return self.rows[-1] if self.rows else []

    @property
    def blow_rows(self) -> List[List[float]]:
        return self.rows[1:-1] if len(self.rows) >= 3 else []

    def col(self, idx: int, rows: Optional[Sequence[Sequence[float]]] = None) -> List[float]:
        src = self.rows if rows is None else rows
        return [r[idx] for r in src if len(r) > idx]

    @property
    def ok(self) -> bool:
        return len(self.rows) >= 2 and all(len(r) >= 15 for r in self.rows)


def parse_ca(path: Path | str) -> CaFile:
    text = read_text(path)
    out = CaFile(path=str(path), run_no=detect_run_no(str(path)) or "")

    lines = text.splitlines()
    for line in lines:
        # The numeric block ends at the ``N5=`` record; everything after is
        # the trailer (nominal Mach, point count, alpha schedule).
        if "N5" in line:
            break
        vals = _floats(line)
        if vals and len(vals) >= 7:
            out.rows.append(vals)

    for line in lines:
        s = line.strip()
        if s.startswith("M=") and out.nominal_mach is None:
            try:
                out.nominal_mach = float(s.split("=", 1)[1])
            except ValueError:
                pass
        elif s.startswith("N6="):
            try:
                out.n_points = int(float(s.split("=", 1)[1]))
            except ValueError:
                pass
        elif s.startswith("ALPHA="):
            vals = _floats(s.split("=", 1)[1])
            if vals:
                out.alpha_targets = vals
    return out


# ══════════════════════════════════════════════════════════════════════════
#  PA — process report
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class PaTable:
    header: List[str] = field(default_factory=list)
    rows: List[List[float]] = field(default_factory=list)

    def col(self, idx: int) -> List[float]:
        return [r[idx] for r in self.rows if len(r) > idx]

    def __bool__(self) -> bool:
        return bool(self.rows)


@dataclass
class PaFile:
    path: str = ""
    run_no: str = ""
    #: True for a force-measurement (测力) run — the only kind these checks
    #: apply to. Hinge-moment (铰链力矩) runs lack the balance/elastic blocks.
    is_force_test: bool = False
    test_no: str = ""
    nominal_mach: Optional[float] = None
    balance_type: str = ""          # e.g. "TP202126"
    balance_formula: str = ""       # e.g. "N636CB01"
    balance_system: str = ""
    model_params: Dict[str, float] = field(default_factory=dict)
    #: ``============CA文件===`` echo, pressures already in kgf/m^2 (== mmH2O).
    ca_echo: PaTable = field(default_factory=PaTable)
    #: 弹性角修正: ALPHA / alpha_e / beta_e / gamma_e / dAlphaMe / dBetaMe
    elastic: PaTable = field(default_factory=PaTable)
    #: 没有插值的姿态角: Am / Bm / Rm / At / Bs — the MEASURED attitude set.
    attitude_measured: PaTable = field(default_factory=PaTable)
    #: 插值后的姿态角 — the interpolation TARGET set.
    attitude_interp: PaTable = field(default_factory=PaTable)
    #: 吹风时天平测量的气动载荷: ALPHA + six balance units, engineering units.
    aero_loads: PaTable = field(default_factory=PaTable)
    #: Diagonal of the balance calibration matrix (primary sensitivities).
    balance_sensitivity: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.is_force_test and bool(self.ca_echo.rows)


_SECTION_END = re.compile(r"^[\s=]*$")


def _collect_numeric_rows(
    lines: Sequence[str], start: int, *, min_cols: int, stop_words: Sequence[str] = ()
) -> Tuple[List[List[float]], int]:
    """Read consecutive numeric rows from ``start``; stop at a blank line, a
    separator, a stop-word, or the first non-numeric line."""
    rows: List[List[float]] = []
    i = start
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s or set(s) <= {"=", "-"}:
            break
        if any(w in line for w in stop_words):
            break
        vals = _floats(line)
        if vals is None or len(vals) < min_cols:
            break
        rows.append(vals)
        i += 1
    return rows, i


def _find(lines: Sequence[str], *needles: str, start: int = 0) -> int:
    """First index at/after ``start`` whose line contains ALL needles."""
    for i in range(start, len(lines)):
        if all(n in lines[i] for n in needles):
            return i
    return -1


def parse_pa(path: Path | str) -> PaFile:
    text = read_text(path)
    lines = text.splitlines()
    out = PaFile(path=str(path), run_no=detect_run_no(str(path)) or "")

    # ── flags & scalars ─────────────────────────────────────────────────
    out.is_force_test = ("L测 =" in text) or ("L测=" in text)

    m = re.search(r"TEST\s*No\.\s*(\d+)", text)
    if m:
        out.test_no = m.group(1)
    m = re.search(r"M\s*=\s*([0-9.]+)", text)
    if m:
        try:
            out.nominal_mach = float(m.group(1))
        except ValueError:
            pass
    m = re.search(r"天平型式\s*[:：]\s*(\S+)", text)
    if m:
        out.balance_type = m.group(1)
    m = re.search(r"天平弹性角公式\s*[:：]\s*(\S+)", text)
    if m:
        out.balance_formula = m.group(1)
    m = re.search(r"天平系统\s*[:：]\s*(\S+)", text)
    if m:
        out.balance_system = m.group(1).strip()
    # ``========天平公式 TP202126   PARAMETER  ========`` is the authoritative
    # balance id when 天平型式 is absent.
    if not out.balance_type:
        m = re.search(r"天平公式\s+(\S+)\s+PARAMETER", text)
        if m:
            out.balance_type = m.group(1)

    for key in ("Sr", "Lcp", "Lmx", "Lmy", "Lmz"):
        m = re.search(rf"\b{key}\s*=\s*(-?[0-9.]+)", text)
        if m:
            try:
                out.model_params[key] = float(m.group(1))
            except ValueError:
                pass

    # ── CA echo table (pressures in kgf/m^2 == mmH2O) ───────────────────
    idx = _find(lines, "CA文件")
    if idx >= 0:
        hdr = _find(lines, "ALPHA", "PL", start=idx)
        if hdr >= 0:
            out.ca_echo.header = _tokens(lines[hdr])
            # Rows after the header: the pre-run zero, a blank, then the blow
            # sweep, a blank, then the post-run zero. Collect every numeric row
            # in the block so callers can slice zeros vs blow points themselves.
            rows: List[List[float]] = []
            i = hdr + 1
            blanks = 0
            while i < len(lines) and blanks < 3:
                s = lines[i].strip()
                if not s:
                    blanks += 1
                    i += 1
                    continue
                if set(s) <= {"=", "-"}:
                    break
                vals = _floats(lines[i])
                if vals is None or len(vals) < 15:
                    break
                rows.append(vals)
                i += 1
            out.ca_echo.rows = rows

    # ── elastic deformation table ───────────────────────────────────────
    idx = _find(lines, "ALPHA", "αe")
    if idx >= 0:
        rows, _ = _collect_numeric_rows(
            lines, idx + 1, min_cols=4, stop_words=("投影用角度", "rtp=")
        )
        out.elastic.header = ["ALPHA", "alpha_e", "beta_e", "gamma_e", "dAlphaMe", "dBetaMe"]
        out.elastic.rows = rows

    # ── attitude tables (measured vs interpolation targets) ─────────────
    idx = _find(lines, "没有插值的姿态角")
    if idx >= 0:
        hdr = _find(lines, "Am", "At", start=idx)
        if hdr >= 0:
            out.attitude_measured.header = _tokens(lines[hdr])
            out.attitude_measured.rows, _ = _collect_numeric_rows(lines, hdr + 1, min_cols=4)
    idx = _find(lines, "插值后的姿态角")
    if idx >= 0:
        hdr = _find(lines, "Am", "At", start=idx)
        if hdr >= 0:
            out.attitude_interp.header = _tokens(lines[hdr])
            out.attitude_interp.rows, _ = _collect_numeric_rows(lines, hdr + 1, min_cols=4)

    # ── aerodynamic loads measured by the balance ───────────────────────
    idx = _find(lines, "吹风时天平测量的气动载荷")
    if idx >= 0:
        hdr = _find(lines, "ALPHA", start=idx)
        if hdr >= 0:
            out.aero_loads.header = _tokens(lines[hdr])
            out.aero_loads.rows, _ = _collect_numeric_rows(lines, hdr + 1, min_cols=7)

    # ── balance calibration matrix diagonal ─────────────────────────────
    idx = _find(lines, "天平公式", "PARAMETER")
    if idx >= 0:
        hdr = _find(lines, "My", "Mz", "Mx", start=idx)
        if hdr >= 0:
            for j in range(hdr + 1, min(hdr + 1 + len(BALANCE_UNITS), len(lines))):
                toks = _tokens(lines[j])
                if len(toks) >= 7 and toks[0] in BALANCE_UNITS:
                    try:
                        pos = BALANCE_UNITS.index(toks[0])
                        out.balance_sensitivity[toks[0]] = float(toks[1 + pos])
                    except (ValueError, IndexError):
                        continue

    if out.is_force_test and not out.ca_echo.rows:
        out.warnings.append("pa 文件中未找到 CA 回显表，底压相关检查将不可用")
    return out


# ══════════════════════════════════════════════════════════════════════════
#  DA — aerodynamic result ("list") file
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class DaFile:
    path: str = ""
    run_no: str = ""
    columns: List[str] = field(default_factory=list)
    rows: List[List[float]] = field(default_factory=list)
    #: Flow conditions block: Pa / P8 / Po / q8 / To1 / To2 / Re1 / Re2
    flow: Dict[str, float] = field(default_factory=dict)
    model_name: str = ""
    mach: Optional[float] = None
    #: "list" (machine-readable 59-column export) | "printed" (report table)
    layout: str = ""
    #: Model attitude / control-surface state for this run — the thing that
    #: distinguishes one run from another in a comparison plot, and therefore
    #: what a multi-run legend must show. Keys: PHI, BETA, dz, dy, dx, XU.
    state: Dict[str, float] = field(default_factory=dict)
    #: Derivatives printed in the header (CNa, MZG1a, …) — the tunnel's own
    #: values, useful as an independent cross-check on our fitted slopes.
    derivatives: Dict[str, float] = field(default_factory=dict)
    #: Reference geometry: Sr, Lcp, Lmx/Lmy/Lmz, L, D, Xg1…Zg2
    geometry: Dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.columns) and bool(self.rows)

    def series(self, name: str) -> List[float]:
        if name not in self.columns:
            return []
        i = self.columns.index(name)
        return [r[i] for r in self.rows if len(r) > i]

    def numeric_columns(self) -> List[str]:
        """Columns that actually carry variation — the ones worth plotting.

        A ``da`` file pads unused coefficients with all-zero columns; offering
        them in a plot picker is noise.
        """
        out: List[str] = []
        for i, name in enumerate(self.columns):
            vals = [r[i] for r in self.rows if len(r) > i]
            if vals and any(abs(v) > 1e-12 for v in vals):
                out.append(name)
        return out


def _parse_da_printed(lines: Sequence[str], out: DaFile) -> DaFile:
    """The PRINTED report layout — what the tunnel actually files.

    A ``da`` file in production is not the machine-readable 59-column export
    but a paginated report::

                      TABLE    2     CONTINUED
              No.246490    M= 1.74  XU=   8
              Φ=    0.00  β=    0.00   δz=  0.0  δy=  0.0  δx=  0.0
              CNa= 0.09655 MZG1a=-0.06177
              Sr=0.0163060
              Po=187218.1   P8=  35647.9  q8= 75636.2  To=286.0  1.0E-6*Re=27.14

              ALPHA        CN        CZ       CAF      MXG1      MYG1      MZG1
               -2.0  -0.12520   0.00306   0.12675  -0.00017   0.00278   0.08402
               …
              ALPHA      MXG2      MYG2      MZG2        CA       CAB        CL
               …

    Several blocks, each keyed on ALPHA, are stitched back into one table. The
    blocks are discovered by shape (a non-numeric header line starting with an
    angle column, followed by numeric rows of the same width) rather than by
    matching literal header text, so a run with a different coefficient set
    still parses.
    """
    text = "\n".join(lines)
    out.layout = "printed"

    def grab(pattern: str) -> Optional[float]:
        m = re.search(pattern, text)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None

    out.mach = grab(r"\bM=\s*(-?[\d.]+)")
    for key, pat in (("XU", r"\bXU=\s*(-?[\d.]+)"), ("PHI", r"Φ=\s*(-?[\d.]+)"),
                     ("BETA", r"β=\s*(-?[\d.]+)"), ("dz", r"δz=\s*(-?[\d.]+)"),
                     ("dy", r"δy=\s*(-?[\d.]+)"), ("dx", r"δx=\s*(-?[\d.]+)")):
        v = grab(pat)
        if v is not None:
            out.state[key] = v
    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9]*a)=\s*(-?[\d.]+)", text):
        try:
            out.derivatives[m.group(1)] = float(m.group(2))
        except ValueError:
            continue
    for key in ("Sr", "Lmx", "Lmy", "Lmz", "Lcp", "L", "D",
                "Xg1", "Yg1", "Zg1", "Xg2", "Yg2", "Zg2"):
        v = grab(rf"\b{key}\s*=\s*(-?[\d.]+)")
        if v is not None:
            out.geometry[key] = v
    for key, pat in (("Po", r"\bPo=\s*(-?[\d.]+)"), ("P8", r"\bP8=\s*(-?[\d.]+)"),
                     ("q8", r"\bq8=\s*(-?[\d.]+)"), ("To", r"\bTo=\s*(-?[\d.]+)"),
                     ("Re", r"1\.0E-6\*Re=\s*(-?[\d.]+)")):
        v = grab(pat)
        if v is not None:
            out.flow[key] = v
    m = re.search(r"No\.\s*(\d+)", text)
    if m and not out.run_no:
        out.run_no = m.group(1)

    # ── stitch the ALPHA-keyed blocks ───────────────────────────────────
    by_alpha: Dict[float, Dict[str, float]] = {}
    order: List[float] = []
    columns: List[str] = []
    i = 0
    while i < len(lines):
        toks = _tokens(lines[i])
        is_header = (
            len(toks) >= 2
            and all(_floats(t) is None for t in toks)   # no token parses as a number
            and toks[0].upper() in ("ALPHA", "AM", "AT", "BETA", "PHI", "MA")
        )
        if not is_header:
            i += 1
            continue
        rows, end = _collect_numeric_rows(lines, i + 1, min_cols=len(toks))
        rows = [r for r in rows if len(r) == len(toks)]
        if not rows:
            i += 1
            continue
        for name in toks[1:]:
            if name not in columns:
                columns.append(name)
        for r in rows:
            a = r[0]
            if a not in by_alpha:
                by_alpha[a] = {}
                order.append(a)
            for name, v in zip(toks[1:], r[1:]):
                by_alpha[a][name] = v
        i = max(end, i + 1)

    if not by_alpha:
        return out
    out.columns = ["ALPHA"] + columns
    for a in order:
        row = [a] + [by_alpha[a].get(c, 0.0) for c in columns]
        out.rows.append(row)
    return out


def parse_da(path: Path | str) -> DaFile:
    text = read_text(path)
    lines = text.splitlines()
    out = DaFile(path=str(path), run_no=detect_run_no(str(path)) or "")

    # Layout: [zeros row] / [nrows ncols] / [header] / nrows x ncols data
    n_rows = n_cols = 0
    header_idx = -1
    for i, line in enumerate(lines[:6]):
        toks = _tokens(line)
        if len(toks) == 2 and all(t.lstrip("-").isdigit() for t in toks):
            n_rows, n_cols = int(toks[0]), int(toks[1])
            header_idx = i + 1
            break
    if header_idx < 0 or header_idx >= len(lines):
        # Not the machine-readable export — fall back to the printed report,
        # which is the layout the tunnel actually archives.
        return _parse_da_printed(lines, out)
    out.layout = "list"

    out.columns = _tokens(lines[header_idx])
    for j in range(header_idx + 1, len(lines)):
        vals = _floats(lines[j])
        if vals is None or len(vals) < max(2, n_cols // 2):
            break
        out.rows.append(vals)
        if n_rows and len(out.rows) >= n_rows:
            break

    # Trailer: flow-condition block, then the model description line.
    idx = _find(lines, "Pa", "P8", "Po", "q8")
    if idx >= 0:
        vals = _floats(lines[idx + 1]) if idx + 1 < len(lines) else None
        if vals:
            for name, v in zip(_tokens(lines[idx]), vals):
                out.flow[name] = v
    idx = _find(lines, "Model")
    if idx >= 0 and idx + 1 < len(lines):
        toks = _tokens(lines[idx + 1])
        if len(toks) >= 5:
            out.model_name = " ".join(toks[4:])
            try:
                out.mach = float(toks[1])
            except ValueError:
                pass
    if out.mach is None:
        ma = out.series("M")
        if ma:
            out.mach = ma[0]
    # The list export carries the run's state as ordinary columns (constant
    # down the sweep). Lift them into `state` so both layouts expose the same
    # thing — a comparison legend must not care which layout it came from.
    for key, col in (("PHI", "PHI"), ("BETA", "BETA"),
                     ("dz", "D5"), ("dy", "D6"), ("dx", "D7"), ("D8", "D8")):
        vals = out.series(col)
        if vals:
            out.state.setdefault(key, vals[0])
    for name in out.columns:
        if name.endswith("a") and len(name) > 2:
            vals = out.series(name)
            if vals:
                out.derivatives.setdefault(name, vals[0])
    return out


# ══════════════════════════════════════════════════════════════════════════
#  Bundle — one run's three files
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class RunBundle:
    """Everything the checks need for a single 车次."""

    run_no: str
    ca: Optional[CaFile] = None
    pa: Optional[PaFile] = None
    da: Optional[DaFile] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def available(self) -> List[str]:
        return [k for k in ("ca", "pa", "da") if getattr(self, k) is not None]

    @property
    def mach(self) -> Optional[float]:
        for src in (self.ca, self.pa, self.da):
            v = getattr(src, "nominal_mach", None) if src is not None else None
            if v:
                return v
        return self.da.mach if self.da else None

    def meta(self) -> Dict[str, Any]:
        return {
            "run_no": self.run_no,
            "files": self.available,
            "mach": self.mach,
            "balance_type": self.pa.balance_type if self.pa else "",
            "balance_formula": self.pa.balance_formula if self.pa else "",
            "model": self.da.model_name if self.da else "",
            # Model attitude / control deflections. Needed by anything that must
            # know whether two runs are the same configuration — the comparison
            # views, and the trend detector's decision on whether a cross-run
            # trend is even interpretable.
            "state": dict(self.da.state) if (self.da and self.da.state) else {},
            "is_force_test": bool(self.pa and self.pa.is_force_test),
            "n_blow_points": len(self.ca.blow_rows) if self.ca else 0,
            "warnings": self.warnings + (self.pa.warnings if self.pa else []),
        }


def load_bundle(paths: Sequence[Path | str]) -> RunBundle:
    """Build a bundle from an arbitrary list of files belonging to one run."""
    run_no = ""
    ca = pa = da = None
    warnings: List[str] = []
    for p in paths:
        kind = detect_kind(str(p))
        if kind is None:
            warnings.append(f"忽略无法识别的文件：{Path(p).name}")
            continue
        run_no = run_no or (detect_run_no(str(p)) or "")
        try:
            if kind == "ca":
                ca = parse_ca(p)
            elif kind == "pa":
                pa = parse_pa(p)
            else:
                da = parse_da(p)
        except Exception as e:  # noqa: BLE001 — one bad file must not kill the run
            warnings.append(f"{Path(p).name} 解析失败：{type(e).__name__}: {e}")
    return RunBundle(run_no=run_no, ca=ca, pa=pa, da=da, warnings=warnings)


def group_by_run(paths: Sequence[Path | str]) -> Dict[str, List[Path]]:
    """Group a directory drop of mixed files into ``{run_no: [paths]}``."""
    groups: Dict[str, List[Path]] = {}
    for p in paths:
        rn = detect_run_no(str(p))
        if rn is None:
            continue
        groups.setdefault(rn, []).append(Path(p))
    return dict(sorted(groups.items()))
