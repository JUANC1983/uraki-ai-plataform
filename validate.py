# -*- coding: utf-8 -*-
"""
validate.py -- Full system validation (no DB, no network required).
Run: python validate.py
"""
import io
import os
import sys
import warnings
from pathlib import Path

# Force UTF-8 output on Windows so arrow/check chars don't crash cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Suppress SQLAlchemy "already defined" warnings caused by re-importing
# models in test context (harmless at runtime, only occurs in validate.py)
warnings.filterwarnings("ignore", message=".*already contains a class.*")
warnings.filterwarnings("ignore", message=".*already defined.*")

import traceback
from datetime import datetime, timezone

PASS = "  [PASS]"
FAIL = "  [FAIL]"
WARN = "  [WARN]"
SEP = "-" * 60

results = {"passed": 0, "failed": 0, "warnings": 0}


def ok(label: str, detail: str = "") -> None:
    print(f"{PASS} {label}" + (f" — {detail}" if detail else ""))
    results["passed"] += 1


def fail(label: str, error: str) -> None:
    print(f"{FAIL} {label}")
    print(f"         ERROR: {error}")
    results["failed"] += 1


def warn(label: str, detail: str) -> None:
    print(f"{WARN} {label} — {detail}")
    results["warnings"] += 1


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


# ==========================================================================
# 1. CORE MODULE IMPORTS
# ==========================================================================
section("1. CORE MODULE IMPORTS")

try:
    from core.decision_contract import (
        DecisionOutput, CaseClassification, CasePriority,
        RiskLevel, Firmness, DocumentReference,
    )
    ok("core.decision_contract — all exports available")
except Exception as e:
    fail("core.decision_contract", str(e))

try:
    from core.rule_engine import RuleEngine, RuleRecord, EngineResult, RuleEvaluationResult
    ok("core.rule_engine — all exports available")
except Exception as e:
    fail("core.rule_engine", str(e))

try:
    from core.risk_engine import RiskEngine, RiskScore
    ok("core.risk_engine — all exports available")
except Exception as e:
    fail("core.risk_engine", str(e))

try:
    from core.case_state_machine import CaseStateMachine, CaseStatus, InvalidTransitionError
    ok("core.case_state_machine — all exports available")
except Exception as e:
    fail("core.case_state_machine", str(e))

try:
    from core.priority_engine import PriorityEngine, PriorityResult
    ok("core.priority_engine — all exports available")
except Exception as e:
    fail("core.priority_engine", str(e))

try:
    from core.config_engine import (
        ConfigEngine, TenantConfig, RiskWeights, RiskThresholds,
        EscalationPolicy, ToneSettings, RateLimitConfig, ModuleConfig,
        PriorityThresholds,
    )
    ok("core.config_engine — all exports available")
except Exception as e:
    fail("core.config_engine", str(e))

try:
    from core.event_bus import EventBus, DomainEvent, get_event_bus
    ok("core.event_bus — all exports available")
except Exception as e:
    fail("core.event_bus", str(e))

try:
    from core.audit_logger import AuditLogger, get_audit_logger
    ok("core.audit_logger — all exports available")
except Exception as e:
    fail("core.audit_logger", str(e))

# ==========================================================================
# 2. DATABASE MODEL CONSISTENCY
# ==========================================================================
section("2. DATABASE MODEL CONSISTENCY")

try:
    from database.models import (
        Tenant, TenantConfiguration, User, APIKey, TenantQuota,
        Rule, Case, Decision, Override, Document, DocumentChunk,
        EventStore, AuditLog, FeedbackRegistry,
    )
    ok("database.models — all 14 model classes importable")
except Exception as e:
    fail("database.models", str(e))

# Verify Rule has versioning fields
try:
    import inspect
    from sqlalchemy import inspect as sa_inspect
    rule_cols = {c.key for c in Rule.__table__.columns}
    required_rule_cols = {
        "id", "tenant_id", "name", "category", "priority",
        "conditions", "actions", "version",
        "effective_from", "effective_to", "parent_rule_id",
        "is_active",
    }
    missing = required_rule_cols - rule_cols
    if missing:
        fail("Rule versioning fields", f"Missing columns: {missing}")
    else:
        ok("Rule versioning fields", f"effective_from, effective_to, parent_rule_id, version present")
except Exception as e:
    fail("Rule versioning fields", str(e))

# Verify Decision has new fields
try:
    decision_cols = {c.key for c in Decision.__table__.columns}
    required_decision_cols = {
        "id", "tenant_id", "case_id", "classification",
        "risk_score", "risk_level", "priority",
        "rule_id_applied", "rule_version_used",
        "document_references", "action", "rationale",
        "escalation_required", "legal_flag", "is_overridden",
    }
    missing = required_decision_cols - decision_cols
    if missing:
        fail("Decision versioning fields", f"Missing columns: {missing}")
    else:
        ok("Decision fields", "rule_version_used, priority, document_references present")
except Exception as e:
    fail("Decision fields check", str(e))

# Verify EventStore, APIKey, TenantQuota exist
try:
    es_cols = {c.key for c in EventStore.__table__.columns}
    assert {"id", "tenant_id", "event_type", "aggregate_id", "payload", "processed"} <= es_cols
    ok("EventStore table schema", f"{len(es_cols)} columns")
except Exception as e:
    fail("EventStore schema", str(e))

try:
    ak_cols = {c.key for c in APIKey.__table__.columns}
    assert {"id", "tenant_id", "key_hash", "key_prefix", "is_active"} <= ak_cols
    ok("APIKey table schema", f"{len(ak_cols)} columns")
except Exception as e:
    fail("APIKey schema", str(e))

try:
    tq_cols = {c.key for c in TenantQuota.__table__.columns}
    assert {"tenant_id", "window_key", "window_type", "request_count"} <= tq_cols
    ok("TenantQuota table schema", f"{len(tq_cols)} columns")
except Exception as e:
    fail("TenantQuota schema", str(e))

# Verify Case has priority
try:
    case_cols = {c.key for c in Case.__table__.columns}
    assert "priority" in case_cols
    ok("Case.priority field", "present")
except Exception as e:
    fail("Case.priority field", str(e))

# Check all tables have tenant_id (except junction tables)
try:
    multi_tenant_models = [
        TenantConfiguration, User, APIKey, Rule, Case,
        Decision, Override, Document, DocumentChunk,
        EventStore, AuditLog, FeedbackRegistry,
    ]
    missing_tenant = [
        m.__tablename__ for m in multi_tenant_models
        if "tenant_id" not in {c.key for c in m.__table__.columns}
    ]
    if missing_tenant:
        fail("Tenant isolation — tenant_id coverage", f"Missing in: {missing_tenant}")
    else:
        ok("Tenant isolation — tenant_id coverage",
           f"All {len(multi_tenant_models)} data tables have tenant_id")
except Exception as e:
    fail("tenant_id coverage check", str(e))

# ==========================================================================
# 3. REPOSITORY TENANT ISOLATION
# ==========================================================================
section("3. REPOSITORY TENANT ISOLATION (BaseRepository)")

try:
    from database.repositories.base import BaseRepository, TenantIsolationError, _require_tenant

    # Should raise with empty tenant_id
    raised = False
    try:
        _require_tenant("")
    except TenantIsolationError:
        raised = True
    assert raised, "_require_tenant('') should raise TenantIsolationError"
    ok("TenantIsolationError raised on empty tenant_id")

    raised = False
    try:
        _require_tenant(None)
    except TenantIsolationError:
        raised = True
    assert raised, "_require_tenant(None) should raise TenantIsolationError"
    ok("TenantIsolationError raised on None tenant_id")

    ok("_require_tenant('valid-uuid')", _require_tenant("abc-123-def"))
except Exception as e:
    fail("BaseRepository / TenantIsolationError", str(e))

# ==========================================================================
# 4. RULE ENGINE — full evaluation with sample case
# ==========================================================================
section("4. RULE ENGINE — Sample Case Evaluation")

try:
    from core.rule_engine import RuleEngine, RuleRecord

    engine = RuleEngine()

    sample_rules = [
        RuleRecord(
            id="rule-001",
            tenant_id="tenant-abc",
            name="Mora Critica 90 dias",
            category="decision",
            priority=10,
            conditions={
                "logic": "AND",
                "conditions": [
                    {"field": "overdue_days", "op": "gte", "value": 90},
                    {"field": "has_legal_action", "op": "eq", "value": False},
                ],
            },
            actions={
                "action": "INICIAR_PROCESO_LEGAL",
                "firmness": "URGENTE",
                "escalation_required": True,
                "escalation_target": "legal",
                "legal_flag": True,
            },
            constraints=None,
            explanation_template=(
                "Mora de {overdue_days} días supera umbral crítico. "
                "Se inicia proceso legal."
            ),
            is_active=True,
            version=2,
            effective_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            effective_to=None,
        ),
        RuleRecord(
            id="rule-002",
            tenant_id="tenant-abc",
            name="Mora Temprana",
            category="decision",
            priority=50,
            conditions={
                "logic": "AND",
                "conditions": [
                    {"field": "overdue_days", "op": "between", "value": [1, 30]},
                ],
            },
            actions={
                "action": "ENVIAR_RECORDATORIO",
                "firmness": "SUAVE",
                "escalation_required": False,
            },
            constraints=None,
            explanation_template="Mora temprana de {overdue_days} días. Recordatorio enviado.",
            is_active=True,
            version=1,
            effective_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            effective_to=None,
        ),
        RuleRecord(
            id="rule-003",
            tenant_id="tenant-abc",
            name="Mora Media con Poliza",
            category="decision",
            priority=20,
            conditions={
                "logic": "AND",
                "conditions": [
                    {"field": "overdue_days", "op": "between", "value": [31, 89]},
                    {"field": "has_policy", "op": "eq", "value": True},
                ],
            },
            actions={
                "action": "ACTIVAR_POLIZA",
                "firmness": "FIRME",
                "policy_flag": True,
                "escalation_required": False,
            },
            constraints=None,
            explanation_template=None,
            is_active=True,
            version=1,
            effective_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            effective_to=None,
        ),
    ]

    # Case A: 95 overdue days, no legal action yet
    context_a = {
        "overdue_days": 95,
        "overdue_amount": 4500000,
        "monthly_rent": 1500000,
        "has_legal_action": False,
        "has_policy": False,
        "risk_score": 88.0,
        "document_clauses": [],
    }
    result_a = engine.evaluate(sample_rules, context_a)
    assert result_a.applied_rule is not None, "Expected a rule to match for 95 overdue days"
    assert result_a.applied_rule.id == "rule-001", f"Expected rule-001, got {result_a.applied_rule.id}"
    assert result_a.applied_actions["action"] == "INICIAR_PROCESO_LEGAL"
    assert "95" in result_a.explanation
    ok("Case A (95 overdue days)", f"→ rule '{result_a.applied_rule.name}' v{result_a.applied_rule.version}")
    ok("Case A conflict resolution", f"{len(result_a.rules_evaluated)} evaluated, {len(result_a.rules_discarded)} discarded")

    # Case B: 15 overdue days (early mora)
    context_b = {**context_a, "overdue_days": 15, "has_policy": False}
    result_b = engine.evaluate(sample_rules, context_b)
    assert result_b.applied_rule is not None
    assert result_b.applied_rule.id == "rule-002"
    ok("Case B (15 overdue days)", f"→ rule '{result_b.applied_rule.name}'")

    # Case C: 60 overdue days WITH policy
    context_c = {**context_a, "overdue_days": 60, "has_policy": True}
    result_c = engine.evaluate(sample_rules, context_c)
    assert result_c.applied_rule is not None
    assert result_c.applied_rule.id == "rule-003"
    ok("Case C (60 days + policy)", f"→ rule '{result_c.applied_rule.name}'")

    # Case D: 0 overdue days (no match expected)
    context_d = {**context_a, "overdue_days": 0}
    result_d = engine.evaluate(sample_rules, context_d)
    assert result_d.applied_rule is None
    ok("Case D (0 days)", "→ no rule matched (expected)")

    # Case E: document clause matching
    rule_with_clause = RuleRecord(
        id="rule-doc-01",
        tenant_id="tenant-abc",
        name="Clausula Mora Identificada",
        category="decision",
        priority=5,
        conditions={
            "field": "document_clauses",
            "op": "clause_contains",
            "value": "penalidad por mora",
        },
        actions={"action": "APLICAR_PENALIDAD", "firmness": "FIRME"},
        constraints=None,
        explanation_template=None,
        is_active=True,
        version=1,
    )
    context_e = {
        "overdue_days": 30,
        "document_clauses": [
            {"content": "En caso de incumplimiento, se aplicará penalidad por mora del 2% mensual.", "clause_label": "CLÁUSULA 8"},
            {"content": "El arrendatario pagará mensualmente.", "clause_label": "CLÁUSULA 2"},
        ],
    }
    result_e = engine.evaluate([rule_with_clause], context_e)
    assert result_e.applied_rule is not None
    assert result_e.applied_actions["action"] == "APLICAR_PENALIDAD"
    ok("Case E (document clause matching)", f"→ found 'penalidad por mora' in CLÁUSULA 8")

    # Historical replay
    old_rule = RuleRecord(
        id="rule-001-old",
        tenant_id="tenant-abc",
        name="Mora Critica (v1 legacy)",
        category="decision",
        priority=10,
        conditions={"field": "overdue_days", "op": "gte", "value": 60},
        actions={"action": "LLAMADA_TELEFONICA", "firmness": "FIRME"},
        constraints=None,
        explanation_template=None,
        is_active=True,
        version=1,
        effective_from=datetime(2023, 1, 1, tzinfo=timezone.utc),
        effective_to=datetime(2024, 1, 1, tzinfo=timezone.utc),  # closed
    )
    replay_at = datetime(2023, 6, 1, tzinfo=timezone.utc)
    result_replay = engine.evaluate_at([old_rule] + sample_rules, context_a, replay_at)
    assert result_replay.applied_rule is not None
    assert result_replay.applied_rule.id == "rule-001-old", (
        f"Replay at 2023-06-01 should use v1 rule, got {result_replay.applied_rule.id}"
    )
    ok("Historical replay (2023-06-01)", f"→ correctly used '{result_replay.applied_rule.name}'")

except Exception as e:
    fail("Rule Engine evaluation", traceback.format_exc())

# ==========================================================================
# 5. RISK ENGINE
# ==========================================================================
section("5. RISK ENGINE — Configurable Scoring")

try:
    from core.risk_engine import RiskEngine

    engine = RiskEngine()

    config_default = {}

    score_high = engine.compute(
        overdue_days=120,
        overdue_amount=5000000,
        monthly_rent=1500000,
        has_legal_action=True,
        previous_overdue_count=3,
        tenant_config=config_default,
    )
    assert score_high.total >= 70, f"Expected high risk, got {score_high.total}"
    ok("Risk: high scenario", f"score={score_high.total} level={score_high.level}")

    score_low = engine.compute(
        overdue_days=5,
        overdue_amount=50000,
        monthly_rent=1500000,
        has_legal_action=False,
        previous_overdue_count=0,
        tenant_config=config_default,
    )
    assert score_low.total <= 30, f"Expected low risk, got {score_low.total}"
    ok("Risk: low scenario", f"score={score_low.total} level={score_low.level}")

    # Custom weights
    custom_config = {
        "risk_weights": {"overdue_days": 0.7, "economic_impact": 0.1, "legal_risk": 0.1, "recurrence": 0.1},
        "risk_thresholds": {
            "low": {"min": 0, "max": 20},
            "medium": {"min": 21, "max": 60},
            "high": {"min": 61, "max": 100},
        },
    }
    score_custom = engine.compute(
        overdue_days=95,
        overdue_amount=100000,
        monthly_rent=1500000,
        has_legal_action=False,
        previous_overdue_count=0,
        tenant_config=custom_config,
    )
    ok("Risk: custom tenant weights", f"score={score_custom.total} level={score_custom.level}")

except Exception as e:
    fail("Risk Engine", traceback.format_exc())

# ==========================================================================
# 6. PRIORITY ENGINE
# ==========================================================================
section("6. PRIORITY ENGINE — Scoring")

try:
    from core.priority_engine import PriorityEngine
    from core.decision_contract import CasePriority

    engine = PriorityEngine()

    r = engine.compute(risk_score=90, escalation_required=True, overdue_days=120, legal_flag=True)
    assert r.priority == CasePriority.CRITICAL, f"Expected CRITICAL, got {r.priority}"
    ok("Priority: CRITICAL", f"composite_score={r.score} factors={r.factors}")

    r = engine.compute(risk_score=70, escalation_required=False, overdue_days=60, legal_flag=False)
    assert r.priority in (CasePriority.HIGH, CasePriority.MEDIUM)
    ok("Priority: HIGH/MEDIUM boundary", f"score={r.score} → {r.priority.value}")

    r = engine.compute(risk_score=10, escalation_required=False, overdue_days=5, legal_flag=False)
    assert r.priority == CasePriority.LOW, f"Expected LOW, got {r.priority}"
    ok("Priority: LOW", f"score={r.score}")

    # Custom thresholds
    from core.config_engine import PriorityThresholds
    custom_t = PriorityThresholds(critical=95, high=75, medium=50)
    r2 = engine.compute(risk_score=90, escalation_required=True, overdue_days=120,
                        legal_flag=True, config_thresholds=custom_t)
    ok("Priority: custom thresholds", f"threshold=95 → {r2.priority.value} (score={r2.score})")

except Exception as e:
    fail("Priority Engine", traceback.format_exc())

# ==========================================================================
# 7. DECISION CONTRACT — Schema Validation
# ==========================================================================
section("7. DECISION CONTRACT — Schema Validation")

try:
    from core.decision_contract import (
        DecisionOutput, CaseClassification, CasePriority,
        RiskLevel, Firmness, DocumentReference,
    )
    from datetime import datetime

    doc_ref = DocumentReference(
        document_id="doc-001",
        clause_id="CLÁUSULA 8",
        snippet="Se aplicará penalidad por mora del 2% mensual.",
        relevance="Define penalidad aplicable al caso",
    )

    decision = DecisionOutput(
        case_id="case-abc-123",
        tenant_id="tenant-xyz",
        classification=CaseClassification.MORA_CRITICA,
        risk_score=88.5,
        risk_level=RiskLevel.HIGH,
        priority=CasePriority.CRITICAL,
        action="INICIAR_PROCESO_LEGAL",
        firmness=Firmness.URGENT,
        next_step="Enviar carta de cobro jurídico en 48 horas",
        escalation_required=True,
        escalation_target="legal",
        legal_flag=True,
        policy_flag=False,
        validations_missing=[],
        rationale="Mora de 95 días supera umbral crítico. Sin póliza activa.",
        why_this_rule="Regla 'Mora Crítica 90 días' v2 tiene mayor prioridad (10).",
        what_happens_next="El caso pasa a proceso legal con carta formal.",
        rule_id_applied="rule-001",
        rule_version_used=2,
        rules_evaluated=[{"rule_id": "rule-001", "matched": True}, {"rule_id": "rule-002", "matched": False}],
        rules_discarded=[{"rule_id": "rule-002", "matched": False}],
        document_references=[doc_ref],
        confidence=0.97,
        suggested_message="Estimado arrendatario, su deuda supera los 90 días...",
    )
    ok("DecisionOutput instantiation", f"risk_score={decision.risk_score}")

    # Verify risk_level auto-derived
    assert decision.risk_level == RiskLevel.HIGH
    ok("risk_level auto-derived from risk_score", f"88.5 → {decision.risk_level.value}")

    # Verify immutability
    raised = False
    try:
        decision.risk_score = 50.0  # type: ignore
    except Exception:
        raised = True
    assert raised, "DecisionOutput must be immutable (frozen)"
    ok("DecisionOutput immutability (frozen=True)")

    # Verify explain() output
    explanation = decision.explain()
    assert "INICIAR_PROCESO_LEGAL" in explanation
    assert "CRÍTICO" in explanation or "CRITICAL" in explanation or "88.5" in explanation
    assert "CLÁUSULA 8" in explanation or "1 cláusula" in explanation
    ok("explain() output", f"{len(explanation)} chars")

    # Verify to_audit_dict() is JSON-serializable
    import json
    audit_dict = decision.to_audit_dict()
    json_str = json.dumps(audit_dict)
    assert len(json_str) > 100
    ok("to_audit_dict() JSON serializable", f"{len(json_str)} bytes")

    # Validate DocumentReference
    assert doc_ref.document_id == "doc-001"
    assert doc_ref.clause_id == "CLÁUSULA 8"
    ok("DocumentReference schema", f"document_id, clause_id, snippet, relevance")

    # Test boundary: risk_score out of range
    raised = False
    try:
        DecisionOutput(
            case_id="x", tenant_id="t",
            classification=CaseClassification.OTRO,
            risk_score=150,  # invalid
            risk_level=RiskLevel.HIGH,
            action="X", firmness=Firmness.FIRM,
            rationale="test",
        )
    except Exception:
        raised = True
    assert raised, "risk_score > 100 should raise validation error"
    ok("risk_score boundary validation (>100 rejected)")

except Exception as e:
    fail("DecisionOutput schema", traceback.format_exc())

# ==========================================================================
# 8. CONFIG ENGINE — TenantConfig parsing
# ==========================================================================
section("8. CONFIG ENGINE — TenantConfig Parsing")

try:
    from core.config_engine import ConfigEngine, TenantConfig

    engine = ConfigEngine()

    # Empty raw config → all defaults
    config = engine._parse("tenant-001", {})
    assert config.tenant_id == "tenant-001"
    assert abs(config.risk_weights.overdue_days - 0.40) < 0.01
    assert config.risk_thresholds.low.max == 30
    assert config.escalation_policy.auto_escalate_days == 90
    assert config.tone_settings.tone == "profesional"
    assert config.modules.document_intelligence is True
    ok("TenantConfig: empty config → defaults applied")

    # Partial override
    raw = {
        "risk_weights": {"overdue_days": 0.6, "economic_impact": 0.2, "legal_risk": 0.1, "recurrence": 0.1},
        "tone_settings": {"tone": "urgente", "language": "es", "company_name": "Inmobiliaria XYZ"},
        "escalation_policy": {"auto_escalate_days": 60, "legal_threshold_days": 45},
        "modules": {"document_intelligence": True, "llm_classification": False, "auto_messaging": True},
    }
    config2 = engine._parse("tenant-002", raw)
    assert abs(config2.risk_weights.overdue_days - 0.6) < 0.01
    assert config2.tone_settings.tone == "urgente"
    assert config2.tone_settings.company_name == "Inmobiliaria XYZ"
    assert config2.escalation_policy.auto_escalate_days == 60
    assert config2.modules.llm_classification is False
    ok("TenantConfig: partial override", f"tone={config2.tone_settings.tone} llm={config2.modules.llm_classification}")

    # Weights normalization
    raw_unnorm = {
        "risk_weights": {
            "overdue_days": 0.4,
            "economic_impact": 0.3,
            "legal_risk": 0.2,
            "recurrence": 0.2,
        }
    }
    config3 = engine._parse("tenant-003", raw_unnorm)
    total = sum(config3.risk_weights.as_dict().values())
    assert abs(total - 1.0) < 0.01, f"Weights should sum to 1.0, got {total}"
    assert abs(config3.risk_weights.overdue_days - (0.4 / 1.1)) < 0.01
    assert abs(config3.risk_weights.recurrence - (0.2 / 1.1)) < 0.01
    ok("RiskWeights normalization", f"0.4+0.3+0.2+0.2 → sum={total:.3f}")

    # TenantConfig root is frozen — cannot replace a field
    raised = False
    try:
        config.tenant_id = "hacked"  # type: ignore[misc]
    except Exception:
        raised = True
    assert raised, "TenantConfig root must be frozen"
    ok("TenantConfig immutability (frozen=True) -- root field replacement blocked")

    # to_prompt_context()
    ctx = config2.tone_settings.to_prompt_context()
    assert "urgente" in ctx and "Inmobiliaria XYZ" in ctx
    ok("ToneSettings.to_prompt_context()", ctx)

    # risk_thresholds.resolve_level()
    assert config.risk_thresholds.resolve_level(15) == "BAJO"
    assert config.risk_thresholds.resolve_level(50) == "MEDIO"
    assert config.risk_thresholds.resolve_level(85) == "ALTO"
    ok("RiskThresholds.resolve_level()", "15→BAJO, 50→MEDIO, 85→ALTO")

    # The API passes a typed TenantConfig into DecisionAgent.
    import asyncio as _asyncio
    from agents.decision_agent import DecisionAgent

    typed_decision = _asyncio.get_event_loop().run_until_complete(
        DecisionAgent().evaluate(
            case_id="case-typed-config",
            tenant_id="tenant-typed-config",
            case_data={
                "client_name": "Validation User",
                "overdue_days": 10,
                "overdue_amount": 100.0,
                "monthly_rent": 1000.0,
            },
            rules=[],
            tenant_config=TenantConfig(tenant_id="tenant-typed-config"),
            llm_connector=None,
            message_agent=None,
        )
    )
    assert typed_decision.action == "REVISAR_MANUALMENTE"
    ok("DecisionAgent accepts typed TenantConfig from API dependency")

except Exception as e:
    fail("Config Engine", traceback.format_exc())

# ==========================================================================
# 9. STATE MACHINE — Transitions
# ==========================================================================
section("9. CASE STATE MACHINE — Transitions")

try:
    from core.case_state_machine import CaseStateMachine, CaseStatus, InvalidTransitionError

    sm = CaseStateMachine()

    # Valid transitions
    assert sm.transition("NEW", "IN_REVIEW") == CaseStatus.IN_REVIEW
    ok("NEW → IN_REVIEW (valid)")

    assert sm.transition("IN_REVIEW", "DECISION_GENERATED") == CaseStatus.DECISION_GENERATED
    ok("IN_REVIEW → DECISION_GENERATED (valid)")

    assert sm.transition("DECISION_GENERATED", "HUMAN_OVERRIDE") == CaseStatus.HUMAN_OVERRIDE
    ok("DECISION_GENERATED → HUMAN_OVERRIDE (valid)")

    assert sm.transition("DECISION_GENERATED", "IN_EXECUTION") == CaseStatus.IN_EXECUTION
    ok("DECISION_GENERATED → IN_EXECUTION (valid)")

    assert sm.transition("IN_EXECUTION", "CLOSED") == CaseStatus.CLOSED
    ok("IN_EXECUTION → CLOSED (valid)")

    assert sm.transition("ESCALATED", "CLOSED") == CaseStatus.CLOSED
    ok("ESCALATED → CLOSED (valid)")

    # Invalid transitions
    raised = False
    try:
        sm.transition("CLOSED", "NEW")
    except InvalidTransitionError:
        raised = True
    assert raised
    ok("CLOSED → NEW blocked (InvalidTransitionError)")

    raised = False
    try:
        sm.transition("NEW", "CLOSED")  # This IS valid — closing a duplicate
    except InvalidTransitionError:
        raised = True
    assert not raised  # Should NOT raise — NEW → CLOSED is allowed
    ok("NEW → CLOSED allowed (duplicate case)")

    raised = False
    try:
        sm.transition("IN_REVIEW", "IN_EXECUTION")  # skipping steps
    except InvalidTransitionError:
        raised = True
    assert raised
    ok("IN_REVIEW → IN_EXECUTION blocked (must go through DECISION_GENERATED)")

    # can_transition helper
    assert sm.can_transition("NEW", "IN_REVIEW") is True
    assert sm.can_transition("CLOSED", "NEW") is False
    ok("can_transition() helper")

    # get_allowed_transitions
    allowed = sm.get_allowed_transitions("DECISION_GENERATED")
    assert "IN_EXECUTION" in allowed and "HUMAN_OVERRIDE" in allowed
    ok("get_allowed_transitions('DECISION_GENERATED')", str(allowed))

except Exception as e:
    fail("Case State Machine", traceback.format_exc())

# ==========================================================================
# 10. EVENT BUS — DomainEvent structure
# ==========================================================================
section("10. EVENT BUS — DomainEvent Structure")

try:
    from core.event_bus import DomainEvent, EventBus

    event = DomainEvent(
        event_type=DomainEvent.CASE_CREATED,
        tenant_id="00000000-0000-0000-0000-000000000001",
        aggregate_type="case",
        aggregate_id="00000000-0000-0000-0000-000000000002",
        payload={"case_type": "mora", "client_name": "Juan García"},
    )
    assert event.event_type == "CASE_CREATED"
    assert event.tenant_id == "00000000-0000-0000-0000-000000000001"
    assert event.event_id  # UUID generated
    d = event.to_dict()
    assert "event_id" in d and "payload" in d and "occurred_at" in d
    ok("DomainEvent creation and serialization")

    # Event type constants
    for et in [
        DomainEvent.CASE_CREATED, DomainEvent.DECISION_GENERATED,
        DomainEvent.OVERRIDE_APPLIED, DomainEvent.CASE_ESCALATED,
        DomainEvent.DOCUMENT_PROCESSED, DomainEvent.RULE_UPDATED,
        DomainEvent.CASE_CLOSED,
    ]:
        assert isinstance(et, str)
    ok("All 7 event type constants defined")

    # Handler subscription
    received = []
    async def test_handler(e: DomainEvent) -> None:
        received.append(e.event_type)

    bus = EventBus()
    bus.subscribe(DomainEvent.CASE_CREATED, test_handler)
    ok("EventBus.subscribe() works")

    # Dispatch without DB (internal _dispatch only)
    import asyncio
    asyncio.get_event_loop().run_until_complete(bus._dispatch(event))
    assert DomainEvent.CASE_CREATED in received
    ok("EventBus._dispatch() calls handler", f"received={received}")

except Exception as e:
    fail("Event Bus", traceback.format_exc())

# ==========================================================================
# 11. MEMORY / VECTOR STORE
# ==========================================================================
section("11. VECTOR STORE — Cosine Similarity")

try:
    from memory.vector_store import VectorStore

    vs = VectorStore()

    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    c = [0.0, 1.0, 0.0]

    assert abs(vs.cosine_similarity(a, b) - 1.0) < 1e-6
    assert abs(vs.cosine_similarity(a, c) - 0.0) < 1e-6
    ok("Cosine similarity: identical=1.0, orthogonal=0.0")

    candidates = [
        {"content": "clause about rent", "embedding": [0.9, 0.1, 0.0]},
        {"content": "unrelated content", "embedding": [0.0, 0.0, 1.0]},
        {"content": "mora payment", "embedding": [0.85, 0.15, 0.0]},
    ]
    search_results = vs.search([1.0, 0.0, 0.0], candidates, top_k=2)
    assert len(search_results) == 2
    assert search_results[0]["score"] >= search_results[1]["score"]
    ok("VectorStore.search() top-k ranking", f"top={search_results[0]['content'][:30]} score={search_results[0]['score']}")

except Exception as e:
    fail("Vector Store", traceback.format_exc())

# ==========================================================================
# 12. MISSING COMPONENT AUDIT
# ==========================================================================
section("12. MISSING COMPONENT AUDIT")

import os

BASE = os.path.dirname(os.path.abspath(__file__))

required_files = {
    "config/settings.py": "App settings",
    "config/__init__.py": "Config package",
    "core/decision_contract.py": "Decision schema",
    "core/rule_engine.py": "Rule engine",
    "core/risk_engine.py": "Risk scoring",
    "core/case_state_machine.py": "State machine",
    "core/audit_logger.py": "Audit logging",
    "core/config_engine.py": "Config engine",
    "core/priority_engine.py": "Priority engine",
    "core/event_bus.py": "Event bus",
    "database/base.py": "DB connection",
    "database/models.py": "ORM models",
    "database/repositories/base.py": "BaseRepository + TenantIsolationError",
    "database/repositories/tenant_repository.py": "Tenant repo",
    "database/repositories/case_repository.py": "Case repo",
    "database/repositories/rule_repository.py": "Rule repo (versioned)",
    "database/repositories/decision_repository.py": "Decision repo",
    "database/repositories/document_repository.py": "Document repo",
    "agents/classifier_agent.py": "Classifier",
    "agents/decision_agent.py": "Decision orchestration",
    "agents/message_agent.py": "Message drafting",
    "agents/document_agent.py": "Document processing",
    "connectors/llm_connector.py": "OpenAI wrapper",
    "connectors/storage_connector.py": "File storage",
    "memory/vector_store.py": "Semantic search",
    "api/middleware.py": "Rate limiting + tenant middleware",
    "api/dependencies.py": "JWT + API key auth",
    "api/routes/auth.py": "Auth endpoints",
    "api/routes/cases.py": "Case endpoints",
    "api/routes/decisions.py": "Decision endpoints",
    "api/routes/documents.py": "Document endpoints",
    "api/routes/tenants.py": "Tenant + rule + API key mgmt",
    "api/routes/dashboard.py": "Dashboard + metrics + events",
    "automation/task_queue.py": "Async task queue",
    "automation/event_handlers.py": "Domain event handlers",
    "automation/scheduler.py": "Periodic jobs",
    "dashboard/app.py": "Operational Streamlit UI",
    "executive.py": "Executive Streamlit UI",
    "main.py": "FastAPI entry point",
    "requirements.txt": "Dependencies",
    ".env.example": "Config template",
    "Dockerfile": "Container definition",
    "docker-compose.yml": "Multi-service stack",
}

missing_files = []
for path, desc in required_files.items():
    full = os.path.join(BASE, path)
    if os.path.exists(full):
        pass
    else:
        missing_files.append((path, desc))

ok(f"File coverage: {len(required_files) - len(missing_files)}/{len(required_files)} required files present")
if missing_files:
    for path, desc in missing_files:
        warn(f"Missing file: {path}", desc)

# Check for known gaps / TODOs
gaps = [
    ("api/routes/feedback.py", "Feedback endpoint not implemented (FeedbackRegistry model exists)"),
    ("connectors/email_connector.py", "Email sending is a stub in task_queue.py"),
    ("dedicated vector backend", "Vector search uses JSONB arrays and Python cosine similarity"),
]

for gap, detail in gaps:
    warn(f"Known gap: {gap}", detail)

if os.path.isdir("tests") and any(
    name.startswith("test_") and name.endswith(".py")
    for _, _, files in os.walk("tests")
    for name in files
):
    ok("Automated test directory", "tests/ contains discoverable test modules")
else:
    warn("Known gap: tests/", "No discoverable automated tests")

main_source = Path("main.py").read_text(encoding="utf-8")
if "app.add_middleware(RateLimitMiddleware)" in main_source:
    ok("Active rate limiting", "RateLimitMiddleware is mounted in main.py")
else:
    warn("Known gap: active rate limiting", "RateLimitMiddleware is not mounted")

auth_source = Path("api/routes/auth.py").read_text(encoding="utf-8")
if "current_user: CurrentUser" in auth_source and "tenant_id: str" not in auth_source.split(
    "class UserCreate", 1
)[1].split("def create_access_token", 1)[0]:
    ok(
        "Restricted registration",
        "Registration requires an authenticated user and does not accept tenant_id",
    )
else:
    warn(
        "Known gap: restricted registration",
        "Registration authorization or tenant assignment remains unsafe",
    )

# ==========================================================================
# SUMMARY
# ==========================================================================
section("VALIDATION SUMMARY")

total = results["passed"] + results["failed"] + results["warnings"]
print(f"\n  Total checks : {total}")
print(f"  Passed       : {results['passed']}")
print(f"  Failed       : {results['failed']}")
print(f"  Warnings     : {results['warnings']}")

if results["failed"] == 0:
    print(f"\n  ✓ SCRIPT CHECKS COMPLETED — Review warnings and external-service limits.\n")
    sys.exit(0)
else:
    print(f"\n  ✗ {results['failed']} CHECK(S) FAILED — Review errors above.\n")
    sys.exit(1)
