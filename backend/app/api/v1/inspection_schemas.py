from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue


class AttachmentResponse(BaseModel):
    attachment_id: str
    purpose: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    uploaded_by: str | None
    url: str


class ChecklistItemResponse(BaseModel):
    item_id: str
    revision_id: str
    sequence: int
    title: str
    inspection_point: str | None
    method: str | None
    standard: str | None
    instruction: str | None
    frequency: str | None
    required_photo_on_fail: bool
    required_remark_on_fail: bool
    is_critical: bool
    reference_image: AttachmentResponse | None = None


class ChecklistMasterResponse(BaseModel):
    checklist_id: str
    asset_type: AssetType
    code: str
    name: str


class ChecklistRevisionResponse(BaseModel):
    revision_id: str
    checklist_id: str
    revision_number: int
    effective_date: date
    created_at: datetime


class ChecklistRevisionDetailResponse(BaseModel):
    checklist: ChecklistMasterResponse
    revision: ChecklistRevisionResponse
    items: list[ChecklistItemResponse]


class SubmitInspectionItemRequest(BaseModel):
    item_id: str = Field(min_length=1)
    result: InspectionResultValue
    remark: str | None = Field(default=None, max_length=1000)
    evidence_attachment_ids: list[str] = Field(default_factory=list)


class SubmitInspectionRequest(BaseModel):
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    overall_remark: str | None = Field(default=None, max_length=1000)
    items: list[SubmitInspectionItemRequest] = Field(min_length=1)


class InspectionItemResultResponse(BaseModel):
    result_id: str
    inspection_id: str
    item_id: str
    sequence: int
    title: str
    inspection_point: str | None
    method: str | None
    standard: str | None
    instruction: str | None
    is_critical: bool
    result: InspectionResultValue
    remark: str | None
    evidence: list[AttachmentResponse] = Field(default_factory=list)


class InspectionFindingResponse(BaseModel):
    finding_id: str
    inspection_id: str
    result_id: str
    asset_type: AssetType
    asset_id: str
    item_title: str
    is_critical: bool
    status: str
    created_at: datetime


class InspectionHeaderResponse(BaseModel):
    inspection_id: str
    asset_type: AssetType
    asset_id: str
    checklist_id: str
    revision_id: str
    revision_number: int
    submitted_at: datetime
    inspector_user_id: str | None
    overall_remark: str | None
    machine_state_snapshot_id: str | None = None


class InspectionDetailResponse(BaseModel):
    header: InspectionHeaderResponse
    items: list[InspectionItemResultResponse]
    findings: list[InspectionFindingResponse]


class InspectionSummaryResponse(BaseModel):
    inspection_id: str
    asset_type: AssetType
    asset_id: str
    checklist_id: str
    revision_number: int
    submitted_at: datetime
    inspector_user_id: str | None
    pass_count: int
    fail_count: int
    na_count: int
    has_fail: bool
