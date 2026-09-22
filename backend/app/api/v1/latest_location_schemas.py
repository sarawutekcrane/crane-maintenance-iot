"""Response schema for `GET /vehicles/{vehicle_id}/latest-location` (Web/API
Phase 6 Batch 6D). Deliberately declares EXACTLY the 7 verified live
`latest_location` D12 columns — never `gps_valid`/`altitude`/`accuracy`/
`event_id`/`updated_at`, none of which the live sheet carries (see
`app.domain.location_snapshot.CurrentLocation`, which this schema mirrors
field-for-field)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LatestLocationResponse(BaseModel):
    vehicle_id: str
    latitude: float | None
    longitude: float | None
    gps_time: datetime | None
    received_at: datetime | None
    source_device_id: str | None
    source_component_id: str | None
