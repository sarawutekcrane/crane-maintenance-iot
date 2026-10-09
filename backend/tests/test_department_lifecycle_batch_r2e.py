"""R2 Batch R2e — department lifecycle over HTTP with the MOCK repository
(TEST data context). Batch-local PROPOSED ids R2E-06..08, 12, 15, 23, 24, 31,
35, 37, 42, 44, 49. SYNTHETIC fixtures only (DEPT-SYN- ids are TEST-ONLY, not a
production department id format). The live department_master tab does not
exist; the department lifecycle is verified on mock / fake data only.
"""
from __future__ import annotations

import uuid

import pytest

from app.domain.lifecycle_schema import DEPARTMENT_LIFECYCLE_HISTORY_COLUMNS
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.repositories.mock import MockRepository
from tests.test_personnel_lifecycle_batch_r2e import LIFECYCLE_CALLS, OTHER_ROLES, Spy
from tests.test_personnel_lifecycle_batch_r2e import post as _post
from tests.test_personnel_lifecycle_batch_r2e import test_row as personnel_row
from tests.test_registration_write_batch7o2b import _http

API = "/api/v1"
DID, DID2 = "DEPT-SYN-101", "DEPT-SYN-102"
SYN = " (สังเคราะห์)"


def dept_row(did: str = DID, active: str = "TRUE", **extra: str) -> dict[str, str]:
    row = {"department_id": did, "department_name_th": "แผนกทดสอบ" + SYN, "is_active": active,
           "is_test_data": "TRUE", "test_batch_id": MOCK_TEST_BATCH_ID}
    row.update(extra)
    return row


def repo_with(*rows) -> Spy:
    repo = Spy()
    repo._department_master = [*rows] if rows else [dept_row()]
    return repo


def body(expected=True, reason="ปิดใช้งานแผนก (ทดสอบ)", **extra) -> dict:
    return {"expected_is_active": expected, "reason_th": reason, **extra}


def p(op: str, did: str = DID) -> str:
    return f"{API}/departments/{did}/{op}"


async def post(path, payload, repo, **kw):
    return await _post(path, payload, repo, **kw)


def _err(response) -> dict:
    return response.json()["error"]


def _active(repo, did: str = DID) -> str:
    return next(r for r in repo._department_master if r["department_id"] == did and r["is_test_data"] == "TRUE")[
        "is_active"]


async def history(repo, did: str = DID) -> dict:
    response = await _http("GET", p("lifecycle-history", did), repo=repo, request_id=None)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_r2e_06_deactivate_true_to_false() -> None:
    repo = repo_with()
    response = await post(p("deactivations"), body(), repo)
    assert response.status_code == 200, response.text
    assert (response.json()["previous_state"], response.json()["new_state"],
            response.json()["lifecycle_consistency_after"]) == (True, False, "CONSISTENT")
    assert _active(repo) == "FALSE" and repo.registry_write_log == ["W1", "W2"]
    (event,) = repo._department_lifecycle_history
    assert list(event) == list(DEPARTMENT_LIFECYCLE_HISTORY_COLUMNS)
    assert (event["event_kind"], event["previous_state"], event["new_state"]) == ("DEACTIVATE", "TRUE", "FALSE")


@pytest.mark.asyncio
async def test_r2e_07_12_reactivate_false_to_true_keeps_id_and_name() -> None:
    repo = repo_with(dept_row(active="FALSE"))
    response = await post(p("reactivations"), body(False, "เปิดใช้งานแผนก (ทดสอบ)"), repo)
    assert (response.json()["previous_state"], response.json()["new_state"]) == (False, True)
    (row,) = repo._department_master
    assert {k: v for k, v in row.items() if k != "is_active"} == {
        k: v for k, v in dept_row().items() if k != "is_active"}  # id, name, flags unchanged
    assert row["is_active"] == "TRUE"


@pytest.mark.asyncio
async def test_r2e_08_stale_is_checked_before_no_op() -> None:
    repo = repo_with(dept_row(active="FALSE"))
    stale = await post(p("deactivations"), body(True), repo)
    assert (stale.status_code, _err(stale)["code"]) == (409, "DEPARTMENT_LIFECYCLE_STALE")
    assert _err(stale)["details"] == {"field": "is_active"}
    noop = await post(p("deactivations"), body(False), repo)
    assert noop.json() == {"request_id": noop.json()["request_id"], "changed": False}
    assert repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["", "true", "1", "YES", " TRUE"])
async def test_r2e_department_unknown_current_state_is_refused(current) -> None:
    repo = repo_with(dept_row(active=current))
    response = await post(p("deactivations"), body(), repo)
    assert (response.status_code, _err(response)["code"]) == (422, "DEPARTMENT_LIFECYCLE_STATE_INVALID")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("expected", ["TRUE", 1, "true", None])
async def test_r2e_department_expected_flag_is_a_strict_boolean(expected) -> None:
    repo = repo_with()
    response = await post(p("deactivations"), body(expected), repo)
    assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR")
    assert repo.calls == []


@pytest.mark.asyncio
async def test_r2e_15_department_capability_holders() -> None:
    for role in ("ADMIN", "MAINTENANCE_MANAGER"):
        assert (await post(p("deactivations"), body(), repo_with(), role=role)).status_code == 200
    for role in OTHER_ROLES:
        repo = repo_with()
        assert (await post(p("deactivations"), body(), repo, role=role)).status_code == 403
        assert repo.calls == []


@pytest.mark.asyncio
async def test_r2e_23_24_replay_and_reuse_within_the_department_tab() -> None:
    repo = repo_with(dept_row(), dept_row(DID2))
    rid = str(uuid.uuid4())
    first = await post(p("deactivations"), body(), repo, request_id=rid)
    again = await post(p("deactivations"), body(), repo, request_id=rid)
    assert again.json() == {"request_id": rid, "replayed": True, "record_ids": [first.json()["record_id"]]}
    other = await post(p("deactivations", DID2), body(), repo, request_id=rid)
    assert (other.status_code, _err(other)["code"]) == (409, "REQUEST_ID_REUSED")
    assert len(repo._department_lifecycle_history) == 1


@pytest.mark.asyncio
async def test_r2e_28_31_state_write_failure_then_reconciliation() -> None:
    repo = repo_with()
    repo.registry_write_faults["W2"] = "unknown_not_applied"
    rid = str(uuid.uuid4())
    failed = await post(p("deactivations"), body(), repo, request_id=rid)
    assert (failed.status_code, _err(failed)["code"]) == (503, "DEPARTMENT_LIFECYCLE_STATE_WRITE_FAILED")
    assert _err(failed)["details"]["event_recorded"] is True
    repo.registry_write_faults.clear()
    assert (await history(repo))["lifecycle_consistency"] == "MISMATCH"
    blocked = await post(p("reactivations"), body(True), repo)
    assert _err(blocked)["code"] == "DEPARTMENT_LIFECYCLE_MISMATCH"
    fixed = await post(p("lifecycle-reconciliations"), body(True, "ซิงก์สถานะ (ทดสอบ)"), repo)
    assert fixed.status_code == 200 and (fixed.json()["previous_state"], fixed.json()["new_state"]) == (True, False)
    assert repo._department_lifecycle_history[-1]["related_request_id"] == rid
    assert _active(repo) == "FALSE" and (await history(repo))["lifecycle_consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_r2e_35_department_lifecycle_history_response() -> None:
    repo = repo_with()
    assert (await history(repo)) == {"entity_id": DID, "current_state": True, "latest_history_state": None,
                                     "lifecycle_consistency": "NO_HISTORY", "events": []}
    await post(p("deactivations"), body(), repo)
    read = await history(repo)
    assert (read["current_state"], read["latest_history_state"], read["lifecycle_consistency"]) == (
        False, False, "CONSISTENT")
    assert (read["events"][0]["previous_state"], read["events"][0]["new_state"]) == (True, False)
    assert "test_batch_id" not in str(read) and "request_fingerprint" not in str(read)


@pytest.mark.asyncio
async def test_r2e_37_existing_department_get_contract_unchanged() -> None:
    from app.main import create_app

    schema = create_app().openapi()["components"]["schemas"]["DepartmentResponse"]
    assert set(schema["properties"]) == {"department_id", "department_name_th", "is_active"}
    listed = (await _http("GET", f"{API}/departments", repo=MockRepository(), request_id=None)).json()
    assert listed["total_items"] == 2 and "lifecycle" not in str(listed)


@pytest.mark.asyncio
async def test_r2e_42_44_scope_flags_phantoms_and_ambiguity() -> None:
    operational = dept_row(is_test_data="FALSE", test_batch_id="")
    repo = repo_with(operational, dept_row(DID2, test_batch_id="SYN-OTHER"))
    for did in (DID, DID2):
        assert (await post(p("deactivations", did), body(), repo)).status_code == 404
    assert operational["is_active"] == "TRUE"
    phantom = {"department_id": "", "department_name_th": "", "is_active": "", "is_test_data": "junk",
               "test_batch_id": ""}
    with_phantom = repo_with(dept_row(), phantom)
    assert (await post(p("deactivations"), body(), with_phantom)).status_code == 200  # phantom skipped
    bad_flag = repo_with(dept_row(), dept_row("DEPT-SYN-999", is_test_data="maybe"))
    response = await post(p("deactivations"), body(), bad_flag)
    assert (response.status_code, _err(response)["code"]) == (500, "DEPARTMENT_MASTER_DATA_INVALID")
    dup = repo_with(dept_row(), dept_row())
    assert _err(await post(p("deactivations"), body(), dup))["code"] == "DEPARTMENT_ID_AMBIGUOUS"


@pytest.mark.asyncio
async def test_r2e_49_department_lifecycle_never_rewrites_personnel() -> None:
    repo = repo_with()
    repo._personnel_master = [personnel_row(department="แผนกทดสอบ" + SYN)]
    before = repr(repo._personnel_master)
    await post(p("deactivations"), body(), repo)
    await post(p("reactivations"), body(False, "เปิด (ทดสอบ)"), repo)
    assert repr(repo._personnel_master) == before and repo._personnel_lifecycle_history == []
    assert set(repo.calls) <= LIFECYCLE_CALLS
