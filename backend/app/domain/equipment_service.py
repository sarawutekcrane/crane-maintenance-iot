"""Workshop equipment domain service (see `app.domain.vehicle_service` for
the same pattern applied to vehicles)."""
from __future__ import annotations

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.equipment import (
    Equipment,
    EquipmentCategory,
    EquipmentOperationalStatus,
    EquipmentStatusHistoryEntry,
)
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

    async def change_status(
        self,
        equipment_id: str,
        new_status: EquipmentOperationalStatus,
        reason: str | None,
        changed_by: str | None,
    ) -> Equipment:
        """Core Demo Fix: equipment status change with reason/actor/
        timestamp, appended to an immutable history (never overwritten).
        No transition-matrix is enforced (equipment status transition
        rules remain TBD-BLOCKING per OPEN_DECISIONS_REGISTER_EN.txt C02)
        beyond the one explicit rule the prompt approves: RETIRED preserves
        history and is never itself the target of further "normal work"
        selection checks (enforced at the call sites that select an asset
        for new work, not here)."""
        await self.get_equipment(equipment_id)
        return await self._repository.change_equipment_status(
            equipment_id=equipment_id, status=new_status, reason=reason, changed_by=changed_by
        )

    async def list_status_history(self, equipment_id: str) -> list[EquipmentStatusHistoryEntry]:
        await self.get_equipment(equipment_id)
        return await self._repository.list_equipment_status_history(equipment_id)
