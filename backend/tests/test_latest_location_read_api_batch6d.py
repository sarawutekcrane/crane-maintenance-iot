"""Web/API Phase 6 Batch 6D — Latest Location Read API.

Proves the frozen Batch 6D contract for the new read-only
`GET /vehicles/{vehicle_id}/latest-location` endpoint:

- exactly the 7 verified live `latest_location` D12 columns are returned
  (never `gps_valid`/`altitude`/`accuracy`/`event_id`/`updated_at`)
- an unknown vehicle raises the existing controlled `VEHICLE_NOT_FOUND`
  (404), distinct from a known vehicle with no current-location row
  (200 + JSON `null` — never fabricated `0, 0`)
- the endpoint never derives current location from `location_snapshot`
  history, and never writes anything (`latest_location` untouched by a
  GET)
- opaque numeric-looking source columns (e.g. "000009") survive as
  strings, never coerced to a number

Uses the same `get_repository()` MockRepository-singleton-seeding
technique already established by
`tests.test_latest_location_projection_batch4b`/
`tests.test_current_counter_and_latest_location_reads`."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.dependencies import get_repository
from app.domain.location_snapshot import CurrentLocation

VEHICLE_ID = "VEH-1046"


def _seed_current_location(**overrides) -> CurrentLocation:
    repo = get_repository()
    defaults = dict(
        vehicle_id=VEHICLE_ID,
        latitude=13.75,
        longitude=100.50,
        gps_time=datetime(2026, 9, 16, 9, 50, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 9, 16, 9, 50, 5, tzinfo=timezone.utc),
        source_device_id="DEV-A",
        source_component_id="CMP-0001",
    )
    defaults.update(overrides)
    entry = CurrentLocation(**defaults)
    repo._current_locations[VEHICLE_ID] = entry  # type: ignore[attr-defined]
    return entry


# ---------------------------------------------------------------------------
# HAPPY PATH — items 1-7
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_vehicle_with_current_row_returns_200(client: AsyncClient) -> None:
    _seed_current_location()
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_response_contains_exactly_the_seven_fields(client: AsyncClient) -> None:
    _seed_current_location()
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    body = response.json()
    assert set(body.keys()) == {
        "vehicle_id",
        "latitude",
        "longitude",
        "gps_time",
        "received_at",
        "source_device_id",
        "source_component_id",
    }


@pytest.mark.asyncio
async def test_latitude_longitude_preserved_exactly(client: AsyncClient) -> None:
    _seed_current_location(latitude=13.75, longitude=100.50)
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    body = response.json()
    assert body["latitude"] == 13.75
    assert body["longitude"] == 100.50


@pytest.mark.asyncio
async def test_gps_time_preserved_separately_from_received_at(client: AsyncClient) -> None:
    _seed_current_location(
        gps_time=datetime(2026, 9, 16, 9, 50, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 9, 16, 9, 55, 30, tzinfo=timezone.utc),
    )
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    body = response.json()
    assert body["gps_time"] != body["received_at"]
    assert datetime.fromisoformat(body["gps_time"]) == datetime(
        2026, 9, 16, 9, 50, 0, tzinfo=timezone.utc
    )
    assert datetime.fromisoformat(body["received_at"]) == datetime(
        2026, 9, 16, 9, 55, 30, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_source_device_id_and_component_id_preserved_exactly(
    client: AsyncClient,
) -> None:
    _seed_current_location(source_device_id="DEV-XYZ", source_component_id="CMP-XYZ")
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    body = response.json()
    assert body["source_device_id"] == "DEV-XYZ"
    assert body["source_component_id"] == "CMP-XYZ"


@pytest.mark.asyncio
async def test_numeric_looking_source_device_id_stays_a_string(client: AsyncClient) -> None:
    _seed_current_location(source_device_id="000009", source_component_id="000001")
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    body = response.json()
    assert body["source_device_id"] == "000009"
    assert isinstance(body["source_device_id"], str)
    assert body["source_component_id"] == "000001"
    assert isinstance(body["source_component_id"], str)


# ---------------------------------------------------------------------------
# NOT-FOUND / NO-DATA SEMANTICS — items 9-10
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_vehicle_with_no_current_row_returns_200_null(
    client: AsyncClient,
) -> None:
    # VEH-1046 exists (seeded vehicle master) but no current_location row
    # was ever seeded/written in this test.
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    assert response.status_code == 200, response.text
    assert response.json() is None


@pytest.mark.asyncio
async def test_unknown_vehicle_returns_404_vehicle_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-DOES-NOT-EXIST/latest-location")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


# ---------------------------------------------------------------------------
# READ-ONLY / NO-DERIVATION GUARANTEES — items 11-14
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_performs_no_write(client: AsyncClient) -> None:
    repo = get_repository()
    assert VEHICLE_ID not in repo._current_locations  # type: ignore[attr-defined]
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    assert response.status_code == 200
    assert response.json() is None
    # A GET must never create a row where none existed.
    assert VEHICLE_ID not in repo._current_locations  # type: ignore[attr-defined]

    _seed_current_location(latitude=1.0, longitude=2.0)
    before = repo._current_locations[VEHICLE_ID].model_copy(deep=True)  # type: ignore[attr-defined]
    await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    after = repo._current_locations[VEHICLE_ID]  # type: ignore[attr-defined]
    assert after == before


@pytest.mark.asyncio
async def test_endpoint_never_falls_back_to_location_snapshot_history(
    client: AsyncClient,
) -> None:
    """A `location_snapshot` existing for the vehicle must never be used
    to fabricate a current-location response when no `latest_location`
    row exists — the endpoint returns honest `null`, not an old
    historical capture."""
    repo = get_repository()
    await repo.create_location_snapshot(
        event_type="REPAIR_OPEN",
        event_id="MS-6D-1",
        vehicle_id=VEHICLE_ID,
        device_id=None,
        latitude=99.0,
        longitude=99.0,
        altitude_m=None,
        accuracy_m=None,
        gps_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        gps_valid=True,
        source=None,
    )
    assert VEHICLE_ID not in repo._current_locations  # type: ignore[attr-defined]

    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.asyncio
async def test_response_has_no_gps_valid_field(client: AsyncClient) -> None:
    _seed_current_location()
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    assert "gps_valid" not in response.json()


@pytest.mark.asyncio
async def test_response_has_no_altitude_or_accuracy_fields(client: AsyncClient) -> None:
    _seed_current_location()
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/latest-location")
    body = response.json()
    assert "altitude_m" not in body
    assert "altitude" not in body
    assert "accuracy_m" not in body
    assert "accuracy" not in body
