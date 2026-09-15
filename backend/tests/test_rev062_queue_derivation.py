"""REV06.2 delta — final independent audit MEDIUM finding fix.

The REV06.1 audit found `Repository.list_repairs`'s `unassigned_only`
("Waiting Assignment"/รอมอบหมายช่าง) and `assigned_to` ("My Work"/
งานของฉัน) filters read the denormalized `Repair.primary_technician`/
`.collaborators` fields directly — the same fields REV06.1 already proved
can go stale relative to active `repair_assignment` history (since
`assign_repair` writes history first and the denormalized fields second,
two separate non-transactional writes). Repair action/part *authorization*
was fixed in REV06.1 to read history instead; these two *queues* were not,
so they could show the wrong repairs under the exact same partial-write
window REV06.1 already reproduces for authorization.

These tests reproduce that same corrupted state directly against the
repository (bypassing `assign_repair`, exactly like
`test_rev061_assignment_authority.py::test_stale_denormalized_assignee_alone_cannot_authorize`)
and prove `list_repairs` now agrees with `RepairService.get_active_assignment`
rather than the corrupted denormalized field, in both MockRepository and
the fake-Sheets-backed GoogleSheetsRepository.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.domain.meter_service import MeterService
from app.domain.repair import RepairSourceType, RepairStatus
from app.domain.repair_service import RepairService
from app.repositories.mock import MockRepository


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


async def _open_repair(service: RepairService, vehicle_id: str = "VEH-1046"):
    return await service.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id=vehicle_id,
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom="ทดสอบ",
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )


_PAGE = PageParams(page=1, page_size=50)


# ---------------------------------------------------------------------------
# Waiting Assignment — Scenario A: repair row says a technician is
# assigned, but the corresponding PRIMARY assignment row is ended/inactive.
# Correct: the repair MUST appear (no active PRIMARY).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waiting_assignment_scenario_a_stale_assigned_field_but_ended_primary() -> None:
    repo = MockRepository()
    service = RepairService(repo, MeterService(repo))
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-a", collaborators=[])
    # End the PRIMARY assignment (reassign to nobody) so history has no
    # active PRIMARY row...
    await service.assign(repair_id, primary_technician=None, collaborators=[])
    # ...then corrupt the denormalized field back to looking assigned,
    # simulating the exact partial-write window `assign_repair` cannot
    # make atomic against Google Sheets.
    stale = repo._repairs[repair_id].model_copy(update={"primary_technician": "tech-a"})
    repo._repairs[repair_id] = stale

    items, _total = await repo.list_repairs(
        asset_type=None,
        asset_id=None,
        status=RepairStatus.OPEN,
        params=_PAGE,
        unassigned_only=True,
    )
    assert repair_id in {r.repair_id for r in items}


# ---------------------------------------------------------------------------
# Waiting Assignment — Scenario B: repair row has a blank/stale
# `primary_technician`, but an active PRIMARY assignment exists in history.
# Correct: the repair must NOT appear.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waiting_assignment_scenario_b_blank_field_but_active_primary() -> None:
    repo = MockRepository()
    service = RepairService(repo, MeterService(repo))
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-b", collaborators=[])
    # Corrupt the denormalized field to blank, without touching history.
    stale = repo._repairs[repair_id].model_copy(update={"primary_technician": None})
    repo._repairs[repair_id] = stale

    items, _total = await repo.list_repairs(
        asset_type=None,
        asset_id=None,
        status=RepairStatus.OPEN,
        params=_PAGE,
        unassigned_only=True,
    )
    assert repair_id not in {r.repair_id for r in items}


# ---------------------------------------------------------------------------
# Waiting Assignment — Scenario C: OPEN, no PRIMARY, but an active
# COLLABORATOR. Correct: still appears (a collaborator is not a PRIMARY).
# Achievable through the real API (no corruption needed).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waiting_assignment_scenario_c_collaborator_only_still_waiting(
    client: AsyncClient,
) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]
    await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": None, "collaborators": ["tech-c"]},
        headers=_as("MAINTENANCE"),
    )

    waiting = await client.get(
        "/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE")
    )
    assert repair_id in {item["repair_id"] for item in waiting.json()["items"]}


# ---------------------------------------------------------------------------
# Waiting Assignment — Scenario D: CLOSED repair with no PRIMARY must NOT
# appear (the OPEN-status filter already excludes it; this proves the
# unassigned_only fix does not accidentally widen the status filter).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waiting_assignment_scenario_d_closed_repair_excluded(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]
    await client.post(
        f"/api/v1/repairs/{repair_id}/close",
        json={"close_note": "ปิดงาน"},
        headers=_as("MAINTENANCE"),
    )

    waiting = await client.get(
        "/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE")
    )
    assert repair_id not in {item["repair_id"] for item in waiting.json()["items"]}


# ---------------------------------------------------------------------------
# My Work — active PRIMARY/COLLABORATOR must appear even when the
# denormalized field is stale/blank; an ended assignment must not appear
# merely because the denormalized field still names that technician.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_work_active_primary_appears_even_with_blank_denormalized_field() -> None:
    repo = MockRepository()
    service = RepairService(repo, MeterService(repo))
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-z", collaborators=[])
    stale = repo._repairs[repair_id].model_copy(update={"primary_technician": None})
    repo._repairs[repair_id] = stale

    items, _total = await repo.list_repairs(
        asset_type=None, asset_id=None, status=None, params=_PAGE, assigned_to="tech-z"
    )
    assert repair_id in {r.repair_id for r in items}


@pytest.mark.asyncio
async def test_my_work_active_collaborator_appears(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]
    await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": ["tech-collab"]},
        headers=_as("MAINTENANCE"),
    )

    my_work = await client.get(
        "/api/v1/repairs/my-work", headers=_as("TECHNICIAN", "tech-collab")
    )
    assert repair_id in {item["repair_id"] for item in my_work.json()["items"]}


@pytest.mark.asyncio
async def test_my_work_ended_primary_does_not_appear_despite_stale_denormalized_field() -> None:
    repo = MockRepository()
    service = RepairService(repo, MeterService(repo))
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-w", collaborators=[])
    # End tech-w's assignment (reassign to someone else) so history no
    # longer has an active row for tech-w...
    await service.assign(repair_id, primary_technician="tech-other", collaborators=[])
    # ...then corrupt the denormalized field back to naming tech-w, as if
    # the second (denormalized-sync) write of that reassignment had failed.
    stale = repo._repairs[repair_id].model_copy(update={"primary_technician": "tech-w"})
    repo._repairs[repair_id] = stale

    items, _total = await repo.list_repairs(
        asset_type=None, asset_id=None, status=None, params=_PAGE, assigned_to="tech-w"
    )
    assert repair_id not in {r.repair_id for r in items}


@pytest.mark.asyncio
async def test_my_work_ended_collaborator_does_not_appear() -> None:
    repo = MockRepository()
    service = RepairService(repo, MeterService(repo))
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-a", collaborators=["tech-collab"])
    # Remove tech-collab from the active collaborator set.
    await service.assign(repair_id, primary_technician="tech-a", collaborators=[])

    items, _total = await repo.list_repairs(
        asset_type=None, asset_id=None, status=None, params=_PAGE, assigned_to="tech-collab"
    )
    assert repair_id not in {r.repair_id for r in items}


# ---------------------------------------------------------------------------
# Same fix proven against the real (fake-Sheets-backed) GoogleSheetsRepository
# — the split-brain is a Sheets-mode-specific risk (two separate writes),
# so the fix must hold there too, not only in Mock.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waiting_assignment_and_my_work_honor_history_in_sheets_mode() -> None:
    from app.repositories.google_sheets import schemas
    from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws

    repair_ws = _ws(schemas.REPAIR_SHEET)
    repo = _repo_with_fake_sheets(
        repair_ws,
        _ws(schemas.REPAIR_ACTION_SHEET),
        _ws(schemas.REPAIR_PART_SHEET),
        _ws(schemas.REPAIR_ASSIGNMENT_SHEET),
    )
    service = RepairService(repo, MeterService(repo))
    repair = await repo.create_repair(
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-9001",
        source_type=RepairSourceType.MANUAL,
        source_id=None,
        category=None,
        symptom=None,
        meter_snapshot_id=None,
        opened_by="user-maintenance",
    )
    await repo.assign_repair(
        repair_id=repair.repair_id, primary_technician="tech-b", collaborators=[], assigned_by="m"
    )

    # Corrupt the repair_order row's own primary_technician cell directly,
    # without touching repair_assignment history — the exact partial-write
    # window a real Sheets failure between the two writes would leave.
    primary_col = repair_ws.header.index("primary_technician")
    for row in repair_ws.rows:
        if row[repair_ws.header.index("repair_id")] == repair.repair_id:
            row[primary_col] = "tech-stale"

    # Waiting Assignment: history says tech-b IS active PRIMARY, so this
    # repair must NOT be in the unassigned queue despite the corrupted
    # empty-looking... (here: mismatched) denormalized cell.
    waiting_items, _ = await repo.list_repairs(
        asset_type=None,
        asset_id=None,
        status=RepairStatus.OPEN,
        params=_PAGE,
        unassigned_only=True,
    )
    assert repair.repair_id not in {r.repair_id for r in waiting_items}

    # My Work for the stale name must NOT include this repair.
    stale_name_items, _ = await repo.list_repairs(
        asset_type=None, asset_id=None, status=None, params=_PAGE, assigned_to="tech-stale"
    )
    assert repair.repair_id not in {r.repair_id for r in stale_name_items}

    # My Work for the real, history-active technician must include it.
    real_items, _ = await repo.list_repairs(
        asset_type=None, asset_id=None, status=None, params=_PAGE, assigned_to="tech-b"
    )
    assert repair.repair_id in {r.repair_id for r in real_items}
