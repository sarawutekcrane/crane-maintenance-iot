"""R2 Batch R2-C1 — E2 operational driver assignment service (Mock/TEST only).

Governance: C1 Amendment A2 and the owner decisions P1–P8, O1–O4, DQ-1–DQ-7.
The authority is `crane_operational_driver_assignment_history` (append-only,
revisioned; `operational_driver_timeline` derives everything). Three separate
concepts are never combined:
1. R2f-f permanent responsibility (`crane_driver_responsibility_history`):
   READ ONLY here, for the non-blocking "no permanent responsible driver"
   warning only; E2 never creates, ends, transfers or blocks it;
2. the Phase 6 `vehicle_driver` assignments: never read, migrated or written;
3. E2 — this module. It records the ASSIGNED driver, never verified driving.

O1 / DQ-1: E2 REAL writes are refused (409 E2_REAL_WRITES_NOT_ENABLED) before
any repository call, and the history read is the FIRST repository call of
every path, so the Google Sheets repository (which refuses it) is never asked
for a workbook value.

Write order: body rules (422) -> write context (503) -> REAL refusal (409) ->
ONE history read (tab-wide record-id / flag check, in-scope derivation) ->
vehicle locate -> stored references proven -> replay -> stale -> operation
rules -> after-state derivation and both-axis conflict check (409) ->
eligibility -> ONE atomic append (W1). After W1 the only outcomes are success,
E2_CONCURRENT_CHANGE (the mock's one-process version guard: nothing written)
and E2_HISTORY_WRITE_FAILED; nothing is retried.

Eligibility (DQ-2: the R2f-f rule as the behavioural contract, reimplemented
here): the driver resolves exactly once in scope; an assignment state with
any derived unit ending after now needs driver_master.active_status exactly
ACTIVE and an in-scope linked Personnel (if any) exactly ACTIVE; more than one
linked Personnel fails closed. O3: a state whose units have ALL elapsed may
name a currently INACTIVE driver (reason mandatory; reference, scope and
conflict checks still apply). CANCEL, EARLY_END and VOID never check
eligibility.

The mock version guard makes acceptance atomic in ONE process only. It is not a
cross-process or production transaction guarantee; that is R11 (B28 GATED).
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone

from fastapi import status

from app.domain.crane_driver_responsibility import classify_reference, reference_issues
from app.domain.crane_driver_timeline import (
    CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB,
    STATUS_VALID as RESPONSIBILITY_VALID,
    derive_responsibility_timeline,
)
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG, in_scope
from app.domain.operational_driver_timeline import (
    ASSIGNMENT,
    CANCELLATION,
    HANDOVER,
    HANDOVER_H2,
    HANDOVER_H3,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_CANCELLED,
    LIFECYCLE_VOIDED,
    MAX_START_AHEAD_DAYS,
    MODE_FULL_DAY,
    MODE_NIGHT_SHIFT,
    OP_CANCEL,
    OP_CREATE,
    OP_REVISE,
    OP_SUBSTITUTE,
    OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_COLUMNS,
    OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB,
    OPERATIONS,
    RELATION_SPLIT,
    RELATION_SUBSTITUTION,
    REVISION,
    SHIFT_MODES,
    STATUS_CONFLICTED,
    STATUS_INVALID,
    TRUE,
    AssignmentState,
    Conflict,
    HandoverState,
    Interval,
    Model,
    Schedule,
    adjacent_pairs,
    bangkok,
    bangkok_date,
    derive,
    handover_displaced,
    handover_structure_issue,
    iso,
    parse_date,
    parse_time,
    schedule_cells,
    schedule_issues,
    validate_row,
)
from app.domain.personnel_relationship import PERSONNEL_PREFIX, PERSONNEL_TAB, same_scope, scoped_personnel
from app.domain.reference_read import reference_read
from app.domain.registration import DATA_CONTEXT_REAL, DATA_CONTEXT_TEST, text
from app.domain.registry_write_support import error, require_write_context
from app.domain.request_replay import find_replay, request_fingerprint
from app.errors import ApiError
from app.repositories.base import (
    ReferenceMasterRead,
    RegistryTableRead,
    Repository,
    RepositoryConcurrentChangeError,
    RepositoryError,
    RepositoryWriteError,
)

OP_OPERATIONAL_DRIVER_ASSIGNMENT = "crane_operational_driver_assignment"  # the request-fingerprint operation name
HISTORY_PREFIX = "E2_HISTORY"
VEHICLE_PREFIX = "VEHICLE_MASTER"
DRIVER_PREFIX = "DRIVER_MASTER"
DRIVER_TAB = "driver_master"
VEHICLE_TAB = "vehicle_master"
RESPONSIBILITY_PREFIX = "CRANE_DRIVER_RESPONSIBILITY_HISTORY"
ACTIVE = "ACTIVE"
MAX_REASON_LENGTH = 500

REFERENCE_MISSING = "MISSING"
REFERENCE_AMBIGUOUS = "AMBIGUOUS"
REFERENCE_SCOPE_UNPROVEN = "SCOPE_UNPROVEN"

# warning codes (non-blocking; Thai presentation belongs to the frontend, G-3)
W_NO_PERMANENT_DRIVER = "NO_PERMANENT_RESPONSIBLE_DRIVER"
W_PERMANENT_UNDETERMINED = "PERMANENT_RESPONSIBILITY_UNDETERMINED"
W_ADJACENT = "ADJACENT_ASSIGNMENT_REST_WARNING"
W_DRIVER_NOT_ACTIVE = "DRIVER_NOT_ACTIVE"
W_FUTURE_DRIVER_NOT_ACTIVE = "FUTURE_ASSIGNMENT_DRIVER_NOT_ACTIVE_PENDING_REVIEW"

CURRENT_ASSIGNED = "ASSIGNED"
CURRENT_UNKNOWN = "UNKNOWN"
CURRENT_NONE = "NONE"
CURRENT_CONFLICTED = "CONFLICTED"


@dataclass(frozen=True)
class Warning:
    code: str
    event_id: str | None = None
    driver_id: str | None = None
    vehicle_id: str | None = None
    related_event_id: str | None = None


@dataclass(frozen=True)
class OperationOutcome:
    """A 200 outcome: changed (rows written), no-op / duplicate, or replay."""

    request_id: str
    changed: bool = False
    replayed: bool = False
    operation_id: str | None = None
    record_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    existing_event_id: str | None = None
    warnings: tuple[Warning, ...] = ()


@dataclass(frozen=True)
class UnknownSpan:
    vehicle_id: str
    start: datetime
    end: datetime
    handover_event_id: str


@dataclass(frozen=True)
class VehicleSchedule:
    vehicle_id: str
    timeline_status: str
    current_status: str
    current: Interval | None
    intervals: tuple[Interval, ...]
    unknown: tuple[UnknownSpan, ...]
    conflicts: tuple[Conflict, ...]
    warnings: tuple[Warning, ...]


@dataclass(frozen=True)
class DriverSchedule:
    driver_id: str
    timeline_status: str
    intervals: tuple[Interval, ...]
    conflicts: tuple[Conflict, ...]
    warnings: tuple[Warning, ...]


@dataclass(frozen=True)
class VehicleHistory:
    vehicle_id: str
    records: tuple[Mapping[str, object], ...]
    assignments: tuple[AssignmentState, ...]
    handovers: tuple[HandoverState, ...]


@dataclass
class _Ctx:
    context: str
    history: RegistryTableRead
    rows: list[Mapping[str, object]]  # every in-scope row (all vehicles: the driver axis needs them)
    model: Model
    vehicles: ReferenceMasterRead | None = None
    drivers: ReferenceMasterRead | None = None


@dataclass
class _Plan:
    """The rows one operation appends, the states it creates or changes and
    the events whose conflicts must be checked."""

    rows: list[dict[str, str]] = field(default_factory=list)
    touched: set[str] = field(default_factory=set)
    eligibility: list[str] = field(default_factory=list)  # event ids whose new state is eligibility-checked
    new_events: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def _unprocessable(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY, details)


def _conflict(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, status.HTTP_409_CONFLICT, details)


def _data_invalid(issues: dict[str, int]) -> ApiError:
    return error(f"{HISTORY_PREFIX}_DATA_INVALID",
                 f"{OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB} contains records that cannot be used exactly",
                 status.HTTP_500_INTERNAL_SERVER_ERROR,
                 {"tab": OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB, "issues": dict(sorted(issues.items()))})


_SCHEDULE_ERRORS = {
    "RANGE_INVALID": ("E2_RANGE_INVALID", "end_date must not be before start_date"),
    "RANGE_TOO_LONG": ("E2_RANGE_TOO_LONG", "An assignment covers at most 366 inclusive calendar days"),
    "SHIFT_REQUIRED": ("E2_SHIFT_REQUIRED", "DAY_SHIFT / NIGHT_SHIFT need explicit applied shift times"),
    "SHIFT_NOT_ALLOWED": ("E2_SHIFT_NOT_ALLOWED", "FULL_DAY takes no shift times"),
    "SHIFT_DURATION_INVALID": ("E2_SHIFT_DURATION_INVALID",
                               "A shift lasts more than 0 and at most 24 hours (equal times need end_day_offset 1)"),
    "MODE_INVALID": ("E2_MODE_INVALID", "Unknown assignment mode"),
    "EXCLUDED_DATE_OUT_OF_RANGE": ("E2_RANGE_INVALID", "The assignment range no longer contains its excluded dates"),
}


def _raise_schedule(sched: Schedule) -> None:
    issues = schedule_issues(sched)
    if issues:
        code, message = _SCHEDULE_ERRORS[issues[0]]
        details: dict[str, object] = {"issue": issues[0]}
        if issues[0] == "RANGE_TOO_LONG":
            details["limit"] = "DURATION"
        raise _unprocessable(code, message, details)


def _interval_details(i: Interval) -> dict[str, object]:
    return {"event_id": i.event_id, "vehicle_id": i.vehicle_id, "assigned_driver_id": i.driver_id,
            "label_date": i.label_date.isoformat(), "start": iso(i.start), "end": iso(i.end)}


# ---------------------------------------------------------------------------
# Body helpers (pure)
# ---------------------------------------------------------------------------


def _date(body: Mapping[str, object], name: str) -> date:
    parsed = parse_date(body.get(name))
    if parsed is None:
        raise _unprocessable("E2_DATE_INVALID", f"{name} must be a calendar date YYYY-MM-DD", {"field": name})
    return parsed


def _shift(body: Mapping[str, object]) -> tuple[time | None, time | None, int]:
    raw = body.get("shift")
    if raw is None:
        return None, None, 0
    assert isinstance(raw, Mapping)
    start, end = parse_time(raw.get("start_time")), parse_time(raw.get("end_time"))
    if start is None or end is None:
        raise _unprocessable("E2_TIME_INVALID", "Shift times must be HH:MM (00:00-23:59)", {"field": "shift"})
    offset = raw.get("end_day_offset")
    return start, end, int(offset) if isinstance(offset, int) else 0


def _reason(body: Mapping[str, object], *, required: bool) -> str:
    reason = body.get("reason_th")
    if reason is None and not required:
        return ""
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
        raise _unprocessable("REASON_REQUIRED", f"A reason of 1-{MAX_REASON_LENGTH} characters is required")
    return reason


def _excluded_within(dates: Sequence[date], start: date, end: date) -> tuple[date, ...]:
    return tuple(sorted(d for d in set(dates) if start <= d <= end))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OperationalDriverAssignmentService:
    def __init__(self, repository: Repository, data_context: str | None, test_batch_id: str) -> None:
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)

    # ---------------------------------------------------------------- reads

    async def _history(self) -> RegistryTableRead:
        """The FIRST repository call of every path (Sheets refuses it before any
        workbook request). Tab-wide: record ids unique, every test flag exact."""
        history = await reference_read(self._repository.read_operational_driver_assignment_history_validated(),
                                       HISTORY_PREFIX, OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB)
        ids = [text(r.get("record_id")) for r in history.rows if text(r.get("record_id"))]
        if len(ids) != len(set(ids)):
            raise _data_invalid({"RECORD_ID_DUPLICATE": len(ids) - len(set(ids))})
        bad = sum(1 for r in history.rows if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
        if bad:
            raise _data_invalid({"TEST_FLAG_INVALID": bad})
        return history

    async def _vehicles(self) -> ReferenceMasterRead:
        return await reference_read(self._repository.read_vehicle_reference(), VEHICLE_PREFIX, VEHICLE_TAB)

    async def _drivers(self) -> ReferenceMasterRead:
        return await reference_read(self._repository.read_driver_responsibility_reference(), DRIVER_PREFIX,
                                    DRIVER_TAB)

    async def _read(self, context: str) -> _Ctx:
        history = await self._history()
        rows = [r for r in history.rows if in_scope(r, context, self._batch_id)]
        model = derive(rows)
        if model.status == STATUS_INVALID:
            raise _data_invalid(model.issue_counts)
        return _Ctx(context, history, rows, model)

    async def _prove_references(self, ctx: _Ctx) -> None:
        """Every stored vehicle_id and driver_id of the in-scope rows resolves
        EXACTLY ONCE in the same scope (existence / uniqueness / scope only — an
        inactive historical driver stays valid history)."""
        vehicle_ids = {text(r.get("vehicle_id")) for r in ctx.rows}
        driver_ids = {text(r.get("driver_id")) for r in ctx.rows if text(r.get("driver_id"))}
        issues: dict[str, int] = {}
        if vehicle_ids:
            ctx.vehicles = ctx.vehicles or await self._vehicles()
            issues.update(reference_issues(vehicle_ids, ctx.vehicles, id_column="vehicle_id", label="VEHICLE",
                                           context=ctx.context, batch_id=self._batch_id))
        if driver_ids:
            ctx.drivers = ctx.drivers or await self._drivers()
            issues.update(reference_issues(driver_ids, ctx.drivers, id_column="driver_id", label="DRIVER",
                                           context=ctx.context, batch_id=self._batch_id))
        if issues:
            raise _data_invalid(issues)

    async def _locate_vehicle(self, ctx: _Ctx, vehicle_id: str) -> str:
        ctx.vehicles = ctx.vehicles or await self._vehicles()
        kind = classify_reference(vehicle_id, ctx.vehicles, "vehicle_id", ctx.context, self._batch_id) \
            if vehicle_id.strip() else REFERENCE_MISSING
        if kind == REFERENCE_AMBIGUOUS:
            raise _conflict("VEHICLE_ID_AMBIGUOUS", "More than one vehicle record has this id")
        if kind == REFERENCE_SCOPE_UNPROVEN:
            raise _unprocessable("VEHICLE_SCOPE_UNPROVEN",
                                 "This vehicle cannot be proven to belong to the request's data scope")
        if kind == REFERENCE_MISSING:
            raise error("VEHICLE_NOT_FOUND", "No vehicle record has exactly this id", status.HTTP_404_NOT_FOUND)
        return vehicle_id

    async def _driver_match(self, ctx: _Ctx, driver_id: str, *, not_found_status: int) -> Mapping[str, str]:
        ctx.drivers = ctx.drivers or await self._drivers()
        kind = classify_reference(driver_id, ctx.drivers, "driver_id", ctx.context, self._batch_id) \
            if driver_id.strip() else REFERENCE_MISSING
        if kind == REFERENCE_AMBIGUOUS:
            raise _conflict("DRIVER_ID_AMBIGUOUS", "More than one driver record has this driver_id",
                            {"driver_id": driver_id})
        if kind == REFERENCE_SCOPE_UNPROVEN:
            raise _unprocessable("DRIVER_SCOPE_UNPROVEN",
                                 "This driver cannot be proven to belong to the request's data scope",
                                 {"driver_id": driver_id})
        if kind == REFERENCE_MISSING:
            raise error("DRIVER_NOT_FOUND", "No driver record has exactly this driver_id", not_found_status,
                        {"driver_id": driver_id})
        (match,) = [r for r in ctx.drivers.rows if text(r.values.get("driver_id")) == driver_id
                    and same_scope(r, ctx.context, self._batch_id)]
        return match.values

    async def _check_driver(self, ctx: _Ctx, driver_id: str, *, require_active: bool) -> None:
        """NEW / forward-effective: ACTIVE driver and ACTIVE linked Personnel.
        O3 (elapsed only): reference, scope and Personnel-link integrity only."""
        values = await self._driver_match(ctx, driver_id, not_found_status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if require_active and text(values.get("active_status")) != ACTIVE:
            raise _unprocessable("DRIVER_NOT_ACTIVE",
                                 "Only an ACTIVE driver can be assigned for a current or future period",
                                 {"driver_id": driver_id})
        master = await reference_read(self._repository.read_personnel_relationship_master(), PERSONNEL_PREFIX,
                                      PERSONNEL_TAB)
        holders = [p for p in scoped_personnel(master.rows, ctx.context, self._batch_id)
                   if text(p.get("driver_id")) == driver_id]
        if len(holders) > 1:
            raise _conflict("DRIVER_PERSONNEL_AMBIGUOUS",
                            "More than one personnel record is linked to this driver; nothing was changed",
                            {"driver_id": driver_id, "match_count": len(holders)})
        if holders and require_active and text(holders[0].get("active_status")) != ACTIVE:
            raise _unprocessable("PERSONNEL_NOT_ACTIVE", "The personnel record linked to this driver is not ACTIVE",
                                 {"driver_id": driver_id})

    async def _permanent_warning(self, ctx: _Ctx, vehicle_id: str) -> Warning | None:
        """R2f-f READ ONLY (never written, never blocking): a vehicle with no
        current permanent responsible driver warns; an unreadable or undetermined
        R2f-f state warns too (A2-2.4, B02)."""
        try:
            history = await reference_read(self._repository.read_crane_driver_responsibility_history_validated(),
                                           RESPONSIBILITY_PREFIX, CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB)
            rows = [r for r in history.rows if text(r.get("vehicle_id")) == vehicle_id]
            if any(text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG) for r in rows):
                return Warning(W_PERMANENT_UNDETERMINED, vehicle_id=vehicle_id)
            timeline = derive_responsibility_timeline([r for r in rows if in_scope(r, ctx.context, self._batch_id)])
        except (ApiError, RepositoryError):
            return Warning(W_PERMANENT_UNDETERMINED, vehicle_id=vehicle_id)
        if timeline.status != RESPONSIBILITY_VALID:
            return Warning(W_PERMANENT_UNDETERMINED, vehicle_id=vehicle_id)
        if timeline.current_driver_id is None:  # R2f-f events are never future-dated
            return Warning(W_NO_PERMANENT_DRIVER, vehicle_id=vehicle_id)
        return None

    def _status_warnings(self, ctx: _Ctx, intervals: Sequence[Interval], now: datetime) -> list[Warning]:
        """A2-7.1 / B25 / B26: an assignment whose driver is (now) not ACTIVE is
        retained and flagged — never cancelled, never presented as fit."""
        out: list[Warning] = []
        seen: set[tuple[str, str]] = set()
        statuses: dict[str, str] = {}
        if ctx.drivers is not None:
            for r in ctx.drivers.rows:
                if same_scope(r, ctx.context, self._batch_id):
                    statuses[text(r.values.get("driver_id"))] = text(r.values.get("active_status"))
        for i in intervals:
            if statuses.get(i.driver_id, ACTIVE) == ACTIVE:
                continue
            code = W_FUTURE_DRIVER_NOT_ACTIVE if i.start > now else W_DRIVER_NOT_ACTIVE
            if (code, i.event_id) not in seen:
                seen.add((code, i.event_id))
                out.append(Warning(code, event_id=i.event_id, driver_id=i.driver_id, vehicle_id=i.vehicle_id))
        return out

    @staticmethod
    def _adjacency_warnings(model: Model, events: set[str] | None = None,
                            vehicle_id: str | None = None, driver_id: str | None = None) -> list[Warning]:
        out: list[Warning] = []
        for a, b in adjacent_pairs(model.intervals):
            if events is not None and not ({a.event_id, b.event_id} & events):
                continue
            if vehicle_id is not None and vehicle_id not in (a.vehicle_id, b.vehicle_id):
                continue
            if driver_id is not None and a.driver_id != driver_id:
                continue
            out.append(Warning(W_ADJACENT, event_id=b.event_id, driver_id=a.driver_id, vehicle_id=b.vehicle_id,
                               related_event_id=a.event_id))
        return out

    # ---------------------------------------------------------------- read API

    @staticmethod
    def _in_window(start: datetime, end: datetime, date_from: date | None, date_to: date | None) -> bool:
        """G-1: the optional inclusive Bangkok date range [from 00:00, to+1 00:00)."""
        return (date_from is None or end > bangkok(date_from)) and (
            date_to is None or start < bangkok(date_to + timedelta(1)))

    def _window(self, intervals: Sequence[Interval], date_from: date | None, date_to: date | None,
                mode: str | None) -> list[Interval]:
        return [i for i in intervals if self._in_window(i.start, i.end, date_from, date_to)
                and (mode is None or i.mode == mode)]

    async def vehicle_schedule(self, vehicle_id: str, *, date_from: date | None = None, date_to: date | None = None,
                               mode: str | None = None) -> VehicleSchedule:
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(context)
        located = await self._locate_vehicle(ctx, vehicle_id)
        await self._prove_references(ctx)
        now = self._now()
        model = ctx.model
        own = [i for i in model.intervals if i.vehicle_id == located]
        unknown = tuple(UnknownSpan(v, s, e, h) for v, s, e, h in model.unknown if v == located)
        conflicts = tuple(c for c in model.conflicts if located in (c.first.vehicle_id, c.second.vehicle_id))
        vehicle_conflicted = model.vehicle_status(located) == STATUS_CONFLICTED
        current = None
        if any(c.axis == "VEHICLE" and c.key == located
               and max(c.first.start, c.second.start) <= now < min(c.first.end, c.second.end) for c in conflicts):
            current_status = CURRENT_CONFLICTED  # never a guessed driver (A2-5.6)
        else:
            current = next((i for i in own if i.start <= now < i.end), None)
            if current is not None:
                current_status = CURRENT_ASSIGNED
            elif any(u.start <= now < u.end for u in unknown):
                current_status = CURRENT_UNKNOWN
            else:
                current_status = CURRENT_NONE
        warnings: list[Warning] = []
        permanent = await self._permanent_warning(ctx, located)
        if permanent is not None:
            warnings.append(permanent)
        warnings += self._status_warnings(ctx, own, now)
        warnings += self._adjacency_warnings(model, vehicle_id=located)
        return VehicleSchedule(
            vehicle_id=located,
            timeline_status=STATUS_CONFLICTED if vehicle_conflicted else "VALID",
            current_status=current_status,
            current=current,
            intervals=tuple(self._window(own, date_from, date_to, mode)),
            unknown=tuple(u for u in unknown if self._in_window(u.start, u.end, date_from, date_to)),
            conflicts=conflicts,
            warnings=tuple(warnings),
        )

    async def driver_schedule(self, driver_id: str, *, date_from: date | None = None, date_to: date | None = None,
                              mode: str | None = None) -> DriverSchedule:
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(context)
        await self._driver_match(ctx, driver_id, not_found_status=status.HTTP_404_NOT_FOUND)
        await self._prove_references(ctx)
        now = self._now()
        model = ctx.model
        own = [i for i in model.intervals if i.driver_id == driver_id]
        conflicts = tuple(c for c in model.conflicts if driver_id in (c.first.driver_id, c.second.driver_id))
        driver_conflicted = any(c.axis == "DRIVER" and c.key == driver_id for c in conflicts)
        warnings = self._status_warnings(ctx, own, now) + self._adjacency_warnings(model, driver_id=driver_id)
        return DriverSchedule(
            driver_id=driver_id,
            timeline_status=STATUS_CONFLICTED if driver_conflicted else "VALID",
            intervals=tuple(self._window(own, date_from, date_to, mode)),
            conflicts=conflicts,
            warnings=tuple(warnings),
        )

    async def vehicle_history(self, vehicle_id: str) -> VehicleHistory:
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(context)
        located = await self._locate_vehicle(ctx, vehicle_id)
        await self._prove_references(ctx)
        records = tuple(r for r in ctx.rows if text(r.get("vehicle_id")) == located)
        return VehicleHistory(
            vehicle_id=located,
            records=records,
            assignments=tuple(a for a in ctx.model.assignments.values() if a.vehicle_id == located),
            handovers=tuple(h for h in ctx.model.handovers.values() if h.vehicle_id == located),
        )

    # ---------------------------------------------------------------- write helpers

    def _base_row(self, ctx: _Ctx, *, vehicle_id: str, operation: str, operation_id: str, request_id: str,
                  fingerprint: str, user_id: str, recorded_at: datetime, reason: str) -> dict[str, str]:
        row = dict.fromkeys(OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_COLUMNS, "")
        row.update(
            record_id=f"ODA-{uuid.uuid4().hex}",
            operation_id=operation_id,
            entry_operation=operation,
            vehicle_id=vehicle_id,
            reason_th=reason,
            recorded_at=recorded_at.isoformat(timespec="microseconds"),
            recorded_by=user_id,
            request_id=request_id,
            request_fingerprint=fingerprint,
            is_test_data=TEST_FLAG if ctx.context == DATA_CONTEXT_TEST else OPERATIONAL_FLAG,
            test_batch_id=self._batch_id if ctx.context == DATA_CONTEXT_TEST else "",
        )
        return row

    @staticmethod
    def _state_cells(sched: Schedule, driver_id: str, *, early_end_at: datetime | None = None, voided: bool = False,
                     related: tuple[str, str] | None = None) -> dict[str, str]:
        cells = schedule_cells(sched)
        cells.update(driver_id=driver_id, early_end_at=iso(early_end_at) if early_end_at else "",
                     voided=TRUE if voided else "")
        if related:
            cells.update(related_event_id=related[0], relation=related[1])
        return cells

    @staticmethod
    def _target(ctx: _Ctx, vehicle_id: str, body: Mapping[str, object]) -> AssignmentState:
        event_id = text(body.get("event_id"))
        target = ctx.model.assignments.get(event_id)
        if target is None or target.vehicle_id != vehicle_id:
            raise error("E2_ASSIGNMENT_NOT_FOUND", "No E2 assignment with this event_id exists for this vehicle",
                        status.HTTP_404_NOT_FOUND, {"event_id": event_id})
        if body.get("expected_revision_no") != target.revision_no:
            raise _conflict("E2_ASSIGNMENT_STALE",
                            "The assignment changed since it was loaded; reload and try again",
                            {"event_id": event_id, "field": "revision_no"})
        if target.lifecycle == LIFECYCLE_CANCELLED:
            raise _conflict("E2_ASSIGNMENT_CANCELLED", "This assignment was cancelled; nothing was changed",
                            {"event_id": event_id})
        if target.lifecycle == LIFECYCLE_VOIDED:
            raise _conflict("E2_ASSIGNMENT_VOIDED", "This assignment was voided; nothing was changed",
                            {"event_id": event_id})
        return target

    @staticmethod
    def _started(model: Model, a: AssignmentState, now: datetime) -> bool:
        intervals = model.intervals_of(a.event_id)
        return bool(intervals) and min(i.start for i in intervals) <= now

    @staticmethod
    def _horizon(sched: Schedule, now: datetime) -> None:
        if (sched.start_date - bangkok_date(now)).days > MAX_START_AHEAD_DAYS:
            raise _unprocessable("E2_RANGE_TOO_LONG",
                                 "A start date may be at most 366 Bangkok calendar days in the future",
                                 {"issue": "RANGE_TOO_LONG", "limit": "START_HORIZON"})

    # ---------------------------------------------------------------- handovers

    def _handover_rows(self, ctx: _Ctx, states: dict[str, AssignmentState], plan: _Plan, now: datetime,
                       base: dict[str, object], *, correction: bool,
                       remap: dict[str, dict[str, str]] | None = None) -> None:
        """Revalidate every in-force handover linked to a changed assignment
        (A2-4.7, DQ-3) against the NEW states of both parties:
        - keep it in step (a HANDOVER revision with the new party revisions,
          parties moved by a split or a boundary substitution via `remap`
          {"PRED" | "SUCC": {old event: new event}}, and the new instant);
        - before it takes effect: cancel it when it no longer applies (the
          freed coverage is then conflict-checked like any other);
        - after it took effect: a reasoned correction (REVISE / split / VOID)
          may correct the applied time or the parties, but elapsed time is
          never given back to the side that gave it — that time becomes the
          handover's UNKNOWN span (withheld from the giver, shown UNKNOWN where
          nobody covers it). A change that breaks the boundary's dates is
          refused (E2_HANDOVER_INVALIDATED): void the wrong assignment and
          re-record the facts instead. A handover with a VOIDED party is frozen
          at its recorded instant."""
        remap = remap or {}
        for h in list(ctx.model.handovers.values()):
            if not h.in_force:
                continue
            pred_id = remap.get("PRED", {}).get(h.predecessor_event_id, h.predecessor_event_id)
            succ_id = remap.get("SUCC", {}).get(h.successor_event_id, h.successor_event_id)
            if not ({h.predecessor_event_id, h.successor_event_id, pred_id, succ_id} & set(states)):
                continue
            pred = states.get(pred_id) or ctx.model.assignments[pred_id]
            succ = states.get(succ_id) or ctx.model.assignments[succ_id]
            plan.touched.update({h.predecessor_event_id, h.successor_event_id, pred.event_id, succ.event_id})
            effective = h.handover_at <= now
            frozen = LIFECYCLE_VOIDED in (pred.lifecycle, succ.lifecycle)
            if frozen:
                new_at = h.handover_at
            else:
                new_at = (succ.schedule.unit(succ.schedule.start_date)[0] if h.kind == HANDOVER_H2
                          else pred.schedule.unit(pred.schedule.end_date)[1])
                cancelled = LIFECYCLE_CANCELLED in (pred.lifecycle, succ.lifecycle)
                if cancelled or handover_structure_issue(h.kind, pred, succ, new_at) is not None:
                    if effective:
                        raise _conflict("E2_HANDOVER_INVALIDATED",
                                        "This change would break the dates of a handover that has already taken "
                                        "effect; void the wrong assignment and re-record the facts instead",
                                        {"handover_event_id": h.event_id})
                    plan.rows.append({**base, "record_kind": CANCELLATION, "event_id": h.event_id,
                                      "revision_no": str(int(h.revision_no) + 1),
                                      "supersedes_record_id": h.head_record_id,
                                      "record_id": f"ODA-{uuid.uuid4().hex}"})  # type: ignore[arg-type]
                    continue  # A2-5.2: revoked before it took effect
                if effective and new_at != h.handover_at and not correction:
                    raise _conflict("E2_HANDOVER_INVALIDATED", "Only a reasoned correction may move a handover "
                                    "that has already taken effect", {"handover_event_id": h.event_id})
            unknown = h.unknown
            if correction and effective:
                spans = [handover_displaced(h.kind, pred, succ, h.handover_at)]
                lo, hi = sorted((h.handover_at, new_at))
                if lo < hi and ((h.kind == HANDOVER_H2 and new_at > h.handover_at)
                                or (h.kind == HANDOVER_H3 and new_at < h.handover_at)):
                    spans.append((lo, hi))  # the giver would regain [lo, hi): withheld, never restored
                if unknown:
                    spans.append(unknown)
                us, ue = min(x for x, _ in spans), min(max(y for _, y in spans), now)  # elapsed only
                unknown = (us, ue) if us < ue else unknown
            if (pred.event_id, pred.revision_no, succ.event_id, succ.revision_no, new_at, unknown) == (
                    h.predecessor_event_id, h.predecessor_revision_no, h.successor_event_id,
                    h.successor_revision_no, h.handover_at, h.unknown):
                continue
            plan.rows.append({**base, "record_kind": HANDOVER, "event_id": h.event_id,
                              "revision_no": str(int(h.revision_no) + 1), "supersedes_record_id": h.head_record_id,
                              "record_id": f"ODA-{uuid.uuid4().hex}", "handover_kind": h.kind,
                              "predecessor_event_id": pred.event_id, "predecessor_revision_no": pred.revision_no,
                              "successor_event_id": succ.event_id, "successor_revision_no": succ.revision_no,
                              "handover_at": iso(new_at),
                              "unknown_start_at": iso(unknown[0]) if unknown else "",
                              "unknown_end_at": iso(unknown[1]) if unknown else ""})  # type: ignore[arg-type]

    # ---------------------------------------------------------------- operations

    @staticmethod
    def _next_state(a: AssignmentState, row: Mapping[str, object]) -> AssignmentState:
        from app.domain.operational_driver_timeline import schedule_of

        sched = schedule_of(row)
        assert sched is not None
        voided = text(row.get("voided")) == TRUE
        early = text(row.get("early_end_at"))
        return replace(a, revision_no=text(row.get("revision_no")), head_record_id=text(row.get("record_id")),
                       head=row, schedule=sched, driver_id=text(row.get("driver_id")),
                       lifecycle=LIFECYCLE_VOIDED if voided else LIFECYCLE_ACTIVE,
                       early_end_at=datetime.fromisoformat(early) if early else None)

    def _revision_row(self, a: AssignmentState, base: dict[str, object], cells: dict[str, str]) -> dict[str, str]:
        row = {**base, **cells, "record_kind": REVISION, "event_id": a.event_id,
               "revision_no": str(int(a.revision_no) + 1), "supersedes_record_id": a.head_record_id,
               "record_id": f"ODA-{uuid.uuid4().hex}"}
        if a.related_event_id and "relation" not in cells:
            row.update(related_event_id=a.related_event_id, relation=a.relation)
        return row  # type: ignore[return-value]

    def _new_assignment_row(self, base: dict[str, object], cells: dict[str, str]) -> dict[str, str]:
        record_id = f"ODA-{uuid.uuid4().hex}"
        return {**base, **cells, "record_kind": ASSIGNMENT, "event_id": record_id, "revision_no": "1",
                "record_id": record_id}  # type: ignore[return-value]

    def _schedule_from_body(self, body: Mapping[str, object], mode: str) -> Schedule:
        start, end = _date(body, "start_date"), _date(body, "end_date")
        s, e, offset = _shift(body)
        sched = Schedule(mode, start, end, s, e, offset)
        _raise_schedule(sched)
        return sched

    async def _create(self, ctx: _Ctx, vehicle_id: str, body: Mapping[str, object], base: dict[str, object],
                      now: datetime, plan: _Plan) -> OperationOutcome | None:
        driver = text(body.get("driver_id"))
        sched = self._schedule_from_body(body, text(body.get("mode")))
        self._horizon(sched, now)
        if sched.start_date < bangkok_date(now):
            _reason(body, required=True)  # A2-5.4: backdated create; a same-day create needs no reason
        model = ctx.model
        if model.vehicle_status(vehicle_id) == STATUS_CONFLICTED:
            raise _conflict("E2_TIMELINE_CONFLICTED", "This vehicle's E2 timeline has a residual conflict; resolve "
                            "it by an authorized correction first", {"vehicle_id": vehicle_id})
        for a in model.assignments.values():  # A3.6 / B27: an identical active assignment is not duplicated
            if (a.vehicle_id, a.driver_id, a.lifecycle, a.schedule, a.early_end_at) == (
                    vehicle_id, driver, LIFECYCLE_ACTIVE, sched, None):
                return OperationOutcome(request_id=text(base["request_id"]), changed=False,
                                        existing_event_id=a.event_id)
        row = self._new_assignment_row(base, self._state_cells(sched, driver))
        plan.rows.append(row)
        plan.new_events.append(row["event_id"])
        plan.eligibility.append(row["event_id"])
        plan.touched.add(row["event_id"])
        handover = body.get("handover")
        if isinstance(handover, Mapping):
            pred_id = text(handover.get("predecessor_event_id"))
            pred = model.assignments.get(pred_id)
            if pred is None or pred.vehicle_id != vehicle_id:
                raise error("E2_ASSIGNMENT_NOT_FOUND", "The handover predecessor does not exist for this vehicle",
                            status.HTTP_404_NOT_FOUND, {"event_id": pred_id})
            if handover.get("expected_revision_no") != pred.revision_no:
                raise _conflict("E2_ASSIGNMENT_STALE", "The predecessor changed since it was loaded; reload",
                                {"event_id": pred_id, "field": "revision_no"})
            if pred.lifecycle != LIFECYCLE_ACTIVE:
                raise _conflict("E2_HANDOVER_NOT_PERMITTED", "The predecessor is not an active assignment",
                                {"event_id": pred_id})
            new = AssignmentState(row["event_id"], vehicle_id, "1", row["record_id"], row, sched, driver,
                                  LIFECYCLE_ACTIVE, None, "", "")
            if pred.schedule.mode == MODE_FULL_DAY and sched.mode == MODE_NIGHT_SHIFT:
                kind, p, s = HANDOVER_H2, pred, new
                at = sched.unit(sched.start_date)[0]
            elif pred.schedule.mode == MODE_NIGHT_SHIFT and sched.mode == MODE_FULL_DAY:
                kind, p, s = HANDOVER_H3, pred, new
                at = pred.schedule.unit(pred.schedule.end_date)[1]
            else:
                raise _conflict("E2_HANDOVER_NOT_PERMITTED", "Only the H2 (FULL_DAY -> NIGHT_SHIFT on its last "
                                "date) and E2-H3 (NIGHT_SHIFT -> next-day FULL_DAY) boundary handovers exist")
            issue = handover_structure_issue(kind, p, s, at)
            if issue is None and p.schedule.end_date in p.schedule.excluded:
                issue = "HANDOVER_NOT_PERMITTED"  # the predecessor holds no boundary unit
            if issue is not None:
                raise _conflict("E2_HANDOVER_NOT_PERMITTED", "This is not a permitted boundary handover; nothing "
                                "was changed", {"issue": issue, "handover_kind": kind})
            if any(h.in_force and h.predecessor_event_id == pred.event_id for h in model.handovers.values()):
                raise _conflict("E2_HANDOVER_NOT_PERMITTED", "The predecessor already hands over",
                                {"event_id": pred.event_id})
            if pred.early_end_at is not None and pred.early_end_at <= at:
                raise _conflict("E2_HANDOVER_NOT_PERMITTED", "The predecessor already ended before the handover",
                                {"event_id": pred.event_id})
            record_id = f"ODA-{uuid.uuid4().hex}"
            plan.rows.append({**base, "record_kind": HANDOVER, "event_id": record_id, "revision_no": "1",
                              "record_id": record_id, "handover_kind": kind, "predecessor_event_id": p.event_id,
                              "predecessor_revision_no": p.revision_no, "successor_event_id": s.event_id,
                              "successor_revision_no": "1", "handover_at": iso(at)})  # type: ignore[arg-type]
            plan.touched.add(pred.event_id)
        return None

    async def _revise(self, ctx: _Ctx, a: AssignmentState, body: Mapping[str, object], base: dict[str, object],
                      now: datetime, plan: _Plan) -> OperationOutcome | None:
        model = ctx.model
        if body.get("void_elapsed") is True:
            # DQ-6: an erroneous elapsed record is voided (never deleted); not-yet-started -> CANCEL.
            if not self._started(model, a, now):
                raise _conflict("E2_ASSIGNMENT_NOT_STARTED", "Only a started assignment can be voided; cancel a "
                                "future assignment instead", {"event_id": a.event_id})
            row = self._revision_row(a, base, self._state_cells(a.schedule, a.driver_id, early_end_at=a.early_end_at,
                                                                 voided=True))
            plan.rows.append(row)
            plan.touched.add(a.event_id)
            self._handover_rows(ctx, {a.event_id: self._next_state(a, row)}, plan, now, base, correction=True)
            return None
        driver = text(body.get("driver_id"))
        sched = self._schedule_from_body(body, a.schedule.mode)
        split = body.get("split_from_date")
        if split is not None and body.get("exclude_dates") is not None:
            raise _unprocessable("E2_SPLIT_INVALID", "A split takes no exclude_dates; exclude units separately")
        if split is not None:
            # A2-3.5 / B17: applied times change from date D; the original keeps D-1 and before.
            day = _date(body, "split_from_date")
            if a.schedule.mode not in SHIFT_MODES or a.early_end_at is not None:
                raise _unprocessable("E2_SPLIT_INVALID", "Only an un-ended shift assignment can be split")
            if (driver, sched.start_date, sched.end_date) != (a.driver_id, a.schedule.start_date, a.schedule.end_date):
                raise _unprocessable("E2_SPLIT_INVALID", "A split changes only the applied shift times; send the "
                                     "current driver and dates unchanged")
            if not a.schedule.start_date < day <= a.schedule.end_date:
                raise _unprocessable("E2_SPLIT_INVALID", "split_from_date must be after the first date and within "
                                     "the assignment")
            if (sched.shift_start, sched.shift_end, sched.shift_offset) == (
                    a.schedule.shift_start, a.schedule.shift_end, a.schedule.shift_offset):
                return OperationOutcome(request_id=text(base["request_id"]), changed=False)
            first = replace(a.schedule, end_date=day - timedelta(1),
                            excluded=_excluded_within(a.schedule.excluded, a.schedule.start_date, day - timedelta(1)))
            second = replace(sched, start_date=day, excluded=_excluded_within(a.schedule.excluded, day,
                                                                             a.schedule.end_date))
            self._horizon(second, now)
            _raise_schedule(second)
            head = self._revision_row(a, base, self._state_cells(first, a.driver_id))
            new = self._new_assignment_row(base, self._state_cells(second, a.driver_id,
                                                                   related=(a.event_id, RELATION_SPLIT)))
            plan.rows += [head, new]
            plan.new_events.append(new["event_id"])
            plan.eligibility += [a.event_id, new["event_id"]]
            plan.touched.update({a.event_id, new["event_id"]})
            new_state = AssignmentState(new["event_id"], a.vehicle_id, "1", new["record_id"], new, second, a.driver_id,
                                        LIFECYCLE_ACTIVE, None, a.event_id, RELATION_SPLIT)
            # the last date (an E2-H3 predecessor's boundary) now belongs to the new segment
            self._handover_rows(ctx, {a.event_id: self._next_state(a, head), new["event_id"]: new_state}, plan, now,
                                base, correction=True, remap={"PRED": {a.event_id: new["event_id"]}})
            return None
        if body.get("exclude_dates") is not None and split is None:
            # F3: specific erroneous units are removed; every other unit and the original rows stay.
            extra = [parse_date(d) for d in body["exclude_dates"]]  # type: ignore[union-attr]
            if any(d is None or not sched.start_date <= d <= sched.end_date for d in extra):
                raise _unprocessable("E2_DATE_INVALID", "exclude_dates must be dates within the assignment",
                                     {"field": "exclude_dates"})
            kept = _excluded_within(a.schedule.excluded, sched.start_date, sched.end_date)
            sched = replace(sched, excluded=tuple(sorted({*kept, *(d for d in extra if d is not None)})))
        else:
            sched = replace(sched, excluded=_excluded_within(a.schedule.excluded, sched.start_date, sched.end_date))
        if sched.start_date != a.schedule.start_date:
            self._horizon(sched, now)
        if (driver, sched) == (a.driver_id, a.schedule):
            return OperationOutcome(request_id=text(base["request_id"]), changed=False)
        row = self._revision_row(a, base, self._state_cells(sched, driver, early_end_at=a.early_end_at))
        plan.rows.append(row)
        plan.eligibility.append(a.event_id)
        plan.touched.add(a.event_id)
        self._handover_rows(ctx, {a.event_id: self._next_state(a, row)}, plan, now, base, correction=True)
        return None

    async def _substitute(self, ctx: _Ctx, a: AssignmentState, body: Mapping[str, object], base: dict[str, object],
                          now: datetime, plan: _Plan) -> None:
        """A2-4.8 / O4 / B19 / B24: whole calendar days (FULL_DAY) or whole shifts;
        unaffected units stay with the original assignment."""
        raw = body.get("dates")
        assert isinstance(raw, list)
        days = [parse_date(d) for d in raw]
        if any(d is None for d in days) or len(set(days)) != len(days):
            raise _unprocessable("E2_DATE_INVALID", "dates must be distinct calendar dates YYYY-MM-DD",
                                 {"field": "dates"})
        chosen = sorted(d for d in days if d is not None)
        driver = text(body.get("driver_id"))
        if driver == a.driver_id:
            raise _unprocessable("E2_SUBSTITUTION_DRIVER_UNCHANGED", "The substitute must be a different driver")
        own: dict[date, list[Interval]] = {}
        for i in ctx.model.intervals_of(a.event_id):
            own.setdefault(i.label_date, []).append(i)
        boundary: dict[date, str] = {}  # the handover boundary units of this assignment -> its role
        for h in ctx.model.handovers_of(a.event_id):
            if h.predecessor_event_id == a.event_id:
                boundary[a.schedule.end_date] = "PRED"
            if h.successor_event_id == a.event_id:
                boundary[a.schedule.start_date] = "SUCC"
        for d in chosen:
            units = own.get(d, [])
            whole = len(units) == 1 and (units[0].start, units[0].end) == a.schedule.unit(d)
            # F2: a boundary unit is the whole unit this assignment holds after the
            # handover; the substitute takes it AND the assignment's place in the handover.
            held = len(units) == 1 and d in boundary and (a.early_end_at is None
                                                         or a.early_end_at >= a.schedule.unit(d)[1])
            if not (whole or held):
                raise _conflict("E2_SUBSTITUTION_UNIT_INVALID",
                                "Only a whole calendar day / whole shift of this assignment can be substituted",
                                {"date": d.isoformat()})
        head = self._revision_row(a, base, self._state_cells(
            replace(a.schedule, excluded=tuple(sorted({*a.schedule.excluded, *chosen}))), a.driver_id,
            early_end_at=a.early_end_at))
        span = Schedule(a.schedule.mode, chosen[0], chosen[-1], a.schedule.shift_start, a.schedule.shift_end,
                        a.schedule.shift_offset)
        gaps = tuple(d for d in (chosen[0] + timedelta(n) for n in range(span.range_days)) if d not in set(chosen))
        span = replace(span, excluded=gaps)
        new = self._new_assignment_row(base, self._state_cells(span, driver,
                                                               related=(a.event_id, RELATION_SUBSTITUTION)))
        plan.rows += [head, new]
        plan.new_events.append(new["event_id"])
        plan.eligibility.append(new["event_id"])
        plan.touched.update({a.event_id, new["event_id"]})
        new_state = AssignmentState(new["event_id"], a.vehicle_id, "1", new["record_id"], new, span, driver,
                                    LIFECYCLE_ACTIVE, None, a.event_id, RELATION_SUBSTITUTION)
        remap = {role: {a.event_id: new["event_id"]} for d, role in boundary.items() if d in chosen}
        self._handover_rows(ctx, {a.event_id: self._next_state(a, head), new["event_id"]: new_state}, plan, now,
                            base, correction=bool(remap), remap=remap)

    async def _cancel(self, ctx: _Ctx, a: AssignmentState, base: dict[str, object], now: datetime,
                      plan: _Plan) -> None:
        """A2-5.1 / DQ-3: only before the assignment's derived start."""
        if self._started(ctx.model, a, now):
            raise _conflict("E2_ASSIGNMENT_ALREADY_STARTED", "A started assignment cannot be cancelled; use "
                            "EARLY_END, or REVISE (correction / void_elapsed)", {"event_id": a.event_id})
        row = {**base, "record_kind": CANCELLATION, "event_id": a.event_id,
               "revision_no": str(int(a.revision_no) + 1), "supersedes_record_id": a.head_record_id,
               "record_id": f"ODA-{uuid.uuid4().hex}"}
        plan.rows.append(row)  # type: ignore[arg-type]
        plan.touched.add(a.event_id)
        self._handover_rows(ctx, {a.event_id: replace(a, lifecycle=LIFECYCLE_CANCELLED)}, plan, now, base,
                            correction=False)

    async def _early_end(self, ctx: _Ctx, a: AssignmentState, body: Mapping[str, object], base: dict[str, object],
                         now: datetime, plan: _Plan) -> OperationOutcome | None:
        """DQ-3: a started assignment ends; its elapsed assigned history stays
        ASSIGNED (never UNKNOWN), nothing is given back to anyone (A5.4)."""
        intervals = ctx.model.intervals_of(a.event_id)
        if not self._started(ctx.model, a, now):
            raise _conflict("E2_ASSIGNMENT_NOT_STARTED", "This assignment has not started; cancel it instead",
                            {"event_id": a.event_id})
        if max(i.end for i in intervals) <= now:
            raise _conflict("E2_ASSIGNMENT_ALREADY_ENDED", "This assignment has already ended",
                            {"event_id": a.event_id})
        end = body.get("end")
        assert isinstance(end, Mapping)
        if end.get("mode") == "NOW":
            sched, early = a.schedule, now
        else:
            day = parse_date(end.get("date"))
            if day is None:
                raise _unprocessable("E2_DATE_INVALID", "end.date must be a calendar date", {"field": "end.date"})
            if not (bangkok_date(now) <= day < a.schedule.end_date and a.schedule.start_date <= day):
                raise _unprocessable("E2_EARLY_END_INVALID", "end.date must be today or later, within the "
                                     "assignment and before its last date")
            sched = replace(a.schedule, end_date=day,
                            excluded=_excluded_within(a.schedule.excluded, a.schedule.start_date, day))
            early = a.early_end_at
        row = self._revision_row(a, base, self._state_cells(sched, a.driver_id, early_end_at=early))
        plan.rows.append(row)
        plan.touched.add(a.event_id)
        self._handover_rows(ctx, {a.event_id: self._next_state(a, row)}, plan, now, base, correction=False)
        return None

    # ---------------------------------------------------------------- entry

    async def apply(self, vehicle_id: str, body: Mapping[str, object], *, request_id: str,
                    user_id: str) -> OperationOutcome:
        operation = text(body.get("operation"))
        if operation not in OPERATIONS:  # the schema already refuses; defensive
            raise _unprocessable("E2_OPERATION_INVALID", "Unknown E2 operation")
        reason = _reason(body, required=operation != OP_CREATE)
        if operation == OP_REVISE and body.get("void_elapsed") is True:
            extra = [n for n in ("driver_id", "start_date", "end_date", "shift", "split_from_date", "exclude_dates")
                     if n in body]
            if extra:
                raise _unprocessable("VALIDATION_ERROR", "void_elapsed takes no new assignment state",
                                     {"field": extra[0]})
        if operation == OP_REVISE and body.get("void_elapsed") is not True:
            for name in ("driver_id", "start_date", "end_date"):
                if not text(body.get(name)).strip():
                    raise _unprocessable("VALIDATION_ERROR", f"REVISE needs {name} (or void_elapsed: true)",
                                         {"field": name})
        context = require_write_context(self._context, self._batch_id)
        if context == DATA_CONTEXT_REAL:  # O1 / DQ-1: before ANY repository call
            raise _conflict("E2_REAL_WRITES_NOT_ENABLED",
                            "E2 operational assignments are not enabled for REAL data before R11; nothing was changed")
        ctx = await self._read(context)
        located = await self._locate_vehicle(ctx, vehicle_id)
        await self._prove_references(ctx)
        event_id = text(body.get("event_id")) or None
        fingerprint = request_fingerprint(OP_OPERATIONAL_DRIVER_ASSIGNMENT, located, event_id, body)
        hit = find_replay(ctx.history.rows, request_id, fingerprint, record_id_column="record_id")
        if hit is not None:
            if not hit.replayed:
                raise _conflict("REQUEST_ID_REUSED",
                                "This request id was already used for a different change; nothing was changed",
                                {"request_id": request_id})
            events = tuple(dict.fromkeys(text(r.get("event_id")) for r in hit.rows))
            return OperationOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids,
                                    operation_id=text(hit.rows[0].get("operation_id")), event_ids=events)
        now = self._now()
        base: dict[str, object] = self._base_row(
            ctx, vehicle_id=located, operation=operation, operation_id=f"ODO-{uuid.uuid4().hex}",
            request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            recorded_at=now, reason=reason)
        plan = _Plan()
        outcome: OperationOutcome | None
        if operation == OP_CREATE:
            outcome = await self._create(ctx, located, body, base, now, plan)
        else:
            target = self._target(ctx, located, body)
            if operation == OP_REVISE:
                outcome = await self._revise(ctx, target, body, base, now, plan)
            elif operation == OP_SUBSTITUTE:
                await self._substitute(ctx, target, body, base, now, plan)
                outcome = None
            elif operation == OP_CANCEL:
                await self._cancel(ctx, target, base, now, plan)
                outcome = None
            else:
                outcome = await self._early_end(ctx, target, body, base, now, plan)
        if outcome is not None:
            return outcome
        return await self._commit(ctx, located, plan, request_id=request_id, now=now,
                                  operation_id=text(base["operation_id"]), create=operation == OP_CREATE)

    async def _commit(self, ctx: _Ctx, vehicle_id: str, plan: _Plan, *, request_id: str, now: datetime,
                      operation_id: str, create: bool) -> OperationOutcome:
        for row in plan.rows:
            issues = validate_row(row)
            if issues:  # a programming error, before any write
                raise RuntimeError(f"generated E2 row is invalid: {issues}")
        after = derive([*ctx.rows, *plan.rows])
        if after.status == STATUS_INVALID:
            raise RuntimeError(f"generated E2 rows break the history: {after.issue_counts}")
        before_pairs = {(c.axis, c.first.event_id, c.second.event_id) for c in ctx.model.conflicts}
        for c in after.conflicts:  # P3: derived intervals, both axes, the whole logical update or nothing
            if not ({c.first.event_id, c.second.event_id} & plan.touched):
                continue
            if (c.axis, c.first.event_id, c.second.event_id) in before_pairs and not (
                    {c.first.event_id, c.second.event_id} & set(plan.new_events)):
                continue  # a residual conflict this change neither creates nor worsens
            code = "E2_VEHICLE_CONFLICT" if c.axis == "VEHICLE" else "E2_DRIVER_CONFLICT"
            raise _conflict(code, "The assignment would overlap another effective assignment; nothing was changed",
                            {"axis": c.axis, "conflicting_event_id": next(
                                (e for e in (c.first.event_id, c.second.event_id) if e not in plan.touched),
                                c.second.event_id),
                             "first": _interval_details(c.first), "second": _interval_details(c.second)})
        for event_id in plan.eligibility:
            state = after.assignments[event_id]
            if state.lifecycle != LIFECYCLE_ACTIVE:
                continue
            before = ctx.model.assignments.get(event_id)
            if before is not None and before.driver_id == state.driver_id and all(
                    any(b.start <= i.start and i.end <= b.end for b in ctx.model.intervals_of(event_id))
                    for i in after.intervals_of(event_id)):
                continue  # only removes / keeps coverage of the same driver: no new assignment (A2-7.1)
            forward = any(i.end > now for i in after.intervals_of(event_id))
            await self._check_driver(ctx, state.driver_id, require_active=forward)
        warnings: list[Warning] = []
        if create:
            permanent = await self._permanent_warning(ctx, vehicle_id)
            if permanent is not None:
                warnings.append(permanent)
        warnings += self._adjacency_warnings(after, events=plan.touched)
        try:
            await self._repository.append_operational_driver_assignment_rows(ctx.history, plan.rows)
        except RepositoryConcurrentChangeError as exc:
            raise _conflict("E2_CONCURRENT_CHANGE", "Another E2 change was accepted first; nothing was changed by "
                            "this request — reload and try again", {"request_id": request_id}) from exc
        except RepositoryWriteError as exc:
            message = ("The E2 history write was rejected; nothing was changed by this request"
                       if exc.outcome == "rejected"
                       else "The E2 history write outcome is unknown (the records may have been written); nothing "
                            "was retried — resend with the same request id to learn the outcome")
            raise error("E2_HISTORY_WRITE_FAILED", message, status.HTTP_503_SERVICE_UNAVAILABLE,
                        {"history_write_outcome": exc.outcome, "request_id": request_id}) from exc
        return OperationOutcome(
            request_id=request_id, changed=True, operation_id=operation_id,
            record_ids=tuple(r["record_id"] for r in plan.rows),
            event_ids=tuple(dict.fromkeys(r["event_id"] for r in plan.rows)),
            warnings=tuple(warnings),
        )


__all__ = [
    "HISTORY_PREFIX",
    "OP_OPERATIONAL_DRIVER_ASSIGNMENT",
    "DriverSchedule",
    "OperationOutcome",
    "OperationalDriverAssignmentService",
    "UnknownSpan",
    "VehicleHistory",
    "VehicleSchedule",
    "Warning",
]
