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
from app.domain.meter import MeterReading, MeterSnapshot
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
from app.domain.requisition import RequisitionLine, RequisitionSourceType
from app.domain.repair import (
    Repair,
    RepairAction,
    RepairDetail,
    RepairPart,
    RepairSourceType,
    RepairStatus,
    RepairSummary,
)
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import ComponentRole, VehicleModel
from app.repositories.base import Repository
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
        self._requisition_lines: dict[str, list[RequisitionLine]] = {}
        self._requisition_line_seq = 0

        # ---- Meter snapshot (Phase 4) ----
        self._meter_snapshots: dict[str, MeterSnapshot] = {}
        self._meter_snapshot_seq = 0

        # ---- Repair (Phase 4) ----
        self._repairs: dict[str, Repair] = {}
        self._repair_actions: dict[str, list[RepairAction]] = {}
        self._repair_parts: dict[str, list[RepairPart]] = {}
        self._repair_seq = 0
        self._repair_action_seq = 0
        self._repair_part_seq = 0

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
        ordered = sorted(entries, key=lambda e: e.changed_at, reverse=True)
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
        )
        self._attachments[attachment.attachment_id] = attachment
        return attachment.model_copy(deep=True)

    async def get_attachment(self, attachment_id: str) -> Attachment | None:
        attachment = self._attachments.get(attachment_id)
        return attachment.model_copy(deep=True) if attachment else None

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
    ) -> tuple[list[PmWorkOrderSummary], int]:
        work_orders = list(self._pm_work_orders.values())
        if asset_type is not None:
            work_orders = [w for w in work_orders if w.asset_type == asset_type]
        if asset_id is not None:
            work_orders = [w for w in work_orders if w.asset_id == asset_id]
        work_orders.sort(key=lambda w: w.opened_at, reverse=True)

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
        updated = work_order.model_copy(
            update={
                "status": PmWorkOrderStatus.CLOSED,
                "closed_at": utc_now(),
                "closed_by": closed_by,
                "note": note if note is not None else work_order.note,
                "closed_snapshot_id": closed_snapshot_id,
            }
        )
        self._pm_work_orders[pm_work_order_id] = updated
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

    async def list_repairs(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: RepairStatus | None,
        params: PageParams,
        assigned_to: str | None = None,
    ) -> tuple[list[RepairSummary], int]:
        repairs = list(self._repairs.values())
        if asset_type is not None:
            repairs = [r for r in repairs if r.asset_type == asset_type]
        if asset_id is not None:
            repairs = [r for r in repairs if r.asset_id == asset_id]
        if status is not None:
            repairs = [r for r in repairs if r.status == status]
        if assigned_to is not None:
            repairs = [
                r
                for r in repairs
                if r.primary_technician == assigned_to or assigned_to in r.collaborators
            ]
        repairs.sort(key=lambda r: r.opened_at, reverse=True)

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

    async def assign_repair(
        self,
        repair_id: str,
        primary_technician: str | None,
        collaborators: list[str],
    ) -> Repair:
        repair = self._repairs[repair_id]
        updated = repair.model_copy(
            update={
                "primary_technician": primary_technician,
                "collaborators": list(collaborators),
            }
        )
        self._repairs[repair_id] = updated
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
        updated = repair.model_copy(
            update={
                "status": RepairStatus.CLOSED,
                "closed_at": utc_now(),
                "closed_by": closed_by,
                "close_note": close_note,
                "closed_snapshot_id": closed_snapshot_id,
            }
        )
        self._repairs[repair_id] = updated
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

    # ---- Requisition line (Core Demo Fix, Store/Inventory boundary) ----

    async def create_requisition_line(
        self,
        work_order_reference: str,
        source_type: RequisitionSourceType,
        part_id: str | None,
        part_instance_id: str | None,
        part_description: str,
        requested_quantity: float | None,
        unit: str | None,
        created_by: str | None,
    ) -> RequisitionLine:
        self._requisition_line_seq += 1
        line = RequisitionLine(
            requisition_line_id=f"REQL-{self._requisition_line_seq:04d}",
            work_order_reference=work_order_reference,
            source_type=source_type,
            part_id=part_id,
            part_instance_id=part_instance_id,
            part_description=part_description,
            requested_quantity=requested_quantity,
            unit=unit,
            created_at=utc_now(),
            created_by=created_by,
        )
        self._requisition_lines.setdefault(work_order_reference, []).append(line)
        return line.model_copy(deep=True)

    async def list_requisition_lines_for_work_order(
        self, work_order_reference: str
    ) -> list[RequisitionLine]:
        return [
            line.model_copy(deep=True)
            for line in self._requisition_lines.get(work_order_reference, [])
        ]
