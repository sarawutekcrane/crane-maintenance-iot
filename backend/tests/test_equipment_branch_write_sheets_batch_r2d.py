"""R2 Batch R2d — equipment responsible-branch writes over Google Sheets,
exercised with the REAL installed gspread client on the 7H2 WRITABLE FAKE
transport (`WritableBackend`): an emulation, not live Google Sheets. No
credentials, network or live workbook; the live asset_branch_history still has
the legacy 9-column header, so live UAT stays blocked. Fixtures are synthetic
and use the frozen 26-column history contract. Request counts are
fake-transport counts, not live cost.

Batch-local PROPOSED ids (fake): R2D-01/02, R2D-04, R2D-14, R2D-15, R2D-26,
R2D-28/29, R2D-31, R2D-32, plus the legacy-schema refusal and request counts.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.branch_timeline import ASSET_BRANCH_HISTORY_COLUMNS, validate_branch_row
from app.domain.equipment_branch_history import (
    equipment_history_rows,
    equipment_timeline,
)
from app.repositories.mock import MockRepository
from tests.test_equipment_branch_history_sheets_batch_r2b import EQ_TAB, _equipment_tab
from tests.test_equipment_branch_write_batch_r2d import (
    EQP,
    LAEM,
    RAYONG,
    assign_body,
    syn_assignment,
)
from tests.test_equipment_branch_write_batch_r2d import post as mock_post
from tests.test_fleet_status_summary_sheets_batch7b2 import _repo
from tests.test_vehicle_text_preservation_sheets_batch7h2 import WritableBackend

API = "/api/v1"
ABH_TAB = "asset_branch_history"
BRANCH_TAB = "branch_master"
SOURCE_TAB = "source_equipment_register"
BATCH = "SYN-R2D-BATCH"
LEGACY_HEADER = ["assignment_id", "asset_type", "asset_id", "branch_id", "start_at", "end_at", "is_test_data",
                 "test_batch_id", "note_th"]
SOURCE_HEADER = ["source_file", "source_sequence", "equipment_code", "equipment_name_th", "inspection_source_sheet",
                 "equipment_status", "responsible_branch_id", "mapping_status", "note_th"]
BRANCHES = [["BR-BANGNA-KM6", "บางนา (สังเคราะห์)", "TRUE"], ["BR-LAEM-CHABANG", "แหลมฉบัง (สังเคราะห์)", "TRUE"],
            ["BR-RAYONG", "ระยอง (สังเคราะห์)", "TRUE"]]


def _settings(context: str | None = "TEST", batch: str = BATCH) -> Settings:
    values: dict = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake-sheet-id",
                    "google_application_credentials": "fake.json", "registry_test_batch_id": batch}
    if context is not None:
        values["registry_data_context"] = context
    return Settings(**values)


def _backend(rows=(), *, history_header=None, branch_header=("branch_id", "branch_name", "is_active"),
             branches=None, with_source=True) -> WritableBackend:
    header = list(history_header or ASSET_BRANCH_HISTORY_COLUMNS)
    width = len(branch_header)
    tabs = {
        EQ_TAB: _equipment_tab(EQP, "EQP-0002"),
        ABH_TAB: [header, *([r.get(h, "") for h in header] for r in rows)],
        BRANCH_TAB: [list(branch_header), *(b[:width] for b in (branches or BRANCHES))],
    }
    if with_source:
        # Present only to prove R2d never requests it (synthetic values).
        tabs[SOURCE_TAB] = [SOURCE_HEADER, ["syn.xlsx", "1", "EC-0", "สังเคราะห์", "S", "READY", "BR-RAYONG", "M", ""]]
    return WritableBackend(copy.deepcopy(tabs))


async def _http(repo, path: str, body, *, settings: Settings | None = None, request_id: str | None = None,
                method: str = "POST"):
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
    chosen = settings or _settings()
    app.dependency_overrides[get_settings_dependency] = lambda: chosen
    headers = {"X-Dev-Role": "MAINTENANCE_MANAGER"}
    if method != "GET":
        headers["X-Request-Id"] = request_id or str(uuid.uuid4())
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers, json=body)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _table(backend: WritableBackend, tab: str) -> list[dict[str, str]]:
    head = backend.tabs[tab][0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in backend.tabs[tab][1:]]


def _writes(backend: WritableBackend) -> list[str]:
    return [w["kind"] for w in backend.write_log]


def _values_reads(backend: WritableBackend) -> list[str]:
    return [tab for _, kind, tab in backend.requests if kind == "values"]


async def _body(repo, **kw) -> dict:
    read = await repo.read_asset_branch_history_validated()
    timeline = equipment_timeline(equipment_history_rows(read.rows, EQP), context="TEST")
    body = {"to_branch_id": kw.pop("to", RAYONG), "effective": kw.pop("effective", {"mode": "DATE", "date": "2026-09-01"}),
            "expected_current_branch_id": timeline.current_branch_id,
            "expected_history_revision": timeline.revision}
    body.update(kw)
    return body


PATH = f"{API}/equipment/{EQP}/branch-assignments"


@pytest.mark.asyncio
async def test_r2d_01_02_first_assignment_appends_one_26_column_row() -> None:
    backend = _backend()
    repo = _repo(backend)
    response = await _http(repo, PATH, await _body(repo))
    assert response.status_code == 200, response.text
    assert _writes(backend) == ["append"]  # W1 only: no batchUpdate (no projection)
    (row,) = _table(backend, ABH_TAB)
    assert list(row) == list(ASSET_BRANCH_HISTORY_COLUMNS) and validate_branch_row(row) == []
    assert (row["asset_type"], row["asset_id"], row["record_kind"], row["entry_operation"]) == (
        "EQUIPMENT", EQP, "ASSIGNMENT", "TRANSFER")
    assert (row["recorded_from_source"], row["recorded_from_branch_id"], row["baseline_source"],
            row["baseline_branch_id"]) == ("NONE", "", "NONE", "")
    assert (row["is_test_data"], row["test_batch_id"]) == ("TRUE", BATCH)
    assert _table(backend, EQ_TAB) == _table(_backend(), EQ_TAB)  # equipment_master untouched


@pytest.mark.asyncio
async def test_r2d_04_request_counts_noop_and_change() -> None:
    backend = _backend()
    repo = _repo(backend)
    await _http(repo, PATH, await _body(repo))
    backend.requests.clear()
    backend.write_log.clear()
    noop = await _http(repo, PATH, await _body(repo, effective={"mode": "DATE", "date": "2026-09-05"}))
    assert noop.json()["changed"] is False
    assert sorted(_values_reads(backend)) == sorted([EQ_TAB, ABH_TAB, ABH_TAB])  # two from _body()/route; no branch
    assert BRANCH_TAB not in _values_reads(backend) and _writes(backend) == []
    backend.requests.clear()
    body = await _body(repo, to=LAEM, effective={"mode": "DATE", "date": "2026-09-10"})
    backend.requests.clear()
    changed = await _http(repo, PATH, body)
    assert changed.status_code == 200
    assert _values_reads(backend) == [EQ_TAB, ABH_TAB, BRANCH_TAB] and _writes(backend) == ["append"]


@pytest.mark.asyncio
async def test_r2d_legacy_nine_column_history_is_refused_before_any_write() -> None:
    backend = _backend(history_header=LEGACY_HEADER)
    repo = _repo(backend)
    body = {"to_branch_id": RAYONG, "effective": {"mode": "DATE", "date": "2026-09-01"},
            "expected_current_branch_id": None, "expected_history_revision": "BHR1-x"}
    response = await _http(repo, PATH, body)
    assert (response.status_code, response.json()["error"]["code"]) == (500, "BRANCH_HISTORY_SCHEMA_INVALID")
    assert response.json()["error"]["details"]["problem"] == "MISSING_HEADERS"
    assert _writes(backend) == []


@pytest.mark.asyncio
async def test_r2d_14_inactive_destination_over_sheets() -> None:
    branches = [["BR-RAYONG", "ระยอง (สังเคราะห์)", "FALSE"], ["BR-LAEM-CHABANG", "แหลมฉบัง (สังเคราะห์)", "TRUE"]]
    backend = _backend(branches=branches)
    repo = _repo(backend)
    response = await _http(repo, PATH, await _body(repo))
    assert (response.status_code, response.json()["error"]["code"]) == (422, "BRANCH_INACTIVE")
    assert _writes(backend) == []


@pytest.mark.asyncio
async def test_r2d_15_live_shape_branch_master_without_is_active() -> None:
    """The live branch_master has branch_id, branch_name only: every listed
    branch is active (frozen R1 rule); an unlisted code is still not found."""
    backend = _backend(branch_header=("branch_id", "branch_name"))
    repo = _repo(backend)
    assert (await _http(repo, PATH, await _body(repo))).status_code == 200
    missing = await _http(repo, PATH, await _body(repo, to="BR-NOWHERE", effective={"mode": "DATE", "date": "2026-09-09"}))
    assert missing.json()["error"]["code"] == "BRANCH_NOT_FOUND"


@pytest.mark.asyncio
async def test_r2d_26_source_equipment_register_is_never_requested() -> None:
    backend = _backend(with_source=True)
    repo = _repo(backend)
    await _http(repo, PATH, await _body(repo))
    assert SOURCE_TAB not in _values_reads(backend)
    assert all(w.get("tab") in (None, ABH_TAB) for w in backend.write_log)
    assert _table(backend, SOURCE_TAB) == _table(_backend(), SOURCE_TAB)


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "outcome", "applied"), [
    ("reject", "rejected", False), ("server_error", "unknown", False), ("apply_then_timeout", "unknown", True)])
async def test_r2d_28_29_append_failures_over_sheets(mode, outcome, applied) -> None:
    backend = _backend()
    repo = _repo(backend)
    body = await _body(repo)
    backend.fail["append"] = mode
    rid = str(uuid.uuid4())
    response = await _http(repo, PATH, body, request_id=rid)
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (503, "BRANCH_HISTORY_WRITE_FAILED")
    assert error["details"] == {"history_write_outcome": outcome, "request_id": rid}
    assert _writes(backend) == ["append"]  # one attempt, never retried
    assert len(_table(backend, ABH_TAB)) == (1 if applied else 0)


@pytest.mark.asyncio
async def test_r2d_31_test_context_requires_a_batch_and_a_context() -> None:
    for settings, code in ((_settings("TEST", batch=""), "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"),
                           (_settings(None), "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED")):
        backend = _backend()
        body = {"to_branch_id": RAYONG, "effective": {"mode": "DATE", "date": "2026-09-01"},
                "expected_current_branch_id": None, "expected_history_revision": "BHR1-x"}
        response = await _http(_repo(backend), PATH, body, settings=settings)
        assert (response.status_code, response.json()["error"]["code"]) == (503, code)
        assert backend.requests == [] and _writes(backend) == []


@pytest.mark.asyncio
async def test_r2d_32_real_context_cutover_safety() -> None:
    test_row = syn_assignment("ABH-" + "d" * 32, RAYONG, "2026-08-10T00:00:00+00:00", 1, first=True)
    backend = _backend([test_row])
    repo = _repo(backend)
    body = {"to_branch_id": LAEM, "effective": {"mode": "DATE", "date": "2026-09-01"},
            "expected_current_branch_id": RAYONG, "expected_history_revision": "BHR1-x"}
    response = await _http(repo, PATH, body, settings=_settings("REAL", batch=""))
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (500, "BRANCH_HISTORY_DATA_INVALID")
    assert error["details"]["issues"] == {"CUTOVER_INCOMPLETE": 1}
    assert _writes(backend) == []
    clean = _backend()
    clean_repo = _repo(clean)
    ok = await _http(clean_repo, PATH, await _body(clean_repo), settings=_settings("REAL", batch=""))
    assert ok.status_code == 200
    (row,) = _table(clean, ABH_TAB)
    assert (row["is_test_data"], row["test_batch_id"]) == ("FALSE", "")


@pytest.mark.asyncio
async def test_r2d_24_mock_and_fake_write_the_same_row_shape() -> None:
    backend = _backend()
    repo = _repo(backend)
    fake = await _http(repo, PATH, await _body(repo), settings=_settings("TEST", batch="MOCK-7O2B-SYNTHETIC"))
    mock_repo = MockRepository()
    mock = await mock_post(PATH, assign_body(mock_repo), mock_repo)
    assert fake.status_code == mock.status_code == 200
    assert {k for k in fake.json() if k not in ("request_id", "record_id", "event_id")} == {
        k for k in mock.json() if k not in ("request_id", "record_id", "event_id")}
    (fake_row,) = _table(backend, ABH_TAB)
    mock_row = equipment_history_rows(mock_repo._asset_branch_history, EQP)[0]
    volatile = {"assignment_id", "event_id", "recorded_at", "request_id", "request_fingerprint"}
    assert {k: v for k, v in fake_row.items() if k not in volatile} == {
        k: v for k, v in mock_row.items() if k not in volatile}
