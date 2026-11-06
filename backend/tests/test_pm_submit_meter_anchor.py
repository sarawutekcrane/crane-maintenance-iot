"""R4 / TASK-010: technician SUBMIT IoT meter anchor (DEC-R4-TASK010-PM-TECH-SUBMIT-ANCHOR-003,
DEC-R4-TASK010-IOT-METER-001), end to end on the Mock repository with a FAKE IoT source.

The real E01 service drives the lifecycle; the Due side reads the repository only
(`read_work_order_evidence`) and evaluates with DUE-02A / DUE-01. Every IoT reading
here is an invented test value: this proves the contract, not real ESP32 telemetry,
device authentication or PostgreSQL."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.asset import AssetType
from app.domain.meter_service import MeterService
from app.domain.pm import PmItemContractDisposition as Disposition
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.pm_due_evidence import (
    CurrentMeter,
    FrozenSet,
    MappedItem,
    evaluate_set_due,
)
from app.domain.pm_meter_anchor import (
    NO_IOT_METER_SOURCE,
    IotMeterObservation,
    PmSubmitMeterAnchor,
    read_work_order_evidence,
)
from app.domain.pm_service import PmService
from app.errors import ApiError
from app.repositories.base import Repository
from tests.pm_e01_support import (
    NOT_PERFORMED,
    U1,
    U2,
    ctx,
    current_set_id,
    manager,
    repo_with,
    rid,
    save,
    scope_of,
    start,
    v2_job,
)
from tests.test_technician_assignment_batch_r2f_h1 import cut

VEHICLE, ENGINE = "VEH-1046", "CMP-0001"  # Mock seed: CMP-0001 CARRIER_ENGINE, CMP-0002 PTO
WINDOW = timedelta(hours=1)
WRITES = ("create_", "append_", "set_", "close_", "update_", "assign_", "add_", "approve_", "delete_")


@dataclass
class FakeIotSource:
    """Invented IoT observations; filtering is entirely the production selector's."""

    items: list[IotMeterObservation] = field(default_factory=list)
    max_observation_age: timedelta | None = WINDOW
    calls: int = 0

    async def observations(self, vehicle_id: str, *, not_after: datetime):
        self.calls += 1
        return tuple(self.items)

    def report(self, counter_type: str, value, *, component_id: str | None = None, vehicle_id: str = VEHICLE,
               ago=timedelta(minutes=2), received_ago=timedelta(minutes=1), **changes) -> None:
        now = datetime.now(UTC)
        self.items.append(replace(IotMeterObservation(
            vehicle_id, component_id, counter_type, value, now - ago, now - received_ago, "TIME_SYNCED",
            "SYN-ESP32-1", f"SYN-DEV-EVT-{len(self.items) + 1}", True), **changes))


def service(repo, source=None) -> PmService:
    return PmService(repo, MeterService(repo, iot_meter_source=source or NO_IOT_METER_SOURCE),
                     assignment_cutover=cut())


def engine_set(tasks, **changes) -> FrozenSet:
    f = FrozenSet(set_ref="SYN|PMP-0001|CARRIER|SET-A", asset_type="VEHICLE", asset_id=VEHICLE,
                  pm_plan_id="PMP-0001", revision_id="PMREV-0001",
                  items=tuple(MappedItem(f"SYN-SRC!{t}", t, True) for t in tasks),
                  meter_type="ENGINE_HOUR", interval=600, interval_unit="HOUR",
                  driving_component_role="CARRIER_ENGINE", component_id=ENGINE,
                  source_verified=True, lineage_verified=True, component_verified=True)
    return replace(f, **changes)


def km_set(tasks) -> FrozenSet:
    return engine_set(tasks, set_ref="SYN|PMP-0001|CARRIER|SET-G", meter_type="ODOMETER", interval=5000,
                      interval_unit="KM", driving_component_role="VEHICLE", component_id=None)


async def evidence(repo, job):
    """Outcomes come through the approved, authorized E01 read (no projection)."""
    outcomes = await service(repo).list_item_outcomes(job, manager())
    return await read_work_order_evidence(repo, job, outcomes=outcomes, v2_scope_verified=True,
                                          data_scope_verified=True)


async def due(repo, fs, job, current_value, *, counter="ENGINE_HOUR", component=ENGINE, extra=()):
    wo = await evidence(repo, job)
    return evaluate_set_due(fs, (*extra, wo), CurrentMeter(counter, component, current_value, True))


async def submit(svc, repo, job, request_id=None):
    return await svc.submit_for_review(job, ctx(U1), request_id=request_id or rid(),
                                       expected_set_id=await current_set_id(repo, job))


async def performed_and_submitted(repo, svc, *, not_performed=(), extra_tasks=0, request_id=None):
    job = await v2_job(repo, extra_tasks=extra_tasks)
    await start(svc, job)
    tasks = await scope_of(repo, job)
    for task in [t for t in tasks if t not in not_performed] + [t for t in tasks if t in not_performed]:
        await save(svc, job, task, NOT_PERFORMED if task in not_performed else Disposition.PERFORMED)
    await submit(svc, repo, job, request_id)
    return job, tasks


def submit_events(repo, job):
    return [e for e in repo._pm_transitions[job] if e.action.value == "SUBMIT"]


# ---------------------------------------------------------------- 1, 2 qualified SUBMIT anchor; CLOSE never replaces it


async def test_t01_verified_reading_at_submit_accepted_by_close_is_the_anchor() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    source.report("ODOMETER", 18200)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    [event] = submit_events(repo, job)
    anchor = repo._pm_submit_meter_anchors[event.event_id]
    assert anchor.submitted_at == event.occurred_at
    assert {(r.counter_type, r.component_id, r.value) for r in anchor.readings} == {
        ("ENGINE_HOUR", ENGINE, 650.0), ("ODOMETER", None, 18200.0)}  # PTO component never anchored
    await svc.close_after_review(job, manager(), request_id=rid())
    decision = await due(repo, engine_set(tasks), job, 1249)
    assert (decision.due.status, decision.due.next_due) == ("NOT_DUE", 1250)
    assert (decision.source_pm_work_order_id, decision.source_submit_event_id) == (job, event.event_id)


async def test_t02_a_later_close_with_a_different_meter_never_replaces_the_submit_anchor() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    [event] = submit_events(repo, job)
    before = repo._pm_submit_meter_anchors[event.event_id]
    source.report("ENGINE_HOUR", 700, component_id=ENGINE, ago=timedelta(0), received_ago=timedelta(0))
    closed = await svc.close_after_review(job, manager(), request_id=rid())
    assert closed.work_order.closed_snapshot_id  # the CLOSE machine-state capture is unchanged ...
    assert repo._pm_submit_meter_anchors == {event.event_id: before}  # ... and is not an anchor
    decision = await due(repo, engine_set(tasks), job, 1249)
    assert decision.due.next_due == 1250  # 650 + 600, never 700 + 600


# ---------------------------------------------------------------- 3, 13 RETURN / resubmission / unaccepted


async def test_t03_returned_then_resubmitted_only_the_accepted_later_submit_counts() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 640, component_id=ENGINE)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    await svc.return_for_rework(job, manager(), request_id=rid(), reason="แก้ไขเอกสาร (synthetic)")
    source.items.clear()
    source.report("ENGINE_HOUR", 655, component_id=ENGINE, ago=timedelta(seconds=30), received_ago=timedelta(seconds=10))
    await submit(svc, repo, job)
    first, second = submit_events(repo, job)
    anchors = repo._pm_submit_meter_anchors
    assert anchors[first.event_id].readings[0].value == 640.0  # kept, immutable, never accepted
    assert anchors[second.event_id].readings[0].value == 655.0
    await svc.close_after_review(job, manager(), request_id=rid())
    decision = await due(repo, engine_set(tasks), job, 1000)
    assert (decision.source_submit_event_id, decision.due.next_due) == (second.event_id, 1255)


async def test_t13_a_pending_review_work_order_gets_no_completion_credit() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    assert submit_events(repo, job) and repo._pm_submit_meter_anchors  # bound at SUBMIT ...
    decision = await due(repo, engine_set(tasks), job, 1300)
    assert (decision.due.status, decision.due.reason) == ("UNKNOWN", "NO_VERIFIED_ACTUAL_SET_COMPLETION")


# ---------------------------------------------------------------- 4, 5, 15 replay, crash recovery, restart


async def test_t04_a_repeated_submit_request_id_never_creates_a_second_anchor() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    request_id = rid()
    job, _ = await performed_and_submitted(repo, svc, request_id=request_id)
    calls = source.calls
    source.report("ENGINE_HOUR", 999, component_id=ENGINE, ago=timedelta(0), received_ago=timedelta(0))
    await submit(svc, repo, job, request_id)  # identical re-send
    assert len(submit_events(repo, job)) == 1 and len(repo._pm_submit_meter_anchors) == 1
    assert source.calls == calls  # the existing anchor is never re-evaluated or overwritten
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert anchor.readings[0].value == 650.0


async def test_t05_an_interrupted_anchor_write_is_completed_by_the_replay_exactly_once() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job = await v2_job(repo)
    await start(svc, job)
    tasks = await scope_of(repo, job)
    for task in tasks:
        await save(svc, job, task)
    request_id = rid()
    repo.fail = {"create_pm_submit_meter_anchor": RuntimeError("synthetic lost write")}
    with pytest.raises(ApiError) as caught:  # honest state, never a bare 500 that reads as "not submitted"
        await submit(svc, repo, job, request_id)
    assert (caught.value.status_code, caught.value.code) == (503, "PM_SUBMIT_METER_ANCHOR_PENDING")
    assert caught.value.details["submission_recorded"] is True and caught.value.details["status"] == "PENDING_REVIEW"
    repo.fail = {}
    assert repo._pm_work_orders[job].status == S.PENDING_REVIEW and not repo._pm_submit_meter_anchors
    # A reading uploaded AFTER the SUBMIT (offline backlog) must not change the replay's choice.
    source.report("ENGINE_HOUR", 651, component_id=ENGINE, ago=timedelta(minutes=3), received_ago=timedelta(0))
    await submit(svc, repo, job, request_id)
    [event] = submit_events(repo, job)
    assert [r.value for r in repo._pm_submit_meter_anchors[event.event_id].readings] == [650.0]
    await submit(svc, repo, job, request_id)
    assert len(repo._pm_submit_meter_anchors) == 1


async def test_t15_restart_gives_the_same_decision_and_the_anchor_is_write_once() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    await svc.close_after_review(job, manager(), request_id=rid())
    first = await due(repo, engine_set(tasks), job, 1249)
    service(repo)  # a "restarted" service graph without any IoT source
    assert await due(repo, engine_set(tasks), job, 1249) == first
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert await repo.create_pm_submit_meter_anchor(anchor) == (anchor, True)  # identical replay
    with pytest.raises(ValueError, match="PM_SUBMIT_ANCHOR_CONFLICT"):
        await repo.create_pm_submit_meter_anchor(replace(anchor, readings=()))
    assert repo._pm_submit_meter_anchors[anchor.submit_event_id] == anchor


# ---------------------------------------------------------------- 6, 7 several Sets, partial Set


async def test_t06_two_fully_completed_sets_in_one_work_order_each_get_their_own_meter() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    source.report("ODOMETER", 18200)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc, extra_tasks=2)
    await svc.close_after_review(job, manager(), request_id=rid())
    engine = await due(repo, engine_set(tasks[:3]), job, 1250)
    km = await due(repo, km_set(tasks[3:]), job, 23100, counter="ODOMETER", component=None)
    assert (engine.due.status, engine.due.next_due) == ("DUE", 1250)
    assert (km.due.status, km.due.next_due) == ("NOT_DUE", 23200)


async def test_t07_a_partial_set_keeps_its_outstanding_and_never_resets_its_cycle() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    source.report("ODOMETER", 18200)
    svc = service(repo, source)
    first, tasks = await performed_and_submitted(repo, svc, extra_tasks=2)  # Set A = 3 tasks, Set G = 2 tasks
    await svc.close_after_review(first, manager(), request_id=rid())
    source.items.clear()
    source.report("ENGINE_HOUR", 900, component_id=ENGINE)
    source.report("ODOMETER", 21000)
    partial, tasks2 = await performed_and_submitted(repo, svc, not_performed=(tasks[4],))
    assert tasks2 == tasks
    await svc.close_after_review(partial, manager(), request_id=rid())  # a partial CLOSE is allowed
    assert [i.pm_task_id for i in repo._pm_outstanding.values() if i.pm_work_order_id == partial] == [tasks[4]]
    history = (await evidence(repo, first),)
    km = await due(repo, km_set(tasks[3:]), partial, 21100, counter="ODOMETER", component=None, extra=history)
    assert (km.source_pm_work_order_id, km.due.next_due) == (first, 23200)  # partial Set: cycle NOT reset
    engine = await due(repo, engine_set(tasks[:3]), partial, 1000, extra=history)
    assert (engine.source_pm_work_order_id, engine.due.next_due) == (partial, 1500)  # complete Set re-anchors


# ---------------------------------------------------------------- 8-12 invalid IoT evidence


@pytest.mark.parametrize("changes", [
    {"device_verified": False},  # wrong / unregistered device
    {"time_quality": "TIME_ESTIMATED"}, {"time_quality": "TIME_NOT_SYNCED"},
    {"observed_at": None},  # missing source observation time
    {"ago": -timedelta(minutes=5)},  # source time later than the SUBMIT
    {"ago": timedelta(hours=2)},  # stale: outside the source's freshness window
    {"vehicle_id": "VEH-OTHER"}, {"component_id": "CMP-9999"},
    {"counter_type": "PTO_HOUR", "component_id": "CMP-0002"},  # PTO never drives existing PM
    {"value": -1}, {"value": None}, {"device_id": ""},
])
async def test_t08_invalid_missing_stale_or_untrusted_observations_give_unknown(changes) -> None:
    repo, source = repo_with(), FakeIotSource()
    kwargs = {"component_id": ENGINE, **changes}
    counter = kwargs.pop("counter_type", "ENGINE_HOUR")
    value = kwargs.pop("value", 650)
    observed_none = kwargs.pop("observed_at", "x") is None
    source.report(counter, value, **kwargs)
    if observed_none:
        source.items[-1] = replace(source.items[-1], observed_at=None)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    await svc.close_after_review(job, manager(), request_id=rid())
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert not [r for r in anchor.readings if r.counter_type == "ENGINE_HOUR"]
    decision = await due(repo, engine_set(tasks), job, 1300)
    assert (decision.due.status, decision.due.reason) == ("UNKNOWN", "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")


async def test_t09_wrong_dimension_odometer_never_satisfies_an_engine_hour_set() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ODOMETER", 18200)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    await svc.close_after_review(job, manager(), request_id=rid())
    decision = await due(repo, engine_set(tasks), job, 1300)
    assert decision.due.reason == "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED"


async def test_t10_a_source_without_a_freshness_window_cannot_vouch_for_any_reading() -> None:
    repo, source = repo_with(), FakeIotSource(max_observation_age=None)
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    await svc.close_after_review(job, manager(), request_id=rid())
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert anchor.readings == () and anchor.max_observation_age == timedelta(0)
    assert (await due(repo, engine_set(tasks), job, 1300)).due.status == "UNKNOWN"


# ---------------------------------------------------------------- 14 header/journal disagreement, no read-side writes


async def test_t14_header_journal_disagreement_is_unknown_and_reading_writes_nothing() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    repo.fail = {"set_pm_work_order_status": RuntimeError("synthetic lost projection")}
    with pytest.raises(RuntimeError):
        await svc.close_after_review(job, manager(), request_id=rid())
    repo.fail = {}
    assert repo._pm_work_orders[job].status == S.PENDING_REVIEW  # journal says CLOSED
    snapshots, anchors = dict(repo._meter_snapshots), dict(repo._pm_submit_meter_anchors)
    repo.calls.clear()
    decision = await due(repo, engine_set(tasks), job, 1300)
    assert (decision.due.status, decision.due.reason) == ("UNKNOWN", "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")
    assert repo.calls and not [c for c in repo.calls if c.startswith(WRITES)]  # reads only
    assert repo._pm_work_orders[job].status == S.PENDING_REVIEW  # never projected by the Due read
    assert (repo._meter_snapshots, repo._pm_submit_meter_anchors) == (snapshots, anchors)


# ---------------------------------------------------------------- 15 TEST/REAL isolation, 16 default runtime / adapters


async def test_t15b_the_anchor_carries_its_work_orders_scope_and_a_foreign_scope_is_refused() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job, _ = await performed_and_submitted(repo, svc)
    wo = repo._pm_work_orders[job]
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert (anchor.is_test_data, anchor.test_batch_id) == (wo.is_test_data, wo.test_batch_id) != ("", "")
    other = PmSubmitMeterAnchor(**{**anchor.__dict__, "submit_event_id": anchor.submit_event_id,
                                   "is_test_data": "FALSE", "test_batch_id": ""})
    repo._pm_submit_meter_anchors.clear()
    with pytest.raises(ValueError, match="PM_SUBMIT_ANCHOR_SOURCE_INVALID"):
        await repo.create_pm_submit_meter_anchor(other)


async def test_t16_without_an_iot_source_or_anchor_storage_submit_works_and_due_stays_unknown() -> None:
    repo = repo_with()
    svc = service(repo)  # runtime default: NO_IOT_METER_SOURCE
    job, tasks = await performed_and_submitted(repo, svc)
    await svc.close_after_review(job, manager(), request_id=rid())
    assert repo._pm_submit_meter_anchors == {}
    assert (await due(repo, engine_set(tasks), job, 1300)).due.status == "UNKNOWN"
    from app.repositories.google_sheets.repository import GoogleSheetsRepository
    assert GoogleSheetsRepository.create_pm_submit_meter_anchor is Repository.create_pm_submit_meter_anchor

    class NoAnchorStorage(type(repo)):
        create_pm_submit_meter_anchor = Repository.create_pm_submit_meter_anchor
        get_pm_submit_meter_anchor = Repository.get_pm_submit_meter_anchor

    repo2, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    repo2.__class__ = NoAnchorStorage
    job2, _ = await performed_and_submitted(repo2, service(repo2, source))
    assert repo2._pm_work_orders[job2].status == S.PENDING_REVIEW and source.calls == 0


async def test_t16b_submit_authorization_and_errors_are_unchanged() -> None:
    repo, source = repo_with(), FakeIotSource()
    svc = service(repo, source)
    job = await v2_job(repo)
    await start(svc, job)
    with pytest.raises(ApiError) as caught:  # nothing saved yet: SUBMIT refused (existing 422) before any binding
        await submit(svc, repo, job)
    assert caught.value.status_code == 422 and repo._pm_submit_meter_anchors == {} and source.calls == 0
    for task in await scope_of(repo, job):
        await save(svc, job, task)
    with pytest.raises(Exception) as caught:  # a COLLABORATOR is never the submitting PRIMARY
        await svc.submit_for_review(job, ctx(U2), request_id=rid(), expected_set_id=await current_set_id(repo, job))
    assert getattr(caught.value, "status_code", None) == 403
    assert repo._pm_submit_meter_anchors == {} and source.calls == 0


# ---------------------------------------------------------------- production-risk review (A: IoT availability, B: partial failures)


async def _ready_to_submit(repo, svc):
    job = await v2_job(repo)
    await start(svc, job)
    for task in await scope_of(repo, job):
        await save(svc, job, task)
    return job


async def test_r_a3_a_source_with_no_valid_observation_binds_an_empty_immutable_anchor() -> None:
    repo, source = repo_with(), FakeIotSource()
    svc = service(repo, source)
    job, tasks = await performed_and_submitted(repo, svc)
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert anchor.readings == ()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)  # arrives later: never re-binds the evaluated SUBMIT
    await submit(svc, repo, job, submit_events(repo, job)[0].request_id)
    assert repo._pm_submit_meter_anchors == {anchor.submit_event_id: anchor}
    await svc.close_after_review(job, manager(), request_id=rid())
    assert (await due(repo, engine_set(tasks), job, 1300)).due.status == "UNKNOWN"


async def test_r_a2_no_iot_source_never_falls_back_to_current_counter_or_manual_readings() -> None:
    from app.domain.meter import CounterType, CurrentCounterReading
    repo = repo_with()
    repo._current_counters[VEHICLE] = [CurrentCounterReading(component_id=ENGINE, counter_type=CounterType.ENGINE_HOUR,
                                                             value=650)]
    svc = service(repo)  # runtime default: no IoT source
    await svc._meter.create_snapshot(asset_type=AssetType.VEHICLE, asset_id=VEHICLE, readings=[],
                                     recorded_by="dev-user")  # a manual snapshot
    job, tasks = await performed_and_submitted(repo, svc)
    await svc.close_after_review(job, manager(), request_id=rid())
    assert repo._pm_submit_meter_anchors == {}
    decision = await due(repo, engine_set(tasks), job, 1300)
    assert (decision.due.status, decision.due.reason) == ("UNKNOWN", "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")


async def test_r_a4_iot_source_exception_reports_the_recorded_submission_and_recovers_on_retry() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job = await _ready_to_submit(repo, svc)
    working = source.observations

    async def outage(*args, **kwargs):
        raise ConnectionError("synthetic IoT outage")

    source.observations = outage
    request_id = rid()
    with pytest.raises(ApiError) as caught:
        await submit(svc, repo, job, request_id)
    assert (caught.value.status_code, caught.value.code) == (503, "PM_SUBMIT_METER_ANCHOR_PENDING")
    assert caught.value.details["failure"] == "ConnectionError" and "outage" not in caught.value.message
    assert repo._pm_work_orders[job].status == S.PENDING_REVIEW and len(submit_events(repo, job)) == 1
    assert repo._pm_submit_meter_anchors == {}  # nothing fabricated
    source.observations = working
    done = await submit(svc, repo, job, request_id)  # same request id: a replay that only completes the anchor
    assert done.work_order.status == S.PENDING_REVIEW and len(submit_events(repo, job)) == 1
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert [r.value for r in anchor.readings] == [650.0]


async def test_r_b4_restart_between_journal_and_anchor_is_recovered_by_a_fresh_service() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    job = await _ready_to_submit(repo, service(repo, source))
    request_id = rid()
    repo.fail = {"create_pm_submit_meter_anchor": RuntimeError("process killed")}
    with pytest.raises(ApiError):
        await submit(service(repo, source), repo, job, request_id)
    repo.fail = {}
    restarted = service(repo, source)  # a new service graph on the preserved repository state
    await submit(restarted, repo, job, request_id)
    assert len(submit_events(repo, job)) == 1 and len(repo._pm_submit_meter_anchors) == 1


async def test_r_b5_concurrent_duplicate_and_competing_submits_never_duplicate_or_reassign() -> None:
    from tests.test_r4_pm_wf_operation_serialization import yielding
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job = await _ready_to_submit(repo, svc)
    yielding(repo)  # Sheets-like interleaving inside repository calls
    set_id = await current_set_id(repo, job)
    same = rid()
    outcomes = await asyncio.gather(
        svc.submit_for_review(job, ctx(U1), request_id=same, expected_set_id=set_id),
        svc.submit_for_review(job, ctx(U1), request_id=same, expected_set_id=set_id),
        svc.submit_for_review(job, ctx(U1), request_id=rid(), expected_set_id=set_id),
        return_exceptions=True)
    assert len(submit_events(repo, job)) == 1 and len(repo._pm_submit_meter_anchors) == 1
    errors = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(errors) == 1 and isinstance(errors[0], ApiError) and errors[0].status_code == 409  # competing id
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert anchor.submit_event_id == submit_events(repo, job)[0].event_id and anchor.readings[0].value == 650.0


async def test_r_b6_a_permanently_failing_anchor_store_never_claims_evidence() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job = await _ready_to_submit(repo, svc)
    tasks = await scope_of(repo, job)
    request_id = rid()
    repo.fail = {"create_pm_submit_meter_anchor": RuntimeError("storage down")}
    for _ in range(3):  # every retry reports the same true state
        with pytest.raises(ApiError) as caught:
            await submit(svc, repo, job, request_id)
        assert caught.value.code == "PM_SUBMIT_METER_ANCHOR_PENDING"
    assert len(submit_events(repo, job)) == 1  # retries never add lifecycle events
    await svc.close_after_review(job, manager(), request_id=rid())  # acceptance is not blocked ...
    repo.fail = {}
    decision = await due(repo, engine_set(tasks), job, 1300)  # ... but no completion meter is claimed
    assert (decision.due.status, decision.due.reason) == ("UNKNOWN", "COMPLETE_WORK_ORDER_EVIDENCE_UNVERIFIED")
    assert repo._pm_submit_meter_anchors == {}


async def test_r_b2_a_replay_after_return_reports_the_actual_current_status() -> None:
    repo, source = repo_with(), FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=ENGINE)
    svc = service(repo, source)
    job = await _ready_to_submit(repo, svc)
    request_id = rid()
    repo.fail = {"create_pm_submit_meter_anchor": RuntimeError("synthetic")}
    with pytest.raises(ApiError):
        await submit(svc, repo, job, request_id)
    await svc.return_for_rework(job, manager(), request_id=rid(), reason="synthetic")
    with pytest.raises(ApiError) as caught:  # still failing: the report names the CURRENT status
        await submit(svc, repo, job, request_id)
    assert caught.value.details["status"] == "IN_PROGRESS"
    repo.fail = {}
    await submit(svc, repo, job, request_id)  # the rejected SUBMIT's own anchor completes (never accepted)
    [anchor] = repo._pm_submit_meter_anchors.values()
    assert anchor.submit_event_id == submit_events(repo, job)[0].event_id
