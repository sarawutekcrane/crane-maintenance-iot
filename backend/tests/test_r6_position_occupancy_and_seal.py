"""R6 — cross-mode occupancy O-1…O-6 and instance-hosted position records
(a seal inside a cylinder follows the cylinder; replacing the seal resets only
the seal) — FINAL plan §7.5, AP-07. Synthetic TEST data only."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.repositories.base import REFERENCE_SCOPE_TEST, ScopedReferenceRow

V = "VEH-1048"
CYLINDER = "PART-0005"   # seeded INSTANCE_TRACKED (development example)
SEAL = "PART-0004"       # seeded POSITION_LIFETIME (development example)


def rid() -> dict:
    return {"X-Request-Id": str(uuid.uuid4())}


def scope(*vehicles: str) -> None:
    from app.dependencies import get_repository

    get_repository()._vehicle_reference = [
        ScopedReferenceRow(values={"vehicle_id": v}, scope=REFERENCE_SCOPE_TEST, test_batch_id=MOCK_TEST_BATCH_ID)
        for v in vehicles]


async def cylinder(client: AsyncClient) -> str:
    r = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": CYLINDER, "tag_label": f"CYL-{uuid.uuid4()}", "prior_usage": {"quality": "UNKNOWN"}})
    return r.json()["instance"]["part_instance_id"]


async def install(client: AsyncClient, iid: str, vehicle: str = V, position: str | None = None):
    return await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                             json={"asset_type": "VEHICLE", "asset_id": vehicle, "position_code": position})


async def position(client: AsyncClient, **body):
    return await client.post("/api/v1/position-lifetime", headers=rid(),
                             json={"position_code": "SEAL", "part_id": SEAL, "prior_usage": {"quality": "UNKNOWN"}} | body)


async def meter(client: AsyncClient, value: float, vehicle: str = V) -> None:
    from app.dependencies import get_repository

    comp = next(c.component_id for c in await get_repository().list_vehicle_components(vehicle)
                if c.component_role.value == "CARRIER_ENGINE")
    r = await client.post("/api/v1/test-support/part-meter-observations", headers=rid(), json={
        "vehicle_id": vehicle, "component_id": comp, "counter_type": "ENGINE_HOUR", "value": value})
    assert r.status_code == 200, r.text


def carrier(status: dict) -> dict:
    return next(c for c in status["counters"] if c["basis"]["component_role"] == "CARRIER_ENGINE")


@pytest.mark.asyncio
async def test_o1_one_instance_per_asset_position_and_trimmed_exact_match(client: AsyncClient) -> None:
    a, b = await cylinder(client), await cylinder(client)
    assert (await install(client, a, position="200/2")).status_code == 200
    clash = await install(client, b, position=" 200/2 ")
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "PART_INVARIANT_POSITION_OCCUPIED"
    assert (await install(client, b, position="200/1")).status_code == 200


@pytest.mark.asyncio
async def test_o2_o3_position_records_and_instances_never_share_an_asset_position(client: AsyncClient) -> None:
    assert (await position(client, asset_type="VEHICLE", asset_id=V, position_code="J-1")).status_code == 200
    dup = await position(client, asset_type="VEHICLE", asset_id=V, position_code="J-1")
    assert dup.status_code == 409  # O-2
    iid = await cylinder(client)
    clash = await install(client, iid, position="J-1")
    assert clash.status_code == 409  # O-3 (instance onto a position-tracked slot)
    assert (await install(client, iid, position="J-2")).status_code == 200
    back = await position(client, asset_type="VEHICLE", asset_id=V, position_code="J-2")
    assert back.status_code == 409  # O-3 (record onto an instance-occupied slot)


@pytest.mark.asyncio
async def test_o4_hosted_seal_placement_is_derived_and_unique_per_host(client: AsyncClient) -> None:
    cyl = await cylinder(client)
    seal = await position(client, host_part_instance_id=cyl, position_code="ROD-SEAL")
    assert seal.status_code == 200, seal.text
    assert seal.json()["asset_type"] is None and seal.json()["asset_id"] is None  # never stored twice
    dup = await position(client, host_part_instance_id=cyl, position_code="ROD-SEAL")
    assert dup.status_code == 409
    forbidden = await position(client, host_part_instance_id=cyl, asset_type="VEHICLE", asset_id=V,
                               position_code="X")
    assert forbidden.status_code == 422 and forbidden.json()["error"]["code"] == "HOSTED_RECORD_ASSET_FORBIDDEN"
    # A hosted record does not occupy the vehicle position namespace (O-4 vs O-1…O-3).
    assert (await install(client, cyl, position="ROD-SEAL")).status_code == 200


@pytest.mark.asyncio
async def test_o6_an_instance_tracked_part_cannot_be_hosted_inside_an_instance(client: AsyncClient) -> None:
    cyl = await cylinder(client)
    r = await position(client, host_part_instance_id=cyl, part_id=CYLINDER, position_code="X")
    assert r.status_code == 422 and r.json()["error"]["code"] == "NESTED_INSTANCE_UNSUPPORTED"


@pytest.mark.asyncio
async def test_seal_follows_its_cylinder_and_seal_replacement_never_resets_the_cylinder(client: AsyncClient) -> None:
    scope("VEH-1048", "VEH-1047")
    cyl = await cylinder(client)
    await meter(client, 100)
    await install(client, cyl)
    seal = (await position(client, host_part_instance_id=cyl, position_code="ROD-SEAL")).json()["position_lifetime_id"]
    await meter(client, 150)
    # The cylinder moves to another vehicle; the seal goes with it (no own placement).
    await meter(client, 9000, vehicle="VEH-1047")
    moved = await client.post(f"/api/v1/part-instances/{cyl}/transfer", headers=rid(),
                              json={"target_asset_type": "VEHICLE", "target_asset_id": "VEH-1047"})
    assert moved.status_code == 200, moved.text
    await meter(client, 9030, vehicle="VEH-1047")
    seal_status = (await client.get(f"/api/v1/position-lifetime/{seal}/lifetime-status")).json()
    assert seal_status["host"]["asset_id"] == "VEH-1047"
    assert carrier(seal_status)["tracked_since_enrollment"]["value"] == 80  # 50 on VEH-1048 + 30 on VEH-1047
    cyl_before = carrier((await client.get(f"/api/v1/part-instances/{cyl}/lifetime-status")).json())
    assert cyl_before["tracked_since_enrollment"]["value"] == 80
    # Replace only the seal: a NEW brand-new seal record; the cylinder is untouched.
    rep = (await client.post("/api/v1/repairs", json={"asset_type": "VEHICLE", "asset_id": V,
                                                      "source_type": "MANUAL", "symptom": "ซีลรั่ว"})).json()
    replaced = await client.post(f"/api/v1/position-lifetime/{seal}/replace", headers=rid(), json={
        "reason": "ซีลรั่ว", "prior_usage": {"quality": "KNOWN", "value": 0, "as_of": "2026-01-01",
                                             "evidence_type": "NEW_PART",
                                             "evidence_reference": rep["repair"]["repair_id"]}})
    assert replaced.status_code == 200, replaced.text
    successor = replaced.json()["successor"]["position_lifetime_id"]
    assert replaced.json()["ended"]["superseded_by_id"] == successor
    await meter(client, 9040, vehicle="VEH-1047")
    new_seal = carrier((await client.get(f"/api/v1/position-lifetime/{successor}/lifetime-status")).json())
    assert (new_seal["verified_lifetime_total"]["value"], new_seal["verified_current_cycle"]["value"]) == (10, 10)
    old_seal = carrier((await client.get(f"/api/v1/position-lifetime/{seal}/lifetime-status")).json())
    assert old_seal["tracked_since_enrollment"]["value"] == 80  # history kept, frozen at its end
    cyl_after = (await client.get(f"/api/v1/part-instances/{cyl}")).json()
    assert len(cyl_after["lifecycles"]) == 1
    assert carrier((await client.get(f"/api/v1/part-instances/{cyl}/lifetime-status")).json())[
        "tracked_since_enrollment"]["value"] == 90


@pytest.mark.asyncio
async def test_asset_summary_nests_hosted_seals_under_their_installed_cylinder(client: AsyncClient) -> None:
    cyl = await cylinder(client)
    await install(client, cyl, position="BOOM-1")
    await position(client, host_part_instance_id=cyl, position_code="ROD-SEAL")
    await position(client, asset_type="VEHICLE", asset_id=V, position_code="HOSE-1")
    summary = (await client.get(f"/api/v1/vehicles/{V}/part-lifetime")).json()
    instance = next(i for i in summary["instances"] if i["target_id"] == cyl)
    assert [h["host"]["host_part_instance_id"] for h in instance["hosted_positions"]] == [cyl]
    assert [p["host"]["position_code"] for p in summary["positions"]] == ["HOSE-1"]
    assert (await client.get("/api/v1/vehicles/VEH-9999/part-lifetime")).status_code == 404
