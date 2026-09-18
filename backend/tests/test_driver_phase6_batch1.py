"""Web/API Phase 6 Batch 1 — Driver / Operator master + vehicle<->driver
assignment history.

Proves: driver master CRUD round-trips through the API/MockRepository;
assignment history is preserved (creating a new assignment never
modifies/ends any other assignment row — project decision, targeted
correction: no PRIMARY-exclusivity/overlap/auto-termination rule is
approved); ending an assignment is idempotent (a repeated end returns the
existing row unchanged, never a 409, never a second history row);
`active_status`/`assignment_status` are honest opaque passthrough values
(no invented vocabulary, never coerced); and the Google Sheets repository
maps the two verified live tabs (`driver_master`, `vehicle_driver`)
correctly by header name, using a FAKE in-memory gspread-shaped client
only (never the real Google API — see
`tests/test_google_sheets_real_io.py` module docstring for why)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas

from tests.test_google_sheets_real_io import FakeSpreadsheet, FakeWorksheet, _ws


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


# ---------------------------------------------------------------------------
# Driver master — API / MockRepository round trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_drivers_are_present(client: AsyncClient) -> None:
    response = await client.get("/api/v1/drivers")
    assert response.status_code == 200
    ids = {d["driver_id"] for d in response.json()["items"]}
    assert {"DRV-0001", "DRV-0002"}.issubset(ids)


@pytest.mark.asyncio
async def test_create_driver_round_trips(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/drivers",
        json={
            "driver_name_th": "ทดสอบ ระบบ",
            "phone": "080-000-0000",
            "license_no": "TH-DL-999999",
            "license_expiry_date": "2028-01-01",
            "active_status": None,
            "note_th": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["driver_id"].startswith("DRV-")
    assert body["driver_name_th"] == "ทดสอบ ระบบ"
    assert body["active_status"] is None

    reread = await client.get(f"/api/v1/drivers/{body['driver_id']}")
    assert reread.status_code == 200
    assert reread.json() == body


@pytest.mark.asyncio
async def test_create_driver_requires_a_name(client: AsyncClient) -> None:
    response = await client.post("/api/v1/drivers", json={"driver_name_th": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_get_unknown_driver_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/drivers/DRV-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DRIVER_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_driver_preserves_driver_id_and_replaces_mutable_fields(
    client: AsyncClient,
) -> None:
    created = await client.post("/api/v1/drivers", json={"driver_name_th": "เดิม"})
    driver_id = created.json()["driver_id"]

    updated = await client.patch(
        f"/api/v1/drivers/{driver_id}",
        json={
            "driver_name_th": "ใหม่",
            "phone": "089-999-9999",
            "license_no": "TH-DL-123123",
            "license_expiry_date": "2029-12-31",
            "active_status": "1",
            "note_th": "ปรับปรุงข้อมูล",
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["driver_id"] == driver_id
    assert body["driver_name_th"] == "ใหม่"
    assert body["active_status"] == "1"


@pytest.mark.asyncio
async def test_active_status_is_an_honest_passthrough_never_a_fixed_vocabulary(
    client: AsyncClient,
) -> None:
    """CRITICAL NO-GUESSING RULE: whatever string a caller supplies is
    stored/returned verbatim; the backend never coerces it against an
    invented ACTIVE/INACTIVE (or any other) enum, and a request supplying
    an arbitrary string is never rejected for that reason."""
    for arbitrary_value in ["1", "0", "SOME_UNEXPECTED_VALUE", "ใช้งาน"]:
        response = await client.post(
            "/api/v1/drivers",
            json={"driver_name_th": "ทดสอบค่า", "active_status": arbitrary_value},
        )
        assert response.status_code == 200
        assert response.json()["active_status"] == arbitrary_value


# ---------------------------------------------------------------------------
# Vehicle <-> Driver assignment history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_assignment_history_shows_one_ended_and_one_active_period(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1046/driver-assignments")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 2
    ended = [e for e in entries if e["end_at"] is not None]
    active = [e for e in entries if e["end_at"] is None]
    assert len(ended) == 1
    assert len(active) == 1
    assert active[0]["driver_id"] == "DRV-0001"
    # assignment_status stays exactly what the (seeded, None) value was —
    # never coerced into a guessed vocabulary.
    assert entries[0]["assignment_status"] is None


@pytest.mark.asyncio
async def test_assign_driver_creates_a_new_history_row(client: AsyncClient) -> None:
    driver = await client.post("/api/v1/drivers", json={"driver_name_th": "คนขับใหม่"})
    driver_id = driver.json()["driver_id"]

    response = await client.post(
        "/api/v1/vehicles/VEH-1047/driver-assignments",
        json={"driver_id": driver_id, "is_primary": False, "note_th": "ทดสอบ"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assignment_id"].startswith("VDRV-")
    assert body["vehicle_id"] == "VEH-1047"
    assert body["driver_id"] == driver_id
    assert body["is_primary"] is False
    assert body["end_at"] is None

    history = await client.get("/api/v1/vehicles/VEH-1047/driver-assignments")
    assert any(e["assignment_id"] == body["assignment_id"] for e in history.json())


@pytest.mark.asyncio
async def test_assign_unknown_driver_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-1046/driver-assignments",
        json={"driver_id": "DRV-9999", "is_primary": False},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DRIVER_NOT_FOUND"


@pytest.mark.asyncio
async def test_assign_driver_to_unknown_vehicle_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/vehicles/VEH-9999/driver-assignments",
        json={"driver_id": "DRV-0001", "is_primary": False},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_new_primary_assignment_does_not_modify_or_end_an_existing_assignment(
    client: AsyncClient,
) -> None:
    """Project decision (targeted correction): creating a new
    `is_primary=True` assignment must NOT auto-close/modify any existing
    assignment. Only "assignment start/end history" + "preservation of
    previous history" are approved — no PRIMARY-exclusivity rule."""
    before = await client.get("/api/v1/vehicles/VEH-1046/driver-assignments")
    previous_active = [e for e in before.json() if e["end_at"] is None][0]
    assert previous_active["is_primary"] is True

    response = await client.post(
        "/api/v1/vehicles/VEH-1046/driver-assignments",
        json={"driver_id": "DRV-0002", "is_primary": True},
    )
    assert response.status_code == 200
    new_entry = response.json()
    assert new_entry["end_at"] is None
    assert new_entry["driver_id"] == "DRV-0002"

    after = await client.get("/api/v1/vehicles/VEH-1046/driver-assignments")
    entries_by_id = {e["assignment_id"]: e for e in after.json()}

    # The previously-active row is completely untouched — still active,
    # never closed, never modified as a side effect of the new one.
    assert previous_active["assignment_id"] in entries_by_id
    assert entries_by_id[previous_active["assignment_id"]] == previous_active

    # Both PRIMARY rows are now simultaneously active — multiple active
    # assignments (PRIMARY or not) for the same vehicle are preserved
    # unless explicitly ended; no exclusivity is enforced.
    active_primary = [e for e in after.json() if e["end_at"] is None and e["is_primary"]]
    assert len(active_primary) == 2

    # Total row count only grew by one — no row was deleted or altered.
    assert len(after.json()) == len(before.json()) + 1


@pytest.mark.asyncio
async def test_non_primary_assignment_does_not_end_existing_primary(
    client: AsyncClient,
) -> None:
    before = await client.get("/api/v1/vehicles/VEH-1046/driver-assignments")
    previous_active = [e for e in before.json() if e["end_at"] is None][0]

    response = await client.post(
        "/api/v1/vehicles/VEH-1046/driver-assignments",
        json={"driver_id": "DRV-0002", "is_primary": False},
    )
    assert response.status_code == 200

    after = await client.get("/api/v1/vehicles/VEH-1046/driver-assignments")
    entries_by_id = {e["assignment_id"]: e for e in after.json()}
    # The existing active PRIMARY row is untouched.
    assert entries_by_id[previous_active["assignment_id"]]["end_at"] is None


@pytest.mark.asyncio
async def test_assignment_status_is_an_honest_passthrough_never_a_fixed_vocabulary(
    client: AsyncClient,
) -> None:
    """CRITICAL NO-GUESSING RULE (mirrors
    test_active_status_is_an_honest_passthrough_never_a_fixed_vocabulary):
    `assignment_status` is a plain opaque string on `vehicle_driver`, not
    an Enum. No approved vocabulary exists for it, so an arbitrary,
    obviously-synthetic caller-supplied value must be persisted and
    returned verbatim — never coerced, normalized, replaced, rejected, or
    mapped to an invented enum — through the create-assignment API path
    and back out through the history-read path."""
    # Must fit the field's existing max_length=50 technical bound (the
    # same minimal, vocabulary-free safety limit already applied to
    # active_status) — a length defect here would be a test-authoring
    # bug, not evidence of business-vocabulary coercion.
    synthetic_value = "ZZZ_TEST_ONLY_UNAPPROVED_VALUE_ไม่ใช่จริง"

    response = await client.post(
        "/api/v1/vehicles/VEH-1047/driver-assignments",
        json={"driver_id": "DRV-0001", "is_primary": False, "assignment_status": synthetic_value},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assignment_status"] == synthetic_value

    history = await client.get("/api/v1/vehicles/VEH-1047/driver-assignments")
    assert history.status_code == 200
    matching = [e for e in history.json() if e["assignment_id"] == body["assignment_id"]]
    assert len(matching) == 1
    assert matching[0]["assignment_status"] == synthetic_value


@pytest.mark.asyncio
async def test_ending_an_assignment_sets_end_at_normally(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/vehicles/VEH-1047/driver-assignments",
        json={"driver_id": "DRV-0001", "is_primary": True},
    )
    assignment_id = created.json()["assignment_id"]
    assert created.json()["end_at"] is None

    ended = await client.post(f"/api/v1/vehicle-driver-assignments/{assignment_id}/end")
    assert ended.status_code == 200
    assert ended.json()["end_at"] is not None
    assert ended.json()["assignment_id"] == assignment_id

    history = await client.get("/api/v1/vehicles/VEH-1047/driver-assignments")
    assert any(e["assignment_id"] == assignment_id for e in history.json())


@pytest.mark.asyncio
async def test_ending_an_already_ended_assignment_is_an_idempotent_no_op(
    client: AsyncClient,
) -> None:
    """Project decision (targeted correction): repeated `end` succeeds,
    never returns 409 VEHICLE_DRIVER_ASSIGNMENT_ALREADY_ENDED, never
    changes the original `end_at`, and never creates an additional
    history row. No correction/edit policy for `end_at` is approved."""
    created = await client.post(
        "/api/v1/vehicles/VEH-1047/driver-assignments",
        json={"driver_id": "DRV-0001", "is_primary": True},
    )
    assignment_id = created.json()["assignment_id"]

    first_end = await client.post(f"/api/v1/vehicle-driver-assignments/{assignment_id}/end")
    assert first_end.status_code == 200
    original_end_at = first_end.json()["end_at"]
    assert original_end_at is not None

    second_end = await client.post(f"/api/v1/vehicle-driver-assignments/{assignment_id}/end")
    assert second_end.status_code == 200
    assert second_end.json()["end_at"] == original_end_at
    assert second_end.json() == first_end.json()

    third_end = await client.post(f"/api/v1/vehicle-driver-assignments/{assignment_id}/end")
    assert third_end.status_code == 200
    assert third_end.json()["end_at"] == original_end_at

    # No additional history row was created by the repeated end calls —
    # exactly one row for this assignment_id, and the vehicle's overall
    # history did not grow beyond the one assignment created.
    history = await client.get("/api/v1/vehicles/VEH-1047/driver-assignments")
    matching = [e for e in history.json() if e["assignment_id"] == assignment_id]
    assert len(matching) == 1
    assert matching[0]["end_at"] == original_end_at


@pytest.mark.asyncio
async def test_end_unknown_assignment_returns_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/vehicle-driver-assignments/VDRV-9999/end")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_DRIVER_ASSIGNMENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Google Sheets — verified live tab/header mapping (FAKE in-memory client)
# ---------------------------------------------------------------------------


def test_driver_master_schema_uses_the_exact_verified_live_headers() -> None:
    assert schemas.DRIVER_MASTER_SHEET.tab_name == "driver_master"
    assert schemas.DRIVER_MASTER_SHEET.required_headers == (
        "driver_id",
        "driver_name_th",
        "phone",
        "license_no",
        "license_expiry_date",
        "active_status",
        "note_th",
    )


def test_vehicle_driver_schema_uses_the_exact_verified_live_headers() -> None:
    assert schemas.VEHICLE_DRIVER_SHEET.tab_name == "vehicle_driver"
    assert schemas.VEHICLE_DRIVER_SHEET.required_headers == (
        "assignment_id",
        "vehicle_id",
        "driver_id",
        "start_at",
        "end_at",
        "is_primary",
        "assignment_status",
        "changed_by_user_id",
        "note_th",
    )


@pytest.mark.asyncio
async def test_google_sheets_driver_create_then_read_round_trips_by_header_name() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.DRIVER_MASTER_SHEET))
    created = await repo.create_driver(
        driver_name_th="ทดสอบ ชีต",
        phone="080-111-2222",
        license_no="TH-DL-111222",
        license_expiry_date=None,
        active_status=None,
        note_th=None,
    )
    assert created.driver_id.startswith("DRV-")

    reread = await repo.get_driver(created.driver_id)
    assert reread is not None
    assert reread.driver_name_th == "ทดสอบ ชีต"
    assert reread.phone == "080-111-2222"
    # Blank cells stay honestly None, never fabricated.
    assert reread.license_expiry_date is None
    assert reread.active_status is None


@pytest.mark.asyncio
async def test_google_sheets_driver_update_touches_only_the_target_row() -> None:
    ws = _ws(schemas.DRIVER_MASTER_SHEET)
    repo = _repo_with_fake_sheets(ws)
    first = await repo.create_driver(
        driver_name_th="คนที่ 1",
        phone=None,
        license_no=None,
        license_expiry_date=None,
        active_status=None,
        note_th=None,
    )
    second = await repo.create_driver(
        driver_name_th="คนที่ 2",
        phone=None,
        license_no=None,
        license_expiry_date=None,
        active_status=None,
        note_th=None,
    )
    assert len(ws.rows) == 2

    await repo.update_driver(
        driver_id=first.driver_id,
        driver_name_th="คนที่ 1 (แก้ไข)",
        phone="080-000-1111",
        license_no=None,
        license_expiry_date=None,
        active_status=None,
        note_th=None,
    )

    reread_first = await repo.get_driver(first.driver_id)
    assert reread_first is not None
    assert reread_first.driver_name_th == "คนที่ 1 (แก้ไข)"

    reread_second = await repo.get_driver(second.driver_id)
    assert reread_second is not None
    assert reread_second.driver_name_th == "คนที่ 2"


# ---------------------------------------------------------------------------
# Live UAT defect fix — phone leading-zero loss on Google Sheets write, and
# HTTP 500 on reading a legacy numeric phone cell.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_sheets_driver_phone_with_leading_zero_survives_create_read_round_trip() -> (
    None
):
    """WRITE-path defect fix: a phone value that looks like a plain
    integer (e.g. "0999999999") must not be silently coerced into a
    Sheets number and lose its leading zero. Exercises the real
    create -> Sheets write -> Sheets read -> domain path end to end."""
    repo = _repo_with_fake_sheets(_ws(schemas.DRIVER_MASTER_SHEET))
    created = await repo.create_driver(
        driver_name_th="ทดสอบเบอร์โทร",
        phone="0999999999",
        license_no=None,
        license_expiry_date=None,
        active_status=None,
        note_th=None,
    )
    assert created.phone == "0999999999"

    reread = await repo.get_driver(created.driver_id)
    assert reread is not None
    assert reread.phone == "0999999999"


@pytest.mark.asyncio
async def test_google_sheets_fake_client_does_not_numerically_coerce_the_written_phone_cell() -> (
    None
):
    """Proves the write path itself defends against numeric coercion:
    the raw value actually sent to the Sheets client for the `phone`
    column carries the text-forcing marker rather than a bare digit
    string that Sheets' USER_ENTERED mode would auto-convert to a
    number (the exact mechanism the live UAT defect exposed)."""
    ws = _ws(schemas.DRIVER_MASTER_SHEET)
    repo = _repo_with_fake_sheets(ws)
    await repo.create_driver(
        driver_name_th="ทดสอบ",
        phone="0999999999",
        license_no=None,
        license_expiry_date=None,
        active_status=None,
        note_th=None,
    )
    phone_column = schemas.DRIVER_MASTER_SHEET.required_headers.index("phone")
    raw_written_value = ws.rows[0][phone_column]
    # A bare "0999999999" is exactly what a prior (defective) write would
    # have sent — Sheets' own USER_ENTERED parsing is what strips the
    # leading zero server-side, which this fake does not simulate, so the
    # defect is caught here instead: the write must never send that bare
    # form for an opaque textual field.
    assert raw_written_value != "0999999999"
    assert str(raw_written_value) == "'0999999999"


@pytest.mark.asyncio
async def test_google_sheets_existing_numeric_phone_cell_does_not_crash_driver_from_row() -> None:
    """READ-path robustness fix, unit-level: `_driver_from_row` (the
    exact function named in the live UAT traceback) must not raise when
    `phone` arrives as a Python int/float rather than str — which is
    exactly what the real Sheets API returns for a legacy row whose
    phone cell is already stored as a number."""
    repo = GoogleSheetsRepository(_configured_settings())
    driver = repo._driver_from_row(  # noqa: SLF001 - exercising the exact defect location
        {
            "driver_id": "DRV-0001",
            "driver_name_th": "UAT Driver Batch1",
            "phone": 999999999,
            "license_no": "UAT-LIC-001",
            "license_expiry_date": "2027-12-31",
            "active_status": "ZZZ_UAT_ONLY_STATUS",
            "note_th": "Phase 6 Batch 1 Live UAT",
        }
    )
    # Returned as text, never invented with a leading zero that has
    # already been lost — the numeric cell genuinely no longer carries
    # that information.
    assert driver.phone == "999999999"
    assert driver.phone != "0999999999"


@pytest.mark.asyncio
async def test_google_sheets_get_driver_reads_a_legacy_numeric_phone_row_without_500() -> None:
    """End-to-end version of the same fix through `get_driver`, with the
    Sheets row itself (not just the isolated row dict) carrying a raw
    int for `phone`, simulating an already-corrupted live row exactly
    like the confirmed DRV-0001 UAT defect."""
    ws = _ws(schemas.DRIVER_MASTER_SHEET)
    repo = _repo_with_fake_sheets(ws)
    created = await repo.create_driver(
        driver_name_th="UAT Driver Batch1",
        phone=None,
        license_no="UAT-LIC-001",
        license_expiry_date=None,
        active_status="ZZZ_UAT_ONLY_STATUS",
        note_th="Phase 6 Batch 1 Live UAT",
    )
    phone_column = schemas.DRIVER_MASTER_SHEET.required_headers.index("phone")
    # Simulate the legacy/corrupted row: the sheet cell is a raw number,
    # not text (what a pre-fix write, or manual spreadsheet entry, would
    # have produced).
    ws.rows[0][phone_column] = 999999999

    reread = await repo.get_driver(created.driver_id)
    assert reread is not None
    assert reread.phone == "999999999"
    assert reread.phone != "0999999999"


# ---------------------------------------------------------------------------
# license_expiry_date follow-up investigation (live UAT evidence: the cell's
# underlying Sheets storage is a date serial, e.g. 46752, formatted as
# yyyy-mm-dd and displaying "2027-12-31"). Confirmed by direct inspection of
# the installed gspread 6.2.1 source (Worksheet.get/get_all_records default
# to ValueRenderOption.formatted when value_render_option is not passed —
# see client.py's read_rows/find_row, which never pass one — and
# gspread.utils.numericise only converts a string that parses cleanly as
# int/float; "2027-12-31" never does) that the CURRENT production read path
# receives the formatted string "2027-12-31", never the raw serial. No
# production date-handling change was made; these tests demonstrate that
# finding and prove the existing safe-degradation behavior for a
# hypothetical serial value is unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_sheets_driver_license_expiry_date_survives_create_read_round_trip() -> None:
    """Item 1: a driver written with license_expiry_date=2027-12-31 reads
    back as 2027-12-31, through the real create -> Sheets write -> Sheets
    read -> domain path (no production change was needed for this)."""
    repo = _repo_with_fake_sheets(_ws(schemas.DRIVER_MASTER_SHEET))
    created = await repo.create_driver(
        driver_name_th="ทดสอบวันหมดอายุ",
        phone=None,
        license_no=None,
        license_expiry_date=date(2027, 12, 31),
        active_status=None,
        note_th=None,
    )
    assert created.license_expiry_date == date(2027, 12, 31)

    reread = await repo.get_driver(created.driver_id)
    assert reread is not None
    assert reread.license_expiry_date == date(2027, 12, 31)


def test_google_sheets_fake_client_never_numericises_a_formatted_date_string() -> None:
    """Confirms, using the now gspread-accurate fake (which reproduces
    real `numericise_all` behavior — see FakeWorksheet.get_all_records),
    that a date cell's FORMATTED_VALUE string ("2027-12-31", exactly what
    the live Sheet displays for a yyyy-mm-dd-formatted cell) is never
    converted into a number by gspread's own client-side coercion —
    unlike the bare-digit `phone` case, a date string is never
    numericised (int()/float() both fail on it) even without being
    listed in numericise_ignore, so no protection is needed for it."""
    ws = _ws(schemas.DRIVER_MASTER_SHEET)
    header = schemas.DRIVER_MASTER_SHEET.required_headers
    row = ["DRV-0001", "UAT Driver Batch1", "0999999999", "UAT-LIC-001", "2027-12-31", "", ""]
    ws.rows.append(row)
    records = ws.get_all_records()
    assert records[0]["license_expiry_date"] == "2027-12-31"
    assert isinstance(records[0]["license_expiry_date"], str)
    assert header[4] == "license_expiry_date"


def test_parse_date_safely_degrades_on_a_raw_serial_number_never_crashes_never_fabricates() -> (
    None
):
    """Items 3/4 (defensive robustness, not a decode claim): since
    production never actually receives a raw Sheets date serial (proven
    above), this proves `_parse_date` — the existing shared helper,
    reused rather than duplicated — still degrades safely rather than
    crashing or inventing a date if one ever did arrive, for both the
    `int`-like and `float`-like forms gspread could in principle return.
    It does NOT decode the serial to a calendar date: no serial-to-date
    conversion exists or was added, matching "do not force the date
    field... unless necessary" and "do not broaden... without
    evidence"."""
    repo = GoogleSheetsRepository(_configured_settings())
    assert repo._parse_date(46752) is None  # noqa: SLF001
    assert repo._parse_date(46752.0) is None  # noqa: SLF001
    assert repo._parse_date("not-a-date") is None  # noqa: SLF001
    assert repo._parse_date("") is None  # noqa: SLF001
    # The one format it is actually responsible for continues to work.
    assert repo._parse_date("2027-12-31") == date(2027, 12, 31)  # noqa: SLF001


@pytest.mark.asyncio
async def test_google_sheets_vehicle_driver_assignment_round_trips_and_preserves_history() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.VEHICLE_DRIVER_SHEET))
    first = await repo.create_vehicle_driver_assignment(
        vehicle_id="VEH-1046",
        driver_id="DRV-0001",
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_primary=True,
        assignment_status=None,
        changed_by_user_id="dev-user",
        note_th=None,
    )
    assert first.assignment_id.startswith("VDRV-")
    assert first.end_at is None
    assert first.is_primary is True

    ended = await repo.end_vehicle_driver_assignment(
        assignment_id=first.assignment_id,
        end_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        changed_by_user_id="dev-user",
    )
    assert ended.end_at is not None

    history = await repo.list_vehicle_driver_assignments("VEH-1046")
    assert len(history) == 1
    assert history[0].assignment_id == first.assignment_id
    assert history[0].end_at is not None


@pytest.mark.asyncio
async def test_google_sheets_missing_credentials_fails_explicitly_never_silently() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)
    with pytest.raises(RepositoryError, match="not configured"):
        await repo.get_driver("DRV-0001")
