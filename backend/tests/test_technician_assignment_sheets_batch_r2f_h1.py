"""R2 Batch R2f-h1 — V2 technician assignment over Google Sheets, exercised with
the REAL installed gspread client on the FAKE HTTP transport (an emulation, not
live Google Sheets: no credentials, network or live workbook). Every row is
SYNTHETIC; the additive V2 columns do NOT exist live.

Proves at the transport (Option A — the SAME existing tabs):
- before the live columns exist (legacy headers, the CURRENT live state) every
  legacy read / write behaves as before, and every V2 path fails closed with
  ZERO writes (governance 12);
- a V2 set is ONE append request whose values follow the live header order;
  legacy rows on the same tab stay byte-identical; V2 rows carry a blank
  user_id and blank legacy status cells, so the unchanged legacy readers treat
  them as inactive (governance 11, 13, 14);
- the marker survives a legacy full-row job update (close) (governance 2);
- live TEST V2 fails closed (governance 18).
"""
from __future__ import annotations

import copy
import random
import re
import uuid
from urllib.parse import unquote

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.asset import AssetType
from app.domain.meter_service import MeterService
from app.domain.personnel import PERSONNEL_MASTER_TARGET_COLUMNS
from app.domain.pm_service import PmService
from app.domain.repair import RepairSourceType
from app.domain.repair_service import RepairService
from app.domain.technician_assignment import REPAIR, TechnicianAssignmentService, cutover_from_settings
from app.errors import ApiError
from app.repositories.base import RepositorySchemaError
from app.repositories.google_sheets import schemas
from tests.test_fleet_status_summary_sheets_batch7b2 import _FakeResponse, _repo
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_relationship_read_sheets_batch_r2f_a import ACCOUNT_HEADER, TECH_HEADER, RangeBackend, _account_row, \
    _tech_row
from tests.test_vehicle_text_preservation_sheets_batch7h2 import _emulate_user_entered

API = "/api/v1"
T1, T2 = "TEC-SYN-1", "0042"  # "0042" proves exact text survives (no numeric coercion)
U1, U2 = "USR-SYN-1", "USR-SYN-2"
LEGACY_JOB, V2_JOB, OTHER_V2 = "RPR-0001", "RPR-0002", "RPR-0003"
TS = "2026-01-05T08:00:00+00:00"
ORDER_LEGACY = list(schemas.REPAIR_SHEET.required_headers)
ORDER_V2 = list(schemas.REPAIR_ORDER_V2_SHEET.required_headers)
ASSIGN_LEGACY = list(schemas.REPAIR_ASSIGNMENT_SHEET.required_headers)
ASSIGN_V2 = list(schemas.REPAIR_ASSIGNMENT_V2_SHEET.required_headers)


class V2Backend(RangeBackend):
    """RangeBackend + every row of an append applied and logged (a V2 set is
    one request with several rows) + the single-row PUT `update_row` uses."""

    def request(self, method, url, json=None, params=None, data=None, files=None, headers=None,  # noqa: A002
                timeout=None):
        m = method.lower()
        values = self._VALUES_RE.search(url)
        if values and m in ("post", "put"):
            rng = unquote(values.group(2))
            appending = rng.endswith(":append")
            rng = rng[: -len(":append")] if appending else rng
            tab = rng.partition("!")[0].strip("'")
            rows = [list(r) for r in (json or {}).get("values", [])]
            kind = "append" if appending else "update"
            self.write_log.append({"kind": kind, "tab": tab, "range": rng, "rows": rows,
                                   "valueInputOption": (params or {}).get("valueInputOption")})
            self.requests.append(("post", kind, tab))
            mode = self.fail.get("append") if appending else None
            if mode in ("reject", "server_error"):
                code = 400 if mode == "reject" else 503
                return _FakeResponse({"error": {"code": code, "message": "simulated", "status": "X"}}, code)
            start = len(self.tabs[tab]) + 1 if appending else int(re.search(r"[A-Z]+(\d+)", rng.partition("!")[2])
                                                                  .group(1))
            for offset, row in enumerate(rows):
                for col, raw in enumerate(row, start=1):
                    self._apply(tab, start + offset, col, str(raw))
            return self._finish("append" if appending else "batchUpdate",
                                {"spreadsheetId": "fake", "updates": {"updatedRange": rng}, "updatedRange": rng})
        return super().request(method, url, json=json, params=params, data=data, files=files, headers=headers,
                               timeout=timeout)

    def appends(self, tab: str) -> list[dict]:
        return [w for w in self.write_log if w["kind"] == "append" and w["tab"] == tab]


def _order_row(header: list[str], job_id: str, **cells: str) -> list[str]:
    values = {"repair_id": job_id, "asset_type": "VEHICLE", "asset_id": "VEH-SYN-1", "source_type": "MANUAL",
              "status": "OPEN", "opened_at": TS, "opened_by": "dev-user", **cells}
    return [values.get(h, "") for h in header]


def _legacy_assignment(header: list[str], rid: str, job_id: str, user_id: str, *, active: str = "TRUE",
                       ended: str = "") -> list[str]:
    values = {"repair_assignment_id": rid, "repair_id": job_id, "user_id": user_id, "assignment_role": "PRIMARY",
              "assigned_at": TS, "assigned_by_user_id": "dev-user", "ended_at": ended, "active_status": active}
    return [values.get(h, "") for h in header]


def _backend(*, order_header=None, assign_header=None, scramble: bool = False, test_job: bool = False) -> V2Backend:
    order_header = list(order_header or ORDER_V2)
    assign_header = list(assign_header or ASSIGN_V2)
    if scramble:
        random.Random(7).shuffle(assign_header)
    v2 = {"assignment_model": "TECHNICIAN_V2", "is_test_data": "TRUE" if test_job else "FALSE",
          "test_batch_id": "SYN-BATCH" if test_job else ""}
    orders = [order_header, _order_row(order_header, LEGACY_JOB)]
    if "assignment_model" in order_header:
        orders += [_order_row(order_header, V2_JOB, **v2), _order_row(order_header, OTHER_V2, **v2)]
    people = [person("P-1", technician_id=T1, user_id=U1), person("P-2", technician_id=T2, user_id=U2)]
    tabs = {
        "repair_order": orders,
        "repair_assignment": [assign_header,
                              _legacy_assignment(assign_header, "RASG-0001", LEGACY_JOB, "u-legacy-old",
                                                 active="FALSE", ended=TS),
                              _legacy_assignment(assign_header, "RASG-0002", LEGACY_JOB, "u-legacy")],
        "repair_action": [list(schemas.REPAIR_ACTION_SHEET.required_headers)],
        "repair_part": [list(schemas.REPAIR_PART_SHEET.required_headers)],
        "material_request": [list(schemas.MATERIAL_REQUEST_SHEET.required_headers)],
        "personnel_master": [list(PERSONNEL_MASTER_TARGET_COLUMNS),
                             *([p.get(h, "") for h in PERSONNEL_MASTER_TARGET_COLUMNS] for p in people)],
        "technician_master": [list(TECH_HEADER), _tech_row(T1), _tech_row(T2)],
        "user_account": [list(ACCOUNT_HEADER), _account_row(U1), _account_row(U2)],
        "pm_work_order": [list(schemas.PM_WORK_ORDER_SHEET.required_headers)],
        "pm_work_assignment": [list(schemas.PM_WORK_ASSIGNMENT_SHEET.required_headers)],
    }
    return V2Backend(tabs)


def _settings(context: str | None = "REAL", *, v2: bool = False) -> Settings:
    values: dict = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake-sheet-id",
                    "google_application_credentials": "fake.json", "registry_test_batch_id": "SYN-BATCH",
                    "technician_assignment_v2_enabled": v2}
    if context:
        values["registry_data_context"] = context
    return Settings(**values)


def _service(repo, context: str | None = "REAL") -> TechnicianAssignmentService:
    return TechnicianAssignmentService(repo, cutover_from_settings(_settings(context)))


def body(primary: str, *collaborators: str, expected: tuple[str, ...] | None = None) -> dict:
    return {"primary_technician_id": primary, "collaborator_technician_ids": list(collaborators),
            "expected_current": None if expected is None else {
                "primary_technician_id": expected[0], "collaborator_technician_ids": list(expected[1:])}}


async def assign(repo, payload: dict, job_id: str = V2_JOB, **kw):
    return await _service(repo, **kw).assign(REPAIR, job_id, payload, request_id=str(uuid.uuid4()),
                                             user_id="dev-user")


async def http(method: str, path: str, repo, *, role: str = "TECHNICIAN", user: str | None = None, json=None,
               settings: Settings | None = None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    chosen = settings or _settings()
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    headers = {"X-Dev-Role": role, "X-Request-Id": str(uuid.uuid4())}
    if user is not None:
        headers["X-Dev-User-Id"] = user
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _rows(backend: V2Backend, tab: str) -> list[dict[str, str]]:
    header, *rows = backend.tabs[tab]
    return [dict(zip(header, [*r, *[""] * (len(header) - len(r))])) for r in rows]


# ---------------------------------------------------------------------------
# The CURRENT live state: legacy headers only (governance 12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_s01_missing_v2_assignment_columns_fail_closed_with_zero_writes() -> None:
    backend = _backend(assign_header=ASSIGN_LEGACY)
    before = copy.deepcopy(backend.tabs)
    with pytest.raises(ApiError) as exc:
        await assign(_repo(backend), body(T1))
    assert exc.value.code == "TECHNICIAN_ASSIGNMENT_SCHEMA_INVALID"
    assert set(exc.value.details["headers"]) == {"assignee_type", "assignee_id", "request_id", "request_fingerprint",
                                                 "reason_th", "is_test_data", "test_batch_id"}
    assert backend.write_log == [] and backend.tabs == before


@pytest.mark.asyncio
async def test_r2fh1_s02_go_live_on_without_job_columns_fails_closed_before_any_write() -> None:
    backend = _backend(order_header=ORDER_LEGACY)
    repo = _repo(backend)
    before = copy.deepcopy(backend.tabs)
    cutover = cutover_from_settings(_settings(v2=True))
    service = RepairService(repo, MeterService(repo), assignment_cutover=cutover)
    with pytest.raises(ApiError) as exc:
        await service.create_repair(AssetType.VEHICLE, "VEH-SYN-1", RepairSourceType.MANUAL, None, None, None, None,
                                    "dev-user")
    assert exc.value.code == "TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID"
    pm = PmService(repo, MeterService(repo), assignment_cutover=cutover)
    with pytest.raises(ApiError) as exc:
        await pm.open_work_order(AssetType.VEHICLE, "VEH-SYN-1", "PLAN-SYN", None, "dev-user", None)
    assert exc.value.code == "TECHNICIAN_ASSIGNMENT_JOB_SCHEMA_INVALID"
    assert backend.write_log == [] and backend.writes == [] and backend.tabs == before
    with pytest.raises(RepositorySchemaError):
        await repo.verify_work_order_v2_schema("PM")


@pytest.mark.asyncio
async def test_r2fh1_s03_legacy_paths_are_unchanged_on_the_legacy_headers() -> None:
    backend = _backend(order_header=ORDER_LEGACY, assign_header=ASSIGN_LEGACY)
    repo = _repo(backend)
    service = RepairService(repo, MeterService(repo), assignment_cutover=cutover_from_settings(_settings()))
    assert await service.get_active_assignment(LEGACY_JOB) == ("u-legacy", [])
    job = (await service.get_repair(LEGACY_JOB)).repair
    assert (job.assignment_model, job.is_test_data, job.test_batch_id) == ("", "", "")
    await service.authorize_recording(LEGACY_JOB, _ctx("u-legacy"), "can_manage_repair", "x")
    created = await repo.create_repair(AssetType.VEHICLE, "VEH-SYN-1", RepairSourceType.MANUAL, None, None, None,
                                       None, "dev-user")
    assert created.assignment_model == ""
    assert [w["kind"] for w in backend.write_log] == ["append"] and len(backend.write_log[0]["rows"][0]) == len(
        ORDER_LEGACY)


def _ctx(user: str | None, *caps: str):
    from app.context import RequestContext

    return RequestContext(request_id=str(uuid.uuid4()), user_id=user, is_dev_auth=True, capabilities=frozenset(caps))


# ---------------------------------------------------------------------------
# Extended headers present: ONE append, header order, legacy byte-equality
# (governance 11, 13, 14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("scramble", [False, True])
async def test_r2fh1_s04_one_append_in_live_header_order_and_legacy_rows_byte_identical(scramble) -> None:
    backend = _backend(scramble=scramble)
    legacy_before = copy.deepcopy([r for r in backend.tabs["repair_assignment"]])
    outcome = await assign(_repo(backend), body(T1, T2))
    assert outcome.changed
    appends = backend.appends("repair_assignment")
    assert [w["kind"] for w in backend.write_log] == ["append"] and len(appends) == 1
    assert len(appends[0]["rows"]) == 2 and appends[0]["valueInputOption"] == "USER_ENTERED"
    header = backend.tabs["repair_assignment"][0]
    assert backend.tabs["repair_assignment"][: len(legacy_before)] == legacy_before
    written = _rows(backend, "repair_assignment")[len(legacy_before) - 1:]
    assert [(r["assignment_role"], r["assignee_id"]) for r in written] == [("PRIMARY", T1), ("COLLABORATOR", T2)]
    for row in written:
        assert (row["user_id"], row["ended_at"], row["active_status"], row["note_th"]) == ("", "", "", "")
        assert (row["assignee_type"], row["repair_id"], row["is_test_data"]) == ("TECHNICIAN", V2_JOB, "FALSE")
    # Values were sent in the LIVE header order, ids as forced text.
    sent = dict(zip(header, appends[0]["rows"][1]))
    assert sent["assignee_id"] == "'0042" and sent["repair_id"] == "'" + V2_JOB
    assert _emulate_user_entered(sent["assignee_id"]) == "0042"


@pytest.mark.asyncio
async def test_r2fh1_s05_unchanged_legacy_readers_treat_v2_rows_as_inactive() -> None:
    backend = _backend()
    repo = _repo(backend)
    await assign(repo, body(T1))
    service = RepairService(repo, MeterService(repo))
    assert await service.get_active_assignment(V2_JOB) == (None, [])  # blank user_id + blank status: inactive
    assert await service.get_active_assignment(LEGACY_JOB) == ("u-legacy", [])
    waiting, _ = await repo.list_repairs(None, None, None, _page(), unassigned_only=True)
    assert [r.repair_id for r in waiting] == []  # legacy job assigned; V2 jobs never in the legacy queue
    mine, _ = await repo.list_repairs(None, None, None, _page(), assigned_to="")
    assert mine == []  # a blank user_id never matches


def _page():
    from app.domain.common import PageParams

    return PageParams(page=1, page_size=50)


@pytest.mark.asyncio
async def test_r2fh1_s06_legacy_assign_on_a_mixed_tab_never_touches_v2_rows() -> None:
    backend = _backend()
    repo = _repo(backend)
    await assign(repo, body(T1))
    v2_snapshot = [r for r in backend.tabs["repair_assignment"] if "TECHNICIAN" in r]
    service = RepairService(repo, MeterService(repo))
    await service.assign(LEGACY_JOB, "u-legacy-new", [], assigned_by="dev-user")
    assert [r for r in backend.tabs["repair_assignment"] if "TECHNICIAN" in r] == v2_snapshot
    legacy_ids = [r["repair_assignment_id"] for r in _rows(backend, "repair_assignment") if not r["assignee_type"]]
    assert legacy_ids == ["RASG-0001", "RASG-0002", "RASG-0003"]
    with pytest.raises(ApiError) as exc:
        await service.assign(V2_JOB, "u-x", [], assigned_by="dev-user")
    assert exc.value.code == "ASSIGNMENT_MODEL_MISMATCH"


# ---------------------------------------------------------------------------
# Marker integrity; live TEST; end-to-end recording (governance 2, 15, 18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_s07_the_marker_survives_a_legacy_full_row_job_update() -> None:
    backend = _backend()
    repo = _repo(backend)
    await repo.close_repair(V2_JOB, closed_by="dev-user", close_note="ปิด", closed_snapshot_id="MS-SYN-1")
    assert [w["kind"] for w in backend.write_log] == ["update"]
    row = {r["repair_id"]: r for r in _rows(backend, "repair_order")}[V2_JOB]
    assert (row["status"], row["assignment_model"], row["is_test_data"], row["test_batch_id"]) == (
        "CLOSED", "TECHNICIAN_V2", "FALSE", "")


@pytest.mark.asyncio
async def test_r2fh1_s08_go_live_create_writes_the_marker_by_the_validated_header() -> None:
    backend = _backend()
    repo = _repo(backend)
    marker = {"assignment_model": "TECHNICIAN_V2", "is_test_data": "FALSE", "test_batch_id": ""}
    created = await repo.create_repair(AssetType.VEHICLE, "VEH-SYN-1", RepairSourceType.MANUAL, None, None, None,
                                       None, "dev-user", assignment_marker=marker)
    assert created.assignment_model == "TECHNICIAN_V2"
    row = {r["repair_id"]: r for r in _rows(backend, "repair_order")}[created.repair_id]
    assert (row["assignment_model"], row["is_test_data"], row["primary_technician"]) == ("TECHNICIAN_V2", "FALSE", "")


@pytest.mark.asyncio
async def test_r2fh1_s09_live_test_v2_fails_closed_with_zero_writes() -> None:
    backend = _backend(test_job=True)
    before = copy.deepcopy(backend.tabs)
    with pytest.raises(ApiError) as exc:
        await assign(_repo(backend), body(T1), context="TEST")
    assert exc.value.code == "TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED"
    response = await http("POST", f"{API}/repairs/{V2_JOB}/technician-assignments", _repo(backend),
                          role="MAINTENANCE", json=body(T1), settings=_settings("TEST"))
    assert (response.status_code, response.json()["error"]["code"]) == (409,
                                                                       "TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED")
    assert backend.write_log == [] and backend.tabs == before


@pytest.mark.asyncio
async def test_r2fh1_s10_end_to_end_assign_and_record_in_real() -> None:
    backend = _backend()
    repo = _repo(backend)
    written = await http("POST", f"{API}/repairs/{V2_JOB}/technician-assignments", repo, role="MAINTENANCE",
                         json=body(T2))
    assert written.status_code == 200, written.text
    read = (await http("GET", f"{API}/repairs/{V2_JOB}/technician-assignments", _repo(backend))).json()
    assert (read["status"], read["current"]["primary_technician_id"]) == ("VALID", T2)
    action = {"action_text": "ทำงาน"}
    assert (await http("POST", f"{API}/repairs/{V2_JOB}/actions", _repo(backend), user=U2,
                       json=action)).status_code == 200
    assert (await http("POST", f"{API}/repairs/{V2_JOB}/actions", _repo(backend), user=U1,
                       json=action)).status_code == 403
    assert (await http("POST", f"{API}/repairs/{OTHER_V2}/actions", _repo(backend), user=U2,
                       json=action)).status_code == 403
    # Legacy job: unchanged opaque compare.
    assert (await http("POST", f"{API}/repairs/{LEGACY_JOB}/actions", _repo(backend), user="u-legacy",
                       json=action)).status_code == 200
    assert (await http("POST", f"{API}/repairs/{LEGACY_JOB}/actions", _repo(backend), user=U2,
                       json=action)).status_code == 403


# ---------------------------------------------------------------------------
# H1-01 — a set damaged on the sheet (a member row lost after a successful
# write, or deleted by hand) is proven incomplete from the stored rows alone.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh1_s11_a_member_row_lost_on_the_sheet_fails_closed() -> None:
    backend = _backend()
    await assign(_repo(backend), body(T1, T2))
    header, *rows = backend.tabs["repair_assignment"]
    collaborator = header.index("assignment_role")
    backend.tabs["repair_assignment"] = [header, *(r for r in rows if r[collaborator] != "COLLABORATOR")]
    before = copy.deepcopy(backend.tabs)
    for call in (_service(_repo(backend)).read(REPAIR, V2_JOB),
                 assign(_repo(backend), body(T2, expected=(T1,)))):
        with pytest.raises(ApiError) as exc:
            await call
        assert (exc.value.code, exc.value.details["issues"]) == ("TECHNICIAN_ASSIGNMENT_DATA_INVALID",
                                                                 {"SET_INCOMPLETE": 1})
    response = await http("POST", f"{API}/repairs/{V2_JOB}/actions", _repo(backend), user=U1,
                          json={"action_text": "ทำงาน"})
    assert (response.status_code, response.json()["error"]["code"]) == (500, "TECHNICIAN_ASSIGNMENT_DATA_INVALID")
    assert backend.tabs == before and len(backend.write_log) == 1  # only the original append
