"""Live UAT findings — two Repair-lifecycle consistency defects.

DEFECT A: closing a Repair left its `repair_assignment` history rows
`active_status=True`/`ended_at=None` even though the Repair itself
correctly became CLOSED and `GET /repairs/my-work` correctly stopped
listing it (My Work also excludes CLOSED repairs, which is why the bug
was not visible there). `repair_assignment` history is documented as
authoritative — it must never keep reporting someone as still actively
assigned to a CLOSED repair. Fixed at the repository contract level
(`Repository.close_repair`, implemented identically by `MockRepository`
and `GoogleSheetsRepository`) so a future PostgreSQL repository inherits
the same requirement, mirroring `assign_repair`'s existing non-destructive
history-ending pattern.

DEFECT B: only `GET /repairs/{id}` computed `awaiting_parts`
(`MaterialRequestService.is_awaiting_parts`); every other endpoint
returning `RepairDetailResponse` (create, convert, assign, add action,
add part, close) defaulted it to `None`. Fixed by centralizing response
construction into `app.api.v1.repairs.build_repair_detail_response`,
called by every one of those endpoints (including the Repair Request
`convert` endpoint in `app.api.v1.repair_requests`), so the same
persisted state always produces the same `awaiting_parts` regardless of
which endpoint served the response.

API-level tests run against the default `client` fixture (MockRepository,
DEV_AUTH_MODE). Repository-level tests exercise the FAKE in-memory
`gspread`-shaped client from `tests.test_google_sheets_real_io` (never
the real Google API/network — see that module's docstring and REV05
section 11G): no live-sheet I/O happens here.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from app.domain.repair import RepairSourceType, RepairStatus
from tests.test_google_sheets_repair_real_io import _repair_sheets
from tests.test_google_sheets_real_io import _repo_with_fake_sheets


# ---------------------------------------------------------------------------
# DEFECT A — repository-level contract tests (Mock + GoogleSheets).
# ---------------------------------------------------------------------------


async def _mock_repo_with_repair(primary=None, collaborators=None):
    from app.repositories.mock.repository import MockRepository

    repo = MockRepository()
    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1046",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="ทดสอบ",
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    if primary or collaborators:
        await repo.assign_repair(
            repair_id=repair.repair_id,
            primary_technician=primary,
            collaborators=list(collaborators) if collaborators else [],
            assigned_by="user-maintenance",
        )
    return repo, repair


def _sheets_repo_with_repair_sync():
    return _repo_with_fake_sheets(*_repair_sheets())


async def _sheets_repo_with_repair(primary=None, collaborators=None):
    repo = _sheets_repo_with_repair_sync()
    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="ทดสอบ",
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    if primary or collaborators:
        await repo.assign_repair(
            repair_id=repair.repair_id,
            primary_technician=primary,
            collaborators=list(collaborators) if collaborators else [],
            assigned_by="user-maintenance",
        )
    return repo, repair


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_repair, _sheets_repo_with_repair])
async def test_close_with_one_active_primary_ends_it(repo_factory) -> None:
    """1. Close Repair with one active PRIMARY -> assignment becomes
    inactive -> ended_at is populated."""
    repo, repair = await repo_factory(primary="user-tech-1")
    await repo.close_repair(repair.repair_id, closed_by="user-maintenance", close_note=None)

    history = await repo.list_repair_assignment_history(repair.repair_id)
    assert len(history) == 1
    entry = history[0]
    assert entry.user_id == "user-tech-1"
    assert entry.active_status is False
    assert entry.ended_at is not None


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_repair, _sheets_repo_with_repair])
async def test_close_with_primary_and_collaborators_ends_all(repo_factory) -> None:
    """2. Close Repair with PRIMARY + active collaborators -> all active
    assignments are ended."""
    repo, repair = await repo_factory(primary="user-tech-1", collaborators=["user-tech-2", "user-tech-3"])
    await repo.close_repair(repair.repair_id, closed_by="user-maintenance", close_note=None)

    history = await repo.list_repair_assignment_history(repair.repair_id)
    assert len(history) == 3
    assert all(not h.active_status for h in history)
    assert all(h.ended_at is not None for h in history)


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_repair, _sheets_repo_with_repair])
async def test_historical_already_ended_rows_are_unchanged_by_close(repo_factory) -> None:
    """3. Historical already-ended assignment rows remain unchanged."""
    repo, repair = await repo_factory(primary="user-tech-1")
    # Reassign so user-tech-1's row is already ended BEFORE close.
    await repo.assign_repair(
        repair_id=repair.repair_id,
        primary_technician="user-tech-2",
        collaborators=[],
        assigned_by="user-maintenance",
    )
    history_before_close = await repo.list_repair_assignment_history(repair.repair_id)
    old_entry_before = next(h for h in history_before_close if h.user_id == "user-tech-1")
    assert old_entry_before.active_status is False
    old_ended_at_before = old_entry_before.ended_at
    assert old_ended_at_before is not None

    await repo.close_repair(repair.repair_id, closed_by="user-maintenance", close_note=None)

    history_after_close = await repo.list_repair_assignment_history(repair.repair_id)
    old_entry_after = next(h for h in history_after_close if h.user_id == "user-tech-1")
    # Untouched: same ended_at, still inactive — close never rewrites an
    # already-ended row.
    assert old_entry_after.active_status is False
    assert old_entry_after.ended_at == old_ended_at_before
    new_entry_after = next(h for h in history_after_close if h.user_id == "user-tech-2")
    assert new_entry_after.active_status is False
    assert new_entry_after.ended_at is not None


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_repair, _sheets_repo_with_repair])
async def test_closed_repair_has_zero_active_assignments(repo_factory) -> None:
    """4. Closed Repair has zero active assignments."""
    from app.domain.assignment import active_primary_and_collaborators

    repo, repair = await repo_factory(primary="user-tech-1", collaborators=["user-tech-2"])
    await repo.close_repair(repair.repair_id, closed_by="user-maintenance", close_note=None)

    history = await repo.list_repair_assignment_history(repair.repair_id)
    primary, collaborators = active_primary_and_collaborators(history)
    assert primary is None
    assert collaborators == []


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_repair, _sheets_repo_with_repair])
async def test_assignment_history_still_returns_all_historical_rows(repo_factory) -> None:
    """5. Assignment-history still returns all historical rows."""
    repo, repair = await repo_factory(primary="user-tech-1")
    await repo.assign_repair(
        repair_id=repair.repair_id,
        primary_technician="user-tech-2",
        collaborators=[],
        assigned_by="user-maintenance",
    )
    await repo.close_repair(repair.repair_id, closed_by="user-maintenance", close_note=None)

    history = await repo.list_repair_assignment_history(repair.repair_id)
    # Both the superseded and the final assignment survive as history.
    assert {h.user_id for h in history} == {"user-tech-1", "user-tech-2"}
    assert len(history) == 2


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_repair, _sheets_repo_with_repair])
async def test_my_work_does_not_return_the_closed_repair(repo_factory) -> None:
    """6. My Work does not return the closed Repair."""
    from app.domain.common import PageParams

    repo, repair = await repo_factory(primary="user-tech-1")
    await repo.close_repair(repair.repair_id, closed_by="user-maintenance", close_note=None)

    items, total = await repo.list_repairs(
        asset_type=None,
        asset_id=None,
        status=RepairStatus.OPEN,
        params=PageParams(page=1, page_size=20),
        assigned_to="user-tech-1",
    )
    assert total == 0
    assert items == []


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_repair, _sheets_repo_with_repair])
async def test_closing_one_repair_does_not_end_assignments_on_another(repo_factory) -> None:
    """7. Closing one Repair does not end assignments on another Repair."""
    repo, repair_a = await repo_factory(primary="user-tech-1")
    repair_b = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1046" if repo.mode == "mock" else "VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="อีกงานหนึ่ง",
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair_b.repair_id,
        primary_technician="user-tech-9",
        collaborators=[],
        assigned_by="user-maintenance",
    )

    await repo.close_repair(repair_a.repair_id, closed_by="user-maintenance", close_note=None)

    history_a = await repo.list_repair_assignment_history(repair_a.repair_id)
    assert all(not h.active_status for h in history_a)

    history_b = await repo.list_repair_assignment_history(repair_b.repair_id)
    assert len(history_b) == 1
    assert history_b[0].active_status is True
    assert history_b[0].ended_at is None

    repair_b_detail = await repo.get_repair(repair_b.repair_id)
    assert repair_b_detail.repair.status == RepairStatus.OPEN


@pytest.mark.parametrize("repo_factory", [_mock_repo_with_repair, _sheets_repo_with_repair])
async def test_repeated_close_is_rejected_and_does_not_further_mutate_history(repo_factory) -> None:
    """8. Repeated close / invalid close behavior remains consistent with
    existing lifecycle rules — the repository itself allows a second raw
    close call (F01/lifecycle enforcement lives in RepairService, not the
    repository), but it must not corrupt already-ended history rows."""
    repo, repair = await repo_factory(primary="user-tech-1")
    await repo.close_repair(repair.repair_id, closed_by="user-maintenance", close_note=None)
    history_after_first_close = await repo.list_repair_assignment_history(repair.repair_id)
    ended_at_after_first = history_after_first_close[0].ended_at

    await repo.close_repair(repair.repair_id, closed_by="user-maintenance", close_note="ปิดซ้ำ")
    history_after_second_close = await repo.list_repair_assignment_history(repair.repair_id)
    assert len(history_after_second_close) == 1
    assert history_after_second_close[0].active_status is False
    # Already-ended row is untouched by a second close call.
    assert history_after_second_close[0].ended_at == ended_at_after_first


@pytest.mark.asyncio
async def test_close_repair_rejected_by_service_lifecycle_rule_on_second_call(
    client: AsyncClient,
) -> None:
    """8 (API level). RepairService enforces REPAIR_ALREADY_CLOSED on a
    second close — that existing lifecycle rule is unaffected by the
    assignment-termination fix."""
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]
    await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "user-tech-1", "collaborators": []},
    )
    first_close = await client.post(f"/api/v1/repairs/{repair_id}/close", json={})
    assert first_close.status_code == 200

    second_close = await client.post(f"/api/v1/repairs/{repair_id}/close", json={})
    assert second_close.status_code == 422
    assert second_close.json()["error"]["code"] == "REPAIR_ALREADY_CLOSED"

    history = await client.get(f"/api/v1/repairs/{repair_id}/assignment-history")
    assert history.status_code == 200
    entries = history.json()
    assert len(entries) == 1
    assert entries[0]["active_status"] is False
    assert entries[0]["ended_at"] is not None


# ---------------------------------------------------------------------------
# DEFECT A — API-level end-to-end (the exact live UAT reproduction).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_ends_active_assignment_end_to_end(client: AsyncClient) -> None:
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    assign = await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "dev-user", "collaborators": []},
    )
    assert assign.status_code == 200

    history_before = await client.get(f"/api/v1/repairs/{repair_id}/assignment-history")
    assert history_before.json()[0]["active_status"] is True
    assert history_before.json()[0]["ended_at"] is None

    close = await client.post(f"/api/v1/repairs/{repair_id}/close", json={})
    assert close.status_code == 200
    closed_body = close.json()["repair"]
    assert closed_body["status"] == "CLOSED"
    assert closed_body["closed_at"] is not None
    assert closed_body["closed_by"] == "dev-user"
    assert closed_body["closed_snapshot_id"] is not None

    history_after = await client.get(f"/api/v1/repairs/{repair_id}/assignment-history")
    assert history_after.status_code == 200
    entries = history_after.json()
    assert len(entries) == 1
    assert entries[0]["active_status"] is False
    assert entries[0]["ended_at"] is not None

    my_work = await client.get("/api/v1/repairs/my-work")
    assert repair_id not in [item["repair_id"] for item in my_work.json()["items"]]


# ---------------------------------------------------------------------------
# DEFECT B — awaiting_parts consistency across every RepairDetailResponse
# endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_repair_with_no_waiting_material_is_false(client: AsyncClient) -> None:
    """10. GET Repair with no waiting material state -> awaiting_parts = false."""
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]
    get_response = await client.get(f"/api/v1/repairs/{repair_id}")
    assert get_response.json()["awaiting_parts"] is False


@pytest.mark.asyncio
async def test_assign_response_awaiting_parts_matches_get(client: AsyncClient) -> None:
    """11. Assign response -> awaiting_parts equals GET result."""
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    assign_response = await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "dev-user", "collaborators": []},
    )
    assert assign_response.json()["awaiting_parts"] is not None
    get_response = await client.get(f"/api/v1/repairs/{repair_id}")
    assert assign_response.json()["awaiting_parts"] == get_response.json()["awaiting_parts"]


@pytest.mark.asyncio
async def test_add_action_response_awaiting_parts_matches_get(client: AsyncClient) -> None:
    """12. Add Action response -> awaiting_parts equals GET result."""
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    action_response = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "ตรวจสอบเบื้องต้น", "attachment_ids": []},
    )
    assert action_response.status_code == 200
    assert action_response.json()["awaiting_parts"] is not None
    get_response = await client.get(f"/api/v1/repairs/{repair_id}")
    assert action_response.json()["awaiting_parts"] == get_response.json()["awaiting_parts"]


@pytest.mark.asyncio
async def test_add_part_response_awaiting_parts_matches_get(client: AsyncClient) -> None:
    """13. Add Part response -> awaiting_parts equals GET result."""
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    part_response = await client.post(
        f"/api/v1/repairs/{repair_id}/parts",
        json={"part_description": "ปะเก็น (ทดสอบ)", "quantity": 1, "unit": "ชิ้น"},
    )
    assert part_response.status_code == 200
    assert part_response.json()["awaiting_parts"] is not None
    get_response = await client.get(f"/api/v1/repairs/{repair_id}")
    assert part_response.json()["awaiting_parts"] == get_response.json()["awaiting_parts"]


@pytest.mark.asyncio
async def test_close_response_awaiting_parts_matches_get(client: AsyncClient) -> None:
    """14. Close response -> awaiting_parts equals GET result."""
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    close_response = await client.post(f"/api/v1/repairs/{repair_id}/close", json={})
    assert close_response.status_code == 200
    assert close_response.json()["awaiting_parts"] is not None
    get_response = await client.get(f"/api/v1/repairs/{repair_id}")
    assert close_response.json()["awaiting_parts"] == get_response.json()["awaiting_parts"]
    # Current simple UAT case: nothing waits for parts.
    assert close_response.json()["awaiting_parts"] is False


@pytest.mark.asyncio
async def test_create_and_convert_responses_also_populate_awaiting_parts(
    client: AsyncClient,
) -> None:
    """Audit requirement: create/open Repair and convert Repair Request ->
    Repair must also produce a real (non-null) awaiting_parts, consistent
    with GET."""
    create_response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    assert create_response.json()["awaiting_parts"] is False

    rrq = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "ทดสอบ"},
    )
    repair_request_id = rrq.json()["request"]["repair_request_id"]
    convert_response = await client.post(
        f"/api/v1/repair-requests/{repair_request_id}/convert", json={}
    )
    assert convert_response.status_code == 200
    assert convert_response.json()["awaiting_parts"] is False
    converted_repair_id = convert_response.json()["repair"]["repair_id"]
    get_response = await client.get(f"/api/v1/repairs/{converted_repair_id}")
    assert convert_response.json()["awaiting_parts"] == get_response.json()["awaiting_parts"]

    # Preserve existing verified UAT behavior: RRQ -> Repair linkage.
    assert convert_response.json()["repair"]["source_type"] == "REPAIR_REQUEST"
    assert convert_response.json()["repair"]["source_id"] == repair_request_id


@pytest.mark.asyncio
async def test_waiting_parts_true_is_consistent_across_mutation_and_get(
    client: AsyncClient,
) -> None:
    """15. If there is an existing supported Waiting Parts/material-request
    state: mutation response must return true when GET returns true. Uses
    the existing Material Request / requisition semantics (Core Demo
    Fixes Delta section H) — never a fabricated rule."""
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
    )
    repair_id = repair.json()["repair"]["repair_id"]

    material_request = await client.post(
        "/api/v1/material-requests",
        json={
            "source_type": "REPAIR",
            "source_work_order_id": repair_id,
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "lines": [{"part_description": "สายพาน (ทดสอบ)", "quantity": 1, "unit": "เส้น"}],
        },
    )
    assert material_request.status_code == 200

    get_response = await client.get(f"/api/v1/repairs/{repair_id}")
    assert get_response.json()["awaiting_parts"] is True

    # A mutation response issued while still awaiting parts must agree.
    action_response = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "รออะไหล่", "attachment_ids": []},
    )
    assert action_response.status_code == 200
    assert action_response.json()["awaiting_parts"] is True

    # The repair record itself stays unduplicated/unaffected (Delta H).
    assert action_response.json()["repair"]["status"] == "OPEN"
