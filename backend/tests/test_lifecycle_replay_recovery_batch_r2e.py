"""R2 Batch R2e — independent-review fix R2: replay after an incomplete
lifecycle write, for BOTH personnel and department (MOCK repository, TEST
context, SYNTHETIC rows only).

Rule: an exact replay is successful only when the entity is not in lifecycle
MISMATCH. When an earlier W1 exists but its W2 is incomplete (an unknown-applied
W1, or a known W2 failure), resending the same request returns
<ENTITY>_LIFECYCLE_MISMATCH — never replay success and never a W2 retry; the
recovery stays an explicit reconciliation. An unknown W1 that was NOT applied
leaves no history, so the same resend proceeds normally. A request id reused
with another fingerprint is still REQUEST_ID_REUSED.
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_lifecycle_audit_integrity_batch_r2e import (
    ENTITIES,
    body,
    read,
    repo_for,
)
from tests.test_personnel_lifecycle_batch_r2e import post as _post


def path(name: str, op: str = "deactivations") -> str:
    e = ENTITIES[name]
    return f"/api/v1/{e['path']}/{e['id']}/{op}"


def history(repo, name: str) -> list[dict]:
    return getattr(repo, ENTITIES[name]["history"])


def master_state(repo, name: str) -> str:
    if name == "personnel":
        return repo._personnel_master[0]["active_status"]
    return repo._department_master[0]["is_active"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_recovery_1_unknown_applied_w1_resend_is_mismatch_not_replay(name) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["active"])
    repo.registry_write_faults["W1"] = "unknown_applied"
    rid = str(uuid.uuid4())
    payload = body(name, e["active"])
    first = await _post(path(name), payload, repo, request_id=rid)
    assert (first.status_code, first.json()["error"]["code"]) == (503, f"{e['label']}_LIFECYCLE_HISTORY_WRITE_FAILED")
    assert first.json()["error"]["details"]["history_write_outcome"] == "unknown"
    assert repo.registry_write_log == ["W1"]  # W2 not attempted
    assert len(history(repo, name)) == 1 and master_state(repo, name) == e["active"]
    assert (await read(repo, name)).json()["lifecycle_consistency"] == "MISMATCH"
    repo.registry_write_faults.clear()
    again = await _post(path(name), payload, repo, request_id=rid)  # SAME request id + body
    assert (again.status_code, again.json()["error"]["code"]) == (409, f"{e['label']}_LIFECYCLE_MISMATCH")
    assert "replayed" not in again.text
    assert repo.registry_write_log == ["W1"]  # no new W1, no W2, no retry
    assert len(history(repo, name)) == 1 and master_state(repo, name) == e["active"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_recovery_2_unknown_not_applied_w1_resend_completes_normally(name) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["active"])
    repo.registry_write_faults["W1"] = "unknown_not_applied"
    rid = str(uuid.uuid4())
    payload = body(name, e["active"])
    first = await _post(path(name), payload, repo, request_id=rid)
    assert first.status_code == 503 and first.json()["error"]["details"]["history_write_outcome"] == "unknown"
    assert history(repo, name) == []
    repo.registry_write_faults.clear()
    again = await _post(path(name), payload, repo, request_id=rid)
    assert again.status_code == 200, again.text
    assert again.json()["changed"] is True and again.json()["lifecycle_consistency_after"] == "CONSISTENT"
    assert repo.registry_write_log == ["W1", "W1", "W2"]
    assert master_state(repo, name) == e["inactive"]
    assert (await read(repo, name)).json()["lifecycle_consistency"] == "CONSISTENT"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
@pytest.mark.parametrize("fault", ["rejected", "unknown_not_applied"])
async def test_r2e_recovery_3_known_w2_failure_resend_is_mismatch(name, fault) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["active"])
    repo.registry_write_faults["W2"] = fault
    rid = str(uuid.uuid4())
    payload = body(name, e["active"])
    first = await _post(path(name), payload, repo, request_id=rid)
    assert first.json()["error"]["code"] == f"{e['label']}_LIFECYCLE_STATE_WRITE_FAILED"
    repo.registry_write_faults.clear()
    again = await _post(path(name), payload, repo, request_id=rid)
    assert (again.status_code, again.json()["error"]["code"]) == (409, f"{e['label']}_LIFECYCLE_MISMATCH")
    assert repo.registry_write_log == ["W1", "W2"]  # nothing new
    assert len(history(repo, name)) == 1 and master_state(repo, name) == e["active"]
    # recovery is an explicit reconciliation (a NEW request with a reason)
    fixed = await _post(path(name, "lifecycle-reconciliations"), body(name, e["active"]), repo)
    assert fixed.status_code == 200 and fixed.json()["changed"] is True
    assert master_state(repo, name) == e["inactive"]
    # once consistent, the ORIGINAL request replays normally again
    replay = await _post(path(name), payload, repo, request_id=rid)
    assert replay.status_code == 200 and replay.json()["replayed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_recovery_reconciliation_replay_while_mismatch_is_not_success(name) -> None:
    """A reconciliation whose own W2 failed is not replayed as a success either."""
    e = ENTITIES[name]
    repo = repo_for(name, e["active"])
    repo.registry_write_faults["W2"] = "rejected"
    await _post(path(name), body(name, e["active"]), repo)
    rid = str(uuid.uuid4())
    payload = body(name, e["active"])
    failed = await _post(path(name, "lifecycle-reconciliations"), payload, repo, request_id=rid)
    assert failed.json()["error"]["code"] == f"{e['label']}_LIFECYCLE_STATE_WRITE_FAILED"
    repo.registry_write_faults.clear()
    again = await _post(path(name, "lifecycle-reconciliations"), payload, repo, request_id=rid)
    assert (again.status_code, again.json()["error"]["code"]) == (409, f"{e['label']}_LIFECYCLE_MISMATCH")
    assert len(history(repo, name)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
async def test_r2e_recovery_4_completed_request_still_replays(name) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["active"])
    rid = str(uuid.uuid4())
    payload = body(name, e["active"])
    first = await _post(path(name), payload, repo, request_id=rid)
    assert first.status_code == 200
    again = await _post(path(name), payload, repo, request_id=rid)
    assert again.json() == {"request_id": rid, "replayed": True, "record_ids": [first.json()["record_id"]]}
    assert repo.registry_write_log == ["W1", "W2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(ENTITIES))
@pytest.mark.parametrize("state", ["consistent", "mismatch"])
async def test_r2e_recovery_5_request_id_reuse_is_still_detected_first(name, state) -> None:
    e = ENTITIES[name]
    repo = repo_for(name, e["active"])
    if state == "mismatch":
        repo.registry_write_faults["W2"] = "rejected"
    rid = str(uuid.uuid4())
    await _post(path(name), body(name, e["active"]), repo, request_id=rid)
    repo.registry_write_faults.clear()
    other = {**body(name, e["active"]), "reason_th": "อื่น"}  # same request id, different fingerprint
    response = await _post(path(name), other, repo, request_id=rid)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "REQUEST_ID_REUSED")
    assert len(history(repo, name)) == 1
