"""INSTANCE_TRACKED part-instance routes: on-demand enrollment, install/
remove/transfer, and lifecycle boundaries (Phase 5; R6 FINAL §8).

R6: every write here accepts an OPTIONAL client `X-Request-Id` (R5
semantics: absent = pre-R6 behaviour; present = idempotent replay of the
committed response, a different body under the same id = 409). The service
returns the committed response, identical on replay.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.v1.part_instance_schemas import (
    CreatePartInstanceRequest,
    InstallPartInstanceRequest,
    PartInstanceDetailResponse,
    RemovePartInstanceRequest,
    StartNewLifecycleRequest,
    TransferPartInstanceRequest,
)
from app.api.v1.repairs import optional_client_request_id
from app.context import RequestContext
from app.dependencies import get_current_context, get_part_instance_service
from app.domain.part_instance import PartInstanceDetail
from app.domain.part_instance_service import PartInstanceService, apply_replay_header

router = APIRouter(tags=["part-instances"])


def _detail_response(detail: PartInstanceDetail | dict) -> PartInstanceDetailResponse:
    data = detail if isinstance(detail, dict) else detail.model_dump(mode="json")
    return PartInstanceDetailResponse.model_validate(data)


def _body(body) -> dict:
    return body.model_dump(mode="json", exclude_unset=True)


@router.post("/part-instances", response_model=PartInstanceDetailResponse)
async def create_part_instance(
    response: Response,
    body: CreatePartInstanceRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str | None = Depends(optional_client_request_id),
) -> PartInstanceDetailResponse:
    detail = await service.create_instance(
        part_id=body.part_id,
        serial_number=body.serial_number,
        prior_usage=body.prior_usage.to_domain(),
        note=body.note,
        created_by=context.user_id,
        tag_label=body.tag_label,
        storage_location=body.storage_location,
        prior_cycle_usage=body.prior_cycle_usage.to_domain() if body.prior_cycle_usage else None,
        initial_status=body.initial_status,
        request_id=request_id,
        body=_body(body),
    )
    apply_replay_header(response, detail)
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
    response: Response,
    part_instance_id: str,
    body: InstallPartInstanceRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str | None = Depends(optional_client_request_id),
) -> PartInstanceDetailResponse:
    detail = await service.install(
        part_instance_id=part_instance_id,
        asset_type=body.asset_type,
        asset_id=body.asset_id,
        position_code=body.position_code,
        baseline_meter_snapshot_id=body.baseline_meter_snapshot_id,
        installed_by=context.user_id,
        note=body.note,
        effective_at=body.effective_at,
        source_type=body.source_type,
        source_id=body.source_id,
        request_id=request_id,
        body=_body(body),
    )
    apply_replay_header(response, detail)
    return _detail_response(detail)


@router.post("/part-instances/{part_instance_id}/remove", response_model=PartInstanceDetailResponse)
async def remove_part_instance(
    response: Response,
    part_instance_id: str,
    body: RemovePartInstanceRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str | None = Depends(optional_client_request_id),
) -> PartInstanceDetailResponse:
    detail = await service.remove(
        part_instance_id=part_instance_id,
        next_status=body.next_status,
        removal_meter_snapshot_id=body.removal_meter_snapshot_id,
        removal_reason=body.removal_reason,
        removed_by=context.user_id,
        storage_location=body.storage_location,
        effective_at=body.effective_at,
        source_type=body.source_type,
        source_id=body.source_id,
        request_id=request_id,
        body=_body(body),
    )
    apply_replay_header(response, detail)
    return _detail_response(detail)


@router.post(
    "/part-instances/{part_instance_id}/transfer", response_model=PartInstanceDetailResponse
)
async def transfer_part_instance(
    response: Response,
    part_instance_id: str,
    body: TransferPartInstanceRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str | None = Depends(optional_client_request_id),
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
        effective_at=body.effective_at,
        source_type=body.source_type,
        source_id=body.source_id,
        request_id=request_id,
        body=_body(body),
    )
    apply_replay_header(response, detail)
    return _detail_response(detail)


@router.post(
    "/part-instances/{part_instance_id}/start-new-lifecycle",
    response_model=PartInstanceDetailResponse,
    responses={409: {"description": "R6 A-2(ii): always NEW_CYCLE_OPENS_AT_INSTALL; nothing is written."}},
)
async def start_new_lifecycle(
    part_instance_id: str,
    body: StartNewLifecycleRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
) -> PartInstanceDetailResponse:
    await service.start_new_lifecycle(
        part_instance_id=part_instance_id,
        approved_reason=body.approved_reason,
        started_by=context.user_id,
    )
    raise AssertionError("unreachable: start_new_lifecycle always raises")  # pragma: no cover
