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
        tenant_config: Any,
        llm_connector: Optional[Any] = None,
        message_agent: Optional[Any] = None,
    ) -> DecisionOutput:
        """
        Full evaluation pipeline. Returns an immutable DecisionOutput.
        """
        start = time.time()
        config_data = (
            tenant_config.model_dump()
            if hasattr(tenant_config, "model_dump")
            else tenant_config
        )
        if not isinstance(config_data, dict):
            config_data = {}

        # 1. Build evaluation context
        context = self._build_context(case_data)

        # 2. Risk score
        risk = self._risk_engine.compute(
            overdue_days=context.get("overdue_days", 0),
            overdue_amount=context.get("overdue_amount", 0.0),
            monthly_rent=context.get("monthly_rent", 0.0),
            has_legal_action=context.get("has_legal_action", False),
            previous_overdue_count=context.get("previous_overdue_count", 0),
            tenant_config=config_data,
        )
        context["risk_score"] = risk.total
        context["risk_level"] = risk.level

        # 3. Classify
        classification_result = await self._classifier.classify(
            case_context=context,
            rules=rules,
            llm_connector=llm_connector,
        )
        # An LLM hint remains visible as advisory metadata but cannot unlock a
        # deterministic decision rule. Only a rule-derived classification has
        # decision authority; all other sources evaluate as OTRO.
        context["classification"] = (
            classification_result["classification"].value
            if classification_result["source"] == "rule_engine"
            else CaseClassification.OTRO.value
        )

        # 4. Evaluate decision rules
        decision_rules = [r for r in rules if r.category == "decision"]
        engine_result = self._rule_engine.evaluate(rules=decision_rules, context=context)

        # 5. Build DecisionOutput
        actions = engine_result.applied_actions or {}
        rule_id = engine_result.applied_rule.id if engine_result.applied_rule else None
        try:
            firmness = Firmness(actions.get("firmness", Firmness.FIRM))
        except (TypeError, ValueError):
            logger.error("Invalid firmness in rule %s; using FIRME", rule_id)
            firmness = Firmness.FIRM

        validations_missing = self._check_validations(case_data, config_data)

        risk_level_map = {
            "BAJO": RiskLevel.LOW,
            "MEDIO": RiskLevel.MEDIUM,
            "ALTO": RiskLevel.HIGH,
        }

        decision = DecisionOutput(
            case_id=case_id,
            tenant_id=tenant_id,
            classification=classification_result["classification"],
            classification_source=classification_result["source"],
            classification_reasoning=classification_result["reasoning"],
            risk_score=risk.total,
            risk_level=risk_level_map.get(risk.level, RiskLevel.HIGH),
            risk_factors={
                "component_scores": risk.component_scores,
                "weights_used": risk.weights_used,
                "thresholds_used": risk.thresholds_used,
                "component_reasons": risk.component_reasons,
            },
            action=actions.get("action", "REVISAR_MANUALMENTE"),
            decision_source=(
                "rule_engine" if engine_result.applied_rule else "deterministic_fallback"
            ),
            firmness=firmness,
            next_step=actions.get("next_step"),
            escalation_required=actions.get("escalation_required", False),
            escalation_target=actions.get("escalation_target"),
            legal_flag=actions.get("legal_flag", False) or risk.level == "ALTO",
            policy_flag=actions.get("policy_flag", False),
            validations_missing=validations_missing,
            rationale=engine_result.explanation,
            why_this_rule=engine_result.explanation if engine_result.applied_rule else None,
            what_happens_next=actions.get("what_happens_next"),
            rule_id_applied=rule_id,
            rule_version_used=(
                engine_result.applied_rule.version if engine_result.applied_rule else None
            ),
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
                logger.warning("Message generation failed (%s)", type(exc).__name__)

        if suggested_message is not None and (
            not isinstance(suggested_message, str) or len(suggested_message) > 10000
        ):
            logger.warning("Message generation returned an invalid bounded text value")
            suggested_message = None

        # model_copy(update=...) bypasses Pydantic validation. Revalidate the
        # optional AI field before it crosses the decision contract boundary.
        decision = DecisionOutput.model_validate({
            **decision.model_dump(),
            "suggested_message": suggested_message,
        })

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
                "currency", "case_type", "has_legal_action",
                "previous_overdue_count", "has_policy", "contract_active",
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
        return [
            field for field in required
            if field not in case_data
            or case_data[field] is None
            or (isinstance(case_data[field], str) and not case_data[field].strip())
        ]
