# automation/task_queue.py
"""
Async Task Queue — FastAPI BackgroundTasks now, Celery-ready design.

Design:
  - Tasks are Python async callables registered with @task_queue.register
  - FastAPI routes enqueue tasks via background_tasks.add_task(queue.run, ...)
  - Same task definitions work with Celery: wrap run() in a @celery_app.task
  - No coupling to FastAPI internals — pure async functions

Tasks defined here:
  - process_document_async   : parse + chunk + embed after upload
  - generate_embeddings_async: re-embed existing document chunks
  - send_notification_async  : email/webhook notification dispatch
  - auto_escalate_async      : trigger escalation workflow
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

AsyncTaskFn = Callable[..., Coroutine[Any, Any, None]]


@dataclass
class Task:
    name: str
    fn: AsyncTaskFn
    payload: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""
    enqueued_at: datetime = field(default_factory=datetime.utcnow)


class TaskQueue:
    """
    Simple async task registry.

    Use via FastAPI BackgroundTasks:
        background_tasks.add_task(queue.run, "process_document", payload={...})

    Celery migration path:
        @celery_app.task(name="process_document")
        def celery_wrapper(**kwargs):
            asyncio.run(queue.run("process_document", **kwargs))
    """

    def __init__(self) -> None:
        self._registry: dict[str, AsyncTaskFn] = {}

    def register(self, name: str) -> Callable:
        def decorator(fn: AsyncTaskFn) -> AsyncTaskFn:
            self._registry[name] = fn
            logger.debug("TaskQueue: registered task '%s'", name)
            return fn
        return decorator

    async def run(self, task_name: str, **kwargs: Any) -> None:
        fn = self._registry.get(task_name)
        if fn is None:
            logger.error("TaskQueue: unknown task '%s'", task_name)
            raise KeyError(f"Unknown task: {task_name}")
        try:
            logger.info("TaskQueue: starting task '%s'", task_name)
            await fn(**kwargs)
            logger.info("TaskQueue: completed task '%s'", task_name)
        except Exception as exc:
            logger.error(
                "TaskQueue: task '%s' failed (%s)", task_name, type(exc).__name__
            )
            raise


# Singleton
_queue = TaskQueue()


def get_task_queue() -> TaskQueue:
    return _queue


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

@_queue.register("process_document")
async def process_document_async(
    *,
    document_id: str,
    tenant_id: str,
    file_path: str,
    mime_type: str,
    document_type: str,
    case_id: Optional[str] = None,
    contract_id: Optional[str] = None,
) -> None:
    """
    Background task: parse → chunk → embed a document.
    Called after upload returns to avoid blocking the HTTP response.
    """
    import io
    from agents.document_agent import DocumentAgent
    from connectors.llm_connector import get_llm_connector
    from connectors.storage_connector import get_storage_connector
    from core.audit_logger import get_audit_logger
    from core.event_bus import DomainEvent, get_event_bus
    from database.base import AsyncSessionLocal
    from database.repositories import DocumentRepository
    import time

    start = time.time()
    storage = get_storage_connector()
    agent = DocumentAgent()
    audit = get_audit_logger()

    try:
        file_bytes = await storage.read_file(file_path, tenant_id=tenant_id)
        try:
            llm = get_llm_connector()
        except Exception as exc:
            llm = None
            logger.info("Document AI enrichment disabled (%s)", type(exc).__name__)

        result = await agent.process(
            file_bytes=file_bytes,
            mime_type=mime_type,
            document_type=document_type,
            tenant_id=tenant_id,
            contract_id=contract_id,
            llm_connector=llm,
        )

        embedding_status = result["embedding_status"]
        processing_status = {
            "completed": "completed",
            "failed": "processed_embedding_failed",
            "not_requested": "processed_without_embeddings",
        }[embedding_status]

        async with AsyncSessionLocal() as db:
            repo = DocumentRepository(db, tenant_id)
            doc = await repo.get(document_id)
            if not doc:
                raise ValueError("Document no longer exists for its tenant")
            doc.parsed_text = result["parsed_text"][:50000]  # type: ignore[attr-defined]
            doc.doc_metadata = {  # type: ignore[attr-defined]
                "summary": result.get("summary"),
                "summary_status": result["summary_status"],
                "embedding_status": embedding_status,
                "processing_status": processing_status,
            }
            doc.is_embedded = embedding_status == "completed"  # type: ignore[attr-defined]
            await repo.create_chunks(
                document_id=document_id,
                chunks=result["chunks"],
                embeddings=result["embeddings"],
            )
            await get_event_bus().publish(
                DomainEvent(
                    event_type=DomainEvent.DOCUMENT_PROCESSED,
                    tenant_id=tenant_id,
                    aggregate_type="document",
                    aggregate_id=document_id,
                    payload={
                        "case_id": case_id,
                        "chunks_created": len(result["chunks"]),
                        "embedding_status": embedding_status,
                    },
                ),
                db=db,
            )
            await db.commit()

        duration_ms = int((time.time() - start) * 1000)
        audit.log_document_processed(
            tenant_id=tenant_id,
            document_id=document_id,
            case_id=case_id,
            chunks=len(result["chunks"]),
            duration_ms=duration_ms,
        )
    except Exception as exc:
        error_type = type(exc).__name__
        logger.error("Document processing failed (%s)", error_type)
        try:
            async with AsyncSessionLocal() as db:
                repo = DocumentRepository(db, tenant_id)
                doc = await repo.get(document_id)
                if doc:
                    metadata = dict(doc.doc_metadata or {})
                    metadata.update(
                        {
                            "processing_status": "failed",
                            "processing_error": error_type,
                        }
                    )
                    doc.doc_metadata = metadata  # type: ignore[attr-defined]
                    await db.commit()
        except Exception as status_exc:
            logger.error(
                "Failed to persist document failure status (%s)",
                type(status_exc).__name__,
            )
        audit.log_error(
            tenant_id=tenant_id,
            event_type="DOCUMENT_PROCESSING",
            error=error_type,
            context={"document_id": document_id, "case_id": case_id},
        )
        raise


@_queue.register("send_notification")
async def send_notification_async(
    *,
    tenant_id: str,
    case_id: str,
    notification_type: str,
    recipient: str,
    payload: dict[str, Any],
) -> None:
    """
    Background task: send notification (email / webhook / Slack).
    Extend with actual provider integrations.
    """
    raise NotImplementedError(
        "Notification delivery is not configured for this prototype"
    )


@_queue.register("auto_escalate")
async def auto_escalate_async(
    *,
    tenant_id: str,
    case_id: str,
    escalation_target: str,
    reason: str,
    risk_score: float,
) -> None:
    """
    Background task: execute automatic escalation workflow.
    Updates case status and triggers notification.
    """
    from database.base import AsyncSessionLocal
    from database.repositories import CaseRepository
    from core.case_state_machine import CaseStateMachine
    from core.audit_logger import get_audit_logger
    from core.event_bus import DomainEvent, get_event_bus

    sm = CaseStateMachine()
    async with AsyncSessionLocal() as db:
        repo = CaseRepository(db, tenant_id)
        # Serialize scheduler/replica attempts before checking the state. The
        # second attempt observes ESCALATED and creates no duplicate event.
        case = await repo.get_for_update(case_id)
        if not case:
            logger.warning("auto_escalate: case %s not found", case_id)
            return

        if sm.can_transition(case.status, "ESCALATED"):
            original_status = case.status
            await repo.update_status(case_id=case_id, status="ESCALATED")
            await get_event_bus().publish(
                DomainEvent(
                    event_type=DomainEvent.CASE_STATUS_CHANGED,
                    tenant_id=tenant_id,
                    aggregate_type="case",
                    aggregate_id=case_id,
                    payload={
                        "from_status": original_status,
                        "to_status": "ESCALATED",
                        "reason": reason,
                        "risk_score": risk_score,
                    },
                ),
                db=db,
            )
            await db.commit()
            get_audit_logger().log_state_transition(
                tenant_id=tenant_id,
                case_id=case_id,
                from_status=original_status,
                to_status="ESCALATED",
                actor="scheduler",
            )
            logger.info(
                "auto_escalate: case %s escalated to %s (risk=%.1f)",
                case_id, escalation_target, risk_score,
            )
        else:
            logger.info(
                "auto_escalate: case %s already in state %s, skipping",
                case_id, case.status,
            )
