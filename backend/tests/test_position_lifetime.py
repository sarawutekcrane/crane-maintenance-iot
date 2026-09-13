"""POSITION_LIFETIME tests (Phase 5; OPEN_DECISIONS_REGISTER_EN.txt G03).

Proves position lifetime works without any serialized PartInstance, a
POSITION_LIFETIME part is rejected for a PartInstance and vice versa, an
example position_code is accepted structurally without being treated as
company master data, and invalid references are controlled 404/422s.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

POSITION_LIFETIME_PART = "PART-0004"
INSTANCE_TRACKED_PART = "PART-0005"


@pytest.mark.asyncio
async def test_position_lifetime_requires_no_part_instance(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/position-lifetime",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "position_code": "BOOM-CYL-DEV-EXAMPLE",
            "part_id": POSITION_LIFETIME_PART,
            "prior_usage": {"quality": "UNKNOWN"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["position_lifetime_id"].startswith("POSLT-")
    # No part_instance_id concept exists on this record at all.
    assert "part_instance_id" not in body

    reread = await client.get(f"/api/v1/position-lifetime/{body['position_lifetime_id']}")
    assert reread.status_code == 200
    assert reread.json() == body


@pytest.mark.asyncio
async def test_instance_tracked_part_rejected_for_position_lifetime(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/position-lifetime",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "position_code": "DEV-EXAMPLE-POS",
            "part_id": INSTANCE_TRACKED_PART,
            "prior_usage": {"quality": "UNKNOWN"},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PART_NOT_POSITION_LIFETIME"


@pytest.mark.asyncio
async def test_position_lifetime_part_id_is_optional(client: AsyncClient) -> None:
    """A position-lifetime record does not require naming a part at all —
    the position/rule concept is independent of a specific catalog part."""
    response = await client.post(
        "/api/v1/position-lifetime",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "position_code": "DEV-EXAMPLE-POS-2",
            "prior_usage": {"quality": "UNKNOWN"},
        },
    )
    assert response.status_code == 200
    assert response.json()["part_id"] is None


@pytest.mark.asyncio
async def test_position_lifetime_rejects_invalid_asset(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/position-lifetime",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-9999",
            "position_code": "DEV-EXAMPLE-POS-3",
            "prior_usage": {"quality": "UNKNOWN"},
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_position_lifetime_for_asset(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/position-lifetime",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1048",
            "position_code": "DEV-EXAMPLE-A",
            "prior_usage": {"quality": "UNKNOWN"},
        },
    )
    await client.post(
        "/api/v1/position-lifetime",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1048",
            "position_code": "DEV-EXAMPLE-B",
            "prior_usage": {"quality": "UNKNOWN"},
        },
    )
    response = await client.get(
        "/api/v1/position-lifetime", params={"asset_type": "VEHICLE", "asset_id": "VEH-1048"}
    )
    assert response.status_code == 200
    codes = {r["position_code"] for r in response.json()}
    assert codes == {"DEV-EXAMPLE-A", "DEV-EXAMPLE-B"}


@pytest.mark.asyncio
async def test_get_unknown_position_lifetime_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/position-lifetime/POSLT-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "POSITION_LIFETIME_NOT_FOUND"
