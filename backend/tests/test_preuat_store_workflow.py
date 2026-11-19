"""R8 PRE-UAT (Owner source approval Rev 1, Decision 1) — repair material (Store) workflow.

Synthetic Mock/TEST only (Access Management mode, per-employee TEST grants). Covers the
complete request → approve/deny → issue → use → return → accept → reconcile path, replay
and duplicate safety (no double ISSUED), quantity guards, permissions, mode isolation
(REAL 409 / Sheets 501) and the future stock-integration event contract fields.
Not PostgreSQL evidence: the journal guard is one-process (R11)."""
from __future__ import annotations

import uuid

import pytest

from app.domain.store_workflow import EVENT_COLUMNS, StoreWorkflowService
from app.domain.technician_assignment import AssignmentCutover
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryFeatureNotImplementedError
from tests import test_access_management as am

API = am.API
MGR, TECH1, TECH2, DRV1, CLERK = am.MGR, am.TECH1, am.TECH2, am.DRV1, am.CLERK
STORE_GRANTS = {"can_view": True, "can_manage_repair": True, "can_close_repair": True,
                "can_test_store_approve": True, "can_test_store_issue": True, "can_test_store_receive_return": True}


@pytest.fixture(autouse=True)
def am_env(monkeypatch):
    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)


async def open_repair(store, vehicle: str = "VEH-1047") -> str:
    assert (await am.grant(store, MGR, am.employee(MGR), STORE_GRANTS)).status_code == 200
    for tech in (TECH1, TECH2):
        await am.grant(store, MGR, am.employee(tech), {"can_view": True})
    opened = await am.http("POST", f"{API}/repairs", store, MGR,
                           json={"asset_type": "VEHICLE", "asset_id": vehicle, "source_type": "MANUAL"})
    assert opened.status_code == 200, opened.text
    rid = opened.json()["repair"]["repair_id"]
    team = {"primary_technician_id": "TEC-TEST-911", "collaborator_technician_ids": ["TEC-TEST-912"],
            "expected_current": None}
    assigned = await am.http("POST", f"{API}/repairs/{rid}/technician-assignments", store, MGR, json=team)
    assert assigned.status_code == 200, assigned.text
    return rid


async def request_parts(store, rid: str, *, user=TECH1, request_id="auto", lines=None):
    body = {"lines": lines or [{"part_id": "PART-0001", "part_description": "ไส้กรองทดสอบ", "quantity": 2,
                                "unit": "ชิ้น"},
                               {"part_description": "สายรัดทดสอบ (ไม่มีรหัส)", "quantity": 1, "unit": "เส้น"}]}
    return await am.http("POST", f"{API}/repairs/{rid}/store-requests", store, user, json=body, request_id=request_id)


async def step(store, rid, line, path, body, user=MGR, request_id="auto"):
    return await am.http("POST", f"{API}/repairs/{rid}/store-lines/{line}/{path}", store, user, json=body,
                         request_id=request_id)


async def recon(store, rid, user=MGR):
    response = await am.http("GET", f"{API}/repairs/{rid}/store-reconciliation", store, user, request_id=None)
    assert response.status_code == 200, response.text
    return response.json()


async def test_full_material_workflow_reconciles_and_keeps_issued_used_returned_distinct() -> None:
    store = am.repo()
    rid = await open_repair(store)
    created = await request_parts(store, rid)
    assert created.status_code == 200, created.text
    events = created.json()["events"]
    assert [e["event_type"] for e in events] == ["REQUESTED", "REQUESTED"]
    line1, line2 = events[0]["requisition_line_id"], events[1]["requisition_line_id"]
    state = await recon(store, rid)
    assert state["state"] == "UNRECONCILED" and "LINE_AWAITING_DECISION" in state["blockers"]
    assert (await step(store, rid, line1, "approvals", {"quantity": 2})).status_code == 200
    denied = await step(store, rid, line2, "denials", {"reason": "ไม่มีในคลังทดสอบ"})
    assert denied.status_code == 200 and denied.json()["events"][0]["event_type"] == "DENIED"
    issued = await step(store, rid, line1, "issues", {"quantity": 2, "part_id": "PART-0001"})
    assert issued.status_code == 200, issued.text
    assert (await recon(store, rid))["blockers"] == ["ISSUED_NOT_USED_OR_RETURNED"]
    used = await step(store, rid, line1, "use-confirmations",
                      {"quantity": 1, "part_id": "PART-0001", "position_code": "ล้อหน้าซ้าย"}, user=TECH1)
    assert used.status_code == 200, used.text
    declared = await step(store, rid, line1, "return-declarations", {"quantity": 1, "part_id": "PART-0001", "reason": "เหลือใช้"}, user=TECH2)
    assert declared.status_code == 200, declared.text
    assert (await recon(store, rid))["blockers"] == ["ISSUED_NOT_USED_OR_RETURNED", "RETURN_NOT_ACCEPTED"]
    accepted = await step(store, rid, line1, "return-acceptances", {"quantity": 1, "part_id": "PART-0001"})
    assert accepted.status_code == 200, accepted.text
    final = await recon(store, rid)
    assert final["state"] == "RECONCILED" and final["blockers"] == []
    first = next(line for line in final["lines"] if line["requisition_line_id"] == line1)
    assert (first["requested"], first["approved"], first["issued"], first["used"], first["return_declared"],
            first["return_accepted"], first["unreconciled"]) == ("2", "2", "2", "1", "1", "1", "0")
    second = next(line for line in final["lines"] if line["requisition_line_id"] == line2)
    assert second["decision"] == "DENIED" and second["blockers"] == []


async def test_no_invented_return_when_everything_issued_was_used() -> None:
    store = am.repo()
    rid = await open_repair(store)
    line = (await request_parts(store, rid, lines=[{"part_id": "PART-0001", "part_description": "x", "quantity": 1,
                                                    "unit": "ชิ้น"}])).json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 1})
    await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0001"})
    await step(store, rid, line, "use-confirmations", {"quantity": 1, "part_id": "PART-0001", "position_code": "P1"},
               user=TECH1)
    final = await recon(store, rid)
    assert final["state"] == "RECONCILED"
    assert not any(e["event_type"].startswith("RETURN") for e in final["events"])


async def test_replay_returns_the_original_event_and_never_issues_twice() -> None:
    store = am.repo()
    rid = await open_repair(store)
    rq = str(uuid.uuid4())
    first = await request_parts(store, rid, request_id=rq)
    again = await request_parts(store, rid, request_id=rq)
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert [e["event_id"] for e in again.json()["events"]] == [e["event_id"] for e in first.json()["events"]]
    line = first.json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 2})
    issue_id = str(uuid.uuid4())
    one = await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"}, request_id=issue_id)
    two = await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"}, request_id=issue_id)
    assert two.json()["replayed"] is True and two.json()["events"][0]["event_id"] == one.json()["events"][0]["event_id"]
    issued = [e for e in (await recon(store, rid))["events"] if e["event_type"] == "ISSUED"]
    assert len(issued) == 1
    # A duplicate submission with a NEW id is refused by the quantity guard (no double deduction).
    dup = await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"})
    assert am.code(dup) == (409, "STORE_QUANTITY_EXCEEDED")
    reused = await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0001"}, request_id=issue_id)
    assert am.code(reused) == (409, "REQUEST_ID_REUSED")
    requests = await am.http("GET", f"{API}/material-requests/by-work-order/{rid}", store, MGR, request_id=None)
    assert requests.status_code == 200 and len(requests.json()) == 1  # the replayed request created nothing new


async def test_quantity_guards_and_decision_rules() -> None:
    store = am.repo()
    rid = await open_repair(store)
    line = (await request_parts(store, rid)).json()["events"][0]["requisition_line_id"]
    assert am.code(await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0001"})) == \
        (409, "STORE_LINE_NOT_APPROVED")
    assert am.code(await step(store, rid, line, "approvals", {"quantity": 3})) == (409, "STORE_QUANTITY_EXCEEDED")
    assert am.code(await step(store, rid, line, "approvals", {"quantity": 0})) == (422, "VALIDATION_ERROR")
    assert am.code(await step(store, rid, line, "approvals", {"quantity": "1.0001"})) == (422, "VALIDATION_ERROR")
    assert (await step(store, rid, line, "approvals", {"quantity": 1})).status_code == 200
    assert am.code(await step(store, rid, line, "approvals", {"quantity": 1})) == (409, "STORE_LINE_ALREADY_DECIDED")
    assert am.code(await step(store, rid, line, "denials", {"reason": ""})) == (409, "STORE_LINE_ALREADY_DECIDED")
    assert am.code(await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-9999"})) == \
        (422, "PART_NOT_FOUND")
    assert am.code(await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0001", "unit": "กล่อง"})) \
        == (422, "STORE_UNIT_MISMATCH")
    assert (await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0001"})).status_code == 200
    assert am.code(await step(store, rid, line, "use-confirmations",
                              {"quantity": 2, "part_id": "PART-0001", "position_code": "P"}, user=TECH1)) == \
        (409, "STORE_QUANTITY_EXCEEDED")
    assert am.code(await step(store, rid, line, "use-confirmations",
                              {"quantity": 1, "part_id": "PART-0002", "position_code": "P"}, user=TECH1)) == \
        (422, "STORE_PART_NOT_ISSUED")
    assert am.code(await step(store, rid, line, "return-acceptances", {"quantity": 1, "part_id": "PART-0001"})) == \
        (409, "STORE_QUANTITY_EXCEEDED")
    assert am.code(await step(store, rid, "LINE-NOPE", "approvals", {"quantity": 1})) == (404, "STORE_LINE_NOT_FOUND")
    assert am.code(await step(store, rid, line, "approvals", {"quantity": 1, "extra": 1})) == (422, "VALIDATION_ERROR")


async def test_permissions_are_checked_per_step() -> None:
    store = am.repo()
    rid = await open_repair(store)
    await am.grant(store, MGR, am.employee(DRV1), {"can_view": True})
    assert am.code(await request_parts(store, rid, user=DRV1)) == (403, "STORE_REQUEST_NOT_AUTHORIZED")
    line = (await request_parts(store, rid)).json()["events"][0]["requisition_line_id"]
    assert am.code(await step(store, rid, line, "approvals", {"quantity": 1}, user=TECH1)) == \
        (403, "PREUAT_ACTION_NOT_AUTHORIZED")
    await step(store, rid, line, "approvals", {"quantity": 2})
    assert am.code(await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0001"}, user=TECH1)) == \
        (403, "PREUAT_ACTION_NOT_AUTHORIZED")
    await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"})
    # The store manager is not a V2 member of the repair: use / return declarations are refused.
    assert am.code(await step(store, rid, line, "use-confirmations",
                              {"quantity": 1, "part_id": "PART-0001", "position_code": "P"})) == \
        (403, "STORE_TECHNICIAN_NOT_ASSIGNED")
    assert am.code(await step(store, rid, line, "return-declarations", {"quantity": 1, "part_id": "PART-0001"}, user=DRV1)) == \
        (403, "STORE_TECHNICIAN_NOT_ASSIGNED")
    await step(store, rid, line, "return-declarations", {"quantity": 2, "part_id": "PART-0001"}, user=TECH1)
    assert am.code(await step(store, rid, line, "return-acceptances", {"quantity": 2, "part_id": "PART-0001"}, user=TECH1)) == \
        (403, "PREUAT_ACTION_NOT_AUTHORIZED")
    # No grant for an unverified actor; reads need a trusted can_view reader.
    assert (await am.http("POST", f"{API}/repairs/{rid}/store-requests", store, None, json={})).status_code == 403
    assert (await am.http("GET", f"{API}/repairs/{rid}/store-reconciliation", store, CLERK,
                          request_id=None)).status_code == 403


async def test_new_requests_stop_after_technical_close_but_return_and_reconcile_continue() -> None:
    store = am.repo()
    rid = await open_repair(store)
    line = (await request_parts(store, rid)).json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 2})
    await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"})
    closed = await am.http("POST", f"{API}/repairs/{rid}/close", store, MGR, json={})
    assert closed.status_code == 200, closed.text
    assert am.code(await request_parts(store, rid)) == (409, "STORE_REQUEST_AFTER_CLOSE_NOT_ALLOWED")
    assert (await step(store, rid, line, "use-confirmations",
                       {"quantity": 2, "part_id": "PART-0001", "position_code": "P"}, user=TECH1)).status_code == 200


async def test_event_contract_fields_and_read_only_feed() -> None:
    store = am.repo()
    rid = await open_repair(store)
    created = await request_parts(store, rid)
    line = created.json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 2})
    await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"})
    raw = await store.read_preuat_journal("STORE_EVENTS")
    assert raw and all(set(EVENT_COLUMNS) <= set(row) for row in raw)
    assert len({row["event_id"] for row in raw}) == len(raw)
    issued = [r for r in raw if r["event_type"] == "ISSUED"][0]
    assert (issued["part_id"], issued["quantity"], issued["unit"], issued["source_work_order_id"]) == \
        ("PART-0001", "2", "ชิ้น", rid)
    assert issued["event_version"] == "1" and issued["fingerprint"] and issued["request_id"]
    feed = await am.http("GET", f"{API}/store-material-events", store, MGR, request_id=None, params={"limit": 2})
    assert feed.status_code == 200 and feed.json()["contract"] == "R8-STORE-MATERIAL-EVENT-v1"
    assert len(feed.json()["events"]) == 2 and feed.json()["next_after_event_id"]
    assert "fingerprint" not in feed.json()["events"][0]
    rest = await am.http("GET", f"{API}/store-material-events", store, MGR, request_id=None,
                         params={"after_event_id": feed.json()["next_after_event_id"]})
    assert [e["event_type"] for e in rest.json()["events"]] == ["APPROVED", "ISSUED"]


async def test_real_context_is_refused_and_sheets_inherits_501() -> None:
    store = am.repo()
    service = StoreWorkflowService(store, AssignmentCutover(data_context="REAL"), mock_repository=True)
    with pytest.raises(ApiError) as real:
        await service.reconciliation("REP-0001")
    assert (real.value.status_code, real.value.code) == (409, "STORE_REAL_NOT_ENABLED")
    sheets = StoreWorkflowService(store, AssignmentCutover(data_context="TEST", test_batch_id="B"),
                                  mock_repository=False)
    with pytest.raises(ApiError) as not_mock:
        await sheets.reconciliation("REP-0001")
    assert (not_mock.value.status_code, not_mock.value.code) == (501, "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE")
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    for name in ("read_preuat_journal", "append_preuat_journal", "list_preuat_master_records",
                 "create_preuat_master_record", "update_preuat_master_record"):
        assert getattr(GoogleSheetsRepository, name) is getattr(Repository, name)  # inherits the 501 default
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await Repository.read_preuat_journal(store, "STORE_EVENTS")


async def test_legacy_mode_refuses_every_store_write(monkeypatch) -> None:
    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "false")
    from app.repositories.mock.repository import MockRepository

    store = MockRepository()
    response = await am.http("POST", f"{API}/repairs/REP-0001/store-lines/L1/approvals", store, "USR-ADMIN",
                             role="ADMIN", json={"quantity": 1})
    assert response.status_code == 403


# Independent review findings 1 and 2 -------------------------------------------------------------


async def test_use_and_return_acceptance_are_cross_guarded_so_reconciliation_never_goes_negative() -> None:
    store = am.repo()
    rid = await open_repair(store)
    line = (await request_parts(store, rid, lines=[{"part_id": "PART-0001", "part_description": "x", "quantity": 2,
                                                    "unit": "ชิ้น"}])).json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 2})
    await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"})
    assert (await step(store, rid, line, "return-declarations", {"quantity": 2, "part_id": "PART-0001"}, user=TECH1)).status_code == 200
    # Scenario A: everything is declared for return, so nothing is left to confirm as used.
    use = await step(store, rid, line, "use-confirmations", {"quantity": 2, "part_id": "PART-0001",
                                                             "position_code": "P1"}, user=TECH1)
    assert am.code(use) == (409, "STORE_QUANTITY_EXCEEDED")
    assert (await step(store, rid, line, "return-acceptances", {"quantity": 2, "part_id": "PART-0001"})).status_code == 200
    final = await recon(store, rid)
    assert final["state"] == "RECONCILED" and final["lines"][0]["unreconciled"] == "0"
    # Scenario B: after a full accepted return, a late use confirmation is refused (never -1).
    late = await step(store, rid, line, "use-confirmations", {"quantity": 1, "part_id": "PART-0001",
                                                              "position_code": "P1"}, user=TECH1)
    assert am.code(late) == (409, "STORE_QUANTITY_EXCEEDED")
    assert (await recon(store, rid))["state"] == "RECONCILED"


async def test_a_concurrent_append_elsewhere_never_orphans_a_new_material_request(monkeypatch) -> None:
    store = am.repo()
    rid = await open_repair(store)
    original = store.append_preuat_journal
    calls = {"n": 0}

    async def flaky(journal, *, expected_count, rows):
        if journal != "STORE_EVENTS":  # the internal intent rows are not under test here
            return await original(journal, expected_count=expected_count, rows=rows)
        calls["n"] += 1
        if calls["n"] == 1:  # another repair's event lands between the read and this append
            await original(journal, expected_count=expected_count, rows=[{"event_id": "OTHER", "request_id": "x"}])
        return await original(journal, expected_count=expected_count, rows=rows)

    monkeypatch.setattr(store, "append_preuat_journal", flaky)
    rq = str(uuid.uuid4())
    first = await request_parts(store, rid, request_id=rq)
    assert first.status_code == 200, first.text
    again = await request_parts(store, rid, request_id=rq)
    assert again.json()["replayed"] is True
    requests = await am.http("GET", f"{API}/material-requests/by-work-order/{rid}", store, MGR, request_id=None)
    assert len(requests.json()) == 1  # exactly one material request, no orphan
    assert calls["n"] == 2  # the stale append was retried against a fresh count


# Second independent review (2026-11-18): every return carries its verified physical identity ----------


def _add_instance(store, instance_id: str, part_id: str = "PART-0005") -> None:
    """Test setup only: one synthetic tracked instance in the Mock part state."""
    from dataclasses import replace
    from datetime import UTC, datetime
    from types import MappingProxyType

    from app.domain.part_instance import PartInstance, PartInstanceStatus, PriorUsage

    now = datetime(2026, 11, 18, tzinfo=UTC)
    instance = PartInstance(part_instance_id=instance_id, part_id=part_id, serial_number=f"SN-{instance_id}",
                            status=PartInstanceStatus.READY_FOR_INSTALL, prior_usage=PriorUsage(quality="UNKNOWN"),
                            current_lifecycle_id=f"PLC-{instance_id}", note="synthetic", created_at=now, updated_at=now,
                            state_version=1)
    state = store._part_state
    store._part_state = replace(state, instances=MappingProxyType({**state.instances, instance_id: instance}))


def apply_stock_effects(events, applied: set[str], stock: dict[tuple[str, str], int]) -> None:
    """Deterministic example of the FUTURE stock consumer (contract §4): ISSUED deducts, RETURN_ACCEPTED adds
    back, everything else is evidence only; each immutable event_id is applied exactly once."""
    for e in events:
        if e["event_id"] in applied:
            continue
        applied.add(e["event_id"])
        if e["event_type"] not in ("ISSUED", "RETURN_ACCEPTED"):
            continue  # workflow / installation evidence only
        key = (e["part_id"], e["part_instance_id"])
        assert e["part_id"], "a stock-affecting event must carry the actual part"
        if e["event_type"] == "ISSUED":
            stock[key] = stock.get(key, 0) - int(float(e["quantity"]))
        elif e["event_type"] == "RETURN_ACCEPTED":
            stock[key] = stock.get(key, 0) + int(float(e["quantity"]))


async def test_two_part_ids_on_one_line_are_reconciled_per_identity_and_returns_name_the_part() -> None:
    store = am.repo()
    rid = await open_repair(store)
    line = (await request_parts(store, rid, lines=[{"part_description": "ไส้กรอง (เทียบเท่าได้)", "quantity": 3,
                                                    "unit": "ชิ้น"}])).json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 3})
    await step(store, rid, line, "issues", {"quantity": 2, "part_id": "PART-0001"})
    await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0002"})
    # A return must name its part; one that was not issued, or more than is out of that part, is refused.
    assert am.code(await step(store, rid, line, "return-declarations", {"quantity": 1}, user=TECH1)) == \
        (422, "STORE_PART_IDENTITY_REQUIRED")
    assert am.code(await step(store, rid, line, "return-declarations", {"quantity": 1, "part_id": "PART-0003"},
                              user=TECH1)) == (422, "STORE_PART_NOT_ISSUED")
    assert am.code(await step(store, rid, line, "return-declarations", {"quantity": 2, "part_id": "PART-0002"},
                              user=TECH1)) == (409, "STORE_QUANTITY_EXCEEDED")
    await step(store, rid, line, "use-confirmations", {"quantity": 2, "part_id": "PART-0001", "position_code": "P1"},
               user=TECH1)
    declared = await step(store, rid, line, "return-declarations", {"quantity": 1, "part_id": "PART-0002"}, user=TECH1)
    assert declared.status_code == 200 and declared.json()["events"][0]["part_id"] == "PART-0002"
    # Accepting the wrong part (all of PART-0001 was used) is refused; the declared part is accepted.
    assert am.code(await step(store, rid, line, "return-acceptances", {"quantity": 1, "part_id": "PART-0001"})) == \
        (409, "STORE_QUANTITY_EXCEEDED")
    rq = str(uuid.uuid4())
    accepted = await step(store, rid, line, "return-acceptances", {"quantity": 1, "part_id": "PART-0002"},
                          request_id=rq)
    event = accepted.json()["events"][0]
    assert (event["event_type"], event["part_id"], event["part_code_snapshot"] != "") == \
        ("RETURN_ACCEPTED", "PART-0002", True)
    replay = await step(store, rid, line, "return-acceptances", {"quantity": 1, "part_id": "PART-0002"},
                        request_id=rq)
    assert replay.json()["replayed"] is True and replay.json()["events"][0]["event_id"] == event["event_id"]
    final = await recon(store, rid)
    assert final["state"] == "RECONCILED"
    parts = {p["part_id"]: p for p in final["lines"][0]["issued_parts"]}
    assert (parts["PART-0001"]["used"], parts["PART-0002"]["return_accepted"]) == ("2", "1")
    assert all(p["unreconciled"] == "0" for p in parts.values())
    # The future consumer, fed the feed twice, applies each event once: net -2 PART-0001, 0 PART-0002.
    feed = (await am.http("GET", f"{API}/store-material-events?limit=500", store, MGR, request_id=None)).json()
    mine = [e for e in feed["events"] if e["requisition_line_id"] == line]
    applied: set[str] = set()
    stock: dict[tuple[str, str], int] = {}
    apply_stock_effects(mine, applied, stock)
    apply_stock_effects(mine, applied, stock)  # replayed delivery: no duplicate stock effect
    assert stock == {("PART-0001", ""): -2, ("PART-0002", ""): 0}


async def test_a_tracked_instance_is_issued_once_and_its_return_names_the_instance() -> None:
    store = am.repo()
    _add_instance(store, "PINST-TEST-S1")
    _add_instance(store, "PINST-TEST-S2")
    _add_instance(store, "PINST-TEST-OTHER", part_id="PART-0001")
    rid = await open_repair(store)
    line = (await request_parts(store, rid, lines=[{"part_id": "PART-0005", "part_description": "ปั๊ม", "quantity": 2,
                                                    "unit": "ชิ้น"}])).json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 2})
    issue = {"quantity": 1, "part_id": "PART-0005", "part_instance_id": "PINST-TEST-S1"}
    assert am.code(await step(store, rid, line, "issues", {**issue, "quantity": 2})) == \
        (422, "STORE_INSTANCE_QUANTITY_INVALID")
    assert am.code(await step(store, rid, line, "issues", {**issue, "part_instance_id": "PINST-NOPE"})) == \
        (422, "PART_INSTANCE_NOT_FOUND")
    assert am.code(await step(store, rid, line, "issues", {**issue, "part_instance_id": "PINST-TEST-OTHER"})) == \
        (422, "STORE_PART_INSTANCE_MISMATCH")
    assert (await step(store, rid, line, "issues", issue)).status_code == 200
    assert am.code(await step(store, rid, line, "issues", issue)) == (409, "STORE_PART_INSTANCE_ALREADY_ISSUED")
    assert (await step(store, rid, line, "issues", {**issue, "part_instance_id": "PINST-TEST-S2"})).status_code == 200
    # Issued as instances: a return without the instance is ambiguous and refused (never guessed).
    ambiguous = await step(store, rid, line, "return-declarations", {"quantity": 1, "part_id": "PART-0005"},
                           user=TECH1)
    assert am.code(ambiguous) == (422, "STORE_PART_INSTANCE_REQUIRED")
    assert ambiguous.json()["error"]["details"]["issued_instances"] == ["PINST-TEST-S1", "PINST-TEST-S2"]
    await step(store, rid, line, "use-confirmations", {"quantity": 1, "part_id": "PART-0005",
                                                       "part_instance_id": "PINST-TEST-S1", "position_code": "P1"},
               user=TECH1)
    assert am.code(await step(store, rid, line, "return-declarations", {"quantity": 1, "part_id": "PART-0005",
                                                                        "part_instance_id": "PINST-TEST-S1"},
                              user=TECH1)) == (409, "STORE_QUANTITY_EXCEEDED")  # it was installed
    back = {"quantity": 1, "part_id": "PART-0005", "part_instance_id": "PINST-TEST-S2"}
    await step(store, rid, line, "return-declarations", back, user=TECH1)
    accepted = (await step(store, rid, line, "return-acceptances", back)).json()["events"][0]
    assert (accepted["part_id"], accepted["part_instance_id"]) == ("PART-0005", "PINST-TEST-S2")
    assert (await recon(store, rid))["state"] == "RECONCILED"
    # Once accepted back, the instance can be issued again elsewhere.
    rid2 = await open_repair(store, vehicle="VEH-1046")
    line2 = (await request_parts(store, rid2, lines=[{"part_id": "PART-0005", "part_description": "ปั๊ม",
                                                      "quantity": 1, "unit": "ชิ้น"}])).json()["events"][0][
        "requisition_line_id"]
    await step(store, rid2, line2, "approvals", {"quantity": 1})
    assert (await step(store, rid2, line2, "issues", back)).status_code == 200
    assert am.code(await step(store, rid2, line2, "issues", {**issue})) == (409, "STORE_QUANTITY_EXCEEDED")


def test_a_movement_without_identity_is_never_attributed_to_a_guessed_part() -> None:
    from app.domain.store_workflow import LineBalance, derive_balances

    line = LineBalance("L1", "MR1", "", "x", "ชิ้น")
    derive_balances({"L1": line}, [
        {"requisition_line_id": "L1", "event_type": "APPROVED", "quantity": "1"},
        {"requisition_line_id": "L1", "event_type": "ISSUED", "quantity": "1", "part_id": "PART-0001"},
        {"requisition_line_id": "L1", "event_type": "RETURN_ACCEPTED", "quantity": "1", "part_id": ""}])
    assert "PART_IDENTITY_UNRECONCILED" in line.blockers()
    assert line.parts[("PART-0001", "")].return_accepted == 0


async def test_an_unrecorded_request_is_frozen_reported_truthfully_and_recovered_by_the_same_request(
        monkeypatch) -> None:
    from app.repositories.base import RepositoryConcurrentChangeError

    store = am.repo()
    rid = await open_repair(store)
    original = store.append_preuat_journal
    blocked = {"on": True}

    async def always_conflicting(journal, *, expected_count, rows):
        if blocked["on"] and journal == "STORE_EVENTS":
            raise RepositoryConcurrentChangeError("injected")
        return await original(journal, expected_count=expected_count, rows=rows)

    monkeypatch.setattr(store, "append_preuat_journal", always_conflicting)
    rq = str(uuid.uuid4())
    lines = [{"part_id": "PART-0001", "part_description": "ไส้กรองทดสอบ", "quantity": 1, "unit": "ชิ้น"}]
    pending = await request_parts(store, rid, request_id=rq, lines=lines)
    assert am.code(pending) == (409, "STORE_REQUEST_RECOVERY_PENDING")
    mr_id = pending.json()["error"]["details"]["material_request_id"]
    state = await recon(store, rid)
    assert "REQUEST_NOT_JOURNALED" in state["blockers"]
    line = state["lines"][0]["requisition_line_id"]
    assert am.code(await step(store, rid, line, "approvals", {"quantity": 1})) == (409, "STORE_REQUEST_NOT_JOURNALED")
    blocked["on"] = False
    recovered = await request_parts(store, rid, request_id=rq, lines=lines)
    assert recovered.status_code == 200 and recovered.json()["material_request_id"] == mr_id
    listed = await am.http("GET", f"{API}/material-requests/by-work-order/{rid}", store, MGR, request_id=None)
    assert len(listed.json()) == 1  # adopted, never a second material request
    assert "REQUEST_NOT_JOURNALED" not in (await recon(store, rid))["blockers"]
    assert (await step(store, rid, line, "approvals", {"quantity": 1})).status_code == 200
    replay = await request_parts(store, rid, request_id=rq, lines=lines)
    assert replay.json()["replayed"] is True


async def test_concurrent_submissions_of_one_request_create_one_material_request(monkeypatch) -> None:
    import asyncio

    store = am.repo()
    rid = await open_repair(store)
    original = store.read_preuat_journal

    async def slow(journal):  # force the submissions to interleave between the replay / intent reads and create
        rows = await original(journal)
        await asyncio.sleep(0.02)
        return rows

    monkeypatch.setattr(store, "read_preuat_journal", slow)
    rq = str(uuid.uuid4())
    results = await asyncio.gather(*(request_parts(store, rid, request_id=rq) for _ in range(3)))
    assert all(r.status_code == 200 for r in results)
    assert sorted(r.json()["replayed"] for r in results) == [False, True, True]
    listed = await am.http("GET", f"{API}/material-requests/by-work-order/{rid}", store, MGR, request_id=None)
    assert len(listed.json()) == 1


# Third independent review (2026-11-18): recovery keyed on the request id; whole-unit instances ---------


async def test_recovery_still_works_after_close_and_never_adopts_another_requests_material(monkeypatch) -> None:
    from app.repositories.base import RepositoryConcurrentChangeError

    store = am.repo()
    rid = await open_repair(store)
    original = store.append_preuat_journal
    blocked = {"on": True}

    async def events_blocked(journal, *, expected_count, rows):
        if blocked["on"] and journal == "STORE_EVENTS":
            raise RepositoryConcurrentChangeError("injected")
        return await original(journal, expected_count=expected_count, rows=rows)

    monkeypatch.setattr(store, "append_preuat_journal", events_blocked)
    lines = [{"part_id": "PART-0001", "part_description": "ไส้กรองทดสอบ", "quantity": 1, "unit": "ชิ้น"}]
    rq_a = str(uuid.uuid4())
    pending = await request_parts(store, rid, request_id=rq_a, lines=lines)
    mr_a = pending.json()["error"]["details"]["material_request_id"]
    blocked["on"] = False
    # A different request id with identical lines creates its OWN material request (never adopts A's).
    rq_b = str(uuid.uuid4())
    other = await request_parts(store, rid, request_id=rq_b, lines=lines)
    assert other.status_code == 200 and other.json()["material_request_id"] != mr_a
    # The repair is closed while A is still unrecorded; resending A recovers it all the same.
    for line in [l["requisition_line_id"] for l in (await recon(store, rid))["lines"]
                 if "REQUEST_NOT_JOURNALED" not in l["blockers"]]:
        await step(store, rid, line, "denials", {"reason": "ไม่ใช้"})
    assert (await am.http("POST", f"{API}/repairs/{rid}/close", store, MGR, json={})).status_code == 200
    recovered = await request_parts(store, rid, request_id=rq_a, lines=lines)
    assert recovered.status_code == 200 and recovered.json()["material_request_id"] == mr_a
    assert "REQUEST_NOT_JOURNALED" not in (await recon(store, rid))["blockers"]
    listed = await am.http("GET", f"{API}/material-requests/by-work-order/{rid}", store, MGR, request_id=None)
    assert len(listed.json()) == 2  # A (recovered) and B — no third
    # A brand-new request after close is still refused (DEC-STORE-004).
    late = await request_parts(store, rid, lines=lines)
    assert am.code(late) == (409, "STORE_REQUEST_AFTER_CLOSE_NOT_ALLOWED")
    reused = await request_parts(store, rid, request_id=rq_a, lines=[{**lines[0], "quantity": 2}])
    assert am.code(reused) == (409, "REQUEST_ID_REUSED")


async def test_a_tracked_instance_moves_as_one_whole_unit_and_only_when_available() -> None:
    from dataclasses import replace
    from types import MappingProxyType

    from app.domain.part_instance import PartInstanceStatus

    store = am.repo()
    _add_instance(store, "PINST-TEST-W1")
    _add_instance(store, "PINST-TEST-INST")
    state = store._part_state
    installed = state.instances["PINST-TEST-INST"].model_copy(update={"status": PartInstanceStatus.INSTALLED})
    store._part_state = replace(state, instances=MappingProxyType({**state.instances, "PINST-TEST-INST": installed}))
    rid = await open_repair(store)
    line = (await request_parts(store, rid, lines=[{"part_id": "PART-0005", "part_description": "ปั๊ม", "quantity": 2,
                                                    "unit": "ชิ้น"}])).json()["events"][0]["requisition_line_id"]
    await step(store, rid, line, "approvals", {"quantity": 2})
    busy = await step(store, rid, line, "issues", {"quantity": 1, "part_id": "PART-0005",
                                                   "part_instance_id": "PINST-TEST-INST"})
    assert am.code(busy) == (409, "STORE_PART_INSTANCE_NOT_AVAILABLE")
    ok = {"part_id": "PART-0005", "part_instance_id": "PINST-TEST-W1"}
    assert (await step(store, rid, line, "issues", {"quantity": 1, **ok})).status_code == 200
    for path, extra in (("use-confirmations", {"position_code": "P1"}), ("return-declarations", {})):
        half = await step(store, rid, line, path, {"quantity": "0.5", **ok, **extra}, user=TECH1)
        assert am.code(half) == (422, "STORE_INSTANCE_QUANTITY_INVALID"), path
    assert (await step(store, rid, line, "return-declarations", {"quantity": 1, **ok}, user=TECH1)).status_code == 200
    assert am.code(await step(store, rid, line, "return-acceptances", {"quantity": "0.5", **ok})) == \
        (422, "STORE_INSTANCE_QUANTITY_INVALID")
    assert (await step(store, rid, line, "return-acceptances", {"quantity": 1, **ok})).status_code == 200



async def test_recovery_falls_back_to_the_exact_lines_when_the_created_marker_was_not_recorded(monkeypatch) -> None:
    from app.repositories.base import RepositoryConcurrentChangeError

    store = am.repo()
    rid = await open_repair(store)
    original = store.append_preuat_journal
    blocked = {"on": True}

    async def failing(journal, *, expected_count, rows):
        created_marker = journal == "STORE_REQUEST_INTENTS" and rows and rows[0].get("kind") == "CREATED"
        if blocked["on"] and (journal == "STORE_EVENTS" or created_marker):
            raise RepositoryConcurrentChangeError("injected")
        return await original(journal, expected_count=expected_count, rows=rows)

    monkeypatch.setattr(store, "append_preuat_journal", failing)
    rq = str(uuid.uuid4())
    lines = [{"part_id": "PART-0001", "part_description": "ไส้กรองทดสอบ", "quantity": 1, "unit": "ชิ้น"}]
    pending = await request_parts(store, rid, request_id=rq, lines=lines)
    mr = pending.json()["error"]["details"]["material_request_id"]
    assert not any(r.get("kind") == "CREATED" for r in store._preuat_journals["STORE_REQUEST_INTENTS"])
    blocked["on"] = False
    recovered = await request_parts(store, rid, request_id=rq, lines=lines)
    assert recovered.status_code == 200 and recovered.json()["material_request_id"] == mr
    listed = await am.http("GET", f"{API}/material-requests/by-work-order/{rid}", store, MGR, request_id=None)
    assert len(listed.json()) == 1
