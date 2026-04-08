# api/routes/cases.py
import time
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agents.decision_agent import DecisionAgent
from agents.message_agent import MessageAgent
from api.dependencies import DB, Bus, CurrentUser, TenantCfg
from connectors.llm_connector import get_llm_connector
from core.audit_logger import get_audit_logger
from core.case_state_machine import CaseStateMachine, InvalidTransitionError
from core.decision_contract import CasePriority
from core.event_bus import DomainEvent, EventBus
from core.priority_engine import PriorityEngine
from database.models import User
from database.repositories import (
    CaseRepository,
    DecisionRepository,
    RuleRepository,
)

router = APIRouter(prefix="/cases", tags=["Cases"])

_state_machine = CaseStateMachine()
_decision_agent = DecisionAgent()
_message_agent = MessageAgent()
_priority_engine = PriorityEngine()
_audit_logger = get_audit_logger()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CaseCreateRequest(BaseModel):
    case_type: str
    client_name: str
    client_id_number: Optional[str] = None
    property_address: Optional[str] = None
    contract_id: Optional[str] = None
    overdue_days: int = 0
    overdue_amount: float = 0.0
    monthly_rent: float = 0.0
    currency: str = "COP"
    external_ref: Optional[str] = None
    raw_data: Optional[dict] = None


class CaseTransitionRequest(BaseModel):
    target_status: str
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: DB,
    bus: Bus,
    config: TenantCfg,
):
    tenant_id = str(current_user.tenant_id)
    repo = CaseRepository(db, tenant_id)
    case = await repo.create(payload.model_dump(exclude_none=True))
    await db.commit()
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


@router.get("/")
async def list_cases(
    current_user: CurrentUser,
    db: DB,
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
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


@router.get("/{case_id}")
async def get_case(case_id: str, current_user: CurrentUser, db: DB):
    tenant_id = str(current_user.tenant_id)
    case = await CaseRepository(db, tenant_id).get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    latest = await DecisionRepository(db, tenant_id).get_latest_for_case(case_id)

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
        "created_at": case.created_at.isoformat(),
        "allowed_transitions": _state_machine.get_allowed_transitions(case.status),
        "latest_decision": _serialize_decision(latest) if latest else None,
    }


@router.post("/{case_id}/evaluate")
async def evaluate_case(
    case_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
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
    tenant_id = str(current_user.tenant_id)

    case_repo = CaseRepository(db, tenant_id)
    case = await case_repo.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

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

    llm = get_llm_connector() if config.modules.llm_classification else None

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

    # Attach priority to decision (via model_copy since it's frozen)
    decision = decision.model_copy(
        update={"priority": priority_result.priority}
    )

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

    await db.commit()

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
    await db.commit()

    _audit_logger.log_decision(
        tenant_id=tenant_id,
        case_id=case_id,
        decision=decision.to_audit_dict(),
        duration_ms=duration_ms,
        user_id=str(current_user.id),
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


@router.post("/{case_id}/transition")
async def transition_case(
    case_id: str,
    payload: CaseTransitionRequest,
    current_user: CurrentUser,
    db: DB,
):
    tenant_id = str(current_user.tenant_id)
    repo = CaseRepository(db, tenant_id)
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        new_status = _state_machine.transition(case.status, payload.target_status)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await repo.update_status(case_id=case_id, status=new_status.value)
    await db.commit()

    _audit_logger.log_state_transition(
        tenant_id=tenant_id,
        case_id=case_id,
        from_status=case.status,
        to_status=new_status.value,
        actor=str(current_user.id),
    )
    return {"case_id": case_id, "status": new_status.value}


@router.get("/{case_id}/replay")
async def replay_decision(
    case_id: str,
    at: str,  # ISO 8601 datetime string — e.g. "2025-11-15T14:30:00"
    current_user: CurrentUser,
    db: DB,
):
    """
    Historical replay: re-run the rule engine using:
      - The exact context that was recorded when the decision was made
        (context_snapshot stored on the Decision row)
      - The rule versions that were active at the given timestamp

    Does NOT persist a new decision. Returns the replay result alongside
    the original stored decision for comparison.

    Requires that the decision was created after context_snapshot support
    was added (revision 0002). Older decisions will return 422.
    """
    from datetime import datetime
    from core.rule_engine import RuleEngine

    tenant_id = str(current_user.tenant_id)

    try:
        point_in_time = datetime.fromisoformat(at)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid datetime format. Use ISO 8601, e.g. '2025-11-15T14:30:00'.",
        )

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
            detail=f"No decision found for case '{case_id}' at or before '{at}'. "
                   f"The case may not have been evaluated yet at that time.",
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
        "replay_timestamp": at,
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
    return {
        "id": str(d.id),
        "classification": d.classification,
        "risk_score": d.risk_score,
        "risk_level": d.risk_level,
        "priority": d.priority,
        "action": d.action,
        "firmness": d.firmness,
        "rationale": d.rationale,
        "rule_id_applied": str(d.rule_id_applied) if d.rule_id_applied else None,
        "rule_version_used": d.rule_version_used,
        "suggested_message": d.suggested_message,
        "document_references": d.document_references or [],
        "created_at": d.created_at.isoformat(),
    }


from typing import Any  # noqa: E402
