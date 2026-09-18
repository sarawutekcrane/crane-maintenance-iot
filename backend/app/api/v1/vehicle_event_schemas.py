"""Vehicle Event request/response schemas (Web/API Phase 6 Batch 4A —
Raw Vehicle Event Foundation + Idempotent Device Event Ingestion). See
`app.domain.vehicle_event` for the full frozen-contract rule set.

The client can never supply `event_id` or `received_at` — both are
backend-owned (`model_config = ConfigDict(extra="forbid")` enforces this
at the request boundary, the same correction Batch 2A/3A's create
requests already apply). `event_type` accepts only the four Batch 4A
device-emitted values (`DEVICE_ONLINE`/`DEVICE_OFFLINE` are reserved,
backend-generated-only values a later batch introduces — never acceptable
here).

Cross-field rules (event_time timezone-awareness, event_time-required-by-
time_quality, gps_valid/latitude/longitude combinations — frozen contract
sections 8/11) are deliberately NOT implemented as pydantic
field_validator/model_validator here: a validator that raises a plain
`ValueError` makes pydantic v2 embed the raw exception object in
`ValidationError.errors()`'s `ctx.error`, which `app.errors.
handle_validation_error` (frozen since Phase 1) then hands directly to
`json.dumps` — a pre-existing latent gap in that shared handler that no
earlier schema ever triggered, since none used a custom raising
validator. Fixing that shared, frozen file is out of scope for this
batch, so these specific cross-field checks are enforced in
`app.domain.vehicle_event_service.VehicleEventService.ingest_device_event`
instead, exactly like every other stateful/cross-field rule elsewhere in
this codebase (e.g. Batch 3B's version/effective_from checks) — each
raising its own specific `ApiError` code. Only plain, single-field
constraints native to pydantic itself (`ge`/`le`/`max_length`, which never
hit this gap) stay here."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.vehicle_event import TimeQuality

DeviceEmittedEventType = Literal["ENGINE_START", "ENGINE_STOP", "PTO_ON", "PTO_OFF"]


class CreateVehicleEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    device_id: str
    component_id: str
    event_type: DeviceEmittedEventType
    event_time: datetime | None = None
    fuel_level_value: float | None = None
    fuel_level_unit: str | None = Field(default=None, max_length=50)
    # Real-world geographic range (an objective physical constraint, not
    # an invented business rule) — applies to any non-null coordinate
    # regardless of gps_valid, since a corrupt reading is invalid raw
    # evidence too (frozen contract section 11).
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    gps_valid: bool | None = None
    note_th: str | None = Field(default=None, max_length=500)
    device_event_id: str = Field(max_length=200)
    sequence: int = Field(ge=0)
    created_offline: bool
    time_quality: TimeQuality


class VehicleEventResponse(BaseModel):
    event_id: str
    vehicle_id: str
    device_id: str
    component_id: str
    event_type: str
    event_time: datetime | None
    fuel_level_value: float | None
    fuel_level_unit: str | None
    latitude: float | None
    longitude: float | None
    gps_valid: bool | None
    received_at: datetime
    note_th: str | None
    device_event_id: str
    sequence: int
    created_offline: bool
    time_quality: str
