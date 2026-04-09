# dashboard/components/simulation_panel.py
"""
Simulation Mode — premium "what-if" panel.

Lets operators modify case inputs and re-run the decision engine without
persisting any changes. Shows the simulated decision side-by-side with
the current real decision for instant comparison.

Requires the backend to expose: POST /cases/{id}/simulate
"""
from __future__ import annotations

import streamlit as st
import core.state_manager as sm
from styles.theme import COLORS, RISK_COLORS, PRIORITY_COLORS
from services.case_service import CaseService
from services.decision_service import DecisionService, ACTION_LABELS
from utils.formatters import fmt_currency


def render(case: dict, current_decision: dict | None) -> None:
    """
    Render the simulation panel as a full-width expander below the decision card.
    Only shown when the user explicitly opens it.
    """
    from core.feature_flags import flag_gate
    if not flag_gate("simulation_mode", "Modo simulación no habilitado para este tenant."):
        return

    c = COLORS

    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};
        border:1px solid rgba(99,102,241,0.3);
        border-radius:10px;
        padding:0 0.75rem;
        margin-top:0.5rem;
    ">
    """, unsafe_allow_html=True)

    with st.expander("⚗ Simular decisión — modo what-if", expanded=sm.get("simulation_open", False)):
        sm.set("simulation_open", True)

        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_muted']};
            padding:0.25rem 0 0.75rem;line-height:1.6;">
            Modifica los parámetros del caso y ejecuta el motor de reglas de forma simulada.
            Los cambios <strong style="color:{c['text_secondary']};">no se guardan</strong> —
            son solo para explorar decisiones alternativas.
        </div>
        """, unsafe_allow_html=True)

        col_inputs, col_results = st.columns([1, 1.1])

        # ── Left: input controls ───────────────────────────────────────
        with col_inputs:
            st.markdown(f"""
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:0.5rem;">Parámetros a modificar</div>
            """, unsafe_allow_html=True)

            sim_days = st.number_input(
                "Días de mora",
                min_value=0,
                max_value=730,
                value=int(case.get("overdue_days", 30)),
                step=10,
                key=f"sim_days_{case['id']}",
            )

            sim_amount = st.number_input(
                "Monto vencido (COP)",
                min_value=0,
                max_value=100_000_000,
                value=int(case.get("overdue_amount", 0)),
                step=100_000,
                format="%d",
                key=f"sim_amount_{case['id']}",
            )

            sim_policy = st.checkbox(
                "Póliza activa",
                value=bool(case.get("has_policy", False)),
                key=f"sim_policy_{case['id']}",
            )

            sim_legal = st.checkbox(
                "Acción legal en curso",
                value=bool(case.get("has_legal_action", False)),
                key=f"sim_legal_{case['id']}",
            )

            sim_prev = st.number_input(
                "Incidentes previos",
                min_value=0,
                max_value=20,
                value=int(case.get("previous_overdue_count", 0)),
                key=f"sim_prev_{case['id']}",
            )

            st.markdown('<div class="uraki-btn-primary" style="margin-top:0.5rem;">',
                        unsafe_allow_html=True)
            run_btn = st.button(
                "⚗ Ejecutar simulación",
                key=f"run_sim_{case['id']}",
                use_container_width=True,
            )
            st.markdown('</div>', unsafe_allow_html=True)

            if run_btn:
                overrides = {
                    "overdue_days":            sim_days,
                    "overdue_amount":          sim_amount,
                    "has_policy":              sim_policy,
                    "has_legal_action":        sim_legal,
                    "previous_overdue_count":  sim_prev,
                }
                from services.event_service import emit_simulation_run
                emit_simulation_run(case["id"], overrides)
                with st.spinner("Ejecutando motor de reglas en modo simulación..."):
                    result, err = CaseService().simulate(case["id"], overrides)

                if err:
                    sm.set("simulation_result", None)
                    st.error(f"Error en simulación: {err}")
                else:
                    ds = DecisionService()
                    sm.set("simulation_result", ds._normalize_eval(result))
                    sm.set("simulation_case_id", case["id"])

        # ── Right: comparison ──────────────────────────────────────────
        with col_results:
            sim_result = sm.get("simulation_result")
            if sm.get("simulation_case_id") != case["id"]:
                sim_result = None

            if sim_result is None:
                st.markdown(f"""
                <div style="
                    text-align:center;padding:2rem 1rem;
                    border:1px dashed {c['border_default']};
                    border-radius:8px;height:100%;
                    display:flex;flex-direction:column;
                    align-items:center;justify-content:center;
                ">
                    <div style="font-size:24px;margin-bottom:0.5rem;">⚗</div>
                    <div style="font-size:12px;color:{c['text_muted']};">
                        Los resultados aparecerán aquí
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                _render_comparison(current_decision, sim_result, c)

    st.markdown('</div>', unsafe_allow_html=True)


def _render_comparison(
    current: dict | None,
    simulated: dict,
    c: dict,
) -> None:
    """Side-by-side delta view of current vs simulated decision."""

    def _card(label: str, decision: dict | None, is_sim: bool) -> str:
        if decision is None:
            return f"""
            <div style="padding:0.6rem;text-align:center;
                border:1px solid {c['border_subtle']};border-radius:8px;">
                <span style="font-size:11px;color:{c['text_muted']};">Sin decisión actual</span>
            </div>"""
        action  = decision.get("action_label", decision.get("action", "—"))
        risk    = decision.get("risk_level", "—")
        score   = decision.get("risk_score", 0)
        r_color = RISK_COLORS.get(risk, c["text_muted"])
        border  = "rgba(99,102,241,0.4)" if is_sim else c["border_subtle"]
        bg      = "rgba(99,102,241,0.05)" if is_sim else c["bg_card"] if hasattr(c, "bg_card") else c["bg_elevated"]
        return f"""
        <div style="background:{bg};border:1px solid {border};
            border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.4rem;">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:4px;">{label}</div>
            <div style="font-size:12px;font-weight:600;color:{c['text_primary']};
                margin-bottom:4px;line-height:1.3;">{action}</div>
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="font-size:11px;color:{r_color};font-weight:500;">{risk}</span>
                <span style="font-size:11px;color:{c['text_muted']};">{score:.0f}/100</span>
            </div>
        </div>"""

    # Detect changes
    action_changed = (
        current is not None
        and current.get("action") != simulated.get("action")
    )
    risk_changed = (
        current is not None
        and current.get("risk_level") != simulated.get("risk_level")
    )

    change_banner = ""
    if action_changed or risk_changed:
        changes = []
        if action_changed:
            changes.append(
                f"Acción: {current.get('action_label','?')} → {simulated.get('action_label','?')}"
            )
        if risk_changed:
            changes.append(
                f"Riesgo: {current.get('risk_level','?')} → {simulated.get('risk_level','?')}"
            )
        change_banner = f"""
        <div style="background:rgba(99,102,241,0.10);border:1px solid rgba(99,102,241,0.25);
            border-radius:6px;padding:0.5rem 0.75rem;margin-bottom:0.5rem;">
            <div style="font-size:10px;color:#818CF8;font-weight:600;
                text-transform:uppercase;letter-spacing:0.06em;margin-bottom:3px;">
                Cambios detectados</div>
            {''.join(f'<div style="font-size:11px;color:{c["text_secondary"]};">{ch}</div>' for ch in changes)}
        </div>"""
    else:
        change_banner = f"""
        <div style="background:rgba(34,197,94,0.07);border:1px solid rgba(34,197,94,0.2);
            border-radius:6px;padding:0.4rem 0.75rem;margin-bottom:0.5rem;">
            <div style="font-size:11px;color:#22C55E;">
                Sin cambios en decisión o nivel de riesgo</div>
        </div>"""

    st.markdown(f"""
    <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
        letter-spacing:0.08em;margin-bottom:0.5rem;">Comparación</div>
    {change_banner}
    {_card("Decisión actual", current, False)}
    {_card("Decisión simulada", simulated, True)}
    """, unsafe_allow_html=True)

    # Rationale diff
    if simulated.get("rationale"):
        with st.expander("Ver razón de la simulación"):
            st.markdown(f"""
            <div style="font-size:12px;color:{c['text_secondary']};
                line-height:1.6;padding:0.25rem 0;">
                {simulated['rationale']}
            </div>
            """, unsafe_allow_html=True)
