"""Web/API Phase 6 Batch 1 — Driver / Operator master.

Proves: driver master CRUD round-trips through the API/MockRepository;
`active_status` is an honest opaque passthrough value (no invented
vocabulary, never coerced); and the Google Sheets repository maps the
verified live tab `driver_master` correctly by header name, using a FAKE
in-memory gspread-shaped client only (never the real Google API — see
`tests/test_google_sheets_real_io.py` module docstring for why).

R2 Batch R2-C3 (A2-8 / A2-10) retired the Phase 6 vehicle<->driver
assignment model, its three routes and their retention tests; the tests
below prove the retirement (routes absent and 404, no code, no readiness
prerequisite) while Driver Master stays fully covered. The live
`vehicle_driver` tab is never touched by the code or by these tests."""
from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.domain.driver_service import DriverService
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


# ---------------------------------------------------------------------------
# Live UAT defect fix — PATCH /drivers/{driver_id} omitted-field preservation.
# ---------------------------------------------------------------------------


async def _create_full_uat_driver(client: AsyncClient) -> dict:
    created = await client.post(
        "/api/v1/drivers",
        json={
            "driver_name_th": "UAT Driver Batch1 Fixed",
            "phone": "0812345678",
            "license_no": "UAT-LIC-002",
            "license_expiry_date": "2028-06-30",
            "active_status": "ZZZ_UAT_FIXED_STATUS",
            "note_th": "Phase 6 Batch 1 Live UAT after phone fix",
        },
    )
    assert created.status_code == 200
    return created.json()


@pytest.mark.asyncio
async def test_patch_omitting_fields_preserves_their_existing_stored_values(
    client: AsyncClient,
) -> None:
    """Reproduces the exact confirmed live UAT defect: PATCH sending only
    driver_name_th/phone/note_th must not erase license_no/
    license_expiry_date/active_status."""
    driver = await _create_full_uat_driver(client)

    patched = await client.patch(
        f"/api/v1/drivers/{driver['driver_id']}",
        json={
            "driver_name_th": "UAT Driver Batch1 Fixed",
            "phone": "0890000123",
            "note_th": "Phase 6 Batch 1 PATCH Live UAT",
        },
    )
    assert patched.status_code == 200
    body = patched.json()

    # Applied fields take the new value; phone keeps its leading zero.
    assert body["phone"] == "0890000123"
    assert body["note_th"] == "Phase 6 Batch 1 PATCH Live UAT"

    # Omitted fields are exactly unchanged, not nulled.
    assert body["license_no"] == "UAT-LIC-002"
    assert body["license_expiry_date"] == "2028-06-30"
    assert body["active_status"] == "ZZZ_UAT_FIXED_STATUS"

    # GET after PATCH returns the same preserved values.
    reread = await client.get(f"/api/v1/drivers/{driver['driver_id']}")
    assert reread.status_code == 200
    reread_body = reread.json()
    assert reread_body["phone"] == "0890000123"
    assert reread_body["note_th"] == "Phase 6 Batch 1 PATCH Live UAT"
    assert reread_body["license_no"] == "UAT-LIC-002"
    assert reread_body["license_expiry_date"] == "2028-06-30"
    assert reread_body["active_status"] == "ZZZ_UAT_FIXED_STATUS"


@pytest.mark.asyncio
async def test_patch_explicit_null_clears_the_field_while_omitted_fields_are_untouched(
    client: AsyncClient,
) -> None:
    """Documented judgment call (Phase 6 Batch 1 PATCH-preservation fix
    report): explicit null for a field the client actually sent clears
    it — this is NOT an established project-wide convention (no other
    endpoint has this shape); it continues this endpoint's own
    pre-existing behavior for the one case that was already observable
    before the omission-preservation fix. Fields omitted entirely from
    the same request remain untouched regardless."""
    driver = await _create_full_uat_driver(client)

    patched = await client.patch(
        f"/api/v1/drivers/{driver['driver_id']}",
        json={
            "driver_name_th": "UAT Driver Batch1 Fixed",
            "license_no": None,  # explicit null: clears
            # license_expiry_date, active_status, note_th, phone: omitted
        },
    )
    assert patched.status_code == 200
    body = patched.json()

    assert body["license_no"] is None
    # Everything omitted from this request stays exactly as it was.
    assert body["phone"] == "0812345678"
    assert body["license_expiry_date"] == "2028-06-30"
    assert body["active_status"] == "ZZZ_UAT_FIXED_STATUS"
    assert body["note_th"] == "Phase 6 Batch 1 Live UAT after phone fix"


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
# R2 Batch R2-C3 — the Phase 6 vehicle<->driver assignment is retired
# (A2-8 / A2-10, owner decisions D1-D4); Driver Master stays (above / below)
# ---------------------------------------------------------------------------

RETIRED_ROUTES = (
    ("GET", "/api/v1/vehicles/VEH-1046/driver-assignments", "/api/v1/vehicles/{vehicle_id}/driver-assignments"),
    ("POST", "/api/v1/vehicles/VEH-1046/driver-assignments", "/api/v1/vehicles/{vehicle_id}/driver-assignments"),
    ("POST", "/api/v1/vehicle-driver-assignments/VDRV-0001/end", "/api/v1/vehicle-driver-assignments/{assignment_id}/end"),
)


@pytest.mark.asyncio
async def test_the_three_phase6_assignment_routes_are_retired(client: AsyncClient) -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    for method, url, template in RETIRED_ROUTES:
        assert template not in paths, template
        response = await client.request(method, url, json={"driver_id": "DRV-0001"})
        assert response.status_code == 404, (method, url)
        assert response.json()["error"]["code"] == "NOT_FOUND"
    # The four Driver Master routes stay.
    assert set(paths["/api/v1/drivers"]) == {"get", "post"}
    assert set(paths["/api/v1/drivers/{driver_id}"]) == {"get", "patch"}


def test_the_retired_assignment_code_is_gone_and_vehicle_driver_is_not_a_readiness_prerequisite() -> None:
    import app.domain.driver as driver_module
    from app.repositories.base import Repository

    assert not hasattr(driver_module, "VehicleDriverAssignment")
    for name in ("create_vehicle_driver_assignment", "get_vehicle_driver_assignment",
                 "end_vehicle_driver_assignment", "list_vehicle_driver_assignments"):
        assert not hasattr(Repository, name), name
    for name in ("assign_driver", "end_assignment", "list_vehicle_driver_history"):
        assert not hasattr(DriverService, name), name
    assert not hasattr(schemas, "VEHICLE_DRIVER_SHEET")
    core = GoogleSheetsRepository._CORE_SCHEMAS  # noqa: SLF001
    assert "vehicle_driver" not in {schema.tab_name for schema in core}
    assert schemas.DRIVER_MASTER_SHEET in core  # Driver Master readiness is unchanged


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


@pytest.mark.asyncio
async def test_google_sheets_patch_via_driver_service_preserves_omitted_fields_in_the_stored_row() -> (
    None
):
    """Live UAT defect fix, Google-Sheets-backed: proves the actual
    STORED SHEET ROW (not merely the returned Driver object) retains
    omitted fields — exercised through `DriverService.update_driver`
    (the real PATCH-handling layer), not by calling
    `GoogleSheetsRepository.update_driver` directly (which is, and
    remains, a full-replace contract by design)."""
    ws = _ws(schemas.DRIVER_MASTER_SHEET)
    repo = _repo_with_fake_sheets(ws)
    service = DriverService(repo)

    created = await repo.create_driver(
        driver_name_th="UAT Driver Batch1 Fixed",
        phone="0812345678",
        license_no="UAT-LIC-002",
        license_expiry_date=date(2028, 6, 30),
        active_status="ZZZ_UAT_FIXED_STATUS",
        note_th="Phase 6 Batch 1 Live UAT after phone fix",
    )

    await service.update_driver(
        driver_id=created.driver_id,
        driver_name_th="UAT Driver Batch1 Fixed",
        phone="0890000123",
        license_no=None,
        license_expiry_date=None,
        active_status=None,
        note_th="Phase 6 Batch 1 PATCH Live UAT",
        fields_set=frozenset({"driver_name_th", "phone", "note_th"}),
    )

    header = schemas.DRIVER_MASTER_SHEET.required_headers
    stored_row = dict(zip(header, ws.rows[0]))
    assert str(stored_row["phone"]).lstrip("'") == "0890000123"
    assert stored_row["note_th"] == "Phase 6 Batch 1 PATCH Live UAT"
    # The raw sheet cells for omitted fields are exactly unchanged.
    assert stored_row["license_no"] == "UAT-LIC-002"
    assert stored_row["license_expiry_date"] == "2028-06-30"
    assert stored_row["active_status"] == "ZZZ_UAT_FIXED_STATUS"

    reread = await repo.get_driver(created.driver_id)
    assert reread is not None
    assert reread.license_no == "UAT-LIC-002"
    assert reread.license_expiry_date == date(2028, 6, 30)
    assert reread.active_status == "ZZZ_UAT_FIXED_STATUS"


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
async def test_google_sheets_missing_credentials_fails_explicitly_never_silently() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)
    with pytest.raises(RepositoryError, match="not configured"):
        await repo.get_driver("DRV-0001")
