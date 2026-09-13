"""Phase 4 <-> Phase 5 integration tests: actual PM/Repair part records may
link to PartMaster/PartInstance, without collapsing standard vs actual
part concepts and without rewriting any Phase 4 history.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

CONSUMABLE_PART = "PART-0002"
INSTANCE_TRACKED_PART = "PART-0005"


async def _open_pm_work_order(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": "PMP-0001"},
    )
    assert response.status_code == 200
    return response.json()["work_order"]["pm_work_order_id"]


async def _create_installed_instance(client: AsyncClient, asset_id: str = "VEH-1046") -> str:
    created = await client.post(
        "/api/v1/part-instances",
        json={"part_id": INSTANCE_TRACKED_PART, "prior_usage": {"quality": "UNKNOWN"}},
    )
    instance_id = created.json()["instance"]["part_instance_id"]
    await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": asset_id},
    )
    return instance_id


@pytest.mark.asyncio
async def test_pm_used_part_may_link_to_part_master(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={
            "pm_task_id": "PMT-0001",
            "completed": True,
            "used_parts": [
                {
                    "part_description": "ไส้กรองน้ำมันเครื่อง",
                    "quantity": 1,
                    "part_id": CONSUMABLE_PART,
                    "action": "CONSUMED",
                }
            ],
        },
    )
    assert response.status_code == 200
    used_part = response.json()["results"][0]["used_parts"][0]
    assert used_part["part_id"] == CONSUMABLE_PART
    assert used_part["action"] == "CONSUMED"
    assert used_part["part_instance_id"] is None


@pytest.mark.asyncio
async def test_pm_used_part_may_link_to_part_instance(client: AsyncClient) -> None:
    instance_id = await _create_installed_instance(client)
    work_order_id = await _open_pm_work_order(client)
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={
            "pm_task_id": "PMT-0001",
            "completed": True,
            "used_parts": [
                {
                    "part_description": "ปั๊มไฮดรอลิกหลัก",
                    "part_instance_id": instance_id,
                    "action": "SERVICED",
                }
            ],
        },
    )
    assert response.status_code == 200
    used_part = response.json()["results"][0]["used_parts"][0]
    assert used_part["part_instance_id"] == instance_id


@pytest.mark.asyncio
async def test_pm_used_part_rejects_unknown_part_id(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={
            "pm_task_id": "PMT-0001",
            "completed": True,
            "used_parts": [{"part_description": "x", "part_id": "PART-9999"}],
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PART_NOT_FOUND"


@pytest.mark.asyncio
async def test_pm_used_part_rejects_unknown_part_instance_id(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={
            "pm_task_id": "PMT-0001",
            "completed": True,
            "used_parts": [{"part_description": "x", "part_instance_id": "PINST-9999"}],
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PART_INSTANCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_linking_actual_pm_part_does_not_alter_standard_task_part_definition(
    client: AsyncClient,
) -> None:
    before = await client.get("/api/v1/pm/plans/PMP-0001/active-revision")
    task_before = next(t for t in before.json()["tasks"] if t["pm_task_id"] == "PMT-0001")

    work_order_id = await _open_pm_work_order(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={
            "pm_task_id": "PMT-0001",
            "completed": True,
            "used_parts": [{"part_description": "x", "part_id": CONSUMABLE_PART}],
        },
    )

    after = await client.get("/api/v1/pm/plans/PMP-0001/active-revision")
    task_after = next(t for t in after.json()["tasks"] if t["pm_task_id"] == "PMT-0001")
    assert task_after["standard_parts"] == task_before["standard_parts"] == []


@pytest.mark.asyncio
async def test_repair_part_may_link_to_part_master_and_instance(client: AsyncClient) -> None:
    instance_id = await _create_installed_instance(client)
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    response = await client.post(
        f"/api/v1/repairs/{repair_id}/parts",
        json={
            "part_description": "ปั๊มไฮดรอลิกหลัก",
            "part_id": INSTANCE_TRACKED_PART,
            "part_instance_id": instance_id,
            "action": "REMOVED",
        },
    )
    assert response.status_code == 200
    part = response.json()["parts"][0]
    assert part["part_id"] == INSTANCE_TRACKED_PART
    assert part["part_instance_id"] == instance_id
    assert part["action"] == "REMOVED"


@pytest.mark.asyncio
async def test_repair_part_rejects_unknown_part_instance_id(client: AsyncClient) -> None:
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]
    response = await client.post(
        f"/api/v1/repairs/{repair_id}/parts",
        json={"part_description": "x", "part_instance_id": "PINST-9999"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PART_INSTANCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_standard_pm_part_actual_pm_part_and_repair_part_remain_distinct_concepts(
    client: AsyncClient,
) -> None:
    """Regression guard: linking to PartMaster/PartInstance must never
    collapse pm_task_part / pm_used_part / repair_part into one concept."""
    work_order_id = await _open_pm_work_order(client)
    pm_result = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={
            "pm_task_id": "PMT-0001",
            "completed": True,
            "used_parts": [{"part_description": "x", "part_id": CONSUMABLE_PART}],
        },
    )
    pm_used_part_id = pm_result.json()["results"][0]["used_parts"][0]["pm_used_part_id"]
    assert pm_used_part_id.startswith("PMUP-")

    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]
    repair_part = await client.post(
        f"/api/v1/repairs/{repair_id}/parts",
        json={"part_description": "x", "part_id": CONSUMABLE_PART},
    )
    repair_part_id = repair_part.json()["parts"][0]["repair_part_id"]
    assert repair_part_id.startswith("RPRP-")
    assert repair_part_id != pm_used_part_id
