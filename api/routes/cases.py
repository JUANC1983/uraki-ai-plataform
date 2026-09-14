# api/routes/cases.py
import logging
import time
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from agents.decision_agent import DecisionAgent
from agents.message_agent import MessageAgent
from api.dependencies import DB, Bus, ReadUser, TenantCfg, WriteUser
from api.response_models import (
    AuditResponse,
    CaseCreatedResponse,
    CaseDetailResponse,
    CaseDocumentListResponse,
    CaseListResponse,
    EvaluationResponse,
    ReplayResponse,
    SimulationResponse,
    TransitionResponse,
)
from connectors.llm_connector import get_llm_connector
from core.audit_logger import get_audit_logger
from core.case_state_machine import CaseStateMachine, InvalidTransitionError
from core.decision_contract import CasePriority
from core.event_bus import DomainEvent, EventBus
from core.priority_engine import PriorityEngine
from database.repositories import (
    CaseRepository,
    DecisionRepository,
    RuleRepository,
)

router = APIRouter(prefix="/cases", tags=["Cases"])
logger = logging.getLogger(__name__)

_state_machine = CaseStateMachine()
_decision_agent = DecisionAgent()
_message_agent = MessageAgent()
_priority_engine = PriorityEngine()
_audit_logger = get_audit_logger()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_type: str = Field(min_length=1, max_length=100)
    client_name: str = Field(min_length=1, max_length=300)
    client_id_number: Optional[str] = Field(default=None, max_length=100)
    property_address: Optional[str] = Field(default=None, max_length=500)
    contract_id: Optional[str] = Field(default=None, max_length=200)
    overdue_days: int = Field(default=0, ge=0, le=36500)
    overdue_amount: float = Field(default=0.0, ge=0)
    monthly_rent: float = Field(default=0.0, ge=0)
    currency: str = Field(default="COP", min_length=3, max_length=10)
    external_ref: Optional[str] = Field(default=None, max_length=200)
    raw_data: Optional[dict] = None


class CaseTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_status: Literal[
        "NEW", "IN_REVIEW", "DECISION_GENERATED", "HUMAN_OVERRIDE",
        "IN_EXECUTION", "ESCALATED", "CLOSED",
    ]
    reason: Optional[str] = Field(default=None, max_length=2000)


class CaseSimulationOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overdue_days: Optional[int] = Field(default=None, ge=0, le=36500)
    overdue_amount: Optional[float] = Field(default=None, ge=0)
    monthly_rent: Optional[float] = Field(default=None, ge=0)
    has_policy: Optional[bool] = None
    has_legal_action: Optional[bool] = None
    previous_overdue_count: Optional[int] = Field(default=None, ge=0, le=10000)


class CaseSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overrides: CaseSimulationOverrides


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/", status_code=status.HTTP_201_CREATED, response_model=CaseCreatedResponse
)
async def create_case(
    payload: CaseCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: WriteUser,
    db: DB,
    bus: Bus,
    config: TenantCfg,
):
    tenant_id = str(current_user.tenant_id)
    repo = CaseRepository(db, tenant_id)
    case = await repo.create(payload.model_dump(exclude_none=True))
    await db.refresh(case)

    # Publish event
    await bus.publish(
        DomainEvent(
            event_type=DomainEvent.CASE_CREATED,
            tenant_id=tenant_id,
            aggregate_type="case",
            aggregate_id=str(case.id),
            payload={"case_type": case.case_type, "client_name": case.client_name},
        ),
        db=db,
        background_tasks=background_tasks,
    )
    await db.commit()

    _audit_logger.log_state_transition(
        tenant_id=tenant_id,
        case_id=str(case.id),
        from_status="—",
        to_status="NEW",
        actor=str(current_user.id),
    )

    return {"id": str(case.id), "status": case.status, "priority": case.priority}


@router.get("/", response_model=CaseListResponse)
async def list_cases(
    current_user: ReadUser,
    db: DB,
    status_filter: Optional[Literal["NEW", "IN_REVIEW", "DECISION_GENERATED", "HUMAN_OVERRIDE", "IN_EXECUTION", "ESCALATED", "CLOSED"]] = Query(None, alias="status"),
    priority: Optional[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    tenant_id = str(current_user.tenant_id)
    repo = CaseRepository(db, tenant_id)
    cases, total = await repo.list(status=status_filter, limit=limit, offset=offset)

    items = [
        {
            "id": str(c.id),
            "status": c.status,
            "priority": c.priority,
            "case_type": c.case_type,
            "client_name": c.client_name,
            "overdue_days": c.overdue_days,
            "overdue_amount": c.overdue_amount,
            "created_at": c.created_at.isoformat(),
        }
        for c in cases
    ]

    # Client-side priority filter (DB filter would need a join — keep simple)
    if priority:
        items = [i for i in items if i.get("priority") == priority.upper()]

    return {"total": total, "items": items}


@router.get("/{case_id}", response_model=CaseDetailResponse)
async def get_case(case_id: UUID, current_user: ReadUser, db: DB):
    case_id = str(case_id)
    tenant_id = str(current_user.tenant_id)
    case = await CaseRepository(db, tenant_id).get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    latest = await DecisionRepository(db, tenant_id).get_latest_for_case(case_id)
    raw = case.raw_data or {}

    return {
        "id": str(case.id),
        "tenant_id": str(case.tenant_id),
        "status": case.status,
        "priority": case.priority,
        "case_type": case.case_type,
        "client_name": case.client_name,
        "client_id_number": case.client_id_number,
        "property_address": case.property_address,
        "contract_id": case.contract_id,
        "overdue_days": case.overdue_days,
        "overdue_amount": case.overdue_amount,
        "monthly_rent": case.monthly_rent,
        "currency": case.currency,
        "has_policy": bool(raw.get("has_policy", False)),
        "has_legal_action": bool(raw.get("has_legal_action", False)),
        "previous_overdue_count": int(raw.get("previous_overdue_count", 0)),
        "created_at": case.created_at.isoformat(),
        "allowed_transitions": _state_machine.get_allowed_transitions(case.status),
        "latest_decision": _serialize_decision(latest) if latest else None,
    }


@router.post("/{case_id}/evaluate", response_model=EvaluationResponse)
async def evaluate_case(
    case_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: WriteUser,
    db: DB,
    bus: Bus,
    config: TenantCfg,
):
    """
    Full decision pipeline:
      1. Load case + rules
      2. Run DecisionAgent (risk + classification + rule engine)
      3. Compute priority
      4. Persist decision
      5. Update case priority + status
      6. Publish DECISION_GENERATED event
      7. Return structured response with explanation
    """
    start = time.time()
    case_id = str(case_id)
    tenant_id = str(current_user.tenant_id)

    case_repo = CaseRepository(db, tenant_id)
    case = await case_repo.get_for_update(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Evaluation owns the NEW -> IN_REVIEW -> DECISION_GENERATED path. Cases
    # already beyond review (or CLOSED) must use an explicit valid transition
    # before another decision can be generated.
    evaluation_status = case.status
    if evaluation_status == "NEW":
        _state_machine.transition(evaluation_status, "IN_REVIEW")
        await case_repo.update_status(case_id=case_id, status="IN_REVIEW")
        evaluation_status = "IN_REVIEW"
    try:
        _state_machine.transition(evaluation_status, "DECISION_GENERATED")
    except (InvalidTransitionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    rule_repo = RuleRepository(db, tenant_id)
    rules = await rule_repo.get_active_rules()

    # Build case data context (include document clauses if available)
    raw = case.raw_data or {}
    case_data = {
        "case_type": case.case_type,
        "client_name": case.client_name,
        "overdue_days": case.overdue_days,
        "overdue_amount": case.overdue_amount,
        "monthly_rent": case.monthly_rent,
        "currency": case.currency,
        "has_legal_action": raw.get("has_legal_action", False),
        "previous_overdue_count": raw.get("previous_overdue_count", 0),
        "has_policy": raw.get("has_policy", False),
        "contract_active": raw.get("contract_active", True),
        "document_clauses": raw.get("document_clauses", []),  # populated by document agent
    }

    llm = None
    if config.modules.llm_classification:
        try:
            llm = get_llm_connector()
        except Exception as exc:
            logger.warning(
                "LLM classification unavailable; using deterministic path (%s)",
                type(exc).__name__,
            )

    decision = await _decision_agent.evaluate(
        case_id=case_id,
        tenant_id=tenant_id,
        case_data=case_data,
        rules=rules,
        tenant_config=config,
        llm_connector=llm,
        message_agent=_message_agent if config.modules.auto_messaging else None,
    )

    # Compute priority
    priority_result = _priority_engine.compute(
        risk_score=decision.risk_score,
        escalation_required=decision.escalation_required,
        overdue_days=case.overdue_days,
        legal_flag=decision.legal_flag,
        config_thresholds=config.priority_thresholds,
    )

    # Revalidate the derived priority at the frozen contract boundary.
    decision = decision.__class__.model_validate({
        **decision.model_dump(),
        "priority": priority_result.priority,
    })

    # Persist decision — store the full evaluation context for accurate replay
    decision_repo = DecisionRepository(db, tenant_id)
    db_decision = await decision_repo.save(decision=decision, context_snapshot=case_data)

    # Update case: priority + status transition
    case_repo = CaseRepository(db, tenant_id)
    await case_repo.update_status(case_id=case_id, status="DECISION_GENERATED")

    # Update case priority in DB
    db_case = await case_repo.get(case_id)
    if db_case:
        db_case.priority = priority_result.priority.value  # type: ignore[attr-defined]

    duration_ms = int((time.time() - start) * 1000)

    # Publish event
    await bus.publish(
        DomainEvent(
            event_type=DomainEvent.DECISION_GENERATED,
            tenant_id=tenant_id,
            aggregate_type="decision",
            aggregate_id=str(db_decision.id),
            payload={
                "case_id": case_id,
                "action": decision.action,
                "priority": priority_result.priority.value,
                "risk_score": decision.risk_score,
                "escalation_required": decision.escalation_required,
            },
        ),
        db=db,
        background_tasks=background_tasks,
    )
    # Auto-escalate if required (publish separate event)
    if decision.escalation_required and config.modules.auto_escalation:
        await bus.publish(
            DomainEvent(
                event_type=DomainEvent.CASE_ESCALATED,
                tenant_id=tenant_id,
                aggregate_type="case",
                aggregate_id=case_id,
                payload={
                    "escalation_target": decision.escalation_target,
                    "risk_score": decision.risk_score,
                    "legal_flag": decision.legal_flag,
                },
            ),
            db=db,
            background_tasks=background_tasks,
        )
    await db.commit()

    _audit_logger.log_decision(
        tenant_id=tenant_id,
        case_id=case_id,
        decision=decision.to_audit_dict(),
        duration_ms=duration_ms,
        user_id=str(current_user.id),
    )

    return {
        "decision_id": str(db_decision.id),
        "case_id": case_id,
        # Decision clarity fields
        "decision": decision.action,
        "why": decision.rationale,
        "rule_applied": {
            "rule_id": decision.rule_id_applied,
            "rule_version": decision.rule_version_used,
            "explanation": decision.why_this_rule,
        },
        "risk": {
            "score": decision.risk_score,
            "level": decision.risk_level.value,
        },
        "priority": priority_result.priority.value,
        "priority_score": priority_result.score,
        "priority_factors": priority_result.factors,
        "next_action": decision.next_step or decision.what_happens_next,
        # Full output
        "classification": decision.classification.value,
        "firmness": decision.firmness.value,
        "escalation_required": decision.escalation_required,
        "escalation_target": decision.escalation_target,
        "legal_flag": decision.legal_flag,
        "policy_flag": decision.policy_flag,
        "validations_missing": decision.validations_missing,
        "confidence": decision.confidence,
        "suggested_message": decision.suggested_message,
        "document_references": [r.model_dump() for r in decision.document_references],
        "explain": decision.explain(),
        "rules_evaluated": len(decision.rules_evaluated),
        "rules_discarded": len(decision.rules_discarded),
        "duration_ms": duration_ms,
    }


@router.post("/{case_id}/simulate", response_model=SimulationResponse)
async def simulate_case(
    case_id: UUID,
    payload: CaseSimulationRequest,
    current_user: WriteUser,
    db: DB,
    config: TenantCfg,
):
    """Run a deterministic what-if evaluation without persisting any changes."""
    case_id = str(case_id)
    start = time.time()
    tenant_id = str(current_user.tenant_id)
    case = await CaseRepository(db, tenant_id).get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    raw = case.raw_data or {}
    case_data = {
        "case_type": case.case_type,
        "client_name": case.client_name,
        "overdue_days": case.overdue_days,
        "overdue_amount": case.overdue_amount,
        "monthly_rent": case.monthly_rent,
        "currency": case.currency,
        "has_legal_action": raw.get("has_legal_action", False),
        "previous_overdue_count": raw.get("previous_overdue_count", 0),
        "has_policy": raw.get("has_policy", False),
        "contract_active": raw.get("contract_active", True),
        "document_clauses": raw.get("document_clauses", []),
    }
    case_data.update(payload.overrides.model_dump(exclude_none=True))
    rules = await RuleRepository(db, tenant_id).get_active_rules()
    decision = await _decision_agent.evaluate(
        case_id=case_id,
        tenant_id=tenant_id,
        case_data=case_data,
        rules=rules,
        tenant_config=config,
        llm_connector=None,
        message_agent=None,
    )
    priority = _priority_engine.compute(
        risk_score=decision.risk_score,
        escalation_required=decision.escalation_required,
        overdue_days=case_data["overdue_days"],
        legal_flag=decision.legal_flag,
        config_thresholds=config.priority_thresholds,
    )
    return {
        "simulation": True,
        "case_id": case_id,
        "decision": decision.action,
        "why": decision.rationale,
        "rule_applied": {
            "rule_id": decision.rule_id_applied,
            "rule_version": decision.rule_version_used,
            "explanation": decision.why_this_rule,
        },
        "risk": {"score": decision.risk_score, "level": decision.risk_level.value},
        "priority": priority.priority.value,
        "next_action": decision.next_step or decision.what_happens_next,
        "classification": decision.classification.value,
        "classification_source": decision.classification_source,
        "classification_reasoning": decision.classification_reasoning,
        "decision_source": decision.decision_source,
        "risk_factors": decision.risk_factors,
        "firmness": decision.firmness.value,
        "escalation_required": decision.escalation_required,
        "escalation_target": decision.escalation_target,
        "legal_flag": decision.legal_flag,
        "policy_flag": decision.policy_flag,
        "confidence": decision.confidence,
        "risk_factors": decision.risk_factors,
        "rules_evaluated": len(decision.rules_evaluated),
        "rules_discarded": len(decision.rules_discarded),
        "duration_ms": int((time.time() - start) * 1000),
    }


@router.get("/{case_id}/documents", response_model=CaseDocumentListResponse)
async def list_case_documents(case_id: UUID, current_user: ReadUser, db: DB):
    """List document processing records linked to one tenant-scoped case."""
    from database.repositories import DocumentRepository

    case_id = str(case_id)
    tenant_id = str(current_user.tenant_id)
    if not await CaseRepository(db, tenant_id).get(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    documents = await DocumentRepository(db, tenant_id).list_by_case(case_id)
    return {
        "total": len(documents),
        "items": [
            {
                "id": str(document.id),
                "file_name": document.file_name,
                "document_type": document.document_type,
                "mime_type": document.mime_type,
                "file_size": document.file_size,
                "is_embedded": document.is_embedded,
                "metadata": document.doc_metadata,
                "created_at": document.created_at.isoformat(),
            }
            for document in documents
        ],
    }


@router.get("/{case_id}/audit", response_model=AuditResponse)
async def get_case_audit(case_id: UUID, current_user: ReadUser, db: DB, bus: Bus):
    """Return persisted domain events associated with one tenant-scoped case."""
    case_id = str(case_id)
    tenant_id = str(current_user.tenant_id)
    if not await CaseRepository(db, tenant_id).get(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    stored = await bus.replay(tenant_id=tenant_id, db=db)
    relevant = [
        event
        for event in stored
        if event["aggregate_id"] == case_id
        or str(event.get("payload", {}).get("case_id", "")) == case_id
    ]
    type_map = {
        DomainEvent.CASE_CREATED: "created",
        DomainEvent.DECISION_GENERATED: "evaluated",
        DomainEvent.CASE_ESCALATED: "escalated",
        DomainEvent.CASE_CLOSED: "resolved",
        DomainEvent.CASE_STATUS_CHANGED: "status_changed",
        DomainEvent.OVERRIDE_APPLIED: "overridden",
        DomainEvent.DOCUMENT_PROCESSED: "document_added",
    }
    return {
        "events": [
            {
                "id": event["event_id"],
                "type": type_map.get(event["event_type"], event["event_type"].lower()),
                "timestamp": event["created_at"],
                "user": "System",
                "details": event["payload"],
            }
            for event in relevant
        ]
    }


@router.post("/{case_id}/transition", response_model=TransitionResponse)
async def transition_case(
    case_id: UUID,
    payload: CaseTransitionRequest,
    background_tasks: BackgroundTasks,
    current_user: WriteUser,
    db: DB,
    bus: Bus,
):
    case_id = str(case_id)
    tenant_id = str(current_user.tenant_id)
    repo = CaseRepository(db, tenant_id)
    case = await repo.get_for_update(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    original_status = case.status
    try:
        new_status = _state_machine.transition(case.status, payload.target_status)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await repo.update_status(case_id=case_id, status=new_status.value)

    event_type = (
        DomainEvent.CASE_CLOSED
        if new_status.value == "CLOSED"
        else DomainEvent.CASE_STATUS_CHANGED
    )
    await bus.publish(
        DomainEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            aggregate_type="case",
            aggregate_id=case_id,
            payload={
                "from_status": original_status,
                "to_status": new_status.value,
                "reason": payload.reason,
                "user_id": str(current_user.id),
            },
        ),
        db=db,
        background_tasks=background_tasks,
    )
    await db.commit()

    _audit_logger.log_state_transition(
        tenant_id=tenant_id,
        case_id=case_id,
        from_status=original_status,
        to_status=new_status.value,
        actor=str(current_user.id),
    )
    return {"case_id": case_id, "status": new_status.value}


@router.get("/{case_id}/replay", response_model=ReplayResponse)
async def replay_decision(
    case_id: UUID,
    at: datetime,
    current_user: ReadUser,
    db: DB,
):
    """
    Historical replay: re-run the rule engine using:
      - The exact context that was recorded when the decision was made
        (context_snapshot stored on the Decision row)
      - The rule versions that were active at the given timestamp

    Does NOT persist a new decision. Returns the replay result alongside
    the original stored decision for comparison.

    Requires that the decision has a stored context_snapshot. Legacy decisions
    without one return 422.
    """
    from core.rule_engine import RuleEngine

    case_id = str(case_id)
    tenant_id = str(current_user.tenant_id)
    if at.tzinfo is None or at.utcoffset() is None:
        raise HTTPException(
            status_code=400,
            detail="Replay timestamp must include a timezone offset.",
        )
    point_in_time = at

    # 1. Load the case (scoped to tenant)
    case = await CaseRepository(db, tenant_id).get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # 2. Find the decision that was active at the requested timestamp.
    #    list_for_case returns decisions ordered newest-first.
    decision_repo = DecisionRepository(db, tenant_id)
    all_decisions = await decision_repo.list_for_case(case_id)

    # The decision "at" the timestamp is the most recent one created at or before it.
    target_decision = None
    for d in all_decisions:
        if d.created_at <= point_in_time:
            target_decision = d
            break

    if target_decision is None:
        raise HTTPException(
            status_code=404,
            detail="No decision exists at or before the requested replay timestamp.",
        )

    # 3. Verify context_snapshot exists — required for accurate replay.
    if not target_decision.context_snapshot:
        raise HTTPException(
            status_code=422,
            detail=(
                "This decision (created before context_snapshot support was added) "
                "cannot be replayed accurately. Re-evaluate the case to enable replay."
            ),
        )

    context = target_decision.context_snapshot

    # 4. Load all rules including history, filter to those active at point_in_time
    rule_repo = RuleRepository(db, tenant_id)
    all_rules = await rule_repo.list_rules(include_history=True)
    records = [rule_repo._to_record(r) for r in all_rules]
    rules_at_time = [r for r in records if r.is_valid_at(point_in_time)]

    # 5. Re-run the rule engine against the stored context
    engine = RuleEngine()
    result = engine.evaluate_at(records, context, point_in_time)

    return {
        "case_id": case_id,
        "replay_timestamp": at.isoformat(),
        # Original stored decision for comparison
        "original_decision": {
            "id": str(target_decision.id),
            "action": target_decision.action,
            "rule_id_applied": str(target_decision.rule_id_applied) if target_decision.rule_id_applied else None,
            "rule_version_used": target_decision.rule_version_used,
            "risk_score": target_decision.risk_score,
            "classification": target_decision.classification,
            "created_at": target_decision.created_at.isoformat(),
        },
        # Replay result
        "replay_result": {
            "rules_active_at_timestamp": len(rules_at_time),
            "applied_rule": result.applied_rule.name if result.applied_rule else None,
            "applied_rule_version": result.applied_rule.version if result.applied_rule else None,
            "applied_rule_id": result.applied_rule.id if result.applied_rule else None,
            "actions": result.applied_actions,
            "explanation": result.explanation,
            "rules_evaluated": [r.to_dict() for r in result.rules_evaluated],
        },
        # Consistency check — did replay reproduce the original?
        "consistent": (
            result.applied_rule is not None
            and result.applied_rule.id == str(target_decision.rule_id_applied)
            and result.applied_rule.version == target_decision.rule_version_used
        ),
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _serialize_decision(d: Any) -> dict:
    full_output = dict(d.full_output or {})
    return {
        **full_output,
        "id": str(d.id),
        "classification": d.classification,
        "risk_score": d.risk_score,
        "risk_level": d.risk_level,
        "priority": d.priority,
        "action": d.action,
        "firmness": d.firmness,
        "escalation_required": d.escalation_required,
        "escalation_target": d.escalation_target,
        "legal_flag": d.legal_flag,
        "policy_flag": d.policy_flag,
        "validations_missing": d.validations_missing or [],
        "rationale": d.rationale,
        "rule_id_applied": str(d.rule_id_applied) if d.rule_id_applied else None,
        "rule_version_used": d.rule_version_used,
        "suggested_message": d.suggested_message,
        "document_references": d.document_references or [],
        "confidence": d.confidence,
        "is_overridden": d.is_overridden,
        "created_at": d.created_at.isoformat(),
    }
