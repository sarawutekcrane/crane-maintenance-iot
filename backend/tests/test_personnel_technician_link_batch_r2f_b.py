"""R2 Batch R2f-b — Personnel ↔ Technician link writes, mock / service level.

Final Contract C1 §5 / §15 / §17 / §19 and the R2f-b authorization. Every row
is SYNTHETIC and labelled; no live workbook value or production count is used.
TEST-scoped technicians are explicit synthetic fixtures (scope TEST + batch),
never derived from an id. REAL-context cases run against the service directly
(mock mode is always the TEST context at the API).

Batch-local ids: R2FB-AUTH, -LINK, -UNLINK, -RELINK, -STALE, -HIST, -REPLAY,
-W1W2, -RECON, -SCOPE, -NOCASCADE.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.personnel_link import CONSISTENCY_CONSISTENT, CONSISTENCY_MISMATCH, CONSISTENCY_NO_HISTORY
from app.domain.personnel_technician_link import (
    PERSONNEL_TECHNICIAN_LINK_HISTORY_COLUMNS,
    personnel_technician_link_service,
)
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_TEST
from tests.test_relationship_read_batch_r2f_a import RelSpy, person, tech

API = "/api/v1"
BATCH = "SYN-R2FB-BATCH"
REASON = "แก้ไขข้อมูลหลัก (ทดสอบ)"
T1, T2, T3 = "TEC-SYN-1", "TEC-SYN-2", "TEC-SYN-3"
LINK_METHODS = {"read_personnel_link_master", "read_personnel_link_history_validated",
                "read_technician_master_reference", "append_personnel_link_history", "write_personnel_link_cell"}


def body(operation: str, expected: str = "", new: str | None = None, reason: str = REASON) -> dict:
    out = {"operation": operation, "expected_technician_id": expected, "reason_th": reason}
    if new is not None:
        out["new_technician_id"] = new
    return out


def rbody(expected: str, related: str, reason: str = REASON) -> dict:
    return {"expected_technician_id": expected, "related_request_id": related, "reason_th": reason}


def repo_with(people=None, technicians=None) -> RelSpy:
    return RelSpy(
        people=people if people is not None else [person("P-1"), person("P-2", technician_id=T2)],
        technicians=technicians if technicians is not None else [tech(T1), tech(T2), tech(T3)],
    )


def svc(repo, context: str = "REAL", batch: str = BATCH):
    return personnel_technician_link_service(repo, context, batch)


async def change(repo, pid: str, payload: dict, *, context: str = "REAL", batch: str = BATCH,
                 request_id: str | None = None):
    return await svc(repo, context, batch).change(pid, payload, request_id=request_id or str(uuid.uuid4()),
                                                   user_id="dev-user")


async def reconcile(repo, pid: str, payload: dict, *, context: str = "REAL", request_id: str | None = None):
    return await svc(repo, context).reconcile(pid, payload, request_id=request_id or str(uuid.uuid4()),
                                              user_id="dev-user")


async def code_of(coro) -> str:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value.code


def cell(repo, pid: str, *, test: bool = False) -> str:
    flag = "TRUE" if test else "FALSE"
    (row,) = [r for r in repo._personnel_master if r["personnel_id"] == pid and r["is_test_data"] == flag]
    return row["technician_id"]


def history(repo) -> list[dict[str, str]]:
    return repo._personnel_technician_link_history


async def http(method: str, path: str, repo, *, role: str = "MAINTENANCE_MANAGER", json=None,
               request_id: str | None = "auto"):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    headers = {"X-Dev-Role": role}
    if request_id is not None:
        headers["X-Request-Id"] = str(uuid.uuid4()) if request_id == "auto" else request_id
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def tperson(pid: str, technician_id: str = "") -> dict[str, str]:
    return person(pid, technician_id=technician_id, test=True, batch=MOCK_TEST_BATCH_ID)


def ttech(tid: str):
    return tech(tid, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)


# ---------------------------------------------------------------------------
# R2FB-AUTH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE_MANAGER"])
async def test_r2fb_auth_admin_and_maintenance_manager_may_link(role) -> None:
    repo = RelSpy(people=[tperson("P-T")], technicians=[ttech("TEC-T1")])
    response = await http("POST", f"{API}/personnel/P-T/technician-links", repo, role=role,
                          json=body("LINK", "", "TEC-T1"))
    assert response.status_code == 200 and response.json()["changed"] is True
    assert cell(repo, "P-T", test=True) == "TEC-T1"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "SUPERVISOR", "MAINTENANCE", "NO_SUCH_ROLE"])
@pytest.mark.parametrize("suffix", ["technician-links", "technician-links/reconcile"])
async def test_r2fb_auth_other_roles_are_refused_with_zero_repository_calls(role, suffix) -> None:
    repo = RelSpy(people=[tperson("P-T")], technicians=[ttech("TEC-T1")])
    payload = body("LINK", "", "TEC-T1") if suffix == "technician-links" else rbody("", "x")
    response = await http("POST", f"{API}/personnel/P-T/{suffix}", repo, role=role, json=payload)
    assert response.status_code == 403
    assert repo.calls == [] and repo.registry_write_log == []


def test_r2fb_auth_capability_holders_are_exact() -> None:
    from app.domain import authz

    cap = authz.CAN_LINK_PERSONNEL_TECHNICIAN
    assert cap == "can_link_personnel_technician" and cap in authz.ALL_CAPABILITIES
    holders = {role for role, caps in authz.ROLE_CAPABILITIES.items() if cap in caps}
    assert holders == {"ADMIN", "MAINTENANCE_MANAGER"}
    # separate from the lifecycle capability: neither implies the other
    assert authz.CAN_MANAGE_PERSONNEL != cap


@pytest.mark.asyncio
async def test_r2fb_auth_request_id_and_body_are_checked_before_any_read() -> None:
    repo = RelSpy(people=[tperson("P-T")])
    no_id = await http("POST", f"{API}/personnel/P-T/technician-links", repo, json=body("LINK", "", "X"),
                       request_id=None)
    assert (no_id.status_code, no_id.json()["error"]["code"]) == (422, "REQUEST_ID_REQUIRED")
    for bad in ({**body("LINK", "", "X"), "recorded_by": "x"}, {**body("LINK", "", "X"), "operation": "MERGE"},
                {"operation": "LINK", "new_technician_id": "X", "reason_th": REASON}):
        response = await http("POST", f"{API}/personnel/P-T/technician-links", repo, json=bad)
        assert response.status_code == 422, bad
    arbitrary = await http("POST", f"{API}/personnel/P-T/technician-links/reconcile", repo,
                           json={**rbody("", "x"), "new_technician_id": "X"})
    assert arbitrary.status_code == 422  # a reconciliation can never name its own target
    assert repo.calls == []


@pytest.mark.asyncio
async def test_r2fb_auth_reason_and_target_shape_are_refused_before_reads() -> None:
    repo = repo_with()
    for payload, code in ((body("LINK", "", T1, reason="  "), "REASON_REQUIRED"),
                          (body("LINK", "", T1, reason="x" * 501), "REASON_REQUIRED"),
                          (body("LINK", "", None), "PERSONNEL_TECHNICIAN_LINK_TARGET_REQUIRED"),
                          (body("RELINK", T2, "  "), "PERSONNEL_TECHNICIAN_LINK_TARGET_REQUIRED"),
                          (body("UNLINK", T2, T1), "PERSONNEL_TECHNICIAN_LINK_TARGET_NOT_ALLOWED")):
        assert await code_of(change(repo, "P-1", payload)) == code
    assert repo.calls == []


# ---------------------------------------------------------------------------
# R2FB-LINK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fb_link_blank_to_target_writes_history_then_cell() -> None:
    repo = repo_with()
    outcome = await change(repo, "P-1", body("LINK", "", T1), request_id="11111111-1111-4111-8111-111111111111")
    assert (outcome.changed, outcome.previous_id, outcome.new_id, outcome.consistency_after) == (
        True, "", T1, CONSISTENCY_CONSISTENT)
    assert repo.registry_write_log == ["W1", "W2"]
    assert cell(repo, "P-1") == T1
    (row,) = history(repo)
    assert set(row) == set(PERSONNEL_TECHNICIAN_LINK_HISTORY_COLUMNS)
    assert (row["event_kind"], row["previous_technician_id"], row["new_technician_id"]) == ("LINK", "", T1)
    assert (row["recorded_by"], row["is_test_data"], row["test_batch_id"], row["related_request_id"]) == (
        "dev-user", "FALSE", "", "")
    assert row["link_event_id"] == outcome.record_id and row["link_event_id"].startswith("PTL-")
    assert row["request_id"] == "11111111-1111-4111-8111-111111111111" and len(row["request_fingerprint"]) == 64


@pytest.mark.asyncio
async def test_r2fb_link_same_target_is_a_no_op_after_guards() -> None:
    repo = repo_with()
    outcome = await change(repo, "P-2", body("LINK", T2, T2))
    assert (outcome.changed, repo.registry_write_log, history(repo)) == (False, [], [])


@pytest.mark.asyncio
async def test_r2fb_link_over_another_target_requires_relink() -> None:
    repo = repo_with()
    assert await code_of(change(repo, "P-2", body("LINK", T2, T3))) == "PERSONNEL_TECHNICIAN_LINK_RELINK_REQUIRED"
    assert repo.registry_write_log == [] and cell(repo, "P-2") == T2


@pytest.mark.asyncio
async def test_r2fb_link_target_missing_duplicate_owned_and_exact_only() -> None:
    repo = repo_with(technicians=[tech(T1), tech(T2), tech("TEC-SYN-D"), tech("TEC-SYN-D")])
    assert await code_of(change(repo, "P-1", body("LINK", "", "TEC-SYN-404"))) == "TECHNICIAN_NOT_FOUND"
    assert await code_of(change(repo, "P-1", body("LINK", "", "TEC-SYN-D"))) == "TECHNICIAN_ID_AMBIGUOUS"
    for near in ("tec-syn-1", " TEC-SYN-1", "TEC-SYN-1 ", "TEC-SYN"):
        assert await code_of(change(repo, "P-1", body("LINK", "", near))) == "TECHNICIAN_NOT_FOUND", near
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("LINK", "", T2))  # held by P-2
    assert (exc.value.code, exc.value.details) == ("TECHNICIAN_ALREADY_LINKED", {"technician_id": T2})
    assert "P-2" not in str(exc.value.details)
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fb_link_needs_no_lifecycle_gate() -> None:
    """OD-5 governs NEW work assignments, not identity-link maintenance."""
    inactive = person("P-I", technician_id="")
    inactive["active_status"] = "INACTIVE"
    repo = repo_with(people=[inactive], technicians=[tech(T1, status="INACTIVE")])
    assert (await change(repo, "P-I", body("LINK", "", T1))).changed is True
    assert repo._personnel_master[0]["active_status"] == "INACTIVE"


# ---------------------------------------------------------------------------
# R2FB-UNLINK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fb_unlink_sets_a_true_blank_and_records_history_first() -> None:
    repo = repo_with()
    outcome = await change(repo, "P-2", body("UNLINK", T2))
    assert (outcome.changed, outcome.previous_id, outcome.new_id) == (True, T2, "")
    assert repo.registry_write_log == ["W1", "W2"]
    assert cell(repo, "P-2") == ""
    (row,) = history(repo)
    assert (row["event_kind"], row["previous_technician_id"], row["new_technician_id"]) == ("UNLINK", T2, "")


@pytest.mark.asyncio
async def test_r2fb_unlink_when_blank_is_a_no_op_and_stale_is_refused() -> None:
    repo = repo_with()
    assert (await change(repo, "P-1", body("UNLINK", ""))).changed is False
    assert await code_of(change(repo, "P-2", body("UNLINK", T1))) == "PERSONNEL_TECHNICIAN_LINK_STALE"
    assert repo.registry_write_log == []


# ---------------------------------------------------------------------------
# R2FB-RELINK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fb_relink_old_to_new_same_no_op_and_blank_requires_link() -> None:
    repo = repo_with()
    outcome = await change(repo, "P-2", body("RELINK", T2, T3))
    assert (outcome.changed, outcome.previous_id, outcome.new_id) == (True, T2, T3)
    assert history(repo)[0]["event_kind"] == "RELINK" and cell(repo, "P-2") == T3
    assert (await change(repo, "P-2", body("RELINK", T3, T3))).changed is False
    assert await code_of(change(repo, "P-1", body("RELINK", "", T1))) == "PERSONNEL_TECHNICIAN_LINK_LINK_REQUIRED"


@pytest.mark.asyncio
async def test_r2fb_relink_target_rules() -> None:
    repo = repo_with(people=[person("P-1", technician_id=T1), person("P-2", technician_id=T2)],
                     technicians=[tech(T1), tech(T2), tech("TEC-SYN-D"), tech("TEC-SYN-D")])
    assert await code_of(change(repo, "P-1", body("RELINK", T1, T2))) == "TECHNICIAN_ALREADY_LINKED"
    assert await code_of(change(repo, "P-1", body("RELINK", T1, "TEC-SYN-404"))) == "TECHNICIAN_NOT_FOUND"
    assert await code_of(change(repo, "P-1", body("RELINK", T1, "TEC-SYN-D"))) == "TECHNICIAN_ID_AMBIGUOUS"
    test_repo = RelSpy(people=[tperson("P-T", "TEC-T1")], technicians=[ttech("TEC-T1"), tech(T2)])
    assert await code_of(change(test_repo, "P-T", body("RELINK", "TEC-T1", T2), context="TEST",
                                batch=MOCK_TEST_BATCH_ID)) == "TECHNICIAN_SCOPE_UNPROVEN"
    assert repo.registry_write_log == [] and test_repo.registry_write_log == []


# ---------------------------------------------------------------------------
# R2FB-STALE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fb_stale_is_checked_before_no_op_with_zero_writes() -> None:
    repo = repo_with()
    # intended == current (would be a no-op) but the client expected no link: stale, not success
    assert await code_of(change(repo, "P-2", body("LINK", "", T2))) == "PERSONNEL_TECHNICIAN_LINK_STALE"
    assert await code_of(change(repo, "P-1", body("UNLINK", T1))) == "PERSONNEL_TECHNICIAN_LINK_STALE"
    assert await code_of(change(repo, "P-2", body("RELINK", T1, T2))) == "PERSONNEL_TECHNICIAN_LINK_STALE"
    assert repo.registry_write_log == [] and history(repo) == []


# ---------------------------------------------------------------------------
# R2FB-HIST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fb_hist_pre_existing_link_is_no_history_then_consistent() -> None:
    repo = repo_with()
    before = await svc(repo).history("P-2")
    assert (before.current_id, before.latest_history_id, before.consistency, before.events) == (
        T2, None, CONSISTENCY_NO_HISTORY, ())
    await change(repo, "P-2", body("RELINK", T2, T3))
    after = await svc(repo).history("P-2")
    assert (after.current_id, after.latest_history_id, after.consistency) == (T3, T3, CONSISTENCY_CONSISTENT)


@pytest.mark.asyncio
async def test_r2fb_hist_sequence_has_unique_event_and_request_ids() -> None:
    repo = repo_with()
    await change(repo, "P-1", body("LINK", "", T1))
    await change(repo, "P-1", body("RELINK", T1, T3))
    await change(repo, "P-1", body("UNLINK", T3))
    kinds = [r["event_kind"] for r in history(repo)]
    assert kinds == ["LINK", "RELINK", "UNLINK"]
    assert len({r["link_event_id"] for r in history(repo)}) == 3
    assert len({r["request_id"] for r in history(repo)}) == 3
    read = await svc(repo).history("P-1")
    assert (read.current_id, read.consistency, len(read.events)) == (None, CONSISTENCY_CONSISTENT, 3)


def _valid_row(**overrides) -> dict[str, str]:
    row = {"link_event_id": "PTL-" + "a" * 32, "personnel_id": "P-1", "event_kind": "LINK",
           "previous_technician_id": "", "new_technician_id": T1, "recorded_at": "2026-10-01T00:00:00+00:00",
           "recorded_by": "u", "request_id": "r-1", "request_fingerprint": "f" * 64, "reason_th": "x",
           "is_test_data": "FALSE", "test_batch_id": "", "related_request_id": ""}
    row.update(overrides)
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize(("overrides", "issue"), [
    ({"event_kind": "MERGE"}, "EVENT_KIND_INVALID"),
    ({"previous_technician_id": T2}, "EVENT_SHAPE_INVALID"),
    ({"event_kind": "UNLINK", "previous_technician_id": "", "new_technician_id": ""}, "EVENT_SHAPE_INVALID"),
    ({"event_kind": "RELINK", "previous_technician_id": T1}, "EVENT_SHAPE_INVALID"),
    ({"recorded_at": "2026-10-01T00:00:00"}, "RECORDED_AT_INVALID"),
    ({"recorded_by": " "}, "FIELD_REQUIRED:recorded_by"),
    ({"reason_th": ""}, "FIELD_REQUIRED:reason_th"),
    ({"request_fingerprint": "nope"}, "FINGERPRINT_INVALID"),
    ({"test_batch_id": "SYN-X"}, "SCOPE_INCONSISTENT"),
    ({"related_request_id": "r-0"}, "FIELD_MUST_BE_BLANK:related_request_id"),
])
async def test_r2fb_hist_malformed_event_fails_closed_with_zero_writes(overrides, issue) -> None:
    repo = repo_with()
    repo._personnel_technician_link_history = [_valid_row(**overrides)]
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("UNLINK", ""))
    assert exc.value.code == "PERSONNEL_TECHNICIAN_LINK_HISTORY_DATA_INVALID"
    assert issue in exc.value.details["issues"]
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fb_hist_duplicate_ids_and_bad_reconciliation_rows_fail_closed() -> None:
    cases = [
        ([_valid_row(), _valid_row(request_id="r-2")], "EVENT_ID_DUPLICATE"),
        ([_valid_row(), _valid_row(link_event_id="PTL-" + "b" * 32, event_kind="UNLINK",
                                   previous_technician_id=T1, new_technician_id="")], "REQUEST_ID_DUPLICATE"),
        ([_valid_row(), _valid_row(link_event_id="PTL-" + "b" * 32, request_id="r-2", event_kind="RECONCILIATION",
                                   previous_technician_id=T1, new_technician_id=T1, related_request_id="r-1")],
         "RECONCILIATION_SAME_STATE"),
        ([_valid_row(event_kind="RECONCILIATION", related_request_id="r-404")], "RELATED_REQUEST_DANGLING"),
        ([_valid_row(), _valid_row(link_event_id="PTL-" + "b" * 32, request_id="r-2", event_kind="RECONCILIATION",
                                   previous_technician_id="", new_technician_id=T2, related_request_id="r-1")],
         "RELATED_STATE_MISMATCH"),
    ]
    for rows, issue in cases:
        repo = repo_with()
        repo._personnel_technician_link_history = rows
        with pytest.raises(ApiError) as exc:
            await svc(repo).history("P-1")
        assert issue in exc.value.details["issues"], issue


@pytest.mark.asyncio
async def test_r2fb_hist_other_scope_rows_are_ignored_and_bad_flags_fail_closed() -> None:
    repo = repo_with()
    repo._personnel_technician_link_history = [_valid_row(is_test_data="TRUE", test_batch_id=BATCH,
                                                          event_kind="MERGE")]
    read = await svc(repo).history("P-1")  # REAL: the (even malformed) TEST row is out of scope
    assert (read.consistency, read.events) == (CONSISTENCY_NO_HISTORY, ())
    repo._personnel_technician_link_history = [_valid_row(is_test_data="yes")]
    assert await code_of(svc(repo).history("P-1")) == "PERSONNEL_TECHNICIAN_LINK_HISTORY_DATA_INVALID"


# ---------------------------------------------------------------------------
# R2FB-REPLAY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fb_replay_exact_reused_and_mismatch() -> None:
    repo = repo_with()
    rid = str(uuid.uuid4())
    first = await change(repo, "P-1", body("LINK", "", T1), request_id=rid)
    again = await change(repo, "P-1", body("LINK", "", T1), request_id=rid)
    assert (again.replayed, again.record_ids) == (True, (first.record_id,))
    assert repo.registry_write_log == ["W1", "W2"]
    assert await code_of(change(repo, "P-1", body("UNLINK", T1), request_id=rid)) == "REQUEST_ID_REUSED"

    broken = repo_with()
    broken.registry_write_faults["W2"] = "rejected"
    rid2 = str(uuid.uuid4())
    assert await code_of(change(broken, "P-1", body("LINK", "", T1), request_id=rid2)) == (
        "PERSONNEL_TECHNICIAN_LINK_PROJECTION_WRITE_FAILED")
    broken.registry_write_faults.clear()
    # the exact same request is NOT a replay success while the link is in MISMATCH, and W2 is never retried
    assert await code_of(change(broken, "P-1", body("LINK", "", T1), request_id=rid2)) == (
        "PERSONNEL_TECHNICIAN_LINK_MISMATCH")
    assert broken.registry_write_log == ["W1", "W2"] and cell(broken, "P-1") == ""


@pytest.mark.asyncio
async def test_r2fb_replay_unknown_not_applied_resend_proceeds_normally() -> None:
    repo = repo_with()
    repo.registry_write_faults["W1"] = "unknown_not_applied"
    rid = str(uuid.uuid4())
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("LINK", "", T1), request_id=rid)
    assert exc.value.details == {"history_write_outcome": "unknown", "request_id": rid}
    repo.registry_write_faults.clear()
    outcome = await change(repo, "P-1", body("LINK", "", T1), request_id=rid)
    assert outcome.changed is True and cell(repo, "P-1") == T1


# ---------------------------------------------------------------------------
# R2FB-W1W2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("fault", "outcome", "applied"), [
    ("rejected", "rejected", False), ("unknown_not_applied", "unknown", False), ("unknown_applied", "unknown", True)])
async def test_r2fb_w1_failure_never_runs_w2(fault, outcome, applied) -> None:
    repo = repo_with()
    repo.registry_write_faults["W1"] = fault
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("LINK", "", T1))
    assert (exc.value.code, exc.value.details["history_write_outcome"]) == (
        "PERSONNEL_TECHNICIAN_LINK_HISTORY_WRITE_FAILED", outcome)
    assert repo.registry_write_log == ["W1"]  # no W2, no retry
    assert cell(repo, "P-1") == "" and len(history(repo)) == (1 if applied else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["rejected", "unknown_not_applied"])
async def test_r2fb_w2_failure_keeps_history_and_enters_mismatch(fault) -> None:
    repo = repo_with()
    repo.registry_write_faults["W2"] = fault
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("LINK", "", T1))
    assert exc.value.code == "PERSONNEL_TECHNICIAN_LINK_PROJECTION_WRITE_FAILED"
    assert exc.value.details["event_recorded"] is True
    assert repo.registry_write_log == ["W1", "W2"]  # no retry, no compensation
    assert len(history(repo)) == 1 and cell(repo, "P-1") == ""
    repo.registry_write_faults.clear()
    read = await svc(repo).history("P-1")
    assert (read.current_id, read.latest_history_id, read.consistency) == (None, T1, CONSISTENCY_MISMATCH)
    # ordinary changes are refused until reconciliation
    assert await code_of(change(repo, "P-1", body("LINK", "", T3))) == "PERSONNEL_TECHNICIAN_LINK_MISMATCH"


# ---------------------------------------------------------------------------
# R2FB-RECON
# ---------------------------------------------------------------------------


async def _mismatched(repo, pid: str = "P-1", payload: dict | None = None) -> str:
    repo.registry_write_faults["W2"] = "rejected"
    rid = str(uuid.uuid4())
    with pytest.raises(ApiError):
        await change(repo, pid, payload or body("LINK", "", T1), request_id=rid)
    repo.registry_write_faults.clear()
    return rid


@pytest.mark.asyncio
async def test_r2fb_recon_restores_the_latest_history_target_history_first() -> None:
    repo = repo_with()
    rid = await _mismatched(repo)
    repo.registry_write_log.clear()
    outcome = await reconcile(repo, "P-1", rbody("", rid))
    assert (outcome.changed, outcome.previous_id, outcome.new_id, outcome.consistency_after) == (
        True, "", T1, CONSISTENCY_CONSISTENT)
    assert repo.registry_write_log == ["W1", "W2"] and cell(repo, "P-1") == T1
    last = history(repo)[-1]
    assert (last["event_kind"], last["related_request_id"], last["new_technician_id"]) == ("RECONCILIATION", rid, T1)
    assert (await svc(repo).history("P-1")).consistency == CONSISTENCY_CONSISTENT


@pytest.mark.asyncio
async def test_r2fb_recon_only_from_mismatch_and_with_a_valid_related_request() -> None:
    repo = repo_with()
    assert await code_of(reconcile(repo, "P-1", rbody("", "x"))) == (
        "PERSONNEL_TECHNICIAN_LINK_RECONCILIATION_NOT_REQUIRED")  # NO_HISTORY
    await change(repo, "P-1", body("LINK", "", T1))
    assert await code_of(reconcile(repo, "P-1", rbody(T1, "x"))) == (
        "PERSONNEL_TECHNICIAN_LINK_RECONCILIATION_NOT_REQUIRED")  # CONSISTENT
    first_rid = history(repo)[0]["request_id"]
    rid = await _mismatched(repo, payload=body("RELINK", T1, T3))
    for related in ("", "r-404", first_rid):  # blank, dangling, a prior event with ANOTHER target (T1 != T3)
        assert await code_of(reconcile(repo, "P-1", rbody(T1, related))) == (
            "PERSONNEL_TECHNICIAN_LINK_RELATED_REQUEST_INVALID"), related
    other = repo_with()
    other_rid = await _mismatched(other, "P-1")
    other._personnel_technician_link_history.extend(copy.deepcopy(history(repo)))
    assert await code_of(reconcile(repo, "P-1", rbody(T1, other_rid))) == (
        "PERSONNEL_TECHNICIAN_LINK_RELATED_REQUEST_INVALID")  # another personnel's / history's request
    assert await code_of(reconcile(repo, "P-1", rbody("", rid))) == "PERSONNEL_TECHNICIAN_LINK_STALE"
    assert (await reconcile(repo, "P-1", rbody(T1, rid))).new_id == T3


@pytest.mark.asyncio
async def test_r2fb_recon_related_request_of_another_personnel_or_scope_is_rejected() -> None:
    repo = repo_with(people=[person("P-1"), person("P-3"), person("P-1", test=True, batch=BATCH)])
    rid_p3 = await _mismatched(repo, "P-3", body("LINK", "", T3))
    await _mismatched(repo, "P-1")
    assert await code_of(reconcile(repo, "P-1", rbody("", rid_p3))) == (
        "PERSONNEL_TECHNICIAN_LINK_RELATED_REQUEST_INVALID")
    # a TEST-scope event of the same personnel id is invisible to the REAL reconciliation
    test_repo = repo_with(people=[person("P-1"), person("P-1", test=True, batch=BATCH)],
                          technicians=[tech(T1), tech(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    test_rid = await _mismatched(test_repo, "P-1")
    test_repo._personnel_technician_link_history[0].update(is_test_data="TRUE", test_batch_id=BATCH)
    test_repo._personnel_master[1]["technician_id"] = ""
    assert await code_of(reconcile(test_repo, "P-1", rbody("", test_rid))) == (
        "PERSONNEL_TECHNICIAN_LINK_RECONCILIATION_NOT_REQUIRED")  # REAL has no history at all


@pytest.mark.asyncio
async def test_r2fb_recon_of_an_unlink_writes_a_true_blank() -> None:
    repo = repo_with()
    rid = await _mismatched(repo, "P-2", body("UNLINK", T2))
    outcome = await reconcile(repo, "P-2", rbody(T2, rid))
    assert (outcome.previous_id, outcome.new_id) == (T2, "") and cell(repo, "P-2") == ""


# ---------------------------------------------------------------------------
# R2FB-SCOPE (TEST / REAL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fb_scope_real_and_test_rows_are_written_separately() -> None:
    people = [person("P-1"), person("P-1", test=True, batch=BATCH), person("P-1", test=True, batch="SYN-OTHER")]
    techs = [tech(T1), tech(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)]
    repo = repo_with(people=people, technicians=techs)
    await change(repo, "P-1", body("LINK", "", T1), context="REAL")
    assert [r["technician_id"] for r in repo._personnel_master] == [T1, "", ""]
    await change(repo, "P-1", body("LINK", "", T1), context="TEST")
    assert [r["technician_id"] for r in repo._personnel_master] == [T1, T1, ""]
    assert [(r["is_test_data"], r["test_batch_id"]) for r in history(repo)] == [("FALSE", ""), ("TRUE", BATCH)]


@pytest.mark.asyncio
async def test_r2fb_scope_test_never_targets_real_and_real_never_sees_fixtures() -> None:
    repo = repo_with(people=[person("P-1"), person("P-T", test=True, batch=BATCH)],
                     technicians=[tech(T1), tech("TEC-T9", scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    assert await code_of(change(repo, "P-T", body("LINK", "", T1), context="TEST")) == "TECHNICIAN_SCOPE_UNPROVEN"
    assert await code_of(change(repo, "P-1", body("LINK", "", "TEC-T9"), context="REAL")) == "TECHNICIAN_NOT_FOUND"
    assert await code_of(change(repo, "P-1", body("LINK", "", T1), context="TEST")) == "PERSONNEL_NOT_FOUND"
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fb_scope_uniqueness_is_per_scope() -> None:
    people = [person("P-T", technician_id=T1, test=True, batch=BATCH), person("P-1")]
    repo = repo_with(people=people, technicians=[tech(T1), tech(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    # a TEST holder never blocks a REAL link, and vice versa
    assert (await change(repo, "P-1", body("LINK", "", T1), context="REAL")).changed is True
    repo2 = repo_with(people=[person("P-R", technician_id=T1), person("P-T2", test=True, batch=BATCH)],
                      technicians=[tech(T1), tech(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    assert (await change(repo2, "P-T2", body("LINK", "", T1), context="TEST")).changed is True


@pytest.mark.asyncio
async def test_r2fb_scope_unclassifiable_flag_and_unconfigured_context_fail_closed() -> None:
    repo = repo_with(people=[person("P-1"), {**person("P-X"), "is_test_data": ""}])
    assert await code_of(change(repo, "P-1", body("LINK", "", T1))) == "PERSONNEL_MASTER_DATA_INVALID"
    assert await code_of(change(repo_with(), "P-1", body("LINK", "", T1), context=None)) == (
        "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert repo.registry_write_log == []


# ---------------------------------------------------------------------------
# R2FB-NOCASCADE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fb_nocascade_only_the_link_cell_and_history_change() -> None:
    repo = repo_with(people=[person("P-1", user_id="USR-SYN-1"), person("P-2", technician_id=T2)])
    snapshot = copy.deepcopy(repo._personnel_master)
    lifecycle_before = copy.deepcopy(repo._personnel_lifecycle_history)
    accounts_before = list(repo._user_account)
    technicians_before = list(repo._technician_master)
    await change(repo, "P-1", body("LINK", "", T1))
    await change(repo, "P-2", body("UNLINK", T2))
    for before, after in zip(snapshot, repo._personnel_master):
        diff = {k for k in before if before[k] != after[k]}
        assert diff <= {"technician_id"}, diff
    assert repo._personnel_lifecycle_history == lifecycle_before
    assert repo._user_account == accounts_before and repo._technician_master == technicians_before
    assert set(repo.calls) <= LINK_METHODS


@pytest.mark.asyncio
async def test_r2fb_nocascade_relationship_read_follows_the_new_link() -> None:
    repo = RelSpy(people=[tperson("P-T")], technicians=[ttech("TEC-T1")])
    await http("POST", f"{API}/personnel/P-T/technician-links", repo, json=body("LINK", "", "TEC-T1"))
    relationships = (await http("GET", f"{API}/personnel/P-T/relationships", repo, request_id=None)).json()
    assert relationships["technician"]["resolution"] == "RESOLVED"
    assert relationships["account"] == {"resolution": "UNSET"}


@pytest.mark.asyncio
async def test_r2fb_api_history_route_and_responses() -> None:
    repo = RelSpy(people=[tperson("P-T")], technicians=[ttech("TEC-T1")])
    rid = str(uuid.uuid4())
    changed = await http("POST", f"{API}/personnel/P-T/technician-links", repo, json=body("LINK", "", "TEC-T1"),
                         request_id=rid)
    assert set(changed.json()) == {"request_id", "changed", "link_event_id", "previous_technician_id",
                                   "new_technician_id", "relationship_consistency_after"}
    replay = await http("POST", f"{API}/personnel/P-T/technician-links", repo, json=body("LINK", "", "TEC-T1"),
                        request_id=rid)
    assert replay.json() == {"request_id": rid, "replayed": True, "record_ids": [changed.json()["link_event_id"]]}
    noop = await http("POST", f"{API}/personnel/P-T/technician-links", repo,
                      json=body("LINK", "TEC-T1", "TEC-T1"))
    assert noop.json()["changed"] is False and set(noop.json()) == {"request_id", "changed"}
    read = await http("GET", f"{API}/personnel/P-T/technician-links/history", repo, role="TECHNICIAN",
                      request_id=None)
    assert read.status_code == 200
    payload = read.json()
    assert (payload["current_technician_id"], payload["relationship_consistency"]) == ("TEC-T1", "CONSISTENT")
    (event,) = payload["events"]
    assert "request_fingerprint" not in event and event["recorded_by"] == "dev-user"
    denied = await http("GET", f"{API}/personnel/P-T/technician-links/history", RelSpy(), role="NO_SUCH_ROLE",
                        request_id=None)
    assert denied.status_code == 403


def test_r2fb_api_routes_have_no_delete_and_no_account_or_driver_writes() -> None:
    from app.main import create_app

    routes = {(m.upper(), path) for path, ops in create_app().openapi()["paths"].items() for m in ops}
    link_routes = {(m, p) for m, p in routes if "technician-links" in p}
    assert link_routes == {
        ("POST", f"{API}/personnel/{{personnel_id}}/technician-links"),
        ("POST", f"{API}/personnel/{{personnel_id}}/technician-links/reconcile"),
        ("GET", f"{API}/personnel/{{personnel_id}}/technician-links/history"),
    }
    assert not [r for r in routes if r[0] == "DELETE" and "personnel" in r[1]]
    assert not [r for r in routes if "account-link" in r[1] or "driver-link" in r[1]]
