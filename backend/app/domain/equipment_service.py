"""Workshop equipment domain service (see `app.domain.vehicle_service` for
the same pattern applied to vehicles)."""
from __future__ import annotations

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.equipment import Equipment, EquipmentCategory
from app.errors import ApiError
from app.repositories.base import Repository


class EquipmentService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> Page[Equipment]:
        items, total = await self._repository.list_equipment(
            q=q, category=category, params=params
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def get_equipment(self, equipment_id: str) -> Equipment:
        equipment = await self._repository.get_equipment(equipment_id)
        if equipment is None:
            raise ApiError(
                code="EQUIPMENT_NOT_FOUND",
                message=f"Equipment '{equipment_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return equipment
