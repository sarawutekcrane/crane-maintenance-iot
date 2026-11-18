"""R8 early workstream — Crew Assignment Extension: record validation and
derivation (pure; no I/O; `now` is never read here).

Governance: Master Roadmap 2026-11-11 R8 addendum; DEC-R8-CREW-CALENDAR-20261111;
R8 Whole-Phase Owner source approval 2026-11-18 (OD-1 = A, OD-4 = A). The ONE
authority is the separate append-only, revisioned
`crane_crew_assignment_history`. It is NOT the E2 driver authority
(`crane_operational_driver_assignment_history`, whose header and derivation are
unchanged) and NOT R2f-f permanent responsibility. A crew record states that a
person is ASSIGNED to a vehicle's crew for a scheduled interval — never verified
attendance, actual work, a customer booking or dispatch.

Reuse (CC-11): the time contract is E2's own (C1 A2-3) — the same `Schedule`,
modes FULL_DAY / DAY_SHIFT / NIGHT_SHIFT with an explicit next-day end, Bangkok
labelled dates, half-open intervals stored as UTC — imported from
`operational_driver_timeline`, never re-implemented.

Logical events: one `event_id`, revisions 1..n; revision 1 is an ASSIGNMENT,
later rows are REVISIONs (a full new state) or one terminal CANCELLATION. The
vehicle and the person of an event never change (OD-4: a substitution is an
EARLY_END / CANCEL plus a new CREATE). Roles (OD-1): RIGGER, SIGNALMAN, OTHER;
OTHER needs a Thai role note, the others take none. A role is display data only:
no crew master, eligibility or certification rule is read or implied.

Any structural defect is INVALID (the service answers 500, never a partial or
empty list).
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG
from app.domain.operational_driver_timeline import (
    ASSIGNMENT,
    CANCELLATION,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_CANCELLED,
    OP_CANCEL,
    OP_CREATE,
    OP_EARLY_END,
    OP_REVISE,
    REVISION,
    STATUS_INVALID,
    STATUS_VALID,
    Schedule,
    schedule_issues,
    schedule_of,
)
from app.domain.registration import parse_aware, text

CREW_ASSIGNMENT_HISTORY_TAB = "crane_crew_assignment_history"
CREW_ASSIGNMENT_HISTORY_COLUMNS: tuple[str, ...] = (
    "record_id",
    "operation_id",
    "record_kind",
    "entry_operation",
    "event_id",
    "revision_no",
    "supersedes_record_id",
    "vehicle_id",
    "personnel_id",
    "crew_role",
    "crew_role_note_th",
    "mode",
    "start_date",
    "end_date",
    "shift_start_time",
    "shift_end_time",
    "shift_end_day_offset",
    "excluded_dates",
    "early_end_at",
    "reason_th",
    "recorded_at",
    "recorded_by",
    "request_id",
    "request_fingerprint",
    "is_test_data",
    "test_batch_id",
)

ROLE_RIGGER = "RIGGER"
ROLE_SIGNALMAN = "SIGNALMAN"
ROLE_OTHER = "OTHER"
CREW_ROLES: tuple[str, ...] = (ROLE_RIGGER, ROLE_SIGNALMAN, ROLE_OTHER)
MAX_ROLE_NOTE_LENGTH = 200

RECORD_KINDS: tuple[str, ...] = (ASSIGNMENT, REVISION, CANCELLATION)
OPERATIONS: tuple[str, ...] = (OP_CREATE, OP_REVISE, OP_CANCEL, OP_EARLY_END)

_HEX64 = re.compile(r"[0-9a-f]{64}")
_INT = re.compile(r"[1-9][0-9]*")
_REQUIRED = ("record_id", "operation_id", "record_kind", "entry_operation", "event_id", "revision_no", "vehicle_id",
             "recorded_at", "recorded_by", "request_id", "request_fingerprint")
_STATE = ("personnel_id", "crew_role", "mode", "start_date", "end_date")
_STATE_ONLY = ("personnel_id", "crew_role", "crew_role_note_th", "mode", "start_date", "end_date",
               "shift_start_time", "shift_end_time", "shift_end_day_offset", "excluded_dates", "early_end_at")


@dataclass(frozen=True)
class CrewInterval:
    event_id: str
    revision_no: str
    vehicle_id: str
    personnel_id: str
    role: str
    role_note_th: str
    mode: str
    label_date: date
    start: datetime
    end: datetime


@dataclass
class CrewState:
    event_id: str
    vehicle_id: str
    personnel_id: str
    role: str
    role_note_th: str
    revision_no: str
    head_record_id: str
    schedule: Schedule
    lifecycle: str
    early_end_at: datetime | None
    records: list[Mapping[str, object]] = field(default_factory=list)


@dataclass
class CrewModel:
    status: str
    issue_counts: dict[str, int]
    assignments: dict[str, CrewState]
    intervals: list[CrewInterval]

    def intervals_of(self, event_id: str) -> list[CrewInterval]:
        return [i for i in self.intervals if i.event_id == event_id]


def role_issue(role: str, note: str) -> str | None:
    """OD-1: a known role code; OTHER needs a 1..200 character Thai note; RIGGER
    and SIGNALMAN take no note (no free-text role invented under a fixed code)."""
    if role not in CREW_ROLES:
        return "ROLE_INVALID"
    if role == ROLE_OTHER:
        if not note.strip() or len(note) > MAX_ROLE_NOTE_LENGTH:
            return "ROLE_NOTE_REQUIRED"
    elif note:
        return "ROLE_NOTE_NOT_ALLOWED"
    return None


def validate_crew_row(row: Mapping[str, object]) -> list[str]:
    """Structural issues of one stored crew row (empty = usable exactly)."""
    issues: list[str] = []
    for name in _REQUIRED:
        if not text(row.get(name)).strip():
            issues.append(f"{name.upper()}_BLANK")
    kind = text(row.get("record_kind"))
    if kind not in RECORD_KINDS:
        issues.append("RECORD_KIND_INVALID")
    if text(row.get("entry_operation")) not in OPERATIONS:
        issues.append("ENTRY_OPERATION_INVALID")
    if text(row.get("revision_no")) and not _INT.fullmatch(text(row.get("revision_no"))):
        issues.append("REVISION_NO_INVALID")
    if text(row.get("request_fingerprint")) and not _HEX64.fullmatch(text(row.get("request_fingerprint"))):
        issues.append("REQUEST_FINGERPRINT_INVALID")
    if text(row.get("recorded_at")) and parse_aware(row.get("recorded_at")) is None:
        issues.append("RECORDED_AT_INVALID")
    if text(row.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG):
        issues.append("TEST_FLAG_INVALID")
    if kind in (ASSIGNMENT, REVISION):
        for name in _STATE:
            if not text(row.get(name)).strip():
                issues.append(f"{name.upper()}_BLANK")
        issue = role_issue(text(row.get("crew_role")), text(row.get("crew_role_note_th")))
        if issue:
            issues.append(issue)
        sched = schedule_of(row)
        if sched is None:
            issues.append("SCHEDULE_INVALID")
        elif schedule_issues(sched):
            issues.append("SCHEDULE_INVALID")
        early = text(row.get("early_end_at"))
        if early and parse_aware(early) is None:
            issues.append("EARLY_END_AT_INVALID")
    elif kind == CANCELLATION:
        if any(text(row.get(name)) for name in _STATE_ONLY):
            issues.append("CANCELLATION_STATE_NOT_ALLOWED")
    return issues


def _state(event_id: str, chain: list[Mapping[str, object]]) -> CrewState:
    head = next(r for r in reversed(chain) if text(r.get("record_kind")) != CANCELLATION)
    sched = schedule_of(head)
    assert sched is not None
    early = text(head.get("early_end_at"))
    last = chain[-1]
    return CrewState(
        event_id=event_id,
        vehicle_id=text(head.get("vehicle_id")),
        personnel_id=text(head.get("personnel_id")),
        role=text(head.get("crew_role")),
        role_note_th=text(head.get("crew_role_note_th")),
        revision_no=text(last.get("revision_no")),
        head_record_id=text(last.get("record_id")),
        schedule=sched,
        lifecycle=LIFECYCLE_CANCELLED if text(last.get("record_kind")) == CANCELLATION else LIFECYCLE_ACTIVE,
        early_end_at=parse_aware(early) if early else None,
        records=list(chain),
    )


def crew_intervals(state: CrewState) -> list[CrewInterval]:
    """The derived effective units of one crew assignment (none when cancelled),
    cut by its early end; empty units are dropped."""
    if state.lifecycle != LIFECYCLE_ACTIVE:
        return []
    out: list[CrewInterval] = []
    for day in state.schedule.dates():
        start, end = state.schedule.unit(day)
        if state.early_end_at is not None:
            end = min(end, state.early_end_at)
        if start >= end:
            continue
        out.append(CrewInterval(state.event_id, state.revision_no, state.vehicle_id, state.personnel_id, state.role,
                                state.role_note_th, state.schedule.mode, day, start, end))
    return out


def derive_crew(rows: Sequence[Mapping[str, object]]) -> CrewModel:
    """The derived model of in-scope crew rows. Total: never raises."""
    issues: dict[str, int] = {}

    def bump(code: str) -> None:
        issues[code] = issues.get(code, 0) + 1

    for row in rows:
        for issue in validate_crew_row(row):
            bump(issue)
    if issues:
        return CrewModel(STATUS_INVALID, dict(sorted(issues.items())), {}, [])
    chains: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        chains.setdefault(text(row.get("event_id")), []).append(row)
    states: dict[str, CrewState] = {}
    for event_id, chain in chains.items():
        chain.sort(key=lambda r: int(text(r.get("revision_no"))))
        numbers = [int(text(r.get("revision_no"))) for r in chain]
        if numbers != list(range(1, len(chain) + 1)):
            bump("REVISION_CHAIN_INVALID")
            continue
        first = chain[0]
        if text(first.get("record_kind")) != ASSIGNMENT or text(first.get("record_id")) != event_id:
            bump("REVISION_CHAIN_INVALID")
            continue
        broken = False
        for prev, row in zip(chain, chain[1:]):
            kind = text(row.get("record_kind"))
            if kind == ASSIGNMENT or text(row.get("supersedes_record_id")) != text(prev.get("record_id")):
                broken = True
            if text(prev.get("record_kind")) == CANCELLATION:
                broken = True  # nothing follows a terminal cancellation
            if text(row.get("vehicle_id")) != text(first.get("vehicle_id")):
                broken = True
            if kind == REVISION and text(row.get("personnel_id")) != text(first.get("personnel_id")):
                broken = True  # OD-4: the person of an event never changes
        if broken:
            bump("REVISION_CHAIN_INVALID")
            continue
        states[event_id] = _state(event_id, chain)
    if issues:
        return CrewModel(STATUS_INVALID, dict(sorted(issues.items())), {}, [])
    intervals = [i for s in states.values() for i in crew_intervals(s)]
    intervals.sort(key=lambda i: (i.start, i.end, i.event_id))
    return CrewModel(STATUS_VALID, {}, states, intervals)


__all__ = [
    "CREW_ASSIGNMENT_HISTORY_COLUMNS",
    "CREW_ASSIGNMENT_HISTORY_TAB",
    "CREW_ROLES",
    "MAX_ROLE_NOTE_LENGTH",
    "ROLE_OTHER",
    "ROLE_RIGGER",
    "ROLE_SIGNALMAN",
    "CrewInterval",
    "CrewModel",
    "CrewState",
    "crew_intervals",
    "derive_crew",
    "role_issue",
    "validate_crew_row",
]
