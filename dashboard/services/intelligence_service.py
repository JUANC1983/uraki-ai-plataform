# dashboard/services/intelligence_service.py
"""
Intelligence service — proactive suggestions, quality scoring, context packaging,
automation readiness tagging, and response performance feedback.

This service wraps several backend endpoints and provides client-side
computation as fallbacks when the backend doesn't yet expose the endpoints.

Backend endpoints (optional — all have client-side fallbacks):
  GET  /intelligence/suggestions?case_id=...  → proactive suggestions
  POST /intelligence/feedback                 → operator response rating
  GET  /intelligence/quality?decision_id=...  → quality/confidence scores
  GET  /intelligence/improvement              → system learning indicators

Client-side computations (always available):
  - quality_score:      derived from confidence, rules_evaluated, is_overridden, duration_ms
  - automation_tags:    derived from firmness, confidence, legal_flag, is_overridden
  - context_package:    executive summary built from case + decision fields
  - proactive alerts:   high-risk detection, repeated escalation patterns
"""
from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from services.api_client import AuthError, NetworkError, get_client

logger = logging.getLogger(__name__)


def _client():
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


# ── Quality scoring ───────────────────────────────────────────────────────────

def compute_quality_score(decision: dict) -> dict:
    """
    Compute a quality_score (0–100) and quality_label for a decision.

    Formula (client-side):
      base = confidence × 40           (0–40: model certainty)
      rules = min(rules_evaluated, 10) × 3   (0–30: rule coverage depth)
      speed = 15 if duration_ms < 5000 else max(0, 15 - (duration_ms-5000)//2000)
      override_penalty = -20 if is_overridden else 0
      legal_bonus = +5 if legal_flag and escalation_required

    Returns dict with quality_score, quality_label, quality_color, confidence_score.
    """
    confidence      = float(decision.get("confidence", 0))
    rules_evaluated = int(decision.get("rules_evaluated", 0))
    duration_ms     = int(decision.get("duration_ms", 0))
    is_overridden   = bool(decision.get("is_overridden", False))
    legal_flag      = bool(decision.get("legal_flag", False))
    escalation_req  = bool(decision.get("escalation_required", False))

    base     = confidence * 40
    rules    = min(rules_evaluated, 10) * 3
    speed    = (
        15 if duration_ms == 0 or duration_ms < 5_000
        else max(0, 15 - (duration_ms - 5_000) // 2_000)
    )
    override_penalty = -20 if is_overridden else 0
    legal_bonus      = 5 if (legal_flag and escalation_req) else 0
    # base coverage if nothing else contributes
    base_floor = 10

    raw = base_floor + base + rules + speed + override_penalty + legal_bonus
    score = max(0, min(100, int(raw)))

    if score >= 85:
        label, color = "Excelente", "#22C55E"
    elif score >= 70:
        label, color = "Bueno", "#84CC16"
    elif score >= 50:
        label, color = "Aceptable", "#F59E0B"
    else:
        label, color = "Bajo", "#EF4444"

    return {
        "quality_score":     score,
        "quality_label":     label,
        "quality_color":     color,
        "confidence_score":  round(confidence * 100),
        "confidence_label":  _confidence_label(confidence),
    }


def _confidence_label(c: float) -> str:
    if c >= 0.90:
        return "Muy alta"
    if c >= 0.75:
        return "Alta"
    if c >= 0.55:
        return "Moderada"
    return "Baja"


# ── Automation readiness tagging ──────────────────────────────────────────────

def compute_automation_tags(decision: dict) -> dict:
    """
    Tag a decision with automation-readiness metadata.
    Does NOT execute anything — only marks what could be automated.

    A decision is "automatable" when:
      - confidence >= 0.90
      - firmness in (FIRME, ESTRICTO, URGENTE)
      - not is_overridden
      - not legal_flag (legal decisions require human review)
      - escalation_required is False

    Returns dict with:
      automatable:       bool
      automation_block:  str | None  — reason why NOT automatable
      structured_output: dict        — machine-readable decision snapshot for future runner
    """
    confidence    = float(decision.get("confidence", 0))
    firmness      = decision.get("firmness", "FIRME")
    is_overridden = bool(decision.get("is_overridden", False))
    legal_flag    = bool(decision.get("legal_flag", False))
    escalation    = bool(decision.get("escalation_required", False))

    blocks: list[str] = []
    if confidence < 0.90:
        blocks.append(f"Confianza insuficiente ({confidence:.0%} < 90%)")
    if firmness not in ("FIRME", "ESTRICTO", "URGENTE"):
        blocks.append(f"Firmeza no automatizable ({firmness})")
    if is_overridden:
        blocks.append("Decisión fue sobreescrita manualmente")
    if legal_flag:
        blocks.append("Implicaciones legales — requiere revisión humana")
    if escalation:
        blocks.append("Requiere escalación — no automatizable")

    automatable = len(blocks) == 0

    structured_output = {
        "decision_id":    decision.get("id", ""),
        "case_id":        decision.get("case_id", ""),
        "action":         decision.get("action", ""),
        "action_label":   decision.get("action_label", ""),
        "confidence":     confidence,
        "firmness":       firmness,
        "rule_id":        decision.get("rule_id", ""),
        "rule_version":   decision.get("rule_version", ""),
        "risk_level":     decision.get("risk_level", ""),
        "risk_score":     decision.get("risk_score", 0),
        "legal_flag":     legal_flag,
        "escalation_required": escalation,
        "automatable":    automatable,
        "version_number": decision.get("version_number", 1),
        "schema_version": decision.get("schema_version", 1),
        # Future runner hooks — not executed yet
        "_runner_hook":   "uraki.automation.v1",
        "_runner_action": decision.get("action", ""),
        "_runner_ready":  automatable,
    }

    return {
        "automatable":       automatable,
        "automation_block":  "; ".join(blocks) if blocks else None,
        "structured_output": structured_output,
    }


# ── Proactive suggestions ─────────────────────────────────────────────────────

def get_proactive_suggestions(case: dict, decision: Optional[dict]) -> list[dict]:
    """
    Generate proactive alerts and suggestions for the operator.
    Computed client-side from case + decision fields.
    Also tries the backend for tenant-context suggestions.

    Each suggestion: {type, priority, title, body, action_hint}
    Types: "risk_alert" | "escalation_warning" | "pattern_detected" | "sla_warning" | "suggestion"
    Priority: "critical" | "high" | "medium" | "low"
    """
    suggestions: list[dict] = []

    # 1. Backend suggestions (tenant-context aware)
    try:
        resp = _client().get(
            "/intelligence/suggestions",
            params={"case_id": case.get("id", "")},
            ttl=60,
        )
        if resp.ok:
            backend = resp.items or (resp.data if isinstance(resp.data, list) else [])
            suggestions.extend(backend)
    except Exception:
        pass

    # 2. Client-side rule-based suggestions (always run — complement backend)
    suggestions.extend(_client_side_suggestions(case, decision))

    # Deduplicate by title + type and sort by priority weight
    seen: set[str] = set()
    unique: list[dict] = []
    for s in suggestions:
        key = f"{s.get('type')}:{s.get('title')}"
        if key not in seen:
            seen.add(key)
            unique.append(s)

    _PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    unique.sort(key=lambda s: _PRIORITY_ORDER.get(s.get("priority", "low"), 3))
    return unique


def _client_side_suggestions(case: dict, decision: Optional[dict]) -> list[dict]:
    suggestions: list[dict] = []

    days   = int(case.get("overdue_days", 0))
    amount = float(case.get("overdue_amount", 0))
    prev   = int(case.get("previous_overdue_count", 0))
    legal  = bool(case.get("has_legal_action", False))
    policy = bool(case.get("has_policy", False))
    status = case.get("status", "")

    # Critical: very high overdue days
    if days > 120:
        suggestions.append({
            "type":        "risk_alert",
            "priority":    "critical",
            "title":       f"Mora crítica: {days} días",
            "body":        "Este caso supera los 120 días de mora. El riesgo de irrecuperabilidad es alto.",
            "action_hint": "Evaluar inicio de proceso legal inmediato.",
        })

    # High: repeated offender
    if prev >= 3:
        suggestions.append({
            "type":        "pattern_detected",
            "priority":    "high",
            "title":       f"Patrón repetido: {prev} incidencias previas",
            "body":        "Este arrendatario tiene historial de mora recurrente. La probabilidad de reincidencia es alta.",
            "action_hint": "Considera activar cláusula de terminación anticipada.",
        })

    # High: large amount without policy
    if amount > 2_000_000 and not policy:
        suggestions.append({
            "type":        "risk_alert",
            "priority":    "high",
            "title":       "Monto alto sin cobertura de póliza",
            "body":        f"${amount:,.0f} COP en mora sin respaldo de seguro. Exposición financiera elevada.",
            "action_hint": "Considera solicitar activación de póliza o gestión directa.",
        })

    # Medium: legal action without escalation in decision
    if legal and decision and not decision.get("escalation_required"):
        suggestions.append({
            "type":        "escalation_warning",
            "priority":    "medium",
            "title":       "Acción legal activa sin escalación recomendada",
            "body":        "El caso tiene acción legal en curso pero la decisión no requiere escalación.",
            "action_hint": "Valida con el área legal si el caso debe ser escalonado.",
        })

    # Medium: case in review for >7 days
    from utils.time import bogota_now
    from datetime import datetime, timezone, timedelta
    created_iso = case.get("created_at", "")
    if created_iso and status == "in_review":
        try:
            ts = created_iso.rstrip("Z") + "+00:00" if created_iso.endswith("Z") else created_iso
            created = datetime.fromisoformat(ts)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone(timedelta(hours=-5)))
            elapsed = (bogota_now() - created).days
            if elapsed > 7:
                suggestions.append({
                    "type":        "sla_warning",
                    "priority":    "medium",
                    "title":       f"En revisión hace {elapsed} días",
                    "body":        "Este caso lleva más de 7 días en estado 'En revisión' sin resolución.",
                    "action_hint": "Resuelve o escala para liberar capacidad operativa.",
                })
        except Exception:
            pass

    # Decision quality suggestions
    if decision:
        quality = compute_quality_score(decision)
        if quality["quality_score"] < 50:
            suggestions.append({
                "type":        "suggestion",
                "priority":    "medium",
                "title":       f"Calidad de decisión baja ({quality['quality_score']}/100)",
                "body":        "La confianza del motor de reglas en esta decisión es baja. Considera una revisión manual.",
                "action_hint": "Verifica los factores de riesgo y considera ejecutar re-evaluación.",
            })

        conf = float(decision.get("confidence", 0))
        if conf < 0.60 and not decision.get("is_overridden"):
            suggestions.append({
                "type":        "suggestion",
                "priority":    "medium",
                "title":       f"Confianza baja: {conf:.0%}",
                "body":        "El motor no tiene certeza alta sobre esta decisión. Puede haber información faltante.",
                "action_hint": "Adjunta documentos adicionales o solicita más información al arrendatario.",
            })

    return suggestions


# ── Context packaging ─────────────────────────────────────────────────────────

def build_context_package(case: dict, decision: Optional[dict]) -> dict:
    """
    Build a structured context package for a case+decision pair.

    Returns:
      executive_summary: str  — 2-sentence operator-facing summary
      risk_summary:      str  — structured risk description
      next_step:         str  — the single recommended immediate action
      quality:           dict — quality scoring output
      automation:        dict — automation readiness tags
      structured_output: dict — machine-readable snapshot
    """
    cname  = case.get("client_name", "—")
    days   = int(case.get("overdue_days", 0))
    amount = float(case.get("overdue_amount", 0))
    status = case.get("status", "—")

    if decision:
        action_label  = decision.get("action_label") or decision.get("action", "—")
        risk_level    = decision.get("risk_level", "—")
        risk_score    = float(decision.get("risk_score", 0))
        rationale     = decision.get("rationale", "")
        next_step_raw = decision.get("next_step") or decision.get("rationale", "")
        legal_flag    = bool(decision.get("legal_flag", False))
        policy_flag   = bool(decision.get("policy_flag", False))
        escalation    = bool(decision.get("escalation_required", False))
        esc_target    = decision.get("escalation_target") or ""

        executive_summary = (
            f"{cname} tiene {days} días de mora por ${amount:,.0f} COP (estado: {status}). "
            f"El motor de reglas recomienda: {action_label} "
            f"con nivel de riesgo {risk_level} ({risk_score:.0f}/100)."
        )

        risk_parts = [f"Riesgo {risk_level} · {risk_score:.0f}/100"]
        if legal_flag:
            risk_parts.append("⚖ Implicaciones legales activas")
        if policy_flag:
            risk_parts.append("🛡 Póliza de seguro aplicable")
        if escalation and esc_target:
            risk_parts.append(f"↑ Requiere escalación a: {esc_target}")
        risk_summary = " · ".join(risk_parts)

        next_step = next_step_raw or action_label

        quality    = compute_quality_score(decision)
        automation = compute_automation_tags(decision)

    else:
        executive_summary = (
            f"{cname} tiene {days} días de mora por ${amount:,.0f} COP. "
            f"Sin decisión generada aún — ejecuta la evaluación del motor de reglas."
        )
        risk_summary = f"{days} días de mora · ${amount:,.0f} COP · Sin decisión"
        next_step    = "Ejecutar evaluación del motor de reglas"
        quality      = {"quality_score": 0, "quality_label": "Sin evaluar", "quality_color": "#888"}
        automation   = {"automatable": False, "automation_block": "Sin decisión", "structured_output": {}}

    return {
        "executive_summary": executive_summary,
        "risk_summary":      risk_summary,
        "next_step":         next_step,
        "quality":           quality,
        "automation":        automation,
        "structured_output": automation.get("structured_output", {}),
    }


# ── Operator response feedback ────────────────────────────────────────────────

class ResponseFeedbackService:

    def submit_rating(
        self,
        decision_id: str,
        case_id:     str,
        rating:      int,             # 1–5
        flags:       list[str],       # e.g. ["incorrect_action", "wrong_risk"]
        comment:     str = "",
    ) -> Optional[str]:
        """
        POST /intelligence/feedback
        Stores operator rating of a decision response.
        Returns error string or None on success.
        Non-critical — never raises.
        """
        body = {
            "decision_id": decision_id,
            "case_id":     case_id,
            "rating":      max(1, min(5, rating)),
            "flags":       flags or [],
            "comment":     comment.strip(),
            "operator_id": st.session_state.get("auth_user", {}).get("email", ""),
            "tenant_id":   st.session_state.get("auth_user", {}).get("tenant_id"),
        }
        try:
            resp = _client().post("/intelligence/feedback", json=body)
            if resp.ok:
                _client().invalidate("/intelligence/improvement")
                return None
            logger.warning("Feedback submit failed: %s", resp.error)
            return resp.error or "Error al registrar feedback"
        except Exception as exc:
            logger.warning("Feedback submit error: %s", exc)
            return None   # non-critical

    def get_improvement_stats(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /intelligence/improvement
        Returns learning indicators.
        Shape: {
          "avg_rating":        float,   # 1–5
          "flagged_rate":      float,   # 0–1
          "accuracy_trend":    list[{date, accuracy}],
          "override_trend":    list[{date, override_rate}],
          "total_ratings":     int,
          "rating_breakdown":  {1: int, 2: int, 3: int, 4: int, 5: int},
        }
        """
        try:
            resp = _client().get("/intelligence/improvement", ttl=120)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al cargar indicadores de mejora"

        return resp.data, None
