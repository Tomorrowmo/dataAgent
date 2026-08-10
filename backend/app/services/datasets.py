"""Dataset ingestion: accept upload, detect format, persist as parquet, record metadata."""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import Conversation, Dataset, FlowTemplate
from .image_parser import IMAGE_EXTS, parse_image_to_df
from .llm import LLMClient


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


async def seed_examples_for_user(session: AsyncSession, owner_id: int) -> int:
    """Give a user a standard set of example datasets + flow templates so EVERY
    account, on every environment, starts with characteristic 算例 to explore.

    Two layers, both idempotent (skip anything whose name the user already has):
      1. A code-defined baseline (services/seed_content) — generated
         deterministically, so it can never be lost to a missing bundle / a
         swapped snapshot. This is the guaranteed minimum every account gets.
      2. The richer data/seed_examples bundle if it happens to be present
         (shipped on the deployed server) — extra, not required.

    Does NOT commit; the caller commits."""
    created = await _seed_code_baseline(session, owner_id)
    created += await _seed_from_manifest(session, owner_id)
    return created


async def _seed_code_baseline(session: AsyncSession, owner_id: int) -> int:
    """Layer 1: the in-code, always-available curated set (datasets + templates)."""
    from .seed_content import SEED_DATASETS, SEED_TEMPLATES

    existing_d = set(
        (await session.execute(select(Dataset.name).where(Dataset.owner_id == owner_id))).scalars().all()
    )
    existing_t = set(
        (await session.execute(select(FlowTemplate.name).where(FlowTemplate.owner_id == owner_id))).scalars().all()
    )
    created = 0
    for name, description, fmt, builder in SEED_DATASETS:
        if name in existing_d:
            continue
        try:
            df = builder()
        except Exception:
            continue
        await _persist_dataset(
            session, owner_id=owner_id, df=df, name=name,
            filename=f"{name}.{fmt}", file_format=fmt, description=description,
        )
        created += 1
    for t in SEED_TEMPLATES:
        if t["name"] in existing_t:
            continue
        session.add(FlowTemplate(
            owner_id=owner_id, name=t["name"], description=t.get("description", ""),
            steps=t.get("steps") or [], graph=t.get("graph") or {},
        ))
        created += 1
    return created


async def _seed_from_manifest(session: AsyncSession, owner_id: int) -> int:
    """Layer 2: the optional shipped bundle under data/seed_examples (server)."""
    settings = get_settings()
    seed_dir = settings.upload_path.parent / "seed_examples"
    manifest_path = seed_dir / "manifest.json"
    if not manifest_path.exists():
        return 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    existing = set(
        (await session.execute(select(Dataset.name).where(Dataset.owner_id == owner_id))).scalars().all()
    )
    created = 0
    for m in manifest:
        name = m.get("name")
        if not name or name in existing:
            continue
        fp = seed_dir / m.get("file", "")
        if not fp.exists():
            continue
        try:
            df = pd.read_parquet(fp)
        except Exception:
            continue
        await _persist_dataset(
            session,
            owner_id=owner_id,
            df=df,
            name=name,
            filename=m.get("orig_filename") or f"{name}.csv",
            file_format=m.get("file_format") or "csv",
            description=m.get("description") or "示例数据",
        )
        created += 1

    # Also seed a few example flow templates (steps/graph are JSON — no files).
    tmpl_path = seed_dir / "templates.json"
    if tmpl_path.exists():
        try:
            templates = json.loads(tmpl_path.read_text(encoding="utf-8"))
        except Exception:
            templates = []
        existing_t = set(
            (await session.execute(select(FlowTemplate.name).where(FlowTemplate.owner_id == owner_id))).scalars().all()
        )
        for t in templates:
            tname = t.get("name")
            if not tname or tname in existing_t:
                continue
            session.add(FlowTemplate(
                owner_id=owner_id, name=tname, description=t.get("description", ""),
                steps=t.get("steps") or [], graph=t.get("graph") or {},
            ))
            created += 1
    return created


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


async def ingest_image_upload(
    session: AsyncSession,
    *,
    owner_id: int,
    image_bytes: bytes,
    extension: str,
    original_filename: str,
    llm: LLMClient,
    display_name: Optional[str] = None,
    description: str = "",
) -> List[Dataset]:
    """Image → table via a vision LLM, then persist as a normal Dataset. Uses
    the same _persist_dataset path as CSV / Excel so lineage / GC / profiling
    all behave identically to any other source dataset."""
    df = await parse_image_to_df(image_bytes, extension=extension, llm=llm)

    stem = display_name or Path(original_filename).stem
    ds = await _persist_dataset(
        session,
        owner_id=owner_id,
        df=df,
        name=stem,
        filename=original_filename,
        file_format="image-ocr",  # so the UI can badge the origin
        description=description or f"Extracted from {original_filename} via vision LLM",
    )
    await session.commit()
    await session.refresh(ds)
    return [ds]


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


# ── Tecplot ASCII (.dat) — a common CFD/CAE export the generic AI parser can't
#    reliably handle (BLOCK packing stores values variable-by-variable, and a
#    file can carry hundreds of zones / probe channels). We read it natively.

def looks_like_tecplot(data: bytes) -> bool:
    """Sniff the first few KB: a Tecplot ASCII file declares VARIABLES and ZONE
    (and usually DATAPACKING). Content-based so it works regardless of the
    extension (.dat / .tec / .plt-ascii / no extension)."""
    try:
        head = data[:4096].decode("utf-8", "ignore").upper()
    except Exception:
        return False
    return "ZONE" in head and ("VARIABLES" in head or "DATAPACKING" in head)


def read_tecplot_ascii(src_path: Path) -> pd.DataFrame:
    """Parse a Tecplot ASCII file into ONE tidy long table: every zone (probe /
    channel) stacked, with a leading `zone` column, then the file's variables as
    columns. Handles BLOCK (variable-major) and POINT (row-major) packing and
    line-wrapped values."""
    import re
    import numpy as np

    lines = src_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    n = len(lines)

    # Variable names: collected from the VARIABLES line through any continuation
    # lines (one quoted name per line is common) up to the first ZONE.
    variables: List[str] = []
    i = 0
    while i < n:
        if lines[i].strip().upper().startswith("VARIABLES"):
            buf, j = [], i
            while j < n and not lines[j].strip().upper().startswith("ZONE"):
                buf.append(lines[j])
                j += 1
            variables = re.findall(r'"([^"]*)"', " ".join(buf))
            i = j
            break
        i += 1
    if not variables:
        raise ValueError("未找到 Tecplot 的 VARIABLES 定义,可能不是 Tecplot ASCII 文件")
    nvars = len(variables)

    def _all_floats(toks: List[str]) -> bool:
        if not toks:
            return False
        for tk in toks:
            try:
                float(tk)
            except ValueError:
                return False
        return True

    frames: List[pd.DataFrame] = []
    while i < n:
        if not lines[i].strip().upper().startswith("ZONE"):
            i += 1
            continue
        m = re.search(r'T\s*=\s*"([^"]*)"', lines[i])
        zone_name = m.group(1) if m else f"zone{len(frames) + 1}"

        # Read the zone header (I/J/K, DATAPACKING…) until the first numeric line.
        i += 1
        header: List[str] = []
        while i < n:
            s = lines[i].strip()
            if s and _all_floats(s.split()):
                break  # data starts; leave i pointing at it
            if s:
                header.append(s)
            i += 1
        h = " ".join(header).upper()
        def _dim(letter: str) -> int:
            mm = re.search(rf"\b{letter}\s*=\s*(\d+)", h)
            return int(mm.group(1)) if mm else 1
        npoints = max(1, _dim("I") * _dim("J") * _dim("K"))
        block = "BLOCK" in h
        need = npoints * nvars

        # Collect numeric tokens until the next ZONE / non-numeric line / EOF.
        vals: List[float] = []
        while i < n:
            s = lines[i].strip()
            if not s:
                i += 1
                continue
            if s.upper().startswith("ZONE"):
                break
            toks = s.split()
            if not _all_floats(toks):
                break
            vals.extend(float(t) for t in toks)
            i += 1

        arr = np.asarray(vals[:need] if len(vals) >= need else vals, dtype=float)
        if arr.size < nvars:
            continue  # not even one full point — skip this zone
        npoints = arr.size // nvars
        arr = arr[: npoints * nvars]
        data = arr.reshape(nvars, npoints).T if block else arr.reshape(npoints, nvars)
        df = pd.DataFrame(data, columns=variables)
        df.insert(0, "zone", zone_name)
        frames.append(df)

    if not frames:
        raise ValueError("没有从这个 Tecplot 文件解析出任何 zone 数据")
    return pd.concat(frames, ignore_index=True)


async def ingest_tecplot_upload(
    session: AsyncSession,
    *,
    owner_id: int,
    src_path: Path,
    original_filename: str,
    display_name: Optional[str] = None,
    description: str = "",
) -> List[Dataset]:
    """Ingest a Tecplot ASCII .dat as ONE tidy dataset (all zones stacked, with a
    `zone` column) so the probe/channel data becomes analyzable / chartable."""
    stem = display_name or Path(original_filename).stem
    df = read_tecplot_ascii(src_path)
    nzones = int(df["zone"].nunique()) if "zone" in df.columns else 1
    value_cols = [c for c in df.columns if c != "zone"]
    ds = await _persist_dataset(
        session, owner_id=owner_id, df=df, name=stem,
        filename=original_filename, file_format="dat",
        description=description or (
            f"Tecplot ASCII 数据:{nzones} 个 zone(测点/通道)堆叠成一张长表,共 {len(df):,} 行;"
            f"变量 {', '.join(value_cols)}(用 zone 列筛选某个通道)"
        ),
    )
    await session.commit()
    await session.refresh(ds)
    try:
        src_path.unlink(missing_ok=True)
    except Exception:
        pass
    return [ds]


def load_dataset_df(ds: Dataset) -> pd.DataFrame:
    path = Path(ds.storage_path)
    if not path.exists():
        raise FileNotFoundError(f"dataset file missing: {path}")
    return pd.read_parquet(path)


# Column-name hints that strongly suggest a time / ordering axis (any language).
_TIME_NAME_HINTS = ("time", "timestamp", "date", "datetime", "t_s", "time_s", "step", "时间", "日期", "时刻")


def _classify_column(s: pd.Series, name: str) -> str:
    """Best-effort semantic ROLE of a column (not just its dtype) so suggestions
    can be tailored. Pure/deterministic — no LLM, no guessing values."""
    lname = name.strip().lower()
    if lname in ("x", "y", "z"):
        return "coord"
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_numeric_dtype(s):
        # A numeric column whose NAME says time and whose values rise monotonically
        # is really the time axis, not a measurement.
        if any(h in lname for h in _TIME_NAME_HINTS):
            vals = s.dropna()
            if len(vals) >= 3 and vals.is_monotonic_increasing:
                return "datetime"
        return "numeric"
    # object / category / string
    n = max(1, int(s.shape[0]))
    n_unique = int(s.nunique(dropna=True))
    # Low-cardinality strings read as categories you can group by; otherwise free text.
    if n_unique <= max(20, int(0.05 * n)):
        return "categorical"
    return "text"


def build_profile(df: pd.DataFrame, ds: Dataset) -> Dict[str, Any]:
    """Deterministic, instant, FREE first-read of a dataset: what it roughly is,
    a few grounded facts, and concrete next actions mapped to real recipes/tools.

    No LLM — every fact is computed from the actual frame, so it can't
    hallucinate columns or numbers (the paid `/explain` stays the deep read)."""
    n_rows, n_cols = int(df.shape[0]), int(df.shape[1])
    roles: Dict[str, List[str]] = {
        "numeric": [], "datetime": [], "categorical": [], "text": [], "coord": [], "bool": [],
    }
    missing_hot: List[Dict[str, Any]] = []
    constant_cols: List[str] = []
    for c in df.columns:
        s = df[c]
        name = str(c)
        role = _classify_column(s, name)
        roles[role].append(name)
        n_missing = int(s.isna().sum())
        if n_missing and n_rows:
            missing_hot.append({"name": name, "pct": round(100.0 * n_missing / n_rows, 1)})
        if int(s.nunique(dropna=True)) <= 1:
            constant_cols.append(name)
    missing_hot.sort(key=lambda d: d["pct"], reverse=True)

    has_coord = {x.lower() for x in roles["coord"]} >= {"x", "y", "z"}
    n_numeric = len(roles["numeric"])
    has_time = bool(roles["datetime"])
    has_cat = bool(roles["categorical"])

    # ── shape "kind" — the headline cognition ──────────────────────────────
    if has_coord:
        kind = "mesh"
        headline = f"这是一份网格/点云数据:每行一个空间点,带 X/Y/Z 坐标和 {n_numeric} 个物理场。"
    elif has_time and n_numeric >= 1:
        kind = "timeseries"
        headline = f"这看起来是一份时间序列:有时间轴(列 {roles['datetime'][0]}),随时间记录了 {n_numeric} 个数值量。"
    elif n_numeric >= 4 and n_rows <= max(2000, n_numeric * 50) and not has_time:
        kind = "wide_numeric"
        headline = f"这是一份多变量数值表:{n_rows} 条记录 × {n_numeric} 个数值变量,适合找规律/找主因。"
    elif has_cat and n_numeric >= 1:
        kind = "grouped"
        headline = f"这是一份带分类的数据:有 {len(roles['categorical'])} 个分类列和 {n_numeric} 个数值列,可以按组对比。"
    else:
        kind = "tabular"
        headline = f"这是一份表格数据:{n_rows} 行 × {n_cols} 列。"

    # ── grounded facts — concrete per-column, not just type counts ──────────
    def _fmt_num(v: float) -> str:
        if v != v:  # NaN
            return "—"
        av = abs(v)
        if av != 0 and (av >= 1e5 or av < 1e-3):
            return f"{v:.2e}"
        return str(int(v)) if float(v).is_integer() else f"{v:.3g}"

    const_set = set(constant_cols)
    facts: List[str] = [f"{n_rows:,} 行 × {n_cols} 列"]

    # Numeric columns → their actual value range (the most useful "what's in it").
    for c in [c for c in roles["numeric"] if c not in const_set][:4]:
        s = df[c].dropna()
        if len(s):
            facts.append(f"{c} ∈ {_fmt_num(float(s.min()))} ~ {_fmt_num(float(s.max()))}")

    # Categorical columns → their actual levels (a few examples + total count).
    for c in [c for c in roles["categorical"] if c not in const_set][:3]:
        s = df[c].dropna()
        k = int(s.nunique())
        vals = [str(v) for v in pd.unique(s)[:4]]
        facts.append(f"{c}:{'/'.join(vals)}{'…' if k > len(vals) else ''}({k} 类)")

    # Constant columns → show the single value they hold (not just "is constant").
    for c in constant_cols[:4]:
        s = df[c].dropna()
        facts.append(f"{c} 恒为 {str(s.iloc[0]) if len(s) else '空'}")

    if missing_hot and missing_hot[0]["pct"] > 0:
        worst = "、".join(f"{m['name']}({m['pct']}%)" for m in missing_hot[:3])
        facts.append(f"有缺失:{worst}")
    elif not missing_hot:
        facts.append("没有缺失值")
    facts = [f for f in facts if f]

    # ── suggestions — each maps to a real recipe (→ chat) or in-view action ─
    sugg: List[Dict[str, str]] = []
    def add(slug: str, why: str):
        sugg.append({"slug": slug, "why": why})

    if kind == "mesh":
        add("mesh3d", "在 3D 里看网格的形状和场分布")
        add("chart", "把某个物理场画成分布图")
    elif kind == "timeseries":
        add("chart", "先把随时间的变化画出来看看趋势")
        add("smooth", "信号有毛刺的话,平滑降噪但保留波形")
        add("outliers", "找出突变/跳变这种异常点")
    elif kind == "wide_numeric":
        add("drivers", "看看哪个变量对结果影响最大、哪些没用")
        add("corr", "找出变量两两之间的相关关系")
        if n_numeric >= 5:
            add("pca", "变量太多看不过来,压到 2-3 个主维度看结构")
        add("chart", "挑两个变量画散点/趋势")
    elif kind == "grouped":
        add("chart", "按分类分组,对比各组的数值")
        add("corr", "看看数值列之间有没有关联")
    else:
        add("chart", "可视化看看数据长什么样")
        if n_numeric == 2:
            add("fit", "两个量之间拟合一条关系")

    if n_numeric == 2 and kind not in ("tabular",):
        add("fit", "在两个数值量之间拟合一条关系")
    if missing_hot and missing_hot[0]["pct"] >= 5:
        add("clean", f"缺失有点多(最高 {missing_hot[0]['pct']}%),先清洗一下")
    add("explain", "让 AI 用大白话详细讲讲这份数据")

    # de-dup by slug, keep first (richest) why
    seen: set[str] = set()
    suggestions = []
    for s in sugg:
        if s["slug"] in seen:
            continue
        seen.add(s["slug"])
        suggestions.append(s)

    return {
        "kind": kind,
        "headline": headline,
        "facts": facts,
        "roles": {k: v for k, v in roles.items() if v},
        "missing": missing_hot[:8],
        "suggestions": suggestions,
    }


def _safe_head(df: pd.DataFrame, n: int) -> Any:
    try:
        return df.head(n).to_dict(orient="records")
    except Exception:
        return [{c: str(df.iloc[i][c]) for c in df.columns} for i in range(min(n, len(df)))]


async def delete_dataset_tree(
    session: AsyncSession,
    *,
    owner_id: int,
    dataset_id: int,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Delete a dataset AND everything derived from it, recursively.

    A derived dataset is only meaningful relative to its parent — 「去噪后的数据」
    with the original gone is an orphan the lineage view can't explain. So a
    delete takes the whole subtree: the target, its children, their children.

    Unlike `gc_derived_datasets` this is an EXPLICIT user action, so it does not
    spare 留存 (kept) or promoted descendants — the caller asked for this node to
    go. It does report them, so the UI can say what is about to be lost before
    committing. `dry_run=True` computes the subtree without deleting anything.
    """
    rows = (await session.execute(
        select(Dataset).where(Dataset.owner_id == owner_id)
    )).scalars().all()
    by_id = {d.id: d for d in rows}
    target = by_id.get(dataset_id)
    if target is None:
        return {"deleted": [], "count": 0, "freed_bytes": 0, "dry_run": dry_run, "found": False}

    children: Dict[int, List[Dataset]] = {}
    for d in rows:
        if d.derived_from is not None:
            children.setdefault(d.derived_from, []).append(d)

    # BFS the subtree. `seen` also guards against a cycle in corrupted lineage.
    victims: List[Dataset] = []
    seen: set = set()
    queue: List[Dataset] = [target]
    while queue:
        cur = queue.pop(0)
        if cur.id in seen:
            continue
        seen.add(cur.id)
        victims.append(cur)
        queue.extend(children.get(cur.id, []))

    freed = 0
    deleted: List[Dict[str, Any]] = []
    for d in victims:
        freed += int(d.size_bytes or 0)
        deleted.append({"id": d.id, "name": d.name, "kind": d.kind, "kept": bool(d.kept)})
    # Delete deepest-first so a parent row never disappears before its children.
    if not dry_run:
        for d in reversed(victims):
            try:
                p = Path(d.storage_path)
                if p.exists():
                    p.unlink()
            except Exception:
                pass  # orphaned parquet is harmless; the row is what matters
            await session.delete(d)
        await session.commit()

    return {
        "deleted": deleted,
        "count": len(deleted),
        "descendants": len(deleted) - 1,
        "kept_hit": sum(1 for d in deleted if d["kept"]),
        "freed_bytes": freed,
        "dry_run": dry_run,
        "found": True,
    }


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
