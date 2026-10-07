"""R2 Batch R2c-2 — department master over Google Sheets, exercised with the
REAL installed gspread client on the 7B2 FAKE HTTP transport: an emulation,
not live Google Sheets. No credentials, network or live workbook (the live
department_master tab does not exist yet). Request counts are fake-transport
counts, not live cost. Every row is SYNTHETIC (DEPT-TEST- ids are TEST-ONLY,
not a production convention); the header is the frozen 5-column contract.

Batch-local PROPOSED ids: R2C2-15..18 (fake), R2C2-21..25.
"""
from __future__ import annotations

import copy

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.department import DEPARTMENT_MASTER_COLUMNS
from tests.test_department_read_batch_r2c2 import (
    DEPTS,
    SYN,
    Spy,
    dept,
    synthetic_test_row,
)
from tests.test_department_read_batch_r2c2 import get as mock_get
from tests.test_fleet_status_summary_sheets_batch7b2 import FakeSheetsBackend, _repo

API = "/api/v1"
TAB = "department_master"
HEADER = list(DEPARTMENT_MASTER_COLUMNS)


def _tab(rows, header=None) -> list[list[str]]:
    header = list(header or HEADER)
    return [header, *([row.get(h, "") for h in header] for row in rows)]


def _backend(rows=DEPTS, header=None, **extra_tabs) -> FakeSheetsBackend:
    return FakeSheetsBackend({TAB: _tab(copy.deepcopy(rows), header), **extra_tabs})


async def _http(repo, path: str, params=None):
    from app.config import get_settings
    from app.dependencies import (
        get_repository,
        get_settings_dependency,
        reset_dependency_cache,
    )
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_settings_dependency] = lambda: Settings(
        data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
        google_application_credentials="fake.json")
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, params=params)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _comparable(response) -> tuple[int, dict]:
    body = response.json()
    if "error" in body:
        body["error"].pop("request_id", None)
    return response.status_code, body


# ---------------------------------------------------------------------------
# R2C2-16 / R2C2-17 / R2C2-18 over the fake transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["department_id", "department_name_th", "is_active", "is_test_data"])
@pytest.mark.parametrize("path", ["departments", "departments/DEPT-TEST-001"])
async def test_r2c2_16_missing_required_header_is_schema_invalid(missing, path) -> None:
    backend = _backend(header=[h for h in HEADER if h != missing])
    response = await _http(_repo(backend), f"{API}/{path}")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "DEPARTMENT_MASTER_SCHEMA_INVALID"
    assert error["details"] == {"tab": TAB, "problem": "MISSING_HEADERS", "headers": [missing]}
    assert backend.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["tab-missing", "no-header-row", "duplicate-header", "read-failed"])
@pytest.mark.parametrize("path", ["departments", "departments/DEPT-TEST-001"])
async def test_r2c2_16_18_structural_and_read_failures(case, path) -> None:
    """The live workbook has no department_master yet: the department routes
    answer DEPARTMENT_MASTER_SCHEMA_INVALID — never 200 [], a default or 404."""
    backend = _backend()
    if case == "tab-missing":
        del backend.tabs[TAB]
    elif case == "no-header-row":
        backend.tabs[TAB] = None
    elif case == "duplicate-header":
        backend.tabs[TAB] = _tab(DEPTS, [*HEADER, "department_name_th"])
    else:
        backend.fail_values_get = True
    response = await _http(_repo(backend), f"{API}/{path}")
    error = response.json()["error"]
    if case == "read-failed":
        assert (response.status_code, error["code"]) == (503, "DEPARTMENT_MASTER_READ_FAILED")
    else:
        assert (response.status_code, error["code"]) == (500, "DEPARTMENT_MASTER_SCHEMA_INVALID")
    assert "items" not in response.text
    assert backend.writes == []


@pytest.mark.asyncio
async def test_r2c2_17_missing_test_batch_id_does_not_block_the_bounded_read() -> None:
    narrow = ["department_id", "department_name_th", "is_active", "is_test_data"]
    backend = _backend(header=narrow)
    response = await _http(_repo(backend), f"{API}/departments")
    assert response.status_code == 200 and response.json()["total_items"] == 3


# ---------------------------------------------------------------------------
# Exact text, phantom rows, header order over Sheets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c2_exact_text_is_kept_over_sheets() -> None:
    rows = [dept("0012", "0012", "FALSE"), dept("12", "  ชื่อ" + SYN + " ")]
    repo = _repo(_backend(rows))
    items = (await _http(repo, f"{API}/departments")).json()["items"]
    assert [(d["department_id"], d["department_name_th"], d["is_active"]) for d in items] == [
        ("0012", "0012", False), ("12", "  ชื่อ" + SYN + " ", True)]
    assert (await _http(repo, f"{API}/departments/0012")).json()["department_id"] == "0012"
    assert (await _http(repo, f"{API}/departments/012")).status_code == 404


@pytest.mark.asyncio
async def test_r2c2_15_phantom_rows_and_reordered_header() -> None:
    empty = dict.fromkeys(HEADER, "")
    rows = [*DEPTS, {**empty, "is_test_data": "FALSE"}, {**empty, "test_batch_id": "SYN-BATCH-ONLY"}]
    backend = _backend(rows, header=list(reversed(HEADER)))
    body = (await _http(_repo(backend), f"{API}/departments")).json()
    assert body["total_items"] == 3
    assert "SYN-BATCH-ONLY" not in str(body)


@pytest.mark.asyncio
async def test_r2c2_flags_are_read_as_text_and_test_rows_excluded_over_sheets() -> None:
    rows = [*DEPTS, synthetic_test_row("DEPT-TEST-901"), synthetic_test_row("DEPT-TEST-001")]
    backend = _backend(rows)
    repo = _repo(backend)
    assert (await _http(repo, f"{API}/departments")).json()["total_items"] == 3
    assert (await _http(repo, f"{API}/departments/DEPT-TEST-901")).status_code == 404
    assert (await _http(repo, f"{API}/departments/DEPT-TEST-001")).status_code == 200
    read = await repo.read_department_master_validated()
    assert sorted({r["is_test_data"] for r in read.rows}) == ["FALSE", "TRUE"]
    assert sorted({r["is_active"] for r in read.rows}) == ["FALSE", "TRUE"]
    assert backend.writes == []


# ---------------------------------------------------------------------------
# R2C2-24 — mock / fake parity
# ---------------------------------------------------------------------------


PARITY = {
    "valid": DEPTS,
    "duplicate": [*DEPTS, dept("DEPT-TEST-001")],
    "blank-id": [*DEPTS, dept("")],
    "blank-name": [*DEPTS, dept("DEPT-TEST-004", " ")],
    "bad-active": [*DEPTS, dept("DEPT-TEST-004", active="yes")],
    "inactive": [dept("DEPT-TEST-001", active="FALSE")],
    "mixed-scope": [*DEPTS, synthetic_test_row("DEPT-TEST-001"), synthetic_test_row("DEPT-TEST-404")],
    "invalid-flag": [*DEPTS, dept("DEPT-TEST-004", is_test_data="true")],
    "test-row-malformed": [*DEPTS, synthetic_test_row("", is_active="", department_name_th="")],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(PARITY))
@pytest.mark.parametrize("path", ["departments", "departments/DEPT-TEST-001", "departments/DEPT-TEST-404"])
async def test_r2c2_24_mock_and_fake_sheets_agree(case, path) -> None:
    rows = PARITY[case]
    mock = await mock_get(f"{API}/{path}", Spy(copy.deepcopy(rows)))
    backend = _backend(rows)
    fake = await _http(_repo(backend), f"{API}/{path}")
    assert _comparable(fake) == _comparable(mock)
    assert backend.writes == []


# ---------------------------------------------------------------------------
# R2C2-21..R2C2-23 / R2C2-25 — read cost, no other tab read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["departments", "departments/DEPT-TEST-001"])
async def test_r2c2_21_25_request_cost_and_no_other_tab(path) -> None:
    # Only department_master exists: any read of personnel_master,
    # branch_master, user_account, role_permission, technician_master,
    # driver_master, an assignment or a workshop tab would fail; none is
    # requested.
    backend = _backend()
    repo = _repo(backend)
    measured = {}
    for phase in ("cold", "warm"):
        backend.requests.clear()
        response = await _http(repo, f"{API}/{path}")
        assert response.status_code == 200
        measured[phase] = (backend.metadata_reads(), backend.values_reads())
        assert backend.values_reads(TAB) == 1
        assert {tab for _, kind, tab in backend.requests if kind == "values"} == {TAB}
    assert measured == {"cold": (2, 1), "warm": (0, 1)}  # (metadata reads, values reads)
    assert backend.writes == []


@pytest.mark.asyncio
async def test_r2c2_21_personnel_tab_present_is_still_not_read() -> None:
    """Even with a personnel_master tab in the workbook, the department read
    never requests it (no personnel join)."""
    personnel = [["personnel_id", "department", "is_test_data"], ["PER-TEST-001", "SYN-DEPT-LABEL", "FALSE"]]
    branch = [["branch_id", "branch_name", "is_active"], ["BR-TEST-1", "สาขา" + SYN, "TRUE"]]
    backend = _backend(personnel_master=personnel, branch_master=branch)
    response = await _http(_repo(backend), f"{API}/departments")
    assert response.status_code == 200 and "SYN-DEPT-LABEL" not in response.text
    assert {tab for _, kind, tab in backend.requests if kind == "values"} == {TAB}
