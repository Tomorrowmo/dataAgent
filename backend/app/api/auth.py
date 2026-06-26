from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import create_access_token, hash_password, verify_password
from ..db.models import User
from ..services.datasets import seed_examples_for_user
from .deps import current_user, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=200)
    name: str = ""


class LoginReq(BaseModel):
    email: EmailStr
    password: str


class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    name: str


class MeResp(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool
    has_llm_key: bool
    llm_base_url: str = ""
    llm_model: str = ""


class SaveKeyReq(BaseModel):
    api_key: str = Field(default="", description="LLM provider key (Bearer). Empty clears it.")
    base_url: str = Field(default="", description="OpenAI-compatible endpoint. Empty falls back to server .env.")
    model: str = Field(default="", description="Model name. Empty falls back to server .env.")


@router.post("/signup", response_model=TokenResp)
async def signup(body: SignupReq, session: AsyncSession = Depends(get_db)):
    existing = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = User(email=body.email, name=body.name, password_hash=hash_password(body.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    # Seed a standard set of example datasets so a brand-new account isn't empty.
    try:
        await seed_examples_for_user(session, user.id)
        await session.commit()
    except Exception:
        await session.rollback()
    token = create_access_token(str(user.id))
    return TokenResp(access_token=token, user_id=user.id, email=user.email, name=user.name)


@router.post("/login", response_model=TokenResp)
async def login(body: LoginReq, session: AsyncSession = Depends(get_db)):
    user = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    token = create_access_token(str(user.id))
    return TokenResp(access_token=token, user_id=user.id, email=user.email, name=user.name)


@router.get("/me", response_model=MeResp)
async def me(user: User = Depends(current_user)):
    return MeResp(
        id=user.id, email=user.email, name=user.name,
        is_admin=user.is_admin, has_llm_key=bool(user.llm_api_key),
        llm_base_url=user.llm_base_url or "",
        llm_model=user.llm_model or "",
    )


@router.put("/llm-key")
async def save_key(
    body: SaveKeyReq,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    user.llm_api_key = body.api_key.strip() or None
    user.llm_base_url = body.base_url.strip() or None
    user.llm_model = body.model.strip() or None
    await session.commit()
    return {
        "ok": True,
        "has_llm_key": bool(user.llm_api_key),
        "llm_base_url": user.llm_base_url or "",
        "llm_model": user.llm_model or "",
    }
