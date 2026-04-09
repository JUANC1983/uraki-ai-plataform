# dashboard/components/audit_timeline.py
"""
Full audit timeline per case — immutable history of every event.

Fetches from GET /cases/{id}/audit and renders a vertical chronological
timeline suitable for compliance, legal review, and operator handoff.
"""
from __future__ import annotations

import streamlit as st
import core.state_manager as sm
from styles.theme import COLORS
from services.case_service import CaseService
from utils.time import time_ago
import json


_EVENT_STYLES: dict[str, tuple[str, str, str]] = {
    # event_type → (icon, color, label)
    "created":        ("📋", "#3B82F6", "Caso creado"),
    "evaluated":      ("⚡", "#E85D2A", "Evaluación ejecutada"),
    "re_evaluated":   ("↺",  "#E85D2A", "Re-evaluación ejecutada"),
    "status_changed": ("→",  "#F59E0B", "Estado cambiado"),
    "overridden":     ("⚠",  "#F59E0B", "Decisión sobreescrita"),
    "escalated":      ("↑",  "#EF4444", "Escalado"),
    "resolved":       ("✓",  "#22C55E", "Resuelto"),
    "document_added": ("📄", "#6366F1", "Documento adjunto"),
    "action_sent":    ("📧", "#8B5CF6", "Acción ejecutada"),
    "note_added":     ("💬", "#888888", "Nota añadida"),
}


def render(case: dict) -> None:
    """Render the full audit timeline for a case inside an expander."""
    from core.feature_flags import flag_gate
    if not flag_gate("advanced_audit", "Auditoría avanzada no habilitada para este tenant."):
        return

    c    = COLORS
    cid  = case["id"]

    with st.expander("📋 Historial de auditoría completo", expanded=False):
        # Emit audit viewed event once per case open
        from services.event_service import emit_audit_viewed
        emit_audit_viewed(cid)

        # Cache audit data per case
        cached_cid = sm.get("audit_case_id")
        if cached_cid != cid or sm.get("audit_data") is None:
            with st.spinner("Cargando historial..."):
                events, err = CaseService().get_audit_log(cid)
            if err:
                st.error(f"Error al cargar historial: {err}")
                return
            sm.set("audit_data", events)
            sm.set("audit_case_id", cid)
        else:
            events = sm.get("audit_data") or []

        if not events:
            st.markdown(f"""
            <div style="text-align:center;padding:1.5rem;
                font-size:12px;color:{c['text_muted']};">
                Sin eventos registrados para este caso.
            </div>
            """, unsafe_allow_html=True)
            return

        # Export button
        col_head, col_export = st.columns([3, 1])
        with col_head:
            st.markdown(f"""
            <div style="font-size:11px;color:{c['text_muted']};
                margin-bottom:0.75rem;">
                {len(events)} evento{'s' if len(events) != 1 else ''} registrado{'s' if len(events) != 1 else ''}
                · ordenado{'s' if len(events) != 1 else ''} cronológicamente
            </div>
            """, unsafe_allow_html=True)
        with col_export:
            st.download_button(
                label="⬇ Exportar",
                data=json.dumps(events, ensure_ascii=False, indent=2),
                file_name=f"audit_{cid}.json",
                mime="application/json",
                key=f"export_audit_{cid}",
                use_container_width=True,
            )

        # Timeline
        _render_timeline(events, c)


def _render_timeline(events: list[dict], c: dict) -> None:
    """Render a vertical chronological timeline of audit events."""

    for i, event in enumerate(events):
        etype    = event.get("type", "unknown")
        ts       = event.get("timestamp", "")
        user     = event.get("user", "Sistema")
        details  = event.get("details", "")
        is_last  = i == len(events) - 1

        icon, color, label = _EVENT_STYLES.get(
            etype, ("·", c["text_muted"], etype.replace("_", " ").capitalize())
        )

        connector = (
            "" if is_last
            else f'<div style="width:2px;height:16px;background:{c["border_subtle"]};'
                 f'margin:0 auto;margin-left:13px;"></div>'
        )

        # Extra metadata from event
        extra_html = ""
        if details:
            extra_html = f"""
            <div style="font-size:11px;color:{c['text_muted']};
                margin-top:4px;padding:4px 8px;
                background:{c['bg_elevated']};border-radius:4px;
                border-left:2px solid {color};word-break:break-word;">
                {details}
            </div>"""

        st.markdown(f"""
        <div style="display:flex;gap:12px;margin-bottom:4px;">
            <!-- Dot -->
            <div style="flex-shrink:0;margin-top:2px;">
                <div style="
                    width:28px;height:28px;border-radius:50%;
                    background:rgba({_hex_rgb(color)},0.12);
                    border:1.5px solid rgba({_hex_rgb(color)},0.4);
                    display:flex;align-items:center;justify-content:center;
                    font-size:12px;
                ">{icon}</div>
            </div>
            <!-- Content -->
            <div style="flex:1;padding-bottom:4px;">
                <div style="display:flex;align-items:center;
                    justify-content:space-between;flex-wrap:wrap;gap:4px;">
                    <span style="font-size:12px;font-weight:600;color:{c['text_primary']};">
                        {label}</span>
                    <span style="font-size:10px;color:{c['text_muted']};">
                        {time_ago(ts) if ts else '—'} · {user}</span>
                </div>
                {extra_html}
            </div>
        </div>
        {connector}
        """, unsafe_allow_html=True)


def _hex_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
    return "128,128,128"
