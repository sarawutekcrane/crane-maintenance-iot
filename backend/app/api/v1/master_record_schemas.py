"""R8 PRE-UAT — TEST master record API schemas (Mock/TEST only)."""
from __future__ import annotations

from pydantic import BaseModel


class MasterRecordOutcomeResponse(BaseModel):
    entity: str
    record_id: str
    action: str  # CREATE | UPDATE | NO_CHANGE
    replayed: bool
    event_id: str
    values: dict[str, str]


class MasterRecordListResponse(BaseModel):
    entity: str
    items: list[dict[str, str]]
    note_th: str = "รายการ TEST สร้าง/แก้ไขได้เฉพาะ Mock/TEST; รายการ REAL แสดงเพื่ออ้างอิงเท่านั้น"


class MasterRecordHistoryEvent(BaseModel):
    event_id: str
    action: str
    values_json: str
    previous_json: str
    actor_user_id: str
    recorded_at: str


class MasterRecordHistoryResponse(BaseModel):
    entity: str
    record_id: str
    events: list[MasterRecordHistoryEvent]
