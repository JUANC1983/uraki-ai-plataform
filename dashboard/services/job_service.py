# dashboard/services/job_service.py
"""
Background job service — async processing for document parsing, simulations, analytics.

Backend exposes a simple job queue pattern:
  POST /jobs                → submit a job, returns {job_id, status: "queued"}
  GET  /jobs/{job_id}       → poll status
  GET  /cases/{id}/jobs     → list jobs for a case

Job statuses: queued → running → completed | failed

The UI polls using st.rerun() with exponential backoff stored in session state.
"""
from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from services.api_client import AuthError, NetworkError, get_client

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_POLL_INTERVAL_S   = [2, 4, 8, 15, 30]   # backoff in seconds


def _client():
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


class JobService:

    def submit(
        self,
        job_type:   str,
        case_id:    Optional[str] = None,
        payload:    Optional[dict] = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        """
        POST /jobs — submit an async job.
        job_types: "document_parse" | "simulation" | "analytics_refresh"
        Returns (job_result, error).
        """
        body = {
            "job_type": job_type,
            "payload":  payload or {},
        }
        if case_id:
            body["case_id"] = case_id

        try:
            resp = _client().post("/jobs", json=body)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al enviar trabajo"
        return resp.data, None

    def get_status(self, job_id: str) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /jobs/{job_id} — poll job status.
        Returns (job_dict, error).
        job_dict shape: {job_id, status, progress, result, error, created_at, updated_at}
        """
        try:
            resp = _client().get(f"/jobs/{job_id}", ttl=0)  # never cache job status
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al consultar trabajo"
        return resp.data, None

    def get_case_jobs(self, case_id: str) -> tuple[list[dict], Optional[str]]:
        """
        GET /cases/{id}/jobs — list all jobs for a case.
        """
        try:
            resp = _client().get(f"/cases/{case_id}/jobs", ttl=15)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar trabajos"
        return resp.items or [], None

    def is_terminal(self, status: str) -> bool:
        return status in _TERMINAL_STATUSES


def render_job_status_html(job: dict, c: dict) -> str:
    """Render a single job status as HTML."""
    status   = job.get("status", "unknown")
    job_type = job.get("job_type", "—")
    progress = job.get("progress", 0)
    error    = job.get("error", "")
    job_id   = job.get("job_id", "?")[:12]

    color = {
        "completed": "#22C55E",
        "failed":    "#EF4444",
        "running":   "#F59E0B",
        "queued":    "#3B82F6",
    }.get(status, c["text_muted"])

    icon = {
        "completed": "✓",
        "failed":    "✕",
        "running":   "⋯",
        "queued":    "◌",
    }.get(status, "·")

    progress_bar = ""
    if status == "running" and progress > 0:
        progress_bar = f"""
        <div style="height:2px;background:{c['bg_secondary']};border-radius:2px;margin-top:4px;">
            <div style="width:{progress}%;height:100%;background:{color};border-radius:2px;"></div>
        </div>"""

    error_line = f'<div style="font-size:10px;color:#EF4444;margin-top:3px;">{error}</div>' if error else ""

    return f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:6px;padding:0.5rem 0.75rem;margin-bottom:4px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-size:11px;color:{c['text_secondary']};">{job_type}</span>
            <span style="font-size:11px;color:{color};font-weight:600;">
                {icon} {status}
                <span style="color:{c['text_muted']};font-weight:400;"> · {job_id}</span>
            </span>
        </div>
        {progress_bar}
        {error_line}
    </div>"""
