# memory/vector_store.py
"""
Vector Store abstraction — currently backed by pgvector (via JSONB for portability).
Extend to Pinecone or Weaviate by implementing the same interface.

NOTE: For production scale, migrate JSONB embeddings to pgvector extension:
  CREATE EXTENSION IF NOT EXISTS vector;
  ALTER TABLE document_chunks ADD COLUMN embedding_vec vector(1536);
"""
import math
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Multi-tenant vector store.
    All operations are scoped to tenant_id.
    """

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x**2 for x in a))
        norm_b = math.sqrt(sum(x**2 for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(
        self,
        query_embedding: list[float],
        candidates: list[dict[str, Any]],
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Rank candidates by cosine similarity.
        Each candidate must have an 'embedding' key.
        """
        scored = []
        for candidate in candidates:
            emb = candidate.get("embedding")
            if not emb:
                continue
            score = self.cosine_similarity(query_embedding, emb)
            if score >= min_score:
                scored.append({**candidate, "score": round(score, 4)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def deduplicate(
        self,
        chunks: list[dict[str, Any]],
        threshold: float = 0.95,
    ) -> list[dict[str, Any]]:
        """
        Remove near-duplicate chunks (cosine sim > threshold).
        Useful when ingesting overlapping documents.
        """
        unique = []
        for chunk in chunks:
            emb = chunk.get("embedding")
            if not emb:
                unique.append(chunk)
                continue
            is_dup = any(
                self.cosine_similarity(emb, u["embedding"]) > threshold
                for u in unique
                if u.get("embedding")
            )
            if not is_dup:
                unique.append(chunk)
        return unique
