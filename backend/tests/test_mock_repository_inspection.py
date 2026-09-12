from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.domain.asset import AssetType
from app.domain.checklist import ChecklistItem, ChecklistRevision, InspectionResultValue
from app.domain.inspection import NewInspectionItemInput
from app.repositories.mock import MockRepository


@pytest.mark.asyncio
async def test_checklist_revisions_are_isolated_per_repository_instance() -> None:
    repo_a = MockRepository()
    repo_b = MockRepository()

    detail_a = await repo_a.get_active_checklist_revision(AssetType.VEHICLE)
    detail_b = await repo_b.get_active_checklist_revision(AssetType.VEHICLE)
    assert detail_a is not None and detail_b is not None
    assert detail_a.revision.revision_id == detail_b.revision.revision_id == "REV-0001"


@pytest.mark.asyncio
async def test_old_checklist_revision_remains_readable_after_a_newer_one_becomes_active() -> None:
    repo = MockRepository()

    original = await repo.get_active_checklist_revision(AssetType.VEHICLE)
    assert original is not None
    assert original.revision.revision_id == "REV-0001"
    original_item_titles = [item.title for item in original.items]

    # There is no checklist-authoring endpoint in Phase 3 (out of scope);
    # this simulates what a future authoring phase would do — add a new,
    # immutable revision without ever touching REV-0001's own row/items —
    # by writing directly into the mock repository's in-memory store.
    new_revision = ChecklistRevision(
        revision_id="REV-0099",
        checklist_id="CHK-0001",
        revision_number=2,
        effective_date=original.revision.effective_date,
        created_at=original.revision.created_at,
    )
    repo._checklist_revisions["REV-0099"] = new_revision  # type: ignore[attr-defined]
    repo._checklist_items["REV-0099"] = [  # type: ignore[attr-defined]
        ChecklistItem(
            item_id="ITM-V2-0001",
            revision_id="REV-0099",
            sequence=1,
            title="รายการตรวจสอบตัวอย่างที่ 1 (แก้ไขในรุ่นใหม่)",
        )
    ]

    # The new revision is now the active one...
    active = await repo.get_active_checklist_revision(AssetType.VEHICLE)
    assert active is not None
    assert active.revision.revision_id == "REV-0099"

    # ...but the old revision is still readable, byte-for-byte unchanged.
    still_old = await repo.get_checklist_revision("CHK-0001", "REV-0001")
    assert still_old is not None
    assert [item.title for item in still_old.items] == original_item_titles
    assert still_old.revision.revision_number == 1


@pytest.mark.asyncio
async def test_new_checklist_revision_does_not_mutate_a_previously_submitted_inspection() -> None:
    repo = MockRepository()

    revision = await repo.get_active_checklist_revision(AssetType.VEHICLE)
    assert revision is not None
    item = revision.items[0]

    detail = await repo.create_inspection(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1046",
        checklist_id=revision.checklist.checklist_id,
        revision_id=revision.revision.revision_id,
        revision_number=revision.revision.revision_number,
        inspector_user_id="tester",
        overall_remark=None,
        items=[
            NewInspectionItemInput(
                item_id=item.item_id,
                sequence=item.sequence,
                title=item.title,
                is_critical=item.is_critical,
                result=InspectionResultValue.PASS,
            )
        ],
    )
    original_title = detail.items[0].title
    original_revision_id = detail.header.revision_id

    # A new revision is introduced (see the test above for why this is
    # written directly into the store rather than through an endpoint).
    repo._checklist_revisions["REV-0099"] = ChecklistRevision(  # type: ignore[attr-defined]
        revision_id="REV-0099",
        checklist_id="CHK-0001",
        revision_number=2,
        effective_date=revision.revision.effective_date,
        created_at=revision.revision.created_at,
    )
    repo._checklist_items["REV-0099"] = [  # type: ignore[attr-defined]
        ChecklistItem(
            item_id=item.item_id,
            revision_id="REV-0099",
            sequence=1,
            title="ชื่อรายการที่ถูกเปลี่ยนในรุ่นใหม่",
        )
    ]

    reloaded = await repo.get_inspection(detail.header.inspection_id)
    assert reloaded is not None
    assert reloaded.items[0].title == original_title
    assert reloaded.header.revision_id == original_revision_id


@pytest.mark.asyncio
async def test_active_checklist_selection_picks_latest_effective_revision() -> None:
    repo = MockRepository()

    future_revision = ChecklistRevision(
        revision_id="REV-0098",
        checklist_id="CHK-0001",
        revision_number=2,
        effective_date=date(2099, 1, 1),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    # effective_date is far in the future, so it must not become active yet.
    repo._checklist_revisions["REV-0098"] = future_revision  # type: ignore[attr-defined]
    repo._checklist_items["REV-0098"] = []  # type: ignore[attr-defined]

    active = await repo.get_active_checklist_revision(AssetType.VEHICLE)
    assert active is not None
    assert active.revision.revision_id == "REV-0001"
