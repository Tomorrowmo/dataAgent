"""Mapping rules API — the promote + consult ends of the expert-knowledge loop.

  - POST /mappings           promote a correction into a reusable rule (the
                             inbox's「晋升为映射规则」calls this; pass feedback_id
                             and that note is auto-marked done)
  - GET  /mappings           rules visible to the user (own + public)
  - DELETE /mappings/{id}    remove one of your own rules
  - POST /mappings/apply     consult: given column names, what do the rules say
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Feedback, MappingRule, User
from ..services.mappings import apply_rules
from .deps import current_user, get_db

router = APIRouter(prefix="/mappings", tags=["mappings"])

_MATCH_TYPES = {"normalized", "exact", "contains", "regex"}


class CreateMappingReq(BaseModel):
    pattern: str
    role: str
    label: str = ""
    note: str = ""
    match_type: str = "normalized"
    is_public: bool = True
    feedback_id: Optional[int] = None  # provenance; if set, that note → done


class MappingResp(BaseModel):
    id: int
    pattern: str
    match_type: str
    role: str
    label: str
    note: str
    source: str
    feedback_id: Optional[int]
    is_public: bool
    hit_count: int
    created_at: str


def _to_resp(r: MappingRule) -> MappingResp:
    return MappingResp(
        id=r.id, pattern=r.pattern, match_type=r.match_type, role=r.role, label=r.label,
        note=r.note, source=r.source, feedback_id=r.feedback_id, is_public=r.is_public,
        hit_count=r.hit_count, created_at=r.created_at.isoformat() if r.created_at else "",
    )


async def _visible_rules(session: AsyncSession, user: User) -> List[MappingRule]:
    """Rules the user should consult: their own + everyone's public ones. Own
    first, so a personal rule shadows a public one on the same column."""
    rows = (await session.execute(
        select(MappingRule)
        .where(or_(MappingRule.owner_id == user.id, MappingRule.is_public.is_(True)))
        .order_by((MappingRule.owner_id == user.id).desc(), MappingRule.id.desc())
    )).scalars().all()
    return list(rows)


@router.post("", response_model=MappingResp)
async def create_mapping(
    body: CreateMappingReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    pattern = (body.pattern or "").strip()
    role = (body.role or "").strip()
    if not pattern or not role:
        raise HTTPException(400, "pattern 和 role 不能为空")
    match_type = body.match_type if body.match_type in _MATCH_TYPES else "normalized"
    rule = MappingRule(
        owner_id=user.id, pattern=pattern, match_type=match_type, role=role,
        label=body.label.strip() or role, note=body.note,
        source="feedback" if body.feedback_id else "manual",
        feedback_id=body.feedback_id, is_public=body.is_public,
    )
    session.add(rule)

    # Promoting a note closes it out: mark the source feedback done.
    if body.feedback_id is not None:
        fb = (await session.execute(
            select(Feedback).where(Feedback.id == body.feedback_id)
        )).scalar_one_or_none()
        if fb is not None and (user.is_admin or fb.owner_id == user.id):
            fb.status = "done"

    await session.commit()
    await session.refresh(rule)
    return _to_resp(rule)


@router.get("", response_model=List[MappingResp])
async def list_mappings(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return [_to_resp(r) for r in await _visible_rules(session, user)]


@router.delete("/{rule_id}")
async def delete_mapping(
    rule_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    rule = (await session.execute(
        select(MappingRule).where(MappingRule.id == rule_id, MappingRule.owner_id == user.id)
    )).scalar_one_or_none()
    if rule is None:
        raise HTTPException(404, "rule not found")
    await session.delete(rule)
    await session.commit()
    return {"ok": True}


class ApplyReq(BaseModel):
    columns: List[str] = Field(default_factory=list)


@router.post("/apply")
async def apply_mappings(
    body: ApplyReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Consult endpoint: given column names, return what the visible rules say.
    Bumps hit_count on the rules that fired so we can see which knowledge earns
    its keep."""
    rules = await _visible_rules(session, user)
    matches = apply_rules(body.columns, rules)
    if matches:
        by_id = {r.id: r for r in rules}
        for m in matches:
            r = by_id.get(m["rule_id"])
            if r is not None:
                r.hit_count += 1
        await session.commit()
    return {"matches": matches}
