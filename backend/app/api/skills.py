"""Skills: import a user's skill package, review its card, enable it for chat."""

from __future__ import annotations

import shutil
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Skill, User
from ..services import skills as svc
from .deps import current_user, get_db, llm_for

router = APIRouter(prefix="/skills", tags=["skills"])


async def _own(session: AsyncSession, skill_id: int, user: User) -> Skill:
    row = await session.get(Skill, skill_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(404, "skill not found")
    return row


@router.get("")
async def list_skills(user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    await svc.ensure_defaults(session, user.id)
    rows = (await session.execute(
        select(Skill).where(Skill.owner_id == user.id).order_by(Skill.id.desc())
    )).scalars().all()
    return [svc.skill_view(s) for s in rows]


@router.post("/import")
async def import_skill(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Upload a skill (.zip of the skill folder, or a SKILL.md). Returns a DRAFT
    with an AI-drafted description / configuration card for the user to review."""
    data = await file.read()
    filename = file.filename or "skill.zip"
    tmp_slug = svc.slugify(filename.rsplit(".", 1)[0])
    dest = svc.skill_dir(user.id, tmp_slug)
    try:
        files = svc.extract_package(data, filename, dest)
        parsed = svc.parse_package(dest, files)
    except svc.SkillImportError as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(400, str(e))

    card, card_source = await svc.draft_card(llm_for(user), parsed)
    slug = svc.slugify(parsed["name"])
    taken = {s for (s,) in (await session.execute(
        select(Skill.slug).where(Skill.owner_id == user.id)
    )).all()}
    base, n = slug, 2
    while slug in taken:
        slug, n = f"{base}_{n}", n + 1
    row = Skill(
        owner_id=user.id, slug=slug, name=parsed["name"], description=parsed["description"],
        instructions=parsed["instructions"], config=card, references=parsed["references"],
        scripts=parsed["scripts"], files_dir=str(dest), source_filename=filename, status="draft",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {**svc.skill_view(row), "card_source": card_source}


@router.get("/{skill_id}")
async def get_skill(skill_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    return svc.skill_view(await _own(session, skill_id, user))


class UpdateSkillReq(BaseModel):
    config: Optional[Dict[str, Any]] = None
    # "active" = confirm / enable (registers its scripts as tools), "disabled" = hide.
    status: Optional[str] = None


@router.put("/{skill_id}")
async def update_skill(
    skill_id: int, body: UpdateSkillReq,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    row = await _own(session, skill_id, user)
    if body.config is not None:
        row.config = svc.normalize_card(body.config)
        if row.config.get("name"):
            row.name = row.config["name"]
    if body.status is not None:
        if body.status not in ("active", "disabled"):
            raise HTTPException(400, "status must be active or disabled")
        if body.status == "active":
            row.scripts = await svc.register_tools(session, row)
        row.status = body.status
    await session.commit()
    await session.refresh(row)
    return svc.skill_view(row)


@router.post("/{skill_id}/regenerate")
async def regenerate_card(skill_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    """Re-draft the card from the stored SKILL.md (discarding manual edits)."""
    row = await _own(session, skill_id, user)
    parsed = {"name": row.name, "description": row.description, "instructions": row.instructions,
              "references": row.references or [], "scripts": row.scripts or []}
    row.config, source = await svc.draft_card(llm_for(user), parsed)
    await session.commit()
    await session.refresh(row)
    return {**svc.skill_view(row), "card_source": source}


@router.delete("/{skill_id}")
async def delete_skill(skill_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    row = await _own(session, skill_id, user)
    if row.is_default:
        # Defaults are re-seeded for every user, so deleting would just bring it
        # back — disable it instead.
        row.status = "disabled"
        await session.commit()
        return {"ok": True, "disabled": True}
    await svc.remove_skill(session, row)
    await session.commit()
    return {"ok": True}


async def load_for_chat(session: AsyncSession, owner_id: int, ids: Optional[List[int]]) -> tuple[list, list]:
    """(selected, catalog): the user's ACTIVE skills split into the ones picked
    for this message and the rest (offered only as recommendations)."""
    await svc.ensure_defaults(session, owner_id)
    rows = (await session.execute(
        select(Skill).where(Skill.owner_id == owner_id, Skill.status == "active").order_by(Skill.id)
    )).scalars().all()
    want = set(ids or [])
    return [s for s in rows if s.id in want], [s for s in rows if s.id not in want]


@router.post("/import-stream")
async def import_skill_stream(file: UploadFile = File(...), user: User = Depends(current_user)):
    """Same as /import, but streams each step (SSE) so the user watches the
    package being read instead of a frozen spinner:
    received → extracted → skill_md → scripts → references → ai_reading → card → saved."""
    import json as _json

    from fastapi.responses import StreamingResponse

    from ..db.base import SessionLocal
    from .chat import SSE_HEADERS

    data = await file.read()
    filename = file.filename or "skill.zip"
    llm = llm_for(user)

    def ev(stage: str, **kw: Any) -> str:
        return f"data: {_json.dumps({'stage': stage, **kw}, ensure_ascii=False, default=str)}\n\n"

    async def stream():
        yield ": import-open\n\n"
        yield ev("received", filename=filename, size=len(data))
        dest = svc.skill_dir(user.id, svc.slugify(filename.rsplit(".", 1)[0]))
        try:
            files = svc.extract_package(data, filename, dest)
            yield ev("extracted", count=len(files), files=[f.relative_to(dest).as_posix() for f in files][:60])
            parsed = svc.parse_package(dest, files)
        except svc.SkillImportError as e:
            shutil.rmtree(dest, ignore_errors=True)
            yield ev("error", message=str(e))
            return
        yield ev("skill_md", name=parsed["name"], description=parsed["description"], chars=len(parsed["instructions"]))
        yield ev("scripts", items=[{"path": x["path"], "kind": x["kind"], "note": x["note"]} for x in parsed["scripts"]])
        yield ev("references", items=parsed["references"])
        yield ev("ai_reading", configured=llm.is_configured,
                 msg=f"AI 正在阅读 SKILL.md（{len(parsed['instructions'])} 字）"
                     f"{'和 ' + str(len(parsed['scripts']) + len(parsed['references'])) + ' 个附带文件' if parsed['scripts'] or parsed['references'] else ''}"
                     "，生成说明卡并检查平台适配度…")
        card, source = await svc.draft_card(llm, parsed)
        yield ev("card", source=source, fit=card.get("platform_fit"))
        async with SessionLocal() as session:
            slug = svc.slugify(parsed["name"])
            taken = {s for (s,) in (await session.execute(
                select(Skill.slug).where(Skill.owner_id == user.id)
            )).all()}
            base, n = slug, 2
            while slug in taken:
                slug, n = f"{base}_{n}", n + 1
            row = Skill(
                owner_id=user.id, slug=slug, name=card.get("name") or parsed["name"], description=parsed["description"],
                instructions=parsed["instructions"], config=card, references=parsed["references"],
                scripts=parsed["scripts"], files_dir=str(dest), source_filename=filename, status="draft",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            yield ev("saved", skill={**svc.skill_view(row), "card_source": source})

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


class AdjustReq(BaseModel):
    instruction: str


@router.post("/{skill_id}/adjust")
async def adjust_skill(
    skill_id: int, body: AdjustReq,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    """Apply a plain-language edit to the card with AI and SAVE it right away
    (the client keeps the previous card for undo)."""
    row = await _own(session, skill_id, user)
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")
    if not body.instruction.strip():
        raise HTTPException(400, "说说想怎么改")
    try:
        card, reply = await svc.adjust_card(llm, row, body.instruction)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"AI 调整失败：{type(e).__name__}: {e}")
    row.config = card
    if card.get("name"):
        row.name = card["name"]
    await session.commit()
    await session.refresh(row)
    return {"reply": reply, "skill": svc.skill_view(row)}
