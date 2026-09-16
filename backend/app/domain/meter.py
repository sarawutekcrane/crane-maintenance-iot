"""Component-aware meter/counter snapshot (baseline sections 9, 16, 17;
guardrails §10 COUNTERS).

Frozen concept: `vehicle_id -> component_id -> counter_type -> value`.
This module models a historical *snapshot* of one or more such readings,
captured at a specific PM/repair moment — never the live/current counter
(no IoT/device integration exists yet in this repository; a snapshot's
values are entered by the technician/user at the time of work, not read
from a device).

GOVERNANCE NOTE (OPEN_DECISIONS_REGISTER_EN.txt E04 / guardrails §10): a
reading whose value is unknown is recorded as `value=None` and must never
be treated as, defaulted to, or displayed as `0`. `PmService`/
`RepairService` never invent a value for a missing reading.

Component validation: a reading naming a `component_id` must reference a
component that actually exists on that vehicle (see
`app.domain.vehicle.VehicleComponent`) — never a fabricated component
(e.g. a `CRANE_ENGINE` reading on a single-engine vehicle). `ODOMETER` is
a vehicle-level (not per-component) counter, so its reading carries
`component_id=None`. Workshop equipment has no approved component/counter
model yet (OPEN_DECISIONS_REGISTER_EN.txt C03 is TBD-DEFERRED) — equipment
snapshots may simply carry no readings; this module does not fabricate an
equipment counter model.

CORE DEMO FIX — AUTOMATIC MACHINE-STATE SNAPSHOT: `MeterService.
capture_current_state` (see `meter_service.py`) is the one shared,
reusable mechanism that produces a `MeterSnapshot` automatically from
backend-held state rather than from an editable browser field, per every
persisted operational event listed in the Core Demo Fixes prompt
(inspection submission, repair creation/closure, PM work-order open/
result/close, part-instance install/remove/transfer).

REV05 GOVERNANCE CORRECTION: an earlier revision of this module
documented `current_counter` as an unread, future-IoT-phase table and had
`capture_current_state` carry forward the latest value out of
`meter_snapshot` history instead. REV05 makes explicit that
`current_counter` is the authoritative CURRENT counter state (read via
`Repository.list_current_counters`) and `meter_snapshot` is only the
immutable HISTORICAL capture of what that current state was at a given
event — every new automatic snapshot must read `current_counter` as it
stands *at that moment*, never a prior snapshot's own value:

- `MeterReading.observed_at`: preserved from the reading's own source
  timestamp when the schema carries one — `current_counter` does not (its
  declared columns are only `vehicle_id`/`component_id`/`counter_type`/
  `value`), so a `CurrentCounterReading`-sourced value always has
  `observed_at=None`: honestly unknown, never fabricated as "now".
- `MeterSnapshot.is_automatic`: `True` for a backend-derived snapshot
  produced by `capture_current_state`; `False` for one built from a
  caller-supplied reading (e.g. the existing `POST /meter-snapshots`
  manual-entry endpoint, kept for the rare case a technician has an
  actual fresh reading to record).
- `latitude`/`longitude`/`gps_observed_at`: always `None` on `MeterSnapshot`
  itself — the real current/historical location pair lives in the
  separate `current_location`/`LocationSnapshot` mechanism
  (`app.domain.location_snapshot`), linked by `event_id`, never on this
  model. These fields exist only so this shape never needs to change
  again.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.domain.asset import AssetType


class CounterType(str, Enum):
    """Stable counter-type codes (guardrails §10 / baseline §16). Not
    exhaustive — extend as future components/counters require, without
    changing the snapshot shape."""

    ENGINE_HOUR = "ENGINE_HOUR"
    PTO_HOUR = "PTO_HOUR"
    ODOMETER = "ODOMETER"


class MeterReadingInput(BaseModel):
    """One reading as submitted by the client, before validation."""

    component_id: str | None = None
    counter_type: CounterType
    value: float | None = None


class MeterReading(BaseModel):
    """One validated, persisted reading within a `MeterSnapshot`.

    `observed_at` is the timestamp the value was actually observed —
    distinct from the snapshot's own `recorded_at` when the reading was
    carried forward automatically from an earlier snapshot (see module
    docstring). `None` alongside `value=None` means no reading has ever
    been recorded for this dimension (UNKNOWN, never `0`)."""

    component_id: str | None = None
    counter_type: CounterType
    value: float | None = None
    observed_at: datetime | None = None


class CurrentCounterReading(BaseModel):
    """One row of the authoritative CURRENT counter state (`current_counter`
    sheet) — REV05. Distinct from `MeterReading`, which is one entry of an
    immutable historical `MeterSnapshot`: this is live current state, read
    fresh at the moment a new automatic snapshot is captured, never a
    stale copy carried forward from a prior snapshot. `component_id=None`
    only for `ODOMETER` (vehicle-level, mirrors `MeterReading`)."""

    component_id: str | None = None
    counter_type: CounterType
    value: float | None = None


class MeterSnapshot(BaseModel):
    """Historical capture, distinct from any future live `current_counter`
    (guardrails §9). Referenced by PM work results and repairs — never
    mutated once created.

    `is_automatic` / `latitude` / `longitude` / `gps_observed_at` are
    additive Core Demo Fix fields — see module docstring."""

    meter_snapshot_id: str
    asset_type: AssetType
    asset_id: str
    readings: list[MeterReading]
    recorded_at: datetime
    recorded_by: str | None = None
    is_automatic: bool = False
    latitude: float | None = None
    longitude: float | None = None
    gps_observed_at: datetime | None = None
    source_note: str | None = None
