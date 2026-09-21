"""Web/API Phase 6 Batch 5A — Alert Read Foundation.

Proves the Batch 5A scope (see `app.domain.alert`/`app.domain.
alert_service` module docstrings, restated from the task's own frozen
sections):

- D24 (APPROVED/FROZEN): AlertSeverity is exactly INFO/WARNING/CRITICAL
  - the vocabulary only, no alert_type -> severity mapping
- AlertStatus is exactly ACTIVE/ACKNOWLEDGED/MUTED/RESOLVED, declared for
  reading only - no transition matrix, no acknowledge/mute/resolve/
  reopen method exists anywhere in this batch
- alert_type/source_type/source_id remain plain opaque text - no
  AlertType/SourceType enum, no rejection of an unrecognized alert_type,
  source_id text-safety (leading zeros preserved)
- conservative nullability: every field except alert_id/vehicle_id/
  created_at stays honestly None when the underlying cell is blank
- read-only repository/service/API surface: get_alert,
  list_alerts_for_vehicle, and their GET-only routes - no create/update/
  delete/acknowledge/mute/resolve/reopen method or endpoint exists
- deterministic vehicle-alert ordering (created_at descending, alert_id
  ascending tie-break) - technical determinism only, never a severity
  ranking or suppression evaluation
- Google Sheets reads never write."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.domain.alert import Alert, AlertSeverity, AlertStatus
from app.domain.alert_service import AlertService
from app.errors import ApiError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.mock import MockRepository

from tests.test_google_sheets_real_io import FakeSpreadsheet, FakeWorksheet, _ws


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


def _alert(
    alert_id: str,
    vehicle_id: str = "VEH-TEST",
    created_at: datetime | None = None,
    **overrides,
) -> Alert:
    return Alert(
        alert_id=alert_id,
        vehicle_id=vehicle_id,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        **overrides,
    )


# ---------------------------------------------------------------------------
# 1-2. ENUM VOCABULARIES
# ---------------------------------------------------------------------------


def test_1_alert_severity_enum_contains_exactly_three_values() -> None:
    assert {s.value for s in AlertSeverity} == {"INFO", "WARNING", "CRITICAL"}


def test_2_alert_status_enum_contains_exactly_four_values() -> None:
    assert {s.value for s in AlertStatus} == {
        "ACTIVE",
        "ACKNOWLEDGED",
        "MUTED",
        "RESOLVED",
    }


# ---------------------------------------------------------------------------
# 3-6. GOOGLE SHEETS PARSING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_3_sheets_parser_reads_all_thirteen_fields_correctly() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(
        [
            "ALT-1", "VEH-1", "PM_DUE", "PM_WORK_ORDER", "WO-000123",
            "WARNING", "2026-01-01T00:00:00+00:00", "ACKNOWLEDGED",
            "2026-01-05T00:00:00+00:00", "USR-1", "2026-01-01T01:00:00+00:00",
            "", "แจ้งเตือนถึงกำหนด PM",
        ]
    )
    repo = _repo_with_fake_sheets(ws)

    alert = await repo.get_alert("ALT-1")

    assert alert is not None
    assert alert.alert_id == "ALT-1"
    assert alert.vehicle_id == "VEH-1"
    assert alert.alert_type == "PM_DUE"
    assert alert.source_type == "PM_WORK_ORDER"
    assert alert.source_id == "WO-000123"
    assert alert.severity == AlertSeverity.WARNING
    assert alert.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert alert.alert_status == AlertStatus.ACKNOWLEDGED
    assert alert.muted_until == datetime(2026, 1, 5, tzinfo=timezone.utc)
    assert alert.acknowledged_by_user_id == "USR-1"
    assert alert.acknowledged_at == datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    assert alert.resolved_at is None
    assert alert.message_th == "แจ้งเตือนถึงกำหนด PM"


@pytest.mark.asyncio
async def test_4_leading_zero_source_id_survives_as_text() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(
        [
            "ALT-2", "VEH-1", "PM_DUE", "PM_WORK_ORDER", "000009",
            "INFO", "2026-01-01T00:00:00+00:00", "ACTIVE",
            "", "", "", "", "",
        ]
    )
    repo = _repo_with_fake_sheets(ws)

    alert = await repo.get_alert("ALT-2")

    assert alert is not None
    assert alert.source_id == "000009"
    assert alert.source_id != 9  # type: ignore[comparison-overlap]


@pytest.mark.asyncio
async def test_5_nullable_fields_remain_none_when_blank() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(
        ["ALT-3", "VEH-1", "", "", "", "", "2026-01-01T00:00:00+00:00", "", "", "", "", "", ""]
    )
    repo = _repo_with_fake_sheets(ws)

    alert = await repo.get_alert("ALT-3")

    assert alert is not None
    assert alert.alert_type is None
    assert alert.source_type is None
    assert alert.source_id is None
    assert alert.severity is None
    assert alert.alert_status is None
    assert alert.muted_until is None
    assert alert.acknowledged_by_user_id is None
    assert alert.acknowledged_at is None
    assert alert.resolved_at is None
    assert alert.message_th is None


@pytest.mark.asyncio
async def test_6_unknown_opaque_alert_type_preserved_as_is() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(
        [
            "ALT-4", "VEH-1", "SOME_FUTURE_ALERT_TYPE_NOT_IN_ANY_ENUM", "", "",
            "", "2026-01-01T00:00:00+00:00", "", "", "", "", "", "",
        ]
    )
    repo = _repo_with_fake_sheets(ws)

    alert = await repo.get_alert("ALT-4")

    assert alert is not None
    assert alert.alert_type == "SOME_FUTURE_ALERT_TYPE_NOT_IN_ANY_ENUM"


# ---------------------------------------------------------------------------
# 7. VEHICLE FILTERING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_7_list_alerts_for_vehicle_returns_only_exact_vehicle_matches() -> None:
    repo = MockRepository()
    repo._alerts.extend(
        [
            _alert("ALT-A1", vehicle_id="VEH-A"),
            _alert("ALT-A2", vehicle_id="VEH-A"),
            _alert("ALT-B1", vehicle_id="VEH-B"),
        ]
    )
    alerts_a = await repo.list_alerts_for_vehicle("VEH-A")
    assert {a.alert_id for a in alerts_a} == {"ALT-A1", "ALT-A2"}


# ---------------------------------------------------------------------------
# 8-11. SERVICE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_8_service_rejects_unknown_vehicle_for_vehicle_scoped_list() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.list_for_vehicle("VEH-DOES-NOT-EXIST")
    assert exc_info.value.code == "VEHICLE_NOT_FOUND"
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_9_service_get_existing_alert_works() -> None:
    repo = MockRepository()
    repo._alerts.append(_alert("ALT-1"))
    service = AlertService(repo)
    alert = await service.get_alert("ALT-1")
    assert alert.alert_id == "ALT-1"


@pytest.mark.asyncio
async def test_10_service_get_missing_alert_returns_404_apierror() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.get_alert("ALT-DOES-NOT-EXIST")
    assert exc_info.value.code == "ALERT_NOT_FOUND"
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_11_service_deterministic_ordering() -> None:
    repo = MockRepository()
    repo._alerts.extend(
        [
            _alert("ALT-OLD", vehicle_id="VEH-1046", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            _alert("ALT-NEW-B", vehicle_id="VEH-1046", created_at=datetime(2026, 1, 5, tzinfo=timezone.utc)),
            _alert("ALT-NEW-A", vehicle_id="VEH-1046", created_at=datetime(2026, 1, 5, tzinfo=timezone.utc)),
        ]
    )
    service = AlertService(repo)
    ordered = await service.list_for_vehicle("VEH-1046")
    # created_at descending first, then alert_id ascending as the tie-break
    # for the two equal-timestamp rows.
    assert [a.alert_id for a in ordered] == ["ALT-NEW-A", "ALT-NEW-B", "ALT-OLD"]


# ---------------------------------------------------------------------------
# 12. GOOGLE SHEETS READ PATH NEVER WRITES
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_12_sheets_read_path_performs_no_write() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(
        ["ALT-1", "VEH-1", "PM_DUE", "", "", "WARNING", "2026-01-01T00:00:00+00:00", "ACTIVE", "", "", "", "", ""]
    )
    repo = _repo_with_fake_sheets(ws)

    # Baseline captured AFTER seeding (seeding itself uses append_row) -
    # what matters is that the REPOSITORY's own read methods below never
    # add to these counts.
    append_row_calls_before = ws.append_row_calls
    append_rows_calls_before = ws.append_rows_calls
    delete_rows_calls_before = ws.delete_rows_calls
    rows_before = len(ws.rows)

    await repo.get_alert("ALT-1")
    await repo.list_alerts_for_vehicle("VEH-1")
    await repo.get_alert("ALT-DOES-NOT-EXIST")

    assert ws.append_row_calls == append_row_calls_before
    assert ws.append_rows_calls == append_rows_calls_before
    assert ws.delete_rows_calls == delete_rows_calls_before
    assert len(ws.rows) == rows_before  # unchanged


# ---------------------------------------------------------------------------
# 13-16. API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_13_api_list_vehicle_alerts_works(client: AsyncClient) -> None:
    from app.dependencies import get_repository

    repo = get_repository()
    repo._alerts.append(_alert("ALT-API-1", vehicle_id="VEH-1046"))  # type: ignore[attr-defined]

    response = await client.get("/api/v1/vehicles/VEH-1046/alerts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(a["alert_id"] == "ALT-API-1" for a in body)


@pytest.mark.asyncio
async def test_14_api_get_alert_works(client: AsyncClient) -> None:
    from app.dependencies import get_repository

    repo = get_repository()
    repo._alerts.append(  # type: ignore[attr-defined]
        _alert(
            "ALT-API-2",
            vehicle_id="VEH-1046",
            alert_type="PM_DUE",
            severity=AlertSeverity.CRITICAL,
            alert_status=AlertStatus.ACTIVE,
        )
    )

    response = await client.get("/api/v1/alerts/ALT-API-2")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["alert_id"] == "ALT-API-2"
    assert body["severity"] == "CRITICAL"
    assert body["alert_status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_15_api_missing_alert_returns_404_contract(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alerts/ALT-DOES-NOT-EXIST")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "ALERT_NOT_FOUND"


@pytest.mark.asyncio
async def test_16_no_lifecycle_write_endpoint_exists(client: AsyncClient) -> None:
    # No route at all for a bare POST /api/v1/alerts (create).
    post_response = await client.post("/api/v1/alerts", json={})
    assert post_response.status_code in (404, 405)

    # The only registered method on /api/v1/alerts/{alert_id} is GET.
    patch_response = await client.patch("/api/v1/alerts/ALT-1", json={})
    assert patch_response.status_code in (404, 405)

    delete_response = await client.delete("/api/v1/alerts/ALT-1")
    assert delete_response.status_code in (404, 405)

    # No acknowledge/mute/resolve/reopen sub-route exists either.
    for action in ("acknowledge", "mute", "resolve", "reopen"):
        action_response = await client.post(f"/api/v1/alerts/ALT-1/{action}", json={})
        assert action_response.status_code == 404
