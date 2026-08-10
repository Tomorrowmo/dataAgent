import io
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import Dataset, FormatAdapter, User
from ..services.datasets import MESH_EXTS, _persist_dataset, build_profile, delete_dataset_tree, gc_derived_datasets, ingest_image_upload, ingest_mesh_upload, ingest_tecplot_upload, ingest_upload, load_dataset_df, looks_like_tecplot, save_temp_upload
from ..services.image_parser import IMAGE_EXTS
from ..services.format_adapter import (
    generate_cleaner_stream, generate_parser_stream, save_adapter, stage_upload, try_saved_adapter,
)
from .deps import current_user, get_db, llm_for

router = APIRouter(prefix="/datasets", tags=["datasets"])

# Keep SSE flowing token-by-token through reverse proxies / CDNs (see chat.py).
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

NATIVE_EXTS = {".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".json"}


class DatasetResp(BaseModel):
    id: int
    name: str
    description: str
    filename: str
    file_format: str
    rows: int
    columns: int
    size_bytes: int
    schema: dict
    kind: str = "source"            # source | derived
    derived_from: Optional[int] = None
    lineage: dict = Field(default_factory=dict)
    kept: bool = False              # pinned derived → survives auto-GC

    @classmethod
    def from_orm_(cls, ds: Dataset) -> "DatasetResp":
        return cls(
            id=ds.id, name=ds.name, description=ds.description, filename=ds.filename,
            file_format=ds.file_format, rows=ds.rows, columns=ds.columns,
            size_bytes=ds.size_bytes, schema=ds.schema_json or {},
            kind=getattr(ds, "kind", "source") or "source",
            derived_from=getattr(ds, "derived_from", None),
            lineage=getattr(ds, "lineage", {}) or {},
            kept=bool(getattr(ds, "kept", False)),
        )


class UploadResp(BaseModel):
    """A successful upload returns the dataset. An upload that needs a custom
    parser returns status='needs_parser' instead — the UI then drives the
    generate/approve flow against the staged file."""
    status: str  # "ok" | "needs_parser"
    dataset: Optional[DatasetResp] = None  # primary (first) — back-compat
    datasets: Optional[List[DatasetResp]] = None  # all (a multi-sheet Excel → one per sheet)
    needs_parser: Optional[Dict[str, Any]] = None  # {staging_path, extension, filename}


@router.post("", response_model=UploadResp)
async def upload(
    file: UploadFile = File(...),
    name: Optional[str] = Form(default=None),
    description: str = Form(default=""),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "filename required")
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(413, "file too large (max 200 MiB)")

    extension = Path(file.filename).suffix.lower()

    # Path 0 — a mesh / field file (CGNS / VTK / STL …). Read it via VTK into one
    # points+fields table per zone. Bypasses the AI-parser, which can't parse the
    # binary mesh format (it produced garbage zeros before).
    if extension in MESH_EXTS:
        tmp = save_temp_upload(data, file.filename)
        try:
            dss = await ingest_mesh_upload(
                session, owner_id=user.id, src_path=tmp,
                original_filename=file.filename, display_name=name, description=description,
            )
            resp = [DatasetResp.from_orm_(d) for d in dss]
            return UploadResp(status="ok", dataset=resp[0], datasets=resp)
        except Exception as e:
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
            raise HTTPException(400, f"网格文件解析失败({type(e).__name__}): {e}")

    # Path 0.3 — an image of a table (screenshot, phone photo, chart with
    # embedded grid). Vision LLM extracts CSV, we persist that as a normal
    # Dataset. Sits before Tecplot / native so a mis-named .png doesn't
    # cascade through pandas-tries-CSV loops.
    if extension in IMAGE_EXTS:
        llm = llm_for(user)
        if not llm.is_configured:
            raise HTTPException(
                400,
                "Reading images needs an LLM key. Set a vision-capable model "
                "(e.g. qwen-vl-max on dashscope) in Settings.",
            )
        try:
            dss = await ingest_image_upload(
                session, owner_id=user.id, image_bytes=data,
                extension=extension, original_filename=file.filename,
                llm=llm, display_name=name, description=description,
            )
            resp = [DatasetResp.from_orm_(d) for d in dss]
            return UploadResp(status="ok", dataset=resp[0], datasets=resp)
        except Exception as e:
            raise HTTPException(400, f"图片解析失败({type(e).__name__}): {e}")

    # Path 0.5 — a Tecplot ASCII export (CFD/CAE probe data). Detected by content
    # (VARIABLES + ZONE), so it works for .dat / .tec / no-extension. Parsed
    # natively into one tidy table; the generic AI parser can't reliably handle
    # BLOCK packing + many zones. On any parse failure we fall through to the AI
    # parser path as a backstop.
    if looks_like_tecplot(data):
        tmp = save_temp_upload(data, file.filename)
        try:
            dss = await ingest_tecplot_upload(
                session, owner_id=user.id, src_path=tmp,
                original_filename=file.filename, display_name=name, description=description,
            )
            resp = [DatasetResp.from_orm_(d) for d in dss]
            return UploadResp(status="ok", dataset=resp[0], datasets=resp)
        except Exception:
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
            # fall through — let the native/adapter/AI paths try.

    # Path 1 — extension we know natively. Try the usual pandas readers.
    if extension in NATIVE_EXTS:
        tmp = save_temp_upload(data, file.filename)
        try:
            dss = await ingest_upload(
                session, owner_id=user.id, src_path=tmp,
                original_filename=file.filename, display_name=name, description=description,
            )
            resp = [DatasetResp.from_orm_(d) for d in dss]
            return UploadResp(status="ok", dataset=resp[0], datasets=resp)
        except Exception:
            # Native parse failed (e.g. an `.xlsx` that's actually a weird custom
            # format). Fall through to the adapter path.
            pass

    # Path 2 — try a previously-saved adapter for this extension.
    staged_path = stage_upload(data, file.filename, owner_id=user.id)
    adapter_result = await try_saved_adapter(
        session, owner_id=user.id, extension=extension, file_path=staged_path,
    )
    if adapter_result:
        # Promote the parquet that the saved adapter wrote into a real Dataset.
        ds = await _ingest_parsed(
            session,
            owner_id=user.id,
            parsed_parquet_path=Path(adapter_result["result_path"]),
            original_filename=file.filename,
            display_name=name,
            description=description or f"Parsed via adapter '{adapter_result['adapter_name']}'",
        )
        # Tidy: drop the staged raw file now that the dataset is persisted.
        try: staged_path.unlink(missing_ok=True)
        except Exception: pass
        return UploadResp(status="ok", dataset=DatasetResp.from_orm_(ds))

    # Path 3 — neither native nor a saved adapter. Hand control back to the UI
    # so it can drive the generate/approve flow.
    return UploadResp(
        status="needs_parser",
        needs_parser={
            "staging_path": str(staged_path),
            "extension": extension or "(no extension)",
            "filename": file.filename,
            "size_bytes": len(data),
            "display_name": name,
            "description": description,
        },
    )


class GenerateParserReq(BaseModel):
    staging_path: str
    extension: str


@router.post("/generate-parser")
async def generate_parser_endpoint(
    body: GenerateParserReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Phase 2 of the unknown-format upload flow — streams step events as the
    LLM generates code, the AST validator checks it, and the sandbox runs it
    against the staged file. Auto-retries up to 3 times, feeding each failure
    back to the model so it tries a different approach. The UI subscribes to
    the SSE stream and renders a live attempt log."""
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")

    staged = _validate_staged_path(body.staging_path, user.id)

    async def event_stream():
        yield ": numetrix-stream-open\n\n"  # prime the proxy pipe (see chat.py)
        try:
            async for ev in generate_parser_stream(
                file_path=staged, extension=body.extension, llm=llm, max_attempts=3,
            ):
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception as e:
            # Defensive — any unhandled exception turns into a final 'fatal'
            # event so the UI un-sticks instead of hanging on a dead stream.
            yield f"data: {json.dumps({'event': 'fatal', 'error': f'{type(e).__name__}: {e}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


class ApproveParserReq(BaseModel):
    staging_path: str
    extension: str
    code: str
    meta: Dict[str, Any] = Field(default_factory=dict)
    name: Optional[str] = None
    description: str = ""


@router.post("/approve-parser", response_model=DatasetResp)
async def approve_parser_endpoint(
    body: ApproveParserReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Phase 3: user has approved the generated parser. We save it as a
    FormatAdapter (so subsequent uploads of the same extension parse silently),
    then run it one final time to produce the actual Dataset row + parquet."""
    from ..sandbox import executor as sandbox_executor

    staged = _validate_staged_path(body.staging_path, user.id)

    # Final run — produces the parquet we'll register as the Dataset.
    result = sandbox_executor.execute(
        body.code, params={}, input_df=None,
        save_result=True,
        mode="parser", parser_file=str(staged),
    )
    if result.status != "ok" or not result.result_path:
        raise HTTPException(400, f"parser failed on final run: {result.error}")

    # Save the adapter so we never have to ask again for this extension.
    await save_adapter(
        session,
        owner_id=user.id,
        extension=body.extension,
        code=body.code,
        meta=body.meta or {},
        sample_size_bytes=staged.stat().st_size,
        test_report={
            "status": result.status,
            "duration_ms": result.duration_ms,
            "result_rows": result.result_rows,
        },
    )

    # Promote the parquet into a Dataset.
    ds = await _ingest_parsed(
        session,
        owner_id=user.id,
        parsed_parquet_path=Path(result.result_path),
        original_filename=staged.name.split("_", 1)[-1],  # strip timestamp prefix
        display_name=body.name,
        description=body.description or f"Parsed via custom {body.extension} adapter",
    )

    try: staged.unlink(missing_ok=True)
    except Exception: pass

    return DatasetResp.from_orm_(ds)


@router.post("/{dataset_id}/clean")
async def clean_dataset_stream(
    dataset_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Stream an AI cleaner for a messy dataset: the model writes run(df)->tidy_df,
    we run it in the sandbox, and stream step events (live code, validate, run,
    preview). The UI reuses the parser modal's live-code view."""
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")
    df = load_dataset_df(ds)

    async def event_stream():
        yield ": numetrix-stream-open\n\n"  # prime the proxy pipe (see chat.py)
        try:
            async for ev in generate_cleaner_stream(df=df, llm=llm, max_attempts=2):
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'fatal', 'error': f'{type(e).__name__}: {e}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


class CleanApproveReq(BaseModel):
    dataset_id: int
    code: str
    name: Optional[str] = None


@router.post("/clean-approve", response_model=DatasetResp)
async def clean_approve(
    body: CleanApproveReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """User approved the AI cleaner → run it once more and register the tidy
    result as a NEW dataset. The messy original is left untouched."""
    from ..sandbox import executor as sandbox_executor

    ds = (await session.execute(
        select(Dataset).where(Dataset.id == body.dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    df = load_dataset_df(ds)
    result = sandbox_executor.execute(body.code, params={}, input_df=df, save_result=True, mode="algorithm")
    if result.status != "ok" or not result.result_path:
        raise HTTPException(400, f"cleaner failed on final run: {result.error}")

    new_ds = await _ingest_parsed(
        session,
        owner_id=user.id,
        parsed_parquet_path=Path(result.result_path),
        original_filename=(body.name or f"{ds.name}_clean") + ".parquet",
        display_name=body.name or f"{ds.name}（整理）",
        description=f"AI 整理自「{ds.name}」",
    )
    return DatasetResp.from_orm_(new_ds)


class AdapterResp(BaseModel):
    id: int
    extension: str
    name: str
    description: str
    is_verified: bool
    sample_size_bytes: int


@router.get("/adapters", response_model=List[AdapterResp])
async def list_adapters(user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(
        select(FormatAdapter).where(FormatAdapter.owner_id == user.id).order_by(FormatAdapter.id.desc())
    )).scalars().all()
    return [
        AdapterResp(id=a.id, extension=a.extension, name=a.name, description=a.description,
                    is_verified=a.is_verified, sample_size_bytes=a.sample_size_bytes)
        for a in rows
    ]


@router.delete("/adapters/{adapter_id}")
async def delete_adapter(
    adapter_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    row = (await session.execute(
        select(FormatAdapter).where(FormatAdapter.id == adapter_id, FormatAdapter.owner_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "adapter not found")
    await session.delete(row)
    await session.commit()
    return {"ok": True}


def _validate_staged_path(path_str: str, owner_id: int) -> Path:
    """Reject any path outside the user's staging dir — defense against
    path-traversal via the staging_path body field."""
    settings = get_settings()
    target = Path(path_str).resolve()
    staging_root = (settings.upload_path / f"user_{owner_id}" / "staging").resolve()
    try:
        target.relative_to(staging_root)
    except ValueError:
        raise HTTPException(400, "staging_path is outside your user dir")
    if not target.exists():
        raise HTTPException(404, "staged file no longer exists")
    return target


async def _ingest_parsed(
    session: AsyncSession,
    *,
    owner_id: int,
    parsed_parquet_path: Path,
    original_filename: str,
    display_name: Optional[str],
    description: str,
) -> Dataset:
    """Promote a parquet produced by a parser run into a Dataset record."""
    import time
    settings = get_settings()
    user_dir = settings.upload_path / f"user_{owner_id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(original_filename).stem.replace(" ", "_")
    final = user_dir / f"{stem}_{int(time.time() * 1000)}.parquet"
    shutil.copy(parsed_parquet_path, final)

    df = pd.read_parquet(final)
    schema = {
        "columns": [
            {
                "name": str(c),
                "dtype": str(df[c].dtype),
                "n_unique": int(df[c].nunique(dropna=True)),
                "n_missing": int(df[c].isna().sum()),
            }
            for c in df.columns
        ],
        "head": _safe_head(df, 10),
    }

    ds = Dataset(
        owner_id=owner_id,
        name=display_name or stem,
        description=description,
        filename=original_filename,
        storage_path=str(final),
        file_format=Path(original_filename).suffix.lstrip(".").lower() or "custom",
        rows=int(len(df)),
        columns=int(df.shape[1]),
        size_bytes=int(final.stat().st_size),
        schema_json=schema,
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return ds


def _safe_head(df: pd.DataFrame, n: int) -> Any:
    try:
        return df.head(n).to_dict(orient="records")
    except Exception:
        return [{c: str(df.iloc[i][c]) for c in df.columns} for i in range(min(n, len(df)))]


@router.get("", response_model=List[DatasetResp])
async def list_datasets(user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(
        select(Dataset).where(Dataset.owner_id == user.id).order_by(Dataset.id.desc())
    )).scalars().all()
    return [DatasetResp.from_orm_(d) for d in rows]


@router.post("/{dataset_id}/promote", response_model=DatasetResp)
async def promote_dataset(dataset_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    """Keep a derived/intermediate dataset — promote it to a first-class source
    dataset so it stops being hidden as a pipeline by-product."""
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    ds.kind = "source"
    ds.kept = True  # promoting also pins it (belt-and-suspenders vs. GC)
    await session.commit()
    await session.refresh(ds)
    return DatasetResp.from_orm_(ds)


class KeepReq(BaseModel):
    kept: bool = True


@router.post("/{dataset_id}/keep", response_model=DatasetResp)
async def keep_dataset(
    dataset_id: int,
    body: KeepReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Pin / unpin a derived dataset IN PLACE so it survives auto-GC without
    being promoted to a source (which would lose its position in the lineage
    tree). This is the lightweight 'keep this intermediate' the GC respects."""
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    ds.kept = bool(body.kept)
    await session.commit()
    await session.refresh(ds)
    return DatasetResp.from_orm_(ds)


@router.post("/gc")
async def gc_datasets(
    dry_run: bool = False,
    grace_minutes: int = 120,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Reclaim un-kept intermediate datasets. `dry_run=true` previews the count
    without deleting (used to label the 清理 button)."""
    return await gc_derived_datasets(
        session, owner_id=user.id, grace_minutes=max(0, grace_minutes), dry_run=dry_run,
    )


@router.get("/export")
async def export_result(path: str, format: str = "csv"):
    """Convert a result/dataset parquet to a FAMILIAR format (CSV or Excel) and
    serve it as a download — most users don't know what .parquet is. Auth-less
    (like /api/result-file) but the path must live under the upload dir."""
    settings = get_settings()
    target = Path(path).resolve()
    try:
        target.relative_to(settings.upload_path.resolve())
    except ValueError:
        raise HTTPException(400, "path not under upload directory")
    if not target.exists():
        raise HTTPException(404, "file not found")
    try:
        df = pd.read_parquet(target)
    except Exception:
        try:
            df = pd.read_csv(target)
        except Exception as e:
            raise HTTPException(400, f"could not read result file: {e}")

    stem = target.stem
    if format == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        return Response(
            buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{stem}.xlsx"'},
        )
    # CSV with BOM so Excel opens Chinese correctly.
    return Response(
        df.to_csv(index=False).encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
    )


@router.get("/preview-file")
async def preview_file(path: str, limit: int = 500):
    """Preview rows from a result parquet/CSV that ISN'T a registered dataset yet
    (e.g. a one-off single-algorithm run output) so it can be visualized directly.
    Path must live under the upload dir (same guard as /export). Auth-less like
    /export and /result-file."""
    settings = get_settings()
    target = Path(path).resolve()
    try:
        target.relative_to(settings.upload_path.resolve())
    except ValueError:
        raise HTTPException(400, "path not under upload directory")
    if not target.exists():
        raise HTTPException(404, "file not found")
    try:
        df = pd.read_parquet(target)
    except Exception:
        try:
            df = pd.read_csv(target)
        except Exception as e:
            raise HTTPException(400, f"could not read result file: {e}")
    n = max(1, min(int(limit), 2000))
    head = df.head(n)
    return {
        "columns": list(map(str, df.columns)),
        "rows": json.loads(head.to_json(orient="records", date_format="iso")),
        "total": int(len(df)),
        "shown": int(len(head)),
    }


@router.get("/{dataset_id}/preview")
async def dataset_preview(
    dataset_id: int,
    limit: int = 50,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Read the first `limit` rows from the dataset's parquet (capped). The
    stored schema head is only 10 rows; this fetches more on demand."""
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    df = load_dataset_df(ds)
    n = max(1, min(int(limit), 500))
    head = df.head(n)
    return {
        "columns": list(map(str, df.columns)),
        "rows": json.loads(head.to_json(orient="records", date_format="iso")),
        "total": int(len(df)),
        "shown": int(len(head)),
    }


def _down_idx(n: int, max_points: int):
    """Deterministic downsample index so /points3d and /column line up."""
    import numpy as np
    mx = max(1000, min(int(max_points), 300000))
    return np.linspace(0, n - 1, mx).astype(int) if n > mx else None


@router.get("/{dataset_id}/points3d")
async def dataset_points3d(
    dataset_id: int,
    color: Optional[str] = None,
    max_points: int = 80000,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Geometry for the 3D point-cloud viewer: downsampled X/Y/Z + the chosen
    field's values + the list of plottable fields. Only for datasets that carry
    X/Y/Z coordinate columns (mesh / CGNS imports)."""
    import numpy as np
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    df = load_dataset_df(ds)
    cols = [str(c) for c in df.columns]
    low = {c.lower(): c for c in cols}
    xc, yc, zc = low.get("x"), low.get("y"), low.get("z")
    if not (xc and yc and zc):
        raise HTTPException(400, "这个数据集没有 X/Y/Z 坐标列,不是网格/点云数据")
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    fields = [c for c in numeric if c not in (xc, yc, zc)]
    cf = color if (color and color in df.columns) else (fields[0] if fields else None)
    n = int(len(df))
    idx = _down_idx(n, max_points)
    sub = df.iloc[idx] if idx is not None else df

    def coord(c):
        return [0.0 if v != v else float(v) for v in sub[c].to_numpy(dtype=float)]

    cvals = sub[cf].to_numpy(dtype=float) if cf else None
    return {
        "n": int(len(sub)), "total": n,
        "x": coord(xc), "y": coord(yc), "z": coord(zc),
        "fields": fields, "color_field": cf,
        "color": ([None if v != v else float(v) for v in cvals] if cvals is not None else None),
        "cmin": float(np.nanmin(cvals)) if cvals is not None and len(cvals) else 0.0,
        "cmax": float(np.nanmax(cvals)) if cvals is not None and len(cvals) else 1.0,
    }


@router.get("/{dataset_id}/column")
async def dataset_column(
    dataset_id: int,
    name: str,
    max_points: int = 80000,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """A single field's values (same downsample as /points3d) so the 3D view can
    re-color without re-sending coordinates."""
    import numpy as np
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    df = load_dataset_df(ds)
    if name not in df.columns:
        raise HTTPException(400, f"column not found: {name}")
    n = int(len(df))
    idx = _down_idx(n, max_points)
    vals = (df.iloc[idx][name] if idx is not None else df[name]).to_numpy(dtype=float)
    return {
        "name": name,
        "values": [None if v != v else float(v) for v in vals],
        "cmin": float(np.nanmin(vals)) if len(vals) else 0.0,
        "cmax": float(np.nanmax(vals)) if len(vals) else 1.0,
    }


class SubsetFilter(BaseModel):
    column: str
    op: str           # eq | ne | gt | ge | lt | le | contains | startswith | in
    value: Any = None


class SubsetReq(BaseModel):
    name: Optional[str] = None
    # Explicit row selection (indices into the dataset's natural row order). When
    # present, takes precedence over filters — this is the "check some rows in the
    # table and save them" path.
    row_indices: Optional[List[int]] = None
    # Otherwise: apply these filters to the FULL dataset (so the saved subset is
    # the true filtered result, not just the previewed rows), then sort/limit.
    filters: List[SubsetFilter] = Field(default_factory=list)
    sort: Optional[Dict[str, Any]] = None   # {"column": str, "desc": bool}
    limit: Optional[int] = None


def _apply_filter(df: pd.DataFrame, f: SubsetFilter) -> pd.DataFrame:
    if f.column not in df.columns:
        raise HTTPException(400, f"筛选列不存在: {f.column}")
    col = df[f.column]
    op = (f.op or "").lower()
    v = f.value
    # Coerce the comparison value to the column's type for numeric comparisons.
    if op in ("gt", "ge", "lt", "le", "eq", "ne") and pd.api.types.is_numeric_dtype(col):
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"列 {f.column} 是数值列,筛选值 '{f.value}' 不是数字")
    try:
        if op == "eq":   return df[col == v]
        if op == "ne":   return df[col != v]
        if op == "gt":   return df[col > v]
        if op == "ge":   return df[col >= v]
        if op == "lt":   return df[col < v]
        if op == "le":   return df[col <= v]
        if op == "contains":   return df[col.astype(str).str.contains(str(v), case=False, na=False)]
        if op == "startswith": return df[col.astype(str).str.startswith(str(v), na=False)]
        if op == "in":
            vals = v if isinstance(v, list) else [v]
            return df[col.isin(vals)]
    except Exception as e:
        raise HTTPException(400, f"筛选失败({f.column} {op}): {e}")
    raise HTTPException(400, f"不支持的筛选操作: {op}")


@router.post("/{dataset_id}/subset", response_model=DatasetResp)
async def save_subset(
    dataset_id: int,
    body: SubsetReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Save a SUBSET of a dataset as a new derived dataset (with lineage). Two
    modes: explicit `row_indices` (rows the user checked in the table), or
    `filters` + `sort` + `limit` applied to the FULL dataset on the server. This
    is the 排序 / 筛选 / 另存选中部分 backing the data-table view."""
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    df = load_dataset_df(ds)

    if body.row_indices is not None:
        valid = [i for i in body.row_indices if isinstance(i, int) and 0 <= i < len(df)]
        if not valid:
            raise HTTPException(400, "没有有效的选中行")
        out = df.iloc[valid].copy()
        op_label = f"选中 {len(out)} 行"
    else:
        out = df
        for f in body.filters:
            out = _apply_filter(out, f)
        if body.sort and body.sort.get("column") in out.columns:
            out = out.sort_values(body.sort["column"], ascending=not bool(body.sort.get("desc")))
        if body.limit and body.limit > 0:
            out = out.head(int(body.limit))
        out = out.copy()
        bits = [f"{f.column}{f.op}{f.value}" for f in body.filters]
        op_label = "筛选" + ("(" + ", ".join(bits)[:60] + ")" if bits else "") or "子集"

    if len(out) == 0:
        raise HTTPException(400, "筛选/选择结果为空,没有可保存的行")

    new_name = (body.name or "").strip() or f"{ds.name} · {op_label}"
    d = await _persist_dataset(
        session, owner_id=user.id, df=out,
        name=new_name, filename=f"{ds.name}_subset.parquet",
        file_format="derived", description=f"由「{ds.name}」{op_label}得到（{len(out)} 行）",
        kind="derived", derived_from=ds.id,
        lineage={"from": ds.id, "from_name": ds.name,
                 "op": {"slug": "subset", "label": op_label,
                        "params": {"filters": [f.model_dump() for f in body.filters],
                                   "sort": body.sort, "n_rows": len(out)}}},
    )
    await session.commit()
    await session.refresh(d)
    return DatasetResp.from_orm_(d)


@router.get("/{dataset_id}/profile")
async def profile_dataset_endpoint(
    dataset_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Instant, FREE first-read of a dataset (no LLM): what it roughly is, a few
    grounded facts, and concrete next actions. Shown automatically right after
    import so a user immediately knows what they can do. Every fact is computed
    from the real frame, so it can't hallucinate."""
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    df = load_dataset_df(ds)
    profile = build_profile(df, ds)

    # CONSULT the sedimented expert judgment: apply column-meaning rules the user
    # can see (own + public) to this dataset's columns. Each hit is the expert's
    # meaning handed to whoever opens the data — the read-back half of the loop.
    from ..db.models import MappingRule
    from ..services.mappings import apply_rules
    from sqlalchemy import or_
    rules = (await session.execute(
        select(MappingRule)
        .where(or_(MappingRule.owner_id == user.id, MappingRule.is_public.is_(True)))
        .order_by((MappingRule.owner_id == user.id).desc(), MappingRule.id.desc())
    )).scalars().all()
    matches = apply_rules([str(c) for c in df.columns], list(rules))
    if matches:
        by_id = {r.id: r for r in rules}
        for m in matches:
            r = by_id.get(m["rule_id"])
            if r is not None:
                r.hit_count += 1
        await session.commit()
    profile["semantic"] = matches
    return profile


@router.post("/{dataset_id}/explain")
async def explain_dataset(dataset_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    """Plain-language AI explanation of a dataset / analysis result: what it is,
    what the columns mean, and what's notable — grounded in the schema + head +
    lineage so it doesn't invent columns."""
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    llm = llm_for(user)
    if not llm.is_configured:
        raise HTTPException(400, "no LLM key configured. Set one in Settings.")
    schema = ds.schema_json or {}
    cols = schema.get("columns", []) or []
    head = (schema.get("head", []) or [])[:8]
    lineage = getattr(ds, "lineage", {}) or {}
    op = lineage.get("op") or {}
    ctx = f"数据集名:{ds.name}\n规模:{ds.rows} 行 × {ds.columns} 列\n"
    if op:
        ctx += f"来历:由「{lineage.get('from_name', '原始数据')}」经算法『{op.get('label') or op.get('slug')}』(参数 {op.get('params') or {}})得到。\n"
    ctx += "列:\n" + "\n".join(
        f"- {c.get('name')} ({c.get('dtype')}, 去重 {c.get('n_unique')}, 缺失 {c.get('n_missing')})" for c in cols[:50]
    )
    ctx += "\n前几行:\n" + json.dumps(head, ensure_ascii=False, default=str)[:2200]
    messages = [
        {"role": "system", "content": (
            "你是数据分析助手,讲给不一定懂数据的人听。用自然、口语化的中文,像同事之间聊天那样"
            "介绍这份数据:它大概是什么、里面有哪些信息、有什么值得留意的地方(比如缺失、数值范围、"
            "异常或主要结论)。"
            "要求:像说话一样自然连贯,2-4 句话即可;不要用 Markdown 的标题/加粗(**)/项目符号(-),"
            "也不要用反引号包列名,直接说列名就行。"
            "只依据给到的 schema/前几行/来历,不要编造不存在的列或数值。"
        )},
        {"role": "user", "content": ctx + "\n\n请解释这份数据。"},
    ]
    try:
        text = await llm.chat(messages, temperature=0.3, max_tokens=600)
    except Exception as e:
        raise HTTPException(500, f"解释失败: {type(e).__name__}: {e}")
    return {"explanation": (text or "").strip()}


@router.get("/{dataset_id}", response_model=DatasetResp)
async def get_dataset(dataset_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_db)):
    ds = (await session.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    )).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    return DatasetResp.from_orm_(ds)


@router.delete("/{dataset_id}")
async def delete_dataset(
    dataset_id: int,
    dry_run: bool = False,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    """Delete a dataset and its whole derived subtree (a 中间结果 without its
    parent is an orphan). `dry_run=true` returns what WOULD go, so the UI can
    warn before anything is destroyed."""
    res = await delete_dataset_tree(
        session, owner_id=user.id, dataset_id=dataset_id, dry_run=dry_run
    )
    if not res.get("found"):
        raise HTTPException(404, "dataset not found")
    return {"ok": True, **res}
