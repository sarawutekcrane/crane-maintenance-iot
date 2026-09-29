"""Recorded inspection findings report (Phase 7 Batch 7E2) — pure,
read-only rules.

Approved decisions (this report only; see
docs/phase-results/web-phase-07-batch7e2-result.md and the reviewed 7E1
Final contract evidence, Sections 4-5):

- DEC-A: one row per recorded finding RECORD (recorded failure history).
  Not outstanding work, unresolved defects, failed inspections, assets or
  inspection coverage. `is_critical` is never exposed or used.
- DEC-C: disclosed partial result. Readable rows are listed; issue rows are
  counted and disclosed, never listed. Structural/read failures are raised
  by the repository and fail the whole request (not handled here).
- DEC-D: optional inclusive Asia/Bangkok calendar-date range on
  `created_at`, compared as DATES (no next-day arithmetic, no clock).

Row algorithm (Final 5.3.2), per non-phantom record:
  1. `read_index` = position among non-phantom records of ONE read (an
     accounting identity only; never a persistent id).
  2. Text fields are converted with `text_value` (original strings kept
     exactly: no trimming, leading zeros and whitespace preserved).
  3. asset_type / status / asset_id-blank / created_at are classified on
     the ORIGINAL values. No general truthiness test is used: only `None`
     and `""` are absent.
  4. Field-level defects are unique and emitted in `DEFECT_ORDER`.
  5. Only when a row has NO field-level defect is the unchanged legacy
     mapper called, once, on `copy.deepcopy` of the ORIGINAL record. Its
     return value is discarded. `ValueError` (pydantic's `ValidationError`
     is one), `TypeError` and `OverflowError` from that call make the row
     `UNMAPPABLE_ROW`; anything else propagates. Consequently
     `UNMAPPABLE_ROW` never co-occurs with a field-level code, and a
     mapper-skipped row carries only its field-level codes (diagnosed
     occurrences only).

Text conversion is necessary but not sufficient for READABLE: an explicit
`None` in finding_id / inspection_id / result_id / item_title converts to
blank text, but the real mapper rejects it for its `str` fields, so such an
otherwise field-clean row is `[UNMAPPABLE_ROW]`. `""` and whitespace-only
values stay READABLE with the blank flags / title fallback.

Everything here is side-effect free: no clock, no I/O.
"""
from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

REPORT_TIMEZONE = "Asia/Bangkok"
_BANGKOK = ZoneInfo(REPORT_TIMEZONE)
MAX_SAMPLE_FINDING_IDS = 20

RECORDED_STATUS_OPEN = "OPEN"
_ALLOWED_STATUSES = frozenset({RECORDED_STATUS_OPEN})
_ALLOWED_ASSET_TYPES = frozenset({"VEHICLE", "EQUIPMENT"})

# Report text fields, in no significant order.
TEXT_FIELDS = ("finding_id", "inspection_id", "result_id", "asset_id", "item_title")

# ---- Defect codes (canonical order; unique per row) ----
DEFECT_UNSUPPORTED_TEXT_VALUE = "UNSUPPORTED_TEXT_VALUE"
DEFECT_BLANK_ASSET_TYPE = "BLANK_ASSET_TYPE"
DEFECT_UNRECOGNIZED_ASSET_TYPE = "UNRECOGNIZED_ASSET_TYPE"
DEFECT_BLANK_ASSET_ID = "BLANK_ASSET_ID"
DEFECT_BLANK_STATUS = "BLANK_STATUS"
DEFECT_UNRECOGNIZED_STATUS = "UNRECOGNIZED_STATUS"
DEFECT_MISSING_CREATED_AT = "MISSING_CREATED_AT"
DEFECT_INVALID_CREATED_AT = "INVALID_CREATED_AT"
DEFECT_CREATED_AT_WITHOUT_TIMEZONE = "CREATED_AT_WITHOUT_TIMEZONE"
DEFECT_UNREPRESENTABLE_CREATED_AT = "UNREPRESENTABLE_CREATED_AT"
DEFECT_UNMAPPABLE_ROW = "UNMAPPABLE_ROW"

DEFECT_ORDER = (
    DEFECT_UNSUPPORTED_TEXT_VALUE,
    DEFECT_BLANK_ASSET_TYPE,
    DEFECT_UNRECOGNIZED_ASSET_TYPE,
    DEFECT_BLANK_ASSET_ID,
    DEFECT_BLANK_STATUS,
    DEFECT_UNRECOGNIZED_STATUS,
    DEFECT_MISSING_CREATED_AT,
    DEFECT_INVALID_CREATED_AT,
    DEFECT_CREATED_AT_WITHOUT_TIMEZONE,
    DEFECT_UNREPRESENTABLE_CREATED_AT,
    DEFECT_UNMAPPABLE_ROW,
)

# ---- Readable-row flags (canonical order) ----
FLAG_DUPLICATE_FINDING_ID = "DUPLICATE_FINDING_ID"
FLAG_BLANK_FINDING_ID = "BLANK_FINDING_ID"
FLAG_BLANK_INSPECTION_ID = "BLANK_INSPECTION_ID"
FLAG_BLANK_RESULT_ID = "BLANK_RESULT_ID"

FLAG_ORDER = (
    FLAG_DUPLICATE_FINDING_ID,
    FLAG_BLANK_FINDING_ID,
    FLAG_BLANK_INSPECTION_ID,
    FLAG_BLANK_RESULT_ID,
)


# ---------------------------------------------------------------------------
# Value conversion and classification (Final 5.3.1)
# ---------------------------------------------------------------------------


def text_value(value: object) -> str | None:
    """Text of a report TEXT field, or None when the value type is
    unsupported (no text is invented). Enums are unwrapped first; `None`
    converts to "" (absent); strings are returned unchanged; bool, int
    (including 0), float (including 0.0), date/datetime and any other
    object are unsupported."""
    if isinstance(value, Enum):
        return text_value(value.value)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return None


def is_blank_text(text: str) -> bool:
    """Blank = "" or whitespace-only (str.isspace characters)."""
    return text.strip() == ""


def _is_absent(value: object) -> bool:
    """Only None and the empty string are absent."""
    return value is None or (isinstance(value, str) and value == "")


def classify_code(
    value: object, allowed: frozenset[str], blank_code: str, unrecognized_code: str
) -> tuple[str | None, str | None]:
    """(defect code or None, validated value or None) for a code field.
    Enums are unwrapped; None/"" -> blank_code; an exactly allowed str is
    valid; anything else (whitespace, case variants, padded text, numbers,
    booleans, other types) -> unrecognized_code."""
    if isinstance(value, Enum):
        value = value.value
    if _is_absent(value):
        return blank_code, None
    if isinstance(value, str) and value in allowed:
        return None, value
    return unrecognized_code, None


def classify_created_at(value: object) -> tuple[str | None, datetime | None, date | None]:
    """(defect code or None, UTC instant, Asia/Bangkok calendar date).

    None/"" -> MISSING; bool -> INVALID (checked before numbers); a
    datetime instance is a candidate; a whitespace-only str is INVALID;
    any other str goes through `datetime.fromisoformat` untrimmed
    (ValueError -> INVALID); date, int, float and other objects are
    INVALID. A naive candidate is WITHOUT_TIMEZONE. An aware candidate
    must convert to UTC AND to Asia/Bangkok; OverflowError from either is
    UNREPRESENTABLE. Only those two exceptions are caught."""
    if _is_absent(value):
        return DEFECT_MISSING_CREATED_AT, None, None
    if isinstance(value, bool):
        return DEFECT_INVALID_CREATED_AT, None, None
    if isinstance(value, datetime):
        candidate = value
    elif isinstance(value, str):
        if value.strip() == "":
            return DEFECT_INVALID_CREATED_AT, None, None
        try:
            candidate = datetime.fromisoformat(value)
        except ValueError:
            return DEFECT_INVALID_CREATED_AT, None, None
    else:
        return DEFECT_INVALID_CREATED_AT, None, None
    if candidate.tzinfo is None or candidate.utcoffset() is None:
        return DEFECT_CREATED_AT_WITHOUT_TIMEZONE, None, None
    try:
        instant = candidate.astimezone(timezone.utc)
        bangkok_date = candidate.astimezone(_BANGKOK).date()
    except OverflowError:
        return DEFECT_UNREPRESENTABLE_CREATED_AT, None, None
    return None, instant, bangkok_date


# ---------------------------------------------------------------------------
# Repository read result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InspectionFindingReportRow:
    """One non-phantom finding record from ONE read, classified.
    `texts` holds the converted TEXT fields (None = unsupported value
    type). `mapper_called` records whether the legacy mapper gate ran."""

    read_index: int
    texts: dict[str, str | None]
    asset_type: str | None
    created_at: datetime | None
    bangkok_date: date | None
    defects: tuple[str, ...]
    mapper_called: bool

    @property
    def readable(self) -> bool:
        return not self.defects

    @property
    def usable_finding_id(self) -> str | None:
        text = self.texts["finding_id"]
        if text is None or is_blank_text(text):
            return None
        return text


@dataclass(frozen=True)
class InspectionFindingReportRead:
    rows: list[InspectionFindingReportRow] = field(default_factory=list)


def build_report_row(
    read_index: int,
    record: Mapping[str, Any],
    mapper: Callable[[dict[str, Any]], Any],
) -> InspectionFindingReportRow:
    """Classify one record (Final 5.3.2 steps 3-7). The mapper is called
    only when there is no field-level defect, with an unmodified deep copy
    of the original record; its result is discarded."""
    texts = {name: text_value(record.get(name)) for name in TEXT_FIELDS}
    found: set[str] = set()
    if any(text is None for text in texts.values()):
        found.add(DEFECT_UNSUPPORTED_TEXT_VALUE)

    asset_code, asset_type = classify_code(
        record.get("asset_type"), _ALLOWED_ASSET_TYPES, DEFECT_BLANK_ASSET_TYPE, DEFECT_UNRECOGNIZED_ASSET_TYPE
    )
    if asset_code:
        found.add(asset_code)
    asset_id = texts["asset_id"]
    if asset_id is not None and is_blank_text(asset_id):
        found.add(DEFECT_BLANK_ASSET_ID)
    status_code, _ = classify_code(
        record.get("status"), _ALLOWED_STATUSES, DEFECT_BLANK_STATUS, DEFECT_UNRECOGNIZED_STATUS
    )
    if status_code:
        found.add(status_code)
    created_code, instant, bangkok_date = classify_created_at(record.get("created_at"))
    if created_code:
        found.add(created_code)

    mapper_called = not found
    if mapper_called:
        try:
            mapper(copy.deepcopy(dict(record)))
        except (ValueError, TypeError, OverflowError):
            found.add(DEFECT_UNMAPPABLE_ROW)

    return InspectionFindingReportRow(
        read_index=read_index,
        texts=texts,
        asset_type=asset_type,
        created_at=instant,
        bangkok_date=bangkok_date,
        defects=tuple(code for code in DEFECT_ORDER if code in found),
        mapper_called=mapper_called,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportFilter:
    asset_type: str | None
    created_from: date | None
    created_to: date | None


@dataclass(frozen=True)
class ReportItem:
    finding_id: str
    inspection_id: str
    result_id: str
    asset_type: str
    asset_id: str
    item_title: str
    recorded_status: str
    created_at: datetime
    flags: list[str]


@dataclass(frozen=True)
class ReportPopulation:
    read_record_count: int
    readable_count: int
    issue_row_count: int


@dataclass(frozen=True)
class ReportDataIssues:
    issue_defect_counts: dict[str, int]
    issue_rows_without_usable_id: int
    sample_finding_ids: list[str]


@dataclass(frozen=True)
class InspectionFindingReport:
    filter: ReportFilter
    items: list[ReportItem]
    page: int
    page_size: int
    total_items: int
    complete: bool
    population: ReportPopulation
    data_issues: ReportDataIssues


def _matches(row: InspectionFindingReportRow, report_filter: ReportFilter) -> bool:
    if report_filter.asset_type is not None and row.asset_type != report_filter.asset_type:
        return False
    # Readable rows always carry a Bangkok date (Final 5.3.2 step 5).
    if report_filter.created_from is not None and row.bangkok_date < report_filter.created_from:
        return False
    return report_filter.created_to is None or row.bangkok_date <= report_filter.created_to


def _flags(row: InspectionFindingReportRow, id_counts: Counter[str]) -> list[str]:
    flags: set[str] = set()
    usable = row.usable_finding_id
    if usable is not None and id_counts[usable] >= 2:
        flags.add(FLAG_DUPLICATE_FINDING_ID)
    for name, flag in (
        ("finding_id", FLAG_BLANK_FINDING_ID),
        ("inspection_id", FLAG_BLANK_INSPECTION_ID),
        ("result_id", FLAG_BLANK_RESULT_ID),
    ):
        text = row.texts[name]
        if text is not None and is_blank_text(text):
            flags.add(flag)
    return [flag for flag in FLAG_ORDER if flag in flags]


def build_report(
    rows: list[InspectionFindingReportRow],
    report_filter: ReportFilter,
    page: int,
    page_size: int,
) -> InspectionFindingReport:
    """Whole-read accounting first (independent of filter and page), then
    filter, order (UTC instant DESC, finding_id text ASC, read_index ASC)
    and paginate the readable rows. Offset paging is not a snapshot."""
    readable = [row for row in rows if row.readable]
    issue_rows = [row for row in rows if not row.readable]

    id_counts = Counter(row.usable_finding_id for row in rows if row.usable_finding_id is not None)
    defect_counts: Counter[str] = Counter()
    for row in issue_rows:
        defect_counts.update(row.defects)

    population = ReportPopulation(
        read_record_count=len(rows),
        readable_count=len(readable),
        issue_row_count=len(issue_rows),
    )
    data_issues = ReportDataIssues(
        issue_defect_counts={code: defect_counts[code] for code in DEFECT_ORDER if defect_counts[code]},
        issue_rows_without_usable_id=sum(1 for row in issue_rows if row.usable_finding_id is None),
        sample_finding_ids=sorted(
            {row.usable_finding_id for row in issue_rows if row.usable_finding_id is not None}
        )[:MAX_SAMPLE_FINDING_IDS],
    )

    matching = [row for row in readable if _matches(row, report_filter)]
    # Stable passes, least significant key first.
    matching.sort(key=lambda row: row.read_index)
    matching.sort(key=lambda row: row.texts["finding_id"] or "")
    matching.sort(key=lambda row: row.created_at, reverse=True)

    start = (page - 1) * page_size
    items = [
        ReportItem(
            finding_id=row.texts["finding_id"] or "",
            inspection_id=row.texts["inspection_id"] or "",
            result_id=row.texts["result_id"] or "",
            asset_type=row.asset_type or "",
            asset_id=row.texts["asset_id"] or "",
            item_title=row.texts["item_title"] or "",
            recorded_status=RECORDED_STATUS_OPEN,
            created_at=row.created_at,  # type: ignore[arg-type]  # readable rows always have one
            flags=_flags(row, id_counts),
        )
        for row in matching[start : start + page_size]
    ]
    return InspectionFindingReport(
        filter=report_filter,
        items=items,
        page=page,
        page_size=page_size,
        total_items=len(matching),
        complete=population.issue_row_count == 0,
        population=population,
        data_issues=data_issues,
    )
