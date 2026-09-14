from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.requisition import RequisitionSourceType


class CreateRequisitionLineRequest(BaseModel):
    part_description: str = Field(min_length=1)
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None
    part_instance_id: str | None = None


class CreateMaterialRequestRequest(BaseModel):
    source_type: RequisitionSourceType
    source_work_order_id: str = Field(min_length=1)
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    lines: list[CreateRequisitionLineRequest] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=500)


class RequisitionLineResponse(BaseModel):
    requisition_line_id: str
    material_request_id: str
    source_task_revision_id: str | None
    part_id: str | None
    part_instance_id: str | None
    part_code_snapshot: str | None
    part_description: str
    requested_quantity: float | None
    unit: str | None
    approved_quantity: float | None
    issued_quantity: float | None
    used_quantity: float | None
    returned_quantity: float | None
    line_source: str | None
    created_at: datetime
    created_by: str | None


class MaterialRequestResponse(BaseModel):
    material_request_id: str
    source_type: RequisitionSourceType
    source_work_order_id: str
    vehicle_id: str | None
    request_status: str
    created_at: datetime
    created_by: str | None
    approved_at: datetime | None
    approved_by: str | None
    issued_at: datetime | None
    issued_by: str | None
    closed_at: datetime | None
    note: str | None


class MaterialRequestDetailResponse(BaseModel):
    request: MaterialRequestResponse
    lines: list[RequisitionLineResponse]
