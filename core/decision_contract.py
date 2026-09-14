# core/decision_contract.py
"""
DecisionOutput — the canonical, immutable output contract.

Every decision pipeline MUST return this schema.
No downstream module may mutate it after creation.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class RiskLevel(str, Enum):
    LOW = "BAJO"
    MEDIUM = "MEDIO"
    HIGH = "ALTO"


class Firmness(str, Enum):
    SOFT = "SUAVE"
    FIRM = "FIRME"
    STRICT = "ESTRICTO"
    URGENT = "URGENTE"


class CaseClassification(str, Enum):
    MORA_TEMPRANA = "MORA_TEMPRANA"
    MORA_MEDIA = "MORA_MEDIA"
    MORA_CRITICA = "MORA_CRITICA"
    ABANDONO = "ABANDONO"
    DISPUTA_LEGAL = "DISPUTA_LEGAL"
    RECUPERACION_POLIZA = "RECUPERACION_POLIZA"
    NEGOCIACION_VOLUNTARIA = "NEGOCIACION_VOLUNTARIA"
    REINCIDENCIA = "REINCIDENCIA"
    OTRO = "OTRO"


class CasePriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DocumentReference(BaseModel):
    """
    A specific document passage that supports or justifies the decision.
    """
    document_id: str
    clause_id: Optional[str] = None       # clause_label from DocumentChunk
    snippet: str                           # relevant excerpt (max ~300 chars)
    relevance: Optional[str] = None        # why this clause is relevant

    model_config = {"frozen": True}


class DecisionOutput(BaseModel):
    """
    Canonical decision output. Immutable after creation.

    Produced by: DecisionAgent
    Consumed by: DecisionRepository, AuditLogger, MessageAgent (read-only)
    Validated by: every API response handler
    """
    model_config = {"frozen": True}

    # Identity
    case_id: str
    tenant_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Classification
    classification: CaseClassification
    classification_source: Literal["rule_engine", "llm_hint", "default"] = "default"
    classification_reasoning: Optional[str] = None

    # Risk
    risk_score: float = Field(..., ge=0, le=100)
    risk_level: RiskLevel
    risk_factors: dict[str, Any] = Field(default_factory=dict)

    # Priority (derived from risk + flags)
    priority: CasePriority = CasePriority.MEDIUM

    # Decision
    action: str = Field(
        ..., min_length=1, max_length=200,
        description="Recommended operator action; this contract does not execute it",
    )
    decision_source: Literal["rule_engine", "deterministic_fallback"] = (
        "deterministic_fallback"
    )
    firmness: Firmness
    next_step: Optional[str] = Field(None, description="Immediate next action for operator")

    # Escalation
    escalation_required: bool = False
    escalation_target: Optional[str] = None

    # Flags
    legal_flag: bool = False
    policy_flag: bool = False

    # Validation gaps
    validations_missing: list[str] = Field(default_factory=list)

    # Explainability
    rationale: str = Field(..., description="Human-readable justification")
    why_this_rule: Optional[str] = Field(None, description="Why this rule was selected over others")
    what_happens_next: Optional[str] = Field(None, description="Expected outcome if action is taken")

    # Rule traceability
    rule_id_applied: Optional[str] = None
    rule_version_used: Optional[int] = None    # rule.version at evaluation time
    rules_evaluated: list[dict[str, Any]] = Field(default_factory=list)
    rules_discarded: list[dict[str, Any]] = Field(default_factory=list)

    # Document evidence
    document_references: list[DocumentReference] = Field(default_factory=list)

    # LLM output (advisory only — does not affect rule engine fields)
    confidence: float = Field(default=1.0, ge=0, le=1)
    suggested_message: Optional[str] = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def derive_risk_level(self) -> "DecisionOutput":
        """Derive risk level from the recorded tenant thresholds when available."""
        thresholds = self.risk_factors.get("thresholds_used", {})
        resolved = None
        labels = {"low": RiskLevel.LOW, "medium": RiskLevel.MEDIUM, "high": RiskLevel.HIGH}
        if isinstance(thresholds, dict):
            for name in ("low", "medium", "high"):
                bounds = thresholds.get(name)
                if isinstance(bounds, dict) and bounds.get("min") is not None and bounds.get("max") is not None:
                    if float(bounds["min"]) <= self.risk_score <= float(bounds["max"]):
                        resolved = labels[name]
                        break
        object.__setattr__(
            self,
            "risk_level",
            resolved or (
                RiskLevel.LOW if self.risk_score <= 30
                else RiskLevel.MEDIUM if self.risk_score <= 70
                else RiskLevel.HIGH
            ),
        )
        return self

    def to_audit_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def explain(self) -> str:
        """
        Single-string decision explanation for display.
        Covers: decision, why, rule, risk, next action.
        """
        lines = [
            f"DECISIÓN: {self.action} ({self.firmness.value})",
            f"CLASIFICACIÓN: {self.classification.value}",
            f"RIESGO: {self.risk_level.value} ({self.risk_score:.1f}/100)",
            f"PRIORIDAD: {self.priority.value}",
            f"JUSTIFICACIÓN: {self.rationale}",
        ]
        if self.why_this_rule:
            lines.append(f"REGLA APLICADA: {self.why_this_rule}")
        if self.what_happens_next:
            lines.append(f"PRÓXIMO PASO: {self.what_happens_next}")
        if self.escalation_required:
            lines.append(f"ESCALAMIENTO: → {self.escalation_target}")
        if self.legal_flag:
            lines.append("⚠ ALERTA LEGAL activa")
        if self.policy_flag:
            lines.append("📋 Póliza aplicable")
        if self.document_references:
            lines.append(f"EVIDENCIA: {len(self.document_references)} cláusula(s) referenciada(s)")
        return "\n".join(lines)
