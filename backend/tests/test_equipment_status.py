"""Tests for the Phase 2 verification correction (decision C02) and its
Core Demo Fixes extension (EQUIPMENT STATUS CHANGE — APPROVED).

Equipment must use its own approved status vocabulary
(`EquipmentOperationalStatus`: READY, IN_USE, MAINTENANCE, OUT_OF_SERVICE,
RETIRED) instead of reusing Vehicle's `OperationalStatus`
(WORKING, READY, MAINTENANCE, OUT_OF_SERVICE, LONG_TERM_PARKING).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.domain.common import OperationalStatus
from app.domain.equipment import Equipment, EquipmentCategory, EquipmentOperationalStatus

_NOW = datetime(2026, 1, 15, 8, 0, 0, tzinfo=timezone.utc)


def _build_equipment(status: str) -> Equipment:
    return Equipment(
        equipment_id="EQP-TEST",
        equipment_code="TEST-01",
        name="ทดสอบ",
        category=EquipmentCategory.OTHER,
        serial_number=None,
        location=None,
        operational_status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.parametrize(
    "status",
    [
        EquipmentOperationalStatus.READY,
        EquipmentOperationalStatus.IN_USE,
        EquipmentOperationalStatus.MAINTENANCE,
        EquipmentOperationalStatus.OUT_OF_SERVICE,
        EquipmentOperationalStatus.RETIRED,
    ],
)
def test_equipment_accepts_each_approved_status(status: EquipmentOperationalStatus) -> None:
    equipment = _build_equipment(status.value)
    assert equipment.operational_status == status


@pytest.mark.parametrize("vehicle_only_status", ["WORKING", "LONG_TERM_PARKING"])
def test_equipment_rejects_vehicle_only_statuses(vehicle_only_status: str) -> None:
    with pytest.raises(ValidationError):
        _build_equipment(vehicle_only_status)


def test_equipment_and_vehicle_status_enums_are_distinct_vocabularies() -> None:
    equipment_values = {s.value for s in EquipmentOperationalStatus}
    vehicle_values = {s.value for s in OperationalStatus}

    assert equipment_values == {"READY", "IN_USE", "MAINTENANCE", "OUT_OF_SERVICE", "RETIRED"}
    assert vehicle_values == {
        "WORKING",
        "READY",
        "MAINTENANCE",
        "OUT_OF_SERVICE",
        "LONG_TERM_PARKING",
    }
    # Equipment must not gain WORKING/LONG_TERM_PARKING, and must not lose
    # any vehicle-shared-looking value it legitimately keeps (READY,
    # MAINTENANCE, OUT_OF_SERVICE are coincidentally spelled the same in
    # both vocabularies but are two separate enums, not a shared type).
    assert "WORKING" not in equipment_values
    assert "LONG_TERM_PARKING" not in equipment_values
    assert "IN_USE" not in vehicle_values
    assert "RETIRED" not in vehicle_values


@pytest.mark.asyncio
async def test_seeded_equipment_only_uses_approved_statuses(client: AsyncClient) -> None:
    response = await client.get("/api/v1/equipment", params={"page_size": 200})
    assert response.status_code == 200
    body = response.json()
    approved = {"READY", "IN_USE", "MAINTENANCE", "OUT_OF_SERVICE", "RETIRED"}
    for item in body["items"]:
        assert item["operational_status"] in approved


@pytest.mark.asyncio
async def test_vehicle_status_vocabulary_unchanged(client: AsyncClient) -> None:
    """Vehicle status behavior/vocabulary must be unaffected by the
    equipment status correction: LONG_TERM_PARKING (a vehicle-only value,
    now deliberately absent from equipment) must still work for vehicles.
    """
    response = await client.patch(
        "/api/v1/vehicles/VEH-1046/status",
        json={"status": "LONG_TERM_PARKING", "note": "ทดสอบสถานะรถ"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle"]["operational_status"] == "LONG_TERM_PARKING"
    assert body["history_entry"]["status"] == "LONG_TERM_PARKING"

    # WORKING must still be valid for vehicles too (proves the vehicle
    # enum itself was not narrowed by this correction).
    response = await client.patch(
        "/api/v1/vehicles/VEH-1046/status",
        json={"status": "WORKING"},
    )
    assert response.status_code == 200
    assert response.json()["vehicle"]["operational_status"] == "WORKING"


@pytest.mark.asyncio
async def test_equipment_status_field_rejects_vehicle_only_value_via_api(
    client: AsyncClient,
) -> None:
    """There is no equipment status-write endpoint in Phase 2, so the
    rejection is proven at the response-model level: a hand-built
    equipment-shaped payload using a vehicle-only status must fail
    validation rather than silently pass through, guarding against a
    future write endpoint being added without enforcing the vocabulary.
    """
    from app.api.v1.equipment_schemas import EquipmentResponse

    valid = EquipmentResponse.model_validate(
        {
            "equipment_id": "EQP-0001",
            "equipment_code": "LATHE-01",
            "name": "เครื่องกลึงเบอร์ 1",
            "category": "LATHE",
            "serial_number": None,
            "location": None,
            "operational_status": "IN_USE",
            "created_at": _NOW,
            "updated_at": _NOW,
        }
    )
    assert valid.operational_status == EquipmentOperationalStatus.IN_USE

    with pytest.raises(ValidationError):
        EquipmentResponse.model_validate(
            {
                "equipment_id": "EQP-0001",
                "equipment_code": "LATHE-01",
                "name": "เครื่องกลึงเบอร์ 1",
                "category": "LATHE",
                "serial_number": None,
                "location": None,
                "operational_status": "WORKING",
                "created_at": _NOW,
                "updated_at": _NOW,
            }
        )


@pytest.mark.asyncio
async def test_change_equipment_status_appends_history_with_reason_actor_timestamp(
    client: AsyncClient,
) -> None:
    equipment_id = "EQP-0001"
    response = await client.post(
        f"/api/v1/equipment/{equipment_id}/status",
        json={"status": "MAINTENANCE", "reason": "ตรวจสอบตามรอบ"},
    )
    assert response.status_code == 200
    assert response.json()["operational_status"] == "MAINTENANCE"

    history = await client.get(f"/api/v1/equipment/{equipment_id}/status-history")
    assert history.status_code == 200
    entries = history.json()
    assert len(entries) == 1
    assert entries[0]["status"] == "MAINTENANCE"
    assert entries[0]["reason"] == "ตรวจสอบตามรอบ"
    assert entries[0]["changed_by"] is not None
    assert entries[0]["changed_at"] is not None

    # A second change appends, never overwrites, the first entry.
    await client.post(
        f"/api/v1/equipment/{equipment_id}/status",
        json={"status": "RETIRED", "reason": "ปลดระวางถาวร"},
    )
    history_after = (await client.get(f"/api/v1/equipment/{equipment_id}/status-history")).json()
    assert len(history_after) == 2
    assert history_after[0]["status"] == "MAINTENANCE"
    assert history_after[1]["status"] == "RETIRED"


@pytest.mark.asyncio
async def test_retired_equipment_preserves_history_but_is_not_selectable_for_new_work(
    client: AsyncClient,
) -> None:
    equipment_id = "EQP-0001"
    before = await client.get(f"/api/v1/equipment/{equipment_id}")
    assert before.status_code == 200

    retire = await client.post(
        f"/api/v1/equipment/{equipment_id}/status",
        json={"status": "RETIRED", "reason": "เลิกใช้งานถาวร"},
    )
    assert retire.status_code == 200
    assert retire.json()["operational_status"] == "RETIRED"

    # History (the equipment record and its status history) is preserved,
    # never hard-deleted.
    still_readable = await client.get(f"/api/v1/equipment/{equipment_id}")
    assert still_readable.status_code == 200
    assert still_readable.json()["operational_status"] == "RETIRED"

    # RETIRED equipment must not be selectable for new normal operational
    # work: repair creation, PM work-order open, part-instance install.
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "EQUIPMENT", "asset_id": equipment_id, "source_type": "MANUAL"},
    )
    assert repair.status_code == 422
    assert repair.json()["error"]["code"] == "EQUIPMENT_RETIRED"

    inspect = await client.get("/api/v1/checklists/active", params={"asset_type": "EQUIPMENT"})
    checklist_items = inspect.json()["items"]
    submit = await client.post(
        "/api/v1/inspections",
        json={
            "asset_type": "EQUIPMENT",
            "asset_id": equipment_id,
            "items": [{"item_id": i["item_id"], "result": "PASS"} for i in checklist_items],
        },
    )
    assert submit.status_code == 422
    assert submit.json()["error"]["code"] == "EQUIPMENT_RETIRED"
