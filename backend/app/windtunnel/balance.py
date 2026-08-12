"""Balance load library — the rated range of each balance's six units.

Why this is a first-class object rather than a hard-coded path
--------------------------------------------------------------
The overload check (`天平载荷超量程`) needs the *rated range* of the balance
that flew, and that number lives nowhere in the run's own files — only in the
tunnel's balance library. The legacy script hard-coded
``D:\\FD06\\TP\\天平载荷库(计算程序用勿删).txt`` and, when the balance was
missing, crashed with an ``IndexError`` that the caller swallowed into
``"PA 分析失败"``. A missing calibration record then looked like a parsing bug.

Here a missing entry is a *named, actionable state*: the feature reports
``unavailable`` with the balance name and the exact remedy, and the user can
add the entry from the UI.

File format (whitespace-separated, one balance per line, ``#`` comments)::

    N628E   3.0   40   5.0   270   2.0   30
    <name>  My    Z    Mz    Y     Mx    Q

The six numbers are the rated ranges of the balance's measuring units in the
canonical order ``My, Z, Mz, Y, Mx, Q`` — the same order used by the raw ``ca``
columns and by the calibration matrix printed in the ``pa`` report, so the
mapping needs no per-tunnel configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .parsers import BALANCE_UNITS, read_text


@dataclass
class BalanceEntry:
    name: str
    ranges: Dict[str, float]
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "ranges": self.ranges, "note": self.note}


@dataclass
class BalanceLibrary:
    entries: Dict[str, BalanceEntry] = field(default_factory=dict)

    # ── lookup ──────────────────────────────────────────────────────────
    def lookup(self, name: Optional[str]) -> Optional[BalanceEntry]:
        """Find a balance by name.

        Matching is deliberately forgiving, because the same physical balance
        is written three different ways across the run's own files:
        ``天平型式:TP202126``, ``天平弹性角公式:N636CB01``, and
        ``天平系统:N632Cb+N636E-N支杆…``. We try exact (case-insensitive),
        then prefix-of / contains in either direction.
        """
        if not name:
            return None
        key = name.strip().lower()
        if not key:
            return None
        if key in self.entries:
            return self.entries[key]
        for k, e in self.entries.items():
            if key.startswith(k) or k.startswith(key):
                return e
        for k, e in self.entries.items():
            if k in key or key in k:
                return e
        return None

    def names(self) -> List[str]:
        return sorted(e.name for e in self.entries.values())

    # ── mutation ────────────────────────────────────────────────────────
    def add(self, name: str, ranges: Dict[str, float], note: str = "") -> BalanceEntry:
        clean = {u: float(ranges[u]) for u in BALANCE_UNITS if u in ranges}
        missing = [u for u in BALANCE_UNITS if u not in clean]
        if missing:
            raise ValueError(f"缺少单元量程：{'、'.join(missing)}")
        entry = BalanceEntry(name=name.strip(), ranges=clean, note=note)
        self.entries[entry.name.lower()] = entry
        return entry

    def remove(self, name: str) -> bool:
        return self.entries.pop(name.strip().lower(), None) is not None

    # ── serialisation ───────────────────────────────────────────────────
    @classmethod
    def from_text(cls, text: str) -> "BalanceLibrary":
        lib = cls()
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            toks = line.split()
            if len(toks) < 7:
                continue
            try:
                vals = [float(t) for t in toks[1:7]]
            except ValueError:
                continue
            lib.entries[toks[0].lower()] = BalanceEntry(
                name=toks[0], ranges=dict(zip(BALANCE_UNITS, vals)),
                note=" ".join(toks[7:]),
            )
        return lib

    @classmethod
    def from_file(cls, path: Path | str) -> "BalanceLibrary":
        return cls.from_text(read_text(path))

    def to_text(self) -> str:
        lines = ["# 天平载荷库  name  My  Z  Mz  Y  Mx  Q"]
        for e in sorted(self.entries.values(), key=lambda x: x.name):
            vals = "  ".join(f"{e.ranges[u]:g}" for u in BALANCE_UNITS)
            lines.append(f"{e.name}  {vals}" + (f"  {e.note}" if e.note else ""))
        return "\n".join(lines) + "\n"

    def to_list(self) -> List[dict]:
        return [e.to_dict() for e in sorted(self.entries.values(), key=lambda x: x.name)]


#: Shipped seed — the public template the customer provided. Enough to make the
#: overload check produce a real verdict on the 91836–91840 demo runs.
SEED_BALANCE_TEXT = """\
# 天平载荷库(公开模板)  name  My  Z  Mz  Y  Mx  Q
N628E   3.0   40   5.0   270   2.0   30   来自甲方公开模板
"""


def default_library() -> BalanceLibrary:
    return BalanceLibrary.from_text(SEED_BALANCE_TEXT)
