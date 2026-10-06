"""R2 Batch R2c-1 — personnel master over Google Sheets, exercised with the
REAL installed gspread client on the 7B2 FAKE HTTP transport: an emulation,
not live Google Sheets. No credentials, network or live workbook. Request
counts are fake-transport counts, not live cost. Every row is SYNTHETIC; the
header is the verified 12-column personnel_master header row.

Batch-local PROPOSED ids: R2C1-06/07 (fake), R2C1-11, R2C1-12..15, R2C1-17,
R2C1-18.
"""
from __future__ import annotations

import copy

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.personnel import PERSONNEL_MASTER_COLUMNS
from tests.test_fleet_status_summary_sheets_batch7b2 import FakeSheetsBackend, _repo
from tests.test_personnel_read_batch_r2c1 import PEOPLE, SYN, Spy, person
from tests.test_personnel_read_batch_r2c1 import get as mock_get

API = "/api/v1"
TAB = "personnel_master"
HEADER = list(PERSONNEL_MASTER_COLUMNS)


def _tab(rows, header=None) -> list[list[str]]:
    header = list(header or HEADER)
    return [header, *([row.get(h, "") for h in header] for row in rows)]


def _backend(rows=PEOPLE, header=None, **extra_tabs) -> FakeSheetsBackend:
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
# R2C1-06 / R2C1-07 over the fake transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["personnel_id", "first_name", "last_name", "active_status", "is_test_data"])
@pytest.mark.parametrize("path", ["personnel", "personnel/PER-TEST-001"])
async def test_r2c1_07_missing_required_header_is_schema_invalid(missing, path) -> None:
    backend = _backend(header=[h for h in HEADER if h != missing])
    response = await _http(_repo(backend), f"{API}/{path}")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "PERSONNEL_MASTER_SCHEMA_INVALID"
    assert error["details"] == {"tab": TAB, "problem": "MISSING_HEADERS", "headers": [missing]}
    assert backend.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["tab-missing", "no-header-row", "duplicate-header", "read-failed"])
async def test_r2c1_06_07_structural_and_read_failures(case) -> None:
    backend = _backend()
    if case == "tab-missing":
        del backend.tabs[TAB]
    elif case == "no-header-row":
        backend.tabs[TAB] = None
    elif case == "duplicate-header":
        backend.tabs[TAB] = _tab(PEOPLE, [*HEADER, "first_name"])
    else:
        backend.fail_values_get = True
    response = await _http(_repo(backend), f"{API}/personnel")
    error = response.json()["error"]
    if case == "read-failed":
        assert (response.status_code, error["code"]) == (503, "PERSONNEL_MASTER_READ_FAILED")
    else:
        assert (response.status_code, error["code"]) == (500, "PERSONNEL_MASTER_SCHEMA_INVALID")
    assert "items" not in response.text


@pytest.mark.asyncio
async def test_r2c1_07_only_the_five_used_columns_are_required() -> None:
    """The narrow read proves the five columns it uses (the four public ones
    plus is_test_data); a missing other column (e.g. test_batch_id) does not
    block it and is never needed."""
    narrow = ["personnel_id", "first_name", "last_name", "active_status", "is_test_data"]
    backend = _backend(header=narrow)
    response = await _http(_repo(backend), f"{API}/personnel")
    assert response.status_code == 200 and response.json()["total_items"] == 3


# ---------------------------------------------------------------------------
# R2C1-11 / identity text over Sheets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2c1_11_numeric_looking_text_is_kept_exactly() -> None:
    rows = [person("0012", first="0012", last="1e3", status="007"), person("12")]
    backend = _backend(rows)
    repo = _repo(backend)
    items = (await _http(repo, f"{API}/personnel")).json()["items"]
    assert [(p["personnel_id"], p["first_name"], p["last_name"], p["active_status"]) for p in items] == [
        ("0012", "0012", "1e3", "007"), ("12", "ชื่อ" + SYN, "สกุล" + SYN, "ACTIVE")]
    assert (await _http(repo, f"{API}/personnel/0012")).json()["personnel_id"] == "0012"
    assert (await _http(repo, f"{API}/personnel/0012")).json()["first_name"] == "0012"


@pytest.mark.asyncio
async def test_r2c1_07_phantom_rows_and_reordered_header() -> None:
    reordered = list(reversed(HEADER))
    rows = [*PEOPLE, dict.fromkeys(HEADER, "") | {"note_th": "SYN-NOTE-ONLY"}]  # no used cell filled -> phantom
    backend = _backend(rows, header=reordered)
    body = (await _http(_repo(backend), f"{API}/personnel")).json()
    assert body["total_items"] == 3
    assert "SYN-NOTE-ONLY" not in str(body)


# ---------------------------------------------------------------------------
# R2C1-17 — mock / fake parity
# ---------------------------------------------------------------------------


PARITY = {
    "valid": PEOPLE,
    "duplicate": [*PEOPLE, person("PER-TEST-001")],
    "blank-id": [*PEOPLE, person("")],
    "blank-status-and-names": [person("PER-TEST-001", first="", last="", status="")],
    "future-status-text": [person("PER-TEST-001", status="SUSPENDED-ทดสอบ")],
    "mixed-scope": [*PEOPLE, person("PER-TEST-001", is_test_data="TRUE"), person("PER-TEST-404", is_test_data="TRUE")],
    "invalid-flag": [*PEOPLE, person("PER-TEST-004", is_test_data="true")],
    "test-row-blank-id": [*PEOPLE, person("", is_test_data="TRUE")],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(PARITY))
@pytest.mark.parametrize("path", ["personnel", "personnel/PER-TEST-001", "personnel/PER-TEST-404"])
async def test_r2c1_17_mock_and_fake_sheets_agree(case, path) -> None:
    rows = PARITY[case]
    mock = await mock_get(f"{API}/{path}", Spy(copy.deepcopy(rows)))
    backend = _backend(rows)
    fake = await _http(_repo(backend), f"{API}/{path}")
    assert _comparable(fake) == _comparable(mock)
    assert backend.writes == []


# ---------------------------------------------------------------------------
# R2C1-12..15 / R2C1-18 — read cost, no other tab read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["personnel", "personnel/PER-TEST-001"])
async def test_r2c1_12_15_18_request_cost_and_no_other_tab(path) -> None:
    # Only personnel_master exists: any read of user_account, role_permission,
    # technician_master, driver_master, branch_master or an assignment tab
    # would fail; none is requested.
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
async def test_r2c1_scope_flag_is_read_as_text_and_test_rows_excluded_over_sheets() -> None:
    """is_test_data is a text-preserved column of the ONE personnel read (the
    formatted TRUE / FALSE of the boolean cells); test rows are excluded."""
    rows = [*PEOPLE, person("PER-TEST-901", is_test_data="TRUE"), person("PER-TEST-001", is_test_data="TRUE")]
    backend = _backend(rows)
    repo = _repo(backend)
    listed = await _http(repo, f"{API}/personnel")
    assert listed.json()["total_items"] == 3
    assert (await _http(repo, f"{API}/personnel/PER-TEST-901")).status_code == 404
    assert (await _http(repo, f"{API}/personnel/PER-TEST-001")).status_code == 200
    read = await repo.read_personnel_master_validated()
    assert sorted({r["is_test_data"] for r in read.rows}) == ["FALSE", "TRUE"]
    assert backend.writes == []
