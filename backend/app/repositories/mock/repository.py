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
from app.domain.equipment import Equipment, EquipmentCategory
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
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import VehicleModel
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
