"""R5 — vehicle status write authorization (AMB-1), effective-dated status events,
effective-time corrections and evidence-based downtime (OD-3).

AMB-1 (Owner-approved): every vehicle status WRITE — the existing
`PATCH /vehicles/{id}/status` and the R5 effective-dated event and correction
routes — needs (1) a trusted authenticated user, (2) `can_manage_repair`, checked
before any repository read, (3) the server's TEST/REAL data context and (4) the
vehicle located exactly once inside that scope (the established
`classify_reference` pattern of the crane-driver responsibility writes). Every
refusal writes nothing.

OD-3 (Owner-approved): downtime is derived ONLY from the vehicle's own status
events — `MAINTENANCE` and `OUT_OF_SERVICE` intervals. Repair / PM records are
never inputs, so simultaneous jobs cannot double count, an open job is never
downtime, and awaiting parts alone is never downtime. Time before the first
recorded event is UNKNOWN (never available, never downtime). An event's effective
time is its explicit `effective_at` or, for every pre-R5 / current-status change,
its recorded `changed_at`; a correction is an append-only record that moves one
event's effective time strictly between its neighbours and never changes a status.
"""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.domain.authz import CAN_MANAGE_REPAIR
from app.domain.common import OperationalStatus
from app.domain.crane_driver_responsibility import (
    REFERENCE_AMBIGUOUS,
    REFERENCE_MISSING,
    REFERENCE_SCOPE_UNPROVEN,
    VEHICLE_PREFIX,
    classify_reference,
)
from app.domain.crane_driver_timeline import VEHICLE_REFERENCE_TAB
from app.domain.effective_time import LOWER_BOUND
from app.domain.reference_read import reference_read
from app.domain.registry_write_support import error, require_write_context
from app.domain.request_replay import canonical_json
from app.domain.technician_assignment import AssignmentCutover
from app.domain.vehicle import Vehicle, VehicleStatusHistoryEntry, VehicleStatusTimeCorrection
from app.errors import ApiError
from app.repositories.base import Repository

UNAVAILABLE_STATUSES = frozenset({OperationalStatus.MAINTENANCE, OperationalStatus.OUT_OF_SERVICE})
EFFECTIVE_EXPLICIT = "EXPLICIT"
EFFECTIVE_RECORDED_TIME = "RECORDED_TIME"
STATUS_HISTORY_INCONSISTENT = "STATUS_HISTORY_INCONSISTENT"
MAX_REASON_LENGTH = 500
STATUS_WRITE_ACTION = "การเปลี่ยนสถานะรถ (change vehicle status)"


# ---------------------------------------------------------------------------
# AMB-1 guard
# ---------------------------------------------------------------------------


def require_vehicle_status_capability(context) -> None:
    """Step 2 of the guard: `can_manage_repair` and a user id, before any read."""
    if context is None or CAN_MANAGE_REPAIR not in context.capabilities or not (context.user_id or "").strip():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"{STATUS_WRITE_ACTION} requires the '{CAN_MANAGE_REPAIR}' capability")


async def require_vehicle_status_write(context, cutover: AssignmentCutover, repository: Repository,
                                       vehicle_id: str) -> str:
    """The ONE AMB-1 guard (Revision 4 §7.3); returns the server data context.
    Order: capability (403, no read) → data context (503) → vehicle exactly once
    in scope (404 / 409 / 422). No scope, batch or row detail is disclosed."""
    require_vehicle_status_capability(context)
    data_context = require_write_context(cutover.data_context, cutover.test_batch_id)
    reference = await reference_read(repository.read_vehicle_reference(), VEHICLE_PREFIX, VEHICLE_REFERENCE_TAB)
    kind = classify_reference(vehicle_id, reference, "vehicle_id", data_context, cutover.test_batch_id) \
        if vehicle_id.strip() else REFERENCE_MISSING
    if kind == REFERENCE_AMBIGUOUS:
        raise error("VEHICLE_ID_AMBIGUOUS", "More than one vehicle record has this id", status.HTTP_409_CONFLICT)
    if kind == REFERENCE_SCOPE_UNPROVEN:
        raise error("VEHICLE_SCOPE_UNPROVEN", "This vehicle cannot be proven to belong to the request's data scope",
                    status.HTTP_422_UNPROCESSABLE_ENTITY)
    if kind == REFERENCE_MISSING:
        raise error("VEHICLE_NOT_FOUND", "No vehicle record has exactly this id", status.HTTP_404_NOT_FOUND)
    return data_context


# ---------------------------------------------------------------------------
# Pure event resolution and downtime
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedEvent:
    entry: VehicleStatusHistoryEntry
    effective_at: datetime
    effective_source: str
    corrections: tuple[VehicleStatusTimeCorrection, ...]


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def resolved_events(history: Sequence[VehicleStatusHistoryEntry],
                    corrections: Sequence[VehicleStatusTimeCorrection]) -> list[ResolvedEvent]:
    """Every status event with its current effective time (latest correction,
    else `effective_at`, else the recorded `changed_at`), ordered by effective
    time, then by history id."""
    by_event: dict[str, list[VehicleStatusTimeCorrection]] = {}
    for correction in sorted(corrections, key=lambda c: (c.recorded_at, c.correction_id)):
        by_event.setdefault(correction.history_id, []).append(correction)
    events = []
    for entry in history:
        own = tuple(by_event.get(entry.history_id, ()))
        if own:
            effective, source = _utc(own[-1].new_effective_at), EFFECTIVE_EXPLICIT
        elif entry.effective_at is not None:
            effective, source = _utc(entry.effective_at), EFFECTIVE_EXPLICIT
        else:
            effective, source = _utc(entry.changed_at), EFFECTIVE_RECORDED_TIME
        events.append(ResolvedEvent(entry=entry, effective_at=effective, effective_source=source, corrections=own))
    return sorted(events, key=lambda e: (e.effective_at, e.entry.history_id))


def correction_bounds(history: Sequence[VehicleStatusHistoryEntry], corrections: Sequence[VehicleStatusTimeCorrection],
                      history_id: str) -> tuple[datetime | None, datetime | None, datetime]:
    """(previous neighbour's effective time, next neighbour's, the event's current
    effective time); ValueError VEHICLE_STATUS_EVENT_NOT_FOUND for an unknown event."""
    events = resolved_events(history, corrections)
    for index, event in enumerate(events):
        if event.entry.history_id == history_id:
            lower = events[index - 1].effective_at if index > 0 else None
            upper = events[index + 1].effective_at if index + 1 < len(events) else None
            return lower, upper, event.effective_at
    raise ValueError("VEHICLE_STATUS_EVENT_NOT_FOUND")


def derive_downtime(events: Sequence[ResolvedEvent], window_start: datetime, window_end: datetime,
                    current_status: OperationalStatus | None) -> dict:
    """OD-3: merged `[start, end)` unavailable intervals clipped to the window,
    their total, the UNKNOWN ranges (before the first event / no events) and the
    consistency flags. Nothing outside the evidence is ever counted."""
    intervals: list[list[datetime]] = []
    unknown: list[tuple[datetime, datetime]] = []
    flags: list[str] = []
    if not events:
        unknown.append((window_start, window_end))
    else:
        first = events[0].effective_at
        if window_start < first:
            unknown.append((window_start, min(first, window_end)))
        for index, event in enumerate(events):
            start = event.effective_at
            end = events[index + 1].effective_at if index + 1 < len(events) else window_end
            start, end = max(start, window_start), min(end, window_end)
            if end <= start or event.entry.status not in UNAVAILABLE_STATUSES:
                continue
            if intervals and intervals[-1][1] == start:
                intervals[-1][1] = end  # consecutive unavailable statuses are one downtime span
            else:
                intervals.append([start, end])
        if current_status is not None and events[-1].entry.status != current_status:
            flags.append(STATUS_HISTORY_INCONSISTENT)
    total = int(sum((end - start).total_seconds() for start, end in intervals))
    return {"intervals": [(start, end) for start, end in intervals], "total_seconds": total,
            "unknown": [(start, end) for start, end in unknown if end > start], "flags": flags}


def fingerprint(operation: str, vehicle_id: str, body: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json({"op": operation, "vehicle_id": vehicle_id, "body": dict(body)})
                          .encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _conflict(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_409_CONFLICT, details=details or {})


def _invalid(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details=details or {})


class VehicleStatusEventService:
    def __init__(self, repository: Repository, cutover: AssignmentCutover) -> None:
        self._repository = repository
        self._cutover = cutover

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)

    async def _vehicle(self, vehicle_id: str) -> Vehicle:
        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            raise ApiError(code="VEHICLE_NOT_FOUND", message=f"Vehicle '{vehicle_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        return vehicle

    async def _events(self, vehicle_id: str) -> list[ResolvedEvent]:
        history = await self._repository.list_vehicle_status_history(vehicle_id)
        corrections = await self._repository.list_vehicle_status_time_corrections(vehicle_id)
        return resolved_events(history, corrections)

    @staticmethod
    def _instant(value: datetime, now: datetime) -> datetime:
        if value.tzinfo is None:
            raise _invalid("EFFECTIVE_TIME_OFFSET_REQUIRED", "The effective time needs a UTC offset")
        if value.microsecond:
            raise _invalid("EFFECTIVE_TIME_PRECISION", "The effective time must be in whole seconds")
        instant = value.astimezone(timezone.utc)
        if instant > now:
            raise _invalid("FUTURE_EFFECTIVE_NOT_ALLOWED", "The effective time cannot be in the future")
        if instant < LOWER_BOUND:
            raise _invalid("EFFECTIVE_TIME_OUT_OF_RANGE", "The effective time is out of range")
        return instant

    async def _replay(self, vehicle_id: str, request_id: str, request_fingerprint: str) -> str | None:
        earlier = await self._repository.find_vehicle_status_request(vehicle_id, request_id)
        if earlier is None:
            return None
        if earlier[0] != request_fingerprint:
            raise _conflict("VEHICLE_STATUS_REQUEST_CONFLICT", "This request id was already used for another change; "
                            "nothing was changed")
        return earlier[1]

    async def record_effective_event(self, context, vehicle_id: str, *, new_status: OperationalStatus,
                                     effective_at: datetime, note: str | None, request_id: str,
                                     body: Mapping[str, object]) -> tuple[Vehicle, VehicleStatusHistoryEntry, bool]:
        await require_vehicle_status_write(context, self._cutover, self._repository, vehicle_id)
        digest = fingerprint("vehicle_status_event", vehicle_id, body)
        replayed_id = await self._replay(vehicle_id, request_id, digest)
        if replayed_id is not None:
            vehicle = await self._vehicle(vehicle_id)
            entry = next(e for e in await self._repository.list_vehicle_status_history(vehicle_id)
                         if e.history_id == replayed_id)
            return vehicle, entry, True
        await self._vehicle(vehicle_id)
        instant = self._instant(effective_at, self._now())
        events = await self._events(vehicle_id)
        if events and instant <= events[-1].effective_at:
            raise _conflict("VEHICLE_STATUS_EVENT_OUT_OF_ORDER", "The effective time must be after the latest recorded "
                            "status event; correct an earlier event's effective time instead")
        try:
            vehicle, entry = await self._repository.append_vehicle_status_event_effective(
                vehicle_id, new_status, instant, context.user_id, note, request_id, digest)
        except ValueError as exc:
            raise _conflict(str(exc), "The status event conflicts with the current history; nothing was changed") \
                from exc
        return vehicle, entry, False

    async def correct_effective_time(self, context, vehicle_id: str, history_id: str, *, new_effective_at: datetime,
                                     reason: str | None, request_id: str,
                                     body: Mapping[str, object]) -> tuple[VehicleStatusTimeCorrection, bool]:
        await require_vehicle_status_write(context, self._cutover, self._repository, vehicle_id)
        digest = fingerprint("vehicle_status_time_correction", vehicle_id, {**body, "history_id": history_id})
        replayed_id = await self._replay(vehicle_id, request_id, digest)
        if replayed_id is not None:
            existing = next(c for c in await self._repository.list_vehicle_status_time_corrections(vehicle_id)
                            if c.correction_id == replayed_id)
            return existing, True
        if reason is None or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
            raise _invalid("VEHICLE_STATUS_CORRECTION_REASON_REQUIRED",
                           f"A reason of 1-{MAX_REASON_LENGTH} characters is required")
        await self._vehicle(vehicle_id)
        instant = self._instant(new_effective_at, self._now())
        history = await self._repository.list_vehicle_status_history(vehicle_id)
        corrections = await self._repository.list_vehicle_status_time_corrections(vehicle_id)
        try:
            lower, upper, current = correction_bounds(history, corrections, history_id)
        except ValueError as exc:
            raise ApiError(code="VEHICLE_STATUS_EVENT_NOT_FOUND", message="No status event has this id",
                           status_code=status.HTTP_404_NOT_FOUND) from exc
        if (lower is not None and instant <= lower) or (upper is not None and instant >= upper):
            raise _conflict("VEHICLE_STATUS_EVENT_OUT_OF_ORDER", "The new effective time must stay strictly between the "
                            "neighbouring status events; nothing was changed")
        correction = VehicleStatusTimeCorrection(
            correction_id=f"VSTC-{uuid.uuid4().hex[:16]}", vehicle_id=vehicle_id, history_id=history_id,
            previous_effective_at=current, new_effective_at=instant, reason=reason, corrected_by=context.user_id,
            recorded_at=self._now(), request_id=request_id, request_fingerprint=digest)
        try:
            stored = await self._repository.append_vehicle_status_time_correction(correction)
        except ValueError as exc:
            raise _conflict(str(exc), "The correction conflicts with the current history; nothing was changed") \
                from exc
        return stored, False

    async def list_events(self, vehicle_id: str) -> list[ResolvedEvent]:
        await self._vehicle(vehicle_id)
        return await self._events(vehicle_id)

    async def downtime(self, vehicle_id: str, window_start: datetime, window_end: datetime) -> dict:
        vehicle = await self._vehicle(vehicle_id)
        now = self._now()
        start, end = _utc(window_start), min(_utc(window_end), now)
        if end <= start:
            raise _invalid("DOWNTIME_WINDOW_INVALID", "`to` must be after `from` (and `from` before now)")
        events = await self._events(vehicle_id)
        result = derive_downtime(events, start, end, vehicle.operational_status)
        return {"vehicle_id": vehicle_id, "from": start, "to": end, **result}


__all__ = [
    "EFFECTIVE_EXPLICIT", "EFFECTIVE_RECORDED_TIME", "ResolvedEvent", "STATUS_HISTORY_INCONSISTENT",
    "UNAVAILABLE_STATUSES", "VehicleStatusEventService", "correction_bounds", "derive_downtime", "fingerprint",
    "require_vehicle_status_capability", "require_vehicle_status_write", "resolved_events",
]
