import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from automation.task_queue import process_document_async
from database.repositories.document_repository import DocumentRepository


TENANT = "00000000-0000-0000-0000-000000000001"
DOCUMENT = "00000000-0000-0000-0000-000000000002"


class _Context:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        return False


class DocumentRepositoryReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunk_replacement_is_locked_tenant_scoped_and_idempotent(self):
        document = SimpleNamespace(id=DOCUMENT, tenant_id=TENANT)
        result = SimpleNamespace(scalar_one_or_none=lambda: document)
        session = SimpleNamespace(
            execute=AsyncMock(return_value=result),
            add=Mock(),
            flush=AsyncMock(),
        )

        created = await DocumentRepository(session, TENANT).create_chunks(
            document_id=DOCUMENT,
            chunks=[{"content": "synthetic", "metadata": {}}],
            embeddings=[[1.0, 0.0]],
        )

        self.assertEqual(len(created), 1)
        self.assertEqual(session.execute.await_count, 2)
        lock_query = str(session.execute.await_args_list[0].args[0])
        delete_query = str(session.execute.await_args_list[1].args[0])
        self.assertIn("FOR UPDATE", lock_query)
        self.assertIn("documents.tenant_id", lock_query)
        self.assertIn("documents.id", lock_query)
        self.assertIn("DELETE FROM document_chunks", delete_query)
        self.assertIn("document_chunks.tenant_id", delete_query)
        self.assertIn("document_chunks.document_id", delete_query)

    async def test_create_ignores_caller_tenant_override(self):
        session = SimpleNamespace(add=Mock(), flush=AsyncMock())
        document = await DocumentRepository(session, TENANT).create(
            {"tenant_id": "00000000-0000-0000-0000-000000000099", "document_type": "note", "file_name": "synthetic.txt", "file_path": "path", "mime_type": "text/plain"}
        )
        self.assertEqual(document.tenant_id, TENANT)


class DocumentWorkerReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_processing_failure_is_persisted_audited_and_propagated(self):
        document = SimpleNamespace(doc_metadata={"processing_status": "processing"}, is_embedded=True)
        session = SimpleNamespace(commit=AsyncMock())

        class Repo:
            def __init__(self, *_):
                pass

            async def get(self, document_id):
                return document

        storage = SimpleNamespace(read_file=AsyncMock(return_value=b"synthetic"))
        agent = SimpleNamespace(process=AsyncMock(side_effect=ValueError("private source text")))
        audit = SimpleNamespace(log_error=Mock(), log_document_processed=Mock())
        with patch("database.base.AsyncSessionLocal", return_value=_Context(session)), patch("database.repositories.DocumentRepository", Repo), patch("connectors.storage_connector.get_storage_connector", return_value=storage), patch("agents.document_agent.DocumentAgent", return_value=agent), patch("connectors.llm_connector.get_llm_connector", side_effect=RuntimeError("disabled")), patch("core.audit_logger.get_audit_logger", return_value=audit):
            with self.assertRaises(ValueError):
                await process_document_async(
                    document_id=DOCUMENT, tenant_id=TENANT, file_path="safe-path",
                    mime_type="text/plain", document_type="note",
                )

        self.assertEqual(document.doc_metadata["processing_status"], "failed")
        self.assertEqual(document.doc_metadata["processing_error"], "ValueError")
        session.commit.assert_awaited_once()
        audit.log_error.assert_called_once()
        self.assertNotIn("private source text", str(audit.log_error.call_args))

    async def test_reprocessing_without_embeddings_clears_stale_flag(self):
        document = SimpleNamespace(doc_metadata={}, parsed_text=None, is_embedded=True)
        session = SimpleNamespace(commit=AsyncMock())

        class Repo:
            create_chunks = AsyncMock()

            def __init__(self, *_):
                pass

            async def get(self, document_id):
                return document

        result = {
            "parsed_text": "synthetic", "chunks": [{"content": "synthetic"}],
            "embeddings": [], "summary": None, "summary_status": "not_requested",
            "embedding_status": "not_requested",
        }
        storage = SimpleNamespace(read_file=AsyncMock(return_value=b"synthetic"))
        agent = SimpleNamespace(process=AsyncMock(return_value=result))
        audit = SimpleNamespace(log_error=Mock(), log_document_processed=Mock())
        bus = SimpleNamespace(publish=AsyncMock())
        with patch("database.base.AsyncSessionLocal", return_value=_Context(session)), patch("database.repositories.DocumentRepository", Repo), patch("connectors.storage_connector.get_storage_connector", return_value=storage), patch("agents.document_agent.DocumentAgent", return_value=agent), patch("connectors.llm_connector.get_llm_connector", side_effect=RuntimeError("disabled")), patch("core.audit_logger.get_audit_logger", return_value=audit), patch("core.event_bus.get_event_bus", return_value=bus):
            await process_document_async(
                document_id=DOCUMENT, tenant_id=TENANT, file_path="safe-path",
                mime_type="text/plain", document_type="note",
            )

        self.assertFalse(document.is_embedded)
        self.assertEqual(document.doc_metadata["processing_status"], "processed_without_embeddings")
        Repo.create_chunks.assert_awaited_once()
        bus.publish.assert_awaited_once()
        session.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
