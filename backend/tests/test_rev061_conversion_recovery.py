"""REV06.1 — independent-audit CONSISTENCY-1 fix.

The REV06 independent audit found `RepairRequestService.convert()` writes
`create_repair` and `mark_repair_request_converted` as two separate,
non-transactional Google Sheets writes. If the first succeeds and the
process crashes/retries before the second commits, `request_status`
alone is left `PENDING` even though a Repair already exists — a naive
retry would then create a second `RPR-xxxx` for the same Repair Request.
`convert()` now looks for an existing Repair linked by
`source_type=REPAIR_REQUEST, source_id=repair_request_id` before
creating one, using the new `Repository.find_repairs_by_source` method
(implemented in both `MockRepository` and `GoogleSheetsRepository`).

These tests exercise the same FAKE in-memory `gspread`-shaped client as
`test_google_sheets_repair_real_io.py` (never the real Google API) so the
recovery is proven against the actual Sheets-mode repository, not just
the in-memory Mock.
"""
from __future__ import annotations

import pytest

from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.domain.meter_service import MeterService
from app.domain.repair import RepairSourceType, RepairStatus
from app.domain.repair_request_service import RepairRequestService
from app.domain.repair_service import RepairService
from app.errors import ApiError
from app.repositories.google_sheets import schemas
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws

pytestmark = pytest.mark.asyncio


def _vehicle_row(vehicle_id: str = "VEH-9001") -> list:
    return [vehicle_id, "MC-9001", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]


def _repair_sheets():
    return (
        _ws(schemas.REPAIR_SHEET),
        _ws(schemas.REPAIR_ACTION_SHEET),
        _ws(schemas.REPAIR_PART_SHEET),
        _ws(schemas.REPAIR_ASSIGNMENT_SHEET),
    )


def _repo_for_conversion():
    vehicle_ws = _ws(schemas.VEHICLE_SHEET)
    vehicle_ws.append_row(_vehicle_row("VEH-9001"))
    return _repo_with_fake_sheets(
        _ws(schemas.REPAIR_REQUEST_SHEET),
        vehicle_ws,
        _ws(schemas.VEHICLE_COMPONENT_SHEET),
        _ws(schemas.METER_SNAPSHOT_SHEET),
        _ws(schemas.METER_READING_SHEET),
        _ws(schemas.LOCATION_SNAPSHOT_SHEET),
        *_repair_sheets(),
    )


async def _make_services(repo):
    meter_service = MeterService(repo)
    repair_service = RepairService(repo, meter_service)
    request_service = RepairRequestService(repo, repair_service, meter_service)
    return repair_service, request_service


async def _submit_request(request_service: RepairRequestService, vehicle_id: str = "VEH-9001"):
    request, _ = await request_service.create(
        vehicle_id=vehicle_id,
        reported_by_user_id="user-driver-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="เครื่องยนต์มีเสียงดัง",
        priority=None,
        note_th=None,
    )
    return request


# ---------------------------------------------------------------------------
# Case A/C — a Repair was already created for this Repair Request by an
# earlier, interrupted conversion attempt (request_status never flipped to
# CONVERTED). Retrying must reuse it, never create a second one, and must
# finish the linkage write.
# ---------------------------------------------------------------------------


async def test_partial_failure_then_retry_reuses_the_existing_repair_and_completes_linkage() -> None:
    repo = _repo_for_conversion()
    repair_service, request_service = await _make_services(repo)
    request = await _submit_request(request_service)

    # Simulate the interrupted first attempt: the Repair got created (the
    # first write in `convert()`), but the second write
    # (`mark_repair_request_converted`) never ran — exactly the partial
    # failure window `convert()` cannot fully prevent on a non-transactional
    # backend.
    orphaned = await repair_service.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id=request.vehicle_id,
        source_type=RepairSourceType.REPAIR_REQUEST,
        source_id=request.repair_request_id,
        category=None,
        symptom=request.symptom_th,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    assert orphaned.repair.status == RepairStatus.OPEN

    # The request is still PENDING (the second write never happened).
    reread_before = await request_service.get(request.repair_request_id)
    assert reread_before.request_status == "PENDING"

    # Retry the conversion — must reuse the orphaned repair, not create a
    # second one, and must finish the linkage.
    recovered = await request_service.convert(
        repair_request_id=request.repair_request_id,
        reviewed_by_user_id="user-maintenance-2",
        category=None,
        primary_technician=None,
        collaborators=None,
    )
    assert recovered.repair.repair_id == orphaned.repair.repair_id

    reread_after = await request_service.get(request.repair_request_id)
    assert reread_after.request_status == "CONVERTED"
    assert reread_after.repair_id == orphaned.repair.repair_id
    assert reread_after.reviewed_by_user_id == "user-maintenance-2"
    assert reread_after.converted_at is not None

    all_repairs, total = await repo.list_repairs(
        asset_type=None, asset_id=None, status=None, params=PageParams(page=1, page_size=50)
    )
    assert total == 1


# ---------------------------------------------------------------------------
# Case B — already fully converted; retrying is a pure no-op (regression
# guard for the pre-existing REV05/REV06 behavior).
# ---------------------------------------------------------------------------


async def test_already_converted_retry_is_idempotent() -> None:
    repo = _repo_for_conversion()
    _, request_service = await _make_services(repo)
    request = await _submit_request(request_service)

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


# ---------------------------------------------------------------------------
# Case D — corrupted historical state: TWO repairs already exist for the
# same Repair Request (from some earlier, worse failure). `convert()` must
# refuse to create a third, and must raise a clear integrity error rather
# than silently guessing which one is correct.
# ---------------------------------------------------------------------------


async def test_two_existing_repairs_for_the_same_request_raises_an_integrity_error() -> None:
    repo = _repo_for_conversion()
    repair_service, request_service = await _make_services(repo)
    request = await _submit_request(request_service)

    first_orphan = await repair_service.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id=request.vehicle_id,
        source_type=RepairSourceType.REPAIR_REQUEST,
        source_id=request.repair_request_id,
        category=None,
        symptom=request.symptom_th,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    second_orphan = await repair_service.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id=request.vehicle_id,
        source_type=RepairSourceType.REPAIR_REQUEST,
        source_id=request.repair_request_id,
        category=None,
        symptom=request.symptom_th,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    assert first_orphan.repair.repair_id != second_orphan.repair.repair_id

    with pytest.raises(ApiError) as excinfo:
        await request_service.convert(
            repair_request_id=request.repair_request_id,
            reviewed_by_user_id="user-maintenance",
            category=None,
            primary_technician=None,
            collaborators=None,
        )
    assert excinfo.value.code == "REPAIR_REQUEST_CONVERSION_INTEGRITY_ERROR"

    # Refusing to proceed — no third repair was created, and the request
    # is still PENDING (not falsely marked CONVERTED against either one).
    all_repairs, total = await repo.list_repairs(
        asset_type=None, asset_id=None, status=None, params=PageParams(page=1, page_size=50)
    )
    assert total == 2
    reread = await request_service.get(request.repair_request_id)
    assert reread.request_status == "PENDING"


# ---------------------------------------------------------------------------
# Case E — Repair creation itself fails; the request must remain
# unconverted (no linkage write ever attempted).
# ---------------------------------------------------------------------------


async def test_repair_creation_failure_leaves_the_request_unconverted() -> None:
    repo = _repo_for_conversion()
    _, request_service = await _make_services(repo)
    request = await _submit_request(request_service)

    with pytest.raises(Exception):
        await request_service.convert(
            repair_request_id="RRQ-DOES-NOT-EXIST",
            reviewed_by_user_id="user-maintenance",
            category=None,
            primary_technician=None,
            collaborators=None,
        )

    reread = await request_service.get(request.repair_request_id)
    assert reread.request_status == "PENDING"
