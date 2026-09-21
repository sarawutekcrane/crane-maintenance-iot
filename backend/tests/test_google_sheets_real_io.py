"""Core Demo Fixes Delta REV05 section 11 — real Google Sheets read/write
I/O, exercised against a FAKE in-memory `gspread`-shaped client (never the
real Google API/network — see module docstring in
`app.repositories.google_sheets.client` and REV05 section 11G: "Unit/
repository tests must mock/fake the Google API/client and MUST NOT mutate
the real live spreadsheet by default.").

`FakeWorksheet`/`FakeSpreadsheet` implement just enough of gspread's
`Worksheet`/`Spreadsheet` surface (`row_values`, `get_all_records`,
`append_row`, `update`, `worksheets`, `worksheet`) for
`GoogleSheetsClient`'s generic row engine to operate against — proving
the *mapping/engine* logic (header-name mapping, append vs. targeted
single-row update, null-preserving reads) without a network dependency.
"""
from __future__ import annotations

import re

import pytest

from app.config import Settings
from app.domain.asset import AssetType
from app.domain.attachment import AttachmentPurpose
from app.domain.common import PageParams
from app.domain.equipment import EquipmentOperationalStatus
from app.domain.meter import CounterType, MeterReading
from app.domain.requisition import RequisitionSourceType
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.google_sheets.client import GoogleSheetsClient


_SINGLE_ROW_RANGE_RE = re.compile(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$")


def _column_index(letters: str) -> int:
    """Inverse of `GoogleSheetsClient._column_letter`: 'A' -> 1, 'Z' ->
    26, 'AA' -> 27, ..."""
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index


def _parse_single_row_range(range_name: str) -> tuple[int, int, int]:
    """Parse an A1-notation range this codebase's client ever issues —
    always a single row, either one cell ("H2") or a column span on one
    row ("H2:L2") — into `(start_col, row_number, end_col)`, all
    1-indexed. Every real call site (`update_row`/`update_row_fields`)
    only ever spans one row, so a differing start/end row is a defect in
    the caller, not something this fake needs to support."""
    match = _SINGLE_ROW_RANGE_RE.match(range_name)
    assert match is not None, f"unparseable range: {range_name!r}"
    start_col_letters, start_row_s, end_col_letters, end_row_s = match.groups()
    start_row = int(start_row_s)
    if end_row_s is not None:
        assert int(end_row_s) == start_row, f"multi-row range not supported by fake: {range_name!r}"
    start_col = _column_index(start_col_letters)
    end_col = _column_index(end_col_letters) if end_col_letters else start_col
    return start_col, start_row, end_col


class FakeWorksheet:
    def __init__(self, title: str, header: tuple[str, ...]) -> None:
        self.title = title
        self.header = list(header)
        self.rows: list[list[object]] = []
        # Call counters (REV07 live UAT defect, section 15): distinguishing
        # single-row appends from batched multi-row appends lets a
        # regression test assert *which* write path a repository method
        # takes, not only the resulting data — see
        # `test_google_sheets_inspection_result_persistence.py`.
        self.append_row_calls = 0
        self.append_rows_calls = 0
        # Every keyword argument set actually passed to append_row/
        # append_rows by the client under test (REV08 live UAT defect) —
        # asserted on directly, since a naive in-memory `self.rows.append`
        # can never itself reproduce a real Sheets API table-detection
        # misfire (see test_google_sheets_real_io module docstring).
        self.append_row_kwargs: list[dict[str, object]] = []
        self.append_rows_kwargs: list[dict[str, object]] = []
        # Web/API Phase 6 Batch 4C D22 review fix: counts calls to
        # delete_rows, mirroring the existing append_row_calls/
        # append_rows_calls counters' purpose.
        self.delete_rows_calls = 0
        # Web/API Phase 6 Batch 5B review fix B5B-01: every `update()`
        # call's exact A1 range string, in call order — lets a targeted-
        # write test assert which COLUMNS were actually touched (a full
        # row range like "A2:M2" vs. a narrow one like "H2:L2"), not only
        # the resulting row content (which a coincidentally-identical
        # rewrite could pass even though it touched every column).
        self.update_calls = 0
        self.update_ranges: list[str] = []

    def row_values(self, n: int) -> list[str]:
        if n == 1:
            return list(self.header)
        return [str(v) for v in self.rows[n - 2]]

    def get_all_records(
        self,
        head: int = 1,
        default_blank: str = "",
        numericise_ignore: list[int] | None = None,
    ) -> list[dict]:
        # Phase 6 Batch 1 live UAT defect fix — two real gspread behaviors
        # this fake previously hid, confirmed by reading the installed
        # gspread 6.2.1 source directly (Worksheet.get_all_records/get,
        # gspread.utils.numericise/numericise_all):
        #
        # 1. A leading apostrophe is a Sheets *write-time* input-
        #    formatting marker (forces USER_ENTERED to store literal text
        #    instead of auto-detecting a number) — it is never part of
        #    the cell's actual stored content, so the real Sheets API
        #    never returns it on read.
        # 2. Independently of (1) and of the cell's real stored type,
        #    `get_all_records()` performs its own **client-side** numeric
        #    coercion (`numericise_all`) on every column's value: any
        #    string that parses cleanly as `int`/`float` is converted to
        #    that type, UNLESS its 1-indexed column position is listed in
        #    `numericise_ignore`. This applies uniformly — gspread cannot
        #    tell "genuinely a number" from "force-texted but numeric-
        #    looking" apart, so apostrophe-forcing alone (1) does NOT
        #    protect a value from this step; only `numericise_ignore`
        #    does. This is why `GoogleSheetsRepository` now passes
        #    `text_only_headers=("phone",)` for every `driver_master`
        #    read (see `_DRIVER_TEXT_ONLY_HEADERS`).
        #
        # No existing write path before the phone fix ever produced a
        # leading apostrophe, and no existing table's tests depended on
        # a numeric-looking text value surviving unnumericised (verified
        # by running the full backend suite after this change), so this
        # is a fidelity correction, not a behavioral regression.
        ignore = set(numericise_ignore or [])

        def _cell(v: object, column_index: int) -> object:
            if v == "":
                return ""
            text = str(v)
            if text.startswith("'"):
                text = text[1:]
            if (column_index + 1) in ignore:
                return text
            try:
                return int(text)
            except ValueError:
                pass
            try:
                return float(text)
            except ValueError:
                return text

        return [
            dict(zip(self.header, (_cell(v, i) for i, v in enumerate(row))))
            for row in self.rows
        ]

    def append_row(
        self,
        values: list,
        value_input_option: str | None = None,
        insert_data_option: str | None = None,
        table_range: str | None = None,
    ) -> None:
        self.append_row_calls += 1
        self.append_row_kwargs.append(
            {
                "value_input_option": value_input_option,
                "insert_data_option": insert_data_option,
                "table_range": table_range,
            }
        )
        self.rows.append(list(values))

    def append_rows(
        self,
        values: list[list],
        value_input_option: str | None = None,
        insert_data_option: str | None = None,
        table_range: str | None = None,
    ) -> None:
        self.append_rows_calls += 1
        self.append_rows_kwargs.append(
            {
                "value_input_option": value_input_option,
                "insert_data_option": insert_data_option,
                "table_range": table_range,
            }
        )
        for row in values:
            self.rows.append(list(row))

    def update(self, range_name: str, values: list[list], value_input_option: str | None = None) -> None:
        """Web/API Phase 6 Batch 5B review fix B5B-01: column-range-aware,
        mirroring real gspread `Worksheet.update(range_name, values, ...)`
        semantics for the subset this codebase's client actually uses —
        a single-row range, either the full row width (`update_row`) or a
        narrower column slice (`update_row_fields`). Only the cells
        inside `range_name` are overwritten; every other cell of that
        row (and every other row) is left exactly as it was — this is
        what lets a test prove a targeted write really did stay
        targeted, rather than only checking the final row content."""
        self.update_calls += 1
        self.update_ranges.append(range_name)
        start_col, start_row, end_col = _parse_single_row_range(range_name)
        row_index = start_row - 2
        row = self.rows[row_index]
        incoming = values[0]
        for offset, col in enumerate(range(start_col, end_col + 1)):
            col_index = col - 1
            while len(row) <= col_index:
                row.append("")
            row[col_index] = incoming[offset]

    def delete_rows(self, start_index: int, end_index: int | None = None) -> None:
        """Mirrors real gspread `Worksheet.delete_rows` semantics
        (verified against installed gspread 6.2.1 source): 1-indexed
        INCLUDING the header row (data rows start at physical row 2);
        deletes rows `[start_index, end_index]` inclusive, or exactly
        `start_index` alone when `end_index` is omitted. Every row after
        the deleted range shifts up — callers deleting several rows must
        account for that (see `GoogleSheetsClient.delete_row`'s own
        docstring/callers)."""
        self.delete_rows_calls += 1
        end = end_index if end_index is not None else start_index
        del self.rows[start_index - 2 : end - 1]


class FakeSpreadsheet:
    def __init__(self, worksheets: list[FakeWorksheet]) -> None:
        self._by_title = {w.title: w for w in worksheets}

    def worksheets(self) -> list[FakeWorksheet]:
        return list(self._by_title.values())

    def worksheet(self, title: str) -> FakeWorksheet:
        if title not in self._by_title:
            raise KeyError(f"no such worksheet: {title}")
        return self._by_title[title]


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


def _ws(schema) -> FakeWorksheet:
    return FakeWorksheet(schema.tab_name, schema.required_headers)


# ---------------------------------------------------------------------------
# 20-21 — repair_request exact header mapping; exact live sheet names used.
# ---------------------------------------------------------------------------


def test_repair_request_schema_uses_the_exact_live_column_list() -> None:
    assert schemas.REPAIR_REQUEST_SHEET.tab_name == "repair_request"
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


# ---------------------------------------------------------------------------
# 22-23 — mode selection never silently falls back to mock; missing
# credential/config fails explicitly.
# ---------------------------------------------------------------------------


def test_google_sheets_mode_always_constructs_the_real_repository_never_mock() -> None:
    from app.config import DataRepositoryMode, get_settings
    from app.dependencies import get_repository, reset_dependency_cache

    import os

    original = os.environ.get("DATA_REPOSITORY")
    original_sheet = os.environ.get("GOOGLE_SHEET_ID")
    os.environ["DATA_REPOSITORY"] = "google_sheets"
    os.environ.pop("GOOGLE_SHEET_ID", None)  # deliberately unconfigured
    get_settings.cache_clear()
    reset_dependency_cache()
    try:
        settings = get_settings()
        assert settings.data_repository == DataRepositoryMode.GOOGLE_SHEETS
        repo = get_repository()
        # Constructed as the real class even though credentials are
        # missing — never silently substituted with MockRepository.
        assert type(repo).__name__ == "GoogleSheetsRepository"
    finally:
        if original is None:
            os.environ.pop("DATA_REPOSITORY", None)
        else:
            os.environ["DATA_REPOSITORY"] = original
        if original_sheet is not None:
            os.environ["GOOGLE_SHEET_ID"] = original_sheet
        get_settings.cache_clear()
        reset_dependency_cache()


@pytest.mark.asyncio
async def test_missing_credentials_fails_explicitly_never_silently() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)
    with pytest.raises(RepositoryError, match="not configured"):
        await repo.get_vehicle("VEH-1046")


# ---------------------------------------------------------------------------
# 24 — schema validator detects a missing sheet / missing header with a
# useful message.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_validator_reports_a_missing_tab_by_name() -> None:
    client = GoogleSheetsClient(_configured_settings())
    client._spreadsheet = FakeSpreadsheet([])  # type: ignore[attr-defined]
    ok, reason = await client.validate_schema(schemas.REPAIR_REQUEST_SHEET)
    assert ok is False
    assert "repair_request" in reason


@pytest.mark.asyncio
async def test_schema_validator_reports_a_missing_required_header() -> None:
    incomplete = FakeWorksheet("repair_request", ("repair_request_id", "vehicle_id"))
    client = GoogleSheetsClient(_configured_settings())
    client._spreadsheet = FakeSpreadsheet([incomplete])  # type: ignore[attr-defined]
    ok, reason = await client.validate_schema(schemas.REPAIR_REQUEST_SHEET)
    assert ok is False
    assert "symptom_th" in reason


@pytest.mark.asyncio
async def test_schema_validator_passes_when_tab_and_headers_match() -> None:
    client = GoogleSheetsClient(_configured_settings())
    client._spreadsheet = FakeSpreadsheet([_ws(schemas.REPAIR_REQUEST_SHEET)])  # type: ignore[attr-defined]
    ok, reason = await client.validate_schema(schemas.REPAIR_REQUEST_SHEET)
    assert ok is True and reason is None


# ---------------------------------------------------------------------------
# 25-27 — read/create/update row-mapping correctness.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_request_create_then_read_round_trips_by_header_name() -> None:
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
    )
    assert created.repair_request_id.startswith("RRQ-")
    assert created.request_status == "PENDING"

    reread = await repo.get_repair_request(created.repair_request_id)
    assert reread is not None
    assert reread.vehicle_id == "VEH-1046"
    assert reread.symptom_th == "เครื่องยนต์มีเสียงดัง"
    assert reread.priority == "HIGH"
    assert reread.request_status == "PENDING"
    assert reread.repair_id is None


@pytest.mark.asyncio
async def test_repair_request_conversion_updates_only_the_target_row() -> None:
    ws = _ws(schemas.REPAIR_REQUEST_SHEET)
    repo = _repo_with_fake_sheets(ws)
    first = await repo.create_repair_request(
        vehicle_id="VEH-1046",
        reported_by_user_id="user-a",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="อาการที่ 1",
        priority=None,
        note_th=None,
    )
    second = await repo.create_repair_request(
        vehicle_id="VEH-1047",
        reported_by_user_id="user-b",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="อาการที่ 2",
        priority=None,
        note_th=None,
    )
    assert len(ws.rows) == 2

    await repo.mark_repair_request_converted(
        repair_request_id=first.repair_request_id,
        repair_id="RPR-0001",
        reviewed_by_user_id="user-maintenance",
    )

    # Row 2 (first) is updated...
    reread_first = await repo.get_repair_request(first.repair_request_id)
    assert reread_first.request_status == "CONVERTED"
    assert reread_first.repair_id == "RPR-0001"
    # ...row 3 (second) is completely untouched — never a full-sheet rewrite.
    reread_second = await repo.get_repair_request(second.repair_request_id)
    assert reread_second.request_status == "PENDING"
    assert reread_second.symptom_th == "อาการที่ 2"
    assert reread_second.repair_id is None


@pytest.mark.asyncio
async def test_pending_repair_requests_list_excludes_converted_ones() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.REPAIR_REQUEST_SHEET))
    pending = await repo.create_repair_request(
        vehicle_id="VEH-1046",
        reported_by_user_id="user-a",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="รอตรวจรับ",
        priority=None,
        note_th=None,
    )
    converted = await repo.create_repair_request(
        vehicle_id="VEH-1047",
        reported_by_user_id="user-b",
        reporter_type=None,
        reporter_driver_id=None,
        reporter_name_snapshot_th=None,
        report_channel=None,
        symptom_th="แปลงแล้ว",
        priority=None,
        note_th=None,
    )
    await repo.mark_repair_request_converted(
        repair_request_id=converted.repair_request_id,
        repair_id="RPR-0001",
        reviewed_by_user_id="user-maintenance",
    )

    items, total = await repo.list_pending_repair_requests(PageParams(page=1, page_size=20))
    assert total == 1
    assert items[0].repair_request_id == pending.repair_request_id


# ---------------------------------------------------------------------------
# 28 — snapshot writes preserve null for missing counter/GPS.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meter_snapshot_write_and_read_preserve_null_readings() -> None:
    repo = _repo_with_fake_sheets(
        _ws(schemas.METER_SNAPSHOT_SHEET), _ws(schemas.METER_READING_SHEET)
    )
    created = await repo.create_meter_snapshot(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1046",
        readings=[
            MeterReading(component_id="COMP-1", counter_type=CounterType.ENGINE_HOUR, value=None)
        ],
        recorded_by="dev-user",
        is_automatic=True,
        source_note="REPAIR_OPEN",
    )
    reread = await repo.get_meter_snapshot(created.meter_snapshot_id)
    assert reread is not None
    assert reread.is_automatic is True
    assert len(reread.readings) == 1
    assert reread.readings[0].value is None  # never fabricated as 0


@pytest.mark.asyncio
async def test_location_snapshot_write_and_read_preserve_null_gps() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.LOCATION_SNAPSHOT_SHEET))
    created = await repo.create_location_snapshot(
        event_type="REPAIR_REQUEST_REPORT",
        event_id="MSNAP-0001",
        vehicle_id="VEH-1046",
        device_id=None,
        latitude=None,
        longitude=None,
        altitude_m=None,
        accuracy_m=None,
        gps_time=None,
        received_at=None,
        gps_valid=False,
        source=None,
    )
    reread = await repo.get_location_snapshot(created.location_snapshot_id)
    assert reread is not None
    assert reread.latitude is None
    assert reread.longitude is None
    assert reread.gps_valid is False

    by_event = await repo.list_location_snapshots_for_event("MSNAP-0001")
    assert len(by_event) == 1
    assert by_event[0].location_snapshot_id == created.location_snapshot_id


# ---------------------------------------------------------------------------
# 29 — Repair Request attachment metadata uses REPAIR_REQUEST source.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_request_attachment_uses_repair_request_source() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.ATTACHMENT_SHEET))
    created = await repo.create_attachment(
        purpose=AttachmentPurpose.REPAIR_REQUEST_EVIDENCE,
        storage_ref="local://uploads/photo1.jpg",
        filename="photo1.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
        uploaded_by="user-driver-1",
        source_type="REPAIR_REQUEST",
        source_id="RRQ-0001",
    )
    assert created.source_type == "REPAIR_REQUEST"
    assert created.source_id == "RRQ-0001"

    reread = await repo.get_attachment(created.attachment_id)
    assert reread.source_type == "REPAIR_REQUEST"

    by_source = await repo.list_attachments_for_source("REPAIR_REQUEST", "RRQ-0001")
    assert len(by_source) == 1
    assert by_source[0].attachment_id == created.attachment_id


# ---------------------------------------------------------------------------
# 30 — material_request header + lines persist correctly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_material_request_header_and_lines_persist_correctly() -> None:
    repo = _repo_with_fake_sheets(
        _ws(schemas.MATERIAL_REQUEST_SHEET), _ws(schemas.MATERIAL_REQUEST_LINE_SHEET)
    )
    header = await repo.create_material_request(
        source_type=RequisitionSourceType.PM,
        source_work_order_id="PMWO-0001",
        vehicle_id="VEH-1046",
        created_by="user-maintenance",
    )
    await repo.create_requisition_line(
        material_request_id=header.material_request_id,
        part_id=None,
        part_instance_id=None,
        part_code_snapshot=None,
        part_description="ไส้กรองน้ำมันเครื่อง",
        requested_quantity=2,
        unit="ชิ้น",
        source_task_revision_id="PMREV-0001",
        line_source="PM_STANDARD",
        created_by="user-maintenance",
    )

    detail = await repo.get_material_request(header.material_request_id)
    assert detail is not None
    assert detail.request.source_work_order_id == "PMWO-0001"
    assert len(detail.lines) == 1
    assert detail.lines[0].part_description == "ไส้กรองน้ำมันเครื่อง"
    assert detail.lines[0].requested_quantity == 2

    by_work_order = await repo.list_material_requests_for_work_order("PMWO-0001")
    assert len(by_work_order) == 1
    lines_by_work_order = await repo.list_requisition_lines_for_work_order("PMWO-0001")
    assert len(lines_by_work_order) == 1


# ---------------------------------------------------------------------------
# 31 — PM same-plan validation remains enforced in Google Sheets mode.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pm_same_plan_validation_enforced_against_real_sheet_reads() -> None:
    model_ws = _ws(schemas.VEHICLE_MODEL_SHEET)
    model_ws.append_row(
        [
            "MDL-1",
            "MC-1",
            "Model 1",
            "",
            "",
            "",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            "PLAN1",
        ]
    )
    vehicle_ws = _ws(schemas.VEHICLE_SHEET)
    vehicle_ws.append_row(
        [
            "VEH-9001",
            "MC-9001",
            "MDL-1",
            "",
            "READY",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ]
    )
    plan_ws = _ws(schemas.PM_PLAN_SHEET)
    plan_ws.append_row(
        ["PMP-0001", "PLAN1", "VEHICLE", "Plan 1", "", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]
    )
    other_plan_ws_row = ["PMP-0002", "PLAN2", "VEHICLE", "Plan 2", "", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]
    plan_ws.append_row(other_plan_ws_row)

    repo = _repo_with_fake_sheets(model_ws, vehicle_ws, plan_ws)

    vehicle = await repo.get_vehicle("VEH-9001")
    assert vehicle is not None
    model = await repo.get_vehicle_model(vehicle.model_id)
    assert model is not None
    assert model.assigned_pm_plan_id == "PMP-0001"  # resolved via plan_code, not guessed

    from app.domain.pm_service import PmService
    from app.domain.meter_service import MeterService

    pm_service = PmService(repo, MeterService(repo))
    from app.errors import ApiError

    with pytest.raises(ApiError) as exc_info:
        await pm_service.open_work_order(
            asset_type=AssetType.VEHICLE,
            asset_id="VEH-9001",
            pm_plan_id="PMP-0002",  # the OTHER plan, not this model's assigned one
            due_reason=None,
            opened_by="user-maintenance",
            note=None,
        )
    assert exc_info.value.code == "PM_PLAN_NOT_ASSIGNED_TO_MODEL"


# ---------------------------------------------------------------------------
# 32 — RETIRED equipment rules still pass in Google Sheets repository tests.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retired_equipment_status_change_persists_and_appends_history() -> None:
    equipment_ws = _ws(schemas.EQUIPMENT_SHEET)
    equipment_ws.append_row(
        [
            "EQP-9001",
            "EC-9001",
            "เครื่องเชื่อมทดสอบ",
            "WELDING",
            "",
            "",
            "SN-1",
            "READY",
            "TRUE",
            "2026-01-01",
            "",
        ]
    )
    history_ws = _ws(schemas.EQUIPMENT_STATUS_HISTORY_SHEET)
    repo = _repo_with_fake_sheets(equipment_ws, history_ws)

    before = await repo.get_equipment("EQP-9001")
    assert before is not None
    assert before.operational_status == EquipmentOperationalStatus.READY

    updated = await repo.change_equipment_status(
        equipment_id="EQP-9001",
        status=EquipmentOperationalStatus.RETIRED,
        reason="ปลดระวางถาวร",
        changed_by="user-maintenance",
    )
    assert updated.operational_status == EquipmentOperationalStatus.RETIRED

    reread = await repo.get_equipment("EQP-9001")
    assert reread.operational_status == EquipmentOperationalStatus.RETIRED
    # Every other equipment column on that same row is untouched.
    assert reread.equipment_code == "EC-9001"

    history = await repo.list_equipment_status_history("EQP-9001")
    assert len(history) == 1
    assert history[0].status == EquipmentOperationalStatus.RETIRED
    assert history[0].reason == "ปลดระวางถาวร"


# ---------------------------------------------------------------------------
# Startup/schema validation (REV05 section 11D) — readiness names the
# first missing Core sheet/header rather than a generic failure.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readiness_names_the_missing_core_tab() -> None:
    # Every Core tab present except repair_request.
    all_ws = [
        _ws(s)
        for s in GoogleSheetsRepository._CORE_SCHEMAS
        if s.tab_name != "repair_request"
    ]
    repo = _repo_with_fake_sheets(*all_ws)
    ready, reason = await repo.check_ready()
    assert ready is False
    assert "repair_request" in reason


@pytest.mark.asyncio
async def test_readiness_passes_when_every_core_tab_and_header_matches() -> None:
    all_ws = [_ws(s) for s in GoogleSheetsRepository._CORE_SCHEMAS]
    repo = _repo_with_fake_sheets(*all_ws)
    ready, reason = await repo.check_ready()
    assert ready is True and reason is None
