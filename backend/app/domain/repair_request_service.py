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
    REPAIR_REQUEST_DEFECT_SOURCE_TYPES,
    REPAIR_REQUEST_STATUS_CONVERTED,
    RepairRequest,
    decode_provenance_note,
    encode_provenance_note,
)
from app.domain.repair_service import RepairService
from app.errors import ApiError
from app.repositories.base import Repository


def _with_decoded_provenance(request: RepairRequest) -> RepairRequest:
    """REV06 section 15: the single point (besides `encode_provenance_note`
    in `create` below) where the `[[SRC:...]]` marker is parsed — every
    `RepairRequest` this service hands back to a caller already has clean
    `note_th` plus decoded `source_type`/`source_id`, so nothing outside
    this module (including `app.api.v1.repair_requests`) ever needs to
    know the encoding exists."""
    source_type, source_id, clean_note = decode_provenance_note(request.note_th)
    return request.model_copy(
        update={"note_th": clean_note, "source_type": source_type, "source_id": source_id}
    )


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
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> tuple[RepairRequest, str | None]:
        """Report a problem. Never creates a Repair Work Order (REV05
        section 2A). Returns the created request plus the
        `meter_snapshot_id` of the automatic machine-state snapshot
        captured for this event (REV05 section 4 / CORE-G01) — the linked
        `location_snapshot` is reachable from that same id via
        `GET /location-snapshots/by-event/{id}`, exactly like every other
        automatic-snapshot call site.

        `source_type`/`source_id` (REV06 section 15) optionally names the
        originating Finding/PM Work Result this report was made from —
        the approved non-Maintenance routing for both an Inspection
        Finding and a PM defect (section 4: "... -> Repair Request ->
        Maintenance review -> RPR", never a direct RPR). Validated against
        a real record exactly like `RepairService._validate_source` does
        for a direct Maintenance-opened Repair, then encoded into the
        persisted `note_th` (see `encode_provenance_note`) since the live
        `repair_request` sheet's fixed 16-column schema has no dedicated
        source column."""
        await require_asset_exists(self._repository, AssetType.VEHICLE, vehicle_id)
        if source_type is not None:
            await self._require_defect_source_exists(source_type, source_id)
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
            note_th=encode_provenance_note(source_type, source_id, note_th),
            meter_snapshot_id=snapshot.meter_snapshot_id,
        )
        return _with_decoded_provenance(request), snapshot.meter_snapshot_id

    async def _require_defect_source_exists(
        self, source_type: str, source_id: str | None
    ) -> None:
        if source_type not in REPAIR_REQUEST_DEFECT_SOURCE_TYPES:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=(
                    f"source_type '{source_type}' is not a supported Repair Request "
                    f"defect source (must be one of {sorted(REPAIR_REQUEST_DEFECT_SOURCE_TYPES)})"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if not source_id:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=f"source_id is required when source_type is '{source_type}'",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        found = False
        if source_type == "FINDING":
            found = await self._repository.find_inspection_finding(source_id) is not None
        elif source_type == "PM_RESULT":
            found = await self._repository.find_pm_work_result(source_id) is not None
        if not found:
            raise ApiError(
                code="REPAIR_REQUEST_SOURCE_NOT_FOUND",
                message=f"{source_type} source '{source_id}' was not found",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"source_type": source_type, "source_id": source_id},
            )

    async def get(self, repair_request_id: str) -> RepairRequest:
        request = await self._repository.get_repair_request(repair_request_id)
        if request is None:
            raise ApiError(
                code="REPAIR_REQUEST_NOT_FOUND",
                message=f"Repair request '{repair_request_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return _with_decoded_provenance(request)

    async def list_pending(self, params: PageParams) -> Page[RepairRequest]:
        """รายการแจ้งซ่อมรอตรวจรับ."""
        items, total = await self._repository.list_pending_repair_requests(params)
        items = [_with_decoded_provenance(item) for item in items]
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def list_mine(
        self, reported_by_user_id: str, params: PageParams
    ) -> Page[RepairRequest]:
        """คำขอแจ้งซ่อมของฉัน (Web UAT Defect Fix UAT-F2) — every Repair
        Request the current actor reported, any status, so they can find
        one they already submitted without navigating away and losing it.
        Strictly narrower than `get`'s existing unrestricted lookup-by-id
        (see `list_repair_requests_by_reporter`)."""
        items, total = await self._repository.list_repair_requests_by_reporter(
            reported_by_user_id, params
        )
        items = [_with_decoded_provenance(item) for item in items]
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def list_by_source(self, source_type: str, source_id: str) -> list[RepairRequest]:
        """Every Repair Request already reported from this Finding/PM Work
        Result (Web UAT Defect Fix UAT-F3) — lets the UI derive "already
        reported" from persisted data instead of client-only state that
        disappears on reload."""
        items = await self._repository.list_repair_requests_by_source(source_type, source_id)
        return [_with_decoded_provenance(item) for item in items]

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
        RPRs for the same accepted conversion event").

        REV06.1 (independent-audit CONSISTENCY-1 fix): `request_status`
        alone cannot guard every retry, because Google Sheets is
        non-transactional and this method's two writes below
        (`_repair_service.create_repair` then
        `mark_repair_request_converted`) are separate. If the first
        succeeds and the process fails/retries before the second commits,
        `request_status` is still `PENDING` even though a Repair already
        exists for this request — a naive retry would create a second
        `RPR-xxxx` for the same Repair Request. Before creating, this now
        looks for a Repair already linked by `source_type=REPAIR_REQUEST,
        source_id=repair_request_id`: none -> create as before; exactly one
        -> reuse it and finish the linkage write (recovering the previously
        interrupted attempt); more than one means an earlier attempt already
        left corrupted state, and this refuses to create a third rather than
        guessing which one is correct."""
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

        existing_repairs = await self._repository.find_repairs_by_source(
            RepairSourceType.REPAIR_REQUEST, repair_request_id
        )
        if len(existing_repairs) > 1:
            raise ApiError(
                code="REPAIR_REQUEST_CONVERSION_INTEGRITY_ERROR",
                message=(
                    f"Repair request '{repair_request_id}' already has "
                    f"{len(existing_repairs)} repairs linked to it "
                    f"({', '.join(sorted(r.repair_id for r in existing_repairs))}) from an "
                    "earlier corrupted conversion attempt; refusing to create another. "
                    "This requires manual reconciliation."
                ),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={
                    "repair_request_id": repair_request_id,
                    "repair_ids": sorted(r.repair_id for r in existing_repairs),
                },
            )
        if existing_repairs:
            detail = await self._repair_service.get_repair(existing_repairs[0].repair_id)
        else:
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
