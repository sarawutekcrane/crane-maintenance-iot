"""R6 — the ONE lifetime-status read service (FINAL §7.3, §7.4, §19).

Every view (part instance page, vehicle / equipment parts page, PM context and
a future R7 report / alert consumer) calls this service: the same rule can
never produce contradictory results in different views, and no formula lives
in the frontend. It is side-effect free: a verified current reading for an
active segment is read with the R4 selector at evaluation time and never
persisted.

A-4 (Owner decision: ON, TEST ONLY): `TestOnlyPartMeterSource` is an
in-memory, explicitly fake IoT source for Mock/TEST browser acceptance. It is
constructed only when `Settings.part_test_meter_source_effective` is True,
which the settings validator allows only with DATA_REPOSITORY=mock (always the
TEST context) outside production; the source additionally refuses to record
or return anything unless its own data context is TEST. No real device data
or meter history is fabricated: it holds only what a TEST caller explicitly
records, and R4 PM Due keeps its own (runtime NO_IOT) source.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import status

from app.domain.asset import AssetType
from app.domain.common import bangkok_today, utc_now
from app.domain.lifetime_rule import LifetimeRule, LifetimeRuleScope, LifetimeTriggerType
from app.domain.meter_service import MeterService
from app.domain.part_instance import (
    InstallationSegment,
    InstallationSegmentStatus,
    PartInstanceDetail,
    PartInstanceStatus,
    PriorUsage,
    verification_level,
)
from app.domain.part_instance_service import (
    AssetScopeFilter,
    approval_state,
    detail_from_state,
    require_asset_scope,
    require_segments_scope,
    verified_anchors,
)
from app.domain.part_lifetime_due import (
    CalendarInputs,
    RuleInputs,
    RuleResult,
    combine_earliest,
    evaluate_rule,
)
from app.domain.part_maintenance_event import ACTION_FOR_DUE
from app.domain.part_usage import (
    Basis,
    Counters,
    PolicyContext,
    Quantity,
    SegmentInput,
    clipped_usage,
    current_lifecycle,
    instance_counters,
    record_counters,
)
from app.domain.pm_meter_anchor import IotMeterObservation
from app.domain.position_lifetime import PositionLifetimeRecord
from app.errors import ApiError
from app.repositories.base import PartState, Repository

_BANGKOK = ZoneInfo("Asia/Bangkok")
ENGINE_ROLES = ("CARRIER_ENGINE", "CRANE_ENGINE")
TEST_FAKE_DEVICE_ID = "R6-TEST-ONLY-FAKE-DEVICE"


class TestOnlyPartMeterSource:
    """A-4: explicitly fake verified observations, TEST context only.
    `max_observation_age` is a TEST-only freshness window (not a real device
    threshold — A05 / I04 remain open)."""

    __test__ = False  # not a pytest test class
    max_observation_age: timedelta | None = timedelta(days=1)

    def __init__(self, data_context: str | None) -> None:
        self._data_context = data_context
        self._observations: list[IotMeterObservation] = []

    @property
    def enabled(self) -> bool:
        return self._data_context == "TEST"

    def add(self, observation: IotMeterObservation) -> None:
        if not self.enabled:
            raise PermissionError("The TEST-only fake meter source is unavailable outside the TEST context")
        self._observations.append(observation)

    def record(self, vehicle_id: str, component_id: str | None, counter_type: str, value: float,
               at: datetime | None = None) -> IotMeterObservation:
        moment = at or utc_now()
        observation = IotMeterObservation(vehicle_id=vehicle_id, component_id=component_id,
                                          counter_type=counter_type, value=float(value), observed_at=moment,
                                          received_at=moment, time_quality="TIME_SYNCED",
                                          device_id=TEST_FAKE_DEVICE_ID, device_event_id=f"R6TEST-{uuid.uuid4()}",
                                          device_verified=True)
        self.add(observation)
        return observation

    async def observations(self, vehicle_id: str, *, not_after: datetime) -> Sequence[IotMeterObservation]:
        if not self.enabled:
            return ()
        return tuple(o for o in self._observations if o.vehicle_id == vehicle_id)


def _bangkok_date(moment: datetime) -> date:
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(_BANGKOK).date()


def quantity_view(q: Quantity) -> dict:
    return {"value": q.value, "quality": q.quality, "policy_state": q.policy_state, "reasons": list(q.reasons)}


def counters_view(basis: Basis, counters: Counters) -> dict:
    return {
        "basis": {"counter_type": basis.counter_type, "component_role": basis.component_role},
        "tracked_since_enrollment": quantity_view(counters.tracked_since_enrollment),
        "tracked_in_current_cycle": quantity_view(counters.tracked_in_current_cycle),
        "verified_lifetime_total": quantity_view(counters.verified_lifetime_total),
        "verified_current_cycle": quantity_view(counters.verified_current_cycle),
    }


def declaration_view(declaration: PriorUsage | None) -> dict | None:
    """F02: the DECLARED value is returned separately with its level; it is
    never placed in a verified field."""
    if declaration is None:
        return None
    level = verification_level(declaration)
    return {
        "declared_value": declaration.value,
        "quality": declaration.quality.value,
        "basis": declaration.basis.value if declaration.basis else None,
        "component_role": declaration.component_role.value if declaration.component_role else None,
        "as_of": declaration.as_of.isoformat() if declaration.as_of else None,
        "evidence_type": declaration.evidence_type.value if declaration.evidence_type else None,
        "evidence_reference": declaration.evidence_reference,
        "reference_status": declaration.reference_status.value if declaration.reference_status else None,
        "verification_level": level.value if level else None,
        "note": declaration.note,
    }


def result_view(result: RuleResult) -> dict:
    return {
        "lifetime_rule_id": result.lifetime_rule_id,
        "condition_group_key": result.condition_group_key,
        "due_action": result.due_action,
        "trigger_type": result.trigger_type,
        "status": result.status,
        "current_value": result.current_value,
        "next_due_value": result.next_due_value,
        "next_due_date": result.next_due_date.isoformat() if result.next_due_date else None,
        "remaining": result.remaining,
        "reasons": list(result.reasons),
        "policy_state": result.policy_state,
        "due_key": result.due_key,
        "members": [result_view(m) for m in result.members],
    }


def rule_basis(rule: LifetimeRule) -> Basis | None:
    if rule.trigger_type == LifetimeTriggerType.ENGINE_HOUR:
        return Basis("ENGINE_HOUR", rule.component_role.value if rule.component_role else None)
    if rule.trigger_type == LifetimeTriggerType.ODOMETER:
        return Basis("ODOMETER", None)
    return None


def applicable_rules(state: PartState, part_id: str | None, model_id: str | None,
                     explicit_rule_id: str | None = None) -> tuple[list[LifetimeRule], list[LifetimeRule]]:
    """MODEL rules of the host's model (+ an explicitly linked rule); VEHICLE
    overrides are reported as inactive (AP-16: "later")."""
    active: list[LifetimeRule] = []
    inactive: list[LifetimeRule] = []
    for rule in sorted(state.rules.values(), key=lambda r: r.lifetime_rule_id):
        if part_id is None or rule.part_id != part_id:
            if rule.lifetime_rule_id == explicit_rule_id:
                active.append(rule)
            continue
        if rule.scope == LifetimeRuleScope.VEHICLE:
            inactive.append(rule)
        elif rule.model_id is not None and rule.model_id == model_id:
            active.append(rule)
        elif rule.lifetime_rule_id == explicit_rule_id:
            active.append(rule)
    return active, inactive


class PartLifetimeStatusService:
    def __init__(self, repository: Repository, meter_service: MeterService, cutover=None,
                 part_meter_source=None) -> None:
        self._repository = repository
        self._data_context = cutover.data_context if cutover is not None else None
        self._batch_id = cutover.test_batch_id if cutover is not None else ""
        self._source = part_meter_source if part_meter_source is not None else meter_service.iot_meter_source

    async def _require_segments(self, segments) -> None:
        await require_segments_scope(self._repository, segments, self._data_context, self._batch_id)

    async def _require_record(self, state: PartState, record: PositionLifetimeRecord) -> None:
        if record.host_part_instance_id:
            await self._require_segments(state.segments.get(record.host_part_instance_id, ()))
        else:
            await require_asset_scope(self._repository, record.asset_type, record.asset_id, self._data_context,
                                      self._batch_id)

    @property
    def policy(self) -> PolicyContext:
        return PolicyContext(self._data_context)

    async def _components(self, vehicle_id: str) -> tuple[tuple[str, str], ...]:
        return tuple((c.component_id, c.component_role.value)
                     for c in await self._repository.list_vehicle_components(vehicle_id))

    async def _model_id(self, asset_type: AssetType | None, asset_id: str | None) -> str | None:
        if asset_type != AssetType.VEHICLE or not asset_id:
            return None
        vehicle = await self._repository.get_vehicle(asset_id)
        return vehicle.model_id if vehicle is not None else None

    async def _segment_inputs(self, segments: Sequence[InstallationSegment], now: datetime) -> list[SegmentInput]:
        items: list[SegmentInput] = []
        for segment in segments:
            if segment.asset_type != AssetType.VEHICLE:
                items.append(SegmentInput(segment))
                continue
            components = await self._components(segment.asset_id)
            current_end: tuple = ()
            if segment.effective_end is None:
                current_end = tuple(await verified_anchors(self._repository, self._source, segment.asset_id, now))
            items.append(SegmentInput(segment, components, current_end))
        return items

    async def _bases(self, rules: Sequence[LifetimeRule], vehicle_id: str | None,
                     history_vehicle_ids: Sequence[str] = ()) -> list[Basis]:
        """The counter dimensions shown: the current host vehicle's first, then any
        dimension of a vehicle earlier in the history (a part now on equipment or in
        storage keeps its accrued verified hours visible — a transfer never hides or
        resets them), then every rule's basis."""
        bases: list[Basis] = []
        vehicles = list(dict.fromkeys([v for v in (vehicle_id, *history_vehicle_ids) if v]))
        for vid in vehicles:
            roles = {role for _, role in await self._components(vid)}
            for basis in [Basis("ENGINE_HOUR", role) for role in ENGINE_ROLES if role in roles] + [
                    Basis("ODOMETER", None)]:
                if basis not in bases:
                    bases.append(basis)
        for rule in rules:
            basis = rule_basis(rule)
            if basis is not None and basis not in bases:
                bases.append(basis)
        return bases

    def _evaluate(self, rules: Sequence[LifetimeRule], counters_by_basis: dict[Basis, Counters],
                  since_event: dict[str, tuple[date, dict[Basis, Quantity]]], calendar_inputs: CalendarInputs,
                  *, target_type: str, target_id: str, lifecycle_id: str | None, cycle_number: int) -> list[dict]:
        today = bangkok_today()
        unknown_base = Quantity(None, "UNKNOWN", None, ("NO_BASIS",))
        results: list[RuleResult] = []
        for rule in rules:
            basis = rule_basis(rule)
            counters = counters_by_basis.get(basis) if basis else None
            replace_base = counters.verified_current_cycle if counters else unknown_base
            anchor_key = rule.condition_group_key and f"GROUP:{rule.condition_group_key}" or rule.lifetime_rule_id
            event = since_event.get(anchor_key)
            since_base = event[1].get(basis) if (event and basis) else None
            results.append(evaluate_rule(rule, RuleInputs(replace_base, since_base, event[0] if event else None,
                                                          cycle_number), calendar_inputs, self.policy, today,
                                         target_type=target_type, target_id=target_id, lifecycle_id=lifecycle_id))
        views: list[dict] = []
        groups: dict[str, list[RuleResult]] = {}
        for result in results:
            if result.condition_group_key:
                groups.setdefault(result.condition_group_key, []).append(result)
            else:
                views.append(result_view(result))
        for key, members in sorted(groups.items()):
            views.append(result_view(combine_earliest(key, members, target_type=target_type, target_id=target_id,
                                                      lifecycle_id=lifecycle_id)))
        return views

    async def _since_events(self, events, rules, items: Sequence[SegmentInput], lifecycle_id: str | None,
                            bases: Sequence[Basis]) -> dict[str, tuple[date, dict[Basis, Quantity]]]:
        """Latest matching INSPECT / REPAIR maintenance event per rule or group
        in the current cycle, with verified usage since it (per basis)."""
        result: dict[str, tuple[date, dict[Basis, Quantity]]] = {}
        for rule in rules:
            expected = ACTION_FOR_DUE.get(rule.due_action.value if rule.due_action else "")
            if expected is None:
                continue
            key = rule.condition_group_key and f"GROUP:{rule.condition_group_key}" or rule.lifetime_rule_id
            matching = [e for e in events if e.action == expected and e.lifecycle_id == lifecycle_id and (
                (rule.condition_group_key and e.condition_group_key == rule.condition_group_key)
                or (not rule.condition_group_key and e.lifetime_rule_id == rule.lifetime_rule_id))]
            if not matching:
                continue
            latest = max(matching, key=lambda e: (e.effective_at, e.event_id))
            usage = {basis: clipped_usage(items, basis, start_at=latest.effective_at, start_anchors=latest.anchors)
                     for basis in bases}
            result[key] = (_bangkok_date(latest.effective_at), usage)
        return result

    # ---- part instance ----

    async def instance_status(self, part_instance_id: str) -> dict:
        state = await self._repository.read_part_state()
        if part_instance_id not in state.instances:
            raise ApiError(code="PART_INSTANCE_NOT_FOUND", message=f"Part instance '{part_instance_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        await self._require_segments(state.segments.get(part_instance_id, ()))  # CG-1 read isolation
        return await self._instance_status(state, detail_from_state(state, part_instance_id))

    async def _instance_status(self, state: PartState, detail: PartInstanceDetail) -> dict:
        now = utc_now()
        instance = detail.instance
        segments = list(detail.segments)
        active = next((s for s in segments if s.status == InstallationSegmentStatus.ACTIVE), None)
        host_segment = active or (segments[-1] if segments else None)
        host = None
        model_id = None
        if host_segment is not None:
            model_id = await self._model_id(host_segment.asset_type, host_segment.asset_id)
            host = {"asset_type": host_segment.asset_type.value, "asset_id": host_segment.asset_id,
                    "position_code": host_segment.position_code, "model_id": model_id,
                    "installed": active is not None}
        rules, inactive = applicable_rules(state, instance.part_id, model_id)
        items = await self._segment_inputs(segments, now)
        vehicle_id = host_segment.asset_id if host_segment and host_segment.asset_type == AssetType.VEHICLE else None
        bases = await self._bases(rules, vehicle_id, [s.asset_id for s in segments
                                                      if s.asset_type == AssetType.VEHICLE])
        counters_by_basis = {
            basis: instance_counters(prior_usage=instance.prior_usage, prior_cycle_usage=instance.prior_cycle_usage,
                                     lifecycles=detail.lifecycles, current_lifecycle_id=instance.current_lifecycle_id,
                                     items=items, basis=basis, policy=self.policy)
            for basis in bases}
        lifecycle = current_lifecycle(detail.lifecycles, instance.current_lifecycle_id)
        cycle_items = [i for i in items if i.segment.lifecycle_id == instance.current_lifecycle_id]
        cycle_segments = sorted((i.segment for i in cycle_items), key=lambda s: s.effective_start)
        anchor = _bangkok_date(cycle_segments[0].effective_start) if cycle_segments else None
        has_storage = bool(cycle_segments) and (active is None or any(
            a.effective_end is not None and a.effective_end < b.effective_start
            for a, b in zip(cycle_segments, cycle_segments[1:])))
        events = state.maintenance.get(instance.part_instance_id, ())
        since = await self._since_events(events, rules, cycle_items, instance.current_lifecycle_id, bases)
        approval, approval_event = approval_state(detail)
        return {
            "target_type": "PART_INSTANCE",
            "target_id": instance.part_instance_id,
            "part_id": instance.part_id,
            "status": instance.status.value,
            "policy_context": "TEST" if self.policy.is_test else "REAL",
            "evaluated_at": now.isoformat(),
            "host": host,
            "lifecycle": {"lifecycle_id": instance.current_lifecycle_id,
                          "cycle_number": lifecycle.cycle_number if lifecycle else None,
                          "start_reason": lifecycle.start_reason.value if lifecycle else None,
                          "start_trigger_event_id": lifecycle.start_trigger_event_id if lifecycle else None},
            "approval": {"state": approval.value, "return_event_id": approval_event.event_id if approval_event else None},
            "declarations": {"prior_usage": declaration_view(instance.prior_usage),
                             "prior_cycle_usage": declaration_view(instance.prior_cycle_usage)},
            "counters": [counters_view(b, c) for b, c in counters_by_basis.items()],
            "rules": self._evaluate(rules, counters_by_basis, since, CalendarInputs(anchor, has_storage),
                                    target_type="PART_INSTANCE", target_id=instance.part_instance_id,
                                    lifecycle_id=instance.current_lifecycle_id,
                                    cycle_number=lifecycle.cycle_number if lifecycle else 1),
            "inactive_rules": [{"lifetime_rule_id": r.lifetime_rule_id, "reason": "VEHICLE_OVERRIDE_NOT_ACTIVE"}
                               for r in inactive],
        }

    # ---- position-lifetime record ----

    async def position_status(self, position_lifetime_id: str) -> dict:
        state = await self._repository.read_part_state()
        record = state.positions.get(position_lifetime_id)
        if record is None:
            raise ApiError(code="POSITION_LIFETIME_NOT_FOUND",
                           message=f"Position lifetime record '{position_lifetime_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        await self._require_record(state, record)  # CG-1 read isolation
        return await self._position_status(state, record)

    def _record_segment(self, record: PositionLifetimeRecord) -> InstallationSegment:
        ended = record.effective_end
        return InstallationSegment(
            segment_id=record.position_lifetime_id, part_instance_id=record.position_lifetime_id,
            lifecycle_id=record.position_lifetime_id, asset_type=record.asset_type, asset_id=record.asset_id,
            position_code=record.position_code,
            status=InstallationSegmentStatus.CLOSED if ended else InstallationSegmentStatus.ACTIVE,
            installed_at=record.started_at, installed_effective_at=record.effective_start,
            removed_at=record.ended_at, removed_effective_at=record.ended_effective_at,
            baseline_anchors=record.baseline_anchors, removal_anchors=record.end_anchors)

    async def _position_status(self, state: PartState, record: PositionLifetimeRecord) -> dict:
        now = utc_now()
        if record.host_part_instance_id:
            host_segments = sorted(state.segments.get(record.host_part_instance_id, ()),
                                   key=lambda s: s.effective_start)
            items = await self._segment_inputs(host_segments, now)
            active = next((s for s in host_segments if s.status == InstallationSegmentStatus.ACTIVE), None)
            last = active or (host_segments[-1] if host_segments else None)
            placement = (last.asset_type, last.asset_id) if last else (None, None)
            installed = active is not None
            usage_items = items
            window = dict(start_at=record.effective_start, start_anchors=record.baseline_anchors,
                          end_at=record.effective_end, end_anchors=record.end_anchors)
        else:
            placement = (record.asset_type, record.asset_id)
            installed = record.ended_at is None
            usage_items = await self._segment_inputs([self._record_segment(record)], now)
            window = dict(start_at=None)
        model_id = await self._model_id(*placement)
        rules, inactive = applicable_rules(state, record.part_id, model_id, record.lifetime_rule_id)
        vehicle_id = placement[1] if placement[0] == AssetType.VEHICLE else None
        bases = await self._bases(rules, vehicle_id, [i.segment.asset_id for i in usage_items
                                                      if i.segment.asset_type == AssetType.VEHICLE])
        counters_by_basis = {}
        for basis in bases:
            usage = clipped_usage(usage_items, basis, **window)
            counters_by_basis[basis] = record_counters(prior_usage=record.prior_usage, usage=usage,
                                                       policy=self.policy, basis=basis)
        predecessor = any(r.superseded_by_id == record.position_lifetime_id for r in state.positions.values())
        anchor = _bangkok_date(record.effective_start)
        events = state.maintenance.get(record.position_lifetime_id, ())
        window_items = usage_items
        since = await self._since_events(events, rules, window_items, record.position_lifetime_id, bases)
        return {
            "target_type": "POSITION_LIFETIME",
            "target_id": record.position_lifetime_id,
            "part_id": record.part_id,
            "status": "ACTIVE" if record.ended_at is None else "ENDED",
            "policy_context": "TEST" if self.policy.is_test else "REAL",
            "evaluated_at": now.isoformat(),
            "host": {"asset_type": placement[0].value if placement[0] else None, "asset_id": placement[1],
                     "position_code": record.position_code, "model_id": model_id, "installed": installed,
                     "host_part_instance_id": record.host_part_instance_id},
            "lifecycle": {"lifecycle_id": record.position_lifetime_id, "cycle_number": 2 if predecessor else 1,
                          "start_reason": "REPLACEMENT" if predecessor else "ENROLLMENT",
                          "start_trigger_event_id": None},
            "approval": None,
            "declarations": {"prior_usage": declaration_view(record.prior_usage), "prior_cycle_usage": None},
            "counters": [counters_view(b, c) for b, c in counters_by_basis.items()],
            "rules": self._evaluate(rules, counters_by_basis, since,
                                    CalendarInputs(anchor, bool(record.host_part_instance_id) and not installed),
                                    target_type="POSITION_LIFETIME", target_id=record.position_lifetime_id,
                                    lifecycle_id=record.position_lifetime_id, cycle_number=2 if predecessor else 1),
            "inactive_rules": [{"lifetime_rule_id": r.lifetime_rule_id, "reason": "VEHICLE_OVERRIDE_NOT_ACTIVE"}
                               for r in inactive],
        }

    # ---- asset summary ----

    async def asset_summary(self, asset_type: AssetType, asset_id: str) -> dict:
        # CG-1: the asset itself must be in the request's scope, and nothing associated with another scope
        # (an instance with history elsewhere, and so its hosted positions) is shown nested under it.
        await require_asset_scope(self._repository, asset_type, asset_id, self._data_context, self._batch_id)
        state = await self._repository.read_part_state()
        scope = AssetScopeFilter(self._repository, self._data_context, self._batch_id)
        instance_ids = sorted(iid for iid, segments in state.segments.items()
                              if any(s.status == InstallationSegmentStatus.ACTIVE and s.asset_type == asset_type
                                     and s.asset_id == asset_id for s in segments))
        instances = []
        for iid in instance_ids:
            if not await scope.allows_segments(state.segments.get(iid, ())):
                continue
            view = await self._instance_status(state, detail_from_state(state, iid))
            hosted = [await self._position_status(state, r)
                      for r in sorted(state.positions.values(), key=lambda r: r.position_lifetime_id)
                      if r.host_part_instance_id == iid and r.ended_at is None]
            view["hosted_positions"] = hosted
            instances.append(view)
        positions = [await self._position_status(state, r)
                     for r in sorted(state.positions.values(), key=lambda r: r.position_lifetime_id)
                     if not r.host_part_instance_id and r.ended_at is None and r.asset_type == asset_type
                     and r.asset_id == asset_id]
        return {"asset_type": asset_type.value, "asset_id": asset_id,
                "policy_context": "TEST" if self.policy.is_test else "REAL",
                "instances": instances, "positions": positions}


__all__ = ["PartLifetimeStatusService", "TestOnlyPartMeterSource", "applicable_rules", "TEST_FAKE_DEVICE_ID"]
