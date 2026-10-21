"""R4-B1 PM Master Foundation — Mock-only acceptance tests (B1-01 .. B1-18, the
additional negative checks, and the correction batch B1-FIX-01 .. B1-FIX-08).

Every source row here is SYNTHETIC. B1-01..B1-05 exercise the original
normalized internal contract (`preview_source`, codes prefixed SYNTH-). Every
other test uses the SOURCE-SHAPED fixture (`source_workbook`): the real reviewed
MAINTENANCE.xlsx header names and enum spellings with invented SYN values. The
Owner's MAINTENANCE.xlsx is NOT available in this environment, so the
real-source reconciliation (260 / 1,146 / 49 / 235 / 13 / 38) and the full real
header inventory remain UNVERIFIED; these tests prove the CONTRACT only.

Write semantics are exercised with `synthetic_test_only_authorizer`, defined in
this file and passed explicitly. The application's own authorizer
(`deny_unproven_master_authority`) refuses every actor (VAL-AM).
"""
from __future__ import annotations

import ast
import asyncio
import copy
import os
import uuid
from collections import Counter
from pathlib import Path

import pytest

from app.context import RequestContext
from app.domain import authz
from app.domain.pm import PmTriggerType, PmWorkOrderStatus, PmWorkResult
from app.domain.pm_master import (
    ASSIGNED,
    validate_candidate,
    LINEAGE_AMBIGUOUS,
    LINEAGE_CONTINUES,
    LINEAGE_DECLARED_NEW,
    LINEAGE_NEW,
    LINEAGE_REMOVED,
    LINEAGE_RETAINED,
    NONE,
    VAL_AM_GATE,
    LineageDecision,
    MasterItem,
    MasterSet,
    MockVehicleResolver,
    PmMasterMockStore,
    PmMasterService,
    ReviewResolution,
    deny_unproven_master_authority,
)
from app.domain.pm_source_preview import (
    ACCEPT,
    EXCLUDE,
    GLOBAL_PLAN_SCOPE,
    ISSUE_METER_UNRESOLVED,
    ISSUE_RAW_35,
    KNOWN_SHEETS,
    NOTE_RAW_35,
    OUTCOME_EXCLUDE_ROW,
    OUTCOME_RESOLVE_METER,
    OUTCOME_RETAIN_RAW,
    REVIEW,
    SCHEMA_MAINTENANCE,
    SOURCE_COLUMNS,
    preview_maintenance_source,
    preview_source,
    allowed_outcomes,
    reconcile_reference,
)
from app.domain.vehicle_model import ComponentRole
from app.errors import ApiError
from app.repositories.mock import seed_data
from app.repositories.mock.repository import MockRepository

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
SOURCE = "SYNTHETIC_B1_FIXTURE.xlsx"
PLAN_N = "SYNTH-PLAN-A"  # normalized contract only
PUBLISHER = "USR-SYNTH-B1-PUBLISHER"


def synthetic_test_only_authorizer(context, action: str) -> None:
    """TEST ONLY: lets one synthetic actor through so the Mock publish/assign
    semantics can be exercised. Not an application authority; anyone else gets
    the application's fail-closed refusal."""
    if getattr(context, "user_id", None) != PUBLISHER:
        deny_unproven_master_authority(context, action)


def ctx(user: str = PUBLISHER, capabilities: frozenset[str] = frozenset({authz.CAN_VIEW}), **kw) -> RequestContext:
    return RequestContext(request_id=str(uuid.uuid4()), user_id=user, capabilities=capabilities, **kw)


def service(store: PmMasterMockStore | None = None, **kw) -> PmMasterService:
    return PmMasterService(store or PmMasterMockStore(), authorizer=synthetic_test_only_authorizer, **kw)


def cycle(plan=PLAN_N, variant="SYNTH-V1", section="CARRIER", set_code="SET-500", meter="ENGINE_HOUR",
          interval="500", unit="hour", doc="SYNTH-DOC-1", group="", **extra) -> dict[str, object]:
    return {"plan_code": plan, "model_variant": variant, "section": section, "set_code": set_code,
            "meter_type": meter, "interval_value": interval, "interval_unit": unit, "independent_group": group,
            "source_doc": doc, **extra}


def item(key, seq, text, plan=PLAN_N, variant="SYNTH-V1", section="CARRIER", set_code="SET-500", doc="SYNTH-DOC-1",
         **extra) -> dict[str, object]:
    return {"plan_code": plan, "model_variant": variant, "section": section, "set_code": set_code, "item_key": key,
            "sequence": seq, "task_text": text, "method": "ตรวจสอบด้วยสายตา", "standard": "ตามคู่มือ",
            "source_doc": doc, **extra}


def synthetic_workbook() -> dict[str, list[dict[str, object]]]:
    return {
        "source_pm_standard": [
            {"doc_code": "SYNTH-DOC-1", "doc_status": "CURRENT"},
            {"doc_code": "SYNTH-DOC-2", "doc_status": "CURRENT"},
            {"doc_code": "SYNTH-DOC-OLD", "doc_status": "CANCELLED"},
            {"doc_code": "SYNTH-DOC-BLANK", "doc_status": "BLANK_TEMPLATE"},
        ],
        "source_pm_cycles": [
            cycle(),                                                          # row 2  ACCEPT
            cycle(section="CRANE", interval="600"),                           # row 3  ACCEPT (same set code, crane)
            cycle(variant="SYNTH-V2", interval="1,000", raw_note="x"),        # row 4  ACCEPT (other variant)
            cycle(set_code="SET-KM", meter="ODOMETER", interval="10,000", unit="km", group="INDEPENDENT_GROUP"),
            cycle(section="NOT_SEPARATED_IN_FORM", set_code="SET-NS"),        # row 6  REVIEW (driving component)
            cycle(set_code="SET-CAL", meter="CALENDAR", unit="day"),          # row 7  REVIEW (no calendar)
            cycle(set_code="SET-DUP"), cycle(set_code="SET-DUP", interval="700"),  # rows 8/9 REVIEW duplicate
            cycle(set_code="SET-OLD", doc="SYNTH-DOC-OLD"),                   # row 10 REVIEW cancelled doc
            cycle(set_code="SET-BLANK", interval=""),                         # row 11 REVIEW blank interval
            cycle(set_code="SET-ZERO", interval="0"),                         # row 12 REVIEW zero interval
            cycle(set_code="SET-35", group="35"),                             # row 13 REVIEW raw 35
            cycle(set_code="SET-UNIT", unit="km"),                            # row 14 REVIEW unit mismatch
        ],
        "source_pm_items": [
            item("I-1", 1, "ตรวจระดับน้ำมันเครื่อง"),
            item("I-2", 2, "ทำความสะอาดไส้กรองอากาศ"),
            item("I-3", 35, "ตรวจสายพาน"),                                    # sequence 35 is a legitimate number
            item("C-1", 1, "ตรวจน้ำมันไฮดรอลิก", section="CRANE"),
            item("V2-1", 1, "ตรวจระดับน้ำมันเครื่อง", variant="SYNTH-V2"),
            item("K-1", 1, "ตรวจลมยาง", set_code="SET-KM"),
            item("", 3, "ไม่มีรหัสรายการ"),                                    # REVIEW: no invented id
            item("I-DUP", 4, "a"), item("I-DUP", 5, "b"),                     # REVIEW duplicates
            item("X-1", 1, "orphan", set_code="SET-NONE"),                   # REVIEW: Set not accepted
            item("N-1", 1, "not separated", section="NOT_SEPARATED_IN_FORM", set_code="SET-NS"),
            item("Q-1", 6, "อะไหล่", quantity="35"),                          # REVIEW raw 35
            item("B-1", 7, "blank-template doc", doc="SYNTH-DOC-BLANK"),      # REVIEW noncurrent doc
        ],
        "vehicle_pm_mapping": [
            {"vehicle_ref": "SYNTH-VEH-01", "plan_code": PLAN_N},
            {"vehicle_ref": "SYNTH-VEH-02", "plan_code": PLAN_N},
            {"vehicle_ref": "SYNTH-VEH-03", "plan_code": "SYNTH-PLAN-B"},
            {"vehicle_ref": "SYNTH-VEH-04", "plan_code": ""},                 # no Plan — valid, stays unassigned
            {"vehicle_ref": "SYNTH-VEH-05", "plan_code": ""},
            {"vehicle_ref": "SYNTH-VEH-06", "plan_code": "35"},               # REVIEW raw 35, never a Plan ID
        ],
        "replacement_policy": [{"policy": "SYNTH-P1"}, {"policy": "SYNTH-P2"}],
        "replacement_items": [{"item": "SYNTH-R1"}],
        "SYNTH_UNRELATED_TAB": [{"name": "private-looking row"}],
    }


def rows(preview, sheet, action=None):
    return [e for e in preview.ledger if e.sheet == sheet and (action is None or e.action == action)]


# B1-01 -------------------------------------------------------------------------


def test_b1_01_repeated_identical_preview_is_deterministic_and_writes_nothing() -> None:
    wb = synthetic_workbook()
    before = copy.deepcopy(wb)
    first, second = preview_source(wb, source_file=SOURCE), preview_source(copy.deepcopy(wb), source_file=SOURCE)
    assert wb == before  # input untouched
    assert first.digest == second.digest and len(first.digest) == 64 and first == second
    reordered = {k: wb[k] for k in reversed(list(wb))}  # tab order does not change the result
    assert preview_source(reordered, source_file=SOURCE).digest == first.digest
    wb["source_pm_items"][0]["task_text"] = "ข้อความเปลี่ยน"
    assert preview_source(wb, source_file=SOURCE).digest != first.digest


# B1-02 / B1-03 -----------------------------------------------------------------


def test_b1_02_every_cycle_row_is_accounted_for_with_a_reasoned_exception() -> None:
    p = preview_source(synthetic_workbook(), source_file=SOURCE)
    acc = p.account("source_pm_cycles")
    assert (acc.total, acc.accepted, acc.review, acc.excluded) == (13, 4, 9, 0) and acc.balanced
    review_rows = {e.row_or_key for e in rows(p, "source_pm_cycles", REVIEW)}
    assert review_rows == {f"row:{n}" for n in range(6, 15)}  # every non-accepted row has a ledger reason
    issues = {(e.row_or_key, e.issue) for e in rows(p, "source_pm_cycles")}
    assert {("row:6", "DRIVING_COMPONENT_ABSENT"), ("row:7", "METER_NOT_EXPLICIT"), ("row:8", "DUPLICATE_SET_IDENTITY"),
            ("row:9", "DUPLICATE_SET_IDENTITY"), ("row:10", "REFERENCES_NONCURRENT_DOC"),
            ("row:11", "MISSING_REQUIRED_VALUE"), ("row:12", "INVALID_INTERVAL"), ("row:13", "AMBIGUOUS_RAW_35"),
            ("row:14", "UNIT_METER_MISMATCH")} <= issues
    assert all(e.source_file == SOURCE and e.reason and e.evidence and e.reviewer == "" for e in p.ledger)
    # every known tab present is balanced; the out-of-scope tab is logged, not silently dropped
    assert all(a.balanced for a in p.accounts)
    assert [e.issue for e in p.ledger if e.sheet == "SYNTH_UNRELATED_TAB"] == ["SHEET_OUT_OF_B1_SCOPE"]


def test_b1_03_every_item_row_is_accounted_for_and_no_identifier_is_invented() -> None:
    p = preview_source(synthetic_workbook(), source_file=SOURCE)
    acc = p.account("source_pm_items")
    assert (acc.total, acc.accepted, acc.review) == (13, 6, 7) and acc.balanced
    assert {i.item_key for i in p.items} == {"I-1", "I-2", "I-3", "C-1", "V2-1", "K-1"}
    assert all(i.item_key for i in p.items)  # the key-less row is REVIEW, never given a generated id
    by_row = {(e.row_or_key, e.issue) for e in rows(p, "source_pm_items")}
    assert {("row:8", "MISSING_REQUIRED_VALUE"), ("row:9", "DUPLICATE_ITEM_KEY"), ("row:10", "DUPLICATE_ITEM_KEY"),
            ("row:11", "SET_NOT_ACCEPTED"), ("row:12", "SET_NOT_ACCEPTED"), ("row:13", "AMBIGUOUS_RAW_35"),
            ("row:14", "REFERENCES_NONCURRENT_DOC")} <= by_row
    # source wording, method, standard and provenance are retained verbatim
    first = next(i for i in p.items if i.item_key == "I-1")
    assert (first.task_text, first.method, first.standard, first.source_row) == (
        "ตรวจระดับน้ำมันเครื่อง", "ตรวจสอบด้วยสายตา", "ตามคู่มือ", "row:2")


# B1-04 / B1-05 -----------------------------------------------------------------


def test_b1_04_cancelled_and_blank_template_documents_are_excluded_and_logged() -> None:
    p = preview_source(synthetic_workbook(), source_file=SOURCE)
    acc = p.account("source_pm_standard")
    assert (acc.total, acc.accepted, acc.review, acc.excluded) == (4, 2, 0, 2)
    assert {(e.raw_reference, e.issue, e.action) for e in rows(p, "source_pm_standard")} == {
        ("CANCELLED", "DOC_CANCELLED", EXCLUDE), ("BLANK_TEMPLATE", "DOC_BLANK_TEMPLATE", EXCLUDE)}
    assert not any(s.source_doc in {"SYNTH-DOC-OLD", "SYNTH-DOC-BLANK"} for s in p.sets)
    assert not any(i.source_doc in {"SYNTH-DOC-OLD", "SYNTH-DOC-BLANK"} for i in p.items)
    replacement = [a for a in p.accounts if a.sheet.startswith("replacement_")]
    assert [(a.sheet, a.total, a.excluded) for a in replacement] == [("replacement_items", 1, 1),
                                                                     ("replacement_policy", 2, 2)]  # reference only, not active


def test_b1_05_ambiguous_raw_35_is_review_and_never_interpreted() -> None:
    p = preview_source(synthetic_workbook(), source_file=SOURCE)
    hits = [e for e in p.ledger if e.issue == "AMBIGUOUS_RAW_35"]
    assert {(e.sheet, e.column, e.raw_reference, e.action) for e in hits} == {
        ("source_pm_cycles", "independent_group", "35", REVIEW), ("source_pm_items", "quantity", "35", REVIEW),
        ("vehicle_pm_mapping", "plan_code", "35", REVIEW)}
    assert all(m.plan_code != "35" for m in p.mapping_candidates)         # not a Plan ID
    assert not any(s.set_code == "SET-35" for s in p.sets)                # not an active Set
    assert not any(i.item_key == "Q-1" for i in p.items)                  # not a part / quantity
    assert any(i.sequence == 35 for i in p.items)                         # the numeric sequence column is fine


# ---------------------------------------------------------------------------
# Source-shaped fixture (real reviewed header names and enum spellings,
# SYNTHETIC values). Planning tabs and inspection documents are DIFFERENT
# namespaces, exactly as in the real workbook; only vehicle_pm_mapping links them.
# ---------------------------------------------------------------------------

SRC_FILE = "SYNTHETIC_SOURCE_SHAPED_B1.xlsx"
PLAN = "SYN PM Plan1"        # a planning tab name (cycles.source_sheet == mapping.source_plan)
PLAN_B = "SYN PM Plan2"
DOC_LOW, DOC_UP = "SYN-DOC-A1 ล่าง", "SYN-DOC-A1 บน"     # dual-engine model M1: carrier / crane documents
DOC_M2, DOC_M3, DOC_M4, DOC_M5, DOC_B = "SYN-DOC-A2", "SYN-DOC-A3", "SYN-DOC-A4", "SYN-DOC-A5", "SYN-DOC-B1"
EVIDENCE = "ตรวจทานกับเอกสารต้นฉบับแผ่นงานที่ระบุแล้ว (synthetic)"
CARRIER_A, CRANE_A = "SYN-M1|CARRIER|A", "SYN-M1|CRANE|A"
M2_A, M3_A, M7_A = "SYN-M2|NOT_SEPARATED_IN_PLAN|A", "SYN-M3|NOT_SEPARATED_IN_PLAN|A", "SYN-M7|NOT_SEPARATED_IN_PLAN|A"
KM_SET, K35_SET = "SYN-M1|CARRIER|KM1", "SYN-M1|CARRIER|K35"


def scyc(model="SYN-M1", section="CARRIER", group="A", value="500", unit="HOUR", sheet=PLAN, group_rule="",
         next_due_rule="") -> dict[str, object]:
    return {"source_sheet": sheet, "model_label_corrected": model, "component_section": section, "task_group": group,
            "interval_value": value, "interval_unit": unit, "group_rule": group_rule, "next_due_rule": next_due_rule}


def sitem(doc, row, group, section, seq, text, check="35", clean="35", change="35") -> dict[str, object]:
    """Like every real item row, the three form action cells carry a raw 35."""
    return {"source_sheet": doc, "source_row": row, "task_group": group, "component_section": section,
            "sequence_raw": seq, "description_raw": text, "method_raw": "ตรวจสอบด้วยสายตา",
            "standard_raw": "ตามคู่มือ", "frequency_approved": "ตามรอบ", "interval_value": "", "interval_unit": "",
            "check_cell_raw": check, "clean_cell_raw": clean, "change_fill_cell_raw": change}


def sstd(doc, status="SOURCE_STANDARD") -> dict[str, object]:
    """Like every real standard row, an unrelated metadata cell carries a raw 35."""
    return {"source_sheet": doc, "source_status": status, "source_google_sheet_url": "35"}


def smap(vehicle, config, plan=PLAN, model="SYN-M1", low="", up="", status="MATCHED_PENDING_IMPLEMENTATION"):
    return {"vehicle_id": vehicle, "source_plan": plan, "plan_model": model, "component_configuration": config,
            "carrier_or_main_source_sheet": low, "crane_source_sheet": up, "mapping_status": status,
            "mapping_basis": "SYN"}


def source_workbook() -> dict[str, list[dict[str, object]]]:
    single = "NOT_SEPARATED_IN_PLAN"
    return {
        "source_pm_standard": [sstd(d) for d in (DOC_LOW, DOC_UP, DOC_M2, DOC_M3, DOC_M4, DOC_M5, DOC_B)] + [
            sstd("SYN-DOC-X", "EMPTY_TEMPLATE"), sstd("SYN-DOC-Y", "CANCELLED")],
        "vehicle_pm_mapping": [
            smap("SYN-VEH-01", "CARRIER_AND_CRANE", low=DOC_LOW, up=DOC_UP),          # row 2  DUAL
            smap("SYN-VEH-02", "CARRIER_AND_CRANE", low=DOC_LOW, up=DOC_UP),          # row 3  DUAL (agrees)
            smap("SYN-VEH-03", single, model="SYN-M2", low=DOC_M2),                   # row 4  SINGLE
            smap("SYN-VEH-04", single, model="SYN-M3", low=DOC_M3),                   # row 5  SINGLE (shares Set A)
            smap("SYN-VEH-05", single, model="SYN-M5", low=DOC_M5),                   # row 6  SINGLE
            smap("SYN-VEH-06", single, model="SYN-M5", low="SYN-DOC-Y"),              # row 7  SINGLE, other doc
            smap("SYN-VEH-07", single, plan=PLAN_B, model="SYN-M6", low=DOC_B),       # row 8  SINGLE (Plan 2)
            smap("SYN-VEH-08", single, model="SYN-M4", low=DOC_M4),                   # row 9  SINGLE (alias case)
            smap("SYN-VEH-09", "UNKNOWN", plan="", model="", status="PENDING_PM_PLAN"),  # row 10 UNKNOWN, no Plan
            smap("SYN-VEH-10", "UNKNOWN", plan="", model="", status="PENDING_PM_PLAN"),  # row 11 UNKNOWN, no Plan
            smap("SYN-VEH-11", "UNKNOWN", model="SYN-M7", low=DOC_M2),                # row 12 UNKNOWN, matched
            smap("SYN-VEH-12", single, model="SYN-M2", low=DOC_M2, status="35"),      # row 13 REVIEW raw 35
            smap("SYN-VEH-13", "CARRIER", model="SYN-M2", low=DOC_M2),                # row 14 REVIEW config
        ],
        "source_pm_cycles": [
            scyc(),                                                           # row 2  M1 CARRIER A (dual, owner rule)
            scyc(section="CRANE", value="600"),                               # row 3  M1 CRANE A
            scyc(model="SYN-M2", section=single, value="250"),                # row 4  M2 single A
            scyc(model="SYN-M3", section=single, value="300"),                # row 5  M3 single A (same Set A)
            scyc(group="KM1", value="10,000", unit="KM", group_rule="INDEPENDENT_GROUP",
                 next_due_rule="ตามระยะทาง"),                                  # row 6  ACCEPT odometer
            scyc(model="SYN-M2", section="CARRIER", group="B"),               # row 7  hard: single has no CARRIER
            scyc(section=single, group="C", value="100"),                     # row 8  hard: dual has no not-separated
            scyc(model="SYN-M9", section=single, value="100"),                # row 9  hard: not mapped
            scyc(model="SYN-M5", section=single, value="100"),                # row 10 hard: two documents
            scyc(model="SYN-M4 (corr)", section=single, value="120"),         # row 11 hard unless alias approved
            scyc(model="SYN-M2", section=single, group="DUP"),                # row 12 hard duplicate
            scyc(model="SYN-M2", section=single, group="DUP", value="700"),   # row 13 hard duplicate
            scyc(section="CRANE", group="KM2", value="5000", unit="KM"),      # row 14 hard: CRANE on km
            scyc(group="DAY", value="30", unit="DAY"),                        # row 15 hard: no calendar
            scyc(group="BLANK", value=""),                                    # row 16 hard: blank interval
            scyc(group="ZERO", value="0"),                                    # row 17 hard: zero interval
            scyc(group="K35", unit="KM", group_rule="35"),                    # row 18 soft: raw 35 label
            scyc(model="SYN-M2", section="NOT_SEPARATED_IN_FORM", group="X"),  # row 19 hard: form label on a plan
            scyc(sheet=PLAN_B, model="SYN-M6", section=single, group="GB", value="20000", unit="KM"),  # row 20
            scyc(model="SYN-M7", section=single, value="400"),                # row 21 soft: HOUR, UNKNOWN config
        ],
        "source_pm_items": [
            sitem(DOC_LOW, 5, "A", "CARRIER", 1, "ตรวจระดับน้ำมันเครื่อง (ล่าง)"),      # row 2  -> M1 CARRIER A
            sitem(DOC_LOW, 6, "A", "CARRIER", 2, "ทำความสะอาดไส้กรองอากาศ"),          # row 3  -> M1 CARRIER A
            sitem(DOC_UP, 5, "A", "CRANE", 1, "ตรวจน้ำมันไฮดรอลิก"),                 # row 4  -> M1 CRANE A
            sitem(DOC_M2, 5, "A", "NOT_SEPARATED_IN_FORM", 1, "ตรวจเครื่องยนต์ M2"),  # row 5  -> M2 A and M7 A
            sitem(DOC_M3, 5, "A", "NOT_SEPARATED_IN_FORM", 1, "ตรวจเครื่องยนต์ M3"),  # row 6  -> M3 A only
            sitem(DOC_LOW, 9, "KM1", "CARRIER", 1, "ตรวจลมยาง"),                     # row 7  -> M1 CARRIER KM1
            sitem(DOC_LOW, 7, "A", "CARRIER", "", "ไม่มีลำดับ"),                      # row 8  hard: no sequence
            sitem(DOC_LOW, 8, "A", "CARRIER", 3, "a"),                               # row 9  hard: dup pointer
            sitem(DOC_LOW, 8, "A", "CARRIER", 4, "b"),                               # row 10 hard: dup pointer
            sitem(DOC_M3, 6, "A", "NOT_SEPARATED_IN_FORM", 2, "35"),                 # row 11 soft: raw 35 task text
            sitem("SYN-DOC-Z", 5, "A", "NOT_SEPARATED_IN_FORM", 1, "unknown doc"),   # row 12 hard: not a standard
            sitem("SYN-DOC-Y", 5, "A", "NOT_SEPARATED_IN_FORM", 1, "cancelled doc"),  # row 13 hard: not current
            sitem(DOC_B, 5, "GB", "NOT_SEPARATED_IN_FORM", 1, "ตรวจลมยาง B"),        # row 14 -> Plan2 M6 GB
            sitem(DOC_M2, 6, "QQ", "NOT_SEPARATED_IN_FORM", 1, "orphan group"),      # row 15 hard: not linked
            sitem(DOC_LOW, 10, "A", "NOT_SEPARATED_IN_FORM", 3, "wrong section"),    # row 16 hard: not linked
            sitem(DOC_M4, 5, "A", "NOT_SEPARATED_IN_FORM", 1, "ตรวจ M4"),            # row 17 linked only via alias
            sitem(DOC_LOW, 11, "K35", "CARRIER", 1, "ตรวจระยะทาง"),                  # row 18 -> M1 CARRIER K35
        ],
        "replacement_policy": [{"policy_raw": "SYN-P1"}, {"policy_raw": "SYN-P2"}],
        "replacement_items": [{"item_raw": "SYN-R1"}],
        "SYNTH_UNRELATED_TAB": [{"name": "private-looking row"}],
    }


M4_ALIAS = ("MODEL", "SYN-M4 (corr)", "SYN-M4", "ชื่อรุ่นในแผนตรงกับรุ่นในตารางจับคู่ ยืนยันโดยผู้ตรวจทาน (synthetic)")
# The one HOUR Set whose mapping configuration is UNKNOWN needs a reviewer's meter decision.
METER_BY_ROW = {"source_pm_cycles!row:21": {"meter_type": "ENGINE_HOUR", "driving_component": "CARRIER_ENGINE"}}


def snapshot(store: PmMasterMockStore):
    return (dict(store.revisions), store.assignments, store.previews, store.resolutions,
            tuple(dict(e) for e in store.events))


async def register(svc, workbook=None, *, source_file=SRC_FILE, context=None, aliases=()):
    return await svc.register_preview(context or ctx(), workbook=workbook or source_workbook(),
                                      source_file=source_file, reason="ลงทะเบียนตัวอย่างข้อมูลต้นทาง",
                                      request_id=str(uuid.uuid4()), approved_aliases=aliases)


def blocks(entry, plan) -> bool:
    return entry.action == REVIEW and (plan in entry.plan_scope or GLOBAL_PLAN_SCOPE in entry.plan_scope)


async def resolve_all(svc, reg, plan=PLAN, *, skip=()):
    """Resolve every REVIEW entry that blocks `plan` (its own scope or the global
    unresolved-source gate): the UNKNOWN-configuration HOUR Set per METER_BY_ROW,
    everything else — including every semantic raw 35 — excluded."""
    for e in reg.preview.ledger:
        if not blocks(e, plan) or e.entry_id in skip:
            continue
        if e.issue == ISSUE_METER_UNRESOLVED and e.row_or_key in METER_BY_ROW:
            outcome, values = OUTCOME_RESOLVE_METER, METER_BY_ROW[e.row_or_key]
        else:
            outcome, values = OUTCOME_EXCLUDE_ROW, None
        await svc.record_review(ctx(), preview_id=reg.preview_id, expected_source_digest=reg.source_digest,
                                entry_id=e.entry_id, outcome=outcome, values=values, evidence=EVIDENCE,
                                request_id=str(uuid.uuid4()))


async def publish(svc, reg, n, *, plan=PLAN, request_id=None, reason="เผยแพร่ทดสอบ", context=None, lineage=()):
    return await svc.publish(context or ctx(), plan_code=plan, expected_revision=n, preview_id=reg.preview_id,
                             expected_source_digest=reg.source_digest, reason=reason,
                             request_id=request_id or str(uuid.uuid4()), lineage=lineage)


async def published(store=None, *, resolver=None, workbook=None):
    store = store or PmMasterMockStore()
    svc = service(store, vehicle_resolver=resolver)
    reg = await register(svc, workbook)
    await resolve_all(svc, reg)
    outcome = await publish(svc, reg, 0)
    return store, svc, reg, outcome.revision


def with_cycle_value(row_index: int, value: str):
    wb = source_workbook()
    wb["source_pm_cycles"][row_index]["interval_value"] = value
    return wb


def item_keys(revision, set_key):
    return [i.item_key for s in revision.sets if s.set_key == set_key for i in s.items]


# B1-06 / B1-07 / B1-08 ----------------------------------------------------------


async def test_b1_06_source_candidates_never_auto_assign_and_missing_plans_stay_valid() -> None:
    store, svc, reg, _ = await published()
    p = reg.preview
    pending = [(m.vehicle_ref, m.plan_code, m.topology) for m in p.mapping_candidates if m.status == "PENDING_PM_PLAN"]
    assert pending == [("SYN-VEH-09", "", "UNKNOWN"), ("SYN-VEH-10", "", "UNKNOWN")]
    assert store.assignments == ()  # previewing, reviewing and publishing assigned nothing
    for m in p.mapping_candidates:
        resolved = svc.resolve_plan(ctx(), m.vehicle_ref)
        assert (resolved.source, resolved.plan_code) == ("ABSENT", None)  # candidate != assigned
    acc = p.account("vehicle_pm_mapping")
    assert (acc.accepted, acc.review) == (11, 2)  # the Plan-less rows are valid, not errors


async def test_b1_07_carrier_and_crane_are_assemblies_of_one_physical_vehicle() -> None:
    repo = MockRepository()
    store, svc, _, rev = await published(resolver=MockVehicleResolver(repo))
    sets = {s.set_key: s for s in rev.sets}
    assert (sets[CARRIER_A].driving_component, sets[CRANE_A].driving_component) == (
        ComponentRole.CARRIER_ENGINE, ComponentRole.CRANE_ENGINE)  # Owner dual-engine rule, CARRIER_AND_CRANE only
    assert (sets[CARRIER_A].interval_value, sets[CRANE_A].interval_value) == (500, 600)
    vehicle_before = (await repo.get_vehicle("VEH-1047")).model_dump()
    for assembly in ("CARRIER", "CRANE"):
        await svc.set_assignment(ctx(), vehicle_id="VEH-1047", assembly=assembly, plan_code=PLAN,
                                 expected_version=0, reason="กำหนดแผนต่อชุดประกอบ", request_id=str(uuid.uuid4()))
    assert {(a.vehicle_id, a.assembly) for a in store.assignments} == {("VEH-1047", "CARRIER"), ("VEH-1047", "CRANE")}
    assert (await repo.get_vehicle("VEH-1047")).model_dump() == vehicle_before  # one identity, unchanged


async def test_b1_08_same_plan_keeps_per_set_intervals_and_original_values() -> None:
    _, _, _, rev = await published()
    sets = {s.set_key: s for s in rev.sets}
    assert {k: (s.meter_type, s.interval_value, s.interval_unit, s.raw_interval) for k, s in sets.items()} == {
        CARRIER_A: (PmTriggerType.ENGINE_HOUR, 500, "HOUR", "500"),
        CRANE_A: (PmTriggerType.ENGINE_HOUR, 600, "HOUR", "600"),
        M2_A: (PmTriggerType.ENGINE_HOUR, 250, "HOUR", "250"),
        M3_A: (PmTriggerType.ENGINE_HOUR, 300, "HOUR", "300"),
        M7_A: (PmTriggerType.ENGINE_HOUR, 400, "HOUR", "400"),
        KM_SET: (PmTriggerType.ODOMETER, 10000, "KM", "10,000"),
    }
    assert sets[KM_SET].independent_group == "INDEPENDENT_GROUP"   # source group_rule kept verbatim
    assert K35_SET not in sets                                     # semantic raw 35 can only be excluded
    assert ("next_due_rule", "ตามระยะทาง") in sets[KM_SET].raw      # kept raw only; no Due computed


# B1-09 / B1-10 -------------------------------------------------------------------


async def test_b1_09_publish_preserves_rev_n_audits_the_diff_and_requires_validation() -> None:
    store, svc, _, rev1 = await published()
    rev1_dump = rev1.model_dump()
    reg2 = await register(svc, with_cycle_value(1, "650"))
    await resolve_all(svc, reg2)
    outcome = await publish(svc, reg2, 1, reason="ปรับรอบตามเอกสารใหม่")
    assert outcome.revision.revision_number == 2 and svc.effective_revision(ctx(), PLAN).revision_number == 2
    assert svc.get_revision(ctx(), PLAN, 1).model_dump() == rev1_dump  # Rev N unchanged
    assert outcome.diff["sets_changed"] == [{"set_key": CRANE_A, "fields": {
        "interval_value": {"from": 600.0, "to": 650.0}, "raw_interval": {"from": "600", "to": "650"}}}]
    assert svc.compare(ctx(), PLAN, 1, 2)["sets_changed"] == outcome.diff["sets_changed"]
    assert {r["status"] for r in outcome.diff["items"]} == {LINEAGE_RETAINED}  # same pointers, same content
    publishes = [(e["kind"], e["version"], e["actor_user_id"], e["reason"]) for e in svc.audit(ctx())
                 if e["kind"] == "PUBLISH"]
    assert publishes == [("PUBLISH", "1", PUBLISHER, "เผยแพร่ทดสอบ"), ("PUBLISH", "2", PUBLISHER, "ปรับรอบตามเอกสารใหม่")]
    assert outcome.revision.preview_id == reg2.preview_id and outcome.revision.source_digest == reg2.source_digest
    with pytest.raises(pydantic_frozen_error()):
        rev1.sets[0].interval_value = 1  # immutable revision content
    reg3 = await register(svc, with_cycle_value(1, "650"))  # identical content to Rev 2
    await resolve_all(svc, reg3)
    before = snapshot(store)
    with pytest.raises(ApiError) as same:
        await publish(svc, reg3, 2)
    assert same.value.code == "PM_MASTER_UNCHANGED" and snapshot(store) == before


def pydantic_frozen_error():
    from pydantic import ValidationError
    return ValidationError


async def test_b1_10_old_work_order_snapshot_keeps_its_revision_after_n_plus_1(client) -> None:
    store, svc, _, _ = await published()
    frozen = svc.freeze_selection(ctx(), PLAN, [CARRIER_A, KM_SET])
    frozen_dump = frozen.model_dump()
    reg2 = await register(svc, with_cycle_value(0, "550"))
    await resolve_all(svc, reg2)
    await publish(svc, reg2, 1)
    assert frozen.model_dump() == frozen_dump and frozen.revision_number == 1
    assert svc.freeze_selection(ctx(), PLAN, [CARRIER_A]).sets[0].interval_value == 550
    assert svc.freeze_selection(ctx(), PLAN, [CARRIER_A], revision_number=1).sets[0] == frozen.sets[0]
    with pytest.raises(ApiError):
        svc.freeze_selection(ctx(), PLAN, ["SYN-M9|CRANE|NOPE"])
    # The current runtime PM flow (OPEN / CLOSED + completed: bool) is untouched by any Master publish.
    opened = (await client.post("/api/v1/pm/work-orders", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046",
                                                                 "pm_plan_id": "PMP-0001"})).json()
    wo_closed = opened["work_order"]["pm_work_order_id"]
    await client.post(f"/api/v1/pm/work-orders/{wo_closed}/results", json={"pm_task_id": "PMT-0001", "completed": True})
    await client.post(f"/api/v1/pm/work-orders/{wo_closed}/close", json={})
    wo_open = (await client.post("/api/v1/pm/work-orders", json={
        "asset_type": "VEHICLE", "asset_id": "VEH-1048", "pm_plan_id": "PMP-0001"})).json()["work_order"]["pm_work_order_id"]
    before = [(await client.get(f"/api/v1/pm/work-orders/{w}")).json() for w in (wo_closed, wo_open)]
    assert [b["work_order"]["status"] for b in before] == ["CLOSED", "OPEN"]
    reg3 = await register(svc, with_cycle_value(0, "575"))
    await resolve_all(svc, reg3)
    await publish(svc, reg3, 2, reason="Rev 3")
    after = [(await client.get(f"/api/v1/pm/work-orders/{w}")).json() for w in (wo_closed, wo_open)]
    assert after == before and all(b["work_order"]["revision_id"] == "PMREV-0001" for b in after)


# B1-11 / B1-12 -------------------------------------------------------------------


async def test_b1_11_assign_change_unassign_with_reason_version_and_audit_or_fail_closed() -> None:
    store, svc, reg, _ = await published(resolver=MockVehicleResolver(MockRepository()))
    await publish(svc, reg, 0, plan=PLAN_B, reason="แผนใหม่")  # a new Plan added later (no open reviews)
    steps = [(PLAN, 0, "ASSIGN"), (PLAN_B, 1, "CHANGE"), (None, 2, "UNASSIGN"), (PLAN, 3, "ASSIGN")]
    for plan, version, kind in steps:
        out = await svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=plan, expected_version=version,
                                       reason=f"เหตุผล {kind}", request_id=str(uuid.uuid4()))
        assert (out.record.version, out.record.state, out.replayed) == (version + 1, NONE if plan is None else ASSIGNED, False)
        assert store.events[-1]["kind"] == kind and store.events[-1]["reason"] == f"เหตุผล {kind}"
    assert [a.version for a in store.assignments] == [1, 2, 3, 4]  # history kept, nothing rewritten
    before = snapshot(store)
    for kwargs, expected in (({"plan_code": PLAN, "expected_version": 1}, "PM_MASTER_STALE_ASSIGNMENT"),
                             ({"plan_code": "SYN UNPUBLISHED", "expected_version": 4}, "PM_MASTER_NOT_PUBLISHED"),
                             ({"plan_code": PLAN, "expected_version": 4}, "PM_MASTER_ASSIGNMENT_UNCHANGED")):
        with pytest.raises(ApiError) as refused:
            await svc.set_assignment(ctx(), vehicle_id="VEH-1046", reason="x", request_id=str(uuid.uuid4()), **kwargs)
        assert refused.value.code == expected
    with pytest.raises(ApiError) as no_reason:
        await svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=None, expected_version=4, reason=" ",
                                 request_id=str(uuid.uuid4()))
    assert no_reason.value.code == "VALIDATION_ERROR"
    app_svc = PmMasterService(store, vehicle_resolver=MockVehicleResolver(MockRepository()))
    with pytest.raises(ApiError) as closed:
        await app_svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=None, expected_version=4, reason="x",
                                     request_id=str(uuid.uuid4()))
    assert (closed.value.status_code, closed.value.code, closed.value.details["gate"]) == (
        403, "PM_MASTER_AUTHORITY_UNPROVEN", VAL_AM_GATE)
    assert snapshot(store) == before


async def test_b1_12_explicit_unassignment_is_never_overridden_by_the_model_default(client) -> None:
    repo = MockRepository()
    store, svc, _, _ = await published(resolver=MockVehicleResolver(repo))
    model = await repo.get_vehicle_model((await repo.get_vehicle("VEH-1046")).model_id)
    legacy = model.assigned_pm_plan_id
    assert legacy == "PMP-0001"  # the old model default is still there and still non-authoritative here
    absent = svc.resolve_plan(ctx(), "VEH-1046", legacy_model_plan_id=legacy)
    assert (absent.source, absent.plan_code, absent.legacy_model_plan_id) == ("ABSENT", None, "PMP-0001")
    await svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=None, expected_version=0,
                             reason="ไม่มีแผน PM", request_id=str(uuid.uuid4()))
    for assembly in ("", "CARRIER", "CRANE"):
        none = svc.resolve_plan(ctx(), "VEH-1046", assembly, legacy_model_plan_id=legacy)
        assert (none.source, none.plan_code) == ("EXPLICIT_NONE", None)
    assert (await client.get("/api/v1/models/MODEL-0001")).json()["assigned_pm_plan_id"] == "PMP-0001"
    status_rows = (await client.get("/api/v1/pm/plans/status", params={"asset_type": "VEHICLE",
                                                                        "asset_id": "VEH-1046"})).json()
    assert [r["plan"]["pm_plan_id"] for r in status_rows] == ["PMP-0001"]
    assert (await client.post("/api/v1/pm/work-orders", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046",
                                                               "pm_plan_id": "PMP-0001"})).status_code == 200


# B1-13 — existing Access Management, effective contexts ---------------------------


@pytest.fixture
def am_mode(monkeypatch):
    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "true")
    monkeypatch.setenv("DEV_AUTH_MODE", "true")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATA_REPOSITORY", "mock")
    yield
    from app.config import get_settings
    get_settings.cache_clear()  # never leak Access Management settings into later tests


async def effective(store, user: str, role: str = "TECHNICIAN") -> RequestContext:
    from app.config import get_settings
    from app.domain.access_management import AccessService
    from app.domain.technician_assignment import cutover_from_settings

    get_settings.cache_clear()
    cutover = cutover_from_settings(get_settings())
    return await AccessService(store, cutover.data_context, cutover.test_batch_id).effective_context(
        RequestContext(request_id=str(uuid.uuid4()), user_id=user, roles=(role,), is_dev_auth=True))


async def test_b1_13_denied_revoked_expired_and_wrong_scope_actors_cannot_read_or_mutate(am_mode) -> None:
    from tests.test_access_management import DRV1, MGR, MNT, OPM, OPS, P, RESIGNED, TECH1, delegate, employee, grant, http

    am = MockRepository(access_management_seed=True)
    master, _, reg, _ = await published()  # synthetic content to read, published with test-only authority
    app_svc = PmMasterService(master, vehicle_resolver=MockVehicleResolver(MockRepository()))
    before = snapshot(master)

    async def outcome(user, role="TECHNICIAN"):
        context = await effective(am, user, role)
        try:
            app_svc.effective_revision(context, PLAN)
            read = "READ"
        except Exception as exc:  # noqa: BLE001 — HTTPException 403 from require_capability
            read = getattr(exc, "status_code", "?")
        writes = set()
        for call in (lambda: app_svc.publish(context, plan_code=PLAN, expected_revision=1, preview_id=reg.preview_id,
                                             expected_source_digest=reg.source_digest, reason="x", request_id="am-1"),
                     lambda: app_svc.register_preview(context, workbook=source_workbook(), source_file=SRC_FILE,
                                                      reason="x", request_id="am-2"),
                     lambda: app_svc.set_assignment(context, vehicle_id="VEH-1046", plan_code=None,
                                                    expected_version=0, reason="x", request_id="am-3")):
            try:
                await call()
                writes.add("WROTE")
            except ApiError as exc:
                writes.add((exc.status_code, exc.code))
        return context, read, writes

    denied = {(403, "PM_MASTER_AUTHORITY_UNPROVEN")}
    assert (await grant(am, MGR, employee(MGR), {"can_view": True, "can_manage_pm": True})).status_code == 200
    context, read, write = await outcome(MGR)
    assert authz.CAN_MANAGE_PM in context.capabilities and context.access.is_root
    assert (read, write) == ("READ", denied)  # can_manage_pm is E01 only, never Master authority
    await grant(am, MGR, employee(DRV1), {"can_manage_pm": True})
    assert (await outcome(DRV1))[1:] == (403, denied)
    await grant(am, MGR, employee(DRV1), {"can_view": True})
    assert (await outcome(DRV1))[1] == "READ"
    await grant(am, MGR, employee(DRV1), {"can_view": False})
    assert (await outcome(DRV1))[1:] == (403, denied)
    await grant(am, MGR, employee(MGR), {"can_move_personnel_department": True})
    await grant(am, MGR, employee(DRV1), {"can_view": True})
    moved = await http("POST", f"/api/v1/personnel/{P[DRV1]}/department-events", am, MGR, json={
        "operation": "TRANSFER", "department_id": MNT, "effective": {"mode": "NOW"},
        "expected_current_department_id": OPS, "reason_th": "ย้ายแผนก"})
    assert moved.status_code == 200, moved.text
    assert (await outcome(DRV1))[1:] == (403, denied)
    await delegate(am, MGR, OPM, OPS, ["can_view"])
    assert (await grant(am, OPM, employee(TECH1), {"can_view": True})).status_code == 403
    assert (await outcome(TECH1))[1:] == (403, denied)
    assert (await outcome(OPM))[2] == denied
    assert (await outcome(RESIGNED, "ADMIN"))[1:] == (403, denied)
    assert (await outcome("USR-UNKNOWN", "ADMIN"))[1:] == (403, denied)
    assert snapshot(master) == before  # no Master mutation by anyone


async def test_forged_master_publish_is_refused_even_with_every_legacy_capability() -> None:
    store, _, reg, _ = await published()
    before = snapshot(store)
    app_svc = PmMasterService(store)
    forged = ctx("dev-user", authz.ALL_CAPABILITIES | {"can_publish_pm_master", "can_manage_pm_master"},
                 roles=("ADMIN",), is_dev_auth=True)
    with pytest.raises(ApiError) as refused:  # a VALID proof does not substitute for authority
        await app_svc.publish(forged, plan_code=PLAN, expected_revision=1, preview_id=reg.preview_id,
                              expected_source_digest=reg.source_digest, reason="x", request_id="forged")
    assert (refused.value.code, refused.value.details["gate"]) == ("PM_MASTER_AUTHORITY_UNPROVEN", VAL_AM_GATE)
    assert "can_publish_pm_master" not in authz.ALL_CAPABILITIES  # no capability was invented
    assert snapshot(store) == before


# B1-14 / B1-15 ---------------------------------------------------------------------


async def test_b1_14_concurrent_publish_yields_one_effective_revision_and_one_event() -> None:
    store = PmMasterMockStore()
    svc = service(store)
    reg = await register(svc)
    await resolve_all(svc, reg)
    events_before = len(store.events)
    results = await asyncio.gather(*(publish(svc, reg, 0, reason=f"พร้อมกัน {n}") for n in range(5)),
                                   return_exceptions=True)
    wins = [r for r in results if not isinstance(r, Exception)]
    losses = [r for r in results if isinstance(r, ApiError)]
    assert len(wins) == 1 and len(losses) == 4
    assert {e.code for e in losses} == {"PM_MASTER_STALE_REVISION"}
    assert len(store.revisions[PLAN]) == 1 and len(store.events) == events_before + 1
    assert store.head(PLAN).revision_id == wins[0].revision.revision_id


async def test_b1_15_same_request_id_replays_and_a_different_payload_is_rejected() -> None:
    store = PmMasterMockStore()
    svc = service(store, vehicle_resolver=MockVehicleResolver(MockRepository()))
    reg = await register(svc)
    await resolve_all(svc, reg)
    first = await publish(svc, reg, 0, request_id="REQ-B1-1")
    again = await publish(svc, reg, 0, request_id="REQ-B1-1")
    assert again.replayed and again.revision == first.revision
    assert [e["kind"] for e in store.events].count("PUBLISH") == 1
    before = snapshot(store)
    with pytest.raises(ApiError) as reused:
        await publish(svc, reg, 0, request_id="REQ-B1-1", reason="เหตุผลอื่น")
    assert (reused.value.status_code, reused.value.code) == (409, "REQUEST_ID_REUSED")
    with pytest.raises(ApiError) as cross_op:
        await svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=PLAN, expected_version=0, reason="x",
                                 request_id="REQ-B1-1")
    assert cross_op.value.code == "REQUEST_ID_REUSED"
    assert snapshot(store) == before
    a1 = await svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=PLAN, expected_version=0, reason="x",
                                  request_id="REQ-B1-2")
    a2 = await svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=PLAN, expected_version=0, reason="x",
                                  request_id="REQ-B1-2")
    assert a2.replayed and a2.record == a1.record and len(store.assignments) == 1


# B1-16 (fail-closed expectation of RV-B1-03) -------------------------------------------


def reworded_workbook():
    """Rev 2 source: pointer 5 reworded in place, pointer 6 removed, new pointer 20
    carries pointer 6's exact text (a possible move OR a genuinely new task)."""
    wb = source_workbook()
    wb["source_pm_items"][0]["description_raw"] = "ตรวจและเติมน้ำมันเครื่อง (ล่าง)"
    wb["source_pm_items"][1] = sitem(DOC_LOW, 20, "A", "CARRIER", 2, "ทำความสะอาดไส้กรองอากาศ")
    return wb


async def test_b1_16_ambiguous_lineage_fails_closed_and_evidenced_lineage_keeps_the_chain() -> None:
    store, svc, _, _ = await published()
    reg2 = await register(svc, reworded_workbook())
    await resolve_all(svc, reg2)
    before = snapshot(store)
    with pytest.raises(ApiError) as ambiguous:
        await publish(svc, reg2, 1)
    assert ambiguous.value.code == "PM_MASTER_LINEAGE_UNRESOLVED"
    assert {(p["where"], p["issue"]) for p in ambiguous.value.details["problems"]} == {
        (f"{CARRIER_A}/{DOC_LOW}!{k}", "AMBIGUOUS_LINEAGE") for k in (5, 20)}
    assert snapshot(store) == before  # no revision, no audit residue
    decisions = [
        LineageDecision(set_key=CARRIER_A, item_key=f"{DOC_LOW}!5", predecessor_item_key=f"{DOC_LOW}!5",
                        evidence="ถ้อยคำแก้ไขในแถวเดิม ยืนยันจากเอกสารฉบับใหม่ หน้า 2"),
        LineageDecision(set_key=CARRIER_A, item_key=f"{DOC_LOW}!20", predecessor_item_key=f"{DOC_LOW}!6",
                        evidence="ย้ายแถวเดิม 6 ไปแถว 20 ตามบันทึกการปรับเอกสาร")]
    outcome = await publish(svc, reg2, 1, lineage=decisions)
    rows_ = {(r["set_key"], r["item_key"]): r for r in outcome.diff["items"]}
    assert rows_[(CARRIER_A, f"{DOC_LOW}!5")]["status"] == LINEAGE_CONTINUES
    assert (rows_[(CARRIER_A, f"{DOC_LOW}!20")]["status"],
            rows_[(CARRIER_A, f"{DOC_LOW}!20")]["previous_item_key"]) == (LINEAGE_CONTINUES, f"{DOC_LOW}!6")
    assert rows_[(CRANE_A, f"{DOC_UP}!5")]["status"] == LINEAGE_RETAINED
    assert (CARRIER_A, f"{DOC_LOW}!6") not in rows_  # continued, therefore not REMOVED
    assert outcome.revision.lineage == tuple(decisions)  # the audited resolution travels with the revision


# B1-17 -------------------------------------------------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_b1_17_strict_mock_isolation() -> None:
    new_modules = {"app.domain.pm_master", "app.domain.pm_source_preview"}
    for name in ("pm_master.py", "pm_source_preview.py"):
        imported = _imports(BACKEND / "app" / "domain" / name)
        assert not any(m.startswith(("app.repositories", "app.api", "gspread", "google", "httpx", "requests",
                                     "openpyxl", "urllib", "socket")) for m in imported), imported
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name not in ("pm_master.py", "pm_source_preview.py"):
            assert not (_imports(path) & new_modules), path
    from app.main import create_app
    paths = {getattr(r, "path", "") for r in create_app().routes}
    assert not any("master" in p and "/pm" in p for p in paths)  # no write (or read) endpoint exposed
    tracked_workbooks = [p for p in REPO_ROOT.rglob("*") if p.suffix.lower() in {".xlsx", ".xlsm", ".xls"}
                         and "node_modules" not in p.parts]
    assert tracked_workbooks == []  # no source workbook uploaded or committed
    assert set(KNOWN_SHEETS) >= {"source_pm_cycles", "source_pm_items", "vehicle_pm_mapping"}


# B1-18 + additional negative checks ------------------------------------------------------


async def test_b1_18_current_pm_r3_am_v2_contract_points_are_preserved(client) -> None:
    retired = await client.get("/api/v1/pm/work-orders/my-work")
    assert (retired.status_code, retired.json()["error"]["code"]) == (410, "LEGACY_ASSIGNMENT_RETIRED")
    assert [p.pm_plan_id for p in seed_data.SEED_PM_PLANS] == ["PMP-0001"]
    assert [r.revision_id for r in seed_data.SEED_PM_TASK_REVISIONS] == ["PMREV-0001"]
    assert [t.pm_task_id for t in seed_data.SEED_PM_TASKS["PMREV-0001"]] == ["PMT-0001", "PMT-0002", "PMT-0003"]
    active = (await client.get("/api/v1/pm/plans/PMP-0001/active-revision")).json()
    assert active["revision"]["revision_id"] == "PMREV-0001" and len(active["tasks"]) == 3


def test_negative_checks_no_e01_due_safety_or_outcome_changes() -> None:
    assert {s.value for s in PmWorkOrderStatus} == {"OPEN", "CLOSED"}  # no E01 states invented
    assert PmWorkResult.model_fields["completed"].annotation is bool  # legacy outcome untouched
    source = (BACKEND / "app" / "domain" / "pm_master.py").read_text(encoding="utf-8") + (
        BACKEND / "app" / "domain" / "pm_source_preview.py").read_text(encoding="utf-8")
    for forbidden in ("due_at", "next_due_at", "overdue", "safety_critical", "warning_threshold", "advisory_percent",
                      "technician_v2_enabled", "part_code", "part_quantity", "device_id", "installation_id"):
        assert forbidden not in source.lower(), forbidden
    fields = set(MasterSet.model_fields) | set(MasterItem.model_fields)
    assert not fields & {"due_status", "safety_critical", "warning_threshold", "part_quantity", "completed",
                         "performed", "check", "clean", "change_fill", "device_id"}


def test_negative_missing_meter_values_are_unknown_never_zero() -> None:
    p = preview_source(synthetic_workbook(), source_file=SOURCE)
    blank = [e for e in p.ledger if e.row_or_key == "row:11" and e.sheet == "source_pm_cycles"]
    assert [(e.column, e.issue) for e in blank] == [("interval_value", "MISSING_REQUIRED_VALUE")]
    assert not any(s.set_code in {"SET-BLANK", "SET-ZERO"} for s in p.sets)  # neither becomes 0
    src = preview_maintenance_source(source_workbook(), source_file=SRC_FILE)
    assert [e.issue for e in src.ledger if e.row_or_key == "source_pm_cycles!row:16"] == ["MISSING_REQUIRED_VALUE"]
    assert not any(s.set_code in {"BLANK", "ZERO"} for s in (*src.sets, *src.pending_sets))
    with pytest.raises(Exception):
        MasterSet(model_variant="v", section="CARRIER", set_code="s", meter_type=PmTriggerType.ENGINE_HOUR,
                  interval_value=None, interval_unit="HOUR")  # null is not silently a number
    from app.domain.pm import PmPlanStatus
    assert PmPlanStatus.model_fields["due_status"].default == "UNKNOWN"  # runtime still reports UNKNOWN


# ===================================================================================
# R4-B1 correction batch: B1-FIX-01 .. B1-FIX-08
# ===================================================================================


def test_b1_fix_01_source_shaped_columns_map_explicitly_with_raw_and_pointers() -> None:
    wb = source_workbook()
    frozen_input = copy.deepcopy(wb)
    p = preview_maintenance_source(wb, source_file=SRC_FILE)
    assert wb == frozen_input and p.schema == SCHEMA_MAINTENANCE
    assert set(source_workbook()["source_pm_cycles"][0]) == set(SOURCE_COLUMNS["source_pm_cycles"])
    assert set(source_workbook()["source_pm_items"][0]) == set(SOURCE_COLUMNS["source_pm_items"])
    km = next(s for s in p.sets if s.set_code == "KM1")
    # Set identity is the raw source text; the document comes from the mapping row, not from source_sheet
    assert (km.plan_code, km.model_variant, km.section, km.set_code, km.source_doc) == (
        PLAN, "SYN-M1", "CARRIER", "KM1", DOC_LOW)
    assert (km.meter_type, km.driving_component, km.interval_unit, km.meter_basis) == (
        "ODOMETER", "VEHICLE", "KM", "UNIT_KM_VEHICLE_ODOMETER")
    assert km.source_row == "source_pm_cycles!row:6" and ("group_rule", "INDEPENDENT_GROUP") in km.raw
    # HOUR on an UNKNOWN configuration is never guessed: held back with a REVIEW entry on the source field
    m7 = next(s for s in p.pending_sets if s.model_variant == "SYN-M7")
    assert (m7.meter_type, m7.driving_component, m7.meter_basis) == ("", "", "REVIEW")
    meter_entry = next(e for e in p.ledger if e.entry_id in m7.blocking_entry_ids)
    assert (meter_entry.column, meter_entry.raw_reference, meter_entry.issue) == (
        "interval_unit", "HOUR", ISSUE_METER_UNRESOLVED)
    # the item key is the document source pointer only, raw form cells kept verbatim and uninterpreted
    tyre = next(i for i in p.items if i.task_text == "ตรวจลมยาง")
    assert (tyre.item_key, tyre.source_row, tyre.linked_set_identities) == (
        f"{DOC_LOW}!9", "source_pm_items!row:7", (f"{PLAN}|{KM_SET}",))
    assert {("check_cell_raw", "35"), ("clean_cell_raw", "35"), ("change_fill_cell_raw", "35")} <= set(tyre.raw)
    assert all(m.plan_code in ("", PLAN, PLAN_B) for m in p.mapping_candidates)  # raw source_plan, not re-coded
    # the normalized synthetic contract is NOT accepted as source-shaped input (no conflation)
    conflated = preview_maintenance_source(synthetic_workbook(), source_file=SRC_FILE)
    assert conflated.sets == () and conflated.items == () and conflated.pending_sets == ()
    assert {e.issue for e in conflated.ledger if e.sheet == "source_pm_cycles"} >= {"MISSING_REQUIRED_VALUE"}


def test_b1_fix_02_all_six_source_tabs_are_accounted_and_real_reconciliation_is_unverified() -> None:
    p = preview_maintenance_source(source_workbook(), source_file=SRC_FILE)
    got = {a.sheet: (a.total, a.accepted, a.review, a.excluded) for a in p.accounts}
    assert got == {"source_pm_standard": (9, 7, 0, 2), "source_pm_cycles": (20, 6, 14, 0),
                   "source_pm_items": (17, 8, 9, 0), "vehicle_pm_mapping": (13, 11, 2, 0),
                   "replacement_policy": (2, 0, 0, 2), "replacement_items": (1, 0, 0, 1)}
    assert all(a.balanced for a in p.accounts)
    for sheet, (total, accepted, _, _) in got.items():
        flagged = {e.row_or_key for e in p.ledger if e.sheet == sheet and e.action != ACCEPT}
        assert len(flagged) == total - accepted  # every non-accepted row has a ledger reason
    assert {(e.raw_reference, e.issue) for e in p.ledger if e.sheet == "source_pm_standard" and e.action == EXCLUDE} == {
        ("EMPTY_TEMPLATE", "SOURCE_EMPTY_TEMPLATE"), ("CANCELLED", "SOURCE_CANCELLED")}
    assert [e.issue for e in p.ledger if e.sheet == "SYNTH_UNRELATED_TAB"] == ["SHEET_OUT_OF_B1_SCOPE"]
    assert preview_maintenance_source(source_workbook(), source_file=SRC_FILE).digest == p.digest
    # The real workbook is not in this environment: 260 / 1,146 / 49 / 235 / 13 / 38 stays UNVERIFIED.
    assert not any(REPO_ROOT.rglob("MAINTENANCE*.xlsx"))


async def test_b1_fix_03_publish_requires_a_bound_verified_proof_with_no_residue() -> None:
    import inspect
    params = set(inspect.signature(PmMasterService.publish).parameters)
    assert {"sets", "open_reviews", "resolutions"}.isdisjoint(params)  # no caller-built candidate, no bypass
    assert {"preview_id", "expected_source_digest"} <= params
    store = PmMasterMockStore()
    svc = service(store)
    reg = await register(svc)

    async def refused(code, issue=None, **kw):
        before = snapshot(store)
        args = {"preview_id": reg.preview_id, "expected_source_digest": reg.source_digest} | kw
        with pytest.raises(ApiError) as exc:
            await svc.publish(ctx(), plan_code=PLAN, expected_revision=0, reason="x", request_id=str(uuid.uuid4()),
                              **args)
        assert exc.value.code == code
        if issue:
            assert issue in str(exc.value.details)
        assert snapshot(store) == before

    await refused("PM_MASTER_VALIDATION_FAILED", "UNRESOLVED_REVIEW")           # unresolved
    await refused("PM_MASTER_PUBLISH_PROOF_INVALID", "PREVIEW_NOT_FOUND", preview_id="PMPV-forged")  # forged
    await refused("PM_MASTER_PUBLISH_PROOF_INVALID", "DIGEST_MISMATCH", expected_source_digest="0" * 64)
    await resolve_all(svc, reg)
    reg2 = await register(svc, with_cycle_value(0, "510"))                        # a newer source preview
    await refused("PM_MASTER_PUBLISH_PROOF_INVALID", "PREVIEW_STALE")            # stale
    await refused("PM_MASTER_VALIDATION_FAILED", "UNRESOLVED_REVIEW", preview_id=reg2.preview_id,
                  expected_source_digest=reg2.source_digest)  # reviews of another preview never count
    meter = next(e for e in reg2.preview.ledger if e.issue == ISSUE_METER_UNRESOLVED)
    dup = next(e for e in reg2.preview.ledger if e.issue == "DUPLICATE_SET_IDENTITY")
    note35 = next(e for e in reg2.preview.ledger if e.issue == NOTE_RAW_35)
    bad_reviews = [
        ({"entry_id": "PMLE-forged", "outcome": OUTCOME_EXCLUDE_ROW}, "ENTRY_NOT_FOUND"),
        ({"entry_id": note35.entry_id, "outcome": OUTCOME_RETAIN_RAW}, "ENTRY_NOT_FOUND"),  # notes need no review
        ({"entry_id": meter.entry_id, "outcome": OUTCOME_EXCLUDE_ROW, "evidence": "ok"}, "EVIDENCE_NOT_SUBSTANTIVE"),
        ({"entry_id": dup.entry_id, "outcome": OUTCOME_RETAIN_RAW}, "OUTCOME_NOT_ALLOWED"),
        ({"entry_id": next(e for e in reg2.preview.ledger if e.issue == ISSUE_RAW_35).entry_id,
          "outcome": OUTCOME_RETAIN_RAW}, "OUTCOME_NOT_ALLOWED"),
        ({"entry_id": meter.entry_id, "outcome": OUTCOME_RESOLVE_METER,
          "values": {"meter_type": "ENGINE_HOUR", "driving_component": "PTO"}}, "INVALID_METER_RESOLUTION"),
        ({"entry_id": meter.entry_id, "outcome": OUTCOME_RESOLVE_METER,
          "values": {"meter_type": "CALENDAR", "driving_component": "VEHICLE"}}, "INVALID_METER_RESOLUTION"),
        ({"entry_id": meter.entry_id, "outcome": OUTCOME_EXCLUDE_ROW, "expected_source_digest": reg.source_digest},
         "DIGEST_MISMATCH"),
    ]
    for kwargs, issue in bad_reviews:
        before = snapshot(store)
        args = {"preview_id": reg2.preview_id, "expected_source_digest": reg2.source_digest, "evidence": EVIDENCE,
                "request_id": str(uuid.uuid4())} | kwargs
        with pytest.raises(ApiError) as exc:
            await svc.record_review(ctx(), **args)
        assert exc.value.details["issue"] == issue
        assert snapshot(store) == before
    first = await svc.record_review(ctx(), preview_id=reg2.preview_id, expected_source_digest=reg2.source_digest,
                                    entry_id=dup.entry_id, outcome=OUTCOME_EXCLUDE_ROW, evidence=EVIDENCE,
                                    request_id=str(uuid.uuid4()))
    with pytest.raises(ApiError) as twice:
        await svc.record_review(ctx(), preview_id=reg2.preview_id, expected_source_digest=reg2.source_digest,
                                entry_id=dup.entry_id, outcome=OUTCOME_EXCLUDE_ROW, evidence=EVIDENCE,
                                request_id=str(uuid.uuid4()))
    assert twice.value.code == "PM_MASTER_REVIEW_ALREADY_RESOLVED"
    assert isinstance(first, ReviewResolution) and first.reviewer == PUBLISHER
    await resolve_all(svc, reg2, skip={dup.entry_id})
    app = PmMasterService(store)
    before = snapshot(store)
    for call in (lambda: app.register_preview(ctx(), workbook=source_workbook(), source_file=SRC_FILE, reason="x",
                                              request_id="r"),
                 lambda: app.record_review(ctx(), preview_id=reg2.preview_id, expected_source_digest=reg2.source_digest,
                                           entry_id=meter.entry_id, outcome=OUTCOME_EXCLUDE_ROW, evidence=EVIDENCE,
                                           request_id="r2"),
                 lambda: app.publish(ctx(), plan_code=PLAN, expected_revision=0, preview_id=reg2.preview_id,
                                     expected_source_digest=reg2.source_digest, reason="x", request_id="r3")):
        with pytest.raises(ApiError) as denied:
            await call()
        assert denied.value.code == "PM_MASTER_AUTHORITY_UNPROVEN"
    assert snapshot(store) == before
    assert (await publish(svc, reg2, 0)).revision.preview_id == reg2.preview_id  # the bound proof does publish


async def test_b1_fix_04_invalid_or_duplicate_supersession_fails_closed() -> None:
    store, svc, _, _ = await published()
    reg2 = await register(svc, reworded_workbook())
    await resolve_all(svc, reg2)
    good = LineageDecision(set_key=CARRIER_A, item_key=f"{DOC_LOW}!5", predecessor_item_key=f"{DOC_LOW}!5",
                           evidence="ถ้อยคำแก้ไขในแถวเดิม ยืนยันจากเอกสารฉบับใหม่")
    cases = {
        "PREDECESSOR_NOT_IN_PREVIOUS_SET": [good, good.model_copy(update={
            "item_key": f"{DOC_LOW}!20", "predecessor_item_key": f"{DOC_LOW}!99"})],
        "PREDECESSOR_NOT_IN_PREVIOUS_SET ": [good, good.model_copy(update={
            "item_key": f"{DOC_LOW}!20", "predecessor_item_key": f"{DOC_UP}!5"})],  # lives in the CRANE Set
        "PREDECESSOR_CONTINUED_TWICE": [good, good.model_copy(update={"item_key": f"{DOC_LOW}!20"})],
        "DUPLICATE_LINEAGE_DECISION": [good, good, good.model_copy(update={"item_key": f"{DOC_LOW}!20",
                                                                           "predecessor_item_key": ""})],
        "LINEAGE_DECISION_UNKNOWN_ITEM": [good, good.model_copy(update={"item_key": f"{DOC_LOW}!77",
                                                                        "predecessor_item_key": ""})],
        "LINEAGE_EVIDENCE_NOT_SUBSTANTIVE": [good, good.model_copy(update={
            "item_key": f"{DOC_LOW}!20", "predecessor_item_key": f"{DOC_LOW}!6", "evidence": "same"})],
        "LINEAGE_WITHOUT_PREVIOUS_SET": [good, good.model_copy(update={"set_key": "SYN-M9|CARRIER|NEW"})],
    }
    before = snapshot(store)
    for issue, decisions in cases.items():
        with pytest.raises(ApiError) as exc:
            await publish(svc, reg2, 1, lineage=decisions)
        assert issue.strip() in {p["issue"] for p in exc.value.details["problems"]}, (issue, exc.value.details)
        assert snapshot(store) == before
    # A predecessor that stays RETAINED cannot also be continued by another item.
    kept_store, kept_svc, _, _ = await published()
    kept = source_workbook()
    kept["source_pm_items"].append(sitem(DOC_LOW, 20, "A", "CARRIER", 6, "ตรวจสายพาน"))
    kept_reg = await register(kept_svc, kept)
    await resolve_all(kept_svc, kept_reg)
    kept_before = snapshot(kept_store)
    with pytest.raises(ApiError) as retained:
        await publish(kept_svc, kept_reg, 1, lineage=[LineageDecision(
            set_key=CARRIER_A, item_key=f"{DOC_LOW}!20", predecessor_item_key=f"{DOC_LOW}!6",
            evidence="อ้างว่าแทนรายการเดิมแถว 6 (ทดสอบ)")])
    assert "PREDECESSOR_STILL_RETAINED" in {p["issue"] for p in retained.value.details["problems"]}
    assert snapshot(kept_store) == kept_before
    # A first revision cannot carry fabricated lineage either.
    fresh = PmMasterMockStore()
    fsvc = service(fresh)
    freg = await register(fsvc)
    await resolve_all(fsvc, freg)
    with pytest.raises(ApiError) as first:
        await publish(fsvc, freg, 0, lineage=[good])
    assert "LINEAGE_WITHOUT_PREVIOUS_SET" in {p["issue"] for p in first.value.details["problems"]}
    assert fresh.revisions == {}
    # Valid: continuing in place plus an evidenced DECLARED_NEW item keeps a stable chain.
    ok = await publish(svc, reg2, 1, lineage=[good, good.model_copy(update={"item_key": f"{DOC_LOW}!20",
                                                                            "predecessor_item_key": ""})])
    statuses = {(r["set_key"], r["item_key"]): r["status"] for r in ok.diff["items"]}
    assert statuses[(CARRIER_A, f"{DOC_LOW}!20")] == LINEAGE_DECLARED_NEW
    assert statuses[(CARRIER_A, f"{DOC_LOW}!6")] == LINEAGE_REMOVED
    assert statuses[(CARRIER_A, f"{DOC_LOW}!5")] == LINEAGE_CONTINUES
    assert LINEAGE_AMBIGUOUS not in statuses.values() and LINEAGE_NEW not in statuses.values()


async def test_b1_fix_05_reading_the_audit_cannot_change_history_or_replay() -> None:
    store, svc, reg, rev = await published()
    events_before = tuple(dict(e) for e in store.events)
    view = svc.audit(ctx())
    with pytest.raises(TypeError):
        view[-1]["kind"] = "FORGED"  # read-only mapping
    with pytest.raises(TypeError):
        store.events[-1]["request_fingerprint"] = "x"  # stored events are read-only too
    assert tuple(dict(e) for e in svc.audit(ctx())) == events_before
    replay = await publish(svc, reg, 0, request_id=rev.request_id)
    assert replay.replayed and replay.revision == rev  # replay evidence intact
    assert tuple(dict(e) for e in store.events) == events_before
    with pytest.raises(Exception):
        svc.audit(ctx(capabilities=frozenset()))  # no can_view, no audit


async def test_b1_fix_06_vehicle_resolver_and_assembly_guards_fail_closed() -> None:
    store, no_resolver_svc, _, _ = await published()
    before = snapshot(store)
    with pytest.raises(ApiError) as missing:
        await no_resolver_svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=PLAN, expected_version=0,
                                             reason="x", request_id=str(uuid.uuid4()))
    assert missing.value.code == "PM_MASTER_VEHICLE_RESOLVER_REQUIRED"

    class FakeRepository:  # not the Mock repository
        async def get_vehicle(self, vehicle_id):
            return object()

    with pytest.raises(ApiError) as not_mock:
        MockVehicleResolver(FakeRepository())
    assert not_mock.value.code == "PM_MASTER_VEHICLE_RESOLVER_NOT_MOCK"
    duck = service(store, vehicle_resolver=FakeRepository())  # duck-typed resolver is not accepted
    with pytest.raises(ApiError) as ducked:
        await duck.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=PLAN, expected_version=0, reason="x",
                                  request_id=str(uuid.uuid4()))
    assert ducked.value.code == "PM_MASTER_VEHICLE_RESOLVER_REQUIRED"
    repo = MockRepository()
    svc = service(store, vehicle_resolver=MockVehicleResolver(repo))
    for kwargs, code_ in (({"vehicle_id": "SYN-VEH-01"}, "VEHICLE_NOT_FOUND"),   # a source candidate, not a vehicle
                          ({"vehicle_id": ""}, "VEHICLE_NOT_FOUND"),
                          ({"vehicle_id": "VEH-1046", "assembly": "UPPER"}, "VALIDATION_ERROR"),
                          ({"vehicle_id": "VEH-1046", "assembly": "CRANE"}, "PM_MASTER_ASSEMBLY_NOT_ON_VEHICLE")):
        with pytest.raises(ApiError) as exc:
            await svc.set_assignment(ctx(), plan_code=PLAN, expected_version=0, reason="x",
                                     request_id=str(uuid.uuid4()), **kwargs)
        assert exc.value.code == code_, kwargs
    assert snapshot(store) == before
    assert await repo.get_vehicle("SYN-VEH-01") is None  # nothing auto-created
    ok = await svc.set_assignment(ctx(), vehicle_id="VEH-1047", assembly="CRANE", plan_code=PLAN, expected_version=0,
                                  reason="เครนมีเครื่องยนต์ส่วนบน", request_id=str(uuid.uuid4()))
    assert ok.record.assembly == "CRANE"


async def test_b1_fix_07_runtime_is_untouched_and_no_plan_vehicles_stay_unassigned() -> None:
    repo = MockRepository()
    plan_before = (await repo.get_pm_plan("PMP-0001")).model_dump()
    active_before = (await repo.get_active_pm_task_revision("PMP-0001")).model_dump()
    store, svc, reg, _ = await published(resolver=MockVehicleResolver(repo))
    assert (await repo.get_pm_plan("PMP-0001")).model_dump() == plan_before
    assert (await repo.get_active_pm_task_revision("PMP-0001")).model_dump() == active_before
    assert await repo.get_pm_plan(PLAN) is None  # the Master never becomes a runtime plan
    no_plan = [m.vehicle_ref for m in reg.preview.mapping_candidates if m.status == "PENDING_PM_PLAN"]
    assert no_plan == ["SYN-VEH-09", "SYN-VEH-10"] and store.assignments == ()
    assert all(svc.resolve_plan(ctx(), v).source == "ABSENT" for v in no_plan)
    assert {e["kind"] for e in store.events} == {"PREVIEW_REGISTERED", "REVIEW_RESOLVED", "PUBLISH"}


def test_b1_fix_08_handoff_report_states_the_verified_status() -> None:
    report = (REPO_ROOT / "docs" / "phase-results" / "r4-b1-pm-master-foundation-mock-result.md").read_text(
        encoding="utf-8")
    addendum = report[report.index("## Addendum"):]
    assert "90d4d0765fc9eee51206db8b60d88c94bed29e6b" in addendum
    assert "UNCOMMITTED" in addendum and "not committed" in addendum.lower()
    assert "FULL REAL HEADER INVENTORY UNVERIFIED" in addendum
    assert "260 / 1,146 / 49 / 235 / 13 / 38" in addendum and "UNVERIFIED" in addendum
    assert "VAL-AM" in addendum and "OPEN" in addendum
    for finding in ("RV-B1-01", "RV-B1-02", "RV-B1-03", "RV-B1-04", "RV-B1-05", "RV-B1-06",
                    "RV-B1-R2-01", "RV-B1-R2-02", "RV-B1-R2-03", "RV-B1-R2-04"):
        assert finding in addendum, finding


# ===================================================================================
# Independent review round 2: RV-B1-R2-01 .. RV-B1-R2-04
# ===================================================================================


async def test_r2_01_plan_and_document_namespaces_are_joined_only_by_mapping_evidence() -> None:
    wb = source_workbook()
    plan_tabs = {r["source_sheet"] for r in wb["source_pm_cycles"]}
    item_docs = {r["source_sheet"] for r in wb["source_pm_items"]}
    assert plan_tabs.isdisjoint(item_docs)  # like the real workbook: zero common source_sheet values
    _, _, _, rev = await published()
    sets = {s.set_key: s for s in rev.sets}
    assert {k: s.source_doc for k, s in sets.items()} == {
        CARRIER_A: DOC_LOW, CRANE_A: DOC_UP, M2_A: DOC_M2, M3_A: DOC_M3, M7_A: DOC_M2, KM_SET: DOC_LOW}
    p = preview_maintenance_source(wb, source_file=SRC_FILE)
    issues = {(e.row_or_key, e.issue) for e in p.ledger}
    assert {("source_pm_cycles!row:9", "SET_NOT_MAPPED"),            # no mapping evidence for the model
            ("source_pm_cycles!row:10", "SET_DOCUMENT_AMBIGUOUS"),   # mapping rows name two documents
            ("source_pm_cycles!row:11", "SET_NOT_MAPPED"),           # label differs; no alias approved
            ("source_pm_items!row:12", "DOCUMENT_NOT_IN_STANDARDS"),
            ("source_pm_items!row:13", "DOCUMENT_NOT_CURRENT"),
            ("source_pm_items!row:15", "ITEM_NOT_LINKED"),
            ("source_pm_items!row:17", "ITEM_NOT_LINKED")} <= issues
    # An approved, evidenced MODEL alias (and a PLAN alias) are the only way to bridge a differing label.
    aliased = preview_maintenance_source(wb, source_file=SRC_FILE, approved_aliases=[M4_ALIAS])
    m4 = next(s for s in aliased.sets if s.model_variant == "SYN-M4")
    assert (m4.source_doc, m4.source_row) == (DOC_M4, "source_pm_cycles!row:11")
    assert next(i for i in aliased.items if i.item_key == f"{DOC_M4}!5").linked_set_identities == (m4.set_identity,)
    assert aliased.digest != p.digest and aliased.approved_aliases == (M4_ALIAS,)
    renamed = source_workbook()
    for r in renamed["source_pm_cycles"]:
        if r["source_sheet"] == PLAN_B:
            r["source_sheet"] = "SYN PM Plan2 (tab)"
    assert not any(s.plan_code.startswith("SYN PM Plan2") for s in preview_maintenance_source(
        renamed, source_file=SRC_FILE).sets)
    bridged = preview_maintenance_source(renamed, source_file=SRC_FILE, approved_aliases=[
        ("PLAN", "SYN PM Plan2 (tab)", PLAN_B, "ชื่อแท็บแผนตรงกับ source_plan ยืนยันโดยผู้ตรวจทาน")])
    assert any(s.plan_code == PLAN_B for s in bridged.sets)
    # Invalid aliases are refused at registration with no residue.
    store = PmMasterMockStore()
    svc = service(store)
    for bad in ([("MODEL", "SYN-M4 (corr)", "SYN-M4", "ok")],
                [M4_ALIAS, ("MODEL", "SYN-M4 (corr)", "SYN-M2", "อีกชื่อหนึ่งที่ขัดแย้งกัน (synthetic)")],
                [("DOCUMENT", "a", "b", "ชนิดที่ไม่อนุญาตให้จับคู่ (synthetic)")]):
        with pytest.raises(ApiError) as exc:
            await register(svc, aliases=bad)
        assert exc.value.code == "PM_MASTER_ALIAS_INVALID"
    assert snapshot(store) == snapshot(PmMasterMockStore())


async def test_r2_02_single_dual_and_unknown_topology_without_fabricated_engines() -> None:
    p = preview_maintenance_source(source_workbook(), source_file=SRC_FILE)
    topo = Counter(m.topology for m in p.mapping_candidates)
    assert topo == {"DUAL": 2, "SINGLE": 6, "UNKNOWN": 3}
    _, _, _, rev = await published()
    sets = {s.set_key: s for s in rev.sets}
    assert (sets[CARRIER_A].topology, sets[CARRIER_A].meter_basis) == ("DUAL", "OWNER_RULE_DUAL_CARRIER_ENGINE")
    assert (sets[CRANE_A].topology, sets[CRANE_A].meter_basis) == ("DUAL", "OWNER_RULE_DUAL_CRANE_ENGINE")
    for key in (M2_A, M3_A):  # NOT_SEPARATED_IN_PLAN = one engine; no CRANE_ENGINE is ever invented
        assert (sets[key].topology, sets[key].driving_component, sets[key].meter_basis) == (
            "SINGLE", ComponentRole.CARRIER_ENGINE, "OWNER_RULE_SINGLE_ENGINE")
    assert not any(s.driving_component == ComponentRole.CRANE_ENGINE for s in rev.sets if s.topology == "SINGLE")
    assert (sets[M7_A].topology, sets[M7_A].meter_basis) == ("UNKNOWN", "REVIEW_RESOLUTION")  # explicit review only
    assert sets[KM_SET].driving_component == ComponentRole.VEHICLE  # one vehicle odometer, not per engine
    issues = {(e.row_or_key, e.issue) for e in p.ledger}
    assert {("source_pm_cycles!row:7", "SECTION_CONFIGURATION_CONFLICT"),   # single model planned with CARRIER
            ("source_pm_cycles!row:8", "SECTION_CONFIGURATION_CONFLICT"),   # dual model planned not-separated
            ("source_pm_cycles!row:19", "UNKNOWN_SECTION")} <= issues      # form label used on a plan
    unknown = [m for m in p.mapping_candidates if m.status == "PENDING_PM_PLAN"]
    assert {(m.topology, m.plan_code) for m in unknown} == {("UNKNOWN", "")}  # stays unknown and unassigned
    # Reference reconciliation (130 single / 53 dual / 52 unknown, 260 cycles, 1,146 items) is reported,
    # never faked: on synthetic input every metric is a MISMATCH, so real-source acceptance stays UNVERIFIED.
    rec = {metric: (expected, observed, status) for metric, expected, observed, status in reconcile_reference(p)}
    assert rec["source_pm_cycles.rows"] == (260, 20, "MISMATCH")
    assert rec["source_pm_items.rows"] == (1146, 17, "MISMATCH")
    assert rec["vehicle_pm_mapping.component_configuration.NOT_SEPARATED_IN_PLAN"][0] == 130
    assert rec["vehicle_pm_mapping.component_configuration.CARRIER_AND_CRANE"][0] == 53
    assert rec["vehicle_pm_mapping.component_configuration.UNKNOWN"][0] == 52
    assert rec["source_pm_cycles.component_section.NOT_SEPARATED_IN_PLAN"] == (80, 10, "MISMATCH")


async def test_r2_03_tasks_and_reviews_never_cross_model_set_section_or_document() -> None:
    _, _, _, rev = await published()
    assert item_keys(rev, M2_A) == [f"{DOC_M2}!5"]            # M2 and M3 share Set "A" ...
    assert item_keys(rev, M3_A) == [f"{DOC_M3}!5"]            # ... but each gets only its own document's tasks
    assert item_keys(rev, M7_A) == [f"{DOC_M2}!5"]            # shared only because the mapping names DOC_M2
    assert item_keys(rev, CARRIER_A) == [f"{DOC_LOW}!5", f"{DOC_LOW}!6"]
    assert item_keys(rev, CRANE_A) == [f"{DOC_UP}!5"]         # carrier tasks never reach the crane Set
    assert all(f"{DOC_LOW}!10" not in item_keys(rev, k) for k in (CARRIER_A, M2_A, M3_A))  # wrong section
    # An unresolved review of M3's task blocks the Plan even though M2's Set "A" is complete.
    store = PmMasterMockStore()
    svc = service(store)
    reg = await register(svc)
    m3_raw = next(e for e in reg.preview.ledger
                  if e.row_or_key == "source_pm_items!row:11" and e.action == REVIEW)
    assert (m3_raw.issue, m3_raw.plan_scope) == (ISSUE_RAW_35, (PLAN,))
    await resolve_all(svc, reg, skip={m3_raw.entry_id})
    with pytest.raises(ApiError) as blocked:
        await publish(svc, reg, 0)
    assert {p["entry_id"] for p in blocked.value.details["problems"]} == {m3_raw.entry_id}
    assert store.revisions == {}
    # No row blocks Plan 2 through its own scope: Plan 2 is held only by the global gate.
    assert not any(PLAN_B in e.plan_scope for e in reg.preview.ledger if e.action == REVIEW)
    await publish(svc, reg, 0, plan=PLAN_B)
    assert item_keys(store.head(PLAN_B), "SYN-M6|NOT_SEPARATED_IN_PLAN|GB") == [f"{DOC_B}!5"]


def test_r2_04_raw_35_is_field_aware_and_document_status_is_accounted_independently() -> None:
    p = preview_maintenance_source(source_workbook(), source_file=SRC_FILE)
    std = p.account("source_pm_standard")
    assert (std.accepted, std.review, std.excluded) == (7, 0, 2)  # every row carries an unrelated raw 35
    notes = [e for e in p.ledger if e.issue == NOTE_RAW_35]
    assert {(e.sheet, e.column) for e in notes} >= {("source_pm_standard", "source_google_sheet_url"),
                                                     ("source_pm_items", "check_cell_raw"),
                                                     ("source_pm_items", "clean_cell_raw"),
                                                     ("source_pm_items", "change_fill_cell_raw")}
    assert all(e.action == ACCEPT and e.raw_reference == "35" and e.plan_scope == () for e in notes)
    assert not p.unresolved_reviews().__contains__(notes[0])  # a note never blocks a publish
    # 35 where meaning IS used stays an auditable REVIEW, never a value
    review35 = {(e.sheet, e.column) for e in p.ledger if e.issue == ISSUE_RAW_35}
    assert review35 == {("source_pm_cycles", "group_rule"), ("source_pm_items", "description_raw"),
                        ("vehicle_pm_mapping", "mapping_status")}
    wb = source_workbook()
    wb["source_pm_standard"][0]["source_status"] = "35"
    status35 = preview_maintenance_source(wb, source_file=SRC_FILE)
    assert status35.account("source_pm_standard").review == 1
    assert ("source_pm_cycles!row:2", "DOCUMENT_UNDER_REVIEW") in {(e.row_or_key, e.issue) for e in status35.ledger}
    # the form cells reach the Master only as raw provenance; no action / part / quantity field exists
    item = next(i for i in p.items if i.item_key == f"{DOC_LOW}!5")
    assert dict(item.raw)["check_cell_raw"] == "35"
    assert not {"performed", "action", "part_quantity", "quantity", "part_code"} & set(MasterItem.model_fields)


REAL_WORKBOOK = os.environ.get("MAINTENANCE_XLSX", "")


@pytest.mark.skipif(not REAL_WORKBOOK, reason="MAINTENANCE.xlsx not supplied: real-source reconciliation UNVERIFIED")
def test_r2_real_workbook_read_only_reconciliation() -> None:
    """Opt-in, read-only: MAINTENANCE_XLSX=/path/MAINTENANCE.xlsx. Reads only the six
    B1 tabs into memory; prints no row; writes nothing."""
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.load_workbook(REAL_WORKBOOK, read_only=True, data_only=True)
    tabs: dict[str, list[dict[str, object]]] = {}
    try:
        for name in KNOWN_SHEETS:
            if name not in book.sheetnames:
                continue
            rows = book[name].iter_rows(values_only=True)
            header = [str(h).strip() if h is not None else "" for h in next(rows)]
            tabs[name] = [dict(zip(header, r)) for r in rows
                          if any(v is not None and str(v).strip() for v in r)]
    finally:
        book.close()
    for sheet, cols in SOURCE_COLUMNS.items():
        if tabs.get(sheet):
            assert set(cols) <= set(tabs[sheet][0]), (sheet, sorted(set(cols) - set(tabs[sheet][0])))
    p = preview_maintenance_source(tabs, source_file=Path(REAL_WORKBOOK).name)
    assert [m for m in reconcile_reference(p) if m[3] != "MATCH"] == []
    assert {r["source_sheet"] for r in tabs["source_pm_cycles"]}.isdisjoint(
        {r["source_sheet"] for r in tabs["source_pm_items"]})
    for item in (*p.items, *p.pending_items):  # no item ever crosses into a Set of another document
        for identity in item.linked_set_identities:
            linked = next(s for s in (*p.sets, *p.pending_sets) if s.set_identity == identity)
            assert linked.source_doc == item.source_doc


# ===================================================================================
# Independent review round 3: RV-B1-R3-01 / RV-B1-R3-02
# ===================================================================================


async def test_r3_01_every_review_has_a_conservative_scope_and_blocks_its_plan() -> None:
    p = preview_maintenance_source(source_workbook(), source_file=SRC_FILE)
    reviews = [e for e in p.ledger if e.action == REVIEW]
    assert reviews and all(e.plan_scope for e in reviews)  # no REVIEW is invisible to publish any more
    scope = {(e.row_or_key, e.issue): e.plan_scope for e in reviews}
    # malformed / unlinked Items in a document Plan 1's mapping references block Plan 1 ...
    for row in (13, 15, 16, 17):
        assert scope[(f"source_pm_items!row:{row}", "ITEM_NOT_LINKED")] == (PLAN,)
    # ... an Item whose document no verified mapping selects falls under the global gate ...
    assert scope[("source_pm_items!row:12", "ITEM_NOT_LINKED")] == (GLOBAL_PLAN_SCOPE,)
    # ... and malformed mapping rows block the Plan they name.
    assert scope[("vehicle_pm_mapping!row:13", "UNKNOWN_MAPPING_STATUS")] == (PLAN,)
    assert scope[("vehicle_pm_mapping!row:14", "UNKNOWN_COMPONENT_CONFIGURATION")] == (PLAN,)
    # Valid PENDING_PM_PLAN rows produce no finding at all, so they never block anything.
    assert not any(e.row_or_key in ("vehicle_pm_mapping!row:10", "vehicle_pm_mapping!row:11") for e in p.ledger)

    # A valid Set with 2 Items + a third malformed Item of the SAME mapped document: refused until resolved.
    store = PmMasterMockStore()
    svc = service(store)
    reg = await register(svc)
    third = [e for e in reg.preview.ledger if e.row_or_key == "source_pm_items!row:16" and e.action == REVIEW]
    await resolve_all(svc, reg, skip={e.entry_id for e in third})
    before = snapshot(store)
    with pytest.raises(ApiError) as refused:
        await publish(svc, reg, 0)
    assert {p_["entry_id"] for p_ in refused.value.details["problems"]} == {e.entry_id for e in third}
    assert snapshot(store) == before
    for e in third:  # an explicit, evidenced exclusion is the only way past it
        await svc.record_review(ctx(), preview_id=reg.preview_id, expected_source_digest=reg.source_digest,
                                entry_id=e.entry_id, outcome=OUTCOME_EXCLUDE_ROW, evidence=EVIDENCE,
                                request_id=str(uuid.uuid4()))
    rev = (await publish(svc, reg, 0)).revision
    assert item_keys(rev, CARRIER_A) == [f"{DOC_LOW}!5", f"{DOC_LOW}!6"]  # nothing invented for the excluded row

    # A malformed mapping row naming Plan 1 blocks Plan 1, while the unrelated Plan 2 may pass.
    store2 = PmMasterMockStore()
    svc2 = service(store2)
    reg2 = await register(svc2)
    bad_map = {e.entry_id for e in reg2.preview.ledger if e.row_or_key == "vehicle_pm_mapping!row:13"}
    await resolve_all(svc2, reg2, skip=bad_map)
    with pytest.raises(ApiError) as map_refused:
        await publish(svc2, reg2, 0)
    assert {p_["entry_id"] for p_ in map_refused.value.details["problems"]} == bad_map
    unrelated = PmMasterMockStore()
    usvc = service(unrelated)
    ureg = await register(usvc)
    await resolve_all(usvc, ureg, plan=PLAN_B)  # resolves only Plan 2's scope and the global gate
    assert any(e.unresolved and PLAN in e.plan_scope for e in ureg.preview.ledger)  # Plan 1 still open
    assert (await publish(usvc, ureg, 0, plan=PLAN_B)).revision.plan_code == PLAN_B
    with pytest.raises(ApiError):
        await publish(usvc, ureg, 0)  # ... and Plan 1 itself stays blocked

    # The global gate holds every Plan until its row is explicitly excluded.
    gated = PmMasterMockStore()
    gsvc = service(gated)
    greg = await register(gsvc)
    global_ids = {e.entry_id for e in greg.preview.ledger if GLOBAL_PLAN_SCOPE in e.plan_scope}
    await resolve_all(gsvc, greg, skip=global_ids)
    await resolve_all(gsvc, greg, plan=PLAN_B, skip=global_ids)
    for plan in (PLAN, PLAN_B):
        with pytest.raises(ApiError) as gate:
            await publish(gsvc, greg, 0, plan=plan)
        assert {p_["entry_id"] for p_ in gate.value.details["problems"]} == global_ids
    assert gated.revisions == {}

    # Not over-blocking: an Item of an UNSELECTED cancelled/blank template blocks nothing, while an
    # Item of an active document that no mapping selects cannot prove its scope -> global gate.
    wb = source_workbook()
    wb["source_pm_standard"].append(sstd("SYN-DOC-ORPHAN"))
    wb["source_pm_items"] += [sitem("SYN-DOC-X", 5, "A", "NOT_SEPARATED_IN_FORM", 1, "template row"),
                              sitem("SYN-DOC-ORPHAN", 5, "A", "NOT_SEPARATED_IN_FORM", 1, "orphan document")]
    extra = preview_maintenance_source(wb, source_file=SRC_FILE)
    rows = {e.row_or_key: e.plan_scope for e in extra.ledger if e.issue == "ITEM_NOT_LINKED"}
    assert rows["source_pm_items!row:19"] == ()                      # unselected EMPTY_TEMPLATE: non-blocking
    assert rows["source_pm_items!row:20"] == (GLOBAL_PLAN_SCOPE,)    # unprovable scope: fail closed


async def test_r3_02_semantic_raw_35_never_enters_an_active_master_field() -> None:
    assert allowed_outcomes(ISSUE_RAW_35) == (OUTCOME_EXCLUDE_ROW,)  # RETAIN is no longer a resolution
    store = PmMasterMockStore()
    svc = service(store)
    reg = await register(svc)
    group_35 = next(e for e in reg.preview.ledger if e.issue == ISSUE_RAW_35 and e.column == "group_rule")
    text_35 = next(e for e in reg.preview.ledger if e.issue == ISSUE_RAW_35 and e.column == "description_raw")
    before = snapshot(store)
    for entry in (group_35, text_35):
        with pytest.raises(ApiError) as refused:
            await svc.record_review(ctx(), preview_id=reg.preview_id, expected_source_digest=reg.source_digest,
                                    entry_id=entry.entry_id, outcome=OUTCOME_RETAIN_RAW, evidence=EVIDENCE,
                                    request_id=str(uuid.uuid4()))
        assert refused.value.details["issue"] == "OUTCOME_NOT_ALLOWED"
    assert snapshot(store) == before
    await resolve_all(svc, reg)
    rev = (await publish(svc, reg, 0)).revision
    active = [(s.model_variant, s.section, s.set_code, s.independent_group, s.source_doc) for s in rev.sets]
    active += [(i.task_text, i.method, i.standard) for s in rev.sets for i in s.items]
    assert all(value.strip() != "35" for fields in active for value in fields)
    assert K35_SET not in {s.set_key for s in rev.sets} and item_keys(rev, M3_A) == [f"{DOC_M3}!5"]
    # the raw source evidence is preserved: ledger, preview candidate raw cells and the resolution record
    assert (group_35.raw_reference, text_35.raw_reference) == ("35", "35")
    k35 = next(s for s in reg.preview.pending_sets if s.set_code == "K35")
    assert ("group_rule", "35") in k35.raw
    assert {r.entry_id: r.outcome for r in store.resolutions}[group_35.entry_id] == OUTCOME_EXCLUDE_ROW
    # provenance-only form cells may still carry 35 in `raw` (never projected) ...
    tyre = next(i for s in rev.sets for i in s.items if i.item_key == f"{DOC_LOW}!9")
    assert dict(tyre.raw)["check_cell_raw"] == "35"
    # ... while the validator refuses 35 in any projected field however it got there (defence in depth).
    poisoned = MasterSet(model_variant="SYN-M1", section="CARRIER", set_code="Z", meter_type=PmTriggerType.ODOMETER,
                         interval_value=1.0, interval_unit="KM", independent_group="35",
                         driving_component=ComponentRole.VEHICLE,
                         items=(MasterItem(item_key=f"{DOC_LOW}!35", sequence=1, task_text="35", method="ok",
                                           standard="35"),))
    issues = {(p_["where"], p_["issue"]) for p_ in validate_candidate(PLAN, [poisoned])}
    assert issues == {("SYN-M1|CARRIER|Z/independent_group", "SEMANTIC_RAW_35_IN_ACTIVE_FIELD"),
                      (f"SYN-M1|CARRIER|Z/{DOC_LOW}!35/task_text", "SEMANTIC_RAW_35_IN_ACTIVE_FIELD"),
                      (f"SYN-M1|CARRIER|Z/{DOC_LOW}!35/standard", "SEMANTIC_RAW_35_IN_ACTIVE_FIELD")}
