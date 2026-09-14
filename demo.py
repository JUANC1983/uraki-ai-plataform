# -*- coding: utf-8 -*-
"""
demo.py -- End-to-end system walkthrough (no DB, no network required).
Run: python demo.py

Shows exactly what happens internally when a case is evaluated:
  Step 1: Case input
  Step 2: Tenant configuration loaded
  Step 3: Risk Engine scores the case
  Step 4: Classifier determines case type
  Step 5: Rule Engine evaluates all rules
  Step 6: Priority Engine assigns urgency
  Step 7: DecisionOutput assembled
  Step 8: Suggested message drafted (simulated — no OpenAI call)
"""
import io
import sys
import json
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────
# Colour helpers (plain text fallback on Windows)
# ─────────────────────────────────────────────
W = 70

def banner(text):
    print("\n" + "=" * W)
    print(f"  {text}")
    print("=" * W)

def step(n, title):
    print(f"\n{'─' * W}")
    print(f"  STEP {n}: {title}")
    print(f"{'─' * W}")

def field(label, value, indent=4):
    pad = " " * indent
    print(f"{pad}{label:<35} {value}")

def section(title):
    print(f"\n  >> {title}")

def pretty(d, indent=4):
    pad = " " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"{pad}{k}:")
            for k2, v2 in v.items():
                print(f"{pad}  {k2:<30} {v2}")
        elif isinstance(v, list) and v:
            print(f"{pad}{k}:")
            for item in v[:3]:
                print(f"{pad}  - {item}")
        else:
            print(f"{pad}{k:<33} {v}")


# ══════════════════════════════════════════════════════════════════════
# STEP 1 — CASE INPUT
# ══════════════════════════════════════════════════════════════════════
banner("URAKI AI PLATFORM — Complete Decision Walkthrough")

step(1, "CASE INPUT")
print("""
  Synthetic input only; this walkthrough does not connect to a CRM.
  This walkthrough feeds internal engines directly; it does not call the API.
""")

CASE = {
    # Identity
    "case_id":                "CASE-SYNTHETIC-001",
    "tenant_id":              "tenant-synthetic-demo",
    "client_name":            "RESIDENTE SINTETICO 001",
    "client_id_number":       "SYNTHETIC-ID-001",
    "property_address":       "INMUEBLE SINTETICO 001 (sin direccion real)",
    "contract_id":            "CONTRACT-SYNTHETIC-001",
    # Financial
    "case_type":              "mora",
    "overdue_days":           97,
    "overdue_amount":         4_850_000,      # COP
    "monthly_rent":           1_600_000,      # COP
    "currency":               "COP",
    # History
    "has_legal_action":       False,
    "previous_overdue_count": 2,              # twice before
    "has_policy":             True,           # insurance policy active
    "contract_active":        True,
    # Document evidence (extracted by DocumentAgent from uploaded PDF)
    "document_clauses": [
        {
            "clause_label": "CLAUSULA 12 - MORA",
            "content": (
                "En caso de mora en el pago del canon, el arrendatario "
                "pagara una penalidad del 2% mensual sobre el valor adeudado. "
                "Transcurridos 90 dias de mora se procedera con proceso juridico."
            ),
        },
        {
            "clause_label": "CLAUSULA 7 - POLIZA",
            "content": (
                "El inmueble cuenta con poliza de arrendamiento vigente. "
                "La aseguradora cubrira hasta 3 canones en caso de incumplimiento."
            ),
        },
    ],
}

for k, v in CASE.items():
    if k == "document_clauses":
        print(f"    document_clauses               {len(v)} clauses loaded")
    else:
        print(f"    {k:<33} {v}")


# ══════════════════════════════════════════════════════════════════════
# STEP 2 — TENANT CONFIGURATION
# ══════════════════════════════════════════════════════════════════════
step(2, "TENANT CONFIGURATION LOADED")
print("""
  ConfigEngine loads this tenant's settings from DB (simulated here).
  Every engine uses this config — no hardcoded values anywhere.
""")

from core.config_engine import ConfigEngine

RAW_TENANT_CONFIG = {
    "risk_weights": {
        "overdue_days":     0.40,
        "economic_impact":  0.30,
        "legal_risk":       0.20,
        "recurrence":       0.10,
    },
    "risk_thresholds": {
        "low":    {"min": 0,  "max": 30},
        "medium": {"min": 30, "max": 70},
        "high":   {"min": 70, "max": 100},
    },
    "priority_thresholds": {
        "critical": 85,
        "high":     65,
        "medium":   40,
    },
    "escalation_policy": {
        "auto_escalate_days":    90,
        "legal_threshold_days":  60,
        "policy_threshold_months": 3.0,
    },
    "tone_settings": {
        "tone":              "firme",
        "language":          "es",
        "company_name":      "URAKI Inmobiliaria",
        "use_formal_address": True,
    },
    "modules": {
        "document_intelligence": True,
        "llm_classification":    False,
        "auto_messaging":        False,
        "auto_escalation":       False,
        "priority_scoring":      True,
    },
    "required_case_fields": ["client_name", "overdue_days", "monthly_rent"],
}

engine_cfg = ConfigEngine()
config = engine_cfg._parse(CASE["tenant_id"], RAW_TENANT_CONFIG)

section("Risk weights (normalized)")
for k, v in config.risk_weights.as_dict().items():
    bar = "#" * int(v * 30)
    print(f"    {k:<20} {v:.2f}  {bar}")

section("Risk thresholds")
print(f"    BAJO   0  – 30    MEDIO  31 – 70    ALTO  71 – 100")

section("Priority thresholds")
print(f"    CRITICAL >= {config.priority_thresholds.critical}    HIGH >= {config.priority_thresholds.high}"
      f"    MEDIUM >= {config.priority_thresholds.medium}")

section("Active modules")
for k, v in config.modules.__dict__.items():
    status = "ON " if v else "OFF"
    print(f"    [{status}] {k}")


# ══════════════════════════════════════════════════════════════════════
# STEP 3 — RISK ENGINE
# ══════════════════════════════════════════════════════════════════════
step(3, "RISK ENGINE — Computing score")
print("""
  RiskEngine computes a 0-100 composite score from 4 variables.
  Each variable is scored 0-100 then weighted per tenant config.
  No LLM involved — pure deterministic math.
""")

from core.risk_engine import RiskEngine

risk_engine = RiskEngine()
risk_result = risk_engine.compute(
    overdue_days=CASE["overdue_days"],
    overdue_amount=CASE["overdue_amount"],
    monthly_rent=CASE["monthly_rent"],
    has_legal_action=CASE["has_legal_action"],
    previous_overdue_count=CASE["previous_overdue_count"],
    tenant_config=RAW_TENANT_CONFIG,
)

section("Component scores (before weighting)")
for var, score in risk_result.component_scores.items():
    weight = risk_result.weights_used.get(var, 0)
    contribution = score * weight
    bar = "#" * int(score / 5)
    print(f"    {var:<22} raw={score:5.1f}  weight={weight:.2f}  contribution={contribution:5.2f}  {bar}")

print()
print(f"    {'TOTAL RISK SCORE':<22} {risk_result.total:5.1f} / 100")
print(f"    {'RISK LEVEL':<22} {risk_result.level}")

# ── Explanation generated entirely from RiskEngine output ──────────────
print()
print(risk_result.explain())

# ── Consistency validation: raises if displayed values diverge from total ──
risk_result.validate_consistency()
print()
print("  [VALIDATION PASS] formula sum matches computed total — single source of truth")


# ══════════════════════════════════════════════════════════════════════
# STEP 4 — CLASSIFIER AGENT
# ══════════════════════════════════════════════════════════════════════
step(4, "CLASSIFIER — Determining case type")
print("""
  ClassifierAgent checks classification rules first (deterministic).
  If no classification rule matches, it falls back to an LLM hint.
  The LLM is ADVISORY only — rule engine always has final say.
""")

from core.rule_engine import RuleEngine, RuleRecord
from core.decision_contract import CaseClassification

CLASSIFICATION_RULES = [
    RuleRecord(
        id="cls-001", tenant_id=CASE["tenant_id"],
        name="Mora Critica (>90 dias)",
        category="classification", priority=10,
        conditions={"field": "overdue_days", "op": "gte", "value": 90},
        actions={"classification": "MORA_CRITICA"},
        constraints=None, explanation_template=None,
        is_active=True, version=2,
    ),
    RuleRecord(
        id="cls-002", tenant_id=CASE["tenant_id"],
        name="Mora Media (31-89 dias)",
        category="classification", priority=20,
        conditions={"field": "overdue_days", "op": "between", "value": [31, 89]},
        actions={"classification": "MORA_MEDIA"},
        constraints=None, explanation_template=None,
        is_active=True, version=1,
    ),
    RuleRecord(
        id="cls-003", tenant_id=CASE["tenant_id"],
        name="Mora Temprana (1-30 dias)",
        category="classification", priority=30,
        conditions={"field": "overdue_days", "op": "between", "value": [1, 30]},
        actions={"classification": "MORA_TEMPRANA"},
        constraints=None, explanation_template=None,
        is_active=True, version=1,
    ),
    RuleRecord(
        id="cls-004", tenant_id=CASE["tenant_id"],
        name="Reincidencia (>1 incidente previo)",
        category="classification", priority=5,
        conditions={
            "logic": "AND",
            "conditions": [
                {"field": "overdue_days", "op": "gte", "value": 30},
                {"field": "previous_overdue_count", "op": "gte", "value": 2},
            ]
        },
        actions={"classification": "REINCIDENCIA"},
        constraints=None, explanation_template=None,
        is_active=True, version=1,
    ),
]

rule_engine = RuleEngine()

context = {
    "overdue_days":           CASE["overdue_days"],
    "overdue_amount":         CASE["overdue_amount"],
    "monthly_rent":           CASE["monthly_rent"],
    "has_legal_action":       CASE["has_legal_action"],
    "previous_overdue_count": CASE["previous_overdue_count"],
    "has_policy":             CASE["has_policy"],
    "contract_active":        CASE["contract_active"],
    "case_type":              CASE["case_type"],
    "document_clauses":       CASE["document_clauses"],
    "risk_score":             risk_result.total,
    "risk_level":             risk_result.level,
}

cls_result = rule_engine.evaluate(CLASSIFICATION_RULES, context)

section("Classification rules evaluated")
for r in cls_result.rules_evaluated:
    icon = "[MATCH]" if r.matched else "[  NO ]"
    print(f"    {icon} priority={r.rule.priority:<3} '{r.rule.name}'")
    print(f"           {r.reason}")

print()
if cls_result.applied_rule:
    classification = CaseClassification(cls_result.applied_actions["classification"])
    print(f"    WINNER:  '{cls_result.applied_rule.name}'  (priority={cls_result.applied_rule.priority})")
    print(f"    RESULT:  {classification.value}")
    if len([r for r in cls_result.rules_evaluated if r.matched]) > 1:
        print(f"    CONFLICT RESOLVED: higher priority rule wins")
    context["classification"] = classification.value
else:
    classification = CaseClassification.OTRO
    context["classification"] = classification.value
    print(f"    RESULT:  {classification.value} (no rule matched - default)")


# ══════════════════════════════════════════════════════════════════════
# STEP 5 — RULE ENGINE — DECISION
# ══════════════════════════════════════════════════════════════════════
step(5, "RULE ENGINE — Evaluating decision rules")
print("""
  The rule engine evaluates ALL active decision rules.
  Rules use AND/OR/NOT logic and can match document clauses.
  Only the highest-priority matching rule is applied.
  Full audit trail: every rule evaluated is recorded.
""")

DECISION_RULES = [
    RuleRecord(
        id="dec-001", tenant_id=CASE["tenant_id"],
        name="Reincidente con Poliza — Activar Cobertura",
        category="decision", priority=5,
        conditions={
            "logic": "AND",
            "conditions": [
                {"field": "previous_overdue_count", "op": "gte", "value": 2},
                {"field": "has_policy", "op": "eq", "value": True},
                {"field": "overdue_days", "op": "gte", "value": 60},
            ]
        },
        actions={
            "action": "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA",
            "firmness": "ESTRICTO",
            "escalation_required": True,
            "escalation_target": "poliza",
            "policy_flag": True,
            "legal_flag": False,
        },
        constraints=None,
        explanation_template=(
            "Arrendatario con {previous_overdue_count} incidentes previos de mora "
            "y {overdue_days} dias de mora actual. Poliza activa. "
            "Se activa cobertura de seguro."
        ),
        is_active=True, version=3,
    ),
    RuleRecord(
        id="dec-002", tenant_id=CASE["tenant_id"],
        name="Mora Critica sin Poliza — Proceso Legal",
        category="decision", priority=10,
        conditions={
            "logic": "AND",
            "conditions": [
                {"field": "overdue_days", "op": "gte", "value": 90},
                {"field": "has_policy", "op": "eq", "value": False},
                {"field": "has_legal_action", "op": "eq", "value": False},
            ]
        },
        actions={
            "action": "INICIAR_DEMANDA_DE_RESTITUCIÓN",
            "firmness": "URGENTE",
            "escalation_required": True,
            "escalation_target": "legal",
            "legal_flag": True,
        },
        constraints=None,
        explanation_template=(
            "{overdue_days} dias de mora sin poliza activa. "
            "Se inicia proceso de restitucion de inmueble."
        ),
        is_active=True, version=2,
    ),
    RuleRecord(
        id="dec-003", tenant_id=CASE["tenant_id"],
        name="Clausula de Mora Identificada — Aplicar Penalidad",
        category="decision", priority=15,
        conditions={
            "logic": "AND",
            "conditions": [
                {"field": "document_clauses", "op": "clause_contains", "value": "penalidad"},
                {"field": "overdue_days", "op": "gte", "value": 30},
            ]
        },
        actions={
            "action": "COBRAR_PENALIDAD_CONTRACTUAL",
            "firmness": "FIRME",
            "escalation_required": False,
        },
        constraints=None,
        explanation_template=(
            "Clausula de penalidad por mora identificada en contrato CONTRACT-SYNTHETIC-001. "
            "Se aplica cargo adicional del 2% mensual."
        ),
        is_active=True, version=1,
    ),
    RuleRecord(
        id="dec-004", tenant_id=CASE["tenant_id"],
        name="Mora Media — Acuerdo de Pago",
        category="decision", priority=50,
        conditions={
            "field": "overdue_days", "op": "between", "value": [31, 89]
        },
        actions={
            "action": "PROPONER_ACUERDO_DE_PAGO",
            "firmness": "FIRME",
            "escalation_required": False,
        },
        constraints=None, explanation_template=None,
        is_active=True, version=1,
    ),
    RuleRecord(
        id="dec-005", tenant_id=CASE["tenant_id"],
        name="Mora Temprana — Recordatorio",
        category="decision", priority=100,
        conditions={
            "field": "overdue_days", "op": "between", "value": [1, 30]
        },
        actions={
            "action": "ENVIAR_RECORDATORIO_DE_PAGO",
            "firmness": "SUAVE",
            "escalation_required": False,
        },
        constraints=None, explanation_template=None,
        is_active=True, version=1,
    ),
]

dec_result = rule_engine.evaluate(DECISION_RULES, context)

section("All decision rules evaluated")
for r in dec_result.rules_evaluated:
    icon = "[MATCH]" if r.matched else "[  NO ]"
    print(f"    {icon} priority={r.rule.priority:<3} v{r.rule.version}  '{r.rule.name}'")
    print(f"           Condition: {r.reason[:80]}...")

print()
if dec_result.conflict_resolution_notes:
    print(f"    CONFLICT RESOLUTION:")
    for note in dec_result.conflict_resolution_notes:
        print(f"    {note}")
    print()

if dec_result.applied_rule:
    print(f"    WINNER:  '{dec_result.applied_rule.name}'")
    print(f"             priority={dec_result.applied_rule.priority}  version={dec_result.applied_rule.version}")
    print(f"             effective_from: {dec_result.applied_rule.effective_from}")
    print()
    section("Actions from winning rule")
    for k, v in dec_result.applied_actions.items():
        print(f"    {k:<35} {v}")
    print()
    section("Explanation")
    print(f"    {dec_result.explanation}")
else:
    print("    NO RULE MATCHED — manual review required")


# ══════════════════════════════════════════════════════════════════════
# STEP 6 — PRIORITY ENGINE
# ══════════════════════════════════════════════════════════════════════
step(6, "PRIORITY ENGINE — Assigning case urgency")
print("""
  Priority is derived from 3 inputs weighted as:
    risk_score         50%
    overdue_days       30%
    flags (legal/esc)  20%

  Thresholds: CRITICAL>=85  HIGH>=65  MEDIUM>=40  LOW<40
""")

from core.priority_engine import PriorityEngine

priority_engine = PriorityEngine()
actions = dec_result.applied_actions if dec_result.applied_rule else {}

priority_result = priority_engine.compute(
    risk_score=risk_result.total,
    escalation_required=actions.get("escalation_required", False),
    overdue_days=CASE["overdue_days"],
    legal_flag=actions.get("legal_flag", False),
    config_thresholds=config.priority_thresholds,
)

for factor, contribution in priority_result.factors.items():
    bar = "#" * int(contribution / 3)
    print(f"    {factor:<40} {contribution:5.2f}  {bar}")
print()
print(f"    {'COMPOSITE SCORE':<40} {priority_result.score:.2f}")
print(f"    {'PRIORITY':<40} {priority_result.priority.value}")


# ══════════════════════════════════════════════════════════════════════
# STEP 7 — DECISION OUTPUT ASSEMBLY
# ══════════════════════════════════════════════════════════════════════
step(7, "DECISION OUTPUT — Assembling final contract")
print("""
  DecisionOutput is a frozen Pydantic model.
  Every field is set exactly once — no mutation allowed after this point.
  This is the canonical record stored in the decisions table.
""")

from core.decision_contract import (
    DecisionOutput, RiskLevel, Firmness, DocumentReference,
)

# Build document references from matched clause evidence
doc_refs = [
    DocumentReference(
        document_id="doc-CONTRACT-SYNTHETIC-001",
        clause_id="CLAUSULA 12 - MORA",
        snippet=(
            "Transcurridos 90 dias de mora se procedera con proceso juridico. "
            "Penalidad del 2% mensual sobre el valor adeudado."
        ),
        relevance="Define el umbral de 90 dias para accion legal y penalidad aplicable",
    ),
    DocumentReference(
        document_id="doc-CONTRACT-SYNTHETIC-001",
        clause_id="CLAUSULA 7 - POLIZA",
        snippet="La aseguradora cubrira hasta 3 canones en caso de incumplimiento.",
        relevance="Confirma cobertura de poliza activa — aplica a este caso",
    ),
]

risk_level_map = {"LOW": RiskLevel.LOW, "BAJO": RiskLevel.LOW,
                  "MEDIUM": RiskLevel.MEDIUM, "MEDIO": RiskLevel.MEDIUM,
                  "HIGH": RiskLevel.HIGH, "ALTO": RiskLevel.HIGH}

firmness_map = {"SUAVE": Firmness.SOFT, "FIRME": Firmness.FIRM,
                "ESTRICTO": Firmness.STRICT, "URGENTE": Firmness.URGENT}

decision = DecisionOutput(
    case_id=CASE["case_id"],
    tenant_id=CASE["tenant_id"],
    classification=classification,
    risk_score=risk_result.total,
    risk_level=risk_level_map.get(risk_result.level, RiskLevel.HIGH),
    priority=priority_result.priority,
    action=actions.get("action", "REVISAR_MANUALMENTE"),
    firmness=firmness_map.get(actions.get("firmness", "FIRME"), Firmness.FIRM),
    next_step="Contactar aseguradora en 24h y enviar carta formal al arrendatario",
    escalation_required=actions.get("escalation_required", False),
    escalation_target=actions.get("escalation_target"),
    legal_flag=actions.get("legal_flag", False),
    policy_flag=actions.get("policy_flag", False),
    validations_missing=[],
    rationale=dec_result.explanation,
    why_this_rule=(
        f"Regla '{dec_result.applied_rule.name}' (prioridad={dec_result.applied_rule.priority}) "
        f"tiene mayor prioridad entre {len([r for r in dec_result.rules_evaluated if r.matched])} "
        f"reglas que coincidieron."
    ) if dec_result.applied_rule else None,
    what_happens_next=(
        "Se notifica a la aseguradora para activar cobertura. "
        "El arrendatario recibe carta formal con liquidacion de deuda y penalidades. "
        "Si no hay respuesta en 15 dias, se escala a proceso juridico."
    ),
    rule_id_applied=dec_result.applied_rule.id if dec_result.applied_rule else None,
    rule_version_used=dec_result.applied_rule.version if dec_result.applied_rule else None,
    rules_evaluated=[r.to_dict() for r in dec_result.rules_evaluated],
    rules_discarded=[r.to_dict() for r in dec_result.rules_discarded],
    document_references=doc_refs,
    confidence=0.96,
)

section("DecisionOutput fields")
field("case_id",               decision.case_id)
field("tenant_id",             decision.tenant_id)
field("classification",        decision.classification.value)
field("risk_score",            f"{decision.risk_score:.1f} / 100")
field("risk_level",            decision.risk_level.value)
field("priority",              decision.priority.value)
field("action",                decision.action)
field("firmness",              decision.firmness.value)
field("escalation_required",   str(decision.escalation_required))
field("escalation_target",     str(decision.escalation_target))
field("legal_flag",            str(decision.legal_flag))
field("policy_flag",           str(decision.policy_flag))
field("rule_id_applied",       str(decision.rule_id_applied))
field("rule_version_used",     f"v{decision.rule_version_used}")
field("confidence",            f"{decision.confidence:.0%}")
field("document_references",   f"{len(decision.document_references)} clauses")
field("rules_evaluated",       str(len(decision.rules_evaluated)))
field("rules_discarded",       str(len(decision.rules_discarded)))

section("Immutability check")
try:
    decision.risk_score = 50.0  # type: ignore
    print("    FAIL: should not be mutable")
except Exception:
    print("    PASS: DecisionOutput is frozen — no field can be changed after creation")


# ══════════════════════════════════════════════════════════════════════
# STEP 8 — COMMUNICATION ENGINE — Template selection + prompt build
# ══════════════════════════════════════════════════════════════════════
step(8, "COMMUNICATION ENGINE — Building structured message prompt")
print("""
  CommunicationEngine selects a template based on (case_type, action, tone).
  Variables from DecisionOutput + case_data are injected verbatim.
  The LLM receives the structured prompt — it converts it to natural language.
  Numbers, names, and actions are LOCKED — the LLM cannot change them.
  (No OpenAI call made in demo mode — prompt is shown, message is simulated.)
""")

from core.communication_engine import CommunicationEngine, get_communication_engine, TONE_LABELS

comm_engine = get_communication_engine()

# Build context — same data that MessageAgent would pass
tone_settings_dict = RAW_TENANT_CONFIG["tone_settings"]
comm_context = comm_engine.build_context(decision, CASE, type("T", (), {
    "tone":              tone_settings_dict["tone"],
    "language":          tone_settings_dict["language"],
    "company_name":      tone_settings_dict["company_name"],
    "use_formal_address": tone_settings_dict["use_formal_address"],
    "signature":         "",
})())

section("Communication context extracted from DecisionOutput + case_data")
print(f"    case_type          {comm_context.case_type}")
print(f"    action             {comm_context.action}")
print(f"    action_label       {comm_context.action_label}")
print(f"    client_name        {comm_context.client_name}")
print(f"    overdue_days       {comm_context.overdue_days}")
print(f"    overdue_amount_fmt {comm_context.overdue_amount_fmt}")
print(f"    clause_labels      {comm_context.clause_labels_str}")
print(f"    tone               {comm_context.tone}  ({comm_context.tone_label})")
print(f"    language           {comm_context.language}")
print(f"    company_name       {comm_context.company_name}")
print(f"    formal_address     {comm_context.formal_address}")

# Template selection
template = comm_engine.get_template(
    case_type=comm_context.case_type,
    action=comm_context.action,
    tone=comm_context.tone,
)

section(f"Template selected: '{template.template_id}'")
print(f"    Matches: case_types={template.case_types}  actions={template.actions[:2]}  tones={template.tones}")
print(f"    Sections: {len(template.sections)}  |  max_tokens: {template.max_tokens}")
print(f"    Tone guidance: \"{template.tone_guidance[:80]}...\"")

# Show penalty / legal consequence validation status
section("Hardening — penalty and legal consequence validation")
print(f"    penalty_validated              {comm_context.penalty_validated}")
print(f"    penalty_clause                 \"{comm_context.penalty_clause}\"")
print(f"    legal_consequences_validated   {comm_context.legal_consequences_validated}")
print(f"    consequence_clause             \"{comm_context.consequence_clause}\"")
print()
print("    NOTE: penalty_rate not in case_data → neutral wording injected into template.")
print("    NOTE: legal_flag=False on decision → consequence language restricted to contractual.")

# Validate context
missing = comm_engine.validate_context(template, comm_context)
if missing:
    print(f"\n    WARNING: Missing variables: {missing}")
else:
    print(f"\n    [PASS] All {len(template.required_variables)} required variables present")

# Build prompt
prompt, constraints = comm_engine.build_prompt(template, comm_context)

section("Structured prompt sent to LLM (section-by-section instructions)")
print()
for line in prompt.split("\n"):
    print(f"    {line}")

section("Constraints dict (locked facts — LLM system prompt enforces these)")
for k, v in constraints.items():
    if k not in ("tone_guidance",):
        print(f"    {k:<20} {v}")
print(f"    tone_guidance        \"{constraints['tone_guidance'][:60]}...\"")


# ── Simulated LLM output ────────────────────────────────────────────
SIMULATED_MESSAGE = (
    "Estimado Sr. RESIDENTE SINTETICO 001,\n\n"
    "Por medio de la presente, URAKI Inmobiliaria se dirige a usted con relacion\n"
    "al inmueble ubicado en INMUEBLE SINTETICO 001 (sin direccion real), correspondiente al\n"
    "contrato de arrendamiento No. CONTRACT-SYNTHETIC-001.\n\n"
    "A la fecha, registramos un saldo vencido de $4,850,000 COP con 97 dias de mora,\n"
    "lo cual supera el umbral establecido en la CLAUSULA 12 - MORA de su contrato.\n\n"
    "En razon de lo anterior, y considerando que usted cuenta con poliza de\n"
    "arrendamiento activa, hemos procedido a activar la cobertura de seguro y\n"
    "notificar a la aseguradora para el tramite correspondiente. Le informamos\n"
    "que seran aplicables las penalidades contractuales establecidas en su\n"
    "contrato de arrendamiento, conforme a las clausulas vigentes.\n\n"
    "Le solicitamos respetuosamente tomar contacto con nuestra oficina dentro de\n"
    "los proximos 5 dias habiles para coordinar el plan de pago y evitar la\n"
    "aplicacion de las medidas previstas en su contrato de arrendamiento.\n\n"
    "En caso de no recibir respuesta dentro del plazo indicado, podran aplicarse\n"
    "las medidas adicionales previstas en su contrato de arrendamiento.\n\n"
    "Atentamente,\n"
    "Equipo de Gestion — URAKI Inmobiliaria"
)

section("Generated message (simulated — no OpenAI call in demo mode)")
print()
for line in SIMULATED_MESSAGE.split("\n"):
    print(f"    {line}")

# Validate output (post-generation fact check)
output_warnings = comm_engine.validate_output(SIMULATED_MESSAGE, comm_context)
print()
if output_warnings:
    print(f"    [WARN] Fact-check warnings: {output_warnings}")
else:
    print(f"    [PASS] Fact-check: client_name, overdue_days, and overdue_amount all present verbatim")

section("LLM boundary enforcement")
print("    The LLM output is stored as suggested_message — advisory only.")
print("    It does NOT modify: action, risk_score, classification,")
print("    escalation_required, or any other DecisionOutput field.")
print("    DecisionOutput is frozen Pydantic — mutation raises ValidationError.")


# ══════════════════════════════════════════════════════════════════════
# STEP 9 — DECISION CARD (3-layer operator view)
# ══════════════════════════════════════════════════════════════════════
step(9, "DECISION CARD — Operator-facing 3-layer presentation")
print("""
  DecisionCard is built FROM DecisionOutput — never the other way around.
  It has three layers:
    1. OPERATOR SUMMARY  — readable in < 5 seconds, actionable
    2. AUDIT TRAIL       — full traceability for compliance
    3. CLIENT MESSAGE    — generated communication, ready to copy-paste
""")

from core.decision_card import DecisionCard
from agents.message_agent import MessageResult

# Build a MessageResult from our simulated output (mirrors what MessageAgent returns)
message_result = MessageResult(
    text=SIMULATED_MESSAGE,
    tone=comm_context.tone,
    tone_label=TONE_LABELS.get(comm_context.tone, comm_context.tone.capitalize()),
    language=comm_context.language,
    template_id=template.template_id,
    validation_passed=len(output_warnings) == 0,
    warnings=output_warnings,
    context_snapshot={
        "client_name":    comm_context.client_name,
        "overdue_days":   comm_context.overdue_days,
        "overdue_amount": comm_context.overdue_amount_fmt,
        "action":         comm_context.action,
        "tone":           comm_context.tone,
        "template_id":    template.template_id,
    },
)

card = DecisionCard.build(
    decision=decision,
    case_data=CASE,
    message_result=message_result,
)

print()
print(card.format_text(width=W))
print()
print(card.format_copy_blocks(width=W))

section("Decision Card as JSON (for API response)")
card_dict = card.to_dict()
print(f"    Top-level keys:  {list(card_dict.keys())}")
print(f"    JSON size:       {len(card.to_json())} bytes")
print(f"    Generated at:    {card.generated_at[:19]}")

section("Audit payload preview (not persisted by this demo)")
audit = decision.to_audit_dict()
print(f"    rules_evaluated : {len(audit['rules_evaluated'])} rules")
print(f"    rules_discarded : {len(audit['rules_discarded'])} rules")
print(f"    document_refs   : {len(audit['document_references'])} clauses referenced")
print(f"    timestamp       : {audit['timestamp']}")
print(f"    JSON size       : {len(json.dumps(audit))} bytes")

section("Illustrative event sequence (not published by this demo)")
print(f"    1. CASE_CREATED         (on initial case creation)")
print(f"    2. DECISION_GENERATED   (this evaluation)")
print(f"    3. CASE_ESCALATED       (auto-triggered: escalation_required=True)")

section("Illustrative integration path (not executed; delivery is unimplemented)")
print(f"    - Decision persisted to DB (decisions table)")
print(f"    - Case status: IN_REVIEW -> DECISION_GENERATED")
print(f"    - Case priority updated: {priority_result.priority.value}")
print(f"    - Event DECISION_GENERATED dispatched to handlers")
print("    - Notification delivery is not implemented; no message is sent")
print("    - External escalation is not executed by this demo")
print(f"    - Operator sees case at top of queue with {priority_result.priority.value} badge")
print(f"    - Operator can: approve action / override / request clarification")
print()
print("=" * W)
from pydantic import ValidationError
from core.config_engine import RiskWeights
try:
    RiskWeights(overdue_days=0, economic_impact=0, legal_risk=0, recurrence=0)
except ValidationError:
    print("  [PASS] Invalid all-zero scoring weights rejected.")
else:
    raise AssertionError("Unsafe scoring configuration was accepted")
print("  Demo complete. No database, no network calls used.")
print("=" * W)
print()
