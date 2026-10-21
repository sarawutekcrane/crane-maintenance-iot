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

TWO INPUT SHAPES, NEVER CONFLATED (R4-B1 correction RV-B1-01):
- `preview_maintenance_source` (schema `MAINTENANCE_SOURCE_V1`) reads the
  SOURCE-SHAPED tabs of `MAINTENANCE.xlsx` by their independently reviewed real
  header names (`SOURCE_COLUMNS`). It is the only preview the PM Master may be
  published from (`app.domain.pm_master`). The reviewed headers are partial
  examples: the FULL REAL HEADER INVENTORY IS UNVERIFIED (workbook not available
  here); a missing column makes the row REVIEW, never a guess.
- `preview_source` (schema `NORMALIZED_SYNTHETIC_V1`) is the original B1
  internal normalized contract (`REQUIRED_COLUMNS`, e.g. `plan_code`,
  `item_key`). Those columns do NOT exist in the real source; it is kept for its
  synthetic contract tests only and can never be registered for publish.

Ledger entries have a deterministic `entry_id` so a review resolution can be
bound to exactly one entry of exactly one preview digest.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace

from app.domain.request_replay import canonical_json

SCHEMA_NORMALIZED = "NORMALIZED_SYNTHETIC_V1"
SCHEMA_MAINTENANCE = "MAINTENANCE_SOURCE_V1"

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
    plan_scope: tuple[str, ...] = ()
    """MAINTENANCE schema: every Plan whose publish this finding blocks (a cycle's
    own Plan; for an Item, the Plans of the Sets it is linked to). Not part of
    `entry_id`."""

    @property
    def unresolved(self) -> bool:
        return self.action == REVIEW and not self.reviewer

    @property
    def entry_id(self) -> str:
        """Deterministic identity of this exact finding (sheet, row, column, issue
        and raw value); a review resolution binds to it."""
        key = canonical_json([self.source_file, self.sheet, self.row_or_key, self.column, self.issue,
                              self.raw_reference])
        return "PMLE-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


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
    driving_component: str = ""
    raw: tuple[tuple[str, str], ...] = ()
    blocking_entry_ids: tuple[str, ...] = ()
    topology: str = ""
    meter_basis: str = ""
    """MAINTENANCE schema: how meter/component were established (an Owner rule
    with its configuration, the KM unit, or REVIEW)."""

    @property
    def set_identity(self) -> str:
        return f"{self.plan_code}|{self.model_variant}|{self.section}|{self.set_code}"


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
    raw: tuple[tuple[str, str], ...] = ()
    blocking_entry_ids: tuple[str, ...] = ()
    linked_set_identities: tuple[str, ...] = ()
    """MAINTENANCE schema: the exact Sets (plan|model|section|group) whose mapped
    document, section and task group this Item matches. Never inferred wider."""


@dataclass(frozen=True)
class MappingCandidate:
    """A source vehicle -> Plan candidate. NEVER an assignment: `plan_code` empty
    means the source names no Plan (valid; may stay unassigned permanently)."""

    vehicle_ref: str
    plan_code: str
    source_row: str
    status: str = ""
    plan_model: str = ""
    component_configuration: str = ""
    topology: str = ""
    """SINGLE / DUAL / UNKNOWN from `component_configuration` (Owner rule); a
    source category, never an installed component or device."""


@dataclass(frozen=True)
class PreviewResult:
    source_file: str
    accounts: tuple[SheetAccount, ...]
    ledger: tuple[LedgerEntry, ...]
    sets: tuple[CandidateSet, ...]
    items: tuple[CandidateItem, ...]
    mapping_candidates: tuple[MappingCandidate, ...]
    digest: str = field(default="")
    schema: str = SCHEMA_NORMALIZED
    pending_sets: tuple[CandidateSet, ...] = ()
    pending_items: tuple[CandidateItem, ...] = ()
    """MAINTENANCE schema only: well-formed rows held back solely by RESOLVABLE
    REVIEW entries (`blocking_entry_ids`); never active without a resolution."""
    source_profile: tuple[tuple[str, int], ...] = ()
    """MAINTENANCE schema: raw category counts of the input (for reconciliation)."""
    approved_aliases: tuple[tuple[str, str, str, str], ...] = ()
    """MAINTENANCE schema: (kind, source label, mapping label, evidence) aliases the
    caller supplied as approved; part of the digest."""

    def account(self, sheet: str) -> SheetAccount | None:
        return next((a for a in self.accounts if a.sheet == sheet), None)

    def unresolved_reviews(self, plan_code: str | None = None) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self.ledger
                     if e.unresolved and (plan_code is None or e.plan_code in ("", plan_code)
                                          or plan_code in e.plan_scope or GLOBAL_PLAN_SCOPE in e.plan_scope))


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
            plan_code: str = "", plan_scope: tuple[str, ...] = ()) -> None:
        self.ledger.append(LedgerEntry(self.source_file, sheet, row, column, raw, issue, reason, action,
                                       evidence=f"{self.source_file}!{sheet}!{row}", plan_code=plan_code,
                                       plan_scope=plan_scope))


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
        "schema": result.schema,
        "source_file": result.source_file,
        "accounts": [asdict(a) for a in result.accounts],
        "ledger": [asdict(e) for e in result.ledger],
        "sets": [asdict(s) for s in result.sets],
        "items": [asdict(i) for i in result.items],
        "mapping_candidates": [asdict(m) for m in result.mapping_candidates],
        "pending_sets": [asdict(s) for s in result.pending_sets],
        "pending_items": [asdict(i) for i in result.pending_items],
        "source_profile": [list(x) for x in result.source_profile],
        "approved_aliases": [list(x) for x in result.approved_aliases],
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Source-shaped adapter: MAINTENANCE.xlsx tabs by their real headers
# (RV-B1-01; source join and classification RV-B1-R2-01..04)
#
# NAMESPACES ARE NEVER EQUATED. `source_sheet` is provenance only:
# - in `source_pm_cycles` it names a planning tab (e.g. "PM Plan1");
# - in `source_pm_items` and `source_pm_standard` it names an inspection
#   standard document (e.g. "TR-100M-1(05.1 Rev.00) ").
# The ONLY bridge is `vehicle_pm_mapping` evidence: a Set (planning tab,
# model, section, task group) is linked to a document through matched mapping
# rows with the same `source_plan` and `plan_model` (exact text, or an approved
# alias with evidence), taking the document from `carrier_or_main_source_sheet`
# (CARRIER, NOT_SEPARATED_IN_PLAN) or `crane_source_sheet` (CRANE). An Item
# belongs to a Set only when its own document, section and task group match that
# Set's linked document exactly. Anything else is REVIEW, never a guess.
# ---------------------------------------------------------------------------

# Independently reviewed header examples (partial; FULL INVENTORY UNVERIFIED).
SOURCE_COLUMNS: dict[str, tuple[str, ...]] = {
    SHEET_CYCLES: ("source_sheet", "model_label_corrected", "component_section", "task_group", "interval_value",
                   "interval_unit", "group_rule", "next_due_rule"),
    SHEET_ITEMS: ("source_sheet", "source_row", "task_group", "component_section", "sequence_raw", "description_raw",
                  "method_raw", "standard_raw", "frequency_approved", "interval_value", "interval_unit",
                  "check_cell_raw", "clean_cell_raw", "change_fill_cell_raw"),
    SHEET_STANDARD: ("source_sheet", "source_status"),
    SHEET_VEHICLE_MAPPING: ("vehicle_id", "source_plan", "plan_model", "component_configuration",
                            "carrier_or_main_source_sheet", "crane_source_sheet", "mapping_status"),
    SHEET_REPLACEMENT_POLICY: (),
    SHEET_REPLACEMENT_ITEMS: (),
}
SOURCE_REQUIRED: dict[str, tuple[str, ...]] = {
    SHEET_CYCLES: ("source_sheet", "model_label_corrected", "component_section", "task_group", "interval_value",
                   "interval_unit"),
    SHEET_ITEMS: ("source_sheet", "source_row", "task_group", "component_section", "sequence_raw", "description_raw"),
    SHEET_STANDARD: ("source_sheet", "source_status"),
    SHEET_VEHICLE_MAPPING: ("vehicle_id", "mapping_status", "component_configuration"),
}
SOURCE_NUMERIC = frozenset({"interval_value", "sequence_raw", "source_row"})
# RV-B1-R2-04: the columns whose MEANING the preview uses. A raw 35 there is
# ambiguous (REVIEW); anywhere else it is preserved raw with a non-blocking ledger
# note and never interpreted (form action cells, URLs, free metadata).
SEMANTIC_COLUMNS: dict[str, frozenset[str]] = {
    SHEET_CYCLES: frozenset({"source_sheet", "model_label_corrected", "component_section", "task_group",
                             "interval_unit", "group_rule"}),
    SHEET_ITEMS: frozenset({"source_sheet", "task_group", "component_section", "description_raw", "method_raw",
                            "standard_raw"}),
    SHEET_STANDARD: frozenset({"source_sheet", "source_status"}),
    SHEET_VEHICLE_MAPPING: frozenset({"vehicle_id", "source_plan", "plan_model", "component_configuration",
                                      "carrier_or_main_source_sheet", "crane_source_sheet", "mapping_status"}),
}
# Raw form cells that LOOK like actions; preserved raw, never mapped to an outcome.
RAW_ACTION_CELLS = ("check_cell_raw", "clean_cell_raw", "change_fill_cell_raw")
UNIT_HOUR = "HOUR"
UNIT_KM = "KM"
STANDARD_ACTIVE = "SOURCE_STANDARD"
STANDARD_NONCURRENT = frozenset({"EMPTY_TEMPLATE", "CANCELLED"})
MAPPING_MATCHED = "MATCHED_PENDING_IMPLEMENTATION"
MAPPING_NO_PLAN = "PENDING_PM_PLAN"

# RV-B1-R2-02: planning sections and inspection-form sections are different label
# sets; only these pairs name the same scope (raw labels are kept verbatim).
CYCLE_NOT_SEPARATED = "NOT_SEPARATED_IN_PLAN"
ITEM_NOT_SEPARATED = SECTION_NOT_SEPARATED  # "NOT_SEPARATED_IN_FORM"
CYCLE_SECTIONS = frozenset({SECTION_CARRIER, SECTION_CRANE, CYCLE_NOT_SEPARATED})
ITEM_SECTIONS = frozenset({SECTION_CARRIER, SECTION_CRANE, ITEM_NOT_SEPARATED})
ITEM_SECTION_FOR: dict[str, str] = {SECTION_CARRIER: SECTION_CARRIER, SECTION_CRANE: SECTION_CRANE,
                                    CYCLE_NOT_SEPARATED: ITEM_NOT_SEPARATED}
DOCUMENT_COLUMN: dict[str, str] = {SECTION_CARRIER: "carrier_or_main_source_sheet",
                                   SECTION_CRANE: "crane_source_sheet",
                                   CYCLE_NOT_SEPARATED: "carrier_or_main_source_sheet"}
CONFIG_DUAL = "CARRIER_AND_CRANE"
CONFIG_SINGLE = "NOT_SEPARATED_IN_PLAN"
CONFIG_UNKNOWN = "UNKNOWN"
TOPOLOGY: dict[str, str] = {CONFIG_DUAL: "DUAL", CONFIG_SINGLE: "SINGLE", CONFIG_UNKNOWN: "UNKNOWN"}
CONFIG_SECTIONS: dict[str, frozenset[str]] = {CONFIG_DUAL: frozenset({SECTION_CARRIER, SECTION_CRANE}),
                                              CONFIG_SINGLE: frozenset({CYCLE_NOT_SEPARATED})}
# Owner rule (IoT addendum 2026-10-21, A1-A3 / H1): CARRIER = lower engine, CRANE =
# upper engine, independent ENGINE_HOUR counters; NOT_SEPARATED_IN_PLAN = one
# engine (modelled as CARRIER_ENGINE; PTO is not a second engine). Applied only
# when the mapping configuration agrees; otherwise HOUR stays REVIEW.
OWNER_HOUR_RULE: dict[tuple[str, str], tuple[str, str, str]] = {
    (SECTION_CARRIER, CONFIG_DUAL): ("ENGINE_HOUR", "CARRIER_ENGINE", "OWNER_RULE_DUAL_CARRIER_ENGINE"),
    (SECTION_CRANE, CONFIG_DUAL): ("ENGINE_HOUR", "CRANE_ENGINE", "OWNER_RULE_DUAL_CRANE_ENGINE"),
    (CYCLE_NOT_SEPARATED, CONFIG_SINGLE): ("ENGINE_HOUR", "CARRIER_ENGINE", "OWNER_RULE_SINGLE_ENGINE"),
}
# Kilometres are only measured by the one vehicle-level odometer (never per engine).
KM_METER, KM_COMPONENT, KM_BASIS = "ODOMETER", "VEHICLE", "UNIT_KM_VEHICLE_ODOMETER"
ALIAS_PLAN = "PLAN"
ALIAS_MODEL = "MODEL"
MIN_ALIAS_EVIDENCE = 12

# RV-B1-R3-01: a REVIEW finding whose affected Plans cannot be proven from verified
# mapping evidence blocks EVERY Plan's publish until it is explicitly resolved
# (registration-level unresolved-source gate). Not a valid source label.
GLOBAL_PLAN_SCOPE = "*ALL_PLANS*"

ISSUE_METER_UNRESOLVED = "METER_COMPONENT_UNRESOLVED"
ISSUE_RAW_35 = "AMBIGUOUS_RAW_35"
NOTE_RAW_35 = "RAW_35_PRESERVED_UNINTERPRETED"
OUTCOME_EXCLUDE_ROW = "EXCLUDE_ROW"
OUTCOME_RESOLVE_METER = "RESOLVE_METER"
# RV-B1-R3-02: no finding may be resolved by retaining a raw value. A raw 35 in a
# semantic column would be projected into an active Master field (Set identity,
# group rule, task text, method, standard), so its only resolution is EXCLUDE_ROW;
# a corrected value must arrive in a new registered source preview. The outcome
# name is kept so a caller that sends it is refused explicitly (OUTCOME_NOT_ALLOWED).
OUTCOME_RETAIN_RAW = "RETAIN_RAW_UNINTERPRETED"
_RESOLVABLE: dict[str, tuple[str, ...]] = {
    ISSUE_METER_UNRESOLVED: (OUTCOME_RESOLVE_METER, OUTCOME_EXCLUDE_ROW),
}

# Reference audit expectations for the real workbook (Owner package + independent
# review, 2026-10-21). Reported by `reconcile_reference`; never used to accept data.
REFERENCE_COUNTS: tuple[tuple[str, int], ...] = (
    ("source_pm_cycles.rows", 260),
    ("source_pm_cycles.component_section.NOT_SEPARATED_IN_PLAN", 80),
    ("source_pm_cycles.component_section.CARRIER", 107),
    ("source_pm_cycles.component_section.CRANE", 73),
    ("source_pm_cycles.interval_unit.HOUR", 231),
    ("source_pm_cycles.interval_unit.KM", 29),
    ("source_pm_items.rows", 1146),
    ("source_pm_items.component_section.NOT_SEPARATED_IN_FORM", 482),
    ("source_pm_items.component_section.CARRIER", 374),
    ("source_pm_items.component_section.CRANE", 290),
    ("source_pm_items.distinct_source_sheet", 44),
    ("source_pm_standard.rows", 49),
    ("source_pm_standard.source_status.SOURCE_STANDARD", 44),
    ("source_pm_standard.source_status.EMPTY_TEMPLATE", 4),
    ("source_pm_standard.source_status.CANCELLED", 1),
    ("vehicle_pm_mapping.rows", 235),
    ("vehicle_pm_mapping.mapping_status.MATCHED_PENDING_IMPLEMENTATION", 183),
    ("vehicle_pm_mapping.mapping_status.PENDING_PM_PLAN", 52),
    ("vehicle_pm_mapping.component_configuration.CARRIER_AND_CRANE", 53),
    ("vehicle_pm_mapping.component_configuration.NOT_SEPARATED_IN_PLAN", 130),
    ("vehicle_pm_mapping.component_configuration.UNKNOWN", 52),
    ("replacement_policy.rows", 13),
    ("replacement_items.rows", 38),
)


def allowed_outcomes(issue: str) -> tuple[str, ...]:
    """Every REVIEW issue except an unresolved HOUR meter can only be resolved by
    excluding the row: the source must be corrected, never patched or retained."""
    return _RESOLVABLE.get(issue, (OUTCOME_EXCLUDE_ROW,))


def _raw_cells(row: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple((col, _raw(row.get(col))) for col in sorted(row))


def _source_issues(sheet: str, row: Mapping[str, object]):
    """(hard, soft, notes). Soft = a raw 35 in a column whose meaning is used;
    notes = a raw 35 anywhere else, preserved and never interpreted."""
    hard = [(col, "", "MISSING_REQUIRED_VALUE", f"required source column '{col}' is absent or blank")
            for col in SOURCE_REQUIRED.get(sheet, ()) if not _key(row.get(col))]
    soft, notes = [], []
    semantic = SEMANTIC_COLUMNS.get(sheet, frozenset())
    for col in sorted(row):
        if col in SOURCE_NUMERIC or _key(row.get(col)) != AMBIGUOUS_RAW:
            continue
        if col in semantic:
            soft.append((col, _raw(row.get(col)), ISSUE_RAW_35,
                         "raw 35 in a column whose meaning is used; not a Plan, model, document, action or value"))
        else:
            notes.append((col, _raw(row.get(col)), NOTE_RAW_35,
                          "raw 35 preserved verbatim; never read as performed work, part, quantity, meter or id"))
    return hard, soft, notes


def _document_scope(document: str, document_plans: Mapping[str, set[str]], *,
                    unselected_ok: bool) -> tuple[str, ...]:
    """RV-B1-R3-01: the conservative affected Plans of a finding on `document`: the
    Plans whose verified mapping rows reference it. A document no mapping selects
    blocks nothing only when it is a known non-current (or, for a standard row,
    unselected) document; otherwise its scope cannot be proven and the global
    unresolved-source gate applies."""
    plans = document_plans.get(document)
    if plans:
        return tuple(sorted(plans))
    if document and unselected_ok:
        return ()
    return (GLOBAL_PLAN_SCOPE,)


def _aliases(approved: Sequence[Sequence[str]]) -> dict[tuple[str, str], tuple[str, str]]:
    """Validate caller-approved aliases (kind, source label, mapping label,
    evidence) -> {(kind, source label): (mapping label, evidence)}. Raises
    ValueError on anything incomplete or conflicting."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for entry in approved:
        kind, source_label, mapping_label, evidence = (str(x).strip() for x in entry)
        if kind not in (ALIAS_PLAN, ALIAS_MODEL) or not source_label or not mapping_label:
            raise ValueError("an alias needs kind PLAN or MODEL, a source label and a mapping label")
        if len(evidence) < MIN_ALIAS_EVIDENCE:
            raise ValueError("an alias needs substantive evidence")
        if out.get((kind, source_label), (mapping_label,))[0] != mapping_label:
            raise ValueError(f"conflicting aliases for {kind} '{source_label}'")
        out[(kind, source_label)] = (mapping_label, evidence)
    return out


def source_profile(workbook: Mapping[str, Sequence[Mapping[str, object]]]) -> tuple[tuple[str, int], ...]:
    """Raw category counts of the input tabs (no interpretation)."""
    counts: Counter[str] = Counter()
    categories = {SHEET_CYCLES: ("component_section", "interval_unit", "source_sheet"),
                  SHEET_ITEMS: ("component_section",), SHEET_STANDARD: ("source_status",),
                  SHEET_VEHICLE_MAPPING: ("mapping_status", "component_configuration")}
    for sheet in KNOWN_SHEETS:
        if sheet not in workbook:
            continue
        rows = workbook[sheet]
        counts[f"{sheet}.rows"] = len(rows)
        for col in categories.get(sheet, ()):
            for row in rows:
                counts[f"{sheet}.{col}.{_key(row.get(col))}"] += 1
    if SHEET_ITEMS in workbook:
        counts[f"{SHEET_ITEMS}.distinct_source_sheet"] = len({_key(r.get("source_sheet")) for r in workbook[SHEET_ITEMS]})
    return tuple(sorted(counts.items()))


def reconcile_reference(preview: PreviewResult) -> tuple[tuple[str, int, int, str], ...]:
    """(metric, expected, observed, MATCH|MISMATCH) against REFERENCE_COUNTS.
    A synthetic or partial input is expected to MISMATCH; only a run over the real
    workbook can turn the reconciliation into evidence."""
    observed = dict(preview.source_profile)
    return tuple((metric, expected, observed.get(metric, 0),
                  "MATCH" if observed.get(metric, 0) == expected else "MISMATCH")
                 for metric, expected in REFERENCE_COUNTS)


def preview_maintenance_source(workbook: Mapping[str, Sequence[Mapping[str, object]]], *, source_file: str,
                               approved_aliases: Sequence[Sequence[str]] = ()) -> PreviewResult:
    """Read-only preview of the source-shaped MAINTENANCE tabs. Pure: no I/O, no
    write, the input is never mutated. See the namespace rule above."""
    aliases = _aliases(approved_aliases)
    out = _Collector(source_file)
    accounts: list[SheetAccount] = []
    for sheet in sorted(workbook):
        if sheet not in KNOWN_SHEETS:
            out.add(sheet, "sheet", "", f"rows={len(workbook[sheet])}", "SHEET_OUT_OF_B1_SCOPE",
                    "tab is not a B1 PM Master source; not read further", EXCLUDE)

    def ref(sheet: str, index: int) -> str:
        return f"{sheet}!row:{index + FIRST_DATA_ROW}"

    def record(sheet: str, label: str, scope: Sequence[str], issues, action: str = REVIEW) -> tuple[str, ...]:
        ids = []
        for col, raw, issue, reason in issues:
            out.add(sheet, label, col, raw, issue, reason, action,
                    plan_code=scope[0] if len(scope) == 1 else "", plan_scope=tuple(scope))
            ids.append(out.ledger[-1].entry_id)
        return tuple(ids)

    def note(sheet: str, label: str, notes) -> None:
        for col, raw, issue, reason in notes:
            out.add(sheet, label, col, raw, issue, reason, ACCEPT)

    # -- vehicle_pm_mapping: candidates + the ONLY Plan/model -> document evidence ----
    rows = workbook.get(SHEET_VEHICLE_MAPPING, ())
    vehicles = Counter(_key(r.get("vehicle_id")) for r in rows)
    mappings: list[MappingCandidate] = []
    evidence: dict[tuple[str, str], list[dict[str, str]]] = {}
    # RV-B1-R3-01: every Plan whose verified (accepted, matched) mapping rows
    # reference a document — the conservative scope of that document's findings.
    document_plans: dict[str, set[str]] = {}
    counts = Counter()
    for index, row in enumerate(rows):
        label, vehicle = ref(SHEET_VEHICLE_MAPPING, index), _key(row.get("vehicle_id"))
        status_, config = _key(row.get("mapping_status")), _key(row.get("component_configuration"))
        hard, soft, notes = _source_issues(SHEET_VEHICLE_MAPPING, row)
        note(SHEET_VEHICLE_MAPPING, label, notes)
        if vehicle and vehicles[vehicle] > 1:
            hard.append(("vehicle_id", vehicle, "DUPLICATE_VEHICLE_ID", "vehicle appears more than once; not merged"))
        if status_ and status_ not in (MAPPING_MATCHED, MAPPING_NO_PLAN):
            hard.append(("mapping_status", status_, "UNKNOWN_MAPPING_STATUS",
                         "status is not MATCHED_PENDING_IMPLEMENTATION / PENDING_PM_PLAN"))
        if config and config not in TOPOLOGY:
            hard.append(("component_configuration", config, "UNKNOWN_COMPONENT_CONFIGURATION",
                         "configuration is not CARRIER_AND_CRANE / NOT_SEPARATED_IN_PLAN / UNKNOWN"))
        if status_ == MAPPING_MATCHED:
            for col in ("source_plan", "plan_model"):
                if not _key(row.get(col)):
                    hard.append((col, "", "MATCHED_WITHOUT_EVIDENCE", f"a matched row must name its {col}"))
            needed = {CONFIG_DUAL: ("carrier_or_main_source_sheet", "crane_source_sheet"),
                      CONFIG_SINGLE: ("carrier_or_main_source_sheet",)}.get(config, ())
            for col in needed:
                if not _key(row.get(col)):
                    hard.append((col, "", "MAPPING_DOCUMENT_MISSING", f"{config} requires {col}"))
        if hard or soft:
            counts[REVIEW] += 1
            named_plan = _key(row.get("source_plan"))
            if named_plan and named_plan != AMBIGUOUS_RAW:
                scope: tuple[str, ...] = (named_plan,)       # the Plan this row names
            elif status_ == MAPPING_NO_PLAN:
                scope = ()                                   # names no Plan and claims none
            else:
                scope = (GLOBAL_PLAN_SCOPE,)                 # might be any Plan's evidence
            record(SHEET_VEHICLE_MAPPING, label, scope, hard + soft)
            continue
        counts[ACCEPT] += 1
        plan = _key(row.get("source_plan")) if status_ == MAPPING_MATCHED else ""
        mappings.append(MappingCandidate(vehicle_ref=vehicle, plan_code=plan, source_row=label, status=status_,
                                         plan_model=_key(row.get("plan_model")), component_configuration=config,
                                         topology=TOPOLOGY[config]))
        if status_ == MAPPING_MATCHED:
            evidence.setdefault((plan, _key(row.get("plan_model"))), []).append(
                {"config": config, "row": label,
                 **{col: _key(row.get(col)) for col in ("carrier_or_main_source_sheet", "crane_source_sheet")}})
            for col in ("carrier_or_main_source_sheet", "crane_source_sheet"):
                if _key(row.get(col)):
                    document_plans.setdefault(_key(row.get(col)), set()).add(plan)
    if SHEET_VEHICLE_MAPPING in workbook:
        accounts.append(SheetAccount(SHEET_VEHICLE_MAPPING, len(rows), counts[ACCEPT], counts[REVIEW],
                                     counts[EXCLUDE]))

    # -- source_pm_standard: document lifecycle, independent of incidental raw 35 ----
    rows = workbook.get(SHEET_STANDARD, ())
    names = Counter(_key(r.get("source_sheet")) for r in rows)
    doc_state: dict[str, str] = {}
    counts = Counter()
    for index, row in enumerate(rows):
        label, name = ref(SHEET_STANDARD, index), _key(row.get("source_sheet"))
        status_ = _key(row.get("source_status"))
        hard, soft, notes = _source_issues(SHEET_STANDARD, row)
        note(SHEET_STANDARD, label, notes)
        if name and names[name] > 1:
            hard.append(("source_sheet", name, "DUPLICATE_SOURCE_SHEET", "document listed more than once; not merged"))
        if not hard and not soft and status_ not in STANDARD_NONCURRENT and status_ != STANDARD_ACTIVE:
            hard.append(("source_status", status_, "UNKNOWN_SOURCE_STATUS",
                         "status is not SOURCE_STANDARD / EMPTY_TEMPLATE / CANCELLED"))
        if hard or soft:
            counts[REVIEW] += 1
            record(SHEET_STANDARD, label, _document_scope(name, document_plans, unselected_ok=True), hard + soft)
            if name:
                doc_state[name] = REVIEW
        elif status_ in STANDARD_NONCURRENT:
            counts[EXCLUDE] += 1
            doc_state[name] = status_
            record(SHEET_STANDARD, label, (), [("source_status", status_, f"SOURCE_{status_}",
                                                "non-current document excluded from the active candidate")], EXCLUDE)
        else:
            counts[ACCEPT] += 1
            doc_state[name] = STANDARD_ACTIVE
    if SHEET_STANDARD in workbook:
        accounts.append(SheetAccount(SHEET_STANDARD, len(rows), counts[ACCEPT], counts[REVIEW], counts[EXCLUDE]))

    def document_problem(doc: str, what: str) -> tuple[str, str] | None:
        state = doc_state.get(doc)
        if state == STANDARD_ACTIVE:
            return None
        if state is None:
            return ("DOCUMENT_NOT_IN_STANDARDS", f"{what} '{doc}' is not listed in source_pm_standard")
        if state == REVIEW:
            return ("DOCUMENT_UNDER_REVIEW", f"{what} '{doc}' has an unresolved standard row")
        return ("DOCUMENT_NOT_CURRENT", f"{what} '{doc}' is {state}")

    # -- source_pm_cycles: Sets, linked to a document only through mapping evidence ----
    rows = workbook.get(SHEET_CYCLES, ())

    def set_ident(r: Mapping[str, object]) -> tuple[str, str, str, str]:
        sheet_, model_ = _key(r.get("source_sheet")), _key(r.get("model_label_corrected"))
        return (aliases.get((ALIAS_PLAN, sheet_), (sheet_,))[0], aliases.get((ALIAS_MODEL, model_), (model_,))[0],
                _key(r.get("component_section")), _key(r.get("task_group")))

    idents = Counter(set_ident(r) for r in rows)
    accepted_sets: list[CandidateSet] = []
    pending_sets: list[CandidateSet] = []
    by_document: dict[tuple[str, str, str], list[str]] = {}
    counts = Counter()
    for index, row in enumerate(rows):
        label, ident = ref(SHEET_CYCLES, index), set_ident(row)
        plan, model, section, group = ident
        unit = _key(row.get("interval_unit"))
        hard, soft, notes = _source_issues(SHEET_CYCLES, row)
        note(SHEET_CYCLES, label, notes)
        interval = _parse_interval(_raw(row.get("interval_value")))
        if section and section not in CYCLE_SECTIONS:
            hard.append(("component_section", section, "UNKNOWN_SECTION",
                         "planning section is not CARRIER / CRANE / NOT_SEPARATED_IN_PLAN"))
        if _key(row.get("interval_value")) and interval is None:
            hard.append(("interval_value", _raw(row.get("interval_value")), "INVALID_INTERVAL",
                         "interval is not a positive number"))
        if all(ident) and idents[ident] > 1:
            hard.append(("task_group", group, "DUPLICATE_SET_IDENTITY",
                         "same plan / model / section / task group appears more than once; not merged"))
        config, document = "", ""
        if all(ident) and section in CYCLE_SECTIONS:
            rows_ev = evidence.get((plan, model), [])
            configs = {e["config"] for e in rows_ev}
            docs = {e[DOCUMENT_COLUMN[section]] for e in rows_ev}
            if not rows_ev:
                hard.append(("model_label_corrected", model, "SET_NOT_MAPPED",
                             "no matched vehicle_pm_mapping row has this source_plan and plan_model"))
            elif len(configs) > 1:
                hard.append(("model_label_corrected", model, "MAPPING_CONFIGURATION_CONFLICT",
                             f"matched mapping rows disagree on configuration: {sorted(configs)}"))
            else:
                config = next(iter(configs))
                if config in CONFIG_SECTIONS and section not in CONFIG_SECTIONS[config]:
                    hard.append(("component_section", section, "SECTION_CONFIGURATION_CONFLICT",
                                 f"a {config} mapping does not plan a {section} section"))
                elif len(docs) != 1 or not next(iter(docs)):
                    hard.append(("component_section", section, "SET_DOCUMENT_AMBIGUOUS",
                                 f"mapping rows name {len(docs - {''})} document(s) for this section"))
                else:
                    document = next(iter(docs))
                    if (problem := document_problem(document, "mapped document")) is not None:
                        hard.append((DOCUMENT_COLUMN[section], document, *problem))
        meter = component = basis = ""
        if unit == UNIT_KM:
            if section == SECTION_CRANE:
                hard.append(("interval_unit", unit, "UNIT_SECTION_CONFLICT", "a CRANE section cannot run on kilometres"))
            meter, component, basis = KM_METER, KM_COMPONENT, KM_BASIS
        elif unit == UNIT_HOUR:
            rule = OWNER_HOUR_RULE.get((section, config))
            if rule is not None:
                meter, component, basis = rule
            elif not hard:  # an already exclusion-only row gets no extra meter finding
                soft.append(("interval_unit", unit, ISSUE_METER_UNRESOLVED,
                             "the mapping configuration does not establish which engine this HOUR Set runs on"))
        elif unit:
            hard.append(("interval_unit", unit, "UNKNOWN_UNIT", "unit is not HOUR / KM; no calendar substitute"))
        ids = record(SHEET_CYCLES, label, (plan,) if plan else (GLOBAL_PLAN_SCOPE,), hard + soft)
        counts[REVIEW if hard or soft else ACCEPT] += 1
        if hard:
            continue
        candidate = CandidateSet(
            plan_code=plan, model_variant=model, section=section, set_code=group, meter_type=meter,
            interval_value=interval or 0.0, interval_unit=unit, raw_interval=_raw(row.get("interval_value")),
            independent_group=_raw(row.get("group_rule")), source_doc=document, source_row=label,
            driving_component=component, raw=_raw_cells(row), blocking_entry_ids=ids,
            topology=TOPOLOGY.get(config, ""), meter_basis=basis or "REVIEW")
        (pending_sets if ids else accepted_sets).append(candidate)
        by_document.setdefault((document, ITEM_SECTION_FOR[section], group), []).append(candidate.set_identity)
    if SHEET_CYCLES in workbook:
        accounts.append(SheetAccount(SHEET_CYCLES, len(rows), counts[ACCEPT], counts[REVIEW], counts[EXCLUDE]))

    # -- source_pm_items: tasks of ONE document, linked only to Sets mapped to it -------
    rows = workbook.get(SHEET_ITEMS, ())
    pointers = Counter((_key(r.get("source_sheet")), _key(r.get("source_row"))) for r in rows)
    accepted_items: list[CandidateItem] = []
    pending_items: list[CandidateItem] = []
    counts = Counter()
    for index, row in enumerate(rows):
        label = ref(SHEET_ITEMS, index)
        document, section, group = (_key(row.get("source_sheet")), _key(row.get("component_section")),
                                    _key(row.get("task_group")))
        pointer = f"{document}!{_key(row.get('source_row'))}"
        hard, soft, notes = _source_issues(SHEET_ITEMS, row)
        note(SHEET_ITEMS, label, notes)
        sequence = _parse_sequence(_raw(row.get("sequence_raw")))
        if _key(row.get("sequence_raw")) and sequence is None:
            hard.append(("sequence_raw", _raw(row.get("sequence_raw")), "INVALID_SEQUENCE",
                         "sequence is not a positive integer"))
        if section and section not in ITEM_SECTIONS:
            hard.append(("component_section", section, "UNKNOWN_SECTION",
                         "form section is not CARRIER / CRANE / NOT_SEPARATED_IN_FORM"))
        if document and _key(row.get("source_row")) and pointers[(document, _key(row.get("source_row")))] > 1:
            hard.append(("source_row", pointer, "DUPLICATE_SOURCE_POINTER", "source pointer appears more than once"))
        if document and (problem := document_problem(document, "item document")) is not None:
            hard.append(("source_sheet", document, *problem))
        linked = tuple(sorted(set(by_document.get((document, section, group), ()))))
        if document and section and group and not linked:
            hard.append(("task_group", group, "ITEM_NOT_LINKED",
                         "no mapped Set references this document, section and task group"))
        # RV-B1-R3-01: the Plans of the Sets it links to PLUS every Plan whose mapping
        # references its document, so a mistyped group/section still blocks them.
        scope = tuple(sorted({identity.split("|", 1)[0] for identity in linked} |
                             set(_document_scope(document, document_plans,
                                                 unselected_ok=doc_state.get(document) in STANDARD_NONCURRENT))))
        ids = record(SHEET_ITEMS, label, scope, hard + soft)
        counts[REVIEW if hard or soft else ACCEPT] += 1
        if hard:
            continue
        candidate = CandidateItem(
            plan_code="", model_variant="", section=section, set_code=group, item_key=pointer,
            sequence=sequence or 0, task_text=_raw(row.get("description_raw")), method=_raw(row.get("method_raw")),
            standard=_raw(row.get("standard_raw")), source_doc=document, source_row=label, raw=_raw_cells(row),
            blocking_entry_ids=ids, linked_set_identities=linked)
        (pending_items if ids else accepted_items).append(candidate)
    if SHEET_ITEMS in workbook:
        accounts.append(SheetAccount(SHEET_ITEMS, len(rows), counts[ACCEPT], counts[REVIEW], counts[EXCLUDE]))

    for sheet in (SHEET_REPLACEMENT_POLICY, SHEET_REPLACEMENT_ITEMS):
        rows = workbook.get(sheet, ())
        for index, _row in enumerate(rows):
            out.add(sheet, ref(sheet, index), "", "", "REFERENCE_ONLY_IN_B1",
                    "replacement metadata: no threshold, part history or advisory is activated in B1", EXCLUDE)
        if sheet in workbook:
            accounts.append(SheetAccount(sheet, len(rows), 0, 0, len(rows)))

    def set_order(s: CandidateSet):
        return (s.plan_code, s.model_variant, s.section, s.set_code)

    def item_order(i: CandidateItem):
        return (i.source_doc, i.section, i.set_code, i.sequence, i.item_key)

    result = PreviewResult(
        source_file=source_file,
        accounts=tuple(sorted(accounts, key=lambda a: a.sheet)),
        ledger=tuple(sorted(out.ledger, key=lambda e: (e.sheet, _row_sort(e.row_or_key.rsplit("!", 1)[-1]),
                                                       e.column, e.issue))),
        sets=tuple(sorted(accepted_sets, key=set_order)),
        items=tuple(sorted(accepted_items, key=item_order)),
        mapping_candidates=tuple(sorted(mappings, key=lambda m: m.vehicle_ref)),
        schema=SCHEMA_MAINTENANCE,
        pending_sets=tuple(sorted(pending_sets, key=set_order)),
        pending_items=tuple(sorted(pending_items, key=item_order)),
        source_profile=source_profile(workbook),
        approved_aliases=tuple(sorted((kind, label, target, evidence_)
                                      for (kind, label), (target, evidence_) in aliases.items())),
    )
    return replace(result, digest=preview_digest(result))


__all__ = [
    "ACCEPT", "REVIEW", "EXCLUDE", "KNOWN_SHEETS", "REQUIRED_COLUMNS", "LedgerEntry", "SheetAccount",
    "CandidateSet", "CandidateItem", "MappingCandidate", "PreviewResult", "preview_source", "preview_digest",
    "SCHEMA_NORMALIZED", "SCHEMA_MAINTENANCE", "SOURCE_COLUMNS", "SOURCE_REQUIRED", "RAW_ACTION_CELLS",
    "OUTCOME_EXCLUDE_ROW", "OUTCOME_RESOLVE_METER", "OUTCOME_RETAIN_RAW", "ISSUE_METER_UNRESOLVED", "ISSUE_RAW_35",
    "NOTE_RAW_35", "SEMANTIC_COLUMNS", "CYCLE_SECTIONS", "ITEM_SECTIONS", "ITEM_SECTION_FOR", "TOPOLOGY",
    "OWNER_HOUR_RULE", "REFERENCE_COUNTS", "ALIAS_PLAN", "ALIAS_MODEL", "GLOBAL_PLAN_SCOPE", "allowed_outcomes",
    "source_profile",
    "reconcile_reference", "preview_maintenance_source",
]
