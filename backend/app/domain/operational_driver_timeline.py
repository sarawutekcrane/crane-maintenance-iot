"""R2 Batch R2-C1 — E2 operational driver assignment: record validation and
schedule derivation (pure; no I/O; `now` is never read here).

Governance: C1 Amendment A2 (A2-2 to A2-7) and the owner decisions P1–P8,
O1–O4, DQ-1–DQ-7. E2 is ONE separate append-only, revisioned authority
(`crane_operational_driver_assignment_history`). It is NOT the R2f-f permanent
responsibility (`crane_driver_responsibility_history`, never written here) and
NOT the Phase 6 `vehicle_driver` history (never read). It records ASSIGNED
drivers, never verified actual driving.

Logical events (one `event_id`, revisions 1..n, each later row naming the head
it supersedes):
- an ASSIGNMENT chain: ASSIGNMENT (revision 1) then REVISION rows, each a full
  new state; it ends with an optional terminal CANCELLATION;
- a HANDOVER chain: HANDOVER rows (an H2 or E2-H3 boundary transition between
  two assignments of one vehicle, naming the exact revisions it was validated
  against); it ends with an optional terminal CANCELLATION.

Derivation (stored facts -> derived values):
- units: one per calendar date of [start_date, end_date] minus
  `excluded_dates`; FULL_DAY = [D 00:00, D+1 00:00), a shift =
  [D start, D+offset end) — all Asia/Bangkok, half-open, stored as UTC;
- clips: an in-force H2 ends the predecessor's last unit at `handover_at`, an
  in-force E2-H3 starts the successor's first unit at `handover_at`;
  `early_end_at` cuts every unit at that instant; a VOIDED assignment has no
  coverage;
- UNKNOWN: a handover revision written by a post-handover correction carries
  the elapsed part of the time the handover moved (`unknown_start_at` /
  `unknown_end_at`); the derived UNKNOWN is that interval minus any current
  coverage of the vehicle. An EARLY_END never creates UNKNOWN;
- CONFLICTED: two derived in-force intervals overlap on one vehicle or for one
  driver. Never resolved by a guess.
Any structural defect is INVALID (the service answers 500, never a partial or
empty list).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from app.domain.effective_time import BANGKOK
from app.domain.registration import parse_aware, text

OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_TAB = "crane_operational_driver_assignment_history"
OPERATIONAL_DRIVER_ASSIGNMENT_HISTORY_COLUMNS: tuple[str, ...] = (
    "record_id",
    "operation_id",
    "record_kind",
    "entry_operation",
    "event_id",
    "revision_no",
    "supersedes_record_id",
    "vehicle_id",
    "driver_id",
    "mode",
    "start_date",
    "end_date",
    "shift_start_time",
    "shift_end_time",
    "shift_end_day_offset",
    "excluded_dates",
    "related_event_id",
    "relation",
    "early_end_at",
    "voided",
    "handover_kind",
    "predecessor_event_id",
    "predecessor_revision_no",
    "successor_event_id",
    "successor_revision_no",
    "handover_at",
    "unknown_start_at",
    "unknown_end_at",
    "reason_th",
    "recorded_at",
    "recorded_by",
    "request_id",
    "request_fingerprint",
    "is_test_data",
    "test_batch_id",
)

# record kinds
ASSIGNMENT = "ASSIGNMENT"
REVISION = "REVISION"
HANDOVER = "HANDOVER"
CANCELLATION = "CANCELLATION"
RECORD_KINDS = (ASSIGNMENT, REVISION, HANDOVER, CANCELLATION)

# the POST operations (the row's entry_operation)
OP_CREATE = "CREATE"
OP_REVISE = "REVISE"
OP_SUBSTITUTE = "SUBSTITUTE"
OP_CANCEL = "CANCEL"
OP_EARLY_END = "EARLY_END"
OPERATIONS = (OP_CREATE, OP_REVISE, OP_SUBSTITUTE, OP_CANCEL, OP_EARLY_END)

MODE_FULL_DAY = "FULL_DAY"
MODE_DAY_SHIFT = "DAY_SHIFT"
MODE_NIGHT_SHIFT = "NIGHT_SHIFT"
MODES = (MODE_FULL_DAY, MODE_DAY_SHIFT, MODE_NIGHT_SHIFT)
SHIFT_MODES = (MODE_DAY_SHIFT, MODE_NIGHT_SHIFT)

HANDOVER_H2 = "H2"  # FULL_DAY last date -> NIGHT_SHIFT starting that date (A2-4.4)
HANDOVER_H3 = "E2_H3"  # NIGHT_SHIFT carrying into D+1 -> FULL_DAY starting D+1 (A2-4.5)
HANDOVER_KINDS = (HANDOVER_H2, HANDOVER_H3)

RELATION_SPLIT = "SPLIT"
RELATION_SUBSTITUTION = "SUBSTITUTION"
RELATIONS = (RELATION_SPLIT, RELATION_SUBSTITUTION)

TRUE = "TRUE"

STATUS_VALID = "VALID"
STATUS_CONFLICTED = "CONFLICTED"
STATUS_INVALID = "INVALID"

COVERAGE_ASSIGNED = "ASSIGNED"
COVERAGE_UNKNOWN = "UNKNOWN"

LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_CANCELLED = "CANCELLED"
LIFECYCLE_VOIDED = "VOIDED"

MAX_RANGE_DAYS = 366  # DQ-7: inclusive calendar days per assignment
MAX_START_AHEAD_DAYS = 366  # DQ-7: a new start date at most this far after today (Bangkok)

_HEX64 = re.compile(r"[0-9a-f]{64}")
_INT = re.compile(r"[1-9][0-9]*")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIME = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")

_ASSIGNMENT_FIELDS = ("vehicle_id", "driver_id", "mode", "start_date", "end_date")
_SHIFT_FIELDS = ("shift_start_time", "shift_end_time", "shift_end_day_offset")
_HANDOVER_FIELDS = ("handover_kind", "predecessor_event_id", "predecessor_revision_no", "successor_event_id",
                    "successor_revision_no", "handover_at")


# ---------------------------------------------------------------------------
# Value parsing (total; None when not exact)
# ---------------------------------------------------------------------------


def parse_date(value: object) -> date | None:
    raw = text(value)
    if not _DATE.fullmatch(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def parse_time(value: object) -> time | None:
    raw = text(value)
    if not _TIME.fullmatch(raw):
        return None
    return time(int(raw[:2]), int(raw[3:]))


def parse_dates(value: object) -> list[date] | None:
    """`excluded_dates`: blank, or comma-separated strictly ascending ISO dates."""
    raw = text(value)
    if not raw:
        return []
    out: list[date] = []
    for part in raw.split(","):
        parsed = parse_date(part)
        if parsed is None or (out and parsed <= out[-1]):
            return None
        out.append(parsed)
    return out


def format_dates(values: Iterable[date]) -> str:
    return ",".join(d.isoformat() for d in sorted(set(values)))


def bangkok(day: date, at: time = time(0, 0)) -> datetime:
    """The UTC instant of a Bangkok wall-clock time (Asia/Bangkok has no DST)."""
    return datetime.combine(day, at, tzinfo=BANGKOK).astimezone(timezone.utc)


def bangkok_date(instant: datetime) -> date:
    return instant.astimezone(BANGKOK).date()


def iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).isoformat()


def shift_duration_valid(start: time, end: time, offset: int) -> bool:
    """>0 and <=24h: offset 0 needs end > start; offset 1 needs end <= start
    (equal = exactly 24 hours, only with the explicit next-day marker)."""
    if offset == 0:
        return end > start
    if offset == 1:
        return end <= start
    return False


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    """The scheduling facts of one assignment state (stored text, parsed)."""

    mode: str
    start_date: date
    end_date: date
    shift_start: time | None = None
    shift_end: time | None = None
    shift_offset: int = 0
    excluded: tuple[date, ...] = ()

    def dates(self) -> list[date]:
        days = (self.end_date - self.start_date).days + 1
        excluded = set(self.excluded)
        return [d for d in (self.start_date + timedelta(n) for n in range(max(days, 0))) if d not in excluded]

    def unit(self, day: date) -> tuple[datetime, datetime]:
        """The applied scheduled interval of the unit labelled `day`."""
        if self.mode == MODE_FULL_DAY:
            return bangkok(day), bangkok(day + timedelta(1))
        assert self.shift_start is not None and self.shift_end is not None
        return bangkok(day, self.shift_start), bangkok(day + timedelta(self.shift_offset), self.shift_end)

    @property
    def range_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


def schedule_issues(sched: Schedule) -> list[str]:
    """Contract checks of one schedule, for rows and for request bodies alike."""
    issues: list[str] = []
    if sched.end_date < sched.start_date:
        issues.append("RANGE_INVALID")
    elif sched.range_days > MAX_RANGE_DAYS:
        issues.append("RANGE_TOO_LONG")
    if sched.mode == MODE_FULL_DAY:
        if sched.shift_start is not None or sched.shift_end is not None or sched.shift_offset:
            issues.append("SHIFT_NOT_ALLOWED")
    elif sched.mode in SHIFT_MODES:
        if sched.shift_start is None or sched.shift_end is None:
            issues.append("SHIFT_REQUIRED")
        elif not shift_duration_valid(sched.shift_start, sched.shift_end, sched.shift_offset):
            issues.append("SHIFT_DURATION_INVALID")
    else:
        issues.append("MODE_INVALID")
    if any(d < sched.start_date or d > sched.end_date for d in sched.excluded):
        issues.append("EXCLUDED_DATE_OUT_OF_RANGE")
    return issues


def schedule_of(row: Mapping[str, object]) -> Schedule | None:
    """The parsed schedule of a stored assignment row; None when not exact."""
    mode = text(row.get("mode"))
    start, end = parse_date(row.get("start_date")), parse_date(row.get("end_date"))
    excluded = parse_dates(row.get("excluded_dates"))
    if mode not in MODES or start is None or end is None or excluded is None:
        return None
    if mode == MODE_FULL_DAY:
        if any(text(row.get(c)) for c in _SHIFT_FIELDS):
            return None
        return Schedule(mode, start, end, excluded=tuple(excluded))
    s, e, offset = parse_time(row.get("shift_start_time")), parse_time(row.get("shift_end_time")), \
        text(row.get("shift_end_day_offset"))
    if s is None or e is None or offset not in ("0", "1"):
        return None
    return Schedule(mode, start, end, s, e, int(offset), tuple(excluded))


def schedule_cells(sched: Schedule) -> dict[str, str]:
    shift = sched.mode in SHIFT_MODES
    return {
        "mode": sched.mode,
        "start_date": sched.start_date.isoformat(),
        "end_date": sched.end_date.isoformat(),
        "shift_start_time": sched.shift_start.strftime("%H:%M") if shift and sched.shift_start else "",
        "shift_end_time": sched.shift_end.strftime("%H:%M") if shift and sched.shift_end else "",
        "shift_end_day_offset": str(sched.shift_offset) if shift else "",
        "excluded_dates": format_dates(sched.excluded),
    }


# ---------------------------------------------------------------------------
# Row validation
# ---------------------------------------------------------------------------


def _blank(row: Mapping[str, object], name: str) -> bool:
    return not text(row.get(name)).strip()


def validate_row(row: Mapping[str, object]) -> list[str]:
    """Issue codes of ONE row against the per-kind matrix. Total: never raises."""
    kind = text(row.get("record_kind"))
    if kind not in RECORD_KINDS:
        return ["RECORD_KIND_INVALID"]
    issues: list[str] = []

    def required(*names: str) -> None:
        issues.extend(f"FIELD_REQUIRED:{n}" for n in names if _blank(row, n))

    def blank(*names: str) -> None:
        issues.extend(f"FIELD_MUST_BE_BLANK:{n}" for n in names if not _blank(row, n))

    required("record_id", "operation_id", "event_id", "vehicle_id", "recorded_by", "request_id")
    if text(row.get("entry_operation")) not in OPERATIONS:
        issues.append("ENTRY_OPERATION_INVALID")
    if not _INT.fullmatch(text(row.get("revision_no"))):
        issues.append("REVISION_NO_INVALID")
    if parse_aware(row.get("recorded_at")) is None:
        issues.append("RECORDED_AT_INVALID")
    if not _HEX64.fullmatch(text(row.get("request_fingerprint"))):
        issues.append("FINGERPRINT_INVALID")
    flag = text(row.get("is_test_data"))
    if flag not in ("TRUE", "FALSE"):
        issues.append("TEST_FLAG_INVALID")
    elif flag == "FALSE" and not _blank(row, "test_batch_id"):
        issues.append("SCOPE_INCONSISTENT")
    elif flag == "TRUE" and _blank(row, "test_batch_id"):
        issues.append("SCOPE_INCONSISTENT")
    first = text(row.get("revision_no")) == "1"
    if kind in (ASSIGNMENT, HANDOVER) and first:
        if text(row.get("event_id")) != text(row.get("record_id")):
            issues.append("EVENT_ID_MISMATCH")
        blank("supersedes_record_id")
    elif kind in (REVISION, CANCELLATION) or not first:
        if kind == ASSIGNMENT:
            issues.append("REVISION_NO_INVALID")
        required("supersedes_record_id")
        if kind in (REVISION, CANCELLATION) and first:
            issues.append("REVISION_NO_INVALID")
    if kind in (ASSIGNMENT, REVISION):
        required(*_ASSIGNMENT_FIELDS)
        blank(*_HANDOVER_FIELDS)
        sched = schedule_of(row)
        if sched is None:
            issues.append("SCHEDULE_INVALID")
        else:
            issues.extend(f"SCHEDULE:{i}" for i in schedule_issues(sched) if i != "RANGE_TOO_LONG")
        relation = text(row.get("relation"))
        if relation and relation not in RELATIONS:
            issues.append("RELATION_INVALID")
        if bool(relation) != bool(text(row.get("related_event_id"))):
            issues.append("RELATION_INCONSISTENT")
        if text(row.get("early_end_at")) and parse_aware(row.get("early_end_at")) is None:
            issues.append("EARLY_END_AT_INVALID")
        if text(row.get("voided")) not in ("", TRUE):
            issues.append("VOIDED_INVALID")
        blank("unknown_start_at", "unknown_end_at")
    elif kind == HANDOVER:
        required(*_HANDOVER_FIELDS)
        blank(*_ASSIGNMENT_FIELDS[1:], *_SHIFT_FIELDS, "excluded_dates", "related_event_id", "relation",
              "early_end_at", "voided")
        if text(row.get("handover_kind")) not in HANDOVER_KINDS:
            issues.append("HANDOVER_KIND_INVALID")
        for name in ("predecessor_revision_no", "successor_revision_no"):
            if not _INT.fullmatch(text(row.get(name))):
                issues.append(f"FIELD_INVALID:{name}")
        if parse_aware(row.get("handover_at")) is None:
            issues.append("HANDOVER_AT_INVALID")
        has_start, has_end = not _blank(row, "unknown_start_at"), not _blank(row, "unknown_end_at")
        if has_start != has_end:
            issues.append("UNKNOWN_INTERVAL_INVALID")
        elif has_start:
            us, ue = parse_aware(row.get("unknown_start_at")), parse_aware(row.get("unknown_end_at"))
            if us is None or ue is None or not us < ue:
                issues.append("UNKNOWN_INTERVAL_INVALID")
    else:  # CANCELLATION
        blank(*_ASSIGNMENT_FIELDS[1:], *_SHIFT_FIELDS, *_HANDOVER_FIELDS, "excluded_dates", "related_event_id",
              "relation", "early_end_at", "voided", "unknown_start_at", "unknown_end_at")
        required("reason_th")
    return issues


# ---------------------------------------------------------------------------
# Derived model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Interval:
    event_id: str
    revision_no: str
    vehicle_id: str
    driver_id: str
    mode: str
    label_date: date
    start: datetime
    end: datetime


@dataclass
class AssignmentState:
    event_id: str
    vehicle_id: str
    revision_no: str
    head_record_id: str
    head: Mapping[str, object]
    schedule: Schedule
    driver_id: str
    lifecycle: str
    early_end_at: datetime | None
    related_event_id: str
    relation: str
    records: list[Mapping[str, object]] = field(default_factory=list)


@dataclass
class HandoverState:
    event_id: str
    vehicle_id: str
    revision_no: str
    head_record_id: str
    head: Mapping[str, object]
    kind: str
    predecessor_event_id: str
    predecessor_revision_no: str
    successor_event_id: str
    successor_revision_no: str
    handover_at: datetime
    unknown: tuple[datetime, datetime] | None
    in_force: bool
    records: list[Mapping[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class Conflict:
    axis: str  # VEHICLE | DRIVER
    key: str  # the vehicle_id or driver_id
    first: Interval
    second: Interval


@dataclass
class Model:
    """The derived E2 state of a set of in-scope rows (one or many vehicles)."""

    status: str
    issue_counts: dict[str, int]
    assignments: dict[str, AssignmentState]
    handovers: dict[str, HandoverState]
    intervals: list[Interval]
    unknown: list[tuple[str, datetime, datetime, str]]  # (vehicle_id, start, end, handover event_id)
    conflicts: list[Conflict]

    def intervals_of(self, event_id: str) -> list[Interval]:
        return [i for i in self.intervals if i.event_id == event_id]

    def handovers_of(self, event_id: str) -> list[HandoverState]:
        return [h for h in self.handovers.values() if h.in_force
                and event_id in (h.predecessor_event_id, h.successor_event_id)]

    def vehicle_status(self, vehicle_id: str) -> str:
        if any(c.axis == "VEHICLE" and c.key == vehicle_id for c in self.conflicts):
            return STATUS_CONFLICTED
        return STATUS_VALID


def _invalid(issues: dict[str, int]) -> Model:
    return Model(STATUS_INVALID, dict(sorted(issues.items())), {}, {}, [], [], [])


def _chains(rows: Sequence[Mapping[str, object]], issues: dict[str, int]) -> dict[str, list[Mapping[str, object]]]:
    by_event: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        by_event.setdefault(text(row.get("event_id")), []).append(row)
    chains: dict[str, list[Mapping[str, object]]] = {}
    for event_id, chain in by_event.items():
        chain = sorted(chain, key=lambda r: int(text(r.get("revision_no"))))
        ok = [int(text(r.get("revision_no"))) for r in chain] == list(range(1, len(chain) + 1))
        ok = ok and len({text(r.get("vehicle_id")) for r in chain}) == 1
        for prev, nxt in zip(chain, chain[1:]):
            if text(nxt.get("supersedes_record_id")) != text(prev.get("record_id")):
                ok = False
            if text(prev.get("record_kind")) == CANCELLATION:
                ok = False  # nothing follows a terminal cancellation
        root = text(chain[0].get("record_kind"))
        family = (ASSIGNMENT, REVISION) if root == ASSIGNMENT else (HANDOVER,) if root == HANDOVER else ()
        if not family:
            ok = False
        for r in chain[1:]:
            if text(r.get("record_kind")) not in (*family, CANCELLATION) or text(r.get("record_kind")) == ASSIGNMENT:
                ok = False
        if not ok:
            issues["EVENT_CHAIN_INVALID"] = issues.get("EVENT_CHAIN_INVALID", 0) + 1
            continue
        chains[event_id] = chain
    return chains


def _assignment(event_id: str, chain: list[Mapping[str, object]]) -> AssignmentState:
    last = chain[-1]
    state_row = last if text(last.get("record_kind")) != CANCELLATION else chain[-2]
    sched = schedule_of(state_row)
    assert sched is not None  # rows were validated
    lifecycle = LIFECYCLE_CANCELLED if text(last.get("record_kind")) == CANCELLATION else (
        LIFECYCLE_VOIDED if text(state_row.get("voided")) == TRUE else LIFECYCLE_ACTIVE)
    return AssignmentState(
        event_id=event_id, vehicle_id=text(state_row.get("vehicle_id")), revision_no=text(last.get("revision_no")),
        head_record_id=text(last.get("record_id")), head=state_row, schedule=sched,
        driver_id=text(state_row.get("driver_id")), lifecycle=lifecycle,
        early_end_at=parse_aware(state_row.get("early_end_at")) if text(state_row.get("early_end_at")) else None,
        related_event_id=text(state_row.get("related_event_id")), relation=text(state_row.get("relation")),
        records=list(chain),
    )


def _handover(event_id: str, chain: list[Mapping[str, object]]) -> HandoverState:
    last = chain[-1]
    in_force = text(last.get("record_kind")) != CANCELLATION
    state_row = last if in_force else chain[-2]
    unknown = None
    if text(state_row.get("unknown_start_at")):
        unknown = (parse_aware(state_row.get("unknown_start_at")), parse_aware(state_row.get("unknown_end_at")))
    at = parse_aware(state_row.get("handover_at"))
    assert at is not None
    return HandoverState(
        event_id=event_id, vehicle_id=text(state_row.get("vehicle_id")), revision_no=text(last.get("revision_no")),
        head_record_id=text(last.get("record_id")), head=state_row, kind=text(state_row.get("handover_kind")),
        predecessor_event_id=text(state_row.get("predecessor_event_id")),
        predecessor_revision_no=text(state_row.get("predecessor_revision_no")),
        successor_event_id=text(state_row.get("successor_event_id")),
        successor_revision_no=text(state_row.get("successor_revision_no")),
        handover_at=at, unknown=unknown, in_force=in_force, records=list(chain),  # type: ignore[arg-type]
    )


def handover_structure_issue(kind: str, pred: AssignmentState, succ: AssignmentState,
                             handover_at: datetime) -> str | None:
    """None when (pred, succ, handover_at) is a valid H2 / E2-H3 boundary on
    the STORED schedules (A2-4.4 / A2-4.5): same vehicle, the exact modes and
    dates, the exact applied instant and a non-empty derived interval for the
    clipped side."""
    p, s = pred.schedule, succ.schedule
    if pred.vehicle_id != succ.vehicle_id or pred.event_id == succ.event_id:
        return "HANDOVER_PARTIES_INVALID"
    if kind == HANDOVER_H2:
        if p.mode != MODE_FULL_DAY or s.mode != MODE_NIGHT_SHIFT or s.start_date != p.end_date:
            return "HANDOVER_NOT_PERMITTED"
        night_start, _ = s.unit(s.start_date)
        last_start, _ = p.unit(p.end_date)
        if handover_at != night_start:
            return "HANDOVER_INSTANT_INVALID"
        if not last_start < handover_at:
            return "HANDOVER_EMPTY_INTERVAL"
        return None
    if kind == HANDOVER_H3:
        if p.mode != MODE_NIGHT_SHIFT or s.mode != MODE_FULL_DAY or s.start_date != p.end_date + timedelta(1):
            return "HANDOVER_NOT_PERMITTED"
        if p.shift_offset != 1:
            return "HANDOVER_NOT_PERMITTED"
        _, night_end = p.unit(p.end_date)
        first_start, first_end = s.unit(s.start_date)
        if handover_at != night_end:
            return "HANDOVER_INSTANT_INVALID"
        if not first_start < handover_at < first_end:
            return "HANDOVER_EMPTY_INTERVAL"
        return None
    return "HANDOVER_KIND_INVALID"


def handover_displaced(kind: str, pred: AssignmentState, succ: AssignmentState,
                       handover_at: datetime) -> tuple[datetime, datetime]:
    """The time the handover moved from one side to the other: H2 — the
    predecessor's last-day time from the night start; E2-H3 — the successor's
    first-day time before the night ends."""
    if kind == HANDOVER_H2:
        return handover_at, pred.schedule.unit(pred.schedule.end_date)[1]
    return succ.schedule.unit(succ.schedule.start_date)[0], handover_at


def handover_gives(h: HandoverState, event_id: str) -> bool:
    """True when `event_id` is the side that GAVE time to the other at this
    handover: the H2 predecessor (ends at the instant) or the E2-H3 successor
    (starts at it)."""
    return (h.kind == HANDOVER_H2 and h.predecessor_event_id == event_id) or (
        h.kind == HANDOVER_H3 and h.successor_event_id == event_id)


def assignment_intervals(a: AssignmentState, handovers: Iterable[HandoverState]) -> list[Interval]:
    """The derived effective units of one assignment (empty when cancelled or
    voided), after in-force handover clips, the early end and — for the side
    that gave time at a handover — the handover's UNKNOWN span, so elapsed
    time is never silently given back to it (A2-5.3)."""
    if a.lifecycle != LIFECYCLE_ACTIVE:
        return []
    clip_end: datetime | None = None
    clip_start: datetime | None = None
    withheld: list[tuple[datetime, datetime]] = []
    for h in handovers:
        if not h.in_force or not handover_gives(h, a.event_id):
            continue
        if h.kind == HANDOVER_H2:
            clip_end = h.handover_at  # nothing of the predecessor at or after the instant
        else:
            clip_start = h.handover_at  # nothing of the successor before the instant
        if h.unknown is not None:
            withheld.append(h.unknown)
    sched = a.schedule
    out: list[Interval] = []
    for day in sched.dates():
        start, end = sched.unit(day)
        if clip_end is not None:
            end = min(end, clip_end)
        if clip_start is not None:
            start = max(start, clip_start)
        if a.early_end_at is not None:
            end = min(end, a.early_end_at)
        if start >= end:
            continue
        for piece_start, piece_end in _subtract((start, end), withheld):
            out.append(Interval(a.event_id, a.revision_no, a.vehicle_id, a.driver_id, sched.mode, day, piece_start,
                                piece_end))
    return out


def _subtract(span: tuple[datetime, datetime], cover: Iterable[tuple[datetime, datetime]]
              ) -> list[tuple[datetime, datetime]]:
    pieces = [span]
    for cs, ce in sorted(cover):
        nxt: list[tuple[datetime, datetime]] = []
        for ps, pe in pieces:
            if ce <= ps or cs >= pe:
                nxt.append((ps, pe))
                continue
            if ps < cs:
                nxt.append((ps, cs))
            if ce < pe:
                nxt.append((ce, pe))
        pieces = nxt
    return pieces


def find_conflicts(intervals: Sequence[Interval]) -> list[Conflict]:
    """Every overlapping pair of derived intervals of DIFFERENT assignments on
    one vehicle, or for one driver (half-open: touching is not overlap)."""
    out: list[Conflict] = []
    for axis, key in (("VEHICLE", lambda i: i.vehicle_id), ("DRIVER", lambda i: i.driver_id)):
        groups: dict[str, list[Interval]] = {}
        for i in intervals:
            groups.setdefault(key(i), []).append(i)
        for k, items in sorted(groups.items()):
            items = sorted(items, key=lambda i: (i.start, i.end, i.event_id))
            for n, a in enumerate(items):
                for b in items[n + 1:]:
                    if b.start >= a.end:
                        break
                    if a.event_id != b.event_id:
                        out.append(Conflict(axis, k, a, b))
    return out


def adjacent_pairs(intervals: Sequence[Interval]) -> list[tuple[Interval, Interval]]:
    """Same-driver intervals of different assignments where one ends exactly
    when the other starts (the non-blocking rest/fitness warning, A2-4.2)."""
    out: list[tuple[Interval, Interval]] = []
    by_driver: dict[str, list[Interval]] = {}
    for i in intervals:
        by_driver.setdefault(i.driver_id, []).append(i)
    for items in by_driver.values():
        starts: dict[datetime, list[Interval]] = {}
        for i in items:
            starts.setdefault(i.start, []).append(i)
        for a in items:
            for b in starts.get(a.end, []):
                if a.event_id != b.event_id:
                    out.append((a, b))
    return out


def derive(rows: Sequence[Mapping[str, object]]) -> Model:
    """The derived model of in-scope rows. Total: never raises."""
    issues: dict[str, int] = {}
    for row in rows:
        for issue in validate_row(row):
            issues[issue] = issues.get(issue, 0) + 1
    if issues:
        return _invalid(issues)
    chains = _chains(rows, issues)
    if issues:
        return _invalid(issues)
    assignments = {e: _assignment(e, c) for e, c in chains.items() if text(c[0].get("record_kind")) == ASSIGNMENT}
    handovers = {e: _handover(e, c) for e, c in chains.items() if text(c[0].get("record_kind")) == HANDOVER}
    for a in assignments.values():
        if a.related_event_id and a.related_event_id not in assignments:
            issues["RELATED_EVENT_MISSING"] = issues.get("RELATED_EVENT_MISSING", 0) + 1
    roles: dict[tuple[str, str], int] = {}
    for h in handovers.values():
        pred, succ = assignments.get(h.predecessor_event_id), assignments.get(h.successor_event_id)
        if pred is None or succ is None or pred.vehicle_id != h.vehicle_id or succ.vehicle_id != h.vehicle_id:
            issues["HANDOVER_REFERENCE_INVALID"] = issues.get("HANDOVER_REFERENCE_INVALID", 0) + 1
            continue
        if not h.in_force:
            continue
        for role in (("PRED", h.predecessor_event_id), ("SUCC", h.successor_event_id)):
            roles[role] = roles.get(role, 0) + 1
        if (h.predecessor_revision_no, h.successor_revision_no) != (pred.revision_no, succ.revision_no):
            issues["HANDOVER_REVISION_STALE"] = issues.get("HANDOVER_REVISION_STALE", 0) + 1
        elif pred.lifecycle == LIFECYCLE_CANCELLED or succ.lifecycle == LIFECYCLE_CANCELLED:
            issues["HANDOVER_PARTY_CANCELLED"] = issues.get("HANDOVER_PARTY_CANCELLED", 0) + 1
        elif LIFECYCLE_VOIDED not in (pred.lifecycle, succ.lifecycle) and \
                handover_structure_issue(h.kind, pred, succ, h.handover_at) is not None:
            # a handover with a VOIDED party is frozen at its recorded instant (the
            # elapsed boundary stays; nothing is given back): only revisions are checked
            issues["HANDOVER_STRUCTURE_INVALID"] = issues.get("HANDOVER_STRUCTURE_INVALID", 0) + 1
    if any(n > 1 for n in roles.values()):
        issues["HANDOVER_DUPLICATE_ROLE"] = sum(n - 1 for n in roles.values() if n > 1)
    if issues:
        return _invalid(issues)
    by_event: dict[str, list[HandoverState]] = {}
    for h in handovers.values():
        for e in (h.predecessor_event_id, h.successor_event_id):
            by_event.setdefault(e, []).append(h)
    intervals = [i for a in assignments.values() for i in assignment_intervals(a, by_event.get(a.event_id, []))]
    intervals.sort(key=lambda i: (i.vehicle_id, i.start, i.event_id))
    unknown: list[tuple[str, datetime, datetime, str]] = []
    for h in handovers.values():
        if h.in_force and h.unknown is not None:
            cover = [(i.start, i.end) for i in intervals if i.vehicle_id == h.vehicle_id]
            unknown.extend((h.vehicle_id, s, e, h.event_id) for s, e in _subtract(h.unknown, cover))
    unknown.sort()
    conflicts = find_conflicts(intervals)
    status = STATUS_CONFLICTED if conflicts else STATUS_VALID
    return Model(status, {}, assignments, handovers, intervals, unknown, conflicts)

