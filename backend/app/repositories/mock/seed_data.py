"""In-memory seed data for `MockRepository`.

Demonstrates, without any external configuration:
- multiple models, one of them dual-engine (baseline section 16:
  "This design must support multi-engine vehicles without changing the
  API architecture" — MODEL-0002 has ENGINE_MAIN, ENGINE_SECONDARY, PTO).
- `VEH-1046`, matching the example vehicle_id used in
  `00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt` section 10.
- a vehicle with a blank serial number, proving missing source values
  stay blank rather than being fabricated (baseline scope item 16).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.common import OperationalStatus
from app.domain.equipment import Equipment, EquipmentCategory, EquipmentOperationalStatus
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import ComponentRole, VehicleModel

_SEED_TIME = datetime(2026, 1, 15, 8, 0, 0, tzinfo=timezone.utc)

SEED_MODELS: list[VehicleModel] = [
    VehicleModel(
        model_id="MODEL-0001",
        model_code="QY50",
        model_name="Zoomlion QY50 รถเครนล้อยาง 50 ตัน",
        brand="Zoomlion",
        description="รถเครนล้อยาง เครื่องยนต์เดียว",
        component_roles=[ComponentRole.ENGINE_MAIN, ComponentRole.PTO],
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    VehicleModel(
        model_id="MODEL-0002",
        model_code="XCT80",
        model_name="XCMG XCT80 รถเครนล้อยาง 80 ตัน (สองเครื่องยนต์)",
        brand="XCMG",
        description="รถเครนล้อยาง เครื่องยนต์คู่ (ขับเคลื่อน + ยกเครน)",
        component_roles=[
            ComponentRole.ENGINE_MAIN,
            ComponentRole.ENGINE_SECONDARY,
            ComponentRole.PTO,
        ],
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    VehicleModel(
        model_id="MODEL-0003",
        model_code="GR-250",
        model_name="Tadano GR-250 รถเครนล้อยาง 25 ตัน",
        brand="Tadano",
        description="รถเครนล้อยาง เครื่องยนต์เดียว",
        component_roles=[ComponentRole.ENGINE_MAIN, ComponentRole.PTO],
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
]

SEED_VEHICLES: list[Vehicle] = [
    Vehicle(
        vehicle_id="VEH-1046",
        machine_no="TC-12",
        model_id="MODEL-0001",
        serial_number="ZL-2021-0456",
        operational_status=OperationalStatus.WORKING,
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    Vehicle(
        vehicle_id="VEH-1047",
        machine_no="TC-13",
        model_id="MODEL-0002",
        serial_number="XC-2022-0099",
        operational_status=OperationalStatus.MAINTENANCE,
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    Vehicle(
        vehicle_id="VEH-1048",
        machine_no="TC-14",
        model_id="MODEL-0003",
        # Serial number not yet recorded for this unit: stays blank rather
        # than being fabricated (baseline scope item 16).
        serial_number=None,
        operational_status=OperationalStatus.LONG_TERM_PARKING,
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
]

_COMPONENT_LABELS: dict[ComponentRole, str] = {
    ComponentRole.ENGINE_MAIN: "เครื่องยนต์หลัก",
    ComponentRole.ENGINE_SECONDARY: "เครื่องยนต์สำรอง",
    ComponentRole.PTO: "ระบบส่งกำลัง (PTO)",
    ComponentRole.VEHICLE: "ตัวรถ",
}


def _components_for(vehicle: Vehicle, model: VehicleModel, next_id: int) -> list[VehicleComponent]:
    components: list[VehicleComponent] = []
    for index, role in enumerate(model.component_roles):
        components.append(
            VehicleComponent(
                component_id=f"CMP-{next_id + index:04d}",
                vehicle_id=vehicle.vehicle_id,
                component_role=role,
                label=_COMPONENT_LABELS[role],
            )
        )
    return components


def build_seed_components() -> dict[str, list[VehicleComponent]]:
    models_by_id = {model.model_id: model for model in SEED_MODELS}
    components_by_vehicle: dict[str, list[VehicleComponent]] = {}
    counter = 1
    for vehicle in SEED_VEHICLES:
        model = models_by_id[vehicle.model_id]
        components = _components_for(vehicle, model, counter)
        counter += len(components)
        components_by_vehicle[vehicle.vehicle_id] = components
    return components_by_vehicle


def build_seed_status_history() -> dict[str, list[VehicleStatusHistoryEntry]]:
    """One initial history entry per vehicle, recording its seeded status."""
    history_by_vehicle: dict[str, list[VehicleStatusHistoryEntry]] = {}
    for index, vehicle in enumerate(SEED_VEHICLES, start=1):
        history_by_vehicle[vehicle.vehicle_id] = [
            VehicleStatusHistoryEntry(
                history_id=f"STH-{index:04d}",
                vehicle_id=vehicle.vehicle_id,
                status=vehicle.operational_status,
                changed_at=vehicle.created_at,
                changed_by=None,
                note="สถานะเริ่มต้นจากการนำเข้าข้อมูล",
            )
        ]
    return history_by_vehicle


SEED_EQUIPMENT: list[Equipment] = [
    Equipment(
        equipment_id="EQP-0001",
        equipment_code="LATHE-01",
        name="เครื่องกลึงเบอร์ 1",
        category=EquipmentCategory.LATHE,
        serial_number="LT-2019-0021",
        location="โรงซ่อมกลาง",
        # Equipment uses its own status vocabulary (EquipmentOperationalStatus),
        # not Vehicle's OperationalStatus.WORKING (OPEN_DECISIONS_REGISTER_EN.txt
        # decision C02).
        operational_status=EquipmentOperationalStatus.IN_USE,
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    Equipment(
        equipment_id="EQP-0002",
        equipment_code="COMP-01",
        name="ปั๊มลมโรงซ่อม",
        category=EquipmentCategory.AIR_COMPRESSOR,
        serial_number="CP-2020-0110",
        location="โรงซ่อมกลาง",
        operational_status=EquipmentOperationalStatus.READY,
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    Equipment(
        equipment_id="EQP-0003",
        equipment_code="WELD-01",
        name="เครื่องเชื่อมไฟฟ้า",
        category=EquipmentCategory.WELDING,
        serial_number=None,
        location="โรงซ่อมสาขา 2",
        operational_status=EquipmentOperationalStatus.MAINTENANCE,
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
]
