"""Phase 7 Batch 7O2a — responsible-branch history: record validation, revision
token and timeline derivation (pure; no I/O).

Contract: Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2 §5 (per-kind
field matrix §5.1, validation §5.2, baseline §5.3, derivation §5.4, revision
§5.5) and §8.1 (data contexts). History records are append-only events; the
current branch is derived from the events in force, never from submission
order, and the imported master value is retained on the asset's first record.
Read-only in 7O2a: nothing here writes or decides a mutation.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.registration import DATA_CONTEXT_REAL, parse_aware, text

ASSET_BRANCH_HISTORY_COLUMNS: tuple[str, ...] = (
    # Observed in the prepared workbook (UNVERIFIED live); meanings fixed by §5.1.
    "assignment_id",
    "asset_type",
    "asset_id",
    "branch_id",
    "start_at",
    "end_at",
    "is_test_data",
    "test_batch_id",
    "note_th",
    # PROPOSED by the contract.
    "record_kind",
    "entry_operation",
    "event_id",
    "revision_no",
    "supersedes_record_id",
    "effective_precision",
    "effective_source",
    "recorded_from_branch_id",
    "recorded_from_source",
    "baseline_branch_id",
    "baseline_source",
    "reconciled_old_master_branch_id",
    "related_request_id",
    "recorded_at",
    "recorded_by",
    "request_id",
    "request_fingerprint",
)

ASSIGNMENT = "ASSIGNMENT"
CORRECTION = "CORRECTION"
CANCELLATION = "CANCELLATION"
PROJECTION_RECONCILIATION = "PROJECTION_RECONCILIATION"
RECORD_KINDS = (ASSIGNMENT, CORRECTION, CANCELLATION, PROJECTION_RECONCILIATION)
_ENTRY_OPERATIONS = {
    ASSIGNMENT: ("TRANSFER", "INSERTION"),
    CORRECTION: ("CORRECTION",),
    CANCELLATION: ("CANCELLATION",),
    PROJECTION_RECONCILIATION: ("PROJECTION_RECONCILIATION",),
}

STATUS_VALID = "VALID"
STATUS_AMBIGUOUS = "AMBIGUOUS_ORDER"
STATUS_INVALID = "INVALID"

CONSISTENCY_CONSISTENT = "CONSISTENT"
CONSISTENCY_NO_HISTORY = "NO_HISTORY"
CONSISTENCY_MISMATCH = "PROJECTION_MISMATCH"
CONSISTENCY_UNDETERMINED = "UNDETERMINED"

_HEX64 = re.compile(r"[0-9a-f]{64}")
_ASCII_INT = re.compile(r"[0-9]+")


def _blank(row: Mapping[str, object], name: str) -> bool:
    return not text(row.get(name)).strip()


def validate_branch_row(row: Mapping[str, object]) -> list[str]:
    """Issue codes for ONE row against the §5.1 per-kind matrix. Total: never
    raises for malformed cells."""
    kind = text(row.get("record_kind"))
    if not kind.strip():
        return ["LEGACY_ROW_UNCLASSIFIED"]
    if kind not in RECORD_KINDS:
        return ["RECORD_KIND_INVALID"]
    issues: list[str] = []

    def required(*names: str) -> None:
        issues.extend(f"FIELD_REQUIRED:{n}" for n in names if _blank(row, n))

    def must_be_blank(*names: str) -> None:
        issues.extend(f"FIELD_MUST_BE_BLANK:{n}" for n in names if not _blank(row, n))

    required("assignment_id", "asset_type", "asset_id", "recorded_by", "request_id")
    if text(row.get("asset_type")) not in ("VEHICLE", "EQUIPMENT"):
        issues.append("ASSET_TYPE_INVALID")
    if parse_aware(row.get("recorded_at")) is None:
        issues.append("RECORDED_AT_INVALID")
    if not _HEX64.fullmatch(text(row.get("request_fingerprint"))):
        issues.append("FINGERPRINT_INVALID")
    if text(row.get("is_test_data")) not in ("TRUE", "FALSE", ""):
        issues.append("TEST_FLAG_INVALID")
    if text(row.get("entry_operation")) not in _ENTRY_OPERATIONS[kind]:
        issues.append("ENTRY_OPERATION_INVALID")
    must_be_blank("end_at")
    if kind in (ASSIGNMENT, CORRECTION):
        required("event_id", "branch_id")
        if parse_aware(row.get("start_at")) is None:
            issues.append("EFFECTIVE_AT_INVALID")
        if text(row.get("effective_precision")) not in ("DATE", "DATETIME"):
            issues.append("EFFECTIVE_PRECISION_INVALID")
        if text(row.get("effective_source")) not in ("SERVER_NOW", "CLIENT"):
            issues.append("EFFECTIVE_SOURCE_INVALID")
        source = text(row.get("recorded_from_source"))
        if source not in ("EVENT", "BASELINE", "NONE"):
            issues.append("RECORDED_FROM_SOURCE_INVALID")
        elif (source == "NONE") != _blank(row, "recorded_from_branch_id"):
            issues.append("RECORDED_FROM_BRANCH_INCONSISTENT")
        must_be_blank("reconciled_old_master_branch_id", "related_request_id")
    if kind == ASSIGNMENT:
        if text(row.get("event_id")) != text(row.get("assignment_id")):
            issues.append("ASSIGNMENT_IDENTITY_INVALID")
        if text(row.get("revision_no")) != "1":
            issues.append("REVISION_INVALID")
        must_be_blank("supersedes_record_id")
        baseline_source = text(row.get("baseline_source"))
        if baseline_source not in ("", "IMPORTED_MASTER", "NONE"):
            issues.append("BASELINE_SOURCE_INVALID")
        elif (baseline_source == "IMPORTED_MASTER") == _blank(row, "baseline_branch_id") and baseline_source:
            issues.append("BASELINE_BRANCH_INCONSISTENT")
        elif not baseline_source and not _blank(row, "baseline_branch_id"):
            issues.append("BASELINE_BRANCH_INCONSISTENT")
        if text(row.get("entry_operation")) == "INSERTION" and _blank(row, "note_th"):
            issues.append("REASON_REQUIRED")
    if kind in (CORRECTION, CANCELLATION):
        required("event_id", "supersedes_record_id", "note_th")
        revision = text(row.get("revision_no"))
        # ASCII digits only: str.isdigit() also accepts e.g. "²", which int() refuses.
        if not (_ASCII_INT.fullmatch(revision) and int(revision) >= 2):
            issues.append("REVISION_INVALID")
        must_be_blank("baseline_branch_id", "baseline_source")
    if kind == CANCELLATION:
        must_be_blank(
            "branch_id", "start_at", "effective_precision", "effective_source",
            "recorded_from_branch_id", "recorded_from_source",
            "reconciled_old_master_branch_id", "related_request_id",
        )
    if kind == PROJECTION_RECONCILIATION:
        # branch_id = the projected value written (blank = none);
        # reconciled_old_master_branch_id = the value replaced (blank = was blank).
        required("note_th")
        must_be_blank(
            "event_id", "revision_no", "supersedes_record_id", "start_at", "effective_precision",
            "effective_source", "recorded_from_branch_id", "recorded_from_source",
            "baseline_branch_id", "baseline_source",
        )
    return issues


def history_revision(records: Sequence[Mapping[str, object]]) -> str:
    """BHR1 token: SHA-256 over the asset's in-scope records (every contract
    column, canonical JSON, sorted by assignment_id), first 20 hex characters.
    Any appended or hand-edited record changes it."""
    canonical = sorted(
        ({c: text(r.get(c)) for c in ASSET_BRANCH_HISTORY_COLUMNS} for r in records),
        key=lambda r: (r["assignment_id"], json.dumps(r, sort_keys=True, ensure_ascii=False)),
    )
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return f"BHR1-{digest[:20]}"


@dataclass(frozen=True)
class TimelineEvent:
    event_id: str
    in_force: bool
    head_record_id: str
    revision_no: str
    to_branch_id: str | None
    effective_at: str | None
    effective_precision: str | None
    derived_from_branch_id: str | None
    original_entry_from_branch_id: str | None
    original_entry_from_source: str | None
    head_entry_from_branch_id: str | None
    head_entry_from_source: str | None
    derived_end_at: str | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class BranchTimeline:
    status: str  # VALID / AMBIGUOUS_ORDER / INVALID
    revision: str
    issue_counts: dict[str, int] = field(default_factory=dict)
    current_branch_id: str | None = None
    current_source: str | None = None  # EVENT / BASELINE / IMPORTED_MASTER / NONE / UNDETERMINED
    consistency: str | None = None
    baseline_branch_id: str | None = None
    baseline_source: str | None = None
    has_baseline: bool = False
    events: tuple[TimelineEvent, ...] = ()
    records: tuple[Mapping[str, object], ...] = ()  # recorded order


def _ordered(records: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    epoch = datetime.fromisoformat("1970-01-01T00:00:00+00:00")

    def key(pair: tuple[int, Mapping[str, object]]) -> tuple[bool, datetime, int]:
        parsed = parse_aware(pair[1].get("recorded_at"))
        return (parsed is not None, parsed or epoch, pair[0])

    return [r for _, r in sorted(enumerate(records), key=key)]


def _none_if_blank(value: object) -> str | None:
    raw = text(value)
    return raw if raw.strip() else None


def derive_timeline(
    records: Sequence[Mapping[str, object]],
    *,
    master_branch_id: str | None,
    master_available: bool,
    context: str,
) -> BranchTimeline:
    """Validate and derive one asset's timeline from its records (physical
    order). `master_branch_id` is the master cell (None = blank);
    `master_available` False when the column is not in the master schema."""
    issues: dict[str, int] = {}

    def count(code: str) -> None:
        issues[code] = issues.get(code, 0) + 1

    revision = history_revision(records)
    for row in records:
        # REAL: only FALSE rows are real data; a TRUE or blank row fails closed (§8.1).
        if context == DATA_CONTEXT_REAL and text(row.get("is_test_data")) != "FALSE":
            count("CUTOVER_INCOMPLETE")
    for row in records:
        for code in validate_branch_row(row):
            count(code)
    ids = [text(r.get("assignment_id")) for r in records]
    if len(ids) != len(set(ids)):
        count("RECORD_ID_DUPLICATE")
    request_ids = [text(r.get("request_id")) for r in records if text(r.get("request_id"))]
    if len(request_ids) != len(set(request_ids)):
        count("REQUEST_ID_DUPLICATE")
    ordered = _ordered(records)
    baselines = {
        (text(r.get("baseline_branch_id")), text(r.get("baseline_source")))
        for r in records
        if text(r.get("baseline_source"))
    }
    if len(baselines) > 1:
        count("BASELINE_CONFLICT")
    if ordered and not text(ordered[0].get("baseline_source")):
        count("BASELINE_MISSING")
    # §5.1 matrix: baseline fields are required on the asset's first record
    # (recorded order) only and must be blank on every later record, even when
    # they repeat the same baseline. CORRECTION/CANCELLATION/RECONCILIATION
    # rows are already held to "blank" by validate_branch_row; this covers a
    # later ASSIGNMENT, using the matrix's FIELD_MUST_BE_BLANK vocabulary.
    for row in ordered[1:]:
        if text(row.get("record_kind")) == ASSIGNMENT:
            for name in ("baseline_branch_id", "baseline_source"):
                if not _blank(row, name):
                    count(f"FIELD_MUST_BE_BLANK:{name}")
    for row in records:
        related = text(row.get("related_request_id"))
        if text(row.get("record_kind")) == PROJECTION_RECONCILIATION and related and related not in request_ids:
            count("RELATED_REQUEST_DANGLING")
    if issues:
        return BranchTimeline(status=STATUS_INVALID, revision=revision, issue_counts=issues)

    by_id = {text(r.get("assignment_id")): r for r in records}
    revisions_by_event: dict[str, list[Mapping[str, object]]] = {}
    for row in records:
        kind = text(row.get("record_kind"))
        if kind == PROJECTION_RECONCILIATION:
            continue
        if kind != ASSIGNMENT and (
            text(row.get("supersedes_record_id")) not in by_id or text(row.get("event_id")) not in by_id
        ):
            count("DANGLING_REFERENCE")
            continue
        revisions_by_event.setdefault(text(row.get("event_id")), []).append(row)
    heads: dict[str, Mapping[str, object]] = {}
    for event_id, revs in revisions_by_event.items():
        revs.sort(key=lambda r: int(text(r.get("revision_no"))))  # integers: validated above
        if text(by_id[event_id].get("record_kind")) != ASSIGNMENT:
            count("DANGLING_REFERENCE")
            continue
        numbers = [int(text(r.get("revision_no"))) for r in revs]
        if numbers != list(range(1, len(revs) + 1)) or any(
            text(revs[i].get("supersedes_record_id")) != text(revs[i - 1].get("assignment_id"))
            for i in range(1, len(revs))
        ):
            count("REVISION_FORK_OR_GAP")
            continue
        if any(text(r.get("record_kind")) == CANCELLATION for r in revs[:-1]):
            count("CANCELLATION_NOT_LAST")
            continue
        heads[event_id] = revs[-1]
    if issues:
        return BranchTimeline(status=STATUS_INVALID, revision=revision, issue_counts=issues)

    baseline = next(iter(baselines)) if baselines else None
    baseline_branch = _none_if_blank(baseline[0]) if baseline else None

    def instant(row: Mapping[str, object]) -> datetime:
        parsed = parse_aware(row.get("start_at"))
        assert parsed is not None  # validated
        return parsed

    in_force = [(eid, h) for eid, h in heads.items() if text(h.get("record_kind")) != CANCELLATION]
    in_force.sort(key=lambda pair: instant(pair[1]))
    instants = [instant(h) for _, h in in_force]
    ambiguous = len(instants) != len(set(instants))
    tied = {i for i in instants if instants.count(i) > 1}

    events: list[TimelineEvent] = []
    previous = baseline_branch
    for index, (event_id, head) in enumerate(in_force):
        original = by_id[event_id]
        head_source = _none_if_blank(head.get("recorded_from_branch_id"))
        to_branch = text(head.get("branch_id"))
        if ambiguous:
            derived_from, derived_end = None, None
            notes: tuple[str, ...] = ("SAME_INSTANT",) if instant(head) in tied else ()
        else:
            derived_from = previous
            derived_end = text(in_force[index + 1][1].get("start_at")) if index + 1 < len(in_force) else None
            notes = tuple(
                code
                for code, applies in (("RECORDED_SOURCE_DIFFERS", head_source != previous), ("REDUNDANT", to_branch == previous))
                if applies
            )
        events.append(
            TimelineEvent(
                event_id=event_id,
                in_force=True,
                head_record_id=text(head.get("assignment_id")),
                revision_no=text(head.get("revision_no")),
                to_branch_id=to_branch,
                effective_at=text(head.get("start_at")),
                effective_precision=text(head.get("effective_precision")),
                derived_from_branch_id=derived_from,
                original_entry_from_branch_id=_none_if_blank(original.get("recorded_from_branch_id")),
                original_entry_from_source=_none_if_blank(original.get("recorded_from_source")),
                head_entry_from_branch_id=head_source,
                head_entry_from_source=_none_if_blank(head.get("recorded_from_source")),
                derived_end_at=derived_end,
                notes=notes,
            )
        )
        previous = to_branch
    for event_id, head in heads.items():
        if text(head.get("record_kind")) != CANCELLATION:
            continue
        revs = revisions_by_event[event_id]
        last_value = revs[-2] if len(revs) > 1 else revs[-1]
        original = by_id[event_id]
        events.append(
            TimelineEvent(
                event_id=event_id,
                in_force=False,
                head_record_id=text(head.get("assignment_id")),
                revision_no=text(head.get("revision_no")),
                to_branch_id=_none_if_blank(last_value.get("branch_id")),
                effective_at=_none_if_blank(last_value.get("start_at")),
                effective_precision=_none_if_blank(last_value.get("effective_precision")),
                derived_from_branch_id=None,
                original_entry_from_branch_id=_none_if_blank(original.get("recorded_from_branch_id")),
                original_entry_from_source=_none_if_blank(original.get("recorded_from_source")),
                head_entry_from_branch_id=None,
                head_entry_from_source=None,
                derived_end_at=None,
                notes=("CANCELLED",),
            )
        )

    if not records:
        current, source = master_branch_id, ("IMPORTED_MASTER" if master_branch_id else "NONE")
    elif ambiguous:
        current, source = None, "UNDETERMINED"
    elif in_force:
        current, source = text(in_force[-1][1].get("branch_id")), "EVENT"
    else:
        current, source = baseline_branch, ("BASELINE" if baseline_branch else "NONE")

    if not records:
        consistency = CONSISTENCY_NO_HISTORY
    elif ambiguous or not master_available:
        consistency = CONSISTENCY_UNDETERMINED
    else:
        consistency = CONSISTENCY_CONSISTENT if master_branch_id == current else CONSISTENCY_MISMATCH

    return BranchTimeline(
        status=STATUS_AMBIGUOUS if ambiguous else STATUS_VALID,
        revision=revision,
        current_branch_id=current,
        current_source=source,
        consistency=consistency,
        baseline_branch_id=baseline_branch,
        baseline_source=baseline[1] if baseline else None,
        has_baseline=baseline is not None,
        events=tuple(events),
        records=tuple(ordered),
    )


def vehicle_history_rows(rows: Sequence[Mapping[str, object]], vehicle_id: str) -> list[Mapping[str, object]]:
    """One vehicle's records, physical order: exact asset_id match. EQUIPMENT
    rows belong to equipment; any other asset_type (blank or malformed) with
    this asset_id IS returned, so validation reports it instead of hiding it."""
    return [
        r for r in rows
        if text(r.get("asset_id")) == vehicle_id and text(r.get("asset_type")) != "EQUIPMENT"
    ]


# ---------------------------------------------------------------------------
# Phase 7 Batch 7O2c — pure helpers for the branch mutations (additive; the
# 7O2a validation and derivation above are unchanged).
# ---------------------------------------------------------------------------


class SourceUndetermined(Exception):
    """The source just before an instant cannot be derived uniquely because the
    remaining earlier in-force events still contain a same-instant tie
    (review clarification C-c2). Never guessed: the caller refuses."""


def tied_event_ids(timeline: BranchTimeline) -> frozenset[str]:
    """The in-force events participating in a same-instant tie."""
    return frozenset(e.event_id for e in timeline.events if e.in_force and "SAME_INSTANT" in e.notes)


def source_before(
    timeline: BranchTimeline, instant: datetime, *, exclude_event: str | None = None
) -> tuple[str | None, str]:
    """(branch, source) derived just before `instant` from the in-force events
    other than `exclude_event`: the latest earlier event's destination
    (`EVENT`), else the baseline (`BASELINE`), else (`None`, `NONE`).
    Raises SourceUndetermined when more than one of those events sits at
    the LATEST earlier instant (C-c2: no tie-break, no recorded order, no
    master fallback). A tie at an older instant does not matter: a later,
    uniquely ordered event has established the branch since."""
    earlier: list[tuple[datetime, TimelineEvent]] = []
    for event in timeline.events:
        if not event.in_force or event.event_id == exclude_event:
            continue
        at = parse_aware(event.effective_at)
        if at is not None and at < instant:
            earlier.append((at, event))
    if earlier:
        latest_instant = max(at for at, _ in earlier)
        at_latest = [event for at, event in earlier if at == latest_instant]
        if len(at_latest) != 1:
            raise SourceUndetermined()
        return at_latest[0].to_branch_id, "EVENT"
    baseline = timeline.baseline_branch_id
    return (baseline, "BASELINE") if baseline else (None, "NONE")


def in_force_instants(timeline: BranchTimeline, *, exclude_event: str | None = None) -> list[datetime]:
    """The effective instants of the in-force events (optionally excluding one)."""
    out: list[datetime] = []
    for event in timeline.events:
        if event.in_force and event.event_id != exclude_event:
            at = parse_aware(event.effective_at)
            if at is not None:
                out.append(at)
    return out
