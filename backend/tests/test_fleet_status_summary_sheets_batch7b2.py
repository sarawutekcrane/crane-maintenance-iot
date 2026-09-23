"""Phase 7 Batch 7B2 — fleet status summary over Google Sheets, exercised
with the REAL installed gspread (`gspread.Client` -> `Spreadsheet` ->
`Worksheet.get` / `get_all_records` / `row_values`, and gspread.utils'
`fill_gaps` / `numericise_all` / `to_records`) on top of a FAKE HTTP
session. Only the network transport is faked: every value transformation
the legacy `read_rows` path and the new validated read apply is gspread's
own code, so list/summary parity below is checked against an independent
oracle (the real `get_all_records`), not a hand-written copy of it.

No credentials, no network, no live spreadsheet. The fake session records
every request; any non-GET request is recorded as a write and answered
with an error, so a write attempt can never succeed silently.
All fixtures are synthetic (SYN-/VEH- test ids), not company fleet data.
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from urllib.parse import unquote

import gspread
import gspread.utils
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.domain.common import OperationalStatus, PageParams
from app.domain.vehicle_service import VehicleService
from app.errors import ApiError
from app.repositories.base import RepositoryError, RepositorySchemaError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.google_sheets.client import GoogleSheetsClient

SHEET_ID = "fake-sheet-id"
VEHICLE_TAB = schemas.VEHICLE_SHEET.tab_name
HEADER = list(schemas.VEHICLE_SHEET.required_headers)
TS = "2026-01-15T08:00:00+00:00"
STATUSES = [s.value for s in OperationalStatus]


# ---------------------------------------------------------------------------
# Fake transport under the real gspread client
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: dict, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


class FakeSheetsBackend:
    """In-memory spreadsheet served through a requests-like session.

    `tabs` maps a tab title to its raw values exactly as the Sheets API
    would return them (list of row lists of strings; ragged rows allowed;
    `None` = a tab with no values at all). Every request is logged in
    `requests` as (method, kind, tab); `writes` collects any non-GET."""

    _VALUES_RE = re.compile(r"/spreadsheets/([^/]+)/values/(.+)$")
    _META_RE = re.compile(r"/spreadsheets/([^/]+)$")

    def __init__(self, tabs: dict[str, list[list[str]] | None]) -> None:
        self.tabs = tabs
        self.requests: list[tuple[str, str, str | None]] = []
        self.writes: list[tuple[str, str]] = []
        self.fail_values_get = False
        self.before_values_get: Callable[[str, str | None], None] | None = None

    # requests.Session.request signature subset used by gspread.HTTPClient
    def request(self, method, url, json=None, params=None, data=None, files=None, headers=None, timeout=None):  # noqa: A002, ARG002
        method = method.lower()
        if method != "get":
            self.writes.append((method, url))
            return _FakeResponse({"error": {"code": 403, "message": "writes are not allowed", "status": "PERMISSION_DENIED"}}, 403)
        values = self._VALUES_RE.search(url)
        if values:
            rng = unquote(values.group(2))
            tab, _, cells = rng.partition("!")
            tab = tab.strip("'").replace("''", "'")
            self.requests.append(("get", "values", tab))
            if self.before_values_get is not None:
                self.before_values_get(tab, cells or None)
            if self.fail_values_get:
                return _FakeResponse({"error": {"code": 500, "message": "backend error", "status": "INTERNAL"}}, 500)
            if tab not in self.tabs:
                return _FakeResponse({"error": {"code": 400, "message": "Unable to parse range", "status": "INVALID_ARGUMENT"}}, 400)
            rows = self.tabs[tab]
            body: dict = {"range": f"{tab}!A1:Z1000", "majorDimension": "ROWS"}
            if rows is not None:
                row_range = re.fullmatch(r"A(\d+):(\d+)", cells) if cells else None
                if row_range:
                    n = int(row_range.group(1))
                    rows = rows[n - 1 : n]
                if rows:
                    body["values"] = copy.deepcopy(rows)
            return _FakeResponse(body)
        if self._META_RE.search(url):
            self.requests.append(("get", "metadata", None))
            return _FakeResponse(
                {
                    "properties": {"title": "fake spreadsheet"},
                    "sheets": [
                        {"properties": {"title": title, "sheetId": i, "index": i}}
                        for i, title in enumerate(self.tabs)
                    ],
                }
            )
        self.requests.append(("get", "other", url))
        return _FakeResponse({"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}}, 404)

    def values_reads(self, tab: str | None = None) -> int:
        return sum(1 for m, kind, t in self.requests if kind == "values" and (tab is None or t == tab))

    def metadata_reads(self) -> int:
        return sum(1 for _, kind, _ in self.requests if kind == "metadata")

    def snapshot(self) -> dict:
        return copy.deepcopy(self.tabs)


def _repo(backend: FakeSheetsBackend) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(
        Settings(google_sheet_id=SHEET_ID, google_application_credentials="fake.json")
    )
    repo._client._gspread_client = gspread.Client(None, session=backend)  # type: ignore[attr-defined]
    return repo


def _row(vid: str, status: str = "READY", machine: str | None = None, model: str = "MDL-1", serial: str = "", created: str = TS, updated: str = TS) -> list[str]:
    return [vid, machine if machine is not None else f"M-{vid}", model, serial, status, created, updated]


def _backend(rows: list[list[str]], header: list[str] | None = None, **extra_tabs) -> FakeSheetsBackend:
    tabs: dict[str, list[list[str]] | None] = {VEHICLE_TAB: [list(header or HEADER), *rows]}
    tabs.update(extra_tabs)
    return FakeSheetsBackend(tabs)


async def _summary(repo: GoogleSheetsRepository):
    return await VehicleService(repo).get_fleet_status_summary()


async def _list_total(repo: GoogleSheetsRepository, status: OperationalStatus | None = None) -> int:
    _, total = await repo.list_vehicles(q=None, operational_status=status, model_id=None, params=PageParams(page=1, page_size=1))
    return total


async def _assert_parity(repo: GoogleSheetsRepository) -> None:
    summary = await _summary(repo)
    assert summary.vehicle_total == await _list_total(repo)
    for status in OperationalStatus:
        assert summary.status_counts[status.value] == await _list_total(repo, status)


async def _api_error(repo: GoogleSheetsRepository) -> ApiError:
    with pytest.raises(ApiError) as info:
        await _summary(repo)
    return info.value


# ---------------------------------------------------------------------------
# LIB — installed library facts the design depends on (LIB-1..LIB-7)
# ---------------------------------------------------------------------------


def test_lib_versions_are_the_declared_major_versions() -> None:
    import pydantic

    assert gspread.__version__.startswith("6.")
    assert pydantic.VERSION.startswith("2.")


@pytest.mark.asyncio
async def test_lib1_validated_read_sends_the_same_values_request_as_get_all_records() -> None:
    backend = _backend([_row("VEH-1")])
    repo = _repo(backend)
    await repo._client.read_rows(schemas.VEHICLE_SHEET)  # warm spreadsheet/worksheet/header
    legacy_log: list[dict] = []
    new_log: list[dict] = []
    original = backend.request

    def spy(log):
        def request(method, url, json=None, params=None, **kw):
            log.append({"method": method, "url": url, "params": dict(params or {})})
            return original(method, url, json=json, params=params, **kw)
        return request

    backend.request = spy(legacy_log)  # type: ignore[method-assign]
    await repo._client.read_rows(schemas.VEHICLE_SHEET)
    backend.request = spy(new_log)  # type: ignore[method-assign]
    await repo._client.read_header_and_records(schemas.VEHICLE_SHEET)
    assert len(legacy_log) == 1 and len(new_log) == 1
    assert new_log == legacy_log
    assert new_log[0]["params"] == {"majorDimension": None, "valueRenderOption": None, "dateTimeRenderOption": None}


def test_lib2_to_lib5_gspread_helpers_behave_as_the_design_assumes() -> None:
    utils = gspread.utils
    # LIB-2: numericise_all with get_all_records' defaults.
    assert utils.numericise_all(["0123", "1,234", "3_2", "2026", "1.5", "", "VEH-1"], False, "", False, []) == [123, 1234, "3_2", 2026, 1.5, "", "VEH-1"]
    # LIB-3: ragged rows are right-padded with "" to the widest row (header too).
    assert utils.fill_gaps([["a", "b", "c"], ["1"]]) == [["a", "b", "c"], ["1", "", ""]]
    assert utils.fill_gaps([["a"], ["1", "x"]]) == [["a", ""], ["1", "x"]]
    # LIB-4: to_records is the public records helper get_all_records uses.
    assert utils.to_records(["a", "b"], [[1, 2]]) == [{"a": 1, "b": 2}]


def test_lib5_get_all_records_rejects_duplicate_and_multiple_blank_headers() -> None:
    for header, row in ((["a", "a"], ["1", "2"]), (["a", "", ""], ["1", "", ""])):
        backend = FakeSheetsBackend({"t": [header, row]})
        ws = gspread.Client(None, session=backend).open_by_key(SHEET_ID).worksheet("t")
        with pytest.raises(gspread.exceptions.GSpreadException, match="duplicates"):
            ws.get_all_records()
    # A single blank header is accepted by gspread: its data lands under "".
    backend = FakeSheetsBackend({"t": [["a", "", "c"], ["1", "hidden", "3"]]})
    ws = gspread.Client(None, session=backend).open_by_key(SHEET_ID).worksheet("t")
    assert ws.get_all_records() == [{"a": 1, "": "hidden", "c": 3}]


@pytest.mark.asyncio
async def test_lib6_missing_tab_is_worksheet_not_found_preserved_as_cause() -> None:
    repo = _repo(FakeSheetsBackend({"other": [["x"]]}))
    with pytest.raises(RepositoryError) as info:
        await repo._client.read_rows(schemas.VEHICLE_SHEET)
    assert isinstance(info.value.__cause__, gspread.exceptions.WorksheetNotFound)


def test_lib7_pydantic_rejects_numbers_for_str_fields_with_a_value_error() -> None:
    from pydantic import ValidationError

    from app.domain.vehicle import Vehicle

    with pytest.raises(ValidationError) as info:
        Vehicle(vehicle_id="V", machine_no=1234, model_id="M", operational_status="READY", created_at=TS, updated_at=TS)  # type: ignore[arg-type]
    assert isinstance(info.value, ValueError)


# ---------------------------------------------------------------------------
# P1 — record-construction parity with the legacy read (real gspread path)
# ---------------------------------------------------------------------------

_P1_HEADER = [*HEADER, "note"]
_P1_ROWS = [
    ["VEH-1", "220/1", "MDL-1", "", "READY", TS, TS, "x"],
    ["0123", "1234", "MDL-2", "SN-1", "WORKING", "2026", "not-a-date"],   # numeric-looking id/machine/date
    ["VEH-3", "1,234", "3_2", "", "MAINTENANCE", "", ""],                 # comma/underscore numerics, blanks
    ["VEH-4", "M-4", "MDL-1"],                                            # ragged: trailing cells missing
    ["", "", "", "", "", "", "", "only-note"],                            # phantom (data only in named extra column)
    ["", "", "", "", "", "", ""],                                         # phantom (blank)
    ["VEH-5", "M-5", "MDL-1", "", "LONG_TERM_PARKING", TS, TS, "1.5"],
    ["  ", "", "", "", "", "", ""],                                        # whitespace-only id cell: canonical-blank phantom
]


@pytest.mark.asyncio
async def test_p1_validated_records_equal_legacy_read_rows_records() -> None:
    backend = FakeSheetsBackend({VEHICLE_TAB: [_P1_HEADER, *_P1_ROWS]})
    client = _repo(backend)._client
    legacy = await client.read_rows(schemas.VEHICLE_SHEET)          # real get_all_records + filter
    read = await client.read_header_and_records(schemas.VEHICLE_SHEET)
    filtered = [r for r in read.records if GoogleSheetsClient._has_any_canonical_value(r, schemas.VEHICLE_SHEET)]
    assert read.header == tuple(_P1_HEADER)
    assert filtered == legacy
    # Same Python types, cell by cell (not merely equal after coercion).
    assert [[type(v) for v in r.values()] for r in filtered] == [[type(v) for v in r.values()] for r in legacy]
    # Numericisation preserved exactly as legacy (F-c), never "repaired".
    numeric_row, comma_row = filtered[1], filtered[2]
    assert (numeric_row["vehicle_id"], numeric_row["machine_no"], numeric_row["created_at"]) == (123, 1234, 2026)
    assert numeric_row["updated_at"] == "not-a-date"
    assert (comma_row["machine_no"], comma_row["model_id"]) == (1234, "3_2")
    assert filtered[3]["operational_status"] == "" and filtered[3]["updated_at"] == ""
    assert len(read.records) == len(_P1_ROWS)  # returned unfiltered


# ---------------------------------------------------------------------------
# Counting and list parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c5_more_than_200_rows_all_statuses_with_phantoms_match_list_totals() -> None:
    rows = [_row(f"VEH-{i:04d}", STATUSES[i % 5]) for i in range(453)]
    rows[100:100] = [["", "", "", "", "", "", ""]] * 30 + [["", "", "", "", "", "", "", "junk"]]
    repo = _repo(_backend(rows, header=[*HEADER, "remark"]))
    summary = await _summary(repo)
    assert summary.vehicle_total == 453
    assert summary.status_counts == {s: len([i for i in range(453) if STATUSES[i % 5] == s]) for s in STATUSES}
    await _assert_parity(repo)


@pytest.mark.asyncio
async def test_s1_valid_header_and_no_rows_is_a_genuine_zero() -> None:
    repo = _repo(_backend([]))
    summary = await _summary(repo)
    assert summary.vehicle_total == 0
    assert summary.status_counts == dict.fromkeys(STATUSES, 0)
    await _assert_parity(repo)


@pytest.mark.asyncio
async def test_s2_only_phantom_rows_is_zero_and_matches_list() -> None:
    rows = [["", "", "", "", "", "", ""]] * 236 + [["", "", "", "", "", "", "", "note only"]]
    repo = _repo(_backend(rows, header=[*HEADER, "note"]))
    summary = await _summary(repo)
    assert summary.vehicle_total == 0
    await _assert_parity(repo)


@pytest.mark.asyncio
async def test_c11_data_only_in_named_non_canonical_columns_is_a_phantom_for_both() -> None:
    rows = [_row("VEH-1", "WORKING"), ["", "", "", "", "", "", "", "stray"]]
    repo = _repo(_backend(rows, header=[*HEADER, "note"]))
    assert (await _summary(repo)).vehicle_total == 1
    await _assert_parity(repo)


@pytest.mark.asyncio
async def test_s10_ragged_short_rows_are_padded_like_the_legacy_read() -> None:
    rows = [
        ["VEH-1", "M-1", "MDL-1", "", "READY"],          # timestamps missing -> epoch, as list
        ["VEH-2", "M-2", "MDL-1", "", "WORKING", TS],
    ]
    repo = _repo(_backend(rows))
    summary = await _summary(repo)
    assert summary.vehicle_total == 2
    await _assert_parity(repo)

    missing_status = _repo(_backend([["VEH-3", "M-3", "MDL-1", "SN"]]))
    err = await _api_error(missing_status)
    assert err.code == "VEHICLE_MASTER_DATA_INVALID"
    assert err.details == {"issue_counts": {"BLANK_STATUS": 1}, "sample_vehicle_ids": ["VEH-3"]}


# ---------------------------------------------------------------------------
# Schema failures (never 200 zeros)
# ---------------------------------------------------------------------------


def _assert_schema(err: ApiError, problem: str, headers: list[str] | None = None) -> None:
    assert err.code == "VEHICLE_MASTER_SCHEMA_INVALID"
    assert err.status_code == 500
    assert err.details is not None
    assert err.details["tab"] == VEHICLE_TAB
    assert err.details["problem"] == problem
    if headers is not None:
        assert err.details["headers"] == headers


@pytest.mark.asyncio
async def test_s3_missing_required_header_is_schema_invalid() -> None:
    header = [h for h in HEADER if h != "operational_status"]
    repo = _repo(_backend([["VEH-1", "M", "MDL-1", "", TS, TS]], header=header))
    _assert_schema(await _api_error(repo), "MISSING_HEADERS", ["operational_status"])


@pytest.mark.asyncio
async def test_s5_renamed_headers_with_populated_rows_is_schema_invalid_not_zero() -> None:
    renamed = [h.upper() for h in HEADER]  # no trimming/case-folding into validity
    repo = _repo(_backend([_row("VEH-1"), _row("VEH-2")], header=renamed))
    _assert_schema(await _api_error(repo), "MISSING_HEADERS", HEADER)
    # The legacy read of the same state would report an empty fleet.
    assert await repo._client.read_rows(schemas.VEHICLE_SHEET) == []


@pytest.mark.asyncio
async def test_s5b_header_names_are_not_trimmed_into_validity() -> None:
    header = [*HEADER]
    header[4] = " operational_status"
    repo = _repo(_backend([_row("VEH-1")], header=header))
    _assert_schema(await _api_error(repo), "MISSING_HEADERS", ["operational_status"])


def _rename_all(backend: FakeSheetsBackend) -> None:
    backend.tabs[VEHICLE_TAB][0] = [f"{h}_renamed" for h in HEADER]  # type: ignore[index]


def _rename_before_full_read(backend: FakeSheetsBackend) -> Callable[[str, str | None], None]:
    """Hook: rename every canonical header just before the next FULL-tab
    values read (a header-only `row_values(1)` read is left untouched)."""

    def hook(tab: str, cells: str | None) -> None:
        if tab == VEHICLE_TAB and cells is None:
            _rename_all(backend)

    return hook


@pytest.mark.asyncio
async def test_s4_adversarial_rename_between_header_check_and_values_read_warm_and_cold() -> None:
    rows = [_row("VEH-1", "WORKING"), _row("VEH-2", "READY")]

    # Legacy-style sequence (cold): the header observation is valid, the
    # header is renamed before the data read -> read_rows returns [] (the
    # false-zero race the withdrawn design would have turned into 200 zeros).
    legacy_backend = _backend(rows)
    legacy_repo = _repo(legacy_backend)
    legacy_backend.before_values_get = _rename_before_full_read(legacy_backend)
    ok, _ = await legacy_repo._client.validate_schema(schemas.VEHICLE_SHEET)
    assert ok is True
    assert await legacy_repo._client.read_rows(schemas.VEHICLE_SHEET) == []

    # Summary, warm: header cache warmed by a prior valid list read, then
    # the single values response the summary uses carries renamed headers.
    warm_backend = _backend(rows)
    warm_repo = _repo(warm_backend)
    assert await _list_total(warm_repo) == 2
    assert (await warm_repo._client.validate_schema(schemas.VEHICLE_SHEET))[0] is True
    warm_backend.before_values_get = _rename_before_full_read(warm_backend)
    _assert_schema(await _api_error(warm_repo), "MISSING_HEADERS", HEADER)
    # The warm validate_schema still trusts its stale cached header.
    assert (await warm_repo._client.validate_schema(schemas.VEHICLE_SHEET))[0] is True

    # Summary, cold.
    cold_backend = _backend(rows)
    cold_backend.before_values_get = _rename_before_full_read(cold_backend)
    _assert_schema(await _api_error(_repo(cold_backend)), "MISSING_HEADERS", HEADER)


@pytest.mark.asyncio
async def test_s6_warm_header_change_across_requests_and_header_cache_untouched() -> None:
    backend = _backend([_row("VEH-1", "WORKING")])
    repo = _repo(backend)
    await repo._client.read_rows(schemas.VEHICLE_SHEET)  # a legacy caller populates the cache
    cache_before = dict(repo._client._header_cache)
    assert (await _summary(repo)).vehicle_total == 1
    _rename_all(backend)
    _assert_schema(await _api_error(repo), "MISSING_HEADERS", HEADER)
    assert repo._client._header_cache == cache_before

    fresh = _repo(_backend([_row("VEH-1")]))
    await _summary(fresh)
    assert fresh._client._header_cache == {}  # the summary never populates it


@pytest.mark.asyncio
async def test_s7_completely_empty_tab_is_no_header_row_not_zero() -> None:
    backend = FakeSheetsBackend({VEHICLE_TAB: None})
    repo = _repo(backend)
    _assert_schema(await _api_error(repo), "NO_HEADER_ROW")
    # Legacy get_all_records returns [] for the same state.
    assert await repo._client.read_rows(schemas.VEHICLE_SHEET) == []


@pytest.mark.asyncio
async def test_s7b_blank_header_row_with_data_below_is_no_header_row() -> None:
    backend = FakeSheetsBackend({VEHICLE_TAB: [["", "", ""], _row("VEH-1")]})
    _assert_schema(await _api_error(_repo(backend)), "NO_HEADER_ROW")


@pytest.mark.asyncio
async def test_s8_duplicate_and_multiple_blank_headers_are_schema_invalid() -> None:
    dup = _repo(_backend([[*_row("VEH-1"), "VEH-1"]], header=[*HEADER, "vehicle_id"]))
    _assert_schema(await _api_error(dup), "DUPLICATE_HEADERS", ["vehicle_id"])

    blanks = _repo(_backend([_row("VEH-1")], header=[*HEADER, "", ""]))
    _assert_schema(await _api_error(blanks), "DUPLICATE_HEADERS", [""])


@pytest.mark.asyncio
async def test_single_unused_blank_header_is_accepted_like_gspread() -> None:
    header = [*HEADER[:3], "", *HEADER[3:]]
    rows = [[*r[:3], "", *r[3:]] for r in (_row("VEH-1", "WORKING"), _row("VEH-2", "READY"))]
    repo = _repo(_backend(rows, header=header))
    assert (await _summary(repo)).vehicle_total == 2
    await _assert_parity(repo)


@pytest.mark.asyncio
async def test_s9_data_under_a_blank_header_or_beyond_header_width_is_rejected() -> None:
    header = [*HEADER[:3], "", *HEADER[3:]]
    under_blank = [[*_row("VEH-1")[:3], "hidden", *_row("VEH-1")[3:]]]
    repo = _repo(_backend(under_blank, header=header))
    _assert_schema(await _api_error(repo), "DATA_OUTSIDE_HEADER")
    # Legacy list silently drops that cell and succeeds.
    assert await _list_total(repo) == 1

    beyond = _repo(_backend([[*_row("VEH-1"), "overflow"]]))
    _assert_schema(await _api_error(beyond), "DATA_OUTSIDE_HEADER")

    whitespace_header = _repo(_backend([[*_row("VEH-1"), "x"]], header=[*HEADER, "  "]))
    _assert_schema(await _api_error(whitespace_header), "DATA_OUTSIDE_HEADER")


@pytest.mark.asyncio
async def test_s9_blank_extra_cells_beyond_header_follow_gspread() -> None:
    one_blank = _repo(_backend([[*_row("VEH-1"), ""]]))
    assert (await _summary(one_blank)).vehicle_total == 1
    await _assert_parity(one_blank)

    # Two blank cells beyond the header: gspread pads the header with two
    # "" names and get_all_records raises, so the summary fails too.
    two_blank_backend = _backend([[*_row("VEH-1"), "", ""]])
    two_blank = _repo(two_blank_backend)
    _assert_schema(await _api_error(two_blank), "DUPLICATE_HEADERS", [""])
    with pytest.raises(RepositoryError):
        await two_blank.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams())


@pytest.mark.asyncio
async def test_overflow_cells_are_rejected_before_any_padding_or_zip(monkeypatch) -> None:
    calls: list[str] = []
    for name in ("fill_gaps", "numericise_all", "to_records"):
        original = getattr(gspread.utils, name)

        def spy(*args, _original=original, _name=name, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(gspread.utils, name, spy)

    wide = [[*_row("VEH-1"), "", "", "overflow"]]  # overflow three cells past the header
    repo = _repo(_backend(wide))
    with pytest.raises(RepositorySchemaError) as info:
        await repo._client.read_header_and_records(schemas.VEHICLE_SHEET)
    assert info.value.problem == "DATA_OUTSIDE_HEADER"
    assert calls == []  # rejected on raw rows: nothing was padded, numericised or zipped

    ok = _repo(_backend([_row("VEH-1")]))
    await ok._client.read_header_and_records(schemas.VEHICLE_SHEET)
    assert calls == ["fill_gaps", "numericise_all", "to_records"]


@pytest.mark.asyncio
async def test_single_overflow_cell_is_data_outside_header_and_raw_width_is_kept() -> None:
    repo = _repo(_backend([[*_row("VEH-1"), "overflow"]]))
    with pytest.raises(RepositorySchemaError) as info:
        await repo._client.read_header_and_records(schemas.VEHICLE_SHEET)
    assert info.value.problem == "DATA_OUTSIDE_HEADER"


@pytest.mark.asyncio
async def test_s11_cold_missing_tab_is_tab_missing() -> None:
    repo = _repo(FakeSheetsBackend({"model_master": [["model_id"]]}))
    _assert_schema(await _api_error(repo), "TAB_MISSING")


@pytest.mark.asyncio
async def test_s12_warm_cached_worksheet_then_tab_deleted_is_read_failed() -> None:
    backend = _backend([_row("VEH-1")])
    repo = _repo(backend)
    await _summary(repo)
    del backend.tabs[VEHICLE_TAB]
    err = await _api_error(repo)
    assert err.code == "VEHICLE_MASTER_READ_FAILED" and err.status_code == 503
    assert err.details is None


@pytest.mark.asyncio
async def test_s13_read_and_configuration_failures_are_read_failed() -> None:
    backend = _backend([_row("VEH-1")])
    backend.fail_values_get = True
    err = await _api_error(_repo(backend))
    assert (err.code, err.status_code) == ("VEHICLE_MASTER_READ_FAILED", 503)

    unconfigured = GoogleSheetsRepository(Settings(google_sheet_id="", google_application_credentials=""))
    err = await _api_error(unconfigured)
    assert (err.code, err.status_code) == ("VEHICLE_MASTER_READ_FAILED", 503)

    class BrokenSession(FakeSheetsBackend):
        def request(self, method, url, **kwargs):
            raise ConnectionError("network down")

    err = await _api_error(_repo(BrokenSession({})))
    assert (err.code, err.status_code) == ("VEHICLE_MASTER_READ_FAILED", 503)


# ---------------------------------------------------------------------------
# Record / identity failures (valid headers)
# ---------------------------------------------------------------------------


def _assert_data(err: ApiError, issue_counts: dict[str, int], sample: list[str] | None = None) -> None:
    assert err.code == "VEHICLE_MASTER_DATA_INVALID"
    assert err.status_code == 500
    assert err.details is not None
    assert err.details["issue_counts"] == issue_counts
    if sample is not None:
        assert err.details["sample_vehicle_ids"] == sample


@pytest.mark.asyncio
async def test_c6_blank_status_blocks_summary_while_legacy_list_shows_ready() -> None:
    repo = _repo(_backend([_row("VEH-1", "WORKING"), _row("VEH-2", "")]))
    _assert_data(await _api_error(repo), {"BLANK_STATUS": 1}, ["VEH-2"])
    items, total = await repo.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams())
    assert total == 2
    assert {v.vehicle_id: v.operational_status for v in items}["VEH-2"] == OperationalStatus.READY


@pytest.mark.asyncio
async def test_whitespace_only_status_is_blank_status() -> None:
    repo = _repo(_backend([_row("VEH-1", "   ")]))
    _assert_data(await _api_error(repo), {"BLANK_STATUS": 1})


@pytest.mark.asyncio
async def test_c7_unrecognized_statuses_block_summary_and_legacy_list_fails() -> None:
    rows = [_row("VEH-1", "Working"), _row("VEH-2", " READY"), _row("VEH-3", "UNKNOWN"), _row("VEH-4", "READY")]
    repo = _repo(_backend(rows))
    _assert_data(await _api_error(repo), {"UNRECOGNIZED_STATUS": 3}, ["VEH-1", "VEH-2", "VEH-3"])
    with pytest.raises(ValueError):
        await _list_total(repo)


@pytest.mark.asyncio
async def test_c8_numeric_looking_machine_no_or_id_is_unmappable_like_legacy() -> None:
    repo = _repo(_backend([_row("VEH-1", machine="1234"), _row("1046"), _row("VEH-3")]))
    _assert_data(await _api_error(repo), {"UNMAPPABLE_ROW": 2}, ["VEH-1"])
    with pytest.raises(ValueError):
        await _list_total(repo)


@pytest.mark.asyncio
async def test_c9_numericised_timestamp_is_unmappable_but_non_iso_text_falls_back() -> None:
    bad = _repo(_backend([_row("VEH-1", created="2026")]))
    _assert_data(await _api_error(bad), {"UNMAPPABLE_ROW": 1})
    with pytest.raises(TypeError):
        await _list_total(bad)

    fallback = _repo(_backend([_row("VEH-1", created="not-a-date", updated="")]))
    assert (await _summary(fallback)).vehicle_total == 1
    await _assert_parity(fallback)


@pytest.mark.asyncio
async def test_c10_blank_and_duplicate_vehicle_ids() -> None:
    rows = [_row("", "READY"), _row("  ", "WORKING"), _row("VEH-2001"), _row("VEH-2001", "WORKING"), _row("VEH-2002")]
    repo = _repo(_backend(rows))
    _assert_data(await _api_error(repo), {"BLANK_VEHICLE_ID": 2, "DUPLICATE_VEHICLE_ID": 2}, ["VEH-2001"])


@pytest.mark.asyncio
async def test_combined_issues_and_sample_ids_are_capped_distinct_and_sorted() -> None:
    rows = [_row(f"VEH-{i:03d}") for i in range(25)] * 2 + [_row("VEH-Z", "")]
    repo = _repo(_backend(rows))
    err = await _api_error(repo)
    _assert_data(err, {"BLANK_STATUS": 1, "DUPLICATE_VEHICLE_ID": 50})
    assert err.details["sample_vehicle_ids"] == sorted(f"VEH-{i:03d}" for i in range(20))
    assert "rows" not in json.dumps(err.details)


# ---------------------------------------------------------------------------
# Call accounting (no N+1, no other tabs) and zero writes
# ---------------------------------------------------------------------------


def _busy_backend() -> FakeSheetsBackend:
    return _backend(
        [_row(f"VEH-{i}", STATUSES[i % 5]) for i in range(60)],
        model_master=[["model_id"], ["MDL-1"]],
        vehicle_component=[["component_id", "vehicle_id", "component_role", "label"], ["C-1", "VEH-1", "CARRIER_ENGINE", "x"]],
        vehicle_status_history=[list(schemas.VEHICLE_STATUS_HISTORY_SHEET.required_headers)],
    )


@pytest.mark.asyncio
async def test_c12_call_counts_cold_and_warm() -> None:
    backend = _busy_backend()
    repo = _repo(backend)
    await _summary(repo)
    # Cold: open_by_key + worksheet() each fetch metadata; exactly ONE values read.
    assert backend.metadata_reads() == 2
    assert backend.values_reads() == 1
    assert backend.values_reads(VEHICLE_TAB) == 1
    assert all(tab in (None, VEHICLE_TAB) for _, _, tab in backend.requests)

    backend.requests.clear()
    await _summary(repo)
    assert backend.requests == [("get", "values", VEHICLE_TAB)]  # warm: one full-tab values read only
    assert backend.writes == []


_ZERO_WRITE_SCENARIOS: dict[str, Callable[[], FakeSheetsBackend]] = {
    "success": _busy_backend,
    "empty": lambda: _backend([]),
    "phantom_only": lambda: _backend([["", "", "", "", "", "", ""]] * 5),
    "missing_header": lambda: _backend([_row("VEH-1")[:6]], header=HEADER[:6]),
    "renamed_header": lambda: _backend([_row("VEH-1")], header=[h.upper() for h in HEADER]),
    "no_header_row": lambda: FakeSheetsBackend({VEHICLE_TAB: None}),
    "duplicate_header": lambda: _backend([[*_row("VEH-1"), "x"]], header=[*HEADER, "machine_no"]),
    "data_outside_header": lambda: _backend([[*_row("VEH-1"), "x"]]),
    "blank_status": lambda: _backend([_row("VEH-1", "")]),
    "unrecognized_status": lambda: _backend([_row("VEH-1", "ready")]),
    "unmappable": lambda: _backend([_row("VEH-1", machine="99")]),
    "duplicate_id": lambda: _backend([_row("VEH-1"), _row("VEH-1")]),
    "tab_missing": lambda: FakeSheetsBackend({"model_master": [["model_id"]]}),
    "read_error": lambda: (lambda b: (setattr(b, "fail_values_get", True), b)[1])(_backend([_row("VEH-1")])),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(_ZERO_WRITE_SCENARIOS))
async def test_z1_summary_never_writes_in_any_path(scenario: str) -> None:
    backend = _ZERO_WRITE_SCENARIOS[scenario]()
    before = backend.snapshot()
    repo = _repo(backend)
    try:
        await _summary(repo)
    except ApiError:
        pass
    assert backend.writes == []
    assert backend.snapshot() == before
    assert all(method == "get" for method, _, _ in backend.requests)


# ---------------------------------------------------------------------------
# API level (Sheets repository behind the real app)
# ---------------------------------------------------------------------------


async def _api_get(repo: GoogleSheetsRepository, headers: dict[str, str] | None = None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.get("/api/v1/dashboard/fleet-status", headers=headers or {})
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a2_sheets_denied_request_performs_zero_sheet_requests() -> None:
    backend = _busy_backend()
    response = await _api_get(_repo(backend), {"X-Dev-Role": "UNKNOWN"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HTTP_ERROR"
    assert backend.requests == [] and backend.writes == []


@pytest.mark.asyncio
async def test_api_envelopes_for_sheets_failures_carry_no_counts() -> None:
    cases = {
        "VEHICLE_MASTER_SCHEMA_INVALID": (_backend([_row("VEH-1")], header=[h.upper() for h in HEADER]), 500),
        "VEHICLE_MASTER_DATA_INVALID": (_backend([_row("VEH-1", "")]), 500),
        "VEHICLE_MASTER_READ_FAILED": (FakeSheetsBackend({}), 503),
    }
    cases["VEHICLE_MASTER_READ_FAILED"][0].fail_values_get = True
    cases["VEHICLE_MASTER_READ_FAILED"][0].tabs[VEHICLE_TAB] = [HEADER]
    for code, (backend, status_code) in cases.items():
        response = await _api_get(_repo(backend))
        assert response.status_code == status_code, code
        body = response.json()
        assert set(body) == {"error"}
        assert body["error"]["code"] == code
        assert body["error"]["request_id"]
        text = response.text
        assert "vehicle_total" not in text and "status_counts" not in text
        assert "Traceback" not in text and "fake.json" not in text


@pytest.mark.asyncio
async def test_api_success_over_sheets_matches_list_route() -> None:
    backend = _busy_backend()
    repo = _repo(backend)
    response = await _api_get(repo)
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_total"] == 60 == await _list_total(repo)
    assert body["status_counts"] == {s: 12 for s in STATUSES}
