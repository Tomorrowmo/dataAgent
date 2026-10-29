"""Image → DataFrame ingestion.

The user pastes / drops an image of a table (screenshot, phone photo of a
printed report, a plot with an embedded data grid, …) and we hand it to a
vision LLM with a strict "return CSV" prompt. The CSV is parsed to a pandas
DataFrame that flows through the same `_persist_dataset` path as an
uploaded .csv.

Why a dedicated path (not the generic `format_adapter` codegen): a Python
parser can't OCR pixels. This is the one upload class where the "read the
file" step MUST run through a vision-capable model.

Model selection:
- If the caller's LLMClient already points at a vision model (name contains
  "vl" / "vision" / "gpt-4o" / "gpt-4-vision"), use it as-is.
- Else if the base_url is dashscope (which is what our BYOK users have),
  swap the model to `qwen-vl-max`. `qwen-max` alone is text-only.
- Else if the base_url is DeepSeek, swap to `deepseek-v4-flash-vision-exp`.
- Else surface a diagnostic error the caller can show to the user.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Optional

import pandas as pd

from .llm import LLMClient, LLMError


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


_VISION_PROMPT = """You are a table-extraction agent. The image contains tabular data — a table from a report/paper, a screenshot from another tool, a photograph of a printed table, or a chart WITH an embedded data grid.

Extract EVERY row and column as CSV. Return ONLY the CSV, no prose, no code fences.

Hard rules:
- First line = column headers. Prefer the headers shown in the image; if they are missing/unclear, invent short snake_case names.
- One row per observation. Do NOT merge rows.
- Numeric values as plain numbers (drop unit suffixes like "kg", "°C", "%" from the cells — those belong in the header if useful).
- Missing cells → empty field (two consecutive commas).
- Comma-separated. If a cell must contain a comma, wrap the cell in double quotes.
- If the image contains multiple tables, extract the LARGEST or most-complete one.
- If the image contains NO table at all (only chart bars with no data labels, a photo of a landscape, a page of prose, …), reply with exactly `NO_TABLE_FOUND` on a single line.

Reply with the CSV only. Nothing else."""


def _pick_vision_model(llm: LLMClient) -> Optional[str]:
    """Return the model slug to use for vision, or None if we have no plausible
    candidate (caller should error out)."""
    model = (llm.model or "").lower()
    # Every Claude model since 3.x is natively multimodal — no swap needed.
    if model.startswith("claude"):
        return llm.model
    if any(hint in model for hint in ("vl", "vision", "gpt-4o", "-o1", "-o3", "gemini")):
        return llm.model
    base = (llm.base_url or "").lower()
    if "dashscope" in base or "aliyun" in base:
        return "qwen-vl-max"
    if "deepseek" in base:
        # deepseek-v4-flash is text-only; images go to the (experimental) vision
        # sibling, live on the public API since 2026-08-21.
        return "deepseek-v4-flash-vision-exp"
    # Unknown provider — try user's model and let it 400 with a real error.
    return llm.model


def _strip_code_fence(s: str) -> str:
    # The prompt says "no code fences" but models occasionally still wrap in ```csv…```
    s = s.strip()
    m = re.match(r"^```(?:csv)?\s*\n?(.*?)```\s*$", s, flags=re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else s


def _data_url(image_bytes: bytes, ext: str) -> str:
    mime = _MIME_BY_EXT.get(ext.lower(), "image/png")
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def _vision_llm(llm: LLMClient) -> "LLMClient":
    """Fork the caller's client onto a vision-capable model (same auth/base_url).
    Raises with an actionable message when the configured provider has none."""
    if not llm.is_configured:
        raise LLMError("LLM is not configured. Set a key in Settings.")
    vision_model = _pick_vision_model(llm)
    if vision_model is None:
        raise LLMError(
            "当前配置的模型不支持图片。请在设置里换一个视觉模型"
            "(例如 dashscope 的 qwen-vl-max,或 Claude / gpt-4o)。"
        )
    return LLMClient(api_key=llm.api_key, base_url=llm.base_url, model=vision_model)


async def _vision_call(
    image_bytes: bytes, *, extension: str, system: str, user_text: str,
    llm: LLMClient, max_tokens: int = 4000,
) -> str:
    """One vision round-trip: image + a system/user prompt → raw model text.
    Shared by table-extraction, question-answering, and chart-digitization."""
    vlm = _vision_llm(llm)
    data_url = _data_url(image_bytes, extension)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": user_text},
        ]},
    ]
    return await vlm.chat(messages, temperature=0.0, max_tokens=max_tokens)


_ANALYZE_PROMPT = """You are an engineering/scientific assistant looking at an image the user uploaded (a chart, plot, diagram, schematic, or photo).

First identify what the image actually is (a table, a line/bar chart, a diagram, a photo) and refer to it accordingly — never call a table a "curve" or say values were "read off a curve" when they were printed in a table.

Answer the user's question about the image directly and concretely, in the user's language. Read values off axes and curves when asked. State numbers with their units. If the user tells you what the axes mean, trust that. If something cannot be determined from the image, say so plainly rather than guessing. Do not invent data the image doesn't show."""


async def analyze_image(
    image_bytes: bytes, *, extension: str, instruction: str, llm: LLMClient,
) -> str:
    """Question-driven image analysis: the user's `instruction` IS the prompt, so
    the model reasons about whatever the image actually is (a Mach-vs-deflection
    curve, a schematic, a photo) instead of being forced to OCR a table. Returns
    the model's prose answer."""
    text = (instruction or "").strip() or "描述这张图,并指出其中的关键信息。"
    return (await _vision_call(
        image_bytes, extension=extension, system=_ANALYZE_PROMPT,
        user_text=text, llm=llm, max_tokens=3000,
    )).strip()


_DIGITIZE_PROMPT = """You are a chart-digitization tool. The image is a 2-D plot (curve(s) on X/Y axes). Read the plotted curve(s) back into numeric data points.

The user will tell you what the axes represent. Use those meanings for the column headers.

Return ONLY CSV, no prose, no code fences:
- First line = column headers: the X-axis quantity, then one column per curve (Y).
- Sample the curve densely and evenly along X (aim for 20-60 rows) so the shape is preserved. Read coordinates off the gridlines/axis ticks as accurately as you can.
- Numbers only in cells (no units in the cells — put units in the header if useful).
- If there are multiple labelled curves, give each its own Y column named after its legend label.
- If the image is NOT a plottable curve chart (a table, a photo, prose), reply with exactly `NOT_A_CHART` on a single line.

Reply with the CSV only."""


async def digitize_chart_to_df(
    image_bytes: bytes, *, extension: str, instruction: str, llm: LLMClient,
) -> pd.DataFrame:
    """Read a plotted curve back into a DataFrame of sampled (x, y…) points, using
    the axis meanings the user supplied. This is the '解析出曲线数据' path — turns
    a chart image into an analyzable dataset."""
    user_text = (
        (instruction or "").strip()
        + "\n\nDigitize the plotted curve(s) into CSV using the axis meanings above."
    )
    raw = await _vision_call(
        image_bytes, extension=extension, system=_DIGITIZE_PROMPT,
        user_text=user_text, llm=llm, max_tokens=6000,
    )
    text = _strip_code_fence(raw)
    if text.strip().upper().startswith("NOT_A_CHART"):
        raise LLMError(
            "这张图不是可数字化的曲线图。如果它是数据表格,请用「上传到数据集」直接抽表格;"
            "如果只是想让我看图回答问题,直接问就行。"
        )
    for engine, sep in (("c", ","), ("python", "\t"), ("python", r"\s{2,}")):
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, engine=engine)
            if df.shape[1] >= 2 and len(df) >= 1:
                df = df.dropna(how="all").reset_index(drop=True)
                df.columns = [str(c).strip() for c in df.columns]
                return df
        except Exception:
            continue
    raise LLMError(
        "视觉模型返回的内容没法解析成数据。前 200 字符:"
        + text[:200].replace("\n", "\\n")
    )


async def parse_image_to_df(
    image_bytes: bytes,
    *,
    extension: str,
    llm: LLMClient,
) -> pd.DataFrame:
    """Send the image to a vision model with the extract-CSV prompt. Return
    a DataFrame or raise a clear exception the caller can surface."""
    raw = await _vision_call(
        image_bytes, extension=extension, system=_VISION_PROMPT,
        user_text="Extract the table as CSV.", llm=llm, max_tokens=6000,
    )
    text = _strip_code_fence(raw)

    if text.strip().upper().startswith("NO_TABLE_FOUND"):
        raise LLMError(
            "No table found in the image. Upload a photo/screenshot that "
            "actually shows a data table, or use CSV/Excel directly."
        )

    # Parse CSV → DataFrame. Try comma first, then tab, then any-whitespace as
    # a fallback (some vision models like to pretty-align columns with spaces).
    for engine, sep in (("c", ","), ("python", "\t"), ("python", r"\s{2,}")):
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, engine=engine)
            if df.shape[1] >= 2 and len(df) >= 1:
                # Sanity: drop rows that are entirely NaN + strip whitespace.
                df = df.dropna(how="all").reset_index(drop=True)
                df.columns = [str(c).strip() for c in df.columns]
                return df
        except Exception:
            continue

    raise LLMError(
        "The vision model returned text I could not parse as CSV. "
        "First 200 chars: " + text[:200].replace("\n", "\\n")
    )
