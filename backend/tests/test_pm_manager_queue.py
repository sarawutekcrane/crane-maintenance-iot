"""R4 / TASK-010 — PM manager fleet Work Order queue
(GET /api/v1/pm/work-orders/v2-manager-queue), mock / service level.

Reuses the V2 waiting-assignment machinery and its test helpers. Every row is
SYNTHETIC. B1..B15 follow the Owner's acceptance list."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.technician_assignment import PM
from tests.pm_e01_support import manager, rid, save, scope_of, start, submit
from tests.test_relationship_read_batch_r2f_a import REFERENCE_SCOPE_REAL, tech
from tests.test_technician_assignment_batch_r2f_h1 import (
    T1,
    T2,
    T3,
    assign,
    body,
    new_pm,
    new_repair,
    pm_service,
    repo_with,
    tt,
    v2_rows,
)
from tests.test_v2_waiting_assignment_batch_r2f_h4_b3 import (
    API,
    PM_Q,
    READS,
    REAL,
    REPAIR_Q,
    call,
    code,
    doctor,
    job_fail,
    queue,
    set_job,
)

MQ = f"{API}/pm/work-orders/v2-manager-queue"


def rows_of(response) -> list[tuple[str, str, str]]:
    assert response.status_code == 200, response.text
    return [(i["pm_work_order_id"], i["status"], i["assignment_status"]) for i in response.json()["items"]]


def entry(response, job_id: str) -> dict:
    return next(i for i in response.json()["items"] if i["pm_work_order_id"] == job_id)


async def jobs_in_every_status(repo) -> dict[str, str]:
    """One V2 PM work order per E01 status (header projection set directly)."""
    jobs = {}
    for status in S:
        job_id = await new_pm(repo)
        set_job(repo, "PM", job_id, status=status)
        jobs[status.value] = job_id
    return jobs


# ---------------------------------------------------------------- B1 / B2 authorization and context before any read


@pytest.mark.asyncio
async def test_b1_capability_first_with_zero_queue_reads() -> None:
    from app.domain import authz

    for role, caps in authz.ROLE_CAPABILITIES.items():
        repo = repo_with()
        repo.calls.clear()
        response = await call(MQ, repo, role=role)
        if authz.CAN_MANAGE_PM in caps:
            assert response.status_code == 200, role
        else:
            assert response.status_code == 403 and repo.calls == [], role
    repo = repo_with()
    repo.calls.clear()
    # 403 before the status validation and before the context check: nothing about the queue is revealed.
    denied = await call(f"{MQ}?status=CLOSED", repo, role="NO_SUCH_ROLE", settings=Settings(data_repository="google_sheets"))
    assert denied.status_code == 403 and repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [Settings(data_repository="google_sheets"),
                                      Settings(data_repository="google_sheets", registry_data_context="TEST")])
async def test_b2_unconfigured_context_is_503_with_zero_reads(settings) -> None:
    repo = repo_with()
    repo.calls.clear()
    assert code(await call(MQ, repo, settings=settings)) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert repo.calls == []


# ---------------------------------------------------------------- B3 / B4 statuses and the filter


@pytest.mark.asyncio
async def test_b3_only_the_three_in_progress_e01_statuses_are_listed() -> None:
    repo = repo_with()
    jobs = await jobs_in_every_status(repo)
    response = await call(MQ, repo)
    assert {j: s for j, s, _ in rows_of(response)} == {
        jobs["OPEN"]: "OPEN", jobs["IN_PROGRESS"]: "IN_PROGRESS", jobs["PENDING_REVIEW"]: "PENDING_REVIEW"}
    assert response.json()["total_items"] == 3 and response.json()["data_context"] == "TEST"
    assert set(entry(response, jobs["OPEN"])) == {
        "pm_work_order_id", "asset_type", "asset_id", "status", "opened_at", "assignment_status",
        "primary_technician", "collaborators", "issues"}


@pytest.mark.asyncio
async def test_b4_status_filter_is_applied_before_paging_and_invalid_values_are_422() -> None:
    repo = repo_with()
    in_progress = []
    for _ in range(3):
        job_id = await new_pm(repo)
        set_job(repo, "PM", job_id, status=S.IN_PROGRESS)
        in_progress.append(job_id)
    for _ in range(4):
        await new_pm(repo)  # OPEN
    filtered = await call(f"{MQ}?status=IN_PROGRESS&page_size=2", repo)
    body_ = filtered.json()
    assert (body_["total_items"], len(body_["items"])) == (3, 2)
    assert {i["status"] for i in body_["items"]} == {"IN_PROGRESS"}
    second = (await call(f"{MQ}?status=IN_PROGRESS&page_size=2&page=2", repo)).json()
    assert len(second["items"]) == 1
    assert {i["pm_work_order_id"] for i in body_["items"] + second["items"]} == set(in_progress)
    assert (await call(f"{MQ}?status=PENDING_REVIEW", repo)).json()["total_items"] == 0
    for bad in ("CLOSED", "CANCELLED", "open", "WAITING", ""):
        repo.calls.clear()
        response = await call(f"{MQ}?status={bad}", repo)
        assert code(response) == (422, "VALIDATION_ERROR"), bad
        assert repo.calls == [], bad  # validated before any read


# ---------------------------------------------------------------- B5 scope isolation


@pytest.mark.asyncio
async def test_b5_real_test_batch_and_other_batches_are_isolated_before_paging() -> None:
    repo = repo_with()
    mine, other_batch, real = await new_pm(repo), await new_pm(repo), await new_pm(repo)
    set_job(repo, "PM", other_batch, test_batch_id="SYN-OTHER-BATCH")
    set_job(repo, "PM", real, is_test_data="FALSE", test_batch_id="")
    test_view = await call(f"{MQ}?page_size=1", repo)
    assert [j for j, _, _ in rows_of(test_view)] == [mine] and test_view.json()["total_items"] == 1
    real_view = await call(MQ, repo, settings=REAL)
    assert [j for j, _, _ in rows_of(real_view)] == [real] and real_view.json()["data_context"] == "REAL"
    for query in ("scope=REAL", "data_context=REAL", "test_batch_id=SYN-OTHER-BATCH", "is_test_data=FALSE"):
        assert [j for j, _, _ in rows_of(await call(f"{MQ}?{query}", repo))] == [mine], query


# ---------------------------------------------------------------- B6 ordering, ties, totals, paging edges


@pytest.mark.asyncio
async def test_b6_newest_first_ties_by_id_and_exact_paging() -> None:
    repo = repo_with()
    jobs = [await new_pm(repo) for _ in range(5)]
    base = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    stamps = [base, base + timedelta(hours=2), base + timedelta(hours=2), base + timedelta(hours=1), base]
    for job_id, at, status in zip(jobs, stamps, (S.OPEN, S.IN_PROGRESS, S.PENDING_REVIEW, S.OPEN, S.IN_PROGRESS)):
        set_job(repo, "PM", job_id, opened_at=at, status=status)
    expected = sorted(jobs, key=lambda j: (repo._pm_work_orders[j].opened_at, j), reverse=True)
    pages = [(await call(f"{MQ}?page={p}&page_size=2", repo)).json() for p in (1, 2, 3, 4)]
    assert [i["pm_work_order_id"] for p in pages for i in p["items"]] == expected
    assert [len(p["items"]) for p in pages] == [2, 2, 1, 0]
    assert {p["total_items"] for p in pages} == {5} and [p["page"] for p in pages] == [1, 2, 3, 4]


# ---------------------------------------------------------------- B7 / B8 assignment state and team identity


@pytest.mark.asyncio
async def test_b7_b8_valid_team_with_scoped_names_and_none_ambiguous_invalid() -> None:
    repo = repo_with()
    valid, none, ambiguous, invalid = [await new_pm(repo) for _ in range(4)]
    await assign(repo, valid, body(T1, T2), kind=PM)
    await assign(repo, ambiguous, body(T1), kind=PM)
    await assign(repo, ambiguous, body(T2, expected=(T1,)), kind=PM)
    await assign(repo, invalid, body(T1, T2), kind=PM)
    rows = v2_rows(repo, "PM")
    amb = [r for r in rows if r["pm_work_order_id"] == ambiguous]
    amb[1]["assigned_at"] = amb[0]["assigned_at"]  # two latest sets share one instant
    inv = [r for r in rows if r["pm_work_order_id"] == invalid]
    inv[1]["assignee_id"] = T3  # digest mismatch: job-attributable
    # An identical technician id in ANOTHER batch / REAL scope must never supply a name.
    repo._technician_master += [tech(T1, first="ห้ามแสดง", last="อื่น", scope=REFERENCE_SCOPE_REAL)]
    response = await call(MQ, repo)
    states = {j: a for j, _, a in rows_of(response)}
    assert states == {valid: "VALID", none: "NONE", ambiguous: "AMBIGUOUS", invalid: "DATA_INVALID"}
    team = entry(response, valid)
    expected_name = " ".join((tt(T1).values["first_name"], tt(T1).values["last_name"]))
    assert team["primary_technician"] == {"technician_id": T1, "display_name": expected_name}
    assert [c["technician_id"] for c in team["collaborators"]] == [T2] and team["issues"] == {}
    assert "ห้ามแสดง" not in response.text
    for job_id in (none, ambiguous, invalid):  # never a guessed or partial team
        assert (entry(response, job_id)["primary_technician"], entry(response, job_id)["collaborators"]) == (None, [])
    assert "SET_DIGEST_MISMATCH" in entry(response, invalid)["issues"]
    # The current team comes from the V2 assignment rows, never the denormalized work order fields.
    set_job(repo, "PM", none, primary_technician=T3, collaborators=[T1])
    assert entry(await call(MQ, repo), none)["assignment_status"] == "NONE"


@pytest.mark.asyncio
async def test_b8_a_blank_name_is_null_never_invented() -> None:
    repo = repo_with(technicians=[tt(T1, first="", last=""), tt(T2), tt(T3)])
    job_id = await new_pm(repo)
    await assign(repo, job_id, body(T1), kind=PM)
    assert entry(await call(MQ, repo), job_id)["primary_technician"] == {"technician_id": T1, "display_name": None}


# ---------------------------------------------------------------- B9 / B10 fail closed, never a partial queue


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", ["WAITING", "", "open", "Closed"])
async def test_b9_invalid_status_of_an_in_scope_job_fails_the_whole_queue(stored) -> None:
    repo = repo_with()
    job_id, _ = await new_pm(repo), await new_pm(repo)
    doctor(repo, {job_id: {"status": stored}})
    job_fail(await call(MQ, repo), {"JOB_STATUS_INVALID": 1}, job_id, "VEH-")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["IN_PROGRESS", "PENDING_REVIEW"])
async def test_b9_a_listed_job_without_a_valid_opened_at_fails_even_under_another_filter(status) -> None:
    repo = repo_with()
    job_id, _ = await new_pm(repo), await new_pm(repo)
    doctor(repo, {job_id: {"status": status, "opened_at": "not-a-time"}})
    job_fail(await call(MQ, repo), {"JOB_OPENED_AT_INVALID": 1}, job_id)
    job_fail(await call(f"{MQ}?status=OPEN", repo), {"JOB_OPENED_AT_INVALID": 1}, job_id)  # a filter hides nothing


@pytest.mark.asyncio
@pytest.mark.parametrize("cells", [{"is_test_data": ""}, {"is_test_data": "YES"},
                                   {"is_test_data": "FALSE", "test_batch_id": "X"}])
async def test_b9_unprovable_job_scope_fails_the_whole_queue(cells) -> None:
    repo = repo_with()
    job_id = await new_pm(repo)
    doctor(repo, {job_id: cells})
    job_fail(await call(MQ, repo), {"JOB_SCOPE_FLAG_INVALID": 1}, job_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "expected"), [
    ("unknown_model", ("ASSIGNMENT_MODEL_DATA_INVALID", "ASSIGNMENT_MODEL_UNKNOWN")),
    ("orphan_row", ("TECHNICIAN_ASSIGNMENT_DATA_INVALID", "V2_ROW_JOB_MISSING")),
    ("duplicate_row", ("TECHNICIAN_ASSIGNMENT_DATA_INVALID", "DUPLICATE_RECORD_ID")),
    ("duplicate_job", ("TECHNICIAN_ASSIGNMENT_DATA_INVALID", "JOB_ID_DUPLICATE")),
])
async def test_b9_b10_whole_queue_defects_return_no_partial_queue(damage, expected) -> None:
    repo = repo_with()
    job_id, other = await new_pm(repo), await new_pm(repo)
    await assign(repo, job_id, body(T1), kind=PM)
    rows = v2_rows(repo, "PM")
    if damage == "unknown_model":
        set_job(repo, "PM", other, assignment_model="TECHNICIAN_V3")
    elif damage == "orphan_row":
        rows.append(dict(rows[0], pm_work_order_id="PMWO-NO-SUCH-JOB"))
    elif damage == "duplicate_row":
        rows.append(dict(rows[0]))
    elif damage == "duplicate_job":
        doctor(repo, {other: {"pm_work_order_id": job_id}})
    response = await call(MQ, repo)
    assert response.status_code == 500, response.text
    error = response.json()["error"]
    assert (error["code"], expected[1] in error["details"]["issues"]) == (expected[0], True)
    assert "manager queue" in error["message"] and "items" not in response.json()


# ---------------------------------------------------------------- B11 legacy, B12 read only and bounded reads


@pytest.mark.asyncio
async def test_b11_legacy_jobs_are_never_listed() -> None:
    repo = repo_with()
    v2 = await new_pm(repo)
    legacy = await new_pm(repo, legacy=True)
    listed = [j for j, _, _ in rows_of(await call(MQ, repo))]
    assert listed == [v2] and legacy not in listed


@pytest.mark.asyncio
async def test_b12_read_only_with_exactly_three_reads() -> None:
    repo = repo_with()
    jobs = await jobs_in_every_status(repo)
    await assign(repo, jobs["OPEN"], body(T1, T2), kind=PM)
    before = (copy.deepcopy(repo._pm_work_orders), copy.deepcopy(repo._technician_assignment_rows),
              len(repo.registry_write_log), copy.deepcopy(repo._pm_transitions))
    for query in ("", "?status=OPEN", "?status=PENDING_REVIEW&page=2&page_size=1"):
        repo.calls.clear()
        assert (await call(f"{MQ}{query}", repo)).status_code == 200
        assert repo.calls == READS, query
    assert (repo._pm_work_orders, repo._technician_assignment_rows, len(repo.registry_write_log),
            repo._pm_transitions) == before


# ---------------------------------------------------------------- B13..B15 existing behaviour preserved


@pytest.mark.asyncio
async def test_b13_b14_waiting_queues_keep_their_contract_alongside_the_manager_queue() -> None:
    repo = repo_with()
    jobs = await jobs_in_every_status(repo)
    assigned = await new_pm(repo)
    await assign(repo, assigned, body(T1), kind=PM)
    repair_waiting, repair_assigned = await new_repair(repo), await new_repair(repo)
    await assign(repo, repair_assigned, body(T1))
    # PM waiting: OPEN jobs without a valid team only (never IN_PROGRESS / PENDING_REVIEW / VALID).
    assert queue(await call(PM_Q, repo)) == [(jobs["OPEN"], "NONE")]
    # Repair waiting: unchanged statuses and rule.
    assert queue(await call(REPAIR_Q, repo)) == [(repair_waiting, "NONE")]
    # Manager queue: every in-progress PM job, including the VALID one, and no Repair job.
    listed = {j: a for j, _, a in rows_of(await call(MQ, repo))}
    assert listed == {jobs["OPEN"]: "NONE", jobs["IN_PROGRESS"]: "NONE", jobs["PENDING_REVIEW"]: "NONE",
                      assigned: "VALID"}


@pytest.mark.asyncio
async def test_b15_a_real_e01_start_moves_the_job_and_detail_is_unchanged() -> None:
    repo = repo_with()
    job_id = await new_pm(repo)
    await assign(repo, job_id, body(T1, T2), kind=PM)
    await start(pm_service(repo), job_id)
    response = await call(MQ, repo)
    assert rows_of(response) == [(job_id, "IN_PROGRESS", "VALID")]
    detail = await call(f"{API}/pm/work-orders/{job_id}", repo)
    assert detail.status_code == 200 and detail.json()["work_order"]["status"] == "IN_PROGRESS"
    assert {s.value for s in S} == {"OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CLOSED", "CANCELLED"}


async def _queue_states(repo) -> dict[str, dict[str, str]]:
    """{filter: {job: status}} for All and each status filter, from the API."""
    out = {}
    for name, query in (("ALL", ""), ("OPEN", "?status=OPEN"), ("IN_PROGRESS", "?status=IN_PROGRESS"),
                        ("PENDING_REVIEW", "?status=PENDING_REVIEW")):
        response = await call(f"{MQ}{query}", repo)
        assert response.status_code == 200, response.text
        out[name] = {i["pm_work_order_id"]: i["status"] for i in response.json()["items"]}
        assert response.json()["total_items"] == len(out[name])
    return out


EMPTY_QUEUE: dict[str, dict[str, str]] = {name: {} for name in ("ALL", "OPEN", "IN_PROGRESS", "PENDING_REVIEW")}


def _only(job: str, status: str) -> dict[str, dict[str, str]]:
    """The job listed under All and under its own status filter only."""
    return {**EMPTY_QUEUE, "ALL": {job: status}, status: {job: status}}


@pytest.mark.asyncio
async def test_b15_actual_e01_transitions_move_the_job_through_the_queue_and_out() -> None:
    """START -> SUBMIT -> RETURN -> SUBMIT -> CLOSE, and CANCEL of a separate job,
    all through the real E01 service (no direct status mutation)."""
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await new_pm(repo)
    await assign(repo, job_id, body(T1, T2), kind=PM)
    assert await _queue_states(repo) == _only(job_id, "OPEN")

    await start(svc, job_id)  # by the current PRIMARY (U1)
    assert await _queue_states(repo) == _only(job_id, "IN_PROGRESS")

    for task in await scope_of(repo, job_id):
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)  # by the current PRIMARY
    assert await _queue_states(repo) == _only(job_id, "PENDING_REVIEW")

    await svc.return_for_rework(job_id, manager(), request_id=rid(), reason="แก้ไขเอกสาร (synthetic)")
    assert await _queue_states(repo) == _only(job_id, "IN_PROGRESS")

    await submit(svc, repo, job_id)  # a valid resubmission
    assert await _queue_states(repo) == _only(job_id, "PENDING_REVIEW")

    await svc.close_after_review(job_id, manager(), request_id=rid())
    assert repo._pm_work_orders[job_id].status == S.CLOSED  # persisted by E01, not by the test
    assert await _queue_states(repo) == EMPTY_QUEUE  # gone from every view, not a stale active row

    cancelled = await new_pm(repo)
    await assign(repo, cancelled, body(T1), kind=PM)
    assert await _queue_states(repo) == _only(cancelled, "OPEN")
    await svc.cancel_work_order(cancelled, manager(), request_id=rid(), reason="ยกเลิกงานทดสอบ (synthetic)")
    assert repo._pm_work_orders[cancelled].status == S.CANCELLED
    assert await _queue_states(repo) == EMPTY_QUEUE
    actions = [e.action.value for e in repo._pm_transitions[job_id]]
    assert actions == ["START", "SUBMIT", "RETURN", "SUBMIT", "CLOSE"]
    assert [e.action.value for e in repo._pm_transitions[cancelled]] == ["CANCEL"]


def test_b15_response_schema_only_admits_listed_statuses_and_states() -> None:
    from pydantic import ValidationError

    from app.api.v1.v2_waiting_assignment_routes import V2ManagerItemResponse

    base = {"pm_work_order_id": "PMWO-1", "asset_type": "VEHICLE", "asset_id": "VEH-1", "status": "OPEN",
            "opened_at": datetime(2026, 11, 1, tzinfo=UTC), "assignment_status": "VALID",
            "primary_technician": None, "collaborators": [], "issues": {}}
    V2ManagerItemResponse(**base)
    for bad in ({"status": "CLOSED"}, {"status": "CANCELLED"}, {"assignment_status": "UNKNOWN"}):
        with pytest.raises(ValidationError):
            V2ManagerItemResponse(**{**base, **bad})
