# dashboard/core/state_manager.py
"""
Centralized session state — single source of truth for all UI state.
Auth and tenant state live here alongside UI state.
"""
import streamlit as st
from datetime import datetime, timezone, timedelta

BOGOTA_TZ = timezone(timedelta(hours=-5))

_DEFAULTS: dict = {
    # Auth (managed by core/auth.py)
    "auth_token":              None,
    "auth_user":               {},
    "tenant_config":           {},
    # Tenant isolation (managed by core/tenant_manager.py)
    "_cache_tenant_id":        None,
    # API cache (managed by api_client.py)
    "api_cache":               {},
    # UI flow
    "selected_case_id":        None,
    "view_mode":               "flow",
    "queue_filter":            "all",
    "show_message":            False,
    # Resolved-case counter (current session, client-side only)
    "resolved_today":          0,
    "total_resolution_ms":     0,
    "case_start_time":         None,
    "last_resolved_id":        None,
    # Upload session state
    "upload_statuses":         {},
    # Evaluation state (per case)
    "evaluating_case_id":      None,
    "eval_result":             None,
    "eval_error":              None,
    # Simulation mode
    "simulation_open":         False,
    "simulation_result":       None,
    "simulation_case_id":      None,
    # Override state
    "override_open_for":       None,
    # Action engine
    "action_running":          False,
    "action_result":           None,
    "action_error":            None,
    # Audit timeline
    "audit_data":              None,
    "audit_case_id":           None,
    # Error/success banners
    "last_error":              None,
    "last_success":            None,
    # Backend state (populated on first API interaction)
    "backend_reachable":       None,   # None = not yet tested
    "backend_error":           None,
    # Schema validation warnings (populated by service layer)
    "schema_warnings":         [],
    # Quick Mode intake state
    "qi_case_type":            "mora",
    "qi_client_name":          "",
    "qi_overdue_days":         30,
    "qi_overdue_amount":       0,
    "qi_has_policy":           False,
    "qi_has_legal_action":     False,
    "qi_prev_count":           0,
    "qi_loading":              False,
    "qi_result":               None,
    "qi_edited_response":      "",
    "qi_mode":                 "basico",
    "qi_next_action":          "",
}


def init() -> None:
    for key, val in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = val


def get(key: str, default=None):
    return st.session_state.get(key, default)


def set(key: str, value) -> None:
    st.session_state[key] = value


def select_case(case_id: str | None) -> None:
    set("selected_case_id", case_id)
    set("case_start_time", datetime.now(BOGOTA_TZ))
    set("show_message", False)
    set("eval_result", None)
    set("eval_error", None)
    set("override_open_for", None)
    set("simulation_open", False)
    set("simulation_result", None)
    set("audit_data", None)
    set("action_result", None)
    set("action_error", None)


def record_resolution() -> None:
    start = get("case_start_time")
    if start:
        elapsed_ms = int((datetime.now(BOGOTA_TZ) - start).total_seconds() * 1000)
        set("resolved_today",      get("resolved_today") + 1)
        set("total_resolution_ms", get("total_resolution_ms") + elapsed_ms)
        set("last_resolved_id",    get("selected_case_id"))


def avg_resolution_ms() -> int:
    resolved = get("resolved_today")
    total    = get("total_resolution_ms")
    return total // resolved if resolved > 0 else 0


def advance_queue(case_service) -> None:
    """After resolving, auto-select the next highest-impact open case."""
    current  = get("selected_case_id")
    queue    = case_service.get_queue(exclude_closed=True)
    candidates = [c for c in queue if c["id"] != current and c.get("status") != "CLOSED"]
    if candidates:
        select_case(candidates[0]["id"])
    else:
        set("selected_case_id", None)
        set("case_start_time",  None)


# ── Flash message API ─────────────────────────────────────────────────────────

def flash_error(msg: str) -> None:
    set("last_error", msg)


def flash_success(msg: str) -> None:
    set("last_success", msg)


def consume_flash() -> tuple[str | None, str | None]:
    """Read and clear flash messages atomically. Returns (error, success)."""
    err = get("last_error")
    ok  = get("last_success")
    set("last_error",   None)
    set("last_success", None)
    return err, ok


# ── Schema warning API ────────────────────────────────────────────────────────

def add_schema_warning(msg: str) -> None:
    warnings = get("schema_warnings") or []
    warnings.append(msg)
    set("schema_warnings", warnings)


def consume_schema_warnings() -> list[str]:
    warnings = get("schema_warnings") or []
    set("schema_warnings", [])
    return warnings


# ── Backward-compat aliases ───────────────────────────────────────────────────

def set_error(msg: str | None) -> None:
    set("last_error", msg)


def set_success(msg: str | None) -> None:
    set("last_success", msg)
