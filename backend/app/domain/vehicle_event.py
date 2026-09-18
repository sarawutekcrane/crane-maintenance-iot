"""Vehicle Event (Web/API Phase 6 Batch 4A — Raw Vehicle Event Foundation +
Idempotent Device Event Ingestion; see the Batch 4 pre-implementation audit
and the Batch 4A frozen-contract task for the full rule set this module
implements).

LIVE GOOGLE SHEETS SCHEMA — the existing live `vehicle_event` tab has 13
verified headers:

    event_id, vehicle_id, device_id, component_id, event_type, event_time,
    fuel_level_value, fuel_level_unit, latitude, longitude, gps_valid,
    received_at, note_th

The Batch 4A frozen contract appends exactly 4 more columns at the end
(never reordering/renaming the existing 13):

    device_event_id, sequence, created_offline, time_quality

`VehicleEvent` below carries exactly those 17 fields, one per header, and
no other. The live spreadsheet itself is NOT migrated by this batch — that
4-column migration is separately authorized after independent review; see
`app.repositories.google_sheets.schemas.VEHICLE_EVENT_SHEET`.

RAW HISTORY SEMANTICS (frozen contract section 15): `vehicle_event` is
append-only raw history/evidence. Once a unique event is accepted, it is
never mutated, rewritten, or deleted — not because a later event arrives,
not because its `sequence`/`event_time` turns out to be older than an
already-stored row (delayed/offline/out-of-order upload is explicitly
supported), and not to make a state transition look cleaner. No
START/STOP or ONLINE/OFFLINE pairing/duration aggregation exists anywhere
in this module — that is explicitly deferred to a later batch.

EVENT IDENTITY (frozen contract section 4): `event_id` is a backend/
repository-generated opaque stable ID (`EVT-` prefix, the same
max-numeric-suffix convention every other domain in this codebase uses —
see `app.domain.model_document`'s `MDOC-` precedent) — never accepted from
a client request, never derived from a Google Sheets row position.
`device_event_id` is a separate, ESP32/device-generated identifier,
required for every Batch 4A device-emitted event, preserved as exact text
(never numericised, e.g. "000001" must round-trip as "000001", not `1`).

IDEMPOTENCY (frozen contract section 4): the dedup identity is exactly
`(device_id, device_event_id)` — never `event_time`/`event_type`/
`sequence`/`component_id`/`latitude`/`longitude`. A replay of an already-
stored pair returns the existing stored `VehicleEvent` unchanged; it never
creates a second `event_id` or appends a second row (see
`app.domain.vehicle_event_service.VehicleEventService.ingest_device_event`).

SEQUENCE (frozen contract section 5): a required, non-negative, device-
owned integer. Its namespace is per-device only — comparing `sequence`
values across two different `device_id`s is meaningless and never done
anywhere in this module (see the history-read-order helper in
`vehicle_event_service.py`). A lower `sequence` than a previously received
one is never grounds for rejection (delayed/offline upload is supported).

CREATED_OFFLINE (frozen contract section 6): a required boolean, stored
exactly as the device supplies it. Never inferred from `event_time`,
`received_at`, `sequence`, or network delay — it is pure device-owned
provenance metadata.

TIME_QUALITY (frozen contract section 7): one of exactly `TIME_SYNCED`,
`TIME_ESTIMATED`, `TIME_NOT_SYNCED` (see `TimeQuality` below — this
vocabulary is authoritative per `docs/claude-prompts/esp32/
04_PHASE4_NETWORK_TELEMETRY_OFFLINE_QUEUE_EN.txt` section I). Required for
every Batch 4A device-emitted event; never derived by the backend from any
other field.

EVENT_TIME / RECEIVED_AT (frozen contract section 8, and
`docs/architecture/API_CONVENTIONS.md`'s frozen Date/time convention):
`event_time` is when the event occurred, device-supplied, timezone-aware
when present, and required exactly when `time_quality` is `TIME_SYNCED` or
`TIME_ESTIMATED` (nullable, non-authoritative, only for `TIME_NOT_SYNCED`).
`received_at` is backend-generated only, at ingestion time, in UTC — never
accepted from a client request, never substituted for `event_time`.

DEVICE / COMPONENT (frozen contract section 9): `device_id` is a required,
opaque, unvalidated passthrough string — no Device Master exists yet
(that is Phase 8 scope, explicitly excluded here), so it is never checked
against anything. `component_id` is required and MUST reference a
component that actually exists on `vehicle_id` (reusing the exact
component-ownership validation `app.domain.meter_service.MeterService`
already established for `MeterReading.component_id` — never inferred from
`event_type`, never auto-paired/substituted).

EVENT TYPE (frozen contract section 10): the frozen six-value Phase 6 Work
History vocabulary. A strict `Enum` is used here — explicitly authorized
for this batch, a deliberate departure from this codebase's usual opaque-
string NO-GUESSING RULE for other domains, because this exact six-value
set has been frozen by the task itself. Batch 4A's create endpoint only
accepts the four device-emitted values (see
`app.api.v1.vehicle_event_schemas.CreateVehicleEventRequest.event_type`,
a `Literal` of just those four) — `DEVICE_ONLINE`/`DEVICE_OFFLINE` are
reserved for a later batch's backend-generated detection logic and can
never be created through this batch's endpoint.

GPS (frozen contract section 11): `latitude`/`longitude`/`gps_valid` are
raw, per-event, source/device-supplied fields — optional, since not every
device on a vehicle carries GPS. `gps_valid` is never derived merely from
coordinate presence; when `true`, both coordinates are required and must
be within their real geographic range; when `false`, coordinates may be
present as raw evidence or null (their presence never implies validity);
when `null`, both coordinates must also be null. This is a per-event raw
capture only — Batch 4A never writes `latest_location` (a completely
separate, already-existing current-state mechanism; see
`app.domain.location_snapshot`) and never compares GPS sources.

FUEL (frozen contract section 12): `fuel_level_value`/`fuel_level_unit`
remain optional raw fields — no new business rule, threshold, alert, or
unit normalization is introduced by this batch.

NOTE (frozen contract section 13): `note_th` is optional free text only —
no structured metadata (`device_event_id`/`sequence`/`created_offline`/
`time_quality`/GPS) is ever encoded into it."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class VehicleEventType(str, Enum):
    """The frozen six-value Phase 6 Work History event vocabulary. Batch
    4A's device-emitted create endpoint only accepts the first four
    (see `app.api.v1.vehicle_event_schemas.CreateVehicleEventRequest`);
    `DEVICE_ONLINE`/`DEVICE_OFFLINE` exist here only so a later batch's
    backend-generated rows can be represented/read by this same model —
    generating or detecting them is explicitly out of scope for Batch 4A."""

    ENGINE_START = "ENGINE_START"
    ENGINE_STOP = "ENGINE_STOP"
    PTO_ON = "PTO_ON"
    PTO_OFF = "PTO_OFF"
    DEVICE_ONLINE = "DEVICE_ONLINE"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"


class TimeQuality(str, Enum):
    """Authoritative vocabulary per ESP32 Phase 4 spec section I (Time
    Synchronization) — reused verbatim, never invented here."""

    TIME_SYNCED = "TIME_SYNCED"
    TIME_ESTIMATED = "TIME_ESTIMATED"
    TIME_NOT_SYNCED = "TIME_NOT_SYNCED"


class VehicleEvent(BaseModel):
    """One row of `vehicle_event` — mirrors the verified 13 live headers
    plus the 4 Batch 4A frozen-contract columns, 1:1, and no other field."""

    event_id: str
    vehicle_id: str
    device_id: str
    component_id: str
    event_type: VehicleEventType
    event_time: datetime | None = None
    fuel_level_value: float | None = None
    fuel_level_unit: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    gps_valid: bool | None = None
    received_at: datetime
    note_th: str | None = None
    device_event_id: str
    sequence: int
    created_offline: bool
    time_quality: TimeQuality


__all__ = ["VehicleEvent", "VehicleEventType", "TimeQuality"]
