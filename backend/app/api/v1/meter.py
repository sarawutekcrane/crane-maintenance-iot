"""Meter/counter snapshot routes (Phase 4). Shared by the PM and Repair
workflows — a snapshot is created once and then referenced by
`meter_snapshot_id` when submitting a PM task result or creating a repair.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.meter_schemas import (
    CreateMeterSnapshotRequest,
    MeterReadingResponse,
    MeterSnapshotResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_meter_service
from app.domain.meter import MeterReadingInput, MeterSnapshot
from app.domain.meter_service import MeterService

router = APIRouter(tags=["meter"])


def _snapshot_response(snapshot: MeterSnapshot) -> MeterSnapshotResponse:
    return MeterSnapshotResponse(
        meter_snapshot_id=snapshot.meter_snapshot_id,
        asset_type=snapshot.asset_type,
        asset_id=snapshot.asset_id,
        readings=[
            MeterReadingResponse(
                component_id=r.component_id, counter_type=r.counter_type, value=r.value
            )
            for r in snapshot.readings
        ],
        recorded_at=snapshot.recorded_at,
        recorded_by=snapshot.recorded_by,
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
