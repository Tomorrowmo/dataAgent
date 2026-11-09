"""Result files ("artifacts"): register algorithm outputs per user and look them
up by id with an owner check. See services/storage.py for the layout rules."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Artifact
from . import storage

log = logging.getLogger(__name__)


async def adopt(session: AsyncSession, owner_id: int, result: Dict[str, Any], *,
                kind: str = "result", commit: bool = True) -> Dict[str, Any]:
    """Move a freshly produced scratch file (result['result_path']) into the
    owner's tmp/ directory, register it, and put `artifact_id` on the result.
    `result_path` is kept (now pointing at the owned file) for in-process use;
    it is scrubbed before anything leaves the API."""
    rp = result.get("result_path")
    if not rp:
        return result
    src = Path(rp)
    if not src.exists():
        return result
    dest = storage.new_file(storage.user_dir(owner_id, "tmp"), stem=kind)
    try:
        shutil.move(str(src), str(dest))
    except OSError:
        log.exception("could not move result %s", src)
        return result
    a = Artifact(
        owner_id=owner_id, rel_path=storage.to_rel(dest), kind=kind,
        size_bytes=dest.stat().st_size, rows=int(result.get("result_rows") or 0),
    )
    session.add(a)
    if commit:
        await session.commit()
    else:
        await session.flush()
    result["artifact_id"] = a.id
    result["result_path"] = str(dest)
    return result


def discard_scratch(result: Dict[str, Any]) -> None:
    """Delete a scratch output that the caller has already consumed (e.g. read
    into a derived dataset). Only touches files inside the internal scratch dir."""
    rp = result.get("result_path")
    if not rp:
        return
    p = Path(rp).resolve()
    try:
        p.relative_to(storage.scratch_dir().resolve())
    except ValueError:
        return
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


async def get_owned(session: AsyncSession, artifact_id: int, owner_id: int) -> Optional[Artifact]:
    return (await session.execute(
        select(Artifact).where(Artifact.id == artifact_id, Artifact.owner_id == owner_id)
    )).scalar_one_or_none()


def file_of(a: Artifact) -> Path:
    return storage.resolve_owned(a.rel_path, a.owner_id)
