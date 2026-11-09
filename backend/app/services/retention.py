"""Retention of intermediate results (改进清单-3 · R0–R4).

State & time rules (un-kept derived datasets and result files):
  * expires_at = created + RETENTION_DAYS (default 20)
  * user "延期": expires_at = now + RETENTION_DAYS, extended=True (no backstop)
  * listed as "即将清理" when expires_at - now <= NOTICE_DAYS (default 3)
  * notice_acked_at: set per item when the user acts on it in that list
    (保留 / 延期 / 立即清理 / 我知道了) — logging in does not count
  * cleaned when NOT kept and NOT protected and either
      ① expired AND acked AND acked >= 24 h ago, or
      ② never extended AND created >= MAX_DAYS (default 60) ago (backstop)
  * cleaning keeps the dataset ROW (state='cleaned'), deletes the file and the
    preview rows of the runs that produced it; lineage and runs stay readable.
Protected (never auto-cleaned): kept datasets and their whole ancestry,
promoted datasets' ancestry, a conversation's live pipeline head.
Result files (artifacts, one-off library outputs) expire after RETENTION_DAYS
without a reminder — save one as a derived dataset to keep it.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AppSetting, Artifact, Conversation, Dataset, Run
from . import storage

log = logging.getLogger(__name__)

DEFAULTS = {"retention_days": 20, "notice_days": 3, "max_days": 60}


async def get_policy(session: AsyncSession) -> Dict[str, int]:
    rows = (await session.execute(select(AppSetting).where(AppSetting.key.in_(list(DEFAULTS))))).scalars().all()
    out = dict(DEFAULTS)
    for r in rows:
        try:
            out[r.key] = max(1, int(r.value))
        except ValueError:
            pass
    return out


async def set_policy(session: AsyncSession, values: Dict[str, int]) -> Dict[str, int]:
    for k, v in values.items():
        if k not in DEFAULTS or v is None:
            continue
        row = await session.get(AppSetting, k)
        if row is None:
            session.add(AppSetting(key=k, value=str(int(v))))
        else:
            row.value = str(int(v))
    await session.commit()
    return await get_policy(session)


def _aware(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def protected_ids(session: AsyncSession, owner_id: int, rows: List[Dataset]) -> Set[int]:
    by_id = {d.id: d for d in rows}
    prot: Set[int] = set()
    for d in rows:
        if d.kept:
            prot.add(d.id)
        if d.kept or (d.kind == "source" and d.derived_from is not None):
            cur, guard = d.derived_from, 0
            while cur is not None and cur in by_id and guard < 1000:
                prot.add(cur)
                cur, guard = by_id[cur].derived_from, guard + 1
    convs = (await session.execute(select(Conversation).where(Conversation.owner_id == owner_id))).scalars().all()
    for c in convs:
        for entry in (c.pipeline_state or {}).values():
            hid = (entry or {}).get("head_id")
            if isinstance(hid, int):
                prot.add(hid)
    return prot


def _days_left(d: Dataset, now: datetime) -> Optional[float]:
    exp = _aware(d.expires_at)
    return None if exp is None else (exp - now).total_seconds() / 86400


async def expiring(session: AsyncSession, owner_id: int) -> List[Dict[str, Any]]:
    """The "即将清理" list: un-kept, unprotected, active intermediates whose
    expiry is within NOTICE_DAYS (or already past, waiting for an ack)."""
    pol = await get_policy(session)
    now = datetime.now(timezone.utc)
    rows = (await session.execute(select(Dataset).where(Dataset.owner_id == owner_id))).scalars().all()
    prot = await protected_ids(session, owner_id, rows)
    out = []
    for d in rows:
        if d.kind != "derived" or d.kept or d.state != "active" or d.id in prot or d.expires_at is None:
            continue
        left = _days_left(d, now)
        backstop = None if d.extended else (_aware(d.created_at) + timedelta(days=pol["max_days"]) - now).total_seconds() / 86400
        if left is not None and left <= pol["notice_days"] or (backstop is not None and backstop <= pol["notice_days"]):
            out.append({"id": d.id, "name": d.name, "days_left": round(min(x for x in (left, backstop) if x is not None), 2),
                        "acked": d.notice_acked_at is not None, "size_bytes": d.size_bytes})
    out.sort(key=lambda x: x["days_left"])
    return out


async def act(session: AsyncSession, owner_id: int, ids: List[int], action: str) -> Dict[str, Any]:
    """User action on items of the reminder list: keep | extend | clean | ack.
    Any of them counts as having seen the reminder for that item."""
    pol = await get_policy(session)
    now = datetime.now(timezone.utc)
    rows = (await session.execute(select(Dataset).where(Dataset.owner_id == owner_id, Dataset.id.in_(ids)))).scalars().all()
    done = 0
    for d in rows:
        if d.kind != "derived" or d.state != "active":
            continue
        d.notice_acked_at = now
        if action == "keep":
            d.kept = True
        elif action == "extend":
            d.expires_at = now + timedelta(days=pol["retention_days"])
            d.extended = True
            d.notice_acked_at = None   # a new period → a new reminder
        elif action == "clean":
            await clean_dataset(session, d)
        done += 1
    await session.commit()
    return {"ok": True, "count": done}


async def clean_dataset(session: AsyncSession, d: Dataset) -> bool:
    """Remove the file, keep the row (state='cleaned'), drop the preview rows
    of the runs that produced it. Returns False when the file couldn't be
    deleted (state stays active, clean_error set → retried next sweep)."""
    from .datasets import dataset_file
    try:
        p = dataset_file(d)
        if p.exists():
            p.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        d.clean_error = f"{type(e).__name__}: {e}"[:500]
        return False
    d.state = "cleaned"
    d.cleaned_at = datetime.now(timezone.utc)
    d.clean_error = ""
    sj = dict(d.schema_json or {})
    sj.pop("head", None)
    d.schema_json = sj
    await session.execute(update(Run).where(Run.result_dataset_id == d.id).values(data_cleaned=True, result_summary={}))
    return True


async def sweep_user(session: AsyncSession, owner_id: int, *, force_all: bool = False) -> Dict[str, Any]:
    """Apply the rules for one user. force_all = the manual 「清理中间结果」
    button: clean every un-kept, unprotected intermediate now."""
    pol = await get_policy(session)
    now = datetime.now(timezone.utc)
    rows = (await session.execute(select(Dataset).where(Dataset.owner_id == owner_id))).scalars().all()
    prot = await protected_ids(session, owner_id, rows)
    cleaned, failed, freed = [], 0, 0
    for d in sorted(rows, key=lambda x: x.id, reverse=True):   # deepest first
        if d.kind != "derived" or d.kept or d.state != "active" or d.id in prot:
            continue
        exp, acked, created = _aware(d.expires_at), _aware(d.notice_acked_at), _aware(d.created_at)
        due = force_all or (
            (exp is not None and exp <= now and acked is not None and acked <= now - timedelta(hours=24))
            or (not d.extended and created is not None and created <= now - timedelta(days=pol["max_days"]))
        )
        if not due:
            continue
        size = int(d.size_bytes or 0)
        if await clean_dataset(session, d):
            cleaned.append({"id": d.id, "name": d.name})
            freed += size
        else:
            failed += 1
    # one-off result files: expire without a reminder
    arts = (await session.execute(select(Artifact).where(Artifact.owner_id == owner_id, Artifact.state == "active"))).scalars().all()
    for a in arts:
        exp = _aware(a.expires_at) or (_aware(a.created_at) + timedelta(days=pol["retention_days"]))
        if force_all or exp <= now:
            try:
                f = storage.resolve_owned(a.rel_path, a.owner_id)
                if f.exists():
                    f.unlink()
                a.state = "cleaned"
            except storage.PathNotOwned:
                a.state = "cleaned"
            except OSError:
                failed += 1
    await session.commit()
    return {"cleaned": cleaned, "count": len(cleaned), "failed": failed, "freed_bytes": freed}


# ── background job: once at startup, then daily; one process at a time ──────

_LOCK_NAME = ".retention.lock"


def _acquire_lock(stale_seconds: int = 3600) -> Optional[Path]:
    lock = storage.upload_root() / _LOCK_NAME
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > stale_seconds:
            lock.unlink()   # a crashed run — take over
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return lock
    except FileExistsError:
        return None
    except OSError:
        return None


async def sweep_all() -> Dict[str, Any]:
    from ..db.base import SessionLocal
    from ..db.models import User
    lock = _acquire_lock()
    if lock is None:
        return {"skipped": "another sweep is running"}
    try:
        total = 0
        async with SessionLocal() as session:
            uids = [u for (u,) in (await session.execute(select(User.id))).all()]
            for uid in uids:
                try:
                    total += (await sweep_user(session, uid))["count"]
                except Exception:  # noqa: BLE001
                    log.exception("retention sweep failed for user %s", uid)
                    await session.rollback()
        return {"cleaned": total}
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


async def daily_loop() -> None:
    import asyncio
    while True:
        try:
            r = await sweep_all()
            if r.get("cleaned"):
                log.info("retention sweep: %s", r)
        except Exception:  # noqa: BLE001
            log.exception("retention sweep crashed")
        await asyncio.sleep(24 * 3600)
