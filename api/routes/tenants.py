# api/routes/tenants.py
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.dependencies import (
    DB,
    ManageAPIKeysUser,
    ManageRulesUser,
    ManageTenantsUser,
    ReadUser,
    TenantCfg,
)
from api.response_models import (
    APIKeyCreatedResponse,
    APIKeyListItem,
    ConfigUpdatedResponse,
    RuleCreatedResponse,
    RuleHistoryItem,
    RuleListItem,
    RuleRollbackResponse,
    RuleUpdatedResponse,
    TenantResponse,
)
from core.config_engine import (
    EscalationPolicy,
    ModuleConfig,
    PriorityThresholds,
    RateLimitConfig,
    RiskThresholds,
    RiskWeights,
    ToneSettings,
    TenantConfig,
    get_config_engine,
)
from core.rule_engine import validate_condition_group, validate_rule_actions
from database.models import APIKey, User
from database.repositories import RuleRepository, TenantRepository

router = APIRouter(prefix="/tenants", tags=["Tenants"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    plan: Literal["starter", "pro", "enterprise"] = "starter"


class ConfigUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_key: Literal[
        "risk_weights",
        "risk_thresholds",
        "priority_thresholds",
        "escalation_policy",
        "tone_settings",
        "rate_limits",
        "modules",
        "required_case_fields",
    ]
    config_value: Any
    description: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_config_section(self) -> "ConfigUpsert":
        models = {
            "risk_weights": RiskWeights,
            "risk_thresholds": RiskThresholds,
            "priority_thresholds": PriorityThresholds,
            "escalation_policy": EscalationPolicy,
            "tone_settings": ToneSettings,
            "rate_limits": RateLimitConfig,
            "modules": ModuleConfig,
        }
        if self.config_key == "required_case_fields":
            if (
                not isinstance(self.config_value, list)
                or not self.config_value
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in self.config_value
                )
            ):
                raise ValueError("required_case_fields must be a non-empty list of field names")
            self.config_value = [item.strip() for item in self.config_value]
        else:
            model = models[self.config_key].model_validate(self.config_value)
            self.config_value = model.model_dump()
        return self


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    category: Literal["classification", "decision"]
    priority: int = Field(default=100, ge=0, le=100000)
    conditions: dict[str, Any]
    actions: dict[str, Any]
    constraints: Optional[dict[str, Any]] = None
    explanation_template: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("conditions")
    @classmethod
    def validate_conditions(cls, value: dict[str, Any]) -> dict[str, Any]:
        validate_condition_group(value)
        return value

    @model_validator(mode="after")
    def validate_actions_for_category(self) -> "RuleCreate":
        validate_rule_actions(self.actions, self.category)
        return self


class RuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    category: Optional[Literal["classification", "decision"]] = None
    priority: Optional[int] = Field(default=None, ge=0, le=100000)
    conditions: Optional[dict[str, Any]] = None
    actions: Optional[dict[str, Any]] = None
    explanation_template: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("conditions")
    @classmethod
    def validate_conditions(cls, value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if value is not None:
            validate_condition_group(value)
        return value

    @model_validator(mode="after")
    def validate_known_actions(self) -> "RuleUpdate":
        if self.actions is not None:
            # Category-less partial updates are fully checked at evaluation
            # against the stored category; validate their intrinsic shape here.
            validate_rule_actions(
                self.actions,
                self.category or (
                    "classification" if "classification" in self.actions else "decision"
                ),
            )
        return self


class APIKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    expires_at: Optional[datetime] = None

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        if value <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return value


# ---------------------------------------------------------------------------
# Tenant management
# ---------------------------------------------------------------------------

@router.post(
    "/", status_code=status.HTTP_201_CREATED, response_model=TenantResponse
)
async def create_tenant(payload: TenantCreate, current_user: ManageTenantsUser, db: DB):
    raise HTTPException(
        status_code=403,
        detail="Tenant creation is disabled over HTTP; use the local bootstrap command",
    )


@router.get("/me", response_model=TenantResponse)
async def get_my_tenant(current_user: ReadUser, db: DB, config: TenantCfg):
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

@router.post("/me/config", response_model=ConfigUpdatedResponse)
async def upsert_config(payload: ConfigUpsert, current_user: ManageTenantsUser, db: DB):
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


@router.get("/me/config", response_model=TenantConfig)
async def get_config(current_user: ReadUser, config: TenantCfg):
    """Return the full strongly-typed config for this tenant."""
    return config.model_dump()


# ---------------------------------------------------------------------------
# Rule management (versioned)
# ---------------------------------------------------------------------------

@router.get("/me/rules", response_model=list[RuleListItem])
async def list_rules(
    current_user: ReadUser,
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


@router.post(
    "/me/rules", status_code=status.HTTP_201_CREATED,
    response_model=RuleCreatedResponse,
)
async def create_rule(payload: RuleCreate, current_user: ManageRulesUser, db: DB):
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


@router.put("/me/rules/{rule_id}", response_model=RuleUpdatedResponse)
async def update_rule(rule_id: UUID, payload: RuleUpdate, current_user: ManageRulesUser, db: DB):
    """Creates a new version of the rule (old version is closed, not deleted)."""
    rule_id = str(rule_id)
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


@router.post(
    "/me/rules/{rule_id}/rollback", response_model=RuleRollbackResponse
)
async def rollback_rule(
    rule_id: UUID,
    target_version: Annotated[int, Query(ge=1, le=1_000_000)],
    current_user: ManageRulesUser,
    db: DB,
):
    """Roll back a rule to a specific historical version."""
    rule_id = str(rule_id)
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


@router.get(
    "/me/rules/{rule_id}/history", response_model=list[RuleHistoryItem]
)
async def get_rule_history(rule_id: UUID, current_user: ReadUser, db: DB):
    rule_id = str(rule_id)
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
async def deactivate_rule(rule_id: UUID, current_user: ManageRulesUser, db: DB):
    rule_id = str(rule_id)
    repo = RuleRepository(db, str(current_user.tenant_id))
    ok = await repo.deactivate(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.commit()


# ---------------------------------------------------------------------------
# API Key management
# ---------------------------------------------------------------------------

@router.post(
    "/me/api-keys", status_code=status.HTTP_201_CREATED,
    response_model=APIKeyCreatedResponse,
)
async def create_api_key(payload: APIKeyCreate, current_user: ManageAPIKeysUser, db: DB):
    raw_key = f"uraki_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:8]

    api_key = APIKey(
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
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


@router.get("/me/api-keys", response_model=list[APIKeyListItem])
async def list_api_keys(current_user: ManageAPIKeysUser, db: DB):
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
async def revoke_api_key(key_id: UUID, current_user: ManageAPIKeysUser, db: DB):
    key_id = str(key_id)
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
