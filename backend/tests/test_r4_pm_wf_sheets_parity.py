"""R4 PM Workflow — Google Sheets TEST persistence parity (corrected plan C-2..C-6,
D-1 / D-2b / D-3a/a1 / D-4a / D-5), exercised with the REAL installed gspread
client on a FAKE HTTP transport (an emulation, not live Google Sheets: no
credentials, network or live workbook). Every row is SYNTHETIC.

Acceptance rows covered here (column F of the matrix): SH-01..SH-15 as far as a
fake transport can prove them. Live (L) and E2E (E) rows are NOT RUN here; see
`test_r4_pm_wf_sheets_live.py`."""
from __future__ import annotations

import copy
import json
import re
from datetime import timedelta
from urllib.parse import unquote

import gspread
import pytest
import requests
from fastapi import HTTPException

from app.config import Settings
from app.domain.asset import AssetType
from app.domain.attachment import AttachmentPurpose
from app.domain.meter_service import MeterService
from app.domain.personnel import PERSONNEL_MASTER_TARGET_COLUMNS
from app.domain.pm import (
    PmItemContractDisposition as Disposition,
)
from app.domain.pm import (
    PmWorkOrderStatus as S,
)
from app.domain.pm import (
    build_pm_outstanding_item,
)
from app.domain.pm_service import PmService
from app.domain.technician_assignment import (
    PM,
    TechnicianAssignmentService,
    cutover_from_settings,
    v2_job_marker,
)
from app.errors import ApiError
from app.repositories.base import (
    REFERENCE_SCOPE_REAL,
    REFERENCE_SCOPE_TEST,
    RepositoryError,
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
    RepositorySchemaError,
)
from app.repositories.google_sheets import schemas
from app.repositories.google_sheets.repository import GoogleSheetsRepository
from tests.pm_e01_support import (
    CHECK,
    MANAGER_ID,
    OTHER,
    WAIT_PARTS,
    ctx,
    manager,
    rid,
)
from tests.pm_e01_support import (
    close as mock_close,
)
from tests.pm_e01_support import (
    pm_service as mock_pm_service,
)
from tests.pm_e01_support import (
    repo_with as mock_repo_with,
)
from tests.pm_e01_support import (
    save as mock_save,
)
from tests.pm_e01_support import (
    scope_of as mock_scope_of,
)
from tests.pm_e01_support import (
    start as mock_start,
)
from tests.pm_e01_support import (
    submit as mock_submit,
)
from tests.pm_e01_support import (
    v2_job as mock_v2_job,
)
from tests.test_fleet_status_summary_sheets_batch7b2 import _FakeResponse
from tests.test_relationship_read_batch_r2f_a import person
from tests.test_relationship_read_sheets_batch_r2f_a import (
    ACCOUNT_HEADER,
    TECH_HEADER,
    _account_row,
    _tech_row,
)
from tests.test_technician_assignment_sheets_batch_r2f_h1 import (
    T1,
    T2,
    U1,
    U2,
    V2Backend,
    body,
)

BATCH = "SYN-BATCH"
OTHER_BATCH = "SYN-OTHER-BATCH"
VEHICLE = "VEH-SYN-1"
PLAN, REVISION = "PMP-SYN-1", "PMREV-SYN-1"
TASKS = ("PMT-SYN-1", "PMT-SYN-2", "PMT-SYN-3")
TS = "2026-01-01T00:00:00+00:00"
PM_TABS = (schemas.PM_WORK_SCOPE_SHEET, schemas.PM_USED_PART_SHEET, schemas.METER_SNAPSHOT_SHEET,
           schemas.METER_READING_SHEET, schemas.ATTACHMENT_SHEET, schemas.MATERIAL_REQUEST_SHEET,
           schemas.MATERIAL_REQUEST_LINE_SHEET, schemas.CURRENT_COUNTER_SHEET, schemas.LATEST_LOCATION_SHEET,
           schemas.VEHICLE_COMPONENT_SHEET, schemas.LOCATION_SNAPSHOT_SHEET)


# ---------------------------------------------------------------------------
# Fake transport + fixture
# ---------------------------------------------------------------------------


class ParityBackend(V2Backend):
    """V2Backend + ONE-SHOT failure injection per tab and write kind:
    `fail_next[(kind, tab)] = mode` with kind in {"append", "batchUpdate",
    "update"} and mode "reject" (HTTP 400, not applied), "server_error" (HTTP
    503, not applied) or "apply_then_timeout" (applied, response lost)."""

    def __init__(self, tabs):
        super().__init__(tabs)
        self.fail_next: dict[tuple[str, str], str] = {}

    def _target(self, method: str, url: str, json) -> tuple[str, str] | None:
        if method.lower() not in ("post", "put"):
            return None
        if url.endswith("/values:batchUpdate"):
            data = (json or {}).get("data", [])
            tab = unquote(data[0]["range"]).partition("!")[0].strip("'") if data else ""
            return "batchUpdate", tab
        values = self._VALUES_RE.search(url)
        if values:
            rng = unquote(values.group(2))
            kind = "append" if rng.endswith(":append") else "update"
            return kind, rng.partition("!")[0].strip("'")
        return None

    def request(self, method, url, json=None, params=None, data=None, files=None, headers=None,
                timeout=None):
        target = self._target(method, url, json)
        mode = self.fail_next.pop(target, None) if target else None
        if mode in ("reject", "server_error"):
            self.write_log.append({"kind": "refused", "target": target})
            code = 400 if mode == "reject" else 503
            return _FakeResponse({"error": {"code": code, "message": "simulated", "status": "X"}}, code)
        response = super().request(method, url, json=json, params=params, data=data, files=files, headers=headers,
                                   timeout=timeout)
        if mode == "apply_then_timeout":
            raise requests.exceptions.ReadTimeout("simulated lost response")
        return response

    def write_count(self) -> int:
        return len([w for w in self.write_log if w["kind"] != "refused"])

    def rows(self, tab: str) -> list[dict[str, str]]:
        header, *rows = self.tabs[tab]
        return [dict(zip(header, [*map(str, r), *[""] * (len(header) - len(r))])) for r in rows if any(r)]


def _row(header: list[str], **values) -> list[str]:
    return [str(values.get(h, "")) for h in header]


def _scoped(header: list[str], rows: list[list[str]], scope: tuple[str, str] | None) -> None:
    """Append the two scope columns to `header` and every row (in place)."""
    header += ["is_test_data", "test_batch_id"]
    for row in rows:
        row += [""] * (len(header) - 2 - len(row)) + list(scope or ("", ""))


def build(context: str = "TEST", *, masters_scoped: bool = True, outcome_columns: bool = True,
          transition_tab: bool = True, outstanding_tab: bool = True, plan_scope: dict | None = None,
          components: bool = False) -> ParityBackend:
    """A synthetic workbook carrying every tab the V2 PM flow touches.

    `masters_scoped`: technician_master / user_account carry both scope columns
    (D-1, every row classified for `context`). `plan_scope`: None = the four PM
    master tabs WITHOUT scope columns (today's live state); otherwise a dict
    {plan_id: (flag, batch)} adds plans with those scope cells (D-2b)."""
    test = context == "TEST"
    flag, batch = ("TRUE", BATCH) if test else ("FALSE", "")
    people = [person("P-1", technician_id=T1, user_id=U1, test=test, batch=batch),
              person("P-2", technician_id=T2, user_id=U2, test=test, batch=batch)]
    tech = [list(TECH_HEADER), _tech_row(T1), _tech_row(T2)]
    account = [list(ACCOUNT_HEADER), _account_row(U1), _account_row(U2)]
    if masters_scoped:
        _scoped(tech[0], tech[1:], (flag, batch))
        _scoped(account[0], account[1:], (flag, batch))
    result_schema = schemas.PM_WORK_RESULT_OUTCOME_SHEET if outcome_columns else schemas.PM_WORK_RESULT_SHEET
    tabs: dict[str, list[list[str]]] = {
        "personnel_master": [list(PERSONNEL_MASTER_TARGET_COLUMNS),
                             *([p.get(h, "") for h in PERSONNEL_MASTER_TARGET_COLUMNS] for p in people)],
        "technician_master": tech,
        "user_account": account,
        "pm_work_order": [list(schemas.PM_WORK_ORDER_V2_SHEET.required_headers)],
        "pm_work_assignment": [list(schemas.PM_WORK_ASSIGNMENT_V2_SHEET.required_headers)],
        "pm_work_result": [list(result_schema.required_headers)],
    }
    if transition_tab:
        tabs["pm_work_order_transition"] = [list(schemas.PM_WORK_ORDER_TRANSITION_SHEET.required_headers)]
    if outstanding_tab:
        tabs["pm_outstanding_item"] = [list(schemas.PM_OUTSTANDING_ITEM_SHEET.required_headers)]
    for schema in PM_TABS:
        tabs[schema.tab_name] = [list(schema.required_headers)]
    plans = {PLAN: None} if plan_scope is None else dict(plan_scope)
    master_tabs = {s.tab_name: [list(s.required_headers)] for s in (
        schemas.PM_PLAN_SHEET, schemas.PM_TASK_REVISION_SHEET, schemas.PM_TASK_SHEET, schemas.PM_TASK_PART_SHEET)}
    for n, (plan_id, scope) in enumerate(plans.items(), start=1):
        revision_id = REVISION if plan_id == PLAN else f"PMREV-SYN-{plan_id}"
        rows = {
            "maintenance_plan": [_row(master_tabs["maintenance_plan"][0], pm_plan_id=plan_id, plan_code=f"SYN-{n}",
                                      asset_type="VEHICLE", name="แผนทดสอบ (synthetic)", created_at=TS,
                                      updated_at=TS)],
            "pm_task_revisions": [_row(master_tabs["pm_task_revisions"][0], revision_id=revision_id,
                                       pm_plan_id=plan_id, revision_number="1", effective_date="2026-01-01",
                                       created_at=TS)],
            "pm_task_master": [_row(master_tabs["pm_task_master"][0],
                                    pm_task_id=t if plan_id == PLAN else f"{t}-{plan_id}", revision_id=revision_id,
                                    sequence=str(i), group="A", description=f"งานทดสอบ {i} (synthetic)",
                                    trigger_type="ENGINE_HOUR", interval_value="250", interval_unit="HOUR")
                               for i, t in enumerate(TASKS, start=1)],
            "pm_task_part": [],
        }
        for tab, new in rows.items():
            master_tabs[tab].extend(new)
            if scope is not None:
                for row in new:
                    row += list(scope)
    if plan_scope is not None:
        for tab in master_tabs.values():
            tab[0] += ["is_test_data", "test_batch_id"]
    tabs |= master_tabs
    if components:
        component = schemas.VEHICLE_COMPONENT_SHEET.required_headers
        tabs["vehicle_component"].append(_row(list(component), component_id="CMP-SYN-1", vehicle_id=VEHICLE,
                                              component_role="CARRIER_ENGINE", label="SYN"))
        counter = list(schemas.CURRENT_COUNTER_SHEET.required_headers)
        tabs["current_counter"] += [_row(counter, vehicle_id=VEHICLE, component_id="CMP-SYN-1",
                                         counter_type="ENGINE_HOUR", value="1200"),
                                    _row(counter, vehicle_id=VEHICLE, counter_type="ODOMETER",
                                         value="54000")]
    return ParityBackend(tabs)


def settings(context: str = "TEST") -> Settings:
    from app.config import DataRepositoryMode
    return Settings(data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id="fake-sheet-id",
                    google_application_credentials="fake.json", registry_test_batch_id=BATCH,
                    registry_data_context=context)


def sheets_repo(backend: ParityBackend, context: str = "TEST") -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(settings(context))
    repo._client._gspread_client = gspread.Client(None, session=backend)  # type: ignore[attr-defined]
    return repo


def cutover(context: str = "TEST"):
    return cutover_from_settings(settings(context))


def service(repo, context: str = "TEST") -> PmService:
    return PmService(repo, MeterService(repo), assignment_cutover=cutover(context))


def ta(repo, context: str = "TEST") -> TechnicianAssignmentService:
    return TechnicianAssignmentService(repo, cutover(context))


async def new_job(repo, context: str = "TEST", *, plan: str = PLAN, revision: str = REVISION,
                  tasks=TASKS, assign_team: bool = True) -> str:
    """A V2 PM work order created through the real C1 proof + V2 marker path,
    then (optionally) assigned PRIMARY T1 / COLLABORATOR T2."""
    marker = await v2_job_marker(repo, PM, cutover(context))
    work_order = await repo.create_pm_work_order(AssetType.VEHICLE, VEHICLE, plan, revision, None, "dev-user", None,
                                                 scope_task_ids=list(tasks), assignment_marker=marker)
    if assign_team:
        await ta(repo, context).assign(PM, work_order.pm_work_order_id, body(T1, T2), request_id=rid(),
                                       user_id="dev-user")
    return work_order.pm_work_order_id


async def set_id(repo, job, context: str = "TEST") -> str:
    return (await ta(repo, context).read(PM, job)).state.current.set_id


async def save(svc, job, task, disposition=Disposition.PERFORMED, user=U1, **kw):
    if disposition == Disposition.PERFORMED:
        kw.setdefault("performed_actions", (CHECK,))
    else:
        kw.setdefault("reason_code", WAIT_PARTS)
    return await svc.record_item_outcome(job, task, disposition, ctx(user), **kw)


async def to_pending_review(repo, job, *, not_performed=(), svc=None, context: str = "TEST"):
    svc = svc or service(repo, context)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    for task in [t for t in TASKS if t not in not_performed] + list(not_performed):
        await save(svc, job, task, Disposition.NOT_PERFORMED if task in not_performed else Disposition.PERFORMED)
    await svc.submit_for_review(job, ctx(U1), request_id=rid(), expected_set_id=await set_id(repo, job, context))
    return svc


async def closed(repo, job, *, not_performed=(), context: str = "TEST"):
    svc = await to_pending_review(repo, job, not_performed=not_performed, context=context)
    return await svc.close_after_review(job, manager(), request_id=rid())


async def refused(awaitable) -> tuple[int, str]:
    with pytest.raises((ApiError, HTTPException)) as caught:
        await awaitable
    if isinstance(caught.value, HTTPException):  # the capability / membership dependency refusal
        return caught.value.status_code, "FORBIDDEN"
    return caught.value.status_code, caught.value.code


def snapshot(backend: ParityBackend):
    return copy.deepcopy(backend.tabs), backend.write_count()


# ---------------------------------------------------------------------------
# SH-01 creation, assignment and header validation (fail closed, zero writes)
# ---------------------------------------------------------------------------


async def test_sh01_v2_pm_create_and_assign_in_test_carry_the_server_scope() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    [order] = backend.rows("pm_work_order")
    assert (order["pm_work_order_id"], order["assignment_model"], order["is_test_data"], order["test_batch_id"]) == (
        job, "TECHNICIAN_V2", "TRUE", BATCH)
    assignments = backend.rows("pm_work_assignment")
    assert assignments and {(r["is_test_data"], r["test_batch_id"]) for r in assignments} == {("TRUE", BATCH)}
    assert [r["pm_task_id"] for r in backend.rows("pm_work_scope")] == list(TASKS)


@pytest.mark.parametrize("missing,step", [
    ("transition_tab", "start"),
    ("outcome_columns", "save"),
    ("outstanding_tab", "close"),
])
async def test_sh01_a_missing_declared_tab_or_column_fails_closed_with_zero_writes(missing, step) -> None:
    backend = build(**{missing: False}) if step == "start" else build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    if step == "save":
        await svc.start_work_order(job, ctx(U1), request_id=rid())
        backend.tabs["pm_work_result"] = [list(schemas.PM_WORK_RESULT_SHEET.required_headers)]
    if step == "close":
        await to_pending_review(repo, job, not_performed=(TASKS[-1],), svc=svc)
        del backend.tabs["pm_outstanding_item"]
    before = snapshot(backend)
    with pytest.raises((ApiError, RepositoryError)):
        if step == "start":
            await svc.start_work_order(job, ctx(U1), request_id=rid())
        elif step == "save":
            await save(svc, job, TASKS[0])
        else:
            await svc.close_after_review(job, manager(), request_id=rid())
    assert snapshot(backend) == before  # nothing at all was written


# ---------------------------------------------------------------------------
# SH-02 / SH-03 / SH-10 lifecycle parity with Mock, journal and replay
# ---------------------------------------------------------------------------


def _journal_shape(transitions) -> list[tuple[str, str, str]]:
    return [(t.action.value, t.from_status.value, t.to_status.value) for t in transitions]


async def test_sh02_full_lifecycle_matches_mock_journal_status_outcomes_and_outstanding() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    for task in TASKS[:-1]:
        await save(svc, job, task)
    await save(svc, job, TASKS[-1], Disposition.NOT_PERFORMED)
    sid = await set_id(repo, job)
    await svc.submit_for_review(job, ctx(U1), request_id=rid(), expected_set_id=sid)
    await svc.return_for_rework(job, manager(), request_id=rid(), reason="แก้ไข (synthetic)")
    await svc.submit_for_review(job, ctx(U1), request_id=rid(), expected_set_id=sid)
    sheets_closed = await svc.close_after_review(job, manager(), request_id=rid())

    mock = mock_repo_with()
    msvc = mock_pm_service(mock)
    mjob = await mock_v2_job(mock)
    await mock_start(msvc, mjob)
    mtasks = await mock_scope_of(mock, mjob)
    for task in mtasks[:-1]:
        await mock_save(msvc, mjob, task)
    await mock_save(msvc, mjob, mtasks[-1], Disposition.NOT_PERFORMED)
    await mock_submit(msvc, mock, mjob)
    await msvc.return_for_rework(mjob, manager(), request_id=rid(), reason="แก้ไข (synthetic)")
    await mock_submit(msvc, mock, mjob)
    mock_closed = await mock_close(msvc, mjob)

    assert sheets_closed.work_order.status == mock_closed.work_order.status == S.CLOSED
    assert _journal_shape(await repo.list_pm_work_order_transitions(job)) == _journal_shape(
        await mock.list_pm_work_order_transitions(mjob))
    sheets_outcomes = await repo.list_pm_item_outcomes(job)
    mock_outcomes = await mock.list_pm_item_outcomes(mjob)
    assert [(o.disposition, o.reason_code, o.performed_actions) for o in sheets_outcomes] == [
        (o.disposition, o.reason_code, o.performed_actions) for o in mock_outcomes]
    assert all(o.source_pm_work_result_id for o in sheets_outcomes)  # C-5: the service always supplies a source
    [item] = await repo.list_pm_outstanding_items(job)
    [mock_item] = await mock.list_pm_outstanding_items(mjob)
    assert (item.pm_task_id, item.origin_reason_code) == (TASKS[-1], mock_item.origin_reason_code)
    history = await svc.list_work_order_history(job, ctx(U1))
    assert [e.action.value for e in history] == ["START", "SUBMIT", "RETURN", "SUBMIT", "CLOSE"]
    assert backend.rows("pm_work_order")[0]["status"] == "CLOSED"


async def test_sh02_actor_and_eligibility_rules_hold_on_sheets() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    assert (await refused(svc.start_work_order(job, ctx("USR-SYN-STRANGER"), request_id=rid())))[0] == 403
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    await save(svc, job, TASKS[0])
    sid = await set_id(repo, job)
    assert (await refused(svc.submit_for_review(job, ctx(U2), request_id=rid(), expected_set_id=sid)))[0] == 403
    assert await refused(svc.cancel_work_order(job, manager(), request_id=rid(), reason="x")) == (
        409, "PM_CANCEL_NOT_ELIGIBLE")
    assert (await refused(svc.return_for_rework(job, manager(), request_id=rid(), reason="x")))[0] == 409


async def test_sh02_cancel_on_sheets_journals_once_and_replays() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    request_id = rid()
    first = await svc.cancel_work_order(job, manager(), request_id=request_id, reason="ยกเลิก (synthetic)")
    again = await svc.cancel_work_order(job, manager(), request_id=request_id, reason="ยกเลิก (synthetic)")
    assert first.work_order.status == again.work_order.status == S.CANCELLED
    assert [r["action"] for r in backend.rows("pm_work_order_transition")] == ["CANCEL"]
    assert await refused(svc.cancel_work_order(job, manager(), request_id=request_id, reason="อื่น")) == (
        409, "PM_E01_REQUEST_CONFLICT")


async def test_sh10_replay_by_request_id_creates_no_duplicate_rows_and_reuse_conflicts() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    start_id = rid()
    await svc.start_work_order(job, ctx(U1), request_id=start_id)
    before = snapshot(backend)
    replay = await svc.start_work_order(job, ctx(U1), request_id=start_id)
    assert replay.work_order.status == S.IN_PROGRESS and snapshot(backend)[0] == before[0]
    for task in TASKS:
        await save(svc, job, task)
    sid = await set_id(repo, job)
    submit_id = rid()
    await svc.submit_for_review(job, ctx(U1), request_id=submit_id, expected_set_id=sid)
    assert await refused(svc.return_for_rework(job, manager(), request_id=submit_id, reason="x")) == (
        409, "PM_E01_REQUEST_CONFLICT")
    close_id = rid()
    await svc.close_after_review(job, manager(), request_id=close_id)
    before = snapshot(backend)
    await svc.close_after_review(job, manager(), request_id=close_id)
    assert snapshot(backend)[0] == before[0]  # no second close effect, no new snapshot
    assert [r["action"] for r in backend.rows("pm_work_order_transition")] == ["START", "SUBMIT", "CLOSE"]


async def test_sh03_a_one_event_projection_lag_is_reconciled_and_a_larger_divergence_fails_closed() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    status_col = backend.tabs["pm_work_order"][0].index("status")
    backend.tabs["pm_work_order"][1][status_col] = "OPEN"  # projection one event behind the journal
    # R4 PM Read Safety B1 (deliberate contract change): the read reports it, never reconciles it.
    lagging = snapshot(backend)
    assert await refused(svc.list_work_order_history(job, ctx(U1))) == (409, "PM_E01_TRANSITION_INCOMPLETE")
    assert snapshot(backend) == lagging and backend.rows("pm_work_order")[0]["status"] == "OPEN"
    await save(svc, job, TASKS[0])  # the next authorized operation reconciles it (E01 recovery unchanged)
    assert backend.rows("pm_work_order")[0]["status"] == "IN_PROGRESS"
    history = await svc.list_work_order_history(job, ctx(U1))
    assert [e.action.value for e in history] == ["START"]
    backend.tabs["pm_work_order"][1][status_col] = "CLOSED"  # cannot be explained by one lagging event
    before = snapshot(backend)
    assert await refused(svc.list_work_order_history(job, ctx(U1))) == (409, "PM_E01_STATE_INCONSISTENT")
    assert snapshot(backend) == before


async def test_sh03_the_journal_is_append_only_and_guards_its_order() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    await service(repo).start_work_order(job, ctx(U1), request_id=rid())
    [event] = await repo.list_pm_work_order_transitions(job)
    stale = event.model_copy(update={"event_id": "PMEV-SYN-OTHER", "request_id": rid(), "request_fingerprint": "f"})
    before = snapshot(backend)
    with pytest.raises(ValueError, match="PM_E01_JOURNAL_CONFLICT"):
        await repo.append_pm_work_order_transition(stale)  # from_status OPEN is no longer current
    with pytest.raises(ValueError, match="PM_E01_JOURNAL_CONFLICT"):
        await repo.append_pm_work_order_transition(event.model_copy(update={
            "request_id": rid(), "from_status": S.IN_PROGRESS}))  # duplicate event id
    assert snapshot(backend) == before
    assert (await repo.append_pm_work_order_transition(event)) == (event, True)  # identical replay


# ---------------------------------------------------------------------------
# SH-04 / SH-05 item save
# ---------------------------------------------------------------------------


async def test_sh04_one_result_and_one_outcome_identical_retry_replays_and_a_difference_conflicts() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    first = await save(svc, job, TASKS[0])
    assert (first.result_replayed, first.outcome_replayed) == (False, False)
    before = snapshot(backend)
    again = await save(svc, job, TASKS[0])
    assert (again.result_replayed, again.outcome_replayed) == (True, True)
    assert again.outcome == first.outcome and snapshot(backend)[0] == before[0]
    assert await refused(save(svc, job, TASKS[0], performed_actions=(CHECK, "ทำความสะอาด"))) == (
        409, "PM_OUTCOME_CONFLICT")
    assert snapshot(backend)[0] == before[0]
    [row] = backend.rows("pm_work_result")
    assert (row["disposition"], json.loads(row["performed_actions"]), row["completed"]) == (
        "PERFORMED", [CHECK], "TRUE")


async def test_sh04_legacy_completed_is_never_interpreted_as_an_outcome() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    header = backend.tabs["pm_work_result"][0]
    backend.tabs["pm_work_result"].append(_row(header, pm_work_result_id="PMWR-0090", pm_work_order_id=job,
                                               pm_task_id=TASKS[0], revision_id=REVISION, sequence="1",
                                               task_description="legacy", completed="TRUE", performed_by="u",
                                               performed_at=TS))
    assert await repo.list_pm_item_outcomes(job) == []


async def test_sh05_not_performed_before_any_performed_is_refused_without_writes() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    before = snapshot(backend)
    assert await refused(save(svc, job, TASKS[0], Disposition.NOT_PERFORMED)) == (
        422, "PM_NOT_PERFORMED_REQUIRES_PERFORMED_FIRST")
    assert snapshot(backend) == before


# ---------------------------------------------------------------------------
# SH-06 / SH-07 Outstanding and G1
# ---------------------------------------------------------------------------


async def test_sh06_partial_close_creates_exactly_one_outstanding_with_g1_provenance_and_none_before() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    await to_pending_review(repo, job, not_performed=(TASKS[-1],))
    assert backend.rows("pm_outstanding_item") == []  # none before CLOSE
    done = await service(repo).close_after_review(job, manager(), request_id=rid())
    assert done.work_order.status == S.CLOSED
    [row] = backend.rows("pm_outstanding_item")
    outcome = next(o for o in await repo.list_pm_item_outcomes(job) if o.pm_task_id == TASKS[-1])
    assert (row["pm_task_id"], row["origin_reason_code"], row["origin_recorded_by"],
            row["origin_pm_work_result_id"], row["is_test_data"], row["test_batch_id"]) == (
        TASKS[-1], outcome.reason_code, outcome.recorded_by, outcome.source_pm_work_result_id, "TRUE", BATCH)
    assert [i.pm_task_id for i in await repo.list_pm_outstanding_items_for_asset(AssetType.VEHICLE, VEHICLE)] == [
        TASKS[-1]]


async def _pending_with_outcome(repo, job):
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    await save(svc, job, TASKS[0])
    return (await save(svc, job, TASKS[1], Disposition.NOT_PERFORMED)).outcome


async def test_sh07_g1_refuses_outstanding_without_a_matching_stored_not_performed_outcome() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    outcome = await _pending_with_outcome(repo, job)
    performed = next(o for o in await repo.list_pm_item_outcomes(job) if o.pm_task_id == TASKS[0])
    before = snapshot(backend)
    item = build_pm_outstanding_item(outcome, created_by=MANAGER_ID, created_at=outcome.recorded_at)
    with pytest.raises(ValueError, match="PM_OUTSTANDING_OUTCOME_REQUIRED"):
        fake = build_pm_outstanding_item(outcome.model_copy(update={"pm_task_id": TASKS[2],
                                                                    "source_pm_work_result_id": None}),
                                         created_by=MANAGER_ID, created_at=outcome.recorded_at)
        await repo.create_pm_outstanding_item(fake)  # TASKS[2] has no stored Outcome
    with pytest.raises(ValueError, match="PM_OUTSTANDING_PROVENANCE_MISMATCH"):
        await repo.create_pm_outstanding_item(item.model_copy(update={"origin_recorded_by": "SYN-OTHER"}))
    assert performed.disposition == Disposition.PERFORMED and snapshot(backend) == before
    assert (await repo.create_pm_outstanding_item(item))[1] is False
    assert (await repo.create_pm_outstanding_item(item))[1] is True  # identical replay
    reason_col = backend.tabs["pm_work_result"][0].index("reason_code")
    row = next(r for r in backend.tabs["pm_work_result"][1:] if TASKS[1] in r)
    row[reason_col] = "อื่น ๆ"  # the stored Outcome no longer matches: G1 is checked on replay too
    with pytest.raises(ValueError, match="PM_OUTSTANDING_PROVENANCE_MISMATCH"):
        await repo.create_pm_outstanding_item(item)


@pytest.mark.parametrize("change,code", [
    ({"work_order": "PMWO-9999"}, "PM_ITEM_OUTCOME_SOURCE_NOT_FOUND"),
    ({"revision_id": "PMREV-9999"}, "PM_ITEM_OUTCOME_SOURCE_REVISION_MISMATCH"),
    ({"pm_task_id": "PMT-9999"}, "PM_ITEM_OUTCOME_SOURCE_TASK_NOT_IN_SCOPE"),
    ({"source_pm_work_result_id": "PMWR-9999"}, "PM_ITEM_OUTCOME_SOURCE_RESULT_INVALID"),
])
async def test_c5_outcome_source_checks_use_the_mock_codes(change, code) -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    stored = (await save(svc, job, TASKS[0])).outcome
    values = stored.model_dump() | {k: v for k, v in change.items() if k != "work_order"}
    if "work_order" in change:
        values["pm_work_order_id"] = change["work_order"]
    values.pop("outcome_id", None)
    values.pop("creation_fingerprint", None)
    candidate = type(stored).model_validate(values)
    before = snapshot(backend)
    with pytest.raises(ValueError, match=code):
        await repo.create_pm_item_outcome(candidate)
    assert snapshot(backend) == before


async def test_c5_documented_divergence_an_outcome_without_a_source_result_is_refused_on_sheets_only() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    stored = (await save(svc, job, TASKS[0])).outcome
    values = stored.model_dump() | {"pm_task_id": TASKS[1], "source_pm_work_result_id": None}
    values.pop("outcome_id", None)
    values.pop("creation_fingerprint", None)
    outcome = type(stored).model_validate(values)
    mock = mock_repo_with()
    mock_job = await mock_v2_job(mock)
    mock_task = (await mock_scope_of(mock, mock_job))[1]
    assert (await mock.create_pm_item_outcome(outcome.model_copy(update={  # Mock accepts it
        "pm_work_order_id": mock_job, "pm_task_id": mock_task,
        "revision_id": (await mock.get_pm_work_order(mock_job)).work_order.revision_id})))[1] is False
    before = snapshot(backend)
    with pytest.raises(ValueError, match="PM_ITEM_OUTCOME_SOURCE_RESULT_INVALID"):
        await repo.create_pm_item_outcome(outcome)
    assert snapshot(backend) == before


async def test_c5_conflicting_outcome_is_never_overwritten_and_two_outcomes_for_one_item_fail_closed() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    stored = (await save(svc, job, TASKS[0])).outcome
    before = snapshot(backend)
    with pytest.raises(ValueError, match="PM_ITEM_OUTCOME_IDENTITY_CONFLICT"):
        await repo.create_pm_item_outcome(stored.model_copy(update={"performed_actions": ("ทำความสะอาด",)}))
    assert snapshot(backend) == before
    duplicate = list(backend.tabs["pm_work_result"][1])
    duplicate[0] = "PMWR-0099"
    backend.tabs["pm_work_result"].append(duplicate)  # a second filled row for the same item identity
    with pytest.raises(RepositoryIdentityAmbiguousError):
        await repo.list_pm_item_outcomes(job)


# ---------------------------------------------------------------------------
# SH-08 resolution (PM path)
# ---------------------------------------------------------------------------


async def test_sh08_a_later_closed_pm_resolves_once_and_a_different_resolution_conflicts() -> None:
    backend = build()
    repo = sheets_repo(backend)
    first = await new_job(repo)
    await closed(repo, first, not_performed=(TASKS[-1],))
    [item] = await repo.list_pm_outstanding_items(first)
    later = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(later, ctx(U1), request_id=rid())
    evidence = (await repo.create_attachment(AttachmentPurpose.PM_EVIDENCE, "synthetic://e", "e.jpg", "image/jpeg",
                                             1, U1, source_type="PM_WORK_ORDER", source_id=later)).attachment_id
    for task in TASKS:
        await save(svc, later, task, evidence_attachment_ids=(evidence,) if task == TASKS[-1] else ())
    await svc.submit_for_review(later, ctx(U1), request_id=rid(), expected_set_id=await set_id(repo, later))
    await svc.close_after_review(later, manager(), request_id=rid())
    result = next(r for r in (await repo.get_pm_work_order(later)).results if r.pm_task_id == TASKS[-1])
    resolution, replayed = await svc.resolve_outstanding(item.outstanding_id, manager(),
                                                         later_pm_work_result_id=result.pm_work_result_id,
                                                         evidence_attachment_ids=(evidence,))
    assert replayed is False and resolution.later_pm_work_result_id == result.pm_work_result_id
    [row] = backend.rows("pm_outstanding_item")
    assert (row["resolved_later_pm_work_result_id"], json.loads(row["resolution_evidence_attachment_ids"])) == (
        result.pm_work_result_id, [evidence])
    assert (await svc.resolve_outstanding(item.outstanding_id, manager(),
                                          later_pm_work_result_id=result.pm_work_result_id,
                                          evidence_attachment_ids=(evidence,)))[1] is True
    before = snapshot(backend)
    with pytest.raises(ValueError, match="PM_RESOLUTION_CONFLICT"):
        await repo.create_pm_outstanding_resolution(resolution.model_copy(update={"later_pm_work_result_id": None,
                                                                                  "later_repair_id": "RPR-0001"}))
    assert snapshot(backend) == before  # write-once: never rewritten


async def test_sh08_unrelated_evidence_is_refused_without_writes() -> None:
    backend = build()
    repo = sheets_repo(backend)
    first = await new_job(repo)
    await closed(repo, first, not_performed=(TASKS[-1],))
    [item] = await repo.list_pm_outstanding_items(first)
    origin = next(r for r in (await repo.get_pm_work_order(first)).results if r.pm_task_id == TASKS[0])
    before = snapshot(backend)
    status_code, _ = await refused(service(repo).resolve_outstanding(
        item.outstanding_id, manager(), later_pm_work_result_id=origin.pm_work_result_id,
        evidence_attachment_ids=("ATT-9999",)))
    assert status_code in (409, 422) and snapshot(backend) == before


# ---------------------------------------------------------------------------
# SH-09 / C-3 meter capture: allocation, write order, orphan readings
# ---------------------------------------------------------------------------


async def test_c3_readings_are_written_first_in_one_request_then_the_snapshot_row() -> None:
    backend = build(components=True)
    repo = sheets_repo(backend)
    snapshot_ = await MeterService(repo).capture_current_state(AssetType.VEHICLE, VEHICLE, U1, "SYN")
    appends = [(w["tab"], len(w["rows"])) for w in backend.write_log if w["kind"] == "append"]
    assert appends[:2] == [("meter_readings", 2), ("meter_snapshot", 1)]  # ENGINE_HOUR + ODOMETER, ONE request
    read = await repo.get_meter_snapshot(snapshot_.meter_snapshot_id)
    assert [(r.counter_type, r.value) for r in read.readings] == [(r.counter_type, r.value) for r in snapshot_.readings]
    assert {r.value for r in read.readings} == {1200.0, 54000.0}


@pytest.mark.parametrize("mode", ["reject", "server_error", "apply_then_timeout"])
async def test_c3_a_failed_snapshot_row_leaves_invisible_orphans_whose_id_is_never_reused(mode) -> None:
    backend = build(components=True)
    repo = sheets_repo(backend)
    backend.fail_next[("append", "meter_snapshot")] = mode
    with pytest.raises(RepositoryError):
        await repo.create_meter_snapshot(AssetType.VEHICLE, VEHICLE,
                                         (await MeterService(repo)._current_readings(AssetType.VEHICLE, VEHICLE)),
                                         U1, is_automatic=True)
    orphan_ids = {r["meter_snapshot_id"] for r in backend.rows("meter_readings")}
    assert orphan_ids == {"MSNAP-0001"}
    retry = await MeterService(repo).capture_current_state(AssetType.VEHICLE, VEHICLE, U1, "SYN")
    assert retry.meter_snapshot_id == "MSNAP-0002"  # never MSNAP-0001 again
    first = await repo.get_meter_snapshot("MSNAP-0001")
    if mode == "apply_then_timeout":  # the row was applied (outcome unknown to the caller): complete readings
        assert first is not None and len(first.readings) == len(retry.readings)
    else:
        assert first is None  # orphan readings are never joined into any snapshot
    read = await repo.get_meter_snapshot("MSNAP-0002")
    assert len(read.readings) == len(retry.readings)
    assert {r["meter_snapshot_id"] for r in backend.rows("meter_readings")} >= {"MSNAP-0001", "MSNAP-0002"}


@pytest.mark.parametrize("mode", ["reject", "server_error", "apply_then_timeout"])
async def test_sh09_an_interrupted_close_never_accumulates_close_captures(mode) -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = await to_pending_review(repo, job)
    close_id = rid()
    backend.fail_next[("batchUpdate", "pm_work_order")] = mode  # the status projection write
    try:
        await svc.close_after_review(job, manager(), request_id=close_id)
        completed = True
    except (ApiError, RepositoryError):
        completed = False
    assert completed is False or mode == "apply_then_timeout"
    done = await svc.close_after_review(job, manager(), request_id=close_id)
    assert done.work_order.status == S.CLOSED
    closes = [r for r in backend.rows("meter_snapshot") if r["source_note"] == "PM_WORK_ORDER_CLOSE"]
    assert len(closes) == 1 and done.work_order.closed_snapshot_id == closes[0]["meter_snapshot_id"]
    assert [r["action"] for r in backend.rows("pm_work_order_transition")].count("CLOSE") == 1


# ---------------------------------------------------------------------------
# SH-11 failure injection at every item-save and close write step
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", [("append", "meter_snapshot"), ("append", "location_snapshot"),
                                    ("append", "pm_work_result"), ("batchUpdate", "pm_work_result")])
@pytest.mark.parametrize("mode", ["reject", "server_error", "apply_then_timeout"])
async def test_sh11_item_save_failure_reports_no_success_and_a_retry_completes_without_duplicates(target,
                                                                                                    mode) -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    backend.fail_next[target] = mode
    with pytest.raises((ApiError, RepositoryError)):
        await save(svc, job, TASKS[0])
    recording = await save(svc, job, TASKS[0])
    results = [r for r in backend.rows("pm_work_result") if r["pm_task_id"] == TASKS[0]]
    assert len(results) == 1 and results[0]["disposition"] == "PERFORMED"
    assert await repo.list_pm_item_outcomes(job) == [recording.outcome]


@pytest.mark.parametrize("target", [("append", "pm_outstanding_item"), ("append", "pm_work_order_transition"),
                                    ("append", "meter_snapshot"), ("batchUpdate", "pm_work_order")])
@pytest.mark.parametrize("mode", ["reject", "server_error", "apply_then_timeout"])
async def test_sh11_close_failure_reports_no_success_and_a_retry_completes_once(target, mode) -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = await to_pending_review(repo, job, not_performed=(TASKS[-1],))
    close_id = rid()
    backend.fail_next[target] = mode
    with pytest.raises((ApiError, RepositoryError)):
        await svc.close_after_review(job, manager(), request_id=close_id)
    done = await svc.close_after_review(job, manager(), request_id=close_id)
    assert done.work_order.status == S.CLOSED
    assert len(backend.rows("pm_outstanding_item")) == 1
    assert [r["action"] for r in backend.rows("pm_work_order_transition")].count("CLOSE") == 1


# ---------------------------------------------------------------------------
# SH-12 TEST/REAL scope: D-1 reference masters, D-2b PM masters, child rows
# ---------------------------------------------------------------------------


async def test_d1_unscoped_masters_read_exactly_as_today_and_live_test_v2_stays_refused() -> None:
    backend = build(masters_scoped=False)
    repo = sheets_repo(backend)
    for read in (await repo.read_technician_master_reference(), await repo.read_user_account_reference()):
        assert read.test_scope_supported is False
        assert {r.scope for r in read.rows} == {REFERENCE_SCOPE_REAL}
    before = snapshot(backend)
    with pytest.raises(ApiError) as caught:
        await v2_job_marker(repo, PM, cutover("TEST"))
    assert (caught.value.status_code, caught.value.code) == (409, "TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED")
    assert snapshot(backend) == before


async def test_d1_scoped_masters_classify_every_row_strictly() -> None:
    backend = build()
    tech = backend.tabs["technician_master"]
    tech.append(_tech_row("TEC-SYN-REAL") + ["FALSE", ""])
    tech.append([""] * (len(tech[0]) - 2) + ["TRUE", BATCH])  # phantom: scope cells alone are no record
    repo = sheets_repo(backend)
    read = await repo.read_technician_master_reference()
    assert read.test_scope_supported is True
    assert [(r.values["technician_id"], r.scope, r.test_batch_id) for r in read.rows] == [
        (T1, REFERENCE_SCOPE_TEST, BATCH), (T2, REFERENCE_SCOPE_TEST, BATCH), ("TEC-SYN-REAL", REFERENCE_SCOPE_REAL, "")]


@pytest.mark.parametrize("cells", [("", ""), ("yes", BATCH), ("TRUE", ""), ("FALSE", BATCH), ("true ", "")])
async def test_d1_an_unclassified_or_invalid_flag_fails_closed(cells) -> None:
    backend = build()
    backend.tabs["technician_master"].append(_tech_row("TEC-SYN-BAD") + list(cells))
    repo = sheets_repo(backend)
    with pytest.raises(RepositoryRecordInvalidError, match="TEST_FLAG_INVALID"):
        await repo.read_technician_master_reference()


async def test_d1_exactly_one_scope_column_fails_closed() -> None:
    backend = build(masters_scoped=False)
    backend.tabs["user_account"][0].append("is_test_data")
    repo = sheets_repo(backend)
    with pytest.raises(RepositorySchemaError):
        await repo.read_user_account_reference()


async def test_d1_test_rows_never_appear_as_real() -> None:
    backend = build()
    repo = sheets_repo(backend, "REAL")
    read = await repo.read_technician_master_reference()
    assert {r.scope for r in read.rows} == {REFERENCE_SCOPE_TEST}  # classified per row, never re-scoped
    before = snapshot(backend)
    with pytest.raises(ApiError):
        await ta(repo, "REAL").assign(PM, "PMWO-9999", body(T1), request_id=rid(), user_id="dev-user")
    assert snapshot(backend) == before


async def test_d2b_pm_master_rows_are_filtered_by_the_server_scope() -> None:
    scopes = {PLAN: ("TRUE", BATCH), "PMP-SYN-OTHER": ("TRUE", OTHER_BATCH), "PMP-SYN-REAL": ("FALSE", "")}
    test_repo = sheets_repo(build(plan_scope=scopes), "TEST")
    real_repo = sheets_repo(build(plan_scope=scopes, context="REAL"), "REAL")
    assert [p.pm_plan_id for p in await test_repo.list_pm_plans(AssetType.VEHICLE, None)] == [PLAN]
    assert [p.pm_plan_id for p in await real_repo.list_pm_plans(AssetType.VEHICLE, None)] == [
        "PMP-SYN-REAL"]
    assert await test_repo.get_pm_plan("PMP-SYN-REAL") is None
    assert await test_repo.get_pm_plan("PMP-SYN-OTHER") is None
    assert await real_repo.get_pm_plan(PLAN) is None
    active = await test_repo.get_active_pm_task_revision(PLAN)
    assert active.revision.revision_id == REVISION and [t.pm_task_id for t in active.tasks] == list(TASKS)
    assert await real_repo.get_pm_task_revision(PLAN, REVISION) is None


async def test_d2b_an_invalid_pm_master_flag_fails_closed() -> None:
    backend = build(plan_scope={PLAN: ("maybe", "")})
    repo = sheets_repo(backend)
    with pytest.raises(RepositoryRecordInvalidError, match="TEST_FLAG_INVALID"):
        await repo.list_pm_plans(AssetType.VEHICLE, None)


async def test_d2b_unscoped_pm_master_tabs_behave_as_today_in_both_contexts() -> None:
    for context in ("TEST", "REAL"):
        repo = sheets_repo(build(context=context), context)
        assert [p.pm_plan_id for p in await repo.list_pm_plans(AssetType.VEHICLE, None)] == [PLAN]


async def test_sh12_child_rows_must_carry_their_work_orders_scope() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    await service(repo).start_work_order(job, ctx(U1), request_id=rid())
    [event] = await repo.list_pm_work_order_transitions(job)
    flag_col = backend.tabs["pm_work_order_transition"][0].index("is_test_data")
    batch_col = backend.tabs["pm_work_order_transition"][0].index("test_batch_id")
    backend.tabs["pm_work_order_transition"][1][flag_col] = "FALSE"
    backend.tabs["pm_work_order_transition"][1][batch_col] = ""
    with pytest.raises(RepositoryRecordInvalidError, match="SCOPE_MISMATCH"):
        await repo.list_pm_work_order_transitions(job)
    backend.tabs["pm_work_order_transition"][1][flag_col] = "TRUE"
    backend.tabs["pm_work_order_transition"][1][batch_col] = BATCH
    before = snapshot(backend)
    other = event.model_copy(update={"event_id": "PMEV-SYN-X", "request_id": rid(), "from_status": S.IN_PROGRESS,
                                     "to_status": S.CANCELLED, "is_test_data": "FALSE", "test_batch_id": ""})
    with pytest.raises(RepositoryRecordInvalidError, match="SCOPE_MISMATCH"):
        await repo.append_pm_work_order_transition(other)
    assert snapshot(backend) == before


async def test_sh12_an_unconfigured_server_scope_fails_closed_for_scoped_pm_masters() -> None:
    backend = build(plan_scope={PLAN: ("TRUE", BATCH)})
    from app.config import DataRepositoryMode
    repo = GoogleSheetsRepository(Settings(data_repository=DataRepositoryMode.GOOGLE_SHEETS,
                                           google_sheet_id="fake-sheet-id",
                                           google_application_credentials="fake.json"))  # no registry context
    repo._client._gspread_client = gspread.Client(None, session=backend)  # type: ignore[attr-defined]
    assert repo._settings.registry_context_effective is None
    with pytest.raises(RepositoryRecordInvalidError, match="SCOPE_CONTEXT_UNCONFIGURED"):
        await repo.get_pm_plan(PLAN)


# ---------------------------------------------------------------------------
# SH-13 legacy unchanged / SH-14 Store compatibility / D-5 declarations
# ---------------------------------------------------------------------------


def test_sh13_legacy_declarations_are_byte_unchanged_and_new_ones_only_extend_them() -> None:
    assert schemas.PM_WORK_RESULT_SHEET.required_headers == (
        "pm_work_result_id", "pm_work_order_id", "pm_task_id", "revision_id", "sequence", "task_description",
        "completed", "meter_snapshot_id", "remark", "evidence_attachment_ids", "performed_by", "performed_at")
    assert schemas.PM_WORK_RESULT_OUTCOME_SHEET.required_headers[:12] == schemas.PM_WORK_RESULT_SHEET.required_headers
    for legacy, scoped in ((schemas.PM_PLAN_SHEET, schemas.PM_PLAN_SCOPED_SHEET),
                           (schemas.PM_TASK_REVISION_SHEET, schemas.PM_TASK_REVISION_SCOPED_SHEET),
                           (schemas.PM_TASK_SHEET, schemas.PM_TASK_SCOPED_SHEET),
                           (schemas.PM_TASK_PART_SHEET, schemas.PM_TASK_PART_SCOPED_SHEET)):
        assert scoped.tab_name == legacy.tab_name
        assert scoped.required_headers == legacy.required_headers + schemas.SCOPE_COLUMNS
    # D-5 / C-6: only the existing V2 Repair declarations, unchanged.
    assert schemas.REPAIR_ORDER_V2_SHEET.required_headers[-3:] == ("assignment_model", "is_test_data",
                                                                    "test_batch_id")
    assert schemas.REPAIR_ASSIGNMENT_V2_SHEET.tab_name == "repair_assignment"


async def test_sh13_outcome_fill_changes_only_the_four_outcome_cells_of_its_row() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    original = svc._repository.create_pm_item_outcome
    seen: dict = {}

    async def spy(outcome):
        seen["row"] = list(backend.tabs["pm_work_result"][1])
        return await original(outcome)

    svc._repository.create_pm_item_outcome = spy
    await save(svc, job, TASKS[0])
    header = backend.tabs["pm_work_result"][0]
    after = backend.tabs["pm_work_result"][1]
    changed = {header[i] for i, (a, b) in enumerate(zip(seen["row"] + [""] * 4, after)) if a != b}
    assert changed <= set(schemas.PM_OUTCOME_COLUMNS)


async def test_sh13_a_legacy_work_order_is_refused_by_every_v2_operation_without_writes() -> None:
    backend = build()
    repo = sheets_repo(backend)
    legacy = await repo.create_pm_work_order(AssetType.VEHICLE, VEHICLE, PLAN, REVISION, None, "dev-user", None,
                                             scope_task_ids=list(TASKS))
    svc = service(repo)
    before = snapshot(backend)
    for attempt in (svc.start_work_order(legacy.pm_work_order_id, ctx(U1), request_id=rid()),
                    svc.cancel_work_order(legacy.pm_work_order_id, manager(), request_id=rid(), reason="x")):
        assert (await refused(attempt))[0] in (409, 422)
    assert snapshot(backend) == before


async def test_sh14_cancel_reads_store_requests_and_refuses_with_zero_writes() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    header = backend.tabs["material_request"][0]
    backend.tabs["material_request"].append(_row(header, material_request_id="MR-SYN-1", source_type="PM",
                                                 source_work_order_id=job, status="REQUESTED", created_at=TS,
                                                 created_by="dev-user"))
    before = snapshot(backend)
    assert await refused(service(repo).cancel_work_order(job, manager(), request_id=rid(), reason="x")) == (
        409, "PM_CANCEL_NOT_ELIGIBLE")
    assert snapshot(backend) == before


# ---------------------------------------------------------------------------
# SH-15 durable history (a fresh repository on the same workbook)
# ---------------------------------------------------------------------------


async def test_sh15_journal_outcomes_outstanding_and_resolution_survive_a_restart() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    await closed(repo, job, not_performed=(TASKS[-1],))
    fresh = sheets_repo(backend)  # a new process: no in-memory state
    assert await fresh.list_pm_work_order_transitions(job) == await repo.list_pm_work_order_transitions(job)
    assert await fresh.list_pm_item_outcomes(job) == await repo.list_pm_item_outcomes(job)
    assert await fresh.list_pm_outstanding_items(job) == await repo.list_pm_outstanding_items(job)
    detail = await fresh.get_pm_work_order(job)
    assert detail.work_order.status == S.CLOSED and detail.work_order.closed_snapshot_id
    history = await service(fresh).list_work_order_history(job, ctx(U1))
    assert [e.action.value for e in history] == ["START", "SUBMIT", "CLOSE"]


# ---------------------------------------------------------------------------
# Identity ambiguity and exact text
# ---------------------------------------------------------------------------


async def test_duplicate_work_order_or_outstanding_rows_fail_closed() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    await closed(repo, job, not_performed=(TASKS[-1],))
    backend.tabs["pm_outstanding_item"].append(list(backend.tabs["pm_outstanding_item"][1]))
    with pytest.raises(RepositoryIdentityAmbiguousError):
        await repo.list_pm_outstanding_items(job)
    backend.tabs["pm_outstanding_item"].pop()
    backend.tabs["pm_work_order"].append(list(backend.tabs["pm_work_order"][1]))
    with pytest.raises(RepositoryIdentityAmbiguousError):
        await repo.list_pm_work_order_transitions(job)


async def test_registry_text_cells_are_never_coerced() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    await save(svc, job, TASKS[0])
    await save(svc, job, TASKS[1], Disposition.NOT_PERFORMED, reason_code=OTHER, other_text="0042")
    stored = next(o for o in await repo.list_pm_item_outcomes(job) if o.pm_task_id == TASKS[1])
    assert stored.other_text == "0042"
    assert re.fullmatch(r"PMEV-[0-9a-f]+", backend.rows("pm_work_order_transition")[0]["event_id"])


async def test_timestamps_round_trip_exactly() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    recording = await save(svc, job, TASKS[0])
    [event] = await repo.list_pm_work_order_transitions(job)
    assert recording.outcome.recorded_at == recording.result.performed_at
    assert event.occurred_at.utcoffset() == timedelta(0)
