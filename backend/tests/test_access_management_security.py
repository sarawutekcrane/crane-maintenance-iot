"""Access Management + L11 — final security corrections (Owner decisions B1, B2,
D1–D8, replay privacy). Each test reproduces an attack or rule found by the
read-only security verification. SYNTHETIC Mock data only; Mock results are not
production evidence (single-process guard, R11; development login, M01).
"""
from __future__ import annotations

import uuid

import pytest

from app.dependencies import AM_RECOVERY_WRITE_ROUTES, AM_UNRESOLVED_WRITE_ROUTES
from app.domain.access_management import SENSITIVE, build_access_event_row
from tests.test_access_management import (
    API,
    CLERK,
    DRV1,
    DRV2,
    MGR,
    MNT,
    OPM,
    OPS,
    P,
    RESIGNED,
    TECH1,
    TECH2,
    _r3_finding,
    access_mode,  # noqa: F401 — the Access Management mode fixture (autouse)
    caps,
    code,
    delegate,
    department,
    employee,
    grant,
    http,
    repo,
    revision,
)

FREE_ACCOUNT = "USR-TEST-901"  # an in-scope TEST account linked to nobody


async def is_root(store, user: str) -> bool:
    return (await http("GET", f"{API}/access/me", store, user, request_id=None)).json()["is_root"]


async def root_valid(store) -> bool:
    return (await http("GET", f"{API}/access/root", store, MGR, role="ADMIN", request_id=None)).json()["valid"]


def link(operation: str, expected: str, new: str | None = None) -> dict:
    body = {"operation": operation, "expected_user_id": expected, "reason_th": "ทดสอบ"}
    if new is not None:
        body["new_user_id"] = new
    return body


def lifecycle() -> dict:
    return {"expected_active_status": "ACTIVE", "reason_th": "ทดสอบ"}


def transfer(to: str, expected: str) -> dict:
    return {"operation": "TRANSFER", "department_id": to, "effective": {"mode": "NOW"},
            "expected_current_department_id": expected, "reason_th": "ย้าย"}


# ---------------------------------------------------------------------------
# B1 — root takeover and lockout
# ---------------------------------------------------------------------------


async def test_b1_account_link_holder_can_neither_unlink_nor_relink_the_root_holder() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_link_personnel_account": True})
    unlink = await http("POST", f"{API}/personnel/{P[MGR]}/account-links", store, CLERK, json=link("UNLINK", MGR))
    assert code(unlink) == (403, "ACCESS_ROOT_PROTECTED")
    relink = await http("POST", f"{API}/personnel/{P[MGR]}/account-links", store, CLERK,
                        json=link("RELINK", MGR, FREE_ACCOUNT))
    assert code(relink) == (403, "ACCESS_ROOT_PROTECTED")
    reconcile = await http("POST", f"{API}/personnel/{P[MGR]}/account-links/reconcile", store, CLERK,
                           json={"expected_user_id": MGR, "related_request_id": str(uuid.uuid4()), "reason_th": "x"})
    assert code(reconcile)[0] == 403
    assert await is_root(store, MGR) and not await is_root(store, FREE_ACCOUNT)
    # Legitimate personnel administration on an ordinary employee still works.
    ordinary = await http("POST", f"{API}/personnel/{P[DRV2]}/account-links", store, CLERK,
                          json=link("UNLINK", DRV2))
    assert ordinary.status_code == 200, ordinary.text


async def test_b1_the_appointment_is_bound_to_the_verified_account_so_a_relink_never_transfers_root() -> None:
    store = repo()
    # Even a link changed outside every guarded route (simulated) cannot transfer the position.
    for row in store._personnel_master:
        if row["personnel_id"] == P[MGR]:
            row["user_id"] = FREE_ACCOUNT
    assert not await is_root(store, FREE_ACCOUNT)
    assert not await root_valid(store)


async def test_b1_personnel_manager_cannot_deactivate_the_root_holder_and_nobody_self_locks_out() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_manage_personnel": True})
    await grant(store, MGR, employee(MGR), {"can_manage_personnel": True, "can_link_personnel_account": True})
    refused = await http("POST", f"{API}/personnel/{P[MGR]}/deactivations", store, CLERK, json=lifecycle())
    assert code(refused) == (403, "ACCESS_ROOT_PROTECTED")
    for path, body in ((f"{API}/personnel/{P[MGR]}/deactivations", lifecycle()),
                       (f"{API}/personnel/{P[MGR]}/account-links", link("UNLINK", MGR))):
        assert code(await http("POST", path, store, MGR, json=body)) == (403, "ACCESS_ROOT_PROTECTED")
    assert await root_valid(store)
    ok = await http("POST", f"{API}/personnel/{P[DRV2]}/deactivations", store, CLERK, json=lifecycle())
    assert ok.status_code == 200, ok.text


async def test_b1_department_of_the_root_holder_only_by_the_holder_or_recovery() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_move_personnel_department": True})
    await grant(store, MGR, employee(MGR), {"can_move_personnel_department": True})
    by_clerk = await http("POST", f"{API}/personnel/{P[MGR]}/department-events", store, CLERK,
                          json=transfer(OPS, MNT))
    assert code(by_clerk) == (403, "ACCESS_ROOT_PROTECTED")
    by_holder = await http("POST", f"{API}/personnel/{P[MGR]}/department-events", store, MGR, json=transfer(OPS, MNT))
    assert by_holder.status_code == 200, by_holder.text
    assert await is_root(store, MGR)  # the position does not follow the department


async def test_b1_an_invalid_holder_stays_protected_and_only_recovery_appoints_a_successor() -> None:
    store = repo()
    await grant(store, MGR, employee(CLERK), {"can_manage_personnel": True})
    for row in store._personnel_master:
        if row["personnel_id"] == P[MGR]:
            row["active_status"] = "INACTIVE"
    assert not await root_valid(store)
    # Ordinary capabilities cannot act on the protected record while it is invalid ...
    reactivate = await http("POST", f"{API}/personnel/{P[MGR]}/reactivations", store, CLERK,
                            json={"expected_active_status": "INACTIVE", "reason_th": "x"})
    assert code(reactivate) == (403, "ACCESS_ROOT_PROTECTED")
    # ... and recovery has no employee identity, so its one pathway is the appointment.
    by_recovery = await http("POST", f"{API}/personnel/{P[MGR]}/reactivations", store, "USR-RECOVERY", role="ADMIN",
                             json={"expected_active_status": "INACTIVE", "reason_th": "x"})
    assert code(by_recovery) == (403, "ACCESS_ACTOR_NOT_VERIFIED")
    appointed = await http("POST", f"{API}/access/root/appointment", store, "USR-RECOVERY", role="ADMIN",
                           json={"personnel_id": P[CLERK], "reason_th": "กู้คืน",
                                 "expected_revision": len(store._access_events)})
    assert appointed.status_code == 200 and appointed.json()["appointments"][-1]["mode"] == "RECOVERY"
    assert await is_root(store, CLERK)


async def test_b1_d7_delegates_cannot_pass_on_sensitive_capabilities_nor_touch_the_root_holder() -> None:
    store = repo()
    refused = await delegate(store, MGR, OPM, MNT, ["can_view", "can_manage_personnel"])
    assert code(refused) == (422, "ACCESS_CAPABILITY_NOT_DELEGABLE")
    # A delegation event written before this rule (simulated) still cannot pass a sensitive capability on.
    store._access_events.append(build_access_event_row(
        event_id="ACE-OLD-DELEGATION", kind="DELEGATION_GRANT", personnel_id=P[OPM], delegation_id="ACD-OLD",
        department_id=MNT, capabilities="can_link_personnel_account,can_view", actor_personnel_id=P[MGR],
        recorded_at="2099-01-01T00:00:00+00:00", details_json='{"delegate_user_id": "USR-TEST-AM-OPM"}'))
    assert code(await grant(store, OPM, employee(CLERK), {"can_link_personnel_account": True}))[0] == 403
    assert (await grant(store, OPM, employee(CLERK), {"can_view": True})).status_code == 200
    assert code(await grant(store, OPM, employee(MGR), {"can_view": True})) == (403, "ACCESS_ROOT_PROTECTED")
    catalog = (await http("GET", f"{API}/access/catalog", store, MGR, request_id=None)).json()
    flagged = {c["code"] for cat in catalog["categories"] for c in cat["capabilities"] if c["sensitive"]}
    assert flagged == SENSITIVE


async def test_b1_d3_a_relinked_delegate_account_does_not_inherit_the_delegation() -> None:
    store = repo()
    assert (await delegate(store, MGR, OPM, OPS, ["can_view"])).status_code == 200
    for row in store._personnel_master:  # the delegate's record re-linked to another account (simulated)
        if row["personnel_id"] == P[OPM]:
            row["user_id"] = FREE_ACCOUNT
    me = (await http("GET", f"{API}/access/me", store, FREE_ACCOUNT, request_id=None)).json()
    assert me["delegations"] == []


# ---------------------------------------------------------------------------
# B2 / D5 — active, verified PRIMARY
# ---------------------------------------------------------------------------


async def _round_with_lead(store) -> tuple[str, str]:
    finding = await _r3_finding(store)
    await grant(store, MGR, employee(MGR), {"can_manage_finding_repair": True, "can_move_personnel_department": True,
                                           "can_view": True})
    opened = await http("POST", f"{API}/repairs", store, MGR, json={
        "asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "FINDING", "source_id": finding})
    rid = opened.json()["repair"]["repair_id"]
    team = {"primary_technician_id": "TEC-TEST-911", "collaborator_technician_ids": ["TEC-TEST-912"],
            "expected_current": None}
    assert (await http("POST", f"{API}/repairs/{rid}/technician-assignments", store, MGR, json=team)).status_code == 200
    set_id = (await http("GET", f"{API}/repairs/{rid}/technician-assignments", store, MGR,
                         request_id=None)).json()["current"]["assignment_set_id"]
    return rid, set_id


async def test_b2_an_inactive_primary_can_neither_record_work_nor_complete() -> None:
    store = repo()
    rid, set_id = await _round_with_lead(store)
    for row in store._personnel_master:
        if row["personnel_id"] == P[TECH1]:
            row["active_status"] = "INACTIVE"
    work = await http("POST", f"{API}/repairs/{rid}/actions", store, TECH1, json={"action_text": "ทำงาน"})
    assert code(work) == (403, "ACCESS_ACTOR_NOT_VERIFIED")
    done = await http("POST", f"{API}/repairs/{rid}/completion", store, TECH1, json={"expected_set_id": set_id})
    assert code(done) == (403, "ACCESS_ACTOR_NOT_VERIFIED")
    current = (await http("GET", f"{API}/repairs/{rid}/technician-assignments", store, MGR, request_id=None)).json()
    assert current["current"]["primary_technician_id"] == "TEC-TEST-911"  # history never rewritten


async def test_b2_d5_a_transferred_primary_is_denied_until_management_reconfirms_the_team() -> None:
    store = repo()
    rid, set_id = await _round_with_lead(store)
    moved = await http("POST", f"{API}/personnel/{P[TECH1]}/department-events", store, MGR, json=transfer(OPS, MNT))
    assert moved.status_code == 200, moved.text
    work = await http("POST", f"{API}/repairs/{rid}/actions", store, TECH1, json={"action_text": "ทำงาน"})
    assert work.status_code == 403
    done = await http("POST", f"{API}/repairs/{rid}/completion", store, TECH1, json={"expected_set_id": set_id})
    assert code(done) == (403, "REPAIR_ACTOR_NOT_ELIGIBLE")
    # The collaborator (not transferred) keeps recording; no automatic reassignment happened.
    assert (await http("POST", f"{API}/repairs/{rid}/actions", store, TECH2,
                       json={"action_text": "ช่วยงาน"})).status_code == 200
    team = {"primary_technician_id": "TEC-TEST-911", "collaborator_technician_ids": ["TEC-TEST-912"],
            "expected_current": {"primary_technician_id": "TEC-TEST-911",
                                 "collaborator_technician_ids": ["TEC-TEST-912"]}}
    again = await http("POST", f"{API}/repairs/{rid}/technician-assignments", store, MGR, json=team)
    assert again.status_code == 200 and again.json()["changed"] is True, again.text  # explicit re-confirmation
    noop = await http("POST", f"{API}/repairs/{rid}/technician-assignments", store, MGR, json=team)
    assert noop.json()["changed"] is False  # the accepted no-op stands once nothing is stale
    new_set = (await http("GET", f"{API}/repairs/{rid}/technician-assignments", store, MGR,
                          request_id=None)).json()
    assert len(new_set["sets"]) == 2  # immutable history: the original set is kept
    ok = await http("POST", f"{API}/repairs/{rid}/completion", store, TECH1,
                    json={"expected_set_id": new_set["current"]["assignment_set_id"]})
    assert ok.status_code == 200, ok.text


async def test_b2_missing_or_unlinked_identity_fails_closed() -> None:
    store = repo()
    rid, set_id = await _round_with_lead(store)
    for user in ("USR-NOBODY", FREE_ACCOUNT):
        done = await http("POST", f"{API}/repairs/{rid}/completion", store, user, json={"expected_set_id": set_id})
        assert code(done) == (403, "ACCESS_ACTOR_NOT_VERIFIED")


# ---------------------------------------------------------------------------
# D1 / D2 — department-wide changes
# ---------------------------------------------------------------------------


async def test_d1_d2_all_employees_includes_the_root_holder_and_exclusions_are_explicit() -> None:
    store = repo()
    preview = (await http("POST", f"{API}/access/grants/preview", store, MGR, json={
        "target": department(MNT), "changes": {"can_view": True}, "expected_revision": await revision(store)})).json()
    assert preview["eligible_count"] == preview["target_count"] == 4 and preview["excluded"] == []
    assert P[MGR] in preview["target_personnel_ids"]  # D2: the root holder's own permissions too
    assert (await grant(store, MGR, department(MNT), {"can_view": True})).status_code == 200
    assert "can_view" in await caps(store, MGR)
    # A delegate for MNT sees themself and the root holder listed as excluded, with reasons.
    await delegate(store, MGR, CLERK, MNT, ["can_report_repair"])
    plan = (await http("POST", f"{API}/access/grants/preview", store, CLERK, json={
        "target": department(MNT), "changes": {"can_report_repair": True},
        "expected_revision": await revision(store)})).json()
    reasons = {e["personnel_id"]: e["reason"] for e in plan["excluded"]}
    assert reasons == {P[CLERK]: "SELF_NOT_EDITABLE", P[MGR]: "ROOT_PROTECTED"}
    assert plan["eligible_count"] == 4 and plan["target_count"] == 2
    ops = (await http("POST", f"{API}/access/grants/preview", store, MGR, json={
        "target": department(OPS), "changes": {"can_view": True}, "expected_revision": await revision(store)})).json()
    assert {e["personnel_id"]: e["reason"] for e in ops["excluded"]} == {P[RESIGNED]: "INACTIVE"}


# ---------------------------------------------------------------------------
# D4 — no resurrection after cancellation or correction
# ---------------------------------------------------------------------------


async def test_d4_cancelling_or_correcting_a_transfer_never_restores_ended_permissions() -> None:
    store = repo()
    await grant(store, MGR, employee(MGR), {"can_move_personnel_department": True})
    await grant(store, MGR, employee(DRV1), {"can_report_repair": True})
    moved = await http("POST", f"{API}/personnel/{P[DRV1]}/department-events", store, MGR, json=transfer(MNT, OPS))
    event_id = moved.json()["event_id"]
    assert await caps(store, DRV1) == []
    await grant(store, MGR, employee(MGR), {"can_view": True})  # to read the department history
    history = (await http("GET", f"{API}/personnel/{P[DRV1]}/department-history", store, MGR,
                          request_id=None)).json()
    revision_no = next(e["revision_no"] for e in history["events"] if e["event_id"] == event_id)
    cancelled = await http("POST", f"{API}/personnel/{P[DRV1]}/department-events", store, MGR, json={
        "operation": "CANCELLATION", "event_id": event_id, "expected_revision_no": str(revision_no),
        "expected_current_department_id": MNT, "reason_th": "ยกเลิกการย้าย"})
    assert cancelled.status_code == 200, cancelled.text
    assert await caps(store, DRV1) == []  # no implicit resurrection
    audit = (await http("GET", f"{API}/access/audit", store, MGR, request_id=None,
                        params={"personnel_id": P[DRV1]})).json()
    kinds = [e["kind"] for e in audit]
    assert kinds[0] == "DEPARTMENT_CANCELLATION_PERMISSIONS_RESET"
    assert "DEPARTMENT_TRANSFER_PERMISSIONS_RESET" in kinds and "GRANT" in kinds  # history kept
    assert (await grant(store, MGR, employee(DRV1), {"can_report_repair": True})).status_code == 200
    assert await caps(store, DRV1) == ["can_report_repair"]  # explicit, audited re-grant


async def test_d4_an_invalid_department_timeline_holds_nothing() -> None:
    store = repo()
    await grant(store, MGR, employee(DRV1), {"can_view": True})
    for row in store._personnel_department_history:
        if row["personnel_id"] == P[DRV1]:
            store._personnel_department_history.append({**row, "record_id": "PDH-DUP", "event_id": "PDH-DUP",
                                                          "request_id": "dup"})
            break
    assert await caps(store, DRV1) == []


# ---------------------------------------------------------------------------
# D6 — every mutating route in Access Management mode
# ---------------------------------------------------------------------------


def _mutating_routes() -> list[tuple[str, str]]:
    from app.main import create_app

    spec = create_app().openapi()
    return sorted((m.upper(), path) for path, ops in spec["paths"].items() for m in ops
                  if m in ("post", "put", "patch", "delete"))


def _concrete(path: str) -> str:
    import re

    return re.sub(r"\{(\w+)\}", "X-1", path)


# R4 PM Workflow (Owner EV-044 / EV-045): the six approved PM workflow writes added to
# the D6 inventory (was: 78 routes). Each needs a verified employee (the default D6
# class: neither unresolved nor recovery) and then its own E01 checks in the service.
R4_PM_WORKFLOW_WRITE_ROUTES = frozenset({
    ("POST", "/api/v1/pm/work-orders/{pm_work_order_id}/start"),
    ("POST", "/api/v1/pm/work-orders/{pm_work_order_id}/submit"),
    ("POST", "/api/v1/pm/work-orders/{pm_work_order_id}/return"),
    ("POST", "/api/v1/pm/work-orders/{pm_work_order_id}/cancel"),
    ("POST", "/api/v1/pm/work-orders/{pm_work_order_id}/items/{pm_task_id}/outcome"),
    ("POST", "/api/v1/pm/outstanding/{outstanding_id}/resolve"),
})
PRE_R4_MUTATING_ROUTE_COUNT = 78


async def test_d6_the_inventory_is_complete_and_classified() -> None:
    routes = _mutating_routes()
    assert len(routes) == len(set(routes))  # no duplicate registration
    assert R4_PM_WORKFLOW_WRITE_ROUTES <= set(routes)
    assert len(routes) == PRE_R4_MUTATING_ROUTE_COUNT + len(R4_PM_WORKFLOW_WRITE_ROUTES)  # 84, nothing else new
    assert AM_UNRESOLVED_WRITE_ROUTES <= set(routes) and AM_RECOVERY_WRITE_ROUTES <= set(routes)
    # The new PM workflow writes are never exempt from the verified-actor requirement.
    assert not R4_PM_WORKFLOW_WRITE_ROUTES & (AM_UNRESOLVED_WRITE_ROUTES | AM_RECOVERY_WRITE_ROUTES)


async def test_d6_an_unidentified_actor_can_write_nothing() -> None:
    store = repo()
    for method, path in _mutating_routes():
        for user, role in ((None, "ADMIN"), ("USR-NOBODY", "ADMIN"), (RESIGNED, "MAINTENANCE_MANAGER")):
            response = await http(method, _concrete(path), store, user, role=role, json={})
            if (method, path) in AM_RECOVERY_WRITE_ROUTES:
                assert response.status_code in (403, 409, 422), (method, path)  # re-checked in the service
                continue
            assert response.status_code == 403, (method, path, user, response.text[:120])


async def test_d6_a_zero_grant_employee_cannot_use_unresolved_routes_and_the_certificate_write_is_closed() -> None:
    store = repo()
    for method, path in sorted(AM_UNRESOLVED_WRITE_ROUTES):
        response = await http(method, _concrete(path), store, DRV1, json={})
        assert code(response) == (403, "ACCESS_CAPABILITY_MAPPING_UNRESOLVED"), (method, path)
    cert = await http("POST", f"{API}/vehicles/VEH-1046/certificates", store, MGR, json={})
    assert code(cert) == (403, "ACCESS_CAPABILITY_MAPPING_UNRESOLVED")  # even for the root holder


async def test_d6_a_zero_grant_employee_is_refused_by_capability_on_guarded_routes() -> None:
    store = repo()
    for method, path, body in (
        ("POST", f"{API}/repairs", {"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "MANUAL"}),
        ("POST", f"{API}/repair-requests", {"vehicle_id": "VEH-1046", "symptom_th": "x"}),
        ("POST", f"{API}/pm/work-orders", {"asset_type": "VEHICLE", "asset_id": "VEH-1046", "pm_plan_id": "PMP-0001"}),
        ("POST", f"{API}/personnel/{P[DRV2]}/deactivations", lifecycle()),
        ("POST", f"{API}/access/grants", {"target": employee(DRV2), "changes": {"can_view": True},
                                          "reason_th": "x", "expected_revision": 1}),
    ):
        assert (await http(method, path, store, DRV1, json=body)).status_code == 403, path


async def test_d6_legacy_mode_is_unchanged(monkeypatch) -> None:
    from app.repositories.mock.repository import MockRepository

    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "false")
    response = await http("POST", f"{API}/vehicles/VEH-1046/certificates", MockRepository(), None, role="ADMIN",
                          json={})
    assert response.status_code != 403


# ---------------------------------------------------------------------------
# Replay privacy
# ---------------------------------------------------------------------------


async def test_replay_is_actor_scoped_and_checked_after_authority() -> None:
    store = repo()
    await delegate(store, MGR, OPM, OPS, ["can_view"])
    rid = str(uuid.uuid4())
    body = {"target": department(OPS), "changes": {"can_view": True}, "reason_th": "x",
            "expected_revision": await revision(store)}
    first = await http("POST", f"{API}/access/grants", store, OPM, json=body, request_id=rid)
    assert first.status_code == 200
    size = len(store._access_events)
    # Another administrator reusing the id gets no summary (409), a non-administrator gets 403.
    assert code(await http("POST", f"{API}/access/grants", store, MGR, json=body, request_id=rid)) == (
        409, "REQUEST_ID_REUSED")
    assert (await http("POST", f"{API}/access/grants", store, DRV2, json=body, request_id=rid)).status_code == 403
    # The same actor's exact repeat replays without new events.
    again = await http("POST", f"{API}/access/grants", store, OPM, json=body, request_id=rid)
    assert again.json()["replayed"] is True and len(store._access_events) == size
    # Once the authority is revoked, even the original actor's replay is refused.
    delegation_id = (await http("GET", f"{API}/access/delegations", store, MGR, request_id=None)).json()[0][
        "delegation_id"]
    await http("POST", f"{API}/access/delegations/{delegation_id}/revocation", store, MGR,
               json={"reason_th": "สิ้นสุด", "expected_revision": await revision(store)})
    assert (await http("POST", f"{API}/access/grants", store, OPM, json=body, request_id=rid)).status_code == 403


@pytest.mark.parametrize("capability", sorted(SENSITIVE))
async def test_d7_each_sensitive_capability_is_root_grantable_only(capability: str) -> None:
    store = repo()
    assert (await grant(store, MGR, employee(CLERK), {capability: True})).status_code == 200
    assert code(await delegate(store, MGR, OPM, OPS, [capability])) == (422, "ACCESS_CAPABILITY_NOT_DELEGABLE")
