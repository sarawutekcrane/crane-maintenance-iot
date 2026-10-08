"""R2 Batch R2d — responsible-branch writes for workshop EQUIPMENT (history-only).

Owner-approved decisions (R2d):
1. The first equipment branch record is a normal BRANCH ASSIGNMENT with no
   known source: record_kind ASSIGNMENT, entry_operation TRANSFER (the frozen
   R1 vocabulary; no INITIAL_ASSIGNMENT), recorded_from_source NONE and
   baseline_source NONE, both branch ids blank. That means "no authoritative
   previous branch is known" — NOT "the equipment had no branch before". No
   prior branch is ever inferred (not from source_equipment_register,
   location, personnel, branch_master or the equipment code/name).
2. Assignment/transfer needs `can_transfer_equipment_branch` (independent of
   the vehicle capability); insertion, correction and cancellation need
   `can_correct_branch_history`, which now covers vehicle AND equipment.
3. HISTORY-ONLY: W1 appends one asset_branch_history row; there is no W2. No
   equipment projection exists (R2b: master NOT_IN_SCHEMA), so there is no
   expected_master_branch_id, no projection mismatch gate, no projection
   write and no projection reconciliation. equipment_master and
   source_equipment_register are never written.

A dedicated service: the frozen vehicle `BranchWriteService` is not changed
or generalised. The frozen pure R1 helpers (row validation, timeline
derivation, BHR1, source_before, same-instant and tie rules, effective time,
replay) and the R2b equipment selector/adapter are reused unchanged; a few
small private helpers are duplicated on purpose so the vehicle module stays
byte-identical.

Order per operation: effective time / reason (422) -> write context (503) ->
7K2 equipment locate (EQUIPMENT_* errors) -> ONE asset_branch_history read
(tab-wide record-id check, this equipment's structural validation) -> replay
-> stale and state checks -> destination check (only for a new destination)
-> W1. Every coded refusal is raised before W1; after W1 the only outcomes
are success and BRANCH_HISTORY_WRITE_FAILED. Nothing is retried,
compensated, re-read or re-appended, and no earlier row is ever edited.
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
    CORRECTION,
    STATUS_AMBIGUOUS,
    STATUS_INVALID,
    BranchTimeline,
    SourceUndetermined,
    TimelineEvent,
    in_force_instants,
    source_before,
    tied_event_ids,
    validate_branch_row,
)
from app.domain.effective_time import (
    EffectiveTime,
    EffectiveTimeError,
    resolve_effective,
)
from app.domain.equipment_branch_history import (
    ASSET_TYPE_EQUIPMENT,
    equipment_history_rows,
    equipment_timeline,
)
from app.domain.equipment_service import EquipmentService
from app.domain.registration import DATA_CONTEXT_TEST, text
from app.domain.registry_errors import data_invalid
from app.domain.registry_write_support import (
    error,
    registry_read,
    require_write_context,
)
from app.domain.request_replay import (
    OP_EQUIPMENT_ASSIGNMENT,
    OP_EQUIPMENT_CANCELLATION,
    OP_EQUIPMENT_CORRECTION,
    OP_EQUIPMENT_INSERTION,
    find_replay,
    request_fingerprint,
)
from app.domain.vehicle_registry import parse_reference_rows
from app.errors import ApiError
from app.repositories.base import RegistryTableRead, Repository, RepositoryWriteError

MAX_REASON_LENGTH = 500


@dataclass(frozen=True)
class EquipmentBranchWriteOutcome:
    """A 200 outcome: changed (record written), no-op, or replay."""

    request_id: str
    changed: bool = False
    replayed: bool = False
    record_id: str | None = None
    event_id: str | None = None
    timeline_status_after: str | None = None
    current_branch_id: str | None = None
    current_source: str | None = None
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Context:
    context: str
    equipment_id: str
    history: RegistryTableRead
    rows: list[Mapping[str, object]]
    timeline: BranchTimeline


class EquipmentBranchWriteService:
    def __init__(self, repository: Repository, data_context: str | None, test_batch_id: str) -> None:
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id
        self._equipment = EquipmentService(repository)

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
            raise error(exc.code, "The effective time is not accepted", status.HTTP_422_UNPROCESSABLE_ENTITY) from exc

    @staticmethod
    def _require_reason(body: Mapping[str, object]) -> str:
        """A string, not blank, 1-500 characters; kept exactly (as R1 C-c5)."""
        reason = body.get("reason_th")
        if not isinstance(reason, str) or not reason.strip() or not 0 < len(reason) <= MAX_REASON_LENGTH:
            raise error(
                "REASON_REQUIRED",
                f"A reason of 1-{MAX_REASON_LENGTH} characters is required",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return reason

    async def _read(self, equipment_id: str, context: str) -> _Context:
        """The accepted 7K2 equipment locate (its errors unchanged), then ONE
        asset_branch_history read: the tab-wide record-id check and this
        equipment's frozen validation. INVALID -> 500 BRANCH_HISTORY_DATA_INVALID."""
        equipment = await self._equipment.get_equipment(equipment_id)
        history = await registry_read(self._repository.read_asset_branch_history_validated())
        ids = [text(r.get("assignment_id")) for r in history.rows if text(r.get("assignment_id"))]
        if len(ids) != len(set(ids)):
            # As R1 §5.2: a duplicate record id anywhere in the tab fails mutations.
            raise data_invalid("asset_branch_history", {"RECORD_ID_DUPLICATE": len(ids) - len(set(ids))})
        rows = equipment_history_rows(history.rows, equipment.equipment_id)
        timeline = equipment_timeline(rows, context=context)
        if timeline.status == STATUS_INVALID:
            raise data_invalid("asset_branch_history", timeline.issue_counts)
        return _Context(context, equipment.equipment_id, history, rows, timeline)

    @staticmethod
    def _replay(ctx: _Context, request_id: str, fingerprint: str) -> EquipmentBranchWriteOutcome | None:
        hit = find_replay(ctx.history.rows, request_id, fingerprint, record_id_column="assignment_id")
        if hit is None:
            return None
        if not hit.replayed:
            raise error(
                "REQUEST_ID_REUSED",
                "This request id was already used for a different change; nothing was changed",
                status.HTTP_409_CONFLICT,
                {"request_id": request_id},
            )
        return EquipmentBranchWriteOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids)

    @staticmethod
    def _stale(field: str) -> ApiError:
        return error(
            "BRANCH_HISTORY_STALE",
            "The equipment's branch history changed since it was loaded; reload and try again",
            status.HTTP_409_CONFLICT,
            {"field": field},
        )

    @staticmethod
    def _ambiguous(reason: str) -> ApiError:
        return error(
            "BRANCH_TIMELINE_AMBIGUOUS",
            "Events share one effective instant, so the branch order is undetermined; nothing was changed",
            status.HTTP_409_CONFLICT,
            {"reason": reason},
        )

    @staticmethod
    def _same_instant() -> ApiError:
        return error(
            "BRANCH_EVENT_SAME_INSTANT",
            "Another branch event already takes effect at this exact instant; nothing was changed",
            status.HTTP_409_CONFLICT,
        )

    def _check_revision(self, ctx: _Context, body: Mapping[str, object]) -> None:
        if body.get("expected_history_revision") != ctx.timeline.revision:
            raise self._stale("history_revision")

    async def _check_destination(self, branch_id: str) -> None:
        """The frozen R1 destination check, only for a new destination and only
        after the no-op check. Without the optional is_active column every
        branch is active (R1 C-c8)."""
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
            raise error(
                "BRANCH_NOT_FOUND",
                f"Branch '{branch_id}' is not in branch_master; nothing was changed",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"branch_id": branch_id},
            )
        if not found[branch_id]:
            raise error(
                "BRANCH_INACTIVE",
                f"Branch '{branch_id}' is inactive; nothing was changed",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"branch_id": branch_id},
            )

    @staticmethod
    def _event(ctx: _Context, event_id: str) -> TimelineEvent:
        event = next((e for e in ctx.timeline.events if e.event_id == event_id), None)
        if event is None:
            raise error(
                "BRANCH_EVENT_NOT_FOUND",
                "No branch event with this id exists for this equipment",
                status.HTTP_404_NOT_FOUND,
                {"event_id": event_id},
            )
        if not event.in_force:
            raise error(
                "BRANCH_EVENT_CANCELLED",
                "This branch event was cancelled; nothing was changed",
                status.HTTP_409_CONFLICT,
                {"event_id": event_id},
            )
        return event

    def _check_tie_target(self, ctx: _Context, event_id: str) -> None:
        """As R1 C-c1: in AMBIGUOUS_ORDER only an event in the tie may be
        corrected or cancelled."""
        if ctx.timeline.status == STATUS_AMBIGUOUS and event_id not in tied_event_ids(ctx.timeline):
            raise self._ambiguous("TARGET_NOT_TIED")

    def _row(self, ctx: _Context, *, request_id: str, fingerprint: str, user_id: str, **cells: str) -> dict[str, str]:
        """One new EQUIPMENT row: server-set identity, actor, time, request and
        data-context cells; the equipment's FIRST record carries the baseline
        NONE (never IMPORTED_MASTER: no equipment projection exists)."""
        row = dict.fromkeys(ASSET_BRANCH_HISTORY_COLUMNS, "")
        record_id = f"ABH-{uuid.uuid4().hex}"
        row.update(
            assignment_id=record_id,
            asset_type=ASSET_TYPE_EQUIPMENT,
            asset_id=ctx.equipment_id,
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
            row["baseline_branch_id"] = ""
            row["baseline_source"] = "NONE"
        issues = validate_branch_row(row)
        if issues:  # a programming error, before any write
            raise RuntimeError(f"generated branch history row is invalid: {issues}")
        return row

    async def _commit(self, ctx: _Context, row: dict[str, str], *, request_id: str) -> EquipmentBranchWriteOutcome:
        """The timeline after is derived in memory BEFORE W1 (an INVALID result
        is a programming error and nothing is written), then W1 only."""
        after = equipment_timeline([*ctx.rows, row], context=ctx.context)
        if after.status == STATUS_INVALID:
            raise RuntimeError(f"generated branch history row breaks the timeline: {after.issue_counts}")
        try:
            await self._repository.append_asset_branch_history(ctx.history, row)
        except RepositoryWriteError as exc:
            message = (
                "Google Sheets rejected the branch-history write; nothing was changed by this request"
                if exc.outcome == "rejected"
                else "The branch-history write outcome is unknown (the record may have been written); "
                "nothing was retried"
            )
            raise error(
                "BRANCH_HISTORY_WRITE_FAILED",
                message,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {"history_write_outcome": exc.outcome, "request_id": request_id},
            ) from exc
        return EquipmentBranchWriteOutcome(
            request_id=request_id,
            changed=True,
            record_id=row["assignment_id"],
            event_id=row["event_id"] or None,
            timeline_status_after=after.status,
            current_branch_id=after.current_branch_id,
            current_source=after.current_source,
        )

    # ------------------------------------------------------------- assignment

    async def assign(
        self, equipment_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> EquipmentBranchWriteOutcome:
        """First assignment (no prior branch known) and every later normal
        transfer: the latest event only."""
        effective = self._effective(body, self._now(), allow_now=True)
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(equipment_id, context)
        fingerprint = request_fingerprint(OP_EQUIPMENT_ASSIGNMENT, ctx.equipment_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        self._check_revision(ctx, body)
        if tl.status == STATUS_AMBIGUOUS:
            raise self._ambiguous("TIMELINE_AMBIGUOUS")
        if body.get("expected_current_branch_id") != tl.current_branch_id:
            raise self._stale("current_branch_id")
        instants = in_force_instants(tl)
        if effective.instant in instants:
            raise self._same_instant()
        if instants and effective.instant < max(instants):
            raise error(
                "BRANCH_TRANSFER_NOT_LATEST",
                "The assignment is earlier than the latest branch event; record it as a backdated insertion",
                status.HTTP_409_CONFLICT,
            )
        destination = str(body.get("to_branch_id"))
        if destination == tl.current_branch_id:
            return EquipmentBranchWriteOutcome(request_id=request_id, changed=False)
        await self._check_destination(destination)
        try:
            # No in-force event -> the recorded baseline, else (None, NONE): an
            # unknown prior branch is never labelled as a real branch.
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
        return await self._commit(ctx, row, request_id=request_id)

    # -------------------------------------------------------------- insertion

    async def insert(
        self, equipment_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> EquipmentBranchWriteOutcome:
        effective = self._effective(body, self._now(), allow_now=False)
        reason = self._require_reason(body)
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(equipment_id, context)
        fingerprint = request_fingerprint(OP_EQUIPMENT_INSERTION, ctx.equipment_id, None, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        self._check_revision(ctx, body)
        if tl.status == STATUS_AMBIGUOUS:
            raise self._ambiguous("TIMELINE_AMBIGUOUS")
        instants = in_force_instants(tl)
        if effective.instant in instants:
            raise self._same_instant()
        if not instants or effective.instant > max(instants):
            raise error(
                "BRANCH_INSERTION_NOT_HISTORICAL",
                "No later branch event exists; record this as a branch assignment instead",
                status.HTTP_409_CONFLICT,
            )
        try:
            source = source_before(tl, effective.instant)
        except SourceUndetermined as exc:  # unreachable while VALID; fail closed
            raise self._ambiguous("SOURCE_UNDETERMINED") from exc
        destination = str(body.get("to_branch_id"))
        if destination == source[0]:
            return EquipmentBranchWriteOutcome(request_id=request_id, changed=False)
        await self._check_destination(destination)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=ASSIGNMENT, entry_operation="INSERTION", revision_no="1",
            branch_id=destination, start_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_branch_id=source[0] or "",
            recorded_from_source=source[1], note_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    # ------------------------------------------------------------- correction

    async def correct(
        self, equipment_id: str, event_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> EquipmentBranchWriteOutcome:
        effective = self._effective(body, self._now(), allow_now=False)
        reason = self._require_reason(body)
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(equipment_id, context)
        fingerprint = request_fingerprint(OP_EQUIPMENT_CORRECTION, ctx.equipment_id, event_id, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        tl = ctx.timeline
        self._check_revision(ctx, body)
        head = self._event(ctx, event_id)
        self._check_tie_target(ctx, event_id)
        destination = str(body.get("to_branch_id"))
        if (destination, effective.stored, effective.precision) == (
            head.to_branch_id, head.effective_at, head.effective_precision,
        ):
            return EquipmentBranchWriteOutcome(request_id=request_id, changed=False)
        if effective.instant in in_force_instants(tl, exclude_event=event_id):
            raise self._same_instant()
        try:
            source = source_before(tl, effective.instant, exclude_event=event_id)
        except SourceUndetermined as exc:  # as R1 C-c2: never guessed
            raise self._ambiguous("SOURCE_UNDETERMINED") from exc
        if destination != head.to_branch_id:
            # Only for a NEW destination: a time-only correction keeps the
            # event's existing code, known, inactive or not, unchecked.
            await self._check_destination(destination)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CORRECTION, entry_operation="CORRECTION", event_id=event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            branch_id=destination, start_at=effective.stored, effective_precision=effective.precision,
            effective_source=effective.source, recorded_from_branch_id=source[0] or "",
            recorded_from_source=source[1], note_th=reason,
        )
        return await self._commit(ctx, row, request_id=request_id)

    # ----------------------------------------------------------- cancellation

    async def cancel(
        self, equipment_id: str, event_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> EquipmentBranchWriteOutcome:
        reason = self._require_reason(body)
        context = require_write_context(self._context, self._batch_id)
        ctx = await self._read(equipment_id, context)
        fingerprint = request_fingerprint(OP_EQUIPMENT_CANCELLATION, ctx.equipment_id, event_id, body)
        replay = self._replay(ctx, request_id, fingerprint)
        if replay is not None:
            return replay
        self._check_revision(ctx, body)
        head = self._event(ctx, event_id)
        self._check_tie_target(ctx, event_id)
        row = self._row(
            ctx, request_id=request_id, fingerprint=fingerprint, user_id=user_id,
            record_kind=CANCELLATION, entry_operation="CANCELLATION", event_id=event_id,
            revision_no=str(int(head.revision_no) + 1), supersedes_record_id=head.head_record_id,
            note_th=reason,
        )
        # Re-derived from the remaining events and the recorded baseline only.
        return await self._commit(ctx, row, request_id=request_id)
