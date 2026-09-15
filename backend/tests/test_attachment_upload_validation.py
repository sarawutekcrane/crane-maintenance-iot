"""CORRECTION (post-Phase-3 verification): the attachment upload endpoint
must not accept completely unrestricted uploads, but the validation policy
itself stays configurable and does not freeze a production policy —
OPEN_DECISIONS_REGISTER_EN.txt M07 remains unresolved. These tests use a
local helper (`_client_with_env`) instead of the shared `client` fixture
because they need to override `ATTACHMENT_MAX_SIZE_BYTES`/
`ATTACHMENT_ALLOWED_CONTENT_TYPES` *before* the app/settings are
constructed, which the module-level `client` fixture does not parameterize.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

# REV06.2: INSPECTION_EVIDENCE now requires a real, existing asset source
# (see AttachmentService.authorize_source) — VEH-1046 is seeded mock data
# (see other test files' use of the same vehicle_id).
_INSPECTION_SOURCE = {"source_type": "INSPECTION_VEHICLE", "source_id": "VEH-1046"}


@asynccontextmanager
async def _client_with_env(**env_overrides: str) -> AsyncIterator[AsyncClient]:
    from app.config import get_settings
    from app.dependencies import reset_dependency_cache
    from app.main import create_app

    previous = {key: os.environ.get(key) for key in env_overrides}
    os.environ.update(env_overrides)
    get_settings.cache_clear()
    reset_dependency_cache()
    try:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        reset_dependency_cache()


@pytest.mark.asyncio
async def test_attachment_upload_rejects_disallowed_content_type() -> None:
    async with _client_with_env() as client:
        files = {"file": ("evidence.exe", b"not-an-image", "application/x-msdownload")}
        response = await client.post(
            "/api/v1/attachments", data={"purpose": "INSPECTION_EVIDENCE", **_INSPECTION_SOURCE}, files=files
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ATTACHMENT_TYPE_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_attachment_upload_rejects_file_larger_than_configured_limit() -> None:
    async with _client_with_env(ATTACHMENT_MAX_SIZE_BYTES="10") as client:
        files = {"file": ("evidence.jpg", b"x" * 100, "image/jpeg")}
        response = await client.post(
            "/api/v1/attachments", data={"purpose": "INSPECTION_EVIDENCE", **_INSPECTION_SOURCE}, files=files
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "ATTACHMENT_TOO_LARGE"
        assert body["error"]["details"]["max_size_bytes"] == 10


@pytest.mark.asyncio
async def test_attachment_upload_limit_is_configurable_not_hardcoded() -> None:
    """Proves the boundary is a configurable setting, not a hardcoded
    production policy: the same 100-byte file is rejected under a 10-byte
    limit and accepted under a 1000-byte limit."""
    async with _client_with_env(
        ATTACHMENT_MAX_SIZE_BYTES="1000", ATTACHMENT_ALLOWED_CONTENT_TYPES="image/jpeg"
    ) as client:
        files = {"file": ("evidence.jpg", b"x" * 100, "image/jpeg")}
        response = await client.post(
            "/api/v1/attachments", data={"purpose": "INSPECTION_EVIDENCE", **_INSPECTION_SOURCE}, files=files
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_attachment_upload_accepts_default_dev_allowlisted_image_types() -> None:
    async with _client_with_env() as client:
        for content_type, filename in (
            ("image/jpeg", "a.jpg"),
            ("image/png", "b.png"),
            ("image/webp", "c.webp"),
            ("image/gif", "d.gif"),
        ):
            files = {"file": (filename, b"fake-image-bytes", content_type)}
            response = await client.post(
                "/api/v1/attachments", data={"purpose": "INSPECTION_EVIDENCE", **_INSPECTION_SOURCE}, files=files
            )
            assert response.status_code == 200, content_type


@pytest.mark.asyncio
async def test_attachment_upload_normalizes_path_traversal_filename() -> None:
    async with _client_with_env() as client:
        files = {"file": ("../../etc/passwd.jpg", b"fake-jpeg-bytes", "image/jpeg")}
        response = await client.post(
            "/api/v1/attachments", data={"purpose": "INSPECTION_EVIDENCE", **_INSPECTION_SOURCE}, files=files
        )
        assert response.status_code == 200
        body = response.json()
        assert "/" not in body["filename"]
        assert "\\" not in body["filename"]
        assert ".." not in body["filename"]
        assert body["filename"].endswith(".jpg")

        # The file must actually have been written safely under the
        # storage root and be retrievable byte-for-byte.
        download = await client.get(body["url"])
        assert download.status_code == 200
        assert download.content == b"fake-jpeg-bytes"


@pytest.mark.asyncio
async def test_attachment_upload_replaces_mismatched_extension_with_safe_one() -> None:
    """A client-declared `.exe` extension on an (allowlist-validated)
    `image/jpeg` upload must never be trusted for the stored filename."""
    async with _client_with_env() as client:
        files = {"file": ("evidence.exe", b"fake-jpeg-bytes", "image/jpeg")}
        response = await client.post(
            "/api/v1/attachments", data={"purpose": "INSPECTION_EVIDENCE", **_INSPECTION_SOURCE}, files=files
        )
        assert response.status_code == 200
        filename = response.json()["filename"]
        assert filename.endswith(".jpg")
        assert not filename.endswith(".exe")
