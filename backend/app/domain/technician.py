"""R2 Batch R2f-a — read-only technician master (bounded reference read).

R2f supersedes the Core Demo Delta §G statement "there is no technician
master" (Final Contract C1 §2): the live prototype has `technician_master`,
and `personnel_master.technician_id` is the Personnel ↔ Technician link
authority. This module only READS it. No technician_master write method exists
in R2f, and legacy Repair / PM assignments keep their opaque `user_id` strings
(they are never reinterpreted as technician ids).

Bounded read: technician_id, first_name, last_name and active_status only.
`department`, `position` and `branch_id` duplicate person attributes and are
legacy source text, and `source_file` / `source_sheet` / `source_row` are
import metadata: none of them is read or exposed. `active_status` is source
text, never an enum; blank means unknown (None), never defaulted.

Identity is `technician_id`, exact text (no trim, case folding or numeric
normalisation). A list fails as a whole on a blank or duplicate technician_id
(issue counts only); a detail needs exactly one exact match. Error details never
carry ids, names or row values.

R2 Batch R2f-h4 B2 (C1 Amendment A1-§15, owner decision O4 — supersedes the
R2f-a "REAL-scope rows only" rule): the list and detail show only rows of the
SERVER-DERIVED scope, the same rule as the relationship routes
(`personnel_relationship.same_scope`):
- REAL: rows the repository proves REAL (every live row: the live tab carries
  no test metadata);
- TEST: rows the repository proves TEST-scoped AND of exactly the server batch
  (only a fake / mock repository can supply them; live TEST is empty, never a
  REAL row);
- unconfigured context, or TEST without a batch: 503
  REGISTRY_DATA_CONTEXT_NOT_CONFIGURED before any repository read.
There is no client-selectable scope. Identity integrity is evaluated over the
returned scope.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.reference_read import reference_read
from app.domain.registration import DATA_CONTEXT_REAL, optional_text, text
from app.domain.registry_write_support import require_write_context
from app.errors import ApiError
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST, Repository, ScopedReferenceRow

TECHNICIAN_TAB = "technician_master"
TECHNICIAN_READ_COLUMNS: tuple[str, ...] = ("technician_id", "first_name", "last_name", "active_status")
TECHNICIAN_PREFIX = "TECHNICIAN_MASTER"

ISSUE_BLANK_ID = "BLANK_TECHNICIAN_ID"
ISSUE_DUPLICATE_ID = "DUPLICATE_TECHNICIAN_ID"


@dataclass(frozen=True)
class TechnicianRecord:
    technician_id: str
    first_name: str | None
    last_name: str | None
    active_status: str | None


def technician_record(values: dict[str, str]) -> TechnicianRecord:
    """Exact source text; blank display / status cells -> None."""
    return TechnicianRecord(
        technician_id=text(values.get("technician_id")),
        first_name=optional_text(values.get("first_name")),
        last_name=optional_text(values.get("last_name")),
        active_status=optional_text(values.get("active_status")),
    )


def identity_issues(rows: Sequence[ScopedReferenceRow]) -> dict[str, int]:
    """Issue counts (empty = valid): blank technician_id, and every row sharing
    a duplicated technician_id (the R1 reference-list counting rule)."""
    issues: dict[str, int] = {}
    ids = [text(r.values.get("technician_id")) for r in rows]
    for tid in ids:
        if not tid.strip():
            issues[ISSUE_BLANK_ID] = issues.get(ISSUE_BLANK_ID, 0) + 1
        elif ids.count(tid) > 1:
            issues[ISSUE_DUPLICATE_ID] = issues.get(ISSUE_DUPLICATE_ID, 0) + 1
    return issues


def data_invalid(issues: dict[str, int]) -> ApiError:
    return ApiError(
        code=f"{TECHNICIAN_PREFIX}_DATA_INVALID",
        message=f"{TECHNICIAN_TAB} contains records whose identity cannot be used exactly",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"tab": TECHNICIAN_TAB, "issues": dict(sorted(issues.items()))},
    )


def not_found() -> ApiError:
    return ApiError(
        code="TECHNICIAN_NOT_FOUND",
        message="No technician record has exactly this technician_id",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def ambiguous(match_count: int) -> ApiError:
    return ApiError(
        code="TECHNICIAN_ID_AMBIGUOUS",
        message="More than one technician record has this technician_id",
        status_code=status.HTTP_409_CONFLICT,
        details={"match_count": match_count},
    )


async def read_technicians(repository: Repository):
    """ONE bounded technician_master read with the shared error mapping."""
    return await reference_read(repository.read_technician_master_reference(), TECHNICIAN_PREFIX, TECHNICIAN_TAB)


def in_server_scope(row: ScopedReferenceRow, context: str, batch_id: str) -> bool:
    """REAL: a REAL-scope row only. TEST: a TEST-scope row of exactly the batch.
    The repository's proven scope only — never an id, name or prefix. (Same rule
    as `personnel_relationship.same_scope`, which imports this module; a parity
    test pins the two together.)"""
    if context == DATA_CONTEXT_REAL:
        return row.scope == REFERENCE_SCOPE_REAL
    return row.scope == REFERENCE_SCOPE_TEST and row.test_batch_id == batch_id


class TechnicianService:
    def __init__(self, repository: Repository, context: str | None, batch_id: str) -> None:
        self._repository = repository
        self._context = context
        self._batch_id = batch_id

    async def _scoped_rows(self) -> list[ScopedReferenceRow]:
        # The context is proven BEFORE any repository read (503 otherwise).
        context = require_write_context(self._context, self._batch_id)
        read = await read_technicians(self._repository)
        return [r for r in read.rows if in_server_scope(r, context, self._batch_id)]

    async def list_technicians(self, params: PageParams) -> Page[TechnicianRecord]:
        rows = await self._scoped_rows()
        issues = identity_issues(rows)
        if issues:
            raise data_invalid(issues)
        records = sorted((technician_record(r.values) for r in rows), key=lambda t: t.technician_id)
        start = (params.page - 1) * params.page_size
        return Page(
            items=records[start : start + params.page_size],
            page=params.page,
            page_size=params.page_size,
            total_items=len(records),
        )

    async def get_technician(self, technician_id: str) -> TechnicianRecord:
        rows = await self._scoped_rows()
        if not technician_id.strip():  # a blank id never identifies a technician
            raise not_found()
        matches = [r for r in rows if text(r.values.get("technician_id")) == technician_id]
        if not matches:
            raise not_found()
        if len(matches) > 1:
            raise ambiguous(len(matches))
        return technician_record(matches[0].values)


__all__ = [
    "TECHNICIAN_PREFIX",
    "TECHNICIAN_READ_COLUMNS",
    "TECHNICIAN_TAB",
    "TechnicianRecord",
    "TechnicianService",
    "ambiguous",
    "data_invalid",
    "identity_issues",
    "in_server_scope",
    "not_found",
    "read_technicians",
    "technician_record",
]
