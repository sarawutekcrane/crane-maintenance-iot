"""Driver / Operator master + vehicle<->driver assignment service
(Web/API Phase 6 Batch 1).

See `app.domain.driver` module docstring for the verified live-sheet
field shapes and the NO-GUESSING RULE governing `active_status`/
`assignment_status`. This service adds no business vocabulary beyond
what that module already documents.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import status

from app.domain.common import Page, PageParams, utc_now
from app.domain.driver import Driver, VehicleDriverAssignment
from app.errors import ApiError
from app.repositories.base import Repository


class DriverService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    # ---- Driver master ----

    @staticmethod
    def _require_name(driver_name_th: str) -> str:
        name = driver_name_th.strip() if driver_name_th else ""
        if not name:
            raise ApiError(
                code="VALIDATION_ERROR",
                message="กรุณาระบุชื่อพนักงานขับ/ผู้ควบคุม (driver_name_th)",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return name

    async def create_driver(
        self,
        driver_name_th: str,
        phone: str | None,
        license_no: str | None,
        license_expiry_date: date | None,
        active_status: str | None,
        note_th: str | None,
    ) -> Driver:
        name = self._require_name(driver_name_th)
        return await self._repository.create_driver(
            driver_name_th=name,
            phone=phone,
            license_no=license_no,
            license_expiry_date=license_expiry_date,
            active_status=active_status,
            note_th=note_th,
        )

    async def get_driver(self, driver_id: str) -> Driver:
        driver = await self._repository.get_driver(driver_id)
        if driver is None:
            raise ApiError(
                code="DRIVER_NOT_FOUND",
                message=f"Driver '{driver_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return driver

    async def list_drivers(self, q: str | None, params: PageParams) -> Page[Driver]:
        items, total = await self._repository.list_drivers(q=q, params=params)
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def update_driver(
        self,
        driver_id: str,
        driver_name_th: str,
        phone: str | None,
        license_no: str | None,
        license_expiry_date: date | None,
        active_status: str | None,
        note_th: str | None,
    ) -> Driver:
        await self.get_driver(driver_id)
        name = self._require_name(driver_name_th)
        return await self._repository.update_driver(
            driver_id=driver_id,
            driver_name_th=name,
            phone=phone,
            license_no=license_no,
            license_expiry_date=license_expiry_date,
            active_status=active_status,
            note_th=note_th,
        )

    # ---- Vehicle <-> Driver assignment history ----

    async def _require_vehicle_exists(self, vehicle_id: str) -> None:
        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            raise ApiError(
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle '{vehicle_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    async def assign_driver(
        self,
        vehicle_id: str,
        driver_id: str,
        is_primary: bool,
        changed_by_user_id: str | None,
        assignment_status: str | None = None,
        note_th: str | None = None,
    ) -> VehicleDriverAssignment:
        """Start a new assignment period. Never modifies any existing
        assignment row — creating a new assignment (PRIMARY or not) never
        closes, ends, or otherwise touches a prior one. The approved
        Phase 6 Batch 1 requirement is only "assignment start/end history"
        plus "preservation of previous history"; no PRIMARY-exclusivity,
        overlap, or auto-termination rule is approved (project decision,
        targeted correction — see the Phase 6 Batch 1 result report).
        `is_primary` is persisted exactly as given, with no side effect on
        any other row; multiple concurrently-active assignments (PRIMARY
        or not) for the same vehicle are permitted unless/until a future
        explicit project decision defines an exclusivity rule."""
        await self._require_vehicle_exists(vehicle_id)
        await self.get_driver(driver_id)
        start_at = utc_now()
        return await self._repository.create_vehicle_driver_assignment(
            vehicle_id=vehicle_id,
            driver_id=driver_id,
            start_at=start_at,
            is_primary=is_primary,
            assignment_status=assignment_status,
            changed_by_user_id=changed_by_user_id,
            note_th=note_th,
        )

    async def end_assignment(
        self,
        assignment_id: str,
        changed_by_user_id: str | None,
        end_at: datetime | None = None,
    ) -> VehicleDriverAssignment:
        """Close one assignment period. Idempotent: ending an assignment
        that already has `end_at` set is a no-op that returns the
        existing row unchanged (its original `end_at` is preserved
        exactly, no second history row is created, and no error is
        raised) — project decision, targeted correction. No correction/
        edit policy for an already-ended `end_at` is approved; this
        method never overwrites one."""
        assignment = await self._repository.get_vehicle_driver_assignment(assignment_id)
        if assignment is None:
            raise ApiError(
                code="VEHICLE_DRIVER_ASSIGNMENT_NOT_FOUND",
                message=f"Vehicle driver assignment '{assignment_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if assignment.end_at is not None:
            return assignment
        return await self._repository.end_vehicle_driver_assignment(
            assignment_id=assignment_id,
            end_at=end_at or utc_now(),
            changed_by_user_id=changed_by_user_id,
        )

    async def list_vehicle_driver_history(self, vehicle_id: str) -> list[VehicleDriverAssignment]:
        await self._require_vehicle_exists(vehicle_id)
        return await self._repository.list_vehicle_driver_assignments(vehicle_id)


__all__ = ["DriverService"]
