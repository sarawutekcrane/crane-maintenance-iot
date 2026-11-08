"""Final Cross-Phase Integration Fix — F1: PM assignment authority.

F1 made PM recording authorization follow the assignment history, never the
denormalized `PmWorkOrder.primary_technician`/`.collaborators` display fields,
mirroring Repair (REV06.1 CONSISTENCY-2).

DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107 (Owner override): the Legacy
assignment runtime and `POST /pm/work-orders/{id}/results` are cancelled. The
same rules are proven on Technician V2 work orders — authority is membership of
the CURRENT V2 set only, exercised on the E01 item route while IN_PROGRESS —
and a historical Legacy work order is proven to authorize nobody.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.context import RequestContext
from app.domain.asset import AssetType
from app.domain.authz import CAN_MANAGE_PM
from app.domain.meter_service import MeterService
from app.domain.pm_service import PmService
from app.errors import ApiError
from app.repositories.mock import MockRepository
from tests.legacy_assignment_seed import (
    app_repository,
    mark_historical_legacy,
    seed_legacy_pm_assignment,
)
from tests.pm_e01_support import http_start
from tests.v2_http_assignment import (
    COLLABORATOR_USER,
    PRIMARY_USER,
    assign_v2,
    save_pm_item,
    start_pm,
)
from tests.v2_only_support import assigned_plan_id, mock_test_cutover


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


async def _make_pm_service() -> tuple[PmService, MockRepository]:
    repo = MockRepository()
    return PmService(repo, MeterService(repo), assignment_cutover=mock_test_cutover()), repo


async def _open_work_order(service: PmService, vehicle_id: str = "VEH-1046") -> str:
    plan_id = await assigned_plan_id(service._repository, vehicle_id)
    detail = await service.open_work_order(
        asset_type=AssetType.VEHICLE,
        asset_id=vehicle_id,
        pm_plan_id=plan_id,
        due_reason=None,
        opened_by="user-maintenance",
        note=None,
    )
    # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration, owner final decision: V2 only): every created job is
    # a V2 job, so the LEGACY job these legacy-authority tests need is the explicit historical fixture.
    mark_historical_legacy("pm/work-orders", detail.work_order.pm_work_order_id, repo=service._repository)
    return detail.work_order.pm_work_order_id


async def _open_work_order_via_api(client: AsyncClient, vehicle_id: str = "VEH-1046") -> tuple[str, str]:
    plans = await client.get(
        "/api/v1/pm/plans/status",
        params={"asset_type": "VEHICLE", "asset_id": vehicle_id},
        headers=_as("MAINTENANCE"),
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    revision = await client.get(
        f"/api/v1/pm/plans/{plan_id}/active-revision", headers=_as("MAINTENANCE")
    )
    task_id = revision.json()["tasks"][0]["pm_task_id"]
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "pm_plan_id": plan_id},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
    return response.json()["work_order"]["pm_work_order_id"], task_id


# ---------------------------------------------------------------------------
# 1-2 — the current PRIMARY and COLLABORATOR may record an item.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_primary_may_submit_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER)
    await start_pm(client, work_order_id)

    response = await save_pm_item(client, work_order_id, task_id, PRIMARY_USER)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_active_collaborator_may_submit_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER, [COLLABORATOR_USER])
    await start_pm(client, work_order_id)

    response = await save_pm_item(client, work_order_id, task_id, COLLABORATOR_USER)
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# 3-4 — members of a replaced set are denied.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ended_primary_cannot_submit_task_result_new_primary_can(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER)
    # The team changes only while the work order is OPEN; the new PRIMARY then starts it.
    await assign_v2(client, "pm/work-orders", work_order_id, COLLABORATOR_USER)
    await start_pm(client, work_order_id, COLLABORATOR_USER)

    denied = await save_pm_item(client, work_order_id, task_id, PRIMARY_USER)
    assert denied.status_code == 403
    allowed = await save_pm_item(client, work_order_id, task_id, COLLABORATOR_USER)
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_ended_collaborator_cannot_submit_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER, [COLLABORATOR_USER])
    # A new set without the collaborator (written while OPEN): they are no longer a member.
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER)
    await start_pm(client, work_order_id)

    denied = await save_pm_item(client, work_order_id, task_id, COLLABORATOR_USER)
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# 5 — an unrelated actor is denied.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_technician_cannot_submit_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER)
    await start_pm(client, work_order_id)

    for user in ("unrelated-tech", COLLABORATOR_USER, "TEC-TEST-911"):  # a technician id is not an account
        denied = await save_pm_item(client, work_order_id, task_id, user)
        assert denied.status_code == 403, user


# ---------------------------------------------------------------------------
# 6-7 — the denormalized display fields never authorize, stale or blank.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_denormalized_field_naming_a_technician_cannot_authorize_without_history(
    client: AsyncClient,
) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER)
    await start_pm(client, work_order_id)
    repo = app_repository()
    repo._pm_work_orders[work_order_id] = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": COLLABORATOR_USER, "collaborators": ["tech-stale"]})

    for user in (COLLABORATOR_USER, "tech-stale"):
        denied = await save_pm_item(client, work_order_id, task_id, user)
        assert denied.status_code == 403, user


@pytest.mark.asyncio
async def test_active_history_authorizes_even_when_denormalized_field_is_blank(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER)
    await start_pm(client, work_order_id)
    repo = app_repository()
    repo._pm_work_orders[work_order_id] = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": None, "collaborators": []})

    allowed = await save_pm_item(client, work_order_id, task_id, PRIMARY_USER)
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_a_legacy_pm_work_order_authorizes_nobody() -> None:
    """Cancelled Legacy runtime: Legacy history and the display fields both name an assignee, yet the
    historical Legacy work order authorizes no recording (409) for them, anyone else or a manager."""
    service, repo = await _make_pm_service()
    work_order_id = await _open_work_order(service)
    await seed_legacy_pm_assignment(work_order_id, "tech-b", ["tech-c"], repo=repo)
    repo._pm_work_orders[work_order_id] = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": "tech-b", "collaborators": ["tech-c"]})

    for user, caps in (("tech-b", ()), ("tech-c", ()), ("tech-x", ()), ("manager-1", (CAN_MANAGE_PM,))):
        context = RequestContext(request_id="t", user_id=user, is_dev_auth=True, capabilities=frozenset(caps))
        with pytest.raises(ApiError) as exc:
            await service.authorize_recording(work_order_id, context, CAN_MANAGE_PM, "test")
        assert (exc.value.status_code, exc.value.code) == (409, "ASSIGNMENT_MODEL_MISMATCH"), user
    assert repo._pm_work_results.get(work_order_id, []) == []  # nothing recorded


# ---------------------------------------------------------------------------
# 8 — can_manage_pm always authorized, on any work order.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_manage_pm_may_always_submit_a_task_result(client: AsyncClient) -> None:
    # R4 PM Workflow: on a V2 work order the item is saved through the E01 item route while
    # IN_PROGRESS (was: legacy /results). Intent unchanged: `can_manage_pm` may record without
    # being on the team.
    work_order_id, task_id = await _open_work_order_via_api(client)
    await http_start(client, work_order_id)

    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/items/{task_id}/outcome",
        json={"disposition": "PERFORMED", "performed_actions": ["ตรวจเช็ค"], "used_parts": [],
              "evidence_attachment_ids": []},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
