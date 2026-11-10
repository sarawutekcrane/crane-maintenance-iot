"""R5 T2 — Repair substates กำลังซ่อม / รออะไหล่ (RM-2..RM-5, RM-12): recorded
periods under an OPEN Repair with effective and recorded times, no new canonical
status, overlap refusal, corrections, replay and freeze rules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.domain.material_request_service import MaterialRequestService
from app.domain.repair import RepairStatus
from app.domain.work_time import SUBSTATE_AWAITING_PARTS, SUBSTATE_REPAIRING, WORK_KIND_REPAIR
from tests.test_r5_work_time_api import BASE, U1, U3, record, repair_job, repair_manager, rid, svc, t
from tests.test_technician_assignment_batch_r2f_h1 import code_of, ctx, cut, http, repair_service, repo_with


async def opened_repair(repo) -> str:
    job = await repair_job(repo)
    repo._repairs[job] = repo._repairs[job].model_copy(update={"opened_at": BASE - timedelta(days=1)})
    return job


def sub_body(substate, start, end=None, close_ongoing=False, material_request_id=None) -> dict:
    return {"substate": substate, "started_at": start.isoformat(), "ended_at": end.isoformat() if end else None,
            "material_request_id": material_request_id, "close_ongoing": close_ongoing}


async def set_substate(repo, job, context, substate, start, end=None, *, close_ongoing=False, request_id=None,
                       material_request_id=None):
    return await svc(repo).record_substate(
        job, context, body=sub_body(substate, start, end, close_ongoing, material_request_id), substate=substate,
        started_at=start, ended_at=end, material_request_id=material_request_id, close_ongoing=close_ongoing,
        request_id=request_id or rid())


async def revise(repo, job, period_id, context, revision, *, action="CORRECT", reason="แก้ช่วงเวลา", substate=None,
                 start=None, end=None, request_id=None):
    payload = {"action": action, "expected_revision": revision, "reason": reason, "substate": substate,
               "started_at": start.isoformat() if start else None, "ended_at": end.isoformat() if end else None}
    return await svc(repo).revise_substate(job, period_id, context, body=payload, action=action,
                                           expected_revision=revision, reason=reason, substate=substate,
                                           started_at=start, ended_at=end, request_id=request_id or rid())


async def substates(repo, job):
    return await svc(repo).substate_view(await svc(repo).locate_job(WORK_KIND_REPAIR, job))


@pytest.mark.asyncio
async def test_repairing_then_awaiting_parts_in_one_request_keeps_the_canonical_status_open() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    await set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(0))
    records, _ = await set_substate(repo, job, ctx(U1), SUBSTATE_AWAITING_PARTS, t(24), close_ongoing=True)
    assert [(r.substate, r.record_kind, r.ended_at) for r in records] == [
        (SUBSTATE_REPAIRING, "CORRECTION", t(24)), (SUBSTATE_AWAITING_PARTS, "ENTRY", None)]
    state = await substates(repo, job)
    assert [p.substate for p in state["periods"]] == [SUBSTATE_REPAIRING, SUBSTATE_AWAITING_PARTS]
    assert state["durations"]["repairing_seconds"] == 24 * 3600
    assert state["durations"]["awaiting_parts_seconds"] >= 0
    assert (await repo.get_repair(job)).repair.status == RepairStatus.OPEN
    assert {m.value for m in RepairStatus} == {"OPEN", "CLOSED", "CANCELLED"}


@pytest.mark.asyncio
async def test_effective_and_recorded_times_are_distinct_and_retrospective_entry_is_allowed() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    records, _ = await set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(0), t(5))
    assert records[0].started_at == t(0) and records[0].recorded_at > t(5)


@pytest.mark.asyncio
async def test_conflicting_periods_are_refused_with_zero_writes() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    await set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(0), t(10))
    assert await code_of(set_substate(repo, job, ctx(U1), SUBSTATE_AWAITING_PARTS, t(5), t(12))) == \
        "REPAIR_SUBSTATE_CONFLICT"
    await set_substate(repo, job, ctx(U1), SUBSTATE_AWAITING_PARTS, t(12))  # ongoing
    assert await code_of(set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(20))) == "REPAIR_SUBSTATE_CONFLICT"
    assert len(await repo.list_repair_substates(job)) == 2


@pytest.mark.asyncio
async def test_invalid_intervals_are_refused() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    before_open = BASE - timedelta(days=2)
    future = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
    for start, end in [(before_open, None), (future, None), (t(5), t(4))]:
        assert await code_of(set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, start, end)) == \
            "REPAIR_SUBSTATE_INVALID_INTERVAL"
    assert await code_of(set_substate(repo, job, ctx(U1), "WAITING", t(1))) == "REPAIR_SUBSTATE_INVALID"


@pytest.mark.asyncio
async def test_corrections_and_voids_are_new_revisions_with_a_reason_and_the_current_revision() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    records, _ = await set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(0), t(10))
    pid = records[0].period_id
    assert await code_of(revise(repo, job, pid, ctx(U1), 1, reason=" ", start=t(1), end=t(10))) == \
        "WORK_TIME_REASON_REQUIRED"
    corrected, _ = await revise(repo, job, pid, ctx(U1), 1, start=t(1), end=t(10))
    assert (corrected[0].revision, corrected[0].started_at) == (2, t(1))
    assert await code_of(revise(repo, job, pid, ctx(U1), 1, start=t(2), end=t(10))) == "WORK_TIME_REVISION_STALE"
    voided, _ = await revise(repo, job, pid, ctx(U1), 2, action="VOID")
    assert voided[0].record_kind == "VOID"
    state = await substates(repo, job)
    assert state["durations"]["repairing_seconds"] == 0 and len(state["history"]) == 3


@pytest.mark.asyncio
async def test_replay_and_request_id_reuse() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    request_id = rid()
    first, replayed = await set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(0), t(2), request_id=request_id)
    again, replayed2 = await set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(0), t(2), request_id=request_id)
    assert (replayed, replayed2, again[0].period_id) == (False, True, first[0].period_id)
    assert await code_of(set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(3), t(4), request_id=request_id)) == \
        "WORK_TIME_REQUEST_CONFLICT"
    assert len(await repo.list_repair_substates(job)) == 1


@pytest.mark.asyncio
async def test_authority_and_freeze_rules() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    with pytest.raises(HTTPException) as denied:
        await set_substate(repo, job, ctx(U3), SUBSTATE_REPAIRING, t(0))  # not on the team, no capability
    assert denied.value.status_code == 403
    repo._repairs[job] = repo._repairs[job].model_copy(update={"completion_submitted_at": t(30)})
    assert await code_of(set_substate(repo, job, ctx(U1), SUBSTATE_REPAIRING, t(0), t(1))) == \
        "REPAIR_SUBSTATE_WINDOW_CLOSED"
    await set_substate(repo, job, repair_manager(), SUBSTATE_REPAIRING, t(0), t(1))  # a manager still may
    repo._repairs[job] = repo._repairs[job].model_copy(update={"completion_submitted_at": None})
    await repair_service(repo).close_repair(job, closed_by="USR-SYN-MANAGER", close_note=None,
                                            context=repair_manager())
    assert await code_of(set_substate(repo, job, repair_manager(), SUBSTATE_REPAIRING, t(2), t(3))) == \
        "REPAIR_SUBSTATE_WINDOW_CLOSED"


@pytest.mark.asyncio
async def test_awaiting_parts_is_separate_from_the_store_flag_and_creates_no_labor() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    await set_substate(repo, job, ctx(U1), SUBSTATE_AWAITING_PARTS, t(0), t(48))
    assert await MaterialRequestService(repo, cut()).is_awaiting_parts(job) is False  # Store flag untouched
    assert (await svc(repo).job_view(WORK_KIND_REPAIR, await svc(repo).locate_job(WORK_KIND_REPAIR, job)))[
        "team"]["total_seconds"] == 0
    await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(10), t(12))  # actual work during the wait
    view = await svc(repo).job_view(WORK_KIND_REPAIR, await svc(repo).locate_job(WORK_KIND_REPAIR, job))
    assert view["team"]["total_seconds"] == 2 * 3600
    assert await code_of(set_substate(repo, job, ctx(U1), SUBSTATE_AWAITING_PARTS, t(50),
                                      material_request_id="MR-NOT-MINE")) == "REPAIR_SUBSTATE_MATERIAL_REQUEST_INVALID"


@pytest.mark.asyncio
async def test_substates_never_change_the_vehicle_status() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    vehicle_id = (await repo.get_repair(job)).repair.asset_id
    before = (await repo.get_vehicle(vehicle_id), await repo.list_vehicle_status_history(vehicle_id))
    await set_substate(repo, job, ctx(U1), SUBSTATE_AWAITING_PARTS, t(0))
    assert (await repo.get_vehicle(vehicle_id), await repo.list_vehicle_status_history(vehicle_id)) == before


@pytest.mark.asyncio
async def test_http_routes() -> None:
    repo = repo_with()
    job = await opened_repair(repo)
    posted = await http("POST", f"/api/v1/repairs/{job}/substates", repo, role="TECHNICIAN", user=U1,
                        json=sub_body(SUBSTATE_REPAIRING, t(0)))
    assert posted.status_code == 200, posted.text
    assert posted.json()["replayed"] is False and posted.json()["periods"][0]["substate"] == SUBSTATE_REPAIRING
    period_id = posted.json()["periods"][0]["period_id"]
    revised = await http("POST", f"/api/v1/repairs/{job}/substates/{period_id}/revisions", repo, role="TECHNICIAN",
                         user=U1, json={"action": "CORRECT", "expected_revision": 1, "reason": "ปิดช่วง",
                                        "started_at": t(0).isoformat(), "ended_at": t(3).isoformat()})
    assert revised.status_code == 200 and revised.json()["durations"]["repairing_seconds"] == 3 * 3600
    read = await http("GET", f"/api/v1/repairs/{job}/substates", repo, role="MAINTENANCE")
    assert read.status_code == 200 and len(read.json()["history"]) == 2
    no_id = await http("POST", f"/api/v1/repairs/{job}/substates", repo, role="TECHNICIAN", user=U1,
                       json=sub_body(SUBSTATE_REPAIRING, t(5)), request_id=None)
    assert no_id.status_code == 422


@pytest.mark.asyncio
async def test_now_is_the_servers_time_even_right_after_opening_and_a_resend_replays() -> None:
    repo = repo_with()
    job = await repair_job(repo)  # opened a moment ago: a client "now" could precede it
    request_id = rid()
    payload = {"substate": SUBSTATE_REPAIRING, "started_at": None, "ended_at": None, "material_request_id": None,
               "close_ongoing": True}
    first, replayed = await svc(repo).record_substate(job, ctx(U1), body=payload, substate=SUBSTATE_REPAIRING,
                                                      started_at=None, ended_at=None, material_request_id=None,
                                                      close_ongoing=True, request_id=request_id)
    again, replayed2 = await svc(repo).record_substate(job, ctx(U1), body=payload, substate=SUBSTATE_REPAIRING,
                                                       started_at=None, ended_at=None, material_request_id=None,
                                                       close_ongoing=True, request_id=request_id)
    opened = (await repo.get_repair(job)).repair.opened_at.replace(microsecond=0)
    assert first[0].started_at >= opened and first[0].started_at.microsecond == 0
    assert (replayed, replayed2, again[0].started_at) == (False, True, first[0].started_at)
    assert await code_of(svc(repo).record_substate(job, ctx(U1), body={**payload, "ended_at": "x"},
                                                   substate=SUBSTATE_REPAIRING, started_at=None, ended_at=t(1),
                                                   material_request_id=None, close_ongoing=False,
                                                   request_id=rid())) == "REPAIR_SUBSTATE_INVALID_INTERVAL"
