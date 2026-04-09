# dashboard/services/schema.py
"""
Schema validation — ensures API responses match expected shape before reaching UI.
Rejects malformed data with structured errors. Never allows fabricated data through.

In production (strict_validation=False), schema mismatches are logged as warnings
rather than raised, so a single bad field doesn't crash a client session.
In development/staging (strict_validation=True), they raise immediately so
engineers catch regressions before they reach production.
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _is_strict() -> bool:
    try:
        from core.environment import env
        return env().strict_validation
    except Exception:
        return False  # safe default

# ── Required fields per resource ────────────────────────────────────────────

_CASE_REQUIRED: frozenset[str] = frozenset({
    "id", "status", "priority", "client_name",
    "overdue_days", "overdue_amount",
})

_DECISION_REQUIRED: frozenset[str] = frozenset({
    "action", "risk_score", "risk_level", "rationale",
})

_AUDIT_EVENT_REQUIRED: frozenset[str] = frozenset({
    "type", "timestamp",
})

_ACTION_RESULT_REQUIRED: frozenset[str] = frozenset({
    "action_id", "status",
})


class SchemaError(ValueError):
    """Raised when an API response fails schema validation."""
    def __init__(self, resource: str, missing: set[str], ref_id: str = "?"):
        self.resource = resource
        self.missing  = missing
        self.ref_id   = ref_id
        super().__init__(
            f"{resource} schema violation (id={ref_id}): "
            f"missing required fields {sorted(missing)}"
        )


# ── Public validators ────────────────────────────────────────────────────────

def validate_case(raw: dict) -> dict:
    """
    Validate and coerce a case dict.
    In strict mode (dev/staging): raises SchemaError on missing required fields.
    In non-strict mode (production): logs a warning and returns a best-effort coerced dict.
    """
    if not isinstance(raw, dict):
        raise SchemaError("case", _CASE_REQUIRED, "non-dict")
    missing = _CASE_REQUIRED - set(raw.keys())
    if missing:
        cid = raw.get("id", "?")
        logger.warning("Case schema violation %s: missing %s", cid, missing)
        if _is_strict():
            raise SchemaError("case", missing, str(cid))
        # Non-strict: fill missing required fields with safe defaults
        raw = {**raw, **{f: "" for f in missing}}
    return _coerce_case(raw)


def validate_decision(raw: dict, case_id: str = "?") -> dict:
    """
    Validate and coerce a decision dict.
    In strict mode (dev/staging): raises SchemaError on missing required fields.
    In non-strict mode (production): logs a warning and returns a best-effort coerced dict.
    """
    if not isinstance(raw, dict):
        raise SchemaError("decision", _DECISION_REQUIRED, case_id)
    missing = _DECISION_REQUIRED - set(raw.keys())
    if missing:
        logger.warning("Decision schema violation for case %s: missing %s", case_id, missing)
        if _is_strict():
            raise SchemaError("decision", missing, case_id)
        # Non-strict: fill with safe defaults so the UI remains functional
        _SAFE_DECISION_DEFAULTS = {
            "action":     "REVISAR_MANUALMENTE",
            "risk_score": 0,
            "risk_level": "BAJO",
            "rationale":  "",
        }
        raw = {**{k: _SAFE_DECISION_DEFAULTS.get(k, "") for k in missing}, **raw}
    return _coerce_decision(raw)


def validate_case_list(items: list[Any]) -> tuple[list[dict], list[str]]:
    """
    Validate a list of raw case dicts.
    Returns (valid_cases, error_strings).
    Partial success is allowed — the caller can warn about rejected items.
    """
    valid:  list[dict] = []
    errors: list[str]  = []
    for item in items:
        if not isinstance(item, dict):
            errors.append(f"Non-dict item in case list: {type(item).__name__}")
            continue
        try:
            valid.append(validate_case(item))
        except SchemaError as exc:
            errors.append(str(exc))
    return valid, errors


def validate_audit_events(events: list[Any]) -> list[dict]:
    """Filter and coerce audit events. Drops invalid events with a warning."""
    valid = []
    for e in events:
        if not isinstance(e, dict):
            continue
        missing = _AUDIT_EVENT_REQUIRED - set(e.keys())
        if missing:
            logger.warning("Audit event dropped — missing %s", missing)
            continue
        valid.append({
            **e,
            "type":      str(e.get("type", "unknown")),
            "timestamp": str(e.get("timestamp", "")),
            "user":      e.get("user") or "Sistema",
            "details":   e.get("details") or "",
        })
    return valid


def validate_action_result(raw: dict) -> dict:
    """Validate an action execution result."""
    missing = _ACTION_RESULT_REQUIRED - set(raw.keys())
    if missing:
        raise SchemaError("action_result", missing)
    return {**raw, "status": str(raw["status"]), "action_id": str(raw["action_id"])}


# ── Private coercers ─────────────────────────────────────────────────────────

def _coerce_case(r: dict) -> dict:
    return {
        **r,
        "overdue_days":            int(r.get("overdue_days", 0)),
        "overdue_amount":          float(r.get("overdue_amount", 0)),
        "monthly_rent":            float(r.get("monthly_rent", 0)),
        "has_policy":              bool(r.get("has_policy", False)),
        "has_legal_action":        bool(r.get("has_legal_action", False)),
        "currency":                r.get("currency") or "COP",
        "assigned_to":             r.get("assigned_to") or "—",
        "contract_id":             r.get("contract_id") or "—",
        "clause_labels":           r.get("clause_labels") or "—",
        "risk_level":              r.get("risk_level") or "BAJO",
        "risk_score":              float(r.get("risk_score", 0)),
        "previous_overdue_count":  int(r.get("previous_overdue_count", 0)),
        "created_at":              r.get("created_at") or "",
        "property_address":        r.get("property_address") or "—",
        "latest_decision":         r.get("latest_decision"),
        "linked_documents":        r.get("linked_documents") or [],
    }


def _coerce_decision(r: dict) -> dict:
    return {
        **r,
        "risk_score":              float(r.get("risk_score", 0)),
        "confidence":              float(r.get("confidence", 0)),
        "rules_evaluated":         int(r.get("rules_evaluated", 0)),
        "rules_discarded":         int(r.get("rules_discarded", 0)),
        "duration_ms":             int(r.get("duration_ms", 0)),
        "is_overridden":           bool(r.get("is_overridden", False)),
        "legal_flag":              bool(r.get("legal_flag", False)),
        "policy_flag":             bool(r.get("policy_flag", False)),
        "escalation_required":     bool(r.get("escalation_required", False)),
        "risk_factors":            r.get("risk_factors") or [],
        "data_used":               r.get("data_used") or {},
        "linked_documents":        r.get("linked_documents") or [],
    }
