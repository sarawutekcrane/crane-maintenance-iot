"""R5 — Repair substates and technician work time: pure models and rules (no I/O).

Roadmap R5 RM-2..RM-12 with Owner decisions OD-2, OD-4 and AMB-2:

* Repair substates `REPAIRING` (กำลังซ่อม) and `AWAITING_PARTS` (รออะไหล่) are
  recorded PERIODS under an OPEN Repair Work Order. They are records, never new
  canonical statuses: `RepairStatus` stays OPEN / CLOSED / CANCELLED.
* A technician's work time is a dated period with an explicit `time_class`
  (REGULAR / OVERTIME, never inferred), a description and an explicit break
  declaration (`[]` = "no break"). A gap between periods is "not recorded",
  never a break. Nothing here ever creates time automatically.
* Every record is append-only: a correction or void is a new revision of the
  same id; the previous revision stays. A confirmation names exact
  `entry_id@revision` values and is valid only for an entry's CURRENT revision.
* Intervals are half-open `[start, end)`, timezone-aware UTC. There is no
  maximum length; crossing midnight is allowed. Workdays are Asia/Bangkok
  calendar dates touched by NET work (the period minus its breaks).
* Actual man-hours are never the planned TEAM_ELAPSED duration of R4 and are
  never multiplied by a team size.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict

from app.domain.effective_time import BANGKOK, LOWER_BOUND

WORK_KIND_REPAIR = "REPAIR"
WORK_KIND_PM = "PM"
WORK_KINDS = (WORK_KIND_REPAIR, WORK_KIND_PM)

SUBSTATE_REPAIRING = "REPAIRING"
SUBSTATE_AWAITING_PARTS = "AWAITING_PARTS"
SUBSTATES = (SUBSTATE_REPAIRING, SUBSTATE_AWAITING_PARTS)

RECORD_ENTRY = "ENTRY"
RECORD_CORRECTION = "CORRECTION"
RECORD_VOID = "VOID"
RECORD_KINDS = (RECORD_ENTRY, RECORD_CORRECTION, RECORD_VOID)

TIME_CLASS_REGULAR = "REGULAR"
TIME_CLASS_OVERTIME = "OVERTIME"
TIME_CLASSES = (TIME_CLASS_REGULAR, TIME_CLASS_OVERTIME)

MAX_REASON_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 1000


class WorkTimeRuleError(ValueError):
    """A refused value; `code` is the stable API error code."""

    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RepairSubstatePeriod(BaseModel):
    """One revision of one Repair substate period (append-only)."""

    model_config = ConfigDict(frozen=True)

    period_id: str
    revision: int
    record_kind: str
    repair_id: str
    substate: str
    started_at: datetime
    ended_at: datetime | None = None
    """None = ongoing (shown ending at close / cancel / now; never written)."""
    material_request_id: str | None = None
    recorded_by: str
    recorded_at: datetime
    reason: str | None = None
    request_id: str
    request_fingerprint: str
    is_test_data: str = ""
    test_batch_id: str = ""


class WorkBreak(BaseModel):
    model_config = ConfigDict(frozen=True)

    started_at: datetime
    ended_at: datetime


class WorkTimeEntry(BaseModel):
    """One revision of one technician work period (append-only)."""

    model_config = ConfigDict(frozen=True)

    entry_id: str
    revision: int
    record_kind: str
    work_kind: str
    job_id: str
    technician_id: str
    started_at: datetime
    ended_at: datetime
    time_class: str
    description: str
    breaks: tuple[WorkBreak, ...] = ()
    recorded_by: str
    recorded_at: datetime
    reason: str | None = None
    request_id: str
    request_fingerprint: str
    member_set_id: str = ""
    """A V2 assignment set of this job that contains the technician (membership evidence)."""
    is_test_data: str = ""
    test_batch_id: str = ""

    @property
    def ref(self) -> str:
        return entry_ref(self.entry_id, self.revision)

    @property
    def is_void(self) -> bool:
        return self.record_kind == RECORD_VOID


class WorkTimeConfirmation(BaseModel):
    """A manager's confirmation of exact entry revisions (append-only)."""

    model_config = ConfigDict(frozen=True)

    confirmation_id: str
    work_kind: str
    job_id: str
    entries: tuple[str, ...]
    """`entry_id@revision` values."""
    confirmed_by: str
    confirmer_technician_id: str | None = None
    confirmed_at: datetime
    note: str | None = None
    request_id: str
    request_fingerprint: str
    is_test_data: str = ""
    test_batch_id: str = ""


def entry_ref(entry_id: str, revision: int) -> str:
    return f"{entry_id}@{revision}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise WorkTimeRuleError("WORK_TIME_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def normalize_instant(value: datetime) -> datetime:
    """UTC, whole seconds (sub-second precision is refused, never rounded)."""
    instant = _aware(value)
    if instant.microsecond:
        raise WorkTimeRuleError("WORK_TIME_PRECISION")
    return instant


def validate_interval(started_at: datetime, ended_at: datetime, now: datetime, *,
                      code: str = "WORK_TIME_INVALID_INTERVAL") -> tuple[datetime, datetime]:
    """end > start, end ≤ now, start ≥ the system lower bound. No maximum length."""
    start, end = normalize_instant(started_at), normalize_instant(ended_at)
    if end <= start or end > now or start < LOWER_BOUND:
        raise WorkTimeRuleError(code, {"started_at": start.isoformat(), "ended_at": end.isoformat()})
    return start, end


def validate_breaks(started_at: datetime, ended_at: datetime,
                    breaks: Sequence[WorkBreak] | None) -> tuple[WorkBreak, ...]:
    """The declaration is mandatory (None refused; `[]` = explicitly no break).
    Each break lies inside the period, has positive length, and breaks never
    overlap; together they never cover the whole period."""
    if breaks is None:
        raise WorkTimeRuleError("WORK_TIME_BREAKS_REQUIRED")
    normalized: list[WorkBreak] = []
    for item in breaks:
        start, end = normalize_instant(item.started_at), normalize_instant(item.ended_at)
        if end <= start or start < started_at or end > ended_at:
            raise WorkTimeRuleError("WORK_TIME_BREAK_INVALID", {"started_at": start.isoformat(),
                                                                 "ended_at": end.isoformat()})
        normalized.append(WorkBreak(started_at=start, ended_at=end))
    normalized.sort(key=lambda b: b.started_at)
    for previous, following in zip(normalized, normalized[1:]):
        if following.started_at < previous.ended_at:
            raise WorkTimeRuleError("WORK_TIME_BREAK_INVALID", {"reason": "OVERLAPPING_BREAKS"})
    if sum((b.ended_at - b.started_at for b in normalized), timedelta()) >= ended_at - started_at:
        raise WorkTimeRuleError("WORK_TIME_BREAK_INVALID", {"reason": "NO_NET_WORK"})
    return tuple(normalized)


def validate_reason(reason: str | None, *, required: bool) -> str | None:
    if reason is None or not reason.strip():
        if required:
            raise WorkTimeRuleError("WORK_TIME_REASON_REQUIRED")
        return None
    if len(reason) > MAX_REASON_LENGTH:
        raise WorkTimeRuleError("WORK_TIME_REASON_TOO_LONG")
    return reason


def validate_description(description: str | None) -> str:
    if description is None or not description.strip():
        raise WorkTimeRuleError("WORK_TIME_DESCRIPTION_REQUIRED")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise WorkTimeRuleError("WORK_TIME_DESCRIPTION_TOO_LONG")
    return description


def validate_time_class(value: str | None) -> str:
    if value not in TIME_CLASSES:
        raise WorkTimeRuleError("WORK_TIME_CLASS_INVALID")
    return value


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


def current_revisions(records: Iterable, id_attr: str) -> dict[str, object]:
    """The latest revision of every id. Revisions of one id must be exactly
    1..n (a gap or a duplicate is untrusted history → WORK_TIME_DATA_INVALID)."""
    grouped: dict[str, list] = defaultdict(list)
    for record in records:
        grouped[getattr(record, id_attr)].append(record)
    latest: dict[str, object] = {}
    for key, revisions in grouped.items():
        numbers = sorted(r.revision for r in revisions)
        if numbers != list(range(1, len(numbers) + 1)):
            raise WorkTimeRuleError("WORK_TIME_DATA_INVALID", {"issue": "REVISION_CHAIN_BROKEN"})
        latest[key] = max(revisions, key=lambda r: r.revision)
    return latest


def effective_entries(records: Iterable[WorkTimeEntry]) -> list[WorkTimeEntry]:
    return [e for e in current_revisions(records, "entry_id").values() if not e.is_void]  # type: ignore[union-attr]


def effective_periods(records: Iterable[RepairSubstatePeriod]) -> list[RepairSubstatePeriod]:
    return [p for p in current_revisions(records, "period_id").values()  # type: ignore[union-attr]
            if p.record_kind != RECORD_VOID]


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------

_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def net_intervals(entry: WorkTimeEntry) -> list[tuple[datetime, datetime]]:
    """The period minus its breaks (half-open pieces)."""
    pieces: list[tuple[datetime, datetime]] = []
    cursor = entry.started_at
    for item in sorted(entry.breaks, key=lambda b: b.started_at):
        if item.started_at > cursor:
            pieces.append((cursor, item.started_at))
        cursor = max(cursor, item.ended_at)
    if entry.ended_at > cursor:
        pieces.append((cursor, entry.ended_at))
    return pieces


def net_seconds(entry: WorkTimeEntry) -> int:
    return int(sum((end - start).total_seconds() for start, end in net_intervals(entry)))


def find_overlap(candidate: WorkTimeEntry, others: Iterable[WorkTimeEntry]) -> WorkTimeEntry | None:
    """RM-3 / RM-9: the first effective entry of the SAME technician (any job)
    whose net work intersects the candidate's net work; another revision of the
    same entry is ignored. Time inside a break may be worked on another job."""
    mine = net_intervals(candidate)
    for other in others:
        if other.entry_id == candidate.entry_id or other.technician_id != candidate.technician_id or other.is_void:
            continue
        for a_start, a_end in mine:
            if any(_overlap(a_start, a_end, b_start, b_end) for b_start, b_end in net_intervals(other)):
                return other
    return None


def substate_conflict(candidate: RepairSubstatePeriod,
                      others: Iterable[RepairSubstatePeriod]) -> RepairSubstatePeriod | None:
    """RM-3: substate periods of one Repair never overlap (either substate); an
    ongoing period extends without end, so at most one can be ongoing."""
    c_end = candidate.ended_at or _FAR_FUTURE
    for other in others:
        if other.period_id == candidate.period_id or other.record_kind == RECORD_VOID:
            continue
        if _overlap(candidate.started_at, c_end, other.started_at, other.ended_at or _FAR_FUTURE):
            return other
    return None


def bangkok_dates(start: datetime, end: datetime) -> set[date]:
    """Asia/Bangkok calendar dates touched by `[start, end)` (an interval ending
    exactly at local midnight does not touch the next date)."""
    if end <= start:
        return set()
    first = start.astimezone(BANGKOK).date()
    last = (end - timedelta(microseconds=1)).astimezone(BANGKOK).date()
    days, current = set(), first
    while current <= last:
        days.add(current)
        current += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Totals and durations (derived, never stored)
# ---------------------------------------------------------------------------


def technician_totals(entries: Iterable[WorkTimeEntry]) -> dict[str, dict]:
    """Per technician: REGULAR / OVERTIME / total net seconds and the
    Asia/Bangkok dates on which net work occurred (RM-11). VOID excluded."""
    totals: dict[str, dict] = {}
    for entry in entries:
        if entry.is_void:
            continue
        row = totals.setdefault(entry.technician_id, {"regular_seconds": 0, "overtime_seconds": 0, "dates": set()})
        seconds = net_seconds(entry)
        row["regular_seconds" if entry.time_class == TIME_CLASS_REGULAR else "overtime_seconds"] += seconds
        for start, end in net_intervals(entry):
            row["dates"] |= bangkok_dates(start, end)
    return {tid: {"regular_seconds": r["regular_seconds"], "overtime_seconds": r["overtime_seconds"],
                  "total_seconds": r["regular_seconds"] + r["overtime_seconds"],
                  "workdays": sorted(d.isoformat() for d in r["dates"])}
            for tid, r in sorted(totals.items())}


def team_totals(per_technician: dict[str, dict]) -> dict:
    """Σ of individual actual man-hours (RM-11); never elapsed × team size."""
    regular = sum(r["regular_seconds"] for r in per_technician.values())
    overtime = sum(r["overtime_seconds"] for r in per_technician.values())
    return {"regular_seconds": regular, "overtime_seconds": overtime, "total_seconds": regular + overtime,
            "technician_count": len(per_technician)}


def substate_durations(periods: Iterable[RepairSubstatePeriod], opened_at: datetime,
                       end_bound: datetime) -> dict:
    """RM-4 / RM-5: elapsed seconds per substate, the whole Work Order elapsed
    (`opened_at` → close / cancel / now) and "other" = elapsed − both; an ongoing
    period is shown up to `end_bound` (nothing is written)."""
    sums = {SUBSTATE_REPAIRING: 0, SUBSTATE_AWAITING_PARTS: 0}
    for period in periods:
        if period.record_kind == RECORD_VOID:
            continue
        end = min(period.ended_at or end_bound, end_bound)
        start = max(period.started_at, opened_at)
        if end > start:
            sums[period.substate] += int((end - start).total_seconds())
    elapsed = max(int((end_bound - opened_at).total_seconds()), 0)
    return {"repairing_seconds": sums[SUBSTATE_REPAIRING], "awaiting_parts_seconds": sums[SUBSTATE_AWAITING_PARTS],
            "elapsed_seconds": elapsed,
            "other_seconds": max(elapsed - sums[SUBSTATE_REPAIRING] - sums[SUBSTATE_AWAITING_PARTS], 0)}


def confirmed_refs(confirmations: Iterable[WorkTimeConfirmation]) -> set[str]:
    return {ref for confirmation in confirmations for ref in confirmation.entries}


def unconfirmed_entries(records: Iterable[WorkTimeEntry],
                        confirmations: Iterable[WorkTimeConfirmation]) -> list[WorkTimeEntry]:
    """OD-2: every recorded entry (its CURRENT revision, a void included) needs a
    confirmation of exactly that revision. A confirmation of an obsolete revision
    does not count."""
    refs = confirmed_refs(confirmations)
    return [e for e in current_revisions(records, "entry_id").values()  # type: ignore[union-attr]
            if e.ref not in refs]


__all__ = [
    "RECORD_CORRECTION", "RECORD_ENTRY", "RECORD_KINDS", "RECORD_VOID", "RepairSubstatePeriod",
    "SUBSTATES", "SUBSTATE_AWAITING_PARTS", "SUBSTATE_REPAIRING", "TIME_CLASSES", "TIME_CLASS_OVERTIME",
    "TIME_CLASS_REGULAR", "WORK_KINDS", "WORK_KIND_PM", "WORK_KIND_REPAIR", "WorkBreak", "WorkTimeConfirmation",
    "WorkTimeEntry", "WorkTimeRuleError", "bangkok_dates", "confirmed_refs", "current_revisions",
    "effective_entries", "effective_periods", "entry_ref", "find_overlap", "net_intervals", "net_seconds",
    "normalize_instant", "substate_conflict", "substate_durations", "team_totals", "technician_totals",
    "unconfirmed_entries", "validate_breaks", "validate_description", "validate_interval", "validate_reason",
    "validate_time_class",
]
