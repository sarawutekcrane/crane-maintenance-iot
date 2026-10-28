"""R4 PM Workflow test support: drive a V2 PM work order through the Owner
E01 A3 lifecycle (Mock, synthetic records only).

Service level: `repo_with()` synthetic TEST personnel / technicians / accounts
(USR-SYN-n -> TEC-SYN-n) from the R2f-h1 fixtures. HTTP level: the app's own
Mock repository with synthetic rows added the same way. No vocabulary is
defined here: Performed actions / Not Performed reasons are the server-owned
FC-1 wording read from `app.domain.pm_service`."""
from __future__ import annotations

import uuid

import app.domain.pm_service as pm_service_module
from app.domain import authz
from app.domain.pm import PmItemContractDisposition as Disposition
from app.domain.technician_assignment import PM
from tests.test_technician_assignment_batch_r2f_h1 import (
    T1,
    T2,
    U1,
    U2,
    assign,
    body,
    ctx,
    new_pm,
    pm_service,
    repo_with,
    ta_service,
)

PERFORMED, NOT_PERFORMED = Disposition.PERFORMED, Disposition.NOT_PERFORMED
CHECK, CLEAN, REPLACE = "ตรวจเช็ค", "ทำความสะอาด", "เปลี่ยน / เติม"
WAIT_PARTS = "รออะไหล่"
OTHER = pm_service_module.PM_APPROVED_OTHER_REASON
# The fixtures only use wording the server already owns (FC-1); never a new value.
assert {CHECK, CLEAN, REPLACE} == pm_service_module.PM_APPROVED_PERFORMED_ACTIONS
assert WAIT_PARTS in pm_service_module.PM_APPROVED_NOT_PERFORMED_REASONS
MANAGER_ID = "USR-SYN-MANAGER"


def rid() -> str:
    return str(uuid.uuid4())


def manager(*extra: str):
    return ctx(MANAGER_ID, authz.CAN_MANAGE_PM, *extra)


def add_synthetic_tasks(repo, revision_id: str, count: int) -> list[str]:
    """Extend a Mock revision with clearly synthetic extra tasks (fixture only)."""
    tasks = repo._pm_tasks[revision_id]
    base = tasks[-1]
    added = []
    for n in range(1, count + 1):
        task_id = f"PMT-SYN-{n}"
        tasks.append(base.model_copy(update={"pm_task_id": task_id, "sequence": base.sequence + n,
                                             "description": f"งานทดสอบ {n} (synthetic)"}))
        added.append(task_id)
    return added


async def v2_job(repo, *, primary=T1, collaborators=(T2,), extra_tasks: int = 0) -> str:
    """A V2 PM work order with a current V2 set (PRIMARY T1 / U1, COLLABORATOR
    T2 / U2 by default)."""
    if extra_tasks:
        plan_id = "PMP-0001"
        revision = (await repo.get_active_pm_task_revision(plan_id)).revision
        add_synthetic_tasks(repo, revision.revision_id, extra_tasks)
    job_id = await new_pm(repo)
    if primary is not None:
        await assign(repo, job_id, body(primary, *collaborators), kind=PM)
    return job_id


async def current_set_id(repo, job_id: str) -> str:
    return (await ta_service(repo).read(PM, job_id)).state.current.set_id


async def scope_of(repo, job_id: str) -> list[str]:
    return list((await repo.get_pm_work_order(job_id)).work_order.scope_task_ids)


async def start(svc, job_id, context=None):
    return await svc.start_work_order(job_id, context or ctx(U1), request_id=rid())


async def save(svc, job_id, task, disposition=PERFORMED, context=None, **kw):
    if disposition == PERFORMED:
        kw.setdefault("performed_actions", (CHECK,))
    else:
        kw.setdefault("reason_code", WAIT_PARTS)
    return await svc.record_item_outcome(job_id, task, disposition, context or ctx(U1), **kw)


async def submit(svc, repo, job_id, context=None):
    return await svc.submit_for_review(job_id, context or ctx(U1), request_id=rid(),
                                       expected_set_id=await current_set_id(repo, job_id))


async def close(svc, job_id, context=None, note=None):
    return await svc.close_after_review(job_id, context or manager(), request_id=rid(), note=note)


async def drive_to_closed(repo, job_id, *, not_performed: tuple[str, ...] = (), svc=None):
    """START -> every in-scope item saved (Performed first) -> SUBMIT -> CLOSE."""
    svc = svc or pm_service(repo)
    await start(svc, job_id)
    tasks = await scope_of(repo, job_id)
    for task in [t for t in tasks if t not in not_performed] + [t for t in tasks if t in not_performed]:
        await save(svc, job_id, task, NOT_PERFORMED if task in not_performed else PERFORMED)
    await submit(svc, repo, job_id)
    return await close(svc, job_id)


# ---------------------------------------------------------------- HTTP (shared `client` fixture)
# The default Mock seed links two synthetic TEST technicians to synthetic TEST
# accounts (seed_data R2f-h4 B2): PRIMARY TEC-TEST-911 / USR-TEST-911 and
# COLLABORATOR TEC-TEST-912 / USR-TEST-912. The reviewer is the default dev
# user (MAINTENANCE, `can_manage_pm`).
SEED_PRIMARY_TECHNICIAN, SEED_PRIMARY_USER = "TEC-TEST-911", "USR-TEST-911"
SEED_COLLABORATOR_TECHNICIAN, SEED_COLLABORATOR_USER = "TEC-TEST-912", "USR-TEST-912"


def technician_headers(user: str = SEED_PRIMARY_USER, *, request_id: bool = True) -> dict[str, str]:
    headers = {"X-Dev-Role": "TECHNICIAN", "X-Dev-User-Id": user}
    if request_id:
        headers["X-Request-Id"] = rid()
    return headers


def reviewer_headers() -> dict[str, str]:
    return {"X-Request-Id": rid()}


async def http_assign_team(client, wo_id: str) -> str:
    """Assign the seeded V2 team (PRIMARY + COLLABORATOR); returns the set id."""
    response = await client.post(f"/api/v1/pm/work-orders/{wo_id}/technician-assignments",
                                 json={"primary_technician_id": SEED_PRIMARY_TECHNICIAN,
                                       "collaborator_technician_ids": [SEED_COLLABORATOR_TECHNICIAN],
                                       "expected_current": None},
                                 headers=reviewer_headers())
    assert response.status_code == 200, response.text
    return response.json()["current"]["assignment_set_id"]


async def http_start(client, wo_id: str) -> str:
    """Assign the team and START the work order; returns the set id."""
    set_id = await http_assign_team(client, wo_id)
    response = await client.post(f"/api/v1/pm/work-orders/{wo_id}/start", headers=technician_headers())
    assert response.status_code == 200, response.text
    return set_id


async def http_save(client, wo_id: str, task: str, disposition: str = "PERFORMED", *,
                    user: str = SEED_PRIMARY_USER, **fields):
    body = {"disposition": disposition, **fields}
    if disposition == "PERFORMED":
        body.setdefault("performed_actions", [CHECK])
    else:
        body.setdefault("reason_code", WAIT_PARTS)
    return await client.post(f"/api/v1/pm/work-orders/{wo_id}/items/{task}/outcome", json=body,
                             headers=technician_headers(user, request_id=False))


async def http_submit(client, wo_id: str, set_id: str):
    return await client.post(f"/api/v1/pm/work-orders/{wo_id}/submit", json={"expected_set_id": set_id},
                             headers=technician_headers())


async def http_close(client, wo_id: str, note: str | None = None):
    return await client.post(f"/api/v1/pm/work-orders/{wo_id}/close", json={"note": note} if note else {},
                             headers=reviewer_headers())


async def http_complete_and_close(client, wo_id: str, *, items: dict[str, dict] | None = None,
                                  note: str | None = None, set_id: str | None = None):
    """START (if `set_id` is None), save every in-scope item Performed unless
    `items` gives its fields, SUBMIT as the PRIMARY and CLOSE as the reviewer."""
    set_id = set_id or await http_start(client, wo_id)
    detail = (await client.get(f"/api/v1/pm/work-orders/{wo_id}")).json()
    items = items or {}
    tasks = detail["work_order"]["scope_task_ids"]
    done = {r["pm_task_id"] for r in detail["results"]}
    ordered = [t for t in tasks if items.get(t, {}).get("disposition", "PERFORMED") == "PERFORMED"] + \
              [t for t in tasks if items.get(t, {}).get("disposition", "PERFORMED") != "PERFORMED"]
    for task in ordered:
        if task not in done:
            fields = dict(items.get(task, {}))
            saved = await http_save(client, wo_id, task, fields.pop("disposition", "PERFORMED"), **fields)
            assert saved.status_code == 200, saved.text
    submitted = await http_submit(client, wo_id, set_id)
    assert submitted.status_code == 200, submitted.text
    return await http_close(client, wo_id, note)


__all__ = ["SEED_COLLABORATOR_USER", "SEED_PRIMARY_USER", "http_assign_team", "http_close",
           "http_complete_and_close", "http_save", "http_start", "http_submit", "reviewer_headers",
           "technician_headers", "CHECK", "CLEAN", "MANAGER_ID", "NOT_PERFORMED", "OTHER", "PERFORMED", "REPLACE", "T1", "T2", "U1", "U2",
           "WAIT_PARTS", "add_synthetic_tasks", "close", "ctx", "current_set_id", "drive_to_closed", "manager",
           "pm_service", "repo_with", "rid", "save", "scope_of", "start", "submit", "v2_job"]
