"""Phase 7 Batch 7C2 — open-repair report over Google Sheets, exercised
with the REAL installed gspread client on top of the FAKE HTTP session
from the 7B2 tests (`FakeSheetsBackend`): only the network transport is
faked; every value transformation (get_all_records, row_values,
fill_gaps, numericise_all, to_records) is gspread's own code.

Approved DEC-2 option S: the report validates repair_order's STRUCTURE on
the same values response its rows come from (every required header by
exact name, no duplicate headers, no data under unnamed columns), while
record-value defaults stay exactly as the legacy list applies them. This
is NOT the 7B2 parity-or-fail identity/status policy.

No credentials, no network, no live spreadsheet; request counts below are
fake-transport counts, not live Sheets performance. All fixtures are
synthetic (SYN-* ids), not company fleet data.
"""
from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.domain.meter_service import MeterService
from app.domain.repair import RepairStatus
from app.domain.repair_service import RepairService
from app.errors import ApiError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from tests.test_fleet_status_summary_sheets_batch7b2 import FakeSheetsBackend, _repo

REPAIR_TAB = schemas.REPAIR_SHEET.tab_name
ACTION_TAB = schemas.REPAIR_ACTION_SHEET.tab_name
ASSIGN_TAB = schemas.REPAIR_ASSIGNMENT_SHEET.tab_name
HEADER = list(schemas.REPAIR_SHEET.required_headers)
ACTION_HEADER = list(schemas.REPAIR_ACTION_SHEET.required_headers)
ASSIGN_HEADER = list(schemas.REPAIR_ASSIGNMENT_SHEET.required_headers)
TS = "2026-01-15T08:00:00+00:00"
URL = "/api/v1/repairs/open-queue"


def _row(
    rid: str,
    status: str = "OPEN",
    asset_type: str = "VEHICLE",
    asset_id: str = "SYN-VEH-1",
    opened_at: str = TS,
    primary: str = "",
    symptom: str = "synthetic",
) -> list[str]:
    values = dict.fromkeys(HEADER, "")
    values.update(
        repair_id=rid,
        asset_type=asset_type,
        asset_id=asset_id,
        source_type="MANUAL",
        status=status,
        opened_at=opened_at,
        primary_technician=primary,
        symptom=symptom,
    )
    return [values[h] for h in HEADER]


def _action(aid: str, rid: str) -> list[str]:
    return [aid, rid, "synthetic action", "", TS, ""]


def _backend(
    rows: list[list[str]],
    header: list[str] | None = None,
    actions: list[list[str]] | None = None,
    **extra_tabs,
) -> FakeSheetsBackend:
    tabs: dict[str, list[list[str]] | None] = {
        REPAIR_TAB: [list(header or HEADER), *rows],
        ACTION_TAB: [ACTION_HEADER, *(actions or [])],
        ASSIGN_TAB: [ASSIGN_HEADER],
        # Unrelated tabs the report must never read.
        "repair_part": [list(schemas.REPAIR_PART_SHEET.required_headers)],
        "vehicle_master": [list(schemas.VEHICLE_SHEET.required_headers)],
        "equipment_master": [["equipment_id"]],
    }
    tabs.update(extra_tabs)
    return FakeSheetsBackend(tabs)


def _service(repo) -> RepairService:
    return RepairService(repo, MeterService(repo))


async def _report(repo, asset_type=None, page=1, page_size=200):
    return await _service(repo).list_open_repairs_for_report(asset_type, PageParams(page=page, page_size=page_size))


async def _legacy(repo, asset_type=None, page=1, page_size=200):
    return await repo.list_repairs(asset_type, None, RepairStatus.OPEN, PageParams(page=page, page_size=page_size))


async def _report_error(repo, asset_type=None) -> ApiError:
    with pytest.raises(ApiError) as info:
        await _report(repo, asset_type)
    return info.value


def _assert_schema(err: ApiError, problem: str, headers: list[str] | None = None) -> None:
    assert (err.code, err.status_code) == ("REPAIR_ORDER_SCHEMA_INVALID", 500)
    assert err.details is not None
    assert err.details["tab"] == REPAIR_TAB
    assert err.details["problem"] == problem
    if headers is not None:
        assert err.details["headers"] == headers


def _assert_read_failed(err: ApiError) -> None:
    assert (err.code, err.status_code) == ("REPAIR_ORDER_READ_FAILED", 503)
    assert err.details is None


# ---------------------------------------------------------------------------
# Legacy false results that the report now rejects (the reason for DEC-2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_canonical_headers_renamed_legacy_false_empty_report_rejects() -> None:
    renamed = [f"{h}_renamed" for h in HEADER]
    repo = _repo(_backend([_row("SYN-RPR-1"), _row("SYN-RPR-2")], header=renamed))
    items, total = await _legacy(repo)
    assert (items, total) == ([], 0)  # legacy: populated sheet reported as a false empty
    _assert_schema(await _report_error(repo), "MISSING_HEADERS", HEADER)


@pytest.mark.asyncio
async def test_status_header_renamed_legacy_turns_closed_into_open_report_rejects() -> None:
    header = ["Status" if h == "status" else h for h in HEADER]
    rows = [_row("SYN-RPR-1", status="CLOSED"), _row("SYN-RPR-2", status="OPEN")]
    repo = _repo(_backend(rows, header=header))
    items, total = await _legacy(repo)
    assert total == 2  # legacy: the CLOSED work order defaults to OPEN
    assert {i.repair_id: i.status for i in items}["SYN-RPR-1"] == RepairStatus.OPEN
    err = await _report_error(repo)
    _assert_schema(err, "MISSING_HEADERS", ["status"])
    assert "total" not in (err.details or {})


# ---------------------------------------------------------------------------
# Genuine empties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_only_sheet_is_a_genuine_empty() -> None:
    repo = _repo(_backend([]))
    result = await _report(repo)
    assert (result.items, result.total_items) == ([], 0)
    assert await _legacy(repo) == ([], 0)


@pytest.mark.asyncio
async def test_phantom_only_rows_are_a_genuine_empty() -> None:
    rows = [[""] * len(HEADER)] * 40 + [[*([""] * len(HEADER)), "note only"]]
    repo = _repo(_backend(rows, header=[*HEADER, "note"]))
    result = await _report(repo)
    assert result.total_items == 0
    assert await _legacy(repo) == ([], 0)


# ---------------------------------------------------------------------------
# Structural failures (never a 200)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_required_headers() -> None:
    header = [h for h in HEADER if h not in ("asset_type", "opened_at")]
    rows = [[v for h, v in zip(HEADER, _row("SYN-RPR-1")) if h in header]]
    _assert_schema(await _report_error(_repo(_backend(rows, header=header))), "MISSING_HEADERS", ["asset_type", "opened_at"])


@pytest.mark.asyncio
async def test_header_names_are_exact_not_trimmed_or_case_folded() -> None:
    header = [" repair_id" if h == "repair_id" else h for h in HEADER]
    _assert_schema(await _report_error(_repo(_backend([_row("SYN-RPR-1")], header=header))), "MISSING_HEADERS", ["repair_id"])


@pytest.mark.asyncio
async def test_duplicate_headers() -> None:
    repo = _repo(_backend([[*_row("SYN-RPR-1"), "OPEN"]], header=[*HEADER, "status"]))
    _assert_schema(await _report_error(repo), "DUPLICATE_HEADERS", ["status"])


@pytest.mark.asyncio
async def test_absent_or_blank_header_row() -> None:
    _assert_schema(await _report_error(_repo(FakeSheetsBackend({REPAIR_TAB: None, ACTION_TAB: [ACTION_HEADER]}))), "NO_HEADER_ROW")
    blank = FakeSheetsBackend({REPAIR_TAB: [[""] * 5, _row("SYN-RPR-1")], ACTION_TAB: [ACTION_HEADER]})
    _assert_schema(await _report_error(_repo(blank)), "NO_HEADER_ROW")


@pytest.mark.asyncio
async def test_data_under_unnamed_column_blocks_report_while_legacy_drops_it() -> None:
    header = [*HEADER[:3], "", *HEADER[3:]]
    rows = [[*_row("SYN-RPR-1")[:3], "hidden", *_row("SYN-RPR-1")[3:]]]
    repo = _repo(_backend(rows, header=header))
    _assert_schema(await _report_error(repo), "DATA_OUTSIDE_HEADER")
    assert (await _legacy(repo))[1] == 1

    beyond = _repo(_backend([[*_row("SYN-RPR-1"), "overflow"]]))
    _assert_schema(await _report_error(beyond), "DATA_OUTSIDE_HEADER")


@pytest.mark.asyncio
async def test_inherited_blank_header_behavior() -> None:
    # One unused blank header cell is tolerated, exactly like gspread.
    header = [*HEADER[:3], "", *HEADER[3:]]
    rows = [[*r[:3], "", *r[3:]] for r in (_row("SYN-RPR-1"), _row("SYN-RPR-2"))]
    ok = _repo(_backend(rows, header=header))
    assert (await _report(ok)).total_items == 2 == (await _legacy(ok))[1]
    # Two blank header names collide (gspread's get_all_records raises too).
    two = _repo(_backend([_row("SYN-RPR-1")], header=[*HEADER, "", ""]))
    _assert_schema(await _report_error(two), "DUPLICATE_HEADERS", [""])


@pytest.mark.asyncio
async def test_cold_missing_tab_is_tab_missing() -> None:
    repo = _repo(FakeSheetsBackend({ACTION_TAB: [ACTION_HEADER]}))
    _assert_schema(await _report_error(repo), "TAB_MISSING")


@pytest.mark.asyncio
async def test_warm_worksheet_failure_is_read_failed_not_tab_missing() -> None:
    backend = _backend([_row("SYN-RPR-1")])
    repo = _repo(backend)
    assert (await _report(repo)).total_items == 1
    del backend.tabs[REPAIR_TAB]
    _assert_read_failed(await _report_error(repo))


@pytest.mark.asyncio
async def test_unconfigured_client_and_values_failure_are_read_failed() -> None:
    unconfigured = GoogleSheetsRepository(Settings(google_sheet_id="", google_application_credentials=""))
    _assert_read_failed(await _report_error(unconfigured))
    backend = _backend([_row("SYN-RPR-1")])
    backend.fail_values_get = True
    _assert_read_failed(await _report_error(_repo(backend)))


@pytest.mark.asyncio
async def test_repair_action_read_failure_is_read_failed() -> None:
    backend = _backend([_row("SYN-RPR-1")])
    del backend.tabs[ACTION_TAB]
    _assert_read_failed(await _report_error(_repo(backend)))

    failing = _backend([_row("SYN-RPR-1")])

    def fail_actions(tab: str, cells: str | None) -> None:
        if tab == ACTION_TAB:
            failing.fail_values_get = True

    failing.before_values_get = fail_actions
    _assert_read_failed(await _report_error(_repo(failing)))


# ---------------------------------------------------------------------------
# Valid-sheet parity and unchanged record-value behavior
# ---------------------------------------------------------------------------


def _mixed_rows() -> list[list[str]]:
    return [
        _row("SYN-RPR-1", asset_id="SYN-VEH-1", opened_at="2026-01-15T08:00:00+00:00"),
        _row("SYN-RPR-2", status="", asset_id="SYN-VEH-2", opened_at="2026-01-15T09:00:00+00:00"),   # blank -> OPEN
        _row("SYN-RPR-3", asset_type="", asset_id="SYN-VEH-3", opened_at="2026-01-15T07:00:00+00:00"),  # blank -> VEHICLE
        _row("SYN-RPR-4", asset_type="EQUIPMENT", asset_id="SYN-EQP-1", opened_at="2026-01-15T08:00:00+00:00"),
        _row("SYN-RPR-5", status="CLOSED", opened_at="2026-01-16T08:00:00+00:00"),
        [""] * len(HEADER),  # phantom
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", [None, AssetType.VEHICLE, AssetType.EQUIPMENT])
async def test_valid_sheet_report_equals_legacy_list(asset_type) -> None:
    actions = [_action("SYN-ACT-1", "SYN-RPR-1"), _action("SYN-ACT-2", "SYN-RPR-1"), _action("SYN-ACT-3", "SYN-RPR-4")]
    repo = _repo(_backend(_mixed_rows(), actions=actions))
    report = await _report(repo, asset_type)
    items, total = await _legacy(repo, asset_type)
    assert report.items == items and report.total_items == total
    expected = {None: 4, AssetType.VEHICLE: 3, AssetType.EQUIPMENT: 1}[asset_type]
    assert total == expected


@pytest.mark.asyncio
async def test_defaults_and_ordering_on_valid_sheet() -> None:
    actions = [_action("SYN-ACT-1", "SYN-RPR-1"), _action("SYN-ACT-2", "SYN-RPR-1"), _action("SYN-ACT-3", "SYN-RPR-4")]
    report = await _report(_repo(_backend(_mixed_rows(), actions=actions)))
    by_id = {i.repair_id: i for i in report.items}
    assert by_id["SYN-RPR-2"].status == RepairStatus.OPEN
    assert by_id["SYN-RPR-3"].asset_type == AssetType.VEHICLE
    assert "SYN-RPR-5" not in by_id
    assert [i.repair_id for i in report.items] == ["SYN-RPR-2", "SYN-RPR-4", "SYN-RPR-1", "SYN-RPR-3"]
    assert (by_id["SYN-RPR-1"].action_count, by_id["SYN-RPR-4"].action_count, by_id["SYN-RPR-2"].action_count) == (2, 1, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("field, value", [("status", "Open"), ("status", "IN_PROGRESS"), ("asset_type", "TRUCK")])
async def test_invalid_enum_values_keep_the_existing_generic_failure(field: str, value: str) -> None:
    kwargs = {field: value}
    repo = _repo(_backend([_row("SYN-RPR-1"), _row("SYN-RPR-2", **kwargs)]))
    with pytest.raises(ValueError):
        await _legacy(repo)
    with pytest.raises(ValueError):
        await _report(repo)
    response = await _api(repo)
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_blank_and_whitespace_ids_remain_counted() -> None:
    rows = [_row(""), _row("   "), _row("SYN-RPR-1")]
    repo = _repo(_backend(rows))
    report = await _report(repo)
    assert report.total_items == 3 == (await _legacy(repo))[1]
    assert sorted(i.repair_id for i in report.items) == ["", "   ", "SYN-RPR-1"]


@pytest.mark.asyncio
async def test_duplicate_ids_remain_distinct_rows() -> None:
    rows = [_row("SYN-RPR-1", asset_id="SYN-VEH-1"), _row("SYN-RPR-1", asset_id="SYN-VEH-2"), _row("SYN-RPR-2")]
    repo = _repo(_backend(rows, actions=[_action("SYN-ACT-1", "SYN-RPR-1")]))
    report = await _report(repo)
    assert report.total_items == 3
    dupes = [i for i in report.items if i.repair_id == "SYN-RPR-1"]
    assert sorted(i.asset_id for i in dupes) == ["SYN-VEH-1", "SYN-VEH-2"]
    assert all(i.action_count == 1 for i in dupes)  # counted by id, as legacy
    assert report.items == (await _legacy(repo))[0]


@pytest.mark.asyncio
async def test_timestamp_fallback_and_existing_limitations() -> None:
    # Blank / unparseable text -> epoch fallback (unchanged); both paths agree.
    fallback = _repo(_backend([_row("SYN-RPR-1", opened_at=""), _row("SYN-RPR-2", opened_at="not-a-date"), _row("SYN-RPR-3")]))
    report = await _report(fallback)
    assert [i.repair_id for i in report.items] == ["SYN-RPR-3", "SYN-RPR-2", "SYN-RPR-1"]
    assert {i.opened_at.isoformat() for i in report.items[1:]} == {"1970-01-01T00:00:00+00:00"}
    assert report.items == (await _legacy(fallback))[0]

    # A naive timestamp alone is returned as stored (no offset added).
    naive = _repo(_backend([_row("SYN-RPR-1", opened_at="2026-01-15T08:00:00")]))
    assert (await _report(naive)).items[0].opened_at.tzinfo is None

    # Mixed naive + aware: the existing sort failure is kept (TypeError).
    mixed = _repo(_backend([_row("SYN-RPR-1", opened_at="2026-01-15T08:00:00"), _row("SYN-RPR-2")]))
    with pytest.raises(TypeError):
        await _report(mixed)
    with pytest.raises(TypeError):
        await _legacy(mixed)

    # A numeric-looking opened_at is numericised by gspread and fails mapping (existing).
    numeric = _repo(_backend([_row("SYN-RPR-1", opened_at="2026")]))
    with pytest.raises(TypeError):
        await _report(numeric)
    with pytest.raises(TypeError):
        await _legacy(numeric)


@pytest.mark.asyncio
async def test_more_than_200_records_paginate_disjointly() -> None:
    rows = [_row(f"SYN-RPR-{i:04d}", opened_at=f"2026-01-15T08:{i // 10:02d}:00+00:00") for i in range(250)]
    rows += [_row(f"SYN-RPR-C{i}", status="CLOSED") for i in range(5)]
    repo = _repo(_backend(rows))
    first = await _report(repo, page=1, page_size=200)
    second = await _report(repo, page=2, page_size=200)
    beyond = await _report(repo, page=3, page_size=200)
    assert (len(first.items), len(second.items), len(beyond.items)) == (200, 50, 0)
    assert first.total_items == second.total_items == beyond.total_items == 250
    ids = [i.repair_id for i in first.items + second.items]
    assert len(set(ids)) == 250
    keys = [(i.opened_at, i.repair_id) for i in first.items + second.items]
    assert keys == sorted(keys, reverse=True)


@pytest.mark.asyncio
async def test_legacy_assignment_history_filtering_is_preserved_over_sheets() -> None:
    rows = [_row("SYN-RPR-1", primary="syn-tech-1"), _row("SYN-RPR-2", primary="syn-tech-1"), _row("SYN-RPR-3")]
    history = [ASSIGN_HEADER, ["SYN-ASG-1", "SYN-RPR-1", "syn-tech-1", "PRIMARY", TS, "", "", "TRUE", ""]]
    repo = _repo(_backend(rows, **{ASSIGN_TAB: history}))
    mine, mine_total = await repo.list_repairs(None, None, RepairStatus.OPEN, PageParams(), assigned_to="syn-tech-1")
    waiting, waiting_total = await repo.list_repairs(None, None, RepairStatus.OPEN, PageParams(), unassigned_only=True)
    assert [i.repair_id for i in mine] == ["SYN-RPR-1"] and mine_total == 1
    assert [i.repair_id for i in waiting] == ["SYN-RPR-3", "SYN-RPR-2"] and waiting_total == 2


# ---------------------------------------------------------------------------
# Request accounting, zero writes, API envelopes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_measured_request_counts_cold_and_warm_and_no_unrelated_tabs() -> None:
    """Counts captured from this fake transport (not live latency): cold =
    3 metadata (open_by_key, worksheet(repair_order), worksheet(repair_action))
    + 1 repair_order values read + 2 repair_action values reads (the
    legacy `read_rows` header `row_values(1)` + `get_all_records`); warm =
    1 repair_order + 1 repair_action values read."""
    backend = _backend([_row(f"SYN-RPR-{i}") for i in range(60)], actions=[_action("SYN-ACT-1", "SYN-RPR-1")])
    repo = _repo(backend)
    await _report(repo)
    assert backend.metadata_reads() == 3
    assert backend.values_reads(REPAIR_TAB) == 1
    assert backend.values_reads(ACTION_TAB) == 2
    assert {tab for _, kind, tab in backend.requests if kind == "values"} == {REPAIR_TAB, ACTION_TAB}
    backend.requests.clear()
    await _report(repo)
    assert backend.requests == [("get", "values", REPAIR_TAB), ("get", "values", ACTION_TAB)]
    assert backend.writes == []
    assert repo._client._header_cache.keys() == {ACTION_TAB}  # repair_order cache untouched


_ZERO_WRITE_SCENARIOS: dict[str, Callable[[], FakeSheetsBackend]] = {
    "success": lambda: _backend(_mixed_rows(), actions=[_action("SYN-ACT-1", "SYN-RPR-1")]),
    "empty": lambda: _backend([]),
    "phantom_only": lambda: _backend([[""] * len(HEADER)] * 5),
    "renamed_all": lambda: _backend([_row("SYN-RPR-1")], header=[h.upper() for h in HEADER]),
    "renamed_status": lambda: _backend([_row("SYN-RPR-1")], header=["Status" if h == "status" else h for h in HEADER]),
    "duplicate_header": lambda: _backend([[*_row("SYN-RPR-1"), "x"]], header=[*HEADER, "symptom"]),
    "data_outside_header": lambda: _backend([[*_row("SYN-RPR-1"), "x"]]),
    "no_header_row": lambda: FakeSheetsBackend({REPAIR_TAB: None, ACTION_TAB: [ACTION_HEADER]}),
    "tab_missing": lambda: FakeSheetsBackend({ACTION_TAB: [ACTION_HEADER]}),
    "read_error": lambda: (lambda b: (setattr(b, "fail_values_get", True), b)[1])(_backend([_row("SYN-RPR-1")])),
    "action_tab_missing": lambda: FakeSheetsBackend({REPAIR_TAB: [HEADER, _row("SYN-RPR-1")]}),
    "invalid_enum": lambda: _backend([_row("SYN-RPR-1", status="Open")]),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(_ZERO_WRITE_SCENARIOS))
@pytest.mark.parametrize("asset_type", [None, AssetType.EQUIPMENT])
async def test_report_never_writes_in_any_path(scenario: str, asset_type) -> None:
    backend = _ZERO_WRITE_SCENARIOS[scenario]()
    before = backend.snapshot()
    try:
        await _report(_repo(backend), asset_type)
    except (ApiError, ValueError):
        pass
    assert backend.writes == []
    assert backend.snapshot() == before
    assert all(method == "get" for method, _, _ in backend.requests)
    assert {tab for _, kind, tab in backend.requests if kind == "values"} <= {REPAIR_TAB, ACTION_TAB}


async def _api(repo, path: str = URL, headers: dict[str, str] | None = None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers=headers or {})
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["DRIVER", "TECHNICIAN", "UNKNOWN"])
async def test_denied_request_performs_zero_transport_requests(role: str) -> None:
    backend = _backend(_mixed_rows())
    response = await _api(_repo(backend), headers={"X-Dev-Role": role})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HTTP_ERROR"
    assert backend.requests == [] and backend.writes == []


@pytest.mark.asyncio
async def test_api_envelopes_over_sheets_carry_no_rows_or_totals() -> None:
    read_failed = _backend([_row("SYN-RPR-1")])
    read_failed.fail_values_get = True
    cases = [
        (_backend([_row("SYN-RPR-1")], header=[h.upper() for h in HEADER]), 500, "REPAIR_ORDER_SCHEMA_INVALID"),
        (read_failed, 503, "REPAIR_ORDER_READ_FAILED"),
        (FakeSheetsBackend({REPAIR_TAB: [HEADER, _row("SYN-RPR-1")]}), 503, "REPAIR_ORDER_READ_FAILED"),
    ]
    for backend, status_code, code in cases:
        response = await _api(_repo(backend))
        assert response.status_code == status_code, code
        body = response.json()
        assert list(body) == ["error"] and body["error"]["code"] == code and body["error"]["request_id"]
        assert "total_items" not in response.text and "SYN-RPR-1" not in response.text
        assert "Traceback" not in response.text and "fake.json" not in response.text
        if code == "REPAIR_ORDER_SCHEMA_INVALID":
            assert body["error"]["details"]["tab"] == REPAIR_TAB
            assert body["error"]["details"]["problem"] == "MISSING_HEADERS"


@pytest.mark.asyncio
async def test_api_success_over_sheets_matches_legacy_route() -> None:
    repo = _repo(_backend(_mixed_rows(), actions=[_action("SYN-ACT-1", "SYN-RPR-1")]))
    for suffix in ("", "&asset_type=VEHICLE", "&asset_type=EQUIPMENT"):
        report = await _api(repo, f"{URL}?page_size=200{suffix}")
        legacy = await _api(repo, f"/api/v1/repairs?status=OPEN&page_size=200{suffix}")
        assert report.status_code == legacy.status_code == 200
        assert report.json() == legacy.json()
