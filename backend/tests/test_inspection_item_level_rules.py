"""CORRECTION (post-Phase-3 verification): `required_remark_on_fail` and
`required_photo_on_fail` are both per-item, source-data-driven flags that
default to `False`. No seed/placeholder checklist item may set either one
`True` without an authoritative source (see the SOURCE DATA RULE note in
`app/repositories/mock/seed_data.py`), so the mechanism itself is proven
here using a synthetic item injected directly into the running
`MockRepository` instance, the same technique already used by
`test_mock_repository_inspection.py` for revision-immutability tests —
never by inventing a real rule in seed data.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.dependencies import get_repository
from app.domain.checklist import ChecklistItem


def _inject_item(revision_id: str, item_id: str, **overrides: object) -> ChecklistItem:
    repo = get_repository()
    item = ChecklistItem(
        item_id=item_id,
        revision_id=revision_id,
        sequence=999,
        title=f"รายการทดสอบ {item_id} (สร้างขึ้นเพื่อทดสอบเท่านั้น ไม่ใช่ข้อมูลจริง)",
        **overrides,  # type: ignore[arg-type]
    )
    repo._checklist_items.setdefault(revision_id, []).append(item)  # type: ignore[attr-defined]
    return item


async def _active_vehicle_checklist(client: AsyncClient) -> dict:
    response = await client.get("/api/v1/checklists/active", params={"asset_type": "VEHICLE"})
    assert response.status_code == 200
    return response.json()


def _all_pass_items(checklist: dict) -> list[dict]:
    return [{"item_id": item["item_id"], "result": "PASS"} for item in checklist["items"]]


@pytest.mark.asyncio
async def test_fail_allowed_without_remark_when_item_does_not_require_it(
    client: AsyncClient,
) -> None:
    checklist = await _active_vehicle_checklist(client)
    revision_id = checklist["revision"]["revision_id"]
    item = _inject_item(revision_id, "ITM-TEST-NOREMARK", required_remark_on_fail=False)

    checklist = await _active_vehicle_checklist(client)
    items = _all_pass_items(checklist)
    for entry in items:
        if entry["item_id"] == item.item_id:
            entry["result"] = "FAIL"

    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 200
    fail_results = [i for i in response.json()["items"] if i["result"] == "FAIL"]
    assert len(fail_results) == 1
    assert fail_results[0]["remark"] is None


@pytest.mark.asyncio
async def test_fail_rejected_without_remark_when_item_requires_it(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    revision_id = checklist["revision"]["revision_id"]
    item = _inject_item(revision_id, "ITM-TEST-REMARK", required_remark_on_fail=True)

    checklist = await _active_vehicle_checklist(client)
    items = _all_pass_items(checklist)
    for entry in items:
        if entry["item_id"] == item.item_id:
            entry["result"] = "FAIL"

    rejected = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert rejected.status_code == 422
    body = rejected.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["item_id"] == item.item_id

    for entry in items:
        if entry["item_id"] == item.item_id:
            entry["remark"] = "พบปัญหาในการทดสอบ"

    accepted = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert accepted.status_code == 200


@pytest.mark.asyncio
async def test_fail_rejected_without_photo_when_item_requires_it(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    revision_id = checklist["revision"]["revision_id"]
    item = _inject_item(revision_id, "ITM-TEST-PHOTO", required_photo_on_fail=True)

    checklist = await _active_vehicle_checklist(client)
    items = _all_pass_items(checklist)
    for entry in items:
        if entry["item_id"] == item.item_id:
            entry["result"] = "FAIL"
            entry["remark"] = "พบปัญหาแต่ไม่มีรูปถ่าย"

    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["item_id"] == item.item_id


@pytest.mark.asyncio
async def test_pass_and_na_unaffected_by_item_level_required_flags(
    client: AsyncClient,
) -> None:
    checklist = await _active_vehicle_checklist(client)
    revision_id = checklist["revision"]["revision_id"]
    _inject_item(
        revision_id,
        "ITM-TEST-BOTHFLAGS",
        required_remark_on_fail=True,
        required_photo_on_fail=True,
    )

    checklist = await _active_vehicle_checklist(client)
    pass_items = _all_pass_items(checklist)
    pass_response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": pass_items},
    )
    assert pass_response.status_code == 200
    assert pass_response.json()["findings"] == []

    na_items = [{"item_id": i["item_id"], "result": "NA"} for i in checklist["items"]]
    na_response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": na_items},
    )
    assert na_response.status_code == 200
    assert na_response.json()["findings"] == []
