"""R2 Batch R2-C2-P0b — the synthetic Mock/TEST equipment fixture.

Mock mode is always the TEST context. Before P0b every page-reachable mock
equipment (EQP-0001..0003) was REAL-scoped in the explicit R2f-d reference list,
so the caretaker reads answered EQUIPMENT_SCOPE_UNPROVEN, and the only TEST
reference (EQP-TEST-901) had no Equipment Master row. P0b classifies the
existing EQP-0002 as TEST in `SEED_EQUIPMENT_REFERENCE` (explicit entry, never
the id spelling). Nothing else changes: no master row, API, scope rule,
authorization, Sheets or production behaviour.

Batch-local ids: P0B-MASTER, -PROJ, -CARE (caretaker reads / writes / history),
-ISO (TEST/REAL isolation, fail closed). Every state-changing case uses its own
MockRepository instance; no caretaker history is seeded.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.equipment_caretaker import EquipmentCaretakerService
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST, ScopedReferenceRow
from app.repositories.mock import seed_data
from app.repositories.mock.repository import MockRepository

API = "/api/v1"
EQ = "EQP-0002"
T1, T2 = "TEC-TEST-911", "TEC-TEST-912"  # TEST technicians of the mock batch, each with a TEST Personnel link
REASON = "ทดสอบ P0b (ข้อมูลสังเคราะห์)"
BKK = timezone(timedelta(hours=7))
EVENTS = f"{API}/equipment/{EQ}/caretaker-events"


def day(offset: int) -> str:
    return (datetime.now(BKK).date() + timedelta(days=offset)).isoformat()


def at(offset: int) -> dict:
    return {"mode": "DATE", "date": day(offset)}


async def call(repo: MockRepository, method: str, path: str, *, role: str = "MAINTENANCE_MANAGER", json=None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    headers = {"X-Dev-Role": role}
    if method != "GET":
        headers["X-Request-Id"] = str(uuid.uuid4())
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://testserver") as client:
            return await client.request(method, path, json=json, headers=headers)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def transfer(tech: str, expected: str | None, effective: dict) -> dict:
    return {"operation": "TRANSFER", "technician_id": tech, "effective": effective,
            "expected_current_technician_id": expected}


# ---------------------------------------------------------------------------
# P0B-MASTER — the Equipment Master is untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p0b_master_list_and_detail_are_unchanged() -> None:
    repo = MockRepository()
    listed = (await call(repo, "GET", f"{API}/equipment?page_size=100")).json()
    assert [e["equipment_id"] for e in listed["items"]] == ["EQP-0001", "EQP-0002", "EQP-0003"]
    assert listed["total_items"] == 3
    detail = await call(repo, "GET", f"{API}/equipment/{EQ}")
    assert detail.status_code == 200
    seed = next(e for e in seed_data.SEED_EQUIPMENT if e.equipment_id == EQ).model_dump(mode="json")
    body = detail.json()
    assert {k: body[k] for k in ("equipment_id", "equipment_code", "name", "category", "serial_number", "location",
                                  "operational_status")} == {k: seed[k] for k in ("equipment_id", "equipment_code", "name",
                                                                                  "category", "serial_number", "location",
                                                                                  "operational_status")}


# ---------------------------------------------------------------------------
# P0B-PROJ — explicit scope, each id once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p0b_proj_only_eqp_0002_changes_scope() -> None:
    rows = (await MockRepository().read_equipment_reference()).rows
    scope = [(r.values["equipment_id"], r.scope, r.test_batch_id) for r in rows]
    assert scope == [
        ("EQP-0001", REFERENCE_SCOPE_REAL, ""),
        ("EQP-0002", REFERENCE_SCOPE_TEST, MOCK_TEST_BATCH_ID),
        ("EQP-0003", REFERENCE_SCOPE_REAL, ""),
        ("EQP-TEST-901", REFERENCE_SCOPE_TEST, MOCK_TEST_BATCH_ID),
    ]


# ---------------------------------------------------------------------------
# P0B-CARE — caretaker reads, writes, revisions and history in TEST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p0b_care_read_in_test_context() -> None:
    body = (await call(MockRepository(), "GET", f"{API}/equipment/{EQ}/caretakers")).json()
    assert (body["equipment_id"], body["timeline_status"], body["current_status"], body["events"]) == (
        EQ, "VALID", "NONE", [])


@pytest.mark.asyncio
async def test_p0b_care_full_lifecycle_with_test_technicians() -> None:
    repo = MockRepository()
    first = await call(repo, "POST", EVENTS, json=transfer(T1, None, at(-10)))
    assert first.status_code == 200 and first.json()["current_technician_id"] == T1, first.text
    second = await call(repo, "POST", EVENTS, json=transfer(T2, T1, at(-5)))
    assert second.status_code == 200 and second.json()["current_technician_id"] == T2
    # reverse read: the current caretaker's equipment includes EQP-0002
    reverse = (await call(repo, "GET", f"{API}/technicians/{T2}/equipment")).json()
    assert [i["equipment_id"] for i in reverse["items"]] == [EQ]
    insertion = await call(repo, "POST", EVENTS, json={
        "operation": "INSERTION", "technician_id": T2, "effective": at(-8), "expected_current_technician_id": T2,
        "reason_th": REASON})  # a backdated period of T2 inside T1's period (T1 again would be a no-op)
    assert insertion.status_code == 200 and insertion.json()["changed"] is True, insertion.text
    inserted = insertion.json()["event_id"]
    stale = await call(repo, "POST", EVENTS, json={
        "operation": "CORRECTION", "event_id": inserted, "expected_revision_no": "9", "technician_id": T2,
        "effective": at(-9), "expected_current_technician_id": T2, "reason_th": REASON})
    assert code(stale) == (409, "CARETAKER_HISTORY_STALE")
    correction = await call(repo, "POST", EVENTS, json={
        "operation": "CORRECTION", "event_id": inserted, "expected_revision_no": "1", "technician_id": T2,
        "effective": at(-9), "expected_current_technician_id": T2, "reason_th": REASON})
    assert correction.status_code == 200, correction.text
    cancellation = await call(repo, "POST", EVENTS, json={
        "operation": "CANCELLATION", "event_id": inserted, "expected_revision_no": "2",
        "expected_current_technician_id": T2, "reason_th": REASON})
    assert cancellation.status_code == 200, cancellation.text
    end = await call(repo, "POST", EVENTS, json={
        "operation": "END", "effective": {"mode": "NOW"}, "expected_current_technician_id": T2})
    assert end.status_code == 200 and end.json()["current_status"] == "ENDED"
    history = (await call(repo, "GET", f"{API}/equipment/{EQ}/caretakers")).json()
    assert history["current_status"] == "ENDED" and history["current_technician_id"] is None
    events = {e["event_id"]: e for e in history["events"]}
    assert events[inserted]["in_force"] is False and events[inserted]["revision_no"] == "3"
    in_force = [e for e in history["events"] if e["in_force"]]
    assert [e["entry_operation"] for e in in_force] == ["TRANSFER", "TRANSFER", "END"]
    backdated = next(e for e in in_force if e["technician_id"] == T1)
    assert backdated["effective_at"] != backdated["recorded_at"]  # effective time is not the recording time
    assert all(e["recorded_by"] for e in history["events"])
    assert (await call(repo, "GET", f"{API}/technicians/{T2}/equipment")).json()["items"] == []


@pytest.mark.asyncio
async def test_p0b_care_expected_current_is_still_a_stale_guard() -> None:
    repo = MockRepository()
    assert (await call(repo, "POST", EVENTS, json=transfer(T1, None, at(-3)))).status_code == 200
    assert code(await call(repo, "POST", EVENTS, json=transfer(T2, None, at(-1)))) == (409, "CARETAKER_HISTORY_STALE")


# ---------------------------------------------------------------------------
# P0B-ISO — TEST/REAL isolation stays fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("equipment", ["EQP-0001", "EQP-0003"])
async def test_p0b_iso_real_equipment_fails_closed_in_test(equipment) -> None:
    repo = MockRepository()
    assert code(await call(repo, "GET", f"{API}/equipment/{equipment}/caretakers")) == (
        422, "EQUIPMENT_SCOPE_UNPROVEN")
    assert code(await call(repo, "POST", f"{API}/equipment/{equipment}/caretaker-events",
                           json=transfer(T1, None, at(-1)))) == (422, "EQUIPMENT_SCOPE_UNPROVEN")
    assert repo._equipment_caretaker_history == []


@pytest.mark.asyncio
async def test_p0b_iso_test_equipment_never_resolves_as_real() -> None:
    with pytest.raises(ApiError) as exc:
        await EquipmentCaretakerService(MockRepository(), "REAL", "").caretakers(EQ)
    assert exc.value.code in {"EQUIPMENT_NOT_FOUND", "EQUIPMENT_SCOPE_UNPROVEN"}


@pytest.mark.asyncio
async def test_p0b_iso_real_technician_is_refused_on_the_test_equipment() -> None:
    repo = MockRepository()
    assert code(await call(repo, "POST", EVENTS, json=transfer("TEC-TEST-001", None, at(-1)))) == (
        422, "TECHNICIAN_SCOPE_UNPROVEN")  # a REAL technician is never used as a TEST one
    assert repo._equipment_caretaker_history == []


@pytest.mark.asyncio
async def test_p0b_iso_duplicated_reference_fails_closed() -> None:
    repo = MockRepository()
    repo._equipment_reference = [*repo._equipment_reference,
                                 ScopedReferenceRow(values={"equipment_id": EQ}, scope=REFERENCE_SCOPE_TEST,
                                                    test_batch_id=MOCK_TEST_BATCH_ID)]
    assert code(await call(repo, "GET", f"{API}/equipment/{EQ}/caretakers")) == (409, "EQUIPMENT_ID_AMBIGUOUS")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["TECHNICIAN", "DRIVER", "SUPERVISOR", "DRIVER_DEPARTMENT_MANAGER"])
async def test_p0b_iso_no_authorization_change(role) -> None:
    repo = MockRepository()
    assert (await call(repo, "POST", EVENTS, role=role, json=transfer(T1, None, at(-1)))).status_code == 403
    assert repo._equipment_caretaker_history == []
    assert (await call(repo, "GET", f"{API}/equipment/{EQ}/caretakers", role=role)).status_code == 200  # can_view
