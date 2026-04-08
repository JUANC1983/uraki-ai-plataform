# api/routes/decisions.py
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.dependencies import DB, CurrentUser, require_permission
from core.audit_logger import get_audit_logger
from database.models import User
from database.repositories import CaseRepository, DecisionRepository
from database.repositories.case_repository import OverrideRepository

router = APIRouter(prefix="/decisions", tags=["Decisions"])
audit_logger = get_audit_logger()


class OverrideRequest(BaseModel):
    overridden_action: str
    reason: str


@router.get("/{decision_id}")
async def get_decision(
    decision_id: str,
    current_user: CurrentUser,
    db: DB,
):
    from sqlalchemy import select
    from database.models import Decision

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


@router.post("/{decision_id}/override")
async def override_decision(
    decision_id: str,
    payload: OverrideRequest,
    current_user: CurrentUser,
    db: DB,
):
    """Human override of a decision. Requires 'override' permission."""
    # Check permission
    from api.dependencies import ROLE_PERMISSIONS
    if "override" not in ROLE_PERMISSIONS.get(current_user.role, set()):
        raise HTTPException(status_code=403, detail="Insufficient permissions for override")

    from sqlalchemy import select
    from database.models import Decision

    result = await db.execute(
        select(Decision).where(
            Decision.id == decision_id,
            Decision.tenant_id == str(current_user.tenant_id),
        )
    )
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    # Record override
    override_repo = OverrideRepository(db)
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
    case_repo = CaseRepository(db)
    from core.case_state_machine import CaseStateMachine
    sm = CaseStateMachine()
    case = await case_repo.get(
        case_id=str(decision.case_id), tenant_id=str(current_user.tenant_id)
    )
    if case and sm.can_transition(case.status, "HUMAN_OVERRIDE"):
        await case_repo.update_status(
            case_id=str(case.id),
            tenant_id=str(current_user.tenant_id),
            status="HUMAN_OVERRIDE",
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
