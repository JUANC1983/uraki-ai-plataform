# dashboard/layouts/executive.py
"""
Executive / Gerencial view — portfolio overview with KPI summary and case table.
"""
import streamlit as st
from services.case_service import CaseService
from services.api_client import BACKEND_CONFIGURED
import core.state_manager as sm
import core.event_bus as bus
from styles.theme import COLORS, PRIORITY_COLORS, STATUS_COLORS, STATUS_LABELS
from utils.formatters import fmt_currency, _hex_to_rgb
from utils.time import time_ago


def render() -> None:
    c  = COLORS
    cs = CaseService()

    if not BACKEND_CONFIGURED:
        st.error("Backend no configurado — configura URAKI_API_URL para ver la cartera.")
        return

    cases, load_err = cs.get_all()
    metrics         = cs.get_metrics()

    if load_err:
        st.error(f"Error al cargar casos: {load_err}")
        cases = []
        if st.button("↺ Reintentar", key="exec_retry"):
            st.rerun()
        return

    html = f"""
    <div style="padding:1.25rem 1.5rem 0;">
        <div style="font-size:18px;font-weight:700;color:{c['text_primary']};
            margin-bottom:0.25rem;">Vista Gerencial</div>
        <div style="font-size:12px;color:{c['text_muted']};">
            Resumen completo de la cartera · {metrics['total']} casos totales
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    # ── KPI row ────────────────────────────────────────────────────────
    st.markdown('<div style="padding:1rem 1.5rem;">', unsafe_allow_html=True)
    k1, k2, k3, k4, k5 = st.columns(5)

    _kpi(k1, "Pendientes",   str(metrics["pending"]),   c["warning"])
    _kpi(k2, "Resueltos",    str(metrics["closed"]),    c["success"])
    _kpi(k3, "Críticos",     str(metrics["critical"]),  c["critical"])
    _kpi(k4, "Escalados",    str(metrics["escalated"]), c["danger"])
    _kpi(k5, "En revisión",  str(metrics["in_review"]), c["info"])
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Risk distribution bar ──────────────────────────────────────────
    if cases:
        alto  = sum(1 for x in cases if x.get("risk_level") == "ALTO"  and x.get("status") != "CLOSED")
        medio = sum(1 for x in cases if x.get("risk_level") == "MEDIO" and x.get("status") != "CLOSED")
        bajo  = sum(1 for x in cases if x.get("risk_level") == "BAJO"  and x.get("status") != "CLOSED")
        total_open = alto + medio + bajo or 1

        html = f"""
        <div style="margin:0 1.5rem 1rem;
            background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem 1rem;">
            <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:0.6rem;">
                Distribución de riesgo (activos)</div>
            <div style="display:flex;height:8px;border-radius:6px;overflow:hidden;
                margin-bottom:0.6rem;">
                <div style="width:{alto/total_open*100:.0f}%;background:#EF4444;"></div>
                <div style="width:{medio/total_open*100:.0f}%;background:#F59E0B;"></div>
                <div style="width:{bajo/total_open*100:.0f}%;background:#22C55E;"></div>
            </div>
            <div style="display:flex;gap:1.5rem;">
                <span style="font-size:11px;color:#EF4444;">● ALTO: {alto}</span>
                <span style="font-size:11px;color:#F59E0B;">● MEDIO: {medio}</span>
                <span style="font-size:11px;color:#22C55E;">● BAJO: {bajo}</span>
            </div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)

    # ── Financial exposure ─────────────────────────────────────────────
    total_exposure   = sum(x.get("overdue_amount", 0) for x in cases if x.get("status") != "CLOSED")
    critical_exposure = sum(
        x.get("overdue_amount", 0) for x in cases
        if x.get("priority") == "CRITICAL" and x.get("status") != "CLOSED"
    )

    exp1, exp2 = st.columns(2)
    with exp1:
        html = f"""
        <div style="margin:0 0.75rem 1rem;
            background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem 1rem;">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:4px;">Exposición total activa</div>
            <div style="font-size:22px;font-weight:700;color:{c['danger']};
                font-variant-numeric:tabular-nums;">
                {fmt_currency(total_exposure)}</div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)
    with exp2:
        html = f"""
        <div style="margin:0 0.75rem 1rem;
            background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem 1rem;">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:4px;">Exposición crítica</div>
            <div style="font-size:22px;font-weight:700;color:{c['critical']};
                font-variant-numeric:tabular-nums;">
                {fmt_currency(critical_exposure)}</div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)

    # ── Case table ─────────────────────────────────────────────────────
    html = f"""
    <div style="padding:0 1.5rem 0.5rem;">
        <div style="font-size:12px;font-weight:600;color:{c['text_secondary']};
            text-transform:uppercase;letter-spacing:0.08em;">Tabla de casos</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    hcols = st.columns([1.8, 2, 1, 1, 1.2, 1.4, 1])
    for col, h in zip(hcols, ["Caso ID", "Cliente", "Días", "Monto",
                               "Prioridad", "Estado", "Acción"]):
        with col:
            html = f"""
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;padding:0 0 0.4rem;
                border-bottom:1px solid {c['border_subtle']};">{h}</div>
            """
            st.markdown(html, unsafe_allow_html=True)

    # Already sorted by impact score from get_all()
    for case in cases:
        p_color   = PRIORITY_COLORS.get(case.get("priority"), c["text_muted"])
        s_color   = STATUS_COLORS.get(case.get("status"), c["text_muted"])
        is_closed = case.get("status") == "CLOSED"
        opacity   = "0.45" if is_closed else "1"
        days      = case.get("overdue_days", 0)
        day_color = "#EF4444" if days > 90 else "#F59E0B" if days > 30 else c["text_primary"]
        amount    = case.get("overdue_amount", 0) / 1_000_000

        row = st.columns([1.8, 2, 1, 1, 1.2, 1.4, 1])

        with row[0]:
            html = f"""<div style="font-size:11px;color:{c['text_muted']};
                opacity:{opacity};padding:0.35rem 0;font-variant-numeric:tabular-nums;">
                {case.get('id', '—')}</div>"""
            st.markdown(html, unsafe_allow_html=True)

        with row[1]:
            html = f"""<div style="font-size:12px;color:{c['text_primary']};
                opacity:{opacity};padding:0.35rem 0;font-weight:500;
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                {case.get('client_name', '—')}</div>"""
            st.markdown(html, unsafe_allow_html=True)

        with row[2]:
            html = f"""<div style="font-size:12px;color:{day_color};
                opacity:{opacity};padding:0.35rem 0;font-weight:600;">{days}d</div>"""
            st.markdown(html, unsafe_allow_html=True)

        with row[3]:
            html = f"""<div style="font-size:11px;color:{c['text_secondary']};
                opacity:{opacity};padding:0.35rem 0;font-variant-numeric:tabular-nums;">
                ${amount:.1f}M</div>"""
            st.markdown(html, unsafe_allow_html=True)

        with row[4]:
            html = f"""
            <div style="padding:0.35rem 0;opacity:{opacity};">
                <span style="background:rgba({_hex_to_rgb(p_color)},0.12);color:{p_color};
                    border-radius:4px;padding:1px 7px;font-size:10px;font-weight:600;">
                    {case.get('priority', '—')}</span>
            </div>"""
            st.markdown(html, unsafe_allow_html=True)

        with row[5]:
            status_label = STATUS_LABELS.get(case.get("status", ""), case.get("status", ""))
            html = f"""
            <div style="padding:0.35rem 0;opacity:{opacity};">
                <span style="background:rgba({_hex_to_rgb(s_color)},0.10);color:{s_color};
                    border-radius:4px;padding:1px 7px;font-size:10px;font-weight:500;">
                    {status_label}</span>
            </div>"""
            st.markdown(html, unsafe_allow_html=True)

        with row[6]:
            if not is_closed:
                if st.button("→", key=f"exec_select_{case['id']}", help="Abrir caso"):
                    sm.set("view_mode", "flow")
                    bus.emit("CASE_SELECTED", {"case_id": case["id"]})
            else:
                html = f'<div style="padding:0.35rem 0;font-size:11px;color:{c["text_muted"]};">Cerrado</div>'
                st.markdown(html, unsafe_allow_html=True)


def _kpi(col, label: str, value: str, color: str) -> None:
    c = COLORS
    with col:
        html = f"""
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.75rem 1rem;margin:0 0.375rem 0;">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:4px;">{label}</div>
            <div style="font-size:24px;font-weight:700;color:{color};line-height:1;">
                {value}</div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)
