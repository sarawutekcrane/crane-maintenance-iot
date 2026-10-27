"""R4-PM-WF-01 B02-B1: Mock persistence of PM item outcomes (synthetic data
only) and adapter / runtime compatibility. No Google Sheets, TEST or REAL."""
import copy
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.asset import AssetType
from app.domain.pm import (
    PmItemContractDisposition as Disposition,
    build_pm_item_outcome,
    build_pm_outstanding_item,
)
from app.repositories.base import Repository, RepositoryFeatureNotImplementedError
from app.repositories.google_sheets.repository import GoogleSheetsRepository
from app.repositories.mock.repository import MockRepository

REASONS = frozenset({"TEST-NOT-DONE", "TEST-OTHER"})  # synthetic, not Owner codes
ACTIONS = frozenset({"TEST-CHECK", "TEST-CLEAN"})
T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
SCOPE = ["PMT-0001", "PMT-0002", "PMT-0003"]  # tasks of the non-authoritative PLAN1 seed revision


async def open_work_order(repo: MockRepository):
    return await repo.create_pm_work_order(AssetType.VEHICLE, "VEH-1046", "PMP-0001", "PMREV-0001", None,
                                           "SYNTH-SUP", None, scope_task_ids=list(SCOPE))


def outcome_for(work_order_id, disposition=Disposition.NOT_PERFORMED, *, task="PMT-0002", revision="PMREV-0001",
                reason="TEST-NOT-DONE", other=None, actions=("TEST-CHECK",), evidence=(), source_result=None,
                recorded_by="SYNTH-TECH", recorded_at=T0):
    performed = disposition == Disposition.PERFORMED
    return build_pm_item_outcome(
        pm_work_order_id=work_order_id, pm_task_id=task, revision_id=revision, disposition=disposition,
        recorded_at=recorded_at, approved_not_performed_reasons=REASONS, approved_other_reason_code="TEST-OTHER",
        approved_performed_actions=ACTIONS, performed_actions=actions if performed else (),
        reason_code=None if performed else reason, other_text=other, evidence_attachment_ids=evidence,
        recorded_by=recorded_by, source_pm_work_result_id=source_result)


def pm_state(repo: MockRepository):
    """Everything B02-B1 must never touch: work orders, immutable results,
    meter snapshots (due-anchor inputs), assignment history, revisions/tasks
    and B02-A Outstanding records."""
    return copy.deepcopy((repo._pm_work_orders, repo._pm_work_results, repo._meter_snapshots,
                          repo._pm_assignment_history, repo._pm_task_revisions, repo._pm_tasks,
                          repo._pm_outstanding))


async def test_b02b1_01_persist_performed():
    repo = MockRepository()
    wo = await open_work_order(repo)
    out = outcome_for(wo.pm_work_order_id, Disposition.PERFORMED, actions=("TEST-CHECK", "TEST-CLEAN"),
                      evidence=("SYNTH-ATT-1",))
    stored, replayed = await repo.create_pm_item_outcome(out)
    assert (stored, replayed) == (out, False)
    read = await repo.get_pm_item_outcome(out.outcome_id)
    assert read == out and read.disposition == Disposition.PERFORMED
    assert read.performed_actions == ("TEST-CHECK", "TEST-CLEAN") and read.reason_code is None


async def test_b02b1_02_persist_not_performed_with_other_text():
    repo = MockRepository()
    wo = await open_work_order(repo)
    out = outcome_for(wo.pm_work_order_id, reason="TEST-OTHER", other="พื้นที่ปิดซ่อม")
    assert (await repo.create_pm_item_outcome(out)) == (out, False)
    read = await repo.get_pm_item_outcome(out.outcome_id)
    assert (read.disposition, read.reason_code, read.other_text, read.performed_actions) == (
        Disposition.NOT_PERFORMED, "TEST-OTHER", "พื้นที่ปิดซ่อม", ())


async def test_b02b1_07_identical_replay_does_not_duplicate():
    repo = MockRepository()
    wo = await open_work_order(repo)
    out = outcome_for(wo.pm_work_order_id, evidence=("SYNTH-ATT-1",))
    await repo.create_pm_item_outcome(out)
    stored, replayed = await repo.create_pm_item_outcome(outcome_for(wo.pm_work_order_id, evidence=("SYNTH-ATT-1",)))
    assert replayed is True and stored == out
    assert await repo.list_pm_item_outcomes(wo.pm_work_order_id) == [out]


@pytest.mark.parametrize("changes", [
    {"disposition": Disposition.PERFORMED},
    {"reason": "TEST-OTHER", "other": "อื่น ๆ"},
    {"evidence": ("SYNTH-ATT-2",)},
    {"recorded_by": "SYNTH-OTHER"},  # a different actor is never silently substituted
    {"recorded_at": T0 + timedelta(minutes=5)},
])
async def test_b02b1_08_conflicting_replay_fails_closed_without_mutation(changes):
    repo = MockRepository()
    wo = await open_work_order(repo)
    original = outcome_for(wo.pm_work_order_id, evidence=("SYNTH-ATT-1",))
    await repo.create_pm_item_outcome(original)
    before = (copy.deepcopy(repo._pm_item_outcomes), pm_state(repo))
    conflict = outcome_for(wo.pm_work_order_id, **({"evidence": ("SYNTH-ATT-1",)} | changes))
    assert conflict.outcome_id == original.outcome_id
    with pytest.raises(ValueError, match="PM_ITEM_OUTCOME_IDENTITY_CONFLICT"):
        await repo.create_pm_item_outcome(conflict)
    assert (repo._pm_item_outcomes, pm_state(repo)) == before
    assert await repo.get_pm_item_outcome(original.outcome_id) == original


async def test_b02b1_09_complete_readback_with_defensive_copies_and_no_original_mutation():
    repo = MockRepository()
    wo = await open_work_order(repo)
    legacy = await repo.create_pm_work_result(wo.pm_work_order_id, "PMT-0001", "PMREV-0001", 1, "งาน 1", True, None,
                                              None, [], [], "SYNTH-TECH")
    legacy_before = legacy.model_copy(deep=True)
    a = outcome_for(wo.pm_work_order_id, Disposition.PERFORMED, task="PMT-0001", evidence=("SYNTH-ATT-1",),
                    source_result=legacy.pm_work_result_id)
    b = outcome_for(wo.pm_work_order_id, task="PMT-0003")
    await repo.create_pm_item_outcome(a)
    await repo.create_pm_item_outcome(b)
    assert await repo.list_pm_item_outcomes(wo.pm_work_order_id) == [a, b]
    assert await repo.list_pm_item_outcomes("SYNTH-OTHER-WO") == []
    assert await repo.get_pm_item_outcome("PMOC-unknown") is None
    read = await repo.get_pm_item_outcome(a.outcome_id)
    assert read.model_dump() == a.model_dump()  # every field, including provenance
    assert read is not repo._pm_item_outcomes[a.outcome_id]
    assert all(o is not repo._pm_item_outcomes[o.outcome_id] for o in await repo.list_pm_item_outcomes(
        wo.pm_work_order_id))
    assert await repo.find_pm_work_result(legacy.pm_work_result_id) == legacy_before  # original result untouched


@pytest.mark.parametrize("kwargs,code", [
    ({"work_order": "PMWO-9999"}, "PM_ITEM_OUTCOME_SOURCE_NOT_FOUND"),
    ({"revision": "PMREV-9999"}, "PM_ITEM_OUTCOME_SOURCE_REVISION_MISMATCH"),
    ({"task": "PMT-9999"}, "PM_ITEM_OUTCOME_SOURCE_TASK_NOT_IN_SCOPE"),
    ({"source_result": "PMWR-9999"}, "PM_ITEM_OUTCOME_SOURCE_RESULT_INVALID"),
])
async def test_b02b1_10_invalid_source_is_rejected_without_writing(kwargs, code):
    repo = MockRepository()
    wo = await open_work_order(repo)
    work_order = kwargs.pop("work_order", wo.pm_work_order_id)
    before = (copy.deepcopy(repo._pm_item_outcomes), pm_state(repo))
    with pytest.raises(ValueError, match=code):
        await repo.create_pm_item_outcome(outcome_for(work_order, **kwargs))
    assert (repo._pm_item_outcomes, pm_state(repo)) == before


async def test_b02b1_10_negative_result_of_other_task_and_tampered_record_are_refused():
    repo = MockRepository()
    wo = await open_work_order(repo)
    other = await repo.create_pm_work_result(wo.pm_work_order_id, "PMT-0001", "PMREV-0001", 1, "งาน 1", True, None,
                                             None, [], [], "SYNTH-TECH")
    with pytest.raises(ValueError, match="PM_ITEM_OUTCOME_SOURCE_RESULT_INVALID"):
        await repo.create_pm_item_outcome(outcome_for(wo.pm_work_order_id, source_result=other.pm_work_result_id))
    valid = outcome_for(wo.pm_work_order_id)
    with pytest.raises(ValueError, match="PM_ITEM_OUTCOME_IDENTITY_INVALID"):
        await repo.create_pm_item_outcome(valid.model_copy(update={"pm_work_order_id": f" {wo.pm_work_order_id}"}))
    with pytest.raises(ValueError, match="PM_ITEM_OUTCOME_RECORD_INVALID"):
        await repo.create_pm_item_outcome(valid.model_copy(update={"disposition": Disposition.PERFORMED}))
    assert repo._pm_item_outcomes == {}
    assert await repo.get_pm_item_outcome("PMOC-forged") is None


async def test_b02b1_negative_legacy_result_is_never_proof_or_trigger():
    """No unauthorized assumption: the legacy `completed` flag neither creates
    nor contradicts an outcome, and nothing else is written."""
    repo = MockRepository()
    wo = await open_work_order(repo)
    done = await repo.create_pm_work_result(wo.pm_work_order_id, "PMT-0002", "PMREV-0001", 2, "งาน 2", True, None,
                                            None, [], [], "SYNTH-TECH")
    assert await repo.list_pm_item_outcomes(wo.pm_work_order_id) == []  # a legacy result creates no outcome
    before = pm_state(repo)
    np = outcome_for(wo.pm_work_order_id, source_result=done.pm_work_result_id)  # completed=True yet NOT_PERFORMED
    assert (await repo.create_pm_item_outcome(np))[1] is False
    assert pm_state(repo) == before and repo._pm_outstanding == {}  # no Outstanding auto-created


async def test_b02b1_13_no_due_anchor_history_or_meter_change():
    repo = MockRepository()
    wo = await open_work_order(repo)
    await repo.create_pm_work_result(wo.pm_work_order_id, "PMT-0001", "PMREV-0001", 1, "งาน 1", True, None,
                                     None, [], [], "SYNTH-TECH")
    np = outcome_for(wo.pm_work_order_id)
    await repo.create_pm_outstanding_item(build_pm_outstanding_item(np, created_by="SYNTH-SUP",
                                                                    created_at=T0 + timedelta(hours=1)))
    await repo.close_pm_work_order(wo.pm_work_order_id, "SYNTH-SUP", None)
    last_closed = await repo.get_last_closed_pm_work_order(AssetType.VEHICLE, "VEH-1046", "PMP-0001")
    before = pm_state(repo)
    await repo.create_pm_item_outcome(np)
    await repo.create_pm_item_outcome(np)  # replay
    await repo.create_pm_item_outcome(outcome_for(wo.pm_work_order_id, Disposition.PERFORMED, task="PMT-0001"))
    await repo.get_pm_item_outcome(np.outcome_id)
    await repo.list_pm_item_outcomes(wo.pm_work_order_id)
    assert pm_state(repo) == before  # WOs, results, meters, assignments, revisions, Outstanding unchanged
    assert await repo.get_last_closed_pm_work_order(AssetType.VEHICLE, "VEH-1046", "PMP-0001") == last_closed


async def test_b02b1_11_15_sheets_adapter_concrete_and_refuses_without_io():
    assert inspect.isabstract(Repository)  # the base stays an ABC; only the new methods are concrete
    assert not inspect.isabstract(MockRepository) and not inspect.isabstract(GoogleSheetsRepository)
    for name in ("create_pm_item_outcome", "get_pm_item_outcome", "list_pm_item_outcomes"):
        assert name not in Repository.__abstractmethods__
        assert not getattr(getattr(Repository, name), "__isabstractmethod__", False)
        assert getattr(GoogleSheetsRepository, name) is getattr(Repository, name)  # Sheets adapter untouched
    sheets = object.__new__(GoogleSheetsRepository)  # no client: any Sheets I/O would fail with AttributeError
    out = outcome_for("SYNTH-PMWO-1")
    for call in (sheets.create_pm_item_outcome(out), sheets.get_pm_item_outcome(out.outcome_id),
                 sheets.list_pm_item_outcomes("SYNTH-PMWO-1")):
        with pytest.raises(RepositoryFeatureNotImplementedError) as refused:
            await call
        assert refused.value.feature == "pm_item_outcome"


async def test_b02b1_14_existing_api_behaves_as_before_and_exposes_no_outcome(client):
    opened = await client.post("/api/v1/pm/work-orders", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046",
                                                               "pm_plan_id": "PMP-0001"})
    assert opened.status_code == 200 and opened.json()["work_order"]["status"] == "OPEN"
    wo_id = opened.json()["work_order"]["pm_work_order_id"]
    result = await client.post(f"/api/v1/pm/work-orders/{wo_id}/results",
                               json={"pm_task_id": "PMT-0001", "completed": False})
    assert result.status_code == 200 and result.json()["results"][0]["completed"] is False
    closed = await client.post(f"/api/v1/pm/work-orders/{wo_id}/close", json={})
    assert closed.status_code == 200 and closed.json()["work_order"]["status"] == "CLOSED"  # no partial close
    body = str(closed.json()).lower()
    assert "outcome" not in body and "disposition" not in body
    from app.main import create_app
    assert not [r.path for r in create_app().routes if "outcome" in getattr(r, "path", "").lower()]
