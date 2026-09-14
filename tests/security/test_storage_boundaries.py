import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from connectors.storage_connector import StorageConnector, settings


class StorageBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = StorageConnector()
        self.storage.backend = "local"
        self.storage.local_base = Path(self.temp.name) / "storage"

    async def test_local_roundtrip_and_cross_tenant_rejection(self):
        saved = await self.storage.save_file(
            tenant_id="tenant-a", file_obj=io.BytesIO(b"synthetic document"),
            original_filename="../../contract.txt", content_type="text/plain",
        )
        self.assertEqual(await self.storage.read_file(saved["file_path"], tenant_id="tenant-a"), b"synthetic document")
        with self.assertRaises(ValueError):
            await self.storage.read_file(saved["file_path"], tenant_id="tenant-b")

        await self.storage.delete_file(saved["file_path"], tenant_id="tenant-a")
        self.assertFalse(Path(saved["file_path"]).exists())

    async def test_delete_rejects_cross_tenant_and_external_paths(self):
        saved = await self.storage.save_file(
            tenant_id="tenant-a", file_obj=io.BytesIO(b"synthetic document"),
            original_filename="contract.txt", content_type="text/plain",
        )
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_bytes(b"keep")
        for tenant, path in (("tenant-b", saved["file_path"]), ("tenant-a", str(outside))):
            with self.subTest(tenant=tenant), self.assertRaises(ValueError):
                await self.storage.delete_file(path, tenant_id=tenant)
        self.assertTrue(Path(saved["file_path"]).exists())
        self.assertTrue(outside.exists())

    async def test_external_path_and_backend_switch_are_rejected(self):
        outside = Path(self.temp.name) / "private.txt"
        outside.write_bytes(b"must not read")
        for path in (str(outside), "s3://foreign/tenant-a/file.txt"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                await self.storage.read_file(path, tenant_id="tenant-a")

    async def test_invalid_tenant_rejected_before_write(self):
        for tenant in ("../outside", "/absolute", "C:\\outside", "..", "a/b", "a\\b", ""):
            with self.subTest(tenant=tenant), self.assertRaises(ValueError):
                await self.storage.save_file(tenant_id=tenant, file_obj=io.BytesIO(b"x"), original_filename="a.txt", content_type="text/plain")
        self.assertFalse(self.storage.local_base.exists())

    async def test_missing_file_is_explicit_failure(self):
        with self.assertRaises(FileNotFoundError):
            await self.storage.read_file(str(self.storage.local_base / "tenant-a" / "missing.txt"), tenant_id="tenant-a")

    async def test_redirected_tenant_directory_is_rejected(self):
        # Model the resolved result of a symlink/junction without requiring
        # Windows symlink privileges. Both same-root and external redirects fail.
        base = self.storage.local_base.absolute()
        for target in (base / "tenant-b", base.parent / "outside"):
            with patch.object(Path, "resolve", side_effect=[base, target]):
                with self.assertRaises(ValueError):
                    self.storage._tenant_directory("tenant-a")

    async def test_s3_bucket_and_tenant_checked_before_provider(self):
        self.storage.backend = "s3"
        with patch.object(settings, "S3_BUCKET", "synthetic-bucket"), patch.object(self.storage, "_read_s3", new_callable=AsyncMock, return_value=b"synthetic") as provider:
            self.assertEqual(await self.storage.read_file("s3://synthetic-bucket/tenant-a/a.txt", tenant_id="tenant-a"), b"synthetic")
            provider.reset_mock()
            for uri in ("s3://foreign/tenant-a/a.txt", "s3://synthetic-bucket/tenant-b/a.txt", "s3://synthetic-bucket/tenant-a/../b.txt", "s3://synthetic-bucket/tenant-a/", "/local/file"):
                with self.subTest(uri=uri), self.assertRaises(ValueError):
                    await self.storage.read_file(uri, tenant_id="tenant-a")
            provider.assert_not_awaited()
