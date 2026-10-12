"""R2 Batch R2f-h2 — V2 My Work, mock / service level.

Every row is SYNTHETIC; TEST-scoped personnel / technicians / accounts are
explicit fixtures (scope TEST + batch). REAL-context cases run against the
service directly (mock mode is always TEST at the API). Governance list 1-19:
R2FH2-WORK (1-4, 10, 11), -CHAIN (5-7, 9), -SCOPE (8), -SET (12), -LEGACY
(13, 14), -AUTH (15), -FAIL (16), -RO (17-19). The Sheets transport is covered
by the `_sheets_` companion file.
"""
from __future__ import annotations

import copy

import pytest

from app.domain import authz
from app.domain.my_work import RESOLUTIONS, MyWorkService
from app.domain.technician_assignment import PM, REPAIR, AssignmentCutover
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_TEST
from tests.test_relationship_read_batch_r2f_a import account, person, tech
from tests.test_technician_assignment_batch_r2f_h1 import (
    BATCH,
    T1,
    T2,
    T3,
    T4,
    U1,
    U2,
    U3,
    assign,
    body,
    ctx,
    http,
    new_pm,
    new_repair,
    pm_service,
    repair_service,
    repo_with,
    tp,
    ta,
    tt,
    v2_rows,
)

API = "/api/v1"


def svc(repo, context: str | None = "TEST", batch: str = BATCH) -> MyWorkService:
    return MyWorkService(repo, AssignmentCutover(enabled=False, data_context=context, test_batch_id=batch))


async def work(repo, user: str | None, **kw):
    return await svc(repo, **kw).my_work(user)


def jobs(result) -> list[tuple[str, str, str]]:
    return [(i.work_type, i.job_id, i.assignment_role) for i in result.items]


async def get_my_work(repo, user: str | None = None, role: str = "TECHNICIAN"):
    return await http("GET", f"{API}/my-work", repo, role=role, user=user, request_id=None)


# ---------------------------------------------------------------------------
# R2FH2-WORK — resolved users and their current work (governance 1-4, 10, 11)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh2_work_01_repair_pm_and_combined_work_with_roles() -> None:
    repo = repo_with()
    repair_a, repair_b, pm_a = await new_repair(repo), await new_repair(repo), await new_pm(repo)
    await assign(repo, repair_a, body(T1, T2))
    await assign(repo, repair_b, body(T2, T1))
    await assign(repo, pm_a, body(T1), kind=PM)
    mine = await work(repo, U1)
    assert (mine.resolution, mine.technician_id) == ("RESOLVED", T1)
    assert sorted(jobs(mine)) == sorted([("REPAIR", repair_a, "PRIMARY"), ("REPAIR", repair_b, "COLLABORATOR"),
                                         ("PM", pm_a, "PRIMARY")])
    theirs = await work(repo, U2)
    assert sorted(jobs(theirs)) == sorted([("REPAIR", repair_a, "COLLABORATOR"), ("REPAIR", repair_b, "PRIMARY")])
    pm_only = await work(repo, U1)
    assert [i for i in pm_only.items if i.work_type == "PM"][0].assignment_set_id == v2_rows(repo, "PM")[0][
        "request_id"]


@pytest.mark.asyncio
async def test_r2fh2_work_02_resolved_with_zero_work_is_an_empty_list_not_unresolved() -> None:
    repo = repo_with()
    await new_repair(repo)  # unassigned V2 job
    result = await work(repo, U3)
    assert (result.resolution, result.technician_id, result.items) == ("RESOLVED", T3, ())
    response = await get_my_work(repo, U3)
    assert response.status_code == 200
    assert response.json() == {"resolution": "RESOLVED", "technician_id": T3, "items": []}


@pytest.mark.asyncio
async def test_r2fh2_work_03_superseded_sets_and_closed_jobs_are_excluded() -> None:
    repo = repo_with()
    moved, closed = await new_repair(repo), await new_repair(repo)
    await assign(repo, moved, body(T1, T2))
    await assign(repo, moved, body(T3, expected=(T1, T2)))  # T1, T2 superseded
    await assign(repo, closed, body(T1))
    await repair_service(repo).close_repair(closed, "dev-user", "ปิด")
    assert (await work(repo, U1)).items == ()
    assert (await work(repo, U2)).items == ()
    assert jobs(await work(repo, U3)) == [("REPAIR", moved, "PRIMARY")]


@pytest.mark.asyncio
async def test_r2fh2_work_04_http_round_trip_and_ordering() -> None:
    repo = repo_with()
    first, second = await new_repair(repo), await new_pm(repo)
    await assign(repo, first, body(T1))
    await assign(repo, second, body(T2, T1), kind=PM)
    payload = (await get_my_work(repo, U1)).json()
    assert payload["resolution"] == "RESOLVED" and payload["technician_id"] == T1
    assert [(i["work_type"], i["job_id"], i["assignment_role"]) for i in payload["items"]] == [
        ("PM", second, "COLLABORATOR"), ("REPAIR", first, "PRIMARY")]  # newest job first
    assert set(payload["items"][0]) == {"work_type", "job_id", "asset_type", "asset_id", "status", "opened_at",
                                        "assignment_role", "assignment_set_id", "assigned_at"}


# ---------------------------------------------------------------------------
# R2FH2-CHAIN — explicit unresolved states, no inference (governance 5-7, 9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("setup", "expected"), [
    ("no_account", "ACCOUNT_MISSING"),
    ("two_accounts", "ACCOUNT_AMBIGUOUS"),
    ("account_real_only", "ACCOUNT_SCOPE_UNPROVEN"),
    ("account_other_batch", "ACCOUNT_SCOPE_UNPROVEN"),
    ("no_personnel", "PERSONNEL_UNLINKED"),
    ("two_personnel", "PERSONNEL_AMBIGUOUS"),
    ("personnel_real_only", "PERSONNEL_SCOPE_MISMATCH"),
    ("personnel_other_batch", "PERSONNEL_SCOPE_MISMATCH"),
    ("technician_unlinked", "TECHNICIAN_UNLINKED"),
    ("technician_shared", "TECHNICIAN_AMBIGUOUS"),
    ("technician_missing", "TECHNICIAN_MISSING"),
    ("technician_two_rows", "TECHNICIAN_AMBIGUOUS"),
    ("technician_real_only", "TECHNICIAN_SCOPE_UNPROVEN"),
])
async def test_r2fh2_chain_01_every_broken_link_is_an_explicit_resolution_without_a_list(setup, expected) -> None:
    people = [tp("P-1", technician_id=T1, user_id=U1), tp("P-2", technician_id=T2, user_id=U2)]
    technicians, accounts = [tt(T1), tt(T2)], [ta(U1), ta(U2)]
    if setup == "no_account":
        accounts = [ta(U2)]
    elif setup == "two_accounts":
        accounts.append(ta(U1))
    elif setup == "account_real_only":
        accounts = [account(U1), ta(U2)]
    elif setup == "account_other_batch":
        accounts = [account(U1, scope=REFERENCE_SCOPE_TEST, batch="OTHER"), ta(U2)]
    elif setup == "no_personnel":
        people[0]["user_id"] = ""
    elif setup == "two_personnel":
        people.append(tp("P-9", technician_id=T3, user_id=U1))
    elif setup == "personnel_real_only":
        people[0] = person("P-1", technician_id=T1, user_id=U1)
    elif setup == "personnel_other_batch":
        people[0] = person("P-1", technician_id=T1, user_id=U1, test=True, batch="OTHER")
    elif setup == "technician_unlinked":
        people[0]["technician_id"] = ""
    elif setup == "technician_shared":
        people.append(tp("P-9", technician_id=T1))
    elif setup == "technician_missing":
        technicians = [tt(T2)]
    elif setup == "technician_two_rows":
        technicians.append(tt(T1))
    elif setup == "technician_real_only":
        technicians = [tech(T1), tt(T2)]
    repo = repo_with(people=people, technicians=technicians, accounts=accounts)
    result = await work(repo, U1)
    assert (result.resolution, result.technician_id, result.items) == (expected, None, None)
    payload = (await get_my_work(repo, U1)).json()
    assert payload == {"resolution": expected, "technician_id": None, "items": None}
    assert expected in RESOLUTIONS


@pytest.mark.asyncio
async def test_r2fh2_chain_02_unauthenticated_actor_gets_no_list_and_no_read() -> None:
    repo = repo_with()
    repo.calls.clear()
    for user in (None, "", "   "):
        result = await work(repo, user)
        assert (result.resolution, result.items) == ("UNAUTHENTICATED", None)
    assert repo.calls == []


@pytest.mark.asyncio
async def test_r2fh2_chain_03_no_inference_from_names_emails_or_identifiers() -> None:
    """Decoys: a technician id used as a user id, a personnel id used as a user id,
    a display name equal to the user id — none of them resolves."""
    people = [tp("P-1", technician_id=T1, user_id=U1)]
    people[0]["first_name"] = "USR-DECOY"
    repo = repo_with(people=people, technicians=[tt(T1)], accounts=[ta(U1), ta(T1), ta("P-1"), ta("USR-DECOY")])
    job = await new_repair(repo)
    await assign(repo, job, body(T1))
    for decoy in (T1, "P-1", "USR-DECOY"):  # each IS an account, but no personnel holds it
        result = await work(repo, decoy)
        assert (result.resolution, result.items) == ("PERSONNEL_UNLINKED", None), decoy
    for decoy in (U1.lower(), " " + U1, U1 + " "):  # exact text only: no folding or trimming
        result = await work(repo, decoy)
        assert (result.resolution, result.items) == ("ACCOUNT_MISSING", None), decoy
    assert jobs(await work(repo, U1)) == [("REPAIR", job, "PRIMARY")]


@pytest.mark.asyncio
async def test_r2fh2_chain_04_agrees_with_the_r2f_h1_recording_chain() -> None:
    """Whenever My Work lists a job for an actor, R2f-h1 recording authorizes
    that actor on it, and vice versa (no second notion of membership)."""
    repo = repo_with()
    job_ids = [await new_repair(repo) for _ in range(3)]
    await assign(repo, job_ids[0], body(T1, T2))
    await assign(repo, job_ids[1], body(T2))
    service = repair_service(repo)
    for user in (U1, U2, U3, "USR-NOBODY"):
        listed = {i.job_id for i in ((await work(repo, user)).items or ())}
        for job_id in job_ids:
            try:
                await service.authorize_recording(job_id, ctx(user), authz.CAN_MANAGE_REPAIR, "x")
                allowed = True
            except Exception:  # noqa: BLE001 - the 403
                allowed = False
            assert allowed == (job_id in listed), (user, job_id)


# ---------------------------------------------------------------------------
# R2FH2-SCOPE — scope mismatch and cross-batch isolation (governance 8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh2_scope_01_real_and_test_never_see_each_other() -> None:
    real_kw = {"context": "REAL", "batch": ""}
    repo = repo_with(people=[person("P-R", technician_id=T1, user_id=U1), tp("P-T", technician_id=T1, user_id=U1)],
                     technicians=[tech(T1), tt(T1)], accounts=[account(U1), ta(U1)])
    real_job = await new_repair(repo, **real_kw)
    test_job = await new_repair(repo)
    await assign(repo, real_job, body(T1), **real_kw)
    await assign(repo, test_job, body(T1))
    assert jobs(await work(repo, U1, **real_kw)) == [("REPAIR", real_job, "PRIMARY")]
    assert jobs(await work(repo, U1)) == [("REPAIR", test_job, "PRIMARY")]


@pytest.mark.asyncio
async def test_r2fh2_scope_02_another_batch_is_invisible_and_unresolvable() -> None:
    repo = repo_with()
    job = await new_repair(repo)
    await assign(repo, job, body(T1))
    other = await work(repo, U1, batch="SYN-OTHER-BATCH")
    assert (other.resolution, other.items) == ("ACCOUNT_SCOPE_UNPROVEN", None)


@pytest.mark.asyncio
async def test_r2fh2_scope_03_context_must_be_configured() -> None:
    repo = repo_with()
    with pytest.raises(ApiError) as exc:
        await work(repo, U1, context=None)
    assert exc.value.code == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    with pytest.raises(ApiError) as exc:
        await work(repo, U1, batch=" ")
    assert exc.value.code == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# R2FH2-SET — damaged / ambiguous sets fail closed (governance 12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "issue"), [
    ("lose_collaborator", "SET_INCOMPLETE"),
    ("swap_assignee", "SET_DIGEST_MISMATCH"),
    ("user_id_written", "V2_USER_ID_NOT_BLANK"),
    ("job_gone", "V2_ROW_JOB_MISSING"),
    ("job_turned_legacy", "V2_ROW_ON_LEGACY_JOB"),
    ("technician_left_master", "TECHNICIAN_REFERENCE_MISSING"),
    ("unrelated_job_damaged", "SET_INCOMPLETE"),
    ("my_row_lost_elsewhere", "SET_INCOMPLETE"),
])
async def test_r2fh2_set_01_untrusted_history_never_yields_a_list(damage, issue) -> None:
    repo = repo_with()
    mine, other = await new_repair(repo), await new_repair(repo)
    await assign(repo, mine, body(T1, T2))
    await assign(repo, other, body(T3, T4) if damage != "my_row_lost_elsewhere" else body(T3, T1))
    rows = v2_rows(repo)
    if damage == "lose_collaborator":
        del rows[1]
    elif damage == "swap_assignee":
        rows[1]["assignee_id"] = T3
    elif damage == "user_id_written":
        rows[0]["user_id"] = U1
    elif damage == "job_gone":
        del repo._repairs[mine]
    elif damage == "job_turned_legacy":
        repo._repairs[mine] = repo._repairs[mine].model_copy(update={"assignment_model": ""})
    elif damage == "technician_left_master":
        repo._technician_master = [tt(T1), tt(T3), tt(T4)]
    elif damage == "unrelated_job_damaged":  # tab-wide: another job's set is incomplete
        del rows[3]
    elif damage == "my_row_lost_elsewhere":  # T1's own COLLABORATOR row of the other job is lost
        del rows[3]
    with pytest.raises(ApiError) as exc:
        await work(repo, U1)
    assert exc.value.code == "TECHNICIAN_ASSIGNMENT_DATA_INVALID" and issue in exc.value.details["issues"]
    response = await get_my_work(repo, U1)
    assert response.status_code == 500 and response.json()["error"]["code"] == "TECHNICIAN_ASSIGNMENT_DATA_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [REPAIR, PM])
@pytest.mark.parametrize(("case", "status_code", "code", "issue"), [
    ("technician_missing", 500, "TECHNICIAN_ASSIGNMENT_DATA_INVALID", "TECHNICIAN_REFERENCE_MISSING"),
    ("technician_ambiguous", 500, "TECHNICIAN_ASSIGNMENT_DATA_INVALID", "TECHNICIAN_REFERENCE_AMBIGUOUS"),
    ("job_missing", 500, "TECHNICIAN_ASSIGNMENT_DATA_INVALID", "V2_ROW_JOB_MISSING"),
    ("job_legacy", 500, "TECHNICIAN_ASSIGNMENT_DATA_INVALID", "V2_ROW_ON_LEGACY_JOB"),
    ("job_scope_mismatch", 500, "TECHNICIAN_ASSIGNMENT_DATA_INVALID", "ROW_SCOPE_MISMATCH"),
    ("current_set_ambiguous", 409, "TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", None),
])
async def test_r2fh2_h201_01_an_other_job_is_validated_exactly_like_the_callers_own(kind, case, status_code, code,
                                                                                     issue) -> None:
    """H2-01: the caller (U1 / T1) is NOT in the other job; its defect still
    withholds the list — one validation path for every in-scope V2 job."""
    repo = repo_with()
    mine = await new_repair(repo)
    other = await (new_repair(repo) if kind is REPAIR else new_pm(repo))
    store = repo._repairs if kind is REPAIR else repo._pm_work_orders
    await assign(repo, mine, body(T1))
    await assign(repo, other, body(T3), kind=kind)
    if case == "technician_missing":
        repo._technician_master = [tt(T1), tt(T2), tt(T4)]
    elif case == "technician_ambiguous":
        repo._technician_master.append(tt(T3))
    elif case == "job_missing":
        del store[other]
    elif case == "job_legacy":
        store[other] = store[other].model_copy(update={"assignment_model": ""})
    elif case == "job_scope_mismatch":
        store[other] = store[other].model_copy(update={"test_batch_id": "SYN-OTHER-BATCH"})
    elif case == "current_set_ambiguous":
        await assign(repo, other, body(T4, expected=(T3,)), kind=kind)
        rows = v2_rows(repo, kind.key)
        rows[-1]["assigned_at"] = rows[-2]["assigned_at"]
    with pytest.raises(ApiError) as exc:
        await work(repo, U1)
    assert (exc.value.status_code, exc.value.code) == (status_code, code)
    if issue is not None:
        assert exc.value.details["issues"] == {issue: 1}
    response = await get_my_work(repo, U1)
    assert (response.status_code, response.json()["error"]["code"]) == (status_code, code)


@pytest.mark.asyncio
async def test_r2fh2_h201_02_other_scope_jobs_are_never_validated_or_listed() -> None:
    """Only the request's scope is validated: a damaged REAL job never blocks a
    TEST caller and vice versa (isolation is not traded for strictness)."""
    real_kw = {"context": "REAL", "batch": ""}
    repo = repo_with(people=[person("P-R", technician_id=T1, user_id=U1), tp("P-T", technician_id=T1, user_id=U1),
                             person("P-R3", technician_id=T3)],
                     technicians=[tech(T1), tt(T1), tech(T3)], accounts=[account(U1), ta(U1)])
    real_job, test_job = await new_repair(repo, **real_kw), await new_repair(repo)
    await assign(repo, real_job, body(T3), **real_kw)
    await assign(repo, test_job, body(T1))
    del repo._repairs[real_job]  # a REAL defect
    assert jobs(await work(repo, U1)) == [("REPAIR", test_job, "PRIMARY")]
    with pytest.raises(ApiError) as exc:
        await work(repo, U1, **real_kw)
    assert exc.value.details["issues"] == {"V2_ROW_JOB_MISSING": 1}


@pytest.mark.asyncio
async def test_r2fh2_set_02_an_ambiguous_current_set_fails_closed() -> None:
    repo = repo_with()
    job = await new_repair(repo)
    await assign(repo, job, body(T1))
    await assign(repo, job, body(T2, expected=(T1,)))
    rows = v2_rows(repo)
    rows[1]["assigned_at"] = rows[0]["assigned_at"]
    with pytest.raises(ApiError) as exc:
        await work(repo, U1)
    assert exc.value.code == "TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS"
    assert (await get_my_work(repo, U2)).status_code == 409


# ---------------------------------------------------------------------------
# R2FH2-LEGACY — legacy excluded and legacy My Work unchanged (governance 13, 14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh2_legacy_01_legacy_jobs_and_user_ids_are_never_v2_work() -> None:
    repo = repo_with()
    legacy_repair = await new_repair(repo, enabled=False)
    legacy_pm = await new_pm(repo, enabled=False)
    # Legacy assignees that look like the actor's own ids stay opaque legacy strings.
    await repair_service(repo, enabled=False).assign(legacy_repair, U1, [T1])
    await pm_service(repo, enabled=False).assign(legacy_pm, T1, [])
    before = (copy.deepcopy(repo._repair_assignment_history), copy.deepcopy(repo._pm_assignment_history))
    assert (await work(repo, U1)).items == ()
    assert (repo._repair_assignment_history, repo._pm_assignment_history) == before


@pytest.mark.asyncio
async def test_r2fh2_legacy_02_legacy_my_work_routes_are_unchanged() -> None:
    repo = repo_with()
    legacy_repair = await new_repair(repo, enabled=False)
    legacy_pm = await new_pm(repo, enabled=False)
    await repair_service(repo, enabled=False).assign(legacy_repair, "u-legacy", [])
    await pm_service(repo, enabled=False).assign(legacy_pm, "u-legacy", [])
    v2_job = await new_repair(repo)
    await assign(repo, v2_job, body(T1))
    legacy_repairs = await http("GET", f"{API}/repairs/my-work", repo, role="TECHNICIAN", user="u-legacy",
                                request_id=None)
    legacy_pms = await http("GET", f"{API}/pm/work-orders/my-work", repo, role="TECHNICIAN", user="u-legacy",
                            request_id=None)
    assert [r["repair_id"] for r in legacy_repairs.json()["items"]] == [legacy_repair]
    assert [w["pm_work_order_id"] for w in legacy_pms.json()["items"]] == [legacy_pm]
    for path in (f"{API}/repairs/my-work", f"{API}/pm/work-orders/my-work"):
        response = await http("GET", path, repo, role="TECHNICIAN", user=U1, request_id=None)
        assert response.json()["items"] == []  # V2 work never appears in a legacy list
    v2 = (await get_my_work(repo, "u-legacy")).json()
    assert (v2["resolution"], v2["items"]) == ("ACCOUNT_MISSING", None)  # no legacy fallback


# ---------------------------------------------------------------------------
# R2FH2-AUTH — the caller's own work only (governance 15)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER",
                                  "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER", "NOBODY"])
async def test_r2fh2_auth_01_every_role_sees_only_its_own_chain(role) -> None:
    repo = repo_with()
    job = await new_repair(repo)
    await assign(repo, job, body(T1))
    own = (await get_my_work(repo, U1, role=role)).json()
    assert own["resolution"] == "RESOLVED" and [i["job_id"] for i in own["items"]] == [job]
    other = (await get_my_work(repo, U2, role=role)).json()
    assert other["resolution"] == "RESOLVED" and other["items"] == []  # a capability never widens the list


def test_r2fh2_auth_02_no_route_parameter_can_name_another_user() -> None:
    from app.main import create_app

    operation = create_app().openapi()["paths"]["/api/v1/my-work"]
    assert set(operation) == {"get"} and not operation["get"].get("parameters")
    holders = {cap: {r for r, caps in authz.ROLE_CAPABILITIES.items() if cap in caps}
               for cap in (authz.CAN_MANAGE_REPAIR, authz.CAN_MANAGE_PM)}
    assert holders == {authz.CAN_MANAGE_REPAIR: {"ADMIN", "MAINTENANCE", "SUPERVISOR"},
                       authz.CAN_MANAGE_PM: {"ADMIN", "MAINTENANCE", "SUPERVISOR"}}


# ---------------------------------------------------------------------------
# R2FH2-FAIL — read failures and data defects are errors (governance 16)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "expected"), [
    ("read_user_account_reference", "USER_ACCOUNT_READ_FAILED"),
    ("read_personnel_relationship_master", "PERSONNEL_MASTER_READ_FAILED"),
    ("read_technician_master_reference", "TECHNICIAN_MASTER_READ_FAILED"),
    ("read_work_assignment_v2_rows", "TECHNICIAN_ASSIGNMENT_READ_FAILED"),
])
async def test_r2fh2_fail_01_a_failed_read_is_an_error_never_an_empty_list(method, expected) -> None:
    from app.repositories.base import RepositoryError

    repo = repo_with()

    async def broken(*_args, **_kwargs):
        raise RepositoryError("simulated read failure")

    setattr(repo, method, broken)
    with pytest.raises(ApiError) as exc:
        await work(repo, U1)
    assert (exc.value.code, exc.value.status_code) == (expected, 503)


@pytest.mark.asyncio
async def test_r2fh2_fail_02_an_invalid_personnel_flag_fails_closed() -> None:
    people = [tp("P-1", technician_id=T1, user_id=U1), {**tp("P-2"), "is_test_data": "maybe"}]
    repo = repo_with(people=people)
    with pytest.raises(ApiError) as exc:
        await work(repo, U1)
    assert exc.value.code == "PERSONNEL_MASTER_DATA_INVALID"


# ---------------------------------------------------------------------------
# R2FH2-RO — read only, no Go-live coupling, synthetic data only (governance 17-19)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh2_ro_01_my_work_performs_zero_writes() -> None:
    repo = repo_with()
    job = await new_repair(repo)
    await assign(repo, job, body(T1))
    snapshot = (copy.deepcopy(v2_rows(repo)), copy.deepcopy(repo._personnel_master),
                repo._repairs[job].model_dump(), list(repo.registry_write_log))
    repo.calls.clear()
    for user in (U1, U2, "USR-NOBODY", None):
        await work(repo, user)
        await get_my_work(repo, user)
    assert set(repo.calls) <= {"read_user_account_reference", "read_personnel_relationship_master",
                               "read_technician_master_reference", "read_work_assignment_v2_rows", "get_repair",
                               "get_pm_work_order"}
    assert (v2_rows(repo), repo._personnel_master, repo._repairs[job].model_dump(),
            repo.registry_write_log) == snapshot


@pytest.mark.asyncio
async def test_r2fh2_ro_02_my_work_does_not_depend_on_or_enable_the_cutover() -> None:
    from app.config import Settings

    repo = repo_with()
    job = await new_repair(repo)  # created while the cutover was ON (fixture)
    await assign(repo, job, body(T1))
    assert Settings(_env_file=None).technician_assignment_v2_enabled is False
    for v2 in (False, True):
        payload = (await http("GET", f"{API}/my-work", repo, role="TECHNICIAN", user=U1, request_id=None,
                              v2=v2)).json()
        assert [i["job_id"] for i in payload["items"]] == [job]
    assert Settings(_env_file=None).technician_assignment_v2_enabled is False


def test_r2fh2_ro_03_no_production_master_data_is_seeded() -> None:
    from app.repositories.mock.repository import MockRepository

    repo = MockRepository()
    assert repo._technician_assignment_rows == {"REPAIR": [], "PM": []}
    assert REPAIR.key == "REPAIR" and PM.key == "PM"
    import inspect

    import app.domain.my_work as module

    source = inspect.getsource(module)
    for forbidden in ('"first_name"', '"last_name"', '"email"', '"phone"', ".startswith(", ".lower(", ".casefold(",
                      "seed_data"):
        assert forbidden not in source, forbidden
