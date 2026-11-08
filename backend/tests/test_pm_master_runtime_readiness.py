"""R4 / TASK-010 PM Master Runtime Readiness RT1 (G5): ONE complete TEST-only path from
a synthetic source workbook to the HTTP Fleet PM Due read.

Synthetic source preview -> review -> publish (TEST_PM_MASTER_EDITOR) -> RT2 explicit,
evidence-backed model variant approval (TEST_PM_MASTER_EDITOR) -> assign
(TEST_PM_MASTER_ASSIGNER) -> open a Master PM Work Order (can_manage_pm) -> Technician
V2 SUBMIT with a verified FAKE IoT anchor -> reviewer CLOSE -> `GET /api/v1/pm/due/...`.

Everything is synthetic and in memory: the Master store is bound to the server's TEST
batch (RT1 G1), its assignment resolver reads the SAME Mock repository as the runtime
(RT1 G2), the personas are the existing TEST-only fixtures (OPEN-005 stays closed in
the application), the model-variant association is an RT2 approval recorded in that
bound Master (no synthetic variant dictionary, OPEN-016) and every meter reading
is a FakeIotSource observation. The Master reaches the HTTP layer only through a
test-local `dependency_overrides[get_pm_service]`; the application's own wiring is
untouched (`test_pm_fleet_due.py` f24/f25 prove it stays MASTER_NOT_ACTIVE). This is a
Mock proof, not Google Sheets, PostgreSQL or physical IoT evidence.
"""
from __future__ import annotations

import uuid

from app.domain import authz
from app.domain.meter_service import MeterService
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.pm_master import MockVehicleResolver, PmMasterMockStore, PmMasterService
from app.domain.pm_meter_anchor import NO_IOT_METER_SOURCE
from app.domain.pm_service import PmService
from app.domain.technician_assignment import PM
from tests.pm_e01_support import ctx, manager, repo_with, rid, start
from tests.test_pm_master_b1_mock import (
    CARRIER_A,
    CRANE_A,
    KM_SET,
    PLAN,
    TEST_PM_MASTER_ASSIGNER,
    TEST_PM_MASTER_EDITOR,
    persona_test_only_authorizer,
    publish,
    register,
    resolve_all,
)
from tests.test_pm_master_b1_mock import ctx as master_ctx
from tests.test_pm_master_e01_due_bridge import (
    CARRIER_ENG,
    CRANE_ENG,
    TEST_SCOPE,
    VEH,
    World,
    complete,
    current_source,
    report_engines,
    tasks_of,
)
from tests.test_pm_master_e01_due_bridge import open_wo as bridge_open_wo
from tests.test_pm_master_model_variant_approval import registered_workbook, row_of
from tests.test_pm_submit_meter_anchor import FakeIotSource
from tests.test_technician_assignment_batch_r2f_h1 import T1, T2, assign, body, cut

API = "/api/v1"
VIEWER = frozenset({authz.CAN_VIEW})
SETS = (CARRIER_A, CRANE_A, KM_SET)  # CARRIER 500 h, CRANE 600 h, vehicle ODOMETER 10,000 km


async def source_to_master_world() -> World:
    """The Master built from the synthetic SOURCE through the audited operations only."""
    repo, source = repo_with(), FakeIotSource()
    store = PmMasterMockStore(data_scope=TEST_SCOPE)
    master = PmMasterService(store, authorizer=persona_test_only_authorizer, vehicle_resolver=MockVehicleResolver(repo))
    editor, assigner = master_ctx(TEST_PM_MASTER_EDITOR), master_ctx(TEST_PM_MASTER_ASSIGNER)
    reg = await register(master, registered_workbook(), context=editor)  # the service computes the preview
    assert any(e.action == "REVIEW" for e in reg.preview.ledger)  # the review step is real, not skipped
    await resolve_all(master, reg, context=editor)
    rev = (await publish(master, reg, 0, context=editor)).revision
    # RT2: the vehicle's model reaches the Plan only through an explicit, evidenced approval.
    approval = (await master.approve_model_variant(
        editor, model_id="MODEL-0002", plan_code=PLAN, model_variant="SYN-M1", expected_version=0,
        preview_id=reg.preview_id, expected_source_digest=reg.source_digest, source_rows=[row_of(reg, VEH)],
        evidence="แถว vehicle_pm_mapping ของ VEH-1047 ระบุ SYN-M1 (synthetic)",
        reason="อนุมัติรุ่น (synthetic)", request_id=rid())).record
    assert (approval.state, approval.recorded_by) == ("APPROVED", TEST_PM_MASTER_EDITOR)
    await master.set_assignment(assigner, vehicle_id=VEH, assembly="", plan_code=PLAN, expected_version=0,
                                reason="กำหนดแผนทดสอบ (synthetic)", request_id=rid())
    assert (rev.revision_number, rev.published_by, store.assignments[-1].recorded_by) == (
        1, TEST_PM_MASTER_EDITOR, TEST_PM_MASTER_ASSIGNER)
    assert set(SETS) <= {s.set_key for s in rev.sets}
    assert store.data_scope == TEST_SCOPE and master.vehicle_repository is repo  # RT1 G1 / G2
    return World(repo, store, master, rev, PmService(repo, MeterService(repo, iot_meter_source=source),
                                                     assignment_cutover=cut()), source)


def due_service(w: World, source=None, **cutover) -> PmService:
    """TEST-ONLY injection of the bound Master into a PM service over the same repository;
    no variant override, so the Master's own RT2 approvals are the variant source."""
    return PmService(w.repo, MeterService(w.repo, iot_meter_source=source or NO_IOT_METER_SOURCE),
                     assignment_cutover=cut(**cutover)).with_master_reads(w.master, None)


async def open_wo(w: World, keys, **kw) -> str:
    """Open through the Master's own approved variant source (no synthetic override)."""
    return await bridge_open_wo(w, keys, model_variants=None, **kw)


async def http_get(path: str, service: PmService, caps: frozenset[str] = VIEWER):
    """GET through the real app and routers; only the PM service (and actor) is overridden."""
    from httpx import ASGITransport, AsyncClient

    from app.context import RequestContext
    from app.dependencies import get_current_context, get_pm_service
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_pm_service] = lambda: service
    app.dependency_overrides[get_current_context] = lambda: RequestContext(
        request_id=str(uuid.uuid4()), user_id="SYN-RT1-VIEWER", is_dev_auth=True, capabilities=caps)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as client:
        return await client.get(f"{API}{path}")


def domain_sets(vehicle) -> dict[str, tuple]:
    return {s.set_key: (s.status, s.next_due, s.diagnostic_code, s.last_completed_meter, s.current_meter,
                        s.last_completed_pm_work_order_id) for s in vehicle.sets}


def http_sets(body: dict) -> dict[str, tuple]:
    return {s["set_key"]: (s["status"], s["next_due"], s["diagnostic_code"], s["last_completed_meter"],
                           s["current_meter"], s["last_completed_pm_work_order_id"]) for s in body["sets"]}


def state(w: World) -> tuple:
    r = w.repo
    return (dict(r._pm_work_orders), r._pm_master_memberships, dict(r._meter_snapshots),
            dict(r._pm_submit_meter_anchors), {k: list(v) for k, v in r._pm_transitions.items()},
            dict(r._pm_task_revisions), dict(r._pm_item_outcomes), w.store.events, w.store.assignments)


async def read_both(w: World, readings: dict) -> dict[str, tuple]:
    """The vehicle's Due through the domain service AND the HTTP route: identical."""
    service = due_service(w, current_source(readings))
    domain = domain_sets(await service.read_vehicle_pm_due(ctx("SYN-RT1-VIEWER", authz.CAN_VIEW), VEH))
    response = await http_get(f"/pm/due/vehicles/{VEH}", service)
    assert response.status_code == 200 and response.json()["state"] == "AVAILABLE"
    assert http_sets(response.json()) == domain
    return domain


def due(rows: dict, key: str) -> tuple:
    status, next_due, reason, last_meter, _, _ = rows[key]
    return status, next_due, reason, last_meter


async def test_rt1_e2e_01_source_to_master_to_e01_to_http_fleet_due() -> None:
    w = await source_to_master_world()

    # 1. Published, assigned, never worked: every Set is listed and UNKNOWN, never zero.
    rows = await read_both(w, {})
    assert {k: due(rows, k) for k in SETS} == {k: ("UNKNOWN", None, "NO_VERIFIED_ACTUAL_SET_COMPLETION", None)
                                               for k in SETS}
    fleet = await http_get("/pm/due/vehicles", due_service(w))
    assert fleet.status_code == 200
    states = {v["vehicle_id"]: v["state"] for v in fleet.json()["items"]}
    assert states[VEH] == "AVAILABLE" and set(states.values()) == {"AVAILABLE", "NO_ASSIGNED_PLAN"}

    # 2. One Work Order, all three Sets fully PERFORMED; SUBMIT anchors CARRIER 1000 h,
    #    CRANE 650 h and ODOMETER 50,000 km (FAKE IoT); the reviewer CLOSE accepts it.
    report_engines(w, carrier=1000, crane=650, odometer=50000)
    first = await open_wo(w, list(SETS))
    await complete(w, first)
    assert w.repo._pm_work_orders[first].status == S.CLOSED
    rows = await read_both(w, {("ENGINE_HOUR", CARRIER_ENG): 1499, ("ENGINE_HOUR", CRANE_ENG): 1249,
                               ("ODOMETER", None): 59999})
    assert [due(rows, k) for k in SETS] == [("NOT_DUE", 1500.0, None, 1000.0),
                                            ("NOT_DUE", 1250.0, None, 650.0),   # 600 h done at 650 -> 1,250
                                            ("NOT_DUE", 60000.0, None, 50000.0)]
    rows = await read_both(w, {("ENGINE_HOUR", CRANE_ENG): 1250})
    assert due(rows, CRANE_A) == ("DUE", 1250.0, None, 650.0)

    # 3. CRANE alone again at 1,300 h: only CRANE moves; CARRIER and ODOMETER keep theirs.
    w.source.items.clear()
    report_engines(w, carrier=1100, crane=1300, odometer=51000)
    second = await open_wo(w, [CRANE_A])
    await complete(w, second)
    current = {("ENGINE_HOUR", CARRIER_ENG): 1400, ("ENGINE_HOUR", CRANE_ENG): 1400, ("ODOMETER", None): 52000}
    rows = await read_both(w, current)
    assert [due(rows, k) for k in SETS] == [("NOT_DUE", 1500.0, None, 1000.0), ("NOT_DUE", 1900.0, None, 1300.0),
                                            ("NOT_DUE", 60000.0, None, 50000.0)]
    assert rows[CRANE_A][5] == second and rows[CARRIER_A][5] == rows[KM_SET][5] == first

    # 4. CARRIER NOT_PERFORMED while ODOMETER is PERFORMED: only the complete Set advances.
    w.source.items.clear()
    report_engines(w, carrier=1200, crane=1350, odometer=55000)
    third = await open_wo(w, [CARRIER_A, KM_SET])
    await complete(w, third, not_performed=tuple(tasks_of(w, third, CARRIER_A)))
    current = {**current, ("ODOMETER", None): 57000}  # a current reading below an anchor would be UNKNOWN
    rows = await read_both(w, current)
    assert due(rows, CARRIER_A) == ("NOT_DUE", 1500.0, None, 1000.0)  # the partial Set kept its anchor
    assert due(rows, KM_SET) == ("NOT_DUE", 65000.0, None, 55000.0)

    # 5. A RETURNed submission and an unfinished Work Order never advance an anchor.
    w.source.items.clear()
    report_engines(w, carrier=1300, crane=1390, odometer=56000)
    returned = await open_wo(w, [CRANE_A])
    await complete(w, returned, close=False)
    await w.svc.return_for_rework(returned, manager(), request_id=rid(), reason="แก้ไขเอกสาร (synthetic)")
    unfinished = await open_wo(w, [CARRIER_A])
    await assign(w.repo, unfinished, body(T1, T2), kind=PM)
    await start(w.svc, unfinished)
    assert (await read_both(w, current)) == rows
    assert w.repo._pm_work_orders[unfinished].status == S.IN_PROGRESS

    # 6. No verified current meter: UNKNOWN (no next Due), never zero; completions stay proven.
    rows = await read_both(w, {})
    for key in SETS:
        status, next_due, _, last_meter, current_meter, _ = rows[key]
        assert (status, next_due, current_meter) == ("UNKNOWN", None, None) and last_meter not in (None, 0)


async def test_rt1_e2e_02_can_view_reads_derived_due_only_and_gets_are_side_effect_free() -> None:
    w = await source_to_master_world()
    report_engines(w, carrier=1000, crane=650, odometer=50000)
    job = await open_wo(w, list(SETS))
    await complete(w, job)
    service = due_service(w, current_source({("ENGINE_HOUR", CRANE_ENG): 700}))
    before = state(w)
    assert (await http_get("/pm/due/vehicles", service)).status_code == 200
    assert (await http_get(f"/pm/due/vehicles/{VEH}", service)).status_code == 200
    for raw in (f"/pm/work-orders/{job}/outcomes", f"/pm/work-orders/{job}/history"):
        assert (await http_get(raw, service)).status_code == 403  # no raw Outcome / journal for can_view
    for caps in (frozenset(), frozenset({authz.CAN_MANAGE_PM})):  # can_view is the Due read capability
        for path in ("/pm/due/vehicles", f"/pm/due/vehicles/{VEH}"):
            assert (await http_get(path, service, caps)).status_code == 403
    assert state(w) == before  # no projection, capture, anchor or audit row from any GET


async def test_rt1_e2e_03_the_same_master_is_invisible_over_http_in_real_and_another_batch() -> None:
    w = await source_to_master_world()
    report_engines(w, crane=650)
    await complete(w, await open_wo(w, [CRANE_A]))
    for cutover in ({"context": "REAL"}, {"batch": "SYN-RT1-OTHER-BATCH"}):
        service = due_service(w, current_source({("ENGINE_HOUR", CRANE_ENG): 700}), **cutover)
        one = await http_get(f"/pm/due/vehicles/{VEH}", service)
        assert one.status_code == 200
        assert {k: one.json()[k] for k in ("state", "assignments", "plans", "sets")} == {
            "state": "MASTER_NOT_ACTIVE", "assignments": [], "plans": [], "sets": []}
        fleet = await http_get("/pm/due/vehicles", service)
        assert {v["state"] for v in fleet.json()["items"]} == {"MASTER_NOT_ACTIVE"}
        assert PLAN not in fleet.text and CRANE_A not in fleet.text and TEST_SCOPE.test_batch_id not in fleet.text
    unconfigured = await http_get(f"/pm/due/vehicles/{VEH}", due_service(w, context=None))
    assert unconfigured.status_code == 503
