"""R5 T6 — Repair retry safety (Revision 4 §8 rows 5–9): optional X-Request-Id on
actions, actual parts and CLOSE; an identical retry returns the original result and
writes nothing; a conflicting reuse is refused; an interrupted close reuses its
capture; without the header the pre-R5 behaviour is unchanged."""
from __future__ import annotations

import pytest

from app.domain.asset import AssetType
from app.domain.repair import RepairStatus
from tests.test_r5_work_time_api import MANAGER, U1, repair_job, repair_manager, rid
from tests.test_technician_assignment_batch_r2f_h1 import code_of, http, repair_service, repo_with


async def close_snapshots(repo, asset_id: str) -> list:
    return [s for s in await repo.list_meter_snapshots_for_asset(AssetType.VEHICLE, asset_id)
            if s.source_note == "REPAIR_CLOSE"]


@pytest.mark.asyncio
async def test_action_retry_with_the_same_request_id_appends_once_and_reuse_is_refused() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    request_id = rid()
    path = f"/api/v1/repairs/{job}/actions"
    first = await http("POST", path, repo, role="TECHNICIAN", user=U1, json={"action_text": "ถอดชุดปั๊ม"},
                       request_id=request_id)
    again = await http("POST", path, repo, role="TECHNICIAN", user=U1, json={"action_text": "ถอดชุดปั๊ม"},
                       request_id=request_id)  # the response of the first was "lost"
    assert first.status_code == again.status_code == 200
    assert len(again.json()["actions"]) == 1
    conflict = await http("POST", path, repo, role="TECHNICIAN", user=U1, json={"action_text": "อื่น"},
                          request_id=request_id)
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "REPAIR_REQUEST_CONFLICT")
    invalid = await http("POST", path, repo, role="TECHNICIAN", user=U1, json={"action_text": "x"},
                         request_id="not-a-uuid")
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (422, "REQUEST_ID_INVALID")
    assert len((await repo.get_repair(job)).actions) == 1


@pytest.mark.asyncio
async def test_part_retry_with_the_same_request_id_records_the_part_once() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    request_id = rid()
    body = {"part_description": "ซีลยาง", "quantity": 2, "unit": "ชิ้น"}
    for _ in range(3):
        response = await http("POST", f"/api/v1/repairs/{job}/parts", repo, role="TECHNICIAN", user=U1, json=body,
                              request_id=request_id)
        assert response.status_code == 200
    assert len((await repo.get_repair(job)).parts) == 1


@pytest.mark.asyncio
async def test_without_the_header_the_pre_r5_behaviour_is_unchanged() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    for _ in range(2):
        response = await http("POST", f"/api/v1/repairs/{job}/actions", repo, role="TECHNICIAN", user=U1,
                              json={"action_text": "ตรวจสอบ"}, request_id=None)
        assert response.status_code == 200
    assert len((await repo.get_repair(job)).actions) == 2
    closed = await http("POST", f"/api/v1/repairs/{job}/close", repo, role="MAINTENANCE", json={}, request_id=None)
    assert closed.status_code == 200
    again = await http("POST", f"/api/v1/repairs/{job}/close", repo, role="MAINTENANCE", json={}, request_id=None)
    assert (again.status_code, again.json()["error"]["code"]) == (422, "REPAIR_ALREADY_CLOSED")


@pytest.mark.asyncio
async def test_repeated_close_with_the_same_request_id_returns_the_closed_record_and_one_snapshot() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    asset = (await repo.get_repair(job)).repair.asset_id
    request_id = rid()
    first = await http("POST", f"/api/v1/repairs/{job}/close", repo, role="MAINTENANCE", json={"close_note": "ok"},
                       request_id=request_id)
    again = await http("POST", f"/api/v1/repairs/{job}/close", repo, role="MAINTENANCE", json={"close_note": "ok"},
                       request_id=request_id)
    assert first.status_code == again.status_code == 200
    assert again.json()["repair"]["closed_snapshot_id"] == first.json()["repair"]["closed_snapshot_id"]
    assert len(await close_snapshots(repo, asset)) == 1
    conflict = await http("POST", f"/api/v1/repairs/{job}/close", repo, role="MAINTENANCE",
                          json={"close_note": "อื่น"}, request_id=request_id)
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "REPAIR_REQUEST_CONFLICT")


@pytest.mark.asyncio
async def test_interrupted_close_after_the_capture_is_recovered_by_the_retry_with_one_snapshot() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    asset = (await repo.get_repair(job)).repair.asset_id
    original = repo.close_repair_once
    state = {"fail": True}

    async def interrupted(*args, **kwargs):
        if state["fail"]:
            state["fail"] = False
            raise ConnectionError("simulated: the close write was lost after the snapshot was captured")
        return await original(*args, **kwargs)

    repo.close_repair_once = interrupted
    request_id = rid()
    service = repair_service(repo)
    with pytest.raises(ConnectionError):
        await service.close_repair(job, closed_by=MANAGER, close_note=None, context=repair_manager(),
                                   request_id=request_id)
    assert (await repo.get_repair(job)).repair.status == RepairStatus.OPEN
    captured = await close_snapshots(repo, asset)
    assert len(captured) == 1  # the capture exists, the close does not
    closed = await service.close_repair(job, closed_by=MANAGER, close_note=None, context=repair_manager(),
                                        request_id=request_id)
    assert closed.repair.status == RepairStatus.CLOSED
    assert closed.repair.closed_snapshot_id == captured[0].meter_snapshot_id
    assert len(await close_snapshots(repo, asset)) == 1  # reused, never captured twice


@pytest.mark.asyncio
async def test_failure_before_the_append_writes_nothing_and_the_retry_records_once() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    original = repo.add_repair_action
    state = {"fail": True}

    async def failing(**kwargs):
        if state["fail"]:
            state["fail"] = False
            raise ConnectionError("simulated: the append request failed before reaching storage")
        return await original(**kwargs)

    repo.add_repair_action = failing
    request_id = rid()
    service = repair_service(repo)
    with pytest.raises(ConnectionError):
        await service.add_action(job, "ถอดชุดปั๊ม", U1, [], request_id=request_id)
    assert (await repo.get_repair(job)).actions == []
    assert await repo.get_repair_request_record(job, request_id) is None
    await service.add_action(job, "ถอดชุดปั๊ม", U1, [], request_id=request_id)
    await service.add_action(job, "ถอดชุดปั๊ม", U1, [], request_id=request_id)
    assert len((await repo.get_repair(job)).actions) == 1


@pytest.mark.asyncio
async def test_a_replay_after_the_round_froze_still_returns_the_original_result() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    service = repair_service(repo)
    request_id = rid()
    await service.add_action(job, "ตรวจสอบ", U1, [], request_id=request_id)
    await service.close_repair(job, closed_by=MANAGER, close_note=None, context=repair_manager())
    replay = await service.add_action(job, "ตรวจสอบ", U1, [], request_id=request_id)
    assert len(replay.actions) == 1
    assert await code_of(service.add_action(job, "อื่น", U1, [], request_id=rid())) == "REPAIR_ROUND_FROZEN"


@pytest.mark.asyncio
async def test_replay_bookkeeping_never_disturbs_the_repair_request_store() -> None:
    """Regression (found by the combined browser flow): the Repair replay map is a separate store;
    a replay-protected write must not corrupt the existing Repair Request listing."""
    repo = repo_with()
    job = await repair_job(repo)
    before = await repo.list_repair_requests_by_source("FINDING", "FND-NONE")
    await repair_service(repo).add_action(job, "ตรวจสอบ", U1, [], request_id=rid())
    assert await repo.list_repair_requests_by_source("FINDING", "FND-NONE") == before
    response = await http("GET", "/api/v1/repair-requests/by-source/FINDING/FND-NONE", repo,
                          role="MAINTENANCE")
    assert response.status_code != 500, response.text
