"""R4-PM-WF-01 B02-A: Mock persistence of Outstanding records (synthetic data
only) and adapter / runtime compatibility. No Google Sheets, TEST or REAL."""
import copy
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.asset import AssetType
from app.domain.pm import (
    PmItemContractDisposition as Disposition,
    PmWorkOrderStatus,
    build_pm_item_outcome,
    build_pm_outstanding_item,
)
from app.repositories.base import Repository, RepositoryFeatureNotImplementedError
from app.repositories.google_sheets.repository import GoogleSheetsRepository
from app.repositories.mock.repository import MockRepository

REASONS = frozenset({"TEST-NOT-DONE", "TEST-OTHER"})  # synthetic, not Owner codes
T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
SCOPE = ["PMT-0001", "PMT-0002", "PMT-0003"]  # tasks of the non-authoritative PLAN1 seed revision


async def open_work_order(repo: MockRepository):
    return await repo.create_pm_work_order(AssetType.VEHICLE, "VEH-1046", "PMP-0001", "PMREV-0001", None,
                                           "SYNTH-SUP", None, scope_task_ids=list(SCOPE))


def outcome_for(work_order_id, *, task="PMT-0002", revision="PMREV-0001", reason="TEST-NOT-DONE", other=None,
                origin_result=None):
    return build_pm_item_outcome(
        pm_work_order_id=work_order_id, pm_task_id=task, revision_id=revision, disposition=Disposition.NOT_PERFORMED,
        recorded_at=T0, approved_not_performed_reasons=REASONS, approved_other_reason_code="TEST-OTHER",
        reason_code=reason, other_text=other, recorded_by="SYNTH-TECH", source_pm_work_result_id=origin_result)


def item_for(work_order_id, *, created_at=T0 + timedelta(hours=1), created_by="SYNTH-SUP", **kw):
    return build_pm_outstanding_item(outcome_for(work_order_id, **kw), created_by=created_by, created_at=created_at)


async def stored_item_for(repo, work_order_id, **kw):
    """R4 PM Workflow G1: an Outstanding record needs its stored NOT_PERFORMED
    Outcome first (repository-enforced), so store it before the record."""
    outcome_kw = {k: v for k, v in kw.items() if k not in ("created_at", "created_by")}
    await repo.create_pm_item_outcome(outcome_for(work_order_id, **outcome_kw))
    return item_for(work_order_id, **kw)


def pm_state(repo: MockRepository):
    """Everything B02-A must never touch: work orders, immutable results,
    meter snapshots (due-anchor inputs) and assignment history."""
    return copy.deepcopy((repo._pm_work_orders, repo._pm_work_results, repo._meter_snapshots,
                          repo._pm_assignment_history, repo._pm_task_revisions, repo._pm_tasks))


async def test_b02a_05_create_and_read_back_in_mock():
    repo = MockRepository()
    wo = await open_work_order(repo)
    item = await stored_item_for(repo, wo.pm_work_order_id)
    stored, replayed = await repo.create_pm_outstanding_item(item)
    assert (stored, replayed) == (item, False)
    assert await repo.get_pm_outstanding_item(item.outstanding_id) == item
    assert await repo.list_pm_outstanding_items(wo.pm_work_order_id) == [item]
    assert await repo.list_pm_outstanding_items("SYNTH-OTHER-WO") == []
    assert await repo.get_pm_outstanding_item("PMOS-unknown") is None
    read = await repo.get_pm_outstanding_item(item.outstanding_id)
    assert read is not repo._pm_outstanding[item.outstanding_id]  # callers get copies, never the stored object


async def test_b02a_06_identical_replay_is_idempotent_and_conflicting_reuse_fails_closed():
    repo = MockRepository()
    wo = await open_work_order(repo)
    item = await stored_item_for(repo, wo.pm_work_order_id)
    await repo.create_pm_outstanding_item(item)
    replay = item_for(wo.pm_work_order_id, created_at=T0 + timedelta(days=3), created_by="SYNTH-OTHER")
    stored, replayed = await repo.create_pm_outstanding_item(replay)
    assert replayed and stored == item  # the original record is kept, not overwritten
    before = copy.deepcopy(repo._pm_outstanding)
    conflict = item_for(wo.pm_work_order_id, reason="TEST-OTHER", other="อื่น ๆ")
    # R4 PM Workflow G1: a conflicting record can no longer match its stored source Outcome, so the
    # repository refuses it at the provenance check (before the identity-conflict check); still no write.
    with pytest.raises(ValueError, match="PM_OUTSTANDING_PROVENANCE_MISMATCH"):
        await repo.create_pm_outstanding_item(conflict)
    assert repo._pm_outstanding == before and len(await repo.list_pm_outstanding_items(wo.pm_work_order_id)) == 1
    other_task = await stored_item_for(repo, wo.pm_work_order_id, task="PMT-0003")  # independent source identity
    assert (await repo.create_pm_outstanding_item(other_task))[1] is False
    assert len(await repo.list_pm_outstanding_items(wo.pm_work_order_id)) == 2


async def test_b02a_07_outstanding_stays_readable_after_the_source_work_order_is_closed():
    repo = MockRepository()
    wo = await open_work_order(repo)
    item = await stored_item_for(repo, wo.pm_work_order_id)
    await repo.create_pm_outstanding_item(item)
    # Synthetic: the existing legacy OPEN -> CLOSED close (no new partial-close runtime is involved).
    await repo.close_pm_work_order(wo.pm_work_order_id, "SYNTH-SUP", None)
    assert repo._pm_work_orders[wo.pm_work_order_id].status == PmWorkOrderStatus.CLOSED
    assert await repo.get_pm_outstanding_item(item.outstanding_id) == item
    assert await repo.list_pm_outstanding_items(wo.pm_work_order_id) == [item]


async def test_b02a_09_outstanding_never_changes_due_anchors_snapshots_or_history():
    repo = MockRepository()
    wo = await open_work_order(repo)
    result = await repo.create_pm_work_result(wo.pm_work_order_id, "PMT-0002", "PMREV-0001", 2, "งานตัวอย่าง",
                                              False, None, None, [], [], "SYNTH-TECH")
    await repo.close_pm_work_order(wo.pm_work_order_id, "SYNTH-SUP", None)
    last_closed = await repo.get_last_closed_pm_work_order(AssetType.VEHICLE, "VEH-1046", "PMP-0001")
    before = pm_state(repo)
    # R4 PM Workflow G1: the source Outcome is stored first (it is not part of the protected state).
    item = await stored_item_for(repo, wo.pm_work_order_id, origin_result=result.pm_work_result_id)
    await repo.create_pm_outstanding_item(item)
    await repo.create_pm_outstanding_item(item)  # replay
    await repo.get_pm_outstanding_item(item.outstanding_id)
    await repo.list_pm_outstanding_items(wo.pm_work_order_id)
    assert pm_state(repo) == before  # work orders, results, meter snapshots, assignments unchanged
    assert await repo.get_last_closed_pm_work_order(AssetType.VEHICLE, "VEH-1046", "PMP-0001") == last_closed
    assert (await repo.find_pm_work_result(result.pm_work_result_id)) == result  # immutable result intact


@pytest.mark.parametrize("kwargs,code", [
    ({"work_order": "PMWO-9999"}, "PM_OUTSTANDING_SOURCE_NOT_FOUND"),
    ({"revision": "PMREV-9999"}, "PM_OUTSTANDING_SOURCE_REVISION_MISMATCH"),
    ({"task": "PMT-9999"}, "PM_OUTSTANDING_SOURCE_TASK_NOT_IN_SCOPE"),
    ({"origin_result": "PMWR-9999"}, "PM_OUTSTANDING_ORIGIN_RESULT_INVALID"),
])
async def test_b02a_negative_invalid_source_is_refused_without_writing(kwargs, code):
    repo = MockRepository()
    wo = await open_work_order(repo)
    work_order = kwargs.pop("work_order", wo.pm_work_order_id)
    before = (copy.deepcopy(repo._pm_outstanding), pm_state(repo))
    with pytest.raises(ValueError, match=code):
        await repo.create_pm_outstanding_item(item_for(work_order, **kwargs))
    assert (repo._pm_outstanding, pm_state(repo)) == before


async def test_b02a_negative_origin_result_of_another_task_and_tampered_id_are_refused():
    repo = MockRepository()
    wo = await open_work_order(repo)
    other = await repo.create_pm_work_result(wo.pm_work_order_id, "PMT-0001", "PMREV-0001", 1, "งาน 1", True, None,
                                             None, [], [], "SYNTH-TECH")
    with pytest.raises(ValueError, match="PM_OUTSTANDING_ORIGIN_RESULT_INVALID"):
        await repo.create_pm_outstanding_item(item_for(wo.pm_work_order_id, origin_result=other.pm_work_result_id))
    tampered = item_for(wo.pm_work_order_id).model_copy(update={"outstanding_id": "PMOS-forged"})
    with pytest.raises(ValueError, match="PM_OUTSTANDING_ID_INVALID"):
        await repo.create_pm_outstanding_item(tampered)
    assert repo._pm_outstanding == {}


async def test_b02a_11_adapters_remain_compatible_and_sheets_refuses_explicitly():
    assert not inspect.isabstract(MockRepository) and not inspect.isabstract(GoogleSheetsRepository)
    for name in ("create_pm_outstanding_item", "get_pm_outstanding_item", "list_pm_outstanding_items"):
        assert not getattr(getattr(Repository, name), "__isabstractmethod__", False)  # never abstract
        assert getattr(GoogleSheetsRepository, name) is getattr(Repository, name)  # Sheets adapter untouched
    sheets = object.__new__(GoogleSheetsRepository)  # no client / no network: the base refusal needs no state
    item = item_for("SYNTH-PMWO-1")
    for call in (sheets.create_pm_outstanding_item(item), sheets.get_pm_outstanding_item(item.outstanding_id),
                 sheets.list_pm_outstanding_items("SYNTH-PMWO-1")):
        with pytest.raises(RepositoryFeatureNotImplementedError) as refused:
            await call
        assert refused.value.feature == "pm_outstanding"
    # R4 PM Workflow: the only resolution writer is the approved repository method, and the Sheets
    # adapter inherits its explicit refusal (was: no resolution writer at all in B02-A).
    assert [n for n in dir(MockRepository) if "outstanding" in n and "resol" in n and n.startswith("create")] == [
        "create_pm_outstanding_resolution"]
    assert GoogleSheetsRepository.create_pm_outstanding_resolution is Repository.create_pm_outstanding_resolution


async def test_b02a_11_existing_pm_service_and_api_behave_as_before(client):
    opened = await client.post("/api/v1/pm/work-orders", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046",
                                                               "pm_plan_id": "PMP-0001"})
    assert opened.status_code == 200 and opened.json()["work_order"]["status"] == "OPEN"
    wo_id = opened.json()["work_order"]["pm_work_order_id"]
    # R4 PM Workflow: a V2 job can no longer bypass E01 through the legacy result / direct close
    # (was: both succeeded on an OPEN job). Nothing is written and no Outstanding is surfaced.
    result = await client.post(f"/api/v1/pm/work-orders/{wo_id}/results",
                               json={"pm_task_id": "PMT-0001", "completed": False})
    assert result.status_code == 409 and result.json()["error"]["code"] == "PM_E01_ITEM_SAVE_REQUIRED"
    closed = await client.post(f"/api/v1/pm/work-orders/{wo_id}/close", json={})
    assert closed.status_code == 422 and closed.json()["error"]["code"] == "REQUEST_ID_REQUIRED"
    detail = await client.get(f"/api/v1/pm/work-orders/{wo_id}")
    assert detail.json()["work_order"]["status"] == "OPEN" and detail.json()["results"] == []
    assert "outstanding" not in str(detail.json()).lower()  # no Outstanding field on the work order itself
