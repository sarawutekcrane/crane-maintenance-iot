"""R8 PRE-UAT Whole-Web Completion — ONE isolated, deterministic synthetic TEST fixture
profile for local browser UAT (Owner source approval Rev 1, 2026-11-18).

Loaded only when MOCK_FIXTURE_PROFILE=uat_r8. The config validator allows that only
with DATA_REPOSITORY=mock and a recognized non-production APP_ENV. The default Mock
seed is unchanged without the flag.

This is a semantic mirror of the UAT workbook scenarios
(docs/uat/r8-preuat-fixture-mapping-and-setup.md). Workbook IDs are never copied: every
id here starts with UAT8-. All data is invented and TEST-scoped (mock batch): no real
licence, employee or GPS position. It adds:
- 2 models (dual-engine with PTO; single-engine);
- 7 vehicles covering all 5 operational statuses across the 3 existing branches, with
  components;
- current meter counters, including one vehicle with deliberately unknown meters;
- latest locations: one recent, one stale, and none for some vehicles;
- vehicle certificates: valid, near expiry and past-dated ACTIVE (to observe R7 A-5);
- personnel (driver / rigger / signalman / other / technician / inactive) and technicians;
- one tracked part instance with synthetic INSPECT / REPAIR rules (PG-5 P-A maintenance UAT).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.repositories.mock.repository import MockRepository

PROFILE_UAT_R8 = "uat_r8"

MODELS = (
    ("UAT8-MDL-A", "UAT8-A", "รุ่นทดสอบ A (สองเครื่องยนต์ + PTO)", ("CARRIER_ENGINE", "CRANE_ENGINE", "PTO")),
    ("UAT8-MDL-B", "UAT8-B", "รุ่นทดสอบ B (เครื่องยนต์เดียว)", ("CARRIER_ENGINE", "PTO")),
)
# vehicle_id, machine_no, model, status, branch
VEHICLES = (
    ("UAT8-VEH-01", "UAT8/01", "UAT8-MDL-A", "READY", "BR-BANGNA-KM6"),
    ("UAT8-VEH-02", "UAT8/02", "UAT8-MDL-A", "WORKING", "BR-LAEM-CHABANG"),
    ("UAT8-VEH-03", "UAT8/03", "UAT8-MDL-B", "MAINTENANCE", "BR-BANGNA-KM6"),
    ("UAT8-VEH-04", "UAT8/04", "UAT8-MDL-B", "OUT_OF_SERVICE", "BR-LAEM-CHABANG"),
    ("UAT8-VEH-05", "UAT8/05", "UAT8-MDL-B", "LONG_TERM_PARKING", "BR-RAYONG"),
    ("UAT8-VEH-06", "UAT8/06", "UAT8-MDL-A", "READY", "BR-RAYONG"),
    ("UAT8-VEH-07", "UAT8/007", "UAT8-MDL-B", "WORKING", "BR-BANGNA-KM6"),
)
# personnel_id, first, last, position, active
PERSONNEL = (
    ("UAT8-PER-01", "คนขับทดสอบ", "หนึ่ง", "คนขับเครน", "ACTIVE"),
    ("UAT8-PER-02", "คนขับทดสอบ", "สอง", "คนขับเครน", "ACTIVE"),
    ("UAT8-PER-03", "ริกเกอร์ทดสอบ", "หนึ่ง", "Rigger", "ACTIVE"),
    ("UAT8-PER-04", "ซิกแนลทดสอบ", "หนึ่ง", "Signalman", "ACTIVE"),
    ("UAT8-PER-05", "ผู้ช่วยทดสอบ", "หนึ่ง", "ผู้ช่วยยก", "ACTIVE"),
    ("UAT8-PER-06", "ช่างทดสอบ", "เอ", "ช่างซ่อมบำรุง", "ACTIVE"),
    ("UAT8-PER-07", "ช่างทดสอบ", "บี", "ช่างซ่อมบำรุง", "ACTIVE"),
    ("UAT8-PER-08", "หัวหน้าทดสอบ", "หนึ่ง", "หัวหน้าซ่อมบำรุง", "ACTIVE"),
    ("UAT8-PER-09", "เซฟตี้ทดสอบ", "หนึ่ง", "เจ้าหน้าที่ความปลอดภัย", "ACTIVE"),
    ("UAT8-PER-10", "พนักงานทดสอบ", "พ้นสภาพ", "คนขับเครน", "INACTIVE"),
)
TECHNICIANS = (("UAT8-TEC-01", "ช่างทดสอบ", "เอ"), ("UAT8-TEC-02", "ช่างทดสอบ", "บี"),
               ("UAT8-TEC-03", "ช่างทดสอบ", "ซี"))


def apply_fixture_profile(repo: MockRepository, profile: str) -> None:
    if profile != PROFILE_UAT_R8:
        raise ValueError(f"unknown fixture profile {profile!r}")
    from app.domain.location_snapshot import CurrentLocation
    from app.domain.meter import CounterType, CurrentCounterReading
    from app.domain.personnel import PERSONNEL_MASTER_TARGET_COLUMNS
    from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
    from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
    from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate
    from app.domain.vehicle_model import VehicleModel
    from app.repositories.base import REFERENCE_SCOPE_TEST, ScopedReferenceRow
    from app.repositories.mock import seed_data

    batch = MOCK_TEST_BATCH_ID
    created = datetime(2026, 11, 18, 1, 0, tzinfo=UTC)
    for model_id, code, name, roles in MODELS:
        repo._models[model_id] = VehicleModel(model_id=model_id, model_code=code, model_name=name,
                                              brand="ยี่ห้อทดสอบ", description="รุ่นสังเคราะห์สำหรับ UAT (TEST)",
                                              component_roles=list(roles), created_at=created, updated_at=created)
        repo._preuat_created.setdefault("MODEL", set()).add(model_id)
        repo._preuat_batch[f"MODEL:{model_id}"] = batch
    for index, (vehicle_id, machine_no, model_id, status, branch) in enumerate(VEHICLES, start=1):
        vehicle = Vehicle(vehicle_id=vehicle_id, machine_no=machine_no, model_id=model_id,
                          serial_number=f"UAT8-SN-{index:02d}", operational_status=status,
                          created_at=created, updated_at=created)
        repo._vehicles[vehicle_id] = vehicle
        repo._vehicle_registry[vehicle_id] = {"registration_no": f"ทดสอบ-{index:02d}",
                                              "registration_province_code": "TH-10", "responsible_branch_id": branch}
        roles = repo._models[model_id].component_roles
        repo._components[vehicle_id] = [
            VehicleComponent(component_id=f"UAT8-CMP-{index:02d}-{n}", vehicle_id=vehicle_id, component_role=role,
                             label=seed_data._COMPONENT_LABELS[role]) for n, role in enumerate(roles, start=1)]
        repo._history_seq += 1
        repo._status_history[vehicle_id] = [VehicleStatusHistoryEntry(
            history_id=f"STH-{repo._history_seq:04d}", vehicle_id=vehicle_id, status=status, changed_at=created,
            changed_by="UAT8-FIXTURE", note="สถานะเริ่มต้นข้อมูลทดสอบ (uat_r8)")]
        repo._preuat_created.setdefault("VEHICLE", set()).add(vehicle_id)
        repo._preuat_batch[f"VEHICLE:{vehicle_id}"] = batch
        if vehicle_id == "UAT8-VEH-03":
            continue  # deliberately unknown meters (UNKNOWN, never 0)
        hours = 1200.0 + 150 * index
        readings = [CurrentCounterReading(component_id=c.component_id,
                                          counter_type=CounterType.PTO_HOUR if c.component_role.value == "PTO"
                                          else CounterType.ENGINE_HOUR, value=hours if c.component_role.value
                                          != "PTO" else round(hours / 3, 1))
                    for c in repo._components[vehicle_id]]
        readings.append(CurrentCounterReading(component_id=None, counter_type=CounterType.ODOMETER,
                                              value=40000.0 + 1000 * index))
        repo._current_counters[vehicle_id] = readings
    now = datetime.now(UTC)
    repo._current_locations["UAT8-VEH-01"] = CurrentLocation(vehicle_id="UAT8-VEH-01", latitude=13.0, longitude=100.9,
                                                             gps_time=now - timedelta(minutes=20),
                                                             received_at=now - timedelta(minutes=19))
    repo._current_locations["UAT8-VEH-02"] = CurrentLocation(vehicle_id="UAT8-VEH-02", latitude=13.1, longitude=101.0,
                                                             gps_time=now - timedelta(days=9),
                                                             received_at=now - timedelta(days=9))
    today = now.date()
    certificates = (
        ("UAT8-CERT-01", "UAT8-VEH-01", today - timedelta(days=200), today + timedelta(days=165)),
        ("UAT8-CERT-02", "UAT8-VEH-02", today - timedelta(days=350), today + timedelta(days=12)),
        ("UAT8-CERT-03", "UAT8-VEH-04", today - timedelta(days=400), today - timedelta(days=20)),
    )
    for cert_id, vehicle_id, issued, expires in certificates:
        repo._vehicle_certificates.setdefault(vehicle_id, []).append(VehicleCertificate(
            certificate_id=cert_id, vehicle_id=vehicle_id, certificate_type_code="UAT8-PJ",
            certificate_type_name_th="ใบตรวจสภาพเครนทดสอบ (ปจ.)", document_no=f"{cert_id}-DOC",
            issue_date=date.fromordinal(issued.toordinal()), expiry_date=date.fromordinal(expires.toordinal()),
            alert_lead_days=30, certificate_status=CertificateStatus.ACTIVE, created_by_user_id="UAT8-FIXTURE",
            created_at=created, note_th="ใบรับรองสังเคราะห์สำหรับ UAT (TEST)"))
    for personnel_id, first, last, position, active in PERSONNEL:
        row = dict.fromkeys(PERSONNEL_MASTER_TARGET_COLUMNS, "")
        row.update(personnel_id=personnel_id, first_name=first, last_name=last, position=position,
                   active_status=active, is_test_data="TRUE", test_batch_id=batch,
                   note_th="ข้อมูลสังเคราะห์ uat_r8 (TEST)")
        repo._personnel_master.append(row)
        repo._preuat_created.setdefault("PERSONNEL", set()).add(personnel_id)
        repo._preuat_batch[f"PERSONNEL:{personnel_id}"] = batch
    for technician_id, first, last in TECHNICIANS:
        repo._technician_master.append(ScopedReferenceRow(
            values={"technician_id": technician_id, "first_name": first, "last_name": last, "active_status": "ACTIVE"},
            scope=REFERENCE_SCOPE_TEST, test_batch_id=batch))
    repo._vehicle_reference = None
    _apply_parts(repo, created)


# PG-5 P-A: one tracked synthetic part instance plus one INSPECT and one REPAIR rule (model-scoped to
# the UAT8 model, never a real threshold), so the part maintenance UI can be exercised in Access
# Management mode, where creating rules / instances stays fail-closed (other R6 routes unresolved).
UAT8_PART_INSTANCE = "UAT8-PINST-01"
UAT8_RULES = (("UAT8-LTR-INSPECT", "INSPECT"), ("UAT8-LTR-REPAIR", "REPAIR"))


def _apply_parts(repo: MockRepository, created: datetime) -> None:
    from dataclasses import replace
    from types import MappingProxyType

    from app.domain.lifetime_rule import (
        DueAction,
        IntervalUnit,
        LifetimeRule,
        LifetimeRuleScope,
        LifetimeTriggerType,
    )
    from app.domain.part_instance import LifecycleStartReason, PartInstance, PartInstanceStatus, PartLifecycle, \
        PriorUsage
    from app.repositories.mock.repository import check_part_invariants

    rules = {rule_id: LifetimeRule(lifetime_rule_id=rule_id, part_id="PART-0005", scope=LifetimeRuleScope.MODEL,
                                   model_id="UAT8-MDL-A", trigger_type=LifetimeTriggerType.CALENDAR,
                                   interval_value=6, interval_unit=IntervalUnit.MONTH, due_action=DueAction(action),
                                   note="SYNTHETIC uat_r8 TEST rule — not a real threshold", created_at=created)
             for rule_id, action in UAT8_RULES}
    lifecycle = PartLifecycle(lifecycle_id="UAT8-PLC-01", part_instance_id=UAT8_PART_INSTANCE, cycle_number=1,
                              start_reason=LifecycleStartReason.ENROLLMENT, started_at=created, started_by="UAT8-FIXTURE")
    instance = PartInstance(part_instance_id=UAT8_PART_INSTANCE, part_id="PART-0005", serial_number="UAT8-SN-P01",
                            status=PartInstanceStatus.READY_FOR_INSTALL, prior_usage=PriorUsage(quality="UNKNOWN"),
                            current_lifecycle_id="UAT8-PLC-01", note="ชิ้นงานสังเคราะห์ uat_r8 (TEST)",
                            created_at=created, updated_at=created, state_version=1)
    state = repo._part_state
    candidate = replace(state, rules=MappingProxyType({**state.rules, **rules}),
                        instances=MappingProxyType({**state.instances, UAT8_PART_INSTANCE: instance}),
                        lifecycles=MappingProxyType({**state.lifecycles, UAT8_PART_INSTANCE: (lifecycle,)}))
    check_part_invariants(candidate)
    repo._part_state = candidate


__all__ = ["apply_fixture_profile", "PROFILE_UAT_R8", "UAT8_PART_INSTANCE", "UAT8_RULES", "VEHICLES", "MODELS", "PERSONNEL", "TECHNICIANS"]
