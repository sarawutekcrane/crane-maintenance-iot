"""Repair domain — a separate workflow from PM (baseline section 10; Phase
4 scope).

STATUS LIFECYCLE WARNING (OPEN_DECISIONS_REGISTER_EN.txt F01 — "Repair
Status Lifecycle: TBD-BLOCKING, need states/transitions"): F01 is NOT
approved. `RepairStatus` below has only the two states technically
unavoidable to know whether a repair is still open or has been closed —
no IN_PROGRESS/ASSIGNED/CANCELLED, and no transition matrix is enforced
anywhere in `RepairService`. Provisional/configurable placeholder only,
mirroring `app.domain.pm.PmWorkOrderStatus`'s identical reasoning.

FINDING-TO-REPAIR WARNING (F02 — "Finding-to-Repair Conversion:
TBD-BLOCKING, need one-to-one/many-to-one, duplicate prevention, review
step"): F02 is NOT approved. `RepairService.create_repair` accepts a
`source_type=FINDING` + `source_id` link without enforcing one-to-one,
without deduplicating, and without any approval/review step — a Finding
may end up linked from zero, one, or many repairs, and nothing here ever
creates a repair automatically from a Finding. See
`app.domain.inspection.InspectionFinding`, which is never mutated by this
module (creating a repair does not modify the source Finding).

CLOSURE WARNING (F03 — "Repair Closure Requirements: TBD-BLOCKING, need
mandatory close data by category"): F03 is NOT approved. Closing a repair
requires nothing beyond the repair itself existing and being open — no
mandatory photo, technician, part, approval, or close note is enforced.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.domain.asset import AssetType


class RepairSourceType(str, Enum):
    """Stable English source_type codes (baseline section 10). `ALERT` is
    interface-ready only — no Alert domain exists yet in this repository
    (a later phase), so a repair may reference an `ALERT` source_id
    structurally but nothing here validates it against a real alert
    record (see `RepairService._validate_source`)."""

    MANUAL = "MANUAL"
    INSPECTION_RESULT = "INSPECTION_RESULT"
    FINDING = "FINDING"
    PM_RESULT = "PM_RESULT"
    ALERT = "ALERT"


class RepairStatus(str, Enum):
    """PROVISIONAL/CONFIGURABLE placeholder only — see module docstring's
    STATUS LIFECYCLE WARNING. F01 is not approved."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Repair(BaseModel):
    """Repair header. Separate from `app.domain.pm.PmWorkOrder` — never
    merged into a PM work order, even when `source_type=PM_RESULT`."""

    repair_id: str
    asset_type: AssetType
    asset_id: str
    source_type: RepairSourceType
    source_id: str | None = None
    category: str | None = None
    symptom: str | None = None
    meter_snapshot_id: str | None = None
    status: RepairStatus
    opened_at: datetime
    opened_by: str | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    close_note: str | None = None


class RepairAction(BaseModel):
    """Append-only repair action/history entry (baseline section 10:
    "Repair action history is append-only"). No update/delete path exists
    anywhere in this module or the repository interface — a correction is
    always a new action, never an edit of a previous one."""

    repair_action_id: str
    repair_id: str
    action_text: str
    actor: str | None = None
    created_at: datetime
    attachment_ids: list[str] = []


class RepairPart(BaseModel):
    """Actual part used during repair — a distinct record type from PM's
    `PmTaskPart`/`PmUsedPart` and from any future Phase 5 part-instance/
    lifetime tracking, per this phase's explicit requirement to keep the
    abstraction separate so Phase 5 can extend it without rewriting this
    one. No `part_id` linking to a part master exists yet (Phase 5
    scope); `part_description` is free text."""

    repair_part_id: str
    repair_id: str
    part_description: str
    quantity: float | None = None
    unit: str | None = None
    recorded_by: str | None = None
    recorded_at: datetime


class RepairDetail(BaseModel):
    repair: Repair
    actions: list[RepairAction]
    parts: list[RepairPart]


class RepairSummary(BaseModel):
    """Lightweight row for history/list views."""

    repair_id: str
    asset_type: AssetType
    asset_id: str
    source_type: RepairSourceType
    source_id: str | None = None
    status: RepairStatus
    opened_at: datetime
    closed_at: datetime | None = None
    action_count: int


__all__ = [
    "RepairSourceType",
    "RepairStatus",
    "Repair",
    "RepairAction",
    "RepairPart",
    "RepairDetail",
    "RepairSummary",
]
