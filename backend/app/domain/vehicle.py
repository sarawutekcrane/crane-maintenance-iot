"""Physical vehicle identity, components, and status history.

Frozen shape starting this phase (see docs/architecture/API_CONVENTIONS.md
and docs/phase-results/web-phase-02-result.md):

- `vehicle_id` is the stable identity; `machine_no` is a free-text
  operational number that may change without affecting `vehicle_id`
  (baseline section 4).
- `VehicleStatusHistoryEntry` records are append-only: a status change
  creates a new entry, it never rewrites a previous one.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.domain.common import OperationalStatus
from app.domain.vehicle_model import ComponentRole


class Vehicle(BaseModel):
    vehicle_id: str
    machine_no: str
    model_id: str
    serial_number: str | None = None
    operational_status: OperationalStatus
    created_at: datetime
    updated_at: datetime


class VehicleComponent(BaseModel):
    """Read model: which component roles exist on a given vehicle.

    Counters (engine hour, PTO hour, odometer) attached to each component
    are introduced by the IoT/counter phase; Phase 2 only establishes
    which components a vehicle has.
    """

    component_id: str
    vehicle_id: str
    component_role: ComponentRole
    label: str


class VehicleStatusHistoryEntry(BaseModel):
    history_id: str
    vehicle_id: str
    status: OperationalStatus
    changed_at: datetime
    changed_by: str | None = None
    note: str | None = None
