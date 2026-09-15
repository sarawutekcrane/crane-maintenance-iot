"""Core Demo Fixes Delta REV06 section 18 — PM My Work.

The independent REV05 audit verified Repair My Work (`GET /repairs/my-work`)
exists but its PM equivalent does not. REV06 adds `GET
/pm/work-orders/my-work`, derived exactly the same way (active assignment
to the current actor via `primary_technician`/`collaborators`, kept in
sync by `assign_pm_work_order`/`PmAssignmentHistoryEntry` — no new table,
no new status, no new source field).

Final Cross-Phase Integration Fix (F1): the Final Cross-Phase Audit found
that `list_pm_work_orders`'s own `assigned_to` filter (backing this My Work
endpoint) still read the denormalized `primary_technician`/`collaborators`
fields directly rather than the append-only `pm_work_order_assignment`
history — the same stale-state class REV06.2 already closed for Repair's
own My Work/Waiting Assignment queues. The tests at the bottom of this file
prove the fix: My Work now tracks history even when the denormalized
fields are stale, missing, or out of sync (deliberately induced here by
writing to the repository directly, bypassing `assign_pm_work_order`).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.domain.meter_service import MeterService
from app.domain.pm_service import PmService
from app.repositories.mock import MockRepository


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


# ---------------------------------------------------------------------------
# F1 (Final Cross-Phase Integration Fix) — My Work tracks assignment
# history, not the denormalized `primary_technician`/`collaborators`
# fields, once the two disagree (the exact partial-write window REV06.2
# already closed for Repair's own queues).
# ---------------------------------------------------------------------------


async def _pm_service_and_repo() -> tuple[PmService, MockRepository]:
    repo = MockRepository()
    return PmService(repo, MeterService(repo)), repo


async def _open_work_order_direct(service: PmService, vehicle_id: str = "VEH-1046") -> str:
    statuses = await service.list_applicable_plan_status(AssetType.VEHICLE, vehicle_id)
    plan_id = statuses[0].plan.pm_plan_id
    detail = await service.open_work_order(
        asset_type=AssetType.VEHICLE,
        asset_id=vehicle_id,
        pm_plan_id=plan_id,
        due_reason=None,
        opened_by="user-maintenance",
        note=None,
    )
    return detail.work_order.pm_work_order_id


@pytest.mark.asyncio
async def test_my_work_does_not_surface_a_stale_denormalized_field_alone() -> None:
    service, repo = await _pm_service_and_repo()
    work_order_id = await _open_work_order_direct(service)

    # No assignment history at all — the denormalized field is corrupted
    # to name a technician directly, without ever going through
    # `assign_pm_work_order`.
    stale = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": "tech-stale", "collaborators": []}
    )
    repo._pm_work_orders[work_order_id] = stale

    page = await service.list_work_orders(
        asset_type=None,
        asset_id=None,
        params=PageParams(),
        assigned_to="tech-stale",
    )
    assert work_order_id not in [w.pm_work_order_id for w in page.items]


@pytest.mark.asyncio
async def test_my_work_reflects_active_history_even_with_a_blank_denormalized_field() -> None:
    service, repo = await _pm_service_and_repo()
    work_order_id = await _open_work_order_direct(service)

    await service.assign(work_order_id, primary_technician="tech-b", collaborators=[])

    # Wipe the denormalized fields entirely, leaving history as the only
    # record of the real, active assignment.
    wiped = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": None, "collaborators": []}
    )
    repo._pm_work_orders[work_order_id] = wiped

    page = await service.list_work_orders(
        asset_type=None,
        asset_id=None,
        params=PageParams(),
        assigned_to="tech-b",
    )
    assert work_order_id in [w.pm_work_order_id for w in page.items]
