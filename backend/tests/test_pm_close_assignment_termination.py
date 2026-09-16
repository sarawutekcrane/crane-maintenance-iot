"""Live UAT finding — PM close leaves active assignments dangling.

Closing a PM Work Order (`PmService.close_work_order` ->
`Repository.close_pm_work_order`) correctly flips the work order to
CLOSED, but left every currently-active `pm_work_assignment` history row
`active_status=True`/`ended_at=None` — inconsistent with the already-fixed
`close_repair` behavior (see `test_repair_close_assignment_and_awaiting_
parts.py`) and with `pm_work_assignment` history being documented as
authoritative. Fixed at the repository contract level
(`Repository.close_pm_work_order`, implemented identically by
`MockRepository` and `GoogleSheetsRepository`), mirroring `close_repair`'s
own non-destructive history-ending pattern exactly.

`pm_work_scope`'s `scope_status`/`completed_at`/`completion_snapshot_
event_id` are explicitly out of scope for this fix (a separate, already
audited question) and are not touched or asserted on here.

Repository-level tests exercise the FAKE in-memory `gspread`-shaped
client from `tests.test_google_sheets_real_io` (never the real Google
API/network — see that module's docstring and REV05 section 11G).
API-level test runs against the default `client` fixture (MockRepository,
DEV_AUTH_MODE).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws
from app.repositories.google_sheets import schemas


async def _mock_repo_with_pmwo(primary=None, collaborators=None):
    from app.repositories.mock.repository import MockRepository

    repo = MockRepository()
    work_order = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1046",
        pm_plan_id="PMP-0001",
        revision_id="PMREV-0001",
        due_reason=None,
        opened_by="user-maintenance",
        note=None,
    )
    if primary or collaborators:
        await repo.assign_pm_work_order(
            pm_work_order_id=work_order.pm_work_order_id,
            primary_technician=primary,
            collaborators=list(collaborators) if collaborators else [],
            assigned_by="user-maintenance",
        )
    return repo, work_order


def _pm_sheets() -> list:
    return [
        _ws(schemas.PM_WORK_ORDER_SHEET),
        _ws(schemas.PM_WORK_SCOPE_SHEET),
        _ws(schemas.PM_WORK_ASSIGNMENT_SHEET),
        _ws(schemas.PM_WORK_RESULT_SHEET),
        _ws(schemas.PM_USED_PART_SHEET),
    ]


async def _sheets_repo_with_pmwo(primary=None, collaborators=None):
    repo = _repo_with_fake_sheets(*_pm_sheets())
    work_order = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        pm_plan_id="PMP-0001",
        revision_id="PMREV-0001",
        due_reason=None,
        opened_by="user-maintenance",
        note=None,
    )
    if primary or collaborators:
        await repo.assign_pm_work_order(
            pm_work_order_id=work_order.pm_work_order_id,
            primary_technician=primary,
            collaborators=list(collaborators) if collaborators else [],
            assigned_by="user-maintenance",
        )
    return repo, work_order


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_pmwo, _sheets_repo_with_pmwo])
async def test_pm_close_with_one_active_primary_ends_it(repo_factory) -> None:
    """1. Close PM Work Order with one active PRIMARY -> assignment
    becomes inactive -> ended_at is populated."""
    repo, work_order = await repo_factory(primary="user-tech-1")
    await repo.close_pm_work_order(work_order.pm_work_order_id, closed_by="user-maintenance", note=None)

    history = await repo.list_pm_work_order_assignment_history(work_order.pm_work_order_id)
    assert len(history) == 1
    entry = history[0]
    assert entry.user_id == "user-tech-1"
    assert entry.active_status is False
    assert entry.ended_at is not None


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_pmwo, _sheets_repo_with_pmwo])
async def test_pm_close_with_primary_and_collaborators_ends_all(repo_factory) -> None:
    """2. Close PM Work Order with PRIMARY + active collaborators -> all
    active assignments are ended."""
    repo, work_order = await repo_factory(
        primary="user-tech-1", collaborators=["user-tech-2", "user-tech-3"]
    )
    await repo.close_pm_work_order(work_order.pm_work_order_id, closed_by="user-maintenance", note=None)

    history = await repo.list_pm_work_order_assignment_history(work_order.pm_work_order_id)
    assert len(history) == 3
    assert all(not h.active_status for h in history)
    assert all(h.ended_at is not None for h in history)


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_pmwo, _sheets_repo_with_pmwo])
async def test_pm_historical_already_ended_rows_are_unchanged_by_close(repo_factory) -> None:
    """3. Historical already-ended assignment rows remain unchanged, and
    ended_at for the newly-ended row equals the work order's own
    closed_at — not a separately generated later timestamp."""
    repo, work_order = await repo_factory(primary="user-tech-1")
    # Reassign so user-tech-1's row is already ended BEFORE close.
    await repo.assign_pm_work_order(
        pm_work_order_id=work_order.pm_work_order_id,
        primary_technician="user-tech-2",
        collaborators=[],
        assigned_by="user-maintenance",
    )
    history_before_close = await repo.list_pm_work_order_assignment_history(work_order.pm_work_order_id)
    old_entry_before = next(h for h in history_before_close if h.user_id == "user-tech-1")
    assert old_entry_before.active_status is False
    old_ended_at_before = old_entry_before.ended_at
    assert old_ended_at_before is not None

    closed = await repo.close_pm_work_order(
        work_order.pm_work_order_id, closed_by="user-maintenance", note=None
    )

    history_after_close = await repo.list_pm_work_order_assignment_history(work_order.pm_work_order_id)
    old_entry_after = next(h for h in history_after_close if h.user_id == "user-tech-1")
    # Untouched: same ended_at, still inactive — close never rewrites an
    # already-ended row.
    assert old_entry_after.active_status is False
    assert old_entry_after.ended_at == old_ended_at_before
    new_entry_after = next(h for h in history_after_close if h.user_id == "user-tech-2")
    assert new_entry_after.active_status is False
    assert new_entry_after.ended_at is not None
    # The exact assertion required: ended_at must equal the PM Work
    # Order's own closed_at, not a separately-generated timestamp.
    assert new_entry_after.ended_at == closed.closed_at


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_pmwo, _sheets_repo_with_pmwo])
async def test_pm_closed_work_order_has_zero_active_assignments(repo_factory) -> None:
    """4. Closed PM Work Order has zero active assignments."""
    from app.domain.assignment import active_primary_and_collaborators

    repo, work_order = await repo_factory(primary="user-tech-1", collaborators=["user-tech-2"])
    await repo.close_pm_work_order(work_order.pm_work_order_id, closed_by="user-maintenance", note=None)

    history = await repo.list_pm_work_order_assignment_history(work_order.pm_work_order_id)
    primary, collaborators = active_primary_and_collaborators(history)
    assert primary is None
    assert collaborators == []


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_pmwo, _sheets_repo_with_pmwo])
async def test_pm_assignment_history_still_returns_all_historical_rows(repo_factory) -> None:
    """5. Assignment-history still returns all historical rows."""
    repo, work_order = await repo_factory(primary="user-tech-1")
    await repo.assign_pm_work_order(
        pm_work_order_id=work_order.pm_work_order_id,
        primary_technician="user-tech-2",
        collaborators=[],
        assigned_by="user-maintenance",
    )
    await repo.close_pm_work_order(work_order.pm_work_order_id, closed_by="user-maintenance", note=None)

    history = await repo.list_pm_work_order_assignment_history(work_order.pm_work_order_id)
    # Both the superseded and the final assignment survive as history.
    assert {h.user_id for h in history} == {"user-tech-1", "user-tech-2"}
    assert len(history) == 2


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_pmwo, _sheets_repo_with_pmwo])
async def test_pm_my_work_does_not_return_the_closed_work_order(repo_factory) -> None:
    """6. My Work does not return the closed PM Work Order."""
    from app.domain.common import PageParams
    from app.domain.pm import PmWorkOrderStatus

    repo, work_order = await repo_factory(primary="user-tech-1")
    await repo.close_pm_work_order(work_order.pm_work_order_id, closed_by="user-maintenance", note=None)

    items, total = await repo.list_pm_work_orders(
        asset_type=None,
        asset_id=None,
        status=PmWorkOrderStatus.OPEN,
        params=PageParams(page=1, page_size=20),
        assigned_to="user-tech-1",
    )
    assert total == 0
    assert items == []


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_pmwo, _sheets_repo_with_pmwo])
async def test_closing_one_pm_work_order_does_not_end_assignments_on_another(repo_factory) -> None:
    """7. Closing one PM Work Order does not end assignments on another."""
    from app.domain.pm import PmWorkOrderStatus

    repo, work_order_a = await repo_factory(primary="user-tech-1")
    work_order_b = await repo.create_pm_work_order(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1046" if repo.mode == "mock" else "VEH-9001",
        pm_plan_id="PMP-0001",
        revision_id="PMREV-0001",
        due_reason=None,
        opened_by="user-maintenance",
        note=None,
    )
    await repo.assign_pm_work_order(
        pm_work_order_id=work_order_b.pm_work_order_id,
        primary_technician="user-tech-9",
        collaborators=[],
        assigned_by="user-maintenance",
    )

    await repo.close_pm_work_order(work_order_a.pm_work_order_id, closed_by="user-maintenance", note=None)

    history_a = await repo.list_pm_work_order_assignment_history(work_order_a.pm_work_order_id)
    assert all(not h.active_status for h in history_a)

    history_b = await repo.list_pm_work_order_assignment_history(work_order_b.pm_work_order_id)
    assert len(history_b) == 1
    assert history_b[0].active_status is True
    assert history_b[0].ended_at is None

    work_order_b_detail = await repo.get_pm_work_order(work_order_b.pm_work_order_id)
    assert work_order_b_detail.work_order.status == PmWorkOrderStatus.OPEN


@pytest.mark.asyncio
async def test_pm_close_ends_active_assignment_end_to_end(client: AsyncClient) -> None:
    """8 (API level) — the exact live UAT reproduction (PMWO-0001)."""
    work_order = await client.post(
        "/api/v1/pm/work-orders",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": "PMP-0001"},
    )
    assert work_order.status_code == 200
    pm_work_order_id = work_order.json()["work_order"]["pm_work_order_id"]

    assign = await client.post(
        f"/api/v1/pm/work-orders/{pm_work_order_id}/assign",
        json={"primary_technician": "dev-user", "collaborators": []},
    )
    assert assign.status_code == 200

    history_before = await client.get(f"/api/v1/pm/work-orders/{pm_work_order_id}/assignment-history")
    assert history_before.json()[0]["active_status"] is True
    assert history_before.json()[0]["ended_at"] is None

    close = await client.post(f"/api/v1/pm/work-orders/{pm_work_order_id}/close", json={})
    assert close.status_code == 200
    closed_body = close.json()["work_order"]
    assert closed_body["status"] == "CLOSED"

    history_after = await client.get(f"/api/v1/pm/work-orders/{pm_work_order_id}/assignment-history")
    assert history_after.status_code == 200
    entries = history_after.json()
    assert len(entries) == 1
    assert entries[0]["active_status"] is False
    assert entries[0]["ended_at"] is not None
    # ended_at must be the PM Work Order's own closed_at, not a separate,
    # later-generated timestamp.
    assert entries[0]["ended_at"] == closed_body["closed_at"]

    my_work = await client.get("/api/v1/pm/work-orders/my-work")
    assert my_work.status_code == 200
    assert my_work.json()["total_items"] == 0
    assert my_work.json()["items"] == []
