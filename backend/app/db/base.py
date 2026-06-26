from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ..core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# Ensure sqlite file directory exists before sqlalchemy tries to open it.
if _settings.database_url.startswith("sqlite"):
    # database_url example: sqlite+aiosqlite:///./data/db/app.db
    _db_path = _settings.database_url.split("///", 1)[-1]
    Path(_db_path).resolve().parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    # Import models so they register with the metadata before create_all.
    from . import models  # noqa: F401
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Tiny inline migration so existing sqlite databases pick up new
        # columns without Alembic. Postgres deploys should use a real
        # migration tool instead.
        if _settings.database_url.startswith("sqlite"):
            def _existing_cols(sync_conn, table: str) -> set[str]:
                rows = sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                return {r[1] for r in rows}

            user_cols = await conn.run_sync(_existing_cols, "users")
            for col_name, ddl in (
                ("llm_base_url", "ALTER TABLE users ADD COLUMN llm_base_url VARCHAR(512)"),
                ("llm_model",    "ALTER TABLE users ADD COLUMN llm_model VARCHAR(120)"),
            ):
                if col_name not in user_cols:
                    await conn.execute(text(ddl))

            # Derived-dataset lineage columns (added to existing datasets tables).
            ds_cols = await conn.run_sync(_existing_cols, "datasets")
            for col_name, ddl in (
                ("kind",         "ALTER TABLE datasets ADD COLUMN kind VARCHAR(16) DEFAULT 'source'"),
                ("derived_from", "ALTER TABLE datasets ADD COLUMN derived_from INTEGER"),
                ("lineage",      "ALTER TABLE datasets ADD COLUMN lineage JSON DEFAULT '{}'"),
                # Auto-GC pin (kept derived datasets survive the sweep).
                ("kept",         "ALTER TABLE datasets ADD COLUMN kept BOOLEAN DEFAULT 0"),
            ):
                if col_name not in ds_cols:
                    await conn.execute(text(ddl))

            # Cross-turn pipeline state on conversations.
            conv_cols = await conn.run_sync(_existing_cols, "conversations")
            if "pipeline_state" not in conv_cols:
                await conn.execute(text("ALTER TABLE conversations ADD COLUMN pipeline_state JSON DEFAULT '{}'"))

            # Free-form canvas layout on flow_templates.
            tpl_cols = await conn.run_sync(_existing_cols, "flow_templates")
            if "graph" not in tpl_cols:
                await conn.execute(text("ALTER TABLE flow_templates ADD COLUMN graph JSON DEFAULT '{}'"))

            # Screenshot path on feedback (added after the feedback table shipped).
            def _table_exists(sync_conn, table: str) -> bool:
                return bool(sync_conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"), {"t": table}
                ).fetchone())
            if await conn.run_sync(_table_exists, "feedback"):
                fb_cols = await conn.run_sync(_existing_cols, "feedback")
                if "screenshot" not in fb_cols:
                    await conn.execute(text("ALTER TABLE feedback ADD COLUMN screenshot VARCHAR(1024)"))

            # format_adapters / flow_templates tables — created via create_all
            # above; no inline migration needed beyond that. (Kept the hook here
            # in case future columns are added.)


async def bootstrap_admin() -> None:
    """Create the configured admin account on first run (idempotent).

    A packaged build ships with an EMPTY database (the packaging script excludes
    backend/data/), so without this there is no way to log in until someone
    registers a plain user and hand-edits is_admin. When BOOTSTRAP_ADMIN_EMAIL /
    BOOTSTRAP_ADMIN_PASSWORD are set (via the shipped .env), this seeds a ready
    admin. Runs every startup but only inserts when the account is missing.
    """
    email = (_settings.bootstrap_admin_email or "").strip().lower()
    password = _settings.bootstrap_admin_password or ""
    if not email or not password:
        return

    from sqlalchemy import select
    from .models import User
    from ..core.security import hash_password
    from ..services.datasets import seed_examples_for_user

    async with SessionLocal() as session:
        existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            return
        user = User(
            email=email,
            name=(_settings.bootstrap_admin_name or "Admin").strip(),
            password_hash=hash_password(password),
            is_admin=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        # Mirror signup: a fresh admin shouldn't land in an empty workspace.
        try:
            await seed_examples_for_user(session, user.id)
            await session.commit()
        except Exception:
            await session.rollback()
