"""REV06.1 — independent-audit CONSISTENCY-2 fix, migrated to Technician V2 only.

REV06.1 made Repair recording authorization follow the append-only assignment
history, never the denormalized `Repair.primary_technician`/`.collaborators`
display fields, so a stale or missing denormalized value could not authorize.

DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107 (Owner override): the Legacy
assignment runtime is cancelled. The same invariants are now proven for the V2
model — authority comes only from the job's CURRENT V2 set through the in-scope
User Account -> Personnel -> Technician chain — and the Legacy paths these
tests used to exercise are proven refused: the Legacy history view is retired
(410) and a historical Legacy job authorizes no recording for anyone (409),
whatever its denormalized fields or Legacy history rows say, in Mock and in
the Sheets transport.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.context import RequestContext
from app.domain import authz
from app.domain.asset import AssetType
from app.domain.meter_service import MeterService
from app.domain.repair import RepairSourceType
from app.domain.repair_service import RepairService
from app.domain.technician_assignment import REPAIR, TechnicianAssignmentService
from app.errors import ApiError
from tests.legacy_assignment_seed import (
    legacy_assign,
    legacy_queue,
    mark_historical_legacy,
    seed_historical_legacy_repair,
    seed_legacy_repair_assignment,
)
from tests.test_technician_assignment_batch_r2f_h1 import (
    API,
    T1,
    T2,
    T3,
    U1,
    U2,
    U3,
    assign,
    body,
    cut,
    http,
    new_repair,
    repo_with,
)
from tests.v2_only_support import mock_test_cutover


def _as(role: str, user_id: str = "dev-user") -> dict[str, str]:
    return {"X-Dev-Role": role, "X-Dev-User-Id": user_id}


def _ctx(user: str, *caps: str) -> RequestContext:
    return RequestContext(request_id="t", user_id=user, is_dev_auth=True, capabilities=frozenset(caps))


async def _is_member(repo, repair_id: str, user: str) -> bool:
    job = (await repo.get_repair(repair_id)).repair
    return await TechnicianAssignmentService(repo, cut()).is_current_member(REPAIR, job, user)


async def _record(repo, repair_id: str, user: str, *, role: str = "TECHNICIAN") -> int:
    response = await http("POST", f"{API}/repairs/{repair_id}/actions", repo, role=role, user=user,
                          json={"action_text": "ตรวจสอบ", "attachment_ids": []})
    return response.status_code


async def _recording_code(service: RepairService, repair_id: str, context: RequestContext) -> tuple[int, str]:
    with pytest.raises(ApiError) as exc:
        await service.authorize_recording(repair_id, context, authz.CAN_MANAGE_REPAIR, "test")
    return exc.value.status_code, exc.value.code


# ---------------------------------------------------------------------------
# 1-3 — assignment history invariants, at the V2 boundary authorization reads.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reassignment_ends_old_primary_but_preserves_history_row() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body(T1))
    await assign(repo, repair_id, body(T2, T3, expected=(T1,)))

    read = await TechnicianAssignmentService(repo, cut()).read(REPAIR, repair_id)
    assert len(read.state.sets) == 2  # the earlier set is kept, never edited or deleted
    assert read.state.current.primary_technician_id == T2
    assert list(read.state.current.collaborator_technician_ids) == [T3]
    assert [(r["assignment_role"], r["assignee_id"]) for r in repo._technician_assignment_rows["REPAIR"]] == [
        ("PRIMARY", T1), ("PRIMARY", T2), ("COLLABORATOR", T3)]
    assert not await _is_member(repo, repair_id, U1)
    assert await _is_member(repo, repair_id, U2) and await _is_member(repo, repair_id, U3)


@pytest.mark.asyncio
async def test_only_one_active_primary_at_a_time() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body(T1))
    await assign(repo, repair_id, body(T2, expected=(T1,)))

    read = await TechnicianAssignmentService(repo, cut()).read(REPAIR, repair_id)
    assert read.state.current.primary_technician_id == T2
    assert [await _is_member(repo, repair_id, user) for user in (U1, U2)] == [False, True]
    # A PRIMARY plus a collaborator naming the same technician is refused before any write.
    before = list(repo._technician_assignment_rows["REPAIR"])
    with pytest.raises(ApiError):
        await assign(repo, repair_id, body(T3, T3, expected=(T2,)))
    assert repo._technician_assignment_rows["REPAIR"] == before


@pytest.mark.asyncio
async def test_collaborator_unaffected_by_primary_reassignment() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body(T1, T3))
    await assign(repo, repair_id, body(T2, T3, expected=(T1, T3)))

    read = await TechnicianAssignmentService(repo, cut()).read(REPAIR, repair_id)
    assert read.state.current.primary_technician_id == T2
    assert list(read.state.current.collaborator_technician_ids) == [T3]
    assert await _is_member(repo, repair_id, U3)  # still a member of the current set
    assert not await _is_member(repo, repair_id, U1)


@pytest.mark.asyncio
async def test_legacy_assignment_history_view_is_retired_for_every_job(client: AsyncClient) -> None:
    """The Legacy history view these invariants were read from is cancelled (410), with nothing read."""
    for repair_id in ("RPR-ANY", "RPR-DOES-NOT-EXIST"):
        response = await client.get(f"/api/v1/repairs/{repair_id}/assignment-history", headers=_as("MAINTENANCE"))
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "LEGACY_ASSIGNMENT_RETIRED"


# ---------------------------------------------------------------------------
# 6-7 — the previous PRIMARY is denied, the new PRIMARY allowed (real HTTP gate).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ended_primary_cannot_add_action_new_primary_can() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body(T1))
    assert await _record(repo, repair_id, U1) == 200
    await assign(repo, repair_id, body(T2, expected=(T1,)))

    assert await _record(repo, repair_id, U1) == 403
    assert await _record(repo, repair_id, U2) == 200


# ---------------------------------------------------------------------------
# 8-9 — the denormalized display fields never authorize, stale or missing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_denormalized_assignee_alone_cannot_authorize() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body(T2))
    # The display field names someone else entirely (a stale or tampered value).
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(
        update={"primary_technician": U1, "collaborators": [U3]})

    assert await _record(repo, repair_id, U1) == 403
    assert await _record(repo, repair_id, U3) == 403
    assert await _record(repo, repair_id, U2) == 200


@pytest.mark.asyncio
async def test_missing_denormalized_field_does_not_break_history_derived_authorization() -> None:
    repo = repo_with()
    repair_id = await new_repair(repo)
    await assign(repo, repair_id, body(T2, T3))
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(
        update={"primary_technician": None, "collaborators": []})

    assert await _record(repo, repair_id, U2) == 200
    assert await _record(repo, repair_id, U3) == 200
    assert await _record(repo, repair_id, U1) == 403


@pytest.mark.asyncio
async def test_a_legacy_job_authorizes_nobody_whatever_its_fields_or_legacy_history_say() -> None:
    """Cancelled Legacy runtime: active Legacy history rows and the denormalized fields both name an
    assignee, yet nobody records on the job (409), a capability holder included, and nothing is written."""
    repo = repo_with()
    service = RepairService(repo, MeterService(repo), assignment_cutover=mock_test_cutover())
    repair_id = await seed_historical_legacy_repair(repo)
    await seed_legacy_repair_assignment(repair_id, U1, [U2], repo=repo)
    repo._repairs[repair_id] = repo._repairs[repair_id].model_copy(
        update={"primary_technician": U1, "collaborators": [U2]})
    actions_before = len((await repo.get_repair(repair_id)).actions)

    for context in (_ctx(U1), _ctx(U2), _ctx(U3), _ctx("manager-1", authz.CAN_MANAGE_REPAIR)):
        assert await _recording_code(service, repair_id, context) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert len((await repo.get_repair(repair_id)).actions) == actions_before
    assert repo._technician_assignment_rows["REPAIR"] == []


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
    # R2 Batch R2f-h4 B6 Rev2 (deliberate test migration): the retained LEGACY queue derivation is exercised on
    # the explicit historical-LEGACY fixture (every created job is V2 and is never in the legacy queue).
    mark_historical_legacy("repairs", repair_id)

    waiting = await legacy_queue(client, "/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE"))
    assert repair_id in {item["repair_id"] for item in waiting.json()["items"]}

    await legacy_assign(client, f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )
    waiting_after = await legacy_queue(client, "/api/v1/repairs/waiting-assignment", headers=_as("MAINTENANCE")
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
    await legacy_assign(client, f"/api/v1/repairs/{repair_id}/assign",
        json={"primary_technician": "tech-a", "collaborators": []},
        headers=_as("MAINTENANCE"),
    )

    my_work = await legacy_queue(client, "/api/v1/repairs/my-work", headers=_as("TECHNICIAN", "tech-a"))
    assert repair_id in {item["repair_id"] for item in my_work.json()["items"]}

    my_work_other = await legacy_queue(client, "/api/v1/repairs/my-work", headers=_as("TECHNICIAN", "tech-b")
    )
    assert repair_id not in {item["repair_id"] for item in my_work_other.json()["items"]}


# ---------------------------------------------------------------------------
# The same refusal against the real (fake-Sheets-backed) GoogleSheetsRepository
# — the split-brain the audit described was a Sheets-mode risk (two separate
# writes), so the Legacy refusal must hold on that transport too.
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
    service = RepairService(repo, MeterService(repo), assignment_cutover=mock_test_cutover())
    # A stored row with no V2 marker: a historical Legacy job on the Sheets transport.
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
    primary_col = repair_ws.header.index("primary_technician")
    for row in repair_ws.rows:
        if row[repair_ws.header.index("repair_id")] == repair.repair_id:
            row[primary_col] = "tech-stale"
    rows_before = [list(row) for row in repair_ws.rows]

    for context in (_ctx("tech-stale"), _ctx("tech-b"), _ctx("manager-1", authz.CAN_MANAGE_REPAIR)):
        assert await _recording_code(service, repair.repair_id, context) == (409, "ASSIGNMENT_MODEL_MISMATCH")
    assert repair_ws.rows == rows_before  # nothing written on the refused path
