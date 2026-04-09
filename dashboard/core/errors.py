# dashboard/core/errors.py
"""
Error classification system.

All errors from the API surface layer are classified into one of four types.
The UI renders a different message and recovery path per class.

Classes:
  validation_error  — bad input, wrong field type, schema mismatch
  business_error    — rule violation, state conflict, permission denied
  system_error      — internal backend failure, unexpected 5xx
  network_error     — connection refused, timeout, DNS failure
  auth_error        — token expired or invalid credentials
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ErrorClass(str, Enum):
    VALIDATION = "validation_error"
    BUSINESS   = "business_error"
    SYSTEM     = "system_error"
    NETWORK    = "network_error"
    AUTH       = "auth_error"


@dataclass
class ClassifiedError:
    cls:        ErrorClass
    message:    str                       # user-facing message (Spanish)
    detail:     str                       # raw technical detail
    endpoint:   str       = ""
    status_code: int      = 0
    retryable:  bool      = False
    recovery:   str       = ""            # what the user can do
    error_id:   str       = ""            # correlates with backend logs


# ── Classification logic ──────────────────────────────────────────────────────

def classify(
    error_str: str,
    status_code: int = 0,
    endpoint: str = "",
) -> ClassifiedError:
    """
    Classify a raw error string + HTTP status into a ClassifiedError.
    Used by all service methods before returning errors to the UI.
    """
    s = error_str.lower() if error_str else ""

    # Auth
    if status_code == 401 or "sesión expirada" in s or "expired" in s or "token" in s:
        return ClassifiedError(
            cls=ErrorClass.AUTH,
            message="Tu sesión ha expirado. Inicia sesión nuevamente.",
            detail=error_str,
            status_code=status_code,
            endpoint=endpoint,
            retryable=False,
            recovery="Cierra sesión y vuelve a entrar.",
        )

    # Business — permission
    if status_code == 403 or "permisos" in s or "permission" in s or "forbidden" in s:
        return ClassifiedError(
            cls=ErrorClass.BUSINESS,
            message="No tienes permisos para realizar esta acción.",
            detail=error_str,
            status_code=status_code,
            endpoint=endpoint,
            retryable=False,
            recovery="Contacta a un administrador para obtener acceso.",
        )

    # Business — state conflict
    if status_code == 409 or "conflict" in s or "already" in s or "estado" in s and ("no puede" in s or "inválido" in s):
        return ClassifiedError(
            cls=ErrorClass.BUSINESS,
            message="Esta operación no es válida en el estado actual del caso.",
            detail=error_str,
            status_code=status_code,
            endpoint=endpoint,
            retryable=False,
            recovery="Recarga el caso para ver su estado actual.",
        )

    # Business — not found
    if status_code == 404 or "no encontrado" in s or "not found" in s:
        return ClassifiedError(
            cls=ErrorClass.BUSINESS,
            message="El recurso solicitado no existe o fue eliminado.",
            detail=error_str,
            status_code=status_code,
            endpoint=endpoint,
            retryable=False,
            recovery="Actualiza la lista de casos.",
        )

    # Validation
    if status_code == 422 or status_code == 400 or "validation" in s or "schema" in s or "inválid" in s or "required" in s:
        return ClassifiedError(
            cls=ErrorClass.VALIDATION,
            message="Los datos enviados no son válidos.",
            detail=error_str,
            status_code=status_code,
            endpoint=endpoint,
            retryable=False,
            recovery="Revisa los campos e intenta de nuevo.",
        )

    # Network
    if "sin conexión" in s or "timeout" in s or "network" in s or "connection" in s or status_code == 0:
        return ClassifiedError(
            cls=ErrorClass.NETWORK,
            message="No se pudo conectar al servidor.",
            detail=error_str,
            status_code=status_code,
            endpoint=endpoint,
            retryable=True,
            recovery="Verifica tu conexión y reintenta.",
        )

    # System — 5xx
    if status_code >= 500 or "internal" in s or "error del servidor" in s:
        return ClassifiedError(
            cls=ErrorClass.SYSTEM,
            message="Error interno del servidor. El equipo técnico ha sido notificado.",
            detail=error_str,
            status_code=status_code,
            endpoint=endpoint,
            retryable=True,
            recovery="Espera unos segundos e intenta de nuevo.",
        )

    # Default: system error
    return ClassifiedError(
        cls=ErrorClass.SYSTEM,
        message=error_str or "Error desconocido.",
        detail=error_str,
        status_code=status_code,
        endpoint=endpoint,
        retryable=True,
        recovery="Intenta de nuevo. Si persiste, contacta soporte.",
    )


# ── UI rendering ──────────────────────────────────────────────────────────────

_CLASS_STYLES: dict[ErrorClass, tuple[str, str, str]] = {
    # cls → (border_color, bg_color, icon)
    ErrorClass.VALIDATION: ("rgba(245,158,11,0.4)", "rgba(245,158,11,0.06)", "⚠"),
    ErrorClass.BUSINESS:   ("rgba(239,68,68,0.4)",  "rgba(239,68,68,0.06)",  "✕"),
    ErrorClass.SYSTEM:     ("rgba(168,85,247,0.4)", "rgba(168,85,247,0.06)", "⚙"),
    ErrorClass.NETWORK:    ("rgba(59,130,246,0.4)", "rgba(59,130,246,0.06)", "📡"),
    ErrorClass.AUTH:       ("rgba(245,158,11,0.4)", "rgba(245,158,11,0.06)", "🔑"),
}

_CLASS_LABELS: dict[ErrorClass, str] = {
    ErrorClass.VALIDATION: "Error de validación",
    ErrorClass.BUSINESS:   "Error de negocio",
    ErrorClass.SYSTEM:     "Error del sistema",
    ErrorClass.NETWORK:    "Error de red",
    ErrorClass.AUTH:       "Sesión expirada",
}


def render_error(err: ClassifiedError) -> str:
    """Return HTML string for a classified error banner."""
    border, bg, icon = _CLASS_STYLES.get(err.cls, ("rgba(239,68,68,0.4)", "rgba(239,68,68,0.06)", "!"))
    label = _CLASS_LABELS.get(err.cls, "Error")

    retry_hint = (
        f'<div style="font-size:10px;color:#3B82F6;margin-top:3px;">Reintentable automáticamente</div>'
        if err.retryable else ""
    )
    recovery = f'<div style="font-size:11px;color:#888888;margin-top:4px;">{err.recovery}</div>' if err.recovery else ""
    status_tag = f'<code style="font-size:10px;background:rgba(0,0,0,0.3);border-radius:3px;padding:1px 5px;margin-left:6px;">HTTP {err.status_code}</code>' if err.status_code else ""

    return f"""
    <div style="
        background:{bg};
        border:1px solid {border};
        border-radius:8px;
        padding:0.75rem 1rem;
        margin-bottom:0.5rem;
    ">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
            <span style="font-size:14px;">{icon}</span>
            <span style="font-size:12px;font-weight:600;color:#EEEEEE;">{label}</span>
            {status_tag}
        </div>
        <div style="font-size:12px;color:#BBBBBB;line-height:1.5;">{err.message}</div>
        {recovery}
        {retry_hint}
    </div>
    """


def classify_and_render(
    error_str: str,
    status_code: int = 0,
    endpoint: str = "",
) -> tuple[ClassifiedError, str]:
    """Classify an error and return (ClassifiedError, html_string)."""
    err = classify(error_str, status_code, endpoint)
    return err, render_error(err)
