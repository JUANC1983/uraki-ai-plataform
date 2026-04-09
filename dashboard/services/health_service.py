# dashboard/services/health_service.py
"""
Health & readiness service.

Polls the backend /health and /ready endpoints to surface system status
in the topbar and observability dashboard.

/health  — liveness: is the process running?
/ready   — readiness: is the backend ready to serve traffic?
           includes DB connectivity, rule engine status, etc.

Response shapes expected from backend:

GET /health:
{
  "status": "ok" | "degraded" | "down",
  "version": str,
  "uptime_seconds": int,
}

GET /ready:
{
  "ready": bool,
  "checks": {
    "database":    {"ok": bool, "latency_ms": int},
    "rule_engine": {"ok": bool, "latency_ms": int},
    "cache":       {"ok": bool, "latency_ms": int},
    "llm":         {"ok": bool, "latency_ms": int},
  }
}
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import streamlit as st

from services.api_client import NetworkError, get_client, BACKEND_CONFIGURED

logger = logging.getLogger(__name__)

_HEALTH_TTL   = 30   # seconds between health checks
_READY_TTL    = 60   # seconds between readiness checks


def _client():
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


class HealthService:

    def get_health(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /health — liveness check.
        Returns (health_dict, error).
        Never uses the session cache so it always reflects real-time status.
        """
        if not BACKEND_CONFIGURED:
            return {"status": "down", "reason": "Backend not configured"}, None

        try:
            resp = _client().get("/health", ttl=_HEALTH_TTL)
        except NetworkError as e:
            return {"status": "down", "reason": str(e)}, None
        except Exception as e:
            return {"status": "down", "reason": str(e)}, None

        if not resp.ok:
            return {"status": "down", "reason": resp.error or f"HTTP {resp.status_code}"}, None

        return resp.data or {"status": "ok"}, None

    def get_ready(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /ready — readiness check with component breakdown.
        Returns (ready_dict, error).
        """
        if not BACKEND_CONFIGURED:
            return {
                "ready": False,
                "checks": {},
                "reason": "Backend not configured",
            }, None

        try:
            resp = _client().get("/ready", ttl=_READY_TTL)
        except NetworkError as e:
            return {"ready": False, "checks": {}, "reason": str(e)}, None
        except Exception as e:
            return {"ready": False, "checks": {}, "reason": str(e)}, None

        if resp.status_code == 503:
            # 503 is the standard "not ready" response — parse it anyway
            data = resp.data or {"ready": False, "checks": {}}
            return data, None

        if not resp.ok:
            return {"ready": False, "checks": {}, "reason": resp.error}, None

        return resp.data or {"ready": True, "checks": {}}, None

    def get_combined_status(self) -> dict:
        """
        Return a combined health+readiness summary for the UI.
        Shape: {
          "overall":   "ok" | "degraded" | "down",
          "backend_version": str,
          "ready":     bool,
          "checks":    dict,
          "uptime_s":  int,
        }
        """
        health, _ = self.get_health()
        ready_data, _ = self.get_ready()

        h = health or {}
        r = ready_data or {}

        overall = h.get("status", "down")
        if overall == "ok" and not r.get("ready", True):
            overall = "degraded"

        return {
            "overall":         overall,
            "backend_version": h.get("version", "—"),
            "ready":           r.get("ready", False),
            "checks":          r.get("checks", {}),
            "uptime_s":        h.get("uptime_seconds", 0),
        }
