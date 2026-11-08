"""R4 TASK-010 R3 — final authorization correction: the external Repair reads need an actor.

`GET /repairs` and `GET /repairs/{id}` previously enforced only the server's data scope.
Data scope is not user authorization. Both now use the effective request context
(`get_current_context`: in Access Management mode the capabilities are recomputed per
request) and require, BEFORE any protected work-order read:

* a genuinely trusted, authenticated actor (a non-blank user id) — else 403
  `REPAIR_READ_CONTEXT_REQUIRED` with no repository read at all;
* an existing read authority (`REPAIR_READ_CAPABILITIES`: `can_view`, the approved single
  read permission, or an existing Repair-operating capability) — else the list is 403;
* for the detail, an actor without one may read ONLY a V2 work order of the server's
  scope whose current team they belong to; every other outcome is the same 403
  (missing, Legacy, malformed, another scope, not a member), so nothing is disclosed.

No role or grant is added. `GET /repairs/open-queue` keeps its own `can_manage_repair` gate.
Synthetic Mock data only; Mock pass is not PostgreSQL proof.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.context import RequestContext
from app.domain import authz
from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.domain.meter_service import MeterService
from app.domain.repair import RepairSourceType
from app.domain.repair_service import REPAIR_READ_CAPABILITIES, RepairService
from app.domain.technician_assignment import REPAIR, TechnicianAssignmentService
from app.errors import ApiError
from tests.test_technician_assignment_batch_r2f_h1 import (
    API,
    BATCH,
    T1,
    U1,
    U2,
    assign,
    body,
    ctx,
    cut,
    http,
    new_repair,
    repo_with,
)
from tests.v2_only_support import mock_test_cutover


def service(repo) -> RepairService:
    return RepairService(repo, MeterService(repo), assignment_cutover=cut())


async def refusal(coro) -> tuple[int, str]:
    with pytest.raises(Exception) as exc:  # ApiError, or the HTTPException of require_any_capability
        await coro
    err = exc.value
    if isinstance(err, ApiError):
        return err.status_code, err.code
    return err.status_code, "HTTP_ERROR"


async def scoped(repo, flag: str, batch: str, model: str = "TECHNICIAN_V2", **update) -> str:
    repair_id = await new_repair(repo)
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(
        update={"assignment_model": model, "is_test_data": flag, "test_batch_id": batch, **update})
    return repair_id


def protected_reads(repo) -> list[str]:
    return [name for name in repo.calls if name.startswith(("get_repair", "list_repairs", "list_open_repairs",
                                                           "read_work_order", "read_work_assignment"))]


# ---------------------------------------------------------------------------
# Service boundary (a direct service read cannot bypass the gate)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [
    None,
    RequestContext(request_id="r", user_id=None),
    RequestContext(request_id="r", user_id="   ", capabilities=frozenset({authz.CAN_VIEW})),
])
async def test_a_missing_or_anonymous_actor_is_refused_before_any_read(context) -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    repo.calls.clear()
    svc = service(repo)
    assert await refusal(svc.list_repairs_for_reader(context, None, None, None, PageParams())) == (
        403, "REPAIR_READ_CONTEXT_REQUIRED")
    assert await refusal(svc.get_repair_for_reader(repair_id, context)) == (403, "REPAIR_READ_CONTEXT_REQUIRED")
    assert repo.calls == []  # not even the scope or a record was read


@pytest.mark.asyncio
async def test_an_actor_without_read_authority_cannot_list_and_reads_nothing() -> None:
    repo = repo_with()
    await new_repair(repo)
    repo.calls.clear()
    no_read = ctx("USR-SYN-NOREAD", authz.CAN_REPORT_REPAIR, authz.CAN_RECORD_INSPECTION)
    assert await refusal(service(repo).list_repairs_for_reader(no_read, None, None, None, PageParams())) == (
        403, "HTTP_ERROR")
    assert protected_reads(repo) == []


@pytest.mark.asyncio
async def test_without_read_authority_every_detail_outcome_but_own_team_is_the_same_403() -> None:
    repo = repo_with()
    mine = await new_repair(repo)
    await assign(repo, mine, body(T1))
    not_mine = await new_repair(repo)
    await assign(repo, not_mine, body("TEC-SYN-3"))
    other_scope = await scoped(repo, "TRUE", "SYN-OTHER-BATCH", symptom="SECRET")
    legacy = await scoped(repo, "", "", model="", symptom="SECRET")
    malformed = await scoped(repo, "TRUE", BATCH, model="technician_v2", symptom="SECRET")
    member = ctx(U1)  # no capability at all: only the team membership
    svc = service(repo)
    detail = await svc.get_repair_for_reader(mine, member)
    assert detail.repair.repair_id == mine
    for repair_id in (not_mine, other_scope, legacy, malformed, "RPR-DOES-NOT-EXIST"):
        assert await refusal(svc.get_repair_for_reader(repair_id, member)) == (403, "REPAIR_READ_FORBIDDEN"), repair_id
    assert await refusal(svc.get_repair_for_reader(mine, ctx(U2))) == (403, "REPAIR_READ_FORBIDDEN")
    # Membership never opens the fleet list.
    assert (await refusal(svc.list_repairs_for_reader(member, None, None, None, PageParams())))[0] == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", REPAIR_READ_CAPABILITIES)
async def test_each_existing_read_authority_reads_the_scoped_list_and_detail(capability) -> None:
    repo = repo_with()
    own = await new_repair(repo)
    other = await scoped(repo, "FALSE", "")  # REAL: never visible to the TEST server
    reader = ctx("USR-SYN-READER", capability)
    svc = service(repo)
    page = await svc.list_repairs_for_reader(reader, None, None, None, PageParams())
    assert [i.repair_id for i in page.items] == [own] and page.total_items == 1
    assert (await svc.get_repair_for_reader(own, reader)).repair.repair_id == own
    assert await refusal(svc.get_repair_for_reader(other, reader)) == (404, "REPAIR_NOT_FOUND")


def test_the_read_authorities_are_existing_capabilities_and_no_grant_changed() -> None:
    assert set(REPAIR_READ_CAPABILITIES) <= authz.ALL_CAPABILITIES
    assert set(REPAIR_READ_CAPABILITIES) == {authz.CAN_VIEW, authz.CAN_MANAGE_REPAIR, authz.CAN_CLOSE_REPAIR,
                                             authz.CAN_MANAGE_FINDING_REPAIR}
    assert authz.ROLE_CAPABILITIES["TECHNICIAN"] == frozenset(
        {authz.CAN_VIEW, authz.CAN_REPORT_REPAIR, authz.CAN_RECORD_INSPECTION})
    assert authz.ROLE_CAPABILITIES["DRIVER"] == frozenset(
        {authz.CAN_VIEW, authz.CAN_REPORT_REPAIR, authz.CAN_RECORD_INSPECTION})


# ---------------------------------------------------------------------------
# HTTP: production-style (no dev auth) anonymous request, and the unchanged open-queue gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_without_dev_auth_an_anonymous_request_gets_no_repair_data(monkeypatch) -> None:
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    repo = repo_with()
    repair_id = await new_repair(repo)
    monkeypatch.setenv("DEV_AUTH_MODE", "false")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATA_REPOSITORY", "mock")
    get_settings.cache_clear()
    reset_dependency_cache()
    try:
        app = create_app()
        app.dependency_overrides[get_repository] = lambda: repo
        repo.calls.clear()
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            for path in (f"{API}/repairs", f"{API}/repairs/{repair_id}"):
                response = await client.get(path)
                assert response.status_code == 403, response.text
                assert response.json()["error"]["code"] == "REPAIR_READ_CONTEXT_REQUIRED"
                assert "items" not in response.json() and "repair" not in response.json()
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()
    assert protected_reads(repo) == []


@pytest.mark.asyncio
async def test_http_dev_roles_keep_their_current_reads_and_the_open_queue_gate_is_unchanged() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    for role in ("MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER", "MAINTENANCE_MANAGER"):
        listed = await http("GET", f"{API}/repairs", repo, role=role, user=f"USR-SYN-{role}", request_id=None)
        assert listed.status_code == 200 and listed.json()["total_items"] == 1, role
        detail = await http("GET", f"{API}/repairs/{repair_id}", repo, role=role, user=f"USR-SYN-{role}",
                            request_id=None)
        assert detail.status_code == 200, role
    for role, expected in (("TECHNICIAN", 403), ("DRIVER", 403), ("MAINTENANCE", 200), ("MAINTENANCE_MANAGER", 200)):
        queue = await http("GET", f"{API}/repairs/open-queue", repo, role=role, user="USR-SYN-Q", request_id=None)
        assert queue.status_code == expected, role
    # An unknown dev role holds no capability: no list, and no detail of a job it is not on.
    assert (await http("GET", f"{API}/repairs", repo, role="UNKNOWN", user="USR-SYN-U",
                       request_id=None)).status_code == 403
    response = await http("GET", f"{API}/repairs/{repair_id}", repo, role="UNKNOWN", user="USR-SYN-U", request_id=None)
    assert response.status_code == 403 and response.json()["error"]["code"] == "REPAIR_READ_FORBIDDEN"


# ---------------------------------------------------------------------------
# Access Management: the effective grant applies to the very next request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_management_grant_and_revocation_of_can_view_apply_to_the_next_read(monkeypatch) -> None:
    from tests import test_access_management as am

    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "true")
    monkeypatch.setenv("DEV_AUTH_MODE", "true")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATA_REPOSITORY", "mock")
    store = am.repo()
    detail = await RepairService(store, MeterService(store), assignment_cutover=mock_test_cutover()).create_repair(
        AssetType.VEHICLE, "VEH-1046", RepairSourceType.MANUAL, None, None, "SYN", None, "USR-TEST-AM-MGR")
    repair_id = detail.repair.repair_id

    async def read(user: str):
        return (await am.http("GET", f"{API}/repairs", store, user, role="ADMIN", request_id=None),
                await am.http("GET", f"{API}/repairs/{repair_id}", store, user, role="ADMIN", request_id=None))

    # A dev role grants nothing in Access Management mode: even "ADMIN" starts without a read permission.
    listed, single = await read(am.DRV1)
    assert listed.status_code == 403 and single.status_code == 403
    assert (await am.grant(store, am.MGR, am.employee(am.DRV1), {"can_view": True})).status_code == 200
    listed, single = await read(am.DRV1)
    assert listed.status_code == 200 and listed.json()["total_items"] == 1 and single.status_code == 200
    assert (await am.grant(store, am.MGR, am.employee(am.DRV1), {"can_view": False})).status_code == 200
    listed, single = await read(am.DRV1)
    assert listed.status_code == 403 and single.status_code == 403
    assert single.json()["error"]["code"] == "REPAIR_READ_FORBIDDEN" and "VEH-1046" not in single.text

    # A current V2 team member without any read grant reads that work order only.
    await TechnicianAssignmentService(store, mock_test_cutover()).assign(
        REPAIR, repair_id, body("TEC-TEST-911"), request_id=str(uuid.uuid4()), user_id="USR-TEST-AM-MGR")
    listed, single = await read(am.TECH1)
    assert single.status_code == 200, single.text
    assert listed.status_code == 403
