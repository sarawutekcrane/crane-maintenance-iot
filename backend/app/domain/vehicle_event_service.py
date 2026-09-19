"""Vehicle Event service (Web/API Phase 6 Batch 4A — Raw Vehicle Event
Foundation + Idempotent Device Event Ingestion; Batch 4B — Latest
Location Projection). See `app.domain.vehicle_event` for the full
Batch 4A frozen-contract rule set this module implements.

BATCH 4B (`_project_latest_location`): raw `vehicle_event` stays
append-only, authoritative history — this module never mutates a stored
event to reflect a projection outcome. `latest_location` is a SEPARATE
current-state table with at most one row per vehicle; an eligible event
(gps_valid is exactly True, latitude/longitude both present, time_quality
TIME_SYNCED/TIME_ESTIMATED, event_time not null) only ever ADVANCES that
row — a candidate whose event_time is not strictly newer than the row's
current `gps_time` is silently skipped, never an error, never a rewrite.
`received_at` is never compared as if it were occurrence chronology; only
`event_time` decides ordering here, matching `order_for_history`'s same
principle. No preferred device/component is hardcoded — whichever
eligible event has the newest `event_time` wins, across any number of
independent devices on one vehicle."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import status

from app.domain.vehicle_event import TimeQuality, VehicleEvent, VehicleEventType
from app.errors import ApiError
from app.repositories.base import Repository


def _is_trusted_time(event: VehicleEvent) -> bool:
    return (
        event.time_quality in (TimeQuality.TIME_SYNCED, TimeQuality.TIME_ESTIMATED)
        and event.event_time is not None
    )


def order_for_history(events: list[VehicleEvent]) -> list[VehicleEvent]:
    """Frozen contract section 16: Google Sheets row/append order is
    never business chronology.

    Trusted-time events (`time_quality` TIME_SYNCED/TIME_ESTIMATED with a
    non-null `event_time`) are sorted by `event_time`, newest first, and
    always precede the untrusted bucket.

    Untrusted-time events (`time_quality` TIME_NOT_SYNCED, or any record
    whose `event_time` is null) are NOT chronologically ordered —
    `event_time` is absent/non-authoritative, and `received_at` is never
    substituted as if it were occurrence time. They only get a
    deterministic tie-break ordering (`device_id`, `sequence`,
    `received_at`, `event_id`) so the API's output is stable across
    calls, not a claim of actual chronology. `sequence` is grouped by
    `device_id` first, so it is never compared across two different
    devices as if they shared one global sequence."""
    trusted = [e for e in events if _is_trusted_time(e)]
    untrusted = [e for e in events if not _is_trusted_time(e)]
    trusted.sort(key=lambda e: e.event_time, reverse=True)  # type: ignore[arg-type,return-value]
    untrusted.sort(key=lambda e: (e.device_id, e.sequence, e.received_at, e.event_id))
    return trusted + untrusted


class VehicleEventService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _require_vehicle_exists(self, vehicle_id: str) -> None:
        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            raise ApiError(
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle '{vehicle_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    async def _require_component_belongs_to_vehicle(
        self, vehicle_id: str, component_id: str
    ) -> None:
        """Reuses the exact component-ownership rule
        `app.domain.meter_service.MeterService._validate_readings`
        already established: a component-scoped reference must name a
        component that actually exists on that vehicle — never a
        fabricated or cross-vehicle component_id, and never inferred/
        substituted from event_type."""
        components = await self._repository.list_vehicle_components(vehicle_id)
        if component_id not in {c.component_id for c in components}:
            raise ApiError(
                code="VEHICLE_EVENT_COMPONENT_NOT_FOUND",
                message=(
                    f"Component '{component_id}' was not found on vehicle '{vehicle_id}' — "
                    "a vehicle event must never be recorded against a component the "
                    "vehicle does not physically have"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"component_id": component_id, "vehicle_id": vehicle_id},
            )

    async def _project_latest_location(self, event: VehicleEvent) -> None:
        """Web/API Phase 6 Batch 4B. Advances `latest_location` for
        `event.vehicle_id` from `event` IF AND ONLY IF `event` is an
        eligible trusted GPS event (frozen contract section B) AND its
        `event_time` is strictly newer than the vehicle's current
        `gps_time` — or no current row exists yet, or the current row's
        `gps_time` is null (a legacy/never-projected row, which any
        eligible trusted event may then establish). An event that is not
        strictly newer is silently skipped: this is normal, expected
        out-of-order/duplicate handling, never an error.

        Called for BOTH a newly-created event (after it is durably
        persisted) and a duplicate-retry's stored existing event (frozen
        contract section F) — the latter lets a prior request that
        appended `vehicle_event` but failed before this projection ran
        heal on retry, without ever re-validating the replay payload or
        creating a second raw row (this method only ever reads the
        already-stored `event`, never the replay's possibly-different
        fields)."""
        if not (
            event.gps_valid is True
            and event.latitude is not None
            and event.longitude is not None
            and event.time_quality in (TimeQuality.TIME_SYNCED, TimeQuality.TIME_ESTIMATED)
            and event.event_time is not None
        ):
            return

        current = await self._repository.get_current_location(event.vehicle_id)
        if (
            current is not None
            and current.gps_time is not None
            and event.event_time <= current.gps_time
        ):
            return

        await self._repository.upsert_current_location(
            vehicle_id=event.vehicle_id,
            latitude=event.latitude,
            longitude=event.longitude,
            gps_time=event.event_time,
            received_at=event.received_at,
            source_device_id=event.device_id,
            source_component_id=event.component_id,
        )

    async def ingest_device_event(
        self,
        vehicle_id: str,
        device_id: str,
        component_id: str,
        event_type: str,
        event_time: datetime | None,
        fuel_level_value: float | None,
        fuel_level_unit: str | None,
        latitude: float | None,
        longitude: float | None,
        gps_valid: bool | None,
        note_th: str | None,
        device_event_id: str,
        sequence: int,
        created_offline: bool,
        time_quality: TimeQuality,
    ) -> VehicleEvent:
        """Frozen contract sections 4/9/15: idempotency identity is
        exactly `(device_id, device_event_id)` — checked FIRST, before
        any other validation, so a replay of an already-accepted pair
        always returns the exact stored row unchanged and never re-runs
        vehicle/component/GPS validation against a possibly-different
        replay payload. Only a genuinely new `(device_id,
        device_event_id)` pair reaches vehicle-existence/component-
        ownership validation and, ultimately,
        `Repository.create_vehicle_event` (always exactly one new
        `EVT-` row — never a mutation of an existing one)."""
        if not device_id.strip():
            raise ApiError(
                code="VEHICLE_EVENT_DEVICE_ID_REQUIRED",
                message="device_id must not be empty or whitespace-only.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if not device_event_id.strip():
            raise ApiError(
                code="VEHICLE_EVENT_DEVICE_EVENT_ID_REQUIRED",
                message="device_event_id must not be empty or whitespace-only.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        existing = await self._repository.find_vehicle_event_by_device_event(
            device_id=device_id, device_event_id=device_event_id
        )
        if existing is not None:
            # Batch 4B section F: heal a possibly-missing projection from
            # a prior partial failure, using the STORED event only — the
            # replay payload (possibly different sequence/event_type/etc.,
            # per Batch 4A's own idempotency contract) is never consulted.
            await self._project_latest_location(existing)
            return existing

        if event_time is not None and event_time.tzinfo is None:
            raise ApiError(
                code="VEHICLE_EVENT_TIME_NOT_TIMEZONE_AWARE",
                message="event_time must be timezone-aware (include a UTC offset) when supplied.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if (
            time_quality in (TimeQuality.TIME_SYNCED, TimeQuality.TIME_ESTIMATED)
            and event_time is None
        ):
            raise ApiError(
                code="VEHICLE_EVENT_TIME_REQUIRED_FOR_TIME_QUALITY",
                message=f"event_time is required when time_quality={time_quality.value}.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        # Frozen contract section 11: gps_valid is never derived here from
        # coordinate presence — only these explicit combination rules.
        if gps_valid is True and (latitude is None or longitude is None):
            raise ApiError(
                code="VEHICLE_EVENT_GPS_COORDINATES_REQUIRED",
                message="latitude and longitude are required when gps_valid is true.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if gps_valid is None and (latitude is not None or longitude is not None):
            raise ApiError(
                code="VEHICLE_EVENT_GPS_COORDINATES_MUST_BE_NULL",
                message="latitude and longitude must be null when gps_valid is null.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        await self._require_vehicle_exists(vehicle_id)
        await self._require_component_belongs_to_vehicle(vehicle_id, component_id)

        # Frozen contract section 8: store/return event_time in the
        # project's UTC convention. `.astimezone(UTC)` preserves the
        # exact instant the device supplied, only normalizing its
        # displayed offset — never manufactured for TIME_NOT_SYNCED,
        # where event_time may legitimately still be None here.
        normalized_event_time = event_time.astimezone(timezone.utc) if event_time else None

        created = await self._repository.create_vehicle_event(
            vehicle_id=vehicle_id,
            device_id=device_id,
            component_id=component_id,
            event_type=VehicleEventType(event_type),
            event_time=normalized_event_time,
            fuel_level_value=fuel_level_value,
            fuel_level_unit=fuel_level_unit,
            latitude=latitude,
            longitude=longitude,
            gps_valid=gps_valid,
            note_th=note_th,
            device_event_id=device_event_id,
            sequence=sequence,
            created_offline=created_offline,
            time_quality=time_quality,
        )
        # Batch 4B section K: the raw event is durably persisted FIRST —
        # projection is attempted only after, so raw evidence is
        # preserved even if this step fails (never reversed).
        await self._project_latest_location(created)
        return created

    async def get_event(self, event_id: str) -> VehicleEvent:
        event = await self._repository.get_vehicle_event(event_id)
        if event is None:
            raise ApiError(
                code="VEHICLE_EVENT_NOT_FOUND",
                message=f"Vehicle event '{event_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return event

    async def list_for_vehicle(self, vehicle_id: str) -> list[VehicleEvent]:
        await self._require_vehicle_exists(vehicle_id)
        events = await self._repository.list_vehicle_events_for_vehicle(vehicle_id)
        return order_for_history(events)


__all__ = ["VehicleEventService", "order_for_history"]
