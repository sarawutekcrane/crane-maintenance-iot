"""R6 — part instance lifecycle API (FINAL plan §7.2 A-1 matrix, §7.2b
approval state machine / A-2(i) / A-2(ii), §7.3a historical declarations, §7.5
identity layers and the R3-05 physical-identity sufficiency rule).

T-LC-01…T-LC-12 prove that no sequence of install / remove / transfer /
return / status / start-new-lifecycle / retry / injected fault can produce a
premature or duplicate cycle reset. Synthetic TEST data only.
"""
from __future__ import annotations

import random
import uuid

import pytest
from httpx import AsyncClient

V = "VEH-1048"
PART = "PART-0005"


def rid() -> dict:
    return {"X-Request-Id": str(uuid.uuid4())}


async def create(client: AsyncClient, **extra) -> dict:
    body = {"part_id": PART, "prior_usage": {"quality": "UNKNOWN"}}
    body.update(extra)
    r = await client.post("/api/v1/part-instances", json=body, headers=rid())
    assert r.status_code == 200, r.text
    return r.json()


async def tagged(client: AsyncClient) -> str:
    return (await create(client, tag_label=f"TAG-{uuid.uuid4()}"))["instance"]["part_instance_id"]


async def post(client: AsyncClient, path: str, body: dict, headers: dict | None = None):
    return await client.post(f"/api/v1/part-instances/{path}", json=body, headers=headers or rid())


async def repair_id(client: AsyncClient) -> str:
    r = await client.post("/api/v1/repairs", json={"asset_type": "VEHICLE", "asset_id": V, "source_type": "MANUAL",
                                                  "symptom": "ทดสอบ"})
    assert r.status_code == 200, r.text
    return r.json()["repair"]["repair_id"]


async def detail(client: AsyncClient, iid: str) -> dict:
    return (await client.get(f"/api/v1/part-instances/{iid}")).json()


async def into_repair(client: AsyncClient, iid: str) -> None:
    assert (await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})).status_code == 200
    assert (await post(client, f"{iid}/remove", {"next_status": "IN_REPAIR"})).status_code == 200


async def approved_return(client: AsyncClient, iid: str):
    return await post(client, f"{iid}/return-from-repair", {
        "repair_reference": await repair_id(client), "new_cycle_approved": True,
        "approval_reason_code": "TEST-QUALIFYING"})


def cycles(d: dict) -> int:
    return len(d["lifecycles"])


# ---------------------------------------------------------------------------
# A-1 transition matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_starts_ready_or_stock_and_records_a_status_event(client: AsyncClient) -> None:
    ready = await create(client)
    assert ready["instance"]["status"] == "READY_FOR_INSTALL"
    assert [e["operation"] for e in ready["status_events"]] == ["REGISTER"]
    stock = await create(client, initial_status="STOCK", tag_label="TAG-STOCK-1", storage_location="ชั้น A1")
    assert stock["instance"]["status"] == "STOCK" and stock["instance"]["storage_location"] == "ชั้น A1"
    bad = await client.post("/api/v1/part-instances", json={"part_id": PART, "prior_usage": {"quality": "UNKNOWN"},
                                                            "initial_status": "INSTALLED"}, headers=rid())
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "PART_TRANSITION_NOT_ALLOWED"


@pytest.mark.asyncio
@pytest.mark.parametrize("start,target,allowed", [
    ("READY_FOR_INSTALL", "STOCK", True), ("READY_FOR_INSTALL", "IN_REPAIR", True),
    ("READY_FOR_INSTALL", "SCRAPPED", True), ("READY_FOR_INSTALL", "REMOVED", False),
    ("READY_FOR_INSTALL", "INSTALLED", False), ("STOCK", "READY_FOR_INSTALL", True),
    ("STOCK", "IN_REPAIR", True), ("STOCK", "REMOVED", False),
])
async def test_status_moves_follow_the_matrix(client: AsyncClient, start, target, allowed) -> None:
    iid = (await create(client, tag_label=f"TAG-{uuid.uuid4()}", initial_status=start))["instance"]["part_instance_id"]
    r = await post(client, f"{iid}/status", {"to_status": target, "storage_location": "ชั้น B"})
    if allowed:
        assert r.status_code == 200, r.text
        assert r.json()["instance"]["status"] == target
        assert r.json()["status_events"][-1]["from_status"] == start
    else:
        assert r.status_code in (409, 422)
        assert (await detail(client, iid))["instance"]["status"] == start


@pytest.mark.asyncio
async def test_in_repair_cannot_be_installed_directly_and_only_returns_or_scraps(client: AsyncClient) -> None:
    iid = await tagged(client)
    await into_repair(client, iid)
    direct = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    assert direct.status_code == 409 and direct.json()["error"]["code"] == "PART_INSTANCE_NOT_READY_FOR_INSTALL"
    assert (await post(client, f"{iid}/status", {"to_status": "READY_FOR_INSTALL"})).status_code == 409
    assert (await post(client, f"{iid}/status", {"to_status": "SCRAPPED"})).status_code == 200
    for path, body in ((f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V}),
                       (f"{iid}/status", {"to_status": "STOCK"}),
                       (f"{iid}/return-from-repair", {})):
        assert (await post(client, path, body)).status_code in (409, 422)  # SCRAPPED is terminal


@pytest.mark.asyncio
async def test_removed_cannot_be_installed_directly(client: AsyncClient) -> None:
    iid = await tagged(client)
    await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    await post(client, f"{iid}/remove", {"next_status": "REMOVED"})
    r = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PART_INSTANCE_NOT_READY_FOR_INSTALL"
    assert (await post(client, f"{iid}/status", {"to_status": "READY_FOR_INSTALL"})).status_code == 200
    assert (await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})).status_code == 200


# ---------------------------------------------------------------------------
# A-2(ii) single reset authority — T-LC-01 … T-LC-12
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_lc_01_approved_return_then_install_opens_exactly_one_cycle_at_install(client: AsyncClient) -> None:
    iid = await tagged(client)
    await into_repair(client, iid)
    ret = await approved_return(client, iid)
    assert ret.status_code == 200 and cycles(ret.json()) == 1
    installed = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    body = installed.json()
    assert cycles(body) == 2
    new_cycle = body["lifecycles"][-1]
    install_event = body["status_events"][-1]
    assert new_cycle["started_at"] == install_event["effective_at"]
    assert new_cycle["start_trigger_event_id"] == ret.json()["status_events"][-1]["event_id"]
    assert body["segments"][-1]["lifecycle_id"] == new_cycle["lifecycle_id"]


@pytest.mark.asyncio
async def test_t_lc_02_and_03_legacy_route_never_writes_in_any_state(client: AsyncClient) -> None:
    iid = await tagged(client)
    async def legacy_state() -> str:
        before = await detail(client, iid)
        r = await post(client, f"{iid}/start-new-lifecycle", {"approved_reason": "อนุมัติ"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "NEW_CYCLE_OPENS_AT_INSTALL"
        assert await detail(client, iid) == before
        return r.json()["error"]["details"]["approval_state"]
    assert await legacy_state() == "NONE"
    await into_repair(client, iid)
    assert await legacy_state() == "NONE"
    await approved_return(client, iid)
    assert await legacy_state() == "PENDING"
    await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    assert await legacy_state() == "CONSUMED"
    await post(client, f"{iid}/remove", {"next_status": "IN_REPAIR"})
    await approved_return(client, iid)
    await post(client, f"{iid}/status", {"to_status": "IN_REPAIR"})
    assert await legacy_state() == "SUPERSEDED"
    assert cycles(await detail(client, iid)) == 2


@pytest.mark.asyncio
async def test_t_lc_04_and_05_retry_and_lost_response_never_open_a_second_cycle(client: AsyncClient) -> None:
    from app.dependencies import get_repository

    iid = await tagged(client)
    await into_repair(client, iid)
    await approved_return(client, iid)
    headers = rid()
    repo = get_repository()
    def lose(stage: str) -> None:
        if stage == "after_publish":
            raise RuntimeError("response lost after commit")
    repo.part_fault_hook = lose
    with pytest.raises(RuntimeError):
        await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V}, headers)
    repo.part_fault_hook = None
    first = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V}, headers)
    again = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V}, headers)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json() and cycles(first.json()) == 2
    assert cycles(await detail(client, iid)) == 2


@pytest.mark.asyncio
async def test_t_lc_06_rejected_install_keeps_the_approval_pending(client: AsyncClient) -> None:
    other = await tagged(client)
    assert (await post(client, f"{other}/install",
                       {"asset_type": "VEHICLE", "asset_id": V, "position_code": "P-1"})).status_code == 200
    iid = await tagged(client)
    await into_repair(client, iid)
    await approved_return(client, iid)
    blocked = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V, "position_code": "P-1"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "PART_INVARIANT_POSITION_OCCUPIED"
    assert cycles(await detail(client, iid)) == 1
    ok = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V, "position_code": "P-2"})
    assert ok.status_code == 200 and cycles(ok.json()) == 2


@pytest.mark.asyncio
async def test_t_lc_07_stock_and_ready_moves_keep_pending(client: AsyncClient) -> None:
    iid = await tagged(client)
    await into_repair(client, iid)
    await approved_return(client, iid)
    await post(client, f"{iid}/status", {"to_status": "STOCK", "storage_location": "ชั้น C"})
    await post(client, f"{iid}/status", {"to_status": "READY_FOR_INSTALL"})
    installed = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    assert cycles(installed.json()) == 2


@pytest.mark.asyncio
async def test_t_lc_08_superseded_approval_can_never_open_a_cycle(client: AsyncClient) -> None:
    iid = await tagged(client)
    await into_repair(client, iid)
    await approved_return(client, iid)
    await post(client, f"{iid}/status", {"to_status": "IN_REPAIR"})
    await post(client, f"{iid}/return-from-repair", {"outcome": "no approval"})
    installed = await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    assert installed.status_code == 200 and cycles(installed.json()) == 1


@pytest.mark.asyncio
async def test_t_lc_09_and_10_reinstall_and_transfer_never_open_a_cycle(client: AsyncClient) -> None:
    iid = await tagged(client)
    await into_repair(client, iid)
    await approved_return(client, iid)
    await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    await post(client, f"{iid}/remove", {"next_status": "STOCK", "storage_location": "ชั้น D"})
    await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
    moved = await post(client, f"{iid}/transfer", {"target_asset_type": "EQUIPMENT", "target_asset_id": "EQP-0002"})
    assert moved.status_code == 200, moved.text
    assert cycles(moved.json()) == 2  # only the one consumed approval ever opened a cycle


@pytest.mark.asyncio
async def test_t_lc_11_unauthorized_or_unlabelled_approval_is_refused(client: AsyncClient) -> None:
    iid = await tagged(client)
    await into_repair(client, iid)
    technician = rid() | {"X-Dev-Role": "TECHNICIAN"}
    r = await post(client, f"{iid}/return-from-repair", {"repair_reference": await repair_id(client),
                                                          "new_cycle_approved": True,
                                                          "approval_reason_code": "TEST-X"}, technician)
    assert r.status_code == 403
    no_label = await post(client, f"{iid}/return-from-repair", {"repair_reference": await repair_id(client),
                                                                 "new_cycle_approved": True,
                                                                 "approval_reason_code": "OVERHAUL"})
    assert no_label.status_code == 422 and no_label.json()["error"]["code"] == "APPROVAL_REASON_CODE_INVALID"
    no_repair = await post(client, f"{iid}/return-from-repair", {"new_cycle_approved": True,
                                                                  "approval_reason_code": "TEST-X"})
    assert no_repair.status_code == 422
    assert (await detail(client, iid))["instance"]["status"] == "IN_REPAIR"


@pytest.mark.asyncio
async def test_t_lc_11b_real_context_refuses_new_cycle_approval_while_pg2_is_pending() -> None:
    from app.domain.part_instance_service import PartInstanceService
    from app.domain.meter_service import MeterService
    from app.domain.technician_assignment import AssignmentCutover
    from app.repositories.mock import MockRepository
    from app.context import RequestContext
    from app.domain.authz import ALL_CAPABILITIES
    from app.errors import ApiError
    from app.domain.part_instance import PartInstanceStatus, PriorUsage

    repo = MockRepository()
    test_service = PartInstanceService(repo, MeterService(repo), AssignmentCutover("TEST", "MOCK-7O2B-SYNTHETIC"))
    created = await test_service.create_instance(PART, None, PriorUsage(quality="UNKNOWN"), None, "u",
                                                 tag_label="T-REAL-1")
    iid = created["instance"]["part_instance_id"]
    await test_service.change_status(iid, actor="u", to_status=PartInstanceStatus.IN_REPAIR, storage_location=None, reason=None,
                                     effective_at=None, request_id=str(uuid.uuid4()), body={})
    real_service = PartInstanceService(repo, MeterService(repo), AssignmentCutover("REAL", ""))
    ctx = RequestContext(request_id="r", user_id="manager", capabilities=ALL_CAPABILITIES)
    with pytest.raises(ApiError) as refused:
        await real_service.return_from_repair(iid, context=ctx, outcome=None, repair_reference=None,
                                              new_cycle_approved=True, approval_reason_code="TEST-X",
                                              storage_location=None, effective_at=None, note=None,
                                              request_id=str(uuid.uuid4()), body={})
    assert refused.value.code == "NEW_CYCLE_POLICY_PENDING"
    assert (await repo.read_part_state()).instances[iid].status.value == "IN_REPAIR"


@pytest.mark.asyncio
async def test_t_lc_12_random_sequences_never_produce_premature_or_duplicate_resets(client: AsyncClient) -> None:
    """Property-style: >= 500 seeded random operations over several instances,
    with retries and injected faults. Invariants after every step:
    lifecycles opened == approvals consumed, each OVERHAUL cycle is triggered
    by exactly one earlier approved return, and its first segment starts at
    `started_at` (= the consuming install)."""
    from app.dependencies import get_repository

    repo = get_repository()
    rng = random.Random(20261110)
    rep = await repair_id(client)
    instances = [await tagged(client) for _ in range(4)]
    last_headers: dict[str, dict] = {}
    operations = 0
    for step in range(640):
        iid = rng.choice(instances)
        kind = rng.choice(["install", "remove_repair", "remove_stock", "transfer", "return_ok", "return_plain",
                           "status_ready", "status_repair", "legacy", "retry", "fault"])
        headers = rid()
        body: tuple[str, dict] | None = None
        if kind == "install":
            body = (f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
        elif kind == "remove_repair":
            body = (f"{iid}/remove", {"next_status": "IN_REPAIR"})
        elif kind == "remove_stock":
            body = (f"{iid}/remove", {"next_status": "STOCK", "storage_location": "ชั้น R"})
        elif kind == "transfer":
            body = (f"{iid}/transfer", {"target_asset_type": "EQUIPMENT", "target_asset_id": "EQP-0002"})
        elif kind == "return_ok":
            body = (f"{iid}/return-from-repair", {"repair_reference": rep, "new_cycle_approved": True,
                                                  "approval_reason_code": "TEST-PROP"})
        elif kind == "return_plain":
            body = (f"{iid}/return-from-repair", {"outcome": "plain"})
        elif kind == "status_ready":
            body = (f"{iid}/status", {"to_status": "READY_FOR_INSTALL"})
        elif kind == "status_repair":
            body = (f"{iid}/status", {"to_status": "IN_REPAIR"})
        elif kind == "legacy":
            r = await post(client, f"{iid}/start-new-lifecycle", {"approved_reason": "x"})
            assert r.status_code in (404, 409)
        elif kind == "retry" and iid in last_headers:
            path, payload, h = last_headers[iid]
            await post(client, path, payload, h)
        elif kind == "fault":
            stage = rng.choice(["after_copy", "after_apply", "after_validate", "before_publish"])
            def hook(s: str, stage=stage) -> None:
                if s == stage:
                    raise RuntimeError("injected")
            repo.part_fault_hook = hook
            before = await repo.read_part_state()
            try:
                await post(client, f"{iid}/install", {"asset_type": "VEHICLE", "asset_id": V})
            except RuntimeError:
                pass
            repo.part_fault_hook = None
            assert await repo.read_part_state() is before or (await repo.read_part_state()).instances == before.instances
        if body is not None:
            r = await post(client, body[0], body[1], headers)
            operations += 1
            if r.status_code == 200:
                last_headers[iid] = (body[0], body[1], headers)
        state = await repo.read_part_state()
        for inst_id in instances:
            d = await detail(client, inst_id)
            approved = {e["event_id"]: e for e in d["status_events"] if e["new_cycle_approved"]}
            overhauls = [lc for lc in d["lifecycles"] if lc["start_reason"] == "OVERHAUL"]
            assert len({lc["start_trigger_event_id"] for lc in overhauls}) == len(overhauls)
            for lc in overhauls:
                assert lc["start_trigger_event_id"] in approved
                first_seg = min((s for s in d["segments"] if s["lifecycle_id"] == lc["lifecycle_id"]),
                                key=lambda s: s["installed_effective_at"])
                assert first_seg["installed_effective_at"] == lc["started_at"]
            assert sum(1 for lc in d["lifecycles"] if lc["ended_at"] is None) == 1
            assert len(state.lifecycles[inst_id]) == 1 + len(overhauls)
    assert operations >= 400  # plus legacy calls, retries and injected faults: 640 seeded steps in total


# ---------------------------------------------------------------------------
# Identity (A-3 OFF) and the R3-05 sufficiency rule I-1 … I-4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_demand_enrollment_never_requires_an_identifier(client: AsyncClient) -> None:
    a = await create(client)
    b = await create(client)
    assert a["instance"]["serial_number"] is None and b["instance"]["tag_label"] is None


@pytest.mark.asyncio
async def test_i2_unknown_location_with_an_unidentified_peer_blocks_movement(client: AsyncClient) -> None:
    a = (await create(client))["instance"]["part_instance_id"]
    await create(client)  # an unidentified peer of the same part, location unknown
    r = await post(client, f"{a}/install", {"asset_type": "VEHICLE", "asset_id": V})
    assert r.status_code == 409 and r.json()["error"]["details"]["reason"] == "UNKNOWN_LOCATION"
    fixed = await post(client, f"{a}/identifiers", {"tag_label": "TAG-I2"})
    assert fixed.status_code == 200 and fixed.json()["status_events"][-1]["operation"] == "IDENTIFIER_ASSIGNED"
    assert (await post(client, f"{a}/install", {"asset_type": "VEHICLE", "asset_id": V})).status_code == 200


@pytest.mark.asyncio
async def test_i1_and_i3_same_or_unknown_peer_location_block_and_distinct_locations_pass(client: AsyncClient) -> None:
    a = (await create(client, initial_status="STOCK", storage_location="ชั้น 1"))["instance"]["part_instance_id"]
    b = (await create(client, initial_status="STOCK", storage_location="ชั้น 1"))["instance"]["part_instance_id"]
    same = await post(client, f"{a}/status", {"to_status": "READY_FOR_INSTALL", "storage_location": "ชั้น 1"})
    assert same.status_code == 409 and same.json()["error"]["details"]["reason"] == "SAME_LOCATION"
    assert (await post(client, f"{a}/status", {"to_status": "READY_FOR_INSTALL",
                                               "storage_location": "ชั้น 2"})).status_code == 200
    c = (await create(client))["instance"]["part_instance_id"]  # peer with unknown location
    blocked = await post(client, f"{a}/status", {"to_status": "STOCK", "storage_location": "ชั้น 3"})
    assert blocked.status_code == 409 and blocked.json()["error"]["details"]["reason"] == "PEER_LOCATION_UNKNOWN"
    await post(client, f"{c}/identifiers", {"serial_number": "SN-I3"})
    assert b and (await post(client, f"{a}/status", {"to_status": "STOCK",
                                                     "storage_location": "ชั้น 3"})).status_code == 200


@pytest.mark.asyncio
async def test_identifiers_are_set_once_unique_and_retry_safe(client: AsyncClient) -> None:
    a = (await create(client))["instance"]["part_instance_id"]
    b = (await create(client))["instance"]["part_instance_id"]
    headers = rid()
    first = await post(client, f"{a}/identifiers", {"serial_number": "SN-ONCE"}, headers)
    assert first.status_code == 200
    assert (await post(client, f"{a}/identifiers", {"serial_number": "SN-ONCE"}, headers)).json() == first.json()
    twice = await post(client, f"{a}/identifiers", {"serial_number": "SN-OTHER"})
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "PART_IDENTIFIER_ALREADY_SET"
    dup = await post(client, f"{b}/identifiers", {"serial_number": "SN-ONCE"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "PART_INVARIANT_DUPLICATE_SERIAL"
    assert (await post(client, f"{b}/identifiers", {})).status_code == 422
    dup_create = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": PART, "serial_number": "SN-ONCE", "prior_usage": {"quality": "UNKNOWN"}})
    assert dup_create.status_code == 409


# ---------------------------------------------------------------------------
# Historical declarations (T-PU-01 … T-PU-16)
# ---------------------------------------------------------------------------


GOOD = {"quality": "KNOWN", "value": 300, "basis": "ENGINE_HOUR", "component_role": "CARRIER_ENGINE",
        "as_of": "2026-01-01", "evidence_type": "DOCUMENT", "evidence_reference": "free text ref"}


@pytest.mark.asyncio
@pytest.mark.parametrize("prior,code", [
    ({"quality": "KNOWN", "value": 10}, "HISTORICAL_USAGE_EVIDENCE_REQUIRED"),            # T-PU-01
    (GOOD | {"basis": "PTO_HOUR", "component_role": "PTO"}, "BASIS_UNSUPPORTED"),         # T-PU-02
    (GOOD | {"basis": "CYCLE", "component_role": None}, "BASIS_UNSUPPORTED"),
    ({"quality": "UNKNOWN", "value": 5}, "HISTORICAL_USAGE_VALUE_FOR_UNKNOWN"),          # T-PU-03
    (GOOD | {"evidence_type": "NEW_PART", "value": 5}, "HISTORICAL_USAGE_CONTRADICTION"),  # T-PU-06
    (GOOD | {"as_of": "2099-01-01"}, "HISTORICAL_USAGE_AS_OF_IN_FUTURE"),                 # T-PU-07
    (GOOD | {"evidence_type": "WORK_ORDER", "evidence_reference": "NOPE"}, "EVIDENCE_REFERENCE_NOT_FOUND"),
    (GOOD | {"value": -1}, "HISTORICAL_USAGE_VALUE_INVALID"),
    (GOOD | {"component_role": None}, "BASIS_COMPONENT_ROLE_REQUIRED"),
])
async def test_invalid_historical_declarations_are_refused(client: AsyncClient, prior, code) -> None:
    r = await client.post("/api/v1/part-instances", json={"part_id": PART, "prior_usage": prior}, headers=rid())
    assert r.status_code == 422 and r.json()["error"]["code"] == code


@pytest.mark.asyncio
async def test_t_pu_04_05_contradictory_pairs_are_refused(client: AsyncClient) -> None:
    r = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": PART, "prior_usage": GOOD, "prior_cycle_usage": GOOD | {"value": 400}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "HISTORICAL_USAGE_CONTRADICTION"
    r = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": PART, "prior_usage": {"quality": "UNKNOWN"}, "prior_cycle_usage": GOOD})
    assert r.status_code == 422 and r.json()["error"]["code"] == "HISTORICAL_USAGE_CONTRADICTION"


@pytest.mark.asyncio
async def test_t_pu_08_to_16_levels_server_fields_and_policy(client: AsyncClient) -> None:
    rep = await repair_id(client)
    # T-PU-10 / T-PU-15: server-derived fields cannot be supplied by the body.
    forged = GOOD | {"declared_by": "attacker", "reference_status": "RESOLVED", "verification_level": "VERIFIED",
                     "policy_state": "APPROVED"}
    r = await client.post("/api/v1/part-instances", json={"part_id": PART, "prior_usage": forged}, headers=rid())
    assert r.status_code == 200, r.text
    stored = r.json()["instance"]["prior_usage"]
    assert stored["declared_by"] == "dev-user" and stored["reference_status"] == "REFERENCE_UNVERIFIED"
    status = (await client.get(f"/api/v1/part-instances/{r.json()['instance']['part_instance_id']}/lifetime-status"))
    assert status.json()["declarations"]["prior_usage"]["verification_level"] == "DECLARED"   # T-PU-11
    # T-PU-12: a resolving reference is EVIDENCE_REFERENCED (record exists, value not proven).
    ref = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": PART, "prior_usage": GOOD | {"evidence_type": "WORK_ORDER", "evidence_reference": rep}})
    ref_status = (await client.get(
        f"/api/v1/part-instances/{ref.json()['instance']['part_instance_id']}/lifetime-status")).json()
    assert ref_status["declarations"]["prior_usage"]["verification_level"] == "EVIDENCE_REFERENCED"
    # T-PU-13 / T-PU-14: NEW_PART 0 is VERIFIED only with a resolving reference.
    new = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": PART, "prior_usage": {"quality": "KNOWN", "value": 0, "as_of": "2026-01-01",
                                         "evidence_type": "NEW_PART", "evidence_reference": rep}})
    new_status = (await client.get(
        f"/api/v1/part-instances/{new.json()['instance']['part_instance_id']}/lifetime-status")).json()
    assert new_status["declarations"]["prior_usage"]["verification_level"] == "VERIFIED"
    free_new = await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": PART, "prior_usage": {"quality": "KNOWN", "value": 0, "as_of": "2026-01-01",
                                         "evidence_type": "NEW_PART", "evidence_reference": "receipt in drawer"}})
    free_status = (await client.get(
        f"/api/v1/part-instances/{free_new.json()['instance']['part_instance_id']}/lifetime-status")).json()
    assert free_status["declarations"]["prior_usage"]["verification_level"] == "DECLARED"
    assert all(c["verified_lifetime_total"]["value"] is None for c in free_status["counters"])


@pytest.mark.asyncio
async def test_t_pu_16_policy_state_comes_only_from_the_server_context() -> None:
    from app.domain.part_lifetime_status_service import PartLifetimeStatusService
    from app.domain.part_instance_service import PartInstanceService
    from app.domain.meter_service import MeterService
    from app.domain.technician_assignment import AssignmentCutover
    from app.domain.part_instance import PriorUsage
    from app.repositories.mock import MockRepository

    repo = MockRepository()
    cut = AssignmentCutover("TEST", "MOCK-7O2B-SYNTHETIC")
    service = PartInstanceService(repo, MeterService(repo), cut)
    detail_ = await service.create_instance(PART, None, PriorUsage(quality="UNKNOWN"), None, "u", tag_label="T-16",
                                            prior_cycle_usage=None)
    iid = detail_["instance"]["part_instance_id"]
    test_view = await PartLifetimeStatusService(repo, MeterService(repo), cut).instance_status(iid)
    real_view = await PartLifetimeStatusService(repo, MeterService(repo), AssignmentCutover("REAL", "")).instance_status(iid)
    assert test_view["policy_context"] == "TEST" and real_view["policy_context"] == "REAL"
