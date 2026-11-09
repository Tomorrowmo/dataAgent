"""Flow templates — reusable multi-step pipelines.

A template is an ordered tool chain (captured from a conversation, or built on
the canvas). Saving / editing / running all go through services.flow_runner,
which enforces what a flow may contain (改进清单-3 · L2b), pins algorithm
versions (L2d), replays explicit inputs (E2) and stops at the first failure (L2c).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Conversation, Dataset, FlowTemplate, Message, User
from ..services.datasets import gc_derived_datasets  # noqa: F401  (kept for callers / tests)
from ..services.flow_runner import FlowError, newer_versions, pin_versions, run_flow, validate_steps
from .deps import current_user, get_db

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateStep(BaseModel):
    action: str = "run_tool"
    slug: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    label: Optional[str] = None
    algorithm_id: Optional[int] = None
    version: Optional[int] = None
    input: Optional[Any] = None          # "start" | step index | None (legacy linear)
    output_role: Optional[str] = None    # "data" | "report"


class CreateTemplateReq(BaseModel):
    name: str
    description: str = ""
    steps: List[TemplateStep]
    graph: Dict[str, Any] = Field(default_factory=dict)


class TemplateResp(BaseModel):
    id: int
    name: str
    description: str
    steps: List[Dict[str, Any]]
    n_steps: int
    graph: Dict[str, Any] = Field(default_factory=dict)
    newer_versions: List[Dict[str, Any]] = Field(default_factory=list)


async def _to_resp(session: AsyncSession, tpl: FlowTemplate) -> TemplateResp:
    steps = tpl.steps or []
    tool_steps = [s for s in steps if s.get("action", "run_tool") == "run_tool" and s.get("slug")]
    return TemplateResp(id=tpl.id, name=tpl.name, description=tpl.description, steps=steps,
                        n_steps=len(tool_steps), graph=getattr(tpl, "graph", {}) or {},
                        newer_versions=await newer_versions(session, tpl.owner_id, steps))


def _dump(steps: List[TemplateStep]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in s.model_dump().items() if v is not None or k in ("slug",)} for s in steps]


@router.post("", response_model=TemplateResp)
async def create_template(
    body: CreateTemplateReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    steps = await pin_versions(session, user.id, _dump(body.steps))
    try:
        await validate_steps(session, user.id, steps)
    except FlowError as e:
        raise HTTPException(422, str(e))
    tpl = FlowTemplate(owner_id=user.id, name=body.name.strip() or "未命名流程",
                       description=body.description, steps=steps, graph=body.graph or {})
    session.add(tpl)
    await session.commit()
    await session.refresh(tpl)
    return await _to_resp(session, tpl)


class UpdateTemplateReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[List[TemplateStep]] = None
    graph: Optional[Dict[str, Any]] = None
    # Re-pin every custom-algorithm step to its CURRENT version ("更新流程").
    upgrade_versions: bool = False


async def _owned_tpl(session: AsyncSession, template_id: int, user: User) -> FlowTemplate:
    tpl = (await session.execute(
        select(FlowTemplate).where(FlowTemplate.id == template_id, FlowTemplate.owner_id == user.id)
    )).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(404, "template not found")
    return tpl


@router.put("/{template_id}", response_model=TemplateResp)
async def update_template(
    template_id: int,
    body: UpdateTemplateReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Edit a template — rename, re-order/add/remove steps, change params, or
    upgrade pinned algorithm versions. The flow canvas saves through here."""
    tpl = await _owned_tpl(session, template_id, user)
    if body.name is not None:
        tpl.name = body.name.strip() or tpl.name
    if body.description is not None:
        tpl.description = body.description
    if body.steps is not None or body.upgrade_versions:
        raw = _dump(body.steps) if body.steps is not None else [dict(s) for s in (tpl.steps or [])]
        if body.upgrade_versions:
            for s in raw:
                s.pop("version", None)
                s.pop("algorithm_id", None)
            steps = await pin_versions(session, user.id, raw)
        else:
            steps = await pin_versions(session, user.id, raw, old_steps=tpl.steps or [])
        try:
            await validate_steps(session, user.id, steps)
        except FlowError as e:
            raise HTTPException(422, str(e))
        tpl.steps = steps
    if body.graph is not None:
        tpl.graph = body.graph
    await session.commit()
    await session.refresh(tpl)
    return await _to_resp(session, tpl)


@router.get("", response_model=List[TemplateResp])
async def list_templates(user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(
        select(FlowTemplate).where(FlowTemplate.owner_id == user.id).order_by(FlowTemplate.id.desc())
    )).scalars().all()
    return [await _to_resp(session, t) for t in rows]


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    tpl = await _owned_tpl(session, template_id, user)
    await session.delete(tpl)
    await session.commit()
    return {"ok": True}


class RunTemplateReq(BaseModel):
    dataset_id: int
    save_result: bool = True
    # Runtime parameter overrides, keyed by step index (as a string, JSON-safe):
    # {"1": {"window": 9}}. Merged over that step's saved params before running.
    param_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


async def _owned_ds(session: AsyncSession, dataset_id: int, user: User) -> Dataset:
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    return ds


@router.post("/{template_id}/run")
async def run_template(
    template_id: int,
    body: RunTemplateReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Replay the flow on a dataset (stops at the first failing step)."""
    tpl = await _owned_tpl(session, template_id, user)
    ds = await _owned_ds(session, body.dataset_id, user)
    try:
        out = await run_flow(session, user.id, tpl.name, list(tpl.steps or []), ds,
                             overrides=body.param_overrides, save_result=body.save_result)
    except FlowError as e:
        raise HTTPException(422, str(e))
    out.pop("events", None)
    return out


class RunInChatReq(BaseModel):
    dataset_id: int
    conversation_id: Optional[int] = None   # None → start a new conversation


@router.post("/{template_id}/run-in-chat")
async def run_template_in_chat(
    template_id: int,
    body: RunInChatReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """改进清单-3 · L3/L4: run the flow WITHOUT the AI and write the outcome into
    a conversation as a 'flow run' message — it survives a reload and the AI
    sees it in the history of later turns."""
    tpl = await _owned_tpl(session, template_id, user)
    ds = await _owned_ds(session, body.dataset_id, user)
    if body.conversation_id is not None:
        conv = (await session.execute(select(Conversation).where(
            Conversation.id == body.conversation_id, Conversation.owner_id == user.id))).scalar_one_or_none()
        if conv is None:
            raise HTTPException(404, "conversation not found")
    else:
        conv = Conversation(owner_id=user.id, title=f"流程：{tpl.name}", dataset_id=ds.id)
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
    try:
        out = await run_flow(session, user.id, tpl.name, list(tpl.steps or []), ds)
    except FlowError as e:
        raise HTTPException(422, str(e))
    n_ok = sum(1 for s in out["steps"] if s.get("status") == "ok")
    n_tool = len([s for s in out["steps"] if s.get("status") != "skipped"])
    if out["status"] == "ok":
        text = f"已在「{ds.name}」上运行流程「{tpl.name}」（{n_ok} 步，不经过 AI），结果如下。"
    else:
        failed = next((s for s in out["steps"] if s.get("status") not in ("ok", "skipped")), {})
        text = (f"在「{ds.name}」上运行流程「{tpl.name}」时，第 {int(failed.get('i', 0)) + 1} 步"
                f"「{failed.get('label', '')}」失败，后续步骤没有执行（成功 {n_ok}/{n_tool} 步）。")
    events = out["events"] + [{"kind": "final", "payload": {"text": text}}]
    user_msg = Message(conversation_id=conv.id, role="user", content=f"运行流程「{tpl.name}」，数据：{ds.name}",
                       meta={"flow_run": tpl.id, "dataset_id": ds.id})
    msg = Message(conversation_id=conv.id, role="assistant", content=text,
                  meta={"events": events, "flow_run": tpl.id, "dataset_id": ds.id, "status": out["status"]})
    session.add(user_msg)
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return {"conversation_id": conv.id, "message_id": msg.id, "status": out["status"]}
