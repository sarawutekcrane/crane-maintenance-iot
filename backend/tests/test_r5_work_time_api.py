"""R5 T3 — technician work time: recording, corrections, confirmation (OD-2, OD-4,
AMB-2), replay, overlap, scope and the HTTP contract. Mock repository with the
R2f-h1 synthetic TEST personnel (USR-SYN-n → TEC-SYN-n). Also hosts the shared
R5 fixtures imported by the other R5 test modules."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import authz
from app.domain.technician_assignment import PM, REPAIR
from app.domain.work_time import TIME_CLASS_OVERTIME, TIME_CLASS_REGULAR, WORK_KIND_PM, WORK_KIND_REPAIR, WorkBreak
from app.domain.work_time_service import WorkTimeService
from app.errors import ApiError
from tests.pm_e01_support import start as pm_start
from tests.pm_e01_support import v2_job
from tests.test_technician_assignment_batch_r2f_h1 import (
    T1,
    T2,
    T3,
    U1,
    U2,
    U3,
    assign,
    body,
    code_of,
    ctx,
    cut,
    http,
    new_repair,
    pm_service,
    repo_with,
)

# ---------------------------------------------------------------- shared R5 fixtures

MANAGER = "USR-SYN-MANAGER"  # a manager with no technician link
BASE = (datetime.now(timezone.utc) - timedelta(days=10)).replace(minute=0, second=0, microsecond=0)


def t(hours: float) -> datetime:
    return BASE + timedelta(hours=hours)


def rid() -> str:
    return str(uuid.uuid4())


def repair_manager(user: str = MANAGER, *extra: str):
    return ctx(user, authz.CAN_MANAGE_REPAIR, authz.CAN_CLOSE_REPAIR, *extra)


def pm_manager(user: str = MANAGER, *extra: str):
    return ctx(user, authz.CAN_MANAGE_PM, *extra)


def svc(repo, **kw) -> WorkTimeService:
    return WorkTimeService(repo, cut(**kw))


async def repair_job(repo, primary=T1, *collaborators) -> str:
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(primary, *(collaborators or (T2,))))
    return job_id


async def pm_job_started(repo) -> str:
    job_id = await v2_job(repo)  # PRIMARY T1 / U1, COLLABORATOR T2 / U2
    await pm_start(pm_service(repo), job_id)
    return job_id


def entry_body(start: datetime, end: datetime, klass: str = TIME_CLASS_REGULAR, breaks=(), description="งานซ่อม",
               technician_id: str | None = None) -> dict:
    return {"started_at": start.isoformat(), "ended_at": end.isoformat(), "time_class": klass,
            "description": description, "technician_id": technician_id,
            "breaks": None if breaks is None else [{"started_at": b[0].isoformat(), "ended_at": b[1].isoformat()}
                                                   for b in breaks]}


async def record(service, kind, job_id, context, start, end, klass=TIME_CLASS_REGULAR, breaks=(),
                 request_id=None, description="งานซ่อม", technician_id=None):
    payload = entry_body(start, end, klass, breaks, description, technician_id)
    return await service.record_entry(
        kind, job_id, context, body=payload, technician_id=technician_id, started_at=start, ended_at=end,
        breaks=None if breaks is None else [WorkBreak(started_at=b[0], ended_at=b[1]) for b in breaks],
        time_class=klass, description=description, request_id=request_id or rid())


async def correct(service, kind, job_id, entry_id, context, revision, start, end, *, reason="แก้เวลา",
                  klass=TIME_CLASS_REGULAR, breaks=(), request_id=None, action="CORRECT"):
    payload = {"action": action, "expected_revision": revision, "reason": reason, **entry_body(start, end, klass,
                                                                                               breaks)}
    payload.pop("technician_id")
    return await service.revise_entry(
        kind, job_id, entry_id, context, body=payload, action=action, expected_revision=revision, reason=reason,
        started_at=start, ended_at=end, breaks=[WorkBreak(started_at=b[0], ended_at=b[1]) for b in breaks],
        time_class=klass, description="งานซ่อม (แก้ไข)", request_id=request_id or rid())


async def confirm(service, kind, job_id, context, *refs, request_id=None):
    payload = {"entries": [{"entry_id": e, "revision": r} for e, r in refs], "note": None}
    return await service.confirm(kind, job_id, context, body=payload, entries=list(refs), note=None,
                                 request_id=request_id or rid())


async def view(repo, kind, job_id):
    job = await svc(repo).locate_job(kind, job_id)
    return await svc(repo).job_view(kind, job)


# ---------------------------------------------------------------- OD-4: own time only


@pytest.mark.asyncio
async def test_a_technician_records_own_time_resolved_on_the_server() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    entry, replayed = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    assert not replayed
    assert (entry.technician_id, entry.recorded_by, entry.revision, entry.record_kind) == (T1, U1, 1, "ENTRY")
    assert entry.member_set_id and entry.is_test_data == "TRUE"


@pytest.mark.asyncio
async def test_on_behalf_entry_is_refused_for_technicians_and_managers() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    assert await code_of(record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(1), technician_id=T2)) == \
        "WORK_TIME_ON_BEHALF_REFUSED"
    assert await code_of(record(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), t(0), t(1),
                                technician_id=T1)) == "WORK_TIME_ON_BEHALF_REFUSED"
    assert await code_of(record(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), t(0), t(1))) == \
        "WORK_TIME_ACTOR_NOT_TECHNICIAN"
    assert await repo.list_work_time_records(WORK_KIND_REPAIR, job) == []


@pytest.mark.asyncio
async def test_non_members_are_refused_and_former_members_may_record_their_past_work() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    assert await code_of(record(svc(repo), WORK_KIND_REPAIR, job, ctx(U3), t(0), t(1))) == "WORK_TIME_NOT_MEMBER"
    await assign(repo, job, body(T3, expected=(T1, T2)))  # handover: T1 and T2 leave the current team
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(2))
    assert entry.technician_id == T1  # handover history honoured
    entry3, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U3), t(2), t(3))
    assert entry3.technician_id == T3


@pytest.mark.asyncio
async def test_pm_work_time_window_follows_e01() -> None:
    repo = repo_with()
    job = await v2_job(repo)
    assert await code_of(record(svc(repo), WORK_KIND_PM, job, ctx(U1), t(0), t(1))) == "WORK_TIME_WINDOW_CLOSED"
    await pm_start(pm_service(repo), job)
    entry, _ = await record(svc(repo), WORK_KIND_PM, job, ctx(U2), t(0), t(1))
    assert entry.work_kind == WORK_KIND_PM and entry.technician_id == T2


# ---------------------------------------------------------------- validation


@pytest.mark.asyncio
async def test_explicit_break_declaration_regular_overtime_and_invalid_values() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    service = svc(repo)
    assert await code_of(record(service, WORK_KIND_REPAIR, job, ctx(U1), t(0), t(8), breaks=None)) == \
        "WORK_TIME_BREAKS_REQUIRED"
    assert await code_of(record(service, WORK_KIND_REPAIR, job, ctx(U1), t(4), t(2))) == "WORK_TIME_INVALID_INTERVAL"
    assert await code_of(record(service, WORK_KIND_REPAIR, job, ctx(U1), t(0), t(8), breaks=[(t(9), t(10))])) == \
        "WORK_TIME_BREAK_INVALID"
    assert await code_of(record(service, WORK_KIND_REPAIR, job, ctx(U1), t(0), t(8), klass="NIGHT")) == \
        "WORK_TIME_CLASS_INVALID"
    assert await code_of(record(service, WORK_KIND_REPAIR, job, ctx(U1), t(0), t(8), description=" ")) == \
        "WORK_TIME_DESCRIPTION_REQUIRED"
    await record(service, WORK_KIND_REPAIR, job, ctx(U1), t(0), t(9), breaks=[(t(4), t(5))])
    await record(service, WORK_KIND_REPAIR, job, ctx(U1), t(10), t(12), TIME_CLASS_OVERTIME)
    totals = (await view(repo, WORK_KIND_REPAIR, job))["technicians"][T1]
    assert (totals["regular_seconds"], totals["overtime_seconds"]) == (8 * 3600, 2 * 3600)


@pytest.mark.asyncio
async def test_backdated_and_cross_midnight_entries_without_a_maximum_length() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    night, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(-50), t(-20), TIME_CLASS_OVERTIME)
    assert night.ended_at - night.started_at == timedelta(hours=30)
    assert len((await view(repo, WORK_KIND_REPAIR, job))["technicians"][T1]["workdays"]) >= 2


# ---------------------------------------------------------------- replay, overlap, stale


@pytest.mark.asyncio
async def test_identical_retry_replays_and_a_reused_request_id_with_another_body_is_refused() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    request_id = rid()
    first, replayed1 = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(2), request_id=request_id)
    again, replayed2 = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(2), request_id=request_id)
    assert (replayed1, replayed2, again.entry_id) == (False, True, first.entry_id)
    assert len(await repo.list_work_time_records(WORK_KIND_REPAIR, job)) == 1
    assert await code_of(record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(3), t(4), request_id=request_id)) == \
        "WORK_TIME_REQUEST_CONFLICT"
    # A re-sent intent under a NEW id is refused by the self-overlap rule: no duplicate time.
    assert await code_of(record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(2))) == "WORK_TIME_OVERLAP"
    assert len(await repo.list_work_time_records(WORK_KIND_REPAIR, job)) == 1


@pytest.mark.asyncio
async def test_same_technician_overlap_across_repair_and_pm_is_refused_naming_the_other_job() -> None:
    repo = repo_with()
    repair = await repair_job(repo)
    pm = await pm_job_started(repo)
    await record(svc(repo), WORK_KIND_REPAIR, repair, ctx(U1), t(0), t(4))
    with pytest.raises(ApiError) as exc:
        await record(svc(repo), WORK_KIND_PM, pm, ctx(U1), t(3), t(5))
    assert exc.value.code == "WORK_TIME_OVERLAP" and exc.value.details["job_id"] == repair
    await record(svc(repo), WORK_KIND_PM, pm, ctx(U1), t(4), t(5))  # adjacent is fine
    await record(svc(repo), WORK_KIND_PM, pm, ctx(U2), t(0), t(4))  # another technician may overlap
    assert len(await repo.list_work_time_records(WORK_KIND_PM, pm)) == 2


@pytest.mark.asyncio
async def test_concurrent_overlapping_entries_for_one_technician_admit_exactly_one() -> None:
    import asyncio

    repo = repo_with()
    repair = await repair_job(repo)
    pm = await pm_job_started(repo)
    results = await asyncio.gather(record(svc(repo), WORK_KIND_REPAIR, repair, ctx(U1), t(0), t(4)),
                                   record(svc(repo), WORK_KIND_PM, pm, ctx(U1), t(1), t(3)),
                                   return_exceptions=True)
    assert sum(1 for r in results if not isinstance(r, Exception)) == 1
    assert [r.code for r in results if isinstance(r, ApiError)] == ["WORK_TIME_OVERLAP"]


@pytest.mark.asyncio
async def test_corrections_need_a_reason_the_current_revision_and_the_right_actor() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    assert await code_of(correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, ctx(U1), 1, t(0), t(5),
                                 reason=" ")) == "WORK_TIME_REASON_REQUIRED"
    assert await code_of(correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, ctx(U2), 1, t(0), t(5))) == \
        "WORK_TIME_CORRECTION_FORBIDDEN"
    second, _ = await correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, ctx(U1), 1, t(0), t(5))
    assert (second.revision, second.record_kind, second.reason) == (2, "CORRECTION", "แก้เวลา")
    assert await code_of(correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, ctx(U1), 1, t(0), t(6))) == \
        "WORK_TIME_REVISION_STALE"
    third, _ = await correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, repair_manager(), 2, t(1), t(5))
    assert third.revision == 3 and third.recorded_by == MANAGER


# ---------------------------------------------------------------- confirmation (OD-2, OD-4, AMB-2)


@pytest.mark.asyncio
async def test_amb2_1_a_manager_may_confirm_an_entry_they_corrected() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U2), t(0), t(4))
    corrected, _ = await correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, repair_manager(), 1, t(0), t(3))
    confirmation, _ = await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 2))
    assert confirmation.confirmed_by == MANAGER == corrected.recorded_by
    assert (await view(repo, WORK_KIND_REPAIR, job))["unconfirmed_count"] == 0


@pytest.mark.asyncio
async def test_amb2_2_a_manager_never_confirms_their_own_technician_time() -> None:
    repo = repo_with()
    job = await repair_job(repo, T1, T3)  # U3 / T3 is on the team and also holds the manager capability
    own, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U3), t(0), t(4))
    assert await code_of(confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(U3), (own.entry_id, 1))) == \
        "WORK_TIME_SELF_CONFIRMATION_REFUSED"
    other, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    confirmation, _ = await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(U3), (other.entry_id, 1))
    assert confirmation.confirmer_technician_id == T3


@pytest.mark.asyncio
async def test_amb2_3_confirmation_needs_the_jobs_own_manager_authority() -> None:
    repo = repo_with()
    repair = await repair_job(repo)
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, repair, ctx(U1), t(0), t(4))
    for context in (ctx(U2), pm_manager(), ctx(MANAGER, authz.CAN_MANAGE_FINDING_REPAIR)):
        assert await code_of(confirm(svc(repo), WORK_KIND_REPAIR, repair, context, (entry.entry_id, 1))) == \
            "WORK_TIME_CONFIRMATION_FORBIDDEN"
    pm = await pm_job_started(repo)
    pm_entry, _ = await record(svc(repo), WORK_KIND_PM, pm, ctx(U2), t(10), t(12))
    assert await code_of(confirm(svc(repo), WORK_KIND_PM, pm, repair_manager(), (pm_entry.entry_id, 1))) == \
        "WORK_TIME_CONFIRMATION_FORBIDDEN"
    await confirm(svc(repo), WORK_KIND_PM, pm, pm_manager(), (pm_entry.entry_id, 1))


@pytest.mark.asyncio
async def test_finding_round_confirmation_needs_the_finding_authority() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    repo._repairs[job] = repo._repairs[job].model_copy(update={"finding_id": "F-SYN-R5"})  # R3 round marker
    assert await code_of(confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1))) == \
        "WORK_TIME_CONFIRMATION_FORBIDDEN"
    await confirm(svc(repo), WORK_KIND_REPAIR, job, ctx(MANAGER, authz.CAN_MANAGE_FINDING_REPAIR),
                  (entry.entry_id, 1))


@pytest.mark.asyncio
async def test_amb2_4_and_5_obsolete_revisions_are_not_confirmed_and_a_correction_needs_a_new_one() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1))
    assert (await view(repo, WORK_KIND_REPAIR, job))["unconfirmed_count"] == 0
    await correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, ctx(U1), 1, t(0), t(5))
    state = await view(repo, WORK_KIND_REPAIR, job)
    assert state["unconfirmed_count"] == 1 and state["entries"][0]["confirmed"] is False
    assert await code_of(confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1))) == \
        "WORK_TIME_REVISION_STALE"
    await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 2))
    assert (await view(repo, WORK_KIND_REPAIR, job))["unconfirmed_count"] == 0


@pytest.mark.asyncio
async def test_amb2_6_correction_and_confirmation_keep_complete_audit_evidence() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    await correct(svc(repo), WORK_KIND_REPAIR, job, entry.entry_id, repair_manager(), 1, t(1), t(4),
                  reason="เริ่มงานจริง 1 ชม. ช้ากว่า")
    await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 2))
    state = await view(repo, WORK_KIND_REPAIR, job)
    revisions = state["entries"][0]["revisions"]
    assert [(r.revision, r.started_at, r.recorded_by) for r in revisions] == [(1, t(0), U1), (2, t(1), MANAGER)]
    assert revisions[1].reason == "เริ่มงานจริง 1 ชม. ช้ากว่า" and revisions[1].recorded_at is not None
    assert [(c.confirmed_by, c.entries) for c in state["confirmations"]] == [(MANAGER, (f"{entry.entry_id}@2",))]


@pytest.mark.asyncio
async def test_confirmation_replay_and_an_already_confirmed_revision_write_nothing_new() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(4))
    request_id = rid()
    first, replayed = await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1),
                                    request_id=request_id)
    again, replayed2 = await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1),
                                     request_id=request_id)
    assert (replayed, replayed2, again.confirmation_id) == (False, True, first.confirmation_id)
    none, replayed3 = await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1))
    assert none is None and replayed3 is True
    assert len(await repo.list_work_time_confirmations(WORK_KIND_REPAIR, job)) == 1


# ---------------------------------------------------------------- scope


@pytest.mark.asyncio
async def test_unconfigured_context_and_another_scope_fail_closed_with_zero_writes() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    assert await code_of(record(svc(repo, context=None), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(1))) == \
        "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    repo._repairs[job] = repo._repairs[job].model_copy(update={"test_batch_id": "OTHER-BATCH"})
    assert await code_of(record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(1))) == \
        "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH"
    assert await repo.list_work_time_records(WORK_KIND_REPAIR, job) == []


# ---------------------------------------------------------------- HTTP contract


def _payload(start, end, **kw):
    out = entry_body(start, end, **kw)
    out.pop("technician_id")
    return out


@pytest.mark.asyncio
async def test_http_record_read_and_request_id_and_strict_body_rules() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    path = f"/api/v1/repairs/{job}/work-time"
    missing_id = await http("POST", path, repo, role="TECHNICIAN", user=U1, json=_payload(t(0), t(2)), request_id=None)
    assert (missing_id.status_code, missing_id.json()["error"]["code"]) == (422, "REQUEST_ID_REQUIRED")
    extra = await http("POST", path, repo, role="TECHNICIAN", user=U1, json={**_payload(t(0), t(2)), "x": 1})
    assert extra.status_code == 422
    no_breaks = _payload(t(0), t(2))
    no_breaks.pop("breaks")
    refused = await http("POST", path, repo, role="TECHNICIAN", user=U1, json=no_breaks)
    assert (refused.status_code, refused.json()["error"]["code"]) == (422, "WORK_TIME_BREAKS_REQUIRED")
    ok = await http("POST", path, repo, role="TECHNICIAN", user=U1, json=_payload(t(0), t(2)))
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["replayed"] is False and data["technicians"][T1]["total_seconds"] == 7200
    assert data["team"]["total_seconds"] == 7200 and data["unconfirmed_count"] == 1
    read = await http("GET", path, repo, role="MAINTENANCE")
    assert read.status_code == 200 and len(read.json()["entries"]) == 1
    # Reads reuse the existing Repair detail rule unchanged: a read capability (can_view) or current team
    # membership. A caller with neither is refused.
    outsider = await http("GET", path, repo, role="NO_SUCH_ROLE", user=U3)
    assert outsider.status_code == 403


@pytest.mark.asyncio
async def test_http_pm_routes_and_confirmation() -> None:
    repo = repo_with()
    job = await pm_job_started(repo)
    ok = await http("POST", f"/api/v1/pm/work-orders/{job}/work-time", repo, role="TECHNICIAN", user=U1,
                    json=_payload(t(0), t(3)))
    assert ok.status_code == 200, ok.text
    entry_id = ok.json()["entries"][0]["entry"]["entry_id"]
    confirmed = await http("POST", f"/api/v1/pm/work-orders/{job}/work-time/confirmations", repo, role="MAINTENANCE",
                           json={"entries": [{"entry_id": entry_id, "revision": 1}]})
    assert confirmed.status_code == 200 and confirmed.json()["unconfirmed_count"] == 0


@pytest.mark.asyncio
async def test_technician_view_authority_window_and_totals() -> None:
    repo = repo_with()
    repair = await repair_job(repo)
    pm = await pm_job_started(repo)
    await record(svc(repo), WORK_KIND_REPAIR, repair, ctx(U1), t(0), t(4))
    await record(svc(repo), WORK_KIND_PM, pm, ctx(U1), t(5), t(7), TIME_CLASS_OVERTIME)
    own = await svc(repo).technician_view(T1, ctx(U1), t(0), t(24))
    assert own["totals"]["regular_seconds"] == 4 * 3600 and own["totals"]["overtime_seconds"] == 2 * 3600
    assert {e.job_id for e in own["entries"]} == {repair, pm}
    clipped = await svc(repo).technician_view(T1, repair_manager(), t(2), t(6))
    assert clipped["totals"]["total_seconds"] == 3 * 3600  # 2 h of the repair + 1 h of the PM inside the window
    assert await code_of(svc(repo).technician_view(T1, ctx(U2), t(0), t(24))) == "WORK_TIME_READ_FORBIDDEN"
    response = await http("GET", f"/api/v1/work-time/assignees/{T1}?from={t(0).isoformat().replace('+', '%2B')}"
                                 f"&to={t(24).isoformat().replace('+', '%2B')}", repo, role="MAINTENANCE")
    assert response.status_code == 200, response.text
    assert set(response.json()) >= {"technician_id", "from", "to", "entries", "totals"}


@pytest.mark.asyncio
async def test_kinds_are_isolated_and_assignment_reads_are_unchanged() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(1))
    assert await repo.list_work_time_records(WORK_KIND_PM, job) == []
    from app.domain.technician_assignment import TechnicianAssignmentService

    state = (await TechnicianAssignmentService(repo, cut()).read(REPAIR, job)).state
    assert state.current.primary_technician_id == T1 and PM.key == "PM"
