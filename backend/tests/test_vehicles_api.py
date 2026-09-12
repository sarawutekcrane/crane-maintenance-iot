from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_vehicles_returns_seeded_vehicles(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles")
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 3
    assert {v["vehicle_id"] for v in body["items"]} == {"VEH-1046", "VEH-1047", "VEH-1048"}


@pytest.mark.asyncio
async def test_list_vehicles_filters_by_status(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles", params={"status": "MAINTENANCE"})
    assert response.status_code == 200
    body = response.json()
    assert [v["vehicle_id"] for v in body["items"]] == ["VEH-1047"]


@pytest.mark.asyncio
async def test_known_vehicle_opens_by_vehicle_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1046")
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle"]["vehicle_id"] == "VEH-1046"
    assert body["vehicle"]["machine_no"] == "TC-12"
    assert body["model"]["model_id"] == "MODEL-0001"
    assert {c["component_role"] for c in body["components"]} == {"CARRIER_ENGINE", "PTO"}


@pytest.mark.asyncio
async def test_multi_engine_vehicle_exposes_both_engine_components(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1047")
    assert response.status_code == 200
    body = response.json()
    assert {c["component_role"] for c in body["components"]} == {
        "CARRIER_ENGINE",
        "CRANE_ENGINE",
        "PTO",
    }


@pytest.mark.asyncio
async def test_missing_source_value_stays_blank(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1048")
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle"]["serial_number"] is None


@pytest.mark.asyncio
async def test_missing_vehicle_returns_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-9999")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "VEHICLE_NOT_FOUND"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_machine_no_change_does_not_change_vehicle_identity(client: AsyncClient) -> None:
    before = await client.get("/api/v1/vehicles/VEH-1046")
    assert before.json()["vehicle"]["machine_no"] == "TC-12"

    patched = await client.patch("/api/v1/vehicles/VEH-1046", json={"machine_no": "TC-12-B"})
    assert patched.status_code == 200
    body = patched.json()
    assert body["vehicle_id"] == "VEH-1046"
    assert body["machine_no"] == "TC-12-B"
    # machine_no is stored/returned as text even though it looks numeric-ish.
    assert isinstance(body["machine_no"], str)

    after = await client.get("/api/v1/vehicles/VEH-1046")
    assert after.status_code == 200
    assert after.json()["vehicle"]["vehicle_id"] == "VEH-1046"
    assert after.json()["vehicle"]["machine_no"] == "TC-12-B"


@pytest.mark.asyncio
async def test_machine_no_update_on_missing_vehicle_returns_404(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/vehicles/VEH-9999", json={"machine_no": "X"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_status_change_creates_append_only_history(client: AsyncClient) -> None:
    history_before = await client.get("/api/v1/vehicles/VEH-1046/status-history")
    assert history_before.status_code == 200
    count_before = len(history_before.json())
    assert count_before == 1
    assert history_before.json()[0]["status"] == "WORKING"

    changed = await client.patch(
        "/api/v1/vehicles/VEH-1046/status",
        json={"status": "MAINTENANCE", "note": "เข้าซ่อมตามแผน"},
    )
    assert changed.status_code == 200
    body = changed.json()
    assert body["vehicle"]["operational_status"] == "MAINTENANCE"
    assert body["history_entry"]["status"] == "MAINTENANCE"
    assert body["history_entry"]["changed_by"] == "dev-user"

    history_after = await client.get("/api/v1/vehicles/VEH-1046/status-history")
    entries = history_after.json()
    assert len(entries) == count_before + 1
    # Append-only: the original entry must still be present, unmodified.
    original_entries = [e for e in entries if e["status"] == "WORKING"]
    assert len(original_entries) == 1
    assert original_entries[0]["note"] == "สถานะเริ่มต้นจากการนำเข้าข้อมูล"
    # Newest-first ordering.
    assert entries[0]["status"] == "MAINTENANCE"


@pytest.mark.asyncio
async def test_status_change_on_missing_vehicle_returns_404(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/v1/vehicles/VEH-9999/status", json={"status": "READY"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_vehicle_components_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1046/components")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert all(c["vehicle_id"] == "VEH-1046" for c in body)


@pytest.mark.asyncio
async def test_components_for_missing_vehicle_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-9999/components")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"
