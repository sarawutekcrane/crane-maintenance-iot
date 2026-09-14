"""Checklist / inspection domain service.

Owns every business rule Phase 3 is allowed to define without an approved
open decision (OPEN_DECISIONS_REGISTER_EN.txt D01-D04):

- which checklist applies to an asset: "the" currently active revision for
  its `AssetType` (see `app.domain.checklist` module docstring — D01 has
  no approved assignment policy, so there is exactly one checklist family
  per asset type rather than an asset/model matrix),
- a submitted inspection must answer every item in that revision, exactly
  once, with no extra/unknown item IDs,
- a FAIL requires a non-empty remark only when the checklist item's
  `required_remark_on_fail` flag is set, and additionally an evidence
  photo when its `required_photo_on_fail` flag is set — both are
  per-item, source-data-driven flags defaulting to `False` (CORRECTION,
  post-Phase-3 verification: an earlier revision of this service required
  a remark unconditionally for every FAIL; that was an unapproved,
  hardcoded global rule with no authoritative source and has been
  replaced by the same item-level-configuration pattern
  `required_photo_on_fail` already used),
- every FAIL creates an OPEN finding (Phase 3 scope: "normal abnormal
  finding" — no automatic repair order, no severity/alert model, both
  belong to a later, explicitly-approved phase),
- nothing here ever updates, voids, or supersedes a previously submitted
  inspection (D04 is not approved) — only creation and read exist.

Attachment uploads are validated against a size limit and an allowed
content-type list (`Settings.attachment_max_size_bytes` /
`attachment_allowed_content_types_set`) so the endpoint is not completely
unrestricted. These are explicitly LOCAL-DEVELOPMENT DEFAULTS, not a
production policy: OPEN_DECISIONS_REGISTER_EN.txt M07 (file upload
limits/MIME/malware-scanning policy) remains unresolved, and this module
must not be read as having frozen it — the values are configurable via
environment variables precisely so a later, explicitly-approved production
policy can replace them without a code change.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import status

from app.config import Settings
from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.attachment_service import AttachmentService
from app.domain.checklist import ChecklistItem, ChecklistRevisionDetail, InspectionResultValue
from app.domain.common import Page, PageParams
from app.domain.equipment import EquipmentOperationalStatus
from app.domain.inspection import (
    FindingStatus,
    InspectionDetail,
    InspectionFinding,
    InspectionSummary,
    NewInspectionItemInput,
)
from app.domain.meter_service import MeterService
from app.errors import ApiError
from app.repositories.base import Repository
from app.storage.base import StorageProvider


@dataclass(frozen=True)
class InspectionItemAnswer:
    """One item answer as submitted by the client, before validation."""

    item_id: str
    result: InspectionResultValue
    remark: str | None
    evidence_attachment_ids: list[str]


class InspectionService:
    def __init__(
        self,
        repository: Repository,
        storage: StorageProvider,
        settings: Settings,
        meter_service: MeterService | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._settings = settings
        self._attachments = AttachmentService(repository, storage, settings)
        # Optional for backward compatibility with any direct instantiation
        # that predates the Core Demo Fix automatic snapshot mechanism;
        # `app.dependencies.get_inspection_service` always supplies one.
        self._meter = meter_service or MeterService(repository)

    # ---- Checklist ----

    async def get_active_checklist(self, asset_type: AssetType) -> ChecklistRevisionDetail:
        detail = await self._repository.get_active_checklist_revision(asset_type)
        if detail is None:
            raise ApiError(
                code="NO_ACTIVE_CHECKLIST",
                message=f"No active inspection checklist is configured for asset type '{asset_type.value}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def get_checklist_revision(
        self, checklist_id: str, revision_id: str
    ) -> ChecklistRevisionDetail:
        detail = await self._repository.get_checklist_revision(checklist_id, revision_id)
        if detail is None:
            raise ApiError(
                code="CHECKLIST_REVISION_NOT_FOUND",
                message=f"Checklist revision '{revision_id}' was not found for checklist '{checklist_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    # ---- Attachments (reference vs evidence, see app.domain.attachment) ----

    async def upload_attachment(
        self,
        purpose: AttachmentPurpose,
        filename: str,
        content_type: str,
        data: bytes,
        uploaded_by: str | None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Attachment:
        # Delegates to the shared `AttachmentService` (extracted post-Phase-3
        # so Phase 4's PM/Repair services reuse the identical boundary) —
        # this method's own signature/behavior is unchanged.
        return await self._attachments.upload_attachment(
            purpose=purpose,
            filename=filename,
            content_type=content_type,
            data=data,
            uploaded_by=uploaded_by,
            source_type=source_type,
            source_id=source_id,
        )

    async def get_attachment_or_none(self, attachment_id: str) -> Attachment | None:
        return await self._attachments.get_attachment_or_none(attachment_id)

    async def require_attachment(self, attachment_id: str) -> Attachment:
        return await self._attachments.require_attachment(attachment_id)

    async def list_attachments_for_source(
        self, source_type: str, source_id: str
    ) -> list[Attachment]:
        return await self._attachments.list_for_source(source_type, source_id)

    async def read_attachment_bytes(self, attachment: Attachment) -> bytes:
        return await self._attachments.read_attachment_bytes(attachment)

    # ---- Asset validation (reuses Phase 2 not-found codes) ----

    async def _require_asset(self, asset_type: AssetType, asset_id: str) -> None:
        if asset_type == AssetType.VEHICLE:
            vehicle = await self._repository.get_vehicle(asset_id)
            if vehicle is None:
                raise ApiError(
                    code="VEHICLE_NOT_FOUND",
                    message=f"Vehicle '{asset_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        else:
            equipment = await self._repository.get_equipment(asset_id)
            if equipment is None:
                raise ApiError(
                    code="EQUIPMENT_NOT_FOUND",
                    message=f"Equipment '{asset_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            if equipment.operational_status == EquipmentOperationalStatus.RETIRED:
                # Core Demo Fix, EQUIPMENT STATUS CHANGE — APPROVED: mirrors
                # `app.domain.asset_lookup.require_asset_exists`'s identical
                # RETIRED guard for the one asset-existence check this
                # module keeps as its own copy (see that module's docstring
                # for why it is not simply delegated to the shared helper).
                raise ApiError(
                    code="EQUIPMENT_RETIRED",
                    message=(
                        f"Equipment '{asset_id}' is RETIRED (ปลดระวาง/เลิกใช้งานถาวร) and "
                        "cannot be selected for new operational work"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

    # ---- Submission ----

    async def submit_inspection(
        self,
        asset_type: AssetType,
        asset_id: str,
        answers: list[InspectionItemAnswer],
        overall_remark: str | None,
        inspector_user_id: str | None,
    ) -> InspectionDetail:
        await self._require_asset(asset_type, asset_id)
        checklist_detail = await self.get_active_checklist(asset_type)
        items_by_id: dict[str, ChecklistItem] = {
            item.item_id: item for item in checklist_detail.items
        }

        answers_by_id: dict[str, InspectionItemAnswer] = {}
        for answer in answers:
            if answer.item_id in answers_by_id:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message=f"Item '{answer.item_id}' was answered more than once",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            answers_by_id[answer.item_id] = answer

        missing = set(items_by_id) - set(answers_by_id)
        unknown = set(answers_by_id) - set(items_by_id)
        if missing or unknown:
            raise ApiError(
                code="VALIDATION_ERROR",
                message="Inspection submission does not match the active checklist revision",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"missing_item_ids": sorted(missing), "unknown_item_ids": sorted(unknown)},
            )

        prepared: list[NewInspectionItemInput] = []
        for item in sorted(checklist_detail.items, key=lambda i: i.sequence):
            answer = answers_by_id[item.item_id]

            if answer.result == InspectionResultValue.FAIL:
                # Both rules are per-item, source-data-driven flags
                # defaulting to False (see the module docstring's
                # CORRECTION note) — neither is a global, unconditional
                # requirement.
                if item.required_remark_on_fail and (
                    not answer.remark or not answer.remark.strip()
                ):
                    raise ApiError(
                        code="VALIDATION_ERROR",
                        message=f"A remark is required when item '{item.item_id}' is marked FAIL",
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        details={"item_id": item.item_id},
                    )
                if item.required_photo_on_fail and not answer.evidence_attachment_ids:
                    raise ApiError(
                        code="VALIDATION_ERROR",
                        message=f"An evidence photo is required when item '{item.item_id}' is marked FAIL",
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        details={"item_id": item.item_id},
                    )

            for attachment_id in answer.evidence_attachment_ids:
                attachment = await self._repository.get_attachment(attachment_id)
                if attachment is None or attachment.purpose != AttachmentPurpose.INSPECTION_EVIDENCE:
                    raise ApiError(
                        code="VALIDATION_ERROR",
                        message=f"Evidence attachment '{attachment_id}' was not found",
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        details={"item_id": item.item_id, "attachment_id": attachment_id},
                    )

            prepared.append(
                NewInspectionItemInput(
                    item_id=item.item_id,
                    sequence=item.sequence,
                    title=item.title,
                    inspection_point=item.inspection_point,
                    method=item.method,
                    standard=item.standard,
                    instruction=item.instruction,
                    is_critical=item.is_critical,
                    result=answer.result,
                    remark=answer.remark,
                    evidence_attachment_ids=list(answer.evidence_attachment_ids),
                )
            )

        # Core Demo Fix: automatic machine-state snapshot at submission time
        # — backend-derived from this asset's own history, never from an
        # editable browser field (see MeterService.capture_current_state).
        snapshot = await self._meter.capture_current_state(
            asset_type=asset_type,
            asset_id=asset_id,
            recorded_by=inspector_user_id,
            source_note="INSPECTION_SUBMISSION",
        )

        return await self._repository.create_inspection(
            asset_type=asset_type,
            asset_id=asset_id,
            checklist_id=checklist_detail.checklist.checklist_id,
            revision_id=checklist_detail.revision.revision_id,
            revision_number=checklist_detail.revision.revision_number,
            inspector_user_id=inspector_user_id,
            overall_remark=overall_remark,
            items=prepared,
            machine_state_snapshot_id=snapshot.meter_snapshot_id,
        )

    # ---- History ----

    async def get_inspection(self, inspection_id: str) -> InspectionDetail:
        detail = await self._repository.get_inspection(inspection_id)
        if detail is None:
            raise ApiError(
                code="INSPECTION_NOT_FOUND",
                message=f"Inspection '{inspection_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def list_inspections(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
    ) -> Page[InspectionSummary]:
        items, total = await self._repository.list_inspections(
            asset_type=asset_type, asset_id=asset_id, params=params
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def list_findings(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: FindingStatus | None,
    ) -> list[InspectionFinding]:
        """Core Demo Fixes, VEHICLE LIST / CORE STATUS SUMMARY: "unresolved
        inspection finding indicator." Uses only data already produced by
        Phase 3 (every FAIL result's OPEN finding) — never fabricates a
        severity/alert model (A06/D03 remain unresolved)."""
        return await self._repository.list_inspection_findings(
            asset_type=asset_type, asset_id=asset_id, status=status
        )
