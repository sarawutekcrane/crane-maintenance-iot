"""R2 Batch R2f-c — Personnel ↔ User Account link writes over Google Sheets,
exercised with the REAL installed gspread client on the FAKE HTTP transport
(`RangeBackend`). An emulation, not live Google Sheets: no credentials,
network or live workbook. Every row is SYNTHETIC; personnel_account_link_history
exists only inside this fake (it does NOT exist live).

Proves at the transport: the personnel locate read is bounded to the account
link columns (no technician_id / department / position / branch / note);
user_account is read as user_id ONLY and is never written; W1 (one append)
precedes W2; W2 is ONE cell — personnel_master.user_id at the located row,
addressed by header name — as exact text, or a truly empty cell for UNLINK;
TEST never writes against the untagged live user_account; a missing history
tab is never created.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.personnel import PERSONNEL_MASTER_COLUMNS
from app.domain.personnel_account_link import (
    PERSONNEL_ACCOUNT_LINK_HISTORY_COLUMNS,
    PERSONNEL_ACCOUNT_LINK_HISTORY_TAB,
    PERSONNEL_ACCOUNT_LINK_MASTER_COLUMNS,
)
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_relationship_read_sheets_batch_r2f_a import RangeBackend

API = "/api/v1"
PTAB, ATAB, HTAB = "personnel_master", "user_account", PERSONNEL_ACCOUNT_LINK_HISTORY_TAB
BATCH = "SYN-R2FC-BATCH"
REASON = "เชื่อมบัญชีผู้ใช้ (ทดสอบ)"
ACCOUNT_HEADER = ["display_name_th", "email", "user_id", "phone", "role_code", "mfa_enabled", "active_status",
                  "note_th"]


def _sentinel(row: dict[str, str]) -> dict[str, str]:
    row.update(department="SENTINEL-DEPT", position="SENTINEL-POS", branch_id="SENTINEL-BRANCH",
               note_th="SENTINEL-NOTE")
    return row


PEOPLE = [
    _sentinel(person("P-1", technician_id="SENTINEL-TECH")),
    _sentinel(person("P-2", user_id="00077")),
    _sentinel(person("P-T", test=True, batch=BATCH)),
]


def _account(uid: str) -> list[str]:
    values = {"display_name_th": "SENTINEL-NAME", "email": "sentinel@example.invalid", "user_id": uid,
              "phone": "SENTINEL-PHONE", "role_code": "SENTINEL-ROLE", "mfa_enabled": "SENTINEL-MFA",
              "active_status": "SENTINEL-STATUS", "note_th": "SENTINEL-NOTE"}
    return [values[h] for h in ACCOUNT_HEADER]


def _backend(people=PEOPLE, *, people_header=None, history=True) -> RangeBackend:
    header = list(people_header or PERSONNEL_MASTER_COLUMNS)
    tabs = {
        PTAB: [header, *([r.get(h, "") for h in header] for r in copy.deepcopy(people))],
        ATAB: [ACCOUNT_HEADER, _account("USR-SYN-1"), _account("00077"), _account("TEST-USER-1")],
        "technician_master": [["technician_id", "first_name", "last_name", "active_status"],
                              ["SENTINEL-TECH", "x", "y", "ACTIVE"]],
    }
    if history:
        tabs[HTAB] = [list(PERSONNEL_ACCOUNT_LINK_HISTORY_COLUMNS)]
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
    headers = {"X-Dev-Role": "MAINTENANCE_MANAGER"}
    if method != "GET":
        headers["X-Request-Id"] = str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def body(operation: str, expected: str = "", new: str | None = None) -> dict:
    out = {"operation": operation, "expected_user_id": expected, "reason_th": REASON}
    if new is not None:
        out["new_user_id"] = new
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


P1 = f"{API}/personnel/P-1/account-links"


@pytest.mark.asyncio
async def test_r2fc_s01_link_is_history_first_then_one_user_id_cell() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs)
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "USR-SYN-1"))
    assert response.status_code == 200 and response.json()["changed"] is True
    assert [w["kind"] for w in backend.write_log] == ["append", "batchUpdate"]
    append, update = backend.write_log
    assert append["tab"] == HTAB
    (cell,) = update["data"]  # exactly ONE cell
    column = PERSONNEL_MASTER_COLUMNS.index("user_id")
    assert cell["range"].endswith(f"!{'ABCDEFGHIJKLMNOPQRSTUVWXYZ'[column]}2")
    assert cell["values"] == [["'USR-SYN-1"]]
    assert _changed_cells(before[PTAB], backend.tabs[PTAB]) == {(2, column + 1)}
    assert backend.tabs[ATAB] == before[ATAB] and backend.tabs["technician_master"] == before["technician_master"]
    assert _rows(backend, PTAB)[0]["technician_id"] == "SENTINEL-TECH"  # the technician link is untouched
    (event,) = _rows(backend, HTAB)
    assert (event["event_kind"], event["previous_user_id"], event["new_user_id"], event["recorded_by"]) == (
        "LINK", "", "USR-SYN-1", "dev-user")


@pytest.mark.asyncio
async def test_r2fc_s02_unlink_writes_a_truly_empty_cell_and_ids_stay_exact_text() -> None:
    backend = _backend()
    response = await _call(_repo(backend), "POST", f"{API}/personnel/P-2/account-links", json=body("UNLINK", "00077"))
    assert response.status_code == 200
    (cell,) = backend.write_log[1]["data"]
    assert cell["values"] == [[""]]
    assert _rows(backend, PTAB)[1]["user_id"] == ""
    (event,) = _rows(backend, HTAB)
    assert (event["previous_user_id"], event["new_user_id"]) == ("00077", "")


@pytest.mark.asyncio
async def test_r2fc_s03_column_order_is_resolved_by_header_name() -> None:
    header = list(reversed(PERSONNEL_MASTER_COLUMNS))
    backend = _backend(people_header=header)
    before = copy.deepcopy(backend.tabs[PTAB])
    assert (await _call(_repo(backend), "POST", P1, json=body("LINK", "", "USR-SYN-1"))).status_code == 200
    assert _changed_cells(before, backend.tabs[PTAB]) == {(2, header.index("user_id") + 1)}


@pytest.mark.asyncio
async def test_r2fc_s04_reads_are_bounded_and_user_account_is_user_id_only() -> None:
    backend = _backend()
    await _call(_repo(backend), "POST", P1, json=body("LINK", "", "USR-SYN-1"))
    assert backend.data_cells_requested(PTAB) == set(PERSONNEL_ACCOUNT_LINK_MASTER_COLUMNS)
    for not_read in ("technician_id", "department", "position", "branch_id", "note_th"):
        assert not_read not in backend.data_cells_requested(PTAB)
    assert backend.data_cells_requested(ATAB) == {"user_id"}  # never email / phone / role / MFA / status
    assert all(cells for tab, cells in backend.ranges if tab in (PTAB, ATAB))
    assert "technician_master" not in {tab for tab, _ in backend.ranges}


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "outcome"), [("reject", "rejected"), ("server_error", "unknown"),
                                                ("apply_then_timeout", "unknown")])
async def test_r2fc_s05_w1_failure_never_writes_the_cell(mode, outcome) -> None:
    backend = _backend()
    backend.fail["append"] = mode
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "USR-SYN-1"))
    assert _code(response) == (503, "PERSONNEL_ACCOUNT_LINK_HISTORY_WRITE_FAILED")
    assert response.json()["error"]["details"]["history_write_outcome"] == outcome
    assert [w["kind"] for w in backend.write_log] == ["append"]
    assert _rows(backend, PTAB)[0]["user_id"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["reject", "server_error"])
async def test_r2fc_s06_w2_failure_keeps_history_mismatch_then_reconcile(mode) -> None:
    backend = _backend()
    backend.fail["batchUpdate"] = mode
    repo = _repo(backend)
    response = await _call(repo, "POST", P1, json=body("LINK", "", "USR-SYN-1"))
    assert _code(response) == (503, "PERSONNEL_ACCOUNT_LINK_PROJECTION_WRITE_FAILED")
    assert [w["kind"] for w in backend.write_log] == ["append", "batchUpdate"]
    backend.fail["batchUpdate"] = None
    read = (await _call(repo, "GET", f"{P1}/history")).json()
    assert (read["current_user_id"], read["latest_history_user_id"], read["relationship_consistency"]) == (
        None, "USR-SYN-1", "MISMATCH")
    rid = _rows(backend, HTAB)[0]["request_id"]
    fixed = await _call(repo, "POST", f"{P1}/reconcile",
                        json={"expected_user_id": "", "related_request_id": rid, "reason_th": REASON})
    assert fixed.status_code == 200 and fixed.json()["relationship_consistency_after"] == "CONSISTENT"
    assert _rows(backend, PTAB)[0]["user_id"] == "USR-SYN-1"


@pytest.mark.asyncio
async def test_r2fc_s07_test_context_never_links_the_untagged_live_accounts() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs)
    for target in ("USR-SYN-1", "TEST-USER-1"):  # an id that merely looks like TEST is still unproven
        response = await _call(_repo(backend), "POST", f"{API}/personnel/P-T/account-links",
                               json=body("LINK", "", target), settings=_settings("TEST"))
        assert _code(response) == (422, "USER_ACCOUNT_SCOPE_UNPROVEN"), target
    assert backend.write_log == [] and backend.tabs == before


@pytest.mark.asyncio
async def test_r2fc_s08_missing_history_tab_fails_closed_and_is_never_created() -> None:
    backend = _backend(history=False)
    response = await _call(_repo(backend), "POST", P1, json=body("LINK", "", "USR-SYN-1"))
    assert _code(response) == (500, "PERSONNEL_ACCOUNT_LINK_HISTORY_SCHEMA_INVALID")
    assert backend.write_log == [] and HTAB not in backend.tabs


def test_r2fc_s09_history_tab_is_not_a_global_readiness_requirement() -> None:
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    core = GoogleSheetsRepository._CORE_SCHEMAS
    assert core and schemas.PERSONNEL_ACCOUNT_LINK_HISTORY_SHEET not in core
    assert schemas.PERSONNEL_ACCOUNT_LINK_MASTER_SHEET not in core
    assert {k for k, v in vars(schemas).items() if getattr(v, "tab_name", "") == "user_account"} == {
        "USER_ACCOUNT_READ_SHEET"}
