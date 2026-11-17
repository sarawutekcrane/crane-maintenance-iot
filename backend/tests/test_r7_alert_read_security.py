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
                             ("DELETE", f"{API}/alerts/ALT-R7-A"), ("POST", f"{API}/alerts/ALT-R7-A/resolve"),
                             ("POST", f"{API}/vehicles/VEH-1046/alerts")):
            response = await _http(method, path, repo, role=role, json={})
            assert response.status_code in (404, 405), (role, method, path)
        # R7 policy R1 P-9: TEST-only acknowledge / mute exist, but no legacy role holds the TEST
        # grant — refused, and the stored alert is untouched. There is still no resolve route.
        for path, body in ((f"{API}/alerts/ALT-R7-A/acknowledge", {}),
                           (f"{API}/alerts/ALT-R7-A/mute", {"muted_until": "2099-01-01T00:00:00+00:00",
                                                             "reason_th": "x"})):
            response = await _http("POST", path, repo, role=role, json=body)
            assert response.status_code == 403, (role, path, response.text)
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


# ===========================================================================
# R7 Whole-Phase Mock/TEST (Owner gate 2026-11-17, policy R1 P-10 / P-11 / C-4):
# central list, provenance, verified source links, consistency, no GET writes.
# Positive paths use REAL audited Access Management grants.
# ===========================================================================

import uuid as _uuid  # noqa: E402
from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402

from app.domain.alert import AlertSeverity  # noqa: E402

R7_VEHICLE = "VEH-1048"
R7_PART_KEY = "PART_INSTANCE:PINST-TEST-R7-0001:LTR-TEST-R7-0001:PLC-TEST-R7-0001:REPLACE"


@pytest.fixture
def r7_am(monkeypatch):
    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)
    from tests import test_access_management as am

    return am


async def _granted_store(am, grants):
    store = MockRepository(access_management_seed=True)
    for user, changes in grants.items():
        response = await am.grant(store, am.MGR, am.employee(user), changes)
        assert response.status_code == 200, response.text
    return store


def _snapshot(store):
    return ([a.model_dump() for a in store._alerts], [s.model_dump() for s in store._alert_settings],
            list(store._alert_action_events))


async def test_r7_u36_reads_and_due_sources_write_nothing(r7_am) -> None:
    am = r7_am
    store = await _granted_store(am, {am.CLERK: {"can_view": True, "can_run_test_alert_evaluation": True}})
    assert (await am.http("POST", f"{API}/alerts/test-evaluations", store, am.CLERK,
                          json={"vehicle_id": R7_VEHICLE})).status_code == 200
    before = _snapshot(store)
    for path in (f"{API}/alerts", f"{API}/vehicles/{R7_VEHICLE}/alerts", f"{API}/vehicles/{R7_VEHICLE}/alert-provenance",
                 f"{API}/alerts/{store._alerts[0].alert_id}", f"{API}/pm/due/vehicles/{R7_VEHICLE}",
                 f"{API}/vehicles/{R7_VEHICLE}/part-lifetime", f"{API}/reports/certificate-expiry"):
        response = await am.http("GET", path, store, am.CLERK, request_id=None)
        assert response.status_code == 200, (path, response.text[:200])
    assert _snapshot(store) == before  # no write on any GET (certificate lazy write is the only legacy exception)


async def test_r7_u43_central_list_needs_can_view_and_never_tells_real_from_guessed(r7_am) -> None:
    am = r7_am
    store = await _granted_store(am, {am.CLERK: {"can_view": True, "can_run_test_alert_evaluation": True}})
    await am.http("POST", f"{API}/alerts/test-evaluations", store, am.CLERK, json={"vehicle_id": R7_VEHICLE})
    page = await am.http("GET", f"{API}/alerts", store, am.CLERK, request_id=None, params={"status": "ACTIVE"})
    assert page.status_code == 200 and page.json()["total_items"] == 1
    assert page.json()["items"][0]["alert_type"] == "PART_LIFETIME_DUE"
    real_id = store._alerts[0].alert_id
    for path in (f"{API}/alerts", f"{API}/alerts/{real_id}", f"{API}/alerts/ALT-GUESSED",
                 f"{API}/vehicles/{R7_VEHICLE}/alert-provenance"):
        refused = await am.http("GET", path, store, am.DRV1, request_id=None)  # no grants at all
        assert refused.status_code == 403, path
        assert real_id not in refused.text


async def test_r7_u44_source_links_only_for_a_verified_source_of_the_same_vehicle(r7_am) -> None:
    am = r7_am
    store = await _granted_store(am, {am.CLERK: {"can_view": True, "can_run_test_alert_evaluation": True}})
    await am.http("POST", f"{API}/alerts/test-evaluations", store, am.CLERK, json={"vehicle_id": R7_VEHICLE})
    (part_alert,) = [a for a in store._alerts if a.alert_type == "PART_LIFETIME_DUE"]
    read = await am.http("GET", f"{API}/alerts/{part_alert.alert_id}", store, am.CLERK, request_id=None)
    assert read.json()["source_link"] == "/part-instances/PINST-TEST-R7-0001"
    now = datetime.now(timezone.utc)
    cert = await store.create_vehicle_certificate(
        vehicle_id="VEH-1046", certificate_type_code="X", certificate_type_name_th=None, document_no=None,
        issue_date=None, expiry_date=None, alert_lead_days=None, certificate_status=None, storage_ref=None,
        note_th=None, created_by_user_id=None, created_at=now)
    store._alerts.extend([
        Alert(alert_id="ALT-FOREIGN-CERT", vehicle_id=R7_VEHICLE, alert_type="CERTIFICATE_EXPIRED",
              source_type="VEHICLE_CERTIFICATE", source_id=cert.certificate_id, created_at=now,
              alert_status=AlertStatus.ACTIVE),
        Alert(alert_id="ALT-UNKNOWN-TYPE", vehicle_id=R7_VEHICLE, alert_type="DEVICE_OFFLINE",
              source_type="DEVICE", source_id="/etc/passwd", created_at=now, alert_status=AlertStatus.ACTIVE),
        Alert(alert_id="ALT-PM", vehicle_id=R7_VEHICLE, alert_type="PM_DUE", source_type="PM_DUE_SET",
              source_id="P|A|B|C", created_at=now, alert_status=AlertStatus.ACTIVE)])
    links = {i["alert_id"]: i["source_link"]
             for i in (await am.http("GET", f"{API}/alerts", store, am.CLERK, request_id=None)).json()["items"]}
    assert links["ALT-FOREIGN-CERT"] is None  # the certificate belongs to another vehicle
    assert links["ALT-UNKNOWN-TYPE"] is None  # never built from a raw source_id
    assert links["ALT-PM"] == f"/vehicle/{R7_VEHICLE}/pm/due"
    # The part moves to another host (P-10 links only while its current or last host is the
    # alert's vehicle): the link is withheld.
    state = store._part_state
    from dataclasses import replace as _replace
    from types import MappingProxyType

    from app.domain.asset import AssetType
    from app.domain.part_instance import InstallationSegmentStatus

    old_seg = state.segments["PINST-TEST-R7-0001"][0]
    closed = old_seg.model_copy(update={"status": InstallationSegmentStatus.CLOSED, "removed_at": now,
                                        "removed_effective_at": now})
    elsewhere = old_seg.model_copy(update={"segment_id": "SEG-TEST-R7-MOVED", "asset_type": AssetType.EQUIPMENT,
                                           "asset_id": "EQP-0002", "installed_at": now, "installed_effective_at": now})
    store._part_state = _replace(state, segments=MappingProxyType({**state.segments,
                                                                   "PINST-TEST-R7-0001": (closed, elsewhere)}))
    moved = await am.http("GET", f"{API}/alerts/{part_alert.alert_id}", store, am.CLERK, request_id=None)
    assert moved.json()["source_link"] is None


async def test_r7_u45_u47_provenance_from_server_records_and_responsibilities_unavailable(r7_am) -> None:
    am = r7_am
    store = await _granted_store(am, {am.CLERK: {"can_view": True, "can_run_test_alert_evaluation": True}})
    before = (await am.http("GET", f"{API}/vehicles/{R7_VEHICLE}/alert-provenance", store, am.CLERK,
                            request_id=None)).json()
    assert set(before["types"].values()) == {"NOT_EVALUATED"} and before["responsibilities"] == "UNAVAILABLE"
    store._alert_settings[:] = [s for s in store._alert_settings if s.alert_type != "CERTIFICATE_EXPIRED"]
    await am.http("POST", f"{API}/alerts/test-evaluations", store, am.CLERK, json={"vehicle_id": R7_VEHICLE})
    after = (await am.http("GET", f"{API}/vehicles/{R7_VEHICLE}/alert-provenance", store, am.CLERK,
                           request_id=None)).json()["types"]
    # Correction C2: the dormant PM Master leaves the PM source INCOMPLETE, so PM_DUE is NOT a
    # verified zero (it was wrongly EVALUATED_NONE before the independent review).
    assert after == {"PART_LIFETIME_DUE": "ALERTS", "PM_DUE": "SOURCE_INCOMPLETE",
                     "CERTIFICATE_EXPIRED": "NOT_CONFIGURED"}


async def test_r7_u46_alert_set_equals_the_due_set_of_the_same_read_models(r7_am) -> None:
    am = r7_am
    store = await _granted_store(am, {am.CLERK: {"can_view": True, "can_run_test_alert_evaluation": True,
                                                 "can_manage_test_document_master": True}})
    await am.http("POST", f"{API}/vehicles/{R7_VEHICLE}/certificates", store, am.CLERK, json={
        "certificate_type_code": "R7-C", "certificate_type_name_th": "x", "expiry_date": "2020-01-01",
        "certificate_status": "ACTIVE"})
    await am.http("POST", f"{API}/alerts/test-evaluations", store, am.CLERK, json={"vehicle_id": R7_VEHICLE})
    lifetime = (await am.http("GET", f"{API}/vehicles/{R7_VEHICLE}/part-lifetime", store, am.CLERK,
                              request_id=None)).json()
    due_keys = {r["due_key"] for i in lifetime["instances"] for r in i["rules"] if r["status"] == "DUE"}
    report = (await am.http("GET", f"{API}/reports/certificate-expiry", store, am.CLERK, request_id=None)).json()
    expired_ids = {r["certificate_id"] for r in report["items"] if r.get("effective_status") == "EXPIRED"
                   and r.get("vehicle_id") == R7_VEHICLE}
    open_by_type = {}
    for a in store._alerts:
        if a.alert_status == AlertStatus.ACTIVE:
            open_by_type.setdefault(a.alert_type, set()).add(a.source_id)
    assert open_by_type.get("PART_LIFETIME_DUE") == due_keys == {R7_PART_KEY}
    assert open_by_type.get("CERTIFICATE_EXPIRED") == expired_ids and len(expired_ids) == 1
    pm = (await am.http("GET", f"{API}/pm/due/vehicles/{R7_VEHICLE}", store, am.CLERK, request_id=None)).json()
    assert pm["state"] == "MASTER_NOT_ACTIVE" and "PM_DUE" not in open_by_type  # E-1: no live PM alert
