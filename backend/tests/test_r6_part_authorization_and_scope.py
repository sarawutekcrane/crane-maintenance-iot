"""R6 — authorization, TEST/REAL isolation and the A-4 TEST-only fake meter
source (FINAL plan §7.6, §12; PG-5 unresolved; Owner decision A-4 ON TEST ONLY).

- PG-5 PROPOSAL on new operational routes: `can_manage_repair` or
  `can_manage_pm` (existing capabilities; nothing new is activated).
- Access Management mode: every R6 write is refused (fail-closed), even for
  the root holder, until the Owner approves a mapping.
- Vehicle TEST/REAL scope (the R5 AMB-1 check) on install and on BOTH vehicles
  of a transfer.
- The fake meter source can never serve a REAL context.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.repositories.base import REFERENCE_SCOPE_TEST, ScopedReferenceRow

V = "VEH-1048"
REAL_SCOPED = "VEH-1046"


def rid(**extra) -> dict:
    return {"X-Request-Id": str(uuid.uuid4())} | extra


async def tagged(client: AsyncClient) -> str:
    r = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": "PART-0005", "tag_label": f"TAG-{uuid.uuid4()}", "prior_usage": {"quality": "UNKNOWN"}})
    return r.json()["instance"]["part_instance_id"]


@pytest.mark.asyncio
async def test_operational_writes_need_repair_or_pm_management(client: AsyncClient) -> None:
    iid = await tagged(client)
    technician = rid(**{"X-Dev-Role": "TECHNICIAN"})
    for path, body in ((f"{iid}/status", {"to_status": "STOCK"}), (f"{iid}/identifiers", {"tag_label": "X"}),
                       (f"{iid}/return-from-repair", {}),
                       (f"{iid}/maintenance-events", {"action": "INSPECTED", "lifetime_rule_id": "LTR-X"})):
        r = await client.post(f"/api/v1/part-instances/{path}", json=body, headers=technician)
        assert r.status_code == 403, (path, r.text)
    supervisor = rid(**{"X-Dev-Role": "SUPERVISOR"})  # holds can_manage_repair / can_manage_pm
    assert (await client.post(f"/api/v1/part-instances/{iid}/status", json={"to_status": "STOCK",
                                                                            "storage_location": "A"},
                              headers=supervisor)).status_code == 200
    detail = (await client.get(f"/api/v1/part-instances/{iid}")).json()
    assert detail["status_events"][-1]["actor"] == "dev-user"  # the server actor, never a body value


@pytest.mark.asyncio
async def test_vehicle_writes_require_the_vehicle_in_the_request_scope(client: AsyncClient) -> None:
    iid = await tagged(client)
    refused = await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                                json={"asset_type": "VEHICLE", "asset_id": REAL_SCOPED})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "VEHICLE_SCOPE_UNPROVEN"
    assert (await client.get(f"/api/v1/part-instances/{iid}")).json()["segments"] == []
    position = await client.post("/api/v1/position-lifetime", json={
        "asset_type": "VEHICLE", "asset_id": REAL_SCOPED, "position_code": "P", "prior_usage": {"quality": "UNKNOWN"}})
    assert position.status_code == 422


@pytest.mark.asyncio
async def test_transfer_checks_both_source_and_target_scope(client: AsyncClient) -> None:
    from app.dependencies import get_repository

    repo = get_repository()
    iid = await tagged(client)
    assert (await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                              json={"asset_type": "VEHICLE", "asset_id": V})).status_code == 200
    target = await client.post(f"/api/v1/part-instances/{iid}/transfer", headers=rid(),
                               json={"target_asset_type": "VEHICLE", "target_asset_id": REAL_SCOPED})
    assert target.status_code == 422 and target.json()["error"]["code"] == "VEHICLE_SCOPE_UNPROVEN"
    # Source no longer provable (the source vehicle is taken out of the TEST scope):
    repo._vehicle_reference = [ScopedReferenceRow(values={"vehicle_id": "VEH-1047"}, scope=REFERENCE_SCOPE_TEST,
                                                  test_batch_id=MOCK_TEST_BATCH_ID)]
    source = await client.post(f"/api/v1/part-instances/{iid}/transfer", headers=rid(),
                               json={"target_asset_type": "VEHICLE", "target_asset_id": "VEH-1047"})
    assert source.status_code in (404, 422)
    assert source.json()["error"]["code"] in ("VEHICLE_NOT_FOUND", "VEHICLE_SCOPE_UNPROVEN")
    # Nothing moved (checked in the repository: CG-1 read isolation now also refuses reading an instance whose
    # vehicle is outside the request's scope).
    state = await repo.read_part_state()
    assert [s.asset_id for s in state.segments[iid] if s.status.value == "ACTIVE"] == [V]
    hidden = await client.get(f"/api/v1/part-instances/{iid}")
    assert hidden.status_code in (404, 422) and hidden.json()["error"]["code"] in ("VEHICLE_NOT_FOUND",
                                                                                   "VEHICLE_SCOPE_UNPROVEN")


# ---------------------------------------------------------------------------
# A-4: TEST-only fake meter source
# ---------------------------------------------------------------------------


def test_settings_refuse_the_fake_source_outside_mock_test() -> None:
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(data_repository="google_sheets", part_test_meter_source=True, app_env="development")
    with pytest.raises(ValueError):
        Settings(data_repository="mock", part_test_meter_source=True, app_env="production")
    assert Settings(data_repository="mock", app_env="development").part_test_meter_source_effective is True
    assert Settings(data_repository="mock", app_env="development",
                    part_test_meter_source=False).part_test_meter_source_effective is False
    assert Settings(data_repository="google_sheets", app_env="development",
                    registry_data_context="REAL").part_test_meter_source_effective is False
    assert Settings(data_repository="mock", app_env="staging").part_test_meter_source_effective is False


@pytest.mark.asyncio
async def test_the_fake_source_never_serves_or_records_in_a_real_context() -> None:
    from app.domain.part_lifetime_status_service import TestOnlyPartMeterSource

    real = TestOnlyPartMeterSource("REAL")
    with pytest.raises(PermissionError):
        real.record("VEH-1048", "CMP-X", "ENGINE_HOUR", 10)
    assert await real.observations("VEH-1048", not_after=datetime.now(timezone.utc)) == ()
    unconfigured = TestOnlyPartMeterSource(None)
    assert unconfigured.enabled is False


@pytest.mark.asyncio
async def test_without_the_test_source_the_runtime_stays_unknown() -> None:
    """F01 / T-MS-01: with A-4 OFF the part services use the R4 source
    (runtime NO_IOT_METER_SOURCE): no anchor is ever bound."""
    from app.domain.meter_service import MeterService
    from app.domain.part_instance import PriorUsage
    from app.domain.part_instance_service import PartInstanceService
    from app.domain.technician_assignment import AssignmentCutover
    from app.repositories.mock import MockRepository

    repo = MockRepository()
    service = PartInstanceService(repo, MeterService(repo), AssignmentCutover("TEST", MOCK_TEST_BATCH_ID))
    created = await service.create_instance("PART-0005", None, PriorUsage(quality="UNKNOWN"), None, "u",
                                            tag_label="T-OFF")
    installed = await service.install(created["instance"]["part_instance_id"], __import__(
        "app.domain.asset", fromlist=["AssetType"]).AssetType.VEHICLE, V, None, None, "u", None)
    assert installed["segments"][0]["baseline_anchors"] == []


@pytest.mark.asyncio
async def test_test_support_hook_validates_and_is_disabled_when_the_source_is_off(client: AsyncClient) -> None:
    pto = await client.post("/api/v1/test-support/part-meter-observations", headers=rid(), json={
        "vehicle_id": V, "component_id": None, "counter_type": "PTO_HOUR", "value": 1})
    assert pto.status_code == 422
    from app.dependencies import get_repository

    comps = {c.component_role.value: c.component_id for c in await get_repository().list_vehicle_components(V)}
    wrong = await client.post("/api/v1/test-support/part-meter-observations", headers=rid(), json={
        "vehicle_id": V, "component_id": comps["PTO"], "counter_type": "ENGINE_HOUR", "value": 1})
    assert wrong.status_code == 422
    technician = await client.post("/api/v1/test-support/part-meter-observations",
                                   headers=rid(**{"X-Dev-Role": "TECHNICIAN"}), json={
        "vehicle_id": V, "component_id": comps["CARRIER_ENGINE"], "counter_type": "ENGINE_HOUR", "value": 1})
    assert technician.status_code == 403


@pytest.mark.asyncio
async def test_hook_is_404_when_disabled(monkeypatch) -> None:
    from httpx import ASGITransport

    from app.config import get_settings
    from app.dependencies import reset_dependency_cache
    from app.main import create_app

    monkeypatch.setenv("PART_TEST_METER_SOURCE", "false")
    get_settings.cache_clear()
    reset_dependency_cache()
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as client:
            r = await client.post("/api/v1/test-support/part-meter-observations", headers=rid(), json={
                "vehicle_id": V, "component_id": None, "counter_type": "ODOMETER", "value": 1})
            assert r.status_code == 404 and r.json()["error"]["code"] == "TEST_SUPPORT_DISABLED"
    finally:
        get_settings.cache_clear()
        reset_dependency_cache()


@pytest.mark.asyncio
async def test_r4_pm_meter_source_is_untouched_by_the_test_source(client: AsyncClient) -> None:
    from app.dependencies import get_meter_service, get_repository
    from app.domain.pm_meter_anchor import NO_IOT_METER_SOURCE

    assert get_meter_service(get_repository()).iot_meter_source is NO_IOT_METER_SOURCE


# ---------------------------------------------------------------------------
# Access Management mode: every R6 write stays fail-closed (PG-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_management_refuses_every_r6_write_even_for_the_root_holder(monkeypatch) -> None:
    from tests.test_access_management import MGR, http, repo
    from tests.test_access_management_security import R6_WRITE_ROUTES
    from app.dependencies import AM_UNRESOLVED_WRITE_ROUTES

    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        store = repo()
        r6 = sorted(R6_WRITE_ROUTES)
        assert len(r6) == 10 and set(r6) <= AM_UNRESOLVED_WRITE_ROUTES
        for method, path in r6:
            concrete = path.replace("{part_id}", "PART-0005").replace("{part_set_id}", "PSET-0001").replace(
                "{part_instance_id}", "PINST-0001").replace("{position_lifetime_id}", "POSLT-0001")
            response = await http(method, concrete, store, MGR, role="ADMIN", json={})
            assert response.status_code == 403, (path, response.text)
            assert response.json()["error"]["code"] == "ACCESS_CAPABILITY_MAPPING_UNRESOLVED"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_service_refuses_a_new_cycle_approval_without_the_capability() -> None:
    """Defence in depth (mutant M17): the route already requires the capability for any
    return, but the SERVICE itself must refuse a new-cycle approval from a context
    without can_manage_repair / can_manage_pm, so no other caller can bypass it."""
    from app.context import RequestContext
    from app.domain.asset import AssetType
    from app.domain.meter_service import MeterService
    from app.domain.part_instance import PartInstanceStatus, PriorUsage
    from app.domain.part_instance_service import PartInstanceService
    from app.domain.technician_assignment import AssignmentCutover
    from app.errors import ApiError
    from app.repositories.mock import MockRepository

    repo = MockRepository()
    service = PartInstanceService(repo, MeterService(repo), AssignmentCutover("TEST", MOCK_TEST_BATCH_ID))
    created = await service.create_instance("PART-0005", None, PriorUsage(quality="UNKNOWN"), None, "u",
                                            tag_label=f"T-M17-{uuid.uuid4()}")
    iid = created["instance"]["part_instance_id"]
    await service.install(iid, AssetType.VEHICLE, V, None, None, "u", None)
    await service.remove(iid, PartInstanceStatus.IN_REPAIR, None, None, "u")
    no_capability = RequestContext(request_id="r", user_id="tech", capabilities=frozenset({"can_view"}))
    with pytest.raises(ApiError) as refused:
        await service.return_from_repair(iid, context=no_capability, outcome=None,
                                         repair_reference=None, new_cycle_approved=True,
                                         approval_reason_code="TEST-QUALIFYING-REPAIR", storage_location=None,
                                         effective_at=None, note=None, request_id=str(uuid.uuid4()), body={"x": 1})
    assert refused.value.status_code == 403
    assert (await service.get_instance(iid)).instance.status == PartInstanceStatus.IN_REPAIR


# ---------------------------------------------------------------------------
# CG-1 (corrected in R3 under Owner authorization): equipment TEST/REAL scope.
# The equipment reference master classifies EQP-0001 / EQP-0003 as REAL and EQP-0002 /
# EQP-TEST-901 as TEST. These were strict-xfail in R2 (defect pinned); they are now ordinary
# tests, together with the remaining write / read / replay cases below.
# ---------------------------------------------------------------------------


async def _cg1_part(client: AsyncClient) -> str:
    return await tagged(client)


@pytest.mark.asyncio
async def test_cg1_test_context_install_on_real_equipment_is_refused(client: AsyncClient) -> None:
    iid = await _cg1_part(client)
    r = await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                          json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001"})
    assert r.status_code in (404, 409, 422), r.text


@pytest.mark.asyncio
async def test_cg1_test_context_transfer_into_real_equipment_is_refused(client: AsyncClient) -> None:
    iid = await _cg1_part(client)
    assert (await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                              json={"asset_type": "VEHICLE", "asset_id": V,
                                    "position_code": f"CG1-{uuid.uuid4()}"})).status_code == 200
    r = await client.post(f"/api/v1/part-instances/{iid}/transfer", headers=rid(),
                          json={"target_asset_type": "EQUIPMENT", "target_asset_id": "EQP-0003"})
    assert r.status_code in (404, 409, 422), r.text


@pytest.mark.asyncio
async def test_cg1_test_context_position_record_on_real_equipment_is_refused(client: AsyncClient) -> None:
    r = await client.post("/api/v1/position-lifetime", headers=rid(), json={
        "asset_type": "EQUIPMENT", "asset_id": "EQP-0001", "position_code": f"CG1-{uuid.uuid4()}",
        "part_id": "PART-0004", "prior_usage": {"quality": "UNKNOWN"}})
    assert r.status_code in (404, 409, 422), r.text


@pytest.mark.asyncio
async def test_cg1_test_scoped_equipment_remains_usable(client: AsyncClient) -> None:
    """Control for the CG-1 cases: TEST-scoped equipment (EQP-0002) is a legitimate target."""
    iid = await _cg1_part(client)
    r = await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                          json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0002"})
    assert r.status_code == 200, r.text


# ---- CG-1 helpers: legacy / cross-scope rows can only be planted below the service layer ----

REAL_EQ, REAL_EQ2, TEST_EQ, TEST_EQ2 = "EQP-0001", "EQP-0003", "EQP-0002", "EQP-CG1-T2"
SCOPE_CODES = {"EQUIPMENT_SCOPE_UNPROVEN", "EQUIPMENT_NOT_FOUND", "VEHICLE_SCOPE_UNPROVEN", "VEHICLE_NOT_FOUND"}


def _repo():
    from app.dependencies import get_repository

    return get_repository()


async def _planted_instance_on(asset_type: str, asset_id: str, *, also_closed_on: tuple[str, str] | None = None) -> str:
    """A pre-existing (e.g. legacy-imported) installed instance written with the pre-R6 repository methods, which
    do not apply any R6 scope rule — the only way to obtain cross-scope data now that the services refuse it."""
    from app.domain.asset import AssetType
    from app.domain.part_instance import PriorUsage

    repo = _repo()
    detail = await repo.create_part_instance("PART-0005", None, PriorUsage(quality="UNKNOWN"), None, "legacy")
    iid = detail.instance.part_instance_id
    lifecycle = detail.instance.current_lifecycle_id
    if also_closed_on is not None:
        seg = await repo.create_installation_segment(iid, lifecycle, AssetType(also_closed_on[0]), also_closed_on[1],
                                                     None, "legacy", None, None)
        await repo.close_installation_segment(seg.segment_id, "legacy", None, "moved")
    await repo.create_installation_segment(iid, lifecycle, AssetType(asset_type), asset_id, None, "legacy", None, None)
    return iid


def _add_test_equipment(equipment_id: str) -> None:
    """A second TEST-scoped equipment (master row + TEST reference row of the mock batch), planted like the
    mock seed's EQP-0002."""
    from app.domain.common import utc_now
    from app.domain.equipment import Equipment, EquipmentCategory, EquipmentOperationalStatus

    repo = _repo()
    now = utc_now()
    repo._equipment[equipment_id] = Equipment(equipment_id=equipment_id, equipment_code=f"C-{equipment_id}",
                                              name="เครื่องทดสอบ", category=EquipmentCategory.LATHE,
                                              serial_number=None, location=None,
                                              operational_status=EquipmentOperationalStatus.READY, created_at=now,
                                              updated_at=now)
    repo._equipment_reference.append(ScopedReferenceRow(values={"equipment_id": equipment_id},
                                                        scope=REFERENCE_SCOPE_TEST, test_batch_id=MOCK_TEST_BATCH_ID))


def _side_effect_snapshot() -> tuple:
    repo = _repo()
    state = repo._part_state
    return (state, len(repo._meter_snapshots))


def _refused(r) -> None:
    assert r.status_code in (404, 409, 422), r.text
    assert r.json()["error"]["code"] in SCOPE_CODES | {"EQUIPMENT_ID_AMBIGUOUS"}, r.text


@pytest.mark.asyncio
async def test_cg1_transfer_out_of_real_equipment_into_a_test_vehicle_is_refused_without_side_effects(
        client: AsyncClient) -> None:
    iid = await _planted_instance_on("EQUIPMENT", REAL_EQ)
    before = _side_effect_snapshot()
    r = await client.post(f"/api/v1/part-instances/{iid}/transfer", headers=rid(), json={
        "target_asset_type": "VEHICLE", "target_asset_id": V, "position_code": f"CG1-{uuid.uuid4()}"})
    _refused(r)
    assert _side_effect_snapshot() == before  # no mutation, no snapshot, no request record


@pytest.mark.asyncio
async def test_cg1_equipment_to_equipment_scope_mismatch_is_refused_and_same_scope_works(client: AsyncClient) -> None:
    _add_test_equipment(TEST_EQ2)
    iid = await _cg1_part(client)
    assert (await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                              json={"asset_type": "EQUIPMENT", "asset_id": TEST_EQ})).status_code == 200
    before = _side_effect_snapshot()
    _refused(await client.post(f"/api/v1/part-instances/{iid}/transfer", headers=rid(),
                               json={"target_asset_type": "EQUIPMENT", "target_asset_id": REAL_EQ2}))
    assert _side_effect_snapshot() == before
    ok = await client.post(f"/api/v1/part-instances/{iid}/transfer", headers=rid(),
                           json={"target_asset_type": "EQUIPMENT", "target_asset_id": TEST_EQ2})
    assert ok.status_code == 200, ok.text
    assert [s["asset_id"] for s in ok.json()["segments"]] == [TEST_EQ, TEST_EQ2]
    assert (await client.post(f"/api/v1/part-instances/{iid}/remove", headers=rid(),
                              json={"next_status": "STOCK", "storage_location": f"S-{uuid.uuid4()}"})).status_code == 200


@pytest.mark.asyncio
async def test_cg1_removal_and_other_writes_on_a_part_at_real_equipment_are_refused(client: AsyncClient) -> None:
    iid = await _planted_instance_on("EQUIPMENT", REAL_EQ)
    before = _side_effect_snapshot()
    for path, body in ((f"{iid}/remove", {"next_status": "STOCK", "storage_location": "A"}),
                       (f"{iid}/identifiers", {"tag_label": f"T-{uuid.uuid4()}"}),
                       (f"{iid}/maintenance-events", {"action": "INSPECTED", "lifetime_rule_id": "LTR-X"})):
        _refused(await client.post(f"/api/v1/part-instances/{path}", headers=rid(), json=body))
    assert _side_effect_snapshot() == before


@pytest.mark.asyncio
async def test_cg1_position_replace_and_maintenance_on_real_equipment_are_refused(client: AsyncClient) -> None:
    from app.domain.asset import AssetType
    from app.domain.part_instance import PriorUsage

    record = await _repo().create_position_lifetime(AssetType.EQUIPMENT, REAL_EQ, f"LEG-{uuid.uuid4()}", "PART-0004",
                                                    None, None, PriorUsage(quality="UNKNOWN"), "legacy", None)
    before = _side_effect_snapshot()
    _refused(await client.post(f"/api/v1/position-lifetime/{record.position_lifetime_id}/replace", headers=rid(),
                               json={"reason": "x", "prior_usage": {"quality": "UNKNOWN"}}))
    _refused(await client.post(f"/api/v1/position-lifetime/{record.position_lifetime_id}/maintenance-events",
                               headers=rid(), json={"action": "INSPECTED", "lifetime_rule_id": "LTR-X"}))
    assert _side_effect_snapshot() == before
    # Reads of that record are refused as well.
    _refused(await client.get(f"/api/v1/position-lifetime/{record.position_lifetime_id}"))
    _refused(await client.get(f"/api/v1/position-lifetime/{record.position_lifetime_id}/lifetime-status"))
    _refused(await client.get(f"/api/v1/position-lifetime?asset_type=EQUIPMENT&asset_id={REAL_EQ}"))


@pytest.mark.asyncio
async def test_cg1_valid_test_equipment_position_create_replace_and_maintenance(client: AsyncClient) -> None:
    created = await client.post("/api/v1/position-lifetime", headers=rid(), json={
        "asset_type": "EQUIPMENT", "asset_id": TEST_EQ, "position_code": f"OK-{uuid.uuid4()}", "part_id": "PART-0004",
        "prior_usage": {"quality": "UNKNOWN"}})
    assert created.status_code == 200, created.text
    pid = created.json()["position_lifetime_id"]
    assert (await client.get(f"/api/v1/position-lifetime/{pid}/lifetime-status")).status_code == 200
    replaced = await client.post(f"/api/v1/position-lifetime/{pid}/replace", headers=rid(),
                                 json={"reason": "worn", "prior_usage": {"quality": "UNKNOWN"}})
    assert replaced.status_code == 200, replaced.text
    listed = await client.get(f"/api/v1/position-lifetime?asset_type=EQUIPMENT&asset_id={TEST_EQ}")
    assert listed.status_code == 200 and pid in [p["position_lifetime_id"] for p in listed.json()]


@pytest.mark.asyncio
async def test_cg1_equipment_reads_are_scope_isolated(client: AsyncClient) -> None:
    hidden = await _planted_instance_on("EQUIPMENT", REAL_EQ)
    _refused(await client.get(f"/api/v1/equipment/{REAL_EQ}/part-lifetime"))
    _refused(await client.get(f"/api/v1/part-instances/{hidden}"))
    _refused(await client.get(f"/api/v1/part-instances/{hidden}/lifetime-status"))
    _refused(await client.get(f"/api/v1/position-lifetime/by-host/{hidden}"))
    listed = await client.get("/api/v1/part-instances?page_size=200")
    assert listed.status_code == 200 and hidden not in [i["instance"]["part_instance_id"] for i in listed.json()["items"]]
    visible = await _cg1_part(client)
    assert (await client.post(f"/api/v1/part-instances/{visible}/install", headers=rid(),
                              json={"asset_type": "EQUIPMENT", "asset_id": TEST_EQ})).status_code == 200
    summary = await client.get(f"/api/v1/equipment/{TEST_EQ}/part-lifetime")
    assert summary.status_code == 200 and visible in [i["target_id"] for i in summary.json()["instances"]]


@pytest.mark.asyncio
async def test_cg1_nested_hosted_positions_and_history_never_leak_across_scopes(client: AsyncClient) -> None:
    """An instance whose history includes REAL equipment is not shown under TEST equipment, and neither is the
    seal hosted in it."""
    from app.domain.part_instance import PriorUsage

    leaked = await _planted_instance_on("EQUIPMENT", TEST_EQ, also_closed_on=("EQUIPMENT", REAL_EQ))
    repo = _repo()
    state = repo._part_state
    # plant a hosted seal directly (the service would refuse because of the REAL history)
    from dataclasses import replace as dc_replace
    from types import MappingProxyType

    from app.domain.position_lifetime import PositionLifetimeRecord
    from app.domain.common import utc_now
    seal = PositionLifetimeRecord(position_lifetime_id=f"POSLT-LEAK-{uuid.uuid4().hex[:6]}", asset_type=None,
                                  asset_id=None, position_code="ROD-SEAL", part_id="PART-0004",
                                  prior_usage=PriorUsage(quality="UNKNOWN"), started_at=utc_now(),
                                  host_part_instance_id=leaked)
    repo._part_state = dc_replace(state, positions=MappingProxyType({**state.positions, seal.position_lifetime_id: seal}))
    summary = await client.get(f"/api/v1/equipment/{TEST_EQ}/part-lifetime")
    assert summary.status_code == 200
    body = summary.text
    assert leaked not in body and seal.position_lifetime_id not in body and REAL_EQ not in body
    _refused(await client.get(f"/api/v1/position-lifetime/{seal.position_lifetime_id}/lifetime-status"))
    _refused(await client.post("/api/v1/position-lifetime", headers=rid(), json={
        "host_part_instance_id": leaked, "position_code": "PISTON-SEAL", "part_id": "PART-0004",
        "prior_usage": {"quality": "UNKNOWN"}}))


@pytest.mark.asyncio
async def test_cg1_missing_and_ambiguous_equipment_references_fail_closed(client: AsyncClient) -> None:
    from app.domain.equipment import Equipment, EquipmentCategory, EquipmentOperationalStatus
    from app.domain.common import utc_now

    repo = _repo()
    now = utc_now()
    repo._equipment["EQP-NOREF"] = Equipment(equipment_id="EQP-NOREF", equipment_code="NR-1", name="ไม่มีอ้างอิง",
                                             category=EquipmentCategory.LATHE, serial_number=None, location=None,
                                             operational_status=EquipmentOperationalStatus.READY, created_at=now,
                                             updated_at=now)
    iid = await _cg1_part(client)
    missing = await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                                json={"asset_type": "EQUIPMENT", "asset_id": "EQP-NOREF"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "EQUIPMENT_NOT_FOUND", missing.text
    repo._equipment_reference.append(ScopedReferenceRow(values={"equipment_id": TEST_EQ}, scope=REFERENCE_SCOPE_TEST,
                                                        test_batch_id=MOCK_TEST_BATCH_ID))
    before = _side_effect_snapshot()
    ambiguous = await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                                  json={"asset_type": "EQUIPMENT", "asset_id": TEST_EQ})
    assert ambiguous.status_code == 409 and ambiguous.json()["error"]["code"] == "EQUIPMENT_ID_AMBIGUOUS"
    assert _side_effect_snapshot() == before


@pytest.mark.asyncio
async def test_cg1_a_replay_never_bypasses_the_current_scope_check(client: AsyncClient) -> None:
    """A valid install is committed; the equipment is then (re)classified REAL. Replaying the SAME request id and
    body is refused by the current scope check instead of returning the stored response (no header, no data)."""
    from app.repositories.base import REFERENCE_SCOPE_REAL

    iid = await _cg1_part(client)
    headers = rid()
    first = await client.post(f"/api/v1/part-instances/{iid}/install", headers=headers,
                              json={"asset_type": "EQUIPMENT", "asset_id": TEST_EQ})
    assert first.status_code == 200
    repo = _repo()
    repo._equipment_reference = [r if r.values.get("equipment_id") != TEST_EQ else
                                 ScopedReferenceRow(values=r.values, scope=REFERENCE_SCOPE_REAL, test_batch_id="")
                                 for r in repo._equipment_reference]
    replay = await client.post(f"/api/v1/part-instances/{iid}/install", headers=headers,
                               json={"asset_type": "EQUIPMENT", "asset_id": TEST_EQ})
    _refused(replay)
    assert "X-Request-Replayed" not in replay.headers


@pytest.mark.asyncio
async def test_cg1_a_real_context_refuses_test_equipment_at_the_service() -> None:
    """The Mock server is always TEST; the REAL direction is proven at the service with a REAL cutover."""
    from app.domain.asset import AssetType
    from app.domain.meter_service import MeterService
    from app.domain.part_instance import PriorUsage
    from app.domain.part_instance_service import PartInstanceService, require_asset_scope
    from app.domain.technician_assignment import AssignmentCutover
    from app.errors import ApiError
    from app.repositories.mock import MockRepository

    repo = MockRepository()
    with pytest.raises(ApiError) as test_eq:
        await require_asset_scope(repo, AssetType.EQUIPMENT, TEST_EQ, "REAL", "")
    assert test_eq.value.code in ("EQUIPMENT_SCOPE_UNPROVEN", "EQUIPMENT_NOT_FOUND")
    await require_asset_scope(repo, AssetType.EQUIPMENT, REAL_EQ, "REAL", "")  # same scope: allowed
    with pytest.raises(ApiError):
        await require_asset_scope(repo, AssetType.EQUIPMENT, REAL_EQ, "TEST", MOCK_TEST_BATCH_ID)
    service = PartInstanceService(repo, MeterService(repo), AssignmentCutover("REAL", ""))
    created = await service.create_instance("PART-0005", None, PriorUsage(quality="UNKNOWN"), None, "u",
                                            tag_label=f"R-{uuid.uuid4()}")
    iid = created["instance"]["part_instance_id"]
    with pytest.raises(ApiError) as refused:
        await service.install(iid, AssetType.EQUIPMENT, TEST_EQ, None, None, "u", None)
    assert refused.value.code == "EQUIPMENT_SCOPE_UNPROVEN"
    installed = await service.install(iid, AssetType.EQUIPMENT, REAL_EQ, None, None, "u", None)
    assert installed["instance"]["status"] == "INSTALLED"  # same-scope (REAL) equipment remains usable


@pytest.mark.asyncio
async def test_cg2_a_replay_never_bypasses_authorization(client: AsyncClient) -> None:
    """The stored response of a committed write is not returned to an actor without the capability: the
    route's capability check runs before the service and its replay lookup (403, no replay header)."""
    iid = await tagged(client)
    request_id = str(uuid.uuid4())
    body = {"to_status": "STOCK", "storage_location": f"S-{uuid.uuid4()}"}
    first = await client.post(f"/api/v1/part-instances/{iid}/status", json=body,
                              headers={"X-Request-Id": request_id, "X-Dev-Role": "SUPERVISOR"})
    assert first.status_code == 200
    replay = await client.post(f"/api/v1/part-instances/{iid}/status", json=body,
                               headers={"X-Request-Id": request_id, "X-Dev-Role": "TECHNICIAN"})
    assert replay.status_code == 403 and "X-Request-Replayed" not in replay.headers
    same_actor = await client.post(f"/api/v1/part-instances/{iid}/status", json=body,
                                   headers={"X-Request-Id": request_id, "X-Dev-Role": "SUPERVISOR"})
    assert same_actor.status_code == 200 and same_actor.headers.get("X-Request-Replayed") == "true"


@pytest.mark.asyncio
async def test_cg1_fake_meter_evidence_is_refused_for_a_real_scoped_vehicle(client: AsyncClient) -> None:
    from app.dependencies import get_repository

    carrier = next(c.component_id for c in await get_repository().list_vehicle_components(REAL_SCOPED)
                   if c.component_role.value == "CARRIER_ENGINE")
    r = await client.post("/api/v1/test-support/part-meter-observations", headers=rid(), json={
        "vehicle_id": REAL_SCOPED, "component_id": carrier, "counter_type": "ENGINE_HOUR", "value": 5})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VEHICLE_SCOPE_UNPROVEN", r.text
