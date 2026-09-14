"""Workshop/maintenance equipment master data.

Kept separate from `Vehicle` per baseline section 7: "Do not force these
records into vehicle_master." Has its own identity, category, status
vocabulary, and QR route (`/equipment/{equipment_id}`).

`EquipmentOperationalStatus` is a deliberately separate enum from
`app.domain.common.OperationalStatus` (Vehicle's status vocabulary).
Phase 2 originally reused `OperationalStatus` for equipment; Phase 2
verification flagged this as an unapproved permanent decision against
OPEN_DECISIONS_REGISTER_EN.txt's C02 item ("Do not automatically reuse
all vehicle statuses" for equipment). The user then explicitly approved
the four-value vocabulary as a resolution of C02 (status codes only — no
transition rules were defined by that decision).

CORE DEMO FIX (EQUIPMENT STATUS CHANGE — APPROVED): the user has since
explicitly approved extending this vocabulary with a fifth value,
`RETIRED`, plus Thai display labels and a status-change capability with
reason/actor/timestamp/history (see `EquipmentStatusHistoryEntry` below
and `EquipmentService.change_status`). `RETIRED` preserves all equipment
history (never hard-deleted) and must not be selectable for new normal
operational work — enforced centrally in `app.domain.asset_lookup.
require_asset_exists` and `InspectionService._require_asset`, the two
places new PM/repair/part-instance/inspection work checks an asset exists
before proceeding. This still does not resolve equipment status
*transition rules* generally (which statuses may follow which) — that
remains open, matching C02's original scope limitation.
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

    Thai display labels (Core Demo Fixes prompt, EQUIPMENT STATUS CHANGE):
    READY=พร้อมใช้งาน, IN_USE=กำลังใช้งาน, MAINTENANCE=ซ่อมบำรุง,
    OUT_OF_SERVICE=งดใช้งานชั่วคราว, RETIRED=ปลดระวาง / เลิกใช้งานถาวร
    (see `frontend/src/lib/labels.ts`).
    """

    READY = "READY"
    IN_USE = "IN_USE"
    MAINTENANCE = "MAINTENANCE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


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


class EquipmentStatusHistoryEntry(BaseModel):
    """Append-only status change record (guardrails §6: "Use history/
    append records for status..."). Mirrors
    `app.domain.vehicle.VehicleStatusHistoryEntry`'s identical shape."""

    history_id: str
    equipment_id: str
    status: EquipmentOperationalStatus
    changed_at: datetime
    changed_by: str | None = None
    reason: str | None = None
