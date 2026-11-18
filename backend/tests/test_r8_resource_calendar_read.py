"""R8 early workstream — Resource Calendar read (OD-7 = A) over BOTH streams.
SYNTHETIC Mock/TEST data only.

Proves: the fleet-wide read needs a trusted actor holding can_assign_crane_driver or
can_assign_crane_crew (a can_view-only reader such as DRIVER is refused) before any
read; the 42-day window; VEHICLES / PERSONNEL / BOTH; each entry's own start/end,
vehicle, role and identity; IDENTITY_UNVERIFIED / CONFLICTED statuses; the public
name allow-list (no phone / licence / account / GPS); branch and person filters;
an interval whose vehicle has no master record is still shown (no false free day).
"""
from __future__ import annotations

import pytest

from app.repositories.mock.repository import MockRepository
from tests.test_r8_crew_assignment import DRV_B, P1, P2, V1, V2, create, crew_rows, e2_create, link
from tests.test_r8_read_authorization import NoReadRepo, _http

PATH = "/api/v1/resource-calendar"
WINDOW = {"from": "2026-11-16", "to": "2026-11-30"}
ENTRY_KEYS = {"kind", "event_id", "vehicle_id", "machine_no", "personnel_id", "personnel_name", "driver_id",
              "driver_name", "identity", "role", "role_note_th", "mode", "label_date", "effective_start",
              "effective_end", "status"}


async def seeded() -> MockRepository:
    repo = MockRepository()  # legacy-mode mock: TEST personnel PER-TEST-911 / 912 of the mock batch
    await create(repo, personnel=P2, vehicle=V1, start="2026-11-20", end="2026-11-20")
    await create(repo, personnel="PER-TEST-912", vehicle=V2, role="OTHER", note="ผู้ช่วยยก",
                 start="2026-11-21", end="2026-11-21")
    await e2_create(repo, DRV_B, vehicle=V1, start="2026-11-24", end="2026-11-24")  # unlinked driver
    return repo


async def get(repo, *, role: str = "MAINTENANCE_MANAGER", **params):
    return await _http("GET", PATH, repo, role=role, params={**WINDOW, **params})


@pytest.mark.parametrize("role", ["MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER", "ADMIN"])
async def test_assignment_capability_holders_read_the_calendar(role) -> None:
    response = await get(await seeded(), role=role)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["view"], body["time_zone"], body["date_from"], body["date_to"]) == (
        "BOTH", "Asia/Bangkok", "2026-11-16", "2026-11-30")


@pytest.mark.parametrize("role", ["DRIVER", "TECHNICIAN", "MAINTENANCE", "UNKNOWN"])
async def test_can_view_only_readers_are_refused_before_any_read(role) -> None:
    assert (await get(NoReadRepo(), role=role)).status_code == 403


async def test_anonymous_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("DEV_AUTH_MODE", "false")
    assert (await _http("GET", PATH, NoReadRepo(), role=None, user=None, params=WINDOW)).status_code == 403


async def test_entries_carry_each_persons_own_interval_and_only_public_fields() -> None:
    body = (await get(await seeded())).json()
    kinds = sorted(e["kind"] for e in body["entries"])
    assert kinds == ["CREW", "CREW", "DRIVER"]
    for entry in body["entries"]:
        assert set(entry) == ENTRY_KEYS
        for forbidden in ("phone", "license_no", "user_id", "latitude", "longitude"):
            assert forbidden not in entry
    rigger = next(e for e in body["entries"] if e["personnel_id"] == P2)
    assert (rigger["vehicle_id"], rigger["role"], rigger["label_date"], rigger["machine_no"]) == (
        V1, "RIGGER", "2026-11-20", "TC-14")
    assert rigger["effective_start"] == "2026-11-19T17:00:00+00:00"  # 2026-11-20 00:00 Bangkok
    other = next(e for e in body["entries"] if e["role"] == "OTHER")
    assert other["role_note_th"] == "ผู้ช่วยยก"
    assert other["machine_no"] is None  # VEH-TEST-901 has no master record: shown, never hidden
    driver = next(e for e in body["entries"] if e["kind"] == "DRIVER")
    assert (driver["identity"], driver["driver_id"], driver["personnel_id"]) == ("UNLINKED", DRV_B, None)
    assert driver["driver_name"]  # the Driver Master display name only


async def test_unlinked_driver_overlapping_crew_shows_identity_unverified() -> None:
    repo = await seeded()
    # crew data written before the rule (directly), overlapping the unlinked driver's day
    crew_rows(repo)[0].update(start_date="2026-11-24", end_date="2026-11-24")
    body = (await get(repo)).json()
    statuses = {e["kind"]: e["status"] for e in body["entries"] if e["label_date"] == "2026-11-24"}
    assert statuses == {"CREW": "IDENTITY_UNVERIFIED", "DRIVER": "IDENTITY_UNVERIFIED"}
    (conflict,) = body["conflicts"]
    assert conflict["code"] == "CROSS_ROLE_IDENTITY_UNVERIFIED"


async def test_linked_driver_shows_the_person_name() -> None:
    repo = MockRepository()
    link(repo, P2, "DRV-TEST-901")
    await e2_create(repo, "DRV-TEST-901", vehicle=V1, start="2026-11-24", end="2026-11-24")
    (entry,) = (await get(repo)).json()["entries"]
    assert (entry["identity"], entry["personnel_id"], entry["driver_name"]) == ("LINKED", P2, None)
    assert entry["personnel_name"]


async def test_filters_and_views() -> None:
    repo = await seeded()
    assert {e["personnel_id"] for e in (await get(repo, personnel_id=P2)).json()["entries"]} == {P2}
    assert {e["vehicle_id"] for e in (await get(repo, vehicle_id=V2)).json()["entries"]} == {V2}
    # VEH-1048 is in BR-? (no recorded branch in the mock) -> the branch filter keeps nothing for it
    assert (await get(repo, branch_id="BR-LAEM-CHABANG")).json()["entries"] == []
    assert (await get(repo, view="PERSONNEL")).status_code == 200
    assert (await get(repo, view="VEHICLES")).status_code == 200
    assert (await get(repo, view="ALL")).status_code == 422


@pytest.mark.parametrize("window", [
    {"from": "2026-11-01", "to": "2026-12-13"},  # 43 days
    {"from": "2026-11-20", "to": "2026-11-19"},
    {"from": "2026-11-xx", "to": "2026-11-19"},
])
async def test_window_validation(window) -> None:
    response = await _http("GET", PATH, MockRepository(), role="MAINTENANCE_MANAGER", params=window)
    assert response.status_code == 422


async def test_42_day_window_is_accepted_and_entries_outside_are_excluded() -> None:
    repo = await seeded()
    response = await _http("GET", PATH, repo, role="MAINTENANCE_MANAGER",
                           params={"from": "2026-11-01", "to": "2026-12-12"})
    assert response.status_code == 200
    narrow = await _http("GET", PATH, repo, role="MAINTENANCE_MANAGER", params={"from": "2026-11-22",
                                                                                "to": "2026-11-23"})
    assert narrow.json()["entries"] == []  # an empty day = no recorded assignment, not a verified free person


async def test_person_one_has_no_entries_by_default() -> None:
    body = (await get(await seeded(), personnel_id=P1)).json()
    assert body["entries"] == []
