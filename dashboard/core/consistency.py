# dashboard/core/consistency.py
"""
Data consistency guardrails.

Validates that case state, decision output, and action history are
internally consistent before rendering the UI. Prevents mismatched
states from causing incorrect operator decisions.

Consistency rules enforced:
  1. A CLOSED case must not have an active escalation_required flag
  2. A decision with legal_flag=True must have a non-empty rationale
  3. An overridden decision must have a non-empty override_reason
  4. A case with status ESCALATED must have a decision with escalation_required=True OR
     the escalation was operator-initiated (override path)
  5. Risk score must be in [0, 100]
  6. Confidence must be in [0, 1]
  7. rule_id must be non-empty on any firm decision
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class ConsistencyViolation:
    rule:    str    # machine-readable rule code
    message: str    # human-readable explanation
    severity: str  # "warning" | "error"
    field:   str    # which field is affected


@dataclass
class ConsistencyResult:
    ok:         bool
    violations: list[ConsistencyViolation]

    @property
    def errors(self) -> list[ConsistencyViolation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> list[ConsistencyViolation]:
        return [v for v in self.violations if v.severity == "warning"]


def check(case: dict, decision: Optional[dict]) -> ConsistencyResult:
    """
    Run all consistency rules against a case + decision pair.
    Returns ConsistencyResult with any violations found.
    """
    violations: list[ConsistencyViolation] = []

    # ── Case-only rules ───────────────────────────────────────────────
    status = case.get("status", "")

    if not case.get("id"):
        violations.append(ConsistencyViolation(
            rule="CASE_NO_ID",
            message="El caso no tiene un ID válido.",
            severity="error",
            field="id",
        ))

    if status == "CLOSED" and case.get("has_legal_action"):
        violations.append(ConsistencyViolation(
            rule="CLOSED_WITH_LEGAL",
            message="Caso cerrado con acción legal activa — verifica que la acción legal fue resuelta.",
            severity="warning",
            field="has_legal_action",
        ))

    if case.get("overdue_amount", 0) < 0:
        violations.append(ConsistencyViolation(
            rule="NEGATIVE_AMOUNT",
            message="Monto vencido negativo — dato inválido del backend.",
            severity="error",
            field="overdue_amount",
        ))

    if case.get("overdue_days", 0) < 0:
        violations.append(ConsistencyViolation(
            rule="NEGATIVE_DAYS",
            message="Días de mora negativos — dato inválido del backend.",
            severity="error",
            field="overdue_days",
        ))

    # ── Case + decision cross-rules ───────────────────────────────────
    if decision is None:
        if status == "DECISION_GENERATED":
            violations.append(ConsistencyViolation(
                rule="STATUS_DECISION_MISMATCH",
                message="Estado indica decisión generada pero no hay objeto de decisión.",
                severity="error",
                field="status / latest_decision",
            ))
        return ConsistencyResult(ok=not any(v.severity == "error" for v in violations), violations=violations)

    # Decision rules
    risk_score = decision.get("risk_score", 0)
    if not (0 <= risk_score <= 100):
        violations.append(ConsistencyViolation(
            rule="RISK_SCORE_RANGE",
            message=f"Risk score fuera de rango: {risk_score} (esperado 0–100).",
            severity="error",
            field="risk_score",
        ))

    confidence = decision.get("confidence", 0)
    if not (0.0 <= confidence <= 1.0):
        violations.append(ConsistencyViolation(
            rule="CONFIDENCE_RANGE",
            message=f"Confidence fuera de rango: {confidence} (esperado 0.0–1.0).",
            severity="error",
            field="confidence",
        ))

    firmness = decision.get("firmness", "")
    if firmness not in ("URGENTE", "ESTRICTO", "FIRME", "SUAVE", ""):
        violations.append(ConsistencyViolation(
            rule="UNKNOWN_FIRMNESS",
            message=f"Firmeza desconocida: '{firmness}'.",
            severity="warning",
            field="firmness",
        ))

    if decision.get("legal_flag") and not decision.get("rationale", "").strip():
        violations.append(ConsistencyViolation(
            rule="LEGAL_FLAG_NO_RATIONALE",
            message="Decisión con implicación legal activa pero sin justificación. No debería renderizarse.",
            severity="error",
            field="rationale",
        ))

    if decision.get("is_overridden") and not decision.get("override_reason", "").strip():
        violations.append(ConsistencyViolation(
            rule="OVERRIDE_NO_REASON",
            message="Decisión sobreescrita sin razón registrada — violación de auditoría.",
            severity="error",
            field="override_reason",
        ))

    if (decision.get("firmness") in ("URGENTE", "ESTRICTO") and
            not decision.get("rule_id", "").strip()):
        violations.append(ConsistencyViolation(
            rule="FIRM_DECISION_NO_RULE",
            message="Decisión firme/urgente sin rule_id — trazabilidad comprometida.",
            severity="warning",
            field="rule_id",
        ))

    if status == "ESCALATED" and not decision.get("escalation_required") and not decision.get("is_overridden"):
        violations.append(ConsistencyViolation(
            rule="ESCALATED_NOT_FLAGGED",
            message="Caso escalado pero la decisión no requería escalación (sin override). Verifica manualmente.",
            severity="warning",
            field="escalation_required",
        ))

    if status == "CLOSED" and decision.get("escalation_required") and not decision.get("is_overridden"):
        violations.append(ConsistencyViolation(
            rule="CLOSED_PENDING_ESCALATION",
            message="Caso cerrado con escalación pendiente — la decisión aún requería escalación.",
            severity="warning",
            field="escalation_required",
        ))

    ok = not any(v.severity == "error" for v in violations)
    return ConsistencyResult(ok=ok, violations=violations)


def render_violations_html(result: ConsistencyResult, c: dict) -> str:
    """Render consistency violations as HTML for display in the decision card."""
    if result.ok and not result.warnings:
        return ""

    items = []
    for v in result.violations:
        border = "rgba(239,68,68,0.4)" if v.severity == "error" else "rgba(245,158,11,0.3)"
        icon   = "✕" if v.severity == "error" else "⚠"
        color  = "#EF4444" if v.severity == "error" else "#F59E0B"
        items.append(
            f'<div style="display:flex;gap:6px;padding:3px 0;">'
            f'<span style="color:{color};font-size:11px;">{icon}</span>'
            f'<span style="font-size:11px;color:{c["text_secondary"]};line-height:1.4;">'
            f'<strong style="color:{color};">[{v.rule}]</strong> {v.message}</span>'
            f'</div>'
        )

    border_color = "rgba(239,68,68,0.4)" if result.errors else "rgba(245,158,11,0.3)"
    bg_color     = "rgba(239,68,68,0.06)" if result.errors else "rgba(245,158,11,0.06)"
    title        = "Inconsistencias de datos detectadas" if result.errors else "Advertencias de consistencia"

    return f"""
    <div style="background:{bg_color};border:1px solid {border_color};
        border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.75rem;">
        <div style="font-size:10px;font-weight:600;color:#888888;
            text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">
            {title}</div>
        {''.join(items)}
    </div>
    """
