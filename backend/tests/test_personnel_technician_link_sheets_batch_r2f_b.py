"""R2 Batch R2f-b — Personnel ↔ Technician link writes over Google Sheets,
exercised with the REAL installed gspread client on the FAKE HTTP transport
(`RangeBackend`: real range semantics for the bounded reads, emulated
USER_ENTERED writes). An emulation, not live Google Sheets: no credentials,
network or live workbook. Every row is SYNTHETIC; the personnel_technician_link_history
tab exists only inside this fake (it does NOT exist live).

Proves at the transport: the personnel locate read is bounded to the link
columns; W1 (one append to the history tab) precedes W2; W2 is ONE cell —
technician_id at the located row, addressed by header name — written as exact
text, or a truly empty cell for UNLINK; every other cell is byte-equivalent;
W1/W2 transport failures follow the contract; TEST never writes against the
untagged live technician_master; a missing history tab is never created.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.personnel import PERSONNEL_MASTER_COLUMNS
from app.domain.personnel_technician_link import (
    PERSONNEL_TECHNICIAN_LINK_HISTORY_COLUMNS,
    PERSONNEL_TECHNICIAN_LINK_HISTORY_TAB,
    PERSONNEL_TECHNICIAN_LINK_MASTER_COLUMNS,
)
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_relationship_read_sheets_batch_r2f_a import RangeBackend

API = "/api/v1"
PTAB, TTAB, HTAB = "personnel_master", "technician_master", PERSONNEL_TECHNICIAN_LINK_HISTORY_TAB
BATCH = "SYN-R2FB-BATCH"
SYN = " (สังเคราะห์)"
TECH_HEADER = ["technician_id", "first_name", "last_name", "department", "active_status", "source_file"]
REASON = "แก้ไขข้อมูลหลัก (ทดสอบ)"


def _people(rows, header=None) -> list[list[str]]:
    header = list(header or PERSONNEL_MASTER_COLUMNS)
    return [header, *([r.get(h, "") for h in header] for r in rows)]


def _sentinel(row: dict[str, str]) -> dict[str, str]:
    row.update(department="SENTINEL-DEPT", position="SENTINEL-POS", branch_id="SENTINEL-BRANCH",
               note_th="SENTINEL-NOTE")
    return row


PEOPLE = [
    _sentinel(person("P-1")),
    _sentinel(person("P-2", technician_id="0042", user_id="SENTINEL-USER")),
    _sentinel(person("P-T", test=True, batch=BATCH)),
]


def _backend(people=PEOPLE, *, people_header=None, history=True) -> RangeBackend:
    tabs = {
        PTAB: _people(copy.deepcopy(people), people_header),
        TTAB: [TECH_HEADER, ["TEC-SYN-1", "ช่าง" + SYN, "หนึ่ง" + SYN, "SENTINEL-DEPT", "ACTIVE", "SENTINEL-SRC"],
               ["0042", "ช่าง" + SYN, "สอง" + SYN, "SENTINEL-DEPT", "ACTIVE", "SENTINEL-SRC"],
               ["TEC-SYN-3", "ช่าง" + SYN, "สาม" + SYN, "SENTINEL-DEPT", "INACTIVE", "SENTINEL-SRC"]],
        "user_account": [["user_id", "email"], ["SENTINEL-USER", "sentinel@example.invalid"]],
    }
    if history:
        tabs[HTAB] = [list(PERSONNEL_TECHNICIAN_LINK_HISTORY_COLUMNS)]
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


def body(operation: str, expected: str = "", new: str | None = None) -> dict:
    out = {"operation": operation, "expected_technician_id": expected, "reason_th": REASON}
    if new is not None:
        out["new_technician_id"] = new
    return out


def _rows(backend: RangeBackend, tab: str) -> list[dict[str, str]]:
    head = backend.tabs[tab][0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in backend.tabs[tab][1:]]


def _changed_cells(before: list[list[str]], after: list[list[str]]) -> set[tuple[int, int]]:
    height = max(len(before), len(after))
    out: set[tuple[int, int]] = set()
    for r in range(height):
        b = before[r] if r < len(before) else []
        a = after[r] if r < len(after) else []
        for c in range(max(len(a), len(b))):
            if (b[c] if c < len(b) else "") != (a[c] if c < len(a) else ""):
                out.add((r + 1, c + 1))
    return out


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


P1 = f"{API}/personnel/P-1/technician-links"


@pytest.mark.asyncio
async def test_r2fb_s01_link_is_history_first_then_one_targeted_text_cell() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs[PTAB])
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "TEC-SYN-1"))
    assert response.status_code == 200 and response.json()["changed"] is True
    assert [w["kind"] for w in backend.write_log] == ["append", "batchUpdate"]
    append, update = backend.write_log
    assert append["tab"] == HTAB and append["valueInputOption"] == "USER_ENTERED"
    (cell,) = update["data"]  # exactly ONE cell
    column = PERSONNEL_MASTER_COLUMNS.index("technician_id")
    letter = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[column]
    assert cell["range"].endswith(f"!{letter}2") and cell["values"] == [["'TEC-SYN-1"]]
    assert _changed_cells(before, backend.tabs[PTAB]) == {(2, column + 1)}
    assert _rows(backend, PTAB)[0]["technician_id"] == "TEC-SYN-1"
    (event,) = _rows(backend, HTAB)
    assert (event["event_kind"], event["previous_technician_id"], event["new_technician_id"]) == (
        "LINK", "", "TEC-SYN-1")
    assert (event["is_test_data"], event["test_batch_id"]) == ("FALSE", "")


@pytest.mark.asyncio
async def test_r2fb_s02_unlink_writes_a_truly_empty_cell_and_ids_stay_exact_text() -> None:
    backend = _backend()
    response = await _call(_repo(backend), "POST", f"{API}/personnel/P-2/technician-links",
                           json=body("UNLINK", "0042"))
    assert response.status_code == 200
    (cell,) = backend.write_log[1]["data"]
    assert cell["values"] == [[""]]  # no apostrophe, space, "None" or "null"
    assert _rows(backend, PTAB)[1]["technician_id"] == ""
    (event,) = _rows(backend, HTAB)
    assert (event["previous_technician_id"], event["new_technician_id"]) == ("0042", "")
    relink = _backend()
    await _call(_repo(relink), "POST", P1, json=body("LINK", "", "0042"))  # held by P-2 -> refused
    assert relink.write_log == []


@pytest.mark.asyncio
async def test_r2fb_s03_column_order_is_resolved_by_header_name() -> None:
    header = list(reversed(PERSONNEL_MASTER_COLUMNS))
    backend = _backend(people_header=header)
    before = copy.deepcopy(backend.tabs[PTAB])
    assert (await _call(_repo(backend), "POST", P1, json=body("LINK", "", "TEC-SYN-1"))).status_code == 200
    column = header.index("technician_id")
    assert _changed_cells(before, backend.tabs[PTAB]) == {(2, column + 1)}


@pytest.mark.asyncio
async def test_r2fb_s04_personnel_locate_read_is_bounded() -> None:
    backend = _backend()
    await _call(_repo(backend), "POST", P1, json=body("LINK", "", "TEC-SYN-1"))
    assert backend.data_cells_requested(PTAB) == set(PERSONNEL_TECHNICIAN_LINK_MASTER_COLUMNS)
    for not_read in ("user_id", "department", "position", "branch_id", "note_th"):
        assert not_read not in backend.data_cells_requested(PTAB)
    assert backend.data_cells_requested(TTAB) == {"technician_id", "first_name", "last_name", "active_status"}
    assert all(cells for tab, cells in backend.ranges if tab in (PTAB, TTAB))  # no unbounded whole-tab read
    assert "user_account" not in {tab for tab, _ in backend.ranges}


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "outcome"), [("reject", "rejected"), ("server_error", "unknown"),
                                                ("apply_then_timeout", "unknown")])
async def test_r2fb_s05_w1_failure_never_writes_the_cell(mode, outcome) -> None:
    backend = _backend()
    backend.fail["append"] = mode
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "TEC-SYN-1"))
    assert _code(response) == (503, "PERSONNEL_TECHNICIAN_LINK_HISTORY_WRITE_FAILED")
    assert response.json()["error"]["details"]["history_write_outcome"] == outcome
    assert [w["kind"] for w in backend.write_log] == ["append"]  # no W2, no retry
    assert _rows(backend, PTAB)[0]["technician_id"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["reject", "server_error"])
async def test_r2fb_s06_w2_failure_keeps_history_and_reports_mismatch(mode) -> None:
    backend = _backend()
    backend.fail["batchUpdate"] = mode
    repo = _repo(backend)
    response = await _call(repo, "POST", P1, json=body("LINK", "", "TEC-SYN-1"))
    assert _code(response) == (503, "PERSONNEL_TECHNICIAN_LINK_PROJECTION_WRITE_FAILED")
    assert response.json()["error"]["details"]["event_recorded"] is True
    assert [w["kind"] for w in backend.write_log] == ["append", "batchUpdate"]
    backend.fail["batchUpdate"] = None
    read = (await _call(repo, "GET", f"{P1}/history")).json()
    assert (read["current_technician_id"], read["latest_history_technician_id"], read["relationship_consistency"]) == (
        None, "TEC-SYN-1", "MISMATCH")
    rid = _rows(backend, HTAB)[0]["request_id"]
    fixed = await _call(repo, "POST", f"{P1}/reconcile",
                        json={"expected_technician_id": "", "related_request_id": rid, "reason_th": REASON})
    assert fixed.status_code == 200 and fixed.json()["relationship_consistency_after"] == "CONSISTENT"
    assert _rows(backend, PTAB)[0]["technician_id"] == "TEC-SYN-1"


@pytest.mark.asyncio
async def test_r2fb_s07_test_context_never_writes_against_the_untagged_live_technicians() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs)
    response = await _call(_repo(backend), "POST", f"{API}/personnel/P-T/technician-links",
                           json=body("LINK", "", "TEC-SYN-1"), settings=_settings("TEST"))
    assert _code(response) == (422, "TECHNICIAN_SCOPE_UNPROVEN")
    assert backend.write_log == [] and backend.tabs == before
    real_row_from_test = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "TEC-SYN-1"),
                                     settings=_settings("TEST"))
    assert _code(real_row_from_test) == (404, "PERSONNEL_NOT_FOUND")


@pytest.mark.asyncio
async def test_r2fb_s08_missing_history_tab_fails_closed_and_is_never_created() -> None:
    backend = _backend(history=False)
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "TEC-SYN-1"))
    assert _code(response) == (500, "PERSONNEL_TECHNICIAN_LINK_HISTORY_SCHEMA_INVALID")
    assert backend.write_log == [] and HTAB not in backend.tabs
    read = await _call(_repo(backend), "GET", f"{P1}/history")
    assert _code(read) == (500, "PERSONNEL_TECHNICIAN_LINK_HISTORY_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_r2fb_s09_history_tab_is_not_a_global_readiness_requirement() -> None:
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    core = GoogleSheetsRepository._CORE_SCHEMAS
    assert core and schemas.PERSONNEL_TECHNICIAN_LINK_HISTORY_SHEET not in core
    assert schemas.PERSONNEL_TECHNICIAN_LINK_MASTER_SHEET not in core
