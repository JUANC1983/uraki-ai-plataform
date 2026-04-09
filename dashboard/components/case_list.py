# dashboard/components/case_list.py
"""Left-column case queue — filterable, selectable list."""
import streamlit as st
import core.state_manager as sm
import core.event_bus as bus
from styles.theme import COLORS, PRIORITY_COLORS, STATUS_COLORS, STATUS_LABELS
from utils.time import time_ago
from utils.formatters import fmt_currency

_FILTER_OPTIONS = {
    "all":        "Todos",
    "new":        "Nuevos",
    "in_review":  "En revisión",
    "escalated":  "Escalados",
    "closed":     "Cerrados",
}

_PRIORITY_ICON = {
    "CRITICAL": "⚡",
    "HIGH":     "↑",
    "MEDIUM":   "·",
    "LOW":      "↓",
}


def render(cases: list[dict]) -> None:
    c = COLORS
    selected_id = sm.get("selected_case_id")
    role = sm.get("current_role", "Operador")

    # ── Column header ──────────────────────────────────────────────────
    st.markdown(f"""
    <div style="
        padding:0.75rem 1rem 0.5rem;
        border-bottom:1px solid {c['border_subtle']};
    ">
        <div style="display:flex;align-items:center;justify-content:space-between;">
            <span style="font-size:12px;font-weight:600;color:{c['text_secondary']};
                text-transform:uppercase;letter-spacing:0.08em;">Cola de Casos</span>
            <span style="
                background:{c['accent_muted']};color:{c['accent']};
                border:1px solid {c['border_accent']};
                border-radius:20px;padding:1px 8px;
                font-size:11px;font-weight:600;
            ">{len([x for x in cases if x['status'] != 'CLOSED'])}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Filter tabs ────────────────────────────────────────────────────
    current_filter = sm.get("queue_filter", "all")
    tab_labels = list(_FILTER_OPTIONS.values())
    tab_keys = list(_FILTER_OPTIONS.keys())

    selected_tab = st.radio(
        label="",
        options=tab_keys,
        format_func=lambda k: _FILTER_OPTIONS[k],
        index=tab_keys.index(current_filter),
        horizontal=True,
        key="queue_filter_radio",
        label_visibility="collapsed",
    )
    if selected_tab != current_filter:
        sm.set("queue_filter", selected_tab)
        st.rerun()

    # ── Apply filter ───────────────────────────────────────────────────
    filter_map = {
        "all":       lambda x: True,
        "new":       lambda x: x["status"] == "NEW",
        "in_review": lambda x: x["status"] == "IN_REVIEW",
        "escalated": lambda x: x["status"] == "ESCALATED",
        "closed":    lambda x: x["status"] == "CLOSED",
    }
    filtered = [c_ for c_ in cases if filter_map.get(selected_tab, lambda x: True)(c_)]

    if not filtered:
        st.markdown(f"""
        <div style="padding:2rem 1rem;text-align:center;">
            <div style="font-size:24px;margin-bottom:0.5rem;">✓</div>
            <div style="font-size:13px;color:{COLORS['text_muted']};">
                Sin casos en esta categoría
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    # ── Case list items ────────────────────────────────────────────────
    st.markdown('<div style="overflow-y:auto;max-height:calc(100vh - 200px);">', unsafe_allow_html=True)

    for case in filtered:
        is_selected = case["id"] == selected_id
        _render_case_item(case, is_selected, role)

    st.markdown('</div>', unsafe_allow_html=True)


def _render_case_item(case: dict, is_selected: bool, role: str) -> None:
    c = COLORS
    priority = case["priority"]
    status = case["status"]
    p_color = PRIORITY_COLORS.get(priority, c["text_muted"])
    s_color = STATUS_COLORS.get(status, c["text_muted"])
    p_icon = _PRIORITY_ICON.get(priority, "·")
    ago = time_ago(case["created_at"])

    bg = c["bg_selected"] if is_selected else "transparent"
    border_left = f"3px solid {c['accent']}" if is_selected else f"3px solid transparent"
    text_opacity = "0.45" if status == "CLOSED" else "1"

    # Risk score bar fill
    score = case["risk_score"]
    risk_color = _risk_color(case["risk_level"])
    bar_width = int(score * 0.8)  # 80px max

    st.markdown(f"""
    <div class="case-item {'case-selected' if is_selected else ''}" style="
        padding:0.75rem 1rem;
        background:{bg};
        border-left:{border_left};
        border-bottom:1px solid {c['border_subtle']};
        cursor:pointer;
        transition:all 0.15s ease;
        opacity:{text_opacity};
        animation: {'fadeIn 0.2s ease' if is_selected else 'none'};
    " onclick="null">
        <!-- Row 1: ID + priority badge -->
        <div style="display:flex;align-items:center;justify-content:space-between;
            margin-bottom:4px;">
            <span style="font-size:11px;color:{c['text_muted']};
                font-variant-numeric:tabular-nums;letter-spacing:0.02em;">{case['id']}</span>
            <span style="
                background:rgba({_hex_rgb(p_color)},0.12);
                color:{p_color};
                border-radius:4px;padding:1px 6px;
                font-size:10px;font-weight:700;letter-spacing:0.04em;
            ">{p_icon} {priority}</span>
        </div>
        <!-- Row 2: Client name -->
        <div style="font-size:13px;font-weight:600;color:{c['text_primary']};
            margin-bottom:3px;white-space:nowrap;overflow:hidden;
            text-overflow:ellipsis;">{case['client_name']}</div>
        <!-- Row 3: Overdue info -->
        <div style="font-size:12px;color:{c['text_secondary']};margin-bottom:6px;">
            {case['overdue_days']}d mora · {fmt_currency(case['overdue_amount'], case['currency'])}
        </div>
        <!-- Row 4: Status + time + risk bar -->
        <div style="display:flex;align-items:center;justify-content:space-between;">
            <span style="
                background:rgba({_hex_rgb(s_color)},0.10);
                color:{s_color};border-radius:4px;
                padding:1px 6px;font-size:10px;font-weight:500;
            ">{STATUS_LABELS.get(status, status)}</span>
            <div style="display:flex;align-items:center;gap:6px;">
                <div style="width:50px;height:3px;background:{c['border_default']};
                    border-radius:3px;overflow:hidden;">
                    <div style="width:{score:.0f}%;height:100%;background:{risk_color};
                        border-radius:3px;"></div>
                </div>
                <span style="font-size:10px;color:{c['text_muted']};">{score:.0f}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Invisible Streamlit button overlaid conceptually — use a real button
    btn_label = f"{'▶ ' if case['id'] == sm.get('selected_case_id') else ''}{case['id']}"
    if st.button(
        label=btn_label,
        key=f"select_{case['id']}",
        use_container_width=True,
    ):
        bus.emit("CASE_SELECTED", {"case_id": case["id"]})


def _risk_color(level: str) -> str:
    return {
        "ALTO":   "#EF4444",
        "MEDIO":  "#F59E0B",
        "BAJO":   "#22C55E",
    }.get(level, "#888888")


def _hex_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
    return "128,128,128"
