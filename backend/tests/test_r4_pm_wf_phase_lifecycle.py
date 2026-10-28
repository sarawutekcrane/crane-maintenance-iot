"""R4 PM Workflow — E01 A3 lifecycle, actor rules, return, cancellation and
frozen history (PH-01..PH-06, PH-18). Mock, synthetic records only."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.domain import authz
from app.domain.attachment import AttachmentPurpose
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.requisition import RequisitionSourceType
from app.domain.technician_assignment import PM
from app.errors import ApiError
from tests.pm_e01_support import (
    NOT_PERFORMED,
    PERFORMED,
    U1,
    U2,
    close,
    ctx,
    current_set_id,
    drive_to_closed,
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
from tests.test_technician_assignment_batch_r2f_h1 import T3, U3, assign, body, new_pm, ta_service


async def refused(coro) -> tuple[int, str]:
    try:
        await coro
    except ApiError as exc:
        return exc.status_code, exc.code
    except HTTPException as exc:
        return exc.status_code, "FORBIDDEN"
    raise AssertionError("expected a refusal")


def journal(repo, job_id):
    return [(e.action.value, e.from_status.value, e.to_status.value) for e in repo._pm_transitions.get(job_id, [])]


# ---------------------------------------------------------------- PH-01


async def test_ph01_valid_path_and_every_other_edge_refused_without_write() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    svc = pm_service(repo)
    # From OPEN: SUBMIT / RETURN / CLOSE are not edges.
    for attempt in (submit(svc, repo, job_id),
                    svc.return_for_rework(job_id, manager(), request_id=rid(), reason="x"),
                    close(svc, job_id)):
        assert (await refused(attempt))[1] in {"PM_E01_INVALID_TRANSITION"}
    assert repo._pm_work_orders[job_id].status == S.OPEN and journal(repo, job_id) == []
    await start(svc, job_id)
    # IN_PROGRESS -> CLOSED directly is not an edge (no review bypass).
    assert (await refused(close(svc, job_id)))[1] == "PM_E01_INVALID_TRANSITION"
    assert (await refused(start(svc, job_id)))[1] == "PM_E01_INVALID_TRANSITION"
    for task in await scope_of(repo, job_id):
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)
    assert (await refused(start(svc, job_id)))[1] == "PM_E01_INVALID_TRANSITION"
    await close(svc, job_id)
    assert repo._pm_work_orders[job_id].status == S.CLOSED
    assert journal(repo, job_id) == [("START", "OPEN", "IN_PROGRESS"), ("SUBMIT", "IN_PROGRESS", "PENDING_REVIEW"),
                                     ("CLOSE", "PENDING_REVIEW", "CLOSED")]
    # CLOSED is terminal.
    for attempt in (start(svc, job_id), submit(svc, repo, job_id), close(svc, job_id),
                    svc.return_for_rework(job_id, manager(), request_id=rid(), reason="x"),
                    svc.cancel_work_order(job_id, manager(), request_id=rid(), reason="x")):
        assert (await refused(attempt))[1] in {"PM_E01_INVALID_TRANSITION", "PM_CANCEL_NOT_ELIGIBLE"}
    assert len(journal(repo, job_id)) == 3


async def test_ph01_closed_projection_records_closure_fields_and_snapshot() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    detail = await drive_to_closed(repo, job_id)
    wo = detail.work_order
    assert wo.status == S.CLOSED and wo.closed_by == "USR-SYN-MANAGER" and wo.closed_at is not None
    assert wo.closed_snapshot_id in repo._meter_snapshots


# ---------------------------------------------------------------- PH-02


@pytest.mark.parametrize("user", [U1, U2])
async def test_ph02_current_member_can_start(user) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    assert (await start(pm_service(repo), job_id, ctx(user))).work_order.status == S.IN_PROGRESS


async def test_ph02_manager_can_start_but_a_current_set_is_required() -> None:
    repo = repo_with()
    no_set = await v2_job(repo, primary=None)
    assert await refused(start(pm_service(repo), no_set, manager())) == (409, "PM_E01_ASSIGNMENT_REQUIRED")
    with_set = await v2_job(repo)
    assert (await start(pm_service(repo), with_set, manager())).work_order.status == S.IN_PROGRESS


async def test_ph02_unassigned_replaced_withdrawn_and_legacy_cannot_start() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    assert (await refused(start(svc, job_id, ctx(U3))))[0] == 403  # in scope, not in the set
    await assign(repo, job_id, body(T3, expected=("TEC-SYN-1", "TEC-SYN-2")), kind=PM)
    assert (await refused(start(svc, job_id, ctx(U1))))[0] == 403  # replaced set
    await ta_service(repo).withdraw(PM, job_id, {"expected_current": {"primary_technician_id": T3,
                                                                      "collaborator_technician_ids": []}},
                                    request_id=str(uuid.uuid4()), user_id="dev-user")
    assert (await refused(start(svc, job_id, ctx(U3))))[0] == 403  # withdrawn: no member any more
    assert await refused(start(svc, job_id, manager())) == (409, "PM_E01_ASSIGNMENT_REQUIRED")
    legacy_id = await new_pm(repo, legacy=True)
    assert await refused(start(svc, legacy_id, manager())) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert repo._pm_work_orders[job_id].status == S.OPEN and journal(repo, job_id) == []


async def test_ph02_test_real_scope_applies_to_capability_holders_too() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)  # a TEST-scope job of the mock batch
    real = pm_service(repo, context="REAL", batch="")
    for attempt in (start(real, job_id, manager()), real.list_item_outcomes(job_id, manager()),
                    real.cancel_work_order(job_id, manager(), request_id=rid(), reason="x")):
        assert await refused(attempt) == (409, "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH")
    other_batch = pm_service(repo, batch="OTHER-BATCH")
    assert await refused(start(other_batch, job_id, manager())) == (409, "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH")
    unconfigured = pm_service(repo, context=None)
    assert (await refused(start(unconfigured, job_id, manager())))[0] == 503
    assert repo._pm_work_orders[job_id].status == S.OPEN


# ---------------------------------------------------------------- PH-03


async def test_ph03_only_the_current_primary_submits_with_a_fresh_set() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    svc = pm_service(repo)
    await start(svc, job_id)
    for task in await scope_of(repo, job_id):
        await save(svc, job_id, task, context=ctx(U2))  # a collaborator may save items
    set_id = await current_set_id(repo, job_id)
    for denied in (ctx(U2), manager(), ctx("USR-SYN-MANAGER", authz.CAN_MANAGE_PM)):
        assert await refused(svc.submit_for_review(job_id, denied, request_id=rid(), expected_set_id=set_id)) == (
            403, "PM_SUBMIT_PRIMARY_ONLY")
    assert await refused(svc.submit_for_review(job_id, ctx(U1), request_id=rid(), expected_set_id="stale")) == (
        409, "PM_ASSIGNMENT_STALE")
    assert repo._pm_work_orders[job_id].status == S.IN_PROGRESS
    detail = await svc.submit_for_review(job_id, ctx(U1), request_id=rid(), expected_set_id=set_id)
    assert detail.work_order.status == S.PENDING_REVIEW


# ---------------------------------------------------------------- PH-04


async def test_ph04_return_and_close_need_can_manage_pm_and_return_needs_a_reason() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    svc = pm_service(repo)
    await start(svc, job_id)
    for task in await scope_of(repo, job_id):
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)
    for member in (ctx(U1), ctx(U2)):
        assert (await refused(svc.return_for_rework(job_id, member, request_id=rid(), reason="x")))[0] == 403
        assert (await refused(close(svc, job_id, member)))[0] == 403
    for blank in (None, "", "   "):
        assert await refused(svc.return_for_rework(job_id, manager(), request_id=rid(), reason=blank)) == (
            422, "PM_RETURN_REASON_REQUIRED")
    assert repo._pm_work_orders[job_id].status == S.PENDING_REVIEW


async def test_ph04_self_review_allowed_when_the_primary_also_holds_can_manage_pm() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    svc = pm_service(repo)
    both = ctx(U1, authz.CAN_MANAGE_PM)  # the V2 PRIMARY who is also an AM-authorized reviewer
    await start(svc, job_id, both)
    for task in await scope_of(repo, job_id):
        await save(svc, job_id, task, context=both)
    await svc.submit_for_review(job_id, both, request_id=rid(), expected_set_id=await current_set_id(repo, job_id))
    assert (await close(svc, job_id, both)).work_order.status == S.CLOSED


# ---------------------------------------------------------------- PH-05


async def test_ph05_return_resubmit_and_history_preserve_saved_items() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    svc = pm_service(repo)
    await start(svc, job_id)
    tasks = await scope_of(repo, job_id)
    for task in tasks:
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)
    saved_before = (list(repo._pm_item_outcomes.values()), [r.model_copy() for r in repo._pm_work_results[job_id]])
    await svc.return_for_rework(job_id, manager(), request_id=rid(), reason="แนบรูปเพิ่ม")
    assert repo._pm_work_orders[job_id].status == S.IN_PROGRESS
    # Saved items stay exactly as they were; a different save of the same item is refused.
    assert (await refused(save(svc, job_id, tasks[0], PERFORMED, performed_actions=("ทำความสะอาด",))))[1] == (
        "PM_OUTCOME_CONFLICT")
    await submit(svc, repo, job_id)
    await close(svc, job_id)
    assert (list(repo._pm_item_outcomes.values()), repo._pm_work_results[job_id]) == saved_before
    history = await svc.list_work_order_history(job_id, ctx(U1))
    assert [(e.action.value, e.to_status.value, e.reason, e.actor) for e in history] == [
        ("START", "IN_PROGRESS", None, U1), ("SUBMIT", "PENDING_REVIEW", None, U1),
        ("RETURN", "IN_PROGRESS", "แนบรูปเพิ่ม", "USR-SYN-MANAGER"), ("SUBMIT", "PENDING_REVIEW", None, U1),
        ("CLOSE", "CLOSED", None, "USR-SYN-MANAGER")]


# ---------------------------------------------------------------- PH-06


async def test_ph06_eligible_cancellation_from_open_and_in_progress() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    open_job, started_job = await v2_job(repo), await v2_job(repo)
    await start(svc, started_job)
    for job_id, from_status in ((open_job, "OPEN"), (started_job, "IN_PROGRESS")):
        assert (await refused(svc.cancel_work_order(job_id, manager(), request_id=rid(), reason="  "))) == (
            409, "PM_CANCEL_NOT_ELIGIBLE")  # a reason is required
        assert (await refused(svc.cancel_work_order(job_id, ctx(U1), request_id=rid(), reason="x")))[0] == 403
        detail = await svc.cancel_work_order(job_id, manager(), request_id=rid(), reason="ยกเลิกแผน")
        assert detail.work_order.status == S.CANCELLED and detail.work_order.closed_at is None
        assert journal(repo, job_id)[-1] == ("CANCEL", from_status, "CANCELLED")
        assert (await refused(start(svc, job_id, manager())))[1] == "PM_E01_INVALID_TRANSITION"  # terminal


@pytest.mark.parametrize("blocker", ["PM_ITEM_OUTCOME", "PM_EVIDENCE", "STORE_REQUEST", "STORE_REQUISITION_LINE"])
async def test_ph06_cancellation_refused_for_each_blocker_with_nothing_changed(blocker) -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    expected = {blocker}
    if blocker == "PM_ITEM_OUTCOME":
        await start(svc, job_id)
        await save(svc, job_id, (await scope_of(repo, job_id))[0])
        expected = {"PM_RESULT", "PM_ITEM_OUTCOME"}
    elif blocker == "PM_EVIDENCE":
        await repo.create_attachment(AttachmentPurpose.PM_EVIDENCE, "synthetic://ref", "e.jpg", "image/jpeg", 1, U1,
                                     source_type="PM_WORK_ORDER", source_id=job_id)
    else:  # a Store request already raised for this work order (synthetic Store record)
        request = await repo.create_material_request(RequisitionSourceType.PM, job_id, "VEH-1046", "dev-user")
        if blocker == "STORE_REQUISITION_LINE":
            await repo.create_requisition_line(request.material_request_id, None, None, None, "ไส้กรอง (synthetic)",
                                               1, "ชิ้น", None, "PM_STANDARD", "dev-user")
            expected = {"STORE_REQUEST", "STORE_REQUISITION_LINE"}
    before = (repo._pm_work_orders[job_id].status, journal(repo, job_id), dict(repo._material_requests),
              {k: list(v) for k, v in repo._requisition_lines.items()})
    try:
        await svc.cancel_work_order(job_id, manager(), request_id=rid(), reason="ยกเลิก")
    except ApiError as exc:
        assert exc.code == "PM_CANCEL_NOT_ELIGIBLE" and set(exc.details["blockers"]) == expected
    else:
        raise AssertionError("cancellation must be refused")
    assert (repo._pm_work_orders[job_id].status, journal(repo, job_id), dict(repo._material_requests),
            {k: list(v) for k, v in repo._requisition_lines.items()}) == before  # nothing linked changed


async def test_ph06_pending_review_and_closed_cannot_be_cancelled() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    await start(svc, job_id)
    for task in await scope_of(repo, job_id):
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)
    assert (await refused(svc.cancel_work_order(job_id, manager(), request_id=rid(), reason="x")))[1] == (
        "PM_CANCEL_NOT_ELIGIBLE")


# ---------------------------------------------------------------- PH-18


async def test_ph18_frozen_revision_and_scope_survive_every_transition() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    frozen = (repo._pm_work_orders[job_id].revision_id, list(repo._pm_work_orders[job_id].scope_task_ids))
    svc = pm_service(repo)
    await start(svc, job_id)
    tasks = await scope_of(repo, job_id)
    for task in tasks:
        await save(svc, job_id, task)
    await submit(svc, repo, job_id)
    # Scope cannot change once submitted.
    assert (await refused(svc.add_scope_task(job_id, tasks[0], "x", "dev-user")))[1] == "PM_SCOPE_LOCKED"
    assert (await refused(svc.approve_scope(job_id, "dev-user")))[1] == "PM_SCOPE_LOCKED"
    await svc.return_for_rework(job_id, manager(), request_id=rid(), reason="ตรวจซ้ำ")
    await submit(svc, repo, job_id)
    await close(svc, job_id)
    wo = repo._pm_work_orders[job_id]
    assert (wo.revision_id, list(wo.scope_task_ids)) == frozen
    assert all(r.revision_id == frozen[0] for r in repo._pm_work_results[job_id])
