"""In-memory seed data for `MockRepository`.

Demonstrates, without any external configuration:
- multiple models, one of them dual-engine (baseline section 16:
  "This design must support multi-engine vehicles without changing the
  API architecture" — MODEL-0002 has CARRIER_ENGINE, CRANE_ENGINE, PTO;
  MODEL-0001/MODEL-0003 are single-engine and carry only CARRIER_ENGINE +
  PTO, since a vehicle is not required to have a CRANE_ENGINE — see
  docs/phase-results/component-role-naming-correction.md).
- `VEH-1046`, matching the example vehicle_id used in
  `00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt` section 10.
- a vehicle with a blank serial number, proving missing source values
  stay blank rather than being fabricated (baseline scope item 16).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.domain.asset import AssetType
from app.domain.checklist import ChecklistItem, ChecklistMaster, ChecklistRevision
from app.domain.common import OperationalStatus
from app.domain.equipment import Equipment, EquipmentCategory, EquipmentOperationalStatus
from app.domain.part import PartMaster, TrackingMode
from app.domain.pm import PmPlan, PmTask, PmTaskRevision
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
        component_roles=[ComponentRole.CARRIER_ENGINE, ComponentRole.PTO],
        # DEVELOPMENT/DEMO ASSIGNMENT ONLY — Core Demo Fixes prompt, PM
        # WORKFLOW REDESIGN section A: no authoritative model->PM-plan
        # mapping source exists for this project. Pointing every seeded
        # model at the same placeholder PLAN1 keeps the PM workflow
        # demonstrable end-to-end; it is NOT a claim that this is the real
        # company-approved assignment. Replace with the real mapping (or
        # leave a model's assigned_pm_plan_id as None) once source data
        # exists — see OPEN_DECISIONS_REGISTER_EN.txt E05.
        assigned_pm_plan_id="PMP-0001",
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
            ComponentRole.CARRIER_ENGINE,
            ComponentRole.CRANE_ENGINE,
            ComponentRole.PTO,
        ],
        # DEVELOPMENT/DEMO ASSIGNMENT ONLY — see MODEL-0001's identical note.
        assigned_pm_plan_id="PMP-0001",
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    VehicleModel(
        model_id="MODEL-0003",
        model_code="GR-250",
        model_name="Tadano GR-250 รถเครนล้อยาง 25 ตัน",
        brand="Tadano",
        description="รถเครนล้อยาง เครื่องยนต์เดียว",
        component_roles=[ComponentRole.CARRIER_ENGINE, ComponentRole.PTO],
        # DEVELOPMENT/DEMO ASSIGNMENT ONLY — see MODEL-0001's identical note.
        assigned_pm_plan_id="PMP-0001",
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
    ComponentRole.CARRIER_ENGINE: "เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง",
    ComponentRole.CRANE_ENGINE: "เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน",
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


# ---------------------------------------------------------------------------
# Inspection checklists (Phase 3)
#
# SOURCE DATA RULE (see project-governance docs): no authoritative checklist
# content (real item wording, inspection method, acceptance standard, or
# critical-item classification) exists anywhere in this repository. The
# checklist names and item titles below are deliberately generic,
# numbered placeholders — clearly NOT a real company inspection standard —
# so the revision/PASS-FAIL-N/A/finding/evidence workflow can be built and
# tested without fabricating maintenance or safety content. `method`,
# `standard`, and `instruction` are left blank (None) for the same reason.
# `frequency` is also left unset: OPEN_DECISIONS_REGISTER_EN.txt D02 (daily
# vs weekly scheduling) is not approved. `is_critical` is False on every
# item: D03 requires an explicit source before any item may be marked
# critical. Replace this seed data with the real checklist once the user
# supplies authoritative content, without changing the revision model
# itself.
# ---------------------------------------------------------------------------

SEED_CHECKLISTS: list[ChecklistMaster] = [
    ChecklistMaster(
        checklist_id="CHK-0001",
        asset_type=AssetType.VEHICLE,
        code="VEHICLE-PLACEHOLDER",
        name="รายการตรวจเช็คยานพาหนะ (ข้อมูลตัวอย่างชั่วคราวสำหรับพัฒนา/ทดสอบระบบ)",
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    ChecklistMaster(
        checklist_id="CHK-0002",
        asset_type=AssetType.EQUIPMENT,
        code="EQUIPMENT-PLACEHOLDER",
        name="รายการตรวจเช็คเครื่องมือ/อุปกรณ์ (ข้อมูลตัวอย่างชั่วคราวสำหรับพัฒนา/ทดสอบระบบ)",
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
]

SEED_CHECKLIST_REVISIONS: list[ChecklistRevision] = [
    ChecklistRevision(
        revision_id="REV-0001",
        checklist_id="CHK-0001",
        revision_number=1,
        effective_date=date(2026, 1, 1),
        created_at=_SEED_TIME,
    ),
    ChecklistRevision(
        revision_id="REV-0002",
        checklist_id="CHK-0002",
        revision_number=1,
        effective_date=date(2026, 1, 1),
        created_at=_SEED_TIME,
    ),
]


def _placeholder_items(revision_id: str, id_prefix: str, count: int) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for index in range(1, count + 1):
        items.append(
            ChecklistItem(
                item_id=f"{id_prefix}-{index:04d}",
                revision_id=revision_id,
                sequence=index,
                title=f"รายการตรวจสอบตัวอย่างที่ {index}",
                # inspection_point / method / standard / instruction /
                # frequency / reference image intentionally left unset —
                # see SOURCE DATA RULE note above.
                #
                # CORRECTION (post-Phase-3 verification): required_photo_on_fail
                # and required_remark_on_fail are both explicitly False for
                # every placeholder item. Neither flag has an authoritative
                # source naming a real item that requires a photo or a
                # remark, so no placeholder/example item may set either one
                # True — doing so would be inventing a real operational
                # rule the same way marking an item `is_critical=True`
                # without source data would be. The item-level mechanism
                # itself (both flags exist and are read by
                # InspectionService.submit_inspection) is exercised by
                # dedicated tests that inject a synthetic item instead of
                # relying on seed data to carry an invented rule — see
                # backend/tests/test_inspection_item_level_rules.py.
                required_photo_on_fail=False,
                required_remark_on_fail=False,
                is_critical=False,
            )
        )
    return items


SEED_CHECKLIST_ITEMS: dict[str, list[ChecklistItem]] = {
    "REV-0001": _placeholder_items("REV-0001", "ITM-V", 5),
    "REV-0002": _placeholder_items("REV-0002", "ITM-E", 4),
}


# ---------------------------------------------------------------------------
# PM plan / task revision (Phase 4)
#
# SOURCE DATA RULE (OPEN_DECISIONS_REGISTER_EN.txt E05): no authoritative PM
# plan/task content (real task wording, interval, standard part, or warning
# threshold) exists anywhere in this repository for ANY plan, including
# PLAN1 — a repo-wide search before this phase confirmed the plan codes are
# only named in governance/prompt documents as concepts, never accompanied
# by real content. Only PLAN1 is given a master record + one clearly
# labeled example/placeholder task revision here, mirroring the Phase 3
# checklist placeholder pattern exactly (generic numbered titles, no
# interval/trigger/standard-part value fabricated). PLAN2/PLAN3/PLAN4 are
# deliberately NOT seeded at all — not even an empty master record — so
# nothing here can be mistaken for "the plan exists, its content is just
# empty"; they simply do not exist until real source data is supplied.
# `trigger_type`/`interval_value` are left None on every placeholder task:
# the trigger-type mechanism itself (ENGINE_HOUR/PTO_HOUR/ODOMETER/CALENDAR)
# is exercised by a synthetic task injected directly into a test repository
# instance, not by an invented seed-data value — see
# backend/tests/test_pm_plan_and_task_revision.py.
# ---------------------------------------------------------------------------

SEED_PM_PLANS: list[PmPlan] = [
    PmPlan(
        pm_plan_id="PMP-0001",
        plan_code="PLAN1",
        asset_type=AssetType.VEHICLE,
        name="แผนบำรุงรักษาเชิงป้องกัน PLAN1 (ข้อมูลตัวอย่างชั่วคราวสำหรับพัฒนา/ทดสอบระบบ)",
        model_ids=[],  # applies to every vehicle model — no per-model source data exists
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
]

SEED_PM_TASK_REVISIONS: list[PmTaskRevision] = [
    PmTaskRevision(
        revision_id="PMREV-0001",
        pm_plan_id="PMP-0001",
        revision_number=1,
        effective_date=date(2026, 1, 1),
        source_revision_note="ข้อมูลตัวอย่างชั่วคราว ไม่มีแหล่งข้อมูลที่อนุมัติ",
        created_at=_SEED_TIME,
    ),
]


def _placeholder_pm_tasks(revision_id: str, count: int) -> list[PmTask]:
    tasks: list[PmTask] = []
    for index in range(1, count + 1):
        tasks.append(
            PmTask(
                pm_task_id=f"PMT-{index:04d}",
                revision_id=revision_id,
                sequence=index,
                group=None,
                description=f"งานบำรุงรักษาตัวอย่างที่ {index} (PLAN1)",
                trigger_type=None,
                interval_value=None,
                interval_unit=None,
                standard_parts=[],
            )
        )
    return tasks


SEED_PM_TASKS: dict[str, list[PmTask]] = {
    "PMREV-0001": _placeholder_pm_tasks("PMREV-0001", 3),
}


# ---------------------------------------------------------------------------
# Part Master (Phase 5)
#
# SOURCE DATA RULE (guardrails section 12 / OPEN_DECISIONS_REGISTER_EN.txt
# G01/G03): no real company parts catalog exists in this repository. The
# entries below are a small number of clearly-labeled development/example
# PartMaster records spanning each tracking_mode, used only to prove the
# tracking-mode/part-identity mechanics (baseline "Do not collapse
# different specifications merely because their display name is similar" —
# see PART-0002/PART-0003 below, same display name, different
# specification, distinct part_id). No PartInstance, PartSet revision,
# PositionLifetimeRecord, or LifetimeRule is seeded here — per the
# incremental/on-demand enrollment principle, those are created only when
# a test/workflow actually needs one, never pre-loaded.
# ---------------------------------------------------------------------------

SEED_PART_MASTERS: list[PartMaster] = [
    PartMaster(
        part_id="PART-0001",
        part_code="BOLT-GENERIC",
        name="สลักเกลียวทั่วไป (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)",
        specification=None,
        manufacturer=None,
        part_number=None,
        tracking_mode=TrackingMode.NONE,
        category="FASTENER",
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    PartMaster(
        part_id="PART-0002",
        part_code="OIL-FILTER-A",
        name="ไส้กรองน้ำมันเครื่อง (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)",
        specification="ขนาด A",
        manufacturer=None,
        part_number=None,
        tracking_mode=TrackingMode.CONSUMABLE,
        category="FILTER",
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    PartMaster(
        part_id="PART-0003",
        # Same display name as PART-0002 above, deliberately, to prove a
        # different specification stays a different part_id rather than
        # being collapsed into the same record.
        part_code="OIL-FILTER-B",
        name="ไส้กรองน้ำมันเครื่อง (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)",
        specification="ขนาด B",
        manufacturer=None,
        part_number=None,
        tracking_mode=TrackingMode.CONSUMABLE,
        category="FILTER",
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    PartMaster(
        part_id="PART-0004",
        part_code="BOOM-CYL-POS",
        name="กระบอกไฮดรอลิกแขนเครน ตามตำแหน่ง (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)",
        specification=None,
        manufacturer=None,
        part_number=None,
        tracking_mode=TrackingMode.POSITION_LIFETIME,
        category="HYDRAULIC",
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
    PartMaster(
        part_id="PART-0005",
        part_code="HYD-PUMP-INST",
        name="ปั๊มไฮดรอลิกหลัก แบบติดตามรายชิ้น (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)",
        specification=None,
        manufacturer=None,
        part_number=None,
        tracking_mode=TrackingMode.INSTANCE_TRACKED,
        category="HYDRAULIC",
        created_at=_SEED_TIME,
        updated_at=_SEED_TIME,
    ),
]
