# dashboard/services/analytics_service.py
"""
Analytics service — system observability data for the internal dashboard.

Endpoints:
  GET /analytics/summary       → high-level KPIs
  GET /analytics/decisions     → decisions over time
  GET /analytics/overrides     → override stats by rule
  GET /analytics/rules         → most triggered rules
  GET /analytics/resolution    → avg resolution times
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


class AnalyticsService:

    def get_summary(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /analytics/summary
        High-level system KPIs for the observability dashboard.
        Expected shape:
        {
          "decisions_today": int,
          "decisions_this_week": int,
          "overrides_today": int,
          "override_rate": float,   # 0–1
          "avg_resolution_ms": int,
          "failure_rate": float,    # evaluation failures / total attempts
          "backend_version": str,
          "rules_active": int,
        }
        """
        try:
            resp = _client().get("/analytics/summary", ttl=60)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al cargar resumen de analytics"

        return resp.data, None

    def get_decisions_daily(self, days: int = 14) -> tuple[list[dict], Optional[str]]:
        """
        GET /analytics/decisions/daily?days=N
        Returns list of {date, count, override_count} for the last N days.
        """
        try:
            resp = _client().get("/analytics/decisions/daily",
                                 params={"days": days}, ttl=120)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar datos diarios"

        return resp.items or resp.data or [], None

    def get_override_stats(self) -> tuple[list[dict], Optional[str]]:
        """
        GET /analytics/overrides
        Returns per-rule override counts and reasons.
        """
        try:
            resp = _client().get("/analytics/overrides", ttl=120)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar overrides"

        return resp.items or resp.data or [], None

    def get_top_rules(self, limit: int = 10) -> tuple[list[dict], Optional[str]]:
        """
        GET /analytics/rules?limit=N
        Returns the most triggered rules.
        """
        try:
            resp = _client().get("/analytics/rules",
                                 params={"limit": limit}, ttl=120)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar reglas"

        return resp.items or resp.data or [], None

    def get_resolution_times(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /analytics/resolution
        Returns avg, p50, p90, p99 resolution times in ms.
        """
        try:
            resp = _client().get("/analytics/resolution", ttl=120)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al cargar tiempos"

        return resp.data, None

    def get_learning_indicators(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /analytics/learning
        Returns system learning / improvement metrics.
        Shape: {
          "accuracy_trend":       list[{date, accuracy}],
          "override_trend":       list[{date, override_rate}],
          "decisions_total":      int,
          "decisions_trend":      float,   # % change vs prior period
          "override_rate_trend":  float,   # % change (negative = improved)
          "avg_rating":           float,   # 1–5 from operator feedback
          "total_ratings":        int,
          "memory_fingerprints":  int,
          "similar_case_matches": int,
        }
        """
        try:
            resp = _client().get("/analytics/learning", ttl=180)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al cargar indicadores de aprendizaje"

        return resp.data, None
