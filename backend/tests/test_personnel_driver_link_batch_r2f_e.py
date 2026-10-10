"""R2 Batch R2f-e — Personnel ↔ Driver identity link writes, mock / service level.

The R2f-e implementation authorization. The shared link-engine contract
(LINK / UNLINK / RELINK / RECONCILIATION, stale-before-no-op, replay, W1/W2,
uniqueness, TEST / REAL) is exercised for the DRIVER spec with the same cases
the approved R2f-c suite uses for the account spec (mechanically derived:
account -> driver), plus the driver-specific sections at the end (no status
gate, no Driver-field leakage, Phase 6 Driver / vehicle_driver separation,
relationship read, capability). Every row is SYNTHETIC and labelled; no live
workbook value is used. TEST-scoped drivers are explicit synthetic fixtures
(scope TEST + batch), never derived from an id.

Batch-local ids: R2FE-AUTH, -LINK, -UNLINK, -RELINK, -STALE, -HIST, -REPLAY,
-W1W2, -RECON, -SCOPE, -NOCASCADE, -READ, -LEGACY, -CAP.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.personnel_driver_link import (
    PERSONNEL_DRIVER_LINK_HISTORY_COLUMNS,
    personnel_driver_link_service,
)
from app.domain.personnel_link import CONSISTENCY_CONSISTENT, CONSISTENCY_MISMATCH, CONSISTENCY_NO_HISTORY
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST, ScopedReferenceRow
from tests.test_relationship_read_batch_r2f_a import RelSpy
from tests.test_relationship_read_batch_r2f_a import person as base_person

API = "/api/v1"
BATCH = "SYN-R2FE-BATCH"
REASON = "แก้ไขข้อมูลหลัก (ทดสอบ)"
T1, T2, T3 = "DRV-SYN-1", "DRV-SYN-2", "DRV-SYN-3"
LINK_METHODS = {"read_personnel_link_master", "read_personnel_link_history_validated",
                "read_driver_master_reference", "append_personnel_link_history", "write_personnel_link_cell"}


def person(pid: str, *, driver_id: str = "", test: bool = False, batch: str = "", technician_id: str = "",
           user_id: str = "") -> dict[str, str]:
    """The R2f-a synthetic personnel row with the R2f-e driver_id link cell."""
    row = base_person(pid, technician_id=technician_id, user_id=user_id, test=test, batch=batch)
    row["driver_id"] = driver_id
    return row


def drv(did: str, *, scope: str = REFERENCE_SCOPE_REAL, batch: str = "") -> ScopedReferenceRow:
    return ScopedReferenceRow(values={"driver_id": did}, scope=scope, test_batch_id=batch)


class DrvSpy(RelSpy):
    """RelSpy with an explicit driver reference list (the bounded driver_id reader)."""

    def __init__(self, people=None, technicians=None, accounts=None, drivers=None, *, fail=None) -> None:
        super().__init__(people, technicians, accounts, fail=fail)
        self._driver_reference = list(drivers) if drivers is not None else []


def body(operation: str, expected: str = "", new: str | None = None, reason: str = REASON) -> dict:
    out = {"operation": operation, "expected_driver_id": expected, "reason_th": reason}
    if new is not None:
        out["new_driver_id"] = new
    return out


def rbody(expected: str, related: str, reason: str = REASON) -> dict:
    return {"expected_driver_id": expected, "related_request_id": related, "reason_th": reason}


def repo_with(people=None, drivers=None) -> DrvSpy:
    return DrvSpy(
        people=people if people is not None else [person("P-1"), person("P-2", driver_id=T2)],
        drivers=drivers if drivers is not None else [drv(T1), drv(T2), drv(T3)],
    )


def svc(repo, context: str = "REAL", batch: str = BATCH):
    return personnel_driver_link_service(repo, context, batch)


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
    return row["driver_id"]


def history(repo) -> list[dict[str, str]]:
    return repo._personnel_driver_link_history


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


def tperson(pid: str, driver_id: str = "") -> dict[str, str]:
    return person(pid, driver_id=driver_id, test=True, batch=MOCK_TEST_BATCH_ID)


def tdrv(did: str):
    return drv(did, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)


# ---------------------------------------------------------------------------
# R2FE-AUTH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE_MANAGER"])
async def test_r2fe_auth_admin_and_maintenance_manager_may_link(role) -> None:
    repo = DrvSpy(people=[tperson("P-T")], drivers=[tdrv("DRV-T1")])
    response = await http("POST", f"{API}/personnel/P-T/driver-links", repo, role=role,
                          json=body("LINK", "", "DRV-T1"))
    assert response.status_code == 200 and response.json()["changed"] is True
    assert cell(repo, "P-T", test=True) == "DRV-T1"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "SUPERVISOR", "MAINTENANCE", "NO_SUCH_ROLE"])
@pytest.mark.parametrize("suffix", ["driver-links", "driver-links/reconcile"])
async def test_r2fe_auth_other_roles_are_refused_with_zero_repository_calls(role, suffix) -> None:
    repo = DrvSpy(people=[tperson("P-T")], drivers=[tdrv("DRV-T1")])
    payload = body("LINK", "", "DRV-T1") if suffix == "driver-links" else rbody("", "x")
    response = await http("POST", f"{API}/personnel/P-T/{suffix}", repo, role=role, json=payload)
    assert response.status_code == 403
    assert repo.calls == [] and repo.registry_write_log == []


def test_r2fe_auth_capability_holders_are_exact() -> None:
    from app.domain import authz

    cap = authz.CAN_LINK_PERSONNEL_DRIVER
    assert cap == "can_link_personnel_driver" and cap in authz.ALL_CAPABILITIES
    holders = {role for role, caps in authz.ROLE_CAPABILITIES.items() if cap in caps}
    assert holders == {"ADMIN", "MAINTENANCE_MANAGER"}
    # separate from the lifecycle capability: neither implies the other
    assert authz.CAN_MANAGE_PERSONNEL != cap


@pytest.mark.asyncio
async def test_r2fe_auth_request_id_and_body_are_checked_before_any_read() -> None:
    repo = DrvSpy(people=[tperson("P-T")])
    no_id = await http("POST", f"{API}/personnel/P-T/driver-links", repo, json=body("LINK", "", "X"),
                       request_id=None)
    assert (no_id.status_code, no_id.json()["error"]["code"]) == (422, "REQUEST_ID_REQUIRED")
    for bad in ({**body("LINK", "", "X"), "recorded_by": "x"}, {**body("LINK", "", "X"), "operation": "MERGE"},
                {"operation": "LINK", "new_driver_id": "X", "reason_th": REASON}):
        response = await http("POST", f"{API}/personnel/P-T/driver-links", repo, json=bad)
        assert response.status_code == 422, bad
    arbitrary = await http("POST", f"{API}/personnel/P-T/driver-links/reconcile", repo,
                           json={**rbody("", "x"), "new_driver_id": "X"})
    assert arbitrary.status_code == 422  # a reconciliation can never name its own target
    assert repo.calls == []


@pytest.mark.asyncio
async def test_r2fe_auth_reason_and_target_shape_are_refused_before_reads() -> None:
    repo = repo_with()
    for payload, code in ((body("LINK", "", T1, reason="  "), "REASON_REQUIRED"),
                          (body("LINK", "", T1, reason="x" * 501), "REASON_REQUIRED"),
                          (body("LINK", "", None), "PERSONNEL_DRIVER_LINK_TARGET_REQUIRED"),
                          (body("RELINK", T2, "  "), "PERSONNEL_DRIVER_LINK_TARGET_REQUIRED"),
                          (body("UNLINK", T2, T1), "PERSONNEL_DRIVER_LINK_TARGET_NOT_ALLOWED")):
        assert await code_of(change(repo, "P-1", payload)) == code
    assert repo.calls == []


# ---------------------------------------------------------------------------
# R2FE-LINK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_link_blank_to_target_writes_history_then_cell() -> None:
    repo = repo_with()
    outcome = await change(repo, "P-1", body("LINK", "", T1), request_id="11111111-1111-4111-8111-111111111111")
    assert (outcome.changed, outcome.previous_id, outcome.new_id, outcome.consistency_after) == (
        True, "", T1, CONSISTENCY_CONSISTENT)
    assert repo.registry_write_log == ["W1", "W2"]
    assert cell(repo, "P-1") == T1
    (row,) = history(repo)
    assert set(row) == set(PERSONNEL_DRIVER_LINK_HISTORY_COLUMNS)
    assert (row["event_kind"], row["previous_driver_id"], row["new_driver_id"]) == ("LINK", "", T1)
    assert (row["recorded_by"], row["is_test_data"], row["test_batch_id"], row["related_request_id"]) == (
        "dev-user", "FALSE", "", "")
    assert row["link_event_id"] == outcome.record_id and row["link_event_id"].startswith("PDL-")
    assert row["request_id"] == "11111111-1111-4111-8111-111111111111" and len(row["request_fingerprint"]) == 64


@pytest.mark.asyncio
async def test_r2fe_link_same_target_is_a_no_op_after_guards() -> None:
    repo = repo_with()
    outcome = await change(repo, "P-2", body("LINK", T2, T2))
    assert (outcome.changed, repo.registry_write_log, history(repo)) == (False, [], [])


@pytest.mark.asyncio
async def test_r2fe_link_over_another_target_requires_relink() -> None:
    repo = repo_with()
    assert await code_of(change(repo, "P-2", body("LINK", T2, T3))) == "PERSONNEL_DRIVER_LINK_RELINK_REQUIRED"
    assert repo.registry_write_log == [] and cell(repo, "P-2") == T2


@pytest.mark.asyncio
async def test_r2fe_link_target_missing_duplicate_owned_and_exact_only() -> None:
    repo = repo_with(drivers=[drv(T1), drv(T2), drv("DRV-SYN-D"), drv("DRV-SYN-D")])
    assert await code_of(change(repo, "P-1", body("LINK", "", "DRV-SYN-404"))) == "DRIVER_NOT_FOUND"
    assert await code_of(change(repo, "P-1", body("LINK", "", "DRV-SYN-D"))) == "DRIVER_ID_AMBIGUOUS"
    for near in ("tec-syn-1", " DRV-SYN-1", "DRV-SYN-1 ", "DRV-SYN"):
        assert await code_of(change(repo, "P-1", body("LINK", "", near))) == "DRIVER_NOT_FOUND", near
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("LINK", "", T2))  # held by P-2
    assert (exc.value.code, exc.value.details) == ("DRIVER_ALREADY_LINKED", {"driver_id": T2})
    assert "P-2" not in str(exc.value.details)
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fe_link_needs_no_lifecycle_gate() -> None:
    """OD-5 governs NEW work assignments, not identity-link maintenance."""
    inactive = person("P-I", driver_id="")
    inactive["active_status"] = "INACTIVE"
    repo = repo_with(people=[inactive], drivers=[drv(T1)])
    assert (await change(repo, "P-I", body("LINK", "", T1))).changed is True
    assert repo._personnel_master[0]["active_status"] == "INACTIVE"


# ---------------------------------------------------------------------------
# R2FE-UNLINK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_unlink_sets_a_true_blank_and_records_history_first() -> None:
    repo = repo_with()
    outcome = await change(repo, "P-2", body("UNLINK", T2))
    assert (outcome.changed, outcome.previous_id, outcome.new_id) == (True, T2, "")
    assert repo.registry_write_log == ["W1", "W2"]
    assert cell(repo, "P-2") == ""
    (row,) = history(repo)
    assert (row["event_kind"], row["previous_driver_id"], row["new_driver_id"]) == ("UNLINK", T2, "")


@pytest.mark.asyncio
async def test_r2fe_unlink_when_blank_is_a_no_op_and_stale_is_refused() -> None:
    repo = repo_with()
    assert (await change(repo, "P-1", body("UNLINK", ""))).changed is False
    assert await code_of(change(repo, "P-2", body("UNLINK", T1))) == "PERSONNEL_DRIVER_LINK_STALE"
    assert repo.registry_write_log == []


# ---------------------------------------------------------------------------
# R2FE-RELINK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_relink_old_to_new_same_no_op_and_blank_requires_link() -> None:
    repo = repo_with()
    outcome = await change(repo, "P-2", body("RELINK", T2, T3))
    assert (outcome.changed, outcome.previous_id, outcome.new_id) == (True, T2, T3)
    assert history(repo)[0]["event_kind"] == "RELINK" and cell(repo, "P-2") == T3
    assert (await change(repo, "P-2", body("RELINK", T3, T3))).changed is False
    assert await code_of(change(repo, "P-1", body("RELINK", "", T1))) == "PERSONNEL_DRIVER_LINK_LINK_REQUIRED"


@pytest.mark.asyncio
async def test_r2fe_relink_target_rules() -> None:
    repo = repo_with(people=[person("P-1", driver_id=T1), person("P-2", driver_id=T2)],
                     drivers=[drv(T1), drv(T2), drv("DRV-SYN-D"), drv("DRV-SYN-D")])
    assert await code_of(change(repo, "P-1", body("RELINK", T1, T2))) == "DRIVER_ALREADY_LINKED"
    assert await code_of(change(repo, "P-1", body("RELINK", T1, "DRV-SYN-404"))) == "DRIVER_NOT_FOUND"
    assert await code_of(change(repo, "P-1", body("RELINK", T1, "DRV-SYN-D"))) == "DRIVER_ID_AMBIGUOUS"
    test_repo = DrvSpy(people=[tperson("P-T", "DRV-T1")], drivers=[tdrv("DRV-T1"), drv(T2)])
    assert await code_of(change(test_repo, "P-T", body("RELINK", "DRV-T1", T2), context="TEST",
                                batch=MOCK_TEST_BATCH_ID)) == "DRIVER_SCOPE_UNPROVEN"
    assert repo.registry_write_log == [] and test_repo.registry_write_log == []


# ---------------------------------------------------------------------------
# R2FE-STALE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_stale_is_checked_before_no_op_with_zero_writes() -> None:
    repo = repo_with()
    # intended == current (would be a no-op) but the client expected no link: stale, not success
    assert await code_of(change(repo, "P-2", body("LINK", "", T2))) == "PERSONNEL_DRIVER_LINK_STALE"
    assert await code_of(change(repo, "P-1", body("UNLINK", T1))) == "PERSONNEL_DRIVER_LINK_STALE"
    assert await code_of(change(repo, "P-2", body("RELINK", T1, T2))) == "PERSONNEL_DRIVER_LINK_STALE"
    assert repo.registry_write_log == [] and history(repo) == []


# ---------------------------------------------------------------------------
# R2FE-HIST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_hist_pre_existing_link_is_no_history_then_consistent() -> None:
    repo = repo_with()
    before = await svc(repo).history("P-2")
    assert (before.current_id, before.latest_history_id, before.consistency, before.events) == (
        T2, None, CONSISTENCY_NO_HISTORY, ())
    await change(repo, "P-2", body("RELINK", T2, T3))
    after = await svc(repo).history("P-2")
    assert (after.current_id, after.latest_history_id, after.consistency) == (T3, T3, CONSISTENCY_CONSISTENT)


@pytest.mark.asyncio
async def test_r2fe_hist_sequence_has_unique_event_and_request_ids() -> None:
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
    row = {"link_event_id": "PDL-" + "a" * 32, "personnel_id": "P-1", "event_kind": "LINK",
           "previous_driver_id": "", "new_driver_id": T1, "recorded_at": "2026-10-01T00:00:00+00:00",
           "recorded_by": "u", "request_id": "r-1", "request_fingerprint": "f" * 64, "reason_th": "x",
           "is_test_data": "FALSE", "test_batch_id": "", "related_request_id": ""}
    row.update(overrides)
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize(("overrides", "issue"), [
    ({"event_kind": "MERGE"}, "EVENT_KIND_INVALID"),
    ({"previous_driver_id": T2}, "EVENT_SHAPE_INVALID"),
    ({"event_kind": "UNLINK", "previous_driver_id": "", "new_driver_id": ""}, "EVENT_SHAPE_INVALID"),
    ({"event_kind": "RELINK", "previous_driver_id": T1}, "EVENT_SHAPE_INVALID"),
    ({"recorded_at": "2026-10-01T00:00:00"}, "RECORDED_AT_INVALID"),
    ({"recorded_by": " "}, "FIELD_REQUIRED:recorded_by"),
    ({"reason_th": ""}, "FIELD_REQUIRED:reason_th"),
    ({"request_fingerprint": "nope"}, "FINGERPRINT_INVALID"),
    ({"test_batch_id": "SYN-X"}, "SCOPE_INCONSISTENT"),
    ({"related_request_id": "r-0"}, "FIELD_MUST_BE_BLANK:related_request_id"),
])
async def test_r2fe_hist_malformed_event_fails_closed_with_zero_writes(overrides, issue) -> None:
    repo = repo_with()
    repo._personnel_driver_link_history = [_valid_row(**overrides)]
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("UNLINK", ""))
    assert exc.value.code == "PERSONNEL_DRIVER_LINK_HISTORY_DATA_INVALID"
    assert issue in exc.value.details["issues"]
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fe_hist_duplicate_ids_and_bad_reconciliation_rows_fail_closed() -> None:
    cases = [
        ([_valid_row(), _valid_row(request_id="r-2")], "EVENT_ID_DUPLICATE"),
        ([_valid_row(), _valid_row(link_event_id="PDL-" + "b" * 32, event_kind="UNLINK",
                                   previous_driver_id=T1, new_driver_id="")], "REQUEST_ID_DUPLICATE"),
        ([_valid_row(), _valid_row(link_event_id="PDL-" + "b" * 32, request_id="r-2", event_kind="RECONCILIATION",
                                   previous_driver_id=T1, new_driver_id=T1, related_request_id="r-1")],
         "RECONCILIATION_SAME_STATE"),
        ([_valid_row(event_kind="RECONCILIATION", related_request_id="r-404")], "RELATED_REQUEST_DANGLING"),
        ([_valid_row(), _valid_row(link_event_id="PDL-" + "b" * 32, request_id="r-2", event_kind="RECONCILIATION",
                                   previous_driver_id="", new_driver_id=T2, related_request_id="r-1")],
         "RELATED_STATE_MISMATCH"),
    ]
    for rows, issue in cases:
        repo = repo_with()
        repo._personnel_driver_link_history = rows
        with pytest.raises(ApiError) as exc:
            await svc(repo).history("P-1")
        assert issue in exc.value.details["issues"], issue


@pytest.mark.asyncio
async def test_r2fe_hist_other_scope_rows_are_ignored_and_bad_flags_fail_closed() -> None:
    repo = repo_with()
    repo._personnel_driver_link_history = [_valid_row(is_test_data="TRUE", test_batch_id=BATCH,
                                                          event_kind="MERGE")]
    read = await svc(repo).history("P-1")  # REAL: the (even malformed) TEST row is out of scope
    assert (read.consistency, read.events) == (CONSISTENCY_NO_HISTORY, ())
    repo._personnel_driver_link_history = [_valid_row(is_test_data="yes")]
    assert await code_of(svc(repo).history("P-1")) == "PERSONNEL_DRIVER_LINK_HISTORY_DATA_INVALID"


# ---------------------------------------------------------------------------
# R2FE-REPLAY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_replay_exact_reused_and_mismatch() -> None:
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
        "PERSONNEL_DRIVER_LINK_PROJECTION_WRITE_FAILED")
    broken.registry_write_faults.clear()
    # the exact same request is NOT a replay success while the link is in MISMATCH, and W2 is never retried
    assert await code_of(change(broken, "P-1", body("LINK", "", T1), request_id=rid2)) == (
        "PERSONNEL_DRIVER_LINK_MISMATCH")
    assert broken.registry_write_log == ["W1", "W2"] and cell(broken, "P-1") == ""


@pytest.mark.asyncio
async def test_r2fe_replay_unknown_not_applied_resend_proceeds_normally() -> None:
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
# R2FE-W1W2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("fault", "outcome", "applied"), [
    ("rejected", "rejected", False), ("unknown_not_applied", "unknown", False), ("unknown_applied", "unknown", True)])
async def test_r2fe_w1_failure_never_runs_w2(fault, outcome, applied) -> None:
    repo = repo_with()
    repo.registry_write_faults["W1"] = fault
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("LINK", "", T1))
    assert (exc.value.code, exc.value.details["history_write_outcome"]) == (
        "PERSONNEL_DRIVER_LINK_HISTORY_WRITE_FAILED", outcome)
    assert repo.registry_write_log == ["W1"]  # no W2, no retry
    assert cell(repo, "P-1") == "" and len(history(repo)) == (1 if applied else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["rejected", "unknown_not_applied"])
async def test_r2fe_w2_failure_keeps_history_and_enters_mismatch(fault) -> None:
    repo = repo_with()
    repo.registry_write_faults["W2"] = fault
    with pytest.raises(ApiError) as exc:
        await change(repo, "P-1", body("LINK", "", T1))
    assert exc.value.code == "PERSONNEL_DRIVER_LINK_PROJECTION_WRITE_FAILED"
    assert exc.value.details["event_recorded"] is True
    assert repo.registry_write_log == ["W1", "W2"]  # no retry, no compensation
    assert len(history(repo)) == 1 and cell(repo, "P-1") == ""
    repo.registry_write_faults.clear()
    read = await svc(repo).history("P-1")
    assert (read.current_id, read.latest_history_id, read.consistency) == (None, T1, CONSISTENCY_MISMATCH)
    # ordinary changes are refused until reconciliation
    assert await code_of(change(repo, "P-1", body("LINK", "", T3))) == "PERSONNEL_DRIVER_LINK_MISMATCH"


# ---------------------------------------------------------------------------
# R2FE-RECON
# ---------------------------------------------------------------------------


async def _mismatched(repo, pid: str = "P-1", payload: dict | None = None) -> str:
    repo.registry_write_faults["W2"] = "rejected"
    rid = str(uuid.uuid4())
    with pytest.raises(ApiError):
        await change(repo, pid, payload or body("LINK", "", T1), request_id=rid)
    repo.registry_write_faults.clear()
    return rid


@pytest.mark.asyncio
async def test_r2fe_recon_restores_the_latest_history_target_history_first() -> None:
    repo = repo_with()
    rid = await _mismatched(repo)
    repo.registry_write_log.clear()
    outcome = await reconcile(repo, "P-1", rbody("", rid))
    assert (outcome.changed, outcome.previous_id, outcome.new_id, outcome.consistency_after) == (
        True, "", T1, CONSISTENCY_CONSISTENT)
    assert repo.registry_write_log == ["W1", "W2"] and cell(repo, "P-1") == T1
    last = history(repo)[-1]
    assert (last["event_kind"], last["related_request_id"], last["new_driver_id"]) == ("RECONCILIATION", rid, T1)
    assert (await svc(repo).history("P-1")).consistency == CONSISTENCY_CONSISTENT


@pytest.mark.asyncio
async def test_r2fe_recon_only_from_mismatch_and_with_a_valid_related_request() -> None:
    repo = repo_with()
    assert await code_of(reconcile(repo, "P-1", rbody("", "x"))) == (
        "PERSONNEL_DRIVER_LINK_RECONCILIATION_NOT_REQUIRED")  # NO_HISTORY
    await change(repo, "P-1", body("LINK", "", T1))
    assert await code_of(reconcile(repo, "P-1", rbody(T1, "x"))) == (
        "PERSONNEL_DRIVER_LINK_RECONCILIATION_NOT_REQUIRED")  # CONSISTENT
    first_rid = history(repo)[0]["request_id"]
    rid = await _mismatched(repo, payload=body("RELINK", T1, T3))
    for related in ("", "r-404", first_rid):  # blank, dangling, a prior event with ANOTHER target (T1 != T3)
        assert await code_of(reconcile(repo, "P-1", rbody(T1, related))) == (
            "PERSONNEL_DRIVER_LINK_RELATED_REQUEST_INVALID"), related
    other = repo_with()
    other_rid = await _mismatched(other, "P-1")
    other._personnel_driver_link_history.extend(copy.deepcopy(history(repo)))
    assert await code_of(reconcile(repo, "P-1", rbody(T1, other_rid))) == (
        "PERSONNEL_DRIVER_LINK_RELATED_REQUEST_INVALID")  # another personnel's / history's request
    assert await code_of(reconcile(repo, "P-1", rbody("", rid))) == "PERSONNEL_DRIVER_LINK_STALE"
    assert (await reconcile(repo, "P-1", rbody(T1, rid))).new_id == T3


@pytest.mark.asyncio
async def test_r2fe_recon_related_request_of_another_personnel_or_scope_is_rejected() -> None:
    repo = repo_with(people=[person("P-1"), person("P-3"), person("P-1", test=True, batch=BATCH)])
    rid_p3 = await _mismatched(repo, "P-3", body("LINK", "", T3))
    await _mismatched(repo, "P-1")
    assert await code_of(reconcile(repo, "P-1", rbody("", rid_p3))) == (
        "PERSONNEL_DRIVER_LINK_RELATED_REQUEST_INVALID")
    # a TEST-scope event of the same personnel id is invisible to the REAL reconciliation
    test_repo = repo_with(people=[person("P-1"), person("P-1", test=True, batch=BATCH)],
                          drivers=[drv(T1), drv(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    test_rid = await _mismatched(test_repo, "P-1")
    test_repo._personnel_driver_link_history[0].update(is_test_data="TRUE", test_batch_id=BATCH)
    test_repo._personnel_master[1]["driver_id"] = ""
    assert await code_of(reconcile(test_repo, "P-1", rbody("", test_rid))) == (
        "PERSONNEL_DRIVER_LINK_RECONCILIATION_NOT_REQUIRED")  # REAL has no history at all


@pytest.mark.asyncio
async def test_r2fe_recon_of_an_unlink_writes_a_true_blank() -> None:
    repo = repo_with()
    rid = await _mismatched(repo, "P-2", body("UNLINK", T2))
    outcome = await reconcile(repo, "P-2", rbody(T2, rid))
    assert (outcome.previous_id, outcome.new_id) == (T2, "") and cell(repo, "P-2") == ""


# ---------------------------------------------------------------------------
# R2FE-SCOPE (TEST / REAL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_scope_real_and_test_rows_are_written_separately() -> None:
    people = [person("P-1"), person("P-1", test=True, batch=BATCH), person("P-1", test=True, batch="SYN-OTHER")]
    accs = [drv(T1), drv(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)]
    repo = repo_with(people=people, drivers=accs)
    await change(repo, "P-1", body("LINK", "", T1), context="REAL")
    assert [r["driver_id"] for r in repo._personnel_master] == [T1, "", ""]
    await change(repo, "P-1", body("LINK", "", T1), context="TEST")
    assert [r["driver_id"] for r in repo._personnel_master] == [T1, T1, ""]
    assert [(r["is_test_data"], r["test_batch_id"]) for r in history(repo)] == [("FALSE", ""), ("TRUE", BATCH)]


@pytest.mark.asyncio
async def test_r2fe_scope_test_never_targets_real_and_real_never_sees_fixtures() -> None:
    repo = repo_with(people=[person("P-1"), person("P-T", test=True, batch=BATCH)],
                     drivers=[drv(T1), drv("DRV-T9", scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    assert await code_of(change(repo, "P-T", body("LINK", "", T1), context="TEST")) == "DRIVER_SCOPE_UNPROVEN"
    assert await code_of(change(repo, "P-1", body("LINK", "", "DRV-T9"), context="REAL")) == "DRIVER_NOT_FOUND"
    assert await code_of(change(repo, "P-1", body("LINK", "", T1), context="TEST")) == "PERSONNEL_NOT_FOUND"
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fe_scope_uniqueness_is_per_scope() -> None:
    people = [person("P-T", driver_id=T1, test=True, batch=BATCH), person("P-1")]
    repo = repo_with(people=people, drivers=[drv(T1), drv(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    # a TEST holder never blocks a REAL link, and vice versa
    assert (await change(repo, "P-1", body("LINK", "", T1), context="REAL")).changed is True
    repo2 = repo_with(people=[person("P-R", driver_id=T1), person("P-T2", test=True, batch=BATCH)],
                      drivers=[drv(T1), drv(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    assert (await change(repo2, "P-T2", body("LINK", "", T1), context="TEST")).changed is True


@pytest.mark.asyncio
async def test_r2fe_scope_unclassifiable_flag_and_unconfigured_context_fail_closed() -> None:
    repo = repo_with(people=[person("P-1"), {**person("P-X"), "is_test_data": ""}])
    assert await code_of(change(repo, "P-1", body("LINK", "", T1))) == "PERSONNEL_MASTER_DATA_INVALID"
    assert await code_of(change(repo_with(), "P-1", body("LINK", "", T1), context=None)) == (
        "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert repo.registry_write_log == []


# ---------------------------------------------------------------------------
# R2FE-REPLAY (driver-specific addition): unknown-applied resend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_replay_unknown_applied_resend_is_mismatch_never_a_hidden_w2() -> None:
    """W1 applied with an unknown outcome and no W2: the exact resend finds the
    event, but the link is in MISMATCH, so it is never a replay success and W2 is
    never retried; an explicit reconciliation finishes it."""
    repo = repo_with()
    repo.registry_write_faults["W1"] = "unknown_applied"
    rid = str(uuid.uuid4())
    assert await code_of(change(repo, "P-1", body("LINK", "", T1), request_id=rid)) == (
        "PERSONNEL_DRIVER_LINK_HISTORY_WRITE_FAILED")
    repo.registry_write_faults.clear()
    assert await code_of(change(repo, "P-1", body("LINK", "", T1), request_id=rid)) == "PERSONNEL_DRIVER_LINK_MISMATCH"
    assert repo.registry_write_log == ["W1"] and len(history(repo)) == 1 and cell(repo, "P-1") == ""
    fixed = await reconcile(repo, "P-1", rbody("", rid))
    assert fixed.new_id == T1 and cell(repo, "P-1") == T1 and repo.registry_write_log == ["W1", "W1", "W2"]
    # once consistent, the original exact request is a replay success with no further write
    again = await change(repo, "P-1", body("LINK", "", T1), request_id=rid)
    assert again.replayed and again.record_ids == (history(repo)[0]["link_event_id"],)
    assert repo.registry_write_log == ["W1", "W1", "W2"]


# ---------------------------------------------------------------------------
# R2FE-NOSTATUS — identity linking ignores every lifecycle / Driver status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["INACTIVE", "", "พักงาน", "ACTIVE"])
async def test_r2fe_nostatus_driver_active_status_is_never_read_or_gated(status) -> None:
    from app.domain.driver import Driver

    repo = DrvSpy(people=[person("P-1"), person("P-2")])
    repo._driver_reference = None  # the default: the Phase 6 mock drivers as REAL references
    repo._drivers = {"DRV-SYN-9": Driver(driver_id="DRV-SYN-9", driver_name_th="ผู้ขับ (สังเคราะห์)",
                                         active_status=status or None)}
    before = copy.deepcopy(repo._drivers)
    assert (await change(repo, "P-1", body("LINK", "", "DRV-SYN-9"))).changed is True
    assert (await change(repo, "P-1", body("UNLINK", "DRV-SYN-9"))).changed is True
    assert repo._drivers == before  # never activated, deactivated or edited


@pytest.mark.asyncio
async def test_r2fe_nostatus_inactive_personnel_may_link_unlink_relink_and_reconcile() -> None:
    inactive = {**person("P-1"), "active_status": "INACTIVE"}
    repo = repo_with(people=[inactive, {**person("P-2", driver_id=T2), "active_status": ""}])
    assert (await change(repo, "P-1", body("LINK", "", T1))).changed
    assert (await change(repo, "P-1", body("RELINK", T1, T3))).changed
    assert (await change(repo, "P-2", body("UNLINK", T2))).changed
    rid = await _mismatched(repo, "P-1", body("UNLINK", T3))
    assert (await reconcile(repo, "P-1", rbody(T3, rid))).new_id == ""
    assert [r["active_status"] for r in repo._personnel_master] == ["INACTIVE", ""]


# ---------------------------------------------------------------------------
# R2FE-NOCASCADE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fe_nocascade_only_the_driver_cell_and_its_history_change() -> None:
    repo = repo_with(people=[person("P-1", technician_id="TEC-SYN-9", user_id="USR-SYN-9"),
                             person("P-2", driver_id=T2)])
    snapshot = copy.deepcopy(repo._personnel_master)
    frozen = {name: copy.deepcopy(getattr(repo, name)) for name in (
        "_personnel_lifecycle_history", "_personnel_technician_link_history", "_personnel_account_link_history",
        "_equipment_caretaker_history", "_drivers", "_vehicle_driver_assignments", "_technician_master",
        "_user_account", "_department_master", "_branch_master")}
    await change(repo, "P-1", body("LINK", "", T1))
    await change(repo, "P-2", body("UNLINK", T2))
    for before, after in zip(snapshot, repo._personnel_master):
        diff = {k for k in before if before[k] != after[k]}
        assert diff <= {"driver_id"}, diff  # technician_id, user_id, active_status, names, flags untouched
    for name, before in frozen.items():
        assert getattr(repo, name) == before, name  # driver_master / vehicle_driver / other links untouched
    assert set(repo.calls) <= LINK_METHODS


# ---------------------------------------------------------------------------
# R2FE-READ — the relationship read resolves the Driver link (R2f-a states)
# ---------------------------------------------------------------------------


async def relationships(repo, pid: str, *, role: str = "TECHNICIAN") -> dict:
    response = await http("GET", f"{API}/personnel/{pid}/relationships", repo, role=role, request_id=None)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_r2fe_read_driver_resolution_states() -> None:
    repo = DrvSpy(
        people=[tperson("P-R", "DRV-T1"), tperson("P-U"), tperson("P-M", "DRV-T404"), tperson("P-A1", "DRV-T2"),
                tperson("P-A2", "DRV-T2"), tperson("P-D", "DRV-TD"), tperson("P-S", "DRV-REAL-ONLY")],
        drivers=[tdrv("DRV-T1"), tdrv("DRV-T2"), tdrv("DRV-TD"), tdrv("DRV-TD"), drv("DRV-REAL-ONLY")],
    )
    expected = {"P-R": ("RESOLVED", "DRV-T1"), "P-U": ("UNSET", None), "P-M": ("MISSING", "DRV-T404"),
                "P-A1": ("AMBIGUOUS", "DRV-T2"), "P-D": ("AMBIGUOUS", "DRV-TD"),
                "P-S": ("SCOPE_UNPROVEN", "DRV-REAL-ONLY")}
    for pid, (resolution, driver_id) in expected.items():
        body_ = await relationships(repo, pid)  # a can_view-only caller sees the stable driver_id
        assert body_["driver"] == {"resolution": resolution, "driver_id": driver_id}, pid
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fe_read_no_driver_field_beyond_the_id_is_read_or_returned() -> None:
    from app.domain.driver import Driver

    repo = DrvSpy(people=[person("P-1", driver_id="DRV-SYN-9")])
    repo._driver_reference = None
    repo._drivers = {"DRV-SYN-9": Driver(driver_id="DRV-SYN-9", driver_name_th="ชื่อลับ-LEAK", phone="000-LEAK",
                                         license_no="LIC-LEAK", active_status="ACTIVE", note_th="NOTE-LEAK")}
    reference = await repo.read_driver_master_reference()
    assert reference.columns == frozenset({"driver_id"})
    assert all(set(r.values) == {"driver_id"} for r in reference.rows)
    read = await svc(repo).history("P-1")
    assert read.current_id == "DRV-SYN-9"
    from app.domain.personnel_relationship import PersonnelRelationshipService

    result = await PersonnelRelationshipService(repo, "REAL", BATCH).personnel_relationships("P-1")
    assert (result.driver.resolution, result.driver.linked_id) == ("RESOLVED", "DRV-SYN-9")
    assert set(result.driver.target.values) == {"driver_id"}
    for leaked in ("LEAK", "LIC-", "phone", "license"):
        assert leaked not in repr(result.driver)


@pytest.mark.asyncio
async def test_r2fe_read_relationship_follows_the_new_link_and_the_history_route() -> None:
    repo = DrvSpy(people=[tperson("P-T")], drivers=[tdrv("DRV-T1")])
    rid = str(uuid.uuid4())
    changed = await http("POST", f"{API}/personnel/P-T/driver-links", repo, json=body("LINK", "", "DRV-T1"),
                         request_id=rid)
    assert set(changed.json()) == {"request_id", "changed", "link_event_id", "previous_driver_id",
                                   "new_driver_id", "relationship_consistency_after"}
    assert (await relationships(repo, "P-T"))["driver"] == {"resolution": "RESOLVED", "driver_id": "DRV-T1"}
    replay = await http("POST", f"{API}/personnel/P-T/driver-links", repo, json=body("LINK", "", "DRV-T1"),
                        request_id=rid)
    assert replay.json() == {"request_id": rid, "replayed": True, "record_ids": [changed.json()["link_event_id"]]}
    read = await http("GET", f"{API}/personnel/P-T/driver-links/history", repo, role="TECHNICIAN", request_id=None)
    payload = read.json()
    assert set(payload) == {"personnel_id", "current_driver_id", "latest_history_driver_id",
                            "relationship_consistency", "events"}
    assert (payload["current_driver_id"], payload["latest_history_driver_id"], payload["relationship_consistency"]) == (
        "DRV-T1", "DRV-T1", "CONSISTENT")
    (event,) = payload["events"]
    assert set(event) == {"link_event_id", "event_kind", "previous_driver_id", "new_driver_id", "recorded_at",
                          "recorded_by", "reason_th", "request_id"}
    assert event["recorded_by"] == "dev-user"  # the actor is the authenticated user, never a driver id
    denied = await http("GET", f"{API}/personnel/P-T/driver-links/history", repo, role="NO_SUCH_ROLE",
                        request_id=None)
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# R2FE-LEGACY — Phase 6 Driver behaviour is untouched
# ---------------------------------------------------------------------------


def test_r2fe_legacy_phase6_driver_and_vehicle_driver_schemas_and_routes_are_unchanged() -> None:
    from app.main import create_app
    from app.repositories.google_sheets import schemas

    assert schemas.DRIVER_MASTER_SHEET.required_headers == (
        "driver_id", "driver_name_th", "phone", "license_no", "license_expiry_date", "active_status", "note_th")
    assert schemas.VEHICLE_DRIVER_SHEET.required_headers == (
        "assignment_id", "vehicle_id", "driver_id", "start_at", "end_at", "is_primary", "assignment_status",
        "changed_by_user_id", "note_th")
    paths = create_app().openapi()["paths"]
    driver_routes = {(m.upper(), p) for p, ops in paths.items() for m in ops if "driver" in p}
    phase6 = {r for r in driver_routes if "driver-links" not in r[1]}
    assert phase6 and not [r for r in phase6 if "personnel" in r[1]]  # no Phase 6 route gained R2f-e semantics
    assert {r for r in driver_routes if "driver-links" in r[1]} == {
        ("POST", f"{API}/personnel/{{personnel_id}}/driver-links"),
        ("POST", f"{API}/personnel/{{personnel_id}}/driver-links/reconcile"),
        ("GET", f"{API}/personnel/{{personnel_id}}/driver-links/history")}
    assert not [p for p in paths if "crane" in p and "driver" in p]


def test_r2fe_legacy_link_sources_never_use_vehicle_driver_or_driver_writes() -> None:
    import inspect

    from app.api.v1 import personnel_driver_link_routes
    from app.domain import personnel_driver_link, personnel_link, personnel_relationship
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    for module in (personnel_driver_link, personnel_link, personnel_relationship, personnel_driver_link_routes):
        code = "\n".join(line for line in inspect.getsource(module).splitlines()
                         if not line.lstrip().startswith("#"))
        for forbidden in ("vehicle_driver_assignment", "create_driver(", "update_driver(", "list_drivers(",
                          "get_driver(", "VehicleDriverAssignment", "crane_driver_responsibility"):
            assert forbidden not in code, (module.__name__, forbidden)
    write = inspect.getsource(GoogleSheetsRepository.write_personnel_link_cell)
    assert "DRIVER_MASTER" not in write and "driver_master" not in write


@pytest.mark.asyncio
async def test_r2fe_legacy_phase6_driver_routes_still_work_and_ignore_the_link() -> None:
    repo = repo_with(people=[person("P-1")])
    repo._driver_reference = None
    created = await http("POST", f"{API}/drivers", repo, role="ADMIN", request_id=None,
                         json={"driver_name_th": "ผู้ขับใหม่ (สังเคราะห์)"})
    assert created.status_code in (200, 201), created.text
    new_id = created.json()["driver_id"]
    assert (await change(repo, "P-1", body("LINK", "", new_id))).changed  # REAL reference via the Phase 6 driver
    listed = await http("GET", f"{API}/drivers", repo, role="ADMIN", request_id=None)
    assert listed.status_code == 200 and "personnel_id" not in listed.text


# ---------------------------------------------------------------------------
# R2FE-CAP
# ---------------------------------------------------------------------------


def test_r2fe_cap_driver_link_capability_is_separate_and_no_new_role_exists() -> None:
    from app.domain import authz

    cap = authz.CAN_LINK_PERSONNEL_DRIVER
    assert cap == "can_link_personnel_driver"
    for other in (authz.CAN_LINK_PERSONNEL_TECHNICIAN, authz.CAN_LINK_PERSONNEL_ACCOUNT,
                  authz.CAN_MANAGE_PERSONNEL, authz.CAN_ASSIGN_EQUIPMENT_CARETAKER):
        assert other != cap
    for role, caps in authz.ROLE_CAPABILITIES.items():
        assert (cap in caps) == (role in {"ADMIN", "MAINTENANCE_MANAGER"}), role
    assert "DRIVER_DEPARTMENT_MANAGER" not in authz.ROLE_CAPABILITIES
    assert not [c for c in authz.ALL_CAPABILITIES if "crane" in c]


@pytest.mark.asyncio
async def test_r2fe_cap_other_link_routes_do_not_accept_driver_bodies() -> None:
    repo = DrvSpy(people=[tperson("P-T")], drivers=[tdrv("DRV-T1")])
    for suffix in ("technician-links", "account-links"):
        response = await http("POST", f"{API}/personnel/P-T/{suffix}", repo, json=body("LINK", "", "DRV-T1"))
        assert response.status_code == 422, suffix
    assert repo.registry_write_log == [] and history(repo) == []


@pytest.mark.asyncio
async def test_r2fe_cap_driver_role_cannot_link_itself() -> None:
    repo = DrvSpy(people=[tperson("P-T")], drivers=[tdrv("DRV-T1")])
    response = await http("POST", f"{API}/personnel/P-T/driver-links", repo, role="DRIVER",
                          json=body("LINK", "", "DRV-T1"))
    assert response.status_code == 403 and repo.calls == []


@pytest.mark.asyncio
async def test_r2fe_scope_test_driver_id_text_never_proves_test_scope() -> None:
    repo = repo_with(people=[person("P-T", test=True, batch=BATCH), person("P-1")], drivers=[drv("TEST-DRV-1")])
    assert await code_of(change(repo, "P-T", body("LINK", "", "TEST-DRV-1"), context="TEST")) == (
        "DRIVER_SCOPE_UNPROVEN")
    assert (await change(repo, "P-1", body("LINK", "", "TEST-DRV-1"), context="REAL")).changed is True
