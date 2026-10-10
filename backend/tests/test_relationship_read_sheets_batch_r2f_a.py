"""R2 Batch R2f-a — relationship read foundation over Google Sheets, exercised
with the REAL installed gspread client on the 7B2/7H2 FAKE HTTP transport: an
emulation, not live Google Sheets. No credentials, network or live workbook.
Every row is SYNTHETIC and labelled; no production count is assumed.

Proves: REAL resolves against the untagged live-style technician_master /
user_account; TEST can never resolve against them (this mode supplies no
TEST-scoped references); bounded column validation fails closed; a failed
read is an error; and every R2f-a route performs ZERO writes.

Independent-review fix R1 (true bounded reads): `RangeBackend` emulates the
real Sheets range semantics the bounded reads use (`'tab'!1:1` and
`values:batchGet` with single-column ranges) and logs EVERY requested range,
including an unbounded whole-tab `worksheet.get()`. The privacy tests assert
the exact ranges requested and that sentinel cells in non-approved columns are
NEVER REQUESTED — not merely absent from the response.
"""
from __future__ import annotations

import copy
import re
from urllib.parse import unquote

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
# R2 Batch R2f-e (deliberate evolution): the fake live personnel_master is the TARGET
# header (driver_id added by the live schema preparation R2f-e integration requires).
from app.domain.personnel import PERSONNEL_MASTER_TARGET_COLUMNS as PERSONNEL_MASTER_COLUMNS
from tests.test_fleet_status_summary_sheets_batch7b2 import _FakeResponse, _repo
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_vehicle_text_preservation_sheets_batch7h2 import WritableBackend

API = "/api/v1"
BATCH = "SYN-R2FA-BATCH"
SYN = " (สังเคราะห์)"
TECH_HEADER = ["technician_id", "first_name", "last_name", "department", "position", "branch_id",
               "active_status", "source_file", "source_sheet", "source_row", "note_th"]
ACCOUNT_HEADER = ["user_id", "display_name_th", "email", "phone", "role_code", "mfa_enabled", "active_status",
                  "note_th"]
OTHER_TABS = {  # present only to prove they are never requested or written
    "driver_master": [["driver_id", "driver_name_th", "active_status"], ["DRV-SYN-1", "ผู้ขับ" + SYN, "ACTIVE"]],
    "asset_responsibility_history": [["assignment_id", "personnel_id", "assignment_status"],
                                     ["ARH-SYN-1", "P-R", "ACTIVE"]],
    "repair_assignment": [["repair_assignment_id", "repair_id", "user_id"], ["RASG-SYN-1", "RPR-SYN-1", "u-1"]],
}


def _tech_row(tid: str, status: str = "ACTIVE") -> list[str]:
    values = {"technician_id": tid, "first_name": "ช่าง" + SYN, "last_name": "ทดสอบ" + SYN,
              "department": "SYN-DEPT-LEAK", "position": "SYN-POS-LEAK", "branch_id": "SYN-BRANCH-LEAK",
              "active_status": status, "source_file": "SYN-FILE-LEAK", "source_sheet": "SYN-SHEET-LEAK",
              "source_row": "7", "note_th": "SYN-NOTE-LEAK"}
    return [values[h] for h in TECH_HEADER]


def _account_row(uid: str) -> list[str]:
    values = {"user_id": uid, "display_name_th": "ผู้ใช้" + SYN, "email": "syn-leak@example.invalid",
              "phone": "000-LEAK", "role_code": "SYN-ROLE-LEAK", "mfa_enabled": "FALSE",
              "active_status": "INACTIVE", "note_th": "SYN-NOTE-LEAK"}
    return [values[h] for h in ACCOUNT_HEADER]


PEOPLE = [
    person("P-R", technician_id="TEC-SYN-1", user_id="USR-SYN-1"),
    person("P-U"),
    person("P-T", technician_id="TEC-SYN-1", user_id="USR-SYN-1", test=True, batch=BATCH),
    person("P-N", technician_id="TEC-SYN-NONE", user_id="USR-SYN-NONE", test=True, batch=BATCH),
]


def _col_index(letters: str) -> int:
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - 64)
    return index - 1


class RangeBackend(WritableBackend):
    """WritableBackend + real range semantics for the bounded reads. Every
    values request is logged in `ranges` as (tab, cells); an unbounded
    whole-tab read is logged with cells "" and served by the base fake (so a
    regression shows up in the range assertions, not as a crash)."""

    _BATCH_RE = re.compile(r"/spreadsheets/([^/]+)/values:batchGet$")
    _COLUMN_RE = re.compile(r"([A-Z]+)2:([A-Z]+)")

    def __init__(self, tabs):
        super().__init__(tabs)
        self.ranges: list[tuple[str, str]] = []

    @staticmethod
    def _split(rng: str) -> tuple[str, str]:
        tab, _, cells = unquote(rng).partition("!")
        return tab.strip("'").replace("''", "'"), cells

    def _guard(self, tab: str):
        self.requests.append(("get", "values", tab))
        if self.fail_values_get:
            return _FakeResponse({"error": {"code": 500, "message": "backend error", "status": "INTERNAL"}}, 500)
        if tab not in self.tabs:
            return _FakeResponse({"error": {"code": 400, "message": "Unable to parse range",
                                            "status": "INVALID_ARGUMENT"}}, 400)
        return None

    def _column(self, tab: str, cells: str) -> dict:
        match = self._COLUMN_RE.fullmatch(cells)
        assert match and match.group(1) == match.group(2), f"not a single-column range: {cells}"
        index = _col_index(match.group(1))
        values = [str(row[index]) if index < len(row) else "" for row in (self.tabs[tab] or [])[1:]]
        while values and values[-1] == "":
            values.pop()
        body: dict = {"range": f"'{tab}'!{cells}", "majorDimension": "COLUMNS"}
        if values:
            body["values"] = [values]
        return body

    def request(self, method, url, json=None, params=None, data=None, files=None, headers=None,  # noqa: A002
                timeout=None):
        if method.lower() == "get" and self._BATCH_RE.search(url):
            requested = params["ranges"] if isinstance(params["ranges"], list) else [params["ranges"]]
            assert params.get("majorDimension") == "COLUMNS"
            parsed = [self._split(r) for r in requested]
            for tab, cells in parsed:
                self.ranges.append((tab, cells))
            for tab in {t for t, _ in parsed}:
                failure = self._guard(tab)
                if failure is not None:
                    return failure
            return _FakeResponse({"valueRanges": [self._column(t, c) for t, c in parsed]})
        values = self._VALUES_RE.search(url) if method.lower() == "get" else None
        if values:
            tab, cells = self._split(values.group(2))
            self.ranges.append((tab, cells))
            if cells == "1:1":
                failure = self._guard(tab)
                if failure is not None:
                    return failure
                header = list((self.tabs[tab] or [[]])[0]) if self.tabs[tab] else []
                while header and header[-1] == "":
                    header.pop()
                body: dict = {"range": f"'{tab}'!1:1", "majorDimension": "ROWS"}
                if header:
                    body["values"] = [header]
                return _FakeResponse(body)
        return super().request(method, url, json=json, params=params, data=data, files=files, headers=headers,
                               timeout=timeout)

    def data_cells_requested(self, tab: str) -> set[str]:
        """The header names whose DATA cells were requested for `tab`."""
        header = (self.tabs[tab] or [[]])[0]
        names: set[str] = set()
        for t, cells in self.ranges:
            if t != tab or cells == "1:1":
                continue
            match = self._COLUMN_RE.fullmatch(cells)
            if not match:
                return {"<UNBOUNDED>"}
            names.add(header[_col_index(match.group(1))])
        return names


def _backend(people=PEOPLE, *, tech_header=TECH_HEADER, account_header=ACCOUNT_HEADER, tech=True,
             account=True) -> RangeBackend:
    header = list(PERSONNEL_MASTER_COLUMNS)
    tabs = {"personnel_master": [header, *([r.get(h, "") for h in header] for r in copy.deepcopy(people))],
            **copy.deepcopy(OTHER_TABS)}
    if tech:
        tabs["technician_master"] = [list(tech_header), *([v for h, v in zip(TECH_HEADER, _tech_row(t))
                                                            if h in tech_header] for t in ("TEC-SYN-1", "TEC-SYN-2"))]
    if account:
        tabs["user_account"] = [list(account_header), *([v for h, v in zip(ACCOUNT_HEADER, _account_row(u))
                                                          if h in account_header] for u in ("USR-SYN-1",))]
    return RangeBackend(tabs)


def _settings(context: str | None = "REAL", batch: str = "") -> Settings:
    values: dict = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake-sheet-id",
                    "google_application_credentials": "fake.json", "registry_test_batch_id": batch}
    if context:
        values["registry_data_context"] = context
    return Settings(**values)


async def _get(repo, path: str, settings: Settings | None = None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    chosen = settings or _settings()
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


# ---------------------------------------------------------------------------
# REAL resolves against the untagged live-style masters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_s01_real_resolves_against_the_live_style_masters() -> None:
    backend = _backend()
    repo = _repo(backend)
    response = await _get(repo, f"{API}/personnel/P-R/relationships")
    assert response.status_code == 200
    body = response.json()
    assert body["technician"]["resolution"] == "RESOLVED"
    assert body["technician"]["technician"]["technician_id"] == "TEC-SYN-1"
    assert body["account"]["resolution"] == "RESOLVED"  # R2f-c: ADMIN also sees user_id
    assert "LEAK" not in response.text  # bounded: no other technician / account column is exposed
    unset = (await _get(repo, f"{API}/personnel/P-U/relationships")).json()
    assert (unset["technician"]["resolution"], unset["account"]["resolution"]) == ("UNSET", "UNSET")
    reverse = (await _get(repo, f"{API}/technicians/TEC-SYN-1/personnel")).json()
    assert (reverse["resolution"], reverse["personnel_id"]) == ("RESOLVED", "P-R")  # the TEST holder is out of scope
    listed = (await _get(repo, f"{API}/technicians")).json()
    assert [t["technician_id"] for t in listed["items"]] == ["TEC-SYN-1", "TEC-SYN-2"]
    assert "LEAK" not in str(listed)


# ---------------------------------------------------------------------------
# TEST never resolves against the untagged operational masters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_s02_test_context_cannot_resolve_operational_references() -> None:
    repo = _repo(_backend())
    settings = _settings("TEST", BATCH)
    real_target = (await _get(repo, f"{API}/personnel/P-T/relationships", settings)).json()
    assert (real_target["technician"]["resolution"], real_target["account"]["resolution"]) == (
        "SCOPE_UNPROVEN", "SCOPE_UNPROVEN")
    assert real_target["technician"]["technician"] is None
    # an id found nowhere is still unproven: this mode cannot supply TEST scope at all
    nowhere = (await _get(repo, f"{API}/personnel/P-N/relationships", settings)).json()
    assert (nowhere["technician"]["resolution"], nowhere["account"]["resolution"]) == (
        "SCOPE_UNPROVEN", "SCOPE_UNPROVEN")
    # a REAL technician is never a target in the TEST context
    assert _code(await _get(repo, f"{API}/technicians/TEC-SYN-1/personnel", settings)) == (404, "TECHNICIAN_NOT_FOUND")
    # and a REAL personnel is not in TEST scope
    assert _code(await _get(repo, f"{API}/personnel/P-R/relationships", settings)) == (404, "PERSONNEL_NOT_FOUND")


@pytest.mark.asyncio
async def test_r2fa_s03_unconfigured_context_is_503_with_zero_reads() -> None:
    backend = _backend()
    response = await _get(_repo(backend), f"{API}/personnel/P-R/relationships", _settings(None))
    assert _code(response) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert backend.values_reads() == 0


# ---------------------------------------------------------------------------
# Bounded headers fail closed; failed reads are errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["technician_id", "first_name", "last_name", "active_status"])
async def test_r2fa_s04_technician_header_defect_fails_closed(missing) -> None:
    repo = _repo(_backend(tech_header=[h for h in TECH_HEADER if h != missing]))
    for path in ("technicians", "technicians/TEC-SYN-1", "personnel/P-R/relationships"):
        assert _code(await _get(repo, f"{API}/{path}")) == (500, "TECHNICIAN_MASTER_SCHEMA_INVALID"), path


@pytest.mark.asyncio
async def test_r2fa_s04_only_the_bounded_columns_are_required() -> None:
    bounded = ["technician_id", "first_name", "last_name", "active_status"]
    repo = _repo(_backend(tech_header=bounded, account_header=["user_id"]))
    response = await _get(repo, f"{API}/personnel/P-R/relationships")
    assert response.status_code == 200 and response.json()["account"]["resolution"] == "RESOLVED"


@pytest.mark.asyncio
async def test_r2fa_s05_account_header_defect_and_missing_tabs_fail_closed() -> None:
    no_id = _repo(_backend(account_header=[h for h in ACCOUNT_HEADER if h != "user_id"]))
    assert _code(await _get(no_id, f"{API}/personnel/P-R/relationships")) == (500, "USER_ACCOUNT_SCHEMA_INVALID")
    no_account_tab = _repo(_backend(account=False))
    assert _code(await _get(no_account_tab, f"{API}/personnel/P-R/relationships")) == (
        500, "USER_ACCOUNT_SCHEMA_INVALID")
    no_tech_tab = _repo(_backend(tech=False))
    assert _code(await _get(no_tech_tab, f"{API}/technicians")) == (500, "TECHNICIAN_MASTER_SCHEMA_INVALID")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["technician_id", "user_id", "is_test_data", "test_batch_id"])
async def test_r2fa_s06_personnel_relationship_header_defect_fails_closed(missing) -> None:
    people_header = [h for h in PERSONNEL_MASTER_COLUMNS if h != missing]
    backend = _backend()
    backend.tabs["personnel_master"] = [people_header, *([r.get(h, "") for h in people_header] for r in PEOPLE)]
    assert _code(await _get(_repo(backend), f"{API}/personnel/P-R/relationships")) == (
        500, "PERSONNEL_MASTER_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_r2fa_s07_transport_failure_is_read_failed_never_empty() -> None:
    backend = _backend()
    backend.fail_values_get = True
    for path, code in (("technicians", "TECHNICIAN_MASTER_READ_FAILED"),
                       ("personnel/P-R/relationships", "PERSONNEL_MASTER_READ_FAILED")):
        response = await _get(_repo(backend), f"{API}/{path}")
        assert _code(response) == (503, code), path
        assert "items" not in response.json() and "resolution" not in response.text


# ---------------------------------------------------------------------------
# ZERO writes; no other tab touched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fa_s08_every_route_performs_zero_writes_and_touches_only_its_tabs() -> None:
    backend = _backend()
    before = copy.deepcopy(backend.tabs)
    repo = _repo(backend)
    for settings in (_settings("REAL"), _settings("TEST", BATCH)):
        for path in ("technicians", "technicians/TEC-SYN-1", "personnel/P-R/relationships",
                     "personnel/P-T/relationships", "technicians/TEC-SYN-1/personnel"):
            await _get(repo, f"{API}/{path}", settings)
    assert backend.write_log == []
    assert backend.tabs == before
    touched = {tab for _, kind, tab in backend.requests if kind == "values"}
    # R2 Batch R2f-e (deliberate evolution): driver_master is now READ (driver_id only, see t04).
    assert touched == {"personnel_master", "technician_master", "user_account", "driver_master"}
    assert not any(method != "get" for method, _, _ in backend.requests)


# ---------------------------------------------------------------------------
# Independent-review fix R1 — TRUE bounded reads, proven at the transport
# ---------------------------------------------------------------------------

TECH_BOUNDED = {"technician_id", "first_name", "last_name", "active_status"}
PERSONNEL_BOUNDED = {"personnel_id", "first_name", "last_name", "active_status", "technician_id", "user_id",
                     "driver_id",  # R2 Batch R2f-e (deliberate evolution): the driver link cell
                     "is_test_data", "test_batch_id"}
ALL_ROUTES = ("technicians", "technicians/TEC-SYN-1", "personnel/P-R/relationships", "personnel/P-T/relationships",
              "technicians/TEC-SYN-1/personnel")


def _sentinel_people() -> list[dict[str, str]]:
    rows = copy.deepcopy(PEOPLE)
    for row in rows:
        row.update(department="SENTINEL-DEPT", position="SENTINEL-POSITION", branch_id="SENTINEL-BRANCH",
                   note_th="SENTINEL-NOTE")
    return rows


@pytest.mark.asyncio
async def test_r2fa_t01_technician_data_read_is_physically_column_limited() -> None:
    backend = _backend()
    response = await _get(_repo(backend), f"{API}/technicians")
    assert response.status_code == 200
    # header row (metadata) + exactly the four approved single-column ranges; non-adjacent
    # active_status (G) is requested alone, never widened across D..F
    assert [r for r in backend.ranges if r[0] == "technician_master"] == [
        ("technician_master", "1:1"), ("technician_master", "A2:A"), ("technician_master", "B2:B"),
        ("technician_master", "C2:C"), ("technician_master", "G2:G")]
    assert backend.data_cells_requested("technician_master") == TECH_BOUNDED
    for not_read in ("department", "position", "branch_id", "source_file", "source_sheet", "source_row", "note_th"):
        assert not_read not in backend.data_cells_requested("technician_master")


@pytest.mark.asyncio
async def test_r2fa_t02_user_account_data_read_is_user_id_only() -> None:
    backend = _backend()
    assert (await _get(_repo(backend), f"{API}/personnel/P-R/relationships")).status_code == 200
    assert [r for r in backend.ranges if r[0] == "user_account"] == [("user_account", "1:1"), ("user_account", "A2:A")]
    assert backend.data_cells_requested("user_account") == {"user_id"}


@pytest.mark.asyncio
async def test_r2fa_t03_personnel_relationship_data_read_is_the_frozen_columns_only() -> None:
    backend = _backend(_sentinel_people())
    assert (await _get(_repo(backend), f"{API}/personnel/P-R/relationships")).status_code == 200
    assert backend.data_cells_requested("personnel_master") == PERSONNEL_BOUNDED
    for not_read in ("department", "position", "branch_id", "note_th"):
        assert not_read not in backend.data_cells_requested("personnel_master")
    header = backend.tabs["personnel_master"][0]
    requested = [c for t, c in backend.ranges if t == "personnel_master" and c != "1:1"]
    assert len(requested) == len(PERSONNEL_BOUNDED)
    for name in ("department", "position", "branch_id", "note_th"):
        letter = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[header.index(name)]
        assert f"{letter}2:{letter}" not in requested


@pytest.mark.asyncio
async def test_r2fa_t04_no_unbounded_whole_tab_fetch_on_any_route_or_context() -> None:
    backend = _backend(_sentinel_people())
    repo = _repo(backend)
    for settings in (_settings("REAL"), _settings("TEST", BATCH)):
        for path in ALL_ROUTES:
            await _get(repo, f"{API}/{path}", settings)
    assert all(cells for _, cells in backend.ranges), "an unbounded worksheet.get() was issued"
    # R2 Batch R2f-e (deliberate evolution): driver_master is read, bounded to driver_id.
    assert {t for t, _ in backend.ranges} == {"personnel_master", "technician_master", "user_account", "driver_master"}
    assert backend.data_cells_requested("technician_master") == TECH_BOUNDED
    assert backend.data_cells_requested("user_account") == {"user_id"}
    assert backend.data_cells_requested("driver_master") == {"driver_id"}
    assert backend.data_cells_requested("personnel_master") == PERSONNEL_BOUNDED
    assert backend.write_log == []


@pytest.mark.asyncio
async def test_r2fa_t05_columns_resolve_by_header_name_not_position() -> None:
    reordered_tech = ["note_th", "source_row", "active_status", "branch_id", "last_name", "position",
                      "technician_id", "first_name", "department", "source_file", "source_sheet"]
    reordered_account = ["email", "phone", "display_name_th", "role_code", "user_id", "mfa_enabled", "note_th",
                         "active_status"]
    backend = _backend(tech_header=TECH_HEADER, account_header=ACCOUNT_HEADER)
    # rebuild the two tabs in the new column order (same synthetic values)
    for tab, header in (("technician_master", reordered_tech), ("user_account", reordered_account)):
        old = backend.tabs[tab]
        rows = [dict(zip(old[0], r)) for r in old[1:]]
        backend.tabs[tab] = [header, *([row[h] for h in header] for row in rows)]
    response = await _get(_repo(backend), f"{API}/personnel/P-R/relationships")
    body = response.json()
    assert body["technician"]["technician"] == {"technician_id": "TEC-SYN-1", "first_name": "ช่าง" + SYN,
                                                "last_name": "ทดสอบ" + SYN, "active_status": "ACTIVE"}
    assert body["account"]["resolution"] == "RESOLVED"  # R2f-c: ADMIN also sees user_id
    assert backend.data_cells_requested("technician_master") == TECH_BOUNDED
    assert backend.data_cells_requested("user_account") == {"user_id"}
    assert ("user_account", "E2:E") in backend.ranges


@pytest.mark.asyncio
async def test_r2fa_t06_opaque_identifiers_stay_exact_text() -> None:
    people = [person("00123", technician_id="0042", user_id="1e5")]
    backend = _backend(people)
    backend.tabs["technician_master"].append(["0042", "ศูนย์" + SYN, "สี่สอง" + SYN, "", "", "", "ACTIVE", "", "", "", ""])
    backend.tabs["user_account"].append(["1e5", "", "", "", "", "", "", ""])
    body = (await _get(_repo(backend), f"{API}/personnel/00123/relationships")).json()
    assert body["personnel_id"] == "00123"
    assert (body["technician"]["resolution"], body["technician"]["technician_id"]) == ("RESOLVED", "0042")
    assert body["account"]["resolution"] == "RESOLVED"  # R2f-c: ADMIN also sees user_id
    detail = (await _get(_repo(backend), f"{API}/technicians/0042")).json()
    assert detail["technician_id"] == "0042"
    assert (await _get(_repo(backend), f"{API}/technicians/42")).status_code == 404


@pytest.mark.asyncio
async def test_r2fa_t07_structural_defects_fail_closed_before_any_data_read() -> None:
    cases = {
        "duplicate declared header": ["technician_id", "first_name", "last_name", "active_status", "technician_id"],
        "duplicate other header": [*TECH_HEADER, "note_th"],
        "blank header row": ["", "", ""],
    }
    for label, header in cases.items():
        backend = _backend()
        backend.tabs["technician_master"] = [header, ["TEC-SYN-1"]]
        response = await _get(_repo(backend), f"{API}/technicians")
        assert _code(response) == (500, "TECHNICIAN_MASTER_SCHEMA_INVALID"), label
        assert backend.data_cells_requested("technician_master") == set(), label  # header only, no data
    empty = _backend()
    empty.tabs["technician_master"] = []
    assert _code(await _get(_repo(empty), f"{API}/technicians")) == (500, "TECHNICIAN_MASTER_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_r2fa_t08_column_read_failure_is_read_failed() -> None:
    class FailingColumns(RangeBackend):
        def request(self, method, url, **kwargs):
            if self._BATCH_RE.search(url):
                self.ranges.append(("batch", "failed"))
                return _FakeResponse({"error": {"code": 500, "message": "backend error", "status": "INTERNAL"}}, 500)
            return super().request(method, url, **kwargs)

    source = _backend()
    backend = FailingColumns(source.tabs)
    for path, code in (("technicians", "TECHNICIAN_MASTER_READ_FAILED"),
                       ("personnel/P-R/relationships", "PERSONNEL_MASTER_READ_FAILED")):
        response = await _get(_repo(backend), f"{API}/{path}")
        assert _code(response) == (503, code), path
        assert "items" not in response.json() and "resolution" not in response.text
