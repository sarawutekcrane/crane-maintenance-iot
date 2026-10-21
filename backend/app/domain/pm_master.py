"""R4-B1 (Mock only) — versioned PM Master, optional per-vehicle/assembly Plan
assignment and the revision / Work Order history firewall (deliverables D2–D5),
with the R4-B1 correction batch (RV-B1-02..05).

ISOLATION (B1 firewall, D4): nothing in the application imports this module. It
is not wired into `Repository`, the Mock or Google Sheets adapters, any API
route, the seed data or `PmService`. The existing `PmPlan` / `PmTaskRevision` /
`PmWorkOrder` (`OPEN/CLOSED + completed: bool`) flow, the non-authoritative
PLAN1 seed (`PMP-0001`, `PMREV-0001`, three placeholder tasks) and
`VehicleModel.assigned_pm_plan_id` are untouched and unaware of it. State lives
only in a `PmMasterMockStore` instance a caller creates (tests); B2 activation
needs a separate Owner approval.

AUTHORITY (VAL-AM gate, OPEN): no existing Access Management capability
authorizes writing the PM Master. `can_manage_pm` is the E01 Work Order
capability (open, scope, assign, close) and is NOT Master authority. Every write
(preview registration, review resolution, publish, assignment) goes through a
`MasterAuthorizer`; the only one this module provides,
`deny_unproven_master_authority`, refuses everyone (403
PM_MASTER_AUTHORITY_UNPROVEN, gate VAL-AM). Reads need the existing `can_view`.

PUBLISH PROOF (RV-B1-02): `publish` takes NO caller-built Sets and no optional
review list. The candidate is rebuilt inside the service from:
1. a preview REGISTERED in the store (`register_preview`), computed by the
   service itself from the source-shaped tabs (`preview_maintenance_source`);
   only the latest registration for its source file is current (else stale);
2. the caller's `expected_source_digest`, which must equal that preview's digest;
3. review resolutions RECORDED in the store (`record_review`) against that exact
   preview, each bound to one ledger entry, with an allowed outcome and
   substantive evidence. A resolution object that was not recorded through the
   audited operation does not exist for publish.
Every REVIEW entry whose `plan_scope` includes the Plan, or the global
unresolved-source gate (`GLOBAL_PLAN_SCOPE`, RV-B1-R3-01), must be resolved, or
publish is refused before any mutation. No resolution can retain a semantic raw
35, and validation refuses one in any active Master field (RV-B1-R3-02). Sets are identified by plan + model +
section + task group and carry their mapped document; an Item joins only the
exact Sets its own document/section/group is linked to (RV-B1-R2-01/03), so a
task or a resolution can never cross a model, Set, section or document.

LINEAGE (RV-B1-03): an Item continues only when it keeps the same source pointer
with identical content (RETAINED) or an explicit, evidenced `LineageDecision`
names its predecessor in the same previous Set (CONTINUES) or declares it new
(DECLARED_NEW). Anything else in a Set that existed before is
AMBIGUOUS_UNVERIFIED and publish is refused. A predecessor must exist in the
same previous Set, may be continued once, and cannot also stay retained.

Revisions are immutable (frozen models), numbered 1..N per Plan; the head is the
one effective revision. Publish is revision-checked, atomic (one copy-then-assign
commit) and idempotent per request id. Audit events are stored and returned as
read-only mappings (RV-B1-04). No Due, Outstanding, E02/E03 value exists here;
nothing generates Work Order history.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from fastapi import status
from pydantic import BaseModel, ConfigDict

from app.domain.authz import CAN_VIEW, require_capability
from app.domain.pm import PmTriggerType
from app.domain.pm_source_preview import (
    AMBIGUOUS_RAW,
    GLOBAL_PLAN_SCOPE,
    ISSUE_METER_UNRESOLVED,
    METER_UNITS,
    OUTCOME_EXCLUDE_ROW,
    OUTCOME_RESOLVE_METER,
    REVIEW,
    SECTION_CARRIER,
    SECTION_CRANE,
    UNIT_HOUR,
    UNIT_KM,
    PreviewResult,
    allowed_outcomes,
    preview_maintenance_source,
)
from app.domain.request_replay import canonical_json, find_replay, request_fingerprint
from app.domain.vehicle_model import ComponentRole
from app.errors import ApiError

VAL_AM_GATE = "VAL-AM"
OP_MASTER_PUBLISH = "pm_master_publish"
OP_MASTER_ASSIGNMENT = "pm_master_assignment"
OP_MASTER_PREVIEW = "pm_master_preview"
OP_MASTER_REVIEW = "pm_master_review"
KIND_PREVIEW = "PREVIEW_REGISTERED"
KIND_REVIEW = "REVIEW_RESOLVED"
KIND_PUBLISH = "PUBLISH"
KIND_ASSIGN = "ASSIGN"
KIND_CHANGE = "CHANGE"
KIND_UNASSIGN = "UNASSIGN"
ASSIGNED = "ASSIGNED"
NONE = "NONE"
ASSEMBLIES = frozenset({"", SECTION_CARRIER, SECTION_CRANE})  # "" = the whole vehicle
# An assembly is valid on a vehicle only when its model declares that engine role
# (UNVERIFIED mapping, fail closed; a PTO-driven upper is not assumed to be CRANE).
ASSEMBLY_ROLE: dict[str, ComponentRole] = {SECTION_CARRIER: ComponentRole.CARRIER_ENGINE,
                                           SECTION_CRANE: ComponentRole.CRANE_ENGINE}
MAX_REASON_LENGTH = 500
MIN_EVIDENCE_LENGTH = 12

LINEAGE_RETAINED = "RETAINED"
LINEAGE_CONTINUES = "CONTINUES"
LINEAGE_DECLARED_NEW = "DECLARED_NEW"
LINEAGE_NEW = "NEW"  # only in a Set the previous revision did not have
LINEAGE_REMOVED = "REMOVED"
LINEAGE_AMBIGUOUS = "AMBIGUOUS_UNVERIFIED"

# What a reviewed HOUR Set may be resolved to (meter -> components it can drive).
HOUR_METER_COMPONENTS: dict[str, frozenset[ComponentRole]] = {
    PmTriggerType.ENGINE_HOUR.value: frozenset({ComponentRole.CARRIER_ENGINE, ComponentRole.CRANE_ENGINE}),
    PmTriggerType.PTO_HOUR.value: frozenset({ComponentRole.PTO}),
}


def _error(code: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=http_status, details=details)


def _unprocessable(code: str, message: str, details: dict[str, object] | None = None) -> ApiError:
    return _error(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY, details)


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
    """`item_key` is the source pointer (`source_sheet!source_row`), NOT a
    semantic id; lineage across revisions is decided only by `resolve_lineage`."""

    model_config = ConfigDict(frozen=True)

    item_key: str
    sequence: int
    task_text: str
    method: str = ""
    standard: str = ""
    source_ref: str = ""
    raw: tuple[tuple[str, str], ...] = ()


class MasterSet(BaseModel):
    """One Set of a Plan for one model + section + task group. Interval value,
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
    """The inspection standard document the mapping evidence links this Set to."""
    source_ref: str = ""
    raw: tuple[tuple[str, str], ...] = ()
    items: tuple[MasterItem, ...] = ()
    topology: str = ""
    """SINGLE / DUAL / UNKNOWN source category of the mapped model (not a device)."""
    meter_basis: str = ""
    """Owner rule, KM odometer rule, or REVIEW_RESOLUTION that set meter/component."""

    @property
    def set_key(self) -> str:
        return f"{self.model_variant}|{self.section}|{self.set_code}"


class LineageDecision(BaseModel):
    """An explicit, evidenced lineage statement for one Item of the candidate:
    `predecessor_item_key` names the Item it continues in the same previous Set,
    or "" declares the Item genuinely new."""

    model_config = ConfigDict(frozen=True)

    set_key: str
    item_key: str
    predecessor_item_key: str = ""
    evidence: str


class ReviewResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolution_id: str
    preview_id: str
    source_digest: str
    entry_id: str
    issue: str
    outcome: str
    values: tuple[tuple[str, str], ...] = ()
    evidence: str
    reviewer: str
    reviewed_at: datetime


@dataclass(frozen=True)
class PreviewRegistration:
    preview_id: str
    source_file: str
    source_digest: str
    registered_by: str
    registered_at: datetime
    preview: PreviewResult


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
    preview_id: str
    source_digest: str
    resolution_ids: tuple[str, ...]
    lineage: tuple[LineageDecision, ...] = ()


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


@dataclass(frozen=True)
class VehicleFacts:
    vehicle_id: str
    component_roles: frozenset[str]


class MockVehicleResolver:
    """RV-B1-05: the explicit, read-only, Mock-ONLY vehicle resolver an assignment
    requires. It accepts only the in-memory Mock repository (checked by type,
    without importing the adapter layer) and never creates or changes a vehicle."""

    _MOCK = ("app.repositories.mock.repository", "MockRepository")

    def __init__(self, repository: object) -> None:
        if (type(repository).__module__, type(repository).__name__) != self._MOCK:
            raise _error("PM_MASTER_VEHICLE_RESOLVER_NOT_MOCK", "only the Mock repository may back the B1 resolver",
                         status.HTTP_403_FORBIDDEN)
        self._repository = repository

    async def resolve(self, vehicle_id: str) -> VehicleFacts | None:
        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            return None
        model = await self._repository.get_vehicle_model(vehicle.model_id)
        roles = frozenset(r.value for r in model.component_roles) if model is not None else frozenset()
        return VehicleFacts(vehicle_id=vehicle.vehicle_id, component_roles=roles)


# ---------------------------------------------------------------------------
# Candidate building, validation, lineage and diff (pure)
# ---------------------------------------------------------------------------


def build_candidate(preview: PreviewResult, plan_code: str,
                    resolutions: Sequence[ReviewResolution]) -> tuple[tuple[MasterSet, ...], list[dict[str, str]]]:
    """The Plan's Sets rebuilt from a registered preview plus its recorded
    resolutions, and every reason it is not yet publishable. A Set is keyed by its
    full identity (plan|model|section|group); an Item is added only to the
    included Sets listed in its own `linked_set_identities`."""
    by_entry = {r.entry_id: r for r in resolutions}

    def settled(blocking: Sequence[str]) -> tuple[bool, bool, dict[str, str]]:
        """(all resolved, excluded, resolved values)."""
        values: dict[str, str] = {}
        excluded = False
        for entry_id in blocking:
            r = by_entry.get(entry_id)
            if r is None:
                return False, False, {}
            excluded = excluded or r.outcome == OUTCOME_EXCLUDE_ROW
            values.update(dict(r.values))
        return True, excluded, values

    included: dict[str, MasterSet] = {}
    for s in (*preview.sets, *preview.pending_sets):
        resolved, excluded, values = settled(s.blocking_entry_ids)
        if s.plan_code != plan_code or not resolved or excluded:
            continue
        meter = values.get("meter_type", s.meter_type)
        component = values.get("driving_component", s.driving_component)
        included[s.set_identity] = MasterSet(
            model_variant=s.model_variant, section=s.section, set_code=s.set_code, meter_type=PmTriggerType(meter),
            interval_value=s.interval_value, interval_unit=s.interval_unit, raw_interval=s.raw_interval,
            independent_group=s.independent_group, driving_component=ComponentRole(component) if component else None,
            source_doc=s.source_doc, source_ref=f"{preview.source_file}!{s.source_row}", raw=s.raw,
            topology=s.topology, meter_basis="REVIEW_RESOLUTION" if "meter_type" in values else s.meter_basis)

    items_by_set: dict[str, list[MasterItem]] = {}
    for i in (*preview.items, *preview.pending_items):
        resolved, excluded, _ = settled(i.blocking_entry_ids)
        if not resolved or excluded:
            continue
        for identity in i.linked_set_identities:
            if identity in included:
                items_by_set.setdefault(identity, []).append(MasterItem(
                    item_key=i.item_key, sequence=i.sequence, task_text=i.task_text, method=i.method,
                    standard=i.standard, source_ref=f"{preview.source_file}!{i.source_row}", raw=i.raw))

    problems = [{"where": e.row_or_key, "issue": f"UNRESOLVED_REVIEW:{e.issue}", "entry_id": e.entry_id}
                for e in preview.ledger
                if e.action == REVIEW and (plan_code in e.plan_scope or GLOBAL_PLAN_SCOPE in e.plan_scope)
                and e.entry_id not in by_entry]
    ordered = tuple(s.model_copy(update={"items": tuple(sorted(items_by_set.get(identity, []),
                                                               key=lambda m: (m.sequence, m.item_key)))})
                    for identity, s in sorted(included.items(), key=lambda kv: kv[1].set_key))
    return ordered, problems


_PROJECTED_SET_FIELDS = ("model_variant", "section", "set_code", "independent_group", "source_doc")
_PROJECTED_ITEM_FIELDS = ("task_text", "method", "standard")


def validate_candidate(plan_code: str, sets: Sequence[MasterSet]) -> list[dict[str, str]]:
    """Every structural reason the candidate cannot become ACTIVE."""
    problems: list[dict[str, str]] = []

    def bad(where: str, issue: str) -> None:
        problems.append({"where": where, "issue": issue})

    if not plan_code.strip():
        bad("plan", "PLAN_CODE_REQUIRED")
    if not sets:
        bad("plan", "NO_SETS")
    seen_sets: set[str] = set()
    for s in sets:
        key = s.set_key
        if key in seen_sets:
            bad(key, "DUPLICATE_SET")
        seen_sets.add(key)
        expected_unit = {UNIT_HOUR: "hour", UNIT_KM: "km"}.get(s.interval_unit, s.interval_unit)
        if s.meter_type.value not in METER_UNITS:
            bad(key, "METER_NOT_EXPLICIT")
        elif expected_unit != METER_UNITS[s.meter_type.value]:
            bad(key, "UNIT_METER_MISMATCH")
        if not s.interval_value > 0:
            bad(key, "INVALID_INTERVAL")
        if s.driving_component is None:
            bad(key, "DRIVING_COMPONENT_ABSENT")
        if not s.items:
            bad(key, "NO_ITEMS")
        # RV-B1-R3-02: an ambiguous raw 35 never becomes active Master data (raw
        # provenance in `raw` is kept; only projected business fields are checked).
        for field_ in _PROJECTED_SET_FIELDS:
            if getattr(s, field_).strip() == AMBIGUOUS_RAW:
                bad(f"{key}/{field_}", "SEMANTIC_RAW_35_IN_ACTIVE_FIELD")
        seen_items: set[str] = set()
        for item in s.items:
            if not item.item_key.strip():
                bad(key, "ITEM_KEY_REQUIRED")
            elif item.item_key in seen_items:
                bad(f"{key}/{item.item_key}", "DUPLICATE_ITEM_KEY")
            seen_items.add(item.item_key)
            if not item.task_text.strip():
                bad(f"{key}/{item.item_key}", "TASK_TEXT_REQUIRED")
            for field_ in _PROJECTED_ITEM_FIELDS:
                if getattr(item, field_).strip() == AMBIGUOUS_RAW:
                    bad(f"{key}/{item.item_key}/{field_}", "SEMANTIC_RAW_35_IN_ACTIVE_FIELD")
    return problems


def _content(item: MasterItem) -> tuple[str, str, str, int]:
    return (" ".join(item.task_text.split()), item.method, item.standard, item.sequence)


def _substantive(evidence: str, *forbidden: str) -> bool:
    text_ = evidence.strip()
    return len(text_) >= MIN_EVIDENCE_LENGTH and text_ not in forbidden


def resolve_lineage(previous: Sequence[MasterSet], current: Sequence[MasterSet],
                    decisions: Sequence[LineageDecision]) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """(lineage rows, problems). See module docstring LINEAGE."""
    problems: list[dict[str, str]] = []
    rows: list[dict[str, object]] = []
    old_by_set = {s.set_key: {i.item_key: i for i in s.items} for s in previous}
    new_keys = {(s.set_key, i.item_key) for s in current for i in s.items}
    counted = Counter((d.set_key, d.item_key) for d in decisions)
    by_item = {(d.set_key, d.item_key): d for d in decisions}
    for d in decisions:
        where = f"{d.set_key}/{d.item_key}"
        if counted[(d.set_key, d.item_key)] > 1:
            problems.append({"where": where, "issue": "DUPLICATE_LINEAGE_DECISION"})
        if (d.set_key, d.item_key) not in new_keys:
            problems.append({"where": where, "issue": "LINEAGE_DECISION_UNKNOWN_ITEM"})
        if d.set_key not in old_by_set:
            problems.append({"where": where, "issue": "LINEAGE_WITHOUT_PREVIOUS_SET"})
        if not _substantive(d.evidence, d.item_key, d.predecessor_item_key):
            problems.append({"where": where, "issue": "LINEAGE_EVIDENCE_NOT_SUBSTANTIVE"})

    for s in current:
        old = old_by_set.get(s.set_key)
        if old is None:
            rows.extend({"set_key": s.set_key, "item_key": i.item_key, "status": LINEAGE_NEW} for i in s.items)
            continue
        continued: Counter[str] = Counter()
        retained: set[str] = set()
        for item in s.items:
            row: dict[str, object] = {"set_key": s.set_key, "item_key": item.item_key}
            decision = by_item.get((s.set_key, item.item_key))
            prior = old.get(item.item_key)
            if decision is None and prior is not None and _content(prior) == _content(item):
                row["status"] = LINEAGE_RETAINED
                retained.add(item.item_key)
            elif decision is None:
                row["status"] = LINEAGE_AMBIGUOUS
                problems.append({"where": f"{s.set_key}/{item.item_key}", "issue": "AMBIGUOUS_LINEAGE"})
            elif not decision.predecessor_item_key:
                row.update(status=LINEAGE_DECLARED_NEW, evidence=decision.evidence)
            else:
                pred = decision.predecessor_item_key
                if pred not in old:
                    problems.append({"where": f"{s.set_key}/{item.item_key}", "issue": "PREDECESSOR_NOT_IN_PREVIOUS_SET"})
                continued[pred] += 1
                row.update(status=LINEAGE_CONTINUES, previous_item_key=pred, evidence=decision.evidence)
            rows.append(row)
        for pred, n in continued.items():
            if n > 1:
                problems.append({"where": f"{s.set_key}/{pred}", "issue": "PREDECESSOR_CONTINUED_TWICE"})
            if pred in retained:
                problems.append({"where": f"{s.set_key}/{pred}", "issue": "PREDECESSOR_STILL_RETAINED"})
        rows.extend({"set_key": s.set_key, "item_key": k, "status": LINEAGE_REMOVED}
                    for k in sorted(old) if k not in retained and k not in continued)
    current_keys = {s.set_key for s in current}
    for s in previous:
        if s.set_key not in current_keys:
            rows.extend({"set_key": s.set_key, "item_key": i.item_key, "status": LINEAGE_REMOVED} for i in s.items)
    return sorted(rows, key=lambda r: (str(r["set_key"]), str(r["item_key"]))), problems


_SET_FIELDS = ("meter_type", "interval_value", "interval_unit", "raw_interval", "independent_group",
               "driving_component", "source_doc")


def compare_sets(previous: Sequence[MasterSet], current: Sequence[MasterSet],
                 lineage: Sequence[dict[str, object]] = ()) -> dict[str, object]:
    """Audited Set-level difference between two revisions plus the item lineage."""
    old = {s.set_key: s for s in previous}
    new = {s.set_key: s for s in current}
    changed: list[dict[str, object]] = []
    for key in sorted(old.keys() & new.keys()):
        a, b = old[key].model_dump(mode="json"), new[key].model_dump(mode="json")
        fields = {f: {"from": a[f], "to": b[f]} for f in _SET_FIELDS if a[f] != b[f]}
        if fields:
            changed.append({"set_key": key, "fields": fields})
    return {"sets_added": sorted(new.keys() - old.keys()), "sets_removed": sorted(old.keys() - new.keys()),
            "sets_changed": changed, "items": list(lineage)}


def content_digest(plan_code: str, sets: Sequence[MasterSet]) -> str:
    body = {"plan_code": plan_code, "sets": [s.model_dump(mode="json") for s in sets]}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Mock store (in-memory, never a Repository)
# ---------------------------------------------------------------------------


class PmMasterMockStore:
    """In-memory Mock state. Each commit replaces the containers in one step (copy
    then assign), so a refused or failed write leaves nothing behind. Events are
    stored as read-only mappings. The lock is single-process only (not R11)."""

    def __init__(self) -> None:
        self.revisions: dict[str, tuple[MasterRevision, ...]] = {}
        self.assignments: tuple[AssignmentRecord, ...] = ()
        self.previews: tuple[PreviewRegistration, ...] = ()
        self.resolutions: tuple[ReviewResolution, ...] = ()
        self.events: tuple[Mapping[str, str], ...] = ()
        self.lock = asyncio.Lock()

    def head(self, plan_code: str) -> MasterRevision | None:
        revisions = self.revisions.get(plan_code, ())
        return revisions[-1] if revisions else None

    def latest_assignment(self, vehicle_id: str, assembly: str) -> AssignmentRecord | None:
        hits = [a for a in self.assignments if (a.vehicle_id, a.assembly) == (vehicle_id, assembly)]
        return hits[-1] if hits else None

    def preview(self, preview_id: str) -> PreviewRegistration | None:
        return next((p for p in self.previews if p.preview_id == preview_id), None)

    def latest_preview(self, source_file: str) -> PreviewRegistration | None:
        hits = [p for p in self.previews if p.source_file == source_file]
        return hits[-1] if hits else None

    def commit(self, event: dict[str, str], *, revision: MasterRevision | None = None,
               assignment: AssignmentRecord | None = None, preview: PreviewRegistration | None = None,
               resolution: ReviewResolution | None = None) -> None:
        revisions = dict(self.revisions)
        if revision is not None:
            revisions[revision.plan_code] = (*revisions.get(revision.plan_code, ()), revision)
        assignments = (*self.assignments, assignment) if assignment is not None else self.assignments
        previews = (*self.previews, preview) if preview is not None else self.previews
        resolutions = (*self.resolutions, resolution) if resolution is not None else self.resolutions
        events = (*self.events, MappingProxyType(dict(event)))
        (self.revisions, self.assignments, self.previews, self.resolutions,
         self.events) = revisions, assignments, previews, resolutions, events


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _reason(raw: object) -> str:
    value = raw.strip() if isinstance(raw, str) else ""
    if not value or len(value) > MAX_REASON_LENGTH:
        raise _unprocessable("VALIDATION_ERROR", f"a reason of 1..{MAX_REASON_LENGTH} characters is required")
    return value


def _request_id(raw: object) -> str:
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        raise _unprocessable("REQUEST_ID_REQUIRED", "a request id is required for a PM Master write")
    return value


def _actor(context: object) -> str:
    return str(getattr(context, "user_id", "") or "")


def _proof_error(issue: str, details: dict[str, object] | None = None) -> ApiError:
    return _unprocessable("PM_MASTER_PUBLISH_PROOF_INVALID", "the publish proof is missing, stale or does not match",
                          {"issue": issue, **(details or {})})


class PmMasterService:
    def __init__(self, store: PmMasterMockStore, *, authorizer: MasterAuthorizer = deny_unproven_master_authority,
                 vehicle_resolver: MockVehicleResolver | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._store = store
        self._authorize = authorizer
        self._vehicles = vehicle_resolver
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

    def audit(self, context: object) -> tuple[Mapping[str, str], ...]:
        """Read-only views of the append-only events (RV-B1-04): a caller cannot
        change what later reads, replay or revisions see."""
        require_capability(context, CAN_VIEW, "PM Master audit read")
        return tuple(MappingProxyType(dict(e)) for e in self._store.events)

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
            raise _unprocessable("VALIDATION_ERROR", "selected Sets must be non-empty and belong to the revision",
                                 {"unknown_set_keys": unknown})
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

    def _event(self, kind: str, context: object, *, request_id: str, fingerprint: str, reason: str,
               **cells: str) -> dict[str, str]:
        row = dict.fromkeys(("plan_code", "revision_id", "vehicle_id", "assembly", "version", "preview_id",
                             "entry_id", "resolution_id", "diff_json"), "")
        row.update(event_id=f"PMMEV-{uuid.uuid4().hex}", kind=kind, actor_user_id=_actor(context),
                   actor_personnel_id=str(getattr(context, "personnel_id", "") or ""),
                   recorded_at=self._clock().isoformat(), reason=reason, request_id=request_id,
                   request_fingerprint=fingerprint, **cells)
        return row

    def _replay(self, request_id: str, fingerprint: str, record_id_column: str):
        lookup = find_replay(self._store.events, request_id, fingerprint, record_id_column=record_id_column)
        if lookup is not None and not lookup.replayed:
            raise _error("REQUEST_ID_REUSED", "this request id was already used for a different request",
                         status.HTTP_409_CONFLICT, {"request_id": request_id})
        return lookup

    async def register_preview(self, context: object, *, workbook: Mapping[str, Sequence[Mapping[str, object]]],
                               source_file: str, reason: str, request_id: str,
                               approved_aliases: Sequence[Sequence[str]] = ()) -> PreviewRegistration:
        """Compute (never accept) the source-shaped preview and register it as the
        current proof basis for `source_file`. `approved_aliases` are explicit,
        evidenced (PLAN|MODEL, source label, mapping label, evidence) equivalences;
        they become part of the preview digest. Nothing else is written."""
        self._authorize(context, KIND_PREVIEW)
        reason_, request_id_ = _reason(reason), _request_id(request_id)
        if not source_file.strip():
            raise _unprocessable("VALIDATION_ERROR", "source_file is required")
        try:
            preview = preview_maintenance_source(workbook, source_file=source_file, approved_aliases=approved_aliases)
        except ValueError as exc:
            raise _unprocessable("PM_MASTER_ALIAS_INVALID", str(exc)) from exc
        fingerprint = request_fingerprint(OP_MASTER_PREVIEW, source_file, _actor(context),
                                          {"source_digest": preview.digest, "reason": reason_})
        await asyncio.sleep(0)
        async with self._store.lock:
            if (lookup := self._replay(request_id_, fingerprint, "preview_id")) is not None:
                return self._store.preview(lookup.record_ids[0])
            registration = PreviewRegistration(
                preview_id=f"PMPV-{len(self._store.previews) + 1:04d}-{preview.digest[:12]}", source_file=source_file,
                source_digest=preview.digest, registered_by=_actor(context), registered_at=self._clock(),
                preview=preview)
            self._store.commit(self._event(KIND_PREVIEW, context, request_id=request_id_, fingerprint=fingerprint,
                                           reason=reason_, preview_id=registration.preview_id),
                               preview=registration)
            return registration

    async def record_review(self, context: object, *, preview_id: str, expected_source_digest: str, entry_id: str,
                            outcome: str, evidence: str, request_id: str,
                            values: Mapping[str, str] | None = None) -> ReviewResolution:
        """Resolve ONE REVIEW ledger entry of ONE registered preview, append-only."""
        self._authorize(context, KIND_REVIEW)
        request_id_ = _request_id(request_id)
        values_ = tuple(sorted((values or {}).items()))
        body = {"preview_id": preview_id, "expected_source_digest": expected_source_digest, "entry_id": entry_id,
                "outcome": outcome, "values": [list(v) for v in values_], "evidence": evidence}
        fingerprint = request_fingerprint(OP_MASTER_REVIEW, preview_id, _actor(context), body)
        await asyncio.sleep(0)
        async with self._store.lock:
            if (lookup := self._replay(request_id_, fingerprint, "resolution_id")) is not None:
                return next(r for r in self._store.resolutions if r.resolution_id == lookup.record_ids[0])
            registration = self._store.preview(preview_id)
            if registration is None:
                raise _unprocessable("PM_MASTER_REVIEW_INVALID", "preview is not registered", {"issue": "PREVIEW_NOT_FOUND"})
            if registration.source_digest != expected_source_digest:
                raise _unprocessable("PM_MASTER_REVIEW_INVALID", "digest does not match the preview",
                                     {"issue": "DIGEST_MISMATCH"})
            entry = next((e for e in registration.preview.ledger if e.entry_id == entry_id), None)
            if entry is None or entry.action != REVIEW:
                raise _unprocessable("PM_MASTER_REVIEW_INVALID", "no REVIEW entry with this id in the preview",
                                     {"issue": "ENTRY_NOT_FOUND"})
            if any(r.preview_id == preview_id and r.entry_id == entry_id for r in self._store.resolutions):
                raise _error("PM_MASTER_REVIEW_ALREADY_RESOLVED", "this entry is already resolved (append-only)",
                             status.HTTP_409_CONFLICT)
            if outcome not in allowed_outcomes(entry.issue):
                raise _unprocessable("PM_MASTER_REVIEW_INVALID", "outcome not allowed for this issue",
                                     {"issue": "OUTCOME_NOT_ALLOWED", "allowed": list(allowed_outcomes(entry.issue))})
            if not _substantive(evidence, entry_id, entry.issue):
                raise _unprocessable("PM_MASTER_REVIEW_INVALID", "substantive evidence is required",
                                     {"issue": "EVIDENCE_NOT_SUBSTANTIVE"})
            self._check_values(entry.issue, outcome, dict(values_))
            resolution = ReviewResolution(
                resolution_id=f"PMRR-{uuid.uuid4().hex}", preview_id=preview_id,
                source_digest=registration.source_digest, entry_id=entry_id, issue=entry.issue, outcome=outcome,
                values=values_, evidence=evidence.strip(), reviewer=_actor(context), reviewed_at=self._clock())
            self._store.commit(self._event(KIND_REVIEW, context, request_id=request_id_, fingerprint=fingerprint,
                                           reason=evidence.strip(), preview_id=preview_id, entry_id=entry_id,
                                           resolution_id=resolution.resolution_id),
                               resolution=resolution)
            return resolution

    @staticmethod
    def _check_values(issue: str, outcome: str, values: dict[str, str]) -> None:
        if outcome != OUTCOME_RESOLVE_METER:
            if values:
                raise _unprocessable("PM_MASTER_REVIEW_INVALID", "this outcome takes no values",
                                     {"issue": "UNEXPECTED_VALUES"})
            return
        meter, component = values.get("meter_type", ""), values.get("driving_component", "")
        allowed = HOUR_METER_COMPONENTS.get(meter)
        if (issue != ISSUE_METER_UNRESOLVED or set(values) != {"meter_type", "driving_component"} or allowed is None
                or component not in {c.value for c in allowed}):
            raise _unprocessable("PM_MASTER_REVIEW_INVALID", "an HOUR Set resolves to ENGINE_HOUR with a carrier / "
                                 "crane engine, or PTO_HOUR with PTO", {"issue": "INVALID_METER_RESOLUTION"})

    async def publish(self, context: object, *, plan_code: str, expected_revision: int, preview_id: str,
                      expected_source_digest: str, reason: str, request_id: str,
                      lineage: Sequence[LineageDecision] = ()) -> PublishOutcome:
        self._authorize(context, KIND_PUBLISH)  # before any replay is disclosed
        reason_, request_id_ = _reason(reason), _request_id(request_id)
        lineage = tuple(lineage)
        body = {"plan_code": plan_code, "expected_revision": expected_revision, "preview_id": preview_id,
                "expected_source_digest": expected_source_digest, "reason": reason_,
                "lineage": [d.model_dump(mode="json") for d in lineage]}
        fingerprint = request_fingerprint(OP_MASTER_PUBLISH, plan_code, _actor(context), body)
        await asyncio.sleep(0)  # a real interleaving point before the single-writer section
        async with self._store.lock:
            if (lookup := self._replay(request_id_, fingerprint, "revision_id")) is not None:
                revision = next(r for r in self._store.revisions.get(plan_code, ())
                                if r.revision_id in lookup.record_ids)
                return PublishOutcome(revision, True, json.loads(lookup.rows[0]["diff_json"]))
            registration = self._store.preview(preview_id)
            if registration is None:
                raise _proof_error("PREVIEW_NOT_FOUND")
            if registration.source_digest != expected_source_digest:
                raise _proof_error("DIGEST_MISMATCH")
            latest = self._store.latest_preview(registration.source_file)
            if latest is None or latest.preview_id != preview_id:
                raise _proof_error("PREVIEW_STALE", {"current_preview_id": latest.preview_id if latest else None})
            resolutions = tuple(r for r in self._store.resolutions
                                if r.preview_id == preview_id and r.source_digest == registration.source_digest)
            sets, problems = build_candidate(registration.preview, plan_code, resolutions)
            problems += validate_candidate(plan_code, sets)
            if problems:
                raise _unprocessable("PM_MASTER_VALIDATION_FAILED", "the candidate cannot become an active revision",
                                     {"problems": problems})
            head = self._store.head(plan_code)
            current = head.revision_number if head else 0
            if expected_revision != current:
                raise _error("PM_MASTER_STALE_REVISION", "the PM Master changed since it was read",
                             status.HTTP_409_CONFLICT, {"expected_revision": expected_revision,
                                                        "current_revision": current})
            lineage_rows, lineage_problems = resolve_lineage(head.sets if head else (), sets, lineage)
            if lineage_problems:
                raise _unprocessable("PM_MASTER_LINEAGE_UNRESOLVED", "item lineage is ambiguous or invalid",
                                     {"problems": lineage_problems})
            digest = content_digest(plan_code, sets)
            if head is not None and head.content_digest == digest:
                raise _unprocessable("PM_MASTER_UNCHANGED", "the candidate is identical to the effective revision")
            number = current + 1
            diff = compare_sets(head.sets if head else (), sets, lineage_rows)
            revision = MasterRevision(
                revision_id=f"PMMREV-{plan_code}-{number:04d}", plan_code=plan_code, revision_number=number,
                sets=sets, content_digest=digest, published_at=self._clock(), published_by=_actor(context),
                reason=reason_, request_id=request_id_, preview_id=preview_id,
                source_digest=registration.source_digest,
                resolution_ids=tuple(sorted(r.resolution_id for r in resolutions)), lineage=lineage)
            event = self._event(KIND_PUBLISH, context, plan_code=plan_code, request_id=request_id_,
                                fingerprint=fingerprint, reason=reason_, revision_id=revision.revision_id,
                                version=str(number), preview_id=preview_id, diff_json=canonical_json(diff))
            self._store.commit(event, revision=revision)
            return PublishOutcome(revision, False, diff)

    async def set_assignment(self, context: object, *, vehicle_id: str, assembly: str = "", plan_code: str | None,
                             expected_version: int, reason: str, request_id: str) -> AssignmentOutcome:
        """Assign / change (plan_code set) or explicitly unassign (plan_code None ->
        NONE) one vehicle or assembly. Requires the Mock-only vehicle resolver;
        version-checked, reasoned and audited."""
        self._authorize(context, KIND_ASSIGN)
        reason_, request_id_ = _reason(reason), _request_id(request_id)
        if not isinstance(self._vehicles, MockVehicleResolver):
            raise _error("PM_MASTER_VEHICLE_RESOLVER_REQUIRED",
                         "an assignment needs the verified Mock-only vehicle resolver", status.HTTP_403_FORBIDDEN)
        if assembly not in ASSEMBLIES:
            raise _unprocessable("VALIDATION_ERROR", "assembly must be blank (whole vehicle), CARRIER or CRANE")
        facts = await self._vehicles.resolve(vehicle_id) if vehicle_id.strip() else None
        if facts is None or facts.vehicle_id != vehicle_id:
            raise _error("VEHICLE_NOT_FOUND", f"vehicle '{vehicle_id}' was not found", status.HTTP_404_NOT_FOUND)
        if assembly and ASSEMBLY_ROLE[assembly].value not in facts.component_roles:
            raise _unprocessable("PM_MASTER_ASSEMBLY_NOT_ON_VEHICLE",
                                 f"the vehicle's model declares no {ASSEMBLY_ROLE[assembly].value}",
                                 {"component_roles": sorted(facts.component_roles)})
        body = {"vehicle_id": vehicle_id, "assembly": assembly, "plan_code": plan_code,
                "expected_version": expected_version, "reason": reason_}
        fingerprint = request_fingerprint(OP_MASTER_ASSIGNMENT, vehicle_id, _actor(context), body)
        await asyncio.sleep(0)
        async with self._store.lock:
            if (lookup := self._replay(request_id_, fingerprint, "version")) is not None:
                hit = next(a for a in self._store.assignments if (a.vehicle_id, a.assembly, str(a.version)) ==
                           (vehicle_id, assembly, lookup.record_ids[0]))
                return AssignmentOutcome(hit, True)
            if plan_code is not None and self._store.head(plan_code) is None:
                raise _unprocessable("PM_MASTER_NOT_PUBLISHED", f"'{plan_code}' has no published revision")
            prior = self._store.latest_assignment(vehicle_id, assembly)
            current = prior.version if prior else 0
            if expected_version != current:
                raise _error("PM_MASTER_STALE_ASSIGNMENT", "the assignment changed since it was read",
                             status.HTTP_409_CONFLICT, {"expected_version": expected_version,
                                                        "current_version": current})
            state = ASSIGNED if plan_code is not None else NONE
            if prior is not None and (prior.state, prior.plan_code) == (state, plan_code or ""):
                raise _unprocessable("PM_MASTER_ASSIGNMENT_UNCHANGED", "the assignment already has this value")
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
    "VAL_AM_GATE", "ASSIGNED", "NONE", "LINEAGE_RETAINED", "LINEAGE_CONTINUES", "LINEAGE_DECLARED_NEW",
    "LINEAGE_NEW", "LINEAGE_REMOVED", "LINEAGE_AMBIGUOUS", "MasterAuthorizer", "deny_unproven_master_authority",
    "MasterItem", "MasterSet", "LineageDecision", "ReviewResolution", "PreviewRegistration", "MasterRevision",
    "AssignmentRecord", "PlanResolution", "MasterWorkOrderSnapshot", "PublishOutcome", "AssignmentOutcome",
    "VehicleFacts", "MockVehicleResolver", "build_candidate", "validate_candidate", "resolve_lineage",
    "compare_sets", "content_digest", "PmMasterMockStore", "PmMasterService",
]
