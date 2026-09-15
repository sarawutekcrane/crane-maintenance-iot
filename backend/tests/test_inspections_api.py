from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _active_vehicle_checklist(client: AsyncClient) -> dict:
    response = await client.get("/api/v1/checklists/active", params={"asset_type": "VEHICLE"})
    assert response.status_code == 200
    return response.json()


def _all_pass_items(checklist: dict) -> list[dict]:
    return [{"item_id": item["item_id"], "result": "PASS"} for item in checklist["items"]]


@pytest.mark.asyncio
async def test_active_checklist_loads_automatically_for_vehicle(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    assert checklist["checklist"]["asset_type"] == "VEHICLE"
    assert checklist["revision"]["revision_number"] == 1
    assert len(checklist["items"]) == 5
    # Thai checklist name renders (no ordinary user needs to pick a revision).
    assert "ตรวจเช็ค" in checklist["checklist"]["name"]


@pytest.mark.asyncio
async def test_active_checklist_loads_automatically_for_equipment(client: AsyncClient) -> None:
    response = await client.get("/api/v1/checklists/active", params={"asset_type": "EQUIPMENT"})
    assert response.status_code == 200
    body = response.json()
    assert body["checklist"]["asset_type"] == "EQUIPMENT"
    assert len(body["items"]) == 4


@pytest.mark.asyncio
async def test_checklist_revision_direct_read_matches_active(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    checklist_id = checklist["checklist"]["checklist_id"]
    revision_id = checklist["revision"]["revision_id"]
    response = await client.get(f"/api/v1/checklists/{checklist_id}/revisions/{revision_id}")
    assert response.status_code == 200
    assert response.json() == checklist


@pytest.mark.asyncio
async def test_checklist_revision_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/checklists/CHK-0001/revisions/REV-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHECKLIST_REVISION_NOT_FOUND"


@pytest.mark.asyncio
async def test_submit_inspection_all_pass_for_vehicle(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    response = await client.post(
        "/api/v1/inspections",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "items": _all_pass_items(checklist),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["header"]["asset_type"] == "VEHICLE"
    assert body["header"]["asset_id"] == "VEH-1046"
    assert body["header"]["revision_id"] == checklist["revision"]["revision_id"]
    assert body["header"]["inspector_user_id"] == "dev-user"
    assert body["header"]["inspection_id"].startswith("INS-")
    assert len(body["items"]) == 5
    assert all(item["result"] == "PASS" for item in body["items"])
    assert body["findings"] == []


@pytest.mark.asyncio
async def test_submit_inspection_accepts_na(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    items = [{"item_id": item["item_id"], "result": "NA"} for item in checklist["items"]]
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(item["result"] == "NA" for item in body["items"])
    assert body["findings"] == []


@pytest.mark.asyncio
async def test_placeholder_seed_items_do_not_require_remark_or_photo(
    client: AsyncClient,
) -> None:
    """CORRECTION (post-Phase-3 verification): no placeholder/development
    checklist item may enforce a remark or photo requirement without an
    authoritative source — see the SOURCE DATA RULE note in seed_data.py.
    """
    vehicle_checklist = await _active_vehicle_checklist(client)
    equipment_response = await client.get(
        "/api/v1/checklists/active", params={"asset_type": "EQUIPMENT"}
    )
    equipment_checklist = equipment_response.json()

    for item in [*vehicle_checklist["items"], *equipment_checklist["items"]]:
        assert item["required_remark_on_fail"] is False
        assert item["required_photo_on_fail"] is False


@pytest.mark.asyncio
async def test_submit_inspection_fail_creates_finding(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    last_item = max(checklist["items"], key=lambda i: i["sequence"])
    # Neither flag is required by seed data (see the test above); a remark
    # and an evidence photo can still be attached voluntarily and must
    # still be linked correctly.

    files = {"file": ("evidence.jpg", b"fake-jpeg-bytes", "image/jpeg")}
    upload = await client.post(
        "/api/v1/attachments",
        data={
            "purpose": "INSPECTION_EVIDENCE",
            "source_type": "INSPECTION_VEHICLE",
            "source_id": "VEH-1046",
        },
        files=files,
    )
    assert upload.status_code == 200
    attachment_id = upload.json()["attachment_id"]
    assert attachment_id.startswith("ATT-")

    items = _all_pass_items(checklist)
    items[-1] = {
        "item_id": last_item["item_id"],
        "result": "FAIL",
        "remark": "พบความผิดปกติระหว่างทดสอบ",
        "evidence_attachment_ids": [attachment_id],
    }
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 200
    body = response.json()

    fail_results = [item for item in body["items"] if item["result"] == "FAIL"]
    assert len(fail_results) == 1
    assert fail_results[0]["evidence"][0]["attachment_id"] == attachment_id
    assert fail_results[0]["evidence"][0]["url"] == f"/api/v1/attachments/{attachment_id}/file"

    assert len(body["findings"]) == 1
    finding = body["findings"][0]
    assert finding["finding_id"].startswith("FND-")
    assert finding["status"] == "OPEN"
    assert finding["result_id"] == fail_results[0]["result_id"]
    assert finding["asset_type"] == "VEHICLE"
    assert finding["asset_id"] == "VEH-1046"
    assert finding["is_critical"] is False


@pytest.mark.asyncio
async def test_submit_inspection_fail_without_remark_is_allowed_when_not_required(
    client: AsyncClient,
) -> None:
    """CORRECTION (post-Phase-3 verification): a FAIL is no longer
    unconditionally required to carry a remark — every seeded placeholder
    item has `required_remark_on_fail=False`, so a remark-less FAIL must
    be accepted. The `required_remark_on_fail=True` case is covered by
    `tests/test_inspection_item_level_rules.py` using an injected
    synthetic item, since no real/seed item may enforce this rule without
    an authoritative source."""
    checklist = await _active_vehicle_checklist(client)
    items = _all_pass_items(checklist)
    items[0] = {"item_id": checklist["items"][0]["item_id"], "result": "FAIL"}
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 200
    body = response.json()
    fail_results = [item for item in body["items"] if item["result"] == "FAIL"]
    assert len(fail_results) == 1
    assert fail_results[0]["remark"] is None
    assert len(body["findings"]) == 1


@pytest.mark.asyncio
async def test_submit_inspection_missing_item_is_rejected(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    items = _all_pass_items(checklist)[:-1]  # drop the last item
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert len(body["error"]["details"]["missing_item_ids"]) == 1


@pytest.mark.asyncio
async def test_submit_inspection_unknown_item_is_rejected(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    items = _all_pass_items(checklist)
    items.append({"item_id": "ITM-DOES-NOT-EXIST", "result": "PASS"})
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 422
    assert "ITM-DOES-NOT-EXIST" in response.json()["error"]["details"]["unknown_item_ids"]


@pytest.mark.asyncio
async def test_submit_inspection_invalid_result_enum_is_rejected(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    items = _all_pass_items(checklist)
    items[0]["result"] = "MAYBE"
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_submit_inspection_unknown_evidence_attachment_is_rejected(
    client: AsyncClient,
) -> None:
    checklist = await _active_vehicle_checklist(client)
    last_item = max(checklist["items"], key=lambda i: i["sequence"])
    items = _all_pass_items(checklist)
    items[-1] = {
        "item_id": last_item["item_id"],
        "result": "FAIL",
        "remark": "ทดสอบ",
        "evidence_attachment_ids": ["ATT-9999"],
    }
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_inspection_for_unknown_vehicle_returns_controlled_404(
    client: AsyncClient,
) -> None:
    checklist = await _active_vehicle_checklist(client)
    response = await client.post(
        "/api/v1/inspections",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-9999",
            "items": _all_pass_items(checklist),
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_submit_inspection_for_unknown_equipment_returns_controlled_404(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/checklists/active", params={"asset_type": "EQUIPMENT"})
    checklist = response.json()
    response = await client.post(
        "/api/v1/inspections",
        json={
            "asset_type": "EQUIPMENT",
            "asset_id": "EQP-9999",
            "items": _all_pass_items(checklist),
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EQUIPMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_submit_inspection_for_equipment_uses_same_engine(client: AsyncClient) -> None:
    response = await client.get("/api/v1/checklists/active", params={"asset_type": "EQUIPMENT"})
    checklist = response.json()
    items = [{"item_id": item["item_id"], "result": "PASS"} for item in checklist["items"]]
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001", "items": items},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["header"]["asset_type"] == "EQUIPMENT"
    assert body["header"]["asset_id"] == "EQP-0001"


@pytest.mark.asyncio
async def test_get_inspection_returns_immutable_submission(client: AsyncClient) -> None:
    checklist = await _active_vehicle_checklist(client)
    submit = await client.post(
        "/api/v1/inspections",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "items": _all_pass_items(checklist),
        },
    )
    inspection_id = submit.json()["header"]["inspection_id"]

    response = await client.get(f"/api/v1/inspections/{inspection_id}")
    assert response.status_code == 200
    assert response.json() == submit.json()


@pytest.mark.asyncio
async def test_get_inspection_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/inspections/INS-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INSPECTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_inspections_filters_by_asset(client: AsyncClient) -> None:
    vehicle_checklist = await _active_vehicle_checklist(client)
    await client.post(
        "/api/v1/inspections",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "items": _all_pass_items(vehicle_checklist),
        },
    )
    await client.post(
        "/api/v1/inspections",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1047",
            "items": _all_pass_items(vehicle_checklist),
        },
    )

    response = await client.get(
        "/api/v1/inspections", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["asset_id"] == "VEH-1046"
    assert body["items"][0]["pass_count"] == 5
    assert body["items"][0]["fail_count"] == 0
    assert body["items"][0]["has_fail"] is False


@pytest.mark.asyncio
async def test_attachment_download_roundtrip(client: AsyncClient) -> None:
    files = {"file": ("evidence.jpg", b"roundtrip-bytes", "image/jpeg")}
    upload = await client.post(
        "/api/v1/attachments",
        data={
            "purpose": "INSPECTION_EVIDENCE",
            "source_type": "INSPECTION_VEHICLE",
            "source_id": "VEH-1046",
        },
        files=files,
    )
    attachment_id = upload.json()["attachment_id"]

    response = await client.get(f"/api/v1/attachments/{attachment_id}/file")
    assert response.status_code == 200
    assert response.content == b"roundtrip-bytes"
    assert response.headers["content-type"].startswith("image/jpeg")


@pytest.mark.asyncio
async def test_attachment_download_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/attachments/ATT-9999/file")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"
