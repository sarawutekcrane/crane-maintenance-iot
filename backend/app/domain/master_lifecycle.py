"""R2 Batch R2e — lifecycle writes for the organisation masters (personnel,
department): deactivate / reactivate / reconcile, plus the lifecycle-history read.

One engine, parametrised by an `EntitySpec` (see `personnel_lifecycle.py` and
`department_lifecycle.py`). Owner-approved decisions:

- Personnel lifecycle vocabulary ACTIVE / INACTIVE (write logic only: the
  R2c-1 read keeps `active_status` as raw text). Department keeps its frozen
  TRUE / FALSE. INACTIVE / FALSE never means deleted: no row is deleted, no id
  is reused, reactivation keeps the same id.
- Separate capabilities `can_manage_personnel` / `can_manage_department`.
- A reason is mandatory for every lifecycle action, both directions and
  reconciliation.

Deactivate != delete. A lifecycle write changes ONE cell of ONE master row and
appends ONE history row. It never touches any other tab: no user_account,
technician, driver, assignment, branch, department relationship, Part or
vehicle data (R2f owns relationships).

Durable audit: a SEPARATE append-only history per entity
(personnel_lifecycle_history / department_lifecycle_history). HISTORY-FIRST:
W1 appends the history row, W2 writes the lifecycle cell. A W2 failure leaves
the event recorded and the master unchanged (lifecycle consistency MISMATCH),
repaired only by an explicit reconciliation. Nothing is retried, compensated,
re-read or re-appended; history rows are never edited or deleted.

Order of every mutation (all coded refusals before W1):
1-3 capability, X-Request-Id, body (route + reason check) -> 4 data context ->
5 exact locate inside the context scope (test/real classification BEFORE
identity) -> 6 history read + validation -> 7 replay -> 8 current lifecycle
value valid -> 9 consistency gate -> 10 stale (expected == current) ->
11 no-op -> 12 W1 -> 13 W2. Stale is checked before no-op, so a stale client
never gets a successful no-op.

Context scope (TEST writes never change operational rows): REAL targets only
rows with is_test_data exactly FALSE; TEST targets only rows with is_test_data
exactly TRUE AND test_batch_id exactly the server-configured batch. A blank
or invalid flag on any content-bearing master row fails the whole request
closed (<MASTER>_DATA_INVALID / TEST_FLAG_INVALID). Rows whose identity /
display / state columns are all blank are not records (phantom rule) and are
never targeted. The history is scoped the same way.

Replay (review fix R2): an exact replay is successful ONLY when the entity is
not in lifecycle MISMATCH. When an earlier W1 exists but its W2 is incomplete
(an unknown-applied W1, or a known W2 failure), resending the same request
returns <ENTITY>_LIFECYCLE_MISMATCH — never replay success, never a W2 retry —
and recovery stays an explicit reconciliation. A request id reused with another
fingerprint is still REQUEST_ID_REUSED first. With no replay hit (e.g. an
unknown W1 that was NOT applied) the resend proceeds as a normal request.

Replay keys: `request_fingerprint` with entity-specific operation names, the entity
id in the frozen `vehicle_id` slot; lookup spans the entity's OWN history tab
only. A request id is therefore unique per history tab: the same UUID may
independently appear once in each of the two tabs (no cross-tab detection is
claimed).
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeVar

from fastapi import status

from app.domain.registration import (
    DATA_CONTEXT_REAL,
    DATA_CONTEXT_TEST,
    parse_aware,
    text,
)
from app.domain.registry_write_support import error, require_write_context
from app.domain.request_replay import find_replay, request_fingerprint
from app.errors import ApiError
from app.repositories.base import (
    LifecycleMasterRead,
    RegistryTableRead,
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositorySchemaError,
    RepositoryWriteError,
)

T = TypeVar("T")

MAX_REASON_LENGTH = 500

EVENT_DEACTIVATE = "DEACTIVATE"
EVENT_REACTIVATE = "REACTIVATE"
EVENT_RECONCILIATION = "RECONCILIATION"
EVENT_KINDS = (EVENT_DEACTIVATE, EVENT_REACTIVATE, EVENT_RECONCILIATION)

CONSISTENCY_NO_HISTORY = "NO_HISTORY"
CONSISTENCY_CONSISTENT = "CONSISTENT"
CONSISTENCY_MISMATCH = "MISMATCH"

TEST_FLAG = "TRUE"
OPERATIONAL_FLAG = "FALSE"
_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class EntitySpec:
    entity: str  # PERSONNEL / DEPARTMENT (repository key)
    label: str  # PERSONNEL / DEPARTMENT (error-code prefix)
    id_column: str
    state_column: str
    record_columns: tuple[str, ...]  # a row with all of these blank is a phantom row
    active_value: str
    inactive_value: str
    expected_field: str  # request body field of the expected current state
    expected_to_state: Callable[[object], str]
    master_tab: str
    master_prefix: str  # PERSONNEL_MASTER / DEPARTMENT_MASTER
    history_tab: str
    history_columns: tuple[str, ...]
    record_id_prefix: str
    op_deactivate: str
    op_reactivate: str
    op_reconcile: str

    @property
    def states(self) -> tuple[str, str]:
        return (self.active_value, self.inactive_value)

    @property
    def lifecycle_prefix(self) -> str:
        return f"{self.label}_LIFECYCLE"


@dataclass(frozen=True)
class LifecycleEvent:
    lifecycle_event_id: str
    event_kind: str
    previous_state: str
    new_state: str
    recorded_at: str
    recorded_by: str
    reason_th: str
    request_id: str


@dataclass(frozen=True)
class LifecycleOutcome:
    request_id: str
    changed: bool = False
    replayed: bool = False
    record_id: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    lifecycle_consistency_after: str | None = None
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleHistoryRead:
    entity_id: str
    current_state: str | None  # raw source text; None when blank
    latest_history_state: str | None
    lifecycle_consistency: str
    events: tuple[LifecycleEvent, ...]


@dataclass(frozen=True)
class _Context:
    context: str
    entity_id: str
    master: LifecycleMasterRead
    row_number: int
    current: str  # exact source text of the lifecycle cell
    history: RegistryTableRead
    events: tuple[LifecycleEvent, ...]
    rows: tuple[Mapping[str, object], ...]  # this entity's in-scope history rows, physical order

    @property
    def latest(self) -> LifecycleEvent | None:
        return self.events[-1] if self.events else None

    @property
    def consistency(self) -> str:
        if self.latest is None:
            return CONSISTENCY_NO_HISTORY
        return CONSISTENCY_CONSISTENT if self.latest.new_state == self.current else CONSISTENCY_MISMATCH


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def in_scope(row: Mapping[str, object], context: str, batch_id: str) -> bool:
    """REAL: exact FALSE only. TEST: exact TRUE with exactly the server batch."""
    flag = text(row.get("is_test_data"))
    if context == DATA_CONTEXT_REAL:
        return flag == OPERATIONAL_FLAG
    return flag == TEST_FLAG and text(row.get("test_batch_id")) == batch_id


def is_record(row: Mapping[str, object], spec: EntitySpec) -> bool:
    return any(text(row.get(c)).strip() for c in spec.record_columns)


def history_issues(rows: Sequence[Mapping[str, object]], spec: EntitySpec) -> dict[str, int]:
    """Issue counts for ONE entity's in-scope history rows, in physical
    (history) order (empty = valid).

    Audit-reference integrity (review fix R1) for a RECONCILIATION:
    `related_request_id` must name the request id of a PRIOR event of this same
    scoped entity history (never itself, a later row or a missing request:
    RELATED_REQUEST_DANGLING), that event's `new_state` must equal the
    reconciliation's `new_state` (RELATED_STATE_MISMATCH), and a reconciliation
    must repair a real difference (`previous_state` == `new_state` is
    TRANSITION_INVALID). The referenced event need not be the immediately
    preceding row: Sheets appends are not transactional, so a concurrent
    append may land between the service's read and its W1."""
    issues: dict[str, int] = {}

    def count(code: str) -> None:
        issues[code] = issues.get(code, 0) + 1

    # DEACTIVATE / REACTIVATE have one fixed transition; RECONCILIATION may record any known pair.
    transitions = {
        EVENT_DEACTIVATE: (spec.active_value, spec.inactive_value),
        EVENT_REACTIVATE: (spec.inactive_value, spec.active_value),
    }
    request_ids: list[str] = []
    prior_states: dict[str, str] = {}  # request_id -> new_state of the events BEFORE the current row
    for row in rows:
        kind = text(row.get("event_kind"))
        previous, new = text(row.get("previous_state")), text(row.get("new_state"))
        if kind not in EVENT_KINDS:
            count("EVENT_KIND_INVALID")
        # A reconciliation must repair a real difference; the other kinds have one fixed transition.
        valid_transition = previous != new if kind == EVENT_RECONCILIATION else transitions.get(kind) in (
            None, (previous, new))
        if previous not in spec.states or new not in spec.states:
            count("STATE_INVALID")
        elif not valid_transition:
            count("TRANSITION_INVALID")
        if parse_aware(row.get("recorded_at")) is None:
            count("RECORDED_AT_INVALID")
        for name in ("lifecycle_event_id", "recorded_by", "request_id", "reason_th"):
            if not text(row.get(name)).strip():
                count(f"FIELD_REQUIRED:{name}")
        if not _HEX64.fullmatch(text(row.get("request_fingerprint"))):
            count("FINGERPRINT_INVALID")
        related = text(row.get("related_request_id")).strip()
        if kind == EVENT_RECONCILIATION and not related:
            count("FIELD_REQUIRED:related_request_id")
        elif kind == EVENT_RECONCILIATION and related not in prior_states:
            count("RELATED_REQUEST_DANGLING")
        elif kind == EVENT_RECONCILIATION and prior_states[related] != new:
            count("RELATED_STATE_MISMATCH")
        if kind in (EVENT_DEACTIVATE, EVENT_REACTIVATE) and related:
            count("FIELD_MUST_BE_BLANK:related_request_id")
        if text(row.get("request_id")):
            request_ids.append(text(row.get("request_id")))
            prior_states.setdefault(text(row.get("request_id")), new)
    if len(request_ids) != len(set(request_ids)):
        count("REQUEST_ID_DUPLICATE")
    return issues


def _event(row: Mapping[str, object]) -> LifecycleEvent:
    return LifecycleEvent(
        lifecycle_event_id=text(row.get("lifecycle_event_id")),
        event_kind=text(row.get("event_kind")),
        previous_state=text(row.get("previous_state")),
        new_state=text(row.get("new_state")),
        recorded_at=text(row.get("recorded_at")),
        recorded_by=text(row.get("recorded_by")),
        reason_th=text(row.get("reason_th")),
        request_id=text(row.get("request_id")),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LifecycleService:
    def __init__(self, spec: EntitySpec, repository: Repository, data_context: str | None, test_batch_id: str) -> None:
        self._spec = spec
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id

    # ---------------------------------------------------------------- errors

    def _err(self, suffix: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
        return error(f"{self._spec.lifecycle_prefix}_{suffix}", message, http_status, details)

    async def _tab(self, call: Awaitable[T], prefix: str, tab: str) -> T:
        try:
            return await call
        except RepositoryFeatureNotImplementedError:
            raise
        except RepositorySchemaError as exc:
            raise error(f"{prefix}_SCHEMA_INVALID", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR,
                        {"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)}) from exc
        except RepositoryError as exc:
            raise error(f"{prefix}_READ_FAILED", f"{tab} could not be read", status.HTTP_503_SERVICE_UNAVAILABLE,
                        {"tab": tab}) from exc

    @staticmethod
    def _data_invalid(prefix: str, tab: str, issues: dict[str, int]) -> ApiError:
        return error(f"{prefix}_DATA_INVALID", f"{tab} contains records that cannot be used exactly",
                     status.HTTP_500_INTERNAL_SERVER_ERROR, {"tab": tab, "issues": dict(sorted(issues.items()))})

    # --------------------------------------------------------------- steps

    @staticmethod
    def require_reason(body: Mapping[str, object]) -> str:
        reason = body.get("reason_th")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
            raise error("REASON_REQUIRED", f"A reason of 1-{MAX_REASON_LENGTH} characters is required",
                        status.HTTP_422_UNPROCESSABLE_ENTITY)
        return reason

    async def _locate(self, entity_id: str, context: str) -> tuple[LifecycleMasterRead, int, Mapping[str, object]]:
        spec = self._spec
        master = await self._tab(self._repository.read_lifecycle_master(spec.entity), spec.master_prefix, spec.master_tab)
        records = [(n, r) for n, r in zip(master.row_numbers, master.rows) if is_record(r, spec)]
        invalid = sum(1 for _, r in records if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
        if invalid:  # classification first: unknown scope fails the whole source closed
            raise self._data_invalid(spec.master_prefix, spec.master_tab, {"TEST_FLAG_INVALID": invalid})
        matches = [
            (n, r) for n, r in records
            if in_scope(r, context, self._batch_id) and entity_id.strip() and text(r.get(spec.id_column)) == entity_id
        ]
        if not matches:
            raise error(f"{spec.label}_NOT_FOUND", f"No {spec.label.lower()} record has exactly this id",
                        status.HTTP_404_NOT_FOUND)
        if len(matches) > 1:
            raise error(f"{spec.label}_ID_AMBIGUOUS", f"More than one {spec.label.lower()} record has this id",
                        status.HTTP_409_CONFLICT, {"match_count": len(matches)})
        row_number, row = matches[0]
        return master, row_number, row

    async def _history(
        self, entity_id: str, context: str
    ) -> tuple[RegistryTableRead, tuple[LifecycleEvent, ...], tuple[Mapping[str, object], ...]]:
        spec = self._spec
        prefix = f"{spec.lifecycle_prefix}_HISTORY"
        history = await self._tab(self._repository.read_lifecycle_history_validated(spec.entity), prefix,
                                  spec.history_tab)
        ids = [text(r.get("lifecycle_event_id")) for r in history.rows if text(r.get("lifecycle_event_id"))]
        if len(ids) != len(set(ids)):
            raise self._data_invalid(prefix, spec.history_tab, {"EVENT_ID_DUPLICATE": len(ids) - len(set(ids))})
        own = [r for r in history.rows if text(r.get(spec.id_column)) == entity_id]
        invalid = sum(1 for r in own if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
        if invalid:
            raise self._data_invalid(prefix, spec.history_tab, {"TEST_FLAG_INVALID": invalid})
        scoped = [r for r in own if in_scope(r, context, self._batch_id)]
        issues = history_issues(scoped, spec)
        if issues:
            raise self._data_invalid(prefix, spec.history_tab, issues)
        return history, tuple(_event(r) for r in scoped), tuple(scoped)

    async def _read(self, entity_id: str) -> _Context:
        context = require_write_context(self._context, self._batch_id)
        master, row_number, row = await self._locate(entity_id, context)
        history, events, rows = await self._history(entity_id, context)
        return _Context(
            context, entity_id, master, row_number, text(row.get(self._spec.state_column)), history, events, rows
        )

    def _replay(self, ctx: _Context, request_id: str, fingerprint: str) -> LifecycleOutcome | None:
        hit = find_replay(ctx.history.rows, request_id, fingerprint, record_id_column="lifecycle_event_id")
        if hit is None:
            return None
        if not hit.replayed:
            raise error("REQUEST_ID_REUSED", "This request id was already used for a different change; nothing was changed",
                        status.HTTP_409_CONFLICT, {"request_id": request_id})
        if ctx.consistency == CONSISTENCY_MISMATCH:
            # Review fix R2: the earlier event exists (an unknown-applied or known-failed
            # W2 left the record unchanged), so this exact replay is NOT a success.
            # Nothing is written and W2 is never retried: recovery is an explicit
            # reconciliation (a new, user-confirmed request with a reason).
            raise self._mismatch()
        return LifecycleOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids)

    def _mismatch(self) -> ApiError:
        return self._err("MISMATCH", "The record's state differs from its latest lifecycle history; reconcile it first",
                         status.HTTP_409_CONFLICT)

    def _check_current(self, ctx: _Context) -> None:
        if ctx.current not in self._spec.states:
            raise self._err("STATE_INVALID", "The current lifecycle state is not a known value; nothing was changed",
                            status.HTTP_422_UNPROCESSABLE_ENTITY, {"field": self._spec.state_column})

    def _check_stale(self, ctx: _Context, body: Mapping[str, object]) -> None:
        expected = self._spec.expected_to_state(body.get(self._spec.expected_field))
        if expected != ctx.current:
            raise self._err("STALE", "The record changed since it was loaded; reload and try again",
                            status.HTTP_409_CONFLICT, {"field": self._spec.state_column})

    def _row(self, ctx: _Context, *, kind: str, new_state: str, request_id: str, fingerprint: str, user_id: str,
             reason: str, related: str = "") -> dict[str, str]:
        test = ctx.context == DATA_CONTEXT_TEST
        return {
            "lifecycle_event_id": f"{self._spec.record_id_prefix}-{uuid.uuid4().hex}",
            self._spec.id_column: ctx.entity_id,
            "event_kind": kind,
            "previous_state": ctx.current,
            "new_state": new_state,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "recorded_by": user_id,
            "request_id": request_id,
            "request_fingerprint": fingerprint,
            "reason_th": reason,
            "is_test_data": TEST_FLAG if test else OPERATIONAL_FLAG,
            "test_batch_id": self._batch_id if test else "",
            "related_request_id": related,
        }

    async def _commit(self, ctx: _Context, row: dict[str, str], *, request_id: str) -> LifecycleOutcome:
        if history_issues([*ctx.rows, row], self._spec):  # a programming error, before any write
            raise RuntimeError("generated lifecycle history row is invalid")
        try:
            await self._repository.append_lifecycle_history(self._spec.entity, ctx.history, row)
        except RepositoryWriteError as exc:
            raise self._err(
                "HISTORY_WRITE_FAILED",
                "The lifecycle history write was rejected; nothing was changed" if exc.outcome == "rejected"
                else "The lifecycle history write outcome is unknown (it may have been written); nothing was retried",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {"history_write_outcome": exc.outcome, "request_id": request_id},
            ) from exc
        try:
            await self._repository.write_lifecycle_state_cell(
                self._spec.entity, ctx.master, ctx.row_number, row["new_state"]
            )
        except RepositoryWriteError as exc:
            raise self._err(
                "STATE_WRITE_FAILED",
                "The lifecycle event was recorded in the history, but the record's state "
                + ("was rejected" if exc.outcome == "rejected" else "has an unknown outcome")
                + "; nothing was retried. Reconcile the record's state to finish it.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {"event_recorded": True, "record_id": row["lifecycle_event_id"], "request_id": request_id},
            ) from exc
        return LifecycleOutcome(
            request_id=request_id, changed=True, record_id=row["lifecycle_event_id"],
            previous_state=row["previous_state"], new_state=row["new_state"],
            lifecycle_consistency_after=CONSISTENCY_CONSISTENT,
        )

    # ----------------------------------------------------------- operations

    async def deactivate(self, entity_id: str, body: Mapping[str, object], *, request_id: str, user_id: str) -> LifecycleOutcome:
        return await self._transition(entity_id, body, request_id=request_id, user_id=user_id,
                                      kind=EVENT_DEACTIVATE, target=self._spec.inactive_value, op=self._spec.op_deactivate)

    async def reactivate(self, entity_id: str, body: Mapping[str, object], *, request_id: str, user_id: str) -> LifecycleOutcome:
        return await self._transition(entity_id, body, request_id=request_id, user_id=user_id,
                                      kind=EVENT_REACTIVATE, target=self._spec.active_value, op=self._spec.op_reactivate)

    async def _transition(self, entity_id: str, body: Mapping[str, object], *, request_id: str, user_id: str,
                          kind: str, target: str, op: str) -> LifecycleOutcome:
        reason = self.require_reason(body)
        ctx = await self._read(entity_id)
        fingerprint = request_fingerprint(op, ctx.entity_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        self._check_current(ctx)
        if ctx.consistency == CONSISTENCY_MISMATCH:
            raise self._mismatch()
        self._check_stale(ctx, body)
        if ctx.current == target:
            return LifecycleOutcome(request_id=request_id, changed=False)
        row = self._row(ctx, kind=kind, new_state=target, request_id=request_id, fingerprint=fingerprint,
                        user_id=user_id, reason=reason)
        return await self._commit(ctx, row, request_id=request_id)

    async def reconcile(self, entity_id: str, body: Mapping[str, object], *, request_id: str, user_id: str) -> LifecycleOutcome:
        """Writes the master state from the latest lifecycle history event.
        The target is never taken from the client."""
        reason = self.require_reason(body)
        ctx = await self._read(entity_id)
        fingerprint = request_fingerprint(self._spec.op_reconcile, ctx.entity_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        self._check_current(ctx)
        self._check_stale(ctx, body)
        latest = ctx.latest
        if latest is None or ctx.consistency != CONSISTENCY_MISMATCH:
            return LifecycleOutcome(request_id=request_id, changed=False)
        row = self._row(ctx, kind=EVENT_RECONCILIATION, new_state=latest.new_state, request_id=request_id,
                        fingerprint=fingerprint, user_id=user_id, reason=reason, related=latest.request_id)
        return await self._commit(ctx, row, request_id=request_id)

    async def history(self, entity_id: str) -> LifecycleHistoryRead:
        ctx = await self._read(entity_id)
        current = ctx.current if ctx.current.strip() else None
        return LifecycleHistoryRead(
            entity_id=ctx.entity_id,
            current_state=current,
            latest_history_state=ctx.latest.new_state if ctx.latest else None,
            lifecycle_consistency=ctx.consistency,
            events=ctx.events,
        )
