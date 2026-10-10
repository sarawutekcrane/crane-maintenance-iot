"""R2 Batch R2f-d — Equipment ↔ Technician caretaker periods (history-only).

Authority: `equipment_caretaker_history` (append-only, the ONLY caretaker
authority). There is no projection column (equipment_master gains none and is
never written), no W2 and no reconciliation; `asset_responsibility_history` is
not read, written, migrated or normalized, and its roles are not vocabulary.
There is no baseline or import: an equipment with no history has no caretaker.

Operations (one strict, operation-discriminated body):
- TRANSFER  — the latest event: the technician becomes the caretaker (the first
  assignment is a TRANSFER from "no caretaker"); NOW allowed; reason optional.
- INSERTION — a backdated assignment before a later in-force event (no NOW);
  reason required.
- END       — the latest event: no caretaker from the instant on; NOW allowed;
  reason optional; only while a caretaker is current.
- CORRECTION / CANCELLATION — a new revision of an existing event (event_id +
  expected_revision_no); reason required; a cancellation is terminal.

Exclusivity: one caretaker at a time per equipment (periods are derived from
the event order, so they never overlap); events at the same effective instant
are AMBIGUOUS_ORDER and never guessed — new events are refused and only a tied
event may be corrected or cancelled.

NEW-assignment gate (TRANSFER, INSERTION, and a CORRECTION that changes the
technician; never END or CANCELLATION): the technician exists exactly once in
the request's scope with active_status exactly ACTIVE, AND exactly one
in-scope Personnel record holds that technician_id with active_status exactly
ACTIVE. Scope is the server's data context, never an id prefix or name.

Order: body shape / reason / effective time (422) -> write context (503) ->
equipment locate (EQUIPMENT_*) -> ONE caretaker-history read (tab-wide record
and request id checks, this equipment's in-scope structural validation) ->
replay -> stale (expected current caretaker; event revision) -> state and
order rules -> no-op -> NEW-assignment gate -> W1. After W1 the only outcomes
are success and CARETAKER_HISTORY_WRITE_FAILED; nothing is retried,
compensated, re-read or re-appended.

Nothing here touches inspections: a caretaker is display information only and
never authorizes, selects or gates an inspection or its inspector.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import status

from app.domain.caretaker_timeline import (
    ASSIGNMENT,
    CANCELLATION,
    CORRECTION,
    EQUIPMENT_CARETAKER_HISTORY_COLUMNS,
    EQUIPMENT_CARETAKER_HISTORY_TAB,
    EQUIPMENT_REFERENCE_TAB,
    OP_CANCELLATION,
    OP_CORRECTION,
    OP_END,
    OP_INSERTION,
    OP_TRANSFER,
    STATUS_AMBIGUOUS,
    STATUS_INVALID,
    STATUS_VALID,
    CaretakerPeriod,
    CaretakerTimeline,
    CaretakerUndetermined,
    caretaker_before,
    derive_caretaker_timeline,
    in_force_instants,
    tied_event_ids,
    validate_caretaker_row,
)
from app.domain.effective_time import EffectiveTime, EffectiveTimeError, resolve_effective
from app.domain.personnel_relationship import PERSONNEL_PREFIX, PERSONNEL_TAB, same_scope, scoped_personnel
from app.domain.reference_read import reference_read
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG, in_scope
from app.domain.registration import DATA_CONTEXT_REAL, DATA_CONTEXT_TEST, text
from app.domain.registry_write_support import error, require_write_context
from app.domain.request_replay import find_replay, request_fingerprint
from app.domain.technician import TechnicianRecord, read_technicians, technician_record
from app.errors import ApiError
from app.repositories.base import (
    ReferenceMasterRead,
    RegistryTableRead,
    Repository,
    RepositoryWriteError,
)

MAX_REASON_LENGTH = 500
ACTIVE = "ACTIVE"
OP_EQUIPMENT_CARETAKER = "equipment_caretaker"  # the request-fingerprint operation name
EQUIPMENT_PREFIX = "EQUIPMENT_MASTER"
HISTORY_PREFIX = "EQUIPMENT_CARETAKER_HISTORY"
_NEW_OPERATIONS = (OP_TRANSFER, OP_INSERTION, OP_END)
_REVISION_OPERATIONS = (OP_CORRECTION, OP_CANCELLATION)
OPERATIONS = (*_NEW_OPERATIONS, *_REVISION_OPERATIONS)


@dataclass(frozen=True)
class CaretakerOutcome:
    """A 200 outcome: changed (one record written), no-op, or replay."""

    request_id: str
    changed: bool = False
    replayed: bool = False
    record_id: str | None = None
    event_id: str | None = None
    timeline_status_after: str | None = None
    current_technician_id: str | None = None
    current_status: str | None = None
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EquipmentCaretakers:
    equipment_id: str
    timeline: CaretakerTimeline
    current_technician: TechnicianRecord | None  # display only; None unless resolved in scope
    current_technician_resolution: str  # RESOLVED / NONE / UNDETERMINED / UNRESOLVED


@dataclass(frozen=True)
class TechnicianEquipmentItem:
    equipment_id: str
    since: str | None
    event_id: str


@dataclass(frozen=True)
class TechnicianEquipment:
    technician_id: str
    items: tuple[TechnicianEquipmentItem, ...]


@dataclass(frozen=True)
class _Context:
    context: str
    equipment_id: str
    history: RegistryTableRead
    rows: list[Mapping[str, object]]
    timeline: CaretakerTimeline
    technicians: ReferenceMasterRead | None  # the ONE bounded read, when the history references any technician


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def _data_invalid(prefix: str, tab: str, issues: dict[str, int]) -> ApiError:
    return error(f"{prefix}_DATA_INVALID", f"{tab} contains records that cannot be used exactly",
                 status.HTTP_500_INTERNAL_SERVER_ERROR, {"tab": tab, "issues": dict(sorted(issues.items()))})


def _stale(field: str) -> ApiError:
    return error("CARETAKER_HISTORY_STALE",
                 "The equipment's caretaker history changed since it was loaded; reload and try again",
                 status.HTTP_409_CONFLICT, {"field": field})


def _ambiguous(reason: str) -> ApiError:
    return error("CARETAKER_TIMELINE_AMBIGUOUS",
                 "Caretaker events share one effective instant, so the order is undetermined; nothing was changed",
                 status.HTTP_409_CONFLICT, {"reason": reason})


def _same_instant() -> ApiError:
    return error("CARETAKER_EVENT_SAME_INSTANT",
                 "Another caretaker event already takes effect at this exact instant; nothing was changed",
                 status.HTTP_409_CONFLICT)


def _unprocessable(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY, details)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def scoped_history_rows(rows: Sequence[Mapping[str, object]], equipment_id: str, context: str,
                        batch_id: str) -> list[Mapping[str, object]]:
    """This equipment's in-scope rows. Classification first: a row of this
    equipment with a test flag other than exactly TRUE / FALSE fails closed."""
    own = [r for r in rows if text(r.get("equipment_id")) == equipment_id]
    invalid = sum(1 for r in own if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
    if invalid:
        raise _data_invalid(HISTORY_PREFIX, EQUIPMENT_CARETAKER_HISTORY_TAB, {"TEST_FLAG_INVALID": invalid})
    return [r for r in own if in_scope(r, context, batch_id)]


# Persisted-history reference integrity (Independent Review Fix R1). OD-13 /
# Corrected C1: REAL history references REAL equipment / technicians; TEST
# history references TEST-scoped ones of exactly the server batch. A stored
# reference that cannot be proven so is a HISTORY DATA DEFECT (500
# EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID), never NONE / UNRESOLVED / NOT_FOUND
# or an empty list. Existence, uniqueness and scope ONLY: no lifecycle (ACTIVE)
# check — an inactive historical technician stays valid history.
REFERENCE_MISSING = "MISSING"
REFERENCE_AMBIGUOUS = "AMBIGUOUS"
REFERENCE_SCOPE_UNPROVEN = "SCOPE_UNPROVEN"


def classify_reference(ref_id: str, reference: ReferenceMasterRead, id_column: str, context: str,
                       batch_id: str) -> str | None:
    """None when `ref_id` resolves EXACTLY ONCE in the request's scope; else
    AMBIGUOUS (several in scope), SCOPE_UNPROVEN (exact rows exist only out of
    scope, or a TEST request against a mode that cannot prove TEST rows) or
    MISSING. Scope is the row's proven scope, never the id text."""
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


def history_technician_ids(rows: Sequence[Mapping[str, object]]) -> set[str]:
    """Every nonblank `technician_id` and `recorded_from_technician_id` STORED
    in the rows is a Technician reference. A CANCELLATION contributes none; an
    END has a blank `technician_id` but contributes its nonblank
    `recorded_from_technician_id` (the caretaker being ended)."""
    return {text(r.get(c)) for r in rows for c in ("technician_id", "recorded_from_technician_id")
            if text(r.get(c)).strip()}


def _tab_issues(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Tab-wide identity checks (every scope, every equipment)."""
    issues: dict[str, int] = {}
    ids = [text(r.get("record_id")) for r in rows if text(r.get("record_id"))]
    if len(ids) != len(set(ids)):
        issues["RECORD_ID_DUPLICATE"] = len(ids) - len(set(ids))
    return issues


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EquipmentCaretakerService:
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
    def _technician_from_body(body: Mapping[str, object]) -> str:
        value = body.get("technician_id")
        if not isinstance(value, str) or not value.strip():
            raise _unprocessable("CARETAKER_TECHNICIAN_REQUIRED", "A technician_id is required",
                                 {"field": "technician_id"})
        return value

    @staticmethod
    def _expected_current(body: Mapping[str, object]) -> str | None:
        value = body.get("expected_current_technician_id")
        return value if isinstance(value, str) and value.strip() else None

    # ---------------------------------------------------------------- reads

    async def _locate_equipment(self, equipment_id: str, context: str) -> str:
        reference: ReferenceMasterRead = await reference_read(
            self._repository.read_equipment_reference(), EQUIPMENT_PREFIX, EQUIPMENT_REFERENCE_TAB
        )
        exact = [r for r in reference.rows if equipment_id.strip() and text(r.values.get("equipment_id")) == equipment_id]
        matches = [r for r in exact if same_scope(r, context, self._batch_id)]
        if len(matches) > 1:
            raise error("EQUIPMENT_ID_AMBIGUOUS", "More than one equipment record has this id",
                        status.HTTP_409_CONFLICT, {"match_count": len(matches)})
        if matches:
            return equipment_id
        if context != DATA_CONTEXT_REAL and (not reference.test_scope_supported or exact):
            raise _unprocessable("EQUIPMENT_SCOPE_UNPROVEN",
                                 "This equipment cannot be proven to belong to the request's data scope")
        raise error("EQUIPMENT_NOT_FOUND", "No equipment record has exactly this id", status.HTTP_404_NOT_FOUND)

    async def _history(self) -> RegistryTableRead:
        history = await reference_read(
            self._repository.read_equipment_caretaker_history_validated(), HISTORY_PREFIX,
            EQUIPMENT_CARETAKER_HISTORY_TAB,
        )
        issues = _tab_issues(history.rows)
        if issues:
            raise _data_invalid(HISTORY_PREFIX, EQUIPMENT_CARETAKER_HISTORY_TAB, issues)
        return history

    @staticmethod
    def _derive(rows: Sequence[Mapping[str, object]]) -> CaretakerTimeline:
        timeline = derive_caretaker_timeline(rows)
        if timeline.status == STATUS_INVALID:
            raise _data_invalid(HISTORY_PREFIX, EQUIPMENT_CARETAKER_HISTORY_TAB, timeline.issue_counts)
        return timeline

    def _require_references(self, issues: dict[str, int]) -> None:
        if issues:
            raise _data_invalid(HISTORY_PREFIX, EQUIPMENT_CARETAKER_HISTORY_TAB, issues)

    async def _history_technicians(self, rows: Sequence[Mapping[str, object]], context: str):
        """ONE bounded technician read (only when the rows reference any
        technician) and the same-scope proof of every stored technician id."""
        ids = history_technician_ids(rows)
        if not ids:
            return None
        technicians = await read_technicians(self._repository)
        self._require_references(reference_issues(ids, technicians, id_column="technician_id", label="TECHNICIAN",
                                                  context=context, batch_id=self._batch_id))
        return technicians

    async def _read(self, equipment_id: str, context: str) -> _Context:
        """The requested equipment is proven by the locate (its rows carry
        exactly that id, so the equipment reference is not re-read); every
        stored technician reference is proven before the timeline is used."""
        located = await self._locate_equipment(equipment_id, context)
        history = await self._history()
        rows = scoped_history_rows(history.rows, located, context, self._batch_id)
        timeline = self._derive(rows)
        technicians = await self._history_technicians(rows, context)
        return _Context(context, located, history, rows, timeline, technicians)

    # ---------------------------------------------------------------- guards

    @staticmethod
    def _replay(ctx: _Context, request_id: str, fingerprint: str) -> CaretakerOutcome | None:
        hit = find_replay(ctx.history.rows, request_id, fingerprint, record_id_column="record_id")
        if hit is None:
            return None
        if not hit.replayed:
            raise error("REQUEST_ID_REUSED",
                        "This request id was already used for a different change; nothing was changed",
                        status.HTTP_409_CONFLICT, {"request_id": request_id})
        return CaretakerOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids)

    @staticmethod
    def _event(ctx: _Context, event_id: str) -> CaretakerPeriod:
        event = next((e for e in ctx.timeline.events if e.event_id == event_id), None)
        if event is None:
            raise error("CARETAKER_EVENT_NOT_FOUND", "No caretaker event with this id exists for this equipment",
                        status.HTTP_404_NOT_FOUND, {"event_id": event_id})
        if not event.in_force:
            raise error("CARETAKER_EVENT_CANCELLED", "This caretaker event was cancelled; nothing was changed",
                        status.HTTP_409_CONFLICT, {"event_id": event_id})
        return event

    async def _check_new_caretaker(self, technician_id: str, context: str,
                                   technicians: ReferenceMasterRead | None = None) -> None:
        """The NEW-assignment gate: technician exact ACTIVE in scope, and
        exactly one in-scope Personnel holding it, exact ACTIVE. Reuses the
        request's bounded technician read when one was already made."""
        if technicians is None:
            technicians = await read_technicians(self._repository)
        exact = [r for r in technicians.rows if text(r.values.get("technician_id")) == technician_id]
        matches = [r for r in exact if same_scope(r, context, self._batch_id)]
        if len(matches) > 1:
            raise error("TECHNICIAN_ID_AMBIGUOUS", "More than one technician record has this technician_id",
                        status.HTTP_409_CONFLICT, {"match_count": len(matches)})
        if not matches:
            if context != DATA_CONTEXT_REAL and (not technicians.test_scope_supported or exact):
                raise _unprocessable("TECHNICIAN_SCOPE_UNPROVEN",
                                     "This technician cannot be proven to belong to the request's data scope",
                                     {"technician_id": technician_id})
            raise _unprocessable("TECHNICIAN_NOT_FOUND", "No technician record has exactly this technician_id",
                                 {"technician_id": technician_id})
        if text(matches[0].values.get("active_status")) != ACTIVE:
            raise _unprocessable("TECHNICIAN_NOT_ACTIVE", "Only an ACTIVE technician can become a caretaker",
                                 {"technician_id": technician_id})
        master = await reference_read(
            self._repository.read_personnel_relationship_master(), PERSONNEL_PREFIX, PERSONNEL_TAB
        )
        holders = [p for p in scoped_personnel(master.rows, context, self._batch_id)
                   if text(p.get("technician_id")) == technician_id]
        if not holders:
            raise _unprocessable("TECHNICIAN_PERSONNEL_UNRESOLVED",
                                 "No personnel record in this data scope is linked to this technician",
                                 {"technician_id": technician_id})
        if len(holders) > 1:
            raise error("TECHNICIAN_PERSONNEL_AMBIGUOUS",
                        "More than one personnel record is linked to this technician; nothing was changed",
                        status.HTTP_409_CONFLICT, {"technician_id": technician_id, "match_count": len(holders)})
        if text(holders[0].get("active_status")) != ACTIVE:
            raise _unprocessable("PERSONNEL_NOT_ACTIVE",
                                 "The personnel record linked to this technician is not ACTIVE",
                                 {"technician_id": technician_id})

    # ---------------------------------------------------------------- write

    def _row(self, ctx: _Context, *, request_id: str, fingerprint: str, user_id: str, **cells: str) -> dict[str, str]:
        row = dict.fromkeys(EQUIPMENT_CARETAKER_HISTORY_COLUMNS, "")
        record_id = f"ECH-{uuid.uuid4().hex}"
        row.update(
            record_id=record_id,
            equipment_id=ctx.equipment_id,
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
        issues = validate_caretaker_row(row)
        if issues:  # a programming error, before any write
            raise RuntimeError(f"generated caretaker history row is invalid: {issues}")
        return row

    async def _commit(self, ctx: _Context, row: dict[str, str], *, request_id: str) -> CaretakerOutcome:
        """The timeline after is derived in memory BEFORE W1 (an INVALID result
        is a programming error and nothing is written), then W1 only."""
        after = derive_caretaker_timeline([*ctx.rows, row])
        if after.status == STATUS_INVALID:
            raise RuntimeError(f"generated caretaker history row breaks the timeline: {after.issue_counts}")
        try:
            await self._repository.append_equipment_caretaker_history(ctx.history, row)
        except RepositoryWriteError as exc:
            message = (
                "Google Sheets rejected the caretaker-history write; nothing was changed by this request"
                if exc.outcome == "rejected"
                else "The caretaker-history write outcome is unknown (the record may have been written); "
                "nothing was retried"
            )
            raise error("CARETAKER_HISTORY_WRITE_FAILED", message, status.HTTP_503_SERVICE_UNAVAILABLE,
                        {"history_write_outcome": exc.outcome, "request_id": request_id}) from exc
        return CaretakerOutcome(
            request_id=request_id, changed=True, record_id=row["record_id"], event_id=row["event_id"],
            timeline_status_after=after.status, current_technician_id=after.current_technician_id,
            current_status=after.current_status,
        )

    @staticmethod
    def _source(timeline: CaretakerTimeline, instant: datetime, *, exclude_event: str | None = None):
        try:
            return caretaker_before(timeline, instant, exclude_event=exclude_event)
        except CaretakerUndetermined as exc:  # never guessed
            raise _ambiguous("SOURCE_UNDETERMINED") from exc

    async def record_event(
        self, equipment_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> CaretakerOutcome:
        operation = text(body.get("operation"))
        if operation not in OPERATIONS:  # the schema already refuses; defensive
            raise _unprocessable("CARETAKER_OPERATION_INVALID", "Unknown caretaker operation")
        now = self._now()
        technician = ""
        if operation in (OP_TRANSFER, OP_INSERTION):
            technician = self._technician_from_body(body)
        elif operation == OP_CORRECTION and body.get("technician_id") is not None:
            technician = self._technician_from_body(body)
        effective = None
        if operation != OP_CANCELLATION:
            effective = self._effective(body, now, allow_now=operation in (OP_TRANSFER, OP_END))
        reason = self._reason(body, required=operation in (OP_INSERTION, *_REVISION_OPERATIONS))
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(equipment_id, context)
        event_id = text(body.get("event_id")) if operation in _REVISION_OPERATIONS else None
        fingerprint = request_fingerprint(OP_EQUIPMENT_CARETAKER, ctx.equipment_id, event_id, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        # Stale guards before every state rule and before the no-op check.
        if self._expected_current(body) != tl.current_technician_id:
            raise _stale("current_technician_id")
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
            return await self._correct(ctx, head, technician, effective, reason, request_id=request_id,
                                       fingerprint=fingerprint, user_id=user_id)
        if tl.status == STATUS_AMBIGUOUS:
            raise _ambiguous("TIMELINE_AMBIGUOUS")
        assert effective is not None
        instants = in_force_instants(tl)
        if effective.instant in instants:
            raise _same_instant()
        if operation == OP_INSERTION:
            if not instants or effective.instant > max(instants):
                raise error("CARETAKER_INSERTION_NOT_HISTORICAL",
                            "No later caretaker event exists; record this as a transfer instead",
                            status.HTTP_409_CONFLICT)
            source = self._source(tl, effective.instant)
            if technician == source[0]:
                return CaretakerOutcome(request_id=request_id, changed=False)
        else:
            if instants and effective.instant < max(instants):
                raise error("CARETAKER_EVENT_NOT_LATEST",
                            "The event is earlier than the latest caretaker event; record it as a backdated "
                            "insertion or correct the existing event", status.HTTP_409_CONFLICT)
            source = self._source(tl, effective.instant)
            if operation == OP_END:
                if tl.current_technician_id is None:
                    return CaretakerOutcome(request_id=request_id, changed=False)
            elif technician == tl.current_technician_id:
                return CaretakerOutcome(request_id=request_id, changed=False)
        if operation != OP_END:
            await self._check_new_caretaker(technician, context, ctx.technicians)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=ASSIGNMENT, entry_operation=operation, revision_no="1",
            technician_id=technician if operation != OP_END else "",
            effective_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_technician_id=source[0] or "",
            recorded_from_source=source[1], reason_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    async def _correct(self, ctx: _Context, head: CaretakerPeriod, technician: str, effective: EffectiveTime,
                       reason: str, *, request_id: str, fingerprint: str, user_id: str) -> CaretakerOutcome:
        is_end = head.technician_id is None
        if is_end and technician:
            raise _unprocessable("CARETAKER_CORRECTION_CHANGES_EVENT_NATURE",
                                 "An END event takes no technician_id; cancel it instead", {"field": "technician_id"})
        if not is_end and not technician:
            raise _unprocessable("CARETAKER_TECHNICIAN_REQUIRED",
                                 "A correction of an assignment requires technician_id", {"field": "technician_id"})
        target = technician or None
        if (target, effective.stored, effective.precision) == (
            head.technician_id, head.effective_at, head.effective_precision,
        ):
            return CaretakerOutcome(request_id=request_id, changed=False)
        tl = ctx.timeline
        if effective.instant in in_force_instants(tl, exclude_event=head.event_id):
            raise _same_instant()
        source = self._source(tl, effective.instant, exclude_event=head.event_id)
        if is_end and source[0] is None:
            raise error("CARETAKER_END_WITHOUT_CARETAKER",
                        "No caretaker is in force just before this instant, so an END cannot take effect there",
                        status.HTTP_409_CONFLICT)
        if target is not None and target != head.technician_id:
            # Only a NEW technician is gated; a time-only correction keeps the
            # event's existing technician unchecked.
            await self._check_new_caretaker(target, ctx.context, ctx.technicians)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CORRECTION, entry_operation=OP_CORRECTION, event_id=head.event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            technician_id=technician, effective_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_technician_id=source[0] or "",
            recorded_from_source=source[1], reason_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    async def _cancel(self, ctx: _Context, head: CaretakerPeriod, reason: str, *, request_id: str,
                      fingerprint: str, user_id: str) -> CaretakerOutcome:
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CANCELLATION, entry_operation=OP_CANCELLATION, event_id=head.event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            reason_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    # ---------------------------------------------------------------- reads

    async def caretakers(self, equipment_id: str) -> EquipmentCaretakers:
        """The derived timeline of one equipment in the request's scope.
        AMBIGUOUS_ORDER is returned explicitly (current UNDETERMINED, never
        "none"); INVALID is 500 EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID."""
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(equipment_id, context)
        tl = ctx.timeline
        if tl.current_technician_id is None:
            resolution = "UNDETERMINED" if tl.status == STATUS_AMBIGUOUS else "NONE"
            return EquipmentCaretakers(ctx.equipment_id, tl, None, resolution)
        # The current technician is a stored reference, already proven exactly
        # once in scope by `_read` (a defect is a 500, never UNRESOLVED).
        technicians = ctx.technicians or await read_technicians(self._repository)
        matches = [r for r in technicians.rows if text(r.values.get("technician_id")) == tl.current_technician_id
                   and same_scope(r, context, self._batch_id)]
        if len(matches) != 1:  # unreachable after the proof; fail closed, never guessed
            self._require_references({"TECHNICIAN_REFERENCE_SCOPE_UNPROVEN": 1})
        return EquipmentCaretakers(ctx.equipment_id, tl, technician_record(matches[0].values), "RESOLVED")

    async def technician_equipment(self, technician_id: str) -> TechnicianEquipment:
        """Reverse read: the equipment whose CURRENT caretaker is exactly this
        technician, in the request's scope. The requested technician is proven
        exactly once in scope (an id existing only out of scope is
        TECHNICIAN_SCOPE_UNPROVEN, never a TEST technician). Every equipment and
        technician id STORED in the in-scope history is same-scope proven
        before any id is returned (a defect is 500 DATA_INVALID, never an
        empty or partial list). Fails closed when any in-scope equipment
        timeline is not VALID (an ambiguous one is 409: its current caretaker
        cannot be excluded)."""
        context = require_write_context(self._context, self._batch_id)
        technicians = await read_technicians(self._repository)
        requested = classify_reference(technician_id, technicians, "technician_id", context, self._batch_id) \
            if technician_id.strip() else REFERENCE_MISSING
        if requested == REFERENCE_AMBIGUOUS:
            matches = [r for r in technicians.rows if text(r.values.get("technician_id")) == technician_id
                       and same_scope(r, context, self._batch_id)]
            raise error("TECHNICIAN_ID_AMBIGUOUS", "More than one technician record has this technician_id",
                        status.HTTP_409_CONFLICT, {"match_count": len(matches)})
        if requested == REFERENCE_SCOPE_UNPROVEN:
            raise _unprocessable("TECHNICIAN_SCOPE_UNPROVEN",
                                 "This technician cannot be proven to belong to the request's data scope")
        if requested == REFERENCE_MISSING:
            raise error("TECHNICIAN_NOT_FOUND", "No technician record has exactly this technician_id",
                        status.HTTP_404_NOT_FOUND)
        history = await self._history()
        # Every in-scope row of every equipment (unknown test flags fail closed).
        by_equipment = {eid: scoped_history_rows(history.rows, eid, context, self._batch_id)
                        for eid in sorted({text(r.get("equipment_id")) for r in history.rows})}
        by_equipment = {eid: rows for eid, rows in by_equipment.items() if rows}
        timelines = {eid: self._derive(rows) for eid, rows in by_equipment.items()}
        # Same-scope proof of every STORED reference before any id is returned:
        # one bounded equipment read for the distinct equipment ids, and the
        # technician read above for the distinct technician ids.
        issues: dict[str, int] = {}
        if by_equipment:
            equipment = await reference_read(
                self._repository.read_equipment_reference(), EQUIPMENT_PREFIX, EQUIPMENT_REFERENCE_TAB
            )
            issues.update(reference_issues(set(by_equipment), equipment, id_column="equipment_id",
                                           label="EQUIPMENT", context=context, batch_id=self._batch_id))
        all_rows = [r for rows in by_equipment.values() for r in rows]
        issues.update(reference_issues(history_technician_ids(all_rows), technicians, id_column="technician_id",
                                       label="TECHNICIAN", context=context, batch_id=self._batch_id))
        self._require_references(issues)
        items: list[TechnicianEquipmentItem] = []
        ambiguous = 0
        for equipment_id, tl in timelines.items():
            if tl.status != STATUS_VALID:
                ambiguous += 1
                continue
            if tl.current_technician_id == technician_id:
                current = next(e for e in tl.events if e.in_force and e.effective_at == tl.current_since)
                items.append(TechnicianEquipmentItem(equipment_id, tl.current_since, current.event_id))
        if ambiguous:
            raise error("CARETAKER_TIMELINE_AMBIGUOUS",
                        "Some equipment caretaker timelines are undetermined, so this list cannot be complete",
                        status.HTTP_409_CONFLICT, {"reason": "TIMELINE_AMBIGUOUS", "equipment_count": ambiguous})
        return TechnicianEquipment(technician_id, tuple(items))


__all__ = [
    "EQUIPMENT_PREFIX",
    "HISTORY_PREFIX",
    "OPERATIONS",
    "OP_EQUIPMENT_CARETAKER",
    "CaretakerOutcome",
    "EquipmentCaretakerService",
    "EquipmentCaretakers",
    "TechnicianEquipment",
    "TechnicianEquipmentItem",
    "classify_reference",
    "history_technician_ids",
    "reference_issues",
    "scoped_history_rows",
]
