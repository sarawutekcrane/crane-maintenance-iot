"""Phase 7 Batch 7D2 — certificate expiry report over Google Sheets,
exercised with the REAL installed gspread client on top of the FAKE HTTP
session from the 7B2 tests (`FakeSheetsBackend`): only the network
transport is faked; every value transformation (Worksheet.get,
fill_gaps, numericise_all with its ignore list, to_records) is gspread's
own code.

Covers the additive `text_only_headers` option of the shared validated
reader (DEC 8) and its unchanged default, structural validation of all
14 vehicle_certificate headers on the SAME values response, cell-value
classification after gspread numericising, mock/Sheets parity, measured
fake-transport request counts, and zero writes.

No credentials, no network, no live spreadsheet; request counts are
fake-transport counts, not live Sheets performance. All fixtures are
synthetic (SYN-* ids), not company fleet data.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import gspread
import pytest

from app.config import Settings
from app.domain.certificate_expiry_report_service import CertificateExpiryReportService
from app.domain.common import PageParams
from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate
from app.errors import ApiError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.google_sheets.client import GoogleSheetsClient
from tests.test_certificate_expiry_report_batch7d2 import _Clock, _SpyRepository
from tests.test_fleet_status_summary_sheets_batch7b2 import SHEET_ID, FakeSheetsBackend, _repo

CERT_TAB = schemas.VEHICLE_CERTIFICATE_SHEET.tab_name
HEADER = list(schemas.VEHICLE_CERTIFICATE_SHEET.required_headers)
URL = "/api/v1/reports/certificate-expiry"
AS_OF = date(2026, 3, 10)
TS = "2026-01-15T08:00:00+00:00"
PROTECTED = GoogleSheetsRepository._CERTIFICATE_TEXT_ONLY_HEADERS


def _row(cid: str, header: list[str] | None = None, **values: str) -> list[str]:
    cells = dict.fromkeys(HEADER, "")
    cells.update(
        certificate_id=cid,
        vehicle_id="SYN-VEH-1",
        certificate_type_code="SYN-TYPE-A",
        certificate_status="ACTIVE",
        created_at=TS,
    )
    cells.update(values)
    return [cells.get(h, "") for h in (header or HEADER)]


def _backend(rows: list[list[str]], header: list[str] | None = None, **extra_tabs) -> FakeSheetsBackend:
    tabs: dict[str, list[list[str]] | None] = {
        CERT_TAB: [list(header or HEADER), *rows],
        # Unrelated tabs the report must never read.
        "vehicle_master": [list(schemas.VEHICLE_SHEET.required_headers)],
        "repair_order": [list(schemas.REPAIR_SHEET.required_headers)],
    }
    tabs.update(extra_tabs)
    return FakeSheetsBackend(tabs)


async def _report(repo, clock=None, **kwargs):
    params = dict(mode="RANGE", expiry_from=None, expiry_to="2030-12-31", effective_status=None, page=1, page_size=200)
    params.update(kwargs)
    return await CertificateExpiryReportService(repo, clock or _Clock(AS_OF)).get_report(**params)


async def _report_error(repo, **kwargs) -> ApiError:
    with pytest.raises(ApiError) as info:
        await _report(repo, **kwargs)
    return info.value


def _assert_schema(err: ApiError, problem: str, headers: list[str] | None = None) -> None:
    assert (err.code, err.status_code) == ("VEHICLE_CERTIFICATE_SCHEMA_INVALID", 500)
    assert err.details["tab"] == CERT_TAB and err.details["problem"] == problem
    if headers is not None:
        assert err.details["headers"] == headers


def _assert_read_failed(err: ApiError) -> None:
    assert (err.code, err.status_code) == ("VEHICLE_CERTIFICATE_READ_FAILED", 503)
    assert err.details is None


async def _api(repo, path: str = URL, headers: dict[str, str] | None = None, clock=None):
    from tests.test_certificate_expiry_report_batch7d2 import _api as api

    return await api(repo, path, headers=headers, clock=clock or _Clock(AS_OF))


# ---------------------------------------------------------------------------
# DEC 8 — additive text_only_headers on the shared validated reader
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [schemas.VEHICLE_SHEET, schemas.REPAIR_SHEET, schemas.VEHICLE_CERTIFICATE_SHEET])
async def test_default_validated_read_is_unchanged_and_equals_get_all_records(schema) -> None:
    header = list(schema.required_headers)
    rows = [
        [f"0{i}{j}" if j % 2 else f"{i}.5" for j in range(len(header))] for i in range(3)
    ] + [["0042", "1,234", "3_2"]]
    backend = FakeSheetsBackend({schema.tab_name: [header, *rows]})
    repo = _repo(backend)
    default = await repo._client.read_header_and_records(schema)
    explicit = await repo._client.read_header_and_records(schema, text_only_headers=())
    ws = gspread.Client(None, session=backend).open_by_key(SHEET_ID).worksheet(schema.tab_name)
    assert default == explicit
    assert default.records == ws.get_all_records(head=1, default_blank="")
    assert any(isinstance(v, (int, float)) for r in default.records for v in r.values())
    assert repo._client._header_cache == {}  # neither used nor refreshed


@pytest.mark.asyncio
async def test_text_only_headers_protect_columns_resolved_from_the_same_response_header() -> None:
    # Physical order differs from the declared schema order.
    shuffled = list(reversed(HEADER))
    backend = _backend(
        [_row("00123", header=shuffled, vehicle_id="0042", certificate_type_code="007",
              document_no="000999", replaced_by_certificate_id="0001", storage_ref="1.50",
              certificate_type_name_th="12", alert_lead_days="7", expiry_date="20260115")],
        header=shuffled,
    )
    repo = _repo(backend)
    read = await repo._client.read_header_and_records(
        schemas.VEHICLE_CERTIFICATE_SHEET, text_only_headers=PROTECTED
    )
    record = read.records[0]
    for name, text in (("certificate_id", "00123"), ("vehicle_id", "0042"), ("certificate_type_code", "007"),
                       ("document_no", "000999"), ("replaced_by_certificate_id", "0001"), ("storage_ref", "1.50")):
        assert record[name] == text and isinstance(record[name], str)
    # Unprotected columns keep gspread's numericising.
    assert (record["certificate_type_name_th"], record["alert_lead_days"], record["expiry_date"]) == (12, 7, 20260115)
    # A name absent from the response header is skipped, as in read_rows.
    again = await repo._client.read_header_and_records(
        schemas.VEHICLE_CERTIFICATE_SHEET, text_only_headers=("no_such_column", "document_no")
    )
    assert again.records[0]["document_no"] == "000999"
    assert repo._client._header_cache == {}


def test_installed_gspread_ignore_positions_are_one_indexed() -> None:
    assert gspread.utils.numericise_all(["01", "02", "03"], False, "", False, [2]) == [1, "02", 3]
    assert GoogleSheetsClient._numericise_ignore_columns(("a", "b", "c"), ("c", "x", "a")) == [3, 1]


@pytest.mark.asyncio
async def test_legacy_read_rows_and_header_cache_are_unchanged() -> None:
    backend = _backend([_row("00123", document_no="000999")])
    repo = _repo(backend)
    rows = await repo._client.read_rows(schemas.VEHICLE_CERTIFICATE_SHEET, text_only_headers=PROTECTED)
    assert rows[0]["document_no"] == "000999"
    assert CERT_TAB in repo._client._header_cache  # legacy path still uses its cache


# ---------------------------------------------------------------------------
# Structural validation (whole-request failure, never a 200)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header", "missing"),
    [
        (["Status" if h == "certificate_status" else h for h in HEADER], ["certificate_status"]),
        (["expiry" if h == "expiry_date" else h for h in HEADER], ["expiry_date"]),
        ([h.upper() for h in HEADER], HEADER),
        ([f" {h}" if h == "certificate_id" else h for h in HEADER], ["certificate_id"]),
        ([h for h in HEADER if h != "note_th"], ["note_th"]),
    ],
)
async def test_renamed_or_missing_headers_fail_the_whole_report(header, missing) -> None:
    rows = [[f"SYN-{i}"] + ["x"] * (len(header) - 1) for i in range(3)]
    err = await _report_error(_repo(_backend(rows, header=header)))
    _assert_schema(err, "MISSING_HEADERS", missing)


@pytest.mark.asyncio
async def test_legacy_list_shows_why_structural_checks_matter() -> None:
    header = ["Status" if h == "certificate_status" else h for h in HEADER]
    repo = _repo(_backend([_row("SYN-1", header=header, Status="REPLACED")], header=header))
    legacy = await repo.list_vehicle_certificates_for_vehicle("SYN-VEH-1")
    assert legacy[0].certificate_status is None  # legacy silently reads a blank status
    _assert_schema(await _report_error(repo), "MISSING_HEADERS", ["certificate_status"])


@pytest.mark.asyncio
async def test_duplicate_headers_data_outside_header_and_no_header_row() -> None:
    dup = _backend([[*_row("SYN-1"), "ACTIVE"]], header=[*HEADER, "certificate_status"])
    _assert_schema(await _report_error(_repo(dup)), "DUPLICATE_HEADERS", ["certificate_status"])
    outside = _backend([[*_row("SYN-1"), "stray"]])
    _assert_schema(await _report_error(_repo(outside)), "DATA_OUTSIDE_HEADER")
    unnamed_data = _backend([[*_row("SYN-1"), "", "stray"]], header=[*HEADER, "note", ""])
    _assert_schema(await _report_error(_repo(unnamed_data)), "DATA_OUTSIDE_HEADER")
    _assert_schema(await _report_error(_repo(FakeSheetsBackend({CERT_TAB: None}))), "NO_HEADER_ROW")
    blank = FakeSheetsBackend({CERT_TAB: [[""] * 4, _row("SYN-1")]})
    _assert_schema(await _report_error(_repo(blank)), "NO_HEADER_ROW")


@pytest.mark.asyncio
async def test_single_unused_unnamed_column_and_named_extras_are_tolerated() -> None:
    backend = _backend([[*_row("SYN-1", expiry_date="2026-05-01"), "", "memo"]], header=[*HEADER, "", "memo"])
    report = await _report(_repo(backend))
    assert [i.certificate_id for i in report.items] == ["SYN-1"] and report.complete


@pytest.mark.asyncio
async def test_genuine_empty_and_phantom_only_sheets() -> None:
    empty = await _report(_repo(_backend([])))
    assert (empty.items, empty.total_items, empty.complete, empty.population.read_record_count) == ([], 0, True, 0)
    rows = [[""] * len(HEADER)] * 30 + [["   "] * len(HEADER), [*([""] * len(HEADER)), "memo only"]]
    phantom = await _report(_repo(_backend(rows, header=[*HEADER, "memo"])))
    assert phantom.population.read_record_count == 0 and phantom.complete


@pytest.mark.asyncio
async def test_cold_missing_tab_warm_failure_unconfigured_and_values_failure() -> None:
    _assert_schema(await _report_error(_repo(FakeSheetsBackend({"vehicle_master": [["vehicle_id"]]}))), "TAB_MISSING")

    backend = _backend([_row("SYN-1", expiry_date="2026-05-01")])
    repo = _repo(backend)
    assert (await _report(repo)).total_items == 1
    del backend.tabs[CERT_TAB]
    _assert_read_failed(await _report_error(repo))  # warm: never claimed as a missing tab

    unconfigured = GoogleSheetsRepository(Settings(google_sheet_id="", google_application_credentials=""))
    _assert_read_failed(await _report_error(unconfigured))

    failing = _backend([_row("SYN-1")])
    failing.fail_values_get = True
    _assert_read_failed(await _report_error(_repo(failing)))


# ---------------------------------------------------------------------------
# Cell values after the real gspread transformation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_and_expiry_cell_classification_over_sheets() -> None:
    cases = {
        # certificate_id: (status cell, expiry cell, expected bucket-ish outcome)
        "S-BLANK": ("", "2026-05-01"),
        "S-SPACE": (" ", "2026-05-01"),
        "S-ZERO": ("0", "2026-05-01"),
        "S-LOWER": ("active", "2026-05-01"),
        "S-TRAIL": ("ACTIVE ", "2026-05-01"),
        "S-TRUE": ("TRUE", "2026-05-01"),
        "E-BLANK": ("ACTIVE", ""),
        "E-SPACE": ("ACTIVE", " "),
        "E-ZERO": ("ACTIVE", "0"),
        "E-ZEROF": ("ACTIVE", "0.0"),
        "E-BAD": ("ACTIVE", "2026-02-30"),
        "E-SLASH": ("ACTIVE", "01/05/2026"),
        "E-COMPACT": ("ACTIVE", "20260501"),
        "E-WEEK": ("ACTIVE", "2026-W18-5"),
        "E-OK": ("ACTIVE", "2026-05-01"),
        "R-BADDATE": ("REPLACED", "0"),
    }
    rows = [_row(cid, certificate_status=s, expiry_date=e) for cid, (s, e) in cases.items()]
    report = await _report(_repo(_backend(rows)))
    assert sorted(i.certificate_id for i in report.items) == ["E-COMPACT", "E-OK", "E-WEEK"]
    assert {i.certificate_id: i.expiry_date for i in report.items} == {
        "E-COMPACT": date(2026, 5, 1), "E-OK": date(2026, 5, 1), "E-WEEK": date(2026, 5, 1),
    }
    missing = await _report(_repo(_backend(rows)), mode="MISSING_EXPIRY_DATE", expiry_to=None)
    assert [i.certificate_id for i in missing.items] == ["E-BLANK"]
    p = report.population
    assert (p.excluded_status_blank_count, p.excluded_replaced_count, p.excluded_rows_with_other_defects) == (1, 1, 1)
    assert p.issue_row_count == 5 + 5  # 5 unrecognized statuses + 5 invalid expiry cells
    assert report.data_issues.issue_defect_counts == {"INVALID_EXPIRY_DATE": 5, "UNRECOGNIZED_STATUS": 5}
    assert report.complete is False


@pytest.mark.asyncio
async def test_leading_zero_and_numeric_looking_identifiers_are_preserved() -> None:
    rows = [
        _row("00123", vehicle_id="0042", certificate_type_code="007", document_no="000999", expiry_date="2026-05-01"),
        _row("1,234", vehicle_id="1.50", certificate_type_code="3_2", document_no="0", expiry_date="2026-05-01"),
    ]
    report = await _report(_repo(_backend(rows)))
    items = {i.certificate_id: i for i in report.items}
    assert set(items) == {"00123", "1,234"}
    assert (items["00123"].vehicle_id, items["00123"].certificate_type_code, items["00123"].document_no) == ("0042", "007", "000999")
    assert (items["1,234"].vehicle_id, items["1,234"].certificate_type_code, items["1,234"].document_no) == ("1.50", "3_2", "0")
    body = (await _api(_repo(_backend(rows)), f"{URL}?expiry_to=2030-01-01")).json()
    assert {i["document_no"] for i in body["items"]} == {"000999", "0"}


@pytest.mark.asyncio
async def test_numeric_unprotected_cells_are_unmappable_rows_via_the_unchanged_mapper() -> None:
    rows = [
        _row("SYN-NAME", certificate_type_name_th="12", expiry_date="2026-05-01"),  # numericised -> int -> str field
        _row("SYN-LEAD", alert_lead_days="abc", expiry_date="2026-05-01"),
        _row("SYN-CREATED", created_at="2026", expiry_date="2026-05-01"),
        _row("SYN-OK", certificate_type_name_th="ใบอนุญาต", expiry_date="2026-05-01"),
    ]
    report = await _report(_repo(_backend(rows)))
    assert [i.certificate_id for i in report.items] == ["SYN-OK"]
    assert report.items[0].certificate_type_name_th == "ใบอนุญาต"
    assert report.data_issues.issue_defect_counts == {"UNMAPPABLE_ROW": 3}


@pytest.mark.asyncio
async def test_mock_and_sheets_parity_including_missing_type_and_links() -> None:
    created = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    spec = [
        dict(cid="SYN-1", vid="SYN-VEH-1", type_code=None, status="ACTIVE", expiry="2026-03-09", doc="0012"),
        dict(cid="SYN-2", vid="SYN-VEH-1", type_code="SYN-T", status="ACTIVE", expiry=None, link="SYN-9"),
        dict(cid="SYN-3", vid="SYN-VEH-1", type_code="SYN-T", status="EXPIRED", expiry="2026-03-10"),
        dict(cid="SYN-4", vid="SYN-VEH-2", type_code="SYN-T", status="REPLACED", expiry="2026-01-01", link="SYN-404"),
        dict(cid="SYN-5", vid="SYN-VEH-2", type_code="SYN-T", status=None, expiry="2026-04-01"),
        dict(cid="SYN-1", vid="", type_code="SYN-T", status="ACTIVE", expiry="2026-03-11", name="ชื่อ"),
        dict(cid="SYN-6", vid="SYN-VEH-3", type_code="SYN-T", status="REPLACED", expiry=None, link=None),
    ]
    typed = [
        VehicleCertificate(
            certificate_id=s["cid"], vehicle_id=s["vid"], certificate_type_code=s["type_code"],
            certificate_type_name_th=s.get("name"), document_no=s.get("doc"),
            expiry_date=date.fromisoformat(s["expiry"]) if s["expiry"] else None,
            certificate_status=CertificateStatus(s["status"]) if s["status"] else None,
            replaced_by_certificate_id=s.get("link"), created_at=created,
        )
        for s in spec
    ]
    mock = _SpyRepository(sorted(typed, key=lambda c: c.vehicle_id))  # mock storage order is per vehicle
    sheet_rows = [
        _row(c.certificate_id, vehicle_id=c.vehicle_id, certificate_type_code=c.certificate_type_code or "",
             certificate_type_name_th=c.certificate_type_name_th or "", document_no=c.document_no or "",
             expiry_date=c.expiry_date.isoformat() if c.expiry_date else "",
             certificate_status=c.certificate_status.value if c.certificate_status else "",
             replaced_by_certificate_id=c.replaced_by_certificate_id or "", created_at=created.isoformat())
        for c in sorted(typed, key=lambda c: c.vehicle_id)
    ]
    sheets = _repo(_backend(sheet_rows))
    for query in ("", "?expiry_from=2000-01-01&expiry_to=2030-01-01", "?mode=MISSING_EXPIRY_DATE",
                  "?expiry_to=2030-01-01&effective_status=EXPIRED", "?expiry_to=2030-01-01&page=2&page_size=1"):
        a = await _api(mock, URL + query)
        b = await _api(sheets, URL + query)
        assert a.status_code == b.status_code == 200
        assert a.json() == b.json(), query
    body = (await _api(sheets, URL + "?expiry_to=2030-01-01")).json()
    assert body["population"]["replaced_link_observations"] == 2
    assert {i["certificate_id"]: i["flags"] for i in body["items"] if i["vehicle_id"] == ""} == {
        "SYN-1": ["DUPLICATE_CERTIFICATE_ID", "BLANK_VEHICLE_ID"]
    }


# ---------------------------------------------------------------------------
# Measured fake-transport request counts and zero writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_measured_request_counts_cold_spreadsheet_cached_and_warm() -> None:
    """Measured (fake transport; counts only, no latency):
    cold 2 metadata + 1 values; spreadsheet cached 1 metadata + 1 values;
    fully warm 1 values. Only the vehicle_certificate tab is read."""
    backend = _backend([_row("SYN-1", expiry_date="2026-05-01")])
    repo = _repo(backend)
    await _report(repo)
    cold = list(backend.requests)
    assert (backend.metadata_reads(), backend.values_reads(CERT_TAB), backend.values_reads()) == (2, 1, 1)

    backend2 = _backend([_row("SYN-1", expiry_date="2026-05-01")])
    repo2 = _repo(backend2)
    await repo2._client.read_header_and_records(schemas.VEHICLE_SHEET)  # caches the spreadsheet only
    backend2.requests.clear()
    await _report(repo2)
    cached = list(backend2.requests)
    assert (backend2.metadata_reads(), backend2.values_reads(CERT_TAB), backend2.values_reads()) == (1, 1, 1)

    backend.requests.clear()
    await _report(repo)
    assert backend.requests == [("get", "values", CERT_TAB)]
    assert cold == [("get", "metadata", None), ("get", "metadata", None), ("get", "values", CERT_TAB)]
    assert cached == [("get", "metadata", None), ("get", "values", CERT_TAB)]
    assert backend.writes == [] and backend2.writes == []


_ZERO_WRITE_SCENARIOS = {
    "valid": lambda: _backend([_row("SYN-1", expiry_date="2026-03-01"), _row("SYN-2", certificate_status="REPLACED")]),
    "stale_active": lambda: _backend([_row("SYN-STALE", expiry_date="2020-01-01")]),
    "partial": lambda: _backend([_row("SYN-1", certificate_status="bad"), _row("SYN-2", expiry_date="0")]),
    "empty": lambda: _backend([]),
    "renamed_status": lambda: _backend([_row("SYN-1")], header=["Status" if h == "certificate_status" else h for h in HEADER]),
    "data_outside_header": lambda: _backend([[*_row("SYN-1"), "x"]]),
    "tab_missing": lambda: FakeSheetsBackend({"vehicle_master": [["vehicle_id"]]}),
    "read_error": lambda: (lambda b: (setattr(b, "fail_values_get", True), b)[1])(_backend([_row("SYN-1")])),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(_ZERO_WRITE_SCENARIOS))
async def test_report_never_writes_and_reads_only_the_certificate_tab(scenario: str) -> None:
    backend = _ZERO_WRITE_SCENARIOS[scenario]()
    before = backend.snapshot()
    for query in ("", "?mode=MISSING_EXPIRY_DATE", "?expiry_from=2031-01-01", "?page=7"):
        await _api(_repo(backend), URL + query)
    assert backend.writes == []
    assert backend.snapshot() == before
    assert all(method == "get" for method, _, _ in backend.requests)
    assert {tab for _, kind, tab in backend.requests if kind == "values"} <= {CERT_TAB}


@pytest.mark.asyncio
async def test_report_does_not_call_legacy_repository_reads_or_reconciliation() -> None:
    backend = _backend([_row("SYN-STALE", expiry_date="2020-01-01")])
    repo = _repo(backend)
    called: list[str] = []
    for name in ("list_vehicle_certificates_for_vehicle", "get_vehicle_certificate", "get_vehicle",
                 "mark_vehicle_certificate_expired", "mark_vehicle_certificate_replaced", "list_vehicles"):
        async def spy(*args, _name=name, **kwargs):
            called.append(_name)
            raise AssertionError(_name)
        setattr(repo, name, spy)
    for method in ("read_rows", "find_row", "update_row", "append_row"):
        async def client_spy(*args, _name=method, **kwargs):
            called.append(_name)
            raise AssertionError(_name)
        setattr(repo._client, method, client_spy)
    report = await _report(repo, expiry_to=None)
    assert report.items[0].effective_status == "EXPIRED" and report.items[0].stored_status == "ACTIVE"
    assert called == []


@pytest.mark.asyncio
async def test_denied_request_performs_zero_transport_requests() -> None:
    backend = _backend([_row("SYN-1")])
    response = await _api(_repo(backend), URL, headers={"X-Dev-Role": "UNKNOWN"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "HTTP_ERROR"
    assert backend.requests == [] and backend.writes == []


@pytest.mark.asyncio
async def test_api_error_envelopes_over_sheets_carry_no_report_data() -> None:
    failing = _backend([_row("SYN-1")])
    failing.fail_values_get = True
    cases = [
        (_backend([_row("SYN-1")], header=[h.upper() for h in HEADER]), 500, "VEHICLE_CERTIFICATE_SCHEMA_INVALID"),
        (failing, 503, "VEHICLE_CERTIFICATE_READ_FAILED"),
        (FakeSheetsBackend({"vehicle_master": [["vehicle_id"]]}), 500, "VEHICLE_CERTIFICATE_SCHEMA_INVALID"),
    ]
    for backend, status_code, code in cases:
        response = await _api(_repo(backend), URL)
        assert response.status_code == status_code
        body = response.json()
        assert list(body) == ["error"] and body["error"]["code"] == code
        for leaked in ("SYN-1", "total_items", "population", "items", "fake.json", "Traceback"):
            assert leaked not in response.text


@pytest.mark.asyncio
async def test_existing_7b2_and_7c2_validated_reads_keep_their_behavior() -> None:
    """Default parity through the real callers (full 7B2/7C2 suites also run unchanged)."""
    from app.domain.vehicle_service import VehicleService

    vehicle_tab = schemas.VEHICLE_SHEET.tab_name
    header = list(schemas.VEHICLE_SHEET.required_headers)
    ok = _repo(FakeSheetsBackend({vehicle_tab: [header, ["VEH-1", "M-1", "MDL-1", "", "READY", TS, TS]]}))
    assert (await VehicleService(ok).get_fleet_status_summary()).vehicle_total == 1

    # A numeric-looking vehicle id is still numericised by the DEFAULT
    # validated read (no columns protected), so 7B2 still fails closed on
    # it exactly as before this batch: the option is opt-in only.
    numeric = _repo(FakeSheetsBackend({vehicle_tab: [header, ["0123", "M-1", "MDL-1", "", "READY", TS, TS]]}))
    read = await numeric._client.read_header_and_records(schemas.VEHICLE_SHEET)
    assert read.records[0]["vehicle_id"] == 123
    with pytest.raises(ApiError) as info:
        await VehicleService(numeric).get_fleet_status_summary()
    assert info.value.code == "VEHICLE_MASTER_DATA_INVALID"
    assert info.value.details["issue_counts"] == {"UNMAPPABLE_ROW": 1}

    repair_tab = schemas.REPAIR_SHEET.tab_name
    repair_header = list(schemas.REPAIR_SHEET.required_headers)
    repair_row = dict.fromkeys(repair_header, "")
    repair_row.update(repair_id="SYN-RPR-1", asset_type="VEHICLE", asset_id="SYN-VEH-1",
                      source_type="MANUAL", status="OPEN", opened_at=TS)
    repairs = _repo(FakeSheetsBackend({
        repair_tab: [repair_header, [repair_row[h] for h in repair_header]],
        schemas.REPAIR_ACTION_SHEET.tab_name: [list(schemas.REPAIR_ACTION_SHEET.required_headers)],
    }))
    items, total = await repairs.list_open_repairs_for_report(None, PageParams(page=1, page_size=5))
    assert total == 1 and items[0].repair_id == "SYN-RPR-1"


# ---------------------------------------------------------------------------
# Review finding (Batch 7D2): malformed alert_lead_days cells "inf", "-inf",
# "1e309" are numericised by gspread into non-finite floats; the UNCHANGED
# legacy mapper then raises OverflowError. The report must classify that as a
# row mapping defect with the approved bucket precedence and still answer 200.
# ---------------------------------------------------------------------------


def _overflow_rows() -> list[list[str]]:
    return [
        _row("SYN-OK", expiry_date="2026-05-01", alert_lead_days="7"),
        _row("00101", certificate_status="ACTIVE", expiry_date="2026-05-01", alert_lead_days="inf"),
        _row("00102", certificate_status="EXPIRED", expiry_date="2026-02-01", alert_lead_days="-inf"),
        _row("00103", certificate_status="REPLACED", expiry_date="2026-05-01", alert_lead_days="1e309"),
        _row("00104", certificate_status="", expiry_date="2026-05-01", alert_lead_days="inf"),
        _row("00105", certificate_status="Active", expiry_date="2026-05-01", alert_lead_days="1e309"),
    ]


def _assert_equations(body: dict) -> None:
    p = body["population"]
    assert p["read_record_count"] == (
        p["in_scope_count"] + p["excluded_replaced_count"] + p["excluded_status_blank_count"] + p["issue_row_count"]
    )
    assert p["in_scope_count"] == p["in_scope_with_expiry_date_count"] + p["in_scope_without_expiry_date_count"]
    assert body["complete"] == (p["issue_row_count"] == 0)


@pytest.mark.asyncio
async def test_overflowing_alert_lead_days_gives_a_partial_report_over_sheets_api() -> None:
    backend = _backend(_overflow_rows())
    before = backend.snapshot()
    response = await _api(_repo(backend), f"{URL}?expiry_to=2030-12-31")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [i["certificate_id"] for i in body["items"]] == ["SYN-OK"]  # the valid row stays visible
    assert body["total_items"] == 1 and body["complete"] is False
    assert body["population"] == {
        "read_record_count": 6,
        "in_scope_count": 1,
        "in_scope_with_expiry_date_count": 1,
        "in_scope_without_expiry_date_count": 0,
        "excluded_replaced_count": 1,
        "excluded_status_blank_count": 1,
        "issue_row_count": 3,  # ACTIVE, EXPIRED, unknown status (one issue row, two defects)
        "excluded_rows_with_other_defects": 2,  # REPLACED and blank status, still excluded
        "replaced_link_observations": 1,
    }
    assert body["data_issues"]["issue_defect_counts"] == {"UNMAPPABLE_ROW": 3, "UNRECOGNIZED_STATUS": 1}
    assert body["data_issues"]["sample_certificate_ids"] == ["00101", "00102", "00105"]  # raw ids, leading zeros kept
    assert body["data_issues"]["issue_rows_without_usable_id"] == 0
    _assert_equations(body)
    assert backend.writes == [] and backend.snapshot() == before
    assert {tab for _, kind, tab in backend.requests if kind == "values"} == {CERT_TAB}
    assert backend.values_reads() == 1


@pytest.mark.asyncio
async def test_all_unreadable_in_scope_overflow_rows_give_an_explicit_incomplete_empty() -> None:
    rows = [
        _row("00201", certificate_status="ACTIVE", expiry_date="2026-05-01", alert_lead_days="inf"),
        _row("00202", certificate_status="EXPIRED", expiry_date="2026-05-01", alert_lead_days="-inf"),
    ]
    backend = _backend(rows)
    response = await _api(_repo(backend), f"{URL}?expiry_to=2030-12-31")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["items"], body["total_items"], body["complete"]) == ([], 0, False)
    assert body["population"]["issue_row_count"] == 2 and body["population"]["in_scope_count"] == 0
    assert body["data_issues"]["issue_defect_counts"] == {"UNMAPPABLE_ROW": 2}
    _assert_equations(body)
    assert backend.writes == []


@pytest.mark.asyncio
async def test_excluded_only_overflow_rows_do_not_make_the_report_incomplete() -> None:
    rows = [
        _row("SYN-OK", expiry_date="2026-05-01"),
        _row("00301", certificate_status="REPLACED", replaced_by_certificate_id="SYN-OK", alert_lead_days="1e309"),
        _row("00302", certificate_status="", alert_lead_days="inf"),
    ]
    backend = _backend(rows)
    for query in ("?expiry_to=2030-12-31", "?mode=MISSING_EXPIRY_DATE"):
        response = await _api(_repo(backend), URL + query)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["complete"] is True
        p = body["population"]
        assert (p["issue_row_count"], p["excluded_replaced_count"], p["excluded_status_blank_count"]) == (0, 1, 1)
        assert p["excluded_rows_with_other_defects"] == 2
        assert body["data_issues"]["issue_defect_counts"] == {}
        _assert_equations(body)
    assert backend.writes == []


@pytest.mark.asyncio
async def test_unexpected_mapper_fault_still_uses_the_existing_internal_error_path() -> None:
    backend = _backend([_row("SYN-1", certificate_status="REPLACED")])
    repo = _repo(backend)

    def broken(_: dict):
        raise RuntimeError("programming fault")

    repo._vehicle_certificate_from_row = broken  # type: ignore[method-assign]
    response = await _api(repo, URL)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "population" not in response.text and "programming fault" not in response.text
    assert backend.writes == []
