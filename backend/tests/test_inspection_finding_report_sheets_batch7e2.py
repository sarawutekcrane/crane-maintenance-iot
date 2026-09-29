"""Phase 7 Batch 7E2 — recorded inspection findings report over Google
Sheets, exercised with the REAL installed gspread client on top of the FAKE
HTTP session from the 7B2 tests (`FakeSheetsBackend`): only the network
transport is faked; every value transformation (Worksheet.get, fill_gaps,
numericise_all with its ignore list, to_records) is gspread's own code, and
the row mapper gate is the REAL unchanged `_inspection_finding_from_row`.

Covers: the approved Final example responses reproduced exactly (T09),
mock/Sheets agreement for genuine data (T10), structural validation of all
9 `inspection_findings` headers on the SAME values response versus genuine
empty data (T28-T42), leading-zero preservation through real gspread
numericising (T43), characterization of the legacy /findings route on the
same rows (T44, unchanged), measured fake-transport request counts (T65),
zero writes and single-tab reads (T45, T50), and characterization of the
EXISTING non-atomic inspection writes read back by the report (T03-T05).

No credentials, no network, no live spreadsheet; request counts are
fake-transport counts, not live Sheets performance. All fixtures are
synthetic, not company fleet data.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import gspread
import pytest

from app.domain.asset import AssetType
from app.domain.checklist import InspectionResultValue
from app.domain.inspection import FindingStatus, InspectionDetail, InspectionFinding, NewInspectionItemInput
from app.domain.inspection_finding_report_service import InspectionFindingReportService
from app.errors import ApiError
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.mock import MockRepository
from tests.test_fleet_status_summary_sheets_batch7b2 import SHEET_ID, FakeSheetsBackend, _repo
from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws
from tests.test_inspection_finding_report_batch7e2 import _SpyRepository, _request

TAB = schemas.INSPECTION_FINDING_SHEET.tab_name
HEADER = list(schemas.INSPECTION_FINDING_SHEET.required_headers)
URL = "/api/v1/reports/inspection-findings"
PROTECTED = GoogleSheetsRepository._INSPECTION_FINDING_TEXT_ONLY_HEADERS
TS = "2026-09-28T02:10:00+00:00"

# The approved 7E1 Final contract's Example 1-8 response bodies, copied
# verbatim from Section 4.5 of the Final evidence file.
FINAL_EXAMPLES = json.loads(
    r'''{
 "EX1": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": null,
   "created_from": null,
   "created_to": null
  },
  "items": [
   {
    "finding_id": "FND-0003",
    "inspection_id": "INS-0002",
    "result_id": "RES-0014",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1047",
    "item_title": "รายการตรวจ 4",
    "recorded_status": "OPEN",
    "created_at": "2026-09-28T02:10:00Z",
    "flags": []
   },
   {
    "finding_id": "FND-0001",
    "inspection_id": "INS-0001",
    "result_id": "RES-0002",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1046",
    "item_title": "รายการตรวจ 2",
    "recorded_status": "OPEN",
    "created_at": "2026-09-20T01:00:00Z",
    "flags": []
   },
   {
    "finding_id": "FND-0002",
    "inspection_id": "INS-0001",
    "result_id": "RES-0005",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1046",
    "item_title": "รายการตรวจ 5",
    "recorded_status": "OPEN",
    "created_at": "2026-09-20T01:00:00Z",
    "flags": []
   }
  ],
  "page": 1,
  "page_size": 50,
  "total_items": 3,
  "complete": true,
  "population": {
   "read_record_count": 3,
   "readable_count": 3,
   "issue_row_count": 0
  },
  "data_issues": {
   "issue_defect_counts": {},
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 0,
   "sample_finding_ids": []
  }
 },
 "EX2A": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": null,
   "created_from": null,
   "created_to": null
  },
  "items": [],
  "page": 1,
  "page_size": 50,
  "total_items": 0,
  "complete": true,
  "population": {
   "read_record_count": 0,
   "readable_count": 0,
   "issue_row_count": 0
  },
  "data_issues": {
   "issue_defect_counts": {},
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 0,
   "sample_finding_ids": []
  }
 },
 "EX2B": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": "EQUIPMENT",
   "created_from": null,
   "created_to": null
  },
  "items": [],
  "page": 1,
  "page_size": 50,
  "total_items": 0,
  "complete": true,
  "population": {
   "read_record_count": 3,
   "readable_count": 3,
   "issue_row_count": 0
  },
  "data_issues": {
   "issue_defect_counts": {},
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 0,
   "sample_finding_ids": []
  }
 },
 "EX3": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": null,
   "created_from": null,
   "created_to": null
  },
  "items": [
   {
    "finding_id": "FND-0003",
    "inspection_id": "INS-0003",
    "result_id": "RES-0020",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1048",
    "item_title": "รายการตรวจ 1",
    "recorded_status": "OPEN",
    "created_at": "2026-09-28T18:30:00Z",
    "flags": [
     "DUPLICATE_FINDING_ID"
    ]
   },
   {
    "finding_id": "FND-0003",
    "inspection_id": "INS-0002",
    "result_id": "RES-0014",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1047",
    "item_title": "รายการตรวจ 4",
    "recorded_status": "OPEN",
    "created_at": "2026-09-28T02:10:00Z",
    "flags": [
     "DUPLICATE_FINDING_ID"
    ]
   },
   {
    "finding_id": "FND-0004",
    "inspection_id": "",
    "result_id": "RES-0017",
    "asset_type": "EQUIPMENT",
    "asset_id": "EQP-0001",
    "item_title": "รายการตรวจ 3",
    "recorded_status": "OPEN",
    "created_at": "2026-09-27T16:59:59Z",
    "flags": [
     "BLANK_INSPECTION_ID"
    ]
   },
   {
    "finding_id": "FND-0001",
    "inspection_id": "INS-0001",
    "result_id": "RES-0002",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1046",
    "item_title": "รายการตรวจ 2",
    "recorded_status": "OPEN",
    "created_at": "2026-09-20T01:00:00Z",
    "flags": []
   }
  ],
  "page": 1,
  "page_size": 50,
  "total_items": 4,
  "complete": false,
  "population": {
   "read_record_count": 7,
   "readable_count": 4,
   "issue_row_count": 3
  },
  "data_issues": {
   "issue_defect_counts": {
    "UNRECOGNIZED_ASSET_TYPE": 1,
    "BLANK_STATUS": 1,
    "MISSING_CREATED_AT": 1,
    "UNREPRESENTABLE_CREATED_AT": 1
   },
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 1,
   "sample_finding_ids": [
    "FND-0005",
    "FND-0006"
   ]
  }
 },
 "EX4": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": null,
   "created_from": "2026-09-28",
   "created_to": "2026-09-28"
  },
  "items": [
   {
    "finding_id": "FND-0003",
    "inspection_id": "INS-0002",
    "result_id": "RES-0014",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1047",
    "item_title": "รายการตรวจ 4",
    "recorded_status": "OPEN",
    "created_at": "2026-09-28T02:10:00Z",
    "flags": [
     "DUPLICATE_FINDING_ID"
    ]
   }
  ],
  "page": 1,
  "page_size": 50,
  "total_items": 1,
  "complete": false,
  "population": {
   "read_record_count": 7,
   "readable_count": 4,
   "issue_row_count": 3
  },
  "data_issues": {
   "issue_defect_counts": {
    "UNRECOGNIZED_ASSET_TYPE": 1,
    "BLANK_STATUS": 1,
    "MISSING_CREATED_AT": 1,
    "UNREPRESENTABLE_CREATED_AT": 1
   },
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 1,
   "sample_finding_ids": [
    "FND-0005",
    "FND-0006"
   ]
  }
 },
 "EX5": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": null,
   "created_from": null,
   "created_to": null
  },
  "items": [
   {
    "finding_id": "FND-0010",
    "inspection_id": "INS 0010",
    "result_id": "RES-0030",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1046",
    "item_title": "รายการตรวจ 1",
    "recorded_status": "OPEN",
    "created_at": "2026-09-25T00:00:00Z",
    "flags": []
   },
   {
    "finding_id": "FND-0011",
    "inspection_id": "INS-0999",
    "result_id": "RES-0031",
    "asset_type": "EQUIPMENT",
    "asset_id": "EQP/0002",
    "item_title": "รายการตรวจ 2",
    "recorded_status": "OPEN",
    "created_at": "2026-09-24T00:00:00Z",
    "flags": []
   },
   {
    "finding_id": "",
    "inspection_id": "INS-0011",
    "result_id": "",
    "asset_type": "VEHICLE",
    "asset_id": " VEH-1047",
    "item_title": "รายการตรวจ 3",
    "recorded_status": "OPEN",
    "created_at": "2026-09-23T00:00:00Z",
    "flags": [
     "BLANK_FINDING_ID",
     "BLANK_RESULT_ID"
    ]
   },
   {
    "finding_id": "FND-0012",
    "inspection_id": "   ",
    "result_id": "RES-0033",
    "asset_type": "VEHICLE",
    "asset_id": "0012",
    "item_title": "",
    "recorded_status": "OPEN",
    "created_at": "2026-09-22T00:00:00Z",
    "flags": [
     "BLANK_INSPECTION_ID"
    ]
   }
  ],
  "page": 1,
  "page_size": 50,
  "total_items": 4,
  "complete": true,
  "population": {
   "read_record_count": 4,
   "readable_count": 4,
   "issue_row_count": 0
  },
  "data_issues": {
   "issue_defect_counts": {},
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 0,
   "sample_finding_ids": []
  }
 },
 "EX6": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": null,
   "created_from": null,
   "created_to": null
  },
  "items": [],
  "page": 5,
  "page_size": 50,
  "total_items": 3,
  "complete": true,
  "population": {
   "read_record_count": 3,
   "readable_count": 3,
   "issue_row_count": 0
  },
  "data_issues": {
   "issue_defect_counts": {},
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 0,
   "sample_finding_ids": []
  }
 },
 "EX7": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": null,
   "created_from": null,
   "created_to": null
  },
  "items": [],
  "page": 1,
  "page_size": 50,
  "total_items": 0,
  "complete": false,
  "population": {
   "read_record_count": 4,
   "readable_count": 0,
   "issue_row_count": 4
  },
  "data_issues": {
   "issue_defect_counts": {
    "BLANK_ASSET_TYPE": 1,
    "BLANK_ASSET_ID": 1,
    "UNRECOGNIZED_STATUS": 1,
    "CREATED_AT_WITHOUT_TIMEZONE": 1,
    "UNREPRESENTABLE_CREATED_AT": 1
   },
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 1,
   "sample_finding_ids": [
    "FND-0020",
    "FND-0021"
   ]
  }
 },
 "EX8": {
  "timezone": "Asia/Bangkok",
  "filter": {
   "asset_type": null,
   "created_from": "0001-01-01",
   "created_to": "9999-12-31"
  },
  "items": [
   {
    "finding_id": "FND-0003",
    "inspection_id": "INS-0003",
    "result_id": "RES-0020",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1048",
    "item_title": "รายการตรวจ 1",
    "recorded_status": "OPEN",
    "created_at": "2026-09-28T18:30:00Z",
    "flags": [
     "DUPLICATE_FINDING_ID"
    ]
   },
   {
    "finding_id": "FND-0003",
    "inspection_id": "INS-0002",
    "result_id": "RES-0014",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1047",
    "item_title": "รายการตรวจ 4",
    "recorded_status": "OPEN",
    "created_at": "2026-09-28T02:10:00Z",
    "flags": [
     "DUPLICATE_FINDING_ID"
    ]
   },
   {
    "finding_id": "FND-0004",
    "inspection_id": "",
    "result_id": "RES-0017",
    "asset_type": "EQUIPMENT",
    "asset_id": "EQP-0001",
    "item_title": "รายการตรวจ 3",
    "recorded_status": "OPEN",
    "created_at": "2026-09-27T16:59:59Z",
    "flags": [
     "BLANK_INSPECTION_ID"
    ]
   },
   {
    "finding_id": "FND-0001",
    "inspection_id": "INS-0001",
    "result_id": "RES-0002",
    "asset_type": "VEHICLE",
    "asset_id": "VEH-1046",
    "item_title": "รายการตรวจ 2",
    "recorded_status": "OPEN",
    "created_at": "2026-09-20T01:00:00Z",
    "flags": []
   }
  ],
  "page": 1,
  "page_size": 50,
  "total_items": 4,
  "complete": false,
  "population": {
   "read_record_count": 7,
   "readable_count": 4,
   "issue_row_count": 3
  },
  "data_issues": {
   "issue_defect_counts": {
    "UNRECOGNIZED_ASSET_TYPE": 1,
    "BLANK_STATUS": 1,
    "MISSING_CREATED_AT": 1,
    "UNREPRESENTABLE_CREATED_AT": 1
   },
   "issue_defect_counts_are_occurrences": true,
   "issue_rows_without_usable_id": 1,
   "sample_finding_ids": [
    "FND-0005",
    "FND-0006"
   ]
  }
 }
}'''
)


def _row(fid: str = "FND-0001", header: list[str] | None = None, **values: str) -> list[str]:
    cells = dict(
        finding_id=fid, inspection_id="INS-0001", result_id="RES-0001", asset_type="VEHICLE",
        asset_id="VEH-1046", item_title="รายการตรวจ 1", is_critical="FALSE", status="OPEN", created_at=TS,
    )
    cells.update(values)
    return [cells.get(h, "") for h in (header or HEADER)]


def _d(fid, iid, rid, at, aid, title, status, created):
    return _row(fid, inspection_id=iid, result_id=rid, asset_type=at, asset_id=aid, item_title=title,
                status=status, created_at=created)


PHANTOM = [""] * len(HEADER)

# Final 4.5 datasets (sheet order = read order).
D1 = [
    _d("FND-0001", "INS-0001", "RES-0002", "VEHICLE", "VEH-1046", "รายการตรวจ 2", "OPEN", "2026-09-20T01:00:00+00:00"),
    _d("FND-0002", "INS-0001", "RES-0005", "VEHICLE", "VEH-1046", "รายการตรวจ 5", "OPEN", "2026-09-20T01:00:00+00:00"),
    _d("FND-0003", "INS-0002", "RES-0014", "VEHICLE", "VEH-1047", "รายการตรวจ 4", "OPEN", "2026-09-28T02:10:00+00:00"),
]
D2 = [
    _d("FND-0003", "INS-0002", "RES-0014", "VEHICLE", "VEH-1047", "รายการตรวจ 4", "OPEN", "2026-09-28T02:10:00+00:00"),
    _d("FND-0003", "INS-0003", "RES-0020", "VEHICLE", "VEH-1048", "รายการตรวจ 1", "OPEN", "2026-09-28T18:30:00+00:00"),
    PHANTOM,
    _d("FND-0004", "", "RES-0017", "EQUIPMENT", "EQP-0001", "รายการตรวจ 3", "OPEN", "2026-09-27T16:59:59+00:00"),
    _d("FND-0001", "INS-0001", "RES-0002", "VEHICLE", "VEH-1046", "รายการตรวจ 2", "OPEN", "2026-09-20T01:00:00+00:00"),
    _d("FND-0005", "INS-0004", "RES-0021", "VEHICLE", "VEH-1046", "รายการตรวจ 6", "", ""),
    PHANTOM,
    _d("", "INS-0005", "RES-0022", "vehicle", "VEH-1047", "รายการตรวจ 7", "OPEN", "2026-09-26T03:00:00+00:00"),
    _d("FND-0006", "INS-0006", "RES-0023", "VEHICLE", "VEH-1048", "รายการตรวจ 8", "OPEN", "9999-12-31T23:59:59+00:00"),
]
D3 = [
    _d("FND-0010", "INS 0010", "RES-0030", "VEHICLE", "VEH-1046", "รายการตรวจ 1", "OPEN", "2026-09-25T00:00:00+00:00"),
    _d("FND-0011", "INS-0999", "RES-0031", "EQUIPMENT", "EQP/0002", "รายการตรวจ 2", "OPEN", "2026-09-24T00:00:00+00:00"),
    _d("", "INS-0011", "", "VEHICLE", " VEH-1047", "รายการตรวจ 3", "OPEN", "2026-09-23T00:00:00+00:00"),
    _d("FND-0012", "   ", "RES-0033", "VEHICLE", "0012", "", "OPEN", "2026-09-22T00:00:00+00:00"),
]
D4 = [
    _d("FND-0020", "INS-0020", "RES-0040", "VEHICLE", "VEH-1046", "รายการตรวจ 1", "CLOSED", "2026-09-21T00:00:00+00:00"),
    _d("FND-0021", "INS-0021", "RES-0041", "VEHICLE", "VEH-1047", "รายการตรวจ 2", "OPEN", "2026-09-29T03:32:01"),
    _d("  ", "INS-0022", "RES-0042", "", "", "รายการตรวจ 3", "OPEN", "2026-09-22T00:00:00+00:00"),
    _d("FND-0020", "INS-0023", "RES-0043", "VEHICLE", "VEH-1048", "รายการตรวจ 4", "OPEN", "0001-01-01T00:00:00+14:00"),
]


def _backend(rows: list[list[str]], header: list[str] | None = None, **extra_tabs) -> FakeSheetsBackend:
    tabs: dict[str, list[list[str]] | None] = {
        TAB: [list(header or HEADER), *rows],
        # Tabs the report must never read.
        "inspection_header": [list(schemas.INSPECTION_SHEET.required_headers)],
        "inspection_result": [list(schemas.INSPECTION_ITEM_RESULT_SHEET.required_headers)],
        "repair_order": [list(schemas.REPAIR_SHEET.required_headers)],
        "vehicle_master": [list(schemas.VEHICLE_SHEET.required_headers)],
    }
    tabs.update(extra_tabs)
    return FakeSheetsBackend(tabs)


async def _report(repo, **kwargs):
    params = dict(asset_type=None, created_from=None, created_to=None, page=1, page_size=200)
    params.update(kwargs)
    return await InspectionFindingReportService(repo).get_report(**params)


async def _report_error(repo, **kwargs) -> ApiError:
    with pytest.raises(ApiError) as info:
        await _report(repo, **kwargs)
    return info.value


def _assert_schema(err: ApiError, problem: str, headers: list[str] | None = None) -> None:
    assert (err.code, err.status_code) == ("INSPECTION_FINDING_SCHEMA_INVALID", 500)
    assert err.details["tab"] == TAB and err.details["problem"] == problem
    if headers is not None:
        assert err.details["headers"] == headers


def _assert_read_failed(err: ApiError) -> None:
    assert (err.code, err.status_code) == ("INSPECTION_FINDING_READ_FAILED", 503)
    assert err.details is None


async def _api(repo, path: str = URL, headers: dict | None = None):
    return await _request(repo, "GET", path, headers=headers)


# ---------------------------------------------------------------------------
# T09 — the approved Final examples, exactly
# ---------------------------------------------------------------------------


_EXAMPLE_REQUESTS = {
    "EX1": (D1, ""),
    "EX2A": ([], ""),
    "EX2B": (D1, "?asset_type=EQUIPMENT"),
    "EX3": (D2, ""),
    "EX4": (D2, "?created_from=2026-09-28&created_to=2026-09-28"),
    "EX5": (D3, ""),
    "EX6": (D1, "?page=5"),
    "EX7": (D4, ""),
    "EX8": (D2, "?created_from=0001-01-01&created_to=9999-12-31"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("example", sorted(_EXAMPLE_REQUESTS))
async def test_t09_final_examples_are_reproduced_exactly(example: str) -> None:
    rows, query = _EXAMPLE_REQUESTS[example]
    backend = _backend(rows)
    response = await _api(_repo(backend), URL + query)
    assert response.status_code == 200
    assert response.json() == FINAL_EXAMPLES[example]
    assert backend.writes == []


@pytest.mark.asyncio
async def test_t09_example_row_partition_by_read_index() -> None:
    read = await _repo(_backend(D2)).read_inspection_findings_for_report()
    partition = [(r.read_index, list(r.defects), r.mapper_called) for r in read.rows]
    assert partition == [
        (0, [], True), (1, [], True), (2, [], True), (3, [], True),
        (4, ["BLANK_STATUS", "MISSING_CREATED_AT"], False),
        (5, ["UNRECOGNIZED_ASSET_TYPE"], False),
        (6, ["UNREPRESENTABLE_CREATED_AT"], False),
    ]
    read4 = await _repo(_backend(D4)).read_inspection_findings_for_report()
    assert [(r.read_index, list(r.defects)) for r in read4.rows] == [
        (0, ["UNRECOGNIZED_STATUS"]), (1, ["CREATED_AT_WITHOUT_TIMEZONE"]),
        (2, ["BLANK_ASSET_TYPE", "BLANK_ASSET_ID"]), (3, ["UNREPRESENTABLE_CREATED_AT"]),
    ]


# ---------------------------------------------------------------------------
# T10 — mock/Sheets agreement for genuine valid data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "?asset_type=VEHICLE", "?created_from=2026-09-21&page_size=2&page=2"])
async def test_t10_mock_and_sheets_agree_on_genuine_data(query: str) -> None:
    genuine = [
        ("FND-0001", "INS-0001", "RES-0001", AssetType.VEHICLE, "VEH-1046", "รายการตรวจ 1", datetime(2026, 9, 20, 1, tzinfo=timezone.utc)),
        ("FND-0002", "INS-0001", "RES-0002", AssetType.VEHICLE, "VEH-1046", "รายการตรวจ 2", datetime(2026, 9, 20, 1, tzinfo=timezone.utc)),
        ("FND-0003", "INS-0002", "RES-0007", AssetType.EQUIPMENT, "EQP-0001", "รายการตรวจ 3", datetime(2026, 9, 22, 5, tzinfo=timezone.utc)),
        ("FND-0004", "INS-0003", "RES-0011", AssetType.VEHICLE, "0012", "รายการตรวจ 4", datetime(2026, 9, 28, 2, 10, tzinfo=timezone.utc)),
    ]
    mock = MockRepository()
    for n, (fid, iid, rid, at, aid, title, created) in enumerate(genuine):
        finding = InspectionFinding(
            finding_id=fid, inspection_id=iid, result_id=rid, asset_type=at, asset_id=aid,
            item_title=title, is_critical=False, status=FindingStatus.OPEN, created_at=created,
        )
        mock._inspections[f"INS-{n}"] = InspectionDetail.model_construct(header=None, items=[], findings=[finding])
    sheets_rows = [
        _row(fid, inspection_id=iid, result_id=rid, asset_type=at.value, asset_id=aid, item_title=title,
             created_at=created.isoformat())
        for fid, iid, rid, at, aid, title, created in genuine
    ]
    mock_body = (await _api(mock, URL + query)).json()
    sheets_body = (await _api(_repo(_backend(sheets_rows)), URL + query)).json()
    assert mock_body == sheets_body
    assert mock_body["complete"] is True


# ---------------------------------------------------------------------------
# T28-T42 — structural damage versus genuine empty data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t28_valid_header_and_zero_rows_is_a_genuine_complete_empty() -> None:
    report = await _report(_repo(_backend([])))
    assert (report.total_items, report.complete, report.population.read_record_count) == (0, True, 0)


@pytest.mark.asyncio
async def test_t29_phantom_rows_only_are_not_counted() -> None:
    report = await _report(_repo(_backend([PHANTOM] * 6 + [[""] * (len(HEADER) - 2)])))
    assert (report.population.read_record_count, report.complete) == (0, True)


@pytest.mark.asyncio
async def test_t30_all_headers_renamed_with_populated_rows_is_schema_invalid_not_empty() -> None:
    renamed = [h.upper() for h in HEADER]
    backend = _backend([_row("FND-1", header=renamed), _row("FND-2", header=renamed)], header=renamed)
    err = await _report_error(_repo(backend))
    _assert_schema(err, "MISSING_HEADERS", HEADER)
    # The unchanged legacy list on the same data is a false empty (recorded, not changed).
    assert await _repo(backend).list_inspection_findings(asset_type=None, asset_id=None, status=None) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("renamed", HEADER)
async def test_t31_t39_each_single_required_header_renamed_is_schema_invalid(renamed: str) -> None:
    header = [f"{h}_old" if h == renamed else h for h in HEADER]
    backend = _backend([_row("FND-1", header=header)], header=header)
    err = await _report_error(_repo(backend))
    _assert_schema(err, "MISSING_HEADERS", [renamed])
    assert backend.writes == []


@pytest.mark.asyncio
async def test_t40_duplicate_header_data_outside_header_and_tolerated_blank_column() -> None:
    dup = [*HEADER, "status"]
    _assert_schema(await _report_error(_repo(_backend([[*_row(), "OPEN"]], header=dup))), "DUPLICATE_HEADERS", ["status"])
    _assert_schema(await _report_error(_repo(_backend([[*_row(), "stray"]]))), "DATA_OUTSIDE_HEADER")
    with_blank = [*HEADER, ""]
    report = await _report(_repo(_backend([[*_row(), ""]], header=with_blank)))
    assert report.total_items == 1 and report.complete
    extra = [*HEADER, "note"]
    report = await _report(_repo(_backend([[*_row(), "x"]], header=extra)))
    assert report.total_items == 1
    _assert_schema(await _report_error(_repo(FakeSheetsBackend({TAB: None}))), "NO_HEADER_ROW")


@pytest.mark.asyncio
async def test_t41_cold_missing_tab_and_warm_unreachable_tab() -> None:
    _assert_schema(await _report_error(_repo(FakeSheetsBackend({"vehicle_master": [["vehicle_id"]]}))), "TAB_MISSING")
    backend = _backend([_row()])
    repo = _repo(backend)
    assert (await _report(repo)).total_items == 1
    del backend.tabs[TAB]
    _assert_read_failed(await _report_error(repo))


@pytest.mark.asyncio
async def test_t42_read_and_configuration_failures_are_read_failed() -> None:
    backend = _backend([_row()])
    backend.fail_values_get = True
    _assert_read_failed(await _report_error(_repo(backend)))
    from app.config import Settings

    unconfigured = GoogleSheetsRepository(Settings(google_sheet_id="", google_application_credentials=""))
    _assert_read_failed(await _report_error(unconfigured))


# ---------------------------------------------------------------------------
# T43 — numeric-looking values through REAL gspread numericising
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t43_text_only_columns_keep_leading_zeros_and_numeric_text() -> None:
    shuffled = list(reversed(HEADER))  # physical order differs from the declaration
    row = _row("0012", header=shuffled, inspection_id="00034", result_id="0100", asset_id="0012", item_title="007")
    backend = _backend([row], header=shuffled)
    report = await _report(_repo(backend))
    item = report.items[0]
    assert (item.finding_id, item.inspection_id, item.result_id, item.asset_id, item.item_title) == (
        "0012", "00034", "0100", "0012", "007"
    )
    # The default (unprotected) validated read WOULD have numericised them.
    default = await _repo(backend)._client.read_header_and_records(schemas.INSPECTION_FINDING_SHEET)
    assert default.records[0]["asset_id"] == 12 and default.records[0]["finding_id"] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("values", "defects"),
    [
        ({"status": "1"}, ["UNRECOGNIZED_STATUS"]),
        ({"asset_type": "0"}, ["UNRECOGNIZED_ASSET_TYPE"]),
        ({"created_at": "2026"}, ["INVALID_CREATED_AT"]),
        ({"created_at": "0"}, ["INVALID_CREATED_AT"]),
        ({"created_at": "20260928"}, ["INVALID_CREATED_AT"]),
        ({"is_critical": "1"}, []),
        ({"is_critical": "0.5"}, []),
    ],
)
async def test_t43_unprotected_numericised_cells_are_classified(values, defects) -> None:
    read = await _repo(_backend([_row("FND-1", **values)])).read_inspection_findings_for_report()
    assert list(read.rows[0].defects) == defects


# ---------------------------------------------------------------------------
# T44 — legacy /findings on the same rows (characterization; UNCHANGED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t44_characterize_legacy_findings_defaults_on_blank_or_falsy_cells() -> None:
    backend = _backend([
        _row("FND-1", status=""),
        _row("FND-2", asset_type=""),
        _row("FND-3", created_at=""),
        _row("FND-4", created_at="0"),       # gspread numericises to int 0 -> falsy -> epoch
        _row("FND-5", created_at="TRUE"),    # text, fromisoformat ValueError -> epoch
    ])
    legacy = await _repo(backend).list_inspection_findings(asset_type=None, asset_id=None, status=None)
    by_id = {f.finding_id: f for f in legacy}
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert by_id["FND-1"].status == FindingStatus.OPEN
    assert by_id["FND-2"].asset_type == AssetType.VEHICLE
    assert by_id["FND-3"].created_at == by_id["FND-4"].created_at == by_id["FND-5"].created_at == epoch
    report = await _report(_repo(backend))
    assert report.total_items == 0 and report.population.issue_row_count == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [{"created_at": "2026"}, {"status": "CLOSED"}, {"asset_type": "vehicle"}])
async def test_t44_characterize_legacy_findings_whole_list_failure_on_one_row(values) -> None:
    backend = _backend([_row("FND-OK"), _row("FND-BAD", **values)])
    with pytest.raises((TypeError, ValueError)):
        await _repo(backend).list_inspection_findings(asset_type=None, asset_id=None, status=None)
    legacy_api = await _api(_repo(backend), "/api/v1/findings")
    assert legacy_api.status_code == 500
    report = await _report(_repo(backend))
    assert [i.finding_id for i in report.items] == ["FND-OK"] and report.population.issue_row_count == 1


# ---------------------------------------------------------------------------
# T45, T50, T65 — single-tab reads, zero writes, measured request counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t45_blank_inspection_id_is_flagged_and_only_the_findings_tab_is_read() -> None:
    backend = _backend([_row("FND-1", inspection_id=""), _row("FND-2", inspection_id="   ")])
    report = await _report(_repo(backend))
    assert [i.flags for i in report.items] == [["BLANK_INSPECTION_ID"], ["BLANK_INSPECTION_ID"]]
    assert {tab for _, kind, tab in backend.requests if kind == "values"} == {TAB}


@pytest.mark.asyncio
async def test_t65_measured_request_counts_cold_spreadsheet_cached_and_warm() -> None:
    """Measured (fake transport; counts only, NO latency): cold 2 metadata +
    1 values; spreadsheet cached 1 metadata + 1 values; warm 1 values.
    Only the inspection_findings tab is read; the header cache is untouched."""
    backend = _backend(D1)
    repo = _repo(backend)
    await _report(repo)
    cold = list(backend.requests)

    backend2 = _backend(D1)
    repo2 = _repo(backend2)
    await repo2._client.read_header_and_records(schemas.VEHICLE_SHEET)  # caches the spreadsheet only
    backend2.requests.clear()
    await _report(repo2)
    cached = list(backend2.requests)

    backend.requests.clear()
    await _report(repo)
    warm = list(backend.requests)

    assert cold == [("get", "metadata", None), ("get", "metadata", None), ("get", "values", TAB)]
    assert cached == [("get", "metadata", None), ("get", "values", TAB)]
    assert warm == [("get", "values", TAB)]
    assert backend.writes == [] and backend2.writes == []
    assert repo._client._header_cache == {}


_ZERO_WRITE_SCENARIOS = {
    "valid": lambda: _backend(D1),
    "partial": lambda: _backend(D2),
    "all_unreadable": lambda: _backend(D4),
    "empty": lambda: _backend([]),
    "renamed_status": lambda: _backend([_row()], header=["Status" if h == "status" else h for h in HEADER]),
    "data_outside_header": lambda: _backend([[*_row(), "x"]]),
    "tab_missing": lambda: FakeSheetsBackend({"vehicle_master": [["vehicle_id"]]}),
    "read_error": lambda: (lambda b: (setattr(b, "fail_values_get", True), b)[1])(_backend([_row()])),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(_ZERO_WRITE_SCENARIOS))
async def test_t50_report_never_writes_and_reads_only_the_findings_tab(scenario: str) -> None:
    backend = _ZERO_WRITE_SCENARIOS[scenario]()
    before = backend.snapshot()
    for query in ("", "?asset_type=EQUIPMENT", "?created_from=2031-01-01", "?page=7",
                  "?created_from=2031-01-02&created_to=2031-01-01", "?created_to=2026-02-30"):
        await _api(_repo(backend), URL + query)
    assert backend.writes == []
    assert backend.snapshot() == before
    assert {tab for _, kind, tab in backend.requests if kind == "values"} <= {TAB}


@pytest.mark.asyncio
async def test_t49_denied_request_performs_zero_transport_requests() -> None:
    backend = _backend(D1)
    response = await _api(_repo(backend), URL, headers={"X-Dev-Role": "UNKNOWN"})
    assert response.status_code == 403
    assert backend.requests == [] and backend.writes == []


@pytest.mark.asyncio
async def test_shared_reader_default_and_legacy_reads_are_unchanged() -> None:
    backend = _backend(D1)
    repo = _repo(backend)
    default = await repo._client.read_header_and_records(schemas.INSPECTION_FINDING_SHEET)
    explicit = await repo._client.read_header_and_records(schemas.INSPECTION_FINDING_SHEET, text_only_headers=())
    ws = gspread.Client(None, session=backend).open_by_key(SHEET_ID).worksheet(TAB)
    assert default == explicit
    assert default.records == ws.get_all_records(head=1, default_blank="")
    assert PROTECTED == ("finding_id", "inspection_id", "result_id", "asset_id", "item_title")


# ---------------------------------------------------------------------------
# T03-T05 — characterization of the EXISTING non-atomic inspection writes
# (unchanged), read back through the report
# ---------------------------------------------------------------------------


def _item(item_id: str, sequence: int, result: InspectionResultValue) -> NewInspectionItemInput:
    return NewInspectionItemInput(item_id=item_id, sequence=sequence, title=f"รายการ {sequence}", is_critical=False, result=result)


def _written_repo():
    header_ws = _ws(schemas.INSPECTION_SHEET)
    result_ws = _ws(schemas.INSPECTION_ITEM_RESULT_SHEET)
    finding_ws = _ws(schemas.INSPECTION_FINDING_SHEET)
    return _repo_with_fake_sheets(header_ws, result_ws, finding_ws), header_ws, result_ws, finding_ws


async def _create(repo) -> None:
    await repo.create_inspection(
        asset_type=AssetType.VEHICLE, asset_id="VEH-1046", checklist_id="CL-1", revision_id="REV-1",
        revision_number=1, inspector_user_id="u1", overall_remark=None,
        items=[_item("I1", 1, InspectionResultValue.PASS), _item("I2", 2, InspectionResultValue.FAIL)],
    )


async def _report_of_written(finding_ws) -> object:
    rows = [[str(v) if not isinstance(v, str) else v for v in row] for row in finding_ws.rows]
    return await _report(_repo(_backend(rows)))


@pytest.mark.asyncio
async def test_t03_characterize_a_retried_sheets_submission_writes_a_second_finding() -> None:
    repo, header_ws, _, finding_ws = _written_repo()
    await _create(repo)
    await _create(repo)  # the same submission retried
    assert len(header_ws.rows) == 2 and len(finding_ws.rows) == 2
    report = await _report_of_written(finding_ws)
    assert report.total_items == 2 and report.complete
    assert [i.finding_id for i in report.items] == ["FND-0002", "FND-0001"]  # newer submission first
    assert len({i.inspection_id for i in report.items}) == 2


@pytest.mark.asyncio
async def test_t04_characterize_failure_after_header_append_leaves_no_report_row() -> None:
    repo, header_ws, result_ws, finding_ws = _written_repo()

    def fail(*args, **kwargs):
        raise RuntimeError("simulated result append failure")

    result_ws.append_rows = fail  # type: ignore[method-assign]
    with pytest.raises(RepositoryError):
        await _create(repo)
    assert len(header_ws.rows) == 1 and result_ws.rows == [] and finding_ws.rows == []
    report = await _report_of_written(finding_ws)
    assert report.total_items == 0 and report.complete and report.population.read_record_count == 0


@pytest.mark.asyncio
async def test_t05_characterize_failure_after_result_append_leaves_fail_results_without_report_rows() -> None:
    repo, header_ws, result_ws, finding_ws = _written_repo()

    def fail(*args, **kwargs):
        raise RuntimeError("simulated finding append failure")

    finding_ws.append_rows = fail  # type: ignore[method-assign]
    with pytest.raises(RepositoryError):
        await _create(repo)
    results = [dict(zip(result_ws.header, row)) for row in result_ws.rows]
    assert [r["result"] for r in results] == ["PASS", "FAIL"] and finding_ws.rows == []
    report = await _report_of_written(finding_ws)
    assert report.total_items == 0 and report.population.read_record_count == 0


# ---------------------------------------------------------------------------
# T66-T69 over the Sheets read path (empty/whitespace cells; None cannot come
# from a values response: gspread fills empty cells with "")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "flags"),
    [("finding_id", ["BLANK_FINDING_ID"]), ("inspection_id", ["BLANK_INSPECTION_ID"]),
     ("result_id", ["BLANK_RESULT_ID"]), ("item_title", [])],
)
@pytest.mark.parametrize("value", ["", "   "])
async def test_t66_t69_blank_text_cells_over_sheets_are_readable_with_flags(field, flags, value) -> None:
    read = await _repo(_backend([_row("FND-0100", **{field: value})])).read_inspection_findings_for_report()
    row = read.rows[0]
    assert row.readable and row.mapper_called and row.texts[field] == value
    report = await _report(_repo(_backend([_row("FND-0100", **{field: value})])))
    assert report.items[0].flags == flags and report.complete


@pytest.mark.asyncio
async def test_empty_cells_arrive_as_empty_strings_never_none() -> None:
    backend = _backend([["FND-1", "", "", "VEHICLE", "VEH-1", "", "", "OPEN", TS]])
    records = (await _repo(backend)._client.read_header_and_records(
        schemas.INSPECTION_FINDING_SHEET, text_only_headers=PROTECTED
    )).records
    assert all(value is not None for value in records[0].values())
    assert records[0]["inspection_id"] == "" and records[0]["item_title"] == ""


@pytest.mark.asyncio
async def test_spy_mock_and_sheets_share_the_report_contract_for_blank_asset_id() -> None:
    mock = _SpyRepository([InspectionFinding.model_construct(
        finding_id="FND-0100", inspection_id="INS-0100", result_id="RES-0100", asset_type=AssetType.VEHICLE,
        asset_id="", item_title="x", is_critical=False, status=FindingStatus.OPEN,
        created_at=datetime(2026, 9, 28, 2, 10, tzinfo=timezone.utc),
    )])
    sheets = _repo(_backend([_row("FND-0100", asset_id="")]))
    for repo in (mock, sheets):
        body = (await _api(repo)).json()
        assert body["data_issues"]["issue_defect_counts"] == {"BLANK_ASSET_ID": 1}
        assert body["data_issues"]["sample_finding_ids"] == ["FND-0100"]
