# connectors/llm_connector.py
"""
LLM Connector — controlled interface to OpenAI.
The LLM is ONLY used for text generation and document summarization.
It CANNOT modify rule engine decisions.
"""
import logging
from typing import Any, Optional

from openai import AsyncOpenAI

from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMConnector:
    """
    Thin, auditable wrapper around OpenAI.
    All calls go through here — centralized rate limiting, logging, and control.

    CONSTRAINT: This class ONLY provides text drafting capabilities.
    Callers must NOT use outputs to override DecisionOutput fields directly.
    """

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL
        self._embedding_model = settings.OPENAI_EMBEDDING_MODEL

    async def draft_from_template(
        self,
        *,
        prompt: str,
        constraints: dict,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate a message from a structured template prompt.

        Called by MessageAgent after CommunicationEngine.build_prompt().
        The prompt already contains section-by-section instructions with
        variables injected. The constraints dict specifies exact values the
        LLM must not change (amounts, days, names, actions).

        The system prompt enforces:
          - Do not invent facts
          - Do not change any of the constrained values
          - Write only the message (no preamble, no explanations)
        """
        tone_guidance = constraints.get("tone_guidance", "Write professionally.")
        language = constraints.get("language", "es")
        formal = constraints.get("formal_address", True)
        address_note = "Use 'usted' (formal)." if formal else "Use 'tu' (informal)."
        _max_tokens = max_tokens or int(constraints.get("max_tokens", 600))

        # Build constraint list for the system prompt
        locked_facts: list[str] = []
        for key in ("client_name", "overdue_days", "overdue_amount", "contract_id", "action", "company_name"):
            if constraints.get(key):
                locked_facts.append(f"  - {key}: {constraints[key]}")
        locked_section = (
            "The following values are EXACT and must appear verbatim in the message:\n"
            + "\n".join(locked_facts)
            + "\nDo NOT change, round, translate, or omit any of these values."
        ) if locked_facts else ""

        system_prompt = (
            f"You are a professional communication specialist for a real estate company. "
            f"Your ONLY job is to write a natural language message in {language.upper()} "
            f"following the provided section structure.\n\n"
            f"TONE GUIDANCE: {tone_guidance}\n"
            f"ADDRESS: {address_note}\n\n"
            f"{locked_section}\n\n"
            "RULES:\n"
            "1. Write ONLY the message body. No headers, no explanations, no commentary.\n"
            "2. Follow each section label's instructions precisely.\n"
            "3. Do not add information not provided in the section instructions.\n"
            "4. Do not modify decisions, actions, or legal implications.\n"
            "5. Keep tone consistent throughout."
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=_max_tokens,
            temperature=0.3,   # lower than draft_message — more consistent output
        )
        return response.choices[0].message.content or ""

    async def draft_message(
        self,
        *,
        case_summary: str,
        action: str,
        tone: str = "profesional",
        language: str = "es",
        tenant_context: Optional[str] = None,
        max_tokens: int = 500,
    ) -> str:
        """
        Draft a communication message for the case.
        Tone and language are configured per tenant.
        """
        system_prompt = (
            "Eres un asistente especializado en redacción de comunicaciones inmobiliarias. "
            "Tu rol es redactar mensajes claros, profesionales y legalmente apropiados. "
            "NUNCA tomes decisiones operativas. Solo redacta el mensaje solicitado."
        )
        if tenant_context:
            system_prompt += f"\n\nContexto del cliente: {tenant_context}"

        user_prompt = (
            f"Redacta un mensaje en idioma '{language}' con tono '{tone}'.\n\n"
            f"Resumen del caso: {case_summary}\n"
            f"Acción a comunicar: {action}\n\n"
            "El mensaje debe ser claro, respetuoso y orientado a la resolución."
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.4,
        )
        return response.choices[0].message.content or ""

    async def classify_case_hint(
        self,
        *,
        case_description: str,
        available_classifications: list[str],
    ) -> dict[str, Any]:
        """
        Provide a classification HINT. The rule engine has final say.
        Returns: {"classification": str, "confidence": float, "reasoning": str}
        """
        prompt = (
            f"Analiza el siguiente caso y sugiere la clasificación más apropiada.\n"
            f"Opciones disponibles: {', '.join(available_classifications)}\n\n"
            f"Descripción del caso:\n{case_description}\n\n"
            "Responde SOLO con JSON en el formato:\n"
            '{"classification": "...", "confidence": 0.0-1.0, "reasoning": "..."}'
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
            temperature=0.2,
        )

        import json
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"classification": "OTRO", "confidence": 0.0, "reasoning": content}

    async def summarize_document(
        self,
        *,
        text: str,
        document_type: str,
        max_tokens: int = 800,
    ) -> str:
        """Summarize a legal or commercial document."""
        prompt = (
            f"Resume el siguiente documento de tipo '{document_type}'. "
            "Identifica: partes involucradas, obligaciones principales, fechas clave, "
            "cláusulas de mora, penalidades y cualquier riesgo legal relevante.\n\n"
            f"DOCUMENTO:\n{text[:4000]}"  # Limit to avoid token overflow
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a text chunk."""
        response = await self._client.embeddings.create(
            model=self._embedding_model,
            input=text[:8000],  # Limit to model context
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple text chunks."""
        response = await self._client.embeddings.create(
            model=self._embedding_model,
            input=[t[:8000] for t in texts],
        )
        return [item.embedding for item in response.data]


_connector: Optional[LLMConnector] = None


def get_llm_connector() -> LLMConnector:
    global _connector
    if _connector is None:
        _connector = LLMConnector()
    return _connector
