# api/routes/dashboard.py
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from api.dependencies import DB, ExecutiveUser, ReadUser, TenantCfg
from api.response_models import (
    EventsResponse,
    ExecutiveResponse,
    KPIResponse,
    MetricsResponse,
    OperationalResponse,
)
from core.event_bus import get_event_bus
from database.repositories import CaseRepository, DecisionRepository
from database.repositories.case_repository import OverrideRepository

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/operational", response_model=OperationalResponse)
async def operational_dashboard(
    current_user: ReadUser,
    db: DB,
    status_filter: Optional[Literal["NEW", "IN_REVIEW", "DECISION_GENERATED", "HUMAN_OVERRIDE", "IN_EXECUTION", "ESCALATED", "CLOSED"]] = Query(None, alias="status"),
    priority: Optional[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Operational view:
      - Case queue with risk scores + priority
      - Filters by status and priority
      - Each case includes latest decision summary
    """
    tenant_id = str(current_user.tenant_id)
    case_repo = CaseRepository(db, tenant_id)
    decision_repo = DecisionRepository(db, tenant_id)

    cases, total = await case_repo.list(status=status_filter, limit=limit, offset=offset)

    enriched = []
    for case in cases:
        latest = await decision_repo.get_latest_for_case(str(case.id))
        item = {
            "id": str(case.id),
            "status": case.status,
            "priority": case.priority,
            "case_type": case.case_type,
            "client_name": case.client_name,
            "overdue_days": case.overdue_days,
            "overdue_amount": case.overdue_amount,
            "created_at": case.created_at.isoformat(),
            "decision": None,
        }
        if latest:
            item["decision"] = {
                "action": latest.action,
                "risk_score": latest.risk_score,
                "risk_level": latest.risk_level,
                "priority": latest.priority,
                "escalation_required": latest.escalation_required,
                "legal_flag": latest.legal_flag,
                "rationale": latest.rationale,
                "rule_version_used": latest.rule_version_used,
            }
        enriched.append(item)

    if priority:
        enriched = [i for i in enriched if i.get("priority") == priority.upper()]

    return {"total": total, "items": enriched}


@router.get("/executive", response_model=ExecutiveResponse)
async def executive_dashboard(current_user: ExecutiveUser, db: DB):
    """
    Executive KPIs:
      - Mora total + aging buckets
      - Decision stats + override rate
      - Priority distribution
      - Escalation summary
    """
    if "view_executive" not in {
        "admin": {"view_executive"},
        "ejecutivo": {"view_executive"},
    }.get(current_user.role, set()):
        raise HTTPException(status_code=403, detail="Executive access only")

    tenant_id = str(current_user.tenant_id)
    case_repo = CaseRepository(db, tenant_id)
    decision_repo = DecisionRepository(db, tenant_id)
    override_repo = OverrideRepository(db, tenant_id)

    case_kpis = await case_repo.get_kpis()
    aging = await case_repo.get_aging_buckets()
    decision_stats = await decision_repo.get_stats()
    override_rate = await override_repo.get_override_rate()

    return {
        "tenant_id": tenant_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": {**case_kpis, "aging": aging},
        "decisions": decision_stats,
        "overrides": {"override_rate_pct": override_rate},
    }


@router.get("/kpis", response_model=KPIResponse)
async def get_kpis(current_user: ReadUser, db: DB):
    tenant_id = str(current_user.tenant_id)
    return {
        "cases": await CaseRepository(db, tenant_id).get_kpis(),
        "decisions": await DecisionRepository(db, tenant_id).get_stats(),
    }


@router.get("/events", response_model=EventsResponse)
async def get_events(
    current_user: ExecutiveUser,
    db: DB,
    event_type: Optional[str] = Query(None),
    since_hours: int = Query(24, ge=1, le=720),
):
    """
    Event log for audit trail.
    Returns stored domain events for this tenant.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    bus = get_event_bus()
    events = await bus.replay(
        tenant_id=str(current_user.tenant_id),
        event_type=event_type,
        since=since,
        db=db,
    )
    return {"count": len(events), "events": events}


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(current_user: ExecutiveUser, db: DB):
    """
    Product metrics for internal tracking.
    """
    tenant_id = str(current_user.tenant_id)
    decision_repo = DecisionRepository(db, tenant_id)
    case_repo = CaseRepository(db, tenant_id)

    stats = await decision_repo.get_stats()
    kpis = await case_repo.get_kpis()

    return {
        "tenant_id": tenant_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "product_metrics": {
            "total_cases_processed": kpis["total_cases"],
            "open_cases": kpis["open_cases"],
            "total_decisions_generated": stats["total_decisions"],
            "escalation_rate_pct": round(
                stats["escalated"] / max(stats["total_decisions"], 1) * 100, 2
            ),
            "legal_flag_rate_pct": round(
                stats["legal_flags"] / max(stats["total_decisions"], 1) * 100, 2
            ),
            "override_rate_pct": stats["override_rate"],
            "avg_overdue_days": kpis["avg_overdue_days"],
            "total_overdue_exposure": kpis["total_overdue_amount"],
        },
    }
