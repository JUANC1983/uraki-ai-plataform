# dashboard/core/tenant_manager.py
"""
Multi-tenant isolation layer.

Verifies that cached data belongs to the current tenant on every Streamlit run.
Flushes all caches on tenant switch to prevent data leakage.

Usage — call at start of every app cycle:
    from core.tenant_manager import assert_tenant_isolation
    assert_tenant_isolation()
"""
from __future__ import annotations
import streamlit as st


# ── Reads ────────────────────────────────────────────────────────────────────

def get_tenant_id() -> str | None:
    return st.session_state.get("auth_user", {}).get("tenant_id")


def get_tenant_config() -> dict:
    return st.session_state.get("tenant_config", {})


def get_tenant_header() -> dict[str, str]:
    """Return the X-Tenant-ID header dict for injection into API requests."""
    tid = get_tenant_id()
    return {"X-Tenant-ID": tid} if tid else {}


def get_tenant_branding() -> dict:
    """
    Return branding overrides from tenant config.
    Falls back to URAKI defaults if tenant config is not yet loaded.
    """
    cfg = get_tenant_config()
    branding = cfg.get("branding") or {}
    return {
        "primary_color": branding.get("primary_color") or "#E85D2A",
        "company_name":  (
            cfg.get("name")
            or cfg.get("config", {}).get("tone_settings", {}).get("company_name")
            or "URAKI OPS"
        ),
        "logo_url": branding.get("logo_url"),
        "plan":     cfg.get("plan") or "standard",
    }


# ── Isolation enforcement ─────────────────────────────────────────────────────

def assert_tenant_isolation() -> None:
    """
    Call once at the beginning of every Streamlit app cycle.

    Detects if the authenticated tenant has changed since the last run
    and flushes all caches to prevent cross-tenant data leakage.
    """
    current_tid = get_tenant_id()
    cached_tid  = st.session_state.get("_cache_tenant_id")

    if cached_tid is not None and cached_tid != current_tid:
        _flush_all_caches()

    st.session_state["_cache_tenant_id"] = current_tid


def _flush_all_caches() -> None:
    """Hard flush of all session-scoped caches."""
    keys_to_clear = [
        "api_cache",
        "eval_result",
        "eval_error",
        "selected_case_id",
        "simulation_result",
        "audit_data",
        "action_result",
        "upload_statuses",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            st.session_state[k] = {} if k == "api_cache" else None
