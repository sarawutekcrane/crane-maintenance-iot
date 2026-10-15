"""R2-C2 Personnel Scope Option S — the R2c-1 personnel list / detail in the
SERVER-DERIVED data scope (owner decisions S1–S4).

Batch-local ids (not owner business codes): OPS-REAL, -TEST, -CFG (context
configuration), -SCHEMA (schema and integrity), -AUTH, -XSYS (cross-system with
the R2e / R2f reads), -SHEETS (fake transport; never live Google Sheets).

Every row is SYNTHETIC (the PER-TEST- / P- ids are invented). Mock repositories
are isolated per test; nothing is written. The REAL-context contract itself is
pinned unchanged by test_personnel_read_batch_r2c1.py (+ its Sheets twin).
"""
from __future__ import annotations

import copy

import pytest

from app.config import DataRepositoryMode, RegistryDataContext, Settings
from app.domain.personnel import PERSONNEL_MASTER_COLUMNS, PERSONNEL_READ_COLUMNS, scoped_rows
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.repositories.google_sheets import schemas as sheet_schemas
from app.repositories.mock import MockRepository
from tests.test_fleet_status_summary_sheets_batch7b2 import FakeSheetsBackend, _repo
from tests.test_personnel_read_batch_r2c1 import SYN, Spy, error, get, person

API = "/api/v1"
TAB = "personnel_master"
BATCH = "SYN-BATCH-B1"
OTHER = "SYN-BATCH-B2"


def sheets_settings(context: str | None = None, batch: str = "") -> Settings:
    kwargs = dict(data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
                  google_application_credentials="fake.json", registry_test_batch_id=batch)
    if context is not None:
        kwargs["registry_data_context"] = RegistryDataContext(context)
    return Settings(**kwargs)


REAL = sheets_settings("REAL")
TEST = sheets_settings("TEST", BATCH)


def real_row(pid: str, **extra: str) -> dict[str, str]:
    return person(pid, **{"test_batch_id": "", **extra})


def scoped_test_row(pid: str, batch: str = BATCH, **extra: str) -> dict[str, str]:
    return person(pid, **{"first": "ทดสอบ" + SYN, "last": "แถว" + SYN, "is_test_data": "TRUE",
                          "test_batch_id": batch, **extra})


MIXED = [
    real_row("P-REAL-2"), real_row("P-REAL-1"),
    scoped_test_row("P-T-2"), scoped_test_row("P-T-1"), scoped_test_row("P-T-3"),
    scoped_test_row("P-OTHER", batch=OTHER), scoped_test_row("P-BLANK", batch=""),
]


def ids(response) -> list[str]:
    return [p["personnel_id"] for p in response.json()["items"]]


# ---------------------------------------------------------------------------
# OPS-REAL — REAL context: exact-FALSE rows only, contract unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ops_real_list_is_false_rows_only_sorted_and_paged() -> None:
    listed = await get(f"{API}/personnel", Spy(copy.deepcopy(MIXED)), settings=REAL)
    assert listed.status_code == 200 and ids(listed) == ["P-REAL-1", "P-REAL-2"]
    assert listed.json()["total_items"] == 2
    page2 = await get(f"{API}/personnel", Spy(copy.deepcopy(MIXED)), settings=REAL, params={"page": 2, "page_size": 1})
    assert ids(page2) == ["P-REAL-2"] and page2.json()["total_items"] == 2


@pytest.mark.asyncio
async def test_ops_real_detail_exact_id_and_source_text() -> None:
    rows = [real_row("0012", first="  0012", last="=1+1", status=" ACTIVE"), real_row("12"), scoped_test_row("P-T-1")]
    detail = await get(f"{API}/personnel/0012", Spy(rows), settings=REAL)
    assert detail.json() == {"personnel_id": "0012", "first_name": "  0012", "last_name": "=1+1",
                             "active_status": " ACTIVE"}
    for other in ("12 ", "012", "P-T-1"):  # non-exact, or a TEST row: never in REAL
        response = await get(f"{API}/personnel/{other}", Spy(rows), settings=REAL)
        assert response.status_code == 404 and error(response)["code"] == "PERSONNEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# OPS-TEST — TEST context: exact-TRUE rows of exactly the server batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ops_test_list_is_the_server_batch_only_sorted_and_paged() -> None:
    listed = await get(f"{API}/personnel", Spy(copy.deepcopy(MIXED)), settings=TEST)
    assert listed.status_code == 200 and ids(listed) == ["P-T-1", "P-T-2", "P-T-3"]
    assert listed.json()["total_items"] == 3
    page2 = await get(f"{API}/personnel", Spy(copy.deepcopy(MIXED)), settings=TEST, params={"page": 2, "page_size": 2})
    assert ids(page2) == ["P-T-3"]
    assert "test_batch_id" not in listed.text and BATCH not in listed.text and "is_test_data" not in listed.text


@pytest.mark.asyncio
async def test_ops_test_detail_resolves_only_the_server_batch() -> None:
    assert (await get(f"{API}/personnel/P-T-1", Spy(copy.deepcopy(MIXED)), settings=TEST)).json()["personnel_id"] == "P-T-1"
    for excluded in ("P-OTHER", "P-BLANK", "P-REAL-1"):  # other batch, blank batch, REAL row
        response = await get(f"{API}/personnel/{excluded}", Spy(copy.deepcopy(MIXED)), settings=TEST)
        assert (response.status_code, error(response)["code"]) == (404, "PERSONNEL_NOT_FOUND")


@pytest.mark.asyncio
async def test_ops_test_same_id_in_another_scope_is_not_ambiguous() -> None:
    rows = [real_row("P-SAME", first="จริง" + SYN), scoped_test_row("P-SAME", first="ทดสอบ" + SYN),
            scoped_test_row("P-SAME", batch=OTHER)]
    in_test = await get(f"{API}/personnel/P-SAME", Spy(copy.deepcopy(rows)), settings=TEST)
    in_real = await get(f"{API}/personnel/P-SAME", Spy(copy.deepcopy(rows)), settings=REAL)
    assert (in_test.status_code, in_test.json()["first_name"]) == (200, "ทดสอบ" + SYN)
    assert (in_real.status_code, in_real.json()["first_name"]) == (200, "จริง" + SYN)
    for settings in (TEST, REAL):
        assert (await get(f"{API}/personnel", Spy(copy.deepcopy(rows)), settings=settings)).json()["total_items"] == 1


@pytest.mark.asyncio
async def test_ops_test_duplicate_or_blank_id_in_scope_fails_closed() -> None:
    duplicated = [*MIXED, scoped_test_row("P-T-1")]
    listed = await get(f"{API}/personnel", Spy(duplicated), settings=TEST)
    assert (listed.status_code, error(listed)["code"]) == (500, "PERSONNEL_MASTER_DATA_INVALID")
    assert error(listed)["details"] == {"tab": TAB, "issues": {"DUPLICATE_PERSONNEL_ID": 2}}
    detail = await get(f"{API}/personnel/P-T-1", Spy(copy.deepcopy(duplicated)), settings=TEST)
    assert (detail.status_code, error(detail)["details"]) == (409, {"match_count": 2})
    assert (await get(f"{API}/personnel/P-T-2", Spy(copy.deepcopy(duplicated)), settings=TEST)).status_code == 200
    blank = await get(f"{API}/personnel", Spy([*MIXED, scoped_test_row(" ")]), settings=TEST)
    assert error(blank)["details"] == {"tab": TAB, "issues": {"BLANK_PERSONNEL_ID": 1}}
    # identity defects of ANOTHER scope never affect this one
    other_scope = [*MIXED, real_row("P-T-1"), real_row(""), scoped_test_row("", batch=OTHER)]
    assert (await get(f"{API}/personnel", Spy(other_scope), settings=TEST)).json()["total_items"] == 3


# ---------------------------------------------------------------------------
# OPS-CFG — unconfigured / TEST without batch: 503 before any read; no client scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["personnel", "personnel/P-REAL-1"])
async def test_ops_cfg_unconfigured_is_503_before_any_read(path) -> None:
    repo = Spy(copy.deepcopy(MIXED))
    response = await get(f"{API}/{path}", repo, settings=sheets_settings(None))
    assert (response.status_code, error(response)["code"]) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert repo.calls == [] and "P-REAL" not in response.text  # never a REAL (or TEST) fallback


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", ["", "  "])
@pytest.mark.parametrize("path", ["personnel", "personnel/P-T-1"])
async def test_ops_cfg_test_without_batch_is_503_before_any_read(batch, path) -> None:
    repo = Spy(copy.deepcopy(MIXED))
    response = await get(f"{API}/{path}", repo, settings=sheets_settings("TEST", batch))
    assert (response.status_code, error(response)["code"]) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert error(response)["details"] == {"setting": "REGISTRY_TEST_BATCH_ID"}
    assert repo.calls == []


@pytest.mark.asyncio
async def test_ops_cfg_no_client_selected_scope() -> None:
    """Query parameters and headers never select or widen the scope (mock = TEST)."""
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = MockRepository
    params = {"context": "REAL", "data_context": "REAL", "scope": "REAL", "registry_data_context": "REAL",
              "test_batch_id": "MOCK-SEED-R2C1", "is_test_data": "FALSE"}
    headers = {"X-Data-Context": "REAL", "X-Registry-Data-Context": "REAL", "X-Test-Batch-Id": "MOCK-SEED-R2C1"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            listed = await client.get(f"{API}/personnel", params=params, headers=headers)
            detail = await client.get(f"{API}/personnel/PER-TEST-001", params=params, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()
    assert ids(listed) == ["PER-TEST-911", "PER-TEST-912"]
    assert detail.status_code == 404


# ---------------------------------------------------------------------------
# OPS-SCHEMA — five-column REAL contract, TEST-only batch column, flags
# ---------------------------------------------------------------------------


def test_ops_schema_read_contract_stays_five_columns() -> None:
    assert PERSONNEL_READ_COLUMNS == ("personnel_id", "first_name", "last_name", "active_status", "is_test_data")
    assert sheet_schemas.PERSONNEL_MASTER_READ_SHEET.required_headers == PERSONNEL_READ_COLUMNS
    assert "test_batch_id" not in sheet_schemas.PERSONNEL_MASTER_READ_SHEET.required_headers


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["", "true", "YES", " TRUE"])
@pytest.mark.parametrize("path", ["personnel", "personnel/P-T-1"])
async def test_ops_schema_invalid_flag_fails_closed_in_test(flag, path) -> None:
    response = await get(f"{API}/{path}", Spy([*MIXED, scoped_test_row("P-BAD", is_test_data=flag)]), settings=TEST)
    assert (response.status_code, error(response)["code"]) == (500, "PERSONNEL_MASTER_DATA_INVALID")
    assert error(response)["details"] == {"tab": TAB, "issues": {"TEST_FLAG_INVALID": 1}}
    assert "P-T" not in response.text and SYN not in response.text


def test_ops_schema_classification_happens_before_identity_checks() -> None:
    rows = [scoped_test_row("A"), scoped_test_row("A", batch=OTHER), real_row("A"), real_row(""), scoped_test_row("B", is_test_data="x")]
    kept, issues = scoped_rows(rows, "TEST", BATCH)
    assert [r["personnel_id"] for r in kept] == ["A"] and issues == {"TEST_FLAG_INVALID": 1}
    kept, _ = scoped_rows(rows, "REAL", "")
    assert [r["personnel_id"] for r in kept] == ["A", ""]


# ---------------------------------------------------------------------------
# OPS-SHEETS — the fake transport (installed gspread client; never live Sheets)
# ---------------------------------------------------------------------------


def _backend(rows, header=PERSONNEL_MASTER_COLUMNS) -> FakeSheetsBackend:
    header = list(header)
    return FakeSheetsBackend({TAB: [header, *([row.get(h, "") for h in header] for row in copy.deepcopy(rows))]})


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["personnel", "personnel/P-REAL-1"])
async def test_ops_sheets_five_column_header_still_serves_real(path) -> None:
    backend = _backend(MIXED, PERSONNEL_READ_COLUMNS)
    response = await get(f"{API}/{path}", _repo(backend), settings=REAL)
    assert response.status_code == 200
    if path == "personnel":
        assert ids(response) == ["P-REAL-1", "P-REAL-2"]
    assert backend.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["personnel", "personnel/P-T-1"])
async def test_ops_sheets_test_without_batch_column_is_schema_invalid_never_empty(path) -> None:
    backend = _backend(MIXED, PERSONNEL_READ_COLUMNS)
    response = await get(f"{API}/{path}", _repo(backend), settings=TEST)
    assert (response.status_code, error(response)["code"]) == (500, "PERSONNEL_MASTER_SCHEMA_INVALID")
    assert error(response)["details"] == {"tab": TAB, "problem": "MISSING_HEADERS", "headers": ["test_batch_id"]}
    assert "items" not in response.text and backend.writes == []


@pytest.mark.asyncio
async def test_ops_sheets_numeric_looking_batch_and_ids_stay_exact_text() -> None:
    rows = [real_row("0012"), scoped_test_row("0012", batch="007"), scoped_test_row("0013", batch="0012"),
            scoped_test_row("0014", batch="7")]
    for batch, expected in (("007", ["0012"]), ("0012", ["0013"]), ("7", ["0014"])):
        repo = _repo(_backend(rows))
        listed = await get(f"{API}/personnel", repo, settings=sheets_settings("TEST", batch))
        assert ids(listed) == expected, batch
        assert (await get(f"{API}/personnel/{expected[0]}", repo,
                          settings=sheets_settings("TEST", batch))).json()["personnel_id"] == expected[0]
    read = await _repo(_backend(rows)).read_personnel_master_validated()
    assert [r["test_batch_id"] for r in read.rows] == ["", "007", "0012", "7"]


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [REAL, TEST], ids=["REAL", "TEST"])
async def test_ops_sheets_request_cost_unchanged(settings) -> None:
    backend = _backend(MIXED)
    repo = _repo(backend)
    measured = {}
    for phase in ("cold", "warm"):
        backend.requests.clear()
        assert (await get(f"{API}/personnel", repo, settings=settings)).status_code == 200
        measured[phase] = (backend.metadata_reads(), backend.values_reads())
        assert {tab for _, kind, tab in backend.requests if kind == "values"} == {TAB}
    assert measured == {"cold": (2, 1), "warm": (0, 1)}
    assert backend.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [REAL, TEST], ids=["REAL", "TEST"])
@pytest.mark.parametrize("path", ["personnel", "personnel/P-T-1", "personnel/P-REAL-1", "personnel/P-OTHER"])
async def test_ops_sheets_and_mock_agree(settings, path) -> None:
    def comparable(response):
        body = response.json()
        if "error" in body:
            body["error"].pop("request_id", None)
        return response.status_code, body

    fake = await get(f"{API}/{path}", _repo(_backend(MIXED)), settings=settings)
    mock = await get(f"{API}/{path}", Spy(copy.deepcopy(MIXED)), settings=settings)
    assert comparable(fake) == comparable(mock)


# ---------------------------------------------------------------------------
# OPS-AUTH — can_view first, before the context check and any read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [TEST, sheets_settings(None)], ids=["TEST", "UNCONFIGURED"])
@pytest.mark.parametrize("path", ["personnel", "personnel/P-T-1"])
async def test_ops_auth_can_view_required_with_zero_reads(settings, path) -> None:
    repo = Spy(copy.deepcopy(MIXED))
    response = await get(f"{API}/{path}", repo, role="NO_SUCH_ROLE", settings=settings)
    assert (response.status_code, error(response)["code"]) == (403, "HTTP_ERROR")
    assert repo.calls == [] and "P-T" not in response.text
    allowed = Spy(copy.deepcopy(MIXED))
    assert (await get(f"{API}/{path}", allowed, role="TECHNICIAN", settings=TEST)).status_code == 200
    assert allowed.calls == ["read_personnel_master_validated"]


# ---------------------------------------------------------------------------
# OPS-XSYS — the mock (TEST) personnel pages and the R2e / R2f reads agree
# ---------------------------------------------------------------------------

R2_READS = ["/relationships", "/lifecycle-history", "/technician-links/history", "/account-links/history",
            "/driver-links/history", "/department-history"]


@pytest.mark.asyncio
@pytest.mark.parametrize("pid", ["PER-TEST-911", "PER-TEST-912"])
async def test_ops_xsys_test_personnel_resolve_everywhere(pid) -> None:
    repo = MockRepository()
    listed = await get(f"{API}/personnel", repo)
    assert ids(listed) == ["PER-TEST-911", "PER-TEST-912"]
    detail = await get(f"{API}/personnel/{pid}", repo)
    assert detail.status_code == 200 and detail.json()["personnel_id"] == pid
    for suffix in R2_READS:
        response = await get(f"{API}/personnel/{pid}{suffix}", repo)
        assert response.status_code == 200, (suffix, response.text)
        body = response.json()
        assert body.get("personnel_id", body.get("entity_id")) == pid
    relationships = (await get(f"{API}/personnel/{pid}/relationships", repo)).json()
    technician = pid.replace("PER-", "TEC-")
    assert relationships["technician"]["resolution"] == "RESOLVED"
    assert relationships["technician"]["technician_id"] == technician
    assert relationships["account"] == {"resolution": "RESOLVED", "user_id": pid.replace("PER-", "USR-")}
    reverse = (await get(f"{API}/technicians/{technician}/personnel", repo)).json()
    assert reverse["personnel_id"] == pid


@pytest.mark.asyncio
@pytest.mark.parametrize("pid", ["PER-TEST-001", "PER-TEST-002", "PER-TEST-003", "PER-TEST-901"])
async def test_ops_xsys_out_of_scope_personnel_are_excluded_everywhere(pid) -> None:
    repo = MockRepository()
    assert pid not in ids(await get(f"{API}/personnel", repo))
    for suffix in ["", *R2_READS]:
        response = await get(f"{API}/personnel/{pid}{suffix}", repo)
        assert (response.status_code, error(response)["code"]) == (404, "PERSONNEL_NOT_FOUND"), suffix


@pytest.mark.asyncio
async def test_ops_xsys_no_cross_scope_leakage_over_the_same_store() -> None:
    """The one mock personnel store, read in both contexts: no row in both."""
    repo = MockRepository()
    in_test = ids(await get(f"{API}/personnel", repo))
    in_real = ids(await get(f"{API}/personnel", repo, settings=REAL))
    assert in_test == ["PER-TEST-911", "PER-TEST-912"]
    assert in_real == ["PER-TEST-001", "PER-TEST-002", "PER-TEST-003"]
    assert not set(in_test) & set(in_real) and "PER-TEST-901" not in in_test + in_real
    assert repo._personnel_master == MockRepository()._personnel_master  # nothing written
    assert MOCK_TEST_BATCH_ID == "MOCK-7O2B-SYNTHETIC"
