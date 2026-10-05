"""Phase 7 Batch 7O2a — registry fields on a vehicle (registration text,
registration province, responsible branch) and the registry data context.

Contract: Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2 §7.1 (one
`{state, value}` shape), §4.1 (columns), §8.1 (contexts). Registry values come
only from the validated, text-only vehicle_master reads; the legacy
`_vehicle_from_row` mapper and the dashboard read never see them, so a
registry data problem cannot change the vehicle population gates or K1-K6.
"""
from __future__ import annotations

from collections.abc import Container, Mapping
from dataclasses import dataclass

from app.domain.registration import DATA_CONTEXT_REAL, DATA_CONTEXT_TEST, text

REGISTRATION_NO_COLUMN = "registration_no"
REGISTRATION_PROVINCE_COLUMN = "registration_province_code"
RESPONSIBLE_BRANCH_COLUMN = "responsible_branch_id"
REGISTRY_COLUMNS: tuple[str, ...] = (
    REGISTRATION_NO_COLUMN,
    REGISTRATION_PROVINCE_COLUMN,
    RESPONSIBLE_BRANCH_COLUMN,
)

STATE_NOT_IN_SCHEMA = "NOT_IN_SCHEMA"
STATE_NOT_RECORDED = "NOT_RECORDED"
STATE_RECORDED = "RECORDED"


@dataclass(frozen=True)
class RegistryField:
    state: str
    value: str | None = None


@dataclass(frozen=True)
class VehicleRegistry:
    registration_no: RegistryField
    registration_province: RegistryField
    responsible_branch: RegistryField

    @property
    def registration_pair(self) -> tuple[str | None, str | None] | None:
        """(text, province) for consistency checks, or None when either
        registration column is not in the master schema."""
        if STATE_NOT_IN_SCHEMA in (self.registration_no.state, self.registration_province.state):
            return None
        return self.registration_no.value, self.registration_province.value


def registry_field(record: Mapping[str, object], column: str, available: Container[str]) -> RegistryField:
    """NOT_IN_SCHEMA when the column is absent from the validated header;
    NOT_RECORDED for a blank (or whitespace-only) cell; otherwise RECORDED with
    the stored text exactly (no trim, case or digit change)."""
    if column not in available:
        return RegistryField(STATE_NOT_IN_SCHEMA)
    raw = text(record.get(column))
    if not raw.strip():
        return RegistryField(STATE_NOT_RECORDED)
    return RegistryField(STATE_RECORDED, raw)


def registry_from_record(record: Mapping[str, object], available: Container[str]) -> VehicleRegistry:
    return VehicleRegistry(
        registration_no=registry_field(record, REGISTRATION_NO_COLUMN, available),
        registration_province=registry_field(record, REGISTRATION_PROVINCE_COLUMN, available),
        responsible_branch=registry_field(record, RESPONSIBLE_BRANCH_COLUMN, available),
    )


NOT_IN_SCHEMA_REGISTRY = VehicleRegistry(
    registration_no=RegistryField(STATE_NOT_IN_SCHEMA),
    registration_province=RegistryField(STATE_NOT_IN_SCHEMA),
    responsible_branch=RegistryField(STATE_NOT_IN_SCHEMA),
)

DATA_CONTEXTS = (DATA_CONTEXT_TEST, DATA_CONTEXT_REAL)


# ---------------------------------------------------------------------------
# Reference lists (branch_master, province_master) — contract §4.2, §7.2
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceEntry:
    code: str
    name: str
    is_active: bool


def parse_reference_rows(
    rows: list[Mapping[str, object]],
    *,
    code_column: str,
    name_column: str,
    active_column: str = "is_active",
    active_column_present: bool = True,
) -> tuple[list[ReferenceEntry], dict[str, int]]:
    """Entries sorted by code, plus issue counts (empty = valid): BLANK_CODE,
    DUPLICATE_CODE (every row sharing a code), BLANK_NAME, INVALID_ACTIVE_FLAG
    (anything but exactly TRUE/FALSE). Codes and names are exact text. Without
    the active column every entry is active (branch_master's optional column)."""
    issues: dict[str, int] = {}

    def count(code: str) -> None:
        issues[code] = issues.get(code, 0) + 1

    codes = [text(r.get(code_column)) for r in rows]
    entries: list[ReferenceEntry] = []
    for row, code in zip(rows, codes):
        name = text(row.get(name_column))
        if not code.strip():
            count("BLANK_CODE")
        elif codes.count(code) > 1:
            count("DUPLICATE_CODE")
        if not name.strip():
            count("BLANK_NAME")
        active = True
        if active_column_present:
            flag = text(row.get(active_column))
            if flag not in ("TRUE", "FALSE"):
                count("INVALID_ACTIVE_FLAG")
            active = flag == "TRUE"
        entries.append(ReferenceEntry(code=code, name=name, is_active=active))
    entries.sort(key=lambda e: e.code)
    return entries, issues
