"""R4 / TASK-010 (DEC-R4-TASK010-PM-TECH-SUBMIT-ANCHOR-003, DEC-R4-TASK010-IOT-METER-001):
the IoT cumulative meter anchor of an E01 technician SUBMIT.

The technician's SUBMIT (IN_PROGRESS -> PENDING_REVIEW) is the PM completion time.
At that SUBMIT the eligible IoT cumulative readings are bound, ONCE and immutably,
to that exact journal event (`submit_event_id`). The reviewer's later CLOSE is
administrative acceptance: it never replaces the anchor (its machine-state capture
is unchanged and is not Due evidence).

What counts as a reading (fail closed, never substituted):
- vehicle-level ODOMETER, and ENGINE_HOUR of each physical CARRIER_ENGINE /
  CRANE_ENGINE component; PTO_HOUR never drives an existing PM schedule;
- from an IoT source that vouches for the device <-> vehicle/component association
  (`device_verified`), with the DEVICE's own observation time, TIME_SYNCED, not
  later than the SUBMIT and inside the source's freshness window;
- RECEIVED by the backend no later than the SUBMIT, so a replay selects exactly the
  same readings (whether a later-uploaded offline reading may count is an open
  Owner decision; until then it does not);
- never browser-entered readings, server receipt or snapshot time, `current_counter`,
  or ENGINE_START/STOP elapsed time.

No IoT counter source exists in the platform yet (no device authentication, device
registry or cumulative-counter ingestion). The runtime default is
`NO_IOT_METER_SOURCE`, which yields nothing, so nothing is bound and Due stays
UNKNOWN. Only tests inject a fake source.

`work_order_evidence` is the PURE builder of the DUE-02A input. It marks the journal
authoritative, so a caller may pass it ONLY a journal and records it has already
proven: the application's sole caller is `PmService` (Fleet PM Due B1), after the R3
E01 read-integrity checks (`_read_only_status`: ownership, TEST/REAL scope, journal
identity / chain / provenance, header consistency, CLOSE evidence and foreign
snapshots) and its own Outcome / result / anchor checks. `read_work_order_evidence`
is the offline unit-proof assembler over a trusted Mock fixture (repository READS
ONLY, never E01 `_current_status`, which can project and write); it performs no
integrity proof and no application module may use it.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Protocol

from app.domain.asset import AssetType
from app.domain.meter import CounterType
from app.domain.pm import PmE01ContractAction
from app.domain.vehicle_event import TimeQuality
from app.domain.vehicle_model import ComponentRole

_ENGINE_ROLES = (ComponentRole.CARRIER_ENGINE, ComponentRole.CRANE_ENGINE)


@dataclass(frozen=True)
class IotMeterObservation:
    """One cumulative counter value as an IoT source reports it."""

    vehicle_id: str
    component_id: str | None  # None only for the vehicle-level ODOMETER
    counter_type: str
    value: float | None
    observed_at: datetime | None  # the device's own observation time
    received_at: datetime | None  # when the backend received it
    time_quality: str
    device_id: str
    device_event_id: str
    device_verified: bool = False  # the source proved device <-> vehicle/component


class IotMeterSource(Protocol):
    """Where verified cumulative observations come from. `max_observation_age` is the
    freshness window the source vouches for; None means it cannot vouch (fail closed)."""

    max_observation_age: timedelta | None

    async def observations(self, vehicle_id: str, *, not_after: datetime) -> Sequence[IotMeterObservation]: ...


class _NoIotMeterSource:
    """The runtime default: no IoT counter infrastructure exists, so nothing is bound."""

    max_observation_age: timedelta | None = None

    async def observations(self, vehicle_id: str, *, not_after: datetime) -> Sequence[IotMeterObservation]:
        return ()


NO_IOT_METER_SOURCE: IotMeterSource = _NoIotMeterSource()


@dataclass(frozen=True)
class SubmitMeterReading:
    counter_type: str
    component_id: str | None
    value: float | None
    observed_at: datetime | None
    received_at: datetime | None
    time_quality: str
    device_id: str
    device_event_id: str
    device_verified: bool = False


@dataclass(frozen=True)
class PmSubmitMeterAnchor:
    """The immutable readings bound to ONE technician SUBMIT event. Empty `readings`
    means the SUBMIT was evaluated and no reading was eligible (still immutable)."""

    pm_work_order_id: str
    submit_event_id: str
    submitted_at: datetime
    asset_type: str
    asset_id: str
    max_observation_age: timedelta
    readings: tuple[SubmitMeterReading, ...]
    is_test_data: str = ""
    test_batch_id: str = ""


def _instant(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _meter(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return isfinite(number) and number >= 0


def _anchor_dimensions(components: Sequence[tuple[str, str]]) -> tuple[tuple[str, str | None], ...]:
    """(counter_type, component_id) a vehicle can be anchored on: its ODOMETER and the
    ENGINE_HOUR of each physical engine. A PTO component never yields a dimension."""
    engines = sorted(cid for cid, role in components if role in {r.value for r in _ENGINE_ROLES})
    return ((CounterType.ODOMETER.value, None), *((CounterType.ENGINE_HOUR.value, cid) for cid in engines))


def _eligible(observation: IotMeterObservation, *, vehicle_id: str, counter_type: str, component_id: str | None,
             submitted_at: datetime, max_observation_age: timedelta | None) -> bool:
    return (max_observation_age is not None and max_observation_age > timedelta(0)
            and observation.vehicle_id == vehicle_id
            and (observation.counter_type, observation.component_id) == (counter_type, component_id)
            and counter_type != CounterType.PTO_HOUR.value
            and observation.device_verified is True
            and observation.time_quality == TimeQuality.TIME_SYNCED.value
            and bool((observation.device_id or "").strip()) and bool((observation.device_event_id or "").strip())
            and _meter(observation.value)
            and _instant(observation.observed_at) and _instant(observation.received_at)
            and observation.observed_at <= submitted_at and observation.received_at <= submitted_at
            and submitted_at - observation.observed_at <= max_observation_age)


def select_submit_readings(observations: Sequence[IotMeterObservation], *, vehicle_id: str,
                           components: Sequence[tuple[str, str]], submitted_at: datetime,
                           max_observation_age: timedelta | None) -> tuple[SubmitMeterReading, ...]:
    """Per dimension, the latest eligible observation. Two latest observations that
    disagree are ambiguous: that dimension is left out (never guessed)."""
    chosen: list[SubmitMeterReading] = []
    for counter_type, component_id in _anchor_dimensions(components):
        candidates = [o for o in observations if _eligible(
            o, vehicle_id=vehicle_id, counter_type=counter_type, component_id=component_id,
            submitted_at=submitted_at, max_observation_age=max_observation_age)]
        if not candidates:
            continue
        latest_at = max(o.observed_at for o in candidates)
        latest = sorted((o for o in candidates if o.observed_at == latest_at), key=lambda o: o.device_event_id)
        if len({float(o.value) for o in latest}) != 1:
            continue
        o = latest[0]
        chosen.append(SubmitMeterReading(counter_type, component_id, float(o.value), o.observed_at, o.received_at,
                                         o.time_quality, o.device_id, o.device_event_id, True))
    return tuple(chosen)


def select_current_reading(observations: Sequence[IotMeterObservation], *, vehicle_id: str,
                           components: Sequence[tuple[str, str]], counter_type: str, component_id: str | None,
                           at: datetime, max_observation_age: timedelta | None) -> SubmitMeterReading | None:
    """R4 / TASK-010 D1: the verified CURRENT reading of one dimension at evaluation
    time `at`, under exactly the SUBMIT eligibility (device verified, TIME_SYNCED,
    device ids, observed and received not after `at`, inside the source's own
    window; ambiguous latest readings and PTO excluded). None means UNKNOWN, never
    `current_counter`, a manual snapshot or the server's receipt time."""
    hits = [r for r in select_submit_readings(observations, vehicle_id=vehicle_id, components=components,
                                              submitted_at=at, max_observation_age=max_observation_age)
            if (r.counter_type, r.component_id) == (counter_type, component_id)]
    return hits[0] if hits else None


def work_order_evidence(detail, journal: Sequence, *, outcomes: Sequence, anchor: PmSubmitMeterAnchor | None,
                        v2_scope_verified: bool, data_scope_verified: bool):
    """The DUE-02A `WorkOrder` from records the CALLER has already proven (see the
    module docstring): the header and results of `detail`, the verified E01
    `journal`, the Work Order's Outcomes and the accepted SUBMIT's anchor (or None).
    Pure: no I/O, nothing repaired; disagreement is passed through for the
    evaluator to turn into UNKNOWN."""
    from app.domain import pm_due_evidence as ev

    wo = detail.work_order
    return ev.WorkOrder(
        pm_work_order_id=wo.pm_work_order_id, asset_type=wo.asset_type.value, asset_id=wo.asset_id,
        pm_plan_id=wo.pm_plan_id, revision_id=wo.revision_id, status=wo.status.value, closed_at=wo.closed_at,
        assignment_model=wo.assignment_model, scope_task_ids=tuple(wo.scope_task_ids),
        outcomes=tuple(ev.ItemOutcome(o.pm_task_id, o.pm_work_order_id, o.revision_id, o.disposition.value,
                                      o.source_pm_work_result_id) for o in outcomes),
        results=tuple(ev.ItemResult(r.pm_work_result_id, r.pm_task_id, r.pm_work_order_id, r.revision_id,
                                    r.completed) for r in detail.results),
        transitions=tuple(ev.CloseTransition(t.pm_work_order_id, t.action.value, t.from_status.value,
                                             t.to_status.value, t.occurred_at, True, t.event_id) for t in journal),
        submit_anchor=anchor, v2_scope_verified=v2_scope_verified, data_scope_verified=data_scope_verified)


async def read_work_order_evidence(repository, pm_work_order_id: str, *, outcomes: Sequence,
                                   v2_scope_verified: bool, data_scope_verified: bool):
    """OFFLINE UNIT PROOF ONLY (trusted Mock fixtures): the DUE-02A `WorkOrder` from
    repository READS ONLY (header, journal, results, the accepted SUBMIT's anchor)
    plus the caller's `outcomes`. It proves NO E01 read integrity, so no application
    module calls it (`PmService` reads through the R3 checks, then
    `work_order_evidence`)."""
    detail = await repository.get_pm_work_order(pm_work_order_id)
    if detail is None:
        return None
    journal = await repository.list_pm_work_order_transitions(pm_work_order_id)
    anchor = None
    if (len(journal) >= 2 and journal[-1].action == PmE01ContractAction.CLOSE
            and journal[-2].action == PmE01ContractAction.SUBMIT):
        anchor = await repository.get_pm_submit_meter_anchor(journal[-2].event_id)
    return work_order_evidence(detail, journal, outcomes=outcomes, anchor=anchor,
                               v2_scope_verified=v2_scope_verified, data_scope_verified=data_scope_verified)


def is_vehicle(asset_type: object) -> bool:
    return asset_type == AssetType.VEHICLE or asset_type == AssetType.VEHICLE.value


__all__ = ["NO_IOT_METER_SOURCE", "IotMeterObservation", "IotMeterSource", "PmSubmitMeterAnchor",
           "SubmitMeterReading", "is_vehicle", "read_work_order_evidence", "select_current_reading",
           "select_submit_readings", "work_order_evidence"]
