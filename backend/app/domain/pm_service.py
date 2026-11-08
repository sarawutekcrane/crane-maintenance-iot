"""PM (preventive maintenance) domain service.

Owns every business rule Phase 4 is allowed to define without an approved
open decision (E01-E05 in OPEN_DECISIONS_REGISTER_EN.txt — see
`app.domain.pm` module docstring for the full explanation of each):

- which plans apply to an asset: same `asset_type`, and — when a plan
  declares `model_ids` — the vehicle's `model_id` must be in that list
  (metadata-only scope filter, not an assignment matrix),
- a PM work order is opened against the plan's currently active task
  revision; every task result it later receives is validated against
  that exact revision (never a newer one), and a task can only receive
  one result per work order — an existing result is never overwritten,
- closing a work order requires nothing beyond it existing and being
  open (no mandatory task-completion requirement is invented),
- a meter snapshot referenced by a task result is validated to exist via
  `MeterService`, which is itself where component/asset validation lives.
"""
from __future__ import annotations

import functools
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import status

from app.context import RequestContext
from app.domain.asset import AssetType
from app.domain.attachment import AttachmentPurpose
from app.domain.asset_lookup import require_asset_exists, require_asset_for_new_work
from app.domain.authz import CAN_MANAGE_PM, CAN_VIEW, require_capability
from app.domain.common import Page, PageParams
from app.domain.meter_service import MeterService
from app.domain.pm_meter_anchor import (
    NO_IOT_METER_SOURCE,
    PmSubmitMeterAnchor,
    is_vehicle,
    read_work_order_evidence,
    select_current_reading,
    select_submit_readings,
)
from app.domain.part import PartActionType
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.domain.pm import (
    PmE01ContractAction,
    PmItemContractDisposition,
    PmItemOutcome,
    PmOutstandingItem,
    PmOutstandingResolutionReference,
    PmWorkOrderTransition,
    PmWorkResult,
    assess_pm_contract_completion,
    build_pm_item_outcome,
    build_pm_outstanding_item,
    pm_e01_contract_transition,
    pm_e01_state,
    pm_item_outcome_id,
    pm_work_order_transition_fingerprint,
    PmPlan,
    PmPlanStatus,
    PmTaskRevisionDetail,
    PmTriggerType,
    PmWorkOrder,
    PmWorkOrderDetail,
    PmWorkOrderStatus,
    PmWorkOrderSummary,
)
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG, in_scope
from app.domain.registration import text
from app.domain.registry_write_support import error
from app.domain.request_replay import find_replay, request_fingerprint
from app.domain.requisition import RequisitionSourceType
from app.domain.technician_assignment import (
    ASSIGNMENT_MODEL_TECHNICIAN_V2,
    JOB_PREFIX,
    PM,
    AssignmentCutover,
    STATUS_AMBIGUOUS,
    TechnicianAssignmentService,
    assignment_model_of,
    model_mismatch,
    require_v2_write_context,
    require_v2_job_in_scope,
    v2_job_marker,
)
from app.domain.v2_read_scope import require_job_list_integrity, server_read_scope
from app.domain.repair import RepairSourceType, RepairStatus
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryFeatureNotImplementedError


# R4-PM-WF-01 B02-B2A: server-owned PM item vocabulary — the exact approved
# wording of Owner Agreements, R4 Final Contract FC-1 (Performed /
# Not Performed). Never supplied or extended by a caller; checked only through
# the B01 builder / validator.
PM_APPROVED_PERFORMED_ACTIONS: frozenset[str] = frozenset({
    "ตรวจเช็ค",
    "ทำความสะอาด",
    "เปลี่ยน / เติม",
})
PM_APPROVED_OTHER_REASON = "อื่น ๆ (ระบุ)"
PM_APPROVED_NOT_PERFORMED_REASONS: frozenset[str] = frozenset({
    "มีการเปลี่ยนอะไหล่แล้วในการซ่อมครั้งก่อน",
    "รออะไหล่",
    "พบความผิดปกติ รอซ่อม",
    "พื้นที่ไม่เพียงพอ",
    "เวลาไม่เพียงพอ",
    PM_APPROVED_OTHER_REASON,
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _work_order_operation(method):
    """R4 Google Sheets TEST persistence (C-1): run the WHOLE service operation
    (precondition reads and every write) under the repository's per-work-order
    operation lock L1, so two requests on one work order can never interleave
    between repository calls inside this backend process."""

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        pm_work_order_id = kwargs["pm_work_order_id"] if "pm_work_order_id" in kwargs else args[0]
        async with self._repository.pm_work_order_lock(pm_work_order_id):
            return await method(self, *args, **kwargs)

    return wrapper


@dataclass(frozen=True)
class PmItemOutcomeRecording:
    """One saved PM item: the factual `PmWorkResult` (parts, meter, evidence,
    Repair source) and the authoritative truthful `PmItemOutcome`, both read
    back and verified. `*_replayed` is True when the record already existed
    (identical retry or partial-write recovery). No Outstanding record is
    created at item save: Outstanding becomes effective only at CLOSE."""
    result: PmWorkResult
    outcome: PmItemOutcome
    result_replayed: bool
    outcome_replayed: bool


@dataclass(frozen=True)
class PmOutstandingState:
    """An effective Outstanding record (its source work order is CLOSED) and
    its single resolution, if any."""
    item: PmOutstandingItem
    resolution: PmOutstandingResolutionReference | None = None


def _vocabulary() -> dict:
    """The server-owned vocabulary, as B01 keyword arguments."""
    return {"approved_not_performed_reasons": PM_APPROVED_NOT_PERFORMED_REASONS,
            "approved_other_reason_code": PM_APPROVED_OTHER_REASON,
            "approved_performed_actions": PM_APPROVED_PERFORMED_ACTIONS}


def _rejected(exc: ValueError, http_status: int | None = None) -> ApiError:
    return ApiError(code=str(exc), message="The PM item outcome was rejected; nothing was changed",
                    status_code=http_status or status.HTTP_422_UNPROCESSABLE_ENTITY)


def _conflict(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_409_CONFLICT, details=details)


def _invalid(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


def _readback_mismatch(record: str) -> ApiError:
    return ApiError(code="PM_OUTCOME_READBACK_MISMATCH",
                    message=f"The stored {record} does not match what was written; not reported as recorded",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@dataclass(frozen=True)
class UsedPartInput:
    part_description: str
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None
    part_instance_id: str | None = None
    action: PartActionType | None = None


class PmService:
    def __init__(self, repository: Repository, meter_service: MeterService,
                 assignment_cutover: AssignmentCutover | None = None) -> None:
        self._repository = repository
        self._meter = meter_service
        # R2 Batch R2f-h1: the V2 cutover setting + server context (default OFF).
        self._cutover = assignment_cutover or AssignmentCutover()

    # ---- Plan / task revision ----

    async def list_applicable_plan_status(
        self, asset_type: AssetType, asset_id: str
    ) -> list[PmPlanStatus]:
        await require_asset_exists(self._repository, asset_type, asset_id)

        plans: list[PmPlan]
        if asset_type == AssetType.VEHICLE:
            # Core Demo Fixes, PM WORKFLOW REDESIGN section A — APPROVED
            # CORRECTION: a vehicle's PM plan comes from its model's own
            # single `assigned_pm_plan_id`, never from scanning every
            # plan's `model_ids` (which permitted an unintended many-to-
            # many mapping — see web-phase-04-result.md Section 31 risk
            # note). `None` means SOURCE-DATA-REQUIRED: no plan at all.
            vehicle = await self._repository.get_vehicle(asset_id)
            model = await self._repository.get_vehicle_model(vehicle.model_id) if vehicle else None
            assigned_plan_id = model.assigned_pm_plan_id if model else None
            if assigned_plan_id is None:
                plans = []
            else:
                plan = await self._repository.get_pm_plan(assigned_plan_id)
                plans = [plan] if plan is not None else []
        else:
            # Equipment has no model/assigned-plan concept in this branch
            # (C03 equipment counter/component model remains TBD-DEFERRED)
            # — unchanged from Phase 4's plan.model_ids-based filter.
            plans = await self._repository.list_pm_plans(asset_type=asset_type, model_id=None)

        statuses: list[PmPlanStatus] = []
        for plan in plans:
            revision_detail = await self._repository.get_active_pm_task_revision(plan.pm_plan_id)
            last_detail = await self._repository.get_last_closed_pm_work_order(
                asset_type=asset_type, asset_id=asset_id, pm_plan_id=plan.pm_plan_id
            )
            last_snapshot_id: str | None = None
            if last_detail is not None:
                for result in reversed(last_detail.results):
                    if result.meter_snapshot_id:
                        last_snapshot_id = result.meter_snapshot_id
                        break
            statuses.append(
                PmPlanStatus(
                    plan=plan,
                    active_revision=revision_detail.revision if revision_detail else None,
                    last_completed_work_order_id=(
                        last_detail.work_order.pm_work_order_id if last_detail else None
                    ),
                    last_completed_at=last_detail.work_order.closed_at if last_detail else None,
                    last_completed_meter_snapshot_id=last_snapshot_id,
                )
            )
        return statuses

    async def _require_plan(self, pm_plan_id: str) -> PmPlan:
        plan = await self._repository.get_pm_plan(pm_plan_id)
        if plan is None:
            raise ApiError(
                code="PM_PLAN_NOT_FOUND",
                message=f"PM plan '{pm_plan_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return plan

    async def get_active_task_revision(self, pm_plan_id: str) -> PmTaskRevisionDetail:
        await self._require_plan(pm_plan_id)
        detail = await self._repository.get_active_pm_task_revision(pm_plan_id)
        if detail is None:
            raise ApiError(
                code="NO_ACTIVE_PM_TASK_REVISION",
                message=f"No active PM task revision is configured for plan '{pm_plan_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def get_task_revision(self, pm_plan_id: str, revision_id: str) -> PmTaskRevisionDetail:
        detail = await self._repository.get_pm_task_revision(pm_plan_id, revision_id)
        if detail is None:
            raise ApiError(
                code="PM_TASK_REVISION_NOT_FOUND",
                message=f"PM task revision '{revision_id}' was not found for plan '{pm_plan_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    # ---- Work order ----

    async def open_work_order(
        self,
        asset_type: AssetType,
        asset_id: str,
        pm_plan_id: str,
        due_reason: PmTriggerType | None,
        opened_by: str | None,
        note: str | None,
        initial_scope_task_ids: list[str] | None = None,
    ) -> PmWorkOrderDetail:
        await require_asset_for_new_work(self._repository, asset_type, asset_id)
        plan = await self._require_plan(pm_plan_id)
        if plan.asset_type != asset_type:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=(
                    f"PM plan '{pm_plan_id}' applies to asset type "
                    f"'{plan.asset_type.value}', not '{asset_type.value}'"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if asset_type == AssetType.VEHICLE:
            # APPROVED CORRECTION: a user may never manually switch a
            # vehicle's PM work order to a plan other than its model's own
            # single assigned plan.
            vehicle = await self._repository.get_vehicle(asset_id)
            model = await self._repository.get_vehicle_model(vehicle.model_id) if vehicle else None
            assigned_plan_id = model.assigned_pm_plan_id if model else None
            if assigned_plan_id is None or assigned_plan_id != pm_plan_id:
                raise ApiError(
                    code="PM_PLAN_NOT_ASSIGNED_TO_MODEL",
                    message=(
                        f"Plan '{pm_plan_id}' is not the PM plan assigned to this vehicle's "
                        "model — a vehicle's PM work order must use only its model's own "
                        "assigned plan (SOURCE-DATA-REQUIRED if no mapping is configured)"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"assigned_pm_plan_id": assigned_plan_id},
                )
        revision_detail = await self.get_active_task_revision(pm_plan_id)

        all_task_ids = [t.pm_task_id for t in revision_detail.tasks]
        if initial_scope_task_ids is None:
            # No due-calculation exists in this branch (E02/E03/E04
            # unresolved) — default to every task in the active revision,
            # matching Phase 4's prior behavior exactly (non-breaking).
            scope_task_ids = all_task_ids
        else:
            unknown = set(initial_scope_task_ids) - set(all_task_ids)
            if unknown:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message="initial_scope_task_ids must all belong to this plan's active revision",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={"unknown_task_ids": sorted(unknown)},
                )
            scope_task_ids = list(initial_scope_task_ids)

        # R2 Batch R2f-h4 B6 Rev2 (owner final decision: V2 only): EVERY new PM
        # work order is a V2 job. After the input validation (as for the former
        # default) and before ANY write — the open-time snapshot included — the
        # data context and the extended-header proof; no legacy fallback.
        assignment_marker = await v2_job_marker(self._repository, PM, self._cutover)

        # Core Demo Fix: automatic machine-state snapshot at open time —
        # backend-derived, never a manually-typed browser field.
        snapshot = await self._meter.capture_current_state(
            asset_type=asset_type,
            asset_id=asset_id,
            recorded_by=opened_by,
            source_note="PM_WORK_ORDER_OPEN",
        )
        work_order = await self._repository.create_pm_work_order(
            asset_type=asset_type,
            asset_id=asset_id,
            pm_plan_id=pm_plan_id,
            revision_id=revision_detail.revision.revision_id,
            due_reason=due_reason,
            opened_by=opened_by,
            note=note,
            opened_snapshot_id=snapshot.meter_snapshot_id,
            scope_task_ids=scope_task_ids,
            assignment_marker=assignment_marker,
        )
        return await self.get_work_order(work_order.pm_work_order_id)

    # ---- R4 / TASK-010 D1: dormant B1 Master -> E01 -> per-Set Due bridge ----
    # No route reaches these methods. They import the bridge lazily, so the running
    # application never loads the PM Master (B1 firewall exception D1, OPEN-005).

    async def open_master_work_order(self, master, context: RequestContext | None, *, asset_id: str,
                                     plan_code: str, revision_number: int, selected_set_keys: list[str],
                                     request_id: str, due_reason: PmTriggerType | None = None,
                                     note: str | None = None, model_variants=None) -> PmWorkOrderDetail:
        """Open ONE E01 V2 Work Order for the selected Sets of one exact published
        Master revision, each with its complete Item list (`master` is the B1
        `PmMasterService`; its reads need `can_view`, opening needs `can_manage_pm`).
        The vehicle must be EXPLICITLY assigned to the Plan for every Set's assembly,
        and `model_variants` (a `ModelVariantSource`, OPEN-016) must give exactly the
        Sets' Master model variant for (the vehicle's registered model, this Plan).
        Its default proves nothing (no approved association is published), so every
        opening is refused.

        Idempotent per request id (`request_replay` contract): the same request
        returns the same Work Order; another payload is 409 REQUEST_ID_REUSED. The
        Work Order, its scope and its membership (and the revision's runtime
        catalogue) are one all-or-nothing repository write, so a failure never
        reports or leaves a Work Order without its membership; the client's retry
        either replays it or opens it. Two DIFFERENT request ids open two Work
        Orders (no duplicate-open policy is approved)."""
        from app.domain import pm_master_runtime as runtime

        context = self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การเปิดงาน PM จากแผนหลัก (open a Master-sourced PM work order)")
        request_id = request_id.strip() if isinstance(request_id, str) else ""
        if not request_id:
            raise _invalid("REQUEST_ID_REQUIRED", "A request id is required; nothing was changed")
        keys = list(selected_set_keys)
        body = {"plan_code": plan_code, "revision_number": revision_number, "selected_set_keys": keys,
                "due_reason": due_reason.value if due_reason is not None else None, "note": note}
        fingerprint = request_fingerprint(runtime.OP_PM_MASTER_WORK_ORDER_OPEN, asset_id, None, body)
        # In-process only: serializes retries of ONE request so they never capture a
        # second open-time snapshot. Across processes only the storage write decides.
        async with self._repository.pm_work_order_lock(f"{runtime.OP_PM_MASTER_WORK_ORDER_OPEN}:{request_id}"):
            marker = await v2_job_marker(self._repository, PM, self._cutover)
            scope = {k: marker[k] for k in ("is_test_data", "test_batch_id")}
            rows = [{"request_id": m.request_id, "request_fingerprint": m.request_fingerprint,
                     "pm_work_order_id": m.pm_work_order_id, "scope": (m.is_test_data, m.test_batch_id)}
                    for m in await self._repository.list_pm_master_memberships(request_id=request_id)]
            lookup = find_replay(rows, request_id, fingerprint, record_id_column="pm_work_order_id")
            if lookup is not None:
                if not lookup.replayed:
                    raise _conflict("REQUEST_ID_REUSED", "This request id was already used for a different request; "
                                    "nothing was changed", {"request_id": request_id})
                if lookup.rows[0]["scope"] != (scope["is_test_data"], scope["test_batch_id"]):
                    raise _conflict("TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH",
                                    "This request belongs to another data scope; nothing was changed")
                return await self.get_work_order(lookup.record_ids[0])

            if (not keys or not all(isinstance(k, str) and k.strip() for k in keys) or len(set(keys)) != len(keys)
                    or isinstance(revision_number, bool) or not isinstance(revision_number, int)
                    or revision_number < 1):
                raise _invalid("PM_MASTER_MAPPING_INVALID", "An explicit revision and distinct Set keys are "
                               "required; nothing was changed", {"selected_set_keys": keys})
            await require_asset_for_new_work(self._repository, AssetType.VEHICLE, asset_id)
            vehicle = await self._repository.get_vehicle(asset_id)
            model = await self._repository.get_vehicle_model(vehicle.model_id) if vehicle else None
            model_id = model.model_id if model is not None else ""
            snapshot = master.freeze_selection(context, plan_code, keys, revision_number=revision_number)
            revision = master.get_revision(context, plan_code, revision_number)
            for master_set in snapshot.sets:
                resolved = master.resolve_plan(context, asset_id, runtime.assembly_of(master_set))
                if (resolved.source, resolved.plan_code) != ("EXPLICIT_ASSIGNED", plan_code):
                    raise _invalid("PM_MASTER_PLAN_NOT_ASSIGNED", "The vehicle is not explicitly assigned to this "
                                   "Master Plan; nothing was changed",
                                   {"set_key": master_set.set_key, "plan_source": resolved.source})
                if not runtime.model_variant_proven(model_variants or runtime.no_proven_model_variant,
                                                    model_id=model_id, plan_code=plan_code,
                                                    model_variant=master_set.model_variant):
                    raise _invalid("PM_MASTER_MODEL_VARIANT_UNVERIFIED", "No approved association proves that this "
                                   "vehicle's model is the Set's Master model variant in this Plan; nothing was "
                                   "changed", {"set_key": master_set.set_key, "plan_code": plan_code,
                                               "model_variant": master_set.model_variant,
                                               "vehicle_model_id": model_id or None})
            try:
                catalogue = runtime.build_catalogue(revision)
                membership = runtime.build_membership(snapshot, asset_id=asset_id, vehicle_model_id=model_id,
                                                      request_id=request_id, fingerprint=fingerprint, scope=scope)
            except ValueError as exc:
                raise _invalid(str(exc), "The Master selection cannot be mapped to E01 tasks; "
                               "nothing was changed") from exc
            # Core Demo Fix (unchanged): the backend-derived open-time machine-state snapshot.
            opened = await self._meter.capture_current_state(asset_type=AssetType.VEHICLE, asset_id=asset_id,
                                                             recorded_by=context.user_id,
                                                             source_note="PM_WORK_ORDER_OPEN")
            try:
                work_order, _, _ = await self._repository.create_pm_master_work_order(
                    membership, catalogue, due_reason=due_reason, opened_by=context.user_id, note=note,
                    opened_snapshot_id=opened.meter_snapshot_id, assignment_marker=marker)
            except ValueError as exc:
                raise _conflict(str(exc), "The Master-sourced work order was not opened; nothing was changed") from exc
            return await self.get_work_order(work_order.pm_work_order_id)

    async def evaluate_master_set_due(self, context: RequestContext | None, *, asset_id: str,
                                      master_revision_id: str, set_key: str):
        """READ ONLY: the DUE-02A / DUE-01 decision of one Master Set (exact revision)
        on one vehicle, over the Master-sourced Work Orders of the server's data scope.
        The frozen Set comes only from stored membership checked against the stored
        catalogue; the engine is the vehicle's single component with the Set's role;
        Outcomes come through the authorized E01 read; the current meter is a verified
        IoT observation at evaluation time. Another revision's completions never
        count (no lineage continuity is approved). Anything unproven is UNKNOWN."""
        from app.domain import pm_master_runtime as runtime
        from app.domain.master_lifecycle import in_scope
        from app.domain.pm_due import PmDueDecision
        from app.domain.pm_due_evidence import (
            CurrentMeter,
            SetDueEvidenceDecision,
            evaluate_set_due,
        )

        context = self._require_trusted(context)
        data_context = await require_v2_write_context(self._cutover, self._repository)
        memberships = [m for m in await self._repository.list_pm_master_memberships(asset_id=asset_id)
                       if m.master_revision_id == master_revision_id and any(s.set_key == set_key for s in m.sets)
                       and in_scope({"is_test_data": m.is_test_data, "test_batch_id": m.test_batch_id},
                                    data_context, self._cutover.test_batch_id)]
        components = [(c.component_id, c.component_role.value)
                      for c in await self._repository.list_vehicle_components(asset_id)]
        vehicle = await self._repository.get_vehicle(asset_id)
        catalogue = (await self._repository.get_pm_task_revision(memberships[0].pm_plan_id, master_revision_id)
                     if memberships else None)
        frozen = runtime.frozen_set(memberships, set_key, catalogue, components,
                                    vehicle.model_id if vehicle is not None else None)
        if frozen is None:
            return SetDueEvidenceDecision(PmDueDecision(status="UNKNOWN", reason="NO_VERIFIED_ACTUAL_SET_COMPLETION"))
        work_orders = []
        for m in memberships:
            outcomes = await self.list_item_outcomes(m.pm_work_order_id, context)  # V2 + scope + authority
            work_orders.append(await read_work_order_evidence(
                self._repository, m.pm_work_order_id, outcomes=outcomes, v2_scope_verified=True,
                data_scope_verified=True))
        source, at = self._meter.iot_meter_source, _utcnow()
        reading = select_current_reading(await source.observations(asset_id, not_after=at), vehicle_id=asset_id,
                                         components=components, counter_type=frozen.meter_type,
                                         component_id=frozen.component_id, at=at,
                                         max_observation_age=source.max_observation_age)
        current = CurrentMeter(frozen.meter_type, frozen.component_id,
                               reading.value if reading is not None else None, reading is not None)
        return evaluate_set_due(frozen, tuple(work_orders), current)

    @_work_order_operation
    async def add_scope_task(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        reason: str,
        added_by: str | None,
    ) -> PmWorkOrderDetail:
        """Core Demo Fix section D: authorized addition of a near-due group
        from the SAME plan (guaranteed structurally: `pm_task_id` must
        belong to this work order's own revision, which belongs to exactly
        one plan). Caller (route layer) is responsible for the "authorized
        PM scope authority" gate — this service enforces only that scope is
        not already frozen and that the task is real."""
        if not reason or not reason.strip():
            raise ApiError(
                code="VALIDATION_ERROR",
                message="reason is required when manually adding a PM scope task",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        detail = await self.get_work_order(pm_work_order_id)
        await self._require_scope_editable(detail)
        if detail.work_order.scope_approved_at is not None:
            raise ApiError(
                code="PM_SCOPE_ALREADY_APPROVED",
                message="This work order's scope is approved/frozen and cannot be extended",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        revision_detail = await self._repository.get_pm_task_revision(
            detail.work_order.pm_plan_id, detail.work_order.revision_id
        )
        task_ids = {t.pm_task_id for t in revision_detail.tasks} if revision_detail else set()
        if pm_task_id not in task_ids:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=f"Task '{pm_task_id}' does not belong to this work order's own plan/revision",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if pm_task_id in detail.work_order.scope_task_ids:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=f"Task '{pm_task_id}' is already in this work order's scope",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        await self._repository.add_pm_scope_task(
            pm_work_order_id=pm_work_order_id, pm_task_id=pm_task_id, added_by=added_by, reason=reason
        )
        return await self.get_work_order(pm_work_order_id)

    @_work_order_operation
    async def approve_scope(
        self, pm_work_order_id: str, approved_by: str | None
    ) -> PmWorkOrderDetail:
        """Core Demo Fix section D: freeze the work order's selected
        group/task set. Section F / Delta section D: auto-generate one
        `MaterialRequest` header plus its `RequisitionLine`s (Store/
        Inventory integration boundary — see `app.domain.requisition`)
        from each in-scope task's standard `PmTaskPart` list. Never
        decrements any stock balance; no header is created when the
        approved scope has no standard parts at all (nothing to request)."""
        detail = await self.get_work_order(pm_work_order_id)
        await self._require_scope_editable(detail)
        if detail.work_order.scope_approved_at is not None:
            raise ApiError(
                code="PM_SCOPE_ALREADY_APPROVED",
                message="This work order's scope is already approved",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        revision_detail = await self._repository.get_pm_task_revision(
            detail.work_order.pm_plan_id, detail.work_order.revision_id
        )
        tasks_in_scope = (
            [t for t in revision_detail.tasks if t.pm_task_id in detail.work_order.scope_task_ids]
            if revision_detail
            else []
        )
        await self._repository.approve_pm_scope(pm_work_order_id, approved_by=approved_by)

        lines_to_create = [
            (task, part) for task in tasks_in_scope for part in task.standard_parts
        ]
        if lines_to_create:
            vehicle_id = (
                detail.work_order.asset_id if detail.work_order.asset_type == AssetType.VEHICLE else None
            )
            material_request = await self._repository.create_material_request(
                source_type=RequisitionSourceType.PM,
                source_work_order_id=pm_work_order_id,
                vehicle_id=vehicle_id,
                created_by=approved_by,
            )
            for task, part in lines_to_create:
                await self._repository.create_requisition_line(
                    material_request_id=material_request.material_request_id,
                    part_id=part.part_id,
                    part_instance_id=None,
                    part_code_snapshot=None,
                    part_description=part.part_description,
                    requested_quantity=part.quantity,
                    unit=part.unit,
                    source_task_revision_id=task.revision_id,
                    line_source="PM_STANDARD",
                    created_by=approved_by,
                )
        return await self.get_work_order(pm_work_order_id)

    async def list_requisition_lines(self, pm_work_order_id: str) -> list:
        await self.get_work_order(pm_work_order_id)
        return await self._repository.list_requisition_lines_for_work_order(pm_work_order_id)

    async def authorize_recording(self, pm_work_order_id: str, context, capability: str,
                                  action_description: str) -> None:
        """Technician V2 only (DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107):
        the capability, or current V2 set membership in scope. Any other job model
        fails closed (409 ASSIGNMENT_MODEL_MISMATCH / 500 for an unknown marker)."""
        detail = await self.get_work_order(pm_work_order_id)
        if assignment_model_of(detail.work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
            raise model_mismatch(ASSIGNMENT_MODEL_TECHNICIAN_V2)
        await TechnicianAssignmentService(self._repository, self._cutover).require_recording(
            PM, detail.work_order, context, capability, action_description)

    async def get_work_order(self, pm_work_order_id: str) -> PmWorkOrderDetail:
        detail = await self._repository.get_pm_work_order(pm_work_order_id)
        if detail is None:
            raise ApiError(
                code="PM_WORK_ORDER_NOT_FOUND",
                message=f"PM work order '{pm_work_order_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def list_work_orders(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
        status: PmWorkOrderStatus | None = None,
        assigned_to: str | None = None,
    ) -> Page[PmWorkOrderSummary]:
        items, total = await self._repository.list_pm_work_orders(
            asset_type=asset_type,
            asset_id=asset_id,
            params=params,
            status=status,
            assigned_to=assigned_to,
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    # ---- R4 / TASK-010 read security: the two PM Work Order read routes ----
    # Read only (no projection or reconcile). The internal `get_work_order` /
    # `list_work_orders` used by E01 and other operations stay unchanged.

    async def list_work_orders_for_reader(
        self,
        context: RequestContext | None,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
        status: PmWorkOrderStatus | None = None,
    ) -> Page[PmWorkOrderSummary]:
        """`GET /pm/work-orders`: `can_view` (the base read capability every
        recognized role holds), then the server's TEST/REAL context (503 before
        any read), then the stored records' integrity, then ONLY the work orders
        of that exact scope, filtered before ordering, counting and paging. A
        refusal or a failed read is an error, never an empty page."""
        context = self._require_trusted(context)
        require_capability(context, CAN_VIEW, "การอ่านรายการใบงาน PM (read PM work orders)")
        data_scope = await server_read_scope(self._cutover, self._repository)
        await self._require_pm_list_integrity()
        items, total = await self._repository.list_pm_work_orders(
            asset_type=asset_type, asset_id=asset_id, params=params, status=status, data_scope=data_scope)
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def _require_pm_list_integrity(self) -> None:
        """Whole-list fail closed (500, counts only, never an id): an unknown
        assignment model, a blank or duplicated work order id, or a V2 job whose
        scope cells cannot prove its scope. Same rules as the V2 queues; the
        shared R4 / TASK-010 read contract (`app.domain.v2_read_scope`)."""
        await require_job_list_integrity(self._repository, PM, "PM work order")

    async def get_work_order_for_reader(self, pm_work_order_id: str,
                                        context: RequestContext | None) -> PmWorkOrderDetail:
        """`GET /pm/work-orders/{id}` (Technician V2 only, DEC-ARCH-LEGACY-RUNTIME-
        CANCEL-CLEANUP-20261107). A trusted actor and the server's TEST/REAL
        context come first (403 / 503, before any record read). Then: a missing
        record, a blank (legacy) model or a V2 job outside that exact scope is the
        SAME 404 (existence is never disclosed); an unrecognized model or
        unprovable scope cells fail closed (500, no contents); finally
        `can_manage_pm` or current V2 team membership — the rule E01 Outcome reads
        and PM evidence use. Read only: no projection or reconcile."""
        context = self._require_trusted(context)
        data_context = await require_v2_write_context(self._cutover, self._repository)
        not_found = ApiError(code="PM_WORK_ORDER_NOT_FOUND", message=f"PM work order '{pm_work_order_id}' was not found",
                             status_code=status.HTTP_404_NOT_FOUND)
        detail = await self._repository.get_pm_work_order(pm_work_order_id)
        if detail is None:
            raise not_found
        work_order = detail.work_order
        if assignment_model_of(work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:  # unknown marker: 500 inside
            raise not_found
        flag, batch = text(work_order.is_test_data), text(work_order.test_batch_id)
        if flag not in (TEST_FLAG, OPERATIONAL_FLAG) or (flag == OPERATIONAL_FLAG and batch):
            raise error(f"{JOB_PREFIX}_DATA_INVALID", "The PM work order record cannot be trusted",
                        status.HTTP_500_INTERNAL_SERVER_ERROR, {"issues": {"JOB_SCOPE_FLAG_INVALID": 1}})
        if not in_scope({"is_test_data": flag, "test_batch_id": batch}, data_context, self._cutover.test_batch_id):
            raise not_found
        await TechnicianAssignmentService(self._repository, self._cutover).require_recording(
            PM, work_order, context, CAN_MANAGE_PM, "การอ่านใบงาน PM (read a PM work order)")
        return detail

    @staticmethod
    def _require_trusted(context: RequestContext | None) -> RequestContext:
        if not isinstance(context, RequestContext) or not (context.user_id or "").strip():
            raise ApiError(
                code="PM_OUTCOME_CONTEXT_REQUIRED",
                message="A trusted, authenticated request context is required",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return context

    async def _require_scope_editable(self, detail: PmWorkOrderDetail) -> None:
        """A V2 scope may change only before review (OPEN / IN_PROGRESS), judged
        on the authoritative journal status (EV-048: never a stale projection,
        since scope approval also creates Store requests)."""
        if assignment_model_of(detail.work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
            return
        current, _ = await self._current_status(detail)
        if current not in (PmWorkOrderStatus.OPEN, PmWorkOrderStatus.IN_PROGRESS):
            raise _conflict("PM_SCOPE_LOCKED", "The PM scope cannot change once the work order is submitted, "
                            "closed or cancelled")

    @asynccontextmanager
    async def linked_write_guard(self, pm_work_order_id: str, allowed: frozenset[PmWorkOrderStatus], code: str,
                                 message: str) -> AsyncIterator[PmWorkOrderDetail | None]:
        """EV-048 (RR-1): wrap a write by ANOTHER service that links a new record
        to a PM work order (PM evidence, a manual Store request).

        V2 work order: the caller's whole write runs under the SAME per-work-order
        lock L1 as every PM transition, and only while the AUTHORITATIVE status
        (journal-reconciled exactly as every PM operation does; any other
        disagreement fails closed) is in `allowed`; otherwise 409 `code` and
        nothing is written. So no linked record can appear between CANCEL's
        eligibility check and its transition, and a record written here is
        visible to the next CANCEL check. Legacy or missing work order: yields
        the detail (or None) without a lock; the caller keeps its own rules."""
        detail = await self._repository.get_pm_work_order(pm_work_order_id)
        if detail is None or assignment_model_of(detail.work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
            yield detail
            return
        async with self._repository.pm_work_order_lock(pm_work_order_id):
            fresh = await self._repository.get_pm_work_order(pm_work_order_id)
            if fresh is None:
                raise ApiError(code="PM_WORK_ORDER_NOT_FOUND",
                               message=f"PM work order '{pm_work_order_id}' was not found",
                               status_code=status.HTTP_404_NOT_FOUND)
            current, _ = await self._current_status(fresh)
            if current not in allowed:
                raise _conflict(code, message, {"pm_work_order_id": pm_work_order_id, "status": current.value})
            yield fresh

    async def _v2_detail(self, pm_work_order_id: str, context: RequestContext | None) -> PmWorkOrderDetail:
        """Trusted context, existing V2 work order, inside the server's TEST/REAL
        data scope — for every actor, `can_manage_pm` included."""
        self._require_trusted(context)
        detail = await self.get_work_order(pm_work_order_id)
        if assignment_model_of(detail.work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
            raise model_mismatch(ASSIGNMENT_MODEL_TECHNICIAN_V2)
        require_v2_job_in_scope(PM, detail.work_order,
                                await require_v2_write_context(self._cutover, self._repository),
                                self._cutover.test_batch_id)
        return detail

    async def _authorize_outcome_access(self, pm_work_order_id: str, context: RequestContext | None,
                                        action_description: str) -> PmWorkOrderDetail:
        detail = await self._v2_detail(pm_work_order_id, context)
        await TechnicianAssignmentService(self._repository, self._cutover).require_recording(
            PM, detail.work_order, context, CAN_MANAGE_PM, action_description)
        return detail

    # -- journal / projection --

    async def _current_status(self, detail: PmWorkOrderDetail
                              ) -> tuple[PmWorkOrderStatus, list[PmWorkOrderTransition]]:
        """The authoritative state from the journal. A projection that lags one
        event behind (interrupted write) is completed; any other disagreement
        fails closed and is never repaired silently."""
        pm_work_order_id = detail.work_order.pm_work_order_id
        journal = await self._repository.list_pm_work_order_transitions(pm_work_order_id)
        header = detail.work_order.status
        if not journal or journal[-1].to_status == header:
            return header, journal
        # C-1: the reconcile WRITES, so it runs under L1 and decides on a fresh
        # read taken inside the lock (another request may have just projected it).
        async with self._repository.pm_work_order_lock(pm_work_order_id):
            fresh = await self._repository.get_pm_work_order(pm_work_order_id)
            if fresh is None:
                raise ApiError(code="PM_WORK_ORDER_NOT_FOUND",
                               message=f"PM work order '{pm_work_order_id}' was not found",
                               status_code=status.HTTP_404_NOT_FOUND)
            journal = await self._repository.list_pm_work_order_transitions(pm_work_order_id)
            header = fresh.work_order.status
            if not journal or journal[-1].to_status == header:
                return header, journal
            last = journal[-1]
            if last.from_status != header:
                raise _conflict("PM_E01_STATE_INCONSISTENT",
                                "The work order status disagrees with its lifecycle history; nothing was changed")
            await self._project(fresh, last)
            return last.to_status, journal

    async def _project(self, detail: PmWorkOrderDetail, event: PmWorkOrderTransition) -> None:
        work_order = detail.work_order
        snapshot_id = None
        if event.to_status == PmWorkOrderStatus.CLOSED:
            snapshot_id = await self._close_snapshot_id(work_order, event)
        try:
            await self._repository.set_pm_work_order_status(
                work_order.pm_work_order_id, event.from_status, event.to_status, actor=event.actor,
                at=event.occurred_at, note=event.reason if event.to_status == PmWorkOrderStatus.CLOSED else None,
                closed_snapshot_id=snapshot_id)
        except ValueError as exc:
            raise _conflict(str(exc), "The work order status changed concurrently; nothing was changed") from exc
        readback = await self._repository.get_pm_work_order(work_order.pm_work_order_id)
        if (readback is None or readback.work_order.status != event.to_status
                or (snapshot_id is not None and readback.work_order.closed_snapshot_id != snapshot_id)):
            raise ApiError(code="PM_E01_READBACK_MISMATCH",
                           message="The stored work order status does not match the recorded transition",
                           status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    async def _close_snapshot_id(self, work_order: PmWorkOrder, event: PmWorkOrderTransition) -> str:
        """The one machine-state snapshot of a CLOSE event. The capture and the status
        compare-and-set are separate writes, so an interrupted projection may already have
        captured it: a retry reuses that capture when it is provably this event's own and
        complete, instead of capturing again. Otherwise a fresh capture is taken, as before;
        no capture is ever deleted or rewritten."""
        reused = await self._interrupted_close_capture(work_order, event)
        if reused is not None:
            return reused
        snapshot = await self._meter.capture_current_state(
            asset_type=work_order.asset_type, asset_id=work_order.asset_id,
            recorded_by=event.actor, source_note="PM_WORK_ORDER_CLOSE")
        return snapshot.meter_snapshot_id

    async def _interrupted_close_capture(self, work_order: PmWorkOrder,
                                         event: PmWorkOrderTransition) -> str | None:
        """The close capture an interrupted projection of `event` left behind, or None. It must
        be the only automatic PM close capture on the asset by the event's actor since the
        event, and no other work order on the asset may have produced it: an unfinished V2
        close, an open legacy job (its close attempts leave no trace), or a closed one whose own
        capture is not older than it (which also excludes every referenced capture). A VEHICLE
        capture must have its GPS half."""
        snapshots = await self._repository.list_meter_snapshots_for_asset(work_order.asset_type, work_order.asset_id)
        others, page = [], 1
        while True:
            rows, total = await self._repository.list_pm_work_orders(
                work_order.asset_type, work_order.asset_id, PageParams(page=page, page_size=200))
            for row in rows:
                if row.pm_work_order_id != work_order.pm_work_order_id:
                    other = await self._repository.get_pm_work_order(row.pm_work_order_id)
                    if other is not None:
                        others.append(other.work_order)
            if not rows or page * 200 >= total:
                break
            page += 1
        candidates = [s for s in snapshots if s.source_note == "PM_WORK_ORDER_CLOSE" and s.is_automatic
                      and s.recorded_by == event.actor and s.recorded_at >= event.occurred_at]
        if len(candidates) != 1:
            return None
        candidate = candidates[0]
        recorded = {s.meter_snapshot_id: s.recorded_at for s in snapshots}
        for other in others:
            if other.status == PmWorkOrderStatus.CANCELLED:
                continue
            if other.status == PmWorkOrderStatus.CLOSED:
                bound = recorded.get(other.closed_snapshot_id) if other.closed_snapshot_id else other.closed_at
                if bound is None or candidate.recorded_at <= bound:
                    return None
                continue
            if assignment_model_of(other) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
                return None
            other_journal = await self._repository.list_pm_work_order_transitions(other.pm_work_order_id)
            if other_journal and other_journal[-1].action == PmE01ContractAction.CLOSE:
                return None
        if work_order.asset_type == AssetType.VEHICLE and len(
                await self._repository.list_location_snapshots_for_event(candidate.meter_snapshot_id)) != 1:
            return None
        return candidate.meter_snapshot_id

    @staticmethod
    def _replay_of(journal: list[PmWorkOrderTransition], request_id: str, action: PmE01ContractAction,
                   fingerprint: str) -> PmWorkOrderTransition | None:
        for event in journal:
            if event.request_id == request_id:
                if event.action != action or event.request_fingerprint != fingerprint:
                    raise _conflict("PM_E01_REQUEST_CONFLICT",
                                    "This request id was already used for a different change; nothing was changed")
                return event
        return None

    async def _transition(self, detail: PmWorkOrderDetail, current: PmWorkOrderStatus,
                          action: PmE01ContractAction, context: RequestContext, request_id: str,
                          fingerprint: str, *, reason: str | None = None, **eligibility) -> PmWorkOrderDetail:
        """Validate with the B01 edge table, append the journal event, verify
        it, then project the status."""
        work_order = detail.work_order
        try:
            target = pm_e01_contract_transition(
                pm_e01_state(current), action, return_reason=reason, cancellation_reason=reason, **eligibility)
        except ValueError as exc:
            code = str(exc)
            if code == "PM_RETURN_REASON_REQUIRED":
                raise _invalid(code, "A reason is required to return the work order") from exc
            raise _conflict(code, f"{action.value} is not allowed from {current.value}; nothing was changed",
                            {"status": current.value}) from exc
        event = PmWorkOrderTransition(
            event_id="PMEV-" + hashlib.sha256(f"{work_order.pm_work_order_id}\x1f{request_id}".encode()).hexdigest()[:24],
            pm_work_order_id=work_order.pm_work_order_id, action=action, from_status=current,
            to_status=PmWorkOrderStatus(target.value), actor=context.user_id, occurred_at=_utcnow(),
            reason=(reason or "").strip() or None, request_id=request_id, request_fingerprint=fingerprint,
            is_test_data=work_order.is_test_data, test_batch_id=work_order.test_batch_id)
        try:
            stored, _ = await self._repository.append_pm_work_order_transition(event)
        except ValueError as exc:
            raise _conflict(str(exc), "The lifecycle history changed concurrently; nothing was changed") from exc
        journal = await self._repository.list_pm_work_order_transitions(work_order.pm_work_order_id)
        if not journal or journal[-1] != stored:
            raise ApiError(code="PM_E01_READBACK_MISMATCH",
                           message="The stored lifecycle event does not match what was written",
                           status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        await self._project(detail, stored)
        return await self.get_work_order(work_order.pm_work_order_id)

    async def _begin(self, pm_work_order_id: str, context: RequestContext | None, action: PmE01ContractAction,
                     request_id: str, fingerprint: str
                     ) -> tuple[PmWorkOrderDetail, PmWorkOrderStatus, PmWorkOrderTransition | None]:
        detail = await self._v2_detail(pm_work_order_id, context)
        if not (request_id or "").strip():
            raise _invalid("REQUEST_ID_REQUIRED", "A client request id is required for this change")
        current, journal = await self._current_status(detail)
        if current != detail.work_order.status:  # a lagging projection was just completed
            detail = await self.get_work_order(pm_work_order_id)
        return detail, current, self._replay_of(journal, request_id, action, fingerprint)

    @_work_order_operation
    async def start_work_order(self, pm_work_order_id: str, context: RequestContext | None, *,
                               request_id: str) -> PmWorkOrderDetail:
        """OPEN -> IN_PROGRESS: a current V2 member or `can_manage_pm`, and a
        current valid V2 assignment set must exist."""
        action = PmE01ContractAction.START
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, None)
        detail = await self._v2_detail(pm_work_order_id, context)
        assignment = TechnicianAssignmentService(self._repository, self._cutover)
        await assignment.require_recording(PM, detail.work_order, context, CAN_MANAGE_PM,
                                           "การเริ่มงาน PM (start a PM work order)")
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        state = (await assignment.read(PM, pm_work_order_id)).state
        if state.status == STATUS_AMBIGUOUS:
            raise _conflict("TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", "The current assignment set cannot be determined")
        if state.current is None:
            raise _conflict("PM_E01_ASSIGNMENT_REQUIRED",
                            "A current V2 technician assignment is required before work can start")
        return await self._transition(detail, current, action, context, request_id, fingerprint)

    @_work_order_operation
    async def submit_for_review(self, pm_work_order_id: str, context: RequestContext | None, *,
                                request_id: str, expected_set_id: str | None) -> PmWorkOrderDetail:
        """IN_PROGRESS -> PENDING_REVIEW: only the current V2 PRIMARY (no
        capability substitute), every in-scope item disposed, at least one
        genuinely PERFORMED."""
        action = PmE01ContractAction.SUBMIT
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, None, expected_set_id)
        detail = await self._v2_detail(pm_work_order_id, context)
        await self._require_current_primary(detail, context, expected_set_id)
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            # Completes an anchor the original request could not write (interrupted).
            await self._bind_submit_anchor(detail.work_order, replay, detail.work_order.status)
            return detail
        if current == PmWorkOrderStatus.IN_PROGRESS:
            await self._require_complete_accounting(detail)
        submitted = await self._transition(detail, current, action, context, request_id, fingerprint)
        event = next(e for e in await self._repository.list_pm_work_order_transitions(pm_work_order_id)
                     if e.request_id == request_id)
        await self._bind_submit_anchor(detail.work_order, event, submitted.work_order.status)
        return submitted

    async def _bind_submit_anchor(self, work_order: PmWorkOrder, event: PmWorkOrderTransition,
                                  status_now: PmWorkOrderStatus) -> None:
        """DEC-R4-TASK010-PM-TECH-SUBMIT-ANCHOR-003: bind the verified IoT cumulative
        readings to exactly this technician SUBMIT event, once (write-once by event id;
        never overwritten, never re-bound at CLOSE). Readings are chosen against the
        event's own time and receipt cut-off, so a replay selects the same ones. With
        no IoT source, a non-vehicle asset or an adapter without anchor storage nothing
        is bound and Due stays UNKNOWN; a source or storage failure is raised so the
        client's retry (a replay of this request) completes it."""
        source = self._meter.iot_meter_source
        if source is NO_IOT_METER_SOURCE or event.action != PmE01ContractAction.SUBMIT \
                or not is_vehicle(work_order.asset_type):
            return
        try:
            if await self._repository.get_pm_submit_meter_anchor(event.event_id) is not None:
                return
        except RepositoryFeatureNotImplementedError:
            return
        try:
            observations = await source.observations(work_order.asset_id, not_after=event.occurred_at)
            components = [(c.component_id, c.component_role.value)
                          for c in await self._repository.list_vehicle_components(work_order.asset_id)]
            window = source.max_observation_age
            anchor = PmSubmitMeterAnchor(
                pm_work_order_id=work_order.pm_work_order_id, submit_event_id=event.event_id,
                submitted_at=event.occurred_at, asset_type=work_order.asset_type.value,
                asset_id=work_order.asset_id, max_observation_age=window or timedelta(0),
                readings=select_submit_readings(observations, vehicle_id=work_order.asset_id,
                                                components=components, submitted_at=event.occurred_at,
                                                max_observation_age=window),
                is_test_data=work_order.is_test_data, test_batch_id=work_order.test_batch_id)
            await self._repository.create_pm_submit_meter_anchor(anchor)
        except ValueError as exc:
            raise _conflict(str(exc), "The meter anchor of this submission could not be recorded") from exc
        except ApiError:
            raise
        except Exception as exc:  # IoT / storage failure AFTER the SUBMIT was recorded
            # The journal SUBMIT and its status are already persisted: say so, never a bare 500
            # that reads as "not submitted". The client's retry with the SAME request id is a
            # replay that only completes this anchor; Due stays UNKNOWN until then.
            raise ApiError(
                code="PM_SUBMIT_METER_ANCHOR_PENDING",
                message="The submission was recorded, but its meter evidence could not be recorded yet; "
                        "retry with the same request id",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"submission_recorded": True, "status": status_now.value,
                         "submit_event_id": event.event_id, "request_id": event.request_id,
                         "failure": type(exc).__name__}) from exc

    @_work_order_operation
    async def return_for_rework(self, pm_work_order_id: str, context: RequestContext | None, *,
                                request_id: str, reason: str | None) -> PmWorkOrderDetail:
        """PENDING_REVIEW -> IN_PROGRESS with a mandatory reason; saved items
        and the earlier history are never changed."""
        action = PmE01ContractAction.RETURN
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, reason)
        self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การส่งคืนงาน PM ให้แก้ไข (return a PM work order)")
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        return await self._transition(detail, current, action, context, request_id, fingerprint, reason=reason)

    @_work_order_operation
    async def close_after_review(self, pm_work_order_id: str, context: RequestContext | None, *,
                                 request_id: str, note: str | None = None) -> PmWorkOrderDetail:
        """PENDING_REVIEW -> CLOSED by `can_manage_pm`. Each NOT_PERFORMED item
        becomes exactly one effective Outstanding record, created from its
        stored Outcome before the CLOSED event is recorded."""
        action = PmE01ContractAction.CLOSE
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, note)
        self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การปิดใบสั่งงาน PM (final PM Work Order closure)")
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        if current == PmWorkOrderStatus.PENDING_REVIEW:
            outcomes = await self._require_complete_accounting(detail)
            for outcome in outcomes:
                if outcome.disposition == PmItemContractDisposition.NOT_PERFORMED:
                    await self._store_outstanding_from(outcome, context.user_id)
        return await self._transition(detail, current, action, context, request_id, fingerprint, reason=note)

    @_work_order_operation
    async def cancel_work_order(self, pm_work_order_id: str, context: RequestContext | None, *,
                                request_id: str, reason: str | None) -> PmWorkOrderDetail:
        """OPEN / IN_PROGRESS -> CANCELLED by `can_manage_pm`, with a reason,
        only with no PM result, Outcome, PM evidence or Store request at all.
        Nothing linked is changed or deleted."""
        action = PmE01ContractAction.CANCEL
        fingerprint = pm_work_order_transition_fingerprint(pm_work_order_id, action, reason)
        self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การยกเลิกใบสั่งงาน PM (cancel a PM work order)")
        detail, current, replay = await self._begin(pm_work_order_id, context, action, request_id, fingerprint)
        if replay is not None:
            return detail
        outcomes = await self._repository.list_pm_item_outcomes(pm_work_order_id)
        evidence = await self._repository.list_attachments_for_source("PM_WORK_ORDER", pm_work_order_id)
        store_requests = await self._repository.list_material_requests_for_work_order(pm_work_order_id)
        store_lines = await self._repository.list_requisition_lines_for_work_order(pm_work_order_id)
        blockers = [name for name, present in (("PM_RESULT", detail.results), ("PM_ITEM_OUTCOME", outcomes),
                                               ("PM_EVIDENCE", evidence), ("STORE_REQUEST", store_requests),
                                               ("STORE_REQUISITION_LINE", store_lines)) if present]
        if blockers and (reason or "").strip() and current in (PmWorkOrderStatus.OPEN, PmWorkOrderStatus.IN_PROGRESS):
            raise _conflict("PM_CANCEL_NOT_ELIGIBLE", "This work order already has PM work, evidence or Store "
                            "requests and cannot be cancelled; nothing was changed", {"blockers": blockers})
        performed = sum(1 for o in outcomes if o.disposition == PmItemContractDisposition.PERFORMED)
        return await self._transition(
            detail, current, action, context, request_id, fingerprint, reason=reason,
            cancellation_eligibility_proven=not store_requests and not store_lines,
            actual_performed_count=performed, existing_result_count=len(detail.results) + len(outcomes),
            existing_evidence_count=len(evidence))

    async def _require_current_primary(self, detail: PmWorkOrderDetail, context: RequestContext,
                                       expected_set_id: str | None) -> None:
        codes = {"REPAIR_COMPLETION_LEAD_ONLY": "PM_SUBMIT_PRIMARY_ONLY",
                 "REPAIR_LEAD_NOT_ASSIGNED": "PM_E01_ASSIGNMENT_REQUIRED",
                 "REPAIR_ACTOR_NOT_ELIGIBLE": "PM_SUBMIT_ACTOR_NOT_ELIGIBLE",
                 "REPAIR_ASSIGNMENT_STALE": "PM_ASSIGNMENT_STALE"}
        try:
            await TechnicianAssignmentService(self._repository, self._cutover).require_current_primary(
                PM, detail.work_order, context.user_id, expected_set_id, context)
        except ApiError as exc:
            if exc.code not in codes:
                raise
            raise ApiError(code=codes[exc.code], message="Only the current V2 PRIMARY technician of this PM work "
                           "order may submit it for review", status_code=exc.status_code, details=exc.details) from exc

    async def _require_complete_accounting(self, detail: PmWorkOrderDetail) -> list[PmItemOutcome]:
        """Every in-scope item saved completely (result + Outcome, linked), and
        at least one genuinely PERFORMED; otherwise no submit or close."""
        work_order = detail.work_order
        outcomes = await self._repository.list_pm_item_outcomes(work_order.pm_work_order_id)
        results = {r.pm_work_result_id: r for r in detail.results}
        linked = {o.source_pm_work_result_id for o in outcomes}
        incomplete = sorted({o.pm_task_id for o in outcomes
                             if o.source_pm_work_result_id not in results
                             or results[o.source_pm_work_result_id].pm_task_id != o.pm_task_id}
                            | {r.pm_task_id for r in detail.results if r.pm_work_result_id not in linked})
        if incomplete:
            raise _conflict("PM_E01_ITEM_RECORD_INCOMPLETE", "Some PM items were not saved completely; save them "
                            "again before review", {"pm_task_ids": incomplete})
        performed = tuple(o.pm_task_id for o in outcomes if o.disposition == PmItemContractDisposition.PERFORMED)
        not_performed = tuple(o.pm_task_id for o in outcomes
                              if o.disposition == PmItemContractDisposition.NOT_PERFORMED)
        try:
            assess_pm_contract_completion(in_scope_task_ids=tuple(work_order.scope_task_ids),
                                          performed_task_ids=performed, accounted_not_performed_ids=not_performed)
        except ValueError as exc:
            missing = sorted(set(work_order.scope_task_ids) - set(performed) - set(not_performed))
            raise _invalid(str(exc), "Every in-scope PM item must be Performed or Not Performed with a reason, "
                           "and at least one must be genuinely Performed", {"missing_pm_task_ids": missing}) from exc
        return outcomes

    # -- reads --

    async def list_item_outcomes(self, pm_work_order_id: str,
                                 context: RequestContext | None) -> list[PmItemOutcome]:
        await self._authorize_outcome_access(
            pm_work_order_id, context, "การอ่านผลการปฏิบัติงาน PM (read PM item outcomes)")
        return await self._repository.list_pm_item_outcomes(pm_work_order_id)

    async def list_work_order_history(self, pm_work_order_id: str,
                                      context: RequestContext | None) -> list[PmWorkOrderTransition]:
        detail = await self._authorize_outcome_access(
            pm_work_order_id, context, "การอ่านประวัติสถานะงาน PM (read PM work order history)")
        await self._current_status(detail)
        return await self._repository.list_pm_work_order_transitions(pm_work_order_id)

    async def list_outstanding_items(self, pm_work_order_id: str,
                                     context: RequestContext | None) -> list[PmOutstandingState]:
        """Effective Outstanding records of one work order: none until it is
        CLOSED (an interrupted close never surfaces partial records)."""
        detail = await self._authorize_outcome_access(
            pm_work_order_id, context, "การอ่านงาน PM ค้าง (read PM Outstanding items)")
        current, _ = await self._current_status(detail)
        if current != PmWorkOrderStatus.CLOSED:
            return []
        return [await self._outstanding_state(i)
                for i in await self._repository.list_pm_outstanding_items(pm_work_order_id)]

    async def list_asset_outstanding(self, asset_type: AssetType, asset_id: str,
                                     context: RequestContext | None) -> list[PmOutstandingState]:
        """The post-PM Outstanding backlog of one asset (separate from Due):
        effective records of in-scope CLOSED V2 work orders only."""
        self._require_trusted(context)
        data_context = await require_v2_write_context(self._cutover, self._repository)
        states = []
        for item in await self._repository.list_pm_outstanding_items_for_asset(asset_type, asset_id):
            detail = await self._repository.get_pm_work_order(item.pm_work_order_id)
            if detail is None or assignment_model_of(detail.work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
                continue
            try:
                require_v2_job_in_scope(PM, detail.work_order, data_context, self._cutover.test_batch_id)
            except ApiError:
                continue
            if (await self._current_status(detail))[0] == PmWorkOrderStatus.CLOSED:
                states.append(await self._outstanding_state(item))
        return states

    async def get_outstanding_item(self, outstanding_id: str) -> PmOutstandingItem:
        item = await self._repository.get_pm_outstanding_item(outstanding_id)
        if item is None:
            raise ApiError(code="PM_OUTSTANDING_NOT_FOUND", message=f"Outstanding item '{outstanding_id}' was not "
                           "found", status_code=status.HTTP_404_NOT_FOUND)
        return item

    async def _outstanding_state(self, item: PmOutstandingItem) -> PmOutstandingState:
        return PmOutstandingState(item=item,
                                  resolution=await self._repository.get_pm_outstanding_resolution(item.outstanding_id))

    # -- item save --

    @_work_order_operation
    async def record_item_outcome(
        self,
        pm_work_order_id: str,
        pm_task_id: str,
        disposition: PmItemContractDisposition,
        context: RequestContext | None,
        *,
        performed_actions: tuple[str, ...] = (),
        reason_code: str | None = None,
        other_text: str | None = None,
        evidence_attachment_ids: tuple[str, ...] = (),
        remark: str | None = None,
        meter_snapshot_id: str | None = None,
        used_parts: tuple[UsedPartInput, ...] = (),
    ) -> PmItemOutcomeRecording:
        """Save one PM item while IN_PROGRESS: one factual `PmWorkResult`
        (`completed` written from the stated disposition, never the other way
        round) and one truthful `PmItemOutcome` referencing it.

        The actor is always `context.user_id`, never a caller-supplied id, and
        no caller-supplied list is ever an approved vocabulary. A
        NOT_PERFORMED item can be saved only after at least one genuinely
        PERFORMED item is saved (before that it stays an unsaved draft).
        Success is returned only after both records are read back and verified;
        a retry with the same payload completes a partially saved item."""
        detail = await self._authorize_outcome_access(
            pm_work_order_id, context, "การบันทึกผลการปฏิบัติงาน PM (record a PM item outcome)")
        work_order = detail.work_order
        current, _ = await self._current_status(detail)
        if current != PmWorkOrderStatus.IN_PROGRESS:
            raise _conflict("PM_E01_ITEM_SAVE_NOT_ALLOWED", "PM items can be saved only while the work order is "
                            "IN_PROGRESS", {"status": current.value})
        if not isinstance(disposition, PmItemContractDisposition):
            raise _invalid("VALIDATION_ERROR", "disposition must be PERFORMED or NOT_PERFORMED")
        revision_detail = await self._repository.get_pm_task_revision(work_order.pm_plan_id,
                                                                      work_order.revision_id)
        if revision_detail is None or revision_detail.revision.revision_id != work_order.revision_id:
            raise ApiError(
                code="PM_TASK_REVISION_NOT_FOUND",
                message="The frozen task revision of this work order cannot be read",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        task = next((t for t in revision_detail.tasks if t.pm_task_id == pm_task_id), None)
        if task is None:
            raise _invalid("VALIDATION_ERROR",
                           f"Task '{pm_task_id}' does not belong to this work order's task revision",
                           {"pm_task_id": pm_task_id})
        if pm_task_id not in work_order.scope_task_ids:
            raise _invalid("PM_TASK_NOT_IN_SCOPE", f"Task '{pm_task_id}' is not in this work order's selected "
                           "scope", {"pm_task_id": pm_task_id})
        for attachment_id in evidence_attachment_ids:
            attachment = await self._repository.get_attachment(attachment_id) if (attachment_id or "").strip() else None
            if (attachment is None or attachment.purpose != AttachmentPurpose.PM_EVIDENCE
                    or attachment.source_type != "PM_WORK_ORDER" or attachment.source_id != pm_work_order_id):
                raise _invalid("PM_OUTCOME_EVIDENCE_INVALID",
                               "Every evidence attachment must be existing PM evidence of this work order",
                               {"attachment_id": attachment_id})
        for part in used_parts:
            if part.part_id is not None:
                await require_part_exists(self._repository, part.part_id)
            if part.part_instance_id is not None:
                await require_part_instance_exists(self._repository, part.part_instance_id)
        candidate = self._build_outcome(work_order, pm_task_id, disposition, context, performed_actions,
                                        reason_code, other_text, evidence_attachment_ids, _utcnow(), None)
        stored_outcome = await self._repository.get_pm_item_outcome(candidate.outcome_id)
        if disposition == PmItemContractDisposition.NOT_PERFORMED and stored_outcome is None and not any(
            o.disposition == PmItemContractDisposition.PERFORMED
            for o in await self._repository.list_pm_item_outcomes(pm_work_order_id)
        ):
            raise _invalid("PM_NOT_PERFORMED_REQUIRES_PERFORMED_FIRST",
                           "Save at least one genuinely Performed item before saving a Not Performed item")
        completed = disposition == PmItemContractDisposition.PERFORMED
        parts = [{"part_description": p.part_description, "quantity": p.quantity, "unit": p.unit,
                  "part_id": p.part_id, "part_instance_id": p.part_instance_id, "action": p.action}
                 for p in used_parts]
        result = next((r for r in detail.results if r.pm_task_id == pm_task_id), None)
        result_replayed = result is not None
        if result is not None:
            same = (result.completed == completed and result.remark == remark
                    and result.evidence_attachment_ids == list(evidence_attachment_ids)
                    and result.performed_by == context.user_id
                    and (meter_snapshot_id is None or result.meter_snapshot_id == meter_snapshot_id)
                    and [(u.part_description, u.quantity, u.unit, u.part_id, u.part_instance_id, u.action)
                         for u in result.used_parts]
                    == [(p["part_description"], p["quantity"], p["unit"], p["part_id"], p["part_instance_id"],
                         p["action"]) for p in parts])
            if not same:
                raise _conflict("PM_OUTCOME_CONFLICT",
                                "A different result is already saved for this item; nothing was changed")
        else:
            if meter_snapshot_id is not None:
                await self._meter.require_snapshot_exists(meter_snapshot_id)
            else:
                snapshot = await self._meter.capture_current_state(
                    asset_type=work_order.asset_type, asset_id=work_order.asset_id,
                    recorded_by=context.user_id, source_note="PM_TASK_RESULT")
                meter_snapshot_id = snapshot.meter_snapshot_id
            written = await self._repository.create_pm_work_result(
                pm_work_order_id=pm_work_order_id, pm_task_id=pm_task_id, revision_id=work_order.revision_id,
                sequence=task.sequence, task_description=task.description, completed=completed,
                meter_snapshot_id=meter_snapshot_id, remark=remark, used_parts=parts,
                evidence_attachment_ids=list(evidence_attachment_ids), performed_by=context.user_id)
            result = await self._repository.find_pm_work_result(written.pm_work_result_id)
            if result is None or result != written:
                raise _readback_mismatch("PM work result")
        candidate = self._build_outcome(work_order, pm_task_id, disposition, context, performed_actions,
                                        reason_code, other_text, evidence_attachment_ids, result.performed_at,
                                        result.pm_work_result_id)
        outcome, outcome_replayed = await self._store_item_outcome(candidate)
        return PmItemOutcomeRecording(result=result, outcome=outcome, result_replayed=result_replayed,
                                      outcome_replayed=outcome_replayed)

    @staticmethod
    def _build_outcome(work_order, pm_task_id: str, disposition: PmItemContractDisposition,
                       context: RequestContext, performed_actions, reason_code, other_text,
                       evidence_attachment_ids, recorded_at: datetime, result_id: str | None) -> PmItemOutcome:
        try:
            return build_pm_item_outcome(
                pm_work_order_id=work_order.pm_work_order_id, pm_task_id=pm_task_id,
                revision_id=work_order.revision_id, disposition=disposition, recorded_at=recorded_at,
                performed_actions=tuple(performed_actions), reason_code=reason_code, other_text=other_text,
                evidence_attachment_ids=tuple(evidence_attachment_ids), recorded_by=context.user_id,
                source_pm_work_result_id=result_id, **_vocabulary())
        except ValueError as exc:
            raise _rejected(exc) from exc

    async def _store_item_outcome(self, candidate: PmItemOutcome) -> tuple[PmItemOutcome, bool]:
        """Store `candidate` once, or reuse the stored Outcome of the same
        identity when it is identical. Any difference — actor included — is a
        conflict, so a reused Outcome always equals a candidate the B01 builder
        accepted."""
        stored = await self._repository.get_pm_item_outcome(candidate.outcome_id)
        if stored is not None:
            if stored != candidate:
                raise ApiError(code="PM_OUTCOME_CONFLICT",
                               message="A different outcome is already recorded for this item; nothing was changed",
                               status_code=status.HTTP_409_CONFLICT)
            return stored, True
        try:
            await self._repository.create_pm_item_outcome(candidate)
        except ValueError as exc:
            raise _rejected(exc, status.HTTP_409_CONFLICT) from exc
        readback = await self._repository.get_pm_item_outcome(candidate.outcome_id)
        if readback != candidate:
            raise _readback_mismatch("PM item outcome")
        return readback, False

    async def _store_outstanding_from(self, outcome: PmItemOutcome,
                                      created_by: str) -> tuple[PmOutstandingItem, bool]:
        """Build the Outstanding record only from the stored NOT_PERFORMED
        Outcome, store it once and verify its provenance against that Outcome."""
        try:
            item = build_pm_outstanding_item(outcome, created_by=created_by, created_at=_utcnow())
        except ValueError as exc:
            raise _rejected(exc, status.HTTP_409_CONFLICT) from exc
        try:
            _, replayed = await self._repository.create_pm_outstanding_item(item)
        except ValueError as exc:
            raise _rejected(exc, status.HTTP_409_CONFLICT) from exc
        readback = await self._repository.get_pm_outstanding_item(item.outstanding_id)
        if (readback is None or readback.creation_fingerprint != item.creation_fingerprint
                or (not replayed and readback != item)
                or readback.source_identity != outcome.source_identity
                or (readback.origin_reason_code, readback.origin_other_text, readback.origin_recorded_by,
                    readback.origin_recorded_at, readback.origin_pm_work_result_id)
                != (outcome.reason_code, outcome.other_text, outcome.recorded_by, outcome.recorded_at,
                    outcome.source_pm_work_result_id)):
            raise _readback_mismatch("PM Outstanding record")
        return readback, replayed

    # -- Outstanding resolution --

    async def resolve_outstanding(
        self,
        outstanding_id: str,
        context: RequestContext | None,
        *,
        later_pm_work_result_id: str | None = None,
        later_repair_id: str | None = None,
        evidence_attachment_ids: tuple[str, ...] = (),
    ) -> tuple[PmOutstandingResolutionReference, bool]:
        """Resolve exactly one effective Outstanding record with verified proof
        of later actual work on that item: a later CLOSED V2 PM work order with
        a genuinely PERFORMED Outcome for the same task (evidence from that
        Outcome), or a CLOSED Repair raised from this item's own PM result
        (evidence from that Repair). Nothing else is changed."""
        self._require_trusted(context)
        require_capability(context, CAN_MANAGE_PM, "การปิดงาน PM ค้าง (resolve a PM Outstanding item)")
        item = await self._repository.get_pm_outstanding_item(outstanding_id)
        if item is None:
            raise ApiError(code="PM_OUTSTANDING_NOT_FOUND", message=f"Outstanding item '{outstanding_id}' was not "
                           "found", status_code=status.HTTP_404_NOT_FOUND)
        source = await self._v2_detail(item.pm_work_order_id, context)
        if (await self._current_status(source))[0] != PmWorkOrderStatus.CLOSED:
            raise _conflict("PM_OUTSTANDING_NOT_EFFECTIVE", "This item is not an effective Outstanding obligation")
        evidence = tuple(evidence_attachment_ids)
        if bool((later_pm_work_result_id or "").strip()) == bool((later_repair_id or "").strip()):
            raise _invalid("PM_RESOLUTION_REFERENCE_SOURCE_INVALID",
                           "Name exactly one later PM result or one later Repair")
        if not evidence or not all((e or "").strip() for e in evidence):
            raise _invalid("PM_RESOLUTION_REFERENCE_EVIDENCE_REQUIRED", "Evidence of the actual work is required")
        if later_pm_work_result_id:
            await self._verify_later_pm(item, source, later_pm_work_result_id, evidence, context)
        else:
            await self._verify_later_repair(item, source, later_repair_id, evidence)
        resolution = PmOutstandingResolutionReference(
            outstanding_id=outstanding_id, later_pm_work_result_id=later_pm_work_result_id or None,
            later_repair_id=later_repair_id or None, evidence_attachment_ids=evidence,
            referenced_by=context.user_id, referenced_at=_utcnow())
        try:
            stored, replayed = await self._repository.create_pm_outstanding_resolution(resolution)
        except ValueError as exc:
            raise _rejected(exc, status.HTTP_409_CONFLICT) from exc
        readback = await self._repository.get_pm_outstanding_resolution(outstanding_id)
        if readback is None or readback != stored or (
                readback.model_dump(exclude={"referenced_at"}) != resolution.model_dump(exclude={"referenced_at"})):
            raise _readback_mismatch("PM Outstanding resolution")
        return readback, replayed

    def _evidence_error(self, message: str) -> ApiError:
        return _invalid("PM_RESOLUTION_EVIDENCE_INVALID", message)

    async def _verify_later_pm(self, item: PmOutstandingItem, source: PmWorkOrderDetail, result_id: str,
                               evidence: tuple[str, ...], context: RequestContext) -> None:
        result = await self._repository.find_pm_work_result(result_id)
        if result is None or result.pm_work_order_id == item.pm_work_order_id:
            raise self._evidence_error("The later PM result must exist on a different PM work order")
        later = await self._v2_detail(result.pm_work_order_id, context)
        if (later.work_order.asset_type, later.work_order.asset_id) != (
                source.work_order.asset_type, source.work_order.asset_id):
            raise self._evidence_error("The later PM work order is on a different asset")
        if (await self._current_status(later))[0] != PmWorkOrderStatus.CLOSED:
            raise self._evidence_error("The later PM work order is not CLOSED")
        if result.pm_task_id != item.pm_task_id:
            raise self._evidence_error("The later PM result is for a different PM item")
        outcome = await self._repository.get_pm_item_outcome(
            pm_item_outcome_id(later.work_order.pm_work_order_id, result.pm_task_id, later.work_order.revision_id))
        if (outcome is None or outcome.disposition != PmItemContractDisposition.PERFORMED
                or outcome.source_pm_work_result_id != result.pm_work_result_id):
            raise self._evidence_error("The later PM item was not genuinely Performed")
        if outcome.recorded_at <= item.created_at:
            raise self._evidence_error("The later PM work does not postdate the Outstanding item")
        if not set(evidence) <= set(outcome.evidence_attachment_ids):
            raise self._evidence_error("Evidence must be the later PM item's own evidence")

    async def _verify_later_repair(self, item: PmOutstandingItem, source: PmWorkOrderDetail, repair_id: str,
                                   evidence: tuple[str, ...]) -> None:
        detail = await self._repository.get_repair(repair_id)
        repair = detail.repair if detail is not None else None
        if repair is None:
            raise self._evidence_error("The later Repair does not exist")
        if (repair.asset_type, repair.asset_id) != (source.work_order.asset_type, source.work_order.asset_id):
            raise self._evidence_error("The Repair is on a different asset")
        if repair.status != RepairStatus.CLOSED or repair.closed_at is None:
            raise self._evidence_error("The Repair is not CLOSED")
        origin = item.origin_pm_work_result_id
        related = origin is not None and repair.source_type == RepairSourceType.PM_RESULT and repair.source_id == origin
        if not related and origin is not None and repair.source_type == RepairSourceType.REPAIR_REQUEST:
            request = await self._repository.get_repair_request(repair.source_id) if repair.source_id else None
            related = (request is not None and request.source_type == RepairSourceType.PM_RESULT.value
                       and request.source_id == origin and request.repair_id == repair.repair_id)
        if not related:
            raise self._evidence_error("The Repair was not raised from this Outstanding PM item")
        if repair.closed_at <= item.origin_recorded_at:
            raise self._evidence_error("The Repair work does not postdate the Not Performed item")
        for attachment_id in evidence:
            attachment = await self._repository.get_attachment(attachment_id)
            if (attachment is None or attachment.purpose != AttachmentPurpose.REPAIR_EVIDENCE
                    or attachment.source_type != "REPAIR" or attachment.source_id != repair.repair_id):
                raise self._evidence_error("Evidence must be this Repair's own evidence")
