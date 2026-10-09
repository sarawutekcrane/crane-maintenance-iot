"""R2 Batch R2e — personnel lifecycle (deactivate / reactivate / reconcile /
history) over HTTP with the MOCK repository (always the TEST data context).

Test ids R2E-xx are batch-local PROPOSED identifiers. Every fixture is
SYNTHETIC: invented ids (PER-SYN- is TEST-ONLY, not a production format),
labelled names. In the TEST context a lifecycle write may target only rows with
is_test_data TRUE and the server's test batch; REAL-context rules are exercised
over the fake Sheets transport (test_lifecycle_sheets_batch_r2e.py).
"""
from __future__ import annotations

import inspect
import uuid

import pytest

from app.domain import authz
from app.domain.lifecycle_schema import PERSONNEL_LIFECYCLE_HISTORY_COLUMNS
from app.domain.personnel_lifecycle import OP_PERSONNEL_DEACTIVATE
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.request_replay import request_fingerprint
from app.repositories.mock import MockRepository
from tests.test_personnel_read_batch_r2c1 import person
from tests.test_registration_write_batch7o2b import _http

API = "/api/v1"
PID, PID2 = "PER-SYN-101", "PER-SYN-102"
SYN = " (สังเคราะห์)"
OTHER_ROLES = ("MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER")
LIFECYCLE_CALLS = {"read_lifecycle_master", "read_lifecycle_history_validated", "append_lifecycle_history",
                   "write_lifecycle_state_cell"}


def test_row(pid: str = PID, status: str = "ACTIVE", **extra: str) -> dict[str, str]:
    """A synthetic TEST row in the server's mock test batch (writable in TEST)."""
    cells = {"is_test_data": "TRUE", "test_batch_id": MOCK_TEST_BATCH_ID, **extra}
    return person(pid, "ทดสอบ" + SYN, "บุคลากร" + SYN, status, **cells)


test_row.__test__ = False  # a helper, not a test


class Spy(MockRepository):
    """MockRepository with replaceable personnel rows and a log of every
    public repository coroutine called from outside (nested calls ignored)."""

    def __init__(self, rows=None) -> None:
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "_depth", [0])
        super().__init__()
        if rows is not None:
            self._personnel_master = rows

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        if not name.startswith("_") and inspect.iscoroutinefunction(attr):
            calls = object.__getattribute__(self, "calls")
            depth = object.__getattribute__(self, "_depth")

            async def wrapper(*args, **kwargs):
                if depth[0] == 0:
                    calls.append(name)
                depth[0] += 1
                try:
                    return await attr(*args, **kwargs)
                finally:
                    depth[0] -= 1

            return wrapper
        return attr


def repo_with(*rows) -> Spy:
    return Spy([*rows] if rows else [test_row()])


def _err(response) -> dict:
    return response.json()["error"]


def body(expected="ACTIVE", reason="ปิดใช้งาน (ทดสอบ)", **extra) -> dict:
    return {"expected_active_status": expected, "reason_th": reason, **extra}


def p(op: str, pid: str = PID) -> str:
    return f"{API}/personnel/{pid}/{op}"


async def post(path, payload, repo, **kw):
    return await _http("POST", path, repo=repo, json_body=payload, **kw)


async def history(repo, pid: str = PID) -> dict:
    response = await _http("GET", p("lifecycle-history", pid), repo=repo, request_id=None)
    assert response.status_code == 200, response.text
    return response.json()


def _status(repo, pid: str = PID) -> str:
    return next(r for r in repo._personnel_master if r["personnel_id"] == pid and r["is_test_data"] == "TRUE")[
        "active_status"]


# ===========================================================================
# R2E-01..R2E-05, R2E-09..R2E-11 — transitions, unknown state, no-op, stale, reason
# ===========================================================================


@pytest.mark.asyncio
async def test_r2e_01_deactivate_active_personnel() -> None:
    repo = repo_with()
    response = await post(p("deactivations"), body(), repo)
    assert response.status_code == 200, response.text
    out = response.json()
    assert set(out) == {"request_id", "changed", "record_id", "previous_state", "new_state",
                        "lifecycle_consistency_after"}
    assert (out["changed"], out["previous_state"], out["new_state"], out["lifecycle_consistency_after"]) == (
        True, "ACTIVE", "INACTIVE", "CONSISTENT")
    assert _status(repo) == "INACTIVE" and repo.registry_write_log == ["W1", "W2"]
    (event,) = repo._personnel_lifecycle_history
    assert list(event) == list(PERSONNEL_LIFECYCLE_HISTORY_COLUMNS)
    assert (event["event_kind"], event["previous_state"], event["new_state"], event["related_request_id"]) == (
        "DEACTIVATE", "ACTIVE", "INACTIVE", "")
    assert event["lifecycle_event_id"] == out["record_id"]


@pytest.mark.asyncio
async def test_r2e_02_reactivate_inactive_personnel_keeps_the_same_id() -> None:
    repo = repo_with(test_row(status="INACTIVE"))
    response = await post(p("reactivations"), body("INACTIVE", "เปิดใช้งาน (ทดสอบ)"), repo)
    assert response.status_code == 200
    assert (response.json()["previous_state"], response.json()["new_state"]) == ("INACTIVE", "ACTIVE")
    assert _status(repo) == "ACTIVE"
    assert [r["personnel_id"] for r in repo._personnel_master] == [PID]  # R2E-11: same id, no new row


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["", " ", "active", "Inactive", "RESIGNED", "ลาออก"])
@pytest.mark.parametrize("op", ["deactivations", "reactivations"])
async def test_r2e_03_unknown_current_state_is_refused(current, op) -> None:
    repo = repo_with(test_row(status=current))
    response = await post(p(op), body(), repo)
    assert (response.status_code, _err(response)["code"]) == (422, "PERSONNEL_LIFECYCLE_STATE_INVALID")
    assert _err(response)["details"] == {"field": "active_status"}
    assert repo.registry_write_log == [] and _status(repo) == current  # never normalised or repaired


@pytest.mark.asyncio
async def test_r2e_04_no_op_with_a_correct_expectation() -> None:
    repo = repo_with(test_row(status="INACTIVE"))
    response = await post(p("deactivations"), body("INACTIVE"), repo)
    assert response.status_code == 200
    assert response.json() == {"request_id": response.json()["request_id"], "changed": False}
    assert repo.registry_write_log == [] and repo._personnel_lifecycle_history == []


@pytest.mark.asyncio
async def test_r2e_05_stale_is_checked_before_no_op() -> None:
    repo = repo_with(test_row(status="INACTIVE"))
    # expected ACTIVE, current INACTIVE, requested INACTIVE: stale, never a no-op
    response = await post(p("deactivations"), body("ACTIVE"), repo)
    assert (response.status_code, _err(response)["code"]) == (409, "PERSONNEL_LIFECYCLE_STALE")
    assert _err(response)["details"] == {"field": "active_status"}
    assert repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["deactivations", "reactivations", "lifecycle-reconciliations"])
@pytest.mark.parametrize("reason", ["", " ", "\t\n", "x" * 501])
async def test_r2e_09_10_reason_is_mandatory_in_both_directions(op, reason) -> None:
    repo = repo_with()
    response = await post(p(op), body(reason=reason), repo)
    assert (response.status_code, _err(response)["code"]) == (422, "REASON_REQUIRED")
    assert repo.calls == []  # refused at the body step, before any read
    missing = await post(p(op), {"expected_active_status": "ACTIVE"}, repo)
    assert (missing.status_code, _err(missing)["code"]) == (422, "VALIDATION_ERROR")


@pytest.mark.asyncio
@pytest.mark.parametrize("forged", [{"new_state": "INACTIVE"}, {"recorded_by": "x"}, {"recorded_at": "2020-01-01"},
                                    {"is_test_data": "FALSE"}, {"test_batch_id": "X"}, {"request_id": "x"},
                                    {"request_fingerprint": "0" * 64}, {"related_request_id": "x"},
                                    {"expected_active_status": "active"}])
async def test_r2e_bodies_are_strict_and_server_set(forged) -> None:
    repo = repo_with()
    response = await post(p("deactivations"), {**body(), **forged}, repo)
    assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR")
    assert repo.calls == []


@pytest.mark.asyncio
async def test_r2e_actor_time_request_and_context_are_server_set() -> None:
    repo = repo_with()
    rid = str(uuid.uuid4())
    payload = body()
    await post(p("deactivations"), payload, repo, request_id=rid)
    (event,) = repo._personnel_lifecycle_history
    from app.context import DEV_USER_ID

    assert (event["recorded_by"], event["request_id"]) == (DEV_USER_ID, rid)
    assert event["request_fingerprint"] == request_fingerprint(OP_PERSONNEL_DEACTIVATE, PID, None, payload)
    assert (event["is_test_data"], event["test_batch_id"]) == ("TRUE", MOCK_TEST_BATCH_ID)
    assert event["reason_th"] == payload["reason_th"]


# ===========================================================================
# R2E-13..R2E-19 — no delete, capabilities, request id
# ===========================================================================


def _routes() -> set[tuple[str, str]]:
    from app.main import create_app

    return {(m.upper(), path) for path, ops in create_app().openapi()["paths"].items() for m in ops}


def test_r2e_13_no_hard_delete_route() -> None:
    routes = _routes()
    for base in (f"{API}/personnel/{{personnel_id}}", f"{API}/departments/{{department_id}}"):
        assert ("DELETE", base) not in routes
        for suffix in ("deactivations", "reactivations", "lifecycle-reconciliations"):
            assert ("POST", f"{base}/{suffix}") in routes
        assert ("GET", f"{base}/lifecycle-history") in routes


@pytest.mark.asyncio
async def test_r2e_14_personnel_capability_holders() -> None:
    for role in ("ADMIN", "MAINTENANCE_MANAGER"):
        assert (await post(p("deactivations"), body(), repo_with(), role=role)).status_code == 200
    for role in (*OTHER_ROLES, "NO_SUCH_ROLE"):
        repo = repo_with()
        for op in ("deactivations", "reactivations", "lifecycle-reconciliations"):
            response = await post(p(op), body(), repo, role=role)
            assert (response.status_code, _err(response)["code"]) == (403, "HTTP_ERROR"), (role, op)
        assert repo.calls == []


@pytest.fixture
def synthetic_roles(monkeypatch):
    for name, caps in (("SYN_DEPARTMENT_ONLY", {"can_manage_department"}),
                       ("SYN_PERSONNEL_ONLY", {"can_manage_personnel"}),
                       ("SYN_MANAGE_USER", {"can_manage_user"})):
        monkeypatch.setitem(authz.ROLE_CAPABILITIES, name, frozenset({authz.CAN_VIEW, *caps}))


@pytest.mark.asyncio
async def test_r2e_16_17_18_capabilities_are_independent_and_not_can_manage_user(synthetic_roles) -> None:
    repo = repo_with()
    for role in ("SYN_DEPARTMENT_ONLY", "SYN_MANAGE_USER"):
        assert (await post(p("deactivations"), body(), repo, role=role)).status_code == 403
    for role in ("SYN_PERSONNEL_ONLY", "SYN_MANAGE_USER"):
        response = await post(f"{API}/departments/DEPT-TEST-001/deactivations",
                              {"expected_is_active": True, "reason_th": "x"}, repo, role=role)
        assert response.status_code == 403
    assert repo.calls == []
    assert (await post(p("deactivations"), body(), repo, role="SYN_PERSONNEL_ONLY")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [None, "", "not-a-uuid"])
async def test_r2e_19_client_request_id_required_before_any_read(request_id) -> None:
    repo = repo_with()
    for op in ("deactivations", "reactivations", "lifecycle-reconciliations"):
        response = await post(p(op), body(), repo, request_id=request_id)
        assert (response.status_code, _err(response)["code"]) == (422, "REQUEST_ID_REQUIRED")
    assert repo.calls == []


def test_r2e_14_15_capability_inventory() -> None:
    for cap in ("can_manage_personnel", "can_manage_department"):
        assert cap in authz.ALL_CAPABILITIES and cap in authz.ROLE_CAPABILITIES["ADMIN"]
        assert cap in authz.ROLE_CAPABILITIES["MAINTENANCE_MANAGER"]
        for role in OTHER_ROLES:
            assert cap not in authz.ROLE_CAPABILITIES[role], (cap, role)
    assert "can_manage_user" not in authz.ROLE_CAPABILITIES["MAINTENANCE_MANAGER"]


# ===========================================================================
# R2E-20..R2E-22 — replay within the personnel history tab
# ===========================================================================


@pytest.mark.asyncio
async def test_r2e_20_same_request_is_replayed() -> None:
    repo = repo_with()
    rid = str(uuid.uuid4())
    first = await post(p("deactivations"), body(), repo, request_id=rid)
    again = await post(p("deactivations"), body(), repo, request_id=rid)
    assert again.json() == {"request_id": rid, "replayed": True, "record_ids": [first.json()["record_id"]]}
    assert repo.registry_write_log == ["W1", "W2"] and len(repo._personnel_lifecycle_history) == 1


@pytest.mark.asyncio
async def test_r2e_21_22_request_reused_on_another_personnel_or_operation() -> None:
    repo = repo_with(test_row(), test_row(PID2))
    rid = str(uuid.uuid4())
    assert (await post(p("deactivations"), body(), repo, request_id=rid)).status_code == 200
    other = await post(p("deactivations", PID2), body(), repo, request_id=rid)
    assert (other.status_code, _err(other)["code"]) == (409, "REQUEST_ID_REUSED")
    changed_op = await post(p("reactivations"), body("INACTIVE"), repo, request_id=rid)
    assert _err(changed_op)["code"] == "REQUEST_ID_REUSED"
    changed_body = await post(p("deactivations"), body(reason="อื่น"), repo, request_id=rid)
    assert _err(changed_body)["code"] == "REQUEST_ID_REUSED"
    assert len(repo._personnel_lifecycle_history) == 1


@pytest.mark.asyncio
async def test_r2e_25_same_uuid_may_appear_once_in_each_history_tab() -> None:
    """Request-id uniqueness is per history tab: no cross-tab detection is claimed."""
    repo = repo_with()
    next(d for d in repo._department_master if d["department_id"] == "DEPT-TEST-901")["test_batch_id"] = (
        MOCK_TEST_BATCH_ID)
    rid = str(uuid.uuid4())
    assert (await post(p("deactivations"), body(), repo, request_id=rid)).status_code == 200
    department = await post(f"{API}/departments/DEPT-TEST-901/deactivations",
                            {"expected_is_active": True, "reason_th": "ทดสอบ"}, repo, request_id=rid)
    assert department.status_code == 200 and department.json()["changed"] is True
    assert [e["request_id"] for e in repo._personnel_lifecycle_history] == [rid]
    assert [e["request_id"] for e in repo._department_lifecycle_history] == [rid]


# ===========================================================================
# R2E-26..R2E-33 — write failures, mismatch and reconciliation
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(("fault", "outcome", "applied"), [
    ("rejected", "rejected", False), ("unknown_not_applied", "unknown", False), ("unknown_applied", "unknown", True)])
async def test_r2e_26_27_history_append_failure(fault, outcome, applied) -> None:
    repo = repo_with()
    repo.registry_write_faults["W1"] = fault
    rid = str(uuid.uuid4())
    response = await post(p("deactivations"), body(), repo, request_id=rid)
    assert (response.status_code, _err(response)["code"]) == (503, "PERSONNEL_LIFECYCLE_HISTORY_WRITE_FAILED")
    assert _err(response)["details"] == {"history_write_outcome": outcome, "request_id": rid}
    assert repo.registry_write_log == ["W1"]  # no master write, no retry
    assert _status(repo) == "ACTIVE" and len(repo._personnel_lifecycle_history) == (1 if applied else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["rejected", "unknown_not_applied"])
async def test_r2e_28_29_state_write_failure_leaves_mismatch_and_blocks_normal_writes(fault) -> None:
    repo = repo_with()
    repo.registry_write_faults["W2"] = fault
    rid = str(uuid.uuid4())
    response = await post(p("deactivations"), body(), repo, request_id=rid)
    assert (response.status_code, _err(response)["code"]) == (503, "PERSONNEL_LIFECYCLE_STATE_WRITE_FAILED")
    details = _err(response)["details"]
    assert details == {"event_recorded": True, "record_id": repo._personnel_lifecycle_history[0]["lifecycle_event_id"],
                       "request_id": rid}
    assert repo.registry_write_log == ["W1", "W2"] and _status(repo) == "ACTIVE"
    repo.registry_write_faults.clear()
    assert (await history(repo))["lifecycle_consistency"] == "MISMATCH"
    for op, expected in (("deactivations", "ACTIVE"), ("reactivations", "ACTIVE")):
        blocked = await post(p(op), body(expected), repo)
        assert (blocked.status_code, _err(blocked)["code"]) == (409, "PERSONNEL_LIFECYCLE_MISMATCH")


@pytest.mark.asyncio
async def test_r2e_30_33_reconciliation_writes_the_latest_history_state() -> None:
    repo = repo_with()
    repo.registry_write_faults["W2"] = "rejected"
    first_rid = str(uuid.uuid4())
    await post(p("deactivations"), body(), repo, request_id=first_rid)
    repo.registry_write_faults.clear()
    stale = await post(p("lifecycle-reconciliations"), body("INACTIVE", "ซิงก์ (ทดสอบ)"), repo)
    assert _err(stale)["code"] == "PERSONNEL_LIFECYCLE_STALE"
    response = await post(p("lifecycle-reconciliations"), body("ACTIVE", "ซิงก์ (ทดสอบ)"), repo)
    assert response.status_code == 200, response.text
    assert (response.json()["previous_state"], response.json()["new_state"],
            response.json()["lifecycle_consistency_after"]) == ("ACTIVE", "INACTIVE", "CONSISTENT")
    reconciliation = repo._personnel_lifecycle_history[-1]
    assert (reconciliation["event_kind"], reconciliation["previous_state"], reconciliation["new_state"]) == (
        "RECONCILIATION", "ACTIVE", "INACTIVE")
    assert reconciliation["related_request_id"] == first_rid  # R2E-33: server-derived
    assert _status(repo) == "INACTIVE" and (await history(repo))["lifecycle_consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_r2e_32_reconciliation_is_a_no_op_when_consistent_or_without_history() -> None:
    repo = repo_with()
    none = await post(p("lifecycle-reconciliations"), body("ACTIVE", "ซิงก์"), repo)
    assert none.json()["changed"] is False
    await post(p("deactivations"), body(), repo)
    consistent = await post(p("lifecycle-reconciliations"), body("INACTIVE", "ซิงก์"), repo)
    assert consistent.json()["changed"] is False
    assert len(repo._personnel_lifecycle_history) == 1


# ===========================================================================
# R2E-34 / R2E-36 — lifecycle history read; R2c-1 GET unchanged
# ===========================================================================


@pytest.mark.asyncio
async def test_r2e_34_lifecycle_history_response() -> None:
    repo = repo_with()
    assert (await history(repo)) == {"entity_id": PID, "current_state": "ACTIVE", "latest_history_state": None,
                                     "lifecycle_consistency": "NO_HISTORY", "events": []}
    await post(p("deactivations"), body(), repo)
    await post(p("reactivations"), body("INACTIVE", "เปิดอีกครั้ง (ทดสอบ)"), repo)
    read = await history(repo)
    assert (read["current_state"], read["latest_history_state"], read["lifecycle_consistency"]) == (
        "ACTIVE", "ACTIVE", "CONSISTENT")
    assert [e["event_kind"] for e in read["events"]] == ["DEACTIVATE", "REACTIVATE"]
    assert set(read["events"][0]) == {"lifecycle_event_id", "event_kind", "previous_state", "new_state",
                                      "recorded_at", "recorded_by", "reason_th"}
    for hidden in ("request_fingerprint", "test_batch_id", "request_id", "is_test_data", MOCK_TEST_BATCH_ID):
        assert hidden not in str(read)
    blank = repo_with(test_row(status=""))
    assert (await history(blank))["current_state"] is None  # raw text; blank stays null


@pytest.mark.asyncio
async def test_r2e_36_existing_personnel_get_contract_unchanged() -> None:
    from app.main import create_app

    schema = create_app().openapi()["components"]["schemas"]["PersonnelResponse"]
    assert set(schema["properties"]) == {"personnel_id", "first_name", "last_name", "active_status"}
    repo = MockRepository()
    listed = (await _http("GET", f"{API}/personnel", repo=repo, request_id=None)).json()
    assert listed["total_items"] == 3 and "lifecycle" not in str(listed)
    detail = (await _http("GET", f"{API}/personnel/PER-TEST-003", repo=repo, request_id=None)).json()
    assert detail["active_status"] is None  # blank still null, never ACTIVE


# ===========================================================================
# R2E-39..R2E-43 — TEST scope, flags, phantom rows, identity
# ===========================================================================


@pytest.mark.asyncio
async def test_r2e_39_40_test_context_never_mutates_operational_or_other_batch_rows() -> None:
    operational = person(PID, status="ACTIVE")  # is_test_data FALSE
    other_batch = test_row(PID2, test_batch_id="SYN-OTHER-BATCH")
    repo = repo_with(operational, other_batch)
    for pid in (PID, PID2):
        response = await post(p("deactivations", pid), body(), repo)
        assert (response.status_code, _err(response)["code"]) == (404, "PERSONNEL_NOT_FOUND")
    assert repo.registry_write_log == [] and operational["active_status"] == "ACTIVE"
    mixed = repo_with(operational, test_row(PID))  # same id: only the TRUE row of this batch is targeted
    assert (await post(p("deactivations"), body(), mixed)).status_code == 200
    assert [r["active_status"] for r in mixed._personnel_master] == ["ACTIVE", "INACTIVE"]


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["", " ", "true", "yes", "0"])
async def test_r2e_41_invalid_test_flags_fail_closed(flag) -> None:
    repo = repo_with(test_row(), person("PER-SYN-999", is_test_data=flag))
    response = await post(p("deactivations"), body(), repo)
    assert (response.status_code, _err(response)["code"]) == (500, "PERSONNEL_MASTER_DATA_INVALID")
    assert _err(response)["details"]["issues"] == {"TEST_FLAG_INVALID": 1}
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2e_43_phantom_rows_are_never_targets_and_identity_is_exact() -> None:
    phantom = dict.fromkeys(test_row(), "") | {"is_test_data": "TRUE", "test_batch_id": MOCK_TEST_BATCH_ID}
    repo = repo_with(test_row(), phantom, test_row("0101"))
    for pid in (" " + PID, PID.lower(), "101", " "):
        assert (await post(p("deactivations", pid), body(), repo)).status_code == 404
    assert (await post(p("deactivations", "0101"), body(), repo)).status_code == 200
    dup = repo_with(test_row(), test_row())
    response = await post(p("deactivations"), body(), dup)
    assert (response.status_code, _err(response)["code"]) == (409, "PERSONNEL_ID_AMBIGUOUS")
    assert _err(response)["details"] == {"match_count": 2} and SYN not in response.text


# ===========================================================================
# R2E-45..R2E-50 — domain separation (no account / technician / driver / assignment / R2f)
# ===========================================================================


@pytest.mark.asyncio
async def test_r2e_45_50_personnel_lifecycle_touches_only_its_own_master_and_history() -> None:
    repo = repo_with()
    snapshot = {name: repr(getattr(repo, name)) for name in vars(repo)
                if name.startswith("_") and name not in ("_personnel_master", "_personnel_lifecycle_history",
                                                         "_depth")}
    await post(p("deactivations"), body(), repo)
    await post(p("reactivations"), body("INACTIVE", "เปิด (ทดสอบ)"), repo)
    assert set(repo.calls) <= LIFECYCLE_CALLS
    assert {name: repr(getattr(repo, name)) for name in snapshot} == snapshot  # nothing else changed
    row = repo._personnel_master[0]
    # only active_status changed: department / branch / technician / user / test columns untouched
    assert {k: v for k, v in row.items() if k != "active_status"} == {
        k: v for k, v in test_row().items() if k != "active_status"}


def test_r2e_50_63_no_relationship_routes_and_no_permanent_freeze() -> None:
    """R2e adds lifecycle routes only. It does not forbid future creation,
    relationship or account-linking routes: only the absence of DELETE (an
    approved R2 principle) is asserted elsewhere."""
    personnel_routes = {path for method, path in _routes() if path.startswith(f"{API}/personnel/{{personnel_id}}/")}
    required = {f"{API}/personnel/{{personnel_id}}/{s}" for s in
                ("deactivations", "reactivations", "lifecycle-reconciliations", "lifecycle-history")}
    assert required <= personnel_routes
