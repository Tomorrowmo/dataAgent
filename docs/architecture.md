# RLab Cortex — Technical Architecture

## Stack at a glance

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 15 (app router) + Tailwind + TypeScript | Same-origin API rewrite in dev; standalone-output for tiny prod containers |
| Backend | FastAPI + SQLAlchemy 2 (async) + Pydantic v2 | Fast, typed, async-native, easy to dockerize |
| DB | SQLite (default) — easy upgrade path to Postgres via `DATABASE_URL` | One file for V1; no ops burden |
| Object store | Local disk (`UPLOAD_DIR`) — easy upgrade to S3/OSS | One volume for V1 |
| LLM | DeepSeek (OpenAI-compatible) — default; users can BYOK to any compatible endpoint | Cheapest credible model with strong code generation; China-friendly |
| Sandbox | `python -I` subprocess + AST whitelist + wall-clock timeout + restricted builtins + best-effort socket block | Cross-platform (Windows / POSIX), no Docker-in-Docker required |
| Auth | Bcrypt + JWT (HS256) | Standard, dependency-light |
| Reverse proxy | Nginx (in compose) | SSE-friendly chat streaming; handles TLS in front of you when you add it |

## Request lifecycle

### A. User uploads a dataset

```
Browser ─POST /api/datasets─► Nginx ─► Next.js (passthrough) ─► FastAPI
                                                                  │
                                                                  ▼
                                                    pandas reads csv/xlsx/parquet
                                                                  │
                                                                  ▼
                                                    write as parquet to /data/uploads/user_<id>/
                                                                  │
                                                                  ▼
                                                    insert Dataset row + schema preview
```

### B. User runs a built-in algorithm

```
Browser ─POST /api/algorithms/run─► FastAPI ─► registry.execute_builtin(slug, df, params)
                                                            │
                                                            ▼
                                                 in-process numpy/pandas/scipy
                                                            │
                                                            ▼
                                                 result → parquet → /data/uploads/results/
                                                            │
                                                            ▼
                                                 insert Run row, return summary
```

### C. User runs a user/AI algorithm

```
Browser ─POST /api/algorithms/run─► FastAPI ─► registry.execute_code(code, df, params)
                                                            │
                                                            ▼
                                            sandbox/validator.py  (AST whitelist + import check)
                                                            │
                                                            ▼
                                            subprocess.run(python -I app/sandbox/runner_worker.py)
                                                            │
                                                            ▼
                                            worker: read input parquet from a temp dir
                                                            │
                                                            ▼
                                                exec(code) in restricted-builtins namespace
                                                            │
                                                            ▼
                                            write output parquet + JSON result delimiter
                                                            │
                                                            ▼
                                            parent reads __SANDBOX_RESULT__ delimiter line
                                                            │
                                                            ▼
                                                            DB
```

### D. Chat agent turn

```
Browser ─POST /api/chat/.../send─► FastAPI ─► chat_agent.run_turn(...)
                                                       │
                                                       ▼
                                  while step < MAX_STEPS:
                                       1. LLM returns {thought, action, args}
                                       2. dispatch action:
                                            - list_tools  → registry index
                                            - describe    → algorithm spec
                                            - run_tool    → execute_builtin or sandbox
                                            - generate    → codegen + sandbox test
                                            - answer      → break
                                       3. SSE stream each step to the browser
```

Every event (thought, tool_call, tool_result, final) is persisted in `Message.meta.events` so the full audit trail is reconstructable later.

## Sandbox threat model

| Threat | Mitigation |
|---|---|
| Arbitrary code execution | Subprocess only — never `exec` user code in the API process |
| Read/write outside scratch dir | `subprocess` `cwd=workdir` (tempdir), no shell, AST rejects `open()`, `__import__`, `eval`, `exec`, dunder attribute access |
| Imports outside an allow-list | AST validator at submission time; restricted builtins at runtime |
| Network access (data exfil, SSRF) | AST rejects `socket`, `urllib`, `requests`, etc.; runtime monkey-patches `socket.socket` and `socket.create_connection` to raise |
| Infinite loops / CPU exhaustion | Wall-clock timeout enforced by parent `subprocess.run(timeout=...)`. POSIX adds RLIMIT_CPU + RLIMIT_AS |
| Memory exhaustion | POSIX RLIMIT_AS. Windows: best-effort via timeout — recommend deploying backend in Linux container (which is what `deploy.sh` does anyway) |
| Subprocess fork bomb | RLIMIT_NPROC=0 on POSIX (worker can't spawn anything) |
| `MemoryError` crashes API | Subprocess isolation — child dies, parent reports `status: error` |
| Output bomb (`print` 1 TB) | Output capped at `SANDBOX_MAX_OUTPUT_BYTES`; worker truncates logs at 200 KB |
| Long-running model token leak | LLM key never sent to user-code subprocess; sandbox has no env access to `DEEPSEEK_API_KEY` (the worker is launched with `env.pop("DEEPSEEK_API_KEY")` semantics via `python -I`) |

**Not yet mitigated (V2 work):** seccomp / cgroups isolation, eBPF syscall filtering, container-per-execution. For higher-assurance deployments we will use a Firecracker-style microVM (~50 ms cold start) as the next layer.

## Performance characteristics (local Windows, single laptop)

| Operation | p50 latency |
|---|---|
| Built-in `linear_regression` (200 samples × 2 features) | <20 ms |
| Built-in `savgol_filter` (500 rows) | 30–50 ms |
| User-code sandbox warm path (500 rows) | 400–500 ms (Python subprocess spin-up dominates) |
| LLM codegen + sandbox test | 2–5 s (DeepSeek dominated) |
| Dataset upload + parquet write (10 MB CSV) | <500 ms |

## Scaling plan

| Scale | Change |
|---|---|
| Today: SQLite + single uvicorn worker | Default |
| 100 active users | Bump `--workers 4`; same SQLite (still fine at <50 writes/s) |
| 1k active users | Swap `DATABASE_URL` to Postgres; move `/data/uploads` to S3/OSS; same backend container |
| 10k active users | Pull sandbox execution into a separate microservice — Modal / Fly Machines / a Firecracker pool. API stays unchanged. |
| Heavy enterprise | Self-hosted Kubernetes Helm chart (~30 lines of values from this compose) |

## Why we picked these specific things over the obvious alternative

- **FastAPI vs Flask**: native async (SSE chat streaming requires this), Pydantic v2 schemas double as request validation and OpenAPI generation.
- **SQLite vs Postgres**: V1 = zero ops. The `DATABASE_URL` swap to Postgres is a one-line config change when we need it.
- **Subprocess sandbox vs Docker per execution vs Pyodide**: subprocess wins on portability (Windows dev + Linux prod from one code path), startup latency (~400 ms vs ~2–4 s for Docker), and operational simplicity. Pyodide in browser was tempting but you can't run scipy/pandas wheels there in 2026 reliably.
- **Next.js standalone output vs static + separate API**: standalone makes the production container tiny (~120 MB) and lets us serve everything from one nginx upstream pair.
- **DeepSeek vs OpenAI/Anthropic**: DeepSeek is the cheapest credible code generator in the OpenAI-compatible-API category in May 2026. China-friendly too. BYOK lets enterprise customers pick anything else they want.
- **Bcrypt + JWT vs OAuth2/sessions**: solo founder optimization. Add OAuth2 (Google / GitHub) once we have 1 person whose job description includes "auth".

## Failure modes & known limits

- Single-tenant sqlite: no horizontal scaling until we swap to Postgres. Don't run V1 with more than one uvicorn worker process if you stay on SQLite (set `--workers 1`).
- Sandbox is not seccomp-isolated. Don't expose the public Internet to a totally untrusted population without adding seccomp (V2 work).
- Result parquet files live forever on the volume. Add a periodic cleanup job before you have a million runs.
- The chat agent has no tool-call format negotiation — it relies on the model returning valid JSON. DeepSeek and modern Claude/GPT are reliable; older / smaller open models can drift. Fix: add a JSON-repair retry loop or migrate to native tool-calling protocol.
