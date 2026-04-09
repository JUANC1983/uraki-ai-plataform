# dashboard/services/sla_service.py
"""
SLA monitoring service.

Tracks:
  - Decision latency (ms per evaluation)
  - Resolution time (days from case creation to close)
  - SLA breach detection (exceeds tenant-configured thresholds)

Client-side tracking:
  Resolution times are measured in the session via state_manager.
  Decision latency is taken from the decision.duration_ms field.

Backend tracking:
  GET /sla/summary  — aggregate SLA metrics
  GET /sla/breaches — cases that breached SLA
"""
from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from services.api_client import AuthError, NetworkError, get_client, BACKEND_CONFIGURED
from core.config_manager import get_sla

logger = logging.getLogger(__name__)


def _client():
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


class SLAService:

    def get_summary(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /sla/summary
        Returns aggregate SLA metrics.
        Expected shape:
        {
          "decisions_on_time":     int,
          "decisions_breached":    int,
          "resolutions_on_time":   int,
          "resolutions_breached":  int,
          "avg_decision_ms":       int,
          "avg_resolution_days":   float,
          "breach_rate":           float,  # 0–1
          "period_days":           int,
        }
        """
        try:
            resp = _client().get("/sla/summary", ttl=120)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al cargar métricas SLA"
        return resp.data, None

    def get_breaches(self, limit: int = 20) -> tuple[list[dict], Optional[str]]:
        """
        GET /sla/breaches?limit=N
        Returns cases that breached SLA.
        Each item: {case_id, breach_type, threshold, actual, created_at}
        """
        try:
            resp = _client().get("/sla/breaches", params={"limit": limit}, ttl=60)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar brechas SLA"
        return resp.items or [], None

    def check_decision_sla(self, duration_ms: int) -> tuple[bool, str]:
        """
        Client-side SLA check for a single decision.
        Returns (within_sla, message).
        """
        thresholds = get_sla()
        limit_ms   = thresholds.get("decision_max_ms", 30_000)
        if duration_ms <= 0:
            return True, ""
        within = duration_ms <= limit_ms
        if within:
            return True, f"{duration_ms}ms (límite: {limit_ms}ms)"
        return False, f"SLA BREACH: {duration_ms}ms excede el límite de {limit_ms}ms"

    def check_resolution_sla(self, created_at_iso: str) -> tuple[bool, str]:
        """
        Client-side SLA check for resolution time.
        Returns (within_sla, message).
        """
        from utils.time import bogota_now
        from datetime import datetime, timezone, timedelta
        thresholds  = get_sla()
        limit_days  = thresholds.get("resolution_max_days", 30)
        try:
            ts = created_at_iso
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            created = datetime.fromisoformat(ts)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone(timedelta(hours=-5)))
            elapsed_days = (bogota_now() - created).days
            within = elapsed_days <= limit_days
            if within:
                return True, f"{elapsed_days}d (límite: {limit_days}d)"
            return False, f"SLA BREACH: {elapsed_days}d excede el límite de {limit_days}d"
        except Exception:
            return True, ""


def render_sla_badge_html(within: bool, message: str, c: dict) -> str:
    """Return a small inline SLA status badge."""
    if not message:
        return ""
    color = c.get("success", "#22C55E") if within else c.get("danger", "#EF4444")
    bg    = "rgba(34,197,94,0.10)" if within else "rgba(239,68,68,0.10)"
    icon  = "✓" if within else "⚠"
    return (
        f'<span style="background:{bg};color:{color};border-radius:4px;'
        f'padding:1px 7px;font-size:10px;font-weight:600;">'
        f'{icon} SLA {message}</span>'
    )
