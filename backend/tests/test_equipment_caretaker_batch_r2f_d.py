"""R2 Batch R2f-d — Equipment ↔ Technician caretaker periods, mock / service level.

The R2f-d implementation authorization. Every row is SYNTHETIC and labelled;
no live workbook value or production count is used. TEST-scoped equipment /
technicians are explicit synthetic fixtures (scope TEST + batch), never derived
from an id. REAL-context cases run against the service directly (mock mode is
always the TEST context at the API).

Batch-local ids: R2FD-AUTH, -TL (timeline), -CARD (cardinality / exclusivity),
-GATE (ACTIVE gate), -SCOPE, -STALE, -REPLAY, -W1, -AMBIG, -INVALID, -REF
(references / legacy untouched), -CHECKLIST (inspection non-gate).
"""
from __future__ import annotations

import copy
import inspect
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain import authz
from app.domain.caretaker_timeline import (
    EQUIPMENT_CARETAKER_HISTORY_COLUMNS,
    STATUS_AMBIGUOUS,
    STATUS_INVALID,
    STATUS_VALID,
    derive_caretaker_timeline,
    validate_caretaker_row,
)
from app.domain.equipment_caretaker import EquipmentCaretakerService
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST, Repository, ScopedReferenceRow
from tests.test_relationship_read_batch_r2f_a import RelSpy, person, tech

API = "/api/v1"
BATCH = "SYN-R2FD-BATCH"
REASON = "บันทึกผู้ดูแลย้อนหลัง (ทดสอบ)"
E1, E2 = "EQP-SYN-1", "EQP-SYN-2"
T1, T2, T3 = "TEC-SYN-1", "TEC-SYN-2", "TEC-SYN-3"
D1, D2, D3, D4 = "2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"
CARETAKER_METHODS = {"read_equipment_reference", "read_equipment_caretaker_history_validated",
                     "read_technician_master_reference", "read_personnel_relationship_master",
                     "append_equipment_caretaker_history"}


def equip(eid: str, *, scope: str = REFERENCE_SCOPE_REAL, batch: str = "") -> ScopedReferenceRow:
    return ScopedReferenceRow(values={"equipment_id": eid}, scope=scope, test_batch_id=batch)


class CareSpy(RelSpy):
    def __init__(self, people=None, technicians=None, equipment=None, *, fail=None) -> None:
        super().__init__(people, technicians, fail=fail)
        if equipment is not None:
            self._equipment_reference = list(equipment)


def repo_with(people=None, technicians=None, equipment=None) -> CareSpy:
    return CareSpy(
        people=people if people is not None else [person("P-1", technician_id=T1), person("P-2", technician_id=T2),
                                                  person("P-3", technician_id=T3)],
        technicians=technicians if technicians is not None else [tech(T1), tech(T2), tech(T3)],
        equipment=equipment if equipment is not None else [equip(E1), equip(E2)],
    )


def test_repo() -> CareSpy:
    """TEST-scope fixtures of the mock server batch (for the API, which is TEST in mock mode)."""
    return CareSpy(
        people=[person("P-T1", technician_id=T1, test=True, batch=MOCK_TEST_BATCH_ID),
                person("P-T2", technician_id=T2, test=True, batch=MOCK_TEST_BATCH_ID)],
        technicians=[tech(T1, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID),
                     tech(T2, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)],
        equipment=[equip(E1, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)],
    )


def svc(repo, context: str | None = "REAL", batch: str = BATCH) -> EquipmentCaretakerService:
    return EquipmentCaretakerService(repo, context, batch)


def eff(date: str | None = None, *, at: str | None = None) -> dict:
    if at is not None:
        return {"mode": "DATETIME", "at": at}
    return {"mode": "DATE", "date": date} if date else {"mode": "NOW"}


def transfer(technician: str, expected: str | None, date: str | None = None, **extra) -> dict:
    return {"operation": "TRANSFER", "technician_id": technician, "effective": eff(date),
            "expected_current_technician_id": expected, **extra}


def insertion(technician: str, expected: str | None, date: str, reason: str = REASON) -> dict:
    return {"operation": "INSERTION", "technician_id": technician, "effective": eff(date),
            "expected_current_technician_id": expected, "reason_th": reason}


def end(expected: str | None, date: str | None = None, **extra) -> dict:
    return {"operation": "END", "effective": eff(date), "expected_current_technician_id": expected, **extra}


def correction(event_id: str, revision: str, expected: str | None, date: str, technician: str | None = None,
               reason: str = REASON) -> dict:
    out = {"operation": "CORRECTION", "event_id": event_id, "expected_revision_no": revision,
           "effective": eff(date), "expected_current_technician_id": expected, "reason_th": reason}
    if technician is not None:
        out["technician_id"] = technician
    return out


def cancellation(event_id: str, revision: str, expected: str | None, reason: str = REASON) -> dict:
    return {"operation": "CANCELLATION", "event_id": event_id, "expected_revision_no": revision,
            "expected_current_technician_id": expected, "reason_th": reason}


async def record(repo, payload: dict, *, equipment: str = E1, context: str = "REAL", batch: str = BATCH,
                 request_id: str | None = None):
    return await svc(repo, context, batch).record_event(equipment, payload, request_id=request_id or str(uuid.uuid4()),
                                                        user_id="dev-user")


async def code_of(coro) -> str:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value.code


async def caretakers(repo, equipment: str = E1, context: str = "REAL", batch: str = BATCH):
    return await svc(repo, context, batch).caretakers(equipment)


def history(repo) -> list[dict[str, str]]:
    return repo._equipment_caretaker_history


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


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


async def seed_three(repo) -> list[str]:
    """T1 from D1, T2 from D3 (TRANSFERs); returns the two event ids."""
    first = await record(repo, transfer(T1, None, D1))
    second = await record(repo, transfer(T2, T1, D3))
    return [first.event_id, second.event_id]


# ---------------------------------------------------------------------------
# R2FD-AUTH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE_MANAGER"])
async def test_r2fd_auth_admin_and_maintenance_manager_may_assign(role) -> None:
    repo = test_repo()
    response = await http("POST", f"{API}/equipment/{E1}/caretaker-events", repo, role=role,
                          json=transfer(T1, None, D1))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True and body["current_technician_id"] == T1 and body["current_status"] == "EVENT"
    (row,) = history(repo)
    assert (row["is_test_data"], row["test_batch_id"], row["recorded_by"]) == ("TRUE", MOCK_TEST_BATCH_ID, "dev-user")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "SUPERVISOR", "MAINTENANCE", "NO_SUCH_ROLE"])
async def test_r2fd_auth_other_roles_are_refused_with_zero_repository_calls(role) -> None:
    repo = test_repo()
    response = await http("POST", f"{API}/equipment/{E1}/caretaker-events", repo, role=role,
                          json=transfer(T1, None, D1))
    assert response.status_code == 403
    assert repo.calls == [] and repo.registry_write_log == []


def test_r2fd_auth_capability_is_dedicated_and_not_implied_by_any_other() -> None:
    cap = authz.CAN_ASSIGN_EQUIPMENT_CARETAKER
    assert cap == "can_assign_equipment_caretaker" and cap in authz.ALL_CAPABILITIES
    holders = {role for role, caps in authz.ROLE_CAPABILITIES.items() if cap in caps}
    assert holders == {"ADMIN", "MAINTENANCE_MANAGER"}
    for reused in ("can_manage_personnel", "can_link_personnel_technician", "can_link_personnel_account",
                   "can_record_inspection", "can_transfer_equipment_branch"):
        assert reused != cap
    source = Path(inspect.getfile(__import__("app.api.v1.equipment_caretaker_routes", fromlist=["x"]))).read_text()
    for forbidden in ("CAN_MANAGE_PERSONNEL", "CAN_LINK_PERSONNEL_TECHNICIAN", "CAN_LINK_PERSONNEL_ACCOUNT"):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_r2fd_auth_request_id_and_strict_body_are_checked_before_any_read() -> None:
    repo = test_repo()
    path = f"{API}/equipment/{E1}/caretaker-events"
    response = await http("POST", path, repo, json=transfer(T1, None, D1), request_id=None)
    assert _code(response) == (422, "REQUEST_ID_REQUIRED")
    bad_bodies = [
        {**transfer(T1, None, D1), "recorded_by": "someone"},  # server-set field
        {**transfer(T1, None, D1), "is_test_data": "FALSE"},
        {**transfer(T1, None, D1), "record_kind": "CORRECTION"},
        {**end(T1, D1), "technician_id": T2},  # END takes no technician
        {**cancellation("E", "1", None), "effective": eff(D1)},  # CANCELLATION takes no time
        {"operation": "DRIVER_ASSIGN", "technician_id": T1},
        {k: v for k, v in transfer(T1, None, D1).items() if k != "expected_current_technician_id"},
    ]
    for payload in bad_bodies:
        response = await http("POST", path, repo, json=payload)
        assert response.status_code == 422, payload
    assert repo.calls == [] and repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fd_auth_reads_need_only_can_view() -> None:
    repo = test_repo()
    await http("POST", f"{API}/equipment/{E1}/caretaker-events", repo, json=transfer(T1, None, D1))
    for role in ("TECHNICIAN", "DRIVER"):
        assert (await http("GET", f"{API}/equipment/{E1}/caretakers", repo, role=role)).status_code == 200
        assert (await http("GET", f"{API}/technicians/{T1}/equipment", repo, role=role)).status_code == 200


# ---------------------------------------------------------------------------
# R2FD-TL — TRANSFER / INSERTION / END / CORRECTION / CANCELLATION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fd_tl_first_transfer_records_no_previous_caretaker() -> None:
    repo = repo_with()
    outcome = await record(repo, transfer(T1, None, D1))
    assert outcome.changed and outcome.current_technician_id == T1 and outcome.timeline_status_after == STATUS_VALID
    (row,) = history(repo)
    assert (row["record_kind"], row["entry_operation"], row["revision_no"]) == ("ASSIGNMENT", "TRANSFER", "1")
    assert row["event_id"] == row["record_id"] and row["record_id"].startswith("ECH-")
    assert (row["recorded_from_technician_id"], row["recorded_from_source"]) == ("", "NONE")
    assert (row["is_test_data"], row["test_batch_id"], row["related_request_id"]) == ("FALSE", "", "")
    assert row["effective_at"] == "2025-12-31T17:00:00+00:00" and row["effective_precision"] == "DATE"
    assert list(row) == list(EQUIPMENT_CARETAKER_HISTORY_COLUMNS)


@pytest.mark.asyncio
async def test_r2fd_tl_transfer_closes_the_previous_period_and_never_overlaps() -> None:
    repo = repo_with()
    first, second = await seed_three(repo)
    assert history(repo)[1]["recorded_from_technician_id"] == T1 and history(repo)[1]["recorded_from_source"] == "EVENT"
    read = await caretakers(repo)
    assert read.timeline.current_technician_id == T2 and read.current_technician_resolution == "RESOLVED"
    periods = {e.event_id: e for e in read.timeline.events}
    assert periods[first].derived_end_at == periods[second].effective_at
    assert periods[second].derived_end_at is None


@pytest.mark.asyncio
async def test_r2fd_tl_transfer_now_is_allowed_and_must_be_latest() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D3))
    assert await code_of(record(repo, transfer(T2, T1, D2))) == "CARETAKER_EVENT_NOT_LATEST"
    assert await code_of(record(repo, transfer(T2, T1, D3))) == "CARETAKER_EVENT_SAME_INSTANT"
    outcome = await record(repo, transfer(T2, T1))  # NOW
    assert outcome.changed and history(repo)[-1]["effective_source"] == "SERVER_NOW"


@pytest.mark.asyncio
async def test_r2fd_tl_end_leaves_no_caretaker_and_a_blank_technician() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D1))
    outcome = await record(repo, end(T1, D2))
    assert outcome.changed and outcome.current_technician_id is None and outcome.current_status == "ENDED"
    row = history(repo)[-1]
    assert (row["entry_operation"], row["technician_id"], row["recorded_from_technician_id"]) == ("END", "", T1)
    read = await caretakers(repo)
    assert read.timeline.current_status == "ENDED" and read.current_technician is None
    assert read.current_technician_resolution == "NONE"
    # END without a current caretaker is a no-op; a later TRANSFER starts a new period.
    assert (await record(repo, end(None, D3))).changed is False
    assert (await record(repo, transfer(T2, None, D3))).current_technician_id == T2
    assert history(repo)[-1]["recorded_from_source"] == "NONE"


@pytest.mark.asyncio
async def test_r2fd_tl_no_history_means_no_caretaker() -> None:
    read = await caretakers(repo_with())
    assert (read.timeline.status, read.timeline.current_status, read.timeline.events) == (STATUS_VALID, "NONE", ())
    assert read.timeline.current_technician_id is None and read.current_technician_resolution == "NONE"


@pytest.mark.asyncio
async def test_r2fd_tl_insertion_is_historical_needs_a_reason_and_records_its_source() -> None:
    repo = repo_with()
    await seed_three(repo)
    assert await code_of(record(repo, {**insertion(T3, T2, D2), "reason_th": "  "})) == "REASON_REQUIRED"
    assert await code_of(record(repo, insertion(T3, T2, D4))) == "CARETAKER_INSERTION_NOT_HISTORICAL"
    now = {**insertion(T3, T2, D2), "effective": {"mode": "NOW"}}
    assert (await code_of(record(repo, now))).startswith("EFFECTIVE")
    outcome = await record(repo, insertion(T3, T2, D2))
    assert outcome.changed and outcome.current_technician_id == T2  # current unchanged
    row = history(repo)[-1]
    assert (row["entry_operation"], row["recorded_from_technician_id"], row["reason_th"]) == ("INSERTION", T1, REASON)
    events = [e for e in (await caretakers(repo)).timeline.events if e.in_force]
    assert [e.technician_id for e in events] == [T1, T3, T2]
    assert events[0].derived_end_at == events[1].effective_at and events[1].derived_end_at == events[2].effective_at
    # Same caretaker as the period it lands in: a no-op.
    assert (await record(repo, insertion(T1, T2, "2026-01-15"))).changed is False


@pytest.mark.asyncio
async def test_r2fd_tl_insertion_before_any_event_has_no_source() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D3))
    await record(repo, insertion(T2, T1, D1))
    assert (history(repo)[-1]["recorded_from_source"], history(repo)[-1]["recorded_from_technician_id"]) == ("NONE", "")
    assert await code_of(record(repo_with(), insertion(T1, None, D1))) == "CARETAKER_INSERTION_NOT_HISTORICAL"


@pytest.mark.asyncio
async def test_r2fd_tl_correction_is_a_new_revision_and_keeps_the_original_row() -> None:
    repo = repo_with()
    first, _second = await seed_three(repo)
    before = copy.deepcopy(history(repo))
    outcome = await record(repo, correction(first, "1", T2, D2, technician=T3))
    assert outcome.changed and outcome.event_id == first
    assert history(repo)[:2] == before  # append-only: nothing edited
    row = history(repo)[-1]
    assert (row["record_kind"], row["revision_no"], row["supersedes_record_id"], row["technician_id"]) == (
        "CORRECTION", "2", first, T3)
    period = next(e for e in (await caretakers(repo)).timeline.events if e.event_id == first)
    assert (period.technician_id, period.revision_no, period.entry_operation) == (T3, "2", "TRANSFER")
    # A second correction chains on the head revision.
    await record(repo, correction(first, "2", T2, D1, technician=T3))
    assert history(repo)[-1]["supersedes_record_id"] == row["record_id"] and history(repo)[-1]["revision_no"] == "3"


@pytest.mark.asyncio
async def test_r2fd_tl_correction_rules() -> None:
    repo = repo_with()
    first, second = await seed_three(repo)
    assert (await record(repo, correction(first, "1", T2, D1, technician=T1))).changed is False  # identical
    assert await code_of(record(repo, correction(first, "1", T2, D3, technician=T1))) == "CARETAKER_EVENT_SAME_INSTANT"
    assert await code_of(record(repo, correction(first, "1", T2, D2))) == "CARETAKER_TECHNICIAN_REQUIRED"
    assert await code_of(record(repo, {**correction(first, "1", T2, D2, technician=T1), "reason_th": ""})) == (
        "REASON_REQUIRED")
    assert await code_of(record(repo, correction("ECH-nope", "1", T2, D2, technician=T1))) == (
        "CARETAKER_EVENT_NOT_FOUND")
    await record(repo, end(T2, D4))
    end_event = history(repo)[-1]["event_id"]
    assert await code_of(record(repo, correction(end_event, "1", None, D4, technician=T1))) == (
        "CARETAKER_CORRECTION_CHANGES_EVENT_NATURE")
    # An END moved before every caretaker would end nothing: refused.
    assert await code_of(record(repo, correction(end_event, "1", None, "2025-12-01"))) == (
        "CARETAKER_END_WITHOUT_CARETAKER")
    moved = await record(repo, correction(end_event, "1", None, "2026-03-15"))
    assert moved.changed and moved.current_status == "ENDED"
    assert second


@pytest.mark.asyncio
async def test_r2fd_tl_cancellation_is_terminal_and_rederives_the_current_caretaker() -> None:
    repo = repo_with()
    first, second = await seed_three(repo)
    outcome = await record(repo, cancellation(second, "1", T2))
    assert outcome.changed and outcome.current_technician_id == T1
    row = history(repo)[-1]
    assert (row["record_kind"], row["technician_id"], row["effective_at"], row["revision_no"]) == (
        "CANCELLATION", "", "", "2")
    read = await caretakers(repo)
    cancelled = next(e for e in read.timeline.events if e.event_id == second)
    assert cancelled.in_force is False and cancelled.notes == ("CANCELLED",) and cancelled.technician_id == T2
    assert next(e for e in read.timeline.events if e.event_id == first).derived_end_at is None
    assert await code_of(record(repo, cancellation(second, "2", T1))) == "CARETAKER_EVENT_CANCELLED"
    assert await code_of(record(repo, correction(second, "2", T1, D4, technician=T2))) == "CARETAKER_EVENT_CANCELLED"
    assert await code_of(record(repo, {**cancellation(first, "1", T1), "reason_th": None})) == "REASON_REQUIRED"
    assert (await record(repo, cancellation(first, "1", T1))).current_status == "NONE"


@pytest.mark.asyncio
async def test_r2fd_tl_optional_reason_is_kept_exactly_and_bounded() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D1, reason_th="  เหตุผล  "))
    assert history(repo)[-1]["reason_th"] == "  เหตุผล  "
    assert await code_of(record(repo, transfer(T2, T1, D2, reason_th="x" * 501))) == "REASON_REQUIRED"
    assert await code_of(record(repo, end(T1, D2, reason_th=" "))) == "REASON_REQUIRED"


# ---------------------------------------------------------------------------
# R2FD-CARD — cardinality / exclusivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fd_card_one_caretaker_per_equipment_many_equipment_per_technician() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D1), equipment=E1)
    await record(repo, transfer(T1, None, D2), equipment=E2)
    reverse = await svc(repo).technician_equipment(T1)
    assert [i.equipment_id for i in reverse.items] == [E1, E2]
    await record(repo, transfer(T2, T1, D3), equipment=E1)
    assert [i.equipment_id for i in (await svc(repo).technician_equipment(T1)).items] == [E2]
    (item,) = (await svc(repo).technician_equipment(T2)).items
    assert (item.equipment_id, item.event_id) == (E1, history(repo)[-1]["event_id"])
    assert item.since == history(repo)[-1]["effective_at"]
    # Same technician again: a no-op (never a second concurrent period).
    assert (await record(repo, transfer(T2, T2, D4), equipment=E1)).changed is False
    in_force = [e for e in (await caretakers(repo)).timeline.events if e.in_force and e.derived_end_at is None]
    assert len(in_force) == 1


@pytest.mark.asyncio
async def test_r2fd_card_reverse_read_requires_the_technician_in_scope() -> None:
    repo = repo_with()
    assert await code_of(svc(repo).technician_equipment("TEC-NONE")) == "TECHNICIAN_NOT_FOUND"
    assert await code_of(svc(repo).technician_equipment("")) == "TECHNICIAN_NOT_FOUND"
    dup = repo_with(technicians=[tech(T1), tech(T1)])
    assert await code_of(svc(dup).technician_equipment(T1)) == "TECHNICIAN_ID_AMBIGUOUS"
    assert (await svc(repo).technician_equipment(T3)).items == ()


# ---------------------------------------------------------------------------
# R2FD-GATE — the Personnel + Technician ACTIVE gate (NEW assignments only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("technicians", "people", "code"), [
    ([tech(T1, status="INACTIVE")], [person("P-1", technician_id=T1)], "TECHNICIAN_NOT_ACTIVE"),
    ([tech(T1, status="")], [person("P-1", technician_id=T1)], "TECHNICIAN_NOT_ACTIVE"),
    ([tech(T1, status="active")], [person("P-1", technician_id=T1)], "TECHNICIAN_NOT_ACTIVE"),
    ([tech(T2)], [person("P-1", technician_id=T1)], "TECHNICIAN_NOT_FOUND"),
    ([tech(T1)], [person("P-1")], "TECHNICIAN_PERSONNEL_UNRESOLVED"),
    ([tech(T1)], [person("P-1", technician_id=T1), person("P-2", technician_id=T1)], "TECHNICIAN_PERSONNEL_AMBIGUOUS"),
    ([tech(T1)], [{**person("P-1", technician_id=T1), "active_status": "INACTIVE"}], "PERSONNEL_NOT_ACTIVE"),
    ([tech(T1)], [{**person("P-1", technician_id=T1), "active_status": ""}], "PERSONNEL_NOT_ACTIVE"),
    ([tech(T1), tech(T1)], [person("P-1", technician_id=T1)], "TECHNICIAN_ID_AMBIGUOUS"),
])
async def test_r2fd_gate_new_assignment_requires_active_technician_and_one_active_personnel(
    technicians, people, code
) -> None:
    repo = repo_with(people=people, technicians=technicians)
    assert await code_of(record(repo, transfer(T1, None, D1))) == code
    assert history(repo) == [] and repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fd_gate_applies_to_insertion_and_technician_changing_correction_only() -> None:
    repo = repo_with()
    first, _second = await seed_three(repo)
    repo._technician_master = [tech(T1, status="INACTIVE"), tech(T2), tech(T3, status="INACTIVE")]
    assert await code_of(record(repo, insertion(T3, T2, D2))) == "TECHNICIAN_NOT_ACTIVE"
    assert await code_of(record(repo, correction(first, "1", T2, D1, technician=T3))) == "TECHNICIAN_NOT_ACTIVE"
    # A time-only correction keeps the (now inactive) technician unchecked.
    assert (await record(repo, correction(first, "1", T2, D2, technician=T1))).changed is True
    # END and CANCELLATION are never gated.
    for row in repo._personnel_master:
        row["active_status"] = "INACTIVE"
    assert (await record(repo, end(T2, D4))).changed is True
    assert (await record(repo, cancellation(first, "2", None))).changed is True


@pytest.mark.asyncio
async def test_r2fd_gate_no_op_is_decided_before_the_gate() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D1))
    repo._technician_master = [tech(T1, status="INACTIVE")]
    calls_before = len(repo.calls)
    assert (await record(repo, transfer(T1, T1, D2))).changed is False
    # The history's own technician reference is proven (existence / scope only;
    # INACTIVE is valid history), but the NEW-assignment gate never runs: its
    # personnel read is absent and the inactive technician is not refused.
    assert "read_personnel_relationship_master" not in repo.calls[calls_before:]
    assert repo.calls[calls_before:].count("read_technician_master_reference") == 1


# ---------------------------------------------------------------------------
# R2FD-SCOPE — strict TEST / REAL scope (never inferred from an id)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fd_scope_equipment_resolution() -> None:
    real = repo_with(equipment=[equip("EQP-TEST-LOOKS-TEST")])  # a REAL row whatever its id looks like
    assert (await record(real, transfer(T1, None, D1), equipment="EQP-TEST-LOOKS-TEST")).changed
    test_only = repo_with(equipment=[equip(E1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    assert await code_of(record(test_only, transfer(T1, None, D1))) == "EQUIPMENT_NOT_FOUND"  # REAL never sees TEST
    # TEST: a REAL row is never proven in scope; another batch is not this batch.
    for rows in ([equip(E1)], [equip(E1, scope=REFERENCE_SCOPE_TEST, batch="OTHER-BATCH")]):
        repo = repo_with(equipment=rows)
        assert await code_of(record(repo, transfer(T1, None, D1), context="TEST")) == "EQUIPMENT_SCOPE_UNPROVEN"
    assert await code_of(record(repo_with(equipment=[]), transfer(T1, None, D1), context="TEST")) == (
        "EQUIPMENT_NOT_FOUND")
    dup = repo_with(equipment=[equip(E1), equip(E1)])
    assert await code_of(record(dup, transfer(T1, None, D1))) == "EQUIPMENT_ID_AMBIGUOUS"
    assert await code_of(record(repo_with(), transfer(T1, None, D1), equipment="")) == "EQUIPMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_r2fd_scope_technician_and_personnel_must_share_the_request_scope() -> None:
    eq = [equip(E1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)]
    real_tech = repo_with(equipment=eq, technicians=[tech(T1)],
                          people=[person("P-1", technician_id=T1, test=True, batch=BATCH)])
    assert await code_of(record(real_tech, transfer(T1, None, D1), context="TEST")) == "TECHNICIAN_SCOPE_UNPROVEN"
    real_person = repo_with(equipment=eq, technicians=[tech(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)],
                            people=[person("P-1", technician_id=T1)])
    assert await code_of(record(real_person, transfer(T1, None, D1), context="TEST")) == (
        "TECHNICIAN_PERSONNEL_UNRESOLVED")
    ok = repo_with(equipment=eq, technicians=[tech(T1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)],
                   people=[person("P-1", technician_id=T1, test=True, batch=BATCH), person("P-R", technician_id=T1)])
    assert (await record(ok, transfer(T1, None, D1), context="TEST")).changed  # the REAL holder is not counted
    (row,) = history(ok)
    assert (row["is_test_data"], row["test_batch_id"]) == ("TRUE", BATCH)


@pytest.mark.asyncio
async def test_r2fd_scope_history_rows_of_another_scope_are_invisible() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D1))  # a REAL event of E1
    test_side = repo_with(equipment=[equip(E1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)],
                          technicians=[tech(T2, scope=REFERENCE_SCOPE_TEST, batch=BATCH)],
                          people=[person("P-2", technician_id=T2, test=True, batch=BATCH)])
    test_side._equipment_caretaker_history = copy.deepcopy(history(repo))
    read = await caretakers(test_side, context="TEST")
    assert read.timeline.current_status == "NONE" and read.timeline.events == ()
    assert (await record(test_side, transfer(T2, None, D1), context="TEST")).changed  # no same-instant clash
    assert (await caretakers(repo)).timeline.current_technician_id == T1


@pytest.mark.asyncio
async def test_r2fd_scope_unknown_test_flag_fails_closed_and_no_context_is_503() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D1))
    history(repo)[0]["is_test_data"] = "true"
    assert await code_of(caretakers(repo)) == "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID"
    clean = repo_with()
    assert await code_of(svc(clean, None).record_event(E1, transfer(T1, None, D1), request_id="r",
                                                       user_id="u")) == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert await code_of(svc(clean, None).caretakers(E1)) == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert clean.calls == []


# ---------------------------------------------------------------------------
# R2FD-STALE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fd_stale_expected_current_is_checked_before_the_no_op() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D1))
    for payload in (transfer(T1, None, D2), transfer(T1, "", D2), transfer(T1, T2, D2), end(None, D2),
                    insertion(T2, None, "2025-12-01")):
        assert await code_of(record(repo, payload)) == "CARETAKER_HISTORY_STALE"
    assert len(history(repo)) == 1
    assert (await record(repo, transfer(T1, T1, D2))).changed is False  # the matching expectation -> no-op


@pytest.mark.asyncio
async def test_r2fd_stale_revision_guard_protects_corrections_and_cancellations() -> None:
    repo = repo_with()
    first, _ = await seed_three(repo)
    await record(repo, correction(first, "1", T2, D2, technician=T3))
    for payload in (correction(first, "1", T2, D1, technician=T3), cancellation(first, "1", T2),
                    correction(first, "3", T2, D1, technician=T3), cancellation(first, 2, T2)):
        with pytest.raises(ApiError) as exc:
            await record(repo, payload)
        assert (exc.value.code, exc.value.details) == ("CARETAKER_HISTORY_STALE", {"field": "revision_no"})
    assert (await record(repo, cancellation(first, "2", T2))).changed


# ---------------------------------------------------------------------------
# R2FD-REPLAY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fd_replay_same_request_returns_the_original_records_without_writing() -> None:
    repo = repo_with()
    payload = transfer(T1, None, D1)
    first = await record(repo, payload, request_id="req-1")
    again = await record(repo, payload, request_id="req-1")  # stale now, but replay wins
    assert again.replayed and again.record_ids == (first.record_id,)
    assert len(history(repo)) == 1 and repo.registry_write_log == ["W1"]


@pytest.mark.asyncio
async def test_r2fd_replay_reuse_with_another_body_or_equipment_is_refused() -> None:
    repo = repo_with()
    await record(repo, transfer(T1, None, D1), request_id="req-1")
    assert await code_of(record(repo, transfer(T2, None, D1), request_id="req-1")) == "REQUEST_ID_REUSED"
    assert await code_of(record(repo, transfer(T1, None, D1), equipment=E2, request_id="req-1")) == (
        "REQUEST_ID_REUSED")  # tab-wide
    assert len(history(repo)) == 1


@pytest.mark.asyncio
async def test_r2fd_replay_through_the_api() -> None:
    repo = test_repo()
    path = f"{API}/equipment/{E1}/caretaker-events"
    rid = str(uuid.uuid4())
    one = await http("POST", path, repo, json=transfer(T1, None, D1), request_id=rid)
    two = await http("POST", path, repo, json=transfer(T1, None, D1), request_id=rid)
    assert two.status_code == 200 and two.json() == {"request_id": rid, "replayed": True,
                                                     "record_ids": [one.json()["record_id"]]}
    three = await http("POST", path, repo, json=transfer(T2, T1, D2), request_id=rid)
    assert _code(three) == (409, "REQUEST_ID_REUSED")


# ---------------------------------------------------------------------------
# R2FD-W1 — history-only append; failure outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("fault", "outcome", "written"), [
    ("rejected", "rejected", 0), ("unknown_not_applied", "unknown", 0), ("unknown_applied", "unknown", 1),
])
async def test_r2fd_w1_failure_is_reported_never_retried(fault, outcome, written) -> None:
    repo = repo_with()
    repo.registry_write_faults["W1"] = fault
    with pytest.raises(ApiError) as exc:
        await record(repo, transfer(T1, None, D1), request_id="req-w1")
    assert exc.value.code == "CARETAKER_HISTORY_WRITE_FAILED"
    assert exc.value.details == {"history_write_outcome": outcome, "request_id": "req-w1"}
    assert repo.registry_write_log == ["W1"] and len(history(repo)) == written


@pytest.mark.asyncio
async def test_r2fd_w1_is_the_only_write_and_no_projection_exists() -> None:
    repo = repo_with()
    equipment_before = copy.deepcopy(repo._equipment)
    people_before = copy.deepcopy(repo._personnel_master)
    await seed_three(repo)
    await record(repo, end(T2, D4))
    assert repo.registry_write_log == ["W1", "W1", "W1"]
    assert set(repo.calls) <= CARETAKER_METHODS
    assert repo._equipment == equipment_before and repo._personnel_master == people_before


# ---------------------------------------------------------------------------
# R2FD-AMBIG — same-instant ties are never guessed
# ---------------------------------------------------------------------------


async def tied_repo():
    repo = repo_with()
    await record(repo, transfer(T1, None, D1))
    await record(repo, transfer(T2, T1, D2))
    clone = dict(history(repo)[1])
    clone.update(record_id="ECH-" + "a" * 32, event_id="ECH-" + "a" * 32, technician_id=T3,
                 request_id="seed-tie", request_fingerprint="0" * 64)
    history(repo).append(clone)  # a second event at D2: the order is undetermined
    return repo, history(repo)[1]["event_id"], clone["event_id"], history(repo)[0]["event_id"]


@pytest.mark.asyncio
async def test_r2fd_ambig_read_reports_undetermined_never_none() -> None:
    repo, _a, _b, _first = await tied_repo()
    read = await caretakers(repo)
    assert (read.timeline.status, read.timeline.current_status) == (STATUS_AMBIGUOUS, "UNDETERMINED")
    assert read.timeline.current_technician_id is None and read.current_technician_resolution == "UNDETERMINED"
    assert sum("SAME_INSTANT" in e.notes for e in read.timeline.events) == 2
    assert await code_of(svc(repo).technician_equipment(T1)) == "CARETAKER_TIMELINE_AMBIGUOUS"


@pytest.mark.asyncio
async def test_r2fd_ambig_writes_are_refused_except_correcting_a_tied_event() -> None:
    repo, tied_a, tied_b, first = await tied_repo()
    for payload in (transfer(T1, None, D4), end(None, D4), insertion(T1, None, "2026-01-15")):
        assert await code_of(record(repo, payload)) == "CARETAKER_TIMELINE_AMBIGUOUS"
    assert await code_of(record(repo, correction(first, "1", None, "2025-12-01", technician=T1))) == (
        "CARETAKER_TIMELINE_AMBIGUOUS")
    resolved = await record(repo, correction(tied_b, "1", None, D3, technician=T3))
    assert resolved.timeline_status_after == STATUS_VALID and resolved.current_technician_id == T3
    assert tied_a


@pytest.mark.asyncio
async def test_r2fd_ambig_cancelling_a_tied_event_resolves_it() -> None:
    repo, _tied_a, tied_b, _first = await tied_repo()
    outcome = await record(repo, cancellation(tied_b, "1", None))
    assert outcome.timeline_status_after == STATUS_VALID and outcome.current_technician_id == T2


# ---------------------------------------------------------------------------
# R2FD-INVALID — the revision-chain guard (pure)
# ---------------------------------------------------------------------------


async def valid_rows() -> list[dict[str, str]]:
    repo = repo_with()
    first, _ = await seed_three(repo)
    await record(repo, correction(first, "1", T2, D2, technician=T3))
    return copy.deepcopy(history(repo))


@pytest.mark.asyncio
async def test_r2fd_invalid_revision_chain_defects_fail_closed() -> None:
    rows = await valid_rows()
    assert derive_caretaker_timeline(rows).status == STATUS_VALID
    fork = [*rows, {**rows[2], "record_id": "ECH-fork", "request_id": "fork"}]
    gap = [*rows[:2], {**rows[2], "revision_no": "3"}]
    dangling = [*rows[:2], {**rows[2], "supersedes_record_id": "ECH-missing"}]
    nature = [*rows[:2], {**rows[2], "technician_id": ""}]
    cancel_first = [*rows[:2], {**rows[2], "record_kind": "CANCELLATION", "entry_operation": "CANCELLATION",
                                "technician_id": "", "effective_at": "", "effective_precision": "",
                                "effective_source": "", "recorded_from_technician_id": "",
                                "recorded_from_source": ""},
                    {**rows[2], "record_id": "ECH-after", "request_id": "after", "revision_no": "3",
                     "supersedes_record_id": rows[2]["record_id"]}]
    duplicate = [*rows, dict(rows[0])]
    expected = {"fork": "REVISION_FORK_OR_GAP", "gap": "REVISION_FORK_OR_GAP", "dangling": "DANGLING_REFERENCE",
                "nature": "CORRECTION_CHANGES_EVENT_NATURE", "cancel_first": "CANCELLATION_NOT_LAST",
                "duplicate": "RECORD_ID_DUPLICATE"}
    for name, broken in {"fork": fork, "gap": gap, "dangling": dangling, "nature": nature,
                         "cancel_first": cancel_first, "duplicate": duplicate}.items():
        timeline = derive_caretaker_timeline(broken)
        assert timeline.status == STATUS_INVALID, name
        assert expected[name] in timeline.issue_counts, (name, timeline.issue_counts)


@pytest.mark.asyncio
async def test_r2fd_invalid_row_matrix() -> None:
    rows = await valid_rows()
    assert validate_caretaker_row(rows[0]) == []
    cases = {
        "RECORD_KIND_INVALID": {"record_kind": "PROJECTION_RECONCILIATION"},
        "ENTRY_OPERATION_INVALID": {"entry_operation": "DRIVER"},
        "FIELD_MUST_BE_BLANK:related_request_id": {"related_request_id": "x"},
        "FINGERPRINT_INVALID": {"request_fingerprint": "nope"},
        "SCOPE_INCONSISTENT": {"test_batch_id": "B"},
        "TEST_FLAG_INVALID": {"is_test_data": "yes"},
        "ASSIGNMENT_IDENTITY_INVALID": {"event_id": "other"},
        "RECORDED_FROM_TECHNICIAN_INCONSISTENT": {"recorded_from_technician_id": "X"},
        "FIELD_MUST_BE_BLANK:technician_id": {"entry_operation": "END"},
        "EFFECTIVE_AT_INVALID": {"effective_at": "2026-01-01"},
    }
    for code, change in cases.items():
        assert code in validate_caretaker_row({**rows[0], **change}), code
    assert "END_WITHOUT_CARETAKER" in validate_caretaker_row(
        {**rows[0], "entry_operation": "END", "technician_id": ""})
    assert "REASON_REQUIRED" in validate_caretaker_row({**rows[0], "entry_operation": "INSERTION"})


@pytest.mark.asyncio
async def test_r2fd_invalid_history_is_a_500_on_reads_and_writes() -> None:
    repo = repo_with()
    await seed_three(repo)
    history(repo)[1]["revision_no"] = "2"
    assert await code_of(caretakers(repo)) == "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID"
    assert await code_of(record(repo, end(T2, D4))) == "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID"
    other = repo_with()
    await record(other, transfer(T1, None, D1), equipment=E2)
    history(other).append(dict(history(other)[0], equipment_id=E1))  # a record id duplicated tab-wide
    assert await code_of(record(other, transfer(T1, None, D1))) == "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID"
    assert len(history(other)) == 2


# ---------------------------------------------------------------------------
# R2FD-REF — references read only; legacy and other relationships untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fd_ref_only_the_caretaker_surface_is_called() -> None:
    repo = repo_with()
    link_before = (copy.deepcopy(repo._personnel_technician_link_history),
                   copy.deepcopy(repo._personnel_account_link_history))
    first, second = await seed_three(repo)
    await record(repo, insertion(T3, T2, D2))
    await record(repo, correction(first, "1", T2, "2025-12-15", technician=T1))
    await record(repo, cancellation(second, "1", T2))
    await caretakers(repo)
    await svc(repo).technician_equipment(T1)
    assert set(repo.calls) <= CARETAKER_METHODS
    assert (repo._personnel_technician_link_history, repo._personnel_account_link_history) == link_before


def test_r2fd_ref_repository_surface_and_no_projection_or_legacy_authority() -> None:
    names = {n for n, v in vars(Repository).items() if getattr(v, "__isabstractmethod__", False)}
    caretaker = {n for n in names if "caretaker" in n}
    assert caretaker == {"read_equipment_caretaker_history_validated", "append_equipment_caretaker_history"}
    assert {n for n in names if "equipment_reference" in n} == {"read_equipment_reference"}
    assert not {n for n in names if "responsibility" in n}
    from app.repositories.google_sheets import schemas

    assert not [h for h in schemas.EQUIPMENT_SHEET.required_headers if "caretaker" in h or "technician" in h]
    assert schemas.EQUIPMENT_REFERENCE_READ_SHEET.required_headers == ("equipment_id",)
    root = Path(__file__).resolve().parents[1] / "app"
    for module in ("domain/caretaker_timeline.py", "domain/equipment_caretaker.py",
                   "api/v1/equipment_caretaker_routes.py", "api/v1/equipment_caretaker_schemas.py"):
        source = (root / module).read_text()
        for legacy in ("PRIMARY_OPERATOR", "MAINTENANCE_SUPERVISOR", "PRIMARY_CUSTODIAN", "driver_id",
                       "inspector_user_id"):
            assert legacy not in source, (module, legacy)
        # Named in docstrings only (as "not used"); never a tab literal in code.
        assert '"asset_responsibility_history"' not in source and "'asset_responsibility_history'" not in source


def test_r2fd_ref_caretaker_history_is_not_a_core_schema() -> None:
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    core = {s.tab_name for s in GoogleSheetsRepository._CORE_SCHEMAS}
    assert schemas.EQUIPMENT_CARETAKER_HISTORY_SHEET.tab_name not in core
    assert schemas.EQUIPMENT_CARETAKER_HISTORY_SHEET.required_headers == EQUIPMENT_CARETAKER_HISTORY_COLUMNS


@pytest.mark.asyncio
async def test_r2fd_ref_no_delete_route_and_no_driver_route() -> None:
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    caretaker = {p: set(v) for p, v in paths.items() if "caretaker" in p or p.endswith("/equipment")
                 and "technicians" in p}
    assert caretaker == {f"{API}/equipment/{{equipment_id}}/caretakers": {"get"},
                         f"{API}/equipment/{{equipment_id}}/caretaker-events": {"post"},
                         f"{API}/technicians/{{technician_id}}/equipment": {"get"}}
    assert not [p for p in paths if "driver" in p and "caretaker" in p]


# ---------------------------------------------------------------------------
# R2FD-CHECKLIST — display only, never an inspection gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fd_checklist_read_surface_for_display() -> None:
    repo = test_repo()
    await http("POST", f"{API}/equipment/{E1}/caretaker-events", repo, json=transfer(T1, None, D1))
    response = await http("GET", f"{API}/equipment/{E1}/caretakers", repo, role="TECHNICIAN")
    body = response.json()
    assert body["current_technician_id"] == T1 and body["current_technician_resolution"] == "RESOLVED"
    assert body["current_technician"]["technician_id"] == T1 and body["current_technician"]["first_name"]
    assert body["timeline_status"] == "VALID" and body["current_status"] == "EVENT"
    (event,) = body["events"]
    assert event["entry_operation"] == "TRANSFER" and event["derived_end_at"] is None
    assert "user_id" not in str(body) and "personnel_id" not in body


@pytest.mark.asyncio
async def test_r2fd_checklist_inspection_is_not_gated_by_the_caretaker() -> None:
    from app.repositories.mock.repository import MockRepository

    repo = MockRepository()
    checklist = (await http("GET", f"{API}/checklists/active?asset_type=EQUIPMENT", repo, role="TECHNICIAN")).json()
    items = [{"item_id": i["item_id"], "result": "PASS"} for i in checklist["items"]]
    # No caretaker anywhere, and a caller who is no caretaker: the inspection is accepted as before.
    response = await http("POST", f"{API}/inspections", repo, role="TECHNICIAN",
                          json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001", "items": items})
    assert response.status_code == 200, response.text
    assert repo._equipment_caretaker_history == []
    root = Path(__file__).resolve().parents[1] / "app"
    for module in ("api/v1/inspections.py", "domain/inspection.py"):
        path = root / module
        if path.exists():
            assert "caretaker" not in path.read_text()


# ---------------------------------------------------------------------------
# R2FD-REFINT — Independent Review Fix R1: persisted-history same-scope
# reference integrity (existence / uniqueness / scope only; never lifecycle)
# ---------------------------------------------------------------------------


async def stored(events, *, test: bool = False, batch: str = BATCH) -> list[dict[str, str]]:
    """Valid caretaker rows written through the service in a permissive REAL
    fixture, then re-labelled as TEST rows of `batch` when `test`: the stored
    shape of real persisted history, whatever the masters now say."""
    src = repo_with(technicians=[tech(T1), tech(T2), tech(T3)], equipment=[equip(E1), equip(E2)])
    for equipment, payload in events:
        await record(src, payload, equipment=equipment)
    rows = copy.deepcopy(history(src))
    if test:
        for row in rows:
            row.update(is_test_data="TRUE", test_batch_id=batch)
    return rows


def with_history(repo: CareSpy, rows) -> CareSpy:
    repo._equipment_caretaker_history = copy.deepcopy(rows)
    return repo


def t_equip(eid: str = E1, batch: str = BATCH) -> ScopedReferenceRow:
    return equip(eid, scope=REFERENCE_SCOPE_TEST, batch=batch)


def t_tech(tid: str, batch: str = BATCH, status: str = "ACTIVE") -> ScopedReferenceRow:
    return tech(tid, scope=REFERENCE_SCOPE_TEST, batch=batch, status=status)


async def invalid_issues(coro) -> dict[str, int]:
    with pytest.raises(ApiError) as exc:
        await coro
    assert exc.value.code == "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID" and exc.value.status_code == 500
    assert set(exc.value.details) == {"tab", "issues"}
    return exc.value.details["issues"]


@pytest.mark.asyncio
async def test_r2fd_refint_01_test_history_to_real_only_technician_fails_the_direct_read() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))], test=True)
    repo = with_history(repo_with(equipment=[t_equip()], technicians=[tech(T1)], people=[]), rows)
    issues = await invalid_issues(caretakers(repo, context="TEST"))
    assert issues == {"TECHNICIAN_REFERENCE_SCOPE_UNPROVEN": 1}
    # Writes built on that history fail closed before W1 as well (END is not gated).
    assert await code_of(record(repo, end(T1, D2), context="TEST")) == "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID"
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2fd_refint_01_api_never_exposes_the_real_technician_as_current() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))], test=True, batch=MOCK_TEST_BATCH_ID)
    repo = with_history(CareSpy(people=[], technicians=[tech(T1)],
                                equipment=[equip(E1, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)]), rows)
    response = await http("GET", f"{API}/equipment/{E1}/caretakers", repo, role="TECHNICIAN")
    assert _code(response) == (500, "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID")
    assert response.json()["error"]["details"]["issues"] == {"TECHNICIAN_REFERENCE_SCOPE_UNPROVEN": 1}
    assert T1 not in response.text and "UNRESOLVED" not in response.text


@pytest.mark.asyncio
async def test_r2fd_refint_02_test_history_to_real_only_equipment_fails_the_reverse_read() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))], test=True)
    repo = with_history(repo_with(equipment=[equip(E1)], technicians=[t_tech(T1)]), rows)
    issues = await invalid_issues(svc(repo, "TEST").technician_equipment(T1))
    assert issues == {"EQUIPMENT_REFERENCE_SCOPE_UNPROVEN": 1}
    rows_mock = await stored([(E1, transfer(T1, None, D1))], test=True, batch=MOCK_TEST_BATCH_ID)
    api_repo = with_history(CareSpy(people=[], equipment=[equip(E1)],
                                    technicians=[tech(T1, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)]),
                            rows_mock)
    response = await http("GET", f"{API}/technicians/{T1}/equipment", api_repo, role="TECHNICIAN")
    assert _code(response) == (500, "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID")
    assert E1 not in response.text and "items" not in response.text


@pytest.mark.asyncio
async def test_r2fd_refint_03_real_history_to_test_only_technician_fails_closed() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))])
    repo = with_history(repo_with(technicians=[t_tech(T1)]), rows)
    assert await invalid_issues(caretakers(repo)) == {"TECHNICIAN_REFERENCE_SCOPE_UNPROVEN": 1}
    reverse = with_history(repo_with(technicians=[tech(T2), t_tech(T1)]), rows)
    assert await invalid_issues(svc(reverse).technician_equipment(T2)) == {"TECHNICIAN_REFERENCE_SCOPE_UNPROVEN": 1}


@pytest.mark.asyncio
async def test_r2fd_refint_04_real_history_to_test_only_equipment_fails_the_reverse_read() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))])
    repo = with_history(repo_with(equipment=[t_equip(E1), equip(E2)]), rows)
    assert await invalid_issues(svc(repo).technician_equipment(T1)) == {"EQUIPMENT_REFERENCE_SCOPE_UNPROVEN": 1}


@pytest.mark.asyncio
async def test_r2fd_refint_05_missing_technician_fails_closed() -> None:
    rows = await stored([(E1, transfer(T1, None, D1)), (E1, transfer(T2, T1, D2))])
    repo = with_history(repo_with(technicians=[tech(T2)]), rows)  # T1 (the earlier period) is gone
    assert await invalid_issues(caretakers(repo)) == {"TECHNICIAN_REFERENCE_MISSING": 1}
    assert await invalid_issues(svc(repo).technician_equipment(T2)) == {"TECHNICIAN_REFERENCE_MISSING": 1}
    assert await code_of(record(repo, end(T2, D3))) == "EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID"


@pytest.mark.asyncio
async def test_r2fd_refint_05_recorded_from_technician_is_a_stored_reference_too() -> None:
    rows = await stored([(E1, transfer(T1, None, D1)), (E1, transfer(T2, T1, D2))])
    rows = [rows[1]]  # T1 now appears ONLY as the recorded "from" caretaker
    repo = with_history(repo_with(technicians=[tech(T2)]), rows)
    assert await invalid_issues(caretakers(repo)) == {"TECHNICIAN_REFERENCE_MISSING": 1}


@pytest.mark.asyncio
async def test_r2fd_refint_06_duplicate_technician_in_scope_fails_closed() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))])
    repo = with_history(repo_with(technicians=[tech(T1), tech(T1)]), rows)
    assert await invalid_issues(caretakers(repo)) == {"TECHNICIAN_REFERENCE_AMBIGUOUS": 1}
    other = with_history(repo_with(technicians=[tech(T1), tech(T1), tech(T2)]), rows)
    assert await invalid_issues(svc(other).technician_equipment(T2)) == {"TECHNICIAN_REFERENCE_AMBIGUOUS": 1}


@pytest.mark.asyncio
async def test_r2fd_refint_07_missing_equipment_fails_the_reverse_read() -> None:
    rows = await stored([(E1, transfer(T1, None, D1)), (E2, transfer(T1, None, D1))])
    repo = with_history(repo_with(equipment=[equip(E2)]), rows)
    assert await invalid_issues(svc(repo).technician_equipment(T1)) == {"EQUIPMENT_REFERENCE_MISSING": 1}


@pytest.mark.asyncio
async def test_r2fd_refint_08_duplicate_equipment_in_scope_fails_the_reverse_read() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))])
    repo = with_history(repo_with(equipment=[equip(E1), equip(E1)]), rows)
    assert await invalid_issues(svc(repo).technician_equipment(T1)) == {"EQUIPMENT_REFERENCE_AMBIGUOUS": 1}
    # A duplicate OUT of scope does not make the REAL reference ambiguous.
    fine = with_history(repo_with(equipment=[equip(E1), t_equip(E1)]), rows)
    assert [i.equipment_id for i in (await svc(fine).technician_equipment(T1)).items] == [E1]


@pytest.mark.asyncio
async def test_r2fd_refint_09_historical_technician_now_inactive_is_still_readable() -> None:
    rows = await stored([(E1, transfer(T1, None, D1)), (E2, transfer(T2, None, D1))])
    repo = with_history(repo_with(technicians=[tech(T1, status="INACTIVE"), tech(T2, status="")]), rows)
    read = await caretakers(repo)
    assert read.timeline.current_technician_id == T1 and read.current_technician_resolution == "RESOLVED"
    assert read.current_technician.active_status == "INACTIVE"
    assert [i.equipment_id for i in (await svc(repo).technician_equipment(T1)).items] == [E1]
    # END, CANCELLATION and a time-only CORRECTION stay allowed.
    first = rows[0]["event_id"]
    assert (await record(repo, correction(first, "1", T1, "2025-12-15", technician=T1))).changed
    assert (await record(repo, end(T1, D2))).changed
    assert (await record(repo, cancellation(first, "2", None))).changed


@pytest.mark.asyncio
async def test_r2fd_refint_10_linked_personnel_inactive_never_gates_a_read() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))])
    inactive = [{**person("P-1", technician_id=T1), "active_status": "INACTIVE"}]
    for people in (inactive, []):  # inactive, or no linked personnel at all
        repo = with_history(repo_with(people=people), rows)
        assert (await caretakers(repo)).timeline.current_technician_id == T1
        assert [i.equipment_id for i in (await svc(repo).technician_equipment(T1)).items] == [E1]
        assert "read_personnel_relationship_master" not in repo.calls
        assert (await record(repo, end(T1, D2))).changed  # END is never gated


@pytest.mark.asyncio
async def test_r2fd_refint_reverse_requested_technician_is_scope_proven() -> None:
    rows = await stored([(E1, transfer(T1, None, D1))], test=True)
    repo = with_history(repo_with(equipment=[t_equip()], technicians=[tech(T1)]), rows)
    assert await code_of(svc(repo, "TEST").technician_equipment(T1)) == "TECHNICIAN_SCOPE_UNPROVEN"
    assert "read_equipment_caretaker_history_validated" not in repo.calls


@pytest.mark.asyncio
async def test_r2fd_refint_reads_are_bounded_once_per_master() -> None:
    rows = await stored([(E1, transfer(T1, None, D1)), (E2, transfer(T2, None, D1)), (E1, transfer(T3, T1, D2))])
    repo = with_history(repo_with(), rows)
    await caretakers(repo)
    assert repo.calls == ["read_equipment_reference", "read_equipment_caretaker_history_validated",
                          "read_technician_master_reference"]  # the located equipment is not re-read
    repo.calls.clear()
    await svc(repo).technician_equipment(T3)
    assert repo.calls == ["read_technician_master_reference", "read_equipment_caretaker_history_validated",
                          "read_equipment_reference"]


# ---------------------------------------------------------------------------
# R2FD-RESEND — an unknown W1 outcome, then the client's exact resend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2fd_resend_after_unknown_applied_replays_without_a_second_append() -> None:
    repo = test_repo()
    path, rid, payload = f"{API}/equipment/{E1}/caretaker-events", str(uuid.uuid4()), transfer(T1, None, D1)
    repo.registry_write_faults["W1"] = "unknown_applied"
    first = await http("POST", path, repo, json=payload, request_id=rid)
    assert _code(first) == (503, "CARETAKER_HISTORY_WRITE_FAILED")
    assert first.json()["error"]["details"] == {"history_write_outcome": "unknown", "request_id": rid}
    assert repo.registry_write_log == ["W1"] and len(history(repo)) == 1  # applied once, never retried
    repo.registry_write_faults["W1"] = None
    again = await http("POST", path, repo, json=payload, request_id=rid)
    assert again.status_code == 200
    assert again.json() == {"request_id": rid, "replayed": True, "record_ids": [history(repo)[0]["record_id"]]}
    assert repo.registry_write_log == ["W1"] and len(history(repo)) == 1  # no second append


@pytest.mark.asyncio
async def test_r2fd_resend_after_unknown_not_applied_executes_once() -> None:
    repo = test_repo()
    path, rid, payload = f"{API}/equipment/{E1}/caretaker-events", str(uuid.uuid4()), transfer(T1, None, D1)
    repo.registry_write_faults["W1"] = "unknown_not_applied"
    first = await http("POST", path, repo, json=payload, request_id=rid)
    assert _code(first) == (503, "CARETAKER_HISTORY_WRITE_FAILED")
    assert first.json()["error"]["details"]["history_write_outcome"] == "unknown"
    assert repo.registry_write_log == ["W1"] and history(repo) == []  # one attempt, nothing applied
    repo.registry_write_faults["W1"] = None
    again = await http("POST", path, repo, json=payload, request_id=rid)
    assert again.status_code == 200 and again.json()["changed"] is True  # no replay hit: normal execution
    assert repo.registry_write_log == ["W1", "W1"]
    (row,) = history(repo)
    assert row["request_id"] == rid and row["technician_id"] == T1
