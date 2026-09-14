"""Checklist / inspection / attachment routes (Phase 3).

`/vehicle/{vehicle_id}/inspect` and `/equipment/{equipment_id}/inspect` on
the frontend call these endpoints; the frozen `/vehicle/{vehicle_id}` and
`/equipment/{equipment_id}` QR routes/endpoints from Phase 2 are untouched.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response

from app.api.v1.inspection_schemas import (
    AttachmentResponse,
    ChecklistItemResponse,
    ChecklistMasterResponse,
    ChecklistRevisionDetailResponse,
    ChecklistRevisionResponse,
    InspectionDetailResponse,
    InspectionFindingResponse,
    InspectionHeaderResponse,
    InspectionItemResultResponse,
    InspectionSummaryResponse,
    SubmitInspectionRequest,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_inspection_service
from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.checklist import ChecklistItem, ChecklistRevisionDetail
from app.domain.common import Page, PageParams
from app.domain.inspection import FindingStatus, InspectionDetail, InspectionItemResult
from app.domain.inspection_service import InspectionItemAnswer, InspectionService

router = APIRouter(tags=["inspections"])


def _attachment_response(attachment: Attachment) -> AttachmentResponse:
    return AttachmentResponse(
        attachment_id=attachment.attachment_id,
        purpose=attachment.purpose.value,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        uploaded_at=attachment.uploaded_at,
        uploaded_by=attachment.uploaded_by,
        url=f"/api/v1/attachments/{attachment.attachment_id}/file",
        source_type=attachment.source_type,
        source_id=attachment.source_id,
    )


async def _checklist_item_response(
    item: ChecklistItem, service: InspectionService
) -> ChecklistItemResponse:
    reference_image = None
    if item.reference_image_attachment_id:
        attachment = await service.get_attachment_or_none(item.reference_image_attachment_id)
        if attachment is not None:
            reference_image = _attachment_response(attachment)
    return ChecklistItemResponse(
        item_id=item.item_id,
        revision_id=item.revision_id,
        sequence=item.sequence,
        title=item.title,
        inspection_point=item.inspection_point,
        method=item.method,
        standard=item.standard,
        instruction=item.instruction,
        frequency=item.frequency,
        required_photo_on_fail=item.required_photo_on_fail,
        required_remark_on_fail=item.required_remark_on_fail,
        is_critical=item.is_critical,
        reference_image=reference_image,
    )


async def _revision_detail_response(
    detail: ChecklistRevisionDetail, service: InspectionService
) -> ChecklistRevisionDetailResponse:
    items = [await _checklist_item_response(item, service) for item in detail.items]
    return ChecklistRevisionDetailResponse(
        checklist=ChecklistMasterResponse(
            checklist_id=detail.checklist.checklist_id,
            asset_type=detail.checklist.asset_type,
            code=detail.checklist.code,
            name=detail.checklist.name,
        ),
        revision=ChecklistRevisionResponse.model_validate(detail.revision.model_dump()),
        items=items,
    )


async def _item_result_response(
    item: InspectionItemResult, service: InspectionService
) -> InspectionItemResultResponse:
    evidence: list[AttachmentResponse] = []
    for attachment_id in item.evidence_attachment_ids:
        attachment = await service.get_attachment_or_none(attachment_id)
        if attachment is not None:
            evidence.append(_attachment_response(attachment))
    return InspectionItemResultResponse(
        result_id=item.result_id,
        inspection_id=item.inspection_id,
        item_id=item.item_id,
        sequence=item.sequence,
        title=item.title,
        inspection_point=item.inspection_point,
        method=item.method,
        standard=item.standard,
        instruction=item.instruction,
        is_critical=item.is_critical,
        result=item.result,
        remark=item.remark,
        evidence=evidence,
    )


async def _inspection_detail_response(
    detail: InspectionDetail, service: InspectionService
) -> InspectionDetailResponse:
    return InspectionDetailResponse(
        header=InspectionHeaderResponse.model_validate(detail.header.model_dump()),
        items=[await _item_result_response(item, service) for item in detail.items],
        findings=[
            InspectionFindingResponse.model_validate(f.model_dump()) for f in detail.findings
        ],
    )


@router.get("/checklists/active", response_model=ChecklistRevisionDetailResponse)
async def get_active_checklist(
    asset_type: AssetType = Query(...),
    service: InspectionService = Depends(get_inspection_service),
) -> ChecklistRevisionDetailResponse:
    detail = await service.get_active_checklist(asset_type)
    return await _revision_detail_response(detail, service)


@router.get(
    "/checklists/{checklist_id}/revisions/{revision_id}",
    response_model=ChecklistRevisionDetailResponse,
)
async def get_checklist_revision(
    checklist_id: str,
    revision_id: str,
    service: InspectionService = Depends(get_inspection_service),
) -> ChecklistRevisionDetailResponse:
    detail = await service.get_checklist_revision(checklist_id, revision_id)
    return await _revision_detail_response(detail, service)


@router.post("/attachments", response_model=AttachmentResponse)
async def upload_attachment(
    purpose: AttachmentPurpose = Form(...),
    file: UploadFile = File(...),
    source_type: str | None = Form(default=None),
    source_id: str | None = Form(default=None),
    service: InspectionService = Depends(get_inspection_service),
    context: RequestContext = Depends(get_current_context),
) -> AttachmentResponse:
    data = await file.read()
    attachment = await service.upload_attachment(
        purpose=purpose,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        uploaded_by=context.user_id,
        context=context,
        source_type=source_type,
        source_id=source_id,
    )
    return _attachment_response(attachment)


@router.get("/attachments/by-source/{source_type}/{source_id}", response_model=list[AttachmentResponse])
async def list_attachments_for_source(
    source_type: str,
    source_id: str,
    service: InspectionService = Depends(get_inspection_service),
    context: RequestContext = Depends(get_current_context),
) -> list[AttachmentResponse]:
    """Currently only populated for `source_type="REPAIR_REQUEST"`
    uploads (REV05 section 4) — every earlier attachment purpose links
    back to its owner via that owner's own attachment_ids field instead.
    REV06 section 14 (P1): `source_id` existence and caller authorization
    are validated before any row is returned — attachment/source ID
    possession alone is never sufficient."""
    attachments = await service.list_attachments_for_source(source_type, source_id, context)
    return [_attachment_response(a) for a in attachments]


@router.get("/attachments/{attachment_id}/file")
async def download_attachment(
    attachment_id: str, service: InspectionService = Depends(get_inspection_service)
) -> Response:
    attachment = await service.require_attachment(attachment_id)
    data = await service.read_attachment_bytes(attachment)
    return Response(content=data, media_type=attachment.content_type)


@router.post("/inspections", response_model=InspectionDetailResponse)
async def submit_inspection(
    body: SubmitInspectionRequest,
    service: InspectionService = Depends(get_inspection_service),
    context: RequestContext = Depends(get_current_context),
) -> InspectionDetailResponse:
    answers = [
        InspectionItemAnswer(
            item_id=item.item_id,
            result=item.result,
            remark=item.remark,
            evidence_attachment_ids=list(item.evidence_attachment_ids),
        )
        for item in body.items
    ]
    detail = await service.submit_inspection(
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        answers=answers,
        overall_remark=body.overall_remark,
        inspector_user_id=context.user_id,
    )
    return await _inspection_detail_response(detail, service)


@router.get("/inspections", response_model=Page[InspectionSummaryResponse])
async def list_inspections(
    asset_type: AssetType | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: InspectionService = Depends(get_inspection_service),
) -> Page[InspectionSummaryResponse]:
    result = await service.list_inspections(
        asset_type=asset_type, asset_id=asset_id, params=PageParams(page=page, page_size=page_size)
    )
    return Page[InspectionSummaryResponse](
        items=[InspectionSummaryResponse.model_validate(s.model_dump()) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/inspections/{inspection_id}", response_model=InspectionDetailResponse)
async def get_inspection(
    inspection_id: str, service: InspectionService = Depends(get_inspection_service)
) -> InspectionDetailResponse:
    detail = await service.get_inspection(inspection_id)
    return await _inspection_detail_response(detail, service)


@router.get("/findings", response_model=list[InspectionFindingResponse])
async def list_findings(
    asset_type: AssetType | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    status: FindingStatus | None = Query(default=None),
    service: InspectionService = Depends(get_inspection_service),
) -> list[InspectionFindingResponse]:
    """Core Demo Fixes, VEHICLE LIST / CORE STATUS SUMMARY: backs the
    "unresolved inspection finding" indicator — one call per asset (or a
    single unfiltered call the frontend groups client-side)."""
    findings = await service.list_findings(asset_type=asset_type, asset_id=asset_id, status=status)
    return [InspectionFindingResponse.model_validate(f.model_dump()) for f in findings]
