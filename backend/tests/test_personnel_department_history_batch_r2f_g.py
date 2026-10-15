"""R2 Batch R2f-g — Personnel department movement history, mock / service level.

Every department / personnel row here is SYNTHETIC (marked "(สังเคราะห์)" /
SYN-) and lives only in this test's fake repository: no real department code,
name, mapping or hierarchy is created, and nothing here is owner master data.
TEST-scoped departments are explicit synthetic fixtures (is_test_data TRUE +
batch), never derived from an id.

The write capability `can_move_personnel_department` is GOVERNANCE PENDING and
held by NO role; API write tests therefore inject it explicitly into the
request context (never through a role), and the R2FG-AUTH tests prove that no
DEV role — ADMIN included — holds it.

Batch-local ids: R2FG-AUTH, -TL (timeline / periods), -ASOF, -REF (department
reference proof), -SCOPE, -STALE, -REPLAY, -WRITE, -AMBIG, -INVALID, -LEGACY.
"""
from __future__ import annotations

import copy
import inspect
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain import authz
from app.domain.personnel_department_history import PersonnelDepartmentHistoryService
from app.domain.personnel_department_timeline import (
    PERSONNEL_DEPARTMENT_HISTORY_COLUMNS,
    STATUS_AMBIGUOUS,
    STATUS_INVALID,
    STATUS_VALID,
    department_at,
    derive_department_timeline,
    validate_department_row,
)
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.base import Repository
from tests.test_relationship_read_batch_r2f_a import RelSpy, person

API = "/api/v1"
BATCH = "SYN-R2FG-BATCH"
REASON = "บันทึกการย้ายแผนก (ทดสอบ)"
SYN = " (สังเคราะห์)"
A, B, C = "DEPT-SYN-A", "DEPT-SYN-B", "DEPT-SYN-C"
D1, D2, D3, D4 = "2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"
METHODS = {"read_personnel_relationship_master", "read_personnel_department_history_validated",
           "read_department_reference", "append_personnel_department_history"}


def dept(did: str, *, test: bool = False, batch: str = "", active: str = "TRUE") -> dict[str, str]:
    """A SYNTHETIC department_master row (mock only; never owner data)."""
    return {"department_id": did, "department_name_th": "แผนก" + SYN, "is_active": active,
            "is_test_data": "TRUE" if test else "FALSE", "test_batch_id": batch}


class DeptSpy(RelSpy):
    def __init__(self, people=None, departments=None, *, fail=None) -> None:
        super().__init__(people, fail=fail)
        if departments is not None:
            self._department_master = list(departments)


def legacy_person(pid: str, **kw) -> dict[str, str]:
    row = person(pid, **kw)
    row["department"] = "SYN-LEGACY-DEPARTMENT-TEXT"  # the legacy text: never read or written by R2f-g
    return row


def repo_with(people=None, departments=None) -> DeptSpy:
    return DeptSpy(people=people if people is not None else [legacy_person("P-1"), legacy_person("P-2")],
                   departments=departments if departments is not None else [dept(A), dept(B), dept(C)])


def test_repo() -> DeptSpy:
    return DeptSpy(people=[legacy_person("P-T", test=True, batch=MOCK_TEST_BATCH_ID)],
                   departments=[dept(A, test=True, batch=MOCK_TEST_BATCH_ID),
                                dept(B, test=True, batch=MOCK_TEST_BATCH_ID)])


def svc(repo, context: str | None = "REAL", batch: str = BATCH) -> PersonnelDepartmentHistoryService:
    return PersonnelDepartmentHistoryService(repo, context, batch)


def eff(date: str | None = None) -> dict:
    return {"mode": "DATE", "date": date} if date else {"mode": "NOW"}


def move(department: str, expected: str | None, date: str | None = None, **extra) -> dict:
    return {"operation": "TRANSFER", "department_id": department, "effective": eff(date),
            "expected_current_department_id": expected, **extra}


def insertion(department: str, expected: str | None, date: str, reason: str = REASON) -> dict:
    return {"operation": "INSERTION", "department_id": department, "effective": eff(date),
            "expected_current_department_id": expected, "reason_th": reason}


def correction(event_id: str, revision: str, expected: str | None, date: str, department: str,
               reason: str = REASON) -> dict:
    return {"operation": "CORRECTION", "event_id": event_id, "expected_revision_no": revision,
            "department_id": department, "effective": eff(date), "expected_current_department_id": expected,
            "reason_th": reason}


def cancellation(event_id: str, revision: str, expected: str | None, reason: str = REASON) -> dict:
    return {"operation": "CANCELLATION", "event_id": event_id, "expected_revision_no": revision,
            "expected_current_department_id": expected, "reason_th": reason}


async def record(repo, payload: dict, *, pid: str = "P-1", context: str = "REAL", batch: str = BATCH,
                 request_id: str | None = None, user: str = "dev-user"):
    return await svc(repo, context, batch).record_event(pid, payload, request_id=request_id or str(uuid.uuid4()),
                                                        user_id=user)


async def read(repo, pid: str = "P-1", *, context: str = "REAL", as_of: dict | None = None):
    return await svc(repo, context).department_history(pid, as_of)


async def code_of(coro) -> str:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value.code


def history(repo) -> list[dict[str, str]]:
    return repo._personnel_department_history


async def http(method: str, path: str, repo, *, role: str = "ADMIN", json=None, request_id: str | None = "auto",
               grant_pending: bool = False, settings=None):
    """`grant_pending` injects the governance-pending capability DIRECTLY into the
    request context (never through a role) to exercise the write behaviour.
    `settings` (optional) overrides the server settings; None keeps the app's own."""
    from app.config import get_settings
    from app.context import RequestContext
    from app.dependencies import get_current_context, get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    if settings is not None:
        app.dependency_overrides[get_settings_dependency] = lambda: settings
    if grant_pending:
        app.dependency_overrides[get_current_context] = lambda: RequestContext(
            request_id=str(uuid.uuid4()), user_id="synthetic-mover", roles=(), is_dev_auth=True,
            capabilities=frozenset({authz.CAN_VIEW, authz.CAN_MOVE_PERSONNEL_DEPARTMENT}))
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


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


EVENTS = f"{API}/personnel/P-T/department-events"


async def seed_ab(repo) -> list[str]:
    """P-1: A from D1, B from D3 (movements); returns both event ids."""
    first = await record(repo, move(A, None, D1))
    second = await record(repo, move(B, A, D3))
    return [first.event_id, second.event_id]


# ---------------------------------------------------------------------------
# R2FG-AUTH — the governance-pending, zero-holder write gate
# ---------------------------------------------------------------------------


def test_r2fg_auth_pending_capability_has_zero_holders_and_is_not_inherited() -> None:
    cap = authz.CAN_MOVE_PERSONNEL_DEPARTMENT
    assert cap == "can_move_personnel_department"
    assert cap in authz.PENDING_CAPABILITIES and cap not in authz.ALL_CAPABILITIES
    assert [role for role, caps in authz.ROLE_CAPABILITIES.items() if cap in caps] == []
    assert cap not in authz.ROLE_CAPABILITIES["ADMIN"]  # ADMIN = ALL_CAPABILITIES does not inherit it
    for roles in [(r,) for r in authz.ROLE_CAPABILITIES] + [tuple(authz.ROLE_CAPABILITIES)]:
        assert cap not in authz.capabilities_for_roles(roles), roles
    # No existing capability was reused or widened for department movement.
    assert not [c for c in authz.ALL_CAPABILITIES if "move" in c or "department_history" in c]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER", "SUPERVISOR",
                                  "MAINTENANCE", "TECHNICIAN", "DRIVER", "NO_SUCH_ROLE"])
async def test_r2fg_auth_every_dev_role_is_refused_with_zero_repository_calls(role) -> None:
    repo = test_repo()
    response = await http("POST", EVENTS, repo, role=role, json=move(A, None, D1))
    assert response.status_code == 403
    assert repo.calls == [] and repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fg_auth_the_explicit_pending_grant_reaches_the_service() -> None:
    repo = test_repo()
    response = await http("POST", EVENTS, repo, json=move(A, None, D1), grant_pending=True)
    assert response.status_code == 200, response.text
    assert response.json()["current_department_id"] == A
    (row,) = history(repo)
    assert (row["recorded_by"], row["is_test_data"], row["test_batch_id"]) == (
        "synthetic-mover", "TRUE", MOCK_TEST_BATCH_ID)


@pytest.mark.asyncio
async def test_r2fg_auth_request_id_and_strict_body_before_any_read() -> None:
    repo = test_repo()
    assert _code(await http("POST", EVENTS, repo, json=move(A, None, D1), request_id=None, grant_pending=True)) == (
        422, "REQUEST_ID_REQUIRED")
    server_set = ("record_id", "record_kind", "revision_no", "supersedes_record_id", "recorded_at", "recorded_by",
                  "request_id", "request_fingerprint", "recorded_from_department_id", "recorded_from_source",
                  "is_test_data", "test_batch_id", "related_request_id", "personnel_id")
    bad = [{**move(A, None, D1), name: "x"} for name in server_set]
    bad += [{"operation": "END", "effective": eff(D1), "expected_current_department_id": A},  # no END operation
            {**cancellation("E", "1", A), "department_id": B},
            {k: v for k, v in correction("E", "1", A, D1, B).items() if k != "department_id"}]
    for payload in bad:
        assert (await http("POST", EVENTS, repo, json=payload, grant_pending=True)).status_code == 422, payload
    assert repo.calls == [] and repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_r2fg_auth_history_read_needs_only_can_view(role) -> None:
    response = await http("GET", f"{API}/personnel/P-T/department-history", test_repo(), role=role)
    assert response.status_code == 200 and response.json()["current_status"] == "NONE"


# ---------------------------------------------------------------------------
# R2FG-TL — movement closes the former period and opens the new one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fg_tl_initial_department_history() -> None:
    repo = repo_with()
    empty = await read(repo)
    assert (empty.timeline.status, empty.timeline.current_status, empty.timeline.events) == (STATUS_VALID, "NONE", ())
    outcome = await record(repo, move(A, None, D1))
    assert outcome.changed and outcome.current_department_id == A
    (row,) = history(repo)
    assert list(row) == list(PERSONNEL_DEPARTMENT_HISTORY_COLUMNS) and len(row) == 21
    assert (row["record_kind"], row["entry_operation"], row["revision_no"]) == ("ASSIGNMENT", "TRANSFER", "1")
    assert (row["personnel_id"], row["department_id"], row["recorded_from_source"]) == ("P-1", A, "NONE")
    assert row["event_id"] == row["record_id"] and row["record_id"].startswith("PDH-")


@pytest.mark.asyncio
async def test_r2fg_tl_movement_closes_the_former_period_and_opens_the_new_one() -> None:
    repo = repo_with()
    first, second = await seed_ab(repo)
    assert (history(repo)[1]["recorded_from_department_id"], history(repo)[1]["recorded_from_source"]) == (A, "EVENT")
    tl = (await read(repo)).timeline
    periods = {e.event_id: e for e in tl.events}
    # A's period is CLOSED at exactly B's start; B's period is OPEN; nothing overlaps.
    assert periods[first].derived_end_at == periods[second].effective_at
    assert periods[second].derived_end_at is None
    assert (tl.current_department_id, tl.current_since) == (B, periods[second].effective_at)
    open_periods = [e for e in tl.events if e.in_force and e.derived_end_at is None]
    assert len(open_periods) == 1
    assert await code_of(record(repo, move(C, B, D2))) == "PERSONNEL_DEPARTMENT_EVENT_NOT_LATEST"
    assert await code_of(record(repo, move(C, B, D3))) == "PERSONNEL_DEPARTMENT_EVENT_SAME_INSTANT"
    assert (await record(repo, move(B, B, D4))).changed is False  # same department: no-op


@pytest.mark.asyncio
async def test_r2fg_tl_backdated_movement_reshapes_periods_without_overlap() -> None:
    repo = repo_with()
    first, second = await seed_ab(repo)
    assert await code_of(record(repo, {**insertion(C, B, D2), "reason_th": " "})) == "REASON_REQUIRED"
    assert await code_of(record(repo, insertion(C, B, D4))) == "PERSONNEL_DEPARTMENT_INSERTION_NOT_HISTORICAL"
    outcome = await record(repo, insertion(C, B, D2))
    assert outcome.changed and outcome.current_department_id == B
    inserted = history(repo)[-1]
    assert (inserted["entry_operation"], inserted["recorded_from_department_id"]) == ("INSERTION", A)
    tl = (await read(repo)).timeline
    ordered = [e for e in tl.events if e.in_force]
    assert [e.department_id for e in ordered] == [A, C, B]
    assert ordered[0].derived_end_at == ordered[1].effective_at  # A now closes at the backdated C
    assert ordered[1].derived_end_at == ordered[2].effective_at  # C closes at B
    assert ordered[2].derived_end_at is None


@pytest.mark.asyncio
async def test_r2fg_tl_correction_is_an_immutable_new_revision() -> None:
    repo = repo_with()
    first, _ = await seed_ab(repo)
    before = copy.deepcopy(history(repo))
    outcome = await record(repo, correction(first, "1", B, D2, C))
    assert outcome.changed and history(repo)[:2] == before  # nothing rewritten
    row = history(repo)[-1]
    assert (row["record_kind"], row["revision_no"], row["supersedes_record_id"], row["department_id"]) == (
        "CORRECTION", "2", first, C)
    await record(repo, correction(first, "2", B, D1, C))
    assert (history(repo)[-1]["revision_no"], history(repo)[-1]["supersedes_record_id"]) == ("3", row["record_id"])
    assert (await record(repo, correction(first, "3", B, D1, C))).changed is False
    period = next(e for e in (await read(repo)).timeline.events if e.event_id == first)
    assert (period.department_id, period.revision_no) == (C, "3")


@pytest.mark.asyncio
async def test_r2fg_tl_cancellation_is_terminal_and_rederives_the_periods() -> None:
    repo = repo_with()
    first, second = await seed_ab(repo)
    outcome = await record(repo, cancellation(second, "1", B))
    assert outcome.current_department_id == A
    tl = (await read(repo)).timeline
    cancelled = next(e for e in tl.events if e.event_id == second)
    assert cancelled.in_force is False and cancelled.notes == ("CANCELLED",)
    assert next(e for e in tl.events if e.event_id == first).derived_end_at is None  # A re-opened
    assert await code_of(record(repo, cancellation(second, "2", A))) == "PERSONNEL_DEPARTMENT_EVENT_CANCELLED"
    assert await code_of(record(repo, correction("PDH-none", "1", A, D4, B))) == "PERSONNEL_DEPARTMENT_EVENT_NOT_FOUND"
    assert len(history(repo)) == 3  # both original rows preserved


@pytest.mark.asyncio
async def test_r2fg_tl_actor_and_effective_versus_recorded_time() -> None:
    repo = repo_with()
    before = datetime.now(timezone.utc)
    await record(repo, move(A, None, D1), user="synthetic-actor-1")
    row = history(repo)[0]
    assert row["recorded_by"] == "synthetic-actor-1"
    assert (row["effective_at"], row["effective_precision"], row["effective_source"]) == (
        "2025-12-31T17:00:00+00:00", "DATE", "CLIENT")
    assert datetime.fromisoformat(row["recorded_at"]) >= before  # server audit time, separate from effective
    await record(repo, move(B, A), user="synthetic-actor-2")
    assert (history(repo)[1]["effective_source"], history(repo)[1]["recorded_by"]) == ("SERVER_NOW", "synthetic-actor-2")


# ---------------------------------------------------------------------------
# R2FG-ASOF — historical / as-of lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fg_asof_lookup_through_movements_backdating_correction_and_cancellation() -> None:
    repo = repo_with()
    first, second = await seed_ab(repo)

    async def at(date: str):
        r = await read(repo, as_of={"mode": "DATE", "date": date})
        return r.as_of_status, r.as_of_department_id

    assert await at("2025-12-15") == ("NONE", None)
    assert await at(D1) == ("EVENT", A)  # an event effective exactly at the instant applies
    assert await at("2026-02-15") == ("EVENT", A)
    assert await at(D3) == ("EVENT", B)
    await record(repo, insertion(C, B, D2))  # backdated
    assert await at("2026-02-15") == ("EVENT", C) and await at("2026-01-15") == ("EVENT", A)
    await record(repo, correction(first, "1", B, "2026-01-10", A))  # A now starts later
    assert await at("2026-01-05") == ("NONE", None)
    await record(repo, cancellation(second, "1", B))
    assert await at(D4) == ("EVENT", C)  # B cancelled: C continues
    r = await read(repo, as_of={"mode": "DATETIME", "at": "2026-02-20T10:00:00+07:00"})
    assert (r.as_of_status, r.as_of_department_id, r.as_of) == ("EVENT", C, "2026-02-20T03:00:00+00:00")


@pytest.mark.asyncio
async def test_r2fg_asof_api_parameters() -> None:
    repo = test_repo()
    await http("POST", EVENTS, repo, json=move(A, None, D1), grant_pending=True)
    base = f"{API}/personnel/P-T/department-history"
    body = (await http("GET", f"{base}?as_of_date=2026-01-05", repo, role="TECHNICIAN")).json()
    assert (body["as_of_status"], body["as_of_department_id"]) == ("EVENT", A)
    none = (await http("GET", f"{base}?as_of_date=2025-01-01", repo, role="TECHNICIAN")).json()
    assert (none["as_of_status"], none["as_of_department_id"]) == ("NONE", None)
    plain = (await http("GET", base, repo, role="TECHNICIAN")).json()
    assert plain["as_of"] is None and plain["as_of_status"] is None
    both = await http("GET", f"{base}?as_of_date=2026-01-05&as_of_at=2026-01-05T00:00:00Z", repo, role="TECHNICIAN")
    assert _code(both) == (422, "AS_OF_INVALID")
    assert (await http("GET", f"{base}?as_of_date=05/01/2026", repo, role="TECHNICIAN")).status_code == 422


def test_r2fg_asof_pure_tie_is_undetermined_never_none() -> None:
    rows = [
        {"record_id": "PDH-1", "personnel_id": "P", "department_id": A, "record_kind": "ASSIGNMENT",
         "entry_operation": "TRANSFER", "event_id": "PDH-1", "revision_no": "1", "supersedes_record_id": "",
         "effective_at": "2026-01-01T00:00:00+00:00", "effective_precision": "DATETIME", "effective_source": "CLIENT",
         "recorded_from_department_id": "", "recorded_from_source": "NONE", "recorded_at": "2026-01-02T00:00:00+00:00",
         "recorded_by": "u", "request_id": "r1", "request_fingerprint": "0" * 64, "reason_th": "",
         "related_request_id": "", "is_test_data": "FALSE", "test_batch_id": ""},
    ]
    rows.append({**rows[0], "record_id": "PDH-2", "event_id": "PDH-2", "department_id": B, "request_id": "r2"})
    rows.append({**rows[0], "record_id": "PDH-3", "event_id": "PDH-3", "department_id": C, "request_id": "r3",
                 "effective_at": "2026-03-01T00:00:00+00:00"})
    tl = derive_department_timeline(rows)
    assert tl.status == STATUS_AMBIGUOUS and tl.current_status == "UNDETERMINED"
    assert department_at(tl, datetime(2026, 2, 1, tzinfo=timezone.utc))[0] == "UNDETERMINED"
    # A later unique event decides the answer regardless of the earlier tie.
    assert department_at(tl, datetime(2026, 4, 1, tzinfo=timezone.utc))[:2] == ("EVENT", C)
    assert department_at(tl, datetime(2025, 1, 1, tzinfo=timezone.utc))[0] == "NONE"


# ---------------------------------------------------------------------------
# R2FG-REF — department reference proof (missing / ambiguous / cross-scope)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fg_ref_missing_and_duplicate_department_are_refused() -> None:
    repo = repo_with(departments=[dept(A), dept(B), dept(B)])
    assert await code_of(record(repo, move("DEPT-SYN-404", None, D1))) == "DEPARTMENT_NOT_FOUND"
    assert await code_of(record(repo, move(B, None, D1))) == "DEPARTMENT_ID_AMBIGUOUS"
    for near in ("dept-syn-a", " DEPT-SYN-A", "DEPT-SYN-A ", "DEPT-SYN"):
        assert await code_of(record(repo, move(near, None, D1))) == "DEPARTMENT_NOT_FOUND", near
    assert history(repo) == [] and repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fg_ref_cross_scope_and_batch_are_refused() -> None:
    t_people = [legacy_person("P-T", test=True, batch=BATCH)]
    cases = [
        ("TEST", [dept(A)], "DEPARTMENT_SCOPE_UNPROVEN"),  # TEST -> REAL department
        ("TEST", [dept(A, test=True, batch="SYN-OTHER")], "DEPARTMENT_SCOPE_UNPROVEN"),  # wrong batch
        ("TEST", [], "DEPARTMENT_NOT_FOUND"),  # TEST-capable master, no such id anywhere
        ("REAL", [dept(A, test=True, batch=BATCH)], "DEPARTMENT_SCOPE_UNPROVEN"),  # REAL -> TEST department
    ]
    for context, departments, code in cases:
        people = t_people if context == "TEST" else [legacy_person("P-T")]
        repo = repo_with(people=people, departments=departments)
        assert await code_of(record(repo, move(A, None, D1), pid="P-T", context=context)) == code, (context, code)
        assert repo.registry_write_log == []
    ok = repo_with(people=t_people, departments=[dept(A), dept(A, test=True, batch=BATCH)])
    assert (await record(ok, move(A, None, D1), pid="P-T", context="TEST")).changed  # same id REAL+TEST: TEST one
    assert (history(ok)[0]["is_test_data"], history(ok)[0]["test_batch_id"]) == ("TRUE", BATCH)


@pytest.mark.asyncio
async def test_r2fg_ref_id_text_never_proves_test_scope_and_bad_flags_fail_closed() -> None:
    repo = repo_with(people=[legacy_person("P-T", test=True, batch=BATCH)], departments=[dept("DEPT-TEST-LOOKS")])
    assert await code_of(record(repo, move("DEPT-TEST-LOOKS", None, D1), pid="P-T", context="TEST")) == (
        "DEPARTMENT_SCOPE_UNPROVEN")
    for bad in ({**dept(A), "is_test_data": "yes"}, {**dept(A), "is_test_data": ""}, {**dept(A), "test_batch_id": "B"}):
        broken = repo_with(departments=[bad, dept(B)])
        assert await code_of(record(broken, move(B, None, D1))) == "DEPARTMENT_MASTER_DATA_INVALID"
        assert broken.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fg_ref_no_lifecycle_gate_on_department_or_personnel() -> None:
    repo = repo_with(people=[{**legacy_person("P-1"), "active_status": "INACTIVE"}],
                     departments=[dept(A, active="FALSE")])
    assert (await record(repo, move(A, None, D1))).changed  # PENDING: no is_active / active_status gate


@pytest.mark.asyncio
async def test_r2fg_ref_persisted_history_references_are_proven() -> None:
    src = repo_with()
    await seed_ab(src)
    rows = copy.deepcopy(history(src))
    cases = [
        ([dept(B)], {"DEPARTMENT_REFERENCE_MISSING": 1}),  # A (old period + recorded-from) gone
        ([dept(A), dept(B), dept(B)], {"DEPARTMENT_REFERENCE_AMBIGUOUS": 1}),
        ([dept(A, test=True, batch=BATCH), dept(B)], {"DEPARTMENT_REFERENCE_SCOPE_UNPROVEN": 1}),
    ]
    for departments, issues in cases:
        repo = repo_with(departments=departments)
        repo._personnel_department_history = copy.deepcopy(rows)
        with pytest.raises(ApiError) as exc:
            await read(repo)
        assert exc.value.code == "PERSONNEL_DEPARTMENT_HISTORY_DATA_INVALID"
        assert exc.value.details["issues"] == issues
        assert await code_of(record(repo, move(C, B, D4))) == "PERSONNEL_DEPARTMENT_HISTORY_DATA_INVALID"
        assert repo.registry_write_log == []
    test_rows = [{**r, "is_test_data": "TRUE", "test_batch_id": BATCH} for r in rows]
    t_repo = repo_with(people=[legacy_person("P-1", test=True, batch=BATCH)], departments=[dept(A), dept(B)])
    t_repo._personnel_department_history = test_rows  # TEST history -> REAL-only departments
    with pytest.raises(ApiError) as exc:
        await read(t_repo, context="TEST")
    assert exc.value.details["issues"] == {"DEPARTMENT_REFERENCE_SCOPE_UNPROVEN": 2}


@pytest.mark.asyncio
async def test_r2fg_ref_department_read_is_bounded() -> None:
    repo = repo_with()
    reference = await repo.read_department_reference()
    assert reference.columns == frozenset({"department_id", "is_test_data", "test_batch_id"})
    assert all(set(r) == {"department_id", "is_test_data", "test_batch_id"} for r in reference.rows)
    await seed_ab(repo)
    repo.calls.clear()
    await read(repo)
    assert repo.calls == ["read_personnel_relationship_master", "read_personnel_department_history_validated",
                          "read_department_reference"]


# ---------------------------------------------------------------------------
# R2FG-SCOPE — personnel and history scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fg_scope_personnel_and_history_are_isolated() -> None:
    people = [legacy_person("P-1"), legacy_person("P-1", test=True, batch=BATCH)]
    repo = repo_with(people=people, departments=[dept(A), dept(B, test=True, batch=BATCH)])
    await record(repo, move(A, None, D1))
    await record(repo, move(B, None, D1), context="TEST")  # same personnel id, other scope: independent
    assert (await read(repo)).timeline.current_department_id == A
    assert (await read(repo, context="TEST")).timeline.current_department_id == B
    assert await code_of(record(repo, move(A, None, D1), pid="P-9")) == "PERSONNEL_NOT_FOUND"
    only_test = repo_with(people=[legacy_person("P-T", test=True, batch=BATCH)])
    assert await code_of(record(only_test, move(A, None, D1), pid="P-T")) == "PERSONNEL_NOT_FOUND"  # REAL request
    history(repo)[0]["is_test_data"] = "maybe"
    assert await code_of(read(repo)) == "PERSONNEL_DEPARTMENT_HISTORY_DATA_INVALID"
    assert await code_of(svc(repo_with(), None).department_history("P-1")) == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# R2FG-STALE / -REPLAY / -WRITE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fg_stale_before_no_op_and_revision_guard() -> None:
    repo = repo_with()
    first, _ = await seed_ab(repo)
    for payload in (move(B, A, D4), move(B, None, D4), insertion(C, A, D2)):
        with pytest.raises(ApiError) as exc:
            await record(repo, payload)
        assert (exc.value.code, exc.value.details) == ("PERSONNEL_DEPARTMENT_HISTORY_STALE",
                                                       {"field": "current_department_id"})
    for payload in (correction(first, "2", B, D2, C), cancellation(first, 1, B)):
        with pytest.raises(ApiError) as exc:
            await record(repo, payload)
        assert exc.value.details == {"field": "revision_no"}
    assert len(history(repo)) == 2


@pytest.mark.asyncio
async def test_r2fg_replay_exact_reused_and_unknown_outcomes() -> None:
    repo = repo_with()
    first = await record(repo, move(A, None, D1), request_id="req-1")
    again = await record(repo, move(A, None, D1), request_id="req-1")
    assert again.replayed and again.record_ids == (first.record_id,) and repo.registry_write_log == ["W1"]
    assert await code_of(record(repo, move(B, None, D1), request_id="req-1")) == "REQUEST_ID_REUSED"
    assert await code_of(record(repo, move(A, None, D1), pid="P-2", request_id="req-1")) == "REQUEST_ID_REUSED"
    applied = repo_with()
    applied.registry_write_faults["W1"] = "unknown_applied"
    assert await code_of(record(applied, move(A, None, D1), request_id="req-u")) == (
        "PERSONNEL_DEPARTMENT_HISTORY_WRITE_FAILED")
    applied.registry_write_faults.clear()
    resend = await record(applied, move(A, None, D1), request_id="req-u")
    assert resend.replayed and applied.registry_write_log == ["W1"] and len(history(applied)) == 1
    lost = repo_with()
    lost.registry_write_faults["W1"] = "unknown_not_applied"
    with pytest.raises(ApiError) as exc:
        await record(lost, move(A, None, D1), request_id="req-n")
    assert exc.value.details == {"history_write_outcome": "unknown", "request_id": "req-n"}
    lost.registry_write_faults.clear()
    assert (await record(lost, move(A, None, D1), request_id="req-n")).changed
    assert lost.registry_write_log == ["W1", "W1"] and len(history(lost)) == 1


@pytest.mark.asyncio
async def test_r2fg_write_history_only_and_no_legacy_rewrite() -> None:
    repo = repo_with()
    frozen = {name: copy.deepcopy(getattr(repo, name)) for name in (
        "_personnel_master", "_department_master", "_personnel_lifecycle_history", "_department_lifecycle_history",
        "_personnel_technician_link_history", "_personnel_account_link_history", "_personnel_driver_link_history",
        "_equipment_caretaker_history", "_crane_driver_responsibility_history")}
    first, second = await seed_ab(repo)
    await record(repo, insertion(C, B, D2))
    await record(repo, correction(first, "1", B, "2025-12-15", A))
    await record(repo, cancellation(second, "1", B))
    assert repo.registry_write_log == ["W1"] * 5 and len(history(repo)) == 5
    for name, before in frozen.items():
        assert getattr(repo, name) == before, name  # personnel_master.department untouched, no projection
    assert all(r["department"] == "SYN-LEGACY-DEPARTMENT-TEXT" for r in repo._personnel_master)
    assert set(repo.calls) <= METHODS


# ---------------------------------------------------------------------------
# R2FG-AMBIG / -INVALID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fg_ambig_ties_refuse_new_events_and_only_tied_events_are_repairable() -> None:
    repo = repo_with()
    await record(repo, move(A, None, D1))
    await record(repo, move(B, A, D2))
    clone = {**history(repo)[1], "record_id": "PDH-" + "a" * 32, "event_id": "PDH-" + "a" * 32,
             "department_id": C, "request_id": "seed-tie", "request_fingerprint": "0" * 64}
    history(repo).append(clone)
    tl = (await read(repo)).timeline
    assert (tl.status, tl.current_status, tl.current_department_id) == (STATUS_AMBIGUOUS, "UNDETERMINED", None)
    for payload in (move(A, None, D4), insertion(A, None, "2026-01-15")):
        assert await code_of(record(repo, payload)) == "PERSONNEL_DEPARTMENT_TIMELINE_AMBIGUOUS"
    first = history(repo)[0]["event_id"]
    assert await code_of(record(repo, correction(first, "1", None, "2025-12-01", A))) == (
        "PERSONNEL_DEPARTMENT_TIMELINE_AMBIGUOUS")
    resolved = await record(repo, cancellation(clone["event_id"], "1", None))
    assert resolved.timeline_status_after == STATUS_VALID and resolved.current_department_id == B


@pytest.mark.asyncio
async def test_r2fg_invalid_structural_defects_fail_closed() -> None:
    repo = repo_with()
    first, _ = await seed_ab(repo)
    await record(repo, correction(first, "1", B, D2, C))
    rows = copy.deepcopy(history(repo))
    assert derive_department_timeline(rows).status == STATUS_VALID
    cases = {
        "REVISION_FORK_OR_GAP": [*rows, {**rows[2], "record_id": "PDH-fork", "request_id": "fork"}],
        "DANGLING_REFERENCE": [*rows[:2], {**rows[2], "supersedes_record_id": "PDH-missing"}],
        "CORRECTION_CHANGES_EVENT_NATURE": [*rows[:2], {**rows[2], "department_id": ""}],
        "RECORD_ID_DUPLICATE": [*rows, dict(rows[0])],
    }
    for code, broken in cases.items():
        tl = derive_department_timeline(broken)
        assert tl.status == STATUS_INVALID and code in tl.issue_counts, (code, tl.issue_counts)
    assert "ENTRY_OPERATION_INVALID" in validate_department_row({**rows[0], "entry_operation": "END",
                                                                 "department_id": ""})
    assert "FIELD_REQUIRED:department_id" in validate_department_row({**rows[0], "department_id": ""})
    history(repo)[1]["revision_no"] = "2"
    assert await code_of(read(repo)) == "PERSONNEL_DEPARTMENT_HISTORY_DATA_INVALID"


# ---------------------------------------------------------------------------
# R2FG-LEGACY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fg_legacy_personnel_read_and_lifecycle_are_unchanged() -> None:
    repo = repo_with()
    await seed_ab(repo)
    # R2-C2 Personnel Scope Option S (deliberate evolution, S3): P-1 is a REAL-scope row
    # (its history is seeded in REAL), so the personnel GET runs in the REAL server context.
    from app.config import Settings

    real = Settings(data_repository="google_sheets", registry_data_context="REAL")
    response = await http("GET", f"{API}/personnel/P-1", repo, role="TECHNICIAN", request_id=None, settings=real)
    assert response.status_code == 200
    assert set(response.json()) == {"personnel_id", "first_name", "last_name", "active_status"}
    from app.repositories.google_sheets import schemas

    from app.domain.personnel import PERSONNEL_MASTER_COLUMNS, PERSONNEL_MASTER_TARGET_COLUMNS

    assert "department" in PERSONNEL_MASTER_COLUMNS and PERSONNEL_MASTER_TARGET_COLUMNS.count("department") == 1
    assert not [h for h in PERSONNEL_MASTER_TARGET_COLUMNS if "department_id" in h or "current_department" in h]
    assert "department" not in schemas.PERSONNEL_DRIVER_LINK_MASTER_SHEET.required_headers


def test_r2fg_legacy_sources_never_touch_personnel_department_text() -> None:
    from app.api.v1 import personnel_department_history_routes, personnel_department_history_schemas
    from app.domain import personnel_department_history, personnel_department_timeline
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    for module in (personnel_department_history, personnel_department_timeline, personnel_department_history_routes,
                   personnel_department_history_schemas):
        code = inspect.getsource(module).split('"""', 2)[-1]
        assert '"department"' not in code and "'department'" not in code, module.__name__
        assert "write_lifecycle_state_cell" not in code and "write_personnel_link_cell" not in code
    core = {s.tab_name for s in GoogleSheetsRepository._CORE_SCHEMAS}
    assert "personnel_department_history" not in core and "department_master" not in core
    assert schemas.DEPARTMENT_REFERENCE_READ_SHEET.required_headers == ("department_id", "is_test_data",
                                                                        "test_batch_id")
    names = {n for n, v in vars(Repository).items() if getattr(v, "__isabstractmethod__", False)}
    assert {n for n in names if "department_history" in n} == {
        "read_personnel_department_history_validated", "append_personnel_department_history"}
    assert not [n for n in names if "department" in n and "write" in n]
