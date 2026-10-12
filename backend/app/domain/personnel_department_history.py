"""R2 Batch R2f-g — Personnel DEPARTMENT movement history (history-only).

Authority: `personnel_department_history` (append-only, the ONLY authority for
department movement). The legacy `personnel_master.department` text is never
read, written, used as a baseline or projected; there is no projection column,
no W2 and no reconciliation. There is no import: a personnel with no history
has no derived department (NONE), whatever the legacy text says.

Operations (one strict, operation-discriminated body), the R2f-d / R2f-f model:
- TRANSFER  — a movement, the latest event: from its effective instant the
  personnel is in `department_id`; the previous derived period ENDS at that same
  instant (the first movement is from NONE). NOW allowed; reason optional.
- INSERTION — a backdated movement before a later in-force event (no NOW):
  the surrounding periods are re-derived so they still never overlap; reason
  required.
- CORRECTION / CANCELLATION — a new revision of `event_id`, guarded by
  `expected_revision_no`; reason required; a cancellation is terminal.
No END operation exists in this batch (see the result doc: PENDING).

Department reference proof (same-scope rule, fail closed): a NEW target
department must resolve EXACTLY ONCE in `department_master` in the request's
scope. department_master rows carry their own scope flags (is_test_data /
test_batch_id): REAL = exactly FALSE (no batch), TEST = exactly TRUE with the
server batch; a content row with any other flag fails the source closed. Scope
is never inferred from an id, name, prefix or description. Every department id
STORED in the in-scope history (department_id and recorded_from_department_id)
is proven the same way before the timeline is trusted (existence / uniqueness
/ scope only). No department lifecycle (is_active) or personnel lifecycle gate
is applied — none is authorized (PENDING).

Order: body shape / reason / effective time (422) -> write context (503) ->
personnel locate in scope -> ONE history read (tab-wide record-id check, this
personnel's in-scope structural validation, stored department references
proven) -> replay -> stale (expected current department; event revision) ->
state and order rules -> no-op -> target department proof -> W1. After W1 the
only outcomes are success and PERSONNEL_DEPARTMENT_HISTORY_WRITE_FAILED;
nothing is retried, compensated, re-read or re-appended. Nothing else is ever
written (personnel_master included).
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import status

from app.domain.crane_driver_responsibility import (
    REFERENCE_AMBIGUOUS,
    REFERENCE_MISSING,
    REFERENCE_SCOPE_UNPROVEN,
    classify_reference,
    reference_issues,
)
from app.domain.effective_time import EffectiveTime, EffectiveTimeError, resolve_effective
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG, in_scope
from app.domain.personnel_department_timeline import (
    ASSIGNMENT,
    CANCELLATION,
    CORRECTION,
    DEPARTMENT_REFERENCE_TAB,
    OP_CANCELLATION,
    OP_CORRECTION,
    OP_INSERTION,
    OP_TRANSFER,
    PERSONNEL_DEPARTMENT_HISTORY_COLUMNS,
    PERSONNEL_DEPARTMENT_HISTORY_TAB,
    STATUS_AMBIGUOUS,
    STATUS_INVALID,
    DepartmentPeriod,
    DepartmentTimeline,
    DepartmentUndetermined,
    department_at,
    department_before,
    derive_department_timeline,
    in_force_instants,
    tied_event_ids,
    validate_department_row,
)
from app.domain.personnel_relationship import PERSONNEL_PREFIX, PERSONNEL_TAB, scoped_personnel
from app.domain.reference_read import reference_read
from app.domain.registration import DATA_CONTEXT_TEST, text
from app.domain.registry_write_support import error, require_write_context
from app.domain.request_replay import find_replay, request_fingerprint
from app.errors import ApiError
from app.repositories.base import (
    REFERENCE_SCOPE_REAL,
    REFERENCE_SCOPE_TEST,
    ReferenceMasterRead,
    RegistryTableRead,
    Repository,
    RepositoryWriteError,
    ScopedReferenceRow,
)

MAX_REASON_LENGTH = 500
OP_PERSONNEL_DEPARTMENT = "personnel_department"  # the request-fingerprint operation name
DEPARTMENT_PREFIX = "DEPARTMENT_MASTER"
HISTORY_PREFIX = "PERSONNEL_DEPARTMENT_HISTORY"
CODE_PREFIX = "PERSONNEL_DEPARTMENT"
_NEW_OPERATIONS = (OP_TRANSFER, OP_INSERTION)
_REVISION_OPERATIONS = (OP_CORRECTION, OP_CANCELLATION)
OPERATIONS = (*_NEW_OPERATIONS, *_REVISION_OPERATIONS)


@dataclass(frozen=True)
class DepartmentOutcome:
    """A 200 outcome: changed (one record written), no-op, or replay."""

    request_id: str
    changed: bool = False
    replayed: bool = False
    record_id: str | None = None
    event_id: str | None = None
    timeline_status_after: str | None = None
    current_department_id: str | None = None
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonnelDepartmentHistory:
    personnel_id: str
    timeline: DepartmentTimeline
    as_of: str | None  # the resolved instant (UTC ISO) when an as-of lookup was asked
    as_of_status: str | None  # EVENT / NONE / UNDETERMINED
    as_of_department_id: str | None
    as_of_since: str | None


@dataclass(frozen=True)
class _Context:
    context: str
    personnel_id: str
    history: RegistryTableRead
    rows: list[Mapping[str, object]]
    timeline: DepartmentTimeline
    departments: ReferenceMasterRead | None  # the ONE bounded department read, when one was needed


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def _data_invalid(prefix: str, tab: str, issues: dict[str, int]) -> ApiError:
    return error(f"{prefix}_DATA_INVALID", f"{tab} contains records that cannot be used exactly",
                 status.HTTP_500_INTERNAL_SERVER_ERROR, {"tab": tab, "issues": dict(sorted(issues.items()))})


def _history_invalid(issues: dict[str, int]) -> ApiError:
    return _data_invalid(HISTORY_PREFIX, PERSONNEL_DEPARTMENT_HISTORY_TAB, issues)


def _err(suffix: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return error(f"{CODE_PREFIX}_{suffix}", message, http_status, details)


def _stale(field: str) -> ApiError:
    return _err("HISTORY_STALE", "The personnel's department history changed since it was loaded; reload and try again",
                status.HTTP_409_CONFLICT, {"field": field})


def _ambiguous(reason: str) -> ApiError:
    return _err("TIMELINE_AMBIGUOUS",
                "Department events share one effective instant, so the order is undetermined; nothing was changed",
                status.HTTP_409_CONFLICT, {"reason": reason})


def _same_instant() -> ApiError:
    return _err("EVENT_SAME_INSTANT",
                "Another department event already takes effect at this exact instant; nothing was changed",
                status.HTTP_409_CONFLICT)


def _unprocessable(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY, details)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def department_reference(rows: Sequence[Mapping[str, object]]) -> ReferenceMasterRead:
    """department_master rows -> scoped references, the scope taken ONLY from
    each row's own flags: exactly FALSE (no batch) = REAL, exactly TRUE = TEST
    of its test_batch_id. A content row with any other flag combination fails
    the whole source closed (DEPARTMENT_MASTER_DATA_INVALID); a row with every
    read cell blank is a phantom row."""
    scoped: list[ScopedReferenceRow] = []
    issues: dict[str, int] = {}
    for row in rows:
        values = {c: text(row.get(c)) for c in ("department_id", "is_test_data", "test_batch_id")}
        if not any(v.strip() for v in values.values()):
            continue
        flag, batch = values["is_test_data"], values["test_batch_id"]
        if flag == OPERATIONAL_FLAG and not batch.strip():
            scoped.append(ScopedReferenceRow(values=values, scope=REFERENCE_SCOPE_REAL))
        elif flag == TEST_FLAG:
            scoped.append(ScopedReferenceRow(values=values, scope=REFERENCE_SCOPE_TEST, test_batch_id=batch))
        else:
            code = "SCOPE_INCONSISTENT" if flag == OPERATIONAL_FLAG else "TEST_FLAG_INVALID"
            issues[code] = issues.get(code, 0) + 1
    if issues:
        raise _data_invalid(DEPARTMENT_PREFIX, DEPARTMENT_REFERENCE_TAB, issues)
    # department_master carries explicit test metadata, so TEST references CAN be proven.
    return ReferenceMasterRead(rows=tuple(scoped), columns=frozenset({"department_id"}), test_scope_supported=True)


def history_department_ids(rows: Sequence[Mapping[str, object]]) -> set[str]:
    """Every nonblank `department_id` and `recorded_from_department_id` STORED in
    the rows is a Department reference (a CANCELLATION contributes none)."""
    return {text(r.get(c)) for r in rows for c in ("department_id", "recorded_from_department_id")
            if text(r.get(c)).strip()}


def scoped_history_rows(rows: Sequence[Mapping[str, object]], personnel_id: str, context: str,
                        batch_id: str) -> list[Mapping[str, object]]:
    """This personnel's in-scope rows. Classification first: a row of this
    personnel with a test flag other than exactly TRUE / FALSE fails closed."""
    own = [r for r in rows if text(r.get("personnel_id")) == personnel_id]
    invalid = sum(1 for r in own if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
    if invalid:
        raise _history_invalid({"TEST_FLAG_INVALID": invalid})
    return [r for r in own if in_scope(r, context, batch_id)]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PersonnelDepartmentHistoryService:
    def __init__(self, repository: Repository, data_context: str | None, test_batch_id: str) -> None:
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    # ---------------------------------------------------------------- body

    @staticmethod
    def _effective(raw: object, now: datetime, *, allow_now: bool) -> EffectiveTime:
        try:
            return resolve_effective(raw if isinstance(raw, Mapping) else {}, now, allow_now=allow_now)
        except EffectiveTimeError as exc:
            raise _unprocessable(exc.code, "The effective time is not accepted") from exc

    @staticmethod
    def _reason(body: Mapping[str, object], *, required: bool) -> str:
        reason = body.get("reason_th")
        if reason is None and not required:
            return ""
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
            raise _unprocessable("REASON_REQUIRED", f"A reason of 1-{MAX_REASON_LENGTH} characters is required")
        return reason

    @staticmethod
    def _department_from_body(body: Mapping[str, object]) -> str:
        value = body.get("department_id")
        if not isinstance(value, str) or not value.strip():
            raise _unprocessable(f"{CODE_PREFIX}_DEPARTMENT_REQUIRED", "A department_id is required",
                                 {"field": "department_id"})
        return value

    @staticmethod
    def _expected_current(body: Mapping[str, object]) -> str | None:
        value = body.get("expected_current_department_id")
        return value if isinstance(value, str) and value.strip() else None

    # ---------------------------------------------------------------- reads

    async def _departments(self) -> ReferenceMasterRead:
        read = await reference_read(self._repository.read_department_reference(), DEPARTMENT_PREFIX,
                                    DEPARTMENT_REFERENCE_TAB)
        return department_reference(read.rows)

    async def _locate_personnel(self, personnel_id: str, context: str) -> str:
        master = await reference_read(
            self._repository.read_personnel_relationship_master(), PERSONNEL_PREFIX, PERSONNEL_TAB
        )
        matches = [p for p in scoped_personnel(master.rows, context, self._batch_id)
                   if personnel_id.strip() and text(p.get("personnel_id")) == personnel_id]
        if not matches:
            raise error("PERSONNEL_NOT_FOUND", "No personnel record has exactly this id", status.HTTP_404_NOT_FOUND)
        if len(matches) > 1:
            raise error("PERSONNEL_ID_AMBIGUOUS", "More than one personnel record has this id",
                        status.HTTP_409_CONFLICT, {"match_count": len(matches)})
        return personnel_id

    async def _history(self) -> RegistryTableRead:
        history = await reference_read(
            self._repository.read_personnel_department_history_validated(), HISTORY_PREFIX,
            PERSONNEL_DEPARTMENT_HISTORY_TAB,
        )
        ids = [text(r.get("record_id")) for r in history.rows if text(r.get("record_id"))]
        if len(ids) != len(set(ids)):  # tab-wide, every scope and personnel
            raise _history_invalid({"RECORD_ID_DUPLICATE": len(ids) - len(set(ids))})
        return history

    async def _read(self, personnel_id: str, context: str) -> _Context:
        """The personnel is located in scope; every stored department reference
        is same-scope proven (ONE bounded department read) before the timeline
        is used."""
        located = await self._locate_personnel(personnel_id, context)
        history = await self._history()
        rows = scoped_history_rows(history.rows, located, context, self._batch_id)
        timeline = derive_department_timeline(rows)
        if timeline.status == STATUS_INVALID:
            raise _history_invalid(timeline.issue_counts)
        departments = None
        ids = history_department_ids(rows)
        if ids:
            departments = await self._departments()
            issues = reference_issues(ids, departments, id_column="department_id", label="DEPARTMENT",
                                      context=context, batch_id=self._batch_id)
            if issues:
                raise _history_invalid(issues)
        return _Context(context, located, history, rows, timeline, departments)

    # ---------------------------------------------------------------- guards

    @staticmethod
    def _replay(ctx: _Context, request_id: str, fingerprint: str) -> DepartmentOutcome | None:
        hit = find_replay(ctx.history.rows, request_id, fingerprint, record_id_column="record_id")
        if hit is None:
            return None
        if not hit.replayed:
            raise error("REQUEST_ID_REUSED",
                        "This request id was already used for a different change; nothing was changed",
                        status.HTTP_409_CONFLICT, {"request_id": request_id})
        return DepartmentOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids)

    @staticmethod
    def _event(ctx: _Context, event_id: str) -> DepartmentPeriod:
        event = next((e for e in ctx.timeline.events if e.event_id == event_id), None)
        if event is None:
            raise _err("EVENT_NOT_FOUND", "No department event with this id exists for this personnel",
                       status.HTTP_404_NOT_FOUND, {"event_id": event_id})
        if not event.in_force:
            raise _err("EVENT_CANCELLED", "This department event was cancelled; nothing was changed",
                       status.HTTP_409_CONFLICT, {"event_id": event_id})
        return event

    async def _check_department(self, department_id: str, ctx: _Context) -> None:
        """The NEW target department: exactly once in department_master in the
        request's scope (no lifecycle gate)."""
        departments = ctx.departments or await self._departments()
        kind = classify_reference(department_id, departments, "department_id", ctx.context, self._batch_id)
        if kind == REFERENCE_AMBIGUOUS:
            raise error("DEPARTMENT_ID_AMBIGUOUS", "More than one department record has this department_id",
                        status.HTTP_409_CONFLICT, {"department_id": department_id})
        if kind == REFERENCE_SCOPE_UNPROVEN:
            raise _unprocessable("DEPARTMENT_SCOPE_UNPROVEN",
                                 "This department cannot be proven to belong to the request's data scope",
                                 {"department_id": department_id})
        if kind == REFERENCE_MISSING:
            raise _unprocessable("DEPARTMENT_NOT_FOUND", "No department record has exactly this department_id",
                                 {"department_id": department_id})

    # ---------------------------------------------------------------- write

    def _row(self, ctx: _Context, *, request_id: str, fingerprint: str, user_id: str, **cells: str) -> dict[str, str]:
        row = dict.fromkeys(PERSONNEL_DEPARTMENT_HISTORY_COLUMNS, "")
        record_id = f"PDH-{uuid.uuid4().hex}"
        row.update(
            record_id=record_id,
            personnel_id=ctx.personnel_id,
            recorded_at=self._now().isoformat(timespec="microseconds"),
            recorded_by=user_id,
            request_id=request_id,
            request_fingerprint=fingerprint,
            is_test_data=TEST_FLAG if ctx.context == DATA_CONTEXT_TEST else OPERATIONAL_FLAG,
            test_batch_id=self._batch_id if ctx.context == DATA_CONTEXT_TEST else "",
        )
        row.update(cells)
        if row["record_kind"] == ASSIGNMENT:
            row["event_id"] = record_id
        issues = validate_department_row(row)
        if issues:  # a programming error, before any write
            raise RuntimeError(f"generated department history row is invalid: {issues}")
        return row

    async def _commit(self, ctx: _Context, row: dict[str, str], *, request_id: str) -> DepartmentOutcome:
        after = derive_department_timeline([*ctx.rows, row])
        if after.status == STATUS_INVALID:
            raise RuntimeError(f"generated department row breaks the timeline: {after.issue_counts}")
        try:
            await self._repository.append_personnel_department_history(ctx.history, row)
        except RepositoryWriteError as exc:
            message = (
                "Google Sheets rejected the department-history write; nothing was changed by this request"
                if exc.outcome == "rejected"
                else "The department-history write outcome is unknown (the record may have been written); "
                "nothing was retried"
            )
            raise _err("HISTORY_WRITE_FAILED", message, status.HTTP_503_SERVICE_UNAVAILABLE,
                       {"history_write_outcome": exc.outcome, "request_id": request_id}) from exc
        return DepartmentOutcome(
            request_id=request_id, changed=True, record_id=row["record_id"], event_id=row["event_id"],
            timeline_status_after=after.status, current_department_id=after.current_department_id,
        )

    @staticmethod
    def _source(timeline: DepartmentTimeline, instant: datetime, *, exclude_event: str | None = None):
        try:
            return department_before(timeline, instant, exclude_event=exclude_event)
        except DepartmentUndetermined as exc:  # never guessed
            raise _ambiguous("SOURCE_UNDETERMINED") from exc

    async def record_event(
        self, personnel_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> DepartmentOutcome:
        operation = text(body.get("operation"))
        if operation not in OPERATIONS:  # the schema already refuses; defensive
            raise _unprocessable(f"{CODE_PREFIX}_OPERATION_INVALID", "Unknown department operation")
        now = self._now()
        department = ""
        if operation in _NEW_OPERATIONS:
            department = self._department_from_body(body)
        elif operation == OP_CORRECTION:
            department = self._department_from_body(body)
        effective = None
        if operation != OP_CANCELLATION:
            effective = self._effective(body.get("effective"), now, allow_now=operation == OP_TRANSFER)
        reason = self._reason(body, required=operation in (OP_INSERTION, *_REVISION_OPERATIONS))
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(personnel_id, context)
        event_id = text(body.get("event_id")) if operation in _REVISION_OPERATIONS else None
        fingerprint = request_fingerprint(OP_PERSONNEL_DEPARTMENT, ctx.personnel_id, event_id, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        # Stale guards before every state rule and before the no-op check.
        if self._expected_current(body) != tl.current_department_id:
            raise _stale("current_department_id")
        if operation in _REVISION_OPERATIONS:
            assert event_id is not None
            head = self._event(ctx, event_id)
            if body.get("expected_revision_no") != head.revision_no:  # exact text, as sent
                raise _stale("revision_no")
            if tl.status == STATUS_AMBIGUOUS and event_id not in tied_event_ids(tl):
                raise _ambiguous("TARGET_NOT_TIED")
            if operation == OP_CANCELLATION:
                row = self._row(
                    ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
                    record_kind=CANCELLATION, entry_operation=OP_CANCELLATION, event_id=head.event_id,
                    revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
                    reason_th=reason,
                )
                return await self._commit(ctx, row, request_id=request_id)
            assert effective is not None
            return await self._correct(ctx, head, department, effective, reason, request_id=request_id,
                                       fingerprint=fingerprint, user_id=user_id)
        if tl.status == STATUS_AMBIGUOUS:
            raise _ambiguous("TIMELINE_AMBIGUOUS")
        assert effective is not None
        instants = in_force_instants(tl)
        if effective.instant in instants:
            raise _same_instant()
        if operation == OP_INSERTION:
            if not instants or effective.instant > max(instants):
                raise _err("INSERTION_NOT_HISTORICAL",
                           "No later department event exists; record this as a movement (TRANSFER) instead",
                           status.HTTP_409_CONFLICT)
            source = self._source(tl, effective.instant)
            if department == source[0]:
                return DepartmentOutcome(request_id=request_id, changed=False)
        else:
            if instants and effective.instant < max(instants):
                raise _err("EVENT_NOT_LATEST",
                           "The movement is earlier than the latest department event; record it as a backdated "
                           "insertion or correct the existing event", status.HTTP_409_CONFLICT)
            source = self._source(tl, effective.instant)
            if department == tl.current_department_id:
                return DepartmentOutcome(request_id=request_id, changed=False)
        await self._check_department(department, ctx)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=ASSIGNMENT, entry_operation=operation, revision_no="1", department_id=department,
            effective_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_department_id=source[0] or "",
            recorded_from_source=source[1], reason_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    async def _correct(self, ctx: _Context, head: DepartmentPeriod, department: str, effective: EffectiveTime,
                       reason: str, *, request_id: str, fingerprint: str, user_id: str) -> DepartmentOutcome:
        if (department, effective.stored, effective.precision) == (
            head.department_id, head.effective_at, head.effective_precision,
        ):
            return DepartmentOutcome(request_id=request_id, changed=False)
        tl = ctx.timeline
        if effective.instant in in_force_instants(tl, exclude_event=head.event_id):
            raise _same_instant()
        source = self._source(tl, effective.instant, exclude_event=head.event_id)
        if department != head.department_id:
            # Only a NEW department is proven again; a time-only correction keeps the
            # event's stored department (already proven as a persisted reference).
            await self._check_department(department, ctx)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CORRECTION, entry_operation=OP_CORRECTION, event_id=head.event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            department_id=department, effective_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_department_id=source[0] or "",
            recorded_from_source=source[1], reason_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    # ---------------------------------------------------------------- reads

    async def department_history(self, personnel_id: str, as_of: Mapping[str, object] | None = None
                                 ) -> PersonnelDepartmentHistory:
        """The derived timeline (current department and every period), plus —
        when `as_of` ({"mode": "DATE"|"DATETIME", ...}) is given — the department
        in force AT that instant. An ambiguous tie is UNDETERMINED, never none."""
        instant = self._effective(as_of, self._now(), allow_now=False) if as_of is not None else None
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(personnel_id, context)
        if instant is None:
            return PersonnelDepartmentHistory(ctx.personnel_id, ctx.timeline, None, None, None, None)
        # UNDETERMINED exactly when a same-instant tie decides the answer; an earlier
        # tie followed by a later unique event cannot change it.
        status_, department, since = department_at(ctx.timeline, instant.instant)
        return PersonnelDepartmentHistory(ctx.personnel_id, ctx.timeline, instant.stored, status_, department, since)


__all__ = [
    "HISTORY_PREFIX",
    "OPERATIONS",
    "OP_PERSONNEL_DEPARTMENT",
    "DepartmentOutcome",
    "PersonnelDepartmentHistory",
    "PersonnelDepartmentHistoryService",
    "department_reference",
    "history_department_ids",
    "scoped_history_rows",
]
