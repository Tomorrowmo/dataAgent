"""Result files by id (owner-checked). Replaces the old path-based
/api/result-file, /api/datasets/export and /api/datasets/preview-file."""
from __future__ import annotations

import io
import json
import re

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import quote

from ..db.models import User
from ..services import artifacts as artifact_svc
from ..services.storage import PathNotOwned
from .deps import current_user, get_db

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _read_table(path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path)
    except Exception:
        try:
            return pd.read_csv(path)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"could not read result file: {type(e).__name__}")


def dataframe_download(df: pd.DataFrame, stem: str, fmt: str) -> Response:
    """CSV (UTF-8 BOM so Excel opens Chinese correctly) or Excel download."""
    safe = re.sub(r'[\\/:*?"<>|\r\n]+', "_", stem).strip() or "result"
    if fmt == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        body, media, ext = buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    else:
        body, media, ext = df.to_csv(index=False).encode("utf-8-sig"), "text/csv; charset=utf-8", "csv"
    fname = f"{safe}.{ext}"
    return Response(body, media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"result.{ext}\"; filename*=UTF-8''{quote(fname)}",
    })


async def _owned_file(session: AsyncSession, artifact_id: int, user: User):
    a = await artifact_svc.get_owned(session, artifact_id, user.id)
    if a is None:
        raise HTTPException(404, "result not found")
    if a.state != "active":
        raise HTTPException(410, "result data has been cleaned up")
    try:
        p = artifact_svc.file_of(a)
    except PathNotOwned:
        raise HTTPException(404, "result not found")
    if not p.exists():
        raise HTTPException(410, "result file is no longer available")
    return a, p


@router.get("/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: int,
    limit: int = 500,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    _, p = await _owned_file(session, artifact_id, user)
    df = _read_table(p)
    n = max(1, min(int(limit), 2000))
    head = df.head(n)
    return {
        "columns": list(map(str, df.columns)),
        "rows": json.loads(head.to_json(orient="records", date_format="iso")),
        "total": int(len(df)),
        "shown": int(len(head)),
    }


@router.get("/{artifact_id}/export")
async def export_artifact(
    artifact_id: int,
    format: str = "csv",
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    a, p = await _owned_file(session, artifact_id, user)
    return dataframe_download(_read_table(p), f"result_{a.id}", format)
