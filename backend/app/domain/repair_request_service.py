"""Repair Request domain service (Core Demo Fixes Delta REV05 section 3).

Owns the boundary between "reported problem" (`RepairRequest`,
`request_status="PENDING"`) and "accepted Repair Work Order" (`Repair`,
`RPR-xxxx`) — only an authorized Maintenance actor (checked at the route
layer via `app.domain.authz.require_capability(..., CAN_MANAGE_REPAIR,
...)`) may convert one into the other, or open an RPR with no request at
all. This service itself does not re-check capabilities — see
`app.api.v1.repair_requests`.
"""
from __future__ import annotations

from fastapi import status

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists
from app.domain.common import Page, PageParams
from app.domain.meter_service import MeterService
from app.domain.repair import RepairDetail, RepairSourceType
from app.domain.repair_request import (
    REPAIR_REQUEST_STATUS_CONVERTED,
    RepairRequest,
)
from app.domain.repair_service import RepairService
from app.errors import ApiError
from app.repositories.base import Repository


class RepairRequestService:
    def __init__(
        self,
        repository: Repository,
        repair_service: RepairService,
        meter_service: MeterService,
    ) -> None:
        self._repository = repository
        self._repair_service = repair_service
        self._meter = meter_service

    async def create(
        self,
        vehicle_id: str,
        reported_by_user_id: str | None,
        reporter_type: str | None,
        reporter_driver_id: str | None,
        reporter_name_snapshot_th: str | None,
        report_channel: str | None,
        symptom_th: str | None,
        priority: str | None,
        note_th: str | None,
    ) -> tuple[RepairRequest, str | None]:
        """Report a problem. Never creates a Repair Work Order (REV05
        section 2A). Returns the created request plus the
        `meter_snapshot_id` of the automatic machine-state snapshot
        captured for this event (REV05 section 4 / CORE-G01) — the linked
        `location_snapshot` is reachable from that same id via
        `GET /location-snapshots/by-event/{id}`, exactly like every other
        automatic-snapshot call site."""
        await require_asset_exists(self._repository, AssetType.VEHICLE, vehicle_id)
        snapshot = await self._meter.capture_current_state(
            asset_type=AssetType.VEHICLE,
            asset_id=vehicle_id,
            recorded_by=reported_by_user_id,
            source_note="REPAIR_REQUEST_REPORT",
        )
        request = await self._repository.create_repair_request(
            vehicle_id=vehicle_id,
            reported_by_user_id=reported_by_user_id,
            reporter_type=reporter_type,
            reporter_driver_id=reporter_driver_id,
            reporter_name_snapshot_th=reporter_name_snapshot_th,
            report_channel=report_channel,
            symptom_th=symptom_th,
            priority=priority,
            note_th=note_th,
            meter_snapshot_id=snapshot.meter_snapshot_id,
        )
        return request, snapshot.meter_snapshot_id

    async def get(self, repair_request_id: str) -> RepairRequest:
        request = await self._repository.get_repair_request(repair_request_id)
        if request is None:
            raise ApiError(
                code="REPAIR_REQUEST_NOT_FOUND",
                message=f"Repair request '{repair_request_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return request

    async def list_pending(self, params: PageParams) -> Page[RepairRequest]:
        """รายการแจ้งซ่อมรอตรวจรับ."""
        items, total = await self._repository.list_pending_repair_requests(params)
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def convert(
        self,
        repair_request_id: str,
        reviewed_by_user_id: str | None,
        category: str | None,
        primary_technician: str | None,
        collaborators: list[str] | None,
    ) -> RepairDetail:
        """Accept a pending Repair Request as a Repair Work Order.
        Idempotent against a retried conversion: a request already
        `CONVERTED` returns its existing linked Repair rather than
        creating a second one (REV05 section 3, "never create duplicate
        RPRs for the same accepted conversion event")."""
        request = await self.get(repair_request_id)
        if request.request_status == REPAIR_REQUEST_STATUS_CONVERTED:
            if request.repair_id is None:
                # Structurally unreachable via this service (only
                # `mark_repair_request_converted` sets CONVERTED, and it
                # always sets repair_id in the same write) — fail loudly
                # rather than silently re-converting.
                raise ApiError(
                    code="REPAIR_REQUEST_INVALID_STATE",
                    message=(
                        f"Repair request '{repair_request_id}' is CONVERTED but has no "
                        "linked repair_id"
                    ),
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            return await self._repair_service.get_repair(request.repair_id)

        detail = await self._repair_service.create_repair(
            asset_type=AssetType.VEHICLE,
            asset_id=request.vehicle_id,
            source_type=RepairSourceType.REPAIR_REQUEST,
            source_id=repair_request_id,
            category=category,
            symptom=request.symptom_th,
            meter_snapshot_id=None,
            opened_by=reviewed_by_user_id,
            primary_technician=primary_technician,
            collaborators=collaborators,
        )
        await self._repository.mark_repair_request_converted(
            repair_request_id=repair_request_id,
            repair_id=detail.repair.repair_id,
            reviewed_by_user_id=reviewed_by_user_id,
        )
        return detail


__all__ = ["RepairRequestService"]
