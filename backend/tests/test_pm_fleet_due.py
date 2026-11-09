"""R4 / TASK-010 Fleet PM Due B1: the read-only fleet / vehicle PM Due read model.

Every Master row is the SYNTHETIC B1 fixture, published and assigned only through the
test-local authorizers (OPEN-005 stays closed in the application), and every model
variant comes from the TEST-ONLY `synthetic_test_only_variants` source (OPEN-016 has no
real mapping). Every IoT reading is an invented FAKE observation. The runtime Master is
injected into `PmService` by these tests only: the application wiring passes none.
This proves the contract on the Mock repository, not Google Sheets, PostgreSQL or
ESP32 telemetry."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain import authz
from app.domain.meter_service import MeterService
from app.domain.pm import PmTriggerType
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.pm_master import PlanResolution
from app.domain.pm_master_runtime import applicable_plans
from app.domain.pm_meter_anchor import NO_IOT_METER_SOURCE
from app.domain.pm_service import PmService
from app.domain.vehicle import VehicleComponent
from app.domain.vehicle_model import ComponentRole
from app.errors import ApiError
from app.repositories.base import RepositoryFeatureNotImplementedError
from tests.pm_e01_support import ctx, manager, rid, start
from tests.test_pm_master_b1_mock import CARRIER_A, CRANE_A, KM_SET, PLAN, PLAN_B
from tests.test_pm_master_b1_mock import ctx as master_ctx
from tests.test_pm_master_e01_due_bridge import (
    BACKEND,
    CARRIER_ENG,
    CRANE_ENG,
    VEH,
    World,
    complete,
    current_source,
    open_wo,
    publish_rev2,
    report_engines,
    submit,
    synthetic_test_only_variants,
    tasks_of,
    unbound_or_foreign_masters,
    world,
)
from tests.test_pm_read_security import get_as
from tests.test_pm_submit_meter_anchor import WRITES, FakeIotSource
from app.domain.technician_assignment import ASSIGNMENT_MODEL_LEGACY, PM
from tests.test_technician_assignment_batch_r2f_h1 import T1, T2, assign, body, cut

API = "/api/v1"
FLEET = f"{API}/pm/due/vehicles"
VIEW = frozenset({authz.CAN_VIEW})
SYN_M1_SETS = sorted([CARRIER_A, KM_SET, CRANE_A])


def due_svc(w: World, source=None, *, variants=synthetic_test_only_variants, master=True, **cutover) -> PmService:
    """TEST-ONLY dependency injection of the synthetic Master and variant source."""
    svc = PmService(w.repo, MeterService(w.repo, iot_meter_source=source or NO_IOT_METER_SOURCE),
                    assignment_cutover=cut(**cutover))
    return svc.with_master_reads(w.master, variants) if master else svc


async def vdue(w: World, *, source=None, svc=None, vehicle=VEH, context=None):
    svc = svc or due_svc(w, source)
    return await svc.read_vehicle_pm_due(context or ctx("SYN-VIEWER", authz.CAN_VIEW), vehicle)


def row(v, set_key):
    [hit] = [s for s in v.sets if s.set_key == set_key]
    return hit


def status(s):
    return s.status, s.next_due, s.diagnostic_code


async def assign_plan(w: World, vehicle=VEH, assembly="", plan=PLAN, version=0):
    await w.master.set_assignment(master_ctx(), vehicle_id=vehicle, assembly=assembly, plan_code=plan,
                                  expected_version=version, reason="กำหนดแผนทดสอบ (synthetic)", request_id=rid())


def state_of(w: World):
    r = w.repo
    return (dict(r._pm_work_orders), r._pm_master_memberships, dict(r._meter_snapshots),
            dict(r._pm_submit_meter_anchors), {k: list(v) for k, v in r._pm_transitions.items()},
            dict(r._pm_task_revisions), dict(r._pm_item_outcomes), {k: list(v) for k, v in r._pm_work_results.items()},
            w.store.events, w.store.assignments)


async def data_invalid(w: World, issue: str, *, svc=None) -> None:
    before = state_of(w)
    with pytest.raises(ApiError) as failed:
        await vdue(w, svc=svc)
    assert (failed.value.status_code, failed.value.code, failed.value.details) == (
        500, "PM_WORK_ORDER_DATA_INVALID", {"issues": {issue: 1}})
    assert state_of(w) == before


async def completed_world(carrier=1000, crane=2000, odometer=50000, keys=(CARRIER_A, CRANE_A, KM_SET)):
    w = await world()
    report_engines(w, carrier=carrier, crane=crane, odometer=odometer)
    job = await open_wo(w, list(keys))
    await complete(w, job)
    return w, job


# ---------------------------------------------------------------- A. canonical Set discovery


async def test_f01_a_vehicle_without_any_work_order_keeps_every_applicable_set_as_unknown() -> None:
    w = await world()  # VEH-1047 explicitly assigned to the Plan; no Work Order ever opened
    v = await vdue(w, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1234, ("ODOMETER", None): 9000}))
    assert (v.state, [(p.plan_code, p.state, p.revision_number, p.model_variant) for p in v.plans]) == (
        "AVAILABLE", [(PLAN, "RESOLVED", 1, "SYN-M1")])
    assert [s.set_key for s in v.sets] == SYN_M1_SETS  # never another variant's Sets
    for s in v.sets:
        assert status(s) == ("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION")
        assert s.last_completed_meter is None and s.last_completed_pm_work_order_id is None
        assert s.explanation and s.explanation != s.diagnostic_code
    carrier, crane, km = row(v, CARRIER_A), row(v, CRANE_A), row(v, KM_SET)
    assert (carrier.meter_type, carrier.interval_value, carrier.interval_unit, carrier.component_id) == (
        "ENGINE_HOUR", 500.0, "HOUR", CARRIER_ENG)
    assert (crane.interval_value, crane.component_id, crane.driving_component_role) == (600.0, CRANE_ENG,
                                                                                         "CRANE_ENGINE")
    assert (km.meter_type, km.interval_unit, km.component_id) == ("ODOMETER", "KM", None)
    # The verified current reading is displayed; it never turns UNKNOWN into a Due.
    assert (carrier.current_meter, km.current_meter, crane.current_meter) == (1234.0, 9000.0, None)
    assert [(a.assembly, a.source, a.plan_code) for a in v.assignments] == [
        ("", "EXPLICIT_ASSIGNED", PLAN), ("CARRIER", "EXPLICIT_ASSIGNED", PLAN), ("CRANE", "EXPLICIT_ASSIGNED", PLAN)]


async def test_f02_no_runtime_master_is_master_not_active_never_an_empty_fleet() -> None:
    w, _ = await completed_world()
    svc = due_svc(w, master=False)
    w.repo.calls.clear()
    v = await svc.read_vehicle_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), VEH)
    assert (v.state, v.sets, v.plans, v.assignments) == ("MASTER_NOT_ACTIVE", (), (), ())
    assert "PM Master" in v.explanation
    assert "list_pm_master_memberships" not in w.repo.calls  # nothing Master-sourced is read
    page = await svc.list_fleet_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), _params())
    assert page.total_items == 3 and [r.vehicle_id for r in page.items] == ["VEH-1046", "VEH-1047", "VEH-1048"]
    assert {r.state for r in page.items} == {"MASTER_NOT_ACTIVE"}


async def test_f03_absent_explicit_none_and_assembly_none_never_falls_back() -> None:
    w = await world()
    v = await vdue(w, vehicle="VEH-1046")  # no assignment record at all
    assert (v.state, v.plans, v.sets) == ("NO_ASSIGNED_PLAN", (), ())
    assert {a.source for a in v.assignments} == {"ABSENT"}
    await assign_plan(w, assembly="CRANE", plan=None)  # explicit CRANE NONE under a vehicle-level Plan
    v = await vdue(w)
    assert [s.set_key for s in v.sets] == sorted([CARRIER_A, KM_SET])  # CRANE Set not inherited
    assert [(a.assembly, a.source) for a in v.assignments] == [
        ("", "EXPLICIT_ASSIGNED"), ("CARRIER", "EXPLICIT_ASSIGNED"), ("CRANE", "EXPLICIT_NONE")]
    await assign_plan(w, assembly="", plan=None, version=1)  # vehicle-level NONE as well
    v = await vdue(w)
    assert (v.state, v.sets) == ("NO_ASSIGNED_PLAN", ())


async def test_f04_missing_or_ambiguous_model_variant_shows_no_invented_sets() -> None:
    w = await world()
    for variants in (None, lambda m, p: frozenset(), lambda m, p: frozenset({"SYN-M1", "SYN-M2"})):
        v = await vdue(w, svc=due_svc(w, variants=variants))
        assert (v.state, [(p.state, p.model_variant, p.revision_number) for p in v.plans], v.sets) == (
            "AVAILABLE", [("MODEL_VARIANT_UNVERIFIED", None, 1)], ())
    v = await vdue(w, svc=due_svc(w, variants=lambda m, p: frozenset({"SYN-M9"})))  # proven, but no such Sets
    assert ([p.state for p in v.plans], v.sets) == (["NO_APPLICABLE_SET"], ())


async def test_f05_carrier_and_crane_assemblies_on_different_plans() -> None:
    w = await world()
    rev_b = w.rev.model_copy(update={"revision_id": f"PMMREV-{PLAN_B}-0001", "plan_code": PLAN_B,
                                     "request_id": "REQ-SYN-PLAN-B"})
    w.store.commit({"kind": "PUBLISH", "request_id": "REQ-SYN-PLAN-B", "request_fingerprint": "b"}, revision=rev_b)
    await assign_plan(w, assembly="CRANE", plan=PLAN_B)
    variants = {("MODEL-0002", PLAN): {"SYN-M1"}, ("MODEL-0002", PLAN_B): {"SYN-M1"}}
    v = await vdue(w, svc=due_svc(w, variants=lambda m, p: frozenset(variants.get((m, p), ()))))
    assert [(p.plan_code, p.state) for p in v.plans] == [(PLAN, "RESOLVED"), (PLAN_B, "RESOLVED")]
    assert [(s.plan_code, s.set_key) for s in v.sets] == [(PLAN, CARRIER_A), (PLAN, KM_SET), (PLAN_B, CRANE_A)]
    assert {status(s) for s in v.sets} == {("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION")}


def test_f05b_applicability_is_pure_and_refuses_partial_or_unpublished_input() -> None:
    absent = PlanResolution(source="ABSENT", plan_code=None, assignment_version=0, legacy_model_plan_id=None)
    assigned = PlanResolution(source="EXPLICIT_ASSIGNED", plan_code=PLAN, assignment_version=1,
                              legacy_model_plan_id=None)
    with pytest.raises(ValueError, match="PM_MASTER_ASSEMBLY_RESOLUTION_INCOMPLETE"):
        applicable_plans({"": assigned}, {}, vehicle_model_id="MODEL-0002", model_variants=synthetic_test_only_variants)
    resolutions = {"": assigned, "CARRIER": absent, "CRANE": absent}
    [plan] = applicable_plans(resolutions, {}, vehicle_model_id="MODEL-0002",
                              model_variants=synthetic_test_only_variants)
    assert (plan.state, plan.revision, plan.sets) == ("NOT_PUBLISHED", None, ())
    assert applicable_plans({"": absent, "CARRIER": absent, "CRANE": absent}, {}, vehicle_model_id="MODEL-0002",
                            model_variants=synthetic_test_only_variants) == ()


# ---------------------------------------------------------------- B. Due reuse: engines, ODOMETER, PTO, completion


async def test_f06_missing_or_ambiguous_physical_engine_is_unknown() -> None:
    w = await world()
    components = w.repo._components[VEH]
    components.append(VehicleComponent(component_id="CMP-SYN-9", vehicle_id=VEH,
                                       component_role=ComponentRole.CARRIER_ENGINE, label="synthetic second engine"))
    w.repo._components[VEH] = [c for c in components if c.component_role != ComponentRole.CRANE_ENGINE]
    v = await vdue(w)
    for key in (CARRIER_A, CRANE_A):
        assert (status(row(v, key)), row(v, key).component_id) == (
            ("UNKNOWN", None, "PHYSICAL_ENGINE_UNVERIFIED"), None)
    assert status(row(v, KM_SET))[2] == "NO_VERIFIED_ACTUAL_SET_COMPLETION"  # ODOMETER needs no engine


async def test_f07_full_set_completion_keeps_odometer_and_each_engine_independent() -> None:
    w, job = await completed_world()
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1499, ("ENGINE_HOUR", CRANE_ENG): 2600,
                             ("ODOMETER", None): 59000})
    v = await vdue(w, source=source)
    carrier, crane, km = row(v, CARRIER_A), row(v, CRANE_A), row(v, KM_SET)
    assert [status(s) for s in (carrier, crane, km)] == [("NOT_DUE", 1500.0, None), ("DUE", 2600.0, None),
                                                          ("NOT_DUE", 60000.0, None)]
    assert [(s.last_completed_meter, s.current_meter) for s in (carrier, crane, km)] == [
        (1000.0, 1499.0), (2000.0, 2600.0), (50000.0, 59000.0)]
    [submit_event] = [e for e in w.repo._pm_transitions[job] if e.action.value == "SUBMIT"]
    assert {(s.last_completed_pm_work_order_id, s.last_completed_at) for s in (carrier, crane, km)} == {
        (job, submit_event.occurred_at)}  # the accepted technician SUBMIT, not the CLOSE


async def test_f08_owner_example_600_hour_set_completed_at_650_is_due_at_1250() -> None:
    w, _ = await completed_world(crane=650, keys=(CRANE_A,))
    for current, expected in ((1249, "NOT_DUE"), (1250, "DUE")):
        crane = row(await vdue(w, source=current_source({("ENGINE_HOUR", CRANE_ENG): current})), CRANE_A)
        assert (crane.status, crane.next_due, crane.last_completed_meter) == (expected, 1250.0, 650.0)


async def test_f09_a_pto_hour_head_set_is_listed_unknown_and_no_revision_credit_carries() -> None:
    w, _ = await completed_world(keys=(CARRIER_A, CRANE_A))
    rev2 = w.rev.model_copy(update={
        "revision_id": f"PMMREV-{PLAN}-0002", "revision_number": 2, "request_id": "REQ-SYN-PTO-REV",
        "sets": tuple(s.model_copy(update={"meter_type": PmTriggerType.PTO_HOUR,
                                           "driving_component": ComponentRole.PTO})
                      if s.set_key == CRANE_A else s for s in w.rev.sets)})
    w.store.commit({"kind": "PUBLISH", "request_id": "REQ-SYN-PTO-REV", "request_fingerprint": "pto"}, revision=rev2)
    v = await vdue(w, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1100}))
    assert [p.revision_number for p in v.plans] == [2]
    crane = row(v, CRANE_A)
    assert (crane.meter_type, status(crane), crane.component_id) == ("PTO_HOUR", ("UNKNOWN", None,
                                                                                 "PM_METER_NOT_APPROVED"), None)
    carrier = row(v, CARRIER_A)  # completed under revision 1 only: no cross-revision credit
    assert (status(carrier), carrier.last_completed_meter) == (("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION"),
                                                               None)


async def test_f10_partial_not_performed_return_and_unfinished_work_never_reset_the_anchor() -> None:
    w = await world()
    report_engines(w, carrier=1000, crane=2000)
    first = await open_wo(w, [CARRIER_A, CRANE_A])
    await complete(w, first)
    w.source.items.clear()
    report_engines(w, carrier=1300, crane=2300)
    second = await open_wo(w, [CARRIER_A, CRANE_A])
    await complete(w, second, not_performed=tuple(tasks_of(w, second, CRANE_A)))  # CRANE Set NOT_PERFORMED
    third = await open_wo(w, [CARRIER_A, CRANE_A])  # unfinished: IN_PROGRESS
    await assign(w.repo, third, body(T1, T2), kind=PM)
    await start(w.svc, third)
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1350, ("ENGINE_HOUR", CRANE_ENG): 2350})
    v = await vdue(w, source=source)
    carrier, crane = row(v, CARRIER_A), row(v, CRANE_A)
    assert (status(carrier), carrier.last_completed_pm_work_order_id, carrier.last_completed_meter) == (
        ("NOT_DUE", 1800.0, None), second, 1300.0)
    assert (status(crane), crane.last_completed_pm_work_order_id, crane.last_completed_meter) == (
        ("NOT_DUE", 2600.0, None), first, 2000.0)  # partial work kept the earlier anchor
    assert w.repo._pm_work_orders[third].status == S.IN_PROGRESS


async def test_f10b_return_then_resubmit_anchors_only_the_accepted_submit() -> None:
    w = await world()
    report_engines(w, crane=2000)
    job = await open_wo(w, [CRANE_A])
    await complete(w, job, close=False)
    await w.svc.return_for_rework(job, manager(), request_id=rid(), reason="แก้ไขเอกสาร (synthetic)")
    pending = row(await vdue(w, source=current_source({("ENGINE_HOUR", CRANE_ENG): 2100})), CRANE_A)
    assert status(pending)[2] == "NO_VERIFIED_ACTUAL_SET_COMPLETION"  # RETURNed work is no completion
    w.source.items.clear()
    report_engines(w, crane=2050, ago=timedelta(seconds=30), received_ago=timedelta(seconds=10))
    await submit(w, job)
    await w.svc.close_after_review(job, manager(), request_id=rid())
    crane = row(await vdue(w, source=current_source({("ENGINE_HOUR", CRANE_ENG): 2100})), CRANE_A)
    assert (status(crane), crane.last_completed_meter) == (("NOT_DUE", 2650.0, None), 2050.0)


async def test_f11_a_newer_revision_never_inherits_an_older_completion() -> None:
    w, _ = await completed_world(keys=(CARRIER_A,))
    rev2 = await publish_rev2(w)
    v = await vdue(w, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1100}))
    carrier = row(v, CARRIER_A)
    assert ([p.revision_number for p in v.plans], carrier.revision_number, carrier.interval_value) == (
        [rev2.revision_number], 2, 550.0)
    assert (status(carrier), carrier.last_completed_meter) == (("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION"),
                                                               None)


async def test_f12_missing_stale_or_untrusted_current_meter_is_unknown_but_keeps_the_proven_completion() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    stale = FakeIotSource()
    stale.report("ENGINE_HOUR", 1600, component_id=CARRIER_ENG, vehicle_id=VEH, ago=timedelta(hours=2))
    untrusted = current_source({("ENGINE_HOUR", CARRIER_ENG): 1600})
    untrusted.items[0] = replace(untrusted.items[0], device_verified=False)
    for source in (None, stale, untrusted):
        carrier = row(await vdue(w, source=source), CARRIER_A)
        assert status(carrier) == ("UNKNOWN", None, "CURRENT_METER_UNVERIFIED")  # no invented next Due
        assert (carrier.last_completed_meter, carrier.last_completed_pm_work_order_id, carrier.current_meter) == (
            1000.0, job, None)
        assert carrier.last_completed_at is not None


async def test_f13_decreasing_counters_are_unknown() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    carrier = row(await vdue(w, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 900})), CARRIER_A)
    assert (status(carrier), carrier.last_completed_meter, carrier.current_meter) == (
        ("UNKNOWN", None, "COUNTER_DECREASE_UNRESOLVED"), 1000.0, 900.0)
    w.source.items.clear()
    report_engines(w, carrier=950)  # a later completion with a LOWER anchored meter
    later = await open_wo(w, [CARRIER_A])
    await complete(w, later)
    carrier = row(await vdue(w, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1200})), CARRIER_A)
    assert (status(carrier), carrier.last_completed_meter) == (
        ("UNKNOWN", None, "COMPLETION_METER_DECREASE_UNRESOLVED"), None)


# ---------------------------------------------------------------- C. R3 E01 read safety (fail closed, zero writes)


async def test_f14_missing_or_interrupted_journal_fails_the_read_closed_without_repair() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    journal = w.repo._pm_transitions[job]
    w.repo._pm_transitions[job] = []  # a progressed (CLOSED) header without its E01 journal
    before = state_of(w)
    with pytest.raises(ApiError) as missing:
        await vdue(w)
    assert (missing.value.status_code, missing.value.code) == (409, "PM_E01_STATE_INCONSISTENT")
    assert state_of(w) == before
    w.repo._pm_transitions[job] = journal
    wo = w.repo._pm_work_orders[job]
    w.repo._pm_work_orders[job] = wo.model_copy(update={"status": S.PENDING_REVIEW, "closed_at": None,
                                                        "closed_by": None, "closed_snapshot_id": None})
    before = state_of(w)
    with pytest.raises(ApiError) as interrupted:  # journal CLOSE not projected: never completed by a GET
        await vdue(w)
    assert (interrupted.value.status_code, interrupted.value.code) == (409, "PM_E01_TRANSITION_INCOMPLETE")
    assert state_of(w) == before and w.repo._pm_work_orders[job].status == S.PENDING_REVIEW
    assert job not in json.dumps(interrupted.value.details or {}) + interrupted.value.message


async def test_f15_forged_duplicated_or_foreign_journal_events_fail_closed() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    journal = list(w.repo._pm_transitions[job])
    for forged, issue in (
            ([*journal[:-1], journal[-1].model_copy(update={"event_id": "PME01-FORGED"})],
             "JOURNAL_PROVENANCE_INVALID"),
            ([*journal, journal[-1]], "JOURNAL_IDENTITY_DUPLICATE"),
            ([*journal[:-1], journal[-1].model_copy(update={"pm_work_order_id": "PMWO-FOREIGN"})],
             "JOURNAL_OWNER_MISMATCH"),
            ([*journal[:-1], journal[-1].model_copy(update={"test_batch_id": "TEST-OTHER-BATCH"})],
             "JOURNAL_SCOPE_MISMATCH")):
        w.repo._pm_transitions[job] = forged
        await data_invalid(w, issue)
    w.repo._pm_transitions[job] = journal
    assert row(await vdue(w), CARRIER_A).last_completed_pm_work_order_id == job  # restored: valid again


async def test_f16_foreign_close_snapshot_outcome_result_or_anchor_evidence_fails_closed() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    wo = w.repo._pm_work_orders[job]
    other = await open_wo(w, [CARRIER_A])  # a second Work Order claiming the same CLOSE capture
    w.repo._pm_work_orders[other] = w.repo._pm_work_orders[other].model_copy(
        update={"closed_snapshot_id": wo.closed_snapshot_id})
    await data_invalid(w, "CLOSE_SNAPSHOT_FOREIGN")
    w.repo._pm_work_orders[other] = w.repo._pm_work_orders[other].model_copy(update={"closed_snapshot_id": None})

    key, outcome = next((k, o) for k, o in w.repo._pm_item_outcomes.items() if o.pm_work_order_id == job)
    w.repo._pm_item_outcomes[key] = outcome.model_copy(update={"revision_id": "PMMREV-OTHER"})
    await data_invalid(w, "OUTCOME_RECORD_MISMATCH")
    w.repo._pm_item_outcomes[key] = outcome
    w.repo._pm_item_outcomes["SYN-DUPLICATE"] = outcome.model_copy(update={"pm_item_outcome_id": "SYN-DUPLICATE"})
    await data_invalid(w, "OUTCOME_ACCOUNTING_INVALID")  # the existing E01 accounting validator rejects it
    del w.repo._pm_item_outcomes["SYN-DUPLICATE"]

    results = list(w.repo._pm_work_results[job])
    w.repo._pm_work_results[job] = [*results, results[0].model_copy(update={"pm_work_result_id": "PMWR-SYN-DUP"})]
    await data_invalid(w, "OUTCOME_ACCOUNTING_INVALID")  # an unlinked second result: E01 accounting rejects it
    w.repo._pm_work_results[job] = [*results, results[0]]  # the same record twice: passes accounting, still caught
    await data_invalid(w, "RESULT_DUPLICATE")
    w.repo._pm_work_results[job] = [results[0].model_copy(update={"revision_id": "PMMREV-OTHER"}), *results[1:]]
    await data_invalid(w, "RESULT_RECORD_MISMATCH")
    w.repo._pm_work_results[job] = results

    [submit_event] = [e for e in w.repo._pm_transitions[job] if e.action.value == "SUBMIT"]
    anchor = w.repo._pm_submit_meter_anchors[submit_event.event_id]
    for forged in (replace(anchor, pm_work_order_id=other), replace(anchor, test_batch_id="TEST-OTHER-BATCH"),
                   replace(anchor, asset_id="VEH-1046"), replace(anchor, submitted_at=anchor.submitted_at
                                                                 - timedelta(seconds=1))):
        w.repo._pm_submit_meter_anchors[submit_event.event_id] = forged
        await data_invalid(w, "SUBMIT_ANCHOR_MISMATCH")
    del w.repo._pm_submit_meter_anchors[submit_event.event_id]  # absent: no IoT evidence, not corruption
    carrier = row(await vdue(w, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})), CARRIER_A)
    assert (status(carrier), carrier.last_completed_meter) == (
        ("UNKNOWN", None, "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED"), None)


async def test_f17_a_membership_whose_work_order_is_missing_foreign_or_out_of_scope_fails_closed() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    wo = w.repo._pm_work_orders[job]
    for changes, issue in (({"asset_id": "VEH-1046"}, "WORK_ORDER_RECORD_MISMATCH"),
                           ({"revision_id": "PMMREV-OTHER"}, "WORK_ORDER_RECORD_MISMATCH"),
                           ({"assignment_model": ASSIGNMENT_MODEL_LEGACY}, "WORK_ORDER_RECORD_MISMATCH")):
        w.repo._pm_work_orders[job] = wo.model_copy(update=changes)
        await data_invalid(w, issue)
    w.repo._pm_work_orders[job] = wo
    [m] = w.repo._pm_master_memberships
    w.repo._pm_master_memberships = (replace(m, pm_work_order_id="PMWO-SYN-MISSING"),)
    await data_invalid(w, "WORK_ORDER_REFERENCE_MISSING")
    w.repo._pm_master_memberships = (m,)


# ---------------------------------------------------------------- R2: membership -> Work Order scope / provenance


async def two_completions(w: World | None = None):
    """An earlier valid, qualified completion of both engine Sets, then a later one."""
    w = w or await world()
    report_engines(w, carrier=1000, crane=2000)
    first = await open_wo(w, [CARRIER_A, CRANE_A])
    await complete(w, first)
    w.source.items.clear()
    report_engines(w, carrier=1300, crane=2300)
    second = await open_wo(w, [CARRIER_A, CRANE_A])
    await complete(w, second)
    return w, first, second


def drop_set_from_scope(w: World, job: str, set_key: str) -> None:
    """Corrupt the STORED Work Order only: its scope loses an originally selected Set,
    and that Set's results and Outcomes go with it, so the remaining E01 accounting is
    internally consistent (every result linked, at least one PERFORMED)."""
    gone = set(tasks_of(w, job, set_key))
    wo = w.repo._pm_work_orders[job]
    w.repo._pm_work_orders[job] = wo.model_copy(
        update={"scope_task_ids": [t for t in wo.scope_task_ids if t not in gone]})
    w.repo._pm_work_results[job] = [r for r in w.repo._pm_work_results[job] if r.pm_task_id not in gone]
    for key in [k for k, o in w.repo._pm_item_outcomes.items() if o.pm_work_order_id == job and o.pm_task_id in gone]:
        del w.repo._pm_item_outcomes[key]


async def test_r2_01_a_work_order_scope_missing_a_membership_set_task_fails_closed() -> None:
    w, first, second = await two_completions()
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1350, ("ENGINE_HOUR", CRANE_ENG): 2350})
    crane = row(await vdue(w, source=source), CRANE_A)
    assert (status(crane), crane.last_completed_pm_work_order_id) == (("NOT_DUE", 2900.0, None), second)
    drop_set_from_scope(w, second, CRANE_A)
    # Call-path evidence: ordinary E01 accounting does NOT catch this corruption ...
    svc = due_svc(w, source)
    accounted = await svc._require_complete_accounting(await w.repo.get_pm_work_order(second))
    assert accounted and not {o.pm_task_id for o in accounted} & set(tasks_of(w, second, CRANE_A))
    # ... so without a membership -> scope check, DUE-02A would read it as a partial
    # Set (NOT_COMPLETE) and silently fall back to the FIRST completion (2000 -> 2600).
    await data_invalid(w, "MEMBERSHIP_SCOPE_TASK_MISSING", svc=svc)
    with pytest.raises(ApiError) as failed:
        await vdue(w, svc=svc)
    text = json.dumps(failed.value.details) + failed.value.message
    assert first not in text and second not in text and VEH not in text  # no protected identifiers
    page_error = None
    try:
        await svc.list_fleet_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), _params())
    except ApiError as exc:
        page_error = exc
    assert page_error is not None and page_error.details == {"issues": {"MEMBERSHIP_SCOPE_TASK_MISSING": 1}}


async def test_r2_02_a_legitimately_added_scope_task_is_kept_and_never_refused() -> None:
    w = await world()
    report_engines(w, carrier=1000, crane=2000)
    job = await open_wo(w, [CARRIER_A])
    [crane_task] = tasks_of(w, (await open_wo(w, [CRANE_A])), CRANE_A)  # a real task of the same revision
    await w.svc.add_scope_task(job, crane_task, "เพิ่มงานที่ใกล้ครบกำหนด (synthetic)", "SYN-MANAGER")
    assert crane_task in w.repo._pm_work_orders[job].scope_task_ids  # scope is a strict SUPERSET of membership
    await complete(w, job)
    v = await vdue(w, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1100}))
    carrier, crane = row(v, CARRIER_A), row(v, CRANE_A)
    assert (status(carrier), carrier.last_completed_pm_work_order_id) == (("NOT_DUE", 1500.0, None), job)
    # The added task never turns this Work Order into a CRANE Set completion (not its membership).
    assert (status(crane), crane.last_completed_pm_work_order_id) == (
        ("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION"), None)


async def test_r2_03_conflicting_membership_plan_revision_or_set_provenance_fails_closed() -> None:
    w, job = await completed_world(keys=(CARRIER_A, CRANE_A))
    [m] = w.repo._pm_master_memberships
    crane_def = next(x for x in m.sets if x.set_key == CRANE_A)
    for forged, issue in (
            (replace(m, plan_code=PLAN_B), "MEMBERSHIP_PROVENANCE_MISMATCH"),
            (replace(m, pm_plan_id="PMMP-SYN-OTHER"), "MEMBERSHIP_PROVENANCE_MISMATCH"),
            (replace(m, master_revision_number=7), "MEMBERSHIP_PROVENANCE_MISMATCH"),
            (replace(m, sets=tuple(replace(x, interval_value=999.0) if x is crane_def else x for x in m.sets)),
             "MEMBERSHIP_SET_MISMATCH"),
            (replace(m, sets=tuple(replace(x, items=x.items[:-1] + (("SYN!9", x.items[-1][1]),))
                                   if x is crane_def else x for x in m.sets)), "MEMBERSHIP_SET_MISMATCH")):
        w.repo._pm_master_memberships = (forged,)
        await data_invalid(w, issue)
    w.repo._pm_master_memberships = (m, replace(m, request_id="REQ-SYN-DUP"))  # two memberships, one Work Order
    await data_invalid(w, "MEMBERSHIP_DUPLICATE")
    w.repo._pm_master_memberships = (m,)
    assert row(await vdue(w), CARRIER_A).last_completed_pm_work_order_id == job  # restored: valid again


async def test_r2_04_other_assets_models_and_revisions_never_contaminate_a_set() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    [m] = w.repo._pm_master_memberships
    await assign_plan(w, vehicle="VEH-1048")  # MODEL-0003 -> SYN-M2 Sets only
    w.repo._pm_master_memberships = (m, replace(m, asset_id="VEH-1048", request_id="REQ-SYN-OTHER-ASSET",
                                                pm_work_order_id="PMWO-SYN-ELSEWHERE"))
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    page = await due_svc(w, source).list_fleet_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), _params())
    other = next(r for r in page.items if r.vehicle_id == "VEH-1048")
    assert [s.set_key for s in other.sets] == ["SYN-M2|NOT_SEPARATED_IN_PLAN|A"]  # never VEH-1047's Set
    assert {s.last_completed_pm_work_order_id for s in other.sets} == {None}
    own = next(r for r in page.items if r.vehicle_id == VEH)
    assert row(own, CARRIER_A).last_completed_pm_work_order_id == job
    # A vehicle whose registered model changed: its new variant's Sets apply, the old
    # model's memberships are not selected (lineage), and nothing is corrupted.
    w.repo._vehicles[VEH] = w.repo._vehicles[VEH].model_copy(update={"model_id": "MODEL-0003"})
    v = await vdue(w, source=source)
    assert [s.set_key for s in v.sets] == ["SYN-M2|NOT_SEPARATED_IN_PLAN|A"]
    assert status(v.sets[0]) == ("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION")
    # A membership of an OLDER revision is history, not corruption: plain UNKNOWN.
    w.repo._vehicles[VEH] = w.repo._vehicles[VEH].model_copy(update={"model_id": "MODEL-0002"})
    await publish_rev2(w)
    carrier = row(await vdue(w, source=source), CARRIER_A)
    assert status(carrier) == ("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION")


# ---------------------------------------------------------------- D. authorization and isolation


async def test_f18_can_view_reads_derived_due_only_and_everyone_else_is_refused_before_any_read() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    svc = due_svc(w)
    for context in (None, manager(), ctx("SYN-NOBODY")):  # no context; can_manage_pm alone; no capability
        w.repo.calls.clear()
        with pytest.raises(Exception) as denied:  # ApiError or the shared capability HTTPException
            await svc.read_vehicle_pm_due(context, VEH)
        assert denied.value.status_code == 403 and w.repo.calls == []
        with pytest.raises(Exception) as denied_fleet:
            await svc.list_fleet_pm_due(context, _params())
        assert denied_fleet.value.status_code == 403 and w.repo.calls == []
    viewer = ctx("SYN-VIEWER", authz.CAN_VIEW)
    assert row(await svc.read_vehicle_pm_due(viewer, VEH), CARRIER_A).last_completed_pm_work_order_id == job
    # ... but it gains NO raw Outcome / journal read and the per-Set method keeps its contract.
    for raw in (svc.list_item_outcomes, svc.list_work_order_history):
        with pytest.raises(Exception) as raw_denied:
            await raw(job, viewer)
        assert raw_denied.value.status_code == 403
    with pytest.raises(Exception) as per_set:
        await svc.evaluate_master_set_due(viewer, asset_id=VEH, master_revision_id=w.rev.revision_id,
                                          set_key=CARRIER_A)
    assert per_set.value.status_code == 403


async def test_f19_test_real_and_other_batch_scopes_are_isolated() -> None:
    w, job = await completed_world(keys=(CARRIER_A,))
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    assert status(row(await vdue(w, source=source), CARRIER_A))[0] == "NOT_DUE"
    # RT1 (G1): this TEST batch's Master is invisible to another batch and to REAL. It is
    # not Master data there at all (no Plan, assignment or Set, not even as UNKNOWN).
    for other in (due_svc(w, source, batch="TEST-OTHER-BATCH"), due_svc(w, source, context="REAL")):
        foreign = await vdue(w, svc=other)
        assert (foreign.state, foreign.assignments, foreign.plans, foreign.sets) == ("MASTER_NOT_ACTIVE", (), (), ())
        assert [(v.state, v.sets) for v in (await other.list_fleet_pm_due(
            ctx("SYN-VIEWER", authz.CAN_VIEW), _params())).items] == [("MASTER_NOT_ACTIVE", ())] * 3
    with pytest.raises(ApiError) as unconfigured:
        await vdue(w, svc=due_svc(w, source, context=None))
    assert unconfigured.value.status_code == 503
    # a membership in this scope whose job is in another batch: record integrity, whole read closed, no ids
    w.repo._pm_work_orders[job] = w.repo._pm_work_orders[job].model_copy(update={"test_batch_id": "TEST-OTHER"})
    with pytest.raises(ApiError) as foreign:
        await vdue(w, source=source)
    assert (foreign.value.status_code, foreign.value.details) == (500, {"issues": {"WORK_ORDER_SCOPE_MISMATCH": 1}})
    assert job not in json.dumps(foreign.value.details or {}) + foreign.value.message


async def test_f20_the_due_reads_make_zero_writes() -> None:
    w, _ = await completed_world()
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100, ("ENGINE_HOUR", CRANE_ENG): 2700})
    before = state_of(w)
    w.repo.calls.clear()
    svc = due_svc(w, source)

    async def never(*_a, **_k):
        raise AssertionError("a GET must never use the projecting E01 status")

    svc._current_status = never
    svc._project = never
    await svc.read_vehicle_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), VEH)
    await svc.list_fleet_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), _params())
    assert w.repo.calls and not [c for c in w.repo.calls if c.startswith(WRITES)]
    assert state_of(w) == before


async def test_f21_reads_are_batched_per_request_not_per_set() -> None:
    w, _ = await completed_world()
    await assign_plan(w, vehicle="VEH-1048")
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    w.repo.calls.clear()
    page = await due_svc(w, source).list_fleet_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), _params())
    assert [r.state for r in page.items] == ["NO_ASSIGNED_PLAN", "AVAILABLE", "AVAILABLE"]
    assert w.repo.calls.count("list_pm_master_memberships") == 1
    assert w.repo.calls.count("list_vehicle_components") == 2  # once per vehicle with Sets
    assert w.repo.calls.count("get_pm_task_revision") == 1  # one catalogue per revision
    assert source.calls == 2  # one IoT read per vehicle with Sets, not per Set


async def test_f22_an_adapter_without_bridge_storage_refuses_explicitly(monkeypatch) -> None:
    w = await world()

    async def unsupported(**_):
        raise RepositoryFeatureNotImplementedError("pm_master_bridge")

    monkeypatch.setattr(w.repo, "list_pm_master_memberships", unsupported)
    with pytest.raises(RepositoryFeatureNotImplementedError):  # never a quiet UNKNOWN
        await vdue(w)
    response = await _get(w, f"{FLEET}/{VEH}", due_svc(w))
    assert (response.status_code, response.json()["error"]["code"]) == (501, "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE")


# ---------------------------------------------------------------- F. HTTP: pagination, filters, firewall


def _params(page=1, page_size=50):
    from app.domain.common import PageParams
    return PageParams(page=page, page_size=page_size)


async def _get(w: World, path: str, svc: PmService, caps=VIEW):
    """HTTP GET with the TEST-ONLY injected service (the application wiring has no Master)."""
    from httpx import ASGITransport, AsyncClient

    from app.context import RequestContext
    from app.dependencies import get_current_context, get_pm_service, get_repository, reset_dependency_cache
    from app.main import create_app

    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: w.repo
    app.dependency_overrides[get_pm_service] = lambda: svc
    app.dependency_overrides[get_current_context] = lambda: RequestContext(
        request_id=str(uuid.uuid4()), user_id="SYN-VIEWER", is_dev_auth=True, capabilities=caps)
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            return await client.get(path)
    finally:
        reset_dependency_cache()


async def test_f23_http_pagination_and_vehicle_filters_page_vehicles_before_evaluation() -> None:
    w, _ = await completed_world()
    svc = due_svc(w, current_source({("ENGINE_HOUR", CARRIER_ENG): 1100}))
    first = (await _get(w, f"{FLEET}?page=1&page_size=2", svc)).json()
    second = (await _get(w, f"{FLEET}?page=2&page_size=2", svc)).json()
    assert (first["total_items"], second["total_items"]) == (3, 3)
    assert [v["vehicle_id"] for v in first["items"] + second["items"]] == ["VEH-1046", "VEH-1047", "VEH-1048"]
    beyond = (await _get(w, f"{FLEET}?page=9&page_size=2", svc)).json()
    assert (beyond["items"], beyond["total_items"]) == ([], 3)  # an empty page, not an empty fleet
    for query, expected in (("model_id=MODEL-0002", ["VEH-1047"]), ("status=MAINTENANCE", ["VEH-1047"]),
                            ("q=TC-14", ["VEH-1048"]), ("model_id=MODEL-NONE", [])):
        body = (await _get(w, f"{FLEET}?{query}", svc)).json()
        assert [v["vehicle_id"] for v in body["items"]] == expected and body["total_items"] == len(expected)
    for bad in ("page_size=201", "page=0", "status=NOPE"):
        assert (await _get(w, f"{FLEET}?{bad}", svc)).status_code == 422
    one = (await _get(w, f"{FLEET}/{VEH}", svc)).json()
    carrier = next(s for s in one["sets"] if s["set_key"] == CARRIER_A)
    assert (carrier["status"], carrier["next_due"], carrier["last_completed_meter"]) == ("NOT_DUE", 1500.0, 1000.0)
    assert not {"submit_event_id", "source_submit_event_id", "outcomes", "transitions", "journal"} & set(carrier)
    assert (await _get(w, f"{FLEET}/VEH-NOPE", svc)).status_code == 404
    assert (await _get(w, FLEET, svc, caps=frozenset({authz.CAN_MANAGE_PM}))).status_code == 403


async def test_f24_application_wiring_reads_master_not_active_for_the_whole_fleet() -> None:
    from tests.test_v2_waiting_assignment_batch_r2f_h4_b3 import REAL

    w, _ = await completed_world()
    response = await get_as(FLEET, w.repo, VIEW, settings=REAL)  # the real get_pm_service wiring
    body = response.json()
    assert response.status_code == 200 and body["total_items"] == 3
    assert {v["state"] for v in body["items"]} == {"MASTER_NOT_ACTIVE"} and all(v["sets"] == [] for v in body["items"])


def test_f25_production_composition_never_loads_or_activates_the_master() -> None:
    """In a fresh interpreter: the application's own wiring serves the PM Due route
    with MASTER_NOT_ACTIVE and neither the B1 Master nor its runtime bridge module is
    ever imported (the dormant D1 firewall holds in production)."""
    script = r"""
import asyncio, json, sys, uuid
from httpx import ASGITransport, AsyncClient
from app.context import RequestContext
from app.dependencies import get_current_context
from app.main import create_app

async def main():
    app = create_app()  # the application's own settings and wiring (Mock, synthetic TEST)
    app.dependency_overrides[get_current_context] = lambda: RequestContext(
        request_id=str(uuid.uuid4()), user_id="SYN-VIEWER", is_dev_auth=True, capabilities=frozenset({"can_view"}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        fleet = await client.get("/api/v1/pm/due/vehicles")
        one = await client.get("/api/v1/pm/due/vehicles/VEH-1047")
    print(json.dumps({"fleet": fleet.status_code, "states": sorted({v["state"] for v in fleet.json()["items"]}),
                      "one": one.json().get("state"),
                      "loaded": sorted(m for m in sys.modules if m.startswith("app.domain.pm_master"))}))

asyncio.run(main())
"""
    out = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, capture_output=True, text=True, check=True)
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result == {"fleet": 200, "states": ["MASTER_NOT_ACTIVE"], "one": "MASTER_NOT_ACTIVE", "loaded": []}


# ---------------------------------------------------------------- RT1 (G1 / G2): only a bound Master is read


async def test_rt1_f26_an_unbound_foreign_or_other_repository_master_is_master_not_active() -> None:
    w, _ = await completed_world(keys=(CARRIER_A,))
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    assert row(await vdue(w, source=source), CARRIER_A).status == "NOT_DUE"  # the bound Master, same batch
    before = state_of(w)
    for label, master, _ in unbound_or_foreign_masters(w):
        svc = PmService(w.repo, MeterService(w.repo, iot_meter_source=source),
                        assignment_cutover=cut()).with_master_reads(master, synthetic_test_only_variants)
        w.repo.calls.clear()
        one = await vdue(w, svc=svc)
        assert (one.state, one.assignments, one.plans, one.sets) == ("MASTER_NOT_ACTIVE", (), (), ()), label
        page = await svc.list_fleet_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), _params())
        assert {(v.state, v.sets) for v in page.items} == {("MASTER_NOT_ACTIVE", ())}, label
        assert "list_pm_master_memberships" not in w.repo.calls, label  # no Master-sourced record is read
    assert state_of(w) == before


async def test_rt1_f27_an_unconfigured_server_scope_fails_closed_before_any_master_read() -> None:
    w, _ = await completed_world(keys=(CARRIER_A,))
    w.repo.calls.clear()
    with pytest.raises(ApiError) as unconfigured:
        await vdue(w, svc=due_svc(w, context=None))
    assert unconfigured.value.status_code == 503
    assert "list_pm_master_memberships" not in w.repo.calls


# ---------------------------------------------------------------- RT4-B: one Master snapshot per Due read (D-2)
# Two vehicles of one model are assigned to one Plan through the real RT2 Master (its own
# evidence-backed approvals, no explicit variant seam). A Master write is injected, once,
# INSIDE a real awaited repository call of an in-flight Due read: the first await of the
# read (`list_pm_master_memberships`) or a per-vehicle read made between the two vehicles
# (`list_vehicle_components`). The in-flight page must equal the page read just before the
# write (ONE Master state for every vehicle); the next request must see the write.
# Deterministic: a one-shot wrapper, no sleeps. Master-only, in-process Mock consistency:
# repository records are not frozen (PostgreSQL R11 needs one read-only snapshot).

VEH_B = "VEH-SYN-3047"  # a second synthetic vehicle of VEH's model (MODEL-0002)
BOUNDARIES = ("list_pm_master_memberships", "list_vehicle_components")


async def two_vehicle_world(extra=()):
    from tests.test_pm_master_model_variant_approval import (
        ASSIGNER,
        approve,
        variant_world,
    )

    w, reg = await variant_world(extra=extra)  # VEH assigned to PLAN
    await approve(w, reg)  # (MODEL-0002, PLAN) -> SYN-M1, an evidenced RT2 approval
    w.repo._vehicles[VEH_B] = w.repo._vehicles[VEH].model_copy(update={"vehicle_id": VEH_B,
                                                                       "machine_no": "SYN-3047"})
    await w.master.set_assignment(ASSIGNER, vehicle_id=VEH_B, plan_code=PLAN, expected_version=0,
                                  reason="กำหนดแผนทดสอบ (synthetic)", request_id=rid())
    return w, reg


def master_svc(w: World) -> PmService:
    return due_svc(w, variants=None)  # the bound Master's own approvals (RT2 default)


async def fleet_page(svc: PmService) -> dict:
    page = await svc.list_fleet_pm_due(ctx("SYN-VIEWER", authz.CAN_VIEW), _params(), model_id="MODEL-0002")
    rows = {v.vehicle_id: v for v in page.items}
    assert {VEH, VEH_B} <= set(rows)
    return rows


class hook_once:
    """Run `action` once, inside the FIRST call of the repository coroutine `name`."""

    def __init__(self, repo, name: str, action) -> None:
        self.repo, self.name, self.action, self.fired = repo, name, action, 0

    def __enter__(self):
        real = getattr(self.repo, self.name)

        async def wrapper(*args, **kwargs):
            if not self.fired:
                self.fired += 1
                await self.action()
            return await real(*args, **kwargs)

        object.__setattr__(self.repo, self.name, wrapper)
        return self

    def __exit__(self, *exc) -> None:
        object.__delattr__(self.repo, self.name)


async def one_master_epoch(w: World, boundary: str, write) -> tuple[dict, dict]:
    """(page before the write == the in-flight page, the next page)."""
    svc = master_svc(w)
    before = await fleet_page(svc)
    with hook_once(w.repo, boundary, write) as hook:
        in_flight = await fleet_page(svc)
    assert hook.fired == 1  # the write really landed inside the in-flight read
    assert in_flight == before  # every vehicle evaluated against the SAME pre-write Master state
    return before, await fleet_page(svc)


def plan_view(v) -> list[tuple]:
    return [(p.plan_code, p.state, p.revision_number, p.model_variant) for p in v.plans]


@pytest.mark.parametrize("boundary", BOUNDARIES)
async def test_rt4b_01_an_approval_revoked_mid_read_never_mixes_into_the_page(boundary) -> None:
    from tests.test_pm_master_model_variant_approval import revoke

    w, _ = await two_vehicle_world()
    before, after = await one_master_epoch(w, boundary, lambda: revoke(w))
    for vehicle in (VEH, VEH_B):
        assert plan_view(before[vehicle]) == [(PLAN, "RESOLVED", 1, "SYN-M1")] and before[vehicle].sets
        assert (plan_view(after[vehicle]), after[vehicle].sets) == ([(PLAN, "MODEL_VARIANT_UNVERIFIED", 1, None)], ())


@pytest.mark.parametrize("boundary", BOUNDARIES)
async def test_rt4b_02_an_assignment_removed_mid_read_keeps_the_page_assignment_snapshot(boundary) -> None:
    from tests.test_pm_master_model_variant_approval import ASSIGNER

    w, _ = await two_vehicle_world()

    async def unassign():
        await w.master.set_assignment(ASSIGNER, vehicle_id=VEH_B, plan_code=None, expected_version=1,
                                      reason="ยกเลิกแผน (synthetic)", request_id=rid())

    before, after = await one_master_epoch(w, boundary, unassign)
    assert before[VEH_B].state == "AVAILABLE" and after[VEH_B].state == "NO_ASSIGNED_PLAN"
    whole = next(a for a in after[VEH_B].assignments if a.assembly == "")  # the vehicle-wide record
    assert (whole.source, whole.plan_code) == ("EXPLICIT_NONE", None)
    assert after[VEH] == before[VEH]  # the untouched vehicle is unchanged


@pytest.mark.parametrize("boundary", BOUNDARIES)
async def test_rt4b_03_an_assignment_moved_to_another_plan_mid_read_never_mixes(boundary) -> None:
    from tests.test_pm_master_b1_mock import publish, resolve_all
    from tests.test_pm_master_model_variant_approval import ASSIGNER, EDITOR

    w, reg = await two_vehicle_world()
    await resolve_all(w.master, reg, PLAN_B, context=EDITOR, skip={r.entry_id for r in w.store.resolutions})
    await publish(w.master, reg, 0, plan=PLAN_B, context=EDITOR)  # Plan B exists before the read

    async def reassign():
        await w.master.set_assignment(ASSIGNER, vehicle_id=VEH_B, plan_code=PLAN_B, expected_version=1,
                                      reason="ย้ายแผน (synthetic)", request_id=rid())

    before, after = await one_master_epoch(w, boundary, reassign)
    assert [p.plan_code for p in before[VEH_B].plans] == [PLAN]
    assert [p.plan_code for p in after[VEH_B].plans] == [PLAN_B]
    assert after[VEH] == before[VEH]


@pytest.mark.parametrize("boundary", BOUNDARIES)
async def test_rt4b_04_a_revision_published_mid_read_keeps_the_captured_revision(boundary) -> None:
    import copy

    from tests.test_pm_master_b1_mock import publish, register, resolve_all
    from tests.test_pm_master_model_variant_approval import EDITOR, registered_workbook

    w, _ = await two_vehicle_world()
    workbook = copy.deepcopy(registered_workbook())
    workbook["source_pm_cycles"][0]["interval_value"] = "550"
    newer = await register(w.master, workbook, context=EDITOR)  # a registered preview changes no Due
    await resolve_all(w.master, newer, context=EDITOR)
    before, after = await one_master_epoch(w, boundary, lambda: publish(w.master, newer, 1, context=EDITOR))
    for vehicle in (VEH, VEH_B):
        assert {s.revision_number for s in before[vehicle].sets} == {1}
        assert {s.revision_number for s in after[vehicle].sets} == {2}
        assert all(s.last_completed_pm_work_order_id is None for s in after[vehicle].sets)  # no carried credit


@pytest.mark.parametrize("boundary", BOUNDARIES)
async def test_rt4b_05_a_variant_corrected_mid_read_never_mixes_variant_states(boundary) -> None:
    from tests.test_pm_master_b1_mock import DOC_M3, register, smap
    from tests.test_pm_master_model_variant_approval import (
        EDITOR,
        SINGLE,
        approve,
        registered_workbook,
        row_of,
    )

    w, _ = await two_vehicle_world(extra=(smap("VEH-SYN-NONE", SINGLE, model="SYN-M3", low=DOC_M3),))
    w.repo._vehicles["VEH-SYN-2047"] = w.repo._vehicles[VEH].model_copy(update={"vehicle_id": "VEH-SYN-2047",
                                                                               "machine_no": "SYN-2047"})
    corrected = registered_workbook(smap("VEH-SYN-2047", SINGLE, model="SYN-M3", low=DOC_M3))
    corrected["vehicle_pm_mapping"] = [r for r in corrected["vehicle_pm_mapping"] if r["vehicle_id"] != VEH]
    newer = await register(w.master, corrected, context=EDITOR)  # registered before the read; changes no Due
    before, after = await one_master_epoch(
        w, boundary, lambda: approve(w, newer, variant="SYN-M3", rows=[row_of(newer, "VEH-SYN-2047")], version=1))
    for vehicle in (VEH, VEH_B):
        assert [p.model_variant for p in before[vehicle].plans] == ["SYN-M1"]
        assert [p.model_variant for p in after[vehicle].plans] == ["SYN-M3"]
        assert {s.model_variant for s in after[vehicle].sets} == {"SYN-M3"}


async def test_rt4b_06_the_vehicle_route_and_the_fleet_page_agree_for_one_master_state() -> None:
    w, _ = await two_vehicle_world()
    svc = master_svc(w)
    page = await fleet_page(svc)
    for vehicle in (VEH, VEH_B):
        assert await vdue(w, svc=svc, vehicle=vehicle) == page[vehicle]


async def test_rt4b_07_snapshot_and_due_reads_write_nothing() -> None:
    w, _ = await two_vehicle_world()
    svc = master_svc(w)

    def everything():
        s = w.store
        return (state_of(w), dict(s.revisions), s.variant_approvals, s.previews, s.resolutions)

    before = everything()
    await fleet_page(svc)
    for vehicle in (VEH, VEH_B):
        await vdue(w, svc=svc, vehicle=vehicle)
    assert everything() == before  # no Work Order, membership, revision, approval, assignment, snapshot,
    # anchor, journal or audit event


def spy_master(master) -> list[str]:
    """Record any Master read on `master` (the Due read must make none when it is not bound)."""
    reads: list[str] = []
    for name in ("resolve_plan", "effective_revision", "model_variant_source"):
        def read(*args, _name=name, **kwargs):
            reads.append(_name)
            raise AssertionError(f"Master read {_name} on an inactive Master")
        object.__setattr__(master, name, read)
    return reads


async def test_rt4b_08_an_inactive_or_foreign_master_is_never_read() -> None:
    w, _ = await two_vehicle_world()
    no_master = due_svc(w, master=False)
    assert {v.state for v in (await fleet_page(no_master)).values()} == {"MASTER_NOT_ACTIVE"}
    for label, master, _ in unbound_or_foreign_masters(w):
        reads = spy_master(master)
        svc = PmService(w.repo, MeterService(w.repo, iot_meter_source=NO_IOT_METER_SOURCE),
                        assignment_cutover=cut()).with_master_reads(master, None)
        page = await fleet_page(svc)
        assert {(v.state, v.assignments, v.plans, v.sets) for v in page.values()} == {
            ("MASTER_NOT_ACTIVE", (), (), ())}, label
        assert reads == [], label  # nothing of the Master was read, so nothing can be disclosed
    # The bound Master in another server batch: also inactive, also unread.
    reads = spy_master(w.master)
    other = PmService(w.repo, MeterService(w.repo, iot_meter_source=NO_IOT_METER_SOURCE),
                      assignment_cutover=cut(batch="SYN-OTHER-BATCH")).with_master_reads(w.master, None)
    assert {v.state for v in (await fleet_page(other)).values()} == {"MASTER_NOT_ACTIVE"} and reads == []


async def test_rt4b_09_an_unrelated_master_write_mid_read_changes_nothing_for_these_vehicles() -> None:
    from tests.test_pm_master_model_variant_approval import (
        ASSIGNER,
        M2,
        VEH_M3,
        approve,
        row_of,
    )

    w, reg = await two_vehicle_world()

    async def unrelated():  # another model's approval and another vehicle's assignment
        await approve(w, reg, model=M2, variant="SYN-M2", rows=[row_of(reg, VEH_M3)])
        await w.master.set_assignment(ASSIGNER, vehicle_id=VEH_M3, plan_code=PLAN, expected_version=0,
                                      reason="กำหนดแผนคันอื่น (synthetic)", request_id=rid())

    before, after = await one_master_epoch(w, "list_vehicle_components", unrelated)
    assert (after[VEH], after[VEH_B]) == (before[VEH], before[VEH_B])


async def test_rt4b_10_authorization_is_checked_before_any_master_read() -> None:
    from fastapi import HTTPException

    w, _ = await two_vehicle_world()
    reads = spy_master(w.master)
    svc = master_svc(w)
    for context in (ctx("SYN-NO-CAPABILITY"), ctx("SYN-PM-MANAGER", authz.CAN_MANAGE_PM), None):
        with pytest.raises((ApiError, HTTPException)) as refused:
            await svc.list_fleet_pm_due(context, _params(), model_id="MODEL-0002")
        assert refused.value.status_code == 403
        with pytest.raises((ApiError, HTTPException)):
            await svc.read_vehicle_pm_due(context, VEH)
    assert reads == []  # refused before the snapshot: nothing of the Master was read
