"""REV05 governance correction — `current_counter`/`latest_location` are
the authoritative CURRENT-state sheets and must actually be read.

These tests exercise the new `Repository.list_current_counters`/
`Repository.get_current_location` methods directly — the repository-level
read contract, independent of `MeterService`/`LocationService`'s own
consumption of them (see `test_meter_service_authoritative_current_state.py`
for that). GoogleSheetsRepository tests use the FAKE in-memory
`gspread`-shaped client from `tests.test_google_sheets_real_io` (never the
real Google API/network — see that module's docstring and REV05 section
11G).
"""
from __future__ import annotations

import pytest

from app.domain.meter import CounterType, CurrentCounterReading
from app.domain.location_snapshot import CurrentLocation
from app.repositories.google_sheets import schemas
from app.repositories.mock.repository import MockRepository
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws


# ---------------------------------------------------------------------------
# GoogleSheetsRepository.list_current_counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sheets_reads_engine_hour_numeric_value_with_component_id() -> None:
    counter_ws = _ws(schemas.CURRENT_COUNTER_SHEET)
    counter_ws.append_row(["UAT-VEH-001", "UAT-COMP-001", "ENGINE_HOUR", "1234.5"])
    repo = _repo_with_fake_sheets(counter_ws)

    readings = await repo.list_current_counters("UAT-VEH-001")

    assert len(readings) == 1
    assert readings[0].component_id == "UAT-COMP-001"
    assert readings[0].counter_type == CounterType.ENGINE_HOUR
    assert readings[0].value == 1234.5


@pytest.mark.asyncio
async def test_sheets_reads_odometer_with_blank_component_id_as_none() -> None:
    counter_ws = _ws(schemas.CURRENT_COUNTER_SHEET)
    counter_ws.append_row(["UAT-VEH-001", "", "ODOMETER", "56789"])
    repo = _repo_with_fake_sheets(counter_ws)

    readings = await repo.list_current_counters("UAT-VEH-001")

    assert len(readings) == 1
    assert readings[0].component_id is None
    assert readings[0].counter_type == CounterType.ODOMETER
    assert readings[0].value == 56789.0


@pytest.mark.asyncio
async def test_sheets_missing_value_remains_none_not_zero() -> None:
    counter_ws = _ws(schemas.CURRENT_COUNTER_SHEET)
    counter_ws.append_row(["UAT-VEH-001", "UAT-COMP-001", "ENGINE_HOUR", ""])
    repo = _repo_with_fake_sheets(counter_ws)

    readings = await repo.list_current_counters("UAT-VEH-001")

    assert len(readings) == 1
    assert readings[0].value is None


@pytest.mark.asyncio
async def test_sheets_current_counters_filters_by_vehicle_id() -> None:
    counter_ws = _ws(schemas.CURRENT_COUNTER_SHEET)
    counter_ws.append_row(["UAT-VEH-001", "UAT-COMP-001", "ENGINE_HOUR", "1234.5"])
    counter_ws.append_row(["VEH-OTHER", "COMP-OTHER", "ENGINE_HOUR", "999"])
    repo = _repo_with_fake_sheets(counter_ws)

    readings = await repo.list_current_counters("UAT-VEH-001")

    assert len(readings) == 1
    assert readings[0].value == 1234.5


@pytest.mark.asyncio
async def test_sheets_no_current_counter_row_returns_empty_list_honestly() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.CURRENT_COUNTER_SHEET))

    readings = await repo.list_current_counters("VEH-UNKNOWN")

    assert readings == []


# ---------------------------------------------------------------------------
# GoogleSheetsRepository.get_current_location
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sheets_reads_latest_location_coordinates_and_timestamps() -> None:
    location_ws = _ws(schemas.LATEST_LOCATION_SHEET)
    location_ws.append_row(
        ["UAT-VEH-001", "13", "100", "2026-09-16T09:50:00+00:00", "2026-09-16T09:50:05+00:00"]
    )
    repo = _repo_with_fake_sheets(location_ws)

    current = await repo.get_current_location("UAT-VEH-001")

    assert current is not None
    assert current.latitude == 13.0
    assert current.longitude == 100.0
    assert current.gps_time.isoformat() == "2026-09-16T09:50:00+00:00"
    assert current.received_at.isoformat() == "2026-09-16T09:50:05+00:00"


@pytest.mark.asyncio
async def test_sheets_no_latest_location_row_returns_none_honestly() -> None:
    repo = _repo_with_fake_sheets(_ws(schemas.LATEST_LOCATION_SHEET))

    current = await repo.get_current_location("VEH-UNKNOWN")

    assert current is None


# ---------------------------------------------------------------------------
# MockRepository parity — same contract, in-memory backing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_list_current_counters_returns_seeded_readings() -> None:
    repo = MockRepository()
    repo._current_counters["UAT-VEH-001"] = [  # type: ignore[attr-defined]
        CurrentCounterReading(component_id="UAT-COMP-001", counter_type=CounterType.ENGINE_HOUR, value=1234.5),
        CurrentCounterReading(component_id=None, counter_type=CounterType.ODOMETER, value=56789.0),
    ]

    readings = await repo.list_current_counters("UAT-VEH-001")
    assert {r.counter_type for r in readings} == {CounterType.ENGINE_HOUR, CounterType.ODOMETER}
    odometer = next(r for r in readings if r.counter_type == CounterType.ODOMETER)
    assert odometer.component_id is None


@pytest.mark.asyncio
async def test_mock_no_current_counter_seeded_returns_empty_list() -> None:
    repo = MockRepository()
    assert await repo.list_current_counters("VEH-UNSEEDED") == []


@pytest.mark.asyncio
async def test_mock_get_current_location_returns_seeded_entry_or_none() -> None:
    from datetime import datetime, timezone

    repo = MockRepository()
    assert await repo.get_current_location("VEH-UNSEEDED") is None

    repo._current_locations["UAT-VEH-001"] = CurrentLocation(  # type: ignore[attr-defined]
        vehicle_id="UAT-VEH-001",
        latitude=13.0,
        longitude=100.0,
        gps_time=datetime(2026, 9, 16, 9, 50, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 9, 16, 9, 50, 5, tzinfo=timezone.utc),
    )
    current = await repo.get_current_location("UAT-VEH-001")
    assert current is not None
    assert current.latitude == 13.0
    assert current.longitude == 100.0
