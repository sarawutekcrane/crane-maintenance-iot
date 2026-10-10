"""R2 Batch R2f-e — Personnel ↔ Driver identity link writes over Google Sheets,
exercised with the REAL installed gspread client on the FAKE HTTP transport
(`RangeBackend`: real range semantics for the bounded reads, emulated
USER_ENTERED writes). An emulation, not live Google Sheets: no credentials,
network or live workbook. Every row is SYNTHETIC; the driver_id column and the
personnel_driver_link_history tab exist only inside this fake (neither exists
live).

Proves at the transport: the personnel locate read is bounded to personnel_id,
driver_id and the test scope; driver_master is read bounded to driver_id and
NEVER written; W1 (one append to the history tab) precedes W2; W2 is ONE cell —
driver_id at the located row, addressed by header name — as exact text, or a
truly empty cell for UNLINK; W1/W2 transport failures follow the contract; TEST
never writes against the untagged live driver_master; a missing history tab is
never created; and the CURRENT live personnel_master shape (no driver_id) fails
honestly, never defaulting the link to UNSET.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.personnel import PERSONNEL_MASTER_COLUMNS, PERSONNEL_MASTER_TARGET_COLUMNS
from app.domain.personnel_driver_link import (
    PERSONNEL_DRIVER_LINK_HISTORY_COLUMNS,
    PERSONNEL_DRIVER_LINK_HISTORY_TAB,
    PERSONNEL_DRIVER_LINK_MASTER_COLUMNS,
)
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_relationship_read_sheets_batch_r2f_a import RangeBackend

API = "/api/v1"
PTAB, DTAB, HTAB = "personnel_master", "driver_master", PERSONNEL_DRIVER_LINK_HISTORY_TAB
BATCH = "SYN-R2FE-BATCH"
REASON = "แก้ไขข้อมูลหลัก (ทดสอบ)"
DRIVER_HEADER = ["driver_id", "driver_name_th", "phone", "license_no", "license_expiry_date", "active_status",
                 "note_th"]
UNTOUCHED = {  # present only to prove they are never requested or written
    "vehicle_driver": [["assignment_id", "vehicle_id", "driver_id", "start_at", "end_at", "is_primary",
                        "assignment_status", "changed_by_user_id", "note_th"],
                       ["VDA-SYN-1", "VEH-SYN-1", "DRV-SYN-1", "2026-01-01T00:00:00+00:00", "", "TRUE", "", "u", ""]],
    "personnel_technician_link_history": [["link_event_id", "personnel_id"]],
    "personnel_account_link_history": [["link_event_id", "personnel_id"]],
}
REFERENCE_TABS = {  # read by the relationship route only (bounded), never by the driver link
    "technician_master": [["technician_id", "first_name", "last_name", "active_status"],
                          ["SENTINEL-TECH", "ช่าง", "ทดสอบ", "ACTIVE"]],
    "user_account": [["user_id"], ["SENTINEL-USER"]],
}


def _driver_row(did: str, status: str = "INACTIVE") -> list[str]:
    values = {"driver_id": did, "driver_name_th": "SENTINEL-NAME", "phone": "SENTINEL-PHONE",
              "license_no": "SENTINEL-LICENSE", "license_expiry_date": "2020-01-01", "active_status": status,
              "note_th": "SENTINEL-NOTE"}
    return [values[h] for h in DRIVER_HEADER]


def _people(rows, header) -> list[list[str]]:
    return [list(header), *([r.get(h, "") for h in header] for r in rows)]


def _person(pid: str, driver_id: str = "", **kw) -> dict[str, str]:
    row = person(pid, **kw)
    row.update(driver_id=driver_id, department="SENTINEL-DEPT", position="SENTINEL-POS", branch_id="SENTINEL-BR",
               note_th="SENTINEL-NOTE", technician_id=row["technician_id"] or "SENTINEL-TECH",
               user_id=row["user_id"] or "SENTINEL-USER")
    return row


PEOPLE = [_person("P-1"), _person("P-2", driver_id="0042"), _person("P-T", test=True, batch=BATCH)]


def _backend(people=PEOPLE, *, people_header=PERSONNEL_MASTER_TARGET_COLUMNS, history=True) -> RangeBackend:
    tabs = {
        PTAB: _people(copy.deepcopy(people), people_header),
        DTAB: [list(DRIVER_HEADER), _driver_row("DRV-SYN-1"), _driver_row("0042", "ACTIVE"),
               _driver_row("DRV-SYN-3", "")],
        **copy.deepcopy(UNTOUCHED),
        **copy.deepcopy(REFERENCE_TABS),
    }
    if history:
        tabs[HTAB] = [list(PERSONNEL_DRIVER_LINK_HISTORY_COLUMNS)]
    return RangeBackend(tabs)


def _settings(context: str = "REAL", batch: str = BATCH) -> Settings:
    return Settings(data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
                    google_application_credentials="fake.json", registry_data_context=context,
                    registry_test_batch_id=batch)


async def _call(repo, method: str, path: str, *, json=None, settings: Settings | None = None,
                request_id: str | None = None, role: str = "MAINTENANCE_MANAGER"):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    chosen = settings or _settings()
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    headers = {"X-Dev-Role": role}
    if method != "GET":
        headers["X-Request-Id"] = request_id or str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def body(operation: str, expected: str = "", new: str | None = None) -> dict:
    out = {"operation": operation, "expected_driver_id": expected, "reason_th": REASON}
    if new is not None:
        out["new_driver_id"] = new
    return out


def _rows(backend: RangeBackend, tab: str) -> list[dict[str, str]]:
    head = backend.tabs[tab][0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in backend.tabs[tab][1:]]


def _changed_cells(before: list[list[str]], after: list[list[str]]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for r in range(max(len(before), len(after))):
        b = before[r] if r < len(before) else []
        a = after[r] if r < len(after) else []
        for c in range(max(len(a), len(b))):
            if (b[c] if c < len(b) else "") != (a[c] if c < len(a) else ""):
                out.add((r + 1, c + 1))
    return out


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


P1 = f"{API}/personnel/P-1/driver-links"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@pytest.mark.asyncio
async def test_r2fe_s01_link_is_history_first_then_one_targeted_text_cell() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs)
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "DRV-SYN-1"))
    assert response.status_code == 200 and response.json()["changed"] is True
    assert [w["kind"] for w in backend.write_log] == ["append", "batchUpdate"]
    append, update = backend.write_log
    assert append["tab"] == HTAB and append["valueInputOption"] == "USER_ENTERED"
    (cell,) = update["data"]  # exactly ONE cell
    column = PERSONNEL_MASTER_TARGET_COLUMNS.index("driver_id")
    assert cell["range"].endswith(f"!{LETTERS[column]}2") and cell["values"] == [["'DRV-SYN-1"]]
    assert _changed_cells(before[PTAB], backend.tabs[PTAB]) == {(2, column + 1)}
    for tab in (DTAB, *UNTOUCHED):
        assert backend.tabs[tab] == before[tab], tab  # driver_master / vehicle_driver / other links untouched
    (event,) = _rows(backend, HTAB)
    assert (event["event_kind"], event["previous_driver_id"], event["new_driver_id"]) == ("LINK", "", "DRV-SYN-1")
    assert (event["is_test_data"], event["test_batch_id"], event["recorded_by"]) == ("FALSE", "", "dev-user")


@pytest.mark.asyncio
async def test_r2fe_s02_unlink_writes_a_truly_empty_cell_and_ids_stay_exact_text() -> None:
    backend = _backend()
    response = await _call(_repo(backend), "POST", f"{API}/personnel/P-2/driver-links", json=body("UNLINK", "0042"))
    assert response.status_code == 200
    (cell,) = backend.write_log[1]["data"]
    assert cell["values"] == [[""]]  # no apostrophe, space, "None" or "null"
    assert _rows(backend, PTAB)[1]["driver_id"] == ""
    (event,) = _rows(backend, HTAB)
    assert (event["previous_driver_id"], event["new_driver_id"]) == ("0042", "")
    relink = _backend()
    await _call(_repo(relink), "POST", P1, json=body("LINK", "", "0042"))  # held by P-2 -> refused
    assert relink.write_log == []


@pytest.mark.asyncio
async def test_r2fe_s03_column_order_is_resolved_by_header_name() -> None:
    header = list(reversed(PERSONNEL_MASTER_TARGET_COLUMNS))
    backend = _backend(people_header=header)
    before = copy.deepcopy(backend.tabs[PTAB])
    assert (await _call(_repo(backend), "POST", P1, json=body("LINK", "", "DRV-SYN-1"))).status_code == 200
    assert _changed_cells(before, backend.tabs[PTAB]) == {(2, header.index("driver_id") + 1)}


@pytest.mark.asyncio
async def test_r2fe_s04_reads_are_bounded_and_driver_fields_are_never_requested() -> None:
    backend = _backend()
    await _call(_repo(backend), "POST", P1, json=body("LINK", "", "DRV-SYN-1"))
    assert backend.data_cells_requested(PTAB) == set(PERSONNEL_DRIVER_LINK_MASTER_COLUMNS)
    for not_read in ("first_name", "last_name", "active_status", "department", "position", "branch_id",
                     "technician_id", "user_id", "note_th"):
        assert not_read not in backend.data_cells_requested(PTAB)
    assert backend.data_cells_requested(DTAB) == {"driver_id"}
    assert all(cells for tab, cells in backend.ranges if tab in (PTAB, DTAB))  # no whole-tab read
    # vehicle_driver, the other link histories and the other reference masters are never requested
    assert not {tab for tab, _ in backend.ranges} & (set(UNTOUCHED) | set(REFERENCE_TABS))


@pytest.mark.asyncio
async def test_r2fe_s05_driver_status_is_never_a_gate() -> None:
    backend = _backend()  # DRV-SYN-1 is INACTIVE, DRV-SYN-3 has a blank status
    repo = _repo(backend)
    assert (await _call(repo, "POST", P1, json=body("LINK", "", "DRV-SYN-1"))).status_code == 200
    assert (await _call(repo, "POST", P1, json=body("RELINK", "DRV-SYN-1", "DRV-SYN-3"))).status_code == 200
    assert "active_status" not in backend.data_cells_requested(DTAB)


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "outcome"), [("reject", "rejected"), ("server_error", "unknown"),
                                                ("apply_then_timeout", "unknown")])
async def test_r2fe_s06_w1_failure_never_writes_the_cell(mode, outcome) -> None:
    backend = _backend()
    backend.fail["append"] = mode
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "DRV-SYN-1"))
    assert _code(response) == (503, "PERSONNEL_DRIVER_LINK_HISTORY_WRITE_FAILED")
    assert response.json()["error"]["details"]["history_write_outcome"] == outcome
    assert [w["kind"] for w in backend.write_log] == ["append"]  # no W2, no retry
    assert _rows(backend, PTAB)[0]["driver_id"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["reject", "server_error"])
async def test_r2fe_s07_w2_failure_keeps_history_and_reports_mismatch(mode) -> None:
    backend = _backend()
    backend.fail["batchUpdate"] = mode
    repo = _repo(backend)
    response = await _call(repo, "POST", P1, json=body("LINK", "", "DRV-SYN-1"))
    assert _code(response) == (503, "PERSONNEL_DRIVER_LINK_PROJECTION_WRITE_FAILED")
    assert response.json()["error"]["details"]["event_recorded"] is True
    assert [w["kind"] for w in backend.write_log] == ["append", "batchUpdate"]
    backend.fail["batchUpdate"] = None
    read = (await _call(repo, "GET", f"{P1}/history")).json()
    assert (read["current_driver_id"], read["latest_history_driver_id"], read["relationship_consistency"]) == (
        None, "DRV-SYN-1", "MISMATCH")
    rid = _rows(backend, HTAB)[0]["request_id"]
    fixed = await _call(repo, "POST", f"{P1}/reconcile",
                        json={"expected_driver_id": "", "related_request_id": rid, "reason_th": REASON})
    assert fixed.status_code == 200 and fixed.json()["relationship_consistency_after"] == "CONSISTENT"
    assert _rows(backend, PTAB)[0]["driver_id"] == "DRV-SYN-1"


@pytest.mark.asyncio
async def test_r2fe_s08_test_context_never_writes_against_the_untagged_live_driver_master() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs)
    response = await _call(_repo(backend), "POST", f"{API}/personnel/P-T/driver-links",
                           json=body("LINK", "", "DRV-SYN-1"), settings=_settings("TEST"))
    assert _code(response) == (422, "DRIVER_SCOPE_UNPROVEN")
    assert backend.write_log == [] and backend.tabs == before
    real_row_from_test = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "DRV-SYN-1"),
                                     settings=_settings("TEST"))
    assert _code(real_row_from_test) == (404, "PERSONNEL_NOT_FOUND")


@pytest.mark.asyncio
async def test_r2fe_s09_missing_history_tab_fails_closed_and_is_never_created() -> None:
    backend = _backend(history=False)
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "DRV-SYN-1"))
    assert _code(response) == (500, "PERSONNEL_DRIVER_LINK_HISTORY_SCHEMA_INVALID")
    assert backend.write_log == [] and HTAB not in backend.tabs
    read = await _call(_repo(backend), "GET", f"{P1}/history")
    assert _code(read) == (500, "PERSONNEL_DRIVER_LINK_HISTORY_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_r2fe_s10_the_current_live_personnel_header_without_driver_id_fails_honestly() -> None:
    """Today's live personnel_master has no driver_id: every path that needs it
    fails with PERSONNEL_MASTER_SCHEMA_INVALID — never a defaulted UNSET, never
    derived from vehicle_driver — and nothing is written or created."""
    assert "driver_id" not in PERSONNEL_MASTER_COLUMNS
    backend = _backend(people_header=PERSONNEL_MASTER_COLUMNS)
    before = copy.deepcopy(backend.tabs)
    repo = _repo(backend)
    for method, path, payload in (("POST", P1, body("LINK", "", "DRV-SYN-1")), ("GET", f"{P1}/history", None),
                                  ("GET", f"{API}/personnel/P-1/relationships", None)):
        response = await _call(repo, method, path, json=payload)
        assert _code(response) == (500, "PERSONNEL_MASTER_SCHEMA_INVALID"), path
    assert backend.write_log == [] and backend.tabs == before
    assert "vehicle_driver" not in {tab for tab, _ in backend.ranges}


@pytest.mark.asyncio
async def test_r2fe_s11_relationship_read_resolves_the_driver_bounded() -> None:
    backend = _backend()
    response = await _call(_repo(backend), "GET", f"{API}/personnel/P-2/relationships", role="TECHNICIAN")
    assert response.status_code == 200
    assert response.json()["driver"] == {"resolution": "RESOLVED", "driver_id": "0042"}
    for leaked in ("SENTINEL-NAME", "SENTINEL-PHONE", "SENTINEL-LICENSE", "SENTINEL-NOTE", "SENTINEL-DEPT"):
        assert leaked not in response.text  # no driver name / phone / licence / note, no other personnel cell
    assert backend.data_cells_requested(DTAB) == {"driver_id"}
    test = await _call(_repo(backend), "GET", f"{API}/personnel/P-T/relationships", settings=_settings("TEST"))
    assert test.json()["driver"] == {"resolution": "UNSET", "driver_id": None}
    assert backend.write_log == []


def test_r2fe_s12_history_tab_and_driver_column_are_not_global_readiness_requirements() -> None:
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    core = GoogleSheetsRepository._CORE_SCHEMAS
    assert core and schemas.PERSONNEL_DRIVER_LINK_HISTORY_SHEET not in core
    assert schemas.PERSONNEL_DRIVER_LINK_MASTER_SHEET not in core
    assert schemas.DRIVER_MASTER_REFERENCE_READ_SHEET not in core
    assert schemas.DRIVER_MASTER_SHEET in core  # the Phase 6 readiness schema is unchanged
    assert not [s for s in core if "driver_id" in s.required_headers and s.tab_name == "personnel_master"]
