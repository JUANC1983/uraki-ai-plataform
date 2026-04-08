# agents/document_agent.py
"""
Document Agent — parses, chunks, and embeds documents.
Supports PDF, DOCX, images (OCR placeholder).
"""
import io
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DocumentAgent:
    """
    Processes uploaded documents:
      1. Parse text (PDF/DOCX)
      2. Chunk by clause / paragraph
      3. Generate embeddings per chunk
      4. Store metadata (tenant_id, document_type, contract_id)
    """

    CHUNK_SIZE = 800   # characters per chunk
    CHUNK_OVERLAP = 100

    async def process(
        self,
        *,
        file_bytes: bytes,
        mime_type: str,
        document_type: str,
        tenant_id: str,
        contract_id: Optional[str] = None,
        llm_connector: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        Returns:
            {
                "parsed_text": str,
                "chunks": list[{content, clause_label, metadata}],
                "summary": Optional[str],
                "embeddings": list[list[float]],
            }
        """
        # 1. Parse
        parsed_text = await self._parse(file_bytes, mime_type)

        # 2. Chunk
        chunks = self._chunk_text(parsed_text)

        # 3. Generate summary (LLM, optional)
        summary: Optional[str] = None
        if llm_connector and parsed_text:
            try:
                summary = await llm_connector.summarize_document(
                    text=parsed_text,
                    document_type=document_type,
                )
            except Exception as exc:
                logger.warning("Document summarization failed: %s", exc)

        # 4. Generate embeddings (LLM, optional)
        embeddings: list[list[float]] = []
        if llm_connector and chunks:
            try:
                texts = [c["content"] for c in chunks]
                embeddings = await llm_connector.embed_batch(texts)
            except Exception as exc:
                logger.warning("Embedding generation failed: %s", exc)

        return {
            "parsed_text": parsed_text,
            "chunks": chunks,
            "summary": summary,
            "embeddings": embeddings,
        }

    async def _parse(self, file_bytes: bytes, mime_type: str) -> str:
        if mime_type == "application/pdf":
            return self._parse_pdf(file_bytes)
        elif mime_type in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ):
            return self._parse_docx(file_bytes)
        elif mime_type.startswith("text/"):
            return file_bytes.decode("utf-8", errors="ignore")
        elif mime_type.startswith("image/"):
            # OCR placeholder — extend with pytesseract or cloud OCR
            logger.warning("Image OCR not implemented — returning empty text")
            return ""
        else:
            logger.warning("Unsupported mime_type: %s", mime_type)
            return ""

    def _parse_pdf(self, file_bytes: bytes) -> str:
        try:
            import pdfplumber  # type: ignore

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n\n".join(pages)
        except Exception as exc:
            logger.error("PDF parsing failed: %s", exc)
            return ""

    def _parse_docx(self, file_bytes: bytes) -> str:
        try:
            from docx import Document  # type: ignore

            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as exc:
            logger.error("DOCX parsing failed: %s", exc)
            return ""

    def _chunk_text(self, text: str) -> list[dict[str, Any]]:
        """
        Chunk by clause (e.g. CLÁUSULA N) if detectable,
        otherwise by character window with overlap.
        """
        if not text:
            return []

        # Try clause-based splitting
        clause_pattern = re.compile(
            r"(CL[AÁ]USULA\s+\w+|ARTÍCULO\s+\d+|PARÁGRAFO\s+\d+)",
            re.IGNORECASE,
        )
        parts = clause_pattern.split(text)

        if len(parts) > 3:
            chunks = []
            i = 0
            label = None
            while i < len(parts):
                part = parts[i].strip()
                if clause_pattern.match(part):
                    label = part
                elif part:
                    chunks.append({
                        "content": part[:self.CHUNK_SIZE],
                        "clause_label": label,
                        "metadata": {"type": "clause"},
                    })
                i += 1
            return chunks

        # Sliding window chunking
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.CHUNK_SIZE, len(text))
            chunks.append({
                "content": text[start:end],
                "clause_label": None,
                "metadata": {"type": "window", "start": start, "end": end},
            })
            start += self.CHUNK_SIZE - self.CHUNK_OVERLAP

        return chunks

    def search_chunks(
        self,
        query_embedding: list[float],
        chunk_embeddings: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Cosine similarity search over in-memory chunk embeddings.
        For production: delegate to pgvector or Pinecone.
        """
        import math

        def cosine_sim(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x**2 for x in a))
            norm_b = math.sqrt(sum(x**2 for x in b))
            return dot / (norm_a * norm_b + 1e-10)

        scored = [
            {**chunk, "score": cosine_sim(query_embedding, chunk["embedding"])}
            for chunk in chunk_embeddings
            if chunk.get("embedding")
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]
