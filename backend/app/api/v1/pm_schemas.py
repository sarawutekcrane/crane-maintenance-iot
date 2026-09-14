from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.part import PartActionType
from app.domain.pm import PmTriggerType, PmWorkOrderStatus
from app.domain.requisition import RequisitionSourceType


class PmTaskPartResponse(BaseModel):
    pm_task_part_id: str
    pm_task_id: str
    part_description: str
    quantity: float | None
    unit: str | None
    part_id: str | None = None


class PmTaskResponse(BaseModel):
    pm_task_id: str
    revision_id: str
    sequence: int
    group: str | None
    description: str
    trigger_type: PmTriggerType | None
    interval_value: float | None
    interval_unit: str | None
    standard_parts: list[PmTaskPartResponse] = Field(default_factory=list)


class PmPlanResponse(BaseModel):
    pm_plan_id: str
    plan_code: str
    asset_type: AssetType
    name: str
    model_ids: list[str]


class PmTaskRevisionResponse(BaseModel):
    revision_id: str
    pm_plan_id: str
    revision_number: int
    effective_date: date
    source_revision_note: str | None
    created_at: datetime


class PmTaskRevisionDetailResponse(BaseModel):
    plan: PmPlanResponse
    revision: PmTaskRevisionResponse
    tasks: list[PmTaskResponse]


class PmPlanStatusResponse(BaseModel):
    plan: PmPlanResponse
    active_revision: PmTaskRevisionResponse | None
    last_completed_work_order_id: str | None
    last_completed_at: datetime | None
    last_completed_meter_snapshot_id: str | None
    due_status: str
    due_status_note: str


class OpenPmWorkOrderRequest(BaseModel):
    asset_type: AssetType
    asset_id: str = Field(min_length=1)
    pm_plan_id: str = Field(min_length=1)
    due_reason: PmTriggerType | None = None
    note: str | None = Field(default=None, max_length=1000)
    initial_scope_task_ids: list[str] | None = None


class AddPmScopeTaskRequest(BaseModel):
    pm_task_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


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


class AssignPmWorkOrderRequest(BaseModel):
    primary_technician: str | None = None
    collaborators: list[str] = Field(default_factory=list)


class PmAssignmentHistoryEntryResponse(BaseModel):
    pm_assignment_id: str
    pm_work_order_id: str
    user_id: str
    assignment_role: str
    assigned_at: datetime
    assigned_by_user_id: str | None
    ended_at: datetime | None
    active_status: bool
    note: str | None = None


class PmScopeAdditionResponse(BaseModel):
    pm_work_order_id: str
    pm_task_id: str
    added_by: str | None
    added_at: datetime
    reason: str


class UsedPartRequest(BaseModel):
    part_description: str = Field(min_length=1)
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None
    part_instance_id: str | None = None
    action: PartActionType | None = None


class SubmitPmTaskResultRequest(BaseModel):
    pm_task_id: str = Field(min_length=1)
    completed: bool
    meter_snapshot_id: str | None = None
    remark: str | None = Field(default=None, max_length=1000)
    used_parts: list[UsedPartRequest] = Field(default_factory=list)
    evidence_attachment_ids: list[str] = Field(default_factory=list)


class ClosePmWorkOrderRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class PmUsedPartResponse(BaseModel):
    pm_used_part_id: str
    pm_work_result_id: str
    part_description: str
    quantity: float | None
    unit: str | None
    part_id: str | None
    part_instance_id: str | None
    action: PartActionType | None
    recorded_by: str | None
    recorded_at: datetime


class PmWorkResultResponse(BaseModel):
    pm_work_result_id: str
    pm_work_order_id: str
    pm_task_id: str
    revision_id: str
    sequence: int
    task_description: str
    completed: bool
    meter_snapshot_id: str | None
    remark: str | None
    used_parts: list[PmUsedPartResponse]
    evidence_attachment_ids: list[str]
    performed_by: str | None
    performed_at: datetime


class PmWorkOrderResponse(BaseModel):
    pm_work_order_id: str
    asset_type: AssetType
    asset_id: str
    pm_plan_id: str
    revision_id: str
    due_reason: PmTriggerType | None
    status: PmWorkOrderStatus
    opened_at: datetime
    opened_by: str | None
    closed_at: datetime | None
    closed_by: str | None
    note: str | None
    opened_snapshot_id: str | None = None
    closed_snapshot_id: str | None = None
    scope_task_ids: list[str] = Field(default_factory=list)
    scope_approved_at: datetime | None = None
    scope_approved_by: str | None = None
    primary_technician: str | None = None
    collaborators: list[str] = Field(default_factory=list)


class PmWorkOrderDetailResponse(BaseModel):
    work_order: PmWorkOrderResponse
    results: list[PmWorkResultResponse]
    scope_additions: list[PmScopeAdditionResponse] = Field(default_factory=list)


class PmWorkOrderSummaryResponse(BaseModel):
    pm_work_order_id: str
    asset_type: AssetType
    asset_id: str
    pm_plan_id: str
    revision_id: str
    status: PmWorkOrderStatus
    opened_at: datetime
    closed_at: datetime | None
    result_count: int
    primary_technician: str | None = None
    collaborators: list[str] = []
