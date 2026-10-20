"""Access Management + L11 — identity-link and legacy-assignment corrections
(Owner-approved A1, A2, B). Each test reproduces an attack found by the final
read-only security closure. SYNTHETIC Mock data only; not production evidence.

Rule under test: an effective employee–account or employee–technician link
change is a reset boundary, exactly like a department movement (D4): grants,
delegations and assignment-based authority recorded before it count for nothing
until an authorized administrator re-grants or a manager re-confirms the team.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.assignment import AssignmentRole, PmAssignmentHistoryEntry, RepairAssignmentHistoryEntry
from tests.test_access_management import (
    API,
    CLERK,
    DRV1,
    MGR,
    MNT,
    OPM,
    OPS,
    P,
    TECH1,
    _r3_finding,
    access_mode,  # noqa: F401 — the Access Management mode fixture (autouse)
    caps,
    code,
    delegate,
    employee,
    grant,
    http,
    repo,
)
from tests.test_access_management_security import FREE_ACCOUNT, is_root, link, transfer

OPM_GRANTS = {"can_manage_finding_repair": True, "can_report_repair": True}


def technician_link(operation: str, expected: str, new: str | None = None) -> dict:
    body = {"operation": operation, "expected_technician_id": expected, "reason_th": "ทดสอบ"}
    if new is not None:
        body["new_technician_id"] = new
    return body


# ---------------------------------------------------------------------------
# A1 — account relinking resets effective permissions
# ---------------------------------------------------------------------------


async def test_a1_relinking_an_employee_account_never_passes_their_grants_on() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_account": True})
    await grant(store, MGR, employee(OPM), OPM_GRANTS)
    assert await caps(store, "USR-TEST-AM-OPM") == sorted(OPM_GRANTS)
    events_before = len(store._access_events)
    relinked = await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK,
                          json=link("RELINK", "USR-TEST-AM-OPM", FREE_ACCOUNT))
    assert relinked.status_code == 200, relinked.text
    assert await caps(store, FREE_ACCOUNT) == []  # the new account inherits nothing
    assert await caps(store, "USR-TEST-AM-OPM") == []  # the old account no longer maps to the employee
    assert await caps(store, CLERK) == ["can_link_personnel_account"]  # the actor gains nothing
    assert len(store._access_events) == events_before  # derived: no grant history rewritten or added
    history = store._personnel_account_link_history[-1]
    assert (history["recorded_by"], history["previous_user_id"], history["new_user_id"]) == (
        CLERK, "USR-TEST-AM-OPM", FREE_ACCOUNT)
    # Only an explicit, audited re-grant makes the new verified account effective.
    assert (await grant(store, MGR, employee(OPM), {"can_report_repair": True})).status_code == 200
    assert await caps(store, FREE_ACCOUNT) == ["can_report_repair"]
    report = await http("POST", f"{API}/repair-requests", store, FREE_ACCOUNT,
                        json={"vehicle_id": "VEH-1046", "symptom_th": "เสียงดัง"})
    assert report.status_code == 200, report.text


async def test_a1_unlink_then_relink_to_the_same_account_still_requires_a_regrant() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_account": True})
    await grant(store, MGR, employee(OPM), OPM_GRANTS)
    assert (await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK,
                       json=link("UNLINK", "USR-TEST-AM-OPM"))).status_code == 200
    assert (await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK,
                       json=link("LINK", "", "USR-TEST-AM-OPM"))).status_code == 200
    assert await caps(store, "USR-TEST-AM-OPM") == []  # an effective identity change happened twice


async def test_a1_a_true_no_op_replay_or_refused_change_does_not_reset() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_account": True})
    await grant(store, MGR, employee(OPM), OPM_GRANTS)
    same = await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK,
                      json=link("RELINK", "USR-TEST-AM-OPM", "USR-TEST-AM-OPM"))
    assert same.status_code in (200, 409, 422)
    assert same.status_code != 200 or same.json().get("changed") is False
    invalid = await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK,
                         json=link("RELINK", "USR-TEST-AM-OPM", "USR-DOES-NOT-EXIST"))
    assert invalid.status_code in (409, 422)
    taken = await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK,
                       json=link("RELINK", "USR-TEST-AM-OPM", "USR-TEST-AM-DRV1"))
    assert code(taken) == (409, "USER_ACCOUNT_ALREADY_LINKED")
    assert await caps(store, "USR-TEST-AM-OPM") == sorted(OPM_GRANTS)  # nothing effective changed
    # A replay of a real change writes nothing new and never resurrects the reset grants.
    rid = str(uuid.uuid4())
    body = link("RELINK", "USR-TEST-AM-OPM", FREE_ACCOUNT)
    first = await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK, json=body, request_id=rid)
    assert first.status_code == 200
    rows = len(store._personnel_account_link_history)
    again = await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK, json=body, request_id=rid)
    assert again.json().get("replayed") is True and len(store._personnel_account_link_history) == rows
    assert await caps(store, FREE_ACCOUNT) == []


async def test_a1_delegation_and_root_identity_bindings_still_hold() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_account": True})
    assert (await delegate(store, MGR, OPM, OPS, ["can_view"])).status_code == 200
    relinked = await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK,
                          json=link("RELINK", "USR-TEST-AM-OPM", FREE_ACCOUNT))
    assert relinked.status_code == 200
    assert (await http("GET", f"{API}/access/me", store, FREE_ACCOUNT, request_id=None)).json()["delegations"] == []
    root = await http("POST", f"{API}/personnel/{P[MGR]}/account-links", store, CLERK,
                      json=link("RELINK", MGR, "USR-TEST-AM-OPM"))
    assert code(root) == (403, "ACCESS_ROOT_PROTECTED") and await is_root(store, MGR)


# ---------------------------------------------------------------------------
# A2 — identity-link changes never transfer PRIMARY authority
# ---------------------------------------------------------------------------


async def _lead_round(store) -> tuple[str, str]:
    finding = await _r3_finding(store)
    await grant(store, MGR, employee(MGR), {"can_manage_finding_repair": True, "can_view": True,
                                           "can_move_personnel_department": True})
    rid = (await http("POST", f"{API}/repairs", store, MGR, json={
        "asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "FINDING", "source_id": finding})).json()[
        "repair"]["repair_id"]
    team = {"primary_technician_id": "TEC-TEST-911", "collaborator_technician_ids": [], "expected_current": None}
    assert (await http("POST", f"{API}/repairs/{rid}/technician-assignments", store, MGR, json=team)).status_code == 200
    return rid, await _set_id(store, rid)


async def _set_id(store, rid: str) -> str:
    return (await http("GET", f"{API}/repairs/{rid}/technician-assignments", store, MGR,
                       request_id=None)).json()["current"]["assignment_set_id"]


async def _reconfirm(store, rid: str) -> dict:
    team = {"primary_technician_id": "TEC-TEST-911", "collaborator_technician_ids": [],
            "expected_current": {"primary_technician_id": "TEC-TEST-911", "collaborator_technician_ids": []}}
    return (await http("POST", f"{API}/repairs/{rid}/technician-assignments", store, MGR, json=team)).json()


async def test_a2_technician_link_impersonation_of_the_primary_is_denied() -> None:
    store = repo()
    rid, set_id = await _lead_round(store)
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_technician": True})
    assert (await http("POST", f"{API}/personnel/{P[TECH1]}/technician-links", store, CLERK,
                       json=technician_link("UNLINK", "TEC-TEST-911"))).status_code == 200
    assert (await http("POST", f"{API}/personnel/{P[CLERK]}/technician-links", store, CLERK,
                       json=technician_link("LINK", "", "TEC-TEST-911"))).status_code == 200
    work = await http("POST", f"{API}/repairs/{rid}/actions", store, CLERK, json={"action_text": "แอบอ้าง"})
    assert work.status_code == 403
    done = await http("POST", f"{API}/repairs/{rid}/completion", store, CLERK, json={"expected_set_id": set_id})
    assert code(done) == (403, "REPAIR_ACTOR_NOT_ELIGIBLE")
    assert (await http("GET", f"{API}/repairs/{rid}", store, MGR, request_id=None)).json()["repair"][
        "completion_submitted_at"] is None


async def test_a2_relinking_an_account_into_the_assigned_primary_is_denied_until_reconfirmed() -> None:
    store = repo()
    rid, set_id = await _lead_round(store)
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_account": True})
    assert (await http("POST", f"{API}/personnel/{P[TECH1]}/account-links", store, CLERK,
                       json=link("RELINK", TECH1, FREE_ACCOUNT))).status_code == 200
    done = await http("POST", f"{API}/repairs/{rid}/completion", store, FREE_ACCOUNT, json={"expected_set_id": set_id})
    assert code(done)[0] == 403
    assert (await http("POST", f"{API}/repairs/{rid}/completion", store, TECH1,
                       json={"expected_set_id": set_id})).status_code == 403  # old account: no longer the employee
    # Only an explicit, authorized re-confirmation of the team restores the lead (L9 full-set replacement).
    assert (await _reconfirm(store, rid))["changed"] is True
    ok = await http("POST", f"{API}/repairs/{rid}/completion", store, FREE_ACCOUNT,
                    json={"expected_set_id": await _set_id(store, rid)})
    assert ok.status_code == 200, ok.text


async def test_a2_a_valid_primary_without_identity_change_keeps_the_accepted_no_op() -> None:
    store = repo()
    rid, set_id = await _lead_round(store)
    assert (await _reconfirm(store, rid))["changed"] is False  # nothing stale: the accepted no-op stands
    ok = await http("POST", f"{API}/repairs/{rid}/completion", store, TECH1, json={"expected_set_id": set_id})
    assert ok.status_code == 200, ok.text


async def test_a2_relinking_the_same_technician_back_is_still_an_identity_change() -> None:
    store = repo()
    rid, set_id = await _lead_round(store)
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_technician": True})
    for body in (technician_link("UNLINK", "TEC-TEST-911"), technician_link("LINK", "", "TEC-TEST-911")):
        assert (await http("POST", f"{API}/personnel/{P[TECH1]}/technician-links", store, CLERK,
                           json=body)).status_code == 200
    done = await http("POST", f"{API}/repairs/{rid}/completion", store, TECH1, json={"expected_set_id": set_id})
    assert code(done) == (403, "REPAIR_ACTOR_NOT_ELIGIBLE")
    assert (await _reconfirm(store, rid))["changed"] is True
    assert (await http("POST", f"{API}/repairs/{rid}/completion", store, TECH1,
                       json={"expected_set_id": await _set_id(store, rid)})).status_code == 200


# ---------------------------------------------------------------------------
# B — historical legacy assignments after a transfer
# ---------------------------------------------------------------------------


async def _legacy_jobs(store) -> tuple[str, str]:
    """A MANUAL repair and a PM work order turned into historical legacy jobs IN MEMORY,
    each with a legacy PRIMARY entry for DRV1 that predates everything (real timestamp)."""
    await grant(store, MGR, employee(MGR), {"can_manage_repair": True, "can_manage_pm": True, "can_view": True,
                                           "can_move_personnel_department": True})
    rid = (await http("POST", f"{API}/repairs", store, MGR, json={
        "asset_type": "VEHICLE", "asset_id": "VEH-1047", "source_type": "MANUAL"})).json()["repair"]["repair_id"]
    store._repairs[rid] = store._repairs[rid].model_copy(update={"assignment_model": ""})
    store._repair_assignment_history.setdefault(rid, []).append(RepairAssignmentHistoryEntry(
        repair_assignment_id="RAH-SYN-1", repair_id=rid, user_id=DRV1, assignment_role=AssignmentRole.PRIMARY,
        assigned_at=LEGACY_AT))
    created = await http("POST", f"{API}/pm/work-orders", store, MGR,
                         json={"asset_type": "VEHICLE", "asset_id": "VEH-1048", "pm_plan_id": "PMP-0001"})
    assert created.status_code == 200, created.text
    wid = created.json()["work_order"]["pm_work_order_id"]
    store._pm_work_orders[wid] = store._pm_work_orders[wid].model_copy(update={"assignment_model": ""})
    store._pm_assignment_history.setdefault(wid, []).append(PmAssignmentHistoryEntry(
        pm_assignment_id="PAH-SYN-1", pm_work_order_id=wid, user_id=DRV1, assignment_role=AssignmentRole.PRIMARY,
        assigned_at=LEGACY_AT))
    return rid, wid


LEGACY_AT = datetime(2026, 2, 1, tzinfo=UTC)


async def _am_context(store, user: str):
    from app.context import RequestContext
    from app.domain.access_management import AccessService

    base = RequestContext(request_id="r", user_id=user, roles=("TECHNICIAN",), capabilities=frozenset())
    return await AccessService(store, "TEST", "MOCK-7O2B-SYNTHETIC").effective_context(base)


async def _upload(store, user: str, source_type: str, source_id: str, purpose: str):
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: store
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            return await client.post(f"{API}/attachments", headers={"X-Dev-Role": "TECHNICIAN", "X-Dev-User-Id": user},
                                     data={"purpose": purpose, "source_type": source_type, "source_id": source_id},
                                     files={"file": ("e.jpg", b"\xff\xd8\xff\xe0synthetic", "image/jpeg")})
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


async def test_b_a_legacy_assignment_stops_authorizing_work_after_a_transfer() -> None:
    store = repo()
    rid, _ = await _legacy_jobs(store)
    before = await http("POST", f"{API}/repairs/{rid}/actions", store, DRV1, json={"action_text": "ก่อนย้าย"})
    assert before.status_code == 200, before.text
    actions = len(store._repair_actions.get(rid, []))
    moved = await http("POST", f"{API}/personnel/{P[DRV1]}/department-events", store, MGR, json=transfer(MNT, OPS))
    assert moved.status_code == 200 and await caps(store, DRV1) == []
    after = await http("POST", f"{API}/repairs/{rid}/actions", store, DRV1, json={"action_text": "หลังย้าย"})
    assert after.status_code == 403
    history = store._repair_assignment_history[rid]
    assert [(e.user_id, e.assigned_at) for e in history] == [(DRV1, LEGACY_AT)]  # never rewritten
    assert len(store._repair_actions.get(rid, [])) == actions  # earlier work kept, nothing new written
    # A current explicit capability still authorizes the action under the existing contract.
    await grant(store, MGR, employee(DRV1), {"can_manage_repair": True})
    assert (await http("POST", f"{API}/repairs/{rid}/actions", store, DRV1,
                       json={"action_text": "สิทธิ์ใหม่"})).status_code == 200


async def test_b_an_inactive_legacy_assignee_is_denied() -> None:
    store = repo()
    rid, _ = await _legacy_jobs(store)
    for row in store._personnel_master:
        if row["personnel_id"] == P[DRV1]:
            row["active_status"] = "INACTIVE"
    assert code(await http("POST", f"{API}/repairs/{rid}/actions", store, DRV1,
                           json={"action_text": "x"}))[0] == 403


async def test_b_a_legacy_assignment_without_a_usable_timestamp_fails_closed() -> None:
    store = repo()
    rid, _ = await _legacy_jobs(store)
    store._repair_assignment_history[rid][0] = store._repair_assignment_history[rid][0].model_copy(
        update={"assigned_at": datetime(2026, 2, 1)})  # naive: no provable instant
    assert (await http("POST", f"{API}/repairs/{rid}/actions", store, DRV1,
                       json={"action_text": "x"})).status_code == 403


async def test_b_legacy_pm_recording_and_both_attachment_paths_apply_the_same_boundary() -> None:
    from fastapi import HTTPException

    from app.domain.authz import CAN_MANAGE_PM
    from app.domain.meter_service import MeterService
    from app.domain.pm_service import PmService
    from app.domain.technician_assignment import AssignmentCutover

    store = repo()
    rid, wid = await _legacy_jobs(store)
    pm = PmService(store, MeterService(store), AssignmentCutover(data_context="TEST", test_batch_id="MOCK-7O2B-SYNTHETIC"))
    await pm.authorize_recording(wid, await _am_context(store, DRV1), CAN_MANAGE_PM, "PM")  # before: allowed
    ok = await _upload(store, DRV1, "REPAIR", rid, "REPAIR_EVIDENCE")
    assert ok.status_code == 200, ok.text
    await http("POST", f"{API}/personnel/{P[DRV1]}/department-events", store, MGR, json=transfer(MNT, OPS))
    try:
        await pm.authorize_recording(wid, await _am_context(store, DRV1), CAN_MANAGE_PM, "PM")
        raise AssertionError("a stale legacy PM assignment still authorized recording")
    except HTTPException as refused:
        assert refused.status_code == 403
    for source_type, source_id, purpose in (("REPAIR", rid, "REPAIR_EVIDENCE"), ("PM_WORK_ORDER", wid, "PM_EVIDENCE")):
        assert (await _upload(store, DRV1, source_type, source_id, purpose)).status_code == 403, source_type


async def test_b_legacy_mode_is_unchanged() -> None:
    from app.domain.technician_assignment import legacy_assignment_counts

    assert legacy_assignment_counts(None, datetime(2026, 2, 1)) is True  # no Access Management context


async def test_a1_reconciling_a_mismatched_account_link_is_an_identity_change_too() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_account": True})
    rid = str(uuid.uuid4())
    assert (await http("POST", f"{API}/personnel/{P[OPM]}/account-links", store, CLERK,
                       json=link("RELINK", "USR-TEST-AM-OPM", FREE_ACCOUNT), request_id=rid)).status_code == 200
    for row in store._personnel_master:  # a projection write that did not land (simulated MISMATCH)
        if row["personnel_id"] == P[OPM]:
            row["user_id"] = "USR-TEST-AM-OPM"
    await grant(store, MGR, employee(OPM), OPM_GRANTS)  # granted while the projection was inconsistent
    rows = len(store._personnel_account_link_history)
    reconciled = await http("POST", f"{API}/personnel/{P[OPM]}/account-links/reconcile", store, CLERK,
                            json={"expected_user_id": "USR-TEST-AM-OPM", "related_request_id": rid,
                                  "reason_th": "ปรับให้ตรงกับประวัติ"})
    assert reconciled.status_code == 200, reconciled.text
    assert len(store._personnel_account_link_history) == rows + 1  # appended, never rewritten
    assert await caps(store, FREE_ACCOUNT) == []  # nothing carried across the effective change
    assert await caps(store, "USR-TEST-AM-OPM") == []


def test_a1_a_grant_recorded_at_the_same_instant_as_a_reset_does_not_count() -> None:
    from app.domain.access_management import AccessState, Person

    instant = datetime(2026, 5, 1, tzinfo=UTC)
    person = Person(personnel_id="P", first_name="", last_name="", position="", active_status="ACTIVE",
                    user_id="U", department_id="D", reset_at=instant, department_status="VALID")
    state = AccessState(persons={"P": person}, departments={}, events=[
        {"kind": "GRANT", "personnel_id": "P", "capability": "can_view", "recorded_at": instant.isoformat()}],
        revision=1)
    assert state.grants("P") == frozenset()  # same instant: fail closed
