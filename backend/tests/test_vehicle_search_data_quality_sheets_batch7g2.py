"""Phase 7 Batch 7G2 — vehicle search validation (A0) over Google Sheets,
exercised with the REAL installed gspread on the existing 7B2 fake HTTP
transport (imported, not modified): only the network is faked; every
value transformation is gspread's own. Any non-GET request is recorded as
a write and refused.

GET /vehicles shares the fleet status summary's single validated read and
whole-population gates (DEC-1, DEC-2(a)); list DATA_INVALID details carry
issue_counts only (DEC-7(b)). Numeric-looking identifiers still fail
(DEC-3 deferred): this batch does not complete N2.
No credentials, no network, no live spreadsheet; synthetic ids only.
"""
from __future__ import annotations

import itertools
import json
import random
from collections.abc import Callable

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.common import OperationalStatus, PageParams
from app.domain.vehicle_service import VehicleService
from app.errors import ApiError
from app.repositories.base import RepositoryError, RepositorySchemaError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from tests.test_fleet_status_summary_sheets_batch7b2 import (
    HEADER,
    STATUSES,
    TS,
    VEHICLE_TAB,
    FakeSheetsBackend,
    _backend,
    _busy_backend,
    _repo,
    _row,
)


# Phase 7 Batch 7J2: a q with usable terms also reads model_master, so the
# success paths that search by q carry a valid model_master tab.
_MODEL_TAB = [
    list(schemas.VEHICLE_MODEL_SHEET.required_headers),
    *[[f"MDL-{i}", f"MC-{i}", f"Model {i}", "", "", "CARRIER_ENGINE", "", "", ""] for i in range(5)],
]


def _with_models(backend: FakeSheetsBackend) -> FakeSheetsBackend:
    backend.tabs["model_master"] = [list(r) for r in _MODEL_TAB]
    return backend


async def _list(repo: GoogleSheetsRepository, q=None, status=None, model_id=None, page=1, page_size=20):
    return await VehicleService(repo).list_vehicles(
        q=q, operational_status=status, model_id=model_id, params=PageParams(page=page, page_size=page_size)
    )


async def _list_failure(repo: GoogleSheetsRepository, **kwargs) -> Exception:
    """The service raises ApiError (data) or a repository error (read or
    structure, mapped by the route); either way no page is returned."""
    with pytest.raises((ApiError, RepositoryError)) as info:
        await _list(repo, **kwargs)
    return info.value


async def _dashboard_failure(repo: GoogleSheetsRepository) -> ApiError:
    with pytest.raises(ApiError) as info:
        await VehicleService(repo).get_fleet_status_summary()
    return info.value


async def _http(repo: GoogleSheetsRepository, path: str, params=None, headers=None):
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
            return await client.get(path, params=params, headers=headers or {})
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


async def _list_http_error(repo: GoogleSheetsRepository, params=None) -> dict:
    response = await _http(repo, "/api/v1/vehicles", params=params)
    assert response.status_code in (500, 503), response.text
    body = response.json()
    assert set(body) == {"error"}
    for key in ("items", "total_items", "vehicle_total", "status_counts", "Traceback", "fake.json"):
        assert key not in response.text
    return {"status": response.status_code, **body["error"]}


def _assert_data(err: ApiError, issue_counts: dict[str, int]) -> None:
    assert (err.code, err.status_code) == ("VEHICLE_MASTER_DATA_INVALID", 500)
    assert err.details == {"issue_counts": issue_counts}


# ---------------------------------------------------------------------------
# G04 — clean 120-row dataset: same results as the legacy Sheets list
# ---------------------------------------------------------------------------


def _clean_rows() -> list[list[str]]:
    rows = [
        _row(f"VEH-{i:03d}", STATUSES[i % 5], machine=f"TC-{(i * 13) % 40:02d}/X", model=f"MDL-{i % 4}")
        for i in range(120)
    ]
    random.Random(7).shuffle(rows)  # storage order is not the sort order
    rows[30:30] = [["", "", "", "", "", "", ""]] * 4  # phantom rows
    return rows


@pytest.mark.asyncio
async def test_g04_clean_dataset_equals_legacy_list_for_filters_and_paging() -> None:
    backend = _with_models(_backend(_clean_rows()))
    repo = _repo(backend)
    combos = itertools.product(
        [None, "veh-01", "  TC-1  ", "/x", "nothing"],
        [None, *OperationalStatus],
        [None, "MDL-2", "MDL-X"],
        [(1, 20), (3, 20), (6, 20), (7, 20), (1, 200), (2, 7)],
    )
    for q, status, model_id, (page, size) in combos:
        params = PageParams(page=page, page_size=size)
        legacy_items, legacy_total = await repo.list_vehicles(q=q, operational_status=status, model_id=model_id, params=params)
        result = await _list(repo, q=q, status=status, model_id=model_id, page=page, page_size=size)
        assert [v.model_dump() for v in result.items] == [v.model_dump() for v in legacy_items]
        assert result.total_items == legacy_total
    assert backend.writes == []


@pytest.mark.asyncio
async def test_g04_totals_sorting_page_bounds_and_page_beyond_end() -> None:
    repo = _repo(_backend(_clean_rows()))
    first = await _list(repo, page=1, page_size=50)
    third = await _list(repo, page=3, page_size=50)
    beyond = await _list(repo, page=4, page_size=50)
    assert first.total_items == third.total_items == beyond.total_items == 120
    assert [v.vehicle_id for v in first.items] == [f"VEH-{i:03d}" for i in range(50)]
    assert [v.vehicle_id for v in third.items] == [f"VEH-{i:03d}" for i in range(100, 120)]
    assert beyond.items == []
    ready = await _list(repo, status=OperationalStatus.READY, page=9, page_size=5)
    assert ready.items == [] and ready.total_items == 24


@pytest.mark.asyncio
async def test_header_only_tab_is_a_genuine_zero_for_list_and_dashboard() -> None:
    repo = _repo(_backend([]))
    result = await _list(repo)
    assert (result.items, result.total_items) == ([], 0)
    assert (await VehicleService(repo).get_fleet_status_summary()).vehicle_total == 0


# ---------------------------------------------------------------------------
# G05 — structural damage: SCHEMA_INVALID, never a false empty / all-READY
# ---------------------------------------------------------------------------

_STRUCTURAL: dict[str, tuple[Callable[[], FakeSheetsBackend], str, list[str] | None]] = {
    "missing_status_header": (
        lambda: _backend([_row("VEH-1")[:4] + _row("VEH-1")[5:]], header=[h for h in HEADER if h != "operational_status"]),
        "MISSING_HEADERS", ["operational_status"],
    ),
    "renamed_status_header": (
        lambda: _backend([_row("VEH-1", "WORKING")], header=[("status" if h == "operational_status" else h) for h in HEADER]),
        "MISSING_HEADERS", ["operational_status"],
    ),
    "renamed_all_headers": (lambda: _backend([_row("VEH-1")], header=[h.upper() for h in HEADER]), "MISSING_HEADERS", None),
    "padded_header": (lambda: _backend([_row("VEH-1")], header=[" vehicle_id", *HEADER[1:]]), "MISSING_HEADERS", ["vehicle_id"]),
    "empty_tab": (lambda: FakeSheetsBackend({VEHICLE_TAB: None}), "NO_HEADER_ROW", None),
    "blank_header_row": (lambda: _backend([_row("VEH-1")], header=[""] * len(HEADER)), "NO_HEADER_ROW", None),
    "duplicate_header": (lambda: _backend([[*_row("VEH-1"), "x"]], header=[*HEADER, "machine_no"]), "DUPLICATE_HEADERS", ["machine_no"]),
    "two_blank_headers": (lambda: _backend([[*_row("VEH-1"), "", ""]], header=[*HEADER, "", ""]), "DUPLICATE_HEADERS", [""]),
    "data_outside_header": (lambda: _backend([[*_row("VEH-1"), "stray"]]), "DATA_OUTSIDE_HEADER", None),
    "tab_missing": (lambda: FakeSheetsBackend({"model_master": [["model_id"]]}), "TAB_MISSING", None),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(_STRUCTURAL))
async def test_g05_structural_damage_fails_every_list_request(case: str) -> None:
    build, problem, headers = _STRUCTURAL[case]
    for kwargs in ({}, {"q": "VEH-1"}, {"status": OperationalStatus.READY}, {"model_id": "MDL-1"}):
        backend = build()
        exc = await _list_failure(_repo(backend), **kwargs)
        assert isinstance(exc, RepositorySchemaError)
        assert (exc.tab, exc.problem) == (VEHICLE_TAB, problem)
        if headers is not None:
            assert list(exc.headers) == headers
        assert backend.writes == []
    body = await _list_http_error(_repo(build()), params={"status": "READY"})
    assert (body["status"], body["code"]) == (500, "VEHICLE_MASTER_SCHEMA_INVALID")
    assert set(body["details"]) == {"tab", "problem", "headers"}
    assert body["details"]["problem"] == problem
    # Same structural error as the dashboard for the same stored data.
    dash = await _dashboard_failure(_repo(build()))
    assert (dash.code, dash.details) == (body["code"], body["details"])


@pytest.mark.asyncio
async def test_g05_legacy_contrast_renamed_status_header_no_longer_lists_all_ready() -> None:
    header = [("status" if h == "operational_status" else h) for h in HEADER]
    repo = _repo(_backend([_row("VEH-1", "WORKING"), _row("VEH-2", "MAINTENANCE")], header=header))
    legacy_items, _ = await repo.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams())
    assert {v.operational_status for v in legacy_items} == {OperationalStatus.READY}  # legacy false all-READY
    with pytest.raises(RepositorySchemaError):
        await _list(repo)


# ---------------------------------------------------------------------------
# G06 — read failures and warm tab loss: READ_FAILED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g06_values_read_failure_is_read_failed() -> None:
    backend = _backend([_row("VEH-1")])
    backend.fail_values_get = True
    exc = await _list_failure(_repo(backend))
    assert type(exc) is RepositoryError
    backend2 = _backend([_row("VEH-1")])
    backend2.fail_values_get = True
    body = await _list_http_error(_repo(backend2))
    assert (body["status"], body["code"], body["details"]) == (503, "VEHICLE_MASTER_READ_FAILED", None)


@pytest.mark.asyncio
async def test_g06_warm_tab_loss_is_read_failed() -> None:
    backend = _backend([_row("VEH-1")])
    repo = _repo(backend)
    assert (await _list(repo)).total_items == 1  # warm the worksheet cache
    del backend.tabs[VEHICLE_TAB]
    exc = await _list_failure(repo)
    assert type(exc) is RepositoryError
    body = await _list_http_error(repo)
    assert (body["status"], body["code"]) == (503, "VEHICLE_MASTER_READ_FAILED")


@pytest.mark.asyncio
async def test_g06_unconfigured_repository_is_read_failed_over_http() -> None:
    from app.config import Settings

    unconfigured = GoogleSheetsRepository(Settings(google_sheet_id="", google_application_credentials=""))
    body = await _list_http_error(unconfigured)
    assert (body["status"], body["code"]) == (503, "VEHICLE_MASTER_READ_FAILED")
    assert "GOOGLE_SHEET_ID" not in json.dumps(body)


# ---------------------------------------------------------------------------
# G07/G08 — exact status classification (classifier unchanged)
# ---------------------------------------------------------------------------

_BLANK = ["", " ", "   ", "\t"]
_UNRECOGNIZED = [" READY", "READY ", "Working", "ready", "UNKNOWN", "ACTIVE", "1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", _BLANK)
async def test_g07_blank_or_whitespace_status_is_blank_status_never_ready(raw: str) -> None:
    rows = [_row("VEH-1", "WORKING"), _row("VEH-2", raw), _row("VEH-3", "READY")]
    for kwargs in ({}, {"q": "VEH-1"}, {"status": OperationalStatus.READY}, {"model_id": "MDL-9"}):
        err = await _list_failure(_repo(_backend(rows)), **kwargs)
        _assert_data(err, {"BLANK_STATUS": 1})


@pytest.mark.asyncio
async def test_g07_missing_status_cell_in_a_short_row_is_blank_status() -> None:
    rows = [_row("VEH-1"), ["VEH-2", "M-2", "MDL-1"]]
    _assert_data(await _list_failure(_repo(_backend(rows))), {"BLANK_STATUS": 1})


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", _UNRECOGNIZED)
async def test_g08_padded_case_unknown_and_non_string_status_is_unrecognized(raw: str) -> None:
    rows = [_row("VEH-1", raw), _row("VEH-2", "READY")]
    for kwargs in ({}, {"q": "VEH-2"}, {"status": OperationalStatus.READY}):
        _assert_data(await _list_failure(_repo(_backend(rows)), **kwargs), {"UNRECOGNIZED_STATUS": 1})


@pytest.mark.asyncio
async def test_g08_every_exact_status_code_is_accepted() -> None:
    rows = [_row(f"VEH-{i}", status) for i, status in enumerate(STATUSES)]
    result = await _list(_repo(_backend(rows)))
    assert result.total_items == 5
    assert [v.operational_status.value for v in result.items] == STATUSES


# ---------------------------------------------------------------------------
# G09/G10 — numeric-looking identifiers still fail (N2 not complete);
# blank and duplicate ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [_row("VEH-1", machine="12"), _row("1046"), _row("VEH-1", model="3"), _row("VEH-1", machine="1,234")],
    ids=["machine_no", "vehicle_id", "model_id", "machine_no_comma"],
)
async def test_g09_numeric_looking_identifiers_are_preserved_as_text(row: list[str]) -> None:
    # Phase 7 Batch 7H2 (DEC-H1, approved 7H1 Final 6.3 update): inverted —
    # the shared validated read now keeps the stored text exactly.
    repo = _repo(_backend([row, _row("VEH-OK")]))
    result = await _list(repo, page_size=200)
    assert result.total_items == 2
    stored = {(v.vehicle_id, v.machine_no, v.model_id) for v in result.items}
    assert (row[0], row[1], row[2]) in stored


@pytest.mark.asyncio
async def test_g10_blank_whitespace_and_duplicate_ids_every_occurrence_counted() -> None:
    rows = [_row("", "READY"), _row("  ", "WORKING"), _row("VEH-7"), _row("VEH-7", "WORKING"), _row("VEH-7"), _row("VEH-8")]
    _assert_data(await _list_failure(_repo(_backend(rows)), q="VEH-8"), {"BLANK_VEHICLE_ID": 2, "DUPLICATE_VEHICLE_ID": 3})


# ---------------------------------------------------------------------------
# G11 — unexpected mapper exceptions are not swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g11_unexpected_mapper_exception_propagates(monkeypatch) -> None:
    repo = _repo(_backend([_row("VEH-1")]))

    def explode(row: dict):
        raise LookupError("unexpected")

    monkeypatch.setattr(repo, "_vehicle_from_row", explode)
    with pytest.raises(LookupError):
        await _list(repo)
    response = await _http(repo, "/api/v1/vehicles")
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# G12/G12b — dashboard/list agreement for the same stored dataset
# ---------------------------------------------------------------------------


def _random_dataset(rng: random.Random) -> list[list[str]]:
    rows = []
    for i in range(rng.randint(0, 40)):
        vid = f"VEH-{i:03d}"
        status = rng.choice(STATUSES)
        machine = f"TC-{i}"
        roll = rng.random()
        if roll < 0.04:
            status = rng.choice(["", "  "])
        elif roll < 0.08:
            status = rng.choice(["ready", " READY", "BROKEN"])
        elif roll < 0.11:
            machine = str(rng.randint(1, 99))
        elif roll < 0.14:
            vid = f"VEH-{max(i - 1, 0):03d}"
        elif roll < 0.16:
            vid = " "
        rows.append(_row(vid, status, machine=machine, model=f"MDL-{i % 3}"))
    if rng.random() < 0.3:
        rows.insert(rng.randint(0, len(rows)), ["", "", "", "", "", "", ""])
    return rows


@pytest.mark.asyncio
async def test_g12_randomized_dataset_family_list_and_dashboard_agree() -> None:
    rng = random.Random(20260930)
    outcomes = {"success": 0, "failure": 0}
    for _ in range(80):
        rows = _random_dataset(rng)
        repo = _repo(_backend(rows))
        service = VehicleService(repo)
        try:
            summary = await service.get_fleet_status_summary()
        except ApiError as dash_err:
            outcomes["failure"] += 1
            for kwargs in ({}, {"status": OperationalStatus.READY}, {"q": "VEH-000"}):
                list_err = await _list_failure(repo, **kwargs)
                assert isinstance(list_err, ApiError)
                assert list_err.code == dash_err.code
                assert list_err.details == {"issue_counts": dash_err.details["issue_counts"]}
            continue
        outcomes["success"] += 1
        # Dashboard total vs UNFILTERED list; each status count vs the
        # STATUS-ONLY list (never a q/model-filtered total vs fleet total).
        assert summary.vehicle_total == (await _list(repo, page_size=1)).total_items
        for status in OperationalStatus:
            assert summary.status_counts[status.value] == (await _list(repo, status=status, page_size=1)).total_items
    assert outcomes["success"] >= 10 and outcomes["failure"] >= 10, outcomes


@pytest.mark.asyncio
async def test_g12b_filtered_request_reports_whole_master_counts_without_ids() -> None:
    rows = [_row("VEH-1", "READY"), _row("VEH-2", "WORKING"), _row("VEH-3", "MAINTENANCE"), _row("VEH-4", "")]
    repo = _repo(_backend(rows))
    response = await _http(repo, "/api/v1/vehicles", params={"q": "veh-2"})
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "VEHICLE_MASTER_DATA_INVALID"
    assert error["details"] == {"issue_counts": {"BLANK_STATUS": 1}}
    assert "VEH-4" not in response.text and "sample_vehicle_ids" not in response.text
    dashboard = await _http(repo, "/api/v1/dashboard/fleet-status")
    assert dashboard.json()["error"]["details"] == {"issue_counts": {"BLANK_STATUS": 1}, "sample_vehicle_ids": ["VEH-4"]}

    # Audit 5.3 dataset D2: VEH-4 fixed to READY.
    rows[3] = _row("VEH-4", "READY")
    fixed = _repo(_with_models(_backend(rows)))
    totals = {}
    for label, params in {"q": {"q": "veh-2"}, "all": {}, "ready": {"status": "READY"}}.items():
        response = await _http(fixed, "/api/v1/vehicles", params=params)
        assert response.status_code == 200
        totals[label] = response.json()["total_items"]
    assert totals == {"q": 1, "all": 4, "ready": 2}
    dash = (await _http(fixed, "/api/v1/dashboard/fleet-status")).json()
    assert dash["vehicle_total"] == 4 and dash["status_counts"]["READY"] == 2


# ---------------------------------------------------------------------------
# G13 — request accounting cold/warm; zero writes in every path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g13_request_counts_cold_and_warm() -> None:
    backend = _with_models(_busy_backend())
    repo = _repo(backend)
    await _list(repo, q="VEH-1")
    # Phase 7 Batch 7J2: a q with usable terms adds one model_master read
    # (cold: one more metadata request) — never maintenance_plan.
    assert backend.metadata_reads() == 3
    assert backend.values_reads() == 2 and backend.values_reads(VEHICLE_TAB) == 1
    assert backend.values_reads("model_master") == 1
    assert all(tab in (None, VEHICLE_TAB, "model_master") for _, _, tab in backend.requests)
    for kwargs in ({}, {"status": OperationalStatus.WORKING}, {"page": 3, "page_size": 5}):
        backend.requests.clear()
        await _list(repo, **kwargs)
        assert backend.requests == [("get", "values", VEHICLE_TAB)]
    assert backend.writes == []


_SCENARIOS: dict[str, Callable[[], FakeSheetsBackend]] = {
    "success": lambda: _with_models(_busy_backend()),
    "empty": lambda: _backend([]),
    "blank_status": lambda: _backend([_row("VEH-1", "")]),
    "unrecognized": lambda: _backend([_row("VEH-1", "ready")]),
    "unmappable": lambda: _backend([_row("VEH-1", created="2026")]),  # numericised timestamp (7H2: identifiers are text)
    "duplicate_id": lambda: _backend([_row("VEH-1"), _row("VEH-1")]),
    "renamed_header": lambda: _backend([_row("VEH-1")], header=[h.upper() for h in HEADER]),
    "no_header_row": lambda: FakeSheetsBackend({VEHICLE_TAB: None}),
    "data_outside_header": lambda: _backend([[*_row("VEH-1"), "x"]]),
    "tab_missing": lambda: FakeSheetsBackend({"model_master": [["model_id"]]}),
    "read_error": lambda: (lambda b: (setattr(b, "fail_values_get", True), b)[1])(_backend([_row("VEH-1")])),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
async def test_z_list_never_writes_in_any_path(scenario: str) -> None:
    backend = _SCENARIOS[scenario]()
    before = backend.snapshot()
    response = await _http(_repo(backend), "/api/v1/vehicles", params={"q": "VEH"})
    assert response.status_code in (200, 500, 503)
    assert backend.writes == []
    assert backend.snapshot() == before
    assert all(method == "get" for method, _, _ in backend.requests)


# ---------------------------------------------------------------------------
# HTTP over Sheets: envelopes, no id leak, success parity with the dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_list_data_invalid_never_leaks_ids_in_message_or_details() -> None:
    rows = [_row("SYN-SECRET-1", ""), _row("SYN-SECRET-2", "Working"), _row("SYN-SECRET-3", created="2026"), _row("SYN-DUP"), _row("SYN-DUP")]
    body = await _list_http_error(_repo(_backend(rows)), params={"model_id": "MDL-1"})
    assert (body["status"], body["code"]) == (500, "VEHICLE_MASTER_DATA_INVALID")
    assert body["details"] == {"issue_counts": {"BLANK_STATUS": 1, "DUPLICATE_VEHICLE_ID": 2, "UNMAPPABLE_ROW": 1, "UNRECOGNIZED_STATUS": 1}}
    assert "SYN-" not in json.dumps(body)


@pytest.mark.asyncio
async def test_http_success_over_sheets_agrees_with_dashboard() -> None:
    repo = _repo(_busy_backend())
    listed = await _http(repo, "/api/v1/vehicles", params={"page_size": 200})
    assert listed.status_code == 200
    body = listed.json()
    ids = [v["vehicle_id"] for v in body["items"]]
    assert ids == sorted(ids) and body["total_items"] == 60
    dashboard = (await _http(repo, "/api/v1/dashboard/fleet-status")).json()
    assert dashboard["vehicle_total"] == body["total_items"]
    for status in STATUSES:
        per_status = (await _http(repo, "/api/v1/vehicles", params={"status": status})).json()
        assert per_status["total_items"] == dashboard["status_counts"][status]


@pytest.mark.asyncio
async def test_http_list_stays_ungated_over_sheets() -> None:
    backend = _busy_backend()
    response = await _http(_repo(backend), "/api/v1/vehicles", headers={"X-Dev-Role": "UNKNOWN"})
    assert response.status_code == 200 and response.json()["total_items"] == 60


@pytest.mark.asyncio
async def test_timestamps_keep_the_legacy_date_handling() -> None:
    # DEC-6: a non-ISO date string still falls back (unchanged mapper).
    repo = _repo(_backend([_row("VEH-1", created="not-a-date", updated=TS)]))
    result = await _list(repo)
    legacy_items, _ = await repo.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams())
    assert [v.model_dump() for v in result.items] == [v.model_dump() for v in legacy_items]
