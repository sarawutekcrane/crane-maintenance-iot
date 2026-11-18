"""R8 Whole-Phase (Owner source approval 2026-11-18, R1 policy ED-3 / ED-10 / ED-11 /
OD-7): read authorization of every read the R8 UI consumes or adds.

SYNTHETIC Mock data only; not PostgreSQL or production evidence. Each guard is
proven to refuse BEFORE any repository read (the repository below fails the test
on the guarded read), to answer the same 403 for a real and a guessed id, and to
keep its existing audience. Routes outside R8 (SG-1) are asserted unchanged so this
batch neither fixes nor worsens them silently.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.repositories.mock.repository import MockRepository

API = "/api/v1"
VEHICLE = "VEH-1046"


async def _http(method: str, path: str, repo, *, role: str | None = "ADMIN", user: str | None = "USR-R8-READ",
                **kwargs):
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    headers = {"X-Request-Id": str(uuid.uuid4())}
    if role is not None:
        headers["X-Dev-Role"] = role
    if user is not None:
        headers["X-Dev-User-Id"] = user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.request(method, path, headers=headers, **kwargs)
    reset_dependency_cache()
    get_settings.cache_clear()
    return response


class NoReadRepo(MockRepository):
    """Any read a guarded route could make before its guard fails the test."""

    async def get_vehicle(self, vehicle_id):  # pragma: no cover - must not run
        raise AssertionError("vehicle read before authorization")

    async def get_current_location(self, vehicle_id):  # pragma: no cover - must not run
        raise AssertionError("location read before authorization")

    async def list_vehicle_components(self, vehicle_id):  # pragma: no cover - must not run
        raise AssertionError("component read before authorization")

    async def read_vehicle_master_for_summary(self):  # pragma: no cover - must not run
        raise AssertionError("vehicle master read before authorization")

    async def read_vehicle_master_with_registry(self):  # pragma: no cover - must not run
        raise AssertionError("vehicle registry read before authorization")

    async def list_findings(self, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("finding read before authorization")

    async def list_alerts(self):  # pragma: no cover - must not run
        raise AssertionError("alert read before authorization")


GUARDED_READS = [
    f"{API}/dashboard/fleet-status",
    f"{API}/dashboard/fleet-status?branch_id=BR-01",
    f"{API}/vehicles/{VEHICLE}/machine-state",
    f"{API}/vehicles/VEH-DOES-NOT-EXIST/machine-state",
    f"{API}/vehicles/{VEHICLE}/latest-location",
    f"{API}/vehicles/VEH-DOES-NOT-EXIST/latest-location",
    f"{API}/findings/follow-up",
    f"{API}/findings/follow-up?asset_type=VEHICLE&asset_id={VEHICLE}",
    f"{API}/vehicles?has_open_alert=true",
]


@pytest.mark.parametrize("path", GUARDED_READS)
async def test_anonymous_actor_is_refused_before_any_read(path, monkeypatch) -> None:
    monkeypatch.setenv("DEV_AUTH_MODE", "false")  # no dev user: the context is anonymous
    response = await _http("GET", path, NoReadRepo(), role=None, user=None)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path", GUARDED_READS)
async def test_trusted_actor_without_a_read_capability_is_refused_before_any_read(path) -> None:
    response = await _http("GET", path, NoReadRepo(), role="UNKNOWN")
    assert response.status_code == 403, response.text


async def test_real_and_guessed_vehicle_ids_get_the_same_refusal() -> None:
    real = await _http("GET", f"{API}/vehicles/{VEHICLE}/machine-state", NoReadRepo(), role="UNKNOWN")
    fake = await _http("GET", f"{API}/vehicles/VEH-NOPE/machine-state", NoReadRepo(), role="UNKNOWN")
    assert real.status_code == fake.status_code == 403
    assert real.json()["error"]["code"] == fake.json()["error"]["code"]


@pytest.mark.parametrize("role", ["ADMIN", "TECHNICIAN", "DRIVER", "MAINTENANCE", "MAINTENANCE_MANAGER"])
async def test_vehicle_machine_state_is_gps_free_for_can_view_readers(role) -> None:
    response = await _http("GET", f"{API}/vehicles/{VEHICLE}/machine-state", MockRepository(), role=role)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vehicle_id"] == VEHICLE
    assert set(body) == {"vehicle_id", "readings", "note"}
    for forbidden in ("latitude", "longitude", "gps_observed_at"):
        assert forbidden not in body
    for reading in body["readings"]:
        assert set(reading) == {"component_id", "counter_type", "value", "observed_at"}
        # an unknown value stays null, never a fabricated 0 (checked when absent)
        assert reading["value"] is None or isinstance(reading["value"], (int, float))


async def test_vehicle_machine_state_unknown_vehicle_is_404_after_the_guard() -> None:
    response = await _http("GET", f"{API}/vehicles/VEH-NOPE/machine-state", MockRepository())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


async def test_legacy_machine_state_route_is_unchanged_sg1() -> None:
    """SG-1: the pre-existing unguarded route is NOT changed by R8 (its consumers are
    the PM work-order and repair-create pages). Recorded, not accepted."""
    response = await _http("GET", f"{API}/machine-state/current?asset_type=VEHICLE&asset_id={VEHICLE}",
                           MockRepository(), role="UNKNOWN")
    assert response.status_code == 200


@pytest.mark.parametrize("role", ["ADMIN", "TECHNICIAN", "DRIVER", "MAINTENANCE_MANAGER"])
async def test_latest_location_keeps_its_can_view_audience(role) -> None:
    response = await _http("GET", f"{API}/vehicles/{VEHICLE}/latest-location", MockRepository(), role=role)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("role", ["ADMIN", "TECHNICIAN", "DRIVER", "MAINTENANCE", "MAINTENANCE_MANAGER",
                                  "DRIVER_DEPARTMENT_MANAGER"])
async def test_finding_followup_keeps_its_audience(role) -> None:
    """REPAIR_READ_CAPABILITIES: every can_view reader plus the follow-up menu audience
    (can_manage_repair / can_manage_finding_repair)."""
    response = await _http("GET", f"{API}/findings/follow-up", MockRepository(), role=role)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("role", ["ADMIN", "TECHNICIAN", "DRIVER"])
async def test_dashboard_keeps_its_can_view_audience(role) -> None:
    response = await _http("GET", f"{API}/dashboard/fleet-status", MockRepository(), role=role)
    assert response.status_code == 200, response.text
    assert "branch_id" not in response.json()  # the unfiltered body is unchanged


@pytest.mark.parametrize("path", [
    f"{API}/vehicles",
    f"{API}/vehicles/{VEHICLE}",
    f"{API}/vehicles/{VEHICLE}/status-events",
    f"{API}/findings",
])
async def test_sg1_routes_are_unchanged_and_recorded_not_accepted(path) -> None:
    """SG-1 (Owner choice SG-1 = A): pre-existing unguarded reads that R8 does not
    consume are left exactly as they were and remain a STOP before REAL use."""
    response = await _http("GET", path, MockRepository(), role="UNKNOWN")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("bad_id", ["..", "%2E%2E", "a" * 300, "VEH%2F1046", "%E0%B8%A3%E0%B8%96"])
async def test_malicious_ids_on_the_new_meter_route_never_500(bad_id) -> None:
    response = await _http("GET", f"{API}/vehicles/{bad_id}/machine-state", MockRepository())
    assert response.status_code in (404, 422), response.text
