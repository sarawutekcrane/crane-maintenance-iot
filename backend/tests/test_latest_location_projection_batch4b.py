"""Web/API Phase 6 Batch 4B — Latest Location Projection.

Proves the Batch 4B frozen contract (see
`app.domain.vehicle_event_service.VehicleEventService.
_project_latest_location` module/method docstrings, restated from the
task's own frozen sections):

- only an eligible trusted GPS event (gps_valid is exactly True,
  latitude/longitude both present, time_quality TIME_SYNCED/
  TIME_ESTIMATED, event_time not null) may ever advance latest_location
- current-state ordering: no row -> create; row with null gps_time ->
  may be established; strictly newer event_time -> update; equal/older
  event_time -> never overwritten
- field mapping: gps_time <- event.event_time, received_at <-
  event.received_at (never the backend clock), source_device_id/
  source_component_id <- event.device_id/component_id
- no hardcoded preferred device/component: newest eligible event_time
  wins regardless of source
- duplicate retry heals a missing/stale projection using the STORED
  original event, never the replay payload's possibly-different fields
- raw vehicle_event remains untouched/unaffected either way
- Google Sheets: one row per vehicle, targeted update or single append,
  never a full-sheet rewrite, with the same text-coercion protection as
  every other opaque identifier in this codebase."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.dependencies import get_repository
from app.domain.location_snapshot import CurrentLocation
from app.domain.vehicle_event import TimeQuality, VehicleEventType
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.mock import MockRepository

from tests.test_google_sheets_real_io import FakeSpreadsheet, FakeWorksheet, _ws
from tests.test_vehicle_event_batch4a import _component_id, _create_event, _payload


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


def _current_location(vehicle_id: str) -> CurrentLocation | None:
    """Same technique `test_automatic_machine_state_snapshot.py` already
    uses: `get_repository()` returns the exact MockRepository singleton
    the `client` fixture's app is using, since Batch 4B adds no public
    read endpoint for latest_location (task M)."""
    repo = get_repository()
    return repo._current_locations.get(vehicle_id)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ELIGIBILITY (items 1-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_time_synced_gps_event_creates_latest_location(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    event = await _create_event(
        client,
        _payload(
            "VEH-1046", component_id, device_event_id="E-4B-1",
            gps_valid=True, latitude=13.75, longitude=100.50,
            time_quality="TIME_SYNCED", event_time="2026-01-01T00:00:00+00:00",
        ),
    )
    current = _current_location("VEH-1046")
    assert current is not None
    assert current.latitude == 13.75
    assert current.longitude == 100.50
    assert current.gps_time == datetime.fromisoformat(event["event_time"])


@pytest.mark.asyncio
async def test_time_estimated_gps_event_creates_latest_location(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1047")
    await _create_event(
        client,
        _payload(
            "VEH-1047", component_id, device_event_id="E-4B-2",
            gps_valid=True, latitude=14.0, longitude=101.0,
            time_quality="TIME_ESTIMATED", event_time="2026-01-01T00:00:00+00:00",
        ),
    )
    current = _current_location("VEH-1047")
    assert current is not None
    assert current.latitude == 14.0
    assert current.longitude == 101.0


@pytest.mark.asyncio
async def test_gps_valid_false_does_not_update_latest_location(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1048")
    await _create_event(
        client,
        _payload(
            "VEH-1048", component_id, device_event_id="E-4B-3",
            gps_valid=False, latitude=15.0, longitude=102.0,
        ),
    )
    assert _current_location("VEH-1048") is None


@pytest.mark.asyncio
async def test_gps_valid_null_does_not_update_latest_location(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1048")
    await _create_event(
        client,
        _payload(
            "VEH-1048", component_id, device_event_id="E-4B-4",
            gps_valid=None, latitude=None, longitude=None,
        ),
    )
    assert _current_location("VEH-1048") is None


@pytest.mark.asyncio
async def test_time_not_synced_event_does_not_update_latest_location(
    client: AsyncClient,
) -> None:
    component_id = await _component_id(client, "VEH-1048")
    await _create_event(
        client,
        _payload(
            "VEH-1048", component_id, device_event_id="E-4B-5",
            gps_valid=True, latitude=15.0, longitude=102.0,
            time_quality="TIME_NOT_SYNCED", event_time=None,
        ),
    )
    assert _current_location("VEH-1048") is None


# ---------------------------------------------------------------------------
# CURRENT-STATE ORDERING (items 6-8, 14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_newer_event_time_updates_latest_location(client: AsyncClient) -> None:
    vehicle_id = "VEH-1046"
    component_id = await _component_id(client, vehicle_id)
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORDER-1", device_event_id="E-ORD-1",
            gps_valid=True, latitude=1.0, longitude=1.0,
            event_time="2026-02-01T00:00:00+00:00",
        ),
    )
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORDER-1", device_event_id="E-ORD-2",
            gps_valid=True, latitude=2.0, longitude=2.0,
            event_time="2026-02-02T00:00:00+00:00",
        ),
    )
    current = _current_location(vehicle_id)
    assert current is not None
    assert current.latitude == 2.0
    assert current.gps_time == datetime(2026, 2, 2, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_older_out_of_order_event_does_not_regress_latest_location(
    client: AsyncClient,
) -> None:
    vehicle_id = "VEH-1047"
    component_id = await _component_id(client, vehicle_id)
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORDER-2", device_event_id="E-ORD-3",
            gps_valid=True, latitude=5.0, longitude=5.0,
            event_time="2026-02-10T00:00:00+00:00",
        ),
    )
    # A delayed, older raw event arrives after the newer one.
    older = await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORDER-2", device_event_id="E-ORD-4",
            gps_valid=True, latitude=6.0, longitude=6.0,
            event_time="2026-02-01T00:00:00+00:00",
        ),
    )
    # Raw row is still stored (Batch 4A behavior untouched).
    assert older["event_id"] is not None
    # But current location is not regressed.
    current = _current_location(vehicle_id)
    assert current is not None
    assert current.latitude == 5.0
    assert current.gps_time == datetime(2026, 2, 10, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_equal_event_time_does_not_overwrite_latest_location(client: AsyncClient) -> None:
    vehicle_id = "VEH-1048"
    component_id = await _component_id(client, vehicle_id)
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORDER-3", device_event_id="E-ORD-5",
            gps_valid=True, latitude=7.0, longitude=7.0,
            event_time="2026-02-15T00:00:00+00:00",
        ),
    )
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORDER-3", device_event_id="E-ORD-6",
            gps_valid=True, latitude=8.0, longitude=8.0,
            event_time="2026-02-15T00:00:00+00:00",
        ),
    )
    current = _current_location(vehicle_id)
    assert current is not None
    # First writer keeps the current row - equal event_time never wins.
    assert current.latitude == 7.0


@pytest.mark.asyncio
async def test_legacy_row_with_null_gps_time_can_be_replaced(client: AsyncClient) -> None:
    vehicle_id = "VEH-1046"
    repo = get_repository()
    # Simulate a pre-Batch-4B legacy row (no source columns, no gps_time)
    # by seeding it directly - mirrors the seeding technique already used
    # by test_automatic_machine_state_snapshot.py for no-live-source gaps.
    repo._current_locations[vehicle_id] = CurrentLocation(  # type: ignore[attr-defined]
        vehicle_id=vehicle_id,
        latitude=99.0,
        longitude=99.0,
        gps_time=None,
        received_at=None,
        source_device_id=None,
        source_component_id=None,
    )
    component_id = await _component_id(client, vehicle_id)
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_event_id="E-LEGACY-1",
            gps_valid=True, latitude=10.0, longitude=10.0,
            event_time="2026-03-01T00:00:00+00:00",
        ),
    )
    current = _current_location(vehicle_id)
    assert current is not None
    assert current.latitude == 10.0
    assert current.gps_time == datetime(2026, 3, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# FIELD MAPPING (item 9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_location_field_mapping(client: AsyncClient) -> None:
    vehicle_id = "VEH-1047"
    component_id = await _component_id(client, vehicle_id)
    event = await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-MAP-1", device_event_id="E-MAP-1",
            gps_valid=True, latitude=11.0, longitude=12.0,
            event_time="2026-03-05T00:00:00+00:00",
        ),
    )
    current = _current_location(vehicle_id)
    assert current is not None
    assert current.gps_time == datetime.fromisoformat(event["event_time"])
    assert current.received_at == datetime.fromisoformat(event["received_at"])
    assert current.source_device_id == "DEV-MAP-1"
    assert current.source_component_id == component_id


# ---------------------------------------------------------------------------
# MULTIPLE DEVICES (item 10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_devices_newest_trusted_event_wins_regardless_of_source(
    client: AsyncClient,
) -> None:
    vehicle_id = "VEH-1048"
    component_id = await _component_id(client, vehicle_id)
    # CRANE-like device reports first (arbitrary naming - never hardcoded
    # as preferred by the implementation).
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-CRANE", device_event_id="E-MULTI-1",
            gps_valid=True, latitude=20.0, longitude=20.0,
            event_time="2026-04-01T00:00:00+00:00",
        ),
    )
    # CARRIER-like device reports a NEWER event_time - it must win even
    # though "CARRIER" is not alphabetically/hardcoded-preferred.
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-CARRIER", device_event_id="E-MULTI-2",
            gps_valid=True, latitude=21.0, longitude=21.0,
            event_time="2026-04-02T00:00:00+00:00",
        ),
    )
    current = _current_location(vehicle_id)
    assert current is not None
    assert current.latitude == 21.0
    assert current.source_device_id == "DEV-CARRIER"


# ---------------------------------------------------------------------------
# DUPLICATE RETRY (items 11-13, 15)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_retry_raw_event_count_remains_one(client: AsyncClient) -> None:
    vehicle_id = "VEH-1046"
    component_id = await _component_id(client, vehicle_id)
    payload = _payload(
        vehicle_id, component_id, device_id="DEV-DUP", device_event_id="E-DUP-1",
        gps_valid=True, latitude=30.0, longitude=30.0,
        event_time="2026-05-01T00:00:00+00:00",
    )
    first = await _create_event(client, payload)
    replay = await _create_event(client, payload)
    assert replay["event_id"] == first["event_id"]

    listing = await client.get(f"/api/v1/vehicles/{vehicle_id}/events")
    matching = [
        e for e in listing.json()
        if e["device_id"] == "DEV-DUP" and e["device_event_id"] == "E-DUP-1"
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_duplicate_retry_heals_missing_latest_location_projection(
    client: AsyncClient,
) -> None:
    """Simulates a prior partial failure: vehicle_event was appended
    directly (bypassing the service, so no projection ran), then a retry
    of the exact same (device_id, device_event_id) through the service
    must heal the missing projection using the STORED event."""
    vehicle_id = "VEH-1047"
    component_id = await _component_id(client, vehicle_id)
    repo = get_repository()
    stored = await repo.create_vehicle_event(
        vehicle_id=vehicle_id,
        device_id="DEV-HEAL",
        component_id=component_id,
        event_type=VehicleEventType.ENGINE_START,
        event_time=datetime(2026, 5, 10, tzinfo=timezone.utc),
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=40.0,
        longitude=40.0,
        gps_valid=True,
        note_th=None,
        device_event_id="E-HEAL-1",
        sequence=1,
        created_offline=False,
        time_quality=TimeQuality.TIME_SYNCED,
    )
    assert _current_location(vehicle_id) is None  # projection never ran

    replay = await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-HEAL", device_event_id="E-HEAL-1",
            gps_valid=True, latitude=40.0, longitude=40.0,
            event_time="2026-05-10T00:00:00+00:00",
        ),
    )
    assert replay["event_id"] == stored.event_id

    current = _current_location(vehicle_id)
    assert current is not None
    assert current.latitude == 40.0
    assert current.source_device_id == "DEV-HEAL"


@pytest.mark.asyncio
async def test_duplicate_retry_with_altered_payload_projects_stored_event_not_replay(
    client: AsyncClient,
) -> None:
    vehicle_id = "VEH-1048"
    component_id = await _component_id(client, vehicle_id)
    payload = _payload(
        vehicle_id, component_id, device_id="DEV-ALTER", device_event_id="E-ALTER-1",
        gps_valid=True, latitude=50.0, longitude=50.0,
        event_time="2026-06-01T00:00:00+00:00",
    )
    original = await _create_event(client, payload)

    altered = dict(payload)
    altered["latitude"] = 60.0
    altered["longitude"] = 60.0
    altered["event_time"] = "2026-06-05T00:00:00+00:00"
    replay = await _create_event(client, altered)
    assert replay["event_id"] == original["event_id"]
    assert replay["latitude"] == 50.0  # stored original, not the replay's 60.0

    current = _current_location(vehicle_id)
    assert current is not None
    assert current.latitude == 50.0
    assert current.gps_time == datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_numeric_looking_source_ids_survive_mock_exactly(client: AsyncClient) -> None:
    vehicle_id = "VEH-1046"
    component_id = await _component_id(client, vehicle_id)
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="000009", device_event_id="E-NUM-1",
            gps_valid=True, latitude=1.5, longitude=2.5,
            event_time="2026-07-01T00:00:00+00:00",
        ),
    )
    current = _current_location(vehicle_id)
    assert current is not None
    assert current.source_device_id == "000009"
    assert current.source_device_id != 9  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# GOOGLE SHEETS REPOSITORY (item 16)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_sheets_upsert_appends_when_no_row_exists() -> None:
    ws = _ws(schemas.LATEST_LOCATION_SHEET)
    repo = _repo_with_fake_sheets(ws)

    current = await repo.upsert_current_location(
        vehicle_id="VEH-9001",
        latitude=13.0,
        longitude=100.0,
        gps_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
        source_device_id="DEV-A",
        source_component_id="CMP-0001",
    )
    assert current.vehicle_id == "VEH-9001"
    assert ws.append_row_calls == 1
    assert len(ws.rows) == 1


@pytest.mark.asyncio
async def test_google_sheets_upsert_updates_existing_row_not_a_second_append() -> None:
    ws = _ws(schemas.LATEST_LOCATION_SHEET)
    repo = _repo_with_fake_sheets(ws)

    await repo.upsert_current_location(
        vehicle_id="VEH-9001",
        latitude=13.0,
        longitude=100.0,
        gps_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
        source_device_id="DEV-A",
        source_component_id="CMP-0001",
    )
    updated = await repo.upsert_current_location(
        vehicle_id="VEH-9001",
        latitude=14.0,
        longitude=101.0,
        gps_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 2, 0, 0, 5, tzinfo=timezone.utc),
        source_device_id="DEV-B",
        source_component_id="CMP-0002",
    )
    assert updated.latitude == 14.0
    # Exactly one append (the first creation) - the second call updated
    # the existing row in place, never a second append / full rewrite.
    assert ws.append_row_calls == 1
    assert len(ws.rows) == 1

    reread = await repo.get_current_location("VEH-9001")
    assert reread is not None
    assert reread.latitude == 14.0
    assert reread.source_device_id == "DEV-B"
    assert reread.source_component_id == "CMP-0002"


@pytest.mark.asyncio
async def test_google_sheets_upsert_does_not_touch_other_vehicles_rows() -> None:
    ws = _ws(schemas.LATEST_LOCATION_SHEET)
    repo = _repo_with_fake_sheets(ws)

    await repo.upsert_current_location(
        vehicle_id="VEH-A",
        latitude=1.0,
        longitude=1.0,
        gps_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_device_id="DEV-A",
        source_component_id="CMP-A",
    )
    await repo.upsert_current_location(
        vehicle_id="VEH-B",
        latitude=2.0,
        longitude=2.0,
        gps_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        source_device_id="DEV-B",
        source_component_id="CMP-B",
    )
    assert len(ws.rows) == 2

    veh_a = await repo.get_current_location("VEH-A")
    assert veh_a is not None and veh_a.latitude == 1.0
    veh_b = await repo.get_current_location("VEH-B")
    assert veh_b is not None and veh_b.latitude == 2.0


@pytest.mark.asyncio
async def test_google_sheets_preserves_numeric_looking_source_ids_as_text() -> None:
    ws = _ws(schemas.LATEST_LOCATION_SHEET)
    repo = _repo_with_fake_sheets(ws)

    await repo.upsert_current_location(
        vehicle_id="VEH-9001",
        latitude=13.0,
        longitude=100.0,
        gps_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_device_id="000009",
        source_component_id="000001",
    )

    reread = await repo.get_current_location("VEH-9001")
    assert reread is not None
    assert reread.source_device_id == "000009"
    assert reread.source_device_id != 9  # type: ignore[comparison-overlap]
    assert reread.source_component_id == "000001"
    assert reread.source_component_id != 1  # type: ignore[comparison-overlap]

    headers = schemas.LATEST_LOCATION_SHEET.required_headers
    raw_device = ws.rows[0][headers.index("source_device_id")]
    raw_component = ws.rows[0][headers.index("source_component_id")]
    assert str(raw_device) == "'000009"
    assert str(raw_component) == "'000001"


@pytest.mark.asyncio
async def test_google_sheets_no_row_returns_none_with_seven_column_schema() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.LATEST_LOCATION_SHEET))
    assert await repo.get_current_location("VEH-UNKNOWN") is None


# ---------------------------------------------------------------------------
# READINESS (item 17)
# ---------------------------------------------------------------------------


def test_latest_location_sheet_is_in_core_schemas() -> None:
    assert schemas.LATEST_LOCATION_SHEET in GoogleSheetsRepository._CORE_SCHEMAS


def test_latest_location_sheet_declares_seven_target_columns() -> None:
    assert schemas.LATEST_LOCATION_SHEET.required_headers == (
        "vehicle_id",
        "latitude",
        "longitude",
        "gps_time",
        "received_at",
        "source_device_id",
        "source_component_id",
    )


@pytest.mark.asyncio
async def test_readiness_reports_schema_mismatch_against_old_five_column_live_sheet() -> None:
    """Task I: the live sheet still has only its original 5 headers until
    the separately-authorized migration runs - readiness against that
    shape must honestly report a mismatch, never silently pass."""
    old_shape_ws = FakeWorksheet(
        "latest_location", ("vehicle_id", "latitude", "longitude", "gps_time", "received_at")
    )
    other_ws = [
        _ws(s) for s in GoogleSheetsRepository._CORE_SCHEMAS if s.tab_name != "latest_location"
    ]
    repo = _repo_with_fake_sheets(old_shape_ws, *other_ws)
    ready, reason = await repo.check_ready()
    assert ready is False
    assert reason is not None
    assert "latest_location" in reason


# ---------------------------------------------------------------------------
# MOCK REPOSITORY PARITY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_upsert_current_location_creates_and_updates() -> None:
    repo = MockRepository()
    created = await repo.upsert_current_location(
        vehicle_id="VEH-1046",
        latitude=1.0,
        longitude=2.0,
        gps_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_device_id="DEV-A",
        source_component_id="CMP-A",
    )
    assert created.latitude == 1.0
    fetched = await repo.get_current_location("VEH-1046")
    assert fetched is not None and fetched.latitude == 1.0

    updated = await repo.upsert_current_location(
        vehicle_id="VEH-1046",
        latitude=3.0,
        longitude=4.0,
        gps_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        source_device_id="DEV-B",
        source_component_id="CMP-B",
    )
    assert updated.latitude == 3.0
    fetched_again = await repo.get_current_location("VEH-1046")
    assert fetched_again is not None and fetched_again.latitude == 3.0
