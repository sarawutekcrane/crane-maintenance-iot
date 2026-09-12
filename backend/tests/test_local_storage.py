from __future__ import annotations

import pytest

from app.storage.local import LocalFileStorageProvider


@pytest.mark.asyncio
async def test_save_read_delete_roundtrip(temp_upload_dir: str) -> None:
    provider = LocalFileStorageProvider(temp_upload_dir)

    stored = await provider.save("photo.jpg", "image/jpeg", b"fake-bytes")
    assert stored.filename == "photo.jpg"
    assert stored.content_type == "image/jpeg"
    assert stored.size_bytes == len(b"fake-bytes")
    assert await provider.exists(stored.storage_ref) is True

    data = await provider.read(stored.storage_ref)
    assert data == b"fake-bytes"

    await provider.delete(stored.storage_ref)
    assert await provider.exists(stored.storage_ref) is False


@pytest.mark.asyncio
async def test_rejects_path_traversal(temp_upload_dir: str) -> None:
    provider = LocalFileStorageProvider(temp_upload_dir)
    with pytest.raises(ValueError):
        await provider.read("../../etc/passwd")
