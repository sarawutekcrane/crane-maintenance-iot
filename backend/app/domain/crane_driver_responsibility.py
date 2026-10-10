"""R2 Batch R2f-f — Crane / Vehicle ↔ Driver RESPONSIBILITY periods (history-only).

Three distinct concepts are never combined:
1. the Driver master (`driver_master`, Phase 6; READ ONLY here),
2. the Personnel ↔ Driver IDENTITY link (`personnel_master.driver_id`, R2f-e;
   READ ONLY here, for the eligibility gate only — never linked / unlinked),
3. crane Driver RESPONSIBILITY — this module.

Authority: `crane_driver_responsibility_history` (append-only, the ONLY
responsibility authority). There is no projection column, no W2 and no
reconciliation. The Phase 6 `vehicle_driver` assignment history is NOT an
authority, is never read, migrated, normalized, made exclusive or auto-ended,
and its is_primary / assignment_status / end_at mean nothing here. There is no
baseline import: a vehicle with no history has no responsible driver, whatever
vehicle_driver contains. The asset identity is the exact vehicle_id (no crane /
category / status / branch / registration gate).

Operations (one strict, operation-discriminated body), as R2f-d:
- TRANSFER  — the latest event (the first may be from NONE); NOW allowed;
  reason optional.
- INSERTION — backdated, before a later in-force event; no NOW; reason required.
- END       — the latest event; no responsible driver from the instant on;
  reason optional; only while a driver is current.
- CORRECTION / CANCELLATION — a new revision of `event_id`, guarded by
  `expected_revision_no`; reason required; a cancellation is terminal.

Exclusivity: one responsible driver at a time per vehicle (periods derive from
the effective-time order, so they never overlap; one driver may hold many
vehicles); same-instant events are AMBIGUOUS_ORDER and never guessed.

NEW-assignment eligibility (TRANSFER, INSERTION, and a CORRECTION that changes
the driver; never END, CANCELLATION, a time / precision-only correction or a
read), READ ONLY:
- the driver resolves exactly once in the request's scope with
  driver_master.active_status EXACTLY "ACTIVE" (no normalization, no licence
  gate; Phase 6 keeps treating the status as opaque elsewhere);
- the in-scope Personnel holding that driver_id (R2f-e): none -> allowed (a
  driver needs no Personnel link); exactly one -> its active_status must be
  EXACTLY "ACTIVE"; more than one -> fail closed (relationship integrity).

Persisted-history reference integrity (the R2f-d Fix R1 principle from the
start): every stored vehicle_id and every nonblank driver_id /
recorded_from_driver_id of the in-scope history must resolve EXACTLY ONCE in
the same scope before the timeline is trusted (existence / uniqueness / scope
only — no lifecycle check: an inactive historical driver stays valid history).
A defect is 500 CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID, never NONE /
UNRESOLVED / NOT_FOUND or an empty / partial list.

Order: body shape / reason / effective time (422) -> write context (503) ->
vehicle locate (VEHICLE_*) -> ONE history read (tab-wide record-id check, this
vehicle's in-scope structural validation, stored driver references proven) ->
replay -> stale (expected current driver; event revision) -> state and order
rules -> no-op -> NEW-assignment eligibility -> W1. After W1 the only outcomes
are success and DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED; nothing is retried,
compensated, re-read or re-appended. Nothing else is ever written.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import status

from app.domain.crane_driver_timeline import (
    ASSIGNMENT,
    CANCELLATION,
    CORRECTION,
    CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS,
    CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB,
    DRIVER_RESPONSIBILITY_REFERENCE_COLUMNS,
    OP_CANCELLATION,
    OP_CORRECTION,
    OP_END,
    OP_INSERTION,
    OP_TRANSFER,
    STATUS_AMBIGUOUS,
    STATUS_INVALID,
    STATUS_VALID,
    VEHICLE_REFERENCE_TAB,
    ResponsibilityPeriod,
    ResponsibilityTimeline,
    ResponsibilityUndetermined,
    derive_responsibility_timeline,
    driver_before,
    in_force_instants,
    tied_event_ids,
    validate_responsibility_row,
)
from app.domain.effective_time import EffectiveTime, EffectiveTimeError, resolve_effective
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG, in_scope
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
    RepositoryWriteError,
)

MAX_REASON_LENGTH = 500
ACTIVE = "ACTIVE"
OP_CRANE_DRIVER_RESPONSIBILITY = "crane_driver_responsibility"  # the request-fingerprint operation name
VEHICLE_PREFIX = "VEHICLE_MASTER"
DRIVER_PREFIX = "DRIVER_MASTER"
DRIVER_TAB = "driver_master"
HISTORY_PREFIX = "CRANE_DRIVER_RESPONSIBILITY_HISTORY"
CODE_PREFIX = "DRIVER_RESPONSIBILITY"
_NEW_OPERATIONS = (OP_TRANSFER, OP_INSERTION, OP_END)
_REVISION_OPERATIONS = (OP_CORRECTION, OP_CANCELLATION)
OPERATIONS = (*_NEW_OPERATIONS, *_REVISION_OPERATIONS)

REFERENCE_MISSING = "MISSING"
REFERENCE_AMBIGUOUS = "AMBIGUOUS"
REFERENCE_SCOPE_UNPROVEN = "SCOPE_UNPROVEN"


@dataclass(frozen=True)
class ResponsibilityOutcome:
    """A 200 outcome: changed (one record written), no-op, or replay."""

    request_id: str
    changed: bool = False
    replayed: bool = False
    record_id: str | None = None
    event_id: str | None = None
    timeline_status_after: str | None = None
    current_driver_id: str | None = None
    current_status: str | None = None
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class VehicleResponsibleDrivers:
    vehicle_id: str
    timeline: ResponsibilityTimeline


@dataclass(frozen=True)
class DriverVehicleItem:
    vehicle_id: str
    since: str | None
    event_id: str


@dataclass(frozen=True)
class DriverVehicles:
    driver_id: str
    items: tuple[DriverVehicleItem, ...]


@dataclass(frozen=True)
class _Context:
    context: str
    vehicle_id: str
    history: RegistryTableRead
    rows: list[Mapping[str, object]]
    timeline: ResponsibilityTimeline
    drivers: ReferenceMasterRead | None  # the ONE bounded driver read, when the history references any driver


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def _data_invalid(issues: dict[str, int]) -> ApiError:
    return error(f"{HISTORY_PREFIX}_DATA_INVALID",
                 f"{CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB} contains records that cannot be used exactly",
                 status.HTTP_500_INTERNAL_SERVER_ERROR,
                 {"tab": CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB, "issues": dict(sorted(issues.items()))})


def _err(suffix: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return error(f"{CODE_PREFIX}_{suffix}", message, http_status, details)


def _stale(field: str) -> ApiError:
    return _err("HISTORY_STALE", "The vehicle's driver responsibility changed since it was loaded; reload and try again",
                status.HTTP_409_CONFLICT, {"field": field})


def _ambiguous(reason: str) -> ApiError:
    return _err("TIMELINE_AMBIGUOUS",
                "Responsibility events share one effective instant, so the order is undetermined; nothing was changed",
                status.HTTP_409_CONFLICT, {"reason": reason})


def _same_instant() -> ApiError:
    return _err("EVENT_SAME_INSTANT",
                "Another responsibility event already takes effect at this exact instant; nothing was changed",
                status.HTTP_409_CONFLICT)


def _unprocessable(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY, details)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def classify_reference(ref_id: str, reference: ReferenceMasterRead, id_column: str, context: str,
                       batch_id: str) -> str | None:
    """None when `ref_id` resolves EXACTLY ONCE in the request's scope; else
    AMBIGUOUS, SCOPE_UNPROVEN (exact rows only out of scope, or a TEST request
    against a mode that cannot prove TEST rows) or MISSING. Scope is the row's
    proven scope, never the id text."""
    exact = [r for r in reference.rows if text(r.values.get(id_column)) == ref_id]
    matches = [r for r in exact if same_scope(r, context, batch_id)]
    if len(matches) == 1:
        return None
    if matches:
        return REFERENCE_AMBIGUOUS
    if exact or (context != DATA_CONTEXT_REAL and not reference.test_scope_supported):
        return REFERENCE_SCOPE_UNPROVEN
    return REFERENCE_MISSING


def reference_issues(ids: set[str], reference: ReferenceMasterRead, *, id_column: str, label: str, context: str,
                     batch_id: str) -> dict[str, int]:
    """`<label>_REFERENCE_<kind>` -> number of distinct defective ids (no id or
    personal value is ever reported)."""
    issues: dict[str, int] = {}
    for ref_id in sorted(ids):
        kind = classify_reference(ref_id, reference, id_column, context, batch_id)
        if kind is not None:
            code = f"{label}_REFERENCE_{kind}"
            issues[code] = issues.get(code, 0) + 1
    return issues


def history_driver_ids(rows: Sequence[Mapping[str, object]]) -> set[str]:
    """Every nonblank `driver_id` and `recorded_from_driver_id` STORED in the
    rows is a Driver reference. A CANCELLATION contributes none; an END has a
    blank `driver_id` but contributes its nonblank `recorded_from_driver_id`
    (the driver being ended)."""
    return {text(r.get(c)) for r in rows for c in ("driver_id", "recorded_from_driver_id") if text(r.get(c)).strip()}


def scoped_history_rows(rows: Sequence[Mapping[str, object]], vehicle_id: str, context: str,
                        batch_id: str) -> list[Mapping[str, object]]:
    """This vehicle's in-scope rows. Classification first: a row of this
    vehicle with a test flag other than exactly TRUE / FALSE fails closed."""
    own = [r for r in rows if text(r.get("vehicle_id")) == vehicle_id]
    invalid = sum(1 for r in own if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
    if invalid:
        raise _data_invalid({"TEST_FLAG_INVALID": invalid})
    return [r for r in own if in_scope(r, context, batch_id)]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CraneDriverResponsibilityService:
    def __init__(self, repository: Repository, data_context: str | None, test_batch_id: str) -> None:
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    # ---------------------------------------------------------------- body

    @staticmethod
    def _effective(body: Mapping[str, object], now: datetime, *, allow_now: bool) -> EffectiveTime:
        raw = body.get("effective")
        try:
            return resolve_effective(raw if isinstance(raw, Mapping) else {}, now, allow_now=allow_now)
        except EffectiveTimeError as exc:
            raise _unprocessable(exc.code, "The effective time is not accepted") from exc

    @staticmethod
    def _reason(body: Mapping[str, object], *, required: bool) -> str:
        """Kept exactly. Required: a string, not blank, 1-500 characters.
        Optional: absent / null, or the same rule."""
        reason = body.get("reason_th")
        if reason is None and not required:
            return ""
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
            raise _unprocessable("REASON_REQUIRED", f"A reason of 1-{MAX_REASON_LENGTH} characters is required")
        return reason

    @staticmethod
    def _driver_from_body(body: Mapping[str, object]) -> str:
        value = body.get("driver_id")
        if not isinstance(value, str) or not value.strip():
            raise _unprocessable(f"{CODE_PREFIX}_DRIVER_REQUIRED", "A driver_id is required", {"field": "driver_id"})
        return value

    @staticmethod
    def _expected_current(body: Mapping[str, object]) -> str | None:
        value = body.get("expected_current_driver_id")
        return value if isinstance(value, str) and value.strip() else None

    # ---------------------------------------------------------------- reads

    async def _vehicles(self) -> ReferenceMasterRead:
        return await reference_read(self._repository.read_vehicle_reference(), VEHICLE_PREFIX, VEHICLE_REFERENCE_TAB)

    async def _drivers(self) -> ReferenceMasterRead:
        return await reference_read(self._repository.read_driver_responsibility_reference(), DRIVER_PREFIX, DRIVER_TAB)

    async def _locate_vehicle(self, vehicle_id: str, context: str) -> str:
        reference = await self._vehicles()
        kind = classify_reference(vehicle_id, reference, "vehicle_id", context, self._batch_id) \
            if vehicle_id.strip() else REFERENCE_MISSING
        if kind == REFERENCE_AMBIGUOUS:
            raise error("VEHICLE_ID_AMBIGUOUS", "More than one vehicle record has this id", status.HTTP_409_CONFLICT)
        if kind == REFERENCE_SCOPE_UNPROVEN:
            raise _unprocessable("VEHICLE_SCOPE_UNPROVEN",
                                 "This vehicle cannot be proven to belong to the request's data scope")
        if kind == REFERENCE_MISSING:
            raise error("VEHICLE_NOT_FOUND", "No vehicle record has exactly this id", status.HTTP_404_NOT_FOUND)
        return vehicle_id

    async def _history(self) -> RegistryTableRead:
        history = await reference_read(
            self._repository.read_crane_driver_responsibility_history_validated(), HISTORY_PREFIX,
            CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB,
        )
        ids = [text(r.get("record_id")) for r in history.rows if text(r.get("record_id"))]
        if len(ids) != len(set(ids)):  # tab-wide, every scope and vehicle
            raise _data_invalid({"RECORD_ID_DUPLICATE": len(ids) - len(set(ids))})
        return history

    @staticmethod
    def _derive(rows: Sequence[Mapping[str, object]]) -> ResponsibilityTimeline:
        timeline = derive_responsibility_timeline(rows)
        if timeline.status == STATUS_INVALID:
            raise _data_invalid(timeline.issue_counts)
        return timeline

    async def _history_drivers(self, rows: Sequence[Mapping[str, object]], context: str) -> ReferenceMasterRead | None:
        """ONE bounded driver read (only when the rows reference a driver) and
        the same-scope proof of every stored driver id (no lifecycle check)."""
        ids = history_driver_ids(rows)
        if not ids:
            return None
        drivers = await self._drivers()
        issues = reference_issues(ids, drivers, id_column="driver_id", label="DRIVER", context=context,
                                  batch_id=self._batch_id)
        if issues:
            raise _data_invalid(issues)
        return drivers

    async def _read(self, vehicle_id: str, context: str) -> _Context:
        """The requested vehicle is proven by the locate (its rows carry exactly
        that id, so it is not re-read); every stored driver reference is proven
        before the timeline is used."""
        located = await self._locate_vehicle(vehicle_id, context)
        history = await self._history()
        rows = scoped_history_rows(history.rows, located, context, self._batch_id)
        timeline = self._derive(rows)
        drivers = await self._history_drivers(rows, context)
        return _Context(context, located, history, rows, timeline, drivers)

    # ---------------------------------------------------------------- guards

    @staticmethod
    def _replay(ctx: _Context, request_id: str, fingerprint: str) -> ResponsibilityOutcome | None:
        hit = find_replay(ctx.history.rows, request_id, fingerprint, record_id_column="record_id")
        if hit is None:
            return None
        if not hit.replayed:
            raise error("REQUEST_ID_REUSED",
                        "This request id was already used for a different change; nothing was changed",
                        status.HTTP_409_CONFLICT, {"request_id": request_id})
        return ResponsibilityOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids)

    @staticmethod
    def _event(ctx: _Context, event_id: str) -> ResponsibilityPeriod:
        event = next((e for e in ctx.timeline.events if e.event_id == event_id), None)
        if event is None:
            raise _err("EVENT_NOT_FOUND", "No responsibility event with this id exists for this vehicle",
                       status.HTTP_404_NOT_FOUND, {"event_id": event_id})
        if not event.in_force:
            raise _err("EVENT_CANCELLED", "This responsibility event was cancelled; nothing was changed",
                       status.HTTP_409_CONFLICT, {"event_id": event_id})
        return event

    async def _check_new_driver(self, driver_id: str, context: str,
                                drivers: ReferenceMasterRead | None = None) -> None:
        """The NEW-assignment eligibility (read only): the driver exactly once in
        scope with active_status exactly ACTIVE; a linked Personnel (if any)
        exactly ACTIVE; more than one linked Personnel fails closed."""
        if drivers is None:
            drivers = await self._drivers()
        kind = classify_reference(driver_id, drivers, "driver_id", context, self._batch_id)
        if kind == REFERENCE_AMBIGUOUS:
            raise error("DRIVER_ID_AMBIGUOUS", "More than one driver record has this driver_id",
                        status.HTTP_409_CONFLICT, {"driver_id": driver_id})
        if kind == REFERENCE_SCOPE_UNPROVEN:
            raise _unprocessable("DRIVER_SCOPE_UNPROVEN",
                                 "This driver cannot be proven to belong to the request's data scope",
                                 {"driver_id": driver_id})
        if kind == REFERENCE_MISSING:
            raise _unprocessable("DRIVER_NOT_FOUND", "No driver record has exactly this driver_id",
                                 {"driver_id": driver_id})
        (match,) = [r for r in drivers.rows if text(r.values.get("driver_id")) == driver_id
                    and same_scope(r, context, self._batch_id)]
        if text(match.values.get("active_status")) != ACTIVE:
            raise _unprocessable("DRIVER_NOT_ACTIVE", "Only an ACTIVE driver can become responsible for a vehicle",
                                 {"driver_id": driver_id})
        master = await reference_read(
            self._repository.read_personnel_relationship_master(), PERSONNEL_PREFIX, PERSONNEL_TAB
        )
        holders = [p for p in scoped_personnel(master.rows, context, self._batch_id)
                   if text(p.get("driver_id")) == driver_id]
        if not holders:
            return  # a driver needs no Personnel link
        if len(holders) > 1:
            raise error("DRIVER_PERSONNEL_AMBIGUOUS",
                        "More than one personnel record is linked to this driver; nothing was changed",
                        status.HTTP_409_CONFLICT, {"driver_id": driver_id, "match_count": len(holders)})
        if text(holders[0].get("active_status")) != ACTIVE:
            raise _unprocessable("PERSONNEL_NOT_ACTIVE", "The personnel record linked to this driver is not ACTIVE",
                                 {"driver_id": driver_id})

    # ---------------------------------------------------------------- write

    def _row(self, ctx: _Context, *, request_id: str, fingerprint: str, user_id: str, **cells: str) -> dict[str, str]:
        row = dict.fromkeys(CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS, "")
        record_id = f"CDR-{uuid.uuid4().hex}"
        row.update(
            record_id=record_id,
            vehicle_id=ctx.vehicle_id,
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
        issues = validate_responsibility_row(row)
        if issues:  # a programming error, before any write
            raise RuntimeError(f"generated responsibility history row is invalid: {issues}")
        return row

    async def _commit(self, ctx: _Context, row: dict[str, str], *, request_id: str) -> ResponsibilityOutcome:
        """The timeline after is derived in memory BEFORE W1 (an INVALID result
        is a programming error and nothing is written), then W1 only."""
        after = derive_responsibility_timeline([*ctx.rows, row])
        if after.status == STATUS_INVALID:
            raise RuntimeError(f"generated responsibility row breaks the timeline: {after.issue_counts}")
        try:
            await self._repository.append_crane_driver_responsibility_history(ctx.history, row)
        except RepositoryWriteError as exc:
            message = (
                "Google Sheets rejected the responsibility-history write; nothing was changed by this request"
                if exc.outcome == "rejected"
                else "The responsibility-history write outcome is unknown (the record may have been written); "
                "nothing was retried"
            )
            raise _err("HISTORY_WRITE_FAILED", message, status.HTTP_503_SERVICE_UNAVAILABLE,
                       {"history_write_outcome": exc.outcome, "request_id": request_id}) from exc
        return ResponsibilityOutcome(
            request_id=request_id, changed=True, record_id=row["record_id"], event_id=row["event_id"],
            timeline_status_after=after.status, current_driver_id=after.current_driver_id,
            current_status=after.current_status,
        )

    @staticmethod
    def _source(timeline: ResponsibilityTimeline, instant: datetime, *, exclude_event: str | None = None):
        try:
            return driver_before(timeline, instant, exclude_event=exclude_event)
        except ResponsibilityUndetermined as exc:  # never guessed
            raise _ambiguous("SOURCE_UNDETERMINED") from exc

    async def record_event(
        self, vehicle_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> ResponsibilityOutcome:
        operation = text(body.get("operation"))
        if operation not in OPERATIONS:  # the schema already refuses; defensive
            raise _unprocessable(f"{CODE_PREFIX}_OPERATION_INVALID", "Unknown responsibility operation")
        now = self._now()
        driver = ""
        if operation in (OP_TRANSFER, OP_INSERTION):
            driver = self._driver_from_body(body)
        elif operation == OP_CORRECTION and body.get("driver_id") is not None:
            driver = self._driver_from_body(body)
        effective = None
        if operation != OP_CANCELLATION:
            effective = self._effective(body, now, allow_now=operation in (OP_TRANSFER, OP_END))
        reason = self._reason(body, required=operation in (OP_INSERTION, *_REVISION_OPERATIONS))
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(vehicle_id, context)
        event_id = text(body.get("event_id")) if operation in _REVISION_OPERATIONS else None
        fingerprint = request_fingerprint(OP_CRANE_DRIVER_RESPONSIBILITY, ctx.vehicle_id, event_id, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        # Stale guards before every state rule and before the no-op check.
        if self._expected_current(body) != tl.current_driver_id:
            raise _stale("current_driver_id")
        if operation in _REVISION_OPERATIONS:
            assert event_id is not None
            head = self._event(ctx, event_id)
            if body.get("expected_revision_no") != head.revision_no:  # exact text, as sent
                raise _stale("revision_no")
            if tl.status == STATUS_AMBIGUOUS and event_id not in tied_event_ids(tl):
                raise _ambiguous("TARGET_NOT_TIED")
            if operation == OP_CANCELLATION:
                return await self._cancel(ctx, head, reason, request_id=request_id, fingerprint=fingerprint,
                                          user_id=user_id)
            assert effective is not None
            return await self._correct(ctx, head, driver, effective, reason, request_id=request_id,
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
                           "No later responsibility event exists; record this as a transfer instead",
                           status.HTTP_409_CONFLICT)
            source = self._source(tl, effective.instant)
            if driver == source[0]:
                return ResponsibilityOutcome(request_id=request_id, changed=False)
        else:
            if instants and effective.instant < max(instants):
                raise _err("EVENT_NOT_LATEST",
                           "The event is earlier than the latest responsibility event; record it as a backdated "
                           "insertion or correct the existing event", status.HTTP_409_CONFLICT)
            source = self._source(tl, effective.instant)
            if operation == OP_END:
                if tl.current_driver_id is None:
                    return ResponsibilityOutcome(request_id=request_id, changed=False)
            elif driver == tl.current_driver_id:
                return ResponsibilityOutcome(request_id=request_id, changed=False)
        if operation != OP_END:
            await self._check_new_driver(driver, context, ctx.drivers)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=ASSIGNMENT, entry_operation=operation, revision_no="1",
            driver_id=driver if operation != OP_END else "",
            effective_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_driver_id=source[0] or "",
            recorded_from_source=source[1], reason_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    async def _correct(self, ctx: _Context, head: ResponsibilityPeriod, driver: str, effective: EffectiveTime,
                       reason: str, *, request_id: str, fingerprint: str, user_id: str) -> ResponsibilityOutcome:
        is_end = head.driver_id is None
        if is_end and driver:
            raise _unprocessable(f"{CODE_PREFIX}_CORRECTION_CHANGES_EVENT_NATURE",
                                 "An END event takes no driver_id; cancel it instead", {"field": "driver_id"})
        if not is_end and not driver:
            raise _unprocessable(f"{CODE_PREFIX}_DRIVER_REQUIRED",
                                 "A correction of an assignment requires driver_id", {"field": "driver_id"})
        target = driver or None
        if (target, effective.stored, effective.precision) == (
            head.driver_id, head.effective_at, head.effective_precision,
        ):
            return ResponsibilityOutcome(request_id=request_id, changed=False)
        tl = ctx.timeline
        if effective.instant in in_force_instants(tl, exclude_event=head.event_id):
            raise _same_instant()
        source = self._source(tl, effective.instant, exclude_event=head.event_id)
        if is_end and source[0] is None:
            raise _err("END_WITHOUT_DRIVER",
                       "No driver is responsible just before this instant, so an END cannot take effect there",
                       status.HTTP_409_CONFLICT)
        if target is not None and target != head.driver_id:
            # Only a NEW driver is gated; a time / precision-only correction keeps
            # the event's existing driver unchecked.
            await self._check_new_driver(target, ctx.context, ctx.drivers)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CORRECTION, entry_operation=OP_CORRECTION, event_id=head.event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            driver_id=driver, effective_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_driver_id=source[0] or "",
            recorded_from_source=source[1], reason_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    async def _cancel(self, ctx: _Context, head: ResponsibilityPeriod, reason: str, *, request_id: str,
                      fingerprint: str, user_id: str) -> ResponsibilityOutcome:
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CANCELLATION, entry_operation=OP_CANCELLATION, event_id=head.event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            reason_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    # ---------------------------------------------------------------- reads

    async def responsible_drivers(self, vehicle_id: str) -> VehicleResponsibleDrivers:
        """The derived timeline of one vehicle in the request's scope.
        AMBIGUOUS_ORDER is returned explicitly (current UNDETERMINED, never
        "none"); INVALID is 500 CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID."""
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(vehicle_id, context)
        return VehicleResponsibleDrivers(ctx.vehicle_id, ctx.timeline)

    async def driver_vehicles(self, driver_id: str) -> DriverVehicles:
        """Reverse read: the vehicles whose CURRENT responsible driver is exactly
        this driver, from the SAME validated history (no reverse index). The
        requested driver is proven exactly once in scope; every stored vehicle
        and driver reference is same-scope proven before any id is returned;
        any in-scope timeline that is not VALID fails closed."""
        context = require_write_context(self._context, self._batch_id)
        drivers = await self._drivers()
        kind = classify_reference(driver_id, drivers, "driver_id", context, self._batch_id) \
            if driver_id.strip() else REFERENCE_MISSING
        if kind == REFERENCE_AMBIGUOUS:
            raise error("DRIVER_ID_AMBIGUOUS", "More than one driver record has this driver_id",
                        status.HTTP_409_CONFLICT)
        if kind == REFERENCE_SCOPE_UNPROVEN:
            raise _unprocessable("DRIVER_SCOPE_UNPROVEN",
                                 "This driver cannot be proven to belong to the request's data scope")
        if kind == REFERENCE_MISSING:
            raise error("DRIVER_NOT_FOUND", "No driver record has exactly this driver_id", status.HTTP_404_NOT_FOUND)
        history = await self._history()
        by_vehicle = {vid: scoped_history_rows(history.rows, vid, context, self._batch_id)
                      for vid in sorted({text(r.get("vehicle_id")) for r in history.rows})}
        by_vehicle = {vid: rows for vid, rows in by_vehicle.items() if rows}
        timelines = {vid: self._derive(rows) for vid, rows in by_vehicle.items()}
        issues: dict[str, int] = {}
        if by_vehicle:
            vehicles = await self._vehicles()
            issues.update(reference_issues(set(by_vehicle), vehicles, id_column="vehicle_id", label="VEHICLE",
                                           context=context, batch_id=self._batch_id))
        all_rows = [r for rows in by_vehicle.values() for r in rows]
        issues.update(reference_issues(history_driver_ids(all_rows), drivers, id_column="driver_id", label="DRIVER",
                                       context=context, batch_id=self._batch_id))
        if issues:
            raise _data_invalid(issues)
        items: list[DriverVehicleItem] = []
        ambiguous = 0
        for vid, tl in timelines.items():
            if tl.status != STATUS_VALID:
                ambiguous += 1
                continue
            if tl.current_driver_id == driver_id:
                current = next(e for e in tl.events if e.in_force and e.effective_at == tl.current_since)
                items.append(DriverVehicleItem(vid, tl.current_since, current.event_id))
        if ambiguous:
            raise _err("TIMELINE_AMBIGUOUS",
                       "Some vehicle responsibility timelines are undetermined, so this list cannot be complete",
                       status.HTTP_409_CONFLICT, {"reason": "TIMELINE_AMBIGUOUS", "vehicle_count": ambiguous})
        return DriverVehicles(driver_id, tuple(items))


__all__ = [
    "DRIVER_RESPONSIBILITY_REFERENCE_COLUMNS",
    "HISTORY_PREFIX",
    "OPERATIONS",
    "OP_CRANE_DRIVER_RESPONSIBILITY",
    "CraneDriverResponsibilityService",
    "DriverVehicleItem",
    "DriverVehicles",
    "ResponsibilityOutcome",
    "VehicleResponsibleDrivers",
    "classify_reference",
    "history_driver_ids",
    "reference_issues",
    "scoped_history_rows",
]
