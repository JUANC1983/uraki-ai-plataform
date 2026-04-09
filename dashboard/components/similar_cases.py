# dashboard/components/similar_cases.py
"""
Similar Cases Panel — shows past cases with similar profile for operator guidance.

Uses MemoryService to fetch (or compute locally) similar fingerprints.
Displays outcome, action taken, and similarity score for each match.
"""
from __future__ import annotations

import streamlit as st
from styles.theme import COLORS, RISK_COLORS
from services.memory_service import MemoryService
from utils.formatters import fmt_currency
from utils.time import time_ago

_OUTCOME_STYLES: dict[str, tuple[str, str]] = {
    "resolved":    ("✓ Resuelto",   "#22C55E"),
    "escalated":   ("↑ Escalado",   "#F59E0B"),
    "overridden":  ("⚠ Override",   "#F59E0B"),
    "closed":      ("✓ Cerrado",    "#22C55E"),
    "pending":     ("· Pendiente",  "#6B7280"),
}


def render(case: dict) -> None:
    """Render the similar cases panel inside an expander."""
    c = COLORS

    with st.expander("🧠 Casos similares — memoria del sistema", expanded=False):
        similar = MemoryService().get_similar(case, limit=5)

        if not similar:
            st.markdown(f"""
            <div style="text-align:center;padding:1.25rem;
                font-size:12px;color:{c['text_muted']};">
                <div style="font-size:20px;margin-bottom:0.4rem;">🔍</div>
                Sin casos similares registrados aún.<br>
                El sistema aprende a medida que se procesan más casos.
            </div>
            """, unsafe_allow_html=True)
            return

        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_muted']};
            margin-bottom:0.6rem;line-height:1.5;">
            {len(similar)} caso{'s' if len(similar) != 1 else ''} similar{'es' if len(similar) != 1 else ''}
            encontrado{'s' if len(similar) != 1 else ''} en la memoria del sistema.
            Úsalos como referencia para tu decisión.
        </div>
        """, unsafe_allow_html=True)

        for fp in similar:
            _render_fingerprint_card(fp, c)


def _render_fingerprint_card(fp: dict, c: dict) -> None:
    sim_score    = fp.get("similarity_score", fp.get("similarity", 0))
    sim_pct      = int(sim_score * 100) if sim_score <= 1 else int(sim_score)
    action       = fp.get("action", "—")
    action_label = _action_label(action)
    risk_level   = fp.get("risk_level", "BAJO")
    risk_color   = RISK_COLORS.get(risk_level, "#888")
    outcome_raw  = fp.get("outcome") or "pending"
    outcome_label, outcome_color = _OUTCOME_STYLES.get(
        outcome_raw, (outcome_raw, "#6B7280")
    )
    outcome_days = fp.get("outcome_days")
    overdue_days = fp.get("overdue_days", 0)
    amount       = fp.get("overdue_amount", 0)
    was_ov       = bool(fp.get("was_overridden", False))
    case_id_short = str(fp.get("case_id", "?"))[:12]
    created      = fp.get("created_at", "")

    sim_color = (
        "#22C55E" if sim_pct >= 85
        else "#F59E0B" if sim_pct >= 70
        else "#6B7280"
    )

    override_note = (
        f'<span style="background:rgba(245,158,11,0.10);color:#F59E0B;'
        f'border-radius:3px;padding:1px 5px;font-size:9px;margin-left:4px;">Override</span>'
        if was_ov else ""
    )

    days_note = f" · {outcome_days}d resolución" if outcome_days else ""

    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:7px;padding:0.55rem 0.8rem;margin-bottom:0.4rem;
    ">
        <div style="display:flex;align-items:center;
            justify-content:space-between;margin-bottom:4px;flex-wrap:wrap;gap:4px;">
            <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:10px;color:{c['text_muted']};font-family:monospace;">
                    {case_id_short}</span>
                <span style="font-size:10px;color:{risk_color};font-weight:600;">
                    {risk_level}</span>
                {override_note}
            </div>
            <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:10px;color:{outcome_color};font-weight:600;">
                    {outcome_label}{days_note}</span>
                <span style="
                    background:rgba({_hex_rgb(sim_color)},0.10);
                    color:{sim_color};border:1px solid rgba({_hex_rgb(sim_color)},0.3);
                    border-radius:4px;padding:1px 6px;
                    font-size:10px;font-weight:700;">
                    {sim_pct}% similar</span>
            </div>
        </div>

        <div style="display:flex;gap:1.5rem;flex-wrap:wrap;">
            <div>
                <span style="font-size:10px;color:{c['text_muted']};">Mora: </span>
                <span style="font-size:11px;color:{c['text_secondary']};font-weight:500;">
                    {overdue_days}d · ${amount:,.0f}</span>
            </div>
            <div>
                <span style="font-size:10px;color:{c['text_muted']};">Acción tomada: </span>
                <span style="font-size:11px;color:{c['text_primary']};font-weight:500;">
                    {action_label}</span>
            </div>
            {f'<div><span style="font-size:10px;color:{c["text_muted"]};">Fecha: </span><span style="font-size:11px;color:{c["text_secondary"]};">{time_ago(created)}</span></div>' if created else ''}
        </div>
    </div>
    """, unsafe_allow_html=True)


def _action_label(action: str) -> str:
    _LABELS = {
        "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA": "Activar póliza",
        "INICIAR_DEMANDA_DE_RESTITUCIÓN":          "Iniciar restitución",
        "PROPONER_ACUERDO_DE_PAGO":                "Acuerdo de pago",
        "COBRAR_PENALIDAD_CONTRACTUAL":            "Cobrar penalidad",
        "ENVIAR_RECORDATORIO_DE_PAGO":             "Recordatorio de pago",
        "REVISAR_MANUALMENTE":                     "Revisión manual",
    }
    return _LABELS.get(action, action.replace("_", " ").capitalize())


def _hex_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
    return "128,128,128"
