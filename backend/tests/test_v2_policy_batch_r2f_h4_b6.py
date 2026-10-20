"""R2 Batch R2f-h4 B6 — owner policies D1 / D2 and the legacy assignment cleanup (D3).

D1: a work order that is not exactly OPEN accepts no V2 assignment change (no new
    set, no withdrawal), enforced in the backend before any write; its current
    set and history stay readable and unchanged.
D2: a manager may withdraw the WHOLE current set of an OPEN V2 job. One audited
    WITHDRAWAL row is appended (never a deletion / rewrite); the job then has no
    current set: U1 lists it as NONE, it leaves the assignees' V2 My Work, the
    previous set stays in history and a new PRIMARY can be assigned.
D3: the legacy write routes and legacy-only queues answer 410
    LEGACY_ASSIGNMENT_RETIRED with zero repository calls; a legacy inline
    assignee on create / convert is refused (422) before any read or write;
    the legacy history reads and legacy-job recording authorization are kept.

Mock repository with the B2 synthetic TEST fixtures (TEC-TEST-911 / -912 linked
to USR-TEST-911 / -912, mock batch) and the fake Google Sheets transport only.
"""
from __future__ import annotations

import copy
import uuid

import pytest

from app.domain.meter_service import MeterService
from app.domain.pm import PmWorkOrderStatus
from app.domain.repair import RepairStatus
from app.domain.repair_service import RepairService
from app.domain.technician_assignment import (
    PM,
    REPAIR,
    ROLE_WITHDRAWAL,
    STATUS_AMBIGUOUS,
    STATUS_NONE,
    STATUS_VALID,
    derive_assignment_state,
    record_id_for,
    set_digest,
)
from app.repositories.base import RepositoryWriteError
from tests.legacy_assignment_seed import seed_historical_legacy_repair
from tests.test_department_read_batch_r2c2 import Spy
from tests.test_technician_assignment_batch_r2f_h1 import (
    API,
    assign,
    body,
    code_of,
    http,
    new_pm,
    new_repair,
    ta_service,
    v2_rows,
)

TA, TB = "TEC-TEST-911", "TEC-TEST-912"
UA, UB = "USR-TEST-911", "USR-TEST-912"
REASON = "ถอนการมอบหมาย (ทดสอบ)"
KINDS = [REPAIR, PM]
PATH = {REPAIR.key: "repairs", PM.key: "pm/work-orders"}


def wbody(*expected: str, reason: str | None = None) -> dict:
    out: dict = {"expected_current": {"primary_technician_id": expected[0],
                                      "collaborator_technician_ids": list(expected[1:])}}
    if reason is not None:
        out["reason_th"] = reason
    return out


async def withdraw(repo, job_id: str, payload: dict, *, kind=REPAIR, request_id: str | None = None, **kw):
    return await ta_service(repo, **kw).withdraw(kind, job_id, payload, request_id=request_id or str(uuid.uuid4()),
                                                 user_id="dev-user")


async def new_job(repo, kind) -> str:
    return await (new_repair(repo) if kind is REPAIR else new_pm(repo))


def close_job(repo, kind, job_id: str) -> None:
    if kind is REPAIR:
        repo._repairs[job_id] = repo._repairs[job_id].model_copy(update={"status": RepairStatus.CLOSED})
    else:
        repo._pm_work_orders[job_id] = repo._pm_work_orders[job_id].model_copy(
            update={"status": PmWorkOrderStatus.CLOSED})


async def state_of(repo, kind, job_id: str):
    return (await ta_service(repo).read(kind, job_id)).state


# ---------------------------------------------------------------------------
# D1 — CLOSED jobs accept no assignment change (backend)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.key)
async def test_r2fh4b6_d1_01_closed_job_refuses_assign_and_withdraw_with_no_change(kind) -> None:
    repo = Spy()
    job_id = await new_job(repo, kind)
    await assign(repo, job_id, body(TA, TB), kind=kind)
    close_job(repo, kind, job_id)
    before = copy.deepcopy(v2_rows(repo, kind.key))
    assert await code_of(assign(repo, job_id, body(TB, expected=(TA, TB)), kind=kind)) == \
        "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"
    assert await code_of(withdraw(repo, job_id, wbody(TA, TB), kind=kind)) == "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"
    assert v2_rows(repo, kind.key) == before  # current set and history byte-identical
    state = await state_of(repo, kind, job_id)  # history stays readable
    assert state.status == STATUS_VALID and state.current.primary_technician_id == TA and len(state.sets) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.key)
async def test_r2fh4b6_d1_02_closed_never_assigned_job_refuses_a_first_assignment(kind) -> None:
    repo = Spy()
    job_id = await new_job(repo, kind)
    close_job(repo, kind, job_id)
    assert await code_of(assign(repo, job_id, body(TA), kind=kind)) == "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"
    assert v2_rows(repo, kind.key) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.key)
async def test_r2fh4b6_d1_03_http_bypassing_the_ui_is_refused_and_reads_still_work(kind) -> None:
    repo = Spy()
    job_id = await new_job(repo, kind)
    await assign(repo, job_id, body(TA), kind=kind)
    close_job(repo, kind, job_id)
    before = copy.deepcopy(v2_rows(repo, kind.key))
    base = f"{API}/{PATH[kind.key]}/{job_id}"
    for path, payload in ((f"{base}/technician-assignments", body(TB, expected=(TA,))),
                          (f"{base}/technician-assignment-withdrawals", wbody(TA))):
        response = await http("POST", path, repo, role="MAINTENANCE", json=payload, v2=True)
        assert response.status_code == 409, response.text
        error = response.json()["error"]
        assert (error["code"], error["details"]) == ("TECHNICIAN_ASSIGNMENT_JOB_CLOSED", {"status": "CLOSED"})
        denied = await http("POST", path, repo, role="TECHNICIAN", json=payload, v2=True)
        assert denied.status_code == 403  # authorization stays first; nothing about the job is revealed
    assert v2_rows(repo, kind.key) == before
    read = await http("GET", f"{base}/technician-assignments", repo, v2=True)
    assert read.status_code == 200 and read.json()["current"]["primary_technician_id"] == TA


@pytest.mark.asyncio
async def test_r2fh4b6_d1_04_a_request_applied_while_open_still_replays_after_close() -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    rid = str(uuid.uuid4())
    await assign(repo, job_id, body(TA), request_id=rid)
    close_job(repo, REPAIR, job_id)
    count = len(v2_rows(repo))
    outcome = await assign(repo, job_id, body(TA), request_id=rid)
    assert outcome.replayed and len(v2_rows(repo)) == count  # idempotent; still no change


@pytest.mark.asyncio
async def test_r2fh4b6_d1_05_closing_through_the_real_close_flow_also_blocks_assignment() -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(TA))
    await RepairService(repo, MeterService(repo)).close_repair(job_id, "dev-user", None)
    assert await code_of(assign(repo, job_id, body(TB, expected=(TA,)))) == "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"


# ---------------------------------------------------------------------------
# D2 — whole-set withdrawal on OPEN jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.key)
async def test_r2fh4b6_d2_01_withdrawal_appends_one_audited_event_and_keeps_history(kind) -> None:
    repo = Spy()
    job_id = await new_job(repo, kind)
    await assign(repo, job_id, body(TA, TB, reason="ทีมแรก"), kind=kind)
    before = copy.deepcopy(v2_rows(repo, kind.key))
    rid = str(uuid.uuid4())
    outcome = await withdraw(repo, job_id, wbody(TA, TB, reason=REASON), kind=kind, request_id=rid)
    rows = v2_rows(repo, kind.key)
    assert outcome.changed and len(rows) == len(before) + 1
    assert rows[: len(before)] == before  # nothing ended, deleted or rewritten
    row = rows[-1]
    digest = set_digest(kind, job_id, rid, [(ROLE_WITHDRAWAL, "")])
    assert row[kind.record_id_column] == record_id_for(kind, digest, 1, 1) == outcome.record_ids[0]
    assert (row["assignment_role"], row["assignee_type"], row["assignee_id"], row["user_id"], row["ended_at"],
            row["active_status"]) == (ROLE_WITHDRAWAL, "TECHNICIAN", "", "", "", "")
    assert (row["assigned_by_user_id"], row["request_id"], row["reason_th"]) == ("dev-user", rid, REASON)
    assert (row["is_test_data"], row["test_batch_id"]) == (before[0]["is_test_data"], before[0]["test_batch_id"])
    state = await state_of(repo, kind, job_id)
    assert (state.status, state.current) == (STATUS_NONE, None)
    assert [s.primary_technician_id for s in state.sets] == [TA]  # the previous set stays readable
    [w] = state.withdrawals
    assert (w.withdrawal_id, w.withdrawn_by_user_id, w.reason_th) == (rid, "dev-user", REASON)
    assert w.withdrawn_at > state.sets[0].assigned_at


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.key)
async def test_r2fh4b6_d2_02_u1_my_work_readback_and_reassignment_over_http(kind) -> None:
    repo = Spy()
    job_id = await new_job(repo, kind)
    base = f"{API}/{PATH[kind.key]}"
    queue = f"{base}/v2-waiting-assignment"

    async def waiting() -> dict:
        response = await http("GET", queue, repo, role="MAINTENANCE", v2=True)
        assert response.status_code == 200, response.text
        return {i["job_id"]: i for i in response.json()["items"]}

    async def my_work(user: str) -> dict:
        response = await http("GET", f"{API}/my-work", repo, role="TECHNICIAN", user=user, v2=True)
        assert response.status_code == 200 and response.json()["resolution"] == "RESOLVED", response.text
        return {i["job_id"]: i["assignment_role"] for i in response.json()["items"] if i["work_type"] == kind.key}

    assigned = await http("POST", f"{base}/{job_id}/technician-assignments", repo, json=body(TA, TB), v2=True)
    assert assigned.status_code == 200, assigned.text
    assert job_id not in await waiting()
    assert (await my_work(UA)).get(job_id) == "PRIMARY" and (await my_work(UB)).get(job_id) == "COLLABORATOR"

    response = await http("POST", f"{base}/{job_id}/technician-assignment-withdrawals", repo,
                          json=wbody(TA, TB, reason=REASON), v2=True)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert (payload["changed"], payload["withdrawn"], len(payload["record_ids"])) == (True, True, 1)

    item = (await waiting())[job_id]  # back in U1 as NONE — never AMBIGUOUS / DATA_INVALID
    assert (item["assignment_status"], item["issues"]) == ("NONE", {})
    assert job_id not in await my_work(UA) and job_id not in await my_work(UB)
    read = (await http("GET", f"{base}/{job_id}/technician-assignments", repo, v2=True)).json()
    assert (read["status"], read["current"]) == ("NONE", None)
    assert [s["primary_technician_id"] for s in read["sets"]] == [TA]
    assert [(w["withdrawn_by_user_id"], w["reason_th"]) for w in read["withdrawals"]] == [("dev-user", REASON)]

    again = await http("POST", f"{base}/{job_id}/technician-assignments", repo, json=body(TB), v2=True)
    assert again.status_code == 200, again.text  # a new PRIMARY after the withdrawal (expected_current null)
    assert job_id not in await waiting()
    assert (await my_work(UB)).get(job_id) == "PRIMARY" and job_id not in await my_work(UA)
    read = (await http("GET", f"{base}/{job_id}/technician-assignments", repo, v2=True)).json()
    assert read["status"] == "VALID" and read["current"]["primary_technician_id"] == TB
    assert [s["primary_technician_id"] for s in read["sets"]] == [TA, TB] and len(read["withdrawals"]) == 1


@pytest.mark.asyncio
async def test_r2fh4b6_d2_03_stale_withdrawals_and_stale_reassignment_change_nothing() -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    assert await code_of(withdraw(repo, job_id, wbody(TA))) == "TECHNICIAN_ASSIGNMENT_STALE"  # nothing to withdraw
    await assign(repo, job_id, body(TA, TB))
    count = len(v2_rows(repo))
    for expected in ((TB,), (TA,), (TA, TB, "TEC-TEST-901"), (TB, TA)):
        assert await code_of(withdraw(repo, job_id, wbody(*expected))) == "TECHNICIAN_ASSIGNMENT_STALE"
    assert len(v2_rows(repo)) == count
    await withdraw(repo, job_id, wbody(TA, TB))
    count = len(v2_rows(repo))
    assert await code_of(withdraw(repo, job_id, wbody(TA, TB))) == "TECHNICIAN_ASSIGNMENT_STALE"  # already withdrawn
    assert await code_of(assign(repo, job_id, body(TB, expected=(TA, TB)))) == "TECHNICIAN_ASSIGNMENT_STALE"
    assert len(v2_rows(repo)) == count  # never a silent overwrite


@pytest.mark.asyncio
async def test_r2fh4b6_d2_04_replay_is_idempotent_and_request_ids_are_never_reused() -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    assign_rid = str(uuid.uuid4())
    await assign(repo, job_id, body(TA), request_id=assign_rid)
    rid = str(uuid.uuid4())
    first = await withdraw(repo, job_id, wbody(TA), request_id=rid)
    count = len(v2_rows(repo))
    second = await withdraw(repo, job_id, wbody(TA), request_id=rid)
    assert second.replayed and second.record_ids == first.record_ids and len(v2_rows(repo)) == count
    assert await code_of(withdraw(repo, job_id, wbody(TA, reason="อื่น"), request_id=rid)) == "REQUEST_ID_REUSED"
    assert await code_of(withdraw(repo, job_id, wbody(TA), request_id=assign_rid)) == "REQUEST_ID_REUSED"
    assert await code_of(assign(repo, job_id, body(TB), request_id=rid)) == "REQUEST_ID_REUSED"
    assert len(v2_rows(repo)) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("written", [False, True], ids=["not-written", "written"])
async def test_r2fh4b6_d2_05_unknown_write_outcome_then_same_id_resend_is_safe(written) -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(TA))
    real_append = repo.append_work_assignment_v2_rows

    async def flaky(kind, read, rows):
        if written:
            await real_append(kind, read, rows)
        raise RepositoryWriteError("repair_assignment", "unknown", None, "lost response")

    rid = str(uuid.uuid4())
    object.__setattr__(repo, "append_work_assignment_v2_rows", flaky)
    response = await http("POST", f"{API}/repairs/{job_id}/technician-assignment-withdrawals", repo,
                          json=wbody(TA), request_id=rid, v2=True)
    assert response.status_code == 503
    assert response.json()["error"]["details"] == {"write_outcome": "unknown", "request_id": rid}
    object.__delattr__(repo, "append_work_assignment_v2_rows")
    count = len(v2_rows(repo))
    resend = await http("POST", f"{API}/repairs/{job_id}/technician-assignment-withdrawals", repo,
                        json=wbody(TA), request_id=rid, v2=True)
    assert resend.status_code == 200, resend.text
    assert bool(resend.json().get("replayed")) is written  # applied once: replayed; not applied: written now
    assert len(v2_rows(repo)) == (count if written else count + 1)
    assert sum(1 for r in v2_rows(repo) if r["assignment_role"] == ROLE_WITHDRAWAL) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER"])
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.key)
async def test_r2fh4b6_d2_06_unauthorized_withdrawal_is_denied_with_no_change(kind, role) -> None:
    repo = Spy()
    job_id = await new_job(repo, kind)
    await assign(repo, job_id, body(TA), kind=kind)
    before = copy.deepcopy(v2_rows(repo, kind.key))
    response = await http("POST", f"{API}/{PATH[kind.key]}/{job_id}/technician-assignment-withdrawals", repo,
                          role=role, json=wbody(TA), v2=True)
    if role == "MAINTENANCE_MANAGER" and kind.key == "REPAIR":
        # R3 TS-2 (Owner-approved; deliberate migration): the manager now holds
        # can_manage_repair, so a Repair withdrawal is authorized. PM stays refused.
        assert response.status_code == 200, response.text
        assert v2_rows(repo, kind.key) != before
        return
    assert response.status_code == 403
    assert v2_rows(repo, kind.key) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(("payload", "request_id", "code"), [
    (wbody(TA), None, "REQUEST_ID_REQUIRED"),
    ({"expected_current": None}, "auto", "VALIDATION_ERROR"),
    ({}, "auto", "VALIDATION_ERROR"),
    ({**wbody(TA), "primary_technician_id": TB}, "auto", "VALIDATION_ERROR"),
    (wbody(TA, reason="   "), "auto", "REASON_REQUIRED"),
])
async def test_r2fh4b6_d2_07_malformed_withdrawals_are_refused_before_any_write(payload, request_id, code) -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(TA))
    before = copy.deepcopy(v2_rows(repo))
    response = await http("POST", f"{API}/repairs/{job_id}/technician-assignment-withdrawals", repo,
                          json=payload, request_id=request_id, v2=True)
    assert response.status_code == 422 and response.json()["error"]["code"] == code, response.text
    assert v2_rows(repo) == before


@pytest.mark.asyncio
async def test_r2fh4b6_d2_08_scope_and_context_stay_authoritative() -> None:
    repo = Spy()
    job_id = await new_repair(repo)  # a TEST job of the mock batch
    await assign(repo, job_id, body(TA))
    before = copy.deepcopy(v2_rows(repo))
    assert await code_of(withdraw(repo, job_id, wbody(TA), context="REAL")) == \
        "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH"
    assert await code_of(withdraw(repo, job_id, wbody(TA), live=True)) == \
        "TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED"
    assert await code_of(withdraw(repo, job_id, wbody(TA), context=None)) == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert await code_of(withdraw(repo, job_id, wbody(TA), batch="OTHER-BATCH")) == \
        "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH"
    assert v2_rows(repo) == before


@pytest.mark.asyncio
async def test_r2fh4b6_d2_09_after_withdrawal_the_former_team_loses_member_recording_rights() -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(TA))
    action = {"action_text": "ตรวจสอบ", "attachment_ids": []}
    path = f"{API}/repairs/{job_id}/actions"
    assert (await http("POST", path, repo, role="TECHNICIAN", user=UA, json=action, v2=True)).status_code == 200
    await withdraw(repo, job_id, wbody(TA))
    assert (await http("POST", path, repo, role="TECHNICIAN", user=UA, json=action, v2=True)).status_code == 403
    assert (await http("POST", path, repo, role="MAINTENANCE", json=action, v2=True)).status_code == 200


# ---------------------------------------------------------------------------
# D2 — stored withdrawal integrity fails closed
# ---------------------------------------------------------------------------

JOB = "RPR-SYN-1"
SCOPE = {"is_test_data": "TRUE", "test_batch_id": "SYN-B"}


def _set_rows(request_id: str, at: str, primary: str = TA) -> list[dict[str, str]]:
    digest = set_digest(REPAIR, JOB, request_id, [("PRIMARY", primary)])
    return [{REPAIR.record_id_column: record_id_for(REPAIR, digest, 1, 1), "repair_id": JOB,
             "assignment_role": "PRIMARY", "assigned_at": at, "assigned_by_user_id": "u", "assignee_type": "TECHNICIAN",
             "assignee_id": primary, "request_id": request_id, "request_fingerprint": "f", "reason_th": "",
             "user_id": "", "ended_at": "", "active_status": "", **SCOPE}]


def _withdrawal_row(request_id: str, at: str, **overrides: str) -> dict[str, str]:
    digest = set_digest(REPAIR, JOB, request_id, [(ROLE_WITHDRAWAL, "")])
    row = {REPAIR.record_id_column: record_id_for(REPAIR, digest, 1, 1), "repair_id": JOB,
           "assignment_role": ROLE_WITHDRAWAL, "assigned_at": at, "assigned_by_user_id": "u",
           "assignee_type": "TECHNICIAN", "assignee_id": "", "request_id": request_id, "request_fingerprint": "f",
           "reason_th": "", "user_id": "", "ended_at": "", "active_status": "", **SCOPE}
    row.update(overrides)
    return row


T0, T1_, T2_, T3_ = (f"2026-01-0{d}T08:00:00+00:00" for d in (1, 2, 3, 4))


def _derive(rows):
    return derive_assignment_state(REPAIR, JOB, rows, SCOPE)


def test_r2fh4b6_d2_10_a_valid_withdrawal_history_derives_none_then_valid() -> None:
    withdrawn = _derive([*_set_rows("s1", T0), _withdrawal_row("w1", T1_)])
    assert (withdrawn.status, withdrawn.current, withdrawn.issues) == (STATUS_NONE, None, {})
    again = _derive([*_set_rows("s1", T0), _withdrawal_row("w1", T1_), *_set_rows("s2", T2_, TB)])
    assert again.status == STATUS_VALID and again.current.primary_technician_id == TB and len(again.withdrawals) == 1


@pytest.mark.parametrize(("rows", "issue"), [
    ([*_set_rows("s1", T0), _withdrawal_row("w1", T1_, assignee_id=TA)], "WITHDRAWAL_ASSIGNEE_NOT_BLANK"),
    ([*_set_rows("s1", T0), _withdrawal_row("w1", T1_, repair_assignment_id="RTA-" + "0" * 32 + "-1-1")],
     "WITHDRAWAL_INVALID"),
    ([*_set_rows("s1", T0), {**_withdrawal_row("w1", T1_), "repair_assignment_id":
                             record_id_for(REPAIR, set_digest(REPAIR, JOB, "w1", [(ROLE_WITHDRAWAL, "")]), 1, 2)}],
     "WITHDRAWAL_INVALID"),
    ([*_set_rows("s1", T0), _withdrawal_row("w1", T1_), {**_set_rows("w1", T1_)[0]}], "WITHDRAWAL_INVALID"),
    ([_withdrawal_row("w1", T1_)], "WITHDRAWAL_WITHOUT_CURRENT_SET"),
    ([*_set_rows("s1", T0), _withdrawal_row("w1", T1_), _withdrawal_row("w2", T2_)],
     "WITHDRAWAL_WITHOUT_CURRENT_SET"),
    ([*_set_rows("s1", T0), _withdrawal_row("w1", T1_), *_set_rows("s2", T1_, TB), *_set_rows("s3", T3_)],
     "WITHDRAWAL_ORDER_AMBIGUOUS"),
    ([*_set_rows("s1", T0), _withdrawal_row("w1", "not-a-time")], "ASSIGNED_AT_INVALID"),
])
def test_r2fh4b6_d2_11_a_damaged_or_unprovable_withdrawal_fails_closed(rows, issue) -> None:
    state = _derive(rows)
    assert issue in state.issues and state.current is None


def test_r2fh4b6_d2_12_a_withdrawal_tied_with_the_latest_set_is_ambiguous_never_guessed() -> None:
    state = _derive([*_set_rows("s1", T0), _withdrawal_row("w1", T1_), *_set_rows("s2", T1_, TB)])
    assert (state.status, state.current, state.issues) == (STATUS_AMBIGUOUS, None, {})


@pytest.mark.asyncio
async def test_r2fh4b6_d2_13_damaged_stored_withdrawal_fails_reads_u1_and_writes_closed() -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(TA))
    await withdraw(repo, job_id, wbody(TA))
    v2_rows(repo)[-1]["assignee_id"] = TB  # a tampered withdrawal row
    before = copy.deepcopy(v2_rows(repo))
    read = await http("GET", f"{API}/repairs/{job_id}/technician-assignments", repo, v2=True)
    assert (read.status_code, read.json()["error"]["code"]) == (500, "TECHNICIAN_ASSIGNMENT_DATA_INVALID")
    queue = await http("GET", f"{API}/repairs/v2-waiting-assignment", repo, role="MAINTENANCE", v2=True)
    item = {i["job_id"]: i for i in queue.json()["items"]}[job_id]  # job-attributable: DATA_INVALID, never NONE
    assert (item["assignment_status"], item["issues"]) == ("DATA_INVALID", {"WITHDRAWAL_ASSIGNEE_NOT_BLANK": 1, "WITHDRAWAL_INVALID": 1})
    assert await code_of(assign(repo, job_id, body(TB))) == "TECHNICIAN_ASSIGNMENT_DATA_INVALID"
    assert v2_rows(repo) == before


@pytest.mark.asyncio
async def test_r2fh4b6_d2_14_an_ambiguous_current_set_refuses_withdrawal_as_ambiguous_never_stale() -> None:
    repo = Spy()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(TA))
    await assign(repo, job_id, body(TB, expected=(TA,)))
    rows = v2_rows(repo)
    rows[1]["assigned_at"] = rows[0]["assigned_at"]  # the two sets now share one instant
    before = copy.deepcopy(v2_rows(repo))
    for expected in ((TA,), (TB,)):  # whichever set the caller believes is current
        assert await code_of(withdraw(repo, job_id, wbody(*expected))) == "TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS"
    response = await http("POST", f"{API}/repairs/{job_id}/technician-assignment-withdrawals", repo,
                          json=wbody(TB), v2=True)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS")
    assert v2_rows(repo) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.key)
async def test_r2fh4b6_d2_15_each_withdrawal_route_requires_its_own_kind_capability(kind, monkeypatch) -> None:
    """Test-only synthetic roles (never added to the application) separate the
    two capabilities, which every shipped role grants together or not at all."""
    from app.domain import authz

    monkeypatch.setitem(authz.ROLE_CAPABILITIES, "SYN_REPAIR_ONLY", frozenset({authz.CAN_VIEW, authz.CAN_MANAGE_REPAIR}))
    monkeypatch.setitem(authz.ROLE_CAPABILITIES, "SYN_PM_ONLY", frozenset({authz.CAN_VIEW, authz.CAN_MANAGE_PM}))
    own, other = ("SYN_REPAIR_ONLY", "SYN_PM_ONLY") if kind is REPAIR else ("SYN_PM_ONLY", "SYN_REPAIR_ONLY")
    repo = Spy()
    job_id = await new_job(repo, kind)
    await assign(repo, job_id, body(TA), kind=kind)
    path = f"{API}/{PATH[kind.key]}/{job_id}/technician-assignment-withdrawals"
    before = copy.deepcopy(v2_rows(repo, kind.key))
    denied = await http("POST", path, repo, role=other, json=wbody(TA), v2=True)
    assert denied.status_code == 403 and v2_rows(repo, kind.key) == before
    allowed = await http("POST", path, repo, role=own, json=wbody(TA), v2=True)
    assert allowed.status_code == 200 and allowed.json()["withdrawn"] is True, allowed.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.key)
async def test_r2fh4b6_d1_06_a_withdrawal_applied_while_open_still_replays_after_close(kind) -> None:
    repo = Spy()
    job_id = await new_job(repo, kind)
    await assign(repo, job_id, body(TA), kind=kind)
    rid = str(uuid.uuid4())
    first = await withdraw(repo, job_id, wbody(TA), kind=kind, request_id=rid)
    close_job(repo, kind, job_id)
    count = len(v2_rows(repo, kind.key))
    again = await withdraw(repo, job_id, wbody(TA), kind=kind, request_id=rid)
    assert again.replayed and again.record_ids == first.record_ids and len(v2_rows(repo, kind.key)) == count
    # a NEW request on the closed job is refused (D1)
    assert await code_of(withdraw(repo, job_id, wbody(TA), kind=kind)) == "TECHNICIAN_ASSIGNMENT_JOB_CLOSED"


# ---------------------------------------------------------------------------
# D3 — legacy cleanup
# ---------------------------------------------------------------------------

RETIRED = [
    ("POST", "/repairs/RPR-0001/assign", {"primary_technician": "u-legacy", "collaborators": []}),
    ("POST", "/pm/work-orders/PMWO-0001/assign", {"primary_technician": "u-legacy", "collaborators": []}),
    ("GET", "/repairs/my-work", None),
    ("GET", "/pm/work-orders/my-work", None),
    ("GET", "/repairs/waiting-assignment", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("v2", [False, True], ids=["leftover-off", "leftover-on"])
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "TECHNICIAN"])
@pytest.mark.parametrize(("method", "path", "payload"), RETIRED, ids=[f"{m} {p}" for m, p, _ in RETIRED])
async def test_r2fh4b6_d3_01_retired_legacy_routes_answer_410_with_zero_repository_calls(method, path, payload,
                                                                                        role, v2) -> None:
    repo = Spy()
    response = await http(method, f"{API}{path}", repo, role=role, user="u-legacy", json=payload, v2=v2)
    assert response.status_code == 410, response.text
    assert response.json()["error"]["code"] == "LEGACY_ASSIGNMENT_RETIRED"
    assert repo.calls == []  # nothing read, nothing written


@pytest.mark.asyncio
@pytest.mark.parametrize("v2", [False, True], ids=["leftover-off", "leftover-on"])
@pytest.mark.parametrize("inline", [{"primary_technician": "u-legacy"}, {"collaborators": ["u-legacy"]}])
async def test_r2fh4b6_d3_02_a_legacy_inline_assignee_on_create_is_refused_before_any_write(inline, v2) -> None:
    repo = Spy()
    repairs_before = dict(repo._repairs)
    response = await http("POST", f"{API}/repairs", repo, role="MAINTENANCE", v2=v2, json={
        "asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL", "symptom": "x", **inline})
    assert response.status_code == 422 and response.json()["error"]["code"] == "LEGACY_ASSIGNMENT_RETIRED"
    assert repo._repairs == repairs_before
    assert [c for c in repo.calls if c.startswith(("create", "append", "assign", "capture"))] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("v2", [False, True], ids=["leftover-off", "leftover-on"])
async def test_r2fh4b6_d3_03_creation_without_an_inline_assignee_is_always_v2(v2) -> None:
    # B6 Rev2 (deliberate test migration, owner final decision: V2 only): a leftover former OFF value no longer
    # creates a LEGACY job.
    repo = Spy()
    response = await http("POST", f"{API}/repairs", repo, role="MAINTENANCE", v2=v2, json={
        "asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL", "symptom": "x"})
    assert response.status_code == 200, response.text
    repair = response.json()["repair"]
    assert repair["assignment_model"] == "TECHNICIAN_V2"
    assert (repair["primary_technician"], repair["collaborators"]) == (None, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("v2", [False, True], ids=["leftover-off", "leftover-on"])
async def test_r2fh4b6_d3_04_a_legacy_inline_assignee_on_conversion_is_refused_and_nothing_converts(v2) -> None:
    repo = Spy()
    reported = await http("POST", f"{API}/repair-requests", repo, role="DRIVER", user="d-1",
                          json={"vehicle_id": "VEH-1046", "symptom_th": "เสียงดัง"}, v2=v2)
    request_id = reported.json()["request"]["repair_request_id"]
    repairs_before = dict(repo._repairs)
    response = await http("POST", f"{API}/repair-requests/{request_id}/convert", repo, role="MAINTENANCE",
                          json={"primary_technician": "u-legacy"}, v2=v2)
    assert response.status_code == 422 and response.json()["error"]["code"] == "LEGACY_ASSIGNMENT_RETIRED"
    assert repo._repairs == repairs_before
    pending = await http("GET", f"{API}/repair-requests/{request_id}", repo, role="MAINTENANCE", v2=v2)
    assert pending.json()["request_status"] == "PENDING"
    converted = await http("POST", f"{API}/repair-requests/{request_id}/convert", repo, role="MAINTENANCE",
                           json={}, v2=v2)
    assert converted.status_code == 200 and converted.json()["repair"]["primary_technician"] is None
    assert converted.json()["repair"]["assignment_model"] == "TECHNICIAN_V2"  # B6 Rev2: always V2


@pytest.mark.asyncio
async def test_r2fh4b6_d3_05_legacy_history_reads_and_legacy_recording_authorization_are_retained() -> None:
    repo = Spy()
    # B6 Rev2 (deliberate test migration): no route creates a LEGACY job any more — a historical one is a fixture.
    repair_id = await seed_historical_legacy_repair(repo)
    await repo.assign_repair(repair_id=repair_id, primary_technician="u-legacy", collaborators=[],
                             assigned_by="dev-user")  # a stored legacy assignment (the storage writer is retained)
    history = await http("GET", f"{API}/repairs/{repair_id}/assignment-history", repo)
    assert history.status_code == 200 and [e["user_id"] for e in history.json()] == ["u-legacy"]
    action = {"action_text": "งานเดิม", "attachment_ids": []}
    path = f"{API}/repairs/{repair_id}/actions"
    assert (await http("POST", path, repo, role="TECHNICIAN", user="u-legacy", json=action)).status_code == 200
    assert (await http("POST", path, repo, role="TECHNICIAN", user="u-other", json=action)).status_code == 403


def test_r2fh4b6_d3_06_no_legacy_assignment_write_route_remains_usable() -> None:
    from app.main import create_app

    app = create_app()
    spec = app.openapi()["paths"]
    for path in ("/api/v1/repairs/{repair_id}/assign", "/api/v1/pm/work-orders/{pm_work_order_id}/assign"):
        assert set(spec[path]) == {"post"} and "410" in spec[path]["post"]["responses"]
        assert "requestBody" not in spec[path]["post"]  # no legacy body is accepted any more
    for path in ("/api/v1/repairs/my-work", "/api/v1/pm/work-orders/my-work", "/api/v1/repairs/waiting-assignment"):
        assert "410" in spec[path]["get"]["responses"]
    for path in ("/api/v1/repairs/{repair_id}/technician-assignment-withdrawals",
                 "/api/v1/pm/work-orders/{pm_work_order_id}/technician-assignment-withdrawals"):
        assert set(spec[path]) == {"post"}
