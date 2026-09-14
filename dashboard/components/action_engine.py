# dashboard/components/action_engine.py
"""
Action Engine — execute post-decision actions from the UI.

Actions: Send Email · Assign Task · Notify Stakeholders
Each action has a preview step before confirmation.
Execution status is tracked and shown inline.
"""
from __future__ import annotations

import streamlit as st
import core.state_manager as sm
from core.auth import has_permission
from styles.theme import COLORS
from services.action_service import ActionService


def render(case: dict, decision: dict | None) -> None:
    """
    Render the action engine panel as an expander.
    Role-gated: requires 'escalate' permission minimum.
    Feature-flagged: requires action_engine to be enabled for this tenant.
    """
    from core.feature_flags import flag_gate
    if not flag_gate("action_engine", "Motor de acciones no habilitado para este tenant."):
        return

    if not has_permission("escalate"):
        return

    c = COLORS

    with st.expander("⚡ Motor de acciones — ejecutar decisión", expanded=False):
        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_muted']};
            padding:0 0 0.75rem;line-height:1.6;">
            Ejecuta acciones directamente desde esta interfaz.
            Cada acción queda registrada en el historial de auditoría.
        </div>
        """, unsafe_allow_html=True)

        # Show previously executed actions
        _render_action_history(case, c)

        tab_email, tab_task, tab_notify = st.tabs(["📧 Email", "✏ Tarea", "🔔 Notificar"])

        with tab_email:
            _render_email_action(case, decision, c)

        with tab_task:
            _render_task_action(case, c)

        with tab_notify:
            _render_notify_action(case, decision, c)


# ── Email action ──────────────────────────────────────────────────────────────

def _render_email_action(case: dict, decision: dict | None, c: dict) -> None:
    st.markdown(f"""
    <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
        letter-spacing:0.08em;margin-bottom:0.5rem;">Enviar correo al cliente</div>
    """, unsafe_allow_html=True)

    suggested_msg = (decision.get("suggested_message", "") if decision else "").strip()

    recipient = st.text_input(
        "Destinatario",
        value=case.get("client_email", ""),
        placeholder="resident@example.com",
        key=f"email_recipient_{case['id']}",
    )
    subject = st.text_input(
        "Asunto",
        value=f"Notificación de mora — {case.get('contract_id','—')}",
        key=f"email_subject_{case['id']}",
    )
    body = st.text_area(
        "Cuerpo del mensaje",
        value=suggested_msg,
        height=150,
        key=f"email_body_{case['id']}",
        help="Pre-cargado con el mensaje sugerido por la IA. Puedes editarlo.",
    )

    ready = bool(recipient.strip() and subject.strip() and body.strip())

    col_btn, col_warn = st.columns([1, 2])
    with col_btn:
        if st.button(
            "📧 Enviar correo",
            key=f"send_email_{case['id']}",
            disabled=not ready,
            use_container_width=True,
        ):
            with st.spinner("Enviando correo..."):
                result, err = ActionService().send_email(
                    case_id=case["id"],
                    recipient=recipient.strip(),
                    subject=subject.strip(),
                    body=body.strip(),
                )
            if err:
                sm.flash_error(f"Error al enviar correo: {err}")
                st.error(f"Error: {err}")
            else:
                action_id = (result or {}).get("action_id", "?")
                sm.flash_success(f"Correo enviado · ID: {action_id}")
                st.success(f"Correo enviado correctamente. ID: {action_id}")
                from services.event_service import emit_action_sent
                emit_action_sent(case["id"], "sent_email", action_id)
    with col_warn:
        if not ready:
            st.markdown(f"""
            <div style="font-size:11px;color:{c['text_muted']};padding-top:0.6rem;">
                Completa todos los campos para habilitar el envío.
            </div>""", unsafe_allow_html=True)


# ── Task action ───────────────────────────────────────────────────────────────

def _render_task_action(case: dict, c: dict) -> None:
    st.markdown(f"""
    <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
        letter-spacing:0.08em;margin-bottom:0.5rem;">Asignar tarea de seguimiento</div>
    """, unsafe_allow_html=True)

    assignee = st.text_input(
        "Asignar a",
        placeholder="operator@example.com",
        key=f"task_assignee_{case['id']}",
    )
    title = st.text_input(
        "Título de la tarea",
        value=f"Seguimiento caso {case['id']}",
        key=f"task_title_{case['id']}",
    )
    description = st.text_area(
        "Descripción",
        placeholder="Describe los pasos a seguir...",
        height=90,
        key=f"task_desc_{case['id']}",
    )
    due_date = st.date_input(
        "Fecha límite (opcional)",
        value=None,
        key=f"task_due_{case['id']}",
    )

    ready = bool(assignee.strip() and title.strip() and description.strip())

    if st.button(
        "✏ Crear tarea",
        key=f"create_task_{case['id']}",
        disabled=not ready,
        use_container_width=True,
    ):
        due_str = str(due_date) if due_date else None
        with st.spinner("Creando tarea..."):
            result, err = ActionService().assign_task(
                case_id=case["id"],
                assignee=assignee.strip(),
                title=title.strip(),
                description=description.strip(),
                due_date=due_str,
            )
        if err:
            st.error(f"Error: {err}")
        else:
            task_id = (result or {}).get("task_id", "?")
            sm.flash_success(f"Tarea creada · ID: {task_id}")
            st.success(f"Tarea creada. ID: {task_id}")
            from services.event_service import emit_action_sent
            emit_action_sent(case["id"], "assigned_task", task_id)


# ── Notify action ─────────────────────────────────────────────────────────────

def _render_notify_action(case: dict, decision: dict | None, c: dict) -> None:
    st.markdown(f"""
    <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
        letter-spacing:0.08em;margin-bottom:0.5rem;">Notificar stakeholders</div>
    """, unsafe_allow_html=True)

    channel = st.selectbox(
        "Canal",
        options=["email", "slack", "webhook"],
        format_func=lambda x: {"email": "📧 Correo", "slack": "💬 Slack", "webhook": "🔗 Webhook"}[x],
        key=f"notify_channel_{case['id']}",
    )
    message = st.text_area(
        "Mensaje",
        value=(
            f"Alerta: Caso {case['id']} — {case.get('client_name','—')} — "
            f"{case.get('overdue_days',0)} días de mora. "
            f"Acción recomendada: {(decision or {}).get('action_label','—')}."
        ),
        height=100,
        key=f"notify_msg_{case['id']}",
    )

    if st.button(
        "🔔 Enviar notificación",
        key=f"send_notify_{case['id']}",
        disabled=not message.strip(),
        use_container_width=True,
    ):
        with st.spinner("Enviando notificación..."):
            result, err = ActionService().notify_stakeholders(
                case_id=case["id"],
                channel=channel,
                message=message.strip(),
            )
        if err:
            st.error(f"Error: {err}")
        else:
            sm.flash_success(f"Notificación enviada por {channel}")
            st.success(f"Notificación enviada por {channel}.")
            from services.event_service import emit_action_sent
            emit_action_sent(case["id"], "notified", (result or {}).get("action_id", ""))


# ── Action history ─────────────────────────────────────────────────────────────

def _render_action_history(case: dict, c: dict) -> None:
    """Show recently executed actions for this case."""
    actions, err = ActionService().get_case_actions(case["id"])
    if err or not actions:
        return

    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.75rem;">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.5rem;">
            Acciones ejecutadas ({len(actions)})</div>
    """, unsafe_allow_html=True)

    for action in actions[:5]:
        atype   = action.get("action_type", "—")
        status  = action.get("status", "—")
        created = action.get("created_at", "")
        s_color = "#22C55E" if status == "sent" else "#EF4444" if status == "failed" else "#F59E0B"

        st.markdown(f"""
        <div style="display:flex;justify-content:space-between;align-items:center;
            padding:3px 0;border-bottom:1px solid {c['border_subtle']};">
            <span style="font-size:11px;color:{c['text_secondary']};">{atype}</span>
            <div style="display:flex;gap:8px;align-items:center;">
                <span style="font-size:10px;color:{s_color};font-weight:500;">{status}</span>
                <span style="font-size:10px;color:{c['text_muted']};">
                    {created[:10] if created else '—'}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
