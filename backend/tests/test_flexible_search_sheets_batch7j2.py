"""Phase 7 Batch 7J2 — flexible list search over Google Sheets, exercised
with the REAL installed gspread client on the 7B2 FAKE HTTP transport
(`FakeSheetsBackend`): an emulation, not live Google Sheets. Request counts
are fake-transport counts.

S01-S07 and S09 of the approved 7J1 Final contract (S08 = the narrow 7G2
fixture/count updates in the 7G2 test files).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.common import PageParams
from app.domain.equipment_service import EquipmentService
from app.domain.vehicle_service import VehicleService
from app.errors import ApiError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from tests.test_fleet_status_summary_sheets_batch7b2 import FakeSheetsBackend, _backend, _repo, _row

MODEL_HEADER = list(schemas.VEHICLE_MODEL_SHEET.required_headers)
EQUIPMENT_HEADER = list(schemas.EQUIPMENT_SHEET.required_headers)


def _model_row(mid: str, code: str, name: str, roles: str = "CARRIER_ENGINE") -> list[str]:
    cells = dict.fromkeys(MODEL_HEADER, "")
    cells.update(model_id=mid, model_code=code, model_name=name, component_roles=roles)
    return [cells[h] for h in MODEL_HEADER]


def _equipment_row(eid: str, code: str, name: str, category: str = "LATHE") -> list[str]:
    cells = dict.fromkeys(EQUIPMENT_HEADER, "")
    cells.update(equipment_id=eid, equipment_code=code, equipment_name_th=name, equipment_type=category,
                 equipment_status="READY", active_status="TRUE")
    return [cells[h] for h in EQUIPMENT_HEADER]


VEHICLE_ROWS = [
    _row("VEH-1046", machine="TC-12", model="MDL-QY"),
    _row("VEH-1047", machine="TC-13", model="MDL-XC"),
    _row("VEH-1048", machine="TC-14", model="MDL-GR"),
    _row("VEH-1013", machine="TC-20", model="MDL-QY"),
    _row("VEH-2000", machine="0012", model="MDL-NUM"),
    _row("VEH-2001", machine="TC-130", model="MDL-XC"),
    _row("VEH-3000", machine="TC-99", model="MDL-MISSING"),
]
MODEL_ROWS = [
    _model_row("MDL-QY", "QY50", "Zoomlion QY50 รถเครนล้อยาง 50 ตัน"),
    _model_row("MDL-XC", "XCT80", "XCMG XCT80 รถเครนล้อยาง 80 ตัน"),
    _model_row("MDL-GR", "GR-250", "Tadano GR-250 รถเครน 25 ตัน"),
    # Numeric-looking text, protected on this read; component_roles would
    # break the full model mapper but is never mapped by the search index.
    _model_row("MDL-NUM", "0012", "0250", roles="NOT_A_ROLE"),
]


def _vehicle_backend(models=MODEL_ROWS, rows=VEHICLE_ROWS, **extra) -> FakeSheetsBackend:
    tabs = {"model_master": [MODEL_HEADER, *models]} if models is not None else {}
    tabs.update(extra)
    return _backend(list(rows), **tabs)


async def _ids(repo: GoogleSheetsRepository, q=None, page_size=50, **kwargs) -> list[str]:
    result = await VehicleService(repo).list_vehicles(
        q=q, operational_status=kwargs.get("status"), model_id=kwargs.get("model_id"),
        params=PageParams(page=1, page_size=page_size),
    )
    return [v.vehicle_id for v in result.items]


async def _http(repo, path: str, params=None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, params=params)
    finally:
        reset_dependency_cache()


@pytest.mark.asyncio
async def test_s01_vehicle_example_matrix() -> None:
    repo = _repo(_vehicle_backend())
    cases = {
        "TC13": ["VEH-1047", "VEH-2001"],
        "TC 13": ["VEH-1013", "VEH-1047", "VEH-2001"],
        "QY50": ["VEH-1013", "VEH-1046"],
        "zoomlion tc-20": ["VEH-1013"],
        "GR250": ["VEH-1048"],
        "รถเครน25": ["VEH-1048"],
        "เครน80": ["VEH-1047", "VEH-2001"],
        "ล้อยาง": ["VEH-1013", "VEH-1046", "VEH-1047", "VEH-2001"],
        "tc-99": ["VEH-3000"],
        "-": [],
        None: [r[0] for r in sorted(VEHICLE_ROWS)],
    }
    for q, expected in cases.items():
        assert await _ids(repo, q) == expected, q


@pytest.mark.asyncio
async def test_s02_model_text_is_protected_and_only_three_columns_are_used() -> None:
    repo = _repo(_vehicle_backend())
    assert await _ids(repo, "0012") == ["VEH-2000"]  # machine_no "0012" and model_code "0012"
    assert await _ids(repo, "0250") == ["VEH-2000"]  # model_name stored as text "0250"
    assert await _ids(repo, "00250") == []
    # The full model mapper would reject component_roles "NOT_A_ROLE"; search does not map it.
    entries = await repo.read_vehicle_model_search_index()
    assert [(e.model_id, e.model_code, e.model_name) for e in entries][-1] == ("MDL-NUM", "0012", "0250")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backend_factory", "status_code", "code", "problem"),
    [
        (lambda: _vehicle_backend(models=None), 500, "MODEL_MASTER_SCHEMA_INVALID", "TAB_MISSING"),
        (lambda: _backend(list(VEHICLE_ROWS), model_master=[[h.upper() for h in MODEL_HEADER], *MODEL_ROWS]),
         500, "MODEL_MASTER_SCHEMA_INVALID", "MISSING_HEADERS"),
    ],
)
async def test_s03_model_structure_failures(backend_factory, status_code, code, problem) -> None:
    backend = backend_factory()
    response = await _http(_repo(backend), "/api/v1/vehicles", params={"q": "tc"})
    assert response.status_code == status_code
    error = response.json()["error"]
    assert error["code"] == code and error["details"]["problem"] == problem and error["details"]["tab"] == "model_master"
    for leaked in ("VEH-", "MDL-", "TC-", "sample_vehicle_ids", "total_items"):
        assert leaked not in response.text
    assert backend.writes == []


@pytest.mark.asyncio
async def test_s03_model_read_failure_is_503_without_details() -> None:
    backend = _vehicle_backend()

    def fail_model_read(tab, _cells):
        if tab == "model_master":
            raise RuntimeError("simulated transport failure")

    backend.before_values_get = fail_model_read
    response = await _http(_repo(backend), "/api/v1/vehicles", params={"q": "tc"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "MODEL_MASTER_READ_FAILED" and error["details"] is None
    assert "VEH-" not in response.text and "MDL-" not in response.text
    # An empty query never reads model_master.
    ok = await _http(_repo(backend), "/api/v1/vehicles")
    assert ok.status_code == 200 and ok.json()["total_items"] == len(VEHICLE_ROWS)


@pytest.mark.asyncio
async def test_s04_vehicle_errors_take_precedence_and_skip_the_model_read() -> None:
    backend = _vehicle_backend(models=None, rows=[*VEHICLE_ROWS, _row("VEH-9", "")])
    response = await _http(_repo(backend), "/api/v1/vehicles", params={"q": "tc"})
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "VEHICLE_MASTER_DATA_INVALID" and error["details"] == {"issue_counts": {"BLANK_STATUS": 1}}
    assert backend.values_reads("model_master") == 0 and "VEH-9" not in response.text


@pytest.mark.asyncio
async def test_s05_request_counts_cold_and_warm() -> None:
    measured = {}
    for label, q in (("empty", None), ("usable", "tc 13"), ("hyphen_only", "-")):
        backend = _vehicle_backend()
        repo = _repo(backend)
        for phase in ("cold", "warm"):
            backend.requests.clear()
            await _ids(repo, q)
            measured[(label, phase)] = (
                backend.metadata_reads(),
                backend.values_reads("vehicle_master"),
                backend.values_reads("model_master"),
                backend.values_reads("maintenance_plan"),
                backend.values_reads(),
            )
        assert backend.writes == []
    # (metadata, vehicle_master values, model_master values, maintenance_plan values, all values)
    assert measured == {
        ("empty", "cold"): (2, 1, 0, 0, 1),
        ("empty", "warm"): (0, 1, 0, 0, 1),
        ("usable", "cold"): (3, 1, 1, 0, 2),
        ("usable", "warm"): (0, 1, 1, 0, 2),
        ("hyphen_only", "cold"): (2, 1, 0, 0, 1),
        ("hyphen_only", "warm"): (0, 1, 0, 0, 1),
    }


@pytest.mark.asyncio
async def test_s05_request_count_is_independent_of_row_count() -> None:
    many = [_row(f"VEH-{i:04d}", machine=f"TC-{i}", model="MDL-QY") for i in range(300)]
    backend = _vehicle_backend(rows=many)
    repo = _repo(backend)
    await _ids(repo, "zoomlion")
    backend.requests.clear()
    assert len(await _ids(repo, "zoomlion", page_size=200)) == 200
    assert backend.requests == [("get", "values", "vehicle_master"), ("get", "values", "model_master")]


@pytest.mark.asyncio
async def test_s06_duplicate_model_rows_rc_and_d11() -> None:
    models = [
        _model_row("MDL-QY", "QY50", "Zoomlion QY50 รถเครน 50 ตัน"),
        _model_row("MDL-XC", "XCT80", "XCMG XCT80 รถเครนล้อยาง 80 ตัน"),
        _model_row("MDL-QY", "XCT80", "XCMG XCT80 รถเครนล้อยาง 80 ตัน"),
    ]
    repo = _repo(_vehicle_backend(models=models))
    for q in ("zoomlion", "ล้อยาง80", "tc-12 xcmg"):
        assert "VEH-1046" in await _ids(repo, q), q
    for q in ("zoomlion xct80", "qy50 80", "ล้อยาง50", "zoomlion ล้อยาง80"):
        assert "VEH-1046" not in await _ids(repo, q), q
    # Exact join only: "mdl-qy" is not "MDL-QY".
    lower = _repo(_vehicle_backend(models=[_model_row("mdl-qy", "LOWERCODE", "Lower")]))
    assert await _ids(lower, "lowercode") == []
    # Duplicates never duplicate the vehicle in the result.
    ids = await _ids(repo, "veh-104")
    assert ids == sorted(set(ids))


@pytest.mark.asyncio
async def test_s07_no_writes_in_any_search_path() -> None:
    scenarios = [
        _vehicle_backend(),
        _vehicle_backend(models=None),
        _vehicle_backend(rows=[*VEHICLE_ROWS, _row("VEH-9", "")]),
    ]
    for backend in scenarios:
        before = backend.snapshot()
        for q in ("tc 13", "รถเครน25", "-", None):
            await _http(_repo(backend), "/api/v1/vehicles", params={"q": q} if q else None)
        assert backend.writes == [] and backend.snapshot() == before
        assert all(method == "get" for method, _, _ in backend.requests)


# ---------------------------------------------------------------------------
# S09 — equipment under D-6(a): flexible matching on the UNCHANGED legacy read
# ---------------------------------------------------------------------------


def _equipment_backend(rows) -> FakeSheetsBackend:
    return FakeSheetsBackend({"equipment_master": [EQUIPMENT_HEADER, *rows]})


EQUIPMENT_ROWS = [
    _equipment_row("EQP-0001", "LATHE-01", "เครื่องกลึงเบอร์ 1"),
    _equipment_row("EQP-0010", "LATHE-10", "เครื่องกลึงเบอร์ 10"),
    _equipment_row("EQP-0011", "LATHE-02", "เครื่องกลึงเบอร์ 2"),
    _equipment_row("EQP-0020", "COMP-01", "ปั๊มลมเบอร์ 01", "AIR_COMPRESSOR"),
]


@pytest.mark.asyncio
async def test_s09_equipment_flexible_matching_on_the_legacy_read() -> None:
    backend = _equipment_backend(EQUIPMENT_ROWS)
    service = EquipmentService(_repo(backend))

    async def ids(q, category=None):
        page = await service.list_equipment(q=q, category=category, params=PageParams(page=1, page_size=50))
        return [e.equipment_id for e in page.items]

    assert await ids("กลึง1") == ["EQP-0001", "EQP-0010"]
    assert await ids("กลึง 1") == ["EQP-0001", "EQP-0010", "EQP-0011"]
    assert await ids("ปั๊ม1") == ["EQP-0020"]
    assert await ids("lathe01") == ["EQP-0001"]
    assert await ids("-") == []
    backend.requests.clear()
    await ids("กลึง")
    assert backend.requests == [("get", "values", "equipment_master")]  # warm: one legacy read
    assert backend.writes == []


@pytest.mark.asyncio
async def test_s09_retained_limitation_numeric_looking_equipment_text_still_fails_the_list() -> None:
    """Phase 7 Batch 7K2 (authorized expectation change T-X1): the D-6(a)
    limitation this test pinned is replaced by the validated, text-preserving
    equipment read — a numeric-looking code is listed exactly and matches q.
    The unchanged LEGACY repository method still fails on the same data."""
    backend = _equipment_backend([*EQUIPMENT_ROWS, _equipment_row("EQP-0099", "0012", "ปั๊มสำรอง")])
    response = await _http(_repo(backend), "/api/v1/equipment")
    assert response.status_code == 200
    assert {e["equipment_id"]: e["equipment_code"] for e in response.json()["items"]}["EQP-0099"] == "0012"
    matched = await _http(_repo(backend), "/api/v1/equipment", params={"q": "0012"})
    assert matched.status_code == 200
    assert [(e["equipment_id"], e["equipment_code"]) for e in matched.json()["items"]] == [("EQP-0099", "0012")]
    legacy = _repo(_equipment_backend([*EQUIPMENT_ROWS, _equipment_row("EQP-0099", "0012", "ปั๊มสำรอง")]))
    with pytest.raises(Exception):
        await legacy.list_equipment(q=None, category=None, params=PageParams())
    assert backend.writes == []


@pytest.mark.asyncio
async def test_s09_equipment_read_failures_are_unchanged_from_the_legacy_method() -> None:
    """Phase 7 Batch 7K2 (authorized expectation change T-X2): the D-6(a)
    "no new validation or error codes" rule is superseded. A numeric-looking
    code now lists; a missing tab is the coded structural error."""
    backend = _equipment_backend([*EQUIPMENT_ROWS, _equipment_row("EQP-0099", "0012", "ปั๊มสำรอง")])
    page = await EquipmentService(_repo(backend)).list_equipment(q="x", category=None, params=PageParams())
    assert page.total_items == 0
    listed = await EquipmentService(_repo(backend)).list_equipment(q=None, category=None, params=PageParams())
    assert "EQP-0099" in [e.equipment_id for e in listed.items]
    with pytest.raises(ApiError) as info:
        await EquipmentService(_repo(FakeSheetsBackend({}))).list_equipment(q="x", category=None, params=PageParams())
    assert info.value.status_code == 500
    assert info.value.code == "EQUIPMENT_MASTER_SCHEMA_INVALID"
    assert info.value.details == {"tab": "equipment_master", "problem": "TAB_MISSING", "headers": []}
