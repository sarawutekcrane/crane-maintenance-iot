"""DUE-02A synthetic Mock evidence tests; NOT a real B1-to-E01 bridge.

All witnesses, V2 scope permissions, source mappings, and actual-close-meter
trust flags are INVENTED TEST VALUES. No real DB, Sheets, Git, network, or
production data is accessed, and no E01 code is modified or invoked.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.pm_due_evidence import (
    CloseSnapshot, CloseTransition, CurrentMeter, FrozenSet, ItemOutcome,
    ItemResult, MappedItem, MeterReading, WorkOrder, evaluate_set_due,
)

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def frozen(**changes) -> FrozenSet:
    f = FrozenSet(
        set_ref="SYN-V1|PLAN-A|CARRIER|SET-A", asset_type="VEHICLE",
        asset_id="SYN-V1", pm_plan_id="SYN-PLAN-A", revision_id="SYN-REV-1",
        items=tuple(MappedItem(f"SOURCE!row:{10+i}", f"SYN-TASK-{i}", True) for i in range(1, 6)),
        meter_type="ENGINE_HOUR", interval=600, interval_unit="HOUR",
        driving_component_role="CARRIER_ENGINE", component_id="SYN-CARRIER-ENGINE",
        source_verified=True, lineage_verified=True, component_verified=True,
    )
    return replace(f, **changes)


def km_set(**changes) -> FrozenSet:
    fields = dict(
        set_ref="SYN-V1|PLAN-A|CARRIER|SET-G",
        items=tuple(MappedItem(f"SHEETG!row:{i}", f"SYN-G-{i}", True) for i in (1, 2)),
        meter_type="ODOMETER", interval=5000, interval_unit="KM",
        driving_component_role="VEHICLE", component_id=None,
    )
    fields.update(changes)
    return frozen(**fields)


def current(value=1249, **changes) -> CurrentMeter:
    return replace(CurrentMeter("ENGINE_HOUR", "SYN-CARRIER-ENGINE", value, True), **changes)


def km_current(value=23199, **changes) -> CurrentMeter:
    return replace(CurrentMeter("ODOMETER", None, value, True), **changes)


def work_order(*, anchor=650, number=1, completed=5, at=None, scope=None,
               extra_outcomes=(), extra_results=(), extra_readings=()) -> WorkOrder:
    at = at or (T0 + timedelta(days=number))
    ref = f"SYN-PMWO-{number}"
    outcomes = tuple(ItemOutcome(f"SYN-TASK-{i}", ref, "SYN-REV-1",
                                 "PERFORMED" if i <= completed else "NOT_PERFORMED", f"SYN-R-{number}-{i}")
                     for i in range(1, 6)) + tuple(extra_outcomes)
    results = tuple(ItemResult(f"SYN-R-{number}-{i}", f"SYN-TASK-{i}", ref, "SYN-REV-1", i <= completed)
                    for i in range(1, 6)) + tuple(extra_results)
    snapshot = CloseSnapshot(f"SYN-SNAP-{number}", "VEHICLE", "SYN-V1",
                             at + timedelta(seconds=1), True, "PM_WORK_ORDER_CLOSE",
                             (MeterReading("ENGINE_HOUR", "SYN-CARRIER-ENGINE", anchor),
                              *tuple(extra_readings)), True)
    return WorkOrder(ref, "VEHICLE", "SYN-V1", "SYN-PLAN-A", "SYN-REV-1", "CLOSED", at,
                     "TECHNICIAN_V2", tuple(scope if scope is not None else (f"SYN-TASK-{i}" for i in range(1, 6))),
                     outcomes, results, (CloseTransition(ref, "CLOSE", "PENDING_REVIEW", "CLOSED", at, True),),
                     snapshot.meter_snapshot_id, snapshot, True, True)


def assert_unknown(out, reason: str) -> None:
    assert out.due.status == "UNKNOWN"
    assert out.due.next_due is None
    assert out.due.reason == reason
    assert out.source_pm_work_order_id is None
    assert out.source_meter_snapshot_id is None


@pytest.mark.parametrize("reading,expected", [(1249, "NOT_DUE"), (1250, "DUE"), (1300, "DUE")])
def test_a01_fully_completed_real_set_threshold(reading, expected):
    decision = evaluate_set_due(frozen(), (work_order(),), current(reading))
    assert (decision.due.status, decision.due.next_due) == (expected, 1250)
    assert decision.source_pm_work_order_id == "SYN-PMWO-1"
    assert decision.source_meter_snapshot_id == "SYN-SNAP-1"


def test_a02_four_of_five_closed_does_not_reanchor():
    assert_unknown(evaluate_set_due(frozen(), (work_order(completed=4),), current()),
                   "NO_VERIFIED_ACTUAL_SET_COMPLETION")


def test_a03_fully_performed_a_and_partial_independent_g_in_same_wo():
    wo = work_order(extra_outcomes=(ItemOutcome("SYN-G-1", "SYN-PMWO-1", "SYN-REV-1", "PERFORMED", "RG1"),
                                    ItemOutcome("SYN-G-2", "SYN-PMWO-1", "SYN-REV-1", "NOT_PERFORMED", "RG2")),
                    extra_results=(ItemResult("RG1", "SYN-G-1", "SYN-PMWO-1", "SYN-REV-1", True),
                                   ItemResult("RG2", "SYN-G-2", "SYN-PMWO-1", "SYN-REV-1", False)),
                    extra_readings=(MeterReading("ODOMETER", None, 18200),),
                    scope=tuple(f"SYN-TASK-{i}" for i in range(1, 6)) + ("SYN-G-1", "SYN-G-2"))
    assert evaluate_set_due(frozen(), (wo,), current()).due.next_due == 1250
    assert_unknown(evaluate_set_due(km_set(), (wo,), km_current()), "NO_VERIFIED_ACTUAL_SET_COMPLETION")


def test_a04_newer_partial_does_not_displace_older_complete():
    decision = evaluate_set_due(frozen(), (work_order(number=1), work_order(number=3, anchor=900, completed=4)), current())
    assert (decision.source_pm_work_order_id, decision.due.next_due) == ("SYN-PMWO-1", 1250)


def test_a05_unrelated_repair_cannot_be_passed_as_completion_work_order():
    # The pure function has NO Repair/Outstanding resolution input by design.
    decision = evaluate_set_due(frozen(), (work_order(),), current())
    assert (decision.source_pm_work_order_id, decision.due.next_due) == ("SYN-PMWO-1", 1250)
    assert_unknown(evaluate_set_due(frozen(), (), current()), "NO_VERIFIED_ACTUAL_SET_COMPLETION")


@pytest.mark.parametrize("change", [
    {"source_verified": False}, {"lineage_verified": False},
    {"items": (MappedItem("SOURCE!row:11", "SYN-TASK-1", False),)},
    {"items": (MappedItem("DUP", "SYN-TASK-1", True), MappedItem("DUP", "SYN-TASK-2", True))},
    {"items": (MappedItem("A", "SYN-TASK-1", True), MappedItem("B", "SYN-TASK-1", True))},
    {"items": ()}, {"set_ref": ""}, {"asset_type": "EQUIPMENT"},
])
def test_a06_unverified_or_duplicate_master_item_linkage(change):
    assert_unknown(evaluate_set_due(frozen(**change), (work_order(),), current()),
                   "FROZEN_SET_ITEM_MAPPING_UNVERIFIED")


def test_a07_all_selected_tasks_done_but_not_every_required_set_item():
    wo = work_order(scope=("SYN-TASK-1", "SYN-TASK-2"))
    assert_unknown(evaluate_set_due(frozen(), (wo,), current()), "NO_VERIFIED_ACTUAL_SET_COMPLETION")


@pytest.mark.parametrize("changes", [
    {"outcomes": (ItemOutcome("SYN-TASK-1", "BAD-WO", "SYN-REV-1", "PERFORMED", "SYN-R-1-1"),)},
    {"results": (ItemResult("SYN-R-1-1", "SYN-TASK-1", "BAD-WO", "SYN-REV-1", True),)},
    {"assignment_model": "LEGACY"}, {"v2_scope_verified": False}, {"data_scope_verified": False},
    {"results": tuple(replace(r, pm_work_result_id="DUPLICATE") for r in work_order().results)},
])
def test_a08_bad_item_provenance_or_scope_is_not_accepted(changes):
    # A malformed outcome/result loses other required tasks: never full Set.
    wo = replace(work_order(), **changes)
    expected = ("COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED" if any(k in changes for k in
                ("assignment_model", "v2_scope_verified", "data_scope_verified"))
                else "NO_VERIFIED_ACTUAL_SET_COMPLETION")
    assert_unknown(evaluate_set_due(frozen(), (wo,), current()), expected)


@pytest.mark.parametrize("transition", [
    None,
    CloseTransition("SYN-PMWO-1", "CLOSE", "PENDING_REVIEW", "CLOSED", T0 + timedelta(days=1), False),
    CloseTransition("SYN-PMWO-1", "CLOSE", "OPEN", "CLOSED", T0 + timedelta(days=1), True),
    CloseTransition("SYN-PMWO-1", "SUBMIT", "IN_PROGRESS", "PENDING_REVIEW", T0 + timedelta(days=1), True),
    CloseTransition("WRONG-WO", "CLOSE", "PENDING_REVIEW", "CLOSED", T0 + timedelta(days=1), True),
])
def test_a09_missing_or_inconsistent_journal_fails_without_repair(transition):
    events = () if transition is None else (transition,)
    wo = replace(work_order(), transitions=events)
    assert_unknown(evaluate_set_due(frozen(), (wo,), current()), "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")


@pytest.mark.parametrize("status", ["OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CANCELLED"])
def test_a10_open_or_non_closed_wo_is_not_completion(status):
    wo = replace(work_order(), status=status, transitions=())
    assert_unknown(evaluate_set_due(frozen(), (wo,), current()), "NO_VERIFIED_ACTUAL_SET_COMPLETION")


@pytest.mark.parametrize("change", [
    {"closed_snapshot_id": None}, {"closed_snapshot_id": "DIFFERENT"},
    {"close_snapshot": None},
    {"close_snapshot": replace(work_order().close_snapshot, is_automatic=False)},
    {"close_snapshot": replace(work_order().close_snapshot, source_note="PM_TASK_RESULT")},
    {"close_snapshot": replace(work_order().close_snapshot, asset_id="OTHER-ASSET")},
    {"close_snapshot": replace(work_order().close_snapshot, asset_type="EQUIPMENT")},
    {"close_snapshot": replace(work_order().close_snapshot, recorded_at=T0)},
    {"close_snapshot": replace(work_order().close_snapshot, actual_completion_meter_verified=False)},
    {"close_snapshot": replace(work_order().close_snapshot, readings=())},
    {"close_snapshot": replace(work_order().close_snapshot,
                               readings=(MeterReading("ENGINE_HOUR", "SYN-CARRIER-ENGINE", None),))},
    {"close_snapshot": replace(work_order().close_snapshot,
                               readings=(MeterReading("ENGINE_HOUR", "SYN-CARRIER-ENGINE", 650),
                                         MeterReading("ENGINE_HOUR", "SYN-CARRIER-ENGINE", 650)))},
])
def test_a11_missing_wrong_close_snapshot_is_unknown(change):
    assert_unknown(evaluate_set_due(frozen(), (replace(work_order(), **change),), current()),
                   "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")


def test_a12_km_odometer_and_forbidden_pto():
    wo = work_order(extra_outcomes=tuple(ItemOutcome(f"SYN-G-{i}", "SYN-PMWO-1", "SYN-REV-1", "PERFORMED", f"RG{i}")
                                          for i in (1, 2)),
                    extra_results=tuple(ItemResult(f"RG{i}", f"SYN-G-{i}", "SYN-PMWO-1", "SYN-REV-1", True)
                                        for i in (1, 2)),
                    extra_readings=(MeterReading("ODOMETER", None, 18200),),
                    scope=tuple(f"SYN-TASK-{i}" for i in range(1, 6)) + ("SYN-G-1", "SYN-G-2"))
    decision = evaluate_set_due(km_set(), (wo,), km_current(23200))
    assert (decision.due.status, decision.due.next_due) == ("DUE", 23200)
    assert_unknown(evaluate_set_due(frozen(meter_type="PTO_HOUR"), (wo,), current()), "PM_METER_NOT_APPROVED")


@pytest.mark.parametrize("input_value", [None, -1, float("inf"), float("nan")])
def test_a13_current_meter_unknown_or_invalid(input_value):
    decision = evaluate_set_due(frozen(), (work_order(),), current(input_value))
    assert_unknown(decision, "CURRENT_METER_UNVERIFIED")


def test_a13b_current_meter_dimension_and_trust():
    assert_unknown(evaluate_set_due(frozen(), (work_order(),), current(verified=False)),
                   "CURRENT_METER_UNVERIFIED")
    assert_unknown(evaluate_set_due(frozen(), (work_order(),), current(component_id="OTHER")),
                   "CURRENT_METER_DIMENSION_MISMATCH")


def test_a14_previous_due01_threshold_still_applies():
    assert evaluate_set_due(frozen(interval=600), (work_order(),), current(1250)).due.is_due is True


def test_a15_no_mutation_and_stable_repeated_read():
    f, wo, c = frozen(), work_order(), current()
    original = (repr(f), repr(wo), repr(c))
    first = evaluate_set_due(f, (wo,), c)
    second = evaluate_set_due(f, (wo,), c)
    assert first == second
    assert (repr(f), repr(wo), repr(c)) == original


def test_a16_equal_time_competing_complete_work_orders_ambiguous():
    at = T0 + timedelta(days=2)
    assert_unknown(evaluate_set_due(frozen(), (work_order(number=1, at=at), work_order(number=2, at=at)), current()),
                   "LATEST_SET_COMPLETION_AMBIGUOUS")


def test_a17_uncertain_new_complete_work_order_blocks_old_anchor():
    old, latest = work_order(number=1), work_order(number=2, anchor=800)
    latest = replace(latest, close_snapshot=replace(latest.close_snapshot, actual_completion_meter_verified=False))
    assert_unknown(evaluate_set_due(frozen(), (old, latest), current()),
                   "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")


def test_a18_actual_verified_zero_not_substituted_for_unknown():
    decision = evaluate_set_due(frozen(), (work_order(anchor=0),), current(600))
    assert (decision.due.status, decision.due.next_due) == ("DUE", 600)
    missing = work_order(anchor=None)
    assert_unknown(evaluate_set_due(frozen(), (missing,), current(600)), "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")


def test_a19_different_asset_plan_revision_does_not_qualify():
    base = work_order()
    for field, wrong in (("asset_id", "OTHER"), ("asset_type", "EQUIPMENT"),
                         ("pm_plan_id", "OTHER"), ("revision_id", "SYN-REV-2")):
        assert_unknown(evaluate_set_due(frozen(), (replace(base, **{field: wrong}),), current()),
                       "NO_VERIFIED_ACTUAL_SET_COMPLETION")


def test_a20_later_performed_work_from_other_set_does_not_update_anchor():
    other_set_only = replace(work_order(number=2, anchor=900), scope_task_ids=("OTHER-TASK",), outcomes=(), results=())
    decision = evaluate_set_due(frozen(), (work_order(), other_set_only), current(1249))
    assert (decision.due.status, decision.due.next_due, decision.source_pm_work_order_id) == (
        "NOT_DUE", 1250, "SYN-PMWO-1")


def test_a21_stale_closed_projection_is_not_a_false_noncompletion():
    wo = replace(work_order(), status="PENDING_REVIEW")
    assert_unknown(evaluate_set_due(frozen(), (wo,), current()), "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")


@pytest.mark.parametrize("closed_at", [None, T0, datetime(2026, 11, 2, 9, 0)])
def test_a22_missing_or_conflicting_header_close_time_is_unknown(closed_at):
    wo = replace(work_order(), closed_at=closed_at)
    assert_unknown(evaluate_set_due(frozen(), (wo,), current()), "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")


def test_a23_historical_completed_set_meter_must_not_silently_decrease():
    history = (work_order(number=1, anchor=650), work_order(number=2, anchor=640))
    assert_unknown(evaluate_set_due(frozen(), history, current(1200)),
                   "COMPLETION_METER_DECREASE_UNRESOLVED")
