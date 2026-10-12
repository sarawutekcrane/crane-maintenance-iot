"""R2 Batch R2f-g — Personnel department movement history over Google Sheets,
exercised with the REAL installed gspread client on the FAKE HTTP transport
(`RangeBackend`). An emulation, not live Google Sheets: no credentials, network
or live workbook. Every row is SYNTHETIC and exists only inside this fake;
department_master and personnel_department_history do NOT exist live.

Proves at the transport: department_master is read bounded to department_id +
its own scope flags and never written; personnel_master is never written (its
legacy `department` text is untouched); the only write is ONE append to
personnel_department_history ordered by its header; the CURRENT live state
(no department_master tab) fails closed; a missing history tab fails closed and
is never created. Writes use the governance-pending capability injected
directly into the request context (no role holds it).
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain import authz
from app.domain.personnel import PERSONNEL_MASTER_TARGET_COLUMNS
from app.domain.personnel_department_timeline import (
    PERSONNEL_DEPARTMENT_HISTORY_COLUMNS,
    PERSONNEL_DEPARTMENT_HISTORY_TAB,
)
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_relationship_read_sheets_batch_r2f_a import RangeBackend

API = "/api/v1"
PTAB, DTAB, HTAB = "personnel_master", "department_master", PERSONNEL_DEPARTMENT_HISTORY_TAB
BATCH = "SYN-R2FG-BATCH"
DEPT_HEADER = ["department_id", "department_name_th", "is_active", "is_test_data", "test_batch_id"]


def _backend(*, departments: bool = True, history: bool = True) -> RangeBackend:
    people = [{**person("P-1"), "department": "SENTINEL-LEGACY-DEPT"},
              {**person("P-T", test=True, batch=BATCH), "department": "SENTINEL-LEGACY-DEPT"}]
    header = list(PERSONNEL_MASTER_TARGET_COLUMNS)
    tabs = {PTAB: [header, *([r.get(h, "") for h in header] for r in people)],
            "department_lifecycle_history": [["lifecycle_event_id", "department_id"]]}
    if departments:
        tabs[DTAB] = [list(DEPT_HEADER), ["DEPT-SYN-A", "SENTINEL-NAME", "SENTINEL-ACTIVE", "FALSE", ""],
                      ["0042", "SENTINEL-NAME", "SENTINEL-ACTIVE", "FALSE", ""]]
    if history:
        tabs[HTAB] = [list(PERSONNEL_DEPARTMENT_HISTORY_COLUMNS)]
    return RangeBackend(tabs)


def _settings(context: str = "REAL") -> Settings:
    return Settings(data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
                    google_application_credentials="fake.json", registry_data_context=context,
                    registry_test_batch_id=BATCH)


async def _call(repo, method: str, path: str, *, json=None, settings: Settings | None = None):
    from app.config import get_settings
    from app.context import RequestContext
    from app.dependencies import get_current_context, get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    chosen = settings or _settings()
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    app.dependency_overrides[get_current_context] = lambda: RequestContext(
        request_id=str(uuid.uuid4()), user_id="synthetic-mover", is_dev_auth=True,
        capabilities=frozenset({authz.CAN_VIEW, authz.CAN_MOVE_PERSONNEL_DEPARTMENT}))
    headers = {"X-Request-Id": str(uuid.uuid4())} if method != "GET" else {}
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def move(department: str, expected: str | None = None, date: str = "2026-01-01") -> dict:
    return {"operation": "TRANSFER", "department_id": department, "effective": {"mode": "DATE", "date": date},
            "expected_current_department_id": expected}


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


P1 = f"{API}/personnel/P-1"


@pytest.mark.asyncio
async def test_r2fg_s01_movement_is_one_append_and_reads_are_bounded() -> None:
    backend = _backend()
    before = {t: copy.deepcopy(v) for t, v in backend.tabs.items() if t != HTAB}
    response = await _call(_repo(backend), "POST", f"{P1}/department-events", json=move("DEPT-SYN-A"))
    assert response.status_code == 200, response.text
    assert [w["kind"] for w in backend.write_log] == ["append"] and backend.write_log[0]["tab"] == HTAB
    assert {t: v for t, v in backend.tabs.items() if t != HTAB} == before  # personnel_master incl. department text
    assert backend.data_cells_requested(DTAB) == {"department_id", "is_test_data", "test_batch_id"}
    assert "department" not in backend.data_cells_requested(PTAB)  # the legacy text is never read
    assert all(cells for tab, cells in backend.ranges if tab in (DTAB, PTAB))


@pytest.mark.asyncio
async def test_r2fg_s02_values_follow_the_header_and_ids_stay_exact_text() -> None:
    backend = _backend()
    repo = _repo(backend)
    assert (await _call(repo, "POST", f"{P1}/department-events", json=move("0042"))).status_code == 200
    sent = dict(zip(PERSONNEL_DEPARTMENT_HISTORY_COLUMNS, backend.write_log[0]["values"]))
    assert sent["department_id"] == "'0042" and sent["personnel_id"] == "'P-1"
    read = (await _call(repo, "GET", f"{P1}/department-history?as_of_date=2026-01-02")).json()
    assert (read["current_department_id"], read["as_of_department_id"]) == ("0042", "0042")


@pytest.mark.asyncio
async def test_r2fg_s03_the_current_live_state_without_department_master_fails_closed() -> None:
    backend = _backend(departments=False)
    before = copy.deepcopy(backend.tabs)
    response = await _call(_repo(backend), "POST", f"{P1}/department-events", json=move("DEPT-SYN-A"))
    assert _code(response) == (500, "DEPARTMENT_MASTER_SCHEMA_INVALID")
    assert backend.write_log == [] and backend.tabs == before and DTAB not in backend.tabs


@pytest.mark.asyncio
async def test_r2fg_s04_missing_history_tab_fails_closed_and_is_never_created() -> None:
    backend = _backend(history=False)
    response = await _call(_repo(backend), "POST", f"{P1}/department-events", json=move("DEPT-SYN-A"))
    assert _code(response) == (500, "PERSONNEL_DEPARTMENT_HISTORY_SCHEMA_INVALID")
    assert backend.write_log == [] and HTAB not in backend.tabs
    assert _code(await _call(_repo(backend), "GET", f"{P1}/department-history")) == (
        500, "PERSONNEL_DEPARTMENT_HISTORY_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_r2fg_s05_test_request_never_resolves_a_real_department() -> None:
    backend = _backend()
    response = await _call(_repo(backend), "POST", f"{API}/personnel/P-T/department-events",
                           json=move("DEPT-SYN-A"), settings=_settings("TEST"))
    assert _code(response) == (422, "DEPARTMENT_SCOPE_UNPROVEN")
    assert backend.write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "outcome"), [("reject", "rejected"), ("server_error", "unknown"),
                                                ("apply_then_timeout", "unknown")])
async def test_r2fg_s06_w1_failure_is_reported_and_never_retried(mode, outcome) -> None:
    backend = _backend()
    backend.fail["append"] = mode
    response = await _call(_repo(backend), "POST", f"{P1}/department-events", json=move("DEPT-SYN-A"))
    assert _code(response) == (503, "PERSONNEL_DEPARTMENT_HISTORY_WRITE_FAILED")
    assert response.json()["error"]["details"]["history_write_outcome"] == outcome
    assert [w["kind"] for w in backend.write_log] == ["append"]


def test_r2fg_s07_not_a_global_readiness_requirement() -> None:
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    core = GoogleSheetsRepository._CORE_SCHEMAS
    assert schemas.PERSONNEL_DEPARTMENT_HISTORY_SHEET not in core and schemas.DEPARTMENT_REFERENCE_READ_SHEET not in core
