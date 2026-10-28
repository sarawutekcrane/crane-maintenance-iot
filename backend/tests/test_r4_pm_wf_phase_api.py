"""R4 PM Workflow — public API: the E01 routes end to end, no lifecycle bypass
through legacy `/results` or direct `/close`, request-id discipline, legacy
jobs unchanged, and My Work showing every non-terminal V2 job (PH-20, PH-21).
Mock, synthetic records only."""
from __future__ import annotations

import pytest

from app.domain.my_work import MyWorkService
from app.domain.technician_assignment import AssignmentCutover
from tests.pm_e01_support import (
    CHECK,
    U1,
    U2,
    WAIT_PARTS,
    current_set_id,
    repo_with,
    scope_of,
    v2_job,
)
from tests.test_technician_assignment_batch_r2f_h1 import BATCH, U3, http, new_pm

API = "/api/v1"


def wo_path(job_id: str, tail: str = "") -> str:
    return f"{API}/pm/work-orders/{job_id}{tail}"


def code(response) -> tuple[int, str]:
    payload = response.json()
    return response.status_code, (payload.get("error") or {}).get("code") or "HTTP_ERROR"


async def tech(method, path, repo, user=U1, json=None, request_id="auto"):
    return await http(method, path, repo, role="TECHNICIAN", user=user, json=json, request_id=request_id)


async def mgr(method, path, repo, json=None, request_id="auto"):
    return await http(method, path, repo, role="MAINTENANCE", user="USR-SYN-MANAGER", json=json,
                      request_id=request_id)


async def test_ph20_full_e01_flow_over_http_with_partial_close_and_outstanding() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    assert (await tech("POST", wo_path(job_id, "/start"), repo)).json()["work_order"]["status"] == "IN_PROGRESS"
    tasks = await scope_of(repo, job_id)
    saved = await tech("POST", wo_path(job_id, f"/items/{tasks[0]}/outcome"), repo,
                       json={"disposition": "PERFORMED", "performed_actions": [CHECK]}, request_id=None)
    assert saved.status_code == 200 and saved.json()["outcome"]["disposition"] == "PERFORMED"
    assert saved.json()["result"]["completed"] is True and saved.json()["replayed"] is False
    for task in tasks[1:-1]:
        await tech("POST", wo_path(job_id, f"/items/{task}/outcome"), repo, user=U2,
                   json={"disposition": "PERFORMED", "performed_actions": [CHECK]}, request_id=None)
    np = await tech("POST", wo_path(job_id, f"/items/{tasks[-1]}/outcome"), repo,
                    json={"disposition": "NOT_PERFORMED", "reason_code": WAIT_PARTS}, request_id=None)
    assert np.status_code == 200 and np.json()["result"]["completed"] is False
    outcomes = (await tech("GET", wo_path(job_id, "/outcomes"), repo, request_id=None)).json()
    assert {o["disposition"] for o in outcomes} == {"PERFORMED", "NOT_PERFORMED"} and len(outcomes) == len(tasks)
    submitted = await tech("POST", wo_path(job_id, "/submit"), repo,
                           json={"expected_set_id": await current_set_id(repo, job_id)})
    assert submitted.json()["work_order"]["status"] == "PENDING_REVIEW"
    returned = await mgr("POST", wo_path(job_id, "/return"), repo, json={"reason": "แนบรูปเพิ่ม"})
    assert returned.json()["work_order"]["status"] == "IN_PROGRESS"
    await tech("POST", wo_path(job_id, "/submit"), repo, json={"expected_set_id": await current_set_id(repo, job_id)})
    assert (await tech("GET", wo_path(job_id, "/outstanding"), repo, request_id=None)).json() == []
    closed = await mgr("POST", wo_path(job_id, "/close"), repo, json={"note": "ตรวจแล้ว"})
    assert closed.status_code == 200 and closed.json()["work_order"]["status"] == "CLOSED"
    outstanding = (await tech("GET", wo_path(job_id, "/outstanding"), repo, request_id=None)).json()
    assert [(o["pm_task_id"], o["origin_reason_code"], o["resolved"]) for o in outstanding] == [
        (tasks[-1], WAIT_PARTS, False)]
    per_asset = (await tech("GET", f"{API}/pm/outstanding?asset_type=VEHICLE&asset_id=VEH-1046", repo,
                            request_id=None)).json()
    assert [o["outstanding_id"] for o in per_asset] == [outstanding[0]["outstanding_id"]]
    history = (await tech("GET", wo_path(job_id, "/history"), repo, request_id=None)).json()
    assert [(h["action"], h["to_status"]) for h in history] == [
        ("START", "IN_PROGRESS"), ("SUBMIT", "PENDING_REVIEW"), ("RETURN", "IN_PROGRESS"),
        ("SUBMIT", "PENDING_REVIEW"), ("CLOSE", "CLOSED")]
    assert history[2]["reason"] == "แนบรูปเพิ่ม"


async def test_ph20_no_lifecycle_bypass_through_legacy_results_or_direct_close() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    task = (await scope_of(repo, job_id))[0]
    legacy_result = await mgr("POST", wo_path(job_id, "/results"), repo, json={"pm_task_id": task, "completed": True})
    assert code(legacy_result) == (409, "PM_E01_ITEM_SAVE_REQUIRED")
    assert code(await mgr("POST", wo_path(job_id, "/close"), repo, json={})) == (409, "PM_E01_INVALID_TRANSITION")
    await tech("POST", wo_path(job_id, "/start"), repo)
    assert code(await mgr("POST", wo_path(job_id, "/close"), repo, json={})) == (409, "PM_E01_INVALID_TRANSITION")
    assert code(await mgr("POST", wo_path(job_id, "/close"), repo, json={}, request_id=None)) == (
        422, "REQUEST_ID_REQUIRED")
    assert repo._pm_work_orders[job_id].status.value == "IN_PROGRESS" and repo._pm_work_results.get(job_id) in (None, [])


@pytest.mark.parametrize("tail,json", [("/start", None), ("/submit", {"expected_set_id": "S"}),
                                       ("/return", {"reason": "x"}), ("/cancel", {"reason": "x"})])
async def test_ph20_every_lifecycle_route_needs_the_clients_own_request_id(tail, json) -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    assert code(await mgr("POST", wo_path(job_id, tail), repo, json=json, request_id=None)) == (
        422, "REQUEST_ID_REQUIRED")
    assert code(await mgr("POST", wo_path(job_id, tail), repo, json=json, request_id="not-a-uuid")) == (
        422, "REQUEST_ID_REQUIRED")
    assert repo._pm_transitions.get(job_id, []) == []


async def test_ph20_actor_rules_over_http() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    assert (await tech("POST", wo_path(job_id, "/start"), repo, user=U3)).status_code == 403  # not in the set
    await tech("POST", wo_path(job_id, "/start"), repo, user=U2)  # a collaborator may start
    for task in await scope_of(repo, job_id):
        await tech("POST", wo_path(job_id, f"/items/{task}/outcome"), repo,
                   json={"disposition": "PERFORMED", "performed_actions": [CHECK]}, request_id=None)
    set_id = await current_set_id(repo, job_id)
    assert code(await tech("POST", wo_path(job_id, "/submit"), repo, user=U2, json={"expected_set_id": set_id})) == (
        403, "PM_SUBMIT_PRIMARY_ONLY")
    assert code(await mgr("POST", wo_path(job_id, "/submit"), repo, json={"expected_set_id": set_id})) == (
        403, "PM_SUBMIT_PRIMARY_ONLY")
    await tech("POST", wo_path(job_id, "/submit"), repo, json={"expected_set_id": set_id})
    assert (await tech("POST", wo_path(job_id, "/close"), repo, json={})).status_code == 403
    assert (await tech("POST", wo_path(job_id, "/return"), repo, json={"reason": "x"})).status_code == 403
    assert (await tech("POST", wo_path(job_id, "/cancel"), repo, json={"reason": "x"})).status_code == 403
    assert repo._pm_work_orders[job_id].status.value == "PENDING_REVIEW"


async def test_ph20_resolve_route_needs_can_manage_pm_and_verified_evidence() -> None:
    from tests.test_r4_pm_wf_phase_outstanding import later_pm, partial_closed
    repo = repo_with()
    _, task, item = await partial_closed(repo)
    _, result_id, evidence = await later_pm(repo, task)
    body = {"later_pm_work_result_id": result_id, "evidence_attachment_ids": list(evidence)}
    path = f"{API}/pm/outstanding/{item.outstanding_id}/resolve"
    assert (await tech("POST", path, repo, json=body, request_id=None)).status_code == 403
    unrelated = await mgr("POST", path, repo, json={**body, "evidence_attachment_ids": ["ATT-NONE"]})
    assert code(unrelated) == (422, "PM_RESOLUTION_EVIDENCE_INVALID")
    resolved = await mgr("POST", path, repo, json=body)
    assert resolved.status_code == 200 and resolved.json()["resolved"] is True
    assert resolved.json()["resolution"]["later_pm_work_result_id"] == result_id


async def test_ph20_historical_legacy_jobs_keep_their_original_result_and_close() -> None:
    repo = repo_with()
    legacy_id = await new_pm(repo, legacy=True)
    task = (await repo.get_active_pm_task_revision("PMP-0001")).tasks[0].pm_task_id
    repo._pm_work_orders[legacy_id] = repo._pm_work_orders[legacy_id].model_copy(update={"scope_task_ids": [task]})
    result = await mgr("POST", wo_path(legacy_id, "/results"), repo, json={"pm_task_id": task, "completed": True},
                       request_id=None)
    assert result.status_code == 200 and result.json()["results"][0]["completed"] is True
    closed = await mgr("POST", wo_path(legacy_id, "/close"), repo, json={}, request_id=None)
    assert closed.status_code == 200 and closed.json()["work_order"]["status"] == "CLOSED"
    assert code(await mgr("POST", wo_path(legacy_id, "/start"), repo)) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert repo._pm_transitions.get(legacy_id, []) == []  # no invented history for a legacy job


async def test_ph21_my_work_lists_every_non_terminal_v2_job() -> None:
    repo = repo_with()
    statuses = {}
    for target in ("OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CLOSED", "CANCELLED"):
        job_id = await v2_job(repo)
        if target != "OPEN":
            if target == "CANCELLED":
                await mgr("POST", wo_path(job_id, "/cancel"), repo, json={"reason": "ยกเลิก"})
            else:
                await tech("POST", wo_path(job_id, "/start"), repo)
                if target in ("PENDING_REVIEW", "CLOSED"):
                    for task in await scope_of(repo, job_id):
                        await tech("POST", wo_path(job_id, f"/items/{task}/outcome"), repo,
                                   json={"disposition": "PERFORMED", "performed_actions": [CHECK]}, request_id=None)
                    await tech("POST", wo_path(job_id, "/submit"), repo,
                               json={"expected_set_id": await current_set_id(repo, job_id)})
                if target == "CLOSED":
                    await mgr("POST", wo_path(job_id, "/close"), repo, json={})
        assert repo._pm_work_orders[job_id].status.value == target
        statuses[job_id] = target
    service = MyWorkService(repo, AssignmentCutover(data_context="TEST", test_batch_id=BATCH))
    listed = {item.job_id: item.status for item in (await service.my_work(U1)).items if item.work_type == "PM"}
    assert listed == {j: s for j, s in statuses.items() if s in ("OPEN", "IN_PROGRESS", "PENDING_REVIEW")}
