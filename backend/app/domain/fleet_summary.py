"""Fleet status summary (Phase 7 Batch 7B2) — pure counting and identity
checks for the approved K1-K6 dashboard KPIs.

K1 `vehicle_total` and K2-K6 `status_counts` count the vehicle master
records as RECORDED: no active/archive filter, no equipment, no model
join; OUT_OF_SERVICE and LONG_TERM_PARKING are included. They say nothing
about IoT connectivity or physical readiness.

Policy (approved DQ-1 "parity-or-fail"): counts are produced only when
every record passed the validated read, so a success always agrees with
`list_vehicles` totals for the same stored state. Otherwise the caller
fails the whole summary with no counts. Nothing here reads or writes
storage.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.common import OperationalStatus
from app.domain.vehicle import Vehicle

POPULATION_VALIDATED_RECORDS = "VEHICLE_MASTER_VALIDATED_RECORDS"

# Record-level issue codes (VEHICLE_MASTER_DATA_INVALID details).
ISSUE_BLANK_STATUS = "BLANK_STATUS"
ISSUE_UNRECOGNIZED_STATUS = "UNRECOGNIZED_STATUS"
ISSUE_UNMAPPABLE_ROW = "UNMAPPABLE_ROW"
ISSUE_BLANK_VEHICLE_ID = "BLANK_VEHICLE_ID"
ISSUE_DUPLICATE_VEHICLE_ID = "DUPLICATE_VEHICLE_ID"

# Structural problem codes (VEHICLE_MASTER_SCHEMA_INVALID details).
SCHEMA_PROBLEM_TAB_MISSING = "TAB_MISSING"
SCHEMA_PROBLEM_NO_HEADER_ROW = "NO_HEADER_ROW"
SCHEMA_PROBLEM_MISSING_HEADERS = "MISSING_HEADERS"
SCHEMA_PROBLEM_DUPLICATE_HEADERS = "DUPLICATE_HEADERS"
SCHEMA_PROBLEM_DATA_OUTSIDE_HEADER = "DATA_OUTSIDE_HEADER"

MAX_SAMPLE_VEHICLE_IDS = 20

# Exact recorded codes, in the order the API documents them.
STATUS_CODES: tuple[str, ...] = tuple(status.value for status in OperationalStatus)


@dataclass(frozen=True)
class FleetStatusSummary:
    vehicle_total: int
    status_counts: dict[str, int]
    population: str = POPULATION_VALIDATED_RECORDS


def classify_raw_status(value: object) -> str | None:
    """Issue code for a raw `operational_status` cell, or None when it is
    exactly one of the five recorded codes. No default, trimming, case
    normalization or alias: a blank cell is never read as READY here."""
    if isinstance(value, str) and value in STATUS_CODES:
        return None
    if value is None or (isinstance(value, str) and not value.strip()):
        return ISSUE_BLANK_STATUS
    return ISSUE_UNRECOGNIZED_STATUS


def find_identity_issues(vehicles: Iterable[Vehicle]) -> tuple[dict[str, int], list[str]]:
    """Blank/whitespace-only ids and exact duplicate ids. Every occurrence
    of a duplicated id is counted (two records sharing one id -> 2). Ids
    are compared exactly as stored; none is rewritten."""
    vehicles = list(vehicles)
    issues: Counter[str] = Counter()
    blank = [v for v in vehicles if not v.vehicle_id.strip()]
    if blank:
        issues[ISSUE_BLANK_VEHICLE_ID] = len(blank)
    occurrences = Counter(v.vehicle_id for v in vehicles if v.vehicle_id.strip())
    duplicated = sorted(vid for vid, n in occurrences.items() if n > 1)
    if duplicated:
        issues[ISSUE_DUPLICATE_VEHICLE_ID] = sum(occurrences[vid] for vid in duplicated)
    return dict(issues), duplicated


def sample_vehicle_ids(ids: Iterable[str]) -> list[str]:
    """Up to `MAX_SAMPLE_VEHICLE_IDS` distinct, sorted, non-blank ids."""
    return sorted({i for i in ids if i.strip()})[:MAX_SAMPLE_VEHICLE_IDS]


def count_fleet_status(vehicles: Iterable[Vehicle]) -> FleetStatusSummary:
    """K1-K6 over already-validated records. All five status keys are
    always present; the K1 == sum(K2..K6) invariant is checked and a
    violation raises rather than returning inconsistent numbers."""
    vehicles = list(vehicles)
    counted = Counter(v.operational_status.value for v in vehicles)
    status_counts = {code: counted.get(code, 0) for code in STATUS_CODES}
    total = len(vehicles)
    if total != sum(status_counts.values()):
        raise AssertionError("fleet status counts do not add up to the vehicle total")
    return FleetStatusSummary(vehicle_total=total, status_counts=status_counts)
