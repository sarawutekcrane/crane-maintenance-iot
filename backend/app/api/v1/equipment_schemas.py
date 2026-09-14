from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.equipment import EquipmentCategory, EquipmentOperationalStatus


class EquipmentResponse(BaseModel):
    equipment_id: str
    equipment_code: str
    name: str
    category: EquipmentCategory
    serial_number: str | None
    location: str | None
    operational_status: EquipmentOperationalStatus
    created_at: datetime
    updated_at: datetime


class ChangeEquipmentStatusRequest(BaseModel):
    status: EquipmentOperationalStatus
    reason: str | None = Field(default=None, max_length=500)


class EquipmentStatusHistoryEntryResponse(BaseModel):
    history_id: str
    equipment_id: str
    status: EquipmentOperationalStatus
    changed_at: datetime
    changed_by: str | None
    reason: str | None
