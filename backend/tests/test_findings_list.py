"""Core Demo Fixes — VEHICLE LIST / CORE STATUS SUMMARY: "unresolved
inspection finding indicator" needs a way to list findings by asset,
which Phase 3 never exposed (only per-inspection). GET /findings backs it.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_findings_filters_by_asset_and_status(client: AsyncClient) -> None:
    checklist = await client.get("/api/v1/checklists/active", params={"asset_type": "VEHICLE"})
    items = [{"item_id": i["item_id"], "result": "PASS"} for i in checklist.json()["items"]]
    items[0]["result"] = "FAIL"
    await client.post(
        "/api/v1/inspections", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items}
    )

    all_open = await client.get("/api/v1/findings", params={"status": "OPEN"})
    assert all_open.status_code == 200
    assert any(f["asset_id"] == "VEH-1046" for f in all_open.json())

    scoped = await client.get(
        "/api/v1/findings", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    assert scoped.status_code == 200
    assert len(scoped.json()) >= 1
    assert all(f["asset_id"] == "VEH-1046" for f in scoped.json())

    other_vehicle = await client.get(
        "/api/v1/findings", params={"asset_type": "VEHICLE", "asset_id": "VEH-1047"}
    )
    assert other_vehicle.status_code == 200
    assert other_vehicle.json() == []
