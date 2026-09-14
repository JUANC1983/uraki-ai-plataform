"""Parse, chunk, optionally summarize, and optionally embed documents."""

from __future__ import annotations

import io
import logging
import re
import zipfile
from typing import Any, Optional

from memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

SUPPORTED_DOCUMENT_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    }
)
MAX_EXTRACTED_CHARACTERS = 2_000_000
MAX_DOCUMENT_CHUNKS = 5_000


def validate_docx_container(file_bytes: bytes, max_uncompressed_bytes: int) -> None:
    """Reject malformed, encrypted, or expansion-heavy DOCX archives."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            members = archive.infolist()
            names = {member.filename for member in members}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocumentProcessingError("DOCX structure is incomplete")
            if len(members) > 1_000 or any(member.flag_bits & 0x1 for member in members):
                raise DocumentProcessingError("DOCX archive structure is not allowed")
            if sum(member.file_size for member in members) > max_uncompressed_bytes:
                raise DocumentProcessingError("DOCX expanded content exceeds the safety limit")
    except zipfile.BadZipFile as exc:
        raise DocumentProcessingError("DOCX container is malformed") from exc


class DocumentProcessingError(ValueError):
    """Raised when an uploaded document cannot be parsed safely."""


class DocumentAgent:
    """Process text-bearing PDF, DOCX, and UTF-8 text documents."""

    CHUNK_SIZE = 800
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
        """Parse and chunk locally; LLM summary and embeddings are optional."""
        parsed_text = (await self._parse(file_bytes, mime_type)).strip()
        if not parsed_text:
            raise DocumentProcessingError("Document contains no extractable text")
        if len(parsed_text) > MAX_EXTRACTED_CHARACTERS:
            raise DocumentProcessingError("Extracted document text exceeds the safety limit")
        chunks = self._chunk_text(parsed_text)
        if not chunks:
            raise DocumentProcessingError("Document did not produce any text chunks")

        summary: Optional[str] = None
        summary_status = "not_requested"
        embedding_status = "not_requested"
        embeddings: list[list[float]] = []

        if llm_connector:
            try:
                candidate_summary = await llm_connector.summarize_document(
                    text=parsed_text,
                    document_type=document_type,
                )
                if (
                    not isinstance(candidate_summary, str)
                    or not candidate_summary.strip()
                    or len(candidate_summary) > 10_000
                ):
                    raise ValueError("Document summary must be bounded non-empty text")
                summary = candidate_summary.strip()
                summary_status = "completed"
            except Exception as exc:
                summary_status = "failed"
                logger.warning("Document summarization failed (%s)", type(exc).__name__)

            try:
                embeddings = await llm_connector.embed_batch(
                    [chunk["content"] for chunk in chunks]
                )
                if len(embeddings) != len(chunks):
                    raise ValueError("Embedding count does not match chunk count")
                dimensions = {len(vector) for vector in embeddings}
                if not embeddings or len(dimensions) != 1 or 0 in dimensions:
                    raise ValueError("Embedding dimensions are empty or inconsistent")
                for vector in embeddings:
                    VectorStore().cosine_similarity(vector, vector)
                embedding_status = "completed"
            except Exception as exc:
                embeddings = []
                embedding_status = "failed"
                logger.warning("Embedding generation failed (%s)", type(exc).__name__)

        return {
            "parsed_text": parsed_text,
            "chunks": chunks,
            "summary": summary,
            "summary_status": summary_status,
            "embeddings": embeddings,
            "embedding_status": embedding_status,
        }

    async def _parse(self, file_bytes: bytes, mime_type: str) -> str:
        if not file_bytes:
            raise DocumentProcessingError("Document is empty")
        if mime_type not in SUPPORTED_DOCUMENT_MIME_TYPES:
            raise DocumentProcessingError(f"Unsupported document MIME type: {mime_type}")
        if mime_type == "application/pdf":
            return self._parse_pdf(file_bytes)
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return self._parse_docx(file_bytes)
        try:
            return file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentProcessingError("Text document must be valid UTF-8") from exc

    def _parse_pdf(self, file_bytes: bytes) -> str:
        try:
            import pdfplumber  # type: ignore

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                return "\n\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as exc:
            raise DocumentProcessingError("PDF parsing failed") from exc

    def _parse_docx(self, file_bytes: bytes) -> str:
        try:
            from docx import Document  # type: ignore

            validate_docx_container(file_bytes, 50 * 1024 * 1024)
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(
                paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()
            )
        except Exception as exc:
            raise DocumentProcessingError("DOCX parsing failed") from exc

    def _chunk_text(self, text: str) -> list[dict[str, Any]]:
        """Chunk on common Spanish clause labels, otherwise use overlapping windows."""
        text = text.strip()
        if not text:
            return []
        clause_pattern = re.compile(
            r"(CL[AÁ]USULA\s+\w+|ART[IÍ]CULO\s+\d+|PAR[AÁ]GRAFO\s+\d+)",
            re.IGNORECASE,
        )
        parts = clause_pattern.split(text)
        if len(parts) > 3:
            chunks: list[dict[str, Any]] = []
            label: Optional[str] = None
            for raw_part in parts:
                part = raw_part.strip()
                if not part:
                    continue
                if clause_pattern.fullmatch(part):
                    label = part
                    continue
                step = self.CHUNK_SIZE - self.CHUNK_OVERLAP
                for start in range(0, len(part), step):
                    end = min(start + self.CHUNK_SIZE, len(part))
                    chunks.append({
                        "content": part[start:end],
                        "clause_label": label,
                        "metadata": {"type": "clause", "start": start, "end": end},
                    })
                    if len(chunks) > MAX_DOCUMENT_CHUNKS:
                        raise DocumentProcessingError("Document produces too many chunks")
                    if end == len(part):
                        break
            return chunks

        chunks = []
        step = self.CHUNK_SIZE - self.CHUNK_OVERLAP
        for start in range(0, len(text), step):
            end = min(start + self.CHUNK_SIZE, len(text))
            chunks.append(
                {
                    "content": text[start:end],
                    "clause_label": None,
                    "metadata": {"type": "window", "start": start, "end": end},
                }
            )
            if len(chunks) > MAX_DOCUMENT_CHUNKS:
                raise DocumentProcessingError("Document produces too many chunks")
            if end == len(text):
                break
        return chunks

    def search_chunks(
        self,
        query_embedding: list[float],
        chunk_embeddings: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Rank JSON-stored vectors in Python with strict dimension checks."""
        return VectorStore().search(
            query_embedding=query_embedding,
            candidates=chunk_embeddings,
            top_k=top_k,
        )
