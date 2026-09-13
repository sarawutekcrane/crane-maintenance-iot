"""INSTANCE_TRACKED part-instance tests (Phase 5).

Proves: on-demand enrollment (no pre-registration required), stable
instance identity, install/remove/transfer history is append-oriented and
survives across vehicles, a removed/IN_REPAIR instance has no ACTIVE
installation segment (so it cannot accumulate a host's usage), duplicate
active installation is rejected, and every invalid reference is a
controlled 404/422 — never a silent guess.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

INSTANCE_TRACKED_PART = "PART-0005"  # seeded HYD-PUMP-INST


async def _create_instance(client: AsyncClient, **overrides) -> dict:
    payload = {
        "part_id": INSTANCE_TRACKED_PART,
        "prior_usage": {"quality": "UNKNOWN"},
    }
    payload.update(overrides)
    response = await client.post("/api/v1/part-instances", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_instance_can_only_be_created_for_instance_tracked_part(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/part-instances",
        json={"part_id": "PART-0002", "prior_usage": {"quality": "UNKNOWN"}},  # CONSUMABLE
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PART_NOT_INSTANCE_TRACKED"


@pytest.mark.asyncio
async def test_create_instance_on_demand_with_stable_identity(client: AsyncClient) -> None:
    detail = await _create_instance(client, serial_number="SN-0001")
    assert detail["instance"]["part_instance_id"].startswith("PINST-")
    assert detail["instance"]["status"] == "READY_FOR_INSTALL"
    assert len(detail["lifecycles"]) == 1
    assert detail["lifecycles"][0]["cycle_number"] == 1
    assert detail["lifecycles"][0]["start_reason"] == "ENROLLMENT"
    assert detail["segments"] == []

    reread = await client.get(f"/api/v1/part-instances/{detail['instance']['part_instance_id']}")
    assert reread.status_code == 200
    assert reread.json() == detail


@pytest.mark.asyncio
async def test_get_unknown_instance_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/part-instances/PINST-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PART_INSTANCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_install_rejects_invalid_asset(client: AsyncClient) -> None:
    detail = await _create_instance(client)
    instance_id = detail["instance"]["part_instance_id"]
    response = await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-9999"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_install_then_duplicate_active_installation_is_rejected(client: AsyncClient) -> None:
    detail = await _create_instance(client)
    instance_id = detail["instance"]["part_instance_id"]

    installed = await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "position_code": "MAIN-PUMP"},
    )
    assert installed.status_code == 200
    assert installed.json()["instance"]["status"] == "INSTALLED"
    assert len(installed.json()["segments"]) == 1
    assert installed.json()["segments"][0]["status"] == "ACTIVE"
    assert installed.json()["segments"][0]["asset_id"] == "VEH-1046"

    duplicate = await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1047"},
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "PART_INSTANCE_ALREADY_INSTALLED"


@pytest.mark.asyncio
async def test_remove_without_install_is_rejected(client: AsyncClient) -> None:
    detail = await _create_instance(client)
    instance_id = detail["instance"]["part_instance_id"]
    response = await client.post(
        f"/api/v1/part-instances/{instance_id}/remove",
        json={"next_status": "IN_REPAIR"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PART_INSTANCE_NOT_INSTALLED"


@pytest.mark.asyncio
async def test_remove_into_in_repair_closes_active_segment_and_stops_host_accumulation(
    client: AsyncClient,
) -> None:
    """Once removed into IN_REPAIR, the instance has NO active installation
    segment — which is exactly what stops it from accumulating the host
    vehicle's ENGINE_HOUR/PTO_HOUR/ODOMETER (baseline "IN_REPAIR USAGE
    RULE")."""
    detail = await _create_instance(client)
    instance_id = detail["instance"]["part_instance_id"]
    await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
    )

    removed = await client.post(
        f"/api/v1/part-instances/{instance_id}/remove",
        json={"next_status": "IN_REPAIR", "removal_reason": "ตรวจสภาพ"},
    )
    assert removed.status_code == 200
    body = removed.json()
    assert body["instance"]["status"] == "IN_REPAIR"
    assert len(body["segments"]) == 1
    closed_segment = body["segments"][0]
    assert closed_segment["status"] == "CLOSED"
    assert closed_segment["removed_at"] is not None
    assert closed_segment["removal_reason"] == "ตรวจสภาพ"
    # No ACTIVE segment remains — nothing here can accumulate host usage.
    assert all(s["status"] != "ACTIVE" for s in body["segments"])


@pytest.mark.asyncio
async def test_remove_rejects_invalid_next_status(client: AsyncClient) -> None:
    detail = await _create_instance(client)
    instance_id = detail["instance"]["part_instance_id"]
    await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
    )
    response = await client.post(
        f"/api/v1/part-instances/{instance_id}/remove",
        json={"next_status": "INSTALLED"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_transfer_between_vehicles_preserves_previous_segment_and_does_not_reset_usage(
    client: AsyncClient,
) -> None:
    """Cylinder A: 200/2 -> 200/1 -> ... -> transfer example from baseline
    section 13 — a transfer closes the old segment (still readable) and
    opens a new one on the target vehicle, in the SAME lifecycle."""
    detail = await _create_instance(client, prior_usage={"quality": "KNOWN", "value": 120.0})
    instance_id = detail["instance"]["part_instance_id"]
    lifecycle_id = detail["instance"]["current_lifecycle_id"]

    await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "position_code": "200/2"},
    )

    transferred = await client.post(
        f"/api/v1/part-instances/{instance_id}/transfer",
        json={
            "target_asset_type": "VEHICLE",
            "target_asset_id": "VEH-1047",
            "position_code": "200/1",
        },
    )
    assert transferred.status_code == 200
    body = transferred.json()
    assert body["instance"]["status"] == "INSTALLED"
    # Previous installation segment remains readable, closed, unchanged.
    assert len(body["segments"]) == 2
    old_segment = next(s for s in body["segments"] if s["asset_id"] == "VEH-1046")
    new_segment = next(s for s in body["segments"] if s["asset_id"] == "VEH-1047")
    assert old_segment["status"] == "CLOSED"
    assert new_segment["status"] == "ACTIVE"
    assert new_segment["position_code"] == "200/1"
    # Same lifecycle throughout — a transfer never starts a new lifecycle
    # or resets accumulated usage (prior_usage untouched).
    assert old_segment["lifecycle_id"] == lifecycle_id
    assert new_segment["lifecycle_id"] == lifecycle_id
    assert body["instance"]["prior_usage"] == {"quality": "KNOWN", "value": 120.0, "note": None}


@pytest.mark.asyncio
async def test_transfer_requires_currently_installed(client: AsyncClient) -> None:
    detail = await _create_instance(client)
    instance_id = detail["instance"]["part_instance_id"]
    response = await client.post(
        f"/api/v1/part-instances/{instance_id}/transfer",
        json={"target_asset_type": "VEHICLE", "target_asset_id": "VEH-1046"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PART_INSTANCE_NOT_INSTALLED"


@pytest.mark.asyncio
async def test_scrapped_instance_cannot_be_installed(client: AsyncClient) -> None:
    detail = await _create_instance(client)
    instance_id = detail["instance"]["part_instance_id"]
    await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
    )
    await client.post(
        f"/api/v1/part-instances/{instance_id}/remove",
        json={"next_status": "SCRAPPED"},
    )
    response = await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1047"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PART_INSTANCE_SCRAPPED"
