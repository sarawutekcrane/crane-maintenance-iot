"""Meter/counter snapshot validation and creation.

Shared by `PmService` and `RepairService` (baseline section 5 "PM Meter
Snapshot" / section 10 "Repair supports... meter snapshot") so both
domains create snapshots through the exact same component/asset
validation, never inventing their own copy of this rule.

Validation enforced here (OPEN_DECISIONS_REGISTER_EN.txt / Phase 4
requirements):
- A component-scoped reading (`component_id` set) must reference a
  component that actually exists on that vehicle
  (`app.domain.vehicle.VehicleComponent`) — never a fabricated
  `CRANE_ENGINE` reading for a single-engine vehicle.
- `ODOMETER` is vehicle-level, not per-component, so it is the only
  counter type allowed with `component_id=None` on a vehicle.
- Workshop equipment has no approved counter/component model yet
  (OPEN_DECISIONS_REGISTER_EN.txt C03 is TBD-DEFERRED): equipment
  snapshots may only carry readings with `component_id=None` (no
  equipment component list exists to validate against).
- A reading's `value` may be `None` (UNKNOWN) and is never coerced to
  `0` anywhere in this module (E04).
"""
from __future__ import annotations

from fastapi import status

from app.domain.asset import AssetType
from app.domain.meter import CounterType, MeterReading, MeterReadingInput, MeterSnapshot
from app.errors import ApiError
from app.repositories.base import Repository


class MeterService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _validate_readings(
        self, asset_type: AssetType, asset_id: str, readings: list[MeterReadingInput]
    ) -> list[MeterReading]:
        component_ids: set[str] = set()
        if asset_type == AssetType.VEHICLE:
            components = await self._repository.list_vehicle_components(asset_id)
            component_ids = {c.component_id for c in components}

        validated: list[MeterReading] = []
        for reading in readings:
            if reading.component_id is not None:
                if asset_type != AssetType.VEHICLE:
                    raise ApiError(
                        code="VALIDATION_ERROR",
                        message=(
                            "Component-scoped meter readings are only supported for "
                            "vehicles; workshop equipment has no approved component/"
                            "counter model yet (OPEN_DECISIONS_REGISTER_EN.txt C03)"
                        ),
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    )
                if reading.component_id not in component_ids:
                    raise ApiError(
                        code="METER_COMPONENT_NOT_FOUND",
                        message=(
                            f"Component '{reading.component_id}' was not found on "
                            f"vehicle '{asset_id}' — a reading must never be recorded "
                            "against a component the vehicle does not physically have"
                        ),
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        details={"component_id": reading.component_id, "vehicle_id": asset_id},
                    )
            elif reading.counter_type != CounterType.ODOMETER:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message=(
                        f"A '{reading.counter_type.value}' reading must specify the "
                        "component it belongs to (only ODOMETER is vehicle-level)"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            validated.append(
                MeterReading(
                    component_id=reading.component_id,
                    counter_type=reading.counter_type,
                    value=reading.value,
                )
            )
        return validated

    async def create_snapshot(
        self,
        asset_type: AssetType,
        asset_id: str,
        readings: list[MeterReadingInput],
        recorded_by: str | None,
    ) -> MeterSnapshot:
        validated = await self._validate_readings(asset_type, asset_id, readings)
        return await self._repository.create_meter_snapshot(
            asset_type=asset_type, asset_id=asset_id, readings=validated, recorded_by=recorded_by
        )

    async def get_snapshot(self, meter_snapshot_id: str) -> MeterSnapshot:
        snapshot = await self._repository.get_meter_snapshot(meter_snapshot_id)
        if snapshot is None:
            raise ApiError(
                code="METER_SNAPSHOT_NOT_FOUND",
                message=f"Meter snapshot '{meter_snapshot_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return snapshot

    async def require_snapshot_exists(self, meter_snapshot_id: str | None) -> None:
        """Validate a referenced snapshot id exists; no-op for `None`."""
        if meter_snapshot_id is None:
            return
        await self.get_snapshot(meter_snapshot_id)
