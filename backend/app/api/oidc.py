"""OIDC login routes — delegate auth to the 统一认证中心, then mint this app's JWT.

Flow (Authorization Code + PKCE, all standard OIDC):
  GET /api/auth/oidc/login     → 302 to the auth center's /authorize
  GET /api/auth/oidc/callback  → exchange code, verify id_token, find-or-create a
                                 local user keyed by `sub`, mint our JWT, and 302
                                 back into the SPA delivering the JWT in the URL
                                 fragment (so it never hits server logs).
  GET /api/auth/oidc/logout    → clear session + 302 to the auth center end-session
  GET /api/auth/oidc/config    → {enabled} so the login page can show the SSO button

Gated on settings.oidc_enabled. When disabled every route 404/short-circuits and
the app keeps using local email/password login.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.oidc import end_session_url, get_provider
from ..core.security import create_access_token
from ..db.models import User
from ..services.datasets import seed_examples_for_user
from .deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/oidc", tags=["auth", "oidc"])


def _require_enabled() -> None:
    if not get_settings().oidc_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OIDC is not enabled")


@router.get("/config")
async def oidc_config():
    """Public: lets the login page decide whether to show the SSO button."""
    return {"enabled": get_settings().oidc_enabled}


@router.get("/login")
async def oidc_login(request: Request):
    """Kick off the browser redirect to the auth center."""
    _require_enabled()
    settings = get_settings()
    provider = get_provider()
    # Explicit redirect_uri is the reliable choice behind a reverse proxy / SPA
    # rewrite; falls back to request-derived only when not configured.
    redirect_uri = settings.oidc_redirect_uri or str(request.url_for("oidc_callback"))
    return await provider.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="oidc_callback")
async def oidc_callback(request: Request, session: AsyncSession = Depends(get_db)):
    """Auth center redirects here with ?code&state. Exchange + provision + mint JWT."""
    _require_enabled()
    provider = get_provider()
    try:
        # Completes token exchange + id_token signature/nonce verification.
        token = await provider.authorize_access_token(request)
    except Exception as e:  # noqa: BLE001 — surface as a clean login error, not a 500
        logger.warning("OIDC callback token exchange failed: %s: %s", type(e).__name__, e)
        return RedirectResponse(url="/login?error=" + quote("登录失败,请重试", safe=""))

    claims = token.get("userinfo")
    if not claims:
        try:
            claims = await provider.userinfo(token=token)
        except Exception:  # noqa: BLE001
            claims = {}
    sub = (claims or {}).get("sub")
    if not sub:
        return RedirectResponse(url="/login?error=" + quote("认证中心未返回用户标识", safe=""))

    email = (claims.get("email") or "").strip()
    name = (claims.get("name") or "").strip()
    is_admin = bool(claims.get("is_admin", False))

    user = await _find_or_create_user(session, sub=sub, email=email, name=name, is_admin=is_admin)

    # Mint THIS app's JWT (subject = local integer user id) so Bearer auth and all
    # owner_id FKs keep working untouched.
    app_token = create_access_token(str(user.id))
    next_path = get_settings().oidc_post_login_path or "/app"
    # Deliver the JWT via the URL fragment — the SPA receiver reads it client-side;
    # fragments are not sent to servers/proxies, so it stays out of access logs.
    return RedirectResponse(url=f"/auth/callback#token={app_token}&next={quote(next_path, safe='/')}")


@router.get("/logout")
async def oidc_logout(request: Request):
    """Single logout: clear our session, then bounce to the auth center end-session,
    asking it to return the browser to the product home."""
    _require_enabled()
    try:
        request.session.clear()
    except Exception:  # noqa: BLE001 — SessionMiddleware may be absent if misconfigured
        pass
    end = await end_session_url()
    if not end:
        return RedirectResponse(url="/login")
    settings = get_settings()
    # post_logout_redirect_uri must be a registered same-origin address; derive the
    # product root from the configured redirect_uri.
    home = ""
    ru = settings.oidc_redirect_uri
    if ru:
        from urllib.parse import urlsplit, urlunsplit
        p = urlsplit(ru)
        if p.netloc:
            home = urlunsplit((p.scheme, p.netloc, "/", "", ""))
    if home:
        sep = "&" if "?" in end else "?"
        end = end + sep + "post_logout_redirect_uri=" + quote(home, safe="")
    return RedirectResponse(url=end)


async def _find_or_create_user(
    session: AsyncSession, *, sub: str, email: str, name: str, is_admin: bool
) -> User:
    """Resolve the local user for an auth-center identity.

    Priority: match by `oidc_sub` (stable cross-product id) → else link an existing
    local account with the same email → else provision a fresh OIDC user (+ seed
    examples). Identity fields are refreshed from the id_token on every login.
    """
    user = (await session.execute(select(User).where(User.oidc_sub == sub))).scalar_one_or_none()
    seeded = True
    if user is None and email:
        # Link a pre-existing local account (same email) to this OIDC subject.
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is not None:
            user.oidc_sub = sub
    if user is None:
        user = User(
            email=email or f"{sub}@oidc.local",
            name=name,
            password_hash="",  # OIDC-managed: no local password
            is_admin=is_admin,
            oidc_sub=sub,
        )
        session.add(user)
        seeded = False
    else:
        # Keep identity in sync with the authoritative auth center.
        if email:
            user.email = email
        if name:
            user.name = name
        user.is_admin = is_admin

    await session.commit()
    await session.refresh(user)

    if not seeded:
        try:
            await seed_examples_for_user(session, user.id)
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
    return user
