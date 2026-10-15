"""R2 Batch R2-C2-P0 — synthetic Mock/TEST vehicle and driver fixtures.

Mock mode is always the TEST context. Before P0 every listed mock vehicle and
driver was REAL-scoped in the R2 reference reads, so R2f-f and E2 answered
*_SCOPE_UNPROVEN on every page-reachable identity. P0 classifies the existing
VEH-1048 as TEST (explicitly, `SEED_TEST_SCOPED_VEHICLE_IDS`) and adds three
synthetic TEST drivers (DRV-TEST-901 / -902 ACTIVE, -903 INACTIVE) to the mock
Driver Master. Nothing is derived from id spelling, no scope check changes, no
API, schema, Sheets or production behaviour changes.

Batch-local ids: P0-MASTER (lists / details / sequence), -PROJ (reference
projection), -R2FF, -E2, -BIDIR, -ISO (TEST/REAL isolation, fail closed).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.crane_driver_responsibility import CraneDriverResponsibilityService
from app.domain.operational_driver_assignment import OperationalDriverAssignmentService
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST
from app.repositories.mock import seed_data
from app.repositories.mock.repository import MockRepository

API = "/api/v1"
VTEST = "VEH-1048"
D1, D2, D3 = "DRV-TEST-901", "DRV-TEST-902", "DRV-TEST-903"
BKK = timezone(timedelta(hours=7))
REASON = "ทดสอบ P0 (ข้อมูลสังเคราะห์)"


def day(offset: int) -> str:
    """A Bangkok calendar date relative to today (E2 uses the real clock over HTTP)."""
    return (datetime.now(BKK).date() + timedelta(days=offset)).isoformat()


async def call(repo: MockRepository, method: str, path: str, *, role: str = "DRIVER_DEPARTMENT_MANAGER", json=None):
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


def e2_create(driver: str, mode: str, start: str, end: str, shift: dict | None = None, handover=None) -> dict:
    body: dict = {"operation": "CREATE", "driver_id": driver, "mode": mode, "start_date": start, "end_date": end}
    if shift:
        body["shift"] = shift
    if handover:
        body["handover"] = {"predecessor_event_id": handover, "expected_revision_no": "1"}
    return body


NIGHT = {"start_time": "20:00", "end_time": "08:00", "end_day_offset": 1}
E2_OPS = f"{API}/vehicles/{VTEST}/operational-driver-assignment-operations"


# ---------------------------------------------------------------------------
# P0-MASTER
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p0_master_vehicle_list_is_still_exactly_the_three_seed_vehicles() -> None:
    repo = MockRepository()
    body = (await call(repo, "GET", f"{API}/vehicles?page_size=100")).json()
    assert [v["vehicle_id"] for v in body["items"]] == ["VEH-1046", "VEH-1047", "VEH-1048"]
    assert body["total_items"] == 3
    detail = await call(repo, "GET", f"{API}/vehicles/{VTEST}")
    assert detail.status_code == 200 and detail.json()["vehicle"]["vehicle_id"] == VTEST


@pytest.mark.asyncio
async def test_p0_master_test_drivers_are_listed_and_resolve_and_originals_are_unchanged() -> None:
    repo = MockRepository()
    listed = (await call(repo, "GET", f"{API}/drivers?page_size=100")).json()["items"]
    assert [d["driver_id"] for d in listed] == ["DRV-0001", "DRV-0002", D1, D2, D3]
    originals = {d.driver_id: d.model_dump(mode="json") for d in seed_data.SEED_DRIVERS}
    assert {d["driver_id"]: d for d in listed if d["driver_id"] in originals} == originals
    statuses = {}
    for driver in (D1, D2, D3):
        response = await call(repo, "GET", f"{API}/drivers/{driver}")
        assert response.status_code == 200, driver
        statuses[driver] = response.json()["active_status"]
        assert "TEST" in response.json()["driver_name_th"]  # clearly synthetic, never presented as a person
    assert statuses == {D1: "ACTIVE", D2: "ACTIVE", D3: "INACTIVE"}


@pytest.mark.asyncio
async def test_p0_master_new_driver_ids_keep_the_drv_sequence() -> None:
    repo = MockRepository()
    response = await call(repo, "POST", f"{API}/drivers", role="ADMIN",
                          json={"driver_name_th": "ผู้ขับใหม่ (ทดสอบ)"})
    assert response.status_code == 200, response.text
    assert response.json()["driver_id"] == "DRV-0003"  # the TEST fixtures never shift DRV-000N


# ---------------------------------------------------------------------------
# P0-PROJ — explicit scope, no duplicate reference rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p0_proj_vehicle_scope_is_explicit() -> None:
    rows = (await MockRepository().read_vehicle_reference()).rows
    scope = {(r.values["vehicle_id"], r.scope, r.test_batch_id) for r in rows}
    assert (VTEST, REFERENCE_SCOPE_TEST, MOCK_TEST_BATCH_ID) in scope
    assert {("VEH-1046", REFERENCE_SCOPE_REAL, ""), ("VEH-1047", REFERENCE_SCOPE_REAL, "")} <= scope
    assert [r.values["vehicle_id"] for r in rows].count(VTEST) == 1  # TEST only, never also REAL
    assert seed_data.SEED_TEST_SCOPED_VEHICLE_IDS == frozenset({VTEST})


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["read_driver_master_reference", "read_driver_responsibility_reference"])
async def test_p0_proj_driver_scope_is_explicit_and_each_id_appears_once(reader) -> None:
    rows = (await getattr(MockRepository(), reader)()).rows
    ids = [r.values["driver_id"] for r in rows]
    assert len(ids) == len(set(ids))  # DRV-TEST-901 is not projected twice
    scope = {r.values["driver_id"]: (r.scope, r.test_batch_id) for r in rows}
    assert scope["DRV-0001"] == scope["DRV-0002"] == (REFERENCE_SCOPE_REAL, "")
    assert scope[D1] == scope[D2] == scope[D3] == (REFERENCE_SCOPE_TEST, MOCK_TEST_BATCH_ID)


# ---------------------------------------------------------------------------
# P0-R2FF / P0-E2 / P0-BIDIR — over HTTP, mock mode (TEST)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p0_r2ff_accepts_the_test_vehicle_and_drivers_both_directions() -> None:
    repo = MockRepository()
    yesterday = {"mode": "DATE", "date": day(-1)}
    transfer = {"operation": "TRANSFER", "driver_id": D1, "effective": yesterday, "expected_current_driver_id": None}
    response = await call(repo, "POST", f"{API}/vehicles/{VTEST}/responsible-driver-events", json=transfer)
    assert response.status_code == 200 and response.json()["current_driver_id"] == D1
    vehicle_view = (await call(repo, "GET", f"{API}/vehicles/{VTEST}/responsible-drivers")).json()
    assert vehicle_view["current_driver_id"] == D1
    driver_view = (await call(repo, "GET", f"{API}/drivers/{D1}/vehicles")).json()
    assert [i["vehicle_id"] for i in driver_view["items"]] == [VTEST]
    inactive = {**transfer, "driver_id": D3, "effective": {"mode": "NOW"}, "expected_current_driver_id": D1}
    assert code(await call(repo, "POST", f"{API}/vehicles/{VTEST}/responsible-driver-events", json=inactive)) == (
        422, "DRIVER_NOT_ACTIVE")


@pytest.mark.asyncio
async def test_p0_e2_assignment_substitution_and_handover_with_test_drivers() -> None:
    repo = MockRepository()
    first = await call(repo, "POST", E2_OPS, json=e2_create(D1, "FULL_DAY", day(10), day(14)))
    assert first.status_code == 200, first.text
    a = first.json()["event_ids"][0]
    sub = {"operation": "SUBSTITUTE", "event_id": a, "expected_revision_no": "1", "dates": [day(11)],
           "driver_id": D2, "reason_th": REASON}
    assert (await call(repo, "POST", E2_OPS, json=sub)).status_code == 200
    h2 = await call(repo, "POST", E2_OPS, json={**e2_create(D2, "NIGHT_SHIFT", day(14), day(15), NIGHT),
                                                 "handover": {"predecessor_event_id": a,
                                                              "expected_revision_no": "2"}})
    assert h2.status_code == 200, h2.text
    assert len(h2.json()["record_ids"]) == 2  # the NIGHT assignment and its H2 HANDOVER
    schedule = (await call(repo, "GET", f"{API}/vehicles/{VTEST}/operational-driver-assignments")).json()
    drivers = [(i["label_date"], i["assigned_driver_id"]) for i in schedule["intervals"]]
    assert (day(11), D2) in drivers and (day(10), D1) in drivers and (day(14), D2) in drivers
    history = (await call(repo, "GET", f"{API}/vehicles/{VTEST}/operational-driver-assignment-history")).json()
    assert any(e["kind"] == "HANDOVER" for e in history["events"])


@pytest.mark.asyncio
async def test_p0_bidir_driver_view_lists_its_assignments_across_vehicles() -> None:
    repo = MockRepository()
    assert (await call(repo, "POST", E2_OPS, json=e2_create(D2, "FULL_DAY", day(20), day(21)))).status_code == 200
    view = (await call(repo, "GET", f"{API}/drivers/{D2}/operational-driver-assignments")).json()
    assert {(i["vehicle_id"], i["label_date"]) for i in view["intervals"]} == {(VTEST, day(20)), (VTEST, day(21))}


@pytest.mark.asyncio
async def test_p0_e2_inactive_test_driver_is_refused_for_new_and_future_assignments() -> None:
    repo = MockRepository()
    assert code(await call(repo, "POST", E2_OPS, json=e2_create(D3, "FULL_DAY", day(5), day(6)))) == (
        422, "DRIVER_NOT_ACTIVE")


@pytest.mark.asyncio
async def test_p0_e2_assignment_retained_with_warning_when_its_driver_becomes_inactive() -> None:
    repo = MockRepository()  # isolated instance: the lifecycle change below never leaves this test
    assert (await call(repo, "POST", E2_OPS, json=e2_create(D2, "FULL_DAY", day(30), day(31)))).status_code == 200
    repo._drivers[D2] = repo._drivers[D2].model_copy(update={"active_status": "INACTIVE"})
    schedule = (await call(repo, "GET", f"{API}/vehicles/{VTEST}/operational-driver-assignments")).json()
    assert len(schedule["intervals"]) == 2  # retained, never silently cancelled
    assert "FUTURE_ASSIGNMENT_DRIVER_NOT_ACTIVE_PENDING_REVIEW" in {w["code"] for w in schedule["warnings"]}
    assert MockRepository()._drivers[D2].active_status == "ACTIVE"  # the seed itself is unchanged


# ---------------------------------------------------------------------------
# P0-ISO — TEST/REAL isolation stays fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("vehicle", ["VEH-1046", "VEH-1047"])
async def test_p0_iso_real_vehicles_stay_scope_unproven_in_test(vehicle) -> None:
    repo = MockRepository()
    for path in (f"{API}/vehicles/{vehicle}/operational-driver-assignments",
                 f"{API}/vehicles/{vehicle}/responsible-drivers"):
        assert code(await call(repo, "GET", path)) == (422, "VEHICLE_SCOPE_UNPROVEN"), path


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["DRV-0001", "DRV-0002"])
async def test_p0_iso_real_drivers_cannot_be_used_as_test_drivers(driver) -> None:
    repo = MockRepository()
    assert code(await call(repo, "POST", E2_OPS, json=e2_create(driver, "FULL_DAY", day(5), day(6)))) == (
        422, "DRIVER_SCOPE_UNPROVEN")
    r2ff = {"operation": "TRANSFER", "driver_id": driver, "effective": {"mode": "NOW"},
            "expected_current_driver_id": None}
    assert code(await call(repo, "POST", f"{API}/vehicles/{VTEST}/responsible-driver-events", json=r2ff)) == (
        422, "DRIVER_SCOPE_UNPROVEN")
    assert code(await call(repo, "GET", f"{API}/drivers/{driver}/operational-driver-assignments")) == (
        422, "DRIVER_SCOPE_UNPROVEN")
    assert repo._operational_driver_assignment_history == [] and repo._crane_driver_responsibility_history == []


@pytest.mark.asyncio
async def test_p0_iso_test_identities_never_resolve_as_real() -> None:
    repo = MockRepository()
    for call_ in (OperationalDriverAssignmentService(repo, "REAL", "").vehicle_schedule(VTEST),
                  CraneDriverResponsibilityService(repo, "REAL", "").responsible_drivers(VTEST)):
        with pytest.raises(ApiError) as exc:
            await call_
        assert exc.value.code == "VEHICLE_SCOPE_UNPROVEN"
    with pytest.raises(ApiError) as exc:
        await OperationalDriverAssignmentService(repo, "REAL", "").driver_schedule(D1)
    assert exc.value.code == "DRIVER_SCOPE_UNPROVEN"


@pytest.mark.asyncio
async def test_p0_iso_duplicated_references_still_fail_closed() -> None:
    repo = MockRepository()
    duplicated = repo._driver_reference_rows() + [r for r in repo._driver_reference_rows() if r.values["driver_id"] == D1]
    repo._driver_reference = duplicated
    assert code(await call(repo, "POST", E2_OPS, json=e2_create(D1, "FULL_DAY", day(5), day(6)))) == (
        409, "DRIVER_ID_AMBIGUOUS")


@pytest.mark.asyncio
async def test_p0_iso_no_driver_is_ever_chosen_automatically() -> None:
    repo = MockRepository()
    created = await call(repo, "POST", E2_OPS, json=e2_create(D1, "FULL_DAY", day(10), day(12)))
    event = created.json()["event_ids"][0]
    no_driver = {"operation": "SUBSTITUTE", "event_id": event, "expected_revision_no": "1", "dates": [day(11)],
                 "reason_th": REASON}
    assert (await call(repo, "POST", E2_OPS, json=no_driver)).status_code == 422
    without = {k: v for k, v in e2_create(D1, "FULL_DAY", day(20), day(21)).items() if k != "driver_id"}
    assert (await call(repo, "POST", E2_OPS, json=without)).status_code == 422
