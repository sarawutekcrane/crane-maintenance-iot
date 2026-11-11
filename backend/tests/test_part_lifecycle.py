"""Lifecycle / overhaul boundary tests (Phase 5;
OPEN_DECISIONS_REGISTER_EN.txt G04).

Proves: normal repair/removal never resets lifetime by itself (there is no
code path anywhere that calls `start_new_part_lifecycle` except the
explicit, caller-approved endpoint), starting a new lifecycle requires an
explicit approved reason, the previous lifecycle and its installation
segments remain fully readable afterward, and no real overhaul-
qualification rule is invented.

R6 (deliberate migration; Owner decisions A-2(i) / A-2(ii), FINAL plan §7.2b):
a part in IN_REPAIR is never installed directly — it must first return from
repair; a repaired-part cycle opens ONLY at a successful install that consumes
a pending authorized approval; the legacy `start-new-lifecycle` route never
creates a lifecycle (always 409 NEW_CYCLE_OPENS_AT_INSTALL). Vehicle writes use
the mock's TEST-scoped VEH-1048.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

INSTANCE_TRACKED_PART = "PART-0005"


def _rid() -> dict:
    return {"X-Request-Id": str(uuid.uuid4())}


async def _repair_id(client: AsyncClient) -> str:
    created = await client.post("/api/v1/repairs", json={"asset_type": "VEHICLE", "asset_id": "VEH-1048",
                                                         "source_type": "MANUAL", "symptom": "ทดสอบ"})
    assert created.status_code == 200, created.text
    return created.json()["repair"]["repair_id"]


async def _create_and_install(client: AsyncClient) -> dict:
    created = await client.post(
        "/api/v1/part-instances",
        json={"part_id": INSTANCE_TRACKED_PART, "prior_usage": {"quality": "UNKNOWN"}},
    )
    instance_id = created.json()["instance"]["part_instance_id"]
    await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1048"},
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

    direct = await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1048"},
    )
    assert direct.status_code == 409  # A-2(i): no direct install from IN_REPAIR
    assert direct.json()["error"]["code"] == "PART_INSTANCE_NOT_READY_FOR_INSTALL"
    returned = await client.post(f"/api/v1/part-instances/{instance_id}/return-from-repair",
                                 json={"outcome": "ซ่อมตามปกติ"}, headers=_rid())
    assert returned.status_code == 200, returned.text
    reinstalled = await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1048"},
    )
    assert reinstalled.status_code == 200
    assert reinstalled.json()["instance"]["current_lifecycle_id"] == lifecycle_id
    assert len(reinstalled.json()["lifecycles"]) == 1
    # Both installation segments (before and after the repair pause)
    # remain readable.
    assert len(reinstalled.json()["segments"]) == 2


@pytest.mark.asyncio
async def test_legacy_start_new_lifecycle_never_creates_a_lifecycle(client: AsyncClient) -> None:
    detail = await _create_and_install(client)
    instance_id = detail["instance"]["part_instance_id"]
    before = (await client.get(f"/api/v1/part-instances/{instance_id}")).json()
    response = await client.post(
        f"/api/v1/part-instances/{instance_id}/start-new-lifecycle",
        json={"approved_reason": "overhaul ที่ได้รับอนุมัติ (ทดสอบ)"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NEW_CYCLE_OPENS_AT_INSTALL"
    assert response.json()["error"]["details"]["approval_state"] == "NONE"
    assert (await client.get(f"/api/v1/part-instances/{instance_id}")).json() == before


@pytest.mark.asyncio
async def test_approved_repair_opens_new_cycle_at_install_and_preserves_old_history(
    client: AsyncClient,
) -> None:
    detail = await _create_and_install(client)
    instance_id = detail["instance"]["part_instance_id"]
    old_lifecycle_id = detail["instance"]["current_lifecycle_id"]
    repair_id = await _repair_id(client)

    await client.post(
        f"/api/v1/part-instances/{instance_id}/remove", json={"next_status": "IN_REPAIR"}
    )
    returned = await client.post(
        f"/api/v1/part-instances/{instance_id}/return-from-repair",
        json={"repair_reference": repair_id, "new_cycle_approved": True,
              "approval_reason_code": "TEST-OVERHAUL-APPROVED"}, headers=_rid())
    assert returned.status_code == 200, returned.text
    # The approval alone opens nothing: the lifecycle is still the old one.
    assert len(returned.json()["lifecycles"]) == 1
    legacy = await client.post(f"/api/v1/part-instances/{instance_id}/start-new-lifecycle",
                               json={"approved_reason": "อนุมัติแล้ว"})
    assert legacy.status_code == 409
    assert legacy.json()["error"]["details"]["approval_state"] == "PENDING"

    overhauled = await client.post(
        f"/api/v1/part-instances/{instance_id}/install", json={"asset_type": "VEHICLE", "asset_id": "VEH-1048"})
    assert overhauled.status_code == 200, overhauled.text
    body = overhauled.json()
    assert len(body["lifecycles"]) == 2
    old_cycle = next(lc for lc in body["lifecycles"] if lc["lifecycle_id"] == old_lifecycle_id)
    new_cycle = next(lc for lc in body["lifecycles"] if lc["lifecycle_id"] != old_lifecycle_id)
    assert old_cycle["ended_at"] is not None
    assert old_cycle["start_reason"] == "ENROLLMENT"
    assert new_cycle["start_reason"] == "OVERHAUL"
    assert new_cycle["start_trigger_event_id"] == returned.json()["status_events"][-1]["event_id"]
    assert new_cycle["cycle_number"] == old_cycle["cycle_number"] + 1
    assert new_cycle["ended_at"] is None
    assert body["instance"]["current_lifecycle_id"] == new_cycle["lifecycle_id"]

    # The old lifecycle's own installation segment remains stored and
    # readable, still pointing at the OLD lifecycle_id.
    old_segment = next(s for s in body["segments"] if s["lifecycle_id"] == old_lifecycle_id)
    assert old_segment["asset_id"] == "VEH-1048"

    reread = await client.get(f"/api/v1/part-instances/{instance_id}")
    assert reread.json() == body
