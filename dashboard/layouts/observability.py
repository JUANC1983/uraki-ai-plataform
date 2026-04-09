# dashboard/layouts/observability.py
"""
System Observability Dashboard — internal view for admins and gerentes.

Shows:
  - Decisions per day (14-day window)
  - Override rate and most overridden rules
  - Average resolution time (p50, p90)
  - Most triggered rules
  - Failure rates
  - Feedback registry summary
"""
from __future__ import annotations

import streamlit as st
from typing import Optional
from core.auth import has_permission, get_role
from styles.theme import COLORS
from services.analytics_service import AnalyticsService
from services.feedback_service import FeedbackService
from services.sla_service import SLAService
from services.health_service import HealthService
from utils.time import fmt_duration_ms
from utils.formatters import _hex_to_rgb


def render() -> None:
    c = COLORS

    if not has_permission("download"):
        st.error("Sin permisos para ver el dashboard de observabilidad. Requiere rol Gerente o Admin.")
        return

    st.markdown(f"""
    <div style="padding:1.25rem 1.5rem 0;">
        <div style="font-size:18px;font-weight:700;color:{c['text_primary']};
            margin-bottom:0.25rem;">Sistema · Observabilidad</div>
        <div style="font-size:12px;color:{c['text_muted']};">
            Métricas internas del motor de decisiones — visibles solo para Gerente y Admin
        </div>
    </div>
    """, unsafe_allow_html=True)

    analytics = AnalyticsService()
    feedback  = FeedbackService()

    # ── Summary KPIs ───────────────────────────────────────────────────
    summary, sum_err = analytics.get_summary()
    if sum_err:
        st.error(f"Error al cargar métricas: {sum_err}")
        _render_offline_state(c)
        return

    if not summary:
        _render_offline_state(c)
        return

    _render_summary_kpis(summary, c)

    # ── Two-column layout ──────────────────────────────────────────────
    col_left, col_right = st.columns([1.2, 1])

    with col_left:
        _render_decisions_chart(analytics, c)
        _render_top_rules(analytics, c)

    with col_right:
        _render_override_stats(analytics, feedback, c)
        _render_resolution_times(analytics, c)

    # ── Feedback registry ──────────────────────────────────────────────
    _render_feedback_registry(feedback, c)

    # ── SLA monitoring ─────────────────────────────────────────────────
    _render_sla_panel(c)

    # ── Health & readiness ─────────────────────────────────────────────
    _render_health_panel(c)

    # ── Continuous improvement ─────────────────────────────────────────
    _render_improvement_panel(analytics, c)

    # ── Feature flags status ────────────────────────────────────────────
    _render_feature_flags_panel(c)


# ── KPI Row ────────────────────────────────────────────────────────────────────

def _render_summary_kpis(summary: dict, c: dict) -> None:
    st.markdown('<div style="padding:1rem 1.5rem;">', unsafe_allow_html=True)

    cols = st.columns(4)
    kpis = [
        ("Decisiones hoy",     str(summary.get("decisions_today", 0)),       c["accent"]),
        ("Overrides hoy",      str(summary.get("overrides_today", 0)),        c["warning"]),
        ("Tasa de override",
            f"{summary.get('override_rate', 0) * 100:.1f}%",                c["danger"]),
        ("Tiempo prom. resolución",
            fmt_duration_ms(summary.get("avg_resolution_ms", 0)) or "—",    c["success"]),
    ]
    for col, (label, value, color) in zip(cols, kpis):
        col.markdown(f"""
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.75rem 1rem;margin:0 0.375rem;">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:4px;">{label}</div>
            <div style="font-size:24px;font-weight:700;color:{color};line-height:1;">
                {value}</div>
        </div>
        """, unsafe_allow_html=True)

    # Extra row: backend version + active rules
    st.markdown(f"""
    <div style="display:flex;gap:1rem;margin-top:0.5rem;padding:0 0.375rem;">
        <span style="font-size:11px;color:{c['text_muted']};">
            Backend: <span style="color:{c['success']};font-weight:500;">
            v{summary.get('backend_version','—')}</span>
        </span>
        <span style="font-size:11px;color:{c['text_muted']};">
            Reglas activas: <span style="color:{c['text_secondary']};font-weight:500;">
            {summary.get('rules_active','—')}</span>
        </span>
        <span style="font-size:11px;color:{c['text_muted']};">
            Decisiones esta semana: <span style="color:{c['text_secondary']};font-weight:500;">
            {summary.get('decisions_this_week','—')}</span>
        </span>
        <span style="font-size:11px;color:{c['text_muted']};">
            Tasa de fallo: <span style="color:{'#EF4444' if (summary.get('failure_rate',0) or 0) > 0.05 else c['success']};font-weight:500;">
            {summary.get('failure_rate', 0) * 100:.1f}%</span>
        </span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Decisions per day chart ────────────────────────────────────────────────────

def _render_decisions_chart(analytics: AnalyticsService, c: dict) -> None:
    daily, err = analytics.get_decisions_daily(days=14)

    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:10px;padding:0.9rem 1rem;margin:0 1.5rem 1rem 1.5rem;">
        <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.75rem;">Decisiones · últimos 14 días</div>
    """, unsafe_allow_html=True)

    if err:
        st.error(f"Error: {err}")
    elif not daily:
        st.markdown(f"""
        <div style="text-align:center;padding:1rem;
            font-size:12px;color:{c['text_muted']};">
            Sin datos disponibles</div>
        """, unsafe_allow_html=True)
    else:
        # Simple text-based bar chart (no Plotly dependency)
        max_count = max((d.get("count", 0) for d in daily), default=1) or 1
        for day in daily[-7:]:   # last 7 days
            date  = day.get("date", "—")[-5:]  # MM-DD
            count = day.get("count", 0)
            ovr   = day.get("override_count", 0)
            bar_w = int((count / max_count) * 100)
            ovr_w = int((ovr / max_count) * 100)
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                <span style="font-size:10px;color:{c['text_muted']};
                    width:40px;flex-shrink:0;">{date}</span>
                <div style="flex:1;height:16px;background:{c['bg_secondary']};
                    border-radius:3px;position:relative;overflow:hidden;">
                    <div style="position:absolute;left:0;top:0;height:100%;
                        width:{bar_w}%;background:rgba(232,93,42,0.5);
                        border-radius:3px;"></div>
                    <div style="position:absolute;left:0;top:0;height:100%;
                        width:{ovr_w}%;background:rgba(245,158,11,0.7);
                        border-radius:3px;"></div>
                </div>
                <span style="font-size:10px;color:{c['text_secondary']};
                    width:30px;text-align:right;">{count}</span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown(f"""
        <div style="display:flex;gap:1rem;margin-top:0.5rem;">
            <span style="font-size:10px;color:{c['text_muted']};">
                <span style="color:rgba(232,93,42,0.8);">■</span> Decisiones</span>
            <span style="font-size:10px;color:{c['text_muted']};">
                <span style="color:rgba(245,158,11,0.8);">■</span> Overrides</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Top rules ─────────────────────────────────────────────────────────────────

def _render_top_rules(analytics: AnalyticsService, c: dict) -> None:
    rules, err = analytics.get_top_rules(limit=8)

    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:10px;padding:0.9rem 1rem;margin:0 1.5rem 1rem 1.5rem;">
        <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.6rem;">Reglas más activadas</div>
    """, unsafe_allow_html=True)

    if err:
        st.error(f"Error: {err}")
    elif not rules:
        st.markdown(f'<div style="font-size:12px;color:{c["text_muted"]};'
                    f'text-align:center;padding:0.5rem;">Sin datos</div>', unsafe_allow_html=True)
    else:
        max_count = max((r.get("trigger_count", 0) for r in rules), default=1) or 1
        hdr = st.columns([2, 1, 1.2])
        for col, h in zip(hdr, ["Regla", "Activaciones", "Override %"]):
            col.markdown(f"""
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.06em;padding-bottom:4px;
                border-bottom:1px solid {c['border_subtle']};">{h}</div>
            """, unsafe_allow_html=True)

        for rule in rules:
            rid   = rule.get("rule_id", "—")
            count = rule.get("trigger_count", 0)
            ovr_r = rule.get("override_rate", 0)
            ovr_c = "#EF4444" if ovr_r > 0.2 else "#F59E0B" if ovr_r > 0.1 else c["success"]
            bar_w = int((count / max_count) * 100)

            row = st.columns([2, 1, 1.2])
            row[0].markdown(f"""
            <div style="display:flex;align-items:center;gap:6px;padding:3px 0;">
                <span style="font-size:11px;color:{c['accent']};font-weight:500;">
                    {rid}</span>
            </div>""", unsafe_allow_html=True)
            row[1].markdown(f"""
            <div style="padding:3px 0;">
                <div style="display:flex;align-items:center;gap:4px;">
                    <div style="width:40px;height:4px;background:{c['bg_secondary']};
                        border-radius:2px;overflow:hidden;">
                        <div style="width:{bar_w}%;height:100%;
                            background:{c['accent']};border-radius:2px;"></div>
                    </div>
                    <span style="font-size:11px;color:{c['text_secondary']};">{count}</span>
                </div>
            </div>""", unsafe_allow_html=True)
            row[2].markdown(f"""
            <div style="padding:3px 0;">
                <span style="font-size:11px;color:{ovr_c};font-weight:600;">
                    {ovr_r*100:.0f}%</span>
            </div>""", unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Override stats ─────────────────────────────────────────────────────────────

def _render_override_stats(
    analytics: AnalyticsService,
    feedback:  FeedbackService,
    c: dict,
) -> None:
    frequently = feedback.get_frequently_overridden(limit=5)

    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:10px;padding:0.9rem 1rem;margin:0 1.5rem 1rem 1.5rem;">
        <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.6rem;">
            Reglas con más overrides (feedback)</div>
    """, unsafe_allow_html=True)

    if not frequently:
        st.markdown(f"""
        <div style="font-size:12px;color:{c['text_muted']};text-align:center;padding:0.5rem;">
            Sin overrides registrados</div>
        """, unsafe_allow_html=True)
    else:
        for rule in frequently:
            rid   = rule.get("rule_id", "—")
            count = rule.get("override_count", 0)
            acc   = rule.get("accuracy_rate", 1.0)
            acc_c = "#EF4444" if acc < 0.7 else "#F59E0B" if acc < 0.85 else c["success"]

            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;align-items:center;
                padding:5px 0;border-bottom:1px solid {c['border_subtle']};">
                <span style="font-size:11px;color:{c['accent']};font-weight:500;">{rid}</span>
                <div style="display:flex;gap:12px;align-items:center;">
                    <span style="font-size:10px;color:{c['warning']};">
                        {count} override{'s' if count != 1 else ''}</span>
                    <span style="font-size:10px;color:{acc_c};font-weight:600;">
                        {acc*100:.0f}% precisión</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Resolution times ──────────────────────────────────────────────────────────

def _render_resolution_times(analytics: AnalyticsService, c: dict) -> None:
    times, err = analytics.get_resolution_times()

    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:10px;padding:0.9rem 1rem;margin:0 1.5rem 1rem 1.5rem;">
        <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.6rem;">Tiempos de resolución</div>
    """, unsafe_allow_html=True)

    if err or not times:
        msg = f"Error: {err}" if err else "Sin datos disponibles"
        st.markdown(f'<div style="font-size:12px;color:{c["text_muted"]};">{msg}</div>',
                    unsafe_allow_html=True)
    else:
        metrics = [
            ("Promedio",  times.get("avg_ms", 0)),
            ("P50",       times.get("p50_ms", 0)),
            ("P90",       times.get("p90_ms", 0)),
            ("P99",       times.get("p99_ms", 0)),
        ]
        for label, ms in metrics:
            duration = fmt_duration_ms(ms) if ms else "—"
            color = (
                "#EF4444" if ms > 600_000
                else "#F59E0B" if ms > 300_000
                else c["success"]
            )
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;
                padding:4px 0;border-bottom:1px solid {c['border_subtle']};">
                <span style="font-size:11px;color:{c['text_muted']};">{label}</span>
                <span style="font-size:11px;color:{color};font-weight:600;">
                    {duration}</span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Feedback registry ─────────────────────────────────────────────────────────

def _render_feedback_registry(feedback: FeedbackService, c: dict) -> None:
    registry, err = feedback.get_registry()

    st.markdown(f"""
    <div style="padding:0 1.5rem 1rem;">
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem 1rem;">
            <div style="display:flex;justify-content:space-between;align-items:center;
                margin-bottom:0.6rem;">
                <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.08em;">Registro de feedback de reglas</div>
            </div>
    """, unsafe_allow_html=True)

    if err:
        st.error(f"Error: {err}")
    elif not registry:
        st.markdown(f'<div style="font-size:12px;color:{c["text_muted"]};">Sin datos</div>',
                    unsafe_allow_html=True)
    else:
        total = registry.get("total_overrides", 0)
        rules = registry.get("rules", [])

        st.markdown(f"""
        <div style="font-size:12px;color:{c['text_secondary']};margin-bottom:0.75rem;">
            Total overrides registrados: <strong style="color:{c['warning']};">{total}</strong>
        </div>
        """, unsafe_allow_html=True)

        if rules:
            cols = st.columns([2, 1, 1, 2])
            for col, h in zip(cols, ["Regla ID", "Overrides", "Precisión", "Razón más frecuente"]):
                col.markdown(f"""
                <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.06em;padding-bottom:4px;
                    border-bottom:1px solid {c['border_subtle']};">{h}</div>
                """, unsafe_allow_html=True)

            for rule in rules[:10]:
                rid     = rule.get("rule_id", "—")
                count   = rule.get("override_count", 0)
                acc     = rule.get("accuracy_rate", 1.0)
                reason  = rule.get("top_reason", "—")
                acc_c   = "#EF4444" if acc < 0.7 else "#F59E0B" if acc < 0.85 else c["success"]
                row     = st.columns([2, 1, 1, 2])

                row[0].markdown(f'<div style="font-size:11px;color:{c["accent"]};'
                                f'font-weight:500;padding:3px 0;">{rid}</div>',
                                unsafe_allow_html=True)
                row[1].markdown(f'<div style="font-size:11px;color:{c["warning"]};'
                                f'padding:3px 0;">{count}</div>',
                                unsafe_allow_html=True)
                row[2].markdown(f'<div style="font-size:11px;color:{acc_c};'
                                f'font-weight:600;padding:3px 0;">{acc*100:.0f}%</div>',
                                unsafe_allow_html=True)
                row[3].markdown(f'<div style="font-size:10px;color:{c["text_muted"]};'
                                f'padding:3px 0;white-space:nowrap;overflow:hidden;'
                                f'text-overflow:ellipsis;">{reason[:40]}</div>',
                                unsafe_allow_html=True)

    st.markdown('</div></div>', unsafe_allow_html=True)


# ── SLA panel ─────────────────────────────────────────────────────────────────

def _render_sla_panel(c: dict) -> None:
    sla = SLAService()
    summary, sum_err = sla.get_summary()
    breaches, br_err = sla.get_breaches(limit=10)

    st.markdown(f"""
    <div style="padding:0 1.5rem 1rem;">
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem 1rem;">
            <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:0.75rem;">SLA — Acuerdos de nivel de servicio</div>
    """, unsafe_allow_html=True)

    if sum_err:
        st.warning(f"SLA summary no disponible: {sum_err}")
    elif summary:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Decisiones a tiempo", summary.get("decisions_on_time", "—"))
        col2.metric("Decisiones fuera de SLA", summary.get("decisions_breached", "—"))
        col3.metric("Resoluciones a tiempo", summary.get("resolutions_on_time", "—"))
        col4.metric("Tasa de breach", f"{summary.get('breach_rate', 0)*100:.1f}%")

    if br_err:
        st.warning(f"Breaches no disponibles: {br_err}")
    elif breaches:
        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_muted']};margin:0.75rem 0 0.4rem;">
            Últimos casos en breach de SLA</div>
        """, unsafe_allow_html=True)
        for breach in breaches[:5]:
            btype = breach.get("breach_type", "—")
            actual = breach.get("actual", "—")
            limit = breach.get("threshold", "—")
            cid = str(breach.get("case_id", "?"))[:12]
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;align-items:center;
                padding:4px 0;border-bottom:1px solid {c['border_subtle']};">
                <span style="font-size:11px;color:{c['text_secondary']};">
                    <span style="color:#EF4444;">⚠</span> {cid}</span>
                <span style="font-size:11px;color:{c['text_muted']};">{btype}</span>
                <span style="font-size:11px;color:#EF4444;">{actual} / límite {limit}</span>
            </div>
            """, unsafe_allow_html=True)
    elif not sum_err:
        st.markdown(f'<div style="font-size:12px;color:{c["text_muted"]};">Sin breaches recientes.</div>',
                    unsafe_allow_html=True)

    st.markdown('</div></div>', unsafe_allow_html=True)


# ── Health & readiness panel ───────────────────────────────────────────────────

def _render_health_panel(c: dict) -> None:
    status = HealthService().get_combined_status()

    overall = status.get("overall", "down")
    color   = {"ok": "#22C55E", "degraded": "#F59E0B"}.get(overall, "#EF4444")
    icon    = {"ok": "✓", "degraded": "⚠"}.get(overall, "✕")

    st.markdown(f"""
    <div style="padding:0 1.5rem 1.5rem;">
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem 1rem;">
            <div style="display:flex;align-items:center;justify-content:space-between;
                margin-bottom:0.75rem;">
                <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.08em;">Backend · Health & Readiness</div>
                <span style="background:rgba({_hex_to_rgb(color)},0.10);
                    color:{color};border:1px solid rgba({_hex_to_rgb(color)},0.3);
                    border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;">
                    {icon} {overall.upper()}</span>
            </div>
            <div style="display:flex;gap:1rem;font-size:11px;color:{c['text_muted']};
                margin-bottom:0.75rem;">
                <span>Versión: <strong style="color:{c['text_secondary']};">
                    {status.get('backend_version','—')}</strong></span>
                <span>Uptime: <strong style="color:{c['text_secondary']};">
                    {_fmt_uptime(status.get('uptime_s',0))}</strong></span>
                <span>Ready: <strong style="color:{'#22C55E' if status.get('ready') else '#EF4444'};">
                    {'Sí' if status.get('ready') else 'No'}</strong></span>
            </div>
    """, unsafe_allow_html=True)

    checks = status.get("checks", {})
    if checks:
        for svc, info in checks.items():
            ok      = info.get("ok", False)
            lat     = info.get("latency_ms", 0)
            dot_col = "#22C55E" if ok else "#EF4444"
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;align-items:center;
                padding:4px 0;border-bottom:1px solid {c['border_subtle']};">
                <span style="font-size:11px;color:{c['text_secondary']};">
                    <span style="color:{dot_col};">{'●' if ok else '●'}</span>
                    &nbsp;{svc.replace('_',' ').capitalize()}</span>
                <span style="font-size:11px;color:{c['text_muted']};">{lat}ms</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="font-size:12px;color:{c["text_muted"]};">Sin datos de checks.</div>',
                    unsafe_allow_html=True)

    st.markdown('</div></div>', unsafe_allow_html=True)


# ── Continuous improvement panel ──────────────────────────────────────────────

def _render_improvement_panel(analytics: AnalyticsService, c: dict) -> None:
    data, err = analytics.get_learning_indicators()

    st.markdown(f"""
    <div style="padding:0 1.5rem 1rem;">
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem 1rem;">
            <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:0.75rem;">
                Evolución del sistema · Indicadores de aprendizaje</div>
    """, unsafe_allow_html=True)

    if err:
        st.warning(f"Indicadores de aprendizaje no disponibles: {err}")
        st.markdown('</div></div>', unsafe_allow_html=True)
        return

    if not data:
        # Show session-level stats as fallback
        import core.state_manager as sm_mod
        resolved   = sm_mod.get("resolved_today") or 0
        avg_ms     = sm_mod.avg_resolution_ms()
        mem_stored = len(st.session_state.get("_case_memory_fingerprints") or [])
        data = {
            "decisions_total":     resolved,
            "avg_rating":          None,
            "total_ratings":       0,
            "memory_fingerprints": mem_stored,
        }

    col1, col2, col3, col4 = st.columns(4)

    total     = data.get("decisions_total", 0)
    d_trend   = data.get("decisions_trend")
    ov_trend  = data.get("override_rate_trend")
    avg_rating = data.get("avg_rating")
    ratings   = data.get("total_ratings", 0)
    mem_fp    = data.get("memory_fingerprints", 0)

    def _trend_badge(val: Optional[float], invert: bool = False) -> str:
        if val is None:
            return ""
        direction = val < 0 if not invert else val > 0
        color = "#22C55E" if direction else "#EF4444"
        arrow = "↓" if val < 0 else "↑"
        return f'<span style="color:{color};font-size:10px;"> {arrow}{abs(val):.1f}%</span>'

    col1.metric("Decisiones procesadas", str(total))
    col2.metric("Overrides (tendencia)", f"{ov_trend:+.1f}%" if ov_trend is not None else "—")
    col3.metric("Valoración media", f"{avg_rating:.1f}/5" if avg_rating else "—",
                f"{ratings} valoraciones" if ratings else "Sin datos")
    col4.metric("Casos en memoria", str(mem_fp))

    # Accuracy trend chart (if available)
    accuracy_trend = data.get("accuracy_trend") or []
    override_trend = data.get("override_trend") or []

    if accuracy_trend or override_trend:
        import streamlit as _st
        chart_data_exists = False

        if accuracy_trend:
            try:
                import pandas as pd
                df = pd.DataFrame(accuracy_trend)
                if "date" in df.columns and "accuracy" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")
                    st.markdown(f"""
                    <div style="font-size:10px;color:{c['text_muted']};
                        text-transform:uppercase;letter-spacing:0.06em;
                        margin:0.75rem 0 0.3rem;">Tendencia de precisión</div>
                    """, unsafe_allow_html=True)
                    st.line_chart(df[["accuracy"]], height=120, use_container_width=True)
                    chart_data_exists = True
            except Exception:
                pass

        if override_trend and not chart_data_exists:
            try:
                import pandas as pd
                df = pd.DataFrame(override_trend)
                if "date" in df.columns and "override_rate" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")
                    st.markdown(f"""
                    <div style="font-size:10px;color:{c['text_muted']};
                        text-transform:uppercase;letter-spacing:0.06em;
                        margin:0.75rem 0 0.3rem;">Tasa de override</div>
                    """, unsafe_allow_html=True)
                    st.line_chart(df[["override_rate"]], height=120, use_container_width=True)
            except Exception:
                pass

    # Learning indicators checklist
    st.markdown(f"""
    <div style="margin-top:0.75rem;font-size:11px;color:{c['text_muted']};line-height:1.8;">
        <span style="color:#22C55E;">✓</span> Fingerprints de casos almacenados en memoria<br>
        <span style="color:#22C55E;">✓</span> Feedback de operadores capturado y procesado<br>
        <span style="color:#22C55E;">✓</span> Override history alimentando el registro de reglas<br>
        <span style="color:{'#22C55E' if mem_fp > 0 else '#F59E0B'};">
            {'✓' if mem_fp > 0 else '·'}</span>
        Similitud de casos {'activa' if mem_fp > 0 else '(en progreso)'} —
        {mem_fp} casos en memoria<br>
        <span style="color:#3B82F6;">· </span>
        Automatización: preparada (pendiente de habilitación por tenant)
    </div>
    """, unsafe_allow_html=True)

    st.markdown('</div></div>', unsafe_allow_html=True)


# ── Feature flags panel ────────────────────────────────────────────────────────

def _render_feature_flags_panel(c: dict) -> None:
    from core.feature_flags import get_all_flags, get_flag_definitions

    flags_state  = get_all_flags()
    definitions  = {d.name: d for d in get_flag_definitions()}

    st.markdown(f"""
    <div style="padding:0 1.5rem 1.5rem;">
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem 1rem;">
            <div style="font-size:11px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:0.75rem;">
                Feature Flags — estado por tenant</div>
    """, unsafe_allow_html=True)

    cols = st.columns([2, 1, 3])
    for col, h in zip(cols, ["Flag", "Estado", "Descripción"]):
        col.markdown(f"""
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.06em;padding-bottom:4px;border-bottom:1px solid {c['border_subtle']};">
            {h}</div>
        """, unsafe_allow_html=True)

    for name, enabled in sorted(flags_state.items()):
        defn = definitions.get(name)
        desc = defn.description if defn else "—"
        rollout = defn.rollout_pct if defn else 100
        status_color = "#22C55E" if enabled else "#EF4444"
        status_label = "Activo" if enabled else "Inactivo"
        rollout_note = f" · {rollout}%" if rollout < 100 else ""
        row = st.columns([2, 1, 3])
        row[0].markdown(f'<div style="font-size:11px;color:{c["text_secondary"]};'
                        f'padding:4px 0;font-family:monospace;">{name}</div>',
                        unsafe_allow_html=True)
        row[1].markdown(f'<div style="font-size:11px;color:{status_color};'
                        f'font-weight:600;padding:4px 0;">'
                        f'{status_label}{rollout_note}</div>',
                        unsafe_allow_html=True)
        row[2].markdown(f'<div style="font-size:11px;color:{c["text_muted"]};'
                        f'padding:4px 0;">{desc}</div>',
                        unsafe_allow_html=True)

    st.markdown('</div></div>', unsafe_allow_html=True)


def _fmt_uptime(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h >= 24:
        return f"{h//24}d {h%24}h"
    return f"{h}h {m}m"


# ── Offline state ─────────────────────────────────────────────────────────────

def _render_offline_state(c: dict) -> None:
    st.markdown(f"""
    <div style="
        text-align:center;padding:4rem 1rem;
        border:1px dashed {c['border_default']};
        border-radius:12px;margin:1.5rem;
    ">
        <div style="font-size:32px;margin-bottom:1rem;">📡</div>
        <div style="font-size:15px;font-weight:600;color:{c['text_primary']};
            margin-bottom:0.5rem;">
            Analytics no disponibles</div>
        <div style="font-size:12px;color:{c['text_muted']};max-width:300px;
            margin:0 auto;line-height:1.6;">
            Los datos de observabilidad provienen del backend.
            Verifica la conexión y los permisos del endpoint /analytics.
        </div>
    </div>
    """, unsafe_allow_html=True)
