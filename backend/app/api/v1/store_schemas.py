"""R8 PRE-UAT — repair material (Store) workflow schemas (Mock/TEST only)."""
from __future__ import annotations

from pydantic import BaseModel


class StoreEventResponse(BaseModel):
    """Future stock-integration event contract v1 (docs/contracts/r8-store-material-event-contract.md)."""
    event_id: str
    event_type: str
    event_version: str
    material_request_id: str
    requisition_line_id: str
    source_type: str
    source_work_order_id: str
    asset_type: str
    asset_id: str
    part_id: str
    part_instance_id: str
    part_code_snapshot: str
    quantity: str
    unit: str
    position_code: str
    reason: str
    actor_user_id: str
    actor_personnel_id: str
    occurred_at: str
    recorded_at: str
    request_id: str
    supersedes_event_id: str
    data_context: str
    test_batch_id: str


class StoreWriteResponse(BaseModel):
    replayed: bool
    material_request_id: str
    events: list[StoreEventResponse]


class StorePartBalanceResponse(BaseModel):
    """One physical identity issued on a line (actual part_id + part_instance_id)."""
    part_id: str
    part_instance_id: str
    part_code_snapshot: str
    issued: str
    used: str
    return_declared: str
    return_accepted: str
    unreconciled: str


class StoreLineBalanceResponse(BaseModel):
    requisition_line_id: str
    material_request_id: str
    part_id: str
    part_description: str
    unit: str
    requested: str
    decision: str
    approved: str
    issued: str
    used: str
    return_declared: str
    return_accepted: str
    unreconciled: str
    pending_return: str
    awaiting_issue: str
    issued_part_ids: list[str]
    issued_parts: list[StorePartBalanceResponse]
    blockers: list[str]


class StoreReconciliationResponse(BaseModel):
    repair_id: str
    state: str  # RECONCILED | UNRECONCILED
    blockers: list[str]
    lines: list[StoreLineBalanceResponse]
    events: list[StoreEventResponse]
    exceptions_note: str = "EXCEPTION_POLICY_PENDING: สูญหาย/เสียหาย/แก้ไขหลังปิดงาน ยังไม่มีนโยบายที่อนุมัติ"
    scope_note: str = "ไม่ใช่บัญชีสต็อกคลัง: กระทบยอดต่อใบงานจากเหตุการณ์ขอเบิก/จ่าย/ใช้จริง/คืนเท่านั้น"


class StoreEventFeedResponse(BaseModel):
    contract: str = "R8-STORE-MATERIAL-EVENT-v1"
    events: list[StoreEventResponse]
    next_after_event_id: str | None
