"""REV06.1 — independent-audit CONSISTENCY-2 fix.

The REV06 independent audit found a split-brain risk between the
append-only `repair_assignment` history (which `assign_repair` writes
first) and the denormalized `Repair.primary_technician`/`.collaborators`
fields (written second, as a separate call) that
`require_assignment_or_capability` used to authorize `POST
/repairs/{id}/actions` and `POST /repairs/{id}/parts`. Since Google
Sheets is non-transactional, a failure between the two writes could leave
the denormalized fields stale relative to the real, active assignment.

`RepairService.get_active_assignment` now derives the active PRIMARY/
COLLABORATORs directly from the assignment history's currently-active
rows, and `repairs.py`'s action/part routes use it instead of
`Repair.primary_technician`/`.collaborators` — those two fields remain on
`Repair` for display only. These tests prove authorization tracks history
even when the denormalized fields are stale, missing, or simply out of
sync — a state deliberately induced here by writing to the repository
directly (bypassing `assign_repair`) to simulate exactly the partial
failure the audit described.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from app.domain.meter_service import MeterService
from app.domain.repair import RepairSourceType
from app.domain.repair_service import RepairService
from app.repositories.mock import MockRepository


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


async def _make_repair_service() -> RepairService:
    repo = MockRepository()
    return RepairService(repo, MeterService(repo))


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


# ---------------------------------------------------------------------------
# 1-5 — assignment history invariants (regression guard; already covered
# elsewhere for the repository layer, restated here at the domain-service
# boundary that authorization actually reads from).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reassignment_ends_old_primary_but_preserves_history_row() -> None:
    service = await _make_repair_service()
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-a", collaborators=[])
    await service.assign(repair_id, primary_technician="tech-b", collaborators=["tech-c"])

    history = await service.list_assignment_history(repair_id)
    tech_a_rows = [e for e in history if e.user_id == "tech-a"]
    assert len(tech_a_rows) == 1
    assert tech_a_rows[0].active_status is False
    assert tech_a_rows[0].ended_at is not None

    tech_b_rows = [e for e in history if e.user_id == "tech-b"]
    assert tech_b_rows[0].active_status is True

    primary, collaborators = await service.get_active_assignment(repair_id)
    assert primary == "tech-b"
    assert collaborators == ["tech-c"]


@pytest.mark.asyncio
async def test_only_one_active_primary_at_a_time() -> None:
    service = await _make_repair_service()
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-a", collaborators=[])
    await service.assign(repair_id, primary_technician="tech-b", collaborators=[])

    history = await service.list_assignment_history(repair_id)
    active_primaries = [
        e for e in history if e.active_status and e.assignment_role.value == "PRIMARY"
    ]
    assert len(active_primaries) == 1
    assert active_primaries[0].user_id == "tech-b"


@pytest.mark.asyncio
async def test_collaborator_unaffected_by_primary_reassignment() -> None:
    service = await _make_repair_service()
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-a", collaborators=["tech-helper"])
    await service.assign(repair_id, primary_technician="tech-b", collaborators=["tech-helper"])

    primary, collaborators = await service.get_active_assignment(repair_id)
    assert primary == "tech-b"
    assert collaborators == ["tech-helper"]
    history = await service.list_assignment_history(repair_id)
    helper_rows = [e for e in history if e.user_id == "tech-helper"]
    # A single still-active row, never ended/re-created by the reassignment.
    assert len(helper_rows) == 1
    assert helper_rows[0].active_status is True


# ---------------------------------------------------------------------------
# 6-7 — ended PRIMARY denied, new PRIMARY allowed (via the real HTTP
# authorization gate).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ended_primary_cannot_add_action_new_primary_can(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]

    await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "tech-b", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    denied = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "ตรวจสอบ", "attachment_ids": []},
        headers=_as("TECHNICIAN", "tech-a"),
    )
    assert denied.status_code == 403

    allowed = await client.post(
        f"/api/v1/repairs/{repair_id}/actions",
        json={"action_text": "ตรวจสอบ", "attachment_ids": []},
        headers=_as("TECHNICIAN", "tech-b"),
    )
    assert allowed.status_code == 200


# ---------------------------------------------------------------------------
# 8 — a stale denormalized `Repair.primary_technician` alone cannot
# authorize, once it disagrees with the real, active assignment history.
# Simulated by writing directly to the repository (bypassing
# `assign_repair`) to reproduce the exact partial-failure the audit
# described: history says the new technician is active, but the
# denormalized field on the Repair row was never updated.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_denormalized_assignee_alone_cannot_authorize() -> None:
    repo = MockRepository()
    service = RepairService(repo, MeterService(repo))
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    # Real assignment: tech-b is the active PRIMARY per history.
    await service.assign(repair_id, primary_technician="tech-b", collaborators=[])

    # Simulate the exact partial-failure window: the denormalized
    # `Repair.primary_technician` field is corrupted/rolled back to a
    # stale name directly, without touching assignment history at all.
    stale_repair = repo._repairs[repair_id].model_copy(
        update={"primary_technician": "tech-stale", "collaborators": []}
    )
    repo._repairs[repair_id] = stale_repair

    # Authorization must come from history, not the corrupted field.
    primary, collaborators = await service.get_active_assignment(repair_id)
    assert primary == "tech-b"
    assert collaborators == []

    from app.context import RequestContext
    from app.domain.authz import CAN_MANAGE_REPAIR, require_assignment_or_capability

    # The stale name in the denormalized field must NOT be authorized.
    with pytest.raises(Exception):
        require_assignment_or_capability(
            RequestContext(request_id="t", user_id="tech-stale", capabilities=frozenset()),
            CAN_MANAGE_REPAIR,
            primary,
            collaborators,
            "test",
        )
    # The real, history-active technician must be authorized.
    require_assignment_or_capability(
        RequestContext(request_id="t", user_id="tech-b", capabilities=frozenset()),
        CAN_MANAGE_REPAIR,
        primary,
        collaborators,
        "test",
    )


# ---------------------------------------------------------------------------
# 9 — a missing/None denormalized field does not break assignment-derived
# authorization: history alone is sufficient.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_denormalized_field_does_not_break_history_derived_authorization() -> None:
    repo = MockRepository()
    service = RepairService(repo, MeterService(repo))
    detail = await _open_repair(service)
    repair_id = detail.repair.repair_id

    await service.assign(repair_id, primary_technician="tech-b", collaborators=["tech-c"])

    # Wipe the denormalized fields entirely (as if that write never
    # happened at all), leaving history as the only record.
    wiped_repair = repo._repairs[repair_id].model_copy(
        update={"primary_technician": None, "collaborators": []}
    )
    repo._repairs[repair_id] = wiped_repair

    primary, collaborators = await service.get_active_assignment(repair_id)
    assert primary == "tech-b"
    assert collaborators == ["tech-c"]


# ---------------------------------------------------------------------------
# 10-11 — Waiting Assignment / My Work remain derived from the (in normal
# operation, always-in-sync) denormalized fields, documented explicitly
# as such — this is a regression guard, not a change in REV06.1.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waiting_assignment_reflects_no_active_primary(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]

    waiting = await client.get("/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE"))
    assert repair_id in {item["repair_id"] for item in waiting.json()["items"]}

    await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    waiting_after = await client.get(
        "/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE")
    )
    assert repair_id not in {item["repair_id"] for item in waiting_after.json()["items"]}


@pytest.mark.asyncio
async def test_my_work_reflects_active_assignment(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"},
        headers=_as("MAINTENANCE"),
    )
    repair_id = create.json()["repair"]["repair_id"]
    await client.post(
        f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    my_work = await client.get("/api/v1/repairs/my-work", headers=_as("TECHNICIAN", "tech-a"))
    assert repair_id in {item["repair_id"] for item in my_work.json()["items"]}

    my_work_other = await client.get(
        "/api/v1/repairs/my-work", headers=_as("TECHNICIAN", "tech-b")
    )
    assert repair_id not in {item["repair_id"] for item in my_work_other.json()["items"]}


# ---------------------------------------------------------------------------
# Same fix, proven against the real (fake-Sheets-backed) GoogleSheetsRepository
# — the split-brain the audit described is a Sheets-mode-specific risk
# (two separate writes), so the fix must hold there too, not only in Mock.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_denormalized_assignee_cannot_authorize_in_sheets_mode() -> None:
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
        repair_id=repair.repair_id,
        primary_technician="tech-b",
        collaborators=[],
        assigned_by="user-maintenance",
    )

    # Simulate the exact partial-failure the audit described: the
    # `repair_order` row's own `primary_technician` cell is corrupted back
    # to a stale name directly (as if that second write had failed or been
    # rolled back), without touching `repair_assignment` history at all.
    primary_col = repair_ws.header.index("primary_technician")
    for row in repair_ws.rows:
        if row[repair_ws.header.index("repair_id")] == repair.repair_id:
            row[primary_col] = "tech-stale"

    primary, collaborators = await service.get_active_assignment(repair.repair_id)
    assert primary == "tech-b"
    assert collaborators == []

    from app.context import RequestContext
    from app.domain.authz import CAN_MANAGE_REPAIR, require_assignment_or_capability

    with pytest.raises(Exception):
        require_assignment_or_capability(
            RequestContext(request_id="t", user_id="tech-stale", capabilities=frozenset()),
            CAN_MANAGE_REPAIR,
            primary,
            collaborators,
            "test",
        )
    require_assignment_or_capability(
        RequestContext(request_id="t", user_id="tech-b", capabilities=frozenset()),
        CAN_MANAGE_REPAIR,
        primary,
        collaborators,
        "test",
    )
