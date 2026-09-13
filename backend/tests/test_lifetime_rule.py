"""Lifetime-rule abstraction tests (Phase 5;
OPEN_DECISIONS_REGISTER_EN.txt G01/G02).

Proves the rule STRUCTURE (trigger type, component-aware counter
reference, model-rule vs vehicle-override scope) is supported without any
seeded real interval/threshold, and that a rule must explicitly name its
counter/component relationship rather than guessing one.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

POSITION_LIFETIME_PART = "PART-0004"


@pytest.mark.asyncio
async def test_no_real_lifetime_interval_is_seeded_for_any_part(client: AsyncClient) -> None:
    response = await client.get("/api/v1/lifetime-rules", params={"part_id": POSITION_LIFETIME_PART})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_engine_hour_trigger_requires_explicit_component_role(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/lifetime-rules",
        json={
            "part_id": POSITION_LIFETIME_PART,
            "scope": "MODEL",
            "model_id": "MODEL-0002",
            "trigger_type": "ENGINE_HOUR",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_model_rule_created_with_explicit_component_role(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/lifetime-rules",
        json={
            "part_id": POSITION_LIFETIME_PART,
            "scope": "MODEL",
            "model_id": "MODEL-0002",
            "trigger_type": "ENGINE_HOUR",
            "component_role": "CRANE_ENGINE",
            "note": "ตัวอย่างสำหรับพัฒนา/ทดสอบ — ไม่มีค่าจริงจากแหล่งข้อมูลที่อนุมัติ",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lifetime_rule_id"].startswith("LTR-")
    assert body["component_role"] == "CRANE_ENGINE"
    # No real interval/threshold was fabricated.
    assert body["first_due_value"] is None
    assert body["interval_value"] is None
    assert body["warning_window_value"] is None

    reread = await client.get(f"/api/v1/lifetime-rules/{body['lifetime_rule_id']}")
    assert reread.json() == body


@pytest.mark.asyncio
async def test_vehicle_override_rule_requires_vehicle_id(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/lifetime-rules",
        json={
            "part_id": POSITION_LIFETIME_PART,
            "scope": "VEHICLE",
            "trigger_type": "CALENDAR",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_vehicle_override_rule_created(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/lifetime-rules",
        json={
            "part_id": POSITION_LIFETIME_PART,
            "scope": "VEHICLE",
            "vehicle_id": "VEH-1046",
            "trigger_type": "CALENDAR",
        },
    )
    assert response.status_code == 200
    assert response.json()["scope"] == "VEHICLE"
    assert response.json()["vehicle_id"] == "VEH-1046"


@pytest.mark.asyncio
async def test_lifetime_rule_rejects_unknown_part(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/lifetime-rules",
        json={
            "part_id": "PART-9999",
            "scope": "MODEL",
            "model_id": "MODEL-0002",
            "trigger_type": "CALENDAR",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PART_NOT_FOUND"
