# core/decision_card.py
"""
Decision Card — structured presentation of a decision for operator workflows.

Three distinct layers, strictly separated:

  1. OPERATOR SUMMARY  — 4-5 lines, readable in < 5 seconds.
                         Actionable: what to do, who, why, next step.
  2. AUDIT TRAIL       — full traceability for compliance and review.
                         Rule used, version, risk score, document evidence.
  3. CLIENT MESSAGE    — the generated communication, ready to copy-paste.
                         Tone-appropriate, validated, factually consistent.

The card is READ-ONLY. It is built FROM DecisionOutput, not the other way around.
DecisionOutput immutability is never compromised.

Usage:
    card = DecisionCard.build(decision, case_data, message_result)
    print(card.format_text())       # plain-text for terminal / copy-paste
    api_data = card.to_dict()       # structured for API response
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Sub-sections
# ---------------------------------------------------------------------------

@dataclass
class OperatorSummary:
    """
    What the operator needs to know at a glance — decision, who, why, what next.
    All fields are short strings. No nested structures.
    """
    case_id: str
    priority: str                 # "HIGH"
    risk_level: str               # "ALTO"
    risk_score: float             # 76.0
    action: str                   # "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA"
    action_label: str             # "Activar poliza y notificar aseguradora"
    client_line: str              # "Carlos Mendoza Rios — 97 dias mora — $4,850,000 COP"
    rationale: str                # max ~120 chars — why this rule fired
    next_step: str                # max ~100 chars — first action operator must take
    escalation: Optional[str]     # "poliza" | None
    legal_alert: bool
    policy_alert: bool

    def format_text(self, width: int = 70) -> str:
        sep = "-" * width
        lines = [
            f"  RESUMEN OPERATIVO",
            f"  Caso:      {self.case_id}  |  Prioridad: {self.priority}  |  Riesgo: {self.risk_level} ({self.risk_score:.0f}/100)",
            sep,
            f"  Accion:    {self.action_label}",
            f"  Cliente:   {self.client_line}",
            f"  Por que:   {self.rationale}",
            f"  Siguiente: {self.next_step}",
        ]
        if self.escalation:
            lines.append(f"  Escalar:   {self.escalation}")
        if self.legal_alert:
            lines.append("  ALERTA:    Implicaciones legales activas")
        if self.policy_alert:
            lines.append("  POLIZA:    Cobertura de seguro aplicable")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id":      self.case_id,
            "priority":     self.priority,
            "risk_level":   self.risk_level,
            "risk_score":   self.risk_score,
            "action":       self.action,
            "action_label": self.action_label,
            "client_line":  self.client_line,
            "rationale":    self.rationale,
            "next_step":    self.next_step,
            "escalation":   self.escalation,
            "legal_alert":  self.legal_alert,
            "policy_alert": self.policy_alert,
        }


@dataclass
class AuditTrail:
    """
    Full traceability block — for compliance, review, and legal disputes.
    Every field maps to a stored value in the Decision DB record.
    """
    rule_id: Optional[str]
    rule_version: Optional[int]
    rule_name: Optional[str]      # looked up from rules_evaluated if available
    rules_evaluated: int
    rules_matched: int
    rules_discarded: int
    classification: str
    confidence: float
    document_clauses: list[str]
    timestamp: str                # ISO format
    why_this_rule: Optional[str]

    def format_text(self, width: int = 70) -> str:
        sep = "-" * width
        rule_str = f"{self.rule_id or '—'} v{self.rule_version or '?'}"
        if self.rule_name:
            rule_str += f"  \"{self.rule_name}\""
        clauses_str = ", ".join(self.document_clauses) if self.document_clauses else "Ninguna"
        lines = [
            f"  TRAZABILIDAD",
            sep,
            f"  Regla:         {rule_str}",
            f"  Clasificacion: {self.classification}",
            f"  Evaluadas: {self.rules_evaluated}  |  Coincidieron: {self.rules_matched}  |  Descartadas: {self.rules_discarded}",
            f"  Confianza:     {self.confidence:.0%}",
            f"  Clausulas:     {clauses_str}",
            f"  Timestamp:     {self.timestamp}",
        ]
        if self.why_this_rule:
            lines.append(f"  Conflicto:     {self.why_this_rule}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id":          self.rule_id,
            "rule_version":     self.rule_version,
            "rule_name":        self.rule_name,
            "rules_evaluated":  self.rules_evaluated,
            "rules_matched":    self.rules_matched,
            "rules_discarded":  self.rules_discarded,
            "classification":   self.classification,
            "confidence":       self.confidence,
            "document_clauses": self.document_clauses,
            "timestamp":        self.timestamp,
            "why_this_rule":    self.why_this_rule,
        }


@dataclass
class ClientMessage:
    """
    The ready-to-send client communication.
    Generated by MessageAgent via CommunicationEngine + LLM.
    Validated to confirm key facts are present.
    """
    text: str
    tone: str
    tone_label: str
    language: str
    template_id: str
    validation_passed: bool
    warnings: list[str] = field(default_factory=list)

    def format_text(self, width: int = 70) -> str:
        sep = "-" * width
        status = "OK" if self.validation_passed else f"ADVERTENCIAS: {len(self.warnings)}"
        lines = [
            f"  MENSAJE AL CLIENTE  [tono: {self.tone_label}]  [{status}]",
            sep,
            "",
            self.text,
            "",
        ]
        if self.warnings:
            lines.append(sep)
            for w in self.warnings:
                lines.append(f"  ! {w}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text":              self.text,
            "tone":              self.tone,
            "tone_label":        self.tone_label,
            "language":          self.language,
            "template_id":       self.template_id,
            "validation_passed": self.validation_passed,
            "warnings":          self.warnings,
        }


# ---------------------------------------------------------------------------
# Decision Card
# ---------------------------------------------------------------------------

@dataclass
class DecisionCard:
    """
    Complete operator-facing presentation of a decision.
    Read-only. Built from DecisionOutput — never the other way around.
    """
    case_id: str
    generated_at: str
    operator_summary: OperatorSummary
    audit_trail: AuditTrail
    client_message: Optional[ClientMessage]  # None if auto_messaging disabled
    # Copy-paste optimized outputs — no headers, no metadata, paste-ready
    copy_operator_summary: str = ""          # plain lines for CRM note / Slack
    copy_client_message: Optional[str] = None  # message body only for email

    def format_text(self, width: int = 70) -> str:
        """
        Plain-text card optimized for terminal display and copy-paste workflows.
        ASCII-safe — no box-drawing characters.
        """
        eq = "=" * width
        lines = [
            eq,
            f"  DECISION CARD  #{self.case_id}  [{self.generated_at[:19]}]",
            eq,
            "",
            self.operator_summary.format_text(width),
            "",
            self.audit_trail.format_text(width),
        ]
        if self.client_message:
            lines += [
                "",
                self.client_message.format_text(width),
            ]
        lines += ["", eq]
        return "\n".join(lines)

    def format_copy_blocks(self, width: int = 70) -> str:
        """
        Outputs only the copy-paste ready blocks — no card headers, no separators.
        Use these to paste directly into a CRM note, email, or Slack message.
        """
        eq = "=" * width
        lines = [
            eq,
            "  COPY — OPERATOR SUMMARY  (paste into CRM / Slack)",
            eq,
            "",
            self.copy_operator_summary,
            "",
            eq,
        ]
        if self.copy_client_message:
            lines += [
                "  COPY — CLIENT MESSAGE  (paste into email / WhatsApp)",
                eq,
                "",
                self.copy_client_message,
                "",
                eq,
            ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Structured dict for API response — JSON-serializable."""
        return {
            "case_id":               self.case_id,
            "generated_at":          self.generated_at,
            "operator_summary":      self.operator_summary.to_dict(),
            "audit_trail":           self.audit_trail.to_dict(),
            "client_message":        self.client_message.to_dict() if self.client_message else None,
            "copy_operator_summary": self.copy_operator_summary,
            "copy_client_message":   self.copy_client_message,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @staticmethod
    def build(
        decision: Any,                        # DecisionOutput — avoid circular import
        case_data: dict[str, Any],
        message_result: Optional[Any] = None, # MessageResult from MessageAgent
    ) -> "DecisionCard":
        """
        Factory — constructs a DecisionCard from a frozen DecisionOutput.
        Does not modify or store anything. Pure presentation transform.

        Args:
            decision:       Frozen DecisionOutput.
            case_data:      The case context dict (client_name, amounts, etc.)
            message_result: Optional MessageResult from MessageAgent.
        """
        from core.communication_engine import ACTION_LABELS, TONE_LABELS

        # ── Operator summary ─────────────────────────────────────────────
        currency = case_data.get("currency", "COP")
        overdue_days = int(case_data.get("overdue_days", 0))
        overdue_amount = float(case_data.get("overdue_amount", 0))
        client_name = case_data.get("client_name", "—")
        contract_id = case_data.get("contract_id", "—")

        client_line = f"{client_name} — {overdue_days} dias mora — ${overdue_amount:,.0f} {currency}"

        priority_val = decision.priority.value if hasattr(decision.priority, "value") else str(decision.priority)
        risk_level_val = decision.risk_level.value if hasattr(decision.risk_level, "value") else str(decision.risk_level)
        action = decision.action
        action_label = ACTION_LABELS.get(action, action.replace("_", " ").title())

        # next_step: prefer explicit field, fall back to what_happens_next, then rationale snippet
        next_step = (
            getattr(decision, "next_step", None)
            or getattr(decision, "what_happens_next", None)
            or (decision.rationale[:100] + "..." if len(decision.rationale) > 100 else decision.rationale)
        )

        # rationale: trim for operator display
        rationale = decision.rationale
        if len(rationale) > 120:
            rationale = rationale[:117] + "..."

        operator_summary = OperatorSummary(
            case_id=decision.case_id,
            priority=priority_val,
            risk_level=risk_level_val,
            risk_score=decision.risk_score,
            action=action,
            action_label=action_label,
            client_line=client_line,
            rationale=rationale,
            next_step=next_step,
            escalation=decision.escalation_target if decision.escalation_required else None,
            legal_alert=decision.legal_flag,
            policy_alert=decision.policy_flag,
        )

        # ── Audit trail ──────────────────────────────────────────────────
        # Extract rule name from rules_evaluated list if available
        rule_name: Optional[str] = None
        rules_matched = 0
        if decision.rule_id_applied and decision.rules_evaluated:
            for r in decision.rules_evaluated:
                if isinstance(r, dict) and r.get("matched"):
                    rules_matched += 1
                if (
                    isinstance(r, dict)
                    and r.get("rule_id") == decision.rule_id_applied
                    and r.get("rule_name")
                ):
                    rule_name = r["rule_name"]

        # Document clause labels
        doc_clauses: list[str] = []
        if decision.document_references:
            doc_clauses = [
                ref.clause_id for ref in decision.document_references
                if hasattr(ref, "clause_id") and ref.clause_id
            ]
        if not doc_clauses:
            raw_clauses = case_data.get("document_clauses", [])
            doc_clauses = [c.get("clause_label", "") for c in raw_clauses if c.get("clause_label")]

        timestamp = getattr(decision, "timestamp", None)
        ts_str = timestamp.isoformat() if timestamp else datetime.utcnow().isoformat()

        audit_trail = AuditTrail(
            rule_id=decision.rule_id_applied,
            rule_version=decision.rule_version_used,
            rule_name=rule_name,
            rules_evaluated=len(decision.rules_evaluated),
            rules_matched=rules_matched,
            rules_discarded=len(decision.rules_discarded),
            classification=decision.classification.value
                if hasattr(decision.classification, "value") else str(decision.classification),
            confidence=decision.confidence,
            document_clauses=doc_clauses,
            timestamp=ts_str,
            why_this_rule=getattr(decision, "why_this_rule", None),
        )

        # ── Client message ───────────────────────────────────────────────
        client_message: Optional[ClientMessage] = None
        if message_result is not None:
            # MessageResult is a dataclass with: text, tone, tone_label, language,
            # template_id, validation_passed, warnings
            if hasattr(message_result, "text") and message_result.text:
                client_message = ClientMessage(
                    text=message_result.text,
                    tone=getattr(message_result, "tone", "profesional"),
                    tone_label=TONE_LABELS.get(
                        getattr(message_result, "tone", "profesional"), "Profesional"
                    ),
                    language=getattr(message_result, "language", "es"),
                    template_id=getattr(message_result, "template_id", "default"),
                    validation_passed=getattr(message_result, "validation_passed", True),
                    warnings=getattr(message_result, "warnings", []),
                )

        # ── Copy-paste outputs ───────────────────────────────────────────
        # Operator summary — plain lines, no formatting characters
        copy_lines = [
            f"Caso: {decision.case_id} | Prioridad: {priority_val} | Riesgo: {risk_level_val} ({decision.risk_score:.0f}/100)",
            f"Accion: {action_label}",
            f"Cliente: {client_line}",
            f"Razon: {rationale}",
            f"Siguiente: {next_step}",
        ]
        if decision.escalation_required and decision.escalation_target:
            copy_lines.append(f"Escalar a: {decision.escalation_target}")
        if decision.legal_flag:
            copy_lines.append("ALERTA: Implicaciones legales activas")
        if decision.policy_flag:
            copy_lines.append("POLIZA: Cobertura de seguro aplicable")
        copy_operator_summary = "\n".join(copy_lines)

        # Client message — body text only, stripped of metadata
        copy_client_message: Optional[str] = (
            client_message.text.strip() if client_message and client_message.text else None
        )

        return DecisionCard(
            case_id=decision.case_id,
            generated_at=ts_str,
            operator_summary=operator_summary,
            audit_trail=audit_trail,
            client_message=client_message,
            copy_operator_summary=copy_operator_summary,
            copy_client_message=copy_client_message,
        )
