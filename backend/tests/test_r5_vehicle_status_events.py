"""R5 T5 — vehicle status write authorization (AMB-1), effective-dated status
events, effective-time corrections and evidence-based downtime (OD-3).

Mock always runs in the TEST context; VEH-1048 is the seed's TEST-scoped vehicle,
VEH-1046 is REAL-scoped. Every refusal is proven to leave the vehicle, its status
history, its corrections and its derived downtime unchanged."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.common import OperationalStatus
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.vehicle import VehicleStatusHistoryEntry
from app.domain.vehicle_status_events import (
    STATUS_HISTORY_INCONSISTENT,
    derive_downtime,
    resolved_events,
)
from app.repositories.base import REFERENCE_SCOPE_TEST, ScopedReferenceRow
from app.repositories.mock.repository import MockRepository
from tests.test_technician_assignment_batch_r2f_h1 import http

API = "/api/v1/vehicles"
IN_SCOPE, REAL_SCOPED = "VEH-1048", "VEH-1046"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = 86400


def ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def snapshot(repo, vehicle_id: str):
    window = (NOW - timedelta(days=30), NOW)
    events = resolved_events(await repo.list_vehicle_status_history(vehicle_id),
                             await repo.list_vehicle_status_time_corrections(vehicle_id))
    return (await repo.get_vehicle(vehicle_id), await repo.list_vehicle_status_history(vehicle_id),
            await repo.list_vehicle_status_time_corrections(vehicle_id),
            derive_downtime(events, *window, None))


async def event(repo, status: str, days_ago: float, *, role="MAINTENANCE_MANAGER", vehicle=IN_SCOPE, request_id="auto"):
    return await http("POST", f"{API}/{vehicle}/status-events", repo, role=role, request_id=request_id,
                      json={"status": status, "effective_at": ago(days_ago)})


async def downtime(repo, vehicle=IN_SCOPE, start=20, end=0):
    response = await http("GET", f"{API}/{vehicle}/downtime?from={ago(start).replace('+', '%2B')}"
                                 f"&to={ago(end).replace('+', '%2B')}", repo, role="MAINTENANCE_MANAGER")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- AMB-1


@pytest.mark.asyncio
async def test_amb1_1_an_authorized_in_scope_manager_changes_the_current_status() -> None:
    repo = MockRepository()
    response = await http("PATCH", f"{API}/{IN_SCOPE}/status", repo, role="MAINTENANCE_MANAGER",
                          json={"status": "MAINTENANCE"})
    assert response.status_code == 200, response.text
    assert response.json()["history_entry"]["effective_at"] is None  # the recorded time is the evidence
    assert (await repo.get_vehicle(IN_SCOPE)).operational_status == OperationalStatus.MAINTENANCE


@pytest.mark.asyncio
async def test_amb1_2_and_3_effective_dated_change_and_time_correction_with_a_reason() -> None:
    repo = MockRepository()
    created = await event(repo, "MAINTENANCE", 3)
    assert created.status_code == 200, created.text
    entry = created.json()["history_entry"]
    assert ts(entry["effective_at"]) == ts(ago(3)) and ts(entry["changed_at"]) > ts(entry["effective_at"])
    history_id = entry["history_id"]
    no_reason = await http("POST", f"{API}/{IN_SCOPE}/status-events/{history_id}/time-corrections", repo,
                           role="MAINTENANCE_MANAGER", json={"new_effective_at": ago(4)})
    assert (no_reason.status_code, no_reason.json()["error"]["code"]) == (
        422, "VEHICLE_STATUS_CORRECTION_REASON_REQUIRED")
    fixed = await http("POST", f"{API}/{IN_SCOPE}/status-events/{history_id}/time-corrections", repo,
                       role="MAINTENANCE_MANAGER", json={"new_effective_at": ago(4), "reason": "แจ้งเข้าซ่อมจริงเร็วกว่า"})
    assert fixed.status_code == 200, fixed.text
    correction = fixed.json()["correction"]
    assert (ts(correction["previous_effective_at"]), ts(correction["new_effective_at"])) == (ts(ago(3)), ts(ago(4)))
    events = (await http("GET", f"{API}/{IN_SCOPE}/status-events", repo, role="MAINTENANCE_MANAGER")).json()
    corrected = next(e for e in events if e["history_id"] == history_id)
    assert ts(corrected["effective_at"]) == ts(ago(4)) and corrected["effective_source"] == "EXPLICIT"
    assert len(corrected["corrections"]) == 1
    assert (await repo.get_vehicle(IN_SCOPE)).operational_status == OperationalStatus.MAINTENANCE


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["DRIVER", "TECHNICIAN"])
async def test_amb1_4_and_5_driver_and_technician_get_403_on_every_write_with_zero_writes(role: str) -> None:
    repo = MockRepository()
    seeded = await event(repo, "MAINTENANCE", 5)
    history_id = seeded.json()["history_entry"]["history_id"]
    before = await snapshot(repo, IN_SCOPE)
    calls = []
    original = repo.read_vehicle_reference

    async def spy():
        calls.append(1)
        return await original()

    repo.read_vehicle_reference = spy
    responses = [
        await http("PATCH", f"{API}/{IN_SCOPE}/status", repo, role=role, json={"status": "WORKING"}),
        await event(repo, "WORKING", 1, role=role),
        await http("POST", f"{API}/{IN_SCOPE}/status-events/{history_id}/time-corrections", repo, role=role,
                   json={"new_effective_at": ago(6), "reason": "x"}),
    ]
    assert [r.status_code for r in responses] == [403, 403, 403]
    assert calls == []  # refused before any vehicle read
    assert await snapshot(repo, IN_SCOPE) == before


@pytest.mark.asyncio
async def test_amb1_6_capability_but_outside_the_scope_is_refused_without_a_write() -> None:
    repo = MockRepository()
    before = await snapshot(repo, REAL_SCOPED)
    first_history = before[1][0].history_id
    responses = [
        await http("PATCH", f"{API}/{REAL_SCOPED}/status", repo, role="MAINTENANCE_MANAGER",
                   json={"status": "MAINTENANCE"}),
        await event(repo, "MAINTENANCE", 1, vehicle=REAL_SCOPED),
        await http("POST", f"{API}/{REAL_SCOPED}/status-events/{first_history}/time-corrections", repo,
                   role="MAINTENANCE_MANAGER", json={"new_effective_at": ago(9), "reason": "x"}),
    ]
    assert [r.status_code for r in responses] == [422, 422, 422]
    assert [r.json()["error"]["code"] for r in responses] == ["VEHICLE_SCOPE_UNPROVEN"] * 3
    assert all(MOCK_TEST_BATCH_ID not in r.text and "REAL" not in r.text for r in responses)
    assert await snapshot(repo, REAL_SCOPED) == before


@pytest.mark.asyncio
async def test_amb1_7_missing_ambiguous_and_unconfigured_scope_fail_closed() -> None:
    repo = MockRepository()
    missing = await http("PATCH", f"{API}/VEH-9999/status", repo, role="MAINTENANCE_MANAGER",
                         json={"status": "MAINTENANCE"})
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "VEHICLE_NOT_FOUND")
    before = await snapshot(repo, IN_SCOPE)
    duplicate = ScopedReferenceRow(values={"vehicle_id": IN_SCOPE}, scope=REFERENCE_SCOPE_TEST,
                                   test_batch_id=MOCK_TEST_BATCH_ID)
    repo._vehicle_reference = [duplicate, duplicate]
    ambiguous = await http("PATCH", f"{API}/{IN_SCOPE}/status", repo, role="MAINTENANCE_MANAGER",
                           json={"status": "MAINTENANCE"})
    assert (ambiguous.status_code, ambiguous.json()["error"]["code"]) == (409, "VEHICLE_ID_AMBIGUOUS")
    repo._vehicle_reference = None
    assert await snapshot(repo, IN_SCOPE) == before

    from app.config import get_settings
    from app.dependencies import get_assignment_cutover, get_repository, reset_dependency_cache
    from app.domain.technician_assignment import AssignmentCutover
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_assignment_cutover] = lambda: AssignmentCutover(data_context=None)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://t") as client:
        unconfigured = await client.patch(f"{API}/{IN_SCOPE}/status", json={"status": "MAINTENANCE"},
                                          headers={"X-Dev-Role": "MAINTENANCE_MANAGER"})
    reset_dependency_cache()
    assert (unconfigured.status_code, unconfigured.json()["error"]["code"]) == (
        503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")
    assert await snapshot(repo, IN_SCOPE) == before


@pytest.mark.asyncio
async def test_amb1_8_existing_authorized_current_status_changes_still_work_for_every_status() -> None:
    repo = MockRepository()
    for status_value in ("MAINTENANCE", "OUT_OF_SERVICE", "LONG_TERM_PARKING", "READY", "WORKING"):
        response = await http("PATCH", f"{API}/{IN_SCOPE}/status", repo, role="MAINTENANCE",
                              json={"status": status_value, "note": "ทดสอบ"})
        assert response.status_code == 200, response.text
    assert len(await repo.list_vehicle_status_history(IN_SCOPE)) == 6


# ---------------------------------------------------------------- OD-3 downtime


@pytest.mark.asyncio
async def test_amb1_9_downtime_from_effective_unavailable_intervals_with_merging_and_reopened_availability() -> None:
    repo = MockRepository()
    for status_value, days in (("MAINTENANCE", 10), ("WORKING", 8), ("OUT_OF_SERVICE", 5), ("MAINTENANCE", 4),
                               ("LONG_TERM_PARKING", 2), ("WORKING", 1)):
        assert (await event(repo, status_value, days)).status_code == 200
    result = await downtime(repo, start=12, end=0)
    assert [(ts(i["started_at"]), ts(i["ended_at"])) for i in result["intervals"]] == [
        (ts(ago(10)), ts(ago(8))), (ts(ago(5)), ts(ago(2)))]
    assert result["total_seconds"] == 5 * DAY  # LONG_TERM_PARKING (2 → 1 days ago) is not counted
    assert result["unavailable_statuses"] == ["MAINTENANCE", "OUT_OF_SERVICE"]


@pytest.mark.asyncio
async def test_open_repairs_and_pm_and_awaiting_parts_never_create_or_double_count_downtime() -> None:
    repo = MockRepository()
    assert (await event(repo, "MAINTENANCE", 6)).status_code == 200
    assert (await event(repo, "WORKING", 3)).status_code == 200
    baseline = await downtime(repo, start=10, end=0)
    for _ in range(2):  # two simultaneous Repair Work Orders on the same vehicle
        created = await http("POST", "/api/v1/repairs", repo, role="MAINTENANCE",
                             json={"asset_type": "VEHICLE", "asset_id": IN_SCOPE, "source_type": "MANUAL"})
        assert created.status_code == 200, created.text
    assert await downtime(repo, start=10, end=0) == baseline
    assert baseline["total_seconds"] == 3 * DAY


@pytest.mark.asyncio
async def test_missing_history_is_unknown_never_fabricated() -> None:
    repo = MockRepository()
    seeded_at = (await repo.list_vehicle_status_history(IN_SCOPE))[0].changed_at
    result = await downtime(repo, start=(NOW - seeded_at).days + 30, end=0)
    assert len(result["unknown"]) == 1 and ts(result["unknown"][0]["ended_at"]) == seeded_at
    assert result["total_seconds"] == 0  # the seed status (LONG_TERM_PARKING) is not downtime
    empty = derive_downtime([], NOW - timedelta(days=5), NOW, None)
    assert empty["intervals"] == [] and empty["total_seconds"] == 0
    assert empty["unknown"] == [(NOW - timedelta(days=5), NOW)]


def test_inconsistent_history_is_flagged_and_counted_from_evidence_only() -> None:
    entry = VehicleStatusHistoryEntry(history_id="STH-X", vehicle_id="V", status=OperationalStatus.MAINTENANCE,
                                      changed_at=NOW - timedelta(days=2))
    result = derive_downtime(resolved_events([entry], []), NOW - timedelta(days=1), NOW, OperationalStatus.WORKING)
    assert result["flags"] == [STATUS_HISTORY_INCONSISTENT] and result["total_seconds"] == DAY


@pytest.mark.asyncio
async def test_amb1_10_corrections_are_bounded_by_neighbours_and_out_of_order_events_are_refused() -> None:
    repo = MockRepository()
    first = (await event(repo, "MAINTENANCE", 6)).json()["history_entry"]["history_id"]
    await event(repo, "WORKING", 3)
    before = await snapshot(repo, IN_SCOPE)
    out_of_order = await event(repo, "OUT_OF_SERVICE", 4)
    assert (out_of_order.status_code, out_of_order.json()["error"]["code"]) == (409, "VEHICLE_STATUS_EVENT_OUT_OF_ORDER")
    too_late = await http("POST", f"{API}/{IN_SCOPE}/status-events/{first}/time-corrections", repo,
                          role="MAINTENANCE_MANAGER", json={"new_effective_at": ago(2), "reason": "เกินช่วง"})
    assert (too_late.status_code, too_late.json()["error"]["code"]) == (409, "VEHICLE_STATUS_EVENT_OUT_OF_ORDER")
    future = await event(repo, "WORKING", -1)
    assert (future.status_code, future.json()["error"]["code"]) == (422, "FUTURE_EFFECTIVE_NOT_ALLOWED")
    assert await snapshot(repo, IN_SCOPE) == before
    ok = await http("POST", f"{API}/{IN_SCOPE}/status-events/{first}/time-corrections", repo,
                    role="MAINTENANCE_MANAGER", json={"new_effective_at": ago(5), "reason": "เวลาจริง"})
    assert ok.status_code == 200
    assert (await downtime(repo, start=10, end=0))["total_seconds"] == 2 * DAY


@pytest.mark.asyncio
async def test_replay_and_conflicting_reuse_of_a_request_id() -> None:
    repo = MockRepository()
    request_id = "1b4e28ba-2fa1-41d2-883f-0016d3cca427"
    first = await event(repo, "MAINTENANCE", 2, request_id=request_id)
    again = await event(repo, "MAINTENANCE", 2, request_id=request_id)
    assert first.status_code == again.status_code == 200
    assert (first.json()["replayed"], again.json()["replayed"]) == (False, True)
    assert again.json()["history_entry"]["history_id"] == first.json()["history_entry"]["history_id"]
    assert len(await repo.list_vehicle_status_history(IN_SCOPE)) == 2
    conflict = await event(repo, "WORKING", 1, request_id=request_id)
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "VEHICLE_STATUS_REQUEST_CONFLICT")
    missing_id = await event(repo, "WORKING", 1, request_id=None)
    assert (missing_id.status_code, missing_id.json()["error"]["code"]) == (422, "REQUEST_ID_REQUIRED")
