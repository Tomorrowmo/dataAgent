"""Single source of truth for the app version, changelog and linked documents.

`/api/about` (main.py) serves this to the UI; `/api/health` and the FastAPI
app version read `APP_VERSION` from here. The changelog lives in `changelog.json`
next to this file — edit it by hand or scaffold a new entry with
`tools/gen_changelog.py`, which appends a draft from the git log.
"""
from __future__ import annotations

import json
import os

APP_VERSION = "2026"
PRODUCT_NAME = "RLab Cortex"
PRODUCT_NOTE = ""

_CHANGELOG_PATH = os.path.join(os.path.dirname(__file__), "changelog.json")


def load_changelog() -> list[dict]:
    """Read the structured changelog (newest version first). Never raises — a
    missing/broken file degrades to an empty list so the API still answers."""
    try:
        with open(_CHANGELOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


# Documents surfaced in the UI (served as static files from web/public/docs/).
# `view`  → PDF, opens inline in a new tab (browser-native preview);
# `download` → the .docx; `filename` is the name the browser saves it as.
DOCUMENTS = [
    {
        "key": "manual",
        "title": "产品使用手册",
        "subtitle": "从登录到出图的完整操作指南",
        "view": "/docs/user-manual.pdf",
        "download": "/docs/user-manual.docx",
        "filename": "RLab Cortex 产品使用手册.docx",
    },
    {
        "key": "whitepaper",
        "title": "产品白皮书",
        "subtitle": "产品定位、技术路线与应用案例",
        "view": "/docs/whitepaper.pdf",
        "download": "/docs/whitepaper.docx",
        "filename": "RLab Cortex 产品白皮书.docx",
    },
]


# where the served PDFs live (web/public/docs); checked per-request so dropping a
# PDF in makes「查看」appear with no restart.
_DOCS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "docs"))


def about_payload() -> dict:
    docs = []
    for d in DOCUMENTS:
        item = dict(d)
        pdf_name = os.path.basename(d.get("view", ""))
        if not pdf_name or not os.path.exists(os.path.join(_DOCS_DIR, pdf_name)):
            item["view"] = ""  # no PDF yet → frontend hides「查看」, shows only「下载」
        docs.append(item)
    return {
        "version": APP_VERSION,
        "product": PRODUCT_NAME,
        "product_note": PRODUCT_NOTE,
        "changelog": load_changelog(),
        "documents": docs,
    }
