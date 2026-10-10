"""R2 Batch R2f-d — Equipment ↔ Technician caretaker periods over Google Sheets,
exercised with the REAL installed gspread client on the FAKE HTTP transport
(`RangeBackend`: real range semantics for the bounded reads, emulated
USER_ENTERED writes). An emulation, not live Google Sheets: no credentials,
network or live workbook. Every row is SYNTHETIC; the equipment_caretaker_history
tab exists only inside this fake (it does NOT exist live).

Proves at the transport: equipment_master is read bounded to equipment_id and
never written; technician_master / personnel_master are read bounded; the only
write is ONE append to equipment_caretaker_history ordered by its header (ids
kept as exact text); W1 failures follow the contract with no retry; a TEST
request never resolves the untagged live equipment; a missing history tab fails
closed and is never created; asset_responsibility_history and
personnel_*_link_history are never requested or written.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.caretaker_timeline import EQUIPMENT_CARETAKER_HISTORY_COLUMNS, EQUIPMENT_CARETAKER_HISTORY_TAB
from app.domain.personnel import PERSONNEL_MASTER_COLUMNS
from app.domain.personnel_relationship import PERSONNEL_RELATIONSHIP_COLUMNS
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_relationship_read_sheets_batch_r2f_a import RangeBackend

API = "/api/v1"
ETAB, PTAB, TTAB, HTAB = "equipment_master", "personnel_master", "technician_master", EQUIPMENT_CARETAKER_HISTORY_TAB
BATCH = "SYN-R2FD-BATCH"
SYN = " (สังเคราะห์)"
EQUIPMENT_HEADER = ["equipment_id", "equipment_code", "equipment_name_th", "equipment_type", "brand", "model_name",
                    "serial_no", "equipment_status", "active_status", "company_start_date", "note_th"]
TECH_HEADER = ["technician_id", "first_name", "last_name", "department", "active_status", "source_file"]
UNTOUCHED = {  # present only to prove they are never requested or written
    "asset_responsibility_history": [["assignment_id", "personnel_id", "responsibility_role"],
                                     ["ARH-SYN-1", "P-1", "PRIMARY_OPERATOR"]],
    "personnel_technician_link_history": [["link_event_id", "personnel_id"]],
    "personnel_account_link_history": [["link_event_id", "personnel_id"]],
    "driver_master": [["driver_id", "driver_name_th"], ["DRV-SYN-1", "ผู้ขับ" + SYN]],
}


def _equipment_row(eid: str) -> list[str]:
    values = {h: f"SENTINEL-{h.upper()}" for h in EQUIPMENT_HEADER}
    values["equipment_id"] = eid
    return [values[h] for h in EQUIPMENT_HEADER]


def _backend(*, history: bool = True, history_header=None, equipment_header=None) -> RangeBackend:
    people_header = list(PERSONNEL_MASTER_COLUMNS)
    people = [person("P-1", technician_id="TEC-SYN-1"), person("P-2", technician_id="0042"),
              person("P-T", technician_id="TEC-SYN-1", test=True, batch=BATCH)]
    for row in people:
        row.update(note_th="SENTINEL-NOTE", user_id="SENTINEL-USER")
    eq_header = equipment_header or EQUIPMENT_HEADER
    tabs = {
        ETAB: [list(eq_header), *([v for h, v in zip(EQUIPMENT_HEADER, _equipment_row(e)) if h in eq_header]
                                  for e in ("EQP-SYN-1", "0007"))],
        PTAB: [people_header, *([r.get(h, "") for h in people_header] for r in people)],
        TTAB: [TECH_HEADER, ["TEC-SYN-1", "ช่าง" + SYN, "หนึ่ง" + SYN, "SENTINEL-DEPT", "ACTIVE", "SENTINEL-SRC"],
               ["0042", "ช่าง" + SYN, "สอง" + SYN, "SENTINEL-DEPT", "ACTIVE", "SENTINEL-SRC"]],
        **copy.deepcopy(UNTOUCHED),
    }
    if history:
        tabs[HTAB] = [list(history_header or EQUIPMENT_CARETAKER_HISTORY_COLUMNS)]
    return RangeBackend(tabs)


def _settings(context: str = "REAL", batch: str = BATCH) -> Settings:
    return Settings(data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
                    google_application_credentials="fake.json", registry_data_context=context,
                    registry_test_batch_id=batch)


async def _call(repo, method: str, path: str, *, json=None, settings: Settings | None = None,
                request_id: str | None = None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
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
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def transfer(technician: str, expected: str | None = None, date: str = "2026-01-01") -> dict:
    return {"operation": "TRANSFER", "technician_id": technician, "effective": {"mode": "DATE", "date": date},
            "expected_current_technician_id": expected}


def _rows(backend: RangeBackend, tab: str) -> list[dict[str, str]]:
    head = backend.tabs[tab][0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in backend.tabs[tab][1:]]


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


E1 = f"{API}/equipment/EQP-SYN-1"


@pytest.mark.asyncio
async def test_r2fd_s01_transfer_is_one_history_append_and_reads_are_bounded() -> None:
    backend = _backend()
    before = {t: copy.deepcopy(v) for t, v in backend.tabs.items() if t != HTAB}
    response = await _call(_repo(backend), "POST", f"{E1}/caretaker-events", json=transfer("TEC-SYN-1"))
    assert response.status_code == 200, response.text
    assert [w["kind"] for w in backend.write_log] == ["append"]  # no W2, no projection
    (append,) = backend.write_log
    assert append["tab"] == HTAB and append["valueInputOption"] == "USER_ENTERED"
    assert {t: v for t, v in backend.tabs.items() if t != HTAB} == before  # equipment_master etc. untouched
    (row,) = _rows(backend, HTAB)
    assert (row["equipment_id"], row["technician_id"], row["entry_operation"]) == ("EQP-SYN-1", "TEC-SYN-1", "TRANSFER")
    assert (row["is_test_data"], row["test_batch_id"]) == ("FALSE", "")
    assert backend.data_cells_requested(ETAB) == {"equipment_id"}
    assert backend.data_cells_requested(TTAB) == {"technician_id", "first_name", "last_name", "active_status"}
    assert backend.data_cells_requested(PTAB) == set(PERSONNEL_RELATIONSHIP_COLUMNS)
    assert all(cells for tab, cells in backend.ranges if tab in (ETAB, PTAB, TTAB))  # no whole-tab read
    requested = {tab for tab, _ in backend.ranges}
    assert not requested & set(UNTOUCHED)


@pytest.mark.asyncio
async def test_r2fd_s02_values_follow_the_history_header_and_ids_stay_exact_text() -> None:
    header = list(reversed(EQUIPMENT_CARETAKER_HISTORY_COLUMNS))
    backend = _backend(history_header=header)
    response = await _call(_repo(backend), "POST", f"{API}/equipment/0007/caretaker-events", json=transfer("0042"))
    assert response.status_code == 200, response.text
    (row,) = _rows(backend, HTAB)
    assert (row["equipment_id"], row["technician_id"]) == ("0007", "0042")
    (append,) = backend.write_log
    sent = dict(zip(header, append["values"]))
    assert sent["equipment_id"] == "'0007" and sent["technician_id"] == "'0042"  # forced text, never a number
    assert sent["related_request_id"] == "" and sent["supersedes_record_id"] == ""
    read = await _call(_repo(backend), "GET", f"{API}/equipment/0007/caretakers")
    assert read.json()["current_technician_id"] == "0042"
    reverse = await _call(_repo(backend), "GET", f"{API}/technicians/0042/equipment")
    assert reverse.json()["items"][0]["equipment_id"] == "0007"


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "outcome"), [("reject", "rejected"), ("server_error", "unknown"),
                                                ("apply_then_timeout", "unknown")])
async def test_r2fd_s03_w1_failure_is_reported_and_never_retried(mode, outcome) -> None:
    backend = _backend()
    backend.fail["append"] = mode
    response = await _call(_repo(backend), "POST", f"{E1}/caretaker-events", json=transfer("TEC-SYN-1"))
    assert _code(response) == (503, "CARETAKER_HISTORY_WRITE_FAILED")
    assert response.json()["error"]["details"]["history_write_outcome"] == outcome
    assert [w["kind"] for w in backend.write_log] == ["append"]


@pytest.mark.asyncio
async def test_r2fd_s04_test_context_never_resolves_the_untagged_live_equipment() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs)
    response = await _call(_repo(backend), "POST", f"{E1}/caretaker-events", json=transfer("TEC-SYN-1"),
                           settings=_settings("TEST"))
    assert _code(response) == (422, "EQUIPMENT_SCOPE_UNPROVEN")
    assert backend.write_log == [] and backend.tabs == before
    read = await _call(_repo(backend), "GET", f"{E1}/caretakers", settings=_settings("TEST"))
    assert _code(read) == (422, "EQUIPMENT_SCOPE_UNPROVEN")
    reverse = await _call(_repo(backend), "GET", f"{API}/technicians/TEC-SYN-1/equipment", settings=_settings("TEST"))
    # The REAL untagged row is never a TEST technician (R2f scope-unproven semantics).
    assert _code(reverse) == (422, "TECHNICIAN_SCOPE_UNPROVEN")


@pytest.mark.asyncio
async def test_r2fd_s05_missing_history_tab_fails_closed_and_is_never_created() -> None:
    backend = _backend(history=False)
    response = await _call(_repo(backend), "POST", f"{E1}/caretaker-events", json=transfer("TEC-SYN-1"))
    assert _code(response) == (500, "EQUIPMENT_CARETAKER_HISTORY_SCHEMA_INVALID")
    assert backend.write_log == [] and HTAB not in backend.tabs
    read = await _call(_repo(backend), "GET", f"{E1}/caretakers")
    assert _code(read) == (500, "EQUIPMENT_CARETAKER_HISTORY_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_r2fd_s06_equipment_master_without_equipment_id_fails_closed() -> None:
    backend = _backend(equipment_header=[h for h in EQUIPMENT_HEADER if h != "equipment_id"])
    response = await _call(_repo(backend), "POST", f"{E1}/caretaker-events", json=transfer("TEC-SYN-1"))
    assert _code(response) == (500, "EQUIPMENT_MASTER_SCHEMA_INVALID")
    assert backend.write_log == []


@pytest.mark.asyncio
async def test_r2fd_s07_reads_perform_zero_writes() -> None:
    backend = _backend()
    repo = _repo(backend)
    assert (await _call(repo, "POST", f"{E1}/caretaker-events", json=transfer("TEC-SYN-1"))).status_code == 200
    writes = list(backend.write_log)
    for path in (f"{E1}/caretakers", f"{API}/technicians/TEC-SYN-1/equipment"):
        assert (await _call(repo, "GET", path)).status_code == 200
    assert backend.write_log == writes


def test_r2fd_s08_history_tab_is_not_a_global_readiness_requirement() -> None:
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    core = GoogleSheetsRepository._CORE_SCHEMAS
    assert core and schemas.EQUIPMENT_CARETAKER_HISTORY_SHEET not in core
    assert schemas.EQUIPMENT_REFERENCE_READ_SHEET not in core


def _equipment_batches(backend: RangeBackend) -> int:
    """Number of equipment_master DATA requests (single-column batchGet ranges)."""
    return sum(1 for tab, cells in backend.ranges if tab == ETAB and cells != "1:1")


@pytest.mark.asyncio
async def test_r2fd_s09_persisted_reference_proof_is_one_bounded_read_per_master() -> None:
    backend = _backend()
    repo = _repo(backend)
    assert (await _call(repo, "POST", f"{E1}/caretaker-events", json=transfer("TEC-SYN-1"))).status_code == 200
    backend.ranges.clear()
    assert (await _call(repo, "GET", f"{E1}/caretakers")).status_code == 200
    assert _equipment_batches(backend) == 1  # the locate only; the located equipment is not re-read
    assert backend.data_cells_requested(ETAB) == {"equipment_id"}
    backend.ranges.clear()
    reverse = await _call(repo, "GET", f"{API}/technicians/TEC-SYN-1/equipment")
    assert reverse.status_code == 200 and [i["equipment_id"] for i in reverse.json()["items"]] == ["EQP-SYN-1"]
    assert _equipment_batches(backend) == 1  # ONE bounded read for all distinct stored equipment ids
    assert backend.data_cells_requested(ETAB) == {"equipment_id"}
    assert backend.data_cells_requested(TTAB) == {"technician_id", "first_name", "last_name", "active_status"}
    assert PTAB not in {tab for tab, _ in backend.ranges}  # no lifecycle / personnel read on reads
    assert all(cells for tab, cells in backend.ranges if tab in (ETAB, TTAB))


@pytest.mark.asyncio
async def test_r2fd_s10_a_stored_equipment_missing_from_the_master_fails_the_reverse_read() -> None:
    backend = _backend()
    repo = _repo(backend)
    assert (await _call(repo, "POST", f"{API}/equipment/0007/caretaker-events", json=transfer("0042"))).status_code == 200
    backend.tabs[ETAB] = [row for row in backend.tabs[ETAB] if row[0] != "0007"]  # manual sheet corruption
    reverse = await _call(repo, "GET", f"{API}/technicians/0042/equipment")
    assert _code(reverse) == (500, "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID")
    assert reverse.json()["error"]["details"]["issues"] == {"EQUIPMENT_REFERENCE_MISSING": 1}
    assert "0007" not in reverse.text
    backend.tabs[TTAB] = [row for row in backend.tabs[TTAB] if row[0] != "0042"]
    direct = await _call(repo, "GET", f"{API}/equipment/EQP-SYN-1/caretakers")
    assert direct.status_code == 200  # an equipment with no history references no technician
