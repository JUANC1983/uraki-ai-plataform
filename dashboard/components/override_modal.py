# dashboard/components/override_modal.py
"""
Override Decision UI — expander inside the decision card.
Only visible to roles with 'override' permission (gerente, admin).

After a successful override, records feedback to the feedback registry.
"""
import streamlit as st
import core.state_manager as sm
from core.auth import has_permission, get_user
from services.decision_service import DecisionService, AVAILABLE_ACTIONS, ACTION_LABELS
from services.feedback_service import FeedbackService
from styles.theme import COLORS


def render(case: dict, decision: dict) -> None:
    if not has_permission("override"):
        return

    c           = COLORS
    decision_id = decision.get("id", "")
    is_overridden = decision.get("is_overridden", False)

    override_label = (
        f"⚠ Decisión sobreescrita — razón: {decision.get('override_reason', '—')}"
        if is_overridden
        else "✏ Sobreescribir decisión"
    )

    with st.expander(override_label, expanded=False):
        if is_overridden:
            st.markdown(f"""
            <div style="
                background:rgba(245,158,11,0.08);
                border:1px solid rgba(245,158,11,0.25);
                border-radius:8px;padding:0.75rem;
                font-size:12px;color:{c['warning']};
                margin-bottom:0.75rem;
            ">
                Esta decisión fue sobreescrita manualmente.
                La acción original fue: <strong>{decision.get('original_action', '—')}</strong>
            </div>
            """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_muted']};margin-bottom:0.75rem;">
            El override queda registrado en el log de auditoría y en el registro de feedback
            con tu usuario y razón. No puede revertirse automáticamente.
        </div>
        """, unsafe_allow_html=True)

        current_action = decision.get("action", AVAILABLE_ACTIONS[0])
        action_idx = AVAILABLE_ACTIONS.index(current_action) if current_action in AVAILABLE_ACTIONS else 0

        new_action = st.selectbox(
            label="Nueva acción",
            options=AVAILABLE_ACTIONS,
            format_func=lambda a: ACTION_LABELS.get(a, a),
            index=action_idx,
            key=f"override_action_{decision_id}",
        )

        reason = st.text_area(
            label="Razón del override (obligatorio)",
            placeholder="Explica por qué esta decisión fue cambiada manualmente...",
            key=f"override_reason_{decision_id}",
            height=90,
        )

        col_btn, col_warn = st.columns([1, 2])

        with col_btn:
            st.markdown('<div class="uraki-btn-danger">', unsafe_allow_html=True)
            submit = st.button(
                "Confirmar override",
                key=f"override_submit_{decision_id}",
                use_container_width=True,
                disabled=not reason.strip(),
            )
            st.markdown('</div>', unsafe_allow_html=True)

        with col_warn:
            if not reason.strip():
                st.markdown(f"""
                <div style="font-size:11px;color:{c['text_muted']};
                    padding-top:0.6rem;">Escribe una razón para habilitar.</div>
                """, unsafe_allow_html=True)

        if submit and reason.strip():
            if new_action == current_action:
                st.warning("La acción seleccionada es la misma que la actual. Elige una diferente.")
                return

            ds = DecisionService()
            with st.spinner("Aplicando override..."):
                result, err = ds.override(decision_id, new_action, reason.strip())

            if err:
                st.error(f"Error: {err}")
            else:
                # Record feedback for the rule accuracy registry
                user = get_user()
                FeedbackService().record_feedback(
                    decision_id=decision_id,
                    rule_id=decision.get("rule_id", ""),
                    original_action=current_action,
                    overridden_action=new_action,
                    reason=reason.strip(),
                    operator_id=user.get("email", ""),
                )

                # Emit audit event
                from services.event_service import emit_case_overridden
                emit_case_overridden(
                    case_id=case.get("id", ""),
                    decision_id=decision_id,
                    from_action=current_action,
                    to_action=new_action,
                    reason=reason.strip(),
                )

                sm.flash_success(
                    f"Override aplicado: {ACTION_LABELS.get(new_action, new_action)}"
                )
                from services.api_client import get_client
                token = sm.get("auth_token")
                cache = sm.get("api_cache") or {}
                get_client(token, cache).invalidate(f"/cases/{case.get('id')}")
                get_client(token, cache).invalidate("/cases")
                st.rerun()
