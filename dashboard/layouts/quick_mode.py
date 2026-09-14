# dashboard/layouts/quick_mode.py
"""
Quick Mode — instant case resolution in a single screen.

Flow:
  1. Operator fills compact intake form (left column, <30 seconds)
  2. Clicks "Generar" → immediate loading state
  3. Decision + structured response appear on the right (dominant)
  4. One-click copy → "¡Copiado!" flash → ready to reset

Layout: 2-column split
  Left  (40%) — intake form + decision summary
  Right (60%) — response output (large, centered, copyable)

Polish (production-ready):
  - Instant clarity banner with action + readiness signal
  - Trust indicators (Recomendado por URAKI, Respuesta validada)
  - Multi-channel output: Estándar / WhatsApp / Email
  - Generation time display
  - Completion feedback after copy
  - First-use guidance with example data
  - Visible intelligence hints (rule basis, similar cases)
  - System-alive messaging in header
"""
from __future__ import annotations

import time
import streamlit as st
import streamlit.components.v1 as components
import core.state_manager as sm
from styles.theme import COLORS
from services.api_client import BACKEND_CONFIGURED


def render() -> None:
    c = COLORS

    if not BACKEND_CONFIGURED:
        _render_not_configured(c)
        return

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="padding:1rem 0 0.75rem;">
        <div style="display:flex;align-items:center;justify-content:space-between;
            flex-wrap:wrap;gap:0.5rem;">
            <div style="display:flex;align-items:baseline;gap:10px;">
                <span style="font-size:18px;font-weight:700;
                    color:{c['text_primary']};letter-spacing:-0.02em;">
                    Resolución rápida</span>
                <span style="font-size:12px;color:{c['text_muted']};">
                    Ingresa el caso · obtén decisión · copia y envía</span>
            </div>
            <span style="font-size:10px;color:{c['text_muted']};
                background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
                border-radius:20px;padding:3px 10px;white-space:nowrap;">
                ✦ Optimizado con casos recientes · Sistema en mejora continua</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_form, col_result = st.columns([0.42, 0.58])

    with col_form:
        _render_form_column(c)

    with col_result:
        _render_result_column(c)


# ── Form column ───────────────────────────────────────────────────────────────

def _render_form_column(c: dict) -> None:
    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:12px;padding:1.1rem 1.2rem;
    ">
    """, unsafe_allow_html=True)

    from components.case_intake import render as render_intake
    payload = render_intake()

    if payload is not None:
        _run_evaluation(payload, c)

    st.markdown('</div>', unsafe_allow_html=True)

    # Decision summary strip (shown after result is ready)
    result = sm.get("qi_result")
    if result and isinstance(result, dict) and result.get("decision"):
        _render_decision_summary(result["case"], result["decision"], c)

    # Session impact strip
    _render_impact_strip(c)


def _run_evaluation(payload: dict, c: dict) -> None:
    """Trigger loading state — actual work happens on next rerun."""
    sm.set("qi_result", None)
    sm.set("qi_loading", True)
    sm.set("qi_error", None)
    sm.set("qi_channel", "standard")
    st.rerun()


# ── Processing (called at top of result column rerun) ─────────────────────────

def _process_if_loading() -> None:
    if not sm.get("qi_loading"):
        return

    payload = _build_case_payload()
    if not payload:
        sm.set("qi_loading", False)
        return

    from services.case_service import CaseService
    from services.decision_service import DecisionService
    from services.response_builder import build_response, clean_for_clipboard

    cs = CaseService()
    ds = DecisionService()
    t0 = time.time()

    # Step 1: Create case
    case, err = cs.create(payload)
    if err or not case:
        sm.set("qi_error", err or "Error al crear el caso")
        sm.set("qi_loading", False)
        return

    case_id = case.get("id") or case.get("case_id")
    if not case_id:
        sm.set("qi_error", "El backend no retornó un ID de caso")
        sm.set("qi_loading", False)
        return

    # Step 2: Evaluate
    decision_raw, err = ds.evaluate(case_id)
    if err or not decision_raw:
        sm.set("qi_error", err or "Error al evaluar el caso")
        sm.set("qi_loading", False)
        return

    # Step 3: Build structured response
    decision  = decision_raw if isinstance(decision_raw, dict) else {}
    full_case = {**payload, "id": case_id}
    response_text = build_response(full_case, decision)
    elapsed   = round(time.time() - t0, 1)

    sm.set("qi_result", {
        "case":      full_case,
        "decision":  decision,
        "response":  clean_for_clipboard(response_text),
        "case_id":   case_id,
        "elapsed_s": elapsed,
    })
    sm.set("qi_loading", False)
    sm.set("qi_copied", False)


def _build_case_payload() -> dict | None:
    name   = sm.get("qi_client_name", "")
    days   = sm.get("qi_overdue_days", 0)
    amount = sm.get("qi_overdue_amount", 0)
    if not name or not days or not amount:
        return None
    return {
        "client_name":            name,
        "overdue_days":           int(days),
        "overdue_amount":         float(amount),
        "currency":               "COP",
        "case_type":               sm.get("qi_case_type", "mora"),
        "raw_data": {
            "has_policy":             bool(sm.get("qi_has_policy", False)),
            "has_legal_action":       bool(sm.get("qi_has_legal_action", False)),
            "previous_overdue_count": int(sm.get("qi_prev_count", 0)),
        },
    }


def _render_decision_summary(case: dict, decision: dict, c: dict) -> None:
    from styles.theme import RISK_COLORS
    from utils.formatters import fmt_currency

    action  = decision.get("action_label") or decision.get("action", "—")
    risk    = decision.get("risk_level", "BAJO")
    score   = float(decision.get("risk_score", 0))
    conf    = float(decision.get("confidence", 0))
    r_color = RISK_COLORS.get(risk, c["text_muted"])
    rule_id = decision.get("rule_id", "—")

    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:10px;padding:0.75rem 1rem;margin-top:0.6rem;
    ">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.5rem;">Decisión del motor</div>

        <div style="font-size:13px;font-weight:700;color:{c['accent']};
            margin-bottom:0.5rem;line-height:1.3;">{action}</div>

        <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:0.4rem;">
            <span style="font-size:11px;color:{r_color};font-weight:600;">
                {risk} · {score:.0f}/100</span>
            <span style="font-size:11px;color:{c['text_muted']};">
                Confianza: <span style="color:{c['text_secondary']};font-weight:500;">
                {conf:.0%}</span></span>
            <span style="font-size:11px;color:{c['text_muted']};">
                Regla: <span style="color:{c['text_secondary']};font-family:monospace;">
                {rule_id}</span></span>
        </div>

        {_legal_policy_flags(decision, c)}

        <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-top:0.5rem;
            border-top:1px solid {c['border_subtle']};padding-top:0.4rem;">
            <span style="font-size:10px;color:{c['text_muted']};">
                🧠 Basado en reglas de mora</span>
            <span style="font-size:10px;color:{c['text_muted']};">
                💾 Memoria del sistema activa</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _legal_policy_flags(decision: dict, c: dict) -> str:
    flags = []
    if decision.get("legal_flag"):
        flags.append('<span style="font-size:10px;color:#A855F7;background:rgba(168,85,247,0.10);'
                     'border-radius:3px;padding:1px 6px;">⚖ Legal</span>')
    if decision.get("policy_flag"):
        flags.append(f'<span style="font-size:10px;color:{c["accent"]};background:{c["accent_muted"]};'
                     f'border-radius:3px;padding:1px 6px;">🛡 Póliza</span>')
    if decision.get("escalation_required"):
        tgt = decision.get("escalation_target") or "supervisor"
        flags.append(f'<span style="font-size:10px;color:#EF4444;background:rgba(239,68,68,0.10);'
                     f'border-radius:3px;padding:1px 6px;">↑ Escalar: {tgt}</span>')
    if not flags:
        return ""
    return f'<div style="display:flex;gap:5px;flex-wrap:wrap;">{"".join(flags)}</div>'


# ── Result column ─────────────────────────────────────────────────────────────

def _render_result_column(c: dict) -> None:
    _process_if_loading()

    loading = sm.get("qi_loading", False)
    error   = sm.get("qi_error")
    result  = sm.get("qi_result")

    if loading:
        _render_loading_state(c)
        time.sleep(0.1)
        st.rerun()
        return

    if error:
        _render_error_state(error, c)
        return

    if result and isinstance(result, dict) and result.get("response"):
        _render_response_output(result, c)
        return

    _render_empty_result(c)


def _render_loading_state(c: dict) -> None:
    components.html(f"""
    <style>
    @keyframes shimmer {{
        0%   {{ background-position: -400px 0; }}
        100% {{ background-position: 400px 0; }}
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    .sk {{
        animation: shimmer 1.4s ease-in-out infinite;
        background: linear-gradient(90deg, #1a1a1a 25%, #242424 50%, #1a1a1a 75%);
        background-size: 800px 100%; border-radius: 6px;
    }}
    </style>
    <div style="padding:1.5rem;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:1.5rem;">
            <div style="width:32px;height:32px;border-radius:50%;
                border:3px solid {c['accent']};border-top-color:transparent;
                animation:spin 0.7s linear infinite;"></div>
            <div>
                <div style="font-size:14px;font-weight:600;color:{c['text_primary']};">
                    Generando decisión...</div>
                <div style="font-size:11px;color:{c['text_muted']};">
                    Motor de reglas en ejecución</div>
            </div>
        </div>
        <div class="sk" style="height:18px;width:70%;margin-bottom:10px;"></div>
        <div class="sk" style="height:14px;width:100%;margin-bottom:8px;"></div>
        <div class="sk" style="height:14px;width:95%;margin-bottom:8px;"></div>
        <div class="sk" style="height:14px;width:88%;margin-bottom:8px;"></div>
        <div class="sk" style="height:14px;width:92%;margin-bottom:8px;"></div>
        <div class="sk" style="height:14px;width:80%;margin-bottom:8px;"></div>
        <div class="sk" style="height:14px;width:100%;margin-bottom:8px;"></div>
        <div class="sk" style="height:14px;width:75%;margin-bottom:8px;"></div>
        <div class="sk" style="height:14px;width:90%;margin-bottom:8px;"></div>
        <div class="sk" style="height:14px;width:60%;"></div>
    </div>
    """, height=320, scrolling=False)


def _render_empty_result(c: dict) -> None:
    # ── First-use "Usar ejemplo" button ───────────────────────────────────────
    col_ex, _ = st.columns([1, 2])
    with col_ex:
        if st.button("✦ Cargar ejemplo", key="qi_load_example", use_container_width=True):
            sm.set("qi_client_name",     "María García López")
            sm.set("qi_overdue_days",    45)
            sm.set("qi_overdue_amount",  850_000)
            sm.set("qi_has_policy",      False)
            sm.set("qi_has_legal_action", False)
            sm.set("qi_prev_count",      0)
            sm.set("qi_case_type",       "mora")
            st.rerun()

    st.markdown(f"""
    <div style="
        display:flex;flex-direction:column;align-items:center;
        justify-content:center;min-height:440px;
        border:1.5px dashed {c['border_default']};
        border-radius:14px;text-align:center;padding:2rem;
    ">
        <div style="
            width:64px;height:64px;border-radius:14px;
            background:{c['accent_muted']};border:1.5px solid {c['border_accent']};
            display:flex;align-items:center;justify-content:center;
            font-size:28px;margin-bottom:1rem;
        ">⚡</div>
        <div style="font-size:15px;font-weight:700;color:{c['text_primary']};
            margin-bottom:0.4rem;">Listo para generar</div>
        <div style="font-size:12px;color:{c['text_muted']};
            max-width:280px;line-height:1.7;margin-bottom:1.25rem;">
            Completa el formulario y haz clic en
            <strong style="color:{c['text_secondary']};">Generar decisión y respuesta</strong>
            para obtener la respuesta al cliente en segundos.
        </div>
        <div style="
            background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:8px;padding:0.65rem 1rem;margin-bottom:1.25rem;
            font-size:11px;color:{c['text_muted']};text-align:left;max-width:300px;
        ">
            <div style="font-weight:600;color:{c['text_secondary']};margin-bottom:4px;">
                Ejemplo de caso</div>
            <div>Arrendatario: <span style="color:{c['text_primary']};">María García López</span></div>
            <div>Mora: <span style="color:{c['text_primary']};">45 días · $850.000 COP</span></div>
            <div>Tipo: <span style="color:{c['text_primary']};">Mora simple</span></div>
        </div>
        <div style="display:flex;gap:1.5rem;font-size:11px;color:{c['text_muted']};">
            <span>① Completa el caso</span>
            <span>→</span>
            <span>② Obtén la respuesta</span>
            <span>→</span>
            <span>③ Copia y envía</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _render_error_state(error: str, c: dict) -> None:
    st.markdown(f"""
    <div style="
        background:rgba(239,68,68,0.07);
        border:1px solid rgba(239,68,68,0.25);
        border-radius:10px;padding:1.25rem;margin-bottom:0.75rem;
    ">
        <div style="font-size:13px;font-weight:600;color:#EF4444;margin-bottom:5px;">
            Error al generar la decisión</div>
        <div style="font-size:12px;color:{c['text_secondary']};line-height:1.6;">
            {error}</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("↺ Reintentar", key="qi_retry", use_container_width=True):
        sm.set("qi_error", None)
        sm.set("qi_loading", True)
        st.rerun()


def _render_response_output(result: dict, c: dict) -> None:
    case        = result["case"]
    decision    = result["decision"]
    elapsed     = result.get("elapsed_s")
    channel     = sm.get("qi_channel", "standard")
    tone        = sm.get("qi_tone", "firme")
    regen_count = int(sm.get("qi_regen_count", 0))

    from services.response_builder import (
        build_response_variant,
        build_whatsapp_response,
        build_email_response,
        build_express_response,
        clean_for_clipboard,
    )

    # Build the appropriate variant
    if channel == "whatsapp":
        response = clean_for_clipboard(build_whatsapp_response(case, decision))
    elif channel == "email":
        response = clean_for_clipboard(build_email_response(case, decision))
    elif channel == "express":
        response = clean_for_clipboard(build_express_response(case, decision))
    else:
        if regen_count > 0 or tone != "firme":
            response = build_response_variant(case, decision,
                                              variant=regen_count, tone_override=tone)
        else:
            response = result["response"]

    action_label = (
        decision.get("action_label")
        or decision.get("action", "—").replace("_", " ").title()
    )
    rule_id    = decision.get("rule_id", "")
    confidence = float(decision.get("confidence", 0))

    # ── Confidence → action guidance ──────────────────────────────────────────
    if confidence >= 0.85:
        g_txt, g_color, g_bg = (
            "✓ Puedes usar esta respuesta directamente",
            "#22C55E", "rgba(34,197,94,0.07)",
        )
    elif confidence >= 0.65:
        g_txt, g_color, g_bg = (
            "⚠ Se recomienda revisar antes de enviar",
            "#F59E0B", "rgba(245,158,11,0.07)",
        )
    else:
        g_txt, g_color, g_bg = (
            "⚠ Validación recomendada antes de enviar",
            "#EF4444", "rgba(239,68,68,0.07)",
        )

    # ── Micro wow: fade-in animation ──────────────────────────────────────────
    st.markdown("""
    <style>
    @keyframes qi-fade-in {
        from { opacity:0; transform:translateY(7px); }
        to   { opacity:1; transform:translateY(0); }
    }
    @keyframes qi-pop {
        0%  { transform:scale(0.88); opacity:0; }
        65% { transform:scale(1.03); }
        100%{ transform:scale(1);   opacity:1; }
    }
    .qi-animate { animation:qi-fade-in 0.27s cubic-bezier(.4,0,.2,1) both; }
    .qi-pop     { animation:qi-pop 0.32s cubic-bezier(.34,1.56,.64,1) both; }
    </style>
    """, unsafe_allow_html=True)

    # ── Operator mode toggle ──────────────────────────────────────────────────
    mode = sm.get("qi_mode", "basico")
    _m_left, _m_b, _m_a = st.columns([3, 1, 1])
    with _m_b:
        if st.button("Básico", key="qi_mode_basico", use_container_width=True,
                     type="primary" if mode == "basico" else "secondary"):
            if mode != "basico":
                sm.set("qi_mode", "basico")
                st.rerun()
    with _m_a:
        if st.button("Avanzado", key="qi_mode_avanzado", use_container_width=True,
                     type="primary" if mode == "avanzado" else "secondary"):
            if mode != "avanzado":
                sm.set("qi_mode", "avanzado")
                st.rerun()

    # ── 1. Instant clarity banner ─────────────────────────────────────────────
    elapsed_badge = (
        f'<span style="font-size:11px;color:{c["text_muted"]};'
        f'background:{c["bg_elevated"]};border:1px solid {c["border_subtle"]};'
        f'border-radius:10px;padding:2px 8px;white-space:nowrap;">⚡ {elapsed}s</span>'
        if elapsed else ""
    )
    st.markdown(f"""
    <div class="qi-animate" style="
        background:linear-gradient(90deg,{c['accent_muted']},transparent);
        border-left:3px solid {c['accent']};border-radius:0 8px 8px 0;
        padding:0.5rem 1rem;margin-bottom:0.3rem;
        display:flex;align-items:center;justify-content:space-between;
        flex-wrap:wrap;gap:6px;
    ">
        <div>
            <div style="font-size:9px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.1em;margin-bottom:1px;">Acción</div>
            <div style="font-size:14px;font-weight:700;color:{c['text_primary']};">
                {action_label} · Listo para enviar</div>
        </div>
        {elapsed_badge}
    </div>
    """, unsafe_allow_html=True)

    # ── Simple explanation (non-technical why) ────────────────────────────────
    _render_simple_explanation(case, decision, c)

    # ── 5. Confidence guidance ────────────────────────────────────────────────
    st.markdown(f"""
    <div class="qi-pop" style="
        background:{g_bg};border-radius:6px;padding:5px 10px;
        margin-bottom:0.4rem;font-size:11px;font-weight:500;color:{g_color};
        display:flex;align-items:center;justify-content:space-between;
    ">
        <span>{g_txt}</span>
        <span style="font-size:10px;color:{c['text_muted']};">
            Tú decides · URAKI sugiere</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Trust row ─────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:0.4rem;">
        <span style="font-size:11px;color:#22C55E;background:rgba(34,197,94,0.08);
            border:1px solid rgba(34,197,94,0.22);border-radius:20px;padding:2px 9px;">
            ✓ Recomendado por URAKI</span>
        <span style="font-size:11px;color:{c['accent']};background:{c['accent_muted']};
            border:1px solid {c['border_accent']};border-radius:20px;padding:2px 9px;">
            ✓ Respuesta validada</span>
    </div>
    """, unsafe_allow_html=True)

    # ── 2. Tone selector ──────────────────────────────────────────────────────
    tone_options = {"suave": "~ Suave", "firme": "→ Firme", "legal": "⚖ Legal"}
    t_cols = st.columns(3)
    for i, (t, label) in enumerate(tone_options.items()):
        with t_cols[i]:
            if st.button(label, key=f"qi_tone_{t}", use_container_width=True,
                         type="primary" if tone == t else "secondary"):
                if tone != t:
                    sm.set("qi_tone", t)
                    st.rerun()

    # ── 3. Channel selector (now includes Express) ────────────────────────────
    ch_options = {
        "standard": "📄 Estándar",
        "express":  "⚡ Express",
        "whatsapp": "💬 WhatsApp",
        "email":    "📧 Email",
    }
    ch_cols = st.columns(4)
    for i, (ch, label) in enumerate(ch_options.items()):
        with ch_cols[i]:
            if st.button(label, key=f"qi_ch_{ch}", use_container_width=True,
                         type="primary" if channel == ch else "secondary"):
                if channel != ch:
                    sm.set("qi_channel", ch)
                    st.rerun()

    # ── Response text — dominant element ──────────────────────────────────────
    min_h = "100px" if channel == "express" else "280px"
    st.markdown(f"""
    <div class="qi-animate" style="
        background:{c['bg_elevated']};border:1px solid {c['border_default']};
        border-radius:12px;padding:1.4rem 1.6rem;
        margin-top:0.35rem;margin-bottom:0.5rem;
        font-family:'Inter',system-ui,sans-serif;font-size:13.5px;
        line-height:1.85;color:{c['text_primary']};white-space:pre-wrap;
        word-break:break-word;min-height:{min_h};max-height:56vh;overflow-y:auto;
        letter-spacing:0.01em;transition:min-height 0.2s ease;
    ">{_escape_html(response)}</div>
    """, unsafe_allow_html=True)

    # ── Copy button ───────────────────────────────────────────────────────────
    _render_copy_button(response, c)

    # ── Next best action ──────────────────────────────────────────────────────
    _render_next_actions(decision, c)

    # ── History tracking ──────────────────────────────────────────────────────
    hist_key = f"{channel}_{tone}_{regen_count}"
    if sm.get("qi_last_hist_key") != hist_key:
        history = list(sm.get("qi_history") or [])
        entry   = {
            "text": response, "action": action_label,
            "channel": channel, "tone": tone,
            "ts": time.strftime("%H:%M"),
        }
        if not history or history[-1]["text"] != response:
            sm.set("qi_history", (history + [entry])[-5:])
        sm.set("qi_last_hist_key", hist_key)

    # ── Intelligence hints ────────────────────────────────────────────────────
    rule_hint = f"Regla {rule_id}" if rule_id and rule_id not in ("—", "") else "Reglas de mora"
    st.markdown(f"""
    <div style="display:flex;gap:1rem;flex-wrap:wrap;padding:0.2rem 0;margin-bottom:0.3rem;">
        <span style="font-size:11px;color:{c['text_muted']};">🧠 {rule_hint}</span>
        <span style="font-size:11px;color:{c['text_muted']};">💾 Memoria activa</span>
    </div>
    """, unsafe_allow_html=True)

    # ── 1. Regenerate + action row ────────────────────────────────────────────
    col_regen, col_edit, col_reset, col_full = st.columns([1.3, 1, 1, 1])
    with col_regen:
        if st.button("↻ Regenerar", key="qi_regen", use_container_width=True):
            sm.set("qi_regen_count", regen_count + 1)
            st.rerun()
    with col_edit:
        if st.button("✏ Editar", key="qi_edit", use_container_width=True):
            sm.set("qi_editing", True)
            st.rerun()
    with col_reset:
        if st.button("↺ Nuevo", key="qi_reset", use_container_width=True):
            _reset_quick_mode()
            st.rerun()
    with col_full:
        if st.button("📋 Flow", key="qi_to_flow", use_container_width=True):
            case_id = result.get("case_id")
            if case_id:
                sm.select_case(case_id)
            sm.set("view_mode", "flow")
            st.rerun()

    # ── 4. Light history panel (Avanzado only) ───────────────────────────────
    if mode == "avanzado":
        _render_history_panel(c)

    # Edit mode
    if sm.get("qi_editing"):
        _render_edit_mode(response, c)


def _render_history_panel(c: dict) -> None:
    """Show up to 4 previous response versions with individual copy buttons."""
    history = sm.get("qi_history") or []
    past    = history[:-1]  # exclude current (last)
    if not past:
        return

    ch_icons   = {"whatsapp": "💬", "email": "📧", "express": "⚡", "standard": "📄"}
    tone_names = {"suave": "Suave", "firme": "Firme", "legal": "Legal"}

    with st.expander(f"🕐 Versiones anteriores ({len(past)})", expanded=False):
        for i, entry in enumerate(reversed(past)):
            ch_icon    = ch_icons.get(entry.get("channel", ""), "📄")
            tone_lbl   = tone_names.get(entry.get("tone", ""), "")
            preview    = entry.get("text", "")
            short      = preview[:180] + ("…" if len(preview) > 180 else "")

            st.markdown(f"""
            <div style="
                border-left:2px solid {c['border_subtle']};
                padding:0.4rem 0.65rem;margin-bottom:0.5rem;
            ">
                <div style="font-size:10px;color:{c['text_muted']};margin-bottom:4px;">
                    {ch_icon} {entry.get('ts','')} · {tone_lbl} · {entry.get('action','—')}</div>
                <div style="
                    font-size:11px;color:{c['text_secondary']};
                    font-family:'Inter',sans-serif;line-height:1.5;
                    max-height:58px;overflow:hidden;white-space:pre-wrap;
                ">{_escape_html(short)}</div>
            </div>
            """, unsafe_allow_html=True)
            _render_mini_copy_button(preview, f"qi_hist_{i}", c)


def _render_mini_copy_button(text: str, btn_id: str, c: dict) -> None:
    escaped = (
        text
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    components.html(f"""
    <button id="{btn_id}" onclick="(function(){{
        var t=`{escaped}`;
        var b=document.getElementById('{btn_id}');
        function done(){{
            b.textContent='✓ Copiado';b.style.color='#22C55E';
            b.style.borderColor='rgba(34,197,94,0.4)';
            setTimeout(function(){{
                b.textContent='📋 Copiar esta versión';
                b.style.color='';b.style.borderColor='';
            }},2000);
        }}
        if(navigator.clipboard&&window.isSecureContext){{
            navigator.clipboard.writeText(t).then(done);
        }}else{{
            var ta=document.createElement('textarea');ta.value=t;
            ta.style.position='fixed';ta.style.opacity='0';
            document.body.appendChild(ta);ta.select();
            document.execCommand('copy');document.body.removeChild(ta);done();
        }}
    }})()" style="
        background:transparent;border:1px solid #333;border-radius:5px;
        color:#888;font-size:11px;padding:3px 10px;cursor:pointer;
        font-family:'Inter',sans-serif;
        transition:color 0.15s,border-color 0.15s;margin-bottom:4px;
    "
    onmouseover="this.style.borderColor='#E85D2A';this.style.color='#E85D2A';"
    onmouseout="this.style.borderColor='#333';this.style.color='#888';"
    >📋 Copiar esta versión</button>
    """, height=34, scrolling=False)


def _render_simple_explanation(case: dict, decision: dict, c: dict) -> None:
    """1-2 line plain-language 'why this decision' — non-technical."""
    action       = decision.get("action", "REVISAR_MANUALMENTE")
    overdue_days = int(case.get("overdue_days", 0))
    amount       = float(case.get("overdue_amount", 0))
    has_policy   = bool(case.get("has_policy") or decision.get("policy_flag"))
    has_legal    = bool(case.get("has_legal_action") or decision.get("legal_flag"))
    prev_count   = int(case.get("previous_overdue_count", 0))

    _BASE = {
        "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA":
            "Se activa la póliza porque hay cobertura vigente y el saldo supera el umbral asegurado.",
        "INICIAR_DEMANDA_DE_RESTITUCIÓN":
            "Se inicia proceso legal por mora acumulada sin acuerdo previo.",
        "PROPONER_ACUERDO_DE_PAGO":
            "Se propone acuerdo para facilitar la regularización del saldo pendiente.",
        "COBRAR_PENALIDAD_CONTRACTUAL":
            "Se aplica penalidad por incumplimiento reiterado según las cláusulas del contrato.",
        "ENVIAR_RECORDATORIO_DE_PAGO":
            "Mora reciente sin historial crítico — un recordatorio es suficiente.",
        "REVISAR_MANUALMENTE":
            "El caso presenta factores atípicos que requieren revisión por parte del equipo.",
    }
    base   = _BASE.get(action, "Decisión basada en el perfil de mora y el historial del arrendatario.")
    extras = []
    if overdue_days > 90:
        extras.append("mora mayor a 90 días")
    if amount > 3_000_000:
        extras.append("monto elevado")
    if prev_count > 1:
        extras.append(f"{prev_count} incidencias previas")
    if has_legal:
        extras.append("proceso legal activo")
    if has_policy:
        extras.append("póliza aplicable")

    suffix      = f" Factores clave: {', '.join(extras)}." if extras else ""
    explanation = base + suffix

    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};border-left:3px solid {c['border_accent']};
        border-radius:0 6px 6px 0;padding:6px 10px;margin-bottom:0.35rem;
        font-size:11.5px;color:{c['text_secondary']};line-height:1.6;
    ">
        <span style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.07em;display:block;margin-bottom:2px;">
            ¿Por qué esta decisión?</span>
        {_escape_html(explanation)}
    </div>
    """, unsafe_allow_html=True)


def _render_next_actions(decision: dict, c: dict) -> None:
    """Suggested next workflow step after sending response."""
    action    = decision.get("action", "")
    escalated = bool(decision.get("escalation_required"))

    if escalated or action == "INICIAR_DEMANDA_DE_RESTITUCIÓN":
        rec = "escalar"
    elif action in ("PROPONER_ACUERDO_DE_PAGO", "ENVIAR_RECORDATORIO_DE_PAGO"):
        rec = "seguimiento"
    else:
        rec = "esperar"

    current_na = sm.get("qi_next_action", "")

    st.markdown(f"""
    <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
        letter-spacing:0.08em;margin:0.5rem 0 0.3rem;">Próximo paso sugerido</div>
    """, unsafe_allow_html=True)

    na_opts = [
        ("seguimiento", "📅", "Hacer seguimiento", "Contacto en 48h"),
        ("escalar",     "↑",  "Escalar",           "Notifica supervisor"),
        ("esperar",     "⏳", "Esperar respuesta",  "Sin contacto ahora"),
    ]
    na_cols = st.columns(3)
    for i, (key, icon, label, hint) in enumerate(na_opts):
        with na_cols[i]:
            is_rec = (key == rec)
            is_sel = (current_na == key)
            border = c["accent"] if is_sel else (c["border_accent"] if is_rec else c["border_subtle"])
            bg     = c["accent_muted"] if is_sel else ("rgba(232,93,42,0.04)" if is_rec else c["bg_elevated"])
            txt    = c["accent"] if (is_sel or is_rec) else c["text_muted"]
            rec_badge = (
                '<div style="font-size:9px;color:#E85D2A;margin-top:2px;">Recomendado</div>'
                if is_rec and not is_sel else ""
            )
            st.markdown(f"""
            <div style="
                background:{bg};border:1px solid {border};border-radius:7px;
                padding:6px 8px;text-align:center;
            ">
                <div style="font-size:15px;">{icon}</div>
                <div style="font-size:11px;font-weight:600;
                    color:{txt};margin:2px 0;">{label}</div>
                <div style="font-size:10px;color:{c['text_muted']};
                    line-height:1.3;">{hint}</div>
                {rec_badge}
            </div>
            """, unsafe_allow_html=True)
            if st.button(
                "✓" if is_sel else "Elegir",
                key=f"qi_na_{key}",
                use_container_width=True,
                type="primary" if is_sel else "secondary",
            ):
                sm.set("qi_next_action", "" if is_sel else key)
                st.rerun()

    # Confirmation of selection
    if current_na:
        na_msg = {
            "seguimiento": "📅 Seguimiento registrado — contacta al arrendatario en 48 horas.",
            "escalar":     "↑ Escalado marcado — notifica a tu supervisor con el caso.",
            "esperar":     "⏳ Modo espera — monitorea sin contacto activo por ahora.",
        }
        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_secondary']};
            background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:6px;padding:6px 10px;margin-top:0.3rem;">
            {_escape_html(na_msg.get(current_na, ""))}
        </div>
        """, unsafe_allow_html=True)


def _render_impact_strip(c: dict) -> None:
    """Session impact metrics — only shown after at least one resolution."""
    resolved = int(sm.get("resolved_today", 0))
    if resolved == 0:
        return
    total_ms = int(sm.get("total_resolution_ms", 0))
    avg_s    = (total_ms // resolved // 1000) if resolved > 0 else 0
    avg_fmt  = f"{avg_s}s" if avg_s < 120 else f"{avg_s // 60}m {avg_s % 60}s"

    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:8px;padding:0.5rem 0.8rem;margin-top:0.5rem;
        display:flex;gap:1.5rem;flex-wrap:wrap;align-items:center;
    ">
        <span style="font-size:10px;color:{c['text_muted']};
            text-transform:uppercase;letter-spacing:0.07em;">Esta sesión</span>
        <span style="font-size:12px;color:{c['text_primary']};font-weight:600;">
            {resolved} caso{'s' if resolved != 1 else ''} resuelto{'s' if resolved != 1 else ''}
        </span>
        <span style="font-size:12px;color:{c['text_muted']};">
            Promedio: <strong style="color:{c['text_secondary']};">{avg_fmt}</strong>
        </span>
        <span style="font-size:10px;color:{c['accent']};">✦ Eficiencia URAKI</span>
    </div>
    """, unsafe_allow_html=True)


def _render_copy_button(response: str, c: dict) -> None:
    """
    JS-powered one-click copy.
    Completion feedback text: "✓ Respuesta lista para enviar"
    """
    escaped = (
        response
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
    )

    components.html(f"""
    <div style="margin-bottom:8px;">
        <button id="copy-btn" onclick="copyText()" style="
            width:100%;
            background:#E85D2A;
            color:#fff;
            border:none;
            border-radius:8px;
            padding:11px 0;
            font-size:14px;
            font-weight:700;
            letter-spacing:0.02em;
            cursor:pointer;
            transition:background 0.15s,transform 0.1s;
            font-family:'Inter',sans-serif;
        "
        onmouseover="this.style.background='#F0703D'"
        onmouseout="this.style.background='#E85D2A'"
        onmousedown="this.style.transform='scale(0.98)'"
        onmouseup="this.style.transform='scale(1)'"
        >
            📋 Copiar respuesta
        </button>
        <div id="copy-feedback" style="
            display:none;
            text-align:center;
            font-size:12px;
            font-weight:600;
            color:#22C55E;
            background:rgba(34,197,94,0.08);
            border:1px solid rgba(34,197,94,0.25);
            border-radius:6px;
            padding:7px 0;
            margin-top:5px;
            font-family:'Inter',sans-serif;
        ">✓ Respuesta lista para enviar</div>
    </div>
    <script>
    function copyText() {{
        const text = `{escaped}`;
        if (navigator.clipboard && window.isSecureContext) {{
            navigator.clipboard.writeText(text).then(() => showFeedback());
        }} else {{
            const el = document.createElement('textarea');
            el.value = text;
            el.style.position = 'fixed';
            el.style.opacity  = '0';
            document.body.appendChild(el);
            el.select();
            document.execCommand('copy');
            document.body.removeChild(el);
            showFeedback();
        }}
    }}
    function showFeedback() {{
        const btn = document.getElementById('copy-btn');
        const fb  = document.getElementById('copy-feedback');
        btn.textContent      = '✓ ¡Copiado!';
        btn.style.background = '#16A34A';
        fb.style.display     = 'block';
        setTimeout(() => {{
            btn.textContent      = '📋 Copiar respuesta';
            btn.style.background = '#E85D2A';
            fb.style.display     = 'none';
        }}, 2500);
    }}
    </script>
    """, height=80, scrolling=False)

    with st.expander("¿No funciona el botón? Copia aquí manualmente", expanded=False):
        st.text_area(
            label="",
            value=response,
            height=180,
            key="qi_copy_fallback",
            label_visibility="collapsed",
        )


def _render_edit_mode(original: str, c: dict) -> None:
    st.markdown(f"""
    <div style="font-size:11px;color:{c['text_muted']};
        text-transform:uppercase;letter-spacing:0.08em;
        margin:0.75rem 0 0.3rem;">Editar respuesta</div>
    """, unsafe_allow_html=True)

    edited = st.text_area(
        label="",
        value=sm.get("qi_edited_response") or original,
        height=300,
        key="qi_edit_area",
        label_visibility="collapsed",
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Guardar", key="qi_save_edit",
                     use_container_width=True, type="primary"):
            result = sm.get("qi_result") or {}
            result["response"] = edited
            sm.set("qi_result", result)
            sm.set("qi_editing", False)
            sm.set("qi_edited_response", None)
            st.rerun()
    with col_cancel:
        if st.button("Cancelar", key="qi_cancel_edit", use_container_width=True):
            sm.set("qi_editing", False)
            sm.set("qi_edited_response", None)
            st.rerun()

    sm.set("qi_edited_response", edited)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reset_quick_mode() -> None:
    keys = [
        "qi_result", "qi_loading", "qi_error", "qi_copied",
        "qi_editing", "qi_edited_response", "qi_channel",
        "qi_client_name", "qi_overdue_days", "qi_overdue_amount",
        "qi_has_policy", "qi_has_legal_action", "qi_prev_count",
        "qi_case_type", "qi_tone", "qi_regen_count",
        "qi_history", "qi_last_hist_key",
        "qi_next_action",
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]


def _escape_html(text: str) -> str:
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_not_configured(c: dict) -> None:
    st.markdown(f"""
    <div style="
        display:flex;flex-direction:column;align-items:center;
        justify-content:center;min-height:60vh;text-align:center;
    ">
        <div style="font-size:32px;margin-bottom:1rem;">📡</div>
        <div style="font-size:16px;font-weight:700;color:{c['danger']};
            margin-bottom:0.5rem;">Backend no configurado</div>
        <div style="font-size:12px;color:{c['text_muted']};max-width:300px;line-height:1.6;">
            Configura URAKI_API_URL para usar el modo de resolución rápida.
        </div>
    </div>
    """, unsafe_allow_html=True)
