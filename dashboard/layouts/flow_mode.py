# dashboard/layouts/flow_mode.py
"""
Flow Mode — the core operator experience.
3-column layout: Case Queue | Decision Card + Action Bar | Upload + Context
Auto-advances to next case on resolution. Loading skeletons prevent blank states.
"""
import streamlit as st
import core.state_manager as sm
import core.event_bus as bus
from services.case_service import CaseService
from services.decision_service import DecisionService
from services.api_client import BACKEND_CONFIGURED
from components.case_list import render as render_case_list
from components.decision_card import render as render_decision_card
from components.action_bar import render as render_action_bar
from components.upload_box import render as render_upload
from components.loading_skeleton import case_list_skeleton, decision_card_skeleton
from styles.theme import COLORS


def render() -> None:
    c  = COLORS
    cs = CaseService()
    ds = DecisionService()

    # ── Backend down check ──────────────────────────────────────────────
    if not BACKEND_CONFIGURED:
        _render_backend_down(c)
        return

    # ── Load case queue ─────────────────────────────────────────────────
    cases, load_err = cs.get_all()
    if load_err:
        _render_load_error(load_err, c)
        return

    # ── Schema warnings ──────────────────────────────────────────────────
    warnings = sm.consume_schema_warnings()
    if warnings:
        with st.expander(f"⚠ {len(warnings)} advertencia(s) de esquema — datos parciales"):
            for w in warnings:
                st.markdown(f"- `{w}`")

    selected_id = sm.get("selected_case_id")

    # Auto-select first open case if nothing selected
    if not selected_id:
        open_cases = [x for x in cases if x["status"] not in ("CLOSED",)]
        if open_cases:
            sm.select_case(open_cases[0]["id"])
            selected_id = open_cases[0]["id"]
            st.rerun()

    # Load selected case + decision
    selected_case: dict | None = None
    case_err: str | None       = None
    decision:  dict | None     = None

    if selected_id:
        selected_case, case_err = cs.get_by_id(selected_id)
        if not case_err and selected_case:
            decision, _dec_err = ds.get_decision(selected_id)
            from services.event_service import emit_case_viewed
            emit_case_viewed(selected_id)

    # ── 3-column layout ──────────────────────────────────────────────────
    col_left, col_center, col_right = st.columns([1.15, 2.5, 1.1])

    # ── LEFT: Case queue ─────────────────────────────────────────────────
    with col_left:
        st.markdown(
            f'<div style="border-right:1px solid {c["border_subtle"]};'
            f'min-height:100vh;background:{c["bg_secondary"]};">',
            unsafe_allow_html=True,
        )
        if cases:
            render_case_list(cases)
        else:
            case_list_skeleton()
        st.markdown('</div>', unsafe_allow_html=True)

    # ── CENTER: Decision card + action bar ──────────────────────────────
    with col_center:
        st.markdown(
            f'<div style="padding:0 1.25rem;min-height:100vh;background:{c["bg_primary"]};">',
            unsafe_allow_html=True,
        )

        if case_err:
            _render_case_error(case_err, c)
        elif selected_case:
            render_decision_card(selected_case, decision)
            st.markdown('<hr style="margin:0.75rem 0;border-color:#1E1E1E;">',
                        unsafe_allow_html=True)
            render_action_bar(selected_case, decision)
        elif selected_id:
            # ID is set but case not loaded yet — show skeleton
            decision_card_skeleton()
        else:
            _render_empty_state(cases, c)

        st.markdown('</div>', unsafe_allow_html=True)

    # ── RIGHT: Upload + context ──────────────────────────────────────────
    with col_right:
        st.markdown(
            f'<div style="border-left:1px solid {c["border_subtle"]};'
            f'min-height:100vh;background:{c["bg_secondary"]};padding:0 0.75rem;">',
            unsafe_allow_html=True,
        )
        render_upload(selected_case)
        st.markdown('</div>', unsafe_allow_html=True)


# ── Error / empty states ──────────────────────────────────────────────────────

def _render_backend_down(c: dict) -> None:
    st.markdown(f"""
    <div style="
        display:flex;flex-direction:column;align-items:center;justify-content:center;
        min-height:60vh;text-align:center;padding:2rem;
    ">
        <div style="font-size:40px;margin-bottom:1rem;">📡</div>
        <div style="font-size:18px;font-weight:700;color:{c['danger']};
            margin-bottom:0.5rem;">Backend no disponible</div>
        <div style="font-size:13px;color:{c['text_muted']};max-width:320px;line-height:1.6;">
            URAKI_API_URL no está configurado. El sistema no puede operar sin
            conexión al backend de decisiones.
        </div>
    </div>
    """, unsafe_allow_html=True)


def _render_load_error(err: str, c: dict) -> None:
    st.markdown(f"""
    <div style="
        background:rgba(239,68,68,0.06);
        border:1px solid rgba(239,68,68,0.2);
        border-radius:10px;padding:1rem 1.25rem;margin:1rem;
    ">
        <div style="font-size:13px;font-weight:600;color:{c['danger']};margin-bottom:4px;">
            Error al cargar casos</div>
        <div style="font-size:12px;color:{c['text_muted']};line-height:1.6;">{err}</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("↺ Reintentar", key="retry_load"):
        st.rerun()


def _render_case_error(err: str, c: dict) -> None:
    st.error(f"Error al cargar el caso: {err}")
    if st.button("↺ Reintentar", key="retry_case"):
        st.rerun()


def _render_empty_state(cases: list[dict], c: dict) -> None:
    open_cases   = [x for x in cases if x["status"] != "CLOSED"]
    closed_count = sum(1 for x in cases if x["status"] == "CLOSED")

    st.markdown(f"""
    <div style="
        display:flex;flex-direction:column;align-items:center;justify-content:center;
        min-height:60vh;text-align:center;padding:2rem;
        animation:fadeIn 0.3s ease;
    ">
        <div style="
            width:72px;height:72px;
            background:{c['accent_muted']};
            border:1.5px solid {c['border_accent']};
            border-radius:16px;
            display:flex;align-items:center;justify-content:center;
            font-size:28px;margin-bottom:1.25rem;
        ">{'✓' if not open_cases else '⚡'}</div>

        <div style="font-size:18px;font-weight:700;color:{c['text_primary']};
            margin-bottom:0.5rem;">
            {'Todos los casos resueltos' if not open_cases else 'Selecciona un caso'}
        </div>
        <div style="font-size:13px;color:{c['text_muted']};max-width:300px;line-height:1.6;">
            {
                f'Excelente trabajo. {closed_count} caso{"s" if closed_count != 1 else ""} '
                f'cerrado{"s" if closed_count != 1 else ""} en esta sesión.'
                if not open_cases
                else 'Elige un caso de la cola izquierda para comenzar la revisión.'
            }
        </div>
        {f'<div style="margin-top:1.5rem;font-size:12px;color:{c["text_muted"]};">'
          f'{len(open_cases)} caso{"s" if len(open_cases) != 1 else ""} '
          f'pendiente{"s" if len(open_cases) != 1 else ""}</div>'
          if open_cases else ''}
    </div>
    """, unsafe_allow_html=True)
