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

DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107: the Legacy assignment runtime
is cancelled. The PM_WORK_ORDER attachment source now authorizes only from the
CURRENT V2 set (evidence while IN_PROGRESS); the display fields never authorize,
and a historical Legacy work order is no attachment source for anyone (409).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.repositories.mock import MockRepository
from tests.legacy_assignment_seed import mark_historical_legacy
from tests.v2_http_assignment import (
    COLLABORATOR_USER,
    PRIMARY_USER,
    assign_v2,
    start_pm,
)


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
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER)
    await start_pm(client, work_order_id)

    from app.dependencies import get_repository

    repo: MockRepository = get_repository()  # type: ignore[assignment]
    stale = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": COLLABORATOR_USER, "collaborators": ["tech-stale"]}
    )
    repo._pm_work_orders[work_order_id] = stale

    for user in (COLLABORATOR_USER, "tech-stale"):
        denied = await _upload_pm_evidence(client, work_order_id, _as("TECHNICIAN", user))
        assert denied.status_code == 403, user

    allowed = await _upload_pm_evidence(client, work_order_id, _as("TECHNICIAN", PRIMARY_USER))
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_active_history_authorizes_evidence_upload_even_with_blank_denormalized_field(
    client: AsyncClient,
) -> None:
    work_order_id = await _open_pm_work_order(client)
    await assign_v2(client, "pm/work-orders", work_order_id, PRIMARY_USER)
    await start_pm(client, work_order_id)

    from app.dependencies import get_repository

    repo: MockRepository = get_repository()  # type: ignore[assignment]
    wiped = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": None, "collaborators": []}
    )
    repo._pm_work_orders[work_order_id] = wiped

    allowed = await _upload_pm_evidence(client, work_order_id, _as("TECHNICIAN", PRIMARY_USER))
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_a_legacy_pm_work_order_is_no_evidence_source_for_anyone(client: AsyncClient) -> None:
    work_order_id = await _open_pm_work_order(client)
    mark_historical_legacy("pm/work-orders", work_order_id)
    from app.dependencies import get_repository

    repo: MockRepository = get_repository()  # type: ignore[assignment]
    repo._pm_work_orders[work_order_id] = repo._pm_work_orders[work_order_id].model_copy(
        update={"primary_technician": PRIMARY_USER, "collaborators": [COLLABORATOR_USER]})
    for headers in (_as("TECHNICIAN", PRIMARY_USER), _as("TECHNICIAN", COLLABORATOR_USER), _as("MAINTENANCE")):
        refused = await _upload_pm_evidence(client, work_order_id, headers)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "ASSIGNMENT_MODEL_MISMATCH"
