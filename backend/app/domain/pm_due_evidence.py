"""R4 DUE-02A: PURE, synthetic-evidence check before the DUE-01 calculator.

This is NOT a B1->E01 source-ID resolver. The caller must independently
establish the frozen Set/Item mapping and V2 authorization; none of that can be
inferred from a CLOSED work order, a similar task description or a boolean chosen
by a browser. Only separately approved B2 integration may supply that proof.

Completion anchor (DEC-R4-TASK010-PM-TECH-SUBMIT-ANCHOR-003): the reviewer's CLOSE
only ACCEPTS the work. The completion time is the accepted technician SUBMIT (the
journal event immediately before the final CLOSE: PENDING_REVIEW is reachable only
by SUBMIT, so an earlier SUBMIT followed by RETURN is never it), and the completion
meter is the IoT reading bound to exactly that SUBMIT (`pm_meter_anchor`). A CLOSE
machine-state snapshot is never a completion meter.

No I/O, writes, clocks, repair credit, event journal, master publish, API or
new persisted Due status. DUE-01 remains the only threshold calculator.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.pm_due import PmDueDecision, PmDueInputs, calculate_pm_due
from app.domain.pm_meter_anchor import PmSubmitMeterAnchor, _instant, _meter


@dataclass(frozen=True)
class MappedItem:
    """One proven B1 source Item -> frozen E01 task mapping (synthetic only)."""

    source_item_key: str
    pm_task_id: str
    verified: bool = False


@dataclass(frozen=True)
class FrozenSet:
    set_ref: str
    asset_type: str
    asset_id: str
    pm_plan_id: str
    revision_id: str
    items: tuple[MappedItem, ...]
    meter_type: str
    interval: float
    interval_unit: str
    driving_component_role: str | None = None
    component_id: str | None = None
    source_verified: bool = False
    lineage_verified: bool = False
    component_verified: bool = False


@dataclass(frozen=True)
class ItemOutcome:
    pm_task_id: str
    pm_work_order_id: str
    revision_id: str
    disposition: str
    source_pm_work_result_id: str | None


@dataclass(frozen=True)
class ItemResult:
    pm_work_result_id: str
    pm_task_id: str
    pm_work_order_id: str
    revision_id: str
    completed: bool


@dataclass(frozen=True)
class CloseTransition:
    """One E01 journal event (any action, despite the historical name)."""

    pm_work_order_id: str
    action: str
    from_status: str
    to_status: str
    occurred_at: datetime
    is_authoritative: bool = False
    event_id: str = ""


@dataclass(frozen=True)
class WorkOrder:
    pm_work_order_id: str
    asset_type: str
    asset_id: str
    pm_plan_id: str
    revision_id: str
    status: str
    closed_at: datetime | None
    assignment_model: str
    scope_task_ids: tuple[str, ...]
    outcomes: tuple[ItemOutcome, ...]
    results: tuple[ItemResult, ...]
    transitions: tuple[CloseTransition, ...]
    submit_anchor: PmSubmitMeterAnchor | None
    # Both flags must come from server authorization / data-scope checks later.
    v2_scope_verified: bool = False
    data_scope_verified: bool = False


@dataclass(frozen=True)
class CurrentMeter:
    counter_type: str
    component_id: str | None
    value: float | None
    verified: bool = False


@dataclass(frozen=True)
class SetDueEvidenceDecision:
    due: PmDueDecision
    source_pm_work_order_id: str | None = None
    source_submit_event_id: str | None = None


def _unknown(reason: str) -> SetDueEvidenceDecision:
    return SetDueEvidenceDecision(PmDueDecision(status="UNKNOWN", reason=reason))


def _identified(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping_ok(frozen: FrozenSet) -> bool:
    if (frozen.source_verified is not True or frozen.lineage_verified is not True
            or frozen.asset_type != "VEHICLE"
            or not all(map(_identified, (frozen.set_ref, frozen.asset_id,
                                          frozen.pm_plan_id, frozen.revision_id)))
            or not frozen.items):
        return False
    keys = [i.source_item_key for i in frozen.items]
    tasks = [i.pm_task_id for i in frozen.items]
    return (all(i.verified is True for i in frozen.items)
            and all(map(_identified, keys + tasks))
            and len(set(keys)) == len(keys) and len(set(tasks)) == len(tasks))


def _set_is_performed(frozen: FrozenSet, wo: WorkOrder) -> bool:
    """Exact frozen full Set, not merely all *selected* scope tasks."""
    scope = wo.scope_task_ids
    required = {i.pm_task_id for i in frozen.items}
    if len(scope) != len(set(scope)) or not required.issubset(scope):
        return False
    # One physical result must never be credited to two separate required tasks.
    matching_results = [r for r in wo.results if r.pm_task_id in required]
    ids = [r.pm_work_result_id for r in matching_results]
    if len(ids) != len(set(ids)):
        return False
    for task_id in required:
        outcomes = [o for o in wo.outcomes if o.pm_task_id == task_id]
        results = [r for r in wo.results if r.pm_task_id == task_id]
        if len(outcomes) != 1 or len(results) != 1:
            return False
        o, r = outcomes[0], results[0]
        if (o.disposition != "PERFORMED" or r.completed is not True
                or o.pm_work_order_id != wo.pm_work_order_id
                or r.pm_work_order_id != wo.pm_work_order_id
                or o.revision_id != frozen.revision_id
                or r.revision_id != frozen.revision_id
                or not _identified(r.pm_work_result_id)
                or o.source_pm_work_result_id != r.pm_work_result_id):
            return False
    return True


def _completion(frozen: FrozenSet, wo: WorkOrder) -> tuple[str, datetime | None, float | None]:
    """Return (NOT_COMPLETE|UNKNOWN|QUALIFIED, closure time, actual meter)."""
    if (wo.asset_type, wo.asset_id, wo.pm_plan_id, wo.revision_id) != (
            frozen.asset_type, frozen.asset_id, frozen.pm_plan_id, frozen.revision_id):
        return "NOT_COMPLETE", None, None  # Not a source candidate for this Set.
    if wo.status != "CLOSED":
        if (wo.transitions and wo.transitions[-1].action == "CLOSE"
                and wo.transitions[-1].to_status == "CLOSED"):
            # An interrupted E01 projection is NOT a harmless non-completion.
            # Calling E01 _current_status could WRITE: fail closed instead.
            return "UNKNOWN", None, None
        return "NOT_COMPLETE", None, None
    if not _set_is_performed(frozen, wo):
        return "NOT_COMPLETE", None, None  # Partial WO: earlier anchor survives.
    if (wo.assignment_model != "TECHNICIAN_V2" or wo.v2_scope_verified is not True
            or wo.data_scope_verified is not True):
        return "UNKNOWN", None, None

    # Do not call E01 _current_status: it may PROJECT a state and WRITE.
    if len(wo.transitions) < 2:
        return "UNKNOWN", None, None
    close, submit = wo.transitions[-1], wo.transitions[-2]
    if (close.pm_work_order_id != wo.pm_work_order_id or close.action != "CLOSE"
            or close.from_status != "PENDING_REVIEW" or close.to_status != "CLOSED"
            or close.is_authoritative is not True or not _instant(close.occurred_at)
            or not _instant(wo.closed_at) or wo.closed_at != close.occurred_at):
        return "UNKNOWN", None, None
    # The accepted technician SUBMIT is the event the CLOSE accepted (DEC-003).
    if (submit.pm_work_order_id != wo.pm_work_order_id or submit.action != "SUBMIT"
            or submit.from_status != "IN_PROGRESS" or submit.to_status != "PENDING_REVIEW"
            or submit.is_authoritative is not True or not _identified(submit.event_id)
            or not _instant(submit.occurred_at) or submit.occurred_at > close.occurred_at):
        return "UNKNOWN", None, None
    anchor = wo.submit_anchor
    if (anchor is None or anchor.pm_work_order_id != wo.pm_work_order_id
            or anchor.submit_event_id != submit.event_id or anchor.submitted_at != submit.occurred_at
            or (anchor.asset_type, anchor.asset_id) != (wo.asset_type, wo.asset_id)):
        return "UNKNOWN", None, None
    readings = [r for r in anchor.readings
                if (r.counter_type, r.component_id) == (frozen.meter_type, frozen.component_id)]
    if len(readings) != 1:
        return "UNKNOWN", None, None
    r = readings[0]
    window = anchor.max_observation_age
    if (not _meter(r.value) or r.device_verified is not True or r.time_quality != "TIME_SYNCED"
            or not _identified(r.device_id) or not _identified(r.device_event_id)
            or not _instant(r.observed_at) or not _instant(r.received_at)
            or r.observed_at > submit.occurred_at or r.received_at > submit.occurred_at
            or not window or submit.occurred_at - r.observed_at > window):
        return "UNKNOWN", None, None
    return "QUALIFIED", submit.occurred_at, float(r.value)


def evaluate_set_due(frozen: FrozenSet, work_orders: tuple[WorkOrder, ...],
                     current: CurrentMeter) -> SetDueEvidenceDecision:
    """Return qualified same-Set next Due, or UNKNOWN without changing state.

    This is a Mock proof over *trusted input fixtures*, not a real reader.
    In particular, true flags cannot be safely populated from frontend data.
    """
    if not _mapping_ok(frozen):
        return _unknown("FROZEN_SET_ITEM_MAPPING_UNVERIFIED")
    if frozen.meter_type not in ("ENGINE_HOUR", "ODOMETER"):
        return _unknown("PM_METER_NOT_APPROVED")
    if frozen.meter_type == "ENGINE_HOUR":
        if (frozen.driving_component_role not in ("CARRIER_ENGINE", "CRANE_ENGINE")
                or not _identified(frozen.component_id)
                or frozen.component_verified is not True):
            return _unknown("PHYSICAL_ENGINE_UNVERIFIED")
    elif frozen.component_id is not None or frozen.driving_component_role not in (None, "VEHICLE"):
        return _unknown("ODOMETER_MUST_BE_VEHICLE_LEVEL")

    candidates: list[tuple[datetime, WorkOrder, float]] = []
    for wo in work_orders:
        state, at, meter = _completion(frozen, wo)
        if state == "UNKNOWN":
            # An apparent complete WO whose authority or historical meter
            # cannot be proven might supersede an older known completion.
            return _unknown("COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")
        if state == "QUALIFIED":
            assert at is not None and meter is not None
            candidates.append((at, wo, meter))
    if not candidates:
        return _unknown("NO_VERIFIED_ACTUAL_SET_COMPLETION")
    # A replacement/reset policy has not been authorized for historical PM
    # counters. Refuse a conflicting sequence rather than inventing an anchor.
    ordered = sorted(candidates, key=lambda entry: entry[0])
    if any(later[2] < earlier[2] for earlier, later in zip(ordered, ordered[1:])):
        return _unknown("COMPLETION_METER_DECREASE_UNRESOLVED")
    latest_at = max(at for at, _, _ in candidates)
    latest = [(wo, value) for at, wo, value in candidates if at == latest_at]
    if len(latest) != 1:
        return _unknown("LATEST_SET_COMPLETION_AMBIGUOUS")
    wo, last_actual = latest[0]
    if (current.counter_type, current.component_id) != (frozen.meter_type, frozen.component_id):
        return _unknown("CURRENT_METER_DIMENSION_MISMATCH")
    due = calculate_pm_due(PmDueInputs(
        set_ref=frozen.set_ref,
        meter_type=frozen.meter_type,
        interval=frozen.interval,
        interval_unit=frozen.interval_unit,
        last_completed_meter=last_actual,
        current_meter=current.value,
        source_verified=True,
        last_completion_verified=True,
        current_meter_verified=current.verified is True,
        driving_component_role=frozen.driving_component_role,
        component_id=frozen.component_id,
        component_verified=frozen.component_verified,
    ))
    if due.status == "UNKNOWN":
        return SetDueEvidenceDecision(due)
    return SetDueEvidenceDecision(due, wo.pm_work_order_id, wo.submit_anchor.submit_event_id)
