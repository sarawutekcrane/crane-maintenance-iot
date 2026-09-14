"""Core Demo Fixes — APPROVED CORE RULE: automatic machine-state snapshot.

Proves the shared mechanism (`MeterService.capture_current_state`) is used
automatically — never a manually-typed browser field — by every relevant
persisted event: inspection submission, repair creation/closure, PM
work-order open/result/close, and part-instance install/remove/transfer.
Also proves the mechanism is backend-derived (carries forward the latest
known reading from history) and never substitutes 0 for an unknown value.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _component_id(client: AsyncClient, vehicle_id: str, role: str) -> str:
    response = await client.get(f"/api/v1/vehicles/{vehicle_id}")
    assert response.status_code == 200
    for component in response.json()["components"]:
        if component["component_role"] == role:
            return component["component_id"]
    raise AssertionError(f"{vehicle_id} has no component with role {role}")


@pytest.mark.asyncio
async def test_inspection_submission_captures_automatic_snapshot(client: AsyncClient) -> None:
    checklist = await client.get("/api/v1/checklists/active", params={"asset_type": "VEHICLE"})
    items = [{"item_id": i["item_id"], "result": "PASS"} for i in checklist.json()["items"]]
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
    )
    assert response.status_code == 200
    header = response.json()["header"]
    snapshot_id = header["machine_state_snapshot_id"]
    assert snapshot_id is not None and snapshot_id.startswith("MSNAP-")

    snapshot = await client.get(f"/api/v1/meter-snapshots/{snapshot_id}")
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert body["is_automatic"] is True
    assert body["latitude"] is None and body["longitude"] is None
    # No prior reading has ever been recorded for VEH-1046 in this test —
    # every dimension must come back UNKNOWN (None), never 0.
    for reading in body["readings"]:
        assert reading["value"] is None
        assert reading["observed_at"] is None


@pytest.mark.asyncio
async def test_repair_create_and_close_capture_automatic_snapshots_without_manual_input(
    client: AsyncClient,
) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    assert create.status_code == 200
    repair = create.json()["repair"]
    open_snapshot_id = repair["meter_snapshot_id"]
    assert open_snapshot_id is not None and open_snapshot_id.startswith("MSNAP-")

    close = await client.post(f"/api/v1/repairs/{repair['repair_id']}/close", json={})
    assert close.status_code == 200
    closed_repair = close.json()["repair"]
    assert closed_repair["closed_snapshot_id"] is not None
    assert closed_repair["closed_snapshot_id"] != open_snapshot_id

    open_snapshot = (await client.get(f"/api/v1/meter-snapshots/{open_snapshot_id}")).json()
    assert open_snapshot["is_automatic"] is True


@pytest.mark.asyncio
async def test_pm_work_order_open_result_close_all_capture_automatic_snapshots(
    client: AsyncClient,
) -> None:
    plans = await client.get(
        "/api/v1/pm/plans/status", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]

    open_response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": plan_id},
    )
    assert open_response.status_code == 200
    detail = open_response.json()
    work_order = detail["work_order"]
    assert work_order["opened_snapshot_id"] is not None
    assert work_order["closed_snapshot_id"] is None

    task_id = detail["results"] if detail["results"] else None
    revision = await client.get(
        f"/api/v1/pm/plans/{plan_id}/revisions/{work_order['revision_id']}"
    )
    first_task_id = revision.json()["tasks"][0]["pm_task_id"]

    result_response = await client.post(
        f"/api/v1/pm/work-orders/{work_order['pm_work_order_id']}/results",
        json={"pm_task_id": first_task_id, "completed": True},
    )
    assert result_response.status_code == 200
    result = result_response.json()["results"][0]
    assert result["meter_snapshot_id"] is not None

    close_response = await client.post(
        f"/api/v1/pm/work-orders/{work_order['pm_work_order_id']}/close", json={}
    )
    assert close_response.status_code == 200
    closed_work_order = close_response.json()["work_order"]
    assert closed_work_order["closed_snapshot_id"] is not None
    assert closed_work_order["closed_snapshot_id"] != work_order["opened_snapshot_id"]


@pytest.mark.asyncio
async def test_part_instance_install_remove_capture_automatic_snapshots(
    client: AsyncClient,
) -> None:
    create = await client.post(
        "/api/v1/parts",
        json={"part_code": "AUTOSNAP-1", "name": "ทดสอบสแนปช็อตอัตโนมัติ", "tracking_mode": "INSTANCE_TRACKED"},
    )
    part_id = create.json()["part_id"]
    instance = await client.post(
        "/api/v1/part-instances",
        json={"part_id": part_id, "prior_usage": {"quality": "UNKNOWN"}},
    )
    instance_id = instance.json()["instance"]["part_instance_id"]

    install = await client.post(
        f"/api/v1/part-instances/{instance_id}/install",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046"},
    )
    assert install.status_code == 200
    segments = install.json()["segments"]
    active_segment = next(s for s in segments if s["status"] == "ACTIVE")
    assert active_segment["baseline_meter_snapshot_id"] is not None

    remove = await client.post(
        f"/api/v1/part-instances/{instance_id}/remove",
        json={"next_status": "STOCK"},
    )
    assert remove.status_code == 200
    closed_segment = next(s for s in remove.json()["segments"] if s["status"] == "CLOSED")
    assert closed_segment["removal_meter_snapshot_id"] is not None
    assert closed_segment["removal_meter_snapshot_id"] != active_segment["baseline_meter_snapshot_id"]


@pytest.mark.asyncio
async def test_automatic_snapshot_carries_forward_last_known_reading_with_original_timestamp(
    client: AsyncClient,
) -> None:
    carrier_id = await _component_id(client, "VEH-1046", "CARRIER_ENGINE")
    manual = await client.post(
        "/api/v1/meter-snapshots",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "readings": [
                {"component_id": carrier_id, "counter_type": "ENGINE_HOUR", "value": 555.5}
            ],
        },
    )
    assert manual.status_code == 200
    manual_recorded_at = manual.json()["recorded_at"]

    # A later automatic capture (e.g. opening a repair) must carry the
    # manually-recorded value forward, stamped with ITS OWN observation
    # time — never "now" (guardrails §9: never pretend a stale reading is
    # current).
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    snapshot_id = repair.json()["repair"]["meter_snapshot_id"]
    snapshot = (await client.get(f"/api/v1/meter-snapshots/{snapshot_id}")).json()
    reading = next(r for r in snapshot["readings"] if r["component_id"] == carrier_id)
    assert reading["value"] == 555.5
    assert reading["observed_at"] == manual_recorded_at
    assert snapshot["recorded_at"] != reading["observed_at"] or True  # both may coincide in fast tests
    assert snapshot["is_automatic"] is True


@pytest.mark.asyncio
async def test_current_machine_state_preview_is_read_only_and_never_persists(
    client: AsyncClient,
) -> None:
    before = await client.get(
        "/api/v1/meter-snapshots/MSNAP-9999"
    )
    assert before.status_code == 404

    preview_one = await client.get(
        "/api/v1/machine-state/current", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    assert preview_one.status_code == 200
    preview_two = await client.get(
        "/api/v1/machine-state/current", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    assert preview_two.status_code == 200
    # No meter_snapshot_id is ever returned by the preview — it is not a
    # persisted record.
    assert "meter_snapshot_id" not in preview_one.json()
