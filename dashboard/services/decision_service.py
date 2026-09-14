# dashboard/services/decision_service.py
"""
Decision service — wraps evaluate, override, upload, and decision fetch.
All business logic lives in the backend. This is a pure API adapter.
No demo mode. A real backend is required.
"""
from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from services.api_client import AuthError, NetworkError, get_client
from services.case_service import CaseService
from services.schema import validate_decision, SchemaError
from core.schema_evolution import migrate_decision, stamp_current_decision

logger = logging.getLogger(__name__)


def _rule_count(value) -> int:
    """Normalize API rule traces (lists) and evaluation counts (integers)."""
    if isinstance(value, list):
        return len(value)
    return int(value or 0)


def _risk_factor_rows(value) -> list[dict]:
    """Map the canonical risk breakdown to the rows rendered by the dashboard."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []

    scores = value.get("component_scores") or {}
    weights = value.get("weights_used") or {}
    reasons = value.get("component_reasons") or {}
    if not isinstance(scores, dict):
        return []

    rows = []
    for name, raw_score in scores.items():
        try:
            score = float(raw_score)
            weight = float(weights.get(name, 0))
        except (TypeError, ValueError):
            continue
        rows.append({
            "factor": str(name).replace("_", " ").title(),
            "value": reasons.get(name) or f"Score {score:.0f}/100",
            "weight": f"Peso {weight:.0%}",
            "contribution": score * weight / 100,
        })
    return rows

# Actions available in the override selector
AVAILABLE_ACTIONS: list[str] = [
    "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA",
    "INICIAR_DEMANDA_DE_RESTITUCIÓN",
    "PROPONER_ACUERDO_DE_PAGO",
    "COBRAR_PENALIDAD_CONTRACTUAL",
    "ENVIAR_RECORDATORIO_DE_PAGO",
    "REVISAR_MANUALMENTE",
]

ACTION_LABELS: dict[str, str] = {
    "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA": "Activar póliza y notificar aseguradora",
    "INICIAR_DEMANDA_DE_RESTITUCIÓN":          "Iniciar proceso de restitución",
    "PROPONER_ACUERDO_DE_PAGO":                "Proponer acuerdo de pago",
    "COBRAR_PENALIDAD_CONTRACTUAL":            "Cobrar penalidad contractual",
    "ENVIAR_RECORDATORIO_DE_PAGO":             "Enviar recordatorio de pago",
    "REVISAR_MANUALMENTE":                     "Revisar manualmente",
}


def _client():
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


class DecisionService:

    def get_decision(self, case_id: str) -> tuple[Optional[dict], Optional[str]]:
        """
        Return the latest normalized decision for a case.
        Decision is embedded in the case detail response — no extra round-trip.
        """
        cs = CaseService()
        case, err = cs.get_by_id(case_id)
        if err:
            return None, err
        if not case:
            return None, "Caso no encontrado"

        d = case.get("latest_decision")
        if not d:
            return None, None   # case exists but no decision yet — caller shows evaluate CTA

        try:
            # Run schema migration before normalizing — old decisions remain valid
            migrated   = migrate_decision(d)
            normalized = self._normalize(migrated, case)
            validate_decision(normalized, case_id)
            return normalized, None
        except SchemaError as exc:
            return None, f"Decisión con formato inválido: {exc}"

    def evaluate(self, case_id: str) -> tuple[Optional[dict], Optional[str]]:
        """Trigger /cases/{id}/evaluate and return normalized decision."""
        cs = CaseService()
        result, err = cs.evaluate(case_id)
        if err:
            return None, err
        if not result:
            return None, "Evaluación no retornó datos"
        return self._normalize_eval(result), None

    def override(
        self,
        decision_id: str,
        overridden_action: str,
        reason: str,
    ) -> tuple[Optional[dict], Optional[str]]:
        """POST /decisions/{decision_id}/override"""
        try:
            resp = _client().post(
                f"/decisions/{decision_id}/override",
                json={"overridden_action": overridden_action, "reason": reason},
            )
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if resp.status_code == 403:
            return None, "Sin permisos para hacer override. Requiere rol Gerente o Admin."
        if not resp.ok:
            return None, resp.error or "Error al aplicar override"

        _client().invalidate("/cases")
        return resp.data, None

    def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        document_type: str,
        case_id: Optional[str] = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        """POST /documents/upload — multipart."""
        files = {"file": (filename, file_bytes, content_type)}
        data: dict = {"document_type": document_type}
        if case_id:
            data["case_id"] = case_id

        try:
            resp = _client().upload("/documents/upload", files=files, data=data)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al subir documento"

        # Invalidate case so the document list refreshes
        if case_id:
            _client().invalidate(f"/cases/{case_id}")

        return resp.data, None

    def get_linked_documents(self, case_id: str) -> tuple[list[dict], Optional[str]]:
        """GET /cases/{case_id}/documents"""
        try:
            resp = _client().get(f"/cases/{case_id}/documents", ttl=30)
        except AuthError as e:
            return [], str(e)
        except NetworkError as e:
            return [], f"Sin conexión: {e}"

        if not resp.ok:
            return [], resp.error or "Error al cargar documentos"

        return resp.items or [], None

    def get_copy_summary(self, case: dict, decision: dict) -> str:
        """Build a plain-text operator summary for clipboard copy."""
        lines = [
            f"Caso: {case.get('id')} | Prioridad: {decision.get('priority','?')} | "
            f"Riesgo: {decision.get('risk_level','?')} ({decision.get('risk_score',0):.0f}/100)",
            f"Acción: {decision.get('action_label', decision.get('action',''))}",
            f"Cliente: {case.get('client_name','—')} — {case.get('overdue_days',0)} días mora — "
            f"${case.get('overdue_amount',0):,.0f} {case.get('currency','COP')}",
            f"Razón: {decision.get('rationale','')}",
            f"Siguiente: {decision.get('next_step','')}",
        ]
        if decision.get("escalation_required") and decision.get("escalation_target"):
            lines.append(f"Escalar a: {decision['escalation_target']}")
        if decision.get("legal_flag"):
            lines.append("ALERTA: Implicaciones legales activas")
        if decision.get("policy_flag"):
            lines.append("PÓLIZA: Cobertura de seguro aplicable")
        if decision.get("rule_id"):
            lines.append(f"Regla: {decision['rule_id']} v{decision.get('rule_version','?')}")
        return "\n".join(lines)

    # ── Normalizers ────────────────────────────────────────────────────

    def _normalize(self, d: dict, case: dict) -> dict:
        """Map GET /cases/{id}.latest_decision → UI decision dict."""
        return stamp_current_decision({
            "id":                  d.get("id", ""),
            "case_id":             case.get("id", ""),
            "action":              d.get("action", "REVISAR_MANUALMENTE"),
            "action_label":        d.get("action_label") or ACTION_LABELS.get(
                                       d.get("action", ""), d.get("action", "")),
            "classification":      d.get("classification", "OTRO"),
            "risk_score":          float(d.get("risk_score", 0)),
            "risk_level":          d.get("risk_level", "BAJO"),
            "priority":            case.get("priority") or d.get("priority", "LOW"),
            "firmness":            d.get("firmness", "FIRME"),
            "escalation_required": bool(d.get("escalation_required")),
            "escalation_target":   d.get("escalation_target"),
            "legal_flag":          bool(d.get("legal_flag")),
            "policy_flag":         bool(d.get("policy_flag")),
            "rationale":           d.get("rationale", ""),
            "next_step":           d.get("next_step") or d.get("what_happens_next", ""),
            "rule_id":             d.get("rule_id_applied") or d.get("rule_id", ""),
            "rule_version":        d.get("rule_version") or d.get("rule_version_used"),
            "why_this_rule":       d.get("why_this_rule", ""),
            "confidence":          float(d.get("confidence", 0)),
            "clause_labels":       d.get("clause_labels", ""),
            "rules_evaluated":     _rule_count(d.get("rules_evaluated")),
            "rules_discarded":     _rule_count(d.get("rules_discarded")),
            "is_overridden":       bool(d.get("is_overridden")),
            "override_reason":     d.get("override_reason", ""),
            "original_action":     d.get("original_action", ""),
            "suggested_message":   d.get("suggested_message", ""),
            "duration_ms":         int(d.get("duration_ms", 0)),
            "created_at":          d.get("created_at", ""),
            # Intelligence layer
            "risk_factors":        _risk_factor_rows(d.get("risk_factors")),
            "data_used":           d.get("data_used") or {},
            "linked_documents":    d.get("linked_documents") or [],
            "explain":             d.get("explain", ""),
            # Decision versioning (from migration — always present after migrate_decision)
            "version_number":      d.get("version_number") or 1,
            "previous_version_id": d.get("previous_version_id"),
            "rule_active_from":    d.get("rule_active_from"),
            "rule_active_to":      d.get("rule_active_to"),
        })

    def _normalize_eval(self, r: dict) -> dict:
        """Map POST /cases/{id}/evaluate response → UI decision dict."""
        rule = r.get("rule_applied") or {}
        risk = r.get("risk") or {}
        return stamp_current_decision({
            "id":                  r.get("decision_id", ""),
            "case_id":             r.get("case_id", ""),
            "action":              r.get("decision", "REVISAR_MANUALMENTE"),
            "action_label":        ACTION_LABELS.get(r.get("decision", ""), r.get("decision", "")),
            "classification":      r.get("classification", "OTRO"),
            "risk_score":          float(risk.get("score", 0)),
            "risk_level":          risk.get("level", "BAJO"),
            "priority":            r.get("priority", "LOW"),
            "firmness":            r.get("firmness", "FIRME"),
            "escalation_required": bool(r.get("escalation_required")),
            "escalation_target":   r.get("escalation_target"),
            "legal_flag":          bool(r.get("legal_flag")),
            "policy_flag":         bool(r.get("policy_flag")),
            "rationale":           r.get("why", ""),
            "next_step":           r.get("next_action", ""),
            "rule_id":             rule.get("rule_id", ""),
            "rule_version":        rule.get("rule_version"),
            "why_this_rule":       rule.get("explanation", ""),
            "confidence":          float(r.get("confidence", 0)),
            "clause_labels":       "",
            "rules_evaluated":     _rule_count(r.get("rules_evaluated")),
            "rules_discarded":     _rule_count(r.get("rules_discarded")),
            "is_overridden":       False,
            "override_reason":     "",
            "original_action":     "",
            "suggested_message":   r.get("suggested_message", ""),
            "duration_ms":         int(r.get("duration_ms", 0)),
            "created_at":          "",
            # Intelligence layer
            "risk_factors":        _risk_factor_rows(r.get("risk_factors")),
            "data_used":           r.get("data_used") or {},
            "linked_documents":    [],
            "explain":             r.get("explain", ""),
            # Decision versioning
            "version_number":      r.get("version_number") or 1,
            "previous_version_id": r.get("previous_version_id"),
            "rule_active_from":    r.get("rule_active_from"),
            "rule_active_to":      r.get("rule_active_to"),
        })
