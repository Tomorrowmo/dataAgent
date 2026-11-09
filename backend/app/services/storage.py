"""Where files live on disk, and the ONE place that turns a stored path into a
real file path.

Layout under the upload root (settings.upload_path):
    user_{id}/sources/        uploaded originals
    user_{id}/runs/YYYY-MM/   run outputs / derived datasets
    user_{id}/tmp/            transient algorithm results (artifacts)
    user_{id}/staging/        upload staging (parser flow)
    _staging/                 sandbox / builtin scratch output — internal only,
                              consumed or adopted immediately, never served

Rules:
  * The database stores paths RELATIVE to the upload root, POSIX separators.
  * Reading a stored path always goes through `resolve_owned()`, which refuses
    anything outside the owner's own `user_{id}/` directory. Legacy rows hold
    absolute paths; those are accepted only when they also sit inside the
    owner's directory.
  * API responses never contain server paths — `scrub()` removes them.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from ..core.config import get_settings


def upload_root() -> Path:
    return get_settings().upload_path.resolve()


def user_dir(owner_id: int, sub: str = "") -> Path:
    p = upload_root() / f"user_{int(owner_id)}"
    if sub:
        p = p / sub
    p.mkdir(parents=True, exist_ok=True)
    return p


def runs_dir(owner_id: int) -> Path:
    return user_dir(owner_id, f"runs/{datetime.now(timezone.utc):%Y-%m}")


def scratch_dir() -> Path:
    """Internal scratch for sandbox / builtin outputs (never served)."""
    p = upload_root() / "_staging"
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_file(directory: Path, stem: str = "", suffix: str = ".parquet") -> Path:
    safe = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_")[:60]
    name = f"{safe + '_' if safe else ''}{uuid.uuid4().hex[:12]}{suffix}"
    return directory / name


def to_rel(path: str | Path) -> str:
    """Absolute path under the upload root → stored relative POSIX string."""
    p = Path(path).resolve()
    rel = p.relative_to(upload_root())
    return PurePosixPath(*rel.parts).as_posix()


class PathNotOwned(Exception):
    pass


def resolve_owned(stored: str, owner_id: int) -> Path:
    """Stored path (relative, or legacy absolute) → real path, guaranteed to be
    inside `user_{owner_id}/`. Raises PathNotOwned otherwise."""
    if not stored:
        raise PathNotOwned("empty path")
    root = upload_root()
    p = Path(stored)
    target = (p if p.is_absolute() else root / Path(*PurePosixPath(stored).parts)).resolve()
    own = (root / f"user_{int(owner_id)}").resolve()
    try:
        target.relative_to(own)
    except ValueError:
        raise PathNotOwned(stored)
    return target


def startup_housekeeping(max_scratch_age_hours: int = 24) -> dict:
    """Run once at startup:
      * retire the legacy shared `results/` directory (files there have no owner
        and can no longer be served — see 改进清单-3 前提);
      * drop internal scratch files older than `max_scratch_age_hours`
        (normally consumed / adopted within the same request)."""
    import shutil
    import time
    out = {"legacy_results_removed": 0, "scratch_removed": 0}
    legacy = upload_root() / "results"
    if legacy.is_dir():
        out["legacy_results_removed"] = sum(1 for _ in legacy.rglob("*") if _.is_file())
        shutil.rmtree(legacy, ignore_errors=True)
    cutoff = time.time() - max_scratch_age_hours * 3600
    for f in scratch_dir().glob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                out["scratch_removed"] += 1
        except OSError:
            pass
    return out


# ── keeping server paths out of API responses ───────────────────────────────

_PATH_KEYS = {"result_path", "storage_path", "output_path", "workdir", "parser_file"}


def _path_patterns() -> list[re.Pattern]:
    root = upload_root()
    forms = {str(root), root.as_posix()}
    pats = [re.compile(re.escape(f) + r"[\\/]?", re.IGNORECASE) for f in sorted(forms, key=len, reverse=True)]
    # sandbox temp workdirs: tempfile.mkdtemp(prefix="da_sbox_"), e.g.
    # C:\Users\x\AppData\Local\Temp\da_sbox_ab12\  or  /tmp/da_sbox_ab12/
    pats.append(re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\\/\s'\"]+)*?[\\/]da_sbox_[\w\-]+[\\/]?", re.IGNORECASE))
    return pats


def scrub_text(s: str) -> str:
    for pat in _path_patterns():
        s = pat.sub("", s)
    return s


def scrub(obj: Any) -> Any:
    """Recursively drop path-bearing keys and strip server paths from strings."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in _PATH_KEYS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(scrub(v) for v in obj)
    if isinstance(obj, str):
        return scrub_text(obj)
    return obj
