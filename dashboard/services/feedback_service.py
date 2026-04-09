# dashboard/services/feedback_service.py
"""
Feedback loop service — tracks override history and rule accuracy.

Every override feeds into the feedback registry so operators and managers
can see which rules fail most often and adjust thresholds accordingly.
"""
from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from services.api_client import AuthError, NetworkError, get_client

logger = logging.getLogger(__name__)


def _client():
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


class FeedbackService:

    def get_registry(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /feedback_registry
        Returns aggregated override stats per rule.
        Shape: {
          "total_overrides": int,
          "rules": [
            {"rule_id": str, "override_count": int, "accuracy_rate": float, ...}
          ]
        }
        """
        try:
            resp = _client().get("/feedback_registry", ttl=60)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al cargar el registro de feedback"

        return resp.data, None

    def get_rule_accuracy(self) -> tuple[list[dict], Optional[str]]:
        """
        GET /analytics/rules
        Returns per-rule accuracy and override counts.
        """
        try:
            resp = _client().get("/analytics/rules", ttl=120)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar estadísticas de reglas"

        return resp.items or resp.data or [], None

    def record_feedback(
        self,
        decision_id: str,
        rule_id: str,
        original_action: str,
        overridden_action: str,
        reason: str,
        operator_id: str,
    ) -> Optional[str]:
        """
        POST /feedback_registry
        Called automatically after a successful override.
        Returns error string or None.
        """
        try:
            resp = _client().post("/feedback_registry", json={
                "decision_id":       decision_id,
                "rule_id":           rule_id,
                "original_action":   original_action,
                "overridden_action": overridden_action,
                "reason":            reason,
                "operator_id":       operator_id,
            })
        except AuthError as e:
            return str(e)
        except NetworkError as e:
            return f"Sin conexión: {e}"

        if not resp.ok:
            logger.warning("Feedback record failed: %s", resp.error)
            return resp.error or "Error al registrar feedback"

        _client().invalidate("/feedback_registry")
        _client().invalidate("/analytics/rules")
        return None

    def get_frequently_overridden(self, limit: int = 5) -> list[dict]:
        """
        Convenience: return top N most overridden rules.
        Returns empty list on error.
        """
        rules, _ = self.get_rule_accuracy()
        sorted_rules = sorted(
            [r for r in rules if isinstance(r, dict)],
            key=lambda r: r.get("override_count", 0),
            reverse=True,
        )
        return sorted_rules[:limit]
