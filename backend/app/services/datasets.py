"""Dataset ingestion: accept upload, detect format, persist as parquet, record metadata."""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import Conversation, Dataset


def _read_any(src_path: Path) -> Tuple[pd.DataFrame, str]:
    ext = src_path.suffix.lower().lstrip(".")
    if ext in ("csv", "tsv"):
        sep = "\t" if ext == "tsv" else ","
        df = pd.read_csv(src_path, sep=sep)
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(src_path)
    elif ext == "parquet":
        df = pd.read_parquet(src_path)
    elif ext == "json":
        df = pd.read_json(src_path)
    else:
        # last-resort: try CSV
        df = pd.read_csv(src_path)
        ext = "csv"
    return df, ext


def _safe_name(s: str) -> str:
    out = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in str(s)).strip()
    return out.replace(" ", "_") or "data"


async def _persist_dataset(
    session: AsyncSession,
    *,
    owner_id: int,
    df: pd.DataFrame,
    name: str,
    filename: str,
    file_format: str,
    description: str,
    idx: int = 0,
    kind: str = "source",
    derived_from: Optional[int] = None,
    lineage: Optional[Dict[str, Any]] = None,
) -> Dataset:
    """Write one DataFrame as parquet + a Dataset row (no commit — the caller
    commits once after all sheets, so a multi-sheet import is atomic)."""
    settings = get_settings()
    user_dir = settings.upload_path / f"user_{owner_id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    out_path = user_dir / f"{_safe_name(name)}_{int(time.time() * 1000)}_{idx}.parquet"
    df.to_parquet(out_path, index=False)

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
        name=name,
        description=description,
        filename=filename,
        storage_path=str(out_path),
        file_format=file_format,
        rows=int(len(df)),
        columns=int(df.shape[1]),
        size_bytes=int(out_path.stat().st_size),
        schema_json=schema,
        kind=kind,
        derived_from=derived_from,
        lineage=lineage or {},
    )
    session.add(ds)
    await session.flush()
    return ds


async def ingest_upload(
    session: AsyncSession,
    *,
    owner_id: int,
    src_path: Path,
    original_filename: str,
    display_name: Optional[str] = None,
    description: str = "",
) -> List[Dataset]:
    """Ingest an upload into one or more Datasets. A multi-sheet Excel becomes
    ONE dataset PER non-empty worksheet (named '<file> · <sheet>'), so nothing
    is silently dropped — pairs with multi-dataset analysis/comparison."""
    ext = src_path.suffix.lower().lstrip(".")
    stem = display_name or Path(original_filename).stem
    out: List[Dataset] = []

    if ext in ("xlsx", "xls"):
        xl = pd.ExcelFile(src_path)
        sheets = xl.sheet_names
        for i, sn in enumerate(sheets):
            df = pd.read_excel(xl, sheet_name=sn)
            df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
            if df.empty or df.shape[1] == 0:
                continue  # skip blank sheets
            name = f"{stem} · {sn}" if len(sheets) > 1 else stem
            out.append(await _persist_dataset(
                session, owner_id=owner_id, df=df, name=name,
                filename=original_filename, file_format=ext, description=description, idx=i,
            ))
        if not out:
            raise ValueError("Excel 文件没有可用的工作表数据（所有工作表都为空）")
    else:
        df, fmt = _read_any(src_path)
        out.append(await _persist_dataset(
            session, owner_id=owner_id, df=df, name=stem,
            filename=original_filename, file_format=fmt, description=description,
        ))

    await session.commit()
    for ds in out:
        await session.refresh(ds)

    try:
        src_path.unlink(missing_ok=True)
    except Exception:
        pass

    return out


# Mesh / field formats read via VTK (pyvista) → points+fields tables. CGNS may
# be ADF or HDF5; VTK handles both (meshio/h5py only read HDF5-CGNS, hence the
# garbage when the generic AI-parser tried to struct-unpack the binary).
MESH_EXTS = {".cgns", ".vtk", ".vtu", ".vtp", ".vtm", ".stl", ".ply", ".obj"}


def _mesh_to_frames(src_path: Path) -> List[Tuple[str, pd.DataFrame]]:
    """Read a mesh/field file and project each zone to a POINTS+FIELDS table:
    one row per mesh point, columns = X,Y,Z + every point field (vector fields
    expanded to _x/_y/_z). Multi-zone files yield one frame per zone.

    pyvista/VTK is imported LAZILY so it never enters the backend's startup
    import path (VTK is heavy)."""
    import numpy as np
    import pyvista as pv  # noqa: lazy heavy import

    data = pv.read(str(src_path))
    blocks: List[Tuple[str, Any]] = []

    def collect(m: Any, name: str) -> None:
        if hasattr(m, "n_blocks"):  # MultiBlock (CGNS base/zone tree)
            for i in range(m.n_blocks):
                try:
                    nm = m.get_block_name(i) or f"{name}/{i}"
                except Exception:
                    nm = f"{name}/{i}"
                b = m[i]
                if b is not None:
                    collect(b, nm)
        elif int(getattr(m, "n_points", 0) or 0) > 0:
            blocks.append((name, m))

    collect(data, src_path.stem)

    frames: List[Tuple[str, pd.DataFrame]] = []
    for zname, m in blocks:
        cols: Dict[str, Any] = {}
        pts = np.asarray(m.points)
        if pts.ndim == 2 and pts.shape[1] >= 3:
            cols["X"], cols["Y"], cols["Z"] = pts[:, 0], pts[:, 1], pts[:, 2]
        for k in list(m.point_data.keys()):
            arr = np.asarray(m.point_data[k])
            if arr.ndim == 1:
                cols[k] = arr
            elif arr.ndim == 2:
                n = arr.shape[1]
                suff = ["x", "y", "z"] if n == 3 else [str(j) for j in range(n)]
                for j in range(min(n, 9)):
                    cols[f"{k}_{suff[j]}"] = arr[:, j]
        if cols:
            frames.append((zname.split("/")[-1], pd.DataFrame(cols)))
    return frames


async def ingest_mesh_upload(
    session: AsyncSession,
    *,
    owner_id: int,
    src_path: Path,
    original_filename: str,
    display_name: Optional[str] = None,
    description: str = "",
) -> List[Dataset]:
    """Ingest a CGNS/VTK/STL mesh file as one dataset PER zone (a points+fields
    table), so the solution fields become analyzable / chartable / exportable."""
    stem = display_name or Path(original_filename).stem
    frames = _mesh_to_frames(src_path)
    if not frames:
        raise ValueError("没有从这个网格文件里读到任何带点数据的 zone")
    out: List[Dataset] = []
    multi = len(frames) > 1
    ext = Path(original_filename).suffix.lstrip(".").lower() or "mesh"
    for i, (zname, df) in enumerate(frames):
        name = f"{stem} · {zname}" if multi else stem
        out.append(await _persist_dataset(
            session, owner_id=owner_id, df=df, name=name,
            filename=original_filename, file_format=ext, idx=i,
            description=description or f"网格/场数据:每行一个网格点,列为坐标 + 各物理场(来自 .{ext},经 VTK 读取)",
        ))
    await session.commit()
    for d in out:
        await session.refresh(d)
    try:
        src_path.unlink(missing_ok=True)
    except Exception:
        pass
    return out


def load_dataset_df(ds: Dataset) -> pd.DataFrame:
    path = Path(ds.storage_path)
    if not path.exists():
        raise FileNotFoundError(f"dataset file missing: {path}")
    return pd.read_parquet(path)


def _safe_head(df: pd.DataFrame, n: int) -> Any:
    try:
        return df.head(n).to_dict(orient="records")
    except Exception:
        return [{c: str(df.iloc[i][c]) for c in df.columns} for i in range(min(n, len(df)))]


async def gc_derived_datasets(
    session: AsyncSession,
    *,
    owner_id: int,
    grace_minutes: int = 120,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Reclaim un-kept derived (intermediate) datasets so pipelines don't bury
    the library in by-products.

    A derived dataset is SWEPT only when ALL of these hold — the policy errs
    hard toward never deleting something the user might still want:
      • kind == 'derived'  (sources are never touched)
      • kept == False      (the user didn't pin it; pinned ones stay in the tree)
      • it is NOT an ancestor of any kept / promoted dataset
        (so a kept leaf keeps its full lineage breadcrumb)
      • it is NOT the live head of any conversation's cross-turn pipeline
      • it was created more than `grace_minutes` ago (active work is safe)

    Deleting a row also removes its parquet on disk. Returns a summary; with
    `dry_run=True` nothing is deleted (used to preview the count in the UI)."""
    rows = (await session.execute(
        select(Dataset).where(Dataset.owner_id == owner_id)
    )).scalars().all()
    by_id = {d.id: d for d in rows}

    # Protect the ancestry of everything the user signalled they want to keep:
    # pinned derived datasets, and derived datasets that were promoted to source
    # (kind=='source' but with a derived_from parent). Walk parents upward.
    protected: set[int] = set()
    seeds = [d for d in rows if d.kept or (d.kind == "source" and d.derived_from is not None)]
    for seed in seeds:
        cur = seed.derived_from
        guard = 0
        while cur is not None and cur in by_id and cur not in protected and guard < 1000:
            protected.add(cur)
            cur = by_id[cur].derived_from
            guard += 1

    # Protect live pipeline heads — a chain a conversation is mid-way through.
    convs = (await session.execute(
        select(Conversation).where(Conversation.owner_id == owner_id)
    )).scalars().all()
    for c in convs:
        for entry in (c.pipeline_state or {}).values():
            hid = (entry or {}).get("head_id")
            if isinstance(hid, int):
                protected.add(hid)

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)

    def _created(d: Dataset) -> datetime:
        ts = d.created_at
        if ts is None:
            return datetime.now(timezone.utc)
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    victims = [
        d for d in rows
        if d.kind == "derived" and not d.kept
        and d.id not in protected
        and _created(d) < cutoff
    ]

    freed = 0
    deleted: List[Dict[str, Any]] = []
    for d in victims:
        freed += int(d.size_bytes or 0)
        deleted.append({"id": d.id, "name": d.name})
        if not dry_run:
            try:
                p = Path(d.storage_path)
                if p.exists():
                    p.unlink()
            except Exception:
                pass  # orphaned parquet is harmless; the row is what matters
            await session.delete(d)
    if not dry_run and deleted:
        await session.commit()

    return {
        "deleted": deleted,
        "count": len(deleted),
        "freed_bytes": freed,
        "dry_run": dry_run,
        "grace_minutes": grace_minutes,
    }


def save_temp_upload(file_bytes: bytes, filename: str) -> Path:
    settings = get_settings()
    tmp_dir = settings.upload_path / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = filename.replace("/", "_").replace("\\", "_")
    out = tmp_dir / f"{int(time.time() * 1000)}_{safe_name}"
    out.write_bytes(file_bytes)
    return out
