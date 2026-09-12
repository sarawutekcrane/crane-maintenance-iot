"""Repair domain service.

Validates a repair's `source_type`/`source_id` link against the actual
source record when one is named (FINDING / INSPECTION_RESULT / PM_RESULT)
— per F02 (unresolved), this only proves the reference is real; it never
enforces one-to-one/many-to-one, deduplication, or an approval step, and
it never mutates the source record itself (Phase 3's `InspectionFinding`
is only ever read here, never written).

Everything else (append-only actions, separate actual-part records,
attachment references, close) follows the same minimal, non-inventive
pattern as `PmService` — see `app.domain.repair` module docstring for the
exact governance reasoning per rule.
"""
from __future__ import annotations

from fastapi import status

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists
from app.domain.common import Page, PageParams
from app.domain.meter_service import MeterService
from app.domain.repair import RepairDetail, RepairSourceType, RepairStatus, RepairSummary
from app.errors import ApiError
from app.repositories.base import Repository


class RepairService:
    def __init__(self, repository: Repository, meter_service: MeterService) -> None:
        self._repository = repository
        self._meter = meter_service

    async def _validate_source(self, source_type: RepairSourceType, source_id: str | None) -> None:
        if source_type == RepairSourceType.MANUAL:
            return

        if not source_id:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=f"source_id is required when source_type is '{source_type.value}'",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if source_type == RepairSourceType.ALERT:
            # Interface-ready only: no Alert domain exists yet in this
            # repository (a later phase) to validate against — see the
            # module docstring's FINDING-TO-REPAIR/ALERT note.
            return

        found = False
        if source_type == RepairSourceType.FINDING:
            found = await self._repository.find_inspection_finding(source_id) is not None
        elif source_type == RepairSourceType.INSPECTION_RESULT:
            found = await self._repository.find_inspection_result(source_id) is not None
        elif source_type == RepairSourceType.PM_RESULT:
            found = await self._repository.find_pm_work_result(source_id) is not None

        if not found:
            raise ApiError(
                code="REPAIR_SOURCE_NOT_FOUND",
                message=f"{source_type.value} source '{source_id}' was not found",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"source_type": source_type.value, "source_id": source_id},
            )

    async def create_repair(
        self,
        asset_type: AssetType,
        asset_id: str,
        source_type: RepairSourceType,
        source_id: str | None,
        category: str | None,
        symptom: str | None,
        meter_snapshot_id: str | None,
        opened_by: str | None,
    ) -> RepairDetail:
        await require_asset_exists(self._repository, asset_type, asset_id)
        await self._validate_source(source_type, source_id)
        await self._meter.require_snapshot_exists(meter_snapshot_id)

        repair = await self._repository.create_repair(
            asset_type=asset_type,
            asset_id=asset_id,
            source_type=source_type,
            source_id=source_id,
            category=category,
            symptom=symptom,
            meter_snapshot_id=meter_snapshot_id,
            opened_by=opened_by,
        )
        return await self.get_repair(repair.repair_id)

    async def get_repair(self, repair_id: str) -> RepairDetail:
        detail = await self._repository.get_repair(repair_id)
        if detail is None:
            raise ApiError(
                code="REPAIR_NOT_FOUND",
                message=f"Repair '{repair_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def list_repairs(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        repair_status: RepairStatus | None,
        params: PageParams,
    ) -> Page[RepairSummary]:
        items, total = await self._repository.list_repairs(
            asset_type=asset_type, asset_id=asset_id, status=repair_status, params=params
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def add_action(
        self, repair_id: str, action_text: str, actor: str | None, attachment_ids: list[str]
    ) -> RepairDetail:
        await self.get_repair(repair_id)
        if not action_text or not action_text.strip():
            raise ApiError(
                code="VALIDATION_ERROR",
                message="action_text must not be empty",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        await self._repository.add_repair_action(
            repair_id=repair_id, action_text=action_text, actor=actor, attachment_ids=list(attachment_ids)
        )
        return await self.get_repair(repair_id)

    async def add_part(
        self,
        repair_id: str,
        part_description: str,
        quantity: float | None,
        unit: str | None,
        recorded_by: str | None,
    ) -> RepairDetail:
        await self.get_repair(repair_id)
        await self._repository.add_repair_part(
            repair_id=repair_id,
            part_description=part_description,
            quantity=quantity,
            unit=unit,
            recorded_by=recorded_by,
        )
        return await self.get_repair(repair_id)

    async def close_repair(
        self, repair_id: str, closed_by: str | None, close_note: str | None
    ) -> RepairDetail:
        detail = await self.get_repair(repair_id)
        if detail.repair.status == RepairStatus.CLOSED:
            raise ApiError(
                code="REPAIR_ALREADY_CLOSED",
                message=f"Repair '{repair_id}' is already closed",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        await self._repository.close_repair(repair_id, closed_by=closed_by, close_note=close_note)
        return await self.get_repair(repair_id)
