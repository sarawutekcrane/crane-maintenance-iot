"""R5 — Repair substate and technician work-time service (Revision 4 §§4–9).

Authorization (Owner decisions OD-2, OD-4, AMB-2; no new role or capability):
* substates: the existing repair-work recording authority (current V2 member, or
  the Repair manager capability — `can_manage_finding_repair` on an R3 Finding
  round); members only before completion is submitted, managers while OPEN;
* work time: a technician records ONLY their own periods. The technician id is
  resolved on the server (User Account → Personnel → Technician, in scope) and
  must appear in the job's V2 assignment-set history. A manager never records on
  someone's behalf;
* corrections: the technician — own entries while the job is open for entries;
  the job's manager — any entry, also after CLOSE (the Work Order stays CLOSED);
  a reason is always required and every correction invalidates the previous
  revision's confirmation;
* confirmation: the job's manager authority (Repair / Finding / PM), never for
  the confirmer's OWN technician time (AMB-2: having corrected the entry does not
  matter).

Every write: trusted context → request id → body → data context (503) → job
(404) → V2 model / scope (409 / 500) → window (409) → authority (403) → replay →
stale → rules → ONE append, under the job lock then the work-time lock. Refusals
write nothing.
"""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import status

from app.context import RequestContext
from app.domain.authz import CAN_MANAGE_FINDING_REPAIR, CAN_MANAGE_PM, CAN_MANAGE_REPAIR
from app.domain.pm import PmWorkOrderStatus
from app.domain.repair import RepairStatus
from app.domain.request_replay import canonical_json
from app.domain.technician_assignment import (
    PM,
    REPAIR,
    AssignmentCutover,
    TechnicianAssignmentService,
    require_v2_job_in_scope,
    require_v2_write_context,
    scope_cells,
    verified_personnel_id,
)
from app.domain.work_time import (
    RECORD_CORRECTION,
    RECORD_ENTRY,
    RECORD_VOID,
    SUBSTATES,
    WORK_KIND_PM,
    WORK_KIND_REPAIR,
    RepairSubstatePeriod,
    WorkBreak,
    WorkTimeConfirmation,
    WorkTimeEntry,
    WorkTimeRuleError,
    confirmed_refs,
    current_revisions,
    effective_periods,
    entry_ref,
    find_overlap,
    normalize_instant,
    substate_conflict,
    substate_durations,
    team_totals,
    technician_totals,
    unconfirmed_entries,
    validate_breaks,
    validate_description,
    validate_interval,
    validate_reason,
    validate_time_class,
)
from app.errors import ApiError
from app.repositories.base import Repository

ACTION_CORRECT = "CORRECT"
ACTION_VOID = "VOID"
AUTO_END_REASON = "ปิดช่วงสถานะก่อนหน้าเมื่อเริ่มสถานะใหม่ (บันทึกโดยระบบตามคำขอเดียวกัน)"
MANAGER_CAPABILITIES = (CAN_MANAGE_REPAIR, CAN_MANAGE_FINDING_REPAIR, CAN_MANAGE_PM)
_REPOSITORY_CODES = {
    "R5_REQUEST_CONFLICT": "WORK_TIME_REQUEST_CONFLICT",
    "WORK_TIME_REVISION_STALE": "WORK_TIME_REVISION_STALE",
    "WORK_TIME_OVERLAP": "WORK_TIME_OVERLAP",
    "REPAIR_SUBSTATE_CONFLICT": "REPAIR_SUBSTATE_CONFLICT",
}


def _err(code: str, message: str, http_status: int, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=http_status, details=details or {})


def _rule(exc: WorkTimeRuleError) -> ApiError:
    http_status = (status.HTTP_500_INTERNAL_SERVER_ERROR if exc.code == "WORK_TIME_DATA_INVALID"
                   else status.HTTP_422_UNPROCESSABLE_ENTITY)
    return _err(exc.code, "The work-time values are not accepted; nothing was changed", http_status, exc.details)


def _repository_refusal(exc: ValueError) -> ApiError:
    code = _REPOSITORY_CODES.get(str(exc), str(exc))
    return _err(code, "The change conflicts with the recorded history; nothing was changed", status.HTTP_409_CONFLICT)


def fingerprint(operation: str, work_kind: str, job_id: str, body: Mapping[str, object]) -> str:
    payload = {"op": operation, "kind": work_kind, "job": job_id, "body": dict(body)}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _clip(entry: WorkTimeEntry, start: datetime, end: datetime) -> WorkTimeEntry | None:
    """The part of an entry inside `[start, end)` (breaks clipped alike), or None."""
    new_start, new_end = max(entry.started_at, start), min(entry.ended_at, end)
    if new_end <= new_start:
        return None
    breaks = tuple(WorkBreak(started_at=max(b.started_at, new_start), ended_at=min(b.ended_at, new_end))
                   for b in entry.breaks if min(b.ended_at, new_end) > max(b.started_at, new_start))
    return entry.model_copy(update={"started_at": new_start, "ended_at": new_end, "breaks": breaks})


class WorkTimeService:
    def __init__(self, repository: Repository, cutover: AssignmentCutover) -> None:
        self._repository = repository
        self._cutover = cutover

    # ---------------------------------------------------------------- shared

    @staticmethod
    def _trusted(context: RequestContext | None) -> RequestContext:
        if not isinstance(context, RequestContext) or not (context.user_id or "").strip():
            raise _err("WORK_TIME_CONTEXT_REQUIRED", "A trusted, authenticated request context is required",
                       status.HTTP_403_FORBIDDEN)
        return context

    async def _job(self, work_kind: str, job_id: str):
        if work_kind == WORK_KIND_REPAIR:
            detail = await self._repository.get_repair(job_id)
            if detail is None:
                raise _err("REPAIR_NOT_FOUND", f"Repair '{job_id}' was not found", status.HTTP_404_NOT_FOUND)
            return detail.repair
        detail = await self._repository.get_pm_work_order(job_id)
        if detail is None:
            raise _err("PM_WORK_ORDER_NOT_FOUND", f"PM work order '{job_id}' was not found",
                       status.HTTP_404_NOT_FOUND)
        return detail.work_order

    async def locate_job(self, work_kind: str, job_id: str):
        """The stored job (used to build a response after an authorized write)."""
        return await self._job(work_kind, job_id)

    async def _scoped_job(self, work_kind: str, job_id: str):
        data_context = await require_v2_write_context(self._cutover, self._repository)
        job = await self._job(work_kind, job_id)
        require_v2_job_in_scope(REPAIR if work_kind == WORK_KIND_REPAIR else PM, job, data_context,
                                self._cutover.test_batch_id)
        return job, data_context

    @asynccontextmanager
    async def _locked(self, work_kind: str, job_id: str):
        job_lock = (self._repository.repair_work_order_lock(job_id) if work_kind == WORK_KIND_REPAIR
                    else self._repository.pm_work_order_lock(job_id))
        async with job_lock:
            async with self._repository.work_time_lock():
                yield

    @staticmethod
    def _manager_capability(work_kind: str, job) -> str:
        if work_kind == WORK_KIND_PM:
            return CAN_MANAGE_PM
        return CAN_MANAGE_FINDING_REPAIR if getattr(job, "finding_id", None) else CAN_MANAGE_REPAIR

    def _is_manager(self, work_kind: str, job, context: RequestContext) -> bool:
        return self._manager_capability(work_kind, job) in context.capabilities

    def _assignments(self) -> TechnicianAssignmentService:
        return TechnicianAssignmentService(self._repository, self._cutover)

    async def _actor_technician(self, context: RequestContext, data_context: str) -> str | None:
        return await self._assignments().actor_technician_id(context.user_id or "", data_context,
                                                             verified_personnel_id(context))

    @staticmethod
    def _status(job) -> str:
        return getattr(job.status, "value", job.status)

    def _technician_window_open(self, work_kind: str, job) -> bool:
        if work_kind == WORK_KIND_REPAIR:
            return self._status(job) == RepairStatus.OPEN.value
        return self._status(job) in (PmWorkOrderStatus.IN_PROGRESS.value, PmWorkOrderStatus.PENDING_REVIEW.value)

    def _cancelled(self, work_kind: str, job) -> bool:
        return self._status(job) == (RepairStatus.CANCELLED.value if work_kind == WORK_KIND_REPAIR
                                     else PmWorkOrderStatus.CANCELLED.value)

    def _closed(self, work_kind: str, job) -> bool:
        return self._status(job) == (RepairStatus.CLOSED.value if work_kind == WORK_KIND_REPAIR
                                     else PmWorkOrderStatus.CLOSED.value)

    # ---------------------------------------------------------------- substates

    async def _authorize_substate(self, repair, context: RequestContext) -> bool:
        """Existing recording authority; returns whether the actor is a manager."""
        capability = self._manager_capability(WORK_KIND_REPAIR, repair)
        await self._assignments().require_recording(REPAIR, repair, context, capability,
                                                    "การบันทึกสถานะย่อยงานซ่อม (record a repair substate)")
        return capability in context.capabilities

    @staticmethod
    def _require_substate_window(repair, manager: bool) -> None:
        if repair.status != RepairStatus.OPEN:
            raise _err("REPAIR_SUBSTATE_WINDOW_CLOSED", "Substates are recorded only on an OPEN repair work order",
                       status.HTTP_409_CONFLICT, {"status": repair.status.value})
        if repair.completion_submitted_at is not None and not manager:
            raise _err("REPAIR_SUBSTATE_WINDOW_CLOSED", "Completion was submitted; only a manager may still record "
                       "or correct substates", status.HTTP_409_CONFLICT, {"completion_submitted": True})

    async def _substate_replay(self, repair_id: str, request_id: str, digest: str) -> list[RepairSubstatePeriod]:
        earlier = [p for p in await self._repository.list_repair_substates(repair_id) if p.request_id == request_id]
        if earlier and any(p.request_fingerprint != digest for p in earlier):
            raise _err("WORK_TIME_REQUEST_CONFLICT", "This request id was already used for another change; nothing "
                       "was changed", status.HTTP_409_CONFLICT)
        return earlier

    async def _material_request_belongs(self, repair_id: str, material_request_id: str | None) -> None:
        if material_request_id is None:
            return
        requests = await self._repository.list_material_requests_for_work_order(repair_id)
        if not any(r.material_request_id == material_request_id for r in requests):
            raise _err("REPAIR_SUBSTATE_MATERIAL_REQUEST_INVALID", "The material request does not belong to this repair",
                       status.HTTP_422_UNPROCESSABLE_ENTITY)

    def _validated_period(self, repair, started_at: datetime, ended_at: datetime | None) -> tuple[datetime,
                                                                                                    datetime | None]:
        now = _utcnow()
        try:
            start = normalize_instant(started_at)
            end = normalize_instant(ended_at) if ended_at is not None else None
        except WorkTimeRuleError as exc:
            raise _rule(exc) from exc
        opened = repair.opened_at if repair.opened_at.tzinfo else repair.opened_at.replace(tzinfo=timezone.utc)
        if start < opened.replace(microsecond=0) or start > now or (end is not None and (end <= start or end > now)):
            raise _err("REPAIR_SUBSTATE_INVALID_INTERVAL", "A substate period must start after the repair was opened, "
                       "end after it starts, and lie in the past", status.HTTP_422_UNPROCESSABLE_ENTITY)
        return start, end

    async def record_substate(self, repair_id: str, context: RequestContext | None, *, body: Mapping[str, object],
                              substate: str, started_at: datetime | None, ended_at: datetime | None,
                              material_request_id: str | None, close_ongoing: bool,
                              request_id: str) -> tuple[list[RepairSubstatePeriod], bool]:
        context = self._trusted(context)
        if substate not in SUBSTATES:
            raise _err("REPAIR_SUBSTATE_INVALID", "Unknown substate", status.HTTP_422_UNPROCESSABLE_ENTITY)
        digest = fingerprint("repair_substate", WORK_KIND_REPAIR, repair_id, body)
        async with self._locked(WORK_KIND_REPAIR, repair_id):
            repair, _ = await self._scoped_job(WORK_KIND_REPAIR, repair_id)
            manager = await self._authorize_substate(repair, context)
            earlier = await self._substate_replay(repair_id, request_id, digest)
            if earlier:
                return earlier, True
            self._require_substate_window(repair, manager)
            if started_at is None:  # "now" is the server's time, never the client's clock
                if ended_at is not None:
                    raise _err("REPAIR_SUBSTATE_INVALID_INTERVAL", "A period starting now cannot already have ended",
                               status.HTTP_422_UNPROCESSABLE_ENTITY)
                started_at = _utcnow()  # whole seconds; never before the (whole-second) opening time
            start, end = self._validated_period(repair, started_at, ended_at)
            await self._material_request_belongs(repair_id, material_request_id)
            now = _utcnow()
            records: list[RepairSubstatePeriod] = []
            if close_ongoing:
                ongoing = [p for p in effective_periods(await self._repository.list_repair_substates(repair_id))
                           if p.ended_at is None]
                for period in ongoing:
                    if period.started_at >= start:
                        raise _err("REPAIR_SUBSTATE_CONFLICT", "The ongoing period started at the same second as (or "
                                   "after) the new one; a period must have a positive length",
                                   status.HTTP_409_CONFLICT, {"period_id": period.period_id})
                    records.append(period.model_copy(update={
                        "revision": period.revision + 1, "record_kind": RECORD_CORRECTION, "ended_at": start,
                        "recorded_by": context.user_id, "recorded_at": now, "reason": AUTO_END_REASON,
                        "request_id": request_id, "request_fingerprint": digest}))
            records.append(RepairSubstatePeriod(
                period_id=f"RSP-{uuid.uuid4().hex[:16]}", revision=1, record_kind=RECORD_ENTRY, repair_id=repair_id,
                substate=substate, started_at=start, ended_at=end, material_request_id=material_request_id,
                recorded_by=context.user_id, recorded_at=now, request_id=request_id, request_fingerprint=digest,
                is_test_data=repair.is_test_data, test_batch_id=repair.test_batch_id))
            try:
                return await self._repository.append_repair_substates(records)
            except ValueError as exc:
                raise _repository_refusal(exc) from exc

    async def revise_substate(self, repair_id: str, period_id: str, context: RequestContext | None, *,
                              body: Mapping[str, object], action: str, expected_revision: int, reason: str | None,
                              substate: str | None, started_at: datetime | None, ended_at: datetime | None,
                              request_id: str) -> tuple[list[RepairSubstatePeriod], bool]:
        context = self._trusted(context)
        digest = fingerprint("repair_substate_revision", WORK_KIND_REPAIR, f"{repair_id}/{period_id}", body)
        try:
            reason = validate_reason(reason, required=True)
        except WorkTimeRuleError as exc:
            raise _rule(exc) from exc
        async with self._locked(WORK_KIND_REPAIR, repair_id):
            repair, _ = await self._scoped_job(WORK_KIND_REPAIR, repair_id)
            manager = await self._authorize_substate(repair, context)
            earlier = await self._substate_replay(repair_id, request_id, digest)
            if earlier:
                return earlier, True
            self._require_substate_window(repair, manager)
            latest = current_revisions(await self._repository.list_repair_substates(repair_id), "period_id")
            head = latest.get(period_id)
            if head is None:
                raise _err("REPAIR_SUBSTATE_NOT_FOUND", "No substate period has this id", status.HTTP_404_NOT_FOUND)
            if head.revision != expected_revision or head.record_kind == RECORD_VOID:
                raise _err("WORK_TIME_REVISION_STALE", "The period changed since it was loaded; reload and try again",
                           status.HTTP_409_CONFLICT, {"current_revision": head.revision})
            update: dict = {"revision": head.revision + 1, "recorded_by": context.user_id, "recorded_at": _utcnow(),
                            "reason": reason, "request_id": request_id, "request_fingerprint": digest}
            if action == ACTION_VOID:
                update["record_kind"] = RECORD_VOID
            elif action == ACTION_CORRECT:
                if substate is not None and substate not in SUBSTATES:
                    raise _err("REPAIR_SUBSTATE_INVALID", "Unknown substate", status.HTTP_422_UNPROCESSABLE_ENTITY)
                start, end = self._validated_period(repair, started_at or head.started_at, ended_at)
                update.update({"record_kind": RECORD_CORRECTION, "substate": substate or head.substate,
                               "started_at": start, "ended_at": end})
            else:
                raise _err("WORK_TIME_ACTION_INVALID", "action must be CORRECT or VOID",
                           status.HTTP_422_UNPROCESSABLE_ENTITY)
            record = head.model_copy(update=update)
            if record.record_kind != RECORD_VOID and substate_conflict(record, latest.values()) is not None:
                raise _err("REPAIR_SUBSTATE_CONFLICT", "The corrected period overlaps another substate period",
                           status.HTTP_409_CONFLICT)
            try:
                return await self._repository.append_repair_substates([record])
            except ValueError as exc:
                raise _repository_refusal(exc) from exc

    async def substate_view(self, repair) -> dict:
        records = await self._repository.list_repair_substates(repair.repair_id)
        latest = current_revisions(records, "period_id")
        end_bound = repair.closed_at or repair.cancelled_at or _utcnow()
        opened = repair.opened_at.replace(microsecond=0)
        periods = sorted(latest.values(), key=lambda p: (p.started_at, p.period_id))
        return {"repair_id": repair.repair_id, "periods": periods,
                "history": sorted(records, key=lambda p: (p.recorded_at, p.period_id, p.revision)),
                "durations": substate_durations(periods, opened, end_bound), "as_of": end_bound}

    # ---------------------------------------------------------------- work time

    async def _member_set(self, work_kind: str, job_id: str, technician_id: str) -> str | None:
        """The latest V2 set of the job containing the technician (current or former member)."""
        state = (await self._assignments().read(REPAIR if work_kind == WORK_KIND_REPAIR else PM, job_id)).state
        sets = sorted((s for s in state.sets if technician_id in s.members), key=lambda s: s.assigned_at)
        return sets[-1].set_id if sets else None

    def _validated_values(self, started_at, ended_at, breaks, time_class, description):
        try:
            start, end = validate_interval(started_at, ended_at, _utcnow())
            return (start, end, validate_breaks(start, end, breaks), validate_time_class(time_class),
                    validate_description(description))
        except WorkTimeRuleError as exc:
            raise _rule(exc) from exc

    async def _entry_replay(self, work_kind: str, job_id: str, request_id: str, digest: str) -> WorkTimeEntry | None:
        earlier = [r for r in await self._repository.list_work_time_records(work_kind, job_id)
                   if r.request_id == request_id]
        if earlier and any(r.request_fingerprint != digest for r in earlier):
            raise _err("WORK_TIME_REQUEST_CONFLICT", "This request id was already used for another change; nothing "
                       "was changed", status.HTTP_409_CONFLICT)
        return earlier[0] if earlier else None

    async def _require_no_overlap(self, candidate: WorkTimeEntry) -> None:
        others = current_revisions(await self._repository.list_work_time_records_for_assignee(
            candidate.technician_id, candidate.is_test_data, candidate.test_batch_id), "entry_id").values()
        clash = find_overlap(candidate, others)
        if clash is not None:
            raise _err("WORK_TIME_OVERLAP", "This technician already has recorded work in this period",
                       status.HTTP_409_CONFLICT, {"work_kind": clash.work_kind, "job_id": clash.job_id,
                                                  "entry_id": clash.entry_id})

    async def _append(self, record: WorkTimeEntry) -> tuple[WorkTimeEntry, bool]:
        try:
            return await self._repository.append_work_time_record(record)
        except ValueError as exc:
            raise _repository_refusal(exc) from exc

    async def record_entry(self, work_kind: str, job_id: str, context: RequestContext | None, *,
                           body: Mapping[str, object], technician_id: str | None, started_at: datetime,
                           ended_at: datetime, breaks, time_class: str, description: str,
                           request_id: str) -> tuple[WorkTimeEntry, bool]:
        context = self._trusted(context)
        digest = fingerprint("work_time_entry", work_kind, job_id, body)
        async with self._locked(work_kind, job_id):
            job, data_context = await self._scoped_job(work_kind, job_id)
            earlier = await self._entry_replay(work_kind, job_id, request_id, digest)
            if earlier is not None:
                return earlier, True
            if not self._technician_window_open(work_kind, job):
                raise _err("WORK_TIME_WINDOW_CLOSED", "Work time can be recorded only while the work order is open "
                           "for work", status.HTTP_409_CONFLICT, {"status": self._status(job)})
            actor_technician = await self._actor_technician(context, data_context)
            if technician_id is not None and technician_id != actor_technician:
                raise _err("WORK_TIME_ON_BEHALF_REFUSED", "A technician records only their own work time",
                           status.HTTP_403_FORBIDDEN)
            if actor_technician is None:
                raise _err("WORK_TIME_ACTOR_NOT_TECHNICIAN", "Your account is not linked to a technician in this "
                           "data scope", status.HTTP_403_FORBIDDEN)
            member_set = await self._member_set(work_kind, job_id, actor_technician)
            if member_set is None:
                raise _err("WORK_TIME_NOT_MEMBER", "You are not (and were not) on this work order's technician team",
                           status.HTTP_403_FORBIDDEN)
            start, end, clean_breaks, klass, text = self._validated_values(started_at, ended_at, breaks, time_class,
                                                                           description)
            record = WorkTimeEntry(
                entry_id=f"WTE-{uuid.uuid4().hex[:16]}", revision=1, record_kind=RECORD_ENTRY, work_kind=work_kind,
                job_id=job_id, technician_id=actor_technician, started_at=start, ended_at=end, time_class=klass,
                description=text, breaks=clean_breaks, recorded_by=context.user_id, recorded_at=_utcnow(),
                request_id=request_id, request_fingerprint=digest, member_set_id=member_set,
                is_test_data=job.is_test_data, test_batch_id=job.test_batch_id)
            await self._require_no_overlap(record)
            return await self._append(record)

    async def revise_entry(self, work_kind: str, job_id: str, entry_id: str, context: RequestContext | None, *,
                           body: Mapping[str, object], action: str, expected_revision: int, reason: str | None,
                           started_at: datetime | None, ended_at: datetime | None, breaks, time_class: str | None,
                           description: str | None, request_id: str) -> tuple[WorkTimeEntry, bool]:
        context = self._trusted(context)
        digest = fingerprint("work_time_revision", work_kind, f"{job_id}/{entry_id}", body)
        try:
            reason = validate_reason(reason, required=True)
        except WorkTimeRuleError as exc:
            raise _rule(exc) from exc
        async with self._locked(work_kind, job_id):
            job, data_context = await self._scoped_job(work_kind, job_id)
            earlier = await self._entry_replay(work_kind, job_id, request_id, digest)
            if earlier is not None:
                return earlier, True
            latest = current_revisions(await self._repository.list_work_time_records(work_kind, job_id), "entry_id")
            head = latest.get(entry_id)
            if head is None:
                raise _err("WORK_TIME_ENTRY_NOT_FOUND", "No work-time entry has this id", status.HTTP_404_NOT_FOUND)
            if self._cancelled(work_kind, job):
                raise _err("WORK_TIME_WINDOW_CLOSED", "The work order was cancelled", status.HTTP_409_CONFLICT)
            manager = self._is_manager(work_kind, job, context)
            own = (await self._actor_technician(context, data_context)) == head.technician_id
            if not manager and not (own and self._technician_window_open(work_kind, job)):
                raise _err("WORK_TIME_CORRECTION_FORBIDDEN", "Only the entry's technician (while the work order is "
                           "open) or the work order's manager may correct this entry", status.HTTP_403_FORBIDDEN)
            if head.revision != expected_revision:
                raise _err("WORK_TIME_REVISION_STALE", "The entry changed since it was loaded; reload and try again",
                           status.HTTP_409_CONFLICT, {"current_revision": head.revision})
            if head.is_void:
                raise _err("WORK_TIME_ENTRY_VOID", "A voided entry cannot be changed", status.HTTP_409_CONFLICT)
            update: dict = {"revision": head.revision + 1, "recorded_by": context.user_id, "recorded_at": _utcnow(),
                            "reason": reason, "request_id": request_id, "request_fingerprint": digest}
            if action == ACTION_VOID:
                update["record_kind"] = RECORD_VOID
            elif action == ACTION_CORRECT:
                start, end, clean_breaks, klass, text = self._validated_values(
                    started_at, ended_at, breaks, time_class, description)
                update.update({"record_kind": RECORD_CORRECTION, "started_at": start, "ended_at": end,
                               "breaks": clean_breaks, "time_class": klass, "description": text})
            else:
                raise _err("WORK_TIME_ACTION_INVALID", "action must be CORRECT or VOID",
                           status.HTTP_422_UNPROCESSABLE_ENTITY)
            record = head.model_copy(update=update)
            if not record.is_void:
                await self._require_no_overlap(record)
            return await self._append(record)

    async def confirm(self, work_kind: str, job_id: str, context: RequestContext | None, *,
                      body: Mapping[str, object], entries: list[tuple[str, int]], note: str | None,
                      request_id: str) -> tuple[WorkTimeConfirmation | None, bool]:
        context = self._trusted(context)
        digest = fingerprint("work_time_confirmation", work_kind, job_id, body)
        async with self._locked(work_kind, job_id):
            job, data_context = await self._scoped_job(work_kind, job_id)
            if not self._is_manager(work_kind, job, context):
                raise _err("WORK_TIME_CONFIRMATION_FORBIDDEN", "Confirming work time requires this work order's "
                           f"manager authority ('{self._manager_capability(work_kind, job)}')",
                           status.HTTP_403_FORBIDDEN)
            confirmations = await self._repository.list_work_time_confirmations(work_kind, job_id)
            earlier = [c for c in confirmations if c.request_id == request_id]
            if earlier:
                if earlier[0].request_fingerprint != digest:
                    raise _err("WORK_TIME_REQUEST_CONFLICT", "This request id was already used for another change",
                               status.HTTP_409_CONFLICT)
                return earlier[0], True
            if self._cancelled(work_kind, job):
                raise _err("WORK_TIME_WINDOW_CLOSED", "The work order was cancelled", status.HTTP_409_CONFLICT)
            if not entries:
                raise _err("WORK_TIME_CONFIRMATION_EMPTY", "Name at least one entry revision",
                           status.HTTP_422_UNPROCESSABLE_ENTITY)
            latest = current_revisions(await self._repository.list_work_time_records(work_kind, job_id), "entry_id")
            confirmer_technician = await self._actor_technician(context, data_context)
            refs = []
            for entry_id, revision in entries:
                head = latest.get(entry_id)
                if head is None:
                    raise _err("WORK_TIME_ENTRY_NOT_FOUND", "No work-time entry has this id",
                               status.HTTP_404_NOT_FOUND, {"entry_id": entry_id})
                if head.revision != revision:
                    raise _err("WORK_TIME_REVISION_STALE", "The entry changed since it was loaded; only its current "
                               "revision can be confirmed", status.HTTP_409_CONFLICT,
                               {"entry_id": entry_id, "current_revision": head.revision})
                if confirmer_technician is not None and confirmer_technician == head.technician_id:
                    raise _err("WORK_TIME_SELF_CONFIRMATION_REFUSED", "A manager cannot confirm their own work time",
                               status.HTTP_403_FORBIDDEN, {"entry_id": entry_id})
                refs.append(entry_ref(entry_id, revision))
            if set(refs) <= confirmed_refs(confirmations):
                return None, True  # already confirmed exactly as asked: nothing new to record
            confirmation = WorkTimeConfirmation(
                confirmation_id=f"WTC-{uuid.uuid4().hex[:16]}", work_kind=work_kind, job_id=job_id,
                entries=tuple(refs), confirmed_by=context.user_id, confirmer_technician_id=confirmer_technician,
                confirmed_at=_utcnow(), note=note or None, request_id=request_id, request_fingerprint=digest,
                is_test_data=job.is_test_data, test_batch_id=job.test_batch_id)
            try:
                return await self._repository.append_work_time_confirmation(confirmation)
            except ValueError as exc:
                raise _repository_refusal(exc) from exc

    async def job_view(self, work_kind: str, job) -> dict:
        job_id = job.repair_id if work_kind == WORK_KIND_REPAIR else job.pm_work_order_id
        records = await self._repository.list_work_time_records(work_kind, job_id)
        confirmations = await self._repository.list_work_time_confirmations(work_kind, job_id)
        latest = current_revisions(records, "entry_id")
        refs = confirmed_refs(confirmations)
        end_bound = job.closed_at or getattr(job, "cancelled_at", None) or _utcnow()
        entries = []
        for head in sorted(latest.values(), key=lambda e: (e.started_at, e.entry_id)):
            entries.append({"entry": head, "confirmed": head.ref in refs,
                            "revisions": sorted((r for r in records if r.entry_id == head.entry_id),
                                                key=lambda r: r.revision)})
        per_technician = technician_totals(latest.values())
        opened = job.opened_at.replace(microsecond=0)
        return {"work_kind": work_kind, "job_id": job_id, "status": self._status(job), "entries": entries,
                "confirmations": sorted(confirmations, key=lambda c: c.confirmed_at),
                "technicians": per_technician, "team": team_totals(per_technician),
                "elapsed_seconds": max(int((end_bound - opened).total_seconds()), 0),
                "unconfirmed_count": len(unconfirmed_entries(records, confirmations))}

    async def technician_view(self, technician_id: str, context: RequestContext | None, window_start: datetime,
                              window_end: datetime) -> dict:
        context = self._trusted(context)
        data_context = await require_v2_write_context(self._cutover, self._repository)
        if not any(c in context.capabilities for c in MANAGER_CAPABILITIES):
            if await self._actor_technician(context, data_context) != technician_id:
                raise _err("WORK_TIME_READ_FORBIDDEN", "Reading another technician's work time requires a manager "
                           "capability", status.HTTP_403_FORBIDDEN)
        try:
            start, end = normalize_instant(window_start), normalize_instant(window_end)
        except WorkTimeRuleError as exc:
            raise _rule(exc) from exc
        if end <= start:
            raise _err("WORK_TIME_WINDOW_INVALID", "`to` must be after `from`", status.HTTP_422_UNPROCESSABLE_ENTITY)
        cells = scope_cells(data_context, self._cutover.test_batch_id)
        records = await self._repository.list_work_time_records_for_assignee(
            technician_id, cells["is_test_data"], cells["test_batch_id"])
        clipped = [c for e in current_revisions(records, "entry_id").values()
                   if not e.is_void and (c := _clip(e, start, end)) is not None]
        clipped.sort(key=lambda e: (e.started_at, e.entry_id))
        per_technician = technician_totals(clipped)
        return {"technician_id": technician_id, "from": start, "to": end, "entries": clipped,
                "totals": per_technician.get(technician_id, {"regular_seconds": 0, "overtime_seconds": 0,
                                                             "total_seconds": 0, "workdays": []})}

    # ---------------------------------------------------------------- lifecycle hooks

    async def require_all_confirmed(self, work_kind: str, job_id: str) -> None:
        """OD-2 close gate: zero recorded entries → no gate; otherwise every entry's
        current revision must be confirmed."""
        records = await self._repository.list_work_time_records(work_kind, job_id)
        if not records:
            return
        pending = unconfirmed_entries(records, await self._repository.list_work_time_confirmations(work_kind, job_id))
        if pending:
            raise _err("WORK_TIME_NOT_CONFIRMED", "Recorded technician work time must be confirmed by a manager before "
                       "this work order can be closed; nothing was changed", status.HTTP_409_CONFLICT,
                       {"unconfirmed_entries": len(pending)})

    async def recorded_work(self, work_kind: str, job_id: str) -> list[str]:
        """Cancellation blockers: R5 records that make a work order 'worked on'."""
        blockers = []
        if await self._repository.list_work_time_records(work_kind, job_id):
            blockers.append("WORK_TIME")
        if work_kind == WORK_KIND_REPAIR and await self._repository.list_repair_substates(job_id):
            blockers.append("REPAIR_SUBSTATE")
        return blockers


__all__ = ["ACTION_CORRECT", "ACTION_VOID", "WorkTimeService", "fingerprint"]
