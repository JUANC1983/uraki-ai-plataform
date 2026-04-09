# dashboard/services/event_service.py
"""
Internal event store service.

Every significant action in the UI emits an event to the backend.
Events are immutable, append-only, and serve as the authoritative audit trail.

Event shape:
{
  "event_id":   str (UUID, generated server-side),
  "tenant_id":  str,
  "case_id":    str | None,
  "event_type": str,
  "actor":      str (user email or "system"),
  "payload":    dict,
  "timestamp":  ISO-8601 str,
}

Event types:
  case.viewed          — operator opened a case
  case.evaluated       — rule engine was triggered
  case.overridden      — decision was manually overridden
  case.resolved        — case was closed
  case.escalated       — case was escalated
  case.status_changed  — status transition
  document.uploaded    — document was uploaded
  action.sent_email    — email was sent
  action.assigned_task — task was created
  action.notified      — stakeholder notification sent
  simulation.run       — what-if simulation executed
  audit.viewed         — audit timeline was opened
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

import streamlit as st

from services.api_client import AuthError, NetworkError, get_client

logger = logging.getLogger(__name__)


def _client():
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


def _actor() -> str:
    return st.session_state.get("auth_user", {}).get("email", "system")


def _tenant_id() -> Optional[str]:
    return st.session_state.get("auth_user", {}).get("tenant_id")


class EventService:

    def emit(
        self,
        event_type: str,
        case_id:    Optional[str] = None,
        payload:    Optional[dict] = None,
    ) -> Optional[str]:
        """
        POST /events — emit an event to the backend event store.
        Returns event_id on success, None on failure.
        Failures are logged but never raised to the UI.
        """
        body = {
            "event_type": event_type,
            "actor":      _actor(),
            "tenant_id":  _tenant_id(),
            "case_id":    case_id,
            "payload":    payload or {},
            "client_event_id": str(uuid.uuid4()),  # idempotency key
        }
        try:
            resp = _client().post("/events", json=body)
            if resp.ok and isinstance(resp.data, dict):
                return resp.data.get("event_id")
            logger.warning("Event emission failed (%s): %s", event_type, resp.error)
        except (AuthError, NetworkError, Exception) as exc:
            logger.warning("Event emission error (%s): %s", event_type, exc)
        return None

    def get_case_events(
        self,
        case_id: str,
        limit: int = 50,
    ) -> tuple[list[dict], Optional[str]]:
        """
        GET /cases/{id}/events — fetch all events for a case.
        Used by the audit timeline.
        """
        try:
            resp = _client().get(f"/cases/{case_id}/events",
                                 params={"limit": limit}, ttl=20)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar eventos"

        raw = resp.data or {}
        events = raw.get("events", []) if isinstance(raw, dict) else raw
        return events if isinstance(events, list) else [], None

    def get_tenant_events(
        self,
        limit:       int = 200,
        event_types: Optional[list[str]] = None,
    ) -> tuple[list[dict], Optional[str]]:
        """
        GET /events — fetch recent events for the tenant (admin/gerente only).
        """
        params: dict = {"limit": limit}
        if event_types:
            params["types"] = ",".join(event_types)
        try:
            resp = _client().get("/events", params=params, ttl=30)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar eventos"

        return resp.items or [], None


# ── Convenience emitters (called from UI components) ─────────────────────────

_svc: Optional[EventService] = None


def _get() -> EventService:
    global _svc
    if _svc is None:
        _svc = EventService()
    return _svc


def emit_case_viewed(case_id: str) -> None:
    _get().emit("case.viewed", case_id=case_id)


def emit_case_evaluated(case_id: str, rule_id: str = "") -> None:
    _get().emit("case.evaluated", case_id=case_id, payload={"rule_id": rule_id})


def emit_case_overridden(case_id: str, decision_id: str, from_action: str, to_action: str, reason: str) -> None:
    _get().emit("case.overridden", case_id=case_id, payload={
        "decision_id": decision_id,
        "from_action": from_action,
        "to_action":   to_action,
        "reason":      reason,
    })


def emit_case_resolved(case_id: str) -> None:
    _get().emit("case.resolved", case_id=case_id)


def emit_case_escalated(case_id: str, target: str) -> None:
    _get().emit("case.escalated", case_id=case_id, payload={"target": target})


def emit_document_uploaded(case_id: str, filename: str, doc_type: str) -> None:
    _get().emit("document.uploaded", case_id=case_id, payload={
        "filename": filename, "doc_type": doc_type,
    })


def emit_simulation_run(case_id: str, overrides: dict) -> None:
    _get().emit("simulation.run", case_id=case_id, payload={"overrides": overrides})


def emit_audit_viewed(case_id: str) -> None:
    _get().emit("audit.viewed", case_id=case_id)


def emit_action_sent(case_id: str, action_type: str, action_id: str = "") -> None:
    _get().emit(f"action.{action_type}", case_id=case_id, payload={"action_id": action_id})
