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
from app.domain.common import OperationalStatus, Page, PageParams
from app.domain.meter_service import MeterService
from app.domain.pm_meter_anchor import (
    NO_IOT_METER_SOURCE,
    PmSubmitMeterAnchor,
    is_vehicle,
    select_current_reading,
    select_submit_readings,
    work_order_evidence,
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
    scope_cells,
    v2_job_marker,
)
from app.domain.v2_read_scope import require_job_list_integrity, server_read_scope
from app.domain.vehicle import Vehicle
from app.domain.vehicle_service import VehicleService, vehicle_master_read_error
from app.domain.repair import RepairSourceType, RepairStatus
from app.errors import ApiError
from app.repositories.base import (
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
)


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


def _e01_event_id(pm_work_order_id: str, request_id: str) -> str:
    """The deterministic E01 journal event id of one client request on one work
    order (the idempotency identity every recorded transition carries)."""
    return "PMEV-" + hashlib.sha256(f"{pm_work_order_id}\x1f{request_id}".encode()).hexdigest()[:24]


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


def _pm_read_invalid(issue: str) -> ApiError:
    """R4 PM Read Safety B1: a stored PM record a read depends on cannot be
    trusted. The whole read fails closed (500); only the issue code is
    reported, never a record id."""
    return ApiError(code="PM_WORK_ORDER_DATA_INVALID",
                    message="A stored PM record cannot be trusted; nothing is returned",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, details={"issues": {issue: 1}})


def _state_inconsistent() -> ApiError:
    return _conflict("PM_E01_STATE_INCONSISTENT",
                     "The work order status disagrees with its lifecycle history; nothing was changed")


def _transition_incomplete() -> ApiError:
    """R4 PM Read Safety B1: the E01 journal holds a change that the stored
    work order does not show yet (an interrupted write). A read never
    completes it; only an authorized PM operation recovers it."""
    return _conflict("PM_E01_TRANSITION_INCOMPLETE",
                     "The work order's last lifecycle change has not been completed yet; it is not reported "
                     "until an authorized PM operation completes it. Nothing was changed")


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


# ---- R4 / TASK-010 Fleet PM Due B1: the canonical read model ----
# One backend read model for the fleet list and the vehicle view; the frontend only
# displays it. Status is DUE / NOT_DUE / UNKNOWN (no warning window). `diagnostic_code`
# is the internal DUE-01 / DUE-02A reason: an UNSTABLE support diagnostic, NOT an API
# enum; clients show `explanation` and never branch on the code.

# RT3-A R2: the Master runtime Plan id prefix (`pm_master_runtime.RUNTIME_PLAN_PREFIX`),
# kept here so a seed-catalogue read never imports the Master modules (firewall).
_MASTER_RUNTIME_PLAN_PREFIX = "PMMP-"

PM_DUE_MASTER_NOT_ACTIVE = "MASTER_NOT_ACTIVE"
PM_DUE_NO_ASSIGNED_PLAN = "NO_ASSIGNED_PLAN"
PM_DUE_AVAILABLE = "AVAILABLE"

_VEHICLE_STATE_EXPLANATIONS = {
    PM_DUE_MASTER_NOT_ACTIVE: "ระบบแผน PM หลัก (PM Master) ยังไม่เปิดใช้งาน จึงยังคำนวณกำหนด PM ไม่ได้ "
                              "(ไม่ได้หมายความว่าไม่มี PM ถึงกำหนด)",
    PM_DUE_NO_ASSIGNED_PLAN: "รถคันนี้ยังไม่ได้รับการกำหนดแผน PM หลักอย่างชัดเจน จึงยังคำนวณกำหนด PM ไม่ได้",
    PM_DUE_AVAILABLE: "แสดงกำหนด PM ตามแผนหลักที่กำหนดให้รถคันนี้",
}
_PLAN_STATE_EXPLANATIONS = {
    "NOT_PUBLISHED": "แผนที่กำหนดยังไม่มีฉบับที่เผยแพร่",
    "MODEL_VARIANT_UNVERIFIED": "ยังไม่มีการจับคู่รุ่นรถกับรุ่นในแผนหลักที่อนุมัติ (หรือมีมากกว่าหนึ่ง) จึงไม่แสดงชุดงาน",
    "NO_APPLICABLE_SET": "แผนฉบับปัจจุบันไม่มีชุดงานสำหรับรุ่นและส่วนประกอบที่กำหนดให้รถคันนี้",
    "RESOLVED": "ชุดงานตามแผนฉบับปัจจุบัน",
}
_SET_STATUS_EXPLANATIONS = {"DUE": "ถึงกำหนด PM แล้ว", "NOT_DUE": "ยังไม่ถึงกำหนด PM"}
_UNKNOWN_EXPLANATIONS = {
    "NO_VERIFIED_ACTUAL_SET_COMPLETION": "ยังไม่มีหลักฐานการทำ PM ครบทั้งชุดที่ยืนยันได้ในแผนฉบับนี้ "
                                         "จึงยังไม่มีจุดอ้างอิงรอบล่าสุด",
    "CURRENT_METER_UNVERIFIED": "ไม่มีค่ามิเตอร์ปัจจุบันจาก IoT ที่ยืนยันได้",
    "PHYSICAL_ENGINE_UNVERIFIED": "ระบุเครื่องยนต์จริงของชุดงานนี้ไม่ได้ (ไม่มี หรือมีมากกว่าหนึ่งเครื่อง)",
    "PM_METER_NOT_APPROVED": "ประเภทมิเตอร์ของชุดงานนี้ไม่ใช่ตัวกำหนดรอบ PM ที่อนุมัติ",
    "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED": "มีใบงานที่ปิดแล้ว แต่ยืนยันหลักฐานมิเตอร์ ณ เวลาที่ช่างส่งงานไม่ได้",
    "COMPLETION_METER_DECREASE_UNRESOLVED": "ค่ามิเตอร์ของการทำ PM ลดลงระหว่างรอบ ต้องตรวจสอบ",
    "COUNTER_DECREASE_UNRESOLVED": "ค่ามิเตอร์ปัจจุบันต่ำกว่าค่าตอนทำ PM ครั้งล่าสุด ต้องตรวจสอบ",
    "LATEST_SET_COMPLETION_AMBIGUOUS": "การทำ PM ครั้งล่าสุดของชุดงานนี้กำกวม",
    "FROZEN_SET_ITEM_MAPPING_UNVERIFIED": "ยืนยันการจับคู่ชุดงานในใบงานกับแผนหลักไม่ได้",
}
_UNKNOWN_FALLBACK = "ยังยืนยันสถานะกำหนด PM ไม่ได้"


def _set_explanation(status_value: str, reason: str | None) -> str:
    if status_value in _SET_STATUS_EXPLANATIONS:
        return _SET_STATUS_EXPLANATIONS[status_value]
    return _UNKNOWN_EXPLANATIONS.get(reason or "", _UNKNOWN_FALLBACK)


@dataclass(frozen=True)
class PmDueAssignment:
    assembly: str  # "" = the whole vehicle
    source: str  # EXPLICIT_ASSIGNED | EXPLICIT_NONE | ABSENT
    plan_code: str | None


@dataclass(frozen=True)
class PmDuePlan:
    plan_code: str
    state: str
    revision_number: int | None
    model_variant: str | None
    explanation: str


@dataclass(frozen=True)
class PmDueSet:
    plan_code: str
    revision_number: int
    set_key: str
    model_variant: str
    section: str
    set_code: str
    meter_type: str
    interval_value: float
    interval_unit: str
    driving_component_role: str | None
    component_id: str | None
    status: str  # DUE | NOT_DUE | UNKNOWN
    explanation: str
    diagnostic_code: str | None
    next_due: float | None
    last_completed_meter: float | None
    last_completed_at: datetime | None
    last_completed_pm_work_order_id: str | None
    current_meter: float | None
    current_observed_at: datetime | None


@dataclass(frozen=True)
class VehiclePmDue:
    vehicle_id: str
    machine_no: str
    model_id: str
    state: str
    explanation: str
    assignments: tuple[PmDueAssignment, ...] = ()
    plans: tuple[PmDuePlan, ...] = ()
    sets: tuple[PmDueSet, ...] = ()


@dataclass
class _PmDueReadCache:
    """Per-request read cache: each Master head, model, catalogue and Work Order's
    verified evidence is read once, however many vehicles or Sets share it."""

    at: datetime
    heads: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)
    catalogues: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)


class PmService:
    # R4 / TASK-010 Fleet PM Due B1: the B1 Master reads (`effective_revision`,
    # `resolve_plan`) and the OPEN-016 model-variant source. None in the application
    # (`dependencies.get_pm_service` never calls `with_master_reads`): the Master stays
    # dormant and unloaded and the PM Due read answers MASTER_NOT_ACTIVE.
    _pm_master = None
    _model_variants = None

    def __init__(self, repository: Repository, meter_service: MeterService,
                 assignment_cutover: AssignmentCutover | None = None) -> None:
        self._repository = repository
        self._meter = meter_service
        # R2 Batch R2f-h1: the V2 cutover setting + server context (default OFF).
        self._cutover = assignment_cutover or AssignmentCutover()

    def with_master_reads(self, pm_master, model_variants) -> PmService:
        """TEST-ONLY dependency injection (Fleet PM Due B1): a NEW service over the same
        repository, meter service and cutover that reads the given synthetic B1 Master
        (`effective_revision` / `resolve_plan`, both `can_view`) and OPEN-016 variant
        source. The constructor contract is unchanged and this instance is never
        mutated; no application module calls it (OPEN-005 / OPEN-016 stay closed).
        RT1: the Master is read only while `_master_bound` (server scope + repository
        identity), checked on every read; otherwise the Due read is MASTER_NOT_ACTIVE."""
        clone = PmService(self._repository, self._meter, self._cutover)
        clone._pm_master, clone._model_variants = pm_master, model_variants
        return clone

    def _master_bound(self, master, data_scope: tuple[str, str]) -> bool:
        """RT1 (G1 + G2): a Master the runtime may read or open work from. Its store's
        TEST/REAL scope was fixed at creation (`MasterDataScope`) and must equal the
        server's own scope cells EXACTLY (so TEST batch A is never visible to batch B or
        REAL), and its assignment resolver must read THIS service's repository object
        (identity, never an equal class, seed or vehicle id). An unbound, invalid or
        foreign Master is never treated as REAL or as matching: it is not bound."""
        return (self._master_scope_is(master, data_scope)
                and getattr(master, "vehicle_repository", None) is self._repository)

    @staticmethod
    def _variant_source(master, context: RequestContext, explicit):
        """RT2 (OPEN-016): the model-variant source for a BOUND Master (callers check
        `_master_bound` first). An explicit `model_variants` is the existing TEST-only
        seam; otherwise the Master's own approved associations (`model_variant_source`,
        `can_view`), which live in its scope-bound store; with neither, nothing is
        proven (`no_proven_model_variant`)."""
        from app.domain import pm_master_runtime as runtime

        if explicit is not None:
            return explicit
        source = getattr(master, "model_variant_source", None)
        return source(context) if source is not None else runtime.no_proven_model_variant

    @staticmethod
    def _master_scope_is(master, data_scope: tuple[str, str]) -> bool:
        """The Master store's fixed scope cells equal `data_scope` (None/unbound never does)."""
        return getattr(getattr(master, "data_scope", None), "cells", None) == tuple(data_scope)

    # ---- Plan / task revision ----

    async def list_applicable_plan_status(
        self, asset_type: AssetType, asset_id: str, context: RequestContext | None
    ) -> list[PmPlanStatus]:
        """`GET /pm/plans/status` (R4 PM Read Safety B1). A trusted actor with
        `can_view` (Access Management resolves it per request), then the
        server's TEST/REAL context (503), then the stored job records' integrity
        (500, counts only), all before any protected asset or work order read.

        The last CLOSED work order of each applicable plan is taken ONLY from
        Technician V2 work orders of exactly that server scope (Legacy, other
        TEST batches and REAL/TEST crossover never count). Equal close times are
        broken by the persisted work order id. A chosen work order whose stored
        record cannot prove a completed CLOSE (no close time, missing record,
        header or close snapshot disagreeing with its E01 journal) fails the whole
        read closed: no completion or meter history is ever guessed, and a plan
        without a proven completion keeps its truthful UNKNOWN / None values.
        Read only: no projection, capture or audit write."""
        context = self._require_trusted(context)
        require_capability(context, CAN_VIEW, "การอ่านสถานะแผน PM (read PM plan status)")
        data_scope = await server_read_scope(self._cutover, self._repository)
        await self._require_pm_list_integrity()
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

        closed = await self._scoped_closed_work_orders(asset_type, asset_id, data_scope) if plans else []
        expected = (asset_type, asset_id, data_scope)
        statuses: list[PmPlanStatus] = []
        for plan in plans:
            revision_detail = await self._repository.get_active_pm_task_revision(plan.pm_plan_id)
            last_detail = await self._last_completed(closed, plan.pm_plan_id, expected)
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

    async def _scoped_closed_work_orders(self, asset_type: AssetType, asset_id: str,
                                         data_scope: tuple[str, str]) -> list[PmWorkOrderSummary]:
        """Every CLOSED Technician V2 work order of this asset in exactly the
        server scope (the repository's shared `in_v2_read_scope` filter). A CLOSED
        record without a close time cannot prove when it completed: fail closed."""
        closed: list[PmWorkOrderSummary] = []
        page = 1
        while True:
            rows, total = await self._repository.list_pm_work_orders(
                asset_type, asset_id, PageParams(page=page, page_size=200), data_scope=data_scope)
            closed.extend(r for r in rows if r.status == PmWorkOrderStatus.CLOSED)
            if not rows or page * 200 >= total:
                break
            page += 1
        if any(r.closed_at is None for r in closed):
            raise _pm_read_invalid("CLOSED_AT_MISSING")
        return closed

    async def _last_completed(self, closed: list[PmWorkOrderSummary], pm_plan_id: str,
                              expected: tuple[AssetType, str, tuple[str, str]]) -> PmWorkOrderDetail | None:
        """The latest proven completion of one plan: newest close time, ties
        broken by the persisted work order id (deterministic). Its record must
        still exist and match its scoped summary (asset, plan, Technician V2,
        exact server TEST/REAL cells), still be CLOSED with that close time, and
        agree with its E01 journal and close evidence (verified read only, never
        projected)."""
        candidates = [r for r in closed if r.pm_plan_id == pm_plan_id]
        if not candidates:
            return None
        latest = max(candidates, key=lambda r: (r.closed_at, r.pm_work_order_id))
        detail = await self._repository.get_pm_work_order(latest.pm_work_order_id)
        if detail is None:
            raise _pm_read_invalid("WORK_ORDER_REFERENCE_MISSING")
        work_order = detail.work_order
        asset_type, asset_id, data_scope = expected
        if (work_order.pm_work_order_id != latest.pm_work_order_id
                or (work_order.asset_type, work_order.asset_id, work_order.pm_plan_id)
                != (asset_type, asset_id, pm_plan_id)
                or text(work_order.assignment_model) != ASSIGNMENT_MODEL_TECHNICIAN_V2
                or (text(work_order.is_test_data), text(work_order.test_batch_id)) != data_scope):
            raise _pm_read_invalid("WORK_ORDER_RECORD_MISMATCH")
        if work_order.status != PmWorkOrderStatus.CLOSED or work_order.closed_at != latest.closed_at:
            raise _pm_read_invalid("WORK_ORDER_RECORD_INCONSISTENT")
        current, journal = await self._read_only_status(detail)
        if current != PmWorkOrderStatus.CLOSED or not journal or journal[-1].action != PmE01ContractAction.CLOSE:
            raise _pm_read_invalid("WORK_ORDER_RECORD_INCONSISTENT")
        return detail

    async def _require_plan(self, pm_plan_id: str) -> PmPlan:
        plan = await self._repository.get_pm_plan(pm_plan_id)
        if plan is None:
            raise ApiError(
                code="PM_PLAN_NOT_FOUND",
                message=f"PM plan '{pm_plan_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return plan

    async def _require_master_catalogue_in_scope(self, pm_plan_id: str, not_found: ApiError) -> None:
        """RT3-A R2 (scope isolation only): a MASTER runtime catalogue (`PMMP-` Plan id)
        is read only when its Plan id is exactly the one its Plan code has in the
        SERVER's own TEST/REAL scope (`_pm_read_context`, 503 when unconfigured, never
        REAL by default). A foreign scope's (or an older, unscoped) Master catalogue is
        reported exactly as missing (`not_found`), so nothing about it is disclosed.
        The Plan id itself is never proof: it is recomputed from the stored Plan code.
        Phase-4 seed catalogues are not Master catalogues and are unaffected. This is
        NOT access authorization: the route still has no `can_view` check (see the
        RT3-A result); the production Master firewall stays the activation barrier."""
        if not pm_plan_id.startswith(_MASTER_RUNTIME_PLAN_PREFIX):
            return
        # Lazy: only a Master catalogue read loads the runtime module (firewall).
        from app.domain import pm_master_runtime as runtime

        _, (flag, batch) = await self._pm_read_context()
        plan = await self._repository.get_pm_plan(pm_plan_id)
        if plan is None or runtime.runtime_plan_id_in_scope(plan.plan_code, flag, batch) != pm_plan_id:
            raise not_found

    async def get_active_task_revision(self, pm_plan_id: str) -> PmTaskRevisionDetail:
        await self._require_master_catalogue_in_scope(pm_plan_id, ApiError(
            code="PM_PLAN_NOT_FOUND", message=f"PM plan '{pm_plan_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND))
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
        not_found = ApiError(
            code="PM_TASK_REVISION_NOT_FOUND",
            message=f"PM task revision '{revision_id}' was not found for plan '{pm_plan_id}'",
            status_code=status.HTTP_404_NOT_FOUND,
        )
        await self._require_master_catalogue_in_scope(pm_plan_id, not_found)
        # A revision is returned only under its own Plan id (repository contract), so a
        # foreign revision id under an in-scope Plan id is missing too.
        detail = await self._repository.get_pm_task_revision(pm_plan_id, revision_id)
        if detail is None:
            raise not_found
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
        RT2: by default (no explicit TEST source) it is the bound Master's own approved
        associations; with none approved, every opening is refused. RT1: the Master
        must also be bound to the server's exact TEST/REAL scope (409
        PM_MASTER_SCOPE_MISMATCH) and resolve assignments against this repository
        object (409 PM_MASTER_REPOSITORY_MISMATCH), checked before any replay, read or
        write, so a replay never bypasses it.

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
            # RT1: before any replay, read or write, the Master must be bound to the
            # server's exact scope and to this repository object (nothing disclosed).
            cells = (scope["is_test_data"], scope["test_batch_id"])
            if not self._master_scope_is(master, cells):
                raise _conflict("PM_MASTER_SCOPE_MISMATCH", "The PM Master is not bound to this server's data "
                                "scope; nothing was changed")
            if not self._master_bound(master, cells):
                raise _conflict("PM_MASTER_REPOSITORY_MISMATCH", "The PM Master's vehicle assignments were not "
                                "resolved against this repository; nothing was changed")
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
            variants = self._variant_source(master, context, model_variants)
            snapshot = master.freeze_selection(context, plan_code, keys, revision_number=revision_number)
            revision = master.get_revision(context, plan_code, revision_number)
            for master_set in snapshot.sets:
                resolved = master.resolve_plan(context, asset_id, runtime.assembly_of(master_set))
                if (resolved.source, resolved.plan_code) != ("EXPLICIT_ASSIGNED", plan_code):
                    raise _invalid("PM_MASTER_PLAN_NOT_ASSIGNED", "The vehicle is not explicitly assigned to this "
                                   "Master Plan; nothing was changed",
                                   {"set_key": master_set.set_key, "plan_source": resolved.source})
                if not runtime.model_variant_proven(variants,
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
        each Work Order needs the E01 Outcome read authority (`_authorize_outcome_access`,
        the `list_item_outcomes` contract) and its evidence passes the R3 E01 read
        integrity checks (`_verified_due_evidence`); the current meter is a verified
        IoT observation at evaluation time. Another revision's completions never
        count (no lineage continuity is approved). Anything unproven is UNKNOWN."""
        from app.domain import pm_master_runtime as runtime
        from app.domain.pm_due import PmDueDecision
        from app.domain.pm_due_evidence import (
            CurrentMeter,
            SetDueEvidenceDecision,
            evaluate_set_due,
        )

        context = self._require_trusted(context)
        require_capability(context, CAN_VIEW, "การอ่านกำหนด PM (read PM Due)")
        data_context, data_scope = await self._pm_read_context()
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
            await self._authorize_outcome_access(  # V2 + scope + the E01 Outcome read authority
                m.pm_work_order_id, context, "การอ่านผลการปฏิบัติงาน PM (read PM item outcomes)")
            work_orders.append(await self._verified_due_evidence(m, data_scope, {}))
        source, at = self._meter.iot_meter_source, _utcnow()
        reading = select_current_reading(await source.observations(asset_id, not_after=at), vehicle_id=asset_id,
                                         components=components, counter_type=frozen.meter_type,
                                         component_id=frozen.component_id, at=at,
                                         max_observation_age=source.max_observation_age)
        current = CurrentMeter(frozen.meter_type, frozen.component_id,
                               reading.value if reading is not None else None, reading is not None)
        return evaluate_set_due(frozen, tuple(work_orders), current)

    # ---- R4 / TASK-010 Fleet PM Due B1: read-only fleet / vehicle PM Due ----

    async def _pm_read_context(self) -> tuple[str, tuple[str, str]]:
        """The server's TEST/REAL context (503 when unconfigured; resolved ONCE per
        read) and its exact `(is_test_data, test_batch_id)` cells."""
        data_context = await require_v2_write_context(self._cutover, self._repository)
        cells = scope_cells(data_context, self._cutover.test_batch_id)
        return data_context, (cells["is_test_data"], cells["test_batch_id"])

    async def _pm_due_scope(self, context: RequestContext | None) -> tuple[RequestContext, str, tuple[str, str]]:
        """Trusted actor with `can_view` (derived Due only, never raw Outcomes or
        journal), then the server's TEST/REAL scope (503), then the whole PM job
        list integrity (500, counts only), all before any protected read."""
        context = self._require_trusted(context)
        require_capability(context, CAN_VIEW, "การอ่านกำหนด PM (read PM Due)")
        data_context, data_scope = await self._pm_read_context()
        await self._require_pm_list_integrity()
        return context, data_context, data_scope

    async def read_vehicle_pm_due(self, context: RequestContext | None, vehicle_id: str) -> VehiclePmDue:
        """`GET /pm/due/vehicles/{vehicle_id}`: the PM Due of one vehicle (see
        `_pm_due_rows`). Read only."""
        context, data_context, data_scope = await self._pm_due_scope(context)
        await require_asset_exists(self._repository, AssetType.VEHICLE, vehicle_id)
        vehicle = await self._repository.get_vehicle(vehicle_id)
        (row,) = await self._pm_due_rows(context, data_context, data_scope, [vehicle])
        return row

    async def list_fleet_pm_due(self, context: RequestContext | None, params: PageParams, *, q: str | None = None,
                                operational_status: OperationalStatus | None = None, model_id: str | None = None,
                                branch_id: str | None = None) -> Page[VehiclePmDue]:
        """`GET /pm/due/vehicles`: one page of the validated vehicle list (the SAME
        `VehicleService.list_vehicles` gates, filters, order and paging as
        `GET /vehicles`), each vehicle with its PM Due. Paging is over vehicles,
        before any Due evaluation; `total_items` is the vehicle count. No fleet Due
        totals are computed (they would need the whole fleet evaluated)."""
        context, data_context, data_scope = await self._pm_due_scope(context)
        try:
            page = await VehicleService(self._repository).list_vehicles(q, operational_status, model_id, params,
                                                                        branch_id)
        except RepositoryError as exc:
            raise vehicle_master_read_error(exc) from exc
        rows = await self._pm_due_rows(context, data_context, data_scope, page.items)
        return Page(items=rows, page=page.page, page_size=page.page_size, total_items=page.total_items)

    async def _pm_due_rows(self, context: RequestContext, data_context: str, data_scope: tuple[str, str],
                           vehicles: list[Vehicle]) -> list[VehiclePmDue]:
        """Each vehicle's PM Due, in order.

        No runtime Master (the application default) is MASTER_NOT_ACTIVE for every
        vehicle: truthful, never an empty "nothing due" fleet, and the Master module
        is not even loaded. So is an injected Master that is not bound to the
        server's exact TEST/REAL scope and this repository (RT1 `_master_bound`):
        none of its Plans, assignments or Sets is disclosed. Otherwise the
        applicable Sets come from the Master itself (`applicable_plans`), so a vehicle
        never loses a Set for having no Work Order; such a Set is UNKNOWN
        NO_VERIFIED_ACTUAL_SET_COMPLETION. A Set with Work Orders is evaluated by DUE-02A /
        DUE-01 over R3-verified evidence only.

        Fail closed, the WHOLE read (the established PM read contract, as
        `list_asset_outstanding`): a Work Order a membership references that is
        missing, foreign, Legacy, outside the scope or whose records cannot be
        trusted is 500 (issue code only, never an id); an interrupted E01 change is
        409 PM_E01_TRANSITION_INCOMPLETE and a journal disagreement 409; an adapter
        without bridge storage is the explicit FEATURE_NOT_AVAILABLE. None of these
        is turned into a normal UNKNOWN or silently dropped.

        Multi-statement read: it is NOT one storage snapshot. A torn read across a
        concurrent E01 change can fail closed (409/500) or show the state just before
        that change; a database adapter must run it in one read-only snapshot
        transaction before PostgreSQL cutover (not provided by this batch)."""
        if not self._master_bound(self._pm_master, data_scope):  # none, unbound, foreign scope or repository
            return [VehiclePmDue(vehicle.vehicle_id, vehicle.machine_no, vehicle.model_id, PM_DUE_MASTER_NOT_ACTIVE,
                                 _VEHICLE_STATE_EXPLANATIONS[PM_DUE_MASTER_NOT_ACTIVE]) for vehicle in vehicles]
        if not vehicles:
            return []
        from app.domain import pm_master_runtime as runtime

        ids = {vehicle.vehicle_id for vehicle in vehicles}
        memberships = [m for m in await self._repository.list_pm_master_memberships(
                           asset_id=vehicles[0].vehicle_id if len(vehicles) == 1 else None)
                       if m.asset_id in ids
                       and in_scope({"is_test_data": m.is_test_data, "test_batch_id": m.test_batch_id},
                                    data_context, self._cutover.test_batch_id)]
        work_order_ids = [m.pm_work_order_id for m in memberships]
        if len(work_order_ids) != len(set(work_order_ids)):  # write-once: one membership per Work Order
            raise _pm_read_invalid("MEMBERSHIP_DUPLICATE")
        cache = _PmDueReadCache(at=_utcnow())
        rows = []
        for vehicle in vehicles:
            rows.append(await self._vehicle_pm_due(context, data_scope, vehicle,
                                                   [m for m in memberships if m.asset_id == vehicle.vehicle_id],
                                                   cache, runtime))
        return rows

    async def _vehicle_pm_due(self, context, data_scope, vehicle: Vehicle, memberships, cache: _PmDueReadCache,
                              runtime) -> VehiclePmDue:
        vehicle_id = vehicle.vehicle_id
        resolutions = {a: self._pm_master.resolve_plan(context, vehicle_id, a) for a in runtime.PLAN_ASSEMBLIES}
        assignments = tuple(PmDueAssignment(a, r.source, r.plan_code) for a, r in resolutions.items())
        for plan_code in {r.plan_code for r in resolutions.values() if r.source == runtime.ASSIGNED_SOURCE
                          and r.plan_code}:
            if plan_code not in cache.heads:
                cache.heads[plan_code] = self._pm_master.effective_revision(context, plan_code)
        if vehicle.model_id not in cache.models:
            model = await self._repository.get_vehicle_model(vehicle.model_id) if vehicle.model_id else None
            cache.models[vehicle.model_id] = model.model_id if model is not None else ""
        model_id = cache.models[vehicle.model_id]
        plans = runtime.applicable_plans(resolutions, cache.heads, vehicle_model_id=model_id,
                                         model_variants=self._variant_source(self._pm_master, context,
                                                                             self._model_variants))
        state = PM_DUE_AVAILABLE if plans else PM_DUE_NO_ASSIGNED_PLAN
        plan_rows = tuple(PmDuePlan(p.plan_code, p.state, p.revision.revision_number if p.revision else None,
                                    p.model_variant, _PLAN_STATE_EXPLANATIONS[p.state]) for p in plans)
        set_rows: list[PmDueSet] = []
        if any(p.sets for p in plans):
            components = [(c.component_id, c.component_role.value)
                          for c in await self._repository.list_vehicle_components(vehicle_id)]
            source = self._meter.iot_meter_source
            observations = await source.observations(vehicle_id, not_after=cache.at)  # once per vehicle
            for plan in plans:
                for master_set in plan.sets:
                    set_rows.append(await self._pm_due_set(data_scope, vehicle_id, model_id, plan.revision,
                                                           master_set, memberships, components, observations,
                                                           cache, runtime))
        return VehiclePmDue(vehicle_id, vehicle.machine_no, vehicle.model_id, state,
                            _VEHICLE_STATE_EXPLANATIONS[state], assignments, plan_rows, tuple(set_rows))

    async def _pm_due_set(self, data_scope, vehicle_id: str, model_id: str, revision, master_set, memberships,
                          components, observations, cache: _PmDueReadCache, runtime) -> PmDueSet:
        from app.domain.pm_due_evidence import CurrentMeter, evaluate_set_due, last_qualified_completion

        set_key = master_set.set_key
        members = [m for m in memberships if m.master_revision_id == revision.revision_id
                   and any(s.set_key == set_key for s in m.sets)]  # the current revision only
        work_orders: tuple = ()
        if members:
            expected = runtime.membership_set_of(master_set, revision.revision_id)
            self._verify_membership_provenance(members, revision, expected, runtime)
            key = (members[0].pm_plan_id, revision.revision_id)
            if key not in cache.catalogues:
                cache.catalogues[key] = await self._repository.get_pm_task_revision(*key)
            frozen = runtime.frozen_set(members, set_key, cache.catalogues[key], components, model_id,
                                        expected=expected)
            work_orders = tuple([await self._verified_due_evidence(m, data_scope, cache.evidence) for m in members])
        else:
            frozen = runtime.master_frozen_set(revision, master_set, asset_id=vehicle_id, components=components)
        source = self._meter.iot_meter_source
        reading = select_current_reading(observations, vehicle_id=vehicle_id, components=components,
                                         counter_type=frozen.meter_type, component_id=frozen.component_id,
                                         at=cache.at, max_observation_age=source.max_observation_age)
        decision = evaluate_set_due(frozen, work_orders, CurrentMeter(
            frozen.meter_type, frozen.component_id, reading.value if reading is not None else None,
            reading is not None))
        last = last_qualified_completion(frozen, work_orders)
        due = decision.due
        return PmDueSet(
            plan_code=revision.plan_code, revision_number=revision.revision_number, set_key=set_key,
            model_variant=master_set.model_variant, section=master_set.section, set_code=master_set.set_code,
            meter_type=master_set.meter_type.value, interval_value=float(master_set.interval_value),
            interval_unit=master_set.interval_unit, driving_component_role=frozen.driving_component_role,
            component_id=frozen.component_id, status=due.status, explanation=_set_explanation(due.status, due.reason),
            diagnostic_code=due.reason, next_due=due.next_due if due.status != "UNKNOWN" else None,
            last_completed_meter=last.meter if last else None, last_completed_at=last.completed_at if last else None,
            last_completed_pm_work_order_id=last.pm_work_order_id if last else None,
            current_meter=reading.value if reading is not None else None,
            current_observed_at=reading.observed_at if reading is not None else None)

    @staticmethod
    def _verify_membership_provenance(members, revision, expected, runtime) -> None:
        """R2: every membership selected for an applicable Set (same asset, same head
        revision id, containing the Set key) must be that revision's own write-once
        record: its Plan code, runtime Plan id and revision number are the published
        revision's, and its frozen definition of this Set (facts and COMPLETE Item list)
        equals the published Master Set. A mismatch is corrupted stored provenance:
        the whole read fails closed (500, issue code only), never an ordinary UNKNOWN
        or another Set's evidence. A membership of an older revision is never selected
        (history, not corruption), and a changed registered model only makes the
        variant's own Sets apply (`applicable_plans`, `frozen_set`)."""
        identity = (revision.plan_code, runtime.runtime_plan_id_of(revision), revision.revision_number)
        for membership in members:
            if (membership.plan_code, membership.pm_plan_id, membership.master_revision_number) != identity:
                raise _pm_read_invalid("MEMBERSHIP_PROVENANCE_MISMATCH")
            if [s for s in membership.sets if s.set_key == expected.set_key] != [expected]:
                raise _pm_read_invalid("MEMBERSHIP_SET_MISMATCH")

    async def _verified_due_evidence(self, membership, data_scope: tuple[str, str], cache: dict):
        """The DUE-02A evidence of one membership's Work Order, ONLY after the R3 E01
        read-integrity proof. Read only: never `_current_status`, never a projection,
        capture or audit row.

        1. the Work Order exists and is exactly the membership's (id, VEHICLE asset,
           plan, revision), Technician V2, with the server's TEST/REAL cells, as is the
           membership itself, and its scope still contains every membership task;
        2. `_read_only_status` (R3): journal owner / scope / identity / provenance /
           chain, header consistency (a progressed header without a journal, an
           interrupted change), and for a CLOSED header its own CLOSE snapshot,
           referenced by no other work order;
        3. for a CLOSED Work Order: complete E01 accounting (`_require_complete_accounting`:
           every result linked to its Outcome, at least one PERFORMED), its results and
           Outcomes belong to it and its revision, one per task; the accepted SUBMIT (the event the verified CLOSE
           accepted) has at most one anchor, which must be that event's own.
        Any failure is 500 (issue code only) or the R3 409; a missing anchor is not
        corruption (no IoT source at SUBMIT) and stays the evaluator's UNKNOWN."""
        pm_work_order_id = membership.pm_work_order_id
        if pm_work_order_id in cache:
            return cache[pm_work_order_id]
        if (text(membership.is_test_data), text(membership.test_batch_id)) != data_scope:
            raise _pm_read_invalid("MEMBERSHIP_SCOPE_MISMATCH")
        detail = await self._repository.get_pm_work_order(pm_work_order_id)
        if detail is None:
            raise _pm_read_invalid("WORK_ORDER_REFERENCE_MISSING")
        work_order = detail.work_order
        if (work_order.pm_work_order_id != pm_work_order_id or work_order.asset_type != AssetType.VEHICLE
                or work_order.asset_id != membership.asset_id
                or (work_order.pm_plan_id, work_order.revision_id) != (membership.pm_plan_id,
                                                                       membership.master_revision_id)
                or text(work_order.assignment_model) != ASSIGNMENT_MODEL_TECHNICIAN_V2):
            raise _pm_read_invalid("WORK_ORDER_RECORD_MISMATCH")
        if (text(work_order.is_test_data), text(work_order.test_batch_id)) != data_scope:
            raise _pm_read_invalid("WORK_ORDER_SCOPE_MISMATCH")
        # R2: the Work Order was opened with EXACTLY its membership's tasks and E01 scope
        # only grows (`add_scope_task`), so every originally selected task must still be
        # in scope; legitimately added tasks are kept (superset, never equality). A
        # missing one is corruption, never a "partial Set" falling back to an older anchor.
        if not set(membership.task_ids) <= set(work_order.scope_task_ids):
            raise _pm_read_invalid("MEMBERSHIP_SCOPE_TASK_MISSING")
        current, journal = await self._read_only_status(detail)
        outcomes: list = []
        anchor = None
        if current == PmWorkOrderStatus.CLOSED:
            # Outcomes only through the approved E01 accounting read (B02 firewall): a
            # CLOSED Work Order passed it at SUBMIT, so a failure now is corruption.
            try:
                outcomes = await self._fail_closed_read(self._require_complete_accounting(detail))
            except ApiError as exc:
                if exc.code not in ("PM_E01_ITEM_RECORD_INCOMPLETE",) and exc.status_code != 422:
                    raise
                raise _pm_read_invalid("OUTCOME_ACCOUNTING_INVALID") from exc
            self._verify_due_records(work_order, detail.results, outcomes)
            # The verified chain ends PENDING_REVIEW -> CLOSED, and PENDING_REVIEW is
            # reachable only by SUBMIT: journal[-2] is the accepted SUBMIT.
            submit = journal[-2] if len(journal) >= 2 else None
            if submit is not None and submit.action == PmE01ContractAction.SUBMIT:
                anchor = await self._fail_closed_read(self._repository.get_pm_submit_meter_anchor(submit.event_id))
                if anchor is not None and (
                        anchor.pm_work_order_id != pm_work_order_id or anchor.submit_event_id != submit.event_id
                        or anchor.submitted_at != submit.occurred_at
                        or (anchor.asset_type, anchor.asset_id) != (AssetType.VEHICLE.value, work_order.asset_id)
                        or (text(anchor.is_test_data), text(anchor.test_batch_id)) != data_scope):
                    raise _pm_read_invalid("SUBMIT_ANCHOR_MISMATCH")
        evidence = work_order_evidence(detail, journal, outcomes=outcomes, anchor=anchor, v2_scope_verified=True,
                                       data_scope_verified=True)
        cache[pm_work_order_id] = evidence
        return evidence

    @staticmethod
    def _verify_due_records(work_order: PmWorkOrder, results: list[PmWorkResult], outcomes: list) -> None:
        """A CLOSED Work Order's results and Outcomes must be its own (this Work
        Order and revision), one per task and one per id; foreign or duplicated
        records are corruption, never quietly read as "not performed"."""
        own = (work_order.pm_work_order_id, work_order.revision_id)
        if any((r.pm_work_order_id, r.revision_id) != own for r in results):
            raise _pm_read_invalid("RESULT_RECORD_MISMATCH")
        if (len({r.pm_task_id for r in results}) != len(results)
                or len({r.pm_work_result_id for r in results}) != len(results)):
            raise _pm_read_invalid("RESULT_DUPLICATE")
        if any((o.pm_work_order_id, o.revision_id) != own for o in outcomes):
            raise _pm_read_invalid("OUTCOME_RECORD_MISMATCH")
        if len({o.pm_task_id for o in outcomes}) != len(outcomes):
            raise _pm_read_invalid("OUTCOME_DUPLICATE")

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

    async def list_requisition_lines_for_reader(self, pm_work_order_id: str,
                                                context: RequestContext | None) -> list:
        """`GET /pm/work-orders/{id}/requisition-lines` (R4 PM Read Safety B1):
        exactly the PM Work Order detail read contract (`get_work_order_for_reader`:
        trusted actor, server scope, Technician V2 only, `can_manage_pm` or the
        current V2 team) before any requisition line is read. Read only."""
        await self.get_work_order_for_reader(pm_work_order_id, context)
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

    async def _read_only_status(self, detail: PmWorkOrderDetail
                                ) -> tuple[PmWorkOrderStatus, list[PmWorkOrderTransition]]:
        """R4 PM Read Safety B1: the authoritative status for a GET, verified and
        NEVER written. When the journal and the stored header agree it is the
        same result `_current_status` gives.

        A V2 work order's journal must prove its header (R2): every event belongs
        to this work order and carries exactly its TEST/REAL cells, and the events
        form one valid E01 chain from OPEN (otherwise 500, issue codes only). A
        progressed V2 header (anything but OPEN) with no journal is not a proven
        E01 state: 409 PM_E01_STATE_INCONSISTENT. A projection that lags one event
        behind (an interrupted write, which `_current_status` would complete) is
        409 PM_E01_TRANSITION_INCOMPLETE: nothing is projected, captured or
        audited, and the pending change is never reported as done. A CLOSED V2
        header must carry its close snapshot (blank: the same incomplete CLOSE)
        and that snapshot must be this CLOSE's own persisted evidence, referenced
        by no other work order (500 otherwise). Journal provenance includes the
        request fingerprint, unique event / request identities and the
        deterministic E01 event id (R3). Any other disagreement is 409 PM_E01_STATE_INCONSISTENT,
        exactly as on the write path."""
        work_order = detail.work_order
        journal = await self._fail_closed_read(
            self._repository.list_pm_work_order_transitions(work_order.pm_work_order_id),
            {"SCOPE_MISMATCH": "JOURNAL_SCOPE_MISMATCH", "TRANSITION_INVALID": "JOURNAL_PROVENANCE_INVALID"})
        header = work_order.status
        v2 = assignment_model_of(work_order) == ASSIGNMENT_MODEL_TECHNICIAN_V2
        if v2:
            self._verify_journal(work_order, journal)
        if not journal:
            if v2 and header != PmWorkOrderStatus.OPEN:
                raise _state_inconsistent()
            return header, journal
        last = journal[-1]
        if last.to_status == header:
            if header == PmWorkOrderStatus.CLOSED and v2:
                if not (work_order.closed_snapshot_id or "").strip():
                    raise _transition_incomplete()
                await self._verify_close_evidence(work_order, last)
            return header, journal
        if last.from_status == header:
            raise _transition_incomplete()
        raise _state_inconsistent()

    @staticmethod
    def _verify_journal(work_order: PmWorkOrder, journal: list[PmWorkOrderTransition]) -> None:
        """R4 PM Read Safety B1 (R2): the shared read-side proof of a V2 journal,
        on every adapter (Sheets already checks scope; the Mock stores events by
        key only). Fails the whole read closed with the issue code only."""
        scope = (text(work_order.is_test_data), text(work_order.test_batch_id))
        for identity in ([e.event_id for e in journal], [e.request_id for e in journal]):
            if len(identity) != len(set(identity)):  # one event per client request (E01 idempotency)
                raise _pm_read_invalid("JOURNAL_IDENTITY_DUPLICATE")
        state = PmWorkOrderStatus.OPEN
        for event in journal:
            if event.pm_work_order_id != work_order.pm_work_order_id:
                raise _pm_read_invalid("JOURNAL_OWNER_MISMATCH")
            if (text(event.is_test_data), text(event.test_batch_id)) != scope:
                raise _pm_read_invalid("JOURNAL_SCOPE_MISMATCH")
            if (not all(text(v).strip() for v in (event.event_id, event.request_id, event.request_fingerprint,
                                                   event.actor))
                    or event.event_id != _e01_event_id(work_order.pm_work_order_id, event.request_id)):
                raise _pm_read_invalid("JOURNAL_PROVENANCE_INVALID")
            if event.from_status != state:
                raise _pm_read_invalid("JOURNAL_CHAIN_INVALID")
            if event.action == PmE01ContractAction.CANCEL:
                valid = (event.from_status in (PmWorkOrderStatus.OPEN, PmWorkOrderStatus.IN_PROGRESS)
                         and event.to_status == PmWorkOrderStatus.CANCELLED and bool(text(event.reason).strip()))
            else:
                try:
                    valid = pm_e01_contract_transition(pm_e01_state(event.from_status), event.action,
                                                       return_reason=event.reason).value == event.to_status.value
                except ValueError:
                    valid = False
            if not valid:
                raise _pm_read_invalid("JOURNAL_CHAIN_INVALID")
            state = event.to_status

    async def _verify_close_evidence(self, work_order: PmWorkOrder, event: PmWorkOrderTransition) -> None:
        """R4 PM Read Safety B1 (R2): a nonblank `closed_snapshot_id` alone proves
        nothing. Read only, with the existing snapshot reads: the header carries
        the CLOSE event's own time and actor, and the referenced snapshot exists
        and is that CLOSE's automatic capture on this asset (the rule the E01
        write-side reuse of an interrupted capture applies), with its one GPS half
        for a vehicle. Otherwise 500, issue code only; no evidence is invented."""
        if work_order.closed_at != event.occurred_at or work_order.closed_by != event.actor:
            raise _pm_read_invalid("CLOSE_RECORD_MISMATCH")
        snapshot = await self._repository.get_meter_snapshot(work_order.closed_snapshot_id)
        if snapshot is None:
            raise _pm_read_invalid("CLOSE_SNAPSHOT_MISSING")
        if ((snapshot.asset_type, snapshot.asset_id) != (work_order.asset_type, work_order.asset_id)
                or not snapshot.is_automatic or snapshot.source_note != "PM_WORK_ORDER_CLOSE"
                or snapshot.recorded_by != event.actor or snapshot.recorded_at < event.occurred_at):
            raise _pm_read_invalid("CLOSE_SNAPSHOT_MISMATCH")
        if work_order.asset_type == AssetType.VEHICLE:
            locations = await self._repository.list_location_snapshots_for_event(snapshot.meter_snapshot_id)
            if len(locations) != 1 or locations[0].vehicle_id != work_order.asset_id \
                    or locations[0].event_type != "PM_WORK_ORDER_CLOSE":
                raise _pm_read_invalid("CLOSE_LOCATION_MISMATCH")
        if await self._close_snapshot_claimed_elsewhere(work_order):
            raise _pm_read_invalid("CLOSE_SNAPSHOT_FOREIGN")

    async def _close_snapshot_claimed_elsewhere(self, work_order: PmWorkOrder) -> bool:
        """R4 PM Read Safety B1 (R3): one CLOSE capture is the evidence of exactly
        one work order. True when any OTHER PM work order on the asset (any model,
        status or scope; the same unscoped asset scan `_interrupted_close_capture`
        uses) persists the same `closed_snapshot_id`: the snapshot is then foreign
        or ambiguous. No event-to-snapshot link beyond the persisted reference is
        inferred, so a valid historical close keeps its own snapshot whatever was
        captured after it."""
        page = 1
        while True:
            rows, total = await self._repository.list_pm_work_orders(
                work_order.asset_type, work_order.asset_id, PageParams(page=page, page_size=200))
            for row in rows:
                if row.pm_work_order_id == work_order.pm_work_order_id:
                    continue
                other = await self._repository.get_pm_work_order(row.pm_work_order_id)
                if other is not None and other.work_order.closed_snapshot_id == work_order.closed_snapshot_id:
                    return True
            if not rows or page * 200 >= total:
                return False
            page += 1

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
            event_id=_e01_event_id(work_order.pm_work_order_id, request_id),
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
        """The E01 journal of one V2 work order. Read only (R4 PM Read Safety
        B1): an interrupted change is 409 PM_E01_TRANSITION_INCOMPLETE, never
        completed by this read."""
        detail = await self._authorize_outcome_access(
            pm_work_order_id, context, "การอ่านประวัติสถานะงาน PM (read PM work order history)")
        _, journal = await self._read_only_status(detail)
        return journal

    async def list_outstanding_items(self, pm_work_order_id: str,
                                     context: RequestContext | None) -> list[PmOutstandingState]:
        """Effective Outstanding records of one work order: none until it is
        CLOSED. Read only (R4 PM Read Safety B1): an interrupted CLOSE is 409
        PM_E01_TRANSITION_INCOMPLETE (never an empty list, never completed by
        this read)."""
        detail = await self._authorize_outcome_access(
            pm_work_order_id, context, "การอ่านงาน PM ค้าง (read PM Outstanding items)")
        current, _ = await self._read_only_status(detail)
        if current != PmWorkOrderStatus.CLOSED:
            return []
        return [await self._outstanding_state(i)
                for i in await self._fail_closed_read(self._repository.list_pm_outstanding_items(pm_work_order_id))]

    async def list_asset_outstanding(self, asset_type: AssetType, asset_id: str,
                                     context: RequestContext | None) -> list[PmOutstandingState]:
        """The post-PM Outstanding backlog of one asset (separate from Due):
        effective records of in-scope CLOSED V2 work orders only.

        R4 PM Read Safety B1: a trusted actor with `can_view`, then the server's
        TEST/REAL context, before any read. Legacy and other-scope work orders are
        excluded. Anything unprovable fails the WHOLE list (never a partial
        success): a missing work order reference or untrusted scope cells (500,
        no ids), an interrupted CLOSE (409 PM_E01_TRANSITION_INCOMPLETE) or a
        journal disagreement (409). Read only: nothing is projected or written."""
        context = self._require_trusted(context)
        require_capability(context, CAN_VIEW, "การอ่านงาน PM ค้างของสินทรัพย์ (read PM Outstanding items)")
        data_context = await require_v2_write_context(self._cutover, self._repository)
        items = await self._fail_closed_read(
            self._repository.list_pm_outstanding_items_for_asset(asset_type, asset_id))
        details: dict[str, PmWorkOrderDetail | None] = {}
        states = []
        for item in items:
            if item.pm_work_order_id not in details:
                details[item.pm_work_order_id] = await self._repository.get_pm_work_order(item.pm_work_order_id)
            detail = details[item.pm_work_order_id]
            if detail is None:
                raise _pm_read_invalid("WORK_ORDER_REFERENCE_MISSING")
            work_order = detail.work_order
            if assignment_model_of(work_order) != ASSIGNMENT_MODEL_TECHNICIAN_V2:  # unknown marker: 500 inside
                continue
            flag, batch = text(work_order.is_test_data), text(work_order.test_batch_id)
            if flag not in (TEST_FLAG, OPERATIONAL_FLAG) or (flag == OPERATIONAL_FLAG and batch):
                raise _pm_read_invalid("JOB_SCOPE_FLAG_INVALID")
            if not in_scope({"is_test_data": flag, "test_batch_id": batch}, data_context,
                            self._cutover.test_batch_id):
                continue
            if (await self._read_only_status(detail))[0] == PmWorkOrderStatus.CLOSED:
                states.append(await self._outstanding_state(item))
        return states

    @staticmethod
    async def _fail_closed_read(call, renamed: dict[str, str] | None = None):
        """A read-side repository call whose stored rows cannot be trusted (a
        missing source work order, a duplicated id, a scope mismatch) fails closed
        with the issue code only. `renamed` maps an adapter issue to the shared
        code the service uses for the same defect (Mock / Sheets parity)."""
        try:
            return await call
        except RepositoryRecordInvalidError as exc:
            raise _pm_read_invalid((renamed or {}).get(exc.issue, exc.issue)) from exc
        except RepositoryIdentityAmbiguousError as exc:
            raise _pm_read_invalid("IDENTITY_AMBIGUOUS") from exc

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
