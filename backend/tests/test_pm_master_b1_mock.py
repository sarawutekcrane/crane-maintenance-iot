"""R4-B1 PM Master Foundation — Mock-only acceptance tests (B1-01 .. B1-18 plus the
additional negative checks of the B1 package).

Every source row here is SYNTHETIC (codes prefixed SYNTH-). The Owner's
MAINTENANCE.xlsx is NOT available in this environment, so the real-source row
counts (260 cycles / 1,146 items / 49 standards / 235 mappings / 13 + 38
replacement rows) remain UNVERIFIED; these tests prove the preview CONTRACT only.

Publish/assign semantics are exercised with `synthetic_test_only_authorizer`,
defined in this file and passed explicitly. The application's own authorizer
(`deny_unproven_master_authority`) refuses every actor (VAL-AM); see B1-11/B1-13.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import uuid
from pathlib import Path

import pytest

from app.context import RequestContext
from app.domain import authz
from app.domain.pm import PmTriggerType, PmWorkOrderStatus, PmWorkResult
from app.domain.pm_master import (
    ASSIGNED,
    LINEAGE_AMBIGUOUS,
    LINEAGE_NEW,
    LINEAGE_PROVEN,
    LINEAGE_REMOVED,
    LINEAGE_RETAINED,
    NONE,
    VAL_AM_GATE,
    MasterItem,
    MasterSet,
    PmMasterMockStore,
    PmMasterService,
    candidate_sets_from_preview,
    deny_unproven_master_authority,
)
from app.domain.pm_source_preview import ACCEPT, EXCLUDE, KNOWN_SHEETS, REVIEW, preview_source
from app.domain.vehicle_model import ComponentRole
from app.errors import ApiError
from app.repositories.mock import seed_data
from app.repositories.mock.repository import MockRepository

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
SOURCE = "SYNTHETIC_B1_FIXTURE.xlsx"
PLAN = "SYNTH-PLAN-A"
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


def cycle(plan=PLAN, variant="SYNTH-V1", section="CARRIER", set_code="SET-500", meter="ENGINE_HOUR",
          interval="500", unit="hour", doc="SYNTH-DOC-1", group="", **extra) -> dict[str, object]:
    return {"plan_code": plan, "model_variant": variant, "section": section, "set_code": set_code,
            "meter_type": meter, "interval_value": interval, "interval_unit": unit, "independent_group": group,
            "source_doc": doc, **extra}


def item(key, seq, text, plan=PLAN, variant="SYNTH-V1", section="CARRIER", set_code="SET-500", doc="SYNTH-DOC-1",
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
            {"vehicle_ref": "SYNTH-VEH-01", "plan_code": PLAN},
            {"vehicle_ref": "SYNTH-VEH-02", "plan_code": PLAN},
            {"vehicle_ref": "SYNTH-VEH-03", "plan_code": "SYNTH-PLAN-B"},
            {"vehicle_ref": "SYNTH-VEH-04", "plan_code": ""},                 # no Plan — valid, stays unassigned
            {"vehicle_ref": "SYNTH-VEH-05", "plan_code": ""},
            {"vehicle_ref": "SYNTH-VEH-06", "plan_code": "35"},               # REVIEW raw 35, never a Plan ID
        ],
        "replacement_policy": [{"policy": "SYNTH-P1"}, {"policy": "SYNTH-P2"}],
        "replacement_items": [{"item": "SYNTH-R1"}],
        "SYNTH_UNRELATED_TAB": [{"name": "private-looking row"}],
    }


def accepted_preview():
    """Preview of only the clean subset (every REVIEW row removed) — publishable."""
    wb = synthetic_workbook()
    wb["source_pm_cycles"] = wb["source_pm_cycles"][:4]
    wb["source_pm_items"] = wb["source_pm_items"][:6]
    wb["vehicle_pm_mapping"] = wb["vehicle_pm_mapping"][:5]
    return preview_source(wb, source_file=SOURCE)


def clean_sets(preview=None):
    preview = preview or accepted_preview()
    return candidate_sets_from_preview(preview, PLAN, driving_components={
        "SYNTH-V1|CARRIER|SET-KM": ComponentRole.VEHICLE})


def rows(preview, sheet, action=None):
    return [e for e in preview.ledger if e.sheet == sheet and (action is None or e.action == action)]


async def publish(svc, sets, n, *, request_id=None, reason="เผยแพร่ทดสอบ", context=None):
    return await svc.publish(context or ctx(), plan_code=PLAN, expected_revision=n, sets=sets, reason=reason,
                             request_id=request_id or str(uuid.uuid4()))


def snapshot(store: PmMasterMockStore):
    return copy.deepcopy((store.revisions, store.assignments, store.events))


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


# B1-06 / B1-07 / B1-08 ----------------------------------------------------------


async def test_b1_06_source_candidates_never_auto_assign_and_missing_plans_stay_valid() -> None:
    store = PmMasterMockStore()
    svc = service(store)
    p = preview_source(synthetic_workbook(), source_file=SOURCE)
    assert [(m.vehicle_ref, m.plan_code) for m in p.mapping_candidates] == [
        ("SYNTH-VEH-01", PLAN), ("SYNTH-VEH-02", PLAN), ("SYNTH-VEH-03", "SYNTH-PLAN-B"),
        ("SYNTH-VEH-04", ""), ("SYNTH-VEH-05", "")]
    await publish(svc, clean_sets(), 0)
    assert store.assignments == ()  # previewing and publishing assigned nothing
    for m in p.mapping_candidates:
        resolved = svc.resolve_plan(ctx(), m.vehicle_ref)
        assert (resolved.source, resolved.plan_code) == ("ABSENT", None)  # candidate != assigned
    acc = p.account("vehicle_pm_mapping")
    assert (acc.accepted, acc.review) == (5, 1)  # the 2 Plan-less rows are valid, not errors


async def test_b1_07_carrier_and_crane_are_assemblies_of_one_physical_vehicle() -> None:
    store, repo = PmMasterMockStore(), MockRepository()
    svc = service(store, repository=repo)
    sets = clean_sets()
    carrier = next(s for s in sets if s.set_key == "SYNTH-V1|CARRIER|SET-500")
    crane = next(s for s in sets if s.set_key == "SYNTH-V1|CRANE|SET-500")
    assert (carrier.driving_component, crane.driving_component) == (ComponentRole.CARRIER_ENGINE,
                                                                     ComponentRole.CRANE_ENGINE)
    assert (carrier.interval_value, crane.interval_value) == (500, 600)
    await publish(svc, sets, 0)
    vehicle_before = (await repo.get_vehicle("VEH-1047")).model_dump()
    for assembly in ("CARRIER", "CRANE"):
        await svc.set_assignment(ctx(), vehicle_id="VEH-1047", assembly=assembly, plan_code=PLAN,
                                 expected_version=0, reason="กำหนดแผนต่อชุดประกอบ", request_id=str(uuid.uuid4()))
    assert {(a.vehicle_id, a.assembly) for a in store.assignments} == {("VEH-1047", "CARRIER"), ("VEH-1047", "CRANE")}
    assert (await repo.get_vehicle("VEH-1047")).model_dump() == vehicle_before  # one identity, unchanged
    with pytest.raises(ApiError) as missing:
        await svc.set_assignment(ctx(), vehicle_id="SYNTH-NO-SUCH-VEHICLE", plan_code=PLAN, expected_version=0,
                                 reason="x", request_id=str(uuid.uuid4()))
    assert missing.value.code == "VEHICLE_NOT_FOUND"


def test_b1_08_same_plan_keeps_per_set_intervals_and_original_values() -> None:
    sets = {s.set_key: s for s in clean_sets()}
    assert {k: (s.meter_type, s.interval_value, s.interval_unit, s.raw_interval) for k, s in sets.items()} == {
        "SYNTH-V1|CARRIER|SET-500": (PmTriggerType.ENGINE_HOUR, 500, "hour", "500"),
        "SYNTH-V1|CRANE|SET-500": (PmTriggerType.ENGINE_HOUR, 600, "hour", "600"),
        "SYNTH-V2|CARRIER|SET-500": (PmTriggerType.ENGINE_HOUR, 1000, "hour", "1,000"),
        "SYNTH-V1|CARRIER|SET-KM": (PmTriggerType.ODOMETER, 10000, "km", "10,000"),
    }
    assert sets["SYNTH-V1|CARRIER|SET-KM"].independent_group == "INDEPENDENT_GROUP"  # source label kept


# B1-09 / B1-10 -------------------------------------------------------------------


async def test_b1_09_publish_preserves_rev_n_audits_the_diff_and_requires_validation() -> None:
    store = PmMasterMockStore()
    svc = service(store)
    sets = clean_sets()
    rev1 = (await publish(svc, sets, 0)).revision
    rev1_dump = rev1.model_dump()
    changed = tuple(s if s.set_key != "SYNTH-V1|CRANE|SET-500" else s.model_copy(update={"interval_value": 650.0,
                                                                                          "raw_interval": "650"})
                    for s in sets)
    outcome = await publish(svc, changed, 1, reason="ปรับรอบตามเอกสารใหม่")
    assert outcome.revision.revision_number == 2 and svc.effective_revision(ctx(), PLAN).revision_number == 2
    assert svc.get_revision(ctx(), PLAN, 1).model_dump() == rev1_dump  # Rev N unchanged
    assert outcome.diff["sets_changed"] == [{"set_key": "SYNTH-V1|CRANE|SET-500", "fields": {
        "interval_value": {"from": 600.0, "to": 650.0}, "raw_interval": {"from": "600", "to": "650"}}}]
    assert svc.compare(ctx(), PLAN, 1, 2)["sets_changed"] == outcome.diff["sets_changed"]
    assert [(e["kind"], e["version"], e["actor_user_id"], e["reason"]) for e in svc.audit(ctx())] == [
        ("PUBLISH", "1", PUBLISHER, "เผยแพร่ทดสอบ"), ("PUBLISH", "2", PUBLISHER, "ปรับรอบตามเอกสารใหม่")]
    with pytest.raises(pydantic_frozen_error()):
        rev1.sets[0].interval_value = 1  # immutable revision content
    # invalid candidates never publish and leave nothing behind
    before = snapshot(store)
    for bad, issue in ((clean_sets(accepted_preview())[:0], "NO_SETS"),
                       (candidate_sets_from_preview(accepted_preview(), PLAN), "DRIVING_COMPONENT_ABSENT")):
        with pytest.raises(ApiError) as refused:
            await publish(svc, bad, 2)
        assert refused.value.code == "PM_MASTER_VALIDATION_FAILED"
        assert issue in {p["issue"] for p in refused.value.details["problems"]}
    full = preview_source(synthetic_workbook(), source_file=SOURCE)
    with pytest.raises(ApiError) as open_review:
        await svc.publish(ctx(), plan_code=PLAN, expected_revision=2, sets=changed, reason="x",
                          request_id=str(uuid.uuid4()), open_reviews=full.unresolved_reviews(PLAN))
    assert any(p["issue"].startswith("UNRESOLVED_REVIEW") for p in open_review.value.details["problems"])
    with pytest.raises(ApiError) as same:
        await publish(svc, changed, 2)
    assert same.value.code == "PM_MASTER_UNCHANGED"
    assert snapshot(store) == before


def pydantic_frozen_error():
    from pydantic import ValidationError
    return ValidationError


async def test_b1_10_old_work_order_snapshot_keeps_its_revision_after_n_plus_1(client) -> None:
    store = PmMasterMockStore()
    svc = service(store)
    sets = clean_sets()
    await publish(svc, sets, 0)
    frozen = svc.freeze_selection(ctx(), PLAN, ["SYNTH-V1|CARRIER|SET-500", "SYNTH-V1|CARRIER|SET-KM"])
    frozen_dump = frozen.model_dump()
    reworded = tuple(s.model_copy(update={"items": tuple(i.model_copy(update={"task_text": i.task_text + " (แก้ไข)"})
                                                         for i in s.items)}) for s in sets)
    await publish(svc, reworded, 1)
    assert frozen.model_dump() == frozen_dump and frozen.revision_number == 1
    assert svc.freeze_selection(ctx(), PLAN, ["SYNTH-V1|CARRIER|SET-500"]).revision_number == 2
    assert svc.freeze_selection(ctx(), PLAN, ["SYNTH-V1|CARRIER|SET-500"], revision_number=1).sets[0] == frozen.sets[0]
    with pytest.raises(ApiError):
        svc.freeze_selection(ctx(), PLAN, ["SYNTH-V9|CRANE|NOPE"])
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
    await publish(svc, sets, 2, reason="Rev 3")
    after = [(await client.get(f"/api/v1/pm/work-orders/{w}")).json() for w in (wo_closed, wo_open)]
    assert after == before and all(b["work_order"]["revision_id"] == "PMREV-0001" for b in after)


# B1-11 / B1-12 -------------------------------------------------------------------


async def test_b1_11_assign_change_unassign_with_reason_version_and_audit_or_fail_closed() -> None:
    store = PmMasterMockStore()
    svc = service(store)
    await publish(svc, clean_sets(), 0)
    other = tuple(s.model_copy(update={"set_code": "SET-B"}) for s in clean_sets()[:1])
    await svc.publish(ctx(), plan_code="SYNTH-PLAN-NEW", expected_revision=0, sets=other, reason="แผนใหม่",
                      request_id=str(uuid.uuid4()))  # a new Plan added later
    steps = [(PLAN, 0, "ASSIGN"), ("SYNTH-PLAN-NEW", 1, "CHANGE"), (None, 2, "UNASSIGN"), (PLAN, 3, "ASSIGN")]
    for plan, version, kind in steps:
        out = await svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=plan, expected_version=version,
                                       reason=f"เหตุผล {kind}", request_id=str(uuid.uuid4()))
        assert (out.record.version, out.record.state, out.replayed) == (version + 1, NONE if plan is None else ASSIGNED, False)
        assert store.events[-1]["kind"] == kind and store.events[-1]["reason"] == f"เหตุผล {kind}"
    assert [a.version for a in store.assignments] == [1, 2, 3, 4]  # history kept, nothing rewritten
    before = snapshot(store)
    for kwargs, expected in (({"plan_code": PLAN, "expected_version": 1}, "PM_MASTER_STALE_ASSIGNMENT"),
                             ({"plan_code": "SYNTH-UNPUBLISHED", "expected_version": 4}, "PM_MASTER_NOT_PUBLISHED"),
                             ({"plan_code": PLAN, "expected_version": 4}, "PM_MASTER_ASSIGNMENT_UNCHANGED")):
        with pytest.raises(ApiError) as refused:
            await svc.set_assignment(ctx(), vehicle_id="VEH-1046", reason="x", request_id=str(uuid.uuid4()), **kwargs)
        assert refused.value.code == expected
    with pytest.raises(ApiError) as no_reason:
        await svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=None, expected_version=4, reason=" ",
                                 request_id=str(uuid.uuid4()))
    assert no_reason.value.code == "VALIDATION_ERROR"
    # The application authorizer fails closed: no self-grant, no write.
    app_svc = PmMasterService(store)
    with pytest.raises(ApiError) as closed:
        await app_svc.set_assignment(ctx(), vehicle_id="VEH-1046", plan_code=None, expected_version=4, reason="x",
                                     request_id=str(uuid.uuid4()))
    assert (closed.value.status_code, closed.value.code, closed.value.details["gate"]) == (
        403, "PM_MASTER_AUTHORITY_UNPROVEN", VAL_AM_GATE)
    assert snapshot(store) == before


async def test_b1_12_explicit_unassignment_is_never_overridden_by_the_model_default(client) -> None:
    store, repo = PmMasterMockStore(), MockRepository()
    svc = service(store, repository=repo)
    await publish(svc, clean_sets(), 0)
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
    # Old API consumers are unchanged: the model still reports its field and the legacy flow still works.
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
    master = PmMasterMockStore()
    await publish(service(master), clean_sets(), 0)  # synthetic content to read
    app_svc = PmMasterService(master)  # the application authorizer
    before = snapshot(master)

    async def outcome(user, role="TECHNICIAN"):
        context = await effective(am, user, role)
        try:
            app_svc.effective_revision(context, PLAN)
            read = "READ"
        except Exception as exc:  # noqa: BLE001 — HTTPException 403 from require_capability
            read = getattr(exc, "status_code", "?")
        try:
            await app_svc.publish(context, plan_code=PLAN, expected_revision=1, sets=clean_sets(), reason="x",
                                  request_id="am-forged")
            write = "WROTE"
        except ApiError as exc:
            write = (exc.status_code, exc.code)
        return context, read, write

    denied = (403, "PM_MASTER_AUTHORITY_UNPROVEN")
    # root holder with can_view + can_manage_pm: may read, may NOT publish (can_manage_pm is E01 only)
    assert (await grant(am, MGR, employee(MGR), {"can_view": True, "can_manage_pm": True})).status_code == 200
    context, read, write = await outcome(MGR)
    assert authz.CAN_MANAGE_PM in context.capabilities and context.access.is_root
    assert (read, write) == ("READ", denied)
    # can_manage_pm alone: no read, no publish
    await grant(am, MGR, employee(DRV1), {"can_manage_pm": True})
    assert (await outcome(DRV1))[1:] == (403, denied)
    # revoked can_view: denied on the very next call
    await grant(am, MGR, employee(DRV1), {"can_view": True})
    assert (await outcome(DRV1))[1] == "READ"
    await grant(am, MGR, employee(DRV1), {"can_view": False})
    assert (await outcome(DRV1))[1:] == (403, denied)
    # expired department period: a transfer resets every grant
    await grant(am, MGR, employee(MGR), {"can_move_personnel_department": True})
    await grant(am, MGR, employee(DRV1), {"can_view": True})
    moved = await http("POST", f"/api/v1/personnel/{P[DRV1]}/department-events", am, MGR, json={
        "operation": "TRANSFER", "department_id": MNT, "effective": {"mode": "NOW"},
        "expected_current_department_id": OPS, "reason_th": "ย้ายแผนก"})
    assert moved.status_code == 200, moved.text
    assert (await outcome(DRV1))[1:] == (403, denied)
    # wrong-scope delegate: cannot give TECH1 (another department) a read, and cannot publish itself
    await delegate(am, MGR, OPM, OPS, ["can_view"])
    assert (await grant(am, OPM, employee(TECH1), {"can_view": True})).status_code == 403
    assert (await outcome(TECH1))[1:] == (403, denied)
    assert (await outcome(OPM))[2] == denied
    # inactive employee and the development ADMIN role hold nothing in AM mode
    assert (await outcome(RESIGNED, "ADMIN"))[1:] == (403, denied)
    assert (await outcome("USR-UNKNOWN", "ADMIN"))[1:] == (403, denied)
    assert snapshot(master) == before  # no Master mutation by anyone


async def test_forged_master_publish_is_refused_even_with_every_legacy_capability() -> None:
    store = PmMasterMockStore()
    app_svc = PmMasterService(store)
    forged = ctx("dev-user", authz.ALL_CAPABILITIES | {"can_publish_pm_master", "can_manage_pm_master"},
                 roles=("ADMIN",), is_dev_auth=True)
    with pytest.raises(ApiError) as refused:
        await app_svc.publish(forged, plan_code=PLAN, expected_revision=0, sets=clean_sets(), reason="x",
                              request_id="forged")
    assert (refused.value.code, refused.value.details["gate"]) == ("PM_MASTER_AUTHORITY_UNPROVEN", VAL_AM_GATE)
    assert "can_publish_pm_master" not in authz.ALL_CAPABILITIES  # no capability was invented
    assert (store.revisions, store.events) == ({}, ())


# B1-14 / B1-15 ---------------------------------------------------------------------


async def test_b1_14_concurrent_publish_yields_one_effective_revision_and_one_event() -> None:
    store = PmMasterMockStore()
    svc = service(store)
    sets = clean_sets()
    variants = [tuple(s.model_copy(update={"raw_interval": f"{s.raw_interval} #{n}"}) for s in sets) for n in range(5)]
    results = await asyncio.gather(*(publish(svc, v, 0) for v in variants), return_exceptions=True)
    wins = [r for r in results if not isinstance(r, Exception)]
    losses = [r for r in results if isinstance(r, ApiError)]
    assert len(wins) == 1 and len(losses) == 4
    assert {e.code for e in losses} == {"PM_MASTER_STALE_REVISION"}
    assert len(store.revisions[PLAN]) == 1 and len(store.events) == 1
    assert store.head(PLAN).revision_id == wins[0].revision.revision_id


async def test_b1_15_same_request_id_replays_and_a_different_payload_is_rejected() -> None:
    store = PmMasterMockStore()
    svc = service(store)
    sets = clean_sets()
    first = await publish(svc, sets, 0, request_id="REQ-B1-1")
    again = await publish(svc, sets, 0, request_id="REQ-B1-1")
    assert again.replayed and again.revision == first.revision and len(store.events) == 1
    before = snapshot(store)
    with pytest.raises(ApiError) as reused:
        await publish(svc, sets, 0, request_id="REQ-B1-1", reason="เหตุผลอื่น")
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


# B1-16 -------------------------------------------------------------------------------


async def test_b1_16_lineage_follows_proven_keys_and_leaves_ambiguity_unverified() -> None:
    store = PmMasterMockStore()
    svc = service(store)
    sets = clean_sets()
    await publish(svc, sets, 0)
    base = next(s for s in sets if s.set_key == "SYNTH-V1|CARRIER|SET-500")
    i1, i2, i3 = base.items
    new_items = (
        i2.model_copy(update={"sequence": 1}),                                     # reordered
        i1.model_copy(update={"sequence": 2, "task_text": "ตรวจและเติมน้ำมันเครื่อง"}),  # reworded, same key
        MasterItem(item_key="I-3B", sequence=3, task_text=i3.task_text),          # same text, new key, no evidence
        MasterItem(item_key="I-4", sequence=4, task_text="งานใหม่"),
    )
    changed = tuple(s.model_copy(update={"items": new_items}) if s.set_key == base.set_key else s for s in sets)
    lineage = {r["item_key"]: r for r in (await publish(svc, changed, 1)).diff["items"]
               if r["set_key"] == base.set_key}
    assert lineage["I-1"]["status"] == LINEAGE_RETAINED and lineage["I-1"]["reworded"] and lineage["I-1"]["resequenced"]
    assert lineage["I-2"]["status"] == LINEAGE_RETAINED and not lineage["I-2"]["reworded"]
    assert (lineage["I-3B"]["status"], lineage["I-3B"]["candidates"]) == (LINEAGE_AMBIGUOUS, ["I-3"])
    assert lineage["I-3"]["status"] == LINEAGE_REMOVED and lineage["I-4"]["status"] == LINEAGE_NEW
    # an evidenced supersession is a proven semantic match
    proven = tuple(s.model_copy(update={"items": (*new_items[:2], MasterItem(
        item_key="I-3C", sequence=3, task_text="ตรวจสายพานและปรับความตึง", supersedes_item_key="I-3B",
        lineage_evidence="SYNTH-DOC-1 rev.B §4 replaces item I-3B"), new_items[3])}) if s.set_key == base.set_key else s
                   for s in sets)
    rows3 = {r["item_key"]: r for r in (await publish(svc, proven, 2)).diff["items"] if r["set_key"] == base.set_key}
    assert (rows3["I-3C"]["status"], rows3["I-3C"]["previous_item_key"]) == (LINEAGE_PROVEN, "I-3B")
    no_evidence = tuple(s.model_copy(update={"items": (*new_items[:2], MasterItem(
        item_key="I-3D", sequence=3, task_text="x", supersedes_item_key="I-3C"), new_items[3])})
                        if s.set_key == base.set_key else s for s in sets)
    with pytest.raises(ApiError) as refused:
        await publish(svc, no_evidence, 3)
    assert "LINEAGE_EVIDENCE_REQUIRED" in {p["issue"] for p in refused.value.details["problems"]}


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
    # nothing in the running application imports the B1 modules (no runtime activation)
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
    for forbidden in ("due_at", "next_due", "overdue", "safety_critical", "warning_threshold", "advisory_percent",
                      "technician_v2_enabled"):
        assert forbidden not in source.lower(), forbidden
    fields = set(MasterSet.model_fields) | set(MasterItem.model_fields)
    assert not fields & {"due_status", "safety_critical", "warning_threshold", "part_quantity", "completed"}


def test_negative_missing_meter_values_are_unknown_never_zero() -> None:
    p = preview_source(synthetic_workbook(), source_file=SOURCE)
    blank = [e for e in p.ledger if e.row_or_key == "row:11" and e.sheet == "source_pm_cycles"]
    assert [(e.column, e.issue) for e in blank] == [("interval_value", "MISSING_REQUIRED_VALUE")]
    assert not any(s.set_code in {"SET-BLANK", "SET-ZERO"} for s in p.sets)  # neither becomes 0
    with pytest.raises(Exception):
        MasterSet(model_variant="v", section="CARRIER", set_code="s", meter_type=PmTriggerType.ENGINE_HOUR,
                  interval_value=None, interval_unit="hour")  # null is not silently a number
    from app.domain.pm import PmPlanStatus
    assert PmPlanStatus.model_fields["due_status"].default == "UNKNOWN"  # runtime still reports UNKNOWN
