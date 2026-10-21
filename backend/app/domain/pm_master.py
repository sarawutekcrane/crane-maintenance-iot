"""R4-B1 (Mock only) — versioned PM Master, optional per-vehicle/assembly Plan
assignment and the revision / Work Order history firewall (deliverables D2–D5).

ISOLATION (B1 firewall, D4): nothing in the application imports this module. It
is not wired into `Repository`, the Mock or Google Sheets adapters, any API
route, the seed data or `PmService`. The existing `PmPlan` / `PmTaskRevision` /
`PmWorkOrder` (`OPEN/CLOSED + completed: bool`) flow, the non-authoritative
PLAN1 seed (`PMP-0001`, `PMREV-0001`, three placeholder tasks) and
`VehicleModel.assigned_pm_plan_id` are untouched and unaware of it. State lives
only in a `PmMasterMockStore` instance a caller creates (tests); B2 activation
needs a separate Owner approval.

AUTHORITY (VAL-AM gate): no existing Access Management capability authorizes
writing the PM Master. `can_manage_pm` is the E01 Work Order capability (open,
scope, assign, close) and is NOT Master publish authority; root / delegated
permission administration is not a functional capability either. Every write
(publish, assign / change / unassign) therefore goes through a
`MasterAuthorizer`, and the only authorizer this module provides,
`deny_unproven_master_authority`, refuses everyone (403
PM_MASTER_AUTHORITY_UNPROVEN, gate VAL-AM). No capability is invented and no
role title is given the power. Reads need the existing `can_view`.

MASTER RULES:
- A published revision is immutable (frozen models), numbered 1..N per Plan,
  and the head is the one effective revision. Publish is revision-checked
  (`expected_revision` must equal the head), atomic (revision + audit event in
  one append, nothing on any refusal) and idempotent per request id (same
  actor + same payload -> the original result; anything else -> 409).
- Each Set carries its own source-backed meter + interval (no global Plan
  interval; ENGINE_HOUR / PTO_HOUR / ODOMETER only, never a calendar
  substitute) and an explicit driving component. A Set without one, an Item
  without a stable key, or an unresolved REVIEW ledger entry blocks publish.
- Item lineage across revisions follows the stable `item_key` (reorder and
  rewording keep lineage) or an explicit `supersedes_item_key` with evidence.
  A new key whose text equals a removed key's text is NOT linked
  automatically: it is reported `AMBIGUOUS_UNVERIFIED` for manual review.
- No Due, Outstanding, early-warning (E02) or replacement advisory (E03)
  value exists here; nothing generates Work Order history.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from pydantic import BaseModel, ConfigDict

from app.domain.authz import CAN_VIEW, require_capability
from app.domain.pm import PmTriggerType
from app.domain.pm_source_preview import METER_UNITS, SECTION_CARRIER, SECTION_CRANE, LedgerEntry, PreviewResult
from app.domain.request_replay import canonical_json, find_replay, request_fingerprint
from app.domain.vehicle_model import ComponentRole
from app.errors import ApiError

VAL_AM_GATE = "VAL-AM"
OP_MASTER_PUBLISH = "pm_master_publish"
OP_MASTER_ASSIGNMENT = "pm_master_assignment"
KIND_PUBLISH = "PUBLISH"
KIND_ASSIGN = "ASSIGN"
KIND_CHANGE = "CHANGE"
KIND_UNASSIGN = "UNASSIGN"
ASSIGNED = "ASSIGNED"
NONE = "NONE"
ASSEMBLIES = frozenset({"", SECTION_CARRIER, SECTION_CRANE})  # "" = the whole vehicle
MAX_REASON_LENGTH = 500

LINEAGE_RETAINED = "RETAINED"
LINEAGE_PROVEN = "PROVEN_SUPERSEDES"
LINEAGE_NEW = "NEW"
LINEAGE_REMOVED = "REMOVED"
LINEAGE_AMBIGUOUS = "AMBIGUOUS_UNVERIFIED"

# Only the unambiguous section/meter pairs name their driving component; every
# other Set needs it stated explicitly (reviewed), never guessed.
_DERIVED_DRIVING_COMPONENT: dict[tuple[str, str], ComponentRole] = {
    (SECTION_CARRIER, PmTriggerType.ENGINE_HOUR.value): ComponentRole.CARRIER_ENGINE,
    (SECTION_CRANE, PmTriggerType.ENGINE_HOUR.value): ComponentRole.CRANE_ENGINE,
}


def _error(code: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=http_status, details=details)


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------

MasterAuthorizer = Callable[[object, str], None]


def deny_unproven_master_authority(context: object, action: str) -> None:
    """The only Master write authorizer B1 provides: fail closed for every actor
    (including ADMIN, the root holder and `can_manage_pm` holders) until the
    Owner approves which existing authority may write the PM Master (VAL-AM)."""
    raise _error("PM_MASTER_AUTHORITY_UNPROVEN",
                 "PM Master write authority is not established by Access Management (VAL-AM); refused",
                 status.HTTP_403_FORBIDDEN, {"gate": VAL_AM_GATE, "action": action})


# ---------------------------------------------------------------------------
# Immutable Master model
# ---------------------------------------------------------------------------


class MasterItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_key: str
    sequence: int
    task_text: str
    method: str = ""
    standard: str = ""
    source_ref: str = ""
    supersedes_item_key: str = ""
    lineage_evidence: str = ""


class MasterSet(BaseModel):
    """One Set/Cycle of a Plan for one model variant + section. Interval value,
    unit and raw text are the source's own; nothing is converted."""

    model_config = ConfigDict(frozen=True)

    model_variant: str
    section: str
    set_code: str
    meter_type: PmTriggerType
    interval_value: float
    interval_unit: str
    raw_interval: str = ""
    independent_group: str = ""
    driving_component: ComponentRole | None = None
    source_doc: str = ""
    source_ref: str = ""
    items: tuple[MasterItem, ...] = ()

    @property
    def set_key(self) -> str:
        return f"{self.model_variant}|{self.section}|{self.set_code}"


class MasterRevision(BaseModel):
    model_config = ConfigDict(frozen=True)

    revision_id: str
    plan_code: str
    revision_number: int
    sets: tuple[MasterSet, ...]
    content_digest: str
    published_at: datetime
    published_by: str
    reason: str
    request_id: str


class AssignmentRecord(BaseModel):
    """Explicit Plan state of one vehicle (assembly "") or one assembly. `NONE` is
    an explicit unassignment and is distinct from having no record at all."""

    model_config = ConfigDict(frozen=True)

    vehicle_id: str
    assembly: str
    state: str
    plan_code: str
    version: int
    recorded_by: str
    recorded_at: datetime
    reason: str
    request_id: str


class PlanResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str  # EXPLICIT_ASSIGNED | EXPLICIT_NONE | ABSENT
    plan_code: str | None
    assignment_version: int
    legacy_model_plan_id: str | None
    """`VehicleModel.assigned_pm_plan_id`, echoed unchanged and NON-authoritative:
    it is never used as the Master Plan and never overrides an explicit NONE."""


class MasterWorkOrderSnapshot(BaseModel):
    """What a future (B2) Work Order would freeze: the exact revision and the
    selected Sets with their Items. A value only — B1 stores no Work Order."""

    model_config = ConfigDict(frozen=True)

    plan_code: str
    revision_id: str
    revision_number: int
    sets: tuple[MasterSet, ...]


@dataclass(frozen=True)
class PublishOutcome:
    revision: MasterRevision
    replayed: bool
    diff: dict[str, object]


@dataclass(frozen=True)
class AssignmentOutcome:
    record: AssignmentRecord
    replayed: bool


# ---------------------------------------------------------------------------
# Candidate building, validation, lineage and diff (pure)
# ---------------------------------------------------------------------------


def candidate_sets_from_preview(preview: PreviewResult, plan_code: str, *,
                                driving_components: Mapping[str, ComponentRole] | None = None) -> tuple[MasterSet, ...]:
    """The ACCEPTED preview rows of one Plan as Master Sets. A driving component
    is taken from `driving_components` (reviewed, by set_key) or from the two
    unambiguous section/meter pairs; otherwise it stays None and publish refuses."""
    reviewed = driving_components or {}
    sets: list[MasterSet] = []
    for s in preview.sets:
        if s.plan_code != plan_code:
            continue
        items = tuple(
            MasterItem(item_key=i.item_key, sequence=i.sequence, task_text=i.task_text, method=i.method,
                       standard=i.standard, source_ref=f"{preview.source_file}!items!{i.source_row}")
            for i in preview.items
            if (i.plan_code, i.model_variant, i.section, i.set_code) == (s.plan_code, s.model_variant, s.section, s.set_code))
        key = f"{s.model_variant}|{s.section}|{s.set_code}"
        sets.append(MasterSet(
            model_variant=s.model_variant, section=s.section, set_code=s.set_code,
            meter_type=PmTriggerType(s.meter_type), interval_value=s.interval_value, interval_unit=s.interval_unit,
            raw_interval=s.raw_interval, independent_group=s.independent_group,
            driving_component=reviewed.get(key, _DERIVED_DRIVING_COMPONENT.get((s.section, s.meter_type))),
            source_doc=s.source_doc, source_ref=f"{preview.source_file}!cycles!{s.source_row}", items=items))
    return tuple(sets)


def validate_candidate(plan_code: str, sets: Sequence[MasterSet], open_reviews: Iterable[LedgerEntry] = ()) -> list[dict[str, str]]:
    """Every reason the candidate cannot become ACTIVE (empty = publishable)."""
    problems: list[dict[str, str]] = []

    def bad(where: str, issue: str) -> None:
        problems.append({"where": where, "issue": issue})

    if not plan_code.strip():
        bad("plan", "PLAN_CODE_REQUIRED")
    for entry in open_reviews:
        if entry.unresolved and entry.plan_code in ("", plan_code):
            bad(f"{entry.sheet}!{entry.row_or_key}", f"UNRESOLVED_REVIEW:{entry.issue}")
    if not sets:
        bad("plan", "NO_SETS")
    seen_sets: set[str] = set()
    for s in sets:
        key = s.set_key
        if key in seen_sets:
            bad(key, "DUPLICATE_SET")
        seen_sets.add(key)
        if s.meter_type.value not in METER_UNITS:
            bad(key, "METER_NOT_EXPLICIT")
        elif s.interval_unit != METER_UNITS[s.meter_type.value]:
            bad(key, "UNIT_METER_MISMATCH")
        if not s.interval_value > 0:
            bad(key, "INVALID_INTERVAL")
        if s.driving_component is None:
            bad(key, "DRIVING_COMPONENT_ABSENT")
        if not s.items:
            bad(key, "NO_ITEMS")
        seen_items: set[str] = set()
        for item in s.items:
            where = f"{key}/{item.item_key}"
            if not item.item_key.strip():
                bad(key, "ITEM_KEY_REQUIRED")
            elif item.item_key in seen_items:
                bad(where, "DUPLICATE_ITEM_KEY")
            seen_items.add(item.item_key)
            if not item.task_text.strip():
                bad(where, "TASK_TEXT_REQUIRED")
            if item.supersedes_item_key and not item.lineage_evidence.strip():
                bad(where, "LINEAGE_EVIDENCE_REQUIRED")
    return problems


def _norm_text(text_: str) -> str:
    return " ".join(text_.split())


def item_lineage(previous: Sequence[MasterSet], current: Sequence[MasterSet]) -> list[dict[str, object]]:
    """Per-Set lineage from the previous revision to the candidate. Only a shared
    stable key or an evidenced `supersedes_item_key` carries lineage; identical
    text under a different key is AMBIGUOUS_UNVERIFIED, never auto-linked."""
    old_by_set = {s.set_key: {i.item_key: i for i in s.items} for s in previous}
    rows: list[dict[str, object]] = []
    for s in current:
        old = old_by_set.get(s.set_key, {})
        new = {i.item_key: i for i in s.items}
        superseded = {i.supersedes_item_key for i in s.items
                      if i.supersedes_item_key in old and i.supersedes_item_key not in new}
        removed = {k: v for k, v in old.items() if k not in new and k not in superseded}
        for key, item in new.items():
            row: dict[str, object] = {"set_key": s.set_key, "item_key": key}
            if key in old:
                prior = old[key]
                row.update(status=LINEAGE_RETAINED, previous_item_key=key,
                           reworded=_norm_text(prior.task_text) != _norm_text(item.task_text),
                           resequenced=prior.sequence != item.sequence)
            elif item.supersedes_item_key in superseded:
                row.update(status=LINEAGE_PROVEN, previous_item_key=item.supersedes_item_key,
                           evidence=item.lineage_evidence)
            else:
                twins = sorted(k for k, v in removed.items() if _norm_text(v.task_text) == _norm_text(item.task_text))
                row.update(status=LINEAGE_AMBIGUOUS if twins else LINEAGE_NEW, candidates=twins)
            rows.append(row)
        rows.extend({"set_key": s.set_key, "item_key": k, "status": LINEAGE_REMOVED} for k in sorted(removed))
    current_keys = {s.set_key for s in current}
    for s in previous:
        if s.set_key not in current_keys:
            rows.extend({"set_key": s.set_key, "item_key": i.item_key, "status": LINEAGE_REMOVED} for i in s.items)
    return sorted(rows, key=lambda r: (str(r["set_key"]), str(r["item_key"])))


_SET_FIELDS = ("meter_type", "interval_value", "interval_unit", "raw_interval", "independent_group",
               "driving_component", "source_doc")


def compare_sets(previous: Sequence[MasterSet], current: Sequence[MasterSet]) -> dict[str, object]:
    """Audited Set-level and Item-level difference between two revisions."""
    old = {s.set_key: s for s in previous}
    new = {s.set_key: s for s in current}
    changed: list[dict[str, object]] = []
    for key in sorted(old.keys() & new.keys()):
        a, b = old[key].model_dump(mode="json"), new[key].model_dump(mode="json")
        fields = {f: {"from": a[f], "to": b[f]} for f in _SET_FIELDS if a[f] != b[f]}
        if fields:
            changed.append({"set_key": key, "fields": fields})
    return {"sets_added": sorted(new.keys() - old.keys()), "sets_removed": sorted(old.keys() - new.keys()),
            "sets_changed": changed, "items": item_lineage(previous, current)}


def content_digest(plan_code: str, sets: Sequence[MasterSet]) -> str:
    body = {"plan_code": plan_code, "sets": [s.model_dump(mode="json") for s in sets]}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Mock store (in-memory, never a Repository)
# ---------------------------------------------------------------------------


class PmMasterMockStore:
    """In-memory Mock state. Each commit replaces the lists in one step (copy then
    assign), so a refused or failed write leaves nothing behind. The lock makes
    revision checks single-writer inside one process only (not production R11)."""

    def __init__(self) -> None:
        self.revisions: dict[str, tuple[MasterRevision, ...]] = {}
        self.assignments: tuple[AssignmentRecord, ...] = ()
        self.events: tuple[dict[str, str], ...] = ()
        self.lock = asyncio.Lock()

    def head(self, plan_code: str) -> MasterRevision | None:
        revisions = self.revisions.get(plan_code, ())
        return revisions[-1] if revisions else None

    def latest_assignment(self, vehicle_id: str, assembly: str) -> AssignmentRecord | None:
        hits = [a for a in self.assignments if (a.vehicle_id, a.assembly) == (vehicle_id, assembly)]
        return hits[-1] if hits else None

    def commit(self, event: dict[str, str], *, revision: MasterRevision | None = None,
               assignment: AssignmentRecord | None = None) -> None:
        revisions = dict(self.revisions)
        if revision is not None:
            revisions[revision.plan_code] = (*revisions.get(revision.plan_code, ()), revision)
        assignments = (*self.assignments, assignment) if assignment is not None else self.assignments
        events = (*self.events, dict(event))
        self.revisions, self.assignments, self.events = revisions, assignments, events


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _reason(raw: object) -> str:
    value = raw.strip() if isinstance(raw, str) else ""
    if not value or len(value) > MAX_REASON_LENGTH:
        raise _error("VALIDATION_ERROR", f"a reason of 1..{MAX_REASON_LENGTH} characters is required",
                     status.HTTP_422_UNPROCESSABLE_ENTITY)
    return value


def _request_id(raw: object) -> str:
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        raise _error("REQUEST_ID_REQUIRED", "a request id is required for a PM Master write",
                     status.HTTP_422_UNPROCESSABLE_ENTITY)
    return value


def _actor(context: object) -> str:
    return str(getattr(context, "user_id", "") or "")


class PmMasterService:
    def __init__(self, store: PmMasterMockStore, *, authorizer: MasterAuthorizer = deny_unproven_master_authority,
                 repository: object | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self._store = store
        self._authorize = authorizer
        self._repository = repository  # read-only (vehicle existence); never written
        self._clock = clock or (lambda: datetime.now(UTC))

    # ---- reads (can_view) ----

    def effective_revision(self, context: object, plan_code: str) -> MasterRevision | None:
        require_capability(context, CAN_VIEW, "PM Master read")
        return self._store.head(plan_code)

    def get_revision(self, context: object, plan_code: str, revision_number: int) -> MasterRevision:
        require_capability(context, CAN_VIEW, "PM Master read")
        for revision in self._store.revisions.get(plan_code, ()):
            if revision.revision_number == revision_number:
                return revision
        raise _error("PM_MASTER_REVISION_NOT_FOUND", f"revision {revision_number} of '{plan_code}' was not found",
                     status.HTTP_404_NOT_FOUND)

    def compare(self, context: object, plan_code: str, from_number: int, to_number: int) -> dict[str, object]:
        old = self.get_revision(context, plan_code, from_number)
        new = self.get_revision(context, plan_code, to_number)
        return compare_sets(old.sets, new.sets)

    def audit(self, context: object) -> tuple[dict[str, str], ...]:
        require_capability(context, CAN_VIEW, "PM Master audit read")
        return self._store.events

    def freeze_selection(self, context: object, plan_code: str, selected_set_keys: Sequence[str], *,
                         revision_number: int | None = None) -> MasterWorkOrderSnapshot:
        """The value a future Work Order would freeze (default: the effective
        revision). Unknown Set keys are refused; nothing is stored."""
        require_capability(context, CAN_VIEW, "PM Master read")
        revision = (self._store.head(plan_code) if revision_number is None
                    else self.get_revision(context, plan_code, revision_number))
        if revision is None:
            raise _error("PM_MASTER_NOT_PUBLISHED", f"'{plan_code}' has no published revision",
                         status.HTTP_404_NOT_FOUND)
        by_key = {s.set_key: s for s in revision.sets}
        unknown = sorted(set(selected_set_keys) - by_key.keys())
        if unknown or not selected_set_keys:
            raise _error("VALIDATION_ERROR", "selected Sets must be non-empty and belong to the revision",
                         status.HTTP_422_UNPROCESSABLE_ENTITY, {"unknown_set_keys": unknown})
        return MasterWorkOrderSnapshot(plan_code=plan_code, revision_id=revision.revision_id,
                                       revision_number=revision.revision_number,
                                       sets=tuple(by_key[k] for k in sorted(set(selected_set_keys))))

    def resolve_plan(self, context: object, vehicle_id: str, assembly: str = "", *,
                     legacy_model_plan_id: str | None = None) -> PlanResolution:
        """Explicit assembly record, else explicit vehicle record, else ABSENT. An
        explicit NONE is final; the legacy model default never overrides it."""
        require_capability(context, CAN_VIEW, "PM Master read")
        record = self._store.latest_assignment(vehicle_id, assembly) if assembly else None
        record = record or self._store.latest_assignment(vehicle_id, "")
        if record is None:
            return PlanResolution(source="ABSENT", plan_code=None, assignment_version=0,
                                  legacy_model_plan_id=legacy_model_plan_id)
        return PlanResolution(source="EXPLICIT_ASSIGNED" if record.state == ASSIGNED else "EXPLICIT_NONE",
                              plan_code=record.plan_code or None, assignment_version=record.version,
                              legacy_model_plan_id=legacy_model_plan_id)

    # ---- writes (authorizer; fail closed by default) ----

    def _event(self, kind: str, context: object, *, plan_code: str, request_id: str, fingerprint: str,
               reason: str, **cells: str) -> dict[str, str]:
        return {"event_id": f"PMMEV-{uuid.uuid4().hex}", "kind": kind, "plan_code": plan_code,
                "actor_user_id": _actor(context),
                "actor_personnel_id": str(getattr(context, "personnel_id", "") or ""),
                "recorded_at": self._clock().isoformat(), "reason": reason, "request_id": request_id,
                "request_fingerprint": fingerprint, "revision_id": "", "vehicle_id": "", "assembly": "",
                "version": "", "diff_json": "", **cells}

    def _replay(self, request_id: str, fingerprint: str, record_id_column: str):
        lookup = find_replay(self._store.events, request_id, fingerprint, record_id_column=record_id_column)
        if lookup is not None and not lookup.replayed:
            raise _error("REQUEST_ID_REUSED", "this request id was already used for a different request",
                         status.HTTP_409_CONFLICT, {"request_id": request_id})
        return lookup

    async def publish(self, context: object, *, plan_code: str, expected_revision: int, sets: Sequence[MasterSet],
                      reason: str, request_id: str, open_reviews: Iterable[LedgerEntry] = ()) -> PublishOutcome:
        self._authorize(context, KIND_PUBLISH)  # before any replay is disclosed
        reason_, request_id_ = _reason(reason), _request_id(request_id)
        sets = tuple(sets)
        body = {"plan_code": plan_code, "expected_revision": expected_revision, "reason": reason_,
                "sets": [s.model_dump(mode="json") for s in sets]}
        fingerprint = request_fingerprint(OP_MASTER_PUBLISH, plan_code, _actor(context), body)
        problems = validate_candidate(plan_code, sets, open_reviews)
        await asyncio.sleep(0)  # a real interleaving point before the single-writer section
        async with self._store.lock:
            if (lookup := self._replay(request_id_, fingerprint, "revision_id")) is not None:
                revision = next(r for r in self._store.revisions.get(plan_code, ())
                                if r.revision_id in lookup.record_ids)
                return PublishOutcome(revision, True, json.loads(lookup.rows[0]["diff_json"]))
            if problems:
                raise _error("PM_MASTER_VALIDATION_FAILED", "the candidate cannot become an active revision",
                             status.HTTP_422_UNPROCESSABLE_ENTITY, {"problems": problems})
            head = self._store.head(plan_code)
            current = head.revision_number if head else 0
            if expected_revision != current:
                raise _error("PM_MASTER_STALE_REVISION", "the PM Master changed since it was read",
                             status.HTTP_409_CONFLICT, {"expected_revision": expected_revision,
                                                        "current_revision": current})
            digest = content_digest(plan_code, sets)
            if head is not None and head.content_digest == digest:
                raise _error("PM_MASTER_UNCHANGED", "the candidate is identical to the effective revision",
                             status.HTTP_422_UNPROCESSABLE_ENTITY)
            number = current + 1
            diff = compare_sets(head.sets if head else (), sets)
            revision = MasterRevision(
                revision_id=f"PMMREV-{plan_code}-{number:04d}", plan_code=plan_code, revision_number=number,
                sets=sets, content_digest=digest, published_at=self._clock(), published_by=_actor(context),
                reason=reason_, request_id=request_id_)
            event = self._event(KIND_PUBLISH, context, plan_code=plan_code, request_id=request_id_,
                                fingerprint=fingerprint, reason=reason_, revision_id=revision.revision_id,
                                version=str(number), diff_json=canonical_json(diff))
            self._store.commit(event, revision=revision)
            return PublishOutcome(revision, False, diff)

    async def set_assignment(self, context: object, *, vehicle_id: str, assembly: str = "", plan_code: str | None,
                             expected_version: int, reason: str, request_id: str) -> AssignmentOutcome:
        """Assign / change (plan_code set) or explicitly unassign (plan_code None ->
        NONE) one vehicle or assembly. Version-checked, reasoned and audited."""
        self._authorize(context, KIND_ASSIGN)
        reason_, request_id_ = _reason(reason), _request_id(request_id)
        if assembly not in ASSEMBLIES:
            raise _error("VALIDATION_ERROR", "assembly must be blank (whole vehicle), CARRIER or CRANE",
                         status.HTTP_422_UNPROCESSABLE_ENTITY)
        body = {"vehicle_id": vehicle_id, "assembly": assembly, "plan_code": plan_code,
                "expected_version": expected_version, "reason": reason_}
        fingerprint = request_fingerprint(OP_MASTER_ASSIGNMENT, vehicle_id, _actor(context), body)
        if self._repository is not None and await self._repository.get_vehicle(vehicle_id) is None:
            raise _error("VEHICLE_NOT_FOUND", f"vehicle '{vehicle_id}' was not found", status.HTTP_404_NOT_FOUND)
        await asyncio.sleep(0)
        async with self._store.lock:
            if (lookup := self._replay(request_id_, fingerprint, "version")) is not None:
                hit = next(a for a in self._store.assignments if (a.vehicle_id, a.assembly, str(a.version)) ==
                           (vehicle_id, assembly, lookup.record_ids[0]))
                return AssignmentOutcome(hit, True)
            if plan_code is not None and self._store.head(plan_code) is None:
                raise _error("PM_MASTER_NOT_PUBLISHED", f"'{plan_code}' has no published revision",
                             status.HTTP_422_UNPROCESSABLE_ENTITY)
            prior = self._store.latest_assignment(vehicle_id, assembly)
            current = prior.version if prior else 0
            if expected_version != current:
                raise _error("PM_MASTER_STALE_ASSIGNMENT", "the assignment changed since it was read",
                             status.HTTP_409_CONFLICT, {"expected_version": expected_version,
                                                        "current_version": current})
            state = ASSIGNED if plan_code is not None else NONE
            if prior is not None and (prior.state, prior.plan_code) == (state, plan_code or ""):
                raise _error("PM_MASTER_ASSIGNMENT_UNCHANGED", "the assignment already has this value",
                             status.HTTP_422_UNPROCESSABLE_ENTITY)
            kind = (KIND_UNASSIGN if state == NONE else
                    KIND_CHANGE if prior is not None and prior.state == ASSIGNED else KIND_ASSIGN)
            record = AssignmentRecord(vehicle_id=vehicle_id, assembly=assembly, state=state,
                                      plan_code=plan_code or "", version=current + 1, recorded_by=_actor(context),
                                      recorded_at=self._clock(), reason=reason_, request_id=request_id_)
            event = self._event(kind, context, plan_code=plan_code or "", request_id=request_id_,
                                fingerprint=fingerprint, reason=reason_, vehicle_id=vehicle_id, assembly=assembly,
                                version=str(record.version),
                                diff_json=canonical_json({"from": prior.plan_code if prior else None,
                                                          "from_state": prior.state if prior else "ABSENT",
                                                          "to": plan_code, "to_state": state}))
            self._store.commit(event, assignment=record)
            return AssignmentOutcome(record, False)


__all__ = [
    "VAL_AM_GATE", "ASSIGNED", "NONE", "LINEAGE_RETAINED", "LINEAGE_PROVEN", "LINEAGE_NEW", "LINEAGE_REMOVED",
    "LINEAGE_AMBIGUOUS", "MasterAuthorizer", "deny_unproven_master_authority", "MasterItem", "MasterSet",
    "MasterRevision", "AssignmentRecord", "PlanResolution", "MasterWorkOrderSnapshot", "PublishOutcome",
    "AssignmentOutcome", "candidate_sets_from_preview", "validate_candidate", "item_lineage", "compare_sets",
    "content_digest", "PmMasterMockStore", "PmMasterService",
]
