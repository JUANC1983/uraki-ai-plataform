# dashboard/core/environment.py
"""
Multi-environment isolation layer.

Environments: development | staging | production

Determined by the URAKI_ENV environment variable.
Defaults to "production" when unset (fail-safe: never assume dev in production).

Each environment has:
  - its own API URL (URAKI_API_URL_{ENV} or URAKI_API_URL fallback)
  - its own logging level
  - its own cache TTL multiplier
  - its own behaviour flags (strict validation, UI warnings, etc.)

No cross-environment contamination:
  - Caches are namespaced by environment
  - Session state carries the environment name
  - API client respects the environment-resolved base URL

Usage:
    from core.environment import env, get_config, is_production, is_development

    if is_development():
        st.warning("Running in DEVELOPMENT mode — not for client use.")
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# ── Types ─────────────────────────────────────────────────────────────────────

EnvName = Literal["development", "staging", "production"]

_VALID_ENVS: set[str] = {"development", "staging", "production"}


@dataclass(frozen=True)
class EnvironmentConfig:
    name:               EnvName
    api_url:            str
    log_level:          str
    cache_ttl_factor:   float   # multiplied against all TTL values
    strict_validation:  bool    # raise on schema mismatches instead of warn
    show_env_banner:    bool    # show banner in UI when not production
    allow_debug_tools:  bool    # show internal debug expanders
    request_timeout_s:  int     # override API client timeout
    max_retry_attempts: int     # retry budget for API calls


# ── Environment resolution ────────────────────────────────────────────────────

def _resolve_api_url(env_name: str) -> str:
    """
    Resolve the API URL for the given environment.
    Priority:
      1. URAKI_API_URL_{ENV_UPPER}  (e.g. URAKI_API_URL_STAGING)
      2. URAKI_API_URL              (universal fallback)
    """
    env_specific = os.getenv(f"URAKI_API_URL_{env_name.upper()}", "")
    universal    = os.getenv("URAKI_API_URL", "")
    return (env_specific or universal).rstrip("/")


def _resolve_env_name() -> EnvName:
    raw = os.getenv("URAKI_ENV", "production").strip().lower()
    if raw not in _VALID_ENVS:
        logger.warning(
            "Unknown URAKI_ENV value '%s' — defaulting to 'production'. "
            "Valid values: %s", raw, sorted(_VALID_ENVS)
        )
        return "production"
    return raw  # type: ignore[return-value]


def _build_config(name: EnvName) -> EnvironmentConfig:
    api_url = _resolve_api_url(name)

    _ENV_PROFILES: dict[str, dict] = {
        "development": dict(
            log_level          = "DEBUG",
            cache_ttl_factor   = 0.1,   # near-zero TTL — always fresh in dev
            strict_validation  = True,
            show_env_banner    = True,
            allow_debug_tools  = True,
            request_timeout_s  = 30,
            max_retry_attempts = 1,     # fail fast in dev — don't hide problems
        ),
        "staging": dict(
            log_level          = "INFO",
            cache_ttl_factor   = 0.5,   # half TTL — fresher than prod
            strict_validation  = True,
            show_env_banner    = True,
            allow_debug_tools  = False,
            request_timeout_s  = 15,
            max_retry_attempts = 2,
        ),
        "production": dict(
            log_level          = "WARNING",
            cache_ttl_factor   = 1.0,
            strict_validation  = False,  # warn, don't blow up client sessions
            show_env_banner    = False,
            allow_debug_tools  = False,
            request_timeout_s  = 15,
            max_retry_attempts = 3,
        ),
    }

    return EnvironmentConfig(name=name, api_url=api_url, **_ENV_PROFILES[name])


# ── Singleton ─────────────────────────────────────────────────────────────────

_CURRENT_ENV: EnvironmentConfig = _build_config(_resolve_env_name())

# Apply log level immediately
logging.getLogger("dashboard").setLevel(_CURRENT_ENV.log_level)

logger.info("URAKI environment: %s | backend: %s", _CURRENT_ENV.name, _CURRENT_ENV.api_url or "(not configured)")


# ── Public API ────────────────────────────────────────────────────────────────

def env() -> EnvironmentConfig:
    """Return the resolved environment config (singleton)."""
    return _CURRENT_ENV


def get_config() -> EnvironmentConfig:
    """Alias for env()."""
    return _CURRENT_ENV


def is_production() -> bool:
    return _CURRENT_ENV.name == "production"


def is_staging() -> bool:
    return _CURRENT_ENV.name == "staging"


def is_development() -> bool:
    return _CURRENT_ENV.name == "development"


def effective_ttl(base_ttl: int) -> int:
    """
    Apply the environment's cache_ttl_factor to a base TTL value.
    Always returns at least 0.
    """
    return max(0, int(base_ttl * _CURRENT_ENV.cache_ttl_factor))


def cache_namespace() -> str:
    """
    Return a namespace prefix for session-state cache keys.
    Ensures dev/staging/prod caches never collide in the same browser session.
    """
    return f"_env_{_CURRENT_ENV.name}"


def render_env_banner() -> None:
    """Render a non-production environment banner in the Streamlit UI."""
    if not _CURRENT_ENV.show_env_banner:
        return

    import streamlit as st
    _COLORS = {
        "development": ("#F59E0B", "rgba(245,158,11,0.10)", "DESARROLLO"),
        "staging":     ("#3B82F6", "rgba(59,130,246,0.10)", "STAGING"),
    }
    color, bg, label = _COLORS.get(_CURRENT_ENV.name, ("#888", "#111", "DESCONOCIDO"))
    st.markdown(f"""
    <div style="
        background:{bg};border:1px solid {color}55;
        border-radius:6px;padding:6px 16px;margin-bottom:0.75rem;
        display:flex;align-items:center;justify-content:space-between;
    ">
        <span style="font-size:11px;color:{color};font-weight:700;
            letter-spacing:0.1em;">⚠ ENTORNO: {label}</span>
        <span style="font-size:10px;color:{color}99;">
            Los datos aquí no son de producción real.</span>
    </div>
    """, unsafe_allow_html=True)
