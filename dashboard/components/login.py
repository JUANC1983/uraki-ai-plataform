# dashboard/components/login.py
"""
Login screen — shown when no auth token is present.
Requires a configured backend. Blocks access if URAKI_API_URL is not set.
"""
import os
import streamlit as st
from styles.theme import COLORS
from core.auth import login
from services.api_client import BACKEND_CONFIGURED, API_BASE

LOGO_SVG = """
<svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="48" height="48" rx="12" fill="#E85D2A"/>
  <path d="M12 13h6v14a6 6 0 0 0 12 0V13h6v14a12 12 0 0 1-24 0V13z" fill="white"/>
</svg>
"""


def render() -> None:
    c = COLORS
    st.markdown(f"""
    <style>
    .stApp {{ background: {c['bg_primary']} !important; }}
    #MainMenu, footer, header {{ visibility:hidden; }}
    .stDeployButton {{ display:none; }}
    </style>
    """, unsafe_allow_html=True)

    if not BACKEND_CONFIGURED:
        _render_not_configured(c)
        return

    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        st.markdown(f"""
        <div style="text-align:center;padding:3rem 0 1.5rem;">
            {LOGO_SVG}
            <div style="margin-top:0.75rem;">
                <div style="font-size:22px;font-weight:700;color:{c['text_primary']};
                    letter-spacing:-0.02em;">URAKI OPS</div>
                <div style="font-size:12px;color:{c['text_muted']};
                    text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;">
                    Plataforma de Decisiones
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="
            background:{c['bg_elevated']};
            border:1px solid {c['border_default']};
            border-radius:14px;
            padding:2rem;
            margin-bottom:1rem;
        ">
        """, unsafe_allow_html=True)

        tenant_slug = st.text_input("Tenant", placeholder="mi-organizacion",
                                    key="login_tenant")
        email    = st.text_input("Correo electrónico", placeholder="operador@uraki.co",
                                 key="login_email")
        password = st.text_input("Contraseña", placeholder="••••••••",
                                 type="password", key="login_pw")

        st.markdown('<div style="height:0.75rem;"></div>', unsafe_allow_html=True)

        st.markdown('<div class="uraki-btn-primary">', unsafe_allow_html=True)
        if st.button("Iniciar sesión", use_container_width=True, key="login_btn"):
            if not tenant_slug or not email or not password:
                st.error("Completa todos los campos.")
            else:
                with st.spinner("Autenticando..."):
                    ok, err = login(tenant_slug.strip(), email.strip(), password)
                if ok:
                    st.rerun()
                else:
                    st.error(err)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        # Show backend connection status
        st.markdown(f"""
        <div style="text-align:center;margin-top:0.75rem;">
            <span style="font-size:11px;color:{c['text_muted']};">
                Conectado a:
                <span style="color:{c['success']};font-weight:500;">
                    {API_BASE}</span>
            </span>
        </div>
        """, unsafe_allow_html=True)


def _render_not_configured(c: dict) -> None:
    """Blocking screen shown when URAKI_API_URL is not set."""
    _, center, _ = st.columns([1, 1.5, 1])
    with center:
        st.markdown(f"""
        <div style="text-align:center;padding:4rem 0 2rem;">
            <div style="font-size:40px;margin-bottom:1rem;">⚠</div>
            <div style="font-size:20px;font-weight:700;color:{c['text_primary']};
                margin-bottom:0.5rem;letter-spacing:-0.02em;">
                Sistema no configurado
            </div>
            <div style="font-size:13px;color:{c['text_muted']};
                max-width:380px;margin:0 auto;line-height:1.6;margin-bottom:2rem;">
                URAKI OPS requiere una conexión a un backend para operar.
                Este sistema no tiene modo de demostración ni datos simulados.
            </div>
        </div>
        <div style="
            background:{c['bg_elevated']};
            border:1px solid {c['border_default']};
            border-radius:12px;
            padding:1.5rem;
            margin-bottom:1.5rem;
        ">
            <div style="font-size:11px;font-weight:600;color:{c['accent']};
                text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.75rem;">
                Configuración requerida</div>
            <div style="font-size:12px;color:{c['text_secondary']};
                line-height:1.8;font-family:monospace;">
                export URAKI_API_URL=https://tu-api.uraki.co<br/>
                streamlit run dashboard/app.py
            </div>
        </div>
        <div style="
            background:rgba(239,68,68,0.06);
            border:1px solid rgba(239,68,68,0.2);
            border-radius:10px;
            padding:1rem;
            font-size:12px;
            color:{c['text_muted']};
            line-height:1.7;
        ">
            <strong style="color:{c['danger']};">¿Por qué no hay modo demo?</strong><br/>
            URAKI OPS es una plataforma de decisiones para casos reales.
            Mostrar datos simulados en producción podría inducir acciones legales erróneas.
            Conecta un backend real para usar el sistema.
        </div>
        """, unsafe_allow_html=True)
