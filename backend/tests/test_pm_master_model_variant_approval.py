"""R4 / TASK-010 RT2 (OPEN-016, DEC-R4-TASK010-MODEL-VARIANT-MAPPING-OPEN016-20261106):
explicit, evidence-backed `(VehicleModel.model_id, exact Master plan_code) ->
MasterSet.model_variant` approvals in the RT1-bound Master store.

A source candidate is never an approval. Every decision here is written by the TEST-ONLY
`TEST_PM_MASTER_EDITOR` persona through the audited operation, against a registered,
digest-pinned preview of the SYNTHETIC source workbook whose `vehicle_pm_mapping` rows
name registered Mock vehicles. The application authorizer still denies everyone
(OPEN-005). This is a Mock proof, not Google Sheets, PostgreSQL or Production evidence."""
from __future__ import annotations

import asyncio
import copy
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.domain import authz
from app.domain.meter_service import MeterService
from app.domain.pm_master import (
    KIND_VARIANT_APPROVE,
    KIND_VARIANT_CORRECT,
    KIND_VARIANT_REVOKE,
    VARIANT_APPROVED,
    VARIANT_REVOKED,
    MasterDataScope,
    MockVehicleResolver,
    PmMasterMockStore,
    PmMasterService,
)
from app.domain.pm_meter_anchor import NO_IOT_METER_SOURCE
from app.domain.pm_service import PmService
from app.errors import ApiError
from tests.pm_e01_support import ctx, repo_with, rid
from tests.test_pm_master_b1_mock import (
    CARRIER_A,
    CRANE_A,
    DOC_LOW,
    DOC_M2,
    DOC_M3,
    DOC_UP,
    EVIDENCE,
    KM_SET,
    M2_A,
    PLAN,
    PLAN_B,
    PUBLISHER,
    TEST_PM_MASTER_ASSIGNER,
    TEST_PM_MASTER_EDITOR,
    persona_test_only_authorizer,
    publish,
    register,
    resolve_all,
    smap,
    source_workbook,
)
from tests.test_pm_master_b1_mock import ctx as master_ctx
from tests.test_pm_master_e01_due_bridge import (
    CARRIER_ENG,
    TEST_SCOPE,
    VEH,
    World,
    complete,
    current_source,
    due,
    open_wo,
    outcome,
    report_engines,
)
from tests.test_pm_submit_meter_anchor import FakeIotSource
from tests.test_technician_assignment_batch_r2f_h1 import cut

EDITOR, ASSIGNER = master_ctx(TEST_PM_MASTER_EDITOR), master_ctx(TEST_PM_MASTER_ASSIGNER)
VEH_M3 = "VEH-1048"  # Mock seed: MODEL-0003
VEH_UNPLANNED = "VEH-1046"  # Mock seed: MODEL-0001, PENDING_PM_PLAN in the synthetic source
M1, M2 = "MODEL-0002", "MODEL-0003"  # VEH-1047 is MODEL-0002
REASON = "อนุมัติการจับคู่รุ่นรถกับแผน PM (synthetic)"
SINGLE = "NOT_SEPARATED_IN_PLAN"
VARIANT_INVALID = (422, "PM_MASTER_VARIANT_EVIDENCE_INVALID")


def registered_workbook(*extra: dict) -> dict:
    """The synthetic source plus `vehicle_pm_mapping` rows for REGISTERED Mock vehicles:
    VEH-1047 -> (PLAN, SYN-M1), VEH-1048 -> (PLAN, SYN-M2), VEH-1046 without a Plan."""
    workbook = copy.deepcopy(source_workbook())
    workbook["vehicle_pm_mapping"] += [
        smap(VEH, "CARRIER_AND_CRANE", low=DOC_LOW, up=DOC_UP),
        smap(VEH_M3, SINGLE, model="SYN-M2", low=DOC_M2),
        smap(VEH_UNPLANNED, "UNKNOWN", plan="", model="", status="PENDING_PM_PLAN"),
        *extra]
    return workbook


async def variant_world(*, extra=(), assign=True, scope=TEST_SCOPE, repo=None):
    repo, source = repo or repo_with(), FakeIotSource()
    store = PmMasterMockStore(data_scope=scope)
    master = PmMasterService(store, authorizer=persona_test_only_authorizer, vehicle_resolver=MockVehicleResolver(repo))
    reg = await register(master, registered_workbook(*extra), context=EDITOR)
    await resolve_all(master, reg, context=EDITOR)
    rev = (await publish(master, reg, 0, context=EDITOR)).revision
    if assign:
        await master.set_assignment(ASSIGNER, vehicle_id=VEH, assembly="", plan_code=PLAN, expected_version=0,
                                    reason="กำหนดแผนทดสอบ (synthetic)", request_id=rid())
    svc = PmService(repo, MeterService(repo, iot_meter_source=source), assignment_cutover=cut())
    return World(repo, store, master, rev, svc, source), reg


def row_of(reg, vehicle: str) -> str:
    [candidate] = [c for c in reg.preview.mapping_candidates if c.vehicle_ref == vehicle]
    return candidate.source_row


async def approve(w: World, reg, *, model=M1, plan=PLAN, variant="SYN-M1", rows=None, version=0, context=EDITOR,
                  request_id=None, preview_id=None, digest=None, evidence=EVIDENCE, reason=REASON):
    return await w.master.approve_model_variant(
        context, model_id=model, plan_code=plan, model_variant=variant, expected_version=version,
        preview_id=preview_id or reg.preview_id, expected_source_digest=digest or reg.source_digest,
        source_rows=rows if rows is not None else [row_of(reg, VEH)], evidence=evidence, reason=reason,
        request_id=rid() if request_id is None else request_id)


async def revoke(w: World, *, model=M1, plan=PLAN, version=1, context=EDITOR, request_id=None, evidence=EVIDENCE):
    return await w.master.revoke_model_variant(context, model_id=model, plan_code=plan, expected_version=version,
                                               evidence=evidence, reason="เพิกถอนการจับคู่ (synthetic)",
                                               request_id=rid() if request_id is None else request_id)


def due_svc(w: World, source=None, **cutover) -> PmService:
    """TEST-ONLY injection of the bound Master WITHOUT a variant override: the Master's
    own approvals are the source (RT2 default)."""
    return PmService(w.repo, MeterService(w.repo, iot_meter_source=source or NO_IOT_METER_SOURCE),
                     assignment_cutover=cut(**cutover)).with_master_reads(w.master, None)


async def vdue(w: World, *, source=None, vehicle=VEH, svc=None):
    return await (svc or due_svc(w, source)).read_vehicle_pm_due(ctx("SYN-RT2-VIEWER", authz.CAN_VIEW), vehicle)


def plan_states(v) -> list[tuple[str, str, str | None]]:
    return [(p.plan_code, p.state, p.model_variant) for p in v.plans]


def master_state(w: World) -> tuple:
    s = w.store
    return (dict(s.revisions), s.assignments, s.previews, s.resolutions, s.variant_approvals, s.events)


def runtime_state(w: World) -> tuple:
    r = w.repo
    return (dict(r._pm_work_orders), r._pm_master_memberships, dict(r._meter_snapshots),
            dict(r._pm_submit_meter_anchors), {k: list(v) for k, v in r._pm_transitions.items()},
            dict(r._pm_task_revisions), dict(r._pm_item_outcomes), {k: list(v) for k, v in r._pm_work_results.items()})


async def refused(w: World, call, expected: tuple, issue: str | None = None) -> ApiError:
    before = master_state(w)
    with pytest.raises(ApiError) as exc:
        await call
    assert (exc.value.status_code, exc.value.code) == expected
    if issue is not None:
        assert exc.value.details["issue"] == issue
    assert master_state(w) == before  # nothing written, no audit event
    return exc.value


# ---------------------------------------------------------------- A. a candidate is never an approval


async def test_rt2_01_candidates_alone_prove_nothing_and_open_nothing() -> None:
    w, reg = await variant_world()
    assert {c.vehicle_ref for c in reg.preview.mapping_candidates} >= {VEH, VEH_M3, VEH_UNPLANNED}
    assert w.store.variant_approvals == ()
    v = await vdue(w)
    assert (v.state, plan_states(v), v.sets) == ("AVAILABLE", [(PLAN, "MODEL_VARIANT_UNVERIFIED", None)], ())
    assert w.master.model_variant_source(EDITOR)(M1, PLAN) == frozenset()
    with pytest.raises(ApiError) as unproven:
        await open_wo(w, [CARRIER_A], model_variants=None)
    assert unproven.value.code == "PM_MASTER_MODEL_VARIANT_UNVERIFIED"
    assert runtime_state(w)[0] == {} and runtime_state(w)[1] == ()


async def test_rt2_02_an_explicit_approval_makes_exactly_its_sets_applicable() -> None:
    w, reg = await variant_world()
    result = await approve(w, reg)
    record = result.record
    assert (result.replayed, record.state, record.version, record.model_variant, record.preview_id,
            record.source_digest, record.source_rows, record.recorded_by) == (
        False, VARIANT_APPROVED, 1, "SYN-M1", reg.preview_id, reg.source_digest, (row_of(reg, VEH),),
        TEST_PM_MASTER_EDITOR)
    assert w.store.events[-1]["kind"] == KIND_VARIANT_APPROVE and w.store.events[-1]["approval_id"] == record.approval_id
    v = await vdue(w)
    assert plan_states(v) == [(PLAN, "RESOLVED", "SYN-M1")]
    assert {s.set_key for s in v.sets} >= {CARRIER_A, CRANE_A, KM_SET}
    assert all(s.model_variant == "SYN-M1" for s in v.sets)
    assert w.master.model_variant_source(EDITOR)(M1, PLAN) == frozenset({"SYN-M1"})
    assert w.master.model_variant_source(EDITOR)(M1, PLAN_B) == frozenset()  # exact Plan only
    assert w.master.model_variant_source(EDITOR)(M2, PLAN) == frozenset()  # exact model only


# ---------------------------------------------------------------- B. evidence validation (nothing written)


async def test_rt2_03_every_missing_or_wrong_proof_is_refused_without_a_write() -> None:
    w, reg = await variant_world()
    unplanned, m3_row = row_of(reg, VEH_UNPLANNED), row_of(reg, VEH_M3)
    synthetic_row = row_of(reg, "SYN-VEH-01")  # an accepted SYN-M1 candidate whose vehicle is not registered
    for kwargs, issue in (
            ({"rows": [unplanned]}, "SOURCE_ROW_NOT_ACCEPTED_CANDIDATE"),       # PENDING_PM_PLAN: no Plan
            ({"rows": ["vehicle_pm_mapping!row:999"]}, "SOURCE_ROW_NOT_ACCEPTED_CANDIDATE"),
            ({"rows": ["vehicle_pm_mapping!row:13"]}, "SOURCE_ROW_NOT_ACCEPTED_CANDIDATE"),  # a REVIEW row (raw 35)
            ({"rows": [m3_row]}, "SOURCE_ROW_PLAN_OR_VARIANT_MISMATCH"),         # SYN-M2 row for SYN-M1
            ({"variant": "SYN-M2", "rows": [row_of(reg, VEH)]}, "SOURCE_ROW_PLAN_OR_VARIANT_MISMATCH"),
            ({"model": M2}, "SOURCE_ROW_MODEL_MISMATCH"),                        # VEH-1047 is MODEL-0002
            ({"rows": [synthetic_row]}, "SOURCE_ROW_MODEL_MISMATCH"),           # not a registered vehicle
            ({"variant": "SYN-M9"}, "VARIANT_NOT_IN_PUBLISHED_PLAN"),
            ({"variant": "syn-m1"}, "VARIANT_NOT_IN_PUBLISHED_PLAN"),            # never case-folded
            ({"variant": ""}, "VARIANT_REQUIRED"),
            ({"rows": []}, "SOURCE_ROWS_REQUIRED"),
            ({"rows": [row_of(reg, VEH)] * 2}, "SOURCE_ROWS_REQUIRED"),
            ({"digest": "0" * 64}, "DIGEST_MISMATCH"),
            ({"preview_id": "PMPV-9999-unknown"}, "PREVIEW_NOT_FOUND"),
            ({"evidence": "ok"}, "EVIDENCE_INSUFFICIENT"),
    ):
        await refused(w, approve(w, reg, **kwargs), VARIANT_INVALID, issue)
    await refused(w, approve(w, reg, model="MODEL-SYN-ABSENT"), (404, "VEHICLE_MODEL_NOT_FOUND"))
    await refused(w, approve(w, reg, plan=PLAN_B, variant="SYN-M6"), (422, "PM_MASTER_NOT_PUBLISHED"))
    await refused(w, approve(w, reg, reason=""), (422, "VALIDATION_ERROR"))
    await refused(w, approve(w, reg, request_id=""), (422, "REQUEST_ID_REQUIRED"))
    assert w.store.variant_approvals == ()


async def test_rt2_04_a_wrong_plan_with_its_own_published_head_is_refused() -> None:
    w, reg = await variant_world()
    await resolve_all(w.master, reg, PLAN_B, context=EDITOR, skip={r.entry_id for r in w.store.resolutions})
    await publish(w.master, reg, 0, plan=PLAN_B, context=EDITOR)
    # SYN-M6 is in PLAN_B's head, but the VEH-1047 row names (PLAN, SYN-M1).
    await refused(w, approve(w, reg, plan=PLAN_B, variant="SYN-M6"), VARIANT_INVALID,
                  "SOURCE_ROW_PLAN_OR_VARIANT_MISMATCH")


async def test_rt2_05_a_contradicting_candidate_of_the_same_model_and_plan_blocks_approval() -> None:
    repo = repo_with()
    repo._vehicles["VEH-SYN-2047"] = repo._vehicles[VEH].model_copy(update={"vehicle_id": "VEH-SYN-2047"})
    w, reg = await variant_world(repo=repo, extra=(smap("VEH-SYN-2047", SINGLE, model="SYN-M3", low=DOC_M3),))
    # Both VEH-1047 (SYN-M1) and VEH-SYN-2047 (SYN-M3) are MODEL-0002 in PLAN: ambiguous.
    for variant, row in (("SYN-M1", row_of(reg, VEH)), ("SYN-M3", row_of(reg, "VEH-SYN-2047"))):
        await refused(w, approve(w, reg, variant=variant, rows=[row]), VARIANT_INVALID, "EVIDENCE_CONFLICT")
    assert w.master.model_variant_source(EDITOR)(M1, PLAN) == frozenset()


async def test_rt2_06_new_approvals_need_the_current_preview_and_a_newer_preview_rewrites_nothing() -> None:
    w, reg = await variant_world()
    approved = (await approve(w, reg)).record
    newer = await register(w.master, registered_workbook(), context=EDITOR)  # same source file, re-registered
    assert newer.preview_id != reg.preview_id
    # The approval keeps its original evidence snapshot and stays in force (no silent rewrite) ...
    assert w.store.variant_approvals == (approved,) and approved.preview_id == reg.preview_id
    assert w.master.model_variant_source(EDITOR)(M1, PLAN) == frozenset({"SYN-M1"})
    # ... no candidate of the newer preview was approved ...
    assert w.master.model_variant_source(EDITOR)(M2, PLAN) == frozenset()
    # ... and a NEW decision cannot cite the superseded preview.
    m3 = {"model": M2, "variant": "SYN-M2", "rows": [row_of(reg, VEH_M3)]}
    await refused(w, approve(w, reg, **m3), VARIANT_INVALID, "PREVIEW_STALE")
    assert (await approve(w, newer, **m3)).record.preview_id == newer.preview_id


async def test_rt2_07_no_vehicle_resolver_means_no_approval() -> None:
    w, reg = await variant_world()
    bare = PmMasterService(w.store, authorizer=persona_test_only_authorizer)
    with pytest.raises(ApiError) as missing:
        await approve(World(w.repo, w.store, bare, w.rev, w.svc, w.source), reg)
    assert missing.value.code == "PM_MASTER_VEHICLE_RESOLVER_REQUIRED" and w.store.variant_approvals == ()


# ---------------------------------------------------------------- C. authority (OPEN-005) and isolation (RT1)


async def test_rt2_08_only_the_test_editor_may_decide_and_the_application_denies_everyone() -> None:
    w, reg = await variant_world()
    root = frozenset(v for k, v in vars(authz).items() if k.startswith("CAN_") and isinstance(v, str))
    for actor in (ASSIGNER, master_ctx("USR-SYN-ADMIN", frozenset({authz.CAN_VIEW, authz.CAN_MANAGE_PM})),
                  master_ctx("USR-SYN-ROOT", root, is_dev_auth=True)):
        await refused(w, approve(w, reg, context=actor), (403, "PM_MASTER_AUTHORITY_UNPROVEN"))
    application = PmMasterService(w.store, vehicle_resolver=MockVehicleResolver(w.repo))  # default authorizer
    for actor in (EDITOR, master_ctx(PUBLISHER)):
        await refused(w, application.approve_model_variant(
            actor, model_id=M1, plan_code=PLAN, model_variant="SYN-M1", expected_version=0, preview_id=reg.preview_id,
            expected_source_digest=reg.source_digest, source_rows=[row_of(reg, VEH)], evidence=EVIDENCE,
            reason=REASON, request_id=rid()), (403, "PM_MASTER_AUTHORITY_UNPROVEN"))
    record = (await approve(w, reg)).record
    for actor in (ASSIGNER, master_ctx("USR-SYN-ROOT", root)):
        await refused(w, revoke(w, context=actor), (403, "PM_MASTER_AUTHORITY_UNPROVEN"))
    with pytest.raises(ApiError) as assigner_cannot:  # the EDITOR stays unable to assign
        await w.master.set_assignment(EDITOR, vehicle_id=VEH_M3, plan_code=PLAN, expected_version=0, reason="x",
                                      request_id=rid())
    assert assigner_cannot.value.code == "PM_MASTER_AUTHORITY_UNPROVEN" and record.version == 1
    with pytest.raises(ApiError) as real:  # a REAL Master can never carry the TEST authorizer
        PmMasterService(PmMasterMockStore(data_scope=MasterDataScope.real()), authorizer=persona_test_only_authorizer)
    assert real.value.code == "PM_MASTER_AUTHORITY_UNPROVEN"


async def test_rt2_09_reading_the_approvals_needs_can_view() -> None:
    w, reg = await variant_world()
    await approve(w, reg)
    for context in (master_ctx("USR-SYN-NOVIEW", frozenset()), master_ctx("USR-SYN-PM", frozenset({authz.CAN_MANAGE_PM}))):
        for read in (lambda c: w.master.model_variant_source(c), lambda c: w.master.variant_approval_history(c, M1, PLAN)):
            with pytest.raises(HTTPException) as denied:
                read(context)
            assert denied.value.status_code == 403


async def test_rt2_10_approvals_never_cross_a_scope_or_a_repository() -> None:
    w, reg = await variant_world()
    await approve(w, reg)
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    assert plan_states(await vdue(w, source=source)) == [(PLAN, "RESOLVED", "SYN-M1")]
    for cutover in ({"batch": "SYN-RT2-OTHER-BATCH"}, {"context": "REAL"}):
        foreign = await vdue(w, svc=due_svc(w, source, **cutover))
        assert (foreign.state, foreign.plans, foreign.sets) == ("MASTER_NOT_ACTIVE", (), ())
    other_repo = PmMasterService(w.store, authorizer=persona_test_only_authorizer,
                                 vehicle_resolver=MockVehicleResolver(repo_with()))
    v = await vdue(w, svc=PmService(w.repo, MeterService(w.repo), assignment_cutover=cut()).with_master_reads(
        other_repo, None))
    assert (v.state, v.plans) == ("MASTER_NOT_ACTIVE", ())
    with pytest.raises(ApiError) as mismatch:
        await w.svc.open_master_work_order(other_repo, ctx("USR-SYN-MGR", authz.CAN_VIEW, authz.CAN_MANAGE_PM),
                                           asset_id=VEH, plan_code=PLAN, revision_number=1,
                                           selected_set_keys=[CARRIER_A], request_id=rid())
    assert mismatch.value.code == "PM_MASTER_REPOSITORY_MISMATCH"
    # Another batch's store with its own approval proves nothing for this batch's Master.
    b, b_reg = await variant_world(scope=MasterDataScope.test("SYN-RT2-OTHER-BATCH"), repo=w.repo)
    await approve(b, b_reg, model=M2, variant="SYN-M2", rows=[row_of(b_reg, VEH_M3)])
    assert w.master.model_variant_source(EDITOR)(M2, PLAN) == frozenset()


# ---------------------------------------------------------------- D. lifecycle, replay, concurrency, history


async def test_rt2_11_correct_then_revoke_keeps_an_immutable_history() -> None:
    w, reg = await variant_world(extra=(smap("VEH-SYN-NONE", SINGLE, model="SYN-M3", low=DOC_M3),))
    first = (await approve(w, reg)).record
    v = await vdue(w)
    assert plan_states(v) == [(PLAN, "RESOLVED", "SYN-M1")]
    # CORRECT: a registered MODEL-0002 vehicle now evidences SYN-M3 instead (source corrected).
    w.repo._vehicles["VEH-SYN-2047"] = w.repo._vehicles[VEH].model_copy(update={"vehicle_id": "VEH-SYN-2047"})
    corrected_wb = registered_workbook(smap("VEH-SYN-2047", SINGLE, model="SYN-M3", low=DOC_M3))
    corrected_wb["vehicle_pm_mapping"] = [r for r in corrected_wb["vehicle_pm_mapping"] if r["vehicle_id"] != VEH]
    newer = await register(w.master, corrected_wb, context=EDITOR)
    await refused(w, approve(w, newer, variant="SYN-M3", rows=[row_of(newer, "VEH-SYN-2047")], version=0),
                  (409, "PM_MASTER_STALE_VARIANT_APPROVAL"))
    second = (await approve(w, newer, variant="SYN-M3", rows=[row_of(newer, "VEH-SYN-2047")], version=1)).record
    assert (second.version, second.model_variant, w.store.events[-1]["kind"]) == (2, "SYN-M3", KIND_VARIANT_CORRECT)
    v = await vdue(w)
    assert plan_states(v) == [(PLAN, "RESOLVED", "SYN-M3")] and {s.model_variant for s in v.sets} == {"SYN-M3"}
    await refused(w, approve(w, newer, variant="SYN-M3", rows=[row_of(newer, "VEH-SYN-2047")], version=2),
                  (422, "PM_MASTER_VARIANT_APPROVAL_UNCHANGED"))
    # REVOKE: no in-force variant; Fleet Due reads MODEL_VARIANT_UNVERIFIED with no Sets.
    await refused(w, revoke(w, version=1), (409, "PM_MASTER_STALE_VARIANT_APPROVAL"))
    await refused(w, revoke(w, version=2, evidence="short"), VARIANT_INVALID, "EVIDENCE_INSUFFICIENT")
    third = (await revoke(w, version=2)).record
    assert (third.state, third.model_variant, third.version, w.store.events[-1]["kind"]) == (
        VARIANT_REVOKED, "", 3, KIND_VARIANT_REVOKE)
    v = await vdue(w)
    assert (plan_states(v), v.sets) == ([(PLAN, "MODEL_VARIANT_UNVERIFIED", None)], ())
    await refused(w, revoke(w, version=3), (422, "PM_MASTER_VARIANT_NOT_APPROVED"))
    history = w.master.variant_approval_history(EDITOR, M1, PLAN)
    assert history == (first, second, third) and first.model_variant == "SYN-M1"  # nothing overwritten
    with pytest.raises(ValidationError):  # frozen records
        first.model_variant = "SYN-M3"
    assert [json.loads(e["diff_json"]) for e in w.store.events if e["kind"].startswith("VARIANT_")] == [
        {"from": None, "from_state": "ABSENT", "to": "SYN-M1", "to_state": "APPROVED"},
        {"from": "SYN-M1", "from_state": "APPROVED", "to": "SYN-M3", "to_state": "APPROVED"},
        {"from": "SYN-M3", "from_state": "APPROVED", "to": None, "to_state": "REVOKED"}]


async def test_rt2_12_replay_reuse_and_concurrency() -> None:
    w, reg = await variant_world()
    request_id = rid()
    first = await approve(w, reg, request_id=request_id)
    again = await approve(w, reg, request_id=request_id)
    assert (again.replayed, again.record) == (True, first.record) and len(w.store.variant_approvals) == 1
    await refused(w, approve(w, reg, request_id=request_id, evidence=EVIDENCE + " (changed)"),
                  (409, "REQUEST_ID_REUSED"))
    await refused(w, revoke(w, request_id=request_id), (409, "REQUEST_ID_REUSED"))
    # authority is checked before a replay is disclosed
    await refused(w, approve(w, reg, request_id=request_id, context=ASSIGNER), (403, "PM_MASTER_AUTHORITY_UNPROVEN"))
    m3 = {"model": M2, "variant": "SYN-M2", "rows": [row_of(reg, VEH_M3)]}
    results = await asyncio.gather(approve(w, reg, **m3), approve(w, reg, **m3), return_exceptions=True)
    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, ApiError)]
    assert len(winners) == 1 and [e.code for e in losers] == ["PM_MASTER_STALE_VARIANT_APPROVAL"]
    assert [a.version for a in w.master.variant_approval_history(EDITOR, M2, PLAN)] == [1]


# ---------------------------------------------------------------- E. historical safety


async def test_rt2_13_revoking_after_work_orders_changes_applicability_only() -> None:
    w, reg = await variant_world()
    await approve(w, reg)
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A], model_variants=None)  # the Master's own approval
    await complete(w, job)
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    carrier = next(s for s in (await vdue(w, source=source)).sets if s.set_key == CARRIER_A)
    assert (carrier.status, carrier.next_due, carrier.last_completed_pm_work_order_id) == ("NOT_DUE", 1500.0, job)
    history = runtime_state(w)
    await revoke(w)
    v = await vdue(w, source=source)
    assert (plan_states(v), v.sets) == ([(PLAN, "MODEL_VARIANT_UNVERIFIED", None)], ())  # no current applicability
    assert runtime_state(w) == history  # Work Order, membership, anchors, outcomes, journal untouched
    with pytest.raises(ApiError) as unproven:
        await open_wo(w, [CARRIER_A], model_variants=None)
    assert unproven.value.code == "PM_MASTER_MODEL_VARIANT_UNVERIFIED" and runtime_state(w) == history
    # Existing internal contract (no route): `evaluate_master_set_due` evaluates ONE Set's stored,
    # membership-backed historical evidence and does not consult current applicability; the only
    # PM Due route (the Fleet/Vehicle read above) no longer shows the Set.
    assert outcome(await due(w, CARRIER_A, source=source)) == ("NOT_DUE", 1500.0, None)
    # Re-approval restores applicability over the SAME history (same revision, no rewrite).
    newer = await register(w.master, registered_workbook(), context=EDITOR)
    await approve(w, newer, rows=[row_of(newer, VEH)], version=2)
    carrier = next(s for s in (await vdue(w, source=source)).sets if s.set_key == CARRIER_A)
    assert (carrier.status, carrier.last_completed_pm_work_order_id) == ("NOT_DUE", job)


async def test_rt2_14_a_changed_vehicle_model_uses_only_its_new_models_approval() -> None:
    w, reg = await variant_world()
    await approve(w, reg)
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A], model_variants=None)
    await complete(w, job)
    history = runtime_state(w)
    w.repo._vehicles[VEH] = w.repo._vehicles[VEH].model_copy(update={"model_id": M2})  # registry correction
    v = await vdue(w)
    assert (plan_states(v), v.sets) == ([(PLAN, "MODEL_VARIANT_UNVERIFIED", None)], ())  # M1's approval ignored
    # The registered source still says VEH-1047 is SYN-M1: for MODEL-0003 that now contradicts
    # VEH-1048's SYN-M2, so approval is refused until the source itself is corrected.
    await refused(w, approve(w, reg, model=M2, variant="SYN-M2", rows=[row_of(reg, VEH_M3)]), VARIANT_INVALID,
                  "EVIDENCE_CONFLICT")
    corrected = registered_workbook()
    for row in corrected["vehicle_pm_mapping"]:
        if row["vehicle_id"] == VEH:
            row.update(plan_model="SYN-M2", component_configuration=SINGLE, carrier_or_main_source_sheet=DOC_M2,
                       crane_source_sheet="")
    newer = await register(w.master, corrected, context=EDITOR)
    await approve(w, newer, model=M2, variant="SYN-M2", rows=[row_of(newer, VEH_M3), row_of(newer, VEH)])
    v = await vdue(w, source=current_source({("ENGINE_HOUR", CARRIER_ENG): 1100}))
    assert plan_states(v) == [(PLAN, "RESOLVED", "SYN-M2")]
    m2 = next(s for s in v.sets if s.set_key == M2_A)
    assert (m2.status, m2.diagnostic_code, m2.last_completed_pm_work_order_id) == (
        "UNKNOWN", "NO_VERIFIED_ACTUAL_SET_COMPLETION", None)  # no credit from the old model's Work Order
    assert runtime_state(w) == history  # the old membership still names MODEL-0002, unchanged


async def test_rt2_15_a_new_revision_cannot_invent_or_keep_a_removed_variant() -> None:
    w, reg = await variant_world()
    await approve(w, reg)
    rev2 = w.rev.model_copy(update={
        "revision_id": f"PMMREV-{PLAN}-0002", "revision_number": 2, "request_id": "REQ-SYN-RT2-REV2",
        "sets": tuple(s for s in w.rev.sets if s.model_variant != "SYN-M1")})  # SYN-M1 removed
    w.store.commit({"kind": "PUBLISH", "request_id": "REQ-SYN-RT2-REV2", "request_fingerprint": "rt2"}, revision=rev2)
    v = await vdue(w)
    assert (plan_states(v), v.sets) == ([(PLAN, "NO_APPLICABLE_SET", "SYN-M1")], ())  # approval kept, no Sets
    with pytest.raises(ApiError) as gone:
        await open_wo(w, [CARRIER_A], model_variants=None, revision=rev2)
    assert gone.value.code == "VALIDATION_ERROR"  # the removed variant's Sets are not in revision 2
    newer = await register(w.master, registered_workbook(), context=EDITOR)
    await refused(w, approve(w, newer, model=M2, variant="SYN-M9", rows=[row_of(newer, VEH_M3)]), VARIANT_INVALID,
                  "VARIANT_NOT_IN_PUBLISHED_PLAN")
