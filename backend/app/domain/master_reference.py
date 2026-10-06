"""R2 Batch R2a — shared master-reference read foundation (read-only).

Resolves stored stable IDs of three existing masters (branch, model, part) to
one small internal shape. No endpoint, no write and no frontend consumer uses
it yet; later R2 batches build on it.

States (the accepted R1 vocabulary, Final Rev2 §7.2):

- RESOLVED: the source was read and exactly one row has this id;
- UNKNOWN_CODE: the source was read and no row has this id;
- REFERENCE_UNAVAILABLE: the source could not be read, or its data cannot
  identify the id (`unavailable_reason` says which). Never reported as
  UNKNOWN_CODE, empty or a default.

Active metadata is separate from identity. An inactive row is still RESOLVED
(historical references stay valid). It is never guessed as active or
inactive:
- branch: is_active is optional (frozen R1); without the column the metadata
  is NOT_IN_SCHEMA;
- model: no approved active semantics, so always NOT_IN_SCHEMA;
- part: is_active is existing required metadata; a part_master without the
  column is a structural problem (REFERENCE_UNAVAILABLE / SCHEMA_INVALID).

Branch reuses the frozen R1 reader and `parse_reference_rows` unchanged, with
the same whole-table rule as R1 (any data issue makes branch_master
unusable). Ids are matched as exact text; a blank id never matches a row.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.domain.registration import text
from app.domain.vehicle_registry import STATE_NOT_IN_SCHEMA, parse_reference_rows
from app.repositories.base import (
    RegistryTableRead,
    Repository,
    RepositoryError,
    RepositorySchemaError,
    VehicleModelSearchEntry,
)

MASTER_KIND_BRANCH = "BRANCH"
MASTER_KIND_MODEL = "MODEL"
MASTER_KIND_PART = "PART"

RESOLVED = "RESOLVED"
UNKNOWN_CODE = "UNKNOWN_CODE"
REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"

ACTIVE = "ACTIVE"
INACTIVE = "INACTIVE"
ACTIVE_NOT_IN_SCHEMA = STATE_NOT_IN_SCHEMA

# Why a reference is REFERENCE_UNAVAILABLE.
READ_FAILED = "READ_FAILED"  # the source could not be read
SCHEMA_INVALID = "SCHEMA_INVALID"  # proven structural problem (missing tab/header, ...)
DATA_INVALID = "DATA_INVALID"  # rows cannot be trusted (R1 branch issues; bad part flag)
DUPLICATE_ID = "DUPLICATE_ID"  # more than one row has this id


@dataclass(frozen=True)
class MasterReference:
    master_kind: str
    reference_id: str
    state: str
    label: str | None = None  # the master's existing name column, verbatim
    active_state: str | None = None  # ACTIVE / INACTIVE / NOT_IN_SCHEMA when RESOLVED
    unavailable_reason: str | None = None  # only when REFERENCE_UNAVAILABLE


@dataclass(frozen=True)
class MasterRow:
    """One source row: its label and active metadata, or the reason its
    active metadata cannot be used (`invalid_reason`)."""

    label: str
    active_state: str
    invalid_reason: str | None = None


# id -> every row with that id (exact text), blank ids excluded.
MasterTable = Mapping[str, tuple[MasterRow, ...]]


def _unique_ids(reference_ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(reference_ids))


def unavailable(kind: str, reference_ids: Iterable[str], reason: str) -> dict[str, MasterReference]:
    return {
        rid: MasterReference(kind, rid, REFERENCE_UNAVAILABLE, unavailable_reason=reason)
        for rid in _unique_ids(reference_ids)
    }


def resolve_ids(kind: str, reference_ids: Iterable[str], table: MasterTable) -> dict[str, MasterReference]:
    """Pure resolution against a successfully read table."""
    result: dict[str, MasterReference] = {}
    for rid in _unique_ids(reference_ids):
        rows = table.get(rid, ()) if rid.strip() else ()
        if not rows:
            result[rid] = MasterReference(kind, rid, UNKNOWN_CODE)
        elif len(rows) > 1:
            result[rid] = MasterReference(kind, rid, REFERENCE_UNAVAILABLE, unavailable_reason=DUPLICATE_ID)
        elif rows[0].invalid_reason is not None:
            result[rid] = MasterReference(kind, rid, REFERENCE_UNAVAILABLE, unavailable_reason=rows[0].invalid_reason)
        else:
            result[rid] = MasterReference(kind, rid, RESOLVED, label=rows[0].label, active_state=rows[0].active_state)
    return result


def _add(table: dict[str, tuple[MasterRow, ...]], rid: str, row: MasterRow) -> None:
    if rid.strip():
        table[rid] = (*table.get(rid, ()), row)


def branch_table(read: RegistryTableRead) -> MasterTable | None:
    """branch_master through the frozen R1 parser, exactly as the R1 branch
    reads call it. None when R1 would report BRANCH_MASTER_DATA_INVALID. With
    no is_active column R1 treats every branch as active (C-c8); here the
    metadata is NOT_IN_SCHEMA, which equally never makes a branch inactive."""
    has_active = "is_active" in read.columns
    entries, issues = parse_reference_rows(
        read.rows, code_column="branch_id", name_column="branch_name", active_column_present=has_active
    )
    if issues:
        return None
    table: dict[str, tuple[MasterRow, ...]] = {}
    for entry in entries:
        active = (ACTIVE if entry.is_active else INACTIVE) if has_active else ACTIVE_NOT_IN_SCHEMA
        _add(table, entry.code, MasterRow(entry.name, active))
    return table


def model_table(entries: Iterable[VehicleModelSearchEntry]) -> MasterTable:
    """model_master identity only: the label is model_name; no active
    semantics exist for models, so the metadata is always NOT_IN_SCHEMA."""
    table: dict[str, tuple[MasterRow, ...]] = {}
    for entry in entries:
        _add(table, entry.model_id, MasterRow(entry.model_name, ACTIVE_NOT_IN_SCHEMA))
    return table


def part_table(read: RegistryTableRead) -> MasterTable | None:
    """part_master identity: the label is name. None when the required
    is_active column is absent (SCHEMA_INVALID). is_active is used only as
    exact TRUE/FALSE text; any other value (blank included) makes that row's
    reference DATA_INVALID rather than a guessed active state."""
    if "is_active" not in read.columns:
        return None
    table: dict[str, tuple[MasterRow, ...]] = {}
    for row in read.rows:
        label = text(row.get("name"))
        flag = text(row.get("is_active"))
        if flag == "TRUE":
            item = MasterRow(label, ACTIVE)
        elif flag == "FALSE":
            item = MasterRow(label, INACTIVE)
        else:
            item = MasterRow(label, ACTIVE_NOT_IN_SCHEMA, invalid_reason=DATA_INVALID)
        _add(table, text(row.get("part_id")), item)
    return table


def _failure_reason(exc: RepositoryError) -> str:
    return SCHEMA_INVALID if isinstance(exc, RepositorySchemaError) else READ_FAILED


class MasterReferenceResolver:
    """One bounded repository read per call; read-only."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def resolve_branches(self, reference_ids: Iterable[str]) -> dict[str, MasterReference]:
        ids = _unique_ids(reference_ids)
        try:
            read = await self._repository.read_branch_master_validated()
        except RepositoryError as exc:
            return unavailable(MASTER_KIND_BRANCH, ids, _failure_reason(exc))
        table = branch_table(read)
        if table is None:
            return unavailable(MASTER_KIND_BRANCH, ids, DATA_INVALID)
        return resolve_ids(MASTER_KIND_BRANCH, ids, table)

    async def resolve_models(self, reference_ids: Iterable[str]) -> dict[str, MasterReference]:
        ids = _unique_ids(reference_ids)
        try:
            entries = await self._repository.read_vehicle_model_search_index()
        except RepositoryError as exc:
            return unavailable(MASTER_KIND_MODEL, ids, _failure_reason(exc))
        return resolve_ids(MASTER_KIND_MODEL, ids, model_table(entries))

    async def resolve_parts(self, reference_ids: Iterable[str]) -> dict[str, MasterReference]:
        ids = _unique_ids(reference_ids)
        try:
            read = await self._repository.read_part_master_reference()
        except RepositoryError as exc:
            return unavailable(MASTER_KIND_PART, ids, _failure_reason(exc))
        table = part_table(read)
        if table is None:
            return unavailable(MASTER_KIND_PART, ids, SCHEMA_INVALID)
        return resolve_ids(MASTER_KIND_PART, ids, table)
