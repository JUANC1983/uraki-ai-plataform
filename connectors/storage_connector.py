# connectors/storage_connector.py
"""
Storage Connector — local filesystem or S3.
Handles document uploads for multi-tenant isolation.
"""
import re
import uuid
from pathlib import Path
from typing import BinaryIO, Optional

from config.settings import get_settings

settings = get_settings()


class StorageConnector:
    def __init__(self) -> None:
        self.backend = settings.STORAGE_BACKEND
        self.local_base = Path(settings.LOCAL_STORAGE_PATH)

    @staticmethod
    def _validate_tenant(tenant_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", tenant_id):
            raise ValueError("Invalid storage tenant")

    def _tenant_directory(self, tenant_id: str) -> Path:
        self._validate_tenant(tenant_id)
        base = self.local_base.resolve()
        directory = (base / tenant_id).resolve()
        if directory != base / tenant_id:
            raise ValueError("Storage tenant escapes configured directory")
        return directory

    async def save_file(
        self,
        *,
        tenant_id: str,
        file_obj: BinaryIO,
        original_filename: str,
        content_type: str,
    ) -> dict[str, str]:
        """
        Save uploaded file. Returns:
            {"file_path": str, "file_name": str, "file_size": int}
        """
        self._validate_tenant(tenant_id)
        ext = Path(original_filename).suffix.lower()
        if ext and not re.fullmatch(r"\.[a-z0-9]{1,10}", ext):
            raise ValueError("Invalid file extension")
        safe_name = f"{uuid.uuid4()}{ext}"

        if self.backend == "local":
            return await self._save_local(tenant_id, file_obj, safe_name)
        elif self.backend == "s3":
            return await self._save_s3(tenant_id, file_obj, safe_name, content_type)
        raise ValueError(f"Unknown storage backend: {self.backend}")

    async def _save_local(
        self, tenant_id: str, file_obj: BinaryIO, file_name: str
    ) -> dict[str, str]:
        dest_dir = self._tenant_directory(tenant_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = (dest_dir / file_name).resolve()
        if dest_path.parent != dest_dir:
            raise ValueError("File escapes tenant directory")

        data = file_obj.read()
        with open(dest_path, "xb") as f:
            f.write(data)

        return {
            "file_path": str(dest_path),
            "file_name": file_name,
            "file_size": str(len(data)),
        }

    async def _save_s3(
        self,
        tenant_id: str,
        file_obj: BinaryIO,
        file_name: str,
        content_type: str,
    ) -> dict[str, str]:
        import boto3  # type: ignore

        s3 = boto3.client(
            "s3",
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        key = f"{tenant_id}/{file_name}"
        data = file_obj.read()
        s3.put_object(
            Bucket=settings.S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        file_path = f"s3://{settings.S3_BUCKET}/{key}"
        return {
            "file_path": file_path,
            "file_name": file_name,
            "file_size": str(len(data)),
        }

    async def read_file(self, file_path: str, *, tenant_id: str) -> bytes:
        """Read only a direct child of the authenticated tenant's storage namespace."""
        self._validate_tenant(tenant_id)
        if self.backend == "s3":
            prefix = f"s3://{settings.S3_BUCKET}/{tenant_id}/"
            if not settings.S3_BUCKET or not file_path.startswith(prefix):
                raise ValueError("Storage object outside tenant namespace")
            name = file_path[len(prefix):]
            if not name or name in {".", ".."} or any(c in name for c in "/\\"):
                raise ValueError("Invalid storage object key")
            return await self._read_s3(file_path)
        if self.backend != "local" or file_path.startswith("s3://"):
            raise ValueError("Storage backend mismatch")
        directory = self._tenant_directory(tenant_id)
        path = Path(file_path).resolve()
        if path.parent != directory:
            raise ValueError("Storage file outside tenant namespace")
        with open(path, "rb") as f:
            return f.read()

    async def delete_file(self, file_path: str, *, tenant_id: str) -> None:
        """Delete only a direct child of the tenant's configured namespace."""
        self._validate_tenant(tenant_id)
        if self.backend == "s3":
            prefix = f"s3://{settings.S3_BUCKET}/{tenant_id}/"
            if not settings.S3_BUCKET or not file_path.startswith(prefix):
                raise ValueError("Storage object outside tenant namespace")
            name = file_path[len(prefix):]
            if not name or name in {".", ".."} or any(c in name for c in "/\\"):
                raise ValueError("Invalid storage object key")
            await self._delete_s3(file_path)
            return
        if self.backend != "local" or file_path.startswith("s3://"):
            raise ValueError("Storage backend mismatch")
        directory = self._tenant_directory(tenant_id)
        path = Path(file_path).resolve()
        if path.parent != directory:
            raise ValueError("Storage file outside tenant namespace")
        path.unlink(missing_ok=True)

    async def _read_s3(self, s3_uri: str) -> bytes:
        import boto3  # type: ignore

        parts = s3_uri.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        s3 = boto3.client("s3")
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    async def _delete_s3(self, s3_uri: str) -> None:
        import boto3  # type: ignore

        bucket, key = s3_uri.replace("s3://", "").split("/", 1)
        boto3.client("s3").delete_object(Bucket=bucket, Key=key)


_storage: Optional[StorageConnector] = None


def get_storage_connector() -> StorageConnector:
    global _storage
    if _storage is None:
        _storage = StorageConnector()
    return _storage
