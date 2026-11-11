"""R6 — verified part usage counters (FINAL §7.3, §7.3a; C1, R3-03, R3-04, F02,
F04, F05). Pure: no repository, clock or meter-source access.

FOUR QUANTITIES, NEVER CONFLATED
- `tracked_since_enrollment`: Σ verified segment deltas over every lifecycle;
- `tracked_in_current_cycle`: Σ verified segment deltas of the current lifecycle;
- `verified_lifetime_total`: prior lifetime declaration + tracked_since_enrollment;
- `verified_current_cycle`: an approved new cycle -> its tracked usage; the
  enrolment cycle -> prior cycle declaration + its tracked usage.
A tracked figure is never presented as a lifetime or cycle value.

METER EVIDENCE (R3-04 / F03 / F05)
A segment delta uses ONLY the verified anchors embedded on the segment (copied
at commit from the R4 selector `select_current_reading`) and, for an active
segment, a verified current reading the caller obtained with the same
selector. Machine-state snapshots (`current_counter`, manual entries, receipt
time) are never used. A delta is computed only within ONE segment and only
when both readings come from the same vehicle, the same component and the same
device. Anything missing, mismatched, reset (negative) or unresolvable is
UNKNOWN with a machine-readable reason — never 0 and never guessed.

QUALITY / POLICY
- UNKNOWN in -> UNKNOWN out (value None).
- PARTIAL prior usage -> PARTIAL_RECORDED (value None): its meaning is not
  defined by the baseline, so it is never used as a lower bound.
- Historical declarations count by verification level (F02): REAL accepts
  VERIFIED only (today: a brand-new NEW_PART 0 with a resolving reference);
  TEST may also use EVIDENCE_REFERENCED, labelled TEST_PROPOSED; DECLARED (free
  text only) is never used.
- A used part's prior cycle usage is Owner policy PG-1: REAL keeps the cycle
  UNKNOWN (PENDING) whatever is declared; TEST may use an EVIDENCE_REFERENCED
  declaration as TEST_PROPOSED. `PolicyContext` comes only from the server's
  data context, never from a request.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.asset import AssetType
from app.domain.part_instance import (
    InstallationSegment,
    LifecycleStartReason,
    MeterAnchor,
    PartLifecycle,
    PriorUsage,
    PriorUsageQuality,
    VerificationLevel,
    is_brand_new,
    verification_level,
)

KNOWN = "KNOWN"
UNKNOWN = "UNKNOWN"
PARTIAL_RECORDED = "PARTIAL_RECORDED"

APPROVED = "APPROVED"
TEST_PROPOSED = "TEST_PROPOSED"
PENDING = "PENDING"

ENGINE_HOUR = "ENGINE_HOUR"
ODOMETER = "ODOMETER"
ENGINE_ROLES = frozenset({"CARRIER_ENGINE", "CRANE_ENGINE"})

# Reasons (machine-readable; the frontend maps them to Thai labels).
METER_EVIDENCE_MISSING = "METER_EVIDENCE_MISSING"
METER_SOURCE_MISMATCH = "METER_SOURCE_MISMATCH"
METER_DEVICE_CHANGED = "METER_DEVICE_CHANGED"
NEGATIVE_DELTA = "NEGATIVE_DELTA"
COMPONENT_UNRESOLVED = "COMPONENT_UNRESOLVED"
NO_COUNTER_MODEL = "NO_COUNTER_MODEL_FOR_ASSET"
PRIOR_USAGE_UNKNOWN = "PRIOR_USAGE_UNKNOWN"
PRIOR_USAGE_PARTIAL = "PRIOR_USAGE_PARTIAL"
PRIOR_USAGE_UNEVIDENCED = "PRIOR_USAGE_UNEVIDENCED"
HISTORICAL_USAGE_NOT_VERIFIED = "HISTORICAL_USAGE_NOT_VERIFIED"
PRIOR_USAGE_BASIS_MISMATCH = "PRIOR_USAGE_BASIS_MISMATCH"
PRIOR_CYCLE_USAGE_UNKNOWN = "PRIOR_CYCLE_USAGE_UNKNOWN"
PRIOR_CYCLE_USAGE_POLICY_PENDING = "PRIOR_CYCLE_USAGE_POLICY_PENDING"
LEGACY_UNTRIGGERED_CYCLE = "LEGACY_UNTRIGGERED_CYCLE"
REFERENCE_UNVERIFIED = "REFERENCE_UNVERIFIED"


@dataclass(frozen=True)
class PolicyContext:
    """The server's data context. Only TEST may exercise TEST_PROPOSED
    behaviour; REAL and an unconfigured context are both fail-closed."""

    data_context: str | None

    @property
    def is_test(self) -> bool:
        return self.data_context == "TEST"


@dataclass(frozen=True)
class Basis:
    """A counter dimension a rule reads: ENGINE_HOUR of exactly one physical
    engine role, or the vehicle-level ODOMETER."""

    counter_type: str
    component_role: str | None = None


@dataclass(frozen=True)
class Quantity:
    value: float | None
    quality: str
    policy_state: str | None = None
    reasons: tuple[str, ...] = ()

    @property
    def is_known(self) -> bool:
        return self.quality == KNOWN and self.value is not None


def _unknown(*reasons: str, policy_state: str | None = None) -> Quantity:
    return Quantity(None, UNKNOWN, policy_state, tuple(dict.fromkeys(reasons)))


_POLICY_RANK = {None: 0, APPROVED: 0, TEST_PROPOSED: 1, PENDING: 2}


def worst_policy(*states: str | None) -> str | None:
    """PENDING > TEST_PROPOSED > APPROVED/None."""
    chosen: str | None = None
    for state in states:
        if _POLICY_RANK.get(state, 0) > _POLICY_RANK.get(chosen, 0):
            chosen = state
    return chosen


def add(a: Quantity, b: Quantity) -> Quantity:
    """Sum of two quantities; UNKNOWN / PARTIAL dominate (Q-1, Q-2)."""
    reasons = tuple(dict.fromkeys(a.reasons + b.reasons))
    policy = worst_policy(a.policy_state, b.policy_state)
    if a.quality == UNKNOWN or b.quality == UNKNOWN:
        return Quantity(None, UNKNOWN, policy, reasons)
    if a.quality == PARTIAL_RECORDED or b.quality == PARTIAL_RECORDED:
        return Quantity(None, PARTIAL_RECORDED, policy, reasons)
    return Quantity(float(a.value) + float(b.value), KNOWN, policy, reasons)


# ---------------------------------------------------------------------------
# Segment deltas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentInput:
    """One installation segment with the context its delta needs: the host
    vehicle's `(component_id, role)` pairs (from `list_vehicle_components`)
    and, for an ACTIVE segment, the verified current reading of each anchor
    dimension (`current_end`, obtained by the caller with the R4 selector at
    evaluation time; empty when none is eligible)."""

    segment: InstallationSegment
    components: tuple[tuple[str, str], ...] = ()
    current_end: tuple[MeterAnchor, ...] = ()


def resolve_component(components: Sequence[tuple[str, str]], basis: Basis) -> tuple[str | None, str | None]:
    """(component_id, None) or (None, reason). ODOMETER is vehicle-level
    (component_id None). ENGINE_HOUR needs EXACTLY one component of the
    rule's engine role: 0 or >1 is unresolved (never guessed)."""
    if basis.counter_type == ODOMETER:
        return None, None
    if basis.counter_type != ENGINE_HOUR or basis.component_role not in ENGINE_ROLES:
        return None, COMPONENT_UNRESOLVED
    matches = [cid for cid, role in components if role == basis.component_role]
    if len(matches) != 1:
        return None, COMPONENT_UNRESOLVED
    return matches[0], None


def find_anchor(anchors: Sequence[MeterAnchor], vehicle_id: str | None, counter_type: str,
                component_id: str | None) -> MeterAnchor | None:
    for anchor in anchors:
        if (anchor.vehicle_id == vehicle_id and anchor.counter_type == counter_type
                and anchor.component_id == component_id):
            return anchor
    return None


def delta_between(start: MeterAnchor | None, end: MeterAnchor | None) -> tuple[float | None, str | None]:
    """R-1…R-4: both verified readings present, same vehicle, same component,
    same device, non-negative difference."""
    if start is None or end is None:
        return None, METER_EVIDENCE_MISSING
    if start.vehicle_id != end.vehicle_id or start.component_id != end.component_id \
            or start.counter_type != end.counter_type:
        return None, METER_SOURCE_MISMATCH
    if start.device_id != end.device_id:
        return None, METER_DEVICE_CHANGED
    value = float(end.value) - float(start.value)
    if value < 0:
        return None, NEGATIVE_DELTA
    return value, None


def segment_delta(item: SegmentInput, basis: Basis, *, clip_start: MeterAnchor | None = None,
                  clip_end: MeterAnchor | None = None, use_clip_start: bool = False,
                  use_clip_end: bool = False) -> tuple[float | None, str | None]:
    """The verified delta of one segment for `basis`. `use_clip_start` /
    `use_clip_end` replace the segment's own boundary with a reading taken
    inside it (a hosted record or a maintenance event that started / ended
    mid-segment); a missing clip reading stays missing (UNKNOWN)."""
    segment = item.segment
    if segment.asset_type != AssetType.VEHICLE:
        return None, NO_COUNTER_MODEL
    component_id, reason = resolve_component(item.components, basis)
    if reason is not None:
        return None, reason
    vehicle = segment.asset_id
    start = clip_start if use_clip_start else find_anchor(segment.baseline_anchors, vehicle, basis.counter_type,
                                                          component_id)
    if use_clip_end:
        end = clip_end
    elif segment.effective_end is not None:
        end = find_anchor(segment.removal_anchors, vehicle, basis.counter_type, component_id)
    else:
        end = find_anchor(item.current_end, vehicle, basis.counter_type, component_id)
    if start is not None and (start.vehicle_id != vehicle or start.component_id != component_id):
        return None, METER_SOURCE_MISMATCH
    if end is not None and (end.vehicle_id != vehicle or end.component_id != component_id):
        return None, METER_SOURCE_MISMATCH
    return delta_between(start, end)


def sum_deltas(deltas: Sequence[tuple[float | None, str | None]]) -> Quantity:
    """Σ of verified deltas; no segment at all is a KNOWN 0 of tracked usage
    (nothing was tracked), any unknown delta makes the sum UNKNOWN."""
    reasons = [reason for value, reason in deltas if value is None and reason]
    if reasons or any(value is None for value, _ in deltas):
        return _unknown(*(reasons or [METER_EVIDENCE_MISSING]))
    return Quantity(float(sum(value for value, _ in deltas)), KNOWN)


def clipped_usage(items: Sequence[SegmentInput], basis: Basis, *, start_at: datetime | None,
                  start_anchors: Sequence[MeterAnchor] = (), end_at: datetime | None = None,
                  end_anchors: Sequence[MeterAnchor] = ()) -> Quantity:
    """Verified usage of the given host segments inside [start_at, end_at)
    (None = unbounded). Used for an instance-hosted record (a seal follows its
    cylinder: O-4) and for usage since a maintenance event. A segment cut by a
    boundary uses the boundary's own verified reading on that segment's
    vehicle; a missing boundary reading leaves that segment UNKNOWN."""
    deltas: list[tuple[float | None, str | None]] = []
    for item in items:
        seg_start = item.segment.effective_start
        seg_end = item.segment.effective_end
        if end_at is not None and seg_start >= end_at:
            continue
        if start_at is not None and seg_end is not None and seg_end <= start_at:
            continue
        cut_start = start_at is not None and start_at > seg_start
        cut_end = end_at is not None and (seg_end is None or end_at < seg_end)
        vehicle = item.segment.asset_id
        component_id, _ = resolve_component(item.components, basis)
        clip_start = find_anchor(start_anchors, vehicle, basis.counter_type, component_id) if cut_start else None
        clip_end = find_anchor(end_anchors, vehicle, basis.counter_type, component_id) if cut_end else None
        deltas.append(segment_delta(item, basis, clip_start=clip_start, clip_end=clip_end,
                                    use_clip_start=cut_start, use_clip_end=cut_end))
    return sum_deltas(deltas)


# ---------------------------------------------------------------------------
# Historical declarations
# ---------------------------------------------------------------------------


def _basis_matches(declaration: PriorUsage, basis: Basis) -> bool:
    if declaration.basis is None or declaration.basis.value != basis.counter_type:
        return False
    if basis.counter_type == ENGINE_HOUR:
        role = declaration.component_role.value if declaration.component_role else None
        return role == basis.component_role
    return True


def declared_quantity(declaration: PriorUsage | None, basis: Basis, policy: PolicyContext, *,
                      missing_reason: str) -> Quantity:
    """The usable value of one historical declaration for `basis` (F02)."""
    if declaration is None or declaration.quality == PriorUsageQuality.UNKNOWN:
        return _unknown(missing_reason)
    if declaration.quality == PriorUsageQuality.PARTIAL:
        return Quantity(None, PARTIAL_RECORDED, None, (PRIOR_USAGE_PARTIAL,))
    level = verification_level(declaration)
    if level == VerificationLevel.DECLARED:
        reason = PRIOR_USAGE_UNEVIDENCED if declaration.evidence_type is None else HISTORICAL_USAGE_NOT_VERIFIED
        return _unknown(reason, REFERENCE_UNVERIFIED) if declaration.evidence_type else _unknown(reason)
    if level == VerificationLevel.VERIFIED:
        # AP-12: a verified brand-new part is 0 on every basis.
        return Quantity(0.0, KNOWN, APPROVED)
    # EVIDENCE_REFERENCED: proves a record exists, not that the value is right.
    if not policy.is_test:
        return _unknown(HISTORICAL_USAGE_NOT_VERIFIED, policy_state=PENDING)
    if not _basis_matches(declaration, basis):
        return _unknown(PRIOR_USAGE_BASIS_MISMATCH, policy_state=TEST_PROPOSED)
    return Quantity(float(declaration.value), KNOWN, TEST_PROPOSED)


@dataclass(frozen=True)
class Counters:
    tracked_since_enrollment: Quantity
    tracked_in_current_cycle: Quantity
    verified_lifetime_total: Quantity
    verified_current_cycle: Quantity
    extra: dict = field(default_factory=dict)


def current_lifecycle(lifecycles: Sequence[PartLifecycle], current_lifecycle_id: str) -> PartLifecycle | None:
    return next((lc for lc in lifecycles if lc.lifecycle_id == current_lifecycle_id), None)


def instance_counters(*, prior_usage: PriorUsage, prior_cycle_usage: PriorUsage | None,
                      lifecycles: Sequence[PartLifecycle], current_lifecycle_id: str,
                      items: Sequence[SegmentInput], basis: Basis, policy: PolicyContext) -> Counters:
    """The four quantities of one part instance for one basis."""
    tracked_all = sum_deltas([segment_delta(i, basis) for i in items])
    current_items = [i for i in items if i.segment.lifecycle_id == current_lifecycle_id]
    tracked_cycle = sum_deltas([segment_delta(i, basis) for i in current_items])

    prior_life = declared_quantity(prior_usage, basis, policy, missing_reason=PRIOR_USAGE_UNKNOWN)
    lifetime = add(prior_life, tracked_all)

    lifecycle = current_lifecycle(lifecycles, current_lifecycle_id)
    if lifecycle is not None and lifecycle.start_reason == LifecycleStartReason.OVERHAUL:
        if lifecycle.start_trigger_event_id:
            # An R6 approved new cycle (A-2(ii)): its own tracked usage only.
            cycle = Quantity(tracked_cycle.value, tracked_cycle.quality,
                             worst_policy(tracked_cycle.policy_state, lifecycle.start_policy_state),
                             tracked_cycle.reasons)
        else:
            # Phase 5 free-text OVERHAUL row (TEST data only): readable, flagged.
            state = TEST_PROPOSED if policy.is_test else PENDING
            cycle = (Quantity(tracked_cycle.value, tracked_cycle.quality, state,
                              tracked_cycle.reasons + (LEGACY_UNTRIGGERED_CYCLE,))
                     if policy.is_test else _unknown(LEGACY_UNTRIGGERED_CYCLE, policy_state=PENDING))
    else:
        cycle = add(_prior_cycle_quantity(prior_usage, prior_cycle_usage, basis, policy), tracked_cycle)
    return Counters(tracked_all, tracked_cycle, lifetime, cycle)


def _prior_cycle_quantity(prior_usage: PriorUsage, prior_cycle_usage: PriorUsage | None, basis: Basis,
                          policy: PolicyContext) -> Quantity:
    """The enrolment cycle's pre-enrolment usage (PG-1 / F04)."""
    if is_brand_new(prior_usage):
        return Quantity(0.0, KNOWN, APPROVED)
    if prior_cycle_usage is None or prior_cycle_usage.quality == PriorUsageQuality.UNKNOWN:
        return _unknown(PRIOR_CYCLE_USAGE_UNKNOWN)
    if not policy.is_test:
        return _unknown(PRIOR_CYCLE_USAGE_POLICY_PENDING, policy_state=PENDING)
    return declared_quantity(prior_cycle_usage, basis, policy, missing_reason=PRIOR_CYCLE_USAGE_UNKNOWN)


def record_counters(*, prior_usage: PriorUsage, usage: Quantity, policy: PolicyContext,
                    basis: Basis) -> Counters:
    """A position-lifetime record is one tracked cycle of the component at
    that position (replace opens a successor). It carries no separate prior
    cycle declaration, so its current cycle equals its lifetime only for a
    VERIFIED brand-new component; otherwise the cycle stays UNKNOWN (PG-1)."""
    lifetime = add(declared_quantity(prior_usage, basis, policy, missing_reason=PRIOR_USAGE_UNKNOWN), usage)
    if is_brand_new(prior_usage):
        cycle = lifetime
    else:
        cycle = _unknown(PRIOR_CYCLE_USAGE_UNKNOWN if policy.is_test else PRIOR_CYCLE_USAGE_POLICY_PENDING,
                         policy_state=None if policy.is_test else PENDING)
    return Counters(usage, usage, lifetime, cycle)


__all__ = [
    "KNOWN", "UNKNOWN", "PARTIAL_RECORDED", "APPROVED", "TEST_PROPOSED", "PENDING",
    "PolicyContext", "Basis", "Quantity", "SegmentInput", "Counters",
    "resolve_component", "find_anchor", "delta_between", "segment_delta", "sum_deltas", "clipped_usage",
    "declared_quantity", "instance_counters", "record_counters", "worst_policy", "add", "current_lifecycle",
]
