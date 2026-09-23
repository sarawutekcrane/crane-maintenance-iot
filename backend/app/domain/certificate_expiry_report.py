"""Certificate expiry report (Phase 7 Batch 7D2) — pure, read-only rules.

Approved decisions (this report only; see
docs/phase-results/web-phase-07-batch7d2-result.md):

- DEC 1 SCOPE: one report row per certificate RECORD. Stored ACTIVE and
  EXPIRED records are in scope when readable; REPLACED and blank-status
  records are excluded and counted. Duplicates are preserved.
- DEC 2 HIST: historical EXPIRED rows are never hidden because another
  ACTIVE record exists; observations are flags only. A flag never
  establishes legal validity, compliance or a replacement relationship.
- DEC 3 WIN: user-selected inclusive expiry-date range; an omitted end
  date is today's Bangkok date, resolved per request. No fixed
  "expiring soon" window and no use of `alert_lead_days`.
- DEC 4 DQ (option B): disclosed partial results for row-value defects;
  structural/read failures still fail the whole request.
- DEC 9 REUSE: `report_effective_status` is a pure predicate with parity
  to `VehicleCertificateService._reconcile_expiry` on readable in-scope
  rows. The report never calls (or writes through) that reconciliation.
- DEC 10 DQ-BLANK: report-only absence rules — `None` and `""` are
  absent; numeric zero, booleans, whitespace-only and unparseable dates
  are invalid. Legacy mapping behavior is unchanged.

Everything here is side-effect free: no clock, no I/O. The service
supplies the single `as_of` date resolved for the request.
"""
from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate

REPORT_TIMEZONE = "Asia/Bangkok"
MAX_SAMPLE_CERTIFICATE_IDS = 20

# ---- Report modes ----
MODE_RANGE = "RANGE"
MODE_MISSING_EXPIRY_DATE = "MISSING_EXPIRY_DATE"

# ---- Row classification ----
STATUS_BLANK = "BLANK"
STATUS_VALID = "VALID"
STATUS_UNRECOGNIZED = "UNRECOGNIZED"

EXPIRY_BLANK = "BLANK"
EXPIRY_VALID = "VALID"
EXPIRY_INVALID = "INVALID"

_STORED_STATUSES = frozenset(s.value for s in CertificateStatus)
_IN_SCOPE_STATUSES = frozenset({CertificateStatus.ACTIVE.value, CertificateStatus.EXPIRED.value})

# ---- Defect codes (occurrences; codes may overlap on one row) ----
DEFECT_UNRECOGNIZED_STATUS = "UNRECOGNIZED_STATUS"
DEFECT_INVALID_EXPIRY_DATE = "INVALID_EXPIRY_DATE"
DEFECT_UNMAPPABLE_ROW = "UNMAPPABLE_ROW"

# ---- Exclusive accounting buckets (first matching bucket wins) ----
BUCKET_ISSUE_UNKNOWN_STATUS = "ISSUE_UNKNOWN_STATUS"
BUCKET_EXCLUDED_REPLACED = "EXCLUDED_REPLACED"
BUCKET_EXCLUDED_STATUS_BLANK = "EXCLUDED_STATUS_BLANK"
BUCKET_ISSUE_IN_SCOPE_DEFECT = "ISSUE_IN_SCOPE_DEFECT"
BUCKET_IN_SCOPE = "IN_SCOPE"

_ISSUE_BUCKETS = frozenset({BUCKET_ISSUE_UNKNOWN_STATUS, BUCKET_ISSUE_IN_SCOPE_DEFECT})
_EXCLUDED_BUCKETS = frozenset({BUCKET_EXCLUDED_REPLACED, BUCKET_EXCLUDED_STATUS_BLANK})

# ---- Expiry position relative to as_of ----
POSITION_BEFORE_TODAY = "BEFORE_TODAY"
POSITION_TODAY = "TODAY"
POSITION_AFTER_TODAY = "AFTER_TODAY"
POSITION_NO_EXPIRY_DATE = "NO_EXPIRY_DATE"

# ---- Observation flags (canonical output order) ----
FLAG_SAME_TYPE_ACTIVE_EXISTS = "SAME_TYPE_ACTIVE_EXISTS"
FLAG_MULTIPLE_ACTIVE_SAME_TYPE = "MULTIPLE_ACTIVE_SAME_TYPE"
FLAG_STORED_ACTIVE_PAST_EXPIRY = "STORED_ACTIVE_PAST_EXPIRY"
FLAG_STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY = "STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY"
FLAG_LINK_PRESENT_ON_NON_REPLACED = "LINK_PRESENT_ON_NON_REPLACED"
FLAG_DUPLICATE_CERTIFICATE_ID = "DUPLICATE_CERTIFICATE_ID"
FLAG_BLANK_CERTIFICATE_ID = "BLANK_CERTIFICATE_ID"
FLAG_BLANK_VEHICLE_ID = "BLANK_VEHICLE_ID"

FLAG_ORDER = (
    FLAG_SAME_TYPE_ACTIVE_EXISTS,
    FLAG_MULTIPLE_ACTIVE_SAME_TYPE,
    FLAG_STORED_ACTIVE_PAST_EXPIRY,
    FLAG_STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY,
    FLAG_LINK_PRESENT_ON_NON_REPLACED,
    FLAG_DUPLICATE_CERTIFICATE_ID,
    FLAG_BLANK_CERTIFICATE_ID,
    FLAG_BLANK_VEHICLE_ID,
)

# Raw text columns retained on every row (original values, never trimmed).
RAW_TEXT_FIELDS = (
    "certificate_id",
    "vehicle_id",
    "certificate_type_code",
    "certificate_type_name_th",
    "document_no",
    "replaced_by_certificate_id",
)


# ---------------------------------------------------------------------------
# Value conversion and classification (DEC 10)
# ---------------------------------------------------------------------------


def raw_text(value: object) -> str | None:
    """Original cell/field value as text, WITHOUT trimming, case change or
    normalization. Returns None for an unsupported value type (the caller
    records a mapping defect; no identifier is invented).

    Enums are checked before generic strings: `CertificateStatus` is a
    `str` subclass whose `str()` is not its stored value."""
    if value is None:
        return ""
    if isinstance(value, Enum):
        return raw_text(value.value)
    if isinstance(value, str):
        return value
    if isinstance(value, bool):  # before int: bool is an int subclass
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None


def _is_absent(value: object) -> bool:
    """DEC 10: only None and the empty string are absent."""
    return value is None or (isinstance(value, str) and value == "")


def classify_status(value: object) -> tuple[str, str | None]:
    """(status_class, stored_status). VALID only for exactly ACTIVE,
    REPLACED or EXPIRED; BLANK only for None/""; anything else (numeric
    zero, booleans, whitespace, case variants, other text) is
    UNRECOGNIZED."""
    if isinstance(value, Enum):
        value = value.value
    if _is_absent(value):
        return STATUS_BLANK, None
    if isinstance(value, str) and value in _STORED_STATUSES:
        return STATUS_VALID, value
    return STATUS_UNRECOGNIZED, None


def classify_expiry(
    value: object, parse_date: Callable[[object], date | None]
) -> tuple[str, date | None]:
    """(expiry_class, parsed date). BLANK only for None/""; booleans are
    INVALID; otherwise VALID only when the UNCHANGED existing parser
    (`GoogleSheetsRepository._parse_date`) returns a date, so accepted
    legacy formats stay accepted and everything else is INVALID."""
    if _is_absent(value):
        return EXPIRY_BLANK, None
    if isinstance(value, bool):
        return EXPIRY_INVALID, None
    try:
        parsed = parse_date(value)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, date) and not isinstance(parsed, datetime):
        return EXPIRY_VALID, parsed
    return EXPIRY_INVALID, None


def _blank(text: str) -> bool:
    return not text.strip()


# ---------------------------------------------------------------------------
# Repository read result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CertificateReportRow:
    """One non-phantom certificate record from ONE read. `read_index` is a
    per-read position only — not a persistent id and not a sheet row
    number. Raw texts are the original values (never trimmed); the
    original status/expiry inputs are retained for classification only
    and are never exposed by the API."""

    read_index: int
    certificate_id_text: str
    vehicle_id_text: str
    type_code_text: str
    type_name_text: str
    document_no_text: str
    replaced_by_text: str
    status_input: Any
    expiry_input: Any
    status_class: str
    stored_status: str | None
    expiry_class: str
    expiry_date: date | None
    mapping_ok: bool
    certificate: VehicleCertificate | None


@dataclass(frozen=True)
class CertificateReportRead:
    rows: list[CertificateReportRow] = field(default_factory=list)


def build_report_row(
    read_index: int,
    record: Mapping[str, Any],
    mapper: Callable[[dict[str, Any]], VehicleCertificate],
    parse_date: Callable[[object], date | None],
    blank_status_value: Any,
) -> CertificateReportRow:
    """Classify one record. Status, expiry and mapping are evaluated
    independently on EVERY row (excluded statuses included). The
    unchanged mapper runs on a COPY; an unrecognized status is blanked in
    that copy only so an independent mapping defect is still detected.
    The mapper's own silent invalid-date handling never overrides
    `classify_expiry`. Only `ValueError`/`TypeError` (pydantic's
    `ValidationError` is a `ValueError`) and `OverflowError` are row-value
    defects; anything else propagates. `OverflowError` comes from the
    unchanged legacy `alert_lead_days` conversion of a non-finite cell
    (e.g. "inf", "-inf", "1e309", which gspread numericises to a float
    infinity): that row is `UNMAPPABLE_ROW`, never a whole-report failure."""
    texts: dict[str, str] = {}
    supported = True
    for name in RAW_TEXT_FIELDS:
        text = raw_text(record.get(name))
        if text is None:
            supported = False
            text = ""
        texts[name] = text

    status_input = record.get("certificate_status")
    expiry_input = record.get("expiry_date")
    status_class, stored_status = classify_status(status_input)
    expiry_class, expiry_date = classify_expiry(expiry_input, parse_date)

    certificate: VehicleCertificate | None = None
    if supported:
        candidate = copy.deepcopy(dict(record))
        if status_class == STATUS_UNRECOGNIZED:
            candidate["certificate_status"] = blank_status_value
        try:
            certificate = mapper(candidate)
        except (ValueError, TypeError, OverflowError):
            certificate = None

    return CertificateReportRow(
        read_index=read_index,
        certificate_id_text=texts["certificate_id"],
        vehicle_id_text=texts["vehicle_id"],
        type_code_text=texts["certificate_type_code"],
        type_name_text=texts["certificate_type_name_th"],
        document_no_text=texts["document_no"],
        replaced_by_text=texts["replaced_by_certificate_id"],
        status_input=status_input,
        expiry_input=expiry_input,
        status_class=status_class,
        stored_status=stored_status,
        expiry_class=expiry_class,
        expiry_date=expiry_date,
        mapping_ok=certificate is not None,
        certificate=certificate,
    )


# ---------------------------------------------------------------------------
# Accounting, effective status, flags (DEC 1, 2, 4, 9)
# ---------------------------------------------------------------------------


def row_defects(row: CertificateReportRow) -> list[str]:
    defects: list[str] = []
    if row.status_class == STATUS_UNRECOGNIZED:
        defects.append(DEFECT_UNRECOGNIZED_STATUS)
    if row.expiry_class == EXPIRY_INVALID:
        defects.append(DEFECT_INVALID_EXPIRY_DATE)
    if not row.mapping_ok:
        defects.append(DEFECT_UNMAPPABLE_ROW)
    return defects


def classify_bucket(row: CertificateReportRow) -> str:
    """Exclusive accounting; the first matching bucket wins."""
    if row.status_class == STATUS_UNRECOGNIZED:
        return BUCKET_ISSUE_UNKNOWN_STATUS
    if row.stored_status == CertificateStatus.REPLACED.value:
        return BUCKET_EXCLUDED_REPLACED
    if row.status_class == STATUS_BLANK:
        return BUCKET_EXCLUDED_STATUS_BLANK
    if row.expiry_class == EXPIRY_INVALID or not row.mapping_ok:
        return BUCKET_ISSUE_IN_SCOPE_DEFECT
    return BUCKET_IN_SCOPE


def report_effective_status(stored_status: str, expiry_date: date | None, as_of: date) -> str:
    """DEC 9 pure predicate for a readable in-scope row: stored ACTIVE
    with an expiry strictly before `as_of` is EXPIRED; stored ACTIVE with
    no expiry, today or a future expiry stays ACTIVE; stored EXPIRED
    stays EXPIRED regardless of its expiry."""
    if stored_status == CertificateStatus.ACTIVE.value:
        if expiry_date is not None and expiry_date < as_of:
            return CertificateStatus.EXPIRED.value
        return CertificateStatus.ACTIVE.value
    if stored_status == CertificateStatus.EXPIRED.value:
        return CertificateStatus.EXPIRED.value
    raise ValueError(f"not an in-scope stored status: {stored_status!r}")


def expiry_position(expiry_date: date | None, as_of: date) -> str:
    if expiry_date is None:
        return POSITION_NO_EXPIRY_DATE
    if expiry_date < as_of:
        return POSITION_BEFORE_TODAY
    if expiry_date == as_of:
        return POSITION_TODAY
    return POSITION_AFTER_TODAY


@dataclass(frozen=True)
class ReportFilter:
    mode: str
    expiry_from: date | None
    expiry_to_requested: date | None
    expiry_to_resolved: date | None
    expiry_to_is_default: bool
    effective_status: str | None


@dataclass(frozen=True)
class ReportItem:
    certificate_id: str
    vehicle_id: str
    certificate_type_code: str | None
    certificate_type_name_th: str | None
    document_no: str | None
    expiry_date: date | None
    stored_status: str
    effective_status: str
    expiry_position: str
    flags: list[str]


@dataclass(frozen=True)
class ReportPopulation:
    read_record_count: int
    in_scope_count: int
    in_scope_with_expiry_date_count: int
    in_scope_without_expiry_date_count: int
    excluded_replaced_count: int
    excluded_status_blank_count: int
    issue_row_count: int
    excluded_rows_with_other_defects: int
    replaced_link_observations: int


@dataclass(frozen=True)
class ReportDataIssues:
    issue_defect_counts: dict[str, int]
    issue_rows_without_usable_id: int
    sample_certificate_ids: list[str]


@dataclass(frozen=True)
class CertificateExpiryReport:
    as_of_date: date
    filter: ReportFilter
    items: list[ReportItem]
    page: int
    page_size: int
    total_items: int
    complete: bool
    population: ReportPopulation
    data_issues: ReportDataIssues


def _optional(text: str) -> str | None:
    return text if text != "" else None


def build_report(
    rows: list[CertificateReportRow],
    as_of: date,
    report_filter: ReportFilter,
    page: int,
    page_size: int,
) -> CertificateExpiryReport:
    """Whole-read accounting and observations first (independent of the
    filter and page), then filter, order and paginate the readable
    IN_SCOPE rows."""
    buckets = {row.read_index: classify_bucket(row) for row in rows}
    bucket_counts = Counter(buckets.values())

    in_scope = [row for row in rows if buckets[row.read_index] == BUCKET_IN_SCOPE]
    issue_rows = [row for row in rows if buckets[row.read_index] in _ISSUE_BUCKETS]
    excluded_with_defects = sum(
        1 for row in rows if buckets[row.read_index] in _EXCLUDED_BUCKETS and row_defects(row)
    )

    nonblank_ids = [row.certificate_id_text for row in rows if not _blank(row.certificate_id_text)]
    id_counts = Counter(nonblank_ids)
    known_ids = set(nonblank_ids)
    replaced_link_observations = sum(
        1
        for row in rows
        if buckets[row.read_index] == BUCKET_EXCLUDED_REPLACED
        and (_blank(row.replaced_by_text) or row.replaced_by_text not in known_ids)
    )

    defect_counts: Counter[str] = Counter()
    for row in issue_rows:
        defect_counts.update(row_defects(row))
    usable_issue_ids = sorted(
        {row.certificate_id_text for row in issue_rows if not _blank(row.certificate_id_text)}
    )

    population = ReportPopulation(
        read_record_count=len(rows),
        in_scope_count=len(in_scope),
        in_scope_with_expiry_date_count=sum(1 for r in in_scope if r.expiry_date is not None),
        in_scope_without_expiry_date_count=sum(1 for r in in_scope if r.expiry_date is None),
        excluded_replaced_count=bucket_counts[BUCKET_EXCLUDED_REPLACED],
        excluded_status_blank_count=bucket_counts[BUCKET_EXCLUDED_STATUS_BLANK],
        issue_row_count=len(issue_rows),
        excluded_rows_with_other_defects=excluded_with_defects,
        replaced_link_observations=replaced_link_observations,
    )
    data_issues = ReportDataIssues(
        issue_defect_counts=dict(sorted(defect_counts.items())),
        issue_rows_without_usable_id=sum(1 for r in issue_rows if _blank(r.certificate_id_text)),
        sample_certificate_ids=usable_issue_ids[:MAX_SAMPLE_CERTIFICATE_IDS],
    )

    # Effective status and group observations over ALL readable in-scope
    # rows (before filters/pages), no-expiry rows included. Groups need a
    # non-blank vehicle id AND type code; ORIGINAL values are compared.
    effective = {
        r.read_index: report_effective_status(r.stored_status or "", r.expiry_date, as_of)
        for r in in_scope
    }
    active_per_group: Counter[tuple[str, str]] = Counter()
    for r in in_scope:
        if _groupable(r) and effective[r.read_index] == CertificateStatus.ACTIVE.value:
            active_per_group[(r.vehicle_id_text, r.type_code_text)] += 1

    items_with_keys: list[tuple[tuple, ReportItem]] = []
    for r in in_scope:
        eff = effective[r.read_index]
        if not _matches(r, eff, report_filter):
            continue
        flags = _flags(r, eff, as_of, active_per_group, id_counts)
        item = ReportItem(
            certificate_id=r.certificate_id_text,
            vehicle_id=r.vehicle_id_text,
            certificate_type_code=_optional(r.type_code_text),
            certificate_type_name_th=_optional(r.type_name_text),
            document_no=_optional(r.document_no_text),
            expiry_date=r.expiry_date,
            stored_status=r.stored_status or "",
            effective_status=eff,
            expiry_position=expiry_position(r.expiry_date, as_of),
            flags=flags,
        )
        identity = (r.vehicle_id_text, r.type_code_text, r.certificate_id_text, r.read_index)
        key = (r.expiry_date, *identity) if report_filter.mode == MODE_RANGE else identity
        items_with_keys.append((key, item))

    items_with_keys.sort(key=lambda pair: pair[0])
    matching = [item for _, item in items_with_keys]
    start = (page - 1) * page_size
    return CertificateExpiryReport(
        as_of_date=as_of,
        filter=report_filter,
        items=matching[start : start + page_size],
        page=page,
        page_size=page_size,
        total_items=len(matching),
        complete=population.issue_row_count == 0,
        population=population,
        data_issues=data_issues,
    )


def _groupable(row: CertificateReportRow) -> bool:
    return not _blank(row.vehicle_id_text) and not _blank(row.type_code_text)


def _matches(row: CertificateReportRow, effective: str, report_filter: ReportFilter) -> bool:
    if report_filter.effective_status is not None and effective != report_filter.effective_status:
        return False
    if report_filter.mode == MODE_MISSING_EXPIRY_DATE:
        return row.expiry_date is None
    if row.expiry_date is None:
        return False
    if report_filter.expiry_from is not None and row.expiry_date < report_filter.expiry_from:
        return False
    return report_filter.expiry_to_resolved is None or row.expiry_date <= report_filter.expiry_to_resolved


def _flags(
    row: CertificateReportRow,
    effective: str,
    as_of: date,
    active_per_group: Counter[tuple[str, str]],
    id_counts: Counter[str],
) -> list[str]:
    flags: set[str] = set()
    active = CertificateStatus.ACTIVE.value
    if _groupable(row):
        group_active = active_per_group[(row.vehicle_id_text, row.type_code_text)]
        if effective != active and group_active >= 1:
            flags.add(FLAG_SAME_TYPE_ACTIVE_EXISTS)
        if effective == active and group_active >= 2:
            flags.add(FLAG_MULTIPLE_ACTIVE_SAME_TYPE)
    if row.expiry_date is not None:
        if row.stored_status == active and row.expiry_date < as_of:
            flags.add(FLAG_STORED_ACTIVE_PAST_EXPIRY)
        if row.stored_status == CertificateStatus.EXPIRED.value and row.expiry_date >= as_of:
            flags.add(FLAG_STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY)
    if row.stored_status in _IN_SCOPE_STATUSES and not _blank(row.replaced_by_text):
        flags.add(FLAG_LINK_PRESENT_ON_NON_REPLACED)
    if _blank(row.certificate_id_text):
        flags.add(FLAG_BLANK_CERTIFICATE_ID)
    elif id_counts[row.certificate_id_text] >= 2:
        flags.add(FLAG_DUPLICATE_CERTIFICATE_ID)
    if _blank(row.vehicle_id_text):
        flags.add(FLAG_BLANK_VEHICLE_ID)
    return [flag for flag in FLAG_ORDER if flag in flags]
