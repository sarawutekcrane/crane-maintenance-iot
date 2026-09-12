from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_equipment_returns_seeded_items(client: AsyncClient) -> None:
    response = await client.get("/api/v1/equipment")
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 3
    assert {e["equipment_id"] for e in body["items"]} == {
        "EQP-0001",
        "EQP-0002",
        "EQP-0003",
    }


@pytest.mark.asyncio
async def test_list_equipment_filters_by_category(client: AsyncClient) -> None:
    response = await client.get("/api/v1/equipment", params={"category": "WELDING"})
    assert response.status_code == 200
    body = response.json()
    assert [e["equipment_id"] for e in body["items"]] == ["EQP-0003"]


@pytest.mark.asyncio
async def test_equipment_route_works(client: AsyncClient) -> None:
    response = await client.get("/api/v1/equipment/EQP-0001")
    assert response.status_code == 200
    body = response.json()
    assert body["equipment_id"] == "EQP-0001"
    assert body["category"] == "LATHE"


@pytest.mark.asyncio
async def test_equipment_is_not_present_in_vehicle_list(client: AsyncClient) -> None:
    vehicles = await client.get("/api/v1/vehicles")
    vehicle_ids = {v["vehicle_id"] for v in vehicles.json()["items"]}
    assert "EQP-0001" not in vehicle_ids


@pytest.mark.asyncio
async def test_missing_equipment_returns_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/equipment/EQP-9999")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "EQUIPMENT_NOT_FOUND"
    assert "request_id" in body["error"]
