"""R4 / TASK-010 RT3-A: scope-safe PM Master runtime identity and the Mock Master
commit contract.

1. Identity: a Master revision id carries its store's scope token, the runtime Plan id
   is derived from (scope, plan_code) and the task id from the scoped revision id, so
   TEST batch A, TEST batch B and REAL never share E01 catalogue identity in one
   repository. Unbound or unscoped revisions fail closed (never REAL).
2. Commit: `PmMasterMockStore.commit` itself refuses an append that would reuse a
   committed request id, revision, assignment / variant-approval version, reviewed
   entry or preview id (what a database enforces with unique keys), and the service
   maps that to its EXISTING replay / 409 outcome with nothing written.

Every case is a synthetic Mock/Fake case. The competing-commit cases are controlled
stale-read simulations; they do not prove multi-process PostgreSQL behavior
(MOCK PASS != POSTGRES PASS)."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import replace

import pytest

from app.domain import authz
from app.domain.meter_service import MeterService
from app.domain.pm_master import (
    CONFLICT_ASSIGNMENT,
    CONFLICT_PREVIEW,
    CONFLICT_REQUEST_ID,
    CONFLICT_REVIEW,
    CONFLICT_REVISION,
    CONFLICT_SCOPE,
    CONFLICT_VARIANT,
    MasterCommitConflict,
    MasterDataScope,
    PmMasterMockStore,
    master_revision_id,
)
from app.domain.pm_master_runtime import (
    RUNTIME_PLAN_PREFIX,
    build_catalogue,
    build_membership,
    frozen_set,
    runtime_plan_id,
    runtime_plan_id_of,
)
from app.domain.pm_service import _MASTER_RUNTIME_PLAN_PREFIX, PmService
from app.errors import ApiError
from tests.pm_e01_support import ctx, repo_with, rid
from tests.test_pm_master_b1_mock import (
    CARRIER_A,
    CRANE_A,
    PLAN,
    PLAN_B,
    publish,
    register,
    resolve_all,
)
from tests.test_pm_master_e01_due_bridge import (
    BACKEND,
    BATCH,
    CARRIER_ENG,
    CRANE_ENG,
    TEST_SCOPE,
    VEH,
    complete,
    current_source,
    open_wo,
    report_engines,
    tasks_of,
)
from tests.test_pm_master_model_variant_approval import (
    ASSIGNER,
    EDITOR,
    M1,
    approve,
    due_svc,
    registered_workbook,
    revoke,
    row_of,
    runtime_state,
    variant_world,
    vdue,
)
from tests.test_technician_assignment_batch_r2f_h1 import cut

BATCH_B = "SYN-RT3A-BATCH-B"
SCOPE_B = MasterDataScope.test(BATCH_B)
REAL = MasterDataScope.real()
OPENER = ctx("USR-SYN-MGR", authz.CAN_VIEW, authz.CAN_MANAGE_PM)


def master_state(store: PmMasterMockStore) -> tuple:
    return (dict(store.revisions), store.assignments, store.previews, store.resolutions, store.variant_approvals,
            store.events)


async def approved_world(*, scope=TEST_SCOPE, repo=None):
    """A bound Master over `repo` with VEH-1047 explicitly assigned and its model
    variant explicitly approved (RT2), in ONE scope."""
    w, reg = await variant_world(scope=scope, repo=repo)
    await approve(w, reg)
    return w, reg


def stale_once(store, name: str, stale_value=None):
    """A controlled competing-commit simulation: the FIRST read of `name` is stale (it
    predates a commit another writer made); every later read sees the committed state."""
    real, calls = getattr(type(store), name), []

    def read(*args):
        calls.append(args)
        return stale_value if len(calls) == 1 else real(store, *args)

    return read


async def publish_plan_b(w, reg) -> None:
    await resolve_all(w.master, reg, PLAN_B, context=EDITOR, skip={r.entry_id for r in w.store.resolutions})
    await publish(w.master, reg, 0, plan=PLAN_B, context=EDITOR)


async def open_in(w, keys, *, batch=BATCH, request_id=None) -> str:
    svc = PmService(w.repo, MeterService(w.repo, iot_meter_source=w.source), assignment_cutover=cut(batch=batch))
    detail = await svc.open_master_work_order(w.master, OPENER, asset_id=VEH, plan_code=PLAN,
                                              revision_number=w.rev.revision_number, selected_set_keys=list(keys),
                                              request_id=request_id or rid())
    return detail.work_order.pm_work_order_id


# ---------------------------------------------------------------- A. scope-safe identity


def test_rt3a_01_plan_revision_and_task_ids_differ_per_scope_and_are_deterministic() -> None:
    scopes = (TEST_SCOPE, SCOPE_B, REAL)
    assert len({s.token for s in scopes}) == 3
    assert len({master_revision_id(s, PLAN, 1) for s in scopes}) == 3
    assert len({runtime_plan_id(PLAN, s) for s in scopes}) == 3
    assert master_revision_id(TEST_SCOPE, PLAN, 1) == master_revision_id(MasterDataScope.test(BATCH), PLAN, 1)
    assert runtime_plan_id(PLAN, TEST_SCOPE) == runtime_plan_id(PLAN, MasterDataScope.test(BATCH))
    assert runtime_plan_id(PLAN, TEST_SCOPE) != runtime_plan_id(PLAN_B, TEST_SCOPE)
    assert master_revision_id(None, PLAN, 1).startswith("PMMREV-UNBOUND-")  # never REAL's token
    assert REAL.token not in master_revision_id(None, PLAN, 1)
    for bad in (None, ("FALSE", ""), "REAL"):
        with pytest.raises(ValueError, match="PM_MASTER_SCOPE_UNBOUND"):
            runtime_plan_id(PLAN, bad)


async def test_rt3a_02_two_test_batches_publish_and_open_the_same_plan_in_one_repository() -> None:
    repo = repo_with()
    a, _ = await approved_world(repo=repo)
    b, _ = await approved_world(scope=SCOPE_B, repo=repo)
    assert (a.rev.plan_code, a.rev.revision_number) == (b.rev.plan_code, b.rev.revision_number) == (PLAN, 1)
    assert a.rev.revision_id != b.rev.revision_id and (a.rev.data_scope, b.rev.data_scope) == (TEST_SCOPE, SCOPE_B)
    cat_a, cat_b = build_catalogue(a.rev), build_catalogue(b.rev)
    assert cat_a.plan.pm_plan_id != cat_b.plan.pm_plan_id
    assert not {t.pm_task_id for t in cat_a.tasks} & {t.pm_task_id for t in cat_b.tasks}
    report_engines(a, carrier=1000)
    job_a = await open_in(a, [CARRIER_A])
    job_b = await open_in(b, [CARRIER_A], batch=BATCH_B)  # base: 409 PM_MASTER_CATALOGUE_CONFLICT
    m_a, m_b = (next(m for m in repo._pm_master_memberships if m.pm_work_order_id == j) for j in (job_a, job_b))
    assert (m_a.pm_plan_id, m_a.master_revision_id) == (runtime_plan_id_of(a.rev), a.rev.revision_id)
    assert (m_b.pm_plan_id, m_b.master_revision_id) == (runtime_plan_id_of(b.rev), b.rev.revision_id)
    assert (m_a.is_test_data, m_a.test_batch_id, m_b.test_batch_id) == ("TRUE", BATCH, BATCH_B)
    assert not set(m_a.task_ids) & set(m_b.task_ids)
    for job, rev in ((job_a, a.rev), (job_b, b.rev)):
        wo = repo._pm_work_orders[job]
        stored = await repo.get_pm_task_revision(wo.pm_plan_id, wo.revision_id)
        assert stored.revision.revision_id == rev.revision_id and {t.revision_id for t in stored.tasks} == {
            rev.revision_id}


async def test_rt3a_03_each_batch_sees_only_its_own_completion_and_catalogue() -> None:
    repo = repo_with()
    a, _ = await approved_world(repo=repo)
    b, _ = await approved_world(scope=SCOPE_B, repo=repo)
    report_engines(a, carrier=1000)
    job_a = await open_in(a, [CARRIER_A])
    await complete(a, job_a)
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100})
    carrier_a = next(s for s in (await vdue(a, source=source)).sets if s.set_key == CARRIER_A)
    assert (carrier_a.status, carrier_a.next_due, carrier_a.last_completed_pm_work_order_id) == (
        "NOT_DUE", 1500.0, job_a)
    b_svc = PmService(repo, MeterService(repo, iot_meter_source=source),
                      assignment_cutover=cut(batch=BATCH_B)).with_master_reads(b.master, None)
    carrier_b = next(s for s in (await vdue(b, svc=b_svc)).sets if s.set_key == CARRIER_A)
    assert (carrier_b.status, carrier_b.diagnostic_code, carrier_b.last_completed_pm_work_order_id) == (
        "UNKNOWN", "NO_VERIFIED_ACTUAL_SET_COMPLETION", None)  # batch A's Work Order never leaks into batch B
    # The plan-level catalogue read is per scope too: each runtime Plan id has only its own revision.
    viewer = ctx("SYN-RT3A-VIEWER", authz.CAN_VIEW)  # RT3-B: a Master catalogue read needs a can_view actor
    assert (await a.svc.get_active_task_revision(runtime_plan_id_of(a.rev), viewer)).revision.revision_id == \
        a.rev.revision_id
    with pytest.raises(ApiError) as none_yet:  # batch B never opened a Work Order: no catalogue under ITS Plan id
        await a.svc.get_active_task_revision(runtime_plan_id_of(b.rev), viewer)
    assert none_yet.value.status_code == 404
    # A foreign-scope Master is refused before any replay or Master read (RT1, unchanged).
    with pytest.raises(ApiError) as foreign:
        await open_in(b, [CARRIER_A], batch=BATCH)
    assert foreign.value.code == "PM_MASTER_SCOPE_MISMATCH"


async def test_rt3a_04_unbound_or_unscoped_revisions_never_reach_the_catalogue() -> None:
    w, _ = await approved_world()
    rev = w.rev
    for bad, code in ((rev.model_copy(update={"data_scope": None}), "PM_MASTER_SCOPE_UNBOUND"),
                      (rev.model_copy(update={"revision_id": f"PMMREV-{PLAN}-0001"}),  # older, unscoped id
                       "PM_MASTER_REVISION_SCOPE_MISMATCH"),
                      (rev.model_copy(update={"data_scope": SCOPE_B}), "PM_MASTER_REVISION_SCOPE_MISMATCH"),
                      (rev.model_copy(update={"data_scope": REAL}), "PM_MASTER_REVISION_SCOPE_MISMATCH")):
        with pytest.raises(ValueError, match=code):
            build_catalogue(bad)
    snapshot = w.master.freeze_selection(EDITOR, PLAN, [CARRIER_A], revision_number=1)
    assert snapshot.data_scope == TEST_SCOPE
    for cells in ({"is_test_data": "TRUE", "test_batch_id": BATCH_B}, {"is_test_data": "FALSE", "test_batch_id": ""}):
        with pytest.raises(ValueError, match="PM_MASTER_REVISION_SCOPE_MISMATCH"):
            build_membership(snapshot, asset_id=VEH, vehicle_model_id=M1, request_id="r", fingerprint="f", scope=cells)
    with pytest.raises(ValueError, match="PM_MASTER_SCOPE_UNBOUND"):
        build_membership(snapshot.model_copy(update={"data_scope": None}), asset_id=VEH, vehicle_model_id=M1,
                         request_id="r", fingerprint="f", scope={"is_test_data": "TRUE", "test_batch_id": BATCH})


async def test_rt3a_05_a_stored_membership_with_unscoped_identity_fails_the_read_closed() -> None:
    w, _ = await approved_world()
    report_engines(w, carrier=1000)
    job = await open_wo(w, [CARRIER_A], model_variants=None)
    await complete(w, job)
    [member] = w.repo._pm_master_memberships
    legacy_plan_id = "PMMP-" + "0" * 20  # e.g. an older, unscoped derivation: never migrated or guessed
    w.repo._pm_master_memberships = (replace(member, pm_plan_id=legacy_plan_id),)
    with pytest.raises(ApiError) as corrupt:
        await vdue(w)
    assert (corrupt.value.status_code, corrupt.value.details) == (500, {"issues": {"MEMBERSHIP_PROVENANCE_MISMATCH": 1}})
    w.repo._pm_master_memberships = (member,)
    assert next(s for s in (await vdue(w)).sets if s.set_key == CARRIER_A).last_completed_pm_work_order_id == job


async def test_rt3a_05b_a_membership_whose_scope_cells_disagree_with_its_identity_is_unverified() -> None:
    """Defence in depth inside `frozen_set` (the service's scope filter and provenance
    check normally refuse such a record first): a membership stored with TEST batch A
    cells but batch-B catalogue identity never proves a Set."""
    w, _ = await approved_world()
    components = [(c.component_id, c.component_role.value) for c in await w.repo.list_vehicle_components(VEH)]
    snapshot = w.master.freeze_selection(EDITOR, PLAN, [CARRIER_A], revision_number=1)
    cells = {"is_test_data": "TRUE", "test_batch_id": BATCH}
    member = build_membership(snapshot, asset_id=VEH, vehicle_model_id=M1, request_id="r", fingerprint="f", scope=cells)
    good = frozen_set([member], CARRIER_A, build_catalogue(w.rev), components, M1)
    assert good.source_verified and all(i.verified for i in good.items)
    rev_b = w.rev.model_copy(update={"data_scope": SCOPE_B, "revision_id": master_revision_id(SCOPE_B, PLAN, 1)})
    snap_b = snapshot.model_copy(update={"data_scope": SCOPE_B, "revision_id": rev_b.revision_id})
    member_b = build_membership(snap_b, asset_id=VEH, vehicle_model_id=M1, request_id="r", fingerprint="f",
                                scope={"is_test_data": "TRUE", "test_batch_id": BATCH_B})
    forged = replace(member_b, is_test_data="TRUE", test_batch_id=BATCH)  # batch-B identity under batch-A cells
    for record in (forged, replace(member, test_batch_id="")):  # mismatched or invalid cells
        catalogue = build_catalogue(rev_b if record is forged else w.rev)
        frozen = frozen_set([record], CARRIER_A, catalogue, components, M1)
        assert not frozen.source_verified and not any(i.verified for i in frozen.items)


# ---------------------------------------------------------------- B. the commit contract


async def test_rt3a_06_commit_itself_refuses_every_duplicate_identity_and_writes_nothing() -> None:
    w, _ = await approved_world()
    store = w.store
    rev, assignment, preview = w.rev, store.assignments[-1], store.previews[-1]
    resolution, approval = store.resolutions[-1], store.variant_approvals[-1]
    new = {"kind": "SYN", "request_id": "REQ-RT3A-NEW", "request_fingerprint": "f"}
    used = {**new, "request_id": store.events[-1]["request_id"]}
    rev2 = rev.model_copy(update={"revision_id": master_revision_id(TEST_SCOPE, PLAN, 2), "revision_number": 2})
    cases = (
        (used, {}, CONFLICT_REQUEST_ID),
        (new, {"revision": rev.model_copy(update={"revision_id": master_revision_id(TEST_SCOPE, PLAN, 9)})},
         CONFLICT_REVISION),  # revision number 1 again
        (new, {"revision": rev2.model_copy(update={"revision_id": rev.revision_id})}, CONFLICT_REVISION),  # same id
        (new, {"revision": rev2.model_copy(update={"data_scope": SCOPE_B})}, CONFLICT_SCOPE),
        (new, {"revision": rev2.model_copy(update={"data_scope": None})}, CONFLICT_SCOPE),
        (new, {"assignment": assignment}, CONFLICT_ASSIGNMENT),
        (new, {"preview": preview}, CONFLICT_PREVIEW),
        (new, {"resolution": resolution.model_copy(update={"resolution_id": "PMRR-OTHER"})}, CONFLICT_REVIEW),
        (new, {"variant_approval": approval.model_copy(update={"approval_id": "PMMVA-OTHER"})}, CONFLICT_VARIANT),
    )
    for event, records, kind in cases:
        before = master_state(store)
        with pytest.raises(MasterCommitConflict) as refused:
            store.commit(event, **records)
        assert refused.value.kind == kind
        assert master_state(store) == before  # neither the event nor any record
    store.commit(new, revision=rev2)  # a genuinely new revision number in the same scope is accepted
    assert store.head(PLAN) == rev2


async def test_rt3a_07_a_competing_commit_maps_to_the_existing_stale_errors(monkeypatch) -> None:
    w, _ = await approved_world()
    store = w.store
    # publish: our read saw no head (stale) while revision 1 is committed
    newer = await register(w.master, registered_workbook(), context=EDITOR)
    await resolve_all(w.master, newer, context=EDITOR)
    monkeypatch.setattr(store, "head", stale_once(store, "head"))
    before = master_state(store)
    with pytest.raises(ApiError) as stale_publish:
        await publish(w.master, newer, 0, context=EDITOR)
    assert (stale_publish.value.status_code, stale_publish.value.code, stale_publish.value.details) == (
        409, "PM_MASTER_STALE_REVISION", {"expected_revision": 0, "current_revision": 1})
    monkeypatch.undo()
    assert master_state(store) == before
    # assignment: our read saw no version (stale) while version 1 is committed
    monkeypatch.setattr(store, "latest_assignment", stale_once(store, "latest_assignment"))
    with pytest.raises(ApiError) as stale_assign:
        await w.master.set_assignment(ASSIGNER, vehicle_id=VEH, plan_code=None, expected_version=0, reason="x",
                                      request_id=rid())
    monkeypatch.undo()
    assert (stale_assign.value.code, stale_assign.value.details["current_version"]) == (
        "PM_MASTER_STALE_ASSIGNMENT", 1)
    # model variant approval: our read saw no version (stale) while version 1 is committed
    monkeypatch.setattr(store, "latest_variant_approval", stale_once(store, "latest_variant_approval"))
    with pytest.raises(ApiError) as stale_variant:
        await approve(w, newer, version=0)
    monkeypatch.undo()
    assert (stale_variant.value.code, stale_variant.value.details["current_version"]) == (
        "PM_MASTER_STALE_VARIANT_APPROVAL", 1)
    assert master_state(store) == before


async def test_rt3a_08_a_request_committed_meanwhile_replays_or_is_reused_never_duplicated(monkeypatch) -> None:
    w, _ = await approved_world()
    store, request_id = w.store, rid()
    first = await w.master.set_assignment(ASSIGNER, vehicle_id=VEH, plan_code=None, expected_version=1,
                                          reason="ถอนแผน (synthetic)", request_id=request_id)
    prior_v1 = store.assignments[-2]  # what a writer that has not seen version 2 yet would read

    def scenario():
        """Our replay check and version read both ran before the competing commit (of
        THIS very request) became visible; every later read sees it."""
        real_replay, calls = w.master._replay, []

        def missed_once(*args):
            calls.append(args)
            return None if len(calls) == 1 else real_replay(*args)

        monkeypatch.setattr(w.master, "_replay", missed_once)
        monkeypatch.setattr(store, "latest_assignment", stale_once(store, "latest_assignment", prior_v1))

    before = master_state(store)
    scenario()  # same payload: the stale writer would append version 2 again; commit refuses, it replays
    again = await w.master.set_assignment(ASSIGNER, vehicle_id=VEH, plan_code=None, expected_version=1,
                                          reason="ถอนแผน (synthetic)", request_id=request_id)
    assert (again.replayed, again.record) == (True, first.record) and master_state(store) == before
    monkeypatch.undo()
    scenario()  # a different payload under the same request id is refused, still nothing written
    with pytest.raises(ApiError) as reused:
        await w.master.set_assignment(ASSIGNER, vehicle_id=VEH, plan_code=None, expected_version=1,
                                      reason="อื่น (synthetic)", request_id=request_id)
    assert reused.value.code == "REQUEST_ID_REUSED" and master_state(store) == before


async def test_rt3a_09_a_failed_commit_writes_nothing_and_a_lost_response_retry_replays(monkeypatch) -> None:
    w, _ = await approved_world()
    store, real_commit = w.store, w.store.commit
    before = master_state(store)

    def broken(event, **records):
        raise RuntimeError("synthetic storage failure before the commit")

    monkeypatch.setattr(store, "commit", broken)
    request_id = rid()
    with pytest.raises(RuntimeError):
        await revoke(w, request_id=request_id)
    assert master_state(store) == before

    def lost(event, **records):
        real_commit(event, **records)
        raise RuntimeError("synthetic failure after the commit (response lost)")

    monkeypatch.setattr(store, "commit", lost)
    with pytest.raises(RuntimeError):
        await revoke(w, request_id=request_id)
    monkeypatch.setattr(store, "commit", real_commit)
    committed = store.variant_approvals[-1]
    retry = await revoke(w, request_id=request_id)
    assert (retry.replayed, retry.record) == (True, committed)
    assert len(store.variant_approvals) == len(before[4]) + 1 and len(store.events) == len(before[5]) + 1


# ---------------------------------------------------------------- C. historical integrity


async def test_rt3a_10_master_changes_never_touch_opened_work_orders_or_their_evidence() -> None:
    w, _ = await approved_world()
    report_engines(w, carrier=1000, crane=2000)
    job = await open_wo(w, [CARRIER_A, CRANE_A], model_variants=None)
    await complete(w, job, not_performed=tuple(tasks_of(w, job, CRANE_A)))  # CRANE Set partial / outstanding
    history = runtime_state(w)
    member = w.repo._pm_master_memberships[0]
    source = current_source({("ENGINE_HOUR", CARRIER_ENG): 1100, ("ENGINE_HOUR", CRANE_ENG): 2100})
    sets = {s.set_key: s for s in (await vdue(w, source=source)).sets}
    assert (sets[CARRIER_A].status, sets[CARRIER_A].last_completed_pm_work_order_id) == ("NOT_DUE", job)
    assert (sets[CRANE_A].status, sets[CRANE_A].diagnostic_code) == ("UNKNOWN", "NO_VERIFIED_ACTUAL_SET_COMPLETION")
    # 1. a new revision of the Plan
    workbook = copy.deepcopy(registered_workbook())
    workbook["source_pm_cycles"][0]["interval_value"] = "550"
    newer = await register(w.master, workbook, context=EDITOR)
    await resolve_all(w.master, newer, context=EDITOR)
    rev2 = (await publish(w.master, newer, 1, context=EDITOR)).revision
    assert rev2.revision_id == master_revision_id(TEST_SCOPE, PLAN, 2) and runtime_state(w) == history
    sets = {s.set_key: s for s in (await vdue(w, source=source)).sets}
    assert all(s.revision_number == 2 for s in sets.values())
    assert sets[CARRIER_A].last_completed_pm_work_order_id is None  # no cross-revision credit
    # 2. correct, then revoke the model variant approval; 3. change, then remove the assignment
    await revoke(w)
    await approve(w, newer, rows=[row_of(newer, VEH)], version=2)
    await publish_plan_b(w, newer)
    await w.master.set_assignment(ASSIGNER, vehicle_id=VEH, plan_code=PLAN_B, expected_version=1, reason="x",
                                  request_id=rid())
    await w.master.set_assignment(ASSIGNER, vehicle_id=VEH, plan_code=None, expected_version=2, reason="x",
                                  request_id=rid())
    assert runtime_state(w) == history and w.repo._pm_master_memberships[0] == member  # byte-identical history
    assert (await vdue(w, source=source)).state == "NO_ASSIGNED_PLAN"
    # the per-Set historical evaluator still reads exactly the frozen revision-1 evidence
    svc = due_svc(w, source)
    decision = await svc.evaluate_master_set_due(OPENER, asset_id=VEH, master_revision_id=w.rev.revision_id,
                                                 set_key=CARRIER_A)
    assert (decision.due.status, decision.due.next_due) == ("NOT_DUE", 1500.0)
    crane = await svc.evaluate_master_set_due(OPENER, asset_id=VEH, master_revision_id=w.rev.revision_id,
                                              set_key=CRANE_A)
    assert crane.due.status == "UNKNOWN"  # the partial Set never became a completion


# ---------------------------------------------------------------- D. RT3-A R2: direct Plan catalogue reads (scope)


async def three_scope_catalogues():
    """One shared Mock repository with FULLY populated Master catalogues of TEST batch A
    and TEST batch B (each opened a Master Work Order) and a SYNTHETIC REAL catalogue
    placed directly in the repository (no REAL authority exists to publish one)."""
    repo = repo_with()
    a, _ = await approved_world(repo=repo)
    b, _ = await approved_world(scope=SCOPE_B, repo=repo)
    await open_in(a, [CARRIER_A])
    await open_in(b, [CARRIER_A], batch=BATCH_B)
    real_rev = a.rev.model_copy(update={"data_scope": REAL, "revision_id": master_revision_id(REAL, PLAN, 1)})
    real_cat = build_catalogue(real_rev)
    repo._pm_plans[real_cat.plan.pm_plan_id] = real_cat.plan
    repo._pm_task_revisions[real_rev.revision_id] = real_cat.revision
    repo._pm_tasks[real_rev.revision_id] = list(real_cat.tasks)
    servers = {"TEST-A": cut(batch=BATCH), "TEST-B": cut(batch=BATCH_B), "REAL": cut(context="REAL")}
    revisions = {"TEST-A": a.rev, "TEST-B": b.rev, "REAL": real_rev}
    return repo, a, servers, revisions


async def http_get(path: str, repo, cutover, role: str | None = "TECHNICIAN"):
    """GET through the real app and routes as a development-header actor (default: a
    `can_view` role); see `http_get_as` (RT3-B)."""
    return await http_get_as(path, repo, cutover, role)


def plan_paths(rev) -> tuple[str, str]:
    plan_id = runtime_plan_id_of(rev)
    return f"/pm/plans/{plan_id}/active-revision", f"/pm/plans/{plan_id}/revisions/{rev.revision_id}"


async def test_rt3a_r2_01_each_scope_reads_its_own_master_catalogue() -> None:
    repo, _, servers, revisions = await three_scope_catalogues()
    for scope in ("TEST-A", "TEST-B", "REAL"):
        for path in plan_paths(revisions[scope]):
            response = await http_get(path, repo, servers[scope])
            body = response.json()
            assert (response.status_code, body["revision"]["revision_id"]) == (200, revisions[scope].revision_id)
            assert body["tasks"] and {t["revision_id"] for t in body["tasks"]} == {revisions[scope].revision_id}


async def test_rt3a_r2_02_no_scope_reads_another_scopes_master_catalogue() -> None:
    repo, _, servers, revisions = await three_scope_catalogues()
    for reader, cutover in servers.items():
        for owner, rev in revisions.items():
            if owner == reader:
                continue
            active, explicit = plan_paths(rev)
            for path, code in ((active, "PM_PLAN_NOT_FOUND"), (explicit, "PM_TASK_REVISION_NOT_FOUND")):
                response = await http_get(path, repo, cutover)
                assert (response.status_code, response.json()["error"]["code"]) == (404, code), (reader, owner, path)
                text = response.text
                assert rev.revision_id not in text or code == "PM_TASK_REVISION_NOT_FOUND"  # only the id asked for
                assert '"tasks"' not in text and "task_text" not in text  # no catalogue content disclosed
    # a missing catalogue answers the same way (no existence oracle)
    missing = await http_get(f"/pm/plans/{RUNTIME_PLAN_PREFIX}{'0' * 20}/active-revision", repo, servers["TEST-A"])
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "PM_PLAN_NOT_FOUND")


async def test_rt3a_r2_03_a_foreign_revision_id_under_a_local_plan_id_is_not_found() -> None:
    repo, _, servers, revisions = await three_scope_catalogues()
    local_plan = runtime_plan_id_of(revisions["TEST-A"])
    for foreign in ("TEST-B", "REAL"):
        response = await http_get(f"/pm/plans/{local_plan}/revisions/{revisions[foreign].revision_id}", repo,
                                  servers["TEST-A"])
        assert (response.status_code, response.json()["error"]["code"]) == (404, "PM_TASK_REVISION_NOT_FOUND")
        assert '"tasks"' not in response.text


async def test_rt3a_r2_04_an_unconfigured_server_scope_fails_closed_for_master_catalogues_only() -> None:
    repo, _, _, revisions = await three_scope_catalogues()
    unconfigured = cut(context=None)
    for rev in revisions.values():
        for path in plan_paths(rev):
            response = await http_get(path, repo, unconfigured)
            assert response.status_code == 503 and '"tasks"' not in response.text  # never read as REAL
    for path in ("/pm/plans/PMP-0001/active-revision", "/pm/plans/PMP-0001/revisions/PMREV-0001"):
        assert (await http_get(path, repo, unconfigured)).status_code == 200  # seed reads unchanged


async def test_rt3a_r2_05_an_older_unscoped_master_catalogue_is_never_served() -> None:
    repo, _, servers, revisions = await three_scope_catalogues()
    legacy = build_catalogue(revisions["TEST-A"])
    legacy_plan_id = f"{RUNTIME_PLAN_PREFIX}{'1' * 20}"  # e.g. an older derivation from plan_code alone
    repo._pm_plans[legacy_plan_id] = legacy.plan.model_copy(update={"pm_plan_id": legacy_plan_id})
    revision = legacy.revision.model_copy(update={"revision_id": "PMMREV-LEGACY-0001", "pm_plan_id": legacy_plan_id})
    repo._pm_task_revisions[revision.revision_id] = revision
    repo._pm_tasks[revision.revision_id] = [t.model_copy(update={"revision_id": revision.revision_id})
                                            for t in legacy.tasks]
    for path in (f"/pm/plans/{legacy_plan_id}/active-revision",
                 f"/pm/plans/{legacy_plan_id}/revisions/{revision.revision_id}"):
        for cutover in servers.values():
            response = await http_get(path, repo, cutover)
            assert response.status_code == 404 and '"tasks"' not in response.text


async def test_rt3a_r2_06_reads_change_nothing_and_seed_behaviour_is_unchanged() -> None:
    repo, a, servers, revisions = await three_scope_catalogues()
    history = runtime_state(a)
    for rev in revisions.values():
        for path in plan_paths(rev):
            await http_get(path, repo, servers["TEST-A"])
    assert runtime_state(a) == history  # memberships, Work Orders, journal, anchors untouched
    for role in (None, "SYN-RT3B-NO-SUCH-ROLE", "TECHNICIAN"):  # Phase-4 seed policy unchanged
        for cutover in servers.values():
            active = await http_get("/pm/plans/PMP-0001/active-revision", repo, cutover, role)
            explicit = await http_get("/pm/plans/PMP-0001/revisions/PMREV-0001", repo, cutover, role)
            assert (active.status_code, explicit.status_code) == (200, 200)
            assert active.json()["revision"]["revision_id"] == "PMREV-0001"
    assert _MASTER_RUNTIME_PLAN_PREFIX == RUNTIME_PLAN_PREFIX  # one prefix, two places (no import on seed reads)


def test_rt3a_r2_07_seed_catalogue_reads_never_load_the_master_modules() -> None:
    """In a fresh interpreter: the application's own wiring serves the seed catalogue and
    neither the B1 Master nor its runtime bridge module is imported (firewall)."""
    script = r"""
import asyncio, json, sys, uuid
from httpx import ASGITransport, AsyncClient
from app.context import RequestContext
from app.dependencies import get_current_context
from app.main import create_app

async def main():
    app = create_app()
    app.dependency_overrides[get_current_context] = lambda: RequestContext(
        request_id=str(uuid.uuid4()), user_id="SYN-VIEWER", is_dev_auth=True, capabilities=frozenset({"can_view"}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        active = await client.get("/api/v1/pm/plans/PMP-0001/active-revision")
        explicit = await client.get("/api/v1/pm/plans/PMP-0001/revisions/PMREV-0001")
    print(json.dumps({"codes": [active.status_code, explicit.status_code],
                      "loaded": sorted(m for m in sys.modules if m.startswith("app.domain.pm_master"))}))

asyncio.run(main())
"""
    out = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"codes": [200, 200], "loaded": []}


# ---------------------------------------------------------------- E. RT3-B: CAN_VIEW on Master catalogue reads


async def http_get_as(path: str, repo, cutover, role: str | None, user_id: str = "SYN-RT3B-READER"):
    """GET through the real app, routes and request-context middleware. The actor comes
    from the development identity headers (`X-Dev-Role` / `X-Dev-User-Id`), exactly as
    the router resolves it; only the repository and the PM service (the server's
    TEST/REAL setting) are overridden. `role=None` sends no identity headers."""
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_pm_service, get_repository
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_pm_service] = lambda: PmService(repo, MeterService(repo), assignment_cutover=cutover)
    headers = {} if role is None else {"X-Dev-Role": role, "X-Dev-User-Id": user_id}
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as client:
        return await client.get(f"/api/v1{path}", headers=headers)


def master_state_of(repo) -> tuple:
    return (dict(repo._pm_work_orders), repo._pm_master_memberships, dict(repo._meter_snapshots),
            dict(repo._pm_submit_meter_anchors), {k: list(v) for k, v in repo._pm_transitions.items()},
            dict(repo._pm_task_revisions), dict(repo._pm_item_outcomes))


VIEWER_ROLE = "TECHNICIAN"  # holds can_view (and no PM Master authority)
DENIED_ROLES = ("SYN-RT3B-NO-SUCH-ROLE",)  # an unrecognized role grants nothing (authz fails closed)


async def test_rt3b_01_a_same_scope_master_catalogue_needs_a_can_view_actor() -> None:
    repo, _, servers, revisions = await three_scope_catalogues()
    before = master_state_of(repo)
    for scope in ("TEST-A", "TEST-B", "REAL"):
        for path in plan_paths(revisions[scope]):
            allowed = await http_get_as(path, repo, servers[scope], VIEWER_ROLE)
            assert (allowed.status_code, allowed.json()["revision"]["revision_id"]) == (
                200, revisions[scope].revision_id)
            for role in DENIED_ROLES:
                denied = await http_get_as(path, repo, servers[scope], role)
                assert denied.status_code == 403, (scope, path, role)
                assert '"tasks"' not in denied.text and revisions[scope].revision_id not in denied.text
    assert master_state_of(repo) == before  # no GET (allowed or refused) writes anything


async def test_rt3b_02_authorization_is_checked_before_scope_or_existence_is_disclosed() -> None:
    repo, _, servers, revisions = await three_scope_catalogues()
    missing = f"{RUNTIME_PLAN_PREFIX}{'0' * 20}"
    paths = (*plan_paths(revisions["TEST-B"]), *plan_paths(revisions["REAL"]),  # foreign to TEST-A
             f"/pm/plans/{missing}/active-revision", f"/pm/plans/{missing}/revisions/PMMREV-NONE")
    for path in paths:  # a refused actor learns neither existence (404) nor ownership nor configuration (503)
        assert (await http_get_as(path, repo, servers["TEST-A"], DENIED_ROLES[0])).status_code == 403, path
        assert (await http_get_as(path, repo, cut(context=None), DENIED_ROLES[0])).status_code == 403, path
    for path in paths:  # an authorized actor still gets the RT3-A R2 scope result: not found
        assert (await http_get_as(path, repo, servers["TEST-A"], VIEWER_ROLE)).status_code == 404, path
    for path in plan_paths(revisions["TEST-A"]):
        assert (await http_get_as(path, repo, cut(context=None), VIEWER_ROLE)).status_code == 503  # never REAL


async def test_rt3b_03_direct_service_calls_cannot_bypass_the_gate() -> None:
    repo, _, servers, revisions = await three_scope_catalogues()
    svc = PmService(repo, MeterService(repo), assignment_cutover=servers["TEST-A"])
    plan_id, revision_id = runtime_plan_id_of(revisions["TEST-A"]), revisions["TEST-A"].revision_id
    refused = (None, "not-a-context", ctx("SYN-RT3B-NOBODY"), ctx("SYN-RT3B-PM", authz.CAN_MANAGE_PM),
               replace(ctx("ignored", authz.CAN_VIEW), user_id=None),  # untrusted: no authenticated user
               replace(ctx("ignored", authz.CAN_VIEW), user_id="  "))
    before = master_state_of(repo)
    for context in refused:
        for call in (svc.get_active_task_revision(plan_id, context), svc.get_task_revision(plan_id, revision_id,
                                                                                            context)):
            with pytest.raises(Exception) as denied:
                await call
            assert getattr(denied.value, "status_code", None) == 403, context
    with pytest.raises(ApiError) as internal:  # the internal default (no actor) is refused too
        await svc.get_active_task_revision(plan_id)
    assert internal.value.status_code == 403 and master_state_of(repo) == before
    viewer = ctx("SYN-RT3B-VIEWER", authz.CAN_VIEW)
    assert (await svc.get_active_task_revision(plan_id, viewer)).revision.revision_id == revision_id
    assert (await svc.get_task_revision(plan_id, revision_id, viewer)).revision.revision_id == revision_id


async def test_rt3b_04_seed_catalogue_reads_keep_their_phase_4_behaviour(monkeypatch) -> None:
    import app.api.v1.pm as pm_routes

    repo, _, servers, revisions = await three_scope_catalogues()
    seed = ("/pm/plans/PMP-0001/active-revision", "/pm/plans/PMP-0001/revisions/PMREV-0001")
    for cutover in (*servers.values(), cut(context=None)):
        for role in (None, *DENIED_ROLES, VIEWER_ROLE):  # anonymous / capability-less reads stay allowed
            for path in seed:
                response = await http_get_as(path, repo, cutover, role)
                assert (response.status_code, response.json()["revision"]["revision_id"]) == (200, "PMREV-0001")
    svc = PmService(repo, MeterService(repo), assignment_cutover=servers["TEST-A"])
    assert (await svc.get_active_task_revision("PMP-0001")).revision.revision_id == "PMREV-0001"  # internal call
    assert (await svc.get_task_revision("PMP-0001", "PMREV-0001", None)).revision.revision_id == "PMREV-0001"

    async def resolution_fails(*_args, **_kwargs):  # e.g. an Access Management resolution that cannot complete
        raise RuntimeError("synthetic actor-resolution failure")

    monkeypatch.setattr(pm_routes, "get_current_context", resolution_fails)
    for path in seed:  # a seed read never resolves an actor, so it is unaffected
        assert (await http_get_as(path, repo, servers["TEST-A"], None)).status_code == 200
    for path in plan_paths(revisions["TEST-A"]):  # a Master read always does (it cannot be skipped)
        assert (await http_get_as(path, repo, servers["TEST-A"], VIEWER_ROLE)).status_code == 500


def test_rt3b_05_the_discriminator_imports_nothing_and_is_not_authority() -> None:
    assert PmService.is_master_catalogue_id(f"{RUNTIME_PLAN_PREFIX}abc") is True
    assert PmService.is_master_catalogue_id("PMP-0001") is False
    assert PmService.is_master_catalogue_id(None) is False  # type: ignore[arg-type]
    script = ("import sys; from app.api.v1 import pm; from app.domain.pm_service import PmService; "
              "PmService.is_master_catalogue_id('PMMP-x'); "
              "print(sorted(m for m in sys.modules if m.startswith('app.domain.pm_master')))")
    out = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, capture_output=True, text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == "[]"
