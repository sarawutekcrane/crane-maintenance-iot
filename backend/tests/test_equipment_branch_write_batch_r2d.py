"""R2 Batch R2d — equipment responsible-branch writes (history-only) over HTTP
with the MOCK repository.

Test ids R2D-01..R2D-40 are batch-local PROPOSED identifiers. Every fixture is
SYNTHETIC: the mock seed's EQP-* equipment, its synthetic BR-* branches and
labelled synthetic history rows. No live workbook value is used. The fake
Sheets counterpart (26-column history contract, legacy 9-column refusal,
is_active absent, REAL context, request counts) is
test_equipment_branch_write_sheets_batch_r2d.py.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain import authz
from app.domain.branch_timeline import ASSET_BRANCH_HISTORY_COLUMNS, validate_branch_row
from app.domain.equipment_branch_history import (
    equipment_history_rows,
    equipment_timeline,
)
from app.domain.registry_write_support import MOCK_TEST_BATCH_ID
from app.domain.request_replay import (
    OP_CANCELLATION,
    OP_CORRECTION,
    OP_EQUIPMENT_ASSIGNMENT,
    OP_EQUIPMENT_CANCELLATION,
    OP_EQUIPMENT_CORRECTION,
    OP_EQUIPMENT_INSERTION,
    OP_INSERTION,
    OP_TRANSFER,
    request_fingerprint,
)
from app.repositories.base import RegistryTableRead
from app.repositories.mock import MockRepository
from tests.test_registration_write_batch7o2b import _http
from tests.test_registry_read_api_batch7o2a import SpyRepository

API = "/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
EQP, EQP2 = "EQP-0001", "EQP-0002"  # seeded synthetic equipment, no branch history
LAEM, BANGNA, RAYONG = "BR-LAEM-CHABANG", "BR-BANGNA-KM6", "BR-RAYONG"  # synthetic mock branches
OTHER_ROLES = ("MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER")
EQUIPMENT_CAP = "can_transfer_equipment_branch"
CORRECT_CAP = "can_correct_branch_history"
VEHICLE_CAP = "can_transfer_vehicle_branch"
# The spy also logs nested calls: the mock's get_equipment_validated delegates to get_equipment.
READS_OK = {"get_equipment_validated", "get_equipment", "read_asset_branch_history_validated",
            "read_branch_master_validated", "append_asset_branch_history"}


def _rid() -> str:
    return str(uuid.uuid4())


def _err(response) -> dict:
    return response.json()["error"]


def _rows(repo: MockRepository, eid: str = EQP) -> list[dict[str, str]]:
    return equipment_history_rows(repo._asset_branch_history, eid)


def _tl(repo: MockRepository, eid: str = EQP):
    return equipment_timeline(_rows(repo, eid), context="TEST")


def _date(d: str) -> dict:
    return {"mode": "DATE", "date": d}


def _at(at: str) -> dict:
    return {"mode": "DATETIME", "at": at}


def assign_body(repo, eid=EQP, to=RAYONG, effective=None, **extra) -> dict:
    body = {"to_branch_id": to, "effective": effective or _date("2026-09-01"),
            "expected_current_branch_id": _tl(repo, eid).current_branch_id,
            "expected_history_revision": _tl(repo, eid).revision}
    body.update(extra)
    return body


def insertion_body(repo, eid=EQP, to=BANGNA, effective=None, **extra) -> dict:
    body = {"to_branch_id": to, "effective": effective or _date("2026-09-05"),
            "reason_th": "บันทึกย้อนหลัง (ข้อมูลสังเคราะห์)", "expected_history_revision": _tl(repo, eid).revision}
    body.update(extra)
    return body


def correction_body(repo, eid=EQP, to=LAEM, effective=None, **extra) -> dict:
    body = {"to_branch_id": to, "effective": effective or _date("2026-09-02"),
            "reason_th": "แก้ไขข้อมูล (ข้อมูลสังเคราะห์)", "expected_history_revision": _tl(repo, eid).revision}
    body.update(extra)
    return body


def cancellation_body(repo, eid=EQP, **extra) -> dict:
    body = {"reason_th": "บันทึกผิด (ข้อมูลสังเคราะห์)", "expected_history_revision": _tl(repo, eid).revision}
    body.update(extra)
    return body


def p_assign(eid=EQP):
    return f"{API}/equipment/{eid}/branch-assignments"


def p_insert(eid=EQP):
    return f"{API}/equipment/{eid}/branch-history/insertions"


def p_correct(event_id: str, eid=EQP):
    return f"{API}/equipment/{eid}/branch-history/events/{event_id}/corrections"


def p_cancel(event_id: str, eid=EQP):
    return f"{API}/equipment/{eid}/branch-history/events/{event_id}/cancellations"


async def post(path: str, body, repo, **kw):
    return await _http("POST", path, repo=repo, json_body=body, **kw)


async def read(repo, eid=EQP) -> dict:
    response = await _http("GET", f"{API}/equipment/{eid}/branch-history", repo=repo, request_id=None)
    assert response.status_code == 200, response.text
    return response.json()


async def assigned(repo, *pairs: tuple[str, str], eid=EQP) -> list[str]:
    """Record the given (branch, date) assignments in order; their event ids."""
    out = []
    for branch, day in pairs:
        response = await post(p_assign(eid), assign_body(repo, eid, to=branch, effective=_date(day)), repo)
        assert response.status_code == 200, response.text
        out.append(response.json()["event_id"])
    return out


def _fp(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def syn_assignment(eid: str, branch: str, start: str, n: int, *, first: bool, asset=EQP) -> dict[str, str]:
    """A strict-valid synthetic EQUIPMENT ASSIGNMENT row (for tie cases)."""
    row = dict.fromkeys(ASSET_BRANCH_HISTORY_COLUMNS, "")
    row.update(assignment_id=eid, asset_type="EQUIPMENT", asset_id=asset, record_kind="ASSIGNMENT",
               entry_operation="TRANSFER", event_id=eid, revision_no="1", branch_id=branch, start_at=start,
               effective_precision="DATETIME", effective_source="CLIENT", recorded_from_source="NONE",
               recorded_at=f"2026-09-0{n}T03:00:00+00:00", recorded_by="synthetic", request_id=f"syn-{eid}",
               request_fingerprint=_fp(eid), is_test_data="TRUE", test_batch_id="SYN-R2D")
    if first:
        row["baseline_source"] = "NONE"
    return row


T1, T2 = "2026-08-10T00:00:00+00:00", "2026-08-20T00:00:00+00:00"
EA, EB, EC = ("ABH-" + c * 32 for c in "def")


def tie_repo() -> MockRepository:
    """EQP-0001 with two in-force events at one instant (AMBIGUOUS_ORDER) and
    an earlier untied event."""
    repo = SpyRepository()
    repo._asset_branch_history.extend([
        syn_assignment(EA, BANGNA, T1, 1, first=True),
        syn_assignment(EB, RAYONG, T2, 2, first=False),
        syn_assignment(EC, LAEM, T2, 3, first=False),
    ])
    assert _tl(repo).status == "AMBIGUOUS_ORDER"
    return repo


@pytest.fixture
def synthetic_roles(monkeypatch):
    """Dev roles holding exactly one branch capability each (plus can_view)."""
    for name, cap in (("SYN_EQUIPMENT_ONLY", EQUIPMENT_CAP), ("SYN_CORRECT_ONLY", CORRECT_CAP),
                      ("SYN_VEHICLE_ONLY", VEHICLE_CAP)):
        monkeypatch.setitem(authz.ROLE_CAPABILITIES, name, frozenset({authz.CAN_VIEW, cap}))


# ===========================================================================
# R2D-01..R2D-04 — first assignment, later assignment, no-op
# ===========================================================================


@pytest.mark.asyncio
async def test_r2d_01_first_assignment_with_unknown_prior_branch() -> None:
    repo = MockRepository()
    body = assign_body(repo)
    assert body["expected_current_branch_id"] is None
    response = await post(p_assign(), body, repo)
    assert response.status_code == 200, response.text
    out = response.json()
    assert set(out) == {"request_id", "changed", "record_id", "event_id", "timeline_status_after",
                        "current_branch_id", "current_source"}
    assert (out["changed"], out["current_branch_id"], out["current_source"], out["timeline_status_after"]) == (
        True, RAYONG, "EVENT", "VALID")
    (row,) = _rows(repo)
    assert row["assignment_id"] == out["record_id"] == out["event_id"] == row["event_id"]
    assert (row["record_kind"], row["entry_operation"], row["revision_no"]) == ("ASSIGNMENT", "TRANSFER", "1")
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == ("", "NONE")
    assert (row["baseline_branch_id"], row["baseline_source"]) == ("", "NONE")
    assert validate_branch_row(row) == []


@pytest.mark.asyncio
async def test_r2d_02_first_assignment_writes_one_history_row_only() -> None:
    repo = SpyRepository()
    equipment_before = {k: v.model_dump() for k, v in repo._equipment.items()}
    vehicles_before = repr(repo._vehicle_registry)
    response = await post(p_assign(), assign_body(repo), repo)
    assert response.status_code == 200
    assert repo.registry_write_log == ["W1"]
    assert set(repo.calls) <= READS_OK and repo.calls.count("append_asset_branch_history") == 1
    assert {k: v.model_dump() for k, v in repo._equipment.items()} == equipment_before
    assert repr(repo._vehicle_registry) == vehicles_before


@pytest.mark.asyncio
async def test_r2d_03_later_assignment_source_comes_from_event() -> None:
    repo = MockRepository()
    first, second = await assigned(repo, (RAYONG, "2026-09-01"), (LAEM, "2026-09-10"))
    rows = _rows(repo)
    assert (rows[1]["recorded_from_branch_id"], rows[1]["recorded_from_source"]) == (RAYONG, "EVENT")
    assert (rows[1]["baseline_branch_id"], rows[1]["baseline_source"]) == ("", "")  # first record only
    assert (_tl(repo).current_branch_id, _tl(repo).current_source) == (LAEM, "EVENT")
    assert first != second


@pytest.mark.asyncio
async def test_r2d_04_same_destination_is_a_noop_with_no_branch_master_read_and_no_write() -> None:
    repo = MockRepository()
    await assigned(repo, (RAYONG, "2026-09-01"))
    spy = SpyRepository()
    spy._asset_branch_history = repo._asset_branch_history
    response = await post(p_assign(), assign_body(spy, to=RAYONG, effective=_date("2026-09-10")), spy)
    assert response.status_code == 200
    assert response.json() == {"request_id": response.json()["request_id"], "changed": False, "warnings": []}
    assert "read_branch_master_validated" not in spy.calls
    assert spy.registry_write_log == [] and len(_rows(spy)) == 1


# ===========================================================================
# R2D-05..R2D-08 — stale guards, same instant, latest rule
# ===========================================================================


@pytest.mark.asyncio
async def test_r2d_05_expected_current_branch_is_a_stale_guard() -> None:
    repo = MockRepository()
    response = await post(p_assign(), assign_body(repo, expected_current_branch_id=BANGNA), repo)
    assert (response.status_code, _err(response)["code"]) == (409, "BRANCH_HISTORY_STALE")
    assert _err(response)["details"] == {"field": "current_branch_id"}
    await assigned(repo, (RAYONG, "2026-09-01"))
    stale = await post(p_assign(), assign_body(repo, to=LAEM, effective=_date("2026-09-10"),
                                               expected_current_branch_id=None), repo)
    assert _err(stale)["details"] == {"field": "current_branch_id"}
    assert repo.registry_write_log == ["W1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["assign", "insert", "correct", "cancel"])
async def test_r2d_06_history_revision_is_a_stale_guard(path) -> None:
    repo = MockRepository()
    (event,) = await assigned(repo, (RAYONG, "2026-09-10"))
    builders = {"assign": (p_assign(), assign_body(repo, to=LAEM, effective=_date("2026-09-20"))),
                "insert": (p_insert(), insertion_body(repo)),
                "correct": (p_correct(event), correction_body(repo)),
                "cancel": (p_cancel(event), cancellation_body(repo))}
    path_, body = builders[path]
    body["expected_history_revision"] = "BHR1-00000000000000000000"
    response = await post(path_, body, repo)
    assert (response.status_code, _err(response)["code"]) == (409, "BRANCH_HISTORY_STALE")
    assert _err(response)["details"] == {"field": "history_revision"}
    assert repo.registry_write_log == ["W1"]


@pytest.mark.asyncio
async def test_r2d_06_another_assets_rows_do_not_change_this_revision() -> None:
    repo = MockRepository()
    before = _tl(repo).revision
    await assigned(repo, (RAYONG, "2026-09-01"), eid=EQP2)
    assert _tl(repo).revision == before


@pytest.mark.asyncio
async def test_r2d_07_same_effective_instant_is_refused() -> None:
    repo = MockRepository()
    await assigned(repo, (RAYONG, "2026-09-10"))
    response = await post(p_assign(), assign_body(repo, to=LAEM, effective=_date("2026-09-10")), repo)
    assert (response.status_code, _err(response)["code"]) == (409, "BRANCH_EVENT_SAME_INSTANT")
    insert = await post(p_insert(), insertion_body(repo, effective=_date("2026-09-10")), repo)
    assert _err(insert)["code"] == "BRANCH_EVENT_SAME_INSTANT"


@pytest.mark.asyncio
async def test_r2d_08_not_latest_assignment_and_non_historical_insertion() -> None:
    repo = MockRepository()
    no_event = await post(p_insert(), insertion_body(repo), repo)
    assert (no_event.status_code, _err(no_event)["code"]) == (409, "BRANCH_INSERTION_NOT_HISTORICAL")
    await assigned(repo, (RAYONG, "2026-09-10"))
    earlier = await post(p_assign(), assign_body(repo, to=LAEM, effective=_date("2026-09-01")), repo)
    assert (earlier.status_code, _err(earlier)["code"]) == (409, "BRANCH_TRANSFER_NOT_LATEST")
    later = await post(p_insert(), insertion_body(repo, effective=_date("2026-09-20")), repo)
    assert _err(later)["code"] == "BRANCH_INSERTION_NOT_HISTORICAL"
    future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    ahead = await post(p_assign(), assign_body(repo, to=LAEM, effective=_date(future)), repo)
    assert (ahead.status_code, _err(ahead)["code"]) == (422, "FUTURE_EFFECTIVE_NOT_ALLOWED")
    assert repo.registry_write_log == ["W1"]


# ===========================================================================
# R2D-09..R2D-12 — insertion, correction, cancellation, ambiguity
# ===========================================================================


@pytest.mark.asyncio
async def test_r2d_09_backdated_insertion() -> None:
    repo = MockRepository()
    await assigned(repo, (RAYONG, "2026-09-01"), (LAEM, "2026-09-10"))
    between = await post(p_insert(), insertion_body(repo, to=BANGNA, effective=_date("2026-09-05")), repo)
    assert between.status_code == 200 and between.json()["current_branch_id"] == LAEM
    row = _rows(repo)[-1]
    assert (row["entry_operation"], row["recorded_from_branch_id"], row["recorded_from_source"]) == (
        "INSERTION", RAYONG, "EVENT")
    assert row["note_th"] == "บันทึกย้อนหลัง (ข้อมูลสังเคราะห์)"
    before_first = await post(p_insert(), insertion_body(repo, to=BANGNA, effective=_date("2026-08-20")), repo)
    assert before_first.status_code == 200
    assert (_rows(repo)[-1]["recorded_from_branch_id"], _rows(repo)[-1]["recorded_from_source"]) == ("", "NONE")
    noop = await post(p_insert(), insertion_body(repo, to=BANGNA, effective=_date("2026-09-07")), repo)
    assert noop.json()["changed"] is False
    no_reason = await post(p_insert(), insertion_body(repo, reason_th="  "), repo)
    assert (no_reason.status_code, _err(no_reason)["code"]) == (422, "REASON_REQUIRED")


@pytest.mark.asyncio
async def test_r2d_10_correction() -> None:
    repo = SpyRepository()
    first, latest = await assigned(repo, (RAYONG, "2026-09-01"), (LAEM, "2026-09-10"))
    response = await post(p_correct(first), correction_body(repo, to=BANGNA, effective=_date("2026-09-02")), repo)
    assert response.status_code == 200 and response.json()["event_id"] == first
    row = _rows(repo)[-1]
    original = next(r for r in _rows(repo) if r["assignment_id"] == first)
    assert (row["record_kind"], row["revision_no"], row["supersedes_record_id"]) == ("CORRECTION", "2", first)
    assert original["branch_id"] == RAYONG  # earlier rows are never edited
    repo.calls.clear()
    time_only = await post(p_correct(latest), correction_body(repo, to=LAEM, effective=_date("2026-09-11")), repo)
    assert time_only.status_code == 200 and "read_branch_master_validated" not in repo.calls
    unknown = await post(p_correct("ABH-" + "0" * 32), correction_body(repo), repo)
    assert (unknown.status_code, _err(unknown)["code"]) == (404, "BRANCH_EVENT_NOT_FOUND")
    await post(p_cancel(first), cancellation_body(repo), repo)
    cancelled = await post(p_correct(first), correction_body(repo), repo)
    assert (cancelled.status_code, _err(cancelled)["code"]) == (409, "BRANCH_EVENT_CANCELLED")


@pytest.mark.asyncio
async def test_r2d_11_cancellation() -> None:
    repo = MockRepository()
    first, latest = await assigned(repo, (RAYONG, "2026-09-01"), (LAEM, "2026-09-10"))
    response = await post(p_cancel(latest), cancellation_body(repo), repo)
    assert response.status_code == 200
    assert (response.json()["current_branch_id"], response.json()["current_source"]) == (RAYONG, "EVENT")
    row = _rows(repo)[-1]
    assert (row["record_kind"], row["entry_operation"], row["revision_no"], row["supersedes_record_id"]) == (
        "CANCELLATION", "CANCELLATION", "2", latest)
    assert row["branch_id"] == "" and row["start_at"] == ""
    again = await post(p_cancel(latest), cancellation_body(repo), repo)
    assert (again.status_code, _err(again)["code"]) == (409, "BRANCH_EVENT_CANCELLED")
    last = await post(p_cancel(first), cancellation_body(repo), repo)
    assert (last.json()["current_branch_id"], last.json()["current_source"]) == (None, "NONE")


@pytest.mark.asyncio
async def test_r2d_12_ambiguous_timeline_and_tie_target_rules() -> None:
    repo = tie_repo()
    blocked = await post(p_assign(), assign_body(repo, to=BANGNA, effective=_date("2026-09-15")), repo)
    assert (blocked.status_code, _err(blocked)["code"]) == (409, "BRANCH_TIMELINE_AMBIGUOUS")
    assert _err(blocked)["details"] == {"reason": "TIMELINE_AMBIGUOUS"}
    insert = await post(p_insert(), insertion_body(repo, effective=_date("2026-08-15")), repo)
    assert _err(insert)["code"] == "BRANCH_TIMELINE_AMBIGUOUS"
    untied = await post(p_correct(EA), correction_body(repo, effective=_at("2026-08-11T00:00:00+00:00")), repo)
    assert _err(untied)["details"] == {"reason": "TARGET_NOT_TIED"}
    untied_cancel = await post(p_cancel(EA), cancellation_body(repo), repo)
    assert _err(untied_cancel)["details"] == {"reason": "TARGET_NOT_TIED"}
    assert repo.registry_write_log == []
    fixed = await post(p_correct(EC), correction_body(repo, to=LAEM, effective=_at("2026-08-25T00:00:00+00:00")),
                       repo)
    assert fixed.status_code == 200 and fixed.json()["timeline_status_after"] == "VALID"
    assert (fixed.json()["current_branch_id"], fixed.json()["current_source"]) == (LAEM, "EVENT")


# ===========================================================================
# R2D-13..R2D-15 — destination branch (R1 rules reused)
# ===========================================================================


@pytest.mark.asyncio
async def test_r2d_13_destination_not_found() -> None:
    repo = MockRepository()
    for code in ("BR-NOWHERE", "br-rayong", " BR-RAYONG"):
        response = await post(p_assign(), assign_body(repo, to=code), repo)
        assert (response.status_code, _err(response)["code"]) == (422, "BRANCH_NOT_FOUND")
    assert repo.registry_write_log == [] and _rows(repo) == []


@pytest.mark.asyncio
async def test_r2d_14_inactive_destination_when_is_active_exists() -> None:
    repo = MockRepository()
    next(b for b in repo._branch_master if b["branch_id"] == RAYONG)["is_active"] = "FALSE"
    response = await post(p_assign(), assign_body(repo, to=RAYONG), repo)
    assert (response.status_code, _err(response)["code"]) == (422, "BRANCH_INACTIVE")
    next(b for b in repo._branch_master if b["branch_id"] == RAYONG)["is_active"] = "maybe"
    invalid = await post(p_assign(), assign_body(repo, to=RAYONG), repo)
    assert (invalid.status_code, _err(invalid)["code"]) == (500, "BRANCH_MASTER_DATA_INVALID")
    assert repo.registry_write_log == []


class _NoActiveColumn(MockRepository):
    async def read_branch_master_validated(self) -> RegistryTableRead:
        rows = [{"branch_id": b["branch_id"], "branch_name": b["branch_name"]} for b in self._branch_master]
        return RegistryTableRead(rows=rows, columns=frozenset({"branch_id", "branch_name"}))


@pytest.mark.asyncio
async def test_r2d_15_branch_master_without_is_active_follows_the_frozen_r1_rule() -> None:
    repo = _NoActiveColumn()
    next(b for b in repo._branch_master if b["branch_id"] == RAYONG)["is_active"] = "FALSE"  # not a column here
    response = await post(p_assign(), assign_body(repo, to=RAYONG), repo)
    assert response.status_code == 200  # without the column every branch is active (R1 C-c8)
    missing = await post(p_assign(), assign_body(repo, to="BR-NOWHERE", effective=_date("2026-09-05")), repo)
    assert _err(missing)["code"] == "BRANCH_NOT_FOUND"


# ===========================================================================
# R2D-16..R2D-20 — authorization and request id (all before any read)
# ===========================================================================


@pytest.mark.asyncio
async def test_r2d_16_equipment_assignment_capability_holders() -> None:
    for role in ("ADMIN", "MAINTENANCE_MANAGER"):
        repo = MockRepository()
        assert (await post(p_assign(), assign_body(repo), repo, role=role)).status_code == 200
    for role in (*OTHER_ROLES, "NO_SUCH_ROLE"):
        repo = SpyRepository()
        response = await post(p_assign(), assign_body(repo), repo, role=role)
        assert (response.status_code, _err(response)["code"]) == (403, "HTTP_ERROR")
        assert repo.calls == [], role


@pytest.mark.asyncio
async def test_r2d_17_vehicle_transfer_capability_does_not_authorize_equipment(synthetic_roles) -> None:
    repo = SpyRepository()
    response = await post(p_assign(), assign_body(repo), repo, role="SYN_VEHICLE_ONLY")
    assert response.status_code == 403 and repo.calls == []
    assert EQUIPMENT_CAP not in authz.capabilities_for_roles(("SYN_VEHICLE_ONLY",))
    # ...and the equipment capability does not authorize a vehicle transfer.
    vehicle = await post(f"{API}/vehicles/VEH-1046/branch-transfers", {}, repo, role="SYN_EQUIPMENT_ONLY")
    assert vehicle.status_code == 403 and repo.calls == []


@pytest.mark.asyncio
async def test_r2d_18_correction_capability_covers_equipment_history(synthetic_roles) -> None:
    for role in ("MAINTENANCE_MANAGER", "SYN_CORRECT_ONLY"):
        repo = MockRepository()
        await assigned(repo, (RAYONG, "2026-09-01"), (LAEM, "2026-09-10"))
        first, latest = (r["assignment_id"] for r in _rows(repo))
        assert (await post(p_insert(), insertion_body(repo), repo, role=role)).status_code == 200
        assert (await post(p_correct(first), correction_body(repo), repo, role=role)).status_code == 200
        assert (await post(p_cancel(latest), cancellation_body(repo), repo, role=role)).status_code == 200
    for role in OTHER_ROLES:
        repo = SpyRepository()
        for path in (p_insert(), p_correct(EA), p_cancel(EA)):
            assert (await post(path, {}, repo, role=role)).status_code == 403
        assert repo.calls == []


@pytest.mark.asyncio
async def test_r2d_19_transfer_and_correction_capabilities_are_independent(synthetic_roles) -> None:
    repo = SpyRepository()
    for path in (p_insert(), p_correct(EA), p_cancel(EA)):
        assert (await post(path, {}, repo, role="SYN_EQUIPMENT_ONLY")).status_code == 403
    assert (await post(p_assign(), assign_body(repo), repo, role="SYN_CORRECT_ONLY")).status_code == 403
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [None, "", "not-a-uuid"])
async def test_r2d_20_client_request_id_is_required_before_any_read(request_id) -> None:
    repo = SpyRepository()
    for path in (p_assign(), p_insert(), p_correct(EA), p_cancel(EA)):
        response = await post(path, {"to_branch_id": RAYONG}, repo, request_id=request_id)
        assert (response.status_code, _err(response)["code"]) == (422, "REQUEST_ID_REQUIRED")
    assert repo.calls == []


# ===========================================================================
# R2D-21..R2D-23 — replay and cross-asset request-id safety
# ===========================================================================


@pytest.mark.asyncio
async def test_r2d_21_same_equipment_same_request_is_replayed() -> None:
    repo = MockRepository()
    rid = _rid()
    body = assign_body(repo)
    first = await post(p_assign(), body, repo, request_id=rid)
    again = await post(p_assign(), body, repo, request_id=rid)
    assert again.status_code == 200
    assert again.json() == {"request_id": rid, "replayed": True, "record_ids": [first.json()["record_id"]]}
    assert repo.registry_write_log == ["W1"] and len(_rows(repo)) == 1
    changed = await post(p_assign(), {**body, "note_th": "อื่น"}, repo, request_id=rid)
    assert (changed.status_code, _err(changed)["code"]) == (409, "REQUEST_ID_REUSED")


@pytest.mark.asyncio
async def test_r2d_22_same_request_id_for_another_equipment_is_reused() -> None:
    repo = MockRepository()
    rid = _rid()
    assert (await post(p_assign(), assign_body(repo), repo, request_id=rid)).status_code == 200
    other = await post(p_assign(EQP2), assign_body(repo, EQP2), repo, request_id=rid)
    assert (other.status_code, _err(other)["code"]) == (409, "REQUEST_ID_REUSED")
    assert _rows(repo, EQP2) == []


def test_r2d_23_equipment_and_vehicle_fingerprints_never_collide() -> None:
    body = {"to_branch_id": RAYONG, "effective": _date("2026-09-01"), "expected_current_branch_id": None,
            "expected_history_revision": "BHR1-x"}
    for vehicle_op, equipment_op in ((OP_TRANSFER, OP_EQUIPMENT_ASSIGNMENT), (OP_INSERTION, OP_EQUIPMENT_INSERTION),
                                     (OP_CORRECTION, OP_EQUIPMENT_CORRECTION),
                                     (OP_CANCELLATION, OP_EQUIPMENT_CANCELLATION)):
        assert request_fingerprint(vehicle_op, "SAME-ID", "E", body) != request_fingerprint(
            equipment_op, "SAME-ID", "E", body)
    assert (OP_TRANSFER, OP_INSERTION, OP_CORRECTION, OP_CANCELLATION) == (
        "transfer", "insertion", "correction", "cancellation")  # vehicle values unchanged


@pytest.mark.asyncio
async def test_r2d_23_vehicle_and_equipment_same_text_id_request_and_body_is_reused() -> None:
    """A VEHICLE row whose asset id text equals the equipment id, recorded
    under the same request id with the same body, is never a replay."""
    repo = MockRepository()
    rid = _rid()
    body = assign_body(repo)
    vehicle_row = syn_assignment("ABH-" + "9" * 32, RAYONG, T1, 1, first=True, asset=EQP)
    vehicle_row.update(asset_type="VEHICLE", request_id=rid,
                       request_fingerprint=request_fingerprint(OP_TRANSFER, EQP, None, body))
    repo._asset_branch_history.append(vehicle_row)
    response = await post(p_assign(), body, repo, request_id=rid)
    assert (response.status_code, _err(response)["code"]) == (409, "REQUEST_ID_REUSED")
    assert repo.registry_write_log == []
    # ...and over real requests: a vehicle transfer, then an equipment assignment.
    repo2 = MockRepository()
    rid2 = _rid()
    from tests.test_branch_write_batch7o2c import transfer_body

    assert (await post(f"{API}/vehicles/VEH-1046/branch-transfers", transfer_body(repo2), repo2,
                       request_id=rid2)).status_code == 200
    equipment = await post(p_assign(), assign_body(repo2), repo2, request_id=rid2)
    assert (equipment.status_code, _err(equipment)["code"]) == (409, "REQUEST_ID_REUSED")


# ===========================================================================
# R2D-24..R2D-27 — generated row, baseline, no source register, no projection
# ===========================================================================


@pytest.mark.asyncio
async def test_r2d_24_25_generated_rows_are_equipment_and_baseline_none() -> None:
    repo = MockRepository()
    await assigned(repo, (RAYONG, "2026-09-01"), (LAEM, "2026-09-10"))
    rows = _rows(repo)
    assert {r["asset_type"] for r in rows} == {"EQUIPMENT"} and {r["asset_id"] for r in rows} == {EQP}
    assert [r["baseline_source"] for r in rows] == ["NONE", ""]
    assert all(r["baseline_source"] != "IMPORTED_MASTER" and r["baseline_branch_id"] == "" for r in rows)
    assert all(r["record_kind"] != "PROJECTION_RECONCILIATION" for r in repo._asset_branch_history
               if r["asset_type"] == "EQUIPMENT")


@pytest.mark.asyncio
async def test_r2d_26_27_no_source_register_and_no_projection() -> None:
    """R2d's own isolation: its modules never reference source_equipment_register,
    a projection writer or a Part module, and its operations make only the
    equipment / history / branch reads and the one W1 append."""
    for module in ("app/domain/equipment_branch_write_service.py", "app/api/v1/equipment_branch_write_routes.py",
                   "app/api/v1/equipment_branch_write_schemas.py"):
        source = (REPO_ROOT / "backend" / module).read_text()
        assert "source_equipment_register" not in source.split('"""', 2)[-1], module
        assert "write_vehicle_branch_cell" not in source and "change_equipment_status" not in source
        assert not re.search(r"^\s*(from|import) app\.(domain|api\.v1)\.part", source, re.MULTILINE), module
    repo = SpyRepository()
    await assigned(repo, (RAYONG, "2026-09-01"))
    first = _rows(repo)[0]["assignment_id"]
    await post(p_correct(first), correction_body(repo), repo)
    await post(p_cancel(first), cancellation_body(repo), repo)
    assert set(repo.calls) <= READS_OK
    assert repo.registry_write_log == ["W1", "W1", "W1"]


# ===========================================================================
# R2D-28..R2D-32 — write failures, server-set cells, data contexts
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(("fault", "outcome", "applied"), [
    ("rejected", "rejected", False), ("unknown_not_applied", "unknown", False), ("unknown_applied", "unknown", True)])
async def test_r2d_28_29_append_failures_are_coded_and_never_retried(fault, outcome, applied) -> None:
    repo = MockRepository()
    repo.registry_write_faults["W1"] = fault
    rid = _rid()
    response = await post(p_assign(), assign_body(repo), repo, request_id=rid)
    assert (response.status_code, _err(response)["code"]) == (503, "BRANCH_HISTORY_WRITE_FAILED")
    assert _err(response)["details"] == {"history_write_outcome": outcome, "request_id": rid}
    assert "projection_write" not in response.text
    assert repo.registry_write_log == ["W1"]  # exactly one attempt: no retry, no second append
    assert len(_rows(repo)) == (1 if applied else 0)


@pytest.mark.asyncio
async def test_r2d_30_actor_request_and_timestamps_are_server_set() -> None:
    repo = SpyRepository()
    for forged in ({"recorded_by": "someone-else"}, {"recorded_at": "2020-01-01T00:00:00+00:00"},
                   {"is_test_data": "FALSE"}, {"test_batch_id": "X"}, {"request_fingerprint": "0" * 64},
                   {"expected_master_branch_id": None}):
        response = await post(p_assign(), {**assign_body(repo), **forged}, repo)
        assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR"), forged
    assert repo.calls == []
    repo = MockRepository()
    rid = _rid()
    body = assign_body(repo)
    before = datetime.now(timezone.utc)
    await post(p_assign(), body, repo, request_id=rid)
    (row,) = _rows(repo)
    from app.context import DEV_USER_ID

    assert row["recorded_by"] == DEV_USER_ID and row["request_id"] == rid
    assert row["request_fingerprint"] == request_fingerprint(OP_EQUIPMENT_ASSIGNMENT, EQP, None, body)
    recorded = datetime.fromisoformat(row["recorded_at"])
    assert before <= recorded <= datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_r2d_31_test_context_marks_rows_with_the_batch() -> None:
    repo = MockRepository()
    await assigned(repo, (RAYONG, "2026-09-01"))
    (row,) = _rows(repo)
    assert (row["is_test_data"], row["test_batch_id"]) == ("TRUE", MOCK_TEST_BATCH_ID)


# R2D-31 (TEST without batch) and R2D-32 (REAL) need Sheets settings: see the fake-Sheets file.


# ===========================================================================
# R2D-33..R2D-37 — reads after mutation and regression
# ===========================================================================


@pytest.mark.asyncio
async def test_r2d_33_read_after_mutation_stays_r2b_compatible() -> None:
    repo = MockRepository()
    assert (await read(repo))["consistency"] == "NO_HISTORY"
    await assigned(repo, (RAYONG, "2026-09-01"))
    body = await read(repo)
    assert body["master"] == {"state": "NOT_IN_SCHEMA", "value": None}
    assert body["consistency"] == "UNDETERMINED"
    assert body["current"] == {"branch_id": RAYONG, "source": "EVENT"}
    assert body["baseline"] == {"branch_id": None, "source": "NONE"}
    assert body["history_revision"] == _tl(repo).revision


@pytest.mark.asyncio
async def test_r2d_34_all_cancelled_with_baseline_none_keeps_the_accepted_r2b_read() -> None:
    """Accepted R2b behaviour, unchanged: the recorded baseline NONE states
    that no authoritative branch is currently in force from the recorded
    history — not that the equipment is proven to belong to no branch."""
    repo = MockRepository()
    (event,) = await assigned(repo, (RAYONG, "2026-09-01"))
    await post(p_cancel(event), cancellation_body(repo), repo)
    body = await read(repo)
    assert body["current"] == {"branch_id": None, "source": "NONE"}
    assert body["consistency"] == "UNDETERMINED" and body["events"][0]["in_force"] is False


@pytest.mark.asyncio
async def test_r2d_35_vehicle_branch_write_is_unchanged() -> None:
    from tests.test_branch_write_batch7o2c import _rows as vehicle_rows
    from tests.test_branch_write_batch7o2c import transfer_body

    repo = MockRepository()
    response = await post(f"{API}/vehicles/VEH-1046/branch-transfers", transfer_body(repo), repo)
    assert response.status_code == 200
    assert set(response.json()) == {"request_id", "changed", "record_id", "event_id", "projection_write",
                                    "timeline_status_after", "current_branch_id", "consistency"}
    assert vehicle_rows(repo, "VEH-1046")[-1]["asset_type"] == "VEHICLE"
    assert repo.registry_write_log == ["W1", "W2"]


@pytest.mark.asyncio
async def test_r2d_36_37_other_reads_are_unchanged() -> None:
    repo = MockRepository()
    await assigned(repo, (RAYONG, "2026-09-01"))
    vehicle = await _http("GET", f"{API}/vehicles/VEH-1046/branch-history", repo=repo, request_id=None)
    assert vehicle.status_code == 200 and all(r["record_id"] not in str(_rows(repo)) for r in vehicle.json()["records"])
    for path in ("personnel", "departments"):
        assert (await _http("GET", f"{API}/{path}", repo=repo, request_id=None)).status_code == 200


# ===========================================================================
# R2D-38 / R2D-39 — capability and required-route checks
# ===========================================================================


def test_r2d_38_capability_inventory() -> None:
    assert authz.CAN_TRANSFER_EQUIPMENT_BRANCH == EQUIPMENT_CAP
    assert EQUIPMENT_CAP in authz.ALL_CAPABILITIES and EQUIPMENT_CAP in authz.ROLE_CAPABILITIES["ADMIN"]
    assert EQUIPMENT_CAP in authz.ROLE_CAPABILITIES["MAINTENANCE_MANAGER"]
    for role in OTHER_ROLES:
        assert EQUIPMENT_CAP not in authz.ROLE_CAPABILITIES[role], role
    assert authz.CAN_CORRECT_BRANCH_HISTORY == CORRECT_CAP  # value unchanged; scope now vehicle + equipment
    assert authz.CAN_TRANSFER_VEHICLE_BRANCH == VEHICLE_CAP


def test_r2d_39_route_inventory_and_strict_bodies() -> None:
    from app.main import create_app

    """The current R2b + R2d routes are present with their exact methods, and
    the four R2d bodies stay strict. Forward-compatible: a later approved
    equipment branch route (e.g. a projection) is not rejected here."""
    spec = create_app().openapi()["paths"]
    base = f"{API}/equipment/{{equipment_id}}"
    required_routes = {
        f"{base}/branch-history": {"get"},  # R2b
        f"{base}/branch-assignments": {"post"},
        f"{base}/branch-history/insertions": {"post"},
        f"{base}/branch-history/events/{{event_id}}/corrections": {"post"},
        f"{base}/branch-history/events/{{event_id}}/cancellations": {"post"},
    }
    assert required_routes.keys() <= spec.keys()
    for path, methods in required_routes.items():
        assert set(spec[path]) == methods, path
    required_fields = {
        f"{base}/branch-assignments": {"to_branch_id", "effective", "expected_current_branch_id",
                                       "expected_history_revision"},
        f"{base}/branch-history/insertions": {"to_branch_id", "effective", "expected_history_revision"},
        f"{base}/branch-history/events/{{event_id}}/corrections": {"to_branch_id", "effective",
                                                                    "expected_history_revision"},
        f"{base}/branch-history/events/{{event_id}}/cancellations": {"expected_history_revision"},
    }
    for path, fields in required_fields.items():
        schema = spec[path]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert schema["additionalProperties"] is False and set(schema["required"]) == fields, path
        assert "expected_master_branch_id" not in schema["properties"], path
