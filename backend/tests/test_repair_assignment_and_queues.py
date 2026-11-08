"""Core Demo Fixes — REPAIR WORKFLOW CORRECTIONS sections A (repair
identity) and C (assignment / technician work access).

Proves: a later repair occurrence always gets a new Repair ID (never
reuses a closed one), assignment (primary technician + collaborators) can
be set, "งานของฉัน" (My Work) shows only the current actor's OPEN assigned
repairs, and "งานซ่อมค้าง" (Open Repair Queue) lists every OPEN repair for
authorized use and excludes closed history.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.v2_http_assignment import (
    COLLABORATOR_USER,
    PRIMARY_USER,
    SEED_TECHNICIAN,
    assign_v2,
)


async def _create_repair(client: AsyncClient, vehicle_id: str = "VEH-1046") -> dict:
    response = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": vehicle_id, "source_type": "MANUAL"},
    )
    assert response.status_code == 200
    return response.json()["repair"]


@pytest.mark.asyncio
async def test_a_later_repair_occurrence_never_reuses_a_closed_repair_id(
    client: AsyncClient,
) -> None:
    first = await _create_repair(client)
    await client.post(f"/api/v1/repairs/{first['repair_id']}/close", json={})

    second = await _create_repair(client)
    assert second["repair_id"] != first["repair_id"]
    assert second["status"] == "OPEN"

    # The closed repair remains readable, unchanged, under its own ID.
    reread = await client.get(f"/api/v1/repairs/{first['repair_id']}")
    assert reread.json()["repair"]["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_assign_sets_primary_technician_and_collaborators(client: AsyncClient) -> None:
    """Legacy cancelled (DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107): the team is a V2 set."""
    repair = await _create_repair(client)
    written = await assign_v2(client, "repairs", repair["repair_id"], PRIMARY_USER, [COLLABORATOR_USER])
    assert written["current"]["primary_technician_id"] == SEED_TECHNICIAN[PRIMARY_USER]
    assert written["current"]["collaborator_technician_ids"] == [SEED_TECHNICIAN[COLLABORATOR_USER]]
    read = (await client.get(f"/api/v1/repairs/{repair['repair_id']}/technician-assignments")).json()
    assert read["current"]["assignment_set_id"] == written["current"]["assignment_set_id"]


@pytest.mark.asyncio
async def test_my_work_shows_only_current_actor_open_assigned_repairs(
    client: AsyncClient,
) -> None:
    """V2 My Work: only the actor's OPEN work orders of their current V2 sets."""
    mine = await _create_repair(client)
    await assign_v2(client, "repairs", mine["repair_id"], PRIMARY_USER)
    not_mine = await _create_repair(client)
    await assign_v2(client, "repairs", not_mine["repair_id"], COLLABORATOR_USER)
    # A repair closed after being assigned to me must not appear in My Work.
    mine_closed = await _create_repair(client)
    await assign_v2(client, "repairs", mine_closed["repair_id"], PRIMARY_USER)
    closed = await client.post(f"/api/v1/repairs/{mine_closed['repair_id']}/close", json={})
    assert closed.status_code == 200, closed.text

    response = await client.get("/api/v1/my-work", headers={"X-Dev-Role": "TECHNICIAN", "X-Dev-User-Id": PRIMARY_USER})
    assert response.status_code == 200
    ids = {item["job_id"] for item in response.json()["items"] or []}
    assert mine["repair_id"] in ids
    assert not_mine["repair_id"] not in ids
    assert mine_closed["repair_id"] not in ids


@pytest.mark.asyncio
async def test_open_repair_queue_lists_all_open_and_excludes_closed(client: AsyncClient) -> None:
    open_repair = await _create_repair(client)
    closed_repair = await _create_repair(client)
    await client.post(f"/api/v1/repairs/{closed_repair['repair_id']}/close", json={})

    response = await client.get("/api/v1/repairs/open-queue")
    assert response.status_code == 200
    ids = {item["repair_id"] for item in response.json()["items"]}
    assert open_repair["repair_id"] in ids
    assert closed_repair["repair_id"] not in ids
    assert all(item["status"] == "OPEN" for item in response.json()["items"])
