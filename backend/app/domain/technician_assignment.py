"""R2 Batch R2f-h1 — V2 Technician assignment core (Repair / PM work orders).

Authority (Final Contract C1 §12 / §13 / §21, Option A as governance-approved):
the EXISTING `repair_assignment` / `pm_work_assignment` tabs carry additive V2
columns; the EXISTING `repair_order` / `pm_work_order` tabs carry the additive
per-job `assignment_model` marker and the job's own scope flags. No separate V2
tab exists.

- Assignee identity (V2): `assignee_type=TECHNICIAN`, `assignee_id=technician_id`.
  `user_id` stays BLANK on every V2 row; it is never given a second meaning.
- Legacy rows (blank `assignee_type`) are never imported, converted, rewritten
  or reinterpreted; legacy `user_id` stays the opaque legacy string.
- Model separation: a job is legacy (blank marker) or TECHNICIAN_V2, fixed at
  creation. Legacy assignment routes refuse V2 jobs and the V2 routes refuse
  legacy jobs (409 ASSIGNMENT_MODEL_MISMATCH).
- Append-only sets: one V2 assignment write appends ONE set (exactly one
  PRIMARY plus zero or more COLLABORATORs) in ONE append request; every row of
  a set shares the client request id, recorded time, actor, fingerprint, reason
  and scope. Set COMPLETENESS is provable from the stored rows alone (H1-01):
  each record id is `<prefix>-<set digest>-<i>-<n>` — row i of a set of n rows,
  where the digest binds the job, the request id and every (role, technician)
  member in order. A missing, extra, moved or altered member row fails closed. A set is never ended in place: the current set is the set with the
  latest recorded time; a same-instant tie is AMBIGUOUS and never guessed. The
  legacy `ended_at` / `active_status` cells stay blank on V2 rows (a legacy
  reader therefore treats a V2 row as inactive: fail closed).
- Gate (C1 §7, the existing R2f-d BOTH-ACTIVE rule, same codes): every NEW
  assignee (not already in the current set) is a technician exactly once in the
  request's scope with active_status exactly ACTIVE, held by exactly one
  in-scope Personnel with active_status exactly ACTIVE.
- Recording on a V2 job: the management capability, or the authenticated actor
  resolves in scope User Account -> Personnel -> Technician to a member of the
  CURRENT set. No lifecycle gate applies to recording (owner decision PENDING).
- TEST / REAL (C1 §15): the job, its rows and every reference are proven in the
  server's scope. Live (non-mock) TEST V2 fails closed: no TEST-scoped live
  technician master exists.

Write order: capability (403) -> X-Request-Id (422) -> body (422) -> write
context (503) / live TEST (409) -> job locate (404) -> model (409) -> job scope
-> ONE validated assignment-tab read (extended headers proven) -> tab-wide and
job-level integrity -> persisted reference proof -> replay -> current set
(ambiguity) -> stale -> no-op -> gate per new assignee -> W1 (one append).
After W1 the only outcomes are success and TECHNICIAN_ASSIGNMENT_WRITE_FAILED;
nothing is retried or compensated.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from app.domain.authz import CAN_MANAGE_FINDING_REPAIR, CAN_MANAGE_REPAIR, require_capability

from app.domain.equipment_caretaker import reference_issues
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG, in_scope
from app.domain.personnel_relationship import (
    PERSONNEL_PREFIX,
    PERSONNEL_TAB,
    RESOLVED,
    USER_ACCOUNT_PREFIX,
    USER_ACCOUNT_TAB,
    resolve_link,
    same_scope,
    scoped_personnel,
)
from app.domain.reference_read import reference_read
from app.domain.registration import DATA_CONTEXT_REAL, DATA_CONTEXT_TEST, text
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID, error, require_write_context
from app.domain.request_replay import canonical_json, find_replay, request_fingerprint
from app.domain.technician import read_technicians
from app.errors import ApiError
from app.repositories.base import ReferenceMasterRead, RegistryTableRead, Repository, RepositoryWriteError

if TYPE_CHECKING:
    from app.context import RequestContext

ASSIGNMENT_MODEL_LEGACY = ""
ASSIGNMENT_MODEL_TECHNICIAN_V2 = "TECHNICIAN_V2"
ASSIGNEE_TYPE_TECHNICIAN = "TECHNICIAN"
ROLE_PRIMARY = "PRIMARY"
ROLE_COLLABORATOR = "COLLABORATOR"
# R2 Batch R2f-h4 B6 (owner decision D2): the ONE row of a whole-set withdrawal
# event — assignee_type TECHNICIAN, assignee_id BLANK, record id
# `<prefix>-<digest>-1-1` over the member ("WITHDRAWAL", ""). Append-only like
# every V2 set; the previous set stays in history. No synthetic PRIMARY.
ROLE_WITHDRAWAL = "WITHDRAWAL"
ACTIVE = "ACTIVE"
MAX_REASON_LENGTH = 500

STATUS_NONE = "NONE"  # no V2 set recorded yet, or the latest event is a withdrawal (B6 D2)
STATUS_VALID = "VALID"
STATUS_AMBIGUOUS = "AMBIGUOUS"  # the latest sets share one recorded instant: never guessed

# The additive columns (C1 §21). Order is engineering; the live header order is
# authoritative for reads and appends (values follow the validated header).
V2_JOB_COLUMNS: tuple[str, ...] = ("assignment_model", "is_test_data", "test_batch_id")
V2_ASSIGNMENT_COLUMNS: tuple[str, ...] = (
    "assignee_type", "assignee_id", "request_id", "request_fingerprint", "reason_th", "is_test_data", "test_batch_id",
)


@dataclass(frozen=True)
class WorkKind:
    """One work-order domain: Repair or PM."""

    key: str
    label: str
    job_id_column: str
    record_id_column: str
    record_prefix: str
    assignment_tab: str
    legacy_assignment_columns: tuple[str, ...]
    fingerprint_op: str
    not_found_code: str

    @property
    def assignment_columns(self) -> tuple[str, ...]:
        return self.legacy_assignment_columns + V2_ASSIGNMENT_COLUMNS


REPAIR = WorkKind(
    key="REPAIR", label="Repair", job_id_column="repair_id", record_id_column="repair_assignment_id",
    record_prefix="RTA", assignment_tab="repair_assignment",
    legacy_assignment_columns=("repair_assignment_id", "repair_id", "user_id", "assignment_role", "assigned_at",
                               "assigned_by_user_id", "ended_at", "active_status", "note_th"),
    fingerprint_op="repair_technician_assignment", not_found_code="REPAIR_NOT_FOUND",
)
PM = WorkKind(
    key="PM", label="PM work order", job_id_column="pm_work_order_id", record_id_column="pm_assignment_id",
    record_prefix="PTA", assignment_tab="pm_work_assignment",
    legacy_assignment_columns=("pm_assignment_id", "pm_work_order_id", "user_id", "assignment_role", "assigned_at",
                               "assigned_by_user_id", "ended_at", "active_status", "note_th"),
    fingerprint_op="pm_technician_assignment", not_found_code="PM_WORK_ORDER_NOT_FOUND",
)
WORK_KINDS = {REPAIR.key: REPAIR, PM.key: PM}

ASSIGNMENT_PREFIX = "TECHNICIAN_ASSIGNMENT"
JOB_PREFIX = "TECHNICIAN_ASSIGNMENT_JOB"


# ---------------------------------------------------------------------------
# Server context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssignmentCutover:
    """The server's data context for Technician V2 (the only assignment model).
    `live` is True for every non-mock repository mode (live TEST V2 fails
    closed). R2 Batch R2f-h4 B6 Rev2: the former `enabled` cutover setting is
    removed (owner final decision: V2 only, no ON/OFF mode, no legacy creation);
    the type keeps its historical name."""

    data_context: str | None = None
    test_batch_id: str = ""
    live: bool = False


def cutover_from_settings(settings) -> AssignmentCutover:
    from app.config import DataRepositoryMode

    batch_id = settings.registry_test_batch_id
    mock = settings.data_repository == DataRepositoryMode.MOCK
    if mock and not batch_id.strip():
        batch_id = MOCK_TEST_BATCH_ID
    return AssignmentCutover(
        data_context=settings.registry_context_effective,
        test_batch_id=batch_id,
        live=not mock,
    )


def require_v2_context(cutover: AssignmentCutover) -> str:
    """The write context (503 when unconfigured), and live TEST refused (409)."""
    context = require_write_context(cutover.data_context, cutover.test_batch_id)
    if cutover.live and context == DATA_CONTEXT_TEST:
        raise error("TECHNICIAN_ASSIGNMENT_LIVE_TEST_UNSUPPORTED",
                    "V2 technician assignment is not available in the live TEST context: no TEST-scoped technician "
                    "master exists; nothing was changed", status.HTTP_409_CONFLICT)
    return context


def scope_cells(context: str, batch_id: str) -> dict[str, str]:
    return {"is_test_data": TEST_FLAG if context == DATA_CONTEXT_TEST else OPERATIONAL_FLAG,
            "test_batch_id": batch_id if context == DATA_CONTEXT_TEST else ""}


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------


def model_mismatch(expected: str, *, http_status: int = status.HTTP_409_CONFLICT) -> ApiError:
    actual = "LEGACY" if expected == ASSIGNMENT_MODEL_TECHNICIAN_V2 else ASSIGNMENT_MODEL_TECHNICIAN_V2
    return error("ASSIGNMENT_MODEL_MISMATCH",
                 f"This operation applies only to {'V2 technician' if expected else 'legacy'} assignment work orders",
                 http_status, {"expected_model": expected or "LEGACY", "actual_model": actual})


def require_r3_round_authority(kind: "WorkKind", job, context: "RequestContext | None", action: str) -> None:
    """R3 L8 (Owner decision): V2 assign / withdraw on an R3 Finding round needs BOTH
    `can_manage_repair` and `can_manage_finding_repair`. The round is identified only by
    the server-stored `finding_id` marker (TS-3), never by the request. Without a caller
    context the check fails closed. Non-R3 jobs are untouched (the route's capability)."""
    if kind is not REPAIR or not getattr(job, "finding_id", None):
        return
    if context is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"{action} on an R3 Finding round requires an authorized caller")
    for capability in (CAN_MANAGE_REPAIR, CAN_MANAGE_FINDING_REPAIR):
        require_capability(context, capability, f"{action} on an R3 Finding round")


def assignment_model_of(job) -> str:
    """Blank -> legacy; TECHNICIAN_V2 -> V2; anything else fails closed."""
    model = text(job.assignment_model)
    if model in (ASSIGNMENT_MODEL_LEGACY, ASSIGNMENT_MODEL_TECHNICIAN_V2):
        return model
    raise error("ASSIGNMENT_MODEL_DATA_INVALID", "The work order's assignment model is not recognized",
                status.HTTP_500_INTERNAL_SERVER_ERROR, {"issues": {"ASSIGNMENT_MODEL_UNKNOWN": 1}})


def require_legacy(job) -> None:
    if assignment_model_of(job) != ASSIGNMENT_MODEL_LEGACY:
        raise model_mismatch(ASSIGNMENT_MODEL_LEGACY)


def require_v2_job_in_scope(kind: WorkKind, job, context: str, batch_id: str) -> None:
    if assignment_model_of(job) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
        raise model_mismatch(ASSIGNMENT_MODEL_TECHNICIAN_V2)
    flags = {"is_test_data": text(job.is_test_data), "test_batch_id": text(job.test_batch_id)}
    if flags["is_test_data"] not in (TEST_FLAG, OPERATIONAL_FLAG) or (
        flags["is_test_data"] == OPERATIONAL_FLAG and flags["test_batch_id"]
    ):
        raise error("TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID", f"The {kind.label}'s scope flags are invalid",
                    status.HTTP_500_INTERNAL_SERVER_ERROR, {"issues": {"JOB_SCOPE_FLAG_INVALID": 1}})
    if not in_scope(flags, context, batch_id):
        raise error("TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH",
                    f"This {kind.label} does not belong to the request's data scope; nothing was changed",
                    status.HTTP_409_CONFLICT)


async def verify_job_schema(repository: Repository, kind: WorkKind) -> None:
    """The extended job header (assignment_model + scope flags) must exist
    before any V2 job write: a missing header fails closed with zero writes."""
    await reference_read(repository.verify_work_order_v2_schema(kind.key), JOB_PREFIX,
                         "repair_order" if kind is REPAIR else "pm_work_order")


async def v2_job_marker(repository: Repository, kind: WorkKind, cutover: AssignmentCutover) -> dict[str, str]:
    """For EVERY new job (B6 Rev2: V2 only): the context checks and the
    extended-header proof (before ANY write of the create path), then the
    marker cells the job is created with. There is no legacy fallback: a
    failed check fails the creation closed."""
    context = require_v2_context(cutover)
    await verify_job_schema(repository, kind)
    return {"assignment_model": ASSIGNMENT_MODEL_TECHNICIAN_V2, **scope_cells(context, cutover.test_batch_id)}


# ---------------------------------------------------------------------------
# Pure set derivation / validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssignmentSet:
    set_id: str  # the request id that wrote the set
    assigned_at: datetime
    assigned_by_user_id: str
    primary_technician_id: str
    collaborator_technician_ids: tuple[str, ...]
    reason_th: str
    record_ids: tuple[str, ...]

    @property
    def members(self) -> frozenset[str]:
        return frozenset((self.primary_technician_id, *self.collaborator_technician_ids))


@dataclass(frozen=True)
class AssignmentWithdrawal:
    """R2 Batch R2f-h4 B6 (D2): one recorded withdrawal of the whole current set."""

    withdrawal_id: str  # the request id that wrote it
    withdrawn_at: datetime
    withdrawn_by_user_id: str
    reason_th: str
    record_ids: tuple[str, ...]


@dataclass(frozen=True)
class AssignmentState:
    status: str
    current: AssignmentSet | None
    sets: tuple[AssignmentSet, ...]
    issues: dict[str, int] = field(default_factory=dict)
    withdrawals: tuple[AssignmentWithdrawal, ...] = ()


def is_v2_row(row: Mapping[str, object]) -> bool:
    return bool(text(row.get("assignee_type")).strip())


def set_digest(kind: WorkKind, job_id: str, request_id: str, members: Sequence[tuple[str, str]]) -> str:
    """H1-01: the digest every record id of a set carries — the job, the
    request id and the ordered (role, technician_id) members."""
    payload = {"op": kind.fingerprint_op, "job_id": job_id, "request_id": request_id,
               "members": [[role, technician_id] for role, technician_id in members]}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:32]


def record_id_for(kind: WorkKind, digest: str, index: int, size: int) -> str:
    return f"{kind.record_prefix}-{digest}-{index}-{size}"


def parse_record_id(kind: WorkKind, value: str) -> tuple[str, int, int] | None:
    """(digest, i, n) of a V2 record id, or None when it is not one."""
    match = re.fullmatch(rf"{re.escape(kind.record_prefix)}-([0-9a-f]{{32}})-([1-9][0-9]*)-([1-9][0-9]*)", value)
    if match is None or int(match.group(2)) > int(match.group(3)):
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def _instant(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _add(issues: dict[str, int], code: str, count: int = 1) -> None:
    issues[code] = issues.get(code, 0) + count


def tab_issues(kind: WorkKind, rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Tab-wide integrity of every V2 row (any job, any scope): record ids
    present, V2-prefixed and unique; a request id present and naming ONE job
    and ONE scope; scope flags exact."""
    issues: dict[str, int] = {}
    seen: dict[str, int] = {}
    groups: dict[str, set[tuple[str, str, str]]] = {}
    for row in rows:
        if not is_v2_row(row):
            continue
        record_id = text(row.get(kind.record_id_column))
        if parse_record_id(kind, record_id) is None:
            _add(issues, "RECORD_ID_INVALID")
        seen[record_id] = seen.get(record_id, 0) + 1
        request_id = text(row.get("request_id"))
        if not request_id.strip():
            _add(issues, "REQUEST_ID_BLANK")
            continue
        flag = text(row.get("is_test_data"))
        if flag not in (TEST_FLAG, OPERATIONAL_FLAG):
            _add(issues, "TEST_FLAG_INVALID")
        groups.setdefault(request_id, set()).add(
            (text(row.get(kind.job_id_column)), flag, text(row.get("test_batch_id"))))
    duplicates = sum(1 for count in seen.values() if count > 1)
    if duplicates:
        _add(issues, "DUPLICATE_RECORD_ID", duplicates)
    inconsistent = sum(1 for keys in groups.values() if len(keys) > 1)
    if inconsistent:
        _add(issues, "REQUEST_ID_INCONSISTENT", inconsistent)
    return issues


def derive_assignment_state(kind: WorkKind, job_id: str, rows: Sequence[Mapping[str, object]],
                            job_scope: Mapping[str, str]) -> AssignmentState:
    """The V2 sets of ONE V2 job from every row of the assignment tab. Any
    defect makes the state carry `issues` (the caller fails closed)."""
    issues = tab_issues(kind, rows)
    job_rows = [r for r in rows if text(r.get(kind.job_id_column)) == job_id]
    groups: dict[str, list[Mapping[str, object]]] = {}
    for row in job_rows:
        if not is_v2_row(row):
            _add(issues, "LEGACY_ROW_ON_V2_JOB")
            continue
        if text(row.get("assignee_type")) != ASSIGNEE_TYPE_TECHNICIAN:
            _add(issues, "ASSIGNEE_TYPE_INVALID")
        if text(row.get("assignment_role")) == ROLE_WITHDRAWAL:
            if text(row.get("assignee_id")):
                _add(issues, "WITHDRAWAL_ASSIGNEE_NOT_BLANK")
        elif not text(row.get("assignee_id")).strip():
            _add(issues, "ASSIGNEE_ID_BLANK")
        if text(row.get("user_id")):
            _add(issues, "V2_USER_ID_NOT_BLANK")
        if text(row.get("ended_at")) or text(row.get("active_status")):
            _add(issues, "V2_LEGACY_STATUS_NOT_BLANK")
        if text(row.get("assignment_role")) not in (ROLE_PRIMARY, ROLE_COLLABORATOR, ROLE_WITHDRAWAL):
            _add(issues, "ASSIGNMENT_ROLE_INVALID")
        if _instant(text(row.get("assigned_at"))) is None:
            _add(issues, "ASSIGNED_AT_INVALID")
        if not text(row.get("assigned_by_user_id")).strip() or not text(row.get("request_fingerprint")).strip():
            _add(issues, "AUDIT_FIELD_BLANK")
        if text(row.get("is_test_data")) != job_scope["is_test_data"] or \
                text(row.get("test_batch_id")) != job_scope["test_batch_id"]:
            _add(issues, "ROW_SCOPE_MISMATCH")
        if text(row.get("request_id")).strip():
            groups.setdefault(text(row.get("request_id")), []).append(row)

    sets: list[AssignmentSet] = []
    withdrawals: list[AssignmentWithdrawal] = []
    for set_id, members in groups.items():
        if any(text(r.get("assignment_role")) == ROLE_WITHDRAWAL for r in members):
            withdrawal = _withdrawal(kind, job_id, set_id, members)
            if withdrawal is None:
                _add(issues, "WITHDRAWAL_INVALID")
            else:
                withdrawals.append(withdrawal)
            continue
        uniform = {(text(r.get("assigned_at")), text(r.get("assigned_by_user_id")), text(r.get("request_fingerprint")),
                    text(r.get("reason_th"))) for r in members}
        if len(uniform) != 1:
            _add(issues, "SET_FIELDS_INCONSISTENT")
            continue
        primaries = [text(r.get("assignee_id")) for r in members if text(r.get("assignment_role")) == ROLE_PRIMARY]
        collaborators = [text(r.get("assignee_id")) for r in members
                         if text(r.get("assignment_role")) == ROLE_COLLABORATOR]
        if len(primaries) != 1:
            _add(issues, "SET_PRIMARY_COUNT_INVALID")
            continue
        if len({*primaries, *collaborators}) != len(primaries) + len(collaborators):
            _add(issues, "SET_DUPLICATE_ASSIGNEE")
            continue
        # H1-01: the stored rows must be exactly the n rows the set was written
        # with — same digest and size on every row, indices 1..n, and the digest
        # recomputed from the rows present (job, request id, ordered members).
        parsed = [parse_record_id(kind, text(r.get(kind.record_id_column))) for r in members]
        if any(p is None for p in parsed):
            _add(issues, "SET_COMPLETENESS_UNPROVEN")
            continue
        digests, sizes = {p[0] for p in parsed}, {p[2] for p in parsed}
        size = next(iter(sizes))
        if len(digests) != 1 or len(sizes) != 1 or sorted(p[1] for p in parsed) != list(range(1, size + 1)):
            _add(issues, "SET_INCOMPLETE")
            continue
        ordered = [row for _p, row in sorted(zip(parsed, members), key=lambda pair: pair[0][1])]
        if set_digest(kind, job_id, set_id, [(text(r.get("assignment_role")), text(r.get("assignee_id")))
                                             for r in ordered]) != next(iter(digests)):
            _add(issues, "SET_DIGEST_MISMATCH")
            continue
        if text(ordered[0].get("assignment_role")) != ROLE_PRIMARY:
            _add(issues, "SET_PRIMARY_COUNT_INVALID")
            continue
        members = ordered
        collaborators = [text(r.get("assignee_id")) for r in ordered[1:]]
        assigned_at = _instant(text(members[0].get("assigned_at")))
        if assigned_at is None:
            continue
        sets.append(AssignmentSet(
            set_id=set_id, assigned_at=assigned_at, assigned_by_user_id=text(members[0].get("assigned_by_user_id")),
            primary_technician_id=primaries[0], collaborator_technician_ids=tuple(collaborators),
            reason_th=text(members[0].get("reason_th")),
            record_ids=tuple(text(r.get(kind.record_id_column)) for r in members),
        ))
    sets.sort(key=lambda s: (s.assigned_at, s.set_id))
    withdrawals.sort(key=lambda w: (w.withdrawn_at, w.withdrawal_id))
    # B6 (D2): every withdrawal must withdraw a set — the latest event strictly
    # before it is a set — and must not share its recorded instant with any
    # other event (the order would then be unprovable). Anything else fails closed.
    events: list[tuple[datetime, str, AssignmentSet | AssignmentWithdrawal]] = sorted(
        [(s.assigned_at, s.set_id, s) for s in sets] + [(w.withdrawn_at, w.withdrawal_id, w) for w in withdrawals],
        key=lambda e: (e[0], e[1]))
    latest = events[-1][0] if events else None
    for w in withdrawals:
        if sum(1 for e in events if e[0] == w.withdrawn_at) > 1:
            if w.withdrawn_at != latest:
                _add(issues, "WITHDRAWAL_ORDER_AMBIGUOUS")
            continue  # at the latest instant: the state is AMBIGUOUS below
        before = [e for e in events if e[0] < w.withdrawn_at]
        if not before or not isinstance(before[-1][2], AssignmentSet):
            _add(issues, "WITHDRAWAL_WITHOUT_CURRENT_SET")
    if issues:
        return AssignmentState(status=STATUS_NONE, current=None, sets=tuple(sets), issues=issues,
                               withdrawals=tuple(withdrawals))
    if not events:
        return AssignmentState(status=STATUS_NONE, current=None, sets=())
    if sum(1 for e in events if e[0] == latest) > 1:
        return AssignmentState(status=STATUS_AMBIGUOUS, current=None, sets=tuple(sets), withdrawals=tuple(withdrawals))
    last = events[-1][2]
    if isinstance(last, AssignmentWithdrawal):
        # Withdrawn: the job has no current set (U1 NONE, out of My Work); history kept.
        return AssignmentState(status=STATUS_NONE, current=None, sets=tuple(sets), withdrawals=tuple(withdrawals))
    return AssignmentState(status=STATUS_VALID, current=last, sets=tuple(sets), withdrawals=tuple(withdrawals))


def _withdrawal(kind: WorkKind, job_id: str, request_id: str,
                members: Sequence[Mapping[str, object]]) -> AssignmentWithdrawal | None:
    """A withdrawal group is exactly ONE WITHDRAWAL row whose record id is
    `<prefix>-<digest>-1-1` with the digest over (job, request id,
    [("WITHDRAWAL", "")]) — H1-01 completeness, same as a set."""
    if len(members) != 1:
        return None
    row = members[0]
    parsed = parse_record_id(kind, text(row.get(kind.record_id_column)))
    if parsed is None or parsed[1:] != (1, 1) or text(row.get("assignee_id")):
        return None
    if parsed[0] != set_digest(kind, job_id, request_id, [(ROLE_WITHDRAWAL, "")]):
        return None
    withdrawn_at = _instant(text(row.get("assigned_at")))
    if withdrawn_at is None:
        return None
    return AssignmentWithdrawal(withdrawal_id=request_id, withdrawn_at=withdrawn_at,
                                withdrawn_by_user_id=text(row.get("assigned_by_user_id")),
                                reason_th=text(row.get("reason_th")),
                                record_ids=(text(row.get(kind.record_id_column)),))


def stored_technician_ids(kind: WorkKind, job_id: str, rows: Sequence[Mapping[str, object]]) -> set[str]:
    return {text(r.get("assignee_id")) for r in rows
            if text(r.get(kind.job_id_column)) == job_id and is_v2_row(r) and text(r.get("assignee_id")).strip()}


# ---------------------------------------------------------------------------
# Outcomes / reads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssignmentOutcome:
    request_id: str
    changed: bool = False
    replayed: bool = False
    record_ids: tuple[str, ...] = ()
    current: AssignmentSet | None = None


@dataclass(frozen=True)
class AssignmentRead:
    job_id: str
    assignment_model: str
    state: AssignmentState


@dataclass
class _Context:
    context: str
    job: object
    job_scope: dict[str, str]
    read: RegistryTableRead
    state: AssignmentState
    technicians: ReferenceMasterRead


def _data_invalid(issues: dict[str, int]) -> ApiError:
    return error(f"{ASSIGNMENT_PREFIX}_DATA_INVALID", "The V2 technician assignment history cannot be trusted; "
                 "nothing was changed", status.HTTP_500_INTERNAL_SERVER_ERROR, {"issues": dict(sorted(issues.items()))})


def _unprocessable(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY, details)


_OPEN = "OPEN"


def require_open_job(kind: WorkKind, job) -> None:
    """R2 Batch R2f-h4 B6 (owner decision D1): a work order that is not exactly
    OPEN accepts no assignment change — no new set and no withdrawal. Raised
    before any write; reads of its current set and history are unaffected."""
    job_status = getattr(job.status, "value", job.status)
    if text(job_status) != _OPEN:
        raise error(f"{ASSIGNMENT_PREFIX}_JOB_CLOSED",
                    f"This {kind.label} is not OPEN; its technician assignment cannot be changed and nothing was "
                    "changed", status.HTTP_409_CONFLICT, {"status": text(job_status)})


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TechnicianAssignmentService:
    def __init__(self, repository: Repository, cutover: AssignmentCutover) -> None:
        self._repository = repository
        self._cutover = cutover
        self._batch_id = cutover.test_batch_id

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def _job(self, kind: WorkKind, job_id: str):
        if kind is REPAIR:
            detail = await self._repository.get_repair(job_id)
            job = detail.repair if detail else None
        else:
            detail = await self._repository.get_pm_work_order(job_id)
            job = detail.work_order if detail else None
        if job is None:
            raise error(kind.not_found_code, f"{kind.label} '{job_id}' was not found", status.HTTP_404_NOT_FOUND)
        return job

    async def _rows(self, kind: WorkKind) -> RegistryTableRead:
        return await reference_read(self._repository.read_work_assignment_v2_rows(kind.key), ASSIGNMENT_PREFIX,
                                    kind.assignment_tab)

    async def _load(self, kind: WorkKind, job, context: str) -> _Context:
        job_scope = {"is_test_data": text(job.is_test_data), "test_batch_id": text(job.test_batch_id)}
        read = await self._rows(kind)
        job_id = getattr(job, kind.job_id_column)
        state = derive_assignment_state(kind, job_id, read.rows, job_scope)
        if state.issues:
            raise _data_invalid(state.issues)
        technicians = await read_technicians(self._repository)
        issues = reference_issues(stored_technician_ids(kind, job_id, read.rows), technicians,
                                  id_column="technician_id", label="TECHNICIAN", context=context,
                                  batch_id=self._batch_id)
        if issues:
            raise _data_invalid(issues)
        return _Context(context=context, job=job, job_scope=job_scope, read=read, state=state,
                        technicians=technicians)

    # ---------------------------------------------------------------- body

    @staticmethod
    def _assignees(body: Mapping[str, object]) -> tuple[str, list[str]]:
        primary = body.get("primary_technician_id")
        collaborators = body.get("collaborator_technician_ids") or []
        if not isinstance(primary, str) or not primary.strip():
            raise _unprocessable("TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED", "Exactly one primary technician_id is "
                                 "required", {"field": "primary_technician_id"})
        if not isinstance(collaborators, list) or any(not isinstance(c, str) or not c.strip() for c in collaborators):
            raise _unprocessable("VALIDATION_ERROR", "Every collaborator technician_id must be non-blank text",
                                 {"field": "collaborator_technician_ids"})
        if len({primary, *collaborators}) != 1 + len(collaborators):
            raise _unprocessable("TECHNICIAN_ASSIGNMENT_DUPLICATE_ASSIGNEE",
                                 "A technician may appear only once in an assignment set")
        return primary, list(collaborators)

    @staticmethod
    def _reason(body: Mapping[str, object]) -> str:
        reason = body.get("reason_th")
        if reason is None:
            return ""
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
            raise _unprocessable("REASON_REQUIRED", f"A reason, when given, must be 1-{MAX_REASON_LENGTH} characters")
        return reason

    @staticmethod
    def _expected(body: Mapping[str, object]) -> tuple[str, frozenset[str]] | None:
        expected = body.get("expected_current")
        if expected is None:
            return None
        if not isinstance(expected, Mapping):
            raise _unprocessable("VALIDATION_ERROR", "expected_current must be null or an assignment set")
        primary = text(expected.get("primary_technician_id"))
        collaborators = expected.get("collaborator_technician_ids") or []
        return primary, frozenset(text(c) for c in collaborators)

    # ---------------------------------------------------------------- gate

    async def _require_eligible(self, technician_id: str, ctx: _Context,
                                personnel: list[Mapping[str, object]]) -> None:
        """The C1 §7 BOTH-ACTIVE gate — the R2f-d rule and codes, unchanged."""
        exact = [r for r in ctx.technicians.rows if text(r.values.get("technician_id")) == technician_id]
        matches = [r for r in exact if same_scope(r, ctx.context, self._batch_id)]
        details = {"technician_id": technician_id}
        if len(matches) > 1:
            raise error("TECHNICIAN_ID_AMBIGUOUS", "More than one technician record has this technician_id",
                        status.HTTP_409_CONFLICT, {**details, "match_count": len(matches)})
        if not matches:
            if ctx.context != DATA_CONTEXT_REAL and (not ctx.technicians.test_scope_supported or exact):
                raise _unprocessable("TECHNICIAN_SCOPE_UNPROVEN",
                                     "This technician cannot be proven to belong to the request's data scope", details)
            raise _unprocessable("TECHNICIAN_NOT_FOUND", "No technician record has exactly this technician_id",
                                 details)
        if text(matches[0].values.get("active_status")) != ACTIVE:
            raise _unprocessable("TECHNICIAN_NOT_ACTIVE", "Only an ACTIVE technician can receive a new assignment",
                                 details)
        holders = [p for p in personnel if text(p.get("technician_id")) == technician_id]
        if not holders:
            raise _unprocessable("TECHNICIAN_PERSONNEL_UNRESOLVED",
                                 "No personnel record in this data scope is linked to this technician", details)
        if len(holders) > 1:
            raise error("TECHNICIAN_PERSONNEL_AMBIGUOUS",
                        "More than one personnel record is linked to this technician; nothing was changed",
                        status.HTTP_409_CONFLICT, {**details, "match_count": len(holders)})
        if text(holders[0].get("active_status")) != ACTIVE:
            raise _unprocessable("PERSONNEL_NOT_ACTIVE",
                                 "The personnel record linked to this technician is not ACTIVE", details)

    async def _personnel(self, context: str) -> list[Mapping[str, object]]:
        master = await reference_read(self._repository.read_personnel_relationship_master(), PERSONNEL_PREFIX,
                                      PERSONNEL_TAB)
        return scoped_personnel(master.rows, context, self._batch_id)

    # ---------------------------------------------------------------- write

    def _rows_for(self, kind: WorkKind, ctx: _Context, *, job_id: str, primary: str, collaborators: list[str],
                  request_id: str, fingerprint: str, user_id: str, reason: str) -> list[dict[str, str]]:
        assigned_at = self._now().isoformat(timespec="microseconds")
        members = [(ROLE_PRIMARY, primary), *((ROLE_COLLABORATOR, c) for c in collaborators)]
        digest = set_digest(kind, job_id, request_id, members)
        rows = []
        for index, (role, technician_id) in enumerate(members, start=1):
            row = dict.fromkeys(kind.assignment_columns, "")
            row.update({
                kind.record_id_column: record_id_for(kind, digest, index, len(members)),
                kind.job_id_column: job_id,
                "assignment_role": role,
                "assigned_at": assigned_at,
                "assigned_by_user_id": user_id,
                "assignee_type": ASSIGNEE_TYPE_TECHNICIAN,
                "assignee_id": technician_id,
                "request_id": request_id,
                "request_fingerprint": fingerprint,
                "reason_th": reason,
                **ctx.job_scope,
            })
            rows.append(row)
        return rows

    async def assign(self, kind: WorkKind, job_id: str, body: Mapping[str, object], *, request_id: str,
                     user_id: str, context: RequestContext | None = None) -> AssignmentOutcome:
        primary, collaborators = self._assignees(body)
        reason = self._reason(body)
        expected = self._expected(body)
        data_context = require_v2_context(self._cutover)
        job = await self._job(kind, job_id)
        require_r3_round_authority(kind, job, context, "การมอบหมายช่าง V2 (V2 technician assignment)")
        require_v2_job_in_scope(kind, job, data_context, self._batch_id)
        ctx = await self._load(kind, job, data_context)

        fingerprint = request_fingerprint(kind.fingerprint_op, job_id, None, body)
        hit = find_replay([r for r in ctx.read.rows if is_v2_row(r)], request_id, fingerprint,
                          record_id_column=kind.record_id_column)
        if hit is not None:
            if hit.replayed and all(text(r.get(kind.job_id_column)) == job_id for r in hit.rows):
                return AssignmentOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids)
            raise error("REQUEST_ID_REUSED", "This X-Request-Id was already used for a different change",
                        status.HTTP_409_CONFLICT, {"request_id": request_id})
        # B6 D1: after replay detection (a request applied while the job was OPEN
        # still replays), before every other check and before any write.
        require_open_job(kind, job)

        state = ctx.state
        if state.status == STATUS_AMBIGUOUS:
            raise error("TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", "The latest assignment sets were recorded at the same "
                        "instant; the current set cannot be determined and nothing was changed",
                        status.HTTP_409_CONFLICT)
        current = state.current
        current_key = (current.primary_technician_id, frozenset(current.collaborator_technician_ids)) \
            if current else None
        if expected != current_key:
            raise error("TECHNICIAN_ASSIGNMENT_STALE", "The current assignment set is not the one expected; reload "
                        "and retry", status.HTTP_409_CONFLICT, {"field": "expected_current"})
        if current_key == (primary, frozenset(collaborators)):
            return AssignmentOutcome(request_id=request_id, changed=False, current=current)

        newcomers = [t for t in (primary, *collaborators) if current is None or t not in current.members]
        if newcomers:
            personnel = await self._personnel(data_context)
            for technician_id in newcomers:
                await self._require_eligible(technician_id, ctx, personnel)

        rows = self._rows_for(kind, ctx, job_id=job_id, primary=primary, collaborators=collaborators,
                              request_id=request_id, fingerprint=fingerprint, user_id=user_id, reason=reason)
        after = derive_assignment_state(kind, job_id, [*ctx.read.rows, *rows], ctx.job_scope)
        if after.issues or after.status != STATUS_VALID or after.current is None or after.current.set_id != request_id:
            raise RuntimeError(f"generated V2 assignment set is invalid: {after.issues or after.status}")
        try:
            await self._repository.append_work_assignment_v2_rows(kind.key, ctx.read, rows)
        except RepositoryWriteError as exc:
            message = ("Google Sheets rejected the assignment write; nothing was changed by this request"
                       if exc.outcome == "rejected" else
                       "The assignment write outcome is unknown (the set may have been written); nothing was retried")
            raise error("TECHNICIAN_ASSIGNMENT_WRITE_FAILED", message, status.HTTP_503_SERVICE_UNAVAILABLE,
                        {"write_outcome": exc.outcome, "request_id": request_id}) from exc
        return AssignmentOutcome(request_id=request_id, changed=True, record_ids=tuple(r[kind.record_id_column]
                                                                                       for r in rows),
                                 current=after.current)

    # ---------------------------------------------------------------- withdrawal (B6 D2)

    async def withdraw(self, kind: WorkKind, job_id: str, body: Mapping[str, object], *, request_id: str,
                       user_id: str, context: RequestContext | None = None) -> AssignmentOutcome:
        """Withdraw the WHOLE current set of an OPEN V2 job (owner decision D2).

        Same discipline as `assign`: capability (route) -> X-Request-Id -> body
        -> context -> job -> R3 round authority (L8) -> model / scope -> ONE validated tab read + integrity
        and reference proof -> replay -> OPEN (D1) -> ambiguity -> stale
        (`expected_current` must equal the current set exactly; with no current
        set every withdrawal is stale) -> ONE append of ONE withdrawal row. The
        previous set is never ended, deleted or rewritten."""
        reason = self._reason(body)
        expected = self._expected(body)
        if expected is None:
            raise _unprocessable("VALIDATION_ERROR", "expected_current must be the current assignment set",
                                 {"field": "expected_current"})
        data_context = require_v2_context(self._cutover)
        job = await self._job(kind, job_id)
        require_r3_round_authority(kind, job, context, "การถอนการมอบหมายช่าง V2 (V2 technician withdrawal)")
        require_v2_job_in_scope(kind, job, data_context, self._batch_id)
        ctx = await self._load(kind, job, data_context)

        fingerprint = request_fingerprint(f"{kind.fingerprint_op}_withdrawal", job_id, None, body)
        hit = find_replay([r for r in ctx.read.rows if is_v2_row(r)], request_id, fingerprint,
                          record_id_column=kind.record_id_column)
        if hit is not None:
            if hit.replayed and all(text(r.get(kind.job_id_column)) == job_id for r in hit.rows):
                return AssignmentOutcome(request_id=request_id, replayed=True, record_ids=hit.record_ids)
            raise error("REQUEST_ID_REUSED", "This X-Request-Id was already used for a different change",
                        status.HTTP_409_CONFLICT, {"request_id": request_id})
        require_open_job(kind, job)
        if kind is REPAIR and getattr(job, "finding_id", None):
            # R3 L9 (Owner rule): an active R3 round never loses its PRIMARY through a
            # withdrawal; the lead is changed only by assigning a complete replacement set
            # (one atomic append, the earlier set kept as history).
            raise error(f"{ASSIGNMENT_PREFIX}_PRIMARY_REQUIRED_ON_R3_ROUND",
                        "An active R3 Finding round must keep a lead technician; assign a replacement team "
                        "instead of withdrawing. Nothing was changed", status.HTTP_409_CONFLICT,
                        {"job_id": job_id})

        state = ctx.state
        if state.status == STATUS_AMBIGUOUS:
            raise error("TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", "The latest assignment events were recorded at the "
                        "same instant; the current set cannot be determined and nothing was changed",
                        status.HTTP_409_CONFLICT)
        current = state.current
        current_key = (current.primary_technician_id, frozenset(current.collaborator_technician_ids)) \
            if current else None
        if current_key is None or expected != current_key:
            raise error("TECHNICIAN_ASSIGNMENT_STALE", "The current assignment set is not the one expected; reload "
                        "and retry", status.HTTP_409_CONFLICT, {"field": "expected_current"})

        row = dict.fromkeys(kind.assignment_columns, "")
        row.update({
            kind.record_id_column: record_id_for(kind, set_digest(kind, job_id, request_id, [(ROLE_WITHDRAWAL, "")]),
                                                 1, 1),
            kind.job_id_column: job_id,
            "assignment_role": ROLE_WITHDRAWAL,
            "assigned_at": self._now().isoformat(timespec="microseconds"),
            "assigned_by_user_id": user_id,
            "assignee_type": ASSIGNEE_TYPE_TECHNICIAN,
            "assignee_id": "",
            "request_id": request_id,
            "request_fingerprint": fingerprint,
            "reason_th": reason,
            **ctx.job_scope,
        })
        after = derive_assignment_state(kind, job_id, [*ctx.read.rows, row], ctx.job_scope)
        if after.issues or after.status != STATUS_NONE or after.current is not None or \
                not after.withdrawals or after.withdrawals[-1].withdrawal_id != request_id:
            raise RuntimeError(f"generated V2 withdrawal is invalid: {after.issues or after.status}")
        try:
            await self._repository.append_work_assignment_v2_rows(kind.key, ctx.read, [row])
        except RepositoryWriteError as exc:
            message = ("Google Sheets rejected the withdrawal write; nothing was changed by this request"
                       if exc.outcome == "rejected" else
                       "The withdrawal write outcome is unknown (it may have been written); nothing was retried")
            raise error("TECHNICIAN_ASSIGNMENT_WRITE_FAILED", message, status.HTTP_503_SERVICE_UNAVAILABLE,
                        {"write_outcome": exc.outcome, "request_id": request_id}) from exc
        return AssignmentOutcome(request_id=request_id, changed=True, record_ids=(row[kind.record_id_column],))

    # ---------------------------------------------------------------- reads

    async def read(self, kind: WorkKind, job_id: str) -> AssignmentRead:
        context = require_write_context(self._cutover.data_context, self._cutover.test_batch_id)
        job = await self._job(kind, job_id)
        require_v2_job_in_scope(kind, job, context, self._batch_id)
        ctx = await self._load(kind, job, context)
        return AssignmentRead(job_id=job_id, assignment_model=ASSIGNMENT_MODEL_TECHNICIAN_V2, state=ctx.state)

    async def actor_technician_id(self, user_id: str, context: str) -> str | None:
        """User Account -> Personnel -> Technician, exact and in scope, or None
        when any link is unset, missing, ambiguous or scope-unproven. Never a
        name / email / phone / prefix match."""
        personnel = await self._personnel(context)
        holders = [p for p in personnel if text(p.get("user_id")) == user_id]
        if len(holders) != 1:
            return None
        accounts = await reference_read(self._repository.read_user_account_reference(), USER_ACCOUNT_PREFIX,
                                        USER_ACCOUNT_TAB)
        if resolve_link(user_id, id_column="user_id", reference=accounts, context=context, batch_id=self._batch_id,
                        holders=1).resolution != RESOLVED:
            return None
        technician_id = text(holders[0].get("technician_id"))
        technicians = await read_technicians(self._repository)
        held = sum(1 for p in personnel if text(p.get("technician_id")) == technician_id)
        resolution = resolve_link(technician_id, id_column="technician_id", reference=technicians, context=context,
                                  batch_id=self._batch_id, holders=held)
        return technician_id if resolution.resolution == RESOLVED else None

    async def is_current_member(self, kind: WorkKind, job, user_id: str | None) -> bool:
        """Whether the actor is a member of the job's CURRENT V2 set. No
        lifecycle gate (owner decision PENDING). Out-of-scope job, no context,
        no set or an unresolved actor chain -> False; an AMBIGUOUS current set
        fails closed (409); untrusted history fails closed (500)."""
        if not (user_id or "").strip() or self._cutover.data_context is None:
            return False
        context = self._cutover.data_context
        if context == DATA_CONTEXT_TEST and not self._batch_id.strip():
            return False
        try:
            require_v2_job_in_scope(kind, job, context, self._batch_id)
        except ApiError as exc:
            if exc.code == "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH":
                return False
            raise
        ctx = await self._load(kind, job, context)
        if ctx.state.status == STATUS_AMBIGUOUS:
            raise error("TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", "The current assignment set cannot be determined",
                        status.HTTP_409_CONFLICT)
        if ctx.state.current is None:
            return False
        technician_id = await self.actor_technician_id(user_id or "", context)
        return technician_id is not None and technician_id in ctx.state.current.members

    async def require_current_primary(self, kind: WorkKind, job, user_id: str | None,
                                      expected_set_id: str | None) -> tuple[str, str]:
        """R3 (Owner rule Q2, contract §10 W2, TS-13): read-only proof that the
        authenticated actor is the PRIMARY of the job's CURRENT VALID V2 set,
        resolved in scope (User Account -> Personnel -> Technician). No
        capability substitutes. Returns (technician_id, set_id). The V2
        assignment behaviour itself is unchanged."""
        def lead_only() -> ApiError:
            return error("REPAIR_COMPLETION_LEAD_ONLY", "Only the current lead technician (PRIMARY) of this "
                         "work order may submit completion", status.HTTP_403_FORBIDDEN)

        if not (user_id or "").strip() or self._cutover.data_context is None:
            raise lead_only()
        context = self._cutover.data_context
        if context == DATA_CONTEXT_TEST and not self._batch_id.strip():
            raise lead_only()
        try:
            require_v2_job_in_scope(kind, job, context, self._batch_id)
        except ApiError as exc:
            if exc.code == "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH":
                raise lead_only() from exc
            raise
        ctx = await self._load(kind, job, context)
        if ctx.state.status == STATUS_AMBIGUOUS:
            raise error("TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", "The current assignment set cannot be determined",
                        status.HTTP_409_CONFLICT)
        current = ctx.state.current
        if current is None:
            raise error("REPAIR_LEAD_NOT_ASSIGNED", "This work order has no current lead technician",
                        status.HTTP_409_CONFLICT)
        technician_id = await self.actor_technician_id(user_id or "", context)
        if technician_id is None or technician_id != current.primary_technician_id:
            raise lead_only()
        if expected_set_id != current.set_id:
            raise error("REPAIR_ASSIGNMENT_STALE", "The technician assignment changed since it was loaded; "
                        "reload and try again", status.HTTP_409_CONFLICT,
                        {"current_set_id": current.set_id})
        return technician_id, current.set_id

    async def require_recording(self, kind: WorkKind, job, context_obj, capability: str, description: str) -> None:
        """V2 recording authorization: the capability (no V2 read), or current
        set membership through the in-scope chain; otherwise 403."""
        if capability in context_obj.capabilities:
            return
        if await self.is_current_member(kind, job, context_obj.user_id):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"{description} requires being a member of this work order's current V2 technician assignment "
                    f"or the '{capability}' capability"),
        )


__all__ = [
    "ASSIGNEE_TYPE_TECHNICIAN",
    "ASSIGNMENT_MODEL_LEGACY",
    "ASSIGNMENT_MODEL_TECHNICIAN_V2",
    "AssignmentCutover",
    "AssignmentOutcome",
    "AssignmentRead",
    "AssignmentSet",
    "AssignmentState",
    "AssignmentWithdrawal",
    "PM",
    "REPAIR",
    "ROLE_WITHDRAWAL",
    "TechnicianAssignmentService",
    "V2_ASSIGNMENT_COLUMNS",
    "V2_JOB_COLUMNS",
    "WORK_KINDS",
    "WorkKind",
    "assignment_model_of",
    "cutover_from_settings",
    "derive_assignment_state",
    "require_legacy",
    "require_open_job",
    "v2_job_marker",
]
