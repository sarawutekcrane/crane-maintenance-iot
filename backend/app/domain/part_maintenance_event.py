"""R6 — part maintenance events (FINAL §7.1, §7.4; AP-05).

An append-only record that an INSPECT or REPAIR action was performed on a
tracked target (a part instance or a position-lifetime record) for one
lifetime rule or condition group. It feeds ONLY the anchor of INSPECT /
REPAIR due evaluation for that same rule or group: it never changes a
REPLACE evaluation, never opens or closes a lifecycle and never resets any
counter (a passed inspection is not a replacement).

`PmUsedPart.action=SERVICED` stays descriptive and non-authoritative
(`app.domain.part.PartActionType`): this record is the only authoritative
maintenance anchor. Whether INSPECT/REPAIR schedules progress from the
actual event (proposed) or from the original schedule is Owner policy PG-3(c);
REAL evaluation stays PENDING until it is decided.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.domain.part_instance import MeterAnchor


class MaintenanceTargetType(str, Enum):
    PART_INSTANCE = "PART_INSTANCE"
    POSITION_LIFETIME = "POSITION_LIFETIME"


class MaintenanceAction(str, Enum):
    INSPECTED = "INSPECTED"
    REPAIRED_IN_PLACE = "REPAIRED_IN_PLACE"


class PartMaintenanceEvent(BaseModel):
    event_id: str
    target_type: MaintenanceTargetType
    target_id: str
    lifetime_rule_id: str | None = None
    condition_group_key: str | None = None
    action: MaintenanceAction
    outcome: str | None = None
    lifecycle_id: str | None = None
    effective_at: datetime
    recorded_at: datetime
    actor: str | None = None
    meter_snapshot_id: str | None = None
    anchors: list[MeterAnchor] = Field(default_factory=list)
    source_type: str | None = None
    source_id: str | None = None
    note: str | None = None
    request_id: str | None = None


# The due action each maintenance action anchors (never REPLACE).
ACTION_FOR_DUE = {"INSPECT": MaintenanceAction.INSPECTED, "REPAIR": MaintenanceAction.REPAIRED_IN_PLACE}

__all__ = [
    "MaintenanceTargetType",
    "MaintenanceAction",
    "PartMaintenanceEvent",
    "ACTION_FOR_DUE",
]
