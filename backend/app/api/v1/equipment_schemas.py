from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

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
