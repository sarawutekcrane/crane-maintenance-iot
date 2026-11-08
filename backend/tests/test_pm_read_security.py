"""R4 / TASK-010 — PM Work Order read security (GET /api/v1/pm/work-orders and
GET /api/v1/pm/work-orders/{id}), mock / service level. Every row is SYNTHETIC.

List: `can_view`, then the server's TEST/REAL context, then record integrity,
then only that exact scope, filtered BEFORE ordering, counting and paging.
Detail (V2 jobs): context, scope (out of scope = the same 404 as missing), then
`can_manage_pm` or current V2 team membership. Legacy / unrecognized-model jobs
keep their previous read (an open Owner decision, asserted as unchanged here)."""
from __future__ import annotations

import copy
import uuid

import pytest

from app.config import Settings
from app.domain import authz
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.technician_assignment import PM
from tests.test_technician_assignment_batch_r2f_h1 import (
    T1,
    T2,
    U1,
    U3,
    assign,
    body,
    new_pm,
    repo_with,
)
from tests.test_v2_waiting_assignment_batch_r2f_h4_b3 import (
    API,
    REAL,
    call,
    code,
    doctor,
    set_job,
)

LIST = f"{API}/pm/work-orders"
INTEGRITY_READ = "read_work_order_v2_rows"
WRITES = ("create_", "append_", "set_", "close_", "update_", "assign_", "add_", "approve_", "delete_", "write_")


def ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [i["pm_work_order_id"] for i in response.json()["items"]]


async def get_as(path: str, repo, caps: frozenset[str], user: str = "SYN-READER", settings: Settings | None = None):
    """GET with an explicit effective capability set (what Access Management resolves)."""
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.context import RequestContext
    from app.dependencies import (
        get_current_context,
        get_repository,
        get_settings_dependency,
        reset_dependency_cache,
    )
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_current_context] = lambda: RequestContext(
        request_id=str(uuid.uuid4()), user_id=user, is_dev_auth=True, capabilities=caps)
    if settings is not None:
        app.dependency_overrides[get_settings_dependency] = lambda: settings
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            return await client.get(path)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


# ---------------------------------------------------------------- list: authorization and context before any read


@pytest.mark.asyncio
async def test_list_refuses_an_actor_without_can_view_before_any_read() -> None:
    repo = repo_with()
    await new_pm(repo)
    for caps in (frozenset(), frozenset({authz.CAN_MANAGE_PM}), frozenset({authz.CAN_REPORT_REPAIR})):
        repo.calls.clear()
        response = await get_as(LIST, repo, caps)
        assert response.status_code == 403 and repo.calls == [], caps
        assert "items" not in response.json()  # a refusal is never an empty page
    repo.calls.clear()
    assert (await call(LIST, repo, role="NO_SUCH_ROLE")).status_code == 403 and repo.calls == []


@pytest.mark.asyncio
async def test_list_is_open_to_every_role_that_holds_can_view_and_a_revocation_is_respected() -> None:
    repo = repo_with()
    job = await new_pm(repo)
    for role, caps in authz.ROLE_CAPABILITIES.items():
        response = await call(LIST, repo, role=role)
        if authz.CAN_VIEW in caps:
            assert ids(response) == [job], role
        else:
            assert response.status_code == 403, role
    assert ids(await get_as(LIST, repo, frozenset({authz.CAN_VIEW}))) == [job]
    assert (await get_as(LIST, repo, frozenset())).status_code == 403  # the same actor after can_view is revoked


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [Settings(data_repository="google_sheets"),
                                      Settings(data_repository="google_sheets", registry_data_context="TEST")])
async def test_list_without_a_configured_data_context_is_503_with_zero_reads(settings) -> None:
    repo = repo_with()
    await new_pm(repo)
    repo.calls.clear()
    response = await call(LIST, repo, settings=settings)
    assert code(response) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED") and repo.calls == []


# ---------------------------------------------------------------- list: scope isolation before paging


@pytest.mark.asyncio
async def test_list_isolates_test_batches_and_real_before_paging_with_exact_totals() -> None:
    repo = repo_with()
    mine = [await new_pm(repo) for _ in range(3)]
    other_batch = [await new_pm(repo) for _ in range(3)]
    real = [await new_pm(repo) for _ in range(2)]
    legacy = await new_pm(repo, legacy=True)
    for job in other_batch:
        set_job(repo, "PM", job, test_batch_id="SYN-OTHER-BATCH")
    for job in real:
        set_job(repo, "PM", job, is_test_data="FALSE", test_batch_id="")
    first = await call(f"{LIST}?page_size=2", repo)
    second = await call(f"{LIST}?page_size=2&page=2", repo)
    assert first.json()["total_items"] == second.json()["total_items"] == 3
    assert sorted(ids(first) + ids(second)) == sorted(mine) and len(ids(first)) == 2
    real_view = await call(LIST, repo, settings=REAL)
    assert sorted(ids(real_view)) == sorted(real) and real_view.json()["total_items"] == 2
    every_listed = set(ids(await call(f"{LIST}?page_size=200", repo))) | set(ids(real_view))
    assert legacy not in every_listed  # no provable scope: never listed (open Owner decision, see report)
    for query in ("is_test_data=FALSE", "test_batch_id=SYN-OTHER-BATCH", "data_context=REAL", "scope=REAL"):
        assert sorted(ids(await call(f"{LIST}?{query}&page_size=200", repo))) == sorted(mine), query


@pytest.mark.asyncio
async def test_list_keeps_its_filters_fields_and_newest_first_order_inside_the_scope() -> None:
    repo = repo_with()
    jobs = [await new_pm(repo) for _ in range(4)]
    set_job(repo, "PM", jobs[0], status=S.CLOSED)
    set_job(repo, "PM", jobs[3], asset_id="VEH-1047")
    response = await call(f"{LIST}?asset_type=VEHICLE&asset_id=VEH-1046", repo)
    expected = sorted(jobs[:3], key=lambda j: (repo._pm_work_orders[j].opened_at, j), reverse=True)
    assert ids(response) == expected
    row = response.json()["items"][0]
    assert set(row) >= {"pm_work_order_id", "asset_type", "asset_id", "pm_plan_id", "revision_id", "status",
                        "opened_at", "closed_at", "result_count"}
    assert ids(await call(f"{LIST}?status=CLOSED", repo)) == [jobs[0]]


# ---------------------------------------------------------------- list: integrity fails closed, never a partial page


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "expected"), [
    ({"is_test_data": "YES"}, ("TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID", "JOB_SCOPE_FLAG_INVALID")),
    ({"is_test_data": "FALSE", "test_batch_id": "X"}, ("TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID", "JOB_SCOPE_FLAG_INVALID")),
    ({"assignment_model": "TECHNICIAN_V3"}, ("ASSIGNMENT_MODEL_DATA_INVALID", "ASSIGNMENT_MODEL_UNKNOWN")),
    ("duplicate", ("TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID", "JOB_ID_DUPLICATE")),
])
async def test_list_fails_closed_on_untrustworthy_records_without_leaking_them(damage, expected) -> None:
    repo = repo_with()
    job, other = await new_pm(repo), await new_pm(repo)
    doctor(repo, {other: {"pm_work_order_id": job}} if damage == "duplicate" else {job: damage})
    response = await call(LIST, repo)
    assert response.status_code == 500, response.text
    error = response.json()["error"]
    assert (error["code"], expected[1] in error["details"]["issues"]) == (expected[0], True)
    assert "items" not in response.json() and job not in response.text and "VEH-" not in response.text


@pytest.mark.asyncio
async def test_list_is_read_only() -> None:
    repo = repo_with()
    job = await new_pm(repo)
    await assign(repo, job, body(T1, T2), kind=PM)
    before = (copy.deepcopy(repo._pm_work_orders), copy.deepcopy(repo._technician_assignment_rows),
              len(repo.registry_write_log), copy.deepcopy(repo._pm_transitions))
    repo.calls.clear()
    assert ids(await call(LIST, repo)) == [job]
    assert repo.calls[0] == INTEGRITY_READ and not [c for c in repo.calls if c.startswith(WRITES)]
    assert (repo._pm_work_orders, repo._technician_assignment_rows, len(repo.registry_write_log),
            repo._pm_transitions) == before


# ---------------------------------------------------------------- detail: scope, membership and non-disclosure


@pytest.mark.asyncio
async def test_detail_manager_and_current_team_members_read_others_are_refused() -> None:
    repo = repo_with()
    job = await new_pm(repo)
    await assign(repo, job, body(T1, T2), kind=PM)
    detail = f"{LIST}/{job}"
    assert (await call(detail, repo)).json()["work_order"]["pm_work_order_id"] == job  # MAINTENANCE: can_manage_pm
    member = await call(detail, repo, role="TECHNICIAN", user=U1)
    assert member.status_code == 200 and member.json()["work_order"]["pm_work_order_id"] == job
    outsider = await call(detail, repo, role="TECHNICIAN", user=U3)  # linked technician, not on this team
    assert outsider.status_code == 403 and job not in outsider.text.replace(f"/{job}", "")
    assert "work_order" not in outsider.json()
    viewer = await get_as(detail, repo, frozenset({authz.CAN_VIEW}))  # can_view alone is not Work Order access
    assert viewer.status_code == 403 and "work_order" not in viewer.json()
    unassigned = await new_pm(repo)
    assert (await call(f"{LIST}/{unassigned}", repo, role="TECHNICIAN", user=U1)).status_code == 403


@pytest.mark.asyncio
async def test_detail_outside_the_scope_is_indistinguishable_from_missing() -> None:
    repo = repo_with()
    other_batch, real = await new_pm(repo), await new_pm(repo)
    set_job(repo, "PM", other_batch, test_batch_id="SYN-OTHER-BATCH")
    set_job(repo, "PM", real, is_test_data="FALSE", test_batch_id="")
    missing = await call(f"{LIST}/PMWO-NO-SUCH", repo)
    for job, settings in ((other_batch, None), (real, None)):
        response = await call(f"{LIST}/{job}", repo, settings=settings)
        assert code(response) == code(missing) == (404, "PM_WORK_ORDER_NOT_FOUND"), job
        assert "work_order" not in response.json() and "VEH-" not in response.text
    assert code(await call(f"{LIST}/{other_batch}", repo, settings=REAL)) == (404, "PM_WORK_ORDER_NOT_FOUND")
    assert (await call(f"{LIST}/{real}", repo, settings=REAL)).status_code == 200


@pytest.mark.asyncio
async def test_detail_untrustworthy_scope_cells_and_missing_context_fail_closed_without_contents() -> None:
    repo = repo_with()
    job = await new_pm(repo)
    set_job(repo, "PM", job, is_test_data="YES")
    response = await call(f"{LIST}/{job}", repo)
    assert response.status_code == 500 and response.json()["error"]["details"] == {"issues": {"JOB_SCOPE_FLAG_INVALID": 1}}
    assert "work_order" not in response.json() and "VEH-" not in response.text
    set_job(repo, "PM", job, is_test_data="TRUE")
    unconfigured = await call(f"{LIST}/{job}", repo, settings=Settings(data_repository="google_sheets"))
    assert code(unconfigured) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED") and "work_order" not in unconfigured.json()


@pytest.mark.asyncio
async def test_detail_is_read_only_and_never_projects_a_status() -> None:
    repo = repo_with()
    job = await new_pm(repo)
    await assign(repo, job, body(T1), kind=PM)
    before = (copy.deepcopy(repo._pm_work_orders), copy.deepcopy(repo._pm_transitions), len(repo.registry_write_log))
    repo.calls.clear()
    assert (await call(f"{LIST}/{job}", repo, role="TECHNICIAN", user=U1)).status_code == 200
    assert not [c for c in repo.calls if c.startswith(WRITES)]
    assert (repo._pm_work_orders, repo._pm_transitions, len(repo.registry_write_log)) == before


@pytest.mark.asyncio
async def test_detail_of_a_legacy_or_unknown_model_job_never_exposes_it() -> None:
    """DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107: Technician V2 only. A legacy
    (blank-model) job has no provable scope: the same 404 as a missing record, even
    for a manager. An unrecognized model fails closed (500) without contents."""
    repo = repo_with()
    legacy = await new_pm(repo, legacy=True)
    missing = await call(f"{LIST}/PMWO-NO-SUCH", repo)
    for response in (await call(f"{LIST}/{legacy}", repo),
                     await call(f"{LIST}/{legacy}", repo, role="TECHNICIAN", user=U1)):
        assert code(response) == code(missing) == (404, "PM_WORK_ORDER_NOT_FOUND")
        assert "work_order" not in response.json() and "VEH-" not in response.text
    odd = await new_pm(repo)
    set_job(repo, "PM", odd, assignment_model="TECHNICIAN_V3")
    response = await call(f"{LIST}/{odd}", repo)
    assert code(response) == (500, "ASSIGNMENT_MODEL_DATA_INVALID") and "work_order" not in response.json()


# ---------------------------------------------------------------- repository contract parity (Mock / Sheets, offline)


@pytest.mark.asyncio
async def test_data_scope_filter_has_the_same_meaning_in_mock_and_sheets_and_runs_before_paging() -> None:
    from app.domain.asset import AssetType
    from app.domain.common import PageParams
    from app.repositories.google_sheets import schemas
    from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws

    cells = [("PMWO-S1", "TRUE", "SYN-B"), ("PMWO-S2", "TRUE", "SYN-OTHER"), ("PMWO-S3", "FALSE", ""),
             ("PMWO-S4", "TRUE", "SYN-B"), ("PMWO-S5", "", "")]  # S5: a legacy row with no scope cells
    headers = schemas.PM_WORK_ORDER_V2_SHEET.required_headers
    work_order_ws = _ws(schemas.PM_WORK_ORDER_V2_SHEET)
    for n, (wo_id, flag, batch) in enumerate(cells):
        row = {"pm_work_order_id": wo_id, "asset_type": "VEHICLE", "asset_id": "VEH-1", "pm_plan_id": "PMP-0001",
               "revision_id": "PMREV-0001", "status": "OPEN", "opened_at": f"2026-01-0{n + 1}T00:00:00+00:00",
               "assignment_model": "TECHNICIAN_V2" if flag else "", "is_test_data": flag, "test_batch_id": batch}
        work_order_ws.append_row([row.get(h, "") for h in headers])
    sheets = _repo_with_fake_sheets(work_order_ws, _ws(schemas.PM_WORK_ASSIGNMENT_SHEET), _ws(schemas.PM_WORK_RESULT_SHEET))

    mock = repo_with()
    for n, (wo_id, flag, batch) in enumerate(cells):
        original = mock._pm_work_orders.pop(await new_pm(mock))
        mock._pm_work_orders[wo_id] = original.model_copy(update={
            "pm_work_order_id": wo_id, "asset_id": "VEH-1", "is_test_data": flag, "test_batch_id": batch,
            "opened_at": original.opened_at.replace(year=2026, month=1, day=n + 1),
            "assignment_model": "TECHNICIAN_V2" if flag else ""})
    for scope, expected in ((("TRUE", "SYN-B"), ["PMWO-S4", "PMWO-S1"]), (("FALSE", ""), ["PMWO-S3"]),
                            (("TRUE", "SYN-NONE"), [])):
        for repo in (mock, sheets):
            items, total = await repo.list_pm_work_orders(AssetType.VEHICLE, "VEH-1", PageParams(page=1, page_size=1),
                                                          data_scope=scope)
            assert (total, [i.pm_work_order_id for i in items]) == (len(expected), expected[:1]), (type(repo), scope)
    for repo in (mock, sheets):  # None keeps the unscoped behaviour internal callers rely on
        assert (await repo.list_pm_work_orders(AssetType.VEHICLE, "VEH-1", PageParams(page=1, page_size=50)))[1] == 5
