import asyncio
import logging
import logging.handlers
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path


def _install_file_logging() -> None:
    """If BACKEND_LOG_FILE is set, mirror everything (uvicorn access + app
    logs + uncaught exceptions) to that file with line-buffered flush.

    Windows note: Start-Process -RedirectStandardOutput buffers writes inside
    the child process, so uvicorn.err.log stays at 0 bytes for minutes — we
    can't debug what we can't see. Python's RotatingFileHandler flushes on
    every emit, so logs appear immediately.

    Called BEFORE the heavy app imports below so the file appears even while
    pandas/sklearn are still loading (Windows AV can stretch first-import to
    a minute+ — invisible without this)."""
    path = os.environ.get("BACKEND_LOG_FILE")
    if not path:
        return
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    handler.setLevel(logging.INFO)

    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    # uvicorn's default config disables propagation on these loggers, so we
    # have to attach the handler directly. They DO propagate when we re-enable
    # it — but that'd double-log via root. Keep propagate=False.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
        lg.propagate = False

    def _hook(exc_type, exc, tb):
        logging.getLogger("unhandled").error(
            "uncaught %s: %s", exc_type.__name__, exc, exc_info=(exc_type, exc, tb)
        )
    sys.excepthook = _hook

    logging.getLogger("boot").info("file logging installed -> %s", log_path)


_install_file_logging()
logger = logging.getLogger(__name__)
_boot_t0 = time.monotonic()
logger.info("importing fastapi + heavy deps…")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .core.config import get_settings
from .db.base import init_db

logger.info("light imports done in %.2fs", time.monotonic() - _boot_t0)

settings = get_settings()

# ── Background warmup ────────────────────────────────────────────────────────
# The heavy, slow imports (pandas/scipy/sklearn pulled in transitively by the
# routers + algorithm registry) are DEFERRED to a background thread, so the
# server binds the port and answers /api/health in ~2 s even when Windows
# Defender cold-scans those packages on first read (which can take many minutes).
#
# This is the real fix for the start-up trap: previously every restart paid the
# full cold-import BEFORE binding, so overlapping launches all cold-imported in
# parallel and then raced to bind (Errno 10048). Now the socket is up instantly;
# data routes answer 503 "warming up" until the thread finishes mounting them.
_WARM: dict = {"ready": False, "error": None, "t0": time.monotonic()}


def _warmup(app: "FastAPI") -> None:
    try:
        t0 = time.monotonic()
        logger.info("warmup: importing routers + heavy deps…")
        from .algorithms import bootstrap as _algo_bootstrap  # noqa: F401  (triggers registration)
        from .api import algorithms as algorithms_api
        from .api import auth as auth_api
        from .api import chat as chat_api
        from .api import datasets as datasets_api
        from .api import templates as templates_api

        app.include_router(auth_api.router, prefix="/api")
        app.include_router(datasets_api.router, prefix="/api")
        app.include_router(algorithms_api.router, prefix="/api")
        app.include_router(chat_api.router, prefix="/api")
        app.include_router(templates_api.router, prefix="/api")
        app.openapi_schema = None  # invalidate cache so the new routes appear in /openapi.json

        # Touch sklearn/scipy too while we're paying the cold-scan cost, so the
        # first PCA / AI-codegen call isn't the one that waits on it.
        try:
            import sklearn.linear_model  # noqa: F401
            import sklearn.metrics  # noqa: F401
            import sklearn.preprocessing  # noqa: F401
            import scipy.optimize  # noqa: F401
            import scipy.signal  # noqa: F401
            import scipy.stats  # noqa: F401
        except Exception as e:  # noqa: BLE001
            logger.warning("warmup: sklearn/scipy prewarm skipped (%s: %s)", type(e).__name__, e)

        _WARM["ready"] = True
        logger.info("warmup: routers ready in %.2fs", time.monotonic() - t0)
    except Exception as e:  # noqa: BLE001
        _WARM["error"] = f"{type(e).__name__}: {e}"
        logger.exception("warmup FAILED")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # init_db is light (no pandas) and the async sqlite engine is loop-bound, so
    # it must run on THIS event loop — keep it here. The slow router imports go to
    # a daemon thread that does pure imports + sync include_router (no loop use),
    # so there's no cross-loop hazard.
    await init_db()
    threading.Thread(target=_warmup, args=(app,), daemon=True, name="warmup").start()
    yield


app = FastAPI(title="Numetrix Data Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths that must work before warmup finishes (no heavy deps needed).
_ALWAYS_OPEN = ("/api/health", "/api/ready", "/openapi.json", "/docs", "/redoc")


@app.middleware("http")
async def _warm_gate(request: Request, call_next):
    """Until warmup mounts the routers, answer data routes with a clear, retryable
    503 instead of a 404 (route not mounted yet) or a hang."""
    path = request.url.path
    if _WARM["ready"] or path in _ALWAYS_OPEN or path.startswith("/api/result-file"):
        return await call_next(request)
    if _WARM["error"]:
        return JSONResponse({"detail": f"backend failed to start: {_WARM['error']}"}, status_code=500)
    return JSONResponse(
        {"detail": "后端正在启动(首次加载科学计算库可能较慢),请稍候重试。", "warming": True},
        status_code=503,
    )


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "numetrix-api", "version": "0.1.0", "ready": _WARM["ready"]}


@app.get("/api/ready")
async def ready():
    """Warmup progress — the frontend / launcher polls this to know when the
    data routes are live."""
    return {
        "ready": _WARM["ready"],
        "error": _WARM["error"],
        "elapsed_s": round(time.monotonic() - _WARM["t0"], 1),
    }


@app.get("/api/result-file")
async def download_result(path: str):
    """Serve a parquet/CSV result back to the browser. The path must live under
    the configured upload directory — anything else is rejected."""
    upload_root = settings.upload_path
    target = Path(path).resolve()
    try:
        target.relative_to(upload_root)
    except ValueError:
        return JSONResponse({"error": "path not under upload directory"}, status_code=400)
    if not target.exists():
        return JSONResponse({"error": "file not found"}, status_code=404)
    return FileResponse(target, filename=target.name)
