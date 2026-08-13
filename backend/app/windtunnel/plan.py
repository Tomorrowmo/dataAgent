"""The test plan (车次表) — what was *supposed* to be flown.

Every check so far answers a question about data that exists. The plan answers
the one question the data alone cannot: **what is missing?** A wind-tunnel entry
is executed against a matrix of conditions; a condition that was planned and
never flown, or flown and then discarded, leaves no trace in the run files. Only
the plan table shows it.

The customer's ``车次表(公开).xlsx`` is a spreadsheet whose rows are model states
and whose columns are Mach numbers::

    LineNum  Bm  Phi  D5   D6  D7  D8 | 0.4  0.6   0.8     0.95    1.05  …
          2   0    0  -25   0   0   0 | ---  ---  246541  246540   ---   …

* ``D5 / D6 / D7`` are the tunnel's channel names for the elevator / rudder /
  aileron deflections — the same labels the engineers' own plotting tool shows.
  This file is the authority for that mapping.
* ``---`` means the condition was not flown.
* **Two run numbers in one cell** (``246538/246539``) means the condition was
  re-flown. On this entry every such pair has data for exactly one of the two,
  so the other is the discarded attempt — which is why the entry contains no
  repeat runs despite looking like it might. That provenance belongs in a
  quality report; it is not something a reader should have to infer.

Parsing is deliberately tolerant: the sheet is a human-maintained spreadsheet,
so the header row is located by content, and any sheet that does not look like
a plan is skipped rather than mis-read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Spreadsheet column label → the state key used everywhere else.
_STATE_ALIASES: Dict[str, str] = {
    "bm": "BETA", "β": "BETA", "beta": "BETA",
    "phi": "PHI", "φ": "PHI",
    "d5": "dz", "dz": "dz",
    "d6": "dy", "dy": "dy",
    "d7": "dx", "dx": "dx",
    "d8": "D8",
}


@dataclass
class PlanEntry:
    run_no: str
    mach: Optional[float]
    state: Dict[str, Optional[float]]
    #: Other run numbers written in the same cell — a re-flight of this
    #: condition. Order is as written.
    cell_runs: List[str] = field(default_factory=list)
    note: str = ""
    row_label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_no": self.run_no, "mach": self.mach, "state": self.state,
            "cell_runs": self.cell_runs, "note": self.note,
            "row_label": self.row_label,
        }


@dataclass
class PlanTable:
    entries: List[PlanEntry] = field(default_factory=list)
    #: Conditions explicitly marked as not flown ("---").
    not_flown: List[Dict[str, Any]] = field(default_factory=list)
    machs: List[float] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    source: str = ""
    sheet: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.entries)

    def run_nos(self) -> List[str]:
        return [e.run_no for e in self.entries]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "not_flown": self.not_flown,
            "machs": self.machs, "notes": self.notes,
            "source": self.source, "sheet": self.sheet,
            "planned_count": len(self.entries),
        }


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # reject NaN


def _looks_like_run(tok: str) -> bool:
    return bool(re.fullmatch(r"\d{4,}", tok))


def parse_plan(path: Path | str) -> PlanTable:
    """Read a 车次表 spreadsheet. Returns an empty table if it is not one."""
    import pandas as pd

    out = PlanTable(source=str(Path(path).name))
    try:
        xl = pd.ExcelFile(path)
    except Exception:                      # noqa: BLE001 — not a spreadsheet
        return out

    for sheet in xl.sheet_names:
        try:
            df = xl.parse(sheet, header=None)
        except Exception:                  # noqa: BLE001
            continue
        if df.empty or df.shape[1] < 4:
            continue

        # Find the header row: the one whose cells name the state channels and
        # whose remaining cells are Mach numbers.
        hdr_idx = -1
        for i in range(min(6, len(df))):
            cells = [str(x).strip().lower() for x in df.iloc[i].tolist()]
            named = sum(1 for c in cells if c in _STATE_ALIASES)
            machy = sum(1 for c in cells if (_num(c) or 0) and 0.1 <= float(c) <= 10)
            if named >= 3 and machy >= 2:
                hdr_idx = i
                break
        if hdr_idx < 0:
            continue

        header = df.iloc[hdr_idx].tolist()
        state_cols: Dict[int, str] = {}
        mach_cols: Dict[int, float] = {}
        for j, cell in enumerate(header):
            key = str(cell).strip().lower()
            if key in _STATE_ALIASES:
                state_cols[j] = _STATE_ALIASES[key]
                continue
            m = _num(cell)
            if m is not None and 0.1 <= m <= 10:
                mach_cols[j] = round(m, 3)
        if not state_cols or not mach_cols:
            continue

        out.sheet = sheet
        out.machs = sorted(set(mach_cols.values()))
        # A trailing free-text column carries the planner's remarks.
        note_col = max(mach_cols) + 1 if (max(mach_cols) + 1) < df.shape[1] else None

        for _, row in df.iloc[hdr_idx + 1:].iterrows():
            state = {v: _num(row[j]) for j, v in state_cols.items()}
            if all(v is None for v in state.values()):
                continue
            note = ""
            if note_col is not None:
                raw = row[note_col]
                if isinstance(raw, str) and raw.strip():
                    note = " ".join(raw.split())
                    if note not in out.notes:
                        out.notes.append(note)
            label = " ".join(f"{k}={v:g}" for k, v in state.items() if v is not None)
            for j, mach in mach_cols.items():
                cell = row[j]
                if cell is None or (isinstance(cell, float) and cell != cell):
                    continue
                text = str(cell).strip()
                if not text:
                    continue
                if set(text) <= {"-", "—", "–"}:
                    out.not_flown.append({"mach": mach, "state": dict(state),
                                          "label": label})
                    continue
                toks = [t for t in re.split(r"[/、,，;；\s]+", text) if _looks_like_run(t)]
                for t in toks:
                    out.entries.append(PlanEntry(
                        run_no=t, mach=mach, state=dict(state),
                        cell_runs=list(toks), note=note, row_label=label))
        if out.entries:
            break                          # first plan-shaped sheet wins
    return out


# ══════════════════════════════════════════════════════════════════════════
def coverage(plan: PlanTable, actual_run_nos: Sequence[str]) -> Dict[str, Any]:
    """Compare the plan against what actually arrived.

    Four buckets, each actionable:

    ``present``     planned and delivered
    ``missing``     planned but no data — the thing no per-run check can see
    ``superseded``  the discarded half of a re-flight pair (missing *because*
                    the condition was flown again); reported separately so it
                    is not mistaken for lost data
    ``unplanned``   data with no plan entry — a run nobody scheduled, or a plan
                    that was not kept up to date
    """
    have = set(actual_run_nos)
    by_run = {e.run_no: e for e in plan.entries}

    present, missing, superseded = [], [], []
    for e in plan.entries:
        if e.run_no in have:
            present.append(e.run_no)
            continue
        siblings = [r for r in e.cell_runs if r != e.run_no]
        if siblings and any(r in have for r in siblings):
            superseded.append({
                "run_no": e.run_no, "mach": e.mach, "label": e.row_label,
                "replaced_by": [r for r in siblings if r in have],
                "note": (f"该状态被重做：车次 {e.run_no} 无数据，"
                         f"由 {'、'.join(r for r in siblings if r in have)} 取代。"),
            })
        else:
            missing.append({"run_no": e.run_no, "mach": e.mach,
                            "label": e.row_label, "note": e.note})

    unplanned = sorted(r for r in have if r not in by_run)
    return {
        "planned": len(plan.entries),
        "present": sorted(present),
        "present_count": len(present),
        "missing": sorted(missing, key=lambda d: d["run_no"]),
        "superseded": sorted(superseded, key=lambda d: d["run_no"]),
        "unplanned": unplanned,
        "not_flown_count": len(plan.not_flown),
        "machs": plan.machs,
        "notes": plan.notes,
        "headline": _headline(plan, present, missing, superseded, unplanned),
    }


def _headline(plan: PlanTable, present: Sequence[str], missing: Sequence[Dict[str, Any]],
              superseded: Sequence[Dict[str, Any]], unplanned: Sequence[str]) -> str:
    bits = [f"计划 {len(plan.entries)} 个车次，实到 {len(present)} 个"]
    if superseded:
        bits.append(f"{len(superseded)} 个为重做前的废弃车次（属正常）")
    if missing:
        bits.append(f"**{len(missing)} 个计划内车次无数据**："
                    + "、".join(d["run_no"] for d in missing[:8]))
    if unplanned:
        bits.append(f"{len(unplanned)} 个车次不在计划表中：" + "、".join(unplanned[:8]))
    if plan.not_flown:
        bits.append(f"另有 {len(plan.not_flown)} 个状态在计划表中标注为未做")
    return "；".join(bits) + "。"


def plan_state_matches(entry: PlanEntry, state: Dict[str, Optional[float]],
                       mach: Optional[float], *, tol: float = 0.02) -> bool:
    """Does a run's parsed state agree with what the plan says it should be?

    A mismatch means either the file was written with the wrong state or the
    plan is stale — both worth surfacing, neither detectable from one side.
    """
    if entry.mach is not None and mach is not None and abs(entry.mach - mach) > 0.06:
        return False
    for k in ("BETA", "PHI", "dz", "dy", "dx"):
        a, b = entry.state.get(k), state.get(k)
        if a is None or b is None:
            continue
        if abs(a - b) > tol:
            return False
    return True
