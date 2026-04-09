# dashboard/services/response_builder.py
"""
Structured response builder — consistent format for every client communication.

Every generated response follows:
  1. Saludo         — greeting, formal or informal based on tenant tone
  2. Contexto       — what situation is being addressed
  3. Explicación    — why this decision / what happened
  4. Acción         — the concrete next step required
  5. Cierre         — professional closing

The builder uses the decision output + case data to fill each section.
If the backend already provides a `suggested_message`, it is reformatted
to enforce the 5-section structure. Otherwise the message is built client-side.

Tone is pulled from tenant config (tone_settings.tone + use_formal_address).
"""
from __future__ import annotations

import re
import textwrap
from typing import Optional

from core.config_manager import get_config
from utils.formatters import fmt_currency


# ── Tone resolution ───────────────────────────────────────────────────────────

def _tone_settings() -> dict:
    cfg = get_config()
    return cfg.get("config", {}).get("tone_settings", {})


def _formal() -> bool:
    return bool(_tone_settings().get("use_formal_address", True))


def _company() -> str:
    return _tone_settings().get("company_name") or "URAKI OPS"


def _tone() -> str:
    return _tone_settings().get("tone", "firme")


# ── Section templates by tone ─────────────────────────────────────────────────

_GREETINGS = {
    "firme": {
        True:  "Estimado/a {name},",
        False: "Hola {name},",
    },
    "suave": {
        True:  "Estimado/a {name},",
        False: "Hola {name}, esperamos que se encuentre bien.",
    },
    "neutral": {
        True:  "Estimado/a {name}:",
        False: "Buenos días, {name}:",
    },
    "legal": {
        True:  "Estimado/a señor/a {name}:",
        False: "Estimado/a {name}:",
    },
}

_CLOSINGS = {
    "firme": (
        "Quedamos atentos a su respuesta antes del plazo indicado.\n"
        "Atentamente,\n{company}"
    ),
    "suave": (
        "Estamos disponibles para cualquier consulta o acuerdo que facilite "
        "la regularización de su situación.\n"
        "Cordialmente,\n{company}"
    ),
    "neutral": (
        "Agradecemos su atención y quedamos en espera de su respuesta.\n"
        "Saludos,\n{company}"
    ),
    "legal": (
        "Le notificamos que de no regularizar la situación descrita en el plazo indicado, "
        "procederemos conforme a las disposiciones contractuales y legales vigentes.\n"
        "Con efectos legales,\n{company}"
    ),
}

# ── Context paragraph variants (for regeneration) ─────────────────────────────

_CONTEXT_VARIANTS = [
    (   # 0 — default
        "Nos comunicamos con usted en relación a su obligación de arrendamiento, "
        "la cual presenta un saldo pendiente de {amount} "
        "con {days} día{s} de mora a la fecha."
    ),
    (   # 1
        "Le escribimos para informarle que su contrato de arrendamiento "
        "registra una mora de {days} día{s} por un valor de {amount}."
    ),
    (   # 2
        "Por medio de la presente, le notificamos que existe un saldo vencido "
        "de {amount} correspondiente a {days} día{s} sin regularizar."
    ),
    (   # 3
        "Nos dirigimos a usted para recordarle que su obligación de arrendamiento "
        "presenta un saldo de {amount} con {days} día{s} de vencimiento."
    ),
]

# ── Express (1-line) action phrases ───────────────────────────────────────────

_EXPRESS_ACTIONS = {
    "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA":
        "Activamos póliza y notificamos aseguradora de inmediato.",
    "INICIAR_DEMANDA_DE_RESTITUCIÓN":
        "Iniciamos proceso legal de restitución del inmueble.",
    "PROPONER_ACUERDO_DE_PAGO":
        "Le proponemos acuerdo de pago. Contáctenos para coordinar.",
    "COBRAR_PENALIDAD_CONTRACTUAL":
        "Aplicamos penalidad contractual según contrato vigente.",
    "ENVIAR_RECORDATORIO_DE_PAGO":
        "Pago pendiente. Regularice a la brevedad para evitar cargos.",
    "REVISAR_MANUALMENTE":
        "Caso en revisión. Le contactamos en las próximas horas.",
}

_ACTION_PHRASES = {
    "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA": (
        "Procederemos a activar la póliza de seguro vigente y a notificar a la aseguradora "
        "sobre la situación actual de mora. Le informaremos sobre los pasos a seguir."
    ),
    "INICIAR_DEMANDA_DE_RESTITUCIÓN": (
        "Ante la situación actual, nos vemos en la necesidad de iniciar el proceso legal "
        "de restitución del inmueble. Le instamos a regularizar su situación "
        "antes de que el proceso avance."
    ),
    "PROPONER_ACUERDO_DE_PAGO": (
        "Le proponemos establecer un acuerdo de pago que le permita regularizar "
        "su obligación de manera progresiva. Por favor, contáctenos para definir "
        "los términos del acuerdo."
    ),
    "COBRAR_PENALIDAD_CONTRACTUAL": (
        "De acuerdo con las cláusulas contractuales vigentes, procederemos a "
        "aplicar la penalidad por incumplimiento. El valor será incluido en "
        "su próxima liquidación."
    ),
    "ENVIAR_RECORDATORIO_DE_PAGO": (
        "Le recordamos que su obligación de pago se encuentra pendiente. "
        "Por favor, realice el pago correspondiente a la brevedad posible "
        "para evitar cargos adicionales."
    ),
    "REVISAR_MANUALMENTE": (
        "Su caso está siendo revisado por nuestro equipo de gestión. "
        "Nos pondremos en contacto con usted en las próximas horas "
        "para informarle sobre los pasos a seguir."
    ),
}


# ── Main builder ──────────────────────────────────────────────────────────────

def build_response(
    case: dict,
    decision: dict,
    tone_override: str | None = None,
) -> str:
    """
    Build a full structured client response.

    If `suggested_message` is already provided by the backend and appears
    well-formed (>100 chars), it is formatted and returned directly
    (unless tone_override forces a fresh build).
    Otherwise the response is constructed from templates.
    """
    existing = (decision.get("suggested_message") or "").strip()
    if len(existing) > 100 and not tone_override:
        return _format_existing(existing, case, decision)

    return _build_from_scratch(case, decision, tone_override=tone_override)


def _build_from_scratch(
    case: dict,
    decision: dict,
    tone_override: str | None = None,
) -> str:
    tone    = tone_override or _tone()
    formal  = _formal()
    company = _company()
    name    = case.get("client_name", "cliente").split()[0]

    action       = decision.get("action", "REVISAR_MANUALMENTE")
    overdue_days = int(case.get("overdue_days", 0))
    amount       = float(case.get("overdue_amount", 0))
    currency     = case.get("currency", "COP")
    rationale    = decision.get("rationale", "").strip()
    next_step    = decision.get("next_step", "").strip()
    legal_flag   = bool(decision.get("legal_flag", False))
    policy_flag  = bool(decision.get("policy_flag", False))

    # 1. Saludo
    greeting = _GREETINGS.get(tone, _GREETINGS["firme"])[formal].format(name=name)

    # 2. Contexto
    context = (
        f"Nos comunicamos con usted en relación a su obligación de arrendamiento, "
        f"la cual presenta un saldo pendiente de {fmt_currency(amount, currency)} "
        f"con {overdue_days} día{'s' if overdue_days != 1 else ''} de mora a la fecha."
    )

    # 3. Explicación
    if rationale:
        explanation = rationale
    else:
        parts = ["Tras la revisión de su expediente"]
        if legal_flag:
            parts.append("y considerando las implicaciones contractuales vigentes")
        if policy_flag:
            parts.append("y la cobertura de póliza asociada")
        explanation = ", ".join(parts) + ", hemos determinado la acción que se describe a continuación."

    # 4. Acción
    action_text = _ACTION_PHRASES.get(action, _ACTION_PHRASES["REVISAR_MANUALMENTE"])
    if next_step and len(next_step) > 20:
        action_text = f"{action_text}\n\n{next_step}"

    # 5. Cierre
    closing = _CLOSINGS.get(tone, _CLOSINGS["firme"]).format(company=company)

    parts = [greeting, "", context, "", explanation, "", action_text, "", closing]
    return "\n".join(parts)


def _format_existing(msg: str, case: dict, decision: dict) -> str:
    """
    Take a backend-provided message and ensure it has proper structure.
    Adds greeting and closing if missing.
    """
    tone    = _tone()
    formal  = _formal()
    company = _company()
    name    = case.get("client_name", "cliente").split()[0]

    has_greeting = any(msg.startswith(g) for g in ("Estimado", "Hola", "Buenos", "Querido"))
    has_closing  = any(word in msg for word in ("Atentamente", "Cordialmente", "Saludos"))

    lines = []
    if not has_greeting:
        lines.append(_GREETINGS.get(tone, _GREETINGS["firme"])[formal].format(name=name))
        lines.append("")

    lines.append(msg)

    if not has_closing:
        lines.append("")
        lines.append(_CLOSINGS.get(tone, _CLOSINGS["firme"]).format(company=company))

    return "\n".join(lines)


# ── Clipboard formatting ──────────────────────────────────────────────────────

def clean_for_clipboard(text: str) -> str:
    """
    Clean the response text for clipboard copy.
    - Collapses multiple blank lines
    - Trims leading/trailing whitespace
    - Preserves paragraph structure
    """
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Express response (1–2 lines, ultra direct) ───────────────────────────────

def build_express_response(case: dict, decision: dict) -> str:
    """Single-sentence response — maximum speed, zero friction."""
    name    = case.get("client_name", "cliente").split()[0]
    action  = decision.get("action", "REVISAR_MANUALMENTE")
    company = _company()
    body    = _EXPRESS_ACTIONS.get(action, _EXPRESS_ACTIONS["REVISAR_MANUALMENTE"])
    return f"{name}: {body} — {company}"


# ── Regeneration variant (same structure, alternate phrasing) ─────────────────

def build_response_variant(
    case: dict,
    decision: dict,
    variant: int = 0,
    tone_override: str | None = None,
) -> str:
    """
    Alternate wording of the standard 5-section response.
    Cycles through _CONTEXT_VARIANTS for the context paragraph.
    All other sections follow the same logic as _build_from_scratch.
    """
    tone    = tone_override or _tone()
    formal  = _formal()
    company = _company()
    name    = case.get("client_name", "cliente").split()[0]

    action       = decision.get("action", "REVISAR_MANUALMENTE")
    overdue_days = int(case.get("overdue_days", 0))
    amount       = float(case.get("overdue_amount", 0))
    currency     = case.get("currency", "COP")
    rationale    = decision.get("rationale", "").strip()
    next_step    = decision.get("next_step", "").strip()
    legal_flag   = bool(decision.get("legal_flag", False))
    policy_flag  = bool(decision.get("policy_flag", False))

    greeting = _GREETINGS.get(tone, _GREETINGS["firme"])[formal].format(name=name)

    ctx_tpl = _CONTEXT_VARIANTS[variant % len(_CONTEXT_VARIANTS)]
    context  = ctx_tpl.format(
        amount=fmt_currency(amount, currency),
        days=overdue_days,
        s="s" if overdue_days != 1 else "",
    )

    if rationale:
        explanation = rationale
    else:
        parts = ["Tras la revisión de su expediente"]
        if legal_flag:
            parts.append("y considerando las implicaciones contractuales vigentes")
        if policy_flag:
            parts.append("y la cobertura de póliza asociada")
        explanation = ", ".join(parts) + ", hemos determinado la acción que se describe a continuación."

    action_text = _ACTION_PHRASES.get(action, _ACTION_PHRASES["REVISAR_MANUALMENTE"])
    if next_step and len(next_step) > 20:
        action_text = f"{action_text}\n\n{next_step}"

    closing = _CLOSINGS.get(tone, _CLOSINGS["firme"]).format(company=company)

    return clean_for_clipboard("\n".join([greeting, "", context, "", explanation, "", action_text, "", closing]))


# ── Multi-channel variants ────────────────────────────────────────────────────

_WHATSAPP_ACTIONS = {
    "ACTIVAR_POLIZA_Y_NOTIFICAR_ASEGURADORA":
        "Activaremos tu póliza e informaremos a la aseguradora. Te contactamos pronto con los detalles.",
    "INICIAR_DEMANDA_DE_RESTITUCIÓN":
        "Ante el incumplimiento acumulado, iniciaremos proceso legal de restitución. Regulariza urgente.",
    "PROPONER_ACUERDO_DE_PAGO":
        "Te proponemos un acuerdo de pago progresivo. Escríbenos para coordinar los términos.",
    "COBRAR_PENALIDAD_CONTRACTUAL":
        "Aplicamos penalidad contractual por incumplimiento. El valor se incluirá en tu próxima liquidación.",
    "ENVIAR_RECORDATORIO_DE_PAGO":
        "Tienes un pago pendiente. Realízalo pronto para evitar cargos adicionales.",
    "REVISAR_MANUALMENTE":
        "Estamos revisando tu caso. Te contactamos en las próximas horas.",
}


def build_whatsapp_response(case: dict, decision: dict) -> str:
    """
    Short, direct WhatsApp message — max 3 paragraphs, no formal structure.
    Uses first name only, plain language, bold markers for key info.
    """
    name     = case.get("client_name", "cliente").split()[0]
    amount   = float(case.get("overdue_amount", 0))
    currency = case.get("currency", "COP")
    action   = decision.get("action", "REVISAR_MANUALMENTE")
    company  = _company()

    body       = _WHATSAPP_ACTIONS.get(action, _WHATSAPP_ACTIONS["REVISAR_MANUALMENTE"])
    amount_str = fmt_currency(amount, currency)

    return clean_for_clipboard(
        f"Hola {name}, te contactamos de *{company}*.\n\n"
        f"Tu saldo pendiente es de *{amount_str}*. {body}\n\n"
        f"— {company}"
    )


def build_email_response(case: dict, decision: dict) -> str:
    """
    Full formal email with subject line prepended, separated by a divider.
    Body is identical to build_response() to guarantee structural consistency.
    """
    action_label = (
        decision.get("action_label")
        or decision.get("action", "Notificación").replace("_", " ").title()
    )
    name    = case.get("client_name", "cliente")
    body    = build_response(case, decision)
    subject = f"Asunto: {action_label} — {name}"
    divider = "─" * min(len(subject), 60)
    return clean_for_clipboard(f"{subject}\n{divider}\n\n{body}")
