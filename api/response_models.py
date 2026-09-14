"""Explicit public response contracts used by the HTTP API.

The domain contains configurable rule and decision payloads, so those nested
objects remain dictionaries. Stable envelope and identity fields are typed to
keep OpenAPI useful and to validate handlers before a response leaves the API.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class PublicResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(PublicResponse):
    status: str
    version: str


class ReadinessResponse(PublicResponse):
    status: str
    ready: bool
    database: str
    checks: dict[str, Any]


class UserResponse(PublicResponse):
    id: str
    email: str
    role: str


class CaseCreatedResponse(PublicResponse):
    id: str
    status: str
    priority: Optional[str] = None


class CaseListItem(PublicResponse):
    id: str
    status: str
    priority: Optional[str] = None
    case_type: str
    client_name: str
    overdue_days: int
    overdue_amount: float
    created_at: str


class CaseListResponse(PublicResponse):
    total: int = Field(ge=0)
    items: list[CaseListItem]


class CaseDetailResponse(PublicResponse):
    id: str
    tenant_id: str
    status: str
    priority: Optional[str] = None
    case_type: str
    client_name: str
    client_id_number: Optional[str] = None
    property_address: Optional[str] = None
    contract_id: Optional[str] = None
    overdue_days: int
    overdue_amount: float
    monthly_rent: float
    currency: str
    has_policy: bool
    has_legal_action: bool
    previous_overdue_count: int
    created_at: str
    allowed_transitions: list[str]
    latest_decision: Optional[dict[str, Any]] = None


class EvaluationResponse(PublicResponse):
    decision_id: str
    case_id: str
    decision: str
    why: str
    rule_applied: dict[str, Any]
    risk: dict[str, Any]
    priority: str
    priority_score: float
    priority_factors: dict[str, float]
    next_action: Optional[str] = None
    classification: str
    firmness: str
    escalation_required: bool
    escalation_target: Optional[str] = None
    legal_flag: bool
    policy_flag: bool
    validations_missing: list[Any]
    confidence: float
    suggested_message: Optional[str] = None
    document_references: list[dict[str, Any]]
    explain: str
    rules_evaluated: int
    rules_discarded: int
    duration_ms: int


class SimulationResponse(PublicResponse):
    simulation: bool
    case_id: str
    decision: str
    why: str
    rule_applied: dict[str, Any]
    risk: dict[str, Any]
    priority: str
    next_action: Optional[str] = None
    classification: str
    classification_source: str
    classification_reasoning: Optional[str] = None
    decision_source: str
    risk_factors: dict[str, Any]
    firmness: str
    escalation_required: bool
    escalation_target: Optional[str] = None
    legal_flag: bool
    policy_flag: bool
    confidence: float
    rules_evaluated: int
    rules_discarded: int
    duration_ms: int


class CaseDocumentItem(PublicResponse):
    id: str
    file_name: str
    document_type: str
    mime_type: str
    file_size: int
    is_embedded: bool
    metadata: Optional[dict[str, Any]] = None
    created_at: str


class CaseDocumentListResponse(PublicResponse):
    total: int = Field(ge=0)
    items: list[CaseDocumentItem]


class AuditResponse(PublicResponse):
    events: list[dict[str, Any]]


class TransitionResponse(PublicResponse):
    case_id: str
    status: str


class ReplayResponse(PublicResponse):
    case_id: str
    replay_timestamp: str
    original_decision: dict[str, Any]
    replay_result: dict[str, Any]
    consistent: bool


class DecisionResponse(PublicResponse):
    id: str
    case_id: str
    classification: str
    risk_score: float
    risk_level: str
    action: str
    firmness: str
    escalation_required: bool
    escalation_target: Optional[str] = None
    legal_flag: bool
    policy_flag: bool
    rationale: str
    rule_id_applied: Optional[str] = None
    confidence: float
    suggested_message: Optional[str] = None
    is_overridden: bool
    full_output: dict[str, Any]
    created_at: str


class OverrideResponse(PublicResponse):
    override_id: str
    decision_id: str
    original_action: str
    overridden_action: str
    reason: str


class UploadResponse(PublicResponse):
    document_id: str
    file_name: str
    document_type: str
    status: str
    message: str


class DocumentResponse(PublicResponse):
    id: str
    document_type: str
    file_name: str
    file_size: int
    mime_type: str
    is_embedded: bool
    case_id: Optional[str] = None
    contract_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    created_at: str


class SearchResult(PublicResponse):
    document_id: str
    clause_label: Optional[str] = None
    content: str
    score: float


class SearchResponse(PublicResponse):
    results: list[SearchResult]


class TenantResponse(PublicResponse):
    id: str
    name: str
    slug: str
    plan: str
    config: dict[str, Any]


class ConfigUpdatedResponse(PublicResponse):
    message: str
    key: str


class RuleListItem(PublicResponse):
    id: str
    parent_rule_id: Optional[str] = None
    name: str
    category: str
    priority: int
    version: int
    is_active: bool
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    conditions: dict[str, Any]
    actions: dict[str, Any]


class RuleCreatedResponse(PublicResponse):
    id: str
    name: str
    category: str
    version: int
    effective_from: str


class RuleUpdatedResponse(PublicResponse):
    id: str
    name: str
    version: int
    effective_from: str
    parent_rule_id: str


class RuleRollbackResponse(PublicResponse):
    id: str
    name: str
    version: int
    message: str


class RuleHistoryItem(PublicResponse):
    id: str
    version: int
    is_active: bool
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None


class APIKeyCreatedResponse(PublicResponse):
    id: str
    name: str
    key: str
    prefix: str
    expires_at: Optional[str] = None
    warning: str


class APIKeyListItem(PublicResponse):
    id: str
    name: str
    prefix: str
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: str


class OperationalDecision(PublicResponse):
    action: str
    risk_score: float
    risk_level: str
    priority: Optional[str] = None
    escalation_required: bool
    legal_flag: bool
    rationale: str
    rule_version_used: Optional[int] = None


class OperationalItem(CaseListItem):
    decision: Optional[OperationalDecision] = None


class OperationalResponse(PublicResponse):
    total: int = Field(ge=0)
    items: list[OperationalItem]


class ExecutiveResponse(PublicResponse):
    tenant_id: str
    generated_at: str
    cases: dict[str, Any]
    decisions: dict[str, Any]
    overrides: dict[str, Any]


class KPIResponse(PublicResponse):
    cases: dict[str, Any]
    decisions: dict[str, Any]


class EventsResponse(PublicResponse):
    count: int = Field(ge=0)
    events: list[dict[str, Any]]


class MetricsResponse(PublicResponse):
    tenant_id: str
    timestamp: str
    product_metrics: dict[str, Any]
