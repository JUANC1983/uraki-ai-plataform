# dashboard/app.py
"""
URAKI OPS — Operational Decision Platform
Run: streamlit run dashboard/app.py

Functional prototype. No fallback demo data.
Requires URAKI_API_URL environment variable.
"""
import sys
import os
import textwrap

# ── Path setup — must be first ──────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

# Streamlit treats four-space-indented Markdown as a code block even when
# unsafe HTML is enabled. Most dashboard components use readable indented
# triple-quoted HTML, so normalize it once at the application boundary.
if not getattr(st.markdown, "_uraki_dedents_html", False):
    _streamlit_markdown = st.markdown

    def _markdown(body, *args, **kwargs):
        if kwargs.get("unsafe_allow_html") and isinstance(body, str):
            body = "\n".join(
                line.lstrip() for line in textwrap.dedent(body).splitlines()
            ).strip()
        return _streamlit_markdown(body, *args, **kwargs)

    _markdown._uraki_dedents_html = True
    st.markdown = _markdown

# ── Page config — must be before any other st call ──────────────────────────
st.set_page_config(
    page_title="URAKI OPS",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Imports after path setup ─────────────────────────────────────────────────
import core.state_manager as sm
from styles.theme import get_css, COLORS
from services.api_client import BACKEND_CONFIGURED


# ---------------------------------------------------------------------------
# Flash message consumer
# ---------------------------------------------------------------------------

def _render_flash() -> None:
    """Consume and display one-shot error/success banners at top of page."""
    err, ok = sm.consume_flash()
    if err:
        st.error(err)
    if ok:
        st.success(ok)


# ---------------------------------------------------------------------------
# Auth expiry handler
# ---------------------------------------------------------------------------

def _handle_auth_error() -> None:
    """Called when a 401 propagates to the app layer."""
    from core.auth import logout
    logout()
    sm.flash_error("Tu sesión expiró. Inicia sesión nuevamente.")
    st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Initialize session state defaults
    sm.init()

    # 2. Inject global CSS design system
    st.markdown(get_css(), unsafe_allow_html=True)

    # 3. Login gate — a real backend identity is required in every environment.
    from core.auth import is_authenticated

    if not is_authenticated():
        from components.login import render as render_login
        render_login()
        return

    # 4. Tenant isolation — flush caches on tenant switch
    from core.tenant_manager import assert_tenant_isolation
    assert_tenant_isolation()

    # 5. Environment banner (non-production only)
    from core.environment import render_env_banner
    render_env_banner()

    # 5b. Flash messages (one-shot banners from previous rerun)
    _render_flash()

    # 6. Topbar (logo + wordmark + clock + tenant + role)
    from components.topbar import render as render_topbar
    render_topbar()

    # 7. System status strip
    _render_system_strip()

    # 8. Metrics bar (momentum system)
    from components.metrics import render as render_metrics
    from services.case_service import CaseService
    cs = CaseService()
    db_metrics = cs.get_metrics()
    render_metrics(db_metrics)

    # 9. Main layout — switch based on view mode
    view = sm.get("view_mode", "flow")

    try:
        if view == "flow":
            from layouts.flow_mode import render as render_flow
            render_flow()
        elif view == "quick":
            from layouts.quick_mode import render as render_quick
            render_quick()
        elif view == "executive":
            from layouts.executive import render as render_executive
            render_executive()
        else:
            from layouts.flow_mode import render as render_flow
            render_flow()

    except Exception as exc:
        # Catch auth errors raised inside layout code
        from services.api_client import AuthError
        if isinstance(exc, AuthError) or "401" in str(exc) or "expired" in str(exc).lower():
            _handle_auth_error()
        else:
            raise


# ---------------------------------------------------------------------------
# System status strip
# ---------------------------------------------------------------------------

def _render_system_strip() -> None:
    """
    Thin strip below topbar showing system status.
    - Backend not configured → red/blocked warning
    - Backend configured → subtle confirmation
    """
    c = COLORS

    if not BACKEND_CONFIGURED:
        st.markdown(f"""
        <div style="
            background:rgba(239,68,68,0.08);
            border-bottom:1px solid rgba(239,68,68,0.25);
            padding:5px 1.5rem;
            display:flex;align-items:center;gap:10px;
        ">
            <span style="color:{c['danger']};font-size:12px;font-weight:600;">
                ⚠ BACKEND NO CONFIGURADO</span>
            <span style="color:{c['text_muted']};font-size:11px;">
                Configura URAKI_API_URL y reinicia el servidor para operar.</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        c = COLORS
        st.markdown(f"""
        <div style="
            background:rgba(34,197,94,0.04);
            border-bottom:1px solid rgba(34,197,94,0.12);
            padding:3px 1.5rem;
            display:flex;align-items:center;gap:10px;
        ">
            <span style="
                width:6px;height:6px;border-radius:50%;
                background:#22C55E;display:inline-block;
                box-shadow:0 0 6px rgba(34,197,94,0.6);
                animation:pulse-beacon 2s ease-in-out infinite;
            "></span>
            <span style="font-size:10px;color:{c['text_muted']};">
                Backend conectado</span>
        </div>
        <style>
        @keyframes pulse-beacon {{
            0%, 100% {{ opacity:1; }}
            50%       {{ opacity:0.4; }}
        }}
        </style>
        """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
