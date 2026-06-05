from typing import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import decode_token
from ..db.base import SessionLocal
from ..db.models import User
from ..services.llm import LLMClient


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = auth[7:].strip()
    try:
        payload = decode_token(token)
    except Exception as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e
    user_id = int(payload["sub"])
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


def llm_for(user: User) -> LLMClient:
    # User-scoped overrides win over the server-side defaults. Any of
    # api_key / base_url / model can be set independently — leaving one
    # unset falls back to the .env value.
    return LLMClient(
        api_key=user.llm_api_key or None,
        base_url=user.llm_base_url or None,
        model=user.llm_model or None,
    )
