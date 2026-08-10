from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "dev"
    secret_key: str = "dev-only-secret-please-override"
    access_token_expires_minutes: int = 60 * 24 * 7

    database_url: str = "sqlite+aiosqlite:///./data/db/app.db"
    upload_dir: str = "./data/uploads"

    # First-run admin bootstrap. When both are set and no user with this email
    # exists yet, an is_admin=True account is created on startup. Lets a packaged
    # build ship with a ready admin (the package's DB is otherwise empty). Empty
    # values (the default) disable bootstrap entirely.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_admin_name: str = "Admin"

    # ── OIDC (统一认证中心 / MCLink Cortex auth_server) ───────────────────────
    # When enabled, login is delegated to the auth center (Authorization Code +
    # PKCE). The backend exchanges the code, reads identity from the id_token
    # (sub/email/name/is_admin), find-or-creates a local user keyed by `sub`, and
    # mints THIS app's own JWT — so the rest of the app (Bearer auth, owner_id FKs)
    # is unchanged. Disabled by default → falls back to local email/password.
    oidc_enabled: bool = False
    # Backend's address to reach the auth center for discovery / token exchange.
    # Same machine → http://localhost:6001 saves a hop; cross-machine → public https.
    oidc_issuer: str = "https://auth.romtekcae.com:5000"
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    # Must EXACTLY match the callback registered at the auth center admin, and be
    # an address the browser can reach (in this SPA setup it goes through the
    # frontend origin, which proxies /api to the backend), e.g.
    #   https://你的产品域名/api/auth/oidc/callback
    oidc_redirect_uri: str = ""
    # Where to land in the SPA after a successful login (frontend route).
    oidc_post_login_path: str = "/app"

    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    # `deepseek-chat` / `deepseek-reasoner` are deprecated 2026-07-24 15:59 UTC;
    # both fold into deepseek-v4-flash (non-thinking / thinking mode).
    deepseek_model: str = "deepseek-v4-flash"

    sandbox_cpu_seconds: int = 10
    sandbox_memory_mb: int = 512
    sandbox_timeout_seconds: int = 30
    sandbox_max_output_bytes: int = 10 * 1024 * 1024

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
