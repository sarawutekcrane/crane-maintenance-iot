"""R8 PRE-UAT (Owner source approval Rev 1, workstream A) — TEST master records on the Mock
repository (Access Management mode, per-employee TEST grant can_test_manage_master_records).
Created records land in the stores the existing reads use; edits only on TEST rows;
replay / duplicates / validation / permissions / REAL 409 / Sheets 501."""
from __future__ import annotations

import uuid

import pytest

from app.domain.master_records import MasterRecordService, entity_of
from app.errors import ApiError
from tests import test_access_management as am

API = am.API
MGR, CLERK = am.MGR, am.CLERK


@pytest.fixture(autouse=True)
def am_env(monkeypatch):
    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)


async def granted_store():
    store = am.repo()
    assert (await am.grant(store, MGR, am.employee(MGR), {"can_view": True,
                                                          "can_test_manage_master_records": True})).status_code == 200
    return store


async def create(store, entity, body, *, user=MGR, request_id="auto"):
    return await am.http("POST", f"{API}/master-records/{entity}", store, user, json=body, request_id=request_id)


async def test_create_every_master_type_and_see_it_in_the_existing_reads() -> None:
    store = await granted_store()
    model = await create(store, "models", {"model_code": "T-MDL-1", "model_name": "รุ่นทดสอบใหม่",
                                           "component_roles": ["CARRIER_ENGINE", "PTO"]})
    assert model.status_code == 200, model.text
    model_id = model.json()["record_id"]
    assert model_id.startswith("MODEL-TEST-")
    vehicle = await create(store, "vehicles", {"machine_no": "T/9001", "model_id": model_id,
                                               "operational_status": "READY"})
    assert vehicle.status_code == 200, vehicle.text
    vid = vehicle.json()["record_id"]
    detail = await am.http("GET", f"{API}/vehicles/{vid}", store, MGR, request_id=None)
    assert detail.status_code == 200 and detail.json()["vehicle"]["machine_no"] == "T/9001"
    assert detail.json()["model"]["model_id"] == model_id
    assert len(detail.json()["components"]) == 2  # components follow the model roles
    ref = await store.read_vehicle_reference()
    assert [r.scope for r in ref.rows if r.values["vehicle_id"] == vid] == ["TEST"]
    for entity, body in (
        ("equipment", {"equipment_code": "T-EQ-1", "name": "เครื่องมือทดสอบ", "category": "WELDING",
                       "operational_status": "READY"}),
        ("branches", {"branch_name": "สาขาทดสอบใหม่"}),
        ("departments", {"department_name_th": "แผนกทดสอบใหม่"}),
        ("personnel", {"first_name": "ทดสอบ", "last_name": "สร้างใหม่", "position": "ช่าง"}),
        ("technicians", {"first_name": "ช่าง", "last_name": "สร้างใหม่"}),
    ):
        response = await create(store, entity, body)
        assert response.status_code == 200, (entity, response.text)
        listed = await am.http("GET", f"{API}/master-records/{entity}", store, MGR, request_id=None)
        row = next(r for r in listed.json()["items"] if r.values() and response.json()["record_id"] in r.values())
        assert row["scope"] == "TEST"
    history = await am.http("GET", f"{API}/master-records/vehicles/{vid}/history", store, MGR, request_id=None)
    assert [e["action"] for e in history.json()["events"]] == ["CREATE"]


async def test_edit_only_test_records_and_record_previous_values() -> None:
    store = await granted_store()
    created = await create(store, "departments", {"department_name_th": "แผนกแก้ไขได้"})
    dept = created.json()["record_id"]
    edited = await am.http("PATCH", f"{API}/master-records/departments/{dept}", store, MGR,
                           json={"department_name_th": "แผนกแก้ไขแล้ว"})
    assert edited.status_code == 200 and edited.json()["action"] == "UPDATE"
    same = await am.http("PATCH", f"{API}/master-records/departments/{dept}", store, MGR,
                         json={"department_name_th": "แผนกแก้ไขแล้ว"})
    assert same.json()["action"] == "NO_CHANGE"
    history = (await am.http("GET", f"{API}/master-records/departments/{dept}/history", store, MGR,
                             request_id=None)).json()["events"]
    assert [e["action"] for e in history] == ["CREATE", "UPDATE"] and "แผนกแก้ไขได้" in history[1]["previous_json"]
    real = await am.http("PATCH", f"{API}/master-records/departments/DEPT-TEST-001", store, MGR,
                         json={"department_name_th": "x"})
    assert am.code(real) == (409, "MASTER_RECORD_NOT_TEST_SCOPED")
    model = await am.http("PATCH", f"{API}/master-records/models/MODEL-0002", store, MGR, json={"model_name": "x"})
    assert am.code(model) == (409, "MASTER_RECORD_NOT_TEST_SCOPED")
    vehicle = await am.http("PATCH", f"{API}/master-records/vehicles/VEH-1046", store, MGR, json={"machine_no": "x"})
    assert am.code(vehicle) == (409, "MASTER_RECORD_EDIT_NOT_SUPPORTED")
    unknown = await am.http("PATCH", f"{API}/master-records/departments/{dept}", store, MGR, json={"is_active": "F"})
    assert am.code(unknown) == (422, "VALIDATION_ERROR")
    missing = await am.http("PATCH", f"{API}/master-records/departments/DEPT-NOPE", store, MGR,
                            json={"department_name_th": "x"})
    assert am.code(missing) == (404, "MASTER_RECORD_NOT_FOUND")


async def test_validation_duplicates_and_replay() -> None:
    store = await granted_store()
    assert am.code(await create(store, "vehicles", {"machine_no": "X", "model_id": "MODEL-NOPE",
                                                    "operational_status": "READY"})) == (422, "MODEL_NOT_FOUND")
    assert am.code(await create(store, "vehicles", {"machine_no": "X", "model_id": "MODEL-0002",
                                                    "operational_status": "DRIVING"})) == (422, "VALIDATION_ERROR")
    assert am.code(await create(store, "vehicles", {"machine_no": "", "model_id": "MODEL-0002",
                                                    "operational_status": "READY"})) == (422, "VALIDATION_ERROR")
    assert am.code(await create(store, "models", {"model_code": "A", "model_name": "B",
                                                  "component_roles": ["WINGS"]})) == (422, "VALIDATION_ERROR")
    assert am.code(await create(store, "personnel", {"first_name": "a", "last_name": "b", "user_id": "U"})) == \
        (422, "VALIDATION_ERROR")  # no account linking here (R11)
    assert am.code(await create(store, "nonsense", {})) == (404, "MASTER_ENTITY_UNKNOWN")
    existing = store._vehicles["VEH-1046"].machine_no
    assert am.code(await create(store, "vehicles", {"machine_no": existing, "model_id": "MODEL-0002",
                                                    "operational_status": "READY"})) == (409, "MASTER_RECORD_DUPLICATE")
    rq = str(uuid.uuid4())
    body = {"branch_name": "สาขาเล่นซ้ำ"}
    first = await create(store, "branches", body, request_id=rq)
    again = await create(store, "branches", body, request_id=rq)
    assert again.json()["replayed"] is True and again.json()["record_id"] == first.json()["record_id"]
    assert sum(1 for b in store._branch_master if b["branch_name"] == "สาขาเล่นซ้ำ") == 1
    assert am.code(await create(store, "branches", {"branch_name": "อื่น"}, request_id=rq)) == (409, "REQUEST_ID_REUSED")
    assert am.code(await create(store, "branches", body)) == (409, "MASTER_RECORD_DUPLICATE")
    no_id = await am.http("POST", f"{API}/master-records/branches", store, MGR, json=body, request_id=None)
    assert am.code(no_id) == (422, "REQUEST_ID_REQUIRED")


async def test_permissions_and_mode_isolation() -> None:
    store = am.repo()
    await am.grant(store, MGR, am.employee(CLERK), {"can_view": True})
    refused = await create(store, "branches", {"branch_name": "x"}, user=CLERK)
    assert am.code(refused) == (403, "PREUAT_ACTION_NOT_AUTHORIZED")
    root = await create(store, "branches", {"branch_name": "x"}, user=MGR)
    assert root.status_code == 403  # root holds no TEST grant automatically
    assert (await am.http("GET", f"{API}/master-records/branches", store, None, request_id=None)).status_code == 403
    spec = entity_of("branches")
    with pytest.raises(ApiError) as real:
        await MasterRecordService(store, "REAL", "", mock_repository=True).list_records(spec)
    assert (real.value.status_code, real.value.code) == (409, "MASTER_RECORD_REAL_NOT_ENABLED")
    with pytest.raises(ApiError) as sheets:
        await MasterRecordService(store, "TEST", "B", mock_repository=False).list_records(spec)
    assert sheets.value.status_code == 501


async def test_legacy_admin_role_cannot_create(monkeypatch) -> None:
    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "false")
    from app.repositories.mock.repository import MockRepository

    response = await am.http("POST", f"{API}/master-records/branches", MockRepository(), "USR-ADMIN", role="ADMIN",
                             json={"branch_name": "x"})
    assert am.code(response) == (403, "PREUAT_ACTION_NOT_AUTHORIZED")


# Second independent review (2026-11-18): record + audit are one unit ---------------------------------


def _parity(store) -> None:
    """Every CREATE audit row has its record (no ghost history)."""
    created = store._preuat_created
    for row in store._preuat_journals.get("MASTER_AUDIT", []):
        if row["action"] == "CREATE":
            assert row["record_id"] in created.get(row["entity"], set()), row


async def test_a_failed_record_write_leaves_no_audit_and_the_same_request_can_be_retried(monkeypatch) -> None:
    from app.repositories.base import RepositoryConcurrentChangeError

    store = await granted_store()
    original = store.create_preuat_master_record
    failures = {"n": 0}

    async def failing(entity, values, *, test_batch_id):
        failures["n"] += 1
        if failures["n"] == 1:
            raise RepositoryConcurrentChangeError("injected: id taken")
        if failures["n"] == 2:
            raise RuntimeError("injected: storage failure")
        return await original(entity, values, test_batch_id=test_batch_id)

    monkeypatch.setattr(store, "create_preuat_master_record", failing)
    rq = str(uuid.uuid4())
    body = {"branch_name": "สาขาล้มเหลวกลางทาง"}
    first = await create(store, "branches", body, request_id=rq)
    assert am.code(first) == (409, "MASTER_RECORD_CONCURRENT_CHANGE")
    assert store._preuat_journals.get("MASTER_AUDIT", []) == []
    second = await create(store, "branches", body, request_id=rq)
    assert second.status_code == 500 and store._preuat_journals.get("MASTER_AUDIT", []) == []
    third = await create(store, "branches", body, request_id=rq)
    assert third.status_code == 200 and third.json()["replayed"] is False
    again = await create(store, "branches", body, request_id=rq)
    assert again.json()["replayed"] is True and again.json()["record_id"] == third.json()["record_id"]
    assert sum(1 for b in store._branch_master if b["branch_name"] == body["branch_name"]) == 1
    assert [r["action"] for r in store._preuat_journals["MASTER_AUDIT"]] == ["CREATE"]
    _parity(store)


async def test_a_concurrent_audit_append_writes_neither_record_nor_audit(monkeypatch) -> None:
    store = await granted_store()
    original = store.list_preuat_master_records

    async def racing(entity):
        rows = await original(entity)
        # another change lands between this request's audit read and its commit
        store._preuat_journals.setdefault("MASTER_AUDIT", []).append({"event_id": "OTHER", "action": "OTHER",
                                                                       "entity": "X", "record_id": "X",
                                                                       "request_id": "x", "fingerprint": "x"})
        return rows

    monkeypatch.setattr(store, "list_preuat_master_records", racing)
    response = await create(store, "departments", {"department_name_th": "แผนกชนกัน"})
    assert am.code(response) == (409, "MASTER_RECORD_CONCURRENT_CHANGE")
    monkeypatch.setattr(store, "list_preuat_master_records", original)
    assert not any(d.get("department_name_th") == "แผนกชนกัน" for d in store._department_master)
    assert [r["action"] for r in store._preuat_journals["MASTER_AUDIT"]] == ["OTHER"]


async def test_a_failed_update_leaves_no_update_audit(monkeypatch) -> None:
    store = await granted_store()
    dept = (await create(store, "departments", {"department_name_th": "แผนกก่อนแก้"})).json()["record_id"]

    async def failing(entity, record_id, values):
        raise RuntimeError("injected: update failure")

    monkeypatch.setattr(store, "update_preuat_master_record", failing)
    response = await am.http("PATCH", f"{API}/master-records/departments/{dept}", store, MGR,
                             json={"department_name_th": "แผนกหลังแก้"})
    assert response.status_code == 500
    assert [r["action"] for r in store._preuat_journals["MASTER_AUDIT"]] == ["CREATE"]
    assert any(d.get("department_name_th") == "แผนกก่อนแก้" for d in store._department_master)
    _parity(store)
