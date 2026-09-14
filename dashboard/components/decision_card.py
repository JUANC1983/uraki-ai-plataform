# dashboard/components/decision_card.py
"""
Decision Card — center-piece of the Flow Mode.

Renders:
  Header      — badges (risk, priority, confidence, override)
  Action block — main recommended action with firmness
  Client block — arrendatario data and overdue metrics
  Reasoning    — rationale + next step + escalation target
  Intelligence — risk factors (structured) + data_used inputs
  Evidence     — linked documents + triggered clauses
  Audit trace  — rule_id, rule_version, timing, conflict resolution
  Message panel — suggested client message + operator copy
  Override     — role-gated override modal
  Simulation   — what-if panel
  Timeline     — full audit timeline
  Actions      — action engine

All data comes from the backend via DecisionService. No fabrication.
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components
import core.state_manager as sm
from core.auth import has_permission
from styles.theme import COLORS, PRIORITY_COLORS, RISK_COLORS
from utils.formatters import (
    fmt_currency, risk_badge_html, priority_badge_html,
    score_bar_html, _hex_to_rgb,
)
from services.decision_service import DecisionService
from core import consistency
from services.sla_service import SLAService, render_sla_badge_html


_FIRMNESS_LABELS = {
    "URGENTE":  ("⚡", "#A855F7"),
    "ESTRICTO": ("!", "#EF4444"),
    "FIRME":    ("→", "#E85D2A"),
    "SUAVE":    ("~", "#22C55E"),
}

_ACTION_ICONS = {
    "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA": "🛡",
    "INICIAR_DEMANDA_DE_RESTITUCIÓN":          "⚖",
    "PROPONER_ACUERDO_DE_PAGO":                "🤝",
    "COBRAR_PENALIDAD_CONTRACTUAL":            "📋",
    "ENVIAR_RECORDATORIO_DE_PAGO":             "💬",
    "REVISAR_MANUALMENTE":                     "👁",
}

_RISK_FACTOR_COLORS = {
    "Alto":  "#EF4444",
    "Medio": "#F59E0B",
    "Bajo":  "#22C55E",
}


def render(case: dict, decision: dict | None) -> None:
    c = COLORS
    st.markdown('<div class="uraki-fade-in">', unsafe_allow_html=True)

    # Consistency guardrail — surface violations before rendering card
    result = consistency.check(case, decision)
    if result.violations:
        _render_consistency_violations(result, c)

    if decision is None:
        _render_no_decision(case, c)
    else:
        # ── 1. Super decision header — first thing operator sees ──────────
        _render_super_header(case, decision, c)

        # ── 2. Client context — compact, one line ─────────────────────────
        _render_client_compact(case, c)

        # ── 3. Primary response — the product ─────────────────────────────
        _render_response_primary(case, decision, c)

        # ── 4. Everything else collapsed ──────────────────────────────────
        with st.expander("📊 Por qué esta decisión", expanded=False):
            _render_reasoning(decision, c)

        _render_intelligence_layer(decision, c)

        with st.expander("🧠 Inteligencia y sugerencias", expanded=False):
            _render_context_intelligence(case, decision, c)

        with st.expander("📄 Evidencia contractual", expanded=False):
            _render_evidence(case, decision, c)

        # Audit trace — has internal expander, rendered directly
        _render_audit_trace(case, decision, c)

        # Role-gated operator tools
        from components.override_modal import render as render_override
        render_override(case, decision)
        from components.simulation_panel import render as render_simulation
        render_simulation(case, decision)
        st.caption(
            "El envío de notificaciones y la asignación de tareas no están "
            "implementados en este prototipo."
        )
        from components.audit_timeline import render as render_timeline
        render_timeline(case)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Super decision header ─────────────────────────────────────────────────────

def _render_super_header(case: dict, decision: dict, c: dict) -> None:
    """
    Dominant block. First thing the operator sees.
    Large action, risk, confidence, and generated-state indicator.
    No competing elements — pure signal.
    """
    action        = decision.get("action", "REVISAR_MANUALMENTE")
    label         = decision.get("action_label") or action.replace("_", " ").title()
    icon          = _ACTION_ICONS.get(action, "→")
    risk          = decision.get("risk_level", "BAJO")
    confidence    = float(decision.get("confidence", 0))
    score         = int(decision.get("risk_score", 0))
    firm          = decision.get("firmness", "FIRME")
    is_overridden = decision.get("is_overridden", False)

    r_color    = RISK_COLORS.get(risk, c["text_muted"])
    conf_color = "#22C55E" if confidence >= 0.85 else "#F59E0B" if confidence >= 0.65 else "#EF4444"
    f_icon, f_color = _FIRMNESS_LABELS.get(firm, ("→", c["accent"]))

    override_badge = (
        f'<span style="font-size:10px;color:#F59E0B;background:rgba(245,158,11,0.1);'
        f'border-radius:4px;padding:2px 7px;">⚠ Override</span>'
        if is_overridden else ""
    )
    legal_badge  = (
        '<span style="font-size:11px;color:#A855F7;background:rgba(168,85,247,0.10);'
        'border-radius:4px;padding:2px 8px;">⚖ Legal</span>'
        if decision.get("legal_flag") else ""
    )
    policy_badge = (
        f'<span style="font-size:11px;color:{c["accent"]};background:{c["accent_muted"]};'
        f'border-radius:4px;padding:2px 8px;">🛡 Póliza</span>'
        if decision.get("policy_flag") else ""
    )

    st.markdown(f"""
    <div style="
        background:linear-gradient(135deg,{c['accent_muted']} 0%,transparent 80%);
        border:1.5px solid {c['border_accent']};
        border-radius:14px;
        padding:1.25rem 1.5rem 1rem;
        margin-bottom:0.6rem;
    ">
        <div style="display:flex;align-items:center;justify-content:space-between;
            margin-bottom:0.9rem;flex-wrap:wrap;gap:6px;">
            <div style="display:flex;align-items:center;gap:7px;">
                <span style="font-size:10px;color:{c['text_muted']};
                    font-variant-numeric:tabular-nums;">{case.get('id','')}</span>
                {override_badge}
            </div>
            <span style="font-size:11px;color:#22C55E;font-weight:600;
                background:rgba(34,197,94,0.10);border-radius:10px;
                padding:3px 11px;">✓ Recomendación generada</span>
        </div>
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:1rem;">
            <span style="font-size:30px;line-height:1;">{icon}</span>
            <span style="font-size:22px;font-weight:800;color:{c['text_primary']};
                letter-spacing:-0.02em;line-height:1.2;">{label}</span>
        </div>
        <div style="display:flex;align-items:center;gap:0;flex-wrap:wrap;">
            <div style="padding:0 16px 0 0;">
                <div style="font-size:9px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.09em;margin-bottom:1px;">Riesgo</div>
                <div style="font-size:16px;font-weight:700;color:{r_color};">{risk}</div>
            </div>
            <div style="width:1px;height:32px;background:{c['border_subtle']};margin-right:16px;"></div>
            <div style="padding-right:16px;">
                <div style="font-size:9px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.09em;margin-bottom:1px;">Confianza</div>
                <div style="font-size:16px;font-weight:700;color:{conf_color};">
                    {confidence:.0%}</div>
            </div>
            <div style="width:1px;height:32px;background:{c['border_subtle']};margin-right:16px;"></div>
            <div style="padding-right:16px;">
                <div style="font-size:9px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.09em;margin-bottom:1px;">Score</div>
                <div style="font-size:16px;font-weight:700;color:{c['text_primary']};">
                    {score}/100</div>
            </div>
            <div style="width:1px;height:32px;background:{c['border_subtle']};margin-right:16px;"></div>
            <div style="padding-right:12px;">
                <div style="font-size:9px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.09em;margin-bottom:1px;">Firmeza</div>
                <div style="font-size:16px;font-weight:700;color:{f_color};">
                    {f_icon} {firm}</div>
            </div>
            <div style="margin-left:auto;display:flex;gap:5px;align-items:center;">
                {legal_badge}{policy_badge}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Client compact (one-line, no noise) ───────────────────────────────────────

def _render_client_compact(case: dict, c: dict) -> None:
    name   = case.get("client_name", "—")
    days   = case.get("overdue_days", 0)
    amount = fmt_currency(case.get("overdue_amount", 0), case.get("currency", "COP"))
    prev   = case.get("previous_overdue_count", 0)

    extras = []
    if case.get("has_policy"):       extras.append("🛡 Póliza")
    if case.get("has_legal_action"): extras.append("⚖ Legal")
    if prev > 0:                     extras.append(f"{prev} prev.")
    extras_str = " · ".join(extras)

    st.markdown(f"""
    <div style="
        padding:0.45rem 0.85rem;
        border-left:2px solid {c['border_subtle']};
        margin-bottom:0.6rem;
        display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
    ">
        <span style="font-size:14px;font-weight:600;color:{c['text_primary']};">{name}</span>
        <span style="font-size:12px;color:{c['text_muted']};">
            {days}d · {amount}{(' · ' + extras_str) if extras_str else ''}</span>
    </div>
    """, unsafe_allow_html=True)


# ── Primary copy button (full-width, dominant) ────────────────────────────────

def _primary_copy_button_html(text: str, btn_id: str) -> None:
    c = COLORS
    escaped = (
        text
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace('"', '\\"')
    )
    components.html(f"""
    <style>
    #{btn_id} {{
        width:100%;background:#E85D2A;color:#fff;border:none;
        border-radius:9px;padding:13px 0;font-size:15px;font-weight:700;
        letter-spacing:0.02em;cursor:pointer;
        transition:background 0.15s,transform 0.1s;
        font-family:'Inter',system-ui,sans-serif;
    }}
    #{btn_id}:hover {{ background:#F0703D;transform:translateY(-1px); }}
    #{btn_id}:active {{ transform:scale(0.99); }}
    #{btn_id}.copied {{ background:#16A34A; }}
    #fb-{btn_id} {{
        display:none;text-align:center;font-size:12px;font-weight:600;
        color:#22C55E;background:rgba(34,197,94,0.08);
        border:1px solid rgba(34,197,94,0.25);border-radius:6px;
        padding:7px 0;margin-top:6px;font-family:'Inter',sans-serif;
    }}
    </style>
    <button id="{btn_id}" onclick="(function(){{
        var t=`{escaped}`;
        var b=document.getElementById('{btn_id}');
        var f=document.getElementById('fb-{btn_id}');
        function done(){{
            b.textContent='✓ Copiado';b.classList.add('copied');
            f.style.display='block';
            setTimeout(function(){{
                b.textContent='📋 Copiar respuesta';
                b.classList.remove('copied');f.style.display='none';
            }},2500);
        }}
        if(navigator.clipboard&&window.isSecureContext){{
            navigator.clipboard.writeText(t).then(done);
        }}else{{
            var ta=document.createElement('textarea');ta.value=t;
            ta.style.position='fixed';ta.style.opacity='0';
            document.body.appendChild(ta);ta.select();
            document.execCommand('copy');document.body.removeChild(ta);done();
        }}
    }})()">📋 Copiar respuesta</button>
    <div id="fb-{btn_id}">✓ Respuesta lista para enviar</div>
    """, height=76, scrolling=False)


# ── Context intelligence (inline — replaces intelligence_panel) ───────────────

def _render_context_intelligence(case: dict, decision: dict, c: dict) -> None:
    """
    Inline version of intelligence_panel: context package, quality scores,
    and proactive suggestions — all inside the main decision card flow.
    Critical/high suggestions shown inline; medium/low collapsed.
    """
    try:
        from services.intelligence_service import (
            build_context_package,
            compute_quality_score,
            get_proactive_suggestions,
        )
        ctx     = build_context_package(case, decision)
        quality = compute_quality_score(decision)
        suggs   = get_proactive_suggestions(case, decision)
    except Exception:
        return

    exec_summary = ctx.get("executive_summary", "")
    risk_summary = ctx.get("risk_summary", "")
    next_step    = ctx.get("next_step", "")
    q_score      = quality.get("quality_score", 0)
    q_label      = quality.get("quality_label", "—")
    q_color      = quality.get("quality_color", c["text_muted"])
    conf_score   = quality.get("confidence_score", 0)
    conf_label   = quality.get("confidence_label", "—")
    conf_color   = "#22C55E" if conf_score >= 0.85 else "#F59E0B" if conf_score >= 0.65 else "#EF4444"

    # ── Context package strip ──────────────────────────────────────────────
    if exec_summary or risk_summary or next_step:
        cols = st.columns([2, 1.4, 1.4])
        with cols[0]:
            st.markdown(f"""
            <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
                border-radius:8px;padding:0.65rem 0.85rem;height:100%;">
                <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.08em;margin-bottom:4px;">Resumen ejecutivo</div>
                <div style="font-size:12px;color:{c['text_secondary']};line-height:1.5;">
                    {exec_summary or '—'}</div>
            </div>
            """, unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f"""
            <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
                border-radius:8px;padding:0.65rem 0.85rem;height:100%;">
                <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.08em;margin-bottom:4px;">Riesgo</div>
                <div style="font-size:12px;color:{c['text_secondary']};line-height:1.5;">
                    {risk_summary or '—'}</div>
            </div>
            """, unsafe_allow_html=True)
        with cols[2]:
            st.markdown(f"""
            <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
                border-radius:8px;padding:0.65rem 0.85rem;height:100%;">
                <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.08em;margin-bottom:4px;">Próximo paso</div>
                <div style="font-size:12px;color:{c['text_secondary']};line-height:1.5;">
                    {next_step or '—'}</div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)

    # ── Quality + confidence bars ──────────────────────────────────────────
    q_pct   = min(100, max(0, int(q_score)))
    conf_pct = min(100, max(0, int(conf_score * 100)))
    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:8px;padding:0.65rem 0.85rem;margin-bottom:0.5rem;">
        <div style="display:flex;justify-content:space-between;margin-bottom:0.4rem;">
            <span style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;">Calidad de decisión</span>
            <span style="font-size:11px;font-weight:600;color:{q_color};">
                {q_score:.0f}/100 · {q_label}</span>
        </div>
        <div style="height:4px;background:{c['bg_secondary']};border-radius:4px;margin-bottom:0.5rem;">
            <div style="width:{q_pct}%;height:100%;background:{q_color};border-radius:4px;
                transition:width 0.4s ease;"></div>
        </div>
        <div style="display:flex;justify-content:space-between;margin-bottom:0.3rem;">
            <span style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;">Confianza del motor</span>
            <span style="font-size:11px;font-weight:600;color:{conf_color};">
                {conf_score:.0%} · {conf_label}</span>
        </div>
        <div style="height:4px;background:{c['bg_secondary']};border-radius:4px;">
            <div style="width:{conf_pct}%;height:100%;background:{conf_color};border-radius:4px;
                transition:width 0.4s ease;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Proactive suggestions ──────────────────────────────────────────────
    if not suggs:
        return

    _TYPE_COLORS = {
        "risk_alert":          "#EF4444",
        "escalation_warning":  "#A855F7",
        "pattern_detected":    "#3B82F6",
        "sla_warning":         "#F59E0B",
        "suggestion":          "#22C55E",
    }
    _PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_suggs = sorted(suggs, key=lambda s: _PRIORITY_ORDER.get(s.get("priority","low"), 3))
    inline   = [s for s in sorted_suggs if s.get("priority") in ("critical", "high")]
    deferred = [s for s in sorted_suggs if s.get("priority") not in ("critical", "high")]

    for s in inline:
        sc = _TYPE_COLORS.get(s.get("type", "suggestion"), c["text_muted"])
        st.markdown(f"""
        <div style="background:rgba({_hex_to_rgb(sc)},0.07);border:1px solid rgba({_hex_to_rgb(sc)},0.28);
            border-radius:7px;padding:0.5rem 0.8rem;margin-bottom:4px;
            display:flex;align-items:flex-start;gap:8px;">
            <span style="font-size:14px;">{s.get('icon','•')}</span>
            <div>
                <div style="font-size:11px;font-weight:600;color:{sc};">{s.get('title','')}</div>
                <div style="font-size:11px;color:{c['text_secondary']};margin-top:1px;">
                    {s.get('message','')}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    if deferred:
        st.markdown(
            f"<div style=\"font-size:10px;color:{c['text_muted']};"
            "text-transform:uppercase;letter-spacing:0.08em;margin:0.65rem 0 0.25rem;\">"
            f"{len(deferred)} sugerencia(s) adicional(es)</div>",
            unsafe_allow_html=True,
        )
        for s in deferred:
            sc = _TYPE_COLORS.get(s.get("type", "suggestion"), c["text_muted"])
            st.markdown(f"""
            <div style="font-size:11px;color:{c['text_secondary']};
                padding:0.3rem 0;border-bottom:1px solid {c['border_subtle']};">
                <span style="color:{sc};font-weight:600;">{s.get('icon','')} {s.get('title','')}</span>
                — {s.get('message','')}
            </div>
            """, unsafe_allow_html=True)


# ── Primary response element ──────────────────────────────────────────────────

def _render_response_primary(case: dict, decision: dict, c: dict) -> None:
    """
    The product. Dominant visual element.
    Response text takes maximum vertical space.
    ONE copy button — large, primary, full width.
    Edit is secondary and non-intrusive.
    """
    import html as _html
    _clean_fn = None
    try:
        from services.response_builder import build_response, clean_for_clipboard as _clean_fn
        response_text = build_response(case, decision)
    except Exception:
        response_text = decision.get("suggested_message", "")

    if not response_text:
        return

    dec_id     = decision.get("id", "0") or "0"
    edit_key   = f"_resp_edit_{dec_id}"
    edit_mode  = f"_resp_edit_mode_{dec_id}"
    edited_txt = st.session_state.get(edit_key, "")
    display    = edited_txt if edited_txt else response_text
    clean_text = _clean_fn(display) if _clean_fn else display.strip()

    # ── Response text — maximum prominence ────────────────────────────────
    st.markdown(f"""
    <div style="
        background:{c['bg_elevated']};
        border:1px solid {c['border_default']};
        border-radius:12px;
        padding:1.35rem 1.5rem;
        margin-bottom:0.6rem;
        font-size:13.5px;
        color:{c['text_primary']};
        line-height:1.8;
        white-space:pre-wrap;
        word-break:break-word;
        font-family:'Inter',system-ui,sans-serif;
        min-height:240px;
        max-height:65vh;
        overflow-y:auto;
        letter-spacing:0.01em;
    ">{_html.escape(display)}</div>
    """, unsafe_allow_html=True)

    # ── ONE dominant copy button ───────────────────────────────────────────
    _primary_copy_button_html(clean_text, f"dc_copy_{dec_id}")

    # ── Edit — secondary, below copy ──────────────────────────────────────
    _, col_edit = st.columns([2, 1])
    with col_edit:
        if st.button("✏ Editar", key=f"resp_edit_btn_{dec_id}", use_container_width=True):
            st.session_state[edit_mode] = not st.session_state.get(edit_mode, False)
            st.rerun()

    if st.session_state.get(edit_mode):
        new_text = st.text_area(
            "",
            value=display,
            height=280,
            key=f"resp_textarea_{dec_id}",
            label_visibility="collapsed",
        )
        save_col, cancel_col, _ = st.columns([1, 1, 2])
        with save_col:
            if st.button("💾 Guardar", key=f"resp_save_{dec_id}",
                         use_container_width=True, type="primary"):
                st.session_state[edit_key] = new_text
                st.session_state[edit_mode] = False
                st.rerun()
        with cancel_col:
            if st.button("✕ Cancelar", key=f"resp_cancel_{dec_id}",
                         use_container_width=True):
                st.session_state[edit_mode] = False
                st.rerun()


# ── Similar cases strip (inline compact) ──────────────────────────────────────

def _render_similar_strip(case: dict, c: dict) -> None:
    """
    Compact 3-card strip of similar past cases from the memory system.
    Replaces the full similar_cases component panel.
    """
    try:
        from services.memory_service import MemoryService
        similar, err = MemoryService().get_similar(case, limit=3)
        if err or not similar:
            return
    except Exception:
        return

    _SIM_COLORS = {
        "resolved":   "#22C55E",
        "escalated":  "#A855F7",
        "overridden": "#F59E0B",
    }

    cards_html = ""
    for fp in similar[:3]:
        sim_pct  = fp.get("similarity_score", 0) * 100
        outcome  = fp.get("outcome", "—")
        action   = fp.get("action_taken", "—").replace("_", " ").title()
        days     = fp.get("outcome_days")
        o_color  = _SIM_COLORS.get(outcome, c["text_muted"])
        sim_color = "#22C55E" if sim_pct >= 85 else "#F59E0B" if sim_pct >= 70 else c["text_muted"]
        days_txt = f" · {days}d" if days is not None else ""

        cards_html += f"""
        <div style="flex:1;min-width:0;background:{c['bg_elevated']};
            border:1px solid {c['border_subtle']};border-radius:8px;padding:0.6rem 0.75rem;">
            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                <span style="font-size:10px;font-weight:700;color:{sim_color};">
                    {sim_pct:.0f}% similar</span>
                <span style="font-size:10px;color:{o_color};font-weight:600;">
                    {outcome}{days_txt}</span>
            </div>
            <div style="font-size:11px;color:{c['text_secondary']};
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                {action}</div>
        </div>
        """

    st.markdown(f"""
    <div style="margin-bottom:0.5rem;">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.4rem;">Casos similares</div>
        <div style="display:flex;gap:8px;">
            {cards_html}
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Inline 1-click feedback ───────────────────────────────────────────────────

def _render_inline_feedback(decision: dict, c: dict) -> None:
    """
    Single-row star rating + optional quick flag. Submits without a modal.
    Deduped by decision_id so it only shows once per decision per session.
    """
    decision_id = decision.get("id", "")
    if not decision_id:
        return
    done_key = f"_feedback_done_{decision_id}"
    if st.session_state.get(done_key):
        st.markdown(f"""
        <div style="font-size:11px;color:{c['text_muted']};padding:0.3rem 0;">
            ✓ Valoración enviada. Gracias.</div>
        """, unsafe_allow_html=True)
        return

    st.markdown(f"""
    <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
        letter-spacing:0.08em;margin-bottom:0.3rem;">Calificar esta decisión</div>
    """, unsafe_allow_html=True)

    star_col, flag_col, submit_col = st.columns([1.2, 2, 1])

    with star_col:
        rating = st.select_slider(
            "Valoración",
            options=[1, 2, 3, 4, 5],
            value=st.session_state.get(f"_fb_rating_{decision_id}", 4),
            format_func=lambda x: "★" * x + "☆" * (5 - x),
            key=f"_fb_slider_{decision_id}",
            label_visibility="collapsed",
        )
        st.session_state[f"_fb_rating_{decision_id}"] = rating

    with flag_col:
        flags = st.multiselect(
            "Flags",
            options=["wrong_action", "wrong_risk", "missing_context", "too_aggressive", "too_lenient"],
            default=[],
            key=f"_fb_flags_{decision_id}",
            label_visibility="collapsed",
            placeholder="Seleccionar flags (opcional)",
        )

    with submit_col:
        if st.button("Enviar", key=f"_fb_submit_{decision_id}", use_container_width=True):
            try:
                from services.intelligence_service import ResponseFeedbackService
                ResponseFeedbackService().submit_rating(
                    decision_id=decision_id,
                    case_id="",
                    rating=rating,
                    flags=flags,
                    comment="",
                )
            except Exception:
                pass
            st.session_state[done_key] = True
            st.rerun()


def _maybe_store_memory(case: dict, decision: dict) -> None:
    """
    Store a case fingerprint in the memory system once per case+decision pair.
    Keyed by decision_id to avoid duplicate writes on every Streamlit rerun.
    """
    decision_id = decision.get("id", "")
    if not decision_id:
        return
    stored_key = f"_memory_stored_{decision_id}"
    if st.session_state.get(stored_key):
        return
    try:
        from services.memory_service import MemoryService
        MemoryService().store_fingerprint(case, decision)
    except Exception:
        pass
    st.session_state[stored_key] = True


# ── Consistency violations ────────────────────────────────────────────────────

def _render_consistency_violations(result: "consistency.ConsistencyResult", c: dict) -> None:
    html = consistency.render_violations_html(result, c)
    if html:
        st.markdown(html, unsafe_allow_html=True)


# ── No decision ───────────────────────────────────────────────────────────────

def _render_no_decision(case: dict, c: dict) -> None:
    ds = DecisionService()

    st.markdown(f"""
    <div style="text-align:center;padding:2rem 1rem;animation:fadeIn 0.25s ease;">
        <div style="font-size:32px;margin-bottom:0.75rem;">🔍</div>
        <div style="font-size:16px;font-weight:600;color:{c['text_primary']};
            margin-bottom:0.4rem;">Sin decisión generada</div>
        <div style="font-size:12px;color:{c['text_muted']};margin-bottom:1.5rem;">
            Este caso no ha sido evaluado aún. Ejecuta la evaluación para obtener
            una decisión del motor de reglas.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="uraki-btn-primary">', unsafe_allow_html=True)
    if st.button("⚡ Evaluar caso ahora", key=f"eval_btn_{case['id']}", use_container_width=True):
        with st.spinner("Evaluando con motor de reglas..."):
            result, err = ds.evaluate(case["id"])
        if err:
            st.error(f"Error en evaluación: {err}")
        else:
            sm.flash_success("Evaluación completada")
            from services.api_client import get_client
            token = sm.get("auth_token")
            cache = sm.get("api_cache") or {}
            get_client(token, cache).invalidate(f"/cases/{case['id']}")
            get_client(token, cache).invalidate("/cases")
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Also show the simulation panel for cases without a decision
    from components.simulation_panel import render as render_simulation
    render_simulation(case, None)


# ── Header ────────────────────────────────────────────────────────────────────

def _render_header(case: dict, decision: dict, c: dict) -> None:
    p_color      = PRIORITY_COLORS.get(decision.get("priority", "LOW"), c["text_muted"])
    r_color      = RISK_COLORS.get(decision.get("risk_level", "BAJO"), c["text_muted"])
    confidence   = decision.get("confidence", 0)
    is_overridden = decision.get("is_overridden", False)

    # SLA badge for decision latency
    duration_ms = decision.get("duration_ms", 0)
    sla_within, sla_msg = SLAService().check_decision_sla(duration_ms)
    sla_badge = render_sla_badge_html(sla_within, sla_msg, c) if sla_msg else ""

    override_badge = (
        f'<span style="background:rgba(245,158,11,0.12);color:#F59E0B;'
        f'border:1px solid rgba(245,158,11,0.3);border-radius:4px;'
        f'padding:2px 7px;font-size:10px;font-weight:600;">⚠ Override</span>'
        if is_overridden else ""
    )

    conf_color = (
        "#22C55E" if confidence >= 0.85
        else "#F59E0B" if confidence >= 0.65
        else "#EF4444"
    )

    st.markdown(f"""
    <div style="padding:1rem 0 0.75rem;border-bottom:1px solid {c['border_subtle']};
        margin-bottom:0.75rem;">
        <div style="display:flex;align-items:center;justify-content:space-between;
            margin-bottom:0.6rem;">
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="font-size:11px;color:{c['text_muted']};
                    letter-spacing:0.06em;font-variant-numeric:tabular-nums;">
                    {case['id']}</span>
                <span style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
                    border-radius:4px;padding:1px 7px;font-size:11px;
                    color:{c['text_secondary']};">
                    {decision.get('classification','—').replace('_',' ')}
                </span>
                {override_badge}
            </div>
            <span style="font-size:11px;color:{c['text_muted']};">
                Confianza: <span style="color:{conf_color};font-weight:600;">
                {confidence:.0%}</span>
            </span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            {risk_badge_html(decision.get('risk_level','BAJO'))}
            {priority_badge_html(decision.get('priority','LOW'))}
            {score_bar_html(decision.get('risk_score',0), r_color, 100)}
            {'<span style="font-size:11px;color:#A855F7;background:rgba(168,85,247,0.10);border:1px solid rgba(168,85,247,0.3);border-radius:4px;padding:2px 7px;">⚖ Legal</span>' if decision.get('legal_flag') else ''}
            {'<span style="font-size:11px;color:' + c["accent"] + ';background:' + c["accent_muted"] + ';border:1px solid ' + c["border_accent"] + ';border-radius:4px;padding:2px 7px;">🛡 Póliza</span>' if decision.get('policy_flag') else ''}
            {sla_badge}
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Action block ──────────────────────────────────────────────────────────────

def _render_action_block(decision: dict, c: dict) -> None:
    action = decision.get("action", "REVISAR_MANUALMENTE")
    label  = decision.get("action_label", action)
    icon   = _ACTION_ICONS.get(action, "→")
    firm   = decision.get("firmness", "FIRME")
    f_icon, f_color = _FIRMNESS_LABELS.get(firm, ("→", c["accent"]))

    st.markdown(f"""
    <div style="
        background:linear-gradient(135deg,{c['accent_muted']} 0%,rgba(0,0,0,0) 100%);
        border:1.5px solid {c['border_accent']};border-radius:12px;
        padding:1.1rem 1.25rem;margin-bottom:0.75rem;
        animation:pulse-accent 3s ease-in-out infinite;
    ">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.1em;margin-bottom:0.4rem;">Acción requerida</div>
        <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-size:24px;">{icon}</span>
            <div>
                <div style="font-size:16px;font-weight:700;color:{c['text_primary']};
                    line-height:1.2;letter-spacing:-0.01em;">{label}</div>
                <div style="font-size:11px;color:{f_color};margin-top:2px;font-weight:500;">
                    {f_icon} Firmeza: {firm}
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Client block ──────────────────────────────────────────────────────────────

def _render_client_block(case: dict, c: dict) -> None:
    amount_str = fmt_currency(case.get("overdue_amount", 0), case.get("currency", "COP"))
    rent_str   = fmt_currency(case.get("monthly_rent", 0),   case.get("currency", "COP"))
    rent       = case.get("monthly_rent", 1) or 1
    ratio      = case.get("overdue_amount", 0) / rent
    prev       = case.get("previous_overdue_count", 0)

    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:10px;padding:0.9rem 1rem;margin-bottom:0.75rem;">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.1em;margin-bottom:0.6rem;">Arrendatario</div>
        <div style="font-size:15px;font-weight:600;color:{c['text_primary']};
            margin-bottom:0.2rem;">{case.get('client_name','—')}</div>
        <div style="font-size:12px;color:{c['text_secondary']};margin-bottom:0.6rem;">
            {case.get('property_address','—')} · {case.get('contract_id','—')}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-top:0.5rem;">
            <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                border-radius:8px;padding:0.5rem 0.75rem;">
                <div style="font-size:10px;color:{c['text_muted']};margin-bottom:2px;">
                    Días de mora</div>
                <div style="font-size:18px;font-weight:700;color:#EF4444;">
                    {case.get('overdue_days',0)}</div>
            </div>
            <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                border-radius:8px;padding:0.5rem 0.75rem;">
                <div style="font-size:10px;color:{c['text_muted']};margin-bottom:2px;">
                    Monto vencido</div>
                <div style="font-size:14px;font-weight:700;color:{c['text_primary']};
                    font-variant-numeric:tabular-nums;">{amount_str}</div>
            </div>
            <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                border-radius:8px;padding:0.5rem 0.75rem;">
                <div style="font-size:10px;color:{c['text_muted']};margin-bottom:2px;">
                    Canon mensual</div>
                <div style="font-size:13px;font-weight:600;
                    color:{c['text_secondary']};">{rent_str}</div>
            </div>
            <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                border-radius:8px;padding:0.5rem 0.75rem;">
                <div style="font-size:10px;color:{c['text_muted']};margin-bottom:2px;">
                    Ratio mora/canon</div>
                <div style="font-size:13px;font-weight:600;
                    color:{'#EF4444' if ratio>2 else '#F59E0B' if ratio>1 else '#22C55E'};">
                    {ratio:.1f}x</div>
            </div>
        </div>
        {f'<div style="margin-top:0.5rem;font-size:11px;color:{c["text_muted"]};">Incidentes previos: <span style="color:{c["warning"]};font-weight:600;">{prev}</span></div>' if prev > 0 else ''}
    </div>
    """, unsafe_allow_html=True)


# ── Reasoning ─────────────────────────────────────────────────────────────────

def _render_reasoning(decision: dict, c: dict) -> None:
    next_step  = decision.get("next_step", "")
    escalation = decision.get("escalation_target")
    rationale  = decision.get("rationale", "")

    st.markdown(f"""
    <div style="margin-bottom:0.75rem;">
        <div style="border-left:2px solid {c['border_accent']};padding:0.5rem 0.75rem;
            margin-bottom:0.5rem;background:{c['accent_glow'] if 'accent_glow' in c else c['accent_muted']};
            border-radius:0 6px 6px 0;">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:3px;">Por qué</div>
            <div style="font-size:13px;color:{c['text_secondary']};line-height:1.5;">
                {rationale}</div>
        </div>
        <div style="border-left:2px solid {c['success']};padding:0.5rem 0.75rem;
            background:rgba(34,197,94,0.04);border-radius:0 6px 6px 0;
            {'margin-bottom:0.5rem;' if escalation else ''}">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:3px;">Siguiente paso</div>
            <div style="font-size:13px;color:{c['text_secondary']};line-height:1.5;">
                {next_step}</div>
        </div>
        {'<div style="border-left:2px solid #A855F7;padding:0.5rem 0.75rem;background:rgba(168,85,247,0.04);border-radius:0 6px 6px 0;"><div style="font-size:10px;color:' + c["text_muted"] + ';text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Escalar a</div><div style="font-size:13px;color:#A855F7;font-weight:600;">' + str(escalation).upper() + '</div></div>' if escalation else ''}
    </div>
    """, unsafe_allow_html=True)


# ── Intelligence layer ────────────────────────────────────────────────────────

def _render_intelligence_layer(decision: dict, c: dict) -> None:
    """Structured decision intelligence: risk factors + data inputs used."""
    risk_factors = decision.get("risk_factors") or []
    data_used    = decision.get("data_used") or {}

    if not risk_factors and not data_used:
        return

    with st.expander("🧠 Inteligencia de decisión — factores y datos", expanded=False):

        if risk_factors:
            st.markdown(f"""
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:0.5rem;">
                Factores de riesgo que influenciaron la decisión</div>
            """, unsafe_allow_html=True)

            for factor in risk_factors:
                fname        = factor.get("factor", "—")
                fvalue       = factor.get("value", "—")
                fweight      = factor.get("weight", "Medio")
                contribution = factor.get("contribution", 0)
                fw_color     = _RISK_FACTOR_COLORS.get(fweight, c["text_muted"])
                bar_pct      = max(0, min(100, abs(contribution) * 100))
                bar_color    = fw_color if contribution >= 0 else "#22C55E"
                direction    = "↑" if contribution > 0 else "↓" if contribution < 0 else "—"

                st.markdown(f"""
                <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
                    border-radius:6px;padding:0.5rem 0.75rem;margin-bottom:4px;">
                    <div style="display:flex;justify-content:space-between;
                        align-items:center;margin-bottom:4px;">
                        <span style="font-size:12px;color:{c['text_primary']};
                            font-weight:500;">{fname}</span>
                        <div style="display:flex;align-items:center;gap:6px;">
                            <span style="font-size:11px;color:{c['text_secondary']};">
                                {fvalue}</span>
                            <span style="font-size:10px;color:{fw_color};font-weight:600;
                                background:rgba({_hex_to_rgb(fw_color)},0.1);
                                border-radius:3px;padding:1px 5px;">
                                {direction} {fweight}</span>
                        </div>
                    </div>
                    <div style="height:3px;background:{c['bg_secondary']};border-radius:3px;">
                        <div style="width:{bar_pct:.0f}%;height:100%;
                            background:{bar_color};border-radius:3px;
                            transition:width 0.3s ease;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        if data_used:
            st.markdown(f"""
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin:0.75rem 0 0.5rem;">
                Datos de entrada utilizados por el motor</div>
            """, unsafe_allow_html=True)

            items_html = "".join([
                f"""<div style="display:flex;justify-content:space-between;
                    padding:3px 0;border-bottom:1px solid {c['border_subtle']};">
                    <span style="font-size:11px;color:{c['text_muted']};">
                        {k.replace('_',' ').title()}</span>
                    <span style="font-size:11px;color:{c['text_secondary']};
                        font-weight:500;">{v}</span>
                </div>"""
                for k, v in data_used.items()
                if v is not None
            ])

            st.markdown(f"""
            <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
                border-radius:6px;padding:0.5rem 0.75rem;">
                {items_html}
            </div>
            """, unsafe_allow_html=True)


# ── Evidence ──────────────────────────────────────────────────────────────────

def _render_evidence(case: dict, decision: dict, c: dict) -> None:
    """Clause labels and document-decision links."""
    clauses          = decision.get("clause_labels", "")
    rule_id          = decision.get("rule_id", "—")
    rule_v           = decision.get("rule_version", "?")
    linked_docs      = decision.get("linked_documents") or case.get("linked_documents") or []

    if (not clauses or clauses == "—") and not linked_docs:
        return

    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:8px;padding:0.6rem 0.9rem;margin-bottom:0.75rem;">
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;
            margin-bottom:{('0.6rem' if linked_docs else '0')};">
            <div>
                <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.08em;margin-bottom:2px;">Evidencia contractual</div>
                <div style="font-size:12px;color:{c['text_secondary']};">
                    {clauses if clauses and clauses != '—' else '—'}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                    letter-spacing:0.08em;margin-bottom:2px;">Regla aplicada</div>
                <div style="font-size:12px;color:{c['accent']};font-weight:500;">
                    {rule_id} v{rule_v}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if linked_docs:
        st.markdown(f"""
        <div style="border-top:1px solid {c['border_subtle']};padding-top:0.5rem;
            margin-top:0.5rem;">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:0.4rem;">
                Documentos que influyeron en la decisión</div>
        """, unsafe_allow_html=True)

        for doc in linked_docs[:5]:
            doc_name    = doc.get("filename", doc.get("document_id", "—"))
            doc_type    = doc.get("type", "—")
            clause_trig = doc.get("clause_triggered", "")
            rule_trig   = doc.get("rule_triggered", "")

            st.markdown(f"""
            <div style="background:{c['bg_secondary']};border-radius:5px;
                padding:0.4rem 0.6rem;margin-bottom:3px;">
                <div style="display:flex;justify-content:space-between;
                    align-items:center;margin-bottom:2px;">
                    <span style="font-size:11px;color:{c['text_primary']};
                        font-weight:500;">📄 {doc_name}</span>
                    <span style="font-size:10px;color:{c['text_muted']};
                        background:{c['bg_elevated']};border-radius:3px;
                        padding:1px 5px;">{doc_type}</span>
                </div>
                {f'<div style="font-size:10px;color:{c["text_muted"]};line-height:1.4;">{clause_trig}</div>' if clause_trig else ''}
                {f'<div style="font-size:10px;color:{c["accent"]};margin-top:1px;">→ {rule_trig}</div>' if rule_trig else ''}
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# ── Audit trace ───────────────────────────────────────────────────────────────

def _render_audit_trace(case: dict, decision: dict, c: dict) -> None:
    from utils.time import time_ago, fmt_duration_ms

    rule_id       = decision.get("rule_id", "—")
    rule_v        = decision.get("rule_version", "?")
    rules_eval    = decision.get("rules_evaluated", 0)
    rules_disc    = decision.get("rules_discarded", 0)
    duration_ms   = decision.get("duration_ms", 0)
    created_at    = decision.get("created_at", "")
    why_rule      = decision.get("why_this_rule", "")
    is_overridden = decision.get("is_overridden", False)
    dec_id        = decision.get("id", "—")

    with st.expander("🔎 Trazabilidad de auditoría", expanded=False):
        st.markdown(f"""
        <div style="font-size:11px;line-height:1.8;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;
                margin-bottom:0.5rem;">
                <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                    border-radius:6px;padding:0.5rem 0.75rem;">
                    <div style="color:{c['text_muted']};font-size:10px;text-transform:uppercase;
                        letter-spacing:0.06em;">Decision ID</div>
                    <div style="color:{c['text_secondary']};word-break:break-all;
                        font-size:10px;">{(dec_id[:28] + '…') if len(dec_id) > 28 else dec_id}</div>
                </div>
                <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                    border-radius:6px;padding:0.5rem 0.75rem;">
                    <div style="color:{c['text_muted']};font-size:10px;text-transform:uppercase;
                        letter-spacing:0.06em;">Regla aplicada</div>
                    <div style="color:{c['accent']};font-weight:600;">
                        {rule_id} v{rule_v}</div>
                </div>
                <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                    border-radius:6px;padding:0.5rem 0.75rem;">
                    <div style="color:{c['text_muted']};font-size:10px;text-transform:uppercase;
                        letter-spacing:0.06em;">Reglas evaluadas</div>
                    <div style="color:{c['text_primary']};font-weight:600;">
                        {rules_eval} evaluadas · {rules_disc} descartadas</div>
                </div>
                <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                    border-radius:6px;padding:0.5rem 0.75rem;">
                    <div style="color:{c['text_muted']};font-size:10px;text-transform:uppercase;
                        letter-spacing:0.06em;">Tiempo evaluación</div>
                    <div style="color:{c['text_primary']};font-weight:600;">
                        {fmt_duration_ms(duration_ms) if duration_ms else '—'}</div>
                </div>
                <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                    border-radius:6px;padding:0.5rem 0.75rem;">
                    <div style="color:{c['text_muted']};font-size:10px;text-transform:uppercase;
                        letter-spacing:0.06em;">Generada</div>
                    <div style="color:{c['text_secondary']};">
                        {time_ago(created_at) if created_at else '—'}</div>
                </div>
                <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                    border-radius:6px;padding:0.5rem 0.75rem;">
                    <div style="color:{c['text_muted']};font-size:10px;text-transform:uppercase;
                        letter-spacing:0.06em;">Override</div>
                    <div style="color:{'#F59E0B' if is_overridden else c['success']};font-weight:600;">
                        {'Sí — modificada manualmente' if is_overridden else 'No'}</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        if why_rule:
            st.markdown(f"""
            <div style="background:{c['bg_card'] if 'bg_card' in c else c['bg_secondary']};
                border-radius:6px;padding:0.5rem 0.75rem;
                border-left:2px solid {c['border_accent']};">
                <div style="color:{c['text_muted']};font-size:10px;text-transform:uppercase;
                    letter-spacing:0.06em;margin-bottom:3px;">Resolución de conflicto</div>
                <div style="color:{c['text_secondary']};font-size:11px;line-height:1.5;">
                    {why_rule}</div>
            </div>
            """, unsafe_allow_html=True)

        if is_overridden:
            orig  = decision.get("original_action", "—")
            oreason = decision.get("override_reason", "—")
            st.markdown(f"""
            <div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25);
                border-radius:6px;padding:0.5rem 0.75rem;margin-top:0.5rem;">
                <div style="color:#F59E0B;font-size:10px;text-transform:uppercase;
                    letter-spacing:0.06em;margin-bottom:3px;">
                    ⚠ Historial de override</div>
                <div style="font-size:11px;color:{c['text_secondary']};line-height:1.5;">
                    Acción original: <strong>{orig}</strong><br/>
                    Razón: {oreason}
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        if has_permission("evaluate"):
            if st.button("↺ Re-evaluar caso", key=f"re_eval_{case['id']}", use_container_width=False):
                ds = DecisionService()
                with st.spinner("Re-evaluando..."):
                    result, err = ds.evaluate(case["id"])
                if err:
                    st.error(err)
                else:
                    from services.api_client import get_client
                    token = sm.get("auth_token")
                    cache = sm.get("api_cache") or {}
                    get_client(token, cache).invalidate(f"/cases/{case['id']}")
                    get_client(token, cache).invalidate("/cases")
                    sm.flash_success("Re-evaluación completada")
                    st.rerun()


# ── Message panel ─────────────────────────────────────────────────────────────

def _render_message_panel(case: dict, decision: dict, c: dict) -> None:
    message      = decision.get("suggested_message", "")
    ds           = DecisionService()
    copy_summary = ds.get_copy_summary(case, decision)

    st.markdown(f"""
    <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
        border-radius:10px;padding:1rem;margin-top:0.5rem;animation:fadeIn 0.2s ease;">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.75rem;">
            Mensaje al cliente
            <span style="background:{c['accent_muted']};color:{c['accent']};
                border-radius:4px;padding:1px 6px;font-size:10px;margin-left:6px;">
                Listo para enviar</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if message:
        st.markdown("**Mensaje al cliente:**")
        st.text_area("", value=message, height=220, key="msg_client_area",
                     label_visibility="collapsed")
        _copy_button_html(message, "📋 Copiar mensaje al cliente", "copy_client_btn")

    st.markdown("**Resumen operativo:**")
    st.text_area("", value=copy_summary, height=120, key="msg_summary_area",
                 label_visibility="collapsed")
    _copy_button_html(copy_summary, "📋 Copiar resumen operativo", "copy_summary_btn")


# ── Copy button ───────────────────────────────────────────────────────────────

def _copy_button_html(text: str, label: str, key: str) -> None:
    c = COLORS
    escaped = (text
               .replace("\\", "\\\\")
               .replace("`", "\\`")
               .replace("$", "\\$")
               .replace('"', '\\"'))
    components.html(f"""
    <style>
    .uraki-copy-btn{{
        display:inline-flex;align-items:center;gap:6px;
        background:{c['bg_elevated']};color:{c['text_secondary']};
        border:1px solid {c['border_default']};border-radius:7px;
        padding:7px 14px;font-family:'Inter',sans-serif;
        font-size:12px;font-weight:500;cursor:pointer;
        transition:all 0.15s ease;margin-top:4px;
    }}
    .uraki-copy-btn:hover{{
        background:{c['bg_elevated']};border-color:{c['border_accent']};
        color:{c['text_primary']};transform:translateY(-1px);
        box-shadow:0 4px 12px rgba(0,0,0,0.3);
    }}
    .uraki-copy-btn.copied{{
        background:rgba(34,197,94,0.10);border-color:rgba(34,197,94,0.3);color:#22C55E;
    }}
    </style>
    <button class="uraki-copy-btn" id="{key}"
        onclick="(function(){{
            var txt=`{escaped}`;
            navigator.clipboard.writeText(txt).then(function(){{
                var b=document.getElementById('{key}');
                b.textContent='✓ Copiado';b.classList.add('copied');
                setTimeout(function(){{b.textContent='{label}';b.classList.remove('copied');}},2000);
            }}).catch(function(){{
                var ta=document.createElement('textarea');
                ta.value=txt;ta.style.position='fixed';ta.style.opacity='0';
                document.body.appendChild(ta);ta.select();
                document.execCommand('copy');document.body.removeChild(ta);
                var b=document.getElementById('{key}');
                b.textContent='✓ Copiado';b.classList.add('copied');
                setTimeout(function(){{b.textContent='{label}';b.classList.remove('copied');}},2000);
            }});
        }})()">
        {label}
    </button>
    """, height=48, scrolling=False)
