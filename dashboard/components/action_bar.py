# dashboard/components/action_bar.py
"""
Sticky action bar — primary operator actions for the selected case.
Resolve · Escalate · Copy · Download · Edit
"""
import streamlit as st
import json
import core.state_manager as sm
import core.event_bus as bus
from styles.theme import COLORS
from services.decision_service import DecisionService
from utils.formatters import fmt_currency


def render(case: dict, decision: dict | None) -> None:
    c = COLORS
    case_id = case["id"]
    status = case["status"]
    is_closed = status == "CLOSED"
    is_escalated = status == "ESCALATED"

    st.markdown(f"""
    <div style="
        position:sticky;bottom:0;
        background:{c['bg_secondary']};
        border-top:1px solid {c['border_default']};
        padding:0.75rem 0;
        margin-top:1rem;
        z-index:100;
    ">
        <div style="font-size:10px;color:{c['text_muted']};
            text-transform:uppercase;letter-spacing:0.08em;
            margin-bottom:0.5rem;padding:0 0.25rem;">
            Acciones
        </div>
    </div>
    """, unsafe_allow_html=True)

    btn_cols = st.columns([1.4, 1.2, 1.2, 1, 1])

    # ── Resolve ────────────────────────────────────────────────────────
    with btn_cols[0]:
        st.markdown('<div class="uraki-btn-success">', unsafe_allow_html=True)
        resolve_disabled = is_closed
        if st.button(
            label="✓ Resolver" if not is_closed else "✓ Cerrado",
            key=f"resolve_{case_id}",
            disabled=resolve_disabled,
            use_container_width=True,
        ):
            # Update memory outcome before emitting resolution event
            try:
                from services.memory_service import MemoryService
                from datetime import datetime, timezone, timedelta
                created_iso = case.get("created_at", "")
                outcome_days: int | None = None
                if created_iso:
                    try:
                        ts = created_iso.rstrip("Z") + "+00:00" if created_iso.endswith("Z") else created_iso
                        created = datetime.fromisoformat(ts)
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=timezone(timedelta(hours=-5)))
                        outcome_days = (datetime.now(timezone(timedelta(hours=-5))) - created).days
                    except Exception:
                        pass
                MemoryService().update_outcome(case_id, "resolved", outcome_days)
            except Exception:
                pass
            bus.emit("CASE_RESOLVED", {"case_id": case_id})
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Escalate ───────────────────────────────────────────────────────
    with btn_cols[1]:
        st.markdown('<div class="uraki-btn-danger">', unsafe_allow_html=True)
        if st.button(
            label="↑ Escalar" if not is_escalated else "↑ Escalado",
            key=f"escalate_{case_id}",
            disabled=is_closed or is_escalated,
            use_container_width=True,
        ):
            target = (decision.get("escalation_target") if decision else None) or "supervisor"
            bus.emit("CASE_ESCALATED", {"case_id": case_id, "target": target})
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Copy summary ───────────────────────────────────────────────────
    with btn_cols[2]:
        if st.button(
            label="📋 Copiar",
            key=f"copy_action_{case_id}",
            use_container_width=True,
        ):
            sm.set("show_message", True)
            st.rerun()

    # ── Download JSON ──────────────────────────────────────────────────
    with btn_cols[3]:
        payload = _build_download_payload(case, decision or {})
        st.download_button(
            label="⬇ JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2),
            file_name=f"{case_id}_decision.json",
            mime="application/json",
            key=f"download_{case_id}",
            use_container_width=True,
            disabled=not decision,
        )

    # ── Mark in review ─────────────────────────────────────────────────
    with btn_cols[4]:
        from services.case_service import CaseService
        cs = CaseService()
        if st.button(
            label="✏ Revisar",
            key=f"review_{case_id}",
            disabled=is_closed,
            use_container_width=True,
        ):
            err = cs.set_status(case_id, "IN_REVIEW")
            if err:
                sm.flash_error(f"No se pudo cambiar estado: {err}")
            st.rerun()

    # ── Status info bar ────────────────────────────────────────────────
    _render_status_strip(case, decision or {}, c)


def _render_status_strip(case: dict, decision: dict, c: dict) -> None:
    status = case["status"]
    assigned = case.get("assigned_to", "—")

    from styles.theme import STATUS_COLORS, STATUS_LABELS
    status_color = STATUS_COLORS.get(status, c["text_muted"])
    status_label = STATUS_LABELS.get(status, status)
    from utils.time import time_ago
    ago = time_ago(case["created_at"])

    st.markdown(f"""
    <div style="
        display:flex;align-items:center;justify-content:space-between;
        padding:0.5rem 0.25rem 0;
        flex-wrap:wrap;gap:0.5rem;
    ">
        <div style="display:flex;align-items:center;gap:12px;">
            <span style="
                background:rgba({_hex_rgb(status_color)},0.10);
                color:{status_color};border-radius:4px;
                padding:2px 8px;font-size:11px;font-weight:500;
            ">{status_label}</span>
            <span style="font-size:11px;color:{c['text_muted']};">
                Asignado: <span style="color:{c['text_secondary']};">{assigned}</span>
            </span>
        </div>
        <span style="font-size:11px;color:{c['text_muted']};">
            Creado {ago} · Regla {decision.get('rule_id','—')} v{decision.get('rule_version','?')}
        </span>
    </div>
    """, unsafe_allow_html=True)


def _build_download_payload(case: dict, decision: dict) -> dict:
    from services.intelligence_service import compute_quality_score, compute_automation_tags, build_context_package
    quality    = compute_quality_score(decision) if decision.get("action") else {}
    automation = compute_automation_tags(decision) if decision.get("action") else {}
    ctx        = build_context_package(case, decision if decision.get("action") else None)

    return {
        "case_id":          case["id"],
        "generated_at":     __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "operator_summary": {
            "priority":     decision.get("priority", "—"),
            "risk_level":   decision.get("risk_level", "—"),
            "risk_score":   decision.get("risk_score", 0),
            "action":       decision.get("action", "—"),
            "action_label": decision.get("action_label", "—"),
            "client":       case.get("client_name", "—"),
            "overdue_days": case.get("overdue_days", 0),
            "overdue_amount": fmt_currency(case.get("overdue_amount", 0), case.get("currency", "COP")),
            "rationale":    decision.get("rationale", ""),
            "next_step":    decision.get("next_step", ""),
        },
        "audit": {
            "rule_id":        decision.get("rule_id"),
            "rule_version":   decision.get("rule_version"),
            "classification": decision.get("classification", ""),
            "confidence":     decision.get("confidence", 0),
            "clause_labels":  decision.get("clause_labels"),
            "version_number": decision.get("version_number", 1),
            "schema_version": decision.get("schema_version", 1),
        },
        "quality": {
            "quality_score":    quality.get("quality_score", 0),
            "quality_label":    quality.get("quality_label", "—"),
            "confidence_score": quality.get("confidence_score", 0),
        },
        "context_package": {
            "executive_summary": ctx.get("executive_summary", ""),
            "risk_summary":      ctx.get("risk_summary", ""),
            "next_step":         ctx.get("next_step", ""),
        },
        "automation": automation.get("structured_output", {}),
        "client_message": decision.get("suggested_message", ""),
    }


def _hex_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
    return "128,128,128"
