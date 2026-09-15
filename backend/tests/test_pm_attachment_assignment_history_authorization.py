"""Final Cross-Phase Integration Fix — F1 (attachment authorization leg).

`AttachmentService.authorize_source`'s `PM_WORK_ORDER` branch used to read
`PmWorkOrder.primary_technician`/`.collaborators` directly (REV06.2),
deliberately left unchanged at the time because PM's history-vs-
denormalized-field consistency was out of REV06.2's scope. The final
cross-phase audit found this meant PM evidence download/list authorization
could still be fooled by (or wrongly deny) a stale denormalized field even
after F1 fixed `submit_pm_task_result` itself — the same source of truth
must back both, or evidence access and task-result recording could
silently disagree. This proves the fix: PM_WORK_ORDER attachment
authorization now derives from `pm_work_order_assignment` history, the
same way `PmService.get_active_assignment` and `submit_pm_task_result` do.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.repositories.mock import MockRepository


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


def _evidence_files() -> dict:
    return {"file": ("evidence.jpg", b"fake-jpeg-bytes", "image/jpeg")}


async def _open_pm_work_order(client: AsyncClient, vehicle_id: str = "VEH-1046") -> str:
    plans = await client.get(
        "/api/v1/pm/plans/status",
        params={"asset_type": "VEHICLE", "asset_id": vehicle_id},
        headers=_as("MAINTENANCE"),
    )
    plan_id = plans.json()[0]["plan"]["pm_plan_id"]
    response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "pm_plan_id": plan_id},
        headers=_as("MAINTENANCE"),
    )
    assert response.status_code == 200
    return response.json()["work_order"]["pm_work_order_id"]


async def _upload_pm_evidence(client: AsyncClient, work_order_id: str, headers: dict):
    return await client.post(
        "/api/v1/attachments",
        data={"purpose": "PM_EVIDENCE", "source_type": "PM_WORK_ORDER", "source_id": work_order_id},
        files=_evidence_files(),
        headers=headers,
    )


@pytest.mark.asyncio
async def test_stale_denormalized_pm_field_cannot_authorize_evidence_upload(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_pm_work_order(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-b", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    from app.dependencies import get_repository

    repo: MockRepository = get_repository()  # type: ignore[assignment]
    stale = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": "tech-stale", "collaborators": []}
    )
    repo._pm_work_orders[work_order_id] = stale

    denied = await _upload_pm_evidence(client, work_order_id, _as("TECHNICIAN", "tech-stale"))
    assert denied.status_code == 403

    allowed = await _upload_pm_evidence(client, work_order_id, _as("TECHNICIAN", "tech-b"))
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_active_history_authorizes_evidence_upload_even_with_blank_denormalized_field(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_pm_work_order(client)
    await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/assign",
        json={"primary_technician": "tech-b", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    from app.dependencies import get_repository

    repo: MockRepository = get_repository()  # type: ignore[assignment]
    wiped = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": None, "collaborators": []}
    )
    repo._pm_work_orders[work_order_id] = wiped

    allowed = await _upload_pm_evidence(client, work_order_id, _as("TECHNICIAN", "tech-b"))
    assert allowed.status_code == 200
