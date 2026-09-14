"""Core Demo Fixes Delta (REV03 alignment) — proves the delta's new/changed
behaviors on top of the 8 existing Core Demo Fixes checkpoints, without
redoing or rewriting any of that prior work:

  A/B  repair + PM technician assignment references `user_account.user_id`
       (no separate technician master), append-only non-destructive history
  C    PM scope: same-plan-only enforcement, frozen after approval even
       across master/source edits
  D    PM auto requisition (one `material_request` header + lines from
       standard PM task parts), quantities stay separate/nullable
  E    GPS/location snapshot: automatic, immutable, honestly-null when no
       live source exists
  G    technician identity is a plain `user_account.user_id` string
  H    "waiting for parts" is a derived indicator — no duplicate table/enum
  I    model -> one assigned PM plan (delegated to
       test_pm_plan_assignment_and_scope.py; not repeated here)

Google Sheets schema-name alignment (B01/B03 both remain TBD-BLOCKING — no
live Google API I/O exists anywhere in this repository) is exercised
separately in test_google_sheets_repository.py.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.dependencies import get_repository
from app.domain.pm import PmTask, PmTaskPart, PmTaskRevision


async def _open_work_order(client: AsyncClient, vehicle_id: str = "VEH-1046") -> dict:
    plans = await client.get(
        "/api/v1/pm/plans/status", params={"asset_type": "VEHICLE", "asset_id": vehicle_id}
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "pm_plan_id": plan_id},
    )
    assert response.status_code == 200
    return response.json()


async def _create_repair(client: AsyncClient, vehicle_id: str = "VEH-1046") -> dict:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "source_type": "MANUAL"},
    )
    assert response.status_code == 200
    return response.json()["repair"]


# ---------------------------------------------------------------------------
# G — technician identity: a plain opaque user_id string, never a separate
# technician master (mirrors app.context.RequestContext.user_id).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_technician_identity_is_a_plain_opaque_user_id_no_technician_master(
    client: AsyncClient,
) -> None:
    repair = await _create_repair(client)
    response = await client.post(
        f"/api/v1/repairs/{repair['repair_id']}/assign",
        json={"primary_technician": "user-somchai-01", "collaborators": ["user-anan-02"]},
    )
    assert response.status_code == 200
    updated = response.json()["repair"]
    # Whatever string is supplied is stored/returned verbatim — no lookup
    # against, validation against, or enrichment from a fabricated
    # technician master exists.
    assert updated["primary_technician"] == "user-somchai-01"
    assert updated["collaborators"] == ["user-anan-02"]

    # No technician-master repository method or Google Sheets tab exists.
    from app.repositories import base as repository_base
    from app.repositories.google_sheets import schemas as sheet_schemas

    assert not any("technician" in name.lower() for name in dir(repository_base.Repository))
    assert not any(
        "technician" in getattr(value, "tab_name", "").lower()
        for value in vars(sheet_schemas).values()
        if hasattr(value, "tab_name")
    )


# ---------------------------------------------------------------------------
# A/B — append-only, non-destructive assignment history (repair + PM).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_reassignment_ends_previous_history_rows_instead_of_deleting(
    client: AsyncClient,
) -> None:
    repair = await _create_repair(client)
    repair_id = repair["repair_id"]

    first = await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "user-a", "collaborators": []},
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "user-b", "collaborators": []},
    )
    assert second.status_code == 200

    history = await client.get(f"/api/v1/repairs/{repair_id}/assignment-history")
    assert history.status_code == 200
    entries = history.json()

    # Both the ended and the new assignment rows remain readable — nothing
    # was deleted.
    user_a_entries = [e for e in entries if e["user_id"] == "user-a"]
    user_b_entries = [e for e in entries if e["user_id"] == "user-b"]
    assert len(user_a_entries) == 1
    assert user_a_entries[0]["active_status"] is False
    assert user_a_entries[0]["ended_at"] is not None
    assert len(user_b_entries) == 1
    assert user_b_entries[0]["active_status"] is True
    assert user_b_entries[0]["ended_at"] is None


@pytest.mark.asyncio
async def test_pm_reassignment_ends_previous_history_rows_instead_of_deleting(
    client: AsyncClient,
) -> None:
    detail = await _open_work_order(client)
    work_order_id = detail["work_order"]["pm_work_order_id"]

    first = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-a", "collaborators": []},
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "user-b", "collaborators": []},
    )
    assert second.status_code == 200

    history = await client.get(f"/api/v1/pm/work-orders/{work_order_id}/assignment-history")
    assert history.status_code == 200
    entries = history.json()
    user_a_entries = [e for e in entries if e["user_id"] == "user-a"]
    user_b_entries = [e for e in entries if e["user_id"] == "user-b"]
    assert len(user_a_entries) == 1
    assert user_a_entries[0]["active_status"] is False
    assert len(user_b_entries) == 1
    assert user_b_entries[0]["active_status"] is True


# ---------------------------------------------------------------------------
# C — same-plan-only scope enforcement + frozen-after-approval, even across
# a subsequent master/source-data edit.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pm_scope_addition_rejects_a_task_from_a_different_plan(
    client: AsyncClient,
) -> None:
    detail = await _open_work_order(client)
    work_order_id = detail["work_order"]["pm_work_order_id"]

    # Inject a second plan/revision/task directly into the shared repository
    # instance (same test-local technique test_pm_plan_and_task_revision.py
    # uses) so a real "different plan" task id exists to attempt cross-plan
    # addition with — no fabricated PLAN2 seed data is added.
    repo = get_repository()
    other_revision = PmTaskRevision(
        revision_id="PMREV-OTHERPLAN",
        pm_plan_id="PMP-OTHERPLAN",
        revision_number=1,
        effective_date=repo._pm_task_revisions["PMREV-0001"].effective_date,  # type: ignore[attr-defined]
        created_at=repo._pm_task_revisions["PMREV-0001"].created_at,  # type: ignore[attr-defined]
    )
    repo._pm_task_revisions["PMREV-OTHERPLAN"] = other_revision  # type: ignore[attr-defined]
    repo._pm_tasks["PMREV-OTHERPLAN"] = [  # type: ignore[attr-defined]
        PmTask(
            pm_task_id="PMT-OTHERPLAN-1",
            revision_id="PMREV-OTHERPLAN",
            sequence=1,
            description="งานจากแผนอื่น (ทดสอบเท่านั้น)",
        )
    ]

    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/scope/add",
        json={"pm_task_id": "PMT-OTHERPLAN-1", "reason": "ทดสอบการเพิ่มขอบเขตข้ามแผน"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_pm_scope_stays_frozen_after_approval_even_when_master_is_later_edited(
    client: AsyncClient,
) -> None:
    detail = await _open_work_order(client)
    work_order = detail["work_order"]
    work_order_id = work_order["pm_work_order_id"]
    original_task_ids = set(work_order["scope_task_ids"])

    approve = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/scope/approve")
    assert approve.status_code == 200
    approved_at = approve.json()["work_order"]["scope_approved_at"]
    assert approved_at is not None

    # Simulate a later PM-authoring edit to the plan's active task revision
    # (adds a brand-new task) on the shared repository instance — this must
    # never reopen or extend the already-approved, frozen work order scope.
    repo = get_repository()
    revision_id = work_order["revision_id"]
    repo._pm_tasks[revision_id].append(  # type: ignore[attr-defined]
        PmTask(
            pm_task_id="PMT-ADDED-AFTER-APPROVAL",
            revision_id=revision_id,
            sequence=99,
            description="งานที่เพิ่มเข้ามาใหม่หลังอนุมัติขอบเขต (ทดสอบเท่านั้น)",
        )
    )

    reread = await client.get(f"/api/v1/pm/work-orders/{work_order_id}")
    assert reread.status_code == 200
    body = reread.json()["work_order"]
    assert body["scope_approved_at"] == approved_at
    assert set(body["scope_task_ids"]) == original_task_ids
    assert "PMT-ADDED-AFTER-APPROVAL" not in body["scope_task_ids"]

    # And addition is still rejected outright because scope is approved.
    add_after = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/scope/add",
        json={"pm_task_id": "PMT-ADDED-AFTER-APPROVAL", "reason": "ทดสอบ"},
    )
    assert add_after.status_code == 422
    assert add_after.json()["error"]["code"] == "PM_SCOPE_ALREADY_APPROVED"


# ---------------------------------------------------------------------------
# D — PM auto requisition: one material_request header + lines generated
# from each in-scope task's standard PmTaskPart list; quantities stay
# separate/nullable columns. No PmTaskPart seed data exists anywhere (no
# authoritative PM task-part source data — see seed_data.py's SOURCE DATA
# RULE), so a synthetic PmTaskPart is injected the same way
# test_pm_plan_and_task_revision.py injects a synthetic task/revision.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pm_scope_approval_with_no_standard_parts_creates_no_material_request(
    client: AsyncClient,
) -> None:
    """Baseline (unmodified seed data — no standard parts exist for
    PLAN1): approving scope must not fabricate a header with zero lines."""
    detail = await _open_work_order(client)
    work_order_id = detail["work_order"]["pm_work_order_id"]
    await client.post(f"/api/v1/pm/work-orders/{work_order_id}/scope/approve")

    requests = await client.get(f"/api/v1/material-requests/by-work-order/{work_order_id}")
    assert requests.status_code == 200
    assert requests.json() == []


@pytest.mark.asyncio
async def test_pm_scope_approval_with_standard_parts_creates_one_header_with_lines(
    client: AsyncClient,
) -> None:
    repo = get_repository()
    revision_id = "PMREV-0001"
    task_with_part = PmTask(
        pm_task_id="PMT-WITH-STANDARD-PART",
        revision_id=revision_id,
        sequence=98,
        description="งานที่มีอะไหล่มาตรฐาน (ทดสอบเท่านั้น)",
        standard_parts=[
            PmTaskPart(
                pm_task_part_id="PMTP-TEST-0001",
                pm_task_id="PMT-WITH-STANDARD-PART",
                part_description="ไส้กรองน้ำมันเครื่อง (ทดสอบ)",
                quantity=2,
                unit="ชิ้น",
                part_id=None,
            )
        ],
    )
    repo._pm_tasks[revision_id].append(task_with_part)  # type: ignore[attr-defined]

    detail = await _open_work_order(client)
    work_order = detail["work_order"]
    work_order_id = work_order["pm_work_order_id"]
    assert "PMT-WITH-STANDARD-PART" in work_order["scope_task_ids"]

    approve = await client.post(f"/api/v1/pm/work-orders/{work_order_id}/scope/approve")
    assert approve.status_code == 200

    requests = await client.get(f"/api/v1/material-requests/by-work-order/{work_order_id}")
    assert requests.status_code == 200
    request_list = requests.json()
    # Exactly one header — never one row per line.
    assert len(request_list) == 1
    header = request_list[0]
    assert header["source_type"] == "PM"
    assert header["source_work_order_id"] == work_order_id
    assert header["vehicle_id"] == "VEH-1046"
    assert header["request_status"] == "OPEN"

    material_request_detail = await client.get(f"/api/v1/material-requests/{header['material_request_id']}")
    assert material_request_detail.status_code == 200
    lines = material_request_detail.json()["lines"]
    matching = [line for line in lines if line["part_description"] == "ไส้กรองน้ำมันเครื่อง (ทดสอบ)"]
    assert len(matching) == 1
    line = matching[0]
    assert line["material_request_id"] == header["material_request_id"]
    assert line["source_task_revision_id"] == revision_id
    assert line["requested_quantity"] == 2
    assert line["unit"] == "ชิ้น"
    assert line["line_source"] == "PM_STANDARD"

    # Requested/approved/issued/used/returned quantities remain separate,
    # nullable columns — approving scope never fabricates a store approval.
    assert line["approved_quantity"] is None
    assert line["issued_quantity"] is None
    assert line["used_quantity"] is None
    assert line["returned_quantity"] is None


@pytest.mark.asyncio
async def test_explicit_repair_material_request_quantities_stay_separate_and_nullable(
    client: AsyncClient,
) -> None:
    repair = await _create_repair(client)
    response = await client.post(
        "/api/v1/material-requests",
        json={
            "source_type": "REPAIR",
            "source_work_order_id": repair["repair_id"],
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "lines": [{"part_description": "ปะเก็นยาง (ทดสอบ)", "quantity": 4, "unit": "ชิ้น"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["request"]["source_type"] == "REPAIR"
    line = body["lines"][0]
    assert line["requested_quantity"] == 4
    assert line["approved_quantity"] is None
    assert line["issued_quantity"] is None
    assert line["used_quantity"] is None
    assert line["returned_quantity"] is None
    assert line["line_source"] == "REPAIR_UNREGISTERED"


# ---------------------------------------------------------------------------
# H — "waiting for parts" (งานรออะไหล่) is a derived indicator only: no
# separate stored table, no duplicated repair record, no new lifecycle enum.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_awaiting_parts_is_derived_and_never_a_stored_table_or_new_status(
    client: AsyncClient,
) -> None:
    repair = await _create_repair(client)
    repair_id = repair["repair_id"]

    before = await client.get(f"/api/v1/repairs/{repair_id}")
    assert before.status_code == 200
    assert before.json()["awaiting_parts"] is False

    await client.post(
        "/api/v1/material-requests",
        json={
            "source_type": "REPAIR",
            "source_work_order_id": repair_id,
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "lines": [{"part_description": "สายพาน (ทดสอบ)", "quantity": 1, "unit": "เส้น"}],
        },
    )

    after = await client.get(f"/api/v1/repairs/{repair_id}")
    assert after.status_code == 200
    after_body = after.json()
    assert after_body["awaiting_parts"] is True
    # The repair record itself is completely unduplicated/unaffected.
    body = after_body["repair"]
    assert body["status"] == "OPEN"
    assert body["repair_id"] == repair_id

    # No new repair lifecycle status exists to represent this.
    from app.domain.repair import RepairStatus

    assert {member.value for member in RepairStatus} == {"OPEN", "CLOSED"}

    # No dedicated waiting_parts table/schema exists anywhere.
    from app.repositories.google_sheets import schemas as sheet_schemas

    assert not any(
        "waiting" in getattr(value, "tab_name", "").lower()
        for value in vars(sheet_schemas).values()
        if hasattr(value, "tab_name")
    )


# ---------------------------------------------------------------------------
# E — GPS/location snapshot: automatic (no browser-typed field), immutable,
# linked to the same event as the counter snapshot, honestly null/unknown
# rather than a fabricated 0,0 when no live GPS source exists.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_creation_automatically_captures_a_linked_location_snapshot(
    client: AsyncClient,
) -> None:
    repair = await _create_repair(client)
    meter_snapshot_id = repair["meter_snapshot_id"]
    assert meter_snapshot_id is not None

    snapshots = await client.get(f"/api/v1/location-snapshots/by-event/{meter_snapshot_id}")
    assert snapshots.status_code == 200
    items = snapshots.json()
    assert len(items) == 1
    snapshot = items[0]
    assert snapshot["event_id"] == meter_snapshot_id
    assert snapshot["vehicle_id"] == "VEH-1046"
    assert snapshot["event_type"] == "REPAIR_OPEN"

    direct = await client.get(f"/api/v1/location-snapshots/{snapshot['location_snapshot_id']}")
    assert direct.status_code == 200
    assert direct.json() == snapshot


@pytest.mark.asyncio
async def test_location_snapshot_stays_honestly_null_when_no_live_gps_source_exists(
    client: AsyncClient,
) -> None:
    """No live GPS/device ingestion exists anywhere in this branch — a
    missing reading must come back as None/False, never a fabricated
    `0, 0` coordinate or a fabricated "valid" flag."""
    repair = await _create_repair(client)
    snapshots = await client.get(
        f"/api/v1/location-snapshots/by-event/{repair['meter_snapshot_id']}"
    )
    snapshot = snapshots.json()[0]
    assert snapshot["latitude"] is None
    assert snapshot["longitude"] is None
    assert snapshot["altitude_m"] is None
    assert snapshot["accuracy_m"] is None
    assert snapshot["gps_time"] is None
    assert snapshot["gps_valid"] is False
    assert snapshot["source"] is None


@pytest.mark.asyncio
async def test_equipment_asset_never_gets_a_fabricated_location_snapshot(
    client: AsyncClient,
) -> None:
    equipment = await client.get("/api/v1/equipment")
    equipment_id = equipment.json()["items"][0]["equipment_id"]
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "EQUIPMENT", "asset_id": equipment_id, "source_type": "MANUAL"},
    )
    assert repair.status_code == 200
    meter_snapshot_id = repair.json()["repair"]["meter_snapshot_id"]

    snapshots = await client.get(f"/api/v1/location-snapshots/by-event/{meter_snapshot_id}")
    assert snapshots.status_code == 200
    assert snapshots.json() == []
