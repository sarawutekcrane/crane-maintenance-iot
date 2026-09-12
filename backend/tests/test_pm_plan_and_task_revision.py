"""PM plan / task revision identity and history integrity (Phase 4).

Mirrors the Phase 3 checklist revision tests exactly — the same revision
model, the same "old revision remains readable / new revision does not
mutate old history" guarantee.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from app.domain.pm import PmTask, PmTaskRevision
from app.repositories.mock import MockRepository


@pytest.mark.asyncio
async def test_active_pm_task_revision_loads_for_plan1(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pm/plans/PMP-0001/active-revision")
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["plan_code"] == "PLAN1"
    assert body["revision"]["revision_number"] == 1
    assert len(body["tasks"]) == 3
    # Placeholder content is clearly example/dev data (SOURCE DATA RULE —
    # OPEN_DECISIONS_REGISTER_EN.txt E05), not a real company PM procedure.
    assert "ตัวอย่างชั่วคราว" in body["plan"]["name"]


@pytest.mark.asyncio
async def test_pm_task_revision_direct_read_matches_active(client: AsyncClient) -> None:
    active = await client.get("/api/v1/pm/plans/PMP-0001/active-revision")
    revision_id = active.json()["revision"]["revision_id"]
    direct = await client.get(f"/api/v1/pm/plans/PMP-0001/revisions/{revision_id}")
    assert direct.status_code == 200
    assert direct.json() == active.json()


@pytest.mark.asyncio
async def test_pm_task_revision_controlled_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pm/plans/PMP-0001/revisions/PMREV-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PM_TASK_REVISION_NOT_FOUND"


@pytest.mark.asyncio
async def test_pm_plan_not_found_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pm/plans/PMP-9999/active-revision")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PM_PLAN_NOT_FOUND"


@pytest.mark.asyncio
async def test_plan2_plan3_plan4_are_not_fabricated(client: AsyncClient) -> None:
    """OPEN_DECISIONS_REGISTER_EN.txt E05: PLAN2/PLAN3/PLAN4 source data is
    not present anywhere in this repository, so no master record or task
    content exists for them — only PLAN1 (clearly labeled example data)."""
    status_response = await client.get(
        "/api/v1/pm/plans/status", params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"}
    )
    assert status_response.status_code == 200
    plan_codes = {row["plan"]["plan_code"] for row in status_response.json()}
    assert plan_codes == {"PLAN1"}
    for guessed_id in ("PMP-0002", "PMP-0003", "PMP-0004"):
        response = await client.get(f"/api/v1/pm/plans/{guessed_id}/active-revision")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_old_pm_task_revision_remains_readable_after_a_newer_one_becomes_active() -> None:
    repo = MockRepository()

    original = await repo.get_active_pm_task_revision("PMP-0001")
    assert original is not None
    assert original.revision.revision_id == "PMREV-0001"

    new_revision = PmTaskRevision(
        revision_id="PMREV-0099",
        pm_plan_id="PMP-0001",
        revision_number=2,
        effective_date=original.revision.effective_date,
        created_at=original.revision.created_at,
    )
    repo._pm_task_revisions["PMREV-0099"] = new_revision  # type: ignore[attr-defined]
    repo._pm_tasks["PMREV-0099"] = [  # type: ignore[attr-defined]
        PmTask(
            pm_task_id="PMT-9001",
            revision_id="PMREV-0099",
            sequence=1,
            description="งานบำรุงรักษาตัวอย่างที่ 1 (แก้ไขในรุ่นใหม่)",
        )
    ]

    active = await repo.get_active_pm_task_revision("PMP-0001")
    assert active is not None
    assert active.revision.revision_id == "PMREV-0099"

    still_old = await repo.get_pm_task_revision("PMP-0001", "PMREV-0001")
    assert still_old is not None
    assert [t.description for t in still_old.tasks] == [t.description for t in original.tasks]


@pytest.mark.asyncio
async def test_new_pm_task_revision_does_not_mutate_old_work_order_history(
    client: AsyncClient,
) -> None:
    open_response = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": "PMP-0001"},
    )
    assert open_response.status_code == 200
    work_order_id = open_response.json()["work_order"]["pm_work_order_id"]
    original_revision_id = open_response.json()["work_order"]["revision_id"]

    result_response = await client.post(
        f"/api/v1/pm/work-orders/{work_order_id}/results",
        json={"pm_task_id": "PMT-0001", "completed": True},
    )
    assert result_response.status_code == 200
    original_description = result_response.json()["results"][0]["task_description"]

    # Simulate a future PM-authoring phase adding a new revision with a
    # changed task description for the same task_id, directly on the
    # shared repository instance the app is using (same pattern Phase 3
    # used for the equivalent checklist-revision test).
    from app.dependencies import get_repository

    repo = get_repository()
    new_revision = PmTaskRevision(
        revision_id="PMREV-9099",
        pm_plan_id="PMP-0001",
        revision_number=2,
        effective_date=repo._pm_task_revisions["PMREV-0001"].effective_date,  # type: ignore[attr-defined]
        created_at=repo._pm_task_revisions["PMREV-0001"].created_at,  # type: ignore[attr-defined]
    )
    repo._pm_task_revisions["PMREV-9099"] = new_revision  # type: ignore[attr-defined]
    repo._pm_tasks["PMREV-9099"] = [  # type: ignore[attr-defined]
        PmTask(
            pm_task_id="PMT-0001",
            revision_id="PMREV-9099",
            sequence=1,
            description="เนื้อหางานที่ถูกแก้ไขในรุ่นใหม่",
        )
    ]

    # The new revision is now active for future work orders...
    new_active = await client.get("/api/v1/pm/plans/PMP-0001/active-revision")
    assert new_active.json()["revision"]["revision_id"] == "PMREV-9099"

    # ...but the previously opened work order and its already-submitted
    # result still reference the exact revision/description used at the
    # time, unaffected by the new revision.
    reread = await client.get(f"/api/v1/pm/work-orders/{work_order_id}")
    assert reread.status_code == 200
    body = reread.json()
    assert body["work_order"]["revision_id"] == original_revision_id == "PMREV-0001"
    assert body["results"][0]["revision_id"] == "PMREV-0001"
    assert body["results"][0]["task_description"] == original_description
    assert body["results"][0]["task_description"] != "เนื้อหางานที่ถูกแก้ไขในรุ่นใหม่"
