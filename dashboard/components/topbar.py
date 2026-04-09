# dashboard/components/topbar.py
"""
URAKI OPS Topbar — production version.
Left:   Logo + URAKI OPS wordmark + tenant name (with dynamic branding)
Center: Live Bogotá clock
Right:  Plan badge + Role/view controls + Logout
"""
import streamlit as st
import streamlit.components.v1 as components
import core.state_manager as sm
from core.auth import get_user, get_role, get_tenant_id, get_tenant_config, logout
from core.config_manager import get_branding
from styles.theme import COLORS

LOGO_SVG = """
<svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="32" height="32" rx="8" fill="{color}"/>
  <path d="M8 9h4v9a4 4 0 0 0 8 0V9h4v9a8 8 0 0 1-16 0V9z" fill="white"/>
</svg>
"""

_ROLE_ICONS = {
    "operador":  "👤",
    "legal":     "⚖",
    "gerente":   "📊",
    "admin":     "🔧",
    "auditor":   "🔍",
}

_PLAN_BADGES = {
    "enterprise": ("ENT", "#A855F7", "rgba(168,85,247,0.12)"),
    "pro":        ("PRO", "#E85D2A", "rgba(232,93,42,0.12)"),
    "standard":   ("STD", "#3B82F6", "rgba(59,130,246,0.12)"),
}


def render() -> None:
    c        = COLORS
    user     = get_user()
    role     = get_role()
    branding = get_branding()

    tenant_name   = branding["company_name"]
    primary_color = branding["primary_color"]
    plan          = branding["plan"]

    # Health indicator dot (cached, non-blocking)
    from services.health_service import HealthService
    health_data = st.session_state.get("_topbar_health", {})
    _health_recheck = st.session_state.get("_topbar_health_tick", 0)
    import time as _time
    if _time.time() - _health_recheck > 30:
        _h, _ = HealthService().get_health()
        health_data = _h or {}
        st.session_state["_topbar_health"] = health_data
        st.session_state["_topbar_health_tick"] = _time.time()
    _overall = health_data.get("status", "down")
    _health_dot_color = {"ok": "#22C55E", "degraded": "#F59E0B"}.get(_overall, "#EF4444")
    _health_dot_title = {"ok": "Backend OK", "degraded": "Backend degradado"}.get(_overall, "Backend sin conexión")
    health_dot = (
        f'<span title="{_health_dot_title}" style="'
        f'display:inline-block;width:8px;height:8px;border-radius:50%;'
        f'background:{_health_dot_color};margin-left:8px;'
        f'box-shadow:0 0 0 2px {_health_dot_color}44;'
        f'vertical-align:middle;"></span>'
    )

    logo_svg  = LOGO_SVG.replace("{color}", primary_color)
    plan_label, plan_fg, plan_bg = _PLAN_BADGES.get(plan, _PLAN_BADGES["standard"])

    plan_badge = (
        f'<span style="background:{plan_bg};color:{plan_fg};'
        f'border:1px solid {plan_fg}33;border-radius:4px;'
        f'padding:1px 6px;font-size:10px;font-weight:700;'
        f'letter-spacing:0.05em;margin-left:6px;">{plan_label}</span>'
    )

    # ── Topbar HTML ──────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="
        display:flex;align-items:center;justify-content:space-between;
        padding:0 1.5rem;height:56px;
        background:{c['bg_secondary']};
        border-bottom:1px solid {c['border_subtle']};
        position:sticky;top:0;z-index:999;
    ">
        <!-- Left: Logo + wordmark + tenant -->
        <div style="display:flex;align-items:center;gap:10px;min-width:200px;">
            {logo_svg}
            <div>
                <div style="display:flex;align-items:center;gap:4px;">
                    <span style="font-size:15px;font-weight:700;
                        color:{c['text_primary']};letter-spacing:-0.02em;
                        line-height:1.1;">URAKI OPS</span>
                    {plan_badge}
                    {health_dot}
                </div>
                <div style="font-size:10px;color:{c['text_muted']};
                    letter-spacing:0.1em;text-transform:uppercase;">
                    {tenant_name[:22]}{'…' if len(tenant_name) > 22 else ''}
                </div>
            </div>
        </div>

        <!-- Center: clock slot (filled by JS component below) -->
        <div style="flex:1;display:flex;justify-content:center;"></div>

        <!-- Right: user info -->
        <div style="min-width:340px;display:flex;align-items:center;
            gap:8px;justify-content:flex-end;">
            <span style="font-size:11px;color:{c['text_muted']};">
                {_ROLE_ICONS.get(role,'👤')}
                {user.get('name') or user.get('email','—')}
                &nbsp;·&nbsp;
                <span style="color:{primary_color};font-weight:500;">
                    {role.capitalize()}</span>
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Right-side controls ──────────────────────────────────────────────
    _, col_view, col_tenant, col_logout = st.columns([3.5, 1.1, 1.4, 0.7])

    with col_view:
        view_options = {
            "flow":        "⚡ Flow",
            "quick":       "🚀 Quick",
            "executive":   "📊 Gerencial",
            "observability": "📡 Sistema",
        }
        current_view = sm.get("view_mode", "flow")
        new_view = st.selectbox(
            label="",
            options=list(view_options.keys()),
            format_func=lambda v: view_options[v],
            index=list(view_options.keys()).index(current_view)
                  if current_view in view_options else 0,
            key="view_mode_select",
            label_visibility="collapsed",
        )
        if new_view != current_view:
            sm.set("view_mode", new_view)
            st.rerun()

    with col_tenant:
        tid = get_tenant_id() or "—"
        st.markdown(f"""
        <div style="
            background:{c['bg_elevated']};
            border:1px solid {c['border_subtle']};
            border-radius:8px;padding:6px 10px;
            font-size:12px;color:{c['text_secondary']};
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
            max-width:160px;
        " title="{tid}">
            🏢 {tenant_name[:18]}{'…' if len(tenant_name) > 18 else ''}
        </div>
        """, unsafe_allow_html=True)

    with col_logout:
        if st.button("↩", key="logout_btn", help="Cerrar sesión"):
            logout()
            st.rerun()

    # ── Live Bogotá clock (JS) ───────────────────────────────────────────
    components.html(f"""
    <div style="
        display:flex;align-items:center;gap:6px;
        background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:8px;padding:6px 16px;
        margin-top:-82px;position:relative;z-index:1000;
        width:fit-content;margin-left:auto;margin-right:auto;
    ">
        <span style="font-size:10px;color:{c['text_muted']};
            text-transform:uppercase;letter-spacing:0.1em;
            font-family:'Inter',sans-serif;">Bogotá</span>
        <span id="clk" style="
            font-size:13px;color:{c['text_secondary']};font-weight:500;
            letter-spacing:0.05em;font-family:'Inter',monospace;
            font-variant-numeric:tabular-nums;">——:——:——</span>
    </div>
    <script>
    (function(){{
        function upd(){{
            var now=new Date();
            var t=now.toLocaleTimeString('es-CO',{{
                timeZone:'America/Bogota',
                hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false
            }});
            var d=now.toLocaleDateString('es-CO',{{
                timeZone:'America/Bogota',day:'2-digit',month:'short'
            }});
            var el=document.getElementById('clk');
            if(el) el.textContent=d+' · '+t;
        }}
        upd(); setInterval(upd,1000);
    }})();
    </script>
    """, height=46, scrolling=False)
