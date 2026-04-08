# automation/event_handlers.py
"""
Domain event handlers — wired to the EventBus at startup.

Each handler is an async function that receives a DomainEvent.
Handlers must be idempotent (they may be called more than once on retry).
"""
import logging

from core.event_bus import DomainEvent, EventBus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handler definitions
# ---------------------------------------------------------------------------

async def on_case_created(event: DomainEvent) -> None:
    logger.info(
        "[EVENT] CASE_CREATED | tenant=%s case=%s type=%s",
        event.tenant_id,
        event.aggregate_id,
        event.payload.get("case_type"),
    )
    # Future: trigger CRM sync, send acknowledgement, etc.


async def on_decision_generated(event: DomainEvent) -> None:
    payload = event.payload
    logger.info(
        "[EVENT] DECISION_GENERATED | tenant=%s decision=%s action=%s priority=%s",
        event.tenant_id,
        event.aggregate_id,
        payload.get("action"),
        payload.get("priority"),
    )

    # Auto-notify if CRITICAL priority
    if payload.get("priority") == "CRITICAL":
        from automation.task_queue import get_task_queue
        queue = get_task_queue()
        await queue.run(
            "send_notification",
            tenant_id=event.tenant_id,
            case_id=payload.get("case_id", ""),
            notification_type="critical_priority_alert",
            recipient="operations_team",
            payload=payload,
        )


async def on_override_applied(event: DomainEvent) -> None:
    payload = event.payload
    logger.info(
        "[EVENT] OVERRIDE_APPLIED | tenant=%s decision=%s original=%s → new=%s by user=%s",
        event.tenant_id,
        payload.get("decision_id"),
        payload.get("original_action"),
        payload.get("overridden_action"),
        payload.get("user_id"),
    )
    # Future: flag for ML feedback, alert supervisors if frequent overrides


async def on_case_escalated(event: DomainEvent) -> None:
    payload = event.payload
    logger.info(
        "[EVENT] CASE_ESCALATED | tenant=%s case=%s target=%s",
        event.tenant_id,
        event.aggregate_id,
        payload.get("escalation_target"),
    )
    from automation.task_queue import get_task_queue
    queue = get_task_queue()
    await queue.run(
        "auto_escalate",
        tenant_id=event.tenant_id,
        case_id=event.aggregate_id,
        escalation_target=payload.get("escalation_target", "management"),
        reason="Automatic escalation triggered by decision engine",
        risk_score=payload.get("risk_score", 0),
    )


async def on_document_processed(event: DomainEvent) -> None:
    logger.info(
        "[EVENT] DOCUMENT_PROCESSED | tenant=%s doc=%s chunks=%s",
        event.tenant_id,
        event.aggregate_id,
        event.payload.get("chunks_created"),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_all_handlers(bus: EventBus) -> None:
    """Called once at application startup."""
    bus.subscribe(DomainEvent.CASE_CREATED, on_case_created)
    bus.subscribe(DomainEvent.DECISION_GENERATED, on_decision_generated)
    bus.subscribe(DomainEvent.OVERRIDE_APPLIED, on_override_applied)
    bus.subscribe(DomainEvent.CASE_ESCALATED, on_case_escalated)
    bus.subscribe(DomainEvent.DOCUMENT_PROCESSED, on_document_processed)
    logger.info("EventBus: registered %d domain event handlers", 5)
