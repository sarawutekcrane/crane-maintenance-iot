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

R3 (docs/project-governance/r3-implementation-contract.md §9–§10): a Work
Order opened from an R3 Finding (directly, or by converting a Repair Request
with that Finding's provenance) is an R3 Finding round (`finding_id`). At most
one active round per Finding; the lead technician submits completion (the
Finding episode ends, the order stays OPEN); the manager closes it only after
that completion (TS-4) or cancels it only before any recorded work (TS-7).
Every round is frozen after completion, closure or cancellation (T3, TS-6).
Non-R3 Work Orders keep their existing behaviour, apart from the T3 refusal of
new work on a CLOSED order.
"""
from __future__ import annotations

from fastapi import status

from app.domain.assignment import active_primary_and_collaborators
from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_for_new_work
from app.domain.authz import CAN_MANAGE_FINDING_REPAIR, require_capability
from app.domain.checklist import ABNORMAL_RESULTS
from app.domain.common import Page, PageParams
from app.domain.inspection import FindingStatus
from app.domain.legacy_assignment_retired import refuse_legacy_inline_assignee
from app.domain.meter_service import MeterService
from app.domain.notification import (
    NoOpNotificationSink,
    NotificationPort,
)
from app.domain.part import PartActionType
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.domain.r3_inspection import R3Conflict, has_active_repair
from app.domain.repair import Repair, RepairDetail, RepairSourceType, RepairStatus, RepairSummary
from app.domain.technician_assignment import (
    ASSIGNMENT_MODEL_LEGACY,
    REPAIR,
    STATUS_AMBIGUOUS,
    STATUS_VALID,
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
            result = await self._repository.find_inspection_result(source_id)
            found = result is not None
            if result is not None and result.item_key is not None and result.result in ABNORMAL_RESULTS:
                # R3 TS-5 (T2): an R3 abnormal result belongs to its Finding;
                # the round is opened from that Finding (manager / delegate).
                finding_id = next(
                    (f.finding_id for f in await self._repository.list_r3_findings()
                     if any(o.result_id == source_id for o in f.observations)), None)
                raise ApiError(
                    code="REPAIR_SOURCE_USE_FINDING",
                    message="This inspection result belongs to a Finding; open the repair round from the Finding",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"result_id": source_id, "finding_id": finding_id},
                )
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
        *,
        finding_id: str | None = None,
    ) -> RepairDetail:
        """`finding_id` (R3): the Finding a converted Repair Request carries in
        its server-built provenance. A direct FINDING source names its own."""
        # R2 Batch R2f-h4 B6 (D3): the legacy inline assignee (an opaque user_id)
        # is retired — refused before ANY read or write, never stored, never
        # read as a technician_id.
        refuse_legacy_inline_assignee(primary_technician, collaborators)
        await require_asset_for_new_work(self._repository, asset_type, asset_id)
        await self._validate_source(source_type, source_id)
        if source_type == RepairSourceType.FINDING and finding_id is None:
            finding_id = await self.r3_finding_id(source_id)
        if finding_id is not None:
            # R3 §9 P2: checked before any write (the repository re-checks atomically).
            await self.require_round_can_open(finding_id)
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

        try:
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
                finding_id=finding_id,
            )
        except R3Conflict as conflict:
            raise conflict.to_api_error() from conflict
        return await self.get_repair(repair.repair_id)

    # ---- R3 Finding rounds (contract §9–§10) ----

    async def r3_finding_id(self, finding_id: str | None) -> str | None:
        """The id when it names an R3 Finding; None for a pre-R3 finding (its
        accepted Phase 4 behaviour is unchanged — no round marker)."""
        if not finding_id:
            return None
        finding = await self._repository.find_inspection_finding(finding_id)
        return finding_id if finding is not None and finding.is_r3 else None

    async def require_round_can_open(self, finding_id: str) -> None:
        finding = await self._repository.find_inspection_finding(finding_id)
        if finding is None or finding.status != FindingStatus.OPEN:
            raise ApiError(code="FINDING_NOT_OPEN", message="A repair round can be opened only from an OPEN Finding",
                           status_code=status.HTTP_409_CONFLICT, details={"finding_id": finding_id})
        orders = await self._repository.list_repairs_for_finding(finding_id)
        if has_active_repair(orders):
            raise ApiError(
                code="FINDING_ACTIVE_REPAIR_EXISTS",
                message="This Finding already has an OPEN repair round",
                status_code=status.HTTP_409_CONFLICT,
                details={"finding_id": finding_id,
                         "repair_ids": sorted(o.repair_id for o in orders if o.status == RepairStatus.OPEN)},
            )

    @staticmethod
    def require_not_frozen(repair: Repair) -> None:
        """T3 / W3: a CLOSED, CANCELLED or completion-submitted order accepts
        no further repair work. Existing records are never altered."""
        if repair.status != RepairStatus.OPEN or repair.completion_submitted:
            raise ApiError(
                code="REPAIR_ROUND_FROZEN",
                message="This repair round accepts no further repair work",
                status_code=status.HTTP_409_CONFLICT,
                details={"repair_id": repair.repair_id, "status": repair.status.value,
                         "completion_submitted": repair.completion_submitted},
            )

    async def submit_completion(self, repair_id: str, context, *, request_id: str, expected_set_id: str | None,
                                note: str | None) -> tuple[RepairDetail, bool]:
        """W2 (Owner rule Q2): only the current V2 PRIMARY submits
        'ส่งงานซ่อมเสร็จ'. The Finding episode ends (E3); the order stays OPEN
        until the manager closes it. Idempotent on request_id."""
        detail = await self.get_repair(repair_id)
        repair = detail.repair
        if not repair.is_r3_round:
            raise ApiError(code="REPAIR_NOT_R3_ROUND", message="Completion submission applies to R3 Finding rounds",
                           status_code=status.HTTP_409_CONFLICT, details={"repair_id": repair_id})
        if repair.completion_submitted and repair.completion_request_id == request_id:
            return detail, True  # replay of the same intent: the repository re-checks the payload below
        technician_id, set_id = await TechnicianAssignmentService(self._repository, self._cutover)             .require_current_primary(REPAIR, repair, context.user_id, expected_set_id)
        try:
            await self._repository.submit_repair_completion(
                repair_id, submitted_by=context.user_id, technician_id=technician_id, set_id=set_id,
                request_id=request_id, note=(note or None),
            )
        except R3Conflict as conflict:
            raise conflict.to_api_error() from conflict
        return await self.get_repair(repair_id), False

    async def cancel_repair(self, repair_id: str, context, *, reason: str | None) -> RepairDetail:
        """W5 (O-2, Q4): an R3 Finding round, by the manager / delegate, with a
        reason, only while no repair work is recorded (TS-7, fail closed)."""
        require_capability(context, CAN_MANAGE_FINDING_REPAIR, "การยกเลิกใบงานซ่อม (cancel a repair round)")
        if not reason or not reason.strip():
            raise ApiError(code="REPAIR_CANCEL_REASON_REQUIRED", message="A cancellation reason is required",
                           status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        detail = await self.get_repair(repair_id)
        repair, actions, parts = detail.repair, detail.actions, detail.parts
        if not repair.is_r3_round:
            raise ApiError(code="REPAIR_CANCEL_NOT_ALLOWED", message="Only an R3 Finding round can be cancelled",
                           status_code=status.HTTP_409_CONFLICT, details={"repair_id": repair_id})
        if repair.status != RepairStatus.OPEN:
            raise ApiError(code="REPAIR_NOT_OPEN", message="Only an OPEN Work Order can be cancelled",
                           status_code=status.HTTP_409_CONFLICT,
                           details={"repair_id": repair_id, "status": repair.status.value})
        try:
            evidence = [a for a in await self._repository.list_attachments_for_source("REPAIR", repair_id)
                        if a.purpose.value == "REPAIR_EVIDENCE"]
        except RepositoryError as exc:
            raise ApiError(code="REPAIR_WORK_EVIDENCE_READ_FAILED", message="Recorded repair work could not be "
                           "read; nothing was cancelled", status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        if actions or parts or evidence or repair.completion_submitted:
            raise ApiError(
                code="REPAIR_WORK_ALREADY_STARTED",
                message="Repair work is already recorded for this round; it cannot be cancelled",
                status_code=status.HTTP_409_CONFLICT,
                details={"repair_id": repair_id, "actions": len(actions), "parts": len(parts),
                         "evidence": len(evidence), "completion_submitted": repair.completion_submitted},
            )
        try:
            await self._repository.cancel_repair(repair_id, cancelled_by=context.user_id, reason=reason.strip())
        except R3Conflict as conflict:
            raise conflict.to_api_error() from conflict
        return await self.get_repair(repair_id)

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
        await require_round_work_allowed(self._repository, self._cutover, (await self.get_repair(repair_id)).repair)
        if not action_text or not action_text.strip():
            raise ApiError(
                code="VALIDATION_ERROR",
                message="action_text must not be empty",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        try:
            await self._repository.add_repair_action(
                repair_id=repair_id, action_text=action_text, actor=actor, attachment_ids=list(attachment_ids)
            )
        except R3Conflict as conflict:
            raise conflict.to_api_error() from conflict
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
        await require_round_work_allowed(self._repository, self._cutover, (await self.get_repair(repair_id)).repair)
        if part_id is not None:
            await require_part_exists(self._repository, part_id)
        if part_instance_id is not None:
            await require_part_instance_exists(self._repository, part_instance_id)
        try:
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
        except R3Conflict as conflict:
            raise conflict.to_api_error() from conflict
        return await self.get_repair(repair_id)

    async def close_repair(
        self, repair_id: str, closed_by: str | None, close_note: str | None, context=None
    ) -> RepairDetail:
        detail = await self.get_repair(repair_id)
        if detail.repair.status == RepairStatus.CLOSED:
            raise ApiError(
                code="REPAIR_ALREADY_CLOSED",
                message=f"Repair '{repair_id}' is already closed",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if detail.repair.status == RepairStatus.CANCELLED:
            # R3 W5: no CANCELLED -> CLOSED transition.
            raise ApiError(code="REPAIR_NOT_OPEN", message=f"Repair '{repair_id}' was cancelled",
                           status_code=status.HTTP_409_CONFLICT,
                           details={"repair_id": repair_id, "status": detail.repair.status.value})
        if detail.repair.is_r3_round:
            # R3 C1 (O-3, T1): closing a Finding round needs the Finding authority too.
            if context is None:
                raise ApiError(code="R3_AUTHORIZED_ACTOR_REQUIRED", message="An R3 round needs an "
                               "authorized closer", status_code=status.HTTP_403_FORBIDDEN)
            require_capability(context, CAN_MANAGE_FINDING_REPAIR,
                               "การปิดใบงานซ่อมจากรายการผิดปกติ (close an R3 Finding round)")
            if not detail.repair.completion_submitted:
                # TS-4 (proposed mechanism): closure only after the lead's completion.
                raise ApiError(
                    code="REPAIR_COMPLETION_NOT_SUBMITTED",
                    message="The lead technician has not submitted completion for this repair round",
                    status_code=status.HTTP_409_CONFLICT,
                    details={"repair_id": repair_id},
                )
        snapshot = await self._meter.capture_current_state(
            asset_type=detail.repair.asset_type,
            asset_id=detail.repair.asset_id,
            recorded_by=closed_by,
            source_note="REPAIR_CLOSE",
        )
        try:
            await self._repository.close_repair(
                repair_id,
                closed_by=closed_by,
                close_note=close_note,
                closed_snapshot_id=snapshot.meter_snapshot_id,
            )
        except R3Conflict as conflict:
            raise conflict.to_api_error() from conflict
        return await self.get_repair(repair_id)


async def require_round_work_allowed(repository: Repository, cutover: AssignmentCutover, repair: Repair) -> None:
    """The single gate before recording repair work (an action, a part or a repair
    evidence photo): the round must not be frozen (T3 / TS-6) and, on an R3 Finding
    round, it must have a VALID current V2 team, i.e. exactly one PRIMARY (Owner rule
    L9). A round may be opened before its first assignment; no work is recorded until
    then. Non-R3 orders keep the accepted rules."""
    RepairService.require_not_frozen(repair)
    if not repair.is_r3_round:
        return
    state = (await TechnicianAssignmentService(repository, cutover).read(REPAIR, repair.repair_id)).state
    if state.status == STATUS_AMBIGUOUS:
        raise ApiError(code="TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", message="The current technician team cannot be "
                       "determined; no repair work was recorded", status_code=status.HTTP_409_CONFLICT,
                       details={"repair_id": repair.repair_id})
    if state.status != STATUS_VALID or state.current is None:
        raise ApiError(code="REPAIR_LEAD_NOT_ASSIGNED", message="Assign a technician team with a lead before "
                       "recording repair work", status_code=status.HTTP_409_CONFLICT,
                       details={"repair_id": repair.repair_id})
