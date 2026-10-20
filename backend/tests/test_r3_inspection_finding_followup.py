"""R3 — daily inspection and Finding follow-up (Mock/TEST).

Source of truth: docs/project-governance/r3-implementation-contract.md. Every
row is SYNTHETIC mock data; the clock is fixed by patching the service's
Asia/Bangkok date. Mock results are not production evidence (L3, R11).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

import app.domain.inspection_service as inspection_service
from app.domain.asset import AssetType
from app.domain.checklist import ChecklistAssignment, ChecklistItem, ChecklistRevision, InspectionResultValue
from app.domain.inspection import NewInspectionItemInput
from app.domain.repair import RepairSourceType
from app.domain.technician_assignment import REPAIR, TechnicianAssignmentService
from app.repositories.base import RepositoryFeatureNotImplementedError
from tests.test_technician_assignment_batch_r2f_h1 import (
    T1, T2, T3, U1, U2, U3, body, cut, http, new_repair, repo_with, v2_rows,
)

API = "/api/v1"
VEH = "VEH-1046"
DAY1 = date(2026, 10, 1)
MANAGER = dict(role="MAINTENANCE_MANAGER", user="USR-MGR")
INSPECTOR = dict(role="TECHNICIAN", user=U1)


@pytest.fixture
def clock(monkeypatch):
    state = {"today": DAY1}
    monkeypatch.setattr(inspection_service, "bangkok_today", lambda: state["today"])

    def set_day(day: date) -> None:
        state["today"] = day

    return set_day


async def form(repo, asset_id: str = VEH, asset_type: str = "VEHICLE", **who):
    return await http("GET", f"{API}/inspections/form?asset_type={asset_type}&asset_id={asset_id}", repo,
                      **(who or INSPECTOR))


async def submit(repo, results: dict[str, tuple[str, str | None]] | None = None, *, asset_id: str = VEH,
                 asset_type: str = "VEHICLE", request_id: str | None = None, default: str = "PASS", **who):
    """Answer every shown item (`default`), overriding item_id -> (result, remark)."""
    shown = (await form(repo, asset_id, asset_type)).json()["items"]
    items = []
    for entry in shown:
        item_id = entry["item"]["item_id"]
        result, remark = (results or {}).get(item_id, (default, None))
        items.append({"item_id": item_id, "result": result, "remark": remark})
    return await http("POST", f"{API}/inspections", repo, json={"asset_type": asset_type, "asset_id": asset_id,
                      "items": items}, request_id=request_id or str(uuid.uuid4()), **(who or INSPECTOR))


def fail(item: str = "ITM-V-0001", remark: str = "น้ำมันรั่ว") -> dict[str, tuple[str, str | None]]:
    return {item: ("FAIL", remark)}


def shown_ids(response) -> list[str]:
    return [i["item"]["item_id"] for i in response.json()["items"]]


def code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


async def finding(repo, finding_id: str):
    return (await http("GET", f"{API}/findings/{finding_id}", repo, **MANAGER)).json()


async def open_round(repo, finding_id: str, **who):
    return await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                      "source_type": "FINDING", "source_id": finding_id}, **(who or MANAGER))


async def assigned_round(repo, finding_id: str) -> tuple[str, str]:
    response = await open_round(repo, finding_id)
    assert response.status_code == 200, response.text
    repair_id = response.json()["repair"]["repair_id"]
    # L8: V2 assignment on an R3 round needs the Finding authority, so it goes through the
    # real route as the Maintenance Department Manager.
    assigned = await http("POST", f"{API}/repairs/{repair_id}/technician-assignments", repo, json=body(T1, T2),
                          **MANAGER)
    assert assigned.status_code == 200, assigned.text
    return repair_id, assigned.json()["current"]["assignment_set_id"]


async def complete(repo, repair_id: str, set_id: str | None, *, request_id: str | None = None, **who):
    return await http("POST", f"{API}/repairs/{repair_id}/completion", repo, json={"expected_set_id": set_id},
                      request_id=request_id or str(uuid.uuid4()), **(who or INSPECTOR))


# ---------------------------------------------------------------------------
# Checklist resolution, due logic (R3-02, R3-03, R3-22, R3-23, O-4)
# ---------------------------------------------------------------------------


async def test_r3_due_first_inspection_then_day2_day8_and_idle_without_backfill(clock) -> None:
    repo = repo_with()
    first = await form(repo)
    assert first.status_code == 200
    assert shown_ids(first) == ["ITM-V-0001", "ITM-V-0002", "ITM-V-0003", "ITM-V-0004", "ITM-V-0005"]
    assert {i["due_reason"] for i in first.json()["items"][3:]} == {"FIRST_WEEKLY"}
    assert (await submit(repo)).status_code == 200
    clock(DAY1 + timedelta(days=1))
    assert shown_ids(await form(repo)) == ["ITM-V-0001", "ITM-V-0002", "ITM-V-0003"]
    clock(DAY1 + timedelta(days=6))
    assert len(shown_ids(await form(repo))) == 3
    clock(DAY1 + timedelta(days=7))
    day8 = await form(repo)
    assert len(shown_ids(day8)) == 5 and day8.json()["items"][4]["due_reason"] == "WEEKLY_DUE"
    clock(DAY1 + timedelta(days=40))  # idle: today's due set only, no missed-day queue
    assert len(shown_ids(await form(repo))) == 5


async def test_r3_not_installed_counts_as_the_last_weekly_result(clock) -> None:
    repo = repo_with()
    assert (await submit(repo, {"ITM-V-0004": ("NOT_INSTALLED", None)})).status_code == 200
    clock(DAY1 + timedelta(days=3))
    assert "ITM-V-0004" not in shown_ids(await form(repo))


async def test_r3_missing_checklist_and_asset_override_and_ambiguity(clock) -> None:
    repo = repo_with()
    assert code(await form(repo, "EQP-0003", "EQUIPMENT")) == (404, "MISSING_CHECKLIST")
    equipment = await form(repo, "EQP-0001", "EQUIPMENT")
    assert equipment.status_code == 200 and equipment.json()["checklist"]["checklist_id"] == "CHK-0002"
    repo._checklist_assignments.append(ChecklistAssignment(assignment_id="CHA-T1", asset_type=AssetType.EQUIPMENT,
                                                           scope="ASSET", checklist_id="CHK-0002",
                                                           asset_id="EQP-0003"))
    assert (await form(repo, "EQP-0003", "EQUIPMENT")).status_code == 200  # asset override, no model needed
    repo._checklist_assignments.append(ChecklistAssignment(assignment_id="CHA-T2", asset_type=AssetType.EQUIPMENT,
                                                           scope="ASSET", checklist_id="CHK-0002",
                                                           asset_id="EQP-0003"))
    assert code(await form(repo, "EQP-0003", "EQUIPMENT")) == (409, "CHECKLIST_ASSIGNMENT_AMBIGUOUS")


async def test_r3_new_revision_keeps_item_identity_by_item_key_not_title(clock) -> None:
    repo = repo_with()
    assert (await submit(repo)).status_code == 200
    repo._checklist_revisions["REV-0009"] = ChecklistRevision(revision_id="REV-0009", checklist_id="CHK-0001",
                                                               revision_number=2, effective_date=DAY1,
                                                               created_at=repo._checklist_revisions["REV-0001"]
                                                               .created_at)
    repo._checklist_items["REV-0009"] = [
        item.model_copy(update={"item_id": f"NEW-{n}", "revision_id": "REV-0009", "title": f"ชื่อใหม่ {n}"})
        for n, item in enumerate(repo._checklist_items["REV-0001"], start=1)
    ]
    clock(DAY1 + timedelta(days=1))
    response = await form(repo)
    assert response.json()["revision"]["revision_id"] == "REV-0009"
    assert shown_ids(response) == ["NEW-1", "NEW-2", "NEW-3"]  # weekly keys already answered on day 1


# ---------------------------------------------------------------------------
# Results and submission protection (R3-15, R3-16, R3-19..R3-21, B2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("result", ["FAIL", "USABLE_PENDING_REPAIR"])
async def test_r3_abnormal_results_need_a_remark_photo_optional(clock, result) -> None:
    repo = repo_with()
    assert code(await submit(repo, {"ITM-V-0001": (result, "   ")})) == (422, "INSPECTION_REMARK_REQUIRED")
    ok = await submit(repo, {"ITM-V-0001": (result, "ฝาครอบหลวม")})
    assert ok.status_code == 200 and ok.json()["items"][0]["result"] == result
    assert ok.json()["findings"][0]["status"] == "OPEN"


async def test_r3_legacy_na_unshown_and_missing_items_are_refused(clock) -> None:
    repo = repo_with()
    assert code(await submit(repo, default="NA")) == (422, "INSPECTION_RESULT_NOT_ALLOWED")
    items = [{"item_id": "ITM-V-0001", "result": "PASS"}]
    missing = await http("POST", f"{API}/inspections", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                         "items": items}, **INSPECTOR)
    assert code(missing) == (422, "VALIDATION_ERROR")
    assert (await submit(repo)).status_code == 200
    clock(DAY1 + timedelta(days=1))
    shown = [{"item_id": f"ITM-V-000{n}", "result": "PASS"} for n in range(1, 6)]  # weekly items not due
    unshown = await http("POST", f"{API}/inspections", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                         "items": shown}, **INSPECTOR)
    assert code(unshown) == (422, "VALIDATION_ERROR")
    assert unshown.json()["error"]["details"]["unknown_item_ids"] == ["ITM-V-0004", "ITM-V-0005"]


async def test_r3_one_per_bangkok_day_and_idempotent_replay(clock) -> None:
    repo = repo_with()
    request_id = str(uuid.uuid4())
    items = [{"item_id": f"ITM-V-000{n}", "result": "PASS"} for n in range(2, 6)]
    payload = {"asset_type": "VEHICLE", "asset_id": VEH,
               "items": [{"item_id": "ITM-V-0001", "result": "FAIL", "remark": "น้ำมันรั่ว"}, *items]}
    first = await http("POST", f"{API}/inspections", repo, json=payload, request_id=request_id, **INSPECTOR)
    assert first.status_code == 200 and first.json()["replayed"] is False
    snapshots = len(repo._meter_snapshots) if hasattr(repo, "_meter_snapshots") else None
    # The same intent retried (timeout / double click): same id, same payload, in any item order.
    replay = await http("POST", f"{API}/inspections", repo, json={**payload, "items": payload["items"][::-1]},
                        request_id=request_id, **INSPECTOR)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["header"]["inspection_id"] == first.json()["header"]["inspection_id"]
    assert len([d for d in repo._inspections.values() if d.header.request_id]) == 1
    assert len(repo._r3_findings) == 1
    if snapshots is not None:
        assert len(repo._meter_snapshots) == snapshots
    changed = {**payload, "items": [{"item_id": "ITM-V-0001", "result": "FAIL", "remark": "อย่างอื่น"}, *items]}
    reused = await http("POST", f"{API}/inspections", repo, json=changed, request_id=request_id, **INSPECTOR)
    assert code(reused) == (409, "REQUEST_ID_REUSED")
    other_inspector = await submit(repo, role="SUPERVISOR", user="USR-OTHER")
    assert code(other_inspector) == (409, "INSPECTION_ALREADY_SUBMITTED_TODAY")
    assert other_inspector.json()["error"]["details"]["inspection_id"] == first.json()["header"]["inspection_id"]
    clock(DAY1 + timedelta(days=1))
    assert (await submit(repo)).status_code == 200


async def test_r3_request_id_is_required_and_recording_needs_the_capability(clock) -> None:
    repo = repo_with()
    no_id = await http("POST", f"{API}/inspections", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                       "items": [{"item_id": "ITM-V-0001", "result": "PASS"}]}, request_id=None, **INSPECTOR)
    assert code(no_id) == (422, "REQUEST_ID_REQUIRED")
    forbidden = await submit(repo, **MANAGER)
    assert forbidden.status_code == 403
    assert not [d for d in repo._inspections.values() if d.header.request_id]


async def test_r3_inspection_history_is_immutable_and_has_no_write_route(clock) -> None:
    repo = repo_with()
    inspection_id = (await submit(repo)).json()["header"]["inspection_id"]
    for method in ("PUT", "PATCH", "DELETE"):
        response = await http(method, f"{API}/inspections/{inspection_id}", repo, **MANAGER)
        assert response.status_code == 405, method


# ---------------------------------------------------------------------------
# Finding episodes without a Work Order (R3-12, R3-13, R3-24, O-5.1)
# ---------------------------------------------------------------------------


async def test_r3_days_1_to_3_one_finding_day4_pass_ends_day20_new_finding(clock) -> None:
    repo = repo_with()
    first = await submit(repo, fail())
    finding_id = first.json()["findings"][0]["finding_id"]
    for offset in (1, 2):
        clock(DAY1 + timedelta(days=offset))
        again = await submit(repo, fail())
        assert [f["finding_id"] for f in again.json()["findings"]] == [finding_id]
    current = await finding(repo, finding_id)
    assert len(current["finding"]["observations"]) == 3
    assert current["followup_group"] == "AWAITING_REPAIR_DECISION"
    clock(DAY1 + timedelta(days=3))
    await submit(repo)
    ended = (await finding(repo, finding_id))["finding"]
    assert ended["status"] == "ENDED" and ended["end_reason"] == "NORMAL_REINSPECTION"
    assert ended["end_note"] == "ตรวจครั้งล่าสุดแล้วไม่พบความผิดปกติ"
    assert len(ended["observations"]) == 4
    clock(DAY1 + timedelta(days=19))
    recurrence = await submit(repo, fail())
    new_id = recurrence.json()["findings"][0]["finding_id"]
    assert new_id != finding_id
    assert recurrence.json()["findings"][0]["previous_finding_id"] == finding_id


async def test_r3_not_installed_after_abnormal_keeps_the_finding_open(clock) -> None:
    repo = repo_with()
    finding_id = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    clock(DAY1 + timedelta(days=1))
    await submit(repo, {"ITM-V-0001": ("NOT_INSTALLED", None)})
    assert (await finding(repo, finding_id))["finding"]["status"] == "OPEN"


async def test_r3_manual_termination_needs_authority_and_a_reason(clock) -> None:
    repo = repo_with()
    finding_id = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    path = f"{API}/findings/{finding_id}/termination"
    assert (await http("POST", path, repo, json={"reason": "x"}, role="MAINTENANCE")).status_code == 403
    assert code(await http("POST", path, repo, json={"reason": " "}, **MANAGER)) == (
        422, "FINDING_TERMINATION_REASON_REQUIRED")
    done = await http("POST", path, repo, json={"reason": "รายการถูกยกเลิกในรุ่นใหม่"}, **MANAGER)
    assert done.status_code == 200
    assert done.json()["finding"]["end_reason"] == "MANUAL_TERMINATION"
    assert done.json()["finding"]["ended_by"] == "USR-MGR"
    assert code(await http("POST", path, repo, json={"reason": "x"}, **MANAGER)) == (409, "FINDING_NOT_OPEN")


# ---------------------------------------------------------------------------
# Repair rounds (contract §9–§10; Q2..Q5, T1..T3)
# ---------------------------------------------------------------------------


async def test_r3_lead_completion_ends_f001_and_a_later_fail_opens_f002_while_rpr001_is_open(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr1, set_id = await assigned_round(repo, f1)
    clock(DAY1 + timedelta(days=1))
    assert [f["finding_id"] for f in (await submit(repo, fail())).json()["findings"]] == [f1]
    assert (await finding(repo, f1))["followup_group"] == "IN_REPAIR"
    done = await complete(repo, rpr1, set_id)
    assert done.status_code == 200, done.text
    assert done.json()["repair"]["status"] == "OPEN"
    t_finish = done.json()["repair"]["completion_submitted_at"]
    ended = (await finding(repo, f1))["finding"]
    assert ended["status"] == "ENDED" and ended["end_reason"] == "TECHNICIAN_COMPLETION_SUBMITTED"
    assert ended["end_note"] == "สิ้นสุดรอบติดตาม — ช่างส่งงานซ่อมแล้ว" and ended["ended_repair_id"] == rpr1
    clock(DAY1 + timedelta(days=2))
    f2 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    assert f2 != f1
    rpr2 = await open_round(repo, f2)
    assert rpr2.status_code == 200 and rpr2.json()["repair"]["finding_id"] == f2  # not blocked by OPEN RPR-1
    closed = await http("POST", f"{API}/repairs/{rpr1}/close", repo, json={"close_note": "ปิดรอบที่ 1"}, **MANAGER)
    assert closed.status_code == 200 and closed.json()["repair"]["status"] == "CLOSED"
    assert closed.json()["repair"]["completion_submitted_at"] == t_finish
    assert closed.json()["repair"]["closed_at"] >= t_finish
    assert (await finding(repo, f1))["finding"]["status"] == "ENDED"  # history unchanged


async def test_r3_completion_is_lead_only_idempotent_and_refuses_stale_sets(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr, set_id = await assigned_round(repo, f1)
    assert code(await complete(repo, rpr, set_id, role="TECHNICIAN", user=U2)) == (403, "REPAIR_COMPLETION_LEAD_ONLY")
    assert code(await complete(repo, rpr, set_id, **MANAGER)) == (403, "REPAIR_COMPLETION_LEAD_ONLY")
    assert code(await complete(repo, rpr, "stale-set")) == (409, "REPAIR_ASSIGNMENT_STALE")
    assert (await finding(repo, f1))["finding"]["status"] == "OPEN"
    request_id = str(uuid.uuid4())
    first = await complete(repo, rpr, set_id, request_id=request_id)
    retry = await complete(repo, rpr, set_id, request_id=request_id)
    assert first.status_code == retry.status_code == 200
    assert first.json()["repair"]["completion_submitted_at"] == retry.json()["repair"]["completion_submitted_at"]
    assert code(await complete(repo, rpr, set_id)) == (409, "REPAIR_COMPLETION_ALREADY_SUBMITTED")


async def test_r3_completion_without_a_lead_is_refused(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr = (await open_round(repo, f1)).json()["repair"]["repair_id"]
    assert code(await complete(repo, rpr, None)) == (409, "REPAIR_LEAD_NOT_ASSIGNED")


async def test_r3_round_is_frozen_after_completion_and_closed_orders_refuse_work(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr, set_id = await assigned_round(repo, f1)
    assert (await complete(repo, rpr, set_id)).status_code == 200
    action = await http("POST", f"{API}/repairs/{rpr}/actions", repo, json={"action_text": "งานรอบสอง"}, **MANAGER)
    part = await http("POST", f"{API}/repairs/{rpr}/parts", repo, json={"part_description": "ซีล"}, **MANAGER)
    assert code(action) == code(part) == (409, "REPAIR_ROUND_FROZEN")
    manual = await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                        "source_type": "MANUAL"}, role="MAINTENANCE")
    manual_id = manual.json()["repair"]["repair_id"]
    closed = await http("POST", f"{API}/repairs/{manual_id}/close", repo, json={}, role="MAINTENANCE")
    assert closed.status_code == 200  # non-R3 closure unchanged (no completion needed)
    late = await http("POST", f"{API}/repairs/{manual_id}/actions", repo, json={"action_text": "x"},
                      role="MAINTENANCE")
    assert code(late) == (409, "REPAIR_ROUND_FROZEN")  # T3


async def test_r3_close_needs_finding_authority_and_the_lead_completion(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr, set_id = await assigned_round(repo, f1)
    path = f"{API}/repairs/{rpr}/close"
    assert code(await http("POST", path, repo, json={}, **MANAGER)) == (409, "REPAIR_COMPLETION_NOT_SUBMITTED")
    assert (await complete(repo, rpr, set_id)).status_code == 200
    assert (await http("POST", path, repo, json={}, role="MAINTENANCE")).status_code == 403
    assert (await http("POST", path, repo, json={}, **MANAGER)).status_code == 200


async def test_r3_cancel_before_work_then_pass_ends_the_finding(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr = (await open_round(repo, f1)).json()["repair"]["repair_id"]
    path = f"{API}/repairs/{rpr}/cancellation"
    assert (await http("POST", path, repo, json={"reason": "x"}, role="MAINTENANCE")).status_code == 403
    assert code(await http("POST", path, repo, json={"reason": ""}, **MANAGER)) == (422, "REPAIR_CANCEL_REASON_REQUIRED")
    cancelled = await http("POST", path, repo, json={"reason": "เปิดซ้ำโดยไม่ตั้งใจ"}, **MANAGER)
    assert cancelled.status_code == 200 and cancelled.json()["repair"]["status"] == "CANCELLED"
    assert cancelled.json()["repair"]["cancel_reason"] == "เปิดซ้ำโดยไม่ตั้งใจ"
    assert (await finding(repo, f1))["followup_group"] == "AWAITING_REPAIR_DECISION"
    assert code(await http("POST", f"{API}/repairs/{rpr}/close", repo, json={}, **MANAGER)) == (409, "REPAIR_NOT_OPEN")
    assert code(await http("POST", path, repo, json={"reason": "again"}, **MANAGER)) == (409, "REPAIR_NOT_OPEN")
    clock(DAY1 + timedelta(days=1))
    await submit(repo)
    ended = (await finding(repo, f1))["finding"]
    assert ended["status"] == "ENDED" and ended["end_reason"] == "NORMAL_REINSPECTION"


async def test_r3_pass_while_a_round_is_open_never_cancels_or_ends(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr = (await open_round(repo, f1)).json()["repair"]["repair_id"]
    clock(DAY1 + timedelta(days=1))
    await submit(repo)
    detail = await finding(repo, f1)
    assert detail["finding"]["status"] == "OPEN" and detail["repairs"][0]["status"] == "OPEN"
    assert detail["finding"]["observations"][-1]["result"] == "PASS"
    assert detail["repairs"][0]["repair_id"] == rpr


@pytest.mark.parametrize("work", ["action", "part", "completion", "closed", "not_r3"])
async def test_r3_cancellation_is_refused_once_work_exists(clock, work) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr, set_id = await assigned_round(repo, f1)
    if work == "action":
        await http("POST", f"{API}/repairs/{rpr}/actions", repo, json={"action_text": "ถอดฝาครอบ"}, **MANAGER)
    elif work == "part":
        await http("POST", f"{API}/repairs/{rpr}/parts", repo, json={"part_description": "ซีล"}, **MANAGER)
    elif work in ("completion", "closed"):
        await complete(repo, rpr, set_id)
        if work == "closed":
            await http("POST", f"{API}/repairs/{rpr}/close", repo, json={}, **MANAGER)
    elif work == "not_r3":
        rpr = (await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                          "source_type": "MANUAL"}, **MANAGER)).json()["repair"]["repair_id"]
    expected = {"action": "REPAIR_WORK_ALREADY_STARTED", "part": "REPAIR_WORK_ALREADY_STARTED",
                "completion": "REPAIR_WORK_ALREADY_STARTED", "closed": "REPAIR_NOT_OPEN",
                "not_r3": "REPAIR_CANCEL_NOT_ALLOWED"}[work]
    response = await http("POST", f"{API}/repairs/{rpr}/cancellation", repo, json={"reason": "x"}, **MANAGER)
    assert code(response) == (409, expected)


async def test_r3_one_active_round_per_finding_and_manager_only_opening(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    assert (await open_round(repo, f1, role="MAINTENANCE")).status_code == 403
    assert (await open_round(repo, f1)).status_code == 200
    assert code(await open_round(repo, f1)) == (409, "FINDING_ACTIVE_REPAIR_EXISTS")
    await http("POST", f"{API}/findings/{f1}/termination", repo, json={"reason": "x"}, **MANAGER)
    assert code(await open_round(repo, f1)) == (409, "FINDING_NOT_OPEN")
    manual = await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                        "source_type": "MANUAL"}, role="MAINTENANCE")
    assert manual.status_code == 200 and manual.json()["repair"]["finding_id"] is None  # MANUAL unchanged


async def test_r3_repair_request_conversion_and_inspection_result_bypasses_are_guarded(clock) -> None:
    repo = repo_with()
    first = (await submit(repo, fail())).json()
    f1, result_id = first["findings"][0]["finding_id"], first["findings"][0]["result_id"]
    reported = await http("POST", f"{API}/repair-requests", repo, json={"vehicle_id": VEH, "symptom_th": "น้ำมันรั่ว",
                          "source_type": "FINDING", "source_id": f1}, **INSPECTOR)
    assert reported.status_code == 200, reported.text  # reporting from a Finding stays allowed
    request_id = reported.json()["request"]["repair_request_id"]
    convert = f"{API}/repair-requests/{request_id}/convert"
    assert (await http("POST", convert, repo, json={}, role="MAINTENANCE")).status_code == 403
    converted = await http("POST", convert, repo, json={}, **MANAGER)
    assert converted.status_code == 200 and converted.json()["repair"]["finding_id"] == f1
    assert converted.json()["repair"]["source_type"] == "REPAIR_REQUEST"
    assert code(await open_round(repo, f1)) == (409, "FINDING_ACTIVE_REPAIR_EXISTS")
    via_result = await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                            "source_type": "INSPECTION_RESULT", "source_id": result_id}, **MANAGER)
    assert code(via_result) == (422, "REPAIR_SOURCE_USE_FINDING")
    assert via_result.json()["error"]["details"]["finding_id"] == f1


async def test_r3_followup_lists_open_findings_by_group_only(clock) -> None:
    repo = repo_with()
    response = await submit(repo, {"ITM-V-0001": ("FAIL", "a"), "ITM-V-0002": ("USABLE_PENDING_REPAIR", "b"),
                                   "ITM-V-0003": ("FAIL", "c")})
    f1, f2, f3 = [f["finding_id"] for f in response.json()["findings"]]
    await open_round(repo, f2)
    await http("POST", f"{API}/findings/{f3}/termination", repo, json={"reason": "x"}, **MANAGER)
    listed = (await http("GET", f"{API}/findings/follow-up", repo, **MANAGER)).json()
    assert {d["finding"]["finding_id"]: d["followup_group"] for d in listed} == {
        f1: "AWAITING_REPAIR_DECISION", f2: "IN_REPAIR"}


# ---------------------------------------------------------------------------
# B1 read compatibility, reports and storage mode
# ---------------------------------------------------------------------------


async def test_r3_b1_readers_cancelled_orders_and_ended_findings(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr = (await open_round(repo, f1)).json()["repair"]["repair_id"]
    await http("POST", f"{API}/repairs/{rpr}/cancellation", repo, json={"reason": "x"}, **MANAGER)
    open_report = (await http("GET", f"{API}/repairs/open-queue", repo, **MANAGER))
    assert open_report.status_code == 200
    assert rpr not in {i["repair_id"] for i in open_report.json()["items"]}
    waiting = await http("GET", f"{API}/repairs/v2-waiting-assignment", repo, **MANAGER)
    assert waiting.status_code == 200 and rpr not in waiting.text
    cancelled = await http("GET", f"{API}/repairs?status=CANCELLED", repo, **MANAGER)
    assert [i["repair_id"] for i in cancelled.json()["items"]] == [rpr]
    clock(DAY1 + timedelta(days=1))
    await submit(repo)
    report = await http("GET", f"{API}/reports/inspection-findings", repo, role="ADMIN")
    assert report.status_code == 200, report.text
    rows = {i["finding_id"]: i["recorded_status"] for i in report.json()["items"]}
    assert rows == {f1: "ENDED"} and report.json()["complete"] is True


async def test_r3_b1_legacy_na_inspection_stays_readable(clock) -> None:
    repo = repo_with()
    legacy = await repo.create_inspection(
        asset_type=AssetType.VEHICLE, asset_id=VEH, checklist_id="CHK-0001", revision_id="REV-0001",
        revision_number=1, inspector_user_id="legacy", overall_remark=None,
        items=[NewInspectionItemInput(item_id="ITM-V-0001", sequence=1, title="t", is_critical=False,
                                      result=InspectionResultValue.NA)],
    )
    detail = await http("GET", f"{API}/inspections/{legacy.header.inspection_id}", repo, **MANAGER)
    assert detail.status_code == 200 and detail.json()["items"][0]["result"] == "NA"
    assert detail.json()["header"]["request_id"] is None
    assert (await form(repo)).json()["items"][0]["last_result_date"] is None  # pre-R3 rows never feed R3 due logic


async def test_r3_google_sheets_mode_fails_closed_for_r3_storage() -> None:
    from app.repositories.google_sheets import GoogleSheetsRepository
    from tests.test_google_sheets_real_io import _configured_settings

    sheets = GoogleSheetsRepository(_configured_settings())
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await sheets.find_r3_inspection_by_request_id("x")
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await sheets.create_repair(AssetType.VEHICLE, VEH, RepairSourceType.FINDING, "FND-1", None, None, None,
                                   None, finding_id="FND-1")
    with pytest.raises(RepositoryFeatureNotImplementedError):
        await sheets.submit_repair_completion("RPR-1", submitted_by=None, technician_id="T", set_id="S",
                                              request_id="R", note=None)
    with pytest.raises(RepositoryFeatureNotImplementedError):  # L10: no sheet column, so 501
        await sheets.cancel_repair_request("RRQ-1", cancelled_by=None, reason="x", duplicate_of_repair_id=None,
                                           duplicate_of_repair_request_id=None)


def test_r3_seed_items_are_r3_ready_placeholders() -> None:
    from app.repositories.mock.seed_data import SEED_CHECKLIST_ITEMS

    for items in SEED_CHECKLIST_ITEMS.values():
        assert all(isinstance(i, ChecklistItem) and i.item_key and i.frequency in {"DAILY", "EVERY_7_DAYS"}
                   for i in items)
        assert not any(i.is_critical or i.required_photo_on_fail or i.required_remark_on_fail for i in items)


# ---------------------------------------------------------------------------
# L9 / L10 evidence scenarios (register §6.1). They record the CURRENT limited
# behaviour; no bypass is introduced and nothing here is an Owner decision.
# ---------------------------------------------------------------------------


async def test_r3_l9_a_worked_round_can_never_lose_its_lead_so_completion_stays_possible(clock) -> None:
    """L9 (Owner rule, supersedes the former "stuck round" limitation): the withdrawal that
    used to leave a worked round without a PRIMARY is refused and changes nothing, so the
    current lead can still complete and the manager can still close."""
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr, set_id = await assigned_round(repo, f1)
    action = await http("POST", f"{API}/repairs/{rpr}/actions", repo, json={"action_text": "ถอดฝาครอบ"}, **MANAGER)
    assert action.status_code == 200, action.text
    before = list(v2_rows(repo))
    withdrawn = await http("POST", f"{API}/repairs/{rpr}/technician-assignment-withdrawals", repo,
                           json=CURRENT_T1_T2, request_id=str(uuid.uuid4()), **MANAGER)
    assert code(withdrawn) == (409, "TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED_ON_R3_ROUND")
    assert v2_rows(repo) == before
    assert (await complete(repo, rpr, set_id)).status_code == 200  # the lead is still there
    closed = await http("POST", f"{API}/repairs/{rpr}/close", repo, json={}, **MANAGER)
    assert closed.status_code == 200 and closed.json()["repair"]["status"] == "CLOSED"


async def test_r3_l10_repair_request_whose_finding_ended_cannot_be_converted_and_stays_pending(clock) -> None:
    """L10: guard E-2 refuses the conversion once the Finding has ENDED; the Repair
    Request is left unchanged (PENDING) because the flow has no rejection state."""
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    reported = await http("POST", f"{API}/repair-requests", repo, json={"vehicle_id": VEH, "symptom_th": "น้ำมันรั่ว",
                          "source_type": "FINDING", "source_id": f1}, **INSPECTOR)
    assert reported.status_code == 200, reported.text
    request_id = reported.json()["request"]["repair_request_id"]
    terminated = await http("POST", f"{API}/findings/{f1}/termination", repo, json={"reason": "ยุติ"}, **MANAGER)
    assert terminated.status_code == 200
    refused = await http("POST", f"{API}/repair-requests/{request_id}/convert", repo, json={}, **MANAGER)
    assert code(refused) == (409, "FINDING_NOT_OPEN")
    after = await http("GET", f"{API}/repair-requests/{request_id}", repo, **MANAGER)
    assert after.json()["request_status"] == "PENDING"
    assert after.json() == {**reported.json()["request"], **{k: after.json()[k] for k in ("request_status",)}}


# ---------------------------------------------------------------------------
# L8 (Owner decision, R3 final correction): V2 assign / withdraw on an R3 Finding round
# needs can_manage_repair + can_manage_finding_repair. Non-R3 jobs keep the accepted V2
# authorization exactly.
# ---------------------------------------------------------------------------

ASSIGN = "{api}/repairs/{rid}/technician-assignments"
WITHDRAW = "{api}/repairs/{rid}/technician-assignment-withdrawals"
CURRENT_T1_T2 = {"expected_current": {"primary_technician_id": T1, "collaborator_technician_ids": [T2]}}


async def _r3_round(repo) -> str:
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    response = await open_round(repo, f1)
    assert response.status_code == 200, response.text
    assert response.json()["repair"]["finding_id"] == f1  # server-stored round marker (TS-3)
    return response.json()["repair"]["repair_id"]


@pytest.mark.parametrize(("role", "allowed"), [
    ("MAINTENANCE_MANAGER", True), ("ADMIN", True), ("MAINTENANCE", False), ("SUPERVISOR", False),
    ("TECHNICIAN", False), ("DRIVER", False), ("DRIVER_DEPARTMENT_MANAGER", False),
])
async def test_r3_l8_assign_and_withdraw_on_an_r3_round_need_both_capabilities(clock, role, allowed) -> None:
    repo = repo_with()
    rid = await _r3_round(repo)
    assigned = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1, T2), role=role)
    if not allowed:
        assert assigned.status_code == 403
        assert v2_rows(repo) == []
        # A withdrawal of a set the manager assigned is refused too, with nothing written.
        ok = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1, T2), **MANAGER)
        assert ok.status_code == 200
        before = list(v2_rows(repo))
        withdrawn = await http("POST", WITHDRAW.format(api=API, rid=rid), repo, json=CURRENT_T1_T2, role=role)
        assert withdrawn.status_code == 403
        assert v2_rows(repo) == before
        return
    assert assigned.status_code == 200, assigned.text
    # L9 (Owner rule, applied after the L8 authority check): even an authorized caller
    # cannot withdraw the lead of an active R3 round; the lead changes only by replacement.
    before = list(v2_rows(repo))
    withdrawn = await http("POST", WITHDRAW.format(api=API, rid=rid), repo, json=CURRENT_T1_T2, role=role)
    assert code(withdrawn) == (409, "TECHNICIAN_ASSIGNMENT_PRIMARY_REQUIRED_ON_R3_ROUND")
    assert v2_rows(repo) == before


async def test_r3_l8_a_replayed_request_id_is_still_refused_without_the_finding_authority(clock) -> None:
    repo = repo_with()
    rid = await _r3_round(repo)
    request_id = str(uuid.uuid4())
    first = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1, T2), request_id=request_id,
                       **MANAGER)
    assert first.status_code == 200
    replay = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1, T2), request_id=request_id,
                        role="MAINTENANCE")
    assert replay.status_code == 403  # authority is checked before replay detection


async def test_r3_l8_service_fails_closed_without_a_caller_context_on_an_r3_round_only(clock) -> None:
    repo = repo_with()
    rid = await _r3_round(repo)
    service = TechnicianAssignmentService(repo, cut())
    with pytest.raises(HTTPException) as refused:
        await service.assign(REPAIR, rid, body(T1), request_id=str(uuid.uuid4()), user_id="x")
    assert refused.value.status_code == 403 and v2_rows(repo) == []
    manual = await new_repair(repo)  # a non-R3 order: the accepted service behaviour is unchanged
    assert (await service.assign(REPAIR, manual, body(T1), request_id=str(uuid.uuid4()), user_id="x")).changed


@pytest.mark.parametrize("role", ["MAINTENANCE", "SUPERVISOR", "MAINTENANCE_MANAGER", "ADMIN"])
async def test_r3_l8_non_r3_orders_keep_the_accepted_v2_authorization(clock, role) -> None:
    repo = repo_with()
    manual = (await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                         "source_type": "MANUAL"}, role="MAINTENANCE")).json()["repair"]["repair_id"]
    # A pre-R3 Finding (no item_key) keeps its Phase 4 behaviour: no round marker, no R3 check.
    legacy = await repo.create_inspection(
        asset_type=AssetType.VEHICLE, asset_id=VEH, checklist_id="CHK-0001", revision_id="REV-0001",
        revision_number=1, inspector_user_id="legacy", overall_remark=None,
        items=[NewInspectionItemInput(item_id="ITM-V-0001", sequence=1, title="t", is_critical=False,
                                      result=InspectionResultValue.FAIL)],
    )
    legacy_finding = legacy.findings[0].finding_id
    from_legacy = await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                             "source_type": "FINDING", "source_id": legacy_finding}, role="MAINTENANCE")
    assert from_legacy.status_code == 200 and from_legacy.json()["repair"]["finding_id"] is None
    for rid in (manual, from_legacy.json()["repair"]["repair_id"]):
        assigned = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1, T2), role=role)
        assert assigned.status_code == 200, assigned.text
        withdrawn = await http("POST", WITHDRAW.format(api=API, rid=rid), repo, json=CURRENT_T1_T2, role=role)
        assert withdrawn.status_code == 200, withdrawn.text
    for role_without in ("TECHNICIAN", "DRIVER"):  # unchanged: no can_manage_repair, no V2 write
        refused = await http("POST", ASSIGN.format(api=API, rid=manual), repo, json=body(T1), role=role_without)
        assert refused.status_code == 403


async def test_r3_l8_the_manager_assigning_never_makes_the_manager_the_completing_lead(clock) -> None:
    repo = repo_with()
    rid = await _r3_round(repo)
    assigned = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1, T2), **MANAGER)
    set_id = assigned.json()["current"]["assignment_set_id"]
    assert code(await complete(repo, rid, set_id, **MANAGER)) == (403, "REPAIR_COMPLETION_LEAD_ONLY")
    assert code(await complete(repo, rid, set_id, role="TECHNICIAN", user=U2)) == (403, "REPAIR_COMPLETION_LEAD_ONLY")
    assert (await complete(repo, rid, set_id)).status_code == 200  # the authenticated current PRIMARY


# ---------------------------------------------------------------------------
# L9 (Owner rule, R3 final correction): a PRIMARY must stay assigned during repair.
# The lead changes only through the existing V2 replacement (one atomic append of a
# complete new set; the earlier set stays in history). Mock evidence only (L3 / R11).
# ---------------------------------------------------------------------------


async def _http_upload(repo, rid: str):
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(f"{API}/attachments", data={"purpose": "REPAIR_EVIDENCE", "source_type": "REPAIR",
                                 "source_id": rid}, files={"file": ("e.jpg", b"jpeg", "image/jpeg")},
                                 headers={"X-Dev-Role": "MAINTENANCE_MANAGER", "X-Dev-User-Id": "USR-MGR"})


async def _replace(repo, rid: str, primary: str, *collaborators: str, expected: tuple[str, ...], **who):
    return await http("POST", ASSIGN.format(api=API, rid=rid), repo,
                      json=body(primary, *collaborators, expected=expected), **(who or MANAGER))


async def test_r3_l9_no_repair_work_is_recorded_before_a_lead_is_assigned(clock) -> None:
    repo = repo_with()
    rid = await _r3_round(repo)  # opened, awaiting its first assignment: allowed
    action = await http("POST", f"{API}/repairs/{rid}/actions", repo, json={"action_text": "ถอดฝาครอบ"}, **MANAGER)
    part = await http("POST", f"{API}/repairs/{rid}/parts", repo, json={"part_description": "ซีล"}, **MANAGER)
    evidence = await _http_upload(repo, rid)
    for refused in (action, part, evidence):
        assert code(refused) == (409, "REPAIR_LEAD_NOT_ASSIGNED"), refused.text
    detail = (await http("GET", f"{API}/repairs/{rid}", repo, **MANAGER)).json()
    assert detail["actions"] == [] and detail["parts"] == []
    assert (await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1), **MANAGER)).status_code == 200
    assert (await http("POST", f"{API}/repairs/{rid}/actions", repo, json={"action_text": "ถอดฝาครอบ"},
                       **MANAGER)).status_code == 200
    assert (await _http_upload(repo, rid)).status_code == 200


@pytest.mark.parametrize("new_primary", [T2, T3], ids=["existing-member", "new-technician"])
async def test_r3_l9_the_lead_is_replaced_atomically_and_only_the_new_lead_completes(clock, new_primary) -> None:
    repo = repo_with()
    rid = await _r3_round(repo)
    first = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1, T2), **MANAGER)
    old_set = first.json()["current"]["assignment_set_id"]
    rows_before = len(v2_rows(repo))
    collaborators = (T1,) if new_primary == T2 else (T1, T2)
    replaced = await _replace(repo, rid, new_primary, *collaborators, expected=(T1, T2))
    assert replaced.status_code == 200, replaced.text
    current = replaced.json()["current"]
    assert current["primary_technician_id"] == new_primary and current["assignment_set_id"] != old_set
    assert current["assigned_by_user_id"] == "USR-MGR"
    history = (await http("GET", ASSIGN.format(api=API, rid=rid), repo, **MANAGER)).json()
    assert {s["primary_technician_id"] for s in history["sets"]} == {T1, new_primary}  # earlier set kept
    assert len(history["sets"]) == 2 and history["withdrawals"] == []
    assert len(v2_rows(repo)) > rows_before  # appended, nothing rewritten
    new_user = {T2: U2, T3: U3}[new_primary]
    # The old lead, and the new lead holding a stale set id, are refused; the new lead completes.
    assert code(await complete(repo, rid, current["assignment_set_id"])) == (403, "REPAIR_COMPLETION_LEAD_ONLY")
    assert code(await complete(repo, rid, old_set, role="TECHNICIAN", user=new_user)) == (409, "REPAIR_ASSIGNMENT_STALE")
    done = await complete(repo, rid, current["assignment_set_id"], role="TECHNICIAN", user=new_user)
    assert done.status_code == 200, done.text
    assert done.json()["repair"]["completion_technician_id"] == new_primary


@pytest.mark.parametrize(("payload", "expected_code"), [
    (lambda: body(T2, T1, expected=(T1,)), "TECHNICIAN_ASSIGNMENT_STALE"),  # wrong expected_current
    (lambda: body("TEC-NOPE", T1, expected=(T1, T2)), "TECHNICIAN_NOT_FOUND"),  # unknown replacement
    (lambda: body(T2, T2, expected=(T1, T2)), "TECHNICIAN_ASSIGNMENT_DUPLICATE_ASSIGNEE"),
], ids=["stale", "unknown-technician", "duplicate"])
async def test_r3_l9_a_failed_replacement_keeps_the_original_lead_and_every_row(clock, payload, expected_code) -> None:
    repo = repo_with()
    rid = await _r3_round(repo)
    first = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=body(T1, T2), **MANAGER)
    rows_before = list(v2_rows(repo))
    refused = await http("POST", ASSIGN.format(api=API, rid=rid), repo, json=payload(), **MANAGER)
    assert refused.status_code in (409, 422) and refused.json()["error"]["code"] == expected_code, refused.text
    assert v2_rows(repo) == rows_before
    current = (await http("GET", ASSIGN.format(api=API, rid=rid), repo, **MANAGER)).json()["current"]
    assert current["primary_technician_id"] == T1
    assert current["assignment_set_id"] == first.json()["current"]["assignment_set_id"]


async def test_r3_l9_non_r3_orders_keep_withdrawal_and_recording_without_assignment(clock) -> None:
    repo = repo_with()
    manual = (await http("POST", f"{API}/repairs", repo, json={"asset_type": "VEHICLE", "asset_id": VEH,
                         "source_type": "MANUAL"}, role="MAINTENANCE")).json()["repair"]["repair_id"]
    recorded = await http("POST", f"{API}/repairs/{manual}/actions", repo, json={"action_text": "ตรวจ"},
                          role="MAINTENANCE")
    assert recorded.status_code == 200, recorded.text  # accepted rule: capability, no V2 set needed
    assert (await http("POST", ASSIGN.format(api=API, rid=manual), repo, json=body(T1, T2),
                       role="MAINTENANCE")).status_code == 200
    withdrawn = await http("POST", WITHDRAW.format(api=API, rid=manual), repo, json=CURRENT_T1_T2, role="MAINTENANCE")
    assert withdrawn.status_code == 200, withdrawn.text


# ---------------------------------------------------------------------------
# L10 (Owner rule, R3 final correction; R3-F1 extends it to every source with the narrow
# can_cancel_repair_request, D8-A): the Maintenance Department Manager cancels a
# duplicate PENDING Repair Request, by hand, with a reason.
# Never automatic; the record and its history are kept; it can never be converted.
# ---------------------------------------------------------------------------


async def _finding_request(repo, finding_id: str) -> dict:
    reported = await http("POST", f"{API}/repair-requests", repo, json={"vehicle_id": VEH, "symptom_th": "น้ำมันรั่ว",
                          "source_type": "FINDING", "source_id": finding_id, "note_th": "แจ้งจากหน้างาน"},
                          **INSPECTOR)
    assert reported.status_code == 200, reported.text
    return reported.json()["request"]


def _cancel(repo, request_id: str, payload: dict | None = None, **who):
    return http("POST", f"{API}/repair-requests/{request_id}/cancellation", repo,
                json=payload if payload is not None else {"reason_th": "ซ้ำกับใบงานที่กำลังซ่อม"}, **(who or MANAGER))


async def test_r3_l10_the_manager_cancels_a_duplicate_pending_request_with_its_audit_kept(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    rpr = (await open_round(repo, f1)).json()["repair"]["repair_id"]  # the work that started first
    original = await _finding_request(repo, f1)  # the duplicate report of the same defect
    queue = (await http("GET", f"{API}/repair-requests/pending", repo, **MANAGER)).json()["items"]
    assert original["repair_request_id"] in {i["repair_request_id"] for i in queue}
    assert code(await _cancel(repo, original["repair_request_id"], {"reason_th": "   "})) == \
        (422, "REPAIR_REQUEST_CANCEL_REASON_REQUIRED")
    assert code(await _cancel(repo, original["repair_request_id"], {"reason_th": "ซ้ำ",
                                                                    "duplicate_of_repair_id": "RPR-9999"})) == \
        (422, "REPAIR_REQUEST_DUPLICATE_REFERENCE_NOT_FOUND")
    cancelled = await _cancel(repo, original["repair_request_id"], {"reason_th": "ซ้ำกับใบงานที่กำลังซ่อม",
                                                                    "duplicate_of_repair_id": rpr})
    assert cancelled.status_code == 200, cancelled.text
    after = cancelled.json()
    assert after["request_status"] == "CANCELLED"
    assert (after["cancelled_by_user_id"], after["cancel_reason_th"], after["duplicate_of_repair_id"]) == \
        ("USR-MGR", "ซ้ำกับใบงานที่กำลังซ่อม", rpr)
    assert after["cancelled_at"] is not None and after["repair_id"] is None
    audit = {"request_status", "cancelled_at", "cancelled_by_user_id", "cancel_reason_th", "duplicate_of_repair_id",
             "duplicate_of_repair_request_id"}
    assert {k: v for k, v in original.items() if k in audit - {"request_status"}} == dict.fromkeys(audit - {"request_status"})
    assert {k: after[k] for k in original if k not in audit} == \
        {k: original[k] for k in original if k not in audit}  # requester, source, dates, note unchanged
    queue = (await http("GET", f"{API}/repair-requests/pending", repo, **MANAGER)).json()["items"]
    assert original["repair_request_id"] not in {i["repair_request_id"] for i in queue}  # out of the actionable queue
    history = await http("GET", f"{API}/repair-requests/{original['repair_request_id']}", repo, **MANAGER)
    assert history.status_code == 200 and history.json()["request_status"] == "CANCELLED"  # still in history
    mine = (await http("GET", f"{API}/repair-requests/mine", repo, **INSPECTOR)).json()["items"]
    assert [i["request_status"] for i in mine if i["repair_request_id"] == original["repair_request_id"]] == \
        ["CANCELLED"]
    by_source = (await http("GET", f"{API}/repair-requests/by-source/FINDING/{f1}", repo, **INSPECTOR)).json()
    assert [r["request_status"] for r in by_source] == ["CANCELLED"]
    # The cancelled request can never become a Work Order, and a second cancel is refused.
    assert code(await http("POST", f"{API}/repair-requests/{original['repair_request_id']}/convert", repo,
                           json={}, **MANAGER)) == (409, "REPAIR_REQUEST_CANCELLED")
    assert code(await _cancel(repo, original["repair_request_id"])) == (409, "REPAIR_REQUEST_NOT_PENDING")
    detail = (await http("GET", f"{API}/repairs/{rpr}", repo, **MANAGER)).json()["repair"]
    assert detail["status"] == "OPEN"  # the active work is untouched


@pytest.mark.parametrize("role", ["MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER", "DRIVER_DEPARTMENT_MANAGER"])
async def test_r3_l10_only_the_finding_authority_cancels(clock, role) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    request = await _finding_request(repo, f1)
    assert (await _cancel(repo, request["repair_request_id"], role=role)).status_code == 403
    after = await http("GET", f"{API}/repair-requests/{request['repair_request_id']}", repo, **MANAGER)
    assert after.json()["request_status"] == "PENDING"
    assert (await _cancel(repo, request["repair_request_id"], role="ADMIN")).status_code == 200


async def test_r3_l10_a_converted_or_conversion_linked_request_cannot_be_cancelled(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    request = await _finding_request(repo, f1)
    converted = await http("POST", f"{API}/repair-requests/{request['repair_request_id']}/convert", repo, json={},
                           **MANAGER)
    assert converted.status_code == 200
    assert code(await _cancel(repo, request["repair_request_id"])) == (409, "REPAIR_REQUEST_NOT_PENDING")
    # An interrupted conversion (Work Order linked, status still PENDING) also counts as converted.
    repo._repair_requests[request["repair_request_id"]] = repo._repair_requests[request["repair_request_id"]] \
        .model_copy(update={"request_status": "PENDING", "repair_id": None, "converted_at": None})
    assert code(await _cancel(repo, request["repair_request_id"])) == (409, "REPAIR_REQUEST_NOT_PENDING")


async def test_r3_l10_an_ended_finding_never_cancels_its_pending_request_automatically(clock) -> None:
    repo = repo_with()
    f1 = (await submit(repo, fail())).json()["findings"][0]["finding_id"]
    request = await _finding_request(repo, f1)
    await http("POST", f"{API}/findings/{f1}/termination", repo, json={"reason": "ยุติ"}, **MANAGER)
    clock(DAY1 + timedelta(days=1))
    await submit(repo)  # a later PASS on the same asset changes nothing either
    after = await http("GET", f"{API}/repair-requests/{request['repair_request_id']}", repo, **MANAGER)
    assert after.json()["request_status"] == "PENDING" and after.json()["cancelled_at"] is None
    # The Manager resolves it by hand: the request is out of the queue but kept.
    assert (await _cancel(repo, request["repair_request_id"], {"reason_th": "รายการผิดปกติสิ้นสุดแล้ว"})).status_code == 200


async def test_r3_l10_requests_without_r3_finding_provenance_keep_the_accepted_flow(clock) -> None:
    """R3-F1 (Owner decision D8-A, supersedes the Finding-only scope of L10): an ordinary
    manual report can now be cancelled by the Manager too; one that is not cancelled
    converts exactly as before."""
    repo = repo_with()
    manual = await http("POST", f"{API}/repair-requests", repo, json={"vehicle_id": VEH, "symptom_th": "เบรกมีเสียง"},
                        role="DRIVER")
    request_id = manual.json()["request"]["repair_request_id"]
    assert (await _cancel(repo, request_id)).json()["request_status"] == "CANCELLED"
    other = await http("POST", f"{API}/repair-requests", repo, json={"vehicle_id": VEH, "symptom_th": "ไฟท้ายไม่ติด"},
                       role="DRIVER")
    converted = await http("POST", f"{API}/repair-requests/{other.json()['request']['repair_request_id']}/convert",
                           repo, json={}, role="MAINTENANCE")
    assert converted.status_code == 200  # unrelated requests convert exactly as before
    assert converted.json()["repair"]["finding_id"] is None
