from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_models_returns_seeded_models(client: AsyncClient) -> None:
    response = await client.get("/api/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 3
    assert {m["model_id"] for m in body["items"]} == {"MODEL-0001", "MODEL-0002", "MODEL-0003"}


@pytest.mark.asyncio
async def test_list_models_supports_free_text_search(client: AsyncClient) -> None:
    response = await client.get("/api/v1/models", params={"q": "XCT80"})
    assert response.status_code == 200
    body = response.json()
    assert [m["model_id"] for m in body["items"]] == ["MODEL-0002"]


@pytest.mark.asyncio
async def test_dual_engine_model_declares_two_engine_roles(client: AsyncClient) -> None:
    response = await client.get("/api/v1/models/MODEL-0002")
    assert response.status_code == 200
    body = response.json()
    assert set(body["component_roles"]) == {"CARRIER_ENGINE", "CRANE_ENGINE", "PTO"}


@pytest.mark.asyncio
async def test_single_engine_model_does_not_fabricate_a_crane_engine(client: AsyncClient) -> None:
    response = await client.get("/api/v1/models/MODEL-0001")
    assert response.status_code == 200
    body = response.json()
    assert set(body["component_roles"]) == {"CARRIER_ENGINE", "PTO"}


@pytest.mark.asyncio
async def test_missing_model_returns_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/models/MODEL-9999")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "MODEL_NOT_FOUND"
    assert "request_id" in body["error"]
