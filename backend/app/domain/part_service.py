"""Part Master and Part Set / Kit revision domain service (Phase 5).

Part Master is created on demand (guardrails §12) — there is no
requirement to pre-load a company parts catalog before the system can
operate; `create_part` simply records a new specification the moment it
is identified. Different specifications always get a different `part_id`
(this service never merges two `create_part` calls just because their
`name` matches).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.part import PartMaster, PartSet, PartSetItemRequirement, PartSetRevisionDetail, TrackingMode
from app.errors import ApiError
from app.repositories.base import Repository


@dataclass(frozen=True)
class PartSetItemInput:
    part_id: str
    requirement: PartSetItemRequirement
    quantity: float | None = None
    unit: str | None = None
    note: str | None = None


class PartService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def create_part(
        self,
        part_code: str,
        name: str,
        specification: str | None,
        manufacturer: str | None,
        part_number: str | None,
        tracking_mode: TrackingMode,
        category: str | None,
        metadata: dict[str, str],
    ) -> PartMaster:
        return await self._repository.create_part_master(
            part_code=part_code,
            name=name,
            specification=specification,
            manufacturer=manufacturer,
            part_number=part_number,
            tracking_mode=tracking_mode,
            category=category,
            metadata=metadata,
        )

    async def get_part(self, part_id: str) -> PartMaster:
        part = await self._repository.get_part_master(part_id)
        if part is None:
            raise ApiError(
                code="PART_NOT_FOUND",
                message=f"Part '{part_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return part

    async def list_parts(
        self, q: str | None, tracking_mode: TrackingMode | None, params: PageParams
    ) -> Page[PartMaster]:
        items, total = await self._repository.list_part_masters(
            q=q, tracking_mode=tracking_mode, params=params
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    # ---- Part Set / Kit revision ----

    async def create_part_set(self, set_code: str, name: str) -> PartSet:
        return await self._repository.create_part_set(set_code=set_code, name=name)

    async def _require_part_set(self, part_set_id: str) -> PartSet:
        part_set = await self._repository.get_part_set(part_set_id)
        if part_set is None:
            raise ApiError(
                code="PART_SET_NOT_FOUND",
                message=f"Part set '{part_set_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return part_set

    async def create_part_set_revision(
        self,
        part_set_id: str,
        effective_date: date,
        items: list[PartSetItemInput],
    ) -> PartSetRevisionDetail:
        await self._require_part_set(part_set_id)
        for item in items:
            await self.get_part(item.part_id)
        return await self._repository.create_part_set_revision(
            part_set_id=part_set_id,
            effective_date=effective_date,
            items=[
                {
                    "part_id": i.part_id,
                    "requirement": i.requirement,
                    "quantity": i.quantity,
                    "unit": i.unit,
                    "note": i.note,
                }
                for i in items
            ],
        )

    async def get_active_part_set_revision(self, part_set_id: str) -> PartSetRevisionDetail:
        await self._require_part_set(part_set_id)
        detail = await self._repository.get_active_part_set_revision(part_set_id)
        if detail is None:
            raise ApiError(
                code="NO_ACTIVE_PART_SET_REVISION",
                message=f"No active revision is configured for part set '{part_set_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def get_part_set_revision(
        self, part_set_id: str, revision_id: str
    ) -> PartSetRevisionDetail:
        detail = await self._repository.get_part_set_revision(part_set_id, revision_id)
        if detail is None:
            raise ApiError(
                code="PART_SET_REVISION_NOT_FOUND",
                message=f"Part set revision '{revision_id}' was not found for set '{part_set_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail
