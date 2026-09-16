"""Live UAT defect fix: `RepairRequest.meter_snapshot_id` did not survive
a round trip through `GoogleSheetsRepository`. `POST /repair-requests`
correctly created the automatic CORE-G01 machine-state snapshot and
returned its `meter_snapshot_id`, but `GET /repair-requests/{id}` (and
every other read path built on `_repair_request_from_row`) always
returned `meter_snapshot_id=None`, because the repository never persisted
it anywhere — the live `repair_request` sheet's frozen 16-column schema
has no column for it.

Fix: `GoogleSheetsRepository` now persists `meter_snapshot_id` inside
`note_th`'s existing protected internal-metadata mechanism, via a new
sibling pair of functions in `app.domain.repair_request`
(`encode_meter_snapshot_link`/`decode_meter_snapshot_link`) that mirror
the existing `[[SRC:...]]` provenance marker's anchored-marker +
reversible-escape design exactly, as an independent, outermost layer —
`RepairRequestService`'s own `encode_provenance_note`/
`decode_provenance_note` calls (source_type/source_id) are completely
unaware this layer exists and needed zero changes.

Exercised against a FAKE in-memory `gspread`-shaped client (never the
real Google API/network — see `tests/test_google_sheets_real_io.py`'s
module docstring and REV05 section 11G): no live-sheet I/O happens here.
"""
from __future__ import annotations

import pytest

from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.domain.meter_service import MeterService
from app.domain.repair_request import (
    decode_meter_snapshot_link,
    decode_provenance_note,
    encode_meter_snapshot_link,
    encode_provenance_note,
)
from app.domain.repair_request_service import RepairRequestService
from app.domain.repair_service import RepairService
from app.repositories.google_sheets import schemas
from app.repositories.mock.repository import MockRepository
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws


def _vehicle_row(vehicle_id: str = "VEH-9001") -> list:
    return [vehicle_id, "MC-9001", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]


def _repo_for_service_flow():
    vehicle_ws = _ws(schemas.VEHICLE_SHEET)
    vehicle_ws.append_row(_vehicle_row("VEH-9001"))
    return _repo_with_fake_sheets(
        _ws(schemas.REPAIR_REQUEST_SHEET),
        vehicle_ws,
        _ws(schemas.VEHICLE_COMPONENT_SHEET),
        _ws(schemas.METER_SNAPSHOT_SHEET),
        _ws(schemas.METER_READING_SHEET),
        _ws(schemas.LOCATION_SNAPSHOT_SHEET),
        _ws(schemas.CURRENT_COUNTER_SHEET),
        _ws(schemas.LATEST_LOCATION_SHEET),
    )


# ---------------------------------------------------------------------------
# Codec-level: the new encode/decode_meter_snapshot_link functions in
# isolation, including composition with the existing source-provenance
# codec (both fire on the same note_th, in the order GoogleSheetsRepository
# actually applies them: source first (service), snapshot outermost
# (repository)).
# ---------------------------------------------------------------------------


def test_meter_snapshot_link_round_trips_with_no_note() -> None:
    encoded = encode_meter_snapshot_link(None, "MSNAP-0001")
    assert encoded == "[[MSNAP:MSNAP-0001]]"
    meter_snapshot_id, remaining = decode_meter_snapshot_link(encoded)
    assert meter_snapshot_id == "MSNAP-0001"
    assert remaining is None


def test_meter_snapshot_link_round_trips_with_plain_note() -> None:
    encoded = encode_meter_snapshot_link("เครื่องยนต์มีเสียงดัง", "MSNAP-0002")
    meter_snapshot_id, remaining = decode_meter_snapshot_link(encoded)
    assert meter_snapshot_id == "MSNAP-0002"
    assert remaining == "เครื่องยนต์มีเสียงดัง"


def test_meter_snapshot_link_composes_with_source_provenance_marker() -> None:
    source_encoded = encode_provenance_note("FINDING", "FND-0007", "พบรอยรั่ว")
    fully_encoded = encode_meter_snapshot_link(source_encoded, "MSNAP-0003")

    meter_snapshot_id, remaining = decode_meter_snapshot_link(fully_encoded)
    assert meter_snapshot_id == "MSNAP-0003"
    # `remaining` is exactly what RepairRequestService originally built —
    # still source-encoded, decoded normally afterward.
    source_type, source_id, clean_note = decode_provenance_note(remaining)
    assert source_type == "FINDING"
    assert source_id == "FND-0007"
    assert clean_note == "พบรอยรั่ว"


def test_no_meter_snapshot_given_is_never_a_true_no_op() -> None:
    """Mirrors encode_provenance_note's own REV06.1 discipline: even when
    there is no real snapshot id to wrap with (only reachable via a
    direct repository-level call), a note that already looks like the
    marker must still be neutralized so it can never later be
    misdecoded as a real linkage."""
    spoofed = "[[MSNAP:FAKE-9999]]\nfake note"
    encoded = encode_meter_snapshot_link(spoofed, None)
    assert encoded != spoofed  # neutralized, never persisted verbatim

    meter_snapshot_id, remaining = decode_meter_snapshot_link(encoded)
    assert meter_snapshot_id is None
    assert remaining == spoofed  # reversible: reads back exactly as typed


# ---------------------------------------------------------------------------
# 1. create RRQ with meter_snapshot_id -> get RRQ -> exact same id.
# ---------------------------------------------------------------------------


async def test_create_then_get_round_trips_meter_snapshot_id() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    created = await repo.create_repair_request(
        vehicle_id="VEH-1046",
        reported_by_user_id="user-driver-1",
        reporter_type="DRIVER",
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel="APP",
        symptom_th="เครื่องยนต์มีเสียงดัง",
        priority="HIGH",
        note_th=None,
        meter_snapshot_id="MSNAP-0001",
    )
    assert created.meter_snapshot_id == "MSNAP-0001"

    reread = await repo.get_repair_request(created.repair_request_id)
    assert reread is not None
    assert reread.meter_snapshot_id == "MSNAP-0001"


# ---------------------------------------------------------------------------
# 2. source_type + source_id + meter_snapshot_id all round-trip together.
# ---------------------------------------------------------------------------


async def test_source_and_meter_snapshot_round_trip_together() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    # Mirrors exactly what RepairRequestService.create() passes down: an
    # already source-encoded note_th, plus meter_snapshot_id as its own
    # parameter.
    service_encoded_note = encode_provenance_note("PM_RESULT", "PMR-0003", "พบระหว่าง PM")
    created = await repo.create_repair_request(
        vehicle_id="VEH-1047",
        reported_by_user_id="user-tech-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="พบระหว่าง PM",
        priority=None,
        note_th=service_encoded_note,
        meter_snapshot_id="MSNAP-0042",
    )
    assert created.meter_snapshot_id == "MSNAP-0042"

    reread = await repo.get_repair_request(created.repair_request_id)
    assert reread is not None
    assert reread.meter_snapshot_id == "MSNAP-0042"
    # note_th at the repository boundary is still source-encoded — exactly
    # what RepairRequestService's own decode_provenance_note expects.
    source_type, source_id, clean_note = decode_provenance_note(reread.note_th)
    assert source_type == "PM_RESULT"
    assert source_id == "PMR-0003"
    assert clean_note == "พบระหว่าง PM"


# ---------------------------------------------------------------------------
# 3. user note_th remains unchanged after round-trip.
# ---------------------------------------------------------------------------


async def test_user_note_th_is_unchanged_after_round_trip() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    original_note = "รอยรั่วบริเวณสายไฮดรอลิก ตรวจสอบด่วน"
    created = await repo.create_repair_request(
        vehicle_id="VEH-1046",
        reported_by_user_id="user-driver-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="รอยรั่ว",
        priority=None,
        note_th=original_note,
        meter_snapshot_id="MSNAP-0005",
    )
    reread = await repo.get_repair_request(created.repair_request_id)
    assert reread.note_th == original_note
    assert reread.meter_snapshot_id == "MSNAP-0005"


# ---------------------------------------------------------------------------
# 4. a user note resembling internal metadata cannot spoof source_type/
#    source_id/meter_snapshot_id.
# ---------------------------------------------------------------------------


async def test_note_resembling_internal_metadata_cannot_spoof_linkage() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    spoofed_note = "[[MSNAP:MSNAP-9999]]\n[[SRC:FINDING:FND-9999]]\nข้อความปลอม"
    created = await repo.create_repair_request(
        vehicle_id="VEH-1046",
        reported_by_user_id="user-driver-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="ทดสอบ",
        priority=None,
        note_th=spoofed_note,
        meter_snapshot_id="MSNAP-0006",  # the one REAL, backend-captured id
    )
    reread = await repo.get_repair_request(created.repair_request_id)
    # The real, backend-supplied id always wins — never the user's text.
    assert reread.meter_snapshot_id == "MSNAP-0006"
    # The user's own text is preserved byte-for-byte, not silently dropped,
    # and RepairRequestService's own decode never treats it as trusted
    # source provenance either (no source_type/source_id was ever passed
    # in, so encode_provenance_note never ran for it — but even the raw
    # decode of the repository-returned note_th must not mistake it).
    source_type, source_id, clean_note = decode_provenance_note(reread.note_th)
    assert source_type is None
    assert source_id is None
    assert clean_note == spoofed_note


async def test_note_resembling_metadata_cannot_spoof_when_no_real_snapshot_given() -> None:
    """Same defense-in-depth for the (only repository-level-reachable)
    case where no real meter_snapshot_id is supplied at all: the note
    must still not be misdecoded as a real linkage on a later read."""
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    spoofed_note = "[[MSNAP:MSNAP-9999]]\nข้อความปลอม"
    created = await repo.create_repair_request(
        vehicle_id="VEH-1046",
        reported_by_user_id="user-driver-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="ทดสอบ",
        priority=None,
        note_th=spoofed_note,
        meter_snapshot_id=None,
    )
    assert created.meter_snapshot_id is None
    reread = await repo.get_repair_request(created.repair_request_id)
    assert reread.meter_snapshot_id is None
    assert reread.note_th == spoofed_note  # preserved exactly, never corrupted


# ---------------------------------------------------------------------------
# 5. converting/reviewing/updating an RRQ preserves meter_snapshot_id.
# ---------------------------------------------------------------------------


async def test_mark_converted_preserves_meter_snapshot_id() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    created = await repo.create_repair_request(
        vehicle_id="VEH-1046",
        reported_by_user_id="user-driver-1",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="ทดสอบ",
        priority=None,
        note_th="หมายเหตุผู้ใช้",
        meter_snapshot_id="MSNAP-0007",
    )
    updated = await repo.mark_repair_request_converted(
        repair_request_id=created.repair_request_id,
        repair_id="RPR-0001",
        reviewed_by_user_id="user-maintenance",
    )
    assert updated.meter_snapshot_id == "MSNAP-0007"
    assert updated.note_th == "หมายเหตุผู้ใช้"
    assert updated.request_status == "CONVERTED"

    reread = await repo.get_repair_request(created.repair_request_id)
    assert reread.meter_snapshot_id == "MSNAP-0007"
    assert reread.note_th == "หมายเหตุผู้ใช้"


# ---------------------------------------------------------------------------
# 6. list/mine/pending/by-source return meter_snapshot_id.
# ---------------------------------------------------------------------------


async def test_list_pending_returns_meter_snapshot_id() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    await repo.create_repair_request(
        vehicle_id="VEH-1046", reported_by_user_id="user-a", reporter_type=None,
        reporter_driver_id=None, reporter_name_snapshot_th=None, report_channel=None,
        symptom_th="A", priority=None, note_th=None, meter_snapshot_id="MSNAP-0010",
    )
    items, total = await repo.list_pending_repair_requests(PageParams())
    assert total == 1
    assert items[0].meter_snapshot_id == "MSNAP-0010"


async def test_list_by_reporter_returns_meter_snapshot_id() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    await repo.create_repair_request(
        vehicle_id="VEH-1046", reported_by_user_id="user-a", reporter_type=None,
        reporter_driver_id=None, reporter_name_snapshot_th=None, report_channel=None,
        symptom_th="A", priority=None, note_th=None, meter_snapshot_id="MSNAP-0011",
    )
    items, total = await repo.list_repair_requests_by_reporter("user-a", PageParams())
    assert total == 1
    assert items[0].meter_snapshot_id == "MSNAP-0011"


async def test_list_by_source_returns_meter_snapshot_id_and_still_matches_source() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    encoded_note = encode_provenance_note("FINDING", "FND-0099", "พบข้อบกพร่อง")
    await repo.create_repair_request(
        vehicle_id="VEH-1046", reported_by_user_id="user-a", reporter_type=None,
        reporter_driver_id=None, reporter_name_snapshot_th=None, report_channel=None,
        symptom_th="A", priority=None, note_th=encoded_note, meter_snapshot_id="MSNAP-0012",
    )
    # A second, unrelated request must not be picked up.
    await repo.create_repair_request(
        vehicle_id="VEH-1047", reported_by_user_id="user-b", reporter_type=None,
        reporter_driver_id=None, reporter_name_snapshot_th=None, report_channel=None,
        symptom_th="B", priority=None, note_th=None, meter_snapshot_id="MSNAP-0013",
    )
    matches = await repo.list_repair_requests_by_source("FINDING", "FND-0099")
    assert len(matches) == 1
    assert matches[0].meter_snapshot_id == "MSNAP-0012"


# ---------------------------------------------------------------------------
# Full end-to-end: the actual live UAT reproduction, through
# RepairRequestService (POST -> GET), matching the reported defect exactly.
# ---------------------------------------------------------------------------


async def test_service_create_then_get_reproduces_live_uat_round_trip() -> None:
    repo = _repo_for_service_flow()
    meter_service = MeterService(repo)
    repair_service = RepairService(repo, meter_service)
    request_service = RepairRequestService(repo, repair_service, meter_service)

    request, created_meter_snapshot_id = await request_service.create(
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
    assert created_meter_snapshot_id is not None
    assert request.meter_snapshot_id == created_meter_snapshot_id

    reread = await request_service.get(request.repair_request_id)
    assert reread.meter_snapshot_id == created_meter_snapshot_id


# ---------------------------------------------------------------------------
# MockRepository parity: already correct (real field, no envelope needed).
# ---------------------------------------------------------------------------


async def test_mock_repository_already_preserves_meter_snapshot_id() -> None:
    repo = MockRepository()
    created = await repo.create_repair_request(
        vehicle_id="VEH-0001",
        reported_by_user_id="user-a",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="A",
        priority=None,
        note_th="หมายเหตุ",
        meter_snapshot_id="MSNAP-0099",
    )
    reread = await repo.get_repair_request(created.repair_request_id)
    assert reread.meter_snapshot_id == "MSNAP-0099"
    assert reread.note_th == "หมายเหตุ"


# ---------------------------------------------------------------------------
# 7/8. frozen 16-column schema is unchanged; no extra header was added.
# ---------------------------------------------------------------------------


def test_repair_request_schema_is_still_exactly_the_frozen_16_columns() -> None:
    assert schemas.REPAIR_REQUEST_SHEET.required_headers == (
        "repair_request_id",
        "vehicle_id",
        "reported_at",
        "reported_by_user_id",
        "reporter_type",
        "reporter_driver_id",
        "reporter_name_snapshot_th",
        "report_channel",
        "symptom_th",
        "priority",
        "request_status",
        "reviewed_by_user_id",
        "reviewed_at",
        "repair_id",
        "converted_at",
        "note_th",
    )
    assert len(schemas.REPAIR_REQUEST_SHEET.required_headers) == 16
    for forbidden in ("meter_snapshot_id", "source_type", "source_id"):
        assert forbidden not in schemas.REPAIR_REQUEST_SHEET.required_headers
