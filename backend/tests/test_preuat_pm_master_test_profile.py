"""R8 PRE-UAT — PM Master TEST profile (Owner Consolidated Source Expansion Gate 2026-11-18, SG-PM).

Synthetic Mock/TEST only (Access Management mode, per-employee TEST grants). Proves:
- the profile exists ONLY with PM_MASTER_TEST_PROFILE=true (default app: 404 / no route; REAL / Sheets refused);
- Master authority comes only from the explicit grants — root, ADMIN, roles and can_manage_pm never suffice;
- preview -> REVIEW (meter decision) -> publish -> model-variant approval -> assignment -> PM Due -> open a
  Master-sourced PM Work Order, with replay, stale-revision and permission refusals at each step;
- distinct CARRIER / CRANE / ODOMETER Sets; the owner case 650 h + 600 h -> next 1250 h (with a TEST-only fake
  verified meter source, as the existing B1 Due tests do — the application itself has no IoT source, so in
  the app a completed Set honestly stays UNKNOWN; R9).
Not PostgreSQL / production evidence."""
from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.domain import authz
from app.domain import pm_master_test_profile as profile
from app.errors import ApiError
from app.repositories.mock.repository import MockRepository
from tests import test_access_management as am

API = am.API
BASE = f"{API}/pm-master-test"
MGR, OPM, CLERK = am.MGR, am.OPM, am.CLERK
SETS_A = ["UAT8-V-A|CARRIER|A", "UAT8-V-A|CARRIER|KM1", "UAT8-V-A|CRANE|A"]
METER_DECISION = {"meter_type": "ENGINE_HOUR", "driving_component": "CARRIER_ENGINE"}


@pytest.fixture(autouse=True)
def profile_env(monkeypatch):
    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock"), ("PM_MASTER_TEST_PROFILE", "true")):
        monkeypatch.setenv(name, value)


def store_with_profile() -> MockRepository:
    return MockRepository(access_management_seed=True, fixture_profile="uat_r8")


async def http(method, path, store, user, **kw):
    return await am.http(method, path, store, user, **kw)


async def granted(store) -> None:
    assert (await am.grant(store, MGR, am.employee(MGR), {"can_view": True, "can_test_pm_master_publish": True,
                                                          "can_manage_pm": True})).status_code == 200
    assert (await am.grant(store, MGR, am.employee(OPM), {"can_view": True,
                                                          "can_test_pm_master_assign": True})).status_code == 200


async def published(store) -> tuple[dict, dict]:
    preview = (await http("POST", f"{BASE}/previews", store, MGR, json={"reason": "ลงทะเบียนต้นทางทดสอบ"})).json()
    [entry] = [e for e in preview["ledger"] if e["action"] == "REVIEW"]
    resolved = await http("POST", f"{BASE}/previews/{preview['preview_id']}/reviews", store, MGR, json={
        "expected_source_digest": preview["source_digest"], "entry_id": entry["entry_id"], "outcome": "RESOLVE_METER",
        "values": METER_DECISION, "evidence": "ตรวจทานเอกสารสังเคราะห์ (TEST)"})
    assert resolved.status_code == 200, resolved.text
    pub = await http("POST", f"{BASE}/publications", store, MGR, json={
        "preview_id": preview["preview_id"], "expected_source_digest": preview["source_digest"],
        "expected_revision": 0, "reason": "เผยแพร่แผนทดสอบ"})
    assert pub.status_code == 200, pub.text
    return preview, pub.json()["revision"]


async def approved_and_assigned(store, preview) -> None:
    variant = await http("POST", f"{BASE}/variant-approvals", store, MGR, json={
        "model_id": "UAT8-MDL-A", "model_variant": "UAT8-V-A", "expected_version": 0,
        "preview_id": preview["preview_id"], "expected_source_digest": preview["source_digest"],
        "source_rows": ["vehicle_pm_mapping!row:2"], "evidence": "ตารางจับคู่สังเคราะห์ (TEST)", "reason": "อนุมัติรุ่น"})
    assert variant.status_code == 200, variant.text
    assigned = await http("POST", f"{BASE}/assignments", store, OPM, json={
        "vehicle_id": "UAT8-VEH-01", "assembly": "", "plan_code": profile.PLAN_CODE, "expected_version": 0,
        "reason": "กำหนดแผนทดสอบ"})
    assert assigned.status_code == 200, assigned.text


async def test_without_the_profile_flag_nothing_exists(monkeypatch) -> None:
    monkeypatch.setenv("PM_MASTER_TEST_PROFILE", "false")
    store = store_with_profile()
    for method, path in (("GET", f"{BASE}/status"), ("POST", f"{BASE}/previews")):
        response = await http(method, path, store, MGR, json={"reason": "x"})
        assert response.status_code in (404, 405), response.text  # no such route in the default application


def test_the_per_request_guard_refuses_every_non_test_composition() -> None:
    from app.config import DataRepositoryMode

    for settings in (SimpleNamespace(pm_master_test_profile=False, access_management_mode=True,
                                     data_repository=DataRepositoryMode.MOCK, registry_context_effective="TEST"),
                     SimpleNamespace(pm_master_test_profile=True, access_management_mode=False,
                                     data_repository=DataRepositoryMode.MOCK, registry_context_effective="TEST"),
                     SimpleNamespace(pm_master_test_profile=True, access_management_mode=True,
                                     data_repository=DataRepositoryMode.GOOGLE_SHEETS, registry_context_effective="TEST"),
                     SimpleNamespace(pm_master_test_profile=True, access_management_mode=True,
                                     data_repository=DataRepositoryMode.MOCK, registry_context_effective="REAL")):
        with pytest.raises(ApiError) as refused:
            profile.require_profile_enabled(settings)
        assert (refused.value.status_code, refused.value.code) == (404, "PM_MASTER_TEST_PROFILE_DISABLED")


def test_a_real_scoped_master_refuses_the_test_authorizer() -> None:
    from app.domain.pm_master import MasterDataScope, PmMasterMockStore, PmMasterService

    with pytest.raises(ApiError) as refused:
        PmMasterService(PmMasterMockStore(data_scope=MasterDataScope.real()), authorizer=profile.test_profile_authorizer)
    assert refused.value.code == "PM_MASTER_AUTHORITY_UNPROVEN"


async def test_master_authority_comes_only_from_the_explicit_test_grants() -> None:
    store = store_with_profile()
    # Root holder without the grant, as TECHNICIAN or ADMIN role, with can_manage_pm: all refused.
    assert (await am.grant(store, MGR, am.employee(MGR), {"can_view": True, "can_manage_pm": True})).status_code == 200
    for role in ("TECHNICIAN", "ADMIN"):
        refused = await http("POST", f"{BASE}/previews", store, MGR, role=role, json={"reason": "x"})
        assert am.code(refused) == (403, "PM_MASTER_AUTHORITY_UNPROVEN")
    assert (await http("GET", f"{BASE}/status", store, None, request_id=None)).status_code == 403
    no_id = await http("POST", f"{BASE}/previews", store, MGR, json={"reason": "x"}, request_id=None)
    assert am.code(no_id) == (422, "REQUEST_ID_REQUIRED")
    unverified = await http("POST", f"{BASE}/previews", store, "USR-NOBODY", role="ADMIN", json={"reason": "x"})
    assert unverified.status_code == 403  # D6: a write needs a verified employee
    await granted(store)
    preview, _ = await published(store)
    # The publisher cannot assign; the assigner cannot publish.
    by_publisher = await http("POST", f"{BASE}/assignments", store, MGR, json={
        "vehicle_id": "UAT8-VEH-01", "plan_code": profile.PLAN_CODE, "expected_version": 0, "reason": "x"})
    assert am.code(by_publisher) == (403, "PM_MASTER_AUTHORITY_UNPROVEN")
    by_assigner = await http("POST", f"{BASE}/previews", store, OPM, json={"reason": "x"})
    assert am.code(by_assigner) == (403, "PM_MASTER_AUTHORITY_UNPROVEN")
    assert preview["source_file"] == profile.SOURCE_FILE


async def test_preview_review_publish_variant_assign_due_and_open_a_work_order() -> None:
    store = store_with_profile()
    await granted(store)
    preview = (await http("POST", f"{BASE}/previews", store, MGR, json={"reason": "ลงทะเบียน"})).json()
    review = [e for e in preview["ledger"] if e["action"] == "REVIEW"]
    assert [(e["issue"], e["resolved"]) for e in review] == [("METER_COMPONENT_UNRESOLVED", False)]
    blocked = await http("POST", f"{BASE}/publications", store, MGR, json={
        "preview_id": preview["preview_id"], "expected_source_digest": preview["source_digest"],
        "expected_revision": 0, "reason": "ยังไม่ตรวจทาน"})
    assert am.code(blocked) == (422, "PM_MASTER_VALIDATION_FAILED")  # an unresolved REVIEW blocks the Plan
    rq = str(uuid.uuid4())
    body = {"expected_source_digest": preview["source_digest"], "entry_id": review[0]["entry_id"],
            "outcome": "RESOLVE_METER", "values": METER_DECISION, "evidence": "ตรวจทาน (TEST)"}
    first = await http("POST", f"{BASE}/previews/{preview['preview_id']}/reviews", store, MGR, json=body, request_id=rq)
    again = await http("POST", f"{BASE}/previews/{preview['preview_id']}/reviews", store, MGR, json=body, request_id=rq)
    assert first.json()["resolution_id"] == again.json()["resolution_id"]  # replay
    bad_digest = await http("POST", f"{BASE}/previews/{preview['preview_id']}/reviews", store, MGR,
                            json={**body, "expected_source_digest": "0" * 64})
    assert am.code(bad_digest) == (422, "PM_MASTER_REVIEW_INVALID")
    pub = await http("POST", f"{BASE}/publications", store, MGR, json={
        "preview_id": preview["preview_id"], "expected_source_digest": preview["source_digest"],
        "expected_revision": 0, "reason": "เผยแพร่"})
    revision = pub.json()["revision"]
    sets = {s["set_key"]: s for s in revision["sets"]}
    assert (revision["revision_number"], sorted(k for k in sets if k.startswith("UAT8-V-A"))) == (1, SETS_A)
    assert (sets["UAT8-V-A|CARRIER|A"]["meter_type"], sets["UAT8-V-A|CARRIER|A"]["interval_value"]) == ("ENGINE_HOUR", 600)
    assert (sets["UAT8-V-A|CRANE|A"]["interval_value"], sets["UAT8-V-A|CARRIER|KM1"]["meter_type"]) == (600, "ODOMETER")
    stale = await http("POST", f"{BASE}/publications", store, MGR, json={
        "preview_id": preview["preview_id"], "expected_source_digest": preview["source_digest"],
        "expected_revision": 0, "reason": "ซ้ำ"})
    assert stale.status_code == 409  # stale expected revision, nothing published
    # Before the variant approval and assignment the vehicle has no proven Plan.
    unproven = (await http("GET", f"{BASE}/vehicles/UAT8-VEH-01/due", store, MGR, request_id=None)).json()
    assert unproven["sets"] == []
    await approved_and_assigned(store, preview)
    due = await http("GET", f"{BASE}/vehicles/UAT8-VEH-01/due", store, MGR, request_id=None)
    assert due.status_code == 200, due.text
    rows = {s["set_key"]: s for s in due.json()["sets"]}
    assert sorted(rows) == SETS_A  # never variant B's Set
    assert {(r["status"], r["diagnostic_code"]) for r in rows.values()} == {
        ("UNKNOWN", "NO_VERIFIED_ACTUAL_SET_COMPLETION")}  # nothing invented without a completion
    status = (await http("GET", f"{BASE}/status", store, MGR, request_id=None)).json()
    assert status["head_revision"]["revision_number"] == 1 and status["note_th"].startswith("โปรไฟล์ทดสอบ")
    rq = str(uuid.uuid4())
    opened = await http("POST", f"{BASE}/vehicles/UAT8-VEH-01/work-orders", store, MGR, request_id=rq,
                        json={"revision_number": 1, "selected_set_keys": SETS_A})
    assert opened.status_code == 200, opened.text
    replay = await http("POST", f"{BASE}/vehicles/UAT8-VEH-01/work-orders", store, MGR, request_id=rq,
                        json={"revision_number": 1, "selected_set_keys": SETS_A})
    assert replay.json()["work_order"]["pm_work_order_id"] == opened.json()["work_order"]["pm_work_order_id"]
    # The Work Order is an ordinary E01 V2 PM Work Order, readable through the existing route.
    job = opened.json()["work_order"]["pm_work_order_id"]
    existing = await http("GET", f"{API}/pm/work-orders/{job}", store, MGR, request_id=None)
    assert existing.status_code == 200 and existing.json()["work_order"]["asset_id"] == "UAT8-VEH-01"
    # Opening needs the existing can_manage_pm: the assigner (without it) is refused.
    no_pm = await http("POST", f"{BASE}/vehicles/UAT8-VEH-01/work-orders", store, OPM,
                       json={"revision_number": 1, "selected_set_keys": SETS_A})
    assert no_pm.status_code == 403
    # A vehicle that is not assigned cannot get a Master work order.
    unassigned = await http("POST", f"{BASE}/vehicles/UAT8-VEH-02/work-orders", store, MGR,
                            json={"revision_number": 1, "selected_set_keys": SETS_A})
    assert am.code(unassigned)[0] in (409, 422)


async def test_owner_case_completed_at_650_with_600_interval_is_due_at_1250() -> None:
    """Service level with a TEST-only fake verified meter source (as the B1 Due suite does)."""
    from app.domain.meter_service import MeterService
    from app.domain.pm_service import PmService
    from app.repositories.mock.uat_fixture_profile import apply_fixture_profile
    from tests.pm_e01_support import PERFORMED, U1, ctx, current_set_id, manager, repo_with, rid, save, start
    from tests.test_pm_submit_meter_anchor import FakeIotSource
    from tests.test_technician_assignment_batch_r2f_h1 import BATCH, T1, T2, assign, body, cut
    from app.domain.technician_assignment import PM

    repo = repo_with()
    apply_fixture_profile(repo, "uat_r8")
    master = profile.master_for(repo, BATCH)
    editor = SimpleNamespace(request_id="r", user_id="EDITOR", personnel_id="PER-E", access=object(),
                             capabilities=frozenset({authz.CAN_VIEW, authz.CAN_TEST_PM_MASTER_PUBLISH}))
    assigner = SimpleNamespace(request_id="r", user_id="ASSIGNER", personnel_id="PER-A", access=object(),
                               capabilities=frozenset({authz.CAN_VIEW, authz.CAN_TEST_PM_MASTER_ASSIGN}))
    reg = await master.register_preview(editor, workbook=profile.synthetic_workbook(), source_file=profile.SOURCE_FILE,
                                        reason="ทดสอบ", request_id=rid())
    [entry] = [e for e in reg.preview.ledger if e.action == "REVIEW"]
    await master.record_review(editor, preview_id=reg.preview_id, expected_source_digest=reg.source_digest,
                               entry_id=entry.entry_id, outcome="RESOLVE_METER", values=METER_DECISION,
                               evidence="ตรวจทานกับเอกสารต้นฉบับสังเคราะห์แล้ว (TEST)", request_id=rid())
    rev = (await master.publish(editor, plan_code=profile.PLAN_CODE, expected_revision=0, preview_id=reg.preview_id,
                                expected_source_digest=reg.source_digest, reason="ทดสอบ", request_id=rid())).revision
    await master.approve_model_variant(editor, model_id="UAT8-MDL-A", plan_code=profile.PLAN_CODE,
                                       model_variant="UAT8-V-A", expected_version=0, preview_id=reg.preview_id,
                                       expected_source_digest=reg.source_digest,
                                       source_rows=["vehicle_pm_mapping!row:2"], evidence="ตรวจทานกับเอกสารต้นฉบับสังเคราะห์แล้ว (TEST)", reason="ทดสอบ",
                                       request_id=rid())
    await master.set_assignment(assigner, vehicle_id="UAT8-VEH-01", plan_code=profile.PLAN_CODE, expected_version=0,
                                reason="ทดสอบ", request_id=rid())
    crane_engine = "UAT8-CMP-01-2"
    source = FakeIotSource()
    source.report("ENGINE_HOUR", 650, component_id=crane_engine, vehicle_id="UAT8-VEH-01")
    svc = PmService(repo, MeterService(repo, iot_meter_source=source), assignment_cutover=cut())
    detail = await svc.open_master_work_order(master, manager(authz.CAN_VIEW), asset_id="UAT8-VEH-01",
                                              plan_code=profile.PLAN_CODE, revision_number=rev.revision_number,
                                              selected_set_keys=["UAT8-V-A|CRANE|A"], request_id=rid())
    job = detail.work_order.pm_work_order_id
    await assign(repo, job, body(T1, T2), kind=PM)
    await start(svc, job)
    for task in repo._pm_work_orders[job].scope_task_ids:
        await save(svc, job, task, PERFORMED)
    await svc.submit_for_review(job, ctx(U1), request_id=rid(), expected_set_id=await current_set_id(repo, job))
    await svc.close_after_review(job, manager(), request_id=rid())
    viewer = ctx("SYN-VIEWER", authz.CAN_VIEW)
    for current, expected in ((1249, "NOT_DUE"), (1250, "DUE")):
        now = FakeIotSource()
        now.report("ENGINE_HOUR", current, component_id=crane_engine, vehicle_id="UAT8-VEH-01",
                   ago=timedelta(seconds=5), received_ago=timedelta(seconds=1))
        reader = PmService(repo, MeterService(repo, iot_meter_source=now), assignment_cutover=cut())
        due = await profile.pm_with_master(reader, master, viewer).read_vehicle_pm_due(viewer, "UAT8-VEH-01")
        [crane] = [s for s in due.sets if s.set_key == "UAT8-V-A|CRANE|A"]
        assert (crane.status, crane.next_due, crane.last_completed_meter) == (expected, 1250.0, 650.0)
        # The other Sets are independent: no shared credit from the crane Set.
        others = {s.set_key: s.status for s in due.sets if s.set_key != "UAT8-V-A|CRANE|A"}
        assert set(others.values()) == {"UNKNOWN"}
