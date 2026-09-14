import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from agents.decision_agent import DecisionAgent
from api.routes.cases import CaseCreateRequest, CaseSimulationRequest, simulate_case
from api.routes.tenants import ConfigUpsert, RuleCreate
from core.config_engine import TenantConfig
from core.decision_contract import CaseClassification, CasePriority
from core.priority_engine import PriorityEngine
from core.rule_engine import RuleEngine, RuleRecord


TENANT_ID = "00000000-0000-0000-0000-000000000401"


def _rule(*, rule_id, category, priority, conditions, actions):
    return RuleRecord(
        id=rule_id,
        tenant_id=TENANT_ID,
        name=rule_id,
        category=category,
        priority=priority,
        conditions=conditions,
        actions=actions,
        constraints=None,
        explanation_template=None,
        is_active=True,
        version=1,
    )


class RuleEngineTests(unittest.TestCase):
    def test_equal_priority_tie_break_is_deterministic(self):
        rules = [
            _rule(rule_id="z-rule", category="decision", priority=10, conditions={"field":"overdue_days","op":"gte","value":1}, actions={"action":"Z"}),
            _rule(rule_id="a-rule", category="decision", priority=10, conditions={"field":"overdue_days","op":"gte","value":1}, actions={"action":"A"}),
        ]
        first=RuleEngine().evaluate(rules,{"overdue_days":2})
        second=RuleEngine().evaluate(list(reversed(rules)),{"overdue_days":2})
        self.assertEqual(first.applied_rule.id,"a-rule")
        self.assertEqual(second.applied_rule.id,"a-rule")

    def test_priority_resolves_conflicting_deterministic_rules(self):
        rules = [
            _rule(
                rule_id="lower-priority",
                category="decision",
                priority=100,
                conditions={"field": "overdue_days", "op": "gte", "value": 30},
                actions={"action": "REMIND"},
            ),
            _rule(
                rule_id="higher-priority",
                category="decision",
                priority=10,
                conditions={"field": "overdue_days", "op": "gte", "value": 90},
                actions={"action": "ESCALATE"},
            ),
        ]

        result = RuleEngine().evaluate(rules, {"overdue_days": 95})

        self.assertEqual(result.applied_rule.id, "higher-priority")
        self.assertEqual(result.applied_actions["action"], "ESCALATE")
        self.assertEqual(len(result.conflict_resolution_notes), 1)

    def test_malformed_rule_is_discarded_instead_of_crashing(self):
        malformed = _rule(
            rule_id="malformed",
            category="decision",
            priority=1,
            conditions={"logic": "AND", "conditions": []},
            actions={"action": "SHOULD_NOT_RUN"},
        )

        result = RuleEngine().evaluate([malformed], {"overdue_days": 95})

        self.assertIsNone(result.applied_rule)
        self.assertIn("Invalid rule definition", result.rules_evaluated[0].reason)

    def test_rule_api_contract_rejects_unsafe_definition(self):
        with self.assertRaises(ValidationError):
            RuleCreate(
                name="Invalid",
                category="decision",
                conditions={"logic": "AND", "conditions": []},
                actions={"action": "RUN"},
            )
        with self.assertRaises(ValidationError):
            RuleCreate(
                name="Invalid firmness",
                category="decision",
                conditions={"field": "overdue_days", "op": "gte", "value": 1},
                actions={"action": "RUN", "firmness": "UNBOUNDED"},
            )


class DeterministicGoldenPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_custom_risk_threshold_and_zero_required_value_are_preserved(self):
        from core.config_engine import RiskThresholds
        config=TenantConfig(
            tenant_id=TENANT_ID,
            risk_thresholds=RiskThresholds(
                low={"min":0,"max":10},
                medium={"min":10,"max":20},
                high={"min":20,"max":100},
            ),
        )
        decision=await DecisionAgent().evaluate(
            case_id="00000000-0000-0000-0000-000000000402",
            tenant_id=TENANT_ID,
            case_data={"client_name":"Synthetic","overdue_days":0,"monthly_rent":1000,"overdue_amount":1000},
            rules=[],tenant_config=config,
        )
        self.assertEqual(decision.risk_level.value,"MEDIO")
        self.assertNotIn("overdue_days",decision.validations_missing)

    async def test_case_to_explainable_decision_without_llm(self):
        rules = [
            _rule(
                rule_id="class-critical",
                category="classification",
                priority=10,
                conditions={"field": "overdue_days", "op": "gte", "value": 90},
                actions={"classification": "MORA_CRITICA"},
            ),
            _rule(
                rule_id="decision-escalate",
                category="decision",
                priority=10,
                conditions={"field": "overdue_days", "op": "gte", "value": 90},
                actions={
                    "action": "ESCALAR_REVISION_LEGAL",
                    "firmness": "URGENTE",
                    "escalation_required": True,
                    "escalation_target": "legal",
                    "legal_flag": True,
                    "next_step": "Review supporting documents",
                },
            ),
        ]
        case_data = {
            "case_type": "arrears",
            "client_name": "Synthetic Resident",
            "overdue_days": 95,
            "overdue_amount": 3_000_000,
            "monthly_rent": 1_000_000,
            "currency": "COP",
            "has_legal_action": False,
            "previous_overdue_count": 1,
            "has_policy": False,
            "contract_active": True,
            "document_clauses": [],
        }

        decision = await DecisionAgent().evaluate(
            case_id="00000000-0000-0000-0000-000000000402",
            tenant_id=TENANT_ID,
            case_data=case_data,
            rules=rules,
            tenant_config=TenantConfig(tenant_id=TENANT_ID),
            llm_connector=None,
            message_agent=None,
        )
        priority = PriorityEngine().compute(
            risk_score=decision.risk_score,
            escalation_required=decision.escalation_required,
            overdue_days=case_data["overdue_days"],
            legal_flag=decision.legal_flag,
        )

        self.assertEqual(decision.classification, CaseClassification.MORA_CRITICA)
        self.assertEqual(decision.classification_source, "rule_engine")
        self.assertEqual(decision.decision_source, "rule_engine")
        self.assertEqual(decision.rule_id_applied, "decision-escalate")
        self.assertEqual(decision.action, "ESCALAR_REVISION_LEGAL")
        self.assertTrue(decision.risk_factors["component_scores"])
        self.assertTrue(decision.why_this_rule)
        self.assertIn(priority.priority, {CasePriority.HIGH, CasePriority.CRITICAL})


class CaseAPIContractTests(unittest.IsolatedAsyncioTestCase):
    def test_case_create_rejects_unknown_and_negative_fields(self):
        with self.assertRaises(ValidationError):
            CaseCreateRequest(
                case_type="mora",
                client_name="Client",
                overdue_days=-1,
            )
        with self.assertRaises(ValidationError):
            CaseCreateRequest(
                case_type="mora",
                client_name="Client",
                status="CLOSED",
            )

    async def test_simulation_is_deterministic_and_does_not_persist(self):
        case = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000402",
            case_type="mora",
            client_name="Client",
            overdue_days=10,
            overdue_amount=100000.0,
            monthly_rent=500000.0,
            currency="COP",
            raw_data={},
        )

        class CaseRepo:
            async def get(self, case_id):
                return case

        class RuleRepo:
            async def get_active_rules(self):
                return []

        with patch("api.routes.cases.CaseRepository", return_value=CaseRepo()), patch(
            "api.routes.cases.RuleRepository", return_value=RuleRepo()
        ):
            result = await simulate_case(
                str(case.id),
                CaseSimulationRequest(
                    overrides={"overdue_days": 120, "has_legal_action": True}
                ),
                SimpleNamespace(tenant_id=TENANT_ID),
                SimpleNamespace(),
                TenantConfig(tenant_id=TENANT_ID),
            )

        self.assertTrue(result["simulation"])
        self.assertEqual(result["case_id"], str(case.id))
        self.assertIn("risk", result)

    def test_tenant_configuration_is_validated_before_persistence(self):
        valid = ConfigUpsert(
            config_key="rate_limits",
            config_value={"requests_per_minute": 50, "enabled": True},
        )
        self.assertEqual(valid.config_value["requests_per_minute"], 50)

        with self.assertRaises(ValidationError):
            ConfigUpsert(
                config_key="rate_limits",
                config_value={"requests_per_minute": 50, "typo": True},
            )
        with self.assertRaises(ValidationError):
            ConfigUpsert(
                config_key="priority_thresholds",
                config_value={"medium": 80, "high": 60, "critical": 90},
            )


if __name__ == "__main__":
    unittest.main()
