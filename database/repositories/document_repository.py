# database/repositories/document_repository.py
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Document, DocumentChunk
from database.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def create(self, data: dict[str, Any]) -> Document:
        safe_data = {key: value for key, value in data.items() if key != "tenant_id"}
        doc = Document(tenant_id=self.tenant_id, **safe_data)
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def get(self, doc_id: str) -> Optional[Document]:
        return await self._get_by_id(doc_id)

    async def list_by_case(self, case_id: str) -> list[Document]:
        rows = await self.session.execute(
            self._q().where(Document.case_id == case_id)
        )
        return list(rows.scalars().all())

    async def create_chunks(
        self,
        *,
        document_id: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[DocumentChunk]:
        # Serialize retries for one document, then replace its chunks in the
        # same transaction. A failed replacement rolls back to the prior set.
        result = await self.session.execute(
            self._q().where(Document.id == document_id).with_for_update()
        )
        doc = result.scalar_one_or_none()
        if not doc:
            from database.repositories.base import TenantIsolationError
            raise TenantIsolationError(
                f"Document '{document_id}' not found for tenant '{self.tenant_id}'"
            )

        await self.session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == self.tenant_id,
            )
        )

        created = []
        for i, chunk in enumerate(chunks):
            embedding = embeddings[i] if i < len(embeddings) else None
            db_chunk = DocumentChunk(
                tenant_id=self.tenant_id,
                document_id=document_id,
                chunk_index=i,
                clause_label=chunk.get("clause_label"),
                content=chunk["content"],
                embedding=embedding,
                doc_metadata=chunk.get("metadata"),
            )
            self.session.add(db_chunk)
            created.append(db_chunk)
        await self.session.flush()
        return created

    async def get_chunks(self, document_id: str) -> list[DocumentChunk]:
        """Load chunks — scoped by both tenant_id AND document ownership."""
        # Verify document ownership first
        doc = await self._get_by_id(document_id)
        if not doc:
            from database.repositories.base import TenantIsolationError
            raise TenantIsolationError(
                f"Document '{document_id}' not found for tenant '{self.tenant_id}'"
            )
        rows = await self.session.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == self.tenant_id,
            )
            .order_by(DocumentChunk.chunk_index)
        )
        return list(rows.scalars().all())

    async def get_all_chunks_for_tenant(
        self, case_id: Optional[str] = None
    ) -> list[DocumentChunk]:
        """Load all embedded chunks for this tenant (for semantic search)."""
        doc_ids_q = self._q().with_only_columns(Document.id)
        if case_id:
            doc_ids_q = doc_ids_q.where(Document.case_id == case_id)

        rows = await self.session.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.tenant_id == self.tenant_id,
                DocumentChunk.document_id.in_(doc_ids_q),
                DocumentChunk.embedding.isnot(None),
            )
        )
        return list(rows.scalars().all())

    async def mark_embedded(self, doc_id: str) -> None:
        doc = await self._get_by_id(doc_id)
        if doc:
            doc.is_embedded = True  # type: ignore[attr-defined]
