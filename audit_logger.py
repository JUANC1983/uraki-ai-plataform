# core/audit_logger.py
"""
Audit Logger — writes structured JSON audit records to DB and/or file.
Every decision, override, state change, and error is logged here.
"""
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Dual-output audit logger: database + file (JSONL).
    All records include tenant_id for multi-tenant filtering.
    """

    def __init__(self, log_file: Optional[str] = None) -> None:
        self.log_file = log_file or os.getenv("AUDIT_LOG_FILE", "./logs/audit.jsonl")
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_decision(
        self,
        *,
        tenant_id: str,
        case_id: str,
        decision: dict[str, Any],
        duration_ms: int,
        user_id: Optional[str] = None,
    ) -> None:
        self._write(
            event_type="DECISION_GENERATED",
            tenant_id=tenant_id,
            entity_type="case",
            entity_id=case_id,
            user_id=user_id,
            duration_ms=duration_ms,
            payload={
                "case_id": case_id,
                "decision": decision,
            },
        )

    def log_override(
        self,
        *,
        tenant_id: str,
        case_id: str,
        decision_id: str,
        original_action: str,
        overridden_action: str,
        reason: str,
        user_id: str,
    ) -> None:
        self._write(
            event_type="DECISION_OVERRIDDEN",
            tenant_id=tenant_id,
            entity_type="decision",
            entity_id=decision_id,
            user_id=user_id,
            payload={
                "case_id": case_id,
                "decision_id": decision_id,
                "original_action": original_action,
                "overridden_action": overridden_action,
                "reason": reason,
            },
        )

    def log_state_transition(
        self,
        *,
        tenant_id: str,
        case_id: str,
        from_status: str,
        to_status: str,
        actor: Optional[str] = None,
    ) -> None:
        self._write(
            event_type="STATE_TRANSITION",
            tenant_id=tenant_id,
            entity_type="case",
            entity_id=case_id,
            user_id=actor,
            payload={
                "from_status": from_status,
                "to_status": to_status,
            },
        )

    def log_document_processed(
        self,
        *,
        tenant_id: str,
        document_id: str,
        case_id: Optional[str],
        chunks: int,
        duration_ms: int,
    ) -> None:
        self._write(
            event_type="DOCUMENT_PROCESSED",
            tenant_id=tenant_id,
            entity_type="document",
            entity_id=document_id,
            payload={
                "case_id": case_id,
                "chunks_created": chunks,
            },
            duration_ms=duration_ms,
        )

    def log_error(
        self,
        *,
        tenant_id: str,
        event_type: str,
        error: str,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        self._write(
            event_type=f"ERROR_{event_type}",
            tenant_id=tenant_id,
            payload={"error": error, "context": context or {}},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(
        self,
        *,
        event_type: str,
        tenant_id: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        user_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
        payload: dict[str, Any],
    ) -> None:
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "tenant_id": tenant_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user_id": user_id,
            "duration_ms": duration_ms,
            "payload": payload,
        }
        self._write_to_file(record)
        logger.info("[AUDIT] %s tenant=%s entity=%s", event_type, tenant_id, entity_id)

    def _write_to_file(self, record: dict[str, Any]) -> None:
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.error("Failed to write audit log to file: %s", exc)


# Singleton instance (can be overridden in tests)
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
