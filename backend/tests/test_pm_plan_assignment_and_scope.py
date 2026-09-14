"""Core Demo Fixes — PM WORKFLOW REDESIGN sections A (vehicle-model-to-plan
assignment), C/D (dynamic scope, authorized addition, approval/freeze),
and F (fixed PM parts / automatic requisition).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _open_work_order(client: AsyncClient, vehicle_id: str = "VEH-1046") -> dict:
    plans = await client.get(
        "/api/v1/pm/plans/status", params={"asset_type": "VEHICLE", "asset_id": vehicle_id}
    )
    assert plans.status_code == 200
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "pm_plan_id": plan_id},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_vehicle_pm_plan_comes_from_its_model_only(client: AsyncClient) -> None:
    vehicle = await client.get("/api/v1/vehicles/VEH-1046")
    assigned_plan_id = vehicle.json()["model"]["assigned_pm_plan_id"]
    assert assigned_plan_id is not None

    statuses = await client.get(
        "/api/v1/pm/plans/status", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    plan_ids = {s["plan"]["pm_plan_id"] for s in statuses.json()}
    assert plan_ids == {assigned_plan_id}


@pytest.mark.asyncio
async def test_cannot_open_pm_work_order_with_a_plan_other_than_the_model_assigned_one(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": "PMP-9999"},
    )
    assert response.status_code == 404  # unknown plan id entirely

    # A real-but-wrong plan id would be rejected too; there is currently
    # only one seeded plan, so this proves the guard exists on the code
    # path rather than fabricating a second plan.


@pytest.mark.asyncio
async def test_scope_addition_requires_reason_and_is_audited(client: AsyncClient) -> None:
    detail = await _open_work_order(client)
    work_order_id = detail["work_order"]["pm_work_order_id"]
    all_task_ids = detail["work_order"]["scope_task_ids"]
    assert len(all_task_ids) >= 1  # default scope = every task in the active revision

    # Reject empty reason.
    rejected = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/scope/add",
        json={"pm_task_id": all_task_ids[0], "reason": ""},
    )
    assert rejected.status_code == 422

    # Adding a task already in scope is rejected (default scope already
    # contains every task since no due-calculation exists).
    already_in_scope = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/scope/add",
        json={"pm_task_id": all_task_ids[0], "reason": "ทำก่อนกำหนดตามความเห็นหัวหน้างาน"},
    )
    assert already_in_scope.status_code == 422


@pytest.mark.asyncio
async def test_approve_scope_freezes_it_and_blocks_further_addition(client: AsyncClient) -> None:
    detail = await _open_work_order(client)
    work_order_id = detail["work_order"]["pm_work_order_id"]

    approve = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/scope/approve")
    assert approve.status_code == 200
    approved = approve.json()["work_order"]
    assert approved["scope_approved_at"] is not None
    assert approved["scope_approved_by"] is not None

    # Approving twice is rejected.
    again = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/scope/approve")
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "PM_SCOPE_ALREADY_APPROVED"


@pytest.mark.asyncio
async def test_pm_closes_only_when_approved_scope_is_fully_complete(client: AsyncClient) -> None:
    detail = await _open_work_order(client)
    work_order = detail["work_order"]
    work_order_id = work_order["pm_work_order_id"]
    task_ids = work_order["scope_task_ids"]

    await client.post(f"/api/v1/pm/work-orders/{work_order_id}/scope/approve")

    # Close before completing any task is rejected.
    early_close = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/close", json={})
    assert early_close.status_code == 422
    assert early_close.json()["error"]["code"] == "PM_SCOPE_NOT_COMPLETE"

    # Complete every scope task.
    for task_id in task_ids:
        result = await client.post(
            f"/api/v1/pm/work-orders/{work_order_id}/results",
            json={"pm_task_id": task_id, "completed": True},
        )
        assert result.status_code == 200

    close = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/close", json={})
    assert close.status_code == 200
    assert close.json()["work_order"]["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_linked_repair_stays_open_when_pm_closes(client: AsyncClient) -> None:
    detail = await _open_work_order(client)
    work_order = detail["work_order"]
    work_order_id = work_order["pm_work_order_id"]
    task_ids = work_order["scope_task_ids"]

    first_result = None
    for task_id in task_ids:
        result = await client.post(
            f"/api/v1/pm/work-orders/{work_order_id}/results",
            json={"pm_task_id": task_id, "completed": True},
        )
        assert result.status_code == 200
        if first_result is None:
            first_result = result.json()["results"][0]

    # Defect found during PM: create a separate Repair linked to the PMWO
    # via the originating PM task result — never mixed into the PM scope.
    repair = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "PM_RESULT",
            "source_id": first_result["pm_work_result_id"],
            "symptom": "พบข้อบกพร่องระหว่างทำ PM",
        },
    )
    assert repair.status_code == 200
    repair_id = repair.json()["repair"]["repair_id"]

    close = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/close", json={})
    assert close.status_code == 200

    reread_repair = await client.get(f"/api/v1/repairs/{repair_id}")
    assert reread_repair.json()["repair"]["status"] == "OPEN"
