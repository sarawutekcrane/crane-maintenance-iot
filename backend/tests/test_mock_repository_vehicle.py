from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.common import OperationalStatus, PageParams
from app.domain.vehicle import VehicleStatusHistoryEntry
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
async def test_list_vehicle_status_history_orders_newest_first_when_changed_at_ties() -> None:
    """Deterministic-ordering fix: two entries sharing the exact same
    `changed_at` (as real successive `change_vehicle_status` calls can
    produce, since `utc_now()` has finite resolution) must still put the
    newer `history_id` first — never fall back to insertion order, which
    Python's stable sort would otherwise expose whenever the timestamps
    tie. Seeded directly (never through `change_vehicle_status`, which
    always stamps its own `utc_now()` and cannot be made to tie from the
    outside)."""
    repo = MockRepository()
    tied_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    repo._status_history.setdefault("VEH-1046", []).extend(
        [
            VehicleStatusHistoryEntry(
                history_id="STH-9001",
                vehicle_id="VEH-1046",
                status=OperationalStatus.OUT_OF_SERVICE,
                changed_at=tied_at,
            ),
            VehicleStatusHistoryEntry(
                history_id="STH-9002",
                vehicle_id="VEH-1046",
                status=OperationalStatus.WORKING,
                changed_at=tied_at,
            ),
        ]
    )

    history = await repo.list_vehicle_status_history("VEH-1046")
    tied_ids = [e.history_id for e in history if e.history_id in ("STH-9001", "STH-9002")]
    assert tied_ids == ["STH-9002", "STH-9001"]


@pytest.mark.asyncio
async def test_list_vehicles_pagination() -> None:
    repo = MockRepository()
    page, total = await repo.list_vehicles(
        q=None, operational_status=None, model_id=None, params=PageParams(page=1, page_size=2)
    )
    assert total == 3
    assert len(page) == 2
