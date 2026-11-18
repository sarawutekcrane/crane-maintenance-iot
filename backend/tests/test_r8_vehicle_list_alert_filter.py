"""R8 S5 = A (Owner source approval 2026-11-18): the guarded `has_open_alert=true`
filter on GET /vehicles.

SYNTHETIC Mock data only. Alert existence is protected data (alert reads need a
trusted can_view actor), so the filter branch - and only that branch - enforces the
same guard before any read; without the parameter the route is byte-identical to
before (no context resolution, same body).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.domain.alert import Alert, AlertStatus
from app.repositories.mock.repository import MockRepository

API = "/api/v1"


def _alert(alert_id: str, vehicle_id: str, status: AlertStatus | None) -> Alert:
    return Alert(alert_id=alert_id, vehicle_id=vehicle_id, alert_status=status,
                 created_at=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc))


def _repo() -> MockRepository:
    repo = MockRepository()
    repo._alerts.extend([  # type: ignore[attr-defined]
        _alert("ALT-R8-1", "VEH-1046", AlertStatus.ACTIVE),
        _alert("ALT-R8-2", "VEH-1047", AlertStatus.RESOLVED),
        _alert("ALT-R8-3", "VEH-1048", AlertStatus.MUTED),
        _alert("ALT-R8-4", "VEH-1047", None),
    ])
    return repo


async def _get(params, repo, *, role: str | None = "ADMIN", user: str | None = "USR-R8-S5"):
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
        response = await client.get(f"{API}/vehicles", headers=headers, params=params)
    reset_dependency_cache()
    get_settings.cache_clear()
    return response


async def test_open_alert_filter_keeps_only_vehicles_with_an_open_alert() -> None:
    response = await _get({"has_open_alert": "true"}, _repo())
    assert response.status_code == 200, response.text
    # ACTIVE and MUTED are open; RESOLVED and blank-status rows are not
    assert [v["vehicle_id"] for v in response.json()["items"]] == ["VEH-1046", "VEH-1048"]
    assert response.json()["total_items"] == 2


async def test_open_alert_filter_ands_with_other_filters() -> None:
    response = await _get({"has_open_alert": "true", "branch_id": "BR-LAEM-CHABANG"}, _repo())
    assert [v["vehicle_id"] for v in response.json()["items"]] == ["VEH-1046"]
    response = await _get({"has_open_alert": "true", "status": "READY"}, _repo())
    assert response.json()["total_items"] == len(
        [v for v in response.json()["items"] if v["operational_status"] == "READY"])


async def test_no_open_alerts_is_an_empty_list_not_an_error() -> None:
    response = await _get({"has_open_alert": "true"}, MockRepository())
    assert response.status_code == 200 and response.json()["total_items"] == 0


@pytest.mark.parametrize("value", ["false", "1", "TRUE", ""])
async def test_only_true_is_accepted(value) -> None:
    assert (await _get({"has_open_alert": value}, _repo())).status_code == 422


class NoAlertRead(MockRepository):
    async def list_alerts(self):  # pragma: no cover - must not run
        raise AssertionError("alert read before authorization")


async def test_anonymous_filter_is_refused_before_reading_alerts(monkeypatch) -> None:
    monkeypatch.setenv("DEV_AUTH_MODE", "false")
    response = await _get({"has_open_alert": "true"}, NoAlertRead(), role=None, user=None)
    assert response.status_code == 403


async def test_actor_without_can_view_is_refused_before_reading_alerts() -> None:
    assert (await _get({"has_open_alert": "true"}, NoAlertRead(), role="UNKNOWN")).status_code == 403


async def test_without_the_parameter_the_list_is_unchanged_and_reads_no_alert() -> None:
    plain = await _get({}, NoAlertRead(), role="UNKNOWN")  # SG-1: still readable as before
    assert plain.status_code == 200
    assert plain.json() == (await _get({}, MockRepository())).json()
