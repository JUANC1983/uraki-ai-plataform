# agents/decision_agent.py
"""
Decision Agent — orchestrates the full decision pipeline.

Flow:
  1. Build case context dict
  2. Compute risk score (RiskEngine)
  3. Classify case (ClassifierAgent → RuleEngine)
  4. Evaluate decision rules (RuleEngine)
  5. Construct DecisionOutput (contract)
  6. Generate suggested message (MessageAgent)
  7. Log audit trail
"""
import time
import logging
from typing import Any, Optional

from core.decision_contract import (
    CaseClassification,
    DecisionOutput,
    Firmness,
    RiskLevel,
)
from core.rule_engine import RuleEngine, RuleRecord
from core.risk_engine import RiskEngine
from agents.classifier_agent import ClassifierAgent

logger = logging.getLogger(__name__)


class DecisionAgent:
    def __init__(self) -> None:
        self._rule_engine = RuleEngine()
        self._risk_engine = RiskEngine()
        self._classifier = ClassifierAgent(self._rule_engine)

    async def evaluate(
        self,
        *,
        case_id: str,
        tenant_id: str,
        case_data: dict[str, Any],
        rules: list[RuleRecord],
        tenant_config: dict[str, Any],
        llm_connector: Optional[Any] = None,
        message_agent: Optional[Any] = None,
    ) -> DecisionOutput:
        """
        Full evaluation pipeline. Returns an immutable DecisionOutput.
        """
        start = time.time()

        # 1. Build evaluation context
        context = self._build_context(case_data)

        # 2. Risk score
        risk = self._risk_engine.compute(
            overdue_days=context.get("overdue_days", 0),
            overdue_amount=context.get("overdue_amount", 0.0),
            monthly_rent=context.get("monthly_rent", 0.0),
            has_legal_action=context.get("has_legal_action", False),
            previous_overdue_count=context.get("previous_overdue_count", 0),
            tenant_config=tenant_config,
        )
        context["risk_score"] = risk.total
        context["risk_level"] = risk.level

        # 3. Classify
        classification_result = await self._classifier.classify(
            case_context=context,
            rules=rules,
            llm_connector=llm_connector,
        )
        context["classification"] = classification_result["classification"].value

        # 4. Evaluate decision rules
        decision_rules = [r for r in rules if r.category == "decision"]
        engine_result = self._rule_engine.evaluate(rules=decision_rules, context=context)

        # 5. Build DecisionOutput
        actions = engine_result.applied_actions or {}
        rule_id = engine_result.applied_rule.id if engine_result.applied_rule else None

        validations_missing = self._check_validations(case_data, tenant_config)

        risk_level_map = {
            "BAJO": RiskLevel.LOW,
            "MEDIO": RiskLevel.MEDIUM,
            "ALTO": RiskLevel.HIGH,
        }

        decision = DecisionOutput(
            case_id=case_id,
            tenant_id=tenant_id,
            classification=classification_result["classification"],
            risk_score=risk.total,
            risk_level=risk_level_map.get(risk.level, RiskLevel.HIGH),
            action=actions.get("action", "REVISAR_MANUALMENTE"),
            firmness=Firmness(actions.get("firmness", Firmness.FIRM)),
            escalation_required=actions.get("escalation_required", False),
            escalation_target=actions.get("escalation_target"),
            legal_flag=actions.get("legal_flag", False) or risk.level == "ALTO",
            policy_flag=actions.get("policy_flag", False),
            validations_missing=validations_missing,
            rationale=engine_result.explanation,
            rule_id_applied=rule_id,
            rules_evaluated=[r.to_dict() for r in engine_result.rules_evaluated],
            rules_discarded=[r.to_dict() for r in engine_result.rules_discarded],
            confidence=classification_result["confidence"],
        )

        # 6. Optional: generate message (does not mutate decision)
        suggested_message: Optional[str] = None
        if message_agent and llm_connector:
            try:
                suggested_message = await message_agent.draft(
                    decision=decision,
                    tenant_config=tenant_config,
                    llm_connector=llm_connector,
                    case_data=case_data,   # pass so MessageAgent can inject client vars
                )
            except Exception as exc:
                logger.warning("Message generation failed: %s", exc)

        # Return final decision (with message as separate field — it's advisory)
        # We use model_copy to add optional suggested_message
        decision = decision.model_copy(update={"suggested_message": suggested_message})

        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            "Decision evaluated | case=%s tenant=%s risk=%.1f action=%s duration=%dms",
            case_id,
            tenant_id,
            risk.total,
            decision.action,
            duration_ms,
        )
        return decision

    def _build_context(self, case_data: dict[str, Any]) -> dict[str, Any]:
        """Flatten and normalize case data into evaluation context."""
        return {
            "overdue_days": int(case_data.get("overdue_days", 0)),
            "overdue_amount": float(case_data.get("overdue_amount", 0)),
            "monthly_rent": float(case_data.get("monthly_rent", 0)),
            "currency": case_data.get("currency", "COP"),
            "case_type": case_data.get("case_type", ""),
            "has_legal_action": bool(case_data.get("has_legal_action", False)),
            "previous_overdue_count": int(case_data.get("previous_overdue_count", 0)),
            "has_policy": bool(case_data.get("has_policy", False)),
            "contract_active": bool(case_data.get("contract_active", True)),
            **{k: v for k, v in case_data.items() if k not in (
                "overdue_days", "overdue_amount", "monthly_rent",
                "case_type", "has_legal_action", "previous_overdue_count",
            )},
        }

    def _check_validations(
        self, case_data: dict[str, Any], tenant_config: dict[str, Any]
    ) -> list[str]:
        """Check for required fields missing in the case."""
        required = tenant_config.get(
            "required_case_fields",
            ["client_name", "overdue_days", "monthly_rent"],
        )
        return [f for f in required if not case_data.get(f)]
