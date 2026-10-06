"""R2 Batch R2b — GET /api/v1/equipment/{equipment_id}/branch-history (mock).

Test ids R2B-01..R2B-20 are batch-local PROPOSED identifiers, not owner
business codes. Every fixture is synthetic (SYN- request ids, R2B batch id,
labelled notes); no live workbook is read. The Google Sheets fake-transport
counterpart is test_equipment_branch_history_sheets_batch_r2b.py.
"""
from __future__ import annotations

import hashlib
import inspect
import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain import authz
from app.domain.branch_timeline import (
    ASSET_BRANCH_HISTORY_COLUMNS,
    derive_timeline,
    history_revision,
    vehicle_history_rows,
)
from app.domain.equipment_branch_history import (
    equipment_history_rows,
    equipment_timeline,
)
from app.repositories.base import (
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
    RepositorySchemaError,
    RepositoryTabReadError,
)
from app.repositories.mock import MockRepository

API = "/api/v1"
EQP = "EQP-0001"  # seeded mock equipment
VEH = "VEH-1046"  # seeded mock vehicle with a responsible branch
NOTE = " (ข้อมูลสังเคราะห์สำหรับทดสอบ)"
BATCH = "SYN-R2B"


# ---------------------------------------------------------------------------
# Synthetic asset_branch_history rows (the frozen R1 record model)
# ---------------------------------------------------------------------------


def rec(asset_type: str, asset_id: str, **cells: str) -> dict[str, str]:
    row = dict.fromkeys(ASSET_BRANCH_HISTORY_COLUMNS, "")
    row.update(asset_type=asset_type, asset_id=asset_id, recorded_by="syn-r2b", is_test_data="TRUE",
               test_batch_id=BATCH)
    row.update(cells)
    row["request_fingerprint"] = hashlib.sha256(f"syn-r2b:{row['request_id']}".encode()).hexdigest()
    return row


def _ids(tag: str, n: int) -> list[str]:
    return [f"ABH-SYN-{tag}-{i}" for i in range(1, n + 1)]


def transfer_insert_correct(asset_type: str, asset_id: str, tag: str, *, baseline=("", "NONE")) -> list[dict[str, str]]:
    """A transfer, a missed transfer inserted before it, then that insertion
    corrected — the R1 VEH-1046 shape with a baseline recorded as given."""
    first, inserted, corrected = _ids(tag, 3)
    base_branch, base_source = baseline
    from_source, from_branch = ("BASELINE", base_branch) if base_branch else ("NONE", "")
    common = {"effective_precision": "DATE", "effective_source": "CLIENT",
              "recorded_from_source": from_source, "recorded_from_branch_id": from_branch}
    return [
        rec(asset_type, asset_id, assignment_id=first, record_kind="ASSIGNMENT", entry_operation="TRANSFER",
            event_id=first, revision_no="1", branch_id="BR-LAEM-CHABANG", start_at="2026-08-31T17:00:00+00:00",
            baseline_branch_id=base_branch, baseline_source=base_source, recorded_at="2026-09-02T03:00:00+00:00",
            request_id=f"syn-{tag}-1", note_th="ย้ายสาขา" + NOTE, **common),
        rec(asset_type, asset_id, assignment_id=inserted, record_kind="ASSIGNMENT", entry_operation="INSERTION",
            event_id=inserted, revision_no="1", branch_id="BR-BANGNA-KM6", start_at="2026-08-14T17:00:00+00:00",
            recorded_at="2026-09-03T03:00:00+00:00", request_id=f"syn-{tag}-2", note_th="บันทึกย้อนหลัง" + NOTE,
            **common),
        rec(asset_type, asset_id, assignment_id=corrected, record_kind="CORRECTION", entry_operation="CORRECTION",
            event_id=inserted, revision_no="2", supersedes_record_id=inserted, branch_id="BR-BANGNA-KM6",
            start_at="2026-08-19T17:00:00+00:00", recorded_at="2026-09-04T03:00:00+00:00",
            request_id=f"syn-{tag}-3", note_th="แก้วันที่มีผล" + NOTE, **common),
    ]


def assigned_then_cancelled(asset_type: str, asset_id: str, tag: str, *, baseline=("", "NONE")) -> list[dict[str, str]]:
    assigned, cancelled = _ids(tag, 2)
    base_branch, base_source = baseline
    from_source, from_branch = ("BASELINE", base_branch) if base_branch else ("NONE", "")
    return [
        rec(asset_type, asset_id, assignment_id=assigned, record_kind="ASSIGNMENT", entry_operation="TRANSFER",
            event_id=assigned, revision_no="1", branch_id="BR-RAYONG", start_at="2026-09-09T17:00:00+00:00",
            effective_precision="DATE", effective_source="CLIENT", recorded_from_source=from_source,
            recorded_from_branch_id=from_branch, baseline_branch_id=base_branch, baseline_source=base_source,
            recorded_at="2026-09-10T03:00:00+00:00", request_id=f"syn-{tag}-1"),
        rec(asset_type, asset_id, assignment_id=cancelled, record_kind="CANCELLATION", entry_operation="CANCELLATION",
            event_id=assigned, revision_no="2", supersedes_record_id=assigned, recorded_at="2026-09-11T03:00:00+00:00",
            request_id=f"syn-{tag}-2", note_th="บันทึกผิดเครื่อง" + NOTE),
    ]


def same_instant(asset_type: str, asset_id: str, tag: str) -> list[dict[str, str]]:
    a, b = _ids(tag, 2)
    common = {"record_kind": "ASSIGNMENT", "revision_no": "1", "start_at": "2026-09-01T00:00:00+00:00",
              "effective_precision": "DATETIME", "effective_source": "CLIENT"}
    return [
        rec(asset_type, asset_id, assignment_id=a, event_id=a, entry_operation="TRANSFER", branch_id="BR-RAYONG",
            recorded_from_source="NONE", baseline_source="NONE", recorded_at="2026-09-02T00:00:00+00:00",
            request_id=f"syn-{tag}-1", **common),
        rec(asset_type, asset_id, assignment_id=b, event_id=b, entry_operation="TRANSFER", branch_id="BR-BANGNA-KM6",
            recorded_from_source="EVENT", recorded_from_branch_id="BR-RAYONG",
            recorded_at="2026-09-03T00:00:00+00:00", request_id=f"syn-{tag}-2", **common),
    ]


# ---------------------------------------------------------------------------
# Repository spy and HTTP helper
# ---------------------------------------------------------------------------


class Spy(MockRepository):
    """MockRepository with replaceable asset_branch_history rows, optional
    injected failures, and a log of every public repository coroutine called
    from outside the repository (nested internal calls are not logged)."""

    def __init__(self, rows=None, *, fail=None) -> None:
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "_depth", [0])
        super().__init__()
        if rows is not None:
            self._asset_branch_history = rows
        self.fail = fail or {}

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        if not name.startswith("_") and inspect.iscoroutinefunction(attr):
            calls = object.__getattribute__(self, "calls")
            fail = object.__getattribute__(self, "fail")
            depth = object.__getattribute__(self, "_depth")

            async def wrapper(*args, **kwargs):
                if depth[0] == 0:
                    calls.append(name)
                if name in fail:
                    raise fail[name]
                depth[0] += 1
                try:
                    return await attr(*args, **kwargs)
                finally:
                    depth[0] -= 1

            return wrapper
        return attr


async def get(path: str, repo, *, role: str | None = None, settings: Settings | None = None):
    from app.config import get_settings
    from app.dependencies import (
        get_repository,
        get_settings_dependency,
        reset_dependency_cache,
    )
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    if settings is not None:
        app.dependency_overrides[get_settings_dependency] = lambda: settings
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers={"X-Dev-Role": role} if role else None)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def eq_path(equipment_id: str = EQP) -> str:
    return f"{API}/equipment/{equipment_id}/branch-history"


def error(response) -> dict:
    return response.json()["error"]


NOT_IN_SCHEMA = {"state": "NOT_IN_SCHEMA", "value": None}


# ---------------------------------------------------------------------------
# R2B-01 / R2B-02 — Option C envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2b_01_valid_equipment_history() -> None:
    rows = transfer_insert_correct("EQUIPMENT", EQP, "E1")
    repo = Spy(rows)
    response = await get(eq_path(), repo)
    assert response.status_code == 200
    body = response.json()
    assert body["asset_type"] == "EQUIPMENT" and body["asset_id"] == EQP
    assert body["timeline_status"] == "VALID"
    assert body["current"] == {"branch_id": "BR-LAEM-CHABANG", "source": "EVENT"}
    assert body["master"] == NOT_IN_SCHEMA
    assert body["consistency"] == "UNDETERMINED"
    assert body["history_revision"] == history_revision(rows)
    assert body["baseline"] == {"branch_id": None, "source": "NONE"}
    assert [e["event_id"] for e in body["events"]] == ["ABH-SYN-E1-2", "ABH-SYN-E1-1"]
    assert [r["record_id"] for r in body["records"]] == ["ABH-SYN-E1-1", "ABH-SYN-E1-2", "ABH-SYN-E1-3"]
    assert body["excluded_test_rows"] == 0 and body["issues"] == {}
    assert repo.calls == ["get_equipment_validated", "read_asset_branch_history_validated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], transfer_insert_correct("VEHICLE", EQP, "V-SAME-ID")],
                         ids=["empty-table", "only-vehicle-rows-with-the-same-id"])
async def test_r2b_02_no_history_is_undetermined_never_none(rows) -> None:
    response = await get(eq_path(), Spy(rows))
    assert response.status_code == 200
    body = response.json()
    assert body["current"] == {"branch_id": None, "source": "UNDETERMINED"}
    assert body["current"]["source"] != "NONE"
    assert body["consistency"] == "NO_HISTORY"
    assert body["master"] == NOT_IN_SCHEMA
    assert body["timeline_status"] == "VALID"
    assert body["baseline"] is None and body["events"] == [] and body["records"] == []
    assert body["history_revision"] == history_revision([])


def test_r2b_02_adapter_changes_only_the_no_history_current() -> None:
    """The frozen derivation is reused; only no-history current is adapted."""
    r1 = derive_timeline([], master_branch_id=None, master_available=False, context="TEST")
    assert (r1.current_branch_id, r1.current_source, r1.consistency) == (None, "NONE", "NO_HISTORY")
    adapted = equipment_timeline([], context="TEST")
    assert (adapted.current_branch_id, adapted.current_source, adapted.consistency) == (None, "UNDETERMINED", "NO_HISTORY")
    assert adapted.revision == r1.revision and adapted.status == r1.status
    rows = transfer_insert_correct("EQUIPMENT", EQP, "E1")
    assert equipment_timeline(rows, context="TEST") == derive_timeline(
        rows, master_branch_id=None, master_available=False, context="TEST")


# ---------------------------------------------------------------------------
# R2B-03 / R2B-04 / R2B-15 — lookup and history failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (RepositoryIdentityAmbiguousError("equipment_master", 2), 409, "EQUIPMENT_ID_AMBIGUOUS"),
        (RepositorySchemaError("equipment_master", "MISSING_HEADERS", ("equipment_status",)), 500,
         "EQUIPMENT_MASTER_SCHEMA_INVALID"),
        (RepositoryRecordInvalidError("equipment_master", "UNRECOGNIZED_CATEGORY"), 500,
         "EQUIPMENT_MASTER_DATA_INVALID"),
        (RepositoryTabReadError("equipment_master", "down"), 503, "EQUIPMENT_MASTER_READ_FAILED"),
    ],
)
async def test_r2b_03_equipment_lookup_errors_stop_before_history(failure, status, code) -> None:
    repo = Spy(transfer_insert_correct("EQUIPMENT", EQP, "E1"), fail={"get_equipment_validated": failure})
    response = await get(eq_path(), repo)
    assert response.status_code == status and error(response)["code"] == code
    assert repo.calls == ["get_equipment_validated"]  # history never read
    if code == "EQUIPMENT_ID_AMBIGUOUS":
        assert error(response)["details"] == {"match_count": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("equipment_id", ["EQP-9999", "eqp-0001", " EQP-0001", "EQP-0001 "])
async def test_r2b_03_unknown_or_non_exact_equipment_id_is_404(equipment_id) -> None:
    repo = Spy(transfer_insert_correct("EQUIPMENT", EQP, "E1"))
    response = await get(eq_path(equipment_id), repo)
    assert response.status_code == 404 and error(response)["code"] == "EQUIPMENT_NOT_FOUND"
    assert "read_asset_branch_history_validated" not in repo.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (RepositorySchemaError("asset_branch_history", "MISSING_HEADERS", ("record_kind",)), 500,
         "BRANCH_HISTORY_SCHEMA_INVALID"),
        (RepositorySchemaError("asset_branch_history", "TAB_MISSING"), 500, "BRANCH_HISTORY_SCHEMA_INVALID"),
        (RepositoryTabReadError("asset_branch_history", "down"), 503, "BRANCH_HISTORY_READ_FAILED"),
    ],
)
async def test_r2b_04_r2b_15_history_failure_is_coded_never_empty(failure, status, code) -> None:
    repo = Spy([], fail={"read_asset_branch_history_validated": failure})
    response = await get(eq_path(), repo)
    assert response.status_code == status and error(response)["code"] == code
    assert error(response)["details"]["tab"] == "asset_branch_history"
    assert "events" not in response.text and "records" not in response.text


# ---------------------------------------------------------------------------
# R2B-05..R2B-07 — asset isolation and the equipment selector
# ---------------------------------------------------------------------------


MIXED = [
    *transfer_insert_correct("VEHICLE", VEH, "V1", baseline=("BR-RAYONG", "IMPORTED_MASTER")),
    *transfer_insert_correct("EQUIPMENT", EQP, "E1"),
    *transfer_insert_correct("EQUIPMENT", VEH, "E-SAME-ID-AS-VEHICLE"),
    *transfer_insert_correct("VEHICLE", EQP, "V-SAME-ID-AS-EQUIPMENT"),
    *assigned_then_cancelled("EQUIPMENT", "EQP-0002", "E2"),
]


@pytest.mark.asyncio
async def test_r2b_05_vehicle_route_still_excludes_equipment_rows() -> None:
    response = await get(f"{API}/vehicles/{VEH}/branch-history", Spy(MIXED))
    assert response.status_code == 200
    body = response.json()
    assert body["asset_type"] == "VEHICLE"
    assert [r["record_id"] for r in body["records"]] == _ids("V1", 3)
    assert body["history_revision"] == history_revision(vehicle_history_rows(MIXED, VEH))


@pytest.mark.asyncio
async def test_r2b_06_equipment_route_excludes_vehicle_rows() -> None:
    response = await get(eq_path(), Spy(MIXED))
    assert response.status_code == 200
    body = response.json()
    assert [r["record_id"] for r in body["records"]] == _ids("E1", 3)
    assert body["history_revision"] == history_revision(equipment_history_rows(MIXED, EQP))


def test_r2b_06_selector_semantics() -> None:
    rows = [
        rec("EQUIPMENT", EQP, assignment_id="a", request_id="1"),
        rec("VEHICLE", EQP, assignment_id="b", request_id="2"),
        rec("", EQP, assignment_id="c", request_id="3"),
        rec("equipment", EQP, assignment_id="d", request_id="4"),
        rec("EQUIPMENT", "eqp-0001", assignment_id="e", request_id="5"),
        rec("EQUIPMENT", " EQP-0001", assignment_id="f", request_id="6"),
        rec("EQUIPMENT", "EQP-0002", assignment_id="g", request_id="7"),
    ]
    assert [r["assignment_id"] for r in equipment_history_rows(rows, EQP)] == ["a", "c", "d"]
    # The vehicle selector is the mirror image (unchanged).
    assert [r["assignment_id"] for r in vehicle_history_rows(rows, EQP)] == ["b", "c", "d"]


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", ["", "equipment", "Equipment", "MACHINE", " EQUIPMENT"])
async def test_r2b_07_malformed_asset_type_for_the_target_is_surfaced(asset_type) -> None:
    rows = transfer_insert_correct("EQUIPMENT", EQP, "E1")
    rows[1]["asset_type"] = asset_type
    response = await get(eq_path(), Spy(rows))
    assert response.status_code == 500
    assert error(response)["code"] == "BRANCH_HISTORY_DATA_INVALID"
    expected = {"ASSET_TYPE_INVALID": 1, **({"FIELD_REQUIRED:asset_type": 1} if not asset_type else {})}
    assert error(response)["details"] == {"tab": "asset_branch_history", "issues": expected}


# ---------------------------------------------------------------------------
# R2B-08..R2B-12 — frozen timeline semantics through the equipment route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2b_08_correction_and_cancellation_follow_the_frozen_timeline() -> None:
    rows = [*transfer_insert_correct("EQUIPMENT", EQP, "E1"), *assigned_then_cancelled("EQUIPMENT", "EQP-0002", "E2")]
    corrected = (await get(eq_path(), Spy(rows))).json()
    inserted = next(e for e in corrected["events"] if e["event_id"] == "ABH-SYN-E1-2")
    assert inserted["revision_no"] == 2 and inserted["head_record_id"] == "ABH-SYN-E1-3"
    assert inserted["effective_at"] == "2026-08-19T17:00:00+00:00"  # corrected value in force
    assert inserted["derived_end_at"] == "2026-08-31T17:00:00+00:00"
    cancelled = (await get(eq_path("EQP-0002"), Spy(rows))).json()
    assert cancelled["events"][0]["in_force"] is False and cancelled["events"][0]["notes"] == ["CANCELLED"]
    expected = derive_timeline(equipment_history_rows(rows, EQP), master_branch_id=None, master_available=False,
                               context="TEST")
    assert [e["event_id"] for e in corrected["events"]] == [e.event_id for e in expected.events]
    assert [e["derived_from_branch_id"] for e in corrected["events"]] == [e.derived_from_branch_id for e in expected.events]


@pytest.mark.asyncio
async def test_r2b_09_same_instant_is_ambiguous_and_undetermined() -> None:
    body = (await get(eq_path(), Spy(same_instant("EQUIPMENT", EQP, "E3")))).json()
    assert body["timeline_status"] == "AMBIGUOUS_ORDER"
    assert body["current"] == {"branch_id": None, "source": "UNDETERMINED"}
    assert body["consistency"] == "UNDETERMINED"
    assert all("SAME_INSTANT" in e["notes"] for e in body["events"])


@pytest.mark.asyncio
async def test_r2b_10_all_cancelled_derives_only_from_the_recorded_baseline() -> None:
    none_baseline = (await get(eq_path(), Spy(assigned_then_cancelled("EQUIPMENT", EQP, "E4")))).json()
    assert none_baseline["current"] == {"branch_id": None, "source": "NONE"}  # stated by the recorded baseline
    assert none_baseline["baseline"] == {"branch_id": None, "source": "NONE"}
    recorded = assigned_then_cancelled("EQUIPMENT", EQP, "E5", baseline=("BR-BANGNA-KM6", "IMPORTED_MASTER"))
    body = (await get(eq_path(), Spy(recorded))).json()
    assert body["current"] == {"branch_id": "BR-BANGNA-KM6", "source": "BASELINE"}
    assert body["baseline"] == {"branch_id": "BR-BANGNA-KM6", "source": "IMPORTED_MASTER"}  # read as recorded
    for result in (none_baseline, body):
        assert result["master"] == NOT_IN_SCHEMA and result["consistency"] == "UNDETERMINED"


@pytest.mark.asyncio
async def test_r2b_11_test_and_real_contexts() -> None:
    rows = transfer_insert_correct("EQUIPMENT", EQP, "E1")
    sheets = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake",
              "google_application_credentials": "fake.json"}
    # Unset context in google_sheets mode: 503 before any repository read.
    repo = Spy(rows)
    unset = await get(eq_path(), repo, settings=Settings(**sheets))
    assert unset.status_code == 503 and error(unset)["code"] == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert repo.calls == []
    # REAL: TRUE (test) rows fail closed as in R1.
    real = await get(eq_path(), Spy(rows), settings=Settings(**sheets, registry_data_context="REAL"))
    assert real.status_code == 500
    assert error(real)["details"]["issues"] == {"CUTOVER_INCOMPLETE": 3}
    for row in rows:
        row["is_test_data"] = "FALSE"
    clean = await get(eq_path(), Spy(rows), settings=Settings(**sheets, registry_data_context="REAL"))
    assert clean.status_code == 200 and clean.json()["current"]["source"] == "EVENT"
    test = await get(eq_path(), Spy(rows), settings=Settings(**sheets, registry_data_context="TEST"))
    assert test.status_code == 200 and test.json()["excluded_test_rows"] == 0


@pytest.mark.asyncio
async def test_r2b_12_bhr1_revision_is_stable_and_scoped_to_this_equipment() -> None:
    own = transfer_insert_correct("EQUIPMENT", EQP, "E1")
    alone = (await get(eq_path(), Spy(own))).json()["history_revision"]
    mixed = (await get(eq_path(), Spy(MIXED))).json()["history_revision"]
    reordered = (await get(eq_path(), Spy(list(reversed(MIXED))))).json()["history_revision"]
    assert alone == mixed == reordered == history_revision(own)
    assert alone.startswith("BHR1-")
    edited = [dict(r) for r in own]
    edited[0]["note_th"] = "แก้ไขด้วยมือ" + NOTE
    assert (await get(eq_path(), Spy(edited))).json()["history_revision"] != alone


# ---------------------------------------------------------------------------
# R2B-13 / R2B-16 / R2B-17 — reads, writes, permission (R2B-19: sheets file)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2b_13_no_branch_master_read_even_when_it_would_fail() -> None:
    repo = Spy(transfer_insert_correct("EQUIPMENT", EQP, "E1"),
               fail={"read_branch_master_validated": RepositoryTabReadError("branch_master", "down")})
    response = await get(eq_path(), repo)
    assert response.status_code == 200
    assert response.json()["current"]["branch_id"] == "BR-LAEM-CHABANG"  # stable id, no label lookup
    assert "read_branch_master_validated" not in repo.calls


@pytest.mark.asyncio
async def test_r2b_16_only_two_reads_and_no_writes() -> None:
    repo = Spy(transfer_insert_correct("EQUIPMENT", EQP, "E1"))
    before = list(repo._asset_branch_history)
    assert (await get(eq_path(), repo)).status_code == 200
    assert repo.calls == ["get_equipment_validated", "read_asset_branch_history_validated"]
    assert repo._asset_branch_history == before


@pytest.mark.asyncio
async def test_r2b_17_can_view_is_required_with_zero_reads() -> None:
    """The route enforces can_view: a caller without it gets 403 with zero
    repository reads; explicit callers that hold it succeed. Other (future)
    roles are not constrained here."""
    repo = Spy(transfer_insert_correct("EQUIPMENT", EQP, "E1"))
    response = await get(eq_path(), repo, role="NO_SUCH_ROLE")  # holds no capability (fails closed)
    assert response.status_code == 403 and error(response)["code"] == "HTTP_ERROR"
    assert repo.calls == []
    for role in ("ADMIN", "MAINTENANCE_MANAGER"):  # explicit callers holding can_view
        assert authz.CAN_VIEW in authz.capabilities_for_roles((role,))
        allowed = Spy(transfer_insert_correct("EQUIPMENT", EQP, "E1"))
        ok = await get(eq_path(), allowed, role=role)
        assert ok.status_code == 200 and ok.json()["asset_id"] == EQP
        assert allowed.calls == ["get_equipment_validated", "read_asset_branch_history_validated"]


# ---------------------------------------------------------------------------
# R2B-18 — serialization parity with the frozen vehicle route
# ---------------------------------------------------------------------------


SCENARIOS = {
    "transfer-insert-correct": transfer_insert_correct,
    "assigned-then-cancelled": assigned_then_cancelled,
    "same-instant": same_instant,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("baseline", [("", "NONE"), ("BR-RAYONG", "IMPORTED_MASTER")], ids=["none", "imported"])
async def test_r2b_18_serialization_matches_the_vehicle_route(scenario, baseline) -> None:
    build = SCENARIOS[scenario]
    vehicle_rows = build("VEHICLE", VEH, "P", baseline=baseline) if scenario != "same-instant" else build("VEHICLE", VEH, "P")
    equipment_rows = [{**r, "asset_type": "EQUIPMENT", "asset_id": EQP} for r in vehicle_rows]
    repo_rows = [*vehicle_rows, *equipment_rows]
    vehicle = (await get(f"{API}/vehicles/{VEH}/branch-history", Spy(repo_rows))).json()
    equipment = (await get(eq_path(), Spy(repo_rows))).json()
    for key in ("timeline_status", "baseline", "events", "records", "excluded_test_rows", "issues"):
        assert equipment[key] == vehicle[key], key
    assert vehicle["history_revision"] == history_revision(vehicle_rows)
    assert equipment["history_revision"] == history_revision(equipment_rows)
    # The only wrapper differences:
    assert (vehicle["asset_type"], equipment["asset_type"]) == ("VEHICLE", "EQUIPMENT")
    assert equipment["master"] == NOT_IN_SCHEMA and vehicle["master"]["state"] == "RECORDED"
    assert equipment["consistency"] == "UNDETERMINED"
    assert equipment["current"]["source"] == vehicle["current"]["source"]  # history-derived either way


# ---------------------------------------------------------------------------
# R2B-20 — permanent guardrails: the R2b GET and response contract, the frozen
# vehicle GET/response and the frozen R1 capability memberships. Candidate-only
# absence facts (no equipment branch mutation route or capability today) are
# review evidence in the result document, not tests: R2d may add them.
# ---------------------------------------------------------------------------


def _routes() -> set[tuple[str, str]]:
    from app.main import create_app

    spec = create_app().openapi()
    return {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}


# The equipment master resources themselves (deactivate rather than delete).
EQUIPMENT_MASTER_RESOURCE = re.compile(r"^/api/v1/equipment(/\{[^/]+\})?$")


def test_r2b_20_route_and_capability_guardrails() -> None:
    routes = _routes()
    assert ("GET", "/api/v1/equipment/{equipment_id}/branch-history") in routes
    assert ("GET", "/api/v1/vehicles/{vehicle_id}/branch-history") in routes
    assert [r for r in routes if r[0] == "DELETE" and EQUIPMENT_MASTER_RESOURCE.match(r[1])] == []
    for capability in ("can_edit_vehicle_registration", "can_transfer_vehicle_branch", "can_correct_branch_history"):
        holders = {role for role, caps in authz.ROLE_CAPABILITIES.items() if capability in caps}
        assert holders == {"ADMIN", "MAINTENANCE_MANAGER"}, capability


def test_r2b_20_vehicle_response_contract_is_not_widened() -> None:
    from app.main import create_app

    schemas = create_app().openapi()["components"]["schemas"]
    assert schemas["BranchHistoryResponse"]["properties"]["asset_type"] == {
        "type": "string", "const": "VEHICLE", "title": "Asset Type"}
    equipment = schemas["EquipmentBranchHistoryResponse"]["properties"]
    assert equipment["asset_type"]["const"] == "EQUIPMENT"
    assert equipment["consistency"]["enum"] == ["NO_HISTORY", "UNDETERMINED"]
