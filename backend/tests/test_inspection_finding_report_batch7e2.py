"""Phase 7 Batch 7E2 — recorded inspection findings report
(GET /api/v1/reports/inspection-findings): pure row classification and
accounting (7E1 Final contract Section 5.3), the REAL legacy mapper gate
(GoogleSheetsRepository._inspection_finding_from_row with the installed
pydantic) and the mock model gate, date semantics, query validation,
ordering and paging, authorization (current dev-auth behavior only —
production authentication is NOT implemented and not claimed) and
zero-write checks over the mock repository.

Separate test groups characterize EXISTING behavior (finding creation,
retries, repair linkage, later PASS, ungated legacy routes). They pin
current behavior only; they are not newly approved production rules.

Test names carry the 7E1 Final PLANNED test id (tNN). The Google Sheets
read path is covered in test_inspection_finding_report_sheets_batch7e2.py.
All fixtures are synthetic, not company fleet data.
"""
from __future__ import annotations

import copy
import inspect
import random
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.domain import inspection_finding_report as rpt
from app.domain.asset import AssetType
from app.domain.inspection import FindingStatus, InspectionDetail, InspectionFinding
from app.domain.inspection_finding_report import (
    DEFECT_ORDER,
    InspectionFindingReportRead,
    ReportFilter,
    build_report,
    build_report_row,
    classify_code,
    classify_created_at,
    text_value,
)
from app.domain.inspection_finding_report_service import InspectionFindingReportService
from app.errors import ApiError
from app.repositories.base import RepositoryError, RepositorySchemaError
from app.repositories.google_sheets.repository import GoogleSheetsRepository
from app.repositories.mock import MockRepository

URL = "/api/v1/reports/inspection-findings"
BANGKOK = ZoneInfo("Asia/Bangkok")
UTC = timezone.utc

# The REAL, unchanged legacy Sheets finding mapper (no I/O happens in it).
SHEETS_MAPPER = GoogleSheetsRepository(
    Settings(google_sheet_id="unused", google_application_credentials="unused.json")
)._inspection_finding_from_row
MODEL_MAPPER = InspectionFinding.model_validate

# 7E1 Final 5.3.8 base row (Sheets-shaped cell values).
BASE = dict(
    finding_id="FND-0100",
    inspection_id="INS-0100",
    result_id="RES-0100",
    asset_type="VEHICLE",
    asset_id="VEH-1046",
    item_title="รายการตรวจ 1",
    is_critical="FALSE",
    status="OPEN",
    created_at="2026-09-28T02:10:00+00:00",
)

_WRITE_PREFIXES = (
    "create_", "add_", "assign_", "close_", "update_", "mark_", "append_",
    "record_", "end_", "set_", "delete_", "change_", "install_", "remove_",
    "upsert_", "save_", "acknowledge_", "mute_", "resolve_", "submit_", "convert_",
    "capture_", "reconcile_", "ensure_",
)


def _rec(**overrides: object) -> dict:
    record = dict(BASE)
    record.update(overrides)
    return record


def _rows(records: list[dict], mapper: Callable = SHEETS_MAPPER):
    return [build_report_row(i, r, mapper) for i, r in enumerate(records)]


def _build(records: list[dict], mapper: Callable = SHEETS_MAPPER, *, asset_type=None, created_from=None,
           created_to=None, page: int = 1, page_size: int = 200):
    return build_report(
        _rows(records, mapper), ReportFilter(asset_type, created_from, created_to), page, page_size
    )


def _finding(fid: object = "FND-0001", **overrides: object) -> InspectionFinding:
    """Typed finding. `model_construct` stores values exactly as given, so a
    diagnostic test can inject malformed values (NOT genuine mock data)."""
    values: dict[str, object] = dict(
        finding_id=fid,
        inspection_id="INS-0001",
        result_id="RES-0001",
        asset_type=AssetType.VEHICLE,
        asset_id="VEH-1046",
        item_title="รายการตรวจ 1",
        is_critical=False,
        status=FindingStatus.OPEN,
        created_at=datetime(2026, 9, 28, 2, 10, tzinfo=UTC),
    )
    values.update(overrides)
    return InspectionFinding.model_construct(**values)


class _SpyRepository(MockRepository):
    """Mock repository whose stored findings are exactly the given list
    (storage order = list order), recording every public coroutine call."""

    def __init__(self, findings: list[InspectionFinding] | None = None) -> None:
        super().__init__()
        self.calls: list[str] = []
        for i, f in enumerate(findings or []):
            self._inspections[f"SEED-{i:04d}"] = InspectionDetail.model_construct(
                header=None, items=[], findings=[f]
            )

    def __getattribute__(self, name: str):
        attr = super().__getattribute__(name)
        if not name.startswith("_") and inspect.iscoroutinefunction(attr):
            calls = super().__getattribute__("calls")

            async def wrapper(*args, **kwargs):
                calls.append(name)
                return await attr(*args, **kwargs)

            return wrapper
        return attr

    def writes(self) -> list[str]:
        return [c for c in self.calls if c.startswith(_WRITE_PREFIXES)]

    def stored(self) -> list[dict]:
        return [
            {n: getattr(f, n, None) for n in InspectionFinding.model_fields}
            for d in self._inspections.values()
            for f in d.findings
        ]


class _MapperRepository(_SpyRepository):
    """Uses a caller-supplied mapper gate on the stored findings (diagnostic
    only: exercises the exception boundary through the API)."""

    def __init__(self, findings, mapper) -> None:
        super().__init__(findings)
        self._mapper = mapper

    async def read_inspection_findings_for_report(self):
        fields = tuple(InspectionFinding.model_fields)
        rows = []
        for d in self._inspections.values():
            for f in d.findings:
                record = {n: getattr(f, n, None) for n in fields}
                rows.append(build_report_row(len(rows), record, self._mapper))
        return InspectionFindingReportRead(rows=rows)


class _FailingRepository(_SpyRepository):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    async def read_inspection_findings_for_report(self):
        raise self._exc


async def _request(repo, method: str, path: str, headers: dict | None = None, json: dict | None = None,
                   env: dict[str, str] | None = None, monkeypatch=None):
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    if env:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    if repo is not None:
        app.dependency_overrides[get_repository] = lambda: repo
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers or {}, json=json)
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


async def _api(repo, path: str = URL, headers: dict | None = None):
    return await _request(repo, "GET", path, headers=headers)


async def _report(repo, **kwargs):
    params = dict(asset_type=None, created_from=None, created_to=None, page=1, page_size=200)
    params.update(kwargs)
    return await InspectionFindingReportService(repo).get_report(**params)


def _assert_equations(report, rows=None) -> None:
    p = report.population
    assert p.read_record_count == p.readable_count + p.issue_row_count
    assert report.complete == (p.issue_row_count == 0)
    assert report.total_items <= p.readable_count
    assert sum(report.data_issues.issue_defect_counts.values()) >= p.issue_row_count
    assert report.data_issues.issue_rows_without_usable_id <= p.issue_row_count
    if rows is not None:
        readable = {r.read_index for r in rows if r.readable}
        issue = {r.read_index for r in rows if not r.readable}
        assert readable.isdisjoint(issue)
        assert readable | issue == set(range(len(rows)))
        assert (len(readable), len(issue)) == (p.readable_count, p.issue_row_count)


# ---------------------------------------------------------------------------
# T01-T03, T06-T08 — characterization of EXISTING creation / linkage
# behavior (mock). Not newly approved rules; the report only reads.
# ---------------------------------------------------------------------------


async def _checklist_items(client: AsyncClient, asset_type: str) -> list[dict]:
    response = await client.get("/api/v1/checklists/active", params={"asset_type": asset_type})
    assert response.status_code == 200
    return sorted(response.json()["items"], key=lambda i: i["sequence"])


async def _submit(client, asset_type: str, asset_id: str, results: list[str], headers=None) -> dict:
    items = await _checklist_items(client, asset_type)
    answers = [
        {"item_id": item["item_id"], "result": results[i] if i < len(results) else "PASS"}
        for i, item in enumerate(items)
    ]
    response = await client.post(
        "/api/v1/inspections",
        json={"asset_type": asset_type, "asset_id": asset_id, "items": answers},
        headers=headers or {},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_t01_one_fail_item_gives_one_report_row_pass_and_na_give_none(client: AsyncClient) -> None:
    empty = (await client.get(URL)).json()
    assert empty["total_items"] == 0 and empty["population"]["read_record_count"] == 0

    detail = await _submit(client, "VEHICLE", "VEH-1046", ["FAIL", "NA", "PASS"])
    fail_results = [i for i in detail["items"] if i["result"] == "FAIL"]
    assert len(fail_results) == 1 and len(detail["findings"]) == 1

    body = (await client.get(URL)).json()
    assert body["total_items"] == 1 and body["complete"] is True
    row = body["items"][0]
    assert row["result_id"] == fail_results[0]["result_id"]
    assert row["inspection_id"] == detail["header"]["inspection_id"]
    assert (row["asset_type"], row["asset_id"], row["recorded_status"], row["flags"]) == (
        "VEHICLE", "VEH-1046", "OPEN", []
    )
    assert row["created_at"].endswith("Z")
    assert "is_critical" not in row


@pytest.mark.asyncio
async def test_t02_equipment_fail_gives_an_equipment_row(client: AsyncClient) -> None:
    await _submit(client, "VEHICLE", "VEH-1047", ["FAIL"])
    detail = await _submit(client, "EQUIPMENT", "EQP-0001", ["FAIL", "FAIL"])
    body = (await client.get(URL, params={"asset_type": "EQUIPMENT"})).json()
    assert body["total_items"] == 2
    assert {r["asset_id"] for r in body["items"]} == {"EQP-0001"}
    assert {r["finding_id"] for r in body["items"]} == {f["finding_id"] for f in detail["findings"]}
    assert body["filter"] == {"asset_type": "EQUIPMENT", "created_from": None, "created_to": None}
    assert body["population"]["read_record_count"] == 3  # whole read, not filtered


@pytest.mark.asyncio
async def test_t03_characterize_resubmission_creates_a_second_inspection_and_findings(client: AsyncClient) -> None:
    first = await _submit(client, "VEHICLE", "VEH-1046", ["FAIL"])
    second = await _submit(client, "VEHICLE", "VEH-1046", ["FAIL"])  # a client retry
    assert first["header"]["inspection_id"] != second["header"]["inspection_id"]
    body = (await client.get(URL)).json()
    assert body["total_items"] == 2
    assert len({r["finding_id"] for r in body["items"]}) == 2
    assert len({r["inspection_id"] for r in body["items"]}) == 2


async def _report_items(client) -> list[dict]:
    body = (await client.get(URL)).json()
    return body["items"]


@pytest.mark.asyncio
async def test_t06_repair_from_a_finding_then_closed_leaves_the_row_unchanged(client: AsyncClient) -> None:
    detail = await _submit(client, "VEHICLE", "VEH-1046", ["FAIL"])
    finding_id = detail["findings"][0]["finding_id"]
    before = await _report_items(client)
    repair = await client.post(
        "/api/v1/repairs",
        json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "source_type": "FINDING", "source_id": finding_id},
    )
    assert repair.status_code == 200, repair.text
    repair_id = repair.json()["repair"]["repair_id"]
    closed = await client.post(f"/api/v1/repairs/{repair_id}/close", json={"close_note": "done"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["repair"]["status"] == "CLOSED"
    after = await _report_items(client)
    assert after == before and after[0]["recorded_status"] == "OPEN"


@pytest.mark.asyncio
async def test_t07_later_all_pass_inspection_leaves_earlier_rows_unchanged(client: AsyncClient) -> None:
    await _submit(client, "VEHICLE", "VEH-1046", ["FAIL"])
    before = await _report_items(client)
    await _submit(client, "VEHICLE", "VEH-1046", [])  # all PASS
    after = await _report_items(client)
    assert after == before and len(after) == 1


@pytest.mark.asyncio
async def test_t08_repair_request_from_a_finding_leaves_the_row_unchanged(client: AsyncClient) -> None:
    detail = await _submit(client, "VEHICLE", "VEH-1046", ["FAIL"])
    finding_id = detail["findings"][0]["finding_id"]
    before = (await client.get(URL)).json()
    response = await client.post(
        "/api/v1/repair-requests",
        json={"vehicle_id": "VEH-1046", "symptom_th": "พบความผิดปกติ", "source_type": "FINDING", "source_id": finding_id},
        headers={"X-Dev-Role": "TECHNICIAN"},
    )
    assert response.status_code == 200, response.text
    after = (await client.get(URL)).json()
    assert after == before
    assert set(after["items"][0]) == {
        "finding_id", "inspection_id", "result_id", "asset_type", "asset_id",
        "item_title", "recorded_status", "created_at", "flags",
    }  # no repair column


# ---------------------------------------------------------------------------
# T11-T13 — accounting, defect order, duplicates and samples
# ---------------------------------------------------------------------------


_VALUE_POOL: dict[str, list[object]] = {
    "finding_id": ["FND-0001", "FND-0001", "FND-0002", "", "   ", None, 0, "0012"],
    "inspection_id": ["INS-0001", "", " ", None, False],
    "result_id": ["RES-0001", "", None],
    "asset_type": ["VEHICLE", "EQUIPMENT", "", None, "vehicle", 0],
    "asset_id": ["VEH-1046", "0012", "", "  ", None, 1.5],
    "item_title": ["รายการ", "", None],
    "status": ["OPEN", "", None, "CLOSED", False],
    "created_at": [
        "2026-09-28T02:10:00+00:00", "2026-09-28T09:10:00+07:00", "", None, "2026-09-29T03:32:01",
        "9999-12-31T23:59:59+00:00", "x", 0, True,
    ],
}


@pytest.mark.parametrize("seed", range(20))
def test_t11_partition_by_read_index_for_generated_mixes(seed: int) -> None:
    rnd = random.Random(seed)
    records = [
        {**BASE, **{k: rnd.choice(v) for k, v in _VALUE_POOL.items() if rnd.random() < 0.4}}
        for _ in range(rnd.randint(0, 60))
    ]
    rows = _rows(records)
    report = build_report(rows, ReportFilter(None, None, None), 1, 200)
    _assert_equations(report, rows)
    assert [r.read_index for r in rows] == list(range(len(records)))
    # Items come only from READABLE rows: match each item to exactly one readable row.
    readable_tuples = sorted(
        (r.texts["finding_id"], r.texts["result_id"], r.texts["asset_id"], r.created_at) for r in rows if r.readable
    )
    item_tuples = sorted((i.finding_id, i.result_id, i.asset_id, i.created_at) for i in report.items)
    assert item_tuples == readable_tuples
    assert report.total_items == report.population.readable_count


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"asset_id": 0, "asset_type": "", "status": "x", "created_at": "2026-09-29"},
         ["UNSUPPORTED_TEXT_VALUE", "BLANK_ASSET_TYPE", "UNRECOGNIZED_STATUS", "CREATED_AT_WITHOUT_TIMEZONE"]),
        ({"finding_id": 1, "result_id": 2.0, "item_title": False}, ["UNSUPPORTED_TEXT_VALUE"]),
        ({"asset_type": "vehicle", "asset_id": " ", "status": None, "created_at": ""},
         ["UNRECOGNIZED_ASSET_TYPE", "BLANK_ASSET_ID", "BLANK_STATUS", "MISSING_CREATED_AT"]),
        ({"created_at": "0001-01-01T00:00:00+14:00", "status": "open"},
         ["UNRECOGNIZED_STATUS", "UNREPRESENTABLE_CREATED_AT"]),
        ({"created_at": 0}, ["INVALID_CREATED_AT"]),
    ],
)
def test_t12_defects_are_unique_canonically_ordered_and_groups_exclusive(overrides, expected) -> None:
    row = _rows([_rec(**overrides)])[0]
    assert list(row.defects) == expected
    assert len(set(row.defects)) == len(row.defects)
    assert list(row.defects) == sorted(row.defects, key=DEFECT_ORDER.index)
    groups = [
        {"BLANK_ASSET_TYPE", "UNRECOGNIZED_ASSET_TYPE"},
        {"BLANK_STATUS", "UNRECOGNIZED_STATUS"},
        {"MISSING_CREATED_AT", "INVALID_CREATED_AT", "CREATED_AT_WITHOUT_TIMEZONE", "UNREPRESENTABLE_CREATED_AT"},
    ]
    assert all(len(g & set(row.defects)) <= 1 for g in groups)
    assert "UNMAPPABLE_ROW" not in row.defects and row.mapper_called is False
    report = build_report([row], ReportFilter(None, None, None), 1, 50)
    assert sum(report.data_issues.issue_defect_counts.values()) == len(expected)
    assert list(report.data_issues.issue_defect_counts) == sorted(
        report.data_issues.issue_defect_counts, key=DEFECT_ORDER.index
    )


def test_t13_duplicates_span_both_buckets_blank_ids_never_duplicate_and_samples_are_capped() -> None:
    records = [
        _rec(finding_id="FND-A"),
        _rec(finding_id="FND-A", status="CLOSED"),  # issue row with the same usable id
        _rec(finding_id=""), _rec(finding_id=""), _rec(finding_id="  "), _rec(finding_id="  "),
        _rec(finding_id="FND-B"),
    ]
    report = _build(records)
    flags = {(i.finding_id, tuple(i.flags)) for i in report.items}
    assert ("FND-A", ("DUPLICATE_FINDING_ID",)) in flags
    assert ("FND-B", ()) in flags
    assert {f for i, f in flags if i.strip() == ""} == {("BLANK_FINDING_ID",)}
    assert report.data_issues.sample_finding_ids == ["FND-A"]

    unsupported = _build([_rec(finding_id=0, status="x"), _rec(finding_id=0, status="x")])
    assert unsupported.data_issues.issue_rows_without_usable_id == 2
    assert unsupported.data_issues.sample_finding_ids == []

    many = _build([_rec(finding_id=f"FND-{n:03d}", status="bad") for n in reversed(range(25))])
    assert many.data_issues.sample_finding_ids == [f"FND-{n:03d}" for n in range(20)]
    assert many.population.issue_row_count == 25


# ---------------------------------------------------------------------------
# T14-T17 — value conversion and classification (Final 5.3.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), ("", ""), (" ", " "), ("\t", "\t"), (" X", " X"), ("0012", "0012"),
     (AssetType.EQUIPMENT, "EQUIPMENT"), (FindingStatus.OPEN, "OPEN")],
)
def test_t14_text_conversion_stage(value, expected) -> None:
    assert text_value(value) == expected
    assert rpt.is_blank_text(expected) is (expected.strip() == "")


@pytest.mark.parametrize("value", [0, 0.0, False, True, 12, 1.5, date(2026, 1, 1), datetime(2026, 1, 1), object()])
@pytest.mark.parametrize("name", ["finding_id", "inspection_id", "result_id", "asset_id", "item_title"])
def test_t15_unsupported_text_values_are_one_row_defect(name, value) -> None:
    assert text_value(value) is None
    row = _rows([_rec(**{name: value})])[0]
    assert row.defects == ("UNSUPPORTED_TEXT_VALUE",) and row.mapper_called is False
    several = _rows([_rec(finding_id=value, result_id=value, item_title=value)])[0]
    assert several.defects == ("UNSUPPORTED_TEXT_VALUE",)
    report = build_report([several], ReportFilter(None, None, None), 1, 50)
    assert report.data_issues.issue_rows_without_usable_id == 1
    assert report.data_issues.issue_defect_counts == {"UNSUPPORTED_TEXT_VALUE": 1}


@pytest.mark.parametrize(
    ("value", "status_code", "asset_code"),
    [
        (None, "BLANK_STATUS", "BLANK_ASSET_TYPE"),
        ("", "BLANK_STATUS", "BLANK_ASSET_TYPE"),
        (" ", "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
        (0, "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
        (0.0, "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
        (False, "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
        (True, "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
        ("open", "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
        (" OPEN", "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
        ("vehicle", "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
        ("VEHICLE ", "UNRECOGNIZED_STATUS", "UNRECOGNIZED_ASSET_TYPE"),
    ],
)
def test_t16_code_field_classification(value, status_code, asset_code) -> None:
    assert classify_code(value, frozenset({"OPEN"}), "BLANK_STATUS", "UNRECOGNIZED_STATUS") == (status_code, None)
    assert classify_code(
        value, frozenset({"VEHICLE", "EQUIPMENT"}), "BLANK_ASSET_TYPE", "UNRECOGNIZED_ASSET_TYPE"
    ) == (asset_code, None)


def test_t16_enum_instances_and_exact_values_are_valid() -> None:
    assert classify_code(FindingStatus.OPEN, frozenset({"OPEN"}), "B", "U") == (None, "OPEN")
    assert classify_code(AssetType.EQUIPMENT, frozenset({"VEHICLE", "EQUIPMENT"}), "B", "U") == (None, "EQUIPMENT")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "MISSING_CREATED_AT"), ("", "MISSING_CREATED_AT"),
        (" ", "INVALID_CREATED_AT"), (0, "INVALID_CREATED_AT"), (0.0, "INVALID_CREATED_AT"),
        (False, "INVALID_CREATED_AT"), (True, "INVALID_CREATED_AT"), (2026, "INVALID_CREATED_AT"),
        ("2026", "INVALID_CREATED_AT"), ("29/9/2026", "INVALID_CREATED_AT"),
        (" 2026-09-29T03:32:01+00:00", "INVALID_CREATED_AT"), ("2026-09-29T03:32:01+00:00 ", "INVALID_CREATED_AT"),
        (date(2026, 9, 29), "INVALID_CREATED_AT"),
        ("2026-09-29", "CREATED_AT_WITHOUT_TIMEZONE"), ("2026-09-29T03:32:01", "CREATED_AT_WITHOUT_TIMEZONE"),
        (datetime(2026, 9, 29), "CREATED_AT_WITHOUT_TIMEZONE"),
        ("2026-09-29T03:32:01+00:00", None), ("2026-09-29T03:32:01Z", None),
        (datetime(2026, 9, 29, tzinfo=UTC), None),
    ],
)
def test_t17_created_at_matrix(value, expected) -> None:
    code, instant, bangkok_date = classify_created_at(value)
    assert code == expected
    if expected is None:
        assert instant.tzinfo == UTC and bangkok_date == instant.astimezone(BANGKOK).date()
    else:
        assert instant is None and bangkok_date is None


# ---------------------------------------------------------------------------
# T18-T21 — legacy mapper gate discipline (Final 5.3.3 / 5.3.5)
# ---------------------------------------------------------------------------


class _SpyMapper:
    def __init__(self, inner: Callable = SHEETS_MAPPER) -> None:
        self.inner = inner
        self.args: list[dict] = []

    def __call__(self, record: dict):
        self.args.append(record)
        return self.inner(record)


def test_t18_mapper_called_once_per_field_clean_row_and_never_otherwise() -> None:
    records = [
        _rec(), _rec(finding_id=None), _rec(item_title=""), _rec(inspection_id="   "),  # field-clean
        _rec(asset_type="vehicle"),  # D2 row i5 shape
        _rec(asset_id=None), _rec(status=""), _rec(created_at="9999-12-31T23:59:59+00:00"),
    ]
    spy = _SpyMapper()
    rows = _rows(records, spy)
    assert [r.mapper_called for r in rows] == [True, True, True, True, False, False, False, False]
    assert len(spy.args) == 4
    assert rows[4].defects == ("UNRECOGNIZED_ASSET_TYPE",)  # never also UNMAPPABLE_ROW
    assert rows[5].defects == ("BLANK_ASSET_ID",)
    for row in rows:
        if "UNMAPPABLE_ROW" in row.defects:
            assert row.defects == ("UNMAPPABLE_ROW",)


def test_t19_mapper_gets_an_unmodified_deep_copy_and_its_output_is_ignored() -> None:
    original = _rec(asset_id="0012", item_title=" padded ")
    snapshot = copy.deepcopy(original)
    received: list[dict] = []

    def mutating_mapper(record: dict):
        received.append(copy.deepcopy(record))
        record["asset_id"] = "CHANGED"
        record["item_title"] = "CHANGED"
        return {"finding_id": "OTHER", "asset_id": "OTHER"}

    report = _build([original], mutating_mapper)
    assert received == [snapshot]
    assert original == snapshot
    item = report.items[0]
    assert (item.asset_id, item.item_title, item.finding_id) == ("0012", " padded ", "FND-0100")


@pytest.mark.parametrize("exc", [ValueError("x"), TypeError("x"), OverflowError("x")])
def test_t20_narrow_mapper_exceptions_make_exactly_unmappable_row(exc) -> None:
    def raising(record):
        raise exc

    row = _rows([_rec()], raising)[0]
    assert row.defects == ("UNMAPPABLE_ROW",) and row.mapper_called


@pytest.mark.parametrize("exc", [KeyError("finding_id"), AttributeError("x"), RuntimeError("boom secret")])
def test_t20_other_mapper_exceptions_propagate(exc) -> None:
    def raising(record):
        raise exc

    with pytest.raises(type(exc)):
        _rows([_rec()], raising)


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [KeyError("finding_id"), AttributeError("x"), RuntimeError("boom secret")])
async def test_t20_other_mapper_exceptions_are_generic_500_without_report_data(exc) -> None:
    def raising(record):
        raise exc

    response = await _api(_MapperRepository([_finding()], raising))
    assert response.status_code == 500
    body = response.json()
    assert list(body) == ["error"] and body["error"]["code"] == "INTERNAL_ERROR"
    for leaked in ("items", "total_items", "population", "secret", "Traceback"):
        assert leaked not in response.text


@pytest.mark.parametrize("value", ["", "maybe", 0, "TRUE", "FALSE", " ", None, 1.5])
def test_t21_is_critical_never_changes_the_report_through_the_sheets_mapper(value) -> None:
    baseline = _build([_rec()])
    changed = _build([_rec(is_critical=value)])
    assert changed == baseline
    assert "is_critical" not in {f for f in vars(changed.items[0])}


# ---------------------------------------------------------------------------
# T22-T27 — datetime representability and extreme query dates
# ---------------------------------------------------------------------------


EXTREMES = [
    "9999-12-31T23:59:59+00:00", "9999-12-31T17:00:00+00:00",
    "0001-01-01T00:00:00+14:00", "0001-01-01T06:59:59+07:00",
]


def test_t22_unrepresentable_timestamps_are_row_defects_not_request_failures() -> None:
    records = [_rec(finding_id="FND-OK")] + [_rec(finding_id=f"FND-X{i}", created_at=v) for i, v in enumerate(EXTREMES)]
    rows = _rows(records)
    report = build_report(rows, ReportFilter(None, None, None), 1, 50)
    assert [i.finding_id for i in report.items] == ["FND-OK"]
    assert report.complete is False
    assert report.data_issues.issue_defect_counts == {"UNREPRESENTABLE_CREATED_AT": 4}
    assert report.data_issues.sample_finding_ids == ["FND-X0", "FND-X1", "FND-X2", "FND-X3"]
    _assert_equations(report, rows)


def test_t23_representable_extremes_are_readable_ordered_and_bangkok_dated_by_zoneinfo() -> None:
    late = "9999-12-31T16:59:59+00:00"
    early = "0001-01-01T00:00:00+00:00"
    report = _build([_rec(finding_id="E", created_at=early), _rec(finding_id="M"), _rec(finding_id="L", created_at=late)])
    assert [i.finding_id for i in report.items] == ["L", "M", "E"]
    rows = _rows([_rec(created_at=late), _rec(created_at=early)])
    assert rows[0].bangkok_date == date(9999, 12, 31)
    assert rows[1].bangkok_date == date(1, 1, 1)
    # tzdata gives Bangkok its historical LMT offset for this instant.
    assert datetime(1, 1, 1, tzinfo=UTC).astimezone(BANGKOK).utcoffset() == timedelta(hours=6, minutes=42, seconds=4)


@pytest.mark.asyncio
async def test_t23_extreme_readable_timestamps_serialize_as_utc_instants() -> None:
    repo = _SpyRepository([
        _finding("FND-L", created_at=datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=7)))),
        _finding("FND-E", created_at=datetime(1, 1, 1, tzinfo=UTC)),
    ])
    body = (await _api(repo)).json()
    assert [(i["finding_id"], i["created_at"]) for i in body["items"]] == [
        ("FND-L", "9999-12-31T16:59:59Z"), ("FND-E", "0001-01-01T00:00:00Z"),
    ]


@pytest.mark.asyncio
async def test_t24_all_rows_unreadable_is_an_explicit_incomplete_empty() -> None:
    repo = _SpyRepository([
        _finding("FND-1", status="CLOSED"),
        _finding("FND-2", created_at=datetime(2026, 9, 29)),
        _finding("FND-3", asset_id=""),
    ])
    body = (await _api(repo)).json()
    assert body["items"] == [] and body["total_items"] == 0 and body["complete"] is False
    assert body["population"] == {"read_record_count": 3, "readable_count": 0, "issue_row_count": 3}
    assert body["data_issues"]["issue_defect_counts"] == {
        "BLANK_ASSET_ID": 1, "UNRECOGNIZED_STATUS": 1, "CREATED_AT_WITHOUT_TIMEZONE": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["created_from=0001-01-01&created_to=9999-12-31", "created_to=9999-12-31", "created_from=9999-12-31",
     "created_to=0001-01-01", "created_from=0001-01-01"],
)
async def test_t25_extreme_query_dates_do_not_overflow(query: str) -> None:
    repo = _SpyRepository([
        _finding("FND-L", created_at=datetime(9999, 12, 31, 16, 59, 59, tzinfo=UTC)),
        _finding("FND-M"),
        _finding("FND-E", created_at=datetime(1, 1, 1, tzinfo=UTC)),
    ])
    response = await _api(repo, f"{URL}?{query}")
    assert response.status_code == 200
    expected = {
        "created_from=0001-01-01&created_to=9999-12-31": ["FND-L", "FND-M", "FND-E"],
        "created_to=9999-12-31": ["FND-L", "FND-M", "FND-E"],
        "created_from=9999-12-31": ["FND-L"],
        "created_to=0001-01-01": ["FND-E"],
        "created_from=0001-01-01": ["FND-L", "FND-M", "FND-E"],
    }[query]
    assert [i["finding_id"] for i in response.json()["items"]] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["created_from", "created_to"])
async def test_t26_year_zero_is_invalid_date(field: str) -> None:
    repo = _SpyRepository([_finding()])
    response = await _api(repo, f"{URL}?{field}=0000-01-01")
    assert response.status_code == 422
    error = response.json()["error"]["details"]["errors"][0]
    assert (error["field"], error["reason"], error["input"]) == (field, "INVALID_DATE", "0000-01-01")
    assert repo.calls == []


@pytest.mark.asyncio
async def test_t27_overflow_outside_the_defined_catches_is_not_swallowed(monkeypatch) -> None:
    def overflow(row, report_filter):
        raise OverflowError("injected outside the representability step")

    monkeypatch.setattr(rpt, "_matches", overflow)
    response = await _api(_SpyRepository([_finding()]))
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "items" not in response.text


# ---------------------------------------------------------------------------
# T46-T48 — date filter boundaries, strict parsing, no clock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "created_from", "created_to", "included"),
    [
        ("2026-09-27T16:59:59+00:00", date(2026, 9, 28), None, False),
        ("2026-09-27T17:00:00+00:00", date(2026, 9, 28), None, True),
        ("2026-09-28T16:59:59+00:00", None, date(2026, 9, 28), True),
        ("2026-09-28T17:00:00+00:00", None, date(2026, 9, 28), False),
    ],
)
def test_t46_bangkok_calendar_date_boundaries(instant, created_from, created_to, included) -> None:
    report = _build([_rec(created_at=instant)], created_from=created_from, created_to=created_to)
    assert (report.total_items == 1) is included
    assert report.population.readable_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["2026-02-30", "20260928", "2026-W40-1", "2026-09-28%0A", "2026-09-28T00:00:00",
                                   "2026-9-28", " 2026-09-28", "0000-01-01"])
@pytest.mark.parametrize("field", ["created_from", "created_to"])
async def test_t47_strict_date_parsing(field: str, value: str) -> None:
    repo = _SpyRepository([_finding()])
    response = await _api(repo, f"{URL}?{field}={value.replace(' ', '%20')}")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    error = body["error"]["details"]["errors"][0]
    assert (error["field"], error["reason"]) == (field, "INVALID_DATE")
    assert error["loc"] == ["query", field]
    assert repo.calls == []


@pytest.mark.asyncio
async def test_t47_created_from_after_created_to() -> None:
    repo = _SpyRepository([_finding()])
    response = await _api(repo, f"{URL}?created_from=2026-10-02&created_to=2026-10-01")
    assert response.status_code == 422
    error = response.json()["error"]["details"]["errors"][0]
    assert (error["field"], error["reason"], error["msg"], error["input"]) == (
        "created_from", "AFTER_CREATED_TO", "created_from is after created_to", "2026-10-02"
    )
    assert repo.calls == []
    same_day = await _api(repo, f"{URL}?created_from=2026-10-01&created_to=2026-10-01")
    assert same_day.status_code == 200


@pytest.mark.asyncio
async def test_t48_no_clock_is_read(monkeypatch) -> None:
    import app.domain.common as common

    def no_clock():
        raise AssertionError("the report must not read a clock")

    monkeypatch.setattr(common, "bangkok_today", no_clock)
    monkeypatch.setattr(common, "utc_now", no_clock)
    response = await _api(_SpyRepository([_finding()]), f"{URL}?created_from=2026-09-01")
    assert response.status_code == 200 and response.json()["total_items"] == 1
    for module in (rpt, __import__("app.domain.inspection_finding_report_service", fromlist=["x"])):
        source = inspect.getsource(module)
        assert "now(" not in source and "today(" not in source and "utc_now" not in source


# ---------------------------------------------------------------------------
# T49-T51 — authorization, writes, existing exposures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["UNKNOWN", "GUEST"])
async def test_t49_denied_role_reads_nothing(role: str) -> None:
    repo = _SpyRepository([_finding("FND-SECRET")])
    response = await _api(repo, f"{URL}?created_from=2026-01-01", headers={"X-Dev-Role": role})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HTTP_ERROR" and "FND-SECRET" not in response.text
    assert repo.calls == []


@pytest.mark.asyncio
async def test_t49_anonymous_context_reads_nothing(monkeypatch) -> None:
    repo = _SpyRepository([_finding("FND-SECRET")])
    response = await _request(repo, "GET", URL, env={"DEV_AUTH_MODE": "false"}, monkeypatch=monkeypatch)
    assert response.status_code == 403 and "FND-SECRET" not in response.text
    assert repo.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER"])
async def test_t49_every_can_view_role_is_allowed(role: str) -> None:
    response = await _api(_SpyRepository([_finding()]), URL, headers={"X-Dev-Role": role})
    assert response.status_code == 200 and response.json()["total_items"] == 1


@pytest.mark.asyncio
async def test_error_envelopes_carry_no_report_data() -> None:
    cases = [
        (RepositorySchemaError("inspection_findings", "MISSING_HEADERS", ("status",)), 500, "INSPECTION_FINDING_SCHEMA_INVALID"),
        (RepositoryError("Google Sheets reading failed: fake.json"), 503, "INSPECTION_FINDING_READ_FAILED"),
        (RuntimeError("boom secret"), 500, "INTERNAL_ERROR"),
    ]
    for exc, status_code, code in cases:
        response = await _api(_FailingRepository(exc))
        assert response.status_code == status_code
        body = response.json()
        assert list(body) == ["error"] and body["error"]["code"] == code and body["error"]["request_id"]
        for leaked in ("items", "total_items", "population", "data_issues", "complete", "fake.json", "secret"):
            assert leaked not in response.text
        if code == "INSPECTION_FINDING_SCHEMA_INVALID":
            assert body["error"]["details"] == {
                "tab": "inspection_findings", "problem": "MISSING_HEADERS", "headers": ["status"],
            }
        else:
            assert body["error"]["details"] is None


def _zero_write_scenarios() -> dict[str, tuple[Callable[[], _SpyRepository], str, dict[str, str]]]:
    mixed = lambda: _SpyRepository([  # noqa: E731
        _finding("FND-A"), _finding("FND-A", status="CLOSED"), _finding("", asset_id=None),
        _finding("FND-X", created_at=datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)),
    ])
    unreadable = lambda: _SpyRepository([_finding("FND-U", status="")])  # noqa: E731
    return {
        "success": (mixed, f"{URL}?created_from=2026-01-01&created_to=2030-01-01", {}),
        "partial": (mixed, URL, {}),
        "all_unreadable": (unreadable, URL, {}),
        "empty": (lambda: _SpyRepository([]), URL, {}),
        "filtered": (mixed, f"{URL}?asset_type=EQUIPMENT", {}),
        "paged": (mixed, f"{URL}?page=2&page_size=1", {}),
        "out_of_range": (mixed, f"{URL}?page=50", {}),
        "validation": (mixed, f"{URL}?created_from=2031-01-01&created_to=2030-01-01", {}),
        "invalid_date": (mixed, f"{URL}?created_to=2026-02-30", {}),
        "denied": (mixed, URL, {"X-Dev-Role": "UNKNOWN"}),
        "schema_error": (lambda: _FailingRepository(RepositorySchemaError("inspection_findings", "TAB_MISSING")), URL, {}),
        "read_error": (lambda: _FailingRepository(RepositoryError("x")), URL, {}),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(_zero_write_scenarios()))
async def test_t50_report_never_writes_or_uses_other_reads(scenario: str) -> None:
    factory, path, headers = _zero_write_scenarios()[scenario]
    repo = factory()
    before = repo.stored()
    for _ in range(3):  # retries
        await _api(repo, path, headers=headers)
    assert repo.writes() == []
    assert set(repo.calls) <= {"read_inspection_findings_for_report"}
    assert len(repo.calls) <= 3
    assert repo.stored() == before


@pytest.mark.asyncio
async def test_t51_characterize_existing_ungated_inspection_routes(monkeypatch) -> None:
    """Existing exposures E1-E3 (recorded, NOT approved and NOT changed by
    this batch): with dev auth off, an anonymous caller can submit an
    inspection and read findings/inspections; the report itself is 403."""
    repo = MockRepository()
    env = {"DEV_AUTH_MODE": "false"}
    checklist = await _request(repo, "GET", "/api/v1/checklists/active?asset_type=VEHICLE", env=env, monkeypatch=monkeypatch)
    items = [{"item_id": i["item_id"], "result": "FAIL"} for i in checklist.json()["items"]]
    submitted = await _request(
        repo, "POST", "/api/v1/inspections", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046", "items": items},
        env=env, monkeypatch=monkeypatch,
    )
    assert submitted.status_code == 200 and submitted.json()["header"]["inspector_user_id"] is None
    findings = await _request(repo, "GET", "/api/v1/findings", env=env, monkeypatch=monkeypatch)
    assert findings.status_code == 200 and len(findings.json()) == len(items)
    inspections = await _request(repo, "GET", "/api/v1/inspections", env=env, monkeypatch=monkeypatch)
    assert inspections.status_code == 200 and inspections.json()["total_items"] == 1
    report = await _request(repo, "GET", URL, env=env, monkeypatch=monkeypatch)
    assert report.status_code == 403


# ---------------------------------------------------------------------------
# T52-T53 — pagination and ordering
# ---------------------------------------------------------------------------


def test_t52_fixed_dataset_pages_cover_readable_rows_exactly_once() -> None:
    records = []
    for n in range(140):
        fid = "FND-DUP" if n % 7 == 0 else ("" if n % 11 == 0 else f"FND-{n:03d}")
        minute = n % 13  # many equal instants
        records.append(_rec(finding_id=fid, result_id=f"TAG-{n:03d}", created_at=f"2026-09-28T02:{minute:02d}:00+00:00",
                            status="bad" if n % 10 == 9 else "OPEN"))
    rows = _rows(records)
    tag_to_index = {r.texts["result_id"]: r.read_index for r in rows}
    readable = {r.read_index for r in rows if r.readable}
    assert len(readable) == 126
    pages = [build_report(rows, ReportFilter(None, None, None), p, 50) for p in (1, 2, 3, 4)]
    seen = [tag_to_index[i.result_id] for page in pages for i in page.items]
    assert [len(p.items) for p in pages] == [50, 50, 26, 0]
    assert len(seen) == len(set(seen)) and set(seen) == readable
    assert all(p.total_items == 126 and p.population.read_record_count == 140 for p in pages)
    whole = build_report(rows, ReportFilter(None, None, None), 1, 200)
    assert [tag_to_index[i.result_id] for i in whole.items] == seen


def test_t53_tie_order_instant_desc_then_finding_id_then_read_index() -> None:
    records = [
        _rec(finding_id="B", result_id="r0", created_at="2026-09-28T09:10:00+07:00"),  # same instant as below
        _rec(finding_id="A", result_id="r1", created_at="2026-09-28T02:10:00+00:00"),
        _rec(finding_id="", result_id="r2", created_at="2026-09-28T02:10:00Z"),
        _rec(finding_id="A", result_id="r3", created_at="2026-09-28T02:10:00+00:00"),
        _rec(finding_id="Z", result_id="r4", created_at="2026-09-28T02:10:01+00:00"),
    ]
    report = _build(records)
    assert [i.result_id for i in report.items] == ["r4", "r2", "r1", "r3", "r0"]


# ---------------------------------------------------------------------------
# T66-T70 — REAL mapper None / "" / whitespace (Final 5.3.8)
# ---------------------------------------------------------------------------


def _one_row(field: str, value, mapper: Callable = SHEETS_MAPPER):
    spy = _SpyMapper(mapper)
    rows = _rows([_rec(**{field: value})], spy)
    return rows[0], build_report(rows, ReportFilter(None, None, None), 1, 50), len(spy.args)


# field, value -> (mapper called, defects, flags, readable/issue, complete, no-id, samples)
_TABLE_5_3_8 = {
    ("finding_id", None): (1, ("UNMAPPABLE_ROW",), None, (0, 1), False, 1, []),
    ("finding_id", ""): (1, (), ["BLANK_FINDING_ID"], (1, 0), True, 0, []),
    ("finding_id", "   "): (1, (), ["BLANK_FINDING_ID"], (1, 0), True, 0, []),
    ("inspection_id", None): (1, ("UNMAPPABLE_ROW",), None, (0, 1), False, 0, ["FND-0100"]),
    ("inspection_id", ""): (1, (), ["BLANK_INSPECTION_ID"], (1, 0), True, 0, []),
    ("inspection_id", "   "): (1, (), ["BLANK_INSPECTION_ID"], (1, 0), True, 0, []),
    ("result_id", None): (1, ("UNMAPPABLE_ROW",), None, (0, 1), False, 0, ["FND-0100"]),
    ("result_id", ""): (1, (), ["BLANK_RESULT_ID"], (1, 0), True, 0, []),
    ("result_id", "   "): (1, (), ["BLANK_RESULT_ID"], (1, 0), True, 0, []),
    ("item_title", None): (1, ("UNMAPPABLE_ROW",), None, (0, 1), False, 0, ["FND-0100"]),
    ("item_title", ""): (1, (), [], (1, 0), True, 0, []),
    ("item_title", "   "): (1, (), [], (1, 0), True, 0, []),
    ("asset_id", None): (0, ("BLANK_ASSET_ID",), None, (0, 1), False, 0, ["FND-0100"]),
    ("asset_id", ""): (0, ("BLANK_ASSET_ID",), None, (0, 1), False, 0, ["FND-0100"]),
    ("asset_id", "   "): (0, ("BLANK_ASSET_ID",), None, (0, 1), False, 0, ["FND-0100"]),
}


def _assert_table_line(field: str, value) -> None:
    called, defects, flags, (readable, issues), complete, no_id, samples = _TABLE_5_3_8[(field, value)]
    row, report, calls = _one_row(field, value)
    assert calls == called and row.mapper_called is bool(called)
    assert row.defects == defects
    assert ("READABLE" if row.readable else "ISSUE") == ("READABLE" if not defects else "ISSUE")
    p = report.population
    assert (p.read_record_count, p.readable_count, p.issue_row_count) == (1, readable, issues)
    assert report.complete is complete
    assert report.data_issues.issue_rows_without_usable_id == no_id
    assert report.data_issues.sample_finding_ids == samples
    if flags is None:
        assert report.items == []
    else:
        assert report.items[0].flags == flags
        assert getattr(report.items[0], field) == value  # returned unchanged


@pytest.mark.parametrize("value", [None, "", "   "])
def test_t66_finding_id_with_the_real_mapper(value) -> None:
    _assert_table_line("finding_id", value)
    if value is not None:
        # A blank id is not usable: two READABLE rows with it are never duplicates.
        report = _build([_rec(finding_id=value), _rec(finding_id=value)])
        assert [i.flags for i in report.items] == [["BLANK_FINDING_ID"], ["BLANK_FINDING_ID"]]


def test_t66_real_pydantic_rejects_none_for_the_str_field() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        SHEETS_MAPPER(_rec(finding_id=None))
    assert isinstance(pydantic.ValidationError, type) and issubclass(pydantic.ValidationError, ValueError)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_t67_inspection_id_with_the_real_mapper(value) -> None:
    _assert_table_line("inspection_id", value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_t68_result_id_with_the_real_mapper(value) -> None:
    _assert_table_line("result_id", value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_t69_item_title_with_the_real_mapper(value) -> None:
    _assert_table_line("item_title", value)


@pytest.mark.asyncio
async def test_t70a_genuine_typed_mock_data_never_yields_unmappable_rows(client: AsyncClient) -> None:
    await _submit(client, "VEHICLE", "VEH-1046", ["FAIL", "FAIL", "FAIL"])
    await _submit(client, "EQUIPMENT", "EQP-0001", ["FAIL"])
    body = (await client.get(URL)).json()
    assert body["complete"] is True and body["population"]["issue_row_count"] == 0
    assert body["total_items"] == body["population"]["readable_count"] == 4


@pytest.mark.parametrize(
    ("overrides", "sheets_defects", "model_defects"),
    [
        # _parse_bool accepts anything; the model's bool field does not.
        ({"is_critical": "maybe"}, (), ("UNMAPPABLE_ROW",)),
        ({"is_critical": "FALSE"}, (), ()),
        ({"finding_id": None}, ("UNMAPPABLE_ROW",), ("UNMAPPABLE_ROW",)),
        ({"item_title": None}, ("UNMAPPABLE_ROW",), ("UNMAPPABLE_ROW",)),
    ],
)
def test_t70b_injected_dicts_are_asserted_separately_per_mapper(overrides, sheets_defects, model_defects) -> None:
    record = _rec(**overrides)
    assert _rows([record], SHEETS_MAPPER)[0].defects == sheets_defects
    assert _rows([record], MODEL_MAPPER)[0].defects == model_defects


@pytest.mark.parametrize("value", [None, "", "   "])
def test_t70c_blank_asset_id_skips_the_mapper(value) -> None:
    _assert_table_line("asset_id", value)


def test_t70d_mapper_skipped_row_carries_only_field_level_codes() -> None:
    spy = _SpyMapper()
    rows = _rows([_rec(status="", item_title=None)], spy)
    assert rows[0].defects == ("BLANK_STATUS",) and spy.args == []


@pytest.mark.asyncio
async def test_t70_injected_none_through_the_mock_model_gate_is_unmappable() -> None:
    repo = _SpyRepository([_finding("FND-OK"), _finding(None), _finding("FND-T", item_title=None)])
    body = (await _api(repo)).json()
    assert [i["finding_id"] for i in body["items"]] == ["FND-OK"]
    assert body["data_issues"]["issue_defect_counts"] == {"UNMAPPABLE_ROW": 2}
    assert body["data_issues"]["issue_rows_without_usable_id"] == 1
    assert body["data_issues"]["sample_finding_ids"] == ["FND-T"]


# ---------------------------------------------------------------------------
# Service-level checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_maps_repository_errors() -> None:
    for exc, code, status_code in (
        (RepositorySchemaError("inspection_findings", "DUPLICATE_HEADERS", ("status",)), "INSPECTION_FINDING_SCHEMA_INVALID", 500),
        (RepositoryError("x"), "INSPECTION_FINDING_READ_FAILED", 503),
    ):
        with pytest.raises(ApiError) as info:
            await _report(_FailingRepository(exc))
        assert (info.value.code, info.value.status_code) == (code, status_code)


@pytest.mark.asyncio
async def test_response_schema_forbids_extra_fields_and_echoes_the_filter() -> None:
    repo = _SpyRepository([_finding("FND-1"), _finding("FND-2", asset_type=AssetType.EQUIPMENT, asset_id="EQP-0001")])
    body = (await _api(repo, f"{URL}?asset_type=VEHICLE&created_from=2026-09-28&created_to=2026-09-28&page_size=10")).json()
    assert list(body) == ["timezone", "filter", "items", "page", "page_size", "total_items", "complete",
                          "population", "data_issues"]
    assert body["timezone"] == "Asia/Bangkok"
    assert body["filter"] == {"asset_type": "VEHICLE", "created_from": "2026-09-28", "created_to": "2026-09-28"}
    assert [i["finding_id"] for i in body["items"]] == ["FND-1"]
    assert body["population"]["read_record_count"] == 2
