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
from ..services.storage import scrub, scrub_text
from ..services.chat_agent import run_turn
from ..services import chat_turns
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
    created_at: Optional[str] = None


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
    return [ConvResp(id=c.id, title=c.title, dataset_id=c.dataset_id, created_at=c.created_at.isoformat() if c.created_at else None) for c in rows]


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
    # Detach the runs from the deleted conversation: SQLite may hand the same id
    # to a later conversation, which would otherwise inherit these results.
    # Their origin then reads 「（已删除的对话）」.
    from ..db.models import RunGroup
    await session.execute(update(RunGroup).where(RunGroup.conversation_id == conv_id, RunGroup.owner_id == user.id)
                          .values(conversation_id=None))
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


async def _owned_message(session: AsyncSession, conv_id: int, msg_id: int, user: User):
    conv = (await session.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.owner_id == user.id)
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "conversation not found")
    msg = (await session.execute(
        select(Message).where(Message.id == msg_id, Message.conversation_id == conv_id)
    )).scalar_one_or_none()
    if msg is None or msg.role != "assistant":
        raise HTTPException(404, "message not found")
    return conv, msg


@router.get("/conversations/{conv_id}/messages/{msg_id}/rerun")
async def rerun_check(
    conv_id: int,
    msg_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Can this turn's algorithm steps be re-run? (drives the button state)"""
    from ..services.rerun import plan_rerun
    conv, msg = await _owned_message(session, conv_id, msg_id, user)
    plan, _ = await plan_rerun(session, user.id, conv, (msg.meta or {}).get("events") or [])
    return {"ok": plan.blocked is None, "reason": plan.blocked, "steps": len(plan.steps)}


@router.post("/conversations/{conv_id}/messages/{msg_id}/rerun", response_model=MessageResp)
async def rerun_message(
    conv_id: int,
    msg_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Replay a past turn's algorithm steps on the original data (no LLM) and
    append the outcome as a new assistant message in the same conversation."""
    from ..services.rerun import execute_rerun, plan_rerun
    conv, msg = await _owned_message(session, conv_id, msg_id, user)
    plan, resolved = await plan_rerun(session, user.id, conv, (msg.meta or {}).get("events") or [])
    if plan.blocked:
        raise HTTPException(409, plan.blocked)
    events = await execute_rerun(session, user.id, plan, resolved, conversation_id=conv.id)
    ok = sum(1 for e in events if e["kind"] == "tool_result" and (e["payload"].get("result") or {}).get("status") == "ok")
    # The time of the original turn is shown by the client (local timezone)
    # from meta.rerun_of_at — the server runs in UTC.
    text = (f"已在原始数据上重新运行这次分析的 {len(plan.steps)} 个算法步骤，结果如下。"
            if ok == len(plan.steps) else
            f"重新运行时第 {ok + 1} 步失败，后续步骤没有执行。")
    events.append({"kind": "final", "payload": {"text": text}})
    created = msg.created_at.isoformat() if msg.created_at else None
    new = Message(conversation_id=conv.id, role="assistant", content=text,
                  meta={"events": events, "rerun_of": msg.id, "rerun_of_at": created})
    session.add(new)
    await session.commit()
    await session.refresh(new)
    return MessageResp(id=new.id, role=new.role, content=new.content, meta=new.meta or {})


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
    ORIGINAL data again (the user clicked 改用原始数据 above the chat input)."""
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
    # Skills the user enabled for this message (their instructions + tools are
    # given to the agent); the user's other active skills are only offered as
    # recommendations.
    skill_ids: Optional[List[int]] = None
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
    # Owner-scoped (改进清单-3 · F2): the image lives in the user's tmp/ and the
    # ref handed to the client is RELATIVE — /send only accepts refs inside the
    # sender's own directory.
    from ..services import storage
    path = storage.new_file(storage.user_dir(user.id, "tmp"), stem="chat_image", suffix=ext)
    path.write_bytes(data)
    return {"ref": storage.to_rel(path), "name": file.filename or f"image{ext}", "ext": ext}


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
    if chat_turns.running(conv.id, user.id) is not None:
        raise HTTPException(409, "上一条回答还在生成，等它完成或先停止再发送。")

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
        if ds is not None and (ds.state or "active") != "cleaned":   # cleaned data can't be analysed
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
    from ..services.storage import PathNotOwned, resolve_owned, to_rel

    def _own_image(ref: str) -> Optional[_Path]:
        try:
            p = resolve_owned(ref, user.id)     # must sit inside the sender's directory
        except PathNotOwned:
            return None
        return p if p.exists() and p.is_file() else None

    if body.image_ref:
        p = _own_image(body.image_ref)
        if p is None:
            raise HTTPException(400, "图片引用无效或已过期,请重新上传图片。")
        image_ref = str(p)
        image_fresh = True
    else:
        prior = (await session.execute(
            select(Message).where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.id.desc())
        )).scalars().all()
        for m in prior:
            ref = (m.meta or {}).get("image_ref")
            p = _own_image(ref) if ref else None
            if p is not None:
                image_ref = str(p)
                break

    # Persist user message immediately. Record the image on meta so a reload shows
    # "(附了一张图)" and the ref survives (best-effort; temp files are transient).
    user_msg = Message(
        conversation_id=conv.id, role="user", content=body.message,
        meta={
            **({"image_ref": to_rel(image_ref)} if image_ref else {}),   # stored relative, never a server path
            # Every source dataset loaded for this turn (primary first): reopening the
            # conversation restores ALL of them, not just the primary — a second
            # dataset used only for comparison would otherwise silently drop out.
            **({"dataset_ids": [d.id for d in datasets]} if datasets else {}),
        },
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

    # Everything the turn needs, as plain values: it runs in its OWN task and DB
    # session (see services/chat_turns), outliving this request if the client leaves.
    turn = chat_turns.start(conv.id, user.id)
    turn.task = asyncio.create_task(_run_turn_task(
        turn, owner_id=user.id, llm=llm, dataset_ids=[d.id for d in datasets], history=history,
        message=body.message, image_ref=image_ref, image_fresh=image_fresh, skill_ids=body.skill_ids,
    ))
    return StreamingResponse(turn.follow(0), media_type="text/event-stream", headers=SSE_HEADERS)


async def _run_turn_task(turn: "chat_turns.Turn", *, owner_id: int, llm: Any, dataset_ids: List[int],
                         history: List[Dict[str, str]], message: str, image_ref: Optional[str],
                         image_fresh: bool, skill_ids: Optional[List[int]]) -> None:
    """One chat turn, start to finish, independent of any HTTP connection.
    Always ends by saving the assistant message: a finished answer, an error, or
    (after an explicit stop) what was produced so far."""
    from ..db.base import SessionLocal
    from .skills import load_for_chat

    conv_id = turn.conv_id
    final_text = ""
    got_final = False
    cancelled = False
    turn_ctx: Dict[str, Any] = {}     # filled by run_turn: this turn's run group (改进清单-3 · D1a)
    pipeline_state: Dict[str, Any] = {}

    async with SessionLocal() as session:
        try:
            try:
                conv = await session.get(Conversation, conv_id)
                pipeline_state = dict((conv.pipeline_state if conv else None) or {})
                datasets: List[Dataset] = []
                for did in dataset_ids:
                    ds = await session.get(Dataset, did)
                    if ds is not None:
                        datasets.append(ds)
                skills_selected, skills_catalog = await load_for_chat(session, owner_id, skill_ids)
                async for step in run_turn(
                    session=session, llm=llm, owner_id=owner_id, datasets=datasets,
                    history=history, user_message=message, max_steps=8,
                    pipeline_state=pipeline_state, image_ref=image_ref, image_fresh=image_fresh,
                    skills=skills_selected, skill_catalog=skills_catalog,
                    turn_ctx=turn_ctx, conversation_id=conv_id,
                ):
                    # No server paths in what the client sees or what gets stored.
                    await turn.push(scrub({"kind": step.kind, "payload": step.payload}))
                    if step.kind == "final":
                        final_text = step.payload.get("text", "")
                        got_final = True
            except asyncio.CancelledError:
                # Explicit stop (POST .../stop). Keep what was produced; saved below.
                cancelled = True
                event = {"kind": "final", "payload": {"text": "（已停止生成）", "cancelled": True}}
                turn.events.append(event)
                final_text, got_final = event["payload"]["text"], True
            except Exception as e:
                # LLM timeout / network / parser crash / sandbox crash. Surface
                # as a final event the UI can render, plus a diagnostic hint.
                hint = _diagnostic_hint(e)
                err_text = scrub_text(f"**Agent error:** {type(e).__name__}: {e}")
                if hint:
                    err_text += "\n\n" + hint
                event = {"kind": "final", "payload": {"text": err_text, "error": True, "exc_type": type(e).__name__}}
                await turn.push(event)
                final_text, got_final = err_text, True
                logger.exception("agent crash in conv=%s msg=%r", conv_id, message[:80])

            if not got_final:
                fallback = {"kind": "final", "payload": {"text": "(agent stopped without a final answer)"}}
                await turn.push(fallback)
                final_text = fallback["payload"]["text"]
        finally:
            # ALWAYS persist. Shielded so a stop arriving during the save can't
            # cancel the write itself (the bug that lost whole answers before).
            async def _persist() -> None:
                meta: Dict[str, Any] = {"events": list(turn.events)}
                if cancelled:
                    meta["cancelled"] = True
                g = turn_ctx.get("group")
                if g is not None:
                    from ..services.runs import finish_group
                    finish_group(g, list(turn_ctx.get("statuses") or []) + (["cancelled"] if cancelled else []))
                    meta["run_group_id"] = g.id
                    meta["run_group_code"] = f"R-{g.seq_no:04d}"
                session.add(Message(conversation_id=conv_id, role="assistant",
                                    content=final_text or "(no output)", meta=meta))
                # Explicit UPDATE: the conv instance's JSON dirty-state isn't reliably
                # flushed across run_turn's mid-turn commits.
                await session.execute(update(Conversation).where(Conversation.id == conv_id)
                                      .values(pipeline_state=dict(pipeline_state)))
                await session.commit()
            try:
                await asyncio.shield(_persist())
            except Exception:
                logger.exception("failed to persist assistant message for conv=%s", conv_id)
            await turn.finish()


@router.get("/conversations/{conv_id}/live")
async def live_turn(conv_id: int, user: User = Depends(current_user)):
    """Re-attach to the conversation's turn if it is still generating (or just
    finished): replays its events so far, then follows. 204 when there is none."""
    from fastapi import Response
    t = chat_turns.latest(conv_id, user.id)
    if t is None:
        return Response(status_code=204)
    return StreamingResponse(t.follow(0), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/conversations/{conv_id}/stop")
async def stop_turn(conv_id: int, user: User = Depends(current_user)):
    """The stop button: end the running turn. Its partial answer is saved."""
    t = chat_turns.running(conv_id, user.id)
    if t is None or t.task is None:
        return {"ok": True, "stopped": False}
    t.task.cancel()
    return {"ok": True, "stopped": True}


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
