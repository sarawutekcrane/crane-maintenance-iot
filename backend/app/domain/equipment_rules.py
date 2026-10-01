"""Phase 7 Batch 7K2 — storage-independent equipment data rules (approved
7K1 corrected contract, Sections 4.3, 4.5 and 4.6).

Pure functions with no I/O and no Google Sheets library import, shared by the
mock and Google Sheets repositories and the domain services.

- `equipment_row_issue` / `equipment_history_row_issue`: the record gates
  that run BEFORE mapping. The first failing step wins, so a row has at most
  one issue key. Values are compared exactly (no trimming, case folding or
  aliases); the mapping step (UNMAPPABLE_ROW) stays in the repositories.
- `known_text_hazard`: identifies KNOWN cases where an equipment id would be
  altered by the unchanged downstream writers/readers (DEC-K3(a)). It is not
  a safety proof: date, time, percent, currency and other locale-dependent
  interpretations by Google Sheets are NOT detected. A value it does not
  flag is "not detected", never "safe".
"""
from __future__ import annotations

from app.domain.equipment import EquipmentCategory, EquipmentOperationalStatus

ISSUE_BLANK_CATEGORY = "BLANK_CATEGORY"
ISSUE_UNRECOGNIZED_CATEGORY = "UNRECOGNIZED_CATEGORY"
ISSUE_BLANK_STATUS = "BLANK_STATUS"
ISSUE_UNRECOGNIZED_STATUS = "UNRECOGNIZED_STATUS"
ISSUE_UNMAPPABLE_ROW = "UNMAPPABLE_ROW"
# DEC-K9(b): a naive start_at among this equipment's history rows while
# another row's timestamp is timezone-aware. Nothing is reinterpreted.
ISSUE_MIXED_TIMEZONE_TIMESTAMP = "MIXED_TIMEZONE_TIMESTAMP"

CATEGORY_CODES: frozenset[str] = frozenset(c.value for c in EquipmentCategory)
STATUS_CODES: frozenset[str] = frozenset(s.value for s in EquipmentOperationalStatus)

# DEC-K3(a), owner-approved prefix set.
HAZARD_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "'")


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _classify_code(value: object, codes: frozenset[str], blank_issue: str, unknown_issue: str) -> str | None:
    if isinstance(value, str) and value in codes:
        return None
    if _blank(value):
        return blank_issue
    return unknown_issue


def equipment_row_issue(record: dict) -> str | None:
    """Steps 1-2 of the 4.3 gate: category, then status."""
    issue = _classify_code(
        record.get("equipment_type"), CATEGORY_CODES, ISSUE_BLANK_CATEGORY, ISSUE_UNRECOGNIZED_CATEGORY
    )
    if issue is not None:
        return issue
    return _classify_code(
        record.get("equipment_status"), STATUS_CODES, ISSUE_BLANK_STATUS, ISSUE_UNRECOGNIZED_STATUS
    )


def equipment_history_row_issue(record: dict) -> str | None:
    """Step 1 of the 4.5 gate: the status_code."""
    return _classify_code(
        record.get("status_code"), STATUS_CODES, ISSUE_BLANK_STATUS, ISSUE_UNRECOGNIZED_STATUS
    )


def _numeric_hazard(value: str) -> bool:
    """Mirrors the branches of the read-side numeric conversion the Google
    Sheets repository's library applies (gspread 6.x `numericise` with
    underscores not allowed): a value containing "_" is left alone; otherwise
    commas are removed and int(), then float(), are tried. Python's int()/
    float() accept surrounding whitespace, non-ASCII decimal digits, "inf"
    and "nan" — all of which the read would convert."""
    if "_" in value:
        return False
    cleaned = value.replace(",", "")
    for convert in (int, float):
        try:
            convert(cleaned)
            return True
        except ValueError:
            pass
    return False


def known_text_hazard(value: str) -> bool:
    """True when `value` matches a KNOWN hazard: numeric conversion on read,
    a boolean literal, or one of the approved leading characters. False means
    only that no known hazard was detected."""
    if _numeric_hazard(value):
        return True
    if value.upper() in ("TRUE", "FALSE"):
        return True
    return value.startswith(HAZARD_PREFIXES)
