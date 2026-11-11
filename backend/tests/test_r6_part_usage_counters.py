"""R6 — verified part usage counters (FINAL plan §7.3, §7.3a; C1, R3-03, R3-04,
F01–F05) and the Owner's principal acceptance example (AP-20).

All meter values are SYNTHETIC TEST readings recorded through the A-4 TEST-only
fake source (or a hand-built fake source); the 5,000-hour REPLACE rule is a
synthetic TEST rule. Nothing here is a real threshold or real meter history.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.domain.asset import AssetType
from app.domain.part_instance import (
    HistoricalEvidenceType,
    InstallationSegment,
    InstallationSegmentStatus,
    LifecycleStartReason,
    MeterAnchor,
    PartInstanceStatus,
    PartLifecycle,
    PriorUsage,
    PriorUsageQuality,
    ReferenceStatus,
)
from app.domain.lifetime_rule import LifetimeTriggerType
from app.domain.part_usage import (
    Basis,
    PolicyContext,
    SegmentInput,
    clipped_usage,
    declared_quantity,
    delta_between,
    instance_counters,
    resolve_component,
    segment_delta,
)
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.vehicle_model import ComponentRole
from app.repositories.base import REFERENCE_SCOPE_TEST, ScopedReferenceRow

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
CARRIER = Basis("ENGINE_HOUR", "CARRIER_ENGINE")
CRANE = Basis("ENGINE_HOUR", "CRANE_ENGINE")
TEST = PolicyContext("TEST")
REAL = PolicyContext("REAL")


def rid() -> dict:
    return {"X-Request-Id": str(uuid.uuid4())}


def anchor(vehicle: str, value: float, *, component: str | None = "C1", counter: str = "ENGINE_HOUR",
           device: str = "D1", minutes: int = 0) -> MeterAnchor:
    t = T0 + timedelta(minutes=minutes)
    return MeterAnchor(vehicle_id=vehicle, component_id=component, counter_type=counter, value=value, observed_at=t,
                       received_at=t, time_quality="TIME_SYNCED", device_id=device, device_event_id=f"E{value}")


def segment(vehicle: str, base: list[MeterAnchor], end: list[MeterAnchor] | None, *, lifecycle: str = "L1",
            start: int = 0, stop: int | None = None, asset_type: AssetType = AssetType.VEHICLE) -> InstallationSegment:
    closed = end is not None
    return InstallationSegment(
        segment_id=f"S-{vehicle}-{start}", part_instance_id="P", lifecycle_id=lifecycle, asset_type=asset_type,
        asset_id=vehicle, status=InstallationSegmentStatus.CLOSED if closed else InstallationSegmentStatus.ACTIVE,
        installed_at=T0 + timedelta(minutes=start), installed_effective_at=T0 + timedelta(minutes=start),
        removed_at=T0 + timedelta(minutes=stop) if closed else None,
        removed_effective_at=T0 + timedelta(minutes=stop) if closed else None,
        baseline_anchors=base, removal_anchors=end or [])


COMPONENTS = (("C1", "CARRIER_ENGINE"), ("PTO1", "PTO"))
TWO_ENGINES = (("C1", "CARRIER_ENGINE"), ("C2", "CRANE_ENGINE"))
NEW_PART = PriorUsage(quality=PriorUsageQuality.KNOWN, value=0, evidence_type=HistoricalEvidenceType.NEW_PART,
                      evidence_reference="RPR-0001", reference_status=ReferenceStatus.RESOLVED)
UNKNOWN_PRIOR = PriorUsage(quality=PriorUsageQuality.UNKNOWN)


# ---------------------------------------------------------------------------
# Pure delta rules (R-1 … R-6)
# ---------------------------------------------------------------------------


def test_delta_requires_same_vehicle_component_device_and_non_negative() -> None:
    assert delta_between(anchor("V1", 100), anchor("V1", 150)) == (50.0, None)
    assert delta_between(None, anchor("V1", 150)) == (None, "METER_EVIDENCE_MISSING")
    assert delta_between(anchor("V1", 100), anchor("V2", 150)) == (None, "METER_SOURCE_MISMATCH")
    assert delta_between(anchor("V1", 100), anchor("V1", 150, component="C2")) == (None, "METER_SOURCE_MISMATCH")
    assert delta_between(anchor("V1", 100), anchor("V1", 150, device="D2")) == (None, "METER_DEVICE_CHANGED")
    assert delta_between(anchor("V1", 150), anchor("V1", 100)) == (None, "NEGATIVE_DELTA")  # never clamped


def test_component_resolution_never_guesses_an_engine() -> None:
    assert resolve_component(COMPONENTS, CARRIER) == ("C1", None)
    assert resolve_component(COMPONENTS, CRANE) == (None, "COMPONENT_UNRESOLVED")  # single-engine vehicle
    assert resolve_component((("A", "CARRIER_ENGINE"), ("B", "CARRIER_ENGINE")), CARRIER) == \
        (None, "COMPONENT_UNRESOLVED")
    assert resolve_component(COMPONENTS, Basis("PTO_HOUR", "PTO")) == (None, "COMPONENT_UNRESOLVED")
    assert resolve_component(COMPONENTS, Basis("ODOMETER")) == (None, None)


def test_two_engine_vehicle_reads_only_the_rules_engine_and_never_sums() -> None:
    seg = segment("V1", [anchor("V1", 100, component="C1"), anchor("V1", 5000, component="C2")],
                  [anchor("V1", 130, component="C1"), anchor("V1", 5200, component="C2")], stop=10)
    item = SegmentInput(seg, TWO_ENGINES)
    assert segment_delta(item, CARRIER) == (30.0, None)
    assert segment_delta(item, CRANE) == (200.0, None)


def test_equipment_and_missing_anchor_are_unknown_never_zero() -> None:
    equipment = SegmentInput(segment("EQ1", [], [], stop=5, asset_type=AssetType.EQUIPMENT))
    assert segment_delta(equipment, CARRIER) == (None, "NO_COUNTER_MODEL_FOR_ASSET")
    open_seg = SegmentInput(segment("V1", [anchor("V1", 100)], None), COMPONENTS, current_end=())
    assert segment_delta(open_seg, CARRIER) == (None, "METER_EVIDENCE_MISSING")


def test_clipped_usage_cuts_a_segment_at_a_boundary_reading_on_the_same_vehicle() -> None:
    seg = segment("V1", [anchor("V1", 100)], [anchor("V1", 300)], stop=60)
    item = SegmentInput(seg, COMPONENTS)
    q = clipped_usage([item], CARRIER, start_at=T0 + timedelta(minutes=10), start_anchors=[anchor("V1", 120, minutes=10)])
    assert q.value == 180.0 and q.quality == "KNOWN"
    missing = clipped_usage([item], CARRIER, start_at=T0 + timedelta(minutes=10), start_anchors=[])
    assert missing.quality == "UNKNOWN" and missing.value is None


# ---------------------------------------------------------------------------
# Declarations by verification level and policy (F02, F04, PG-1)
# ---------------------------------------------------------------------------


def _decl(level: str, value: float = 500) -> PriorUsage:
    if level == "DECLARED":
        return PriorUsage(quality=PriorUsageQuality.KNOWN, value=value, basis=LifetimeTriggerType.ENGINE_HOUR,
                          component_role=ComponentRole.CARRIER_ENGINE, evidence_type=HistoricalEvidenceType.DOCUMENT,
                          evidence_reference="free text", reference_status=ReferenceStatus.REFERENCE_UNVERIFIED)
    return PriorUsage(quality=PriorUsageQuality.KNOWN, value=value, basis=LifetimeTriggerType.ENGINE_HOUR,
                      component_role=ComponentRole.CARRIER_ENGINE, evidence_type=HistoricalEvidenceType.DOCUMENT,
                      evidence_reference="ATT-1", reference_status=ReferenceStatus.RESOLVED)


def test_declared_free_text_is_never_used_even_in_test() -> None:
    for policy in (TEST, REAL):
        q = declared_quantity(_decl("DECLARED"), CARRIER, policy, missing_reason="X")
        assert q.quality == "UNKNOWN" and q.value is None and "HISTORICAL_USAGE_NOT_VERIFIED" in q.reasons


def test_evidence_referenced_is_pending_in_real_and_test_proposed_in_test() -> None:
    real = declared_quantity(_decl("REF"), CARRIER, REAL, missing_reason="X")
    assert (real.quality, real.value, real.policy_state) == ("UNKNOWN", None, "PENDING")
    test = declared_quantity(_decl("REF"), CARRIER, TEST, missing_reason="X")
    assert (test.quality, test.value, test.policy_state) == ("KNOWN", 500.0, "TEST_PROPOSED")
    other_basis = declared_quantity(_decl("REF"), CRANE, TEST, missing_reason="X")
    assert other_basis.quality == "UNKNOWN" and "PRIOR_USAGE_BASIS_MISMATCH" in other_basis.reasons


def test_verified_brand_new_is_zero_approved_in_real_and_partial_is_non_decisive() -> None:
    q = declared_quantity(NEW_PART, CARRIER, REAL, missing_reason="X")
    assert (q.value, q.quality, q.policy_state) == (0.0, "KNOWN", "APPROVED")
    partial = PriorUsage(quality=PriorUsageQuality.PARTIAL, value=10, basis=LifetimeTriggerType.ODOMETER,
                         evidence_type=HistoricalEvidenceType.DOCUMENT, evidence_reference="ATT-1",
                         reference_status=ReferenceStatus.RESOLVED)
    assert declared_quantity(partial, Basis("ODOMETER"), TEST, missing_reason="X").quality == "PARTIAL_RECORDED"


def _lifecycles(*specs) -> list[PartLifecycle]:
    out = []
    for n, (lid, reason, trigger) in enumerate(specs, start=1):
        out.append(PartLifecycle(lifecycle_id=lid, part_instance_id="P", cycle_number=n, start_reason=reason,
                                 started_at=T0, ended_at=None if n == len(specs) else T0,
                                 start_trigger_event_id=trigger, start_policy_state="TEST_PROPOSED" if trigger else None))
    return out


def test_used_part_unknown_prior_tracks_but_never_claims_lifetime_or_cycle() -> None:
    seg = SegmentInput(segment("V1", [anchor("V1", 100)], [anchor("V1", 1100)], stop=10), COMPONENTS)
    counters = instance_counters(prior_usage=UNKNOWN_PRIOR, prior_cycle_usage=None,
                                 lifecycles=_lifecycles(("L1", LifecycleStartReason.ENROLLMENT, None)),
                                 current_lifecycle_id="L1", items=[seg], basis=CARRIER, policy=TEST)
    assert counters.tracked_since_enrollment.value == 1000.0
    assert counters.tracked_in_current_cycle.value == 1000.0
    assert counters.verified_lifetime_total.value is None and counters.verified_lifetime_total.quality == "UNKNOWN"
    assert counters.verified_current_cycle.value is None
    assert "PRIOR_CYCLE_USAGE_UNKNOWN" in counters.verified_current_cycle.reasons


def test_used_part_cycle_declaration_pending_in_real_test_proposed_in_test() -> None:
    seg = SegmentInput(segment("V1", [anchor("V1", 100)], [anchor("V1", 200)], stop=10), COMPONENTS)
    kwargs = dict(prior_usage=_decl("REF", 900), prior_cycle_usage=_decl("REF", 300),
                  lifecycles=_lifecycles(("L1", LifecycleStartReason.ENROLLMENT, None)), current_lifecycle_id="L1",
                  items=[seg], basis=CARRIER)
    real = instance_counters(policy=REAL, **kwargs)
    assert real.verified_current_cycle.value is None and real.verified_current_cycle.policy_state == "PENDING"
    assert "PRIOR_CYCLE_USAGE_POLICY_PENDING" in real.verified_current_cycle.reasons
    test = instance_counters(policy=TEST, **kwargs)
    assert (test.verified_current_cycle.value, test.verified_current_cycle.policy_state) == (400.0, "TEST_PROPOSED")
    assert (test.verified_lifetime_total.value, test.verified_lifetime_total.policy_state) == (1000.0, "TEST_PROPOSED")


def test_a_lifetime_declaration_is_never_auto_attributed_to_the_cycle() -> None:
    """PG-1 / mutant M19: a used part with an evidenced LIFETIME declaration but no
    cycle declaration keeps its current cycle UNKNOWN — the lifetime figure is never
    copied into the cycle, in TEST or REAL."""
    seg = SegmentInput(segment("V1", [anchor("V1", 100)], [anchor("V1", 200)], stop=10), COMPONENTS)
    for policy in (TEST, REAL):
        counters = instance_counters(prior_usage=_decl("REF", 900), prior_cycle_usage=None,
                                     lifecycles=_lifecycles(("L1", LifecycleStartReason.ENROLLMENT, None)),
                                     current_lifecycle_id="L1", items=[seg], basis=CARRIER, policy=policy)
        assert counters.verified_current_cycle.value is None
        assert counters.verified_current_cycle.quality == "UNKNOWN"
        assert "PRIOR_CYCLE_USAGE_UNKNOWN" in counters.verified_current_cycle.reasons


def test_approved_new_cycle_counts_only_its_own_segments_and_lifetime_keeps_everything() -> None:
    first = SegmentInput(segment("V1", [anchor("V1", 10000)], [anchor("V1", 13200)], stop=10), COMPONENTS)
    second = SegmentInput(segment("V1", [anchor("V1", 20000, minutes=20)], None, lifecycle="L2", start=20),
                          COMPONENTS, current_end=(anchor("V1", 25000, minutes=30),))
    counters = instance_counters(
        prior_usage=NEW_PART, prior_cycle_usage=None,
        lifecycles=_lifecycles(("L1", LifecycleStartReason.ENROLLMENT, None),
                               ("L2", LifecycleStartReason.OVERHAUL, "PSE-RETURN")),
        current_lifecycle_id="L2", items=[first, second], basis=CARRIER, policy=TEST)
    assert counters.verified_lifetime_total.value == 8200.0
    assert counters.verified_current_cycle.value == 5000.0
    assert counters.verified_current_cycle.policy_state == "TEST_PROPOSED"  # opened under PG-2 TEST policy


# ---------------------------------------------------------------------------
# API: the principal acceptance example with the A-4 TEST-only source
# ---------------------------------------------------------------------------


V = "VEH-1048"  # the mock's TEST-scoped single-engine vehicle (CARRIER_ENGINE CMP + PTO)


async def carrier_component(client: AsyncClient, vehicle: str = V) -> str:
    from app.dependencies import get_repository

    comps = await get_repository().list_vehicle_components(vehicle)
    return next(c.component_id for c in comps if c.component_role.value == "CARRIER_ENGINE")


async def meter(client: AsyncClient, value: float, vehicle: str = V, component: str | None = None) -> None:
    component = component or await carrier_component(client, vehicle)
    r = await client.post("/api/v1/test-support/part-meter-observations",
                          json={"vehicle_id": vehicle, "component_id": component, "counter_type": "ENGINE_HOUR",
                                "value": value}, headers=rid())
    assert r.status_code == 200, r.text


async def new_part_instance(client: AsyncClient, *, prior=None) -> str:
    repair = await client.post("/api/v1/repairs", json={"asset_type": "VEHICLE", "asset_id": V, "source_type": "MANUAL",
                                                       "symptom": "ทดสอบ"})
    prior = prior or {"quality": "KNOWN", "value": 0, "as_of": "2026-01-01", "evidence_type": "NEW_PART",
                      "evidence_reference": repair.json()["repair"]["repair_id"]}
    r = await client.post("/api/v1/part-instances", json={"part_id": "PART-0005", "tag_label": f"T-{uuid.uuid4()}",
                                                         "prior_usage": prior}, headers=rid())
    assert r.status_code == 200, r.text
    return r.json()["instance"]["part_instance_id"]


async def replace_rule(client: AsyncClient, interval: float = 5000) -> str:
    r = await client.post("/api/v1/lifetime-rules", json={
        "part_id": "PART-0005", "scope": "MODEL", "model_id": "MODEL-0003", "trigger_type": "ENGINE_HOUR",
        "component_role": "CARRIER_ENGINE", "interval_value": interval, "interval_unit": "HOUR",
        "due_action": "REPLACE", "note": "SYNTHETIC TEST RULE — not a real threshold"})
    assert r.status_code == 200, r.text
    return r.json()["lifetime_rule_id"]


def carrier_counters(status: dict) -> dict:
    return next(c for c in status["counters"]
                if c["basis"] == {"counter_type": "ENGINE_HOUR", "component_role": "CARRIER_ENGINE"})


async def repair_id(client: AsyncClient) -> str:
    r = await client.post("/api/v1/repairs", json={"asset_type": "VEHICLE", "asset_id": V, "source_type": "MANUAL",
                                                  "symptom": "ไดชาร์จเสีย"})
    return r.json()["repair"]["repair_id"]


@pytest.mark.asyncio
async def test_principal_example_3200_then_new_cycle_then_8200_and_5000_due(client: AsyncClient) -> None:
    rule_id = await replace_rule(client)
    iid = await new_part_instance(client)
    await meter(client, 10000)
    assert (await client.post(f"/api/v1/part-instances/{iid}/install",
                              json={"asset_type": "VEHICLE", "asset_id": V}, headers=rid())).status_code == 200
    await meter(client, 13200)
    assert (await client.post(f"/api/v1/part-instances/{iid}/remove", json={"next_status": "IN_REPAIR"},
                              headers=rid())).status_code == 200
    status = (await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json()
    c = carrier_counters(status)
    assert c["verified_lifetime_total"]["value"] == 3200 and c["verified_current_cycle"]["value"] == 3200
    # Removed: the vehicle keeps running, the part accrues nothing.
    await meter(client, 15000)
    c = carrier_counters((await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json())
    assert c["verified_lifetime_total"]["value"] == 3200 and c["tracked_since_enrollment"]["value"] == 3200
    # Qualifying approved return (TEST policy) and a successful install.
    returned = await client.post(f"/api/v1/part-instances/{iid}/return-from-repair", headers=rid(), json={
        "repair_reference": await repair_id(client), "new_cycle_approved": True,
        "approval_reason_code": "TEST-QUALIFYING-REPAIR"})
    assert returned.status_code == 200, returned.text
    await meter(client, 20000)
    installed = await client.post(f"/api/v1/part-instances/{iid}/install",
                                  json={"asset_type": "VEHICLE", "asset_id": V}, headers=rid())
    assert installed.status_code == 200 and len(installed.json()["lifecycles"]) == 2
    status = (await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json()
    c = carrier_counters(status)
    assert c["verified_lifetime_total"]["value"] == 3200 and c["verified_current_cycle"]["value"] == 0
    await meter(client, 25000)
    status = (await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json()
    c = carrier_counters(status)
    assert c["verified_lifetime_total"]["value"] == 8200
    assert c["verified_current_cycle"]["value"] == 5000
    rule = next(r for r in status["rules"] if r["lifetime_rule_id"] == rule_id)
    assert rule["status"] == "DUE" and rule["current_value"] == 5000 and rule["next_due_value"] == 5000
    assert rule["policy_state"] == "TEST_PROPOSED"  # the cycle was opened under the TEST-proposed PG-2 policy


@pytest.mark.asyncio
async def test_return_without_approval_never_resets_and_transfer_keeps_both_counters(client: AsyncClient) -> None:
    from app.dependencies import get_repository

    get_repository()._vehicle_reference = [
        ScopedReferenceRow(values={"vehicle_id": v}, scope=REFERENCE_SCOPE_TEST, test_batch_id=MOCK_TEST_BATCH_ID)
        for v in ("VEH-1048", "VEH-1047")]
    iid = await new_part_instance(client)
    await meter(client, 1000)
    await client.post(f"/api/v1/part-instances/{iid}/install", json={"asset_type": "VEHICLE", "asset_id": V},
                      headers=rid())
    await meter(client, 1400)
    await client.post(f"/api/v1/part-instances/{iid}/remove", json={"next_status": "IN_REPAIR"}, headers=rid())
    await client.post(f"/api/v1/part-instances/{iid}/return-from-repair", json={"outcome": "minor"}, headers=rid())
    await meter(client, 1500)
    await client.post(f"/api/v1/part-instances/{iid}/install", json={"asset_type": "VEHICLE", "asset_id": V},
                      headers=rid())
    await meter(client, 1600)
    c = carrier_counters((await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json())
    assert (c["verified_lifetime_total"]["value"], c["verified_current_cycle"]["value"]) == (500, 500)
    # Transfer to a two-engine vehicle (VEH-1047): no reset; deltas stay per segment and per vehicle.
    crane_vehicle = "VEH-1047"
    other_carrier = await carrier_component(client, crane_vehicle)
    await meter(client, 70000, vehicle=crane_vehicle, component=other_carrier)
    moved = await client.post(f"/api/v1/part-instances/{iid}/transfer", headers=rid(),
                              json={"target_asset_type": "VEHICLE", "target_asset_id": crane_vehicle})
    assert moved.status_code == 200, moved.text
    assert len(moved.json()["lifecycles"]) == 1
    await meter(client, 70100, vehicle=crane_vehicle, component=other_carrier)
    c = carrier_counters((await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json())
    # 500 before + 100 on the new vehicle; never 70100 - 1600.
    assert (c["verified_lifetime_total"]["value"], c["verified_current_cycle"]["value"]) == (600, 600)


@pytest.mark.asyncio
async def test_transfer_to_equipment_keeps_the_vehicle_basis_visible_and_never_reports_zero(
        client: AsyncClient) -> None:
    """Regression (found by the R6 browser scenario): after a transfer to workshop
    equipment the earlier vehicle's engine-hour basis must stay listed — the tracked
    history is still reported and the verified counters become non-decisive, never
    hidden, never 0 and never reset."""
    iid = await new_part_instance(client)
    await meter(client, 90000)
    assert (await client.post(f"/api/v1/part-instances/{iid}/install",
                              json={"asset_type": "VEHICLE", "asset_id": V}, headers=rid())).status_code == 200
    await meter(client, 90300)
    moved = await client.post(f"/api/v1/part-instances/{iid}/transfer", headers=rid(),
                              json={"target_asset_type": "EQUIPMENT", "target_asset_id": "EQP-0002"})
    assert moved.status_code == 200, moved.text
    status = (await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json()
    assert status["host"]["asset_type"] == "EQUIPMENT"
    c = carrier_counters(status)
    for key in ("verified_lifetime_total", "verified_current_cycle"):
        assert c[key]["quality"] != "KNOWN" and c[key]["value"] != 0
    assert c["tracked_since_enrollment"]["quality"] != "KNOWN"
    assert c["tracked_since_enrollment"]["value"] in (None, 300)


@pytest.mark.asyncio
async def test_used_part_with_unknown_prior_shows_tracked_only(client: AsyncClient) -> None:
    iid = await new_part_instance(client, prior={"quality": "UNKNOWN"})
    await meter(client, 100)
    await client.post(f"/api/v1/part-instances/{iid}/install", json={"asset_type": "VEHICLE", "asset_id": V},
                      headers=rid())
    await meter(client, 1100)
    status = (await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json()
    c = carrier_counters(status)
    assert c["tracked_since_enrollment"]["value"] == 1000 and c["tracked_since_enrollment"]["quality"] == "KNOWN"
    assert c["verified_lifetime_total"]["value"] is None and c["verified_current_cycle"]["value"] is None
    assert status["declarations"]["prior_usage"]["verification_level"] is None


@pytest.mark.asyncio
async def test_without_any_verified_reading_every_counter_is_unknown_never_zero(client: AsyncClient) -> None:
    """F01 / T-MS-01 / T-MS-11: machine-state snapshots exist (automatic install
    capture) but no verified IoT reading -> UNKNOWN everywhere."""
    iid = await new_part_instance(client)
    installed = await client.post(f"/api/v1/part-instances/{iid}/install", json={"asset_type": "VEHICLE", "asset_id": V},
                                  headers=rid())
    assert installed.json()["segments"][0]["baseline_meter_snapshot_id"] is not None  # context snapshot kept
    assert installed.json()["segments"][0]["baseline_anchors"] == []
    c = carrier_counters((await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json())
    for key in ("tracked_since_enrollment", "tracked_in_current_cycle", "verified_lifetime_total",
                "verified_current_cycle"):
        assert c[key]["value"] is None and c[key]["quality"] == "UNKNOWN"
        assert "METER_EVIDENCE_MISSING" in c[key]["reasons"]


@pytest.mark.asyncio
async def test_manual_snapshot_is_context_only_never_an_anchor(client: AsyncClient) -> None:
    """T-MS-13 / F03: a caller-supplied manual snapshot with real-looking
    values is stored as context; with no IoT reading the delta is UNKNOWN."""
    comp = await carrier_component(client)
    snap = await client.post("/api/v1/meter-snapshots", json={
        "asset_type": "VEHICLE", "asset_id": V,
        "readings": [{"component_id": comp, "counter_type": "ENGINE_HOUR", "value": 12345}]})
    assert snap.status_code == 200, snap.text
    iid = await new_part_instance(client)
    installed = await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(), json={
        "asset_type": "VEHICLE", "asset_id": V, "baseline_meter_snapshot_id": snap.json()["meter_snapshot_id"]})
    segment_row = installed.json()["segments"][0]
    assert segment_row["baseline_meter_snapshot_id"] == snap.json()["meter_snapshot_id"]
    assert segment_row["baseline_anchors"] == []
    c = carrier_counters((await client.get(f"/api/v1/part-instances/{iid}/lifetime-status")).json())
    assert c["tracked_since_enrollment"]["value"] is None


# ---------------------------------------------------------------------------
# Retrospective effective time and R4 selector eligibility (T-MS-09/10/14/15)
# ---------------------------------------------------------------------------


class _Source:
    """A hand-built verified source with explicit observed / received times."""

    def __init__(self, observations, max_age=timedelta(hours=6)) -> None:
        self.max_observation_age = max_age
        self._observations = list(observations)

    async def observations(self, vehicle_id, *, not_after):
        return tuple(o for o in self._observations if o.vehicle_id == vehicle_id)


def _obs(vehicle, component, value, observed, received=None, **kw):
    from app.domain.pm_meter_anchor import IotMeterObservation

    base = dict(vehicle_id=vehicle, component_id=component, counter_type="ENGINE_HOUR", value=value,
                observed_at=observed, received_at=received or observed, time_quality="TIME_SYNCED", device_id="DEV-1",
                device_event_id=f"EV-{value}-{observed.timestamp()}", device_verified=True)
    base.update(kw)
    return IotMeterObservation(**base)


async def _service_with(source):
    from app.domain.meter_service import MeterService
    from app.domain.part_instance_service import PartInstanceService
    from app.domain.technician_assignment import AssignmentCutover
    from app.repositories.mock import MockRepository

    repo = MockRepository()
    comp = next(c.component_id for c in await repo.list_vehicle_components(V) if c.component_role.value == "CARRIER_ENGINE")
    return repo, PartInstanceService(repo, MeterService(repo), AssignmentCutover("TEST", MOCK_TEST_BATCH_ID), source), comp


@pytest.mark.asyncio
async def test_t_ms_14_retro_event_uses_the_reading_at_its_effective_time_never_a_later_one() -> None:
    now = datetime.now(timezone.utc)
    t_install = now - timedelta(hours=3)
    source = _Source([])
    repo, service, comp = await _service_with(source)
    source._observations = [
        _obs(V, comp, 500, t_install - timedelta(minutes=5)),                          # eligible at t_install
        _obs(V, comp, 520, t_install - timedelta(minutes=1), now - timedelta(hours=1)),  # received too late
    ]
    # A pre-R6 row (no status event yet), so a back-dated install is forward-only valid.
    created = await repo.create_part_instance("PART-0005", "SN-RETRO", PriorUsage(quality="UNKNOWN"), None, "u")
    iid = created.instance.part_instance_id
    installed = await service.install(iid, AssetType.VEHICLE, V, None, None, "u", None, effective_at=t_install)
    seg = installed["segments"][0]
    assert seg["installed_effective_at"].startswith(t_install.isoformat()[:19])
    assert [a["value"] for a in seg["baseline_anchors"]] == [500.0]
    assert seg["baseline_meter_snapshot_id"] is None  # no present-time capture for a back-dated event (F03)
    later = now - timedelta(hours=4)
    from app.errors import ApiError
    with pytest.raises(ApiError) as before_latest:
        await service.remove(iid, PartInstanceStatus.STOCK,
                             None, None, "u", storage_location="S", effective_at=later)
    assert before_latest.value.code == "EFFECTIVE_TIME_BEFORE_LATEST_EVENT"
    with pytest.raises(ApiError) as future:
        await service.remove(iid, PartInstanceStatus.STOCK,
                             None, None, "u", storage_location="S", effective_at=now + timedelta(hours=1))
    assert future.value.code == "EFFECTIVE_TIME_IN_FUTURE"


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [
    {"device_verified": False}, {"time_quality": "RECEIVED_TIME"}, {"device_id": " "}, {"device_event_id": ""},
    {"observed_offset": timedelta(minutes=5)},      # observed after `at`
    {"received_offset": timedelta(minutes=5)},      # received after `at`
    {"observed_offset": -timedelta(hours=7)},       # outside the 6 h window
    {"max_age": None},                              # the source cannot vouch -> fail closed
    {"counter_type": "PTO_HOUR"},
])
async def test_t_ms_15_each_r4_eligibility_rule_is_enforced_for_part_anchors(override) -> None:
    from app.domain.part_instance_service import verified_anchors
    from app.repositories.mock import MockRepository

    repo = MockRepository()
    comp = next(c.component_id for c in await repo.list_vehicle_components(V) if c.component_role.value == "CARRIER_ENGINE")
    at = datetime.now(timezone.utc)
    kw = {k: v for k, v in override.items() if k not in ("observed_offset", "received_offset", "max_age")}
    observed = at + override.get("observed_offset", -timedelta(minutes=1))
    received = at + override.get("received_offset", -timedelta(minutes=1))
    source = _Source([_obs(V, comp, 100, observed, received, **kw)],
                     max_age=override.get("max_age", timedelta(hours=6)))
    assert await verified_anchors(repo, source, V, at) == []
    ok = _Source([_obs(V, comp, 100, at - timedelta(minutes=1))])
    assert [a.value for a in await verified_anchors(repo, ok, V, at)] == [100.0]


@pytest.mark.asyncio
async def test_equal_time_disagreeing_readings_are_ambiguous_and_never_guessed() -> None:
    from app.domain.part_instance_service import verified_anchors
    from app.repositories.mock import MockRepository

    repo = MockRepository()
    comp = next(c.component_id for c in await repo.list_vehicle_components(V) if c.component_role.value == "CARRIER_ENGINE")
    at = datetime.now(timezone.utc)
    t = at - timedelta(minutes=1)
    source = _Source([_obs(V, comp, 100, t, device_event_id="A"), _obs(V, comp, 105, t, device_event_id="B")])
    assert await verified_anchors(repo, source, V, at) == []
