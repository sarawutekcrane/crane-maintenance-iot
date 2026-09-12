"""Checklist / inspection domain service.

Owns every business rule Phase 3 is allowed to define without an approved
open decision (OPEN_DECISIONS_REGISTER_EN.txt D01-D04):

- which checklist applies to an asset: "the" currently active revision for
  its `AssetType` (see `app.domain.checklist` module docstring — D01 has
  no approved assignment policy, so there is exactly one checklist family
  per asset type rather than an asset/model matrix),
- a submitted inspection must answer every item in that revision, exactly
  once, with no extra/unknown item IDs,
- a FAIL requires a non-empty remark, and additionally a evidence photo
  when the checklist item's `required_photo_on_fail` flag is set,
- every FAIL creates an OPEN finding (Phase 3 scope: "normal abnormal
  finding" — no automatic repair order, no severity/alert model, both
  belong to a later, explicitly-approved phase),
- nothing here ever updates, voids, or supersedes a previously submitted
  inspection (D04 is not approved) — only creation and read exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import status

from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.checklist import ChecklistItem, ChecklistRevisionDetail, InspectionResultValue
from app.domain.common import Page, PageParams
from app.domain.inspection import InspectionDetail, InspectionSummary, NewInspectionItemInput
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
    def __init__(self, repository: Repository, storage: StorageProvider) -> None:
        self._repository = repository
        self._storage = storage

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
    ) -> Attachment:
        if not data:
            raise ApiError(
                code="VALIDATION_ERROR",
                message="Uploaded file is empty",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        stored = await self._storage.save(filename=filename, content_type=content_type, data=data)
        return await self._repository.create_attachment(
            purpose=purpose,
            storage_ref=stored.storage_ref,
            filename=stored.filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            uploaded_by=uploaded_by,
        )

    async def get_attachment_or_none(self, attachment_id: str) -> Attachment | None:
        return await self._repository.get_attachment(attachment_id)

    async def require_attachment(self, attachment_id: str) -> Attachment:
        attachment = await self._repository.get_attachment(attachment_id)
        if attachment is None:
            raise ApiError(
                code="ATTACHMENT_NOT_FOUND",
                message=f"Attachment '{attachment_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return attachment

    async def read_attachment_bytes(self, attachment: Attachment) -> bytes:
        return await self._storage.read(attachment.storage_ref)

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
                if not answer.remark or not answer.remark.strip():
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

        return await self._repository.create_inspection(
            asset_type=asset_type,
            asset_id=asset_id,
            checklist_id=checklist_detail.checklist.checklist_id,
            revision_id=checklist_detail.revision.revision_id,
            revision_number=checklist_detail.revision.revision_number,
            inspector_user_id=inspector_user_id,
            overall_remark=overall_remark,
            items=prepared,
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
