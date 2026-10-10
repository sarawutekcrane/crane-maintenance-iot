"""R2 Batch R2f-f — Crane / Vehicle ↔ Driver RESPONSIBILITY periods: record
validation and timeline derivation (pure; no I/O).

A direct structural analogue of the accepted R2f-d caretaker timeline
(`caretaker_timeline`, itself the R1 branch-timeline model), with vehicle_id /
driver_id in place of equipment_id / technician_id, on a DEDICATED history tab
(`crane_driver_responsibility_history`, the ONLY responsibility authority). It
is NOT the Personnel ↔ Driver identity link (R2f-e) and NOT the Phase 6
`vehicle_driver` assignment history, which is never read. Rows are immutable
events; a correction or cancellation is a new revision of an existing logical
event (event_id / revision_no / supersedes_record_id), and a cancellation is
terminal. The current responsible driver is DERIVED from the in-force events
ordered by EFFECTIVE time, never from recorded order:

- ASSIGNMENT / TRANSFER or INSERTION: from its instant the responsible driver
  is `driver_id`; the previous period ends at that instant (derived).
- ASSIGNMENT / END: from its instant there is no responsible driver
  (`driver_id` blank; `recorded_from_driver_id` is the driver being ended).

Exclusivity: events at the same effective instant cannot be ordered, so the
timeline is AMBIGUOUS_ORDER (current UNDETERMINED, never "none"); any
structural defect is INVALID. There is no baseline (no vehicle_driver import)
and no projection: with no history the current responsible driver is none.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.registration import parse_aware, text

# The bounded vehicle_master read of the responsibility writes: the identity only.
VEHICLE_REFERENCE_TAB = "vehicle_master"
VEHICLE_REFERENCE_COLUMNS: tuple[str, ...] = ("vehicle_id",)
# The bounded driver_master read of R2f-f: the identity and the NEW-assignment
# eligibility status only — no name, phone, licence, expiry or note.
DRIVER_RESPONSIBILITY_REFERENCE_COLUMNS: tuple[str, ...] = ("driver_id", "active_status")

CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB = "crane_driver_responsibility_history"
CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS: tuple[str, ...] = (
    "record_id",
    "vehicle_id",
    "driver_id",
    "record_kind",
    "entry_operation",
    "event_id",
    "revision_no",
    "supersedes_record_id",
    "effective_at",
    "effective_precision",
    "effective_source",
    "recorded_from_driver_id",
    "recorded_from_source",
    "recorded_at",
    "recorded_by",
    "request_id",
    "request_fingerprint",
    "reason_th",
    "related_request_id",
    "is_test_data",
    "test_batch_id",
)

ASSIGNMENT = "ASSIGNMENT"
CORRECTION = "CORRECTION"
CANCELLATION = "CANCELLATION"
RECORD_KINDS = (ASSIGNMENT, CORRECTION, CANCELLATION)
OP_TRANSFER = "TRANSFER"
OP_INSERTION = "INSERTION"
OP_END = "END"
OP_CORRECTION = "CORRECTION"
OP_CANCELLATION = "CANCELLATION"
_ENTRY_OPERATIONS = {
    ASSIGNMENT: (OP_TRANSFER, OP_INSERTION, OP_END),
    CORRECTION: (OP_CORRECTION,),
    CANCELLATION: (OP_CANCELLATION,),
}

STATUS_VALID = "VALID"
STATUS_AMBIGUOUS = "AMBIGUOUS_ORDER"
STATUS_INVALID = "INVALID"

CURRENT_EVENT = "EVENT"  # a responsible driver from an in-force assignment
CURRENT_ENDED = "ENDED"  # the latest in-force event is an END
CURRENT_NONE = "NONE"  # no in-force event (no history, or all cancelled)
CURRENT_UNDETERMINED = "UNDETERMINED"  # same-instant tie: never reported as none

_HEX64 = re.compile(r"[0-9a-f]{64}")
_ASCII_INT = re.compile(r"[0-9]+")


def _blank(row: Mapping[str, object], name: str) -> bool:
    return not text(row.get(name)).strip()


def validate_responsibility_row(row: Mapping[str, object]) -> list[str]:
    """Issue codes for ONE row against the per-kind matrix. Total: never raises."""
    kind = text(row.get("record_kind"))
    if kind not in RECORD_KINDS:
        return ["RECORD_KIND_INVALID"]
    issues: list[str] = []

    def required(*names: str) -> None:
        issues.extend(f"FIELD_REQUIRED:{n}" for n in names if _blank(row, n))

    def must_be_blank(*names: str) -> None:
        issues.extend(f"FIELD_MUST_BE_BLANK:{n}" for n in names if not _blank(row, n))

    required("record_id", "vehicle_id", "event_id", "recorded_by", "request_id")
    if parse_aware(row.get("recorded_at")) is None:
        issues.append("RECORDED_AT_INVALID")
    if not _HEX64.fullmatch(text(row.get("request_fingerprint"))):
        issues.append("FINGERPRINT_INVALID")
    flag = text(row.get("is_test_data"))
    if flag not in ("TRUE", "FALSE"):
        issues.append("TEST_FLAG_INVALID")
    elif flag == "FALSE" and not _blank(row, "test_batch_id"):
        issues.append("SCOPE_INCONSISTENT")
    operation = text(row.get("entry_operation"))
    if operation not in _ENTRY_OPERATIONS[kind]:
        issues.append("ENTRY_OPERATION_INVALID")
    must_be_blank("related_request_id")  # no projection, so no reconciliation reference
    if kind in (ASSIGNMENT, CORRECTION):
        if parse_aware(row.get("effective_at")) is None:
            issues.append("EFFECTIVE_AT_INVALID")
        if text(row.get("effective_precision")) not in ("DATE", "DATETIME"):
            issues.append("EFFECTIVE_PRECISION_INVALID")
        if text(row.get("effective_source")) not in ("SERVER_NOW", "CLIENT"):
            issues.append("EFFECTIVE_SOURCE_INVALID")
        source = text(row.get("recorded_from_source"))
        if source not in ("EVENT", "NONE"):
            issues.append("RECORDED_FROM_SOURCE_INVALID")
        elif (source == "NONE") != _blank(row, "recorded_from_driver_id"):
            issues.append("RECORDED_FROM_DRIVER_INCONSISTENT")
    if kind == ASSIGNMENT:
        if text(row.get("event_id")) != text(row.get("record_id")):
            issues.append("ASSIGNMENT_IDENTITY_INVALID")
        if text(row.get("revision_no")) != "1":
            issues.append("REVISION_INVALID")
        must_be_blank("supersedes_record_id")
        if operation == OP_END:
            must_be_blank("driver_id")
            if _blank(row, "recorded_from_driver_id"):
                issues.append("END_WITHOUT_DRIVER")
        else:
            required("driver_id")
        if operation == OP_INSERTION and _blank(row, "reason_th"):
            issues.append("REASON_REQUIRED")
    if kind in (CORRECTION, CANCELLATION):
        required("supersedes_record_id", "reason_th")
        revision = text(row.get("revision_no"))
        if not (_ASCII_INT.fullmatch(revision) and int(revision) >= 2):
            issues.append("REVISION_INVALID")
    if kind == CANCELLATION:
        must_be_blank("driver_id", "effective_at", "effective_precision", "effective_source",
                      "recorded_from_driver_id", "recorded_from_source")
    return issues


@dataclass(frozen=True)
class ResponsibilityPeriod:
    event_id: str
    in_force: bool
    entry_operation: str  # of the ORIGINAL event: TRANSFER / INSERTION / END
    head_record_id: str
    revision_no: str
    driver_id: str | None  # None for an END event
    effective_at: str | None
    effective_precision: str | None
    derived_end_at: str | None
    recorded_at: str  # of the head revision
    recorded_by: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ResponsibilityTimeline:
    status: str  # VALID / AMBIGUOUS_ORDER / INVALID
    issue_counts: dict[str, int] = field(default_factory=dict)
    current_driver_id: str | None = None
    current_status: str = CURRENT_NONE
    current_since: str | None = None
    events: tuple[ResponsibilityPeriod, ...] = ()


def _instant(row: Mapping[str, object]) -> datetime:
    parsed = parse_aware(row.get("effective_at"))
    assert parsed is not None  # validated
    return parsed


def _none_if_blank(value: object) -> str | None:
    raw = text(value)
    return raw if raw.strip() else None


def derive_responsibility_timeline(records: Sequence[Mapping[str, object]]) -> ResponsibilityTimeline:
    """Validate and derive ONE vehicle's in-scope responsibility timeline."""
    issues: dict[str, int] = {}

    def count(code: str) -> None:
        issues[code] = issues.get(code, 0) + 1

    for row in records:
        for code in validate_responsibility_row(row):
            count(code)
    ids = [text(r.get("record_id")) for r in records]
    if len(ids) != len(set(ids)):
        count("RECORD_ID_DUPLICATE")
    request_ids = [text(r.get("request_id")) for r in records if text(r.get("request_id"))]
    if len(request_ids) != len(set(request_ids)):
        count("REQUEST_ID_DUPLICATE")
    if issues:
        return ResponsibilityTimeline(status=STATUS_INVALID, issue_counts=issues)

    by_id = {text(r.get("record_id")): r for r in records}
    revisions: dict[str, list[Mapping[str, object]]] = {}
    for row in records:
        if text(row.get("record_kind")) != ASSIGNMENT and (
            text(row.get("supersedes_record_id")) not in by_id or text(row.get("event_id")) not in by_id
        ):
            count("DANGLING_REFERENCE")
            continue
        revisions.setdefault(text(row.get("event_id")), []).append(row)
    heads: dict[str, Mapping[str, object]] = {}
    for event_id, revs in revisions.items():
        revs.sort(key=lambda r: int(text(r.get("revision_no"))))
        original = by_id[event_id]
        if text(original.get("record_kind")) != ASSIGNMENT:
            count("DANGLING_REFERENCE")
            continue
        numbers = [int(text(r.get("revision_no"))) for r in revs]
        if numbers != list(range(1, len(revs) + 1)) or any(
            text(revs[i].get("supersedes_record_id")) != text(revs[i - 1].get("record_id"))
            for i in range(1, len(revs))
        ):
            count("REVISION_FORK_OR_GAP")
            continue
        if any(text(r.get("record_kind")) == CANCELLATION for r in revs[:-1]):
            count("CANCELLATION_NOT_LAST")
            continue
        is_end = text(original.get("entry_operation")) == OP_END
        if any(text(r.get("record_kind")) == CORRECTION and (_blank(r, "driver_id") != is_end) for r in revs):
            count("CORRECTION_CHANGES_EVENT_NATURE")  # an END stays an END, an assignment stays one
            continue
        heads[event_id] = revs[-1]
    if issues:
        return ResponsibilityTimeline(status=STATUS_INVALID, issue_counts=issues)

    in_force = sorted(((eid, h) for eid, h in heads.items() if text(h.get("record_kind")) != CANCELLATION),
                      key=lambda pair: _instant(pair[1]))
    instants = [_instant(h) for _, h in in_force]
    tied = {i for i in instants if instants.count(i) > 1}

    def operation(event_id: str) -> str:
        return text(by_id[event_id].get("entry_operation"))

    periods: list[ResponsibilityPeriod] = []
    for index, (event_id, head) in enumerate(in_force):
        end = None if tied else (text(in_force[index + 1][1].get("effective_at")) if index + 1 < len(in_force) else None)
        periods.append(ResponsibilityPeriod(
            event_id=event_id, in_force=True, entry_operation=operation(event_id),
            head_record_id=text(head.get("record_id")), revision_no=text(head.get("revision_no")),
            driver_id=_none_if_blank(head.get("driver_id")), effective_at=text(head.get("effective_at")),
            effective_precision=text(head.get("effective_precision")), derived_end_at=end,
            recorded_at=text(head.get("recorded_at")), recorded_by=text(head.get("recorded_by")),
            notes=("SAME_INSTANT",) if _instant(head) in tied else (),
        ))
    for event_id, head in heads.items():
        if text(head.get("record_kind")) != CANCELLATION:
            continue
        revs = revisions[event_id]
        last_value = revs[-2]
        periods.append(ResponsibilityPeriod(
            event_id=event_id, in_force=False, entry_operation=operation(event_id),
            head_record_id=text(head.get("record_id")), revision_no=text(head.get("revision_no")),
            driver_id=_none_if_blank(last_value.get("driver_id")),
            effective_at=_none_if_blank(last_value.get("effective_at")),
            effective_precision=_none_if_blank(last_value.get("effective_precision")), derived_end_at=None,
            recorded_at=text(head.get("recorded_at")), recorded_by=text(head.get("recorded_by")),
            notes=("CANCELLED",),
        ))

    if tied:
        return ResponsibilityTimeline(status=STATUS_AMBIGUOUS, current_status=CURRENT_UNDETERMINED, events=tuple(periods))
    if not in_force:
        return ResponsibilityTimeline(status=STATUS_VALID, current_status=CURRENT_NONE, events=tuple(periods))
    latest = in_force[-1][1]
    driver = _none_if_blank(latest.get("driver_id"))
    return ResponsibilityTimeline(
        status=STATUS_VALID,
        current_driver_id=driver,
        current_status=CURRENT_EVENT if driver else CURRENT_ENDED,
        current_since=text(latest.get("effective_at")),
        events=tuple(periods),
    )


class ResponsibilityUndetermined(Exception):
    """The responsible driver just before an instant cannot be derived uniquely
    (a tie at the latest earlier instant). Never guessed: the caller refuses."""


def driver_before(timeline: ResponsibilityTimeline, instant: datetime, *,
                  exclude_event: str | None = None) -> tuple[str | None, str]:
    """(driver, source) in force just before `instant` from the in-force
    events other than `exclude_event`: the latest earlier event's driver
    (`EVENT`, None after an END), else (None, `NONE`)."""
    earlier: list[tuple[datetime, ResponsibilityPeriod]] = []
    for event in timeline.events:
        if not event.in_force or event.event_id == exclude_event:
            continue
        at = parse_aware(event.effective_at)
        if at is not None and at < instant:
            earlier.append((at, event))
    if not earlier:
        return None, "NONE"
    latest = max(at for at, _ in earlier)
    at_latest = [event for at, event in earlier if at == latest]
    if len(at_latest) != 1:
        raise ResponsibilityUndetermined()
    driver = at_latest[0].driver_id
    return (driver, "EVENT") if driver else (None, "NONE")


def in_force_instants(timeline: ResponsibilityTimeline, *, exclude_event: str | None = None) -> list[datetime]:
    out: list[datetime] = []
    for event in timeline.events:
        if event.in_force and event.event_id != exclude_event:
            at = parse_aware(event.effective_at)
            if at is not None:
                out.append(at)
    return out


def tied_event_ids(timeline: ResponsibilityTimeline) -> frozenset[str]:
    return frozenset(e.event_id for e in timeline.events if e.in_force and "SAME_INSTANT" in e.notes)


__all__ = [
    "ASSIGNMENT",
    "CANCELLATION",
    "CORRECTION",
    "CURRENT_ENDED",
    "CURRENT_EVENT",
    "CURRENT_NONE",
    "CURRENT_UNDETERMINED",
    "CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS",
    "CRANE_DRIVER_RESPONSIBILITY_HISTORY_TAB",
    "DRIVER_RESPONSIBILITY_REFERENCE_COLUMNS",
    "VEHICLE_REFERENCE_COLUMNS",
    "VEHICLE_REFERENCE_TAB",
    "OP_CANCELLATION",
    "OP_CORRECTION",
    "OP_END",
    "OP_INSERTION",
    "OP_TRANSFER",
    "STATUS_AMBIGUOUS",
    "STATUS_INVALID",
    "STATUS_VALID",
    "ResponsibilityPeriod",
    "ResponsibilityTimeline",
    "ResponsibilityUndetermined",
    "driver_before",
    "derive_responsibility_timeline",
    "in_force_instants",
    "tied_event_ids",
    "validate_responsibility_row",
]
