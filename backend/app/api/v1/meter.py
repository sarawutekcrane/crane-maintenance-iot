"""Meter/counter snapshot routes (Phase 4). Shared by the PM and Repair
workflows — a snapshot is created once and then referenced by
`meter_snapshot_id` when submitting a PM task result or creating a repair.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.meter_schemas import (
    CreateMeterSnapshotRequest,
    CurrentMachineStateResponse,
    MeterReadingResponse,
    MeterSnapshotResponse,
    VehicleMachineStateResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_meter_service
from app.domain.asset import AssetType
from app.domain.authz import require_trusted_reader
from app.domain.meter import MeterReading, MeterReadingInput, MeterSnapshot
from app.domain.meter_service import MeterService

router = APIRouter(tags=["meter"])


def _reading_response(reading: MeterReading) -> MeterReadingResponse:
    return MeterReadingResponse(
        component_id=reading.component_id,
        counter_type=reading.counter_type,
        value=reading.value,
        observed_at=reading.observed_at,
    )


def _snapshot_response(snapshot: MeterSnapshot) -> MeterSnapshotResponse:
    return MeterSnapshotResponse(
        meter_snapshot_id=snapshot.meter_snapshot_id,
        asset_type=snapshot.asset_type,
        asset_id=snapshot.asset_id,
        readings=[_reading_response(r) for r in snapshot.readings],
        recorded_at=snapshot.recorded_at,
        recorded_by=snapshot.recorded_by,
        is_automatic=snapshot.is_automatic,
        latitude=snapshot.latitude,
        longitude=snapshot.longitude,
        gps_observed_at=snapshot.gps_observed_at,
        source_note=snapshot.source_note,
    )


@router.post("/meter-snapshots", response_model=MeterSnapshotResponse)
async def create_meter_snapshot(
    body: CreateMeterSnapshotRequest,
    service: MeterService = Depends(get_meter_service),
    context: RequestContext = Depends(get_current_context),
) -> MeterSnapshotResponse:
    readings = [
        MeterReadingInput(component_id=r.component_id, counter_type=r.counter_type, value=r.value)
        for r in body.readings
    ]
    snapshot = await service.create_snapshot(
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        readings=readings,
        recorded_by=context.user_id,
    )
    return _snapshot_response(snapshot)


@router.get("/meter-snapshots/{meter_snapshot_id}", response_model=MeterSnapshotResponse)
async def get_meter_snapshot(
    meter_snapshot_id: str, service: MeterService = Depends(get_meter_service)
) -> MeterSnapshotResponse:
    snapshot = await service.get_snapshot(meter_snapshot_id)
    return _snapshot_response(snapshot)


@router.get("/machine-state/current", response_model=CurrentMachineStateResponse)
async def get_current_machine_state(
    asset_type: AssetType,
    asset_id: str = Query(min_length=1),
    service: MeterService = Depends(get_meter_service),
) -> CurrentMachineStateResponse:
    """Read-only preview for a normal user-facing form (Core Demo Fixes
    prompt: "show these values read-only... remove manual counter/GPS
    entry as the normal path"). Never persists a snapshot."""
    readings = await service.preview_current_state(asset_type, asset_id)
    return CurrentMachineStateResponse(
        asset_type=asset_type,
        asset_id=asset_id,
        readings=[_reading_response(r) for r in readings],
    )


@router.get("/vehicles/{vehicle_id}/machine-state", response_model=VehicleMachineStateResponse)
async def get_vehicle_machine_state(
    vehicle_id: str,
    context: RequestContext = Depends(get_current_context),
    service: MeterService = Depends(get_meter_service),
) -> VehicleMachineStateResponse:
    """R8 (ED-10): the vehicle page's meter read. A trusted actor holding
    `can_view` is checked BEFORE any repository read (the same 403 for a real
    and a guessed id); then the vehicle must exist (404). The response has no
    GPS fields. `GET /machine-state/current` is left unchanged for its existing
    consumers (SG-1 records it as a pre-existing unguarded read)."""
    require_trusted_reader(context, "ค่ามาตรวัดของรถ (vehicle machine state)")
    readings = await service.preview_current_state(AssetType.VEHICLE, vehicle_id)
    return VehicleMachineStateResponse(
        vehicle_id=vehicle_id,
        readings=[_reading_response(r) for r in readings],
    )
