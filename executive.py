# dashboard/executive.py
"""
URAKI AI — Executive Dashboard (Streamlit)

For: CEO / Gerencia
Shows: KPIs, aging, override rate, risk distribution, event log
Run: streamlit run dashboard/executive.py
"""
import os
from typing import Optional

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")


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
            timeout=15,
        )
        if resp.ok:
            return resp.json()
        st.error(f"API {resp.status_code}")
    except Exception as exc:
        st.error(f"Connection error: {exc}")
    return None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_login() -> None:
    st.title("URAKI AI — Executive")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar"):
            token = login(email, password)
            if token:
                st.session_state["token"] = token
                st.session_state["email"] = email
                st.rerun()
            else:
                st.error("Credenciales incorrectas")


def page_executive(token: str) -> None:
    st.title("Dashboard Ejecutivo")

    # Load data
    exec_data = api_get("/dashboard/executive", token)
    metrics_data = api_get("/dashboard/metrics", token)

    if not exec_data:
        st.warning("No se pudieron cargar los datos ejecutivos")
        return

    cases = exec_data.get("cases", {})
    decisions = exec_data.get("decisions", {})
    overrides = exec_data.get("overrides", {})
    aging = cases.get("aging", {})

    # ---- KPI Row ----
    st.subheader("KPIs Principales")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Casos", cases.get("total_cases", 0))
    k2.metric("Casos Abiertos", cases.get("open_cases", 0))
    k3.metric(
        "Mora Total",
        f"${cases.get('total_overdue_amount', 0):,.0f}",
    )
    k4.metric("Días Mora Promedio", f"{cases.get('avg_overdue_days', 0):.1f}")
    k5.metric("Total Decisiones", decisions.get("total_decisions", 0))

    st.divider()

    # ---- Decisions Row ----
    st.subheader("Gestión de Decisiones")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Escalamientos", decisions.get("escalated", 0))
    d2.metric("Alertas Legales", decisions.get("legal_flags", 0))
    d3.metric("Overrides", decisions.get("overridden", 0))
    d4.metric(
        "Tasa de Override",
        f"{overrides.get('override_rate_pct', 0):.1f}%",
        delta_color="inverse",
    )

    st.divider()

    # ---- Aging Buckets ----
    st.subheader("Antigüedad de Mora")
    import pandas as pd

    aging_df = pd.DataFrame([
        {"Rango": "0–30 días", "Casos": aging.get("0_30_days", 0), "color": "green"},
        {"Rango": "31–60 días", "Casos": aging.get("31_60_days", 0), "color": "yellow"},
        {"Rango": "61–90 días", "Casos": aging.get("61_90_days", 0), "color": "orange"},
        {"Rango": "+90 días", "Casos": aging.get("90_plus_days", 0), "color": "red"},
    ])
    st.bar_chart(aging_df.set_index("Rango")["Casos"])

    # ---- Priority Distribution ----
    priority_dist = decisions.get("priority_distribution", {})
    if priority_dist:
        st.divider()
        st.subheader("Distribución por Prioridad")
        prio_df = pd.DataFrame(
            [{"Prioridad": k, "Decisiones": v} for k, v in priority_dist.items()]
        )
        st.bar_chart(prio_df.set_index("Prioridad")["Decisiones"])

    # ---- Product Metrics ----
    if metrics_data:
        st.divider()
        st.subheader("Métricas de Producto")
        pm = metrics_data.get("product_metrics", {})
        m1, m2, m3 = st.columns(3)
        m1.metric("Tasa de Escalamiento", f"{pm.get('escalation_rate_pct', 0):.1f}%")
        m2.metric("Tasa Alerta Legal", f"{pm.get('legal_flag_rate_pct', 0):.1f}%")
        m3.metric("Exposición Total Mora", f"${pm.get('total_overdue_exposure', 0):,.0f}")


def page_events(token: str) -> None:
    st.header("Log de Eventos")

    col1, col2 = st.columns(2)
    with col1:
        event_type = st.selectbox(
            "Tipo de evento",
            ["", "CASE_CREATED", "DECISION_GENERATED", "OVERRIDE_APPLIED", "CASE_ESCALATED"],
        )
    with col2:
        since_hours = st.slider("Últimas N horas", 1, 168, 24)

    params = f"?since_hours={since_hours}"
    if event_type:
        params += f"&event_type={event_type}"

    data = api_get(f"/dashboard/events{params}", token)
    if not data:
        return

    events = data.get("events", [])
    st.caption(f"{len(events)} eventos encontrados")

    import pandas as pd
    if events:
        df = pd.DataFrame([
            {
                "Timestamp": e["created_at"],
                "Tipo": e["event_type"],
                "Entidad": e["aggregate_type"],
                "ID": e["aggregate_id"][:8] + "…",
                "Procesado": "✅" if e["processed"] else "⏳",
            }
            for e in events
        ])
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No hay eventos en este rango")


def page_rules(token: str) -> None:
    st.header("Reglas de Decisión")
    st.caption("Vista de solo lectura. Edición disponible para administradores vía API.")

    include_history = st.checkbox("Incluir historial de versiones")
    path = f"/tenants/me/rules?include_history={str(include_history).lower()}"
    data = api_get(path, token)

    if not data:
        return

    import pandas as pd
    df = pd.DataFrame([
        {
            "Nombre": r["name"],
            "Categoría": r["category"],
            "Prioridad": r["priority"],
            "Versión": r["version"],
            "Activa": "✅" if r["is_active"] else "❌",
            "Desde": r.get("effective_from", "")[:10] if r.get("effective_from") else "—",
            "Hasta": r.get("effective_to", "")[:10] if r.get("effective_to") else "Activa",
        }
        for r in data
    ])
    st.dataframe(df, use_container_width=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="URAKI AI — Ejecutivo",
        page_icon="📊",
        layout="wide",
    )

    if "token" not in st.session_state:
        page_login()
        return

    token = st.session_state["token"]

    with st.sidebar:
        st.title("URAKI AI")
        st.caption("Dashboard Ejecutivo")
        st.caption(f"Usuario: {st.session_state.get('email', '')}")
        section = st.radio(
            "Sección",
            ["KPIs", "Eventos", "Reglas"],
        )
        if st.button("Actualizar datos"):
            st.rerun()
        if st.button("Cerrar sesión"):
            st.session_state.clear()
            st.rerun()

    if section == "KPIs":
        page_executive(token)
    elif section == "Eventos":
        page_events(token)
    elif section == "Reglas":
        page_rules(token)


if __name__ == "__main__":
    main()
