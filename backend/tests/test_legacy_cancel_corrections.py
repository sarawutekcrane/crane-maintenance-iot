"""R4 TASK-010 — Legacy runtime cancellation, independent-review corrections.

DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107 (Owner: Technician V2 only, operational
history starts from scratch). The independent review found three remaining reachable Legacy
paths; each is closed at its authoritative boundary and proven here with zero writes:

A. Repair close (`RepairService.close_repair`): a Legacy work order is refused (409), an
   unknown model fails closed (500), both before any meter capture or closing write.
B. Store requests (`MaterialRequestService.create`): the PM or Repair source must be an
   existing V2 work order in the server's TEST/REAL scope; Legacy, unknown, missing or
   out-of-scope sources write no header or line.
C. Repair detail (`GET /repairs/{id}`): a Legacy work order answers exactly like a missing
   one (404) and discloses no stored user id; an unknown model fails closed (500).

Every row is synthetic (Mock, TEST batch). Mock pass is not PostgreSQL proof.
"""
from __future__ import annotations

import copy

import pytest

from app.context import RequestContext
from app.domain import authz
from app.domain.asset import AssetType
from app.domain.material_request_service import (
    MaterialRequestService,
    RequisitionLineInput,
)
from app.domain.requisition import RequisitionSourceType
from app.errors import ApiError
from tests.legacy_assignment_seed import (
    seed_legacy_pm_assignment,
    seed_legacy_repair_assignment,
)
from tests.test_technician_assignment_batch_r2f_h1 import (
    API,
    T1,
    U1,
    assign,
    body,
    cut,
    http,
    new_pm,
    new_repair,
    repair_service,
    repo_with,
)

_IGNORED_STATE = {"calls", "fail"}


def state(repo) -> dict:
    """Every Mock store (deep copy), so a refused request is proven to have written nothing at all."""
    snapshot = {}
    for name, value in vars(repo).items():
        if name in _IGNORED_STATE or not isinstance(value, (dict, list)):
            continue
        try:
            snapshot[name] = copy.deepcopy(value)
        except TypeError:  # locks and similar runtime objects are not data
            continue
    return snapshot


def manager_ctx() -> RequestContext:
    return RequestContext(request_id="t", user_id="USR-SYN-MANAGER", is_dev_auth=True,
                          capabilities=frozenset({authz.CAN_CLOSE_REPAIR, authz.CAN_MANAGE_REPAIR}))


def store_service(repo) -> MaterialRequestService:
    return MaterialRequestService(repo, cut())


async def create_store_request(repo, source: RequisitionSourceType, job_id: str):
    return await store_service(repo).create(
        source_type=source, source_work_order_id=job_id, asset_type=AssetType.VEHICLE, asset_id="VEH-1046",
        lines=[RequisitionLineInput(part_description="อะไหล่ทดสอบ (synthetic)", quantity=1, unit="ชิ้น",
                                    line_source="REPAIR_UNREGISTERED")], created_by="dev-user")


async def legacy_repair_with_history(repo) -> str:
    repair_id = await new_repair(repo, legacy=True)
    await seed_legacy_repair_assignment(repair_id, "legacy-user-a", ["legacy-user-b"], repo=repo)
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(
        update={"primary_technician": "legacy-user-a", "collaborators": ["legacy-user-b"]})
    return repair_id


def code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


# ---------------------------------------------------------------------------
# A — Repair close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a1_legacy_repair_close_is_refused_with_zero_writes_api_and_service() -> None:
    repo = repo_with()
    repair_id = await legacy_repair_with_history(repo)
    before = state(repo)
    response = await http("POST", f"{API}/repairs/{repair_id}/close", repo, json={"close_note": "ทดสอบ"})
    assert code(response) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert state(repo) == before  # no meter snapshot, status change, assignment end or any other write
    for context in (manager_ctx(), None):
        with pytest.raises(ApiError) as exc:
            await repair_service(repo).close_repair(repair_id, "USR-SYN-MANAGER", None, context=context)
        assert (exc.value.status_code, exc.value.code) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert state(repo) == before
    assert repo._repairs[repair_id].status.value == "OPEN"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", ["technician_v2", "V2", "UNKNOWN", " TECHNICIAN_V2"])
async def test_a2_unknown_repair_model_fails_closed_before_any_write(stored) -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(update={"assignment_model": stored})
    before = state(repo)
    response = await http("POST", f"{API}/repairs/{repair_id}/close", repo, json={})
    assert code(response) == (500, "ASSIGNMENT_MODEL_DATA_INVALID")
    with pytest.raises(ApiError) as exc:
        await repair_service(repo).close_repair(repair_id, "USR-SYN-MANAGER", None, context=manager_ctx())
    assert exc.value.code == "ASSIGNMENT_MODEL_DATA_INVALID"
    assert state(repo) == before


@pytest.mark.asyncio
async def test_a3_v2_repair_close_and_its_lifecycle_rules_are_unchanged() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body(T1))
    snapshots_before = len(repo._meter_snapshots)
    closed = await http("POST", f"{API}/repairs/{repair_id}/close", repo, json={"close_note": "ปิดงาน"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["repair"]["status"] == "CLOSED"
    assert len(repo._meter_snapshots) == snapshots_before + 1  # the closing capture still happens
    assert code(await http("POST", f"{API}/repairs/{repair_id}/close", repo, json={})) == (
        422, "REPAIR_ALREADY_CLOSED")
    assert (await http("POST", f"{API}/repairs/{repair_id}/close", repo, role="TECHNICIAN", user=U1,
                       json={})).status_code == 403


# ---------------------------------------------------------------------------
# B — Store request sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b1_legacy_pm_cannot_be_a_store_request_source() -> None:
    repo = repo_with()
    pm_id = await new_pm(repo, legacy=True)
    await seed_legacy_pm_assignment(pm_id, "legacy-user-a", [], repo=repo)
    before = state(repo)
    with pytest.raises(ApiError) as exc:
        await create_store_request(repo, RequisitionSourceType.PM, pm_id)
    assert (exc.value.status_code, exc.value.code) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    response = await http("POST", f"{API}/material-requests", repo, json={
        "source_type": "PM", "source_work_order_id": pm_id, "asset_type": "VEHICLE", "asset_id": "VEH-1046",
        "lines": [{"part_description": "ไส้กรอง", "quantity": 1}]})
    assert code(response) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert state(repo) == before  # no header, line, inventory or audit record


@pytest.mark.asyncio
async def test_b2_legacy_repair_cannot_be_a_store_request_source() -> None:
    repo = repo_with()
    repair_id = await legacy_repair_with_history(repo)
    before = state(repo)
    with pytest.raises(ApiError) as exc:
        await create_store_request(repo, RequisitionSourceType.REPAIR, repair_id)
    assert (exc.value.status_code, exc.value.code) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    response = await http("POST", f"{API}/material-requests", repo, role="TECHNICIAN", user="legacy-user-a", json={
        "source_type": "REPAIR", "source_work_order_id": repair_id, "asset_type": "VEHICLE", "asset_id": "VEH-1046",
        "lines": [{"part_description": "ไส้กรอง", "quantity": 1}]})
    assert code(response) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert state(repo) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["missing", "unknown_model", "invalid_scope_flag", "other_scope"])
@pytest.mark.parametrize("source", [RequisitionSourceType.PM, RequisitionSourceType.REPAIR])
async def test_b3_missing_unknown_or_unproven_sources_are_never_accepted(source, damage) -> None:
    repo = repo_with()
    job_id = await (new_pm(repo) if source == RequisitionSourceType.PM else new_repair(repo))
    store = repo._pm_work_orders if source == RequisitionSourceType.PM else repo._repairs
    expected = {"missing": (404, "PM_WORK_ORDER_NOT_FOUND" if source == RequisitionSourceType.PM
                            else "REPAIR_NOT_FOUND"),
                "unknown_model": (500, "ASSIGNMENT_MODEL_DATA_INVALID"),
                "invalid_scope_flag": (500, "TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID"),
                "other_scope": (409, "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH")}[damage]
    if damage == "missing":
        job_id = "PMWO-9999" if source == RequisitionSourceType.PM else "RPR-9999"
    elif damage == "unknown_model":
        store[job_id] = store[job_id].model_copy(update={"assignment_model": "V3"})
    elif damage == "invalid_scope_flag":
        store[job_id] = store[job_id].model_copy(update={"is_test_data": "yes"})
    else:  # a REAL (operational) job is never a source for the TEST server
        store[job_id] = store[job_id].model_copy(update={"is_test_data": "FALSE", "test_batch_id": ""})
    before = state(repo)
    with pytest.raises(ApiError) as exc:
        await create_store_request(repo, source, job_id)
    assert (exc.value.status_code, exc.value.code) == expected
    assert state(repo) == before


@pytest.mark.asyncio
async def test_b4_v2_pm_and_repair_store_requests_still_work() -> None:
    repo = repo_with()
    pm_id, repair_id = await new_pm(repo), await new_repair(repo)
    pm_request = await create_store_request(repo, RequisitionSourceType.PM, pm_id)
    repair_request = await create_store_request(repo, RequisitionSourceType.REPAIR, repair_id)
    assert pm_request.request.source_work_order_id == pm_id and len(pm_request.lines) == 1
    assert repair_request.request.source_work_order_id == repair_id and len(repair_request.lines) == 1
    response = await http("POST", f"{API}/material-requests", repo, json={
        "source_type": "REPAIR", "source_work_order_id": repair_id, "asset_type": "VEHICLE", "asset_id": "VEH-1046",
        "lines": [{"part_description": "ไส้กรอง", "quantity": 1}]})
    assert response.status_code == 200, response.text
    assert len([r for r in repo._material_requests.values() if r.source_work_order_id == repair_id]) == 2


# ---------------------------------------------------------------------------
# C — Repair detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c1_legacy_repair_detail_is_indistinguishable_from_missing_and_discloses_no_user_id() -> None:
    repo = repo_with()
    repair_id = await legacy_repair_with_history(repo)
    before = state(repo)
    legacy = await http("GET", f"{API}/repairs/{repair_id}", repo, request_id=None)
    missing = await http("GET", f"{API}/repairs/RPR-9999", repo, request_id=None)
    assert code(legacy) == code(missing) == (404, "REPAIR_NOT_FOUND")
    assert "legacy-user" not in legacy.text
    assert set(legacy.json()["error"]) == set(missing.json()["error"])
    assert state(repo) == before


@pytest.mark.asyncio
async def test_c2_unknown_repair_model_detail_fails_closed() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(update={"assignment_model": "LEGACY"})
    response = await http("GET", f"{API}/repairs/{repair_id}", repo, request_id=None)
    assert code(response) == (500, "ASSIGNMENT_MODEL_DATA_INVALID")


@pytest.mark.asyncio
async def test_c3_v2_repair_detail_remains_usable_and_internal_reads_are_unchanged() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body(T1))
    response = await http("GET", f"{API}/repairs/{repair_id}", repo, role="TECHNICIAN", user=U1, request_id=None)
    assert response.status_code == 200, response.text
    assert response.json()["repair"]["repair_id"] == repair_id
    assert response.json()["repair"]["assignment_model"] == "TECHNICIAN_V2"
    # The internal service read stays available to V2 operations (it is not the external boundary).
    legacy_id = await new_repair(repo, legacy=True)
    assert (await repair_service(repo).get_repair(legacy_id)).repair.repair_id == legacy_id


@pytest.mark.asyncio
async def test_c4_the_legacy_assigned_to_list_filter_is_retired_and_reads_nothing() -> None:
    """`GET /repairs?assigned_to=` derived "my work" from the Legacy assignee fields only."""
    repo = repo_with()
    await legacy_repair_with_history(repo)
    repo.calls.clear()
    response = await http("GET", f"{API}/repairs?assigned_to=legacy-user-a", repo, request_id=None)
    assert code(response) == (410, "LEGACY_ASSIGNMENT_RETIRED")
    assert "legacy-user-a" not in response.text.replace("assigned_to=", "")
    assert not [name for name in repo.calls if name.startswith("list_repairs")]
    plain = await http("GET", f"{API}/repairs", repo, request_id=None)
    assert plain.status_code == 200  # the general list itself is unchanged
