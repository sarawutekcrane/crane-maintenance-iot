"""R6 — Part Master identity / lifecycle, Part Set alternatives, model
applicability (AP-17) and the read-only expected-vs-actual view of a PM work
order (FINAL plan §8, J1–J3). No real catalogue, compatibility or kit content
exists: every value is synthetic TEST data."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def rid() -> dict:
    return {"X-Request-Id": str(uuid.uuid4())}


async def part_set(client: AsyncClient) -> str:
    r = await client.post("/api/v1/part-sets", json={"set_code": f"KIT-{uuid.uuid4()}", "name": "ชุดทดสอบ"})
    return r.json()["part_set_id"]


@pytest.mark.asyncio
async def test_part_code_is_unique_and_master_create_is_idempotent(client: AsyncClient) -> None:
    body = {"part_code": "R6-UNIQ-1", "name": "ทดสอบ", "tracking_mode": "CONSUMABLE"}
    headers = rid()
    first = await client.post("/api/v1/parts", json=body, headers=headers)
    assert first.status_code == 200
    assert (await client.post("/api/v1/parts", json=body, headers=headers)).json() == first.json()
    dup = await client.post("/api/v1/parts", json=body | {"name": "อื่น"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "PART_CODE_DUPLICATE"
    same_name_other_spec = await client.post("/api/v1/parts", json={"part_code": "R6-UNIQ-2", "name": "ทดสอบ",
                                                                   "specification": "อีกสเปก",
                                                                   "tracking_mode": "CONSUMABLE"})
    assert same_name_other_spec.status_code == 200
    assert same_name_other_spec.json()["part_id"] != first.json()["part_id"]


@pytest.mark.asyncio
async def test_deactivate_keeps_history_blocks_new_instances_and_can_be_reversed(client: AsyncClient) -> None:
    created = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": "PART-0005", "tag_label": "TAG-DEACT", "prior_usage": {"quality": "UNKNOWN"}})
    off = await client.post("/api/v1/parts/PART-0005/deactivate", json={"reason": "เลิกใช้ (ทดสอบ)"}, headers=rid())
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert off.json()["metadata"]["last_active_change_reason"] == "เลิกใช้ (ทดสอบ)"
    assert (await client.get(f"/api/v1/part-instances/{created.json()['instance']['part_instance_id']}")).status_code == 200
    blocked = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": "PART-0005", "prior_usage": {"quality": "UNKNOWN"}})
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "PART_INACTIVE"
    again = await client.post("/api/v1/parts/PART-0005/deactivate", json={"reason": "x"}, headers=rid())
    assert again.status_code == 409
    on = await client.post("/api/v1/parts/PART-0005/reactivate", json={"reason": "ใช้ต่อ"}, headers=rid())
    assert on.status_code == 200 and on.json()["is_active"] is True
    assert (await client.post("/api/v1/parts/PART-9999/deactivate", json={"reason": "x"},
                              headers=rid())).status_code == 404


@pytest.mark.asyncio
async def test_an_alternative_line_must_name_the_line_it_substitutes(client: AsyncClient) -> None:
    psid = await part_set(client)
    orphan = await client.post(f"/api/v1/part-sets/{psid}/revisions", json={"effective_date": "2026-01-01", "items": [
        {"part_id": "PART-0002", "requirement": "REQUIRED"}, {"part_id": "PART-0003", "requirement": "ALTERNATIVE"}]})
    assert orphan.status_code == 422 and orphan.json()["error"]["code"] == "PART_SET_ALTERNATIVE_UNLINKED"
    alt_of_alt = await client.post(f"/api/v1/part-sets/{psid}/revisions", json={"effective_date": "2026-01-01", "items": [
        {"part_id": "PART-0003", "requirement": "ALTERNATIVE", "alternative_for_index": 1},
        {"part_id": "PART-0002", "requirement": "ALTERNATIVE", "alternative_for_index": 0}]})
    assert alt_of_alt.status_code == 422
    linked = await client.post(f"/api/v1/part-sets/{psid}/revisions", json={"effective_date": "2026-01-01", "items": [
        {"part_id": "PART-0002", "requirement": "REQUIRED", "quantity": 1, "unit": "ชิ้น"},
        {"part_id": "PART-0003", "requirement": "ALTERNATIVE", "alternative_for_index": 0},
        {"part_id": "PART-0001", "requirement": "OPTIONAL"}]})
    assert linked.status_code == 200, linked.text
    items = linked.json()["items"]
    required = next(i for i in items if i["requirement"] == "REQUIRED")
    alternative = next(i for i in items if i["requirement"] == "ALTERNATIVE")
    assert alternative["alternative_for_item_id"] == required["part_set_item_id"]
    assert all(i["alternative_for_item_id"] is None for i in items if i["requirement"] != "ALTERNATIVE")


@pytest.mark.asyncio
async def test_applicability_is_explicit_per_model_and_idempotent(client: AsyncClient) -> None:
    psid = await part_set(client)
    headers = rid()
    body = {"model_id": "MODEL-0003", "effective_from": "2026-01-01", "document_ref": "TEST-DOC"}
    first = await client.post(f"/api/v1/part-sets/{psid}/applicability", json=body, headers=headers)
    assert first.status_code == 200 and first.json()["approved_by"] == "dev-user"
    assert (await client.post(f"/api/v1/part-sets/{psid}/applicability", json=body, headers=headers)).json() == first.json()
    dup = await client.post(f"/api/v1/part-sets/{psid}/applicability", json=body, headers=rid())
    assert dup.status_code == 409
    missing_model = await client.post(f"/api/v1/part-sets/{psid}/applicability", headers=rid(),
                                      json={"model_id": "MODEL-9999", "effective_from": "2026-01-01"})
    assert missing_model.status_code == 404
    listed = (await client.get(f"/api/v1/part-sets/{psid}/applicability")).json()
    assert [r["model_id"] for r in listed] == ["MODEL-0003"]


async def _pm_work_order(client: AsyncClient, vehicle: str) -> str:
    r = await client.post("/api/v1/pm/work-orders", json={"asset_type": "VEHICLE", "asset_id": vehicle,
                                                          "pm_plan_id": "PMP-0001"})
    assert r.status_code == 200, r.text
    return r.json()["work_order"]["pm_work_order_id"]


@pytest.mark.asyncio
async def test_expected_part_sets_follow_model_applicability_only(client: AsyncClient) -> None:
    """AP-17: model A's set never applies to model B (VEH-1048 = MODEL-0003,
    VEH-1047 = MODEL-0002), and the view is read-only."""
    psid = await part_set(client)
    await client.post(f"/api/v1/part-sets/{psid}/revisions", json={"effective_date": "2026-01-01", "items": [
        {"part_id": "PART-0002", "requirement": "REQUIRED", "quantity": 1}]})
    await client.post(f"/api/v1/part-sets/{psid}/applicability", headers=rid(),
                      json={"model_id": "MODEL-0003", "effective_from": "2026-01-01"})
    wo_a = await _pm_work_order(client, "VEH-1048")
    expected = (await client.get(f"/api/v1/pm/work-orders/{wo_a}/expected-part-sets")).json()
    assert expected["status"] == "KNOWN" and expected["model_id"] == "MODEL-0003"
    assert [s["part_set_id"] for s in expected["sets"]] == [psid]
    assert expected["sets"][0]["items"][0]["part_id"] == "PART-0002"
    wo_b = await _pm_work_order(client, "VEH-1047")
    other = (await client.get(f"/api/v1/pm/work-orders/{wo_b}/expected-part-sets")).json()
    assert other["status"] == "UNKNOWN" and other["reason"] == "NO_APPLICABLE_PART_SET" and other["sets"] == []
    detail_before = (await client.get(f"/api/v1/pm/work-orders/{wo_a}")).json()
    await client.get(f"/api/v1/pm/work-orders/{wo_a}/expected-part-sets")
    assert (await client.get(f"/api/v1/pm/work-orders/{wo_a}")).json() == detail_before
    assert (await client.get("/api/v1/pm/work-orders/PMWO-NOPE/expected-part-sets")).status_code == 404
