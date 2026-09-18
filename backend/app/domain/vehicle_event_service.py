"""Vehicle Event service (Web/API Phase 6 Batch 4A — Raw Vehicle Event
Foundation + Idempotent Device Event Ingestion). See
`app.domain.vehicle_event` for the full frozen-contract rule set this
module implements."""
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

        return await self._repository.create_vehicle_event(
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
