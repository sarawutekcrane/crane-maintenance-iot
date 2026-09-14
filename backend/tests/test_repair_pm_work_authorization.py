"""Core Demo Fixes Delta REV06 sections 12/13 (P1) — Repair action/part
and PM task-result authorization.

The independent REV05 audit found `POST /repairs/{id}/actions`,
`POST /repairs/{id}/parts`, and `POST /pm/work-orders/{id}/results` had no
capability or assignment check at all: any actor could write to any
Repair/PM Work Order. REV06 adds
`app.domain.authz.require_assignment_or_capability`: an actor may record
work only when they are that specific occurrence's own active
PRIMARY/COLLABORATOR, or hold `can_manage_repair`/`can_manage_pm` —
being assigned to a DIFFERENT repair/work order never grants access to
this one.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


async def _open_repair(client: AsyncClient, vehicle_id: str = "VEH-1046") -> str:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
    return response.json()["repair"]["repair_id"]


async def _assign_repair(
    client: AsyncClient, repair_id: str, primary: str | None, collaborators: list[str] | None = None
) -> None:
    response = await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": primary, "collaborators": collaborators or []},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200


async def _open_pm_work_order(client: AsyncClient, vehicle_id: str = "VEH-1046") -> tuple[str, str]:
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
    work_order = response.json()["work_order"]
    return work_order["pm_work_order_id"], work_order["scope_task_ids"][0]


async def _assign_pm(
    client: AsyncClient, work_order_id: str, primary: str | None, collaborators: list[str] | None = None
) -> None:
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": primary, "collaborators": collaborators or []},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 13-19 — Repair action/part authorization.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unassigned_technician_cannot_record_a_repair_action(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    response = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "ตรวจสอบ"},
        headers=_as("TECHNICIAN", "user-unassigned"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_technician_assigned_to_a_different_repair_cannot_record_here(
    client: AsyncClient,
) -> None:
    repair_a = await _open_repair(client, "VEH-1046")
    repair_b = await _open_repair(client, "VEH-1047")
    await _assign_repair(client, repair_a, "user-tech-1")

    response = await client.post(
        f"/api/v1/repairs/{repair_b}/actions",
        json={"action_text": "ตรวจสอบ"},
        headers=_as("TECHNICIAN", "user-tech-1"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_active_primary_technician_can_record_a_repair_action(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1")

    response = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "เปลี่ยนอะไหล่"},
        headers=_as("TECHNICIAN", "user-tech-1"),
    )
    assert response.status_code == 200
    assert len(response.json()["actions"]) == 1


@pytest.mark.asyncio
async def test_active_collaborator_can_record_a_repair_action(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1", ["user-tech-2"])

    response = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "ช่วยตรวจสอบ"},
        headers=_as("TECHNICIAN", "user-tech-2"),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_maintenance_can_record_a_repair_action_on_any_repair(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    response = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "ทีมซ่อมบำรุงบันทึก"},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_driver_cannot_record_a_repair_action(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    response = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "ทดสอบ"},
        headers=_as("DRIVER"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unassigned_technician_cannot_record_a_repair_part(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    response = await client.post(
        f"/api/v1/repairs/{repair_id}/parts",
        json={"part_description": "ไส้กรอง", "quantity": 1},
        headers=_as("TECHNICIAN", "user-unassigned"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_active_primary_technician_can_record_a_repair_part(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    await _assign_repair(client, repair_id, "user-tech-1")

    response = await client.post(
        f"/api/v1/repairs/{repair_id}/parts",
        json={"part_description": "ไส้กรอง", "quantity": 1},
        headers=_as("TECHNICIAN", "user-tech-1"),
    )
    assert response.status_code == 200
    assert len(response.json()["parts"]) == 1


@pytest.mark.asyncio
async def test_driver_cannot_record_a_repair_part(client: AsyncClient) -> None:
    repair_id = await _open_repair(client)
    response = await client.post(
        f"/api/v1/repairs/{repair_id}/parts",
        json={"part_description": "ไส้กรอง", "quantity": 1},
        headers=_as("DRIVER"),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 20-22 — PM task result authorization.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_technician_cannot_submit_a_pm_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_pm_work_order(client)
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True},
        headers=_as("TECHNICIAN", "user-unrelated"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_technician_assigned_to_a_different_pmwo_cannot_submit_here(
    client: AsyncClient,
) -> None:
    wo_a, _ = await _open_pm_work_order(client, "VEH-1046")
    wo_b, task_b = await _open_pm_work_order(client, "VEH-1047")
    await _assign_pm(client, wo_a, "user-pm-1")

    response = await client.post(
        f"/api/v1/pm/work-orders/{wo_b}/results",
        json={"pm_task_id": task_b, "completed": True},
        headers=_as("TECHNICIAN", "user-pm-1"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_assigned_technician_can_submit_a_pm_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_pm_work_order(client)
    await _assign_pm(client, work_order_id, "user-pm-1")

    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True},
        headers=_as("TECHNICIAN", "user-pm-1"),
    )
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


@pytest.mark.asyncio
async def test_assigned_collaborator_can_submit_a_pm_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_pm_work_order(client)
    await _assign_pm(client, work_order_id, "user-pm-1", ["user-pm-2"])

    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True},
        headers=_as("TECHNICIAN", "user-pm-2"),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_maintenance_can_submit_a_pm_task_result_on_any_work_order(
    client: AsyncClient,
) -> None:
    work_order_id, task_id = await _open_pm_work_order(client)
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
