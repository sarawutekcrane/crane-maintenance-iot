"""In-memory mock repository.

Runs fully offline with no external services. Used for local development
before Google Sheets credentials exist, and for fast automated tests.
Starting Phase 2, it holds seeded vehicle/model/equipment domain data
(see `seed_data.py`) so the domain/service layer and Web UI can be built
and tested before any Google Sheets schema exists.
"""
from __future__ import annotations

import copy

from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.checklist import ChecklistItem, ChecklistMaster, ChecklistRevision, ChecklistRevisionDetail
from app.domain.common import OperationalStatus, PageParams, utc_now
from app.domain.driver import Driver, VehicleDriverAssignment
from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate
from app.domain.certificate_expiry_report import CertificateReportRead, build_report_row
from app.domain.model_document import ModelDocument
from app.domain.alert import Alert, AlertStatus
from app.domain.alert_setting import AlertSetting
from app.domain.daily_summary import DailySummary, DailySummaryDataStatus, DailySummaryMetricType
from app.domain.vehicle_event import TimeQuality, VehicleEvent, VehicleEventType
from app.domain.equipment import (
    Equipment,
    EquipmentCategory,
    EquipmentOperationalStatus,
    EquipmentStatusHistoryEntry,
)
from app.domain.inspection import (
    FindingStatus,
    InspectionDetail,
    InspectionFinding,
    InspectionHeader,
    InspectionItemResult,
    InspectionResultValue,
    InspectionSummary,
    NewInspectionItemInput,
)
from app.domain.lifetime_rule import LifetimeRule, LifetimeRuleScope, LifetimeTriggerType
from app.domain.meter import CurrentCounterReading, MeterReading, MeterSnapshot
from app.domain.part import (
    PartActionType,
    PartMaster,
    PartSet,
    PartSetItem,
    PartSetRevision,
    PartSetRevisionDetail,
    TrackingMode,
)
from app.domain.part_instance import (
    InstallationSegment,
    InstallationSegmentStatus,
    LifecycleStartReason,
    PartInstance,
    PartInstanceDetail,
    PartInstanceStatus,
    PartLifecycle,
    PriorUsage,
)
from app.domain.pm import (
    PmPlan,
    PmScopeAdditionAudit,
    PmTaskRevision,
    PmTaskRevisionDetail,
    PmTriggerType,
    PmUsedPart,
    PmWorkOrder,
    PmWorkOrderDetail,
    PmWorkOrderStatus,
    PmWorkOrderSummary,
    PmWorkResult,
)
from app.domain.position_lifetime import PositionLifetimeRecord
from app.domain.assignment import (
    AssignmentRole,
    PmAssignmentHistoryEntry,
    RepairAssignmentHistoryEntry,
    active_primary_and_collaborators,
)
from app.domain.location_snapshot import CurrentLocation, LocationSnapshot
from app.domain.requisition import (
    MaterialRequest,
    MaterialRequestDetail,
    RequisitionLine,
    RequisitionSourceType,
)
from app.domain.repair import (
    Repair,
    RepairAction,
    RepairDetail,
    RepairPart,
    RepairSourceType,
    RepairStatus,
    RepairSummary,
)
from app.domain.repair_request import (
    REPAIR_REQUEST_STATUS_CONVERTED,
    REPAIR_REQUEST_STATUS_PENDING,
    RepairRequest,
    decode_provenance_note,
)
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import ComponentRole, VehicleModel
from app.repositories.base import Repository, RepositoryError, VehicleMasterSummaryRead
from app.repositories.mock import seed_data


def _paginate(items: list, params: PageParams) -> tuple[list, int]:
    total = len(items)
    start = (params.page - 1) * params.page_size
    end = start + params.page_size
    return items[start:end], total


class MockRepository(Repository):
    def __init__(self) -> None:
        self._models: dict[str, VehicleModel] = {
            model.model_id: model.model_copy(deep=True) for model in seed_data.SEED_MODELS
        }
        self._vehicles: dict[str, Vehicle] = {
            vehicle.vehicle_id: vehicle.model_copy(deep=True)
            for vehicle in seed_data.SEED_VEHICLES
        }
        self._components: dict[str, list[VehicleComponent]] = copy.deepcopy(
            seed_data.build_seed_components()
        )
        self._status_history: dict[str, list[VehicleStatusHistoryEntry]] = copy.deepcopy(
            seed_data.build_seed_status_history()
        )
        self._equipment: dict[str, Equipment] = {
            item.equipment_id: item.model_copy(deep=True) for item in seed_data.SEED_EQUIPMENT
        }
        self._equipment_status_history: dict[str, list[EquipmentStatusHistoryEntry]] = {}
        self._equipment_status_history_seq = 0
        self._history_seq = len(self._vehicles)

        self._checklists: dict[str, ChecklistMaster] = {
            c.checklist_id: c.model_copy(deep=True) for c in seed_data.SEED_CHECKLISTS
        }
        self._checklist_revisions: dict[str, ChecklistRevision] = {
            r.revision_id: r.model_copy(deep=True) for r in seed_data.SEED_CHECKLIST_REVISIONS
        }
        self._checklist_items: dict[str, list[ChecklistItem]] = copy.deepcopy(
            seed_data.SEED_CHECKLIST_ITEMS
        )
        self._attachments: dict[str, Attachment] = {}
        self._inspections: dict[str, InspectionDetail] = {}
        self._attachment_seq = 0
        self._inspection_seq = 0
        self._result_seq = 0
        self._finding_seq = 0

        # ---- PM (Phase 4) ----
        self._pm_plans: dict[str, PmPlan] = {
            p.pm_plan_id: p.model_copy(deep=True) for p in seed_data.SEED_PM_PLANS
        }
        self._pm_task_revisions: dict[str, PmTaskRevision] = {
            r.revision_id: r.model_copy(deep=True) for r in seed_data.SEED_PM_TASK_REVISIONS
        }
        self._pm_tasks: dict[str, list] = copy.deepcopy(seed_data.SEED_PM_TASKS)
        self._pm_work_orders: dict[str, PmWorkOrder] = {}
        self._pm_work_results: dict[str, list[PmWorkResult]] = {}
        self._pm_scope_additions: dict[str, list[PmScopeAdditionAudit]] = {}
        self._pm_work_order_seq = 0
        self._pm_work_result_seq = 0
        self._pm_used_part_seq = 0
        self._material_requests: dict[str, MaterialRequest] = {}
        self._material_request_seq = 0
        self._requisition_lines: dict[str, list[RequisitionLine]] = {}
        self._requisition_line_seq = 0
        self._pm_assignment_history: dict[str, list[PmAssignmentHistoryEntry]] = {}
        self._pm_assignment_seq = 0

        # ---- Meter snapshot (Phase 4) ----
        self._meter_snapshots: dict[str, MeterSnapshot] = {}
        self._meter_snapshot_seq = 0

        # ---- Current counter / current location (REV05 — authoritative
        # CURRENT state, distinct from the immutable historical snapshots
        # above; no live IoT/device ingestion writes these in this branch,
        # so tests seed them directly, e.g. `repo._current_counters[...]`) ----
        self._current_counters: dict[str, list[CurrentCounterReading]] = {}
        self._current_locations: dict[str, CurrentLocation] = {}

        # ---- Location snapshot (Core Demo Fixes Delta section E) ----
        self._location_snapshots: dict[str, LocationSnapshot] = {}
        self._location_snapshot_seq = 0

        # ---- Repair (Phase 4) ----
        self._repairs: dict[str, Repair] = {}
        self._repair_actions: dict[str, list[RepairAction]] = {}
        self._repair_parts: dict[str, list[RepairPart]] = {}
        self._repair_seq = 0
        self._repair_action_seq = 0
        self._repair_part_seq = 0
        self._repair_assignment_history: dict[str, list[RepairAssignmentHistoryEntry]] = {}
        self._repair_assignment_seq = 0

        # ---- Repair Request (Core Demo Fixes Delta REV05 section 3) ----
        self._repair_requests: dict[str, RepairRequest] = {}
        self._repair_request_seq = 0

        # ---- Part Master / Part Set (Phase 5) ----
        self._part_masters: dict[str, PartMaster] = {
            p.part_id: p.model_copy(deep=True) for p in seed_data.SEED_PART_MASTERS
        }
        self._part_master_seq = len(self._part_masters)
        self._part_sets: dict[str, PartSet] = {}
        self._part_set_seq = 0
        self._part_set_revisions: dict[str, PartSetRevision] = {}
        self._part_set_revision_seq = 0
        self._part_set_items: dict[str, list[PartSetItem]] = {}
        self._part_set_item_seq = 0

        # ---- Part Instance / lifecycle / installation segment (Phase 5) ----
        self._part_instances: dict[str, PartInstance] = {}
        self._part_instance_seq = 0
        self._part_lifecycles: dict[str, list[PartLifecycle]] = {}
        self._part_lifecycle_seq = 0
        self._installation_segments: dict[str, list[InstallationSegment]] = {}
        self._installation_segment_seq = 0

        # ---- Position lifetime (Phase 5) ----
        self._position_lifetime: dict[str, PositionLifetimeRecord] = {}
        self._position_lifetime_seq = 0

        # ---- Lifetime rule (Phase 5) ----
        self._lifetime_rules: dict[str, LifetimeRule] = {}
        self._lifetime_rule_seq = 0

        # ---- Driver / Operator (Phase 6 Batch 1) ----
        self._drivers: dict[str, Driver] = {
            d.driver_id: d.model_copy(deep=True) for d in seed_data.SEED_DRIVERS
        }
        self._driver_seq = len(self._drivers)
        self._vehicle_driver_assignments: dict[str, list[VehicleDriverAssignment]] = copy.deepcopy(
            seed_data.build_seed_vehicle_driver_assignments()
        )
        self._vehicle_driver_assignment_seq = sum(
            len(v) for v in self._vehicle_driver_assignments.values()
        )

        # ---- Vehicle Certificate (Phase 6 Batch 2A) ----
        self._vehicle_certificates: dict[str, list[VehicleCertificate]] = {}
        self._vehicle_certificate_seq = 0

        # ---- Model Document (Phase 6 Batch 3A) ----
        self._model_documents: dict[str, list[ModelDocument]] = {}
        self._model_document_seq = 0
        self._vehicle_events: list[VehicleEvent] = []
        self._vehicle_event_seq = 0
        self._daily_summaries: dict[tuple, DailySummary] = {}
        self._daily_summary_seq = 0
        # Web/API Phase 6 Batch 5A: no public creation method exists on
        # this repository (read-only batch) — tests seed this list
        # directly, matching the task's own instruction not to invent a
        # convenience creation method merely for test setup.
        self._alerts: list[Alert] = []
        # Web/API Phase 6 Batch 5C: read-only foundation batch — no public
        # creation method exists on this repository. Tests seed this list
        # directly, matching the Batch 5A precedent above.
        self._alert_settings: list[AlertSetting] = []

    @property
    def mode(self) -> str:
        return "mock"

    async def check_ready(self) -> tuple[bool, str | None]:
        # Mock mode has no external dependency, so it is always ready.
        return True, None

    # ---- Vehicle model ----

    async def list_vehicle_models(
        self, q: str | None, params: PageParams
    ) -> tuple[list[VehicleModel], int]:
        models = list(self._models.values())
        if q:
            needle = q.strip().lower()
            models = [
                m
                for m in models
                if needle in m.model_code.lower() or needle in m.model_name.lower()
            ]
        models.sort(key=lambda m: m.model_id)
        page, total = _paginate(models, params)
        return page, total

    async def get_vehicle_model(self, model_id: str) -> VehicleModel | None:
        model = self._models.get(model_id)
        return model.model_copy(deep=True) if model else None

    # ---- Vehicle ----

    async def list_vehicles(
        self,
        q: str | None,
        operational_status: OperationalStatus | None,
        model_id: str | None,
        params: PageParams,
    ) -> tuple[list[Vehicle], int]:
        vehicles = list(self._vehicles.values())
        if q:
            needle = q.strip().lower()
            vehicles = [
                v
                for v in vehicles
                if needle in v.machine_no.lower() or needle in v.vehicle_id.lower()
            ]
        if operational_status is not None:
            vehicles = [v for v in vehicles if v.operational_status == operational_status]
        if model_id is not None:
            vehicles = [v for v in vehicles if v.model_id == model_id]
        vehicles.sort(key=lambda v: v.vehicle_id)
        page, total = _paginate(vehicles, params)
        return page, total

    async def read_vehicle_master_for_summary(self) -> VehicleMasterSummaryRead:
        # Mock rows are already typed `Vehicle` models (no raw cells to
        # validate); the service still applies the identity checks.
        return VehicleMasterSummaryRead(
            vehicles=[v.model_copy(deep=True) for v in self._vehicles.values()]
        )

    async def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        vehicle = self._vehicles.get(vehicle_id)
        return vehicle.model_copy(deep=True) if vehicle else None

    async def update_vehicle_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        vehicle = self._vehicles[vehicle_id]
        updated = vehicle.model_copy(update={"machine_no": machine_no, "updated_at": utc_now()})
        self._vehicles[vehicle_id] = updated
        return updated.model_copy(deep=True)

    async def list_vehicle_components(self, vehicle_id: str) -> list[VehicleComponent]:
        return [c.model_copy(deep=True) for c in self._components.get(vehicle_id, [])]

    async def list_vehicle_status_history(
        self, vehicle_id: str
    ) -> list[VehicleStatusHistoryEntry]:
        entries = self._status_history.get(vehicle_id, [])
        # Deterministic-ordering fix: `changed_at` alone ties when two
        # entries are written close enough together to get an equal
        # timestamp, letting Python's stable sort fall back to insertion
        # order — the newest entry (the higher `history_id`) is not
        # reliably first. `history_id` breaks the tie deterministically.
        ordered = sorted(entries, key=lambda e: (e.changed_at, e.history_id), reverse=True)
        return [e.model_copy(deep=True) for e in ordered]

    async def change_vehicle_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> VehicleStatusHistoryEntry:
        vehicle = self._vehicles[vehicle_id]
        self._history_seq += 1
        entry = VehicleStatusHistoryEntry(
            history_id=f"STH-{self._history_seq:04d}",
            vehicle_id=vehicle_id,
            status=new_status,
            changed_at=utc_now(),
            changed_by=changed_by,
            note=note,
        )
        # Append-only: previous entries are never rewritten or removed.
        self._status_history.setdefault(vehicle_id, []).append(entry)
        self._vehicles[vehicle_id] = vehicle.model_copy(
            update={"operational_status": new_status, "updated_at": entry.changed_at}
        )
        return entry.model_copy(deep=True)

    # ---- Workshop equipment ----

    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> tuple[list[Equipment], int]:
        items = list(self._equipment.values())
        if q:
            needle = q.strip().lower()
            items = [
                e
                for e in items
                if needle in e.name.lower() or needle in e.equipment_code.lower()
            ]
        if category is not None:
            items = [e for e in items if e.category == category]
        items.sort(key=lambda e: e.equipment_id)
        page, total = _paginate(items, params)
        return page, total

    async def get_equipment(self, equipment_id: str) -> Equipment | None:
        item = self._equipment.get(equipment_id)
        return item.model_copy(deep=True) if item else None

    async def change_equipment_status(
        self,
        equipment_id: str,
        status: EquipmentOperationalStatus,
        reason: str | None,
        changed_by: str | None,
    ) -> Equipment:
        equipment = self._equipment[equipment_id]
        self._equipment_status_history_seq += 1
        entry = EquipmentStatusHistoryEntry(
            history_id=f"ESTH-{self._equipment_status_history_seq:04d}",
            equipment_id=equipment_id,
            status=status,
            changed_at=utc_now(),
            changed_by=changed_by,
            reason=reason,
        )
        # Append-only: previous entries are never rewritten or removed.
        self._equipment_status_history.setdefault(equipment_id, []).append(entry)
        updated = equipment.model_copy(
            update={"operational_status": status, "updated_at": entry.changed_at}
        )
        self._equipment[equipment_id] = updated
        return updated.model_copy(deep=True)

    async def list_equipment_status_history(
        self, equipment_id: str
    ) -> list[EquipmentStatusHistoryEntry]:
        entries = self._equipment_status_history.get(equipment_id, [])
        ordered = sorted(entries, key=lambda e: e.changed_at)
        return [e.model_copy(deep=True) for e in ordered]

    # ---- Checklist / inspection (Phase 3) ----

    def _revision_detail(self, revision: ChecklistRevision) -> ChecklistRevisionDetail | None:
        checklist = self._checklists.get(revision.checklist_id)
        if checklist is None:
            return None
        items = sorted(
            self._checklist_items.get(revision.revision_id, []), key=lambda i: i.sequence
        )
        return ChecklistRevisionDetail(
            checklist=checklist.model_copy(deep=True),
            revision=revision.model_copy(deep=True),
            items=[i.model_copy(deep=True) for i in items],
        )

    async def get_active_checklist_revision(
        self, asset_type: AssetType
    ) -> ChecklistRevisionDetail | None:
        checklist = next(
            (c for c in self._checklists.values() if c.asset_type == asset_type), None
        )
        if checklist is None:
            return None
        today = utc_now().date()
        candidates = [
            r
            for r in self._checklist_revisions.values()
            if r.checklist_id == checklist.checklist_id and r.effective_date <= today
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda r: (r.effective_date, r.revision_number))
        return self._revision_detail(latest)

    async def get_checklist_revision(
        self, checklist_id: str, revision_id: str
    ) -> ChecklistRevisionDetail | None:
        revision = self._checklist_revisions.get(revision_id)
        if revision is None or revision.checklist_id != checklist_id:
            return None
        return self._revision_detail(revision)

    async def create_attachment(
        self,
        purpose: AttachmentPurpose,
        storage_ref: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        uploaded_by: str | None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Attachment:
        self._attachment_seq += 1
        attachment = Attachment(
            attachment_id=f"ATT-{self._attachment_seq:04d}",
            purpose=purpose,
            storage_ref=storage_ref,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_at=utc_now(),
            uploaded_by=uploaded_by,
            source_type=source_type,
            source_id=source_id,
        )
        self._attachments[attachment.attachment_id] = attachment
        return attachment.model_copy(deep=True)

    async def get_attachment(self, attachment_id: str) -> Attachment | None:
        attachment = self._attachments.get(attachment_id)
        return attachment.model_copy(deep=True) if attachment else None

    async def list_attachments_for_source(
        self, source_type: str, source_id: str
    ) -> list[Attachment]:
        matches = [
            a
            for a in self._attachments.values()
            if a.source_type == source_type and a.source_id == source_id
        ]
        matches.sort(key=lambda a: a.uploaded_at)
        return [a.model_copy(deep=True) for a in matches]

    async def create_inspection(
        self,
        asset_type: AssetType,
        asset_id: str,
        checklist_id: str,
        revision_id: str,
        revision_number: int,
        inspector_user_id: str | None,
        overall_remark: str | None,
        items: list[NewInspectionItemInput],
        machine_state_snapshot_id: str | None = None,
    ) -> InspectionDetail:
        self._inspection_seq += 1
        inspection_id = f"INS-{self._inspection_seq:04d}"
        submitted_at = utc_now()

        header = InspectionHeader(
            inspection_id=inspection_id,
            asset_type=asset_type,
            asset_id=asset_id,
            checklist_id=checklist_id,
            revision_id=revision_id,
            revision_number=revision_number,
            submitted_at=submitted_at,
            inspector_user_id=inspector_user_id,
            overall_remark=overall_remark,
            machine_state_snapshot_id=machine_state_snapshot_id,
        )

        item_results: list[InspectionItemResult] = []
        findings: list[InspectionFinding] = []
        for item_input in items:
            self._result_seq += 1
            result_id = f"RES-{self._result_seq:04d}"
            item_results.append(
                InspectionItemResult(
                    result_id=result_id,
                    inspection_id=inspection_id,
                    item_id=item_input.item_id,
                    sequence=item_input.sequence,
                    title=item_input.title,
                    inspection_point=item_input.inspection_point,
                    method=item_input.method,
                    standard=item_input.standard,
                    instruction=item_input.instruction,
                    is_critical=item_input.is_critical,
                    result=item_input.result,
                    remark=item_input.remark,
                    evidence_attachment_ids=list(item_input.evidence_attachment_ids),
                )
            )
            if item_input.result == InspectionResultValue.FAIL:
                self._finding_seq += 1
                findings.append(
                    InspectionFinding(
                        finding_id=f"FND-{self._finding_seq:04d}",
                        inspection_id=inspection_id,
                        result_id=result_id,
                        asset_type=asset_type,
                        asset_id=asset_id,
                        item_title=item_input.title,
                        is_critical=item_input.is_critical,
                        status=FindingStatus.OPEN,
                        created_at=submitted_at,
                    )
                )

        detail = InspectionDetail(header=header, items=item_results, findings=findings)
        # Immutable once stored: no method ever replaces or edits an entry
        # in `self._inspections` (OPEN_DECISIONS_REGISTER_EN.txt D04).
        self._inspections[inspection_id] = detail
        return detail.model_copy(deep=True)

    async def get_inspection(self, inspection_id: str) -> InspectionDetail | None:
        detail = self._inspections.get(inspection_id)
        return detail.model_copy(deep=True) if detail else None

    async def list_inspections(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
    ) -> tuple[list[InspectionSummary], int]:
        details = list(self._inspections.values())
        if asset_type is not None:
            details = [d for d in details if d.header.asset_type == asset_type]
        if asset_id is not None:
            details = [d for d in details if d.header.asset_id == asset_id]
        details.sort(key=lambda d: d.header.submitted_at, reverse=True)

        summaries = [
            InspectionSummary(
                inspection_id=d.header.inspection_id,
                asset_type=d.header.asset_type,
                asset_id=d.header.asset_id,
                checklist_id=d.header.checklist_id,
                revision_number=d.header.revision_number,
                submitted_at=d.header.submitted_at,
                inspector_user_id=d.header.inspector_user_id,
                pass_count=sum(1 for i in d.items if i.result == InspectionResultValue.PASS),
                fail_count=sum(1 for i in d.items if i.result == InspectionResultValue.FAIL),
                na_count=sum(1 for i in d.items if i.result == InspectionResultValue.NA),
                has_fail=any(i.result == InspectionResultValue.FAIL for i in d.items),
            )
            for d in details
        ]
        page, total = _paginate(summaries, params)
        return page, total

    async def find_inspection_finding(self, finding_id: str) -> InspectionFinding | None:
        for detail in self._inspections.values():
            for finding in detail.findings:
                if finding.finding_id == finding_id:
                    return finding.model_copy(deep=True)
        return None

    async def find_inspection_result(self, result_id: str) -> InspectionItemResult | None:
        for detail in self._inspections.values():
            for item in detail.items:
                if item.result_id == result_id:
                    return item.model_copy(deep=True)
        return None

    async def list_inspection_findings(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: FindingStatus | None,
    ) -> list[InspectionFinding]:
        findings: list[InspectionFinding] = []
        for detail in self._inspections.values():
            for finding in detail.findings:
                if asset_type is not None and finding.asset_type != asset_type:
                    continue
                if asset_id is not None and finding.asset_id != asset_id:
                    continue
                if status is not None and finding.status != status:
                    continue
                findings.append(finding.model_copy(deep=True))
        findings.sort(key=lambda f: f.created_at, reverse=True)
        return findings

    # ---- PM plan / task revision (Phase 4) ----

    async def list_pm_plans(
        self, asset_type: AssetType | None, model_id: str | None
    ) -> list[PmPlan]:
        plans = list(self._pm_plans.values())
        if asset_type is not None:
            plans = [p for p in plans if p.asset_type == asset_type]
        if model_id is not None:
            plans = [p for p in plans if not p.model_ids or model_id in p.model_ids]
        plans.sort(key=lambda p: p.pm_plan_id)
        return [p.model_copy(deep=True) for p in plans]

    async def get_pm_plan(self, pm_plan_id: str) -> PmPlan | None:
        plan = self._pm_plans.get(pm_plan_id)
        return plan.model_copy(deep=True) if plan else None

    def _pm_task_revision_detail(self, revision: PmTaskRevision) -> PmTaskRevisionDetail | None:
        plan = self._pm_plans.get(revision.pm_plan_id)
        if plan is None:
            return None
        tasks = sorted(self._pm_tasks.get(revision.revision_id, []), key=lambda t: t.sequence)
        return PmTaskRevisionDetail(
            plan=plan.model_copy(deep=True),
            revision=revision.model_copy(deep=True),
            tasks=[t.model_copy(deep=True) for t in tasks],
        )

    async def get_active_pm_task_revision(self, pm_plan_id: str) -> PmTaskRevisionDetail | None:
        today = utc_now().date()
        candidates = [
            r
            for r in self._pm_task_revisions.values()
            if r.pm_plan_id == pm_plan_id and r.effective_date <= today
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda r: (r.effective_date, r.revision_number))
        return self._pm_task_revision_detail(latest)

    async def get_pm_task_revision(
        self, pm_plan_id: str, revision_id: str
    ) -> PmTaskRevisionDetail | None:
        revision = self._pm_task_revisions.get(revision_id)
        if revision is None or revision.pm_plan_id != pm_plan_id:
            return None
        return self._pm_task_revision_detail(revision)

    # ---- PM work order / work result (Phase 4) ----

    def _pm_work_order_detail(self, work_order: PmWorkOrder) -> PmWorkOrderDetail:
        results = sorted(
            self._pm_work_results.get(work_order.pm_work_order_id, []), key=lambda r: r.sequence
        )
        additions = sorted(
            self._pm_scope_additions.get(work_order.pm_work_order_id, []),
            key=lambda a: a.added_at,
        )
        return PmWorkOrderDetail(
            work_order=work_order.model_copy(deep=True),
            results=[r.model_copy(deep=True) for r in results],
            scope_additions=[a.model_copy(deep=True) for a in additions],
        )

    async def create_pm_work_order(
        self,
        asset_type: AssetType,
        asset_id: str,
        pm_plan_id: str,
        revision_id: str,
        due_reason: PmTriggerType | None,
        opened_by: str | None,
        note: str | None,
        opened_snapshot_id: str | None = None,
        scope_task_ids: list[str] | None = None,
    ) -> PmWorkOrder:
        self._pm_work_order_seq += 1
        work_order = PmWorkOrder(
            pm_work_order_id=f"PMWO-{self._pm_work_order_seq:04d}",
            asset_type=asset_type,
            asset_id=asset_id,
            pm_plan_id=pm_plan_id,
            revision_id=revision_id,
            due_reason=due_reason,
            status=PmWorkOrderStatus.OPEN,
            opened_at=utc_now(),
            opened_by=opened_by,
            note=note,
            opened_snapshot_id=opened_snapshot_id,
            scope_task_ids=list(scope_task_ids) if scope_task_ids else [],
        )
        self._pm_work_orders[work_order.pm_work_order_id] = work_order
        self._pm_work_results[work_order.pm_work_order_id] = []
        self._pm_scope_additions[work_order.pm_work_order_id] = []
        return work_order.model_copy(deep=True)

    async def add_pm_scope_task(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        added_by: str | None,
        reason: str,
    ) -> PmScopeAdditionAudit:
        work_order = self._pm_work_orders[pm_work_order_id]
        self._pm_work_orders[pm_work_order_id] = work_order.model_copy(
            update={"scope_task_ids": [*work_order.scope_task_ids, pm_task_id]}
        )
        audit = PmScopeAdditionAudit(
            pm_work_order_id=pm_work_order_id,
            pm_task_id=pm_task_id,
            added_by=added_by,
            added_at=utc_now(),
            reason=reason,
        )
        # Append-only: previous additions are never rewritten or removed.
        self._pm_scope_additions.setdefault(pm_work_order_id, []).append(audit)
        return audit.model_copy(deep=True)

    async def approve_pm_scope(
        self, pm_work_order_id: str, approved_by: str | None
    ) -> PmWorkOrder:
        work_order = self._pm_work_orders[pm_work_order_id]
        updated = work_order.model_copy(
            update={"scope_approved_at": utc_now(), "scope_approved_by": approved_by}
        )
        self._pm_work_orders[pm_work_order_id] = updated
        return updated.model_copy(deep=True)

    async def assign_pm_work_order(
        self,
        pm_work_order_id: str,
        primary_technician: str | None,
        collaborators: list[str],
        assigned_by: str | None = None,
    ) -> PmWorkOrder:
        work_order = self._pm_work_orders[pm_work_order_id]
        now = utc_now()
        new_assignments: list[tuple[str, AssignmentRole]] = []
        if primary_technician:
            new_assignments.append((primary_technician, AssignmentRole.PRIMARY))
        for collaborator in collaborators:
            new_assignments.append((collaborator, AssignmentRole.COLLABORATOR))
        new_keys = set(new_assignments)

        history = self._pm_assignment_history.setdefault(pm_work_order_id, [])
        for index, entry in enumerate(history):
            if entry.active_status and (entry.user_id, entry.assignment_role) not in new_keys:
                history[index] = entry.model_copy(update={"active_status": False, "ended_at": now})

        already_active = {
            (entry.user_id, entry.assignment_role) for entry in history if entry.active_status
        }
        for user_id, role in new_assignments:
            if (user_id, role) in already_active:
                continue
            self._pm_assignment_seq += 1
            history.append(
                PmAssignmentHistoryEntry(
                    pm_assignment_id=f"PASG-{self._pm_assignment_seq:04d}",
                    pm_work_order_id=pm_work_order_id,
                    user_id=user_id,
                    assignment_role=role,
                    assigned_at=now,
                    assigned_by_user_id=assigned_by,
                    active_status=True,
                )
            )

        updated = work_order.model_copy(
            update={
                "primary_technician": primary_technician,
                "collaborators": list(collaborators),
            }
        )
        self._pm_work_orders[pm_work_order_id] = updated
        return updated.model_copy(deep=True)

    async def list_pm_work_order_assignment_history(
        self, pm_work_order_id: str
    ) -> list[PmAssignmentHistoryEntry]:
        entries = sorted(
            self._pm_assignment_history.get(pm_work_order_id, []), key=lambda e: e.assigned_at
        )
        return [e.model_copy(deep=True) for e in entries]

    async def get_pm_work_order(self, pm_work_order_id: str) -> PmWorkOrderDetail | None:
        work_order = self._pm_work_orders.get(pm_work_order_id)
        if work_order is None:
            return None
        return self._pm_work_order_detail(work_order)

    async def list_pm_work_orders(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
        status: PmWorkOrderStatus | None = None,
        assigned_to: str | None = None,
    ) -> tuple[list[PmWorkOrderSummary], int]:
        work_orders = list(self._pm_work_orders.values())
        if asset_type is not None:
            work_orders = [w for w in work_orders if w.asset_type == asset_type]
        if asset_id is not None:
            work_orders = [w for w in work_orders if w.asset_id == asset_id]
        if status is not None:
            work_orders = [w for w in work_orders if w.status == status]
        if assigned_to is not None:
            # F1 cross-phase integration fix: derive "who is currently
            # assigned" from the same active `pm_work_order_assignment`
            # history `PmService.get_active_assignment` and PM task-result
            # authorization now treat as authoritative — never the
            # denormalized `primary_technician`/`collaborators` fields,
            # which can go stale between the two separate writes
            # `assign_pm_work_order` makes (Google Sheets has no
            # transactions). Mirrors `list_repairs`'s own REV06.2 fix.
            active_by_work_order_id = {
                w.pm_work_order_id: active_primary_and_collaborators(
                    self._pm_assignment_history.get(w.pm_work_order_id, [])
                )
                for w in work_orders
            }
            work_orders = [
                w
                for w in work_orders
                if assigned_to == active_by_work_order_id[w.pm_work_order_id][0]
                or assigned_to in active_by_work_order_id[w.pm_work_order_id][1]
            ]
        # Deterministic-ordering fix: `opened_at` alone ties when two
        # work orders are opened close enough together to get an equal
        # timestamp; `pm_work_order_id` breaks the tie deterministically
        # so the newest one is reliably first.
        work_orders.sort(key=lambda w: (w.opened_at, w.pm_work_order_id), reverse=True)

        summaries = [
            PmWorkOrderSummary(
                pm_work_order_id=w.pm_work_order_id,
                asset_type=w.asset_type,
                asset_id=w.asset_id,
                pm_plan_id=w.pm_plan_id,
                revision_id=w.revision_id,
                status=w.status,
                opened_at=w.opened_at,
                closed_at=w.closed_at,
                result_count=len(self._pm_work_results.get(w.pm_work_order_id, [])),
                primary_technician=w.primary_technician,
                collaborators=list(w.collaborators),
            )
            for w in work_orders
        ]
        page, total = _paginate(summaries, params)
        return page, total

    async def get_last_closed_pm_work_order(
        self, asset_type: AssetType, asset_id: str, pm_plan_id: str
    ) -> PmWorkOrderDetail | None:
        candidates = [
            w
            for w in self._pm_work_orders.values()
            if w.asset_type == asset_type
            and w.asset_id == asset_id
            and w.pm_plan_id == pm_plan_id
            and w.status == PmWorkOrderStatus.CLOSED
            and w.closed_at is not None
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda w: w.closed_at)
        return self._pm_work_order_detail(latest)

    async def close_pm_work_order(
        self,
        pm_work_order_id: str,
        closed_by: str | None,
        note: str | None,
        closed_snapshot_id: str | None = None,
    ) -> PmWorkOrder:
        work_order = self._pm_work_orders[pm_work_order_id]
        now = utc_now()
        updated = work_order.model_copy(
            update={
                "status": PmWorkOrderStatus.CLOSED,
                "closed_at": now,
                "closed_by": closed_by,
                "note": note if note is not None else work_order.note,
                "closed_snapshot_id": closed_snapshot_id,
            }
        )
        self._pm_work_orders[pm_work_order_id] = updated

        # Live UAT fix: closing a PM work order must end every currently-
        # active assignment (PRIMARY and collaborators), using this same
        # closure timestamp — pm_work_assignment history is authoritative
        # and must never keep reporting someone as still actively
        # assigned to a CLOSED work order. Non-destructive: end each row
        # in place, never delete it (mirrors close_repair's identical fix
        # and assign_pm_work_order's own ending logic, just with no
        # replacement row appended afterward).
        history = self._pm_assignment_history.setdefault(pm_work_order_id, [])
        for index, entry in enumerate(history):
            if entry.active_status:
                history[index] = entry.model_copy(update={"active_status": False, "ended_at": now})

        return updated.model_copy(deep=True)

    async def create_pm_work_result(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        revision_id: str,
        sequence: int,
        task_description: str,
        completed: bool,
        meter_snapshot_id: str | None,
        remark: str | None,
        used_parts: list[dict],
        evidence_attachment_ids: list[str],
        performed_by: str | None,
    ) -> PmWorkResult:
        self._pm_work_result_seq += 1
        result_id = f"PMWR-{self._pm_work_result_seq:04d}"
        performed_at = utc_now()

        built_parts: list[PmUsedPart] = []
        for part in used_parts:
            self._pm_used_part_seq += 1
            built_parts.append(
                PmUsedPart(
                    pm_used_part_id=f"PMUP-{self._pm_used_part_seq:04d}",
                    pm_work_result_id=result_id,
                    part_description=part["part_description"],
                    quantity=part.get("quantity"),
                    unit=part.get("unit"),
                    part_id=part.get("part_id"),
                    part_instance_id=part.get("part_instance_id"),
                    action=part.get("action"),
                    recorded_by=performed_by,
                    recorded_at=performed_at,
                )
            )

        result = PmWorkResult(
            pm_work_result_id=result_id,
            pm_work_order_id=pm_work_order_id,
            pm_task_id=pm_task_id,
            revision_id=revision_id,
            sequence=sequence,
            task_description=task_description,
            completed=completed,
            meter_snapshot_id=meter_snapshot_id,
            remark=remark,
            used_parts=built_parts,
            evidence_attachment_ids=list(evidence_attachment_ids),
            performed_by=performed_by,
            performed_at=performed_at,
        )
        # Append-only: never replaces an existing entry for this work order.
        self._pm_work_results.setdefault(pm_work_order_id, []).append(result)
        return result.model_copy(deep=True)

    async def find_pm_work_result(self, pm_work_result_id: str) -> PmWorkResult | None:
        for results in self._pm_work_results.values():
            for result in results:
                if result.pm_work_result_id == pm_work_result_id:
                    return result.model_copy(deep=True)
        return None

    # ---- Meter snapshot (Phase 4) ----

    async def create_meter_snapshot(
        self,
        asset_type: AssetType,
        asset_id: str,
        readings: list[MeterReading],
        recorded_by: str | None,
        is_automatic: bool = False,
        latitude: float | None = None,
        longitude: float | None = None,
        gps_observed_at=None,
        source_note: str | None = None,
    ) -> MeterSnapshot:
        self._meter_snapshot_seq += 1
        snapshot = MeterSnapshot(
            meter_snapshot_id=f"MSNAP-{self._meter_snapshot_seq:04d}",
            asset_type=asset_type,
            asset_id=asset_id,
            readings=[r.model_copy(deep=True) for r in readings],
            recorded_at=utc_now(),
            recorded_by=recorded_by,
            is_automatic=is_automatic,
            latitude=latitude,
            longitude=longitude,
            gps_observed_at=gps_observed_at,
            source_note=source_note,
        )
        self._meter_snapshots[snapshot.meter_snapshot_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def get_meter_snapshot(self, meter_snapshot_id: str) -> MeterSnapshot | None:
        snapshot = self._meter_snapshots.get(meter_snapshot_id)
        return snapshot.model_copy(deep=True) if snapshot else None

    async def list_meter_snapshots_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[MeterSnapshot]:
        return [
            s.model_copy(deep=True)
            for s in self._meter_snapshots.values()
            if s.asset_type == asset_type and s.asset_id == asset_id
        ]

    async def list_current_counters(self, vehicle_id: str) -> list[CurrentCounterReading]:
        return [r.model_copy(deep=True) for r in self._current_counters.get(vehicle_id, [])]

    async def get_current_location(self, vehicle_id: str) -> CurrentLocation | None:
        entry = self._current_locations.get(vehicle_id)
        return entry.model_copy(deep=True) if entry is not None else None

    async def upsert_current_location(
        self,
        vehicle_id: str,
        latitude: float | None,
        longitude: float | None,
        gps_time,
        received_at,
        source_device_id: str | None,
        source_component_id: str | None,
    ) -> CurrentLocation:
        entry = CurrentLocation(
            vehicle_id=vehicle_id,
            latitude=latitude,
            longitude=longitude,
            gps_time=gps_time,
            received_at=received_at,
            source_device_id=source_device_id,
            source_component_id=source_component_id,
        )
        # At most one row per vehicle: unconditionally replaces whatever
        # was there (create or overwrite) — the caller has already
        # decided this write should happen.
        self._current_locations[vehicle_id] = entry
        return entry.model_copy(deep=True)

    # ---- Repair (Phase 4) ----

    def _repair_detail(self, repair: Repair) -> RepairDetail:
        actions = sorted(
            self._repair_actions.get(repair.repair_id, []), key=lambda a: a.created_at
        )
        parts = sorted(
            self._repair_parts.get(repair.repair_id, []), key=lambda p: p.recorded_at
        )
        return RepairDetail(
            repair=repair.model_copy(deep=True),
            actions=[a.model_copy(deep=True) for a in actions],
            parts=[p.model_copy(deep=True) for p in parts],
        )

    async def create_repair(
        self,
        asset_type: AssetType,
        asset_id: str,
        source_type: RepairSourceType,
        source_id: str | None,
        category: str | None,
        symptom: str | None,
        meter_snapshot_id: str | None,
        opened_by: str | None,
        primary_technician: str | None = None,
        collaborators: list[str] | None = None,
    ) -> Repair:
        self._repair_seq += 1
        repair = Repair(
            repair_id=f"RPR-{self._repair_seq:04d}",
            asset_type=asset_type,
            asset_id=asset_id,
            source_type=source_type,
            source_id=source_id,
            category=category,
            symptom=symptom,
            meter_snapshot_id=meter_snapshot_id,
            status=RepairStatus.OPEN,
            opened_at=utc_now(),
            opened_by=opened_by,
            primary_technician=primary_technician,
            collaborators=list(collaborators) if collaborators else [],
        )
        self._repairs[repair.repair_id] = repair
        self._repair_actions[repair.repair_id] = []
        self._repair_parts[repair.repair_id] = []
        return repair.model_copy(deep=True)

    async def get_repair(self, repair_id: str) -> RepairDetail | None:
        repair = self._repairs.get(repair_id)
        if repair is None:
            return None
        return self._repair_detail(repair)

    async def find_repairs_by_source(
        self, source_type: RepairSourceType, source_id: str
    ) -> list[Repair]:
        return [
            r.model_copy(deep=True)
            for r in self._repairs.values()
            if r.source_type == source_type and r.source_id == source_id
        ]

    async def list_repairs(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: RepairStatus | None,
        params: PageParams,
        assigned_to: str | None = None,
        unassigned_only: bool = False,
    ) -> tuple[list[RepairSummary], int]:
        repairs = list(self._repairs.values())
        if asset_type is not None:
            repairs = [r for r in repairs if r.asset_type == asset_type]
        if asset_id is not None:
            repairs = [r for r in repairs if r.asset_id == asset_id]
        if status is not None:
            repairs = [r for r in repairs if r.status == status]
        if assigned_to is not None or unassigned_only:
            # REV06.2 (independent-audit MEDIUM fix): derive "who is
            # currently assigned" from the same active `repair_assignment`
            # history `RepairService.get_active_assignment` and Repair
            # action/part authorization already treat as authoritative —
            # never the denormalized `primary_technician`/`collaborators`
            # fields, which can go stale between the two separate writes
            # `assign_repair` makes (Google Sheets has no transactions).
            active_by_repair_id = {
                r.repair_id: active_primary_and_collaborators(
                    self._repair_assignment_history.get(r.repair_id, [])
                )
                for r in repairs
            }
            if assigned_to is not None:
                repairs = [
                    r
                    for r in repairs
                    if assigned_to == active_by_repair_id[r.repair_id][0]
                    or assigned_to in active_by_repair_id[r.repair_id][1]
                ]
            if unassigned_only:
                repairs = [r for r in repairs if active_by_repair_id[r.repair_id][0] is None]
        # Phase 7 Batch 7C2: repair_id breaks opened_at ties (string order).
        repairs.sort(key=lambda r: (r.opened_at, r.repair_id), reverse=True)

        summaries = [
            RepairSummary(
                repair_id=r.repair_id,
                asset_type=r.asset_type,
                asset_id=r.asset_id,
                source_type=r.source_type,
                source_id=r.source_id,
                status=r.status,
                opened_at=r.opened_at,
                closed_at=r.closed_at,
                action_count=len(self._repair_actions.get(r.repair_id, [])),
                primary_technician=r.primary_technician,
                collaborators=list(r.collaborators),
                symptom=r.symptom,
            )
            for r in repairs
        ]
        page, total = _paginate(summaries, params)
        return page, total

    async def list_open_repairs_for_report(
        self, asset_type: AssetType | None, params: PageParams
    ) -> tuple[list[RepairSummary], int]:
        # Mock repairs are already typed models (no raw headers to
        # validate): the report is exactly the legacy OPEN list.
        return await self.list_repairs(
            asset_type=asset_type, asset_id=None, status=RepairStatus.OPEN, params=params
        )

    async def assign_repair(
        self,
        repair_id: str,
        primary_technician: str | None,
        collaborators: list[str],
        assigned_by: str | None = None,
    ) -> Repair:
        repair = self._repairs[repair_id]
        now = utc_now()
        new_assignments: list[tuple[str, AssignmentRole]] = []
        if primary_technician:
            new_assignments.append((primary_technician, AssignmentRole.PRIMARY))
        for collaborator in collaborators:
            new_assignments.append((collaborator, AssignmentRole.COLLABORATOR))
        new_keys = set(new_assignments)

        history = self._repair_assignment_history.setdefault(repair_id, [])
        for index, entry in enumerate(history):
            if entry.active_status and (entry.user_id, entry.assignment_role) not in new_keys:
                # Non-destructive: end the row, never delete it.
                history[index] = entry.model_copy(update={"active_status": False, "ended_at": now})

        already_active = {
            (entry.user_id, entry.assignment_role) for entry in history if entry.active_status
        }
        for user_id, role in new_assignments:
            if (user_id, role) in already_active:
                continue
            self._repair_assignment_seq += 1
            history.append(
                RepairAssignmentHistoryEntry(
                    repair_assignment_id=f"RASG-{self._repair_assignment_seq:04d}",
                    repair_id=repair_id,
                    user_id=user_id,
                    assignment_role=role,
                    assigned_at=now,
                    assigned_by_user_id=assigned_by,
                    active_status=True,
                )
            )

        updated = repair.model_copy(
            update={
                "primary_technician": primary_technician,
                "collaborators": list(collaborators),
            }
        )
        self._repairs[repair_id] = updated
        return updated.model_copy(deep=True)

    async def list_repair_assignment_history(
        self, repair_id: str
    ) -> list[RepairAssignmentHistoryEntry]:
        entries = sorted(
            self._repair_assignment_history.get(repair_id, []), key=lambda e: e.assigned_at
        )
        return [e.model_copy(deep=True) for e in entries]

    # ---- Repair Request (Core Demo Fixes Delta REV05 section 3) ----

    async def create_repair_request(
        self,
        vehicle_id: str,
        reported_by_user_id: str | None,
        reporter_type: str | None,
        reporter_driver_id: str | None,
        reporter_name_snapshot_th: str | None,
        report_channel: str | None,
        symptom_th: str | None,
        priority: str | None,
        note_th: str | None,
        meter_snapshot_id: str | None = None,
    ) -> RepairRequest:
        self._repair_request_seq += 1
        request = RepairRequest(
            repair_request_id=f"RRQ-{self._repair_request_seq:04d}",
            vehicle_id=vehicle_id,
            reported_at=utc_now(),
            reported_by_user_id=reported_by_user_id,
            reporter_type=reporter_type,
            reporter_driver_id=reporter_driver_id,
            reporter_name_snapshot_th=reporter_name_snapshot_th,
            report_channel=report_channel,
            symptom_th=symptom_th,
            priority=priority,
            request_status=REPAIR_REQUEST_STATUS_PENDING,
            note_th=note_th,
            meter_snapshot_id=meter_snapshot_id,
        )
        self._repair_requests[request.repair_request_id] = request
        return request.model_copy(deep=True)

    async def get_repair_request(self, repair_request_id: str) -> RepairRequest | None:
        request = self._repair_requests.get(repair_request_id)
        return request.model_copy(deep=True) if request else None

    async def list_pending_repair_requests(
        self, params: PageParams
    ) -> tuple[list[RepairRequest], int]:
        pending = [
            r
            for r in self._repair_requests.values()
            if r.request_status == REPAIR_REQUEST_STATUS_PENDING
        ]
        pending.sort(key=lambda r: r.reported_at)
        page, total = _paginate(pending, params)
        return [r.model_copy(deep=True) for r in page], total

    async def list_repair_requests_by_reporter(
        self, reported_by_user_id: str, params: PageParams
    ) -> tuple[list[RepairRequest], int]:
        mine = [
            r
            for r in self._repair_requests.values()
            if r.reported_by_user_id == reported_by_user_id
        ]
        mine.sort(key=lambda r: r.reported_at, reverse=True)
        page, total = _paginate(mine, params)
        return [r.model_copy(deep=True) for r in page], total

    async def list_repair_requests_by_source(
        self, source_type: str, source_id: str
    ) -> list[RepairRequest]:
        matches = []
        for r in self._repair_requests.values():
            decoded_type, decoded_id, _ = decode_provenance_note(r.note_th)
            if decoded_type == source_type and decoded_id == source_id:
                matches.append(r)
        matches.sort(key=lambda r: r.reported_at)
        return [r.model_copy(deep=True) for r in matches]

    async def mark_repair_request_converted(
        self,
        repair_request_id: str,
        repair_id: str,
        reviewed_by_user_id: str | None,
    ) -> RepairRequest:
        request = self._repair_requests[repair_request_id]
        now = utc_now()
        updated = request.model_copy(
            update={
                "request_status": REPAIR_REQUEST_STATUS_CONVERTED,
                "reviewed_by_user_id": reviewed_by_user_id,
                "reviewed_at": now,
                "repair_id": repair_id,
                "converted_at": now,
            }
        )
        self._repair_requests[repair_request_id] = updated
        return updated.model_copy(deep=True)

    async def add_repair_action(
        self,
        repair_id: str,
        action_text: str,
        actor: str | None,
        attachment_ids: list[str],
    ) -> None:
        self._repair_action_seq += 1
        action = RepairAction(
            repair_action_id=f"RPRA-{self._repair_action_seq:04d}",
            repair_id=repair_id,
            action_text=action_text,
            actor=actor,
            created_at=utc_now(),
            attachment_ids=list(attachment_ids),
        )
        # Append-only: previous actions are never rewritten or removed.
        self._repair_actions.setdefault(repair_id, []).append(action)

    async def add_repair_part(
        self,
        repair_id: str,
        part_description: str,
        quantity: float | None,
        unit: str | None,
        recorded_by: str | None,
        part_id: str | None = None,
        part_instance_id: str | None = None,
        action: PartActionType | None = None,
    ) -> None:
        self._repair_part_seq += 1
        part = RepairPart(
            repair_part_id=f"RPRP-{self._repair_part_seq:04d}",
            repair_id=repair_id,
            part_description=part_description,
            quantity=quantity,
            unit=unit,
            part_id=part_id,
            part_instance_id=part_instance_id,
            action=action,
            recorded_by=recorded_by,
            recorded_at=utc_now(),
        )
        self._repair_parts.setdefault(repair_id, []).append(part)

    async def close_repair(
        self,
        repair_id: str,
        closed_by: str | None,
        close_note: str | None,
        closed_snapshot_id: str | None = None,
    ) -> Repair:
        repair = self._repairs[repair_id]
        now = utc_now()
        updated = repair.model_copy(
            update={
                "status": RepairStatus.CLOSED,
                "closed_at": now,
                "closed_by": closed_by,
                "close_note": close_note,
                "closed_snapshot_id": closed_snapshot_id,
            }
        )
        self._repairs[repair_id] = updated

        # Live UAT fix: closing a repair must end every currently-active
        # assignment (PRIMARY and collaborators), using this same closure
        # timestamp — repair_assignment history is authoritative and must
        # never keep reporting someone as still actively assigned to a
        # CLOSED repair. Non-destructive: end each row in place, never
        # delete it (mirrors assign_repair's own ending logic, just with
        # no replacement row appended afterward).
        history = self._repair_assignment_history.setdefault(repair_id, [])
        for index, entry in enumerate(history):
            if entry.active_status:
                history[index] = entry.model_copy(update={"active_status": False, "ended_at": now})

        return updated.model_copy(deep=True)

    # ---- Part Master / Part Set (Phase 5) ----

    async def create_part_master(
        self,
        part_code: str,
        name: str,
        specification: str | None,
        manufacturer: str | None,
        part_number: str | None,
        tracking_mode: TrackingMode,
        category: str | None,
        metadata: dict[str, str],
    ) -> PartMaster:
        self._part_master_seq += 1
        now = utc_now()
        part = PartMaster(
            part_id=f"PART-{self._part_master_seq:04d}",
            part_code=part_code,
            name=name,
            specification=specification,
            manufacturer=manufacturer,
            part_number=part_number,
            tracking_mode=tracking_mode,
            category=category,
            is_active=True,
            metadata=dict(metadata),
            created_at=now,
            updated_at=now,
        )
        self._part_masters[part.part_id] = part
        return part.model_copy(deep=True)

    async def get_part_master(self, part_id: str) -> PartMaster | None:
        part = self._part_masters.get(part_id)
        return part.model_copy(deep=True) if part else None

    async def list_part_masters(
        self, q: str | None, tracking_mode: TrackingMode | None, params: PageParams
    ) -> tuple[list[PartMaster], int]:
        items = list(self._part_masters.values())
        if q:
            needle = q.strip().lower()
            items = [
                p
                for p in items
                if needle in p.name.lower()
                or needle in p.part_code.lower()
                or (p.specification and needle in p.specification.lower())
            ]
        if tracking_mode is not None:
            items = [p for p in items if p.tracking_mode == tracking_mode]
        items.sort(key=lambda p: p.part_id)
        page, total = _paginate(items, params)
        return page, total

    async def create_part_set(self, set_code: str, name: str) -> PartSet:
        self._part_set_seq += 1
        now = utc_now()
        part_set = PartSet(
            part_set_id=f"PSET-{self._part_set_seq:04d}",
            set_code=set_code,
            name=name,
            created_at=now,
            updated_at=now,
        )
        self._part_sets[part_set.part_set_id] = part_set
        return part_set.model_copy(deep=True)

    async def get_part_set(self, part_set_id: str) -> PartSet | None:
        part_set = self._part_sets.get(part_set_id)
        return part_set.model_copy(deep=True) if part_set else None

    def _part_set_revision_detail(
        self, revision: PartSetRevision
    ) -> PartSetRevisionDetail | None:
        part_set = self._part_sets.get(revision.part_set_id)
        if part_set is None:
            return None
        items = sorted(
            self._part_set_items.get(revision.revision_id, []),
            key=lambda i: i.part_set_item_id,
        )
        return PartSetRevisionDetail(
            part_set=part_set.model_copy(deep=True),
            revision=revision.model_copy(deep=True),
            items=[i.model_copy(deep=True) for i in items],
        )

    async def create_part_set_revision(
        self, part_set_id: str, effective_date, items: list[dict]
    ) -> PartSetRevisionDetail:
        self._part_set_revision_seq += 1
        revision_number = (
            sum(1 for r in self._part_set_revisions.values() if r.part_set_id == part_set_id) + 1
        )
        revision = PartSetRevision(
            revision_id=f"PSREV-{self._part_set_revision_seq:04d}",
            part_set_id=part_set_id,
            revision_number=revision_number,
            effective_date=effective_date,
            created_at=utc_now(),
        )
        self._part_set_revisions[revision.revision_id] = revision

        built_items: list[PartSetItem] = []
        for item in items:
            self._part_set_item_seq += 1
            built_items.append(
                PartSetItem(
                    part_set_item_id=f"PSITEM-{self._part_set_item_seq:04d}",
                    revision_id=revision.revision_id,
                    part_id=item["part_id"],
                    requirement=item["requirement"],
                    quantity=item.get("quantity"),
                    unit=item.get("unit"),
                    note=item.get("note"),
                )
            )
        # A new revision is an entirely new set of items — never an edit
        # of a previous revision's items (baseline section 15).
        self._part_set_items[revision.revision_id] = built_items
        return self._part_set_revision_detail(revision)

    async def get_active_part_set_revision(
        self, part_set_id: str
    ) -> PartSetRevisionDetail | None:
        today = utc_now().date()
        candidates = [
            r
            for r in self._part_set_revisions.values()
            if r.part_set_id == part_set_id and r.effective_date <= today
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda r: (r.effective_date, r.revision_number))
        return self._part_set_revision_detail(latest)

    async def get_part_set_revision(
        self, part_set_id: str, revision_id: str
    ) -> PartSetRevisionDetail | None:
        revision = self._part_set_revisions.get(revision_id)
        if revision is None or revision.part_set_id != part_set_id:
            return None
        return self._part_set_revision_detail(revision)

    # ---- Part Instance / lifecycle / installation segment (Phase 5) ----

    def _part_instance_detail(self, instance: PartInstance) -> PartInstanceDetail:
        lifecycles = sorted(
            self._part_lifecycles.get(instance.part_instance_id, []),
            key=lambda lc: lc.cycle_number,
        )
        segments = sorted(
            self._installation_segments.get(instance.part_instance_id, []),
            key=lambda s: s.installed_at,
        )
        return PartInstanceDetail(
            instance=instance.model_copy(deep=True),
            lifecycles=[lc.model_copy(deep=True) for lc in lifecycles],
            segments=[s.model_copy(deep=True) for s in segments],
        )

    async def create_part_instance(
        self,
        part_id: str,
        serial_number: str | None,
        prior_usage: PriorUsage,
        note: str | None,
        created_by: str | None,
    ) -> PartInstanceDetail:
        self._part_instance_seq += 1
        instance_id = f"PINST-{self._part_instance_seq:04d}"
        now = utc_now()

        self._part_lifecycle_seq += 1
        lifecycle = PartLifecycle(
            lifecycle_id=f"PLC-{self._part_lifecycle_seq:04d}",
            part_instance_id=instance_id,
            cycle_number=1,
            start_reason=LifecycleStartReason.ENROLLMENT,
            started_at=now,
            started_by=created_by,
            started_note=None,
            ended_at=None,
        )
        self._part_lifecycles[instance_id] = [lifecycle]
        self._installation_segments[instance_id] = []

        instance = PartInstance(
            part_instance_id=instance_id,
            part_id=part_id,
            serial_number=serial_number,
            status=PartInstanceStatus.READY_FOR_INSTALL,
            prior_usage=prior_usage.model_copy(deep=True),
            current_lifecycle_id=lifecycle.lifecycle_id,
            note=note,
            created_at=now,
            updated_at=now,
        )
        self._part_instances[instance_id] = instance
        return self._part_instance_detail(instance)

    async def get_part_instance(self, part_instance_id: str) -> PartInstanceDetail | None:
        instance = self._part_instances.get(part_instance_id)
        if instance is None:
            return None
        return self._part_instance_detail(instance)

    async def list_part_instances(
        self, part_id: str | None, status: PartInstanceStatus | None, params: PageParams
    ) -> tuple[list[PartInstanceDetail], int]:
        instances = list(self._part_instances.values())
        if part_id is not None:
            instances = [i for i in instances if i.part_id == part_id]
        if status is not None:
            instances = [i for i in instances if i.status == status]
        instances.sort(key=lambda i: i.part_instance_id)
        page, total = _paginate(instances, params)
        return [self._part_instance_detail(i) for i in page], total

    async def update_part_instance_status(
        self, part_instance_id: str, status: PartInstanceStatus
    ) -> None:
        instance = self._part_instances[part_instance_id]
        self._part_instances[part_instance_id] = instance.model_copy(
            update={"status": status, "updated_at": utc_now()}
        )

    async def create_installation_segment(
        self,
        part_instance_id: str,
        lifecycle_id: str,
        asset_type: AssetType,
        asset_id: str,
        position_code: str | None,
        installed_by: str | None,
        baseline_meter_snapshot_id: str | None,
        install_note: str | None,
    ) -> InstallationSegment:
        self._installation_segment_seq += 1
        segment = InstallationSegment(
            segment_id=f"SEG-{self._installation_segment_seq:04d}",
            part_instance_id=part_instance_id,
            lifecycle_id=lifecycle_id,
            asset_type=asset_type,
            asset_id=asset_id,
            position_code=position_code,
            status=InstallationSegmentStatus.ACTIVE,
            installed_at=utc_now(),
            installed_by=installed_by,
            baseline_meter_snapshot_id=baseline_meter_snapshot_id,
            install_note=install_note,
        )
        # Append-only: previous segments are never rewritten or removed.
        self._installation_segments.setdefault(part_instance_id, []).append(segment)
        return segment.model_copy(deep=True)

    async def close_installation_segment(
        self,
        segment_id: str,
        removed_by: str | None,
        removal_meter_snapshot_id: str | None,
        removal_reason: str | None,
    ) -> InstallationSegment:
        for segments in self._installation_segments.values():
            for index, segment in enumerate(segments):
                if segment.segment_id == segment_id:
                    updated = segment.model_copy(
                        update={
                            "status": InstallationSegmentStatus.CLOSED,
                            "removed_at": utc_now(),
                            "removed_by": removed_by,
                            "removal_meter_snapshot_id": removal_meter_snapshot_id,
                            "removal_reason": removal_reason,
                        }
                    )
                    segments[index] = updated
                    return updated.model_copy(deep=True)
        raise KeyError(f"Installation segment '{segment_id}' was not found")

    async def start_new_part_lifecycle(
        self,
        part_instance_id: str,
        start_reason: LifecycleStartReason,
        started_note: str | None,
        started_by: str | None,
    ) -> None:
        lifecycles = self._part_lifecycles[part_instance_id]
        now = utc_now()
        current = lifecycles[-1]
        # The previous lifecycle is never removed or rewritten beyond
        # setting `ended_at` — its own installation segments stay
        # associated with its `lifecycle_id` and remain fully readable
        # (OPEN_DECISIONS_REGISTER_EN.txt G04: "preserve all old lifecycle
        # history").
        lifecycles[-1] = current.model_copy(update={"ended_at": now})
        self._part_lifecycle_seq += 1
        new_lifecycle = PartLifecycle(
            lifecycle_id=f"PLC-{self._part_lifecycle_seq:04d}",
            part_instance_id=part_instance_id,
            cycle_number=current.cycle_number + 1,
            start_reason=start_reason,
            started_at=now,
            started_by=started_by,
            started_note=started_note,
            ended_at=None,
        )
        lifecycles.append(new_lifecycle)
        instance = self._part_instances[part_instance_id]
        self._part_instances[part_instance_id] = instance.model_copy(
            update={"current_lifecycle_id": new_lifecycle.lifecycle_id, "updated_at": now}
        )

    # ---- Position lifetime (Phase 5) ----

    async def create_position_lifetime(
        self,
        asset_type: AssetType,
        asset_id: str,
        position_code: str,
        part_id: str | None,
        lifetime_rule_id: str | None,
        baseline_meter_snapshot_id: str | None,
        prior_usage: PriorUsage,
        started_by: str | None,
        note: str | None,
    ) -> PositionLifetimeRecord:
        self._position_lifetime_seq += 1
        record = PositionLifetimeRecord(
            position_lifetime_id=f"POSLT-{self._position_lifetime_seq:04d}",
            asset_type=asset_type,
            asset_id=asset_id,
            position_code=position_code,
            part_id=part_id,
            lifetime_rule_id=lifetime_rule_id,
            baseline_meter_snapshot_id=baseline_meter_snapshot_id,
            prior_usage=prior_usage.model_copy(deep=True),
            started_at=utc_now(),
            started_by=started_by,
            note=note,
        )
        self._position_lifetime[record.position_lifetime_id] = record
        return record.model_copy(deep=True)

    async def get_position_lifetime(
        self, position_lifetime_id: str
    ) -> PositionLifetimeRecord | None:
        record = self._position_lifetime.get(position_lifetime_id)
        return record.model_copy(deep=True) if record else None

    async def list_position_lifetime_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[PositionLifetimeRecord]:
        records = [
            r
            for r in self._position_lifetime.values()
            if r.asset_type == asset_type and r.asset_id == asset_id
        ]
        records.sort(key=lambda r: r.started_at)
        return [r.model_copy(deep=True) for r in records]

    # ---- Lifetime rule (Phase 5) ----

    async def create_lifetime_rule(
        self,
        part_id: str,
        scope: LifetimeRuleScope,
        model_id: str | None,
        vehicle_id: str | None,
        trigger_type: LifetimeTriggerType,
        component_role: ComponentRole | None,
        first_due_value: float | None,
        interval_value: float | None,
        warning_window_value: float | None,
        note: str | None,
    ) -> LifetimeRule:
        self._lifetime_rule_seq += 1
        rule = LifetimeRule(
            lifetime_rule_id=f"LTR-{self._lifetime_rule_seq:04d}",
            part_id=part_id,
            scope=scope,
            model_id=model_id,
            vehicle_id=vehicle_id,
            trigger_type=trigger_type,
            component_role=component_role,
            first_due_value=first_due_value,
            interval_value=interval_value,
            warning_window_value=warning_window_value,
            note=note,
            created_at=utc_now(),
        )
        self._lifetime_rules[rule.lifetime_rule_id] = rule
        return rule.model_copy(deep=True)

    async def get_lifetime_rule(self, lifetime_rule_id: str) -> LifetimeRule | None:
        rule = self._lifetime_rules.get(lifetime_rule_id)
        return rule.model_copy(deep=True) if rule else None

    async def list_lifetime_rules_for_part(self, part_id: str) -> list[LifetimeRule]:
        rules = [r for r in self._lifetime_rules.values() if r.part_id == part_id]
        rules.sort(key=lambda r: r.lifetime_rule_id)
        return [r.model_copy(deep=True) for r in rules]

    # ---- Location snapshot (Core Demo Fixes Delta section E) ----

    async def create_location_snapshot(
        self,
        event_type: str,
        event_id: str,
        vehicle_id: str | None,
        device_id: str | None,
        latitude: float | None,
        longitude: float | None,
        altitude_m: float | None,
        accuracy_m: float | None,
        gps_time,
        received_at,
        gps_valid: bool,
        source: str | None,
    ) -> LocationSnapshot:
        self._location_snapshot_seq += 1
        snapshot = LocationSnapshot(
            location_snapshot_id=f"LOCSNAP-{self._location_snapshot_seq:04d}",
            event_type=event_type,
            event_id=event_id,
            vehicle_id=vehicle_id,
            device_id=device_id,
            latitude=latitude,
            longitude=longitude,
            altitude_m=altitude_m,
            accuracy_m=accuracy_m,
            gps_time=gps_time,
            received_at=received_at,
            snapshot_at=utc_now(),
            gps_valid=gps_valid,
            source=source,
        )
        self._location_snapshots[snapshot.location_snapshot_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def get_location_snapshot(self, location_snapshot_id: str) -> LocationSnapshot | None:
        snapshot = self._location_snapshots.get(location_snapshot_id)
        return snapshot.model_copy(deep=True) if snapshot else None

    async def list_location_snapshots_for_event(self, event_id: str) -> list[LocationSnapshot]:
        return [
            s.model_copy(deep=True)
            for s in self._location_snapshots.values()
            if s.event_id == event_id
        ]

    # ---- Material request (Core Demo Fixes Delta, Store/Inventory boundary) ----

    async def create_material_request(
        self,
        source_type: RequisitionSourceType,
        source_work_order_id: str,
        vehicle_id: str | None,
        created_by: str | None,
        note: str | None = None,
    ) -> MaterialRequest:
        self._material_request_seq += 1
        request = MaterialRequest(
            material_request_id=f"MREQ-{self._material_request_seq:04d}",
            source_type=source_type,
            source_work_order_id=source_work_order_id,
            vehicle_id=vehicle_id,
            created_at=utc_now(),
            created_by=created_by,
            note=note,
        )
        self._material_requests[request.material_request_id] = request
        self._requisition_lines[request.material_request_id] = []
        return request.model_copy(deep=True)

    async def get_material_request(self, material_request_id: str) -> MaterialRequestDetail | None:
        request = self._material_requests.get(material_request_id)
        if request is None:
            return None
        lines = self._requisition_lines.get(material_request_id, [])
        return MaterialRequestDetail(
            request=request.model_copy(deep=True),
            lines=[line.model_copy(deep=True) for line in lines],
        )

    async def list_material_requests_for_work_order(
        self, source_work_order_id: str
    ) -> list[MaterialRequest]:
        requests = [
            r for r in self._material_requests.values() if r.source_work_order_id == source_work_order_id
        ]
        requests.sort(key=lambda r: r.created_at)
        return [r.model_copy(deep=True) for r in requests]

    async def create_requisition_line(
        self,
        material_request_id: str,
        part_id: str | None,
        part_instance_id: str | None,
        part_code_snapshot: str | None,
        part_description: str,
        requested_quantity: float | None,
        unit: str | None,
        source_task_revision_id: str | None,
        line_source: str | None,
        created_by: str | None,
    ) -> RequisitionLine:
        self._requisition_line_seq += 1
        line = RequisitionLine(
            requisition_line_id=f"REQL-{self._requisition_line_seq:04d}",
            material_request_id=material_request_id,
            source_task_revision_id=source_task_revision_id,
            part_id=part_id,
            part_instance_id=part_instance_id,
            part_code_snapshot=part_code_snapshot,
            part_description=part_description,
            requested_quantity=requested_quantity,
            unit=unit,
            line_source=line_source,
            created_at=utc_now(),
            created_by=created_by,
        )
        self._requisition_lines.setdefault(material_request_id, []).append(line)
        return line.model_copy(deep=True)

    async def list_requisition_lines_for_work_order(
        self, work_order_reference: str
    ) -> list[RequisitionLine]:
        requests = await self.list_material_requests_for_work_order(work_order_reference)
        lines: list[RequisitionLine] = []
        for request in requests:
            lines.extend(self._requisition_lines.get(request.material_request_id, []))
        return [line.model_copy(deep=True) for line in lines]

    # ---- Driver / Operator (Web/API Phase 6 Batch 1) ----

    async def create_driver(
        self,
        driver_name_th: str,
        phone: str | None,
        license_no: str | None,
        license_expiry_date,
        active_status: str | None,
        note_th: str | None,
    ) -> Driver:
        self._driver_seq += 1
        driver = Driver(
            driver_id=f"DRV-{self._driver_seq:04d}",
            driver_name_th=driver_name_th,
            phone=phone,
            license_no=license_no,
            license_expiry_date=license_expiry_date,
            active_status=active_status,
            note_th=note_th,
        )
        self._drivers[driver.driver_id] = driver
        return driver.model_copy(deep=True)

    async def get_driver(self, driver_id: str) -> Driver | None:
        driver = self._drivers.get(driver_id)
        return driver.model_copy(deep=True) if driver else None

    async def list_drivers(
        self, q: str | None, params: PageParams
    ) -> tuple[list[Driver], int]:
        items = list(self._drivers.values())
        if q:
            needle = q.strip().lower()
            items = [
                d
                for d in items
                if needle in d.driver_name_th.lower()
                or (d.phone and needle in d.phone.lower())
                or (d.license_no and needle in d.license_no.lower())
            ]
        items.sort(key=lambda d: d.driver_id)
        page, total = _paginate(items, params)
        return page, total

    async def update_driver(
        self,
        driver_id: str,
        driver_name_th: str,
        phone: str | None,
        license_no: str | None,
        license_expiry_date,
        active_status: str | None,
        note_th: str | None,
    ) -> Driver:
        driver = self._drivers[driver_id]
        updated = driver.model_copy(
            update={
                "driver_name_th": driver_name_th,
                "phone": phone,
                "license_no": license_no,
                "license_expiry_date": license_expiry_date,
                "active_status": active_status,
                "note_th": note_th,
            }
        )
        self._drivers[driver_id] = updated
        return updated.model_copy(deep=True)

    async def create_vehicle_driver_assignment(
        self,
        vehicle_id: str,
        driver_id: str,
        start_at,
        is_primary: bool,
        assignment_status: str | None,
        changed_by_user_id: str | None,
        note_th: str | None,
    ) -> VehicleDriverAssignment:
        self._vehicle_driver_assignment_seq += 1
        entry = VehicleDriverAssignment(
            assignment_id=f"VDRV-{self._vehicle_driver_assignment_seq:04d}",
            vehicle_id=vehicle_id,
            driver_id=driver_id,
            start_at=start_at,
            end_at=None,
            is_primary=is_primary,
            assignment_status=assignment_status,
            changed_by_user_id=changed_by_user_id,
            note_th=note_th,
        )
        # Append-only: no existing row is ever rewritten/removed here.
        self._vehicle_driver_assignments.setdefault(vehicle_id, []).append(entry)
        return entry.model_copy(deep=True)

    async def get_vehicle_driver_assignment(
        self, assignment_id: str
    ) -> VehicleDriverAssignment | None:
        for entries in self._vehicle_driver_assignments.values():
            for entry in entries:
                if entry.assignment_id == assignment_id:
                    return entry.model_copy(deep=True)
        return None

    async def end_vehicle_driver_assignment(
        self,
        assignment_id: str,
        end_at,
        changed_by_user_id: str | None,
    ) -> VehicleDriverAssignment:
        for vehicle_id, entries in self._vehicle_driver_assignments.items():
            for index, entry in enumerate(entries):
                if entry.assignment_id == assignment_id:
                    updated = entry.model_copy(
                        update={"end_at": end_at, "changed_by_user_id": changed_by_user_id}
                    )
                    entries[index] = updated
                    return updated.model_copy(deep=True)
        raise KeyError(assignment_id)

    async def list_vehicle_driver_assignments(
        self, vehicle_id: str
    ) -> list[VehicleDriverAssignment]:
        entries = sorted(
            self._vehicle_driver_assignments.get(vehicle_id, []),
            key=lambda e: e.start_at,
            reverse=True,
        )
        return [e.model_copy(deep=True) for e in entries]

    # ---- Vehicle Certificate (Web/API Phase 6 Batch 2A) ----

    async def create_vehicle_certificate(
        self,
        vehicle_id: str,
        certificate_type_code: str | None,
        certificate_type_name_th: str | None,
        document_no: str | None,
        issue_date,
        expiry_date,
        alert_lead_days: int | None,
        certificate_status: CertificateStatus | None,
        storage_ref: str | None,
        note_th: str | None,
        created_by_user_id: str | None,
        created_at,
    ) -> VehicleCertificate:
        self._vehicle_certificate_seq += 1
        entry = VehicleCertificate(
            certificate_id=f"CERT-{self._vehicle_certificate_seq:04d}",
            vehicle_id=vehicle_id,
            certificate_type_code=certificate_type_code,
            certificate_type_name_th=certificate_type_name_th,
            document_no=document_no,
            issue_date=issue_date,
            expiry_date=expiry_date,
            alert_lead_days=alert_lead_days,
            certificate_status=certificate_status,
            replaced_by_certificate_id=None,
            storage_ref=storage_ref,
            created_by_user_id=created_by_user_id,
            created_at=created_at,
            note_th=note_th,
        )
        # Append-only: no existing row is ever rewritten/removed here.
        self._vehicle_certificates.setdefault(vehicle_id, []).append(entry)
        return entry.model_copy(deep=True)

    async def get_vehicle_certificate(self, certificate_id: str) -> VehicleCertificate | None:
        for entries in self._vehicle_certificates.values():
            for entry in entries:
                if entry.certificate_id == certificate_id:
                    return entry.model_copy(deep=True)
        return None

    async def list_vehicle_certificates_for_vehicle(
        self, vehicle_id: str
    ) -> list[VehicleCertificate]:
        entries = sorted(
            self._vehicle_certificates.get(vehicle_id, []),
            key=lambda e: e.created_at,
            reverse=True,
        )
        return [e.model_copy(deep=True) for e in entries]

    def _find_vehicle_certificate_slot(self, certificate_id: str) -> tuple[str, int]:
        for vehicle_id, entries in self._vehicle_certificates.items():
            for index, entry in enumerate(entries):
                if entry.certificate_id == certificate_id:
                    return vehicle_id, index
        raise KeyError(certificate_id)

    async def mark_vehicle_certificate_replaced(
        self, certificate_id: str, replaced_by_certificate_id: str
    ) -> VehicleCertificate:
        vehicle_id, index = self._find_vehicle_certificate_slot(certificate_id)
        entries = self._vehicle_certificates[vehicle_id]
        # Non-destructive: replace the row in place, never delete/reorder.
        updated = entries[index].model_copy(
            update={
                "certificate_status": CertificateStatus.REPLACED,
                "replaced_by_certificate_id": replaced_by_certificate_id,
            }
        )
        entries[index] = updated
        return updated.model_copy(deep=True)

    async def mark_vehicle_certificate_expired(self, certificate_id: str) -> VehicleCertificate:
        vehicle_id, index = self._find_vehicle_certificate_slot(certificate_id)
        entries = self._vehicle_certificates[vehicle_id]
        updated = entries[index].model_copy(update={"certificate_status": CertificateStatus.EXPIRED})
        entries[index] = updated
        return updated.model_copy(deep=True)

    # ---- Certificate expiry report (Web/API Phase 7 Batch 7D2) ----

    async def read_vehicle_certificates_for_report(self) -> CertificateReportRead:
        """Read-only: every stored certificate in storage order, classified
        by the same rules and the same unchanged date parser as the
        Google Sheets read. Field values are taken as stored (typed
        values; `None` is absent, never the text "None"); mapping is a
        re-validation of a copy through the unchanged model."""
        # Imported here only for the shared, unchanged `_parse_date`
        # (mock and Sheets must classify expiry values identically).
        from app.repositories.google_sheets.repository import GoogleSheetsRepository

        fields = tuple(VehicleCertificate.model_fields)
        rows = []
        for entries in self._vehicle_certificates.values():
            for entry in entries:
                record = {name: getattr(entry, name, None) for name in fields}
                rows.append(
                    build_report_row(
                        read_index=len(rows),
                        record=record,
                        mapper=VehicleCertificate.model_validate,
                        parse_date=GoogleSheetsRepository._parse_date,
                        blank_status_value=None,
                    )
                )
        return CertificateReportRead(rows=rows)

    # ---- Vehicle Event (Web/API Phase 6 Batch 4A) ----

    async def find_vehicle_event_by_device_event(
        self, device_id: str, device_event_id: str
    ) -> VehicleEvent | None:
        for event in self._vehicle_events:
            if event.device_id == device_id and event.device_event_id == device_event_id:
                return event.model_copy(deep=True)
        return None

    async def create_vehicle_event(
        self,
        vehicle_id: str,
        device_id: str,
        component_id: str,
        event_type: VehicleEventType,
        event_time,
        fuel_level_value: float | None,
        fuel_level_unit: str | None,
        latitude: float | None,
        longitude: float | None,
        gps_valid: bool | None,
        note_th: str | None,
        device_event_id: str,
        sequence: int,
        created_offline: bool,
        time_quality: TimeQuality,
    ) -> VehicleEvent:
        self._vehicle_event_seq += 1
        event = VehicleEvent(
            event_id=f"EVT-{self._vehicle_event_seq:04d}",
            vehicle_id=vehicle_id,
            device_id=device_id,
            component_id=component_id,
            event_type=event_type,
            event_time=event_time,
            fuel_level_value=fuel_level_value,
            fuel_level_unit=fuel_level_unit,
            latitude=latitude,
            longitude=longitude,
            gps_valid=gps_valid,
            received_at=utc_now(),
            note_th=note_th,
            device_event_id=device_event_id,
            sequence=sequence,
            created_offline=created_offline,
            time_quality=time_quality,
        )
        # Append-only: no existing row is ever rewritten/removed here.
        self._vehicle_events.append(event)
        return event.model_copy(deep=True)

    async def get_vehicle_event(self, event_id: str) -> VehicleEvent | None:
        for event in self._vehicle_events:
            if event.event_id == event_id:
                return event.model_copy(deep=True)
        return None

    async def list_vehicle_events_for_vehicle(self, vehicle_id: str) -> list[VehicleEvent]:
        return [
            e.model_copy(deep=True) for e in self._vehicle_events if e.vehicle_id == vehicle_id
        ]

    # ---- Daily Summary (Web/API Phase 6 Batch 4C) ----

    async def upsert_daily_summary(
        self,
        summary_date,
        vehicle_id: str,
        component_id: str,
        metric_type: DailySummaryMetricType,
        value: float | None,
        unit: str,
        data_status: DailySummaryDataStatus,
    ) -> DailySummary:
        key = (summary_date, vehicle_id, component_id, metric_type)
        existing = self._daily_summaries.get(key)
        if existing is not None:
            # Targeted update: only the derived fields change;
            # daily_summary_id/created_at are always preserved.
            updated = existing.model_copy(
                update={"value": value, "unit": unit, "data_status": data_status}
            )
            self._daily_summaries[key] = updated
            return updated.model_copy(deep=True)
        self._daily_summary_seq += 1
        created = DailySummary(
            daily_summary_id=f"DSUM-{self._daily_summary_seq:04d}",
            summary_date=summary_date,
            vehicle_id=vehicle_id,
            component_id=component_id,
            metric_type=metric_type,
            value=value,
            unit=unit,
            data_status=data_status,
            created_at=utc_now(),
        )
        self._daily_summaries[key] = created
        return created.model_copy(deep=True)

    async def list_daily_summaries_for_vehicle(self, vehicle_id: str) -> list[DailySummary]:
        return [
            s.model_copy(deep=True)
            for s in self._daily_summaries.values()
            if s.vehicle_id == vehicle_id
        ]

    async def delete_daily_summary(self, daily_summary_id: str) -> None:
        # Idempotent no-op if already missing - matches the abstract
        # method's documented contract.
        stale_key = next(
            (
                key
                for key, summary in self._daily_summaries.items()
                if summary.daily_summary_id == daily_summary_id
            ),
            None,
        )
        if stale_key is not None:
            del self._daily_summaries[stale_key]

    # ---- Alert (Web/API Phase 6 Batch 5A) ----

    async def get_alert(self, alert_id: str) -> Alert | None:
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                return alert.model_copy(deep=True)
        return None

    async def list_alerts_for_vehicle(self, vehicle_id: str) -> list[Alert]:
        return [a.model_copy(deep=True) for a in self._alerts if a.vehicle_id == vehicle_id]

    # ---- Alert lifecycle (Web/API Phase 6 Batch 5B — D25, internal only) ----

    async def list_alerts_by_identity(
        self,
        vehicle_id: str,
        alert_type: str,
        source_type: str | None,
        source_id: str | None,
    ) -> list[Alert]:
        return [
            a.model_copy(deep=True)
            for a in self._alerts
            if a.vehicle_id == vehicle_id
            and a.alert_type == alert_type
            and a.source_type == source_type
            and a.source_id == source_id
        ]

    async def create_alert(self, alert: Alert) -> Alert:
        if any(a.alert_id == alert.alert_id for a in self._alerts):
            raise RepositoryError(
                f"Alert '{alert.alert_id}' already exists — refusing to create a duplicate row."
            )
        stored = alert.model_copy(deep=True)
        self._alerts.append(stored)
        return stored.model_copy(deep=True)

    async def update_alert_lifecycle(
        self,
        alert_id: str,
        *,
        alert_status: AlertStatus,
        muted_until,
        acknowledged_by_user_id: str | None,
        acknowledged_at,
        resolved_at,
    ) -> Alert:
        for index, alert in enumerate(self._alerts):
            if alert.alert_id == alert_id:
                updated = alert.model_copy(
                    update={
                        "alert_status": alert_status,
                        "muted_until": muted_until,
                        "acknowledged_by_user_id": acknowledged_by_user_id,
                        "acknowledged_at": acknowledged_at,
                        "resolved_at": resolved_at,
                    }
                )
                self._alerts[index] = updated
                return updated.model_copy(deep=True)
        raise RepositoryError(f"Alert '{alert_id}' was not found")

    # ---- Alert Setting (Web/API Phase 6 Batch 5C) ----

    async def list_alert_settings(self) -> list[AlertSetting]:
        return [s.model_copy(deep=True) for s in self._alert_settings]

    async def get_alert_setting(self, alert_setting_id: str) -> AlertSetting | None:
        for setting in self._alert_settings:
            if setting.alert_setting_id == alert_setting_id:
                return setting.model_copy(deep=True)
        return None

    async def list_alert_settings_for_type(self, alert_type: str) -> list[AlertSetting]:
        return [
            s.model_copy(deep=True) for s in self._alert_settings if s.alert_type == alert_type
        ]

    # ---- Model Document (Web/API Phase 6 Batch 3A) ----

    async def create_model_document(
        self,
        model_id: str,
        document_type: str | None,
        document_name_th: str | None,
        version: str | None,
        effective_from,
        effective_to,
        storage_ref: str | None,
        file_status: str | None,
        active_status: str | None,
        note_th: str | None,
    ) -> ModelDocument:
        self._model_document_seq += 1
        entry = ModelDocument(
            model_document_id=f"MDOC-{self._model_document_seq:04d}",
            model_id=model_id,
            document_type=document_type,
            document_name_th=document_name_th,
            version=version,
            effective_from=effective_from,
            effective_to=effective_to,
            storage_ref=storage_ref,
            file_status=file_status,
            active_status=active_status,
            replaced_by_document_id=None,
            note_th=note_th,
        )
        # Append-only: no existing row is ever rewritten/removed here.
        self._model_documents.setdefault(model_id, []).append(entry)
        return entry.model_copy(deep=True)

    async def get_model_document(self, model_document_id: str) -> ModelDocument | None:
        for entries in self._model_documents.values():
            for entry in entries:
                if entry.model_document_id == model_document_id:
                    return entry.model_copy(deep=True)
        return None

    async def list_model_documents_for_model(self, model_id: str) -> list[ModelDocument]:
        entries = self._model_documents.get(model_id, [])
        return [e.model_copy(deep=True) for e in entries]

    def _find_model_document_slot(self, model_document_id: str) -> tuple[str, int]:
        for model_id, entries in self._model_documents.items():
            for index, entry in enumerate(entries):
                if entry.model_document_id == model_document_id:
                    return model_id, index
        raise KeyError(model_document_id)

    async def finalize_model_document_revision(
        self, model_document_id: str, effective_to, replaced_by_document_id: str
    ) -> ModelDocument:
        model_id, index = self._find_model_document_slot(model_document_id)
        entries = self._model_documents[model_id]
        # Non-destructive: replace the row in place, never delete/reorder.
        updated = entries[index].model_copy(
            update={
                "effective_to": effective_to,
                "replaced_by_document_id": replaced_by_document_id,
            }
        )
        entries[index] = updated
        return updated.model_copy(deep=True)
