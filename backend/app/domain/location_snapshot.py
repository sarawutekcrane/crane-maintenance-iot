"""GPS/event-location snapshot — the location half of the shared automatic
machine-state snapshot mechanism (Core Demo Fixes prompt APPROVED CORE
RULE; Core Demo Fixes Delta REV03 section E).

Complements `app.domain.meter.MeterSnapshot` (counters): guardrails §9's
frozen concept is `current_counter` = current state / `meter_snapshot` =
historical capture for counters, and identically `latest_location` =
current state / `location_snapshot` = historical capture for GPS. This
module is the `location_snapshot` half.

REV05 GOVERNANCE CORRECTION: an earlier revision of this module treated
`latest_location` as an unread, future-IoT-phase table and always
derived `latitude=None, longitude=None, gps_valid=False`. REV05 makes
explicit that `latest_location` is the authoritative CURRENT location
state, read via `Repository.get_current_location` in
`LocationService._read_latest_location` — every new automatic snapshot
reads it fresh at that moment. When no row exists for the vehicle, the
result is still honestly `latitude=None, longitude=None, gps_valid=False`
— unknown must never be displayed/treated as `0,0`, and a missing current
row is never silently replaced by an old `location_snapshot` value.
`gps_valid` is derived the only way this module has data to derive it:
`True` exactly when both `latitude` and `longitude` are present.

WEB/API PHASE 6 BATCH 4B (Latest Location Projection): `CurrentLocation`
gained two source-tracking columns, `source_device_id`/
`source_component_id`, recording which raw `vehicle_event` most recently
won the projection (see `app.domain.vehicle_event_service.
VehicleEventService._project_latest_location` for the write path — this
module itself still only ever READS `latest_location`, via
`Repository.get_current_location`; it never writes it). A legacy row
written before Batch 4B, or one with no known source, may have both
`None` — never fabricated. This module's own `LocationService` deliberately
does NOT expose `source_device_id`/`source_component_id` into
`LocationSnapshot`/`_LatestLocationReading`: `LocationSnapshot`'s existing
`device_id` field is a distinct, pre-existing, always-`None`-today
concept for a *different* trigger set (operational events, not IoT
events — see that field's own docstring), and it has no
`source_component_id`-shaped field at all. Broadening that unrelated
contract is out of Batch 4B's scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.repositories.base import Repository


class LocationSnapshot(BaseModel):
    """Immutable, backend-derived GPS/location capture for one persisted
    operational event. Never mutated once created."""

    location_snapshot_id: str
    event_type: str
    """The same source-note vocabulary `MeterSnapshot.source_note` uses
    (e.g. "REPAIR_OPEN", "PM_WORK_ORDER_CLOSE") — one snapshot per event."""
    event_id: str
    """The `MeterSnapshot.meter_snapshot_id` of the counter snapshot
    captured for the same event, linking the two immutable records."""
    vehicle_id: str | None = None
    """`None` for EQUIPMENT — no location concept exists for workshop
    equipment (mirrors C03's counter-model deferral)."""
    device_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    accuracy_m: float | None = None
    gps_time: datetime | None = None
    """The GPS fix's own observation time — preserved separately from
    `received_at`/`snapshot_at` so a stale reading is never presented as
    current (guardrails §8/§9)."""
    received_at: datetime | None = None
    snapshot_at: datetime
    gps_valid: bool = False
    source: str | None = None
    note: str | None = None


class CurrentLocation(BaseModel):
    """One row of the authoritative CURRENT location state
    (`latest_location` sheet) — REV05, extended by Batch 4B. Distinct
    from `LocationSnapshot`, which is an immutable historical capture:
    this is live current state, read fresh at the moment a new automatic
    snapshot is captured (and, since Batch 4B, written by
    `VehicleEventService._project_latest_location`). Only the columns the
    target `latest_location` schema declares — never a fabricated
    `altitude_m`/`accuracy_m`, which no version of that sheet carries.

    `source_device_id`/`source_component_id` (Batch 4B) record which
    `vehicle_event` most recently won the projection — both `None` for a
    legacy row written before Batch 4B, or when the source is otherwise
    unknown; never fabricated/inferred."""

    vehicle_id: str
    latitude: float | None = None
    longitude: float | None = None
    gps_time: datetime | None = None
    received_at: datetime | None = None
    source_device_id: str | None = None
    source_component_id: str | None = None


@dataclass(frozen=True)
class _LatestLocationReading:
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    accuracy_m: float | None
    gps_time: datetime | None
    received_at: datetime | None
    gps_valid: bool
    source: str | None
    device_id: str | None


class LocationService:
    def __init__(self, repository: "Repository") -> None:
        self._repository = repository

    async def _read_latest_location(self, vehicle_id: str) -> _LatestLocationReading:
        """REV05: read the authoritative CURRENT location
        (`Repository.get_current_location`) fresh, at the moment of this
        call — never a value carried forward from an old
        `location_snapshot`. `altitude_m`/`accuracy_m`/`source`/
        `device_id` stay `None`: the live `latest_location` sheet does not
        declare those columns, so they are honestly unknown, not
        fabricated. `gps_valid` is `True` exactly when both coordinates
        are present; a missing row (no current location known) is an
        honestly-unknown reading, never a fabricated `0, 0` coordinate."""
        current = await self._repository.get_current_location(vehicle_id)
        if current is None:
            return _LatestLocationReading(
                latitude=None,
                longitude=None,
                altitude_m=None,
                accuracy_m=None,
                gps_time=None,
                received_at=None,
                gps_valid=False,
                source=None,
                device_id=None,
            )
        return _LatestLocationReading(
            latitude=current.latitude,
            longitude=current.longitude,
            altitude_m=None,
            accuracy_m=None,
            gps_time=current.gps_time,
            received_at=current.received_at,
            gps_valid=current.latitude is not None and current.longitude is not None,
            source=None,
            device_id=None,
        )

    async def capture_location_snapshot(
        self,
        event_type: str,
        event_id: str,
        vehicle_id: str | None,
    ) -> LocationSnapshot | None:
        """Capture one immutable location snapshot for a persisted
        operational event, backend-derived from `latest_location`. Returns
        `None` for a non-VEHICLE asset (no fabricated equipment location)."""
        if vehicle_id is None:
            return None
        reading = await self._read_latest_location(vehicle_id)
        return await self._repository.create_location_snapshot(
            event_type=event_type,
            event_id=event_id,
            vehicle_id=vehicle_id,
            device_id=reading.device_id,
            latitude=reading.latitude,
            longitude=reading.longitude,
            altitude_m=reading.altitude_m,
            accuracy_m=reading.accuracy_m,
            gps_time=reading.gps_time,
            received_at=reading.received_at,
            gps_valid=reading.gps_valid,
            source=reading.source,
        )

    async def get_snapshot(self, location_snapshot_id: str) -> LocationSnapshot | None:
        return await self._repository.get_location_snapshot(location_snapshot_id)

    async def list_for_event(self, event_id: str) -> list[LocationSnapshot]:
        return await self._repository.list_location_snapshots_for_event(event_id)

    async def get_current_location(self, vehicle_id: str) -> CurrentLocation | None:
        """Web/API Phase 6 Batch 6D: read-only accessor for
        `GET /vehicles/{vehicle_id}/latest-location`. Verifies the vehicle
        exists (raising `VEHICLE_NOT_FOUND` if not — same distinction the
        rest of Phase 6 uses, e.g. `DailySummaryService.
        _require_vehicle_exists`), then returns
        `Repository.get_current_location(vehicle_id)` exactly as given: a
        known vehicle with no current-location row honestly returns
        `None` (never a fabricated `0, 0`), distinct from the 404 an
        unknown vehicle raises. Never falls back to `location_snapshot`
        history, never derives/repairs/overwrites current state, and
        performs no write — this method and
        `Repository.get_current_location` are both pure reads."""
        from app.errors import ApiError  # local import: avoids a circular
        # import, since `app.repositories.base` (imported by `app.errors`
        # transitively via `RepositoryFeatureNotImplementedError`) itself
        # imports `CurrentLocation`/`LocationSnapshot` from this module.
        from fastapi import status

        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            raise ApiError(
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle '{vehicle_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return await self._repository.get_current_location(vehicle_id)


__all__ = ["LocationSnapshot", "LocationService"]
