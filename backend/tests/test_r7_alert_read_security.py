"""R7-B — alert read authorization and fail-closed alert policy gates
(Owner-approved bounded Mock/TEST scope, DEC-R7-MOCK-BOUNDED-APPROACH-20261111).

SYNTHETIC Mock data only. Not PostgreSQL concurrency evidence (A09 / R11). No
alert generator, scheduler, severity mapping or lifecycle route exists or is
added (A01 / A06 / A07 write RBAC stay Owner gates); these tests prove that the
two existing GET routes now refuse an unauthorized or unverified caller before
any repository read, and that reading other domains never fabricates an alert.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.domain.alert import Alert, AlertSeverity, AlertStatus
from app.repositories.mock.repository import MockRepository

API = "/api/v1"


def _alert(alert_id: str, vehicle_id: str = "VEH-1046", minute: int = 0, **overrides) -> Alert:
    return Alert(alert_id=alert_id, vehicle_id=vehicle_id,
                 created_at=datetime(2026, 1, 1, 8, minute, tzinfo=timezone.utc), **overrides)


async def _http(method: str, path: str, repo, *, role: str | None = "ADMIN", user: str | None = "USR-TEST-R7",
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
    """Fails the test if any alert / vehicle read happens (deny-before-read proof)."""

    async def get_alert(self, alert_id):  # pragma: no cover - must not run
        raise AssertionError("alert read before authorization")

    async def list_alerts_for_vehicle(self, vehicle_id):  # pragma: no cover - must not run
        raise AssertionError("alert list read before authorization")

    async def get_vehicle(self, vehicle_id):  # pragma: no cover - must not run
        raise AssertionError("vehicle read before authorization")


@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER",
                                  "MAINTENANCE_MANAGER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_a_can_view_actor_reads_the_list_and_the_detail_unchanged(role) -> None:
    repo = MockRepository()
    repo._alerts.extend([  # type: ignore[attr-defined]
        _alert("ALT-R7-B", minute=1, alert_type="PM_DUE", severity=AlertSeverity.WARNING,
               alert_status=AlertStatus.ACTIVE, source_type="OPAQUE", source_id="000009"),
        _alert("ALT-R7-A", minute=1),
        _alert("ALT-R7-C", minute=5, severity=None, alert_status=None),
        _alert("ALT-R7-OTHER", vehicle_id="VEH-1047"),
    ])
    listed = await _http("GET", f"{API}/vehicles/VEH-1046/alerts", repo, role=role)
    assert listed.status_code == 200, listed.text
    # Backend-owned deterministic order: created_at desc, alert_id asc.
    assert [a["alert_id"] for a in listed.json()] == ["ALT-R7-C", "ALT-R7-A", "ALT-R7-B"]
    assert listed.json()[0]["severity"] is None and listed.json()[0]["alert_status"] is None
    detail = await _http("GET", f"{API}/alerts/ALT-R7-B", repo, role=role)
    assert detail.status_code == 200
    assert (detail.json()["source_type"], detail.json()["source_id"]) == ("OPAQUE", "000009")


@pytest.mark.parametrize("path", [f"{API}/vehicles/VEH-1046/alerts", f"{API}/vehicles/VEH-DOES-NOT-EXIST/alerts",
                                  f"{API}/alerts/ALT-R7-A", f"{API}/alerts/ALT-DOES-NOT-EXIST"])
async def test_an_actor_without_can_view_is_refused_before_any_read_and_learns_nothing(path) -> None:
    response = await _http("GET", path, NoReadRepo(), role="NO_SUCH_ROLE")
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "HTTP_ERROR"
    assert "ALT-" not in str(body) and "source" not in str(body)


async def test_an_unverified_request_without_dev_auth_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("DEV_AUTH_MODE", "false")
    for path in (f"{API}/vehicles/VEH-1046/alerts", f"{API}/alerts/ALT-R7-A"):
        response = await _http("GET", path, NoReadRepo(), role=None, user=None)
        assert response.status_code == 403, path


async def test_a_blank_user_id_is_not_a_trusted_actor() -> None:
    from fastapi import HTTPException

    from app.api.v1.alerts import _require_alert_reader
    from app.context import RequestContext

    for user_id in (None, "", "   "):
        with pytest.raises(HTTPException) as caught:
            _require_alert_reader(RequestContext(request_id="r", user_id=user_id,
                                                 capabilities=frozenset({"can_view"})))
        assert caught.value.status_code == 403


async def test_an_authorized_reader_still_gets_the_existing_not_found_contracts() -> None:
    repo = MockRepository()
    missing_alert = await _http("GET", f"{API}/alerts/ALT-DOES-NOT-EXIST", repo)
    assert (missing_alert.status_code, missing_alert.json()["error"]["code"]) == (404, "ALERT_NOT_FOUND")
    missing_vehicle = await _http("GET", f"{API}/vehicles/VEH-DOES-NOT-EXIST/alerts", repo)
    assert (missing_vehicle.status_code, missing_vehicle.json()["error"]["code"]) == (404, "VEHICLE_NOT_FOUND")


async def test_no_public_alert_mutation_route_exists_for_any_role() -> None:
    repo = MockRepository()
    repo._alerts.append(_alert("ALT-R7-A", alert_status=AlertStatus.ACTIVE))  # type: ignore[attr-defined]
    for role in ("ADMIN", "MAINTENANCE_MANAGER"):
        for method, path in (("POST", f"{API}/alerts"), ("PATCH", f"{API}/alerts/ALT-R7-A"),
                             ("DELETE", f"{API}/alerts/ALT-R7-A"), ("POST", f"{API}/alerts/ALT-R7-A/acknowledge"),
                             ("POST", f"{API}/alerts/ALT-R7-A/mute"), ("POST", f"{API}/alerts/ALT-R7-A/resolve"),
                             ("POST", f"{API}/vehicles/VEH-1046/alerts")):
            response = await _http(method, path, repo, role=role, json={})
            assert response.status_code in (404, 405), (role, method, path)
    (stored,) = repo._alerts  # type: ignore[attr-defined]
    assert stored.alert_status == AlertStatus.ACTIVE and stored.acknowledged_at is None


async def test_reading_due_and_certificate_sources_never_fabricates_an_alert() -> None:
    """No generator exists: R4 PM Due, R6 Parts Due, the certificate expiry
    report and certificate reads (an ACTIVE certificate whose expiry is near or
    past, with alert_lead_days) leave the alert store exactly as it was."""
    repo = MockRepository()
    await repo.create_vehicle_certificate(
        vehicle_id="VEH-1046", certificate_type_code="R7-INS", certificate_type_name_th=None, document_no=None,
        issue_date=None, expiry_date=datetime(2020, 1, 1).date(), alert_lead_days=30,
        certificate_status=None, storage_ref=None, note_th=None, created_by_user_id=None,
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    before = list(repo._alerts)  # type: ignore[attr-defined]
    for path in (f"{API}/pm/due/vehicles/VEH-1046", f"{API}/pm/due/vehicles", f"{API}/vehicles/VEH-1046/certificates",
                 f"{API}/reports/certificate-expiry", f"{API}/vehicles/VEH-1048/part-lifetime",
                 f"{API}/vehicles/VEH-1046/alerts", f"{API}/vehicles/VEH-1048/alerts"):
        response = await _http("GET", path, repo)
        assert response.status_code == 200, (path, response.text[:200])  # each source read really ran
    assert repo._alerts == before == []  # type: ignore[attr-defined]


async def test_access_management_mode_needs_a_granted_can_view(monkeypatch) -> None:
    from tests.test_access_management import DRV1, MGR, employee, grant, http

    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "true")
    store = MockRepository(access_management_seed=True)
    store._alerts.append(_alert("ALT-R7-AM"))  # type: ignore[attr-defined]
    refused = await http("GET", f"{API}/vehicles/VEH-1046/alerts", store, DRV1, role="ADMIN", request_id=None)
    assert refused.status_code == 403  # zero grants; the development role header grants nothing here
    refused_detail = await http("GET", f"{API}/alerts/ALT-R7-AM", store, DRV1, role="ADMIN", request_id=None)
    assert refused_detail.status_code == 403
    assert (await grant(store, MGR, employee(DRV1), {"can_view": True})).status_code == 200
    allowed = await http("GET", f"{API}/vehicles/VEH-1046/alerts", store, DRV1, role="TECHNICIAN", request_id=None)
    assert allowed.status_code == 200 and [a["alert_id"] for a in allowed.json()] == ["ALT-R7-AM"]
    get_settings.cache_clear()
