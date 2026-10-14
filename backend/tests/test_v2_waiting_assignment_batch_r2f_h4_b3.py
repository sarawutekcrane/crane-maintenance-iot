"""R2 Batch R2f-h4 B3 — U1 V2 waiting-assignment queues (C1 Amendment A1-§24,
owner decision O2), mock / service level. Every row is SYNTHETIC.

Governance list: R2FH4B3-NONE, -VALID, -AMB, -INV (job-attributable
DATA_INVALID), -FAIL (whole-queue fail closed), -IO (schema / read failures),
-AUTH, -CTX, -SCOPE, -ORDER, -READS, -RO, -COMPAT.
"""
from __future__ import annotations

import copy
import uuid

import pytest

from app.config import Settings
from app.repositories.base import RepositorySchemaError, RepositoryTabReadError
from tests.test_technician_assignment_batch_r2f_h1 import (
    BATCH,
    T1,
    T2,
    T3,
    U1,
    assign,
    body,
    new_pm,
    new_repair,
    repo_with,
    v2_rows,
)
from app.domain.repair import RepairStatus
from app.domain.technician_assignment import PM

API = "/api/v1"
REPAIR_Q = f"{API}/repairs/v2-waiting-assignment"
PM_Q = f"{API}/pm/work-orders/v2-waiting-assignment"
READS = ["read_work_order_v2_rows", "read_work_assignment_v2_rows", "read_technician_master_reference"]
REAL = Settings(data_repository="google_sheets", registry_data_context="REAL")


async def call(path: str, repo, *, role: str = "MAINTENANCE", settings: Settings | None = None,
               user: str | None = None):
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    if settings is not None:
        app.dependency_overrides[get_settings_dependency] = lambda: settings
    headers = {"X-Dev-Role": role}
    if user is not None:
        headers["X-Dev-User-Id"] = user
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def queue(response) -> list[tuple[str, str]]:
    assert response.status_code == 200, response.text
    return [(i["job_id"], i["assignment_status"]) for i in response.json()["items"]]


def item(response, job_id: str) -> dict:
    return next(i for i in response.json()["items"] if i["job_id"] == job_id)


def code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def set_job(repo, kind: str, job_id: str, **changes) -> None:
    store = repo._repairs if kind == "REPAIR" else repo._pm_work_orders
    store[job_id] = store[job_id].model_copy(update=changes)


# ---------------------------------------------------------------------------
# NONE / VALID / AMBIGUOUS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh4b3_none_01_new_v2_repair_and_pm_jobs_wait_with_status_none() -> None:
    repo = repo_with()
    repair_id, wo_id = await new_repair(repo), await new_pm(repo)
    repairs = await call(REPAIR_Q, repo)
    assert queue(repairs) == [(repair_id, "NONE")]
    entry = item(repairs, repair_id)
    assert set(entry) == {"work_type", "job_id", "asset_type", "asset_id", "status", "opened_at",
                          "assignment_status", "issues"}
    assert (entry["work_type"], entry["status"], entry["issues"]) == ("REPAIR", "OPEN", {})
    assert entry["asset_type"] == "VEHICLE" and entry["asset_id"] and entry["opened_at"]
    body_ = repairs.json()
    assert (body_["data_context"], body_["page"], body_["page_size"], body_["total_items"]) == ("TEST", 1, 50, 1)
    pms = await call(PM_Q, repo)
    assert queue(pms) == [(wo_id, "NONE")] and item(pms, wo_id)["work_type"] == "PM"


@pytest.mark.asyncio
async def test_r2fh4b3_valid_01_a_valid_assignment_leaves_the_queue_but_stays_everywhere_else() -> None:
    repo = repo_with()
    repair_id, other = await new_repair(repo), await new_repair(repo)
    wo_id = await new_pm(repo)
    assert {j for j, _ in queue(await call(REPAIR_Q, repo))} == {repair_id, other}
    await assign(repo, repair_id, body(T1, T2))
    await assign(repo, wo_id, body(T1), kind=PM)
    assert queue(await call(REPAIR_Q, repo)) == [(other, "NONE")]
    assert queue(await call(PM_Q, repo)) == []
    # Still in the normal list, its detail, and the assignee's V2 My Work.
    listed = await call(f"{API}/repairs", repo)
    assert repair_id in {r["repair_id"] for r in listed.json()["items"]}
    assert (await call(f"{API}/repairs/{repair_id}", repo)).json()["repair"]["assignment_model"] == "TECHNICIAN_V2"
    my_work = await call(f"{API}/my-work", repo, role="TECHNICIAN", user=U1)
    assert {(i["work_type"], i["job_id"]) for i in my_work.json()["items"]} >= {("REPAIR", repair_id), ("PM", wo_id)}


@pytest.mark.asyncio
async def test_r2fh4b3_valid_02_legacy_and_closed_jobs_never_wait_here() -> None:
    repo = repo_with()
    legacy = await new_repair(repo, enabled=False)
    closed = await new_repair(repo)
    set_job(repo, "REPAIR", closed, status=RepairStatus.CLOSED)
    assert queue(await call(REPAIR_Q, repo)) == []
    legacy_queue = await call(f"{API}/repairs/waiting-assignment", repo)  # the legacy queue is unchanged
    assert legacy in {r["repair_id"] for r in legacy_queue.json()["items"]}
    assert closed not in {r["repair_id"] for r in legacy_queue.json()["items"]}


@pytest.mark.asyncio
async def test_r2fh4b3_amb_01_an_undeterminable_current_set_is_ambiguous() -> None:
    repo = repo_with()
    job_id = await new_repair(repo)
    await assign(repo, job_id, body(T1))
    await assign(repo, job_id, body(T2, expected=(T1,)))
    rows = v2_rows(repo)
    rows[1]["assigned_at"] = rows[0]["assigned_at"]  # two latest sets share one instant (R2f-h1 tie rule)
    response = await call(REPAIR_Q, repo)
    assert queue(response) == [(job_id, "AMBIGUOUS")] and item(response, job_id)["issues"] == {}


# ---------------------------------------------------------------------------
# DATA_INVALID — job-attributable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "issue"), [
    ("lose_collaborator", "SET_INCOMPLETE"), ("swap_assignee", "SET_DIGEST_MISMATCH"),
    ("row_scope", "ROW_SCOPE_MISMATCH"), ("technician_missing", "TECHNICIAN_REFERENCE_MISSING"),
])
async def test_r2fh4b3_inv_01_job_attributable_defects_are_listed_as_data_invalid(damage, issue) -> None:
    repo = repo_with()
    job_id, healthy = await new_repair(repo), await new_repair(repo)
    await assign(repo, job_id, body(T1, T2))
    await assign(repo, healthy, body(T3))
    rows = v2_rows(repo)
    mine = [r for r in rows if r["repair_id"] == job_id]
    if damage == "lose_collaborator":
        rows.remove(next(r for r in mine if r["assignment_role"] == "COLLABORATOR"))
    elif damage == "swap_assignee":
        mine[1]["assignee_id"] = T3  # digest no longer matches (H1-01)
    elif damage == "row_scope":
        for r in mine:  # the rows now name another batch than their job (job stays in this scope)
            r["test_batch_id"] = BATCH + "-OTHER"
    elif damage == "technician_missing":
        repo._technician_master = [t for t in repo._technician_master if t.values["technician_id"] != T2]
    response = await call(REPAIR_Q, repo)
    assert response.status_code == 200, response.text
    entry = item(response, job_id)
    assert entry["assignment_status"] == "DATA_INVALID" and issue in entry["issues"], entry
    assert healthy not in {j for j, _ in queue(response)}  # a VALID job is still excluded


def doctor(repo, changes: dict[str, dict[str, str]]) -> None:
    """Rewrite cells of the job rows as READ (the stored records stay intact)."""
    original = repo.read_work_order_v2_rows

    async def doctored(kind):
        read = await original(kind)
        id_column = "repair_id" if kind == "REPAIR" else "pm_work_order_id"
        for row in read.rows:
            row.update(changes.get(row.get(id_column), {}))
        return read

    repo.read_work_order_v2_rows = doctored


def job_fail(response, issues: dict[str, int], *secrets: str) -> None:
    assert response.status_code == 500, response.text
    error = response.json()["error"]
    assert (error["code"], error["details"]) == ("TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID", {"issues": issues})
    assert "items" not in response.json()
    for secret in secrets:  # counts only: never a job or asset identity
        assert secret not in response.text, secret


async def two_kinds(repo):
    return {"REPAIR": (await new_repair(repo), REPAIR_Q), "PM": (await new_pm(repo), PM_Q)}


# ---------------------------------------------------------------------------
# B3 integrity fix — I1 status, I1b opened_at, I2 scope (A1-§24 as clarified)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", ["WAITING", "", "open", " OPEN", "OPEN ", "Closed"])
@pytest.mark.parametrize("kind", ["REPAIR", "PM"])
async def test_r2fh4b3_int_01_invalid_status_of_an_in_scope_job_fails_the_whole_queue(stored, kind) -> None:
    repo = repo_with()
    jobs = await two_kinds(repo)
    job_id, path = jobs[kind]
    doctor(repo, {job_id: {"status": stored}})
    job_fail(await call(path, repo), {"JOB_STATUS_INVALID": 1}, job_id, "VEH-")


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", ["not-a-time", "", "2026-01-05T08:00:00", "2026-13-40T00:00:00+00:00"])
@pytest.mark.parametrize("kind", ["REPAIR", "PM"])
async def test_r2fh4b3_int_02_invalid_opened_at_of_an_open_in_scope_job_fails_the_whole_queue(stored, kind) -> None:
    repo = repo_with()
    jobs = await two_kinds(repo)
    job_id, path = jobs[kind]
    doctor(repo, {job_id: {"opened_at": stored}})
    job_fail(await call(path, repo), {"JOB_OPENED_AT_INVALID": 1}, job_id, "VEH-")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["REPAIR", "PM"])
async def test_r2fh4b3_int_03_invalid_opened_at_on_a_closed_job_does_not_block(kind) -> None:
    repo = repo_with()
    jobs = await two_kinds(repo)
    closed, path = jobs[kind]
    waiting = await (new_repair(repo) if kind == "REPAIR" else new_pm(repo))
    doctor(repo, {closed: {"status": "CLOSED", "opened_at": "not-a-time"}})
    assert queue(await call(path, repo)) == [(waiting, "NONE")]


@pytest.mark.asyncio
@pytest.mark.parametrize("cells", [{"is_test_data": "maybe"}, {"is_test_data": ""}, {"is_test_data": "true"},
                                   {"is_test_data": "FALSE", "test_batch_id": "ANY-BATCH"}])
@pytest.mark.parametrize("settings", [None, REAL])
@pytest.mark.parametrize("kind", ["REPAIR", "PM"])
async def test_r2fh4b3_int_04_unprovable_job_scope_fails_the_whole_queue_in_every_context(cells, settings,
                                                                                         kind) -> None:
    repo = repo_with()
    jobs = await two_kinds(repo)
    job_id, path = jobs[kind]
    doctor(repo, {job_id: cells})
    job_fail(await call(path, repo, settings=settings), {"JOB_SCOPE_FLAG_INVALID": 1}, job_id, "VEH-")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["REPAIR", "PM"])
async def test_r2fh4b3_int_05_provably_other_scope_or_batch_jobs_are_skipped_unvalidated(kind) -> None:
    repo = repo_with()
    jobs = await two_kinds(repo)
    mine, path = jobs[kind]
    make = new_repair if kind == "REPAIR" else new_pm
    other_batch, blank_batch, real = await make(repo), await make(repo), await make(repo)
    defects = {"status": "WAITING", "opened_at": "not-a-time"}  # would fail the queue if they were in scope
    doctor(repo, {other_batch: {"test_batch_id": "SYN-OTHER-BATCH", **defects},
                  blank_batch: {"test_batch_id": "", **defects},
                  real: {"is_test_data": "FALSE", "test_batch_id": "", **defects}})
    assert queue(await call(path, repo)) == [(mine, "NONE")]  # TEST context: only this batch
    # From REAL, every TEST job (this batch included) is provably another scope; the defective REAL job fails.
    job_fail(await call(path, repo, settings=REAL), {"JOB_STATUS_INVALID": 1}, real)  # status is checked first


@pytest.mark.asyncio
async def test_r2fh4b3_int_06_counts_aggregate_and_every_success_item_is_open_with_a_valid_time() -> None:
    repo = repo_with()
    a, b, c = await new_repair(repo), await new_repair(repo), await new_repair(repo)
    doctor(repo, {a: {"status": "WAITING"}, b: {"status": "x"}, c: {"is_test_data": "?"}})
    job_fail(await call(REPAIR_Q, repo), {"JOB_SCOPE_FLAG_INVALID": 1, "JOB_STATUS_INVALID": 2}, a, b, c)
    healthy = repo_with()
    for _ in range(3):
        await new_repair(healthy)
        await new_pm(healthy)
    from datetime import datetime

    for path in (REPAIR_Q, PM_Q):
        response = await call(path, healthy)
        assert response.status_code == 200 and response.json()["items"]
        for entry in response.json()["items"]:
            assert entry["status"] == "OPEN"
            assert datetime.fromisoformat(entry["opened_at"]).tzinfo is not None


def test_r2fh4b3_int_07_response_schema_enforces_open_and_a_required_time() -> None:
    from pydantic import ValidationError

    from app.api.v1.v2_waiting_assignment_routes import V2WaitingItemResponse

    base = dict(work_type="REPAIR", job_id="J", asset_type="VEHICLE", asset_id="A", status="OPEN",
                opened_at="2026-01-05T08:00:00+00:00", assignment_status="NONE", issues={})
    V2WaitingItemResponse(**base)
    for bad in ({"status": "WAITING"}, {"status": "CLOSED"}, {"opened_at": None}):
        with pytest.raises(ValidationError):
            V2WaitingItemResponse(**{**base, **bad})


# ---------------------------------------------------------------------------
# Whole-queue fail closed (never a partial queue)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("damage", "expected"), [
    ("unknown_model", ("ASSIGNMENT_MODEL_DATA_INVALID", "ASSIGNMENT_MODEL_UNKNOWN")),
    ("orphan_row", ("TECHNICIAN_ASSIGNMENT_DATA_INVALID", "V2_ROW_JOB_MISSING")),
    ("row_on_legacy_job", ("TECHNICIAN_ASSIGNMENT_DATA_INVALID", "V2_ROW_ON_LEGACY_JOB")),
    ("tab_wide", ("TECHNICIAN_ASSIGNMENT_DATA_INVALID", "RECORD_ID_INVALID")),
    ("duplicate_row", ("TECHNICIAN_ASSIGNMENT_DATA_INVALID", "DUPLICATE_RECORD_ID")),
    ("duplicate_job", ("TECHNICIAN_ASSIGNMENT_DATA_INVALID", "JOB_ID_DUPLICATE")),
])
async def test_r2fh4b3_fail_01_unattributable_or_tab_wide_defects_fail_the_whole_queue(damage, expected) -> None:
    repo = repo_with()
    job_id, waiting = await new_repair(repo), await new_repair(repo)
    legacy = await new_repair(repo, enabled=False)
    await assign(repo, job_id, body(T1))
    rows = v2_rows(repo)
    if damage == "unknown_model":
        set_job(repo, "REPAIR", legacy, assignment_model="TECHNICIAN_V3")
    elif damage == "orphan_row":
        rows.append(dict(rows[0], repair_id="REP-NO-SUCH-JOB"))
    elif damage == "row_on_legacy_job":
        rows.append(dict(rows[0], repair_id=legacy))
    elif damage == "tab_wide":
        rows.append(dict(rows[0], repair_assignment_id="BROKEN-ID"))
    elif damage == "duplicate_row":  # record ids are tab-wide in R2f-h1: a duplicate fails the whole queue
        rows.append(dict(rows[0]))
    elif damage == "duplicate_job":
        original = repo.read_work_order_v2_rows

        async def doubled(kind):
            read = await original(kind)
            read.rows.append(dict(next(r for r in read.rows if r.get("repair_id") == waiting)))
            return read

        repo.read_work_order_v2_rows = doubled
    response = await call(REPAIR_Q, repo)
    status_code, error_code = code(response)
    assert (status_code, error_code) == (500, expected[0])
    assert expected[1] in response.json()["error"]["details"]["issues"]
    assert "items" not in response.json()  # never a partial queue


@pytest.mark.asyncio
@pytest.mark.parametrize("method", READS)
@pytest.mark.parametrize(("exc", "status_code", "suffix"), [
    (RepositorySchemaError("synthetic_tab", "MISSING_HEADERS", ("assignment_model",)), 500, "_SCHEMA_INVALID"),
    (RepositoryTabReadError("synthetic_tab", "down"), 503, "_READ_FAILED"),
])
async def test_r2fh4b3_io_01_schema_and_read_failures_fail_closed(method, exc, status_code, suffix) -> None:
    repo = repo_with()
    await new_repair(repo)

    async def broken(*_a, **_k):
        raise exc

    setattr(repo, method, broken)
    response = await call(REPAIR_Q, repo)
    assert response.status_code == status_code and response.json()["error"]["code"].endswith(suffix)
    assert "items" not in response.json()


# ---------------------------------------------------------------------------
# Authorization, context, scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "allowed"), [
    (REPAIR_Q, {"ADMIN", "MAINTENANCE"}),
    (PM_Q, {"ADMIN", "MAINTENANCE"}),
])
async def test_r2fh4b3_auth_01_capability_first_with_zero_reads(path, allowed) -> None:
    from app.domain import authz

    capability = authz.CAN_MANAGE_REPAIR if path == REPAIR_Q else authz.CAN_MANAGE_PM
    for role, caps in authz.ROLE_CAPABILITIES.items():
        repo = repo_with()
        repo.calls.clear()
        response = await call(path, repo, role=role)
        if capability in caps:
            assert response.status_code == 200, role
        else:
            assert response.status_code == 403 and repo.calls == [], role
    assert {r for r, c in authz.ROLE_CAPABILITIES.items() if capability in c} >= allowed
    repo = repo_with()
    repo.calls.clear()
    assert (await call(path, repo, role="NO_SUCH_ROLE", settings=Settings(data_repository="google_sheets"))
            ).status_code == 403 and repo.calls == []  # capability before the context check


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [Settings(data_repository="google_sheets"),
                                      Settings(data_repository="google_sheets", registry_data_context="TEST")])
@pytest.mark.parametrize("path", [REPAIR_Q, PM_Q])
async def test_r2fh4b3_ctx_01_unconfigured_is_503_with_zero_reads(settings, path) -> None:
    repo = repo_with()
    repo.calls.clear()
    assert code(await call(path, repo, settings=settings)) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert repo.calls == []


@pytest.mark.asyncio
async def test_r2fh4b3_scope_01_real_test_and_batch_isolation() -> None:
    repo = repo_with()
    mine, other_batch, real = await new_repair(repo), await new_repair(repo), await new_repair(repo)
    # Another batch's job with a job-attributable defect (digest mismatch): never listed, never validated here.
    await assign(repo, other_batch, body(T1, T2))
    set_job(repo, "REPAIR", other_batch, test_batch_id="SYN-OTHER-BATCH")
    rows = [r for r in v2_rows(repo) if r["repair_id"] == other_batch]
    for row in rows:
        row["test_batch_id"] = "SYN-OTHER-BATCH"
    rows[1]["assignee_id"] = T3
    set_job(repo, "REPAIR", real, is_test_data="FALSE", test_batch_id="")
    test_view = await call(REPAIR_Q, repo)
    assert queue(test_view) == [(mine, "NONE")] and test_view.json()["data_context"] == "TEST"
    real_view = await call(REPAIR_Q, repo, settings=REAL)
    assert queue(real_view) == [(real, "NONE")] and real_view.json()["data_context"] == "REAL"
    for query in ("scope=REAL", "data_context=REAL", "test_batch_id=SYN-OTHER-BATCH", "is_test_data=FALSE"):
        assert queue(await call(f"{REPAIR_Q}?{query}", repo)) == [(mine, "NONE")], query


# ---------------------------------------------------------------------------
# Ordering, paging, bounded reads, read only, compatibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fh4b3_order_01_newest_first_ties_by_job_id_and_paging_after_classification() -> None:
    repo = repo_with()
    ids = [await new_repair(repo) for _ in range(5)]
    assigned = ids[2]
    await assign(repo, assigned, body(T1))
    same = repo._repairs[ids[0]].opened_at
    set_job(repo, "REPAIR", ids[1], opened_at=same)  # a tie with ids[0]
    full = queue(await call(f"{REPAIR_Q}?page_size=200", repo))
    waiting = [i for i in ids if i != assigned]
    expected = sorted(waiting, key=lambda j: (repo._repairs[j].opened_at, j), reverse=True)
    assert [j for j, _ in full] == expected
    pages = [queue(await call(f"{REPAIR_Q}?page={p}&page_size=2", repo)) for p in (1, 2, 3)]
    assert [j for page in pages for j, _ in page] == expected and len(pages[2]) == 0
    second = await call(f"{REPAIR_Q}?page=2&page_size=2", repo)
    assert second.json()["total_items"] == 4 and second.json()["page"] == 2
    for bad in ("page=0", "page_size=0", "page_size=201"):
        assert (await call(f"{REPAIR_Q}?{bad}", repo)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("jobs", [0, 1, 6])
async def test_r2fh4b3_reads_01_exactly_three_reads_whatever_the_queue_size(jobs) -> None:
    repo = repo_with()
    for _ in range(jobs):
        await assign(repo, await new_repair(repo), body(T1))
        await new_repair(repo)
    repo.calls.clear()
    assert (await call(REPAIR_Q, repo)).status_code == 200
    assert repo.calls == READS


@pytest.mark.asyncio
async def test_r2fh4b3_ro_01_the_queue_writes_nothing() -> None:
    repo = repo_with()
    await assign(repo, await new_repair(repo), body(T1))
    await new_repair(repo)
    await new_pm(repo)
    before = (copy.deepcopy(repo._repairs), copy.deepcopy(repo._pm_work_orders),
              copy.deepcopy(repo._technician_assignment_rows), len(repo.registry_write_log))
    for path in (REPAIR_Q, PM_Q):
        assert (await call(path, repo)).status_code == 200
    assert (repo._repairs, repo._pm_work_orders, repo._technician_assignment_rows,
            len(repo.registry_write_log)) == before


@pytest.mark.asyncio
async def test_r2fh4b3_compat_01_static_paths_precede_detail_routes_and_nothing_else_changed() -> None:
    repo = repo_with()
    repair_id, wo_id = await new_repair(repo), await new_pm(repo)
    assert (await call(f"{API}/repairs/{repair_id}", repo)).json()["repair"]["repair_id"] == repair_id
    assert (await call(f"{API}/pm/work-orders/{wo_id}", repo)).json()["work_order"]["pm_work_order_id"] == wo_id
    assert "items" in (await call(REPAIR_Q, repo)).json() and "items" in (await call(PM_Q, repo)).json()
    from app.domain import authz
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    assert set(paths["/api/v1/repairs/v2-waiting-assignment"]) == {"get"}
    assert set(paths["/api/v1/pm/work-orders/v2-waiting-assignment"]) == {"get"}
    assert {p for p in paths if "v2-waiting" in p} == {"/api/v1/repairs/v2-waiting-assignment",
                                                       "/api/v1/pm/work-orders/v2-waiting-assignment"}
    assert not [c for c in authz.ALL_CAPABILITIES if "waiting" in c or "queue" in c]
    assert str(uuid.uuid4())  # no request id is needed for a read


@pytest.mark.asyncio
async def test_r2fh4b3_auth_02_each_queue_needs_its_own_capability_only() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.context import RequestContext
    from app.dependencies import get_current_context, get_repository, reset_dependency_cache
    from app.domain import authz
    from app.main import create_app

    for caps, repair_ok, pm_ok in (({authz.CAN_MANAGE_REPAIR}, True, False), ({authz.CAN_MANAGE_PM}, False, True),
                                   ({authz.CAN_VIEW}, False, False)):
        repo = repo_with()
        repo.calls.clear()
        reset_dependency_cache()
        app = create_app()
        app.dependency_overrides[get_repository] = lambda: repo
        app.dependency_overrides[get_current_context] = lambda: RequestContext(
            request_id=str(uuid.uuid4()), user_id="synthetic", is_dev_auth=True, capabilities=frozenset(caps))
        try:
            async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                                   base_url="http://testserver") as client:
                repair = await client.get(REPAIR_Q)
                pm = await client.get(PM_Q)
        finally:
            reset_dependency_cache()
        assert (repair.status_code == 200, pm.status_code == 200) == (repair_ok, pm_ok), caps
        if not (repair_ok or pm_ok):
            assert repo.calls == []
