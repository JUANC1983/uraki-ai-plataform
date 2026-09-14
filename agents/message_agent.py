# agents/message_agent.py
"""
Message Agent — generates structured client communications.

Flow:
  1. Build CommunicationContext from DecisionOutput + case_data + tone_settings
  2. Select appropriate MessageTemplate from registry
  3. Validate required variables are present
  4. Build structured prompt via CommunicationEngine
  5. Call LLMConnector.draft_from_template() — LLM converts structure to text
  6. Validate output (facts match source values)
  7. Return MessageResult (text + metadata + warnings)

Invariants:
  - DecisionOutput is never modified.
  - The LLM receives only the structured prompt, not the DecisionOutput object.
  - Numeric facts (amounts, days) are injected verbatim — LLM reformats only prose.
  - If LLM call fails, returns None gracefully (never crashes the decision pipeline).

Backward compatibility:
  - draft() signature adds case_data and returns Optional[str] as before
    so existing callers in DecisionAgent are unaffected.
  - draft_structured() is the new interface, returns MessageResult.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class MessageResult:
    """
    Full result of a message generation call.
    text is the ready-to-send communication.
    validation_passed and warnings describe fact-check results.
    """
    text: str
    tone: str
    tone_label: str
    language: str
    template_id: str
    validation_passed: bool
    warnings: list[str] = field(default_factory=list)
    context_snapshot: dict[str, Any] = field(default_factory=dict)


class MessageAgent:
    """
    Generates client communications using CommunicationEngine + LLM.

    The agent is stateless — all configuration is passed per call.
    It can be called with TenantConfig objects or raw dicts (backward compatible).
    """

    async def draft(
        self,
        *,
        decision: Any,               # DecisionOutput
        tenant_config: Any,          # TenantConfig object OR dict — both handled
        llm_connector: Any,          # LLMConnector
        case_data: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Backward-compatible interface. Returns the message text or None.
        Callers that don't need MessageResult metadata use this.
        """
        result = await self.draft_structured(
            decision=decision,
            tenant_config=tenant_config,
            llm_connector=llm_connector,
            case_data=case_data,
        )
        # Callers of the compact interface cannot inspect warnings. Fail closed
        # so a factually invalid draft never becomes a suggested message.
        return result.text if result and result.validation_passed else None

    async def draft_structured(
        self,
        *,
        decision: Any,
        tenant_config: Any,
        llm_connector: Any,
        case_data: Optional[dict[str, Any]] = None,
    ) -> Optional["MessageResult"]:
        """
        Full interface. Returns MessageResult with text + metadata + validation status.
        Use this when building a DecisionCard.
        """
        from core.communication_engine import CommunicationEngine, get_communication_engine

        engine = get_communication_engine()
        _case_data = case_data or {}

        # ── 1. Resolve tone settings ─────────────────────────────────────
        tone_settings = self._resolve_tone_settings(tenant_config)

        # ── 2. Build context ─────────────────────────────────────────────
        try:
            context = engine.build_context(decision, _case_data, tone_settings)
        except Exception as exc:
            logger.error("Communication context construction failed (%s)", type(exc).__name__)
            return None

        # ── 3. Select template ───────────────────────────────────────────
        template = engine.get_template(
            case_type=context.case_type,
            action=context.action,
            tone=context.tone,
        )

        # ── 4. Validate required variables ───────────────────────────────
        missing = engine.validate_context(template, context)
        if missing:
            logger.warning(
                "MessageAgent: missing variables %s for template '%s' — proceeding with defaults",
                missing, template.template_id,
            )
            # Inject placeholder so the prompt doesn't break
            fmt = context.as_format_dict()
            for var in missing:
                fmt[var] = f"[{var}]"

        # ── 5. Build structured prompt ───────────────────────────────────
        prompt, constraints = engine.build_prompt(template, context)

        # ── 6. Call LLM ──────────────────────────────────────────────────
        try:
            generated = await llm_connector.draft_from_template(
                prompt=prompt,
                constraints=constraints,
            )
        except AttributeError:
            # LLMConnector does not yet have draft_from_template → fall back to draft_message
            logger.warning(
                "LLMConnector.draft_from_template not available — falling back to draft_message"
            )
            try:
                generated = await llm_connector.draft_message(
                    case_summary=self._build_legacy_summary(decision, _case_data),
                    action=decision.action,
                    tone=context.tone,
                    language=context.language,
                    tenant_context=f"Empresa: {context.company_name}" if context.company_name else None,
                )
            except Exception as exc:
                logger.error("Fallback message drafting failed (%s)", type(exc).__name__)
                return None
        except Exception as exc:
            logger.error("Message drafting failed (%s)", type(exc).__name__)
            return None

        if not generated or not generated.strip():
            logger.warning("MessageAgent: LLM returned empty response")
            return None

        # ── 7. Validate output ───────────────────────────────────────────
        warnings = engine.validate_output(generated, context)
        validation_passed = len(warnings) == 0
        if warnings:
            logger.warning(
                "MessageAgent validation produced %d finding(s) for case %s",
                len(warnings), decision.case_id,
            )

        from core.communication_engine import TONE_LABELS
        return MessageResult(
            text=generated.strip(),
            tone=context.tone,
            tone_label=TONE_LABELS.get(context.tone, context.tone.capitalize()),
            language=context.language,
            template_id=template.template_id,
            validation_passed=validation_passed,
            warnings=warnings,
            context_snapshot={
                "client_name":     context.client_name,
                "overdue_days":    context.overdue_days,
                "overdue_amount":  context.overdue_amount_fmt,
                "action":          context.action,
                "tone":            context.tone,
                "template_id":     template.template_id,
            },
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _resolve_tone_settings(self, tenant_config: Any) -> Any:
        """
        Return tone_settings from TenantConfig object or a dict shim.
        Handles both typed TenantConfig and legacy raw dict.
        """
        if hasattr(tenant_config, "tone_settings"):
            return tenant_config.tone_settings
        # Raw dict: wrap in a simple namespace
        return _DictToneSettings(tenant_config)

    def _build_legacy_summary(
        self, decision: Any, case_data: dict[str, Any]
    ) -> str:
        """Fallback summary for older LLMConnector without draft_from_template."""
        client = case_data.get("client_name", "")
        overdue = case_data.get("overdue_days", 0)
        amount = case_data.get("overdue_amount", 0)
        currency = case_data.get("currency", "COP")
        parts = [
            f"Caso: {decision.case_id}",
            f"Cliente: {client}" if client else "",
            f"Dias de mora: {overdue}",
            f"Monto: ${amount:,.0f} {currency}" if amount else "",
            f"Clasificacion: {decision.classification.value if hasattr(decision.classification, 'value') else decision.classification}",
            f"Riesgo: {decision.risk_level.value if hasattr(decision.risk_level, 'value') else decision.risk_level} ({decision.risk_score:.1f})",
            f"Accion: {decision.action}",
        ]
        return ". ".join(p for p in parts if p)


class _DictToneSettings:
    """
    Minimal shim so CommunicationEngine.build_context() can use hasattr/getattr
    consistently whether it receives a ToneSettings object or a raw dict.
    """
    def __init__(self, d: dict[str, Any]) -> None:
        self.tone = d.get("communication_tone") or d.get("tone", "firme")
        self.language = d.get("communication_language") or d.get("language", "es")
        self.company_name = d.get("company_name", "")
        self.use_formal_address = d.get("use_formal_address", True)
        self.signature = d.get("signature", "")
