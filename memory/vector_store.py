"""JSONB embedding search implemented with Python cosine similarity."""

import math
from typing import Any


class VectorStore:
    """In-process vector ranking over tenant-filtered candidates."""

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if not a or not b:
            raise ValueError("Embedding vectors must not be empty")
        if len(a) != len(b):
            raise ValueError("Embedding vector dimensions must match")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in [*a, *b]
        ):
            raise ValueError("Embedding vectors must contain finite numeric values")
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        norm_a = math.sqrt(sum(float(x) ** 2 for x in a))
        norm_b = math.sqrt(sum(float(x) ** 2 for x in b))
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
        """Rank compatible candidate vectors, skipping corrupt stored vectors."""
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        if not isinstance(min_score, (int, float)) or not math.isfinite(float(min_score)) or not -1 <= min_score <= 1:
            raise ValueError("min_score must be finite and between -1 and 1")
        self.cosine_similarity(query_embedding, query_embedding)
        scored = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            embedding = candidate.get("embedding")
            if not embedding:
                continue
            try:
                score = self.cosine_similarity(query_embedding, embedding)
            except (TypeError, ValueError):
                continue
            if score >= min_score:
                scored.append({**candidate, "score": round(score, 4)})
        scored.sort(key=lambda item: (
            -item["score"], str(item.get("document_id", item.get("id", ""))),
            int(item.get("chunk_index", 0)),
        ))
        return scored[:top_k]

    def deduplicate(
        self,
        chunks: list[dict[str, Any]],
        threshold: float = 0.95,
    ) -> list[dict[str, Any]]:
        """Remove near-duplicates when stored vector dimensions are compatible."""
        unique: list[dict[str, Any]] = []
        for chunk in chunks:
            embedding = chunk.get("embedding")
            if not embedding:
                unique.append(chunk)
                continue
            is_duplicate = False
            for existing in unique:
                existing_embedding = existing.get("embedding")
                if not existing_embedding:
                    continue
                try:
                    if self.cosine_similarity(embedding, existing_embedding) > threshold:
                        is_duplicate = True
                        break
                except (TypeError, ValueError):
                    continue
            if not is_duplicate:
                unique.append(chunk)
        return unique
