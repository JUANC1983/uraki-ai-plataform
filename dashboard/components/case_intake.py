# dashboard/components/case_intake.py
"""
Case Intake Form — fast input for Quick Mode.

Design goals:
  - Fill in under 30 seconds
  - Minimal required fields (3 core: name, days, amount)
  - Dynamic fields expand based on case type selection
  - Smart defaults from tenant config and prior entries
  - Inline validation with clear error messages before submit
  - Single prominent "Generar" button

Case types:
  mora      — simple overdue (3 fields)
  poliza    — with insurance policy (+1 field, auto-sets has_policy)
  legal     — with legal action (+1 field, auto-sets has_legal_action)
  complejo  — all fields (6 fields)

Returns the case payload dict, or None if validation fails.
"""
from __future__ import annotations

import streamlit as st
import core.state_manager as sm
from styles.theme import COLORS
from utils.formatters import fmt_currency

# ── Case type definitions ─────────────────────────────────────────────────────

_CASE_TYPES = {
    "mora":     ("📋 Mora simple",    "Pago atrasado sin complicaciones"),
    "poliza":   ("🛡 Con póliza",     "Hay póliza de seguro aplicable"),
    "legal":    ("⚖ Acción legal",   "Proceso legal en curso"),
    "complejo": ("🔍 Caso complejo",  "Múltiples factores a considerar"),
}

_SMART_DEFAULTS = {
    "mora":     {"has_policy": False, "has_legal_action": False, "previous_overdue_count": 0},
    "poliza":   {"has_policy": True,  "has_legal_action": False, "previous_overdue_count": 0},
    "legal":    {"has_policy": False, "has_legal_action": True,  "previous_overdue_count": 1},
    "complejo": {"has_policy": True,  "has_legal_action": True,  "previous_overdue_count": 2},
}


def _normalize_name(name: str) -> str:
    """Title-case and strip; preserves compound particles (de, del, la...)."""
    particles = {"de", "del", "la", "las", "los", "el", "y"}
    words = name.strip().split()
    result = []
    for i, w in enumerate(words):
        result.append(w if (i > 0 and w.lower() in particles) else w.capitalize())
    return " ".join(result)


def render() -> dict | None:
    """
    Render the intake form. Returns validated case payload on submit, None otherwise.
    Stores form state in session_state so values survive Streamlit reruns.
    """
    c = COLORS

    # ── Case type selector ─────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
        letter-spacing:0.08em;margin-bottom:0.4rem;">Tipo de caso</div>
    """, unsafe_allow_html=True)

    cols = st.columns(4)
    current_type = sm.get("qi_case_type", "mora")
    for i, (key, (label, desc)) in enumerate(_CASE_TYPES.items()):
        with cols[i]:
            selected = current_type == key
            border   = c["accent"] if selected else c["border_default"]
            bg       = c["accent_muted"] if selected else c["bg_elevated"]
            if st.button(
                label,
                key=f"qi_type_{key}",
                use_container_width=True,
                help=desc,
            ):
                if current_type != key:
                    sm.set("qi_case_type", key)
                    # Apply smart defaults when switching type
                    defaults = _SMART_DEFAULTS[key]
                    for k, v in defaults.items():
                        sm.set(f"qi_{k}", v)
                    st.rerun()
            # Visual indicator for selected type
            st.markdown(f"""
            <div style="
                height:2px;background:{border};
                border-radius:1px;margin-top:-8px;
                transition:background 0.2s;
            "></div>
            """, unsafe_allow_html=True)

    case_type = sm.get("qi_case_type", "mora")
    defaults  = _SMART_DEFAULTS[case_type]

    st.markdown('<div style="height:0.6rem;"></div>', unsafe_allow_html=True)

    # ── Core fields (always visible) ───────────────────────────────────────────
    col_name, col_days = st.columns([1.6, 1])

    with col_name:
        raw_name = st.text_input(
            "Nombre del arrendatario *",
            value=sm.get("qi_client_name", ""),
            key="qi_input_name",
            placeholder="Ej: María García López",
            help="Nombre completo del arrendatario",
        )
        # Smart correction: title-case + strip
        client_name = _normalize_name(raw_name)
        if client_name != sm.get("qi_client_name", ""):
            sm.set("qi_client_name", client_name)

    with col_days:
        overdue_days = st.number_input(
            "Días de mora *",
            min_value=1,
            max_value=1825,
            value=int(sm.get("qi_overdue_days", 30)),
            step=1,
            key="qi_input_days",
            help="Días desde el último pago",
        )
        if overdue_days != sm.get("qi_overdue_days", 30):
            sm.set("qi_overdue_days", overdue_days)

    overdue_amount = st.number_input(
        "Monto vencido (COP) *",
        min_value=0,
        max_value=500_000_000,
        value=int(sm.get("qi_overdue_amount", 0)),
        step=50_000,
        format="%d",
        key="qi_input_amount",
        help="Valor total de la deuda en mora",
    )
    if overdue_amount != sm.get("qi_overdue_amount", 0):
        sm.set("qi_overdue_amount", overdue_amount)

    # ── Dynamic fields ─────────────────────────────────────────────────────────
    has_policy       = defaults["has_policy"]
    has_legal_action = defaults["has_legal_action"]
    prev_count       = defaults["previous_overdue_count"]

    if case_type in ("poliza", "complejo"):
        has_policy = st.toggle(
            "🛡 Póliza de seguro activa",
            value=bool(sm.get("qi_has_policy", defaults["has_policy"])),
            key="qi_input_policy",
        )
        sm.set("qi_has_policy", has_policy)

    if case_type in ("legal", "complejo"):
        has_legal_action = st.toggle(
            "⚖ Acción legal en curso",
            value=bool(sm.get("qi_has_legal_action", defaults["has_legal_action"])),
            key="qi_input_legal",
        )
        sm.set("qi_has_legal_action", has_legal_action)

    if case_type == "complejo":
        prev_count = st.number_input(
            "Incidencias previas de mora",
            min_value=0,
            max_value=20,
            value=int(sm.get("qi_prev_count", defaults["previous_overdue_count"])),
            step=1,
            key="qi_input_prev",
        )
        sm.set("qi_prev_count", prev_count)

    # ── Inline validation ──────────────────────────────────────────────────────
    errors:   list[str] = []
    warnings: list[str] = []

    stripped_name = client_name.strip()
    if not stripped_name:
        errors.append("Nombre del arrendatario es obligatorio")
    elif len(stripped_name) < 3:
        errors.append("El nombre debe tener al menos 3 caracteres")
    elif stripped_name.replace(" ", "").isdigit():
        errors.append("El nombre no puede ser solo números")
    elif not any(ch.isalpha() for ch in stripped_name):
        errors.append("El nombre debe contener letras")

    if overdue_days < 1:
        errors.append("Los días de mora deben ser al menos 1")
    elif overdue_days > 730:
        warnings.append("¿Días correctos? Superan 2 años de mora")

    if overdue_amount <= 0:
        errors.append("El monto vencido debe ser mayor a 0")
    elif overdue_amount > 100_000_000:
        warnings.append("¿Monto correcto? Supera $100 millones COP")

    # Blocking errors
    for err in errors:
        st.markdown(f"""
        <div style="font-size:11px;color:#EF4444;margin-bottom:2px;">⚠ {err}</div>
        """, unsafe_allow_html=True)

    # Non-blocking warnings
    for warn in warnings:
        st.markdown(f"""
        <div style="font-size:11px;color:#F59E0B;margin-bottom:2px;">⚠ {warn}</div>
        """, unsafe_allow_html=True)

    # ── Amount preview ─────────────────────────────────────────────────────────
    if overdue_amount > 0 and not errors:
        risk_hint = (
            "Alto" if overdue_days > 90 or overdue_amount > 3_000_000
            else "Medio" if overdue_days > 45 or overdue_amount > 1_000_000
            else "Bajo"
        )
        hint_color = {"Alto": "#EF4444", "Medio": "#F59E0B", "Bajo": "#22C55E"}[risk_hint]
        st.markdown(f"""
        <div style="
            background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:6px;padding:6px 10px;margin-bottom:0.4rem;
            display:flex;align-items:center;justify-content:space-between;
        ">
            <span style="font-size:11px;color:{c['text_muted']};">
                {client_name.strip() or '—'} · {overdue_days}d ·
                {fmt_currency(overdue_amount, 'COP')}</span>
            <span style="font-size:11px;font-weight:600;color:{hint_color};">
                Riesgo estimado: {risk_hint}</span>
        </div>
        """, unsafe_allow_html=True)

    # ── Submit button ──────────────────────────────────────────────────────────
    st.markdown('<div style="margin-top:0.25rem;">', unsafe_allow_html=True)
    submit = st.button(
        "⚡ Generar decisión y respuesta",
        key="qi_submit",
        use_container_width=True,
        disabled=bool(errors),
        type="primary",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    if not submit:
        return None

    if errors:
        return None

    return {
        "client_name":           client_name.strip(),
        "overdue_days":          int(overdue_days),
        "overdue_amount":        float(overdue_amount),
        "has_policy":            bool(has_policy),
        "has_legal_action":      bool(has_legal_action),
        "previous_overdue_count": int(prev_count),
        "currency":              "COP",
        "status":                "NEW",
        "priority":              "MEDIUM",
        "case_type":             case_type,
    }
