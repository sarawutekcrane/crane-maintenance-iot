"""Phase 7 Batch 7H2 — vehicle text preservation over Google Sheets.

Real installed gspread over the existing 7B2 fake HTTP transport
(FakeSheetsBackend, imported unchanged), extended IN THIS FILE so that the
two write requests the new paths use — values:batchUpdate and
values:append — are ACCEPTED, RECORDED and applied to the in-memory sheet.

STORAGE EMULATION — NOT GOOGLE SHEETS. Each written cell is interpreted
with a simplified, documented model of USER_ENTERED: a leading apostrophe
forces text (the apostrophe is not stored); a plain number is stored as a
number and read back in general format ("0012" -> "12"); anything else is
stored as sent. No locale, dates, formulas or formats are emulated. These
tests prove the PAYLOADS the application sends and the application logic
around them; what live Sheets stores is not validated here.

FAILURE SIMULATION — the fake can REJECT a write (HTTP 400, not applied),
APPLY it and then raise a timeout (lost response), or answer HTTP 503 (not
applied). Real Sheets semantics for these cases are not validated here.
All fixtures are synthetic.
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from urllib.parse import unquote

import pytest
import requests
from httpx import ASGITransport, AsyncClient

from app.domain.common import OperationalStatus, PageParams
from app.domain.vehicle_service import VehicleService
from app.errors import ApiError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from tests.test_fleet_status_summary_sheets_batch7b2 import (
    HEADER,
    STATUSES,
    TS,
    VEHICLE_TAB,
    FakeSheetsBackend,
    _FakeResponse,
    _repo,
    _row,
)

MODEL_HEADER = list(schemas.VEHICLE_MODEL_SHEET.required_headers)
PLAN_HEADER = list(schemas.PM_PLAN_SHEET.required_headers)
COMPONENT_HEADER = list(schemas.VEHICLE_COMPONENT_SHEET.required_headers)
HISTORY_HEADER = list(schemas.VEHICLE_STATUS_HISTORY_SHEET.required_headers)
HISTORY_TAB = schemas.VEHICLE_STATUS_HISTORY_SHEET.tab_name

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def _emulate_user_entered(value: str) -> str:
    """EMULATION (see module docstring): the FORMATTED value a later read
    would return for a cell written with this USER_ENTERED value."""
    if value.startswith("'"):
        return value[1:]
    if _NUMBER.match(value):
        number = float(value)
        return str(int(number)) if number.is_integer() else repr(number)
    return value


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


class WritableBackend(FakeSheetsBackend):
    """7B2 fake + recorded, emulated writes and failure injection.
    `fail[kind]` for kind in {"batchUpdate", "append"}: None (succeed),
    "reject" (HTTP 400, not applied), "apply_then_timeout" (applied, then
    the response is lost) or "server_error" (HTTP 503, not applied)."""

    def __init__(self, tabs):
        super().__init__(tabs)
        self.write_log: list[dict] = []
        self.fail: dict[str, str | None] = {"batchUpdate": None, "append": None}

    def _apply(self, tab: str, row: int, col: int, raw: str) -> None:
        rows = self.tabs[tab]
        while len(rows) < row:
            rows.append([])
        target = rows[row - 1]
        while len(target) < col:
            target.append("")
        target[col - 1] = _emulate_user_entered(raw)

    def _finish(self, kind: str, body: dict):
        mode = self.fail[kind]
        if mode == "apply_then_timeout":
            raise requests.exceptions.ReadTimeout("simulated lost response")
        return _FakeResponse(body)

    def request(self, method, url, json=None, params=None, data=None, files=None, headers=None, timeout=None):  # noqa: A002, ARG002
        m = method.lower()
        if m == "get":
            response = super().request(method, url, json=json, params=params)
            body = response._body
            if isinstance(body, dict):
                for sheet in body.get("sheets", []):
                    sheet["properties"].setdefault("gridProperties", {"rowCount": 1000, "columnCount": 26})
            return response
        if url.endswith("/values:batchUpdate"):
            kind = "batchUpdate"
            self.write_log.append({"kind": kind, "valueInputOption": (json or {}).get("valueInputOption"),
                                   "data": copy.deepcopy((json or {}).get("data", []))})
            self.requests.append(("post", kind, None))
            if self.fail[kind] in ("reject", "server_error"):
                code = 400 if self.fail[kind] == "reject" else 503
                return _FakeResponse({"error": {"code": code, "message": "simulated", "status": "X"}}, code)
            for item in (json or {}).get("data", []):
                tab, _, cell = unquote(item["range"]).partition("!")
                tab = tab.strip("'")
                mm = re.fullmatch(r"([A-Z]+)(\d+)", cell)
                self._apply(tab, int(mm.group(2)), _col_index(mm.group(1)), str(item["values"][0][0]))
            return self._finish(kind, {"spreadsheetId": "fake", "totalUpdatedCells": len(json["data"])})
        values = self._VALUES_RE.search(url)
        if values and unquote(values.group(2)).endswith(":append"):
            kind = "append"
            rng = unquote(values.group(2))[: -len(":append")]
            tab = rng.partition("!")[0].strip("'")
            row_values = (json or {}).get("values", [[]])[0]
            self.write_log.append({"kind": kind, "tab": tab, "range": rng,
                                   "valueInputOption": (params or {}).get("valueInputOption"),
                                   "insertDataOption": (params or {}).get("insertDataOption"),
                                   "values": list(row_values)})
            self.requests.append(("post", kind, tab))
            if self.fail[kind] in ("reject", "server_error"):
                code = 400 if self.fail[kind] == "reject" else 503
                return _FakeResponse({"error": {"code": code, "message": "simulated", "status": "X"}}, code)
            new_row = len(self.tabs[tab]) + 1
            for c, raw in enumerate(row_values, start=1):
                self._apply(tab, new_row, c, str(raw))
            return self._finish(kind, {"spreadsheetId": "fake", "updates": {"updatedRange": rng}})
        self.writes.append((m, url))
        return _FakeResponse({"error": {"code": 400, "message": "unsupported", "status": "X"}}, 400)

    def mutation_count(self) -> int:
        return len(self.write_log) + len(self.writes)


def _tabs(vehicle_rows, *, vehicle_header=None, models=None, plans=None, components=None, history=None, history_header=None):
    return {
        VEHICLE_TAB: [list(vehicle_header or HEADER), *copy.deepcopy(vehicle_rows)],
        "model_master": [MODEL_HEADER, *(models or [["MDL-1", "MC-1", "Model One", "", "", "CARRIER_ENGINE", TS, TS, ""]])],
        "maintenance_plan": [PLAN_HEADER, *(plans or [])],
        "vehicle_component": [COMPONENT_HEADER, *(components or [])],
        HISTORY_TAB: [list(history_header or HISTORY_HEADER), *(history or [])],
    }


def _setup(vehicle_rows, **kw) -> tuple[WritableBackend, GoogleSheetsRepository, VehicleService]:
    backend = WritableBackend(_tabs(vehicle_rows, **kw))
    repo = _repo(backend)
    return backend, repo, VehicleService(repo)


async def _api_error(coro) -> ApiError:
    with pytest.raises(ApiError) as info:
        await coro
    return info.value


def _reorder(rows: list[list[str]], new_header: list[str]) -> list[list[str]]:
    idx = [rows[0].index(h) for h in new_header]
    return [[r[i] if i < len(r) else "" for i in idx] for r in rows]


async def _http(repo, method: str, path: str, **kwargs):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


TEXT_VALUES = ["0012", "0005", "000123", "1.50", "1e3", "1,234", "-5", "TRUE", "=1+1", "'quoted", " 0012 ", "12/03"]


# ---------------------------------------------------------------------------
# T01 / T02a-d — read-side text preservation and classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t01_validated_read_keeps_text_only_for_protected_columns() -> None:
    backend, repo, _ = _setup([["0012", "0012", "0005", "000123", "READY", TS, TS]])
    read = await repo._client.read_header_and_records(schemas.VEHICLE_SHEET)
    assert read.records[0]["machine_no"] == 12  # gspread numericises by default
    summary = await repo.read_vehicle_master_for_summary()
    v = summary.vehicles[0]
    assert (v.vehicle_id, v.machine_no, v.model_id, v.serial_number) == ("0012", "0012", "0005", "000123")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", TEXT_VALUES)
@pytest.mark.parametrize("field", ["vehicle_id", "machine_no", "model_id", "serial_number"])
async def test_t02a_identifier_and_text_fields_keep_exact_text(field: str, value: str) -> None:
    row = {"vehicle_id": "VEH-1", "machine_no": "TC-1", "model_id": "MDL-1", "serial_number": "",
           "operational_status": "WORKING", "created_at": TS, "updated_at": TS}
    row[field] = value
    backend, repo, service = _setup([[row[h] for h in HEADER]])
    listed = await service.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams())
    assert getattr(listed.items[0], field) == value
    assert (await service.get_fleet_status_summary()).vehicle_total == 1
    detail = await service.get_vehicle_detail(row["vehicle_id"])
    assert getattr(detail.vehicle, field) == value
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_t02b_status_text_is_raw_but_only_exact_codes_are_accepted() -> None:
    _, repo, service = _setup([_row("VEH-1", status) for status in STATUSES[:1]] + [_row("VEH-2", "1")])
    err = await _api_error(service.list_vehicles(None, None, None, PageParams()))
    assert err.details == {"issue_counts": {"UNRECOGNIZED_STATUS": 1}}
    for code in STATUSES:
        _, _, ok_service = _setup([_row("VEH-1", code)])
        assert (await ok_service.get_vehicle_detail("VEH-1")).vehicle.operational_status.value == code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "issue"),
    [("", "BLANK_STATUS"), ("   ", "BLANK_STATUS"), (" READY", "UNRECOGNIZED_STATUS"),
     ("ready", "UNRECOGNIZED_STATUS"), ("UNKNOWN", "UNRECOGNIZED_STATUS")],
)
async def test_t02c_invalid_status_classification_on_list_detail_and_both_writes(raw: str, issue: str) -> None:
    backend, _, service = _setup([_row("VEH-1", raw)])
    err = await _api_error(service.list_vehicles(None, None, None, PageParams()))
    assert err.details == {"issue_counts": {issue: 1}}
    for call in (service.get_vehicle_detail("VEH-1"), service.update_machine_no("VEH-1", "X"),
                 service.change_status("VEH-1", OperationalStatus.WORKING, "u", None)):
        err = await _api_error(call)
        assert (err.code, err.status_code, err.details) == ("VEHICLE_MASTER_DATA_INVALID", 500, {"issue_counts": {issue: 1}})
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_t02d_dates_are_not_protected() -> None:
    backend, _, service = _setup([_row("VEH-1", created="2026")])
    err = await _api_error(service.list_vehicles(None, None, None, PageParams()))
    assert err.details == {"issue_counts": {"UNMAPPABLE_ROW": 1}}
    err = await _api_error(service.update_machine_no("VEH-1", "X"))
    assert err.details == {"issue_counts": {"UNMAPPABLE_ROW": 1}}
    assert backend.mutation_count() == 0
    _, _, fallback = _setup([_row("VEH-2", created="not-a-date")])
    assert (await fallback.get_vehicle_detail("VEH-2")).vehicle.created_at.year == 1970


# ---------------------------------------------------------------------------
# T03 — list/dashboard parity, error-detail boundaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t03_parity_and_disclosure_with_numeric_looking_ids() -> None:
    rows = [_row(f"{i:04d}", STATUSES[i % 5], machine=f"{i:03d}", model="0005") for i in range(1, 26)]
    _, _, service = _setup(rows)
    summary = await service.get_fleet_status_summary()
    assert summary.vehicle_total == 25 == (await service.list_vehicles(None, None, None, PageParams(page_size=1))).total_items
    for status in OperationalStatus:
        page = await service.list_vehicles(None, status, None, PageParams(page_size=1))
        assert page.total_items == summary.status_counts[status.value]
    filtered = await service.list_vehicles("0007", None, "0005", PageParams())
    assert [v.vehicle_id for v in filtered.items] == ["0007"]

    _, _, bad = _setup([_row("0012", ""), _row("0013")])
    list_err = await _api_error(bad.list_vehicles(None, None, None, PageParams()))
    dash_err = await _api_error(bad.get_fleet_status_summary())
    assert list_err.details == {"issue_counts": {"BLANK_STATUS": 1}}
    assert dash_err.details == {"issue_counts": {"BLANK_STATUS": 1}, "sample_vehicle_ids": ["0012"]}


# ---------------------------------------------------------------------------
# T04 / T08 — identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t04_detail_resolves_text_ids_models_components_and_history() -> None:
    backend, _, service = _setup(
        [_row("0012", machine="0012", model="0005")],
        models=[["0005", "0099", "Model Five", "", "", "CARRIER_ENGINE", TS, TS, ""]],
        components=[["CMP-1", "0012", "CARRIER_ENGINE", "engine"], ["CMP-2", "12", "PTO", "pto"]],
        history=[["STH-0001", "0012", "READY", TS, "u", ""]],
    )
    detail = await service.get_vehicle_detail("0012")
    assert detail.model is not None and (detail.model.model_id, detail.model.model_code) == ("0005", "0099")
    assert [c.component_id for c in detail.components] == ["CMP-1"]
    assert [e.history_id for e in await service.list_status_history("0012")] == ["STH-0001"]
    assert [c.component_id for c in await service.list_components("0012")] == ["CMP-1"]
    assert (await _api_error(service.get_vehicle_detail("12"))).code == "VEHICLE_NOT_FOUND"
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_t08_t19_duplicate_ids_are_409_everywhere_with_zero_writes() -> None:
    backend, _, service = _setup([_row("VEH-D"), _row("VEH-D", "WORKING"), _row("VEH-2")])
    calls = [service.get_vehicle_detail("VEH-D"), service.list_components("VEH-D"),
             service.list_status_history("VEH-D"), service.update_machine_no("VEH-D", "X"),
             service.change_status("VEH-D", OperationalStatus.WORKING, "u", None)]
    for call in calls:
        err = await _api_error(call)
        assert (err.code, err.status_code, err.details) == ("VEHICLE_ID_AMBIGUOUS", 409, {"match_count": 2})
        assert "VEH-2" not in err.message
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_t08_blank_and_whitespace_ids_are_not_found_without_reading() -> None:
    backend, _, service = _setup([_row(" "), _row("VEH-1")])
    for vid in ("", " ", "\t"):
        backend.requests.clear()
        for call in (service.get_vehicle_detail(vid), service.update_machine_no(vid, "X"),
                     service.change_status(vid, OperationalStatus.WORKING, "u", None)):
            assert (await _api_error(call)).code == "VEHICLE_NOT_FOUND"
        assert backend.requests == []
    assert backend.mutation_count() == 0
    # Exact equality, no normalization: " VEH-1" is a different id.
    assert (await _api_error(service.get_vehicle_detail(" VEH-1"))).code == "VEHICLE_NOT_FOUND"


# ---------------------------------------------------------------------------
# T05 / T10 — warm header cache + live column reorder on every new path
# ---------------------------------------------------------------------------

VEHICLE_REORDER = ["created_at", "updated_at", "operational_status", "serial_number", "model_id", "machine_no", "vehicle_id"]


@pytest.mark.asyncio
async def test_t05_new_read_paths_survive_warm_cache_and_reorder() -> None:
    backend, repo, service = _setup(
        [_row("0012", machine="0012", model="0005", serial="000777")],
        models=[["0005", "0099", "Model Five", "", "", "CARRIER_ENGINE", TS, TS, "01"]],
        plans=[["PMP-0001", "01", "VEHICLE", "Plan 01", "", TS, TS]],
        components=[["CMP-1", "0012", "CARRIER_ENGINE", "engine"]],
        history=[["STH-0001", "0012", "READY", TS, "u", ""]],
    )
    # Warm the client's legacy header cache on every tab (legacy reads).
    for schema in (schemas.VEHICLE_SHEET, schemas.VEHICLE_MODEL_SHEET, schemas.PM_PLAN_SHEET,
                   schemas.VEHICLE_COMPONENT_SHEET, schemas.VEHICLE_STATUS_HISTORY_SHEET):
        await repo._client.read_rows(schema)
    t = backend.tabs
    t[VEHICLE_TAB] = _reorder(t[VEHICLE_TAB], VEHICLE_REORDER)
    t["model_master"] = _reorder(t["model_master"], list(reversed(MODEL_HEADER)))
    t["maintenance_plan"] = _reorder(t["maintenance_plan"], list(reversed(PLAN_HEADER)))
    t["vehicle_component"] = _reorder(t["vehicle_component"], list(reversed(COMPONENT_HEADER)))
    t[HISTORY_TAB] = _reorder(t[HISTORY_TAB], list(reversed(HISTORY_HEADER)))

    detail = await service.get_vehicle_detail("0012")
    v = detail.vehicle
    assert (v.vehicle_id, v.machine_no, v.model_id, v.serial_number) == ("0012", "0012", "0005", "000777")
    assert (detail.model.model_code, detail.model.assigned_pm_plan_id) == ("0099", "PMP-0001")
    assert [c.vehicle_id for c in detail.components] == ["0012"]
    assert [e.vehicle_id for e in await service.list_status_history("0012")] == ["0012"]
    listed = await service.list_vehicles(None, None, None, PageParams())
    assert listed.items[0].machine_no == "0012"
    models = await service.list_models(None, PageParams())
    assert models.items[0].model_id == "0005"
    # Legacy path, documented unchanged: cached positions -> not found.
    assert await repo.get_vehicle("0012") is None


@pytest.mark.asyncio
async def test_t10_writes_after_warm_cache_and_reorder_address_the_right_cells() -> None:
    backend, repo, service = _setup([_row("VEH-1", machine="TC-1", model="0005")])
    await repo._client.find_row(schemas.VEHICLE_SHEET, "vehicle_id", "VEH-1")  # warm legacy cache
    backend.tabs[VEHICLE_TAB] = _reorder(backend.tabs[VEHICLE_TAB], VEHICLE_REORDER)
    await service.update_machine_no("VEH-1", "0012")
    await service.change_status("VEH-1", OperationalStatus.MAINTENANCE, "u", None)
    stored = dict(zip(backend.tabs[VEHICLE_TAB][0], backend.tabs[VEHICLE_TAB][1]))
    assert (stored["machine_no"], stored["model_id"], stored["operational_status"]) == ("0012", "0005", "MAINTENANCE")
    ranges = [d["range"] for w in backend.write_log if w["kind"] == "batchUpdate" for d in w["data"]]
    assert ranges == ["'vehicle_master'!F2", "'vehicle_master'!B2", "'vehicle_master'!C2", "'vehicle_master'!B2"]


# ---------------------------------------------------------------------------
# T06 / T07 — targeted payloads, round trips, history alignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["0012", "1.50", "=1+1", "TRUE", "'x", "12/03", " 0012 "])
async def test_t06_machine_no_round_trip_one_targeted_forced_text_write(value: str) -> None:
    header = [*HEADER, "asset_tag", "formula_col"]
    backend, _, service = _setup([[*_row("VEH-1", model="0005", serial="000777"), "000045", "=SUM(1,2)"]], vehicle_header=header)
    before = copy.deepcopy(backend.tabs[VEHICLE_TAB][1])
    result = await service.update_machine_no("VEH-1", value)
    assert result.machine_no == value
    assert len(backend.write_log) == 1
    write = backend.write_log[0]
    assert write["kind"] == "batchUpdate" and write["valueInputOption"] == "USER_ENTERED"
    assert [d["range"] for d in write["data"]] == ["'vehicle_master'!B2", "'vehicle_master'!G2"]
    assert write["data"][0]["values"] == [[f"'{value}"]]
    after = backend.tabs[VEHICLE_TAB][1]
    changed = [h for h, a, b in zip(header, before, after) if a != b]
    assert changed == ["machine_no", "updated_at"]
    assert (await service.get_vehicle_detail("VEH-1")).vehicle.machine_no == value  # EMULATED storage


@pytest.mark.asyncio
async def test_t07_status_change_targets_two_cells_and_aligns_history_after_reorder() -> None:
    header = [*HEADER, "formula_col"]
    backend, repo, service = _setup(
        [[*_row("VEH-9", machine="0012", model="0005", serial="000777"), "=A1"]],
        vehicle_header=header,
        history=[["STH-0007", "VEH-9", "READY", TS, "u0", "first"]],
    )
    await repo.list_vehicle_status_history("VEH-9")  # warm legacy history header
    new_order = ["note", "changed_by", "changed_at", "status", "vehicle_id", "history_id"]
    backend.tabs[HISTORY_TAB] = _reorder(backend.tabs[HISTORY_TAB], new_order)
    before = copy.deepcopy(backend.tabs[VEHICLE_TAB][1])
    vehicle, entry = await service.change_status("VEH-9", OperationalStatus.MAINTENANCE, "u1", "n1")
    assert (vehicle.operational_status, vehicle.machine_no) == (OperationalStatus.MAINTENANCE, "0012")
    assert entry.history_id == "STH-0008"
    after = backend.tabs[VEHICLE_TAB][1]
    assert [h for h, a, b in zip(header, before, after) if a != b] == ["operational_status", "updated_at"]
    batch, append = backend.write_log
    assert [d["values"][0][0] for d in batch["data"]][0] == "'MAINTENANCE"
    assert append["values"][:2] == ["n1", "u1"] and append["values"][4:] == ["'VEH-9", "'STH-0008"]
    assert append["range"] == "'vehicle_status_history'!A1:F" and append["insertDataOption"] == "INSERT_ROWS"
    stored = dict(zip(new_order, backend.tabs[HISTORY_TAB][-1]))
    assert (stored["history_id"], stored["vehicle_id"], stored["status"], stored["note"]) == ("STH-0008", "VEH-9", "MAINTENANCE", "n1")
    history = await service.list_status_history("VEH-9")
    assert [e.history_id for e in history] == ["STH-0008", "STH-0007"]


@pytest.mark.asyncio
async def test_t07_history_vehicle_id_with_leading_zeros_is_forced_text() -> None:
    backend, _, service = _setup([_row("0012")])
    await service.change_status("0012", OperationalStatus.WORKING, None, None)
    assert backend.write_log[1]["values"][:2] == ["'STH-0001", "'0012"]
    assert [e.vehicle_id for e in await service.list_status_history("0012")] == ["0012"]


# ---------------------------------------------------------------------------
# T09 / T20 / T21 / T18 — zero-write preflight
# ---------------------------------------------------------------------------

_VEHICLE_DAMAGE: dict[str, Callable[[], dict]] = {
    "missing_header": lambda: {"vehicle_header": [h for h in HEADER if h != "machine_no"], "rows": [_row("VEH-1")[:1] + _row("VEH-1")[2:]]},
    "renamed_header": lambda: {"vehicle_header": [("machine no" if h == "machine_no" else h) for h in HEADER], "rows": [_row("VEH-1")]},
    "duplicate_header": lambda: {"vehicle_header": [*HEADER, "machine_no"], "rows": [[*_row("VEH-1"), "x"]]},
    "data_outside_header": lambda: {"vehicle_header": HEADER, "rows": [[*_row("VEH-1"), "stray"]]},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(_VEHICLE_DAMAGE))
async def test_t09_t20_vehicle_master_damage_zero_writes(case: str) -> None:
    spec = _VEHICLE_DAMAGE[case]()
    backend, _, service = _setup(spec["rows"], vehicle_header=spec["vehicle_header"])
    for call in (service.update_machine_no("VEH-1", "X"), service.change_status("VEH-1", OperationalStatus.WORKING, "u", None),
                 service.get_vehicle_detail("VEH-1")):
        err = await _api_error(call)
        assert (err.code, err.status_code) == ("VEHICLE_MASTER_SCHEMA_INVALID", 500)
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_t20_missing_tab_and_empty_tab_zero_writes() -> None:
    backend = WritableBackend({"model_master": [MODEL_HEADER]})
    service = VehicleService(_repo(backend))
    err = await _api_error(service.update_machine_no("VEH-1", "X"))
    assert (err.code, err.details["problem"]) == ("VEHICLE_MASTER_SCHEMA_INVALID", "TAB_MISSING")
    backend2 = WritableBackend({VEHICLE_TAB: None})
    err = await _api_error(VehicleService(_repo(backend2)).change_status("VEH-1", OperationalStatus.WORKING, "u", None))
    assert err.details["problem"] == "NO_HEADER_ROW"
    assert backend.mutation_count() == backend2.mutation_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "history_header",
    [[h for h in HISTORY_HEADER if h != "note"], [h for h in HISTORY_HEADER if h != "vehicle_id"],
     [("Status" if h == "status" else h) for h in HISTORY_HEADER], [*HISTORY_HEADER, "note"]],
    ids=["missing_note", "missing_vehicle_id", "renamed_status", "duplicate_note"],
)
async def test_t21_history_schema_damage_rejected_before_the_vehicle_write(history_header: list[str]) -> None:
    backend, _, service = _setup([_row("VEH-1")], history_header=history_header)
    err = await _api_error(service.change_status("VEH-1", OperationalStatus.WORKING, "u", None))
    assert (err.code, err.status_code, err.details["tab"]) == ("VEHICLE_STATUS_HISTORY_SCHEMA_INVALID", 500, HISTORY_TAB)
    assert backend.mutation_count() == 0
    assert dict(zip(HEADER, backend.tabs[VEHICLE_TAB][1]))["operational_status"] == "READY"


@pytest.mark.asyncio
async def test_t21_history_data_outside_header_rejected_before_write() -> None:
    backend, _, service = _setup([_row("VEH-1")], history=[["STH-0001", "VEH-1", "READY", TS, "u", "", "stray"]])
    err = await _api_error(service.change_status("VEH-1", OperationalStatus.WORKING, "u", None))
    assert err.details["problem"] == "DATA_OUTSIDE_HEADER"
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_row", [_row("VEH-1", ""), _row("VEH-1", "BROKEN"), _row("VEH-1", updated="2026")],
                         ids=["blank_status", "unknown_status", "numericised_date"])
async def test_t18_invalid_source_row_zero_writes(bad_row: list[str]) -> None:
    backend, _, service = _setup([bad_row])
    for call in (service.update_machine_no("VEH-1", "X"), service.change_status("VEH-1", OperationalStatus.WORKING, "u", None)):
        assert (await _api_error(call)).code == "VEHICLE_MASTER_DATA_INVALID"
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_t18_mapper_failure_is_data_invalid_zero_writes(monkeypatch) -> None:
    backend, repo, service = _setup([_row("VEH-1")])

    def bad_mapper(row):
        raise ValueError("synthetic mapping failure")

    monkeypatch.setattr(repo, "_vehicle_from_row", bad_mapper)
    err = await _api_error(service.update_machine_no("VEH-1", "X"))
    assert err.details == {"issue_counts": {"UNMAPPABLE_ROW": 1}}
    assert backend.mutation_count() == 0


# ---------------------------------------------------------------------------
# T11 / T11a / T11b / T12a-c — read failures and honest write outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t11_read_failures_are_503_zero_writes() -> None:
    backend, _, service = _setup([_row("VEH-1")])
    backend.fail_values_get = True
    for call in (service.update_machine_no("VEH-1", "X"), service.get_vehicle_detail("VEH-1")):
        err = await _api_error(call)
        assert (err.code, err.status_code) == ("VEHICLE_MASTER_READ_FAILED", 503)
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["machine_no", "status"])
@pytest.mark.parametrize(("mode", "outcome", "applied"), [("reject", "rejected", False), ("apply_then_timeout", "unknown", True), ("server_error", "unknown", False)])
async def test_t11a_t11b_vehicle_write_outcomes(which: str, mode: str, outcome: str, applied: bool) -> None:
    """[SIMULATION] reject = HTTP 400, not applied; apply_then_timeout =
    applied by the fake, then the response is lost; server_error = 503."""
    backend, _, service = _setup([_row("VEH-1", machine="TC-1")])
    backend.fail["batchUpdate"] = mode
    call = service.update_machine_no("VEH-1", "TC-NEW") if which == "machine_no" else service.change_status("VEH-1", OperationalStatus.MAINTENANCE, "u", None)
    err = await _api_error(call)
    assert (err.code, err.status_code, err.details) == ("VEHICLE_MASTER_WRITE_FAILED", 503, {"vehicle_write_outcome": outcome})
    assert [w["kind"] for w in backend.write_log] == ["batchUpdate"]  # one attempt, no retry, no history
    stored = dict(zip(HEADER, backend.tabs[VEHICLE_TAB][1]))
    changed = stored["machine_no"] == "TC-NEW" or stored["operational_status"] == "MAINTENANCE"
    assert changed is applied
    if outcome == "unknown":
        assert "may have been applied" in err.message and "not updated" not in err.message
    assert len(backend.tabs[HISTORY_TAB]) == 1  # header only


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "outcome", "row_added"), [("reject", "rejected", False), ("apply_then_timeout", "unknown", True), ("server_error", "unknown", False)])
async def test_t12a_t12b_t12c_history_append_outcomes(mode: str, outcome: str, row_added: bool) -> None:
    """[SIMULATION] after an ACKNOWLEDGED vehicle write the history append is
    rejected (400), applied-then-lost (timeout) or 503."""
    backend, _, service = _setup([_row("VEH-1")])
    backend.fail["append"] = mode
    backend.requests.clear()
    err = await _api_error(service.change_status("VEH-1", OperationalStatus.MAINTENANCE, "u", None))
    assert (err.code, err.status_code) == ("VEHICLE_STATUS_HISTORY_WRITE_FAILED", 503)
    assert err.details == {"vehicle_status_updated": True, "history_write_outcome": outcome}
    assert [w["kind"] for w in backend.write_log] == ["batchUpdate", "append"]  # one attempt each
    assert (len(backend.tabs[HISTORY_TAB]) == 2) is row_added
    assert dict(zip(HEADER, backend.tabs[VEHICLE_TAB][1]))["operational_status"] == "MAINTENANCE"
    if outcome == "unknown":
        assert "may or may not have been recorded" in err.message
    # No re-read after the uncertain write: the last request is the append.
    assert backend.requests[-1][1] == "append"


@pytest.mark.asyncio
async def test_t12b_http_envelope_reports_unknown_history_outcome() -> None:
    backend, repo, _ = _setup([_row("VEH-1")])
    backend.fail["append"] = "apply_then_timeout"
    response = await _http(repo, "PATCH", "/api/v1/vehicles/VEH-1/status", json={"status": "WORKING"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "VEHICLE_STATUS_HISTORY_WRITE_FAILED"
    assert error["details"] == {"vehicle_status_updated": True, "history_write_outcome": "unknown"}
    assert "Traceback" not in response.text and "fake.json" not in response.text


# ---------------------------------------------------------------------------
# T13 — measured request counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t13_measured_request_counts_warm() -> None:
    backend, _, service = _setup([_row("VEH-1")], history=[["STH-0001", "VEH-1", "READY", TS, "u", ""]])
    await service.change_status("VEH-1", OperationalStatus.WORKING, "u", None)  # warm
    backend.requests.clear()
    await service.update_machine_no("VEH-1", "TC-2")
    assert backend.requests == [("get", "values", VEHICLE_TAB), ("post", "batchUpdate", None)]
    backend.requests.clear()
    await service.change_status("VEH-1", OperationalStatus.READY, "u", None)
    assert backend.requests == [("get", "values", VEHICLE_TAB), ("get", "values", HISTORY_TAB),
                                ("post", "batchUpdate", None), ("post", "append", HISTORY_TAB)]
    backend.requests.clear()
    await service.get_vehicle_detail("VEH-1")
    await service.list_components("VEH-1")
    await service.list_status_history("VEH-1")
    await service.list_models(None, PageParams())
    assert all(method == "get" for method, _, _ in backend.requests)
    assert backend.mutation_count() == 5  # 2 (warm-up status) + 1 + 2


# ---------------------------------------------------------------------------
# T14 — unexpected exceptions propagate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t14_unexpected_exception_propagates(monkeypatch) -> None:
    backend, repo, service = _setup([_row("VEH-1")])

    def broken(row):
        raise LookupError("programming error")

    monkeypatch.setattr(repo, "_vehicle_from_row", broken)
    with pytest.raises(LookupError):
        await service.update_machine_no("VEH-1", "X")
    response = await _http(repo, "PATCH", "/api/v1/vehicles/VEH-1", json={"machine_no": "X"})
    assert (response.status_code, response.json()["error"]["code"]) == (500, "INTERNAL_ERROR")
    assert backend.mutation_count() == 0


# ---------------------------------------------------------------------------
# DEC-H3(a) — model -> plan resolution on text codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h3a_plan_codes_01_and_1_are_distinct_and_numeric_plan_ids_are_text() -> None:
    _, repo, service = _setup(
        [_row("VEH-1")],
        models=[["MDL-1", "MC-1", "One", "", "", "CARRIER_ENGINE", TS, TS, "01"],
                ["MDL-2", "MC-2", "Two", "", "", "CARRIER_ENGINE", TS, TS, "1"]],
        plans=[["0007", "01", "VEHICLE", "Plan 01", "", TS, TS], ["PMP-0002", "1", "VEHICLE", "Plan 1", "", TS, TS]],
    )
    models = (await service.list_models(None, PageParams())).items
    assert {m.model_id: m.assigned_pm_plan_id for m in models} == {"MDL-1": "0007", "MDL-2": "PMP-0002"}
    assert (await service.get_model("MDL-1")).assigned_pm_plan_id == "0007"
    # Legacy PM paths are unchanged (DEC-H3a is limited to VehicleService):
    # they still numericise these codes and fail to map them.
    with pytest.raises(ValueError):
        await repo.list_pm_plans(None, None)


@pytest.mark.asyncio
async def test_h14a_model_and_plan_tab_failures_use_model_codes() -> None:
    backend = WritableBackend(_tabs([_row("VEH-1")]))
    del backend.tabs["maintenance_plan"]
    service = VehicleService(_repo(backend))
    err = await _api_error(service.list_models(None, PageParams()))
    assert (err.code, err.details["tab"], err.details["problem"]) == ("MODEL_MASTER_SCHEMA_INVALID", "maintenance_plan", "TAB_MISSING")
    backend2 = WritableBackend(_tabs([_row("VEH-1")]))
    backend2.tabs["vehicle_component"] = [[h.upper() for h in COMPONENT_HEADER]]
    err = await _api_error(VehicleService(_repo(backend2)).get_vehicle_detail("VEH-1"))
    assert (err.code, err.details["tab"]) == ("VEHICLE_COMPONENT_SCHEMA_INVALID", "vehicle_component")


# ---------------------------------------------------------------------------
# HTTP over Sheets — H8(b) and success shapes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_patch_preserves_text_and_rejects_whitespace_only() -> None:
    backend, repo, _ = _setup([_row("0012", machine="TC-1")])
    ok = await _http(repo, "PATCH", "/api/v1/vehicles/0012", json={"machine_no": " 0099 "})
    assert ok.status_code == 200 and ok.json()["machine_no"] == " 0099 " and ok.json()["vehicle_id"] == "0012"
    assert set(ok.json()) == {"vehicle_id", "machine_no", "model_id", "serial_number", "operational_status", "created_at", "updated_at"}
    backend.requests.clear()
    before = len(backend.write_log)
    bad = await _http(repo, "PATCH", "/api/v1/vehicles/0012", json={"machine_no": "   "})
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "VALIDATION_ERROR")
    assert backend.requests == [] and len(backend.write_log) == before
    detail = await _http(repo, "GET", "/api/v1/vehicles/0012")
    assert detail.json()["vehicle"]["machine_no"] == " 0099 "
    status = await _http(repo, "PATCH", "/api/v1/vehicles/0012/status", json={"status": "WORKING"})
    assert status.status_code == 200
    assert set(status.json()) == {"vehicle", "history_entry"}
    assert status.json()["history_entry"]["vehicle_id"] == "0012"
    ambiguous = await _http(_repo(WritableBackend(_tabs([_row("D"), _row("D")]))), "GET", "/api/v1/vehicles/D")
    assert (ambiguous.status_code, ambiguous.json()["error"]["code"]) == (409, "VEHICLE_ID_AMBIGUOUS")


@pytest.mark.asyncio
async def test_list_and_dashboard_reads_never_write() -> None:
    backend, repo, _ = _setup([_row("0012")])
    for path in ("/api/v1/vehicles", "/api/v1/dashboard/fleet-status", "/api/v1/vehicles/0012",
                 "/api/v1/vehicles/0012/components", "/api/v1/vehicles/0012/status-history", "/api/v1/models"):
        response = await _http(repo, "GET", path)
        assert response.status_code == 200, (path, response.text)
    assert backend.mutation_count() == 0
    assert json.dumps(backend.tabs)  # unchanged storage is serialisable
