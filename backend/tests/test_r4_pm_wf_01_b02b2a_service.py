"""R4-PM-WF-01 B02-B2A: internal PmService outcome integration — authorization,
source validation, server-owned vocabulary, Outcome -> Outstanding persistence,
replay and partial-write recovery (Mock, synthetic records).

The vocabulary is the server-owned FC-1 wording in `app.domain.pm_service`;
no test supplies its own approved list to the service."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import app.domain.pm_service as pm_service_module
from app.domain import authz
from app.domain.attachment import AttachmentPurpose
from app.domain.pm import PmItemContractDisposition as Disposition, PmItemOutcome
from app.domain.technician_assignment import PM
from app.errors import ApiError
from app.repositories.base import RepositoryWriteError
from tests.test_technician_assignment_batch_r2f_h1 import (
    T1,
    T2,
    T3,
    U1,
    U2,
    U3,
    assign,
    body,
    ctx,
    new_pm,
    pm_service,
    repo_with,
    ta_service,
)

T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
NP, PERFORMED = Disposition.NOT_PERFORMED, Disposition.PERFORMED
# The approved FC-1 wording, read from the server-owned binding (never redefined here).
CHECK, CLEAN, REPLACE = "ตรวจเช็ค", "ทำความสะอาด", "เปลี่ยน / เติม"
WAIT_PARTS, OTHER = "รออะไหล่", pm_service_module.PM_APPROVED_OTHER_REASON


async def v2_job(repo, *, primary=T1, collaborators=(T2,)) -> str:
    job_id = await new_pm(repo)
    await assign(repo, job_id, body(primary, *collaborators), kind=PM)
    return job_id


async def code_of(coro) -> tuple[int, str]:
    try:
        await coro
    except ApiError as exc:
        return exc.status_code, exc.code
    except HTTPException as exc:
        return exc.status_code, "FORBIDDEN"
    raise AssertionError("expected a refusal")


async def scope_task(repo, job_id, index: int = 0) -> str:
    return (await repo.get_pm_work_order(job_id)).work_order.scope_task_ids[index]


def stored(repo, job_id):
    """Every stored Outcome / Outstanding record of the job (direct read)."""
    return ([o for o in repo._pm_item_outcomes.values() if o.pm_work_order_id == job_id],
            [i for i in repo._pm_outstanding.values() if i.pm_work_order_id == job_id])


@pytest.fixture
def clock(monkeypatch):
    now = {"value": T0}
    monkeypatch.setattr(pm_service_module, "_utcnow", lambda: now["value"])
    return now


# ---------------------------------------------------------------- authorization


@pytest.mark.parametrize("user", [U1, U2])  # PRIMARY and COLLABORATOR of the current V2 set
async def test_b02b2a_01_v2_primary_and_collaborator_can_read_and_record(user, clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    service = pm_service(repo)
    task = await scope_task(repo, job_id)
    result = await service.record_item_outcome(job_id, task, NP, ctx(user), reason_code=WAIT_PARTS)
    assert result.outcome.recorded_by == user and result.outstanding is not None
    assert await service.list_item_outcomes(job_id, ctx(user)) == [result.outcome]
    assert await service.list_outstanding_items(job_id, ctx(user)) == [result.outstanding]


async def test_b02b2a_01_am_capability_records_without_membership(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    admin = ctx("USR-ADMIN", authz.CAN_MANAGE_PM)
    result = await pm_service(repo).record_item_outcome(job_id, await scope_task(repo, job_id), PERFORMED, admin,
                                                        performed_actions=(CHECK,))
    assert result.outcome.recorded_by == "USR-ADMIN" and result.outstanding is None


async def test_b02b2a_02_unassigned_revoked_and_legacy_are_denied() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    service = pm_service(repo)
    task = await scope_task(repo, job_id)
    for denied in (service.list_item_outcomes(job_id, ctx(U3)),  # in scope, not in the current set
                   service.record_item_outcome(job_id, task, NP, ctx(U3), reason_code=WAIT_PARTS),
                   service.list_item_outcomes(job_id, ctx("USR-UNKNOWN"))):  # no technician link at all
        assert (await code_of(denied))[0] == 403
    # Revoked: the set is replaced, so the former PRIMARY loses authority.
    await assign(repo, job_id, body(T3, expected=(T1, T2)), kind=PM)
    assert (await code_of(service.record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)))[0] == 403
    assert await service.list_item_outcomes(job_id, ctx(U3)) == []
    # Withdrawn: no current set at all.
    await ta_service(repo).withdraw(PM, job_id, {"expected_current": {"primary_technician_id": T3,
                                                                      "collaborator_technician_ids": []}},
                                    request_id=str(uuid.uuid4()), user_id="dev-user")
    assert (await code_of(service.record_item_outcome(job_id, task, NP, ctx(U3), reason_code=WAIT_PARTS)))[0] == 403
    # LEGACY job: refused even for the AM capability and a seeded legacy assignee.
    legacy_id = await new_pm(repo, legacy=True)
    await repo.assign_pm_work_order(pm_work_order_id=legacy_id, primary_technician=U1, collaborators=[],
                                    assigned_by="dev-user")
    legacy_task = await scope_task(repo, job_id)  # a task of the same plan revision (legacy seed has no scope)
    for context in (ctx(U1), ctx("USR-ADMIN", authz.CAN_MANAGE_PM)):
        assert await code_of(service.list_item_outcomes(legacy_id, context)) == (409, "ASSIGNMENT_MODEL_MISMATCH")
        assert await code_of(service.record_item_outcome(legacy_id, legacy_task, NP, context,
                                                         reason_code=WAIT_PARTS)) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert stored(repo, job_id) == ([], []) and stored(repo, legacy_id) == ([], [])


async def test_b02b2a_02_denormalized_primary_field_never_authorizes() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    work_order = repo._pm_work_orders[job_id]
    repo._pm_work_orders[job_id] = work_order.model_copy(update={"primary_technician": U3, "collaborators": [U3]})
    service = pm_service(repo)
    assert (await code_of(service.list_item_outcomes(job_id, ctx(U3))))[0] == 403
    assert (await code_of(service.record_item_outcome(job_id, work_order.scope_task_ids[0], NP, ctx(U3),
                                                      reason_code=WAIT_PARTS)))[0] == 403


@pytest.mark.parametrize("context", [None, "not-a-context", {"user_id": U1}])
async def test_b02b2a_02_untrusted_or_missing_context_is_refused(context) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    service = pm_service(repo)
    task = await scope_task(repo, job_id)
    for bad in (context, ctx(None), ctx("  ")):
        assert await code_of(service.list_item_outcomes(job_id, bad)) == (403, "PM_OUTCOME_CONTEXT_REQUIRED")
        assert await code_of(service.record_item_outcome(job_id, task, NP, bad, reason_code=WAIT_PARTS)) == (
            403, "PM_OUTCOME_CONTEXT_REQUIRED")
    assert stored(repo, job_id) == ([], [])


async def test_b02b2a_03_unauthorized_read_and_replay_are_denied_without_change(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    service = pm_service(repo)
    first = await service.record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)
    before = stored(repo, job_id)
    for denied in (service.list_item_outcomes(job_id, ctx(U3)), service.list_outstanding_items(job_id, ctx(U3)),
                   service.record_item_outcome(job_id, task, NP, ctx(U3), reason_code=WAIT_PARTS)):
        assert (await code_of(denied))[0] == 403
    assert stored(repo, job_id) == before == ([first.outcome], [first.outstanding])


# ---------------------------------------------------------------- vocabulary


@pytest.mark.parametrize("name,code", [
    ("PM_APPROVED_NOT_PERFORMED_REASONS", "PM_APPROVED_REASON_SOURCE_REQUIRED"),
    ("PM_APPROVED_PERFORMED_ACTIONS", "PM_APPROVED_ACTION_SOURCE_REQUIRED"),
])
async def test_b02b2a_04_missing_server_vocabulary_fails_closed(name, code, monkeypatch) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    monkeypatch.setattr(pm_service_module, name, frozenset())
    disposition, kw = ((NP, {"reason_code": WAIT_PARTS}) if "REASONS" in name
                       else (PERFORMED, {"performed_actions": (CHECK,)}))
    assert await code_of(pm_service(repo).record_item_outcome(job_id, task, disposition, ctx(U1), **kw)) == (
        422, code)
    assert stored(repo, job_id) == ([], [])


async def test_b02b2a_04_caller_cannot_supply_an_approved_list() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    for approved_list in ("approved_not_performed_reasons", "approved_performed_actions",
                          "approved_other_reason_code", "vocabulary"):
        with pytest.raises(TypeError):
            await pm_service(repo).record_item_outcome(job_id, task, NP, ctx(U1), reason_code="INVENTED",
                                                       **{approved_list: frozenset({"INVENTED"})})
    assert stored(repo, job_id) == ([], [])


@pytest.mark.parametrize("disposition,kw,code", [
    (PERFORMED, {"performed_actions": ()}, "PM_PERFORMED_ACTION_INVALID"),
    (PERFORMED, {"performed_actions": ("ล้างเครื่อง",)}, "PM_PERFORMED_ACTION_INVALID"),  # not approved
    (PERFORMED, {"performed_actions": ("เปลี่ยน/เติม",)}, "PM_PERFORMED_ACTION_INVALID"),  # alias, not exact
    (PERFORMED, {"performed_actions": (CHECK, CLEAN, REPLACE)}, "PM_PERFORMED_ACTION_INVALID"),
    (PERFORMED, {"performed_actions": (CHECK, CHECK)}, "PM_PERFORMED_ACTION_INVALID"),
    (PERFORMED, {"performed_actions": (CHECK,), "reason_code": WAIT_PARTS}, "PM_PERFORMED_REASON_CONFLICT"),
    (NP, {}, "PM_NOT_PERFORMED_REASON_REQUIRED"),
    (NP, {"reason_code": "รอช่าง"}, "PM_NOT_PERFORMED_REASON_REQUIRED"),  # not approved
    (NP, {"reason_code": WAIT_PARTS, "performed_actions": (CHECK,)}, "PM_NOT_PERFORMED_ACTION_CONFLICT"),
    (NP, {"reason_code": OTHER}, "PM_OTHER_REASON_TEXT_REQUIRED"),
    (NP, {"reason_code": OTHER, "other_text": "   "}, "PM_OTHER_REASON_TEXT_REQUIRED"),
])
async def test_b02b2a_05_unknown_actions_reasons_and_missing_other_text_are_denied(disposition, kw, code) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    assert await code_of(pm_service(repo).record_item_outcome(job_id, task, disposition, ctx(U1), **kw)) == (
        422, code)
    assert stored(repo, job_id) == ([], [])


# ---------------------------------------------------------------- source validation


async def test_b02b2a_06_work_order_task_revision_and_scope_are_verified() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    service = pm_service(repo)
    admin = ctx("USR-ADMIN", authz.CAN_MANAGE_PM)
    work_order = repo._pm_work_orders[job_id]
    ok = {"reason_code": WAIT_PARTS}
    assert await code_of(service.record_item_outcome("PMWO-9999", "PMT-0001", NP, admin, **ok)) == (
        404, "PM_WORK_ORDER_NOT_FOUND")
    assert await code_of(service.record_item_outcome(job_id, "PMT-9999", NP, admin, **ok)) == (
        422, "VALIDATION_ERROR")
    in_revision_out_of_scope = work_order.scope_task_ids[-1]
    repo._pm_work_orders[job_id] = work_order.model_copy(update={"scope_task_ids": work_order.scope_task_ids[:-1]})
    assert await code_of(service.record_item_outcome(job_id, in_revision_out_of_scope, NP, admin, **ok)) == (
        422, "PM_TASK_NOT_IN_SCOPE")
    repo._pm_work_orders[job_id] = work_order.model_copy(update={"revision_id": "PMREV-9999"})
    assert await code_of(service.record_item_outcome(job_id, work_order.scope_task_ids[0], NP, admin, **ok)) == (
        404, "PM_TASK_REVISION_NOT_FOUND")
    repo._pm_work_orders[job_id] = work_order
    assert await code_of(service.record_item_outcome(job_id, work_order.scope_task_ids[0], "NOT_PERFORMED",
                                                     admin, **ok)) == (422, "VALIDATION_ERROR")  # untyped
    assert await code_of(service.record_item_outcome(job_id, work_order.scope_task_ids[0], NP, admin,
                                                     source_pm_work_result_id="PMWR-9999", **ok)) == (
        422, "PM_OUTCOME_SOURCE_RESULT_INVALID")
    assert stored(repo, job_id) == ([], [])


async def test_b02b2a_07_closed_work_order_is_denied() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    await repo.close_pm_work_order(job_id, "dev-user", None)
    assert await code_of(pm_service(repo).record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)) == (
        422, "PM_WORK_ORDER_CLOSED")
    assert stored(repo, job_id) == ([], [])


async def test_b02b2a_08_evidence_attachments_must_be_pm_evidence_of_this_work_order(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    other_id = await v2_job(repo)
    task = await scope_task(repo, job_id)

    async def attachment(purpose=AttachmentPurpose.PM_EVIDENCE, source_type="PM_WORK_ORDER", source_id=job_id):
        return (await repo.create_attachment(purpose, "synthetic://ref", "e.jpg", "image/jpeg", 1, U1,
                                             source_type=source_type, source_id=source_id)).attachment_id

    good = await attachment()
    bad = [await attachment(source_id=other_id), await attachment(purpose=AttachmentPurpose.REPAIR_EVIDENCE,
                                                                  source_type="REPAIR"),
           await attachment(source_type=None, source_id=None), "ATT-DOES-NOT-EXIST", " "]
    service = pm_service(repo)
    for attachment_id in bad:
        assert await code_of(service.record_item_outcome(job_id, task, PERFORMED, ctx(U1), performed_actions=(CHECK,),
                                                         evidence_attachment_ids=(good, attachment_id))) == (
            422, "PM_OUTCOME_EVIDENCE_INVALID")
    assert stored(repo, job_id) == ([], [])
    result = await service.record_item_outcome(job_id, task, PERFORMED, ctx(U1), performed_actions=(CHECK,),
                                               evidence_attachment_ids=(good,))
    assert result.outcome.evidence_attachment_ids == (good,)


# ---------------------------------------------------------------- persistence


async def test_b02b2a_09_performed_is_stored_without_outstanding(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    service = pm_service(repo)
    for index, actions in enumerate([(CHECK,), (CLEAN, REPLACE)]):
        task = await scope_task(repo, job_id, index)
        result = await service.record_item_outcome(job_id, task, PERFORMED, ctx(U1), performed_actions=actions)
        assert (result.outcome.disposition, result.outcome.performed_actions, result.outcome.reason_code) == (
            PERFORMED, actions, None)
        assert result.outstanding is None and result.outcome_replayed is False
        assert await repo.get_pm_item_outcome(result.outcome.outcome_id) == result.outcome
    outcomes, outstanding = stored(repo, job_id)
    assert len(outcomes) == 2 and outstanding == []


async def test_b02b2a_10_not_performed_stores_the_outcome_before_the_outstanding(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    repo.calls.clear()
    result = await pm_service(repo).record_item_outcome(job_id, task, NP, ctx(U1), reason_code=OTHER,
                                                        other_text="รถออกงานด่วน")
    writes = [c for c in repo.calls if c.startswith("create_")]
    assert writes == ["create_pm_item_outcome", "create_pm_outstanding_item"]
    assert repo.calls.index("get_pm_item_outcome") < repo.calls.index("create_pm_outstanding_item")
    assert result.outcome.disposition == NP and result.outstanding is not None


async def test_b02b2a_11_outstanding_provenance_equals_the_stored_outcome(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    result = await pm_service(repo).record_item_outcome(job_id, task, NP, ctx(U2), reason_code=OTHER,
                                                        other_text="รถออกงานด่วน")
    outcome = await repo.get_pm_item_outcome(result.outcome.outcome_id)
    item = await repo.get_pm_outstanding_item(result.outstanding.outstanding_id)
    assert outcome == result.outcome and item == result.outstanding
    assert item.source_identity == outcome.source_identity
    assert (item.origin_reason_code, item.origin_other_text, item.origin_recorded_by, item.origin_recorded_at,
            item.origin_pm_work_result_id) == (OTHER, "รถออกงานด่วน", U2, T0, None)
    assert item.outstanding_id == outcome.source_identity.outstanding_id  # derived from the same source identity


async def test_b02b2a_12_identical_replay_does_not_duplicate(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    service = pm_service(repo)
    first = await service.record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)
    clock["value"] = T0 + timedelta(minutes=10)  # a retry later must keep the original provenance
    again = await service.record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)
    assert (again.outcome_replayed, again.outstanding_replayed) == (True, True)
    assert (again.outcome, again.outstanding) == (first.outcome, first.outstanding)
    assert again.outcome.recorded_at == T0
    assert stored(repo, job_id) == ([first.outcome], [first.outstanding])
    task2 = await scope_task(repo, job_id, 1)
    p1 = await service.record_item_outcome(job_id, task2, PERFORMED, ctx(U1), performed_actions=(CHECK,))
    p2 = await service.record_item_outcome(job_id, task2, PERFORMED, ctx(U1), performed_actions=(CHECK,))
    assert p2.outcome_replayed and p2.outcome == p1.outcome and len(stored(repo, job_id)[0]) == 2


@pytest.mark.parametrize("changes", [
    {"context": ctx(U2)},  # another authorized member may not take over the recorded actor
    {"kw": {"reason_code": "เวลาไม่เพียงพอ"}},
    {"kw": {"reason_code": OTHER, "other_text": "อื่น"}},
    {"disposition": PERFORMED, "kw": {"performed_actions": (CHECK,)}},
])
async def test_b02b2a_13_conflicting_replay_fails_closed(changes, clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    service = pm_service(repo)
    await service.record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)
    before = stored(repo, job_id)
    clock["value"] = T0 + timedelta(minutes=5)
    assert await code_of(service.record_item_outcome(job_id, task, changes.get("disposition", NP),
                                                     changes.get("context", ctx(U1)),
                                                     **changes.get("kw", {"reason_code": WAIT_PARTS}))) == (
        409, "PM_OUTCOME_CONFLICT")
    assert stored(repo, job_id) == before


async def test_b02b2a_13_untruthful_stored_record_is_not_reused() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    work_order = repo._pm_work_orders[job_id]
    task = work_order.scope_task_ids[0]
    legacy_code = PmItemOutcome(pm_work_order_id=job_id, pm_task_id=task, revision_id=work_order.revision_id,
                                disposition=NP, reason_code="SYNTH-UNAPPROVED", recorded_by=U1, recorded_at=T0)
    await repo.create_pm_item_outcome(legacy_code)  # a record outside the approved wording
    assert (await code_of(pm_service(repo).record_item_outcome(job_id, task, NP, ctx(U1),
                                                               reason_code="SYNTH-UNAPPROVED")))[0] == 422
    assert stored(repo, job_id) == ([legacy_code], [])


# ---------------------------------------------------------------- partial writes


async def test_b02b2a_14_outcome_write_failure_creates_no_outstanding(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    repo.fail = {"create_pm_item_outcome": RepositoryWriteError("pm_item_outcome", "unknown", None, "synthetic")}
    with pytest.raises(RepositoryWriteError):
        await pm_service(repo).record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)
    assert stored(repo, job_id) == ([], [])
    assert "create_pm_outstanding_item" not in repo.calls


async def test_b02b2a_15_16_outstanding_failure_reports_no_success_and_retry_recovers(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    service = pm_service(repo)
    repo.fail = {"create_pm_outstanding_item": RepositoryWriteError("pm_outstanding", "unknown", None, "synthetic")}
    with pytest.raises(RepositoryWriteError):  # 15: never a success response
        await service.record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)
    outcomes, outstanding = stored(repo, job_id)
    assert len(outcomes) == 1 and outstanding == []  # the immutable Outcome is preserved
    original = outcomes[0]
    repo.fail = {}
    clock["value"] = T0 + timedelta(hours=2)
    recovered = await service.record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)  # 16
    assert recovered.outcome_replayed is True and recovered.outstanding_replayed is False
    assert recovered.outcome == original and recovered.outcome.recorded_at == T0
    assert recovered.outstanding.origin_recorded_at == T0  # original provenance, not the retry time
    assert recovered.outstanding.created_at == T0 + timedelta(hours=2)
    assert stored(repo, job_id) == ([original], [recovered.outstanding])
    again = await service.record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)
    assert (again.outcome_replayed, again.outstanding_replayed) == (True, True)
    assert stored(repo, job_id) == ([original], [recovered.outstanding])  # no duplicate


class _Tampering(type(repo_with())):
    """Reads back a record that differs from what was written."""
    tamper: str = ""

    async def get_pm_item_outcome(self, outcome_id):
        found = await super().get_pm_item_outcome(outcome_id)
        if found is not None and self.tamper == "outcome":
            return found.model_copy(update={"evidence_attachment_ids": ("ATT-FORGED",)})
        return found

    async def get_pm_outstanding_item(self, outstanding_id):
        found = await super().get_pm_outstanding_item(outstanding_id)
        if found is not None and self.tamper == "outstanding":
            return found.model_copy(update={"origin_recorded_by": "USR-FORGED"})
        return found


@pytest.mark.parametrize("tamper", ["outcome", "outstanding"])
async def test_b02b2a_17_readback_mismatch_fails_closed(tamper, clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = await scope_task(repo, job_id)
    repo.__class__ = _Tampering
    repo.tamper = tamper
    assert await code_of(pm_service(repo).record_item_outcome(job_id, task, NP, ctx(U1), reason_code=WAIT_PARTS)) == (
        500, "PM_OUTCOME_READBACK_MISMATCH")
    outcomes, outstanding = stored(repo, job_id)
    assert len(outcomes) == 1  # the written record is kept (never deleted), but success is not reported
    assert len(outstanding) == (0 if tamper == "outcome" else 1)  # written, yet never reported as success
    if tamper == "outcome":
        assert "create_pm_outstanding_item" not in repo.calls


# ---------------------------------------------------------------- legacy boundary


async def test_b02b2a_18_legacy_completed_result_is_not_an_outcome(clock) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    service = pm_service(repo)
    task_done, task_open = await scope_task(repo, job_id, 0), await scope_task(repo, job_id, 1)
    await service.submit_task_result(job_id, task_done, True, None, None, [], [], U1)  # legacy completed=True
    await service.submit_task_result(job_id, task_open, False, None, None, [], [], U1)  # legacy completed=False
    results = {r.pm_task_id: r for r in (await repo.get_pm_work_order(job_id)).results}
    assert await service.list_item_outcomes(job_id, ctx(U1)) == []  # no outcome is inferred
    assert await service.list_outstanding_items(job_id, ctx(U1)) == []
    # The stated disposition is recorded as stated; the legacy flag is only provenance.
    np = await service.record_item_outcome(job_id, task_done, NP, ctx(U1), reason_code=WAIT_PARTS,
                                           source_pm_work_result_id=results[task_done].pm_work_result_id)
    done = await service.record_item_outcome(job_id, task_open, PERFORMED, ctx(U1), performed_actions=(CHECK,),
                                             source_pm_work_result_id=results[task_open].pm_work_result_id)
    assert (np.outcome.disposition, done.outcome.disposition) == (NP, PERFORMED)
    after = {r.pm_task_id: r for r in (await repo.get_pm_work_order(job_id)).results}
    assert after == results  # the legacy results are unchanged
