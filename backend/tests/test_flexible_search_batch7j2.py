"""Phase 7 Batch 7J2 — flexible vehicle and equipment list search.

Unit tests of the shared matcher (`app.domain.search_match`, U01-U17) and
service/API tests on the mock repository (M01-M10), all exercising the
implemented code. Approved 7J1 Final contract, D-1..D-11 (owner approval).
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.common import OperationalStatus, PageParams
from app.domain.equipment import Equipment, EquipmentCategory, EquipmentOperationalStatus
from app.domain.equipment_service import EquipmentService
from app.domain.search_match import compact, record_matches, thai_digit_pieces, token_matches, tokenize
from app.domain.vehicle import Vehicle
from app.domain.vehicle_model import VehicleModel
from app.domain.vehicle_service import VehicleService
from app.errors import ApiError
from app.repositories.base import (
    RepositoryError,
    RepositorySchemaError,
    RepositoryTabReadError,
    VehicleMasterSummaryRead,
    VehicleModelSearchEntry,
)
from app.repositories.mock import MockRepository

TS = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _equipment(eid: str, name: str, code: str, category: EquipmentCategory = EquipmentCategory.LATHE) -> Equipment:
    return Equipment(
        equipment_id=eid,
        equipment_code=code,
        name=name,
        category=category,
        operational_status=EquipmentOperationalStatus.READY,
        created_at=TS,
        updated_at=TS,
    )


EQUIPMENT = [
    _equipment("EQP-0001", "เครื่องกลึงเบอร์ 1", "LATHE-01"),
    _equipment("EQP-0010", "เครื่องกลึงเบอร์ 10", "LATHE-10"),
    _equipment("EQP-0011", "เครื่องกลึงเบอร์ 2", "LATHE-02"),
    _equipment("EQP-0020", "ปั๊มลมเบอร์ 01", "COMP-01", EquipmentCategory.AIR_COMPRESSOR),
    _equipment("EQP-0030", "เครื่องเชื่อม 2 หัว 3", "WELD-23", EquipmentCategory.WELDING),
    _equipment("EQP-0012", "ปั๊มลมสำรอง", "0012", EquipmentCategory.AIR_COMPRESSOR),
]


def _vehicle(vid: str, machine: str, model: str, status: OperationalStatus = OperationalStatus.READY) -> Vehicle:
    return Vehicle(
        vehicle_id=vid,
        machine_no=machine,
        model_id=model,
        serial_number=None,
        operational_status=status,
        created_at=TS,
        updated_at=TS,
    )


def _model(mid: str, code: str, name: str) -> VehicleModel:
    return VehicleModel(model_id=mid, model_code=code, model_name=name, created_at=TS, updated_at=TS)


VEHICLES = [
    _vehicle("VEH-1046", "TC-12", "MDL-QY", OperationalStatus.WORKING),
    _vehicle("VEH-1047", "TC-13", "MDL-XC", OperationalStatus.MAINTENANCE),
    _vehicle("VEH-1048", "TC-14", "MDL-GR", OperationalStatus.READY),
    _vehicle("VEH-1013", "TC-20", "MDL-QY", OperationalStatus.READY),
    _vehicle("VEH-2000", "0012", "MDL-GR", OperationalStatus.READY),
    _vehicle("VEH-2001", "TC-130", "MDL-XC", OperationalStatus.WORKING),
    _vehicle("VEH-3000", "TC-99", "MDL-MISSING", OperationalStatus.READY),
    _vehicle("VEH-3001", "TC-98", "", OperationalStatus.READY),
]
MODELS = [
    _model("MDL-QY", "QY50", "Zoomlion QY50 รถเครนล้อยาง 50 ตัน"),
    _model("MDL-XC", "XCT80", "XCMG XCT80 รถเครนล้อยาง 80 ตัน"),
    _model("MDL-GR", "GR-250", "Tadano GR-250 รถเครน 25 ตัน"),
    _model("mdl-qy", "LOWER", "Lower-case id model"),  # exact join: never joins MDL-QY
]


class SearchRepository(MockRepository):
    """Mock repository with the 7J2 fixtures, counting reads. `model_rows`
    replaces the model index (to give duplicate model ids, which the mock's
    dict cannot hold); `model_error` makes the model index read fail."""

    def __init__(self, model_rows: list[VehicleModelSearchEntry] | None = None, model_error: Exception | None = None,
                 vehicle_read: VehicleMasterSummaryRead | None = None) -> None:
        super().__init__()
        self._vehicles = {v.vehicle_id: v.model_copy(deep=True) for v in VEHICLES}
        self._models = {m.model_id: m.model_copy(deep=True) for m in MODELS}
        self._equipment = {e.equipment_id: e.model_copy(deep=True) for e in EQUIPMENT}
        self._model_rows = model_rows
        self._model_error = model_error
        self._vehicle_read = vehicle_read
        self.model_index_reads = 0
        self.summary_reads = 0
        self.equipment_record_reads = 0
        self.legacy_equipment_list_calls = 0

    async def read_vehicle_model_search_index(self):  # type: ignore[override]
        self.model_index_reads += 1
        if self._model_error is not None:
            raise self._model_error
        if self._model_rows is not None:
            return list(self._model_rows)
        return await super().read_vehicle_model_search_index()

    async def read_vehicle_master_for_summary(self):  # type: ignore[override]
        self.summary_reads += 1
        if self._vehicle_read is not None:
            return self._vehicle_read
        return await super().read_vehicle_master_for_summary()

    async def list_equipment_records(self):  # type: ignore[override]
        self.equipment_record_reads += 1
        return await super().list_equipment_records()

    async def list_equipment(self, *args, **kwargs):  # type: ignore[override]
        self.legacy_equipment_list_calls += 1
        return await super().list_equipment(*args, **kwargs)


async def _vehicles(repo, q=None, status=None, model_id=None, page=1, page_size=50):
    page_ = await VehicleService(repo).list_vehicles(
        q=q, operational_status=status, model_id=model_id, params=PageParams(page=page, page_size=page_size)
    )
    return page_


async def _vehicle_ids(repo, q=None, **kwargs) -> list[str]:
    return [v.vehicle_id for v in (await _vehicles(repo, q=q, **kwargs)).items]


async def _equipment_ids(repo, q=None, category=None, page=1, page_size=50) -> list[str]:
    result = await EquipmentService(repo).list_equipment(q=q, category=category, params=PageParams(page=page, page_size=page_size))
    return [e.equipment_id for e in result.items]


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


# ---------------------------------------------------------------------------
# U01-U17 — the shared matcher
# ---------------------------------------------------------------------------


def test_u01_no_text_filter_for_none_empty_and_whitespace_including_nbsp() -> None:
    for q in (None, "", " ", "\t\n ", " ", "　 "):
        assert tokenize(q) is None
    assert record_matches(None, (), ("anything",))
    # ZWSP is not whitespace (D-3): it is a token of its own.
    assert tokenize("​") == ("​",)


def test_u02_tokenization_lowercases_dedupes_and_keeps_order() -> None:
    assert tokenize("  TC  tc  13 TC ") == ("tc", "13")
    assert tokenize("13 TC") == ("13", "tc")
    assert tokenize("เครื่อง กลึง") == ("เครื่อง", "กลึง")


def test_u03_hyphen_only_tokens_are_dropped_and_an_all_hyphen_query_matches_nothing() -> None:
    for q in ("-", "--", " - -- "):
        assert tokenize(q) == ()
        assert not record_matches(tokenize(q), ("a-b",), ("-",))
    assert tokenize("TC - 13") == ("tc", "13")


def test_u04_names_are_literal_and_never_compacted() -> None:
    assert not token_matches("gr250", ("Tadano GR-250",), ())
    assert token_matches("gr250", (), ("GR-250",))
    assert token_matches("gr-250", ("Tadano GR-250",), ())
    assert not token_matches("tadanogr", ("Tadano GR-250",), ())


def test_u05_identifier_tolerance_for_spaces_and_ascii_hyphens() -> None:
    for token in ("tc13", "tc-13", "tc-1-3"):
        assert token_matches(token, (), ("TC-13",))
    assert token_matches("tc13", (), ("TC 13",))
    assert compact(" T C-1 3 ") == "tc13"


def test_u06_d1_worked_example_formatting_variants_are_not_equivalent() -> None:
    record_a = ("TC-20", "VEH-1013")
    record_b = ("TC-13", "VEH-1047")
    assert record_matches(tokenize("TC 13"), (), record_a)  # "tc" in TC-20, "13" in VEH-1013
    assert not record_matches(tokenize("TC13"), (), record_a)
    assert not record_matches(tokenize("TC-13"), (), record_a)
    for q in ("TC 13", "TC13", "TC-13"):
        assert record_matches(tokenize(q), (), record_b)


def test_u07_thai_text_and_digits_literal_and_order_free_terms() -> None:
    name = ("เครื่องกลึงเบอร์ 1",)
    for q in ("เครื่องกลึง 1", "กลึง 1", "1 กลึง", "  กลึง   1  ", "เครื่อง กลึง"):
        assert record_matches(tokenize(q), name, ()), q
    assert not record_matches(tokenize("เบอร์ 2"), name, ())


def test_u08_leading_zeros_are_text_substrings_never_numbers() -> None:
    assert record_matches(tokenize("0012"), (), ("0012",))
    assert record_matches(tokenize("12"), (), ("0012",))
    assert not record_matches(tokenize("00012"), (), ("0012",))
    assert not record_matches(tokenize("0012"), (), ("12",))


def test_u09_other_punctuation_stays_literal() -> None:
    assert record_matches(tokenize("/b"), (), ("A/B",))
    assert not record_matches(tokenize("ab"), (), ("A/B",))
    assert not record_matches(tokenize("ab"), (), ("A.B",))
    assert not record_matches(tokenize("ab"), (), ("A_B",))


def test_u10_zero_width_space_and_unicode_hyphen_are_not_whitespace_or_hyphen() -> None:
    assert tokenize("tc​13") == ("tc​13",)
    assert not record_matches(tokenize("tc​13"), (), ("TC-13",))
    assert not record_matches(tokenize("tc‐13"), (), ("TC-13",))
    assert tokenize("‐") == ("‐",)  # not dropped as a hyphen-only token


def test_u11_superset_of_the_former_substring_rule() -> None:
    rng = random.Random(20261001)
    alphabet = "aTc1-3 /ก"
    for _ in range(3000):
        field = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))
        q = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 5)))
        needle = q.strip().lower()
        tokens = tokenize(q)
        if not needle or not tokens:
            continue
        if needle in field.lower():
            assert record_matches(tokens, (), (field,)), (q, field)


def test_u12_d11_eligibility_and_pieces() -> None:
    assert thai_digit_pieces("กลึง1") == ("กลึง", "1")
    assert thai_digit_pieces("1กลึง") == ("1", "กลึง")
    assert thai_digit_pieces("เชื่อม2หัว3") == ("เชื่อม", "2", "หัว", "3")
    assert thai_digit_pieces("ปั๊ม1") == ("ปั๊ม", "1")  # combining marks stay in the Thai run
    assert thai_digit_pieces("ลม01") == ("ลม", "01")
    assert thai_digit_pieces("กลึง1กลึง") == ("กลึง", "1")  # duplicates collapse
    assert thai_digit_pieces("1ั") is None  # a Thai run of combining marks only
    assert thai_digit_pieces("กลึง") is None and thai_digit_pieces("12") is None


def test_u13_d11_finds_numbered_names_but_never_combines_with_identifier_digits() -> None:
    tokens = tokenize("กลึง1")
    assert record_matches(tokens, ("เครื่องกลึงเบอร์ 1",), ("EQP-0001", "LATHE-01"))
    assert record_matches(tokens, ("เครื่องกลึงเบอร์ 10",), ("EQP-0010", "LATHE-10"))
    # Thai piece only in the name, digit only in the identifiers -> no match.
    assert not record_matches(tokens, ("เครื่องกลึงเบอร์ 2",), ("EQP-0011", "LATHE-02"))
    # Pieces must be in ONE name field.
    assert not record_matches(tokens, ("เครื่องกลึง", "เบอร์ 1"), ())
    # Literal matching remains available for an eligible token.
    assert record_matches(tokens, ("ป้ายกลึง1",), ())


def test_u14_boundary_tokens_stay_on_the_literal_and_identifier_paths() -> None:
    for token in ("กลึง-1", "กลึง๑", "กลึง​1", "aกลึง1", "กลึง1.", "฿1กลึง"):
        assert thai_digit_pieces(token) is None, token
        assert not token_matches(token, ("เครื่องกลึงเบอร์ 1",), ("EQP-0001",)), token
    # A hyphenated Thai/digit token still matches identifiers through compact.
    assert token_matches("กลึง-1", (), ("กลึง1",))


def test_u15_leading_zero_digit_runs() -> None:
    assert record_matches(tokenize("ลม01"), ("ปั๊มลมเบอร์ 01",), ())
    assert record_matches(tokenize("ปั๊ม1"), ("ปั๊มลมเบอร์ 01",), ())
    assert not record_matches(tokenize("ลม001"), ("ปั๊มลมเบอร์ 01",), ())


def test_u16_latin_identifiers_are_not_split() -> None:
    assert thai_digit_pieces("tc13") is None and thai_digit_pieces("gr250") is None
    assert record_matches(tokenize("GR250"), (), ("GR-250",))
    assert record_matches(tokenize("LATHE01"), (), ("LATHE-01",))
    assert record_matches(tokenize("lathe1"), (), ("LATHE-10",))  # compact substring
    assert not record_matches(tokenize("lathe1"), (), ("LATHE-01",))
    assert not record_matches(tokenize("TC13"), ("TC รุ่น 13",), ())


@pytest.mark.asyncio
async def test_u17_spaced_and_unspaced_thai_queries_are_different_sets() -> None:
    repo = SearchRepository()
    assert await _equipment_ids(repo, "กลึง1") == ["EQP-0001", "EQP-0010"]
    assert await _equipment_ids(repo, "กลึง 1") == ["EQP-0001", "EQP-0010", "EQP-0011"]


# ---------------------------------------------------------------------------
# M01-M10 — services and HTTP on the mock repository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m01_equipment_examples() -> None:
    repo = SearchRepository()
    cases = {
        "เครื่องกลึง 1": ["EQP-0001", "EQP-0010", "EQP-0011"],
        "กลึง1": ["EQP-0001", "EQP-0010"],
        "1กลึง": ["EQP-0001", "EQP-0010"],
        "ปั๊ม1": ["EQP-0020"],
        "ลม01": ["EQP-0020"],
        "ลม001": [],
        "เชื่อม2หัว3": ["EQP-0030"],
        "เชื่อม3หัว2": ["EQP-0030"],
        "2เชื่อม": ["EQP-0030"],
        "LATHE01": ["EQP-0001"],
        "lathe 01": ["EQP-0001", "EQP-0010", "EQP-0011"],  # "01" also in EQP-0010/EQP-0011 ids (D-1)
        "EQP 0001": ["EQP-0001"],
        "eqp0001": ["EQP-0001"],
        "0012": ["EQP-0012"],
        "12": ["EQP-0012"],
        "-": [],
        "  ": ["EQP-0001", "EQP-0010", "EQP-0011", "EQP-0012", "EQP-0020", "EQP-0030"],
    }
    for q, expected in cases.items():
        assert await _equipment_ids(repo, q) == expected, q
    assert repo.legacy_equipment_list_calls == 0


@pytest.mark.asyncio
async def test_m01_vehicle_examples_including_model_fields() -> None:
    repo = SearchRepository()
    cases = {
        "TC13": ["VEH-1047", "VEH-2001"],
        "TC-13": ["VEH-1047", "VEH-2001"],
        "TC 13": ["VEH-1013", "VEH-1047", "VEH-2001"],
        "QY50": ["VEH-1013", "VEH-1046"],
        "qy 50": ["VEH-1013", "VEH-1046"],
        "Tadano": ["VEH-1048", "VEH-2000"],
        "GR250": ["VEH-1048", "VEH-2000"],
        "รถเครน25": ["VEH-1048", "VEH-2000"],
        "เครน80": ["VEH-1047", "VEH-2001"],
        "gr 250 tc-14": ["VEH-1048"],
        "0012": ["VEH-2000"],
        "00012": [],
        "-": [],
    }
    for q, expected in cases.items():
        assert await _vehicle_ids(repo, q) == expected, q


@pytest.mark.asyncio
async def test_m02_cross_field_and() -> None:
    repo = SearchRepository()
    assert await _vehicle_ids(repo, "xcmg tc-13") == ["VEH-1047", "VEH-2001"]  # TC-130 contains tc-13
    assert await _vehicle_ids(repo, "zoomlion tc-20") == ["VEH-1013"]
    assert await _vehicle_ids(repo, "zoomlion tc-13") == []
    assert await _equipment_ids(repo, "กลึง lathe-10") == ["EQP-0010"]


@pytest.mark.asyncio
async def test_m03_q_combines_with_status_model_and_category() -> None:
    repo = SearchRepository()
    assert await _vehicle_ids(repo, "tc", status=OperationalStatus.WORKING) == ["VEH-1046", "VEH-2001"]
    assert await _vehicle_ids(repo, "tc-1", model_id="MDL-XC") == ["VEH-1047", "VEH-2001"]
    assert await _vehicle_ids(repo, "zoomlion", status=OperationalStatus.WORKING) == ["VEH-1046"]
    assert await _equipment_ids(repo, "เบอร์", category=EquipmentCategory.AIR_COMPRESSOR) == ["EQP-0020"]
    assert await _equipment_ids(repo, "กลึง1", category=EquipmentCategory.WELDING) == []


@pytest.mark.asyncio
async def test_m04_totals_slices_and_out_of_range_pages() -> None:
    repo = SearchRepository()
    page1 = await _vehicles(repo, "tc", page=1, page_size=3)
    page3 = await _vehicles(repo, "tc", page=3, page_size=3)
    beyond = await _vehicles(repo, "tc", page=9, page_size=3)
    all_ids = await _vehicle_ids(repo, "tc")
    assert page1.total_items == page3.total_items == beyond.total_items == len(all_ids) == 7
    assert [v.vehicle_id for v in page1.items] == all_ids[:3]
    assert [v.vehicle_id for v in page3.items] == all_ids[6:9]
    assert beyond.items == [] and beyond.page == 9
    eq = await EquipmentService(repo).list_equipment(q="เครื่อง", category=None, params=PageParams(page=2, page_size=2))
    assert eq.total_items == 4 and [e.equipment_id for e in eq.items] == ["EQP-0011", "EQP-0030"]


@pytest.mark.asyncio
async def test_m05_ordering_is_unchanged() -> None:
    repo = SearchRepository()
    ids = await _vehicle_ids(repo, "veh")
    assert ids == sorted(ids)
    eids = await _equipment_ids(repo, "e")
    assert eids == sorted(eids)


@pytest.mark.asyncio
async def test_m06_exact_model_id_join_missing_and_blank_models() -> None:
    repo = SearchRepository()
    # "lower" is the code of model "mdl-qy", which no vehicle references exactly.
    assert await _vehicle_ids(repo, "lower") == []
    # Missing model and blank model_id: searchable by their own fields only.
    assert await _vehicle_ids(repo, "tc-99") == ["VEH-3000"]
    assert await _vehicle_ids(repo, "tc-98") == ["VEH-3001"]
    assert await _vehicle_ids(repo, "tc-98 zoomlion") == []
    padded = SearchRepository(model_rows=[VehicleModelSearchEntry(" MDL-QY", "PAD", "Padded")])
    assert await _vehicle_ids(padded, "pad") == []


@pytest.mark.asyncio
async def test_m06_duplicate_model_rows_follow_rc() -> None:
    rows = [
        VehicleModelSearchEntry("MDL-QY", "QY50", "Zoomlion QY50 รถเครน 50 ตัน"),
        VehicleModelSearchEntry("MDL-QY", "XCT80", "XCMG XCT80 รถเครนล้อยาง 80 ตัน"),
    ]
    repo = SearchRepository(model_rows=rows)
    for q in ("zoomlion", "xct80", "ล้อยาง80", "รถเครน 50"):
        assert await _vehicle_ids(repo, q) == ["VEH-1013", "VEH-1046"], q
    assert await _vehicle_ids(repo, "tc-12 xcmg") == ["VEH-1046"]  # machine_no + one row
    # Never assembled across the two rows: tokens or D-11 pieces.
    for q in ("zoomlion xct80", "qy50 80", "ล้อยาง50", "zoomlion ล้อยาง80"):
        assert await _vehicle_ids(repo, q) == [], q
    # A vehicle matching on its own fields is returned once.
    assert await _vehicle_ids(repo, "VEH-1046") == ["VEH-1046"]
    assert (await _vehicles(repo, "veh-104")).total_items == 3


@pytest.mark.asyncio
async def test_m07_model_index_is_read_only_for_usable_terms_after_vehicle_validation() -> None:
    repo = SearchRepository()
    for q, reads in ((None, 0), ("", 0), ("   ", 0), ("-", 0), (" -- - ", 0), ("tc", 1), ("tc 13", 1)):
        repo.model_index_reads = 0
        repo.summary_reads = 0
        await _vehicles(repo, q)
        assert (repo.summary_reads, repo.model_index_reads) == (1, reads), q
    invalid = SearchRepository(vehicle_read=VehicleMasterSummaryRead(vehicles=[], issue_counts={"BLANK_STATUS": 1}, issue_vehicle_ids=["VEH-X"]))
    with pytest.raises(ApiError) as info:
        await _vehicles(invalid, "tc")
    assert info.value.code == "VEHICLE_MASTER_DATA_INVALID" and invalid.model_index_reads == 0


@pytest.mark.asyncio
async def test_m08_search_never_writes() -> None:
    repo = SearchRepository()
    before = (
        {k: v.model_dump() for k, v in repo._vehicles.items()},
        {k: v.model_dump() for k, v in repo._equipment.items()},
        {k: v.model_dump() for k, v in repo._models.items()},
        dict(repo._status_history),
    )
    for q in ("tc 13", "กลึง1", "-", "zoomlion", None):
        await _vehicles(repo, q)
        await _equipment_ids(repo, q)
    after = (
        {k: v.model_dump() for k, v in repo._vehicles.items()},
        {k: v.model_dump() for k, v in repo._equipment.items()},
        {k: v.model_dump() for k, v in repo._models.items()},
        dict(repo._status_history),
    )
    assert after == before


@pytest.mark.asyncio
async def test_m09_http_success_hyphen_only_and_shapes() -> None:
    repo = SearchRepository()
    response = await _http(repo, "/api/v1/vehicles", params={"q": "รถเครน25"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "page", "page_size", "total_items"}
    assert [v["vehicle_id"] for v in body["items"]] == ["VEH-1048", "VEH-2000"]
    none = await _http(repo, "/api/v1/vehicles", params={"q": "-"})
    assert none.status_code == 200 and none.json()["total_items"] == 0 and none.json()["items"] == []
    eq = await _http(repo, "/api/v1/equipment", params={"q": "กลึง1", "category": "LATHE"})
    assert eq.status_code == 200 and [e["equipment_id"] for e in eq.json()["items"]] == ["EQP-0001", "EQP-0010"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "code", "details"),
    [
        (RepositoryTabReadError("model_master", "x"), 503, "MODEL_MASTER_READ_FAILED", None),
        (RepositorySchemaError("model_master", "TAB_MISSING", ()), 500, "MODEL_MASTER_SCHEMA_INVALID",
         {"tab": "model_master", "problem": "TAB_MISSING", "headers": []}),
        (RepositoryError("connection reset"), 503, "MODEL_MASTER_READ_FAILED", None),
    ],
)
async def test_m09_model_failures_use_model_codes_without_ids(error, status_code, code, details) -> None:
    repo = SearchRepository(model_error=error)
    response = await _http(repo, "/api/v1/vehicles", params={"q": "tc"})
    assert response.status_code == status_code
    payload = response.json()["error"]
    assert payload["code"] == code and payload["details"] == details
    for leaked in ("VEH-", "MDL-", "TC-", "sample_vehicle_ids", "items", "total_items"):
        assert leaked not in response.text
    # An empty query never reads model_master, so it still succeeds.
    ok = await _http(SearchRepository(model_error=error), "/api/v1/vehicles")
    assert ok.status_code == 200 and ok.json()["total_items"] == len(VEHICLES)


@pytest.mark.asyncio
async def test_m09_vehicle_errors_come_first_with_issue_counts_only() -> None:
    repo = SearchRepository(
        model_error=RepositoryTabReadError("model_master", "x"),
        vehicle_read=VehicleMasterSummaryRead(vehicles=[], issue_counts={"BLANK_STATUS": 1}, issue_vehicle_ids=["VEH-X"]),
    )
    response = await _http(repo, "/api/v1/vehicles", params={"q": "tc"})
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "VEHICLE_MASTER_DATA_INVALID" and error["details"] == {"issue_counts": {"BLANK_STATUS": 1}}
    assert "VEH-X" not in response.text and repo.model_index_reads == 0


@pytest.mark.asyncio
async def test_m09_unexpected_model_errors_propagate_to_the_generic_handler() -> None:
    repo = SearchRepository(model_error=ZeroDivisionError("bug"))
    response = await _http(repo, "/api/v1/vehicles", params={"q": "tc"})
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_m10_dashboard_is_unchanged_and_never_reads_models() -> None:
    repo = SearchRepository()
    before = await VehicleService(repo).get_fleet_status_summary()
    await _vehicles(repo, "zoomlion")
    repo.model_index_reads = 0
    after = await VehicleService(repo).get_fleet_status_summary()
    assert after == before and repo.model_index_reads == 0
    assert after.vehicle_total == len(VEHICLES)
