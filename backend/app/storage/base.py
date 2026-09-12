"""StorageProvider interface.

Frozen in Phase 1: files/media are always stored outside relational
tables; the database/sheet only stores metadata + `storage_ref`. Swapping
`LocalFileStorageProvider` for a Google Drive or object-storage provider
later must not change any Web workflow.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredFile:
    """Metadata returned after a successful save.

    `storage_ref` is the opaque reference persisted by the caller
    (e.g. in a repository record) and later passed back to `open`/`delete`.
    It must not encode assumptions about the underlying backend (e.g. not
    a raw filesystem path leaking outside the provider).
    """

    storage_ref: str
    filename: str
    content_type: str
    size_bytes: int


class StorageProvider(ABC):
    @abstractmethod
    async def save(self, filename: str, content_type: str, data: bytes) -> StoredFile:
        """Persist `data` and return its metadata/storage_ref."""

    @abstractmethod
    async def read(self, storage_ref: str) -> bytes:
        """Return the raw bytes for a previously saved file."""

    @abstractmethod
    async def delete(self, storage_ref: str) -> None:
        """Remove a previously saved file. No-op if it does not exist."""

    @abstractmethod
    async def exists(self, storage_ref: str) -> bool:
        """Return whether `storage_ref` currently refers to a stored file."""
