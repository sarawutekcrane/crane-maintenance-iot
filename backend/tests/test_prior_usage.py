"""Prior-usage quality tests (Phase 5; baseline §12).

Proves KNOWN / PARTIAL / UNKNOWN are all supported and that UNKNOWN never
becomes (or is displayed as) `0`, for both PartInstance and
PositionLifetimeRecord enrollment.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

INSTANCE_TRACKED_PART = "PART-0005"
POSITION_LIFETIME_PART = "PART-0004"


@pytest.mark.asyncio
async def test_instance_prior_usage_known_supported(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/part-instances",
        json={
            "part_id": INSTANCE_TRACKED_PART,
            "prior_usage": {"quality": "KNOWN", "value": 480.5, "note": "จากบันทึกเดิม"},
        },
    )
    assert response.status_code == 200
    assert response.json()["instance"]["prior_usage"] == {
        "quality": "KNOWN",
        "value": 480.5,
        "note": "จากบันทึกเดิม",
    }


@pytest.mark.asyncio
async def test_instance_prior_usage_partial_supported(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/part-instances",
        json={
            "part_id": INSTANCE_TRACKED_PART,
            "prior_usage": {
                "quality": "PARTIAL",
                "value": 100.0,
                "note": "ทราบเฉพาะช่วงหลังปี 2568 เท่านั้น ก่อนหน้านั้นไม่มีข้อมูล",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()["instance"]["prior_usage"]
    assert body["quality"] == "PARTIAL"
    assert body["value"] == 100.0
    assert "ไม่มีข้อมูล" in body["note"]


@pytest.mark.asyncio
async def test_instance_prior_usage_unknown_never_becomes_zero(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/part-instances",
        json={"part_id": INSTANCE_TRACKED_PART, "prior_usage": {"quality": "UNKNOWN"}},
    )
    assert response.status_code == 200
    body = response.json()["instance"]["prior_usage"]
    assert body["quality"] == "UNKNOWN"
    assert body["value"] is None

    instance_id = response.json()["instance"]["part_instance_id"]
    reread = await client.get(f"/api/v1/part-instances/{instance_id}")
    assert reread.json()["instance"]["prior_usage"]["value"] is None


@pytest.mark.asyncio
async def test_instance_prior_usage_unknown_rejects_a_supplied_value_being_required(
    client: AsyncClient,
) -> None:
    """UNKNOWN with no value is accepted and stored as `None` — the value
    field is never defaulted to 0 even though it was omitted."""
    response = await client.post(
        "/api/v1/part-instances",
        json={"part_id": INSTANCE_TRACKED_PART, "prior_usage": {"quality": "UNKNOWN", "value": None}},
    )
    assert response.status_code == 200
    assert response.json()["instance"]["prior_usage"]["value"] is None


@pytest.mark.asyncio
async def test_position_lifetime_prior_usage_unknown_never_becomes_zero(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/position-lifetime",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "position_code": "BOOM-CYL-1",
            "part_id": POSITION_LIFETIME_PART,
            "prior_usage": {"quality": "UNKNOWN"},
        },
    )
    assert response.status_code == 200
    assert response.json()["prior_usage"] == {"quality": "UNKNOWN", "value": None, "note": None}
