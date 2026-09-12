"""Component Role Naming Correction — approved decision proof.

Approved vocabulary (see OPEN_DECISIONS_REGISTER_EN.txt and
docs/phase-results/component-role-naming-correction.md):

    CARRIER_ENGINE, CRANE_ENGINE, PTO

`ENGINE_MAIN` / `ENGINE_SECONDARY` are deprecated legacy names and are no
longer valid `ComponentRole` values. There is no legacy-input compatibility
path: no write endpoint accepts a client-supplied `component_role`, and no
historical/persisted record ever stored the old names (Phase 1-3 use only
in-memory `MockRepository` seed data), so a direct rename is the correct,
minimal fix rather than a permanent dual vocabulary.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.api.v1.vehicle_schemas import VehicleComponentResponse
from app.domain.vehicle_model import ComponentRole

_NOW = "2026-01-15T08:00:00Z"


def test_carrier_engine_is_accepted() -> None:
    assert ComponentRole("CARRIER_ENGINE") is ComponentRole.CARRIER_ENGINE


def test_crane_engine_is_accepted() -> None:
    assert ComponentRole("CRANE_ENGINE") is ComponentRole.CRANE_ENGINE


def test_pto_remains_accepted() -> None:
    assert ComponentRole("PTO") is ComponentRole.PTO


def test_engine_main_is_rejected_for_new_authoritative_writes() -> None:
    with pytest.raises(ValueError):
        ComponentRole("ENGINE_MAIN")

    with pytest.raises(ValidationError):
        VehicleComponentResponse.model_validate(
            {
                "component_id": "CMP-9001",
                "vehicle_id": "VEH-9999",
                "component_role": "ENGINE_MAIN",
                "label": "test",
            }
        )


def test_engine_secondary_is_rejected_for_new_authoritative_writes() -> None:
    with pytest.raises(ValueError):
        ComponentRole("ENGINE_SECONDARY")

    with pytest.raises(ValidationError):
        VehicleComponentResponse.model_validate(
            {
                "component_id": "CMP-9002",
                "vehicle_id": "VEH-9999",
                "component_role": "ENGINE_SECONDARY",
                "label": "test",
            }
        )


def test_no_legacy_normalization_path_exists_for_the_old_names() -> None:
    """No legacy-compatibility shim was introduced for this correction.

    `ComponentRole` rejects the old names outright rather than silently
    normalizing them, because no authoritative write path or persisted
    historical record ever depended on accepting them (see module
    docstring). This test guards against one being added later without an
    explicit, documented legacy-input-compatibility boundary.
    """
    valid_values = {member.value for member in ComponentRole}
    assert "ENGINE_MAIN" not in valid_values
    assert "ENGINE_SECONDARY" not in valid_values
    assert valid_values == {"CARRIER_ENGINE", "CRANE_ENGINE", "PTO", "VEHICLE"}


@pytest.mark.asyncio
async def test_api_output_never_emits_legacy_component_role_names(client: AsyncClient) -> None:
    models_response = await client.get("/api/v1/models")
    assert models_response.status_code == 200
    models_text = models_response.text
    assert "ENGINE_MAIN" not in models_text
    assert "ENGINE_SECONDARY" not in models_text

    for vehicle_id in ("VEH-1046", "VEH-1047", "VEH-1048"):
        detail_response = await client.get(f"/api/v1/vehicles/{vehicle_id}")
        assert detail_response.status_code == 200
        detail_text = detail_response.text
        assert "ENGINE_MAIN" not in detail_text
        assert "ENGINE_SECONDARY" not in detail_text


@pytest.mark.asyncio
async def test_vehicle_may_contain_carrier_engine_without_crane_engine(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1046")
    assert response.status_code == 200
    body = response.json()
    roles = {c["component_role"] for c in body["components"]}
    assert "CARRIER_ENGINE" in roles
    assert "CRANE_ENGINE" not in roles


@pytest.mark.asyncio
async def test_vehicle_may_contain_both_carrier_and_crane_engine(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1047")
    assert response.status_code == 200
    body = response.json()
    roles = {c["component_role"] for c in body["components"]}
    assert {"CARRIER_ENGINE", "CRANE_ENGINE"}.issubset(roles)


@pytest.mark.asyncio
async def test_vehicle_may_contain_carrier_engine_and_pto(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-1046")
    assert response.status_code == 200
    body = response.json()
    roles = {c["component_role"] for c in body["components"]}
    assert {"CARRIER_ENGINE", "PTO"}.issubset(roles)


@pytest.mark.asyncio
async def test_multi_engine_vehicle_components_are_distinguishable_by_id_and_role(
    client: AsyncClient,
) -> None:
    """A future component-aware counter (e.g. ENGINE_HOUR) keys off
    `component_id`/`component_role`, not a fixed engine count. This proves
    the two engine components on a dual-engine vehicle remain distinct and
    addressable independently after the rename.
    """
    response = await client.get("/api/v1/vehicles/VEH-1047")
    assert response.status_code == 200
    body = response.json()
    engine_components = [
        c for c in body["components"] if c["component_role"] in ("CARRIER_ENGINE", "CRANE_ENGINE")
    ]
    assert len(engine_components) == 2
    component_ids = {c["component_id"] for c in engine_components}
    roles = {c["component_role"] for c in engine_components}
    assert len(component_ids) == 2  # distinct component_id per engine
    assert roles == {"CARRIER_ENGINE", "CRANE_ENGINE"}


@pytest.mark.asyncio
async def test_stable_vehicle_and_component_ids_are_unchanged_by_the_rename(
    client: AsyncClient,
) -> None:
    """The correction only changes `component_role` values; `vehicle_id`,
    `model_id`, and `component_id` must be byte-for-byte the same stable
    identifiers documented since Phase 2.
    """
    response = await client.get("/api/v1/vehicles/VEH-1047")
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle"]["vehicle_id"] == "VEH-1047"
    assert body["model"]["model_id"] == "MODEL-0002"
    component_ids = {c["component_id"] for c in body["components"]}
    assert component_ids == {"CMP-0003", "CMP-0004", "CMP-0005"}
