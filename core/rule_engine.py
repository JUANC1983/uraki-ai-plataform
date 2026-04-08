# core/rule_engine.py
"""
Rule Engine — deterministic, auditable, priority-based decision engine.

Capabilities:
  - Dynamic rules from DB (no hardcoded logic)
  - Priority-ordered evaluation with conflict resolution
  - AND / OR / NOT condition groups (nestable)
  - Document clause matching (clause_contains, any_clause_contains)
  - Versioned rule loading: fetch rules valid at a given timestamp
  - Full audit trail: evaluated / matched / discarded per decision
"""
import logging
import operator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule data structure (mirrors DB model Rule — no SQLAlchemy in engine core)
# ---------------------------------------------------------------------------

@dataclass
class RuleRecord:
    id: str
    tenant_id: str
    name: str
    category: str
    priority: int
    conditions: dict[str, Any]
    actions: dict[str, Any]
    constraints: Optional[dict[str, Any]]
    explanation_template: Optional[str]
    is_active: bool
    version: int
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    parent_rule_id: Optional[str] = None

    def is_valid_at(self, point_in_time: datetime) -> bool:
        """True if this rule version was active at the given timestamp."""
        if self.effective_from and point_in_time < self.effective_from:
            return False
        if self.effective_to and point_in_time > self.effective_to:
            return False
        return True


@dataclass
class RuleEvaluationResult:
    rule: RuleRecord
    matched: bool
    reason: str
    actions_proposed: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule.id,
            "rule_name": self.rule.name,
            "rule_version": self.rule.version,
            "priority": self.rule.priority,
            "matched": self.matched,
            "reason": self.reason,
            "actions_proposed": self.actions_proposed,
        }


@dataclass
class EngineResult:
    applied_rule: Optional[RuleRecord]
    applied_actions: dict[str, Any]
    explanation: str
    rules_evaluated: list[RuleEvaluationResult] = field(default_factory=list)
    rules_discarded: list[RuleEvaluationResult] = field(default_factory=list)
    conflict_resolution_notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Document clause operator functions — MUST be defined before _OPERATORS dict
# ---------------------------------------------------------------------------

def _clause_contains_op(field_val: Any, search_value: Any) -> bool:
    """
    field_val: list of {"content": str, "clause_label": str} dicts
    (passed via context["document_clauses"])
    Checks if any clause content contains search_value.
    """
    if not isinstance(field_val, list):
        return False
    search = str(search_value).lower()
    return any(search in str(c.get("content", "")).lower() for c in field_val)


def _any_clause_contains_op(field_val: Any, search_values: Any) -> bool:
    """True if ANY clause contains ANY of the search strings."""
    if not isinstance(field_val, list) or not isinstance(search_values, list):
        return False
    return any(
        str(term).lower() in str(c.get("content", "")).lower()
        for c in field_val
        for term in search_values
    )


def _clause_label_matches_op(field_val: Any, label: Any) -> bool:
    """True if any clause has a label matching the given string."""
    if not isinstance(field_val, list):
        return False
    label_lower = str(label).lower()
    return any(label_lower in str(c.get("clause_label", "")).lower() for c in field_val)


# ---------------------------------------------------------------------------
# Operator registry — all clause functions must be defined above this dict
# ---------------------------------------------------------------------------

_OPERATORS: dict[str, Any] = {
    # Standard comparisons
    "eq":           operator.eq,
    "ne":           operator.ne,
    "gt":           operator.gt,
    "gte":          operator.ge,
    "lt":           operator.lt,
    "lte":          operator.le,
    "in":           lambda a, b: a in b,
    "not_in":       lambda a, b: a not in b,
    "contains":     lambda a, b: b in str(a),
    "starts_with":  lambda a, b: str(a).startswith(str(b)),
    "ends_with":    lambda a, b: str(a).endswith(str(b)),
    "is_null":      lambda a, _: a is None,
    "is_not_null":  lambda a, _: a is not None,
    "between":      lambda a, b: b[0] <= a <= b[1],
    # Document clause operators
    "clause_contains":       _clause_contains_op,
    "any_clause_contains":   _any_clause_contains_op,
    "clause_label_matches":  _clause_label_matches_op,
}


def _resolve_value(value: Any, context: dict[str, Any]) -> Any:
    """Resolve context variables: '$overdue_days' → context['overdue_days']."""
    if isinstance(value, str) and value.startswith("$"):
        return context.get(value[1:])
    return value


def _evaluate_single_condition(
    condition: dict[str, Any], context: dict[str, Any]
) -> tuple[bool, str]:
    """
    Evaluate one atomic condition.

    Schema:
        { "field": "overdue_days", "op": "gte", "value": 30 }
        { "field": "document_clauses", "op": "clause_contains", "value": "mora" }
    """
    field_name: str = condition.get("field", "")
    op_name: str = condition.get("op", "")
    value = _resolve_value(condition.get("value"), context)

    if field_name not in context:
        return False, f"Field '{field_name}' not in context (available: {list(context.keys())})"

    op_fn = _OPERATORS.get(op_name)
    if op_fn is None:
        return False, f"Unknown operator '{op_name}'"

    field_val = context[field_name]
    try:
        result = op_fn(field_val, value)
        desc = f"{field_name} {op_name} {value!r} → {result} (actual={field_val!r})"
        return bool(result), desc
    except Exception as exc:
        return False, f"Evaluation error for '{field_name}' op='{op_name}': {exc}"


def _evaluate_condition_group(
    group: dict[str, Any], context: dict[str, Any]
) -> tuple[bool, str]:
    """
    Recursive evaluation of AND / OR / NOT groups.

    Schema (group):
        { "logic": "AND", "conditions": [ <condition|group>, ... ] }
    Schema (atomic):
        { "field": "...", "op": "...", "value": ... }
    """
    if "logic" not in group:
        return _evaluate_single_condition(group, context)

    logic = str(group.get("logic", "AND")).upper()
    sub_conditions = group.get("conditions", [])

    if not sub_conditions:
        return True, f"{logic}() — empty condition group (vacuously true)"

    results = [_evaluate_condition_group(c, context) for c in sub_conditions]
    reasons = [r[1] for r in results]

    if logic == "AND":
        matched = all(r[0] for r in results)
    elif logic == "OR":
        matched = any(r[0] for r in results)
    elif logic == "NOT":
        matched = not results[0][0]
        return matched, f"NOT({reasons[0]})"
    else:
        return False, f"Unknown logic operator: '{logic}'"

    return matched, f"{logic}[{'; '.join(reasons)}]"


# ---------------------------------------------------------------------------
# Rule Engine
# ---------------------------------------------------------------------------

class RuleEngine:
    """
    Deterministic, priority-based rule engine.

    evaluate():
        1. Filter active rules
        2. Evaluate ALL rules (full audit trail)
        3. Sort matching rules by priority (asc = higher priority)
        4. Resolve conflicts (highest priority wins)
        5. Return EngineResult with complete trace

    evaluate_at():
        Same but for a historical timestamp (decision replay).
    """

    def evaluate(
        self,
        rules: list[RuleRecord],
        context: dict[str, Any],
    ) -> EngineResult:
        """Evaluate rules against the current context."""
        return self._run(rules=rules, context=context, point_in_time=None)

    def evaluate_at(
        self,
        rules: list[RuleRecord],
        context: dict[str, Any],
        point_in_time: datetime,
    ) -> EngineResult:
        """
        Historical replay: evaluate only rules that were valid at `point_in_time`.
        Used to reproduce the exact decision that was made at a past timestamp.
        """
        historical_rules = [r for r in rules if r.is_valid_at(point_in_time)]
        return self._run(rules=historical_rules, context=context, point_in_time=point_in_time)

    def _run(
        self,
        rules: list[RuleRecord],
        context: dict[str, Any],
        point_in_time: Optional[datetime],
    ) -> EngineResult:
        if not rules:
            return EngineResult(
                applied_rule=None,
                applied_actions={},
                explanation="No rules configured for this tenant.",
            )

        active = [r for r in rules if r.is_active]
        evaluated: list[RuleEvaluationResult] = []
        matching: list[RuleEvaluationResult] = []
        discarded: list[RuleEvaluationResult] = []

        for rule in active:
            matched, reason = _evaluate_condition_group(rule.conditions, context)
            result = RuleEvaluationResult(
                rule=rule,
                matched=matched,
                reason=reason,
                actions_proposed=rule.actions if matched else None,
            )
            evaluated.append(result)
            if matched:
                matching.append(result)
            else:
                discarded.append(result)

        if not matching:
            return EngineResult(
                applied_rule=None,
                applied_actions={},
                explanation="No rules matched the case context.",
                rules_evaluated=evaluated,
                rules_discarded=discarded,
            )

        # Sort by priority (lower number = higher priority)
        matching.sort(key=lambda r: r.rule.priority)
        winner = matching[0]
        conflict_notes: list[str] = []

        if len(matching) > 1:
            losers = [r.rule.name for r in matching[1:]]
            conflict_notes.append(
                f"{len(matching)} rules matched. Applied '{winner.rule.name}' "
                f"(priority={winner.rule.priority}, v{winner.rule.version}). "
                f"Overridden: {losers}"
            )
            for r in matching[1:]:
                discarded.append(
                    RuleEvaluationResult(
                        rule=r.rule,
                        matched=True,
                        reason=f"Matched but overridden by higher-priority rule '{winner.rule.name}'",
                    )
                )

        explanation = self._build_explanation(winner, context)

        return EngineResult(
            applied_rule=winner.rule,
            applied_actions=winner.rule.actions,
            explanation=explanation,
            rules_evaluated=evaluated,
            rules_discarded=discarded,
            conflict_resolution_notes=conflict_notes,
        )

    def _build_explanation(
        self, result: RuleEvaluationResult, context: dict[str, Any]
    ) -> str:
        template = result.rule.explanation_template
        if not template:
            return (
                f"Regla '{result.rule.name}' v{result.rule.version} aplicada "
                f"(prioridad={result.rule.priority}). "
                f"Condición: {result.reason}"
            )
        try:
            return template.format(**context)
        except KeyError as exc:
            logger.warning(
                "Explanation template missing key %s for rule %s", exc, result.rule.id
            )
            return template
