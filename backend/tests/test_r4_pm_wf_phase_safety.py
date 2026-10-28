"""R4 PM Workflow — idempotency, partial-write recovery, readback (G2),
isolation and unsupported adapters (PH-13, PH-14, PH-15, PH-19, PH-22).
Failures are injected through the Spy repository's `fail` map (synthetic)."""
from __future__ import annotations

import copy
import inspect

import pytest

from app.domain.asset import AssetType
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.pm_service import PmService
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryFeatureNotImplementedError
from tests.pm_e01_support import (
    MANAGER_ID,
    NOT_PERFORMED,
    U1,
    close,
    ctx,
    current_set_id,
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
from tests.test_r4_pm_wf_phase_lifecycle import refused
from tests.test_r4_pm_wf_phase_outstanding import later_pm, partial_closed

NEW_REPOSITORY_METHODS = ("append_pm_work_order_transition", "list_pm_work_order_transitions",
                          "set_pm_work_order_status", "create_pm_outstanding_resolution",
                          "get_pm_outstanding_resolution", "list_pm_outstanding_items_for_asset")
WRITE_PREFIXES = ("create_", "append_", "close_", "assign_", "update_", "add_", "approve_", "delete_",
                  "withdraw", "write_", "set_", "end_", "mark_")
FAILURE = RuntimeError("synthetic write failure")


def journal(repo, job_id):
    return list(repo._pm_transitions.get(job_id, []))


async def submitted(repo):
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    await start(svc, job_id)
    tasks = await scope_of(repo, job_id)
    await save(svc, job_id, tasks[0])
    for task in tasks[1:]:
        await save(svc, job_id, task, NOT_PERFORMED)
    await submit(svc, repo, job_id)
    return svc, job_id, tasks


# ---------------------------------------------------------------- PH-13 replay / conflict


async def test_ph13_every_transition_replays_by_request_id_and_refuses_a_conflicting_reuse() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    start_id = rid()
    await svc.start_work_order(job_id, ctx(U1), request_id=start_id)
    again = await svc.start_work_order(job_id, ctx(U1), request_id=start_id)  # identical re-send
    assert again.work_order.status == S.IN_PROGRESS and len(journal(repo, job_id)) == 1
    for task in await scope_of(repo, job_id):
        await save(svc, job_id, task)
    set_id = await current_set_id(repo, job_id)
    submit_id = rid()
    await svc.submit_for_review(job_id, ctx(U1), request_id=submit_id, expected_set_id=set_id)
    await svc.submit_for_review(job_id, ctx(U1), request_id=submit_id, expected_set_id=set_id)
    assert await refused(svc.return_for_rework(job_id, manager(), request_id=submit_id, reason="x")) == (
        409, "PM_E01_REQUEST_CONFLICT")  # same id, different change
    return_id = rid()
    await svc.return_for_rework(job_id, manager(), request_id=return_id, reason="แก้")
    assert await refused(svc.return_for_rework(job_id, manager(), request_id=return_id, reason="อื่น")) == (
        409, "PM_E01_REQUEST_CONFLICT")  # same id, different reason
    await svc.submit_for_review(job_id, ctx(U1), request_id=rid(), expected_set_id=set_id)
    close_id = rid()
    await svc.close_after_review(job_id, manager(), request_id=close_id)
    snapshots = dict(repo._meter_snapshots)
    replay = await svc.close_after_review(job_id, manager(), request_id=close_id)
    assert replay.work_order.status == S.CLOSED and repo._meter_snapshots == snapshots  # no second close effect
    assert [e.action.value for e in journal(repo, job_id)] == ["START", "SUBMIT", "RETURN", "SUBMIT", "CLOSE"]


async def test_ph13_cancel_replay_and_close_outstanding_replay_create_no_duplicates() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    cancel_id = rid()
    await svc.cancel_work_order(job_id, manager(), request_id=cancel_id, reason="ยกเลิก")
    await svc.cancel_work_order(job_id, manager(), request_id=cancel_id, reason="ยกเลิก")
    assert len(journal(repo, job_id)) == 1
    repo2 = repo_with()
    svc2, job2, _ = await submitted(repo2)
    close_id = rid()
    await svc2.close_after_review(job2, manager(), request_id=close_id)
    await svc2.close_after_review(job2, manager(), request_id=close_id)
    assert len([i for i in repo2._pm_outstanding.values() if i.pm_work_order_id == job2]) == 2


# ---------------------------------------------------------------- PH-14 partial writes


@pytest.mark.parametrize("step", ["create_pm_work_result", "create_pm_item_outcome"])
async def test_ph14_item_save_failure_reports_no_success_and_a_retry_completes_without_duplicates(step) -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    await start(svc, job_id)
    task = (await scope_of(repo, job_id))[0]
    repo.fail = {step: FAILURE}
    with pytest.raises(RuntimeError):
        await save(svc, job_id, task)
    repo.fail = {}
    if step == "create_pm_item_outcome":  # the factual result exists, the Outcome does not: incomplete item
        assert len(repo._pm_work_results[job_id]) == 1 and not repo._pm_item_outcomes
        set_id = await current_set_id(repo, job_id)
        assert (await refused(svc.submit_for_review(job_id, ctx(U1), request_id=rid(), expected_set_id=set_id)))[1] \
            == "PM_E01_ITEM_RECORD_INCOMPLETE"
    recovered = await save(svc, job_id, task)
    assert recovered.result_replayed is (step == "create_pm_item_outcome") and recovered.outcome_replayed is False
    assert len(repo._pm_work_results[job_id]) == 1 and len(repo._pm_item_outcomes) == 1


@pytest.mark.parametrize("step", ["create_pm_outstanding_item", "append_pm_work_order_transition",
                                  "set_pm_work_order_status"])
async def test_ph14_close_failure_reports_no_success_and_a_retry_completes_it(step) -> None:
    repo = repo_with()
    svc, job_id, tasks = await submitted(repo)
    close_id = rid()
    repo.fail = {step: FAILURE}
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job_id, manager(), request_id=close_id)
    repo.fail = {}
    assert await svc.list_outstanding_items(job_id, ctx(U1)) == [] or step == "set_pm_work_order_status"
    # The same request (or any later action) completes the close; nothing is duplicated.
    detail = await svc.close_after_review(job_id, manager(), request_id=close_id)
    assert detail.work_order.status == S.CLOSED
    assert [e.action.value for e in journal(repo, job_id)].count("CLOSE") == 1
    assert len([i for i in repo._pm_outstanding.values() if i.pm_work_order_id == job_id]) == len(tasks) - 1
    assert len(await svc.list_outstanding_items(job_id, ctx(U1))) == len(tasks) - 1


async def test_ph14_a_lagging_projection_is_completed_by_the_next_read() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    repo.fail = {"set_pm_work_order_status": FAILURE}
    with pytest.raises(RuntimeError):
        await start(svc, job_id)
    repo.fail = {}
    assert repo._pm_work_orders[job_id].status == S.OPEN and journal(repo, job_id)[-1].to_status == S.IN_PROGRESS
    await svc.list_work_order_history(job_id, ctx(U1))  # any authorized read reconciles the projection
    assert repo._pm_work_orders[job_id].status == S.IN_PROGRESS


async def test_ph14_resolution_write_failure_is_retried_without_duplicates() -> None:
    repo = repo_with()
    _, task, item = await partial_closed(repo)
    _, result_id, evidence = await later_pm(repo, task)
    svc = pm_service(repo)
    repo.fail = {"create_pm_outstanding_resolution": FAILURE}
    with pytest.raises(RuntimeError):
        await svc.resolve_outstanding(item.outstanding_id, manager(), later_pm_work_result_id=result_id,
                                      evidence_attachment_ids=evidence)
    repo.fail = {}
    assert repo._pm_outstanding_resolutions == {}
    resolution, replayed = await svc.resolve_outstanding(item.outstanding_id, manager(),
                                                         later_pm_work_result_id=result_id,
                                                         evidence_attachment_ids=evidence)
    assert replayed is False and len(repo._pm_outstanding_resolutions) == 1


# ---------------------------------------------------------------- PH-14 close machine-state snapshot
# Independent review: the CLOSE projection captures the machine-state snapshot before the status
# compare-and-set. An interrupted projection must never make retries accumulate close snapshots,
# and one logical CLOSE has exactly one effective (referenced) close snapshot.


def close_snapshots(repo, job_id):
    """Every PM close machine-state snapshot persisted on this job's asset."""
    asset = repo._pm_work_orders[job_id]
    return [s for s in repo._meter_snapshots.values()
            if s.source_note == "PM_WORK_ORDER_CLOSE" and (s.asset_type, s.asset_id) == (asset.asset_type, asset.asset_id)]


async def assert_single_effective_close_snapshot(repo, job_id, before):
    """Exactly one close snapshot was created for the job, it is the referenced one, linked to
    the CLOSE event (same actor, captured after the event) with its one GPS half."""
    created = [s for s in close_snapshots(repo, job_id) if s.meter_snapshot_id not in before]
    work_order = repo._pm_work_orders[job_id]
    event = journal(repo, job_id)[-1]
    assert event.action.value == "CLOSE" and work_order.status == S.CLOSED
    assert [s.meter_snapshot_id for s in created] == [work_order.closed_snapshot_id]
    snapshot = created[0]
    assert snapshot.is_automatic and snapshot.recorded_by == event.actor == work_order.closed_by
    assert snapshot.recorded_at >= event.occurred_at and work_order.closed_at == event.occurred_at
    assert len(await repo.list_location_snapshots_for_event(snapshot.meter_snapshot_id)) == 1
    return snapshot


@pytest.mark.parametrize("failures", [0, 1, 3])
@pytest.mark.parametrize("retry", ["same_close_request", "any_authorized_read"])
async def test_ph14_an_interrupted_close_never_accumulates_close_snapshots(failures, retry) -> None:
    repo = repo_with()
    svc, job_id, _ = await submitted(repo)
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_id)}
    close_id = rid()
    first_capture = None
    for _ in range(failures):  # the status projection fails after the snapshot was captured
        repo.fail = {"set_pm_work_order_status": FAILURE}
        with pytest.raises(RuntimeError):
            await svc.close_after_review(job_id, manager(), request_id=close_id)
        repo.fail = {}
        pending = [s.meter_snapshot_id for s in close_snapshots(repo, job_id) if s.meter_snapshot_id not in before]
        assert len(pending) == 1  # captured once, never again on a retry; nothing deleted
        first_capture = first_capture or pending[0]
        assert repo._pm_work_orders[job_id].status == S.PENDING_REVIEW
        assert repo._pm_work_orders[job_id].closed_snapshot_id is None  # not effective yet (a read would
        # reconcile the projection, so the header is checked directly while the failure is in place)
    if retry == "same_close_request" or failures == 0:
        await svc.close_after_review(job_id, manager(), request_id=close_id)
    else:
        await svc.list_work_order_history(job_id, ctx(U1))  # reconciles the lagging projection
    snapshot = await assert_single_effective_close_snapshot(repo, job_id, before)
    if first_capture is not None:
        assert snapshot.meter_snapshot_id == first_capture  # the interrupted capture became the effective one
    replay = await svc.close_after_review(job_id, manager(), request_id=close_id)
    assert replay.work_order.closed_snapshot_id == snapshot.meter_snapshot_id
    assert [e.action.value for e in journal(repo, job_id)].count("CLOSE") == 1
    assert len([s for s in close_snapshots(repo, job_id) if s.meter_snapshot_id not in before]) == 1


async def test_ph14_a_persistently_failing_close_keeps_one_capture_and_never_becomes_effective() -> None:
    repo = repo_with()
    svc, job_id, tasks = await submitted(repo)
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_id)}
    close_id = rid()
    repo.fail = {"set_pm_work_order_status": FAILURE}
    for _ in range(5):
        with pytest.raises(RuntimeError):
            await svc.close_after_review(job_id, manager(), request_id=close_id)
    repo.fail = {}
    created = [s for s in close_snapshots(repo, job_id) if s.meter_snapshot_id not in before]
    assert len(created) == 1  # five attempts, one capture, kept (never deleted or rewritten)
    work_order = repo._pm_work_orders[job_id]
    assert work_order.status == S.PENDING_REVIEW and work_order.closed_snapshot_id is None
    assert work_order.closed_at is None  # not CLOSED, so no Outstanding item is effective
    assert [e.action.value for e in journal(repo, job_id)].count("CLOSE") == 1
    await svc.close_after_review(job_id, manager(), request_id=close_id)  # the failure ends: completes
    assert (await assert_single_effective_close_snapshot(repo, job_id, before)) == created[0]
    assert len(await svc.list_outstanding_items(job_id, manager())) == len(tasks) - 1


async def test_ph14_an_incomplete_close_capture_is_never_reused() -> None:
    """The GPS half of the capture failed: that partial capture is kept, but a complete capture
    is taken on the retry and becomes the effective one."""
    repo = repo_with()
    svc, job_id, _ = await submitted(repo)
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_id)}
    close_id = rid()
    repo.fail = {"create_location_snapshot": FAILURE}
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job_id, manager(), request_id=close_id)
    repo.fail = {}
    partial = [s.meter_snapshot_id for s in close_snapshots(repo, job_id) if s.meter_snapshot_id not in before]
    assert len(partial) == 1 and await repo.list_location_snapshots_for_event(partial[0]) == []
    await svc.close_after_review(job_id, manager(), request_id=close_id)
    effective = repo._pm_work_orders[job_id].closed_snapshot_id
    assert effective != partial[0] and partial[0] in repo._meter_snapshots  # kept, not rewritten
    assert len(await repo.list_location_snapshots_for_event(effective)) == 1


async def test_ph14_an_interrupted_capture_is_never_attributed_to_another_work_order() -> None:
    """Two V2 PMs on the same asset are closed by the same reviewer and both projections fail:
    neither close may adopt the other's capture; each falls back to its own fresh capture."""
    repo = repo_with()
    svc = pm_service(repo)
    jobs = []
    for _ in range(2):
        job_id = await v2_job(repo)
        await start(svc, job_id)
        for task in await scope_of(repo, job_id):
            await save(svc, job_id, task)
        await submit(svc, repo, job_id)
        jobs.append(job_id)
    before = {s.meter_snapshot_id for s in close_snapshots(repo, jobs[0])}
    requests = {job_id: rid() for job_id in jobs}
    orphans = {}
    for job_id in jobs:
        repo.fail = {"set_pm_work_order_status": FAILURE}
        with pytest.raises(RuntimeError):
            await svc.close_after_review(job_id, manager(), request_id=requests[job_id])
        repo.fail = {}
        orphans[job_id] = next(s.meter_snapshot_id for s in close_snapshots(repo, job_id)
                               if s.meter_snapshot_id not in before and s.meter_snapshot_id not in orphans.values())
    for job_id in jobs:
        await svc.close_after_review(job_id, manager(), request_id=requests[job_id])
    effective = {job_id: repo._pm_work_orders[job_id].closed_snapshot_id for job_id in jobs}
    assert effective[jobs[0]] != effective[jobs[1]]
    assert not set(effective.values()) & set(orphans.values())  # never a capture that is not provably its own
    assert set(orphans.values()) <= set(repo._meter_snapshots)  # unprovable captures are kept, not deleted
    for job_id in jobs:
        snapshot = repo._meter_snapshots[effective[job_id]]
        assert snapshot.recorded_at >= journal(repo, job_id)[-1].occurred_at


async def test_ph14_another_jobs_interrupted_capture_is_never_adopted() -> None:
    """Job A's close fails before any capture; job B (same asset, same reviewer, later) captures
    and is interrupted. A's retry sees exactly one unreferenced capture since its event — B's —
    and must not adopt it, because B's unfinished close could have produced it."""
    repo = repo_with()
    svc = pm_service(repo)
    jobs = []
    for _ in range(2):
        job_id = await v2_job(repo)
        await start(svc, job_id)
        for task in await scope_of(repo, job_id):
            await save(svc, job_id, task)
        await submit(svc, repo, job_id)
        jobs.append(job_id)
    job_a, job_b = jobs
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_a)}
    request_a, request_b = rid(), rid()
    repo.fail = {"create_meter_snapshot": FAILURE}  # A: journaled CLOSE, nothing captured
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job_a, manager(), request_id=request_a)
    assert [s for s in close_snapshots(repo, job_a) if s.meter_snapshot_id not in before] == []
    repo.fail = {"set_pm_work_order_status": FAILURE}  # B: captured, projection interrupted
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job_b, manager(), request_id=request_b)
    repo.fail = {}
    capture_b = next(s.meter_snapshot_id for s in close_snapshots(repo, job_b) if s.meter_snapshot_id not in before)
    await svc.close_after_review(job_a, manager(), request_id=request_a)
    assert repo._pm_work_orders[job_a].closed_snapshot_id not in (None, capture_b)
    await svc.close_after_review(job_b, manager(), request_id=request_b)
    assert repo._pm_work_orders[job_b].status == S.CLOSED
    assert repo._pm_work_orders[job_b].closed_snapshot_id != repo._pm_work_orders[job_a].closed_snapshot_id


async def unexplained_capture(repo, job_id, recorded_by):
    """A synthetic PM close capture on the job's asset that no work order explains."""
    from app.domain.meter_service import MeterService
    asset = repo._pm_work_orders[job_id]
    return (await MeterService(repo).capture_current_state(asset_type=asset.asset_type, asset_id=asset.asset_id,
                                                           recorded_by=recorded_by,
                                                           source_note="PM_WORK_ORDER_CLOSE")).meter_snapshot_id


async def interrupted_close(repo, svc, job_id, request_id, before):
    repo.fail = {"set_pm_work_order_status": FAILURE}
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job_id, manager(), request_id=request_id)
    repo.fail = {}
    return next(s.meter_snapshot_id for s in close_snapshots(repo, job_id) if s.meter_snapshot_id not in before)


@pytest.mark.parametrize("unrelated", ["same_actor_before_the_event", "other_actor_after_the_event"])
async def test_ph14_an_unrelated_capture_does_not_prevent_reuse(unrelated) -> None:
    """Only captures by the CLOSE event's actor since the event are candidates."""
    repo = repo_with()
    svc, job_id, _ = await submitted(repo)
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_id)}
    request_id = rid()
    if unrelated == "same_actor_before_the_event":
        before.add(await unexplained_capture(repo, job_id, MANAGER_ID))
    orphan = await interrupted_close(repo, svc, job_id, request_id, before)
    if unrelated == "other_actor_after_the_event":
        before.add(await unexplained_capture(repo, job_id, "USR-SYN-OTHER"))
    await svc.close_after_review(job_id, manager(), request_id=request_id)
    assert repo._pm_work_orders[job_id].closed_snapshot_id == orphan  # its own capture, reused


async def test_ph14_two_candidate_captures_are_unprovable_so_a_fresh_capture_is_taken() -> None:
    repo = repo_with()
    svc, job_id, _ = await submitted(repo)
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_id)}
    request_id = rid()
    orphan = await interrupted_close(repo, svc, job_id, request_id, before)
    unexplained = await unexplained_capture(repo, job_id, MANAGER_ID)  # same actor, after the event
    await svc.close_after_review(job_id, manager(), request_id=request_id)
    effective = repo._pm_work_orders[job_id].closed_snapshot_id
    assert effective not in (None, orphan, unexplained)  # never a guess between two candidates
    assert {orphan, unexplained} <= set(repo._meter_snapshots)  # both kept


async def test_ph15_a_close_snapshot_reference_readback_mismatch_fails_closed() -> None:
    repo = repo_with()
    repo.__class__ = _ReadbackOnce
    svc, job_id, _ = await submitted(repo)
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_id)}
    request_id = rid()
    repo.tamper, repo.remaining = "close_ref", 1
    with pytest.raises(ApiError) as mismatch:
        await svc.close_after_review(job_id, manager(), request_id=request_id)
    assert mismatch.value.code == "PM_E01_READBACK_MISMATCH"  # never reported as done
    replay = await svc.close_after_review(job_id, manager(), request_id=request_id)
    snapshot = await assert_single_effective_close_snapshot(repo, job_id, before)
    assert replay.work_order.closed_snapshot_id == snapshot.meter_snapshot_id


async def test_ph14_a_capture_older_than_another_closed_jobs_own_capture_is_unprovable() -> None:
    """A historical LEGACY job's failed close attempt by the same reviewer leaves a capture, and
    a different user then closes that job. The V2 retry sees exactly one candidate since its
    event, but the legacy job (closed with a later capture of its own) may have produced it."""
    from tests.test_technician_assignment_batch_r2f_h1 import new_pm
    repo = repo_with()
    svc, job_id, _ = await submitted(repo)
    legacy_id = await new_pm(repo, legacy=True)
    task = (await scope_of(repo, job_id))[0]
    repo._pm_work_orders[legacy_id] = repo._pm_work_orders[legacy_id].model_copy(update={"scope_task_ids": [task]})
    await svc.submit_task_result(legacy_id, task, True, None, None, [], [], U1)
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_id)}
    request_id = rid()
    repo.fail = {"create_meter_snapshot": FAILURE}  # V2: journaled CLOSE, nothing captured
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job_id, manager(), request_id=request_id)
    repo.fail = {"close_pm_work_order": FAILURE}  # legacy: captured by the same reviewer, not closed
    with pytest.raises(RuntimeError):
        await svc.close_work_order(legacy_id, MANAGER_ID, None)
    repo.fail = {}
    legacy_attempt = next(s.meter_snapshot_id for s in close_snapshots(repo, job_id) if s.meter_snapshot_id not in before)
    await svc.close_work_order(legacy_id, "USR-SYN-OTHER-REVIEWER", None)  # closed with its own later capture
    await svc.close_after_review(job_id, manager(), request_id=request_id)
    assert repo._pm_work_orders[job_id].closed_snapshot_id not in (None, legacy_attempt)
    assert legacy_attempt in repo._meter_snapshots


async def test_ph14_an_open_legacy_job_on_the_asset_makes_a_capture_unprovable() -> None:
    """A historical LEGACY job on the same asset may also have attempted a close (its capture is
    untraceable), so a V2 retry never adopts a capture it cannot prove is its own."""
    from tests.test_technician_assignment_batch_r2f_h1 import new_pm
    repo = repo_with()
    svc, job_id, _ = await submitted(repo)
    await new_pm(repo, legacy=True)  # OPEN legacy job on the same asset
    before = {s.meter_snapshot_id for s in close_snapshots(repo, job_id)}
    close_id = rid()
    repo.fail = {"set_pm_work_order_status": FAILURE}
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job_id, manager(), request_id=close_id)
    repo.fail = {}
    orphan = next(s.meter_snapshot_id for s in close_snapshots(repo, job_id) if s.meter_snapshot_id not in before)
    await svc.close_after_review(job_id, manager(), request_id=close_id)
    work_order = repo._pm_work_orders[job_id]
    assert work_order.status == S.CLOSED and work_order.closed_snapshot_id not in (None, orphan)
    assert orphan in repo._meter_snapshots


# ---------------------------------------------------------------- PH-15 G2 readback


class _ReadbackOnce(type(repo_with())):
    """Returns one mismatching readback of the named record kind, then the truth."""
    tamper: str = ""
    remaining: int = 0
    skip: int = 0  # untampered reads to let through first (e.g. the pre-write reconcile read)

    async def get_pm_item_outcome(self, outcome_id):
        found = await super().get_pm_item_outcome(outcome_id)
        if self.tamper == "outcome" and found is not None and self.remaining:
            self.remaining -= 1
            return found.model_copy(update={"recorded_by": "USR-FORGED"})
        return found

    async def get_pm_work_order(self, pm_work_order_id):
        found = await super().get_pm_work_order(pm_work_order_id)
        if (self.tamper == "close_ref" and found is not None and self.remaining
                and found.work_order.status == S.CLOSED):
            self.remaining -= 1
            return found.model_copy(update={"work_order": found.work_order.model_copy(
                update={"closed_snapshot_id": "MSNAP-FORGED"})})
        return found

    async def list_pm_work_order_transitions(self, pm_work_order_id):
        journal_ = await super().list_pm_work_order_transitions(pm_work_order_id)
        if self.tamper == "journal" and journal_ and self.remaining:
            if self.skip:
                self.skip -= 1
                return journal_
            self.remaining -= 1
            return journal_[:-1] + [journal_[-1].model_copy(update={"actor": "USR-FORGED"})]
        return journal_


async def test_ph15_transient_readback_mismatch_fails_closed_then_a_retry_succeeds() -> None:
    repo = repo_with()
    repo.__class__ = _ReadbackOnce
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    await start(svc, job_id)
    task = (await scope_of(repo, job_id))[0]
    repo.tamper, repo.remaining = "outcome", 1
    assert await refused(save(svc, job_id, task)) == (500, "PM_OUTCOME_READBACK_MISMATCH")
    stored_before = dict(repo._pm_item_outcomes)
    recovered = await save(svc, job_id, task)  # the stored record was right; the retry verifies and reuses it
    assert recovered.outcome_replayed is True and dict(repo._pm_item_outcomes) == stored_before
    set_id = await current_set_id(repo, job_id)
    for t in (await scope_of(repo, job_id))[1:]:
        await save(svc, job_id, t)
    submit_id = rid()
    repo.tamper, repo.remaining, repo.skip = "journal", 1, 1  # only the readback after the append mismatches
    with pytest.raises(ApiError) as mismatch:
        await svc.submit_for_review(job_id, ctx(U1), request_id=submit_id, expected_set_id=set_id)
    assert mismatch.value.code == "PM_E01_READBACK_MISMATCH"
    assert repo._pm_work_orders[job_id].status == S.IN_PROGRESS  # not projected, not reported as done
    detail = await svc.submit_for_review(job_id, ctx(U1), request_id=submit_id, expected_set_id=set_id)
    assert detail.work_order.status == S.PENDING_REVIEW and len(journal(repo, job_id)) == 2


async def test_ph15_persistent_inconsistency_fails_closed_and_is_never_repaired_silently() -> None:
    repo = repo_with()
    svc, job_id, _ = await submitted(repo)
    # The header disagrees with the journal in a way no interrupted write can explain.
    repo._pm_work_orders[job_id] = repo._pm_work_orders[job_id].model_copy(update={"status": S.CANCELLED})
    before = (repo._pm_work_orders[job_id], journal(repo, job_id), dict(repo._pm_outstanding))
    for attempt in (close(svc, job_id), svc.list_work_order_history(job_id, ctx(U1)),
                    svc.list_outstanding_items(job_id, ctx(U1))):
        assert await refused(attempt) == (409, "PM_E01_STATE_INCONSISTENT")
    assert (repo._pm_work_orders[job_id], journal(repo, job_id), dict(repo._pm_outstanding)) == before


async def test_ph15_a_conflicting_stored_outcome_is_never_overwritten() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    await start(svc, job_id)
    task = (await scope_of(repo, job_id))[0]
    first = await save(svc, job_id, task)
    assert (await refused(save(svc, job_id, task, remark="ต่างจากเดิม")))[1] == "PM_OUTCOME_CONFLICT"
    assert list(repo._pm_item_outcomes.values()) == [first.outcome] and repo._pm_work_results[job_id] == [first.result]


# ---------------------------------------------------------------- PH-19 isolation


def protected(repo):
    return copy.deepcopy((repo._pm_assignment_history, repo._technician_assignment_rows, repo._material_requests,
                          repo._requisition_lines, repo._repairs, repo._repair_requests, repo._pm_task_revisions,
                          repo._pm_tasks))


async def test_ph19_workflow_touches_no_due_repair_store_assignment_or_master_record() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    due_before = [(s.due_status, s.due_status_note) for s in
                  await svc.list_applicable_plan_status(AssetType.VEHICLE, "VEH-1046")]
    job_id = await v2_job(repo)
    before = protected(repo)
    snapshots_before = set(repo._meter_snapshots)
    repo.calls.clear()
    await start(svc, job_id)
    tasks = await scope_of(repo, job_id)
    await save(svc, job_id, tasks[0])
    for task in tasks[1:]:
        await save(svc, job_id, task, NOT_PERFORMED)
    await submit(svc, repo, job_id)
    await svc.return_for_rework(job_id, manager(), request_id=rid(), reason="ตรวจซ้ำ")
    await submit(svc, repo, job_id)
    await close(svc, job_id)
    assert protected(repo) == before
    writes = {c for c in repo.calls if c.startswith(WRITE_PREFIXES)}
    assert writes <= {"create_pm_work_result", "create_pm_item_outcome", "create_pm_outstanding_item",
                      "append_pm_work_order_transition", "set_pm_work_order_status",
                      # the existing machine-state capture of PM results and closure (MeterService)
                      "create_meter_snapshot", "create_location_snapshot"}
    new_snapshots = [repo._meter_snapshots[k] for k in set(repo._meter_snapshots) - snapshots_before]
    assert {getattr(s, "source_note", None) for s in new_snapshots} <= {"PM_TASK_RESULT", "PM_WORK_ORDER_CLOSE"}
    due_after = [(s.due_status, s.due_status_note) for s in
                 await svc.list_applicable_plan_status(AssetType.VEHICLE, "VEH-1046")]
    assert due_after == due_before


# ---------------------------------------------------------------- PH-22 unsupported adapter


class _NoE01Repository(type(repo_with())):
    """A Mock whose new storage behaves like an adapter without it (the
    Repository base implementation, exactly what GoogleSheetsRepository inherits)."""


for _name in (*NEW_REPOSITORY_METHODS, "create_pm_item_outcome", "get_pm_item_outcome", "list_pm_item_outcomes",
              "create_pm_outstanding_item", "get_pm_outstanding_item", "list_pm_outstanding_items"):
    setattr(_NoE01Repository, _name, getattr(Repository, _name))


async def test_ph22_sheets_adapter_inherits_explicit_refusals_and_nothing_is_written() -> None:
    from app.repositories.google_sheets.repository import GoogleSheetsRepository
    assert not inspect.isabstract(GoogleSheetsRepository)
    for name in NEW_REPOSITORY_METHODS:
        assert name not in Repository.__abstractmethods__
        assert getattr(GoogleSheetsRepository, name) is getattr(Repository, name)
    repo = repo_with()
    job_id = await v2_job(repo)
    repo.__class__ = _NoE01Repository
    svc = pm_service(repo)
    before = (repo._pm_work_orders[job_id], dict(repo._pm_work_results), dict(repo._meter_snapshots))
    for attempt in (start(svc, job_id), svc.list_work_order_history(job_id, ctx(U1)),
                    svc.list_asset_outstanding(AssetType.VEHICLE, "VEH-1046", ctx(U1))):
        with pytest.raises(RepositoryFeatureNotImplementedError):
            await attempt
    assert (repo._pm_work_orders[job_id], dict(repo._pm_work_results), dict(repo._meter_snapshots)) == before


def test_ph22_service_constructor_and_vocabulary_binding_are_unchanged() -> None:
    assert list(inspect.signature(PmService.__init__).parameters) == [
        "self", "repository", "meter_service", "assignment_cutover"]
