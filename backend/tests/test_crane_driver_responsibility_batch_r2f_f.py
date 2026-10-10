"""R2 Batch R2f-f — Crane / Vehicle ↔ Driver responsibility periods, mock / service level.

The R2f-f implementation authorization. Every row is SYNTHETIC and labelled;
no live workbook value is used. TEST-scoped vehicles / drivers are explicit
synthetic fixtures (scope TEST + batch), never derived from an id. REAL-context
cases run against the service directly (mock mode is always the TEST context at
the API).

Batch-local ids: R2FF-AUTH, -DDM (DRIVER_DEPARTMENT_MANAGER), -TL (timeline),
-CARD, -GATE, -SCOPE, -REFINT, -STALE, -REPLAY, -WRITE, -AMBIG, -INVALID,
-LEGACY.
"""
from __future__ import annotations

import copy
import inspect
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain import authz
from app.domain.crane_driver_responsibility import CraneDriverResponsibilityService
from app.domain.crane_driver_timeline import (
    CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS,
    STATUS_AMBIGUOUS,
    STATUS_INVALID,
    STATUS_VALID,
    derive_responsibility_timeline,
    validate_responsibility_row,
)
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST, Repository, ScopedReferenceRow
from tests.test_relationship_read_batch_r2f_a import RelSpy
from tests.test_relationship_read_batch_r2f_a import person as base_person

API = "/api/v1"
BATCH = "SYN-R2FF-BATCH"
REASON = "บันทึกผู้ขับย้อนหลัง (ทดสอบ)"
V1, V2 = "VEH-SYN-1", "VEH-SYN-2"
D1, D2, D3 = "DRV-SYN-1", "DRV-SYN-2", "DRV-SYN-3"
DATE1, DATE2, DATE3, DATE4 = "2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"
RESPONSIBILITY_METHODS = {"read_vehicle_reference", "read_crane_driver_responsibility_history_validated",
                          "read_driver_responsibility_reference", "read_personnel_relationship_master",
                          "append_crane_driver_responsibility_history"}


def veh(vid: str, *, scope: str = REFERENCE_SCOPE_REAL, batch: str = "") -> ScopedReferenceRow:
    return ScopedReferenceRow(values={"vehicle_id": vid}, scope=scope, test_batch_id=batch)


def drv(did: str, *, status: str = "ACTIVE", scope: str = REFERENCE_SCOPE_REAL, batch: str = "") -> ScopedReferenceRow:
    return ScopedReferenceRow(values={"driver_id": did, "active_status": status}, scope=scope, test_batch_id=batch)


def person(pid: str, *, driver_id: str = "", status: str = "ACTIVE", test: bool = False,
           batch: str = "") -> dict[str, str]:
    row = base_person(pid, test=test, batch=batch)
    row.update(driver_id=driver_id, active_status=status)
    return row


class RespSpy(RelSpy):
    def __init__(self, people=None, drivers=None, vehicles=None, *, fail=None) -> None:
        super().__init__(people, fail=fail)
        self._driver_reference = list(drivers) if drivers is not None else []
        self._vehicle_reference = list(vehicles) if vehicles is not None else []


def repo_with(people=None, drivers=None, vehicles=None) -> RespSpy:
    return RespSpy(
        people=people if people is not None else [],  # by default no driver has a Personnel link
        drivers=drivers if drivers is not None else [drv(D1), drv(D2), drv(D3)],
        vehicles=vehicles if vehicles is not None else [veh(V1), veh(V2)],
    )


def test_repo() -> RespSpy:
    """TEST-scope fixtures of the mock server batch (the API is TEST in mock mode)."""
    return RespSpy(
        people=[],
        drivers=[drv(D1, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID),
                 drv(D2, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)],
        vehicles=[veh(V1, scope=REFERENCE_SCOPE_TEST, batch=MOCK_TEST_BATCH_ID)],
    )


def svc(repo, context: str | None = "REAL", batch: str = BATCH) -> CraneDriverResponsibilityService:
    return CraneDriverResponsibilityService(repo, context, batch)


def eff(date: str | None = None) -> dict:
    return {"mode": "DATE", "date": date} if date else {"mode": "NOW"}


def transfer(driver: str, expected: str | None, date: str | None = None, **extra) -> dict:
    return {"operation": "TRANSFER", "driver_id": driver, "effective": eff(date),
            "expected_current_driver_id": expected, **extra}


def insertion(driver: str, expected: str | None, date: str, reason: str = REASON) -> dict:
    return {"operation": "INSERTION", "driver_id": driver, "effective": eff(date),
            "expected_current_driver_id": expected, "reason_th": reason}


def end(expected: str | None, date: str | None = None, **extra) -> dict:
    return {"operation": "END", "effective": eff(date), "expected_current_driver_id": expected, **extra}


def correction(event_id: str, revision: str, expected: str | None, date: str, driver: str | None = None,
               reason: str = REASON) -> dict:
    out = {"operation": "CORRECTION", "event_id": event_id, "expected_revision_no": revision,
           "effective": eff(date), "expected_current_driver_id": expected, "reason_th": reason}
    if driver is not None:
        out["driver_id"] = driver
    return out


def cancellation(event_id: str, revision: str, expected: str | None, reason: str = REASON) -> dict:
    return {"operation": "CANCELLATION", "event_id": event_id, "expected_revision_no": revision,
            "expected_current_driver_id": expected, "reason_th": reason}


async def record(repo, payload: dict, *, vehicle: str = V1, context: str = "REAL", batch: str = BATCH,
                 request_id: str | None = None):
    return await svc(repo, context, batch).record_event(vehicle, payload, request_id=request_id or str(uuid.uuid4()),
                                                        user_id="dev-user")


async def code_of(coro) -> str:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value.code


async def responsible(repo, vehicle: str = V1, context: str = "REAL", batch: str = BATCH):
    return (await svc(repo, context, batch).responsible_drivers(vehicle)).timeline


def history(repo) -> list[dict[str, str]]:
    return repo._crane_driver_responsibility_history


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


async def seed_two(repo) -> list[str]:
    """D1 from DATE1, D2 from DATE3 (TRANSFERs); returns the two event ids."""
    first = await record(repo, transfer(D1, None, DATE1))
    second = await record(repo, transfer(D2, D1, DATE3))
    return [first.event_id, second.event_id]


EVENTS = f"{API}/vehicles/{V1}/responsible-driver-events"


# ---------------------------------------------------------------------------
# R2FF-AUTH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_r2ff_auth_write_roles(role) -> None:
    repo = test_repo()
    response = await http("POST", EVENTS, repo, role=role, json=transfer(D1, None, DATE1))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True and body["current_driver_id"] == D1 and body["current_status"] == "EVENT"
    (row,) = history(repo)
    assert (row["is_test_data"], row["test_batch_id"], row["recorded_by"]) == ("TRUE", MOCK_TEST_BATCH_ID, "dev-user")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER", "NO_SUCH_ROLE"])
async def test_r2ff_auth_other_roles_are_refused_with_zero_repository_calls(role) -> None:
    repo = test_repo()
    response = await http("POST", EVENTS, repo, role=role, json=transfer(D1, None, DATE1))
    assert response.status_code == 403
    assert repo.calls == [] and repo.registry_write_log == []


def test_r2ff_auth_capability_is_dedicated() -> None:
    cap = authz.CAN_ASSIGN_CRANE_DRIVER
    assert cap == "can_assign_crane_driver" and cap in authz.ALL_CAPABILITIES
    holders = {role for role, caps in authz.ROLE_CAPABILITIES.items() if cap in caps}
    assert holders == {"ADMIN", "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER"}
    for other in (authz.CAN_LINK_PERSONNEL_DRIVER, authz.CAN_ASSIGN_EQUIPMENT_CARETAKER,
                  authz.CAN_TRANSFER_VEHICLE_BRANCH, authz.CAN_MANAGE_PERSONNEL):
        assert other != cap


@pytest.mark.asyncio
async def test_r2ff_auth_request_id_and_strict_body_are_checked_before_any_read() -> None:
    repo = test_repo()
    assert _code(await http("POST", EVENTS, repo, json=transfer(D1, None, DATE1), request_id=None)) == (
        422, "REQUEST_ID_REQUIRED")
    server_set = ("record_id", "record_kind", "revision_no", "supersedes_record_id", "recorded_at", "recorded_by",
                  "request_id", "request_fingerprint", "recorded_from_driver_id", "recorded_from_source",
                  "is_test_data", "test_batch_id", "related_request_id")
    bad = [{**transfer(D1, None, DATE1), name: "x"} for name in server_set]
    bad += [
        {**end(D1, DATE1), "driver_id": D2},  # END takes no driver
        {**cancellation("E", "1", None), "effective": eff(DATE1)},  # CANCELLATION takes no time
        {**transfer(D1, None, DATE1), "event_id": "E"},  # TRANSFER takes no event
        {"operation": "MERGE", "driver_id": D1},
        {k: v for k, v in transfer(D1, None, DATE1).items() if k != "expected_current_driver_id"},
    ]
    for payload in bad:
        assert (await http("POST", EVENTS, repo, json=payload)).status_code == 422, payload
    assert repo.calls == [] and repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_r2ff_auth_reads_need_only_can_view(role) -> None:
    repo = test_repo()
    await http("POST", EVENTS, repo, json=transfer(D1, None, DATE1))
    assert (await http("GET", f"{API}/vehicles/{V1}/responsible-drivers", repo, role=role)).status_code == 200
    assert (await http("GET", f"{API}/drivers/{D1}/vehicles", repo, role=role)).status_code == 200


# ---------------------------------------------------------------------------
# R2FF-DDM — the provisional DRIVER_DEPARTMENT_MANAGER dev role
# ---------------------------------------------------------------------------


def test_r2ff_ddm_has_exactly_the_three_approved_capabilities() -> None:
    assert authz.ROLE_CAPABILITIES["DRIVER_DEPARTMENT_MANAGER"] == frozenset(
        {"can_view", "can_link_personnel_driver", "can_assign_crane_driver"})
    for forbidden in ("can_manage_pm", "can_manage_repair", "can_close_repair", "can_record_inspection",
                      "can_report_repair", "can_manage_personnel", "can_manage_department",
                      "can_link_personnel_technician", "can_link_personnel_account",
                      "can_assign_equipment_caretaker", "can_edit_vehicle_registration",
                      "can_transfer_vehicle_branch", "can_correct_branch_history", "can_transfer_equipment_branch"):
        assert forbidden not in authz.ROLE_CAPABILITIES["DRIVER_DEPARTMENT_MANAGER"], forbidden


@pytest.mark.asyncio
async def test_r2ff_ddm_may_link_drivers_but_nothing_else_in_r2f() -> None:
    from tests.test_personnel_driver_link_batch_r2f_e import DrvSpy, tdrv, tperson

    repo = DrvSpy(people=[tperson("P-T")], drivers=[tdrv("DRV-T1")])
    role = "DRIVER_DEPARTMENT_MANAGER"
    link = await http("POST", f"{API}/personnel/P-T/driver-links", repo, role=role,
                      json={"operation": "LINK", "expected_driver_id": "", "new_driver_id": "DRV-T1",
                            "reason_th": REASON})
    assert link.status_code == 200 and link.json()["changed"] is True
    refused = [
        ("POST", f"{API}/personnel/P-T/technician-links",
         {"operation": "LINK", "expected_technician_id": "", "new_technician_id": "T", "reason_th": REASON}),
        ("POST", f"{API}/personnel/P-T/account-links",
         {"operation": "LINK", "expected_user_id": "", "new_user_id": "U", "reason_th": REASON}),
        ("POST", f"{API}/equipment/EQP-0001/caretaker-events",
         {"operation": "END", "effective": {"mode": "NOW"}, "expected_current_technician_id": None}),
        ("POST", f"{API}/personnel/P-T/deactivations", {"expected_active_status": "ACTIVE", "reason_th": REASON}),
        ("POST", f"{API}/departments/D-1/deactivations", {"expected_is_active": "TRUE", "reason_th": REASON}),
    ]
    for method, path, payload in refused:
        repo.calls.clear()
        response = await http(method, path, repo, role=role, json=payload)
        assert response.status_code == 403, (path, response.status_code)  # capability refusal, never a 404
        assert repo.calls == [], path
    for cap in ("can_manage_pm", "can_manage_repair", "can_close_repair"):
        assert cap not in authz.capabilities_for_roles(("DRIVER_DEPARTMENT_MANAGER",))


# ---------------------------------------------------------------------------
# R2FF-TL — TRANSFER / INSERTION / END / CORRECTION / CANCELLATION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2ff_tl_no_history_is_none_even_with_vehicle_driver_rows() -> None:
    repo = repo_with()
    from app.domain.driver import VehicleDriverAssignment
    from datetime import datetime, timezone

    repo._vehicle_driver_assignments = {V1: [VehicleDriverAssignment(
        assignment_id="VDA-SYN-1", vehicle_id=V1, driver_id=D1, start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_primary=True, assignment_status="ACTIVE")]}
    tl = await responsible(repo)
    assert (tl.status, tl.current_status, tl.current_driver_id, tl.events) == (STATUS_VALID, "NONE", None, ())


@pytest.mark.asyncio
async def test_r2ff_tl_first_transfer_from_none() -> None:
    repo = repo_with()
    outcome = await record(repo, transfer(D1, None, DATE1))
    assert outcome.changed and outcome.current_driver_id == D1 and outcome.timeline_status_after == STATUS_VALID
    (row,) = history(repo)
    assert list(row) == list(CRANE_DRIVER_RESPONSIBILITY_HISTORY_COLUMNS) and len(row) == 21
    assert (row["record_kind"], row["entry_operation"], row["revision_no"]) == ("ASSIGNMENT", "TRANSFER", "1")
    assert row["event_id"] == row["record_id"] and row["record_id"].startswith("CDR-")
    assert (row["vehicle_id"], row["driver_id"]) == (V1, D1)
    assert (row["recorded_from_driver_id"], row["recorded_from_source"]) == ("", "NONE")
    assert (row["is_test_data"], row["test_batch_id"], row["related_request_id"]) == ("FALSE", "", "")
    assert row["effective_at"] == "2025-12-31T17:00:00+00:00" and row["effective_precision"] == "DATE"
    assert row["recorded_at"] != row["effective_at"] and row["recorded_by"] == "dev-user"


@pytest.mark.asyncio
async def test_r2ff_tl_transfer_closes_the_previous_period() -> None:
    repo = repo_with()
    first, second = await seed_two(repo)
    assert (history(repo)[1]["recorded_from_driver_id"], history(repo)[1]["recorded_from_source"]) == (D1, "EVENT")
    tl = await responsible(repo)
    assert tl.current_driver_id == D2 and tl.current_since == history(repo)[1]["effective_at"]
    periods = {e.event_id: e for e in tl.events}
    assert periods[first].derived_end_at == periods[second].effective_at and periods[second].derived_end_at is None
    assert await code_of(record(repo, transfer(D3, D2, DATE2))) == "DRIVER_RESPONSIBILITY_EVENT_NOT_LATEST"
    assert await code_of(record(repo, transfer(D3, D2, DATE3))) == "DRIVER_RESPONSIBILITY_EVENT_SAME_INSTANT"
    now = await record(repo, transfer(D3, D2))
    assert now.changed and history(repo)[-1]["effective_source"] == "SERVER_NOW"


@pytest.mark.asyncio
async def test_r2ff_tl_end_and_restart() -> None:
    repo = repo_with()
    await record(repo, transfer(D1, None, DATE1))
    outcome = await record(repo, end(D1, DATE2))
    assert (outcome.current_driver_id, outcome.current_status) == (None, "ENDED")
    row = history(repo)[-1]
    assert (row["entry_operation"], row["driver_id"], row["recorded_from_driver_id"]) == ("END", "", D1)
    assert (await record(repo, end(None, DATE3))).changed is False  # nothing to end
    assert (await record(repo, transfer(D2, None, DATE3))).current_driver_id == D2


@pytest.mark.asyncio
async def test_r2ff_tl_backdated_insertion() -> None:
    repo = repo_with()
    await seed_two(repo)
    assert await code_of(record(repo, {**insertion(D3, D2, DATE2), "reason_th": " "})) == "REASON_REQUIRED"
    assert await code_of(record(repo, insertion(D3, D2, DATE4))) == "DRIVER_RESPONSIBILITY_INSERTION_NOT_HISTORICAL"
    assert (await code_of(record(repo, {**insertion(D3, D2, DATE2), "effective": {"mode": "NOW"}}))).startswith(
        "EFFECTIVE")
    outcome = await record(repo, insertion(D3, D2, DATE2))
    assert outcome.changed and outcome.current_driver_id == D2
    assert history(repo)[-1]["recorded_from_driver_id"] == D1
    tl = await responsible(repo)
    assert [e.driver_id for e in tl.events if e.in_force] == [D1, D3, D2]
    assert (await record(repo, insertion(D1, D2, "2026-01-15"))).changed is False


@pytest.mark.asyncio
async def test_r2ff_tl_correction_is_an_immutable_new_revision() -> None:
    repo = repo_with()
    first, _ = await seed_two(repo)
    before = copy.deepcopy(history(repo))
    outcome = await record(repo, correction(first, "1", D2, DATE2, driver=D3))
    assert outcome.changed and history(repo)[:2] == before
    row = history(repo)[-1]
    assert (row["record_kind"], row["revision_no"], row["supersedes_record_id"], row["driver_id"]) == (
        "CORRECTION", "2", first, D3)
    await record(repo, correction(first, "2", D2, DATE1, driver=D3))
    assert history(repo)[-1]["revision_no"] == "3" and history(repo)[-1]["supersedes_record_id"] == row["record_id"]
    assert (await record(repo, correction(first, "3", D2, DATE1, driver=D3))).changed is False
    assert await code_of(record(repo, correction(first, "3", D2, DATE2))) == "DRIVER_RESPONSIBILITY_DRIVER_REQUIRED"
    await record(repo, end(D2, DATE4))
    end_event = history(repo)[-1]["event_id"]
    assert await code_of(record(repo, correction(end_event, "1", None, DATE4, driver=D1))) == (
        "DRIVER_RESPONSIBILITY_CORRECTION_CHANGES_EVENT_NATURE")
    assert await code_of(record(repo, correction(end_event, "1", None, "2025-12-01"))) == (
        "DRIVER_RESPONSIBILITY_END_WITHOUT_DRIVER")


@pytest.mark.asyncio
async def test_r2ff_tl_cancellation_is_terminal() -> None:
    repo = repo_with()
    first, second = await seed_two(repo)
    outcome = await record(repo, cancellation(second, "1", D2))
    assert outcome.current_driver_id == D1
    row = history(repo)[-1]
    assert (row["record_kind"], row["driver_id"], row["effective_at"], row["revision_no"]) == ("CANCELLATION", "", "", "2")
    tl = await responsible(repo)
    cancelled = next(e for e in tl.events if e.event_id == second)
    assert cancelled.in_force is False and cancelled.notes == ("CANCELLED",)
    assert await code_of(record(repo, cancellation(second, "2", D1))) == "DRIVER_RESPONSIBILITY_EVENT_CANCELLED"
    assert await code_of(record(repo, correction(second, "2", D1, DATE4, driver=D2))) == (
        "DRIVER_RESPONSIBILITY_EVENT_CANCELLED")
    assert await code_of(record(repo, correction("CDR-none", "1", D1, DATE4, driver=D2))) == (
        "DRIVER_RESPONSIBILITY_EVENT_NOT_FOUND")
    assert (await record(repo, cancellation(first, "1", D1))).current_status == "NONE"


# ---------------------------------------------------------------------------
# R2FF-CARD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2ff_card_one_driver_per_vehicle_many_vehicles_per_driver() -> None:
    repo = repo_with()
    await record(repo, transfer(D1, None, DATE1), vehicle=V1)
    await record(repo, transfer(D1, None, DATE2), vehicle=V2)
    assert [i.vehicle_id for i in (await svc(repo).driver_vehicles(D1)).items] == [V1, V2]
    await record(repo, transfer(D2, D1, DATE3), vehicle=V1)
    assert [i.vehicle_id for i in (await svc(repo).driver_vehicles(D1)).items] == [V2]
    (item,) = (await svc(repo).driver_vehicles(D2)).items
    assert (item.vehicle_id, item.event_id, item.since) == (V1, history(repo)[-1]["event_id"],
                                                            history(repo)[-1]["effective_at"])
    assert (await record(repo, transfer(D2, D2, DATE4), vehicle=V1)).changed is False
    open_periods = [e for e in (await responsible(repo)).events if e.in_force and e.derived_end_at is None]
    assert len(open_periods) == 1


@pytest.mark.asyncio
async def test_r2ff_card_reverse_read_requires_the_driver_in_scope() -> None:
    repo = repo_with()
    assert await code_of(svc(repo).driver_vehicles("DRV-NONE")) == "DRIVER_NOT_FOUND"
    assert await code_of(svc(repo).driver_vehicles("")) == "DRIVER_NOT_FOUND"
    assert await code_of(svc(repo_with(drivers=[drv(D1), drv(D1)])).driver_vehicles(D1)) == "DRIVER_ID_AMBIGUOUS"
    test_side = repo_with(drivers=[drv(D1)])
    assert await code_of(svc(test_side, "TEST").driver_vehicles(D1)) == "DRIVER_SCOPE_UNPROVEN"
    assert (await svc(repo).driver_vehicles(D3)).items == ()


# ---------------------------------------------------------------------------
# R2FF-GATE — Driver / Personnel eligibility for NEW assignments only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2ff_gate_active_driver_without_personnel_link_succeeds() -> None:
    repo = repo_with(people=[person("P-OTHER")])  # personnel exist, none linked to D1
    assert (await record(repo, transfer(D1, None, DATE1))).changed


@pytest.mark.asyncio
async def test_r2ff_gate_active_driver_with_active_linked_personnel_succeeds() -> None:
    repo = repo_with(people=[person("P-1", driver_id=D1)])
    assert (await record(repo, transfer(D1, None, DATE1))).changed


@pytest.mark.asyncio
@pytest.mark.parametrize(("drivers", "people", "code"), [
    ([drv(D1, status="INACTIVE")], [], "DRIVER_NOT_ACTIVE"),
    ([drv(D1, status="")], [], "DRIVER_NOT_ACTIVE"),
    ([drv(D1, status="active")], [], "DRIVER_NOT_ACTIVE"),
    ([drv(D1, status=" ACTIVE")], [], "DRIVER_NOT_ACTIVE"),
    ([drv(D1, status="พักงาน")], [], "DRIVER_NOT_ACTIVE"),
    ([drv(D2)], [], "DRIVER_NOT_FOUND"),
    ([drv(D1), drv(D1)], [], "DRIVER_ID_AMBIGUOUS"),
    ([drv(D1)], [person("P-1", driver_id=D1, status="INACTIVE")], "PERSONNEL_NOT_ACTIVE"),
    ([drv(D1)], [person("P-1", driver_id=D1, status="")], "PERSONNEL_NOT_ACTIVE"),
    ([drv(D1)], [person("P-1", driver_id=D1), person("P-2", driver_id=D1)], "DRIVER_PERSONNEL_AMBIGUOUS"),
])
async def test_r2ff_gate_new_assignment_is_refused(drivers, people, code) -> None:
    repo = repo_with(drivers=drivers, people=people)
    assert await code_of(record(repo, transfer(D1, None, DATE1))) == code
    assert history(repo) == [] and repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2ff_gate_history_survives_later_inactivation_and_old_events_stay_editable() -> None:
    repo = repo_with(people=[person("P-1", driver_id=D1), person("P-3", driver_id=D3)])
    first, _ = await seed_two(repo)
    repo._driver_reference = [drv(D1, status="INACTIVE"), drv(D2, status="INACTIVE"), drv(D3, status="INACTIVE")]
    for row in repo._personnel_master:
        row["active_status"] = "INACTIVE"
    tl = await responsible(repo)  # readable: no lifecycle check on history
    assert tl.status == STATUS_VALID and tl.current_driver_id == D2
    assert [i.vehicle_id for i in (await svc(repo).driver_vehicles(D2)).items] == [V1]
    assert (await record(repo, correction(first, "1", D2, DATE2, driver=D1))).changed  # unchanged assignee, new time
    assert await code_of(record(repo, correction(first, "2", D2, DATE2, driver=D3))) == "DRIVER_NOT_ACTIVE"
    assert await code_of(record(repo, insertion(D3, D2, "2026-02-15"))) == "DRIVER_NOT_ACTIVE"
    assert (await record(repo, end(D2, DATE4))).changed
    assert (await record(repo, cancellation(first, "2", None))).changed


@pytest.mark.asyncio
async def test_r2ff_gate_correction_to_a_new_driver_uses_the_gate() -> None:
    repo = repo_with(people=[person("P-3", driver_id=D3, status="INACTIVE")])
    first, _ = await seed_two(repo)
    assert await code_of(record(repo, correction(first, "1", D2, DATE1, driver=D3))) == "PERSONNEL_NOT_ACTIVE"
    calls_before = len(repo.calls)
    assert (await record(repo, correction(first, "1", D2, DATE2, driver=D1))).changed  # same driver: no gate
    assert "read_personnel_relationship_master" not in repo.calls[calls_before:]


@pytest.mark.asyncio
async def test_r2ff_gate_runs_after_the_no_op_and_never_mutates_anything() -> None:
    repo = repo_with(people=[person("P-1", driver_id=D1)])
    await record(repo, transfer(D1, None, DATE1))
    repo._driver_reference = [drv(D1, status="INACTIVE"), drv(D2)]
    calls_before = len(repo.calls)
    assert (await record(repo, transfer(D1, D1, DATE2))).changed is False
    assert "read_personnel_relationship_master" not in repo.calls[calls_before:]
    snapshot = (copy.deepcopy(repo._personnel_master), list(repo._driver_reference),
                copy.deepcopy(repo._personnel_driver_link_history))
    await record(repo, transfer(D2, D1, DATE3))
    assert (repo._personnel_master, repo._driver_reference, repo._personnel_driver_link_history) == snapshot


# ---------------------------------------------------------------------------
# R2FF-SCOPE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2ff_scope_vehicle_and_driver_proof() -> None:
    t_veh, t_drv = veh(V1, scope=REFERENCE_SCOPE_TEST, batch=BATCH), drv(D1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)
    ok = repo_with(vehicles=[t_veh], drivers=[t_drv])
    assert (await record(ok, transfer(D1, None, DATE1), context="TEST")).changed
    assert (history(ok)[0]["is_test_data"], history(ok)[0]["test_batch_id"]) == ("TRUE", BATCH)
    cases = [
        ("TEST", [veh(V1)], [t_drv], "VEHICLE_SCOPE_UNPROVEN"),  # TEST -> REAL vehicle
        ("TEST", [t_veh], [drv(D1)], "DRIVER_SCOPE_UNPROVEN"),  # TEST -> REAL driver
        # One classifier everywhere: an id existing only out of scope is SCOPE_UNPROVEN in both directions.
        ("REAL", [t_veh], [drv(D1)], "VEHICLE_SCOPE_UNPROVEN"),  # REAL -> TEST vehicle
        ("REAL", [veh(V1)], [t_drv], "DRIVER_SCOPE_UNPROVEN"),  # REAL -> TEST driver
        ("TEST", [veh(V1, scope=REFERENCE_SCOPE_TEST, batch="OTHER")], [t_drv], "VEHICLE_SCOPE_UNPROVEN"),
        ("TEST", [t_veh], [drv(D1, scope=REFERENCE_SCOPE_TEST, batch="OTHER")], "DRIVER_SCOPE_UNPROVEN"),
        ("REAL", [veh(V1), veh(V1)], [drv(D1)], "VEHICLE_ID_AMBIGUOUS"),
        ("REAL", [], [drv(D1)], "VEHICLE_NOT_FOUND"),
    ]
    for context, vehicles, drivers, code in cases:
        repo = repo_with(vehicles=vehicles, drivers=drivers)
        assert await code_of(record(repo, transfer(D1, None, DATE1), context=context)) == code, (context, code)
        assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2ff_scope_id_prefix_never_proves_test_scope() -> None:
    repo = repo_with(vehicles=[veh("VEH-TEST-LOOKS")], drivers=[drv("DRV-TEST-LOOKS")])
    assert (await record(repo, transfer("DRV-TEST-LOOKS", None, DATE1), vehicle="VEH-TEST-LOOKS")).changed  # REAL
    test = repo_with(vehicles=[veh("VEH-TEST-LOOKS")], drivers=[drv("DRV-TEST-LOOKS")])
    assert await code_of(record(test, transfer("DRV-TEST-LOOKS", None, DATE1), vehicle="VEH-TEST-LOOKS",
                                context="TEST")) == "VEHICLE_SCOPE_UNPROVEN"


@pytest.mark.asyncio
async def test_r2ff_scope_personnel_of_another_scope_never_counts() -> None:
    people = [person("P-T", driver_id=D1, status="INACTIVE", test=True, batch=BATCH)]  # TEST holder, inactive
    repo = repo_with(people=people)
    assert (await record(repo, transfer(D1, None, DATE1))).changed  # REAL: the TEST holder is out of scope


@pytest.mark.asyncio
async def test_r2ff_scope_history_of_another_scope_is_invisible_and_bad_flags_fail_closed() -> None:
    repo = repo_with()
    await record(repo, transfer(D1, None, DATE1))
    other = repo_with(vehicles=[veh(V1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)],
                      drivers=[drv(D2, scope=REFERENCE_SCOPE_TEST, batch=BATCH)])
    other._crane_driver_responsibility_history = copy.deepcopy(history(repo))
    assert (await responsible(other, context="TEST")).current_status == "NONE"
    assert (await record(other, transfer(D2, None, DATE1), context="TEST")).changed
    history(repo)[0]["is_test_data"] = "yes"
    assert await code_of(responsible(repo)) == "CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID"
    clean = repo_with()
    assert await code_of(svc(clean, None).record_event(V1, transfer(D1, None, DATE1), request_id="r",
                                                       user_id="u")) == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert clean.calls == []


# ---------------------------------------------------------------------------
# R2FF-REFINT — persisted-history same-scope reference proof (from the start)
# ---------------------------------------------------------------------------


async def stored(events, *, test: bool = False, batch: str = BATCH) -> list[dict[str, str]]:
    src = repo_with()
    for vehicle, payload in events:
        await record(src, payload, vehicle=vehicle)
    rows = copy.deepcopy(history(src))
    if test:
        for row in rows:
            row.update(is_test_data="TRUE", test_batch_id=batch)
    return rows


def with_history(repo, rows):
    repo._crane_driver_responsibility_history = copy.deepcopy(rows)
    return repo


async def invalid_issues(coro) -> dict[str, int]:
    with pytest.raises(ApiError) as exc:
        await coro
    assert exc.value.code == "CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID" and exc.value.status_code == 500
    assert set(exc.value.details) == {"tab", "issues"}
    return exc.value.details["issues"]


T_VEH = veh(V1, scope=REFERENCE_SCOPE_TEST, batch=BATCH)


def t_drv(did: str, status: str = "ACTIVE") -> ScopedReferenceRow:
    return drv(did, status=status, scope=REFERENCE_SCOPE_TEST, batch=BATCH)


@pytest.mark.asyncio
async def test_r2ff_refint_test_history_to_real_only_driver() -> None:
    rows = await stored([(V1, transfer(D1, None, DATE1))], test=True)
    repo = with_history(repo_with(vehicles=[T_VEH], drivers=[drv(D1)]), rows)
    assert await invalid_issues(svc(repo, "TEST").responsible_drivers(V1)) == {"DRIVER_REFERENCE_SCOPE_UNPROVEN": 1}
    assert await code_of(record(repo, end(D1, DATE2), context="TEST")) == (
        "CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID")
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_r2ff_refint_test_history_to_real_only_vehicle_reverse() -> None:
    rows = await stored([(V1, transfer(D1, None, DATE1))], test=True)
    repo = with_history(repo_with(vehicles=[veh(V1)], drivers=[t_drv(D1)]), rows)
    assert await invalid_issues(svc(repo, "TEST").driver_vehicles(D1)) == {"VEHICLE_REFERENCE_SCOPE_UNPROVEN": 1}


@pytest.mark.asyncio
async def test_r2ff_refint_real_history_to_test_only_references() -> None:
    rows = await stored([(V1, transfer(D1, None, DATE1))])
    repo = with_history(repo_with(drivers=[t_drv(D1), drv(D2)]), rows)
    assert await invalid_issues(svc(repo).responsible_drivers(V1)) == {"DRIVER_REFERENCE_SCOPE_UNPROVEN": 1}
    repo = with_history(repo_with(vehicles=[T_VEH, veh(V2)]), rows)
    assert await invalid_issues(svc(repo).driver_vehicles(D1)) == {"VEHICLE_REFERENCE_SCOPE_UNPROVEN": 1}


@pytest.mark.asyncio
async def test_r2ff_refint_missing_and_duplicate_references() -> None:
    rows = await stored([(V1, transfer(D1, None, DATE1)), (V1, transfer(D2, D1, DATE2)), (V2, transfer(D2, None, DATE1))])
    missing_driver = with_history(repo_with(drivers=[drv(D2)]), rows)  # D1 only as recorded-from + old period
    assert await invalid_issues(svc(missing_driver).responsible_drivers(V1)) == {"DRIVER_REFERENCE_MISSING": 1}
    dup_driver = with_history(repo_with(drivers=[drv(D1), drv(D2), drv(D2)]), rows)
    assert await invalid_issues(svc(dup_driver).responsible_drivers(V1)) == {"DRIVER_REFERENCE_AMBIGUOUS": 1}
    missing_vehicle = with_history(repo_with(vehicles=[veh(V1)]), rows)
    assert await invalid_issues(svc(missing_vehicle).driver_vehicles(D2)) == {"VEHICLE_REFERENCE_MISSING": 1}
    dup_vehicle = with_history(repo_with(vehicles=[veh(V1), veh(V2), veh(V2)]), rows)
    assert await invalid_issues(svc(dup_vehicle).driver_vehicles(D2)) == {"VEHICLE_REFERENCE_AMBIGUOUS": 1}


@pytest.mark.asyncio
async def test_r2ff_refint_historical_inactive_driver_is_still_readable() -> None:
    rows = await stored([(V1, transfer(D1, None, DATE1))])
    repo = with_history(repo_with(drivers=[drv(D1, status="INACTIVE")], people=[person("P", driver_id=D1,
                                                                                         status="INACTIVE")]), rows)
    assert (await responsible(repo)).current_driver_id == D1
    assert [i.vehicle_id for i in (await svc(repo).driver_vehicles(D1)).items] == [V1]


@pytest.mark.asyncio
async def test_r2ff_refint_reads_are_bounded_once_per_master() -> None:
    rows = await stored([(V1, transfer(D1, None, DATE1)), (V2, transfer(D2, None, DATE1)), (V1, transfer(D3, D1, DATE2))])
    repo = with_history(repo_with(), rows)
    await svc(repo).responsible_drivers(V1)
    assert repo.calls == ["read_vehicle_reference", "read_crane_driver_responsibility_history_validated",
                          "read_driver_responsibility_reference"]
    repo.calls.clear()
    await svc(repo).driver_vehicles(D3)
    assert repo.calls == ["read_driver_responsibility_reference", "read_crane_driver_responsibility_history_validated",
                          "read_vehicle_reference"]


# ---------------------------------------------------------------------------
# R2FF-STALE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2ff_stale_before_no_op_with_zero_writes() -> None:
    repo = repo_with()
    await record(repo, transfer(D1, None, DATE1))
    for payload in (transfer(D1, None, DATE2), transfer(D1, "", DATE2), transfer(D1, D2, DATE2), end(None, DATE2),
                    insertion(D2, None, "2025-12-01")):
        with pytest.raises(ApiError) as exc:
            await record(repo, payload)
        assert (exc.value.code, exc.value.details) == ("DRIVER_RESPONSIBILITY_HISTORY_STALE",
                                                       {"field": "current_driver_id"})
    assert len(history(repo)) == 1 and repo.registry_write_log == ["W1"]
    assert (await record(repo, transfer(D1, D1, DATE2))).changed is False


@pytest.mark.asyncio
async def test_r2ff_stale_revision_guard() -> None:
    repo = repo_with()
    first, _ = await seed_two(repo)
    await record(repo, correction(first, "1", D2, DATE2, driver=D3))
    for payload in (correction(first, "1", D2, DATE1, driver=D3), cancellation(first, "1", D2),
                    correction(first, "3", D2, DATE1, driver=D3), cancellation(first, 2, D2)):
        with pytest.raises(ApiError) as exc:
            await record(repo, payload)
        assert (exc.value.code, exc.value.details) == ("DRIVER_RESPONSIBILITY_HISTORY_STALE", {"field": "revision_no"})
    assert (await record(repo, cancellation(first, "2", D2))).changed


# ---------------------------------------------------------------------------
# R2FF-REPLAY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2ff_replay_exact_and_reused() -> None:
    repo = repo_with()
    first = await record(repo, transfer(D1, None, DATE1), request_id="req-1")
    again = await record(repo, transfer(D1, None, DATE1), request_id="req-1")
    assert again.replayed and again.record_ids == (first.record_id,) and repo.registry_write_log == ["W1"]
    assert await code_of(record(repo, transfer(D2, None, DATE1), request_id="req-1")) == "REQUEST_ID_REUSED"
    assert await code_of(record(repo, transfer(D1, None, DATE1), vehicle=V2, request_id="req-1")) == (
        "REQUEST_ID_REUSED")  # tab-wide
    assert len(history(repo)) == 1


@pytest.mark.asyncio
async def test_r2ff_replay_unknown_applied_resend_replays_without_a_second_append() -> None:
    repo = test_repo()
    rid, payload = str(uuid.uuid4()), transfer(D1, None, DATE1)
    repo.registry_write_faults["W1"] = "unknown_applied"
    first = await http("POST", EVENTS, repo, json=payload, request_id=rid)
    assert _code(first) == (503, "DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED")
    assert first.json()["error"]["details"] == {"history_write_outcome": "unknown", "request_id": rid}
    assert repo.registry_write_log == ["W1"] and len(history(repo)) == 1
    repo.registry_write_faults["W1"] = None
    again = await http("POST", EVENTS, repo, json=payload, request_id=rid)
    assert again.json() == {"request_id": rid, "replayed": True, "record_ids": [history(repo)[0]["record_id"]]}
    assert repo.registry_write_log == ["W1"] and len(history(repo)) == 1


@pytest.mark.asyncio
async def test_r2ff_replay_unknown_not_applied_resend_executes_once() -> None:
    repo = test_repo()
    rid, payload = str(uuid.uuid4()), transfer(D1, None, DATE1)
    repo.registry_write_faults["W1"] = "unknown_not_applied"
    first = await http("POST", EVENTS, repo, json=payload, request_id=rid)
    assert _code(first) == (503, "DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED")
    assert repo.registry_write_log == ["W1"] and history(repo) == []
    repo.registry_write_faults["W1"] = None
    again = await http("POST", EVENTS, repo, json=payload, request_id=rid)
    assert again.status_code == 200 and again.json()["changed"] is True
    assert repo.registry_write_log == ["W1", "W1"] and len(history(repo)) == 1


# ---------------------------------------------------------------------------
# R2FF-WRITE — exactly one append, nothing else
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("fault", "outcome", "written"), [
    ("rejected", "rejected", 0), ("unknown_not_applied", "unknown", 0), ("unknown_applied", "unknown", 1)])
async def test_r2ff_write_failure_is_reported_never_retried(fault, outcome, written) -> None:
    repo = repo_with()
    repo.registry_write_faults["W1"] = fault
    with pytest.raises(ApiError) as exc:
        await record(repo, transfer(D1, None, DATE1), request_id="req-w")
    assert (exc.value.code, exc.value.details) == ("DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED",
                                                   {"history_write_outcome": outcome, "request_id": "req-w"})
    assert repo.registry_write_log == ["W1"] and len(history(repo)) == written


@pytest.mark.asyncio
async def test_r2ff_write_history_only_nothing_else_changes() -> None:
    repo = repo_with(people=[person("P-1", driver_id=D1)])
    frozen = {name: copy.deepcopy(getattr(repo, name)) for name in (
        "_vehicles", "_vehicle_registry", "_drivers", "_vehicle_driver_assignments", "_personnel_master",
        "_personnel_driver_link_history", "_personnel_technician_link_history", "_personnel_account_link_history",
        "_equipment_caretaker_history", "_asset_branch_history", "_driver_reference", "_vehicle_reference")}
    first, _ = await seed_two(repo)
    await record(repo, insertion(D3, D2, DATE2))
    await record(repo, correction(first, "1", D2, "2025-12-15", driver=D1))
    await record(repo, end(D2, DATE4))
    assert repo.registry_write_log == ["W1"] * 5 and len(history(repo)) == 5
    for name, before in frozen.items():
        assert getattr(repo, name) == before, name
    assert set(repo.calls) <= RESPONSIBILITY_METHODS


# ---------------------------------------------------------------------------
# R2FF-AMBIG / -INVALID
# ---------------------------------------------------------------------------


async def tied_repo():
    repo = repo_with()
    await record(repo, transfer(D1, None, DATE1))
    await record(repo, transfer(D2, D1, DATE2))
    clone = dict(history(repo)[1])
    clone.update(record_id="CDR-" + "a" * 32, event_id="CDR-" + "a" * 32, driver_id=D3, request_id="seed-tie",
                 request_fingerprint="0" * 64)
    history(repo).append(clone)
    return repo, clone["event_id"], history(repo)[0]["event_id"]


@pytest.mark.asyncio
async def test_r2ff_ambig_same_instant_is_undetermined_never_none() -> None:
    repo, tied, first = await tied_repo()
    tl = await responsible(repo)
    assert (tl.status, tl.current_status, tl.current_driver_id) == (STATUS_AMBIGUOUS, "UNDETERMINED", None)
    assert await code_of(svc(repo).driver_vehicles(D1)) == "DRIVER_RESPONSIBILITY_TIMELINE_AMBIGUOUS"
    for payload in (transfer(D1, None, DATE4), end(None, DATE4), insertion(D1, None, "2026-01-15")):
        assert await code_of(record(repo, payload)) == "DRIVER_RESPONSIBILITY_TIMELINE_AMBIGUOUS"
    assert await code_of(record(repo, correction(first, "1", None, "2025-12-01", driver=D1))) == (
        "DRIVER_RESPONSIBILITY_TIMELINE_AMBIGUOUS")
    resolved = await record(repo, cancellation(tied, "1", None))
    assert resolved.timeline_status_after == STATUS_VALID and resolved.current_driver_id == D2
    response = await http("GET", f"{API}/vehicles/{V1}/responsible-drivers", test_repo(), role="TECHNICIAN")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_r2ff_invalid_structural_defects_fail_closed() -> None:
    repo = repo_with()
    first, _ = await seed_two(repo)
    await record(repo, correction(first, "1", D2, DATE2, driver=D3))
    rows = copy.deepcopy(history(repo))
    assert derive_responsibility_timeline(rows).status == STATUS_VALID
    cases = {
        "REVISION_FORK_OR_GAP": [*rows, {**rows[2], "record_id": "CDR-fork", "request_id": "fork"}],
        "DANGLING_REFERENCE": [*rows[:2], {**rows[2], "supersedes_record_id": "CDR-missing"}],
        "CORRECTION_CHANGES_EVENT_NATURE": [*rows[:2], {**rows[2], "driver_id": ""}],
        "RECORD_ID_DUPLICATE": [*rows, dict(rows[0])],
        "REQUEST_ID_DUPLICATE": [*rows[:2], {**rows[2], "request_id": rows[0]["request_id"]}],
        "CANCELLATION_NOT_LAST": [*rows[:2], {**rows[2], "record_kind": "CANCELLATION", "entry_operation": "CANCELLATION",
                                              "driver_id": "", "effective_at": "", "effective_precision": "",
                                              "effective_source": "", "recorded_from_driver_id": "",
                                              "recorded_from_source": ""},
                                  {**rows[2], "record_id": "CDR-after", "request_id": "after", "revision_no": "3",
                                   "supersedes_record_id": rows[2]["record_id"]}],
    }
    for code, broken in cases.items():
        timeline = derive_responsibility_timeline(broken)
        assert timeline.status == STATUS_INVALID and code in timeline.issue_counts, (code, timeline.issue_counts)
    row = rows[0]
    for code, change in {"RECORD_KIND_INVALID": {"record_kind": "PROJECTION"},
                         "ENTRY_OPERATION_INVALID": {"entry_operation": "ASSIGN"},
                         "EFFECTIVE_AT_INVALID": {"effective_at": "2026-01-01"},
                         "EFFECTIVE_PRECISION_INVALID": {"effective_precision": "MONTH"},
                         "REVISION_INVALID": {"revision_no": "2"},
                         "RECORDED_AT_INVALID": {"recorded_at": "yesterday"},
                         "FINGERPRINT_INVALID": {"request_fingerprint": "x"},
                         "SCOPE_INCONSISTENT": {"test_batch_id": "B"},
                         "FIELD_MUST_BE_BLANK:related_request_id": {"related_request_id": "r"}}.items():
        assert code in validate_responsibility_row({**row, **change}), code
    history(repo)[1]["revision_no"] = "2"
    assert await code_of(responsible(repo)) == "CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID"
    assert await code_of(record(repo, end(D2, DATE4))) == "CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID"


# ---------------------------------------------------------------------------
# R2FF-API / -LEGACY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2ff_api_vehicle_read_shape_has_no_driver_pii() -> None:
    repo = test_repo()
    await http("POST", EVENTS, repo, json=transfer(D1, None, DATE1))
    body = (await http("GET", f"{API}/vehicles/{V1}/responsible-drivers", repo, role="TECHNICIAN")).json()
    assert set(body) == {"vehicle_id", "timeline_status", "current_status", "current_driver_id", "current_since",
                         "events"}
    (event,) = body["events"]
    assert set(event) == {"event_id", "in_force", "entry_operation", "revision_no", "head_record_id", "driver_id",
                          "effective_at", "effective_precision", "derived_end_at", "recorded_at", "recorded_by",
                          "notes"}
    for leaked in ("phone", "license", "licence", "expiry", "driver_name"):
        assert leaked not in str(body)
    reverse = (await http("GET", f"{API}/drivers/{D1}/vehicles", repo, role="TECHNICIAN")).json()
    assert reverse == {"driver_id": D1, "items": [{"vehicle_id": V1, "since": body["current_since"],
                                                   "event_id": event["event_id"]}]}


def test_r2ff_api_routes_are_exactly_the_frozen_three_and_no_delete() -> None:
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    found = {(m.upper(), p) for p, ops in paths.items() for m in ops if "responsible" in p
             or p == f"{API}/drivers/{{driver_id}}/vehicles"}
    assert found == {("GET", f"{API}/vehicles/{{vehicle_id}}/responsible-drivers"),
                     ("POST", f"{API}/vehicles/{{vehicle_id}}/responsible-driver-events"),
                     ("GET", f"{API}/drivers/{{driver_id}}/vehicles")}
    assert not [p for p in paths if "reconcile" in p and "responsib" in p]


def test_r2ff_legacy_vehicle_driver_and_driver_master_are_never_used() -> None:
    from app.api.v1 import crane_driver_responsibility_routes, crane_driver_responsibility_schemas
    from app.domain import crane_driver_responsibility, crane_driver_timeline
    from app.repositories.google_sheets import schemas
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    for module in (crane_driver_responsibility, crane_driver_timeline, crane_driver_responsibility_routes,
                   crane_driver_responsibility_schemas):
        code = "\n".join(line for line in inspect.getsource(module).splitlines()
                         if not line.lstrip().startswith("#"))
        code = code.split('"""', 2)[-1]  # skip the module docstring
        for forbidden in ("vehicle_driver", "VehicleDriverAssignment", "is_primary", "assignment_status",
                          "create_driver", "update_driver", "get_driver(", "list_drivers", "DriverService",
                          "write_personnel_link_cell", "append_personnel_link_history", "asset_responsibility",
                          "license", "phone"):
            assert forbidden not in code, (module.__name__, forbidden)
    assert schemas.VEHICLE_REFERENCE_READ_SHEET.required_headers == ("vehicle_id",)
    assert schemas.DRIVER_RESPONSIBILITY_REFERENCE_READ_SHEET.required_headers == ("driver_id", "active_status")
    core = {s.tab_name for s in GoogleSheetsRepository._CORE_SCHEMAS}
    assert "crane_driver_responsibility_history" not in core
    source = inspect.getsource(GoogleSheetsRepository)
    for schema in ("VEHICLE_REFERENCE_READ_SHEET", "DRIVER_RESPONSIBILITY_REFERENCE_READ_SHEET"):
        lines = [line for line in source.splitlines() if schema in line]
        assert lines and all("_reference_master(" in line for line in lines), schema
    names = {n for n, v in vars(Repository).items() if getattr(v, "__isabstractmethod__", False)}
    assert not [n for n in names if "crane" in n and "write" in n]


@pytest.mark.asyncio
async def test_r2ff_legacy_phase6_driver_and_vehicle_driver_routes_still_work() -> None:
    from app.repositories.mock.repository import MockRepository

    repo = MockRepository()
    listed = await http("GET", f"{API}/drivers", repo, role="ADMIN", request_id=None)
    assert listed.status_code == 200 and "responsib" not in listed.text
    assignments_before = copy.deepcopy(repo._vehicle_driver_assignments)
    drivers_before = copy.deepcopy(repo._drivers)
    response = await http("POST", f"{API}/vehicles/VEH-TEST-901/responsible-driver-events", repo,
                          json=transfer("DRV-TEST-901", None, DATE1))
    assert response.status_code == 200, response.text  # the mock's explicit TEST synthetic references
    for path in (f"{API}/vehicles/VEH-TEST-901/responsible-drivers", f"{API}/drivers/DRV-TEST-901/vehicles"):
        assert (await http("GET", path, repo, role="TECHNICIAN", request_id=None)).status_code == 200
    assert repo._vehicle_driver_assignments == assignments_before and repo._drivers == drivers_before


def test_r2ff_legacy_asset_responsibility_history_untouched() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    for module in ("domain/crane_driver_responsibility.py", "domain/crane_driver_timeline.py",
                   "api/v1/crane_driver_responsibility_routes.py"):
        source = (root / module).read_text()
        assert '"asset_responsibility_history"' not in source
        for legacy in ("PRIMARY_OPERATOR", "MAINTENANCE_SUPERVISOR", "PRIMARY_CUSTODIAN"):
            assert legacy not in source
