"""Phase 7 Batch 7O2c — responsible-branch writes over HTTP with the MOCK
repository (contract Final Rev2 §3, §5, §6, §8.1; Outcome Classification
Addendum A.1, A.4, B-OC-01..04; review clarifications C-c1..C-c7).

Acceptance rows: B-01..B-13, B-17..B-21 (server side), B-OC-01..04, C-c1,
C-c2, C-c4..C-c7, the allowlist cross-check (shared with 7O2b) and the request
order. Fake-transport rows (B-10 interleaving, B-12 over Sheets, B-16 parity,
header reorder, request counts) are in test_branch_write_sheets_batch7o2c.py;
B-14/B-15 are frontend tests. Synthetic data only.
"""
from __future__ import annotations

import ast
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import DataRepositoryMode, Settings
from app.domain.branch_timeline import (
    ASSET_BRANCH_HISTORY_COLUMNS,
    derive_timeline,
    validate_branch_row,
    vehicle_history_rows,
)
from app.domain.branch_write_service import BranchWriteService
from app.domain.effective_time import EffectiveTimeError, resolve_effective
from app.domain.registry_outcomes import NEVER_ALLOWLISTED_CODES, SPECIAL_OUTCOMES, ZERO_WRITE_ALLOWLIST
from app.domain.request_replay import request_fingerprint
from app.errors import ApiError
from app.repositories.base import (
    RegistrationMasterRead,
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
    RepositorySchemaError,
    RepositoryTabReadError,
)
from app.repositories.mock import MockRepository
from tests.test_registration_write_batch7o2b import _AUTO, _http
from tests.test_registry_read_api_batch7o2a import SpyRepository

API = "/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
ROLES_WITHOUT = ("MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER")
BRANCH_CAPS = ("can_transfer_vehicle_branch", "can_correct_branch_history")

# Mock seed (synthetic): VEH-1046 = transfer to Laem Chabang at 2026-08-31T17Z
# (baseline Rayong), an inserted Bangna event corrected to 2026-08-19T17Z;
# VEH-1048 = one assignment, cancelled (baseline NONE); VEH-1047 = no history.
E_LATEST = "ABH-" + "a" * 31 + "1"
E_INSERTED = "ABH-" + "a" * 31 + "2"
H_INSERTED = "ABH-" + "a" * 31 + "3"  # its head (revision 2)
E_CANCELLED = "ABH-" + "b" * 31 + "1"
LAEM, BANGNA, RAYONG = "BR-LAEM-CHABANG", "BR-BANGNA-KM6", "BR-RAYONG"


def _rid() -> str:
    return str(uuid.uuid4())


def _sheets_settings(context: str | None, batch: str = "") -> Settings:
    values: dict = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake",
                    "google_application_credentials": "fake.json", "registry_test_batch_id": batch}
    if context is not None:
        values["registry_data_context"] = context
    return Settings(**values)


def _err(response) -> dict:
    return response.json()["error"]


def _rows(repo: MockRepository, vid: str) -> list[dict[str, str]]:
    return [r for r in repo._asset_branch_history if r["asset_id"] == vid]


def _timeline(repo: MockRepository, vid: str):
    master = repo._vehicle_registry.get(vid, {}).get("responsible_branch_id") or None
    return derive_timeline(_rows(repo, vid), master_branch_id=master, master_available=True, context="TEST")


def _rev(repo: MockRepository, vid: str) -> str:
    return _timeline(repo, vid).revision


def _master(repo: MockRepository, vid: str) -> str:
    return repo._vehicle_registry.get(vid, {}).get("responsible_branch_id", "")


def _set_master(repo: MockRepository, vid: str, branch: str) -> None:
    repo._vehicle_registry.setdefault(vid, {})["responsible_branch_id"] = branch


def _current(repo: MockRepository, vid: str) -> str | None:
    return _timeline(repo, vid).current_branch_id


def _date(d: str) -> dict:
    return {"mode": "DATE", "date": d}


def _at(at: str) -> dict:
    return {"mode": "DATETIME", "at": at}


# ---- request builders (the expected values are read from the repo NOW) ----

def transfer_body(repo, vid="VEH-1046", to=RAYONG, effective=None, **extra) -> dict:
    body = {"to_branch_id": to, "effective": effective or _date("2026-09-15"),
            "expected_current_branch_id": _current(repo, vid), "expected_history_revision": _rev(repo, vid)}
    body.update(extra)
    return body


def insertion_body(repo, vid="VEH-1046", to=RAYONG, effective=None, **extra) -> dict:
    body = {"to_branch_id": to, "effective": effective or _date("2026-08-25"), "reason_th": "บันทึกย้อนหลัง (ทดสอบ)",
            "expected_history_revision": _rev(repo, vid)}
    body.update(extra)
    return body


def correction_body(repo, vid="VEH-1046", to=BANGNA, effective=None, **extra) -> dict:
    body = {"to_branch_id": to, "effective": effective or _date("2026-08-22"), "reason_th": "แก้วันที่ (ทดสอบ)",
            "expected_history_revision": _rev(repo, vid), "expected_master_branch_id": _master(repo, vid) or None}
    body.update(extra)
    return body


def cancellation_body(repo, vid="VEH-1046", **extra) -> dict:
    body = {"reason_th": "บันทึกผิด (ทดสอบ)", "expected_history_revision": _rev(repo, vid),
            "expected_master_branch_id": _master(repo, vid) or None}
    body.update(extra)
    return body


def reconcile_body(repo, vid="VEH-1046", **extra) -> dict:
    body = {"reason_th": "ปรับให้ตรง (ทดสอบ)", "expected_history_revision": _rev(repo, vid),
            "expected_master_branch_id": _master(repo, vid) or None}
    body.update(extra)
    return body


def p_transfer(vid="VEH-1046"):
    return f"{API}/vehicles/{vid}/branch-transfers"


def p_insertion(vid="VEH-1046"):
    return f"{API}/vehicles/{vid}/branch-history/insertions"


def p_correction(vid="VEH-1046", event=E_INSERTED):
    return f"{API}/vehicles/{vid}/branch-history/events/{event}/corrections"


def p_cancellation(vid="VEH-1046", event=E_LATEST):
    return f"{API}/vehicles/{vid}/branch-history/events/{event}/cancellations"


def p_reconcile(vid="VEH-1046"):
    return f"{API}/vehicles/{vid}/branch-projection/reconciliations"


async def post(path: str, body, repo, **kw):
    return await _http("POST", path, repo=repo, json_body=body, **kw)


async def branch_history(repo, vid="VEH-1046") -> dict:
    response = await _http("GET", f"{API}/vehicles/{vid}/branch-history", repo=repo, request_id=None)
    assert response.status_code == 200, response.text
    return response.json()


# ---- synthetic histories for tie cases (VEH-1047; strict-valid rows) ----

def _fp(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def assignment(eid: str, branch: str, start: str, n: int, *, first_baseline: tuple[str, str] | None = None,
               source: tuple[str, str] = ("", "NONE"), vid: str = "VEH-1047") -> dict[str, str]:
    row = dict.fromkeys(ASSET_BRANCH_HISTORY_COLUMNS, "")
    row.update(assignment_id=eid, asset_type="VEHICLE", asset_id=vid, record_kind="ASSIGNMENT",
               entry_operation="TRANSFER", event_id=eid, revision_no="1", branch_id=branch, start_at=start,
               effective_precision="DATETIME", effective_source="CLIENT", recorded_from_branch_id=source[0],
               recorded_from_source=source[1], recorded_at=f"2026-09-0{n}T03:00:00+00:00",
               recorded_by="synthetic", request_id=f"syn-{eid}", request_fingerprint=_fp(eid),
               is_test_data="TRUE", test_batch_id="SYN")
    if first_baseline is not None:
        row["baseline_branch_id"], row["baseline_source"] = first_baseline
    return row


T0, T1, T2 = "2026-08-01T00:00:00+00:00", "2026-08-10T00:00:00+00:00", "2026-08-20T00:00:00+00:00"
EA, EB, EC = ("ABH-" + c * 32 for c in "def")


def tie_repo(events: list[tuple[str, str, str]], master: str = BANGNA) -> MockRepository:
    """VEH-1047 with the given (event_id, branch, start) ASSIGNMENT rows in
    recorded order; the first row carries baseline BR-BANGNA-KM6."""
    repo = MockRepository()
    repo._asset_branch_history = [r for r in repo._asset_branch_history if r["asset_id"] != "VEH-1047"]
    for n, (eid, branch, start) in enumerate(events, start=1):
        repo._asset_branch_history.append(
            assignment(eid, branch, start, n, first_baseline=(BANGNA, "IMPORTED_MASTER") if n == 1 else None)
        )
    _set_master(repo, "VEH-1047", master)
    assert _timeline(repo, "VEH-1047").status != "INVALID", _timeline(repo, "VEH-1047").issue_counts
    return repo


def tie_seed_1046(repo: MockRepository) -> None:
    """VEH-1046: move the inserted event's head onto the latest event's instant -> AMBIGUOUS_ORDER."""
    next(r for r in repo._asset_branch_history if r["assignment_id"] == H_INSERTED)["start_at"] = "2026-08-31T17:00:00+00:00"


# ===========================================================================
# Permissions (B-07, §3.1)
# ===========================================================================


def test_branch_capabilities_and_roles() -> None:
    from app.domain.authz import ALL_CAPABILITIES, ROLE_CAPABILITIES

    for cap in BRANCH_CAPS:
        assert cap in ALL_CAPABILITIES
        assert cap in ROLE_CAPABILITIES["ADMIN"]
        for role in ROLES_WITHOUT:
            assert cap not in ROLE_CAPABILITIES[role], (cap, role)
    assert ROLE_CAPABILITIES["MAINTENANCE_MANAGER"] == frozenset(
        {"can_view", "can_edit_vehicle_registration", *BRANCH_CAPS,
         "can_transfer_equipment_branch",  # R2d (owner-approved, provisional)
         "can_manage_personnel", "can_manage_department",  # R2e (owner-approved, provisional)
         "can_link_personnel_technician"}  # R2f-b (owner-approved, provisional)
    )


ENDPOINTS = {
    "transfer": (lambda: p_transfer(), lambda r: transfer_body(r)),
    "insertion": (lambda: p_insertion(), lambda r: insertion_body(r)),
    "correction": (lambda: p_correction(), lambda r: correction_body(r)),
    "cancellation": (lambda: p_cancellation(), lambda r: cancellation_body(r)),
    "reconcile": (lambda: p_reconcile(), lambda r: reconcile_body(r)),
}
CAPABILITY_OF = {"transfer": "can_transfer_vehicle_branch", "reconcile": "can_transfer_vehicle_branch",
                 "insertion": "can_correct_branch_history", "correction": "can_correct_branch_history",
                 "cancellation": "can_correct_branch_history"}


@pytest.mark.asyncio
@pytest.mark.parametrize("op", sorted(ENDPOINTS))
@pytest.mark.parametrize("role", [*ROLES_WITHOUT, "NO_AUTH"])
@pytest.mark.parametrize("content", [None, b"{not json", b'{"x": 1}'], ids=["valid", "malformed", "schema-invalid"])
async def test_refused_with_403_and_zero_repository_calls(op, role, content, monkeypatch) -> None:
    repo = SpyRepository()
    path, body = ENDPOINTS[op]
    response = await _http("POST", path(), repo=repo, role=None if role == "NO_AUTH" else role,
                           no_auth=role == "NO_AUTH", monkeypatch=monkeypatch,
                           json_body=body(MockRepository()) if content is None else _AUTO, content=content)
    assert (response.status_code, _err(response)["code"]) == (403, "HTTP_ERROR")
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("op", sorted(ENDPOINTS))
async def test_b07_transfer_and_correction_capabilities_are_separate(op, monkeypatch) -> None:
    from app.domain import authz

    monkeypatch.setitem(authz.ROLE_CAPABILITIES, "TRANSFER_ONLY", frozenset({"can_view", "can_transfer_vehicle_branch"}))
    monkeypatch.setitem(authz.ROLE_CAPABILITIES, "CORRECT_ONLY", frozenset({"can_view", "can_correct_branch_history"}))
    path, body = ENDPOINTS[op]
    other = "CORRECT_ONLY" if CAPABILITY_OF[op] == "can_transfer_vehicle_branch" else "TRANSFER_ONLY"
    repo = SpyRepository()
    refused = await post(path(), body(MockRepository()), repo, role=other)
    assert (refused.status_code, _err(refused)["code"]) == (403, "HTTP_ERROR")
    assert repo.calls == []
    holder = "TRANSFER_ONLY" if other == "CORRECT_ONLY" else "CORRECT_ONLY"
    allowed = await post(path(), body(MockRepository()), MockRepository(), role=holder)
    assert allowed.status_code != 403


@pytest.mark.asyncio
@pytest.mark.parametrize("op", sorted(ENDPOINTS))
async def test_order_capability_then_request_id_then_body(op) -> None:
    path, _ = ENDPOINTS[op]
    repo = SpyRepository()
    no_cap = await _http("POST", path(), repo=repo, role="DRIVER", request_id=None, content=b"{bad")
    no_id = await _http("POST", path(), repo=repo, role="MAINTENANCE_MANAGER", request_id="nope", content=b"{bad")
    bad = await _http("POST", path(), repo=repo, role="MAINTENANCE_MANAGER", content=b"{bad")
    extra = await _http("POST", path(), repo=repo, role="MAINTENANCE_MANAGER",
                        json_body={**ENDPOINTS[op][1](MockRepository()), "unexpected": 1})
    assert [(r.status_code, _err(r)["code"]) for r in (no_cap, no_id, bad, extra)] == [
        (403, "HTTP_ERROR"), (422, "REQUEST_ID_REQUIRED"), (422, "VALIDATION_ERROR"), (422, "VALIDATION_ERROR")]
    for r in (bad, extra):
        assert '"input"' not in json.dumps(_err(r)["details"])
    assert repo.calls == []


# ===========================================================================
# B-01 first transfer / baseline (§5.3)
# ===========================================================================


@pytest.mark.asyncio
async def test_b01_first_transfer_captures_the_imported_baseline() -> None:
    repo = MockRepository()  # VEH-1047: master BR-BANGNA-KM6, no history
    response = await post(p_transfer("VEH-1047"), transfer_body(repo, "VEH-1047", effective=_date("2026-09-20")), repo)
    assert response.status_code == 200, response.text
    out = response.json()
    assert (out["projection_write"], out["current_branch_id"], out["consistency"]) == ("WRITTEN", RAYONG, "CONSISTENT")
    row = _rows(repo, "VEH-1047")[-1]
    assert (row["baseline_branch_id"], row["baseline_source"]) == (BANGNA, "IMPORTED_MASTER")
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == (BANGNA, "BASELINE")
    assert (row["record_kind"], row["entry_operation"], row["revision_no"], row["event_id"]) == (
        "ASSIGNMENT", "TRANSFER", "1", row["assignment_id"])
    assert row["start_at"] == "2026-09-19T17:00:00+00:00"  # Bangkok midnight, stored UTC
    assert (row["effective_precision"], row["effective_source"]) == ("DATE", "CLIENT")
    assert row["assignment_id"].startswith("ABH-") and len(row["assignment_id"]) == 36
    assert _master(repo, "VEH-1047") == RAYONG
    assert repo.registry_write_log == ["W1", "W2"]
    assert validate_branch_row(row) == []


@pytest.mark.asyncio
async def test_b01_first_transfer_from_a_blank_master_records_none() -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1047", "")
    response = await post(p_transfer("VEH-1047"), transfer_body(repo, "VEH-1047", effective=_date("2026-09-20")), repo)
    assert response.status_code == 200, response.text
    row = _rows(repo, "VEH-1047")[-1]
    assert (row["baseline_branch_id"], row["baseline_source"]) == ("", "NONE")
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == ("", "NONE")
    assert _master(repo, "VEH-1047") == RAYONG
    second = await post(p_transfer("VEH-1047"), transfer_body(repo, "VEH-1047", to=LAEM, effective=_date("2026-09-25")), repo)
    assert second.status_code == 200
    later = _rows(repo, "VEH-1047")[-1]
    assert (later["baseline_branch_id"], later["baseline_source"]) == ("", "")  # first record only
    assert (later["recorded_from_branch_id"], later["recorded_from_source"]) == (RAYONG, "EVENT")


# ===========================================================================
# B-02 transfer (§6.2)
# ===========================================================================


@pytest.mark.asyncio
async def test_b02_transfer_after_latest_writes_history_then_master() -> None:
    repo = MockRepository()
    before = [dict(r) for r in repo._asset_branch_history]
    rid = _rid()
    response = await post(p_transfer(), transfer_body(repo, note_th="  หมายเหตุ =1+1 "), repo, request_id=rid)
    assert response.status_code == 200, response.text
    out = response.json()
    assert set(out) == {"request_id", "changed", "record_id", "event_id", "projection_write",
                        "timeline_status_after", "current_branch_id", "consistency"}
    assert out["request_id"] == rid == response.headers["X-Request-Id"]
    assert (out["changed"], out["projection_write"], out["timeline_status_after"]) == (True, "WRITTEN", "VALID")
    assert out["record_id"] == out["event_id"]
    assert repo._asset_branch_history[:-1] == before  # append-only
    row = repo._asset_branch_history[-1]
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == (LAEM, "EVENT")
    assert row["note_th"] == "  หมายเหตุ =1+1 "  # C-c6: exact
    assert row["request_fingerprint"] == request_fingerprint("transfer", "VEH-1046", None, transfer_body(MockRepository(), note_th="  หมายเหตุ =1+1 "))
    assert (row["is_test_data"], row["test_batch_id"], row["recorded_by"]) == ("TRUE", "MOCK-7O2B-SYNTHETIC", "dev-user")
    assert _master(repo, "VEH-1046") == RAYONG
    assert (await branch_history(repo))["consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_b02_transfer_with_now_uses_whole_seconds_server_time() -> None:
    repo = MockRepository()
    response = await post(p_transfer(), transfer_body(repo, effective={"mode": "NOW"}), repo)
    assert response.status_code == 200, response.text
    row = repo._asset_branch_history[-1]
    start = datetime.fromisoformat(row["start_at"])
    assert start.microsecond == 0 and start.utcoffset().total_seconds() == 0
    assert (row["effective_precision"], row["effective_source"]) == ("DATETIME", "SERVER_NOW")


@pytest.mark.asyncio
async def test_b02_transfer_noop_does_not_read_the_branch_master() -> None:
    repo = SpyRepository()
    response = await post(p_transfer(), transfer_body(repo, to=LAEM), repo)
    assert response.json() == {"request_id": response.sent_request_id, "changed": False, "warnings": []}
    assert "read_branch_master_validated" not in repo.calls
    assert repo.registry_write_log == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "effective,code",
    [(_at("2026-08-31T17:00:00Z"), "BRANCH_EVENT_SAME_INSTANT"),
     (_date("2026-09-01"), "BRANCH_EVENT_SAME_INSTANT"),  # DATE == the DATETIME of an event (Bangkok midnight)
     (_at("2026-09-01T00:00:00+07:00"), "BRANCH_EVENT_SAME_INSTANT"),
     (_date("2026-08-25"), "BRANCH_TRANSFER_NOT_LATEST")],
)
async def test_b02_same_instant_and_not_latest(effective, code) -> None:
    repo = MockRepository()
    response = await post(p_transfer(), transfer_body(repo, effective=effective), repo)
    assert (response.status_code, _err(response)["code"]) == (409, code)
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_b02_stale_mismatch_and_ambiguous_with_their_precedence() -> None:
    repo = MockRepository()
    stale_rev = await post(p_transfer(), transfer_body(repo, expected_history_revision="BHR1-0"), repo)
    assert _err(stale_rev)["details"] == {"field": "history_revision"}
    stale_cur = await post(p_transfer(), transfer_body(repo, expected_current_branch_id=BANGNA), repo)
    assert (_err(stale_cur)["code"], _err(stale_cur)["details"]) == ("BRANCH_HISTORY_STALE", {"field": "current_branch_id"})
    null_cur = await post(p_transfer(), transfer_body(repo, expected_current_branch_id=None), repo)
    assert _err(null_cur)["details"] == {"field": "current_branch_id"}  # null compared exactly
    mism = MockRepository()
    _set_master(mism, "VEH-1046", RAYONG)
    mismatch = await post(p_transfer(), transfer_body(mism, expected_current_branch_id=LAEM, to=BANGNA), mism)
    assert (mismatch.status_code, _err(mismatch)["code"]) == (409, "BRANCH_PROJECTION_MISMATCH")
    amb = MockRepository()
    tie_seed_1046(amb)
    ambiguous = await post(p_transfer(), transfer_body(amb, expected_current_branch_id=None), amb)
    assert (ambiguous.status_code, _err(ambiguous)["code"]) == (409, "BRANCH_TIMELINE_AMBIGUOUS")
    # precedence: a stale revision is reported before the ambiguity
    both = await post(p_transfer(), transfer_body(amb, expected_history_revision="BHR1-0"), amb)
    assert _err(both)["code"] == "BRANCH_HISTORY_STALE"
    for r in (repo, mism, amb):
        assert r.registry_write_log == []


@pytest.mark.asyncio
async def test_b02_destination_reference_checks() -> None:
    repo = MockRepository()
    unknown = await post(p_transfer(), transfer_body(repo, to="BR-NOPE"), repo)
    assert (unknown.status_code, _err(unknown)["code"], _err(unknown)["details"]) == (422, "BRANCH_NOT_FOUND", {"branch_id": "BR-NOPE"})
    next(b for b in repo._branch_master if b["branch_id"] == RAYONG)["is_active"] = "FALSE"
    inactive = await post(p_transfer(), transfer_body(repo), repo)
    assert (inactive.status_code, _err(inactive)["code"]) == (422, "BRANCH_INACTIVE")
    for exc, status, code in (
        (RepositoryTabReadError("branch_master", "down"), 503, "BRANCH_MASTER_READ_FAILED"),
        (RepositorySchemaError("branch_master", "TAB_MISSING"), 500, "BRANCH_MASTER_SCHEMA_INVALID"),
    ):
        down = MockRepository()
        down.read_branch_master_validated = _raise(exc)  # type: ignore[method-assign]
        response = await post(p_transfer(), transfer_body(down), down)
        assert (response.status_code, _err(response)["code"]) == (status, code)
        assert down.registry_write_log == []
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_c_c8_branch_master_without_is_active_column_treats_every_branch_as_active() -> None:
    repo = MockRepository()
    repo._branch_master = [{"branch_id": b["branch_id"], "branch_name": b["branch_name"]} for b in repo._branch_master]
    from app.repositories.base import RegistryTableRead

    async def without_column():
        return RegistryTableRead(rows=[dict(b) for b in repo._branch_master], columns=frozenset({"branch_id", "branch_name"}))

    repo.read_branch_master_validated = without_column  # type: ignore[method-assign]
    response = await post(p_transfer(), transfer_body(repo), repo)
    assert response.status_code == 200, response.text


def _raise(exc):
    async def method(*args, **kwargs):
        raise exc

    return method


# ===========================================================================
# B-03 insertion (§6.3)
# ===========================================================================


@pytest.mark.asyncio
async def test_b03_insertion_between_events_records_the_derived_source_and_writes_no_master() -> None:
    repo = MockRepository()
    before = [dict(r) for r in repo._asset_branch_history]
    prior = next(e for e in (await branch_history(repo))["events"] if e["event_id"] == E_LATEST)
    assert prior["derived_from_branch_id"] == BANGNA and "RECORDED_SOURCE_DIFFERS" in prior["notes"]
    response = await post(p_insertion(), insertion_body(repo), repo)
    assert response.status_code == 200, response.text
    assert response.json()["projection_write"] == "NOT_NEEDED"
    assert repo.registry_write_log == ["W1"]
    assert repo._asset_branch_history[:-1] == before  # later events never rewritten
    row = repo._asset_branch_history[-1]
    assert (row["entry_operation"], row["note_th"]) == ("INSERTION", "บันทึกย้อนหลัง (ทดสอบ)")
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == (BANGNA, "EVENT")
    assert (row["baseline_branch_id"], row["baseline_source"]) == ("", "")  # never a second baseline
    assert _master(repo, "VEH-1046") == LAEM
    history = await branch_history(repo)
    assert history["consistency"] == "CONSISTENT" and history["timeline_status"] == "VALID"
    latest = next(e for e in history["events"] if e["event_id"] == E_LATEST)
    # the later event was recorded from Rayong; the insertion makes the derived source agree (row untouched)
    assert latest["derived_from_branch_id"] == RAYONG and "RECORDED_SOURCE_DIFFERS" not in latest["notes"]


@pytest.mark.asyncio
async def test_b03_insertion_before_the_first_event_uses_the_baseline() -> None:
    repo = MockRepository()
    response = await post(p_insertion(), insertion_body(repo, to=LAEM, effective=_date("2026-08-01")), repo)
    assert response.status_code == 200, response.text
    row = repo._asset_branch_history[-1]
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == (RAYONG, "BASELINE")


@pytest.mark.asyncio
async def test_b03_insertion_noop_refusals_and_now() -> None:
    repo = SpyRepository()
    noop = await post(p_insertion(), insertion_body(repo, to=BANGNA), repo)  # already Bangna from 08-19
    assert noop.json()["changed"] is False
    assert "read_branch_master_validated" not in repo.calls
    later = await post(p_insertion(), insertion_body(repo, effective=_date("2026-09-15")), repo)
    assert (later.status_code, _err(later)["code"]) == (409, "BRANCH_INSERTION_NOT_HISTORICAL")
    empty = await post(p_insertion("VEH-1047"), insertion_body(repo, "VEH-1047", effective=_date("2026-09-01")), repo)
    assert _err(empty)["code"] == "BRANCH_INSERTION_NOT_HISTORICAL"  # NO_HISTORY: use a transfer
    same = await post(p_insertion(), insertion_body(repo, effective=_at("2026-08-19T17:00:00Z")), repo)
    assert _err(same)["code"] == "BRANCH_EVENT_SAME_INSTANT"
    now = await post(p_insertion(), insertion_body(repo, effective={"mode": "NOW"}), repo)
    assert (now.status_code, _err(now)["code"]) == (422, "EFFECTIVE_MODE_NOT_ALLOWED")
    amb = MockRepository()
    tie_seed_1046(amb)
    ambiguous = await post(p_insertion(), insertion_body(amb), amb)
    assert _err(ambiguous)["code"] == "BRANCH_TIMELINE_AMBIGUOUS"
    mism = MockRepository()
    _set_master(mism, "VEH-1046", RAYONG)
    assert _err(await post(p_insertion(), insertion_body(mism), mism))["code"] == "BRANCH_PROJECTION_MISMATCH"
    assert repo.registry_write_log == [] and amb.registry_write_log == [] and mism.registry_write_log == []


# ===========================================================================
# B-04 / B-06 / B-20 correction (§6.4)
# ===========================================================================


@pytest.mark.asyncio
async def test_b04_correction_appends_a_revision_and_retains_every_row() -> None:
    repo = MockRepository()
    before = [dict(r) for r in repo._asset_branch_history]
    old_rev = _rev(repo, "VEH-1046")
    response = await post(p_correction(), correction_body(repo), repo)
    assert response.status_code == 200, response.text
    assert response.json()["projection_write"] == "NOT_NEEDED"  # current still Laem
    assert repo._asset_branch_history[:-1] == before
    row = repo._asset_branch_history[-1]
    assert (row["record_kind"], row["event_id"], row["revision_no"], row["supersedes_record_id"]) == (
        "CORRECTION", E_INSERTED, "3", H_INSERTED)
    assert row["start_at"] == "2026-08-21T17:00:00+00:00"
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == (RAYONG, "BASELINE")
    # B-06: an older-event edit changes the revision although current and latest id are unchanged
    assert _rev(repo, "VEH-1046") != old_rev and _current(repo, "VEH-1046") == LAEM
    stale = await post(p_transfer(), transfer_body(repo, expected_history_revision=old_rev), repo)
    assert _err(stale)["details"] == {"field": "history_revision"}
    # revision chain: correct again (destination) -> revision 4 supersedes 3
    again = await post(p_correction(), correction_body(repo, to=RAYONG, effective=_date("2026-08-22")), repo)
    assert again.status_code == 200
    chain = [r for r in _rows(repo, "VEH-1046") if r["event_id"] == E_INSERTED]
    assert [r["revision_no"] for r in chain] == ["1", "2", "3", "4"]
    assert chain[-1]["supersedes_record_id"] == chain[-2]["assignment_id"]


@pytest.mark.asyncio
async def test_b04_correcting_the_latest_destination_projects_the_master() -> None:
    repo = MockRepository()
    response = await post(p_correction(event=E_LATEST), correction_body(repo, to=RAYONG, effective=_date("2026-09-01")), repo)
    assert response.status_code == 200, response.text
    assert response.json()["projection_write"] == "WRITTEN"
    assert _master(repo, "VEH-1046") == RAYONG
    assert repo.registry_write_log == ["W1", "W2"]


@pytest.mark.asyncio
async def test_b04_correction_noop_not_found_cancelled_same_instant() -> None:
    repo = SpyRepository()
    noop = await post(p_correction(), correction_body(repo, effective=_date("2026-08-20")), repo)  # head: 08-19T17Z, Bangna
    assert noop.json()["changed"] is False and "read_branch_master_validated" not in repo.calls
    missing = await post(p_correction(event="ABH-nope"), correction_body(repo), repo)
    assert (missing.status_code, _err(missing)["code"]) == (404, "BRANCH_EVENT_NOT_FOUND")
    cancelled = await post(p_correction("VEH-1048", E_CANCELLED), correction_body(repo, "VEH-1048"), repo)
    assert (cancelled.status_code, _err(cancelled)["code"]) == (409, "BRANCH_EVENT_CANCELLED")
    other_vehicle = await post(p_correction("VEH-1048", E_INSERTED), correction_body(repo, "VEH-1048"), repo)
    assert _err(other_vehicle)["code"] == "BRANCH_EVENT_NOT_FOUND"
    same = await post(p_correction(), correction_body(repo, effective=_at("2026-08-31T17:00:00Z")), repo)
    assert _err(same)["code"] == "BRANCH_EVENT_SAME_INSTANT"
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_b20_entry_time_sources_are_kept_for_original_and_head() -> None:
    repo = MockRepository()
    await post(p_correction(event=E_LATEST), correction_body(repo, to=LAEM, effective=_date("2026-08-15")), repo)
    history = await branch_history(repo)
    event = next(e for e in history["events"] if e["event_id"] == E_LATEST)
    assert (event["original_entry_from_branch_id"], event["original_entry_from_source"]) == (RAYONG, "BASELINE")
    assert (event["head_entry_from_branch_id"], event["head_entry_from_source"]) == (RAYONG, "BASELINE")
    head = repo._asset_branch_history[-1]
    assert (head["recorded_from_branch_id"], head["recorded_from_source"]) == (RAYONG, "BASELINE")


# ===========================================================================
# B-05 cancellation (§6.5)
# ===========================================================================


@pytest.mark.asyncio
async def test_b05_cancel_latest_first_and_all() -> None:
    repo = MockRepository()
    latest = await post(p_cancellation(), cancellation_body(repo), repo)
    assert latest.status_code == 200, latest.text
    assert latest.json()["projection_write"] == "WRITTEN" and _master(repo, "VEH-1046") == BANGNA
    row = repo._asset_branch_history[-1]
    assert (row["record_kind"], row["revision_no"], row["supersedes_record_id"]) == ("CANCELLATION", "2", E_LATEST)
    assert all(row[f] == "" for f in ("branch_id", "start_at", "recorded_from_source", "baseline_source"))
    everything = await post(p_cancellation(event=E_INSERTED), cancellation_body(repo), repo)
    assert everything.json()["projection_write"] == "WRITTEN"
    assert _master(repo, "VEH-1046") == RAYONG  # the BASELINE, never the mutated master
    assert (await branch_history(repo))["current"] == {"branch_id": RAYONG, "source": "BASELINE"}
    first = MockRepository()
    response = await post(p_cancellation(event=E_INSERTED), cancellation_body(first), first)
    assert response.json()["projection_write"] == "NOT_NEEDED" and _master(first, "VEH-1046") == LAEM


@pytest.mark.asyncio
async def test_b05_baseline_none_clears_the_master_and_nothing_is_guessed() -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1047", "")
    await post(p_transfer("VEH-1047"), transfer_body(repo, "VEH-1047", to=BANGNA, effective=_date("2026-09-20")), repo)
    event = _rows(repo, "VEH-1047")[-1]["assignment_id"]
    response = await post(p_cancellation("VEH-1047", event), cancellation_body(repo, "VEH-1047"), repo)
    assert response.status_code == 200, response.text
    assert response.json()["projection_write"] == "WRITTEN"
    assert _master(repo, "VEH-1047") == ""
    assert (await branch_history(repo, "VEH-1047"))["current"] == {"branch_id": None, "source": "NONE"}


@pytest.mark.asyncio
async def test_b05_cancellation_refusals() -> None:
    repo = MockRepository()
    again = await post(p_cancellation("VEH-1048", E_CANCELLED), cancellation_body(repo, "VEH-1048"), repo)
    assert (again.status_code, _err(again)["code"]) == (409, "BRANCH_EVENT_CANCELLED")
    missing = await post(p_cancellation(event="ABH-x"), cancellation_body(repo), repo)
    assert _err(missing)["code"] == "BRANCH_EVENT_NOT_FOUND"
    mism = MockRepository()
    _set_master(mism, "VEH-1046", RAYONG)
    assert _err(await post(p_cancellation(), cancellation_body(mism), mism))["code"] == "BRANCH_PROJECTION_MISMATCH"
    assert repo.registry_write_log == [] and mism.registry_write_log == []


# ===========================================================================
# B-17 expected master (every state) and replay precedence
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["correction", "cancellation"])
@pytest.mark.parametrize("state", ["VALID", "AMBIGUOUS", "NOOP"])
@pytest.mark.parametrize("expected", ["wrong", "null"])
async def test_b17_expected_master_is_checked_in_every_state(op, state, expected) -> None:
    if state == "AMBIGUOUS":
        repo = tie_repo([(EA, RAYONG, T1), (EB, LAEM, T1)])
        vid, event = "VEH-1047", EA
    else:
        repo, vid, event = MockRepository(), "VEH-1046", E_INSERTED
    path = p_correction(vid, event) if op == "correction" else p_cancellation(vid, event)
    body = correction_body(repo, vid, effective=_date("2026-08-20")) if op == "correction" else cancellation_body(repo, vid)
    if state == "NOOP" and op == "correction":
        body["effective"] = _date("2026-08-20")  # equals the head: would be a no-op
    body["expected_master_branch_id"] = "BR-WRONG" if expected == "wrong" else None
    response = await post(path, body, repo)
    assert (response.status_code, _err(response)["code"], _err(response)["details"]) == (
        409, "BRANCH_HISTORY_STALE", {"field": "master_branch_id"})
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_b17_replay_precedes_stale_and_state_checks() -> None:
    repo = MockRepository()
    rid = _rid()
    body = cancellation_body(repo)
    first = await post(p_cancellation(), body, repo, request_id=rid)
    assert first.status_code == 200
    again = await post(p_cancellation(), body, repo, request_id=rid)  # its expected values are now stale
    assert again.status_code == 200
    assert again.json() == {"request_id": rid, "replayed": True, "record_ids": [first.json()["record_id"]],
                            "consistency": "CONSISTENT"}
    assert repo.registry_write_log == ["W1", "W2"]


@pytest.mark.asyncio
async def test_replay_identity_includes_operation_vehicle_and_event_id() -> None:
    repo = MockRepository()
    rid = _rid()
    await post(p_correction(), correction_body(repo), repo, request_id=rid)
    for path, body in ((p_correction(event=E_LATEST), correction_body(repo)),
                       (p_cancellation(event=E_INSERTED), cancellation_body(repo)),
                       (p_transfer(), transfer_body(repo)),
                       (p_correction("VEH-1048"), correction_body(repo, "VEH-1048"))):
        response = await post(path, body, repo, request_id=rid)
        assert (response.status_code, _err(response)["code"]) == (409, "REQUEST_ID_REUSED"), path
    assert request_fingerprint("correction", "V", "E1", {}) != request_fingerprint("correction", "V", "E2", {})
    assert repo.registry_write_log == ["W1"]


# ===========================================================================
# C-c1 / C-c2 / B-19 ties
# ===========================================================================


@pytest.mark.asyncio
async def test_c_c1_ambiguous_timeline_refuses_edits_of_a_non_tied_event() -> None:
    repo = tie_repo([(EC, RAYONG, T0), (EA, LAEM, T1), (EB, BANGNA, T1)])  # EC not tied
    for path, body in ((p_correction("VEH-1047", EC), correction_body(repo, "VEH-1047", effective=_at("2026-08-05T00:00:00Z"))),
                       (p_cancellation("VEH-1047", EC), cancellation_body(repo, "VEH-1047"))):
        response = await post(path, body, repo)
        assert (response.status_code, _err(response)["code"], _err(response)["details"]) == (
            409, "BRANCH_TIMELINE_AMBIGUOUS", {"reason": "TARGET_NOT_TIED"})
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_c_c1_c_c2_a_tied_target_may_be_corrected_when_the_source_is_unique() -> None:
    repo = tie_repo([(EC, RAYONG, T0), (EA, LAEM, T1), (EB, BANGNA, T1)], master=LAEM)
    body = correction_body(repo, "VEH-1047", to=LAEM, effective=_at("2026-08-20T00:00:00Z"))
    response = await post(p_correction("VEH-1047", EA), body, repo)
    assert response.status_code == 200, response.text
    row = repo._asset_branch_history[-1]
    # earlier remaining: EC (Rayong, T0) and EB (Bangna, T1): no tie -> Bangna, uniquely
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == (BANGNA, "EVENT")
    assert response.json()["timeline_status_after"] == "VALID"
    assert response.json()["projection_write"] == "NOT_NEEDED"  # current EA=Laem == master


@pytest.mark.asyncio
async def test_c_c2_correction_refuses_when_earlier_events_are_still_tied() -> None:
    repo = tie_repo([(EA, RAYONG, T1), (EB, LAEM, T1), (EC, BANGNA, T1)])  # three-way tie
    body = correction_body(repo, "VEH-1047", to=RAYONG, effective=_at("2026-08-20T00:00:00Z"))
    response = await post(p_correction("VEH-1047", EA), body, repo)
    assert (response.status_code, _err(response)["code"], _err(response)["details"]) == (
        409, "BRANCH_TIMELINE_AMBIGUOUS", {"reason": "SOURCE_UNDETERMINED"})
    assert repo.registry_write_log == []
    assert not any(r["record_kind"] == "CORRECTION" for r in _rows(repo, "VEH-1047"))  # no false NONE source


@pytest.mark.asyncio
async def test_c_c2_correction_before_the_tie_is_allowed_and_stays_not_determined() -> None:
    repo = tie_repo([(EA, RAYONG, T1), (EB, LAEM, T1), (EC, BANGNA, T1)], master=LAEM)
    body = correction_body(repo, "VEH-1047", to=RAYONG, effective=_at("2026-08-01T00:00:00Z"))
    response = await post(p_correction("VEH-1047", EA), body, repo)
    assert response.status_code == 200, response.text
    assert (response.json()["projection_write"], response.json()["timeline_status_after"]) == ("NOT_DETERMINED", "AMBIGUOUS_ORDER")
    row = repo._asset_branch_history[-1]
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == (BANGNA, "BASELINE")
    assert _master(repo, "VEH-1047") == LAEM and repo.registry_write_log == ["W1"]


@pytest.mark.asyncio
async def test_b19_three_tied_events_cancel_one_then_another() -> None:
    repo = tie_repo([(EA, RAYONG, T1), (EB, LAEM, T1), (EC, BANGNA, T1)], master=RAYONG)
    first = await post(p_cancellation("VEH-1047", EA), cancellation_body(repo, "VEH-1047"), repo)
    assert first.status_code == 200, first.text
    assert (first.json()["projection_write"], first.json()["timeline_status_after"], first.json()["consistency"]) == (
        "NOT_DETERMINED", "AMBIGUOUS_ORDER", "UNDETERMINED")
    assert _master(repo, "VEH-1047") == RAYONG and repo.registry_write_log == ["W1"]  # master kept, no W2
    second = await post(p_cancellation("VEH-1047", EB), cancellation_body(repo, "VEH-1047"), repo)
    assert (second.json()["projection_write"], second.json()["timeline_status_after"]) == ("WRITTEN", "VALID")
    assert _master(repo, "VEH-1047") == BANGNA  # the remaining event; master differed, so W2
    assert repo.registry_write_log == ["W1", "W1", "W2"]


@pytest.mark.asyncio
async def test_b19_cancel_one_of_two_tied_events_resolves_without_w2_when_equal() -> None:
    repo = tie_repo([(EA, RAYONG, T1), (EB, LAEM, T1)], master=LAEM)
    response = await post(p_cancellation("VEH-1047", EA), cancellation_body(repo, "VEH-1047"), repo)
    assert (response.json()["projection_write"], response.json()["timeline_status_after"]) == ("NOT_NEEDED", "VALID")
    assert repo.registry_write_log == ["W1"]


# ===========================================================================
# B-09 / B-21 projection reconciliation (§6.6)
# ===========================================================================


@pytest.mark.asyncio
async def test_b09_reconciliation_writes_the_derived_value_and_audit_row() -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1046", RAYONG)  # hand-edited master: PROJECTION_MISMATCH
    before = [dict(r) for r in repo._asset_branch_history]
    spy_calls: list[str] = []
    original = repo.read_branch_master_validated

    async def spy():
        spy_calls.append("branch_master")
        return await original()

    repo.read_branch_master_validated = spy  # type: ignore[method-assign]
    body = reconcile_body(repo, related_request_id="mock-seed-7o2a-0001")
    response = await post(p_reconcile(), body, repo)
    assert response.status_code == 200, response.text
    assert (response.json()["projection_write"], response.json()["event_id"]) == ("WRITTEN", None)
    assert repo._asset_branch_history[:-1] == before
    row = repo._asset_branch_history[-1]
    assert (row["record_kind"], row["entry_operation"], row["branch_id"], row["reconciled_old_master_branch_id"]) == (
        "PROJECTION_RECONCILIATION", "PROJECTION_RECONCILIATION", LAEM, RAYONG)
    assert row["related_request_id"] == "mock-seed-7o2a-0001"
    assert all(row[f] == "" for f in ("event_id", "revision_no", "supersedes_record_id", "start_at",
                                       "recorded_from_source", "baseline_source"))
    assert validate_branch_row(row) == []
    assert _master(repo, "VEH-1046") == LAEM and spy_calls == []  # no reference check
    assert (await branch_history(repo))["consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_b09_reconciliation_mirrors_an_unknown_historical_code() -> None:
    repo = tie_repo([(EA, "BR-RETIRED", T1)], master=RAYONG)  # history names a code not in branch_master
    response = await post(p_reconcile("VEH-1047"), reconcile_body(repo, "VEH-1047"), repo)
    assert response.status_code == 200, response.text
    assert _master(repo, "VEH-1047") == "BR-RETIRED"


@pytest.mark.asyncio
async def test_b09_reconciliation_noop_stale_ambiguous() -> None:
    repo = MockRepository()
    noop = await post(p_reconcile(), reconcile_body(repo), repo)
    assert noop.json()["changed"] is False
    no_history = await post(p_reconcile("VEH-1047"), reconcile_body(repo, "VEH-1047"), repo)
    assert no_history.json()["changed"] is False
    stale = await post(p_reconcile(), reconcile_body(repo, expected_history_revision="BHR1-0"), repo)
    assert _err(stale)["details"] == {"field": "history_revision"}
    master = await post(p_reconcile(), reconcile_body(repo, expected_master_branch_id=RAYONG), repo)
    assert _err(master)["details"] == {"field": "master_branch_id"}
    amb = MockRepository()
    tie_seed_1046(amb)
    ambiguous = await post(p_reconcile(), reconcile_body(amb), amb)
    assert _err(ambiguous)["code"] == "BRANCH_TIMELINE_AMBIGUOUS"
    assert repo.registry_write_log == [] and amb.registry_write_log == []


@pytest.mark.asyncio
async def test_b21_related_request_id_must_name_a_request_of_this_vehicle() -> None:
    repo = MockRepository()
    _set_master(repo, "VEH-1046", RAYONG)
    for related in ("no-such-request", "mock-seed-7o2a-0004"):  # nonexistent; VEH-1048's request
        response = await post(p_reconcile(), reconcile_body(repo, related_request_id=related), repo)
        assert (response.status_code, _err(response)["code"]) == (422, "RELATED_REQUEST_NOT_FOUND"), related
    assert repo.registry_write_log == []
    valid = await post(p_reconcile(), reconcile_body(repo, related_request_id="mock-seed-7o2a-0003"), repo)
    assert valid.status_code == 200


# ===========================================================================
# B-08 write-failure matrix (§6.7) and B-OC-02
# ===========================================================================

OPS_W2 = {
    "transfer": (p_transfer, transfer_body),
    "correction": (lambda: p_correction(event=E_LATEST), lambda r: correction_body(r, to=RAYONG, effective=_date("2026-09-01"))),
    "cancellation": (p_cancellation, cancellation_body),
    "reconcile": (p_reconcile, reconcile_body),
}


def _w2_repo(op: str) -> MockRepository:
    repo = MockRepository()
    if op == "reconcile":
        _set_master(repo, "VEH-1046", RAYONG)
    return repo


@pytest.mark.asyncio
@pytest.mark.parametrize("op", sorted(OPS_W2))
@pytest.mark.parametrize("fault,outcome,recorded", [("rejected", "rejected", False), ("unknown_applied", "unknown", True),
                                                     ("unknown_not_applied", "unknown", False)])
async def test_b08_w1_failures(op, fault, outcome, recorded) -> None:
    repo = _w2_repo(op)
    path, body = OPS_W2[op]
    count = len(repo._asset_branch_history)
    master = _master(repo, "VEH-1046")
    repo.registry_write_faults["W1"] = fault
    response = await post(path(), body(repo), repo)
    assert (response.status_code, _err(response)["code"]) == (503, "BRANCH_HISTORY_WRITE_FAILED")
    assert _err(response)["details"] == {"history_write_outcome": outcome, "projection_write": "NOT_ATTEMPTED",
                                         "request_id": response.sent_request_id}
    assert repo.registry_write_log == ["W1"]
    assert len(repo._asset_branch_history) == count + (1 if recorded else 0)
    assert _master(repo, "VEH-1046") == master


@pytest.mark.asyncio
@pytest.mark.parametrize("op", sorted(OPS_W2))
@pytest.mark.parametrize("fault,outcome,applied", [("rejected", "rejected", False), ("unknown_applied", "unknown", True),
                                                   ("unknown_not_applied", "unknown", False)])
async def test_b08_w2_failures(op, fault, outcome, applied) -> None:
    repo = _w2_repo(op)
    path, body = OPS_W2[op]
    repo.registry_write_faults["W2"] = fault
    response = await post(path(), body(repo), repo)
    assert (response.status_code, _err(response)["code"]) == (503, "BRANCH_PROJECTION_WRITE_FAILED")
    details = _err(response)["details"]
    assert details["event_recorded"] is True and details["projection_write_outcome"] == outcome
    assert details["record_id"] == repo._asset_branch_history[-1]["assignment_id"]
    assert details["request_id"] == response.sent_request_id
    history = await branch_history(repo)
    assert history["consistency"] == ("CONSISTENT" if applied else "PROJECTION_MISMATCH")
    assert any(r["request_id"] == response.sent_request_id for r in history["records"])


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["unknown_applied", "unknown_not_applied"])
async def test_b08_insertion_projection_matches_whether_or_not_w1_applied(fault) -> None:
    repo = MockRepository()
    repo.registry_write_faults["W1"] = fault
    response = await post(p_insertion(), insertion_body(repo), repo)
    assert _err(response)["details"]["history_write_outcome"] == "unknown"
    history = await branch_history(repo)
    assert history["consistency"] == "CONSISTENT"  # proves nothing: only the request id tells
    assert any(r["request_id"] == response.sent_request_id for r in history["records"]) is (fault == "unknown_applied")


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["W1", "W2"])
async def test_b_oc_02_crash_after_a_write_is_internal_error(step) -> None:
    repo = MockRepository()
    repo.registry_write_faults[step] = "crash_after_apply"
    response = await post(p_transfer(), transfer_body(repo), repo)
    assert (response.status_code, _err(response)["code"]) == (500, "INTERNAL_ERROR")
    assert _err(response)["request_id"] == response.sent_request_id
    assert _master(repo, "VEH-1046") == (RAYONG if step == "W2" else LAEM)


@pytest.mark.asyncio
async def test_b_oc_02_failure_while_building_the_response(monkeypatch) -> None:
    import app.api.v1.branch_routes as routes

    monkeypatch.setattr(routes, "_respond", lambda outcome: (_ for _ in ()).throw(RuntimeError("serialize")))
    repo = MockRepository()
    response = await post(p_transfer(), transfer_body(repo), repo)
    assert (response.status_code, _err(response)["code"]) == (500, "INTERNAL_ERROR")
    assert repo.registry_write_log == ["W1", "W2"]


# ===========================================================================
# B-11 / B-18 structural validation
# ===========================================================================

DEFECTS = {
    "REVISION_FORK_OR_GAP": lambda rows: rows.__setitem__(slice(None), [
        {**r, "revision_no": "3"} if r["assignment_id"] == H_INSERTED else r for r in rows]),
    "DANGLING_REFERENCE": lambda rows: next(r for r in rows if r["assignment_id"] == H_INSERTED).update(supersedes_record_id="ABH-ghost"),
    "EFFECTIVE_AT_INVALID": lambda rows: rows[0].update(start_at="2026-08-31T17:00:00"),
    "FIELD_MUST_BE_BLANK:end_at": lambda rows: rows[0].update(end_at="2026-09-30T00:00:00+00:00"),
    "LEGACY_ROW_UNCLASSIFIED": lambda rows: rows[0].update(record_kind=""),
    "BASELINE_CONFLICT": lambda rows: next(r for r in rows if r["assignment_id"] == E_INSERTED).update(
        baseline_branch_id=LAEM, baseline_source="IMPORTED_MASTER"),
    "REQUEST_ID_DUPLICATE": lambda rows: rows[1].update(request_id=rows[0]["request_id"]),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("issue", sorted(DEFECTS))
@pytest.mark.parametrize("op", sorted(ENDPOINTS))
async def test_b11_structural_issues_block_every_mutation(issue, op) -> None:
    repo = MockRepository()
    rows = [r for r in repo._asset_branch_history if r["asset_id"] == "VEH-1046"]
    path, body = ENDPOINTS[op]
    request = body(repo)  # built before the defect (the revision is irrelevant: INVALID comes first)
    DEFECTS[issue](rows)
    others = [r for r in repo._asset_branch_history if r["asset_id"] != "VEH-1046"]
    repo._asset_branch_history = rows + others
    response = await post(path(), request, repo)
    assert (response.status_code, _err(response)["code"]) == (500, "BRANCH_HISTORY_DATA_INVALID")
    assert any(issue in code for code in _err(response)["details"]["issues"]), _err(response)["details"]
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_b11_duplicate_record_id_anywhere_in_the_tab_refuses_mutations_but_not_reads() -> None:
    repo = MockRepository()
    clone = dict(next(r for r in repo._asset_branch_history if r["asset_id"] == "VEH-1048"))
    clone.update(asset_id="VEH-OTHER", request_id="other")  # same assignment_id, another asset
    repo._asset_branch_history.append(clone)
    response = await post(p_transfer(), transfer_body(repo), repo)
    assert (response.status_code, _err(response)["details"]["issues"]) == (500, {"RECORD_ID_DUPLICATE": 1})
    assert repo.registry_write_log == []
    assert (await _http("GET", f"{API}/vehicles/VEH-1046/branch-history", repo=repo, request_id=None)).status_code == 200


@pytest.mark.asyncio
async def test_b18_every_generated_row_passes_the_strict_validator_and_the_timeline_stays_valid() -> None:
    repo = MockRepository()
    await post(p_transfer(), transfer_body(repo, effective=_date("2026-09-10")), repo)
    await post(p_insertion(), insertion_body(repo, to=LAEM, effective=_date("2026-08-05")), repo)
    await post(p_correction(), correction_body(repo, effective=_date("2026-08-24")), repo)
    await post(p_cancellation(event=E_LATEST), cancellation_body(repo), repo)
    _set_master(repo, "VEH-1046", BANGNA)
    await post(p_reconcile(), reconcile_body(repo), repo)
    written = repo._asset_branch_history[-5:]
    assert [r["record_kind"] for r in written] == ["ASSIGNMENT", "ASSIGNMENT", "CORRECTION", "CANCELLATION",
                                                   "PROJECTION_RECONCILIATION"]
    for row in written:
        assert validate_branch_row(row) == [], row
    assert _timeline(repo, "VEH-1046").status == "VALID"
    assert (await branch_history(repo))["consistency"] == "CONSISTENT"


@pytest.mark.asyncio
async def test_b18_every_kind_in_the_matrix_rejects_a_violation() -> None:
    repo = MockRepository()
    await post(p_cancellation(event=E_INSERTED), cancellation_body(repo), repo)
    cancellation = dict(repo._asset_branch_history[-1])
    assert validate_branch_row({**cancellation, "branch_id": LAEM}) == ["FIELD_MUST_BE_BLANK:branch_id"]
    _set_master(repo, "VEH-1046", RAYONG)
    await post(p_reconcile(), reconcile_body(repo), repo)
    recon = dict(repo._asset_branch_history[-1])
    assert "FIELD_MUST_BE_BLANK:event_id" in validate_branch_row({**recon, "event_id": E_LATEST})
    assert "FIELD_REQUIRED:note_th" in validate_branch_row({**recon, "note_th": ""})


# ===========================================================================
# B-12 branch-only master (C-c7) and B-13 contexts
# ===========================================================================


def _branch_only(repo: MockRepository) -> MockRepository:
    original = repo.read_vehicle_branch_master

    async def read(vehicle_id):
        r = await original(vehicle_id)
        return None if r is None else RegistrationMasterRead(
            r.vehicle, r.registry, frozenset({"responsible_branch_id"}), r.target_row_key, r.rows, r.write_target)

    repo.read_vehicle_branch_master = read  # type: ignore[method-assign]
    original_reg = repo.read_vehicle_registration_master

    async def read_reg(vehicle_id):
        r = await original_reg(vehicle_id)
        return None if r is None else RegistrationMasterRead(
            r.vehicle, r.registry, frozenset({"responsible_branch_id"}), r.target_row_key, r.rows, r.write_target)

    repo.read_vehicle_registration_master = read_reg  # type: ignore[method-assign]
    return repo


@pytest.mark.asyncio
async def test_b12_c_c7_branch_only_master_supports_every_branch_mutation_and_refuses_registration() -> None:
    repo = _branch_only(MockRepository())
    steps = [
        (p_transfer(), transfer_body(repo, effective=_date("2026-09-10"))),
    ]
    response = await post(*steps[0], repo)
    assert response.status_code == 200, response.text
    for path, build in ((p_insertion(), lambda: insertion_body(repo, to=LAEM, effective=_date("2026-08-05"))),
                        (p_correction(), lambda: correction_body(repo, effective=_date("2026-08-24"))),
                        (p_cancellation(event=E_LATEST), lambda: cancellation_body(repo))):
        response = await post(path, build(), repo)
        assert response.status_code == 200, (path, response.text)
    _set_master(repo, "VEH-1046", BANGNA)
    assert (await post(p_reconcile(), reconcile_body(repo), repo)).status_code == 200
    registration = await _http("PATCH", f"{API}/vehicles/VEH-1046/registration", repo=repo, json_body={
        "registration_no": "1", "registration_province_code": None,
        "expected_registration_no": "0012", "expected_registration_province_code": "TH-21"})
    assert (registration.status_code, _err(registration)["code"]) == (500, "VEHICLE_MASTER_SCHEMA_INVALID")


@pytest.mark.asyncio
async def test_missing_branch_column_is_refused_before_any_write() -> None:
    repo = MockRepository()
    original = repo.read_vehicle_branch_master

    async def read(vehicle_id):
        r = await original(vehicle_id)
        return RegistrationMasterRead(r.vehicle, r.registry, frozenset({"registration_no", "registration_province_code"}),
                                      r.target_row_key, r.rows, r.write_target)

    repo.read_vehicle_branch_master = read  # type: ignore[method-assign]
    response = await post(p_transfer(), transfer_body(MockRepository()), repo)
    assert (response.status_code, _err(response)["code"]) == (500, "VEHICLE_MASTER_SCHEMA_INVALID")
    assert _err(response)["details"]["headers"] == ["responsible_branch_id"]
    assert repo.registry_write_log == []


@pytest.mark.asyncio
async def test_b13_real_context_refuses_test_rows_and_writes_false_flags() -> None:
    repo = MockRepository()
    service = BranchWriteService(repo, "REAL", "")
    with pytest.raises(ApiError) as info:
        await service.transfer("VEH-1046", transfer_body(repo), request_id=_rid(), user_id="u1")
    assert info.value.code == "BRANCH_HISTORY_DATA_INVALID" and "CUTOVER_INCOMPLETE" in info.value.details["issues"]
    outcome = await service.transfer("VEH-1047", transfer_body(repo, "VEH-1047", effective=_date("2026-09-20")),
                                     request_id=_rid(), user_id="u1")
    assert outcome.changed
    row = _rows(repo, "VEH-1047")[-1]
    assert (row["is_test_data"], row["test_batch_id"]) == ("FALSE", "")


@pytest.mark.asyncio
async def test_b13_blank_test_batch_id_refuses_branch_mutations_but_not_reads() -> None:
    settings = _sheets_settings("TEST", "")
    for op, (path, body) in ENDPOINTS.items():
        repo = SpyRepository()
        response = await post(path(), body(MockRepository()), repo, settings=settings)
        assert (response.status_code, _err(response)["code"]) == (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"), op
        assert repo.calls == []
    read = await _http("GET", f"{API}/vehicles/VEH-1046/branch-history", repo=MockRepository(), settings=settings, request_id=None)
    assert read.status_code == 200


# ===========================================================================
# C-c4 effective time, C-c5 reason, C-c6 transfer note
# ===========================================================================

NOW = datetime(2026, 10, 5, 3, 0, 0, tzinfo=timezone.utc)


def test_c_c4_effective_time_rules_exactly() -> None:
    lower = resolve_effective(_at("1990-01-01T00:00:00Z"), NOW)
    assert lower.instant == datetime(1990, 1, 1, tzinfo=timezone.utc)
    for value, code in ((_at("1989-12-31T23:59:59Z"), "EFFECTIVE_TIME_OUT_OF_RANGE"),
                        (_date("1990-01-01"), "EFFECTIVE_TIME_OUT_OF_RANGE"),  # Bangkok midnight = 1989-12-31T17Z
                        (_at("2026-09-01T10:00:00.5+07:00"), "EFFECTIVE_TIME_PRECISION"),
                        (_at("2026-09-01T10:00:00"), "EFFECTIVE_TIME_OFFSET_REQUIRED"),
                        (_at("2026-10-05T03:00:01Z"), "FUTURE_EFFECTIVE_NOT_ALLOWED"),
                        (_date("2026-10-06"), "FUTURE_EFFECTIVE_NOT_ALLOWED"),
                        (_date("2026-02-30"), "EFFECTIVE_MODE_INVALID"),
                        ({"mode": "SOON"}, "EFFECTIVE_MODE_INVALID"),
                        ({}, "EFFECTIVE_MODE_INVALID")):
        with pytest.raises(EffectiveTimeError) as info:
            resolve_effective(value, NOW)
        assert info.value.code == code, value
    assert resolve_effective(_date("1990-01-02"), NOW).instant == datetime(1990, 1, 1, 17, tzinfo=timezone.utc)
    zero = resolve_effective(_at("2026-09-01T10:00:00.000+07:00"), NOW)  # .000: microsecond 0 -> accepted
    assert zero.instant == datetime(2026, 9, 1, 3, tzinfo=timezone.utc) and zero.precision == "DATETIME"
    assert resolve_effective(_date("2026-10-05"), NOW).instant == datetime(2026, 10, 4, 17, tzinfo=timezone.utc)  # today


@pytest.mark.asyncio
async def test_c_c4_effective_time_through_the_api_with_zero_reads_on_refusal() -> None:
    repo = MockRepository()
    accepted = await post(p_transfer("VEH-1047"), transfer_body(repo, "VEH-1047", effective=_at("1990-01-01T00:00:00Z")), repo)
    assert accepted.status_code == 200, accepted.text
    spy = SpyRepository()
    for effective, code in ((_date("1990-01-01"), "EFFECTIVE_TIME_OUT_OF_RANGE"),
                            (_at("2026-09-01T10:00:00.25Z"), "EFFECTIVE_TIME_PRECISION")):
        response = await post(p_transfer(), transfer_body(MockRepository(), effective=effective), spy)
        assert (response.status_code, _err(response)["code"]) == (422, code)
    assert spy.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["insertion", "correction", "cancellation", "reconcile"])
@pytest.mark.parametrize("reason", ["", "   ", "\t\n", None, "ก" * 501, "<omitted>"], ids=["empty", "spaces", "tab", "null", "501", "omitted"])
async def test_c_c5_reason_rule_is_semantic_with_zero_calls(op, reason) -> None:
    path, build = ENDPOINTS[op]
    body = build(MockRepository())
    if reason == "<omitted>":
        del body["reason_th"]
    else:
        body["reason_th"] = reason
    repo = SpyRepository()
    response = await post(path(), body, repo)
    assert (response.status_code, _err(response)["code"]) == (422, "REASON_REQUIRED")
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["insertion", "correction", "cancellation", "reconcile"])
async def test_c_c5_wrong_reason_type_is_validation_error(op) -> None:
    path, build = ENDPOINTS[op]
    for value in (5, {"a": 1}, ["x"]):
        repo = SpyRepository()
        response = await post(path(), {**build(MockRepository()), "reason_th": value}, repo)
        assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR")
        assert repo.calls == []


@pytest.mark.asyncio
async def test_c_c5_reason_of_500_characters_is_stored_exactly() -> None:
    repo = MockRepository()
    reason = " " + "ข" * 498 + " "
    response = await post(p_cancellation(), cancellation_body(repo, reason_th=reason), repo)
    assert response.status_code == 200, response.text
    assert repo._asset_branch_history[-1]["note_th"] == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("note", ["<omitted>", None, "", "  =1+1 ", "ย" * 900])
async def test_c_c6_transfer_note_is_optional_exact_and_unlimited(note) -> None:
    repo = MockRepository()
    body = transfer_body(repo)
    if note != "<omitted>":
        body["note_th"] = note
    response = await post(p_transfer(), body, repo)
    assert response.status_code == 200, response.text
    assert repo._asset_branch_history[-1]["note_th"] == ("" if note in ("<omitted>", None) else note)
    wrong = await post(p_transfer(), {**transfer_body(repo), "note_th": 5}, SpyRepository())
    assert _err(wrong)["code"] == "VALIDATION_ERROR"


# ===========================================================================
# B-OC-01 every allowlisted pair of the five operations
# ===========================================================================


def _common(op: str):
    path, build = ENDPOINTS[op]

    def master_cols(repo, cols):
        original = repo.read_vehicle_branch_master

        async def read(vehicle_id):
            r = await original(vehicle_id)
            return RegistrationMasterRead(r.vehicle, r.registry, cols, r.target_row_key, r.rows, r.write_target)

        repo.read_vehicle_branch_master = read

    def setter(name, exc):
        return lambda repo: setattr(repo, name, _raise(exc))

    def broken_row(repo):
        next(r for r in repo._asset_branch_history if r["assignment_id"] == E_LATEST)["recorded_by"] = ""

    return {
        (403, "HTTP_ERROR"): {"role": "DRIVER"},
        (422, "REQUEST_ID_REQUIRED"): {"request_id": "not-a-uuid"},
        (422, "VALIDATION_ERROR"): {"patch": {"unexpected": 1}},
        (503, "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"): {"settings": _sheets_settings(None, "B")},
        (404, "VEHICLE_NOT_FOUND"): {"path": path().replace("VEH-1046", "VEH-NONE")},
        (409, "VEHICLE_ID_AMBIGUOUS"): {"mutate": setter("read_vehicle_branch_master", RepositoryIdentityAmbiguousError("vehicle_master", 2))},
        (500, "VEHICLE_MASTER_DATA_INVALID"): {"mutate": setter("read_vehicle_branch_master", RepositoryRecordInvalidError("vehicle_master", "BLANK_STATUS"))},
        (500, "VEHICLE_MASTER_SCHEMA_INVALID"): {"mutate": lambda repo: master_cols(repo, frozenset())},
        (503, "VEHICLE_MASTER_READ_FAILED"): {"mutate": setter("read_vehicle_branch_master", RepositoryTabReadError("vehicle_master", "x"))},
        (503, "BRANCH_HISTORY_READ_FAILED"): {"mutate": setter("read_asset_branch_history_validated", RepositoryTabReadError("asset_branch_history", "x"))},
        (500, "BRANCH_HISTORY_SCHEMA_INVALID"): {"mutate": setter("read_asset_branch_history_validated", RepositorySchemaError("asset_branch_history", "TAB_MISSING"))},
        (500, "BRANCH_HISTORY_DATA_INVALID"): {"mutate": broken_row},
    }


def _reference_and_time(base_patch: dict | None = None):
    """`base_patch` is merged into the R3 cases: a correction reaches R3 only
    when its destination changes (7O2c R1)."""
    r3 = {"patch": dict(base_patch or {})}

    def setter(name, exc):
        return lambda repo: setattr(repo, name, _raise(exc))

    def inactive(repo):
        for b in repo._branch_master:
            b["is_active"] = "FALSE"

    return {
        (503, "BRANCH_MASTER_READ_FAILED"): {**r3, "mutate": setter("read_branch_master_validated", RepositoryTabReadError("branch_master", "x"))},
        (500, "BRANCH_MASTER_SCHEMA_INVALID"): {**r3, "mutate": setter("read_branch_master_validated", RepositorySchemaError("branch_master", "TAB_MISSING"))},
        (500, "BRANCH_MASTER_DATA_INVALID"): {**r3, "mutate": lambda repo: repo._branch_master.append(dict(repo._branch_master[0]))},
        (422, "BRANCH_NOT_FOUND"): {"patch": {"to_branch_id": "BR-NOPE"}},
        (422, "BRANCH_INACTIVE"): {**r3, "mutate": inactive},
        (422, "EFFECTIVE_MODE_INVALID"): {"patch": {"effective": {"mode": "SOON"}}},
        (422, "EFFECTIVE_MODE_NOT_ALLOWED"): {"patch": {"effective": {"mode": "NOW"}}},
        (422, "EFFECTIVE_TIME_OFFSET_REQUIRED"): {"patch": {"effective": _at("2026-08-25T00:00:00")}},
        (422, "EFFECTIVE_TIME_PRECISION"): {"patch": {"effective": _at("2026-08-25T00:00:00.5Z")}},
        (422, "FUTURE_EFFECTIVE_NOT_ALLOWED"): {"patch": {"effective": _date("2099-01-01")}},
        (422, "EFFECTIVE_TIME_OUT_OF_RANGE"): {"patch": {"effective": _date("1980-01-01")}},
    }


def _mismatch(repo):
    _set_master(repo, "VEH-1046", RAYONG)


B_OC = {
    "transfer": {
        **_common("transfer"), **_reference_and_time(),
        (409, "BRANCH_HISTORY_STALE"): {"patch": {"expected_history_revision": "BHR1-0"}},
        (409, "BRANCH_TIMELINE_AMBIGUOUS"): {"mutate": tie_seed_1046, "patch": {"expected_current_branch_id": None}},
        (409, "BRANCH_PROJECTION_MISMATCH"): {"mutate": _mismatch, "patch": {"to_branch_id": BANGNA}},
        (409, "BRANCH_EVENT_SAME_INSTANT"): {"patch": {"effective": _at("2026-08-31T17:00:00Z")}},
        (409, "BRANCH_TRANSFER_NOT_LATEST"): {"patch": {"effective": _date("2026-08-25")}},
    },
    "insertion": {
        **_common("insertion"), **_reference_and_time(),
        (422, "REASON_REQUIRED"): {"patch": {"reason_th": ""}},
        (409, "BRANCH_HISTORY_STALE"): {"patch": {"expected_history_revision": "BHR1-0"}},
        (409, "BRANCH_TIMELINE_AMBIGUOUS"): {"mutate": tie_seed_1046},
        (409, "BRANCH_PROJECTION_MISMATCH"): {"mutate": _mismatch},
        (409, "BRANCH_EVENT_SAME_INSTANT"): {"patch": {"effective": _at("2026-08-19T17:00:00Z")}},
        (409, "BRANCH_INSERTION_NOT_HISTORICAL"): {"patch": {"effective": _date("2026-09-15")}},
    },
    "correction": {
        **_common("correction"), **_reference_and_time({"to_branch_id": RAYONG}),
        (422, "REASON_REQUIRED"): {"patch": {"reason_th": None}},
        (409, "BRANCH_HISTORY_STALE"): {"patch": {"expected_master_branch_id": "BR-WRONG"}},
        (409, "BRANCH_PROJECTION_MISMATCH"): {"mutate": _mismatch, "patch": {"expected_master_branch_id": RAYONG}},
        (404, "BRANCH_EVENT_NOT_FOUND"): {"path": p_correction(event="ABH-nope")},
        (409, "BRANCH_EVENT_CANCELLED"): {"path": p_correction("VEH-1048", E_CANCELLED), "patch": {"expected_master_branch_id": None}, "vid": "VEH-1048"},
        (409, "BRANCH_EVENT_SAME_INSTANT"): {"patch": {"effective": _at("2026-08-31T17:00:00Z")}},
        (409, "BRANCH_TIMELINE_AMBIGUOUS"): {"tie": True},
    },
    "cancellation": {
        **_common("cancellation"),
        (422, "REASON_REQUIRED"): {"patch": {"reason_th": "  "}},
        (409, "BRANCH_HISTORY_STALE"): {"patch": {"expected_history_revision": "BHR1-0"}},
        (409, "BRANCH_PROJECTION_MISMATCH"): {"mutate": _mismatch, "patch": {"expected_master_branch_id": RAYONG}},
        (404, "BRANCH_EVENT_NOT_FOUND"): {"path": p_cancellation(event="ABH-nope")},
        (409, "BRANCH_EVENT_CANCELLED"): {"path": p_cancellation("VEH-1048", E_CANCELLED), "patch": {"expected_master_branch_id": None}, "vid": "VEH-1048"},
        (409, "BRANCH_TIMELINE_AMBIGUOUS"): {"tie": True},
    },
    "reconcile": {
        **_common("reconcile"),
        (422, "REASON_REQUIRED"): {"patch": {"reason_th": "ก" * 501}},
        (422, "RELATED_REQUEST_NOT_FOUND"): {"patch": {"related_request_id": "nope"}},
        (409, "BRANCH_HISTORY_STALE"): {"patch": {"expected_history_revision": "BHR1-0"}},
        (409, "BRANCH_TIMELINE_AMBIGUOUS"): {"mutate": tie_seed_1046, "patch": {"expected_master_branch_id": LAEM}},
    },
}
# Allowlisted but unreachable by construction (documented, never raised):
# NOW is a valid transfer mode.
UNREACHABLE = {("transfer", (422, "EFFECTIVE_MODE_NOT_ALLOWED"))}
for _op, _pair in UNREACHABLE:
    B_OC[_op].pop(_pair)


def test_b_oc_cases_cover_the_branch_allowlists() -> None:
    for op, cases in B_OC.items():
        assert set(cases) | {p for o, p in UNREACHABLE if o == op} == set(ZERO_WRITE_ALLOWLIST[op]), op


@pytest.mark.asyncio
@pytest.mark.parametrize("op,pair", [(op, pair) for op, cases in B_OC.items() for pair in sorted(cases)],
                         ids=lambda v: v if isinstance(v, str) else f"{v[0]}-{v[1]}")
async def test_b_oc_01_each_allowlisted_branch_pair_writes_nothing(op, pair) -> None:
    case = B_OC[op][pair]
    path, build = ENDPOINTS[op]
    if case.get("tie"):
        repo = tie_repo([(EC, RAYONG, T0), (EA, LAEM, T1), (EB, BANGNA, T1)])
        request_path = p_correction("VEH-1047", EC) if op == "correction" else p_cancellation("VEH-1047", EC)
        body = (correction_body(repo, "VEH-1047", effective=_at("2026-08-05T00:00:00Z")) if op == "correction"
                else cancellation_body(repo, "VEH-1047"))
    else:
        repo = MockRepository()
        if "mutate" in case:
            case["mutate"](repo)
        request_path = case.get("path", path())
        vid = case.get("vid", "VEH-1046")
        body = build(repo) if vid == "VEH-1046" else {
            "correction": lambda: correction_body(repo, vid), "cancellation": lambda: cancellation_body(repo, vid)}[op]()
    body.update(case.get("patch", {}))
    response = await post(request_path, body, repo, role=case.get("role", "MAINTENANCE_MANAGER"),
                          request_id=case.get("request_id", _AUTO), settings=case.get("settings"))
    assert (response.status_code, _err(response)["code"]) == pair, response.text
    assert _err(response)["request_id"] == response.sent_request_id
    assert repo.registry_write_log == []


def test_b_oc_static_every_branch_code_is_classified_and_no_http_exception() -> None:
    path = REPO_ROOT / "backend" / "app" / "domain" / "branch_write_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    raised = {n.args[0].value for n in ast.walk(tree)
              if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "_error"
              and n.args and isinstance(n.args[0], ast.Constant)}
    branch_ops = ("transfer", "insertion", "correction", "cancellation", "reconcile")
    classified = {c for op in branch_ops for _, c in ZERO_WRITE_ALLOWLIST[op]} | {c for _, c in SPECIAL_OUTCOMES}
    assert raised and raised <= classified, raised - classified
    assert not (NEVER_ALLOWLISTED_CODES & classified)
    for module in (path, REPO_ROOT / "backend" / "app" / "api" / "v1" / "branch_routes.py"):
        names = {n.id for n in ast.walk(ast.parse(module.read_text(encoding="utf-8"))) if isinstance(n, ast.Name)}
        assert "HTTPException" not in names and "require_capability" not in names, module


def test_branch_allowlists_follow_the_addendum_and_c_c1_c_c2() -> None:
    assert (409, "BRANCH_TIMELINE_AMBIGUOUS") in ZERO_WRITE_ALLOWLIST["correction"]
    assert (409, "BRANCH_TIMELINE_AMBIGUOUS") in ZERO_WRITE_ALLOWLIST["cancellation"]
    for op in ("transfer", "insertion", "correction", "cancellation", "reconcile"):
        codes = {c for _, c in ZERO_WRITE_ALLOWLIST[op]}
        assert not codes & {"REGISTRATION_DUPLICATE", "PROVINCE_NOT_FOUND", "MASTER_PAIR_INVALID",
                            "BRANCH_HISTORY_WRITE_FAILED", "BRANCH_PROJECTION_WRITE_FAILED", "REQUEST_ID_REUSED"}, op
    assert "REASON_REQUIRED" not in {c for _, c in ZERO_WRITE_ALLOWLIST["transfer"]}
    assert not {c for _, c in ZERO_WRITE_ALLOWLIST["cancellation"]} & {"BRANCH_NOT_FOUND", "EFFECTIVE_MODE_INVALID"}


# ===========================================================================
# B-OC-04 shapes and route inventory
# ===========================================================================


@pytest.mark.asyncio
async def test_b_oc_04_noop_and_replay_shapes_and_header_echo() -> None:
    repo = MockRepository()
    rid = _rid()
    noop = await post(p_reconcile(), reconcile_body(repo), repo, request_id=rid)
    assert noop.json() == {"request_id": rid, "changed": False, "warnings": []}
    assert noop.headers["X-Request-Id"] == rid
    rid2 = _rid()
    body = insertion_body(repo)
    done = await post(p_insertion(), body, repo, request_id=rid2)
    replay = await post(p_insertion(), body, repo, request_id=rid2)
    assert replay.json() == {"request_id": rid2, "replayed": True, "record_ids": [done.json()["record_id"]],
                             "consistency": "CONSISTENT"}


@pytest.mark.asyncio
async def test_exactly_five_branch_mutation_routes_and_strict_bodies() -> None:
    schema = (await _http("GET", "/openapi.json", request_id=None)).json()["paths"]
    branch = {p: set(ops) for p, ops in schema.items() if "branch" in p}
    assert branch == {
        f"{API}/branches": {"get"},
        f"{API}/vehicles/{{vehicle_id}}/branch-history": {"get"},
        f"{API}/vehicles/{{vehicle_id}}/branch-transfers": {"post"},
        f"{API}/vehicles/{{vehicle_id}}/branch-history/insertions": {"post"},
        f"{API}/vehicles/{{vehicle_id}}/branch-history/events/{{event_id}}/corrections": {"post"},
        f"{API}/vehicles/{{vehicle_id}}/branch-history/events/{{event_id}}/cancellations": {"post"},
        f"{API}/vehicles/{{vehicle_id}}/branch-projection/reconciliations": {"post"},
        f"{API}/equipment/{{equipment_id}}/branch-history": {"get"},  # R2b (read only)
        f"{API}/equipment/{{equipment_id}}/branch-assignments": {"post"},  # R2d (history-only)
        f"{API}/equipment/{{equipment_id}}/branch-history/insertions": {"post"},  # R2d (history-only)
        f"{API}/equipment/{{equipment_id}}/branch-history/events/{{event_id}}/corrections": {"post"},  # R2d
        f"{API}/equipment/{{equipment_id}}/branch-history/events/{{event_id}}/cancellations": {"post"},  # R2d
    }
    transfer = schema[f"{API}/vehicles/{{vehicle_id}}/branch-transfers"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert transfer["additionalProperties"] is False and "$defs" not in json.dumps(transfer)
    assert set(transfer["required"]) == {"to_branch_id", "effective", "expected_current_branch_id", "expected_history_revision"}
    assert transfer["properties"]["effective"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_effective_object_rejects_unknown_keys() -> None:
    repo = SpyRepository()
    body = transfer_body(MockRepository(), effective={"mode": "DATE", "date": "2026-09-15", "tz": "Asia/Bangkok"})
    response = await post(p_transfer(), body, repo)
    assert (response.status_code, _err(response)["code"]) == (422, "VALIDATION_ERROR")
    assert repo.calls == []


@pytest.mark.asyncio
async def test_registration_mutations_are_unchanged_by_7o2c() -> None:
    repo = MockRepository()
    response = await _http("PATCH", f"{API}/vehicles/VEH-1046/registration", repo=repo, json_body={
        "registration_no": "0013", "registration_province_code": "TH-21",
        "expected_registration_no": "0012", "expected_registration_province_code": "TH-21"})
    assert response.status_code == 200 and response.json()["master_write"] == "WRITTEN"
    assert vehicle_history_rows(repo._asset_branch_history, "VEH-1046") == [
        r for r in MockRepository()._asset_branch_history if r["asset_id"] == "VEH-1046"]


# ===========================================================================
# 7O2c R1 review fixes
# ===========================================================================

T3 = "2026-08-25T00:00:00+00:00"
ED = "ABH-" + "9" * 32


@pytest.mark.asyncio
async def test_r1_c_c2_source_is_the_latest_earlier_instant_even_with_an_older_tie() -> None:
    """T1: three tied events; T2: one later, unique event. Correcting a T1
    event to T3 leaves two tied at T1, but the source just before T3 is the
    T2 event, uniquely. The timeline stays ambiguous: NOT_DETERMINED, no W2."""
    repo = tie_repo([(EA, RAYONG, T1), (EB, LAEM, T1), (EC, BANGNA, T1), (ED, RAYONG, T2)], master=LAEM)
    from app.domain.branch_timeline import source_before

    timeline = _timeline(repo, "VEH-1047")
    assert timeline.status == "AMBIGUOUS_ORDER"
    t3 = datetime.fromisoformat(T3)
    assert source_before(timeline, t3, exclude_event=EA) == (RAYONG, "EVENT")
    body = correction_body(repo, "VEH-1047", to=LAEM, effective=_at("2026-08-25T00:00:00Z"))
    response = await post(p_correction("VEH-1047", EA), body, repo)
    assert response.status_code == 200, response.text
    out = response.json()
    assert (out["projection_write"], out["timeline_status_after"]) == ("NOT_DETERMINED", "AMBIGUOUS_ORDER")
    row = repo._asset_branch_history[-1]
    assert (row["record_kind"], row["event_id"]) == ("CORRECTION", EA)
    assert (row["recorded_from_branch_id"], row["recorded_from_source"]) == (RAYONG, "EVENT")
    assert repo.registry_write_log == ["W1"] and _master(repo, "VEH-1047") == LAEM


def test_r1_c_c2_source_before_rules() -> None:
    from app.domain.branch_timeline import SourceUndetermined, source_before

    tied_latest = _timeline(tie_repo([(EA, RAYONG, T0), (EB, LAEM, T1), (EC, BANGNA, T1)]), "VEH-1047")
    with pytest.raises(SourceUndetermined):  # the LATEST earlier instant is a tie
        source_before(tied_latest, datetime.fromisoformat(T2))
    assert source_before(tied_latest, datetime.fromisoformat(T2), exclude_event=EB) == (BANGNA, "EVENT")
    assert source_before(tied_latest, datetime.fromisoformat(T1)) == (RAYONG, "EVENT")  # strictly earlier only
    assert source_before(tied_latest, datetime.fromisoformat("2026-07-01T00:00:00+00:00")) == (BANGNA, "BASELINE")
    older_tie = _timeline(tie_repo([(EA, RAYONG, T0), (EB, LAEM, T0), (EC, BANGNA, T1)]), "VEH-1047")
    assert source_before(older_tie, datetime.fromisoformat(T2)) == (BANGNA, "EVENT")


def _time_only_repo(mutate=None) -> tuple[MockRepository, list[str]]:
    repo = MockRepository()
    if mutate:
        mutate(repo)
    reads: list[str] = []
    original = repo.read_branch_master_validated

    async def counted():
        reads.append("branch_master")
        return await original()

    repo.read_branch_master_validated = counted  # type: ignore[method-assign]
    return repo, reads


def _head(repo: MockRepository) -> dict[str, str]:
    return next(r for r in repo._asset_branch_history if r["assignment_id"] == H_INSERTED)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["A-unknown-code", "B-inactive-code", "E-branch-master-outage"])
async def test_r1_time_only_correction_skips_r3(case) -> None:
    def prepare(repo: MockRepository) -> None:
        if case == "A-unknown-code":
            _head(repo)["branch_id"] = "BR-RETIRED"  # historical code absent from branch_master
        elif case == "B-inactive-code":
            next(b for b in repo._branch_master if b["branch_id"] == BANGNA)["is_active"] = "FALSE"

    repo, reads = _time_only_repo(prepare)
    if case == "E-branch-master-outage":
        repo.read_branch_master_validated = _raise(RepositoryTabReadError("branch_master", "down"))  # type: ignore[method-assign]
    destination = _head(repo)["branch_id"]
    response = await post(p_correction(), correction_body(repo, to=destination, effective=_date("2026-08-22")), repo)
    assert response.status_code == 200, response.text
    assert repo._asset_branch_history[-1]["branch_id"] == destination
    assert reads == []
    assert repo.registry_write_log == ["W1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case,to,code", [("C", "BR-NOPE", "BRANCH_NOT_FOUND"), ("D", RAYONG, "BRANCH_INACTIVE")])
async def test_r1_destination_changing_correction_runs_r3(case, to, code) -> None:
    def prepare(repo: MockRepository) -> None:
        next(b for b in repo._branch_master if b["branch_id"] == RAYONG)["is_active"] = "FALSE"
        _head(repo)["branch_id"] = "BR-RETIRED"  # even from an unknown code, a NEW destination is checked

    repo, reads = _time_only_repo(prepare)
    response = await post(p_correction(), correction_body(repo, to=to, effective=_date("2026-08-22")), repo)
    assert (response.status_code, _err(response)["code"]) == (422, code)
    assert reads == ["branch_master"] and repo.registry_write_log == []
