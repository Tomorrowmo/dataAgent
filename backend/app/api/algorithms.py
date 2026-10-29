import json
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..algorithms import registry
from ..db.models import Algorithm, Dataset, Run, User
from ..sandbox import executor as sandbox_executor
from ..sandbox.validator import validate_algorithm_code
from ..services import algo_store
from ..services.algo_store import find_algorithm
from ..services.algo_check import admission_check, diagnose_run
from ..services.codegen import generate_algorithm, parse_meta
from ..services.datasets import _persist_dataset, load_dataset_df
from .deps import current_user, get_db, llm_for

router = APIRouter(prefix="/algorithms", tags=["algorithms"])


class AlgoSummary(BaseModel):
    slug: str
    name: str
    category: str
    description: str
    source: str  # builtin | user | ai
    params_schema: Dict[str, Any]
    returns: str
    verified: bool = True
    id: Optional[int] = None


@router.get("", response_model=List[AlgoSummary])
async def list_all(
    category: Optional[str] = None,
    source: Optional[str] = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    items: List[AlgoSummary] = []
    if source in (None, "builtin"):
        for spec in registry.list_builtins(category):
            items.append(AlgoSummary(
                slug=spec.slug, name=spec.name, category=spec.category,
                description=spec.description, source="builtin",
                params_schema=spec.params_schema, returns=spec.returns, verified=True,
            ))
    if source in (None, "user", "ai"):
        q = select(Algorithm).where(
            (Algorithm.owner_id == user.id) | (Algorithm.is_public == True)  # noqa: E712
        )
        if category:
            q = q.where(Algorithm.category == category)
        if source in ("user", "ai"):
            q = q.where(Algorithm.source == source)
        rows = (await session.execute(q.order_by(Algorithm.id.desc()))).scalars().all()
        items.extend([
            AlgoSummary(
                slug=r.slug, name=r.name, category=r.category, description=r.description,
                source=r.source, params_schema=r.params_schema or {}, returns=r.returns,
                verified=bool(r.is_verified), id=r.id,
            )
            for r in rows
        ])
    return items


class TestCodeReq(BaseModel):
    code: str
    params: Dict[str, Any] = Field(default_factory=dict)
    dataset_id: Optional[int] = None


@router.post("/test")
async def test_code(
    body: TestCodeReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    validation = validate_algorithm_code(body.code)
    df = None
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds is None:
            raise HTTPException(404, "dataset not found")
        df = load_dataset_df(ds)

    result = sandbox_executor.execute(body.code, body.params, input_df=df, save_result=False)
    # Best-effort parse of META so the save dialog can pre-fill name / description
    # / category / params_schema (same curation step as the AI-tool flow).
    meta: Dict[str, Any] = {}
    try:
        meta = parse_meta(body.code)
    except Exception:
        pass
    return {
        "validation": {
            "ok": validation.ok,
            "errors": validation.errors,
            "imports": validation.imports,
            "has_run": validation.has_run_function,
            "has_meta": validation.has_meta,
        },
        "execution": result.to_dict(),
        "meta": meta,
        "diagnosis": None if result.status == "ok" else diagnose_run(
            result.error, code=body.code, params=body.params,
            columns=[str(c) for c in df.columns] if df is not None else None, has_df=df is not None,
        ),
    }


class CheckReq(BaseModel):
    code: str


@router.post("/check")
async def check_code(body: CheckReq, user: User = Depends(current_user)):
    """Admission checklist for an uploaded / pasted algorithm (static, nothing
    runs): syntax, run() entry, META, allowed libraries, forbidden constructs,
    declared params, self-tests — each with the offending line when it fails."""
    return admission_check(body.code)


class AutofixReq(BaseModel):
    code: str
    dataset_id: Optional[int] = None
    # From the code editor's「AI 校正」: what the user wants changed, and the
    # last debug-run error to fix. Both optional (empty = plain conformance fix).
    instruction: str = ""
    error: str = ""
    # From the code editor's「AI 校正」: what the user wants changed, and the
    # last debug-run error to fix. Both optional (empty = plain conformance fix).
    instruction: str = ""
    error: str = ""


@router.post("/autofix")
async def autofix(
    body: AutofixReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Auto-correct a pasted snippet / uploaded .py into a conformant tool.

    The接入规范 is: a top-level META dict + `run(df, **params)`, sandbox-safe
    imports (numpy / pandas / scipy / sklearn / stdlib) only. Users often paste
    a bare function or a script — this hands their code to the same codegen +
    self-test loop the AI-generate path uses, instructed to PRESERVE the
    original logic while wrapping it into the required shape, then proves it runs
    in the sandbox. Returns the same bundle as /generate (code, meta, tests,
    all_tests_passed, attempt_log, final_hints…)."""
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")
    if not body.code.strip():
        raise HTTPException(400, "code is empty — nothing to fix")

    schema_hint = None
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds:
            schema_hint = str(ds.schema_json)[:4000]

    fix_prompt = (
        "把下面这段用户提供的 Python 代码改造成符合接入规范的算法模块：\n"
        "- 保留它的核心计算逻辑，不要改变它实际做的事；\n"
        "- 若缺少，补上顶级 META 字典与 `run(df, **params)` 入口（把原有函数/脚本逻辑接进 run）；\n"
        "- 只用允许的库（numpy / pandas / scipy / sklearn 子模块 / 标准库），把不允许的依赖替换或移除；\n"
        "- 补 1–3 个 test_cases 以便沙箱自测。\n\n"
        + (f"用户的修改要求：{body.instruction.strip()}\n\n" if body.instruction.strip() else "")
        + (f"最近一次调试运行的报错（请修正）：\n{body.error.strip()[:2000]}\n\n" if body.error.strip() else "")
        + "用户代码：\n```python\n" + body.code.strip() + "\n```"
    )
    try:
        bundle = await generate_algorithm(fix_prompt, llm=llm, schema_hint=schema_hint)
    except Exception as e:
        raise HTTPException(400, f"autofix failed: {e}") from e
    return bundle


class ExplainTestErrorReq(BaseModel):
    code: str
    error: str
    dataset_id: Optional[int] = None


@router.post("/explain-test-error")
async def explain_test_error(
    body: ExplainTestErrorReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Explain in plain Chinese why an UPLOADED-but-unsaved algorithm failed its
    test. Unlike /explain-error this has no slug — it's grounded in the raw code,
    the error, and whether a dataset was selected (a very common cause is 选了
    '无' but run() requires df). Also surfaces a deterministic diagnostic hint
    (from codegen.diagnose) when one matches, so infra errors don't need an LLM."""
    from ..services.codegen import diagnose

    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")

    name, desc = "(未命名算法)", ""
    try:
        meta = parse_meta(body.code)
        name = meta.get("name") or name
        desc = meta.get("description") or ""
    except Exception:
        pass  # code may not parse yet — explain from the error + snippet anyway

    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds:
            sj = ds.schema_json or {}
            cols = sj.get("columns", [])
            ds_ctx = (f"测试时选了数据集 '{ds.name}'（{ds.rows} 行）的列："
                      + ", ".join(f"{c['name']}({c['dtype']})" for c in cols[:40]))
        else:
            ds_ctx = "测试时未选择数据集（数据集=无），run(df) 收到的 df 是 None。"
    else:
        ds_ctx = "测试时未选择数据集（数据集=无），run(df) 收到的 df 是 None。"

    hints = diagnose(body.error)
    hint_line = ("\n已知诊断提示：" + "；".join(h["cause"] for h in hints)) if hints else ""

    sys_prompt = ("你是数据分析助手。一个用户上传的 Python 算法在沙箱测试时报错了。"
                  "用通俗中文解释:1) 为什么失败(结合代码、报错和是否选了数据集);"
                  "2) 具体怎么改才能通过。简洁 3-5 句,不要原样复述英文报错。"
                  "若失败原因是没选数据集而 run() 需要 df,请直接提示在上方下拉里选一个数据集再测。")
    user_prompt = (
        f"算法：{name} —— {desc}\n"
        f"{ds_ctx}{hint_line}\n"
        f"报错信息：{body.error[:800]}\n"
        f"代码（节选）：\n{body.code[:2000]}\n\n"
        "请解释为什么失败,并给出修改建议。"
    )
    try:
        text = await llm.chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.2, max_tokens=600,
        )
    except Exception as e:
        raise HTTPException(400, f"解释失败: {type(e).__name__}: {e}")
    return {"explanation": text, "hints": hints}


class SaveReq(BaseModel):
    code: str
    name: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    source: str = "user"  # user | ai
    # Curated params schema from the save dialog — overrides the code's META
    # params_schema (lets the user pick which params are exposed, with labels /
    # defaults). When None, the META's schema is used as-is.
    params_schema: Optional[Dict[str, Any]] = None
    test_report: Dict[str, Any] = Field(default_factory=dict)
    is_public: bool = False
    # Code editor path: re-run the code in the sandbox on the server (with this
    # dataset / params) and refuse to save unless it passes, instead of trusting
    # the client-sent test_report.
    verify: bool = False
    dataset_id: Optional[int] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    note: str = ""


def _summary(row: Algorithm) -> AlgoSummary:
    return AlgoSummary(
        slug=row.slug, name=row.name, category=row.category, description=row.description,
        source=row.source, params_schema=row.params_schema or {}, returns=row.returns,
        verified=bool(row.is_verified), id=row.id,
    )


async def _verify_in_sandbox(
    session: AsyncSession, user: User, code: str, dataset_id: Optional[int], params: Dict[str, Any],
) -> Dict[str, Any]:
    df = None
    if dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds is None:
            raise HTTPException(404, "dataset not found")
        df = load_dataset_df(ds)
    return sandbox_executor.execute(code, params, input_df=df, save_result=False).to_dict()


@router.post("/save", response_model=AlgoSummary)
async def save_algorithm(
    body: SaveReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    validation = validate_algorithm_code(body.code)
    if not validation.ok:
        raise HTTPException(400, "code failed validation: " + "; ".join(validation.errors))

    try:
        meta = parse_meta(body.code)
    except Exception as e:
        raise HTTPException(400, f"could not extract META: {e}") from e

    slug = (body.slug or meta.get("slug") or "").strip()
    if not slug:
        raise HTTPException(400, "slug is required (provide in body or in META)")
    if registry.get_builtin(slug):
        raise HTTPException(400, f"slug '{slug}' 与内置算法重名，请在 META 里换一个 slug")

    test_report = body.test_report or {}
    if body.verify:
        execution = await _verify_in_sandbox(session, user, body.code, body.dataset_id, body.params)
        if execution["status"] != "ok":
            raise HTTPException(400, "沙箱调试运行未通过，未保存：" + (execution.get("error") or "")[:1500])
        test_report = {"all_tests_passed": True, "tests": [execution], "dataset_id": body.dataset_id}

    fields = dict(
        name=body.name or meta.get("name") or slug,
        category=body.category or meta.get("category") or "custom",
        description=body.description or meta.get("description") or "",
        code=body.code,
        params_schema=body.params_schema if body.params_schema is not None else (meta.get("params_schema") or {}),
        returns=meta.get("returns") or "dataframe",
        is_verified=bool(test_report.get("all_tests_passed", False)),
        test_report=test_report,
    )
    # One live row per (owner, slug): saving the same slug again is a new
    # VERSION of that row (history in algorithm_versions), not a second row.
    existing = (await session.execute(
        select(Algorithm).where(Algorithm.slug == slug, Algorithm.owner_id == user.id)
        .order_by(Algorithm.id.desc()).limit(1)
    )).scalar_one_or_none()
    if existing is not None:
        await algo_store.ensure_history(session, existing, user.id)
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.version = (existing.version or 1) + 1
        row = existing
    else:
        row = Algorithm(owner_id=user.id, slug=slug, source=body.source,
                        is_public=body.is_public, version=1, **fields)
        session.add(row)
        await session.flush()
    algo_store.snapshot(session, row, note=body.note or ("新建" if row.version == 1 else "保存"), user_id=user.id)
    await session.commit()
    await session.refresh(row)
    return _summary(row)


class GenerateReq(BaseModel):
    description: str
    dataset_id: Optional[int] = None


@router.post("/generate")
async def generate(
    body: GenerateReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set a DeepSeek key in Settings.")
    schema_hint = None
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds:
            schema_hint = str(ds.schema_json)[:4000]
    try:
        bundle = await generate_algorithm(body.description, llm=llm, schema_hint=schema_hint)
    except Exception as e:
        raise HTTPException(400, f"generation failed: {e}") from e
    return bundle


class ConfirmGeneratedReq(BaseModel):
    slug: str
    keep: bool
    # Optional edits applied on keep, so the saved tool is GENERAL & reusable:
    # a clear name/description + a curated params schema (which params the user
    # may set, with labels/defaults). AI pre-fills these; the user can edit.
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    params_schema: Optional[dict] = None


@router.post("/confirm-generated")
async def confirm_generated(
    body: ConfirmGeneratedReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """User's decision on an AI-generated tool the agent auto-registered (as a
    draft) and used this turn: keep it in the library (optionally with edited
    name / description / params schema), or discard (delete) it."""
    row = (await session.execute(
        select(Algorithm).where(Algorithm.slug == body.slug, Algorithm.owner_id == user.id)
        .order_by(Algorithm.id.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "tool not found (maybe already discarded)")
    if body.keep:
        if body.name:
            row.name = body.name.strip() or row.name
        if body.description is not None:
            row.description = body.description.strip()
        if body.category:
            row.category = body.category.strip() or row.category
        if body.params_schema is not None:
            row.params_schema = body.params_schema
        row.is_verified = True
        await session.commit()
        return {"ok": True, "kept": True, "slug": row.slug, "name": row.name}
    await algo_store.delete_algorithm(session, row)
    await session.commit()
    return {"ok": True, "kept": False, "slug": body.slug}


class RefineReq(BaseModel):
    slug: str
    instruction: str                       # plain-language: what to add / change
    dataset_id: Optional[int] = None


@router.post("/refine")
async def refine_tool(
    body: RefineReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Let AI REWRITE an existing tool to add/adjust a capability or parameter from
    a plain-language instruction. Returns a fresh generation bundle (new code +
    meta + tests); if the rewrite passes its own sandbox tests we persist the new
    code + params onto the (still-unverified) draft, so the Save dialog can refresh
    its params and the new option is REAL (the algorithm actually uses it) — not a
    dead label."""
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set a key in Settings.")
    if not body.instruction.strip():
        raise HTTPException(400, "refine requires an instruction")
    row = (await session.execute(
        select(Algorithm).where(Algorithm.slug == body.slug, Algorithm.owner_id == user.id)
        .order_by(Algorithm.id.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "tool not found")

    schema_hint = None
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds:
            schema_hint = str(ds.schema_json)[:4000]

    prompt = (
        "Here is an existing algorithm. Rewrite it to satisfy the user's request, "
        "KEEPING its current behavior unless the request changes it. Expose any new "
        "option as a proper run() parameter that is BOTH declared in META params_schema "
        "AND actually used in run() — never a dead parameter.\n\n"
        f"Current name: {row.name}\n"
        f"Current description: {row.description}\n\n"
        f"Current code:\n```python\n{row.code}\n```\n\n"
        f"User's request: {body.instruction.strip()}\n\n"
        "Return the complete rewritten algorithm (META + run + test_cases)."
    )
    try:
        bundle = await generate_algorithm(prompt, llm=llm, schema_hint=schema_hint)
    except Exception as e:
        raise HTTPException(400, f"refine failed: {e}") from e

    if bundle.get("all_tests_passed"):
        meta = bundle.get("meta") or {}
        row.code = bundle.get("code") or row.code
        if meta.get("params_schema") is not None:
            row.params_schema = meta["params_schema"]
        if meta.get("description"):
            row.description = meta["description"]
        await session.commit()
    return bundle


class SuggestParamsReq(BaseModel):
    slug: str
    dataset_id: Optional[int] = None
    intent: Optional[str] = None  # optional natural-language description of what the user wants


@router.post("/suggest-params")
async def suggest_params(
    body: SuggestParamsReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Given an algorithm + dataset (+ optional plain-language intent), ask the
    LLM to suggest sensible parameter values and explain each in Chinese. It only
    FILLS the form — the user reviews and runs. (Assistive, not agentic, so it
    doesn't overlap with the autonomous chat agent.)"""
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")

    spec = registry.get_builtin(body.slug)
    if spec:
        name, desc, schema = spec.name, spec.description, spec.params_schema
    else:
        row = await find_algorithm(session, body.slug, user.id)
        if row is None:
            raise HTTPException(404, "algorithm not found")
        name, desc, schema = row.name, row.description, row.params_schema or {}

    ds_ctx = "（用户未选数据集）"
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds:
            sj = ds.schema_json or {}
            cols = sj.get("columns", [])
            head = sj.get("head", [])
            ds_ctx = (
                f"数据集 '{ds.name}'（{ds.rows} 行）的列：" +
                ", ".join(f"{c['name']}({c['dtype']})" for c in cols) +
                f"\n前几行：{json.dumps(head[:3], default=str)[:800]}"
            )

    sys_prompt = ("你是数据分析助手,帮非专家为一个算法挑选合理的参数值,并用通俗中文解释。"
                  "只输出一个 JSON 对象,不要任何多余文字。")
    user_prompt = (
        f"算法：{name} —— {desc}\n"
        f"参数定义(JSON Schema)：{json.dumps(schema, ensure_ascii=False, default=str)}\n\n"
        f"{ds_ctx}\n\n"
        + (f"用户想做的事：{body.intent}\n\n" if body.intent else "")
        + "请基于这个数据集给出合理的参数取值,返回 JSON：\n"
        '{\n'
        '  "params": { "<参数名>": <建议值> },   // 用真实列名;数值要合理;能用默认的参数可省略\n'
        '  "explanations": { "<参数名>": "<一句话:这参数是什么 + 为什么取这个值>" },\n'
        '  "note": "<一句话总体建议>"\n'
        '}'
    )

    raw = ""
    try:
        raw = await llm.chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.2, max_tokens=1200, json_mode=True,
        )
        parsed = json.loads(raw)
    except Exception:
        import re
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        try:
            parsed = json.loads(m.group(0)) if m else {}
        except Exception:
            parsed = {}

    return {
        "params": parsed.get("params", {}) or {},
        "explanations": parsed.get("explanations", {}) or {},
        "note": parsed.get("note", "") or "",
    }


class ExplainErrorReq(BaseModel):
    slug: str
    error: str
    params: Dict[str, Any] = Field(default_factory=dict)
    dataset_id: Optional[int] = None


@router.post("/explain-error")
async def explain_error(
    body: ExplainErrorReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Explain a tool-execution error in plain Chinese (what went wrong + how to
    fix it), grounded in the algorithm, the user's params, and the dataset."""
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")

    spec = registry.get_builtin(body.slug)
    if spec:
        name, desc, schema = spec.name, spec.description, spec.params_schema
    else:
        row = await find_algorithm(session, body.slug, user.id)
        name, desc, schema = (row.name, row.description, row.params_schema or {}) if row else (body.slug, "", {})

    ds_ctx = ""
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds:
            sj = ds.schema_json or {}
            cols = sj.get("columns", [])
            ds_ctx = f"数据集 '{ds.name}'（{ds.rows} 行）的列：" + ", ".join(f"{c['name']}({c['dtype']})" for c in cols)

    sys_prompt = ("你是数据分析助手。用通俗中文解释一个工具执行为什么报错,并给出具体可操作的修改建议。"
                  "简洁(3-5 句),不要原样复述英文报错,直接说人话。")
    user_prompt = (
        f"算法：{name} —— {desc}\n"
        f"参数定义：{json.dumps(schema, ensure_ascii=False, default=str)[:1500]}\n"
        f"用户填的参数：{json.dumps(body.params, ensure_ascii=False, default=str)[:800]}\n"
        f"{ds_ctx}\n"
        f"报错信息：{body.error[:800]}\n\n"
        "请解释：1) 为什么会报这个错(结合用户的参数和数据);2) 具体怎么改才能成功。"
    )
    try:
        text = await llm.chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.2, max_tokens=600,
        )
    except Exception as e:
        raise HTTPException(400, f"解释失败: {type(e).__name__}: {e}")
    return {"explanation": text}


class ExplainResultReq(BaseModel):
    slug: str
    params: Dict[str, Any] = Field(default_factory=dict)
    dataset_id: Optional[int] = None
    summary: Dict[str, Any] = Field(default_factory=dict)


@router.post("/explain-result")
async def explain_result(
    body: ExplainResultReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Interpret an algorithm's RESULT in plain Chinese — what it shows, what's
    notable, and a possible next step — grounded in the algorithm + dataset."""
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")

    spec = registry.get_builtin(body.slug)
    if spec:
        name, desc = spec.name, spec.description
    else:
        row = await find_algorithm(session, body.slug, user.id)
        name, desc = (row.name, row.description) if row else (body.slug, "")

    ds_ctx = ""
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds:
            cols = (ds.schema_json or {}).get("columns", [])
            ds_ctx = f"数据集 '{ds.name}'（{ds.rows} 行）的列：" + ", ".join(f"{c['name']}({c['dtype']})" for c in cols)

    sys_prompt = ("你是数据分析助手。用通俗中文解读一个算法的执行结果对用户意味着什么。"
                  "简洁(3-5 句):说清结果说明了什么、有什么值得注意的、下一步可以做什么。不要复述参数。")
    user_prompt = (
        f"算法：{name} —— {desc}\n"
        f"用户填的参数：{json.dumps(body.params, ensure_ascii=False, default=str)[:600]}\n"
        f"{ds_ctx}\n"
        f"执行结果摘要：{json.dumps(body.summary, ensure_ascii=False, default=str)[:2000]}\n\n"
        "请解读这个结果。"
    )
    try:
        text = await llm.chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.2, max_tokens=600,
        )
    except Exception as e:
        raise HTTPException(400, f"解读失败: {type(e).__name__}: {e}")
    return {"explanation": text}


class RunToDatasetReq(BaseModel):
    slug: str
    params: Dict[str, Any] = Field(default_factory=dict)
    dataset_id: int


@router.post("/run-to-dataset")
async def run_to_dataset(
    body: RunToDatasetReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Run an algorithm and save its DataFrame output as a DERIVED dataset with
    lineage — the manual counterpart to pipeline materialization."""
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    df = load_dataset_df(ds)

    spec = registry.get_builtin(body.slug)
    if spec:
        res = registry.execute_builtin(body.slug, df, body.params)
        label = spec.name
    else:
        row = await find_algorithm(session, body.slug, user.id)
        if row is None:
            raise HTTPException(404, "algorithm not found")
        res = registry.execute_code(row.code, df, body.params)
        label = row.name

    if res.get("status") != "ok" or not res.get("result_path"):
        raise HTTPException(400, f"该算法没有产出表格结果,无法存为数据集（{res.get('error','') or res.get('summary',{})}）")

    out_df = pd.read_parquet(res["result_path"])
    d = await _persist_dataset(
        session, owner_id=user.id, df=out_df,
        name=f"{ds.name} · {label}", filename=f"{body.slug}.parquet",
        file_format="derived", description=f"由「{ds.name}」经『{label}』得到",
        kind="derived", derived_from=ds.id,
        lineage={"from": ds.id, "from_name": ds.name, "op": {"slug": body.slug, "label": label, "params": body.params}},
    )
    await session.commit()
    await session.refresh(d)
    return {"id": d.id, "name": d.name, "rows": d.rows, "columns": d.columns}


class RunReq(BaseModel):
    slug: str
    params: Dict[str, Any] = Field(default_factory=dict)
    dataset_id: Optional[int] = None


@router.post("/run")
async def run_algorithm(
    body: RunReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    df = None
    ds_id = body.dataset_id
    if ds_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == ds_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds is None:
            raise HTTPException(404, "dataset not found")
        df = load_dataset_df(ds)

    if registry.get_builtin(body.slug):
        result = registry.execute_builtin(body.slug, df, body.params)
        algo_id = None
    else:
        row = await find_algorithm(session, body.slug, user.id)
        if row is None:
            raise HTTPException(404, "algorithm not found")
        result = registry.execute_code(row.code, df, body.params)
        algo_id = row.id

    run = Run(
        owner_id=user.id,
        algorithm_id=algo_id or 0,
        dataset_id=ds_id,
        params=body.params,
        status=result.get("status", "error"),
        error=result.get("error", ""),
        duration_ms=int(result.get("duration_ms", 0)),
        result_summary=result.get("summary") or {},
        result_artifacts=[result["result_path"]] if result.get("result_path") else [],
        logs=result.get("logs", ""),
    )
    if algo_id:
        session.add(run)
        await session.commit()
        await session.refresh(run)
        result["run_id"] = run.id
    return result


# ── 代码编辑器（看源码 / 调试 / 改版 / 历史 / 删除）──────────────────────────────
# Custom (user / AI) algorithms are edited in place: every save re-runs the code
# in the sandbox on the server and only then becomes a new version. Built-ins are
# read-only here (they run in-process, outside the sandbox); "copy as my
# algorithm" turns one into a sandboxed custom algorithm the user can edit.


class ForkReq(BaseModel):
    slug: str


@router.get("/builtin-source/{slug}")
async def builtin_source(slug: str, user: User = Depends(current_user)):
    try:
        return algo_store.builtin_source(slug)
    except KeyError:
        raise HTTPException(404, "builtin algorithm not found")


@router.post("/fork-builtin")
async def fork_builtin(body: ForkReq, user: User = Depends(current_user)):
    """Code for a new custom algorithm copied from a built-in. Nothing is saved
    yet — the editor opens it in "new" mode and saving goes through /save."""
    try:
        return {"code": algo_store.fork_code(body.slug)}
    except KeyError:
        raise HTTPException(404, "builtin algorithm not found")


async def _readable_algo(session: AsyncSession, algo_id: int, user: User) -> Algorithm:
    row = await session.get(Algorithm, algo_id)
    if row is None or (row.owner_id != user.id and not row.is_public):
        raise HTTPException(404, "algorithm not found")
    return row


async def _owned_algo(session: AsyncSession, algo_id: int, user: User) -> Algorithm:
    row = await session.get(Algorithm, algo_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(404, "algorithm not found (or not yours to edit)")
    return row


@router.get("/{algo_id}/source")
async def algorithm_source(algo_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    row = await _readable_algo(session, algo_id, user)
    return {
        "id": row.id, "slug": row.slug, "name": row.name, "category": row.category,
        "description": row.description, "source": row.source, "code": row.code or "",
        "params_schema": row.params_schema or {}, "version": row.version or 1,
        "verified": bool(row.is_verified), "test_report": row.test_report or {},
        "editable": row.owner_id == user.id,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/{algo_id}/versions")
async def algorithm_versions(algo_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    row = await _readable_algo(session, algo_id, user)
    return [
        {
            "version": v.version, "name": v.name, "note": v.note, "code": v.code,
            "verified": bool(v.is_verified), "current": v.version == row.version,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in await algo_store.list_versions(session, row.id)
    ]


class UpdateAlgoReq(BaseModel):
    code: str
    note: str = ""
    dataset_id: Optional[int] = None          # data for the save-time sandbox run
    params: Dict[str, Any] = Field(default_factory=dict)


@router.put("/{algo_id}")
async def update_algorithm(
    algo_id: int,
    body: UpdateAlgoReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Save edited code as a NEW VERSION of the same algorithm. Gate: static
    validation → META parses → sandbox run passes on the server. A failing gate
    returns ok=false with the details (nothing saved) so the editor can show the
    problems inline."""
    row = await _owned_algo(session, algo_id, user)
    validation = validate_algorithm_code(body.code)
    vdict = {"ok": validation.ok, "errors": validation.errors, "imports": validation.imports,
             "has_run": validation.has_run_function, "has_meta": validation.has_meta}
    if not validation.ok:
        return {"ok": False, "stage": "validation", "validation": vdict}
    try:
        meta = parse_meta(body.code)
    except Exception as e:
        return {"ok": False, "stage": "meta", "validation": vdict, "error": str(e)}
    execution = await _verify_in_sandbox(session, user, body.code, body.dataset_id, body.params)
    if execution["status"] != "ok":
        return {"ok": False, "stage": "sandbox", "validation": vdict, "execution": execution}

    try:
        old_meta = parse_meta(row.code or "")
    except Exception:
        old_meta = {}
    await algo_store.ensure_history(session, row, user.id)
    row.code = body.code
    # Name / description / params were possibly curated in the save dialog —
    # only take META's value for a field the user actually changed in the code.
    for meta_key, attr in (("name", "name"), ("description", "description"), ("category", "category"),
                           ("params_schema", "params_schema"), ("returns", "returns")):
        if meta.get(meta_key) is not None and meta.get(meta_key) != old_meta.get(meta_key):
            setattr(row, attr, meta[meta_key])
    row.is_verified = True
    row.test_report = {"all_tests_passed": True, "tests": [execution], "dataset_id": body.dataset_id}
    row.version = (row.version or 1) + 1
    algo_store.snapshot(session, row, note=body.note or "编辑器保存", user_id=user.id)
    await session.commit()
    await session.refresh(row)
    slug_note = ""
    if meta.get("slug") and meta["slug"] != row.slug:
        slug_note = f"META.slug 改成了 '{meta['slug']}'，但已保存的算法标识保持 '{row.slug}'（流程和对话按它引用）。"
    return {"ok": True, "algorithm": _summary(row), "version": row.version,
            "execution": execution, "validation": vdict, "note": slug_note}


@router.delete("/{algo_id}")
async def delete_algorithm(algo_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    row = await _owned_algo(session, algo_id, user)
    await algo_store.delete_algorithm(session, row)
    await session.commit()
    return {"ok": True}


# ── 算法共创对话（AI 生成 / 上传代码 → 对话式修改）──────────────────────────────
# One endpoint drives the "chat with AI to write / adjust an algorithm" studio.
# Each turn the planner decides: ask ONE clarifying question (with clickable
# options), write / modify the code (streaming the build stages), or just answer
# a question about the code. Modifications always start from the code currently
# in the editor — including the user's own manual edits.

STUDIO_PLANNER = """你是数据分析平台里的「算法共创助手」，和用户对话来编写/修改一个 Python 算法（平台规范：顶级 META 字典 + run(df, **params)，在沙箱运行）。
根据对话历史和当前代码，决定这一轮做什么，只输出一个 JSON 对象：

1. 需求含糊、不同理解会写出完全不同的算法时（例如只说「一元二次方程」：求根？按数据拟合 y=ax²+bx+c？画曲线？），先问一个问题：
   {"action": "ask", "question": "一句话的问题", "options": ["2-4 个可直接点选的简短选项"]}
   - 只在【还没有代码】且确实含糊时问；已有代码时按最合理的理解直接改。
   - 上一条 AI 消息已经是提问时，不要再连续追问，按用户回答直接写。
2. 写新代码或修改当前代码：
   {"action": "code", "reply": "一两句话告诉用户这次要做/改什么", "spec": "给代码生成器的完整、精确的需求说明：要做什么、输入哪些列/参数、输出什么；如果是修改，写清楚改哪里、其余保持不变"}
3. 用户只是在问代码相关的问题、不需要改代码（如「这个参数是什么意思」）：
   {"action": "answer", "reply": "直接回答"}
用中文回复用户。"""


class StudioMsg(BaseModel):
    role: str          # "user" | "assistant"
    content: str


class StudioReq(BaseModel):
    messages: List[StudioMsg]
    code: str = ""                       # what's in the editor right now (may be hand-edited)
    dataset_id: Optional[int] = None     # helps the model use real column names
    last_error: str = ""                 # latest debug-run error, if the user wants it fixed
    # "fix" = admission fix after an upload: no planning / clarifying question,
    # rewrite the current code to meet the platform rules (the last user message
    # lists the failed checks).
    mode: str = ""


@router.post("/studio")
async def algorithm_studio(
    body: StudioReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """SSE stream of: plan → (ask | answer | progress… → result) | error."""
    import asyncio
    import re as _re

    from fastapi.responses import StreamingResponse

    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")
    schema_hint = None
    if body.dataset_id is not None:
        ds = (await session.execute(
            select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
        )).scalar_one_or_none()
        if ds:
            schema_hint = str(ds.schema_json)[:4000]

    def sse(obj: Dict[str, Any]) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n"

    async def stream():
        yield ": studio-open\n\n"
        history = [{"role": m.role if m.role in ("user", "assistant") else "user", "content": m.content[:4000]}
                   for m in body.messages[-16:]]
        ctx = (f"当前编辑器里的代码：\n```python\n{body.code[:12000]}\n```" if body.code.strip() else "当前还没有代码。")
        if body.last_error.strip():
            ctx += f"\n\n最近一次调试运行的报错：\n{body.last_error.strip()[:2000]}"
        if schema_hint:
            ctx += f"\n\n用户选的参考数据集结构：{schema_hint[:2000]}"
        if body.mode == "fix" and body.code.strip():
            plan = {"action": "code", "reply": "开始按平台接入规范修改代码，原有计算逻辑保持不变。",
                    "spec": "Make this module conform to the platform algorithm contract — a top-level literal META dict "
                            "(name, slug, category, description, params_schema declaring every run() parameter, returns), "
                            "a top-level run(df, **params) entry, only sandbox-allowed imports (numpy / pandas / scipy / "
                            "sklearn / stdlib math-like modules; no os / sys / argparse / network / file IO), and 1-3 "
                            "test_cases. PRESERVE the original computation exactly. Failed checks: "
                            + (history[-1]["content"] if history else "")}
        else:
            try:
                raw = await llm.chat(
                    [{"role": "system", "content": STUDIO_PLANNER + "\n\n" + ctx}, *history],
                    temperature=0.2, max_tokens=900, json_mode=True,
                )
                m = _re.search(r"\{.*\}", raw, _re.DOTALL)
                plan = json.loads(m.group(0)) if m else {}
            except Exception as e:  # noqa: BLE001
                yield sse({"kind": "error", "message": f"AI 调用失败：{type(e).__name__}: {e}"})
                return
        action = plan.get("action")
        if action == "ask" and not body.code.strip():
            opts = [str(o)[:40] for o in (plan.get("options") or []) if str(o).strip()][:4]
            yield sse({"kind": "ask", "question": str(plan.get("question") or "能再具体说说想要什么吗？"), "options": opts})
            return
        if action == "answer":
            yield sse({"kind": "answer", "reply": str(plan.get("reply") or "")})
            return

        spec = str(plan.get("spec") or (history[-1]["content"] if history else "")).strip()
        yield sse({"kind": "plan", "reply": str(plan.get("reply") or "")})
        if body.code.strip():
            prompt = (
                "Here is the CURRENT algorithm module (the user may have edited it by hand — keep their edits). "
                "Rewrite it to satisfy the change request, KEEPING everything else unchanged. Any new option must be a "
                "real run() parameter declared in META params_schema AND used in run().\n\n"
                f"Current code:\n```python\n{body.code[:12000]}\n```\n\n"
                f"Change request: {spec}\n"
                + (f"\nThe latest debug run failed with:\n{body.last_error.strip()[:2000]}\nFix that too.\n"
                   if body.last_error.strip() else "")
                + "\nReturn the complete module (META + run + test_cases)."
            )
        else:
            prompt = spec

        stages: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(generate_algorithm(prompt, llm=llm, schema_hint=schema_hint, on_progress=stages.put_nowait))
        try:
            while not task.done() or not stages.empty():
                try:
                    ev = await asyncio.wait_for(stages.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                yield sse({"kind": "progress", **ev})
            bundle = task.result()
        except Exception as e:  # noqa: BLE001
            yield sse({"kind": "error", "message": f"生成失败：{type(e).__name__}: {e}"})
            return
        finally:
            if not task.done():
                task.cancel()
        yield sse({
            "kind": "result", "code": bundle.get("code") or "", "meta": bundle.get("meta") or {},
            "tests": bundle.get("tests") or [], "all_tests_passed": bool(bundle.get("all_tests_passed")),
            "attempts": int(bundle.get("attempts") or 1), "final_error": bundle.get("final_error") or "",
        })

    from .chat import SSE_HEADERS
    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


class MetaReq(BaseModel):
    code: str


@router.post("/meta")
async def read_meta(body: MetaReq, user: User = Depends(current_user)):
    """META of a code draft, read statically (never executed) — lets the editor
    build the run-settings form (params, required, column pickers) as you type."""
    try:
        return {"ok": True, "meta": algo_store.static_meta(body.code)}
    except ValueError as e:
        return {"ok": False, "error": str(e), "meta": {}}
