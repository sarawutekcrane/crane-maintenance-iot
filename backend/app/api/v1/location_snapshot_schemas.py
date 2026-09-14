from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LocationSnapshotResponse(BaseModel):
    location_snapshot_id: str
    event_type: str
    event_id: str
    vehicle_id: str | None
    device_id: str | None
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    accuracy_m: float | None
    gps_time: datetime | None
    received_at: datetime | None
    snapshot_at: datetime
    gps_valid: bool
    source: str | None
    note: str | None = None
