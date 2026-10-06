"""Phase 7 Batch 7O2c — responsible-branch writes (contract Final Rev2 §3, §5,
§6.2-§6.7, §8.1; Outcome Classification Addendum A.1, A.4; 7O2c review
clarifications C-c1..C-c7).

Five operations: transfer, insertion, correction, cancellation, projection
reconciliation. HISTORY-FIRST: W1 appends one asset_branch_history row; W2
writes responsible_branch_id + updated_at only when the operation requires it.
Every coded refusal is raised BEFORE W1 (each code is in
`registry_outcomes.ZERO_WRITE_ALLOWLIST` for its operation); after W1 the only
coded outcomes are the two write-failure codes and success. Nothing is retried,
compensated, re-read or re-appended, and no earlier row is ever edited. The
master is never written from an unresolved (AMBIGUOUS_ORDER) timeline.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import status

from app.domain.branch_timeline import (
    ASSET_BRANCH_HISTORY_COLUMNS,
    ASSIGNMENT,
    CANCELLATION,
    CONSISTENCY_CONSISTENT,
    CONSISTENCY_MISMATCH,
    CONSISTENCY_NO_HISTORY,
    CORRECTION,
    PROJECTION_RECONCILIATION,
    STATUS_AMBIGUOUS,
    STATUS_INVALID,
    STATUS_VALID,
    BranchTimeline,
    SourceUndetermined,
    TimelineEvent,
    derive_timeline,
    in_force_instants,
    source_before,
    tied_event_ids,
    validate_branch_row,
    vehicle_history_rows,
)
from app.domain.effective_time import EffectiveTime, EffectiveTimeError, resolve_effective
from app.domain.registration import DATA_CONTEXT_TEST, text
from app.domain.registry_errors import data_invalid
from app.domain.registry_write_support import error, registry_read, require_write_context, vehicle_read
from app.domain.request_replay import (
    OP_BRANCH_RECONCILE,
    OP_CANCELLATION,
    OP_CORRECTION,
    OP_INSERTION,
    OP_TRANSFER,
    find_replay,
    request_fingerprint,
)
from app.domain.vehicle_registry import RESPONSIBLE_BRANCH_COLUMN, parse_reference_rows
from app.errors import ApiError
from app.repositories.base import RegistryTableRead, Repository, RepositoryWriteError, VehicleMasterLocate

MAX_REASON_LENGTH = 500

PROJECTION_WRITTEN = "WRITTEN"
PROJECTION_NOT_NEEDED = "NOT_NEEDED"
PROJECTION_NOT_DETERMINED = "NOT_DETERMINED"


def _error(code: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, http_status, details)


@dataclass(frozen=True)
class BranchWriteOutcome:
    """A 200 outcome: changed (record written), no-op, or replay."""

    request_id: str
    changed: bool = False
    replayed: bool = False
    record_id: str | None = None
    event_id: str | None = None
    projection_write: str | None = None
    timeline_status_after: str | None = None
    current_branch_id: str | None = None
    consistency: str | None = None
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Context:
    """Everything read before any state check (R1 + R2 + validation)."""

    context: str
    master: VehicleMasterLocate
    vehicle_id: str
    master_value: str | None
    history: RegistryTableRead
    rows: list[Mapping[str, object]]
    timeline: BranchTimeline


class BranchWriteService:
    def __init__(self, repository: Repository, data_context: str | None, test_batch_id: str) -> None:
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _effective(body: Mapping[str, object], now: datetime, *, allow_now: bool) -> EffectiveTime:
        raw = body.get("effective")
        try:
            return resolve_effective(raw if isinstance(raw, Mapping) else {}, now, allow_now=allow_now)
        except EffectiveTimeError as exc:
            raise _error(exc.code, "The effective time is not accepted", status.HTTP_422_UNPROCESSABLE_ENTITY) from exc

    @staticmethod
    def _require_reason(body: Mapping[str, object]) -> str:
        """C-c5: a string, not blank, 1-500 characters; kept exactly."""
        reason = body.get("reason_th")
        if not isinstance(reason, str) or not reason.strip() or not 0 < len(reason) <= MAX_REASON_LENGTH:
            raise _error(
                "REASON_REQUIRED",
                f"A reason of 1-{MAX_REASON_LENGTH} characters is required",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return reason

    async def _read(self, vehicle_id: str, context: str) -> _Context:
        """R1 (+ locate, branch column), R2 (+ tab-wide record ids, this asset's
        structural validation). INVALID -> 500 BRANCH_HISTORY_DATA_INVALID."""
        master = await vehicle_read(self._repository.read_vehicle_branch_master(vehicle_id))
        if master is None:
            raise _error("VEHICLE_NOT_FOUND", f"Vehicle '{vehicle_id}' was not found", status.HTTP_404_NOT_FOUND)
        if RESPONSIBLE_BRANCH_COLUMN not in master.registry_columns:
            raise _error(
                "VEHICLE_MASTER_SCHEMA_INVALID",
                "vehicle_master has no responsible_branch_id column; nothing was changed",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                {"tab": "vehicle_master", "problem": "MISSING_HEADERS", "headers": [RESPONSIBLE_BRANCH_COLUMN]},
            )
        own_id = master.vehicle.vehicle_id
        field = master.registry.responsible_branch
        master_value = field.value if field.state == "RECORDED" else None
        history = await registry_read(self._repository.read_asset_branch_history_validated())
        ids = [text(r.get("assignment_id")) for r in history.rows if text(r.get("assignment_id"))]
        if len(ids) != len(set(ids)):
            # §5.2: a duplicate record id anywhere in the tab fails mutations.
            raise data_invalid("asset_branch_history", {"RECORD_ID_DUPLICATE": len(ids) - len(set(ids))})
        rows = vehicle_history_rows(history.rows, own_id)
        timeline = derive_timeline(rows, master_branch_id=master_value, master_available=True, context=context)
        if timeline.status == STATUS_INVALID:
            raise data_invalid("asset_branch_history", timeline.issue_counts)
        return _Context(context, master, own_id, master_value, history, rows, timeline)

    @staticmethod
    def _replay(ctx: _Context, request_id: str, fingerprint: str) -> BranchWriteOutcome | None:
        hit = find_replay(ctx.history.rows, request_id, fingerprint, record_id_column="assignment_id")
        if hit is None:
            return None
        if not hit.replayed:
            raise _error(
                "REQUEST_ID_REUSED",
                "This request id was already used for a different change; nothing was changed",
                status.HTTP_409_CONFLICT,
                {"request_id": request_id},
            )
        return BranchWriteOutcome(
            request_id=request_id, replayed=True, record_ids=hit.record_ids, consistency=ctx.timeline.consistency
        )

    @staticmethod
    def _stale(field: str) -> ApiError:
        return _error(
            "BRANCH_HISTORY_STALE",
            "The branch history or the vehicle record changed since it was loaded; reload and try again",
            status.HTTP_409_CONFLICT,
            {"field": field},
        )

    @staticmethod
    def _ambiguous(reason: str) -> ApiError:
        return _error(
            "BRANCH_TIMELINE_AMBIGUOUS",
            "Events share one effective instant, so the branch order is undetermined; nothing was changed",
            status.HTTP_409_CONFLICT,
            {"reason": reason},
        )

    @staticmethod
    def _mismatch() -> ApiError:
        return _error(
            "BRANCH_PROJECTION_MISMATCH",
            "The vehicle record's branch differs from the branch history; reconcile it first",
            status.HTTP_409_CONFLICT,
        )

    @staticmethod
    def _same_instant() -> ApiError:
        return _error(
            "BRANCH_EVENT_SAME_INSTANT",
            "Another branch event already takes effect at this exact instant; nothing was changed",
            status.HTTP_409_CONFLICT,
        )

    def _check_revision(self, ctx: _Context, body: Mapping[str, object]) -> None:
        if body.get("expected_history_revision") != ctx.timeline.revision:
            raise self._stale("history_revision")

    def _check_master(self, ctx: _Context, body: Mapping[str, object]) -> None:
        """Every timeline state; null compared exactly (Rev2 §6.4-§6.6)."""
        if body.get("expected_master_branch_id") != ctx.master_value:
            raise self._stale("master_branch_id")

    async def _check_destination(self, branch_id: str) -> None:
        """R3, only for a new destination and only after the no-op check.
        Without the optional is_active column every branch is active (C-c8)."""
        read = await registry_read(self._repository.read_branch_master_validated())
        entries, issues = parse_reference_rows(
            read.rows,
            code_column="branch_id",
            name_column="branch_name",
            active_column_present="is_active" in read.columns,
        )
        if issues:
            raise data_invalid("branch_master", issues)
        found = {e.code: e.is_active for e in entries}
        if branch_id not in found:
            raise _error(
                "BRANCH_NOT_FOUND",
                f"Branch '{branch_id}' is not in branch_master; nothing was changed",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"branch_id": branch_id},
            )
        if not found[branch_id]:
            raise _error(
                "BRANCH_INACTIVE",
                f"Branch '{branch_id}' is inactive; nothing was changed",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"branch_id": branch_id},
            )

    @staticmethod
    def _event(ctx: _Context, event_id: str) -> TimelineEvent:
        event = next((e for e in ctx.timeline.events if e.event_id == event_id), None)
        if event is None:
            raise _error(
                "BRANCH_EVENT_NOT_FOUND",
                "No branch event with this id exists for this vehicle",
                status.HTTP_404_NOT_FOUND,
                {"event_id": event_id},
            )
        if not event.in_force:
            raise _error(
                "BRANCH_EVENT_CANCELLED",
                "This branch event was cancelled; nothing was changed",
                status.HTTP_409_CONFLICT,
                {"event_id": event_id},
            )
        return event

    def _check_tie_target(self, ctx: _Context, event_id: str) -> None:
        """C-c1: in AMBIGUOUS_ORDER only an event participating in the tie may
        be corrected or cancelled."""
        if ctx.timeline.status == STATUS_AMBIGUOUS and event_id not in tied_event_ids(ctx.timeline):
            raise self._ambiguous("TARGET_NOT_TIED")

    def _row(
        self,
        ctx: _Context,
        *,
        request_id: str,
        fingerprint: str,
        user_id: str,
        **cells: str,
    ) -> dict[str, str]:
        row = dict.fromkeys(ASSET_BRANCH_HISTORY_COLUMNS, "")
        record_id = f"ABH-{uuid.uuid4().hex}"
        row.update(
            assignment_id=record_id,
            asset_type="VEHICLE",
            asset_id=ctx.vehicle_id,
            recorded_at=self._now().isoformat(timespec="microseconds"),
            recorded_by=user_id,
            request_id=request_id,
            request_fingerprint=fingerprint,
            is_test_data="TRUE" if ctx.context == DATA_CONTEXT_TEST else "FALSE",
            test_batch_id=self._batch_id if ctx.context == DATA_CONTEXT_TEST else "",
        )
        row.update(cells)
        if row["record_kind"] == ASSIGNMENT:
            row["event_id"] = record_id
        if not ctx.rows:
            # §5.3: the asset's FIRST record carries the imported baseline.
            row["baseline_branch_id"] = ctx.master_value or ""
            row["baseline_source"] = "IMPORTED_MASTER" if ctx.master_value else "NONE"
        issues = validate_branch_row(row)
        if issues:  # a programming error, before any write
            raise RuntimeError(f"generated branch history row is invalid: {issues}")
        return row

    async def _commit(
        self,
        ctx: _Context,
        row: dict[str, str],
        *,
        request_id: str,
        projection: str,
        target: str | None = None,
    ) -> BranchWriteOutcome:
        """W1, then W2 when `projection` is WRITTEN. The timeline after is
        derived in memory (no re-read)."""
        try:
            await self._repository.append_asset_branch_history(ctx.history, row)
        except RepositoryWriteError as exc:
            message = (
                "Google Sheets rejected the branch-history write; nothing was changed by this request"
                if exc.outcome == "rejected"
                else "The branch-history write outcome is unknown (the record may have been written); "
                "nothing was retried"
            )
            raise _error(
                "BRANCH_HISTORY_WRITE_FAILED",
                message,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {"history_write_outcome": exc.outcome, "projection_write": "NOT_ATTEMPTED", "request_id": request_id},
            ) from exc
        master_after = ctx.master_value
        if projection == PROJECTION_WRITTEN:
            try:
                await self._repository.write_vehicle_branch_cell(ctx.master, target, self._now())
            except RepositoryWriteError as exc:
                raise _error(
                    "BRANCH_PROJECTION_WRITE_FAILED",
                    "The branch change was recorded in the history, but the vehicle record update "
                    + ("was rejected" if exc.outcome == "rejected" else "has an unknown outcome")
                    + "; nothing was retried. Reconcile the vehicle's branch to finish it.",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    {
                        "event_recorded": True,
                        "record_id": row["assignment_id"],
                        "projection_write_outcome": exc.outcome,
                        "request_id": request_id,
                    },
                ) from exc
            master_after = target
        after = derive_timeline(
            [*ctx.rows, row], master_branch_id=master_after, master_available=True, context=ctx.context
        )
        return BranchWriteOutcome(
            request_id=request_id,
            changed=True,
            record_id=row["assignment_id"],
            event_id=row["event_id"] or None,
            projection_write=projection,
            timeline_status_after=after.status,
            current_branch_id=after.current_branch_id,
            consistency=after.consistency,
        )

    def _projection_after(self, ctx: _Context, row: dict[str, str]) -> tuple[str, str | None]:
        """Rev2 §6.4/§6.5: W2 only when the recomputed timeline is VALID and its
        current differs from the master; still AMBIGUOUS -> NOT_DETERMINED
        (master kept, never cleared or guessed)."""
        after = derive_timeline([*ctx.rows, row], master_branch_id=ctx.master_value, master_available=True, context=ctx.context)
        if after.status == STATUS_INVALID:  # a programming error, before any write
            raise RuntimeError(f"generated branch history row breaks the timeline: {after.issue_counts}")
        if after.status != STATUS_VALID:
            return PROJECTION_NOT_DETERMINED, None
        if after.current_branch_id != ctx.master_value:
            return PROJECTION_WRITTEN, after.current_branch_id
        return PROJECTION_NOT_NEEDED, None

    # ------------------------------------------------------------ §6.2 transfer

    async def transfer(self, vehicle_id: str, body: Mapping[str, object], *, request_id: str, user_id: str) -> BranchWriteOutcome:
        effective = self._effective(body, self._now(), allow_now=True)
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(vehicle_id, context)
        fingerprint = request_fingerprint(OP_TRANSFER, ctx.vehicle_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        self._check_revision(ctx, body)
        if tl.status == STATUS_AMBIGUOUS:
            raise self._ambiguous("TIMELINE_AMBIGUOUS")
        if tl.consistency == CONSISTENCY_MISMATCH:
            raise self._mismatch()
        if body.get("expected_current_branch_id") != tl.current_branch_id:
            raise self._stale("current_branch_id")
        instants = in_force_instants(tl)
        if effective.instant in instants:
            raise self._same_instant()
        if instants and effective.instant < max(instants):
            raise _error(
                "BRANCH_TRANSFER_NOT_LATEST",
                "The transfer is earlier than the latest branch event; record it as a backdated insertion",
                status.HTTP_409_CONFLICT,
            )
        destination = str(body.get("to_branch_id"))
        if destination == tl.current_branch_id:
            return BranchWriteOutcome(request_id=request_id, changed=False)
        await self._check_destination(destination)
        if not ctx.rows:
            source = (ctx.master_value, "BASELINE") if ctx.master_value else (None, "NONE")
        else:
            try:
                source = source_before(tl, effective.instant)
            except SourceUndetermined as exc:  # unreachable while VALID; fail closed
                raise self._ambiguous("SOURCE_UNDETERMINED") from exc
        note = body.get("note_th")
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=ASSIGNMENT, entry_operation="TRANSFER", revision_no="1",
            branch_id=destination, start_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_branch_id=source[0] or "",
            recorded_from_source=source[1], note_th=note if isinstance(note, str) else "",
        )
        projection, target = self._projection_after(ctx, row)
        return await self._commit(ctx, row, request_id=request_id, projection=projection, target=target)

    # ----------------------------------------------------------- §6.3 insertion

    async def insert(self, vehicle_id: str, body: Mapping[str, object], *, request_id: str, user_id: str) -> BranchWriteOutcome:
        effective = self._effective(body, self._now(), allow_now=False)
        reason = self._require_reason(body)
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(vehicle_id, context)
        fingerprint = request_fingerprint(OP_INSERTION, ctx.vehicle_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        self._check_revision(ctx, body)
        if tl.status == STATUS_AMBIGUOUS:
            raise self._ambiguous("TIMELINE_AMBIGUOUS")
        if tl.consistency == CONSISTENCY_MISMATCH:
            raise self._mismatch()
        instants = in_force_instants(tl)
        if effective.instant in instants:
            raise self._same_instant()
        if not instants or effective.instant > max(instants):
            raise _error(
                "BRANCH_INSERTION_NOT_HISTORICAL",
                "No later branch event exists; record this as a transfer instead",
                status.HTTP_409_CONFLICT,
            )
        try:
            source = source_before(tl, effective.instant)
        except SourceUndetermined as exc:  # unreachable while VALID; fail closed
            raise self._ambiguous("SOURCE_UNDETERMINED") from exc
        destination = str(body.get("to_branch_id"))
        if destination == source[0]:
            return BranchWriteOutcome(request_id=request_id, changed=False)
        await self._check_destination(destination)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=ASSIGNMENT, entry_operation="INSERTION", revision_no="1",
            branch_id=destination, start_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_branch_id=source[0] or "",
            recorded_from_source=source[1], note_th=reason,
        )
        # Strictly earlier than the latest event: the current branch cannot change (no W2).
        return await self._commit(ctx, row, request_id=request_id, projection=PROJECTION_NOT_NEEDED)

    # ---------------------------------------------------------- §6.4 correction

    async def correct(
        self, vehicle_id: str, event_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> BranchWriteOutcome:
        effective = self._effective(body, self._now(), allow_now=False)
        reason = self._require_reason(body)
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(vehicle_id, context)
        fingerprint = request_fingerprint(OP_CORRECTION, ctx.vehicle_id, event_id, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        self._check_revision(ctx, body)
        self._check_master(ctx, body)
        if tl.status == STATUS_VALID and tl.consistency == CONSISTENCY_MISMATCH:
            raise self._mismatch()
        head = self._event(ctx, event_id)
        self._check_tie_target(ctx, event_id)
        destination = str(body.get("to_branch_id"))
        if (destination, effective.stored, effective.precision) == (
            head.to_branch_id, head.effective_at, head.effective_precision,
        ):
            return BranchWriteOutcome(request_id=request_id, changed=False)
        if effective.instant in in_force_instants(tl, exclude_event=event_id):
            raise self._same_instant()
        try:
            source = source_before(tl, effective.instant, exclude_event=event_id)
        except SourceUndetermined as exc:  # C-c2: never guessed
            raise self._ambiguous("SOURCE_UNDETERMINED") from exc
        if destination != head.to_branch_id:
            # R3 only for a NEW destination (§6.1): a time-only correction keeps
            # the event's existing code, known, inactive or not, unchecked.
            await self._check_destination(destination)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CORRECTION, entry_operation="CORRECTION", event_id=event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            branch_id=destination, start_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_branch_id=source[0] or "",
            recorded_from_source=source[1], note_th=reason,
        )
        projection, target = self._projection_after(ctx, row)
        return await self._commit(ctx, row, request_id=request_id, projection=projection, target=target)

    # -------------------------------------------------------- §6.5 cancellation

    async def cancel(
        self, vehicle_id: str, event_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> BranchWriteOutcome:
        reason = self._require_reason(body)
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(vehicle_id, context)
        fingerprint = request_fingerprint(OP_CANCELLATION, ctx.vehicle_id, event_id, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        self._check_revision(ctx, body)
        self._check_master(ctx, body)
        if tl.status == STATUS_VALID and tl.consistency == CONSISTENCY_MISMATCH:
            raise self._mismatch()
        head = self._event(ctx, event_id)
        self._check_tie_target(ctx, event_id)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CANCELLATION, entry_operation="CANCELLATION", event_id=event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            note_th=reason,
        )
        # Re-derived from the remaining events and the BASELINE, never the master.
        projection, target = self._projection_after(ctx, row)
        return await self._commit(ctx, row, request_id=request_id, projection=projection, target=target)

    # ------------------------------------------- §6.6 projection reconciliation

    async def reconcile(self, vehicle_id: str, body: Mapping[str, object], *, request_id: str, user_id: str) -> BranchWriteOutcome:
        reason = self._require_reason(body)
        related_raw = body.get("related_request_id")
        related = related_raw if isinstance(related_raw, str) else ""
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(vehicle_id, context)
        fingerprint = request_fingerprint(OP_BRANCH_RECONCILE, ctx.vehicle_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        self._check_revision(ctx, body)
        self._check_master(ctx, body)
        if related and related not in [text(r.get("request_id")) for r in ctx.rows]:
            raise _error(
                "RELATED_REQUEST_NOT_FOUND",
                "related_request_id does not name a branch-history request of this vehicle",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if tl.status == STATUS_AMBIGUOUS:
            raise self._ambiguous("TIMELINE_AMBIGUOUS")
        if tl.consistency in (CONSISTENCY_CONSISTENT, CONSISTENCY_NO_HISTORY):
            return BranchWriteOutcome(request_id=request_id, changed=False)
        # PROJECTION_MISMATCH: write the derived value; no reference check (the
        # projection mirrors history, even for an unknown or deactivated code).
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=PROJECTION_RECONCILIATION, entry_operation="PROJECTION_RECONCILIATION",
            branch_id=tl.current_branch_id or "", reconciled_old_master_branch_id=ctx.master_value or "",
            related_request_id=related, note_th=reason,
        )
        return await self._commit(
            ctx, row, request_id=request_id, projection=PROJECTION_WRITTEN, target=tl.current_branch_id
        )
