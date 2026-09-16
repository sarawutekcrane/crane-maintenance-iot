"""REV05 governance correction — `MeterService.capture_current_state`/
`LocationService._read_latest_location` must snapshot the AUTHORITATIVE
CURRENT state (`current_counter`/`latest_location`) at event time, never
carry forward a value from prior immutable historical snapshots
(`meter_snapshot`/`location_snapshot`).

Parametrized over MockRepository and GoogleSheetsRepository (FAKE
in-memory `gspread`-shaped client — never the real Google API/network,
see `tests.test_google_sheets_real_io` module docstring and REV05 section
11G).
"""
from __future__ import annotations

import pytest

from app.domain.asset import AssetType
from app.domain.location_snapshot import CurrentLocation, LocationService
from app.domain.meter import CounterType, CurrentCounterReading
from app.domain.meter_service import MeterService
from app.domain.vehicle_model import ComponentRole
from app.repositories.google_sheets import schemas
from app.repositories.mock.repository import MockRepository
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws


def _vehicle_row(vehicle_id: str = "VEH-9001") -> list:
    return [vehicle_id, "MC-9001", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]


def _sheets_repo_with_vehicle_and_component(component_id: str = "COMP-1", vehicle_id: str = "VEH-9001"):
    vehicle_ws = _ws(schemas.VEHICLE_SHEET)
    vehicle_ws.append_row(_vehicle_row(vehicle_id))
    component_ws = _ws(schemas.VEHICLE_COMPONENT_SHEET)
    component_ws.append_row([component_id, vehicle_id, "CARRIER_ENGINE", "Carrier engine"])
    return _repo_with_fake_sheets(
        vehicle_ws,
        component_ws,
        _ws(schemas.METER_SNAPSHOT_SHEET),
        _ws(schemas.METER_READING_SHEET),
        _ws(schemas.LOCATION_SNAPSHOT_SHEET),
        _ws(schemas.CURRENT_COUNTER_SHEET),
        _ws(schemas.LATEST_LOCATION_SHEET),
    )


async def _mock_repo_with_vehicle_and_component():
    from app.domain.vehicle import VehicleComponent

    repo = MockRepository()
    vehicle_id = "VEH-1046"  # already seeded with a CARRIER_ENGINE component
    components = await repo.list_vehicle_components(vehicle_id)
    component_id = next(c.component_id for c in components if c.component_role == ComponentRole.CARRIER_ENGINE)
    return repo, vehicle_id, component_id


async def _sheets_repo_with_vehicle_and_component_async():
    component_id = "COMP-1"
    vehicle_id = "VEH-9001"
    repo = _sheets_repo_with_vehicle_and_component(component_id, vehicle_id)
    return repo, vehicle_id, component_id


def _set_mock_current_counter(repo: MockRepository, vehicle_id: str, readings: list[CurrentCounterReading]) -> None:
    repo._current_counters[vehicle_id] = readings  # type: ignore[attr-defined]


def _set_sheets_current_counter(repo, vehicle_id: str, component_id: str | None, counter_type: CounterType, value) -> None:
    ws = repo._client._spreadsheet.worksheet(schemas.CURRENT_COUNTER_SHEET.tab_name)  # type: ignore[attr-defined]
    ws.rows.clear()
    ws.append_row([vehicle_id, component_id or "", counter_type.value, "" if value is None else str(value)])


def _set_mock_current_location(repo: MockRepository, vehicle_id: str, current: CurrentLocation | None) -> None:
    if current is None:
        repo._current_locations.pop(vehicle_id, None)  # type: ignore[attr-defined]
    else:
        repo._current_locations[vehicle_id] = current  # type: ignore[attr-defined]


def _set_sheets_current_location(repo, vehicle_id: str, latitude, longitude, gps_time: str, received_at: str) -> None:
    ws = repo._client._spreadsheet.worksheet(schemas.LATEST_LOCATION_SHEET.tab_name)  # type: ignore[attr-defined]
    ws.rows.clear()
    ws.append_row(
        [
            vehicle_id,
            "" if latitude is None else str(latitude),
            "" if longitude is None else str(longitude),
            gps_time,
            received_at,
        ]
    )


BACKENDS = ["mock", "sheets"]


async def _make_backend(kind: str):
    if kind == "mock":
        return await _mock_repo_with_vehicle_and_component()
    return await _sheets_repo_with_vehicle_and_component_async()


# ---------------------------------------------------------------------------
# Automatic snapshot uses current_counter, never meter_snapshot history.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
async def test_automatic_snapshot_uses_current_counter_value(backend: str) -> None:
    repo, vehicle_id, component_id = await _make_backend(backend)
    if backend == "mock":
        _set_mock_current_counter(
            repo,
            vehicle_id,
            [CurrentCounterReading(component_id=component_id, counter_type=CounterType.ENGINE_HOUR, value=1234.5)],
        )
    else:
        _set_sheets_current_counter(repo, vehicle_id, component_id, CounterType.ENGINE_HOUR, 1234.5)

    meter_service = MeterService(repo)
    snapshot = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )

    reading = next(r for r in snapshot.readings if r.component_id == component_id)
    assert reading.value == 1234.5


@pytest.mark.parametrize("backend", BACKENDS)
async def test_second_event_uses_new_current_counter_value_not_prior_snapshot(backend: str) -> None:
    """CRITICAL: changing current_counter between two events must cause
    the SECOND automatic snapshot to reflect the NEW value, never the
    first (now-historical) snapshot's value."""
    repo, vehicle_id, component_id = await _make_backend(backend)
    if backend == "mock":
        _set_mock_current_counter(
            repo,
            vehicle_id,
            [CurrentCounterReading(component_id=component_id, counter_type=CounterType.ENGINE_HOUR, value=1000.0)],
        )
    else:
        _set_sheets_current_counter(repo, vehicle_id, component_id, CounterType.ENGINE_HOUR, 1000.0)

    meter_service = MeterService(repo)
    first = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )
    first_reading = next(r for r in first.readings if r.component_id == component_id)
    assert first_reading.value == 1000.0

    # The authoritative current value changes between events (e.g. a new
    # IoT/manual reading updates current_counter).
    if backend == "mock":
        _set_mock_current_counter(
            repo,
            vehicle_id,
            [CurrentCounterReading(component_id=component_id, counter_type=CounterType.ENGINE_HOUR, value=2000.0)],
        )
    else:
        _set_sheets_current_counter(repo, vehicle_id, component_id, CounterType.ENGINE_HOUR, 2000.0)

    second = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )
    second_reading = next(r for r in second.readings if r.component_id == component_id)
    assert second_reading.value == 2000.0
    # The first (now-historical) snapshot's own persisted value is
    # untouched — immutability of history is preserved.
    reread_first = await repo.get_meter_snapshot(first.meter_snapshot_id)
    reread_first_reading = next(r for r in reread_first.readings if r.component_id == component_id)
    assert reread_first_reading.value == 1000.0


@pytest.mark.parametrize("backend", BACKENDS)
async def test_missing_current_counter_does_not_pull_old_snapshot_forward(backend: str) -> None:
    """A prior snapshot recorded a real value; current_counter has since
    gone blank (or was never populated for this dimension) — the next
    automatic snapshot must show None, never the old historical value."""
    repo, vehicle_id, component_id = await _make_backend(backend)
    if backend == "mock":
        _set_mock_current_counter(
            repo,
            vehicle_id,
            [CurrentCounterReading(component_id=component_id, counter_type=CounterType.ENGINE_HOUR, value=1234.5)],
        )
    else:
        _set_sheets_current_counter(repo, vehicle_id, component_id, CounterType.ENGINE_HOUR, 1234.5)

    meter_service = MeterService(repo)
    first = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )
    assert next(r for r in first.readings if r.component_id == component_id).value == 1234.5

    # current_counter is now blank/absent for this dimension.
    if backend == "mock":
        _set_mock_current_counter(repo, vehicle_id, [])
    else:
        _set_sheets_current_counter(repo, vehicle_id, component_id, CounterType.ENGINE_HOUR, None)

    second = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )
    second_reading = next(r for r in second.readings if r.component_id == component_id)
    assert second_reading.value is None
    assert second_reading.observed_at is None


# ---------------------------------------------------------------------------
# Location snapshot uses latest_location, never location_snapshot history.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
async def test_location_snapshot_uses_latest_location(backend: str) -> None:
    repo, vehicle_id, _ = await _make_backend(backend)
    if backend == "mock":
        from datetime import datetime, timezone

        _set_mock_current_location(
            repo,
            vehicle_id,
            CurrentLocation(
                vehicle_id=vehicle_id,
                latitude=13.0,
                longitude=100.0,
                gps_time=datetime(2026, 9, 16, 9, 50, 0, tzinfo=timezone.utc),
                received_at=datetime(2026, 9, 16, 9, 50, 5, tzinfo=timezone.utc),
            ),
        )
    else:
        _set_sheets_current_location(
            repo, vehicle_id, 13.0, 100.0, "2026-09-16T09:50:00+00:00", "2026-09-16T09:50:05+00:00"
        )

    meter_service = MeterService(repo)
    snapshot = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )
    location_service = LocationService(repo)
    locations = await location_service.list_for_event(snapshot.meter_snapshot_id)
    assert len(locations) == 1
    location = locations[0]
    assert location.latitude == 13.0
    assert location.longitude == 100.0
    assert location.gps_time.isoformat() == "2026-09-16T09:50:00+00:00"
    assert location.received_at.isoformat() == "2026-09-16T09:50:05+00:00"
    assert location.gps_valid is True


@pytest.mark.parametrize("backend", BACKENDS)
async def test_changing_latest_location_between_events_uses_the_new_location(backend: str) -> None:
    repo, vehicle_id, _ = await _make_backend(backend)
    if backend == "mock":
        from datetime import datetime, timezone

        _set_mock_current_location(
            repo,
            vehicle_id,
            CurrentLocation(vehicle_id=vehicle_id, latitude=13.0, longitude=100.0),
        )
    else:
        _set_sheets_current_location(repo, vehicle_id, 13.0, 100.0, "", "")

    meter_service = MeterService(repo)
    location_service = LocationService(repo)
    first_snapshot = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )
    first_location = (await location_service.list_for_event(first_snapshot.meter_snapshot_id))[0]
    assert first_location.latitude == 13.0

    if backend == "mock":
        _set_mock_current_location(
            repo,
            vehicle_id,
            CurrentLocation(vehicle_id=vehicle_id, latitude=14.5, longitude=101.5),
        )
    else:
        _set_sheets_current_location(repo, vehicle_id, 14.5, 101.5, "", "")

    second_snapshot = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )
    second_location = (await location_service.list_for_event(second_snapshot.meter_snapshot_id))[0]
    assert second_location.latitude == 14.5
    assert second_location.longitude == 101.5
    # The first event's own location snapshot is immutable/untouched.
    reread_first_location = await location_service.get_snapshot(first_location.location_snapshot_id)
    assert reread_first_location.latitude == 13.0


@pytest.mark.parametrize("backend", BACKENDS)
async def test_missing_latest_location_gives_null_coordinates_and_invalid_gps(backend: str) -> None:
    repo, vehicle_id, _ = await _make_backend(backend)
    # No current-location seeded at all.
    meter_service = MeterService(repo)
    location_service = LocationService(repo)
    snapshot = await meter_service.capture_current_state(
        asset_type=AssetType.VEHICLE, asset_id=vehicle_id, recorded_by="user-1"
    )
    location = (await location_service.list_for_event(snapshot.meter_snapshot_id))[0]
    assert location.latitude is None
    assert location.longitude is None
    assert location.gps_valid is False
