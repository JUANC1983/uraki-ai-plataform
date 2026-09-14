# api/routes/auth.py
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select

from api.dependencies import DB, CurrentUser
from api.response_models import UserResponse
from config.settings import get_settings
from core.security import hash_password, validate_password, verify_password
from database.models import Tenant, User

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])


class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    role: str
    tenant_id: str


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "operador", "legal", "ejecutivo"] = "operador"

    @field_validator("password")
    @classmethod
    def password_boundary(cls, value: str) -> str:
        return validate_password(value)


def create_access_token(user: User) -> str:
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
        "email": user.email,
        "iat": issued_at,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    tenant_slug: Annotated[str, Form(min_length=1, max_length=100)],
    db: DB,
):
    normalized_email = form_data.username.strip().lower()
    normalized_slug = tenant_slug.strip().lower()
    result = await db.execute(
        select(User)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            User.email == normalized_email,
            User.is_active.is_(True),
            Tenant.slug == normalized_slug,
            Tenant.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user)
    return Token(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        role=user.role,
        tenant_id=str(user.tenant_id),
    )


@router.post(
    "/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse
)
async def register(payload: UserCreate, current_user: CurrentUser, db: DB):
    """Create a user inside the authenticated administrator's tenant."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can register users")

    tenant_id = str(current_user.tenant_id)
    normalized_email = str(payload.email).strip().lower()
    result = await db.execute(
        select(User).where(User.email == normalized_email, User.tenant_id == tenant_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        tenant_id=tenant_id,
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id), "email": user.email, "role": user.role}
