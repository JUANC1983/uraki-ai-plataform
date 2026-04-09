# dashboard/services/action_service.py
"""
Action Engine service — executes post-decision actions.

Actions:
  send_email        → POST /actions/send_email
  assign_task       → POST /tasks
  notify_stakeholders → POST /actions/notify
  escalate          → POST /cases/{id}/transition (ESCALATED)
  get_status        → GET  /actions/{action_id}
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


class ActionService:

    def send_email(
        self,
        case_id:   str,
        recipient: str,
        subject:   str,
        body:      str,
    ) -> tuple[Optional[dict], Optional[str]]:
        """
        Send an email to the client or a stakeholder.
        Returns (action_result, error).
        """
        try:
            resp = _client().post("/actions/send_email", json={
                "case_id":   case_id,
                "recipient": recipient,
                "subject":   subject,
                "body":      body,
            })
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al enviar correo"

        return resp.data, None

    def assign_task(
        self,
        case_id:     str,
        assignee:    str,
        title:       str,
        description: str,
        due_date:    Optional[str] = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        """
        Assign a follow-up task to a team member.
        Returns (task_result, error).
        """
        payload: dict = {
            "case_id":     case_id,
            "assignee":    assignee,
            "title":       title,
            "description": description,
        }
        if due_date:
            payload["due_date"] = due_date

        try:
            resp = _client().post("/tasks", json=payload)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al crear tarea"

        return resp.data, None

    def notify_stakeholders(
        self,
        case_id:    str,
        channel:    str,
        message:    str,
        recipients: list[str] | None = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        """
        Notify stakeholders via a channel (email, slack, webhook).
        Returns (notification_result, error).
        """
        try:
            resp = _client().post("/actions/notify", json={
                "case_id":    case_id,
                "channel":    channel,
                "message":    message,
                "recipients": recipients or [],
            })
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al notificar"

        return resp.data, None

    def get_status(self, action_id: str) -> tuple[Optional[dict], Optional[str]]:
        """Poll the status of an async action."""
        try:
            resp = _client().get(f"/actions/{action_id}", ttl=5)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al consultar acción"

        return resp.data, None

    def get_case_actions(self, case_id: str) -> tuple[list[dict], Optional[str]]:
        """Return all actions executed for a case."""
        try:
            resp = _client().get(f"/cases/{case_id}/actions", ttl=15)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar acciones"

        return resp.items or [], None
