"""R2 Batch R2f-a — Personnel relationship read foundation (READ ONLY).

Final Contract C1 §5 / §6 / §15. Two links are resolved, each from its
approved authority column on `personnel_master`:

- Personnel ↔ Technician: `personnel_master.technician_id` -> technician_master
- Personnel ↔ User Account: `personnel_master.user_id` -> user_account

Both are 0..1 ↔ 0..1. Matching is by exact id only: never by name, display
name, email, phone, role, position, department, branch, id prefix or
similarity, and nothing is ever auto-linked. Driver is NOT handled here (R2f-e).

One shared pure resolver (`resolve_link`) classifies every link:

- UNSET: the personnel cell is blank.
- RESOLVED: exactly one same-scope target has exactly this id, and no other
  in-scope personnel holds the same link.
- AMBIGUOUS: the id matches more than one same-scope target, or more than one
  in-scope personnel holds it (the 0..1 cardinality is violated). Nothing is
  selected.
- SCOPE_UNPROVEN (TEST only): no same-scope target exists and the repository
  either cannot supply TEST-scoped references at all (the live tabs are
  untagged) or the id exists only outside the request's TEST scope (a REAL
  row, or another batch). A TEST personnel never resolves to a REAL entity.
- MISSING: a nonblank id with no target in scope (REAL: a TEST fixture never
  counts; TEST: only when TEST-scoped references are supported and none,
  in any scope, carries the id).

A repository / schema / read failure is an ApiError, never one of these
states. The data scope is the server's (registry data context + test batch,
the R2e rule): REAL = exact-FALSE personnel rows, TEST = exact-TRUE rows of
the server batch; an unclassifiable test flag fails the source closed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.master_lifecycle import in_scope
from app.domain.personnel import (
    OPERATIONAL_FLAG,
    PERSONNEL_PUBLIC_COLUMNS,
    TEST_FLAG,
    ambiguous as personnel_ambiguous,
    data_invalid as personnel_data_invalid,
    not_found as personnel_not_found,
)
from app.domain.reference_read import reference_read
from app.domain.registration import DATA_CONTEXT_REAL, text
from app.domain.registry_write_support import require_write_context
from app.domain.technician import (
    TECHNICIAN_PREFIX,
    TECHNICIAN_TAB,
    TechnicianRecord,
    ambiguous as technician_ambiguous,
    not_found as technician_not_found,
    read_technicians,
    technician_record,
)
from app.repositories.base import (
    REFERENCE_SCOPE_REAL,
    REFERENCE_SCOPE_TEST,
    ReferenceMasterRead,
    Repository,
    ScopedReferenceRow,
)

PERSONNEL_TAB = "personnel_master"
PERSONNEL_PREFIX = "PERSONNEL_MASTER"
# The personnel_master columns the relationship read requires.
PERSONNEL_RELATIONSHIP_COLUMNS: tuple[str, ...] = (
    *PERSONNEL_PUBLIC_COLUMNS, "technician_id", "user_id", "is_test_data", "test_batch_id",
)
USER_ACCOUNT_TAB = "user_account"
USER_ACCOUNT_PREFIX = "USER_ACCOUNT"
# Bounded: the identity only. No name, email, phone, role, MFA or status column.
USER_ACCOUNT_READ_COLUMNS: tuple[str, ...] = ("user_id",)

RESOLVED = "RESOLVED"
UNSET = "UNSET"
MISSING = "MISSING"
AMBIGUOUS = "AMBIGUOUS"
SCOPE_UNPROVEN = "SCOPE_UNPROVEN"
RESOLUTIONS = (RESOLVED, UNSET, MISSING, AMBIGUOUS, SCOPE_UNPROVEN)


@dataclass(frozen=True)
class LinkResolution:
    resolution: str
    linked_id: str | None  # the exact personnel cell; None when UNSET
    target: ScopedReferenceRow | None = None  # only when RESOLVED


@dataclass(frozen=True)
class PersonnelRelationships:
    personnel_id: str
    technician: LinkResolution
    technician_record: TechnicianRecord | None
    account: LinkResolution


@dataclass(frozen=True)
class TechnicianPersonnel:
    technician_id: str
    resolution: str  # RESOLVED / UNSET (no personnel) / AMBIGUOUS
    personnel_id: str | None
    match_count: int


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def same_scope(row: ScopedReferenceRow, context: str, batch_id: str) -> bool:
    """REAL: a REAL-scope row only. TEST: a TEST-scope row of exactly the batch."""
    if context == DATA_CONTEXT_REAL:
        return row.scope == REFERENCE_SCOPE_REAL
    return row.scope == REFERENCE_SCOPE_TEST and row.test_batch_id == batch_id


def resolve_link(
    linked_id: str,
    *,
    id_column: str,
    reference: ReferenceMasterRead,
    context: str,
    batch_id: str,
    holders: int,
) -> LinkResolution:
    """Classify one link. `holders` = in-scope personnel whose cell is exactly
    `linked_id` (the subject included)."""
    if not linked_id.strip():
        return LinkResolution(UNSET, None)
    if holders > 1:
        return LinkResolution(AMBIGUOUS, linked_id)
    exact = [r for r in reference.rows if text(r.values.get(id_column)) == linked_id]
    matches = [r for r in exact if same_scope(r, context, batch_id)]
    if len(matches) > 1:
        return LinkResolution(AMBIGUOUS, linked_id)
    if matches:
        return LinkResolution(RESOLVED, linked_id, matches[0])
    if context != DATA_CONTEXT_REAL and (not reference.test_scope_supported or exact):
        return LinkResolution(SCOPE_UNPROVEN, linked_id)
    return LinkResolution(MISSING, linked_id)


def _is_record(row: Mapping[str, object]) -> bool:
    return any(text(row.get(c)).strip() for c in PERSONNEL_PUBLIC_COLUMNS)


def scoped_personnel(rows: Sequence[Mapping[str, object]], context: str, batch_id: str) -> list[Mapping[str, object]]:
    """The in-scope personnel records. Classification first: any record whose
    test flag is not exactly TRUE / FALSE fails the whole source closed."""
    records = [r for r in rows if _is_record(r)]
    invalid = sum(1 for r in records if text(r.get("is_test_data")) not in (TEST_FLAG, OPERATIONAL_FLAG))
    if invalid:
        raise personnel_data_invalid({"TEST_FLAG_INVALID": invalid})
    return [r for r in records if in_scope(r, context, batch_id)]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PersonnelRelationshipService:
    def __init__(self, repository: Repository, context: str | None, batch_id: str) -> None:
        self._repository = repository
        self._context = context
        self._batch_id = batch_id

    async def _personnel(self, context: str) -> list[Mapping[str, object]]:
        read = await reference_read(
            self._repository.read_personnel_relationship_master(), PERSONNEL_PREFIX, PERSONNEL_TAB
        )
        return scoped_personnel(read.rows, context, self._batch_id)

    async def _accounts(self) -> ReferenceMasterRead:
        return await reference_read(
            self._repository.read_user_account_reference(), USER_ACCOUNT_PREFIX, USER_ACCOUNT_TAB
        )

    def _link(self, people, row, column: str, reference: ReferenceMasterRead, id_column: str, context: str):
        linked = text(row.get(column))
        holders = sum(1 for p in people if text(p.get(column)) == linked)
        return resolve_link(linked, id_column=id_column, reference=reference, context=context,
                            batch_id=self._batch_id, holders=holders)

    async def personnel_relationships(self, personnel_id: str) -> PersonnelRelationships:
        context = require_write_context(self._context, self._batch_id)
        people = await self._personnel(context)
        matches = [p for p in people if personnel_id.strip() and text(p.get("personnel_id")) == personnel_id]
        if not matches:
            raise personnel_not_found()
        if len(matches) > 1:
            raise personnel_ambiguous(len(matches))
        row = matches[0]
        technicians = await read_technicians(self._repository)
        accounts = await self._accounts()
        technician = self._link(people, row, "technician_id", technicians, "technician_id", context)
        account = self._link(people, row, "user_id", accounts, "user_id", context)
        return PersonnelRelationships(
            personnel_id=personnel_id,
            technician=technician,
            technician_record=technician_record(technician.target.values) if technician.target else None,
            account=account,
        )

    async def technician_personnel(self, technician_id: str) -> TechnicianPersonnel:
        """Reverse resolution: the technician must exist in the request's
        scope; then the in-scope personnel holding exactly this id. More than
        one holder is AMBIGUOUS and nothing is selected (fail closed)."""
        context = require_write_context(self._context, self._batch_id)
        technicians = await read_technicians(self._repository)
        targets = [
            r for r in technicians.rows
            if technician_id.strip() and text(r.values.get("technician_id")) == technician_id
            and same_scope(r, context, self._batch_id)
        ]
        if not targets:
            raise technician_not_found()
        if len(targets) > 1:
            raise technician_ambiguous(len(targets))
        people = await self._personnel(context)
        holders = [p for p in people if text(p.get("technician_id")) == technician_id]
        if not holders:
            return TechnicianPersonnel(technician_id, UNSET, None, 0)
        if len(holders) > 1:
            return TechnicianPersonnel(technician_id, AMBIGUOUS, None, len(holders))
        return TechnicianPersonnel(technician_id, RESOLVED, text(holders[0].get("personnel_id")), 1)


__all__ = [
    "AMBIGUOUS",
    "MISSING",
    "PERSONNEL_RELATIONSHIP_COLUMNS",
    "RESOLUTIONS",
    "RESOLVED",
    "SCOPE_UNPROVEN",
    "TECHNICIAN_PREFIX",
    "TECHNICIAN_TAB",
    "UNSET",
    "USER_ACCOUNT_READ_COLUMNS",
    "USER_ACCOUNT_TAB",
    "LinkResolution",
    "PersonnelRelationshipService",
    "PersonnelRelationships",
    "TechnicianPersonnel",
    "resolve_link",
    "same_scope",
    "scoped_personnel",
]
