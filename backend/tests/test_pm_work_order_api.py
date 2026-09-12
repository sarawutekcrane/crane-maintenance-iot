"""PM work-order / work-result API tests (Phase 4)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _open_work_order(client: AsyncClient, asset_id: str = "VEH-1046") -> dict:
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": asset_id, "pm_plan_id": "PMP-0001"},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_open_pm_work_order_references_active_plan_and_revision(client: AsyncClient) -> None:
    body = await _open_work_order(client)
    work_order = body["work_order"]
    assert work_order["pm_work_order_id"].startswith("PMWO-")
    assert work_order["pm_plan_id"] == "PMP-0001"
    assert work_order["revision_id"] == "PMREV-0001"
    assert work_order["status"] == "OPEN"
    assert work_order["opened_by"] == "dev-user"
    assert body["results"] == []


@pytest.mark.asyncio
async def test_pm_work_order_for_unknown_vehicle_returns_controlled_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-9999", "pm_plan_id": "PMP-0001"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_pm_work_order_with_unknown_plan_returns_controlled_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": "PMP-9999"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PM_PLAN_NOT_FOUND"


@pytest.mark.asyncio
async def test_pm_plan_asset_type_mismatch_is_rejected(client: AsyncClient) -> None:
    """PMP-0001 is a VEHICLE plan; requesting it for EQUIPMENT is invalid."""
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001", "pm_plan_id": "PMP-0001"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_pm_work_order_direct_read_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pm/work-orders/PMWO-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PM_WORK_ORDER_NOT_FOUND"


@pytest.mark.asyncio
async def test_work_order_accumulates_multiple_task_results(client: AsyncClient) -> None:
    body = await _open_work_order(client)
    work_order_id = body["work_order"]["pm_work_order_id"]

    for task_id in ("PMT-0001", "PMT-0002", "PMT-0003"):
        response = await client.post(
            f"/api/v1/pm/work-orders/{work_order_id}/results",
            json={"pm_task_id": task_id, "completed": True},
        )
        assert response.status_code == 200

    detail = await client.get(f"/api/v1/pm/work-orders/{work_order_id}")
    results = detail.json()["results"]
    assert len(results) == 3
    assert {r["pm_task_id"] for r in results} == {"PMT-0001", "PMT-0002", "PMT-0003"}
    assert all(r["performed_by"] == "dev-user" for r in results)


@pytest.mark.asyncio
async def test_completed_task_result_is_not_silently_overwritten(client: AsyncClient) -> None:
    body = await _open_work_order(client)
    work_order_id = body["work_order"]["pm_work_order_id"]

    first = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": True, "remark": "ครั้งแรก"},
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": False, "remark": "พยายามแก้ไข"},
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "PM_TASK_RESULT_ALREADY_EXISTS"

    detail = await client.get(f"/api/v1/pm/work-orders/{work_order_id}")
    results = detail.json()["results"]
    assert len(results) == 1
    assert results[0]["remark"] == "ครั้งแรก"
    assert results[0]["completed"] is True


@pytest.mark.asyncio
async def test_task_result_for_task_outside_the_revision_is_rejected(client: AsyncClient) -> None:
    body = await _open_work_order(client)
    work_order_id = body["work_order"]["pm_work_order_id"]
    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-DOES-NOT-EXIST", "completed": True},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_actual_parts_used_are_separate_from_pm_task_standard_parts(
    client: AsyncClient,
) -> None:
    """PmTask.standard_parts (expected parts) and the actual-used parts
    recorded on a work result are distinct record sets (Phase 4
    requirement: never write actual usage back into the standard PM
    definition)."""
    revision_before = await client.get("/api/v1/pm/plans/PMP-0001/active-revision")
    standard_parts_before = revision_before.json()["tasks"][0]["standard_parts"]
    assert standard_parts_before == []  # no fabricated standard part exists (E05)

    body = await _open_work_order(client)
    work_order_id = body["work_order"]["pm_work_order_id"]
    result = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={
            "pm_task_id": "PMT-0001",
            "completed": True,
            "used_parts": [
                {"part_description": "ไส้กรองน้ำมันเครื่อง (ตัวอย่าง)", "quantity": 1, "unit": "ชิ้น"}
            ],
        },
    )
    assert result.status_code == 200
    used_parts = result.json()["results"][0]["used_parts"]
    assert len(used_parts) == 1
    assert used_parts[0]["pm_used_part_id"].startswith("PMUP-")
    assert used_parts[0]["part_description"] == "ไส้กรองน้ำมันเครื่อง (ตัวอย่าง)"

    # The task revision's own standard-parts definition is unaffected by
    # what was actually used in this work order.
    revision_after = await client.get("/api/v1/pm/plans/PMP-0001/active-revision")
    assert revision_after.json()["tasks"][0]["standard_parts"] == []


@pytest.mark.asyncio
async def test_close_work_order_preserves_task_result_history(client: AsyncClient) -> None:
    body = await _open_work_order(client)
    work_order_id = body["work_order"]["pm_work_order_id"]
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": True},
    )

    close_response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/close", json={"note": "ปิดงาน PM"}
    )
    assert close_response.status_code == 200
    closed = close_response.json()
    assert closed["work_order"]["status"] == "CLOSED"
    assert closed["work_order"]["closed_by"] == "dev-user"
    assert closed["work_order"]["note"] == "ปิดงาน PM"
    assert len(closed["results"]) == 1

    # Closing again is rejected rather than silently accepted.
    second_close = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/close", json={})
    assert second_close.status_code == 422
    assert second_close.json()["error"]["code"] == "PM_WORK_ORDER_ALREADY_CLOSED"


@pytest.mark.asyncio
async def test_closed_work_order_rejects_new_task_results(client: AsyncClient) -> None:
    body = await _open_work_order(client)
    work_order_id = body["work_order"]["pm_work_order_id"]
    await client.post(f"/api/v1/pm/work-orders/{work_order_id}/close", json={})

    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": True},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PM_WORK_ORDER_CLOSED"


@pytest.mark.asyncio
async def test_pm_work_order_history_lists_newest_first(client: AsyncClient) -> None:
    first = await _open_work_order(client, asset_id="VEH-1047")
    second = await _open_work_order(client, asset_id="VEH-1047")

    history = await client.get(
        "/api/v1/pm/work-orders", params={"asset_type": "VEHICLE", "asset_id": "VEH-1047"}
    )
    assert history.status_code == 200
    ids = [row["pm_work_order_id"] for row in history.json()["items"]]
    assert ids[0] == second["work_order"]["pm_work_order_id"]
    assert ids[1] == first["work_order"]["pm_work_order_id"]


@pytest.mark.asyncio
async def test_pm_plan_status_reports_last_completed_after_close(client: AsyncClient) -> None:
    before = await client.get(
        "/api/v1/pm/plans/status", params={"asset_type": "VEHICLE", "asset_id": "VEH-1048"}
    )
    assert before.json()[0]["last_completed_work_order_id"] is None
    # due_status is never computed — E02/E03/E04 remain unresolved.
    assert before.json()[0]["due_status"] == "UNKNOWN"

    body = await _open_work_order(client, asset_id="VEH-1048")
    work_order_id = body["work_order"]["pm_work_order_id"]
    snapshot = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1048",
            "readings": [{"counter_type": "ODOMETER", "value": 500}],
        },
    )
    snapshot_id = snapshot.json()["meter_snapshot_id"]
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": True, "meter_snapshot_id": snapshot_id},
    )
    await client.post(f"/api/v1/pm/work-orders/{work_order_id}/close", json={})

    after = await client.get(
        "/api/v1/pm/plans/status", params={"asset_type": "VEHICLE", "asset_id": "VEH-1048"}
    )
    row = after.json()[0]
    assert row["last_completed_work_order_id"] == work_order_id
    assert row["last_completed_meter_snapshot_id"] == snapshot_id
    assert row["last_completed_at"] is not None
    # Still never computed into a due/remaining value.
    assert row["due_status"] == "UNKNOWN"
