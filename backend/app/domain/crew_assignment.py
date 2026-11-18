"""R8 early workstream — Crew Assignment Extension service (Mock/TEST only).

Governance: Master Roadmap 2026-11-11 R8 addendum; DEC-R8-CREW-CALENDAR-20261111;
R8 Whole-Phase Owner source approval 2026-11-18: OD-1 = A (RIGGER / SIGNALMAN /
OTHER + Thai note), OD-2 = A (interval-scoped fail-closed cross-role identity),
OD-3 = A (`can_assign_crane_crew`, per-employee TEST grant only — checked at the
route), OD-4 = A (CREATE / REVISE / CANCEL / EARLY_END; E2 time modes; no crew
handover or SUBSTITUTE). The authority is `crane_crew_assignment_history`
(append-only, revisioned; `crew_assignment_timeline` derives everything). E2
(`operational_driver_assignment`) is read here, never written.

Write order (mirrors E2): body rules (422) -> repository mode (501, Google Sheets)
-> write context (503) -> REAL refusal (409 CREW_REAL_WRITES_NOT_ENABLED) -> ONE
crew history read + ONE E2 history read -> vehicle locate -> replay -> stale /
lifecycle -> operation rules -> after-state derivation -> person-axis conflicts
(409 RESOURCE_CONFLICT / CROSS_ROLE_IDENTITY_UNVERIFIED) -> person eligibility ->
ONE two-stream guarded append. After the append the only outcomes are success,
CREW_CONCURRENT_CHANGE (nothing written) and CREW_HISTORY_WRITE_FAILED (outcome
reported, never retried; the same request id later replays or reports it).

Eligibility (A2-7 analogue, no crew master): the person resolves exactly once in
scope; a state with any unit ending after now needs the Personnel row exactly
ACTIVE; a state whose units have all elapsed may name an inactive person (reason
mandatory). No certification, role eligibility or crew-size rule exists.

The mock version guard makes acceptance atomic in ONE process only. Cross-process
one-winner and persistent overlap safety are R11 (PostgreSQL), not claimed here.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone

from fastapi import status

from app.domain.crane_driver_responsibility import classify_reference
from app.domain.crew_assignment_timeline import (
    CREW_ASSIGNMENT_HISTORY_COLUMNS,
    CREW_ASSIGNMENT_HISTORY_TAB,
    CrewInterval,
    CrewModel,
    CrewState,
    derive_crew,
    role_issue,
    validate_crew_row,
)
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG, in_scope
from app.domain.operational_driver_timeline import (
    ASSIGNMENT,
    CANCELLATION,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_CANCELLED,
    MAX_START_AHEAD_DAYS,
    OP_CANCEL,
    OP_CREATE,
    OP_EARLY_END,
    OP_REVISE,
    OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB,
    REVISION,
    STATUS_INVALID,
    Model,
    Schedule,
    bangkok,
    bangkok_date,
    derive,
    iso,
    parse_date,
    parse_time,
    schedule_cells,
    schedule_issues,
)
from app.domain.personnel_relationship import PERSONNEL_PREFIX, PERSONNEL_TAB, scoped_personnel
from app.domain.personnel_resource_conflict import (
    CODE_IDENTITY_UNVERIFIED,
    W_PERSON_ADJACENT,
    DriverIdentity,
    PersonConflict,
    PersonInterval,
    driver_identities,
    find_person_conflicts,
    new_conflicts,
    person_adjacency,
    person_intervals,
)
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
    RepositoryWriteError,
)

OP_CREW_ASSIGNMENT = "crane_crew_assignment"  # the request-fingerprint operation name
CREW_HISTORY_PREFIX = "CREW_HISTORY"
E2_HISTORY_PREFIX = "E2_HISTORY"
VEHICLE_PREFIX = "VEHICLE_MASTER"
VEHICLE_TAB = "vehicle_master"
ACTIVE = "ACTIVE"
MAX_REASON_LENGTH = 500
CREW_OPERATIONS = (OP_CREATE, OP_REVISE, OP_CANCEL, OP_EARLY_END)

REFERENCE_MISSING = "MISSING"
REFERENCE_AMBIGUOUS = "AMBIGUOUS"
REFERENCE_SCOPE_UNPROVEN = "SCOPE_UNPROVEN"


@dataclass(frozen=True)
class CrewWarning:
    code: str
    event_id: str | None = None
    personnel_id: str | None = None
    vehicle_id: str | None = None
    related_event_id: str | None = None


@dataclass(frozen=True)
class CrewOutcome:
    request_id: str
    changed: bool = False
    replayed: bool = False
    operation_id: str | None = None
    record_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    existing_event_id: str | None = None
    warnings: tuple[CrewWarning, ...] = ()


@dataclass(frozen=True)
class CrewIntervalView:
    interval: CrewInterval
    status: str  # VALID | CONFLICTED | IDENTITY_UNVERIFIED


@dataclass(frozen=True)
class VehicleCrew:
    vehicle_id: str
    intervals: tuple[CrewIntervalView, ...]
    names: Mapping[str, str]


@dataclass(frozen=True)
class VehicleCrewHistory:
    vehicle_id: str
    records: tuple[Mapping[str, object], ...]
    assignments: tuple[CrewState, ...]


@dataclass
class ResourceRead:
    """One consistent read of both streams and the person identities."""

    context: str
    crew_history: RegistryTableRead
    e2_history: RegistryTableRead
    crew_rows: list[Mapping[str, object]]
    crew: CrewModel
    e2: Model
    personnel: list[Mapping[str, object]] = field(default_factory=list)
    personnel_master_rows: list[Mapping[str, object]] = field(default_factory=list)
    identities: dict[str, DriverIdentity] = field(default_factory=dict)
    vehicles: ReferenceMasterRead | None = None


def _unprocessable(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY, details)


def _conflict(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, status.HTTP_409_CONFLICT, details)


def _invalid(prefix: str, tab: str, issues: dict[str, int]) -> ApiError:
    return error(f"{prefix}_DATA_INVALID", f"{tab} contains records that cannot be used exactly",
                 status.HTTP_500_INTERNAL_SERVER_ERROR, {"tab": tab, "issues": dict(sorted(issues.items()))})


_SCHEDULE_ERRORS = {
    "RANGE_INVALID": ("CREW_RANGE_INVALID", "end_date must not be before start_date"),
    "RANGE_TOO_LONG": ("CREW_RANGE_TOO_LONG", "An assignment covers at most 366 inclusive calendar days"),
    "SHIFT_REQUIRED": ("CREW_SHIFT_REQUIRED", "DAY_SHIFT / NIGHT_SHIFT need explicit applied shift times"),
    "SHIFT_NOT_ALLOWED": ("CREW_SHIFT_NOT_ALLOWED", "FULL_DAY takes no shift times"),
    "SHIFT_DURATION_INVALID": ("CREW_SHIFT_DURATION_INVALID",
                               "A shift lasts more than 0 and at most 24 hours (equal times need end_day_offset 1)"),
    "MODE_INVALID": ("CREW_MODE_INVALID", "Unknown assignment mode"),
    "EXCLUDED_DATE_OUT_OF_RANGE": ("CREW_RANGE_INVALID", "The assignment range no longer contains its excluded dates"),
}

_ROLE_ERRORS = {
    "ROLE_INVALID": "crew_role must be RIGGER, SIGNALMAN or OTHER",
    "ROLE_NOTE_REQUIRED": "crew_role OTHER needs a Thai role note of 1-200 characters",
    "ROLE_NOTE_NOT_ALLOWED": "Only crew_role OTHER takes a role note",
}


def person_interval_details(p: PersonInterval) -> dict[str, object]:
    return {"kind": p.kind, "event_id": p.event_id, "vehicle_id": p.vehicle_id, "personnel_id": p.personnel_id,
            "driver_id": p.driver_id, "identity": p.identity, "role": p.role,
            "label_date": p.label_date.isoformat(), "start": iso(p.start), "end": iso(p.end)}


def person_conflict_error(c: PersonConflict, touched: set[str]) -> ApiError:
    """The 409 of a refused person-axis conflict (crew and E2 writes share it)."""
    other = c.second if c.first.event_id in touched else c.first
    if c.code == CODE_IDENTITY_UNVERIFIED:
        message = ("A driver assignment overlapping this time has no single verified personnel link, so the same "
                   "person cannot be ruled out; nothing was changed")
    else:
        message = "The same person would be assigned twice for overlapping time; nothing was changed"
    return _conflict(c.code, message, {"axis": "PERSON", "conflicting_event_id": other.event_id,
                                       "first": person_interval_details(c.first),
                                       "second": person_interval_details(c.second)})


def _reason(body: Mapping[str, object], *, required: bool) -> str:
    reason = body.get("reason_th")
    if reason is None and not required:
        return ""
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
        raise _unprocessable("REASON_REQUIRED", f"A reason of 1-{MAX_REASON_LENGTH} characters is required")
    return reason


def _date(body: Mapping[str, object], name: str) -> date:
    parsed = parse_date(body.get(name))
    if parsed is None:
        raise _unprocessable("CREW_DATE_INVALID", f"{name} must be a calendar date YYYY-MM-DD", {"field": name})
    return parsed


def _schedule_from_body(body: Mapping[str, object]) -> Schedule:
    mode = text(body.get("mode"))
    start, end = _date(body, "start_date"), _date(body, "end_date")
    raw = body.get("shift")
    s = e = None
    offset = 0
    if raw is not None:
        assert isinstance(raw, Mapping)
        s, e = parse_time(raw.get("start_time")), parse_time(raw.get("end_time"))
        if s is None or e is None:
            raise _unprocessable("CREW_TIME_INVALID", "Shift times must be HH:MM (00:00-23:59)", {"field": "shift"})
        offset = int(raw.get("end_day_offset")) if isinstance(raw.get("end_day_offset"), int) else 0
    sched = Schedule(mode, start, end, s, e, offset)
    issues = schedule_issues(sched)
    if issues:
        code, message = _SCHEDULE_ERRORS[issues[0]]
        raise _unprocessable(code, message, {"issue": issues[0]})
    return sched


def _role_from_body(body: Mapping[str, object]) -> tuple[str, str]:
    role = text(body.get("crew_role"))
    note = body.get("crew_role_note_th")
    note_text = note if isinstance(note, str) else ""
    issue = role_issue(role, note_text)
    if issue:
        raise _unprocessable(f"CREW_{issue}", _ROLE_ERRORS[issue], {"field": "crew_role"})
    return role, note_text


class CrewAssignmentService:
    def __init__(self, repository: Repository, data_context: str | None, test_batch_id: str, *,
                 mock_repository: bool) -> None:
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id
        self._mock = mock_repository

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)

    # ------------------------------------------------------------------ reads

    def _require_mock(self) -> None:
        if not self._mock:
            raise error("FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE",
                        "Crew assignments are available only in the synthetic Mock/TEST repository",
                        status.HTTP_501_NOT_IMPLEMENTED, {"feature": "crew_assignment"})

    async def _stream(self, call, prefix: str, tab: str) -> RegistryTableRead:
        history = await reference_read(call, prefix, tab)
        ids = [text(r.get("record_id")) for r in history.rows if text(r.get("record_id"))]
        if len(ids) != len(set(ids)):
            raise _invalid(prefix, tab, {"RECORD_ID_DUPLICATE": len(ids) - len(set(ids))})
        bad = sum(1 for r in history.rows if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
        if bad:
            raise _invalid(prefix, tab, {"TEST_FLAG_INVALID": bad})
        return history

    async def read_resources(self, context: str) -> ResourceRead:
        """Both streams (crew first, then E2), derived in scope, plus the in-scope
        personnel and every in-scope E2 driver's identity. Any invalid stream fails
        the whole read (500) — never a partial calendar or a silent "free"."""
        crew_history = await self._stream(self._repository.read_crew_assignment_history_validated(),
                                          CREW_HISTORY_PREFIX, CREW_ASSIGNMENT_HISTORY_TAB)
        e2_history = await self._stream(self._repository.read_operational_driver_assignment_history_validated(),
                                        E2_HISTORY_PREFIX, OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB)
        crew_rows = [r for r in crew_history.rows if in_scope(r, context, self._batch_id)]
        crew = derive_crew(crew_rows)
        if crew.status == STATUS_INVALID:
            raise _invalid(CREW_HISTORY_PREFIX, CREW_ASSIGNMENT_HISTORY_TAB, crew.issue_counts)
        e2 = derive([r for r in e2_history.rows if in_scope(r, context, self._batch_id)])
        if e2.status == STATUS_INVALID:
            raise _invalid(E2_HISTORY_PREFIX, OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB, e2.issue_counts)
        master = await reference_read(self._repository.read_personnel_relationship_master(), PERSONNEL_PREFIX,
                                      PERSONNEL_TAB)
        personnel = scoped_personnel(master.rows, context, self._batch_id)
        identities = driver_identities(personnel, {i.driver_id for i in e2.intervals})
        return ResourceRead(context, crew_history, e2_history, crew_rows, crew, e2, personnel, list(master.rows),
                            identities)

    async def _locate_vehicle(self, res: ResourceRead, vehicle_id: str) -> str:
        if res.vehicles is None:
            res.vehicles = await reference_read(self._repository.read_vehicle_reference(), VEHICLE_PREFIX,
                                                VEHICLE_TAB)
        kind = classify_reference(vehicle_id, res.vehicles, "vehicle_id", res.context, self._batch_id) \
            if vehicle_id.strip() else REFERENCE_MISSING
        if kind == REFERENCE_AMBIGUOUS:
            raise _conflict("VEHICLE_ID_AMBIGUOUS", "More than one vehicle record has this id")
        if kind == REFERENCE_SCOPE_UNPROVEN:
            raise _unprocessable("VEHICLE_SCOPE_UNPROVEN",
                                 "This vehicle cannot be proven to belong to the request's data scope")
        if kind == REFERENCE_MISSING:
            raise error("VEHICLE_NOT_FOUND", "No vehicle record has exactly this id", status.HTTP_404_NOT_FOUND)
        return vehicle_id

    @staticmethod
    def names(res: ResourceRead) -> dict[str, str]:
        """personnel_id -> display name (public columns only)."""
        return {text(p.get("personnel_id")): f"{text(p.get('first_name'))} {text(p.get('last_name'))}".strip()
                for p in res.personnel}

    @staticmethod
    def person_view(res: ResourceRead) -> tuple[list[PersonInterval], list[PersonConflict]]:
        intervals = person_intervals(res.e2.intervals, res.crew.intervals, res.identities)
        return intervals, find_person_conflicts(intervals)

    @staticmethod
    def status_of(event_id: str, conflicts: Sequence[PersonConflict]) -> str:
        codes = {c.code for c in conflicts if event_id in (c.first.event_id, c.second.event_id)}
        if CODE_IDENTITY_UNVERIFIED in codes:
            return "IDENTITY_UNVERIFIED"
        return "CONFLICTED" if codes else "VALID"

    @staticmethod
    def in_window(start: datetime, end: datetime, date_from: date | None, date_to: date | None) -> bool:
        return (date_from is None or end > bangkok(date_from)) and (
            date_to is None or start < bangkok(date_to + timedelta(1)))

    async def vehicle_crew(self, vehicle_id: str, *, date_from: date | None = None,
                           date_to: date | None = None) -> VehicleCrew:
        self._require_mock()
        context = require_write_context(self._context, self._batch_id)
        res = await self.read_resources(context)
        located = await self._locate_vehicle(res, vehicle_id)
        _, conflicts = self.person_view(res)
        own = [CrewIntervalView(i, self.status_of(i.event_id, conflicts)) for i in res.crew.intervals
               if i.vehicle_id == located and self.in_window(i.start, i.end, date_from, date_to)]
        return VehicleCrew(located, tuple(own), self.names(res))

    async def vehicle_history(self, vehicle_id: str) -> VehicleCrewHistory:
        self._require_mock()
        context = require_write_context(self._context, self._batch_id)
        res = await self.read_resources(context)
        located = await self._locate_vehicle(res, vehicle_id)
        records = tuple(r for r in res.crew_rows if text(r.get("vehicle_id")) == located)
        return VehicleCrewHistory(located, records,
                                  tuple(a for a in res.crew.assignments.values() if a.vehicle_id == located))

    # ------------------------------------------------------------------ writes

    def _base_row(self, res: ResourceRead, *, vehicle_id: str, operation: str, operation_id: str, request_id: str,
                  fingerprint: str, user_id: str, recorded_at: datetime, reason: str) -> dict[str, str]:
        row = dict.fromkeys(CREW_ASSIGNMENT_HISTORY_COLUMNS, "")
        row.update(
            operation_id=operation_id, entry_operation=operation, vehicle_id=vehicle_id, reason_th=reason,
            recorded_at=recorded_at.isoformat(timespec="microseconds"), recorded_by=user_id,
            request_id=request_id, request_fingerprint=fingerprint,
            is_test_data=TEST_FLAG if res.context == DATA_CONTEXT_TEST else OPERATIONAL_FLAG,
            test_batch_id=self._batch_id if res.context == DATA_CONTEXT_TEST else "",
        )
        return row

    @staticmethod
    def _state_cells(sched: Schedule, personnel_id: str, role: str, note: str,
                     early_end_at: datetime | None = None) -> dict[str, str]:
        cells = schedule_cells(sched)
        cells.update(personnel_id=personnel_id, crew_role=role, crew_role_note_th=note,
                     early_end_at=iso(early_end_at) if early_end_at else "")
        return cells

    @staticmethod
    def _target(res: ResourceRead, vehicle_id: str, body: Mapping[str, object]) -> CrewState:
        event_id = text(body.get("event_id"))
        target = res.crew.assignments.get(event_id)
        if target is None or target.vehicle_id != vehicle_id:
            raise error("CREW_ASSIGNMENT_NOT_FOUND", "No crew assignment with this event_id exists for this vehicle",
                        status.HTTP_404_NOT_FOUND, {"event_id": event_id})
        if body.get("expected_revision_no") != target.revision_no:
            raise _conflict("CREW_ASSIGNMENT_STALE", "The assignment changed since it was loaded; reload and try "
                            "again", {"event_id": event_id, "field": "revision_no"})
        if target.lifecycle == LIFECYCLE_CANCELLED:
            raise _conflict("CREW_ASSIGNMENT_CANCELLED", "This assignment was cancelled; nothing was changed",
                            {"event_id": event_id})
        return target

    def _person(self, res: ResourceRead, master_rows: Sequence[Mapping[str, object]],
                personnel_id: str) -> Mapping[str, object]:
        """The person resolves EXACTLY ONCE in scope (existence / uniqueness / scope)."""
        if not personnel_id.strip():
            raise _unprocessable("PERSONNEL_NOT_FOUND", "No personnel record has exactly this personnel_id",
                                 {"personnel_id": personnel_id})
        scoped = [p for p in res.personnel if text(p.get("personnel_id")) == personnel_id]
        if len(scoped) > 1:
            raise _conflict("PERSONNEL_ID_AMBIGUOUS", "More than one personnel record has this personnel_id",
                            {"personnel_id": personnel_id})
        if not scoped:
            if any(text(p.get("personnel_id")) == personnel_id for p in master_rows):
                raise _unprocessable("PERSONNEL_SCOPE_UNPROVEN",
                                     "This person cannot be proven to belong to the request's data scope",
                                     {"personnel_id": personnel_id})
            raise _unprocessable("PERSONNEL_NOT_FOUND", "No personnel record has exactly this personnel_id",
                                 {"personnel_id": personnel_id})
        return scoped[0]

    async def apply(self, vehicle_id: str, body: Mapping[str, object], *, request_id: str,
                    user_id: str) -> CrewOutcome:
        operation = text(body.get("operation"))
        if operation not in CREW_OPERATIONS:  # the schema already refuses; defensive
            raise _unprocessable("CREW_OPERATION_INVALID", "Unknown crew operation")
        reason = _reason(body, required=operation != OP_CREATE)
        self._require_mock()
        context = require_write_context(self._context, self._batch_id)
        if context == DATA_CONTEXT_REAL:  # before ANY repository call
            raise _conflict("CREW_REAL_WRITES_NOT_ENABLED",
                            "Crew assignments are not enabled for REAL data before R11; nothing was changed")
        res = await self.read_resources(context)
        located = await self._locate_vehicle(res, vehicle_id)
        event_id = text(body.get("event_id")) or None
        fingerprint = request_fingerprint(OP_CREW_ASSIGNMENT, located, event_id, body)
        hit = find_replay(res.crew_history.rows, request_id, fingerprint, record_id_column="record_id")
        if hit is not None:
            if not hit.replayed:
                raise _conflict("REQUEST_ID_REUSED",
                                "This request id was already used for a different change; nothing was changed",
                                {"request_id": request_id})
            return CrewOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids,
                               operation_id=text(hit.rows[0].get("operation_id")),
                               event_ids=tuple(dict.fromkeys(text(r.get("event_id")) for r in hit.rows)))
        now = self._now()
        base = self._base_row(res, vehicle_id=located, operation=operation, operation_id=f"CRO-{uuid.uuid4().hex}",
                              request_id=request_id, fingerprint=fingerprint, user_id=user_id, recorded_at=now,
                              reason=reason)
        if operation == OP_CREATE:
            sched = _schedule_from_body(body)
            role, note = _role_from_body(body)
            personnel_id = text(body.get("personnel_id"))
            if (sched.start_date - bangkok_date(now)).days > MAX_START_AHEAD_DAYS:
                raise _unprocessable("CREW_RANGE_TOO_LONG",
                                     "A start date may be at most 366 Bangkok calendar days in the future",
                                     {"issue": "RANGE_TOO_LONG", "limit": "START_HORIZON"})
            if sched.start_date < bangkok_date(now):
                _reason(body, required=True)  # a backdated create needs a reason; same-day does not
            for a in res.crew.assignments.values():  # an identical active assignment is not duplicated
                if (a.vehicle_id, a.personnel_id, a.role, a.role_note_th, a.lifecycle, a.schedule,
                        a.early_end_at) == (located, personnel_id, role, note, LIFECYCLE_ACTIVE, sched, None):
                    return CrewOutcome(request_id=request_id, changed=False, existing_event_id=a.event_id)
            record_id = f"CRA-{uuid.uuid4().hex}"
            row = {**base, **self._state_cells(sched, personnel_id, role, note), "record_kind": ASSIGNMENT,
                   "event_id": record_id, "revision_no": "1", "record_id": record_id}
            return await self._commit(res, located, [row], {record_id}, {record_id}, request_id=request_id, now=now,
                                      operation_id=base["operation_id"], check_person=personnel_id)
        target = self._target(res, located, body)
        if operation == OP_REVISE:
            sched = _schedule_from_body(body)
            role, note = _role_from_body(body)
            if (role, note, sched, target.early_end_at) == (target.role, target.role_note_th, target.schedule,
                                                             None):
                return CrewOutcome(request_id=request_id, changed=False, existing_event_id=target.event_id)
            row = self._revision_row(target, base, self._state_cells(sched, target.personnel_id, role, note))
        elif operation == OP_CANCEL:
            if self._started(res.crew, target, now):
                raise _conflict("CREW_ASSIGNMENT_ALREADY_STARTED", "A started assignment cannot be cancelled; use "
                                "EARLY_END or REVISE", {"event_id": target.event_id})
            row = {**base, "record_kind": CANCELLATION, "event_id": target.event_id,
                   "revision_no": str(int(target.revision_no) + 1), "supersedes_record_id": target.head_record_id,
                   "record_id": f"CRA-{uuid.uuid4().hex}"}
        else:
            row = self._early_end_row(res, target, body, base, now)
        check = target.personnel_id if operation == OP_REVISE else None
        return await self._commit(res, located, [row], {target.event_id}, set(), request_id=request_id, now=now,
                                  operation_id=base["operation_id"], check_person=check, before_state=target)

    @staticmethod
    def _started(model: CrewModel, a: CrewState, now: datetime) -> bool:
        intervals = model.intervals_of(a.event_id)
        return bool(intervals) and min(i.start for i in intervals) <= now

    @staticmethod
    def _revision_row(a: CrewState, base: dict[str, str], cells: dict[str, str]) -> dict[str, str]:
        return {**base, **cells, "record_kind": REVISION, "event_id": a.event_id,
                "revision_no": str(int(a.revision_no) + 1), "supersedes_record_id": a.head_record_id,
                "record_id": f"CRA-{uuid.uuid4().hex}"}

    def _early_end_row(self, res: ResourceRead, a: CrewState, body: Mapping[str, object], base: dict[str, str],
                       now: datetime) -> dict[str, str]:
        intervals = res.crew.intervals_of(a.event_id)
        if not self._started(res.crew, a, now):
            raise _conflict("CREW_ASSIGNMENT_NOT_STARTED", "This assignment has not started; cancel it instead",
                            {"event_id": a.event_id})
        if max(i.end for i in intervals) <= now:
            raise _conflict("CREW_ASSIGNMENT_ALREADY_ENDED", "This assignment has already ended",
                            {"event_id": a.event_id})
        end = body.get("end")
        assert isinstance(end, Mapping)
        if end.get("mode") == "NOW":
            sched, early = a.schedule, now
        else:
            day = parse_date(end.get("date"))
            if day is None:
                raise _unprocessable("CREW_DATE_INVALID", "end.date must be a calendar date", {"field": "end.date"})
            if not (bangkok_date(now) <= day < a.schedule.end_date and a.schedule.start_date <= day):
                raise _unprocessable("CREW_EARLY_END_INVALID", "end.date must be today or later, within the "
                                     "assignment and before its last date")
            sched = replace(a.schedule, end_date=day,
                            excluded=tuple(d for d in a.schedule.excluded if d <= day))
            early = a.early_end_at
        return self._revision_row(a, base, self._state_cells(sched, a.personnel_id, a.role, a.role_note_th,
                                                             early_end_at=early))

    async def _commit(self, res: ResourceRead, vehicle_id: str, rows: list[dict[str, str]], touched: set[str],
                      new_events: set[str], *, request_id: str, now: datetime, operation_id: str,
                      check_person: str | None, before_state: CrewState | None = None) -> CrewOutcome:
        for row in rows:
            issues = validate_crew_row(row)
            if issues:  # a programming error, before any write
                raise RuntimeError(f"generated crew row is invalid: {issues}")
        after = derive_crew([*res.crew_rows, *rows])
        if after.status == STATUS_INVALID:
            raise RuntimeError(f"generated crew rows break the history: {after.issue_counts}")
        before_conflicts = find_person_conflicts(
            person_intervals(res.e2.intervals, res.crew.intervals, res.identities))
        after_intervals = person_intervals(res.e2.intervals, after.intervals, res.identities)
        refused = new_conflicts(before_conflicts, find_person_conflicts(after_intervals), touched, new_events)
        if refused:
            raise person_conflict_error(refused[0], touched)
        if check_person is not None:  # eligibility of a coverage-adding state
            person = self._person(res, res.personnel_master_rows, check_person)
            event_id = next(iter(touched))
            new = after.intervals_of(event_id)
            shrink_only = before_state is not None and all(
                any(b.start <= i.start and i.end <= b.end for b in res.crew.intervals_of(event_id)) for i in new)
            forward = any(i.end > now for i in new)
            if forward and not shrink_only and text(person.get("active_status")) != ACTIVE:
                raise _unprocessable("PERSONNEL_NOT_ACTIVE",
                                     "Only an ACTIVE person can be assigned for a current or future period",
                                     {"personnel_id": check_person})
        warnings = [CrewWarning(W_PERSON_ADJACENT, event_id=b.event_id, personnel_id=a.personnel_id,
                                vehicle_id=b.vehicle_id, related_event_id=a.event_id)
                    for a, b in person_adjacency(after_intervals) if {a.event_id, b.event_id} & touched]
        try:
            await self._repository.append_resource_assignment_rows(res.e2_history, res.crew_history, "CREW", rows)
        except RepositoryConcurrentChangeError as exc:
            raise _conflict("CREW_CONCURRENT_CHANGE", "Another crew or driver assignment change was accepted first; "
                            "nothing was changed by this request — reload and try again",
                            {"request_id": request_id}) from exc
        except RepositoryWriteError as exc:
            message = ("The crew history write was rejected; nothing was changed by this request"
                       if exc.outcome == "rejected"
                       else "The crew history write outcome is unknown (the records may have been written); nothing "
                            "was retried — resend with the same request id to learn the outcome")
            raise error("CREW_HISTORY_WRITE_FAILED", message, status.HTTP_503_SERVICE_UNAVAILABLE,
                        {"history_write_outcome": exc.outcome, "request_id": request_id}) from exc
        return CrewOutcome(request_id=request_id, changed=True, operation_id=operation_id,
                           record_ids=tuple(r["record_id"] for r in rows),
                           event_ids=tuple(dict.fromkeys(r["event_id"] for r in rows)),
                           warnings=tuple(dict.fromkeys(warnings)))


__all__ = [
    "CREW_OPERATIONS",
    "CrewAssignmentService",
    "CrewIntervalView",
    "CrewOutcome",
    "CrewWarning",
    "ResourceRead",
    "VehicleCrew",
    "VehicleCrewHistory",
    "person_conflict_error",
    "person_interval_details",
]
