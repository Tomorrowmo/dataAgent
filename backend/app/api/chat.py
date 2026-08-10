import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Conversation, Dataset, Message, User
from ..services.chat_agent import run_turn
from ..services.datasets import save_temp_upload
from ..services.image_parser import IMAGE_EXTS
from .deps import current_user, get_db, llm_for

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

# Headers that keep Server-Sent-Events flowing token-by-token instead of being
# buffered into one lump by a reverse proxy / CDN. `X-Accel-Buffering: no` is the
# one nginx honours PER-RESPONSE — so streaming works even if the server's nginx
# location lacks `proxy_buffering off`. `no-transform` stops proxies/CDNs from
# compressing (which would re-buffer). Without these, the agent's reply appeared
# only after the whole turn finished — the "不是流式输出" symptom.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class CreateConvReq(BaseModel):
    title: Optional[str] = None
    dataset_id: Optional[int] = None


class ConvResp(BaseModel):
    id: int
    title: str
    dataset_id: Optional[int]


class MessageResp(BaseModel):
    id: int
    role: str
    content: str
    meta: Dict[str, Any] = Field(default_factory=dict)


@router.post("/conversations", response_model=ConvResp)
async def create_conv(
    body: CreateConvReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    conv = Conversation(
        owner_id=user.id,
        title=body.title or "New session",
        dataset_id=body.dataset_id,
    )
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return ConvResp(id=conv.id, title=conv.title, dataset_id=conv.dataset_id)


@router.get("/conversations", response_model=List[ConvResp])
async def list_convs(user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(
        select(Conversation).where(Conversation.owner_id == user.id).order_by(Conversation.id.desc())
    )).scalars().all()
    return [ConvResp(id=c.id, title=c.title, dataset_id=c.dataset_id) for c in rows]


class RenameConvReq(BaseModel):
    title: str


@router.patch("/conversations/{conv_id}", response_model=ConvResp)
async def rename_conv(
    conv_id: int,
    body: RenameConvReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Rename a conversation."""
    conv = (await session.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.owner_id == user.id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "conversation not found")
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    conv.title = title[:200]
    await session.commit()
    await session.refresh(conv)
    return ConvResp(id=conv.id, title=conv.title, dataset_id=conv.dataset_id)


@router.delete("/conversations/{conv_id}")
async def delete_conv(
    conv_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Delete a conversation and all its messages."""
    conv = (await session.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.owner_id == user.id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "conversation not found")
    await session.execute(delete(Message).where(Message.conversation_id == conv_id))
    await session.execute(delete(Conversation).where(Conversation.id == conv_id))
    await session.commit()
    return {"ok": True}


@router.get("/conversations/{conv_id}/messages", response_model=List[MessageResp])
async def list_messages(
    conv_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    conv = (await session.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.owner_id == user.id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "conversation not found")
    msgs = (await session.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)
    )).scalars().all()
    return [MessageResp(id=m.id, role=m.role, content=m.content, meta=m.meta or {}) for m in msgs]


@router.get("/conversations/{conv_id}/pipeline")
async def get_pipeline(
    conv_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Current cross-turn pipeline head per dataset (for the chat 'continuing
    pipeline' chip). Empty dict = fresh / no active pipeline."""
    conv = (await session.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.owner_id == user.id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "conversation not found")
    return {"pipeline_state": conv.pipeline_state or {}}


@router.post("/conversations/{conv_id}/reset-pipeline")
async def reset_pipeline(
    conv_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Drop the cross-turn pipeline state so the next message starts from the
    ORIGINAL data again (the user clicked 重置流水线)."""
    conv = (await session.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.owner_id == user.id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "conversation not found")
    conv.pipeline_state = {}
    await session.commit()
    return {"ok": True}


class SendReq(BaseModel):
    message: str
    dataset_id: Optional[int] = None
    # Multi-dataset: the full set of datasets active in this turn. The first is
    # treated as PRIMARY. Falls back to dataset_id / the conversation's dataset.
    dataset_ids: Optional[List[int]] = None
    # An image the user attached to THIS message (a chart/plot/diagram to analyze
    # or digitize). Ref = the token returned by POST /chat/upload-image. The agent
    # sees it and can call `analyze_image`. Distinct from dataset upload (which
    # OCRs a table); here the image is analysis context driven by the question.
    image_ref: Optional[str] = None


@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    """Stash an image for use in the NEXT chat message. Returns a ref the client
    passes back as `image_ref` on /send. Kept separate from /send so that
    endpoint stays a small JSON body + SSE stream (no multipart streaming)."""
    ext = "." + (file.filename or "img.png").rsplit(".", 1)[-1].lower()
    if ext not in IMAGE_EXTS:
        raise HTTPException(400, f"不支持的图片格式 {ext};支持 {', '.join(sorted(IMAGE_EXTS))}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "图片太大(上限 20MB)")
    path = save_temp_upload(data, file.filename or f"chat_image{ext}")
    # The ref is just the saved path; the agent reads it back by path. Basename is
    # returned for display only.
    return {"ref": str(path), "name": file.filename or f"image{ext}", "ext": ext}


@router.post("/conversations/{conv_id}/send")
async def send_message(
    conv_id: int,
    body: SendReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    conv = (await session.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.owner_id == user.id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "conversation not found")

    # Resolve the active dataset set: explicit dataset_ids (primary first) win,
    # then dataset_id, then the conversation's stored dataset. Dedupe, keep order.
    id_order: List[int] = []
    for did in (body.dataset_ids or []):
        if did not in id_order:
            id_order.append(did)
    if body.dataset_id and body.dataset_id not in id_order:
        id_order.append(body.dataset_id)
    if conv.dataset_id and conv.dataset_id not in id_order:
        id_order.append(conv.dataset_id)

    datasets: List[Dataset] = []
    for did in id_order:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == did, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds is not None:
            datasets.append(ds)

    # Persist the primary as the conversation's dataset (back-compat / reload).
    if datasets and conv.dataset_id != datasets[0].id:
        conv.dataset_id = datasets[0].id

    # Resolve the image for THIS turn. A fresh attachment wins; otherwise the
    # image is STICKY across the conversation — the user naturally expects "the
    # chart I uploaded" to stay available for follow-up questions, not vanish
    # after one message. So when nothing new is attached, reuse the most recent
    # prior image in this conversation that's still on disk.
    from pathlib import Path as _Path
    image_ref: Optional[str] = None
    image_fresh = False  # True only when THIS message carried a new image
    if body.image_ref:
        p = _Path(body.image_ref)
        if p.exists() and p.is_file():
            image_ref = str(p)
            image_fresh = True
        else:
            raise HTTPException(400, "图片引用无效或已过期,请重新上传图片。")
    else:
        prior = (await session.execute(
            select(Message).where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.id.desc())
        )).scalars().all()
        for m in prior:
            ref = (m.meta or {}).get("image_ref")
            if ref and _Path(ref).exists():
                image_ref = ref
                break

    # Persist user message immediately. Record the image on meta so a reload shows
    # "(附了一张图)" and the ref survives (best-effort; temp files are transient).
    user_msg = Message(
        conversation_id=conv.id, role="user", content=body.message,
        meta={"image_ref": image_ref} if image_ref else {},
    )
    session.add(user_msg)
    await session.commit()

    # Load full history for context.
    history_rows = (await session.execute(
        select(Message).where(Message.conversation_id == conv.id, Message.role.in_(["user", "assistant"]))
        .order_by(Message.id)
    )).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in history_rows[:-1]]  # exclude the just-added one

    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set a DeepSeek key in Settings.")

    # Cross-turn pipeline state: seed from what prior turns produced, let
    # run_turn mutate it as new stages materialize, then persist it back so the
    # NEXT message keeps composing on this turn's result.
    pipeline_state: Dict[str, Any] = dict(conv.pipeline_state or {})

    async def event_stream():
        events: List[Dict[str, Any]] = []
        final_text = ""
        got_final = False
        cancelled = False

        # Prime the connection: an SSE comment line flushed before any slow work
        # forces the proxy to open the pipe to the client immediately, so the
        # first real token isn't held back behind a buffering threshold. The
        # frontend parser ignores any block that doesn't start with "data:".
        yield ": numetrix-stream-open\n\n"

        async def _yield(event: Dict[str, Any]):
            # Yielding can itself fail if the client has already disconnected.
            # We still want the event recorded in `events` so the DB row carries
            # the full trace — so callers append BEFORE awaiting this.
            try:
                return f"data: {json.dumps(event, default=str)}\n\n"
            except Exception:  # pragma: no cover — json failure is essentially never
                logger.exception("failed to serialize SSE event")
                return f"data: {{\"kind\":\"final\",\"payload\":{{\"text\":\"(serialization failed)\",\"error\":true}}}}\n\n"

        try:
            try:
                async for step in run_turn(
                    session=session, llm=llm, owner_id=user.id, datasets=datasets,
                    history=history, user_message=body.message, max_steps=8,
                    pipeline_state=pipeline_state, image_ref=image_ref, image_fresh=image_fresh,
                ):
                    event = {"kind": step.kind, "payload": step.payload}
                    events.append(event)
                    yield await _yield(event)
                    if step.kind == "final":
                        final_text = step.payload.get("text", "")
                        got_final = True
            except asyncio.CancelledError:
                # Client disconnected mid-stream. We can't send anything more,
                # but the finally block below still persists what we collected.
                cancelled = True
                event = {"kind": "final", "payload": {
                    "text": "(client disconnected before the agent finished)",
                    "cancelled": True,
                }}
                events.append(event)
                final_text = event["payload"]["text"]
                got_final = True
                raise
            except Exception as e:
                # LLM timeout / network / parser crash / sandbox crash. Surface
                # as a final event the UI can render, plus a diagnostic hint.
                hint = _diagnostic_hint(e)
                err_text = f"**Agent error:** {type(e).__name__}: {e}"
                if hint:
                    err_text += f"\n\n💡 {hint}"
                event = {"kind": "final", "payload": {
                    "text": err_text, "error": True, "exc_type": type(e).__name__,
                }}
                events.append(event)
                final_text = err_text
                got_final = True
                logger.exception("agent crash in conv=%s msg=%r", conv.id, body.message[:80])
                yield await _yield(event)

            if not got_final:
                fallback = {"kind": "final", "payload": {"text": "(agent stopped without a final answer)"}}
                events.append(fallback)
                final_text = fallback["payload"]["text"]
                yield await _yield(fallback)
        finally:
            # ALWAYS persist whatever we collected. Without this, a mid-stream
            # cancel (user navigates away, network blip, second send racing the
            # first) leaves the user with no assistant row in history at all —
            # the symptom that prompted this whole rework.
            try:
                assistant_msg = Message(
                    conversation_id=conv.id, role="assistant",
                    content=final_text or "(no output)",
                    meta={"events": events, "cancelled": cancelled} if cancelled else {"events": events},
                )
                session.add(assistant_msg)
                # Persist the advanced pipeline head so the next turn continues
                # the chain. Use an explicit UPDATE rather than ORM attribute
                # assignment: across the streaming generator's mid-turn commits
                # the `conv` instance's dirty-state on a JSON column wasn't being
                # flushed, so the head silently never persisted.
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conv.id)
                    .values(pipeline_state=dict(pipeline_state))
                )
                await session.commit()
            except Exception:
                logger.exception("failed to persist assistant message for conv=%s", conv.id)
            # Opportunistic auto-GC: reclaim OLD un-kept intermediates from past
            # sessions. The grace window + head-protection keep THIS turn's fresh
            # stages and the live pipeline head safe. Best-effort — never let a
            # cleanup failure surface to the user.
            try:
                from ..services.datasets import gc_derived_datasets
                await gc_derived_datasets(session, owner_id=user.id)
            except Exception:
                logger.exception("auto-GC failed for owner=%s", user.id)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


def _diagnostic_hint(exc: Exception) -> str:
    """Map common failure modes to a short, user-actionable hint. Keep this
    small — the rule is one sentence pointing at the most likely cause, not a
    full troubleshooting tree."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if "apikey" in msg or "api_key" in msg or "unauthorized" in msg or name in ("AuthenticationError",):
        return "LLM rejected the credentials. Re-check your API key in Settings."
    if "timeout" in msg or name in ("TimeoutError", "ReadTimeout", "ConnectTimeout"):
        return "LLM call timed out. The provider may be slow — retry, or pick a faster model in Settings."
    if "rate" in msg and "limit" in msg:
        return "Provider rate-limited the call. Wait a few seconds and retry."
    if "connection" in msg or "name or service" in msg or "getaddrinfo" in msg:
        return "Could not reach the LLM endpoint. Check your network and the Base URL in Settings."
    if "json" in msg and ("decode" in msg or "parse" in msg):
        return "The model returned malformed JSON. Try sending the same message again — it usually self-corrects."
    return ""
