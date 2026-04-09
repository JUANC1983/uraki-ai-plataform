# dashboard/core/event_bus.py
"""
Event bus — routes UI events to backend API.

Events:
  CASE_SELECTED   → update selected_case_id in state
  CASE_RESOLVED   → POST /cases/{id}/transition CLOSED  + advance queue
  CASE_ESCALATED  → POST /cases/{id}/transition ESCALATED
  CASE_EVALUATED  → POST /cases/{id}/evaluate
  STATUS_CHANGED  → POST /cases/{id}/transition {status}

Note: FILE_UPLOADED is no longer routed through the bus.
      upload_box.py calls DecisionService.upload_document() directly.
"""
import streamlit as st
import core.state_manager as sm
from services.case_service import CaseService


def emit(event: str, payload: dict | None = None) -> None:
    payload = payload or {}
    cs = CaseService()

    if event == "CASE_SELECTED":
        sm.select_case(payload["case_id"])

    elif event == "CASE_RESOLVED":
        case_id = payload["case_id"]
        err = cs.resolve_case(case_id)
        if err:
            sm.flash_error(f"No se pudo cerrar el caso: {err}")
        else:
            sm.record_resolution()
            sm.advance_queue(cs)
            sm.flash_success(f"Caso {case_id} cerrado correctamente")

    elif event == "CASE_ESCALATED":
        case_id = payload["case_id"]
        target  = payload.get("target", "supervisor")
        err = cs.escalate_case(case_id, target)
        if err:
            sm.flash_error(f"No se pudo escalar: {err}")
        else:
            sm.flash_success(f"Caso escalado a {target}")
            sm.select_case(case_id)

    elif event == "CASE_EVALUATED":
        sm.set("evaluating_case_id", payload.get("case_id"))
        # Actual evaluation is triggered inline in decision_card.py
        # so the spinner renders correctly inside the component

    elif event == "STATUS_CHANGED":
        case_id = payload["case_id"]
        status  = payload["status"]
        err = cs.set_status(case_id, status)
        if err:
            sm.flash_error(f"Error al cambiar estado: {err}")
        else:
            sm.select_case(case_id)

    # Rerun to reflect state changes
    st.rerun()
