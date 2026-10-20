"""CORRECTION (post-Phase-3 verification): `required_remark_on_fail` and
`required_photo_on_fail` are both per-item, source-data-driven flags that
default to `False`. No seed/placeholder checklist item may set either one
`True` without an authoritative source (see the SOURCE DATA RULE note in
`app/repositories/mock/seed_data.py`), so the mechanism itself is proven
here using a synthetic item injected directly into the running
`MockRepository` instance, the same technique already used by
`test_mock_repository_inspection.py` for revision-immutability tests —
never by inventing a real rule in seed data.

R3 DELIBERATE MIGRATION (docs/project-governance/r3-implementation-contract.md §4, Owner
rule R3-15): "The per-item `required_photo_on_fail` and `required_remark_on_fail` flags are
kept for reading history but no longer drive validation." Both abnormal results now always
need a non-empty remark and a photo is always optional; legacy NA is never accepted for new
entry (R3-16). Each test below keeps its injected flag and asserts the R3 outcome. Injected
items carry an R3 item_key and frequency so the revision stays R3-ready (TS-11).
"""
from __future__ import annotations

import uuid

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
        item_key=f"KEY-{item_id}",
        frequency="DAILY",
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


def _post(client: AsyncClient, items: list[dict], asset_id: str = "VEH-1046"):
    return client.post(
        "/api/v1/inspections",
        headers={"X-Request-Id": str(uuid.uuid4())},  # R3 S2: one request id per submission
        json={"asset_type": "VEHICLE", "asset_id": asset_id, "items": items},
    )


async def _items_with(client: AsyncClient, item_id: str, **answer: object) -> list[dict]:
    items = _all_pass_items(await _active_vehicle_checklist(client))
    for entry in items:
        if entry["item_id"] == item_id:
            entry.update(answer)
    return items


@pytest.mark.asyncio
async def test_fail_allowed_without_remark_when_item_does_not_require_it(
    client: AsyncClient,
) -> None:
    """R3-15 supersedes the flag: a FAIL without a remark is refused even when the
    item's required_remark_on_fail is False."""
    checklist = await _active_vehicle_checklist(client)
    item = _inject_item(checklist["revision"]["revision_id"], "ITM-TEST-NOREMARK", required_remark_on_fail=False)
    response = await _post(client, await _items_with(client, item.item_id, result="FAIL"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INSPECTION_REMARK_REQUIRED"
    assert response.json()["error"]["details"]["item_id"] == item.item_id


@pytest.mark.asyncio
async def test_fail_rejected_without_remark_when_item_requires_it(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    item = _inject_item(checklist["revision"]["revision_id"], "ITM-TEST-REMARK", required_remark_on_fail=True)
    rejected = await _post(client, await _items_with(client, item.item_id, result="FAIL"))
    assert rejected.status_code == 422
    body = rejected.json()
    assert body["error"]["code"] == "INSPECTION_REMARK_REQUIRED"  # R3-15 code (was VALIDATION_ERROR)
    assert body["error"]["details"]["item_id"] == item.item_id

    accepted = await _post(client, await _items_with(client, item.item_id, result="FAIL", remark="พบปัญหาในการทดสอบ"))
    assert accepted.status_code == 200


@pytest.mark.asyncio
async def test_fail_rejected_without_photo_when_item_requires_it(client: AsyncClient) -> None:
    """R3-15 supersedes the flag: a photo is optional, so a FAIL with a remark and no
    photo is accepted even when required_photo_on_fail is True."""
    checklist = await _active_vehicle_checklist(client)
    item = _inject_item(checklist["revision"]["revision_id"], "ITM-TEST-PHOTO", required_photo_on_fail=True)
    response = await _post(client, await _items_with(client, item.item_id, result="FAIL", remark="พบปัญหาแต่ไม่มีรูปถ่าย"))
    assert response.status_code == 200, response.text
    fail = [i for i in response.json()["items"] if i["item_id"] == item.item_id][0]
    assert fail["evidence"] == []


@pytest.mark.asyncio
async def test_pass_and_na_unaffected_by_item_level_required_flags(
    client: AsyncClient,
) -> None:
    checklist = await _active_vehicle_checklist(client)
    _inject_item(
        checklist["revision"]["revision_id"],
        "ITM-TEST-BOTHFLAGS",
        required_remark_on_fail=True,
        required_photo_on_fail=True,
    )
    checklist = await _active_vehicle_checklist(client)
    pass_response = await _post(client, _all_pass_items(checklist))
    assert pass_response.status_code == 200
    assert pass_response.json()["findings"] == []

    # R3-16: legacy NA is never accepted for a new entry (another asset: one per day).
    na_items = [{"item_id": i["item_id"], "result": "NA"} for i in checklist["items"]]
    na_response = await _post(client, na_items, asset_id="VEH-1047")
    assert na_response.status_code == 422
    assert na_response.json()["error"]["code"] == "INSPECTION_RESULT_NOT_ALLOWED"
