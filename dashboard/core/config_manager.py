# dashboard/core/config_manager.py
"""
Tenant config management — versioned, validated, explicitly fallback.

Tenant config is fetched from /tenants/me after login.
This module validates the structure, exposes typed accessors,
and makes every fallback explicit and logged (never silent).

Config schema (expected from backend):
{
  "id":      str,
  "name":    str,
  "slug":    str,
  "plan":    "enterprise" | "pro" | "standard",
  "version": int,          # config version number
  "config": {
    "tone_settings": {
      "tone":                "firme" | "suave" | "neutral",
      "language":            "es",
      "company_name":        str,
      "use_formal_address":  bool,
    },
    "modules": {
      "document_intelligence": bool,
      "llm_classification":    bool,
      "auto_messaging":        bool,
      "auto_escalation":       bool,
      "priority_scoring":      bool,
      "simulation_mode":       bool,
      "action_engine":         bool,
    },
    "sla": {
      "decision_max_ms":    int,   # max ms allowed per decision
      "resolution_max_days": int,  # max days to resolve a case
    },
    "branding": {
      "primary_color": str,
      "logo_url":      str | None,
    },
  },
}
"""
from __future__ import annotations
import logging
import streamlit as st

logger = logging.getLogger(__name__)

# ── Explicit defaults (every field documented) ────────────────────────────────

_DEFAULTS = {
    "id":      "unknown",
    "name":    "URAKI OPS",
    "slug":    "uraki",
    "plan":    "standard",
    "version": 0,
    "config": {
        "tone_settings": {
            "tone":               "firme",
            "language":           "es",
            "company_name":       "URAKI OPS",
            "use_formal_address": True,
        },
        "modules": {
            "document_intelligence": True,
            "llm_classification":    True,
            "auto_messaging":        True,
            "auto_escalation":       True,
            "priority_scoring":      True,
            "simulation_mode":       False,
            "action_engine":         False,
        },
        "sla": {
            "decision_max_ms":     30_000,
            "resolution_max_days": 30,
        },
        "branding": {
            "primary_color": "#E85D2A",
            "logo_url":      None,
        },
    },
}

_REQUIRED_TOP    = {"id", "name", "plan"}
_VALID_PLANS     = {"enterprise", "pro", "standard"}
_VALID_TONES     = {"firme", "suave", "neutral"}


# ── Validation ────────────────────────────────────────────────────────────────

def validate_tenant_config(raw: dict) -> tuple[dict, list[str]]:
    """
    Validate raw tenant config from backend.
    Returns (merged_config, warning_list).
    Missing fields are filled from _DEFAULTS with a warning logged.
    Invalid values are replaced with defaults with a warning.
    Never raises — always returns a usable config.
    """
    warnings: list[str] = []
    if not isinstance(raw, dict):
        warnings.append(f"Tenant config is not a dict ({type(raw).__name__}) — using all defaults")
        return _DEFAULTS.copy(), warnings

    result = dict(_DEFAULTS)
    result.update({k: v for k, v in raw.items() if k in result})

    # Top-level required fields
    for field in _REQUIRED_TOP:
        if not result.get(field):
            warnings.append(f"Tenant config missing '{field}' — using default '{_DEFAULTS[field]}'")
            result[field] = _DEFAULTS[field]

    # Plan validation
    if result.get("plan") not in _VALID_PLANS:
        warnings.append(f"Unknown plan '{result.get('plan')}' — defaulting to 'standard'")
        result["plan"] = "standard"

    # Nested config merge
    raw_cfg = raw.get("config") or {}
    merged_cfg = {}

    for section, section_defaults in _DEFAULTS["config"].items():
        raw_section = raw_cfg.get(section) or {}
        if not isinstance(raw_section, dict):
            warnings.append(f"config.{section} is not a dict — using defaults")
            merged_cfg[section] = dict(section_defaults)
            continue
        merged_section = dict(section_defaults)
        merged_section.update({k: v for k, v in raw_section.items() if k in merged_section})
        merged_cfg[section] = merged_section

    # Tone validation
    tone = merged_cfg["tone_settings"].get("tone", "firme")
    if tone not in _VALID_TONES:
        warnings.append(f"Unknown tone '{tone}' — defaulting to 'firme'")
        merged_cfg["tone_settings"]["tone"] = "firme"

    result["config"] = merged_cfg

    for w in warnings:
        logger.warning("TenantConfig: %s", w)

    return result, warnings


# ── Typed accessors ───────────────────────────────────────────────────────────

def get_config() -> dict:
    """Return the current session's validated tenant config."""
    return st.session_state.get("tenant_config") or _DEFAULTS


def is_module_enabled(module: str) -> bool:
    """Return True if a module is enabled in the tenant config."""
    cfg = get_config()
    return bool(cfg.get("config", {}).get("modules", {}).get(module, False))


def get_sla() -> dict:
    """Return SLA limits for this tenant."""
    cfg = get_config()
    return cfg.get("config", {}).get("sla", _DEFAULTS["config"]["sla"])


def get_branding() -> dict:
    """Return branding config for this tenant."""
    cfg = get_config()
    b = cfg.get("config", {}).get("branding", _DEFAULTS["config"]["branding"])
    return {
        "primary_color": b.get("primary_color") or "#E85D2A",
        "logo_url":      b.get("logo_url"),
        "company_name":  (
            cfg.get("name")
            or cfg.get("config", {}).get("tone_settings", {}).get("company_name")
            or "URAKI OPS"
        ),
        "plan":          cfg.get("plan", "standard"),
    }


def get_company_name() -> str:
    return get_branding()["company_name"]


def get_plan() -> str:
    return get_config().get("plan", "standard")


def get_config_version() -> int:
    return int(get_config().get("version", 0))
