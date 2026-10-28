"""R4 PM Workflow — truthful item save, zero-Performed rule, complete / partial
review and close (PH-07..PH-11). Mock, synthetic records only."""
from __future__ import annotations

import pytest

from app.domain import authz
from app.domain.pm import PmWorkOrderStatus as S
from tests.pm_e01_support import (
    CHECK,
    CLEAN,
    NOT_PERFORMED,
    OTHER,
    PERFORMED,
    REPLACE,
    U1,
    U2,
    WAIT_PARTS,
    close,
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
from tests.test_r4_pm_wf_phase_lifecycle import refused
from tests.test_technician_assignment_batch_r2f_h1 import U3


async def started(extra_tasks: int = 0):
    repo = repo_with()
    job_id = await v2_job(repo, extra_tasks=extra_tasks)
    svc = pm_service(repo)
    await start(svc, job_id)
    return repo, svc, job_id, await scope_of(repo, job_id)


def stored(repo, job_id):
    return ([o for o in repo._pm_item_outcomes.values() if o.pm_work_order_id == job_id],
            list(repo._pm_work_results.get(job_id, [])),
            [i for i in repo._pm_outstanding.values() if i.pm_work_order_id == job_id])


# ---------------------------------------------------------------- PH-07


async def test_ph07_item_save_only_while_in_progress_by_an_authorized_member() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    svc = pm_service(repo)
    task = (await scope_of(repo, job_id))[0]
    assert await refused(save(svc, job_id, task)) == (409, "PM_E01_ITEM_SAVE_NOT_ALLOWED")  # still OPEN
    await start(svc, job_id)
    assert (await refused(save(svc, job_id, task, context=ctx(U3))))[0] == 403
    saved = await save(svc, job_id, task, context=ctx(U2), performed_actions=(CHECK, CLEAN))
    assert (saved.outcome.recorded_by, saved.result.performed_by) == (U2, U2)
    assert saved.result.completed is True and saved.outcome.source_pm_work_result_id == saved.result.pm_work_result_id
    assert saved.outcome.recorded_at == saved.result.performed_at  # one stable provenance for both records


async def test_ph07_one_result_and_one_outcome_per_item_with_parts_meter_and_evidence() -> None:
    from app.domain.attachment import AttachmentPurpose
    from app.domain.pm_service import UsedPartInput
    repo, svc, job_id, tasks = await started()
    att = (await repo.create_attachment(AttachmentPurpose.PM_EVIDENCE, "synthetic://e", "e.jpg", "image/jpeg", 1, U1,
                                        source_type="PM_WORK_ORDER", source_id=job_id)).attachment_id
    part = UsedPartInput(part_description="น้ำมันเครื่อง (synthetic)", quantity=4, unit="ลิตร")
    first = await save(svc, job_id, tasks[0], performed_actions=(REPLACE,), evidence_attachment_ids=(att,),
                       remark="เปลี่ยนแล้ว", used_parts=(part,))
    again = await save(svc, job_id, tasks[0], performed_actions=(REPLACE,), evidence_attachment_ids=(att,),
                       remark="เปลี่ยนแล้ว", used_parts=(part,))
    assert (again.result_replayed, again.outcome_replayed) == (True, True)
    assert (again.result, again.outcome) == (first.result, first.outcome)
    outcomes, results, _ = stored(repo, job_id)
    assert len(outcomes) == 1 and len(results) == 1
    assert results[0].used_parts[0].part_description == "น้ำมันเครื่อง (synthetic)"
    assert results[0].meter_snapshot_id in repo._meter_snapshots and results[0].evidence_attachment_ids == [att]


@pytest.mark.parametrize("disposition,kw,code", [
    (PERFORMED, {"performed_actions": ()}, "PM_PERFORMED_ACTION_INVALID"),
    (PERFORMED, {"performed_actions": ("ล้างเครื่อง",)}, "PM_PERFORMED_ACTION_INVALID"),
    (PERFORMED, {"performed_actions": (CHECK, CLEAN, REPLACE)}, "PM_PERFORMED_ACTION_INVALID"),
    (PERFORMED, {"performed_actions": (CHECK,), "reason_code": WAIT_PARTS}, "PM_PERFORMED_REASON_CONFLICT"),
    (NOT_PERFORMED, {"reason_code": "รอช่าง"}, "PM_NOT_PERFORMED_REASON_REQUIRED"),
    (NOT_PERFORMED, {"reason_code": OTHER}, "PM_OTHER_REASON_TEXT_REQUIRED"),
    (NOT_PERFORMED, {"reason_code": OTHER, "other_text": "   "}, "PM_OTHER_REASON_TEXT_REQUIRED"),
])
async def test_ph07_fc1_vocabulary_and_other_text_are_enforced(disposition, kw, code) -> None:
    repo, svc, job_id, tasks = await started()
    await save(svc, job_id, tasks[0])  # a Performed item exists, so a Not Performed save is allowed in principle
    before = stored(repo, job_id)
    assert await refused(svc.record_item_outcome(job_id, tasks[1], disposition, ctx(U1), **kw)) == (422, code)
    assert stored(repo, job_id) == before


# ---------------------------------------------------------------- PH-08


async def test_ph08_not_performed_needs_a_saved_performed_item_first() -> None:
    repo, svc, job_id, tasks = await started()
    assert await refused(save(svc, job_id, tasks[0], NOT_PERFORMED)) == (
        422, "PM_NOT_PERFORMED_REQUIRES_PERFORMED_FIRST")
    assert stored(repo, job_id) == ([], [], [])  # nothing persisted: the choice stays an unsaved draft
    await save(svc, job_id, tasks[1])
    saved = await save(svc, job_id, tasks[0], NOT_PERFORMED)
    assert saved.outcome.disposition == NOT_PERFORMED and saved.result.completed is False


async def test_ph08_zero_performed_blocks_submit_and_close_and_keeps_the_job_cancellable() -> None:
    repo, svc, job_id, _ = await started()
    assert await refused(submit(svc, repo, job_id)) == (422, "PM_ITEM_SCOPE_ACCOUNTING_INVALID")
    assert repo._pm_work_orders[job_id].status == S.IN_PROGRESS
    snapshots = len(repo._meter_snapshots)
    detail = await svc.cancel_work_order(job_id, manager(), request_id=rid(), reason="ไม่สามารถทำงานได้")
    assert detail.work_order.status == S.CANCELLED and detail.work_order.closed_snapshot_id is None
    assert len(repo._meter_snapshots) == snapshots and stored(repo, job_id) == ([], [], [])


# ---------------------------------------------------------------- PH-09


async def test_ph09_full_completion_closes_with_no_outstanding() -> None:
    repo, svc, job_id, tasks = await started(extra_tasks=2)
    assert len(tasks) == 5
    for task in tasks:
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)
    detail = await close(svc, job_id)
    assert detail.work_order.status == S.CLOSED
    assert stored(repo, job_id)[2] == [] and await svc.list_outstanding_items(job_id, ctx(U1)) == []


# ---------------------------------------------------------------- PH-10


async def test_ph10_four_of_five_performed_closes_with_exactly_one_outstanding() -> None:
    repo, svc, job_id, tasks = await started(extra_tasks=2)
    for task in tasks[:4]:
        await save(svc, job_id, task)
    await save(svc, job_id, tasks[4], NOT_PERFORMED, reason_code=WAIT_PARTS)
    assert stored(repo, job_id)[2] == []  # a recorded Not Performed item is not yet an Outstanding obligation
    await submit(svc, repo, job_id)
    assert stored(repo, job_id)[2] == [] and await svc.list_outstanding_items(job_id, ctx(U1)) == []
    detail = await close(svc, job_id)
    assert detail.work_order.status == S.CLOSED
    states = await svc.list_outstanding_items(job_id, ctx(U1))
    assert len(states) == 1 and states[0].resolution is None
    item = states[0].item
    np = next(o for o in stored(repo, job_id)[0] if o.pm_task_id == tasks[4])
    assert (item.pm_task_id, item.origin_reason_code, item.origin_recorded_by, item.origin_recorded_at,
            item.origin_pm_work_result_id) == (tasks[4], WAIT_PARTS, U1, np.recorded_at, np.source_pm_work_result_id)
    assert not hasattr(item, "follow_up_date")  # no mandatory follow-up date


async def test_ph10_returned_or_cancelled_work_never_leaves_an_outstanding() -> None:
    repo, svc, job_id, tasks = await started()
    await save(svc, job_id, tasks[0])
    for task in tasks[1:]:
        await save(svc, job_id, task, NOT_PERFORMED)
    await submit(svc, repo, job_id)
    await svc.return_for_rework(job_id, manager(), request_id=rid(), reason="ตรวจสอบเพิ่ม")
    assert stored(repo, job_id)[2] == [] and await svc.list_outstanding_items(job_id, ctx(U1)) == []


# ---------------------------------------------------------------- PH-11


async def test_ph11_a_missing_scope_item_blocks_submit_and_close() -> None:
    repo, svc, job_id, tasks = await started()
    for task in tasks[:-1]:
        await save(svc, job_id, task)
    try:
        await submit(svc, repo, job_id)
    except Exception as exc:  # noqa: BLE001 - the coded refusal is asserted below
        assert getattr(exc, "code", None) == "PM_ITEM_SCOPE_ACCOUNTING_INVALID"
        assert exc.details["missing_pm_task_ids"] == [tasks[-1]]
    else:
        raise AssertionError("submit must be refused")
    assert repo._pm_work_orders[job_id].status == S.IN_PROGRESS


async def test_ph11_close_rechecks_accounting_even_when_reached_from_review() -> None:
    repo, svc, job_id, tasks = await started()
    for task in tasks:
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)
    # Corrupt the stored outcome set behind the service (an Outcome removed): close must refuse.
    victim = next(k for k, o in repo._pm_item_outcomes.items() if o.pm_task_id == tasks[0])
    repo._pm_item_outcomes.pop(victim)
    assert (await refused(close(svc, job_id)))[1] == "PM_E01_ITEM_RECORD_INCOMPLETE"
    assert repo._pm_work_orders[job_id].status == S.PENDING_REVIEW


async def test_ph11_reviewer_identity_is_recorded_and_capability_is_effective_not_by_title() -> None:
    repo, svc, job_id, tasks = await started()
    for task in tasks:
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)
    titled = ctx("USR-SYN-SUPERVISOR")  # a manager title without the capability
    assert (await refused(close(svc, job_id, titled)))[0] == 403
    detail = await close(svc, job_id, ctx("USR-SYN-REVIEWER", authz.CAN_MANAGE_PM))
    assert detail.work_order.closed_by == "USR-SYN-REVIEWER"
