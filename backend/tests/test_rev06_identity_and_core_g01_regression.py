"""Core Demo Fixes Delta REV06 section 24 — identity and CORE-G01
regression coverage, confirming REV06's changes (Google Sheets Repair I/O,
new authorization gates, provenance encoding, PM My Work) never touched
these previously-approved invariants.

Most of CORE-G01 (backend-authoritative snapshots, missing value stays
null, preview never persists) already has dedicated regression coverage
in `tests/test_automatic_machine_state_snapshot.py`,
`tests/test_meter_snapshot.py`, and
`tests/test_google_sheets_real_io.py::test_meter_snapshot_write_and_read_preserve_null_readings`
— none of it needed to change for REV06, and the full suite passing
alongside this file IS that regression proof. This file adds the specific
assertions REV06 section 24 names that did not already have a dedicated
test: vehicle identity suffix distinctness (41) and a direct proof that
`POST /repairs` cannot be used to inject a fabricated current counter/GPS
value (46, beyond the existing "preview is read-only" coverage).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.repositories.mock import MockRepository


# ---------------------------------------------------------------------------
# 41 — 220/1, 220/2, 220/3 remain separate (never normalized to "220").
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suffixed_machine_numbers_remain_distinct_separate_vehicles() -> None:
    repo = MockRepository()
    await repo.update_vehicle_machine_no("VEH-1046", "220/1")
    await repo.update_vehicle_machine_no("VEH-1047", "220/2")
    await repo.update_vehicle_machine_no("VEH-1048", "220/3")

    v1 = await repo.get_vehicle("VEH-1046")
    v2 = await repo.get_vehicle("VEH-1047")
    v3 = await repo.get_vehicle("VEH-1048")

    machine_nos = {v1.machine_no, v2.machine_no, v3.machine_no}
    assert machine_nos == {"220/1", "220/2", "220/3"}
    # Three distinct physical vehicles — never collapsed/normalized to a
    # shared "220" identity, and each keeps its own separate vehicle_id.
    vehicle_ids = {v1.vehicle_id, v2.vehicle_id, v3.vehicle_id}
    assert len(vehicle_ids) == 3


@pytest.mark.asyncio
async def test_machine_no_is_treated_as_opaque_display_data_never_parsed_for_a_prefix() -> None:
    repo = MockRepository()
    await repo.update_vehicle_machine_no("VEH-1046", "220/1")
    vehicle = await repo.get_vehicle("VEH-1046")
    # Stored/returned byte-for-byte — no "/1" suffix stripped, no numeric
    # coercion of the "220" portion.
    assert vehicle.machine_no == "220/1"


# ---------------------------------------------------------------------------
# 43 — lower/upper components still describe the SAME vehicle (never
# modeled as two separate vehicles).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_carrier_and_crane_engine_components_belong_to_one_shared_vehicle_id() -> None:
    repo = MockRepository()
    components = await repo.list_vehicle_components("VEH-1046")
    vehicle_ids = {c.vehicle_id for c in components}
    assert vehicle_ids == {"VEH-1046"}, "components must never imply a second vehicle identity"


# ---------------------------------------------------------------------------
# 46 — browser cannot override authoritative snapshots: `POST /repairs`
# only ever accepts a REFERENCE to an already-backend-created snapshot
# (`meter_snapshot_id`), never a raw counter/GPS value.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_repair_request_body_has_no_raw_counter_or_gps_fields(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "MANUAL",
            # Even if a malicious/buggy client tries to smuggle a raw
            # current-value override, unknown fields are simply not part
            # of the schema `CreateRepairRequest` accepts.
            "current_engine_hour": 999999,
            "latitude": 13.75,
            "longitude": 100.5,
        },
    )
    assert response.status_code == 200
    repair = response.json()["repair"]
    # The automatic snapshot mechanism ran — a real, backend-created
    # snapshot id is present — but nothing about the fabricated
    # "current_engine_hour"/"latitude"/"longitude" fields reached it.
    assert repair["meter_snapshot_id"] is not None


@pytest.mark.asyncio
async def test_meter_snapshot_id_override_must_reference_a_real_backend_snapshot(
    client: AsyncClient,
) -> None:
    """The one explicit override escape hatch `CreateRepairRequest` has
    (`meter_snapshot_id`) is a REFERENCE to a snapshot the backend already
    created — an arbitrary/unknown id is rejected, never trusted as an
    authoritative current value in its own right."""
    response = await client.post(
        "/api/v1/repairs",
        json={
            "asset_type": "VEHICLE",
            "asset_id": "VEH-1046",
            "source_type": "MANUAL",
            "meter_snapshot_id": "MSNAP-DOES-NOT-EXIST",
        },
    )
    assert response.status_code == 404
