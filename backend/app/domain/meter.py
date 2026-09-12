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
    """One validated, persisted reading within a `MeterSnapshot`."""

    component_id: str | None = None
    counter_type: CounterType
    value: float | None = None


class MeterSnapshot(BaseModel):
    """Historical capture, distinct from any future live `current_counter`
    (guardrails §9). Referenced by PM work results and repairs — never
    mutated once created."""

    meter_snapshot_id: str
    asset_type: AssetType
    asset_id: str
    readings: list[MeterReading]
    recorded_at: datetime
    recorded_by: str | None = None
