# api/routes/decisions.py
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import Bus, DB, OverrideUser, ReadUser
from api.response_models import DecisionResponse, OverrideResponse
from core.audit_logger import get_audit_logger
from core.event_bus import DomainEvent
from database.repositories import CaseRepository, DecisionRepository
from database.repositories.case_repository import OverrideRepository

router = APIRouter(prefix="/decisions", tags=["Decisions"])
audit_logger = get_audit_logger()


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overridden_action: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/{decision_id}", response_model=DecisionResponse)
async def get_decision(
    decision_id: UUID,
    current_user: ReadUser,
    db: DB,
):
    from sqlalchemy import select
    from database.models import Decision

    decision_id = str(decision_id)
    result = await db.execute(
        select(Decision).where(
            Decision.id == decision_id,
            Decision.tenant_id == str(current_user.tenant_id),
        )
    )
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    return {
        "id": str(decision.id),
        "case_id": str(decision.case_id),
        "classification": decision.classification,
        "risk_score": decision.risk_score,
        "risk_level": decision.risk_level,
        "action": decision.action,
        "firmness": decision.firmness,
        "escalation_required": decision.escalation_required,
        "escalation_target": decision.escalation_target,
        "legal_flag": decision.legal_flag,
        "policy_flag": decision.policy_flag,
        "rationale": decision.rationale,
        "rule_id_applied": str(decision.rule_id_applied) if decision.rule_id_applied else None,
        "confidence": decision.confidence,
        "suggested_message": decision.suggested_message,
        "is_overridden": decision.is_overridden,
        "full_output": decision.full_output,
        "created_at": decision.created_at.isoformat(),
    }


@router.post("/{decision_id}/override", response_model=OverrideResponse)
async def override_decision(
    decision_id: UUID,
    payload: OverrideRequest,
    background_tasks: BackgroundTasks,
    current_user: OverrideUser,
    db: DB,
    bus: Bus,
):
    """Human override of a decision. Requires 'override' permission."""
    decision_id = str(decision_id)
    tenant_id = str(current_user.tenant_id)
    decision = await DecisionRepository(db, tenant_id).get_for_update(decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    if decision.is_overridden:
        raise HTTPException(status_code=409, detail="Decision has already been overridden")

    case_repo = CaseRepository(db, tenant_id)
    case = await case_repo.get_for_update(str(decision.case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    from core.case_state_machine import CaseStateMachine, InvalidTransitionError
    sm = CaseStateMachine()
    try:
        sm.transition(case.status, "HUMAN_OVERRIDE")
    except (InvalidTransitionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Record override
    override_repo = OverrideRepository(db, tenant_id)
    override = await override_repo.create(
        data={
            "tenant_id": str(current_user.tenant_id),
            "case_id": str(decision.case_id),
            "decision_id": str(decision.id),
            "user_id": str(current_user.id),
            "original_action": decision.action,
            "overridden_action": payload.overridden_action,
            "reason": payload.reason,
        }
    )

    # Mark decision as overridden
    decision.is_overridden = True

    # Transition case to HUMAN_OVERRIDE
    await case_repo.update_status(
        case_id=str(case.id),
        status="HUMAN_OVERRIDE",
    )

    await bus.publish(
        DomainEvent(
            event_type=DomainEvent.OVERRIDE_APPLIED,
            tenant_id=tenant_id,
            aggregate_type="decision",
            aggregate_id=decision_id,
            payload={
                "case_id": str(decision.case_id),
                "decision_id": decision_id,
                "original_action": decision.action,
                "overridden_action": payload.overridden_action,
                "user_id": str(current_user.id),
            },
        ),
        db=db,
        background_tasks=background_tasks,
    )
    await db.commit()

    audit_logger.log_override(
        tenant_id=str(current_user.tenant_id),
        case_id=str(decision.case_id),
        decision_id=decision_id,
        original_action=decision.action,
        overridden_action=payload.overridden_action,
        reason=payload.reason,
        user_id=str(current_user.id),
    )

    return {
        "override_id": str(override.id),
        "decision_id": decision_id,
        "original_action": override.original_action,
        "overridden_action": override.overridden_action,
        "reason": override.reason,
    }
