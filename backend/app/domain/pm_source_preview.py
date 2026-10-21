"""R4-B1 (Mock only) — reproducible, read-only PM source preview (deliverable D1).

The input is rows the caller has ALREADY read from an authorized LOCAL source
subset (sheet name -> list of row mappings, header names as keys). This module
performs no I/O at all: it never opens a file, never calls a repository, never
reaches Google Sheets (TEST/REAL) and never writes anything, so repeating a
preview over identical input yields the identical result and digest.

Every data row of a known source tab is accounted for exactly once as
ACCEPT, REVIEW or EXCLUDE; REVIEW and EXCLUDE rows (and every unknown tab) get a
ledger entry carrying the minimum fields `source_file, sheet, row_or_key, column,
raw_reference, issue, reason, action, evidence, reviewer, reviewed_at`. Nothing
is silently dropped, merged or invented:
- no identifier is generated for a row that lacks one (REVIEW instead);
- a raw `35` outside the numeric columns stays raw ambiguous input (REVIEW) — it
  is never read as an action checkbox, Plan ID, part, quantity or result;
- duplicate Set identities / Item keys are never merged (REVIEW, all copies);
- a Set whose driving component is not stated (`NOT_SEPARATED_IN_FORM`), whose
  meter is not ENGINE_HOUR / PTO_HOUR / ODOMETER, or whose unit does not match
  its meter cannot become an active candidate (REVIEW; no calendar substitute);
- `vehicle_pm_mapping` rows are candidates only — a preview never assigns a Plan;
- `replacement_policy` / `replacement_items` are metadata reference only (EXCLUDE
  from the active candidate; no threshold, part history or advisory in B1).

COLUMN CONTRACT — UNVERIFIED: the header names below are the B1 preview
contract. They have NOT been checked against the Owner's `MAINTENANCE.xlsx`
(not available in this environment); a real header that differs makes the row
REVIEW (missing required column), never a guess.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

from app.domain.request_replay import canonical_json

ACCEPT = "ACCEPT"
REVIEW = "REVIEW"
EXCLUDE = "EXCLUDE"

SHEET_CYCLES = "source_pm_cycles"
SHEET_ITEMS = "source_pm_items"
SHEET_STANDARD = "source_pm_standard"
SHEET_VEHICLE_MAPPING = "vehicle_pm_mapping"
SHEET_REPLACEMENT_POLICY = "replacement_policy"
SHEET_REPLACEMENT_ITEMS = "replacement_items"
KNOWN_SHEETS: tuple[str, ...] = (SHEET_CYCLES, SHEET_ITEMS, SHEET_STANDARD, SHEET_VEHICLE_MAPPING,
                                 SHEET_REPLACEMENT_POLICY, SHEET_REPLACEMENT_ITEMS)

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    SHEET_CYCLES: ("plan_code", "model_variant", "section", "set_code", "meter_type", "interval_value",
                   "interval_unit", "source_doc"),
    SHEET_ITEMS: ("plan_code", "model_variant", "section", "set_code", "item_key", "sequence", "task_text",
                  "source_doc"),
    SHEET_STANDARD: ("doc_code", "doc_status"),
    SHEET_VEHICLE_MAPPING: ("vehicle_ref",),
    SHEET_REPLACEMENT_POLICY: (),
    SHEET_REPLACEMENT_ITEMS: (),
}
# Columns where a number is the expected content; a raw 35 anywhere else is ambiguous.
NUMERIC_COLUMNS = frozenset({"interval_value", "sequence"})
AMBIGUOUS_RAW = "35"

SECTION_CARRIER = "CARRIER"
SECTION_CRANE = "CRANE"
SECTION_NOT_SEPARATED = "NOT_SEPARATED_IN_FORM"
SECTIONS = frozenset({SECTION_CARRIER, SECTION_CRANE, SECTION_NOT_SEPARATED})
# The source unit each explicit meter must carry (no conversion, no alias merge).
METER_UNITS: dict[str, str] = {"ENGINE_HOUR": "hour", "PTO_HOUR": "hour", "ODOMETER": "km"}
DOC_CURRENT = "CURRENT"
DOC_NONCURRENT = frozenset({"CANCELLED", "BLANK_TEMPLATE"})

# The first data row of a tab is spreadsheet row 2 (row 1 is the header).
FIRST_DATA_ROW = 2


@dataclass(frozen=True)
class LedgerEntry:
    source_file: str
    sheet: str
    row_or_key: str
    column: str
    raw_reference: str
    issue: str
    reason: str
    action: str
    evidence: str = ""
    reviewer: str = ""
    reviewed_at: str = ""
    plan_code: str = ""

    @property
    def unresolved(self) -> bool:
        return self.action == REVIEW and not self.reviewer


@dataclass(frozen=True)
class SheetAccount:
    sheet: str
    total: int
    accepted: int
    review: int
    excluded: int

    @property
    def balanced(self) -> bool:
        return self.accepted + self.review + self.excluded == self.total


@dataclass(frozen=True)
class CandidateSet:
    """One source-backed Set/Cycle candidate; raw text kept verbatim."""

    plan_code: str
    model_variant: str
    section: str
    set_code: str
    meter_type: str
    interval_value: float
    interval_unit: str
    raw_interval: str
    independent_group: str
    source_doc: str
    source_row: str


@dataclass(frozen=True)
class CandidateItem:
    plan_code: str
    model_variant: str
    section: str
    set_code: str
    item_key: str
    sequence: int
    task_text: str
    method: str
    standard: str
    source_doc: str
    source_row: str


@dataclass(frozen=True)
class MappingCandidate:
    """A source vehicle -> Plan candidate. NEVER an assignment: `plan_code` empty
    means the source names no Plan (valid; may stay unassigned permanently)."""

    vehicle_ref: str
    plan_code: str
    source_row: str


@dataclass(frozen=True)
class PreviewResult:
    source_file: str
    accounts: tuple[SheetAccount, ...]
    ledger: tuple[LedgerEntry, ...]
    sets: tuple[CandidateSet, ...]
    items: tuple[CandidateItem, ...]
    mapping_candidates: tuple[MappingCandidate, ...]
    digest: str = field(default="")

    def account(self, sheet: str) -> SheetAccount | None:
        return next((a for a in self.accounts if a.sheet == sheet), None)

    def unresolved_reviews(self, plan_code: str | None = None) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self.ledger
                     if e.unresolved and (plan_code is None or e.plan_code in ("", plan_code)))


def _raw(value: object) -> str:
    """The cell exactly as text (None -> ""); never trimmed for storage."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _key(value: object) -> str:
    return _raw(value).strip()


def _row_label(index: int) -> str:
    return f"row:{index + FIRST_DATA_ROW}"


class _Collector:
    def __init__(self, source_file: str) -> None:
        self.source_file = source_file
        self.ledger: list[LedgerEntry] = []

    def add(self, sheet: str, row: str, column: str, raw: str, issue: str, reason: str, action: str,
            plan_code: str = "") -> None:
        self.ledger.append(LedgerEntry(self.source_file, sheet, row, column, raw, issue, reason, action,
                                       evidence=f"{self.source_file}!{sheet}!{row}", plan_code=plan_code))


def _common_issues(sheet: str, row: Mapping[str, object]) -> list[tuple[str, str, str, str]]:
    """(column, raw, issue, reason) problems that make any row of `sheet` REVIEW."""
    issues = [(col, "", "MISSING_REQUIRED_VALUE", f"required column '{col}' is absent or blank")
              for col in REQUIRED_COLUMNS[sheet] if not _key(row.get(col))]
    for col in sorted(row):
        if col not in NUMERIC_COLUMNS and _key(row.get(col)) == AMBIGUOUS_RAW:
            issues.append((col, _raw(row.get(col)), "AMBIGUOUS_RAW_35",
                           "raw 35 kept as raw input; not an action, Plan ID, part, quantity or result"))
    return issues


def _parse_interval(raw: str) -> float | None:
    try:
        value = float(raw.strip().replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_sequence(raw: str) -> int | None:
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    return int(value) if value.is_integer() and value > 0 else None


def preview_source(workbook: Mapping[str, Sequence[Mapping[str, object]]], *,
                   source_file: str) -> PreviewResult:
    """Read-only preview of an authorized local source subset. Pure: the input is
    never mutated and nothing is written anywhere."""
    out = _Collector(source_file)
    accounts: list[SheetAccount] = []

    for sheet in sorted(workbook):
        if sheet not in KNOWN_SHEETS:
            out.add(sheet, "sheet", "", f"rows={len(workbook[sheet])}", "SHEET_OUT_OF_B1_SCOPE",
                    "tab is not a B1 PM Master source; not read further", EXCLUDE)

    # -- source_pm_standard: which documents are current --------------------------
    standard_rows = workbook.get(SHEET_STANDARD, ())
    doc_status: dict[str, str] = {}
    counts = Counter()
    for index, row in enumerate(standard_rows):
        label, doc = _row_label(index), _key(row.get("doc_code"))
        issues = _common_issues(SHEET_STANDARD, row)
        status_ = _key(row.get("doc_status")).upper()
        if not issues and status_ not in DOC_NONCURRENT and status_ != DOC_CURRENT:
            issues.append(("doc_status", _raw(row.get("doc_status")), "UNKNOWN_DOC_STATUS",
                           "document status is neither CURRENT nor a known non-current state"))
        if issues:
            counts[REVIEW] += 1
            for col, raw, issue, reason in issues:
                out.add(SHEET_STANDARD, label, col, raw, issue, reason, REVIEW)
            if doc:
                doc_status.setdefault(doc, "REVIEW")
            continue
        if doc in doc_status:
            counts[REVIEW] += 1
            out.add(SHEET_STANDARD, label, "doc_code", doc, "DUPLICATE_DOC_CODE",
                    "document code appears more than once; not merged", REVIEW)
            doc_status[doc] = "REVIEW"
            continue
        doc_status[doc] = status_
        if status_ in DOC_NONCURRENT:
            counts[EXCLUDE] += 1
            out.add(SHEET_STANDARD, label, "doc_status", _raw(row.get("doc_status")), f"DOC_{status_}",
                    "non-current document excluded from the active candidate", EXCLUDE)
        else:
            counts[ACCEPT] += 1
    if SHEET_STANDARD in workbook:
        accounts.append(SheetAccount(SHEET_STANDARD, len(standard_rows), counts[ACCEPT], counts[REVIEW],
                                     counts[EXCLUDE]))

    def doc_issue(row: Mapping[str, object]) -> tuple[str, str, str, str] | None:
        doc = _key(row.get("source_doc"))
        state = doc_status.get(doc)
        if state == DOC_CURRENT:
            return None
        if state in DOC_NONCURRENT:
            return ("source_doc", doc, "REFERENCES_NONCURRENT_DOC",
                    f"source document is {state}; not an active candidate until reviewed")
        return ("source_doc", doc, "UNRESOLVED_SOURCE_DOC", "source document is not a current, unique standard")

    # -- source_pm_cycles: Set identity, meter, interval --------------------------
    cycle_rows = workbook.get(SHEET_CYCLES, ())
    set_ids = Counter(
        (_key(r.get("plan_code")), _key(r.get("model_variant")), _key(r.get("section")), _key(r.get("set_code")))
        for r in cycle_rows)
    accepted_sets: dict[tuple[str, str, str, str], CandidateSet] = {}
    counts = Counter()
    for index, row in enumerate(cycle_rows):
        label = _row_label(index)
        plan = _key(row.get("plan_code"))
        ident = (plan, _key(row.get("model_variant")), _key(row.get("section")), _key(row.get("set_code")))
        issues = _common_issues(SHEET_CYCLES, row)
        section, meter = ident[2], _key(row.get("meter_type"))
        unit_raw = _raw(row.get("interval_unit"))
        interval = _parse_interval(_raw(row.get("interval_value")))
        if section and section not in SECTIONS:
            issues.append(("section", section, "UNKNOWN_SECTION", "section is not CARRIER / CRANE / NOT_SEPARATED_IN_FORM"))
        elif section == SECTION_NOT_SEPARATED:
            issues.append(("section", section, "DRIVING_COMPONENT_ABSENT",
                           "the form does not separate carrier / crane; driving meter component must be reviewed"))
        if meter and meter not in METER_UNITS:
            issues.append(("meter_type", meter, "METER_NOT_EXPLICIT",
                           "meter must be ENGINE_HOUR / PTO_HOUR / ODOMETER; no calendar substitute"))
        elif meter and unit_raw.strip() and unit_raw.strip() != METER_UNITS[meter]:
            issues.append(("interval_unit", unit_raw, "UNIT_METER_MISMATCH",
                           f"{meter} requires unit '{METER_UNITS[meter]}'; not converted"))
        if _key(row.get("interval_value")) and interval is None:
            issues.append(("interval_value", _raw(row.get("interval_value")), "INVALID_INTERVAL",
                           "interval is not a positive number"))
        if set_ids[ident] > 1:
            issues.append(("set_code", ident[3], "DUPLICATE_SET_IDENTITY",
                           "same plan / variant / section / set appears more than once; not merged"))
        if (problem := doc_issue(row)) is not None:
            issues.append(problem)
        if issues:
            counts[REVIEW] += 1
            for col, raw, issue, reason in issues:
                out.add(SHEET_CYCLES, label, col, raw, issue, reason, REVIEW, plan_code=plan)
            continue
        counts[ACCEPT] += 1
        accepted_sets[ident] = CandidateSet(
            plan_code=plan, model_variant=ident[1], section=section, set_code=ident[3], meter_type=meter,
            interval_value=interval or 0.0, interval_unit=unit_raw.strip(), raw_interval=_raw(row.get("interval_value")),
            independent_group=_raw(row.get("independent_group")), source_doc=_key(row.get("source_doc")),
            source_row=label)
    if SHEET_CYCLES in workbook:
        accounts.append(SheetAccount(SHEET_CYCLES, len(cycle_rows), counts[ACCEPT], counts[REVIEW], counts[EXCLUDE]))

    # -- source_pm_items -------------------------------------------------------------
    item_rows = workbook.get(SHEET_ITEMS, ())
    item_ids = Counter(
        (_key(r.get("plan_code")), _key(r.get("model_variant")), _key(r.get("section")), _key(r.get("set_code")),
         _key(r.get("item_key"))) for r in item_rows)
    items: list[CandidateItem] = []
    counts = Counter()
    for index, row in enumerate(item_rows):
        label = _row_label(index)
        ident = (_key(row.get("plan_code")), _key(row.get("model_variant")), _key(row.get("section")),
                 _key(row.get("set_code")))
        issues = _common_issues(SHEET_ITEMS, row)
        sequence = _parse_sequence(_raw(row.get("sequence")))
        if _key(row.get("sequence")) and sequence is None:
            issues.append(("sequence", _raw(row.get("sequence")), "INVALID_SEQUENCE", "sequence is not a positive integer"))
        if all(ident) and ident not in accepted_sets:
            issues.append(("set_code", ident[3], "SET_NOT_ACCEPTED",
                           "the item's Set is missing or under review; item cannot be active on its own"))
        if _key(row.get("item_key")) and item_ids[(*ident, _key(row.get("item_key")))] > 1:
            issues.append(("item_key", _key(row.get("item_key")), "DUPLICATE_ITEM_KEY",
                           "item key appears more than once in the Set; not merged"))
        if (problem := doc_issue(row)) is not None:
            issues.append(problem)
        if issues:
            counts[REVIEW] += 1
            for col, raw, issue, reason in issues:
                out.add(SHEET_ITEMS, label, col, raw, issue, reason, REVIEW, plan_code=ident[0])
            continue
        counts[ACCEPT] += 1
        items.append(CandidateItem(
            plan_code=ident[0], model_variant=ident[1], section=ident[2], set_code=ident[3],
            item_key=_key(row.get("item_key")), sequence=sequence or 0, task_text=_raw(row.get("task_text")),
            method=_raw(row.get("method")), standard=_raw(row.get("standard")), source_doc=_key(row.get("source_doc")),
            source_row=label))
    if SHEET_ITEMS in workbook:
        accounts.append(SheetAccount(SHEET_ITEMS, len(item_rows), counts[ACCEPT], counts[REVIEW], counts[EXCLUDE]))

    # -- vehicle_pm_mapping: candidates only, never an assignment ------------------
    mapping_rows = workbook.get(SHEET_VEHICLE_MAPPING, ())
    vehicle_refs = Counter(_key(r.get("vehicle_ref")) for r in mapping_rows)
    mappings: list[MappingCandidate] = []
    counts = Counter()
    for index, row in enumerate(mapping_rows):
        label = _row_label(index)
        issues = _common_issues(SHEET_VEHICLE_MAPPING, row)
        ref = _key(row.get("vehicle_ref"))
        if ref and vehicle_refs[ref] > 1:
            issues.append(("vehicle_ref", ref, "DUPLICATE_VEHICLE_REF", "vehicle appears more than once; not merged"))
        if issues:
            counts[REVIEW] += 1
            for col, raw, issue, reason in issues:
                out.add(SHEET_VEHICLE_MAPPING, label, col, raw, issue, reason, REVIEW)
            continue
        counts[ACCEPT] += 1
        mappings.append(MappingCandidate(vehicle_ref=ref, plan_code=_key(row.get("plan_code")), source_row=label))
    if SHEET_VEHICLE_MAPPING in workbook:
        accounts.append(SheetAccount(SHEET_VEHICLE_MAPPING, len(mapping_rows), counts[ACCEPT], counts[REVIEW],
                                     counts[EXCLUDE]))

    # -- replacement_*: metadata reference only in B1 -------------------------------
    for sheet in (SHEET_REPLACEMENT_POLICY, SHEET_REPLACEMENT_ITEMS):
        rows = workbook.get(sheet, ())
        for index, _row in enumerate(rows):
            out.add(sheet, _row_label(index), "", "", "REFERENCE_ONLY_IN_B1",
                    "replacement metadata: no threshold, part history or advisory is activated in B1", EXCLUDE)
        if sheet in workbook:
            accounts.append(SheetAccount(sheet, len(rows), 0, 0, len(rows)))

    ledger = tuple(sorted(out.ledger, key=lambda e: (e.sheet, _row_sort(e.row_or_key), e.column, e.issue)))
    result = PreviewResult(
        source_file=source_file,
        accounts=tuple(sorted(accounts, key=lambda a: a.sheet)),
        ledger=ledger,
        sets=tuple(sorted(accepted_sets.values(), key=lambda s: (s.plan_code, s.model_variant, s.section, s.set_code))),
        items=tuple(sorted(items, key=lambda i: (i.plan_code, i.model_variant, i.section, i.set_code, i.sequence,
                                                 i.item_key))),
        mapping_candidates=tuple(sorted(mappings, key=lambda m: m.vehicle_ref)),
    )
    return PreviewResult(**{**result.__dict__, "digest": preview_digest(result)})


def _row_sort(label: str) -> tuple[int, str]:
    number = label.removeprefix("row:")
    return (int(number), "") if number.isdigit() else (0, label)


def preview_digest(result: PreviewResult) -> str:
    """SHA-256 of the canonical JSON of everything but the digest itself."""
    body = {
        "source_file": result.source_file,
        "accounts": [asdict(a) for a in result.accounts],
        "ledger": [asdict(e) for e in result.ledger],
        "sets": [asdict(s) for s in result.sets],
        "items": [asdict(i) for i in result.items],
        "mapping_candidates": [asdict(m) for m in result.mapping_candidates],
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


__all__ = [
    "ACCEPT", "REVIEW", "EXCLUDE", "KNOWN_SHEETS", "REQUIRED_COLUMNS", "LedgerEntry", "SheetAccount",
    "CandidateSet", "CandidateItem", "MappingCandidate", "PreviewResult", "preview_source", "preview_digest",
]
