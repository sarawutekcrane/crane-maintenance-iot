"""Part Master / tracking-mode / Part Set revision tests (Phase 5).

Proves: all four tracking modes are distinct concepts, a different
specification always gets a different part_id even with the same display
name, and a later Part Set revision never rewrites an earlier one.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_seeded_parts_cover_every_tracking_mode(client: AsyncClient) -> None:
    response = await client.get("/api/v1/parts", params={"page_size": 50})
    assert response.status_code == 200
    modes = {p["tracking_mode"] for p in response.json()["items"]}
    assert modes == {"NONE", "CONSUMABLE", "POSITION_LIFETIME", "INSTANCE_TRACKED"}


@pytest.mark.asyncio
async def test_same_display_name_different_specification_gets_different_part_id(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/parts", params={"q": "ไส้กรองน้ำมันเครื่อง"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    part_ids = {p["part_id"] for p in items}
    specs = {p["specification"] for p in items}
    assert len(part_ids) == 2
    assert specs == {"ขนาด A", "ขนาด B"}


@pytest.mark.asyncio
async def test_create_part_master_on_demand(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/parts",
        json={
            "part_code": "TEST-BEARING-01",
            "name": "ตลับลูกปืนทดสอบ",
            "specification": "50mm",
            "tracking_mode": "CONSUMABLE",
            "category": "BEARING",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["part_id"].startswith("PART-")
    assert body["is_active"] is True
    assert body["tracking_mode"] == "CONSUMABLE"

    reread = await client.get(f"/api/v1/parts/{body['part_id']}")
    assert reread.status_code == 200
    assert reread.json() == body


@pytest.mark.asyncio
async def test_get_unknown_part_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/parts/PART-9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PART_NOT_FOUND"


@pytest.mark.asyncio
async def test_part_set_revision_requires_valid_part_ids(client: AsyncClient) -> None:
    part_set = await client.post(
        "/api/v1/part-sets", json={"set_code": "KIT-TEST", "name": "ชุดอะไหล่ทดสอบ"}
    )
    assert part_set.status_code == 200
    part_set_id = part_set.json()["part_set_id"]

    response = await client.post(
        f"/api/v1/part-sets/{part_set_id}/revisions",
        json={
            "effective_date": "2026-01-01",
            "items": [{"part_id": "PART-9999", "requirement": "REQUIRED"}],
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PART_NOT_FOUND"


@pytest.mark.asyncio
async def test_part_set_revision_supports_required_optional_alternative(
    client: AsyncClient,
) -> None:
    part_set = await client.post(
        "/api/v1/part-sets", json={"set_code": "KIT-TEST-2", "name": "ชุดอะไหล่ทดสอบ 2"}
    )
    part_set_id = part_set.json()["part_set_id"]

    response = await client.post(
        f"/api/v1/part-sets/{part_set_id}/revisions",
        json={
            "effective_date": "2026-01-01",
            "items": [
                {"part_id": "PART-0002", "requirement": "REQUIRED", "quantity": 1, "unit": "ชิ้น"},
                {"part_id": "PART-0003", "requirement": "ALTERNATIVE"},
                {"part_id": "PART-0001", "requirement": "OPTIONAL"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    requirements = {item["part_id"]: item["requirement"] for item in body["items"]}
    assert requirements == {
        "PART-0002": "REQUIRED",
        "PART-0003": "ALTERNATIVE",
        "PART-0001": "OPTIONAL",
    }

    active = await client.get(f"/api/v1/part-sets/{part_set_id}/active-revision")
    assert active.status_code == 200
    assert active.json() == body


@pytest.mark.asyncio
async def test_later_part_set_revision_does_not_rewrite_earlier_one(client: AsyncClient) -> None:
    part_set = await client.post(
        "/api/v1/part-sets", json={"set_code": "KIT-TEST-3", "name": "ชุดอะไหล่ทดสอบ 3"}
    )
    part_set_id = part_set.json()["part_set_id"]

    first = await client.post(
        f"/api/v1/part-sets/{part_set_id}/revisions",
        json={
            "effective_date": "2026-01-01",
            "items": [{"part_id": "PART-0002", "requirement": "REQUIRED"}],
        },
    )
    first_revision_id = first.json()["revision"]["revision_id"]

    second = await client.post(
        f"/api/v1/part-sets/{part_set_id}/revisions",
        json={
            "effective_date": "2026-02-01",
            "items": [{"part_id": "PART-0003", "requirement": "REQUIRED"}],
        },
    )
    assert second.status_code == 200
    assert second.json()["revision"]["revision_number"] == 2

    # The first revision's own items are still readable and unchanged.
    reread_first = await client.get(f"/api/v1/part-sets/{part_set_id}/revisions/{first_revision_id}")
    assert reread_first.status_code == 200
    assert reread_first.json()["items"][0]["part_id"] == "PART-0002"

    active = await client.get(f"/api/v1/part-sets/{part_set_id}/active-revision")
    assert active.json()["revision"]["revision_id"] != first_revision_id
