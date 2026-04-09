# dashboard/styles/theme.py
"""
URAKI OPS Design System
Minimalist, premium SaaS — comparable to Stripe/Linear visual quality.
Primary accent: #E85D2A (URAKI Orange)
"""

COLORS = {
    "bg_primary":      "#0B0B0B",
    "bg_secondary":    "#111111",
    "bg_elevated":     "#171717",
    "bg_card":         "#141414",
    "bg_card_hover":   "#1A1A1A",
    "bg_selected":     "#1C1410",       # warm dark tint for selected case
    "border_subtle":   "#1E1E1E",
    "border_default":  "#282828",
    "border_accent":   "rgba(232,93,42,0.35)",
    "accent":          "#E85D2A",
    "accent_hover":    "#F0703D",
    "accent_dim":      "#C24E22",
    "accent_muted":    "rgba(232,93,42,0.10)",
    "accent_glow":     "rgba(232,93,42,0.06)",
    "text_primary":    "#EEEEEE",
    "text_secondary":  "#888888",
    "text_muted":      "#444444",
    "success":         "#22C55E",
    "success_muted":   "rgba(34,197,94,0.10)",
    "warning":         "#F59E0B",
    "warning_muted":   "rgba(245,158,11,0.10)",
    "danger":          "#EF4444",
    "danger_muted":    "rgba(239,68,68,0.10)",
    "info":            "#3B82F6",
    "info_muted":      "rgba(59,130,246,0.10)",
    "critical":        "#A855F7",
    "critical_muted":  "rgba(168,85,247,0.10)",
}

# Risk / priority → color mapping
RISK_COLORS = {
    "ALTO":   COLORS["danger"],
    "MEDIO":  COLORS["warning"],
    "BAJO":   COLORS["success"],
    "HIGH":   COLORS["danger"],
    "MEDIUM": COLORS["warning"],
    "LOW":    COLORS["success"],
}

PRIORITY_COLORS = {
    "CRITICAL": COLORS["critical"],
    "HIGH":     COLORS["danger"],
    "MEDIUM":   COLORS["warning"],
    "LOW":      COLORS["success"],
}

STATUS_COLORS = {
    "NEW":                 COLORS["info"],
    "IN_REVIEW":           COLORS["warning"],
    "DECISION_GENERATED":  COLORS["accent"],
    "ESCALATED":           COLORS["critical"],
    "CLOSED":              COLORS["text_muted"],
}

STATUS_LABELS = {
    "NEW":                 "Nuevo",
    "IN_REVIEW":           "En revisión",
    "DECISION_GENERATED":  "Decisión lista",
    "ESCALATED":           "Escalado",
    "CLOSED":              "Cerrado",
}


def get_css() -> str:
    c = COLORS
    return f"""
<style>
/* ── Reset & globals ──────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    color: {c['text_primary']} !important;
}}

/* Hide Streamlit chrome */
#MainMenu, footer, header {{ visibility: hidden; height: 0; }}
.stDeployButton {{ display: none; }}
[data-testid="stToolbar"] {{ display: none; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stStatusWidget"] {{ display: none; }}

/* Page background */
.stApp {{
    background: {c['bg_primary']} !important;
}}

/* Main container — remove default padding */
.main .block-container {{
    padding: 0 !important;
    max-width: 100% !important;
}}

/* ── Scrollbars ───────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: {c['bg_secondary']}; }}
::-webkit-scrollbar-thumb {{ background: {c['border_default']}; border-radius: 4px; }}
::-webkit-scrollbar-thumb:hover {{ background: {c['text_muted']}; }}

/* ── Streamlit columns ────────────────────────────────────────────── */
[data-testid="stHorizontalBlock"] {{
    gap: 0 !important;
    align-items: flex-start;
}}

/* ── Buttons — override all Streamlit defaults ────────────────────── */
.stButton > button {{
    background: {c['bg_elevated']} !important;
    color: {c['text_secondary']} !important;
    border: 1px solid {c['border_default']} !important;
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 0.45rem 1rem !important;
    transition: all 0.15s ease !important;
    cursor: pointer !important;
    white-space: nowrap !important;
}}
.stButton > button:hover {{
    background: {c['bg_card_hover']} !important;
    border-color: {c['border_accent']} !important;
    color: {c['text_primary']} !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
}}
.stButton > button:active {{
    transform: translateY(0) !important;
}}

/* Primary accent button */
.uraki-btn-primary > button {{
    background: {c['accent']} !important;
    color: white !important;
    border-color: {c['accent']} !important;
    font-weight: 600 !important;
}}
.uraki-btn-primary > button:hover {{
    background: {c['accent_hover']} !important;
    border-color: {c['accent_hover']} !important;
    box-shadow: 0 4px 16px rgba(232,93,42,0.35) !important;
}}

/* Danger button */
.uraki-btn-danger > button {{
    background: {c['danger_muted']} !important;
    color: {c['danger']} !important;
    border-color: rgba(239,68,68,0.3) !important;
}}
.uraki-btn-danger > button:hover {{
    background: rgba(239,68,68,0.18) !important;
    border-color: {c['danger']} !important;
    color: {c['danger']} !important;
    box-shadow: 0 4px 12px rgba(239,68,68,0.2) !important;
}}

/* Success / resolve button */
.uraki-btn-success > button {{
    background: {c['success_muted']} !important;
    color: {c['success']} !important;
    border-color: rgba(34,197,94,0.3) !important;
}}
.uraki-btn-success > button:hover {{
    background: rgba(34,197,94,0.18) !important;
    border-color: {c['success']} !important;
    color: {c['success']} !important;
    box-shadow: 0 4px 12px rgba(34,197,94,0.2) !important;
}}

/* ── Selectbox ────────────────────────────────────────────────────── */
.stSelectbox > div > div {{
    background: {c['bg_elevated']} !important;
    border: 1px solid {c['border_default']} !important;
    border-radius: 8px !important;
    color: {c['text_primary']} !important;
    font-size: 13px !important;
}}
.stSelectbox > div > div:hover {{
    border-color: {c['border_accent']} !important;
}}

/* ── Text input ───────────────────────────────────────────────────── */
.stTextInput > div > div > input {{
    background: {c['bg_elevated']} !important;
    border: 1px solid {c['border_default']} !important;
    border-radius: 8px !important;
    color: {c['text_primary']} !important;
    font-size: 13px !important;
}}

/* ── File uploader ────────────────────────────────────────────────── */
[data-testid="stFileUploader"] {{
    background: {c['bg_elevated']} !important;
    border: 1.5px dashed {c['border_default']} !important;
    border-radius: 12px !important;
    transition: all 0.2s ease !important;
}}
[data-testid="stFileUploader"]:hover {{
    border-color: {c['border_accent']} !important;
    background: {c['accent_glow']} !important;
}}
[data-testid="stFileUploader"] label {{
    color: {c['text_secondary']} !important;
    font-size: 13px !important;
}}

/* ── Metrics ──────────────────────────────────────────────────────── */
[data-testid="stMetric"] {{
    background: {c['bg_elevated']} !important;
    border: 1px solid {c['border_subtle']} !important;
    border-radius: 10px !important;
    padding: 0.75rem 1rem !important;
}}
[data-testid="stMetricLabel"] {{
    color: {c['text_secondary']} !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}}
[data-testid="stMetricValue"] {{
    color: {c['text_primary']} !important;
    font-size: 22px !important;
    font-weight: 700 !important;
}}
[data-testid="stMetricDelta"] {{
    font-size: 11px !important;
}}

/* ── Divider ──────────────────────────────────────────────────────── */
hr {{
    border: none !important;
    border-top: 1px solid {c['border_subtle']} !important;
    margin: 0.75rem 0 !important;
}}

/* ── Tabs ─────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent !important;
    border-bottom: 1px solid {c['border_subtle']} !important;
    gap: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: {c['text_muted']} !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    padding: 0.5rem 1rem !important;
    border-radius: 0 !important;
    border-bottom: 2px solid transparent !important;
}}
.stTabs [aria-selected="true"] {{
    color: {c['accent']} !important;
    border-bottom-color: {c['accent']} !important;
    background: transparent !important;
}}

/* ── Expander ─────────────────────────────────────────────────────── */
.streamlit-expanderHeader {{
    background: {c['bg_elevated']} !important;
    border: 1px solid {c['border_subtle']} !important;
    border-radius: 8px !important;
    color: {c['text_secondary']} !important;
    font-size: 13px !important;
}}
.streamlit-expanderContent {{
    background: {c['bg_card']} !important;
    border: 1px solid {c['border_subtle']} !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px !important;
}}

/* ── Spinner ──────────────────────────────────────────────────────── */
.stSpinner > div {{
    border-top-color: {c['accent']} !important;
}}

/* ── Toast / success messages ─────────────────────────────────────── */
.stToast {{
    background: {c['bg_elevated']} !important;
    border: 1px solid {c['border_default']} !important;
    border-radius: 10px !important;
}}

/* ── Markdown text ────────────────────────────────────────────────── */
.stMarkdown p, .stMarkdown li {{
    color: {c['text_secondary']} !important;
    font-size: 13px !important;
    line-height: 1.6 !important;
}}
.stMarkdown h3 {{
    color: {c['text_primary']} !important;
    font-size: 14px !important;
    font-weight: 600 !important;
}}

/* ── Textarea ─────────────────────────────────────────────────────── */
.stTextArea > div > div > textarea {{
    background: {c['bg_elevated']} !important;
    border: 1px solid {c['border_default']} !important;
    border-radius: 8px !important;
    color: {c['text_primary']} !important;
    font-size: 13px !important;
    font-family: 'Inter', sans-serif !important;
    line-height: 1.6 !important;
}}

/* ── Column separators ────────────────────────────────────────────── */
.col-left {{
    border-right: 1px solid {c['border_subtle']};
    min-height: 100vh;
    background: {c['bg_secondary']};
}}
.col-center {{
    min-height: 100vh;
    background: {c['bg_primary']};
}}
.col-right {{
    border-left: 1px solid {c['border_subtle']};
    min-height: 100vh;
    background: {c['bg_secondary']};
}}

/* ── Keyframes ────────────────────────────────────────────────────── */
@keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(6px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes pulse-accent {{
    0%, 100% {{ box-shadow: 0 0 0 0 rgba(232,93,42,0); }}
    50%       {{ box-shadow: 0 0 0 6px rgba(232,93,42,0.12); }}
}}
@keyframes slideUp {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}

.uraki-fade-in  {{ animation: fadeIn 0.25s ease forwards; }}
.uraki-slide-up {{ animation: slideUp 0.3s ease forwards; }}
</style>
"""
