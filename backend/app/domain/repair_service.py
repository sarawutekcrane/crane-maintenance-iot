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

from app.domain.assignment import AssignmentRole
from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists
from app.domain.common import Page, PageParams, utc_now
from app.domain.meter_service import MeterService
from app.domain.notification import (
    AssignmentNotificationPayload,
    NoOpNotificationSink,
    NotificationPort,
)
from app.domain.part import PartActionType
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.domain.repair import RepairDetail, RepairSourceType, RepairStatus, RepairSummary
from app.errors import ApiError
from app.repositories.base import Repository


class RepairService:
    def __init__(
        self,
        repository: Repository,
        meter_service: MeterService,
        notification_sink: NotificationPort | None = None,
    ) -> None:
        self._repository = repository
        self._meter = meter_service
        self._notifications: NotificationPort = notification_sink or NoOpNotificationSink()

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
        await require_asset_exists(self._repository, asset_type, asset_id)
        await self._validate_source(source_type, source_id)
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
            primary_technician=primary_technician,
            collaborators=list(collaborators) if collaborators else [],
        )
        return await self.get_repair(repair.repair_id)

    async def assign(
        self,
        repair_id: str,
        primary_technician: str | None,
        collaborators: list[str] | None,
        assigned_by: str | None = None,
    ) -> RepairDetail:
        """Set/replace assignment (baseline REPAIR WORKFLOW CORRECTIONS
        section C: one primary technician plus zero or more collaborators).
        Not a production RBAC system — no permission check beyond the
        repair existing is enforced here (see module docstring). Technician
        identifiers reference `user_account.user_id` (Delta section G) —
        this service never creates a separate technician master."""
        await self.get_repair(repair_id)
        await self._repository.assign_repair(
            repair_id=repair_id,
            primary_technician=primary_technician,
            collaborators=list(collaborators) if collaborators else [],
            assigned_by=assigned_by,
        )
        detail = await self.get_repair(repair_id)
        if primary_technician:
            # REV05 section 7: "when Maintenance assigns a technician,
            # work immediately appears in that technician's งานของฉัน" is
            # already true the instant `assign_repair` above returns
            # (My Work reads live repair state) — this notification is an
            # additional, best-effort integration point only; its outcome
            # never affects whether the assignment above already
            # succeeded.
            await self._notify_assignment(detail)
        return detail

    async def _notify_assignment(self, detail: RepairDetail) -> None:
        repair = detail.repair
        original_reporter: str | None = None
        if repair.source_type == RepairSourceType.REPAIR_REQUEST and repair.source_id:
            source_request = await self._repository.get_repair_request(repair.source_id)
            original_reporter = source_request.reported_by_user_id if source_request else None
        location_snapshot_id: str | None = None
        if repair.meter_snapshot_id:
            snapshots = await self._repository.list_location_snapshots_for_event(
                repair.meter_snapshot_id
            )
            location_snapshot_id = snapshots[0].location_snapshot_id if snapshots else None
        attachment_ids = [
            attachment_id
            for action in detail.actions
            for attachment_id in action.attachment_ids
        ]
        payload = AssignmentNotificationPayload(
            repair_id=repair.repair_id,
            asset_type=repair.asset_type.value,
            asset_id=repair.asset_id,
            symptom=repair.symptom,
            priority=None,
            opened_by=repair.opened_by,
            original_reporter=original_reporter,
            opened_at=repair.opened_at,
            assigned_at=utc_now(),
            meter_snapshot_id=repair.meter_snapshot_id,
            location_snapshot_id=location_snapshot_id,
            attachment_ids=attachment_ids,
            source_type=repair.source_type.value,
            source_id=repair.source_id,
            route=f"/repairs/{repair.repair_id}",
            primary_technician=repair.primary_technician,
            collaborators=list(repair.collaborators),
        )
        try:
            await self._notifications.notify_assignment(payload)
        except Exception:  # noqa: BLE001 - assignment must never fail because of this
            pass

    async def list_assignment_history(self, repair_id: str):
        await self.get_repair(repair_id)
        return await self._repository.list_repair_assignment_history(repair_id)

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
        primary_technician: str | None = None
        collaborators: list[str] = []
        for entry in history:
            if not entry.active_status:
                continue
            if entry.assignment_role == AssignmentRole.PRIMARY:
                primary_technician = entry.user_id
            elif entry.assignment_role == AssignmentRole.COLLABORATOR:
                collaborators.append(entry.user_id)
        return primary_technician, collaborators

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
