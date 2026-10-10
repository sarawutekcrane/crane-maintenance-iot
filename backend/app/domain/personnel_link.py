"""R2 Batch R2f-b — Personnel relationship-link writes (one engine, explicit specs).

Final Contract C1 §5 / §15 / §17 / §19. The engine is parametrised by a
`LinkSpec`; R2f-b registers ONLY the Personnel ↔ Technician spec
(`personnel_technician_link.py`). No account or driver spec, route or
repository key exists.

Authority: the CURRENT link is the `personnel_master` link cell (e.g.
`technician_id`). The append-only link-history tab is the durable audit of
changes; it is never a second current authority. Existing links with no
history are valid baseline state (consistency NO_HISTORY).

Operations (all need a reason; recorded time only, no effective-date
backdating): LINK (blank -> target), RELINK (nonblank -> different target),
UNLINK (nonblank -> blank). LINK never silently becomes RELINK or the reverse.
RECONCILIATION is recovery only: it runs only in MISMATCH, names a PRIOR
in-scope event of the same personnel, and restores the latest history target;
the client cannot choose the target.

Order of every mutation (all coded refusals before W1):
1-3 capability, X-Request-Id, body (route) -> reason + operation shape ->
4 data context -> 5 exact personnel locate inside the scope (test/real
classification BEFORE identity) -> 6 history read + validation -> 7 replay ->
8 consistency gate -> 9 target validation (exact, same scope, not held by
another in-scope personnel) -> 10 stale (expected == current) -> 11 operation
rule (LINK needs blank current, RELINK nonblank) -> 12 no-op -> 13 W1 history
-> 14 W2 the ONE link cell. Stale precedes no-op; a broken target is never
hidden behind a no-op.

Identity-link maintenance has NO lifecycle gate (OD-5 applies to new work
assignments, not here) and NO cascade: it never changes active_status,
accounts, drivers, departments, branches or any assignment.

Failures: a rejected W1 -> nothing written; an unknown W1 -> no W2, no retry
(history_write_outcome reported); a failed W2 after W1 -> the event stays,
the link enters MISMATCH, explicit reconciliation required. Nothing is
retried or compensated. An exact replay is a success only when the link is
not in MISMATCH; a reused request id with another fingerprint is
REQUEST_ID_REUSED.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeVar

from fastapi import status

from app.domain.master_lifecycle import MAX_REASON_LENGTH, in_scope
from app.domain.personnel_relationship import same_scope  # the ONE R2f-a reference-scope rule
from app.domain.registration import DATA_CONTEXT_TEST, parse_aware, text
from app.domain.registry_write_support import error, require_write_context
from app.domain.request_replay import find_replay, request_fingerprint
from app.errors import ApiError
from app.repositories.base import (
    LifecycleMasterRead,
    ReferenceMasterRead,
    RegistryTableRead,
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositorySchemaError,
    RepositoryWriteError,
)

T = TypeVar("T")

OP_LINK = "LINK"
OP_UNLINK = "UNLINK"
OP_RELINK = "RELINK"
OPERATIONS = (OP_LINK, OP_UNLINK, OP_RELINK)
EVENT_RECONCILIATION = "RECONCILIATION"
EVENT_KINDS = (*OPERATIONS, EVENT_RECONCILIATION)

CONSISTENCY_NO_HISTORY = "NO_HISTORY"
CONSISTENCY_CONSISTENT = "CONSISTENT"
CONSISTENCY_MISMATCH = "MISMATCH"

TEST_FLAG = "TRUE"
OPERATIONAL_FLAG = "FALSE"
_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class LinkSpec:
    link: str  # repository key, e.g. TECHNICIAN
    label: str  # error-code prefix, e.g. PERSONNEL_TECHNICIAN_LINK
    link_column: str  # personnel_master link cell, e.g. technician_id
    previous_column: str  # history: previous_<x>
    new_column: str  # history: new_<x>
    record_columns: tuple[str, ...]  # a personnel row with all of these blank is a phantom row
    history_tab: str
    history_columns: tuple[str, ...]
    record_id_prefix: str
    target_label: str  # TECHNICIAN (target error-code prefix)
    target_id_column: str
    read_targets: Callable[[Repository], Awaitable[ReferenceMasterRead]]
    op_link: str
    op_unlink: str
    op_relink: str
    op_reconcile: str

    def op_name(self, operation: str) -> str:
        return {OP_LINK: self.op_link, OP_UNLINK: self.op_unlink, OP_RELINK: self.op_relink}[operation]


@dataclass(frozen=True)
class LinkEvent:
    link_event_id: str
    event_kind: str
    previous_id: str
    new_id: str
    recorded_at: str
    recorded_by: str
    reason_th: str
    request_id: str


@dataclass(frozen=True)
class LinkOutcome:
    request_id: str
    changed: bool = False
    replayed: bool = False
    record_id: str | None = None
    previous_id: str | None = None
    new_id: str | None = None
    consistency_after: str | None = None
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinkHistoryRead:
    personnel_id: str
    current_id: str | None
    latest_history_id: str | None
    consistency: str
    events: tuple[LinkEvent, ...]


def link_value(value: object) -> str:
    """A link cell's exact text; whitespace-only is blank (never a link)."""
    raw = text(value)
    return raw if raw.strip() else ""


def _nullable(value: str) -> str | None:
    return value or None


@dataclass(frozen=True)
class _Context:
    context: str
    personnel_id: str
    master: LifecycleMasterRead
    row_number: int
    current: str  # link_value of the personnel link cell
    people: tuple[Mapping[str, object], ...]  # in-scope personnel records
    history: RegistryTableRead
    events: tuple[LinkEvent, ...]
    rows: tuple[Mapping[str, object], ...]  # this personnel's in-scope history rows, physical order

    @property
    def latest(self) -> LinkEvent | None:
        return self.events[-1] if self.events else None

    @property
    def consistency(self) -> str:
        if self.latest is None:
            return CONSISTENCY_NO_HISTORY
        return CONSISTENCY_CONSISTENT if self.latest.new_id == self.current else CONSISTENCY_MISMATCH


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def valid_shape(kind: str, previous: str, new: str) -> bool:
    if kind == OP_LINK:
        return not previous and bool(new)
    if kind == OP_UNLINK:
        return bool(previous) and not new
    if kind == OP_RELINK:
        return bool(previous) and bool(new) and previous != new
    return previous != new  # RECONCILIATION must repair a real difference


def history_issues(rows: Sequence[Mapping[str, object]], spec: LinkSpec) -> dict[str, int]:
    """Issue counts for ONE personnel's in-scope link-history rows, in
    physical order (empty = valid). A RECONCILIATION's `related_request_id`
    must name the request id of a PRIOR event of this same scoped history
    whose new value equals the reconciliation's new value."""
    issues: dict[str, int] = {}

    def count(code: str) -> None:
        issues[code] = issues.get(code, 0) + 1

    request_ids: list[str] = []
    prior: dict[str, str] = {}  # request_id -> new value of the events BEFORE the current row
    for row in rows:
        kind = text(row.get("event_kind"))
        previous, new = link_value(row.get(spec.previous_column)), link_value(row.get(spec.new_column))
        if kind not in EVENT_KINDS:
            count("EVENT_KIND_INVALID")
        elif not valid_shape(kind, previous, new):
            count("RECONCILIATION_SAME_STATE" if kind == EVENT_RECONCILIATION else "EVENT_SHAPE_INVALID")
        if parse_aware(row.get("recorded_at")) is None:
            count("RECORDED_AT_INVALID")
        for name in ("link_event_id", "personnel_id", "recorded_by", "request_id", "reason_th"):
            if not text(row.get(name)).strip():
                count(f"FIELD_REQUIRED:{name}")
        if not _HEX64.fullmatch(text(row.get("request_fingerprint"))):
            count("FINGERPRINT_INVALID")
        if text(row.get("is_test_data")) == OPERATIONAL_FLAG and text(row.get("test_batch_id")).strip():
            count("SCOPE_INCONSISTENT")
        related = text(row.get("related_request_id")).strip()
        if kind == EVENT_RECONCILIATION and not related:
            count("FIELD_REQUIRED:related_request_id")
        elif kind == EVENT_RECONCILIATION and related not in prior:
            count("RELATED_REQUEST_DANGLING")
        elif kind == EVENT_RECONCILIATION and prior[related] != new:
            count("RELATED_STATE_MISMATCH")
        if kind in OPERATIONS and related:
            count("FIELD_MUST_BE_BLANK:related_request_id")
        if text(row.get("request_id")):
            request_ids.append(text(row.get("request_id")))
            prior.setdefault(text(row.get("request_id")), new)
    if len(request_ids) != len(set(request_ids)):
        count("REQUEST_ID_DUPLICATE")
    return issues


def _event(row: Mapping[str, object], spec: LinkSpec) -> LinkEvent:
    return LinkEvent(
        link_event_id=text(row.get("link_event_id")),
        event_kind=text(row.get("event_kind")),
        previous_id=link_value(row.get(spec.previous_column)),
        new_id=link_value(row.get(spec.new_column)),
        recorded_at=text(row.get("recorded_at")),
        recorded_by=text(row.get("recorded_by")),
        reason_th=text(row.get("reason_th")),
        request_id=text(row.get("request_id")),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PersonnelLinkService:
    def __init__(self, spec: LinkSpec, repository: Repository, data_context: str | None, test_batch_id: str) -> None:
        self._spec = spec
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id

    # ---------------------------------------------------------------- errors

    def _err(self, suffix: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
        return error(f"{self._spec.label}_{suffix}", message, http_status, details)

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

    def _mismatch(self) -> ApiError:
        return self._err("MISMATCH", "The current link differs from its latest link history; reconcile it first",
                         status.HTTP_409_CONFLICT)

    # --------------------------------------------------------------- body

    @staticmethod
    def require_reason(body: Mapping[str, object]) -> str:
        reason = body.get("reason_th")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
            raise error("REASON_REQUIRED", f"A reason of 1-{MAX_REASON_LENGTH} characters is required",
                        status.HTTP_422_UNPROCESSABLE_ENTITY)
        return reason

    def _target_from_body(self, operation: str, body: Mapping[str, object]) -> str:
        target = link_value(body.get(self._spec.new_column))
        if operation == OP_UNLINK:
            if target:
                raise self._err("TARGET_NOT_ALLOWED", f"UNLINK takes no {self._spec.new_column}",
                                status.HTTP_422_UNPROCESSABLE_ENTITY, {"field": self._spec.new_column})
            return ""
        if not target:
            raise self._err("TARGET_REQUIRED", f"{operation} requires {self._spec.new_column}",
                            status.HTTP_422_UNPROCESSABLE_ENTITY, {"field": self._spec.new_column})
        return target

    # --------------------------------------------------------------- reads

    async def _locate(self, personnel_id: str, context: str):
        spec = self._spec
        master = await self._tab(self._repository.read_personnel_link_master(spec.link), "PERSONNEL_MASTER",
                                 "personnel_master")
        records = [(n, r) for n, r in zip(master.row_numbers, master.rows)
                   if any(text(r.get(c)).strip() for c in spec.record_columns)]
        invalid = sum(1 for _, r in records if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
        if invalid:  # classification first: unknown scope fails the whole source closed
            raise self._data_invalid("PERSONNEL_MASTER", "personnel_master", {"TEST_FLAG_INVALID": invalid})
        people = [(n, r) for n, r in records if in_scope(r, context, self._batch_id)]
        matches = [(n, r) for n, r in people if personnel_id.strip() and text(r.get("personnel_id")) == personnel_id]
        if not matches:
            raise error("PERSONNEL_NOT_FOUND", "No personnel record has exactly this id", status.HTTP_404_NOT_FOUND)
        if len(matches) > 1:
            raise error("PERSONNEL_ID_AMBIGUOUS", "More than one personnel record has this id",
                        status.HTTP_409_CONFLICT, {"match_count": len(matches)})
        row_number, row = matches[0]
        return master, row_number, row, tuple(r for _, r in people)

    async def _history(self, personnel_id: str, context: str):
        spec = self._spec
        prefix = f"{spec.label}_HISTORY"
        history = await self._tab(self._repository.read_personnel_link_history_validated(spec.link), prefix,
                                  spec.history_tab)
        ids = [text(r.get("link_event_id")) for r in history.rows if text(r.get("link_event_id"))]
        if len(ids) != len(set(ids)):
            raise self._data_invalid(prefix, spec.history_tab, {"EVENT_ID_DUPLICATE": len(ids) - len(set(ids))})
        own = [r for r in history.rows if text(r.get("personnel_id")) == personnel_id]
        invalid = sum(1 for r in own if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
        if invalid:
            raise self._data_invalid(prefix, spec.history_tab, {"TEST_FLAG_INVALID": invalid})
        scoped = [r for r in own if in_scope(r, context, self._batch_id)]
        issues = history_issues(scoped, spec)
        if issues:
            raise self._data_invalid(prefix, spec.history_tab, issues)
        return history, tuple(_event(r, spec) for r in scoped), tuple(scoped)

    async def _read(self, personnel_id: str) -> _Context:
        context = require_write_context(self._context, self._batch_id)
        master, row_number, row, people = await self._locate(personnel_id, context)
        history, events, rows = await self._history(personnel_id, context)
        return _Context(context, personnel_id, master, row_number, link_value(row.get(self._spec.link_column)),
                        people, history, events, rows)

    # --------------------------------------------------------------- guards

    def _replay(self, ctx: _Context, request_id: str, fingerprint: str) -> LinkOutcome | None:
        hit = find_replay(ctx.history.rows, request_id, fingerprint, record_id_column="link_event_id")
        if hit is None:
            return None
        if not hit.replayed:
            raise error("REQUEST_ID_REUSED", "This request id was already used for a different change; nothing was changed",
                        status.HTTP_409_CONFLICT, {"request_id": request_id})
        if ctx.consistency == CONSISTENCY_MISMATCH:
            # The earlier event exists but its projection did not complete: never a replay success,
            # never a W2 retry. Recovery is an explicit reconciliation.
            raise self._mismatch()
        return LinkOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids)

    async def _check_target(self, ctx: _Context, target: str) -> None:
        """Exact id, exactly once, in the request's scope, and not held by
        another in-scope personnel. Never selects the first duplicate."""
        spec = self._spec
        targets = await self._tab(spec.read_targets(self._repository), f"{spec.target_label}_MASTER",
                                  f"{spec.target_label.lower()}_master")
        exact = [r for r in targets.rows if text(r.values.get(spec.target_id_column)) == target]
        matches = [r for r in exact if same_scope(r, ctx.context, self._batch_id)]
        label = spec.target_label
        if len(matches) > 1:
            raise error(f"{label}_ID_AMBIGUOUS", f"More than one {label.lower()} record has this id",
                        status.HTTP_409_CONFLICT, {"match_count": len(matches)})
        if not matches:
            if ctx.context == DATA_CONTEXT_TEST and (not targets.test_scope_supported or exact):
                raise error(f"{label}_SCOPE_UNPROVEN",
                            f"The {label.lower()} cannot be proven to belong to this TEST scope; nothing was changed",
                            status.HTTP_422_UNPROCESSABLE_ENTITY)
            raise error(f"{label}_NOT_FOUND", f"No {label.lower()} record has exactly this id in scope",
                        status.HTTP_422_UNPROCESSABLE_ENTITY)
        holders = [p for p in ctx.people
                   if link_value(p.get(spec.link_column)) == target and text(p.get("personnel_id")) != ctx.personnel_id]
        if holders:
            raise error(f"{label}_ALREADY_LINKED",
                        f"This {label.lower()} is already linked to another personnel record; unlink it there first",
                        status.HTTP_409_CONFLICT, {spec.target_id_column: target})

    def _check_stale(self, ctx: _Context, body: Mapping[str, object]) -> None:
        if link_value(body.get(f"expected_{self._spec.link_column}")) != ctx.current:
            raise self._err("STALE", "The link changed since it was loaded; reload and try again",
                            status.HTTP_409_CONFLICT, {"field": self._spec.link_column})

    # --------------------------------------------------------------- writes

    def _row(self, ctx: _Context, *, kind: str, new: str, request_id: str, fingerprint: str, user_id: str,
             reason: str, related: str = "") -> dict[str, str]:
        test = ctx.context == DATA_CONTEXT_TEST
        return {
            "link_event_id": f"{self._spec.record_id_prefix}-{uuid.uuid4().hex}",
            "personnel_id": ctx.personnel_id,
            "event_kind": kind,
            self._spec.previous_column: ctx.current,
            self._spec.new_column: new,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "recorded_by": user_id,
            "request_id": request_id,
            "request_fingerprint": fingerprint,
            "reason_th": reason,
            "is_test_data": TEST_FLAG if test else OPERATIONAL_FLAG,
            "test_batch_id": self._batch_id if test else "",
            "related_request_id": related,
        }

    async def _commit(self, ctx: _Context, row: dict[str, str], *, request_id: str) -> LinkOutcome:
        if history_issues([*ctx.rows, row], self._spec):  # a programming error, before any write
            raise RuntimeError("generated link history row is invalid")
        try:
            await self._repository.append_personnel_link_history(self._spec.link, ctx.history, row)
        except RepositoryWriteError as exc:
            raise self._err(
                "HISTORY_WRITE_FAILED",
                "The link history write was rejected; nothing was changed" if exc.outcome == "rejected"
                else "The link history write outcome is unknown (it may have been written); nothing was retried",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {"history_write_outcome": exc.outcome, "request_id": request_id},
            ) from exc
        try:
            await self._repository.write_personnel_link_cell(
                self._spec.link, ctx.master, ctx.row_number, row[self._spec.new_column]
            )
        except RepositoryWriteError as exc:
            raise self._err(
                "PROJECTION_WRITE_FAILED",
                "The link event was recorded in the history, but the personnel link "
                + ("was rejected" if exc.outcome == "rejected" else "has an unknown outcome")
                + "; nothing was retried. Reconcile the link to finish it.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {"event_recorded": True, "record_id": row["link_event_id"], "request_id": request_id,
                 "projection_write_outcome": exc.outcome},
            ) from exc
        return LinkOutcome(
            request_id=request_id, changed=True, record_id=row["link_event_id"],
            previous_id=row[self._spec.previous_column], new_id=row[self._spec.new_column],
            consistency_after=CONSISTENCY_CONSISTENT,
        )

    # ----------------------------------------------------------- operations

    async def change(self, personnel_id: str, body: Mapping[str, object], *, request_id: str,
                     user_id: str) -> LinkOutcome:
        """LINK / UNLINK / RELINK of the personnel's link."""
        operation = text(body.get("operation"))
        reason = self.require_reason(body)
        target = self._target_from_body(operation, body)
        ctx = await self._read(personnel_id)
        fingerprint = request_fingerprint(self._spec.op_name(operation), ctx.personnel_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        if ctx.consistency == CONSISTENCY_MISMATCH:
            raise self._mismatch()
        if target:
            await self._check_target(ctx, target)
        self._check_stale(ctx, body)
        if operation == OP_LINK and ctx.current and ctx.current != target:
            raise self._err("RELINK_REQUIRED", "The personnel is already linked; use RELINK to change it",
                            status.HTTP_409_CONFLICT)
        if operation == OP_RELINK and not ctx.current:
            raise self._err("LINK_REQUIRED", "The personnel is not linked; use LINK", status.HTTP_409_CONFLICT)
        if ctx.current == target:
            return LinkOutcome(request_id=request_id, changed=False)
        row = self._row(ctx, kind=operation, new=target, request_id=request_id, fingerprint=fingerprint,
                        user_id=user_id, reason=reason)
        return await self._commit(ctx, row, request_id=request_id)

    async def reconcile(self, personnel_id: str, body: Mapping[str, object], *, request_id: str,
                        user_id: str) -> LinkOutcome:
        """Restores the latest link-history target into the personnel link
        cell. Only from MISMATCH; the target is never taken from the client."""
        reason = self.require_reason(body)
        ctx = await self._read(personnel_id)
        fingerprint = request_fingerprint(self._spec.op_reconcile, ctx.personnel_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        latest = ctx.latest
        if latest is None or ctx.consistency != CONSISTENCY_MISMATCH:
            raise self._err("RECONCILIATION_NOT_REQUIRED",
                            "The link matches its history (or has none); use LINK / UNLINK / RELINK instead",
                            status.HTTP_409_CONFLICT)
        related = text(body.get("related_request_id"))
        referenced = [e for e in ctx.events if e.request_id == related]
        if not related.strip() or not referenced or referenced[0].new_id != latest.new_id:
            raise self._err("RELATED_REQUEST_INVALID",
                            "related_request_id must name a prior event of this personnel whose target is the "
                            "latest history target", status.HTTP_409_CONFLICT)
        if latest.new_id:
            await self._check_target(ctx, latest.new_id)
        self._check_stale(ctx, body)
        row = self._row(ctx, kind=EVENT_RECONCILIATION, new=latest.new_id, request_id=request_id,
                        fingerprint=fingerprint, user_id=user_id, reason=reason, related=related)
        return await self._commit(ctx, row, request_id=request_id)

    async def history(self, personnel_id: str) -> LinkHistoryRead:
        ctx = await self._read(personnel_id)
        return LinkHistoryRead(
            personnel_id=ctx.personnel_id,
            current_id=_nullable(ctx.current),
            latest_history_id=_nullable(ctx.latest.new_id) if ctx.latest else None,
            consistency=ctx.consistency,
            events=ctx.events,
        )


__all__ = [
    "CONSISTENCY_CONSISTENT",
    "CONSISTENCY_MISMATCH",
    "CONSISTENCY_NO_HISTORY",
    "EVENT_KINDS",
    "EVENT_RECONCILIATION",
    "OPERATIONS",
    "OP_LINK",
    "OP_RELINK",
    "OP_UNLINK",
    "LinkEvent",
    "LinkHistoryRead",
    "LinkOutcome",
    "LinkSpec",
    "PersonnelLinkService",
    "history_issues",
    "link_value",
    "valid_shape",
]
