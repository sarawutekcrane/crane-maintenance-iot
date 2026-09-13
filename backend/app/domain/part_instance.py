"""INSTANCE_TRACKED part instances, lifecycle (overhaul) boundaries, and
installation/removal/transfer usage-segment history (Phase 5 scope;
baseline sections 12, 13, 14; guardrails §12; OPEN_DECISIONS_REGISTER_EN.txt
G04, G05).

PRIOR USAGE (baseline §12): three explicit quality states. `UNKNOWN` must
never be estimated or silently coerced to `0`/`KNOWN` anywhere in this
module, the repository, the API, or the frontend (see
`backend/tests/test_prior_usage.py`).

PART INSTANCE STATUS (OPEN_DECISIONS_REGISTER_EN.txt G05 — "PARTIALLY
FROZEN: known states INSTALLED, REMOVED, IN_REPAIR, READY_FOR_INSTALL,
STOCK, SCRAPPED; need transition matrix/permissions"): `PartInstanceStatus`
below declares exactly those six known states and nothing more. G05 is NOT
fully resolved — `PartInstanceService` enforces only the minimal guards a
physical instance's own consistency requires technically (never two active
installations at once, never install a SCRAPPED instance, never remove/
transfer an instance that is not currently INSTALLED), never a full
company-approved transition matrix/permission model.

LIFECYCLE / OVERHAUL BOUNDARY (G04 — "Overhaul Reset Rules:
SOURCE-DATA-REQUIRED"): `PartLifecycle` is a cycle-boundary record, not a
business rule about what qualifies as an overhaul. Starting a new
lifecycle (`PartInstanceService.start_new_lifecycle`) requires the caller
to supply an explicit `approved_reason` string — this module never decides
which repair qualifies as an overhaul, never auto-detects one from repair
history, and never resets accumulated usage as a side effect of a normal
repair. The previous lifecycle and every one of its installation segments
remain stored and readable after a new lifecycle starts (proven by
`backend/tests/test_part_lifecycle.py`).

INSTALLATION SEGMENT / TRANSFER (baseline §13): append-oriented history.
`InstallationSegment` records are never edited or deleted — closing one
(`removed_at` set) and opening a new one is how a transfer or a repair
pause is represented; the physical instance's own accumulated usage is
reconstructed by reading every segment across every lifecycle, never by
mutating a running total in place.

IN_REPAIR RULE (baseline §13, guardrails §12): while a `PartInstance` is
`IN_REPAIR` (or otherwise not `INSTALLED`), it has no ACTIVE
`InstallationSegment` — so it cannot accumulate any host vehicle's
ENGINE_HOUR/PTO_HOUR/ODOMETER during that period; this falls directly out
of the segment model (no active segment => no host to accumulate from),
never out of an explicit "pause" flag that could be forgotten.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.domain.asset import AssetType


class PriorUsageQuality(str, Enum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class PriorUsage(BaseModel):
    """Historical usage state at the moment a component is first enrolled
    for tracking (baseline §12). `value` is only meaningful for KNOWN/
    PARTIAL; for UNKNOWN it MUST remain `None` — never `0` — and callers
    must never treat a `None` value as zero."""

    quality: PriorUsageQuality
    value: float | None = None
    note: str | None = None


class PartInstanceStatus(str, Enum):
    """PARTIALLY FROZEN (G05) — known states only, see module docstring.
    No transition matrix is declared here; `PartInstanceService` enforces
    only the minimal technical guards described above."""

    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"
    IN_REPAIR = "IN_REPAIR"
    READY_FOR_INSTALL = "READY_FOR_INSTALL"
    STOCK = "STOCK"
    SCRAPPED = "SCRAPPED"


class PartInstance(BaseModel):
    """Stable physical-instance identity for an INSTANCE_TRACKED part.
    Created on demand (guardrails §12) — never pre-registered for an
    entire machine's BOM."""

    part_instance_id: str
    part_id: str
    serial_number: str | None = None
    status: PartInstanceStatus
    prior_usage: PriorUsage
    current_lifecycle_id: str
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class LifecycleStartReason(str, Enum):
    """ENROLLMENT: the instance's first tracked lifecycle, created
    automatically when the instance itself is created. OVERHAUL: an
    explicitly caller-approved new cycle (G04) — this module never decides
    which repair qualifies."""

    ENROLLMENT = "ENROLLMENT"
    OVERHAUL = "OVERHAUL"


class PartLifecycle(BaseModel):
    """One tracked lifecycle/cycle for a `PartInstance`. `ended_at` is
    `None` while this is the instance's `current_lifecycle_id`; once a new
    lifecycle starts, this record's `ended_at` is set and it is never
    edited again — the old cycle's own installation segments remain
    associated with `lifecycle_id` and remain fully readable."""

    lifecycle_id: str
    part_instance_id: str
    cycle_number: int
    start_reason: LifecycleStartReason
    started_at: datetime
    started_by: str | None = None
    started_note: str | None = None
    ended_at: datetime | None = None


class InstallationSegmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class InstallationSegment(BaseModel):
    """One installation occurrence of a `PartInstance` on a host asset,
    within one `PartLifecycle` (baseline §13). Never edited in place once
    closed — `InstallationSegment` rows are append-oriented history; a
    transfer closes the active segment and opens a new one, it never
    rewrites the closed one."""

    segment_id: str
    part_instance_id: str
    lifecycle_id: str
    asset_type: AssetType
    asset_id: str
    position_code: str | None = None
    status: InstallationSegmentStatus
    installed_at: datetime
    installed_by: str | None = None
    baseline_meter_snapshot_id: str | None = None
    install_note: str | None = None
    removed_at: datetime | None = None
    removed_by: str | None = None
    removal_meter_snapshot_id: str | None = None
    removal_reason: str | None = None


class PartInstanceDetail(BaseModel):
    """Full read model: the instance, its part master, every lifecycle
    (oldest first), and every installation segment across every lifecycle
    (baseline §13: "reconstruct... periods outside a host asset")."""

    instance: PartInstance
    lifecycles: list[PartLifecycle]
    segments: list[InstallationSegment]


__all__ = [
    "PriorUsageQuality",
    "PriorUsage",
    "PartInstanceStatus",
    "PartInstance",
    "LifecycleStartReason",
    "PartLifecycle",
    "InstallationSegmentStatus",
    "InstallationSegment",
    "PartInstanceDetail",
]
