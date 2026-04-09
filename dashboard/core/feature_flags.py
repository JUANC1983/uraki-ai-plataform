# dashboard/core/feature_flags.py
"""
Feature flag system — per-tenant, runtime-evaluated, no-redeploy.

Architecture:
  - Flags are defined with a canonical name, description, and default value.
  - Tenant-level overrides come from the backend (GET /tenants/me → config.modules
    OR a dedicated GET /feature-flags endpoint if present).
  - Operator-level overrides (for testing) come from URAKI_FLAGS env var (dev only).
  - Evaluation order: env override > tenant config > registered default.

Adding a new flag:
  1. Call register_flag("my_flag", default=False, description="What it does")
     at module load time (e.g. at the bottom of this file).
  2. Check with: is_enabled("my_flag")
  3. No redeploy needed — tenant config changes propagate on next config refresh.

Flag names correspond 1:1 with the `config.modules` dict in the tenant config
so that enabling a module in the backend config automatically enables the flag.

Flags that are NOT in config.modules can be independently controlled via the
dedicated /feature-flags endpoint (future) or the URAKI_FLAGS env var.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import streamlit as st

logger = logging.getLogger(__name__)


# ── Flag definition ───────────────────────────────────────────────────────────

@dataclass
class FlagDefinition:
    name:        str
    default:     bool
    description: str
    rollout_pct: int = 100   # 0–100 percent rollout (100 = fully rolled out)


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, FlagDefinition] = {}


def register_flag(name: str, *, default: bool, description: str, rollout_pct: int = 100) -> None:
    """Register a feature flag definition. Call at module load time."""
    _REGISTRY[name] = FlagDefinition(
        name=name, default=default, description=description, rollout_pct=rollout_pct
    )


# ── Env override parsing ───────────────────────────────────────────────────────

def _parse_env_overrides() -> dict[str, bool]:
    """
    Parse URAKI_FLAGS environment variable for local overrides.
    Format: comma-separated list of flag names, optionally prefixed with ! to disable.
    Example: URAKI_FLAGS=simulation_mode,!action_engine,advanced_audit
    Only active when URAKI_ENV != "production" (safety guard).
    """
    from core.environment import is_production
    if is_production():
        return {}

    raw = os.getenv("URAKI_FLAGS", "").strip()
    if not raw:
        return {}

    overrides: dict[str, bool] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("!"):
            overrides[part[1:].strip()] = False
        else:
            overrides[part] = True

    if overrides:
        logger.info("Feature flag env overrides: %s", overrides)
    return overrides


_ENV_OVERRIDES: dict[str, bool] = _parse_env_overrides()


# ── Tenant flag resolution ────────────────────────────────────────────────────

def _get_tenant_flags() -> dict[str, bool]:
    """
    Pull feature flags from the current session's tenant config.

    Sources (merged, later wins):
      1. config.modules  — the existing module toggles from the tenant config
      2. config.feature_flags — a dedicated dict if the backend provides it
    """
    try:
        cfg = st.session_state.get("tenant_config") or {}
        inner = cfg.get("config") or {}
        modules: dict[str, Any] = inner.get("modules") or {}
        dedicated: dict[str, Any] = inner.get("feature_flags") or {}
        # Merge: dedicated flags take precedence over module flags
        merged: dict[str, bool] = {}
        for k, v in modules.items():
            merged[k] = bool(v)
        for k, v in dedicated.items():
            merged[k] = bool(v)
        return merged
    except Exception:
        return {}


# ── Public API ────────────────────────────────────────────────────────────────

def is_enabled(flag: str, tenant_id: Optional[str] = None) -> bool:
    """
    Evaluate a feature flag for the current tenant.

    Evaluation order (highest to lowest priority):
      1. URAKI_FLAGS env override   (non-production only)
      2. Tenant config (modules + feature_flags)
      3. Registered default

    Returns True if the flag is enabled, False otherwise.
    Flags that are not registered always return False and log a warning.
    """
    if flag not in _REGISTRY:
        logger.warning("is_enabled('%s') — flag not registered; returning False", flag)
        return False

    defn = _REGISTRY[flag]

    # 1. Env override
    if flag in _ENV_OVERRIDES:
        return _ENV_OVERRIDES[flag]

    # 2. Tenant config
    tenant_flags = _get_tenant_flags()
    if flag in tenant_flags:
        value = tenant_flags[flag]
        # Honour rollout_pct — below 100% only evaluate to True probabilistically
        # (using tenant_id as a stable hash seed so a tenant always gets the same result)
        if value and defn.rollout_pct < 100:
            seed = hash(tenant_id or "") % 100
            return seed < defn.rollout_pct
        return value

    # 3. Default
    return defn.default


def get_all_flags() -> dict[str, bool]:
    """
    Return the evaluated state of every registered flag for the current tenant.
    Useful for the observability dashboard and debug tooling.
    """
    return {name: is_enabled(name) for name in _REGISTRY}


def get_flag_definitions() -> list[FlagDefinition]:
    """Return all registered flag definitions (for admin UI)."""
    return list(_REGISTRY.values())


def require_flag(flag: str) -> None:
    """
    Raise a RuntimeError if the flag is disabled.
    Use at the top of routes/renders that are gated on a flag.
    """
    if not is_enabled(flag):
        raise RuntimeError(
            f"Feature '{flag}' is not enabled for this tenant. "
            f"Enable it in the tenant config under config.modules.{flag}."
        )


# ── Streamlit guard helper ────────────────────────────────────────────────────

def flag_gate(flag: str, disabled_message: str = "") -> bool:
    """
    Streamlit-friendly guard. Returns True if the flag is enabled.
    When disabled, renders a styled notice and returns False.

    Usage:
        if not flag_gate("simulation_mode", "Simulación no habilitada"):
            return
    """
    if is_enabled(flag):
        return True

    if disabled_message:
        st.markdown(f"""
        <div style="
            background:rgba(59,130,246,0.07);
            border:1px solid rgba(59,130,246,0.25);
            border-radius:8px;padding:0.75rem 1rem;
            font-size:12px;color:#94A3B8;
        ">
            🔒 {disabled_message}
        </div>
        """, unsafe_allow_html=True)
    return False


# ── Flag definitions (canonical registry) ────────────────────────────────────
# These mirror config.modules names so tenant config drives them directly.

register_flag(
    "document_intelligence",
    default=True,
    description="Document parsing and clause extraction",
)
register_flag(
    "llm_classification",
    default=True,
    description="LLM-based case classification",
)
register_flag(
    "auto_messaging",
    default=True,
    description="Automated client message generation",
)
register_flag(
    "auto_escalation",
    default=True,
    description="Automatic escalation routing",
)
register_flag(
    "priority_scoring",
    default=True,
    description="Dynamic impact-based priority scoring",
)
register_flag(
    "simulation_mode",
    default=False,
    description="What-if simulation panel in the decision card",
    rollout_pct=100,
)
register_flag(
    "action_engine",
    default=False,
    description="Action engine (send email, assign task, notify)",
    rollout_pct=100,
)
register_flag(
    "advanced_audit",
    default=False,
    description="Full immutable audit timeline with export",
    rollout_pct=100,
)
register_flag(
    "observability_dashboard",
    default=False,
    description="Internal system observability dashboard (gerente/admin)",
)
register_flag(
    "sla_monitoring",
    default=True,
    description="SLA breach detection and badge rendering",
)
register_flag(
    "time_travel",
    default=False,
    description="View past case and decision states by version",
)
register_flag(
    "soft_delete",
    default=False,
    description="Soft-delete and case recovery UI",
)
