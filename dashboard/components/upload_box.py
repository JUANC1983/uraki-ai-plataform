# dashboard/components/upload_box.py
"""Right-column upload box — drag & drop with preview and status."""
import streamlit as st
import core.state_manager as sm
from styles.theme import COLORS
from services.decision_service import DecisionService

_ALLOWED_TYPES = ["pdf", "docx", "txt"]
_TYPE_ICONS = {
    "pdf":  "📄",
    "docx": "📝",
    "txt":  "📝",
}
_TYPE_LABELS = {
    "contrato":       "Contrato",
    "pagare":         "Pagaré",
    "poliza":         "Póliza",
    "comunicacion":   "Comunicación",
    "soporte_pago":   "Soporte de pago",
}


def render(case: dict | None) -> None:
    c = COLORS

    # Header
    st.markdown(f"""
    <div style="
        padding:0.75rem 1rem 0.5rem;
        border-bottom:1px solid {c['border_subtle']};
    ">
        <span style="font-size:12px;font-weight:600;color:{c['text_secondary']};
            text-transform:uppercase;letter-spacing:0.08em;">Documentos</span>
    </div>
    """, unsafe_allow_html=True)

    if case is None:
        st.markdown(f"""
        <div style="padding:1.5rem 1rem;text-align:center;">
            <div style="font-size:20px;margin-bottom:0.5rem;">📂</div>
            <div style="font-size:12px;color:{c['text_muted']};">
                Selecciona un caso para gestionar documentos
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    # Document type selector
    doc_type = st.selectbox(
        label="Tipo de documento",
        options=list(_TYPE_LABELS.keys()),
        format_func=lambda k: _TYPE_LABELS[k],
        key="upload_doc_type",
        label_visibility="visible",
    )

    # Upload widget
    uploaded = st.file_uploader(
        label="Arrastra o selecciona un archivo",
        type=_ALLOWED_TYPES,
        key=f"uploader_{case['id']}",
        label_visibility="visible",
    )

    if uploaded:
        ext = uploaded.name.rsplit(".", 1)[-1].lower()
        icon = _TYPE_ICONS.get(ext, "📎")
        size_kb = uploaded.size // 1024

        st.markdown(f"""
        <div style="
            background:{c['bg_elevated']};
            border:1px solid {c['border_default']};
            border-radius:8px;padding:0.6rem 0.75rem;
            margin-top:0.5rem;
            display:flex;align-items:center;gap:10px;
        ">
            <span style="font-size:18px;">{icon}</span>
            <div style="flex:1;overflow:hidden;">
                <div style="font-size:12px;color:{c['text_primary']};
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
                    font-weight:500;">{uploaded.name}</div>
                <div style="font-size:11px;color:{c['text_muted']};">
                    {size_kb} KB · {ext.upper()} · {_TYPE_LABELS.get(doc_type,'—')}
                </div>
            </div>
            <span style="
                background:rgba(34,197,94,0.10);color:#22C55E;
                border-radius:4px;padding:1px 7px;font-size:10px;font-weight:500;
            ">Listo</span>
        </div>
        """, unsafe_allow_html=True)

        if st.button("⬆ Procesar documento", key="process_doc", use_container_width=True):
            content_type = (
                "application/pdf" if ext == "pdf"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if ext == "docx" else "text/plain"
            )
            with st.spinner("Subiendo..."):
                result, err = DecisionService().upload_document(
                    file_bytes=uploaded.getvalue(),
                    filename=uploaded.name,
                    content_type=content_type,
                    document_type=doc_type,
                    case_id=case["id"],
                )
            statuses = sm.get("upload_statuses") or {}
            if err:
                sm.flash_error(f"Error al subir {uploaded.name}: {err}")
                statuses[uploaded.name] = "error"
            else:
                doc_id = result.get("document_id", "?") if result else "?"
                sm.flash_success(f"Documento recibido · ID: {doc_id}")
                statuses[uploaded.name] = result.get("status", "uploaded") if result else "uploaded"
                from services.event_service import emit_document_uploaded
                emit_document_uploaded(case["id"], uploaded.name, doc_type)
            sm.set("upload_statuses", statuses)
            st.rerun()

    # ── Uploaded files status ──────────────────────────────────────────
    statuses = sm.get("upload_statuses") or {}
    if statuses:
        st.markdown(f"""
        <div style="margin-top:0.75rem;">
            <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
                letter-spacing:0.08em;margin-bottom:0.4rem;">Procesados en sesión</div>
        """, unsafe_allow_html=True)
        for fname, status in statuses.items():
            s_color = "#22C55E" if status == "uploaded" else "#EF4444" if status == "error" else "#F59E0B"
            s_label = "Subido" if status == "uploaded" else "Error" if status == "error" else "Procesando"
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "file"
            icon = _TYPE_ICONS.get(ext, "📎")
            st.markdown(f"""
            <div style="
                display:flex;align-items:center;justify-content:space-between;
                padding:4px 0;border-bottom:1px solid {c['border_subtle']};
            ">
                <div style="display:flex;align-items:center;gap:6px;">
                    <span>{icon}</span>
                    <span style="font-size:11px;color:{c['text_secondary']};
                        max-width:120px;overflow:hidden;text-overflow:ellipsis;
                        white-space:nowrap;">{fname}</span>
                </div>
                <span style="font-size:10px;color:{s_color};
                    font-weight:500;">{s_label}</span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ── Case context panel ─────────────────────────────────────────────
    _render_case_context(case, c)


def _render_case_context(case: dict, c: dict) -> None:
    st.markdown(f"""
    <div style="
        margin-top:1rem;
        border-top:1px solid {c['border_subtle']};
        padding-top:0.75rem;
    ">
        <div style="font-size:10px;color:{c['text_muted']};text-transform:uppercase;
            letter-spacing:0.08em;margin-bottom:0.6rem;">Contexto del caso</div>
    </div>
    """, unsafe_allow_html=True)

    rows = [
        ("Contrato",         case.get("contract_id", "—")),
        ("Póliza activa",    "Sí" if case.get("has_policy") else "No"),
        ("Acción legal",     "Sí" if case.get("has_legal_action") else "No"),
        ("Asignado a",       case.get("assigned_to", "—")),
        ("Cláusulas",        case.get("clause_labels", "—")),
    ]

    for label, value in rows:
        vcolor = "#22C55E" if value == "Sí" else ("#EF4444" if value == "No" else c["text_primary"])
        st.markdown(f"""
        <div style="
            display:flex;justify-content:space-between;align-items:flex-start;
            padding:5px 0;border-bottom:1px solid {c['border_subtle']};
        ">
            <span style="font-size:11px;color:{c['text_muted']};flex-shrink:0;
                margin-right:0.5rem;">{label}</span>
            <span style="font-size:11px;color:{vcolor};font-weight:500;
                text-align:right;word-break:break-word;">{value}</span>
        </div>
        """, unsafe_allow_html=True)
