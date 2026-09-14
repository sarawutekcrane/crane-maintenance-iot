"""GPS/event-location snapshot — the location half of the shared automatic
machine-state snapshot mechanism (Core Demo Fixes prompt APPROVED CORE
RULE; Core Demo Fixes Delta REV03 section E).

Complements `app.domain.meter.MeterSnapshot` (counters): guardrails §9's
frozen concept is `current_counter` = current state / `meter_snapshot` =
historical capture for counters, and identically `latest_location` =
current state / `location_snapshot` = historical capture for GPS. This
module is the `location_snapshot` half.

No live GPS/device ingestion exists anywhere in Phases 1-5 (no IoT/device
domain has been built yet — that is explicitly out of scope for this fix
pass). `LocationService.capture_location_snapshot` therefore always
derives `latitude=None, longitude=None, gps_valid=False` today; the single
point where a future phase would wire in a real `latest_location` reader
is `LocationService._read_latest_location`, so a real implementation never
needs to change any of the calling event code. Unknown must never be
displayed/treated as `0,0`.
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
        """The one seam a future phase wires a real `latest_location`
        reader into. No live GPS/device ingestion exists in this branch —
        always returns an honestly-unknown reading, never a fabricated
        `0, 0` coordinate."""
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


__all__ = ["LocationSnapshot", "LocationService"]
