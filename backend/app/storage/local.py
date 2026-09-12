"""Local filesystem StorageProvider for development.

Files are stored under `LOCAL_UPLOAD_DIR` (default `./data/uploads`),
which is git-ignored. `storage_ref` is a UUID-based relative filename so
it never depends on the caller's original filename or on directory
layout, keeping it portable to a future Drive/object-storage provider.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.storage.base import StorageProvider, StoredFile


class LocalFileStorageProvider(StorageProvider):
    def __init__(self, upload_dir: str) -> None:
        self._root = Path(upload_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, storage_ref: str) -> Path:
        path = (self._root / storage_ref).resolve()
        if self._root.resolve() not in path.parents and path != self._root.resolve():
            raise ValueError("Invalid storage_ref")
        return path

    async def save(self, filename: str, content_type: str, data: bytes) -> StoredFile:
        suffix = Path(filename).suffix
        storage_ref = f"{uuid.uuid4().hex}{suffix}"
        path = self._resolve(storage_ref)
        path.write_bytes(data)
        return StoredFile(
            storage_ref=storage_ref,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
        )

    async def read(self, storage_ref: str) -> bytes:
        return self._resolve(storage_ref).read_bytes()

    async def delete(self, storage_ref: str) -> None:
        path = self._resolve(storage_ref)
        path.unlink(missing_ok=True)

    async def exists(self, storage_ref: str) -> bool:
        return self._resolve(storage_ref).is_file()
