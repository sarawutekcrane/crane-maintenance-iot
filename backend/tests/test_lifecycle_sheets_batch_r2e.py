"""R2 Batch R2e — personnel / department lifecycle over Google Sheets, exercised
with the REAL installed gspread client on the 7H2 WRITABLE FAKE transport: an
emulation, not live Google Sheets. No credentials, network or live workbook;
the lifecycle-history tabs and department_master do not exist live. Fixtures
are SYNTHETIC. Request counts are fake-transport counts, not live cost.

Covers the REAL context (R2E-38, R2E-42 REAL), the TEST scope over Sheets
(R2E-39/40), the targeted single-cell W2, W1/W2 failures, a missing history tab
(fail closed, never created), the live-shape absent department_master, the
domain separation over a workbook that also holds user_account,
technician_master, driver_master and asset_responsibility_history (R2E-45..48),
and the request counts.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.lifecycle_schema import (
    DEPARTMENT_LIFECYCLE_HISTORY_COLUMNS,
    DEPARTMENT_LIFECYCLE_HISTORY_TAB,
    PERSONNEL_LIFECYCLE_HISTORY_COLUMNS,
    PERSONNEL_LIFECYCLE_HISTORY_TAB,
)
from app.domain.personnel import PERSONNEL_MASTER_COLUMNS
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_personnel_read_batch_r2c1 import person
from tests.test_vehicle_text_preservation_sheets_batch7h2 import WritableBackend

API = "/api/v1"
PTAB, DTAB = "personnel_master", "department_master"
BATCH = "SYN-R2E-BATCH"
PID, DID = "PER-SYN-201", "DEPT-SYN-201"
SYN = " (สังเคราะห์)"
DEPT_HEADER = ["department_id", "department_name_th", "is_active", "is_test_data", "test_batch_id"]
OTHER_TABS = {  # present only to prove they are never requested or written
    "user_account": [["user_id", "display_name_th", "role_code", "mfa_enabled", "active_status"],
                     ["USR-SYN-1", "ผู้ใช้" + SYN, "ADMIN", "FALSE", "INACTIVE"]],
    "technician_master": [["technician_id", "active_status"], ["TEC-SYN-1", "ACTIVE"]],
    "driver_master": [["driver_id", "active_status"], ["DRV-SYN-1", "ACTIVE"]],
    "asset_responsibility_history": [["assignment_id", "personnel_id", "assignment_status"],
                                     ["ARH-SYN-1", PID, "ACTIVE"]],
}


def _settings(context: str | None = "REAL", batch: str = "") -> Settings:
    values: dict = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake-sheet-id",
                    "google_application_credentials": "fake.json", "registry_test_batch_id": batch}
    if context:
        values["registry_data_context"] = context
    return Settings(**values)


def _people(*rows) -> list[list[str]]:
    header = list(PERSONNEL_MASTER_COLUMNS)
    return [header, *([r.get(h, "") for h in header] for r in rows)]


def _backend(people=None, *, departments=None, personnel_history=True, department_history=True) -> WritableBackend:
    tabs = {PTAB: _people(*(people or [person(PID)])), **copy.deepcopy(OTHER_TABS)}
    if personnel_history:
        tabs[PERSONNEL_LIFECYCLE_HISTORY_TAB] = [list(PERSONNEL_LIFECYCLE_HISTORY_COLUMNS)]
    if departments is not None:
        tabs[DTAB] = [DEPT_HEADER, *departments]
    if department_history:
        tabs[DEPARTMENT_LIFECYCLE_HISTORY_TAB] = [list(DEPARTMENT_LIFECYCLE_HISTORY_COLUMNS)]
    return WritableBackend(copy.deepcopy(tabs))


async def _http(repo, method: str, path: str, *, json_body=None, settings: Settings | None = None,
                request_id: str | None = None):
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
    chosen = settings or _settings()
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    headers = {"X-Dev-Role": "MAINTENANCE_MANAGER"}
    if method != "GET":
        headers["X-Request-Id"] = request_id or str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers, json=json_body)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _table(backend: WritableBackend, tab: str) -> list[dict[str, str]]:
    head = backend.tabs[tab][0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in backend.tabs[tab][1:]]


def _writes(backend: WritableBackend) -> list[tuple[str, str | None]]:
    return [(w["kind"], w.get("tab")) for w in backend.write_log]


def _touched_tabs(backend: WritableBackend) -> set[str]:
    return {tab for _, kind, tab in backend.requests if kind == "values"} | {
        w.get("tab") or w["data"][0]["range"].partition("!")[0].strip("'") for w in backend.write_log}


def pbody(expected="ACTIVE", reason="ปิดใช้งาน (ทดสอบ)") -> dict:
    return {"expected_active_status": expected, "reason_th": reason}


P_DEACT = f"{API}/personnel/{PID}/deactivations"


@pytest.mark.asyncio
async def test_r2e_38_real_context_writes_one_history_row_and_one_cell() -> None:
    backend = _backend([person("PER-SYN-200"), person(PID), person(PID, is_test_data="TRUE", test_batch_id=BATCH)])
    repo = _repo(backend)
    response = await _http(repo, "POST", P_DEACT, json_body=pbody())
    assert response.status_code == 200, response.text  # R2E-42: the TRUE row creates no REAL ambiguity
    assert _writes(backend) == [("append", PERSONNEL_LIFECYCLE_HISTORY_TAB), ("batchUpdate", None)]
    (update,) = backend.write_log[1]["data"]
    assert update["range"].endswith("!G3")  # active_status column of the FALSE row only (row 3)
    rows = _table(backend, PTAB)
    assert [r["active_status"] for r in rows] == ["ACTIVE", "INACTIVE", "ACTIVE"]
    assert {k: v for k, v in rows[1].items() if k != "active_status"} == {
        k: v for k, v in person(PID).items() if k != "active_status"}
    (event,) = _table(backend, PERSONNEL_LIFECYCLE_HISTORY_TAB)
    assert (event["event_kind"], event["is_test_data"], event["test_batch_id"]) == ("DEACTIVATE", "FALSE", "")


@pytest.mark.asyncio
async def test_r2e_39_40_test_context_over_sheets_targets_only_its_batch() -> None:
    backend = _backend([person(PID), person(PID, is_test_data="TRUE", test_batch_id="OTHER-BATCH")])
    repo = _repo(backend)
    missing = await _http(repo, "POST", P_DEACT, json_body=pbody(), settings=_settings("TEST", BATCH))
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "PERSONNEL_NOT_FOUND")
    assert _writes(backend) == []
    backend = _backend([person(PID), person(PID, is_test_data="TRUE", test_batch_id=BATCH)])
    repo = _repo(backend)
    ok = await _http(repo, "POST", P_DEACT, json_body=pbody(), settings=_settings("TEST", BATCH))
    assert ok.status_code == 200
    assert [r["active_status"] for r in _table(backend, PTAB)] == ["ACTIVE", "INACTIVE"]  # the FALSE row untouched
    (event,) = _table(backend, PERSONNEL_LIFECYCLE_HISTORY_TAB)
    assert (event["is_test_data"], event["test_batch_id"]) == ("TRUE", BATCH)


@pytest.mark.asyncio
async def test_r2e_45_48_no_other_tab_is_read_or_written() -> None:
    backend = _backend()
    repo = _repo(backend)
    await _http(repo, "POST", P_DEACT, json_body=pbody())
    await _http(repo, "POST", f"{API}/personnel/{PID}/reactivations", json_body=pbody("INACTIVE", "เปิด (ทดสอบ)"))
    await _http(repo, "GET", f"{API}/personnel/{PID}/lifecycle-history")
    assert _touched_tabs(backend) == {PTAB, PERSONNEL_LIFECYCLE_HISTORY_TAB}
    for tab, rows in OTHER_TABS.items():
        assert backend.tabs[tab] == rows, tab


@pytest.mark.asyncio
async def test_r2e_missing_history_tab_fails_closed_and_is_never_created() -> None:
    backend = _backend(personnel_history=False)
    repo = _repo(backend)
    response = await _http(repo, "POST", P_DEACT, json_body=pbody())
    assert (response.status_code, response.json()["error"]["code"]) == (
        500, "PERSONNEL_LIFECYCLE_HISTORY_SCHEMA_INVALID")
    assert _writes(backend) == [] and PERSONNEL_LIFECYCLE_HISTORY_TAB not in backend.tabs
    read = await _http(repo, "GET", f"{API}/personnel/{PID}/lifecycle-history")
    assert read.json()["error"]["code"] == "PERSONNEL_LIFECYCLE_HISTORY_SCHEMA_INVALID"


@pytest.mark.asyncio
async def test_r2e_live_shape_without_department_master_is_schema_invalid_never_empty() -> None:
    backend = _backend()  # no department_master tab, as in the live workbook
    repo = _repo(backend)
    for method, path, payload in (
        ("POST", f"{API}/departments/{DID}/deactivations", {"expected_is_active": True, "reason_th": "x"}),
        ("GET", f"{API}/departments/{DID}/lifecycle-history", None),
    ):
        response = await _http(repo, method, path, json_body=payload)
        assert (response.status_code, response.json()["error"]["code"]) == (500, "DEPARTMENT_MASTER_SCHEMA_INVALID")
    assert _writes(backend) == [] and DTAB not in backend.tabs


@pytest.mark.asyncio
async def test_r2e_department_over_sheets_writes_the_literal_flag() -> None:
    backend = _backend(departments=[[DID, "แผนก" + SYN, "TRUE", "FALSE", ""]])
    repo = _repo(backend)
    response = await _http(repo, "POST", f"{API}/departments/{DID}/deactivations",
                           json_body={"expected_is_active": True, "reason_th": "ปิด (ทดสอบ)"})
    assert response.status_code == 200, response.text
    (update,) = backend.write_log[1]["data"]
    assert update["values"] == [["FALSE"]] and update["range"].endswith("!C2")
    assert _table(backend, DTAB)[0] == {"department_id": DID, "department_name_th": "แผนก" + SYN,
                                        "is_active": "FALSE", "is_test_data": "FALSE", "test_batch_id": ""}
    read = (await _http(repo, "GET", f"{API}/departments/{DID}/lifecycle-history")).json()
    assert (read["current_state"], read["lifecycle_consistency"]) == (False, "CONSISTENT")


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "mode", "code", "key", "outcome"), [
    ("append", "reject", "PERSONNEL_LIFECYCLE_HISTORY_WRITE_FAILED", "history_write_outcome", "rejected"),
    ("append", "server_error", "PERSONNEL_LIFECYCLE_HISTORY_WRITE_FAILED", "history_write_outcome", "unknown"),
    ("batchUpdate", "reject", "PERSONNEL_LIFECYCLE_STATE_WRITE_FAILED", "event_recorded", True),
    ("batchUpdate", "server_error", "PERSONNEL_LIFECYCLE_STATE_WRITE_FAILED", "event_recorded", True),
])
async def test_r2e_26_28_write_failures_over_sheets_are_never_retried(kind, mode, code, key, outcome) -> None:
    backend = _backend()
    repo = _repo(backend)
    backend.fail[kind] = mode
    response = await _http(repo, "POST", P_DEACT, json_body=pbody())
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (503, code) and error["details"][key] == outcome
    expected = [("append", PERSONNEL_LIFECYCLE_HISTORY_TAB)] + ([("batchUpdate", None)] if kind == "batchUpdate" else [])
    assert _writes(backend) == expected  # one attempt each, no retry
    backend.fail[kind] = None
    if kind == "batchUpdate":
        read = (await _http(repo, "GET", f"{API}/personnel/{PID}/lifecycle-history")).json()
        assert read["lifecycle_consistency"] == "MISMATCH" and read["current_state"] == "ACTIVE"


@pytest.mark.asyncio
async def test_r2e_request_counts() -> None:
    backend = _backend()
    repo = _repo(backend)
    backend.requests.clear()
    await _http(repo, "POST", P_DEACT, json_body=pbody())
    values = [tab for _, kind, tab in backend.requests if kind == "values"]
    assert values == [PTAB, PERSONNEL_LIFECYCLE_HISTORY_TAB]  # one master read, one history read
    assert _writes(backend) == [("append", PERSONNEL_LIFECYCLE_HISTORY_TAB), ("batchUpdate", None)]
