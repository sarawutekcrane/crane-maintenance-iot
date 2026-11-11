"""R6 cross-phase regression (FINAL plan §11, §13): the only R4 / R5 code paths
R6 touches are the instance-of-part consistency checks on actual PM / Repair /
Material-request part records and a separate read-only expected-sets route.
Recording `action=INSTALLED` on an actual-part record stays descriptive: it
never creates an installation segment or touches a lifecycle."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.pm_e01_support import http_save, http_start

V = "VEH-1048"


def rid() -> dict:
    return {"X-Request-Id": str(uuid.uuid4())}


async def instance_of(client: AsyncClient, part_id: str = "PART-0005") -> str:
    r = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": part_id, "tag_label": f"TAG-{uuid.uuid4()}", "prior_usage": {"quality": "UNKNOWN"}})
    assert r.status_code == 200, r.text
    return r.json()["instance"]["part_instance_id"]


async def repair(client: AsyncClient) -> str:
    r = await client.post("/api/v1/repairs", json={"asset_type": "VEHICLE", "asset_id": V, "source_type": "MANUAL",
                                                  "symptom": "ทดสอบ"})
    return r.json()["repair"]["repair_id"]


@pytest.mark.asyncio
async def test_repair_part_must_name_an_instance_of_that_part(client: AsyncClient) -> None:
    rid_ = await repair(client)
    iid = await instance_of(client)
    mismatch = await client.post(f"/api/v1/repairs/{rid_}/parts", json={
        "part_description": "ปั๊ม", "quantity": 1, "part_id": "PART-0002", "part_instance_id": iid,
        "action": "INSTALLED"})
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "PART_INSTANCE_PART_MISMATCH"
    ok = await client.post(f"/api/v1/repairs/{rid_}/parts", json={
        "part_description": "ปั๊ม", "quantity": 1, "part_id": "PART-0005", "part_instance_id": iid,
        "action": "INSTALLED"})
    assert ok.status_code == 200, ok.text
    # Descriptive only: no installation segment, no lifecycle change.
    detail = (await client.get(f"/api/v1/part-instances/{iid}")).json()
    assert detail["segments"] == [] and len(detail["lifecycles"]) == 1
    assert detail["instance"]["status"] == "READY_FOR_INSTALL"


@pytest.mark.asyncio
async def test_material_request_line_must_name_an_instance_of_that_part(client: AsyncClient) -> None:
    rid_ = await repair(client)
    iid = await instance_of(client)
    r = await client.post("/api/v1/material-requests", json={
        "source_type": "REPAIR", "source_work_order_id": rid_, "asset_type": "VEHICLE", "asset_id": V,
        "lines": [{"part_description": "x", "part_id": "PART-0002", "part_instance_id": iid}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "PART_INSTANCE_PART_MISMATCH"


@pytest.mark.asyncio
async def test_pm_used_part_must_name_an_instance_of_that_part(client: AsyncClient) -> None:
    created = await client.post("/api/v1/pm/work-orders", json={"asset_type": "VEHICLE", "asset_id": V,
                                                                "pm_plan_id": "PMP-0001"})
    wo = created.json()["work_order"]["pm_work_order_id"]
    await http_start(client, wo)
    detail = (await client.get(f"/api/v1/pm/work-orders/{wo}")).json()
    task_id = detail["work_order"]["scope_task_ids"][0]
    iid = await instance_of(client)
    r = await http_save(client, wo, task_id, used_parts=[
        {"part_description": "x", "part_id": "PART-0002", "part_instance_id": iid}])
    assert r.status_code == 422 and r.json()["error"]["code"] == "PART_INSTANCE_PART_MISMATCH"


@pytest.mark.asyncio
async def test_pm_due_and_the_r4_meter_source_are_unchanged(client: AsyncClient) -> None:
    """R4 Fleet PM Due keeps its own source (runtime NO_IOT): recording an A-4
    TEST-only part reading never makes a PM Set due or known."""
    before = await client.get(f"/api/v1/vehicles/{V}/pm/due")
    from app.dependencies import get_repository

    comp = next(c.component_id for c in await get_repository().list_vehicle_components(V)
                if c.component_role.value == "CARRIER_ENGINE")
    await client.post("/api/v1/test-support/part-meter-observations", headers=rid(), json={
        "vehicle_id": V, "component_id": comp, "counter_type": "ENGINE_HOUR", "value": 99999})
    after = await client.get(f"/api/v1/vehicles/{V}/pm/due")
    assert before.status_code == after.status_code
    assert before.json() == after.json() or before.status_code != 200


@pytest.mark.asyncio
async def test_r5_repair_part_retry_safety_is_preserved(client: AsyncClient) -> None:
    rid_ = await repair(client)
    headers = rid()
    body = {"part_description": "สายไฮดรอลิก", "quantity": 1, "part_id": "PART-0002"}
    first = await client.post(f"/api/v1/repairs/{rid_}/parts", json=body, headers=headers)
    again = await client.post(f"/api/v1/repairs/{rid_}/parts", json=body, headers=headers)
    assert first.status_code == again.status_code == 200
    assert len(again.json()["parts"]) == len(first.json()["parts"]) == 1
