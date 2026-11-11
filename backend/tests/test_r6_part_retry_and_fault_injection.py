"""R6 — idempotency, copy-on-write atomicity, fault injection and single-process
concurrency (FINAL plan §7.2a step 6, §7.6; R3-02; F-01, F-05).

These are MOCK guarantees only (single process, in memory): durable,
cross-process transactions are R11 PostgreSQL and are NOT proven here."""
from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient

V = "VEH-1048"
PART = "PART-0005"
STAGES_BEFORE_PUBLISH = ("after_copy", "after_apply", "after_validate", "before_publish")


def rid() -> dict:
    return {"X-Request-Id": str(uuid.uuid4())}


def repo():
    from app.dependencies import get_repository

    return get_repository()


async def tagged(client: AsyncClient, **extra) -> str:
    r = await client.post("/api/v1/part-instances", headers=rid(),
                          json={"part_id": PART, "tag_label": f"TAG-{uuid.uuid4()}",
                                "prior_usage": {"quality": "UNKNOWN"}} | extra)
    assert r.status_code == 200, r.text
    return r.json()["instance"]["part_instance_id"]


async def repair_id(client: AsyncClient) -> str:
    r = await client.post("/api/v1/repairs", json={"asset_type": "VEHICLE", "asset_id": V, "source_type": "MANUAL",
                                                  "symptom": "ทดสอบ"})
    return r.json()["repair"]["repair_id"]


REPLAYED = "X-Request-Replayed"


def _snapshot(state) -> dict:
    return {name: dict(getattr(state, name)) for name in (
        "instances", "lifecycles", "segments", "status_events", "positions", "maintenance", "requests", "masters",
        "rules", "applicability")}


# ---------------------------------------------------------------------------
# Replay / conflict for every write
# ---------------------------------------------------------------------------


async def _writes(client: AsyncClient) -> list[tuple[str, str, dict]]:
    """(path, method, body) of each R6 write, each prepared so it can succeed."""
    installed = await tagged(client)
    await client.post(f"/api/v1/part-instances/{installed}/install", headers=rid(),
                      json={"asset_type": "VEHICLE", "asset_id": V, "position_code": "R-1"})
    ready = await tagged(client)
    repairing = await tagged(client)
    await client.post(f"/api/v1/part-instances/{repairing}/status", headers=rid(), json={"to_status": "IN_REPAIR"})
    unidentified = (await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": PART, "prior_usage": {"quality": "UNKNOWN"}})).json()["instance"]["part_instance_id"]
    inspect_rule = (await client.post("/api/v1/lifetime-rules", json={
        "part_id": PART, "scope": "MODEL", "model_id": "MODEL-0003", "trigger_type": "ENGINE_HOUR",
        "component_role": "CARRIER_ENGINE", "interval_value": 10, "interval_unit": "HOUR",
        "due_action": "INSPECT"})).json()["lifetime_rule_id"]
    position = (await client.post("/api/v1/position-lifetime", json={
        "asset_type": "VEHICLE", "asset_id": V, "position_code": "SEAL-R", "part_id": "PART-0004",
        "prior_usage": {"quality": "UNKNOWN"}})).json()["position_lifetime_id"]
    part_set = (await client.post("/api/v1/part-sets", json={"set_code": f"S-{uuid.uuid4()}", "name": "x"})).json()[
        "part_set_id"]
    # CG-2: the four remaining request-id write routes, so every route that sets X-Request-Replayed is covered.
    moving = await tagged(client)
    await client.post(f"/api/v1/part-instances/{moving}/install", headers=rid(),
                      json={"asset_type": "VEHICLE", "asset_id": V, "position_code": f"MV-{uuid.uuid4()}"})
    stocked = await tagged(client)
    inspect_position = (await client.post("/api/v1/position-lifetime", json={
        "asset_type": "VEHICLE", "asset_id": V, "position_code": f"SEAL-I-{uuid.uuid4()}", "part_id": "PART-0004",
        "prior_usage": {"quality": "UNKNOWN"}})).json()["position_lifetime_id"]
    position_rule = (await client.post("/api/v1/lifetime-rules", json={
        "part_id": "PART-0004", "scope": "MODEL", "model_id": "MODEL-0003", "trigger_type": "ENGINE_HOUR",
        "component_role": "CARRIER_ENGINE", "interval_value": 10, "interval_unit": "HOUR",
        "due_action": "INSPECT"})).json()["lifetime_rule_id"]
    await client.post("/api/v1/parts/PART-0002/deactivate", headers=rid(), json={"reason": "prepare"})
    return [
        (f"/api/v1/part-instances/{moving}/transfer", "POST", {"target_asset_type": "EQUIPMENT",
                                                              "target_asset_id": "EQP-0002"}),
        (f"/api/v1/part-instances/{stocked}/status", "POST", {"to_status": "STOCK", "storage_location": "S9"}),
        (f"/api/v1/position-lifetime/{inspect_position}/maintenance-events", "POST",
         {"action": "INSPECTED", "lifetime_rule_id": position_rule}),
        ("/api/v1/parts/PART-0002/reactivate", "POST", {"reason": "ทดสอบ"}),
        ("/api/v1/part-instances", "POST", {"part_id": PART, "prior_usage": {"quality": "UNKNOWN"},
                                            "tag_label": f"TAG-R-{uuid.uuid4()}"}),
        (f"/api/v1/part-instances/{ready}/install", "POST", {"asset_type": "VEHICLE", "asset_id": V}),
        (f"/api/v1/part-instances/{installed}/remove", "POST", {"next_status": "STOCK", "storage_location": "S1"}),
        (f"/api/v1/part-instances/{repairing}/return-from-repair", "POST", {"outcome": "ok"}),
        (f"/api/v1/part-instances/{unidentified}/identifiers", "POST", {"tag_label": f"TAG-ID-{uuid.uuid4()}"}),
        (f"/api/v1/part-instances/{ready}/maintenance-events", "POST", {"action": "INSPECTED",
                                                                       "lifetime_rule_id": inspect_rule}),
        (f"/api/v1/position-lifetime/{position}/replace", "POST", {"prior_usage": {"quality": "UNKNOWN"}}),
        ("/api/v1/position-lifetime", "POST", {"asset_type": "VEHICLE", "asset_id": V, "position_code": "SEAL-NEW",
                                               "part_id": "PART-0004", "prior_usage": {"quality": "UNKNOWN"}}),
        ("/api/v1/parts", "POST", {"part_code": f"RP-{uuid.uuid4()}", "name": "x", "tracking_mode": "NONE"}),
        ("/api/v1/parts/PART-0001/deactivate", "POST", {"reason": "ทดสอบ"}),
        (f"/api/v1/part-sets/{part_set}/applicability", "POST", {"model_id": "MODEL-0003",
                                                                "effective_from": "2026-01-01"}),
        ("/api/v1/lifetime-rules", "POST", {"part_id": PART, "scope": "MODEL", "model_id": "MODEL-0003",
                                            "trigger_type": "ODOMETER", "interval_value": 5,
                                            "interval_unit": "KM", "due_action": "REPLACE"}),
    ]


def _alternate(path: str, body: dict) -> dict:
    """A different, still schema-valid intent for the same request id."""
    if path.endswith("/deactivate") or path.endswith("/reactivate"):
        return {"reason": "อีกเหตุผลหนึ่ง"}
    if path.endswith("/transfer"):
        return body | {"position_code": "DIFFERENT"}
    if path.endswith("/status"):
        return body | {"storage_location": "DIFFERENT"}
    if path.endswith("/identifiers"):
        return {"tag_label": "TAG-DIFFERENT"}
    if path.endswith("/maintenance-events"):
        return body | {"outcome": "DIFFERENT"}
    if path.endswith("/applicability"):
        return body | {"document_ref": "DIFFERENT"}
    if path.endswith("/lifetime-rules"):
        return body | {"interval_value": 6}
    if path.endswith("/parts"):
        return body | {"name": "different"}
    if path.endswith("/remove"):
        return body | {"storage_location": "DIFFERENT"}
    return body | {"note": "different intent"}


@pytest.mark.asyncio
async def test_every_r6_write_replays_its_committed_response_and_refuses_a_reused_id(client: AsyncClient) -> None:
    writes = await _writes(client)
    assert len(writes) == 16  # every R6 route that honours the request-id / replay contract
    for path, method, body in writes:
        headers = rid()
        first = await client.request(method, path, json=body, headers=headers)
        assert first.status_code == 200, (path, first.text)
        assert REPLAYED not in first.headers, path  # CG-2: a first success is not a replay
        before = _snapshot(await repo().read_part_state())
        snapshots_before = len(repo()._meter_snapshots)
        again = await client.request(method, path, json=body, headers=headers)
        assert again.status_code == 200 and again.json() == first.json(), path
        assert again.headers.get(REPLAYED) == "true", path  # CG-2: the stored response, acknowledged
        assert _snapshot(await repo().read_part_state()) == before, path  # replay writes nothing
        assert len(repo()._meter_snapshots) == snapshots_before, path  # ... and captures nothing
        conflict = await client.request(method, path, json=_alternate(path, body), headers=headers)
        assert conflict.status_code == 409, (path, conflict.text)
        assert conflict.json()["error"]["code"] == "PART_REQUEST_CONFLICT", path
        assert REPLAYED not in conflict.headers, path
        assert _snapshot(await repo().read_part_state()) == before, path


@pytest.mark.asyncio
async def test_new_routes_require_a_request_id(client: AsyncClient) -> None:
    iid = await tagged(client)
    r = await client.post(f"/api/v1/part-instances/{iid}/status", json={"to_status": "STOCK"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REQUEST_ID_REQUIRED"


# ---------------------------------------------------------------------------
# Fault injection F-H1 … F-H5
# ---------------------------------------------------------------------------


async def _operations(client: AsyncClient) -> list[tuple[str, dict]]:
    a = await tagged(client)
    b = await tagged(client)
    await client.post(f"/api/v1/part-instances/{b}/install", headers=rid(), json={"asset_type": "VEHICLE", "asset_id": V})
    b2 = await tagged(client)
    await client.post(f"/api/v1/part-instances/{b2}/install", headers=rid(), json={"asset_type": "VEHICLE",
                                                                                 "asset_id": V})
    c = await tagged(client)
    await client.post(f"/api/v1/part-instances/{c}/status", headers=rid(), json={"to_status": "IN_REPAIR"})
    d = (await client.post("/api/v1/part-instances", headers=rid(), json={
        "part_id": PART, "prior_usage": {"quality": "UNKNOWN"}})).json()["instance"]["part_instance_id"]
    position = (await client.post("/api/v1/position-lifetime", json={
        "asset_type": "VEHICLE", "asset_id": V, "position_code": "F-SEAL", "part_id": "PART-0004",
        "prior_usage": {"quality": "UNKNOWN"}})).json()["position_lifetime_id"]
    rep = await repair_id(client)
    return [
        (f"/api/v1/part-instances/{a}/install", {"asset_type": "VEHICLE", "asset_id": V, "position_code": "F-1"}),
        (f"/api/v1/part-instances/{b}/remove", {"next_status": "STOCK", "storage_location": "S"}),
        (f"/api/v1/part-instances/{b2}/transfer", {"target_asset_type": "EQUIPMENT", "target_asset_id": "EQP-0002"}),
        (f"/api/v1/part-instances/{c}/return-from-repair", {"repair_reference": rep, "new_cycle_approved": True,
                                                           "approval_reason_code": "TEST-F"}),
        (f"/api/v1/position-lifetime/{position}/replace", {"prior_usage": {"quality": "UNKNOWN"}}),
        (f"/api/v1/part-instances/{d}/identifiers", {"serial_number": f"SN-F-{uuid.uuid4()}"}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", STAGES_BEFORE_PUBLISH)
async def test_a_fault_before_publication_leaves_nothing_partial_and_a_retry_converges(client: AsyncClient,
                                                                                      stage) -> None:
    for path, body in await _operations(client):
        repository = repo()
        before = await repository.read_part_state()
        headers = rid()
        def hook(s: str) -> None:
            if s == stage:
                raise RuntimeError(f"injected at {stage}")
        repository.part_fault_hook = hook
        with pytest.raises(RuntimeError):
            await client.post(path, json=body, headers=headers)
        repository.part_fault_hook = None
        after = await repository.read_part_state()
        assert after is before, (stage, path)  # the published state object is untouched
        retry = await client.post(path, json=body, headers=headers)
        assert retry.status_code == 200, (stage, path, retry.text)
        assert (await client.post(path, json=body, headers=headers)).json() == retry.json()


@pytest.mark.asyncio
async def test_f_h5_lost_response_after_publication_replays_the_committed_outcome(client: AsyncClient) -> None:
    for path, body in await _operations(client):
        repository = repo()
        headers = rid()
        def hook(s: str) -> None:
            if s == "after_publish":
                raise RuntimeError("response lost")
        repository.part_fault_hook = hook
        with pytest.raises(RuntimeError):
            await client.post(path, json=body, headers=headers)
        repository.part_fault_hook = None
        committed = await repository.read_part_state()
        retry = await client.post(path, json=body, headers=headers)
        assert retry.status_code == 200, (path, retry.text)
        assert retry.headers.get(REPLAYED) == "true", path  # CG-2: the lost commit is acknowledged as a replay
        assert await repository.read_part_state() is committed, path  # replay: no second write


@pytest.mark.asyncio
async def test_f01_interrupted_install_can_no_longer_produce_two_active_segments(client: AsyncClient) -> None:
    iid = await tagged(client)
    repository = repo()
    def hook(s: str) -> None:
        if s == "after_apply":
            raise RuntimeError("crash between the segment and the status")
    repository.part_fault_hook = hook
    with pytest.raises(RuntimeError):
        await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(), json={"asset_type": "VEHICLE",
                                                                                       "asset_id": V})
    repository.part_fault_hook = None
    detail = (await client.get(f"/api/v1/part-instances/{iid}")).json()
    assert detail["segments"] == [] and detail["instance"]["status"] == "READY_FOR_INSTALL"
    assert (await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                              json={"asset_type": "VEHICLE", "asset_id": V})).status_code == 200
    second = await client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                               json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0002"})
    assert second.status_code == 422
    detail = (await client.get(f"/api/v1/part-instances/{iid}")).json()
    assert sum(s["status"] == "ACTIVE" for s in detail["segments"]) == 1


@pytest.mark.asyncio
async def test_invariant_violation_at_commit_publishes_nothing() -> None:
    from app.repositories.base import PART_SEGMENTS, PartMutation, PartMutationRejected
    from app.repositories.mock import MockRepository
    from app.domain.part_instance import InstallationSegment, InstallationSegmentStatus, PriorUsage
    from app.domain.asset import AssetType
    from datetime import datetime, timezone

    repository = MockRepository()
    created = await repository.create_part_instance(PART, None, PriorUsage(quality="UNKNOWN"), None, "u")
    iid = created.instance.part_instance_id
    seg = lambda n: InstallationSegment(segment_id=f"S{n}", part_instance_id=iid, lifecycle_id=created.lifecycles[0].lifecycle_id,  # noqa: E731
                                        asset_type=AssetType.VEHICLE, asset_id=V, status=InstallationSegmentStatus.ACTIVE,
                                        installed_at=datetime.now(timezone.utc))
    before = await repository.read_part_state()
    with pytest.raises(PartMutationRejected) as rejected:
        await repository.apply_part_mutation(PartMutation(puts={PART_SEGMENTS: {iid: (seg(1), seg(2))}}))
    assert rejected.value.code == "PART_INVARIANT_DOUBLE_ACTIVE_INSTALLATION"
    assert await repository.read_part_state() is before


# ---------------------------------------------------------------------------
# Single-process concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_installs_returns_and_replacements_commit_exactly_once(client: AsyncClient) -> None:
    iid = await tagged(client)
    results = await asyncio.gather(*[
        client.post(f"/api/v1/part-instances/{iid}/install", headers=rid(),
                    json={"asset_type": "VEHICLE", "asset_id": V, "position_code": f"C-{n}"}) for n in range(5)])
    assert sum(r.status_code == 200 for r in results) == 1
    assert all(r.status_code in (409, 422) for r in results if r.status_code != 200)
    detail = (await client.get(f"/api/v1/part-instances/{iid}")).json()
    assert sum(s["status"] == "ACTIVE" for s in detail["segments"]) == 1

    repairing = await tagged(client)
    await client.post(f"/api/v1/part-instances/{repairing}/status", headers=rid(), json={"to_status": "IN_REPAIR"})
    rep = await repair_id(client)
    returns = await asyncio.gather(*[
        client.post(f"/api/v1/part-instances/{repairing}/return-from-repair", headers=rid(),
                    json={"repair_reference": rep, "new_cycle_approved": True, "approval_reason_code": "TEST-C"})
        for _ in range(4)])
    assert sum(r.status_code == 200 for r in returns) == 1
    installs = await asyncio.gather(*[
        client.post(f"/api/v1/part-instances/{repairing}/install", headers=rid(),
                    json={"asset_type": "VEHICLE", "asset_id": V, "position_code": f"D-{n}"}) for n in range(4)])
    assert sum(r.status_code == 200 for r in installs) == 1
    assert len((await client.get(f"/api/v1/part-instances/{repairing}")).json()["lifecycles"]) == 2

    position = (await client.post("/api/v1/position-lifetime", json={
        "asset_type": "VEHICLE", "asset_id": V, "position_code": "C-SEAL", "part_id": "PART-0004",
        "prior_usage": {"quality": "UNKNOWN"}})).json()["position_lifetime_id"]
    replaces = await asyncio.gather(*[
        client.post(f"/api/v1/position-lifetime/{position}/replace", headers=rid(),
                    json={"prior_usage": {"quality": "UNKNOWN"}}) for _ in range(4)])
    assert sum(r.status_code == 200 for r in replaces) == 1
    active = [r for r in (await repo().read_part_state()).positions.values()
              if r.position_code == "C-SEAL" and r.ended_at is None]
    assert len(active) == 1



# ---------------------------------------------------------------------------
# CG-2: X-Request-Replayed isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cg2_distinct_requests_never_inherit_a_replay_flag(client: AsyncClient) -> None:
    iid = await tagged(client)
    headers = rid()
    body = {"to_status": "STOCK", "storage_location": f"S-{uuid.uuid4()}"}
    await client.post(f"/api/v1/part-instances/{iid}/status", headers=headers, json=body)
    replay = await client.post(f"/api/v1/part-instances/{iid}/status", headers=headers, json=body)
    assert replay.headers.get(REPLAYED) == "true"
    # Immediately afterwards, an unrelated request (new id) and a read: no flag.
    other = await tagged(client)
    fresh = await client.post(f"/api/v1/part-instances/{other}/status", headers=rid(),
                              json={"to_status": "STOCK", "storage_location": f"S-{uuid.uuid4()}"})
    assert fresh.status_code == 200 and REPLAYED not in fresh.headers
    assert REPLAYED not in (await client.get(f"/api/v1/part-instances/{iid}")).headers


@pytest.mark.asyncio
async def test_cg2_a_refused_request_leaves_no_record_and_never_marks_a_later_request(client: AsyncClient) -> None:
    iid = await tagged(client)
    headers = rid()
    refused = await client.post(f"/api/v1/part-instances/{iid}/install", headers=headers,
                                json={"asset_type": "VEHICLE", "asset_id": "VEH-1046"})  # REAL vehicle: refused
    assert refused.status_code == 422 and REPLAYED not in refused.headers
    key_count = len((await repo().read_part_state()).requests)
    # The same id may now carry a valid intent: it executes as a FIRST request (nothing was recorded).
    ok = await client.post(f"/api/v1/part-instances/{iid}/install", headers=headers,
                           json={"asset_type": "VEHICLE", "asset_id": V, "position_code": f"OK-{uuid.uuid4()}"})
    assert ok.status_code == 200 and REPLAYED not in ok.headers
    assert len((await repo().read_part_state()).requests) == key_count + 1


@pytest.mark.asyncio
async def test_cg2_concurrent_duplicates_commit_once_and_only_the_loser_is_marked(client: AsyncClient) -> None:
    iid = await tagged(client)
    headers = rid()
    body = {"asset_type": "VEHICLE", "asset_id": V, "position_code": f"CC-{uuid.uuid4()}"}
    results = await asyncio.gather(*[client.post(f"/api/v1/part-instances/{iid}/install", headers=headers, json=body)
                                     for _ in range(4)])
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert len({r.text for r in results}) == 1  # every caller sees the one committed response
    assert sum(REPLAYED not in r.headers for r in results) == 1  # exactly one original
    assert sum(r.headers.get(REPLAYED) == "true" for r in results) == 3
    detail = (await client.get(f"/api/v1/part-instances/{iid}")).json()
    assert len(detail["segments"]) == 1


@pytest.mark.asyncio
async def test_cg2_replay_marker_is_safe_outside_http_and_never_global() -> None:
    """The marker is the result's own type: a replayed result stays marked, the next first-time result is not,
    and no state outlives a call (service used directly, no request context)."""
    from app.domain.meter_service import MeterService
    from app.domain.part_instance import PriorUsage
    from app.domain.part_instance_service import PartInstanceService, is_replayed
    from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
    from app.domain.technician_assignment import AssignmentCutover
    from app.repositories.mock import MockRepository

    repository = MockRepository()
    service = PartInstanceService(repository, MeterService(repository), AssignmentCutover("TEST", MOCK_TEST_BATCH_ID))
    kwargs = dict(tag_label=f"T-{uuid.uuid4()}", request_id=str(uuid.uuid4()), body={"k": 1})
    first = await service.create_instance("PART-0005", None, PriorUsage(quality="UNKNOWN"), None, "u", **kwargs)
    again = await service.create_instance("PART-0005", None, PriorUsage(quality="UNKNOWN"), None, "u", **kwargs)
    other = await service.create_instance("PART-0005", None, PriorUsage(quality="UNKNOWN"), None, "u",
                                          tag_label=f"T-{uuid.uuid4()}", request_id=str(uuid.uuid4()), body={"k": 2})
    assert (is_replayed(first), is_replayed(again), is_replayed(other)) == (False, True, False)
    assert dict(again) == dict(first)


@pytest.mark.asyncio
async def test_cg2_a_replay_detected_inside_the_commit_is_marked(client: AsyncClient) -> None:
    """The race the early check cannot see (mutant CG2-M2): the duplicate read the part state BEFORE the first
    request published, so it passes the service-level replay lookup and reaches the commit, where the repository
    finds the request record and returns the committed response. That reply must still be marked, and nothing is
    written twice."""
    repository = repo()
    iid = await tagged(client)
    headers = rid()
    body = {"asset_type": "VEHICLE", "asset_id": V, "position_code": f"RACE-{uuid.uuid4()}"}
    stale = await repository.read_part_state()
    first = await client.post(f"/api/v1/part-instances/{iid}/install", headers=headers, json=body)
    assert first.status_code == 200 and REPLAYED not in first.headers
    committed = await repository.read_part_state()

    async def stale_read():
        return stale

    repository.read_part_state = stale_read  # the duplicate's view predates the first commit
    try:
        second = await client.post(f"/api/v1/part-instances/{iid}/install", headers=headers, json=body)
    finally:
        del repository.read_part_state
    assert second.status_code == 200, second.text
    assert second.headers.get(REPLAYED) == "true"
    assert second.json() == first.json()
    assert await repository.read_part_state() is committed  # the commit published nothing new
