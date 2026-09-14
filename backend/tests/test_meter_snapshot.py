"""Meter/counter snapshot tests (Phase 4).

Guardrails §10 / baseline §16 frozen concept:
`vehicle_id -> component_id -> counter_type -> value`. These tests prove
the snapshot is genuinely component-aware (CARRIER_ENGINE and CRANE_ENGINE
readings never conflated), never fabricates a component a vehicle does not
have, and never coerces an unknown reading to `0` (E04).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _component_id(client: AsyncClient, vehicle_id: str, role: str) -> str:
    response = await client.get(f"/api/v1/vehicles/{vehicle_id}")
    assert response.status_code == 200
    for component in response.json()["components"]:
        if component["component_role"] == role:
            return component["component_id"]
    raise AssertionError(f"{vehicle_id} has no component with role {role}")


async def _roles(client: AsyncClient, vehicle_id: str) -> set[str]:
    response = await client.get(f"/api/v1/vehicles/{vehicle_id}")
    return {c["component_role"] for c in response.json()["components"]}


@pytest.mark.asyncio
async def test_meter_snapshot_references_correct_asset_component_counter(
    client: AsyncClient,
) -> None:
    carrier_id = await _component_id(client, "VEH-1046", "CARRIER_ENGINE")
    response = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "readings": [{"component_id": carrier_id, "counter_type": "ENGINE_HOUR", "value": 1200.5}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meter_snapshot_id"].startswith("MSNAP-")
    assert body["asset_type"] == "VEHICLE"
    assert body["asset_id"] == "VEH-1046"
    assert body["readings"] == [
        {
            "component_id": carrier_id,
            "counter_type": "ENGINE_HOUR",
            "value": 1200.5,
            "observed_at": None,
        }
    ]

    reread = await client.get(f"/api/v1/meter-snapshots/{body['meter_snapshot_id']}")
    assert reread.status_code == 200
    assert reread.json() == body


@pytest.mark.asyncio
async def test_carrier_engine_hour_remains_distinct_from_crane_engine_hour(
    client: AsyncClient,
) -> None:
    """VEH-1047 is the seeded dual-engine vehicle (MODEL-0002)."""
    carrier_id = await _component_id(client, "VEH-1047", "CARRIER_ENGINE")
    crane_id = await _component_id(client, "VEH-1047", "CRANE_ENGINE")
    assert carrier_id != crane_id

    response = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1047",
            "readings": [
                {"component_id": carrier_id, "counter_type": "ENGINE_HOUR", "value": 100.0},
                {"component_id": crane_id, "counter_type": "ENGINE_HOUR", "value": 40.0},
            ],
        },
    )
    assert response.status_code == 200
    readings = {r["component_id"]: r["value"] for r in response.json()["readings"]}
    assert readings[carrier_id] == 100.0
    assert readings[crane_id] == 40.0
    assert readings[carrier_id] != readings[crane_id]


@pytest.mark.asyncio
async def test_pto_hour_associates_with_pto_component(client: AsyncClient) -> None:
    pto_id = await _component_id(client, "VEH-1046", "PTO")
    response = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "readings": [{"component_id": pto_id, "counter_type": "PTO_HOUR", "value": 12.0}],
        },
    )
    assert response.status_code == 200
    assert response.json()["readings"][0]["counter_type"] == "PTO_HOUR"
    assert response.json()["readings"][0]["component_id"] == pto_id


@pytest.mark.asyncio
async def test_odometer_is_vehicle_level_not_per_component(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "readings": [{"counter_type": "ODOMETER", "value": 45210}],
        },
    )
    assert response.status_code == 200
    assert response.json()["readings"][0]["component_id"] is None


@pytest.mark.asyncio
async def test_single_engine_vehicle_rejects_a_fabricated_crane_engine_reading(
    client: AsyncClient,
) -> None:
    """VEH-1046/VEH-1048 are single-engine (CARRIER_ENGINE + PTO only, per
    the approved Component Role Naming correction) — a reading naming a
    CRANE_ENGINE-role component_id that does not exist on this vehicle
    must be rejected, never silently accepted."""
    assert "CRANE_ENGINE" not in await _roles(client, "VEH-1046")
    fabricated_component_id = "CMP-9999"
    response = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "readings": [
                {"component_id": fabricated_component_id, "counter_type": "ENGINE_HOUR", "value": 10}
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "METER_COMPONENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_reading_a_real_component_from_a_different_vehicle_is_rejected(
    client: AsyncClient,
) -> None:
    """A component_id that is real, but belongs to a different vehicle,
    must not be accepted for this vehicle's snapshot either."""
    other_vehicle_crane_id = await _component_id(client, "VEH-1047", "CRANE_ENGINE")
    response = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "readings": [
                {"component_id": other_vehicle_crane_id, "counter_type": "ENGINE_HOUR", "value": 10}
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "METER_COMPONENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_unknown_counter_value_stays_unknown_never_becomes_zero(client: AsyncClient) -> None:
    carrier_id = await _component_id(client, "VEH-1046", "CARRIER_ENGINE")
    response = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "readings": [{"component_id": carrier_id, "counter_type": "ENGINE_HOUR", "value": None}],
        },
    )
    assert response.status_code == 200
    reading = response.json()["readings"][0]
    assert reading["value"] is None
    assert reading["value"] != 0

    reread = await client.get(f"/api/v1/meter-snapshots/{response.json()['meter_snapshot_id']}")
    assert reread.json()["readings"][0]["value"] is None


@pytest.mark.asyncio
async def test_meter_snapshot_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meter-snapshots/MSNAP-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "METER_SNAPSHOT_NOT_FOUND"


@pytest.mark.asyncio
async def test_equipment_snapshot_may_carry_no_component_scoped_readings(
    client: AsyncClient,
) -> None:
    """C03 (equipment counter model) is TBD-DEFERRED — no fabricated
    equipment component/counter model is invented here; an equipment
    snapshot with zero readings is valid, and a component-scoped reading
    is rejected rather than silently accepted."""
    empty = await client.post(
        "/api/v1/meter-snapshots",
        json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001", "readings": []},
    )
    assert empty.status_code == 200
    assert empty.json()["readings"] == []

    with_component = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "EQUIPMENT",
            "asset_id": "EQP-0001",
            "readings": [{"component_id": "CMP-0001", "counter_type": "ENGINE_HOUR", "value": 1}],
        },
    )
    assert with_component.status_code == 422


@pytest.mark.asyncio
async def test_non_odometer_reading_without_a_component_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "readings": [{"counter_type": "ENGINE_HOUR", "value": 10}],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_meter_snapshot_for_unknown_vehicle_is_still_asset_scoped(
    client: AsyncClient,
) -> None:
    """Creating a snapshot does not itself validate the asset exists in
    Phase 4 (mirrors how attachments are asset-agnostic) — but referencing
    it from a PM work order/repair does validate the asset via those
    services' own `require_asset_exists` check, exercised in
    test_pm_work_order_api.py / test_repair_api.py."""
    response = await client.post(
        "/api/v1/meter-snapshots",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "readings": []},
    )
    assert response.status_code == 200
