# api/routes/tenants.py
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.dependencies import DB, CurrentUser, TenantCfg
from core.config_engine import get_config_engine
from database.models import APIKey, User
from database.repositories import RuleRepository, TenantRepository

router = APIRouter(prefix="/tenants", tags=["Tenants"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TenantCreate(BaseModel):
    name: str
    slug: str
    plan: str = "starter"


class ConfigUpsert(BaseModel):
    config_key: str
    config_value: Any
    description: Optional[str] = None


class RuleCreate(BaseModel):
    name: str
    category: str
    priority: int = 100
    conditions: dict[str, Any]
    actions: dict[str, Any]
    constraints: Optional[dict[str, Any]] = None
    explanation_template: Optional[str] = None


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[int] = None
    conditions: Optional[dict[str, Any]] = None
    actions: Optional[dict[str, Any]] = None
    explanation_template: Optional[str] = None


class APIKeyCreate(BaseModel):
    name: str
    expires_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Tenant management
# ---------------------------------------------------------------------------

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_tenant(payload: TenantCreate, current_user: CurrentUser, db: DB):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create tenants")
    repo = TenantRepository(db)
    if await repo.get_by_slug(payload.slug):
        raise HTTPException(status_code=409, detail="Slug already exists")
    tenant = await repo.create(name=payload.name, slug=payload.slug, plan=payload.plan)
    await db.commit()
    return {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug}


@router.get("/me")
async def get_my_tenant(current_user: CurrentUser, db: DB, config: TenantCfg):
    repo = TenantRepository(db)
    tenant = await repo.get_by_id(str(current_user.tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "plan": tenant.plan,
        "config": config.model_dump(),
    }


# ---------------------------------------------------------------------------
# Configuration management
# ---------------------------------------------------------------------------

@router.post("/me/config")
async def upsert_config(payload: ConfigUpsert, current_user: CurrentUser, db: DB):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can modify config")

    repo = TenantRepository(db)
    await repo.set_config(
        tenant_id=str(current_user.tenant_id),
        config_key=payload.config_key,
        config_value=payload.config_value,
        description=payload.description or "",
    )
    await db.commit()

    # Invalidate config cache so next request picks up new values
    get_config_engine().invalidate(str(current_user.tenant_id))

    return {"message": "Configuration updated", "key": payload.config_key}


@router.get("/me/config")
async def get_config(current_user: CurrentUser, config: TenantCfg):
    """Return the full strongly-typed config for this tenant."""
    return config.model_dump()


# ---------------------------------------------------------------------------
# Rule management (versioned)
# ---------------------------------------------------------------------------

@router.get("/me/rules")
async def list_rules(
    current_user: CurrentUser,
    db: DB,
    include_history: bool = False,
):
    repo = RuleRepository(db, str(current_user.tenant_id))
    rules = await repo.list_rules(include_history=include_history)
    return [
        {
            "id": str(r.id),
            "parent_rule_id": str(r.parent_rule_id) if r.parent_rule_id else None,
            "name": r.name,
            "category": r.category,
            "priority": r.priority,
            "version": r.version,
            "is_active": r.is_active,
            "effective_from": r.effective_from.isoformat() if r.effective_from else None,
            "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            "conditions": r.conditions,
            "actions": r.actions,
        }
        for r in rules
    ]


@router.post("/me/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(payload: RuleCreate, current_user: CurrentUser, db: DB):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create rules")
    repo = RuleRepository(db, str(current_user.tenant_id))
    rule = await repo.create(payload.model_dump(exclude_none=True))
    await db.commit()
    return {
        "id": str(rule.id),
        "name": rule.name,
        "category": rule.category,
        "version": rule.version,
        "effective_from": rule.effective_from.isoformat(),
    }


@router.put("/me/rules/{rule_id}")
async def update_rule(rule_id: str, payload: RuleUpdate, current_user: CurrentUser, db: DB):
    """Creates a new version of the rule (old version is closed, not deleted)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update rules")
    repo = RuleRepository(db, str(current_user.tenant_id))
    try:
        new_version = await repo.update(rule_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {
        "id": str(new_version.id),
        "name": new_version.name,
        "version": new_version.version,
        "effective_from": new_version.effective_from.isoformat(),
        "parent_rule_id": str(new_version.parent_rule_id),
    }


@router.post("/me/rules/{rule_id}/rollback")
async def rollback_rule(rule_id: str, target_version: int, current_user: CurrentUser, db: DB):
    """Roll back a rule to a specific historical version."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can rollback rules")
    repo = RuleRepository(db, str(current_user.tenant_id))
    try:
        rolled_back = await repo.rollback(rule_id, target_version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return {
        "id": str(rolled_back.id),
        "name": rolled_back.name,
        "version": rolled_back.version,
        "message": f"Rolled back to v{target_version} logic as new v{rolled_back.version}",
    }


@router.get("/me/rules/{rule_id}/history")
async def get_rule_history(rule_id: str, current_user: CurrentUser, db: DB):
    repo = RuleRepository(db, str(current_user.tenant_id))
    history = await repo.get_version_history(rule_id)
    return [
        {
            "id": str(r.id),
            "version": r.version,
            "is_active": r.is_active,
            "effective_from": r.effective_from.isoformat() if r.effective_from else None,
            "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        }
        for r in history
    ]


@router.delete("/me/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_rule(rule_id: str, current_user: CurrentUser, db: DB):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can deactivate rules")
    repo = RuleRepository(db, str(current_user.tenant_id))
    ok = await repo.deactivate(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.commit()


# ---------------------------------------------------------------------------
# API Key management
# ---------------------------------------------------------------------------

@router.post("/me/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: APIKeyCreate, current_user: CurrentUser, db: DB):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create API keys")

    raw_key = f"uraki_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:12]

    api_key = APIKey(
        tenant_id=str(current_user.tenant_id),
        name=payload.name,
        key_prefix=prefix,
        key_hash=key_hash,
        expires_at=payload.expires_at,
    )
    db.add(api_key)
    await db.commit()

    # Return raw key ONCE — never stored in plain text
    return {
        "id": str(api_key.id),
        "name": api_key.name,
        "key": raw_key,  # shown only once
        "prefix": prefix,
        "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
        "warning": "Store this key securely. It will not be shown again.",
    }


@router.get("/me/api-keys")
async def list_api_keys(current_user: CurrentUser, db: DB):
    from sqlalchemy import select
    result = await db.execute(
        select(APIKey).where(
            APIKey.tenant_id == str(current_user.tenant_id),
            APIKey.is_active.is_(True),
        )
    )
    keys = result.scalars().all()
    return [
        {
            "id": str(k.id),
            "name": k.name,
            "prefix": k.key_prefix,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "created_at": k.created_at.isoformat(),
        }
        for k in keys
    ]


@router.delete("/me/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: str, current_user: CurrentUser, db: DB):
    from sqlalchemy import select
    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.tenant_id == str(current_user.tenant_id),
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.is_active = False
    await db.commit()
