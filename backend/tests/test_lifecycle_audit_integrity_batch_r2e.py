"""R2 Batch R2e — independent-review fix R1: lifecycle-history audit-reference
integrity for RECONCILIATION rows, for BOTH personnel and department (MOCK
repository, TEST context, SYNTHETIC rows only).

A reconciliation's `related_request_id` must reference a PRIOR event of the same
scoped entity history (else RELATED_REQUEST_DANGLING), that event's `new_state`
must equal the reconciliation's `new_state` (else RELATED_STATE_MISMATCH), and a
reconciliation must change the state (previous == new is TRANSITION_INVALID). An
invalid history fails closed on reads and before any mutation. These tests
validate the current three-event R2e contract only; they do not forbid future
event kinds, correction workflows or audit tables.
"""
from __future__ import annotations

import hashlib
import uuid

import pytest

from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from tests.test_department_lifecycle_batch_r2e import dept_row
from tests.test_personnel_lifecycle_batch_r2e import Spy
from tests.test_personnel_lifecycle_batch_r2e import post as _post
from tests.test_personnel_lifecycle_batch_r2e import test_row as personnel_row
from tests.test_registration_write_batch7o2b import _http

API = "/api/v1"
ENTITIES = {
    "personnel": {
        "path": "personnel", "id": "PER-SYN-301", "id_column": "personnel_id", "label": "PERSONNEL",
        "active": "ACTIVE", "inactive": "INACTIVE", "history": "_personnel_lifecycle_history",
        "expected": lambda state: {"expected_active_status": state},
    },
    "department": {
        "path": "departments", "id": "DEPT-SYN-301", "id_column": "department_id", "label": "DEPARTMENT",
        "active": "TRUE", "inactive": "FALSE", "history": "_department_lifecycle_history",
        "expected": lambda state: {"expected_is_active": state == "TRUE"},
    },
}


def repo_for(name: str, current: str) -> Spy:
    e = ENTITIES[name]
    repo = Spy()
    if name == "personnel":
        repo._personnel_master = [personnel_row(e["id"], status=current)]
    else:
        repo._department_master = [dept_row(e["id"], active=current)]
    return repo


def event(name: str, kind: str, previous: str, new: str, request_id: str, related: str = "", **extra) -> dict:
    """A synthetic, otherwise strictly valid lifecycle-history row."""
    e = ENTITIES[name]
    row = {
        "lifecycle_event_id": f"LH-SYN-{uuid.uuid4().hex}",
        e["id_column"]: e["id"],
        "event_kind": kind,
        "previous_state": previous,
        "new_state": new,
        "recorded_at": "2026-10-01T03:00:00+00:00",
        "recorded_by": "synthetic",
        "request_id": request_id,
        "request_fingerprint": hashlib.sha256(request_id.encode()).hexdigest(),
        "reason_th": "ข้อมูลสังเคราะห์",
        "is_test_data": "TRUE",
        "test_batch_id": MOCK_TEST_BATCH_ID,
        "related_request_id": related,
    }
    row.update(extra)
    return row


def body(name: str, current: str) -> dict:
    return {**ENTITIES[name]["expected"](current), "reason_th": "ทดสอบ"}


async def read(repo, name: str):
    e = ENTITIES[name]
    return await _http("GET", f"{API}/{e['path']}/{e['id']}/lifecycle-history", repo=repo, request_id=None)


def assert_invalid(response, name: str, issues: dict[str, int]) -> None:
    e = ENTITIES[name]
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (500, f"{e['label']}_LIFECYCLE_HISTORY_DATA_INVALID")
    assert error["details"]["issues"] == issues
    # issue counts only: no entity id, request id or row reference
    assert e["id"] not in response.text and "rq-" not in response.text and "LH-SYN" not in response.text


async def assert_fails_closed_everywhere(repo, name: str, current: str, issues: dict[str, int]) -> None:
    """The read and every mutation fail closed before any write."""
    e = ENTITIES[name]
    assert_invalid(await read(repo, name), name, issues)
    for op in ("deactivations", "reactivations", "lifecycle-reconciliations"):
        response = await _post(f"{API}/{e['path']}/{e['id']}/{op}", body(name, current), repo)
        assert_invalid(response, name, issues)
    assert repo.registry_write_log == []


# ---------------------------------------------------------------------------
# A — a valid generated reconciliation still passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_audit_a_generated_reconciliation_remains_valid(name) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["active"])
    repo.registry_write_faults["W2"] = "rejected"
    first = str(uuid.uuid4())
    await _post(f"{API}/{e['path']}/{e['id']}/deactivations", body(name, e["active"]), repo, request_id=first)
    repo.registry_write_faults.clear()
    fixed = await _post(f"{API}/{e['path']}/{e['id']}/lifecycle-reconciliations", body(name, e["active"]), repo)
    assert fixed.status_code == 200 and fixed.json()["changed"] is True
    reconciliation = getattr(repo, e["history"])[-1]
    assert (reconciliation["event_kind"], reconciliation["related_request_id"]) == ("RECONCILIATION", first)
    read_back = await read(repo, name)
    assert read_back.status_code == 200 and read_back.json()["lifecycle_consistency"] == "CONSISTENT"
    # a later normal action still works on top of the reconciled history
    again = await _post(f"{API}/{e['path']}/{e['id']}/reactivations", body(name, e["inactive"]), repo)
    assert again.status_code == 200 and again.json()["changed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_audit_a_reference_to_an_earlier_non_adjacent_event_is_valid(name) -> None:
    """The referenced event need not be the immediately preceding row
    (non-transactional appends): only prior + same scope + same new_state."""
    e = ENTITIES[name]
    repo = repo_for(name, e["inactive"])
    getattr(repo, e["history"]).extend([
        event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-1"),
        event(name, "REACTIVATE", e["inactive"], e["active"], "rq-2"),
        event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-3"),
        event(name, "RECONCILIATION", e["active"], e["inactive"], "rq-4", related="rq-1"),
    ])
    response = await read(repo, name)
    assert response.status_code == 200 and response.json()["lifecycle_consistency"] == "CONSISTENT"


# ---------------------------------------------------------------------------
# B / C — missing, nonexistent, self, future and out-of-scope references
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
@pytest.mark.parametrize("case", ["nonexistent", "self", "future", "other-scope", "other-entity"])
async def test_r2e_audit_b_c_dangling_references_fail_closed(name, case) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["inactive"])
    history = getattr(repo, e["history"])
    history.append(event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-1"))
    related = {"nonexistent": "rq-missing", "self": "rq-2", "future": "rq-3", "other-scope": "rq-x",
               "other-entity": "rq-y"}[case]
    history.append(event(name, "RECONCILIATION", e["active"], e["inactive"], "rq-2", related=related))
    if case == "future":
        history.append(event(name, "REACTIVATE", e["inactive"], e["active"], "rq-3"))
        repo_state = e["active"]
    else:
        repo_state = e["inactive"]
    if case == "other-scope":  # an event of the same entity in another data-context scope
        history.insert(0, event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-x", is_test_data="FALSE",
                                test_batch_id=""))
    if case == "other-entity":  # an event of another entity in the same tab
        history.insert(0, event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-y",
                                **{e["id_column"]: e["id"] + "-OTHER"}))
    if case == "future":
        repo = _with_state(repo, name, repo_state)
    await assert_fails_closed_everywhere(repo, name, repo_state, {"RELATED_REQUEST_DANGLING": 1})


def _with_state(repo, name: str, state: str):
    if name == "personnel":
        repo._personnel_master[0]["active_status"] = state
    else:
        repo._department_master[0]["is_active"] = state
    return repo


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_audit_b_blank_related_request_id_remains_required(name) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["inactive"])
    getattr(repo, e["history"]).extend([
        event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-1"),
        event(name, "RECONCILIATION", e["active"], e["inactive"], "rq-2", related=" "),
    ])
    await assert_fails_closed_everywhere(repo, name, e["inactive"], {"FIELD_REQUIRED:related_request_id": 1})


# ---------------------------------------------------------------------------
# D — the referenced event's new_state must equal the reconciliation's
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_audit_d_related_state_mismatch_fails_closed(name) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["active"])
    getattr(repo, e["history"]).extend([
        event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-1"),
        # claims to reconcile rq-1 (desired INACTIVE / FALSE) but writes the active state
        event(name, "RECONCILIATION", e["inactive"], e["active"], "rq-2", related="rq-1"),
    ])
    await assert_fails_closed_everywhere(repo, name, e["active"], {"RELATED_STATE_MISMATCH": 1})


# ---------------------------------------------------------------------------
# E — a reconciliation must repair a real difference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_audit_e_same_state_reconciliation_is_transition_invalid(name) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["inactive"])
    getattr(repo, e["history"]).extend([
        event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-1"),
        event(name, "RECONCILIATION", e["inactive"], e["inactive"], "rq-2", related="rq-1"),
    ])
    await assert_fails_closed_everywhere(repo, name, e["inactive"], {"TRANSITION_INVALID": 1})


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_audit_normal_events_keep_a_blank_related_request_id(name) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["inactive"])
    getattr(repo, e["history"]).extend([
        event(name, "REACTIVATE", e["inactive"], e["active"], "rq-0"),
        event(name, "DEACTIVATE", e["active"], e["inactive"], "rq-1", related="rq-0"),
    ])
    await assert_fails_closed_everywhere(repo, name, e["inactive"], {"FIELD_MUST_BE_BLANK:related_request_id": 1})
