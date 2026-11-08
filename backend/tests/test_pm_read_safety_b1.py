"""R4 PM Read Safety B1 — the PM GET routes are authorized, scope-isolated, fail
closed on untrustworthy records and never write. Every row is SYNTHETIC.

Covers `GET /pm/plans/status`, `GET /pm/outstanding`,
`GET /pm/work-orders/{id}/history`, `GET /pm/work-orders/{id}/outstanding` and
`GET /pm/work-orders/{id}/requisition-lines`, Mock and simulated Sheets (the
fake gspread transport of the R4 Sheets parity suite; Sheets is TEST-only and its
own problems are simulated, never fixed)."""
from __future__ import annotations

import copy

import pytest

from app.config import Settings
from app.domain import authz
from app.domain.asset import AssetType
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.technician_assignment import PM
from tests.pm_e01_support import (
    NOT_PERFORMED,
    U1,
    close,
    ctx,
    drive_to_closed,
    manager,
    pm_service,
    repo_with,
    save,
    scope_of,
    start,
    submit,
    v2_job,
)
from tests.test_pm_read_security import WRITES, get_as
from tests.test_r4_pm_wf_phase_lifecycle import refused
from tests.test_technician_assignment_batch_r2f_h1 import U3, new_pm
from tests.test_v2_waiting_assignment_batch_r2f_h4_b3 import (
    API,
    REAL,
    call,
    code,
    set_job,
)

VEHICLE = "VEH-1046"
STATUS = f"{API}/pm/plans/status?asset_type=VEHICLE&asset_id={VEHICLE}"
ASSET_OUTSTANDING = f"{API}/pm/outstanding?asset_type=VEHICLE&asset_id={VEHICLE}"
VIEW = frozenset({authz.CAN_VIEW})
OTHER_BATCH = "SYN-OTHER-BATCH"
CAPTURE_WRITES = ("create_meter_snapshot", "create_location_snapshot")


def wo_path(job: str, leaf: str) -> str:
    return f"{API}/pm/work-orders/{job}/{leaf}"


def last_completed(response) -> list[str | None]:
    assert response.status_code == 200, response.text
    return [s["last_completed_work_order_id"] for s in response.json()]


def stored(repo):
    """Every store a GET could touch: headers, journal, captures, Outstanding, requisitions, audit."""
    return copy.deepcopy((repo._pm_work_orders, repo._pm_transitions, repo._meter_snapshots,
                          repo._pm_outstanding, repo._pm_outstanding_resolutions, repo._material_requests,
                          repo._requisition_lines, repo._technician_assignment_rows, len(repo.registry_write_log)))


def writes(repo) -> list[str]:
    return [c for c in repo.calls if c.startswith(WRITES)]


def rescope(repo, job: str, **cells) -> None:
    """Move a job to other TEST/REAL cells CONSISTENTLY (header and every journal event), the
    way a job created in that scope would be stored."""
    set_job(repo, "PM", job, **cells)
    repo._pm_transitions[job] = [e.model_copy(update=cells) for e in repo._pm_transitions.get(job, [])]


def retime_close(repo, job: str, at) -> None:
    """Give a CLOSED job another close time consistently (header and its CLOSE event)."""
    set_job(repo, "PM", job, closed_at=at)
    events = repo._pm_transitions[job]
    events[-1] = events[-1].model_copy(update={"occurred_at": at})


async def closed_job(repo, *, not_performed_last: bool = False, **scope) -> str:
    job = await v2_job(repo)
    tasks = await scope_of(repo, job)
    await drive_to_closed(repo, job, not_performed=(tasks[-1],) if not_performed_last else ())
    if scope:
        rescope(repo, job, **scope)
    return job


async def interrupted_close(repo) -> str:
    """A V2 job whose journal CLOSE is recorded but whose header projection failed
    after the close machine-state capture (the E01 interrupted-write case)."""
    svc = pm_service(repo)
    job = await v2_job(repo)
    await start(svc, job)
    tasks = await scope_of(repo, job)
    await save(svc, job, tasks[0])
    for task in tasks[1:]:
        await save(svc, job, task, NOT_PERFORMED)
    await submit(svc, repo, job)
    repo.fail = {"set_pm_work_order_status": RuntimeError("synthetic projection failure")}
    with pytest.raises(RuntimeError):
        await close(svc, job)
    repo.fail = {}
    assert repo._pm_work_orders[job].status == S.PENDING_REVIEW
    assert repo._pm_transitions[job][-1].to_status == S.CLOSED
    return job


# ---------------------------------------------------------------- D1: authorization before any read


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [STATUS, ASSET_OUTSTANDING])
async def test_anonymous_and_missing_can_view_are_refused_before_any_repository_read(path) -> None:
    repo = repo_with()
    await closed_job(repo, not_performed_last=True)
    for caps in (frozenset(), frozenset({authz.CAN_MANAGE_PM}), frozenset({authz.CAN_REPORT_REPAIR})):
        repo.calls.clear()
        response = await get_as(path, repo, caps)
        assert response.status_code == 403 and repo.calls == [], caps
        assert not isinstance(response.json(), list)  # a refusal is never an empty list
    for anonymous in ("", "   "):
        repo.calls.clear()
        response = await get_as(path, repo, VIEW, user=anonymous)
        assert code(response) == (403, "PM_OUTCOME_CONTEXT_REQUIRED") and repo.calls == []
    repo.calls.clear()
    assert (await call(path, repo, role="NO_SUCH_ROLE")).status_code == 403 and repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [STATUS, ASSET_OUTSTANDING])
async def test_every_role_holding_can_view_reads_and_a_revocation_applies_to_the_next_request(path) -> None:
    repo = repo_with()
    await closed_job(repo, not_performed_last=True)
    for role, caps in authz.ROLE_CAPABILITIES.items():
        response = await call(path, repo, role=role)
        assert response.status_code == (200 if authz.CAN_VIEW in caps else 403), (role, response.text)
    assert (await get_as(path, repo, VIEW)).status_code == 200
    assert (await get_as(path, repo, frozenset())).status_code == 403  # the same actor, can_view revoked


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [STATUS, ASSET_OUTSTANDING])
@pytest.mark.parametrize("settings", [Settings(data_repository="google_sheets"),
                                      Settings(data_repository="google_sheets", registry_data_context="TEST")])
async def test_an_unconfigured_data_context_is_503_with_zero_reads(path, settings) -> None:
    repo = repo_with()
    await closed_job(repo)
    repo.calls.clear()
    response = await call(path, repo, settings=settings)
    assert code(response) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED") and repo.calls == []


class TestAccessManagementGrantAndRevoke:
    """Real Access Management mode: per-employee grants are re-resolved on every request."""

    @pytest.fixture(autouse=True)
    def _access_mode(self, monkeypatch):
        monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "true")
        monkeypatch.setenv("DEV_AUTH_MODE", "true")
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("DATA_REPOSITORY", "mock")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", [STATUS, ASSET_OUTSTANDING])
    async def test_a_grant_and_a_revocation_take_effect_on_the_next_request(self, path) -> None:
        from tests.test_access_management import DRV1, MGR, employee, grant, http, repo

        store = repo()
        assert (await http("GET", path, store, DRV1, request_id=None)).status_code == 403  # zero grants
        assert (await grant(store, MGR, employee(DRV1), {"can_view": True})).status_code == 200
        allowed = await http("GET", path, store, DRV1, request_id=None)
        assert allowed.status_code == 200 and isinstance(allowed.json(), list)
        assert (await grant(store, MGR, employee(DRV1), {"can_view": False})).status_code == 200
        refused_again = await http("GET", path, store, DRV1, request_id=None)
        assert refused_again.status_code == 403 and not isinstance(refused_again.json(), list)


# ---------------------------------------------------------------- PM Plan Status: scope, tie-break, integrity


@pytest.mark.asyncio
async def test_plan_status_last_completion_comes_only_from_the_servers_own_scope() -> None:
    repo = repo_with()
    mine = await closed_job(repo)
    other_batch = await closed_job(repo, test_batch_id=OTHER_BATCH)  # closed later than mine
    real = await closed_job(repo, is_test_data="FALSE", test_batch_id="")
    assert repo._pm_work_orders[mine].closed_at < repo._pm_work_orders[other_batch].closed_at
    legacy = await new_pm(repo, legacy=True)
    set_job(repo, "PM", legacy, status=S.CLOSED,
            closed_at=repo._pm_work_orders[mine].closed_at.replace(year=2099))
    assert last_completed(await call(STATUS, repo)) == [mine]  # batch A: never B, REAL or Legacy
    assert last_completed(await call(STATUS, repo, settings=REAL)) == [real]  # REAL: never TEST or Legacy
    rescope(repo, mine, test_batch_id="SYN-THIRD-BATCH")
    assert last_completed(await call(STATUS, repo)) == [None]  # no own completion: truthful None, never borrowed
    text = (await call(STATUS, repo)).text
    assert other_batch not in text and real not in text and legacy not in text


@pytest.mark.asyncio
async def test_plan_status_preserves_the_model_mapping_and_truthful_unknown_values() -> None:
    repo = repo_with()
    response = await call(STATUS, repo)
    assert response.status_code == 200
    [row] = response.json()
    model = await repo.get_vehicle_model((await repo.get_vehicle(VEHICLE)).model_id)
    assert row["plan"]["pm_plan_id"] == model.assigned_pm_plan_id
    assert (row["last_completed_work_order_id"], row["last_completed_at"], row["last_completed_meter_snapshot_id"],
            row["due_status"]) == (None, None, None, "UNKNOWN")
    job = await closed_job(repo)
    [row] = (await call(STATUS, repo)).json()
    assert row["last_completed_work_order_id"] == job and row["due_status"] == "UNKNOWN"
    results = repo._pm_work_results[job]
    assert row["last_completed_meter_snapshot_id"] == results[-1].meter_snapshot_id


@pytest.mark.asyncio
async def test_plan_status_equal_close_times_are_broken_by_the_persisted_id_deterministically() -> None:
    repo = repo_with()
    first, second = await closed_job(repo), await closed_job(repo)
    retime_close(repo, second, repo._pm_work_orders[first].closed_at)
    expected = max(first, second)
    for _ in range(3):
        assert last_completed(await call(STATUS, repo)) == [expected]
    # Reversing the stored insertion order changes nothing.
    repo._pm_work_orders = dict(reversed(list(repo._pm_work_orders.items())))
    assert last_completed(await call(STATUS, repo)) == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "expected"), [
    ({"closed_at": None}, (500, "PM_WORK_ORDER_DATA_INVALID", "CLOSED_AT_MISSING")),
    ({"closed_snapshot_id": None}, (409, "PM_E01_TRANSITION_INCOMPLETE", None)),
    ({"is_test_data": "YES"}, (500, "TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID", "JOB_SCOPE_FLAG_INVALID")),
    ({"assignment_model": "TECHNICIAN_V3"}, (500, "ASSIGNMENT_MODEL_DATA_INVALID", "ASSIGNMENT_MODEL_UNKNOWN")),
])
async def test_plan_status_fails_closed_on_an_unprovable_completion_without_leaking_it(damage, expected) -> None:
    repo = repo_with()
    await closed_job(repo)
    job = await closed_job(repo)
    set_job(repo, "PM", job, **damage)
    before = stored(repo)
    response = await call(STATUS, repo)
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == expected[:2], response.text
    if expected[2] is not None:
        assert error["details"] == {"issues": {expected[2]: 1}}
    assert job not in response.text and "pm_work_order_id" not in response.text
    assert stored(repo) == before


@pytest.mark.asyncio
async def test_plan_status_refuses_a_closed_header_its_journal_does_not_prove() -> None:
    repo = repo_with()
    job = await v2_job(repo)
    await start(pm_service(repo), job)
    set_job(repo, "PM", job, status=S.CLOSED, closed_at=repo._pm_work_orders[job].opened_at)
    assert code(await call(STATUS, repo)) == (409, "PM_E01_STATE_INCONSISTENT")
    repo._pm_transitions.pop(job)  # a CLOSED V2 header with no journal at all (R2: never proven)
    assert code(await call(STATUS, repo)) == (409, "PM_E01_STATE_INCONSISTENT")


@pytest.mark.asyncio
async def test_plan_status_never_reports_an_interrupted_close_as_completed_and_writes_nothing() -> None:
    repo = repo_with()
    earlier = await closed_job(repo)
    await interrupted_close(repo)
    before = stored(repo)
    repo.calls.clear()
    assert last_completed(await call(STATUS, repo)) == [earlier]  # the pending CLOSE is not a completion
    assert writes(repo) == [] and stored(repo) == before


# ---------------------------------------------------------------- Outstanding / history: read-only E01 status


@pytest.mark.asyncio
async def test_a_lagging_close_stays_incomplete_on_every_read_and_nothing_is_written() -> None:
    repo = repo_with()
    job = await interrupted_close(repo)
    before = stored(repo)
    repo.calls.clear()
    for path in (ASSET_OUTSTANDING, wo_path(job, "outstanding"), wo_path(job, "history")):
        response = await call(path, repo)
        assert code(response) == (409, "PM_E01_TRANSITION_INCOMPLETE"), path
        assert not isinstance(response.json(), list) and job not in response.text.replace(f"/{job}/", "")
    assert writes(repo) == [] and not [c for c in repo.calls if c in CAPTURE_WRITES]
    assert "set_pm_work_order_status" not in repo.calls and stored(repo) == before
    assert repo._pm_work_orders[job].status == S.PENDING_REVIEW  # still exactly what was persisted


@pytest.mark.asyncio
async def test_e01_write_side_recovery_still_completes_the_interrupted_close_exactly_once() -> None:
    repo = repo_with()
    job = await interrupted_close(repo)
    captures = [s for s in repo._meter_snapshots.values() if s.source_note == "PM_WORK_ORDER_CLOSE"]
    assert (await call(wo_path(job, "history"), repo)).status_code == 409  # a read changes nothing ...
    svc = pm_service(repo)
    close_id = repo._pm_transitions[job][-1].request_id
    detail = await svc.close_after_review(job, manager(), request_id=close_id)  # ... the authorized retry recovers
    assert detail.work_order.status == S.CLOSED
    assert detail.work_order.closed_snapshot_id == captures[0].meter_snapshot_id  # the interrupted capture reused
    assert [s for s in repo._meter_snapshots.values() if s.source_note == "PM_WORK_ORDER_CLOSE"] == captures
    assert [e.action.value for e in repo._pm_transitions[job]].count("CLOSE") == 1
    outstanding = await call(wo_path(job, "outstanding"), repo)
    history = await call(wo_path(job, "history"), repo)
    assert outstanding.status_code == history.status_code == 200
    assert len(outstanding.json()) == len(await scope_of(repo, job)) - 1
    assert [e["action"] for e in history.json()] == ["START", "SUBMIT", "CLOSE"]
    assert len(await svc.list_asset_outstanding(AssetType.VEHICLE, VEHICLE, ctx(U1, authz.CAN_VIEW))) == \
        len(outstanding.json())


@pytest.mark.asyncio
async def test_asset_outstanding_isolates_batches_real_and_legacy() -> None:
    repo = repo_with()
    mine = await closed_job(repo, not_performed_last=True)
    other = await closed_job(repo, not_performed_last=True, test_batch_id=OTHER_BATCH)
    real = await closed_job(repo, not_performed_last=True, is_test_data="FALSE", test_batch_id="")

    def jobs(response) -> set[str]:
        assert response.status_code == 200, response.text
        return {i["pm_work_order_id"] for i in response.json()}

    assert jobs(await call(ASSET_OUTSTANDING, repo)) == {mine}
    assert jobs(await call(ASSET_OUTSTANDING, repo, settings=REAL)) == {real}
    set_job(repo, "PM", mine, assignment_model="")  # a Legacy work order is never readable here
    assert jobs(await call(ASSET_OUTSTANDING, repo)) == set()
    assert other not in (await call(ASSET_OUTSTANDING, repo)).text


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "expected"), [
    ("missing", (500, "PM_WORK_ORDER_DATA_INVALID", "SOURCE_NOT_FOUND")),
    ({"is_test_data": "YES"}, (500, "PM_WORK_ORDER_DATA_INVALID", "JOB_SCOPE_FLAG_INVALID")),
    ({"is_test_data": "FALSE", "test_batch_id": "X"}, (500, "PM_WORK_ORDER_DATA_INVALID", "JOB_SCOPE_FLAG_INVALID")),
    ({"assignment_model": "TECHNICIAN_V3"}, (500, "ASSIGNMENT_MODEL_DATA_INVALID", "ASSIGNMENT_MODEL_UNKNOWN")),
])
async def test_asset_outstanding_fails_closed_on_any_untrusted_record_never_a_partial_list(damage, expected) -> None:
    repo = repo_with()
    await closed_job(repo, not_performed_last=True)  # a good record that must NOT be returned alone
    job = await closed_job(repo, not_performed_last=True)
    if damage == "missing":
        repo._pm_work_orders.pop(job)
    else:
        set_job(repo, "PM", job, **damage)
    before = stored(repo)
    response = await call(ASSET_OUTSTANDING, repo)
    assert (response.status_code, response.json()["error"]["code"]) == expected[:2], response.text
    assert response.json()["error"]["details"] == {"issues": {expected[2]: 1}}
    assert job not in response.text and "outstanding_id" not in response.text
    assert stored(repo) == before


@pytest.mark.asyncio
async def test_authorized_outstanding_and_history_reads_still_work_and_write_nothing() -> None:
    repo = repo_with()
    job = await closed_job(repo, not_performed_last=True)
    before = stored(repo)
    repo.calls.clear()
    asset = await call(ASSET_OUTSTANDING, repo, role="TECHNICIAN", user=U1)
    member = await call(wo_path(job, "outstanding"), repo, role="TECHNICIAN", user=U1)
    history = await call(wo_path(job, "history"), repo)
    assert asset.status_code == member.status_code == history.status_code == 200
    assert [i["outstanding_id"] for i in asset.json()] == [i["outstanding_id"] for i in member.json()]
    assert len(member.json()) == 1 and member.json()[0]["resolved"] is False
    assert [e["action"] for e in history.json()] == ["START", "SUBMIT", "CLOSE"]
    assert (await call(wo_path(job, "history"), repo, role="TECHNICIAN", user=U3)).status_code == 403
    assert writes(repo) == [] and stored(repo) == before


@pytest.mark.asyncio
async def test_an_open_work_order_has_no_effective_outstanding_and_reads_its_history() -> None:
    repo = repo_with()
    job = await v2_job(repo)
    await start(pm_service(repo), job)
    assert (await call(wo_path(job, "outstanding"), repo)).json() == []
    assert [e["action"] for e in (await call(wo_path(job, "history"), repo)).json()] == ["START"]


# ---------------------------------------------------------------- requisition lines: the V2 PM detail contract


async def approved_job(repo) -> str:
    """A V2 job whose approved scope generated requisition lines from two synthetic
    standard parts (fixture pattern of test_core_demo_fixes_delta)."""
    from app.domain.pm import PmTask, PmTaskPart

    revision_id = (await repo.get_active_pm_task_revision("PMP-0001")).revision.revision_id
    for n in (1, 2):
        task_id = f"PMT-SYN-PART-{n}"
        repo._pm_tasks[revision_id].append(PmTask(
            pm_task_id=task_id, revision_id=revision_id, sequence=90 + n,
            description=f"งานที่มีอะไหล่มาตรฐาน {n} (synthetic)",
            standard_parts=[PmTaskPart(pm_task_part_id=f"PMTP-SYN-{n}", pm_task_id=task_id,
                                       part_description=f"อะไหล่ทดสอบ {n} (synthetic)", quantity=n, unit="ชิ้น",
                                       part_id=None)]))
    job = await v2_job(repo)
    await pm_service(repo).approve_scope(job, approved_by="dev-user")
    assert len(await repo.list_requisition_lines_for_work_order(job)) == 2
    return job


@pytest.mark.asyncio
async def test_requisition_lines_are_read_by_the_manager_and_the_current_team_in_their_stored_order() -> None:
    repo = repo_with()
    job = await approved_job(repo)
    expected = [line.requisition_line_id
                for line in await repo.list_requisition_lines_for_work_order(job)]
    before = stored(repo)
    repo.calls.clear()
    for kwargs in ({}, {"role": "TECHNICIAN", "user": U1}):
        response = await call(wo_path(job, "requisition-lines"), repo, **kwargs)
        assert response.status_code == 200, response.text
        assert [line["requisition_line_id"] for line in response.json()] == expected
    assert writes(repo) == [] and stored(repo) == before


@pytest.mark.asyncio
async def test_requisition_lines_refuse_unauthorized_actors_before_reading_lines() -> None:
    repo = repo_with()
    job = await approved_job(repo)
    path = wo_path(job, "requisition-lines")
    for response in (await call(path, repo, role="TECHNICIAN", user=U3),  # linked, not on this team
                     await get_as(path, repo, VIEW),  # can_view alone is not Work Order access
                     await get_as(path, repo, frozenset())):
        assert response.status_code == 403 and not isinstance(response.json(), list)
    repo.calls.clear()
    anonymous = await get_as(path, repo, frozenset({authz.CAN_MANAGE_PM}), user="")
    assert code(anonymous) == (403, "PM_OUTCOME_CONTEXT_REQUIRED") and repo.calls == []
    repo.calls.clear()
    assert (await call(path, repo, role="TECHNICIAN", user=U3)).status_code == 403
    assert "list_requisition_lines_for_work_order" not in repo.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(("changes", "settings", "expected"), [
    ({"test_batch_id": OTHER_BATCH}, None, (404, "PM_WORK_ORDER_NOT_FOUND")),  # other TEST batch
    ({}, REAL, (404, "PM_WORK_ORDER_NOT_FOUND")),  # a TEST job read from REAL
    ({"is_test_data": "FALSE", "test_batch_id": ""}, None, (404, "PM_WORK_ORDER_NOT_FOUND")),  # REAL from TEST
    ({"assignment_model": ""}, None, (404, "PM_WORK_ORDER_NOT_FOUND")),  # Legacy: no access
    ({"is_test_data": "YES"}, None, (500, "TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID")),
    ({"assignment_model": "TECHNICIAN_V3"}, None, (500, "ASSIGNMENT_MODEL_DATA_INVALID")),
])
async def test_requisition_lines_of_cross_scope_legacy_or_malformed_work_orders_are_never_returned(
        changes, settings, expected) -> None:
    repo = repo_with()
    job = await approved_job(repo)
    set_job(repo, "PM", job, **changes)
    repo.calls.clear()
    response = await call(wo_path(job, "requisition-lines"), repo, settings=settings)
    assert code(response) == expected and not isinstance(response.json(), list)
    assert "list_requisition_lines_for_work_order" not in repo.calls and "requisition_line_id" not in response.text
    assert code(await call(wo_path("PMWO-NO-SUCH", "requisition-lines"), repo)) == (404, "PM_WORK_ORDER_NOT_FOUND")


# ---------------------------------------------------------------- unchanged neighbours


@pytest.mark.asyncio
async def test_work_order_reads_and_the_manager_queue_are_unchanged() -> None:
    repo = repo_with()
    job = await closed_job(repo)
    assert (await call(f"{API}/pm/work-orders/{job}", repo)).status_code == 200
    listed = await call(f"{API}/pm/work-orders", repo)
    assert [i["pm_work_order_id"] for i in listed.json()["items"]] == [job]
    assert (await call(f"{API}/pm/work-orders/{job}/outcomes", repo)).status_code == 200
    assert (await call(f"{API}/pm/work-orders/v2-waiting-assignment", repo)).status_code == 200
    assert (await call(f"{API}/pm/work-orders/{job}/technician-assignments", repo)).status_code == 200
    assert PM.key == "PM"


# ---------------------------------------------------------------- Mock / simulated-Sheets parity (offline fake gspread)


def _sheet_cell(backend, tab: str, key_column: str, key: str, column: str, value: str) -> None:
    header, *rows = backend.tabs[tab]
    for row in rows:
        row += [""] * (len(header) - len(row))
        if row[header.index(key_column)] == key:
            row[header.index(column)] = value
            return
    raise AssertionError(f"{tab}: no row {key}")


def _sheet_close_time(backend, job: str, value: str) -> None:
    """Give a CLOSED Sheets job another close time consistently (header and its CLOSE event row)."""
    _sheet_cell(backend, "pm_work_order", "pm_work_order_id", job, "closed_at", value)
    header, *rows = backend.tabs["pm_work_order_transition"]
    [row] = [r for r in rows if r[header.index("pm_work_order_id")] == job and r[header.index("action")] == "CLOSE"]
    row[header.index("occurred_at")] = value


async def _outcome(awaitable):
    try:
        value = await awaitable
    except Exception as exc:  # noqa: BLE001 - the contract compared is the refusal itself
        return ("refused", *await refused(_raise(exc)), getattr(exc, "details", None))
    return ("ok", value)


async def _raise(exc):
    raise exc


def _sheets_vehicle(monkeypatch, repo, plan: str) -> None:
    """Simulate the vehicle / model masters the parity workbook does not carry (the
    plan mapping is not under test here; the scoped last-completion lookup is)."""
    from types import SimpleNamespace

    import app.domain.pm_service as module

    async def exists(*_args):
        return None

    async def vehicle(_vehicle_id):
        return SimpleNamespace(model_id="MDL-SYN-1")

    async def model(_model_id):
        return SimpleNamespace(assigned_pm_plan_id=plan)

    monkeypatch.setattr(module, "require_asset_exists", exists)
    monkeypatch.setattr(repo, "get_vehicle", vehicle)
    monkeypatch.setattr(repo, "get_vehicle_model", model)


@pytest.mark.asyncio
async def test_parity_plan_status_scope_tie_break_and_unprovable_close(monkeypatch) -> None:
    from tests import test_r4_pm_wf_sheets_parity as sh

    backend = sh.build()
    sheets = sh.sheets_repo(backend)
    _sheets_vehicle(monkeypatch, sheets, sh.PLAN)
    svc = sh.service(sheets)
    jobs = [await sh.new_job(sheets) for _ in range(3)]
    for job in jobs:
        await sh.closed(sheets, job)
    first_closed = {r["pm_work_order_id"]: r["closed_at"] for r in backend.rows("pm_work_order")}[jobs[0]]
    _sheet_cell(backend, "pm_work_order", "pm_work_order_id", jobs[1], "test_batch_id", sh.OTHER_BATCH)
    _sheet_cell(backend, "pm_work_order", "pm_work_order_id", jobs[1], "closed_at", "2099-01-01T00:00:00+00:00")
    _sheet_close_time(backend, jobs[2], first_closed)  # a tie

    mock = repo_with()
    mock_jobs = [await closed_job(mock) for _ in range(3)]
    rescope(mock, mock_jobs[1], test_batch_id=OTHER_BATCH)
    retime_close(mock, mock_jobs[1], mock._pm_work_orders[mock_jobs[1]].closed_at.replace(year=2099))
    retime_close(mock, mock_jobs[2], mock._pm_work_orders[mock_jobs[0]].closed_at)

    before = sh.snapshot(backend)
    [sheet_status] = await svc.list_applicable_plan_status(AssetType.VEHICLE, sh.VEHICLE, ctx(U1, authz.CAN_VIEW))
    [mock_status] = await pm_service(mock).list_applicable_plan_status(AssetType.VEHICLE, VEHICLE,
                                                                      ctx(U1, authz.CAN_VIEW))
    assert sheet_status.last_completed_work_order_id == max(jobs[0], jobs[2])  # never the other batch's later close
    assert mock_status.last_completed_work_order_id == max(mock_jobs[0], mock_jobs[2])
    assert sh.snapshot(backend) == before  # zero Sheets writes

    _sheet_cell(backend, "pm_work_order", "pm_work_order_id", jobs[0], "closed_at", "")  # unprovable close time
    set_job(mock, "PM", mock_jobs[0], closed_at=None)
    sheet = await _outcome(svc.list_applicable_plan_status(AssetType.VEHICLE, sh.VEHICLE, ctx(U1, authz.CAN_VIEW)))
    mocked = await _outcome(pm_service(mock).list_applicable_plan_status(AssetType.VEHICLE, VEHICLE,
                                                                         ctx(U1, authz.CAN_VIEW)))
    assert sheet == mocked == ("refused", 500, "PM_WORK_ORDER_DATA_INVALID", {"issues": {"CLOSED_AT_MISSING": 1}})


@pytest.mark.asyncio
async def test_parity_a_lagging_close_is_incomplete_on_every_read_with_zero_writes() -> None:
    from tests import test_r4_pm_wf_sheets_parity as sh

    backend = sh.build()
    sheets = sh.sheets_repo(backend)
    svc = sh.service(sheets)
    job = await sh.new_job(sheets)
    await sh.closed(sheets, job, not_performed=(sh.TASKS[-1],))
    for column, value in (("status", "PENDING_REVIEW"), ("closed_at", ""), ("closed_snapshot_id", ""),
                          ("closed_by", "")):
        _sheet_cell(backend, "pm_work_order", "pm_work_order_id", job, column, value)  # the projection lags
    mock = repo_with()
    mock_job = await interrupted_close(mock)

    before, mock_before = sh.snapshot(backend), stored(mock)
    viewer = ctx(U1, authz.CAN_VIEW)
    for name, sheet_call, mock_call in (
        ("history", svc.list_work_order_history(job, ctx(U1)),
         pm_service(mock).list_work_order_history(mock_job, ctx(U1))),
        ("outstanding", svc.list_outstanding_items(job, ctx(U1)),
         pm_service(mock).list_outstanding_items(mock_job, ctx(U1))),
        ("asset", svc.list_asset_outstanding(AssetType.VEHICLE, sh.VEHICLE, viewer),
         pm_service(mock).list_asset_outstanding(AssetType.VEHICLE, VEHICLE, viewer)),
    ):
        sheet, mocked = await _outcome(sheet_call), await _outcome(mock_call)
        assert sheet[:3] == mocked[:3] == ("refused", 409, "PM_E01_TRANSITION_INCOMPLETE"), name
    assert sh.snapshot(backend) == before and stored(mock) == mock_before


@pytest.mark.asyncio
async def test_parity_an_outstanding_record_without_its_work_order_fails_the_asset_read_closed() -> None:
    from tests import test_r4_pm_wf_sheets_parity as sh

    backend = sh.build()
    sheets = sh.sheets_repo(backend)
    good, bad = await sh.new_job(sheets), await sh.new_job(sheets)
    for job in (good, bad):
        await sh.closed(sheets, job, not_performed=(sh.TASKS[-1],))
    orphan = next(r["outstanding_id"] for r in backend.rows("pm_outstanding_item") if r["pm_work_order_id"] == bad)
    _sheet_cell(backend, "pm_outstanding_item", "outstanding_id", orphan, "pm_work_order_id", "PMWO-SYN-GONE")

    mock = repo_with()
    await closed_job(mock, not_performed_last=True)
    mock_bad = await closed_job(mock, not_performed_last=True)
    item = next(i for i in mock._pm_outstanding.values() if i.pm_work_order_id == mock_bad)
    mock._pm_outstanding[item.outstanding_id] = item.model_copy(update={"pm_work_order_id": "PMWO-SYN-GONE"})

    viewer = ctx(U1, authz.CAN_VIEW)
    before = sh.snapshot(backend)
    sheet = await _outcome(sh.service(sheets).list_asset_outstanding(AssetType.VEHICLE, sh.VEHICLE, viewer))
    mocked = await _outcome(pm_service(mock).list_asset_outstanding(AssetType.VEHICLE, VEHICLE, viewer))
    assert sheet == mocked == ("refused", 500, "PM_WORK_ORDER_DATA_INVALID", {"issues": {"SOURCE_NOT_FOUND": 1}})
    assert "PMWO-SYN-GONE" not in str(sheet) and sh.snapshot(backend) == before


# ---------------------------------------------------------------- R2 correction 1: no journal never proves progress


@pytest.mark.asyncio
async def test_r2_a_closed_v2_header_without_journal_never_yields_empty_history_or_outstanding() -> None:
    repo = repo_with()
    job = await closed_job(repo, not_performed_last=True)
    repo._pm_transitions.pop(job)  # the journal is gone; only the CLOSED header remains
    before = stored(repo)
    repo.calls.clear()
    for path in (wo_path(job, "history"), wo_path(job, "outstanding"), ASSET_OUTSTANDING):
        response = await call(path, repo)
        assert code(response) == (409, "PM_E01_STATE_INCONSISTENT"), (path, response.text)
        assert not isinstance(response.json(), list) and "outstanding_id" not in response.text
        assert job not in response.text.replace(f"/{job}/", "")
    assert writes(repo) == [] and stored(repo) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [S.IN_PROGRESS, S.PENDING_REVIEW, S.CANCELLED, S.CLOSED])
async def test_r2_every_progressed_v2_header_without_journal_fails_closed(header) -> None:
    repo = repo_with()
    job = await v2_job(repo)
    set_job(repo, "PM", job, status=header)
    assert code(await call(wo_path(job, "history"), repo)) == (409, "PM_E01_STATE_INCONSISTENT")
    assert code(await call(wo_path(job, "outstanding"), repo)) == (409, "PM_E01_STATE_INCONSISTENT")


@pytest.mark.asyncio
async def test_r2_an_open_v2_work_order_without_journal_stays_readable() -> None:
    repo = repo_with()
    job = await v2_job(repo)
    assert repo._pm_transitions.get(job, []) == []
    assert (await call(wo_path(job, "history"), repo)).json() == []
    assert (await call(wo_path(job, "outstanding"), repo)).json() == []


@pytest.mark.asyncio
async def test_r2_authorized_write_recovery_is_unchanged_by_the_read_side_journal_proof() -> None:
    repo = repo_with()
    job = await interrupted_close(repo)
    detail = await pm_service(repo).close_after_review(job, manager(),
                                                       request_id=repo._pm_transitions[job][-1].request_id)
    assert detail.work_order.status == S.CLOSED
    assert (await call(wo_path(job, "history"), repo)).status_code == 200


# ---------------------------------------------------------------- R2 correction 2: journal ownership, scope, provenance


def tamper_event(repo, job: str, index: int, **changes) -> None:
    events = repo._pm_transitions[job]
    events[index] = events[index].model_copy(update=changes)


@pytest.mark.asyncio
@pytest.mark.parametrize(("tamper", "issue"), [
    ({"test_batch_id": OTHER_BATCH}, "JOURNAL_SCOPE_MISMATCH"),  # another TEST batch
    ({"is_test_data": "FALSE", "test_batch_id": ""}, "JOURNAL_SCOPE_MISMATCH"),  # REAL
    ({"is_test_data": "YES"}, "JOURNAL_SCOPE_MISMATCH"),  # unknown flag
    ({"pm_work_order_id": "PMWO-SYN-ELSEWHERE"}, "JOURNAL_OWNER_MISMATCH"),
    ({"request_id": " "}, "JOURNAL_PROVENANCE_INVALID"),
    ({"actor": ""}, "JOURNAL_PROVENANCE_INVALID"),
    ({"from_status": S.IN_PROGRESS}, "JOURNAL_CHAIN_INVALID"),  # START no longer starts from OPEN
])
async def test_r2_a_foreign_or_unprovable_journal_event_fails_every_read_closed(tamper, issue) -> None:
    repo = repo_with()
    job = await closed_job(repo, not_performed_last=True)
    tamper_event(repo, job, 0, **tamper)
    before = stored(repo)
    for path in (wo_path(job, "history"), wo_path(job, "outstanding"), ASSET_OUTSTANDING, STATUS):
        response = await call(path, repo)
        assert code(response) == (500, "PM_WORK_ORDER_DATA_INVALID"), (path, response.text)
        assert response.json()["error"]["details"] == {"issues": {issue: 1}}
        assert "event_id" not in response.text and "PMEV-" not in response.text
        assert "PMWO-SYN-ELSEWHERE" not in response.text
    assert stored(repo) == before


@pytest.mark.asyncio
async def test_r2_a_gap_or_an_invalid_edge_in_the_journal_fails_closed() -> None:
    repo = repo_with()
    job = await closed_job(repo)
    repo._pm_transitions[job].pop(1)  # SUBMIT missing: START -> CLOSE is no E01 chain
    assert (await call(wo_path(job, "history"), repo)).json()["error"]["details"] == {
        "issues": {"JOURNAL_CHAIN_INVALID": 1}}
    other = await closed_job(repo)
    tamper_event(repo, other, -1, to_status=S.CANCELLED)  # CLOSE action claiming CANCELLED
    set_job(repo, "PM", other, status=S.CANCELLED)
    assert (await call(wo_path(other, "history"), repo)).json()["error"]["details"] == {
        "issues": {"JOURNAL_CHAIN_INVALID": 1}}


# ---------------------------------------------------------------- R2: CLOSE evidence and the selected completion


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "issue"), [
    ("snapshot_missing", "CLOSE_SNAPSHOT_MISSING"),
    ("snapshot_other_asset", "CLOSE_SNAPSHOT_MISMATCH"),
    ("snapshot_other_purpose", "CLOSE_SNAPSHOT_MISMATCH"),
    ("snapshot_other_actor", "CLOSE_SNAPSHOT_MISMATCH"),
    ("snapshot_before_close", "CLOSE_SNAPSHOT_MISMATCH"),
    ("snapshot_not_automatic", "CLOSE_SNAPSHOT_MISMATCH"),
    ("snapshot_of_another_event", "CLOSE_SNAPSHOT_MISMATCH"),
    ("gps_missing", "CLOSE_LOCATION_MISMATCH"),
    ("closed_by_other", "CLOSE_RECORD_MISMATCH"),
])
async def test_r2_a_closed_header_needs_its_own_persisted_close_evidence(damage, issue) -> None:
    repo = repo_with()
    job = await closed_job(repo, not_performed_last=True)
    work_order = repo._pm_work_orders[job]
    snapshot_id = work_order.closed_snapshot_id
    snap = repo._meter_snapshots[snapshot_id]
    event = repo._pm_transitions[job][-1]
    if damage == "snapshot_missing":
        set_job(repo, "PM", job, closed_snapshot_id="MS-SYN-NO-SUCH")
    elif damage == "snapshot_other_asset":
        repo._meter_snapshots[snapshot_id] = snap.model_copy(update={"asset_id": "VEH-1047"})
    elif damage == "snapshot_other_purpose":
        repo._meter_snapshots[snapshot_id] = snap.model_copy(update={"source_note": "PM_TASK_RESULT"})
    elif damage == "snapshot_other_actor":
        repo._meter_snapshots[snapshot_id] = snap.model_copy(update={"recorded_by": "USR-SYN-OTHER"})
    elif damage == "snapshot_before_close":
        repo._meter_snapshots[snapshot_id] = snap.model_copy(
            update={"recorded_at": event.occurred_at.replace(year=2000)})
    elif damage == "snapshot_not_automatic":
        repo._meter_snapshots[snapshot_id] = snap.model_copy(update={"is_automatic": False})
    elif damage == "snapshot_of_another_event":  # a real snapshot, but an item-result capture
        result_snapshot = repo._pm_work_results[job][0].meter_snapshot_id
        set_job(repo, "PM", job, closed_snapshot_id=result_snapshot)
    elif damage == "gps_missing":
        repo._location_snapshots = {k: v for k, v in repo._location_snapshots.items() if v.event_id != snapshot_id}
    elif damage == "closed_by_other":
        set_job(repo, "PM", job, closed_by="USR-SYN-OTHER")
    before = stored(repo)
    for path in (wo_path(job, "history"), wo_path(job, "outstanding"), ASSET_OUTSTANDING, STATUS):
        response = await call(path, repo)
        assert code(response) == (500, "PM_WORK_ORDER_DATA_INVALID"), (path, damage, response.text)
        assert response.json()["error"]["details"] == {"issues": {issue: 1}}
        assert "MS-" not in response.text and "outstanding_id" not in response.text
    assert stored(repo) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["asset_id", "pm_plan_id", "assignment_model", "test_batch_id",
                                   "pm_work_order_id", "missing"])
async def test_r2_the_selected_completion_must_match_its_scoped_summary(field, monkeypatch) -> None:
    repo = repo_with()
    job = await closed_job(repo)
    original = repo.get_pm_work_order

    async def mismatched(pm_work_order_id):
        detail = await original(pm_work_order_id)
        if pm_work_order_id != job:
            return detail
        if field == "missing":
            return None
        value = {"asset_id": "VEH-1047", "pm_plan_id": "PMP-SYN-OTHER", "assignment_model": "",
                 "test_batch_id": OTHER_BATCH, "pm_work_order_id": "PMWO-SYN-OTHER"}[field]
        return detail.model_copy(update={"work_order": detail.work_order.model_copy(update={field: value})})

    monkeypatch.setattr(repo, "get_pm_work_order", mismatched)
    response = await call(STATUS, repo)
    issue = "WORK_ORDER_REFERENCE_MISSING" if field == "missing" else "WORK_ORDER_RECORD_MISMATCH"
    assert code(response) == (500, "PM_WORK_ORDER_DATA_INVALID") and response.json()["error"]["details"] == {
        "issues": {issue: 1}}
    assert job not in response.text and "VEH-1047" not in response.text


# ---------------------------------------------------------------- R2 Mock / simulated-Sheets parity


@pytest.mark.asyncio
async def test_r2_parity_a_journal_event_of_another_scope_fails_closed_identically() -> None:
    from tests import test_r4_pm_wf_sheets_parity as sh

    backend = sh.build()
    sheets = sh.sheets_repo(backend)
    job = await sh.new_job(sheets)
    await sh.closed(sheets, job, not_performed=(sh.TASKS[-1],))
    header, *rows = backend.tabs["pm_work_order_transition"]
    rows[0][header.index("test_batch_id")] = sh.OTHER_BATCH  # the START event, now another batch's
    mock = repo_with()
    mock_job = await closed_job(mock, not_performed_last=True)
    tamper_event(mock, mock_job, 0, test_batch_id=OTHER_BATCH)

    viewer = ctx(U1, authz.CAN_VIEW)
    expected = ("refused", 500, "PM_WORK_ORDER_DATA_INVALID", {"issues": {"JOURNAL_SCOPE_MISMATCH": 1}})
    before, mock_before = sh.snapshot(backend), stored(mock)
    for sheet_call, mock_call in (
        (sh.service(sheets).list_work_order_history(job, ctx(U1)),
         pm_service(mock).list_work_order_history(mock_job, ctx(U1))),
        (sh.service(sheets).list_outstanding_items(job, ctx(U1)),
         pm_service(mock).list_outstanding_items(mock_job, ctx(U1))),
        (sh.service(sheets).list_asset_outstanding(AssetType.VEHICLE, sh.VEHICLE, viewer),
         pm_service(mock).list_asset_outstanding(AssetType.VEHICLE, VEHICLE, viewer)),
    ):
        assert await _outcome(sheet_call) == await _outcome(mock_call) == expected
    assert sh.snapshot(backend) == before and stored(mock) == mock_before


@pytest.mark.asyncio
async def test_r2_parity_closed_header_without_journal_and_missing_close_snapshot() -> None:
    from tests import test_r4_pm_wf_sheets_parity as sh

    backend = sh.build()
    sheets = sh.sheets_repo(backend)
    no_journal, no_snapshot = await sh.new_job(sheets), await sh.new_job(sheets)
    for job in (no_journal, no_snapshot):
        await sh.closed(sheets, job)
    header, *rows = backend.tabs["pm_work_order_transition"]
    backend.tabs["pm_work_order_transition"] = [header, *[
        r for r in rows if r[header.index("pm_work_order_id")] != no_journal]]
    _sheet_cell(backend, "pm_work_order", "pm_work_order_id", no_snapshot, "closed_snapshot_id", "MS-SYN-NO-SUCH")

    mock = repo_with()
    mock_no_journal, mock_no_snapshot = await closed_job(mock), await closed_job(mock)
    mock._pm_transitions.pop(mock_no_journal)
    set_job(mock, "PM", mock_no_snapshot, closed_snapshot_id="MS-SYN-NO-SUCH")

    before = sh.snapshot(backend)
    for sheet_job, mock_job, expected in (
        (no_journal, mock_no_journal, ("refused", 409, "PM_E01_STATE_INCONSISTENT")),
        (no_snapshot, mock_no_snapshot, ("refused", 500, "PM_WORK_ORDER_DATA_INVALID")),
    ):
        sheet = await _outcome(sh.service(sheets).list_work_order_history(sheet_job, ctx(U1)))
        mocked = await _outcome(pm_service(mock).list_work_order_history(mock_job, ctx(U1)))
        assert sheet[:3] == mocked[:3] == expected and sheet[3] == mocked[3]
    assert sh.snapshot(backend) == before


# ---------------------------------------------------------------- R3 correction 1: a CLOSE snapshot has one owner


@pytest.mark.asyncio
async def test_r3_an_earlier_close_borrowing_the_later_closes_snapshot_fails_closed() -> None:
    """The reviewer's counterexample: two V2 closes on one asset by the same actor; the earlier
    work order is pointed at the later CLOSE's valid snapshot (asset, actor, purpose, time and GPS
    all still pass)."""
    repo = repo_with()
    earlier = await closed_job(repo, not_performed_last=True)
    later = await closed_job(repo, not_performed_last=True)
    assert repo._pm_work_orders[earlier].closed_by == repo._pm_work_orders[later].closed_by
    borrowed = repo._pm_work_orders[later].closed_snapshot_id
    set_job(repo, "PM", earlier, closed_snapshot_id=borrowed)
    before = stored(repo)
    repo.calls.clear()
    for path in (wo_path(earlier, "history"), wo_path(earlier, "outstanding"), ASSET_OUTSTANDING, STATUS):
        response = await call(path, repo)
        assert code(response) == (500, "PM_WORK_ORDER_DATA_INVALID"), (path, response.text)
        assert response.json()["error"]["details"] == {"issues": {"CLOSE_SNAPSHOT_FOREIGN": 1}}
        assert borrowed not in response.text and earlier not in response.text.replace(f"/{earlier}/", "")
    assert writes(repo) == [] and stored(repo) == before


@pytest.mark.asyncio
async def test_r3_a_snapshot_also_claimed_by_a_legacy_or_cancelled_record_is_ambiguous() -> None:
    repo = repo_with()
    job = await closed_job(repo)
    claimant = await new_pm(repo, legacy=True)
    set_job(repo, "PM", claimant, closed_snapshot_id=repo._pm_work_orders[job].closed_snapshot_id)
    response = await call(wo_path(job, "history"), repo)
    assert response.json()["error"]["details"] == {"issues": {"CLOSE_SNAPSHOT_FOREIGN": 1}}


@pytest.mark.asyncio
async def test_r3_valid_historical_closes_keep_their_own_snapshot_whatever_was_captured_later() -> None:
    repo = repo_with()
    first = await closed_job(repo, not_performed_last=True)
    second = await closed_job(repo, not_performed_last=True)  # later captures by the same actor
    third = await v2_job(repo)
    svc = pm_service(repo)
    await start(svc, third)
    await save(svc, third, (await scope_of(repo, third))[0])  # an even later item capture
    for job in (first, second):
        assert [e["action"] for e in (await call(wo_path(job, "history"), repo)).json()] == [
            "START", "SUBMIT", "CLOSE"]
        assert len((await call(wo_path(job, "outstanding"), repo)).json()) == 1
    assert len((await call(ASSET_OUTSTANDING, repo)).json()) == 2
    assert last_completed(await call(STATUS, repo)) == [second]


# ---------------------------------------------------------------- R3 correction 2: E01 journal provenance


@pytest.mark.asyncio
@pytest.mark.parametrize(("tamper", "issue"), [
    ("blank_fingerprint", "JOURNAL_PROVENANCE_INVALID"),
    ("space_fingerprint", "JOURNAL_PROVENANCE_INVALID"),
    ("foreign_event_id", "JOURNAL_PROVENANCE_INVALID"),  # not the request's deterministic E01 id
    ("duplicate_event", "JOURNAL_IDENTITY_DUPLICATE"),  # the same event recorded twice
    ("duplicate_request", "JOURNAL_IDENTITY_DUPLICATE"),  # two events under one client request id
])
async def test_r3_malformed_journal_provenance_fails_every_read_closed(tamper, issue) -> None:
    repo = repo_with()
    job = await closed_job(repo, not_performed_last=True)
    events = repo._pm_transitions[job]
    if tamper == "blank_fingerprint":
        tamper_event(repo, job, 1, request_fingerprint="")
    elif tamper == "space_fingerprint":
        tamper_event(repo, job, 1, request_fingerprint="   ")
    elif tamper == "foreign_event_id":
        tamper_event(repo, job, 1, event_id="PMEV-SYN-FORGED")
    elif tamper == "duplicate_event":
        events.insert(1, events[0].model_copy())
    elif tamper == "duplicate_request":
        tamper_event(repo, job, 1, request_id=events[0].request_id)
    identities = {v for e in repo._pm_transitions[job] for v in (e.event_id, e.request_id) if v}
    before = stored(repo)
    for path in (wo_path(job, "history"), wo_path(job, "outstanding"), ASSET_OUTSTANDING, STATUS):
        response = await call(path, repo)
        assert code(response) == (500, "PM_WORK_ORDER_DATA_INVALID"), (path, response.text)
        assert response.json()["error"]["details"] == {"issues": {issue: 1}}
        assert not [v for v in identities if v in response.text]  # no journal identity is disclosed
    assert stored(repo) == before


@pytest.mark.asyncio
async def test_r3_legitimate_journals_and_write_side_recovery_still_pass_the_provenance_proof() -> None:
    repo = repo_with()
    job = await interrupted_close(repo)
    events = repo._pm_transitions[job]
    from app.domain.pm_service import _e01_event_id

    assert all(e.event_id == _e01_event_id(job, e.request_id) and e.request_fingerprint for e in events)
    assert code(await call(wo_path(job, "history"), repo)) == (409, "PM_E01_TRANSITION_INCOMPLETE")
    await pm_service(repo).close_after_review(job, manager(), request_id=events[-1].request_id)  # a replay
    assert len(repo._pm_transitions[job]) == len(events)  # the retry appended no second event
    assert [e["action"] for e in (await call(wo_path(job, "history"), repo)).json()] == ["START", "SUBMIT", "CLOSE"]


# ---------------------------------------------------------------- R3 Mock / simulated-Sheets parity


def _sheet_rows(backend, tab: str) -> tuple[list[str], list[list[str]]]:
    header, *rows = backend.tabs[tab]
    for row in rows:
        row += [""] * (len(header) - len(row))
    return header, rows


@pytest.mark.asyncio
@pytest.mark.parametrize(("tamper", "issue"), [
    ("blank_fingerprint", "JOURNAL_PROVENANCE_INVALID"),
    ("foreign_event_id", "JOURNAL_PROVENANCE_INVALID"),
    ("duplicate_event", "JOURNAL_IDENTITY_DUPLICATE"),
    ("borrowed_snapshot", "CLOSE_SNAPSHOT_FOREIGN"),
])
async def test_r3_parity_provenance_and_snapshot_ownership_fail_closed_identically(tamper, issue) -> None:
    from tests import test_r4_pm_wf_sheets_parity as sh

    backend = sh.build()
    sheets = sh.sheets_repo(backend)
    job, later = await sh.new_job(sheets), await sh.new_job(sheets)
    for each in (job, later):
        await sh.closed(sheets, each, not_performed=(sh.TASKS[-1],))
    mock = repo_with()
    mock_job = await closed_job(mock, not_performed_last=True)
    mock_later = await closed_job(mock, not_performed_last=True)

    header, rows = _sheet_rows(backend, "pm_work_order_transition")
    mine = [r for r in rows if r[header.index("pm_work_order_id")] == job]
    if tamper == "blank_fingerprint":
        mine[1][header.index("request_fingerprint")] = ""
        tamper_event(mock, mock_job, 1, request_fingerprint="")
    elif tamper == "foreign_event_id":
        mine[1][header.index("event_id")] = "PMEV-SYN-FORGED"
        tamper_event(mock, mock_job, 1, event_id="PMEV-SYN-FORGED")
    elif tamper == "duplicate_event":
        backend.tabs["pm_work_order_transition"].insert(backend.tabs["pm_work_order_transition"].index(mine[0]) + 1,
                                                        list(mine[0]))
        mock._pm_transitions[mock_job].insert(1, mock._pm_transitions[mock_job][0].model_copy())
    else:
        later_snapshot = {r["pm_work_order_id"]: r["closed_snapshot_id"]
                          for r in backend.rows("pm_work_order")}[later]
        _sheet_cell(backend, "pm_work_order", "pm_work_order_id", job, "closed_snapshot_id", later_snapshot)
        set_job(mock, "PM", mock_job, closed_snapshot_id=mock._pm_work_orders[mock_later].closed_snapshot_id)

    viewer = ctx(U1, authz.CAN_VIEW)
    expected = ("refused", 500, "PM_WORK_ORDER_DATA_INVALID", {"issues": {issue: 1}})
    before, mock_before = sh.snapshot(backend), stored(mock)
    for sheet_call, mock_call in (
        (sh.service(sheets).list_work_order_history(job, ctx(U1)),
         pm_service(mock).list_work_order_history(mock_job, ctx(U1))),
        (sh.service(sheets).list_outstanding_items(job, ctx(U1)),
         pm_service(mock).list_outstanding_items(mock_job, ctx(U1))),
        (sh.service(sheets).list_asset_outstanding(AssetType.VEHICLE, sh.VEHICLE, viewer),
         pm_service(mock).list_asset_outstanding(AssetType.VEHICLE, VEHICLE, viewer)),
    ):
        assert await _outcome(sheet_call) == await _outcome(mock_call) == expected, tamper
    assert sh.snapshot(backend) == before and stored(mock) == mock_before
