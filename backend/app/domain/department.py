"""R2 Batch R2c-2 — read-only department master (standalone, stable identity).

Source: a standalone `department_master` tab with the frozen header below
(R2c-2 contract lock). The live tab does not exist yet; until it does, the
department routes report DEPARTMENT_MASTER_SCHEMA_INVALID. No live row, label
or id is known to this code: the production id format and the operational
department set are owner business data, not decided here.

Identity is `department_id` only, matched as exact text (no trim, case
folding or numeric normalization) and never derived from the display name.
`department_name_th` is required display text, returned exactly as stored;
it is not identity and need not be unique. `is_active` is the exact text
TRUE / FALSE (no default); both are valid and inactive departments stay
readable. `test_batch_id` is known schema metadata: not required by the read,
never exposed or interpreted.

No personnel, branch, workshop, account, technician or driver data is read
or joined. `personnel_master.department` stays legacy free text and is not
touched. Workshop modelling is deferred: this module makes no claim about it.

Processing order (one department_master read):
1. a row whose three business columns (department_id, department_name_th,
   is_active) are all blank is skipped whatever its checkbox says;
2. `is_test_data` is classified on every remaining row: exact FALSE ->
   operational, exact TRUE -> test (excluded everywhere), anything else ->
   the WHOLE source fails closed (DATA_INVALID / TEST_FLAG_INVALID) for both
   list and detail;
3. only operational rows are then validated.

List: any operational defect (BLANK_DEPARTMENT_ID, DUPLICATE_DEPARTMENT_ID,
BLANK_DEPARTMENT_NAME, ACTIVE_FLAG_INVALID) fails the whole list.
Detail: target-focused after classification — the exact operational matches
for the requested id only: 0 -> 404, >1 -> 409, 1 -> that row's name and
is_active must be valid (else DATA_INVALID with that row's issue counts).
Unrelated malformed operational rows do not block a valid exact detail.
Error details carry issue counts only, never ids, names, batch ids or row
numbers.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.registration import text
from app.errors import ApiError
from app.repositories.base import (
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositorySchemaError,
)

DEPARTMENT_TAB = "department_master"

# Frozen header (R2c-2 contract lock), in source order.
DEPARTMENT_MASTER_COLUMNS: tuple[str, ...] = (
    "department_id",
    "department_name_th",
    "is_active",
    "is_test_data",
    "test_batch_id",
)
# The business columns that make a row a department record.
DEPARTMENT_BUSINESS_COLUMNS: tuple[str, ...] = ("department_id", "department_name_th", "is_active")
# Required by the bounded read: the business columns plus the scope flag.
DEPARTMENT_READ_COLUMNS: tuple[str, ...] = (*DEPARTMENT_BUSINESS_COLUMNS, "is_test_data")

ISSUE_BLANK_ID = "BLANK_DEPARTMENT_ID"
ISSUE_DUPLICATE_ID = "DUPLICATE_DEPARTMENT_ID"
ISSUE_BLANK_NAME = "BLANK_DEPARTMENT_NAME"
ISSUE_ACTIVE_FLAG_INVALID = "ACTIVE_FLAG_INVALID"
ISSUE_TEST_FLAG_INVALID = "TEST_FLAG_INVALID"
OPERATIONAL_FLAG = "FALSE"
TEST_FLAG = "TRUE"
_ACTIVE_VALUES = {"TRUE": True, "FALSE": False}


@dataclass(frozen=True)
class DepartmentRecord:
    department_id: str
    department_name_th: str
    is_active: bool


def _count(issues: dict[str, int], code: str) -> None:
    issues[code] = issues.get(code, 0) + 1


def operational_rows(rows: Sequence[Mapping[str, object]]) -> tuple[list[Mapping[str, object]], dict[str, int]]:
    """(operational rows, issue counts). Classifies `is_test_data` on every
    department row BEFORE any id/name/active check: exact FALSE kept, exact
    TRUE dropped, anything else counted as TEST_FLAG_INVALID (never guessed)."""
    kept: list[Mapping[str, object]] = []
    invalid = 0
    for row in rows:
        if not any(text(row.get(c)).strip() for c in DEPARTMENT_BUSINESS_COLUMNS):
            continue  # no department content in this row (e.g. a checkbox-only row)
        flag = text(row.get("is_test_data"))
        if flag == OPERATIONAL_FLAG:
            kept.append(row)
        elif flag != TEST_FLAG:
            invalid += 1
    return kept, ({ISSUE_TEST_FLAG_INVALID: invalid} if invalid else {})


def row_issues(row: Mapping[str, object]) -> dict[str, int]:
    """Display/lifecycle issues of one operational row (empty = valid)."""
    issues: dict[str, int] = {}
    if not text(row.get("department_name_th")).strip():
        _count(issues, ISSUE_BLANK_NAME)
    if text(row.get("is_active")) not in _ACTIVE_VALUES:
        _count(issues, ISSUE_ACTIVE_FLAG_INVALID)
    return issues


def table_issues(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Issue counts over all operational rows (empty = valid): a blank id,
    every row sharing a duplicated id (the R1 counting rule), and each row's
    display/lifecycle issues."""
    issues: dict[str, int] = {}
    ids = [text(r.get("department_id")) for r in rows]
    for row, did in zip(rows, ids):
        if not did.strip():
            _count(issues, ISSUE_BLANK_ID)
        elif ids.count(did) > 1:
            _count(issues, ISSUE_DUPLICATE_ID)
        for code, n in row_issues(row).items():
            issues[code] = issues.get(code, 0) + n
    return issues


def department_record(row: Mapping[str, object]) -> DepartmentRecord:
    """Exact source text; only called on a row that passed validation."""
    return DepartmentRecord(
        department_id=text(row.get("department_id")),
        department_name_th=text(row.get("department_name_th")),
        is_active=_ACTIVE_VALUES[text(row.get("is_active"))],
    )


# ---------------------------------------------------------------------------
# Errors (additive, department-specific)
# ---------------------------------------------------------------------------


def _schema_invalid(exc: RepositorySchemaError) -> ApiError:
    return ApiError(
        code="DEPARTMENT_MASTER_SCHEMA_INVALID",
        message=str(exc),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
    )


def _read_failed() -> ApiError:
    return ApiError(
        code="DEPARTMENT_MASTER_READ_FAILED",
        message=f"{DEPARTMENT_TAB} could not be read",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        details={"tab": DEPARTMENT_TAB},
    )


def data_invalid(issues: dict[str, int]) -> ApiError:
    return ApiError(
        code="DEPARTMENT_MASTER_DATA_INVALID",
        message=f"{DEPARTMENT_TAB} contains records that cannot be used exactly",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"tab": DEPARTMENT_TAB, "issues": dict(sorted(issues.items()))},
    )


def not_found() -> ApiError:
    return ApiError(
        code="DEPARTMENT_NOT_FOUND",
        message="No department record has exactly this department_id",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def ambiguous(match_count: int) -> ApiError:
    return ApiError(
        code="DEPARTMENT_ID_AMBIGUOUS",
        message="More than one department record has this department_id",
        status_code=status.HTTP_409_CONFLICT,
        details={"match_count": match_count},
    )


class DepartmentService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _read(self) -> list[Mapping[str, object]]:
        """ONE validated department_master read, then the operational scope:
        only exact-FALSE rows. Failures are coded, never empty; an unknown
        test flag anywhere fails closed before any other check."""
        try:
            read = await self._repository.read_department_master_validated()
        except RepositoryFeatureNotImplementedError:
            raise
        except RepositorySchemaError as exc:
            raise _schema_invalid(exc) from exc
        except RepositoryError as exc:
            raise _read_failed() from exc
        rows, issues = operational_rows(read.rows)
        if issues:
            raise data_invalid(issues)
        return rows

    async def list_departments(self, params: PageParams) -> Page[DepartmentRecord]:
        rows = await self._read()
        issues = table_issues(rows)
        if issues:
            raise data_invalid(issues)
        records = sorted((department_record(r) for r in rows), key=lambda d: d.department_id)
        start = (params.page - 1) * params.page_size
        return Page(
            items=records[start : start + params.page_size],
            page=params.page,
            page_size=params.page_size,
            total_items=len(records),
        )

    async def get_department(self, department_id: str) -> DepartmentRecord:
        rows = await self._read()
        if not department_id.strip():  # a blank id never identifies a department
            raise not_found()
        matches = [r for r in rows if text(r.get("department_id")) == department_id]
        if not matches:
            raise not_found()
        if len(matches) > 1:
            raise ambiguous(len(matches))
        issues = row_issues(matches[0])
        if issues:
            raise data_invalid(issues)
        return department_record(matches[0])
