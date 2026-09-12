"""Workshop/maintenance equipment master data.

Kept separate from `Vehicle` per baseline section 7: "Do not force these
records into vehicle_master." Has its own identity, category, status
vocabulary, and QR route (`/equipment/{equipment_id}`).

`EquipmentOperationalStatus` is a deliberately separate enum from
`app.domain.common.OperationalStatus` (Vehicle's status vocabulary).
Phase 2 originally reused `OperationalStatus` for equipment; Phase 2
verification flagged this as an unapproved permanent decision against
OPEN_DECISIONS_REGISTER_EN.txt's C02 item ("Do not automatically reuse
all vehicle statuses" for equipment). The user has since explicitly
approved the vocabulary below as a resolution of C02 (status codes only —
no transition rules are defined by this decision).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


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


class EquipmentOperationalStatus(str, Enum):
    """Workshop equipment operational status.

    Approved (OPEN_DECISIONS_REGISTER_EN.txt, decision C02) as a
    vocabulary separate from `app.domain.common.OperationalStatus`
    (Vehicle-only). Do not add vehicle-only values (e.g. `WORKING`,
    `LONG_TERM_PARKING`) here, and do not add further equipment values
    without the same kind of explicit approval. Transition rules between
    these statuses remain undefined/unapproved.
    """

    READY = "READY"
    IN_USE = "IN_USE"
    MAINTENANCE = "MAINTENANCE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class Equipment(BaseModel):
    equipment_id: str
    equipment_code: str
    name: str
    category: EquipmentCategory
    serial_number: str | None = None
    location: str | None = None
    operational_status: EquipmentOperationalStatus
    created_at: datetime
    updated_at: datetime
