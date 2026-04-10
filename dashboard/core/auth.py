# dashboard/core/auth.py
"""
Auth state management — login, logout, token lifecycle.

Token is stored in st.session_state["auth_token"].
The JWT payload (role, tenant_id, email) is decoded client-side for display only.
All authoritative security decisions are made by the backend.

This module does NOT have a demo mode. A real backend is required.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional

import streamlit as st

from services.api_client import APIClient, AuthError, NetworkError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role / permission definitions (mirrors backend ROLE_PERMISSIONS)
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "operador":  {"read", "evaluate"},
    "legal":     {"read", "evaluate", "escalate"},
    "gerente":   {"read", "evaluate", "escalate", "override", "download"},
    "admin":     {"read", "evaluate", "escalate", "override", "download", "manage"},
    "auditor":   {"read", "download"},
}

ROLE_LABELS: dict[str, str] = {
    "operador":  "Operador",
    "legal":     "Legal",
    "gerente":   "Gerente",
    "admin":     "Admin",
    "auditor":   "Auditor",
}

ROLE_ICONS: dict[str, str] = {
    "operador":  "👤",
    "legal":     "⚖",
    "gerente":   "📊",
    "admin":     "🔧",
    "auditor":   "🔍",
}


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def is_authenticated() -> bool:
    return bool(st.session_state.get("auth_token"))


def get_token() -> Optional[str]:
    return st.session_state.get("auth_token")


def get_user() -> dict:
    """Return decoded user info. Never make security decisions from this — backend is authoritative."""
    return st.session_state.get("auth_user", {})


def get_role() -> str:
    return get_user().get("role", "operador")


def get_tenant_id() -> Optional[str]:
    return get_user().get("tenant_id")


def has_permission(perm: str) -> bool:
    role = get_role()
    return perm in ROLE_PERMISSIONS.get(role, set())


def get_tenant_config() -> dict:
    return st.session_state.get("tenant_config", {})


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

def login(email: str, password: str) -> tuple[bool, str]:
    """
    Authenticate against the backend.
    Returns (success, error_message).
    Requires URAKI_API_URL to be configured.
    """
    from services.api_client import BACKEND_CONFIGURED
    if not BACKEND_CONFIGURED:
        return False, (
            "El sistema no está conectado a un backend. "
            "Configura URAKI_API_URL y reinicia el servidor."
        )
    return _api_login(email, password)


def dev_login() -> None:
    """
    Inject a synthetic admin session for local development.
    Only runs when URAKI_ENV=development. No-op in any other environment.
    """
    from core.environment import is_development
    if not is_development():
        return
    st.session_state["auth_token"]    = "DEV_LOCAL_TOKEN"
    st.session_state["auth_user"]     = {
        "email":     "dev@local",
        "role":      "admin",
        "name":      "Dev Local",
        "tenant_id": "dev-tenant",
    }
    st.session_state["tenant_config"] = {}
    st.session_state["api_cache"]     = {}


def logout() -> None:
    keys = ["auth_token", "auth_user", "tenant_config", "api_cache",
            "_cache_tenant_id", "selected_case_id", "eval_result",
            "simulation_result", "audit_data", "action_result"]
    for key in keys:
        st.session_state.pop(key, None)


# ---------------------------------------------------------------------------
# Private — real API login
# ---------------------------------------------------------------------------

def _api_login(email: str, password: str) -> tuple[bool, str]:
    client = APIClient()
    try:
        resp = client.post_form("/auth/login", {
            "username": email,
            "password": password,
        })
    except NetworkError as e:
        return False, f"No se pudo conectar al servidor: {e}"
    except AuthError:
        return False, "Credenciales incorrectas."

    if resp.status_code == 503 and "no configurado" in (resp.error or "").lower():
        return False, resp.error or "Backend no disponible."

    if not resp.ok:
        return False, resp.error or "Error de autenticación."

    data  = resp.data or {}
    token = data.get("access_token", "")
    if not token:
        return False, "El servidor no devolvió un token de acceso."

    claims = _decode_jwt_claims(token)
    st.session_state["auth_token"] = token
    st.session_state["auth_user"]  = {
        "email":     email,
        "role":      data.get("role") or claims.get("role", "operador"),
        "name":      data.get("name") or claims.get("name") or email.split("@")[0],
        "tenant_id": data.get("tenant_id") or claims.get("tenant_id"),
        **{k: v for k, v in claims.items() if k not in ("role", "name", "tenant_id")},
    }
    st.session_state["api_cache"] = {}
    _load_tenant_config(token)
    return True, ""


def _load_tenant_config(token: str) -> None:
    """Fetch tenant configuration from backend. Non-critical — failure is logged, not raised."""
    from core.config_manager import validate_tenant_config
    client = APIClient(token=token)
    try:
        resp = client.get("/tenants/me", ttl=300)
        if resp.ok and isinstance(resp.data, dict):
            validated, warnings = validate_tenant_config(resp.data)
            st.session_state["tenant_config"] = validated
            if warnings:
                existing = st.session_state.get("schema_warnings", [])
                st.session_state["schema_warnings"] = existing + [
                    f"[tenant config] {w}" for w in warnings
                ]
    except Exception as exc:
        logger.warning("Could not load tenant config: %s", exc)


def _decode_jwt_claims(token: str) -> dict:
    """Client-side JWT payload decode (no signature verification — display only)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.b64decode(payload_b64))
    except Exception:
        return {}
