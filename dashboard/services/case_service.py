# dashboard/services/case_service.py
"""
Case service — single source of truth for case data.

All methods call the FastAPI backend. No demo mode, no fallback data.
If the backend is unavailable, error strings are returned to the caller.

Priority scoring uses a dynamic impact formula instead of static label ordering.
"""
from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from services.api_client import APIClient, APIResponse, AuthError, NetworkError, get_client
from services.schema import validate_case, validate_case_list, validate_audit_events
from core.schema_evolution import migrate_case, stamp_current_case
import core.state_manager as sm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> APIClient:
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


def _impact_score(case: dict) -> float:
    """
    Dynamic priority score — higher = more urgent.
    Replaces static PRIORITY label sorting with a computed impact signal.

    Dimensions:
      Risk score (0-40 pts)    — from decision engine
      Overdue amount (0-30 pts) — capped at 15M COP
      Overdue days (0-15 pts)   — capped at 150 days
      Legal flag (+10)
      Escalation required (+5)
      Has legal action (+5)
    """
    d = case.get("latest_decision") or {}
    score  = float(d.get("risk_score", 0)) * 0.40               # 0–40 pts
    score += min(float(case.get("overdue_amount", 0)) / 1_000_000 * 2, 30.0)  # 0–30 pts
    score += min(int(case.get("overdue_days", 0)) * 0.10, 15.0)               # 0–15 pts
    if d.get("legal_flag"):                score += 10.0
    if d.get("escalation_required"):        score += 5.0
    if case.get("has_legal_action"):        score += 5.0
    return score


# ---------------------------------------------------------------------------
# CaseService
# ---------------------------------------------------------------------------

class CaseService:

    # ── Read ───────────────────────────────────────────────────────────

    def get_all(self, status_filter: Optional[str] = None) -> tuple[list[dict], Optional[str]]:
        """
        Returns (cases, error_message).
        error_message is None on success.
        Cases are sorted by dynamic impact score (highest first).
        """
        params: dict = {"limit": 200}
        if status_filter:
            params["status"] = status_filter

        try:
            resp = _client().get("/cases", params=params, ttl=15)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión al backend: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar casos"

        raw_items = resp.items

        # Run schema migrations before validation — old cases remain valid
        migrated_items = [migrate_case(item) if isinstance(item, dict) else item
                          for item in raw_items]

        # Schema validation — partial success: log and warn on bad items
        valid, errors = validate_case_list(migrated_items)
        if errors:
            for err in errors:
                logger.warning(err)
                sm.add_schema_warning(err)

        return sorted(valid, key=_impact_score, reverse=True), None

    def get_queue(self, exclude_closed: bool = False) -> list[dict]:
        """Convenience wrapper — returns list only (swallows error for queue display)."""
        cases, _ = self.get_all()
        if exclude_closed:
            cases = [c for c in cases if c.get("status") != "CLOSED"]
        return cases

    def get_by_id(self, case_id: str) -> tuple[Optional[dict], Optional[str]]:
        try:
            resp = _client().get(f"/cases/{case_id}", ttl=10)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if resp.status_code == 404:
            return None, "Caso no encontrado"
        if not resp.ok:
            return None, resp.error or "Error al cargar el caso"

        try:
            migrated = migrate_case(resp.data)
            return validate_case(migrated), None
        except Exception as exc:
            return None, f"Respuesta del servidor no válida: {exc}"

    def get_audit_log(self, case_id: str) -> tuple[list[dict], Optional[str]]:
        """Fetch the full audit timeline for a case."""
        try:
            resp = _client().get(f"/cases/{case_id}/audit", ttl=30)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar el historial"

        raw = resp.data or {}
        events = raw.get("events", []) if isinstance(raw, dict) else raw
        return validate_audit_events(events), None

    def get_metrics(self) -> dict:
        """Aggregate metrics from the full case list."""
        cases, _ = self.get_all()
        total     = len(cases)
        closed    = sum(1 for c in cases if c.get("status") == "CLOSED")
        escalated = sum(1 for c in cases if c.get("status") == "ESCALATED")
        new       = sum(1 for c in cases if c.get("status") == "NEW")
        in_review = sum(1 for c in cases if c.get("status") == "IN_REVIEW")
        critical  = sum(1 for c in cases
                        if c.get("priority") == "CRITICAL" and c.get("status") != "CLOSED")
        return {
            "total":     total,
            "closed":    closed,
            "escalated": escalated,
            "new":       new,
            "in_review": in_review,
            "critical":  critical,
            "pending":   total - closed,
        }

    # ── Mutations ──────────────────────────────────────────────────────

    def transition(self, case_id: str, target_status: str, reason: str = "") -> Optional[str]:
        """
        Transition a case to a new status.
        Returns error string on failure, None on success.
        """
        try:
            resp = _client().post(
                f"/cases/{case_id}/transition",
                json={"target_status": target_status, "reason": reason},
            )
        except AuthError as e:
            return str(e)
        except NetworkError as e:
            return f"Sin conexión: {e}"

        if not resp.ok:
            return resp.error or f"Error al cambiar estado a {target_status}"

        _client().invalidate(f"/cases/{case_id}")
        _client().invalidate("/cases")
        return None

    def resolve_case(self, case_id: str) -> Optional[str]:
        return self.transition(case_id, "CLOSED", reason="Resuelto por operador")

    def escalate_case(self, case_id: str, target: str = "") -> Optional[str]:
        return self.transition(case_id, "ESCALATED", reason=f"Escalado a {target}")

    def set_status(self, case_id: str, status: str) -> Optional[str]:
        return self.transition(case_id, status)

    def evaluate(self, case_id: str) -> tuple[Optional[dict], Optional[str]]:
        """
        Trigger the rule engine for a case.
        Returns (evaluate_response, error).
        """
        try:
            resp = _client().post(f"/cases/{case_id}/evaluate")
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al evaluar el caso"

        _client().invalidate(f"/cases/{case_id}")
        _client().invalidate("/cases")
        return resp.data, None

    def create(self, payload: dict) -> tuple[Optional[dict], Optional[str]]:
        """
        Create a new case from a Quick Mode intake payload.
        Returns (created_case, error).
        """
        try:
            resp = _client().post("/cases", json=payload)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al crear el caso"

        _client().invalidate("/cases")
        try:
            created = resp.data or {}
            stamped = stamp_current_case(created)
            return stamped, None
        except Exception as exc:
            return resp.data, None

    def simulate(self, case_id: str, overrides: dict) -> tuple[Optional[dict], Optional[str]]:
        """
        Run a what-if simulation against the rule engine.
        `overrides` modifies case inputs for this run only — no persistence.
        Returns (simulated_decision, error).
        """
        try:
            resp = _client().post(
                f"/cases/{case_id}/simulate",
                json={"overrides": overrides},
            )
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error en simulación"

        return resp.data, None
