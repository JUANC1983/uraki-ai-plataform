# dashboard/core/schema_evolution.py
"""
Schema evolution engine — backward-compatible versioned model migrations.

Every persisted or API-returned resource carries a `schema_version` field.
When the system reads an old resource, it runs all migration functions in order
until the resource is at the current version.

Adding a new field:
  1. Bump CURRENT_DECISION_VERSION (or CURRENT_CASE_VERSION)
  2. Add a migration function to the registry:
       @register_decision_migration(from_version=N)
       def _v{N}_to_v{N+1}(d: dict) -> dict: ...
  3. The function must return a NEW dict with the old dict preserved — no in-place mutation.

Contract:
  - Missing schema_version is treated as version 1 (first production version).
  - Migrations are idempotent: running them twice produces the same result.
  - Old decisions remain valid forever — the migration layer always produces a
    current-version dict from any historical shape.
"""
from __future__ import annotations
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# ── Version constants ─────────────────────────────────────────────────────────

CURRENT_DECISION_VERSION: int = 3
CURRENT_CASE_VERSION:     int = 2

# ── Migration registries ──────────────────────────────────────────────────────

# Registry maps: resource_name → {from_version → migration_fn}
_DECISION_MIGRATIONS: dict[int, Callable[[dict], dict]] = {}
_CASE_MIGRATIONS:     dict[int, Callable[[dict], dict]] = {}


def register_decision_migration(from_version: int):
    """Decorator to register a decision migration from `from_version` → from_version+1."""
    def decorator(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _DECISION_MIGRATIONS[from_version] = fn
        return fn
    return decorator


def register_case_migration(from_version: int):
    """Decorator to register a case migration from `from_version` → from_version+1."""
    def decorator(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _CASE_MIGRATIONS[from_version] = fn
        return fn
    return decorator


# ── Decision migrations ───────────────────────────────────────────────────────

@register_decision_migration(from_version=1)
def _decision_v1_to_v2(d: dict) -> dict:
    """
    v1 → v2: Added intelligence layer fields (risk_factors, data_used, linked_documents, explain).
    Old decisions that predate these fields get empty defaults.
    """
    return {
        **d,
        "schema_version":   2,
        "risk_factors":     d.get("risk_factors") or [],
        "data_used":        d.get("data_used") or {},
        "linked_documents": d.get("linked_documents") or [],
        "explain":          d.get("explain") or "",
    }


@register_decision_migration(from_version=2)
def _decision_v2_to_v3(d: dict) -> dict:
    """
    v2 → v3: Added decision versioning fields (version_number, previous_version_id, rule_version).
    Old decisions that predate versioning get version_number=1, no previous version.
    """
    return {
        **d,
        "schema_version":      3,
        "version_number":      d.get("version_number") or 1,
        "previous_version_id": d.get("previous_version_id"),
        "rule_version":        d.get("rule_version") or d.get("rule_version_used") or "1.0",
        "rule_active_from":    d.get("rule_active_from"),
        "rule_active_to":      d.get("rule_active_to"),
    }


# ── Case migrations ───────────────────────────────────────────────────────────

@register_case_migration(from_version=1)
def _case_v1_to_v2(c: dict) -> dict:
    """
    v1 → v2: Added soft delete fields (is_deleted, deleted_at, deleted_by) and
    access traceability (last_viewed_by, last_viewed_at).
    """
    return {
        **c,
        "schema_version":  2,
        "is_deleted":      bool(c.get("is_deleted", False)),
        "deleted_at":      c.get("deleted_at"),
        "deleted_by":      c.get("deleted_by"),
        "last_viewed_by":  c.get("last_viewed_by"),
        "last_viewed_at":  c.get("last_viewed_at"),
    }


# ── Migration engine ──────────────────────────────────────────────────────────

def migrate_decision(raw: dict) -> dict:
    """
    Run all registered decision migrations needed to bring `raw` to CURRENT_DECISION_VERSION.
    Returns a new dict. Never mutates the input.

    Old decisions with no schema_version are treated as version 1.
    """
    return _migrate(raw, _DECISION_MIGRATIONS, CURRENT_DECISION_VERSION, "decision")


def migrate_case(raw: dict) -> dict:
    """
    Run all registered case migrations needed to bring `raw` to CURRENT_CASE_VERSION.
    Returns a new dict. Never mutates the input.
    """
    return _migrate(raw, _CASE_MIGRATIONS, CURRENT_CASE_VERSION, "case")


def _migrate(
    raw:        dict,
    registry:   dict[int, Callable[[dict], dict]],
    target:     int,
    label:      str,
) -> dict:
    version = int(raw.get("schema_version") or 1)

    if version > target:
        # Received a future version — pass through without migration
        logger.warning(
            "%s schema_version=%d is ahead of current=%d — passing through",
            label, version, target,
        )
        return raw

    result = dict(raw)
    while version < target:
        fn = registry.get(version)
        if fn is None:
            # No migration registered for this gap — stamp the version and skip
            logger.warning(
                "No %s migration registered for v%d → v%d; stamping version",
                label, version, version + 1,
            )
            result["schema_version"] = version + 1
            version += 1
            continue
        try:
            result = fn(result)
            logger.debug("%s migrated v%d → v%d", label, version, version + 1)
        except Exception as exc:
            logger.error(
                "%s migration v%d → v%d failed: %s — leaving at v%d",
                label, version, version + 1, exc, version,
            )
            break
        version += 1

    return result


# ── Compatibility helpers ─────────────────────────────────────────────────────

def is_current_decision(d: dict) -> bool:
    return int(d.get("schema_version") or 1) == CURRENT_DECISION_VERSION


def is_current_case(c: dict) -> bool:
    return int(c.get("schema_version") or 1) == CURRENT_CASE_VERSION


def stamp_current_decision(d: dict) -> dict:
    """Stamp a freshly constructed decision dict with the current schema version."""
    return {**d, "schema_version": CURRENT_DECISION_VERSION}


def stamp_current_case(c: dict) -> dict:
    """Stamp a freshly constructed case dict with the current schema version."""
    return {**c, "schema_version": CURRENT_CASE_VERSION}
