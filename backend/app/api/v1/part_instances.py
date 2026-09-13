"""INSTANCE_TRACKED part-instance routes: on-demand enrollment, install/
remove/transfer, and lifecycle (overhaul) boundaries (Phase 5).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.part_instance_schemas import (
    CreatePartInstanceRequest,
    InstallPartInstanceRequest,
    InstallationSegmentResponse,
    PartInstanceDetailResponse,
    PartInstanceResponse,
    PartLifecycleResponse,
    PriorUsageResponse,
    RemovePartInstanceRequest,
    StartNewLifecycleRequest,
    TransferPartInstanceRequest,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_part_instance_service
from app.domain.part_instance import PartInstanceDetail, PriorUsage
from app.domain.part_instance_service import PartInstanceService

router = APIRouter(tags=["part-instances"])


def _detail_response(detail: PartInstanceDetail) -> PartInstanceDetailResponse:
    return PartInstanceDetailResponse(
        instance=PartInstanceResponse(
            part_instance_id=detail.instance.part_instance_id,
            part_id=detail.instance.part_id,
            serial_number=detail.instance.serial_number,
            status=detail.instance.status,
            prior_usage=PriorUsageResponse.model_validate(detail.instance.prior_usage.model_dump()),
            current_lifecycle_id=detail.instance.current_lifecycle_id,
            note=detail.instance.note,
            created_at=detail.instance.created_at,
            updated_at=detail.instance.updated_at,
        ),
        lifecycles=[
            PartLifecycleResponse.model_validate(lc.model_dump()) for lc in detail.lifecycles
        ],
        segments=[
            InstallationSegmentResponse.model_validate(s.model_dump()) for s in detail.segments
        ],
    )


@router.post("/part-instances", response_model=PartInstanceDetailResponse)
async def create_part_instance(
    body: CreatePartInstanceRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
) -> PartInstanceDetailResponse:
    detail = await service.create_instance(
        part_id=body.part_id,
        serial_number=body.serial_number,
        prior_usage=PriorUsage(
            quality=body.prior_usage.quality,
            value=body.prior_usage.value,
            note=body.prior_usage.note,
        ),
        note=body.note,
        created_by=context.user_id,
    )
    return _detail_response(detail)


@router.get("/part-instances/{part_instance_id}", response_model=PartInstanceDetailResponse)
async def get_part_instance(
    part_instance_id: str, service: PartInstanceService = Depends(get_part_instance_service)
) -> PartInstanceDetailResponse:
    detail = await service.get_instance(part_instance_id)
    return _detail_response(detail)


@router.post(
    "/part-instances/{part_instance_id}/install", response_model=PartInstanceDetailResponse
)
async def install_part_instance(
    part_instance_id: str,
    body: InstallPartInstanceRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
) -> PartInstanceDetailResponse:
    detail = await service.install(
        part_instance_id=part_instance_id,
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        position_code=body.position_code,
        baseline_meter_snapshot_id=body.baseline_meter_snapshot_id,
        installed_by=context.user_id,
        note=body.note,
    )
    return _detail_response(detail)


@router.post("/part-instances/{part_instance_id}/remove", response_model=PartInstanceDetailResponse)
async def remove_part_instance(
    part_instance_id: str,
    body: RemovePartInstanceRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
) -> PartInstanceDetailResponse:
    detail = await service.remove(
        part_instance_id=part_instance_id,
        next_status=body.next_status,
        removal_meter_snapshot_id=body.removal_meter_snapshot_id,
        removal_reason=body.removal_reason,
        removed_by=context.user_id,
    )
    return _detail_response(detail)


@router.post(
    "/part-instances/{part_instance_id}/transfer", response_model=PartInstanceDetailResponse
)
async def transfer_part_instance(
    part_instance_id: str,
    body: TransferPartInstanceRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
) -> PartInstanceDetailResponse:
    detail = await service.transfer(
        part_instance_id=part_instance_id,
        target_asset_type=body.target_asset_type,
        target_asset_id=body.target_asset_id,
        position_code=body.position_code,
        removal_meter_snapshot_id=body.removal_meter_snapshot_id,
        baseline_meter_snapshot_id=body.baseline_meter_snapshot_id,
        removal_reason=body.removal_reason,
        transferred_by=context.user_id,
        note=body.note,
    )
    return _detail_response(detail)


@router.post(
    "/part-instances/{part_instance_id}/start-new-lifecycle",
    response_model=PartInstanceDetailResponse,
)
async def start_new_lifecycle(
    part_instance_id: str,
    body: StartNewLifecycleRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
) -> PartInstanceDetailResponse:
    detail = await service.start_new_lifecycle(
        part_instance_id=part_instance_id,
        approved_reason=body.approved_reason,
        started_by=context.user_id,
    )
    return _detail_response(detail)
