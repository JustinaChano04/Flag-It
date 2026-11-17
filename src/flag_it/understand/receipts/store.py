"""Where receipt files live. Production uses MinIO (S3 API) so the laptop and the GPU machine both
reach the same files; tests and a machine without MinIO use a local folder.

Settings: FLAG_IT_MINIO_ENDPOINT (host:port), FLAG_IT_MINIO_ACCESS_KEY, FLAG_IT_MINIO_SECRET_KEY,
FLAG_IT_MINIO_BUCKET (default "receipts"), FLAG_IT_MINIO_SECURE ("1" for TLS),
FLAG_IT_RECEIPT_DIR (the local folder when MinIO isn't set; default "receipts").
"""

import io
import os
from pathlib import Path
from typing import Protocol

from minio import Minio


class ReceiptStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"key {key!r} points outside the store")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class MinioStore:
    def __init__(self, client: Minio, bucket: str):
        self.client, self.bucket = client, bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

    @classmethod
    def from_env(cls) -> "MinioStore":
        client = Minio(
            os.environ["FLAG_IT_MINIO_ENDPOINT"],
            access_key=os.environ["FLAG_IT_MINIO_ACCESS_KEY"],
            secret_key=os.environ["FLAG_IT_MINIO_SECRET_KEY"],
            secure=os.environ.get("FLAG_IT_MINIO_SECURE") == "1",
        )
        return cls(client, os.environ.get("FLAG_IT_MINIO_BUCKET", "receipts"))

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(self.bucket, key, io.BytesIO(data), len(data), content_type=content_type)

    def get(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


def store_from_env() -> ReceiptStore:
    if os.environ.get("FLAG_IT_MINIO_ENDPOINT"):
        return MinioStore.from_env()
    return LocalStore(Path(os.environ.get("FLAG_IT_RECEIPT_DIR", "receipts")))
