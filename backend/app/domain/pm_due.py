"""R4 DUE-01: pure, per-Set PM due calculation over *already verified* inputs.

No repository calls, writes, side effects, master publication, or meter lookup.
A future DUE-02 integration must establish the actual completed Set/Group,
physical component, trustworthy meter readings, and source provenance BEFORE
marking any of the verification flags True. A CLOSED (possibly partial) PM work
order, an Outstanding resolution, or a snapshot by itself is not that proof.

The strings used here are existing PM/meter/component enum *values*, not new
API enums. This internal result must not be exposed as a public API contract
without a separate review. Existing PM uses ENGINE_HOUR or vehicle ODOMETER,
never PTO_HOUR. PTO telemetry elsewhere is unaffected.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, kw_only=True)
class PmDueInputs:
    """Values and verification outcomes supplied by an authoritative caller.

    ``set_ref`` is an *opaque, already-proven* vehicle/Plan/Set/Group reference,
    not a new generated key. ``source_verified`` covers that identity, revision,
    interval and source mapping; this function cannot independently prove them.

    ENGINE_HOUR requires a verified physical engine component ID and role.
    ODOMETER is vehicle-level and must have no component ID; the existing
    VEHICLE role is allowed but is not an engine. Missing verification is not 0.
    """

    set_ref: str
    meter_type: str | None
    interval: float | None
    interval_unit: str | None
    last_completed_meter: float | None
    current_meter: float | None
    source_verified: bool = False
    last_completion_verified: bool = False
    current_meter_verified: bool = False
    driving_component_role: str | None = None
    component_id: str | None = None
    component_verified: bool = False


@dataclass(frozen=True)
class PmDueDecision:
    """Internal calculation result; UNKNOWN is deliberately not due."""

    status: str  # DUE | NOT_DUE | UNKNOWN (internal, not an API enum)
    next_due: float | None = None
    reason: str | None = None

    @property
    def is_due(self) -> bool | None:
        if self.status == "UNKNOWN":
            return None
        return self.status == "DUE"


def _unknown(reason: str) -> PmDueDecision:
    return PmDueDecision(status="UNKNOWN", reason=reason)


def _nonnegative_finite(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return isfinite(numeric) and numeric >= 0


def calculate_pm_due(inputs: PmDueInputs) -> PmDueDecision:
    """Calculate the next *meter threshold* for one verified PM Set/Group.

    Threshold = verified last ACTUAL completed same-Set meter + source interval.
    DUE when current verified meter >= threshold; otherwise NOT_DUE.
    Invalid, contradictory, unsupported, or unverified facts fail to UNKNOWN.
    No warning windows, calendar intervals, work-order mutations, or alerts.
    """
    if inputs.source_verified is not True or not isinstance(inputs.set_ref, str) or not inputs.set_ref.strip():
        return _unknown("SET_SOURCE_UNVERIFIED")

    if inputs.meter_type not in ("ENGINE_HOUR", "ODOMETER"):
        return _unknown("PM_METER_NOT_APPROVED")

    unit = inputs.interval_unit.strip().upper() if isinstance(inputs.interval_unit, str) else None
    expected_unit = "HOUR" if inputs.meter_type == "ENGINE_HOUR" else "KM"
    if unit != expected_unit:
        return _unknown("INTERVAL_UNIT_MISMATCH")
    if not _nonnegative_finite(inputs.interval) or inputs.interval == 0:
        return _unknown("INTERVAL_INVALID")

    if inputs.meter_type == "ENGINE_HOUR":
        if (inputs.driving_component_role not in ("CARRIER_ENGINE", "CRANE_ENGINE")
                or inputs.component_verified is not True
                or not isinstance(inputs.component_id, str)
                or not inputs.component_id.strip()):
            return _unknown("PHYSICAL_ENGINE_UNVERIFIED")
    elif inputs.component_id is not None or inputs.driving_component_role not in (None, "VEHICLE"):
        return _unknown("ODOMETER_MUST_BE_VEHICLE_LEVEL")

    if inputs.last_completion_verified is not True or not _nonnegative_finite(inputs.last_completed_meter):
        return _unknown("LAST_ACTUAL_SET_COMPLETION_UNVERIFIED")
    if inputs.current_meter_verified is not True or not _nonnegative_finite(inputs.current_meter):
        return _unknown("CURRENT_METER_UNVERIFIED")
    if inputs.current_meter < inputs.last_completed_meter:
        # Counter replacements/resets require an independent approved policy.
        return _unknown("COUNTER_DECREASE_UNRESOLVED")

    last_value = float(inputs.last_completed_meter)
    current_value = float(inputs.current_meter)
    next_due = last_value + float(inputs.interval)
    if not isfinite(next_due):
        return _unknown("NEXT_DUE_OVERFLOW")
    return PmDueDecision(
        status="DUE" if current_value >= next_due else "NOT_DUE",
        next_due=float(next_due),
    )
