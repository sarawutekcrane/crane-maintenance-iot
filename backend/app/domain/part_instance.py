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

LIFECYCLE / OVERHAUL BOUNDARY (G04; R6 FINAL §7.2b, Owner decision A-2(ii)):
`PartLifecycle` is a cycle-boundary record, not a business rule about what
qualifies as an overhaul. Since R6 the ONLY way a repaired part starts a new
service cycle is a successful INSTALL that consumes a pending, authorized,
unconsumed approval recorded by `return-from-repair`; the legacy
`start-new-lifecycle` route never creates a lifecycle. Which repairs qualify
remains Owner policy PG-2 (fail-closed in REAL). Lifetime totals are never
reset, a normal repair never resets anything, and the previous lifecycle
and every one of its installation segments remain stored and readable
(proven by `backend/tests/test_part_lifecycle.py` and
`backend/tests/test_r6_part_instance_lifecycle_api.py`).

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

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.domain.asset import AssetType
from app.domain.lifetime_rule import LifetimeTriggerType
from app.domain.vehicle_model import ComponentRole


class PriorUsageQuality(str, Enum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class HistoricalEvidenceType(str, Enum):
    """R6 FINAL §7.3a: the kind of evidence a KNOWN/PARTIAL historical usage
    declaration cites. `NEW_PART` is valid only with value 0 (AP-12)."""

    NEW_PART = "NEW_PART"
    DOCUMENT = "DOCUMENT"
    WORK_ORDER = "WORK_ORDER"
    METER_RECORD = "METER_RECORD"


class ReferenceStatus(str, Enum):
    """Server-derived at declaration time: RESOLVED = the reference names an
    existing in-scope work order or attachment; REFERENCE_UNVERIFIED = free
    text the system cannot check."""

    RESOLVED = "RESOLVED"
    REFERENCE_UNVERIFIED = "REFERENCE_UNVERIFIED"


class VerificationLevel(str, Enum):
    """R6 FINAL §7.3a (F02): DECLARED < EVIDENCE_REFERENCED < VERIFIED."""

    DECLARED = "DECLARED"
    EVIDENCE_REFERENCED = "EVIDENCE_REFERENCED"
    VERIFIED = "VERIFIED"


class PriorUsage(BaseModel):
    """Historical (pre-enrolment) usage declaration (baseline §12; R6 FINAL
    §7.3a `HistoricalUsageDeclaration`). Used both for the prior LIFETIME
    usage (`PartInstance.prior_usage`) and the prior usage within the CURRENT
    CYCLE (`PartInstance.prior_cycle_usage`). `value` is only meaningful for
    KNOWN/PARTIAL; for UNKNOWN it MUST remain `None` — never `0` — and callers
    must never treat a `None` value as zero.

    The R6 evidence fields are additive (all default `None`): a legacy row
    without them is DECLARED (`PRIOR_USAGE_UNEVIDENCED`) and never counts as
    verified. `reference_status`, `declared_by` and `declared_at` are set by
    the server, never taken from a request body."""

    quality: PriorUsageQuality
    value: float | None = None
    note: str | None = None
    basis: LifetimeTriggerType | None = None
    component_role: ComponentRole | None = None
    as_of: date | None = None
    evidence_type: HistoricalEvidenceType | None = None
    evidence_reference: str | None = None
    reference_status: ReferenceStatus | None = None
    declared_by: str | None = None
    declared_at: datetime | None = None


HistoricalUsageDeclaration = PriorUsage


def verification_level(declaration: PriorUsage | None) -> VerificationLevel | None:
    """Pure, deterministic (F02). None for UNKNOWN / no declaration. VERIFIED
    has exactly one source-backed criterion today: a NEW_PART declaration of
    value 0 whose reference resolves (AP-12). Every other KNOWN/PARTIAL
    declaration is at most EVIDENCE_REFERENCED until an Owner-approved
    historical-evidence verification policy exists (PG-6)."""
    if declaration is None or declaration.quality == PriorUsageQuality.UNKNOWN:
        return None
    if declaration.evidence_type is None or declaration.reference_status != ReferenceStatus.RESOLVED:
        return VerificationLevel.DECLARED
    if (declaration.evidence_type == HistoricalEvidenceType.NEW_PART
            and declaration.quality == PriorUsageQuality.KNOWN and declaration.value == 0):
        return VerificationLevel.VERIFIED
    return VerificationLevel.EVIDENCE_REFERENCED


def is_brand_new(declaration: PriorUsage | None) -> bool:
    """AP-12: a VERIFIED brand-new whole part (both counters start at 0)."""
    return verification_level(declaration) == VerificationLevel.VERIFIED


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
    entire machine's BOM.

    R6 FINAL §7.5 identity layers: `part_instance_id` is the system identity;
    `serial_number` / `tag_label` are optional external identifiers, each set
    at most once (null -> value, never overwritten); `storage_location` is
    mutable current custody text and never an identity. `state_version`
    increments on every committed mutation (optimistic concurrency)."""

    part_instance_id: str
    part_id: str
    serial_number: str | None = None
    tag_label: str | None = None
    storage_location: str | None = None
    status: PartInstanceStatus
    prior_usage: PriorUsage
    prior_cycle_usage: PriorUsage | None = None
    current_lifecycle_id: str
    note: str | None = None
    state_version: int = 0
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
    associated with `lifecycle_id` and remain fully readable.

    R6 (A-2(ii), FINAL §7.2b): an R6 repaired-part cycle is opened ONLY by a
    successful install that consumes a pending approved return;
    `start_trigger_event_id` names that return event and is unique across
    every lifecycle (one approval opens at most one cycle). A Phase 5
    OVERHAUL row without a trigger is a legacy untriggered cycle."""

    lifecycle_id: str
    part_instance_id: str
    cycle_number: int
    start_reason: LifecycleStartReason
    started_at: datetime
    started_by: str | None = None
    started_note: str | None = None
    ended_at: datetime | None = None
    start_trigger_event_id: str | None = None
    start_policy_state: str | None = None


class MeterAnchor(BaseModel):
    """R6 FINAL §7.1 / §7.2a step 4 (F05): one verified cumulative reading
    copied, at commit, from the existing R4 selector `select_current_reading`
    (device verified, TIME_SYNCED, observed AND received <= the event's
    effective time, inside the source's freshness window, unambiguous, never
    PTO). Never a machine-state snapshot, `current_counter`, manual entry or
    receipt time."""

    vehicle_id: str
    component_id: str | None = None
    counter_type: str
    value: float
    observed_at: datetime
    received_at: datetime
    time_quality: str
    device_id: str
    device_event_id: str


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
    # R6 additive fields (FINAL §7.1). Effective times default to the
    # recorded times for legacy rows. Snapshot ids above stay machine-state
    # CONTEXT only; usage is computed exclusively from the anchors.
    installed_effective_at: datetime | None = None
    removed_effective_at: datetime | None = None
    source_type: str | None = None
    source_id: str | None = None
    baseline_anchors: list[MeterAnchor] = Field(default_factory=list)
    removal_anchors: list[MeterAnchor] = Field(default_factory=list)
    request_id: str | None = None

    @property
    def effective_start(self) -> datetime:
        return self.installed_effective_at or self.installed_at

    @property
    def effective_end(self) -> datetime | None:
        if self.removed_at is None and self.removed_effective_at is None:
            return None
        return self.removed_effective_at or self.removed_at


class ApprovalState(str, Enum):
    """R6 FINAL §7.2b: the repaired-part new-cycle approval state."""

    NONE = "NONE"
    PENDING = "PENDING"
    CONSUMED = "CONSUMED"
    SUPERSEDED = "SUPERSEDED"


class PartInstanceStatusEvent(BaseModel):
    """R6 FINAL §7.1: append-only status history (one row per committed
    status change, plus identifier assignments with unchanged status).
    Location while installed stays in `InstallationSegment`."""

    event_id: str
    part_instance_id: str
    operation: str
    from_status: PartInstanceStatus | None = None
    to_status: PartInstanceStatus
    effective_at: datetime
    recorded_at: datetime
    actor: str | None = None
    reason: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    meter_snapshot_id: str | None = None
    storage_location: str | None = None
    new_cycle_approved: bool = False
    approval_reason_code: str | None = None
    approval_policy_state: str | None = None
    repair_reference: str | None = None
    approved_by: str | None = None
    request_id: str | None = None


class PartInstanceDetail(BaseModel):
    """Full read model: the instance, its part master, every lifecycle
    (oldest first), and every installation segment across every lifecycle
    (baseline §13: "reconstruct... periods outside a host asset"). R6 adds
    the append-only status events (oldest first)."""

    instance: PartInstance
    lifecycles: list[PartLifecycle]
    segments: list[InstallationSegment]
    status_events: list[PartInstanceStatusEvent] = Field(default_factory=list)


__all__ = [
    "PriorUsageQuality",
    "HistoricalEvidenceType",
    "ReferenceStatus",
    "VerificationLevel",
    "verification_level",
    "is_brand_new",
    "HistoricalUsageDeclaration",
    "MeterAnchor",
    "ApprovalState",
    "PartInstanceStatusEvent",
    "PriorUsage",
    "PartInstanceStatus",
    "PartInstance",
    "LifecycleStartReason",
    "PartLifecycle",
    "InstallationSegmentStatus",
    "InstallationSegment",
    "PartInstanceDetail",
]


# ---------------------------------------------------------------------------
# R6 FINAL §7.2a step 6.5 — invariants validated on a candidate part state
# BEFORE it is published (any violation: nothing is published).
# ---------------------------------------------------------------------------


class PartInvariantError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def position_key(position_code: str | None) -> str | None:
    """Exact-match position identity after trimming (G03 unverified)."""
    if position_code is None:
        return None
    trimmed = position_code.strip()
    return trimmed or None


def check_part_invariants(state) -> None:
    """Raise `PartInvariantError` when the candidate `state` (an
    `app.repositories.base.PartState`) breaks a physical-integrity rule:
    - <= 1 ACTIVE installation segment per instance; INSTALLED iff active;
    - exactly one open lifecycle per instance, equal to `current_lifecycle_id`;
    - every lifecycle `start_trigger_event_id` unique (one approval, one cycle);
    - O-1 one active instance segment per occupied asset position;
    - O-2 one active asset-hosted position record per asset position;
    - O-3 no asset position held by both an instance and a position record;
    - O-4 one active instance-hosted record per (host instance, position);
    - serial unique per part (all statuses), tag unique across all instances."""
    occupied: dict[tuple, str] = {}
    triggers: dict[str, str] = {}
    serials: dict[tuple, str] = {}
    tags: dict[str, str] = {}
    for instance_id, instance in state.instances.items():
        segments = state.segments.get(instance_id, ())
        active = [s for s in segments if s.status == InstallationSegmentStatus.ACTIVE]
        if len(active) > 1:
            raise PartInvariantError("PART_INVARIANT_DOUBLE_ACTIVE_INSTALLATION",
                                     "A part instance cannot be installed in two places at once",
                                     {"part_instance_id": instance_id})
        if (instance.status == PartInstanceStatus.INSTALLED) != bool(active):
            raise PartInvariantError("PART_INVARIANT_STATUS_SEGMENT_MISMATCH",
                                     "Instance status and its installation segments disagree",
                                     {"part_instance_id": instance_id})
        lifecycles = state.lifecycles.get(instance_id, ())
        open_cycles = [lc for lc in lifecycles if lc.ended_at is None]
        if len(open_cycles) != 1 or open_cycles[0].lifecycle_id != instance.current_lifecycle_id:
            raise PartInvariantError("PART_INVARIANT_LIFECYCLE", "Exactly one open lifecycle is required",
                                     {"part_instance_id": instance_id})
        for lc in lifecycles:
            if lc.start_trigger_event_id:
                if lc.start_trigger_event_id in triggers:
                    raise PartInvariantError("PART_INVARIANT_APPROVAL_CONSUMED_TWICE",
                                             "One approved return can open at most one new cycle",
                                             {"return_event_id": lc.start_trigger_event_id})
                triggers[lc.start_trigger_event_id] = lc.lifecycle_id
        for segment in active:
            key = position_key(segment.position_code)
            if key is not None:
                slot = (segment.asset_type.value, segment.asset_id, key)
                if slot in occupied:
                    raise PartInvariantError("PART_INVARIANT_POSITION_OCCUPIED",
                                             "This position is already occupied", {"position_code": key})
                occupied[slot] = instance_id
        if instance.serial_number:
            skey = (instance.part_id, instance.serial_number.strip())
            if skey in serials:
                raise PartInvariantError("PART_INVARIANT_DUPLICATE_SERIAL",
                                         "This serial number is already used for this part")
            serials[skey] = instance_id
        if instance.tag_label:
            tkey = instance.tag_label.strip()
            if tkey in tags:
                raise PartInvariantError("PART_INVARIANT_DUPLICATE_TAG", "This tag label is already used")
            tags[tkey] = instance_id
    hosted: set[tuple] = set()
    for record in state.positions.values():
        if record.ended_at is not None:
            continue
        key = position_key(record.position_code)
        if record.host_part_instance_id:
            if record.host_part_instance_id not in state.instances:
                raise PartInvariantError("PART_INVARIANT_HOST_MISSING", "The host instance does not exist")
            hkey = (record.host_part_instance_id, key)
            if hkey in hosted:
                raise PartInvariantError("PART_INVARIANT_POSITION_OCCUPIED",
                                         "This position on the host instance is already tracked",
                                         {"position_code": key})
            hosted.add(hkey)
            continue
        slot = (record.asset_type.value if record.asset_type else None, record.asset_id, key)
        if slot in occupied:
            raise PartInvariantError("PART_INVARIANT_POSITION_OCCUPIED", "This position is already occupied",
                                     {"position_code": key})
        occupied[slot] = record.position_lifetime_id
