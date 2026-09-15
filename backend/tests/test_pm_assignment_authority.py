"""Final Cross-Phase Integration Fix — F1: PM assignment authority.

The final cross-phase audit found that Repair now authorizes work against
the append-only `repair_assignment` history (REV06.1 CONSISTENCY-2), but
PM Work Order task-result authorization still read the denormalized
`PmWorkOrder.primary_technician`/`.collaborators` fields directly — the
exact same stale-state class already closed for Repair. `PmService.
get_active_assignment` (mirroring `RepairService.get_active_assignment`)
and `POST /pm/work-orders/{id}/results` now derive authorization from
`pm_work_order_assignment` history instead, using the same shared
`active_primary_and_collaborators` helper Repair already uses — so PM and
Repair can never independently drift into two different notions of
"currently assigned".
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from app.domain.meter_service import MeterService
from app.domain.pm_service import PmService
from app.repositories.mock import MockRepository


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


async def _make_pm_service() -> tuple[PmService, MockRepository]:
    repo = MockRepository()
    return PmService(repo, MeterService(repo)), repo


async def _open_work_order(service: PmService, vehicle_id: str = "VEH-1046") -> str:
    statuses = await service.list_applicable_plan_status(AssetType.VEHICLE, vehicle_id)
    plan_id = statuses[0].plan.pm_plan_id
    detail = await service.open_work_order(
        asset_type=AssetType.VEHICLE,
        asset_id=vehicle_id,
        pm_plan_id=plan_id,
        due_reason=None,
        opened_by="user-maintenance",
        note=None,
    )
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
# 1 — active PRIMARY may submit a task result.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_primary_may_submit_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True, "used_parts": [], "evidence_attachment_ids": []},
        headers=_as("TECHNICIAN", "tech-a"),
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2 — active COLLABORATOR may submit a task result.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_collaborator_may_submit_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": ["tech-helper"]},
        headers=_as("MAINTENANCE"),
    )

    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True, "used_parts": [], "evidence_attachment_ids": []},
        headers=_as("TECHNICIAN", "tech-helper"),
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 3-4 — ended PRIMARY/collaborator denied.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ended_primary_cannot_submit_task_result_new_primary_can(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-b", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    denied = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True, "used_parts": [], "evidence_attachment_ids": []},
        headers=_as("TECHNICIAN", "tech-a"),
    )
    assert denied.status_code == 403

    allowed = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True, "used_parts": [], "evidence_attachment_ids": []},
        headers=_as("TECHNICIAN", "tech-b"),
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_ended_collaborator_cannot_submit_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": ["tech-helper"]},
        headers=_as("MAINTENANCE"),
    )
    # Reassign without tech-helper — ends their COLLABORATOR row.
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    denied = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True, "used_parts": [], "evidence_attachment_ids": []},
        headers=_as("TECHNICIAN", "tech-helper"),
    )
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# 5 — unrelated technician denied.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_technician_cannot_submit_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    denied = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True, "used_parts": [], "evidence_attachment_ids": []},
        headers=_as("TECHNICIAN", "unrelated-tech"),
    )
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# 6-7 — stale/missing denormalized field vs. real assignment history
# (simulated by writing directly to the repository, bypassing
# `assign_pm_work_order`, to reproduce the exact partial-failure window
# REV06.1 already proved for Repair).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_denormalized_field_naming_a_technician_cannot_authorize_without_history() -> None:
    service, repo = await _make_pm_service()
    work_order_id = await _open_work_order(service)

    # No assignment history at all — but the denormalized field is
    # corrupted to name a technician directly (as if a stray write
    # happened without ever going through `assign_pm_work_order`).
    stale = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": "tech-stale", "collaborators": []}
    )
    repo._pm_work_orders[work_order_id] = stale

    primary, collaborators = await service.get_active_assignment(work_order_id)
    assert primary is None
    assert collaborators == []

    from app.context import RequestContext
    from app.domain.authz import CAN_MANAGE_PM, require_assignment_or_capability

    with pytest.raises(Exception):
        require_assignment_or_capability(
            RequestContext(request_id="t", user_id="tech-stale", capabilities=frozenset()),
            CAN_MANAGE_PM,
            primary,
            collaborators,
            "test",
        )


@pytest.mark.asyncio
async def test_active_history_authorizes_even_when_denormalized_field_is_blank() -> None:
    service, repo = await _make_pm_service()
    work_order_id = await _open_work_order(service)

    await service.assign(work_order_id, primary_technician="tech-b", collaborators=[])

    # Wipe the denormalized fields entirely, leaving history as the only
    # record (simulating the second write never having happened).
    wiped = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": None, "collaborators": []}
    )
    repo._pm_work_orders[work_order_id] = wiped

    primary, collaborators = await service.get_active_assignment(work_order_id)
    assert primary == "tech-b"
    assert collaborators == []

    from app.context import RequestContext
    from app.domain.authz import CAN_MANAGE_PM, require_assignment_or_capability

    require_assignment_or_capability(
        RequestContext(request_id="t", user_id="tech-b", capabilities=frozenset()),
        CAN_MANAGE_PM,
        primary,
        collaborators,
        "test",
    )


# ---------------------------------------------------------------------------
# 8 — can_manage_pm always authorized, on any work order.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_manage_pm_may_always_submit_a_task_result(client: AsyncClient) -> None:
    work_order_id, task_id = await _open_work_order_via_api(client)

    response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": task_id, "completed": True, "used_parts": [], "evidence_attachment_ids": []},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
