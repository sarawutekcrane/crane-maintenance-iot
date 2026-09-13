"""Part Master, tracking-mode vocabulary, and Part Set / Kit revisions
(Phase 5 scope; baseline sections 11, 12, 15;
docs/claude-prompts/web-api/05_PHASE5_PARTS_LIFETIME_TRANSFER_EN.txt).

TRACKING MODE (guardrails §12 / baseline §11): four distinct, non-
overlapping meanings, frozen by prior approval:

- NONE: no lifetime/instance tracking at all.
- CONSUMABLE: usage may be recorded during PM/repair; no permanent
  serialized physical instance is created.
- POSITION_LIFETIME: lifetime is tracked by asset+position+rule/baseline
  (see `app.domain.position_lifetime`); no unique physical instance is
  required.
- INSTANCE_TRACKED: a stable, serialized physical instance
  (`app.domain.part_instance.PartInstance`) whose history follows the
  physical component across vehicles/assets.

`PartInstanceService`/`PositionLifetimeService` each enforce that a part's
declared `tracking_mode` matches the endpoint being used — POSITION_LIFETIME
parts are never enrolled as a `PartInstance`, and INSTANCE_TRACKED parts
are never enrolled as a position-lifetime record — so the four meanings
never collapse into each other.

INCREMENTAL / ON-DEMAND ENROLLMENT (guardrails §12): the platform never
requires pre-registering every physical component in every crane.
`PartMaster` is a catalog/specification concept (created when a part is
first identified, not pre-loaded for an entire BOM); `PartInstance` /
`PositionLifetimeRecord` are created only when actually needed (transfer,
replacement, start of tracking, high-value/safety-critical component —
baseline §12). No seed data pre-enrolls a full machine's parts.

PART MASTER IDENTITY: different specification = different `part_id`, even
when the display name is similar — `PartMaster` never collapses two
distinct specifications under one identity (see
`backend/tests/test_part_master.py`).

SOURCE DATA RULE: no real company part catalog, kit content, or standard-
part compatibility list exists anywhere in this repository. Seed data (see
`app.repositories.mock.seed_data`) is limited to a small number of clearly
-labeled development/example `PartMaster` records spanning each tracking
mode, used only to prove the tracking-mode/part-identity mechanics — never
presented as a real parts catalog.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class TrackingMode(str, Enum):
    NONE = "NONE"
    CONSUMABLE = "CONSUMABLE"
    POSITION_LIFETIME = "POSITION_LIFETIME"
    INSTANCE_TRACKED = "INSTANCE_TRACKED"


class PartMaster(BaseModel):
    """Physical/material specification. Never itself represents an
    installed physical instance (see `app.domain.part_instance.PartInstance`
    for that concept)."""

    part_id: str
    part_code: str
    name: str
    specification: str | None = None
    manufacturer: str | None = None
    part_number: str | None = None
    tracking_mode: TrackingMode
    category: str | None = None
    is_active: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class PartActionType(str, Enum):
    """Actual PM/Repair part action (Phase 5 scope item 5). Purely
    descriptive metadata on an actual-usage record (`PmUsedPart`/
    `RepairPart`) — recording `action=INSTALLED` here does NOT itself
    create an `InstallationSegment`; a real install/remove/transfer of an
    INSTANCE_TRACKED component still goes through
    `PartInstanceService.install`/`remove`/`transfer` explicitly. This
    keeps the free-text PM/Repair actual-part record and the authoritative
    instance-history record from being silently conflated."""

    CONSUMED = "CONSUMED"
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"
    SERVICED = "SERVICED"


class PartSetItemRequirement(str, Enum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    ALTERNATIVE = "ALTERNATIVE"


class PartSet(BaseModel):
    """Stable Part Set / Kit identity."""

    part_set_id: str
    set_code: str
    name: str
    created_at: datetime
    updated_at: datetime


class PartSetItem(BaseModel):
    """One line within a specific, immutable `PartSetRevision`."""

    part_set_item_id: str
    revision_id: str
    part_id: str
    requirement: PartSetItemRequirement
    quantity: float | None = None
    unit: str | None = None
    note: str | None = None


class PartSetRevision(BaseModel):
    """One immutable revision of a Part Set. A later revision is an
    entirely new set of items — never an edit of a previous revision's
    items (baseline §15: "A later kit revision must not rewrite historical
    PM/Repair usage"), mirroring `app.domain.checklist.ChecklistRevision`
    exactly."""

    revision_id: str
    part_set_id: str
    revision_number: int
    effective_date: date
    created_at: datetime


class PartSetRevisionDetail(BaseModel):
    part_set: PartSet
    revision: PartSetRevision
    items: list[PartSetItem]


__all__ = [
    "TrackingMode",
    "PartMaster",
    "PartActionType",
    "PartSetItemRequirement",
    "PartSet",
    "PartSetItem",
    "PartSetRevision",
    "PartSetRevisionDetail",
]
