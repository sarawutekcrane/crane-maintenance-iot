"""Repair API tests (Phase 4)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _submit_failing_inspection(client: AsyncClient, vehicle_id: str = "VEH-1046") -> dict:
    checklist = await client.get("/api/v1/checklists/active", params={"asset_type": "VEHICLE"})
    items = [{"item_id": i["item_id"], "result": "PASS"} for i in checklist.json()["items"]]
    items[0]["result"] = "FAIL"
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "items": items},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_manual_repair_creation_works(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "MANUAL",
            "category": "ระบบไฮดรอลิก",
            "symptom": "มีเสียงดังผิดปกติ",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["repair"]["repair_id"].startswith("RPR-")
    assert body["repair"]["source_type"] == "MANUAL"
    assert body["repair"]["source_id"] is None
    assert body["repair"]["status"] == "OPEN"
    assert body["actions"] == []
    assert body["parts"] == []


@pytest.mark.asyncio
async def test_repair_for_unknown_vehicle_returns_controlled_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-9999", "source_type": "MANUAL"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_finding_source_links_to_repair_without_mutating_the_finding(
    client: AsyncClient,
) -> None:
    inspection = await _submit_failing_inspection(client)
    finding_id = inspection["findings"][0]["finding_id"]
    finding_before = inspection["findings"][0]

    repair_response = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "FINDING",
            "source_id": finding_id,
        },
    )
    assert repair_response.status_code == 200
    assert repair_response.json()["repair"]["source_type"] == "FINDING"
    assert repair_response.json()["repair"]["source_id"] == finding_id

    # The source Finding itself is never mutated — re-reading the original
    # inspection shows the exact same finding record.
    reread = await client.get(f"/api/v1/inspections/{inspection['header']['inspection_id']}")
    assert reread.json()["findings"][0] == finding_before


@pytest.mark.asyncio
async def test_inspection_result_source_linkage_supported(client: AsyncClient) -> None:
    inspection = await _submit_failing_inspection(client, vehicle_id="VEH-1048")
    failed_result = next(i for i in inspection["items"] if i["result"] == "FAIL")

    response = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1048",
            "source_type": "INSPECTION_RESULT",
            "source_id": failed_result["result_id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["repair"]["source_type"] == "INSPECTION_RESULT"


@pytest.mark.asyncio
async def test_pm_result_source_linkage_supported(client: AsyncClient) -> None:
    work_order = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1047", "pm_plan_id": "PMP-0001"},
    )
    work_order_id = work_order.json()["work_order"]["pm_work_order_id"]
    result = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": False, "remark": "พบความผิดปกติระหว่าง PM"},
    )
    pm_result_id = result.json()["results"][0]["pm_work_result_id"]

    repair = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1047",
            "source_type": "PM_RESULT",
            "source_id": pm_result_id,
        },
    )
    assert repair.status_code == 200
    assert repair.json()["repair"]["source_type"] == "PM_RESULT"
    assert repair.json()["repair"]["source_id"] == pm_result_id


@pytest.mark.asyncio
async def test_alert_source_is_interface_ready_without_an_alert_domain(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "ALERT",
            "source_id": "ALERT-PLACEHOLDER-0001",
        },
    )
    assert response.status_code == 200
    assert response.json()["repair"]["source_type"] == "ALERT"


@pytest.mark.asyncio
async def test_invalid_source_reference_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "FINDING",
            "source_id": "FND-DOES-NOT-EXIST",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPAIR_SOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_finding_source_requires_a_source_id(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "FINDING"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_fail_result_does_not_automatically_create_a_repair(client: AsyncClient) -> None:
    """Phase 3's FAIL->Finding behavior is unchanged: submitting a FAIL
    inspection never itself creates a Repair record unless this API is
    called explicitly (F02 is unresolved — no automatic conversion)."""
    before = await client.get(
        "/api/v1/repairs", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    before_count = before.json()["total_items"]

    await _submit_failing_inspection(client)

    after = await client.get(
        "/api/v1/repairs", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    assert after.json()["total_items"] == before_count


@pytest.mark.asyncio
async def test_repair_action_history_is_append_only_and_previous_actions_remain_readable(
    client: AsyncClient,
) -> None:
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    first = await client.post(
        f"/api/v1/repairs/{repair_id}/actions", json={"action_text": "ตรวจสอบเบื้องต้น"}
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/repairs/{repair_id}/actions", json={"action_text": "เปลี่ยนอะไหล่และทดสอบ"}
    )
    assert second.status_code == 200

    detail = await client.get(f"/api/v1/repairs/{repair_id}")
    actions = detail.json()["actions"]
    assert len(actions) == 2
    assert actions[0]["action_text"] == "ตรวจสอบเบื้องต้น"
    assert actions[1]["action_text"] == "เปลี่ยนอะไหล่และทดสอบ"
    assert actions[0]["repair_action_id"] != actions[1]["repair_action_id"]
    assert all(a["actor"] == "dev-user" for a in actions)


@pytest.mark.asyncio
async def test_repair_parts_are_separate_from_pm_parts(client: AsyncClient) -> None:
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    part_response = await client.post(
        f"/api/v1/repairs/{repair_id}/parts",
        json={"part_description": "สายไฮดรอลิก (ตัวอย่าง)", "quantity": 2, "unit": "เส้น"},
    )
    assert part_response.status_code == 200
    parts = part_response.json()["parts"]
    assert len(parts) == 1
    assert parts[0]["repair_part_id"].startswith("RPRP-")
    assert parts[0]["part_description"] == "สายไฮดรอลิก (ตัวอย่าง)"

    # Repair part IDs are a distinct namespace from PM used-part IDs.
    assert not parts[0]["repair_part_id"].startswith("PMUP-")


@pytest.mark.asyncio
async def test_repair_attachment_uses_storage_reference(client: AsyncClient) -> None:
    upload = await client.post(
        "/api/v1/attachments",
        data={"purpose": "REPAIR_EVIDENCE"},
        files={"file": ("evidence.jpg", b"fake-bytes", "image/jpeg")},
    )
    assert upload.status_code == 200
    attachment = upload.json()
    assert attachment["url"].startswith("/api/v1/attachments/")

    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]
    action = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "แนบรูปหลักฐาน", "attachment_ids": [attachment["attachment_id"]]},
    )
    assert action.status_code == 200
    assert action.json()["actions"][0]["attachment_ids"] == [attachment["attachment_id"]]


@pytest.mark.asyncio
async def test_repair_direct_read_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/repairs/RPR-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPAIR_NOT_FOUND"


@pytest.mark.asyncio
async def test_close_repair_requires_no_unapproved_fields(client: AsyncClient) -> None:
    """F03 is unresolved — closing must not require a photo, technician,
    part, approval, or note."""
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    close_response = await client.post(f"/api/v1/repairs/{repair_id}/close", json={})
    assert close_response.status_code == 200
    closed = close_response.json()["repair"]
    assert closed["status"] == "CLOSED"
    assert closed["closed_by"] == "dev-user"
    assert closed["close_note"] is None

    second_close = await client.post(f"/api/v1/repairs/{repair_id}/close", json={})
    assert second_close.status_code == 422
    assert second_close.json()["error"]["code"] == "REPAIR_ALREADY_CLOSED"


@pytest.mark.asyncio
async def test_repair_is_separate_from_pm_work_order_namespace(client: AsyncClient) -> None:
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    # A repair id is never resolvable through the PM work-order endpoint.
    response = await client.get(f"/api/v1/pm/work-orders/{repair_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PM_WORK_ORDER_NOT_FOUND"
