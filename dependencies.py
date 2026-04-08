# api/dependencies.py
"""
FastAPI dependency injection:
  - get_db             → AsyncSession per request
  - get_current_user   → JWT or API key authentication
  - get_tenant_config  → TenantConfig loaded & cached per request
  - require_permission → RBAC enforcement
  - get_event_bus      → singleton EventBus
"""
import hashlib
import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from core.config_engine import ConfigEngine, TenantConfig, get_config_engine
from core.event_bus import EventBus, get_event_bus
from database.base import get_db
from database.models import APIKey, User

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Auth schemes
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "read", "write", "delete", "override",
        "manage_rules", "manage_tenants", "manage_api_keys",
        "view_executive", "escalate",
    },
    "operador": {"read", "write", "override"},
    "legal": {"read", "write", "escalate"},
    "ejecutivo": {"read", "view_executive"},
}


# ---------------------------------------------------------------------------
# User resolution — JWT
# ---------------------------------------------------------------------------

async def _user_from_jwt(token: str, db: AsyncSession) -> Optional[User]:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub", "")
        tenant_id: str = payload.get("tenant_id", "")
        if not user_id or not tenant_id:
            return None
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError:
        return None

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# User resolution — API Key
# ---------------------------------------------------------------------------

def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def _user_from_api_key(raw_key: str, db: AsyncSession) -> Optional[User]:
    key_hash = _hash_api_key(raw_key)

    result = await db.execute(
        select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.is_active.is_(True),
        )
    )
    api_key_record = result.scalar_one_or_none()
    if not api_key_record:
        return None

    # Check expiry
    if api_key_record.expires_at and api_key_record.expires_at < datetime.now(timezone.utc):
        return None

    # Update last_used_at (fire-and-forget; don't block the request)
    api_key_record.last_used_at = datetime.now(timezone.utc)

    # Load the tenant's admin user as the "identity" for API key requests
    # In production, link APIKey → User directly instead.
    result2 = await db.execute(
        select(User).where(
            User.tenant_id == api_key_record.tenant_id,
            User.role == "admin",
            User.is_active.is_(True),
        ).limit(1)
    )
    return result2.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Core dependency: get_current_user
# ---------------------------------------------------------------------------

async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    api_key: Annotated[Optional[str], Security(api_key_header)] = None,
) -> User:
    user: Optional[User] = None

    if token:
        user = await _user_from_jwt(token, db)

    if user is None and api_key:
        user = await _user_from_api_key(api_key, db)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials. Provide Bearer token or X-API-Key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# ---------------------------------------------------------------------------
# Tenant config dependency (cached per request via ConfigEngine)
# ---------------------------------------------------------------------------

async def get_tenant_config(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantConfig:
    engine: ConfigEngine = get_config_engine()
    return await engine.load(str(current_user.tenant_id), db)


# ---------------------------------------------------------------------------
# RBAC dependency factory
# ---------------------------------------------------------------------------

def require_permission(permission: str):
    async def check(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        allowed = ROLE_PERMISSIONS.get(current_user.role, set())
        if permission not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' lacks permission '{permission}'",
            )
        return current_user
    return check


# ---------------------------------------------------------------------------
# Convenience type aliases
# ---------------------------------------------------------------------------
DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
TenantCfg = Annotated[TenantConfig, Depends(get_tenant_config)]
Bus = Annotated[EventBus, Depends(get_event_bus)]
