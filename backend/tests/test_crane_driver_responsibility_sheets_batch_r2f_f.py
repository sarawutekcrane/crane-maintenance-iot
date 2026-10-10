"""R2 Batch R2f-f — Crane / Vehicle ↔ Driver responsibility periods over Google
Sheets, exercised with the REAL installed gspread client on the FAKE HTTP
transport (`RangeBackend`: real range semantics for the bounded reads, emulated
USER_ENTERED writes). An emulation, not live Google Sheets: no credentials,
network or live workbook. Every row is SYNTHETIC; the
crane_driver_responsibility_history tab exists only inside this fake (it does
NOT exist live).

Proves at the transport: vehicle_master is read bounded to vehicle_id and
driver_master to driver_id + active_status, and neither is written; the only
write is ONE append to crane_driver_responsibility_history ordered by its header
(ids kept as exact text); W1 failures follow the contract with no retry; a TEST
request never resolves the untagged live masters; a missing history tab fails
closed and is never created; vehicle_driver, the personnel link histories and
asset_responsibility_history are never requested or written.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.crane_driver_timeline import (
    CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS,
    CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB,
)
from app.domain.personnel import PERSONNEL_MASTER_TARGET_COLUMNS
from app.domain.personnel_relationship import PERSONNEL_RELATIONSHIP_COLUMNS
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_relationship_read_sheets_batch_r2f_a import RangeBackend

API = "/api/v1"
VTAB, DTAB, PTAB, HTAB = "vehicle_master", "driver_master", "personnel_master", CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB
BATCH = "SYN-R2FF-BATCH"
VEHICLE_HEADER = ["vehicle_id", "machine_no", "model_id", "serial_number", "operational_status", "created_at",
                  "updated_at", "responsible_branch_id", "registration_no"]
DRIVER_HEADER = ["driver_id", "driver_name_th", "phone", "license_no", "license_expiry_date", "active_status",
                 "note_th"]
UNTOUCHED = {  # present only to prove they are never requested or written
    "vehicle_driver": [["assignment_id", "vehicle_id", "driver_id", "start_at", "end_at", "is_primary",
                        "assignment_status", "changed_by_user_id", "note_th"],
                       ["VDA-SYN-1", "VEH-SYN-1", "DRV-SYN-2", "2026-01-01T00:00:00+00:00", "", "TRUE", "ACTIVE",
                        "u", ""]],
    "personnel_driver_link_history": [["link_event_id", "personnel_id"]],
    "asset_responsibility_history": [["assignment_id", "responsibility_role"], ["ARH-SYN-1", "PRIMARY_OPERATOR"]],
    "equipment_caretaker_history": [["record_id", "equipment_id"]],
}


def _vehicle_row(vid: str) -> list[str]:
    values = {h: f"SENTINEL-{h.upper()}" for h in VEHICLE_HEADER}
    values["vehicle_id"] = vid
    return [values[h] for h in VEHICLE_HEADER]


def _driver_row(did: str, status: str = "ACTIVE") -> list[str]:
    values = {"driver_id": did, "driver_name_th": "SENTINEL-NAME", "phone": "SENTINEL-PHONE",
              "license_no": "SENTINEL-LICENSE", "license_expiry_date": "2000-01-01", "active_status": status,
              "note_th": "SENTINEL-NOTE"}
    return [values[h] for h in DRIVER_HEADER]


def _backend(*, history: bool = True, history_header=None) -> RangeBackend:
    people = [{**person("P-1"), "driver_id": "DRV-SYN-1"}, {**person("P-I"), "driver_id": "DRV-SYN-9",
                                                             "active_status": "INACTIVE"}]
    header = list(PERSONNEL_MASTER_TARGET_COLUMNS)
    tabs = {
        VTAB: [list(VEHICLE_HEADER), _vehicle_row("VEH-SYN-1"), _vehicle_row("0007")],
        DTAB: [list(DRIVER_HEADER), _driver_row("DRV-SYN-1"), _driver_row("0042"), _driver_row("DRV-SYN-3", "INACTIVE"),
               _driver_row("DRV-SYN-9")],
        PTAB: [header, *([r.get(h, "") for h in header] for r in people)],
        **copy.deepcopy(UNTOUCHED),
    }
    if history:
        tabs[HTAB] = [list(history_header or CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS)]
    return RangeBackend(tabs)


def _settings(context: str = "REAL", batch: str = BATCH) -> Settings:
    return Settings(data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
                    google_application_credentials="fake.json", registry_data_context=context,
                    registry_test_batch_id=batch)


async def _call(repo, method: str, path: str, *, json=None, settings: Settings | None = None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    chosen = settings or _settings()
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    headers = {"X-Dev-Role": "DRIVER_DEPARTMENT_MANAGER"}
    if method != "GET":
        headers["X-Request-Id"] = str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def transfer(driver: str, expected: str | None = None, date: str = "2026-01-01") -> dict:
    return {"operation": "TRANSFER", "driver_id": driver, "effective": {"mode": "DATE", "date": date},
            "expected_current_driver_id": expected}


def _rows(backend: RangeBackend, tab: str) -> list[dict[str, str]]:
    head = backend.tabs[tab][0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in backend.tabs[tab][1:]]


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


V1 = f"{API}/vehicles/VEH-SYN-1"


@pytest.mark.asyncio
async def test_r2ff_s01_transfer_is_one_history_append_and_reads_are_bounded() -> None:
    backend = _backend()
    before = {t: copy.deepcopy(v) for t, v in backend.tabs.items() if t != HTAB}
    response = await _call(_repo(backend), "POST", f"{V1}/responsible-driver-events", json=transfer("DRV-SYN-1"))
    assert response.status_code == 200, response.text
    assert [w["kind"] for w in backend.write_log] == ["append"]  # no W2, no projection
    (append,) = backend.write_log
    assert append["tab"] == HTAB and append["valueInputOption"] == "USER_ENTERED"
    assert {t: v for t, v in backend.tabs.items() if t != HTAB} == before  # every master untouched
    (row,) = _rows(backend, HTAB)
    assert (row["vehicle_id"], row["driver_id"], row["entry_operation"]) == ("VEH-SYN-1", "DRV-SYN-1", "TRANSFER")
    assert backend.data_cells_requested(VTAB) == {"vehicle_id"}
    assert backend.data_cells_requested(DTAB) == {"driver_id", "active_status"}
    assert backend.data_cells_requested(PTAB) == set(PERSONNEL_RELATIONSHIP_COLUMNS)  # the linked-personnel gate
    assert all(cells for tab, cells in backend.ranges if tab in (VTAB, DTAB, PTAB))
    assert not {tab for tab, _ in backend.ranges} & set(UNTOUCHED)


@pytest.mark.asyncio
async def test_r2ff_s02_values_follow_the_history_header_and_ids_stay_exact_text() -> None:
    header = list(reversed(CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS))
    backend = _backend(history_header=header)
    response = await _call(_repo(backend), "POST", f"{API}/vehicles/0007/responsible-driver-events",
                           json=transfer("0042"))
    assert response.status_code == 200, response.text
    sent = dict(zip(header, backend.write_log[0]["values"]))
    assert sent["vehicle_id"] == "'0007" and sent["driver_id"] == "'0042"
    read = await _call(_repo(backend), "GET", f"{API}/vehicles/0007/responsible-drivers")
    assert read.json()["current_driver_id"] == "0042"
    reverse = await _call(_repo(backend), "GET", f"{API}/drivers/0042/vehicles")
    assert reverse.json()["items"][0]["vehicle_id"] == "0007"


@pytest.mark.asyncio
async def test_r2ff_s03_eligibility_reads_driver_status_and_linked_personnel_only() -> None:
    backend = _backend()
    repo = _repo(backend)
    assert _code(await _call(repo, "POST", f"{V1}/responsible-driver-events", json=transfer("DRV-SYN-3"))) == (
        422, "DRIVER_NOT_ACTIVE")
    assert _code(await _call(repo, "POST", f"{V1}/responsible-driver-events", json=transfer("DRV-SYN-9"))) == (
        422, "PERSONNEL_NOT_ACTIVE")
    assert (await _call(repo, "POST", f"{V1}/responsible-driver-events", json=transfer("0042"))).status_code == 200
    assert [w["kind"] for w in backend.write_log] == ["append"]  # only the allowed (unlinked) driver


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "outcome"), [("reject", "rejected"), ("server_error", "unknown"),
                                                ("apply_then_timeout", "unknown")])
async def test_r2ff_s04_w1_failure_is_reported_and_never_retried(mode, outcome) -> None:
    backend = _backend()
    backend.fail["append"] = mode
    response = await _call(_repo(backend), "POST", f"{V1}/responsible-driver-events", json=transfer("DRV-SYN-1"))
    assert _code(response) == (503, "DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED")
    assert response.json()["error"]["details"]["history_write_outcome"] == outcome
    assert [w["kind"] for w in backend.write_log] == ["append"]


@pytest.mark.asyncio
async def test_r2ff_s05_test_context_never_resolves_the_untagged_live_masters() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs)
    test = _settings("TEST")
    assert _code(await _call(_repo(backend), "POST", f"{V1}/responsible-driver-events", json=transfer("DRV-SYN-1"),
                             settings=test)) == (422, "VEHICLE_SCOPE_UNPROVEN")
    assert _code(await _call(_repo(backend), "GET", f"{V1}/responsible-drivers", settings=test)) == (
        422, "VEHICLE_SCOPE_UNPROVEN")
    assert _code(await _call(_repo(backend), "GET", f"{API}/drivers/DRV-SYN-1/vehicles", settings=test)) == (
        422, "DRIVER_SCOPE_UNPROVEN")
    assert backend.write_log == [] and backend.tabs == before


@pytest.mark.asyncio
async def test_r2ff_s06_missing_history_tab_fails_closed_and_is_never_created() -> None:
    backend = _backend(history=False)
    response = await _call(_repo(backend), "POST", f"{V1}/responsible-driver-events", json=transfer("DRV-SYN-1"))
    assert _code(response) == (500, "CRANE_DRIVER_RESPONSIBILITY_HISTORY_SCHEMA_INVALID")
    assert backend.write_log == [] and HTAB not in backend.tabs
    assert _code(await _call(_repo(backend), "GET", f"{V1}/responsible-drivers")) == (
        500, "CRANE_DRIVER_RESPONSIBILITY_HISTORY_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_r2ff_s07_persisted_reference_proof_is_bounded_and_fails_closed() -> None:
    backend = _backend()
    repo = _repo(backend)
    assert (await _call(repo, "POST", f"{API}/vehicles/0007/responsible-driver-events",
                        json=transfer("0042"))).status_code == 200
    backend.ranges.clear()
    reverse = await _call(repo, "GET", f"{API}/drivers/0042/vehicles")
    assert reverse.status_code == 200
    assert sum(1 for tab, cells in backend.ranges if tab == VTAB and cells != "1:1") == 1  # ONE vehicle read
    assert backend.data_cells_requested(VTAB) == {"vehicle_id"}
    backend.tabs[VTAB] = [row for row in backend.tabs[VTAB] if row[0] != "0007"]  # manual sheet corruption
    broken = await _call(repo, "GET", f"{API}/drivers/0042/vehicles")
    assert _code(broken) == (500, "CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID")
    assert broken.json()["error"]["details"]["issues"] == {"VEHICLE_REFERENCE_MISSING": 1}
    assert "0007" not in broken.text
    backend.tabs[DTAB] = [row for row in backend.tabs[DTAB] if row[0] != "0042"]
    assert (await _call(repo, "GET", f"{V1}/responsible-drivers")).status_code == 200  # no history on VEH-SYN-1


@pytest.mark.asyncio
async def test_r2ff_s08_reads_perform_zero_writes() -> None:
    backend = _backend()
    repo = _repo(backend)
    assert (await _call(repo, "POST", f"{V1}/responsible-driver-events", json=transfer("DRV-SYN-1"))).status_code == 200
    writes = list(backend.write_log)
    for path in (f"{V1}/responsible-drivers", f"{API}/drivers/DRV-SYN-1/vehicles"):
        assert (await _call(repo, "GET", path)).status_code == 200
    assert backend.write_log == writes


def test_r2ff_s09_history_tab_is_not_a_global_readiness_requirement() -> None:
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    core = GoogleSheetsRepository._CORE_SCHEMAS
    for schema in (schemas.CRANE_DRIVER_RESPONSIBILITY_HISTORY_SHEET, schemas.VEHICLE_REFERENCE_READ_SHEET,
                   schemas.DRIVER_RESPONSIBILITY_REFERENCE_READ_SHEET):
        assert schema not in core
    assert schemas.VEHICLE_DRIVER_SHEET in core and schemas.DRIVER_MASTER_SHEET in core  # Phase 6 unchanged
