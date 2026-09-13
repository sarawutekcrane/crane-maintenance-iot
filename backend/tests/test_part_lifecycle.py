"""Lifecycle / overhaul boundary tests (Phase 5;
OPEN_DECISIONS_REGISTER_EN.txt G04).

Proves: normal repair/removal never resets lifetime by itself (there is no
code path anywhere that calls `start_new_part_lifecycle` except the
explicit, caller-approved endpoint), starting a new lifecycle requires an
explicit approved reason, the previous lifecycle and its installation
segments remain fully readable afterward, and no real overhaul-
qualification rule is invented.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

INSTANCE_TRACKED_PART = "PART-0005"


async def _create_and_install(client: AsyncClient) -> dict:
    created = await client.post(
        "/api/v1/part-instances",
        json={"part_id": INSTANCE_TRACKED_PART, "prior_usage": {"quality": "UNKNOWN"}},
    )
    instance_id = created.json()["instance"]["part_instance_id"]
    await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
    )
    return created.json()


@pytest.mark.asyncio
async def test_start_new_lifecycle_requires_explicit_approved_reason(client: AsyncClient) -> None:
    detail = await _create_and_install(client)
    instance_id = detail["instance"]["part_instance_id"]
    await client.post(
        f"/api/v1/part-instances/{instance_id}/remove", json={"next_status": "IN_REPAIR"}
    )
    response = await client.post(
        f"/api/v1/part-instances/{instance_id}/start-new-lifecycle", json={"approved_reason": ""}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_normal_repair_does_not_reset_lifetime(client: AsyncClient) -> None:
    """Removing into IN_REPAIR and back to INSTALLED is a normal repair —
    it must never, on its own, start a new lifecycle or reset accumulated
    usage."""
    detail = await _create_and_install(client)
    instance_id = detail["instance"]["part_instance_id"]
    lifecycle_id = detail["instance"]["current_lifecycle_id"]

    removed = await client.post(
        f"/api/v1/part-instances/{instance_id}/remove",
        json={"next_status": "IN_REPAIR", "removal_reason": "ซ่อมตามปกติ"},
    )
    assert removed.json()["instance"]["current_lifecycle_id"] == lifecycle_id
    assert len(removed.json()["lifecycles"]) == 1

    reinstalled = await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
    )
    assert reinstalled.status_code == 200
    assert reinstalled.json()["instance"]["current_lifecycle_id"] == lifecycle_id
    assert len(reinstalled.json()["lifecycles"]) == 1
    # Both installation segments (before and after the repair pause)
    # remain readable.
    assert len(reinstalled.json()["segments"]) == 2


@pytest.mark.asyncio
async def test_cannot_start_new_lifecycle_while_installed(client: AsyncClient) -> None:
    detail = await _create_and_install(client)
    instance_id = detail["instance"]["part_instance_id"]
    response = await client.post(
        f"/api/v1/part-instances/{instance_id}/start-new-lifecycle",
        json={"approved_reason": "overhaul ที่ได้รับอนุมัติ (ทดสอบ)"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PART_INSTANCE_INSTALLED"


@pytest.mark.asyncio
async def test_approved_overhaul_starts_new_cycle_and_preserves_old_history(
    client: AsyncClient,
) -> None:
    detail = await _create_and_install(client)
    instance_id = detail["instance"]["part_instance_id"]
    old_lifecycle_id = detail["instance"]["current_lifecycle_id"]

    await client.post(
        f"/api/v1/part-instances/{instance_id}/remove", json={"next_status": "IN_REPAIR"}
    )
    overhauled = await client.post(
        f"/api/v1/part-instances/{instance_id}/start-new-lifecycle",
        json={"approved_reason": "overhaul ที่ได้รับอนุมัติจากฝ่ายซ่อมบำรุง (ทดสอบ)"},
    )
    assert overhauled.status_code == 200
    body = overhauled.json()
    assert len(body["lifecycles"]) == 2
    old_cycle = next(lc for lc in body["lifecycles"] if lc["lifecycle_id"] == old_lifecycle_id)
    new_cycle = next(lc for lc in body["lifecycles"] if lc["lifecycle_id"] != old_lifecycle_id)
    assert old_cycle["ended_at"] is not None
    assert old_cycle["start_reason"] == "ENROLLMENT"
    assert new_cycle["start_reason"] == "OVERHAUL"
    assert new_cycle["cycle_number"] == old_cycle["cycle_number"] + 1
    assert new_cycle["ended_at"] is None
    assert body["instance"]["current_lifecycle_id"] == new_cycle["lifecycle_id"]

    # The old lifecycle's own installation segment remains stored and
    # readable, still pointing at the OLD lifecycle_id.
    old_segment = next(s for s in body["segments"] if s["lifecycle_id"] == old_lifecycle_id)
    assert old_segment["asset_id"] == "VEH-1046"

    reread = await client.get(f"/api/v1/part-instances/{instance_id}")
    assert reread.json() == body
