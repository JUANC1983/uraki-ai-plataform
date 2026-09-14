# core/config_engine.py
"""
Configuration Engine — strongly typed per-tenant configuration.

Responsibilities:
  - Parse raw DB key-value config into a typed TenantConfig model
  - Cache per request (inject via FastAPI dependency)
  - Provide defaults for any missing key
  - Expose config to: RiskEngine, RuleEngine, MessageAgent, RateLimiter

Usage:
    config = await ConfigEngine.load(tenant_id, db)
    risk_engine.compute(..., config=config)
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-models (strongly typed sections)
# ---------------------------------------------------------------------------

class RiskWeights(BaseModel):
    """
    Weights for each risk variable. Must sum to 1.0 (normalized internally).
    """
    model_config = ConfigDict(extra="forbid")

    overdue_days: float = Field(0.40, ge=0, le=1)
    economic_impact: float = Field(0.30, ge=0, le=1)
    legal_risk: float = Field(0.20, ge=0, le=1)
    recurrence: float = Field(0.10, ge=0, le=1)

    @model_validator(mode="after")
    def normalize(self) -> "RiskWeights":
        total = self.overdue_days + self.economic_impact + self.legal_risk + self.recurrence
        if total <= 0:
            raise ValueError("At least one risk weight must be greater than zero")
        if abs(total - 1.0) > 0.01:
            self.overdue_days /= total
            self.economic_impact /= total
            self.legal_risk /= total
            self.recurrence /= total
        return self

    def as_dict(self) -> dict[str, float]:
        return {
            "overdue_days": self.overdue_days,
            "economic_impact": self.economic_impact,
            "legal_risk": self.legal_risk,
            "recurrence": self.recurrence,
        }


class RiskThresholdBand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float = Field(..., ge=0)
    max: float = Field(..., le=100)

    @model_validator(mode="after")
    def validate_order(self) -> "RiskThresholdBand":
        if self.min > self.max:
            raise ValueError("Risk threshold min must not exceed max")
        return self


class RiskThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    low: RiskThresholdBand = Field(default_factory=lambda: RiskThresholdBand(min=0, max=30))
    medium: RiskThresholdBand = Field(default_factory=lambda: RiskThresholdBand(min=30, max=70))
    high: RiskThresholdBand = Field(default_factory=lambda: RiskThresholdBand(min=70, max=100))

    @model_validator(mode="after")
    def validate_coverage(self) -> "RiskThresholds":
        if self.low.min != 0 or self.high.max != 100:
            raise ValueError("Risk thresholds must cover scores from 0 through 100")
        if self.medium.min != self.low.max or self.high.min != self.medium.max:
            raise ValueError("Risk threshold bands must be contiguous")
        return self

    def resolve_level(self, score: float) -> str:
        if self.low.min <= score <= self.low.max:
            return "BAJO"
        if self.medium.min <= score <= self.medium.max:
            return "MEDIO"
        return "ALTO"

    def as_dict(self) -> dict[str, dict[str, float]]:
        return {
            "low": {"min": self.low.min, "max": self.low.max},
            "medium": {"min": self.medium.min, "max": self.medium.max},
            "high": {"min": self.high.min, "max": self.high.max},
        }


class PriorityThresholds(BaseModel):
    """Score thresholds for case priority assignment."""
    model_config = ConfigDict(extra="forbid")

    critical: float = Field(85.0, ge=0, le=100)
    high: float = Field(65.0, ge=0, le=100)
    medium: float = Field(40.0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_order(self) -> "PriorityThresholds":
        if not self.medium < self.high < self.critical:
            raise ValueError("Priority thresholds must satisfy medium < high < critical")
        return self


class EscalationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_escalate_days: int = Field(90, ge=1)           # escalate after N overdue days
    legal_threshold_days: int = Field(60, ge=1)          # legal flag after N days
    policy_threshold_months: float = Field(3.0, ge=0)   # policy activates at N months of rent owed
    escalation_targets: dict[str, str] = Field(
        default_factory=lambda: {
            "legal": "legal_team",
            "policy": "insurance_team",
            "gerencia": "management",
        }
    )

    def resolve_target(self, flag: str) -> str:
        return self.escalation_targets.get(flag, "management")


class ToneSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: Literal["suave", "profesional", "firme", "urgente", "neutral", "legal"] = "profesional"
    language: str = Field(default="es", min_length=2, max_length=10)
    company_name: str = Field(default="", max_length=200)
    signature: str = Field(default="", max_length=1000)
    use_formal_address: bool = True    # "usted" vs "tú"
    max_message_length: int = Field(default=500, ge=50, le=10000)

    def to_prompt_context(self) -> str:
        parts = [f"Tono: {self.tone}", f"Idioma: {self.language}"]
        if self.company_name:
            parts.append(f"Empresa: {self.company_name}")
        if self.use_formal_address:
            parts.append("Usar tratamiento formal (usted)")
        return ". ".join(parts)


class RateLimitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests_per_minute: int = Field(100, ge=1)
    monthly_quota: int = Field(10_000, ge=1)
    burst_size: int = Field(20, ge=1)
    enabled: bool = True


class ModuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_intelligence: bool = True
    llm_classification: bool = False
    auto_messaging: bool = False
    auto_escalation: bool = False
    priority_scoring: bool = True
    event_driven: bool = True


# ---------------------------------------------------------------------------
# Root TenantConfig
# ---------------------------------------------------------------------------

class TenantConfig(BaseModel):
    """
    Canonical per-tenant configuration. Immutable after construction.
    All engines consume this — never access raw DB config directly.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    risk_weights: RiskWeights = Field(default_factory=RiskWeights)
    risk_thresholds: RiskThresholds = Field(default_factory=RiskThresholds)
    priority_thresholds: PriorityThresholds = Field(default_factory=PriorityThresholds)
    escalation_policy: EscalationPolicy = Field(default_factory=EscalationPolicy)
    tone_settings: ToneSettings = Field(default_factory=ToneSettings)
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)
    modules: ModuleConfig = Field(default_factory=ModuleConfig)
    required_case_fields: list[str] = Field(
        default_factory=lambda: ["client_name", "overdue_days", "monthly_rent"]
    )


# ---------------------------------------------------------------------------
# Config Engine
# ---------------------------------------------------------------------------

class ConfigEngine:
    """
    Loads and parses tenant configuration from DB records into TenantConfig.

    Cache strategy:
      - Per-request: inject ConfigEngine as a FastAPI dependency.
        The same instance is reused within a single request, giving
        O(1) repeated calls with one DB round-trip per request.
      - For prod: wrap with Redis TTL (extend _load_raw).

    Invalidation:
      - Call invalidate(tenant_id) when config is updated via API.
    """

    # Simple in-process cache (request-scoped when used as FastAPI dep)
    _cache: dict[str, TenantConfig] = {}

    async def load(
        self,
        tenant_id: str,
        db: Any,  # AsyncSession — avoid circular import
    ) -> TenantConfig:
        if tenant_id in self._cache:
            return self._cache[tenant_id]

        raw = await self._load_raw(tenant_id, db)
        config = self._parse(tenant_id, raw)
        self._cache[tenant_id] = config
        return config

    def invalidate(self, tenant_id: str) -> None:
        """Call after updating tenant configuration."""
        self._cache.pop(tenant_id, None)
        logger.info("Config cache invalidated for tenant %s", tenant_id)

    # ------------------------------------------------------------------

    async def _load_raw(self, tenant_id: str, db: Any) -> dict[str, Any]:
        from sqlalchemy import select
        from database.models import TenantConfiguration

        result = await db.execute(
            select(TenantConfiguration).where(
                TenantConfiguration.tenant_id == tenant_id
            )
        )
        return {row.config_key: row.config_value for row in result.scalars().all()}

    def _parse(self, tenant_id: str, raw: dict[str, Any]) -> TenantConfig:
        """
        Build TenantConfig from raw key→value dict.
        Each top-level section is a separate config_key in DB.
        Missing keys fall back to model defaults.
        """
        def _section(key: str, model_cls: type, **overrides: Any) -> Any:
            data = raw.get(key, {})
            if not isinstance(data, dict):
                data = {}
            try:
                return model_cls(**{**data, **overrides})
            except Exception as exc:
                logger.warning(
                    "Config parse error for tenant=%s key=%s: %s — using defaults",
                    tenant_id, key, exc,
                )
                return model_cls()

        return TenantConfig(
            tenant_id=tenant_id,
            risk_weights=_section("risk_weights", RiskWeights),
            risk_thresholds=_section("risk_thresholds", RiskThresholds),
            priority_thresholds=_section("priority_thresholds", PriorityThresholds),
            escalation_policy=_section("escalation_policy", EscalationPolicy),
            tone_settings=_section("tone_settings", ToneSettings),
            rate_limits=_section("rate_limits", RateLimitConfig),
            modules=_section("modules", ModuleConfig),
            required_case_fields=raw.get(
                "required_case_fields",
                ["client_name", "overdue_days", "monthly_rent"],
            ),
        )


# Singleton — shared across requests (cache lives here)
_config_engine = ConfigEngine()


def get_config_engine() -> ConfigEngine:
    return _config_engine
    model_config = ConfigDict(extra="forbid")

    model_config = ConfigDict(extra="forbid")
