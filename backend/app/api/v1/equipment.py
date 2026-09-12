"""Workshop equipment routes (Phase 2).

`/equipment/{equipment_id}` backs the stable QR entry point for
non-vehicle machinery (baseline section 5/7): the frontend route
`/equipment/{equipment_id}` calls `GET /api/v1/equipment/{equipment_id}`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.equipment_schemas import EquipmentResponse
from app.dependencies import get_equipment_service
from app.domain.common import Page, PageParams
from app.domain.equipment import EquipmentCategory
from app.domain.equipment_service import EquipmentService

router = APIRouter(tags=["equipment"])


@router.get("/equipment", response_model=Page[EquipmentResponse])
async def list_equipment(
    q: str | None = Query(default=None),
    category: EquipmentCategory | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: EquipmentService = Depends(get_equipment_service),
) -> Page[EquipmentResponse]:
    result = await service.list_equipment(
        q=q, category=category, params=PageParams(page=page, page_size=page_size)
    )
    return Page[EquipmentResponse](
        items=[EquipmentResponse.model_validate(e.model_dump()) for e in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/equipment/{equipment_id}", response_model=EquipmentResponse)
async def get_equipment(
    equipment_id: str, service: EquipmentService = Depends(get_equipment_service)
) -> EquipmentResponse:
    equipment = await service.get_equipment(equipment_id)
    return EquipmentResponse.model_validate(equipment.model_dump())
