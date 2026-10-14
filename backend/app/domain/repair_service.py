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

from app.domain.assignment import active_primary_and_collaborators
from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_for_new_work
from app.domain.common import Page, PageParams
from app.domain.legacy_assignment_retired import refuse_legacy_inline_assignee
from app.domain.meter_service import MeterService
from app.domain.notification import (
    NoOpNotificationSink,
    NotificationPort,
)
from app.domain.part import PartActionType
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.domain.repair import RepairDetail, RepairSourceType, RepairStatus, RepairSummary
from app.domain.technician_assignment import (
    ASSIGNMENT_MODEL_LEGACY,
    REPAIR,
    AssignmentCutover,
    TechnicianAssignmentService,
    assignment_model_of,
    require_legacy,
    v2_job_marker,
)
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryError, RepositorySchemaError


class RepairService:
    def __init__(
        self,
        repository: Repository,
        meter_service: MeterService,
        notification_sink: NotificationPort | None = None,
        assignment_cutover: AssignmentCutover | None = None,
    ) -> None:
        self._repository = repository
        self._meter = meter_service
        self._notifications: NotificationPort = notification_sink or NoOpNotificationSink()
        # R2 Batch R2f-h1: the V2 cutover setting + server context. Default OFF:
        # a service built without it behaves exactly as before.
        self._cutover = assignment_cutover or AssignmentCutover()

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
        elif source_type == RepairSourceType.REPAIR_REQUEST:
            found = await self._repository.get_repair_request(source_id) is not None

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
        primary_technician: str | None = None,
        collaborators: list[str] | None = None,
    ) -> RepairDetail:
        # R2 Batch R2f-h4 B6 (D3): the legacy inline assignee (an opaque user_id)
        # is retired — refused before ANY read or write, never stored, never
        # read as a technician_id.
        refuse_legacy_inline_assignee(primary_technician, collaborators)
        await require_asset_for_new_work(self._repository, asset_type, asset_id)
        await self._validate_source(source_type, source_id)
        # R2 Batch R2f-h4 B6 Rev2 (owner final decision: V2 only): EVERY new
        # Repair (direct creation and Repair Request conversion) is a V2 job.
        # After the input validation (as for the former default) and before ANY
        # write — the automatic snapshot included — the data context and the
        # extended-header proof; a failure fails the creation closed. There is no
        # legacy fallback.
        assignment_marker = await v2_job_marker(self._repository, REPAIR, self._cutover)
        if meter_snapshot_id is not None:
            await self._meter.require_snapshot_exists(meter_snapshot_id)
        else:
            # Normal path: no manual counter/GPS entry on the repair-report
            # form — the backend automatically captures current state
            # (Core Demo Fixes prompt, APPROVED CORE RULE).
            snapshot = await self._meter.capture_current_state(
                asset_type=asset_type,
                asset_id=asset_id,
                recorded_by=opened_by,
                source_note="REPAIR_OPEN",
            )
            meter_snapshot_id = snapshot.meter_snapshot_id

        repair = await self._repository.create_repair(
            asset_type=asset_type,
            asset_id=asset_id,
            source_type=source_type,
            source_id=source_id,
            category=category,
            symptom=symptom,
            meter_snapshot_id=meter_snapshot_id,
            opened_by=opened_by,
            primary_technician=None,
            collaborators=[],
            assignment_marker=assignment_marker,
        )
        return await self.get_repair(repair.repair_id)

    async def list_assignment_history(self, repair_id: str):
        # R2 Batch R2f-h1: the legacy history view serves legacy jobs only (a V2
        # job's rows carry a blank user_id and are read through the V2 route).
        require_legacy((await self.get_repair(repair_id)).repair)
        return await self._repository.list_repair_assignment_history(repair_id)

    async def authorize_recording(self, repair_id: str, context, capability: str, action_description: str) -> None:
        """R2 Batch R2f-h1: recording authorization per job model. Legacy: the
        unchanged REV06.1 path (active legacy history, opaque user_id compare,
        or the capability). V2: the capability, or current V2 set membership
        through User Account -> Personnel -> Technician in scope."""
        from app.domain.authz import require_assignment_or_capability

        detail = await self.get_repair(repair_id)
        if assignment_model_of(detail.repair) == ASSIGNMENT_MODEL_LEGACY:
            history = await self._repository.list_repair_assignment_history(repair_id)
            primary_technician, collaborators = active_primary_and_collaborators(history)
            require_assignment_or_capability(context, capability, primary_technician, collaborators,
                                             action_description)
            return
        await TechnicianAssignmentService(self._repository, self._cutover).require_recording(
            REPAIR, detail.repair, context, capability, action_description)

    async def get_active_assignment(self, repair_id: str) -> tuple[str | None, list[str]]:
        """REV06.1 (independent-audit CONSISTENCY-2 fix): returns
        `(active_primary_technician, active_collaborators)` derived from
        the append-only `repair_assignment` history's currently-active rows
        — this is what `require_assignment_or_capability` must be given for
        an authorization decision, never `Repair.primary_technician`/
        `.collaborators` directly. Those two fields remain on `Repair` for
        display and are kept in sync by `assign_repair`, but that sync is a
        second, separate write after the history rows are appended/ended
        (Google Sheets has no transactions); a failure between the two
        writes must never let the stale denormalized field authorize (or
        deny) the wrong actor. `Repair.primary_technician`/`.collaborators`
        are compatibility/denormalized convenience fields only — this
        method, sourced from history, is authoritative."""
        await self.get_repair(repair_id)
        history = await self._repository.list_repair_assignment_history(repair_id)
        return active_primary_and_collaborators(history)

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
        assigned_to: str | None = None,
        unassigned_only: bool = False,
    ) -> Page[RepairSummary]:
        items, total = await self._repository.list_repairs(
            asset_type=asset_type,
            asset_id=asset_id,
            status=repair_status,
            params=params,
            assigned_to=assigned_to,
            unassigned_only=unassigned_only,
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def list_open_repairs_for_report(
        self, asset_type: AssetType | None, params: PageParams
    ) -> Page[RepairSummary]:
        """Phase 7 Batch 7C2 — "งานซ่อมค้าง" report: OPEN repair work orders
        (never Repair Requests), vehicles and equipment unless `asset_type`
        narrows it; `total_items` is counted before pagination. A proven
        repair_order structural problem is a 500 with no rows or totals
        and any other repository failure a 503 — never an empty or
        partial success. Mapping errors (e.g. an invalid enum value) and
        unexpected bugs propagate to the generic INTERNAL_ERROR handler."""
        try:
            items, total = await self._repository.list_open_repairs_for_report(
                asset_type=asset_type, params=params
            )
        except RepositorySchemaError as exc:
            raise ApiError(
                code="REPAIR_ORDER_SCHEMA_INVALID",
                message=str(exc),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
            ) from exc
        except RepositoryError as exc:
            raise ApiError(
                code="REPAIR_ORDER_READ_FAILED",
                message="repair_order could not be read",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
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
        part_id: str | None = None,
        part_instance_id: str | None = None,
        action: PartActionType | None = None,
    ) -> RepairDetail:
        await self.get_repair(repair_id)
        if part_id is not None:
            await require_part_exists(self._repository, part_id)
        if part_instance_id is not None:
            await require_part_instance_exists(self._repository, part_instance_id)
        await self._repository.add_repair_part(
            repair_id=repair_id,
            part_description=part_description,
            quantity=quantity,
            unit=unit,
            recorded_by=recorded_by,
            part_id=part_id,
            part_instance_id=part_instance_id,
            action=action,
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
        snapshot = await self._meter.capture_current_state(
            asset_type=detail.repair.asset_type,
            asset_id=detail.repair.asset_id,
            recorded_by=closed_by,
            source_note="REPAIR_CLOSE",
        )
        await self._repository.close_repair(
            repair_id,
            closed_by=closed_by,
            close_note=close_note,
            closed_snapshot_id=snapshot.meter_snapshot_id,
        )
        return await self.get_repair(repair_id)
