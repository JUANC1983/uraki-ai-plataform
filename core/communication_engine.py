# core/communication_engine.py
"""
Communication Engine — structured template system for client messages.

Design contract:
  - Templates define STRUCTURE (sections + instructions), never full text.
  - Variables are injected from DecisionOutput + case_data before the LLM sees them.
  - The LLM converts structured content into natural language.
  - The LLM CANNOT change numbers, actions, names, or decisions.
  - Output is validated against source values before being returned.

Public API:
    engine = CommunicationEngine()
    context = engine.build_context(decision, case_data, tone_settings)
    template = engine.get_template(case_type, action, tone)
    prompt   = engine.build_prompt(template, context)
    # → prompt is passed to LLMConnector.draft_from_template()

Template lookup priority:
    (case_type, action, tone)
    → (*, action, tone)
    → (case_type, action, *)
    → (*, action, *)
    → (*, *, tone)
    → default
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action labels (Spanish — shown in operator card and template)
# ---------------------------------------------------------------------------

ACTION_LABELS: dict[str, str] = {
    "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA": "Activar póliza y notificar aseguradora",
    "INICIAR_DEMANDA_DE_RESTITUCIÓN":          "Iniciar proceso de restitución del inmueble",
    "PROPONER_ACUERDO_DE_PAGO":                "Proponer acuerdo de pago",
    "COBRAR_PENALIDAD_CONTRACTUAL":            "Cobrar penalidad contractual",
    "ENVIAR_RECORDATORIO_DE_PAGO":             "Enviar recordatorio de pago",
    "REVISAR_MANUALMENTE":                     "Revisar caso manualmente",
}

TONE_LABELS: dict[str, str] = {
    "amable":      "Amable / comprensivo",
    "consultivo":  "Consultivo / explicativo",
    "firme":       "Firme / profesional",
    "legal":       "Legal / formal",
    "estricto":    "Estricto / aviso final",
    "profesional": "Profesional",
    "urgente":     "Urgente",
}


# ---------------------------------------------------------------------------
# Template data structures
# ---------------------------------------------------------------------------

@dataclass
class MessageSection:
    """One section of a communication message."""
    label: str           # e.g. "SALUDO"
    instructions: str    # what the LLM should write — uses {variable} placeholders
    required: bool = True


@dataclass
class MessageTemplate:
    """
    Defines the structure of a message for a given context.
    Templates define sections, not full text.
    The LLM converts the structure into natural language.
    """
    template_id: str
    case_types: list[str]    # ["mora", "*"] — "*" means any
    actions: list[str]       # ["ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA", "*"]
    tones: list[str]         # ["firme", "*"]
    language: str            # "es"
    sections: list[MessageSection]
    tone_guidance: str       # extra instruction about voice/register for this tone
    required_variables: list[str]   # must all be present in context before calling LLM
    max_tokens: int = 600


# ---------------------------------------------------------------------------
# Communication context — all variables available for injection
# ---------------------------------------------------------------------------

class MissingVariableError(ValueError):
    """Raised when required template variables are absent from the context."""


@dataclass
class CommunicationContext:
    """
    All variables available for message generation.
    Built from DecisionOutput + case_data + ToneSettings.
    Validated against template.required_variables before calling the LLM.
    """
    # Case identity
    case_id: str
    case_type: str

    # Client / property
    client_name: str
    client_id: str
    property_address: str
    contract_id: str

    # Financial (pre-formatted for injection — LLM must not reformat)
    overdue_days: int
    overdue_amount: float
    monthly_rent: float
    currency: str
    overdue_amount_fmt: str    # e.g. "$4,850,000 COP"
    monthly_rent_fmt: str      # e.g. "$1,600,000 COP"

    # Decision fields
    action: str
    action_label: str           # human-readable Spanish label
    classification: str
    risk_level: str
    risk_score: float
    firmness: str
    rationale: str
    escalation_required: bool
    escalation_target: Optional[str]
    legal_flag: bool
    policy_flag: bool

    # Document evidence
    document_clauses: list[str]   # ["CLAUSULA 12 - MORA", "CLAUSULA 7 - POLIZA"]
    clause_labels_str: str        # comma-joined for injection

    # Communication config
    company_name: str
    tone: str
    tone_label: str
    language: str
    formal_address: bool          # True → "usted", False → "tú"
    signature: str

    # Validated penalty / legal consequence data
    # These are ONLY set when explicitly present in case_data — never inferred from clause text.
    penalty_rate: Optional[float]        # e.g. 0.02 — set only if case_data["penalty_rate"] exists
    penalty_validated: bool              # True only when penalty_rate is explicitly provided
    penalty_clause: str                  # injection-ready: exact rate or neutral contractual wording
    legal_consequences_validated: bool   # True only when legal_flag=True on the decision
    consequence_clause: str              # injection-ready: legal language or neutral fallback

    def as_format_dict(self) -> dict[str, Any]:
        """Returns a flat dict for .format() substitution in section instructions."""
        return {
            "case_id":            self.case_id,
            "case_type":          self.case_type,
            "client_name":        self.client_name,
            "client_id":          self.client_id,
            "property_address":   self.property_address,
            "contract_id":        self.contract_id,
            "overdue_days":       self.overdue_days,
            "overdue_amount":     self.overdue_amount,
            "monthly_rent":       self.monthly_rent,
            "currency":           self.currency,
            "overdue_amount_fmt": self.overdue_amount_fmt,
            "monthly_rent_fmt":   self.monthly_rent_fmt,
            "action":             self.action,
            "action_label":       self.action_label,
            "classification":     self.classification,
            "risk_level":         self.risk_level,
            "risk_score":         f"{self.risk_score:.1f}",
            "firmness":           self.firmness,
            "rationale":          self.rationale,
            "escalation_target":  self.escalation_target or "—",
            "legal_flag":         str(self.legal_flag),
            "policy_flag":        str(self.policy_flag),
            "clause_labels":      self.clause_labels_str or "N/A",
            "company_name":       self.company_name,
            "tone":               self.tone,
            "signature":          self.signature or self.company_name,
            # Pre-resolved clauses — LLM uses these directly, cannot override them
            "penalty_clause":     self.penalty_clause,
            "consequence_clause": self.consequence_clause,
        }


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

class TemplateRegistry:
    """
    Stores and retrieves MessageTemplates.
    Lookup is most-specific-first:
      (case_type, action, tone) → (*, action, tone) → (case_type, action, *) → (*, action, *) → default
    """

    def __init__(self) -> None:
        self._templates: list[MessageTemplate] = []

    def register(self, template: MessageTemplate) -> None:
        self._templates.append(template)

    def get(
        self,
        case_type: str,
        action: str,
        tone: str,
    ) -> MessageTemplate:
        """Return best-matching template. Always returns something (fallback guaranteed)."""
        candidates = [
            (case_type, action, tone),
            ("*",        action, tone),
            (case_type,  action, "*"),
            ("*",        action, "*"),
            ("*",        "*",    tone),
            ("*",        "*",    "*"),
        ]
        for ct, ac, to in candidates:
            for t in self._templates:
                if ct in t.case_types and ac in t.actions and to in t.tones:
                    return t
        # Should never reach here if registry has a wildcard default
        raise RuntimeError(
            f"No template found for case_type={case_type!r} action={action!r} tone={tone!r}. "
            "Ensure a wildcard (*/*/*) default template is registered."
        )


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

def _build_default_registry() -> TemplateRegistry:
    registry = TemplateRegistry()

    # ── Template 1: mora + policy activation — firme / estricto ────────────
    registry.register(MessageTemplate(
        template_id="mora_poliza_firme",
        case_types=["mora", "*"],
        actions=[
            "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA",
            "COBRAR_PENALIDAD_CONTRACTUAL",
        ],
        tones=["firme", "estricto"],
        language="es",
        required_variables=[
            "client_name", "property_address", "contract_id",
            "overdue_days", "overdue_amount_fmt", "company_name",
        ],
        tone_guidance=(
            "Write in a firm, professional, and respectful tone. Use 'usted'. "
            "State facts directly. No apologies. Make deadlines explicit. "
            "Leave no ambiguity about the required action."
        ),
        sections=[
            MessageSection(
                label="SALUDO",
                instructions=(
                    "Formal greeting. Address the client as 'Estimado/a Sr./Sra. {client_name}'."
                ),
            ),
            MessageSection(
                label="REFERENCIA",
                instructions=(
                    "Identify the communication subject: property at '{property_address}', "
                    "lease contract no. {contract_id}."
                ),
            ),
            MessageSection(
                label="SITUACION",
                instructions=(
                    "State the overdue balance clearly and factually: {overdue_days} days overdue, "
                    "{overdue_amount_fmt} outstanding. "
                    "Reference the relevant contract clause(s): {clause_labels}. "
                    "Do not interpret or add context beyond these facts."
                ),
            ),
            MessageSection(
                label="ACCION_TOMADA",
                instructions=(
                    "Inform the client of the action taken: {action_label}. "
                    "If a policy is active, state that the insurer has been notified. "
                    "Regarding applicable penalties, state exactly: {penalty_clause}. "
                    "Do NOT introduce any percentage, fee amount, or penalty rate "
                    "beyond what is stated in this instruction."
                ),
            ),
            MessageSection(
                label="REQUERIMIENTO",
                instructions=(
                    "Request the client to contact {company_name} within 5 business days "
                    "to arrange payment and avoid further measures."
                ),
            ),
            MessageSection(
                label="CONSECUENCIAS",
                instructions=(
                    "State the consequence of non-compliance: {consequence_clause}. "
                    "Do NOT introduce legal proceedings, judicial processes, or restitution "
                    "language beyond what is stated in this instruction."
                ),
            ),
            MessageSection(
                label="CIERRE",
                instructions=(
                    "Professional closing signed by the management team of {company_name}."
                ),
            ),
        ],
        max_tokens=650,
    ))

    # ── Template 2: mora + legal action — legal ─────────────────────────────
    registry.register(MessageTemplate(
        template_id="mora_legal_formal",
        case_types=["mora"],
        actions=["INICIAR_DEMANDA_DE_RESTITUCIÓN"],
        tones=["legal", "estricto"],
        language="es",
        required_variables=[
            "client_name", "property_address", "contract_id",
            "overdue_days", "overdue_amount_fmt", "company_name", "clause_labels",
        ],
        tone_guidance=(
            "Write in formal legal language. Reference clauses explicitly. "
            "Use passive voice where appropriate. State legal implications clearly. "
            "Use 'usted'. Every claim must be tied to a contractual or legal basis."
        ),
        sections=[
            MessageSection(
                label="ENCABEZADO",
                instructions=(
                    "Formal legal heading. Addressee: {client_name}. "
                    "Subject: Notificación de Inicio de Proceso de Restitución."
                ),
            ),
            MessageSection(
                label="ANTECEDENTES",
                instructions=(
                    "Establish the contractual relationship: lease of property at {property_address}, "
                    "under contract {contract_id}."
                ),
            ),
            MessageSection(
                label="INCUMPLIMIENTO",
                instructions=(
                    "State the breach: {overdue_days} days of overdue rent totaling {overdue_amount_fmt}. "
                    "Cite applicable clauses: {clause_labels}."
                ),
            ),
            MessageSection(
                label="MEDIDA_LEGAL",
                instructions=(
                    "Inform that {company_name} has initiated legal restitution proceedings "
                    "as permitted by the applicable rental agreement and Colombian civil law."
                ),
            ),
            MessageSection(
                label="OPORTUNIDAD_ULTIMA",
                instructions=(
                    "Offer a final 3-business-day window to pay the full outstanding balance "
                    "plus contractual penalties before the legal process is irrevocably filed."
                ),
            ),
            MessageSection(
                label="CIERRE_LEGAL",
                instructions=(
                    "Legal closing. Signed by the legal department of {company_name}."
                ),
            ),
        ],
        max_tokens=700,
    ))

    # ── Template 3: mora + payment plan — consultivo / amable ───────────────
    registry.register(MessageTemplate(
        template_id="mora_acuerdo_amable",
        case_types=["mora"],
        actions=["PROPONER_ACUERDO_DE_PAGO"],
        tones=["amable", "consultivo", "profesional"],
        language="es",
        required_variables=[
            "client_name", "property_address", "contract_id",
            "overdue_days", "overdue_amount_fmt", "company_name",
        ],
        tone_guidance=(
            "Write warmly and constructively. Acknowledge the situation with empathy. "
            "Use 'usted'. Present a payment plan as a collaborative solution. "
            "Avoid threats. Focus on resolution and maintaining the relationship."
        ),
        sections=[
            MessageSection(
                label="SALUDO_CORDIAL",
                instructions=(
                    "Warm but professional greeting to {client_name}."
                ),
            ),
            MessageSection(
                label="SITUACION_ACTUAL",
                instructions=(
                    "Mention the outstanding balance of {overdue_amount_fmt} and {overdue_days} days "
                    "of delay, without accusatory language."
                ),
            ),
            MessageSection(
                label="PROPUESTA",
                instructions=(
                    "Propose a flexible payment plan. Invite the client to contact {company_name} "
                    "to agree on terms that work for both parties."
                ),
            ),
            MessageSection(
                label="BENEFICIOS",
                instructions=(
                    "Explain that agreeing to a plan will avoid penalties and preserve the "
                    "contractual relationship."
                ),
            ),
            MessageSection(
                label="CONTACTO",
                instructions=(
                    "Provide contact invitation. Ask client to reach out within 5 business days."
                ),
            ),
            MessageSection(
                label="CIERRE_CORDIAL",
                instructions=(
                    "Warm, professional closing from {company_name}."
                ),
            ),
        ],
        max_tokens=550,
    ))

    # ── Template 4: early reminder — amable ─────────────────────────────────
    registry.register(MessageTemplate(
        template_id="mora_recordatorio_suave",
        case_types=["mora"],
        actions=["ENVIAR_RECORDATORIO_DE_PAGO"],
        tones=["amable", "consultivo", "profesional"],
        language="es",
        required_variables=[
            "client_name", "overdue_days", "overdue_amount_fmt", "company_name",
        ],
        tone_guidance=(
            "Gentle, brief reminder. No pressure. Assume it is an oversight. "
            "Use 'usted'. Keep to 3 short paragraphs maximum."
        ),
        sections=[
            MessageSection(
                label="RECORDATORIO",
                instructions=(
                    "Friendly payment reminder to {client_name}. "
                    "Mention {overdue_amount_fmt} outstanding, {overdue_days} days past due."
                ),
            ),
            MessageSection(
                label="INSTRUCCIONES",
                instructions=(
                    "Remind payment channels and due date. Keep brief."
                ),
            ),
            MessageSection(
                label="CIERRE",
                instructions=("Short, friendly closing from {company_name}."),
            ),
        ],
        max_tokens=350,
    ))

    # ── Template 5: wildcard default ────────────────────────────────────────
    registry.register(MessageTemplate(
        template_id="default_profesional",
        case_types=["*"],
        actions=["*"],
        tones=["*"],
        language="es",
        required_variables=["client_name", "action", "company_name"],
        tone_guidance=(
            "Write in a professional, respectful tone. "
            "Use 'usted'. Be concise and factual."
        ),
        sections=[
            MessageSection(
                label="SALUDO",
                instructions="Formal greeting to {client_name}.",
            ),
            MessageSection(
                label="COMUNICADO",
                instructions=(
                    "Communicate the following action: {action_label}. "
                    "State the relevant facts from the case."
                ),
            ),
            MessageSection(
                label="REQUERIMIENTO",
                instructions=(
                    "If action is required from the client, state it clearly with a deadline."
                ),
                required=False,
            ),
            MessageSection(
                label="CIERRE",
                instructions="Professional closing from {company_name}.",
            ),
        ],
        max_tokens=500,
    ))

    return registry


# Singleton registry
_registry = _build_default_registry()


# ---------------------------------------------------------------------------
# Communication Engine
# ---------------------------------------------------------------------------

class CommunicationEngine:
    """
    Orchestrates template selection, context building, and prompt generation.

    Usage:
        engine = get_communication_engine()
        context = engine.build_context(decision, case_data, tone_settings)
        template = engine.get_template(context.case_type, context.action, context.tone)
        prompt, constraints = engine.build_prompt(template, context)
        # → pass prompt + constraints to LLMConnector.draft_from_template()
    """

    def __init__(self, registry: Optional[TemplateRegistry] = None) -> None:
        self._registry = registry or _registry

    def build_context(
        self,
        decision: Any,  # DecisionOutput — avoid circular import
        case_data: dict[str, Any],
        tone_settings: Any,  # ToneSettings or dict — handle both
    ) -> CommunicationContext:
        """
        Extract and normalize all variables needed for message generation.
        Handles both ToneSettings objects and raw dicts for backward compatibility.
        """
        # Tone settings — handle both ToneSettings object and raw dict
        if hasattr(tone_settings, "tone"):
            tone = tone_settings.tone
            language = tone_settings.language
            company_name = tone_settings.company_name
            formal_address = tone_settings.use_formal_address
            signature = getattr(tone_settings, "signature", "")
        else:
            tone = tone_settings.get("tone", "firme")
            language = tone_settings.get("language", "es")
            company_name = tone_settings.get("company_name", "")
            formal_address = tone_settings.get("use_formal_address", True)
            signature = tone_settings.get("signature", "")

        # Financial formatting
        currency = case_data.get("currency", "COP")
        overdue_amount = float(case_data.get("overdue_amount", 0))
        monthly_rent = float(case_data.get("monthly_rent", 0))
        overdue_amount_fmt = f"${overdue_amount:,.0f} {currency}"
        monthly_rent_fmt = f"${monthly_rent:,.0f} {currency}"

        # Document clauses — from case_data or decision document_references
        doc_clauses: list[str] = []
        raw_clauses = case_data.get("document_clauses", [])
        if raw_clauses:
            doc_clauses = [c.get("clause_label", "") for c in raw_clauses if c.get("clause_label")]
        if not doc_clauses and decision.document_references:
            doc_clauses = [
                ref.clause_id for ref in decision.document_references
                if ref.clause_id
            ]

        # Action label
        action = decision.action
        action_label = ACTION_LABELS.get(action, action.replace("_", " ").title())

        # ── Penalty validation ────────────────────────────────────────────────
        # A penalty rate is ONLY considered validated when case_data contains an
        # explicit numeric "penalty_rate" field.  Clause text is unstructured and
        # must NOT be parsed to extract percentages — doing so would put unvalidated
        # numbers into client communications.
        raw_penalty = case_data.get("penalty_rate")  # e.g. 0.02
        penalty_rate: Optional[float] = float(raw_penalty) if raw_penalty is not None else None
        penalty_validated = penalty_rate is not None
        if penalty_validated:
            pct = penalty_rate * 100
            pct_str = f"{pct:.0f}%" if pct == int(pct) else f"{pct:.2f}%"
            penalty_clause = (
                f"una penalidad del {pct_str} mensual sobre el saldo adeudado, "
                "segun las condiciones de su contrato"
            )
        else:
            penalty_clause = (
                "las penalidades contractuales establecidas en su contrato de arrendamiento"
            )

        # ── Legal consequence validation ──────────────────────────────────────
        # Legal consequence language (restitution, judicial process) is ONLY
        # included when the decision has legal_flag=True.  Policy-activation or
        # payment-plan actions must not imply legal proceedings.
        legal_consequences_validated = bool(decision.legal_flag)
        if legal_consequences_validated:
            consequence_clause = (
                "el incumplimiento dara lugar al inicio del proceso juridico de "
                "restitucion del inmueble conforme a la normativa civil vigente"
            )
        else:
            consequence_clause = (
                "podran aplicarse las medidas adicionales previstas en su "
                "contrato de arrendamiento"
            )

        return CommunicationContext(
            case_id=decision.case_id,
            case_type=case_data.get("case_type", "mora"),
            client_name=case_data.get("client_name", ""),
            client_id=case_data.get("client_id_number", ""),
            property_address=case_data.get("property_address", ""),
            contract_id=case_data.get("contract_id", ""),
            overdue_days=int(case_data.get("overdue_days", 0)),
            overdue_amount=overdue_amount,
            monthly_rent=monthly_rent,
            currency=currency,
            overdue_amount_fmt=overdue_amount_fmt,
            monthly_rent_fmt=monthly_rent_fmt,
            action=action,
            action_label=action_label,
            classification=decision.classification.value
                if hasattr(decision.classification, "value") else str(decision.classification),
            risk_level=decision.risk_level.value
                if hasattr(decision.risk_level, "value") else str(decision.risk_level),
            risk_score=decision.risk_score,
            firmness=decision.firmness.value
                if hasattr(decision.firmness, "value") else str(decision.firmness),
            rationale=decision.rationale,
            escalation_required=decision.escalation_required,
            escalation_target=decision.escalation_target,
            legal_flag=decision.legal_flag,
            policy_flag=decision.policy_flag,
            document_clauses=doc_clauses,
            clause_labels_str=", ".join(doc_clauses) if doc_clauses else "",
            company_name=company_name,
            tone=tone,
            tone_label=TONE_LABELS.get(tone, tone.capitalize()),
            language=language,
            formal_address=formal_address,
            signature=signature,
            penalty_rate=penalty_rate,
            penalty_validated=penalty_validated,
            penalty_clause=penalty_clause,
            legal_consequences_validated=legal_consequences_validated,
            consequence_clause=consequence_clause,
        )

    def get_template(
        self,
        case_type: str,
        action: str,
        tone: str,
    ) -> MessageTemplate:
        return self._registry.get(case_type, action, tone)

    def validate_context(
        self,
        template: MessageTemplate,
        context: CommunicationContext,
    ) -> list[str]:
        """
        Validate that all required variables are present and non-empty.
        Returns a list of missing variable names (empty = all good).
        """
        fmt = context.as_format_dict()
        missing = [
            var for var in template.required_variables
            if not fmt.get(var)
        ]
        return missing

    def build_prompt(
        self,
        template: MessageTemplate,
        context: CommunicationContext,
    ) -> tuple[str, dict[str, Any]]:
        """
        Build the structured prompt for the LLM and a constraints dict.

        Returns:
            (prompt_text, constraints)

        constraints is passed to LLMConnector so it can enforce facts in the system prompt.
        The LLM receives clear section-by-section instructions, not a blob of prose.
        """
        fmt = context.as_format_dict()

        # Resolve section instructions with variable substitution
        sections_text: list[str] = []
        for section in template.sections:
            try:
                resolved = section.instructions.format(**fmt)
            except KeyError as e:
                logger.warning("Template variable %s missing for section %s", e, section.label)
                resolved = section.instructions  # use raw if substitution fails
            sections_text.append(f"[{section.label}]\n{resolved}")

        prompt = (
            f"Write a {context.language} message with the following sections.\n"
            f"Language: {context.language.upper()}. "
            f"Tone: {context.tone_label}. "
            f"Addressee: {context.client_name}.\n\n"
            + "\n\n".join(sections_text)
        )

        # Constraints — exact values the LLM must not change
        constraints: dict[str, Any] = {
            "client_name":     context.client_name,
            "overdue_days":    context.overdue_days,
            "overdue_amount":  context.overdue_amount_fmt,
            "contract_id":     context.contract_id,
            "action":          context.action,
            "company_name":    context.company_name,
            "tone_guidance":   template.tone_guidance,
            "max_tokens":      template.max_tokens,
            "language":        context.language,
            "formal_address":  context.formal_address,
        }

        return prompt, constraints

    def validate_output(
        self,
        generated_text: str,
        context: CommunicationContext,
    ) -> list[str]:
        """
        Post-generation validation: check that key facts appear in the output
        and that no unvalidated penalty or legal language was introduced.

        Returns validation findings. String-only consumers suppress drafts with findings.
        """
        warnings: list[str] = []
        text_lower = generated_text.lower()

        # ── Presence checks ──────────────────────────────────────────────────
        # Client name: at least the first surname should appear
        name_parts = context.client_name.lower().split()
        if name_parts and not any(part in text_lower for part in name_parts if len(part) > 3):
            warnings.append(f"client_name '{context.client_name}' may be missing from output")

        # Overdue days
        if context.overdue_days > 0 and str(context.overdue_days) not in generated_text:
            warnings.append(
                f"overdue_days '{context.overdue_days}' not found verbatim in output"
            )

        # Overdue amount — check the numeric part (without currency formatting)
        amount_int = str(int(context.overdue_amount))
        if context.overdue_amount > 0 and amount_int[:4] not in generated_text.replace(",", ""):
            warnings.append(
                f"overdue_amount '{context.overdue_amount_fmt}' may be missing from output"
            )

        # ── Unvalidated penalty detection ────────────────────────────────────
        # Any percentage in the message must come from a validated penalty_rate.
        # If penalty_validated=False and a percentage appears, the LLM fabricated it.
        if not context.penalty_validated:
            pct_matches = re.findall(r'\d+[,.]?\d*\s*%', generated_text)
            if pct_matches:
                warnings.append(
                    f"HARDENING: unvalidated penalty percentage in output {pct_matches} — "
                    "set case_data['penalty_rate'] to validate, or review template instructions"
                )

        # ── Unvalidated legal consequence detection ──────────────────────────
        # Legal proceedings language must not appear unless legal_flag=True.
        if not context.legal_consequences_validated:
            legal_triggers = [
                "proceso juridico",
                "proceso judicial",
                "demanda",
                "proceso de restitucion",
                "proceso de restitución",
                "restitucion del inmueble",
                "restitución del inmueble",
                "accion legal",
                "acción legal",
                "proceso legal",
            ]
            found = [t for t in legal_triggers if t in text_lower]
            if found:
                warnings.append(
                    f"HARDENING: unvalidated legal consequence language in output {found} — "
                    "only include when decision.legal_flag=True"
                )

        return warnings


# Singleton
_engine = CommunicationEngine()


def get_communication_engine() -> CommunicationEngine:
    return _engine
