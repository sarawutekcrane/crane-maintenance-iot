"""Web/API Phase 6 Batch 4A — Raw Vehicle Event Foundation + Idempotent
Device Event Ingestion.

Proves the Batch 4A frozen contract (see
`app.domain.vehicle_event`/`app.domain.vehicle_event_service` module
docstrings, restated from the task's own frozen sections):

- event_id is backend-generated (EVT-), device_event_id is device-owned
  and preserved exactly as text
- idempotency identity is exactly (device_id, device_event_id) — a replay
  returns the same stored event, never a second row
- sequence is a required, non-negative, per-device integer; a lower
  sequence than previously received is never rejected
- created_offline/time_quality are required, device-owned metadata,
  never backend-derived
- event_time is required for TIME_SYNCED/TIME_ESTIMATED, optional for
  TIME_NOT_SYNCED, and must be timezone-aware whenever supplied;
  received_at is always backend-generated
- vehicle_id must exist; component_id must exist AND belong to that
  vehicle; device_id is an unvalidated opaque passthrough (no Device
  Master exists yet)
- the create endpoint accepts only the four device-emitted event types;
  DEVICE_ONLINE/DEVICE_OFFLINE are rejected
- GPS fields follow the gps_valid true/false/null combination rules and
  are never derived from coordinate presence
- vehicle_event is raw, append-only history — out-of-order/duplicate-
  looking sequence/event_time is accepted, never rejected or rewritten
- history read order sorts trusted-time events by event_time and places
  untrusted-time events in a separate, explicitly non-chronological,
  deterministic bucket."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.domain.vehicle_event_service import order_for_history
from app.domain.vehicle_event import TimeQuality, VehicleEvent, VehicleEventType
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.mock import MockRepository

from tests.test_google_sheets_real_io import FakeSpreadsheet, FakeWorksheet, _ws


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


async def _component_id(client: AsyncClient, vehicle_id: str) -> str:
    response = await client.get(f"/api/v1/vehicles/{vehicle_id}/components")
    assert response.status_code == 200, response.text
    components = response.json()
    assert components, f"expected seeded components for {vehicle_id}"
    return components[0]["component_id"]


def _payload(vehicle_id: str, component_id: str, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "device_id": "DEV-A",
        "component_id": component_id,
        "event_type": "ENGINE_START",
        "event_time": "2026-01-01T12:00:00+07:00",
        "device_event_id": "E-001",
        "sequence": 1,
        "created_offline": False,
        "time_quality": "TIME_SYNCED",
    }
    payload.update(overrides)
    return payload


async def _create_event(client: AsyncClient, payload: dict) -> dict:
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# DUPLICATE / IDEMPOTENCY (section 23)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_event_returns_evt_prefixed_id(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    event = await _create_event(client, _payload("VEH-1046", component_id))
    assert event["event_id"].startswith("EVT-")
    assert event["vehicle_id"] == "VEH-1046"
    assert event["device_event_id"] == "E-001"


@pytest.mark.asyncio
async def test_replay_same_device_and_device_event_id_returns_same_event_no_new_row(
    client: AsyncClient,
) -> None:
    """Item A+B: create once, replay the identical (device_id,
    device_event_id) pair -> same event_id, no second row created."""
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, device_id="DEV-A", device_event_id="E-001")
    first = await _create_event(client, payload)

    replay = await _create_event(client, payload)
    assert replay["event_id"] == first["event_id"]

    listing = await client.get("/api/v1/vehicles/VEH-1046/events")
    assert listing.status_code == 200, listing.text
    matching = [e for e in listing.json() if e["device_id"] == "DEV-A" and e["device_event_id"] == "E-001"]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_replay_with_different_payload_still_returns_original_stored_event(
    client: AsyncClient,
) -> None:
    """A replay of an already-accepted (device_id, device_event_id) pair
    returns the stored row unchanged — it never re-validates or applies a
    different payload sent on the replay attempt."""
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, device_id="DEV-A", device_event_id="E-001")
    first = await _create_event(client, payload)

    replay_payload = dict(payload)
    replay_payload["sequence"] = 999
    replay_payload["event_type"] = "PTO_ON"
    replay = await _create_event(client, replay_payload)
    assert replay["event_id"] == first["event_id"]
    assert replay["sequence"] == first["sequence"]
    assert replay["event_type"] == first["event_type"]


@pytest.mark.asyncio
async def test_same_device_event_id_on_different_devices_creates_two_events(
    client: AsyncClient,
) -> None:
    """Item C."""
    component_id = await _component_id(client, "VEH-1046")
    event_a = await _create_event(
        client, _payload("VEH-1046", component_id, device_id="DEV-A", device_event_id="E-001")
    )
    event_b = await _create_event(
        client, _payload("VEH-1046", component_id, device_id="DEV-B", device_event_id="E-001")
    )
    assert event_a["event_id"] != event_b["event_id"]


@pytest.mark.asyncio
async def test_same_device_different_device_event_id_creates_two_events(
    client: AsyncClient,
) -> None:
    """Item D."""
    component_id = await _component_id(client, "VEH-1046")
    event_1 = await _create_event(
        client, _payload("VEH-1046", component_id, device_id="DEV-A", device_event_id="E-001")
    )
    event_2 = await _create_event(
        client, _payload("VEH-1046", component_id, device_id="DEV-A", device_event_id="E-002")
    )
    assert event_1["event_id"] != event_2["event_id"]


# ---------------------------------------------------------------------------
# VALIDATION (section 24)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_vehicle_is_not_found(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-NOPE", component_id)
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


@pytest.mark.asyncio
async def test_nonexistent_component_is_rejected(client: AsyncClient) -> None:
    payload = _payload("VEH-1046", "CMP-DOES-NOT-EXIST")
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_COMPONENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_component_belonging_to_different_vehicle_is_rejected(client: AsyncClient) -> None:
    other_vehicle_component_id = await _component_id(client, "VEH-1047")
    payload = _payload("VEH-1046", other_vehicle_component_id)
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_COMPONENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_blank_device_id_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, device_id="   ")
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_DEVICE_ID_REQUIRED"


@pytest.mark.asyncio
async def test_blank_device_event_id_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, device_event_id="")
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_DEVICE_EVENT_ID_REQUIRED"


@pytest.mark.asyncio
async def test_negative_sequence_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, sequence=-1)
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_invalid_event_type_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, event_type="NOT_A_REAL_EVENT_TYPE")
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_device_online_rejected_by_post(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, event_type="DEVICE_ONLINE")
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_device_offline_rejected_by_post(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, event_type="DEVICE_OFFLINE")
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_invalid_time_quality_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, time_quality="NOT_A_REAL_QUALITY")
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_time_synced_with_null_event_time_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, time_quality="TIME_SYNCED", event_time=None)
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_TIME_REQUIRED_FOR_TIME_QUALITY"


@pytest.mark.asyncio
async def test_time_estimated_with_null_event_time_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, time_quality="TIME_ESTIMATED", event_time=None)
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_TIME_REQUIRED_FOR_TIME_QUALITY"


@pytest.mark.asyncio
async def test_time_not_synced_with_null_event_time_accepted(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046",
        component_id,
        device_event_id="E-TNS-1",
        time_quality="TIME_NOT_SYNCED",
        event_time=None,
    )
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["event_time"] is None


@pytest.mark.asyncio
async def test_naive_event_time_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id, event_time="2026-01-01T12:00:00")
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_TIME_NOT_TIMEZONE_AWARE"


@pytest.mark.asyncio
async def test_event_time_normalized_to_utc_convention(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046",
        component_id,
        device_event_id="E-TZ-1",
        event_time="2026-01-01T12:00:00+07:00",
    )
    event = await _create_event(client, payload)
    returned = datetime.fromisoformat(event["event_time"])
    assert returned == datetime(2026, 1, 1, 5, 0, 0, tzinfo=timezone.utc)
    assert returned.utcoffset() == timezone.utc.utcoffset(None)


@pytest.mark.asyncio
async def test_client_supplied_event_id_forbidden(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id)
    payload["event_id"] = "EVT-9999"
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_client_supplied_received_at_forbidden(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id)
    payload["received_at"] = "2026-01-01T00:00:00+00:00"
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_unknown_request_field_forbidden(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload("VEH-1046", component_id)
    payload["some_unexpected_field"] = "x"
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# GPS (section 25)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gps_all_null_accepted(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, device_event_id="E-GPS-1",
        gps_valid=None, latitude=None, longitude=None,
    )
    event = await _create_event(client, payload)
    assert event["gps_valid"] is None
    assert event["latitude"] is None
    assert event["longitude"] is None


@pytest.mark.asyncio
async def test_gps_valid_true_with_coordinates_accepted(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, device_event_id="E-GPS-2",
        gps_valid=True, latitude=13.7563, longitude=100.5018,
    )
    event = await _create_event(client, payload)
    assert event["gps_valid"] is True
    assert event["latitude"] == 13.7563
    assert event["longitude"] == 100.5018


@pytest.mark.asyncio
async def test_gps_valid_true_missing_latitude_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, gps_valid=True, latitude=None, longitude=100.5018,
    )
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_GPS_COORDINATES_REQUIRED"


@pytest.mark.asyncio
async def test_gps_valid_true_missing_longitude_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, gps_valid=True, latitude=13.7563, longitude=None,
    )
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_GPS_COORDINATES_REQUIRED"


@pytest.mark.asyncio
async def test_invalid_latitude_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, gps_valid=True, latitude=200.0, longitude=100.5018,
    )
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_invalid_longitude_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, gps_valid=True, latitude=13.7563, longitude=200.0,
    )
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_gps_valid_false_with_coordinates_accepted_as_raw_evidence(
    client: AsyncClient,
) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, device_event_id="E-GPS-3",
        gps_valid=False, latitude=13.7563, longitude=100.5018,
    )
    event = await _create_event(client, payload)
    assert event["gps_valid"] is False
    assert event["latitude"] == 13.7563
    assert event["longitude"] == 100.5018


@pytest.mark.asyncio
async def test_gps_valid_false_with_null_coordinates_accepted(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, device_event_id="E-GPS-4",
        gps_valid=False, latitude=None, longitude=None,
    )
    event = await _create_event(client, payload)
    assert event["gps_valid"] is False
    assert event["latitude"] is None
    assert event["longitude"] is None


@pytest.mark.asyncio
async def test_gps_valid_null_with_coordinates_rejected(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, gps_valid=None, latitude=13.7563, longitude=100.5018,
    )
    response = await client.post("/api/v1/vehicle-events", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VEHICLE_EVENT_GPS_COORDINATES_MUST_BE_NULL"


@pytest.mark.asyncio
async def test_gps_fields_round_trip(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    payload = _payload(
        "VEH-1046", component_id, device_event_id="E-GPS-5",
        gps_valid=True, latitude=13.75, longitude=100.5,
    )
    created = await _create_event(client, payload)
    fetched = await client.get(f"/api/v1/vehicle-events/{created['event_id']}")
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["gps_valid"] is True
    assert body["latitude"] == 13.75
    assert body["longitude"] == 100.5


# ---------------------------------------------------------------------------
# OUT-OF-ORDER (section 27)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_older_event_time_than_already_stored_is_still_accepted(
    client: AsyncClient,
) -> None:
    component_id = await _component_id(client, "VEH-1046")
    await _create_event(
        client,
        _payload(
            "VEH-1046", component_id, device_event_id="E-OOO-1",
            sequence=5, event_time="2026-01-05T00:00:00+00:00",
        ),
    )
    delayed = await _create_event(
        client,
        _payload(
            "VEH-1046", component_id, device_event_id="E-OOO-2",
            sequence=1, event_time="2026-01-01T00:00:00+00:00",
        ),
    )
    assert delayed["event_time"] is not None


@pytest.mark.asyncio
async def test_lower_sequence_than_already_stored_is_still_accepted(client: AsyncClient) -> None:
    component_id = await _component_id(client, "VEH-1046")
    await _create_event(
        client,
        _payload("VEH-1046", component_id, device_event_id="E-SEQ-1", sequence=10),
    )
    still_accepted = await _create_event(
        client,
        _payload("VEH-1046", component_id, device_event_id="E-SEQ-2", sequence=1),
    )
    assert still_accepted["sequence"] == 1


@pytest.mark.asyncio
async def test_history_read_order_sorts_trusted_time_events_and_isolates_untrusted_bucket(
    client: AsyncClient,
) -> None:
    vehicle_id = "VEH-1048"  # dedicated vehicle, avoids cross-test interference
    component_id = await _component_id(client, vehicle_id)

    older = await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_event_id="E-ORDER-OLD",
            device_id="DEV-ORDER", sequence=1, event_time="2026-01-01T00:00:00+00:00",
        ),
    )
    newer = await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_event_id="E-ORDER-NEW",
            device_id="DEV-ORDER", sequence=2, event_time="2026-01-05T00:00:00+00:00",
        ),
    )
    untrusted = await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_event_id="E-ORDER-UNTRUSTED",
            device_id="DEV-ORDER", sequence=3, time_quality="TIME_NOT_SYNCED", event_time=None,
        ),
    )

    response = await client.get(f"/api/v1/vehicles/{vehicle_id}/events")
    assert response.status_code == 200, response.text
    ids = [e["event_id"] for e in response.json()]

    # Trusted-time bucket (event_time non-null, TIME_SYNCED) is newest
    # first, and entirely precedes the untrusted bucket.
    assert ids.index(newer["event_id"]) < ids.index(older["event_id"])
    assert ids.index(older["event_id"]) < ids.index(untrusted["event_id"])


def _mk_event(
    event_id: str,
    device_id: str,
    sequence: int,
    time_quality: TimeQuality,
    event_time,
    received_at,
) -> VehicleEvent:
    return VehicleEvent(
        event_id=event_id,
        vehicle_id="VEH-1046",
        device_id=device_id,
        component_id="CMP-0001",
        event_type=VehicleEventType.ENGINE_START,
        event_time=event_time,
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=None,
        longitude=None,
        gps_valid=None,
        received_at=received_at,
        note_th=None,
        device_event_id=f"DEVEVT-{event_id}",
        sequence=sequence,
        created_offline=False,
        time_quality=time_quality,
    )


def test_order_for_history_never_compares_sequence_across_devices() -> None:
    """Unit-level proof for `order_for_history`: two different devices'
    untrusted-time events are grouped by device_id first — a device with
    a numerically larger sequence never gets sorted purely by that
    sequence across a different device's rows."""
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    device_b_first = _mk_event(
        "EVT-B1", "DEV-B", 1, TimeQuality.TIME_NOT_SYNCED, None, epoch
    )
    device_a_high_seq = _mk_event(
        "EVT-A9", "DEV-A", 9, TimeQuality.TIME_NOT_SYNCED, None, epoch
    )
    ordered = order_for_history([device_b_first, device_a_high_seq])
    # Grouped by device_id first (DEV-A < DEV-B lexicographically), never
    # a flat cross-device sequence comparison that would put DEV-B first
    # here if 1 < 9 were compared globally in the wrong grouping.
    assert [e.event_id for e in ordered] == ["EVT-A9", "EVT-B1"]


def test_order_for_history_trusted_bucket_precedes_untrusted_bucket() -> None:
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trusted = _mk_event(
        "EVT-T1", "DEV-A", 1, TimeQuality.TIME_SYNCED, epoch, epoch
    )
    untrusted = _mk_event(
        "EVT-U1", "DEV-A", 2, TimeQuality.TIME_NOT_SYNCED, None, epoch
    )
    ordered = order_for_history([untrusted, trusted])
    assert [e.event_id for e in ordered] == ["EVT-T1", "EVT-U1"]


# ---------------------------------------------------------------------------
# GOOGLE SHEETS — text preservation + idempotency plumbing (section 26,
# mirrors the Batch 3B `note_th` regression-test pattern exactly)
# ---------------------------------------------------------------------------


def _ws_for_vehicle_event() -> FakeWorksheet:
    return _ws(schemas.VEHICLE_EVENT_SHEET)


@pytest.mark.asyncio
async def test_google_sheets_preserves_numeric_looking_identifiers_as_text() -> None:
    """Regression coverage mirroring Batch 3B's `note_th` fix: every
    numeric-looking opaque identifier (`device_event_id`, `device_id`,
    `note_th`) must round-trip as exact text, never coerced to a number
    by gspread's own client-side `numericise_all()`."""
    ws = _ws_for_vehicle_event()
    repo = _repo_with_fake_sheets(ws)

    created = await repo.create_vehicle_event(
        vehicle_id="VEH-1046",
        device_id="000009",
        component_id="CMP-0001",
        event_type=VehicleEventType.ENGINE_START,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=None,
        longitude=None,
        gps_valid=None,
        note_th="001",
        device_event_id="000001",
        sequence=1,
        created_offline=False,
        time_quality=TimeQuality.TIME_SYNCED,
    )
    assert created.device_id == "000009"
    assert created.device_event_id == "000001"
    assert created.note_th == "001"

    reread = await repo.get_vehicle_event(created.event_id)
    assert reread is not None
    assert reread.device_id == "000009"
    assert reread.device_id != 9  # type: ignore[comparison-overlap]
    assert reread.device_event_id == "000001"
    assert reread.device_event_id != 1  # type: ignore[comparison-overlap]
    assert reread.note_th == "001"
    assert reread.note_th != 1  # type: ignore[comparison-overlap]

    headers = schemas.VEHICLE_EVENT_SHEET.required_headers
    raw_device_id = ws.rows[0][headers.index("device_id")]
    raw_device_event_id = ws.rows[0][headers.index("device_event_id")]
    raw_note_th = ws.rows[0][headers.index("note_th")]
    assert str(raw_device_id) == "'000009"
    assert str(raw_device_event_id) == "'000001"
    assert str(raw_note_th) == "'001"


@pytest.mark.asyncio
async def test_google_sheets_find_by_device_event_matches_existing_row() -> None:
    ws = _ws_for_vehicle_event()
    repo = _repo_with_fake_sheets(ws)

    created = await repo.create_vehicle_event(
        vehicle_id="VEH-1046",
        device_id="DEV-A",
        component_id="CMP-0001",
        event_type=VehicleEventType.PTO_ON,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=None,
        longitude=None,
        gps_valid=None,
        note_th=None,
        device_event_id="E-100",
        sequence=1,
        created_offline=True,
        time_quality=TimeQuality.TIME_ESTIMATED,
    )

    found = await repo.find_vehicle_event_by_device_event(
        device_id="DEV-A", device_event_id="E-100"
    )
    assert found is not None
    assert found.event_id == created.event_id

    missing = await repo.find_vehicle_event_by_device_event(
        device_id="DEV-A", device_event_id="E-999"
    )
    assert missing is None

    assert ws.append_row_calls == 1


@pytest.mark.asyncio
async def test_google_sheets_sequence_and_created_offline_stay_genuine_types() -> None:
    """sequence/created_offline are genuine int/bool columns — never in
    `_VEHICLE_EVENT_TEXT_ONLY_HEADERS` — so a numeric-looking sequence is
    read back as a real int, and created_offline round-trips as a real
    bool, not text."""
    ws = _ws_for_vehicle_event()
    repo = _repo_with_fake_sheets(ws)

    created = await repo.create_vehicle_event(
        vehicle_id="VEH-1046",
        device_id="DEV-A",
        component_id="CMP-0001",
        event_type=VehicleEventType.ENGINE_STOP,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=None,
        longitude=None,
        gps_valid=None,
        note_th=None,
        device_event_id="E-200",
        sequence=7,
        created_offline=True,
        time_quality=TimeQuality.TIME_SYNCED,
    )
    assert created.sequence == 7
    assert created.created_offline is True

    reread = await repo.get_vehicle_event(created.event_id)
    assert reread is not None
    assert reread.sequence == 7
    assert isinstance(reread.sequence, int)
    assert reread.created_offline is True
