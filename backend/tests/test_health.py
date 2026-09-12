from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_env"] == "development"


@pytest.mark.asyncio
async def test_readiness_mock_mode_is_ready(client: AsyncClient) -> None:
    response = await client.get("/api/v1/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["repository_mode"] == "mock"
    assert body["checks"][0]["ready"] is True


@pytest.mark.asyncio
async def test_response_has_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert "x-request-id" in response.headers
