"""Part Master / Part Set routes (Phase 5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.part_schemas import (
    CreatePartMasterRequest,
    CreatePartSetRequest,
    CreatePartSetRevisionRequest,
    PartMasterResponse,
    PartSetItemResponse,
    PartSetResponse,
    PartSetRevisionDetailResponse,
    PartSetRevisionResponse,
)
from app.dependencies import get_part_service
from app.domain.common import Page, PageParams
from app.domain.part import PartMaster, PartSet, PartSetRevisionDetail, TrackingMode
from app.domain.part_service import PartService, PartSetItemInput

router = APIRouter(tags=["parts"])


def _part_response(part: PartMaster) -> PartMasterResponse:
    return PartMasterResponse.model_validate(part.model_dump())


def _part_set_response(part_set: PartSet) -> PartSetResponse:
    return PartSetResponse.model_validate(part_set.model_dump())


def _revision_detail_response(detail: PartSetRevisionDetail) -> PartSetRevisionDetailResponse:
    return PartSetRevisionDetailResponse(
        part_set=_part_set_response(detail.part_set),
        revision=PartSetRevisionResponse.model_validate(detail.revision.model_dump()),
        items=[PartSetItemResponse.model_validate(i.model_dump()) for i in detail.items],
    )


@router.post("/parts", response_model=PartMasterResponse)
async def create_part(
    body: CreatePartMasterRequest, service: PartService = Depends(get_part_service)
) -> PartMasterResponse:
    part = await service.create_part(
        part_code=body.part_code,
        name=body.name,
        specification=body.specification,
        manufacturer=body.manufacturer,
        part_number=body.part_number,
        tracking_mode=body.tracking_mode,
        category=body.category,
        metadata=body.metadata,
    )
    return _part_response(part)


@router.get("/parts", response_model=Page[PartMasterResponse])
async def list_parts(
    q: str | None = Query(default=None),
    tracking_mode: TrackingMode | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: PartService = Depends(get_part_service),
) -> Page[PartMasterResponse]:
    result = await service.list_parts(
        q=q, tracking_mode=tracking_mode, params=PageParams(page=page, page_size=page_size)
    )
    return Page[PartMasterResponse](
        items=[_part_response(p) for p in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/parts/{part_id}", response_model=PartMasterResponse)
async def get_part(part_id: str, service: PartService = Depends(get_part_service)) -> PartMasterResponse:
    part = await service.get_part(part_id)
    return _part_response(part)


@router.post("/part-sets", response_model=PartSetResponse)
async def create_part_set(
    body: CreatePartSetRequest, service: PartService = Depends(get_part_service)
) -> PartSetResponse:
    part_set = await service.create_part_set(set_code=body.set_code, name=body.name)
    return _part_set_response(part_set)


@router.post("/part-sets/{part_set_id}/revisions", response_model=PartSetRevisionDetailResponse)
async def create_part_set_revision(
    part_set_id: str,
    body: CreatePartSetRevisionRequest,
    service: PartService = Depends(get_part_service),
) -> PartSetRevisionDetailResponse:
    detail = await service.create_part_set_revision(
        part_set_id=part_set_id,
        effective_date=body.effective_date,
        items=[
            PartSetItemInput(
                part_id=i.part_id,
                requirement=i.requirement,
                quantity=i.quantity,
                unit=i.unit,
                note=i.note,
            )
            for i in body.items
        ],
    )
    return _revision_detail_response(detail)


@router.get("/part-sets/{part_set_id}/active-revision", response_model=PartSetRevisionDetailResponse)
async def get_active_part_set_revision(
    part_set_id: str, service: PartService = Depends(get_part_service)
) -> PartSetRevisionDetailResponse:
    detail = await service.get_active_part_set_revision(part_set_id)
    return _revision_detail_response(detail)


@router.get(
    "/part-sets/{part_set_id}/revisions/{revision_id}",
    response_model=PartSetRevisionDetailResponse,
)
async def get_part_set_revision(
    part_set_id: str, revision_id: str, service: PartService = Depends(get_part_service)
) -> PartSetRevisionDetailResponse:
    detail = await service.get_part_set_revision(part_set_id, revision_id)
    return _revision_detail_response(detail)
