"""User feedback — the in-the-moment "📍标记" a user drops while using the
product. Captures the thought together with the context it happened in, so it
becomes an actionable, replayable record instead of a vague memory.

This is the seed of the knowledge flywheel: when it fills up with real usage,
it grows into the candidate → review → promote loop.
"""

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import Feedback, User
from .deps import current_user, get_db

router = APIRouter(prefix="/feedback", tags=["feedback"])

# The four buckets a note can fall into. Anything else is coerced to "idea".
_KINDS = {"cannot", "wrong", "distrust", "idea"}

# Accepted screenshot mime → file extension. Decoded payload is capped so a
# pasted image can't bloat storage.
_IMG_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
_MAX_SHOT_BYTES = 8 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:(image/[a-zA-Z+]+);base64,(.+)$", re.DOTALL)


def _save_screenshot(data_url: str, fb_id: int) -> Optional[str]:
    """Decode a `data:image/...;base64,...` URL and write it under
    <upload>/feedback/. Returns the path RELATIVE to the upload root (portable
    if the bundle moves), or None if the payload isn't a usable image."""
    m = _DATA_URL_RE.match((data_url or "").strip())
    if not m:
        return None
    mime, payload = m.group(1).lower(), m.group(2)
    ext = _IMG_EXT.get(mime)
    if not ext:
        return None
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception:
        return None
    if not raw or len(raw) > _MAX_SHOT_BYTES:
        raise HTTPException(400, "截图过大或无效(上限 8MB)")
    root = get_settings().upload_path
    rel = f"feedback/fb_{fb_id}.{ext}"
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return rel


class CreateFeedbackReq(BaseModel):
    text: str
    kind: str = "idea"
    view: str = ""
    conversation_id: Optional[int] = None
    dataset_id: Optional[int] = None
    run_id: Optional[int] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    screenshot_b64: Optional[str] = None  # data:image/...;base64,...


class FeedbackResp(BaseModel):
    id: int
    kind: str
    text: str
    view: str
    conversation_id: Optional[int]
    dataset_id: Optional[int]
    run_id: Optional[int]
    context: Dict[str, Any]
    status: str
    created_at: str
    has_screenshot: bool = False


def _to_resp(f: Feedback) -> FeedbackResp:
    return FeedbackResp(
        id=f.id, kind=f.kind, text=f.text, view=f.view,
        conversation_id=f.conversation_id, dataset_id=f.dataset_id, run_id=f.run_id,
        context=f.context or {}, status=f.status,
        created_at=f.created_at.isoformat() if f.created_at else "",
        has_screenshot=bool(f.screenshot),
    )


@router.post("", response_model=FeedbackResp)
async def create_feedback(
    body: CreateFeedbackReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "反馈内容不能为空")
    kind = body.kind if body.kind in _KINDS else "idea"
    fb = Feedback(
        owner_id=user.id, kind=kind, text=text, view=body.view or "",
        conversation_id=body.conversation_id, dataset_id=body.dataset_id, run_id=body.run_id,
        context=body.context or {},
    )
    session.add(fb)
    # Flush to get the row id, so the screenshot file can be named by it.
    await session.flush()
    if body.screenshot_b64:
        fb.screenshot = _save_screenshot(body.screenshot_b64, fb.id)
    await session.commit()
    await session.refresh(fb)
    return _to_resp(fb)


@router.get("", response_model=List[FeedbackResp])
async def list_feedback(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Your own feedback; admins see everyone's — so you can triage what the
    expert has been dropping across sessions."""
    stmt = select(Feedback).order_by(Feedback.id.desc())
    if not user.is_admin:
        stmt = stmt.where(Feedback.owner_id == user.id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_resp(f) for f in rows]


_STATUSES = {"new", "triaged", "done"}


class UpdateFeedbackReq(BaseModel):
    status: Optional[str] = None
    kind: Optional[str] = None


@router.patch("/{feedback_id}", response_model=FeedbackResp)
async def update_feedback(
    feedback_id: int,
    body: UpdateFeedbackReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Triage a note: move it new → triaged → done, or re-bucket its kind.
    Admins can triage anyone's; a user only their own."""
    stmt = select(Feedback).where(Feedback.id == feedback_id)
    if not user.is_admin:
        stmt = stmt.where(Feedback.owner_id == user.id)
    fb = (await session.execute(stmt)).scalar_one_or_none()
    if fb is None:
        raise HTTPException(404, "feedback not found")
    if body.status is not None and body.status in _STATUSES:
        fb.status = body.status
    if body.kind is not None and body.kind in _KINDS:
        fb.kind = body.kind
    await session.commit()
    await session.refresh(fb)
    return _to_resp(fb)


@router.get("/{feedback_id}/screenshot")
async def get_screenshot(
    feedback_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Serve the note's screenshot INLINE (so an <img> can show it). Admins can
    see anyone's; a user only their own."""
    stmt = select(Feedback).where(Feedback.id == feedback_id)
    if not user.is_admin:
        stmt = stmt.where(Feedback.owner_id == user.id)
    fb = (await session.execute(stmt)).scalar_one_or_none()
    if fb is None or not fb.screenshot:
        raise HTTPException(404, "no screenshot")
    path = (get_settings().upload_path / fb.screenshot).resolve()
    if not path.exists():
        raise HTTPException(404, "screenshot file missing")
    return FileResponse(path)  # no filename → inline, media type inferred from ext
