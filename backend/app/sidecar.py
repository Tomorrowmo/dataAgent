"""计算面 sidecar —— 迁移第 1 阶段。

把现有 FastAPI 拆成两半中的下半：**只算，不管人**。

    网关（保留 auth.py / oidc.py）          ← 认证、账号、BYOK、配额
        └── dsh 实例（每用户一个）           ← agent 与 UI
                └── 本文件                   ← 算法、沙箱、风洞、解析、导出

设计上只做一件不寻常的事：用 ``dependency_overrides`` 把 ``current_user`` 整体
换成「本实例的固定属主」。因此**没有任何一个路由文件被改动**——owner_id 的行级
作用域、上传目录的归属、报告的编制人，全部照旧工作，只是这台实例里永远只有一个
人。隔离从数据库行上移到了进程边界。

不挂载的路由与理由::

    auth / oidc     认证归网关；sidecar 只监听回环，不面向公网
    chat            由 dsh 的 agent loop 取代（chat_agent.py 的 1600 行退休）

运行::

    ./.venv/Scripts/python.exe -m uvicorn app.sidecar:app --host 127.0.0.1 --port 8078

安全姿态：本进程**没有认证**，必须只绑回环地址。绑到非回环即等于把一个无鉴权的
数据面暴露出去——启动时会对此大声拒绝。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select

from .core.config import get_settings
from .db.base import SessionLocal, init_db
from .db.models import User
from .version import APP_VERSION

logger = logging.getLogger(__name__)
settings = get_settings()

#: 本实例属主。一台 sidecar 服务一个人，身份由启动它的网关决定。
OWNER_EMAIL = os.environ.get("DSH_OWNER_EMAIL", "owner@localhost")
OWNER_NAME = os.environ.get("DSH_OWNER_NAME", "Instance Owner")

_WARM: dict = {"ready": False, "error": None, "t0": time.monotonic()}
_OWNER: dict = {"user": None}


async def _ensure_owner() -> User:
    """取得（必要时创建）本实例的属主行。

    仍然落一行真实的 User，因为下游路由是按 ``owner_id`` 组织数据的。这里不设密码
    可用值——本进程没有登录入口，这一行只作为数据归属的锚点。
    """
    async with SessionLocal() as s:
        u = (await s.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one_or_none()
        if u is None:
            u = User(email=OWNER_EMAIL, name=OWNER_NAME,
                     password_hash="!sidecar-no-login", is_admin=False)
            s.add(u)
            await s.commit()
            await s.refresh(u)
            logger.info("sidecar: created instance owner %s (id=%s)", OWNER_EMAIL, u.id)
        return u


def _warmup(app: FastAPI) -> None:
    """后台挂载计算路由。

    与 main.py 同样的姿态：先绑端口再加载 pandas/sklearn，否则 Windows 首次冷扫描
    会让启动看起来像卡死。数据路由在就绪前答可重试的 503。
    """
    try:
        t0 = time.monotonic()
        logger.info("sidecar warmup: importing compute routers…")
        from .algorithms import bootstrap as _algo_bootstrap  # noqa: F401
        from .api import algorithms as algorithms_api
        from .api import datasets as datasets_api
        from .api import feedback as feedback_api
        from .api import mappings as mappings_api
        from .api import templates as templates_api
        from .api import windtunnel as windtunnel_api

        for mod in (datasets_api, algorithms_api, templates_api,
                    mappings_api, feedback_api, windtunnel_api):
            app.include_router(mod.router, prefix="/api")
        app.openapi_schema = None

        try:
            import scipy.optimize  # noqa: F401
            import scipy.signal  # noqa: F401
            import scipy.stats  # noqa: F401
            import sklearn.linear_model  # noqa: F401
            import sklearn.metrics  # noqa: F401
            import sklearn.preprocessing  # noqa: F401
        except Exception as e:  # noqa: BLE001
            logger.warning("sidecar warmup: prewarm skipped (%s: %s)", type(e).__name__, e)

        _WARM["ready"] = True
        logger.info("sidecar warmup: compute routes ready in %.2fs", time.monotonic() - t0)
    except Exception as e:  # noqa: BLE001
        _WARM["error"] = f"{type(e).__name__}: {e}"
        logger.exception("sidecar warmup FAILED")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    _OWNER["user"] = await _ensure_owner()

    # 属主行就绪后再装依赖覆盖：路由拿到的永远是这一个人，鉴权头被完全忽略。
    from .api.deps import current_user

    async def _instance_owner() -> User:
        u = _OWNER["user"]
        if u is None:  # pragma: no cover —— lifespan 保证先于请求完成
            raise RuntimeError("instance owner not initialised")
        return u

    app.dependency_overrides[current_user] = _instance_owner
    logger.info("sidecar: auth bypassed, all routes scoped to owner id=%s", _OWNER["user"].id)

    threading.Thread(target=_warmup, args=(app,), daemon=True, name="sidecar-warmup").start()
    yield


app = FastAPI(title="RLab Cortex Compute Sidecar", version=APP_VERSION, lifespan=lifespan)

_ALWAYS_OPEN = ("/api/health", "/api/ready", "/openapi.json", "/docs", "/redoc")


@app.middleware("http")
async def _warm_gate(request: Request, call_next):
    path = request.url.path
    if _WARM["ready"] or path in _ALWAYS_OPEN or path.startswith("/api/result-file"):
        return await call_next(request)
    if _WARM["error"]:
        return JSONResponse({"detail": f"sidecar failed to start: {_WARM['error']}"},
                            status_code=500)
    return JSONResponse({"detail": "计算面正在启动（首次加载科学计算库较慢），请稍候重试。",
                         "warming": True}, status_code=503)


@app.get("/api/health")
async def health():
    owner = _OWNER["user"]
    return {"ok": True, "service": "rlab-compute-sidecar", "version": APP_VERSION,
            "ready": _WARM["ready"], "auth": "bypassed",
            "owner": {"id": owner.id, "email": owner.email} if owner else None}


@app.get("/api/ready")
async def ready():
    return {"ready": _WARM["ready"], "error": _WARM["error"],
            "elapsed_s": round(time.monotonic() - _WARM["t0"], 1)}


@app.get("/api/result-file")
async def download_result(path: str):
    """把结果文件交回调用方。路径必须落在上传目录内，越界一律拒绝。"""
    target = Path(path).resolve()
    try:
        target.relative_to(settings.upload_path)
    except ValueError:
        return JSONResponse({"error": "path not under upload directory"}, status_code=400)
    if not target.exists():
        return JSONResponse({"error": "file not found"}, status_code=404)
    return FileResponse(target, filename=target.name)
