"""Access Management + L11 (Owner-approved Mock implementation).

Every row is SYNTHETIC mock data of the Access Management seed (loaded only in
Access Management mode). Mock results are not production evidence: the event-log
guard is single-process (R11) and Sheets mode answers 501.
"""
from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.access_management import build_access_event_row
from app.repositories.base import RepositoryFeatureNotImplementedError
from app.repositories.mock import seed_data
from app.repositories.mock.repository import MockRepository

API = "/api/v1"
MGR, CLERK, OPM, DRV1, DRV2, RESIGNED = ("USR-TEST-AM-MGR", "USR-TEST-AM-CLERK", "USR-TEST-AM-OPM",
                                         "USR-TEST-AM-DRV1", "USR-TEST-AM-DRV2", "USR-TEST-AM-RESIGNED")
TECH1, TECH2 = "USR-TEST-911", "USR-TEST-912"
P = {MGR: "PER-TEST-AM-MGR", CLERK: "PER-TEST-AM-CLERK", OPM: "PER-TEST-AM-OPM", DRV1: "PER-TEST-AM-DRV1",
     DRV2: "PER-TEST-AM-DRV2", RESIGNED: "PER-TEST-AM-RESIGNED", TECH1: "PER-TEST-911", TECH2: "PER-TEST-912"}
OPS, MNT = seed_data.ACCESS_OPERATION_DEPARTMENT, seed_data.ACCESS_MAINTENANCE_DEPARTMENT


@pytest.fixture(autouse=True)
def access_mode(monkeypatch):
    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "true")
    monkeypatch.setenv("DEV_AUTH_MODE", "true")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATA_REPOSITORY", "mock")


def repo() -> MockRepository:
    return MockRepository(access_management_seed=True)


async def http(method: str, path: str, store, user: str | None, *, role: str = "TECHNICIAN", json=None,
               request_id: str | None = "auto", params=None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: store
    headers = {"X-Dev-Role": role}
    if user is not None:
        headers["X-Dev-User-Id"] = user
    if request_id is not None:
        headers["X-Request-Id"] = str(uuid.uuid4()) if request_id == "auto" else request_id
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers, params=params)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def code(response) -> tuple[int, str]:
    body = response.json()
    return response.status_code, body["error"]["code"] if "error" in body else body.get("detail", "")


async def caps(store, user: str) -> list[str]:
    return (await http("GET", f"{API}/me", store, user, request_id=None)).json()["capabilities"]


async def revision(store) -> int:
    return (await http("GET", f"{API}/access/me", store, MGR, request_id=None)).json()["revision"]


async def grant(store, actor: str, target: dict, changes: dict, *, reason: str = "ทดสอบ",
                request_id: str = "auto", expected: int | None = None):
    body = {"target": target, "changes": changes, "reason_th": reason,
            "expected_revision": await revision(store) if expected is None else expected}
    return await http("POST", f"{API}/access/grants", store, actor, json=body, request_id=request_id)


def employee(user: str) -> dict:
    return {"kind": "EMPLOYEE", "personnel_id": P[user]}


def department(dept: str) -> dict:
    return {"kind": "DEPARTMENT", "department_id": dept}


async def delegate(store, actor: str, delegate_user: str, dept: str, capabilities: list[str]):
    return await http("POST", f"{API}/access/delegations", store, actor, json={
        "delegate_personnel_id": P[delegate_user], "department_id": dept, "capabilities": capabilities,
        "reason_th": "มอบอำนาจ", "expected_revision": await revision(store)})


# 1 / 2 ----------------------------------------------------------------------


async def test_am_01_every_employee_starts_without_permissions_and_dev_roles_grant_nothing() -> None:
    store = repo()
    for user in (MGR, CLERK, OPM, DRV1, DRV2, RESIGNED, TECH1, TECH2):
        for role in ("TECHNICIAN", "MAINTENANCE", "ADMIN", "MAINTENANCE_MANAGER"):
            assert await caps(store, user) == [] or role != "TECHNICIAN"
            assert (await http("GET", f"{API}/me", store, user, role=role, request_id=None)).json()["capabilities"] == []
    blocked = await http("POST", f"{API}/repairs", store, MGR, role="ADMIN",
                         json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"})
    assert blocked.status_code == 403  # the development role table carries nothing over


async def test_am_02_root_authority_comes_only_from_the_position_appointment() -> None:
    store = repo()
    me = (await http("GET", f"{API}/access/me", store, MGR, request_id=None)).json()
    assert me["is_root"] is True and me["personnel_id"] == P[MGR]
    # A copied free-text position, a client role or an unknown account never confers root.
    for row in store._personnel_master:
        if row["personnel_id"] == P[CLERK]:
            row["position"] = "ผู้จัดการแผนกซ่อมบำรุง"
    for user, role in ((CLERK, "TECHNICIAN"), (CLERK, "MAINTENANCE_MANAGER"), ("USR-NOBODY", "ADMIN")):
        assert (await http("GET", f"{API}/access/me", store, user, role=role, request_id=None)).json()["is_root"] is False
    assert (await grant(store, CLERK, employee(DRV1), {"can_view": True})).status_code == 403


async def test_am_02b_root_handover_moves_the_authority_and_keeps_history() -> None:
    store = repo()
    assert (await grant(store, MGR, employee(DRV1), {"can_view": True})).status_code == 200
    self_appoint = await http("POST", f"{API}/access/root/appointment", store, MGR,
                              json={"personnel_id": P[MGR], "reason_th": "x", "expected_revision": await revision(store)})
    assert self_appoint.status_code == 403
    by_other = await http("POST", f"{API}/access/root/appointment", store, CLERK,
                          json={"personnel_id": P[CLERK], "reason_th": "x", "expected_revision": await revision(store)})
    assert by_other.status_code == 403
    inactive = await http("POST", f"{API}/access/root/appointment", store, MGR,
                          json={"personnel_id": P[RESIGNED], "reason_th": "x", "expected_revision": await revision(store)})
    assert code(inactive) == (409, "ACCESS_EMPLOYEE_NOT_ELIGIBLE")
    handover = await http("POST", f"{API}/access/root/appointment", store, MGR,
                          json={"personnel_id": P[CLERK], "reason_th": "ส่งมอบตำแหน่ง",
                                "expected_revision": await revision(store)})
    assert handover.status_code == 200 and handover.json()["holder"]["personnel_id"] == P[CLERK]
    assert (await grant(store, MGR, employee(DRV2), {"can_view": True})).status_code == 403  # former holder
    assert (await grant(store, CLERK, employee(DRV2), {"can_view": True})).status_code == 200  # new holder
    audit = (await http("GET", f"{API}/access/audit", store, CLERK, request_id=None)).json()
    first = next(e for e in audit if e["kind"] == "GRANT" and e["personnel_id"] == P[DRV1])
    assert first["actor_personnel_id"] == P[MGR] and first["actor_name_snapshot"].startswith("ผู้จัดการซ่อม")


async def test_am_02c_technical_recovery_only_when_no_valid_holder_exists() -> None:
    store = repo()
    body = lambda: {"personnel_id": P[CLERK], "reason_th": "กู้คืน", "expected_revision": len(store._access_events)}
    assert (await http("POST", f"{API}/access/root/appointment", store, "USR-RECOVERY", role="ADMIN",
                       json=body())).status_code == 403  # a valid holder exists: no takeover
    for row in store._personnel_master:
        if row["personnel_id"] == P[MGR]:
            row["active_status"] = "INACTIVE"
    assert (await http("GET", f"{API}/access/me", store, MGR, request_id=None)).json()["is_root"] is False
    recovered = await http("POST", f"{API}/access/root/appointment", store, "USR-RECOVERY", role="ADMIN", json=body())
    assert recovered.status_code == 200 and recovered.json()["appointments"][-1]["mode"] == "RECOVERY"
    assert recovered.json()["appointments"][-1]["actor_user_id"] == "USR-RECOVERY"


# 3 / 4 / 5 / 6 ----------------------------------------------------------------


async def test_am_03_individual_on_off_applies_to_the_next_request() -> None:
    store = repo()
    assert (await grant(store, MGR, employee(DRV1), {"can_report_repair": True, "can_view": True})).status_code == 200
    assert await caps(store, DRV1) == ["can_report_repair", "can_view"]
    assert (await grant(store, MGR, employee(DRV1), {"can_view": False})).status_code == 200
    assert await caps(store, DRV1) == ["can_report_repair"]
    assert await caps(store, DRV2) == []


async def test_am_04_department_switch_changes_only_the_touched_capability_for_every_eligible_employee() -> None:
    store = repo()
    await grant(store, MGR, employee(DRV1), {"can_view": True})
    preview = await http("POST", f"{API}/access/grants/preview", store, MGR, json={
        "target": department(OPS), "changes": {"can_report_repair": True}, "expected_revision": await revision(store)})
    assert preview.json()["target_count"] == 3 and preview.json()["skipped_personnel_ids"] == [P[RESIGNED]]
    applied = await grant(store, MGR, department(OPS), {"can_report_repair": True})
    assert applied.status_code == 200, applied.text
    assert await caps(store, DRV1) == ["can_report_repair", "can_view"]  # untouched can_view preserved
    assert await caps(store, DRV2) == ["can_report_repair"] and await caps(store, OPM) == ["can_report_repair"]
    assert await caps(store, TECH1) == []  # another department untouched
    revoked = await grant(store, MGR, department(OPS), {"can_report_repair": False})
    assert revoked.json()["per_capability"] == [{"capability": "can_report_repair", "action": "REVOKE",
                                                 "changed": 3, "unchanged": 0}]
    assert await caps(store, DRV1) == ["can_view"]
    counts = (await http("GET", f"{API}/access/employees", store, MGR, request_id=None,
                         params={"department_id": OPS})).json()["capability_counts"]
    assert counts["can_view"] == 1 and counts["can_report_repair"] == 0


async def test_am_06_a_new_employee_never_inherits_an_earlier_bulk_grant() -> None:
    store = repo()
    await grant(store, MGR, department(OPS), {"can_report_repair": True})
    newcomer = copy.deepcopy(seed_data.SEED_ACCESS_PERSONNEL[3])
    newcomer.update(personnel_id="PER-TEST-AM-NEW", user_id="USR-TEST-AM-NEW", first_name="พนักงานใหม่")
    store._personnel_master.append(newcomer)
    history = copy.deepcopy(seed_data.seed_access_department_history()[-1])
    history.update(record_id="PDH-SEED-AM-NEW", event_id="PDH-SEED-AM-NEW", personnel_id="PER-TEST-AM-NEW",
                   request_id="seed-am-new", recorded_at=datetime.now(UTC).isoformat())
    store._personnel_department_history.append(history)
    assert await caps(store, "USR-TEST-AM-NEW") == []


# 7 / 8 / 9 / 10 / 11 / 19 -----------------------------------------------------


async def test_am_07_employees_without_authority_cannot_administer() -> None:
    store = repo()
    await grant(store, MGR, employee(DRV1), {"can_view": True, "can_view_access_audit": True})
    for user in (DRV1, CLERK, OPM, TECH1, "USR-UNKNOWN"):
        assert (await grant(store, user, employee(DRV2), {"can_view": True})).status_code == 403
        assert (await http("GET", f"{API}/access/employees", store, user, request_id=None,
                           params={"department_id": OPS})).status_code == 403
    assert (await http("GET", f"{API}/access/audit", store, DRV1, request_id=None)).status_code == 200  # read only


async def test_am_08_19_a_delegate_is_confined_to_the_department_and_the_list() -> None:
    store = repo()
    assert (await delegate(store, MGR, OPM, OPS, ["can_report_repair", "can_record_inspection"])).status_code == 200
    me = (await http("GET", f"{API}/access/me", store, OPM, request_id=None)).json()
    assert me["is_root"] is False and [d["department_id"] for d in me["delegations"]] == [OPS]
    assert (await grant(store, OPM, employee(DRV1), {"can_report_repair": True})).status_code == 200
    assert (await grant(store, OPM, department(OPS), {"can_record_inspection": True})).status_code == 200
    assert await caps(store, DRV2) == ["can_record_inspection"]
    assert await caps(store, OPM) == []  # the delegate's own permissions are never touched by a bulk change
    for target, changes in ((employee(DRV1), {"can_manage_repair": True}),   # outside the list
                            (employee(TECH1), {"can_report_repair": True}),   # outside the department
                            (department(MNT), {"can_report_repair": True}),   # outside the department
                            (employee(OPM), {"can_report_repair": True})):    # self
        assert (await grant(store, OPM, target, changes)).status_code == 403
    # A client-sent department on an employee target is ignored: the server derives it.
    spoof = await grant(store, OPM, {"kind": "EMPLOYEE", "personnel_id": P[TECH1], "department_id": OPS},
                        {"can_report_repair": True})
    assert spoof.status_code == 403
    assert (await http("GET", f"{API}/access/employees", store, OPM, request_id=None,
                       params={"department_id": MNT})).status_code == 403
    assert await caps(store, TECH1) == []


async def test_am_09_10_11_no_onward_delegation_and_revocation_is_immediate_but_keeps_grants() -> None:
    store = repo()
    created = (await delegate(store, MGR, OPM, OPS, ["can_report_repair"])).json()
    onward = await delegate(store, OPM, DRV1, OPS, ["can_report_repair"])
    assert onward.status_code == 403
    assert (await grant(store, OPM, employee(DRV1), {"can_report_repair": True})).status_code == 200
    revoke = await http("POST", f"{API}/access/delegations/{created['delegation_id']}/revocation", store, MGR,
                        json={"reason_th": "สิ้นสุดการมอบอำนาจ", "expected_revision": await revision(store)})
    assert revoke.status_code == 200 and revoke.json()["revoked"] is True and revoke.json()["effective"] is False
    assert (await grant(store, OPM, employee(DRV2), {"can_report_repair": True})).status_code == 403
    assert await caps(store, DRV1) == ["can_report_repair"]  # the third party keeps the legitimate grant
    again = await http("POST", f"{API}/access/delegations/{created['delegation_id']}/revocation", store, MGR,
                       json={"reason_th": "x", "expected_revision": await revision(store)})
    assert code(again) == (409, "ACCESS_DELEGATION_ALREADY_REVOKED")


# 12 / 13 ----------------------------------------------------------------------


async def test_am_12_13_a_department_transfer_revokes_every_permission_and_keeps_history() -> None:
    store = repo()
    await grant(store, MGR, employee(MGR), {"can_move_personnel_department": True})
    await grant(store, MGR, employee(DRV1), {"can_view": True, "can_report_repair": True})
    await delegate(store, MGR, DRV1, OPS, ["can_report_repair"])
    events_before = copy.deepcopy(store._access_events)
    moved = await http("POST", f"{API}/personnel/{P[DRV1]}/department-events", store, MGR, json={
        "operation": "TRANSFER", "department_id": MNT, "effective": {"mode": "NOW"},
        "expected_current_department_id": OPS, "reason_th": "ย้ายไปแผนกซ่อม"})
    assert moved.status_code == 200, moved.text
    assert await caps(store, DRV1) == []  # nothing of the new department is granted either
    me = (await http("GET", f"{API}/access/me", store, DRV1, request_id=None)).json()
    assert me["delegations"] == []
    assert store._access_events == events_before  # derived: no history rewritten, nothing deleted
    audit = (await http("GET", f"{API}/access/audit", store, MGR, request_id=None,
                        params={"personnel_id": P[DRV1]})).json()
    assert audit[0]["kind"] == "DEPARTMENT_TRANSFER_PERMISSIONS_RESET" and audit[0]["actor_user_id"] == MGR
    assert {e["kind"] for e in audit} >= {"GRANT", "DELEGATION_GRANT"}
    assert (await grant(store, MGR, employee(DRV1), {"can_view": True})).status_code == 200
    assert await caps(store, DRV1) == ["can_view"]  # re-granted afterwards by the manager


async def test_am_12b_a_transfer_without_the_permission_is_refused() -> None:
    store = repo()
    refused = await http("POST", f"{API}/personnel/{P[DRV1]}/department-events", store, CLERK, json={
        "operation": "TRANSFER", "department_id": MNT, "effective": {"mode": "NOW"}, "expected_current_department_id": OPS})
    assert refused.status_code == 403
    await grant(store, MGR, employee(CLERK), {"can_move_personnel_department": True})
    assert (await http("GET", f"{API}/access/me", store, CLERK, request_id=None)).json()["delegations"] == []
    assert (await grant(store, CLERK, employee(DRV2), {"can_view": True})).status_code == 403  # no admin power


# 14 / 15 ----------------------------------------------------------------------


async def test_am_14_15_inactive_employees_hold_nothing_and_revocation_beats_an_open_session() -> None:
    store = repo()
    assert code(await grant(store, MGR, employee(RESIGNED), {"can_view": True})) == (409, "ACCESS_EMPLOYEE_INACTIVE")
    store._access_events.append(build_access_event_row(
        event_id="ACE-INJECTED", kind="GRANT", personnel_id=P[RESIGNED], capability="can_report_repair",
        recorded_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat()))
    assert await caps(store, RESIGNED) == []
    await grant(store, MGR, employee(DRV1), {"can_report_repair": True})
    report = {"vehicle_id": "VEH-1046", "symptom_th": "เสียงดัง"}
    assert (await http("POST", f"{API}/repair-requests", store, DRV1, json=report)).status_code == 200
    await grant(store, MGR, employee(DRV1), {"can_report_repair": False})
    assert (await http("POST", f"{API}/repair-requests", store, DRV1, json=report)).status_code == 403


# 16 / 17 — L11 ------------------------------------------------------------------


async def _r3_finding(store) -> str:
    await grant(store, MGR, employee(TECH1), {"can_record_inspection": True, "can_view": True})
    form = (await http("GET", f"{API}/inspections/form", store, TECH1, request_id=None,
                       params={"asset_type": "VEHICLE", "asset_id": "VEH-1046"})).json()
    items = [{"item_id": e["item"]["item_id"], "result": "PASS"} for e in form["items"]]
    items[0].update(result="FAIL", remark="น้ำมันรั่ว")
    submitted = await http("POST", f"{API}/inspections", store, TECH1,
                           json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items})
    assert submitted.status_code == 200, submitted.text
    return submitted.json()["findings"][0]["finding_id"]


async def test_am_16_17_l11_finding_delegate_runs_finding_work_without_unrelated_authority() -> None:
    store = repo()
    finding = await _r3_finding(store)
    await grant(store, MGR, employee(CLERK), {"can_manage_finding_repair": True, "can_view": True})
    opened = await http("POST", f"{API}/repairs", store, CLERK, json={
        "asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "FINDING", "source_id": finding})
    assert opened.status_code == 200, opened.text
    rid = opened.json()["repair"]["repair_id"]
    team = {"primary_technician_id": "TEC-TEST-911", "collaborator_technician_ids": ["TEC-TEST-912"],
            "expected_current": None}
    assert (await http("POST", f"{API}/repairs/{rid}/technician-assignments", store, CLERK, json=team)).status_code == 200
    # No unrelated authority: MANUAL repairs, PM, closing / assigning non-Finding orders.
    manual = await http("POST", f"{API}/repairs", store, CLERK,
                        json={"asset_type": "VEHICLE", "asset_id": "VEH-1047", "source_type": "MANUAL"})
    assert manual.status_code == 403
    assert (await http("POST", f"{API}/pm/work-orders", store, CLERK,
                       json={"asset_type": "VEHICLE", "asset_id": "VEH-1047", "pm_plan_id": "PMP-0001"})).status_code == 403
    await grant(store, MGR, employee(MGR), {"can_manage_repair": True})
    other = (await http("POST", f"{API}/repairs", store, MGR,
                        json={"asset_type": "VEHICLE", "asset_id": "VEH-1047", "source_type": "MANUAL"})).json()
    other_id = other["repair"]["repair_id"]
    assert (await http("POST", f"{API}/repairs/{other_id}/technician-assignments", store, CLERK,
                       json=team)).status_code == 403
    assert (await http("POST", f"{API}/repairs/{other_id}/close", store, CLERK, json={})).status_code == 403
    # Only the current PRIMARY completes; the delegate cannot impersonate the technician.
    set_id = (await http("GET", f"{API}/repairs/{rid}/technician-assignments", store, CLERK,
                         request_id=None)).json()["current"]["assignment_set_id"]
    refused = await http("POST", f"{API}/repairs/{rid}/completion", store, CLERK, json={"expected_set_id": set_id})
    assert code(refused) == (403, "REPAIR_COMPLETION_LEAD_ONLY")
    member = await http("POST", f"{API}/repairs/{rid}/completion", store, TECH2, json={"expected_set_id": set_id})
    assert code(member) == (403, "REPAIR_COMPLETION_LEAD_ONLY")
    done = await http("POST", f"{API}/repairs/{rid}/completion", store, TECH1, json={"expected_set_id": set_id})
    assert done.status_code == 200, done.text
    closed = await http("POST", f"{API}/repairs/{rid}/close", store, CLERK, json={})
    assert closed.status_code == 200 and closed.json()["repair"]["status"] == "CLOSED"
    # Revoking the Finding authority applies to the next action.
    await grant(store, MGR, employee(CLERK), {"can_manage_finding_repair": False})
    later = await _r3_finding_on(store, "VEH-1048")
    again = await http("POST", f"{API}/repairs", store, CLERK, json={
        "asset_type": "VEHICLE", "asset_id": "VEH-1048", "source_type": "FINDING", "source_id": later})
    assert again.status_code == 403


async def _r3_finding_on(store, asset_id: str) -> str:
    form = (await http("GET", f"{API}/inspections/form", store, TECH1, request_id=None,
                       params={"asset_type": "VEHICLE", "asset_id": asset_id})).json()
    items = [{"item_id": e["item"]["item_id"], "result": "PASS"} for e in form["items"]]
    items[0].update(result="FAIL", remark="ยางรั่ว")
    submitted = await http("POST", f"{API}/inspections", store, TECH1,
                           json={"asset_type": "VEHICLE", "asset_id": asset_id, "items": items})
    return submitted.json()["findings"][0]["finding_id"]


async def test_am_16b_l11_terminate_and_convert_finding_requests_under_the_finding_authority_only() -> None:
    store = repo()
    finding = await _r3_finding(store)
    await grant(store, MGR, employee(DRV1), {"can_report_repair": True})
    reported = await http("POST", f"{API}/repair-requests", store, DRV1, json={
        "vehicle_id": "VEH-1046", "symptom_th": "น้ำมันรั่ว", "source_type": "FINDING", "source_id": finding})
    request_id = reported.json()["request"]["repair_request_id"]
    manual = await http("POST", f"{API}/repair-requests", store, DRV1, json={"vehicle_id": "VEH-1046", "symptom_th": "ไฟ"})
    await grant(store, MGR, employee(CLERK), {"can_manage_finding_repair": True})
    assert (await http("POST", f"{API}/repair-requests/{manual.json()['request']['repair_request_id']}/convert",
                       store, CLERK, json={})).status_code == 403  # not Finding provenance
    converted = await http("POST", f"{API}/repair-requests/{request_id}/convert", store, CLERK, json={})
    assert converted.status_code == 200 and converted.json()["repair"]["finding_id"] == finding
    later = await _r3_finding_on(store, "VEH-1048")
    assert (await http("POST", f"{API}/findings/{later}/termination", store, DRV1,
                       json={"reason": "ไม่ซ่อม"})).status_code == 403
    ended = await http("POST", f"{API}/findings/{later}/termination", store, CLERK, json={"reason": "ไม่ซ่อม"})
    assert ended.status_code == 200, ended.text


# 20 / storage --------------------------------------------------------------------


async def test_am_20_replay_stale_revision_and_reused_ids_never_corrupt_the_log() -> None:
    store = repo()
    rid = str(uuid.uuid4())
    first = await grant(store, MGR, department(OPS), {"can_view": True}, request_id=rid)
    size = len(store._access_events)
    replay = await grant(store, MGR, department(OPS), {"can_view": True}, request_id=rid, expected=first.json()["revision"] - 4)
    assert replay.status_code == 200 and replay.json()["replayed"] is True and len(store._access_events) == size
    reused = await grant(store, MGR, department(OPS), {"can_view": False}, request_id=rid)
    assert code(reused) == (409, "REQUEST_ID_REUSED") and len(store._access_events) == size
    stale = await grant(store, MGR, employee(DRV1), {"can_report_repair": True}, expected=0)
    assert code(stale) == (409, "ACCESS_STALE_REVISION") and len(store._access_events) == size
    missing_reason = await grant(store, MGR, employee(DRV1), {"can_report_repair": True}, reason=" ")
    assert code(missing_reason) == (422, "ACCESS_REASON_REQUIRED")
    not_grantable = await grant(store, MGR, employee(DRV1), {"admin": True})
    assert code(not_grantable) == (422, "ACCESS_CAPABILITY_NOT_GRANTABLE") and len(store._access_events) == size


async def test_am_20b_the_mock_append_is_compare_and_append() -> None:
    from app.domain.access_management import AccessConflict

    store = repo()
    with pytest.raises(AccessConflict):
        await store.append_access_events([build_access_event_row(event_id="x")], expected_revision=5)
    assert len(store._access_events) == 1


async def test_am_sheets_mode_and_legacy_mode_fail_closed(monkeypatch) -> None:
    from app.repositories.google_sheets import GoogleSheetsRepository
    from tests.test_google_sheets_real_io import _configured_settings

    sheets = GoogleSheetsRepository(_configured_settings())
    for call in (sheets.read_access_personnel(), sheets.read_access_events(), sheets.append_access_events([], 0)):
        with pytest.raises(RepositoryFeatureNotImplementedError):
            await call
    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "false")
    legacy = await http("GET", f"{API}/access/me", MockRepository(), MGR, request_id=None)
    assert code(legacy) == (409, "ACCESS_MANAGEMENT_NOT_ENABLED")


def test_am_settings_refuse_production_or_sheets(monkeypatch) -> None:
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(access_management_mode=True, app_env="production")
    with pytest.raises(ValueError):
        Settings(access_management_mode=True, data_repository="google_sheets")


async def test_am_catalog_maps_only_existing_capabilities_into_the_ten_categories() -> None:
    from app.domain import authz
    from app.domain.access_management import CATALOG, GRANTABLE

    store = repo()
    catalog = (await http("GET", f"{API}/access/catalog", store, MGR, request_id=None)).json()
    assert [c["code"] for c in catalog["categories"]] == list("ABCDEFGHIJ")
    assert GRANTABLE <= authz.ALL_CAPABILITIES | authz.PENDING_CAPABILITIES
    assert len({e.code for e in CATALOG}) == len(CATALOG)  # each capability in exactly one category
    assert (await http("GET", f"{API}/access/catalog", store, DRV1, request_id=None)).status_code == 403
