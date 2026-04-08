# core/event_bus.py
"""
Event Bus — async, in-process event dispatcher with persistent event store.

Architecture:
  - Events are stored in the DB (EventStore table) first → guaranteed durability
  - Then dispatched in-memory to registered async handlers
  - Handlers run fire-and-forget inside BackgroundTasks or Celery (Celery-ready)

Event types:
  CASE_CREATED, DECISION_GENERATED, OVERRIDE_APPLIED,
  CASE_ESCALATED, DOCUMENT_PROCESSED, RULE_UPDATED
"""
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

# Type alias for async event handler
AsyncHandler = Callable[["DomainEvent"], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Domain Event
# ---------------------------------------------------------------------------

class DomainEvent:
    """
    Immutable domain event.

    Fields:
        event_id      — UUID, unique per event
        event_type    — one of the EVENT_* constants below
        tenant_id     — always scoped to a tenant
        aggregate_type— "case" | "decision" | "document" | "rule"
        aggregate_id  — ID of the entity the event refers to
        payload       — arbitrary dict with event-specific data
        occurred_at   — UTC datetime of occurrence
    """

    # Event type constants — use these, never raw strings
    CASE_CREATED = "CASE_CREATED"
    DECISION_GENERATED = "DECISION_GENERATED"
    OVERRIDE_APPLIED = "OVERRIDE_APPLIED"
    CASE_ESCALATED = "CASE_ESCALATED"
    DOCUMENT_PROCESSED = "DOCUMENT_PROCESSED"
    RULE_UPDATED = "RULE_UPDATED"
    CASE_CLOSED = "CASE_CLOSED"

    def __init__(
        self,
        *,
        event_type: str,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        occurred_at: Optional[datetime] = None,
    ) -> None:
        self.event_id = str(uuid.uuid4())
        self.event_type = event_type
        self.tenant_id = tenant_id
        self.aggregate_type = aggregate_type
        self.aggregate_id = aggregate_id
        self.payload = payload
        self.occurred_at = occurred_at or datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"DomainEvent(type={self.event_type}, "
            f"tenant={self.tenant_id}, aggregate={self.aggregate_id})"
        )


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------

class EventBus:
    """
    In-process async event bus with DB persistence.

    Usage:
        bus = get_event_bus()

        # Register handler (done at startup in main.py)
        bus.subscribe(DomainEvent.CASE_ESCALATED, escalation_handler)

        # Publish (inside request handler)
        await bus.publish(event, db=db)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[AsyncHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: AsyncHandler) -> None:
        """Register an async handler for an event type."""
        self._handlers[event_type].append(handler)
        logger.debug("EventBus: subscribed handler %s to %s", handler.__name__, event_type)

    def subscribe_many(self, mapping: dict[str, AsyncHandler]) -> None:
        for event_type, handler in mapping.items():
            self.subscribe(event_type, handler)

    async def publish(
        self,
        event: DomainEvent,
        *,
        db: Any,  # AsyncSession — avoid circular import
        background_tasks: Optional[Any] = None,  # FastAPI BackgroundTasks
    ) -> str:
        """
        1. Persist to EventStore (guaranteed)
        2. Dispatch to handlers (best-effort, logged on failure)

        Returns the event_id.
        """
        await self._persist(event, db)

        if background_tasks is not None:
            # Defer handler execution to after response
            background_tasks.add_task(self._dispatch, event)
        else:
            await self._dispatch(event)

        return event.event_id

    async def replay(
        self,
        *,
        tenant_id: str,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        db: Any,
    ) -> list[dict[str, Any]]:
        """
        Replay stored events for a tenant (historical audit / reprocessing).
        Does NOT re-execute handlers — returns raw event records.
        """
        from sqlalchemy import select
        from database.models import EventStore

        q = select(EventStore).where(EventStore.tenant_id == tenant_id)
        if event_type:
            q = q.where(EventStore.event_type == event_type)
        if since:
            q = q.where(EventStore.created_at >= since)
        q = q.order_by(EventStore.created_at.asc())

        result = await db.execute(q)
        return [
            {
                "event_id": str(row.id),
                "event_type": row.event_type,
                "aggregate_type": row.aggregate_type,
                "aggregate_id": str(row.aggregate_id),
                "payload": row.payload,
                "processed": row.processed,
                "created_at": row.created_at.isoformat(),
            }
            for row in result.scalars().all()
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _persist(self, event: DomainEvent, db: Any) -> None:
        from database.models import EventStore

        record = EventStore(
            id=event.event_id,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
        )
        db.add(record)
        await db.flush()
        logger.debug("EventBus: persisted %s", event.event_type)

    async def _dispatch(self, event: DomainEvent) -> None:
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                logger.error(
                    "EventBus handler %s failed for event %s: %s",
                    handler.__name__,
                    event.event_type,
                    exc,
                    exc_info=True,
                )

    async def _mark_processed(self, event_id: str, db: Any, error: Optional[str] = None) -> None:
        from sqlalchemy import select
        from database.models import EventStore

        result = await db.execute(select(EventStore).where(EventStore.id == event_id))
        record = result.scalar_one_or_none()
        if record:
            record.processed = True
            record.processed_at = datetime.utcnow()
            if error:
                record.error = error


# Singleton
_event_bus = EventBus()


def get_event_bus() -> EventBus:
    return _event_bus
