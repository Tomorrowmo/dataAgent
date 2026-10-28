"""Skill-pack REST API: install / inspect / enable / run / remove.

The install endpoints intentionally return the FULL install report (every stage
with its verdict), because a half-installed pack that silently does nothing is
the worst outcome for the user — worse than a refusal with a reason.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import Dataset, MappingRule, SkillPack, User
from ..services.datasets import _persist_dataset, load_dataset_df
from ..services.mappings import apply_rules, normalize as _norm_role
from ..skills import store as skill_store
from ..skills.installer import InstallError, install_pack, remove_pack
from ..skills.runtime import run_tool as run_skill_tool
from ..skills.suggest import suggest_params
from .deps import current_user, get_db

router = APIRouter(prefix="/skills", tags=["skills"])

# The authoring spec ships with the app so the UI can show it without a network trip.
_SPEC_PATH = Path(__file__).resolve().parents[3] / "docs" / "skills" / "技能包接入规范.md"
_EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples" / "skills"


class SkillSummary(BaseModel):
    id: int
    slug: str
    name: str
    version: str
    description: str
    when_to_use: str = ""
    triggers: List[str] = []
    category: str = "skill"
    enabled: bool = True
    is_public: bool = False
    is_verified: bool = False
    trust: str = "sandbox"
    doc_chars: int = 0
    tool_count: int = 0
    tools: List[Dict[str, Any]] = []
    files: List[str] = []
    root: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class InstallResp(BaseModel):
    ok: bool
    skill: Optional[SkillSummary] = None
    report: Dict[str, Any]


class EnableReq(BaseModel):
    enabled: bool
    is_public: Optional[bool] = None


class SuggestReq(BaseModel):
    dataset_id: Optional[int] = None


class RunReq(BaseModel):
    dataset_id: Optional[int] = None
    params: Dict[str, Any] = {}
    save_as: Optional[str] = None  # name → persist the result as a new dataset


async def _get_owned(session: AsyncSession, user: User, slug: str) -> SkillPack:
    pack = await skill_store.get_pack(session, user.id, slug)
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"技能包不存在:{slug}")
    return pack


@router.get("", response_model=List[SkillSummary])
async def list_skills(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> List[SkillSummary]:
    packs = await skill_store.list_packs(session, user.id)
    return [SkillSummary(**skill_store.summarize(p)) for p in packs]


@router.post("/install", response_model=InstallResp)
async def install(
    file: Optional[UploadFile] = File(default=None),
    path: Optional[str] = Form(default=None),
    # 三态:不传 = 由安装器决定(新装启用、升级保持原状),别把用户的停用选择冲掉
    enable: Optional[bool] = Form(default=None),
    allow_command: bool = Form(default=False),
    dry_run: bool = Form(default=False),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> InstallResp:
    """Install from an uploaded .zip, or from a folder path on the server.

    The folder form is what a local/desktop user actually wants: point at the
    directory they're editing and re-install after each change, no zipping."""
    if file is None and not (path or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "请上传技能包 zip,或填写服务器上的技能包目录路径。")
    if allow_command and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "只有管理员可以安装自带可执行程序(runtime: command)的技能包。")

    zip_bytes = await file.read() if file is not None else None
    try:
        row, report = await install_pack(
            session, user.id,
            zip_bytes=zip_bytes,
            src_dir=(path or "").strip() or None,
            enable=enable,
            allow_command=allow_command,
            dry_run=dry_run,
        )
    except InstallError as e:
        # A refusal IS a result — hand back the reason, not a bare 500.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    return InstallResp(
        ok=True,
        skill=SkillSummary(**skill_store.summarize(row)) if row is not None else None,
        report=report,
    )


@router.post("/install-example", response_model=InstallResp)
async def install_example(
    example: str = Form(default="battery-health"),
    dry_run: bool = Form(default=False),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> InstallResp:
    """Install one of the bundled example packs — the fastest way to see the whole
    thing work end to end without writing anything first."""
    src = _EXAMPLES_DIR / example
    if not src.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"没有这个示例包:{example}")
    try:
        row, report = await install_pack(session, user.id, src_dir=str(src),
                                         enable=True, allow_command=False, dry_run=dry_run)
    except InstallError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return InstallResp(
        ok=True,
        skill=SkillSummary(**skill_store.summarize(row)) if row is not None else None,
        report=report,
    )


@router.get("/spec")
async def authoring_spec(user: User = Depends(current_user)) -> Dict[str, Any]:
    """The 技能包接入规范 markdown, so the UI can show it inline."""
    if not _SPEC_PATH.is_file():
        return {"ok": False, "content": "", "error": "规范文档未随本次部署一起发布。"}
    return {"ok": True, "content": _SPEC_PATH.read_text(encoding="utf-8", errors="replace")}


@router.get("/template")
async def download_template(
    example: str = "battery-health",
    user: User = Depends(current_user),
) -> Response:
    """A ready-to-edit example pack as a zip — the fastest path from "我想写一个"
    to a working pack."""
    src = _EXAMPLES_DIR / example
    if not src.is_dir():
        available = [p.name for p in _EXAMPLES_DIR.iterdir() if p.is_dir()] if _EXAMPLES_DIR.is_dir() else []
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"没有这个示例包:{example}(可用:{'、'.join(available) or '无'})")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                zf.write(p, str(Path(example) / p.relative_to(src)))
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{example}.zip"'},
    )


@router.get("/{slug}")
async def get_skill(
    slug: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Dict[str, Any]:
    pack = await _get_owned(session, user, slug)
    data = skill_store.summarize(pack)
    data["install_report"] = pack.install_report or {}
    data["manifest"] = pack.manifest or {}
    data["doc"] = skill_store.read_doc(pack)
    return data


@router.get("/{slug}/doc")
async def get_doc(
    slug: str,
    file: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Dict[str, Any]:
    pack = await _get_owned(session, user, slug)
    return skill_store.read_doc(pack, file)


@router.post("/{slug}/enable")
async def set_enabled(
    slug: str,
    body: EnableReq,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Dict[str, Any]:
    pack = await _get_owned(session, user, slug)
    if pack.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "这是别人共享的技能包,不能改。")
    pack.enabled = bool(body.enabled)
    if body.is_public is not None:
        if not user.is_admin and body.is_public:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "只有管理员可以把技能包共享给所有人。")
        pack.is_public = bool(body.is_public)
    await session.commit()
    await session.refresh(pack)
    return skill_store.summarize(pack)


@router.delete("/{slug}")
async def delete_skill(
    slug: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Dict[str, Any]:
    pack = await _get_owned(session, user, slug)
    if pack.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "这是别人共享的技能包,不能删。")
    await remove_pack(session, pack)
    return {"ok": True, "slug": slug}


@router.post("/{slug}/tools/{tool_name}/suggest")
async def suggest_tool_params(
    slug: str,
    tool_name: str,
    body: SuggestReq,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Dict[str, Any]:
    """按所选数据集的真实列名,给这个工具推荐一套参数。

    确定性匹配,不调 LLM —— 打开面板就能立刻填好,没配 key 也能用。挑不出对应列时
    如实说"这份数据不适合这个工具",而不是填个能跑但没意义的值。"""
    pack = await _get_owned(session, user, slug)
    hit = skill_store.resolve_tool([pack], f"{pack.slug}.{tool_name}")
    if hit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"技能包「{pack.name}」里没有这个工具:{tool_name}")
    _pack, tool = hit

    columns: List[Dict[str, Any]] = []
    ds_name = ""
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "数据集不存在")
        columns = list((ds.schema_json or {}).get("columns") or [])
        ds_name = ds.name

    # 先问"用户/团队教过什么":这些是沉淀下来的专家判断,排在字面猜测之前。
    role_columns: Dict[str, List[str]] = {}
    role_labels: Dict[str, str] = {}
    rules = list((await session.execute(
        select(MappingRule).where(
            (MappingRule.owner_id == user.id) | (MappingRule.is_public == True)  # noqa: E712
        )
    )).scalars().all())
    if rules and columns:
        for m in apply_rules([str(c.get("name")) for c in columns], rules):
            role_columns.setdefault(str(m["role"]), []).append(m["column"])
            role_labels.setdefault(str(m["role"]), str(m.get("label") or m["role"]))

    out = suggest_params(tool, columns, dataset_name=ds_name,
                         role_columns=role_columns, role_labels=role_labels)

    # 规则被真正用上了 → 记一次命中。存了却从没被读回的知识等于没沉淀。
    if out.get("used_rules"):
        used = {str(r) for r in out["used_rules"]}
        for rule in rules:
            if _norm_role(rule.role) in used:
                rule.hit_count = (rule.hit_count or 0) + 1
        await session.commit()
    return out


@router.post("/{slug}/tools/{tool_name}/run")
async def run_skill(
    slug: str,
    tool_name: str,
    body: RunReq,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Dict[str, Any]:
    """Run one tool of an installed pack directly (the 工具面板 path — same code
    the chat agent calls, so behaviour can't drift between the two)."""
    import asyncio

    pack = await _get_owned(session, user, slug)
    hit = skill_store.resolve_tool([pack], f"{pack.slug}.{tool_name}")
    if hit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"技能包「{pack.name}」里没有这个工具:{tool_name}")
    _pack, tool = hit

    df = None
    ds: Optional[Dataset] = None
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "数据集不存在")
        df = load_dataset_df(ds)

    result = await asyncio.to_thread(
        run_skill_tool, root=pack.root, tool=tool, df=df,
        params=body.params or {}, allow_command=None,
    )
    if not pack.enabled:
        # 手动试跑一个停用的包是合理的(排查、验证),但不能让人以为它已经在为 AI 服务。
        result["warning"] = (
            f"技能包「{pack.name}」当前是**停用**状态:AI 在对话里看不到它,也不会主动用它。"
            "这次是你在页面上手动触发的。想让 AI 用它,回到包详情勾上「启用」。"
        )

    # Optionally materialize the output so the user can chart / chain it.
    if result.get("status") == "ok" and body.save_as and result.get("result_path"):
        import pandas as pd
        out_df = pd.read_parquet(result["result_path"])
        new_ds = await _persist_dataset(
            session, owner_id=user.id, df=out_df, name=body.save_as,
            filename=f"{pack.slug}.{tool_name}.parquet", file_format="parquet",
            description=f"由技能包「{pack.name}」的 {tool_name} 生成",
            kind="derived", derived_from=ds.id if ds else None,
            lineage={"skill": pack.slug, "tool": tool_name, "params": body.params or {}},
        )
        await session.commit()
        await session.refresh(new_ds)
        result["derived_dataset"] = {"id": new_ds.id, "name": new_ds.name,
                                     "rows": new_ds.rows, "columns": new_ds.columns}
    return result
