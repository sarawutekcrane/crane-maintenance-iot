"""Core Demo Fixes Delta REV06 section 18 — PM My Work.

The independent REV05 audit verified Repair My Work (`GET /repairs/my-work`)
exists but its PM equivalent does not. REV06 adds `GET
/pm/work-orders/my-work`, derived exactly the same way (active assignment
to the current actor via `primary_technician`/`collaborators`, kept in
sync by `assign_pm_work_order`/`PmAssignmentHistoryEntry` — no new table,
no new status, no new source field).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


async def _open_work_order(client: AsyncClient, vehicle_id: str = "VEH-1046") -> str:
    plans = await client.get(
        "/api/v1/pm/plans/status",
        params={"asset_type": "VEHICLE", "asset_id": vehicle_id},
        headers=_as("MAINTENANCE"),
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "pm_plan_id": plan_id},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
    return response.json()["work_order"]["pm_work_order_id"]


# ---------------------------------------------------------------------------
# 38 — assigned PM appears in My Work.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assigned_primary_technician_sees_the_work_order_in_my_work(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_work_order(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-pm-1", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    my_work = await client.get("/api/v1/pm/work-orders/my-work", headers=_as("TECHNICIAN", "user-pm-1"))
    assert my_work.status_code == 200
    ids = [w["pm_work_order_id"] for w in my_work.json()["items"]]
    assert work_order_id in ids


@pytest.mark.asyncio
async def test_assigned_collaborator_also_sees_the_work_order_in_my_work(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_work_order(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-pm-1", "collaborators": ["user-pm-2"]},
        headers=_as("MAINTENANCE"),
    )

    my_work = await client.get("/api/v1/pm/work-orders/my-work", headers=_as("TECHNICIAN", "user-pm-2"))
    ids = [w["pm_work_order_id"] for w in my_work.json()["items"]]
    assert work_order_id in ids


# ---------------------------------------------------------------------------
# 39 — unrelated PM does not appear.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_technician_does_not_see_a_work_order_assigned_to_someone_else(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_work_order(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-pm-1", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    my_work = await client.get(
        "/api/v1/pm/work-orders/my-work", headers=_as("TECHNICIAN", "user-unrelated")
    )
    ids = [w["pm_work_order_id"] for w in my_work.json()["items"]]
    assert work_order_id not in ids


@pytest.mark.asyncio
async def test_unassigned_work_order_appears_in_nobodys_my_work(client: AsyncClient) -> None:
    work_order_id = await _open_work_order(client)

    my_work = await client.get(
        "/api/v1/pm/work-orders/my-work", headers=_as("TECHNICIAN", "user-anyone")
    )
    ids = [w["pm_work_order_id"] for w in my_work.json()["items"]]
    assert work_order_id not in ids


# ---------------------------------------------------------------------------
# 40 — closed/inactive assignment behavior matches current approved
# semantics (mirrors Repair My Work's own OPEN-only filter).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_work_order_drops_out_of_my_work(client: AsyncClient) -> None:
    work_order_id = await _open_work_order(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-pm-1", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/close",
        json={},
        headers=_as("MAINTENANCE"),
    )

    my_work = await client.get("/api/v1/pm/work-orders/my-work", headers=_as("TECHNICIAN", "user-pm-1"))
    ids = [w["pm_work_order_id"] for w in my_work.json()["items"]]
    assert work_order_id not in ids


@pytest.mark.asyncio
async def test_reassignment_removes_the_work_order_from_the_previous_technicians_my_work(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_work_order(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-pm-1", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-pm-2", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    old_my_work = await client.get(
        "/api/v1/pm/work-orders/my-work", headers=_as("TECHNICIAN", "user-pm-1")
    )
    assert work_order_id not in [w["pm_work_order_id"] for w in old_my_work.json()["items"]]

    new_my_work = await client.get(
        "/api/v1/pm/work-orders/my-work", headers=_as("TECHNICIAN", "user-pm-2")
    )
    assert work_order_id in [w["pm_work_order_id"] for w in new_my_work.json()["items"]]
