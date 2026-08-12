"""Wind-tunnel quality-check API.

Mounted at ``/api/wt``. The five groups map one-to-one onto the五个功能分区 in
the customer's specification, plus the two extension surfaces that make the
whole thing worth building on this platform rather than as another script:

    ① 数据导入      POST /wt/batches            上传 ca/pa/da,自动按车次分组
                    POST /wt/batches/{id}/check 勾选检查项 → 执行 → 结果
    ② 运算结果      GET  /wt/batches/{id}
    ③ 气动曲线      POST /wt/batches/{id}/curve  + /curve/conclusion (AI 叙述)
    ④ 报告          POST /wt/batches/{id}/report → 预览可编辑 → /export
    ⑤ 知识库        /wt/rules  /wt/features  /wt/balances

    扩展面 A（规则）  POST /wt/rules/draft    自然语言 → 规则草稿(可预览再落库)
                      POST /wt/rules/preview  草稿在真实车次上试跑,不入库
    扩展面 B（算法）  POST /wt/extractors/generate  自然语言 → 沙箱验证过的特征算子
                      POST /wt/extractors         审核通过后入算法库,即刻可被规则引用

Design note: `preview-before-save` appears on both extension surfaces on
purpose. A rule or an algorithm that a model just wrote is a *proposal*; it
becomes part of the quality system only after a human has seen what it does to
real runs. That is the same gate the platform already applies to AI-generated
algorithms, extended to rules.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import Algorithm, User, WtBalance, WtBatch, WtReport, WtRule
from ..windtunnel import ai as wt_ai
from ..windtunnel.balance import BalanceLibrary, default_library
from ..windtunnel.features import FEATURE_SPECS
from ..windtunnel.frames import bundle_to_frame, frame_schema_hint, wide_table
from ..windtunnel.knowledge import EXTRACTOR_CONTRACT, FILE_FORMAT_DOC, feature_catalog
from ..windtunnel.parsers import BALANCE_UNITS, detect_kind, detect_run_no, group_by_run, load_bundle
from ..windtunnel.pipeline import (
    CheckConfig,
    check_batch,
    curve_data,
    curve_statistics,
    load_batch,
)
from ..windtunnel.report import (
    SECTIONS,
    ReportOptions,
    build_batch_summary,
    build_report,
    build_shift_record,
    report_filename,
)
from ..windtunnel.rules import Rule
from ..windtunnel.seed_rules import seed_rules
from .deps import current_user, get_db, llm_for

router = APIRouter(prefix="/wt", tags=["windtunnel"])


# ══════════════════════════════════════════════════════════════════════════
#  storage helpers
# ══════════════════════════════════════════════════════════════════════════
def _batch_dir(owner_id: int, batch_id: int) -> Path:
    p = get_settings().upload_path / "windtunnel" / str(owner_id) / str(batch_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _get_batch(session: AsyncSession, user: User, batch_id: int) -> WtBatch:
    b = (await session.execute(
        select(WtBatch).where(WtBatch.id == batch_id, WtBatch.owner_id == user.id)
    )).scalar_one_or_none()
    if b is None:
        raise HTTPException(404, "批次不存在")
    return b


# ══════════════════════════════════════════════════════════════════════════
#  rules: seed-on-first-use, then pure data
# ══════════════════════════════════════════════════════════════════════════
async def _ensure_seeded(session: AsyncSession, user: User) -> None:
    """Materialise the shipped rules for this user on first access.

    They live in the database, not in code, so a test engineer can edit a
    threshold in the UI. ``builtin_id`` keeps the link to the original for
    audit and for a future "restore default".
    """
    n = (await session.execute(
        select(WtRule.id).where(WtRule.owner_id == user.id).limit(1)
    )).scalar_one_or_none()
    if n is not None:
        return
    for r in seed_rules():
        session.add(WtRule(
            owner_id=user.id, rule_id=r.rule_id, name=r.name, feature=r.feature,
            object_name=r.object_, note=r.note, applies_when_mach=r.applies_when_mach,
            bands=[b.to_dict() for b in r.bands], refs=list(r.refs),
            enabled=True, source="builtin", builtin_id=r.rule_id,
            changelog=[{"at": datetime.now(timezone.utc).isoformat(),
                        "what": "内置规则初始化"}],
        ))
    # Seed the shipped balance library too.
    lib = default_library()
    for e in lib.entries.values():
        session.add(WtBalance(owner_id=user.id, name=e.name, ranges=e.ranges, note=e.note))
    await session.commit()


def _row_to_rule(r: WtRule) -> Rule:
    return Rule.from_dict({
        "rule_id": r.rule_id, "name": r.name, "feature": r.feature,
        "object": r.object_name, "note": r.note,
        "applies_when_mach": r.applies_when_mach or "",
        "bands": r.bands or [], "refs": r.refs or [],
        "enabled": bool(r.enabled), "source": r.source,
    })


def _rule_row_dict(r: WtRule) -> Dict[str, Any]:
    d = _row_to_rule(r).to_dict()
    d["id"] = r.id
    d["builtin_id"] = r.builtin_id
    d["changelog"] = r.changelog or []
    d["updated_at"] = r.updated_at.isoformat() if r.updated_at else ""
    return d


async def _user_rules(session: AsyncSession, user: User) -> List[WtRule]:
    await _ensure_seeded(session, user)
    return list((await session.execute(
        select(WtRule).where(WtRule.owner_id == user.id).order_by(WtRule.rule_id)
    )).scalars())


async def _user_library(session: AsyncSession, user: User) -> BalanceLibrary:
    rows = list((await session.execute(
        select(WtBalance).where(WtBalance.owner_id == user.id)
    )).scalars())
    lib = BalanceLibrary()
    for r in rows:
        try:
            lib.add(r.name, r.ranges or {}, r.note or "")
        except ValueError:
            continue
    return lib or default_library()


async def _custom_extractors(session: AsyncSession, user: User) -> Dict[str, Dict[str, str]]:
    """Every verified custom extractor in this user's algorithm library,
    keyed the way a rule references it (``custom:<slug>``)."""
    rows = list((await session.execute(
        select(Algorithm).where(
            Algorithm.owner_id == user.id, Algorithm.category == "custom",
        )
    )).scalars())
    return {f"custom:{a.slug}": {"code": a.code, "name": a.name}
            for a in rows if a.code}


# ══════════════════════════════════════════════════════════════════════════
#  ① 数据导入
# ══════════════════════════════════════════════════════════════════════════
class BatchResp(BaseModel):
    id: int
    name: str
    status: str
    runs: List[Dict[str, Any]]
    config: Dict[str, Any]
    created_at: str
    checked_at: str = ""
    error: str = ""


def _batch_resp(b: WtBatch) -> BatchResp:
    return BatchResp(
        id=b.id, name=b.name, status=b.status, runs=b.runs or [],
        config=b.config or {}, error=b.error or "",
        created_at=b.created_at.isoformat() if b.created_at else "",
        checked_at=b.checked_at.isoformat() if b.checked_at else "",
    )


@router.post("/batches", response_model=BatchResp)
async def create_batch(
    files: List[UploadFile] = File(...),
    name: str = Form(""),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Upload a drop of ca/pa/da files; they are grouped into 车次 automatically.

    Files carry no extension, so the ``ca``/``pa``/``da`` prefix plus the run
    number IS the type system. Anything that does not match is reported back
    rather than silently ignored — a mistyped filename that vanishes without a
    word is how a run ends up checked with two of its three files.
    """
    await _ensure_seeded(session, user)
    b = WtBatch(owner_id=user.id, name=name or "", status="new")
    session.add(b)
    await session.commit()
    await session.refresh(b)

    d = _batch_dir(user.id, b.id)
    saved: List[Path] = []
    rejected: List[str] = []
    for f in files:
        fname = Path(f.filename or "").name
        if not fname:
            continue
        # A zip drop is common when engineers pack a whole entry's runs.
        data = await f.read()
        if fname.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for member in z.namelist():
                        inner = Path(member).name
                        if not inner or member.endswith("/"):
                            continue
                        if detect_kind(inner) is None:
                            rejected.append(inner)
                            continue
                        (d / inner).write_bytes(z.read(member))
                        saved.append(d / inner)
            except zipfile.BadZipFile:
                rejected.append(fname + "（压缩包损坏）")
            continue
        if detect_kind(fname) is None:
            rejected.append(fname)
            continue
        (d / fname).write_bytes(data)
        saved.append(d / fname)

    groups = group_by_run(saved)
    runs = []
    for run_no, paths in groups.items():
        bundle = load_bundle(paths)
        runs.append({
            "run_no": run_no,
            "files": {detect_kind(p.name): p.name for p in paths},
            "meta": bundle.meta(),
        })
    b.storage_dir = str(d)
    b.runs = runs
    b.name = name or (f"{runs[0]['run_no']}~{runs[-1]['run_no']}" if len(runs) > 1
                      else (runs[0]["run_no"] if runs else "空批次"))
    if rejected:
        b.error = "以下文件无法识别为 ca/pa/da 车次文件，已忽略：" + "、".join(rejected[:20])
    await session.commit()
    await session.refresh(b)
    return _batch_resp(b)


@router.get("/batches", response_model=List[BatchResp])
async def list_batches(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    rows = list((await session.execute(
        select(WtBatch).where(WtBatch.owner_id == user.id).order_by(WtBatch.id.desc())
    )).scalars())
    return [_batch_resp(b) for b in rows]


@router.delete("/batches/{batch_id}")
async def delete_batch(
    batch_id: int, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    b = await _get_batch(session, user, batch_id)
    if b.storage_dir:
        shutil.rmtree(b.storage_dir, ignore_errors=True)
    await session.delete(b)
    await session.commit()
    return {"ok": True}


class CheckReq(BaseModel):
    rule_ids: List[str] = []
    tail_contracted: bool = False
    balance_ranges: Dict[str, float] = {}
    trend_window: int = 5


@router.post("/batches/{batch_id}/check")
async def run_check(
    batch_id: int,
    req: CheckReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Execute the selected checks over every run in the batch."""
    b = await _get_batch(session, user, batch_id)
    rows = await _user_rules(session, user)
    rules = [_row_to_rule(r) for r in rows]
    lib = await _user_library(session, user)
    customs = await _custom_extractors(session, user)

    paths = sorted(Path(b.storage_dir).iterdir()) if b.storage_dir and Path(b.storage_dir).exists() else []
    bundles = load_batch(paths)
    if not bundles:
        b.status = "error"
        b.error = "本批次没有可解析的车次文件"
        await session.commit()
        raise HTTPException(400, b.error)

    cfg = CheckConfig(
        rule_ids=req.rule_ids, tail_contracted=req.tail_contracted,
        balance_ranges=req.balance_ranges, trend_window=req.trend_window,
    )
    try:
        result = check_batch(bundles, config=cfg, rules=rules, library=lib,
                             custom_extractors=customs)
    except Exception as e:  # noqa: BLE001
        b.status = "error"
        b.error = f"{type(e).__name__}: {e}"
        await session.commit()
        raise HTTPException(500, b.error) from e

    b.config = cfg.to_dict()
    b.result = result.to_dict()
    b.status = "checked"
    b.error = ""
    b.checked_at = datetime.now(timezone.utc)
    await session.commit()
    return b.result


@router.get("/batches/{batch_id}")
async def get_batch(
    batch_id: int, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    b = await _get_batch(session, user, batch_id)
    return {"batch": _batch_resp(b).model_dump(), "result": b.result or None}


@router.get("/batches/{batch_id}/frame")
async def get_batch_frame(
    batch_id: int, run_no: str, table: str = "ca",
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    """The tidy/wide data behind a run — so a reviewer can see the actual rows
    a verdict was computed from, not just the verdict."""
    b = await _get_batch(session, user, batch_id)
    bundles = {x.run_no: x for x in load_batch(sorted(Path(b.storage_dir).iterdir()))}
    bundle = bundles.get(run_no)
    if bundle is None:
        raise HTTPException(404, f"批次中没有车次 {run_no}")
    wide = wide_table(bundle, table)
    if wide.empty:
        long = bundle_to_frame(bundle)
        tables = sorted(long["table"].unique().tolist()) if not long.empty else []
        raise HTTPException(404, f"车次 {run_no} 没有表「{table}」。可用：{'、'.join(tables)}")
    return {
        "run_no": run_no, "table": table,
        "columns": [str(c) for c in wide.columns],
        "rows": json.loads(wide.to_json(orient="records")),
    }


# ══════════════════════════════════════════════════════════════════════════
#  ③ 气动曲线
# ══════════════════════════════════════════════════════════════════════════
class CurveReq(BaseModel):
    run_no: str
    x: str = "ALPHA"
    ys: List[str] = []


@router.post("/batches/{batch_id}/curve")
async def get_curve(
    batch_id: int, req: CurveReq,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    b = await _get_batch(session, user, batch_id)
    bundles = {x.run_no: x for x in load_batch(sorted(Path(b.storage_dir).iterdir()))}
    bundle = bundles.get(req.run_no)
    if bundle is None:
        raise HTTPException(404, f"批次中没有车次 {req.run_no}")
    data = curve_data(bundle, x=req.x, ys=req.ys or None)
    if not data.get("ok"):
        raise HTTPException(400, data.get("error", "无法绘制曲线"))
    data["statistics"] = curve_statistics(data)
    return data


class CurveConclusionReq(BaseModel):
    run_no: str
    statistics: List[Dict[str, Any]]
    meta: Dict[str, Any] = {}


@router.post("/batches/{batch_id}/curve/conclusion")
async def curve_conclusion(
    batch_id: int, req: CurveConclusionReq,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    await _get_batch(session, user, batch_id)
    return await wt_ai.aero_conclusion(llm=llm_for(user), stats=req.statistics, meta=req.meta)


# ══════════════════════════════════════════════════════════════════════════
#  ④ 报告
# ══════════════════════════════════════════════════════════════════════════
class ReportReq(BaseModel):
    run_no: str = ""
    kind: str = "report"          # report | shift | summary
    sections: List[str] = []
    title: str = ""
    author: str = ""
    narratives: Dict[str, str] = {}
    include_curve: bool = True


@router.get("/report-sections")
async def report_sections():
    return {"sections": SECTIONS}


@router.post("/batches/{batch_id}/report")
async def make_report(
    batch_id: int, req: ReportReq,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    b = await _get_batch(session, user, batch_id)
    if not b.result:
        raise HTTPException(400, "请先执行检查再生成报告")

    rows = await _user_rules(session, user)
    rules = [_row_to_rule(r) for r in rows]
    lib = await _user_library(session, user)
    customs = await _custom_extractors(session, user)
    bundles = load_batch(sorted(Path(b.storage_dir).iterdir()))
    cfg = CheckConfig(**{k: v for k, v in (b.config or {}).items()
                         if k in CheckConfig.__dataclass_fields__})
    batch = check_batch(bundles, config=cfg, rules=rules, library=lib,
                        custom_extractors=customs)

    if req.kind == "summary":
        content = build_batch_summary(batch, title=req.title)
        run_no = batch.runs[0].run_no if batch.runs else ""
    else:
        run_no = req.run_no or (batch.runs[0].run_no if batch.runs else "")
        run = next((r for r in batch.runs if r.run_no == run_no), None)
        if run is None:
            raise HTTPException(404, f"批次中没有车次 {run_no}")
        if req.kind == "shift":
            content = build_shift_record(run)
        else:
            bundle = next((x for x in bundles if x.run_no == run_no), None)
            cd = st = None
            if req.include_curve and bundle is not None:
                cd = curve_data(bundle)
                st = curve_statistics(cd) if cd.get("ok") else None
            content = build_report(
                run,
                options=ReportOptions(
                    sections=req.sections or None or list(ReportOptions().sections),
                    title=req.title, author=req.author, narratives=req.narratives,
                ),
                curve=cd, curve_stats=st, batch=batch,
            )

    rpt = WtReport(
        owner_id=user.id, batch_id=b.id, run_no=run_no, kind=req.kind,
        title=req.title, sections=req.sections, content=content, edited="",
    )
    session.add(rpt)
    await session.commit()
    await session.refresh(rpt)
    return {"id": rpt.id, "run_no": run_no, "kind": req.kind, "content": content,
            "filename": report_filename(run_no, req.kind, "md")}


class SaveReportReq(BaseModel):
    edited: str


@router.put("/reports/{report_id}")
async def save_report(
    report_id: int, req: SaveReportReq,
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    r = (await session.execute(
        select(WtReport).where(WtReport.id == report_id, WtReport.owner_id == user.id)
    )).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "报告不存在")
    r.edited = req.edited
    await session.commit()
    return {"ok": True}


@router.get("/reports")
async def list_reports(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    rows = list((await session.execute(
        select(WtReport).where(WtReport.owner_id == user.id).order_by(WtReport.id.desc())
    )).scalars())
    return [{"id": r.id, "batch_id": r.batch_id, "run_no": r.run_no, "kind": r.kind,
             "title": r.title, "edited": bool(r.edited),
             "updated_at": r.updated_at.isoformat() if r.updated_at else ""}
            for r in rows]


@router.get("/reports/{report_id}/export")
async def export_report(
    report_id: int, fmt: str = "txt",
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    """Download as ``车次号_跟班记录.txt`` — the naming the spec mandates."""
    r = (await session.execute(
        select(WtReport).where(WtReport.id == report_id, WtReport.owner_id == user.id)
    )).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "报告不存在")
    body = r.edited or r.content
    ext = "md" if fmt == "md" else "txt"
    fname = report_filename(r.run_no or "batch", r.kind, ext)
    buf = io.BytesIO(body.encode("utf-8-sig"))  # BOM so Windows 记事本 reads CJK
    from urllib.parse import quote
    return StreamingResponse(
        buf, media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename=report.{ext}; filename*=UTF-8''{quote(fname)}"},
    )


# ══════════════════════════════════════════════════════════════════════════
#  ⑤ 知识库：规则 / 特征 / 天平载荷库
# ══════════════════════════════════════════════════════════════════════════
@router.get("/features")
async def list_features():
    return {
        "features": [
            {"key": k, "name": s.name, "unit": s.unit, "requires": s.requires,
             "needs_prev_run": s.needs_prev_run, "description": s.description,
             "method": s.method}
            for k, s in sorted(FEATURE_SPECS.items())
        ],
        "catalog_markdown": feature_catalog(),
        "format_doc": FILE_FORMAT_DOC,
        "extractor_contract": EXTRACTOR_CONTRACT,
    }


@router.get("/rules")
async def list_rules(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    rows = await _user_rules(session, user)
    return {"rules": [_rule_row_dict(r) for r in rows]}


class RuleReq(BaseModel):
    rule_id: str
    name: str
    feature: str
    object: str = ""
    note: str = ""
    applies_when_mach: str = ""
    bands: List[Dict[str, Any]] = []
    refs: List[str] = []
    enabled: bool = True
    source: str = "user"


def _validate_or_400(payload: Dict[str, Any]) -> Rule:
    try:
        rule = Rule.from_dict(payload)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"规则结构不合法：{type(e).__name__}: {e}") from e
    problems = rule.validate()
    if problems:
        raise HTTPException(400, "规则校验未通过：" + "；".join(problems))
    return rule


@router.post("/rules")
async def create_rule(
    req: RuleReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    await _ensure_seeded(session, user)
    payload = req.model_dump()
    # A rule may bind to a custom extractor that is not in FEATURE_SPECS yet;
    # register it from the algorithm library so validation can see it.
    if req.feature.startswith("custom:"):
        customs = await _custom_extractors(session, user)
        if req.feature not in customs:
            raise HTTPException(400, f"自定义特征「{req.feature}」不在算法库中，请先保存算子")
        from ..windtunnel.features import FeatureSpec
        FEATURE_SPECS.setdefault(req.feature, FeatureSpec(
            key=req.feature, name=customs[req.feature]["name"], unit="",
            description="用户/AI 自定义特征算子"))
    rule = _validate_or_400(payload)
    dup = (await session.execute(
        select(WtRule).where(WtRule.owner_id == user.id, WtRule.rule_id == rule.rule_id)
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(400, f"规则 ID「{rule.rule_id}」已存在")
    row = WtRule(
        owner_id=user.id, rule_id=rule.rule_id, name=rule.name, feature=rule.feature,
        object_name=rule.object_, note=rule.note,
        applies_when_mach=rule.applies_when_mach,
        bands=[b.to_dict() for b in rule.bands], refs=rule.refs,
        enabled=rule.enabled, source=req.source or "user",
        changelog=[{"at": datetime.now(timezone.utc).isoformat(), "what": "新建"}],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _rule_row_dict(row)


@router.put("/rules/{row_id}")
async def update_rule(
    row_id: int, req: RuleReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    row = (await session.execute(
        select(WtRule).where(WtRule.id == row_id, WtRule.owner_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "规则不存在")
    if req.feature.startswith("custom:"):
        customs = await _custom_extractors(session, user)
        if req.feature not in customs:
            raise HTTPException(400, f"自定义特征「{req.feature}」不在算法库中")
        from ..windtunnel.features import FeatureSpec
        FEATURE_SPECS.setdefault(req.feature, FeatureSpec(
            key=req.feature, name=customs[req.feature]["name"], unit=""))
    rule = _validate_or_400(req.model_dump())
    before = {"bands": row.bands, "enabled": row.enabled}
    row.rule_id = rule.rule_id
    row.name = rule.name
    row.feature = rule.feature
    row.object_name = rule.object_
    row.note = rule.note
    row.applies_when_mach = rule.applies_when_mach
    row.bands = [b.to_dict() for b in rule.bands]
    row.refs = rule.refs
    row.enabled = rule.enabled
    row.changelog = (row.changelog or []) + [{
        "at": datetime.now(timezone.utc).isoformat(),
        "what": "修改", "before": before,
    }]
    await session.commit()
    await session.refresh(row)
    return _rule_row_dict(row)


@router.delete("/rules/{row_id}")
async def delete_rule(
    row_id: int, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    row = (await session.execute(
        select(WtRule).where(WtRule.id == row_id, WtRule.owner_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "规则不存在")
    await session.delete(row)
    await session.commit()
    return {"ok": True}


@router.post("/rules/restore-defaults")
async def restore_defaults(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    """Re-seed the shipped rules, keeping user/AI rules untouched."""
    rows = list((await session.execute(
        select(WtRule).where(WtRule.owner_id == user.id, WtRule.source == "builtin")
    )).scalars())
    for r in rows:
        await session.delete(r)
    await session.flush()
    for r in seed_rules():
        session.add(WtRule(
            owner_id=user.id, rule_id=r.rule_id, name=r.name, feature=r.feature,
            object_name=r.object_, note=r.note, applies_when_mach=r.applies_when_mach,
            bands=[b.to_dict() for b in r.bands], refs=list(r.refs),
            enabled=True, source="builtin", builtin_id=r.rule_id,
            changelog=[{"at": datetime.now(timezone.utc).isoformat(), "what": "恢复默认"}],
        ))
    await session.commit()
    return {"ok": True}


# ── AI: 自然语言 → 规则 ──────────────────────────────────────────────────
class DraftReq(BaseModel):
    request: str


@router.post("/rules/draft")
async def draft_rule_api(
    req: DraftReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    rows = await _user_rules(session, user)
    customs = await _custom_extractors(session, user)
    from ..windtunnel.features import FeatureSpec
    for key, spec in customs.items():
        FEATURE_SPECS.setdefault(key, FeatureSpec(
            key=key, name=spec["name"], unit="", description="用户/AI 自定义特征算子"))
    return await wt_ai.draft_rule(
        req.request, llm=llm_for(user),
        existing_rule_ids=[r.rule_id for r in rows],
    )


class TriageReq(BaseModel):
    request: str


@router.post("/rules/triage")
async def triage_api(req: TriageReq, user: User = Depends(current_user)):
    """Does an existing feature already measure this, or do we need a new one?"""
    return await wt_ai.plan_custom_check(req.request, llm=llm_for(user))


class PreviewReq(BaseModel):
    rule: Dict[str, Any]
    batch_id: int


@router.post("/rules/preview")
async def preview_rule(
    req: PreviewReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Try a DRAFT rule on real runs without saving it.

    This is the gate that turns an AI proposal into an engineering decision:
    the user sees exactly which runs the new rule would flag, and at what
    level, before it can affect a single report.
    """
    b = await _get_batch(session, user, req.batch_id)
    customs = await _custom_extractors(session, user)
    from ..windtunnel.features import FeatureSpec
    for key, spec in customs.items():
        FEATURE_SPECS.setdefault(key, FeatureSpec(
            key=key, name=spec["name"], unit="", description="用户/AI 自定义特征算子"))
    rule = _validate_or_400(req.rule)
    bundles = load_batch(sorted(Path(b.storage_dir).iterdir()))
    lib = await _user_library(session, user)
    result = check_batch(bundles, config=CheckConfig(rule_ids=[rule.rule_id]),
                         rules=[rule], library=lib, custom_extractors=customs)
    return {
        "ok": True,
        "rule": rule.to_dict(),
        "preview": [
            {"run_no": r.run_no,
             "findings": [f.to_dict() for f in r.findings]}
            for r in result.runs
        ],
    }


# ── AI: 自然语言 → 特征算子 ─────────────────────────────────────────────
class ExtractorGenReq(BaseModel):
    request: str
    batch_id: Optional[int] = None
    run_no: str = ""


@router.post("/extractors/generate")
async def generate_extractor_api(
    req: ExtractorGenReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    hint = ""
    if req.batch_id:
        b = await _get_batch(session, user, req.batch_id)
        bundles = load_batch(sorted(Path(b.storage_dir).iterdir()))
        bundle = next((x for x in bundles if not req.run_no or x.run_no == req.run_no),
                      bundles[0] if bundles else None)
        if bundle is not None:
            hint = frame_schema_hint(bundle)
    return await wt_ai.generate_extractor(req.request, llm=llm_for(user), schema_hint=hint)


class ExtractorSaveReq(BaseModel):
    code: str
    name: str
    slug: str
    description: str = ""
    test_report: Dict[str, Any] = {}


@router.post("/extractors")
async def save_extractor(
    req: ExtractorSaveReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Approve a generated extractor into the algorithm library.

    Stored as a normal ``Algorithm`` row with ``category='custom'`` — it is a
    first-class tool afterwards, callable from chat, from a flow template, and
    referenceable by a rule as ``custom:<slug>``.
    """
    slug = req.slug.strip()
    if not slug:
        raise HTTPException(400, "slug 不能为空")
    dup = (await session.execute(
        select(Algorithm).where(Algorithm.owner_id == user.id, Algorithm.slug == slug)
    )).scalar_one_or_none()
    if dup is not None:
        dup.code = req.code
        dup.name = req.name
        dup.description = req.description
        dup.version = (dup.version or 1) + 1
        dup.is_verified = True
        dup.test_report = req.test_report
        await session.commit()
        return {"ok": True, "feature_key": f"custom:{slug}", "updated": True}
    row = Algorithm(
        owner_id=user.id, slug=slug, name=req.name, category="custom",
        description=req.description, source="ai", code=req.code,
        params_schema={}, returns="dict", is_verified=True,
        test_report=req.test_report,
    )
    session.add(row)
    await session.commit()
    return {"ok": True, "feature_key": f"custom:{slug}", "updated": False}


@router.get("/extractors")
async def list_extractors(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    rows = list((await session.execute(
        select(Algorithm).where(Algorithm.owner_id == user.id,
                                Algorithm.category == "custom")
    )).scalars())
    return {"extractors": [
        {"id": a.id, "slug": a.slug, "name": a.name, "description": a.description,
         "feature_key": f"custom:{a.slug}", "verified": a.is_verified,
         "version": a.version, "code": a.code}
        for a in rows
    ]}


# ── 天平载荷库 ──────────────────────────────────────────────────────────
class BalanceReq(BaseModel):
    name: str
    ranges: Dict[str, float]
    note: str = ""


@router.get("/balances")
async def list_balances(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db)
):
    await _ensure_seeded(session, user)
    rows = list((await session.execute(
        select(WtBalance).where(WtBalance.owner_id == user.id).order_by(WtBalance.name)
    )).scalars())
    return {"units": list(BALANCE_UNITS),
            "balances": [{"id": r.id, "name": r.name, "ranges": r.ranges, "note": r.note}
                         for r in rows]}


@router.post("/balances")
async def add_balance(
    req: BalanceReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    missing = [u for u in BALANCE_UNITS if u not in req.ranges]
    if missing:
        raise HTTPException(400, f"缺少单元量程：{'、'.join(missing)}")
    row = (await session.execute(
        select(WtBalance).where(WtBalance.owner_id == user.id, WtBalance.name == req.name)
    )).scalar_one_or_none()
    if row is None:
        row = WtBalance(owner_id=user.id, name=req.name.strip())
        session.add(row)
    row.ranges = {u: float(req.ranges[u]) for u in BALANCE_UNITS}
    row.note = req.note
    await session.commit()
    await session.refresh(row)
    return {"id": row.id, "name": row.name, "ranges": row.ranges, "note": row.note}


@router.post("/balances/import")
async def import_balances(
    file: UploadFile = File(...),
    user: User = Depends(current_user), session: AsyncSession = Depends(get_db),
):
    """Import a whole 天平载荷库 text file (``name My Z Mz Y Mx Q`` per line)."""
    data = await file.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("gbk", errors="replace")
    lib = BalanceLibrary.from_text(text)
    if not lib.entries:
        raise HTTPException(400, "文件中没有解析到任何天平条目（每行需为：名称 My Z Mz Y Mx Q）")
    existing = {r.name.lower(): r for r in (await session.execute(
        select(WtBalance).where(WtBalance.owner_id == user.id)
    )).scalars()}
    added = updated = 0
    for e in lib.entries.values():
        row = existing.get(e.name.lower())
        if row is None:
            session.add(WtBalance(owner_id=user.id, name=e.name, ranges=e.ranges, note=e.note))
            added += 1
        else:
            row.ranges = e.ranges
            row.note = e.note
            updated += 1
    await session.commit()
    return {"ok": True, "added": added, "updated": updated}


@router.delete("/balances/{row_id}")
async def delete_balance(
    row_id: int, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    row = (await session.execute(
        select(WtBalance).where(WtBalance.id == row_id, WtBalance.owner_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "条目不存在")
    await session.delete(row)
    await session.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════
#  AI 问答与小结
# ══════════════════════════════════════════════════════════════════════════
class AskReq(BaseModel):
    batch_id: int
    run_no: str = ""
    question: str


@router.post("/ask")
async def ask(
    req: AskReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    b = await _get_batch(session, user, req.batch_id)
    if not b.result:
        raise HTTPException(400, "请先执行检查")
    runs = (b.result or {}).get("runs", [])
    ctx = next((r for r in runs if r["run_no"] == req.run_no), None) or \
        {"批次汇总": (b.result or {}).get("summary"), "各车次": [
            {"run_no": r["run_no"], "grade": r["grade"], "counts": r["counts"]} for r in runs]}
    return await wt_ai.answer_question(llm=llm_for(user), question=req.question, context=ctx)


class SummarizeReq(BaseModel):
    batch_id: int
    run_no: str


@router.post("/summarize")
async def summarize(
    req: SummarizeReq, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    b = await _get_batch(session, user, req.batch_id)
    runs = (b.result or {}).get("runs", [])
    run = next((r for r in runs if r["run_no"] == req.run_no), None)
    if run is None:
        raise HTTPException(404, "车次不存在或尚未检查")
    return await wt_ai.explain_findings(llm=llm_for(user), run_result_dict=run)


@router.get("/health")
async def wt_health(user: User = Depends(current_user)):
    llm = llm_for(user)
    return {"ok": True, "llm_configured": llm.is_configured, "model": llm.model,
            "features": len(FEATURE_SPECS), "seed_rules": len(seed_rules())}
