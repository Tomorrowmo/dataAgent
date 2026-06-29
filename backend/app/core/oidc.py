"""OIDC client wiring for the 统一认证中心 (MCLink Cortex auth_server).

This product is a FastAPI + SPA app, not a server-rendered Flask app, so we adapt
the reference Flask/Authlib integration: OIDC happens at the backend edge
(Authorization Code + PKCE), and on success we mint THIS app's own JWT. The rest
of the app keeps using Bearer-JWT auth and integer `owner_id` FKs unchanged.

Everything here is lazy + gated on settings.oidc_enabled: when disabled, nothing
is registered and the app behaves exactly as before (local email/password login).
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from .config import get_settings

# The Authlib Starlette client. Imported lazily so the dependency is only needed
# when OIDC is actually enabled (keeps `authlib` optional for local-only builds).
_oauth = None
_PROVIDER = "idp"


def init_oidc() -> None:
    """Register the auth-center provider. Safe to call once at startup; no-op when
    OIDC is disabled. Discovery (.well-known) is fetched lazily on first use."""
    global _oauth
    settings = get_settings()
    if not settings.oidc_enabled:
        return
    if _oauth is not None:
        return
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name=_PROVIDER,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid profile email",
            "code_challenge_method": "S256",  # PKCE (S256) — required by the auth center
            "token_endpoint_auth_method": "client_secret_basic",
        },
    )
    _oauth = oauth


def get_provider():
    """The registered auth-center OAuth client, or raise if OIDC isn't ready."""
    if _oauth is None:
        init_oidc()
    if _oauth is None:
        raise RuntimeError("OIDC is not enabled / not configured")
    return getattr(_oauth, _PROVIDER)


async def end_session_url() -> Optional[str]:
    """Public end-session endpoint for single logout — taken from discovery, NOT
    built from OIDC_ISSUER (which may be a localhost backend-direct address and
    would send the browser to localhost). Returns None if it can't be resolved."""
    try:
        provider = get_provider()
        md = await provider.load_server_metadata()
        end = md.get("end_session_endpoint")
        if end:
            return end
        # Fall back to <authorization host>/logout if no explicit end_session.
        a = urlsplit(md.get("authorization_endpoint", ""))
        if a.netloc:
            return urlunsplit((a.scheme, a.netloc, "/logout", "", ""))
    except Exception:
        pass
    settings = get_settings()
    base = (settings.oidc_issuer or "").rstrip("/")
    return base + "/logout" if base else None
