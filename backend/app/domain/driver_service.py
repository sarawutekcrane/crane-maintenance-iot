"""Driver / Operator master service (Web/API Phase 6 Batch 1). The Phase 6
vehicle<->driver assignment methods were retired in R2 Batch R2-C3.

See `app.domain.driver` module docstring for the verified live-sheet
field shapes and the NO-GUESSING RULE governing `active_status`. This service adds no business vocabulary beyond
what that module already documents.
"""
from __future__ import annotations

from datetime import date

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.driver import Driver
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
        fields_set: frozenset[str] = frozenset(),
    ) -> Driver:
        """Partial update. LIVE UAT DEFECT FIX: `Repository.update_driver`
        is, and remains, a full-replace contract (see its own docstring)
        — this method is the one place that resolves PATCH's "omitted
        vs explicit" distinction before calling it, so the repository
        layer needs no change and no knowledge of HTTP semantics.

        `fields_set` is `UpdateDriverRequest.model_fields_set` from the
        route (empty by default only for any other caller that does not
        need partial-update semantics — none currently exists). A field
        NOT in `fields_set` (omitted from the PATCH request body) keeps
        its current stored value exactly; a field present in
        `fields_set` is applied as given, INCLUDING an explicit JSON
        `null` (which clears it) — this preserves this endpoint's own
        pre-existing behavior for a value the client actually sent
        (before this fix, every field was always "sent" in effect, so
        `None` always meant "clear"; that is unchanged here). This is
        not an established project-wide "explicit null clears" rule —
        no other endpoint has this shape — it is this endpoint's own
        continued behavior for the one case (explicit null) that was
        already observable before this fix; see the Phase 6 Batch 1
        result report for this explicitly flagged as a judgment call,
        not silently invented."""
        existing = await self.get_driver(driver_id)
        name = self._require_name(driver_name_th)
        return await self._repository.update_driver(
            driver_id=driver_id,
            driver_name_th=name,
            phone=phone if "phone" in fields_set else existing.phone,
            license_no=license_no if "license_no" in fields_set else existing.license_no,
            license_expiry_date=(
                license_expiry_date
                if "license_expiry_date" in fields_set
                else existing.license_expiry_date
            ),
            active_status=(
                active_status if "active_status" in fields_set else existing.active_status
            ),
            note_th=note_th if "note_th" in fields_set else existing.note_th,
        )


__all__ = ["DriverService"]
