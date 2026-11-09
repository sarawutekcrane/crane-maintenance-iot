"""R4 / TASK-010 D1 (DEC-R4-TASK010-B1-E01-BRIDGE-D1-20261106): the DORMANT B1 PM
Master -> E01 runtime -> per-Set Due bridge, end to end on the Mock repository.

Every Master row is the SYNTHETIC source-shaped B1 fixture, published and assigned
only through the test-local `synthetic_test_only_authorizer` (OPEN-005 stays closed
for the application). Every IoT reading is an invented FAKE observation
(DEC-IOT-SIMULATION-20261106): this proves the contract, not ESP32 telemetry, device
authentication, Google Sheets or PostgreSQL behaviour."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import pytest

from app.domain import authz
from app.domain.asset import AssetType
from app.domain.meter import CounterType, CurrentCounterReading
from app.domain.meter_service import MeterService
from app.domain.pm import PmTriggerType
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.pm_due_evidence import CurrentMeter, evaluate_set_due
from app.domain.pm_master import (
    MasterDataScope,
    MockVehicleResolver,
    PmMasterMockStore,
    PmMasterService,
    master_revision_id,
)
from app.domain.pm_master_runtime import (
    build_catalogue,
    build_membership,
    frozen_set,
    runtime_task_id,
)
from app.domain.pm_meter_anchor import NO_IOT_METER_SOURCE
from app.domain.pm_service import PmService
from app.domain.technician_assignment import PM
from app.domain.vehicle import VehicleComponent
from app.domain.vehicle_model import ComponentRole
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryFeatureNotImplementedError
from tests.pm_e01_support import (
    NOT_PERFORMED,
    PERFORMED,
    T1,
    T2,
    U1,
    ctx,
    current_set_id,
    manager,
    repo_with,
    rid,
    save,
    start,
)
from tests.test_pm_master_b1_mock import (
    CARRIER_A,
    CRANE_A,
    KM_SET,
    M2_A,
    M7_A,
    PLAN,
    PLAN_B,
    TEST_PM_MASTER_ASSIGNER,
    TEST_PM_MASTER_EDITOR,
    persona_test_only_authorizer,
    publish,
    published,
    register,
    resolve_all,
    synthetic_test_only_authorizer,
    with_cycle_value,
)
from tests.test_pm_master_b1_mock import (
    ctx as master_ctx,
)
from tests.test_pm_submit_meter_anchor import WRITES, FakeIotSource
from tests.test_technician_assignment_batch_r2f_h1 import BATCH, assign, body, cut

VEH = "VEH-1047"  # Mock seed: CMP-0003 CARRIER_ENGINE, CMP-0004 CRANE_ENGINE, CMP-0005 PTO
CARRIER_ENG, CRANE_ENG, PTO = "CMP-0003", "CMP-0004", "CMP-0005"
BACKEND = Path(__file__).resolve().parents[1]
# RT1 (G1): the synthetic Master is bound to the same TEST batch as the server (`cut()`).
TEST_SCOPE = MasterDataScope.test(BATCH)


# TEST ONLY (like B1's `synthetic_test_only_authorizer`): SYNTHETIC approved OPEN-016
# associations (model_id, Master plan_code) -> variant. NOT an application mapping: the
# application default (`no_proven_model_variant`) proves nothing and refuses.
SYNTHETIC_MODEL_VARIANTS = {("MODEL-0002", PLAN): {"SYN-M1"}, ("MODEL-0003", PLAN): {"SYN-M2"}}


def synthetic_test_only_variants(model_id: str, plan_code: str) -> frozenset[str]:
    return frozenset(SYNTHETIC_MODEL_VARIANTS.get((model_id, plan_code), ()))


def opener(*extra: str):
    return manager(authz.CAN_VIEW, *extra)


@dataclass
class World:
    repo: object
    store: PmMasterMockStore
    master: PmMasterService
    rev: object
    svc: PmService
    source: FakeIotSource


def pm(repo, source=None, **cutover) -> PmService:
    return PmService(repo, MeterService(repo, iot_meter_source=source or NO_IOT_METER_SOURCE),
                     assignment_cutover=cut(**cutover))


async def world(*, assign_vehicle: bool = True) -> World:
    repo, source = repo_with(), FakeIotSource()
    # RT1 (G2): assignments are resolved against the SAME repository object the runtime uses.
    store, master, _, rev = await published(PmMasterMockStore(data_scope=TEST_SCOPE),
                                            resolver=MockVehicleResolver(repo))
    if assign_vehicle:
        await master.set_assignment(master_ctx(), vehicle_id=VEH, assembly="", plan_code=PLAN, expected_version=0,
                                    reason="กำหนดแผนทดสอบ (synthetic)", request_id=rid())
    return World(repo, store, master, rev, pm(repo, source), source)


OPENER = object()


async def open_wo(w: World, keys, *, request_id=None, revision=None, svc=None, context=OPENER, **kw) -> str:
    detail = await (svc or w.svc).open_master_work_order(
        w.master, opener() if context is OPENER else context, asset_id=kw.pop("asset_id", VEH),
        plan_code=kw.pop("plan_code", PLAN),
        revision_number=(revision or w.rev).revision_number, selected_set_keys=list(keys),
        request_id=request_id or rid(), model_variants=kw.pop("model_variants", synthetic_test_only_variants), **kw)
    return detail.work_order.pm_work_order_id


def membership(w: World, job: str):
    [m] = [m for m in w.repo._pm_master_memberships if m.pm_work_order_id == job]
    return m


def tasks_of(w: World, job: str, set_key: str) -> list[str]:
    return [t for s in membership(w, job).sets if s.set_key == set_key for _, t in s.items]


def report_engines(w: World, carrier=None, crane=None, odometer=None, **kw) -> None:
    for counter, component, value in (("ENGINE_HOUR", CARRIER_ENG, carrier), ("ENGINE_HOUR", CRANE_ENG, crane),
                                      ("ODOMETER", None, odometer)):
        if value is not None:
            w.source.report(counter, value, component_id=component, vehicle_id=VEH, **kw)


async def submit(w: World, job: str):
    return await w.svc.submit_for_review(job, ctx(U1), request_id=rid(),
                                         expected_set_id=await current_set_id(w.repo, job))


async def complete(w: World, job: str, *, not_performed=(), close=True) -> None:
    await assign(w.repo, job, body(T1, T2), kind=PM)
    await start(w.svc, job)
    scope = list(w.repo._pm_work_orders[job].scope_task_ids)
    for task in [t for t in scope if t not in not_performed] + [t for t in scope if t in not_performed]:
        await save(w.svc, job, task, NOT_PERFORMED if task in not_performed else PERFORMED)
    await submit(w, job)
    if close:
        await w.svc.close_after_review(job, manager(), request_id=rid())


def current_source(readings: dict) -> FakeIotSource:
    """A fresh fake source for the Due read: only the CURRENT observations."""
    source = FakeIotSource()
    for (counter, component), value in readings.items():
        source.report(counter, value, component_id=component, vehicle_id=VEH, ago=timedelta(seconds=5),
                      received_ago=timedelta(seconds=1))
    return source


async def due(w: World, set_key: str, *, revision=None, source=None, svc=None):
    svc = svc or pm(w.repo, source or NO_IOT_METER_SOURCE)
    return await svc.evaluate_master_set_due(opener(), asset_id=VEH, master_revision_id=(revision or w.rev).revision_id,
                                             set_key=set_key)


def outcome(decision):
    return decision.due.status, decision.due.next_due, decision.due.reason


async def publish_rev2(w: World, interval="550"):
    reg = await register(w.master, with_cycle_value(0, interval))
    await resolve_all(w.master, reg)
    return (await publish(w.master, reg, 1)).revision


# ---------------------------------------------------------------- 1 single Set, 2 multiple Sets, catalogue identity


async def test_01_one_frozen_set_opens_one_e01_work_order_with_its_complete_item_list() -> None:
    w = await world()
    job = await open_wo(w, [CARRIER_A])
    wo, m = w.repo._pm_work_orders[job], membership(w, job)
    master_set = next(s for s in w.rev.sets if s.set_key == CARRIER_A)
    expected = [runtime_task_id(w.rev.revision_id, CARRIER_A, i.item_key) for i in master_set.items]
    assert wo.revision_id == m.master_revision_id == w.rev.revision_id  # the exact immutable Master revision
    assert wo.pm_plan_id == m.pm_plan_id and (m.plan_code, m.master_revision_number) == (PLAN, 1)
    assert wo.scope_task_ids == expected == m.task_ids  # every Item of the Set, in Master order
    assert wo.assignment_model == "TECHNICIAN_V2" and wo.opened_snapshot_id and wo.status == S.OPEN
    [frozen] = m.sets
    assert (frozen.set_key, frozen.model_variant, frozen.section, frozen.meter_type, frozen.interval_value,
            frozen.interval_unit, frozen.driving_component_role) == (
        CARRIER_A, "SYN-M1", "CARRIER", "ENGINE_HOUR", 500.0, "HOUR", "CARRIER_ENGINE")
    assert [k for k, _ in frozen.items] == [i.item_key for i in master_set.items]
    catalogue = await w.repo.get_pm_task_revision(wo.pm_plan_id, wo.revision_id)
    assert {t.group for t in catalogue.tasks} == {s.set_key for s in w.rev.sets}  # every Set of the revision
    by_id = {t.pm_task_id: t for t in catalogue.tasks}
    assert [by_id[t].description for t in expected] == [i.task_text for i in master_set.items]
    assert all((by_id[t].trigger_type.value, by_id[t].interval_value, by_id[t].interval_unit) ==
               ("ENGINE_HOUR", 500.0, "HOUR") for t in expected)


def test_01b_a_shared_source_item_gets_one_task_per_set_never_shared_credit() -> None:
    async def run():
        _, _, _, rev = await published(PmMasterMockStore(data_scope=TEST_SCOPE))  # RT3-A: catalogues need a scope
        return build_catalogue(rev), rev
    catalogue, rev = asyncio.run(run())
    shared = "SYN-DOC-A2!5"  # the same source row is an Item of M2 Set A and of M7 Set A
    tasks = {t.group: t.pm_task_id for t in catalogue.tasks if t.group in (M2_A, M7_A)}
    assert tasks == {M2_A: runtime_task_id(rev.revision_id, M2_A, shared),
                     M7_A: runtime_task_id(rev.revision_id, M7_A, shared)} and len(set(tasks.values())) == 2
    assert build_catalogue(rev) == catalogue  # deterministic


async def test_02_05_06_16_18_multiple_sets_keep_independent_hour_km_and_engine_due() -> None:
    w = await world()
    report_engines(w, carrier=1000, crane=2000, odometer=50000)
    job = await open_wo(w, [CARRIER_A, CRANE_A, KM_SET])
    m = membership(w, job)
    assert [s.set_key for s in m.sets] == sorted([CARRIER_A, CRANE_A, KM_SET])
    assert w.repo._pm_work_orders[job].scope_task_ids == m.task_ids and len(m.task_ids) == 4
    await complete(w, job)  # every Item PERFORMED, technician SUBMIT, reviewer CLOSE
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1499, ("ENGINE_HOUR", CRANE_ENG): 2600,
                               ("ODOMETER", None): 59000})
    carrier, crane, km = [await due(w, k, source=source) for k in (CARRIER_A, CRANE_A, KM_SET)]
    assert outcome(carrier) == ("NOT_DUE", 1500.0, None)  # 1000 + 500 HOUR on the CARRIER engine
    assert outcome(crane) == ("DUE", 2600.0, None)        # 2000 + 600 HOUR on the CRANE engine
    assert outcome(km) == ("NOT_DUE", 60000.0, None)      # 50000 + 10000 KM, vehicle level
    [submit_event] = [e for e in w.repo._pm_transitions[job] if e.action.value == "SUBMIT"]
    assert {(d.source_pm_work_order_id, d.source_submit_event_id) for d in (carrier, crane, km)} == {
        (job, submit_event.event_id)}  # the accepted SUBMIT anchors every Set; CLOSE only accepted it


# ---------------------------------------------------------------- 3, 4 full vs partial Set


async def test_03_04_a_partial_set_keeps_its_earlier_anchor_and_its_outstanding_item() -> None:
    w = await world()
    report_engines(w, carrier=1000, crane=2000)
    first = await open_wo(w, [CARRIER_A, CRANE_A])
    await complete(w, first)
    w.source.items.clear()
    report_engines(w, carrier=1300, crane=2300)
    second = await open_wo(w, [CARRIER_A, CRANE_A])
    crane_tasks = tasks_of(w, second, CRANE_A)
    await complete(w, second, not_performed=tuple(crane_tasks))
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1350, ("ENGINE_HOUR", CRANE_ENG): 2350})
    carrier, crane = await due(w, CARRIER_A, source=source), await due(w, CRANE_A, source=source)
    assert (outcome(carrier), carrier.source_pm_work_order_id) == (("NOT_DUE", 1800.0, None), second)
    assert (outcome(crane), crane.source_pm_work_order_id) == (("NOT_DUE", 2600.0, None), first)  # not reset
    outstanding = await w.svc.list_outstanding_items(second, manager())
    assert [o.item.pm_task_id for o in outstanding] == crane_tasks  # E01 Outstanding preserved unchanged
    only_partial = await world()
    report_engines(only_partial, crane=2000)
    job = await open_wo(only_partial, [CRANE_A, CARRIER_A])
    await complete(only_partial, job, not_performed=tuple(tasks_of(only_partial, job, CRANE_A)))
    decision = await due(only_partial, CRANE_A, source=source)
    assert outcome(decision) == ("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION")


# ---------------------------------------------------------------- 7 physical component resolution


async def test_07_missing_or_ambiguous_physical_engine_is_unknown() -> None:
    w = await world()
    report_engines(w, carrier=1000, crane=2000)
    job = await open_wo(w, [CARRIER_A, CRANE_A])
    await complete(w, job)
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100, ("ENGINE_HOUR", CRANE_ENG): 2100})
    assert outcome(await due(w, CARRIER_A, source=source))[0] == "NOT_DUE"
    components = w.repo._components[VEH]
    components.append(VehicleComponent(component_id="CMP-SYN-9", vehicle_id=VEH,
                                       component_role=ComponentRole.CARRIER_ENGINE, label="synthetic second engine"))
    assert outcome(await due(w, CARRIER_A, source=source)) == ("UNKNOWN", None, "PHYSICAL_ENGINE_UNVERIFIED")
    w.repo._components[VEH] = [c for c in components if c.component_role != ComponentRole.CRANE_ENGINE]
    assert outcome(await due(w, CRANE_A, source=source)) == ("UNKNOWN", None, "PHYSICAL_ENGINE_UNVERIFIED")


# ---------------------------------------------------------------- 8 a new Master revision never rewrites a Work Order


async def test_08_a_new_master_revision_never_rewrites_or_inherits_completion() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A])
    await complete(w, job)
    before_wo = w.repo._pm_work_orders[job].model_dump()
    before_membership = membership(w, job)
    before_catalogue = (await w.repo.get_pm_task_revision(before_membership.pm_plan_id, w.rev.revision_id)).model_dump()
    rev2 = await publish_rev2(w)  # CARRIER A interval 500 -> 550 (the Items are RETAINED in B1 lineage)
    job2 = await open_wo(w, [CARRIER_A], revision=rev2)
    assert w.repo._pm_work_orders[job].model_dump() == before_wo and membership(w, job) == before_membership
    assert (await w.repo.get_pm_task_revision(before_membership.pm_plan_id, w.rev.revision_id)).model_dump() == \
        before_catalogue
    assert w.repo._pm_work_orders[job2].revision_id == rev2.revision_id != w.rev.revision_id
    assert not set(tasks_of(w, job2, CARRIER_A)) & set(tasks_of(w, job, CARRIER_A))  # revision-bound tasks
    assert membership(w, job2).sets[0].interval_value == 550.0
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    assert outcome(await due(w, CARRIER_A, source=source)) == ("NOT_DUE", 1500.0, None)  # rev 1 unchanged
    assert outcome(await due(w, CARRIER_A, revision=rev2, source=source)) == (
        "UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION")  # no cross-revision credit (D2 not decided)


# ---------------------------------------------------------------- 9, 10 wrong / duplicate / conflicting mapping


async def test_09_wrong_set_revision_or_unassigned_vehicle_is_refused_with_no_write() -> None:
    w = await world()
    for keys, kw, code in (([CARRIER_A, "SYN-M1|CARRIER|NOPE"], {}, "VALIDATION_ERROR"),
                           ([CARRIER_A], {"revision": w.rev.model_copy(update={"revision_number": 9})}, "PM_MASTER_REVISION_NOT_FOUND"),
                           ([CARRIER_A], {"asset_id": "VEH-1046"}, "PM_MASTER_PLAN_NOT_ASSIGNED"),
                           ([], {}, "PM_MASTER_MAPPING_INVALID")):
        with pytest.raises(ApiError) as refused:
            await open_wo(w, keys, **kw)
        assert refused.value.code == code
    assert (w.repo._pm_work_orders, w.repo._pm_master_memberships, w.repo._meter_snapshots) == ({}, (), {})


async def test_09b_tampered_membership_or_catalogue_makes_due_unknown() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A])
    await complete(w, job)
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    good = membership(w, job)
    wrong_item = replace(good.sets[0], items=((good.sets[0].items[0][0], good.sets[0].items[1][1]),
                                              good.sets[0].items[1]))
    for tampered in (replace(good, sets=(wrong_item,)),
                     replace(good, sets=(replace(good.sets[0], items=good.sets[0].items[:1]),)),
                     replace(good, sets=(replace(good.sets[0], interval_value=5.0),))):
        w.repo._pm_master_memberships = (tampered,)
        assert outcome(await due(w, CARRIER_A, source=source)) == (
            "UNKNOWN", None, "FROZEN_SET_ITEM_MAPPING_UNVERIFIED")
    w.repo._pm_master_memberships = (good,)
    assert outcome(await due(w, CARRIER_A, source=source))[0] == "NOT_DUE"
    tasks = w.repo._pm_tasks[w.rev.revision_id]
    tasks[0] = tasks[0].model_copy(update={"interval_value": 50.0})
    assert outcome(await due(w, CARRIER_A, source=source)) == ("UNKNOWN", None, "FROZEN_SET_ITEM_MAPPING_UNVERIFIED")


async def test_10_duplicate_or_conflicting_mappings_are_refused() -> None:
    w = await world()
    for keys, code in (([CARRIER_A, CARRIER_A], "PM_MASTER_MAPPING_INVALID"),
                       ([CARRIER_A, M2_A], "PM_MASTER_MODEL_VARIANT_UNVERIFIED")):
        with pytest.raises(ApiError) as refused:
            await open_wo(w, keys)
        assert refused.value.code == code
    snapshot = w.master.freeze_selection(master_ctx(), PLAN, [CARRIER_A], revision_number=1)
    item = snapshot.sets[0].items[0]
    duplicated = snapshot.model_copy(update={"sets": (snapshot.sets[0].model_copy(update={"items": (item, item)}),)})
    with pytest.raises(ValueError, match="PM_MASTER_MAPPING_INVALID"):
        build_membership(duplicated, asset_id=VEH, vehicle_model_id="MODEL-0002", request_id="r", fingerprint="f",
                         scope={"is_test_data": "TRUE", "test_batch_id": BATCH})
    mixed = w.master.freeze_selection(master_ctx(), PLAN, [CARRIER_A, M2_A], revision_number=1)
    with pytest.raises(ValueError, match="PM_MASTER_MIXED_MODEL_VARIANT"):
        build_membership(mixed, asset_id=VEH, vehicle_model_id="MODEL-0002", request_id="r", fingerprint="f",
                         scope={"is_test_data": "TRUE", "test_batch_id": BATCH})
    # A different catalogue already stored under the same revision id is never overwritten.
    catalogue = build_catalogue(w.rev)
    w.repo._pm_task_revisions[w.rev.revision_id] = catalogue.revision
    w.repo._pm_tasks[w.rev.revision_id] = [catalogue.tasks[0].model_copy(update={"description": "อื่น"}),
                                           *catalogue.tasks[1:]]
    with pytest.raises(ApiError) as conflict:
        await open_wo(w, [CARRIER_A])
    assert (conflict.value.code, w.repo._pm_work_orders, w.repo._pm_master_memberships) == (
        "PM_MASTER_CATALOGUE_CONFLICT", {}, ())
    # An incomplete Set membership is refused by the storage itself.
    clean = await world()
    member = build_membership(snapshot, asset_id=VEH, vehicle_model_id="MODEL-0002", request_id=rid(),
                              fingerprint="f", scope={"is_test_data": "TRUE", "test_batch_id": BATCH})
    partial = replace(member, sets=(replace(member.sets[0], items=member.sets[0].items[:1]),))
    marker = {"assignment_model": "TECHNICIAN_V2", "is_test_data": "TRUE", "test_batch_id": BATCH}
    for bad in (partial, replace(member, is_test_data="FALSE", test_batch_id=""), replace(member, vehicle_model_id="")):
        with pytest.raises(ValueError, match="PM_MASTER_MEMBERSHIP_INVALID"):
            await clean.repo.create_pm_master_work_order(bad, build_catalogue(clean.rev), due_reason=None,
                                                         opened_by="u", note=None, opened_snapshot_id=None,
                                                         assignment_marker=marker)
    assert (clean.repo._pm_work_orders, clean.repo._pm_master_memberships) == ({}, ())
    assert clean.rev.revision_id not in clean.repo._pm_task_revisions  # no catalogue residue either
    # Two memberships disagreeing about one Set leave its Due unverified.
    report_engines(clean, carrier=1000)
    job, other = await open_wo(clean, [CARRIER_A]), await open_wo(clean, [CARRIER_A])
    await complete(clean, job)
    m, n = membership(clean, job), membership(clean, other)
    clean.repo._pm_master_memberships = (m, replace(n, sets=(replace(n.sets[0], section="CRANE"),)))
    decision = await due(clean, CARRIER_A, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1100}))
    assert outcome(decision) == ("UNKNOWN", None, "FROZEN_SET_ITEM_MAPPING_UNVERIFIED")


# ---------------------------------------------------------------- 11..15 idempotent creation


async def test_11_12_same_request_replays_and_a_changed_payload_is_rejected() -> None:
    w = await world()
    request_id = rid()
    job = await open_wo(w, [CARRIER_A, KM_SET], request_id=request_id, note="รอบทดสอบ")
    snapshots = dict(w.repo._meter_snapshots)
    assert await open_wo(w, [CARRIER_A, KM_SET], request_id=request_id, note="รอบทดสอบ") == job
    for changed in ({"keys": [KM_SET, CARRIER_A]}, {"note": "อื่น"}, {"asset_id": "VEH-1046"}):
        with pytest.raises(ApiError) as reused:
            await open_wo(w, changed.pop("keys", [CARRIER_A, KM_SET]), request_id=request_id,
                          **{"note": "รอบทดสอบ", **changed})
        assert (reused.value.code, reused.value.status_code) == ("REQUEST_ID_REUSED", 409)
    assert list(w.repo._pm_work_orders) == [job] and len(w.repo._pm_master_memberships) == 1
    assert w.repo._meter_snapshots == snapshots  # a replay captures no second open-time snapshot


async def test_13_concurrent_creation_same_request_is_one_work_order_different_requests_are_two() -> None:
    w = await world()
    request_id = rid()
    jobs = await asyncio.gather(*(open_wo(w, [CARRIER_A], request_id=request_id) for _ in range(5)))
    assert len(set(jobs)) == 1 and len(w.repo._pm_work_orders) == 1 and len(w.repo._meter_snapshots) == 1
    others = await asyncio.gather(open_wo(w, [CARRIER_A]), open_wo(w, [CARRIER_A]))
    assert len({*jobs, *others}) == 3  # separate requests are separate Work Orders (D3 is not decided)


async def test_13b_two_processes_racing_past_the_service_check_still_get_one_work_order(monkeypatch) -> None:
    """Simulates two backend processes: neither shares the in-process lock and both
    read "no such request" before writing. Only the storage write decides (a database
    needs a unique request id constraint inside the same transaction for this)."""
    w = await world()

    @asynccontextmanager
    async def no_shared_lock(_key):
        yield

    async def nothing_seen_yet(**_filters):
        return []

    monkeypatch.setattr(w.repo, "pm_work_order_lock", no_shared_lock)
    monkeypatch.setattr(w.repo, "list_pm_master_memberships", nothing_seen_yet)
    request_id = rid()
    jobs = await asyncio.gather(*(open_wo(w, [CARRIER_A], request_id=request_id) for _ in range(3)))
    assert len(set(jobs)) == 1 and len(w.repo._pm_work_orders) == 1 and len(w.repo._pm_master_memberships) == 1
    assert len(w.repo._meter_snapshots) == 3  # each "process" captured its own open-time snapshot (unreferenced)
    with pytest.raises(ApiError) as reused:
        await open_wo(w, [CARRIER_A], request_id=request_id, note="อื่น")
    assert reused.value.code == "REQUEST_ID_REUSED" and len(w.repo._pm_work_orders) == 1


async def test_14_an_interrupted_creation_is_never_reported_and_a_retry_recovers_it(monkeypatch) -> None:
    w = await world()
    real = w.repo.create_pm_master_work_order

    async def aborted(*args, **kwargs):
        raise RuntimeError("synthetic storage failure before commit")

    monkeypatch.setattr(w.repo, "create_pm_master_work_order", aborted)
    request_id = rid()
    with pytest.raises(RuntimeError):
        await open_wo(w, [CARRIER_A], request_id=request_id)
    assert (w.repo._pm_work_orders, w.repo._pm_master_memberships) == ({}, ())
    assert len(w.repo._meter_snapshots) == 1  # the only residue: an unreferenced open-time snapshot

    async def lost_response(*args, **kwargs):
        await real(*args, **kwargs)
        raise RuntimeError("synthetic failure after commit (response lost)")

    monkeypatch.setattr(w.repo, "create_pm_master_work_order", lost_response)
    with pytest.raises(RuntimeError):
        await open_wo(w, [CARRIER_A], request_id=request_id)
    [job] = w.repo._pm_work_orders
    monkeypatch.setattr(w.repo, "create_pm_master_work_order", real)
    assert await open_wo(w, [CARRIER_A], request_id=request_id) == job  # the retry is a replay
    assert len(w.repo._pm_work_orders) == 1 and membership(w, job).request_id == request_id
    assert {s.meter_snapshot_id for s in w.repo._meter_snapshots.values()} >= {
        w.repo._pm_work_orders[job].opened_snapshot_id}


async def test_15_restart_with_preserved_mock_state_replays_and_reads_the_same_due() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    request_id = rid()
    job = await open_wo(w, [CARRIER_A], request_id=request_id)
    await complete(w, job)
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1200})
    before = outcome(await due(w, CARRIER_A, source=source))
    w.repo.__dict__.pop("_pm_work_order_locks", None)  # in-process state is lost on restart
    # A restarted process composes the same bound store and repository again (RT1: the
    # scope / repository check runs before the replay lookup too).
    restarted = World(w.repo, w.store, PmMasterService(w.store, vehicle_resolver=MockVehicleResolver(w.repo)),
                      w.rev, pm(w.repo), FakeIotSource())
    assert await open_wo(restarted, [CARRIER_A], request_id=request_id) == job  # replay needs no Master write
    assert outcome(await due(restarted, CARRIER_A, source=source)) == before == ("NOT_DUE", 1500.0, None)


# ---------------------------------------------------------------- 17 RETURN -> SUBMIT -> CLOSE


async def test_17_returned_then_resubmitted_uses_only_the_accepted_submit() -> None:
    w = await world()
    report_engines(w, crane=2000)
    job = await open_wo(w, [CRANE_A])
    await complete(w, job, close=False)
    await w.svc.return_for_rework(job, manager(), request_id=rid(), reason="แก้ไขเอกสาร (synthetic)")
    w.source.items.clear()
    report_engines(w, crane=2050, ago=timedelta(seconds=30), received_ago=timedelta(seconds=10))
    await submit(w, job)
    await w.svc.close_after_review(job, manager(), request_id=rid())
    first, second = [e for e in w.repo._pm_transitions[job] if e.action.value == "SUBMIT"]
    decision = await due(w, CRANE_A, source=current_source({("ENGINE_HOUR", CRANE_ENG): 2100}))
    assert (outcome(decision), decision.source_submit_event_id) == (("NOT_DUE", 2650.0, None), second.event_id)
    assert w.repo._pm_submit_meter_anchors[first.event_id].readings[0].value == 2000.0  # kept, never accepted


# ---------------------------------------------------------------- 19, 20 current IoT meter


async def test_19_missing_stale_invalid_or_untrusted_current_meter_is_unknown() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A])
    await complete(w, job)
    unverified = ("UNKNOWN", None, "CURRENT_METER_UNVERIFIED")
    assert outcome(await due(w, CARRIER_A)) == unverified  # runtime default: no IoT source
    for changes in ({"ago": timedelta(hours=2)},                 # older than the source's own window
                    {"time_quality": "DEVICE_UNSYNCED"},        # no trusted device clock
                    {"device_verified": False},                 # device <-> vehicle not vouched
                    {"device_event_id": " "},                   # no device event identity
                    {"value": -1}, {"value": float("nan")},     # not a cumulative counter value
                    {"received_ago": -timedelta(minutes=5)},    # received after the evaluation time
                    {"vehicle_id": "VEH-1046"}):                # another vehicle
        source = FakeIotSource()
        source.report("ENGINE_HOUR", changes.pop("value", 1600), component_id=CARRIER_ENG,
                      vehicle_id=changes.pop("vehicle_id", VEH),
                      **{"ago": timedelta(seconds=5), "received_ago": timedelta(seconds=1), **changes})
        assert outcome(await due(w, CARRIER_A, source=source)) == unverified, changes
    no_window = current_source({("ENGINE_HOUR", CARRIER_ENG): 1600})
    no_window.max_observation_age = None  # the source cannot vouch for freshness: never a fixed default
    assert outcome(await due(w, CARRIER_A, source=no_window)) == unverified
    ambiguous = current_source({("ENGINE_HOUR", CARRIER_ENG): 1600})
    ambiguous.items.append(replace(ambiguous.items[0], value=1700, device_event_id="SYN-DEV-EVT-X"))
    assert outcome(await due(w, CARRIER_A, source=ambiguous)) == unverified


async def test_19b_current_counter_and_manual_snapshots_are_never_a_current_meter() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A])
    await complete(w, job)
    w.repo._current_counters[VEH] = [CurrentCounterReading(component_id=CARRIER_ENG,
                                                           counter_type=CounterType.ENGINE_HOUR, value=1600.0)]
    manual = await w.svc._meter.capture_current_state(asset_type=AssetType.VEHICLE, asset_id=VEH, recorded_by="u",
                                                      source_note="SYNTHETIC_MANUAL")
    assert any(r.value == 1600.0 for r in manual.readings)  # the snapshot carries the counter value ...
    assert outcome(await due(w, CARRIER_A)) == ("UNKNOWN", None, "CURRENT_METER_UNVERIFIED")  # ... never used


async def test_20_pto_and_vehicle_totals_are_never_substituted_for_an_engine() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A])
    await complete(w, job)
    source = FakeIotSource()
    for counter, component in (("PTO_HOUR", PTO), ("ENGINE_HOUR", PTO), ("ENGINE_HOUR", None),
                               ("ENGINE_HOUR", CRANE_ENG)):
        source.report(counter, 1600, component_id=component, vehicle_id=VEH, ago=timedelta(seconds=5),
                      received_ago=timedelta(seconds=1))
    assert outcome(await due(w, CARRIER_A, source=source)) == ("UNKNOWN", None, "CURRENT_METER_UNVERIFIED")
    m = membership(w, job)
    pto_set = replace(m.sets[0], meter_type="PTO_HOUR", driving_component_role="PTO")
    catalogue = await w.repo.get_pm_task_revision(m.pm_plan_id, m.master_revision_id)
    catalogue = catalogue.model_copy(update={"tasks": [
        t.model_copy(update={"trigger_type": PmTriggerType.PTO_HOUR}) if t.group == CARRIER_A else t for t in catalogue.tasks]})
    frozen = frozen_set([replace(m, sets=(pto_set,))], CARRIER_A, catalogue, [(PTO, "PTO")], "MODEL-0002")
    assert frozen.component_id is None and frozen.component_verified is False
    decision = evaluate_set_due(frozen, (), CurrentMeter("PTO_HOUR", None, 1600, True))
    assert outcome(decision) == ("UNKNOWN", None, "PM_METER_NOT_APPROVED")


# ---------------------------------------------------------------- 21 zero writes, 22 TEST/REAL


async def test_21_a_due_read_makes_zero_writes() -> None:
    w = await world()
    report_engines(w, carrier=1000, crane=2000)
    job = await open_wo(w, [CARRIER_A, CRANE_A])
    await complete(w, job)
    state = (dict(w.repo._pm_work_orders), w.repo._pm_master_memberships, dict(w.repo._meter_snapshots),
             dict(w.repo._pm_submit_meter_anchors), {k: list(v) for k, v in w.repo._pm_transitions.items()},
             dict(w.repo._pm_task_revisions), dict(w.repo._pm_item_outcomes))
    w.repo.calls.clear()
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100, ("ENGINE_HOUR", CRANE_ENG): 2700})
    for key in (CARRIER_A, CRANE_A, KM_SET):
        await due(w, key, source=source)
    assert w.repo.calls and not [c for c in w.repo.calls if c.startswith(WRITES)]
    assert (dict(w.repo._pm_work_orders), w.repo._pm_master_memberships, dict(w.repo._meter_snapshots),
            dict(w.repo._pm_submit_meter_anchors), {k: list(v) for k, v in w.repo._pm_transitions.items()},
            dict(w.repo._pm_task_revisions), dict(w.repo._pm_item_outcomes)) == state


async def test_21b_the_due_read_needs_the_e01_outcome_read_authority() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A])
    await complete(w, job)
    for context in (ctx("USR-SYN-OUTSIDER", authz.CAN_VIEW), None):
        with pytest.raises(Exception) as denied:
            await pm(w.repo).evaluate_master_set_due(context, asset_id=VEH, master_revision_id=w.rev.revision_id,
                                                     set_key=CARRIER_A)
        assert getattr(denied.value, "status_code", None) == 403


async def test_22_test_and_real_scopes_are_isolated() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    request_id = rid()
    job = await open_wo(w, [CARRIER_A], request_id=request_id)
    wo, m = w.repo._pm_work_orders[job], membership(w, job)
    assert (m.is_test_data, m.test_batch_id) == (wo.is_test_data, wo.test_batch_id) == ("TRUE", BATCH)
    await complete(w, job)
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    assert outcome(await due(w, CARRIER_A, source=source))[0] == "NOT_DUE"
    for other, other_scope in ((pm(w.repo, source, batch="TEST-OTHER-BATCH"), MasterDataScope.test("TEST-OTHER-BATCH")),
                               (pm(w.repo, source, context="REAL"), MasterDataScope.real())):
        assert outcome(await due(w, CARRIER_A, svc=other)) == ("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION")
        # RT1: this batch's Master is refused by a foreign server before its replay is even looked up ...
        with pytest.raises(ApiError) as foreign:
            await open_wo(w, [CARRIER_A], request_id=request_id, svc=other)
        assert (foreign.value.code, foreign.value.details) == ("PM_MASTER_SCOPE_MISMATCH", None)
        # ... and a Master bound to THAT server's scope still cannot replay this batch's request.
        theirs = PmMasterService(PmMasterMockStore(data_scope=other_scope),
                                 vehicle_resolver=MockVehicleResolver(w.repo))
        with pytest.raises(ApiError) as replay:
            await other.open_master_work_order(theirs, opener(), asset_id=VEH, plan_code=PLAN, revision_number=1,
                                               selected_set_keys=[CARRIER_A], request_id=request_id,
                                               model_variants=synthetic_test_only_variants)
        assert replay.value.code == "TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH"
    assert len(w.repo._pm_work_orders) == 1


# ---------------------------------------------------------------- 23, 24 firewall, dormancy and OPEN-005


def test_23_the_bridge_is_dormant_no_route_or_api_module_reaches_it() -> None:
    """No route opens a Master-sourced Work Order or reaches the per-Set bridge, and no
    API module touches the Master. The only Master-AWARE route is the read-only Fleet
    PM Due B1 read (`pm_due_routes`); `test_23b` proves the application composition
    gives it no Master, so it cannot activate, load or write one."""
    for path in (BACKEND / "app" / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "open_master_work_order" not in text and "evaluate_master_set_due" not in text, path
        assert "pm_master" not in text and "PmMaster" not in text, path


def test_23b_production_composition_wires_no_master_and_no_unverified_evidence_reader() -> None:
    """Fleet PM Due B1 semantic firewall (replaces nothing above, adds to it):
    1. the composition root never constructs, imports or passes a Master or a model
       variant source, and no application module calls the TEST-ONLY
       `PmService.with_master_reads`, so the application's `PmService` has neither
       (the constructor contract is unchanged; MASTER_NOT_ACTIVE;
       the fresh-interpreter route proof is `test_pm_fleet_due.test_f25`);
    2. outside the Master and its runtime bridge, no application module imports either
       at module level (`PmService` imports the runtime lazily, after a Master was
       injected), so the running application never loads them;
    3. no application module builds Due evidence with the integrity-free
       `read_work_order_evidence` (R3 E01 read safety: `PmService._verified_due_evidence`);
    4. no route writes through the Master: every PM Due route is a GET."""
    import ast

    from app.dependencies import get_pm_service
    from app.config import get_settings

    wiring = (BACKEND / "app" / "dependencies.py").read_text(encoding="utf-8")
    for forbidden in ("pm_master", "PmMaster", "model_variants", "ModelVariantSource", "with_master_reads"):
        assert forbidden not in wiring, forbidden
    svc = get_pm_service(repo_with(), MeterService(repo_with()), get_settings())
    assert (svc._pm_master, svc._model_variants) == (None, None)
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name in ("pm_master.py", "pm_master_runtime.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module level only; lazy imports inside functions are allowed
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            names += [f"{node.module}.{a.name}" for a in node.names] if isinstance(node, ast.ImportFrom) else []
            assert not any(n.startswith(("app.domain.pm_master", "app.domain.pm_master_runtime")) for n in names), path
        if path.name != "pm_meter_anchor.py":
            assert "read_work_order_evidence" not in path.read_text(encoding="utf-8"), path
        if path.name != "pm_service.py":  # the TEST-ONLY injection is defined there and called by no app module
            assert "with_master_reads" not in path.read_text(encoding="utf-8"), path
    from app.api.v1.pm_due_routes import router as due_router
    assert {m for r in due_router.routes for m in r.methods} == {"GET"}


async def test_24_open_005_master_authority_still_refuses_and_the_bridge_fails_closed() -> None:
    repo = repo_with()
    store = PmMasterMockStore(data_scope=TEST_SCOPE)
    production = PmMasterService(store, vehicle_resolver=MockVehicleResolver(repo))  # default authorizer
    with pytest.raises(ApiError) as refused:
        await production.set_assignment(opener(), vehicle_id=VEH, plan_code=PLAN, expected_version=0,
                                        reason="ทดสอบ", request_id=rid())
    assert (refused.value.code, refused.value.status_code) == ("PM_MASTER_AUTHORITY_UNPROVEN", 403)
    with pytest.raises(ApiError) as unpublished:
        await pm(repo).open_master_work_order(production, opener(), asset_id=VEH, plan_code=PLAN, revision_number=1,
                                              selected_set_keys=[CARRIER_A], request_id=rid())
    assert unpublished.value.code == "PM_MASTER_REVISION_NOT_FOUND"
    w = await world(assign_vehicle=False)
    with pytest.raises(ApiError) as unassigned:
        await open_wo(w, [CARRIER_A])
    assert unassigned.value.code == "PM_MASTER_PLAN_NOT_ASSIGNED"
    w = await world()
    for context in (manager(), ctx("USR-SYN-VIEWER", authz.CAN_VIEW), None):  # no can_view / no can_manage_pm
        with pytest.raises(Exception) as denied:
            await open_wo(w, [CARRIER_A], context=context)
        assert getattr(denied.value, "status_code", None) == 403
    assert (w.repo._pm_work_orders, w.repo._pm_master_memberships) == ({}, ())


async def test_24b_adapters_without_bridge_storage_refuse_explicitly() -> None:
    repo = repo_with()
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await Repository.list_pm_master_memberships(repo)
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await Repository.create_pm_master_work_order(repo, None, None, due_reason=None, opened_by=None, note=None,
                                                     opened_snapshot_id=None, assignment_marker={})


# ---------------------------------------------------------------- model variant safety gate (pre-commit)


def nothing_written(repo) -> tuple:
    return (repo._pm_work_orders, repo._pm_master_memberships, repo._meter_snapshots,
            [r for r in repo._pm_task_revisions if r.startswith("PMMREV-")])


async def test_mv_01_two_models_sharing_a_plan_get_only_their_own_variant_sets() -> None:
    w = await world()
    await w.master.set_assignment(master_ctx(), vehicle_id="VEH-1048", assembly="", plan_code=PLAN, expected_version=0,
                                  reason="กำหนดแผนทดสอบ (synthetic)", request_id=rid())
    m1 = await open_wo(w, [CARRIER_A, CRANE_A])                 # VEH-1047 / MODEL-0002 -> SYN-M1
    m2 = await open_wo(w, [M2_A], asset_id="VEH-1048")           # VEH-1048 / MODEL-0003 -> SYN-M2
    assert (membership(w, m1).vehicle_model_id, membership(w, m2).vehicle_model_id) == ("MODEL-0002", "MODEL-0003")
    assert {s.model_variant for s in membership(w, m2).sets} == {"SYN-M2"}
    before = (dict(w.repo._pm_work_orders), w.repo._pm_master_memberships, dict(w.repo._meter_snapshots))
    # Same Plan, and each vehicle has the CARRIER_ENGINE the other model's Set needs: still refused.
    for keys, vehicle in (([M2_A], VEH), ([CARRIER_A], "VEH-1048"), ([M7_A], VEH)):
        with pytest.raises(ApiError) as refused:
            await open_wo(w, keys, asset_id=vehicle)
        assert (refused.value.code, refused.value.status_code) == ("PM_MASTER_MODEL_VARIANT_UNVERIFIED", 422)
    assert (dict(w.repo._pm_work_orders), w.repo._pm_master_memberships, dict(w.repo._meter_snapshots)) == before


async def test_mv_02_missing_or_ambiguous_mapping_refuses_before_any_write() -> None:
    w = await world()
    for source in (None,                                               # the application default: nothing proven
                   lambda model_id, plan_code: frozenset(),            # missing / PENDING_PM_PLAN / no provenance
                   lambda model_id, plan_code: {"SYN-M1", "SYN-M2"},   # ambiguous or conflicting
                   lambda model_id, plan_code: {"syn-m1"}):            # similar text is not the variant
        with pytest.raises(ApiError) as refused:
            await open_wo(w, [CARRIER_A], model_variants=source)
        assert refused.value.code == "PM_MASTER_MODEL_VARIANT_UNVERIFIED"
    w.repo._vehicles[VEH] = w.repo._vehicles[VEH].model_copy(update={"model_id": "MODEL-SYN-ABSENT"})
    with pytest.raises(ApiError) as no_model:
        await open_wo(w, [CARRIER_A], model_variants=lambda model_id, plan_code: {"SYN-M1"})
    assert no_model.value.code == "PM_MASTER_MODEL_VARIANT_UNVERIFIED"  # a vehicle without a model proves nothing
    assert nothing_written(w.repo) == ({}, (), {}, [])  # no Work Order, membership, snapshot or catalogue


async def test_mv_03_replay_never_changes_identity_and_a_changed_model_makes_due_unknown() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    request_id = rid()
    job = await open_wo(w, [CARRIER_A], request_id=request_id)
    await complete(w, job)
    with pytest.raises(ApiError) as other_vehicle:
        await open_wo(w, [CARRIER_A], request_id=request_id, asset_id="VEH-1048")
    assert other_vehicle.value.code == "REQUEST_ID_REUSED"
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    assert outcome(await due(w, CARRIER_A, source=source))[0] == "NOT_DUE"
    w.repo._vehicles[VEH] = w.repo._vehicles[VEH].model_copy(update={"model_id": "MODEL-0001"})
    assert await open_wo(w, [CARRIER_A], request_id=request_id) == job  # replay: the recorded Work Order, no new write
    assert len(w.repo._pm_work_orders) == 1 and membership(w, job).vehicle_model_id == "MODEL-0002"
    assert outcome(await due(w, CARRIER_A, source=source)) == ("UNKNOWN", None, "FROZEN_SET_ITEM_MAPPING_UNVERIFIED")
    with pytest.raises(ApiError) as new_request:  # a NEW request for the re-modelled vehicle is not proven
        await open_wo(w, [CARRIER_A])
    assert new_request.value.code == "PM_MASTER_MODEL_VARIANT_UNVERIFIED"


async def test_mv_04_an_association_holds_only_for_its_exact_master_plan() -> None:
    """OPEN-016: the association is (model, exact Master Plan) -> variant. An approval
    for Plan1 never opens a Plan2 Set with the same variant label, and the plan code is
    never converted to anything else."""
    w = await world()
    reg = await register(w.master)
    await resolve_all(w.master, reg, plan=PLAN_B)
    rev_b = (await publish(w.master, reg, 0, plan=PLAN_B)).revision
    [gb] = rev_b.sets
    await w.master.set_assignment(master_ctx(), vehicle_id=VEH, assembly="", plan_code=PLAN_B, expected_version=1,
                                  reason="เปลี่ยนแผนทดสอบ (synthetic)", request_id=rid())
    plan1_only = {("MODEL-0002", PLAN): {gb.model_variant}}  # approved for Plan1 only, same label as the Plan2 Set
    with pytest.raises(ApiError) as wrong_plan:
        await open_wo(w, [gb.set_key], plan_code=PLAN_B, revision=rev_b,
                      model_variants=lambda model_id, plan_code: plan1_only.get((model_id, plan_code), ()))
    assert (wrong_plan.value.code, wrong_plan.value.details["plan_code"]) == (
        "PM_MASTER_MODEL_VARIANT_UNVERIFIED", PLAN_B)
    assert nothing_written(w.repo) == ({}, (), {}, [])
    both = {**plan1_only, ("MODEL-0002", PLAN_B): {gb.model_variant}}
    job = await open_wo(w, [gb.set_key], plan_code=PLAN_B, revision=rev_b,
                        model_variants=lambda model_id, plan_code: both.get((model_id, plan_code), ()))
    assert (membership(w, job).plan_code, membership(w, job).vehicle_model_id) == (PLAN_B, "MODEL-0002")
    other_model = {("MODEL-0003", PLAN_B): {gb.model_variant}}  # another model's approval never applies
    with pytest.raises(ApiError) as registration_mismatch:
        await open_wo(w, [gb.set_key], plan_code=PLAN_B, revision=rev_b,
                      model_variants=lambda model_id, plan_code: other_model.get((model_id, plan_code), ()))
    assert registration_mismatch.value.code == "PM_MASTER_MODEL_VARIANT_UNVERIFIED"


async def test_mv_05_a_refused_opening_writes_nothing_in_either_data_scope() -> None:
    # RT1: under REAL the TEST-bound Master is refused even earlier (scope), still writing nothing.
    for scope, code in (({}, "PM_MASTER_MODEL_VARIANT_UNVERIFIED"), ({"context": "REAL"}, "PM_MASTER_SCOPE_MISMATCH")):
        w = await world()
        with pytest.raises(ApiError) as refused:
            await open_wo(w, [M2_A], svc=pm(w.repo, **scope))
        assert refused.value.code == code
        assert nothing_written(w.repo) == ({}, (), {}, [])


async def test_25_distinct_synthetic_personas_drive_master_to_e01_to_due() -> None:
    """DEC-R4-TASK010-OPEN005-TEST-AUTH-20261106: EDITOR publishes, ASSIGNER assigns, a
    can_manage_pm user opens, the V2 PRIMARY submits and a separate reviewer closes."""
    repo, source = repo_with(), FakeIotSource()
    store = PmMasterMockStore(data_scope=TEST_SCOPE)
    master = PmMasterService(store, authorizer=persona_test_only_authorizer, vehicle_resolver=MockVehicleResolver(repo))
    editor, assigner = master_ctx(TEST_PM_MASTER_EDITOR), master_ctx(TEST_PM_MASTER_ASSIGNER)
    reg = await register(master, context=editor)
    await resolve_all(master, reg, context=editor)
    rev = (await publish(master, reg, 0, context=editor)).revision
    await master.set_assignment(assigner, vehicle_id=VEH, assembly="", plan_code=PLAN, expected_version=0,
                                reason="กำหนดแผนทดสอบ (synthetic)", request_id=rid())
    w = World(repo, store, master, rev, pm(repo, source), source)
    for persona in (editor, assigner):  # Master authority is not E01 Work Order authority
        with pytest.raises(Exception) as denied:
            await open_wo(w, [CARRIER_A], context=persona)
        assert getattr(denied.value, "status_code", None) == 403
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A])
    await assign(repo, job, body(T1, T2), kind=PM)
    await start(w.svc, job)
    for task in repo._pm_work_orders[job].scope_task_ids:
        await save(w.svc, job, task, PERFORMED)
    await submit(w, job)  # the V2 PRIMARY (U1)
    reviewer = ctx("USR-SYN-REVIEWER", authz.CAN_MANAGE_PM)
    closed = await w.svc.close_after_review(job, reviewer, request_id=rid())
    assert (closed.work_order.status, closed.work_order.closed_by) == (S.CLOSED, "USR-SYN-REVIEWER")
    [submitted] = [e for e in repo._pm_transitions[job] if e.action.value == "SUBMIT"]
    assert submitted.actor == U1
    decision = await due(w, CARRIER_A, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1499}))
    assert (outcome(decision), decision.source_submit_event_id) == (("NOT_DUE", 1500.0, None), submitted.event_id)


async def test_26_an_older_revision_with_a_pto_hour_set_never_opens_that_set() -> None:
    """Owner PM policy at the opening boundary: an immutable revision published before
    the PTO_HOUR correction keeps its data, but its PTO_HOUR Set opens no Work Order;
    its ENGINE_HOUR Sets still open and complete normally."""
    w = await world()
    first = await open_wo(w, [CARRIER_A])
    historical = w.repo._pm_work_orders[first].model_dump()
    rev2 = w.rev.model_copy(update={  # RT3-A: the scope-qualified id `publish` gives revision 2
        "revision_id": master_revision_id(w.rev.data_scope, PLAN, 2), "revision_number": 2,
        "request_id": "REQ-SYN-LEGACY-REV",
        "sets": tuple(s.model_copy(update={"meter_type": PmTriggerType.PTO_HOUR, "driving_component": ComponentRole.PTO})
                      if s.set_key == CRANE_A else s for s in w.rev.sets)})
    w.store.commit({"kind": "PUBLISH", "request_id": "REQ-SYN-LEGACY-REV", "request_fingerprint": "legacy"},
                   revision=rev2)  # as an older build published it
    before = (dict(w.repo._pm_work_orders), w.repo._pm_master_memberships, dict(w.repo._meter_snapshots),
              rev2.revision_id in w.repo._pm_task_revisions)
    for keys in ([CRANE_A], [CARRIER_A, CRANE_A]):
        with pytest.raises(ApiError) as refused:
            await open_wo(w, keys, revision=rev2)
        assert (refused.value.code, refused.value.status_code) == ("PM_MASTER_METER_NOT_PM_TRIGGER", 422)
    assert (dict(w.repo._pm_work_orders), w.repo._pm_master_memberships, dict(w.repo._meter_snapshots),
            rev2.revision_id in w.repo._pm_task_revisions) == before == (before[0], before[1], before[2], False)
    assert w.repo._pm_work_orders[first].model_dump() == historical  # history untouched
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A], revision=rev2)  # the ENGINE_HOUR Set still opens
    await complete(w, job)
    decision = await due(w, CARRIER_A, revision=rev2, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1499}))
    assert outcome(decision) == ("NOT_DUE", 1500.0, None)


# ---------------------------------------------------------------- RT1 (G1 / G2): bound Master at the opening


def unbound_or_foreign_masters(w: World):
    """(label, Master, expected 409 code): every Master the runtime must refuse to open from."""
    same_repo = MockVehicleResolver(w.repo)
    return (
        ("unbound", PmMasterService(PmMasterMockStore(), vehicle_resolver=same_repo), "PM_MASTER_SCOPE_MISMATCH"),
        ("other TEST batch", PmMasterService(PmMasterMockStore(data_scope=MasterDataScope.test("SYN-OTHER-BATCH")),
                                             vehicle_resolver=same_repo), "PM_MASTER_SCOPE_MISMATCH"),
        ("REAL", PmMasterService(PmMasterMockStore(data_scope=MasterDataScope.real()), vehicle_resolver=same_repo),
         "PM_MASTER_SCOPE_MISMATCH"),
        # The SAME published, assigned TEST store whose resolver reads another Mock repository
        # instance with the identical seed (the pre-RT1 test composition), or no resolver.
        ("other repository", PmMasterService(w.store, authorizer=synthetic_test_only_authorizer,
                                             vehicle_resolver=MockVehicleResolver(repo_with())),
         "PM_MASTER_REPOSITORY_MISMATCH"),
        ("no resolver", PmMasterService(w.store, authorizer=synthetic_test_only_authorizer),
         "PM_MASTER_REPOSITORY_MISMATCH"),
    )


def side_effects(w: World) -> tuple:
    return (*nothing_written(w.repo), dict(w.repo._pm_submit_meter_anchors), w.store.events, w.store.assignments,
            dict(w.store.revisions))


async def test_rt1_08_a_foreign_unbound_or_other_repository_master_opens_nothing() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    before = side_effects(w)
    for label, master, code in unbound_or_foreign_masters(w):
        with pytest.raises(ApiError) as refused:
            await w.svc.open_master_work_order(master, opener(), asset_id=VEH, plan_code=PLAN, revision_number=1,
                                               selected_set_keys=[CARRIER_A], request_id=rid(),
                                               model_variants=synthetic_test_only_variants)
        assert (refused.value.status_code, refused.value.code, refused.value.details) == (409, code, None), label
        assert "SYN-OTHER-BATCH" not in refused.value.message and BATCH not in refused.value.message
        assert side_effects(w) == before, label  # no WO, membership, catalogue, snapshot, anchor or audit
    job = await open_wo(w, [CARRIER_A])  # the bound Master over the same repository still opens normally
    assert membership(w, job).sets[0].set_key == CARRIER_A


async def test_rt1_09_a_replay_never_bypasses_the_scope_or_repository_check() -> None:
    w = await world()
    report_engines(w, carrier=1000)
    request_id = rid()
    job = await open_wo(w, [CARRIER_A], request_id=request_id)
    before = side_effects(w)
    for label, master, code in unbound_or_foreign_masters(w):
        with pytest.raises(ApiError) as refused:
            await w.svc.open_master_work_order(master, opener(), asset_id=VEH, plan_code=PLAN, revision_number=1,
                                               selected_set_keys=[CARRIER_A], request_id=request_id,
                                               model_variants=synthetic_test_only_variants)
        assert (refused.value.code, refused.value.details) == (code, None), label
        assert job not in refused.value.message
    assert side_effects(w) == before
    assert await open_wo(w, [CARRIER_A], request_id=request_id) == job  # the bound replay is unchanged
    assert len(w.repo._pm_work_orders) == 1
