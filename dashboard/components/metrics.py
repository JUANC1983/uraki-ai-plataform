# dashboard/components/metrics.py
"""Horizontal KPI metrics bar — momentum system."""
import streamlit as st
import core.state_manager as sm
from styles.theme import COLORS
from utils.formatters import fmt_currency
from utils.time import fmt_duration_ms


def render(db_metrics: dict) -> None:
    c = COLORS
    resolved = sm.get("resolved_today", 0)
    avg_ms = sm.avg_resolution_ms()
    critical = db_metrics.get("critical", 0)
    escalated = db_metrics.get("escalated", 0)

    # ── Momentum strip ─────────────────────────────────────────────────
    momentum_color = c["success"] if resolved >= 3 else c["accent"] if resolved >= 1 else c["text_muted"]
    avg_display = fmt_duration_ms(avg_ms) if avg_ms else "—"
    dots = "".join(_dot(i < resolved, momentum_color) for i in range(10))

    icon_bg_momentum = f"rgba({_hex_rgb(momentum_color)},0.12)"
    icon_border_momentum = f"rgba({_hex_rgb(momentum_color)},0.3)"

    html = f"""
    <div style="
        display:flex;align-items:center;justify-content:space-between;
        padding:0.6rem 1.5rem;
        background:{c['bg_secondary']};
        border-bottom:1px solid {c['border_subtle']};
        gap:1rem;
        flex-wrap:wrap;
    ">
        <div style="display:flex;align-items:center;gap:10px;">
            <div style="
                width:36px;height:36px;
                background:{icon_bg_momentum};
                border:1px solid {icon_border_momentum};
                border-radius:8px;display:flex;align-items:center;justify-content:center;
                font-size:16px;
            ">✓</div>
            <div>
                <div style="font-size:20px;font-weight:700;color:{momentum_color};
                    line-height:1.1;">{resolved}</div>
                <div style="font-size:10px;color:{c['text_muted']};
                    text-transform:uppercase;letter-spacing:0.08em;">Resueltos hoy</div>
            </div>
        </div>

        <div style="width:1px;height:32px;background:{c['border_subtle']};"></div>

        <div style="display:flex;align-items:center;gap:10px;">
            <div style="
                width:36px;height:36px;
                background:rgba(59,130,246,0.08);
                border:1px solid rgba(59,130,246,0.2);
                border-radius:8px;display:flex;align-items:center;justify-content:center;
                font-size:16px;
            ">⏱</div>
            <div>
                <div style="font-size:20px;font-weight:700;color:{c['text_primary']};
                    line-height:1.1;">{avg_display}</div>
                <div style="font-size:10px;color:{c['text_muted']};
                    text-transform:uppercase;letter-spacing:0.08em;">Tiempo promedio</div>
            </div>
        </div>

        <div style="width:1px;height:32px;background:{c['border_subtle']};"></div>

        <div style="display:flex;align-items:center;gap:10px;">
            <div style="
                width:36px;height:36px;
                background:rgba(245,158,11,0.08);
                border:1px solid rgba(245,158,11,0.2);
                border-radius:8px;display:flex;align-items:center;justify-content:center;
                font-size:16px;
            ">⋯</div>
            <div>
                <div style="font-size:20px;font-weight:700;color:{c['warning']};
                    line-height:1.1;">{db_metrics.get('pending', 0)}</div>
                <div style="font-size:10px;color:{c['text_muted']};
                    text-transform:uppercase;letter-spacing:0.08em;">Pendientes</div>
            </div>
        </div>

        <div style="width:1px;height:32px;background:{c['border_subtle']};"></div>

        <div style="display:flex;align-items:center;gap:10px;">
            <div style="
                width:36px;height:36px;
                background:rgba(168,85,247,0.08);
                border:1px solid rgba(168,85,247,0.2);
                border-radius:8px;display:flex;align-items:center;justify-content:center;
                font-size:16px;
            ">⚡</div>
            <div>
                <div style="font-size:20px;font-weight:700;color:{c['critical']};
                    line-height:1.1;">{critical}</div>
                <div style="font-size:10px;color:{c['text_muted']};
                    text-transform:uppercase;letter-spacing:0.08em;">Críticos</div>
            </div>
        </div>

        <div style="width:1px;height:32px;background:{c['border_subtle']};"></div>

        <div style="display:flex;align-items:center;gap:10px;">
            <div style="
                width:36px;height:36px;
                background:rgba(239,68,68,0.08);
                border:1px solid rgba(239,68,68,0.2);
                border-radius:8px;display:flex;align-items:center;justify-content:center;
                font-size:16px;
            ">↑</div>
            <div>
                <div style="font-size:20px;font-weight:700;color:{c['danger']};
                    line-height:1.1;">{escalated}</div>
                <div style="font-size:10px;color:{c['text_muted']};
                    text-transform:uppercase;letter-spacing:0.08em;">Escalados</div>
            </div>
        </div>

        <div style="
            display:flex;align-items:center;gap:8px;
            margin-left:auto;
        ">
            <span style="font-size:10px;color:{c['text_muted']};
                text-transform:uppercase;letter-spacing:0.08em;">Sesión</span>
            {dots}
        </div>
    </div>
    """
    with st.container():
    st.markdown(html, unsafe_allow_html=True)

def _dot(filled: bool, color: str) -> str:
    bg = color if filled else COLORS["border_default"]
    return (
        f'<div style="width:8px;height:8px;border-radius:50%;'
        f'background:{bg};transition:background 0.3s;"></div>'
    )


def _hex_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
    return "128,128,128"
