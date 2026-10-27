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


def item_for(work_order_id, *, task="PMT-0002", revision="PMREV-0001", reason="TEST-NOT-DONE", other=None,
             origin_result=None, created_at=T0 + timedelta(hours=1), created_by="SYNTH-SUP"):
    outcome = build_pm_item_outcome(
        pm_work_order_id=work_order_id, pm_task_id=task, revision_id=revision, disposition=Disposition.NOT_PERFORMED,
        recorded_at=T0, approved_not_performed_reasons=REASONS, approved_other_reason_code="TEST-OTHER",
        reason_code=reason, other_text=other, recorded_by="SYNTH-TECH", source_pm_work_result_id=origin_result)
    return build_pm_outstanding_item(outcome, created_by=created_by, created_at=created_at)


def pm_state(repo: MockRepository):
    """Everything B02-A must never touch: work orders, immutable results,
    meter snapshots (due-anchor inputs) and assignment history."""
    return copy.deepcopy((repo._pm_work_orders, repo._pm_work_results, repo._meter_snapshots,
                          repo._pm_assignment_history, repo._pm_task_revisions, repo._pm_tasks))


async def test_b02a_05_create_and_read_back_in_mock():
    repo = MockRepository()
    wo = await open_work_order(repo)
    item = item_for(wo.pm_work_order_id)
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
    item = item_for(wo.pm_work_order_id)
    await repo.create_pm_outstanding_item(item)
    replay = item_for(wo.pm_work_order_id, created_at=T0 + timedelta(days=3), created_by="SYNTH-OTHER")
    stored, replayed = await repo.create_pm_outstanding_item(replay)
    assert replayed and stored == item  # the original record is kept, not overwritten
    before = copy.deepcopy(repo._pm_outstanding)
    conflict = item_for(wo.pm_work_order_id, reason="TEST-OTHER", other="อื่น ๆ")
    with pytest.raises(ValueError, match="PM_OUTSTANDING_IDENTITY_CONFLICT"):
        await repo.create_pm_outstanding_item(conflict)
    assert repo._pm_outstanding == before and len(await repo.list_pm_outstanding_items(wo.pm_work_order_id)) == 1
    other_task = item_for(wo.pm_work_order_id, task="PMT-0003")  # a different source identity is independent
    assert (await repo.create_pm_outstanding_item(other_task))[1] is False
    assert len(await repo.list_pm_outstanding_items(wo.pm_work_order_id)) == 2


async def test_b02a_07_outstanding_stays_readable_after_the_source_work_order_is_closed():
    repo = MockRepository()
    wo = await open_work_order(repo)
    item = item_for(wo.pm_work_order_id)
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
    item = item_for(wo.pm_work_order_id, origin_result=result.pm_work_result_id)
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
    assert not [n for n in dir(MockRepository) if "outstanding" in n and "resol" in n]  # no resolution writer


async def test_b02a_11_existing_pm_service_and_api_behave_as_before(client):
    opened = await client.post("/api/v1/pm/work-orders", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046",
                                                               "pm_plan_id": "PMP-0001"})
    assert opened.status_code == 200 and opened.json()["work_order"]["status"] == "OPEN"
    wo_id = opened.json()["work_order"]["pm_work_order_id"]
    result = await client.post(f"/api/v1/pm/work-orders/{wo_id}/results",
                               json={"pm_task_id": "PMT-0001", "completed": False})
    assert result.status_code == 200 and result.json()["results"][0]["completed"] is False
    closed = await client.post(f"/api/v1/pm/work-orders/{wo_id}/close", json={})
    assert closed.status_code == 200 and closed.json()["work_order"]["status"] == "CLOSED"
    assert "outstanding" not in str(closed.json()).lower()  # no new runtime field surfaced
    from app.main import create_app
    assert not [r.path for r in create_app().routes if "outstanding" in getattr(r, "path", "").lower()]
