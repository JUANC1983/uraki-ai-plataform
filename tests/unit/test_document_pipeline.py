import unittest
from unittest.mock import patch

from agents.document_agent import DocumentAgent, DocumentProcessingError
from memory.vector_store import VectorStore


class _MismatchedEmbeddingClient:
    async def summarize_document(self, **kwargs):
        return "Summary"

    async def embed_batch(self, texts):
        return [[0.1, 0.2]] * max(0, len(texts) - 1)


class _UnsafeEnrichmentClient:
    async def summarize_document(self, **kwargs):
        return {"not": "text"}

    async def embed_batch(self, texts):
        return [[float("nan"), 0.2] for _ in texts]


class DocumentPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_utf8_text_processes_without_llm(self):
        result = await DocumentAgent().process(
            file_bytes="CLÁUSULA PRIMERA\nPago mensual".encode("utf-8"),
            mime_type="text/plain",
            document_type="contract",
            tenant_id="tenant-a",
            llm_connector=None,
        )

        self.assertTrue(result["chunks"])
        self.assertEqual(result["embedding_status"], "not_requested")
        self.assertEqual(result["embeddings"], [])

    async def test_empty_and_malformed_pdf_are_rejected(self):
        with self.assertRaises(DocumentProcessingError):
            await DocumentAgent().process(
                file_bytes=b"",
                mime_type="text/plain",
                document_type="note",
                tenant_id="tenant-a",
            )
        with self.assertRaises(DocumentProcessingError):
            await DocumentAgent().process(
                file_bytes=b"%PDF-not-a-real-pdf",
                mime_type="application/pdf",
                document_type="contract",
                tenant_id="tenant-a",
            )

    async def test_embedding_count_mismatch_is_explicit_partial_state(self):
        result = await DocumentAgent().process(
            file_bytes=("x" * 1200).encode(),
            mime_type="text/plain",
            document_type="note",
            tenant_id="tenant-a",
            llm_connector=_MismatchedEmbeddingClient(),
        )

        self.assertEqual(result["embedding_status"], "failed")
        self.assertEqual(result["embeddings"], [])

    async def test_unsafe_summary_and_vectors_fail_as_explicit_metadata(self):
        result = await DocumentAgent().process(
            file_bytes=b"Synthetic contract text",
            mime_type="text/plain",
            document_type="contract",
            tenant_id="tenant-a",
            llm_connector=_UnsafeEnrichmentClient(),
        )
        self.assertEqual(result["summary_status"], "failed")
        self.assertIsNone(result["summary"])
        self.assertEqual(result["embedding_status"], "failed")
        self.assertEqual(result["embeddings"], [])

    async def test_extracted_text_limit_fails_closed(self):
        with patch("agents.document_agent.MAX_EXTRACTED_CHARACTERS", 10):
            with self.assertRaises(DocumentProcessingError):
                await DocumentAgent().process(
                    file_bytes=b"a" * 11,
                    mime_type="text/plain",
                    document_type="note",
                    tenant_id="tenant-a",
                )

    def test_long_clause_is_chunked_without_dropping_tail(self):
        marker="END-OF-SYNTHETIC-CLAUSE"
        chunks=DocumentAgent()._chunk_text("CLÁUSULA PRIMERA\n" + "x" * 1600 + marker + "\nCLÁUSULA SEGUNDA\nshort")
        first_clause=[item for item in chunks if item["clause_label"]=="CLÁUSULA PRIMERA"]
        self.assertGreater(len(first_clause),1)
        self.assertIn(marker,first_clause[-1]["content"])


class VectorStoreTests(unittest.TestCase):
    def test_similarity_rejects_dimension_mismatch(self):
        with self.assertRaises(ValueError):
            VectorStore().cosine_similarity([1.0, 0.0], [1.0])

    def test_search_skips_corrupt_stored_vector(self):
        results = VectorStore().search(
            query_embedding=[1.0, 0.0],
            candidates=[
                {"id": "wrong-dimension", "embedding": [1.0]},
                {"id": "valid", "embedding": [1.0, 0.0]},
            ],
        )

        self.assertEqual([item["id"] for item in results], ["valid"])

    def test_equal_scores_have_stable_order_and_invalid_candidates_are_skipped(self):
        candidates=[
            {"document_id":"z","chunk_index":0,"embedding":[1.0,0.0]},
            object(),
            {"document_id":"a","chunk_index":2,"embedding":[1.0,0.0]},
            {"document_id":"a","chunk_index":1,"embedding":[1.0,0.0]},
        ]
        first=VectorStore().search([1.0,0.0],candidates)
        second=VectorStore().search([1.0,0.0],list(reversed(candidates)))
        expected=[("a",1),("a",2),("z",0)]
        self.assertEqual([(x["document_id"],x["chunk_index"]) for x in first],expected)
        self.assertEqual([(x["document_id"],x["chunk_index"]) for x in second],expected)
        for value in (float("nan"),2,-2):
            with self.assertRaises(ValueError):VectorStore().search([1.0],[{"embedding":[1.0]}],min_score=value)


if __name__ == "__main__":
    unittest.main()
