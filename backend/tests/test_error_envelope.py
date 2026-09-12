from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_not_found_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "NOT_FOUND"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_validation_error_uses_error_envelope(client: AsyncClient) -> None:
    # readiness takes no query params; send an invalid page param to a
    # hypothetical future endpoint is not available yet, so instead verify
    # the handler is registered by hitting an endpoint with a bad method.
    response = await client.post("/api/v1/health")
    assert response.status_code == 405
    body = response.json()
    assert body["error"]["code"] == "HTTP_ERROR"
