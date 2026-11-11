"""INSTANCE_TRACKED part-instance domain service (Phase 5; R6 FINAL plan
§7.2, §7.2a, §7.2b, §7.3a, §7.5, §7.6).

Every write follows ONE contract (FINAL §7.2a):
1. pre-checks (capability at the route; data context; vehicle data scope —
   transfer checks source AND target);
2. replay: a committed `(scope, kind, key, X-Request-Id)` with the same
   fingerprint returns the stored committed response; a different intent ->
   409 PART_REQUEST_CONFLICT; nothing is written either way;
3. machine-state CONTEXT snapshot (existing behaviour; never usage evidence;
   an unreferenced one left by a failed commit is harmless);
4. verified meter anchors from the existing R4 selector `select_current_reading`
   at the event's effective time (F05) — the ONLY usage evidence;
5. a pure plan validated against the loaded state (transition matrix, approval
   state machine, occupancy, physical-identity sufficiency, forward-only
   effective time);
6. `Repository.apply_part_mutation`: copy-on-write, invariants re-validated on
   the candidate, published by one assignment (all or nothing).

Owner decisions implemented: A-1 transition matrix; A-2(i) no direct install
from IN_REPAIR / REMOVED; A-2(ii) a repaired-part cycle opens ONLY inside a
successful install that consumes a pending, authorized, unconsumed approval
(the legacy `start-new-lifecycle` never opens a cycle); A-3 OFF (identifiers
optional at registration; set-once assignment later). Owner policies PG-1…PG-6
stay fail-closed in REAL: e.g. a new-cycle approval is refused in REAL while
PG-2 is pending, and only a TEST context may use TEST-labelled reason codes.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from math import isfinite

from fastapi import status

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_for_new_work
from app.domain.authz import CAN_MANAGE_PM, CAN_MANAGE_REPAIR
from app.domain.common import PageParams, bangkok_today, utc_now
from app.domain.meter_service import MeterService
from app.domain.part import TrackingMode
from app.domain.part_instance import (
    ApprovalState,
    HistoricalEvidenceType,
    InstallationSegment,
    InstallationSegmentStatus,
    LifecycleStartReason,
    MeterAnchor,
    PartInstance,
    PartInstanceDetail,
    PartInstanceStatus,
    PartInstanceStatusEvent,
    PartLifecycle,
    PriorUsage,
    PriorUsageQuality,
    ReferenceStatus,
    position_key,
)
from app.domain.part_lookup import require_part_exists
from app.domain.part_maintenance_event import (
    ACTION_FOR_DUE,
    MaintenanceAction,
    MaintenanceTargetType,
    PartMaintenanceEvent,
)
from app.domain.pm_meter_anchor import select_current_reading
from app.domain.request_replay import canonical_json
from app.errors import ApiError
from app.repositories.base import (
    PART_INSTANCES,
    PART_LIFECYCLES,
    PART_MAINTENANCE,
    PART_SEGMENTS,
    PART_STATUS_EVENTS,
    PartMutation,
    PartMutationRejected,
    PartState,
    Repository,
)

OPERATIONAL_CAPABILITIES = (CAN_MANAGE_REPAIR, CAN_MANAGE_PM)  # PG-5 PROPOSAL (not Owner-approved)
TEST_REASON_PREFIX = "TEST-"
ENGINE_ROLES = frozenset({"CARRIER_ENGINE", "CRANE_ENGINE"})

# A-1 transition matrix (FINAL §7.2) for non-install status moves.
_STATUS_MOVES: dict[PartInstanceStatus, frozenset[PartInstanceStatus]] = {
    PartInstanceStatus.REMOVED: frozenset({PartInstanceStatus.IN_REPAIR, PartInstanceStatus.READY_FOR_INSTALL,
                                           PartInstanceStatus.STOCK, PartInstanceStatus.SCRAPPED}),
    PartInstanceStatus.READY_FOR_INSTALL: frozenset({PartInstanceStatus.IN_REPAIR, PartInstanceStatus.STOCK,
                                                     PartInstanceStatus.SCRAPPED}),
    PartInstanceStatus.STOCK: frozenset({PartInstanceStatus.IN_REPAIR, PartInstanceStatus.READY_FOR_INSTALL,
                                         PartInstanceStatus.SCRAPPED}),
    PartInstanceStatus.IN_REPAIR: frozenset({PartInstanceStatus.SCRAPPED}),
}
_REMOVAL_NEXT_STATUSES = frozenset({PartInstanceStatus.REMOVED, PartInstanceStatus.IN_REPAIR,
                                    PartInstanceStatus.STOCK, PartInstanceStatus.SCRAPPED})
_INSTALLABLE = frozenset({PartInstanceStatus.READY_FOR_INSTALL, PartInstanceStatus.STOCK})
_REGISTRATION_STATUSES = frozenset({PartInstanceStatus.READY_FOR_INSTALL, PartInstanceStatus.STOCK})


# ---------------------------------------------------------------------------
# Shared R6 write plumbing (also used by position / rule / set services)
# ---------------------------------------------------------------------------


def invalid(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


def conflict(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_409_CONFLICT, details=details)


def fingerprint(operation: str, resource_key: str, actor: str | None, body: dict) -> str:
    """R5 shape: sha256 of canonical JSON {op, resource_key, actor, body}."""
    payload = {"op": operation, "resource_key": resource_key, "actor": actor, "body": body}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def request_key(data_context: str | None, kind: str, resource_key: str, request_id: str | None) -> tuple | None:
    return None if request_id is None else (data_context or "", kind, resource_key, request_id)


REPLAYED_HEADER = "X-Request-Replayed"


class Replayed(dict):
    """CG-2: the stored committed response of a replayed request (FINAL §7.2a
    step 2), returned unchanged. The marker is the result's own type — no
    global or request-scoped state — so it cannot leak into another request
    and is equally safe outside HTTP. It serialises exactly like a dict."""

    __slots__ = ()


_REPLAYED_MODELS: dict[type, type] = {}


def is_replayed(result: object) -> bool:
    return isinstance(result, Replayed) or bool(getattr(type(result), "__r6_replayed__", False))


def apply_replay_header(response, result: object) -> None:
    """Set `X-Request-Replayed: true` on an R6 write route's response when the
    result is a replay; a first success, a refusal or a conflict never get it."""
    if is_replayed(result):
        response.headers[REPLAYED_HEADER] = "true"


def to_model(model_cls: type, payload: dict):
    """Build the response model from a committed / replayed payload, keeping
    the replay marker: a replayed payload yields an instance of a cached
    subclass of `model_cls` with identical fields and serialisation."""
    if not is_replayed(payload):
        return model_cls.model_validate(payload)
    flagged = _REPLAYED_MODELS.get(model_cls)
    if flagged is None:
        flagged = type(f"Replayed{model_cls.__name__}", (model_cls,),
                       {"__r6_replayed__": True, "__module__": model_cls.__module__})
        _REPLAYED_MODELS[model_cls] = flagged
    return flagged.model_validate(dict(payload))


def replayed_response(state: PartState, key: tuple | None, operation: str, digest: str) -> dict | None:
    """Replay BEFORE any validation or capture: the committed outcome is
    returned even if the current state would now refuse the same request."""
    if key is None:
        return None
    earlier = state.requests.get(key)
    if earlier is None:
        return None
    if (earlier.operation, earlier.fingerprint) != (operation, digest):
        raise conflict("PART_REQUEST_CONFLICT",
                       "This request id was already used for a different part change; nothing was changed")
    return Replayed(earlier.response)


async def commit(repository: Repository, mutation: PartMutation) -> dict:
    try:
        response, replayed = await repository.apply_part_mutation(mutation)
    except PartMutationRejected as exc:
        raise conflict(exc.code, exc.message, exc.details) from exc
    # A replay detected inside the commit (e.g. the same request won a race) is marked like an early replay.
    return Replayed(response) if replayed else response


def require_aware(value: datetime | None, field: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise invalid("VALIDATION_ERROR", f"{field} must include a timezone offset", {"field": field})


def resolve_effective(effective_at: datetime | None, now: datetime, latest: datetime | None) -> datetime:
    """Forward-only effective time (FINAL §7.7): <= now and >= the target's
    latest effective event. Omitted -> the commit time."""
    require_aware(effective_at, "effective_at")
    value = effective_at or now
    if value > now:
        raise invalid("EFFECTIVE_TIME_IN_FUTURE", "effective_at cannot be in the future")
    if latest is not None and value < latest:
        raise invalid("EFFECTIVE_TIME_BEFORE_LATEST_EVENT",
                      "effective_at cannot be earlier than this part's latest recorded event "
                      "(historical corrections are Owner policy PG-6)", {"latest_effective_at": latest.isoformat()})
    return value


def require_operational_capability(context, action: str) -> None:
    """PG-5 PROPOSAL applied to NEW operational routes (and new-cycle
    approval) in every mode, like the R5 AMB-1 guard. In Access Management
    mode these routes are additionally refused by the D6 unresolved-route
    registry until the Owner approves a mapping."""
    if context is None or not (context.user_id or "").strip() or not any(
            capability in context.capabilities for capability in OPERATIONAL_CAPABILITIES):
        raise ApiError(code="HTTP_ERROR", message=f"{action} requires one of {sorted(OPERATIONAL_CAPABILITIES)}",
                       status_code=status.HTTP_403_FORBIDDEN)


async def require_vehicle_scope(repository: Repository, vehicle_id: str, data_context: str | None,
                                batch_id: str) -> None:
    """The R5 AMB-1 data-scope check: the vehicle resolves exactly once in the
    request's TEST/REAL scope (404 / 409 / 422 otherwise)."""
    from app.domain.crane_driver_responsibility import (
        REFERENCE_AMBIGUOUS,
        REFERENCE_MISSING,
        REFERENCE_SCOPE_UNPROVEN,
        VEHICLE_PREFIX,
        classify_reference,
    )
    from app.domain.crane_driver_timeline import VEHICLE_REFERENCE_TAB
    from app.domain.reference_read import reference_read

    reference = await reference_read(repository.read_vehicle_reference(), VEHICLE_PREFIX, VEHICLE_REFERENCE_TAB)
    kind = classify_reference(vehicle_id, reference, "vehicle_id", data_context or "", batch_id) \
        if vehicle_id.strip() else REFERENCE_MISSING
    if kind == REFERENCE_AMBIGUOUS:
        raise conflict("VEHICLE_ID_AMBIGUOUS", "More than one vehicle record has this id")
    if kind == REFERENCE_SCOPE_UNPROVEN:
        raise invalid("VEHICLE_SCOPE_UNPROVEN", "This vehicle cannot be proven to belong to the request's data scope")
    if kind == REFERENCE_MISSING:
        raise ApiError(code="VEHICLE_NOT_FOUND", message="No vehicle record has exactly this id",
                       status_code=status.HTTP_404_NOT_FOUND)


def require_data_context(data_context: str | None, batch_id: str) -> str:
    from app.domain.registry_write_support import require_write_context

    return require_write_context(data_context, batch_id)


async def verified_anchors(repository: Repository, source, vehicle_id: str, at: datetime) -> list[MeterAnchor]:
    """F05: one call of the existing R4 selector per anchor dimension
    (ODOMETER + ENGINE_HOUR of each CARRIER_ENGINE / CRANE_ENGINE component),
    with exactly its inputs: the source's own observations (`not_after=at`),
    `vehicle_id`, `components`, `counter_type`, `component_id`, `at` and the
    source's `max_observation_age`. A dimension without an eligible reading
    yields no anchor (UNKNOWN later). PTO never yields a dimension."""
    components = [(c.component_id, c.component_role.value)
                  for c in await repository.list_vehicle_components(vehicle_id)]
    observations = await source.observations(vehicle_id, not_after=at)
    dimensions = [("ODOMETER", None)] + [("ENGINE_HOUR", cid) for cid, role in sorted(components)
                                         if role in ENGINE_ROLES]
    anchors: list[MeterAnchor] = []
    for counter_type, component_id in dimensions:
        reading = select_current_reading(observations, vehicle_id=vehicle_id, components=components,
                                         counter_type=counter_type, component_id=component_id, at=at,
                                         max_observation_age=source.max_observation_age)
        if reading is not None:
            anchors.append(MeterAnchor(vehicle_id=vehicle_id, component_id=reading.component_id,
                                       counter_type=reading.counter_type, value=float(reading.value),
                                       observed_at=reading.observed_at, received_at=reading.received_at,
                                       time_quality=reading.time_quality, device_id=reading.device_id,
                                       device_event_id=reading.device_event_id))
    return anchors


async def resolve_reference(repository: Repository, evidence_type: HistoricalEvidenceType,
                            reference: str) -> ReferenceStatus:
    """F02: RESOLVED only when the reference names an existing work order or
    attachment (the Mock is a single TEST scope; other modes fail closed)."""
    ref = reference.strip()
    if await repository.get_pm_work_order(ref) is not None or await repository.get_repair(ref) is not None:
        return ReferenceStatus.RESOLVED
    if evidence_type == HistoricalEvidenceType.WORK_ORDER:
        raise invalid("EVIDENCE_REFERENCE_NOT_FOUND",
                      "A WORK_ORDER reference must name an existing PM or Repair work order", {"field": "evidence_reference"})
    if await repository.get_attachment(ref) is not None:
        return ReferenceStatus.RESOLVED
    return ReferenceStatus.REFERENCE_UNVERIFIED


async def validate_declaration(repository: Repository, declaration: PriorUsage, *, actor: str | None,
                               now: datetime, field: str) -> PriorUsage:
    """FINAL §7.3a: validate one historical usage declaration and set the
    server-derived fields (reference_status, declared_by, declared_at). The
    body can never set them."""
    base = declaration.model_copy(update={"reference_status": None, "declared_by": actor, "declared_at": now})
    if declaration.quality == PriorUsageQuality.UNKNOWN:
        if declaration.value is not None:
            raise invalid("HISTORICAL_USAGE_VALUE_FOR_UNKNOWN", "An UNKNOWN declaration must not carry a value",
                          {"field": field})
        return base.model_copy(update={"basis": None, "component_role": None, "as_of": None,
                                       "evidence_type": None, "evidence_reference": None})
    value = declaration.value
    if value is None or isinstance(value, bool) or not isfinite(float(value)) or float(value) < 0:
        raise invalid("HISTORICAL_USAGE_VALUE_INVALID", "KNOWN / PARTIAL needs a finite value >= 0", {"field": field})
    if declaration.evidence_type is None:
        raise invalid("HISTORICAL_USAGE_EVIDENCE_REQUIRED", "KNOWN / PARTIAL needs an evidence type", {"field": field})
    new_part = declaration.evidence_type == HistoricalEvidenceType.NEW_PART
    if new_part and not (declaration.quality == PriorUsageQuality.KNOWN and float(value) == 0):
        raise invalid("HISTORICAL_USAGE_CONTRADICTION", "NEW_PART evidence is valid only for KNOWN 0",
                      {"field": field})
    basis = declaration.basis.value if declaration.basis else None
    if basis is None and not new_part:
        raise invalid("BASIS_REQUIRED", "KNOWN / PARTIAL needs a basis (ENGINE_HOUR or ODOMETER)", {"field": field})
    if basis is not None and basis not in ("ENGINE_HOUR", "ODOMETER"):
        raise invalid("BASIS_UNSUPPORTED", f"'{basis}' cannot carry a historical usage value", {"field": field})
    role = declaration.component_role.value if declaration.component_role else None
    if basis == "ENGINE_HOUR" and role not in ENGINE_ROLES:
        raise invalid("BASIS_COMPONENT_ROLE_REQUIRED", "ENGINE_HOUR needs CARRIER_ENGINE or CRANE_ENGINE",
                      {"field": field})
    if basis == "ODOMETER" and role is not None:
        raise invalid("BASIS_COMPONENT_ROLE_INVALID", "ODOMETER is vehicle-level (no component role)", {"field": field})
    if declaration.as_of is None:
        raise invalid("HISTORICAL_USAGE_AS_OF_REQUIRED", "KNOWN / PARTIAL needs as_of", {"field": field})
    if declaration.as_of > bangkok_today():
        raise invalid("HISTORICAL_USAGE_AS_OF_IN_FUTURE", "as_of cannot be after enrolment", {"field": field})
    if not (declaration.evidence_reference or "").strip():
        raise invalid("HISTORICAL_USAGE_EVIDENCE_REQUIRED", "KNOWN / PARTIAL needs an evidence reference",
                      {"field": field})
    reference_status = await resolve_reference(repository, declaration.evidence_type, declaration.evidence_reference)
    return base.model_copy(update={"value": float(value), "evidence_reference": declaration.evidence_reference.strip(),
                                   "reference_status": reference_status})


def check_declaration_pair(prior: PriorUsage, cycle: PriorUsage | None) -> None:
    if cycle is None:
        return
    if prior.quality == PriorUsageQuality.UNKNOWN:
        raise invalid("HISTORICAL_USAGE_CONTRADICTION", "A cycle declaration needs a known lifetime declaration")
    if cycle.quality == PriorUsageQuality.UNKNOWN:
        return
    if prior.evidence_type == HistoricalEvidenceType.NEW_PART and (cycle.value or 0) != 0:
        raise invalid("HISTORICAL_USAGE_CONTRADICTION", "A brand-new part cannot carry prior cycle usage")
    if prior.basis is not None and cycle.basis is not None and (
            prior.basis != cycle.basis or prior.component_role != cycle.component_role):
        raise invalid("HISTORICAL_USAGE_CONTRADICTION", "Lifetime and cycle declarations use different bases")
    if (prior.quality == cycle.quality == PriorUsageQuality.KNOWN and prior.basis == cycle.basis
            and float(cycle.value) > float(prior.value)):
        raise invalid("HISTORICAL_USAGE_CONTRADICTION", "Cycle usage cannot exceed lifetime usage")


def detail_from_state(state: PartState, instance_id: str) -> PartInstanceDetail:
    instance = state.instances[instance_id]
    return PartInstanceDetail(
        instance=instance,
        lifecycles=sorted(state.lifecycles.get(instance_id, ()), key=lambda lc: lc.cycle_number),
        segments=sorted(state.segments.get(instance_id, ()), key=lambda s: (s.effective_start, s.segment_id)),
        status_events=list(state.status_events.get(instance_id, ())),
    )


def detail_response(instance_id: str):
    def build(state: PartState) -> dict:
        return detail_from_state(state, instance_id).model_dump(mode="json")
    return build


def latest_effective(detail: PartInstanceDetail) -> datetime | None:
    times = [e.effective_at for e in detail.status_events]
    for segment in detail.segments:
        times.append(segment.effective_start)
        if segment.effective_end is not None:
            times.append(segment.effective_end)
    return max(times) if times else None


def approval_state(detail: PartInstanceDetail) -> tuple[ApprovalState, PartInstanceStatusEvent | None]:
    """FINAL §7.2b: NONE / PENDING / CONSUMED / SUPERSEDED of the latest
    approved return."""
    events = detail.status_events
    index = next((i for i in range(len(events) - 1, -1, -1)
                  if events[i].operation == OP_RETURN and events[i].new_cycle_approved), None)
    if index is None:
        return ApprovalState.NONE, None
    event = events[index]
    if any(lc.start_trigger_event_id == event.event_id for lc in detail.lifecycles):
        return ApprovalState.CONSUMED, event
    for later in events[index + 1:]:
        if later.to_status in (PartInstanceStatus.IN_REPAIR, PartInstanceStatus.SCRAPPED,
                               PartInstanceStatus.INSTALLED):
            return ApprovalState.SUPERSEDED, event
    return ApprovalState.PENDING, event


async def require_equipment_scope(repository: Repository, equipment_id: str, data_context: str | None,
                                  batch_id: str) -> None:
    """CG-1: the equipment resolves exactly once in the request's TEST/REAL
    scope, using the SAME equipment reference master and classifier as the
    equipment caretaker feature (`classify_reference` on
    `read_equipment_reference`; raw-text id match, so leading zeros are kept).
    Error codes are the caretaker's: 409 EQUIPMENT_ID_AMBIGUOUS, 422
    EQUIPMENT_SCOPE_UNPROVEN, 404 EQUIPMENT_NOT_FOUND."""
    from app.domain.caretaker_timeline import EQUIPMENT_REFERENCE_TAB
    from app.domain.equipment_caretaker import (
        EQUIPMENT_PREFIX,
        REFERENCE_AMBIGUOUS,
        REFERENCE_MISSING,
        REFERENCE_SCOPE_UNPROVEN,
        classify_reference,
    )
    from app.domain.reference_read import reference_read

    reference = await reference_read(repository.read_equipment_reference(), EQUIPMENT_PREFIX, EQUIPMENT_REFERENCE_TAB)
    kind = classify_reference(equipment_id, reference, "equipment_id", data_context or "", batch_id) \
        if equipment_id.strip() else REFERENCE_MISSING
    if kind == REFERENCE_AMBIGUOUS:
        raise conflict("EQUIPMENT_ID_AMBIGUOUS", "More than one equipment record has this id")
    if kind == REFERENCE_SCOPE_UNPROVEN:
        raise invalid("EQUIPMENT_SCOPE_UNPROVEN", "This equipment cannot be proven to belong to the request's data scope")
    if kind == REFERENCE_MISSING:
        raise ApiError(code="EQUIPMENT_NOT_FOUND", message="No equipment record has exactly this id",
                       status_code=status.HTTP_404_NOT_FOUND)


async def require_asset_scope(repository: Repository, asset_type: AssetType | None, asset_id: str | None,
                              data_context: str | None, batch_id: str) -> None:
    """CG-1: the one data-scope check for any asset a part operation touches
    or exposes (VEHICLE: the R5 AMB-1 check; EQUIPMENT: the caretaker
    reference). Scope comes only from the server data context and the
    reference rows, never from the request or the id text."""
    if asset_type == AssetType.VEHICLE:
        await require_vehicle_scope(repository, asset_id or "", data_context, batch_id)
    elif asset_type == AssetType.EQUIPMENT:
        await require_equipment_scope(repository, asset_id or "", data_context, batch_id)


async def require_segments_scope(repository: Repository, segments, data_context: str | None, batch_id: str) -> None:
    """CG-1: every asset an instance was ever installed on is in scope, so a
    write, a replayed response or a read never crosses scopes through history."""
    for asset_type, asset_id in dict.fromkeys((s.asset_type, s.asset_id) for s in segments):
        await require_asset_scope(repository, asset_type, asset_id, data_context, batch_id)


class AssetScopeFilter:
    """CG-1 for list reads: memoised in-scope test per asset (rows of other
    scopes are omitted, never an error for the whole list)."""

    def __init__(self, repository: Repository, data_context: str | None, batch_id: str) -> None:
        self._repository = repository
        self._data_context = data_context
        self._batch_id = batch_id
        self._cache: dict[tuple, bool] = {}

    async def allows(self, asset_type: AssetType | None, asset_id: str | None) -> bool:
        key = (asset_type, asset_id)
        if key not in self._cache:
            try:
                await require_asset_scope(self._repository, asset_type, asset_id, self._data_context, self._batch_id)
                self._cache[key] = True
            except ApiError:
                self._cache[key] = False
        return self._cache[key]

    async def allows_segments(self, segments) -> bool:
        for segment in segments:
            if not await self.allows(segment.asset_type, segment.asset_id):
                return False
        return True


def externally_identified(instance: PartInstance) -> bool:
    return bool((instance.serial_number or "").strip() or (instance.tag_label or "").strip())


def identity_issue(state: PartState, instance: PartInstance, location: str | None) -> str | None:
    """FINAL §7.5 R3-05 I-1…I-4 for a movement of `instance` into or out of
    non-installed custody at `location` (blank = unknown, possibly anywhere)."""
    if externally_identified(instance):
        return None
    peers = [p for p in state.instances.values()
             if p.part_instance_id != instance.part_instance_id and p.part_id == instance.part_id
             and p.status not in (PartInstanceStatus.INSTALLED, PartInstanceStatus.SCRAPPED)
             and not externally_identified(p)]
    if not peers:
        return None
    here = (location or "").strip()
    if not here:
        return "UNKNOWN_LOCATION"
    if any(not (p.storage_location or "").strip() for p in peers):
        return "PEER_LOCATION_UNKNOWN"
    if any((p.storage_location or "").strip() == here for p in peers):
        return "SAME_LOCATION"
    return None


def require_identity(state: PartState, instance: PartInstance, location: str | None) -> None:
    reason = identity_issue(state, instance, location)
    if reason is not None:
        raise conflict("PHYSICAL_IDENTITY_INSUFFICIENT",
                       "This part cannot be told apart from another identical part without a serial number or tag "
                       "label; add one (set once) and retry", {"reason": reason,
                                                               "part_instance_id": instance.part_instance_id})


def occupancy_issue(state: PartState, asset_type: AssetType, asset_id: str, position_code: str | None,
                    *, ignore_instance: str | None = None) -> bool:
    """O-1 / O-3 pre-check (the commit re-validates)."""
    key = position_key(position_code)
    if key is None:
        return False
    for instance_id, segments in state.segments.items():
        if instance_id == ignore_instance:
            continue
        for segment in segments:
            if (segment.status == InstallationSegmentStatus.ACTIVE and segment.asset_type == asset_type
                    and segment.asset_id == asset_id and position_key(segment.position_code) == key):
                return True
    return any(r.ended_at is None and not r.host_part_instance_id and r.asset_type == asset_type
               and r.asset_id == asset_id and position_key(r.position_code) == key for r in state.positions.values())


OP_REGISTER = "REGISTER"
OP_INSTALL = "INSTALL"
OP_REMOVE = "REMOVE"
OP_TRANSFER = "TRANSFER"
OP_RETURN = "RETURN_FROM_REPAIR"
OP_STATUS = "STATUS_CHANGE"
OP_IDENTIFIERS = "IDENTIFIER_ASSIGNED"
OP_MAINTENANCE = "MAINTENANCE_EVENT"


class PartInstanceService:
    def __init__(self, repository: Repository, meter_service: MeterService, cutover=None,
                 part_meter_source=None) -> None:
        self._repository = repository
        self._meter = meter_service
        self._data_context = cutover.data_context if cutover is not None else None
        self._batch_id = cutover.test_batch_id if cutover is not None else ""
        # R6 A-4: the TEST-only fake source when enabled; otherwise the same
        # source R4 uses (runtime default NO_IOT_METER_SOURCE -> UNKNOWN).
        self._source = part_meter_source if part_meter_source is not None else meter_service.iot_meter_source

    @property
    def data_context(self) -> str | None:
        return self._data_context

    # ---- reads ----

    async def get_instance(self, part_instance_id: str) -> PartInstanceDetail:
        state = await self._repository.read_part_state()
        if part_instance_id not in state.instances:
            raise ApiError(code="PART_INSTANCE_NOT_FOUND", message=f"Part instance '{part_instance_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        detail = detail_from_state(state, part_instance_id)
        await self._instance_scope(detail)  # CG-1 read isolation
        return detail

    async def list_instances(self, *, part_id: str | None, status_filter: PartInstanceStatus | None,
                             serial_number: str | None, tag_label: str | None, storage_location: str | None,
                             params: PageParams) -> tuple[list[PartInstanceDetail], int]:
        state = await self._repository.read_part_state()
        scope = AssetScopeFilter(self._repository, self._data_context, self._batch_id)
        items = []
        for instance in state.instances.values():
            if not await scope.allows_segments(state.segments.get(instance.part_instance_id, ())):
                continue  # CG-1: rows associated with another scope are not listed
            if part_id and instance.part_id != part_id:
                continue
            if status_filter and instance.status != status_filter:
                continue
            if serial_number and (instance.serial_number or "").strip() != serial_number.strip():
                continue
            if tag_label and (instance.tag_label or "").strip() != tag_label.strip():
                continue
            if storage_location and (instance.storage_location or "").strip() != storage_location.strip():
                continue
            items.append(instance.part_instance_id)
        items.sort()
        start = (params.page - 1) * params.page_size
        return [detail_from_state(state, i) for i in items[start:start + params.page_size]], len(items)

    async def approval_state(self, part_instance_id: str) -> tuple[ApprovalState, PartInstanceStatusEvent | None]:
        return approval_state(await self.get_instance(part_instance_id))

    # ---- helpers ----

    async def _load(self, part_instance_id: str) -> tuple[PartState, PartInstanceDetail]:
        state = await self._repository.read_part_state()
        if part_instance_id not in state.instances:
            raise ApiError(code="PART_INSTANCE_NOT_FOUND", message=f"Part instance '{part_instance_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        return state, detail_from_state(state, part_instance_id)

    async def _scope(self, asset_type: AssetType, asset_id: str) -> None:
        await require_asset_for_new_work(self._repository, asset_type, asset_id)
        await require_asset_scope(self._repository, asset_type, asset_id, self._data_context, self._batch_id)

    async def _instance_scope(self, detail: PartInstanceDetail) -> None:
        await require_segments_scope(self._repository, detail.segments, self._data_context, self._batch_id)

    async def _anchors(self, asset_type: AssetType, asset_id: str, at: datetime) -> list[MeterAnchor]:
        if asset_type != AssetType.VEHICLE:
            return []  # workshop equipment has no approved counter model (C03)
        return await verified_anchors(self._repository, self._source, asset_id, at)

    async def _context_snapshot(self, supplied: str | None, explicit_effective: bool, asset_type: AssetType,
                                asset_id: str, actor: str | None, note: str) -> str | None:
        """Machine-state CONTEXT (never usage evidence). A supplied id is
        validated; with no id, the existing automatic capture runs — except
        for an explicitly back-dated event, where a present-time capture would
        misrepresent the past (F03)."""
        if supplied is not None:
            await self._meter.require_snapshot_exists(supplied)
            return supplied
        if explicit_effective:
            return None
        snapshot = await self._meter.capture_current_state(asset_type=asset_type, asset_id=asset_id,
                                                           recorded_by=actor, source_note=note)
        return snapshot.meter_snapshot_id

    def _event(self, event_id: str, instance: PartInstance, operation: str, to_status: PartInstanceStatus, *,
               effective_at: datetime, recorded_at: datetime, actor: str | None, request_id: str | None,
               **fields) -> PartInstanceStatusEvent:
        return PartInstanceStatusEvent(event_id=event_id, part_instance_id=instance.part_instance_id,
                                       operation=operation, from_status=instance.status, to_status=to_status,
                                       effective_at=effective_at, recorded_at=recorded_at, actor=actor,
                                       request_id=request_id, **fields)

    def _bump(self, instance: PartInstance, now: datetime, **update) -> PartInstance:
        return instance.model_copy(update={**update, "updated_at": now, "state_version": instance.state_version + 1})

    # ---- registration ----

    async def create_instance(
        self,
        part_id: str,
        serial_number: str | None,
        prior_usage: PriorUsage,
        note: str | None,
        created_by: str | None,
        *,
        tag_label: str | None = None,
        storage_location: str | None = None,
        prior_cycle_usage: PriorUsage | None = None,
        initial_status: PartInstanceStatus = PartInstanceStatus.READY_FOR_INSTALL,
        request_id: str | None = None,
        body: dict | None = None,
    ) -> dict:
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "PART_INSTANCE", "NEW:PART_INSTANCE", request_id)
        digest = fingerprint(OP_REGISTER, "NEW:PART_INSTANCE", created_by, body or {})
        state = await self._repository.read_part_state()
        replay = replayed_response(state, key, OP_REGISTER, digest)
        if replay is not None:
            return replay
        part = await require_part_exists(self._repository, part_id)
        if part.tracking_mode != TrackingMode.INSTANCE_TRACKED:
            raise invalid("PART_NOT_INSTANCE_TRACKED",
                          f"Part '{part_id}' has tracking_mode='{part.tracking_mode.value}' — "
                          "a PartInstance may only be created for an INSTANCE_TRACKED part")
        if not part.is_active:
            raise invalid("PART_INACTIVE", f"Part '{part_id}' is deactivated; no new instance can be registered")
        if initial_status not in _REGISTRATION_STATUSES:
            raise invalid("PART_TRANSITION_NOT_ALLOWED", "A new instance starts READY_FOR_INSTALL or STOCK")
        now = utc_now()
        prior = await validate_declaration(self._repository, prior_usage, actor=created_by, now=now,
                                           field="prior_usage")
        cycle = None
        if prior_cycle_usage is not None:
            cycle = await validate_declaration(self._repository, prior_cycle_usage, actor=created_by, now=now,
                                               field="prior_cycle_usage")
        check_declaration_pair(prior, cycle)
        serial = (serial_number or "").strip() or None
        tag = (tag_label or "").strip() or None
        if serial and any(i.part_id == part_id and (i.serial_number or "").strip() == serial
                          for i in state.instances.values()):
            raise conflict("PART_INVARIANT_DUPLICATE_SERIAL", "This serial number is already used for this part")
        if tag and any((i.tag_label or "").strip() == tag for i in state.instances.values()):
            raise conflict("PART_INVARIANT_DUPLICATE_TAG", "This tag label is already used")
        (instance_id,) = await self._repository.allocate_part_ids("PINST")
        (lifecycle_id,) = await self._repository.allocate_part_ids("PLC")
        (event_id,) = await self._repository.allocate_part_ids("PSE")
        lifecycle = PartLifecycle(lifecycle_id=lifecycle_id, part_instance_id=instance_id, cycle_number=1,
                                  start_reason=LifecycleStartReason.ENROLLMENT, started_at=now, started_by=created_by)
        instance = PartInstance(part_instance_id=instance_id, part_id=part_id, serial_number=serial, tag_label=tag,
                                storage_location=(storage_location or "").strip() or None, status=initial_status,
                                prior_usage=prior, prior_cycle_usage=cycle, current_lifecycle_id=lifecycle_id,
                                note=note, state_version=1, created_at=now, updated_at=now)
        event = PartInstanceStatusEvent(event_id=event_id, part_instance_id=instance_id, operation=OP_REGISTER,
                                        from_status=None, to_status=initial_status, effective_at=now, recorded_at=now,
                                        actor=created_by, storage_location=instance.storage_location,
                                        request_id=request_id)
        return await commit(self._repository, PartMutation(
            puts={PART_INSTANCES: {instance_id: instance}, PART_LIFECYCLES: {instance_id: (lifecycle,)},
                  PART_SEGMENTS: {instance_id: ()}, PART_STATUS_EVENTS: {instance_id: (event,)}},
            expected_versions={instance_id: None}, request_key=key, operation=OP_REGISTER, fingerprint=digest,
            response=detail_response(instance_id)))

    # ---- install / remove / transfer ----

    async def install(
        self,
        part_instance_id: str,
        asset_type: AssetType,
        asset_id: str,
        position_code: str | None,
        baseline_meter_snapshot_id: str | None,
        installed_by: str | None,
        note: str | None,
        *,
        effective_at: datetime | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        request_id: str | None = None,
        body: dict | None = None,
    ) -> dict:
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "PART_INSTANCE", part_instance_id, request_id)
        digest = fingerprint(OP_INSTALL, part_instance_id, installed_by, body or {})
        state, detail = await self._load(part_instance_id)
        await self._instance_scope(detail)  # CG-1: before replay, so a replay never bypasses scope
        replay = replayed_response(state, key, OP_INSTALL, digest)
        if replay is not None:
            return replay
        instance = detail.instance
        if instance.status == PartInstanceStatus.INSTALLED or any(
                s.status == InstallationSegmentStatus.ACTIVE for s in detail.segments):
            raise invalid("PART_INSTANCE_ALREADY_INSTALLED",
                          f"Part instance '{part_instance_id}' is already installed — remove or transfer it before "
                          "installing again (no duplicate active installation)")
        if instance.status == PartInstanceStatus.SCRAPPED:
            raise invalid("PART_INSTANCE_SCRAPPED", f"Part instance '{part_instance_id}' is scrapped and cannot be installed")
        if instance.status not in _INSTALLABLE:
            # Owner decision A-2(i): no direct install from IN_REPAIR / REMOVED.
            raise conflict("PART_INSTANCE_NOT_READY_FOR_INSTALL",
                           "Complete the return from repair, or mark the part ready / in stock, before installing it",
                           {"status": instance.status.value})
        await self._scope(asset_type, asset_id)
        if occupancy_issue(state, asset_type, asset_id, position_code):
            raise conflict("PART_INVARIANT_POSITION_OCCUPIED", "This position is already occupied",
                           {"position_code": position_key(position_code)})
        require_identity(state, instance, instance.storage_location)
        now = utc_now()
        at = resolve_effective(effective_at, now, latest_effective(detail))
        snapshot_id = await self._context_snapshot(baseline_meter_snapshot_id, effective_at is not None, asset_type,
                                                   asset_id, installed_by, "PART_INSTANCE_INSTALL")
        anchors = await self._anchors(asset_type, asset_id, at)
        state_now, detail_now = state, detail
        approval, approval_event = approval_state(detail_now)
        lifecycles = tuple(detail_now.lifecycles)
        lifecycle_id = instance.current_lifecycle_id
        if approval == ApprovalState.PENDING and approval_event is not None:
            # A-2(ii): the ONE place a repaired-part cycle opens; consumed in this commit.
            (lifecycle_id,) = await self._repository.allocate_part_ids("PLC")
            current = next(lc for lc in lifecycles if lc.lifecycle_id == instance.current_lifecycle_id)
            new_cycle = PartLifecycle(lifecycle_id=lifecycle_id, part_instance_id=part_instance_id,
                                      cycle_number=max(lc.cycle_number for lc in lifecycles) + 1,
                                      start_reason=LifecycleStartReason.OVERHAUL, started_at=at,
                                      started_by=installed_by, started_note=approval_event.approval_reason_code,
                                      start_trigger_event_id=approval_event.event_id,
                                      start_policy_state=approval_event.approval_policy_state)
            lifecycles = tuple(lc.model_copy(update={"ended_at": at}) if lc.lifecycle_id == current.lifecycle_id
                               else lc for lc in lifecycles) + (new_cycle,)
        (segment_id,) = await self._repository.allocate_part_ids("SEG")
        (event_id,) = await self._repository.allocate_part_ids("PSE")
        segment = InstallationSegment(segment_id=segment_id, part_instance_id=part_instance_id,
                                      lifecycle_id=lifecycle_id, asset_type=asset_type, asset_id=asset_id,
                                      position_code=position_code, status=InstallationSegmentStatus.ACTIVE,
                                      installed_at=now, installed_by=installed_by,
                                      baseline_meter_snapshot_id=snapshot_id, install_note=note,
                                      installed_effective_at=at, source_type=source_type, source_id=source_id,
                                      baseline_anchors=anchors, request_id=request_id)
        event = self._event(event_id, instance, OP_INSTALL, PartInstanceStatus.INSTALLED, effective_at=at,
                            recorded_at=now, actor=installed_by, request_id=request_id, source_type=source_type,
                            source_id=source_id, meter_snapshot_id=snapshot_id)
        updated = self._bump(instance, now, status=PartInstanceStatus.INSTALLED, current_lifecycle_id=lifecycle_id,
                             storage_location=None)
        return await commit(self._repository, PartMutation(
            puts={PART_INSTANCES: {part_instance_id: updated},
                  PART_LIFECYCLES: {part_instance_id: lifecycles},
                  PART_SEGMENTS: {part_instance_id: tuple(detail_now.segments) + (segment,)},
                  PART_STATUS_EVENTS: {part_instance_id: tuple(detail_now.status_events) + (event,)}},
            expected_versions={part_instance_id: instance.state_version}, request_key=key, operation=OP_INSTALL,
            fingerprint=digest, response=detail_response(part_instance_id)))

    def _active_segment(self, detail: PartInstanceDetail) -> InstallationSegment | None:
        return next((s for s in detail.segments if s.status == InstallationSegmentStatus.ACTIVE), None)

    async def remove(
        self,
        part_instance_id: str,
        next_status: PartInstanceStatus,
        removal_meter_snapshot_id: str | None,
        removal_reason: str | None,
        removed_by: str | None,
        *,
        storage_location: str | None = None,
        effective_at: datetime | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        request_id: str | None = None,
        body: dict | None = None,
    ) -> dict:
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "PART_INSTANCE", part_instance_id, request_id)
        digest = fingerprint(OP_REMOVE, part_instance_id, removed_by, body or {})
        state, detail = await self._load(part_instance_id)
        await self._instance_scope(detail)  # CG-1: before replay, so a replay never bypasses scope
        replay = replayed_response(state, key, OP_REMOVE, digest)
        if replay is not None:
            return replay
        instance = detail.instance
        segment = self._active_segment(detail)
        if instance.status != PartInstanceStatus.INSTALLED or segment is None:
            raise invalid("PART_INSTANCE_NOT_INSTALLED", f"Part instance '{part_instance_id}' is not currently installed")
        if next_status not in _REMOVAL_NEXT_STATUSES:
            raise invalid("VALIDATION_ERROR", f"'{next_status.value}' is not a valid removal outcome — expected one of "
                          f"{sorted(s.value for s in _REMOVAL_NEXT_STATUSES)}")
        location = (storage_location or "").strip() or None
        candidate = instance.model_copy(update={"status": next_status, "storage_location": location})
        if next_status != PartInstanceStatus.SCRAPPED:
            require_identity(state, candidate, location)
        now = utc_now()
        at = resolve_effective(effective_at, now, latest_effective(detail))
        snapshot_id = await self._context_snapshot(removal_meter_snapshot_id, effective_at is not None,
                                                   segment.asset_type, segment.asset_id, removed_by,
                                                   "PART_INSTANCE_REMOVE")
        anchors = await self._anchors(segment.asset_type, segment.asset_id, at)
        closed = segment.model_copy(update={"status": InstallationSegmentStatus.CLOSED, "removed_at": now,
                                            "removed_effective_at": at, "removed_by": removed_by,
                                            "removal_meter_snapshot_id": snapshot_id,
                                            "removal_reason": removal_reason, "removal_anchors": anchors})
        (event_id,) = await self._repository.allocate_part_ids("PSE")
        event = self._event(event_id, instance, OP_REMOVE, next_status, effective_at=at, recorded_at=now,
                            actor=removed_by, request_id=request_id, reason=removal_reason, source_type=source_type,
                            source_id=source_id, meter_snapshot_id=snapshot_id, storage_location=location)
        updated = self._bump(instance, now, status=next_status, storage_location=location)
        segments = tuple(closed if s.segment_id == segment.segment_id else s for s in detail.segments)
        return await commit(self._repository, PartMutation(
            puts={PART_INSTANCES: {part_instance_id: updated}, PART_SEGMENTS: {part_instance_id: segments},
                  PART_STATUS_EVENTS: {part_instance_id: tuple(detail.status_events) + (event,)}},
            expected_versions={part_instance_id: instance.state_version}, request_key=key, operation=OP_REMOVE,
            fingerprint=digest, response=detail_response(part_instance_id)))

    async def transfer(
        self,
        part_instance_id: str,
        target_asset_type: AssetType,
        target_asset_id: str,
        position_code: str | None,
        removal_meter_snapshot_id: str | None,
        baseline_meter_snapshot_id: str | None,
        removal_reason: str | None,
        transferred_by: str | None,
        note: str | None,
        *,
        effective_at: datetime | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        request_id: str | None = None,
        body: dict | None = None,
    ) -> dict:
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "PART_INSTANCE", part_instance_id, request_id)
        digest = fingerprint(OP_TRANSFER, part_instance_id, transferred_by, body or {})
        state, detail = await self._load(part_instance_id)
        await self._instance_scope(detail)  # CG-1: before replay, so a replay never bypasses scope
        replay = replayed_response(state, key, OP_TRANSFER, digest)
        if replay is not None:
            return replay
        instance = detail.instance
        segment = self._active_segment(detail)
        if instance.status != PartInstanceStatus.INSTALLED or segment is None:
            raise invalid("PART_INSTANCE_NOT_INSTALLED", f"Part instance '{part_instance_id}' is not currently installed")
        # Data scope of BOTH assets (C7, CG-1): the source and the target, vehicle or equipment.
        await require_asset_scope(self._repository, segment.asset_type, segment.asset_id, self._data_context,
                                  self._batch_id)
        await self._scope(target_asset_type, target_asset_id)
        if occupancy_issue(state, target_asset_type, target_asset_id, position_code, ignore_instance=part_instance_id):
            raise conflict("PART_INVARIANT_POSITION_OCCUPIED", "This position is already occupied",
                           {"position_code": position_key(position_code)})
        now = utc_now()
        at = resolve_effective(effective_at, now, latest_effective(detail))
        explicit = effective_at is not None
        out_snapshot = await self._context_snapshot(removal_meter_snapshot_id, explicit, segment.asset_type,
                                                    segment.asset_id, transferred_by, "PART_INSTANCE_TRANSFER_OUT")
        in_snapshot = await self._context_snapshot(baseline_meter_snapshot_id, explicit, target_asset_type,
                                                   target_asset_id, transferred_by, "PART_INSTANCE_TRANSFER_IN")
        out_anchors = await self._anchors(segment.asset_type, segment.asset_id, at)
        in_anchors = await self._anchors(target_asset_type, target_asset_id, at)
        closed = segment.model_copy(update={"status": InstallationSegmentStatus.CLOSED, "removed_at": now,
                                            "removed_effective_at": at, "removed_by": transferred_by,
                                            "removal_meter_snapshot_id": out_snapshot,
                                            "removal_reason": removal_reason or "TRANSFER",
                                            "removal_anchors": out_anchors})
        (segment_id,) = await self._repository.allocate_part_ids("SEG")
        (event_id,) = await self._repository.allocate_part_ids("PSE")
        # Same lifecycle: a transfer never starts a cycle and never resets usage.
        opened = InstallationSegment(segment_id=segment_id, part_instance_id=part_instance_id,
                                     lifecycle_id=instance.current_lifecycle_id, asset_type=target_asset_type,
                                     asset_id=target_asset_id, position_code=position_code,
                                     status=InstallationSegmentStatus.ACTIVE, installed_at=now,
                                     installed_by=transferred_by, baseline_meter_snapshot_id=in_snapshot,
                                     install_note=note, installed_effective_at=at, source_type=source_type,
                                     source_id=source_id, baseline_anchors=in_anchors, request_id=request_id)
        event = self._event(event_id, instance, OP_TRANSFER, PartInstanceStatus.INSTALLED, effective_at=at,
                            recorded_at=now, actor=transferred_by, request_id=request_id,
                            reason=removal_reason or "TRANSFER", source_type=source_type, source_id=source_id,
                            meter_snapshot_id=in_snapshot)
        segments = tuple(closed if s.segment_id == segment.segment_id else s for s in detail.segments) + (opened,)
        return await commit(self._repository, PartMutation(
            puts={PART_INSTANCES: {part_instance_id: self._bump(instance, now)},
                  PART_SEGMENTS: {part_instance_id: segments},
                  PART_STATUS_EVENTS: {part_instance_id: tuple(detail.status_events) + (event,)}},
            expected_versions={part_instance_id: instance.state_version}, request_key=key, operation=OP_TRANSFER,
            fingerprint=digest, response=detail_response(part_instance_id)))

    # ---- return / status / identifiers ----

    async def return_from_repair(
        self,
        part_instance_id: str,
        *,
        context,
        outcome: str | None,
        repair_reference: str | None,
        new_cycle_approved: bool,
        approval_reason_code: str | None,
        storage_location: str | None,
        effective_at: datetime | None,
        note: str | None,
        request_id: str,
        body: dict,
    ) -> dict:
        actor = context.user_id if context is not None else None
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "PART_INSTANCE", part_instance_id, request_id)
        digest = fingerprint(OP_RETURN, part_instance_id, actor, body)
        state, detail = await self._load(part_instance_id)
        await self._instance_scope(detail)  # CG-1: before replay, so a replay never bypasses scope
        replay = replayed_response(state, key, OP_RETURN, digest)
        if replay is not None:
            return replay
        instance = detail.instance
        if instance.status != PartInstanceStatus.IN_REPAIR:
            raise conflict("PART_TRANSITION_NOT_ALLOWED", "Only a part that is IN_REPAIR can return from repair",
                           {"status": instance.status.value})
        reference = (repair_reference or "").strip() or None
        if reference is not None and await self._repository.get_repair(reference) is None:
            raise invalid("REPAIR_REFERENCE_NOT_FOUND", "repair_reference must name an existing Repair work order")
        policy_state = None
        if new_cycle_approved:
            require_operational_capability(context, "อนุมัติเริ่มรอบใหม่หลังซ่อม (approve a new service cycle)")
            if data_context != "TEST":
                # PG-2 (qualifying repair criteria / evidence / approver) is not Owner-approved.
                raise conflict("NEW_CYCLE_POLICY_PENDING",
                               "Starting a new service cycle after repair awaits Owner policy PG-2 in this data context")
            if reference is None:
                raise invalid("REPAIR_REFERENCE_REQUIRED", "A new-cycle approval needs the Repair work order reference")
            code = (approval_reason_code or "").strip()
            if not code.startswith(TEST_REASON_PREFIX):
                raise invalid("APPROVAL_REASON_CODE_INVALID",
                              "In TEST the approval reason code must be TEST-labelled (no real repair codes exist yet)")
            policy_state = "TEST_PROPOSED"
        location = (storage_location or "").strip() or None
        candidate = instance.model_copy(update={"status": PartInstanceStatus.READY_FOR_INSTALL,
                                                "storage_location": location})
        require_identity(state, candidate, location)
        now = utc_now()
        at = resolve_effective(effective_at, now, latest_effective(detail))
        (event_id,) = await self._repository.allocate_part_ids("PSE")
        event = self._event(event_id, instance, OP_RETURN, PartInstanceStatus.READY_FOR_INSTALL, effective_at=at,
                            recorded_at=now, actor=actor, request_id=request_id, reason=outcome or note,
                            storage_location=location, new_cycle_approved=bool(new_cycle_approved),
                            approval_reason_code=(approval_reason_code or "").strip() or None if new_cycle_approved
                            else None, approval_policy_state=policy_state, repair_reference=reference,
                            approved_by=actor if new_cycle_approved else None)
        updated = self._bump(instance, now, status=PartInstanceStatus.READY_FOR_INSTALL, storage_location=location)
        return await commit(self._repository, PartMutation(
            puts={PART_INSTANCES: {part_instance_id: updated},
                  PART_STATUS_EVENTS: {part_instance_id: tuple(detail.status_events) + (event,)}},
            expected_versions={part_instance_id: instance.state_version}, request_key=key, operation=OP_RETURN,
            fingerprint=digest, response=detail_response(part_instance_id)))

    async def change_status(self, part_instance_id: str, *, actor: str | None, to_status: PartInstanceStatus,
                            storage_location: str | None, reason: str | None, effective_at: datetime | None,
                            request_id: str, body: dict) -> dict:
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "PART_INSTANCE", part_instance_id, request_id)
        digest = fingerprint(OP_STATUS, part_instance_id, actor, body)
        state, detail = await self._load(part_instance_id)
        await self._instance_scope(detail)  # CG-1: before replay, so a replay never bypasses scope
        replay = replayed_response(state, key, OP_STATUS, digest)
        if replay is not None:
            return replay
        instance = detail.instance
        if to_status not in _STATUS_MOVES.get(instance.status, frozenset()):
            raise conflict("PART_TRANSITION_NOT_ALLOWED",
                           f"{instance.status.value} -> {to_status.value} is not an allowed status move",
                           {"from": instance.status.value, "to": to_status.value})
        location = (storage_location or "").strip() or None
        if to_status != PartInstanceStatus.SCRAPPED:
            require_identity(state, instance.model_copy(update={"status": to_status, "storage_location": location}),
                             location)
        now = utc_now()
        at = resolve_effective(effective_at, now, latest_effective(detail))
        (event_id,) = await self._repository.allocate_part_ids("PSE")
        event = self._event(event_id, instance, OP_STATUS, to_status, effective_at=at, recorded_at=now, actor=actor,
                            request_id=request_id, reason=reason, storage_location=location)
        updated = self._bump(instance, now, status=to_status, storage_location=location)
        return await commit(self._repository, PartMutation(
            puts={PART_INSTANCES: {part_instance_id: updated},
                  PART_STATUS_EVENTS: {part_instance_id: tuple(detail.status_events) + (event,)}},
            expected_versions={part_instance_id: instance.state_version}, request_key=key, operation=OP_STATUS,
            fingerprint=digest, response=detail_response(part_instance_id)))

    async def assign_identifiers(self, part_instance_id: str, *, actor: str | None, serial_number: str | None,
                                 tag_label: str | None, request_id: str, body: dict) -> dict:
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "PART_INSTANCE", part_instance_id, request_id)
        digest = fingerprint(OP_IDENTIFIERS, part_instance_id, actor, body)
        state, detail = await self._load(part_instance_id)
        await self._instance_scope(detail)  # CG-1: before replay, so a replay never bypasses scope
        replay = replayed_response(state, key, OP_IDENTIFIERS, digest)
        if replay is not None:
            return replay
        instance = detail.instance
        serial = (serial_number or "").strip() or None
        tag = (tag_label or "").strip() or None
        if serial is None and tag is None:
            raise invalid("VALIDATION_ERROR", "Provide serial_number and/or tag_label")
        if (serial and instance.serial_number) or (tag and instance.tag_label):
            raise conflict("PART_IDENTIFIER_ALREADY_SET",
                           "An identifier can be set only once; correcting it is Owner policy PG-6")
        now = utc_now()
        (event_id,) = await self._repository.allocate_part_ids("PSE")
        event = self._event(event_id, instance, OP_IDENTIFIERS, instance.status, effective_at=now, recorded_at=now,
                            actor=actor, request_id=request_id, reason="IDENTIFIER_ASSIGNED",
                            storage_location=instance.storage_location)
        update = {}
        if serial:
            update["serial_number"] = serial
        if tag:
            update["tag_label"] = tag
        return await commit(self._repository, PartMutation(
            puts={PART_INSTANCES: {part_instance_id: self._bump(instance, now, **update)},
                  PART_STATUS_EVENTS: {part_instance_id: tuple(detail.status_events) + (event,)}},
            expected_versions={part_instance_id: instance.state_version}, request_key=key, operation=OP_IDENTIFIERS,
            fingerprint=digest, response=detail_response(part_instance_id)))

    async def start_new_lifecycle(self, part_instance_id: str, approved_reason: str, started_by: str | None) -> None:
        """Owner decision A-2(ii): this legacy route NEVER creates a lifecycle
        and never changes an approval, in any state. Always 409 with the
        read-only approval state (route and body kept for compatibility)."""
        detail = await self.get_instance(part_instance_id)
        state, event = approval_state(detail)
        raise conflict("NEW_CYCLE_OPENS_AT_INSTALL",
                       "A new service cycle opens only when an approved repaired part is installed; record the "
                       "return from repair (with approval) and then install the part",
                       {"approval_state": state.value, "return_event_id": event.event_id if event else None})

    # ---- maintenance events (INSPECT / REPAIR anchors only) ----

    async def add_maintenance_event(self, part_instance_id: str, *, actor: str | None, action: MaintenanceAction,
                                    lifetime_rule_id: str | None, condition_group_key: str | None,
                                    outcome: str | None, effective_at: datetime | None, source_type: str | None,
                                    source_id: str | None, note: str | None, request_id: str, body: dict) -> dict:
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "PART_INSTANCE", part_instance_id, request_id)
        digest = fingerprint(OP_MAINTENANCE, part_instance_id, actor, body)
        state, detail = await self._load(part_instance_id)
        await self._instance_scope(detail)  # CG-1: before replay, so a replay never bypasses scope
        replay = replayed_response(state, key, OP_MAINTENANCE, digest)
        if replay is not None:
            return replay
        instance = detail.instance
        if instance.status == PartInstanceStatus.SCRAPPED:
            raise conflict("PART_TRANSITION_NOT_ALLOWED", "A scrapped part takes no maintenance events")
        validate_maintenance_target(state, instance.part_id, action, lifetime_rule_id, condition_group_key)
        now = utc_now()
        at = resolve_effective(effective_at, now, latest_effective(detail))
        segment = self._active_segment(detail)
        anchors = await self._anchors(segment.asset_type, segment.asset_id, at) if segment is not None else []
        (event_id,) = await self._repository.allocate_part_ids("PME")
        event = PartMaintenanceEvent(event_id=event_id, target_type=MaintenanceTargetType.PART_INSTANCE,
                                     target_id=part_instance_id, lifetime_rule_id=lifetime_rule_id,
                                     condition_group_key=condition_group_key, action=action, outcome=outcome,
                                     lifecycle_id=instance.current_lifecycle_id, effective_at=at, recorded_at=now,
                                     actor=actor, anchors=anchors, source_type=source_type, source_id=source_id,
                                     note=note, request_id=request_id)
        existing = state.maintenance.get(part_instance_id, ())
        return await commit(self._repository, PartMutation(
            puts={PART_MAINTENANCE: {part_instance_id: existing + (event,)},
                  # A maintenance event never changes status or lifecycle; the
                  # version bump serializes it against concurrent moves.
                  PART_INSTANCES: {part_instance_id: self._bump(instance, now)}},
            expected_versions={part_instance_id: instance.state_version}, request_key=key, operation=OP_MAINTENANCE,
            fingerprint=digest, response=lambda s: s.maintenance[part_instance_id][-1].model_dump(mode="json")))


def validate_maintenance_target(state: PartState, part_id: str | None, action: MaintenanceAction,
                                lifetime_rule_id: str | None, condition_group_key: str | None) -> None:
    """A maintenance event anchors exactly one INSPECT / REPAIR rule or one
    condition group of the target's own part, with the matching action."""
    if bool(lifetime_rule_id) == bool(condition_group_key):
        raise invalid("VALIDATION_ERROR", "Name exactly one of lifetime_rule_id or condition_group_key")
    if lifetime_rule_id:
        rules = [state.rules.get(lifetime_rule_id)]
        if rules[0] is None:
            raise ApiError(code="LIFETIME_RULE_NOT_FOUND", message=f"Lifetime rule '{lifetime_rule_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
    else:
        rules = [r for r in state.rules.values() if r.condition_group_key == condition_group_key]
        if not rules:
            raise ApiError(code="CONDITION_GROUP_NOT_FOUND", message="No rule has this condition group",
                           status_code=status.HTTP_404_NOT_FOUND)
    for rule in rules:
        if part_id is None or rule.part_id != part_id:
            raise invalid("MAINTENANCE_RULE_MISMATCH", "The rule belongs to a different part")
        expected = ACTION_FOR_DUE.get(rule.due_action.value if rule.due_action else "")
        if expected != action:
            raise invalid("MAINTENANCE_RULE_MISMATCH",
                          "INSPECTED anchors INSPECT rules and REPAIRED_IN_PLACE anchors REPAIR rules only "
                          "(a maintenance event never resets REPLACE)")


__all__ = [
    "PartInstanceService", "approval_state", "identity_issue", "verified_anchors", "validate_declaration",
    "commit", "fingerprint", "request_key", "replayed_response", "resolve_effective", "require_vehicle_scope",
    "require_operational_capability", "require_data_context", "detail_from_state", "occupancy_issue",
    "validate_maintenance_target", "invalid", "conflict", "OPERATIONAL_CAPABILITIES",
]
