# dashboard/operational.py
"""
URAKI AI — Operational Dashboard (Streamlit)

For: operadores, legal
Shows: case queue, risk distribution, decision details, override UI
Run: streamlit run dashboard/operational.py
"""
import os
from typing import Optional

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login(email: str, password: str) -> Optional[str]:
    try:
        resp = requests.post(
            f"{API_BASE}/auth/login",
            data={"username": email, "password": password},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()["access_token"]
    except Exception:
        pass
    return None


def api_get(path: str, token: str) -> Optional[dict]:
    try:
        resp = requests.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.ok:
            return resp.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
    return None


def api_post(path: str, token: str, data: dict) -> Optional[dict]:
    try:
        resp = requests.post(
            f"{API_BASE}{path}",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.ok:
            return resp.json()
        st.error(f"API {resp.status_code}: {resp.text}")
    except Exception as exc:
        st.error(f"API error: {exc}")
    return None


# ---------------------------------------------------------------------------
# Priority badge
# ---------------------------------------------------------------------------

PRIORITY_COLOR = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "MEDIUM": "🟡",
    "LOW": "🟢",
}

RISK_COLOR = {
    "ALTO": "🔴",
    "MEDIO": "🟡",
    "BAJO": "🟢",
}


# ---------------------------------------------------------------------------
# Page: Login
# ---------------------------------------------------------------------------

def page_login() -> None:
    st.title("URAKI AI Platform")
    st.subheader("Iniciar sesión")

    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Ingresar")

    if submitted:
        token = login(email, password)
        if token:
            st.session_state["token"] = token
            st.session_state["email"] = email
            st.rerun()
        else:
            st.error("Credenciales incorrectas")


# ---------------------------------------------------------------------------
# Page: Case Queue
# ---------------------------------------------------------------------------

def page_case_queue(token: str) -> None:
    st.header("Cola de Trabajo")

    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.selectbox(
            "Estado",
            ["", "NEW", "IN_REVIEW", "DECISION_GENERATED", "ESCALATED"],
            index=0,
        )
    with col2:
        priority_filter = st.selectbox(
            "Prioridad",
            ["", "CRITICAL", "HIGH", "MEDIUM", "LOW"],
            index=0,
        )
    with col3:
        limit = st.number_input("Casos a mostrar", min_value=5, max_value=200, value=50)

    params = f"?limit={limit}"
    if status_filter:
        params += f"&status={status_filter}"

    data = api_get(f"/cases{params}", token)
    if not data:
        st.warning("No se pudieron cargar los casos")
        return

    cases = data.get("items", [])
    st.caption(f"Total: {data.get('total', 0)} casos")

    if priority_filter:
        cases = [c for c in cases if c.get("priority") == priority_filter]

    if not cases:
        st.info("No hay casos con estos filtros")
        return

    for case in cases:
        priority = case.get("priority") or "—"
        badge = PRIORITY_COLOR.get(priority, "⚪")
        decision = case.get("decision") or {}
        risk_level = decision.get("risk_level", "—")
        risk_badge = RISK_COLOR.get(risk_level, "⚪")

        with st.expander(
            f"{badge} {case['client_name']} | {case['case_type']} | "
            f"{case['overdue_days']}d mora | {risk_badge} {risk_level}"
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Días mora", case["overdue_days"])
            c2.metric("Monto mora", f"${case['overdue_amount']:,.0f}")
            c3.metric("Prioridad", priority)
            c4.metric("Riesgo", f"{decision.get('risk_score', '—')}")

            if decision:
                st.markdown(f"**Acción:** `{decision.get('action', '—')}`")
                st.markdown(f"**Justificación:** {decision.get('rationale', '—')}")
                if decision.get("escalation_required"):
                    st.warning(f"⚠ Escalamiento → {decision.get('escalation_target')}")
                if decision.get("legal_flag"):
                    st.error("⚖ Alerta legal activa")

            col_a, col_b, col_c = st.columns(3)

            if col_a.button("▶ Evaluar", key=f"eval_{case['id']}"):
                result = api_post(f"/cases/{case['id']}/evaluate", token, {})
                if result:
                    st.success(f"Decisión: {result.get('decision')}")
                    st.json({
                        "Riesgo": result.get("risk"),
                        "Prioridad": result.get("priority"),
                        "Próximo paso": result.get("next_action"),
                        "Regla aplicada": result.get("rule_applied"),
                    })
                    st.markdown(f"**Explicación completa:**\n```\n{result.get('explain')}\n```")
                    st.rerun()

            if decision and col_b.button("✏ Override", key=f"override_{case['id']}"):
                st.session_state["override_case_id"] = case["id"]
                st.session_state["override_decision_id"] = (
                    decision.get("id") or ""
                )
                st.session_state["page"] = "override"
                st.rerun()

            if col_c.button("→ Ver detalle", key=f"detail_{case['id']}"):
                st.session_state["selected_case_id"] = case["id"]
                st.session_state["page"] = "case_detail"
                st.rerun()


# ---------------------------------------------------------------------------
# Page: Case Detail
# ---------------------------------------------------------------------------

def page_case_detail(token: str, case_id: str) -> None:
    if st.button("← Volver"):
        st.session_state["page"] = "queue"
        st.rerun()

    data = api_get(f"/cases/{case_id}", token)
    if not data:
        st.error("Caso no encontrado")
        return

    st.header(f"Caso: {data['client_name']}")
    st.caption(f"ID: {case_id} | Estado: {data['status']} | Prioridad: {data.get('priority')}")

    with st.expander("Datos del caso", expanded=True):
        col1, col2 = st.columns(2)
        col1.markdown(f"**Tipo:** {data['case_type']}")
        col1.markdown(f"**Contrato:** {data.get('contract_id', '—')}")
        col1.markdown(f"**Propiedad:** {data.get('property_address', '—')}")
        col2.metric("Días mora", data["overdue_days"])
        col2.metric("Monto mora", f"${data['overdue_amount']:,.0f}")
        col2.metric("Renta mensual", f"${data['monthly_rent']:,.0f}")

    decision = data.get("latest_decision")
    if decision:
        st.subheader("Última decisión")
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        col1.metric("Acción", decision["action"])
        col2.metric("Riesgo", f"{decision['risk_score']:.1f} / {decision['risk_level']}")
        col3.metric("Prioridad", decision.get("priority", "—"))

        st.markdown(f"**Por qué:** {decision['rationale']}")
        if decision.get("rule_id_applied"):
            st.caption(
                f"Regla: `{decision['rule_id_applied']}` v{decision.get('rule_version_used')}"
            )

        if decision.get("document_references"):
            st.subheader("Evidencia documental")
            for ref in decision["document_references"]:
                with st.expander(f"Cláusula: {ref.get('clause_id', 'N/A')}"):
                    st.markdown(f"> {ref.get('snippet', '')}")
                    st.caption(f"Relevancia: {ref.get('relevance', '—')}")

        if decision.get("suggested_message"):
            st.subheader("Mensaje sugerido")
            st.text_area("", value=decision["suggested_message"], height=150, disabled=True)

    transitions = data.get("allowed_transitions", [])
    if transitions:
        st.subheader("Transición de estado")
        target = st.selectbox("Nuevo estado", transitions)
        if st.button("Cambiar estado"):
            result = api_post(
                f"/cases/{case_id}/transition",
                token,
                {"target_status": target},
            )
            if result:
                st.success(f"Estado actualizado: {result.get('status')}")
                st.rerun()


# ---------------------------------------------------------------------------
# Page: Override
# ---------------------------------------------------------------------------

def page_override(token: str) -> None:
    case_id = st.session_state.get("override_case_id", "")
    decision_id = st.session_state.get("override_decision_id", "")

    st.header("Override de Decisión")
    st.caption(f"Caso: {case_id} | Decisión: {decision_id}")

    if st.button("← Volver"):
        st.session_state["page"] = "queue"
        st.rerun()

    with st.form("override_form"):
        new_action = st.text_input("Nueva acción")
        reason = st.text_area("Motivo del override (obligatorio)")
        submitted = st.form_submit_button("Aplicar Override")

    if submitted:
        if not new_action or not reason:
            st.error("Acción y motivo son obligatorios")
            return
        result = api_post(
            f"/decisions/{decision_id}/override",
            token,
            {"overridden_action": new_action, "reason": reason},
        )
        if result:
            st.success("Override aplicado correctamente")
            st.json(result)
            st.session_state["page"] = "queue"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="URAKI AI — Operativo",
        page_icon="⚖",
        layout="wide",
    )

    if "token" not in st.session_state:
        page_login()
        return

    token = st.session_state["token"]

    with st.sidebar:
        st.title("URAKI AI")
        st.caption(f"Usuario: {st.session_state.get('email', '')}")
        page = st.radio(
            "Navegación",
            ["Cola de trabajo", "Crear caso"],
            key="nav",
        )
        if st.button("Cerrar sesión"):
            st.session_state.clear()
            st.rerun()

    current_page = st.session_state.get("page", "queue")

    if current_page == "case_detail":
        page_case_detail(token, st.session_state["selected_case_id"])
    elif current_page == "override":
        page_override(token)
    elif page == "Crear caso":
        _page_create_case(token)
    else:
        page_case_queue(token)


def _page_create_case(token: str) -> None:
    st.header("Crear Nuevo Caso")
    with st.form("create_case"):
        client_name = st.text_input("Nombre del arrendatario *")
        case_type = st.selectbox("Tipo de caso", ["mora", "disputa", "abandono", "poliza"])
        overdue_days = st.number_input("Días de mora", min_value=0, value=0)
        overdue_amount = st.number_input("Monto adeudado", min_value=0.0, value=0.0)
        monthly_rent = st.number_input("Renta mensual", min_value=0.0, value=0.0)
        contract_id = st.text_input("ID de contrato")
        property_address = st.text_input("Dirección del inmueble")
        submitted = st.form_submit_button("Crear caso")

    if submitted:
        if not client_name:
            st.error("El nombre del arrendatario es obligatorio")
            return
        result = api_post(
            "/cases",
            token,
            {
                "client_name": client_name,
                "case_type": case_type,
                "overdue_days": int(overdue_days),
                "overdue_amount": float(overdue_amount),
                "monthly_rent": float(monthly_rent),
                "contract_id": contract_id or None,
                "property_address": property_address or None,
            },
        )
        if result:
            st.success(f"Caso creado: {result.get('id')}")
            st.session_state["page"] = "queue"


if __name__ == "__main__":
    main()
