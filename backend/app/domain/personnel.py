"""R2 Batch R2c-1 — read-only personnel master (identity and minimum display).

Source: the prepared `personnel_master` tab. Its 12 headers below were
verified from row 1 of the workbook by an owner-authorized, schema-only
inspection outside this repository (no row values were copied).

Personnel identity is `personnel_id` only, matched as exact text (no trim,
case folding or numeric normalization). It is never user_id, technician_id,
a driver id, a name, an email or a phone number: person and login account
are separate records, and no account, technician, driver, department or
assignment data is read or joined here.

The public record exposes only `personnel_id`, `first_name`, `last_name` and
`active_status`. `active_status` is source text: no validation rule exists
in the sheet, so it is not an enum; blank means unknown (None) and is never
defaulted to ACTIVE. Blank names are None too, never substituted. The other
eight columns are known but not public in R2c-1.

Operational scope (independent-review fix R1): R2c-1 is the OPERATIONAL
personnel read. `is_test_data` is classified for every personnel row first:
exact "FALSE" -> operational (included); exact "TRUE" -> an explicitly test
row (excluded everywhere: list, total_items and detail); blank or any other
text -> classification unknown -> the read fails closed
(PERSONNEL_MASTER_DATA_INVALID, TEST_FLAG_INVALID). Identity validation runs
only on the operational rows afterwards, so a test row can never create an
operational duplicate, blank-id failure or detail match. `test_batch_id`
stays internal and is not interpreted; there is no TEST personnel view.
A row whose four public columns are all blank carries no personnel and is
skipped whatever its flag says (e.g. an unchecked checkbox left in an
otherwise empty row) — the pre-existing phantom-row rule.

A list fails as a whole on any identity defect (blank or duplicate
personnel_id among operational rows), with issue counts only; a detail
lookup needs exactly one exact operational match. Error details never
contain ids, names, row numbers, test batch ids or other row values.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.registration import optional_text, text
from app.errors import ApiError
from app.repositories.base import (
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositorySchemaError,
)

PERSONNEL_TAB = "personnel_master"

# Verified header row, in source order.
PERSONNEL_MASTER_COLUMNS: tuple[str, ...] = (
    "personnel_id",
    "first_name",
    "last_name",
    "department",
    "position",
    "branch_id",
    "active_status",
    "technician_id",
    "user_id",
    "is_test_data",
    "test_batch_id",
    "note_th",
)
# R2 Batch R2f-e: the TARGET personnel_master header — the verified header
# above plus the additive `driver_id` link cell, placed after `user_id` with
# the other relationship cells. The live tab does NOT have this column yet: it
# is added (blank, no row value changed) only by a separately authorized live
# schema preparation. The verified PERSONNEL_MASTER_COLUMNS stays unchanged.
PERSONNEL_DRIVER_ID_COLUMN = "driver_id"
PERSONNEL_MASTER_TARGET_COLUMNS: tuple[str, ...] = (
    *PERSONNEL_MASTER_COLUMNS[: PERSONNEL_MASTER_COLUMNS.index("user_id") + 1],
    PERSONNEL_DRIVER_ID_COLUMN,
    *PERSONNEL_MASTER_COLUMNS[PERSONNEL_MASTER_COLUMNS.index("user_id") + 1:],
)
# The public record's columns.
PERSONNEL_PUBLIC_COLUMNS: tuple[str, ...] = ("personnel_id", "first_name", "last_name", "active_status")
# Required and validated by the R2c-1 read: the public columns plus the
# operational-scope flag (read as its formatted text, TRUE / FALSE).
PERSONNEL_READ_COLUMNS: tuple[str, ...] = (*PERSONNEL_PUBLIC_COLUMNS, "is_test_data")

ISSUE_BLANK_ID = "BLANK_PERSONNEL_ID"
ISSUE_DUPLICATE_ID = "DUPLICATE_PERSONNEL_ID"
ISSUE_TEST_FLAG_INVALID = "TEST_FLAG_INVALID"
OPERATIONAL_FLAG = "FALSE"
TEST_FLAG = "TRUE"


@dataclass(frozen=True)
class PersonnelRecord:
    personnel_id: str
    first_name: str | None
    last_name: str | None
    active_status: str | None


def personnel_record(row: Mapping[str, object]) -> PersonnelRecord:
    """Exact source text; blank (whitespace-only) display/status cells -> None."""
    return PersonnelRecord(
        personnel_id=text(row.get("personnel_id")),
        first_name=optional_text(row.get("first_name")),
        last_name=optional_text(row.get("last_name")),
        active_status=optional_text(row.get("active_status")),
    )


def operational_rows(rows: Sequence[Mapping[str, object]]) -> tuple[list[Mapping[str, object]], dict[str, int]]:
    """(operational rows, issue counts). Classifies `is_test_data` on every
    personnel row BEFORE any identity check: exact FALSE kept, exact TRUE
    dropped, anything else counted as TEST_FLAG_INVALID (never guessed)."""
    kept: list[Mapping[str, object]] = []
    invalid = 0
    for row in rows:
        if not any(text(row.get(c)).strip() for c in PERSONNEL_PUBLIC_COLUMNS):
            continue  # no personnel content in this row
        flag = text(row.get("is_test_data"))
        if flag == OPERATIONAL_FLAG:
            kept.append(row)
        elif flag != TEST_FLAG:
            invalid += 1
    return kept, ({ISSUE_TEST_FLAG_INVALID: invalid} if invalid else {})


def identity_issues(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Issue counts (empty = valid): a blank personnel_id, and every row sharing
    a duplicated personnel_id (the R1 reference-list counting rule)."""
    issues: dict[str, int] = {}
    ids = [text(r.get("personnel_id")) for r in rows]
    for pid in ids:
        if not pid.strip():
            issues[ISSUE_BLANK_ID] = issues.get(ISSUE_BLANK_ID, 0) + 1
        elif ids.count(pid) > 1:
            issues[ISSUE_DUPLICATE_ID] = issues.get(ISSUE_DUPLICATE_ID, 0) + 1
    return issues


# ---------------------------------------------------------------------------
# Errors (additive, personnel-specific)
# ---------------------------------------------------------------------------


def _schema_invalid(exc: RepositorySchemaError) -> ApiError:
    return ApiError(
        code="PERSONNEL_MASTER_SCHEMA_INVALID",
        message=str(exc),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
    )


def _read_failed() -> ApiError:
    return ApiError(
        code="PERSONNEL_MASTER_READ_FAILED",
        message=f"{PERSONNEL_TAB} could not be read",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        details={"tab": PERSONNEL_TAB},
    )


def data_invalid(issues: dict[str, int]) -> ApiError:
    return ApiError(
        code="PERSONNEL_MASTER_DATA_INVALID",
        message=f"{PERSONNEL_TAB} contains records whose identity cannot be used exactly",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"tab": PERSONNEL_TAB, "issues": dict(sorted(issues.items()))},
    )


def not_found() -> ApiError:
    return ApiError(
        code="PERSONNEL_NOT_FOUND",
        message="No personnel record has exactly this personnel_id",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def ambiguous(match_count: int) -> ApiError:
    return ApiError(
        code="PERSONNEL_ID_AMBIGUOUS",
        message="More than one personnel record has this personnel_id",
        status_code=status.HTTP_409_CONFLICT,
        details={"match_count": match_count},
    )


class PersonnelService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _read(self) -> list[Mapping[str, object]]:
        """ONE validated personnel_master read, then the operational scope:
        only exact-FALSE rows. Failures are coded, never empty; an unknown
        test flag anywhere fails closed before any identity logic."""
        try:
            read = await self._repository.read_personnel_master_validated()
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

    async def list_personnel(self, params: PageParams) -> Page[PersonnelRecord]:
        rows = await self._read()
        issues = identity_issues(rows)
        if issues:
            raise data_invalid(issues)
        records = sorted((personnel_record(r) for r in rows), key=lambda p: p.personnel_id)
        start = (params.page - 1) * params.page_size
        return Page(
            items=records[start : start + params.page_size],
            page=params.page,
            page_size=params.page_size,
            total_items=len(records),
        )

    async def get_personnel(self, personnel_id: str) -> PersonnelRecord:
        rows = await self._read()
        if not personnel_id.strip():  # a blank id never identifies a person
            raise not_found()
        matches = [r for r in rows if text(r.get("personnel_id")) == personnel_id]
        if not matches:
            raise not_found()
        if len(matches) > 1:
            raise ambiguous(len(matches))
        return personnel_record(matches[0])
