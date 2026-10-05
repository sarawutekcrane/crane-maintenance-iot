"""Phase 7 Batch 7O2a — registry reads over Google Sheets, exercised with the
REAL installed gspread client on the 7B2 FAKE HTTP transport
(`FakeSheetsBackend`): an emulation, not live Google Sheets. No credentials,
no network, no live workbook; request counts are fake-transport counts, not a
claim about live latency or quota. Every fixture is synthetic.

Acceptance rows: R-01 (all 8 column combinations, list + detail + dashboard),
R-02 (numeric-looking text; legacy callers), R-04 (missing branch column),
R-06/R-07 (history tabs: missing tab/header, reorder), R-12 (mock/fake
parity), plus cold/warm request counts and zero writes for every new GET.
"""
from __future__ import annotations

import itertools

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DataRepositoryMode, Settings
from app.domain.branch_timeline import ASSET_BRANCH_HISTORY_COLUMNS
from app.domain.common import PageParams
from app.domain.registration import REGISTRATION_HISTORY_COLUMNS
from app.domain.vehicle_registry import REGISTRY_COLUMNS
from app.domain.vehicle_service import VehicleService
from app.repositories.google_sheets import schemas
from app.repositories.mock import MockRepository, seed_data
from tests.test_fleet_status_summary_sheets_batch7b2 import (
    HEADER,
    TS,
    VEHICLE_TAB,
    FakeSheetsBackend,
    _repo,
    _row,
)

API = "/api/v1"
REG, PROV, BRANCH = REGISTRY_COLUMNS
BRANCH_TAB, PROVINCE_TAB = "branch_master", "province_master"
ABH_TAB, VRH_TAB = "asset_branch_history", "vehicle_registration_history"
ALL_COMBOS = [combo for n in range(4) for combo in itertools.combinations(REGISTRY_COLUMNS, n)]


def _settings(context: str | None = "TEST") -> Settings:
    values = {"data_repository": DataRepositoryMode.GOOGLE_SHEETS, "google_sheet_id": "fake-sheet-id",
              "google_application_credentials": "fake.json"}
    if context:
        values["registry_data_context"] = context
    return Settings(**values)


async def _http(repo, path: str, params=None, settings: Settings | None = None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_settings_dependency] = lambda: settings or _settings()
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, params=params)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _table(header: list[str], rows: list[dict[str, str]]) -> list[list[str]]:
    return [list(header), *([row.get(h, "") for h in header] for row in rows)]


def _vehicle_tab(rows: list[tuple[list[str], dict[str, str]]], columns: tuple[str, ...]) -> list[list[str]]:
    """7 canonical cells + the named registry columns (appended)."""
    header = [*HEADER, *columns]
    return [header, *([*base, *(registry.get(c, "") for c in columns)] for base, registry in rows)]


def _detail_tabs() -> dict[str, list[list[str]]]:
    """model_master / maintenance_plan / vehicle_component so the full detail page reads."""
    model_header = list(schemas.VEHICLE_MODEL_SHEET.required_headers)
    cells = dict.fromkeys(model_header, "")
    cells.update(model_id="MDL-1", model_code="QY", model_name="Model", component_roles="CARRIER_ENGINE",
                 created_at=TS, updated_at=TS)
    return {
        "model_master": [model_header, [cells[h] for h in model_header]],
        "maintenance_plan": [list(schemas.PM_PLAN_SHEET.required_headers)],
        "vehicle_component": [list(schemas.VEHICLE_COMPONENT_SHEET.required_headers)],
    }


ROWS = [
    (_row("VEH-1", "WORKING"), {REG: "0012", PROV: "TH-21", BRANCH: "BR-TEST-A"}),
    (_row("VEH-2", "READY"), {REG: "1,234", PROV: "", BRANCH: "BR-TEST-B"}),
    (_row("VEH-3", "MAINTENANCE"), {REG: "", PROV: "", BRANCH: ""}),
    (_row("VEH-4", "WORKING"), {REG: "  ", PROV: "10", BRANCH: "007"}),
]


# ---------------------------------------------------------------------------
# R-01 — the eight column combinations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("columns", ALL_COMBOS, ids=lambda c: "+".join(c) or "seven-only")
async def test_r01_each_column_combination_list_detail_filter_dashboard(columns) -> None:
    backend = FakeSheetsBackend({VEHICLE_TAB: _vehicle_tab(ROWS, columns), **_detail_tabs()})
    repo = _repo(backend)
    listed = await _http(repo, f"{API}/vehicles")
    assert listed.status_code == 200
    items = {i["vehicle_id"]: i["registry"] for i in listed.json()["items"]}
    assert listed.json()["total_items"] == 4
    for field, column in zip(("registration_no", "registration_province", "responsible_branch"), REGISTRY_COLUMNS):
        expected_states = (
            ["NOT_IN_SCHEMA"] * 4 if column not in columns
            else ["RECORDED" if ROWS[i][1][column].strip() else "NOT_RECORDED" for i in range(4)]
        )
        assert [items[f"VEH-{i + 1}"][field]["state"] for i in range(4)] == expected_states, (columns, field)
    if REG in columns:
        assert items["VEH-1"]["registration_no"]["value"] == "0012"
        assert items["VEH-2"]["registration_no"]["value"] == "1,234"
    if BRANCH in columns:
        assert items["VEH-4"]["responsible_branch"]["value"] == "007"
    for index in range(4):
        detail = await _http(repo, f"{API}/vehicles/VEH-{index + 1}")
        assert detail.status_code == 200
        assert detail.json()["vehicle"]["registry"] == items[f"VEH-{index + 1}"]  # detail == list item
    filtered = await _http(repo, f"{API}/vehicles", params={"branch_id": "BR-TEST-A"})
    if BRANCH in columns:
        assert filtered.status_code == 200
        assert [i["vehicle_id"] for i in filtered.json()["items"]] == ["VEH-1"]
    else:
        assert filtered.status_code == 409
        assert filtered.json()["error"]["code"] == "VEHICLE_BRANCH_FILTER_UNAVAILABLE"
    dashboard = (await _http(repo, f"{API}/dashboard/fleet-status")).json()
    assert dashboard["vehicle_total"] == 4
    assert dashboard["status_counts"] == {"WORKING": 2, "READY": 1, "MAINTENANCE": 1, "OUT_OF_SERVICE": 0, "LONG_TERM_PARKING": 0}
    assert backend.writes == []


@pytest.mark.asyncio
async def test_r01_seven_column_sheet_detail_is_complete() -> None:
    """An old seven-column vehicle_master keeps the full detail page working."""
    backend = FakeSheetsBackend({VEHICLE_TAB: [HEADER, _row("VEH-1")], **_detail_tabs()})
    response = await _http(_repo(backend), f"{API}/vehicles/VEH-1")
    assert response.status_code == 200
    assert response.json()["vehicle"]["registry"] == {
        "registration_no": {"state": "NOT_IN_SCHEMA", "value": None},
        "registration_province": {"state": "NOT_IN_SCHEMA", "value": None},
        "responsible_branch": {"state": "NOT_IN_SCHEMA", "value": None},
    }
    assert backend.writes == []


# ---------------------------------------------------------------------------
# R-02 — numeric-looking text; registry never gates; legacy callers unchanged
# ---------------------------------------------------------------------------

ODD = ["0012", "1,234", "1e3", "00", "12.50", "-0", "=1+1", "#N/A", "TRUE", " 0012 ", "๑๒๓", "x" * 300]


@pytest.mark.asyncio
async def test_r02_numeric_looking_and_odd_registry_text_is_exact_and_never_gates() -> None:
    rows = [(_row(f"VEH-{i:02d}"), {REG: value, PROV: value, BRANCH: value}) for i, value in enumerate(ODD)]
    backend = FakeSheetsBackend({VEHICLE_TAB: _vehicle_tab(rows, REGISTRY_COLUMNS)})
    repo = _repo(backend)
    listed = (await _http(repo, f"{API}/vehicles", params={"page_size": 50})).json()
    got = {i["vehicle_id"]: i["registry"]["registration_no"]["value"] for i in listed["items"]}
    assert got == {f"VEH-{i:02d}": value for i, value in enumerate(ODD)}
    for i, value in enumerate(ODD):
        located = await repo.get_vehicle_with_registry_validated(f"VEH-{i:02d}")
        assert located.registry.responsible_branch.value == value
    assert (await _http(repo, f"{API}/vehicles", params={"branch_id": "0012"})).json()["total_items"] == 1
    assert (await _http(repo, f"{API}/vehicles", params={"branch_id": "12"})).json()["total_items"] == 0
    assert (await _http(repo, f"{API}/dashboard/fleet-status")).json()["vehicle_total"] == len(ODD)


@pytest.mark.asyncio
async def test_r02_legacy_reads_on_the_same_tab_are_unchanged() -> None:
    rows = [(_row("VEH-1", machine="TC-1"), {REG: "0012", PROV: "21", BRANCH: "007"})]
    plain = _repo(FakeSheetsBackend({VEHICLE_TAB: _vehicle_tab(rows, ())}))
    wide = _repo(FakeSheetsBackend({VEHICLE_TAB: _vehicle_tab(rows, REGISTRY_COLUMNS)}))
    for repo in (plain, wide):
        items, total = await repo.list_vehicles(q=None, operational_status=None, model_id=None, params=PageParams())
        assert total == 1 and items[0].machine_no == "TC-1"
        assert (await repo.get_vehicle("VEH-1")).vehicle_id == "VEH-1"
        assert (await repo.get_vehicle_validated("VEH-1")).machine_no == "TC-1"
    assert (await plain.list_vehicles(None, None, None, PageParams()))[0] == (await wide.list_vehicles(None, None, None, PageParams()))[0]


@pytest.mark.asyncio
async def test_r02_phantom_rule_ignores_registry_only_rows() -> None:
    rows = [*ROWS, (["", "", "", "", "", "", ""], {REG: "9999", PROV: "TH-10", BRANCH: "BR-TEST-A"})]
    repo = _repo(FakeSheetsBackend({VEHICLE_TAB: _vehicle_tab(rows, REGISTRY_COLUMNS)}))
    assert (await _http(repo, f"{API}/vehicles")).json()["total_items"] == 4
    assert (await _http(repo, f"{API}/vehicles", params={"branch_id": "BR-TEST-A"})).json()["total_items"] == 1
    assert (await _http(repo, f"{API}/dashboard/fleet-status")).json()["vehicle_total"] == 4


INVALID_POPULATIONS = {
    "blank_status": [*ROWS, (_row("VEH-9", ""), {})],
    "bad_status": [*ROWS, (_row("VEH-9", "FIXING"), {})],
    "fallback_time": [*ROWS, (_row("VEH-9", created="yesterday"), {})],
    "duplicate_id": [*ROWS, (_row("VEH-1"), {})],
    "blank_id": [*ROWS, (_row(""), {REG: "0012"})],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("label", sorted(INVALID_POPULATIONS))
async def test_r12_registry_read_gates_equal_summary_read(label: str) -> None:
    backend = FakeSheetsBackend({VEHICLE_TAB: _vehicle_tab(INVALID_POPULATIONS[label], REGISTRY_COLUMNS)})
    repo = _repo(backend)
    summary = await repo.read_vehicle_master_for_summary()
    registry = await repo.read_vehicle_master_with_registry()
    assert registry.vehicles == summary.vehicles
    assert (registry.issue_counts, registry.issue_vehicle_ids) == (summary.issue_counts, summary.issue_vehicle_ids)
    assert len(registry.registries) == len(registry.vehicles)
    listed = await _http(repo, f"{API}/vehicles", params={"branch_id": "BR-TEST-A"})
    dashboard = await _http(repo, f"{API}/dashboard/fleet-status")
    if label == "fallback_time":  # the unchanged legacy mapper's epoch fallback: valid on both paths
        assert listed.status_code == dashboard.status_code == 200
        assert dashboard.json()["vehicle_total"] == 5
        return
    assert listed.status_code == dashboard.status_code == 500
    assert listed.json()["error"]["code"] == dashboard.json()["error"]["code"] == "VEHICLE_MASTER_DATA_INVALID"
    assert listed.json()["error"]["details"]["issue_counts"] == dashboard.json()["error"]["details"]["issue_counts"]
    assert "sample_vehicle_ids" not in listed.json()["error"]["details"]


@pytest.mark.asyncio
async def test_list_read_failure_maps_exactly_as_today() -> None:
    backend = FakeSheetsBackend({VEHICLE_TAB: _vehicle_tab(ROWS, REGISTRY_COLUMNS)})
    backend.fail_values_get = True
    response = await _http(_repo(backend), f"{API}/vehicles", params={"branch_id": "BR-TEST-A"})
    assert (response.status_code, response.json()["error"]["code"]) == (503, "VEHICLE_MASTER_READ_FAILED")
    missing = FakeSheetsBackend({VEHICLE_TAB: [[h for h in HEADER if h != "machine_no"] + list(REGISTRY_COLUMNS)]})
    response = await _http(_repo(missing), f"{API}/vehicles")
    assert (response.status_code, response.json()["error"]["code"]) == (500, "VEHICLE_MASTER_SCHEMA_INVALID")


# ---------------------------------------------------------------------------
# Reference and history tabs over the fake transport
# ---------------------------------------------------------------------------


def _seed_backend() -> FakeSheetsBackend:
    """The mock seed's vehicles, registry cells, reference lists and both
    histories, laid out as sheet tabs (for mock/fake parity)."""
    vehicles = [
        ([v.vehicle_id, v.machine_no, v.model_id, v.serial_number or "", v.operational_status.value, TS, TS],
         seed_data.SEED_VEHICLE_REGISTRY.get(v.vehicle_id, {}))
        for v in seed_data.SEED_VEHICLES
    ]
    model_header = list(schemas.VEHICLE_MODEL_SHEET.required_headers)
    models = [{"model_id": m.model_id, "model_code": m.model_code, "model_name": m.model_name} for m in seed_data.SEED_MODELS]
    return FakeSheetsBackend({
        VEHICLE_TAB: _vehicle_tab(vehicles, REGISTRY_COLUMNS),
        "model_master": _table(model_header, models),  # read only by the q search index
        BRANCH_TAB: _table(["branch_id", "branch_name", "is_active"], seed_data.SEED_BRANCH_MASTER),
        PROVINCE_TAB: _table(["province_code", "province_name_th", "is_active"], seed_data.SEED_PROVINCE_MASTER),
        ABH_TAB: _table(list(ASSET_BRANCH_HISTORY_COLUMNS), seed_data.build_seed_asset_branch_history()),
        VRH_TAB: _table(list(REGISTRATION_HISTORY_COLUMNS), seed_data.build_seed_registration_history()),
    })


PARITY_PATHS = [
    "branches", "provinces",
    *(f"vehicles/{v}/{kind}" for v in ("VEH-1046", "VEH-1047", "VEH-1048") for kind in ("branch-history", "registration-history")),
]


@pytest.mark.asyncio
async def test_r12_mock_and_fake_sheets_responses_are_identical() -> None:
    sheets = _repo(_seed_backend())
    for path in PARITY_PATHS:
        fake = await _http(sheets, f"{API}/{path}")
        mock = await _http(MockRepository(), f"{API}/{path}")
        assert fake.status_code == mock.status_code == 200, path
        assert fake.json() == mock.json(), path
    for params in ({}, {"branch_id": "BR-LAEM-CHABANG"}, {"branch_id": "BR-RAYONG"}, {"q": "TC-12", "branch_id": "BR-LAEM-CHABANG"}):
        fake = (await _http(sheets, f"{API}/vehicles", params=params)).json()
        mock = (await _http(MockRepository(), f"{API}/vehicles", params=params)).json()
        assert [(i["vehicle_id"], i["registry"]) for i in fake["items"]] == [(i["vehicle_id"], i["registry"]) for i in mock["items"]]
        assert fake["total_items"] == mock["total_items"]
    for vid in ("VEH-1046", "VEH-1047", "VEH-1048"):
        assert (await sheets.get_vehicle_with_registry_validated(vid)).registry == \
            (await MockRepository().get_vehicle_with_registry_validated(vid)).registry


@pytest.mark.asyncio
async def test_r12_error_semantics_match_between_mock_and_fake() -> None:
    backend = _seed_backend()
    rows = seed_data.build_seed_asset_branch_history()
    rows[2]["revision_no"] = "x"
    backend.tabs[ABH_TAB] = _table(list(ASSET_BRANCH_HISTORY_COLUMNS), rows)
    fake = await _http(_repo(backend), f"{API}/vehicles/VEH-1046/branch-history")

    class Broken(MockRepository):
        def __init__(self) -> None:
            super().__init__()
            self._asset_branch_history = rows

    mock = await _http(Broken(), f"{API}/vehicles/VEH-1046/branch-history")
    assert fake.status_code == mock.status_code == 500
    strip = lambda r: {k: v for k, v in r.json()["error"].items() if k != "request_id"}  # noqa: E731
    assert strip(fake) == strip(mock)


@pytest.mark.asyncio
async def test_history_structure_errors_are_coded_and_scoped() -> None:
    backend = _seed_backend()
    prepared = ["assignment_id", "asset_type", "asset_id", "branch_id", "start_at", "end_at", "is_test_data", "test_batch_id", "note_th"]
    backend.tabs[ABH_TAB] = [prepared]  # the observed prepared format: proposed columns missing
    del backend.tabs[VRH_TAB]
    repo = _repo(backend)
    branch = await _http(repo, f"{API}/vehicles/VEH-1046/branch-history")
    assert (branch.status_code, branch.json()["error"]["code"]) == (500, "BRANCH_HISTORY_SCHEMA_INVALID")
    assert branch.json()["error"]["details"]["problem"] == "MISSING_HEADERS"
    registration = await _http(repo, f"{API}/vehicles/VEH-1046/registration-history")
    assert (registration.status_code, registration.json()["error"]["code"]) == (500, "REGISTRATION_HISTORY_SCHEMA_INVALID")
    assert registration.json()["error"]["details"]["problem"] == "TAB_MISSING"
    # Only those panels fail: the vehicle list and the reference lists still work.
    assert (await _http(repo, f"{API}/vehicles")).status_code == 200
    assert (await _http(repo, f"{API}/branches")).status_code == 200
    del backend.tabs[BRANCH_TAB]
    # A tab that vanishes after the client cached the worksheet list is a read
    # failure (existing client behaviour); a cold client reports it as missing.
    assert (await _http(repo, f"{API}/branches")).json()["error"]["code"] == "BRANCH_MASTER_READ_FAILED"
    assert (await _http(_repo(backend), f"{API}/branches")).json()["error"]["code"] == "BRANCH_MASTER_SCHEMA_INVALID"
    assert (await _http(repo, f"{API}/provinces")).status_code == 200
    backend.fail_values_get = True
    down = await _http(repo, f"{API}/provinces")
    assert (down.status_code, down.json()["error"]["code"]) == (503, "PROVINCE_MASTER_READ_FAILED")
    assert backend.writes == []


@pytest.mark.asyncio
async def test_branch_master_without_is_active_and_phantom_rows() -> None:
    backend = _seed_backend()
    backend.tabs[BRANCH_TAB] = [["branch_name", "branch_id"], ["ระยอง", "BR-RAYONG"], ["", ""], ["บางนา", "007"]]
    response = await _http(_repo(backend), f"{API}/branches")
    # Optional is_active absent -> every branch active; header order irrelevant; the
    # blank row is a phantom; a numeric-looking id stays text.
    assert response.json() == {"items": [
        {"branch_id": "007", "branch_name": "บางนา", "is_active": True},
        {"branch_id": "BR-RAYONG", "branch_name": "ระยอง", "is_active": True},
    ]}
    backend.tabs[BRANCH_TAB] = [["branch_id", "branch_name"], ["BR-RAYONG", ""], ["BR-RAYONG", "ระยอง"]]
    invalid = (await _http(_repo(backend), f"{API}/branches")).json()["error"]
    assert (invalid["code"], invalid["details"]["issues"]) == ("BRANCH_MASTER_DATA_INVALID", {"BLANK_NAME": 1, "DUPLICATE_CODE": 2})


@pytest.mark.asyncio
async def test_history_tabs_survive_warm_cache_and_header_reorder() -> None:
    backend = _seed_backend()
    repo = _repo(backend)
    before = {p: (await _http(repo, f"{API}/{p}")).json() for p in PARITY_PATHS}
    # Warm the client's legacy header cache, then reorder every new tab's columns.
    for schema in (schemas.BRANCH_SHEET, schemas.PROVINCE_SHEET, schemas.ASSET_BRANCH_HISTORY_SHEET,
                   schemas.VEHICLE_REGISTRATION_HISTORY_SHEET, schemas.VEHICLE_SHEET):
        await repo._client.read_rows(schema)
    for tab in (BRANCH_TAB, PROVINCE_TAB, ABH_TAB, VRH_TAB, VEHICLE_TAB):
        header, *rows = backend.tabs[tab]
        order = list(reversed(range(len(header))))
        backend.tabs[tab] = [[header[i] for i in order], *([row[i] if i < len(row) else "" for i in order] for row in rows)]
    after = {p: (await _http(repo, f"{API}/{p}")).json() for p in PARITY_PATHS}
    assert after == before
    assert backend.writes == []


# ---------------------------------------------------------------------------
# Request counts (fake transport), cold and warm; zero writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_counts_cold_and_warm_for_every_new_get() -> None:
    measured = {}
    for path in ("branches", "provinces", "vehicles/VEH-1046/branch-history", "vehicles/VEH-1046/registration-history",
                 "vehicles?branch_id=BR-LAEM-CHABANG"):
        backend = _seed_backend()
        repo = _repo(backend)
        for phase in ("cold", "warm"):
            backend.requests.clear()
            response = await _http(repo, f"{API}/{path}")
            assert response.status_code == 200, path
            measured[(path, phase)] = (backend.metadata_reads(), backend.values_reads())
        assert backend.writes == []
    # (metadata reads, values reads). One values read per tab touched; the
    # warm metadata count is 0 (the client caches the worksheet list).
    assert measured == {
        ("branches", "cold"): (2, 1), ("branches", "warm"): (0, 1),
        ("provinces", "cold"): (2, 1), ("provinces", "warm"): (0, 1),
        ("vehicles/VEH-1046/branch-history", "cold"): (3, 2), ("vehicles/VEH-1046/branch-history", "warm"): (0, 2),
        ("vehicles/VEH-1046/registration-history", "cold"): (3, 2), ("vehicles/VEH-1046/registration-history", "warm"): (0, 2),
        ("vehicles?branch_id=BR-LAEM-CHABANG", "cold"): (2, 1), ("vehicles?branch_id=BR-LAEM-CHABANG", "warm"): (0, 1),
    }


@pytest.mark.asyncio
async def test_list_request_count_is_unchanged_by_the_registry_columns() -> None:
    counts = []
    for columns in ((), REGISTRY_COLUMNS):
        backend = FakeSheetsBackend({VEHICLE_TAB: _vehicle_tab(ROWS, columns)})
        repo = _repo(backend)
        await VehicleService(repo).list_vehicles(None, None, None, PageParams())
        backend.requests.clear()
        await _http(repo, f"{API}/vehicles")
        counts.append(backend.values_reads())
    assert counts == [1, 1]


@pytest.mark.asyncio
async def test_unset_context_reads_nothing_over_sheets() -> None:
    backend = _seed_backend()
    repo = _repo(backend)
    for path in PARITY_PATHS:
        response = await _http(repo, f"{API}/{path}", settings=_settings(None))
        assert response.json()["error"]["code"] == "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED"
    assert backend.requests == [] and backend.writes == []
