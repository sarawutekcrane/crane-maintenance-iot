"""Workshop/maintenance equipment master data.

Kept separate from `Vehicle` per baseline section 7: "Do not force these
records into vehicle_master." Shares the `OperationalStatus` vocabulary
with `Vehicle` (both are physical assets with an operational state) but
has its own identity, category, and QR route (`/equipment/{equipment_id}`).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.domain.common import OperationalStatus


class EquipmentCategory(str, Enum):
    LATHE = "LATHE"
    MILLING = "MILLING"
    AIR_COMPRESSOR = "AIR_COMPRESSOR"
    WELDING = "WELDING"
    PRESS = "PRESS"
    DRILL_PRESS = "DRILL_PRESS"
    GRINDER = "GRINDER"
    FORKLIFT = "FORKLIFT"
    OTHER = "OTHER"


class Equipment(BaseModel):
    equipment_id: str
    equipment_code: str
    name: str
    category: EquipmentCategory
    serial_number: str | None = None
    location: str | None = None
    operational_status: OperationalStatus
    created_at: datetime
    updated_at: datetime
