"""R4 PM Workflow — Outstanding provenance (G1), resolution with verified
evidence and the Due / Outstanding separation (PH-10 visibility, PH-12, PH-16,
PH-17). Mock, synthetic records only (Repairs and Repair Requests used as
evidence are synthetic repository fixtures)."""
from __future__ import annotations

import pytest

from app.domain.asset import AssetType
from app.domain.attachment import AttachmentPurpose
from app.domain.pm import (
    PmItemContractDisposition as Disposition,
    PmItemOutcome,
    build_pm_outstanding_item,
    pm_item_outcome_id,
)
from app.domain.repair import RepairSourceType
from tests.pm_e01_support import (
    NOT_PERFORMED,
    U1,
    WAIT_PARTS,
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
from tests.test_r4_pm_wf_phase_lifecycle import refused

VEHICLE = "VEH-1046"


async def partial_closed(repo):
    """A CLOSED V2 PM with every item Performed except the last (Not Performed)."""
    job_id = await v2_job(repo)
    last = (await scope_of(repo, job_id))[-1]
    await drive_to_closed(repo, job_id, not_performed=(last,))
    item = next(i for i in repo._pm_outstanding.values() if i.pm_work_order_id == job_id)
    return job_id, last, item


async def pm_evidence(repo, job_id):
    return (await repo.create_attachment(AttachmentPurpose.PM_EVIDENCE, "synthetic://e", "e.jpg", "image/jpeg", 1, U1,
                                         source_type="PM_WORK_ORDER", source_id=job_id)).attachment_id


async def later_pm(repo, task, *, with_evidence=True, performed=True, close_it=True, asset=VEHICLE):
    """A later V2 PM on the asset where `task` is genuinely Performed (with its own evidence)."""
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    if asset != VEHICLE:
        repo._pm_work_orders[job_id] = repo._pm_work_orders[job_id].model_copy(update={"asset_id": asset})
    await start(svc, job_id)
    evidence = (await pm_evidence(repo, job_id),) if with_evidence else ()
    tasks = await scope_of(repo, job_id)
    for t in [t for t in tasks if t != task] + [task]:
        kwargs = {"evidence_attachment_ids": evidence} if t == task and performed else {}
        await save(svc, job_id, t, Disposition.PERFORMED if (t != task or performed) else NOT_PERFORMED, **kwargs)
    if close_it:
        await submit(svc, repo, job_id)
        await close(svc, job_id)
    result = next(r for r in repo._pm_work_results[job_id] if r.pm_task_id == task)
    return job_id, result.pm_work_result_id, evidence


async def repair_for(repo, *, source_type=RepairSourceType.PM_RESULT, source_id=None, asset=VEHICLE, closed=True):
    repair = await repo.create_repair(AssetType.VEHICLE, asset, source_type, source_id, None, "ซ่อม (synthetic)", None,
                                      "dev-user")
    if closed:
        await repo.close_repair(repair.repair_id, "dev-user", "เสร็จ")
    evidence = (await repo.create_attachment(AttachmentPurpose.REPAIR_EVIDENCE, "synthetic://r", "r.jpg", "image/jpeg",
                                             1, "dev-user", source_type="REPAIR",
                                             source_id=repair.repair_id)).attachment_id
    return repair.repair_id, evidence


# ---------------------------------------------------------------- PH-10 visibility


async def test_ph10_outstanding_is_visible_only_once_closed_and_per_asset() -> None:
    repo = repo_with()
    job_id, _, item = await partial_closed(repo)
    svc = pm_service(repo)
    per_job = await svc.list_outstanding_items(job_id, ctx(U1))
    per_asset = await svc.list_asset_outstanding(AssetType.VEHICLE, VEHICLE, ctx(U1))
    assert [s.item for s in per_job] == [s.item for s in per_asset] == [item]
    assert await svc.list_asset_outstanding(AssetType.VEHICLE, "VEH-OTHER", ctx(U1)) == []


async def test_ph10_an_interrupted_close_never_surfaces_outstanding() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    await start(svc, job_id)
    tasks = await scope_of(repo, job_id)
    await save(svc, job_id, tasks[0])
    for t in tasks[1:]:
        await save(svc, job_id, t, NOT_PERFORMED)
    await submit(svc, repo, job_id)
    repo.fail = {"append_pm_work_order_transition": RuntimeError("synthetic journal failure")}
    with pytest.raises(RuntimeError):
        await close(svc, job_id)
    repo.fail = {}
    assert len([i for i in repo._pm_outstanding.values() if i.pm_work_order_id == job_id]) == 2  # written ...
    assert await svc.list_outstanding_items(job_id, ctx(U1)) == []  # ... but not effective
    assert await svc.list_asset_outstanding(AssetType.VEHICLE, VEHICLE, ctx(U1)) == []


# ---------------------------------------------------------------- PH-12 (G1)


async def test_ph12_repository_refuses_outstanding_without_a_matching_stored_not_performed_outcome() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    job_id = await v2_job(repo)
    await start(svc, job_id)
    tasks = await scope_of(repo, job_id)
    performed = await save(svc, job_id, tasks[0])
    not_performed = await save(svc, job_id, tasks[1], NOT_PERFORMED)
    wo = repo._pm_work_orders[job_id]
    # (1) no stored outcome at all for the identity
    ghost = PmItemOutcome(pm_work_order_id=job_id, pm_task_id=tasks[2], revision_id=wo.revision_id,
                          disposition=Disposition.NOT_PERFORMED, reason_code=WAIT_PARTS, recorded_by=U1,
                          recorded_at=not_performed.outcome.recorded_at)
    # (2) the stored outcome is PERFORMED
    as_np = performed.outcome.model_copy(update={"disposition": Disposition.NOT_PERFORMED, "performed_actions": (),
                                                 "reason_code": WAIT_PARTS})
    # (3) provenance differs from the stored NOT_PERFORMED outcome (reason / actor / time / source)
    for field, value in [("reason_code", "เวลาไม่เพียงพอ"), ("recorded_by", "USR-SYN-OTHER"),
                         ("source_pm_work_result_id", None)]:
        forged = not_performed.outcome.model_copy(update={field: value})
        with pytest.raises(ValueError, match="PM_OUTSTANDING_PROVENANCE_MISMATCH"):
            await repo.create_pm_outstanding_item(build_pm_outstanding_item(forged, created_by=U1,
                                                                            created_at=forged.recorded_at))
    for source, code in [(ghost, "PM_OUTSTANDING_OUTCOME_REQUIRED"), (as_np, "PM_OUTSTANDING_OUTCOME_REQUIRED")]:
        with pytest.raises(ValueError, match=code):
            await repo.create_pm_outstanding_item(build_pm_outstanding_item(source, created_by=U1,
                                                                            created_at=source.recorded_at))
    assert repo._pm_outstanding == {}


async def test_ph12_g1_also_guards_an_idempotent_replay() -> None:
    repo = repo_with()
    job_id, last, item = await partial_closed(repo)
    replay = item.model_copy(update={"created_by": "USR-SYN-OTHER"})
    assert (await repo.create_pm_outstanding_item(replay))[1] is True  # identical provenance: replay
    outcome_id = pm_item_outcome_id(job_id, last, item.revision_id)
    stored = repo._pm_item_outcomes.pop(outcome_id)  # the source outcome disappears behind the service
    with pytest.raises(ValueError, match="PM_OUTSTANDING_OUTCOME_REQUIRED"):
        await repo.create_pm_outstanding_item(replay)
    repo._pm_item_outcomes[outcome_id] = stored


# ---------------------------------------------------------------- PH-16 resolution


async def test_ph16_a_later_performed_pm_on_the_same_item_resolves_only_that_outstanding() -> None:
    repo = repo_with()
    source_id, task, item = await partial_closed(repo)
    source_before = (repo._pm_work_orders[source_id], list(repo._pm_work_results[source_id]))
    later_id, result_id, evidence = await later_pm(repo, task)
    svc = pm_service(repo)
    resolution, replayed = await svc.resolve_outstanding(item.outstanding_id, manager(),
                                                         later_pm_work_result_id=result_id,
                                                         evidence_attachment_ids=evidence)
    assert replayed is False and resolution.later_pm_work_result_id == result_id
    again, replayed = await svc.resolve_outstanding(item.outstanding_id, manager(), later_pm_work_result_id=result_id,
                                                    evidence_attachment_ids=evidence)
    assert replayed is True and again == resolution
    states = await svc.list_outstanding_items(source_id, ctx(U1))
    assert [s.resolution for s in states] == [resolution]
    assert (repo._pm_work_orders[source_id], list(repo._pm_work_results[source_id])) == source_before
    assert later_id != source_id


async def test_ph16_a_repair_raised_from_the_item_resolves_it_but_an_unrelated_repair_does_not() -> None:
    repo = repo_with()
    _, _, item = await partial_closed(repo)
    svc = pm_service(repo)
    unrelated_id, unrelated_evidence = await repair_for(repo, source_type=RepairSourceType.MANUAL)
    assert await refused(svc.resolve_outstanding(item.outstanding_id, manager(), later_repair_id=unrelated_id,
                                                 evidence_attachment_ids=(unrelated_evidence,))) == (
        422, "PM_RESOLUTION_EVIDENCE_INVALID")  # CLOSED, same asset, own evidence — but not this item's work
    related_id, evidence = await repair_for(repo, source_id=item.origin_pm_work_result_id)
    assert await refused(svc.resolve_outstanding(item.outstanding_id, manager(), later_repair_id=related_id,
                                                 evidence_attachment_ids=(unrelated_evidence,))) == (
        422, "PM_RESOLUTION_EVIDENCE_INVALID")  # another Repair's evidence
    resolution, _ = await svc.resolve_outstanding(item.outstanding_id, manager(), later_repair_id=related_id,
                                                  evidence_attachment_ids=(evidence,))
    assert resolution.later_repair_id == related_id
    assert await refused(svc.resolve_outstanding(item.outstanding_id, manager(), later_repair_id=unrelated_id,
                                                 evidence_attachment_ids=(unrelated_evidence,))) == (
        422, "PM_RESOLUTION_EVIDENCE_INVALID")


async def test_ph16_a_repair_converted_from_the_items_repair_request_resolves_it() -> None:
    repo = repo_with()
    _, _, item = await partial_closed(repo)
    request = await repo.create_repair_request(VEHICLE, "dev-user", None, None, None, None, "ชำรุด", None, None)
    repo._repair_requests[request.repair_request_id] = request.model_copy(
        update={"source_type": "PM_RESULT", "source_id": item.origin_pm_work_result_id})
    repair_id, evidence = await repair_for(repo, source_type=RepairSourceType.REPAIR_REQUEST,
                                           source_id=request.repair_request_id)
    await repo.mark_repair_request_converted(request.repair_request_id, repair_id, "dev-user")
    resolution, _ = await pm_service(repo).resolve_outstanding(item.outstanding_id, manager(),
                                                               later_repair_id=repair_id,
                                                               evidence_attachment_ids=(evidence,))
    assert resolution.later_repair_id == repair_id


@pytest.mark.parametrize("case,reason", [
    ("other_task", "different PM item"),
    ("not_closed", "not CLOSED"),
    ("not_performed", "not genuinely Performed"),
    ("no_evidence", "own evidence"),
    ("other_asset", "different asset"),
    ("same_work_order", "different PM work order"),
    ("foreign_evidence", "own evidence"),
])
async def test_ph16_unverified_pm_evidence_is_refused_with_nothing_written(case, reason) -> None:
    from app.errors import ApiError
    repo = repo_with()
    source_id, task, item = await partial_closed(repo)
    tasks = await scope_of(repo, source_id)
    svc = pm_service(repo)
    if case == "other_task":
        _, result_id, evidence = await later_pm(repo, tasks[0])
    elif case == "not_closed":
        _, result_id, evidence = await later_pm(repo, task, close_it=False)
    elif case == "not_performed":
        later_id, result_id, _ = await later_pm(repo, task, performed=False)
        evidence = (await pm_evidence(repo, later_id),)
    elif case == "no_evidence":
        _, result_id, _ = await later_pm(repo, task, with_evidence=False)
        evidence = ("ATT-NONE",)
    elif case == "other_asset":
        _, result_id, evidence = await later_pm(repo, task, asset="VEH-OTHER")
    elif case == "same_work_order":
        result_id = next(r.pm_work_result_id for r in repo._pm_work_results[source_id] if r.pm_task_id == tasks[0])
        evidence = (await pm_evidence(repo, source_id),)
    else:
        later_id, result_id, _ = await later_pm(repo, task)
        evidence = (await pm_evidence(repo, later_id),)  # PM evidence of that work order, but not of that item
    with pytest.raises(ApiError) as refusal:
        await svc.resolve_outstanding(item.outstanding_id, manager(), later_pm_work_result_id=result_id,
                                      evidence_attachment_ids=evidence)
    assert refusal.value.code == "PM_RESOLUTION_EVIDENCE_INVALID" and reason in refusal.value.message
    assert repo._pm_outstanding_resolutions == {}


async def test_ph16_resolution_needs_can_manage_pm_one_source_and_evidence() -> None:
    repo = repo_with()
    _, task, item = await partial_closed(repo)
    _, result_id, evidence = await later_pm(repo, task)
    svc = pm_service(repo)
    assert (await refused(svc.resolve_outstanding(item.outstanding_id, ctx(U1), later_pm_work_result_id=result_id,
                                                  evidence_attachment_ids=evidence)))[0] == 403
    assert (await refused(svc.resolve_outstanding(item.outstanding_id, manager(), evidence_attachment_ids=evidence)))[1] \
        == "PM_RESOLUTION_REFERENCE_SOURCE_INVALID"
    assert (await refused(svc.resolve_outstanding(item.outstanding_id, manager(),
                                                  later_pm_work_result_id=result_id)))[1] \
        == "PM_RESOLUTION_REFERENCE_EVIDENCE_REQUIRED"
    assert (await refused(svc.resolve_outstanding("PMOS-unknown", manager(), later_pm_work_result_id=result_id,
                                                  evidence_attachment_ids=evidence))) == (404, "PM_OUTSTANDING_NOT_FOUND")
    assert repo._pm_outstanding_resolutions == {}


async def test_ph16_repair_closed_before_the_not_performed_item_is_not_later_work() -> None:
    repo = repo_with()
    _, _, item = await partial_closed(repo)
    repair_id, evidence = await repair_for(repo, source_id=item.origin_pm_work_result_id)
    early = repo._repairs[repair_id].model_copy(update={"closed_at": item.origin_recorded_at})
    repo._repairs[repair_id] = early
    assert await refused(pm_service(repo).resolve_outstanding(item.outstanding_id, manager(), later_repair_id=repair_id,
                                                              evidence_attachment_ids=(evidence,))) == (
        422, "PM_RESOLUTION_EVIDENCE_INVALID")



async def test_ph16_a_concurrent_pm_performed_before_the_outstanding_existed_is_not_later_work() -> None:
    """Chronology: a Performed Outcome recorded on another PM of the same asset BEFORE the
    Outstanding was created (concurrent work orders) does not prove the item was done later."""
    repo = repo_with()
    source_id = await v2_job(repo)
    task = (await scope_of(repo, source_id))[-1]
    other_id, result_id, evidence = await later_pm(repo, task, close_it=False)  # Performed now
    await drive_to_closed(repo, source_id, not_performed=(task,))
    item = next(i for i in repo._pm_outstanding.values() if i.pm_work_order_id == source_id)
    svc = pm_service(repo)
    await submit(svc, repo, other_id)
    await close(svc, other_id)  # the other PM is CLOSED, but its work predates the Outstanding
    earlier = next(o for o in repo._pm_item_outcomes.values()
                   if o.pm_work_order_id == other_id and o.pm_task_id == task)
    assert earlier.recorded_at < item.created_at
    assert await refused(svc.resolve_outstanding(item.outstanding_id, manager(), later_pm_work_result_id=result_id,
                                                 evidence_attachment_ids=evidence)) == (
        422, "PM_RESOLUTION_EVIDENCE_INVALID")
    assert await repo.get_pm_outstanding_resolution(item.outstanding_id) is None

# ---------------------------------------------------------------- PH-17


async def test_ph17_due_status_and_outstanding_backlog_stay_separate() -> None:
    repo = repo_with()
    svc = pm_service(repo)
    before = await svc.list_applicable_plan_status(AssetType.VEHICLE, VEHICLE)
    _, _, item = await partial_closed(repo)
    after = await svc.list_applicable_plan_status(AssetType.VEHICLE, VEHICLE)
    # Due remains UNKNOWN (no calculation or anchor was introduced); Outstanding is its own list.
    assert [s.due_status for s in after] == [s.due_status for s in before]
    assert [s.item for s in await svc.list_asset_outstanding(AssetType.VEHICLE, VEHICLE, ctx(U1))] == [item]
