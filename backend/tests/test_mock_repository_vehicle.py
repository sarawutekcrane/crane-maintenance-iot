from __future__ import annotations

import pytest

from app.domain.common import OperationalStatus, PageParams
from app.repositories.mock import MockRepository


@pytest.mark.asyncio
async def test_seed_data_is_isolated_per_repository_instance() -> None:
    repo_a = MockRepository()
    repo_b = MockRepository()

    await repo_a.update_vehicle_machine_no("VEH-1046", "CHANGED")

    vehicle_a = await repo_a.get_vehicle("VEH-1046")
    vehicle_b = await repo_b.get_vehicle("VEH-1046")

    assert vehicle_a is not None and vehicle_a.machine_no == "CHANGED"
    assert vehicle_b is not None and vehicle_b.machine_no == "TC-12"


@pytest.mark.asyncio
async def test_change_vehicle_status_appends_history_without_removing_previous_entries() -> None:
    repo = MockRepository()

    history_before = await repo.list_vehicle_status_history("VEH-1046")
    assert len(history_before) == 1

    await repo.change_vehicle_status(
        "VEH-1046", OperationalStatus.OUT_OF_SERVICE, changed_by="tester", note=None
    )
    await repo.change_vehicle_status(
        "VEH-1046", OperationalStatus.WORKING, changed_by="tester", note="กลับมาทำงาน"
    )

    history_after = await repo.list_vehicle_status_history("VEH-1046")
    assert len(history_after) == 3
    original_ids = {entry.history_id for entry in history_before}
    after_ids = {entry.history_id for entry in history_after}
    assert original_ids.issubset(after_ids)


@pytest.mark.asyncio
async def test_list_vehicles_pagination() -> None:
    repo = MockRepository()
    page, total = await repo.list_vehicles(
        q=None, operational_status=None, model_id=None, params=PageParams(page=1, page_size=2)
    )
    assert total == 3
    assert len(page) == 2
