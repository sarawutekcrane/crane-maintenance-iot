"""R5 T4 — OD-2: confirmation of every recorded work-time entry before Repair /
PM CLOSE; zero entries close exactly as before; the gate runs after every existing
check and never on a replay; post-close manager corrections keep the Work Order
CLOSED and need a fresh confirmation (AMB-2: the correcting manager may confirm)."""
from __future__ import annotations

import pytest

from app.domain.asset import AssetType
from app.domain.pm import PmWorkOrderStatus
from app.domain.repair import RepairStatus
from app.domain.work_time import WORK_KIND_PM, WORK_KIND_REPAIR
from app.errors import ApiError
from tests.pm_e01_support import manager as pm_mgr
from tests.pm_e01_support import NOT_PERFORMED, save, scope_of, submit
from tests.test_r5_work_time_api import (
    MANAGER,
    U1,
    confirm,
    correct,
    pm_job_started,
    record,
    repair_job,
    repair_manager,
    rid,
    svc,
    t,
    view,
)
from tests.test_technician_assignment_batch_r2f_h1 import code_of, ctx, pm_service, repair_service, repo_with


async def close_snapshots(repo, asset_id: str) -> list:
    return [s for s in await repo.list_meter_snapshots_for_asset(AssetType.VEHICLE, asset_id)
            if s.source_note in ("REPAIR_CLOSE", "PM_WORK_ORDER_CLOSE")]


async def close_repair(repo, job, request_id=None):
    return await repair_service(repo).close_repair(job, closed_by=MANAGER, close_note=None, context=repair_manager(),
                                                   request_id=request_id)


async def pm_to_review(repo) -> str:
    job = await pm_job_started(repo)
    service = pm_service(repo)
    for task in await scope_of(repo, job):
        await save(service, job, task)
    await submit(service, repo, job)
    return job


@pytest.mark.asyncio
async def test_zero_entries_close_exactly_as_before_for_repair_and_pm() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    closed = await close_repair(repo, job)
    assert closed.repair.status == RepairStatus.CLOSED
    pm = await pm_to_review(repo)
    done = await pm_service(repo).close_after_review(pm, pm_mgr(), request_id=rid())
    assert done.work_order.status == PmWorkOrderStatus.CLOSED


@pytest.mark.asyncio
async def test_repair_close_is_refused_until_every_entry_is_confirmed_and_writes_nothing() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    asset = (await repo.get_repair(job)).repair.asset_id
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    before = await close_snapshots(repo, asset)
    with pytest.raises(ApiError) as refused:
        await close_repair(repo, job)
    assert (refused.value.code, refused.value.status_code) == ("WORK_TIME_NOT_CONFIRMED", 409)
    assert refused.value.details == {"unconfirmed_entries": 1}
    assert (await repo.get_repair(job)).repair.status == RepairStatus.OPEN
    assert await close_snapshots(repo, asset) == before  # gate before the snapshot capture
    await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1))
    assert (await close_repair(repo, job)).repair.status == RepairStatus.CLOSED


@pytest.mark.asyncio
async def test_pm_close_is_refused_until_confirmed_and_no_outstanding_is_created_meanwhile() -> None:
    repo = repo_with()
    job = await pm_job_started(repo)
    entry, _ = await record(svc(repo), WORK_KIND_PM, job, ctx(U1), t(0), t(4))
    service = pm_service(repo)
    tasks = await scope_of(repo, job)
    await save(service, job, tasks[0])
    for task in tasks[1:]:
        await save(service, job, task, disposition=NOT_PERFORMED)
    await submit(service, repo, job)
    assert await code_of(service.close_after_review(job, pm_mgr(), request_id=rid())) == "WORK_TIME_NOT_CONFIRMED"
    detail = await repo.get_pm_work_order(job)
    assert detail.work_order.status == PmWorkOrderStatus.PENDING_REVIEW
    assert await repo.list_pm_outstanding_items(job) == []  # refused before any Outstanding record
    await confirm(svc(repo), WORK_KIND_PM, job, pm_mgr(), (entry.entry_id, 1))
    closed = await service.close_after_review(job, pm_mgr(), request_id=rid())
    assert closed.work_order.status == PmWorkOrderStatus.CLOSED
    assert len(await repo.list_pm_outstanding_items(job)) == len(tasks) - 1  # existing E01 behaviour intact


@pytest.mark.asyncio
async def test_the_gate_runs_after_the_existing_checks() -> None:
    repo = repo_with()
    pm = await pm_to_review(repo)
    await record(svc(repo), WORK_KIND_PM, pm, ctx(U1), t(0), t(1))
    from fastapi import HTTPException

    with pytest.raises(HTTPException):  # authority first (403), not the work-time gate
        await pm_service(repo).close_after_review(pm, ctx(U1), request_id=rid())
    job = await repair_job(repo)
    await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(10), t(11))
    repo._repairs[job] = repo._repairs[job].model_copy(update={"finding_id": "F-SYN-R5"})
    finding_manager = ctx(MANAGER, "can_manage_finding_repair", "can_close_repair")
    assert await code_of(repair_service(repo).close_repair(job, closed_by=MANAGER, close_note=None,
                                                           context=finding_manager)) == \
        "REPAIR_COMPLETION_NOT_SUBMITTED"  # the R3 TS-4 rule still comes first


@pytest.mark.asyncio
async def test_post_close_correction_keeps_the_work_order_closed_and_needs_a_new_confirmation() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1))
    request_id = rid()
    closed = (await close_repair(repo, job, request_id=request_id)).repair
    assert await code_of(record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(5), t(6))) == "WORK_TIME_WINDOW_CLOSED"
    assert await code_of(correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, ctx(U1), 1, t(0), t(5))) == \
        "WORK_TIME_CORRECTION_FORBIDDEN"
    corrected, _ = await correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, repair_manager(), 1, t(0), t(3),
                                 reason="ปิดงานแล้วพบเวลาเกิน 1 ชม.")
    after = (await repo.get_repair(job)).repair
    assert after.status == RepairStatus.CLOSED
    assert (after.closed_at, after.closed_by, after.closed_snapshot_id) == (
        closed.closed_at, closed.closed_by, closed.closed_snapshot_id)
    assert (await view(repo, WORK_KIND_REPAIR, job))["unconfirmed_count"] == 1
    # A replay of the completed close is not re-gated by the later correction.
    replayed = await close_repair(repo, job, request_id=request_id)
    assert replayed.repair.closed_snapshot_id == closed.closed_snapshot_id
    # AMB-2: the manager who corrected may confirm the corrected revision.
    await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, corrected.revision))
    assert (await view(repo, WORK_KIND_REPAIR, job))["unconfirmed_count"] == 0


@pytest.mark.asyncio
async def test_pm_post_close_correction_and_close_replay() -> None:
    repo = repo_with()
    job = await pm_job_started(repo)
    entry, _ = await record(svc(repo), WORK_KIND_PM, job, ctx(U1), t(0), t(4))
    service = pm_service(repo)
    for task in await scope_of(repo, job):
        await save(service, job, task)
    await submit(service, repo, job)
    await confirm(svc(repo), WORK_KIND_PM, job, pm_mgr(), (entry.entry_id, 1))
    request_id = rid()
    closed = await service.close_after_review(job, pm_mgr(), request_id=request_id)
    await correct(svc(repo), WORK_KIND_PM, job, entry.entry_id, pm_mgr(), 1, t(0), t(3))
    again = await service.close_after_review(job, pm_mgr(), request_id=request_id)
    assert again.work_order.status == PmWorkOrderStatus.CLOSED
    assert again.work_order.closed_snapshot_id == closed.work_order.closed_snapshot_id
    assert (await view(repo, WORK_KIND_PM, job))["unconfirmed_count"] == 1
