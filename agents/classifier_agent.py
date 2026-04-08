# agents/classifier_agent.py
"""
Classifier Agent — determines case classification.
Uses rule engine first; falls back to LLM hint if no rule matches.
LLM hint is advisory only — never overrides explicit rule output.
"""
import logging
from typing import Any, Optional

from core.decision_contract import CaseClassification
from core.rule_engine import RuleEngine, RuleRecord

logger = logging.getLogger(__name__)


class ClassifierAgent:
    """
    Determines the classification of a case.

    Priority:
      1. Rule engine (deterministic, from DB rules)
      2. LLM hint (advisory, requires confirmation)
    """

    def __init__(self, rule_engine: RuleEngine) -> None:
        self._engine = rule_engine

    async def classify(
        self,
        *,
        case_context: dict[str, Any],
        rules: list[RuleRecord],
        llm_connector: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        Returns:
            {
                "classification": CaseClassification,
                "source": "rule_engine" | "llm_hint" | "default",
                "confidence": float,
                "reasoning": str,
                "rule_id": Optional[str],
            }
        """
        # Filter only classification rules
        classification_rules = [r for r in rules if r.category == "classification"]
        engine_result = self._engine.evaluate(
            rules=classification_rules,
            context=case_context,
        )

        if engine_result.applied_rule and "classification" in engine_result.applied_actions:
            return {
                "classification": CaseClassification(
                    engine_result.applied_actions["classification"]
                ),
                "source": "rule_engine",
                "confidence": 1.0,
                "reasoning": engine_result.explanation,
                "rule_id": engine_result.applied_rule.id,
            }

        # LLM hint fallback
        if llm_connector:
            try:
                hint = await llm_connector.classify_case_hint(
                    case_description=self._build_description(case_context),
                    available_classifications=[c.value for c in CaseClassification],
                )
                return {
                    "classification": CaseClassification(hint.get("classification", "OTRO")),
                    "source": "llm_hint",
                    "confidence": hint.get("confidence", 0.5),
                    "reasoning": hint.get("reasoning", "LLM-based hint"),
                    "rule_id": None,
                }
            except Exception as exc:
                logger.warning("LLM classification failed: %s", exc)

        return {
            "classification": CaseClassification.OTRO,
            "source": "default",
            "confidence": 0.0,
            "reasoning": "No rule or LLM matched. Default classification applied.",
            "rule_id": None,
        }

    def _build_description(self, context: dict[str, Any]) -> str:
        return (
            f"Días de mora: {context.get('overdue_days', 0)}. "
            f"Monto adeudado: {context.get('overdue_amount', 0)} {context.get('currency', 'COP')}. "
            f"Tipo de caso: {context.get('case_type', 'N/A')}. "
            f"Acciones legales previas: {context.get('has_legal_action', False)}. "
            f"Incidencias previas de mora: {context.get('previous_overdue_count', 0)}."
        )
