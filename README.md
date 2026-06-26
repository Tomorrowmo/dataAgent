# RLab Cortex — Verifiable Data Analysis Agent

> **The data-analysis agent for people who need to trust the number.**
>
> RLab Cortex runs your data through a curated library of *vetted classical algorithms* instead of guessing with LLM-generated pandas. Drop in your own algorithm code, or let the agent write a new one — but only after a sandboxed test passes and you approve it.

---

## Table of contents

1. [Why this exists](#why-this-exists)
2. [Quick start (local)](#quick-start-local)
3. [Quick start (cloud, one-click)](#quick-start-cloud-one-click)
4. [Architecture](#architecture)
5. [Built-in algorithm catalog](#built-in-algorithm-catalog)
6. [Adding your own algorithm](#adding-your-own-algorithm)
7. [Configuration](#configuration)
8. [Project layout](#project-layout)
9. [Business documents](#business-documents)

---

## Why this exists

We surveyed the data-analysis AI space in May 2026 (see [docs/positioning.md](docs/positioning.md)) and found:

- **Chat-with-CSV is saturated.** Julius, Hex, ChatGPT Data Analysis, PandasAI all do it. Vanna AI was archived in March 2026 — the moat is gone.
- **The #1 user complaint is "looks confident, wrong number."** Generic LLM tools hallucinate the math. 38% of executives (Deloitte 2024) admit acting on wrong AI numbers.
- **Engineers and scientists are underserved.** Battery test, CAE/CFD, NVH, instrument-data, and other workflows need *domain-specific* algorithms (Savgol, Butterworth, Dixon, sensitivity analysis, dV/dQ peak tracking…) that no generic tool provides.

RLab Cortex is the answer: **curated, citable, classical algorithms first; sandboxed user code second; LLM-generated code only as a last-resort fallback — and only after a test passes and the human approves.**

V1 wedge market: **battery test engineers** (fastest-growing TAM, no entrenched incumbent, structural multi-vendor binary-data fragmentation moat). Follow-on verticals: CAE post-processing, NVH labs.

## Quick start (local)

### Prerequisites

- **Node 22+**, **Python 3.12+**, **Docker Desktop** (for production-style runs)
- Optional: a **DeepSeek API key** (for the AI-coding feature and the chat agent). Users can also bring their own via the in-app Settings.

### Run the dev stack manually

```bash
# 1. Backend
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt           # Linux/macOS
cp .env.example .env                                            # then edit DEEPSEEK_API_KEY
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8077

# 2. Frontend (new shell)
cd web
npm install
cp .env.example .env.local      # API_PROXY_TARGET defaults to localhost:8077
npm run dev
# open http://localhost:3000
```

### Run as a Docker stack (one command)

```bash
# Windows (PowerShell)
$env:DEEPSEEK_API_KEY = "sk-..."
pwsh -File deploy/deploy.ps1

# Linux / macOS
DEEPSEEK_API_KEY=sk-... bash deploy/deploy.sh

# Then open http://localhost:8088
```

## Quick start (cloud, one-click)

Tested on Aliyun ECS and Tencent Cloud CVM (any Ubuntu/Debian VM also works).

```bash
# On the cloud VM
git clone https://github.com/<you>/numetrix.git   # or scp the folder up
cd numetrix
DEEPSEEK_API_KEY=sk-...  PUBLIC_PORT=80  bash deploy/deploy.sh
```

The script:

1. Installs Docker if it's missing
2. Auto-detects Docker Hub access and falls back to `docker.m.daocloud.io` mirror in mainland China
3. Generates a fresh `SECRET_KEY` for JWT signing
4. Builds the backend + frontend images and brings the stack up via Docker Compose
5. Health-checks the API and prints your public URL

**Open Aliyun security group → port 80 (or your `PUBLIC_PORT`) inbound.** Done.

To later upgrade: `git pull && bash deploy/deploy.sh` — Docker volumes persist user data across rebuilds.

## Architecture

```
                  ┌────────────────┐
   Browser  ────► │  Nginx (80)    │
                  └────────┬───────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
      ┌──────────────┐         ┌────────────────┐
      │  Next.js 15  │ ◄────── │  FastAPI       │
      │  (3000)      │  /api/* │  (8000)        │
      └──────────────┘         └────────┬───────┘
                                        │
                            ┌───────────┼─────────────┐
                            ▼           ▼             ▼
                       sqlite       parquet         python -I
                       /data/db   /data/uploads    sandbox subprocess
                                                   (AST-validated,
                                                    timeout, no network)
```

Key design choices:

- **Stateless API workers** + sqlite/parquet on a Docker volume — drop-in upgradable to Postgres + S3 later.
- **Subprocess sandbox** with AST whitelist + wall-clock timeout + restricted builtins + best-effort socket block. Survives accidental infinite loops, AST-rejects `import os`, dies cleanly on `MemoryError`.
- **JSON-action ReAct loop** for the chat agent — portable across any OpenAI-compatible LLM (DeepSeek default, OpenAI/Claude/local-Ollama swappable via env).
- **BYOK first.** A user can paste their own DeepSeek key in Settings; the server-side key is only a convenience for solo deployments.

See [docs/architecture.md](docs/architecture.md) for the full diagram, request lifecycle, and threat model.

## Built-in algorithm catalog

20 algorithms in 5 categories. Run `python backend/smoke_test.py` to see them in action.

| Category | Algorithm | Notes |
|---|---|---|
| regression | `linear_regression` | OLS with R² and RMSE |
| regression | `polynomial_regression` | degree 1–10 |
| regression | `curve_fit` | exponential / logarithmic / power / sigmoid |
| regression | `correlation` | Pearson / Spearman / Kendall |
| regression | `interpolate` | linear / cubic / quadratic / nearest |
| filter | `moving_average` | rolling-mean smoother |
| filter | `median_filter` | robust to spikes |
| filter | `gaussian_filter` | σ-controlled |
| filter | `savgol_filter` | Savitzky-Golay |
| filter | `butterworth_filter` | zero-phase, low/high-pass |
| preprocess | `normalize` | min-max / z-score / max-abs |
| preprocess | `fill_missing` | linear / ffill / bfill / mean / median / value |
| preprocess | `outlier_detect` | IQR / z-score / **Dixon's Q (small sample)** |
| preprocess | `data_prep` | drop dupes + NaN |
| structure | `transpose` | optional index column |
| structure | `derived_column` | safe pandas-eval expressions |
| structure | `drop_columns` | |
| structure | `group_aggregate` | mean/median/sum/min/max/std/var/count/first/last |
| reduce | `pca` | linear or kernel (rbf/poly/sigmoid/cosine) |
| reduce | `sensitivity` | correlation / Morris / variance-based |

## Adding your own algorithm

Any file with a top-level `META` dict and a `run(df, **params)` function is a valid RLab Cortex tool:

```python
import pandas as pd
import numpy as np

META = {
    "name": "Z-normalize columns",
    "slug": "znorm_demo",
    "category": "preprocess",
    "description": "Z-score normalize selected numeric columns.",
    "params_schema": {
        "columns": {"type": "array", "items": "string", "required": False},
    },
    "returns": "dataframe",
}

def run(df, *, columns=None):
    if df is None:
        raise ValueError("df is required")
    out = df.copy()
    cols = columns or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    for c in cols:
        s = out[c].astype(float)
        mu, sd = s.mean(), s.std(ddof=0)
        out[c] = (s - mu) / sd if sd else 0.0
    return out

test_cases = [{"df": pd.DataFrame({"x": [1.0, 2.0, 3.0]}), "params": {}}]
```

Paste it into **Algorithm library → Upload your algorithm**. RLab Cortex will:

1. AST-validate (reject `import os`, `eval`, `__import__`, etc.)
2. Run it in the sandbox against your test cases (and optionally a real dataset)
3. Show you the result + the test report
4. Save it as a permanent, callable tool only after you approve

The same flow applies to LLM-generated algorithms — the model writes the file, the sandbox tests it, and you decide whether it joins your library.

## Configuration

Backend `backend/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | (dev only) | JWT signing key — rotated by deploy script |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/db/app.db` | Postgres URL also supported |
| `UPLOAD_DIR` | `./data/uploads` | Parquet + result file root |
| `DEEPSEEK_API_KEY` | empty | Server-side key. Users can also set their own per-account |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | Swap to any OpenAI-compatible endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | |
| `SANDBOX_CPU_SECONDS` | 10 | POSIX rlimit; ignored on Windows |
| `SANDBOX_MEMORY_MB` | 512 | POSIX rlimit |
| `SANDBOX_TIMEOUT_SECONDS` | 30 | Cross-platform wall-clock kill |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated |

Frontend `web/.env.local`:

| Variable | Default | Purpose |
|---|---|---|
| `API_PROXY_TARGET` | `http://127.0.0.1:8077` | Where `/api/*` is rewritten in dev |

## Project layout

```
.
├── backend/                 # FastAPI app
│   ├── app/
│   │   ├── algorithms/      # Built-in algorithm registry (+ 20 algorithms)
│   │   ├── api/             # auth / datasets / algorithms / chat routers
│   │   ├── core/            # config + security
│   │   ├── db/              # SQLAlchemy models
│   │   ├── sandbox/         # AST validator + subprocess executor
│   │   └── services/        # LLM, codegen, datasets, chat agent
│   ├── requirements.txt
│   └── smoke_test.py        # 8 standalone tests — no HTTP, no LLM
├── web/                     # Next.js 15 app router
│   ├── app/                 # landing, login, signup, /app workspace
│   ├── components/          # Sidebar, ChatView, DatasetsView, AlgorithmsView, SettingsView
│   └── lib/api.ts           # typed fetch client + SSE chat stream
├── deploy/
│   ├── backend.Dockerfile   # multi-stage, wheels-only (no gcc)
│   ├── web.Dockerfile       # Next.js standalone output
│   ├── docker-compose.yml   # nginx + web + backend + persistent volume
│   ├── nginx.conf           # reverse proxy (SSE-friendly)
│   ├── deploy.sh            # one-click Linux / cloud deploy
│   └── deploy.ps1           # Windows / Docker Desktop helper
└── docs/
    ├── positioning.md       # product positioning + market research synthesis
    ├── business-plan.md     # GTM, pricing, financial plan, fundraising
    └── architecture.md      # technical architecture + threat model
```

## Business documents

- **[docs/positioning.md](docs/positioning.md)** — competitive landscape, white-space, target persona, wedge market, vision
- **[docs/business-plan.md](docs/business-plan.md)** — 12-month plan to $1M ARR, pricing, distribution, fundraising plan
- **[docs/architecture.md](docs/architecture.md)** — technical architecture, scaling plan, threat model

---

© 2026 RLab Cortex. Built fast, built right.
