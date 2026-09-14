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
    repair = await _create_repair(client)
    response = await client.post(
        f"/api/v1/repairs/{repair['repair_id']}/assign",
        json={"primary_technician": "dev-user", "collaborators": ["tech-2"]},
    )
    assert response.status_code == 200
    updated = response.json()["repair"]
    assert updated["primary_technician"] == "dev-user"
    assert updated["collaborators"] == ["tech-2"]


@pytest.mark.asyncio
async def test_my_work_shows_only_current_actor_open_assigned_repairs(
    client: AsyncClient,
) -> None:
    mine = await _create_repair(client)
    await client.post(
        f"/api/v1/repairs/{mine['repair_id']}/assign",
        json={"primary_technician": "dev-user", "collaborators": []},
    )
    not_mine = await _create_repair(client)
    await client.post(
        f"/api/v1/repairs/{not_mine['repair_id']}/assign",
        json={"primary_technician": "someone-else", "collaborators": []},
    )
    # A repair closed after being assigned to me must not appear in My Work.
    mine_closed = await _create_repair(client)
    await client.post(
        f"/api/v1/repairs/{mine_closed['repair_id']}/assign",
        json={"primary_technician": "dev-user", "collaborators": []},
    )
    await client.post(f"/api/v1/repairs/{mine_closed['repair_id']}/close", json={})

    response = await client.get("/api/v1/repairs/my-work")
    assert response.status_code == 200
    ids = {item["repair_id"] for item in response.json()["items"]}
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
