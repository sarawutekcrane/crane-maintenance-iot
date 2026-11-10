"""R5 T3b — OD-1: Technician V2 team changes on a PM Work Order while IN_PROGRESS.

Allowed in OPEN (unchanged) and IN_PROGRESS; refused in PENDING_REVIEW, CLOSED and
CANCELLED with the existing 409 TECHNICIAN_ASSIGNMENT_JOB_CLOSED. Same work order,
append-only set history, stale-set and replay protection unchanged. Repair keeps
the D1 rule (exactly OPEN)."""
from __future__ import annotations

import pytest

from app.domain.pm import PmWorkOrderStatus
from app.domain.technician_assignment import PM, REPAIR
from tests.pm_e01_support import close, manager, save, scope_of, submit, v2_job
from tests.pm_e01_support import start as pm_start
from tests.test_r5_work_time_api import rid
from tests.test_technician_assignment_batch_r2f_h1 import (
    T1,
    T2,
    T3,
    U1,
    U3,
    assign,
    body,
    code_of,
    ctx,
    pm_service,
    repo_with,
    ta_service,
)


async def started_pm(repo) -> str:
    job = await v2_job(repo)
    await pm_start(pm_service(repo), job)
    assert (await repo.get_pm_work_order(job)).work_order.status == PmWorkOrderStatus.IN_PROGRESS
    return job


async def withdraw(repo, job, expected=(T1, T2), request_id=None):
    payload = {"expected_current": {"primary_technician_id": expected[0],
                                    "collaborator_technician_ids": list(expected[1:])}}
    return await ta_service(repo).withdraw(PM, job, payload, request_id=request_id or rid(), user_id="dev-user")


@pytest.mark.asyncio
async def test_in_progress_reassignment_keeps_the_same_work_order_and_its_history() -> None:
    repo = repo_with()
    job = await started_pm(repo)
    outcome = await assign(repo, job, body(T3, T2, expected=(T1, T2)), kind=PM)
    assert outcome.changed and outcome.current.primary_technician_id == T3
    state = (await ta_service(repo).read(PM, job)).state
    assert [s.primary_technician_id for s in state.sets] == [T1, T3]  # append-only history
    assert (await repo.get_pm_work_order(job)).work_order.pm_work_order_id == job


@pytest.mark.asyncio
async def test_the_new_primary_submits_and_the_former_primary_lost_authority() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job = await started_pm(repo)
    await assign(repo, job, body(T3, T2, expected=(T1, T2)), kind=PM)
    for task in await scope_of(repo, job):
        await save(svc, job, task, context=ctx(U3))
    assert await code_of(submit(svc, repo, job, context=ctx(U1))) == "PM_SUBMIT_PRIMARY_ONLY"
    submitted = await submit(svc, repo, job, context=ctx(U3))
    assert submitted.work_order.status == PmWorkOrderStatus.PENDING_REVIEW


@pytest.mark.asyncio
async def test_pending_review_closed_and_cancelled_refuse_team_changes() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job = await started_pm(repo)
    for task in await scope_of(repo, job):
        await save(svc, job, task)
    await submit(svc, repo, job)
    assert await code_of(assign(repo, job, body(T3, expected=(T1, T2)), kind=PM)) == \
        "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"
    assert await code_of(withdraw(repo, job)) == "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"
    await close(svc, job)
    assert await code_of(assign(repo, job, body(T3, expected=(T1, T2)), kind=PM)) == \
        "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"
    other = await v2_job(repo)
    await svc.cancel_work_order(other, manager(), request_id=rid(), reason="ยกเลิกทดสอบ")
    assert await code_of(assign(repo, other, body(T3, expected=(T1, T2)), kind=PM)) == \
        "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"


@pytest.mark.asyncio
async def test_in_progress_withdrawal_stale_set_and_replay_follow_the_existing_v2_rules() -> None:
    repo = repo_with()
    job = await started_pm(repo)
    assert await code_of(assign(repo, job, body(T3, expected=(T2, T1)), kind=PM)) == "TECHNICIAN_ASSIGNMENT_STALE"
    request_id = rid()
    first = await assign(repo, job, body(T3, expected=(T1, T2)), kind=PM, request_id=request_id)
    again = await assign(repo, job, body(T3, expected=(T1, T2)), kind=PM, request_id=request_id)
    assert first.changed and again.replayed
    withdrawn = await withdraw(repo, job, expected=(T3,))
    assert withdrawn.changed
    assert (await ta_service(repo).read(PM, job)).state.current is None


@pytest.mark.asyncio
async def test_repair_keeps_the_exactly_open_rule() -> None:
    from tests.test_r5_work_time_api import repair_job, repair_manager
    from tests.test_technician_assignment_batch_r2f_h1 import repair_service

    repo = repo_with()
    job = await repair_job(repo)
    await repair_service(repo).close_repair(job, closed_by="m", close_note=None, context=repair_manager())
    assert await code_of(assign(repo, job, body(T3, expected=(T1, T2)), kind=REPAIR)) == \
        "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"
