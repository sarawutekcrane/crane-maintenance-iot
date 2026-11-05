"""R4 PM Workflow — operation serialization (corrected plan C-1) and the
mandatory RR-1 gate. Synthetic data only; no live Google Sheets.

The Mock repository never yields inside a call, so its service operations
never interleave. `yielding()` injects `await asyncio.sleep(0)` around every
repository coroutine (what the Sheets adapter's `asyncio.to_thread` I/O does),
which makes the interleavings R1..R4 real. Each race is shown WITHOUT the
locks (the defect reproduces: proof the test can see it) and WITH them (the
invariant holds).

RR-1 (EV-048, closed): PM evidence upload (`InspectionService`) and manual
Store requests (`MaterialRequestService`) now run their write under the SAME
per-work-order lock L1 as every PM transition, gated on the authoritative
(journal) status: evidence only while IN_PROGRESS, Store requests only while
OPEN / IN_PROGRESS. The tests below prove the refusal sequentially, in both
directions of CANCEL's eligibility window, through the real HTTP routes, on the
fake Sheets adapter, under a lagging projection, and across failures/retries."""
from __future__ import annotations

import asyncio
import contextlib
import inspect
from dataclasses import dataclass

import pytest

from app.config import Settings
from app.domain.asset import AssetType
from app.domain.attachment import AttachmentPurpose
from app.domain.inspection_service import InspectionService
from app.domain.material_request_service import (
    MaterialRequestService,
    RequisitionLineInput,
)
from app.domain.pm import PmItemContractDisposition as Disposition
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.requisition import RequisitionSourceType
from app.errors import ApiError
from app.repositories.base import KeyedTaskReentrantLocks, Repository, TaskReentrantLock
from app.repositories.google_sheets.repository import GoogleSheetsRepository
from tests.pm_e01_support import (
    U1,
    ctx,
    manager,
    pm_service,
    repo_with,
    rid,
    save,
    scope_of,
    start,
    submit,
    v2_job,
)
from tests.test_r4_pm_wf_sheets_parity import TASKS, build, new_job, sheets_repo

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def yielding(repo):
    """Every public repository coroutine yields to the event loop before and
    after it runs (instance attributes shadow the class methods)."""
    for name, member in inspect.getmembers(type(repo)):
        if name.startswith("_") or not inspect.iscoroutinefunction(member):
            continue
        bound = getattr(repo, name)

        async def wrapper(*args, __bound=bound, **kwargs):
            await asyncio.sleep(0)
            try:
                return await __bound(*args, **kwargs)
            finally:
                await asyncio.sleep(0)

        setattr(repo, name, wrapper)
    return repo


@pytest.fixture
def no_locks(monkeypatch):
    """Remove L1 and L2 (the 'without locks' baseline)."""
    monkeypatch.setattr(Repository, "pm_work_order_lock", lambda self, key: contextlib.nullcontext())
    monkeypatch.setattr(GoogleSheetsRepository, "_write_lock", lambda self: contextlib.nullcontext())


async def settle(*awaitables):
    """Run concurrently; return results or the exceptions (never hang)."""
    return await asyncio.wait_for(asyncio.gather(*awaitables, return_exceptions=True), timeout=10)


async def in_progress(repo):
    svc = pm_service(repo)
    job = await v2_job(repo)
    await start(svc, job)
    return svc, job


def results_for(repo, job, task=None):
    return [r for r in repo._pm_work_results.get(job, []) if task is None or r.pm_task_id == task]


# ---------------------------------------------------------------------------
# L1 / L2 primitives
# ---------------------------------------------------------------------------


async def test_task_reentrant_lock_excludes_other_tasks_and_reenters_in_its_own() -> None:
    lock = TaskReentrantLock()
    inside = 0
    peak = 0

    async def worker():
        nonlocal inside, peak
        await lock.acquire()
        await lock.acquire()  # re-entry by the owning task never blocks
        inside += 1
        peak = max(peak, inside)
        await asyncio.sleep(0)
        inside -= 1
        lock.release()
        lock.release()

    await settle(*(worker() for _ in range(20)))
    assert peak == 1 and lock.idle


async def test_keyed_locks_serialize_one_key_run_different_keys_concurrently_and_are_dropped_when_idle() -> None:
    locks = KeyedTaskReentrantLocks()
    order: list[str] = []
    gate = asyncio.Event()

    async def hold(key, tag, wait=False):
        async with locks.hold(key):
            order.append(f"{tag}+")
            if wait:
                await gate.wait()
            order.append(f"{tag}-")

    first = asyncio.create_task(hold("W1", "a", wait=True))
    await asyncio.sleep(0)
    other_key = asyncio.create_task(hold("W2", "b"))
    same_key = asyncio.create_task(hold("W1", "c"))
    await asyncio.sleep(0.01)
    assert order == ["a+", "b+", "b-"]  # W2 is not blocked by W1; the second W1 holder waits
    gate.set()
    await settle(first, other_key, same_key)
    assert order[3:] == ["a-", "c+", "c-"]
    assert not locks._locks  # nothing retained once idle


async def test_a_cancelled_waiter_never_leaks_the_lock() -> None:
    locks = KeyedTaskReentrantLocks()
    gate = asyncio.Event()

    async def holder():
        async with locks.hold("W1"):
            await gate.wait()

    async def waiter():
        async with locks.hold("W1"):
            pass

    held = asyncio.create_task(holder())
    await asyncio.sleep(0)
    pending = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    pending.cancel()
    gate.set()
    await settle(held, pending)
    async with locks.hold("W1"):
        pass
    assert not locks._locks


async def test_l1_is_held_for_the_whole_service_operation() -> None:
    repo = yielding(repo_with())
    svc, job = await in_progress(repo)
    held = []
    original = repo.create_pm_work_result

    async def probe(*args, **kwargs):
        locks = repo.__dict__["_pm_work_order_locks"]._locks
        held.append(job in locks and not locks[job].idle)
        return await original(*args, **kwargs)

    repo.create_pm_work_result = probe
    await save(svc, job, (await scope_of(repo, job))[0])
    assert held == [True]


# ---------------------------------------------------------------------------
# R1 two item saves for the same task
# ---------------------------------------------------------------------------


async def _r1(repo):
    svc, job = await in_progress(repo)
    task = (await scope_of(repo, job))[0]
    outcomes = await settle(save(svc, job, task), save(svc, job, task))
    return job, task, outcomes


async def test_r1_without_locks_two_saves_write_two_results_for_one_item(no_locks) -> None:
    repo = yielding(repo_with())
    job, task, _ = await _r1(repo)
    assert len(results_for(repo, job, task)) == 2  # the defect is real without L1


async def test_r1_with_l1_one_result_one_outcome_and_the_second_save_replays() -> None:
    repo = yielding(repo_with())
    job, task, outcomes = await _r1(repo)
    assert not [o for o in outcomes if isinstance(o, BaseException)]
    assert len(results_for(repo, job, task)) == 1
    assert sorted((o.result_replayed, o.outcome_replayed) for o in outcomes) == [(False, False), (True, True)]
    assert len(await repo.list_pm_item_outcomes(job)) == 1


# ---------------------------------------------------------------------------
# R2 CANCEL eligibility vs an item save
# ---------------------------------------------------------------------------


async def _r2(repo):
    svc, job = await in_progress(repo)
    task = (await scope_of(repo, job))[0]
    outcomes = await settle(svc.cancel_work_order(job, manager(), request_id=rid(), reason="ยกเลิก (synthetic)"),
                            save(svc, job, task))
    detail = await repo.get_pm_work_order(job)
    return job, detail, outcomes


async def test_r2_without_locks_a_cancelled_work_order_gains_a_result(no_locks) -> None:
    repo = yielding(repo_with())
    job, detail, _ = await _r2(repo)
    assert detail.work_order.status == S.CANCELLED and results_for(repo, job)  # eligibility broken


async def test_r2_with_l1_cancelled_never_coexists_with_a_result() -> None:
    repo = yielding(repo_with())
    job, detail, outcomes = await _r2(repo)
    cancelled = detail.work_order.status == S.CANCELLED
    assert cancelled != bool(results_for(repo, job))  # exactly one of the two operations won
    assert sum(isinstance(o, ApiError) for o in outcomes) == 1


# ---------------------------------------------------------------------------
# R3 read-reconcile of a lagging CLOSE vs the retry of the same CLOSE
# ---------------------------------------------------------------------------


async def _lagging_close(repo):
    svc = pm_service(repo)
    job = await v2_job(repo)
    await start(svc, job)
    for task in await scope_of(repo, job):
        await save(svc, job, task)
    await submit(svc, repo, job)
    close_id = rid()
    repo.fail = {"set_pm_work_order_status": RuntimeError("synthetic lost status write")}
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job, manager(), request_id=close_id)
    repo.fail = {}
    return svc, job, close_id


def close_captures(repo, job):
    return [s for s in repo._meter_snapshots.values() if s.source_note == "PM_WORK_ORDER_CLOSE"]


async def _r3(repo):
    svc, job, close_id = await _lagging_close(repo)
    yielding(repo)
    outcomes = await settle(svc.list_work_order_history(job, ctx(U1)),
                            svc.close_after_review(job, manager(), request_id=close_id))
    return job, outcomes


async def test_r3_without_locks_two_reconcilers_race_on_one_close(no_locks) -> None:
    repo = repo_with()
    job, outcomes = await _r3(repo)
    defects = len(close_captures(repo, job)) > 1 or any(isinstance(o, BaseException) for o in outcomes)
    assert defects  # an orphan capture or a spurious conflict to one caller


async def test_r3_with_l1_one_capture_and_both_callers_succeed() -> None:
    repo = repo_with()
    job, outcomes = await _r3(repo)
    assert not [o for o in outcomes if isinstance(o, BaseException)]
    assert len(close_captures(repo, job)) == 1
    assert (await repo.get_pm_work_order(job)).work_order.status == S.CLOSED


# ---------------------------------------------------------------------------
# R4 id allocation on (fake) Google Sheets: L2
# ---------------------------------------------------------------------------


async def _r4():
    backend = build()
    repo = sheets_repo(backend)
    await settle(*(repo.create_meter_snapshot(AssetType.VEHICLE, "VEH-SYN-1", [], U1, is_automatic=True)
                   for _ in range(4)))
    return [r["meter_snapshot_id"] for r in backend.rows("meter_snapshot")]


async def test_r4_without_l2_concurrent_captures_allocate_duplicate_ids(no_locks) -> None:
    ids = await _r4()
    assert len(ids) == 4 and len(set(ids)) < 4


async def test_r4_with_l2_every_concurrent_capture_gets_its_own_id() -> None:
    ids = await _r4()
    assert sorted(ids) == ["MSNAP-0001", "MSNAP-0002", "MSNAP-0003", "MSNAP-0004"]


async def test_r4_sheets_item_saves_on_different_work_orders_allocate_distinct_result_ids() -> None:
    backend = build()
    repo = sheets_repo(backend)
    jobs = [await new_job(repo) for _ in range(2)]
    from tests.test_r4_pm_wf_sheets_parity import save as sheets_save
    from tests.test_r4_pm_wf_sheets_parity import service
    svc = service(repo)
    for job in jobs:
        await svc.start_work_order(job, ctx(U1), request_id=rid())
    outcomes = await settle(*(sheets_save(svc, job, TASKS[0]) for job in jobs))
    assert not [o for o in outcomes if isinstance(o, BaseException)]
    ids = [r["pm_work_result_id"] for r in backend.rows("pm_work_result")]
    assert len(ids) == 2 == len(set(ids))


async def test_sheets_concurrent_same_item_saves_write_one_result_and_one_outcome() -> None:
    backend = build()
    repo = sheets_repo(backend)
    job = await new_job(repo)
    from tests.test_r4_pm_wf_sheets_parity import save as sheets_save
    from tests.test_r4_pm_wf_sheets_parity import service
    svc = service(repo)
    await svc.start_work_order(job, ctx(U1), request_id=rid())
    outcomes = await settle(*(sheets_save(svc, job, TASKS[0]) for _ in range(3)))
    assert not [o for o in outcomes if isinstance(o, BaseException)]
    assert len(backend.rows("pm_work_result")) == 1
    assert len(await repo.list_pm_item_outcomes(job)) == 1


# ---------------------------------------------------------------------------
# Deadlock freedom: cross-resolutions and L1 nesting
# ---------------------------------------------------------------------------


async def test_cross_resolutions_never_deadlock_and_no_task_holds_two_work_order_locks() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    jobs = []
    for _ in range(2):
        job = await v2_job(repo)
        await start(svc, job)
        tasks = await scope_of(repo, job)
        for task in tasks[:-1]:
            await save(svc, job, task)
        await save(svc, job, tasks[-1], Disposition.NOT_PERFORMED)
        await submit(svc, repo, job)
        await svc.close_after_review(job, manager(), request_id=rid())
        jobs.append(job)
    items = [next(i for i in repo._pm_outstanding.values() if i.pm_work_order_id == job) for job in jobs]
    later = [next(r for r in repo._pm_work_results[job] if r.pm_task_id == items[0].pm_task_id) for job in jobs]
    for job in jobs:  # both projections lag one CLOSE event: every status read must reconcile under L1
        repo._pm_work_orders[job] = repo._pm_work_orders[job].model_copy(update={"status": S.PENDING_REVIEW})
    yielding(repo)
    held: dict[asyncio.Task, set[str]] = {}
    acquired: dict[asyncio.Task, list[str]] = {}
    nested: list[set[str]] = []
    original = Repository.pm_work_order_lock

    @contextlib.asynccontextmanager
    async def recording(key):
        async with original(repo, key):
            task = asyncio.current_task()
            mine = held.setdefault(task, set())
            if mine - {key}:
                nested.append(mine | {key})
            mine.add(key)
            acquired.setdefault(task, []).append(key)
            try:
                yield
            finally:
                mine.discard(key)

    repo.pm_work_order_lock = recording
    resolutions = [asyncio.create_task(svc.resolve_outstanding(  # O1 source W1 / later W2, O2 source W2 / later W1
        items[i].outstanding_id, manager(), later_pm_work_result_id=later[1 - i].pm_work_result_id,
        evidence_attachment_ids=("ATT-SYN-1",))) for i in (0, 1)]
    outcomes = await settle(*resolutions, svc.list_work_order_history(jobs[0], ctx(U1)),
                            svc.list_work_order_history(jobs[1], ctx(U1)))
    assert len(outcomes) == 4  # every call completed (a result or a deterministic refusal) within the timeout
    assert nested == []  # no task ever held two different work-order locks
    assert set().union(*(acquired.get(t, []) for t in resolutions)) == set(jobs)  # the resolutions reconciled under L1
    assert all(repo._pm_work_orders[job].status == S.CLOSED for job in jobs)


# ---------------------------------------------------------------------------
# RR-1 cross-service writers (PM evidence upload, manual Store requests)
# ---------------------------------------------------------------------------


@dataclass
class _Stored:
    storage_ref: str
    content_type: str
    size_bytes: int


class _Storage:
    def __init__(self):
        self.saved = 0

    async def save(self, *, filename, content_type, data):
        await asyncio.sleep(0)
        self.saved += 1
        return _Stored(f"synthetic://{filename}", content_type, len(data))


def uploads(repo, storage=None):
    return InspectionService(repo, storage or _Storage(), Settings())


async def upload_evidence(repo, job, context=None, storage=None):
    return await uploads(repo, storage).upload_attachment(
        AttachmentPurpose.PM_EVIDENCE, "e.jpg", "image/jpeg", b"x", U1, context or ctx(U1),
        source_type="PM_WORK_ORDER", source_id=job)


async def store_request(repo, job, source=RequisitionSourceType.PM):
    asset = (await repo.get_pm_work_order(job)).work_order.asset_id if source == RequisitionSourceType.PM else "VEH-1046"
    return await MaterialRequestService(repo).create(
        source_type=source, source_work_order_id=job, asset_type=AssetType.VEHICLE, asset_id=asset,
        lines=[RequisitionLineInput(part_description="อะไหล่ทดสอบ (synthetic)", quantity=1, unit="ชิ้น",
                                    line_source="PM_STANDARD")], created_by="dev-user")


async def job_in(repo, wanted: S) -> str:
    """A V2 PM work order driven to `wanted` through the real E01 service."""
    svc = pm_service(repo)
    job = await v2_job(repo)
    if wanted == S.CANCELLED:
        await svc.cancel_work_order(job, manager(), request_id=rid(), reason="ยกเลิก (synthetic)")
        return job
    if wanted == S.OPEN:
        return job
    await start(svc, job)
    if wanted == S.IN_PROGRESS:
        return job
    for task in await scope_of(repo, job):
        await save(svc, job, task)
    await submit(svc, repo, job)
    if wanted == S.CLOSED:
        await svc.close_after_review(job, manager(), request_id=rid())
    return job


def evidence_rows(repo, job):
    return [a for a in repo._attachments.values() if a.source_type == "PM_WORK_ORDER" and a.source_id == job]


def store_rows(repo, job):
    requests = [r for r in repo._material_requests.values() if r.source_work_order_id == job]
    ids = {r.material_request_id for r in requests}
    return requests, [line for rid_, lines in repo._requisition_lines.items() if rid_ in ids for line in lines]


def cancelled_with_linked_records(repo, job) -> bool:
    return repo._pm_work_orders[job].status == S.CANCELLED and bool(evidence_rows(repo, job) or store_rows(repo, job)[0])


def lock_idle(repo, job) -> bool:
    locks = repo.__dict__.get("_pm_work_order_locks")
    return locks is None or job not in locks._locks


async def test_rr1_trace_the_cancel_blockers_are_exactly_the_cross_service_records() -> None:
    """Evidence and Store records ARE cancellation blockers (read under L1);
    every accepted write is visible to the next CANCEL eligibility check."""
    repo = repo_with()
    svc = pm_service(repo)
    job = await job_in(repo, S.IN_PROGRESS)
    await upload_evidence(repo, job)
    with pytest.raises(ApiError) as caught:
        await svc.cancel_work_order(job, manager(), request_id=rid(), reason="x")
    assert caught.value.code == "PM_CANCEL_NOT_ELIGIBLE" and caught.value.details["blockers"] == ["PM_EVIDENCE"]
    other = await v2_job(repo)
    await store_request(repo, other)
    with pytest.raises(ApiError) as caught:
        await svc.cancel_work_order(other, manager(), request_id=rid(), reason="x")
    assert set(caught.value.details["blockers"]) >= {"STORE_REQUEST", "STORE_REQUISITION_LINE"}


@pytest.mark.parametrize("status", [S.OPEN, S.IN_PROGRESS, S.PENDING_REVIEW, S.CLOSED, S.CANCELLED])
async def test_rr1_a_pm_evidence_is_accepted_only_while_in_progress(status) -> None:
    repo = repo_with()
    job = await job_in(repo, status)
    storage = _Storage()
    before = len(evidence_rows(repo, job))
    if status == S.IN_PROGRESS:
        attachment = await upload_evidence(repo, job, storage=storage)
        assert [a.attachment_id for a in evidence_rows(repo, job)][-1] == attachment.attachment_id
        return
    with pytest.raises(ApiError) as caught:
        await upload_evidence(repo, job, manager(), storage=storage)
    assert (caught.value.status_code, caught.value.code) == (409, "PM_EVIDENCE_NOT_ALLOWED")
    assert caught.value.details["status"] == status.value
    assert len(evidence_rows(repo, job)) == before and storage.saved == 0  # no row, no stored file
    assert lock_idle(repo, job)


@pytest.mark.parametrize("status", [S.OPEN, S.IN_PROGRESS, S.PENDING_REVIEW, S.CLOSED, S.CANCELLED])
async def test_rr1_b_pm_store_requests_are_accepted_only_while_open_or_in_progress(status) -> None:
    repo = repo_with()
    job = await job_in(repo, status)
    if status in (S.OPEN, S.IN_PROGRESS):
        detail = await store_request(repo, job)
        assert [r.material_request_id for r in store_rows(repo, job)[0]] == [detail.request.material_request_id]
        return
    with pytest.raises(ApiError) as caught:
        await store_request(repo, job)
    assert (caught.value.status_code, caught.value.code) == (409, "PM_STORE_REQUEST_NOT_ALLOWED")
    assert store_rows(repo, job) == ([], []) and lock_idle(repo, job)


async def test_rr1_b_a_store_request_for_a_missing_pm_work_order_is_refused_without_writes() -> None:
    repo = repo_with()
    before = dict(repo._material_requests)
    with pytest.raises(ApiError) as caught:
        await MaterialRequestService(repo).create(
            source_type=RequisitionSourceType.PM, source_work_order_id="PMWO-9999", asset_type=AssetType.VEHICLE,
            asset_id="VEH-1046", lines=[], created_by="dev-user")
    assert (caught.value.status_code, caught.value.code) == (404, "PM_WORK_ORDER_NOT_FOUND")
    assert repo._material_requests == before


async def test_rr1_legacy_pm_and_repair_sources_keep_their_behaviour() -> None:
    from tests.test_technician_assignment_batch_r2f_h1 import new_pm, new_repair
    repo = repo_with()
    legacy = await new_pm(repo, legacy=True)
    await upload_evidence(repo, legacy, manager())  # legacy PM evidence: unchanged (no V2 gate)
    await store_request(repo, legacy)  # legacy PM Store request: unchanged
    assert evidence_rows(repo, legacy) and store_rows(repo, legacy)[0]
    repair = await new_repair(repo)
    await store_request(repo, repair, RequisitionSourceType.REPAIR)  # Repair Store request: unchanged
    assert store_rows(repo, repair)[0]
    assert not repo.__dict__.get("_pm_work_order_locks") or not repo._pm_work_order_locks._locks


async def window(repo, write, method: str, job: str):
    """Run `write` (as its own task) inside the window right after `method`
    returns in the OTHER operation, giving it many loop turns but never
    awaiting it there (a correctly-locked writer would otherwise deadlock the
    test rather than show the window is closed)."""
    original = getattr(repo, method)
    tasks: list[asyncio.Task] = []

    async def hooked(*args, **kwargs):
        result = await original(*args, **kwargs)
        if not tasks:
            tasks.append(asyncio.create_task(write()))
            for _ in range(200):
                await asyncio.sleep(0)
        return result

    setattr(repo, method, hooked)
    return tasks


@pytest.mark.parametrize("writer", ["evidence", "store"])
async def test_rr1_c_a_write_inside_cancels_eligibility_window_waits_and_is_then_refused(writer) -> None:
    repo = yielding(repo_with())
    job = await job_in(repo, S.IN_PROGRESS)
    write = (lambda: upload_evidence(repo, job)) if writer == "evidence" else (lambda: store_request(repo, job))
    tasks = await window(repo, write, "list_requisition_lines_for_work_order", job)
    cancelled = await settle(pm_service(repo).cancel_work_order(job, manager(), request_id=rid(),
                                                                reason="ยกเลิก (synthetic)"))
    (outcome,) = await settle(*tasks)
    assert not isinstance(cancelled[0], BaseException)  # CANCEL saw no blocker and completed
    assert isinstance(outcome, ApiError) and outcome.status_code == 409  # the writer ran AFTER, and was refused
    assert outcome.code == ("PM_EVIDENCE_NOT_ALLOWED" if writer == "evidence" else "PM_STORE_REQUEST_NOT_ALLOWED")
    assert not cancelled_with_linked_records(repo, job) and lock_idle(repo, job)


@pytest.mark.parametrize("writer", ["evidence", "store"])
async def test_rr1_c_a_cancel_inside_a_writers_window_waits_and_then_sees_the_record(writer) -> None:
    repo = yielding(repo_with())
    svc = pm_service(repo)
    job = await job_in(repo, S.IN_PROGRESS)
    method = "create_attachment" if writer == "evidence" else "create_material_request"
    tasks = await window(repo, lambda: svc.cancel_work_order(job, manager(), request_id=rid(), reason="x"),
                         method, job)
    written = await settle(upload_evidence(repo, job) if writer == "evidence" else store_request(repo, job))
    (outcome,) = await settle(*tasks)
    assert not isinstance(written[0], BaseException)
    assert isinstance(outcome, ApiError) and outcome.code == "PM_CANCEL_NOT_ELIGIBLE"  # the write is visible
    assert repo._pm_work_orders[job].status == S.IN_PROGRESS and lock_idle(repo, job)


@pytest.mark.parametrize("writer", ["evidence", "store"])
async def test_rr1_a_lagging_cancel_projection_is_never_trusted(writer) -> None:
    """Journal says CANCELLED, the projected status still says IN_PROGRESS
    (interrupted status write): the writer reconciles under L1 and refuses."""
    repo = repo_with()
    job = await job_in(repo, S.IN_PROGRESS)
    repo.fail = {"set_pm_work_order_status": RuntimeError("synthetic lost status write")}
    with pytest.raises(RuntimeError):
        await pm_service(repo).cancel_work_order(job, manager(), request_id=rid(), reason="x")
    repo.fail = {}
    assert repo._pm_work_orders[job].status == S.IN_PROGRESS  # stale projection
    with pytest.raises(ApiError) as caught:
        await (upload_evidence(repo, job) if writer == "evidence" else store_request(repo, job))
    assert caught.value.details["status"] == "CANCELLED"
    assert repo._pm_work_orders[job].status == S.CANCELLED  # reconciled by the authorized path
    assert not evidence_rows(repo, job) and store_rows(repo, job) == ([], [])


async def test_rr1_scope_approval_never_trusts_a_lagging_cancel_projection() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job = await v2_job(repo)
    repo.fail = {"set_pm_work_order_status": RuntimeError("synthetic lost status write")}
    with pytest.raises(RuntimeError):
        await svc.cancel_work_order(job, manager(), request_id=rid(), reason="x")
    repo.fail = {}
    with pytest.raises(ApiError) as caught:
        await svc.approve_scope(job, manager())
    assert caught.value.code == "PM_SCOPE_LOCKED" and store_rows(repo, job) == ([], [])


async def test_rr1_scope_approval_store_writes_are_serialized_with_cancel() -> None:
    """approve_scope (allowlisted) is under L1, so it never interleaves with CANCEL."""
    repo = yielding(repo_with())
    svc = pm_service(repo)
    job = await v2_job(repo)
    outcomes = await settle(svc.cancel_work_order(job, manager(), request_id=rid(), reason="ยกเลิก (synthetic)"),
                            svc.approve_scope(job, manager()))
    assert not cancelled_with_linked_records(repo, job), outcomes


@pytest.mark.parametrize("step", ["create_attachment", "create_material_request", "create_requisition_line"])
async def test_rr1_a_failed_linked_write_releases_the_lock_and_a_retry_or_cancel_proceeds(step) -> None:
    repo = repo_with()
    job = await job_in(repo, S.IN_PROGRESS)
    repo.fail = {step: RuntimeError("synthetic write failure")}
    with pytest.raises(RuntimeError):
        await (upload_evidence(repo, job) if step == "create_attachment" else store_request(repo, job))
    repo.fail = {}
    assert lock_idle(repo, job)  # released on failure: no later operation can hang
    if step == "create_attachment":
        await upload_evidence(repo, job)  # retry succeeds, exactly one row
        assert len(evidence_rows(repo, job)) == 1
    elif step == "create_requisition_line":
        # A partially written Store request is RETAINED (never deleted) and is a
        # CANCEL blocker, so the failure can only make CANCEL more conservative.
        assert store_rows(repo, job)[0]
    cancel = pm_service(repo).cancel_work_order(job, manager(), request_id=rid(), reason="x")
    if step == "create_material_request":  # nothing was written: nothing blocks CANCEL
        assert (await cancel).work_order.status == S.CANCELLED
    else:  # every record that WAS written is visible to CANCEL eligibility
        with pytest.raises(ApiError) as caught:
            await cancel
        assert caught.value.code == "PM_CANCEL_NOT_ELIGIBLE"
    assert lock_idle(repo, job)


async def test_rr1_writers_reenter_l1_held_by_their_own_task_and_many_writers_never_deadlock() -> None:
    repo = yielding(repo_with())
    job = await job_in(repo, S.IN_PROGRESS)
    async with repo.pm_work_order_lock(job):  # nested in the same task: re-entry, no self-deadlock
        await upload_evidence(repo, job)
        await store_request(repo, job)
    svc = pm_service(repo)
    outcomes = await settle(*(upload_evidence(repo, job) for _ in range(4)), *(store_request(repo, job) for _ in range(4)),
                            svc.cancel_work_order(job, manager(), request_id=rid(), reason="x"))
    assert len(outcomes) == 9 and isinstance(outcomes[-1], ApiError)  # CANCEL sees the writes
    assert len(evidence_rows(repo, job)) == 5 and len(store_rows(repo, job)[0]) == 5  # no duplicates, none lost
    assert lock_idle(repo, job)


# ---------------------------------------------------------------- the real HTTP routes (no bypass)


async def _http(repo, method, path, **kwargs):
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app
    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.request(method, path, headers={"X-Request-Id": rid()}, **kwargs)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


@pytest.mark.parametrize("status", [S.CANCELLED, S.CLOSED])
async def test_rr1_http_routes_refuse_evidence_and_store_requests_for_a_finished_v2_work_order(status) -> None:
    repo = repo_with()
    job = await job_in(repo, status)
    upload = await _http(repo, "POST", "/api/v1/attachments",
                         data={"purpose": "PM_EVIDENCE", "source_type": "PM_WORK_ORDER", "source_id": job},
                         files={"file": ("e.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert upload.status_code == 409 and upload.json()["error"]["code"] == "PM_EVIDENCE_NOT_ALLOWED"
    request = await _http(repo, "POST", "/api/v1/material-requests",
                          json={"source_type": "PM", "source_work_order_id": job, "asset_type": "VEHICLE",
                                "asset_id": "VEH-1046", "lines": [{"part_description": "x", "quantity": 1}]})
    assert request.status_code == 409 and request.json()["error"]["code"] == "PM_STORE_REQUEST_NOT_ALLOWED"
    assert not evidence_rows(repo, job) and store_rows(repo, job) == ([], [])


async def test_rr1_http_routes_accept_valid_writes() -> None:
    repo = repo_with()
    job = await job_in(repo, S.IN_PROGRESS)
    upload = await _http(repo, "POST", "/api/v1/attachments",
                         data={"purpose": "PM_EVIDENCE", "source_type": "PM_WORK_ORDER", "source_id": job},
                         files={"file": ("e.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert upload.status_code == 200, upload.text
    request = await _http(repo, "POST", "/api/v1/material-requests",
                          json={"source_type": "PM", "source_work_order_id": job, "asset_type": "VEHICLE",
                                "asset_id": "VEH-1046", "lines": [{"part_description": "x", "quantity": 1}]})
    assert request.status_code == 200, request.text
    assert len(evidence_rows(repo, job)) == 1 and len(store_rows(repo, job)[0]) == 1


# ---------------------------------------------------------------- the (fake) Google Sheets adapter


async def _sheets_cancelled_then_written(writer: str):
    from app.repositories.google_sheets import schemas
    from tests.test_r4_pm_wf_sheets_parity import service as sheets_service
    backend = build()
    header = list(schemas.VEHICLE_SHEET.required_headers)
    backend.tabs["vehicle_master"] = [header, [{"vehicle_id": "VEH-SYN-1", "machine_no": "M-SYN-1",
                                                "model_id": "MDL-SYN", "operational_status": "READY",
                                                "created_at": "2026-01-01T00:00:00+00:00"}.get(h, "")
                                               for h in header]]
    repo = sheets_repo(backend)
    job = await new_job(repo)
    await sheets_service(repo).cancel_work_order(job, manager(), request_id=rid(), reason="ยกเลิก (synthetic)")
    before = backend.write_count()
    with pytest.raises(ApiError) as caught:
        if writer == "evidence":
            await upload_evidence(repo, job, manager())
        else:
            await store_request(repo, job)
    linked = [r for r in backend.rows("attachment") if r["source_id"] == job] + [
        r for r in backend.rows("material_request") if r["source_work_order_id"] == job]
    return backend.rows("pm_work_order")[0]["status"], linked, caught.value, backend.write_count() - before


@pytest.mark.parametrize("writer", ["evidence", "store"])
async def test_rr1_on_sheets_a_cancelled_work_order_refuses_cross_service_records_with_zero_writes(writer) -> None:
    status, linked, error, writes = await _sheets_cancelled_then_written(writer)
    assert status == "CANCELLED" and linked == [] and writes == 0
    assert (error.status_code, error.code) == (409, "PM_EVIDENCE_NOT_ALLOWED" if writer == "evidence"
                                               else "PM_STORE_REQUEST_NOT_ALLOWED")


async def test_l2_is_task_reentrant_and_excludes_other_tasks() -> None:
    """L2 stays task-reentrant (EV-047 deviation, kept with proof): nested
    holds in one task never self-deadlock; another task is excluded until the
    outermost release."""
    repo = sheets_repo(build())
    order: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with repo._write_lock():
            async with repo._write_lock():  # nested
                order.append("held")
                entered.set()
                await release.wait()
            order.append("inner-released")
        order.append("released")

    async def other():
        await entered.wait()
        async with repo._write_lock():
            order.append("other")

    tasks = [asyncio.create_task(holder()), asyncio.create_task(other())]
    await entered.wait()
    for _ in range(50):
        await asyncio.sleep(0)
    assert order == ["held"]  # the other task is excluded
    release.set()
    await settle(*tasks)
    assert order == ["held", "inner-released", "released", "other"]  # excluded until the OUTERMOST release
