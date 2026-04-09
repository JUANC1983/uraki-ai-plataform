# dashboard/components/intelligence_panel.py
"""
Intelligence Panel — shown inside the decision card for every case.

Renders four sections:
  1. Context package   — executive summary + risk summary + next step
  2. Quality scores    — quality_score + confidence_score bars
  3. Proactive alerts  — high-risk detections, pattern warnings, suggestions
  4. Automation badge  — whether this decision is automatable (display only)

All computations are client-side — no extra API round-trip required.
Backend-enhanced suggestions are fetched if the /intelligence/suggestions endpoint exists.
"""
from __future__ import annotations

import streamlit as st
import core.state_manager as sm
from styles.theme import COLORS
from services.intelligence_service import (
    build_context_package,
    get_proactive_suggestions,
    compute_quality_score,
    compute_automation_tags,
)

_PRIORITY_STYLES: dict[str, tuple[str, str, str]] = {
    # priority → (icon, border_color, bg_color)
    "critical": ("⛔", "#EF4444", "rgba(239,68,68,0.07)"),
    "high":     ("⚠",  "#F59E0B", "rgba(245,158,11,0.07)"),
    "medium":   ("ℹ",  "#3B82F6", "rgba(59,130,246,0.07)"),
    "low":      ("·",  "#6B7280", "rgba(107,114,128,0.05)"),
}

_FLAG_OPTIONS = [
    "Acción incorrecta",
    "Nivel de riesgo incorrecto",
    "Clasificación errónea",
    "Razón poco clara",
    "Recomendación inapropiada",
]


def render(case: dict, decision: dict | None) -> None:
    """Render the full intelligence panel for a case."""
    c = COLORS

    # Build context package (always)
    ctx = build_context_package(case, decision)

    # ── Context package section ────────────────────────────────────────────────
    _render_context_package(ctx, c)

    # ── Quality scores ─────────────────────────────────────────────────────────
    if decision:
        _render_quality_scores(ctx["quality"], c)

    # ── Proactive suggestions ──────────────────────────────────────────────────
    suggestions = get_proactive_suggestions(case, decision)
    if suggestions:
        _render_proactive_suggestions(suggestions, c)

    # ── Automation readiness badge ─────────────────────────────────────────────
    if decision:
        _render_automation_badge(ctx["automation"], ctx.get("structured_output", {}), c)

    # ── Response feedback ──────────────────────────────────────────────────────
    if decision:
        _render_response_feedback(case, decision, c)


# ── Context package ────────────────────────────────────────────────────────────

def _render_context_package(ctx: dict, c: dict) -> None:
    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};
        border:1px solid {c['border_subtle']};
        border-left:3px solid {c['accent']};
        border-radius:8px;padding:0.75rem 1rem;
        margin-bottom:0.6rem;
    ">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.5rem;">Resumen ejecutivo</div>
        <div style="font-size:12px;color:{c['text_primary']};line-height:1.6;
            margin-bottom:0.6rem;">
            {ctx['executive_summary']}
        </div>
        <div style="font-size:11px;color:{c['text_secondary']};
            padding:5px 8px;background:{c['bg_secondary']};
            border-radius:5px;margin-bottom:0.5rem;">
            {ctx['risk_summary']}
        </div>
        <div style="display:flex;align-items:flex-start;gap:6px;">
            <span style="font-size:10px;color:{c['text_muted']};
                text-transform:uppercase;letter-spacing:0.06em;
                white-space:nowrap;padding-top:1px;">Siguiente paso:</span>
            <span style="font-size:12px;color:{c['accent']};font-weight:600;
                line-height:1.4;">{ctx['next_step']}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Quality scores ─────────────────────────────────────────────────────────────

def _render_quality_scores(quality: dict, c: dict) -> None:
    q_score  = quality.get("quality_score", 0)
    q_label  = quality.get("quality_label", "—")
    q_color  = quality.get("quality_color", c["text_muted"])
    conf_pct = quality.get("confidence_score", 0)
    conf_lbl = quality.get("confidence_label", "—")

    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:8px;padding:0.65rem 1rem;margin-bottom:0.6rem;
    ">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.5rem;">Calidad de respuesta</div>
        <div style="display:flex;gap:1.5rem;align-items:center;flex-wrap:wrap;">

            <!-- Quality score -->
            <div style="flex:1;min-width:120px;">
                <div style="display:flex;justify-content:space-between;
                    align-items:baseline;margin-bottom:3px;">
                    <span style="font-size:11px;color:{c['text_secondary']};">
                        Calidad</span>
                    <span style="font-size:13px;color:{q_color};font-weight:700;">
                        {q_score}/100
                        <span style="font-size:10px;font-weight:400;
                            color:{c['text_muted']};"> {q_label}</span>
                    </span>
                </div>
                <div style="height:4px;background:{c['bg_secondary']};
                    border-radius:2px;overflow:hidden;">
                    <div style="width:{q_score}%;height:100%;
                        background:linear-gradient(90deg,{q_color}88,{q_color});
                        border-radius:2px;transition:width 0.4s ease;"></div>
                </div>
            </div>

            <!-- Confidence score -->
            <div style="flex:1;min-width:120px;">
                <div style="display:flex;justify-content:space-between;
                    align-items:baseline;margin-bottom:3px;">
                    <span style="font-size:11px;color:{c['text_secondary']};">
                        Confianza</span>
                    <span style="font-size:13px;color:{c['text_primary']};
                        font-weight:700;">
                        {conf_pct}%
                        <span style="font-size:10px;font-weight:400;
                            color:{c['text_muted']};"> {conf_lbl}</span>
                    </span>
                </div>
                <div style="height:4px;background:{c['bg_secondary']};
                    border-radius:2px;overflow:hidden;">
                    <div style="width:{conf_pct}%;height:100%;
                        background:linear-gradient(90deg,#6366F188,#6366F1);
                        border-radius:2px;transition:width 0.4s ease;"></div>
                </div>
            </div>

        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Proactive suggestions ──────────────────────────────────────────────────────

def _render_proactive_suggestions(suggestions: list[dict], c: dict) -> None:
    # Show critical + high inline; collapse medium + low
    critical_high = [s for s in suggestions if s.get("priority") in ("critical", "high")]
    medium_low    = [s for s in suggestions if s.get("priority") in ("medium", "low")]

    for s in critical_high:
        _render_suggestion_card(s, c)

    if medium_low:
        with st.expander(
            f"ℹ {len(medium_low)} sugerencia{'s' if len(medium_low) != 1 else ''} adicional{'es' if len(medium_low) != 1 else ''}",
            expanded=False,
        ):
            for s in medium_low:
                _render_suggestion_card(s, c)


def _render_suggestion_card(s: dict, c: dict) -> None:
    icon, border, bg = _PRIORITY_STYLES.get(
        s.get("priority", "low"), _PRIORITY_STYLES["low"]
    )
    title       = s.get("title", "")
    body        = s.get("body", "")
    action_hint = s.get("action_hint", "")

    st.markdown(f"""
    <div style="
        background:{bg};border:1px solid {border}55;
        border-left:3px solid {border};
        border-radius:6px;padding:0.6rem 0.85rem;margin-bottom:0.4rem;
    ">
        <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:3px;">
            <span style="font-size:13px;">{icon}</span>
            <span style="font-size:12px;font-weight:600;color:{border};">
                {title}</span>
        </div>
        <div style="font-size:11px;color:{c['text_secondary']};
            line-height:1.5;margin-bottom:{'4px' if action_hint else '0'};">
            {body}
        </div>
        {f'<div style="font-size:11px;color:{c["text_muted"]};font-style:italic;">→ {action_hint}</div>' if action_hint else ''}
    </div>
    """, unsafe_allow_html=True)


# ── Automation badge ───────────────────────────────────────────────────────────

def _render_automation_badge(automation: dict, structured_output: dict, c: dict) -> None:
    automatable = automation.get("automatable", False)
    block       = automation.get("automation_block")

    if automatable:
        badge_color = "#22C55E"
        badge_bg    = "rgba(34,197,94,0.08)"
        badge_text  = "✓ Automatizable"
        badge_desc  = "Esta decisión cumple todos los criterios para ejecución automática futura."
    else:
        badge_color = "#6B7280"
        badge_bg    = "rgba(107,114,128,0.06)"
        badge_text  = "⊘ No automatizable"
        badge_desc  = block or "Requiere revisión humana."

    st.markdown(f"""
    <div style="
        background:{badge_bg};border:1px solid {badge_color}33;
        border-radius:6px;padding:0.5rem 0.85rem;margin-bottom:0.6rem;
        display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px;
    ">
        <div>
            <span style="font-size:11px;font-weight:600;color:{badge_color};">
                🤖 {badge_text}</span>
            <div style="font-size:10px;color:{c['text_muted']};margin-top:2px;">
                {badge_desc}</div>
        </div>
        <span style="font-size:10px;color:{c['text_muted']};font-style:italic;">
            Modo: solo visualización</span>
    </div>
    """, unsafe_allow_html=True)

    if automatable and structured_output:
        import json
        with st.expander("Ver salida estructurada para automatización", expanded=False):
            st.markdown(f"""
            <div style="font-size:10px;color:{c['text_muted']};margin-bottom:0.4rem;">
                Esta salida estructurada será consumida por el motor de automatización
                cuando se habilite. No ejecuta nada actualmente.</div>
            """, unsafe_allow_html=True)
            st.code(
                json.dumps(structured_output, ensure_ascii=False, indent=2),
                language="json",
            )


# ── Response feedback ──────────────────────────────────────────────────────────

def _render_response_feedback(case: dict, decision: dict, c: dict) -> None:
    """
    Compact operator rating widget. Submitted once per decision per session.
    """
    decision_id = decision.get("id", "")
    state_key   = f"_feedback_submitted_{decision_id}"

    if st.session_state.get(state_key):
        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_muted']};
            text-align:center;padding:4px 0;">
            ✓ Feedback registrado — gracias por tu valoración.</div>
        """, unsafe_allow_html=True)
        return

    with st.expander("⭐ Valorar esta respuesta", expanded=False):
        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_muted']};margin-bottom:0.5rem;">
            Tu valoración ayuda al sistema a mejorar su precisión.
            Califica la calidad de esta decisión del motor de reglas.</div>
        """, unsafe_allow_html=True)

        rating = st.select_slider(
            "Calificación",
            options=[1, 2, 3, 4, 5],
            value=4,
            format_func=lambda v: {1: "⭐ Muy mala", 2: "⭐⭐ Mala", 3: "⭐⭐⭐ Regular",
                                   4: "⭐⭐⭐⭐ Buena", 5: "⭐⭐⭐⭐⭐ Excelente"}[v],
            key=f"feedback_rating_{decision_id}",
        )

        flags = st.multiselect(
            "¿Qué estuvo mal? (opcional)",
            options=_FLAG_OPTIONS,
            key=f"feedback_flags_{decision_id}",
        )

        comment = st.text_input(
            "Comentario adicional (opcional)",
            key=f"feedback_comment_{decision_id}",
            placeholder="Describe brevemente el problema...",
        )

        if st.button("Enviar valoración", key=f"feedback_submit_{decision_id}",
                     use_container_width=True):
            from services.intelligence_service import ResponseFeedbackService
            err = ResponseFeedbackService().submit_rating(
                decision_id=decision_id,
                case_id=case.get("id", ""),
                rating=rating,
                flags=flags,
                comment=comment,
            )
            st.session_state[state_key] = True
            if err:
                sm.flash_error(f"Error al enviar feedback: {err}")
            else:
                sm.flash_success("Valoración registrada")
            st.rerun()
