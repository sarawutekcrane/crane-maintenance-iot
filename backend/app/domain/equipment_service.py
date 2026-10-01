"""Workshop equipment domain service (see `app.domain.vehicle_service` for
the same pattern applied to vehicles)."""
from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.search_match import record_matches, tokenize
from app.domain.equipment import (
    Equipment,
    EquipmentCategory,
    EquipmentOperationalStatus,
    EquipmentStatusHistoryEntry,
)
from app.domain.equipment_errors import (
    EQUIPMENT_HISTORY_TAB,
    EQUIPMENT_TAB,
    data_invalid_error,
    equipment_write_error,
)
from app.domain.equipment_rules import ISSUE_MIXED_TIMEZONE_TIMESTAMP
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryError

T = TypeVar("T")


def _is_aware(value) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class EquipmentService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    @staticmethod
    async def _call(operation: Awaitable[T]) -> T:
        """Phase 7 Batch 7K2: map the expected repository failures of the
        validated equipment paths to their API errors; anything else is
        re-raised unchanged (generic handler)."""
        try:
            return await operation
        except RepositoryError as exc:
            mapped = equipment_write_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> Page[Equipment]:
        """Phase 7 Batch 7J2 (D-7) flexible matching, category, equipment_id
        ordering and paging — unchanged — over the Phase 7 Batch 7K2
        validated, text-preserving read. DEC-K2(b): any row failing the record
        gates fails the whole list with per-row issue counts (no ids); blank
        and duplicate ids are listed."""
        tokens = tokenize(q)
        read = await self._call(self._repository.read_equipment_master())
        if read.issue_counts:
            raise data_invalid_error(EQUIPMENT_TAB, read.issue_counts)
        items = list(read.equipment)
        if category is not None:
            items = [e for e in items if e.category == category]
        if tokens is not None:
            items = [
                e
                for e in items
                if record_matches(tokens, (e.name,), (e.equipment_id, e.equipment_code))
            ]
        items.sort(key=lambda e: e.equipment_id)
        start = (params.page - 1) * params.page_size
        return Page(
            items=items[start : start + params.page_size],
            page=params.page,
            page_size=params.page_size,
            total_items=len(items),
        )

    async def get_equipment(self, equipment_id: str) -> Equipment:
        equipment = await self._call(self._repository.get_equipment_validated(equipment_id))
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
        for new work, not here).

        Phase 7 Batch 7K2: ONE repository call (validated locate, intended
        response and history preflight before the first write; one targeted
        status cell; then the history append). An acknowledged status write
        is not a verified stored state: nothing is re-read, retried or
        compensated."""
        result = await self._call(
            self._repository.change_equipment_status_validated(
                equipment_id=equipment_id, status=new_status, reason=reason, changed_by=changed_by
            )
        )
        if result is None:
            raise ApiError(
                code="EQUIPMENT_NOT_FOUND",
                message=f"Equipment '{equipment_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return result[0]

    async def list_status_history(self, equipment_id: str) -> list[EquipmentStatusHistoryEntry]:
        """Phase 7 Batch 7K2 (4.5): equipment pre-check, then this
        equipment's history rows. Per-row data issues fail the response
        (DEC-K7(a)); DEC-K9(b): when naive and timezone-aware start_at values
        are mixed, each naive row counts as MIXED_TIMEZONE_TIMESTAMP and no
        value is reinterpreted. Order: changed_at ascending, stable."""
        await self.get_equipment(equipment_id)
        read = await self._call(
            self._repository.list_equipment_status_history_validated(equipment_id)
        )
        issues = dict(read.issue_counts)
        entries = list(read.entries)
        naive = [e for e in entries if not _is_aware(e.changed_at)]
        if naive and len(naive) < len(entries):
            issues[ISSUE_MIXED_TIMEZONE_TIMESTAMP] = (
                issues.get(ISSUE_MIXED_TIMEZONE_TIMESTAMP, 0) + len(naive)
            )
        if issues:
            raise data_invalid_error(EQUIPMENT_HISTORY_TAB, issues)
        entries.sort(key=lambda e: e.changed_at)
        return entries
