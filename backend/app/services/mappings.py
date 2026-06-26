"""Column-meaning mapping rules — the consult side of the expert-knowledge loop.

`apply_rules(columns, rules)` is what gets called at DECISION TIME (dataset
profiling, and later column picking): given the real column names of a dataset
and the rules visible to the user, return which columns the expert's rules
recognize and what they mean. This is the "read back" half — without it,
sedimented judgment would be write-only and change nothing.
"""

import re
from typing import Any, Dict, List


def normalize(name: str) -> str:
    """Loose, robust key: lowercase, drop everything but letters/digits. So
    'U(V)', 'u (v)', 'U_V' all collapse to 'uv' and match the same rule."""
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _matches(col: str, pattern: str, match_type: str) -> bool:
    if match_type == "exact":
        return col == pattern
    if match_type == "contains":
        return pattern.lower() in col.lower()
    if match_type == "regex":
        try:
            return re.search(pattern, col, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    # default: normalized equality
    return normalize(col) == normalize(pattern)


def apply_rules(columns: List[str], rules: List[Any]) -> List[Dict[str, Any]]:
    """Return one entry per (column, matching rule). First matching rule per
    column wins, so a user's own rule shadows a public one if listed first."""
    out: List[Dict[str, Any]] = []
    seen_cols: set[str] = set()
    for col in columns:
        c = str(col)
        for r in rules:
            if c in seen_cols:
                break
            if _matches(c, r.pattern, r.match_type):
                out.append({
                    "column": c,
                    "role": r.role,
                    "label": r.label or r.role,
                    "rule_id": r.id,
                    "source": r.source,
                    "match_type": r.match_type,
                })
                seen_cols.add(c)
                break
    return out
