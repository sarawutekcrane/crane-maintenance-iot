"""Core Demo Fixes Delta REV06 section 9/10 (P0) — real Google Sheets I/O
for the Repair Work Order subset the approved `Repair Request ->
Maintenance review -> RPR` conversion path actually needs.

REV05 left `create_repair`/`get_repair`/`list_repairs`/`assign_repair`/
`add_repair_action`/`add_repair_part`/`close_repair` as `NotImplementedError`
stubs in `GoogleSheetsRepository`, which meant `RepairRequestService.convert`
(which calls `RepairService.create_repair` -> `repository.create_repair`)
silently broke in `DATA_REPOSITORY=google_sheets` mode even though Repair
Request creation itself worked. These tests exercise the FAKE in-memory
`gspread`-shaped client from `tests.test_google_sheets_real_io` (never the
real Google API/network) to prove the actual repository domain path now
performs functioning Sheets I/O end to end.
"""
from __future__ import annotations

import pytest

from fastapi import HTTPException

from app.context import RequestContext
from app.domain.asset import AssetType
from app.domain.authz import CAN_MANAGE_REPAIR, require_assignment_or_capability
from app.domain.common import PageParams
from app.domain.meter_service import MeterService
from app.domain.repair import RepairSourceType, RepairStatus
from app.domain.repair_request_service import RepairRequestService
from app.domain.repair_service import RepairService
from app.repositories.google_sheets import schemas
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws

pytestmark = pytest.mark.asyncio


def _ctx(user_id: str, capabilities: frozenset[str] = frozenset()) -> RequestContext:
    return RequestContext(request_id="test", user_id=user_id, capabilities=capabilities)


def _repair_sheets():
    return (
        _ws(schemas.REPAIR_SHEET),
        _ws(schemas.REPAIR_ACTION_SHEET),
        _ws(schemas.REPAIR_PART_SHEET),
        _ws(schemas.REPAIR_ASSIGNMENT_SHEET),
    )


def _vehicle_row(vehicle_id: str = "VEH-9001") -> list:
    return [vehicle_id, "MC-9001", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]


# ---------------------------------------------------------------------------
# Repair CRUD round trip.
# ---------------------------------------------------------------------------


async def test_create_then_get_repair_round_trips_by_header_name() -> None:
    repair_ws, action_ws, part_ws, assignment_ws = _repair_sheets()
    repo = _repo_with_fake_sheets(repair_ws, action_ws, part_ws, assignment_ws)

    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category="ระบบไฮดรอลิก",
        symptom="รั่วซึม",
        meter_snapshot_id="MSNAP-0001",
        opened_by="user-maintenance",
    )
    assert repair.repair_id.startswith("RPR-")
    assert repair.status == RepairStatus.OPEN

    detail = await repo.get_repair(repair.repair_id)
    assert detail is not None
    assert detail.repair.asset_id == "VEH-9001"
    assert detail.repair.category == "ระบบไฮดรอลิก"
    assert detail.repair.symptom == "รั่วซึม"
    assert detail.repair.source_type == RepairSourceType.MANUAL
    assert detail.actions == []
    assert detail.parts == []


async def test_get_repair_returns_none_for_unknown_id() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    assert await repo.get_repair("RPR-9999") is None


async def test_create_repair_never_reuses_an_id_and_preserves_other_rows() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    first = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="อาการที่ 1",
        meter_snapshot_id=None,
        opened_by="user-a",
    )
    second = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9002",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="อาการที่ 2",
        meter_snapshot_id=None,
        opened_by="user-b",
    )
    assert first.repair_id != second.repair_id

    reread_first = await repo.get_repair(first.repair_id)
    assert reread_first.repair.symptom == "อาการที่ 1"
    reread_second = await repo.get_repair(second.repair_id)
    assert reread_second.repair.symptom == "อาการที่ 2"


# ---------------------------------------------------------------------------
# list_repairs filtering: asset, status, assigned_to, unassigned_only.
# ---------------------------------------------------------------------------


async def test_list_repairs_filters_by_status_and_assigned_to() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    open_unassigned = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="ไม่ได้มอบหมาย",
        meter_snapshot_id=None,
        opened_by="user-a",
    )
    assigned = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="มอบหมายแล้ว",
        meter_snapshot_id=None,
        opened_by="user-a",
        primary_technician="user-tech-1",
    )
    await repo.close_repair(assigned.repair_id, closed_by="user-a", close_note=None)

    open_items, open_total = await repo.list_repairs(
        asset_type=None, asset_id=None, status=RepairStatus.OPEN, params=PageParams(page=1, page_size=20)
    )
    assert open_total == 1
    assert open_items[0].repair_id == open_unassigned.repair_id

    unassigned_items, unassigned_total = await repo.list_repairs(
        asset_type=None,
        asset_id=None,
        status=RepairStatus.OPEN,
        params=PageParams(page=1, page_size=20),
        unassigned_only=True,
    )
    assert unassigned_total == 1
    assert unassigned_items[0].repair_id == open_unassigned.repair_id

    # Live UAT fix: closing a repair ends its active assignment, so
    # user-tech-1 is no longer authoritatively "assigned" to it (even
    # though `Repair.primary_technician` still shows them as a
    # compatibility/display value) — repair_assignment history, not
    # row status, is what `assigned_to` is derived from.
    mine_items, mine_total = await repo.list_repairs(
        asset_type=None,
        asset_id=None,
        status=None,
        params=PageParams(page=1, page_size=20),
        assigned_to="user-tech-1",
    )
    assert mine_total == 0


# ---------------------------------------------------------------------------
# assign_repair: append-only history, non-destructive reassignment.
# ---------------------------------------------------------------------------


async def test_assign_repair_creates_primary_and_collaborator_history_rows() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom=None,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair.repair_id,
        primary_technician="user-tech-1",
        collaborators=["user-tech-2"],
        assigned_by="user-maintenance",
    )

    detail = await repo.get_repair(repair.repair_id)
    assert detail.repair.primary_technician == "user-tech-1"
    assert detail.repair.collaborators == ["user-tech-2"]

    history = await repo.list_repair_assignment_history(repair.repair_id)
    assert len(history) == 2
    roles = {(h.user_id, h.assignment_role.value) for h in history}
    assert roles == {("user-tech-1", "PRIMARY"), ("user-tech-2", "COLLABORATOR")}
    assert all(h.active_status for h in history)


async def test_reassignment_ends_previous_history_rows_without_deleting_them() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom=None,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair.repair_id,
        primary_technician="user-tech-1",
        collaborators=[],
        assigned_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair.repair_id,
        primary_technician="user-tech-2",
        collaborators=[],
        assigned_by="user-maintenance",
    )

    history = await repo.list_repair_assignment_history(repair.repair_id)
    # Both rows still exist (non-destructive) — the old one is ended, the
    # new one is active.
    assert len(history) == 2
    old_entry = next(h for h in history if h.user_id == "user-tech-1")
    new_entry = next(h for h in history if h.user_id == "user-tech-2")
    assert old_entry.active_status is False
    assert old_entry.ended_at is not None
    assert new_entry.active_status is True
    assert new_entry.ended_at is None

    detail = await repo.get_repair(repair.repair_id)
    assert detail.repair.primary_technician == "user-tech-2"


async def test_reassigning_a_repair_never_touches_another_repairs_history() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    repair_a = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom=None,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    repair_b = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9002",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom=None,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair_a.repair_id,
        primary_technician="user-tech-1",
        collaborators=[],
        assigned_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair_b.repair_id,
        primary_technician="user-tech-2",
        collaborators=[],
        assigned_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair_a.repair_id,
        primary_technician="user-tech-3",
        collaborators=[],
        assigned_by="user-maintenance",
    )

    history_b = await repo.list_repair_assignment_history(repair_b.repair_id)
    assert len(history_b) == 1
    assert history_b[0].user_id == "user-tech-2"
    assert history_b[0].active_status is True

    detail_b = await repo.get_repair(repair_b.repair_id)
    assert detail_b.repair.primary_technician == "user-tech-2"


# ---------------------------------------------------------------------------
# add_repair_action / add_repair_part: append-only.
# ---------------------------------------------------------------------------


async def test_repair_actions_are_appended_and_never_overwritten() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom=None,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.add_repair_action(
        repair_id=repair.repair_id, action_text="ตรวจสอบเบื้องต้น", actor="user-tech-1", attachment_ids=[]
    )
    await repo.add_repair_action(
        repair_id=repair.repair_id,
        action_text="เปลี่ยนอะไหล่",
        actor="user-tech-1",
        attachment_ids=["ATT-0001", "ATT-0002"],
    )

    detail = await repo.get_repair(repair.repair_id)
    assert [a.action_text for a in detail.actions] == ["ตรวจสอบเบื้องต้น", "เปลี่ยนอะไหล่"]
    assert detail.actions[1].attachment_ids == ["ATT-0001", "ATT-0002"]
    assert len({a.repair_action_id for a in detail.actions}) == 2


async def test_repair_parts_persist_with_quantity_and_optional_links() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom=None,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.add_repair_part(
        repair_id=repair.repair_id,
        part_description="ไส้กรองน้ำมันเครื่อง",
        quantity=2,
        unit="ชิ้น",
        recorded_by="user-tech-1",
        part_id="PRT-0001",
    )

    detail = await repo.get_repair(repair.repair_id)
    assert len(detail.parts) == 1
    assert detail.parts[0].part_description == "ไส้กรองน้ำมันเครื่อง"
    assert detail.parts[0].quantity == 2
    assert detail.parts[0].part_id == "PRT-0001"


# ---------------------------------------------------------------------------
# close_repair: only the target row changes.
# ---------------------------------------------------------------------------


async def test_close_repair_updates_only_the_target_row() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    a = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="A",
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    b = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9002",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="B",
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.close_repair(a.repair_id, closed_by="user-maintenance", close_note="เสร็จแล้ว", closed_snapshot_id="MSNAP-0099")

    reread_a = await repo.get_repair(a.repair_id)
    assert reread_a.repair.status == RepairStatus.CLOSED
    assert reread_a.repair.close_note == "เสร็จแล้ว"
    assert reread_a.repair.closed_snapshot_id == "MSNAP-0099"

    reread_b = await repo.get_repair(b.repair_id)
    assert reread_b.repair.status == RepairStatus.OPEN
    assert reread_b.repair.symptom == "B"


# ---------------------------------------------------------------------------
# End-to-end: Repair Request -> Maintenance conversion -> real repair_order
# row, in google_sheets mode (the actual P0 gap).
# ---------------------------------------------------------------------------


def _repo_for_conversion():
    vehicle_ws = _ws(schemas.VEHICLE_SHEET)
    vehicle_ws.append_row(_vehicle_row("VEH-9001"))
    vehicle_ws.append_row(_vehicle_row("VEH-9002"))
    return _repo_with_fake_sheets(
        _ws(schemas.REPAIR_REQUEST_SHEET),
        vehicle_ws,
        _ws(schemas.VEHICLE_COMPONENT_SHEET),
        _ws(schemas.METER_SNAPSHOT_SHEET),
        _ws(schemas.METER_READING_SHEET),
        _ws(schemas.LOCATION_SNAPSHOT_SHEET),
        *_repair_sheets(),
    )


async def test_repair_request_conversion_creates_a_real_repair_order_row_in_sheets_mode() -> None:
    repo = _repo_for_conversion()
    meter_service = MeterService(repo)
    repair_service = RepairService(repo, meter_service)
    request_service = RepairRequestService(repo, repair_service, meter_service)

    request, _ = await request_service.create(
        vehicle_id="VEH-9001",
        reported_by_user_id="user-driver-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="เครื่องยนต์มีเสียงดัง",
        priority="HIGH",
        note_th=None,
    )
    assert request.request_status == "PENDING"

    detail = await request_service.convert(
        repair_request_id=request.repair_request_id,
        reviewed_by_user_id="user-maintenance",
        category=None,
        primary_technician=None,
        collaborators=None,
    )
    assert detail.repair.repair_id.startswith("RPR-")
    assert detail.repair.status == RepairStatus.OPEN
    assert detail.repair.source_type == RepairSourceType.REPAIR_REQUEST
    assert detail.repair.source_id == request.repair_request_id

    # The Repair actually persisted (independent read via get_repair).
    reread_repair = await repo.get_repair(detail.repair.repair_id)
    assert reread_repair is not None
    assert reread_repair.repair.asset_id == "VEH-9001"

    # The Repair Request itself is updated: converted status, linked
    # repair_id, reviewer, reviewed_at, converted_at.
    reread_request = await request_service.get(request.repair_request_id)
    assert reread_request.request_status == "CONVERTED"
    assert reread_request.repair_id == detail.repair.repair_id
    assert reread_request.reviewed_by_user_id == "user-maintenance"
    assert reread_request.reviewed_at is not None
    assert reread_request.converted_at is not None


async def test_repair_request_conversion_retry_never_creates_a_duplicate_repair_in_sheets_mode() -> None:
    repo = _repo_for_conversion()
    meter_service = MeterService(repo)
    repair_service = RepairService(repo, meter_service)
    request_service = RepairRequestService(repo, repair_service, meter_service)

    request, _ = await request_service.create(
        vehicle_id="VEH-9001",
        reported_by_user_id="user-driver-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="เครื่องยนต์มีเสียงดัง",
        priority=None,
        note_th=None,
    )

    first = await request_service.convert(
        repair_request_id=request.repair_request_id,
        reviewed_by_user_id="user-maintenance",
        category=None,
        primary_technician=None,
        collaborators=None,
    )
    second = await request_service.convert(
        repair_request_id=request.repair_request_id,
        reviewed_by_user_id="user-maintenance",
        category=None,
        primary_technician=None,
        collaborators=None,
    )
    assert first.repair.repair_id == second.repair.repair_id

    all_repairs, total = await repo.list_repairs(
        asset_type=None, asset_id=None, status=None, params=PageParams(page=1, page_size=50)
    )
    assert total == 1


async def test_unrelated_repair_request_rows_are_untouched_by_a_conversion() -> None:
    repo = _repo_for_conversion()
    meter_service = MeterService(repo)
    repair_service = RepairService(repo, meter_service)
    request_service = RepairRequestService(repo, repair_service, meter_service)

    keep_pending, _ = await request_service.create(
        vehicle_id="VEH-9002",
        reported_by_user_id="user-driver-2",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="อาการที่ไม่เกี่ยวข้อง",
        priority=None,
        note_th=None,
    )
    to_convert, _ = await request_service.create(
        vehicle_id="VEH-9001",
        reported_by_user_id="user-driver-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="อาการที่ต้องการแปลง",
        priority=None,
        note_th=None,
    )

    await request_service.convert(
        repair_request_id=to_convert.repair_request_id,
        reviewed_by_user_id="user-maintenance",
        category=None,
        primary_technician=None,
        collaborators=None,
    )

    reread_untouched = await request_service.get(keep_pending.repair_request_id)
    assert reread_untouched.request_status == "PENDING"
    assert reread_untouched.repair_id is None
    assert reread_untouched.symptom_th == "อาการที่ไม่เกี่ยวข้อง"


# ---------------------------------------------------------------------------
# REV06 section 12: the Repair action/part assignment-or-capability gate
# must work in both repository modes since assignments are now real in
# google_sheets mode too (not just MockRepository) — see
# tests/test_repair_pm_work_authorization.py for the MockRepository/API
# coverage of the same rule.
# ---------------------------------------------------------------------------


async def test_repair_work_authorization_gate_honors_real_sheets_backed_assignment() -> None:
    repo = _repo_with_fake_sheets(*_repair_sheets())
    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom=None,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair.repair_id,
        primary_technician="user-tech-1",
        collaborators=["user-tech-2"],
        assigned_by="user-maintenance",
    )
    detail = await repo.get_repair(repair.repair_id)

    # Active PRIMARY: allowed.
    require_assignment_or_capability(
        _ctx("user-tech-1"),
        CAN_MANAGE_REPAIR,
        detail.repair.primary_technician,
        detail.repair.collaborators,
        "test",
    )
    # Active COLLABORATOR: allowed.
    require_assignment_or_capability(
        _ctx("user-tech-2"),
        CAN_MANAGE_REPAIR,
        detail.repair.primary_technician,
        detail.repair.collaborators,
        "test",
    )
    # Maintenance (capability, no assignment at all): allowed.
    require_assignment_or_capability(
        _ctx("user-maintenance-2", frozenset({CAN_MANAGE_REPAIR})),
        CAN_MANAGE_REPAIR,
        detail.repair.primary_technician,
        detail.repair.collaborators,
        "test",
    )
    # Unrelated actor: denied.
    with pytest.raises(HTTPException) as exc_info:
        require_assignment_or_capability(
            _ctx("user-unrelated"),
            CAN_MANAGE_REPAIR,
            detail.repair.primary_technician,
            detail.repair.collaborators,
            "test",
        )
    assert exc_info.value.status_code == 403

    # After reassignment, the PREVIOUS primary technician loses access to
    # this same repair (real Sheets-backed reassignment, not just mock).
    await repo.assign_repair(
        repair_id=repair.repair_id,
        primary_technician="user-tech-3",
        collaborators=[],
        assigned_by="user-maintenance",
    )
    reread = await repo.get_repair(repair.repair_id)
    with pytest.raises(HTTPException) as exc_info:
        require_assignment_or_capability(
            _ctx("user-tech-1"),
            CAN_MANAGE_REPAIR,
            reread.repair.primary_technician,
            reread.repair.collaborators,
            "test",
        )
    assert exc_info.value.status_code == 403
