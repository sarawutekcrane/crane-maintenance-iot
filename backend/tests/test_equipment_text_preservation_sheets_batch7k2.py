"""Phase 7 Batch 7K2 — equipment text preservation over Google Sheets.

Real installed gspread over the existing fake HTTP transport. The 7H2
`WritableBackend` (values:batchUpdate and values:append recorded, applied and
failure-injectable) is imported UNCHANGED; `PutBackend` below adds, in THIS
FILE only, recording of the legacy whole-row PUT (`update_row`) so tests can
prove it is never sent, plus "formula" cell markers (any write to such a cell
is recorded as an overwrite).

STORAGE EMULATION — NOT GOOGLE SHEETS (7H2 model): a leading apostrophe
forces text; a plain number is stored as a number and re-read in general
format ("0012" -> "12"); dates, booleans, locales and formula evaluation are
not emulated. These tests prove the PAYLOADS and the application logic; what
live Sheets stores is not validated here. Request counts are fake-transport
measurements, not live cost. All fixtures are synthetic.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from urllib.parse import unquote

import gspread
import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists, require_asset_for_new_work
from app.domain.common import PageParams
from app.domain.equipment import EquipmentOperationalStatus as S
from app.domain.equipment_rules import known_text_hazard
from app.domain.equipment_service import EquipmentService
from app.errors import ApiError
from app.repositories.google_sheets import schemas
from app.repositories.mock.repository import MockRepository
from tests.test_equipment_text_preservation_batch7k2 import SpyStorage
from tests.test_fleet_status_summary_sheets_batch7b2 import _FakeResponse, _repo
from tests.test_vehicle_text_preservation_sheets_batch7h2 import WritableBackend, _col_index

EQ = schemas.EQUIPMENT_SHEET.tab_name
EQH = schemas.EQUIPMENT_STATUS_HISTORY_SHEET.tab_name
EQ_HEADER = list(schemas.EQUIPMENT_SHEET.required_headers)
EQH_HEADER = list(schemas.EQUIPMENT_STATUS_HISTORY_SHEET.required_headers)
TS = "2026-01-15T08:00:00+00:00"


def eq_row(eid="EQP-1", code="EC-1", name="เครื่องกลึง", etype="LATHE", brand="", model_name="", serial="",
           status="READY", active="TRUE", start="2026-01-01", note="") -> list[str]:
    return [eid, code, name, etype, brand, model_name, serial, status, active, start, note]


def h_row(hid="ESTH-0001", eid="EQP-1", code="READY", start=TS, reason="", by="") -> list[str]:
    return [hid, eid, code, start, "", reason, by, "", ""]


class PutBackend(WritableBackend):
    def __init__(self, tabs):
        super().__init__(tabs)
        self.formulas: dict[tuple[str, int, int], str] = {}
        self.formula_overwrites: list[tuple] = []

    def _apply(self, tab, row, col, raw):
        if (tab, row, col) in self.formulas:
            self.formula_overwrites.append((tab, row, col, self.formulas.pop((tab, row, col)), raw))
        super()._apply(tab, row, col, raw)

    def request(self, method, url, json=None, params=None, data=None, files=None, headers=None, timeout=None):  # noqa: A002
        if method.lower() == "put":
            values = self._VALUES_RE.search(url)
            tab, _, cells = unquote(values.group(2)).partition("!")
            self.write_log.append({"kind": "put", "tab": tab.strip("'"), "range": cells})
            self.requests.append(("put", "values", tab.strip("'")))
            m = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", cells)
            for c_off, raw in enumerate((json or {}).get("values", [[]])[0]):
                self._apply(tab.strip("'"), int(m.group(2)), _col_index(m.group(1)) + c_off, str(raw))
            return _FakeResponse({"spreadsheetId": "fake"})
        return super().request(method, url, json=json, params=params, data=data, files=files, headers=headers, timeout=timeout)

    def puts(self) -> list[dict]:
        return [w for w in self.write_log if w["kind"] == "put"]


def setup(rows, *, history=None, eq_header=None, eqh_header=None, extra=None):
    tabs = {EQ: [list(eq_header or EQ_HEADER), *copy.deepcopy(rows)],
            EQH: [list(eqh_header or EQH_HEADER), *copy.deepcopy(history or [])]}
    tabs.update(copy.deepcopy(extra or {}))
    backend = PutBackend(tabs)
    repo = _repo(backend)
    return backend, repo, EquipmentService(repo)


def reorder(rows, new_header):
    idx = [rows[0].index(h) for h in new_header]
    return [[r[i] if i < len(r) else "" for i in idx] for r in rows]


async def api_error(coro) -> ApiError:
    with pytest.raises(ApiError) as info:
        await coro
    return info.value


async def http(repo, method, path, storage=None, **kwargs):
    from app.config import get_settings
    from app.dependencies import get_repository, get_storage_provider, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_storage_provider] = lambda: storage or SpyStorage()
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            return await c.request(method, path, **kwargs)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


async def ids(service, q=None):
    page = await service.list_equipment(q, None, PageParams(page=1, page_size=200))
    return [(e.equipment_id, e.equipment_code, e.name, e.serial_number) for e in page.items]


MUTATIONS = {
    "D1b": ("POST", "/api/v1/pm/work-orders", lambda e: {"json": {"asset_type": "EQUIPMENT", "asset_id": e, "pm_plan_id": "P"}}),
    "D1c": ("POST", "/api/v1/repairs", lambda e: {"json": {"asset_type": "EQUIPMENT", "asset_id": e, "source_type": "MANUAL"}}),
    "D1g": ("POST", "/api/v1/material-requests", lambda e: {"json": {"source_type": "REPAIR", "source_work_order_id": "R",
                                                                     "asset_type": "EQUIPMENT", "asset_id": e}}),
    "D1h": ("POST", "/api/v1/position-lifetime", lambda e: {"json": {"asset_type": "EQUIPMENT", "asset_id": e, "position_code": "P",
                                                                     "prior_usage": {"quality": "UNKNOWN"}}}),
    "D2": ("POST", "/api/v1/inspections", lambda e: {"json": {"asset_type": "EQUIPMENT", "asset_id": e,
                                                              "items": [{"item_id": "I", "result": "PASS"}]}}),
    "D3u": ("POST", "/api/v1/attachments", lambda e: {"data": {"purpose": "INSPECTION_EVIDENCE", "source_type": "INSPECTION_EQUIPMENT",
                                                               "source_id": e}, "files": {"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")}}),
}


# =============================================================================================
# KS01 — F-A: ordinary unique id with numeric-looking code/name/serial, end to end
# =============================================================================================


@pytest.mark.asyncio
async def test_ks01_fixture_a_ordinary_id_with_numeric_looking_fields() -> None:
    ms = [list(schemas.METER_SNAPSHOT_SHEET.required_headers)]
    mr = [list(schemas.METER_READING_SHEET.required_headers)]
    backend, repo, service = setup([eq_row(code="0012", name="1234", serial="0099")],
                                   history=[h_row()], extra={"meter_snapshot": ms, "meter_readings": mr})
    assert await ids(service) == [("EQP-1", "0012", "1234", "0099")]
    assert await ids(service, "0012") == [("EQP-1", "0012", "1234", "0099")]
    assert await ids(service, "1234") == [("EQP-1", "0012", "1234", "0099")]
    detail = await service.get_equipment("EQP-1")
    assert (detail.equipment_code, detail.name, detail.serial_number) == ("0012", "1234", "0099")
    assert [h.history_id for h in await service.list_status_history("EQP-1")] == ["ESTH-0001"]
    # The exact helper D1d install and D1e transfer call before their first write.
    await require_asset_for_new_work(repo, AssetType.EQUIPMENT, "EQP-1")
    await require_asset_exists(repo, AssetType.EQUIPMENT, "EQP-1")
    changed = await service.change_status("EQP-1", S.MAINTENANCE, None, "user-1")
    assert (changed.equipment_code, changed.operational_status) == ("0012", S.MAINTENANCE)
    assert backend.tabs[EQ][1][1] == "0012" and backend.tabs[EQ][1][6] == "0099"
    await repo.create_meter_snapshot(AssetType.EQUIPMENT, "EQP-1", [], "u", is_automatic=True)
    sent = [w["values"][2] for w in backend.write_log if w["kind"] == "append" and w["tab"] == "meter_snapshot"]
    assert sent == ["EQP-1"]  # downstream asset_id unchanged for an id with no known hazard


# =============================================================================================
# KS02 — F-B: numeric-looking id "0012"
# =============================================================================================


@pytest.mark.asyncio
async def test_ks02_fixture_b_equipment_owned_operations_keep_0012_exactly() -> None:
    backend, repo, service = setup([eq_row(eid="0012")], history=[h_row(eid="0012"), h_row(hid="ESTH-0002", eid="12")])
    assert await ids(service) == [("0012", "EC-1", "เครื่องกลึง", None)]
    assert (await service.get_equipment("0012")).equipment_id == "0012"
    history = await service.list_status_history("0012")
    assert [h.history_id for h in history] == ["ESTH-0001"]  # the row stored as "12" is not shown
    assert (await api_error(service.get_equipment("12"))).code == "EQUIPMENT_NOT_FOUND"
    await service.change_status("0012", S.IN_USE, None, "u")
    append = [w for w in backend.write_log if w["kind"] == "append"][-1]
    assert append["values"][1] == "'0012" and backend.tabs[EQH][-1][1] == "0012"
    assert backend.tabs[EQ][1][0] == "0012"


@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(MUTATIONS))
async def test_ks02_fixture_b_mutating_sites_refuse_before_any_mutation_request(label) -> None:
    backend, repo, _ = setup([eq_row(eid="0012")])
    storage = SpyStorage()
    method, path, kwargs = MUTATIONS[label]
    r = await http(repo, method, path, storage=storage, **kwargs("0012"))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK"
    assert backend.mutation_count() == 0 and storage.save_calls == 0
    assert all(kind == "values" and tab == EQ for m, kind, tab in backend.requests if m == "get" and kind == "values")


@pytest.mark.asyncio
async def test_ks02_fixture_b_read_only_callers_and_lost_zero() -> None:
    backend, repo, _ = setup([eq_row(eid="0012"), eq_row(eid="12", code="EC-12")])
    r = await http(repo, "GET", "/api/v1/machine-state/current?asset_type=EQUIPMENT&asset_id=0012")
    assert r.status_code == 200, r.text  # D1f is read-only: not guarded (DEC-K10(a))
    assert r.json()["asset_id"] == "0012" and r.json()["readings"] == []
    # A cell already stored as the number 12 reads "12": no recovery, distinct from "0012".
    service = EquipmentService(repo)
    assert {i[0] for i in await ids(service)} == {"0012", "12"}
    assert (await service.get_equipment("12")).equipment_code == "EC-12"
    assert backend.mutation_count() == 0


# =============================================================================================
# KS03 — warm cache + live column reorder before list/detail/history/status
# =============================================================================================


@pytest.mark.asyncio
async def test_ks03_warm_cache_then_column_reorder() -> None:
    backend, repo, service = setup([eq_row(code="0099", serial="SN-9")], history=[h_row(reason="0007")])
    await ids(service)
    await service.list_status_history("EQP-1")
    await repo._client.read_rows(schemas.EQUIPMENT_SHEET)  # also warm the LEGACY header cache
    await repo._client.read_rows(schemas.EQUIPMENT_STATUS_HISTORY_SHEET)
    backend.tabs[EQ] = reorder(backend.tabs[EQ], ["equipment_status", *[h for h in EQ_HEADER if h != "equipment_status"]])
    backend.tabs[EQH] = reorder(backend.tabs[EQH], ["equipment_id", "status_history_id",
                                                    *[h for h in EQH_HEADER if h not in ("equipment_id", "status_history_id")]])
    assert await ids(service) == [("EQP-1", "0099", "เครื่องกลึง", "SN-9")]
    assert [h.reason for h in await service.list_status_history("EQP-1")] == ["0007"]
    await service.change_status("EQP-1", S.MAINTENANCE, "r", "u")
    batch = [w for w in backend.write_log if w["kind"] == "batchUpdate"][0]
    assert [d["range"] for d in batch["data"]] == ["'equipment_master'!A2"]
    row = dict(zip(backend.tabs[EQ][0], backend.tabs[EQ][1]))
    assert (row["equipment_status"], row["equipment_id"], row["serial_no"]) == ("MAINTENANCE", "EQP-1", "SN-9")
    hist = dict(zip(backend.tabs[EQH][0], backend.tabs[EQH][-1]))
    assert (hist["equipment_id"], hist["status_code"]) == ("EQP-1", "MAINTENANCE")
    assert backend.puts() == []


# =============================================================================================
# KS04 / KS05 — structural failures: envelope and ZERO mutations
# =============================================================================================


def _broken(header, problem):
    if problem == "MISSING_HEADERS":
        return [[h if i != 2 else h + "_x" for i, h in enumerate(header)]], (header[2],)
    if problem == "DUPLICATE_HEADERS":
        return [[*header, header[1]]], (header[1],)
    if problem == "DATA_OUTSIDE_HEADER":
        return [[*header, ""]], ()
    raise AssertionError(problem)


@pytest.mark.asyncio
@pytest.mark.parametrize("tab", [EQ, EQH])
@pytest.mark.parametrize("problem", ["TAB_MISSING", "NO_HEADER_ROW", "MISSING_HEADERS", "DUPLICATE_HEADERS", "DATA_OUTSIDE_HEADER"])
async def test_ks04_structural_problems_fail_before_any_write(tab, problem) -> None:
    backend, repo, service = setup([eq_row()], history=[h_row()])
    header = EQ_HEADER if tab == EQ else EQH_HEADER
    expected_headers: tuple = ()
    if problem == "TAB_MISSING":
        del backend.tabs[tab]
    elif problem == "NO_HEADER_ROW":
        backend.tabs[tab] = None
    else:
        (new_header,), expected_headers = _broken(header, problem)
        body = backend.tabs[tab][1:]
        if problem == "DATA_OUTSIDE_HEADER":
            body = [[*r, "stray"] for r in body]
        backend.tabs[tab] = [new_header, *body]
    prefix = "EQUIPMENT_MASTER" if tab == EQ else "EQUIPMENT_STATUS_HISTORY"
    err = await api_error(service.change_status("EQP-1", S.MAINTENANCE, None, None))
    assert (err.status_code, err.code) == (500, f"{prefix}_SCHEMA_INVALID")
    assert err.details == {"tab": tab, "problem": problem, "headers": list(expected_headers)}
    assert backend.mutation_count() == 0
    if tab == EQ:
        assert (await api_error(ids(service))).code == "EQUIPMENT_MASTER_SCHEMA_INVALID"
    assert (await api_error(service.list_status_history("EQP-1"))).code == f"{prefix}_SCHEMA_INVALID"


@pytest.mark.asyncio
async def test_ks05_history_header_missing_blocks_the_status_write_although_the_row_is_valid() -> None:
    backend, repo, service = setup([eq_row()], eqh_header=[h if h != "status_code" else "status" for h in EQH_HEADER])
    err = await api_error(service.change_status("EQP-1", S.MAINTENANCE, None, None))
    assert err.code == "EQUIPMENT_STATUS_HISTORY_SCHEMA_INVALID" and err.details["headers"] == ["status_code"]
    assert backend.mutation_count() == 0 and backend.tabs[EQ][1][7] == "READY"


@pytest.mark.asyncio
async def test_ks05_read_failure_maps_to_503_without_writes() -> None:
    backend, repo, service = setup([eq_row()])
    backend.fail_values_get = True
    err = await api_error(service.change_status("EQP-1", S.MAINTENANCE, None, None))
    assert (err.status_code, err.code, err.details) == (503, "EQUIPMENT_MASTER_READ_FAILED", None)
    assert backend.mutation_count() == 0


# =============================================================================================
# KS06 — F-C blank id and F-D duplicate id
# =============================================================================================


@pytest.mark.asyncio
async def test_ks06_fixture_c_blank_id_is_listed_but_not_addressable() -> None:
    backend, repo, service = setup([eq_row(), eq_row(eid="", code="EC-X")])
    assert [i[:2] for i in await ids(service)] == [("", "EC-X"), ("EQP-1", "EC-1")]
    assert (await service.get_equipment("EQP-1")).equipment_code == "EC-1"
    backend.requests.clear()
    for blank in ("", " ", "\t"):
        assert (await api_error(service.get_equipment(blank))).code == "EQUIPMENT_NOT_FOUND"
        assert (await api_error(service.change_status(blank, S.READY, None, None))).code == "EQUIPMENT_NOT_FOUND"
    assert backend.requests == []  # no read at all
    r = await http(repo, "POST", "/api/v1/repairs", json={"asset_type": "EQUIPMENT", "asset_id": "", "source_type": "MANUAL"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert backend.mutation_count() == 0


@pytest.mark.asyncio
async def test_ks06_fixture_d_duplicate_id_is_listed_but_ambiguous_everywhere_else() -> None:
    backend, repo, service = setup([eq_row(code="EC-A"), eq_row(code="EC-B")], history=[h_row()])
    assert [i[:2] for i in await ids(service)] == [("EQP-1", "EC-A"), ("EQP-1", "EC-B")]
    for call in (service.get_equipment("EQP-1"), service.list_status_history("EQP-1"),
                 service.change_status("EQP-1", S.MAINTENANCE, None, None),
                 require_asset_exists(repo, AssetType.EQUIPMENT, "EQP-1"),
                 require_asset_for_new_work(repo, AssetType.EQUIPMENT, "EQP-1")):
        err = await api_error(call)
        assert (err.status_code, err.code, err.details) == (409, "EQUIPMENT_ID_AMBIGUOUS", {"match_count": 2})
    r = await http(repo, "GET", "/api/v1/machine-state/current?asset_type=EQUIPMENT&asset_id=EQP-1")
    assert r.status_code == 409
    assert backend.mutation_count() == 0


# =============================================================================================
# KS07 — F-F and per-row counting / precedence
# =============================================================================================


@pytest.mark.asyncio
async def test_ks07_fixture_f_other_row_invalid_category_fails_only_the_list() -> None:
    backend, repo, service = setup([eq_row(), eq_row(eid="EQP-2", etype="Lathe")])
    err = await api_error(ids(service))
    assert (err.status_code, err.code, err.details) == (500, "EQUIPMENT_MASTER_DATA_INVALID",
                                                        {"issue_counts": {"UNRECOGNIZED_CATEGORY": 1}})
    r = await http(repo, "GET", "/api/v1/equipment?page_size=10&q=x")  # the picker's request
    assert r.status_code == 500 and r.json()["error"]["code"] == "EQUIPMENT_MASTER_DATA_INVALID"
    assert (await service.get_equipment("EQP-1")).equipment_id == "EQP-1"
    await service.change_status("EQP-1", S.IN_USE, None, None)
    assert (await api_error(service.get_equipment("EQP-2"))).details == {"issue_counts": {"UNRECOGNIZED_CATEGORY": 1}}


@pytest.mark.asyncio
async def test_ks07_issue_counts_are_per_row_with_fixed_precedence() -> None:
    rows = [eq_row(eid="D", status="Ready"), eq_row(eid="D", status="Ready"),       # duplicate id: 2 rows
            eq_row(eid="X", etype="Lathe", status="Ready"),                          # both bad: category wins
            eq_row(eid="Y", etype=""), eq_row(eid="Z", status=""),
            ["", "", "", "", "", "", "", "", "", "", "note only"],                   # real row (note_th)
            [""] * 11]                                                               # phantom: ignored
    backend, repo, service = setup(rows)
    err = await api_error(ids(service))
    assert err.details == {"issue_counts": {"BLANK_CATEGORY": 2, "BLANK_STATUS": 1, "UNRECOGNIZED_CATEGORY": 1,
                                            "UNRECOGNIZED_STATUS": 2}}
    target = await api_error(service.change_status("Z", S.READY, None, None))
    assert target.details == {"issue_counts": {"BLANK_STATUS": 1}} and backend.mutation_count() == 0


# =============================================================================================
# KS08 — targeted write preserves unrelated cells and formulas; no legacy PUT
# =============================================================================================


@pytest.mark.asyncio
async def test_ks08_only_the_status_cell_is_written() -> None:
    backend, repo, service = setup([eq_row(brand="007", model_name="0250", note="8", active="TRUE", start="2026-01-01")])
    backend.formulas[(EQ, 2, EQ_HEADER.index("note_th") + 1)] = "=LEN(B2)*2"
    before = list(backend.tabs[EQ][1])
    await service.change_status("EQP-1", S.MAINTENANCE, None, None)
    batches = [w for w in backend.write_log if w["kind"] == "batchUpdate"]
    assert len(batches) == 1 and batches[0]["valueInputOption"] == "USER_ENTERED"
    assert [(d["range"], d["values"]) for d in batches[0]["data"]] == [("'equipment_master'!H2", [["'MAINTENANCE"]])]
    after = backend.tabs[EQ][1]
    assert after[7] == "MAINTENANCE" and after[:7] + after[8:] == before[:7] + before[8:]
    assert after[4:6] == ["007", "0250"] and backend.formula_overwrites == [] and backend.puts() == []


# =============================================================================================
# KS09 — history payload, order, structural-only preflight
# =============================================================================================


@pytest.mark.asyncio
async def test_ks09_history_payload_order_and_structural_only_preflight() -> None:
    history = [h_row(hid="ESTH-0007", eid="EQP-1", code="Broken"), h_row(hid="", eid="EQP-9", code=""),
               h_row(hid="ESTH-0003", eid="EQP-9", start="2026-01-02")]
    backend, repo, service = setup([eq_row()], history=history)
    await service.change_status("EQP-1", S.OUT_OF_SERVICE, "0007", "0042")
    kinds = [w["kind"] for w in backend.write_log]
    assert kinds == ["batchUpdate", "append"]
    append = backend.write_log[1]
    assert append["range"] == "'equipment_status_history'!A1:I" and append["insertDataOption"] == "INSERT_ROWS"
    assert append["valueInputOption"] == "USER_ENTERED"
    values = dict(zip(EQH_HEADER, append["values"]))
    assert values["status_history_id"] == "'ESTH-0008" and values["equipment_id"] == "'EQP-1"
    assert values["status_code"] == "'OUT_OF_SERVICE" and values["reason_th"] == "'0007"
    assert values["changed_by_user_id"] == "'0042" and values["start_at"].endswith("+00:00")
    assert values["end_at"] == values["source_type"] == values["source_id"] == ""
    stored = dict(zip(EQH_HEADER, backend.tabs[EQH][-1]))
    assert (stored["reason_th"], stored["changed_by_user_id"]) == ("0007", "0042")
    post_requests = backend.requests[[i for i, r in enumerate(backend.requests) if r[0] == "post"][0]:]
    assert all(r[0] == "post" for r in post_requests)  # no read after the first write
    # This equipment's own bad history row makes the HISTORY READ fail, but never blocked the write.
    assert (await api_error(service.list_status_history("EQP-1"))).details == {"issue_counts": {"UNRECOGNIZED_STATUS": 1}}


@pytest.mark.asyncio
async def test_ks09_empty_reason_and_actor_are_written_blank() -> None:
    backend, repo, service = setup([eq_row()])
    await service.change_status("EQP-1", S.READY, None, None)
    values = dict(zip(EQH_HEADER, backend.write_log[1]["values"]))
    assert values["reason_th"] == "" and values["changed_by_user_id"] == ""


# =============================================================================================
# KS10 — outcomes: one attempt, no retry, no re-read
# =============================================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, outcome, applied", [("reject", "rejected", False), ("server_error", "unknown", False),
                                                    ("apply_then_timeout", "unknown", True)])
async def test_ks10_equipment_update_failure(mode, outcome, applied) -> None:
    backend, repo, service = setup([eq_row()])
    backend.fail["batchUpdate"] = mode
    err = await api_error(service.change_status("EQP-1", S.MAINTENANCE, None, None))
    assert (err.status_code, err.code, err.details) == (503, "EQUIPMENT_MASTER_WRITE_FAILED", {"equipment_write_outcome": outcome})
    assert [w["kind"] for w in backend.write_log] == ["batchUpdate"]  # one attempt; history not attempted
    assert backend.tabs[EQ][1][7] == ("MAINTENANCE" if applied else "READY")
    assert backend.requests[-1][0] == "post"  # nothing read after the write


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, outcome", [("reject", "rejected"), ("server_error", "unknown"), ("apply_then_timeout", "unknown")])
async def test_ks10_history_append_failure_after_acknowledged_update(mode, outcome) -> None:
    backend, repo, service = setup([eq_row()])
    backend.fail["append"] = mode
    err = await api_error(service.change_status("EQP-1", S.MAINTENANCE, None, None))
    assert (err.status_code, err.code, err.details) == (
        503, "EQUIPMENT_STATUS_HISTORY_WRITE_FAILED", {"equipment_status_updated": True, "history_write_outcome": outcome})
    assert [w["kind"] for w in backend.write_log] == ["batchUpdate", "append"]
    assert backend.requests[-1][0] == "post"


@pytest.mark.asyncio
async def test_ks10_http_envelopes() -> None:
    backend, repo, _ = setup([eq_row()])
    backend.fail["append"] = "apply_then_timeout"
    r = await http(repo, "POST", "/api/v1/equipment/EQP-1/status", json={"status": "IN_USE"})
    assert r.status_code == 503
    assert r.json()["error"]["details"] == {"equipment_status_updated": True, "history_write_outcome": "unknown"}


# =============================================================================================
# KS11 — race characterization (A09): columns moved AFTER the validated read
# =============================================================================================


@pytest.mark.asyncio
async def test_ks11_columns_moved_between_read_and_write_are_not_detected() -> None:
    """Characterizes a DISCLOSED limit, not a guarantee: the targeted write
    uses the column of the validated read; a concurrent move before the write
    lands it on another column. No retry or compensation follows."""
    backend, repo, service = setup([eq_row(serial="SN-9")])

    def move(tab, cells):
        if tab == EQH and backend.tabs[EQ][0][0] != "equipment_status":
            backend.tabs[EQ] = reorder(backend.tabs[EQ], ["equipment_status", *[h for h in EQ_HEADER if h != "equipment_status"]])

    backend.before_values_get = move
    await service.change_status("EQP-1", S.MAINTENANCE, None, None)
    row = dict(zip(backend.tabs[EQ][0], backend.tabs[EQ][1]))
    assert row["serial_no"] == "MAINTENANCE" and row["equipment_status"] == "READY"
    assert [w["kind"] for w in backend.write_log] == ["batchUpdate", "append"]


# =============================================================================================
# KS12 — request counts (fake transport; not live cost)
# =============================================================================================


@pytest.mark.asyncio
async def test_ks12_request_counts_per_method_and_per_operation() -> None:
    backend, repo, service = setup([eq_row()], history=[h_row()])
    await ids(service)
    await service.list_status_history("EQP-1")

    async def measure(coro):
        backend.requests.clear()
        await coro
        gets = [t for m, k, t in backend.requests if m == "get" and k == "values"]
        posts = [k for m, k, _ in backend.requests if m == "post"]
        return gets, posts, [r for r in backend.requests if r[1] == "metadata"]

    assert await measure(repo.read_equipment_master()) == ([EQ], [], [])
    assert await measure(repo.get_equipment_validated("EQP-1")) == ([EQ], [], [])
    assert await measure(repo.list_equipment_status_history_validated("EQP-1")) == ([EQH], [], [])
    assert await measure(ids(service)) == ([EQ], [], [])
    assert await measure(service.get_equipment("EQP-1")) == ([EQ], [], [])
    assert await measure(service.list_status_history("EQP-1")) == ([EQ, EQH], [], [])
    assert await measure(require_asset_exists(repo, AssetType.EQUIPMENT, "EQP-1")) == ([EQ], [], [])
    assert await measure(service.change_status("EQP-1", S.IN_USE, None, None)) == ([EQ, EQH], ["batchUpdate", "append"], [])


# =============================================================================================
# KS13 — history policy (4.5, DEC-K7(a), DEC-K9(b))
# =============================================================================================


@pytest.mark.asyncio
async def test_ks13_history_issue_keys_counts_and_preserved_legacy_behaviour() -> None:
    _, _, service = setup([eq_row()], history=[h_row(code=""), h_row(hid="ESTH-0002", code="ready"),
                                               h_row(hid="ESTH-0003", code="Broken"), h_row(eid="EQP-9", code="")])
    err = await api_error(service.list_status_history("EQP-1"))
    assert err.details == {"issue_counts": {"BLANK_STATUS": 1, "UNRECOGNIZED_STATUS": 2}}

    _, _, service = setup([eq_row()], history=[h_row(hid="", start="2026-01-03T00:00:00+00:00"),
                                               h_row(hid="ESTH-0001", code="IN_USE", start="2026-01-02T00:00:00+00:00"),
                                               h_row(hid="ESTH-0001", code="MAINTENANCE", start="2026-01-02T00:00:00+00:00"),
                                               h_row(hid="ESTH-0009", start="03/01/2026")])
    entries = await service.list_status_history("EQP-1")
    assert [(e.history_id, e.status.value) for e in entries] == [
        ("ESTH-0009", "READY"), ("ESTH-0001", "IN_USE"), ("ESTH-0001", "MAINTENANCE"), ("", "READY")]
    assert entries[0].changed_at == datetime(1970, 1, 1, tzinfo=timezone.utc)  # unparseable -> epoch (legacy)


@pytest.mark.asyncio
async def test_ks13_mixed_naive_and_aware_timestamps_are_a_coded_error_without_reinterpretation() -> None:
    _, _, service = setup([eq_row()], history=[h_row(start="2026-01-02"), h_row(hid="ESTH-0002", start="2026-01-04"),
                                               h_row(hid="ESTH-0003", start=TS)])
    err = await api_error(service.list_status_history("EQP-1"))
    assert (err.status_code, err.code, err.details) == (500, "EQUIPMENT_STATUS_HISTORY_DATA_INVALID",
                                                        {"issue_counts": {"MIXED_TIMEZONE_TIMESTAMP": 2}})
    _, _, service = setup([eq_row()], history=[h_row(start="2026-01-03"), h_row(hid="ESTH-0002", start="2026-01-02")])
    entries = await service.list_status_history("EQP-1")  # all naive: unchanged, ordered, not reinterpreted
    assert [e.history_id for e in entries] == ["ESTH-0002", "ESTH-0001"]
    assert all(e.changed_at.tzinfo is None for e in entries)


# =============================================================================================
# KS14 — mock / Sheets parity
# =============================================================================================


def _sheet_rows_from_mock(mock: MockRepository) -> list[list[str]]:
    return [eq_row(eid=e.equipment_id, code=e.equipment_code, name=e.name, etype=e.category.value,
                   serial=e.serial_number or "", status=e.operational_status.value)
            for e in mock._equipment.values()]


@pytest.mark.asyncio
async def test_ks14_mock_and_sheets_agree_on_shared_scenarios() -> None:
    mock = MockRepository()
    m_service = EquipmentService(mock)
    _, _, s_service = setup(_sheet_rows_from_mock(mock))

    def view(page):
        return [(e.equipment_id, e.equipment_code, e.name, e.category, e.serial_number, e.operational_status)
                for e in page.items]

    for q in (None, "กลึง1", "LATHE01", "eqp 0002", "-"):
        assert view(await m_service.list_equipment(q, None, PageParams())) == view(await s_service.list_equipment(q, None, PageParams())), q
    for service in (m_service, s_service):
        changed = await service.change_status("EQP-0002", S.MAINTENANCE, "0007", "u-1")
        assert (changed.equipment_id, changed.operational_status) == ("EQP-0002", S.MAINTENANCE)
        history = await service.list_status_history("EQP-0002")
        assert [(h.equipment_id, h.status, h.reason, h.changed_by) for h in history][-1:] == [("EQP-0002", S.MAINTENANCE, "0007", "u-1")]
        for blank in ("", "  "):
            assert (await api_error(service.get_equipment(blank))).code == "EQUIPMENT_NOT_FOUND"
        assert (await api_error(service.get_equipment("NOPE"))).code == "EQUIPMENT_NOT_FOUND"
    # Documented difference: Sheets has no updated_at column (epoch); the mock records now.
    assert (await s_service.get_equipment("EQP-0002")).updated_at == datetime(1970, 1, 1, tzinfo=timezone.utc)


# =============================================================================================
# KS15 — pure predicate cross-checked against the installed library (samples only)
# =============================================================================================

SAMPLES = ["0012", "12", " 0012 ", "1e3", "1E3", "1,234", "๐๑๒", "inf", "-inf", "nan", "NaN", "Infinity", "1_000", "0x10",
           "1.", ".5", "+5", "-0", "١٢", "EQP-0001", "0012A", "A-0012", "", " ", "TRUE", "2026-01-01", "1/2", "12:30",
           "5%", "$5", "1 000", "１２"]


def test_ks15_numeric_part_agrees_with_installed_numericise_on_samples() -> None:
    """Agreement on these samples is not proof for all inputs; the major
    version check detects a library change, it does not guarantee behaviour."""
    from gspread.utils import numericise

    from app.domain.equipment_rules import _numeric_hazard

    assert gspread.__version__.split(".")[0] == "6"
    for value in SAMPLES:
        assert _numeric_hazard(value) == (numericise(value, False, "", False) != value), value


# =============================================================================================
# KS16 — F-E padded id and the existing picker trimming
# =============================================================================================


@pytest.mark.asyncio
async def test_ks16_fixture_e_padded_id() -> None:
    backend, repo, service = setup([eq_row(eid=" 0012 ")])
    assert [i[0] for i in await ids(service)] == [" 0012 "]
    assert (await service.get_equipment(" 0012 ")).equipment_id == " 0012 "
    await service.change_status(" 0012 ", S.IN_USE, None, None)
    assert backend.tabs[EQ][1][0] == " 0012 "
    assert known_text_hazard(" 0012 ")
    err = await api_error(require_asset_for_new_work(repo, AssetType.EQUIPMENT, " 0012 "))
    assert err.code == "EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK"
    # PartInstanceDetailPage sends asset_id.trim() (existing, unchanged): "0012" is a different id.
    assert (await api_error(require_asset_for_new_work(repo, AssetType.EQUIPMENT, "0012"))).code == "EQUIPMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_ks_legacy_status_change_unchanged_still_rewrites_whole_row() -> None:
    """The legacy repository method is kept unchanged (only routes moved off
    it): it still sends the whole-row PUT."""
    backend, repo, _ = setup([eq_row(model_name="0250")])
    await repo.change_equipment_status("EQP-1", S.IN_USE, None, None)
    assert len(backend.puts()) == 1 and backend.tabs[EQ][1][5] == "250"
