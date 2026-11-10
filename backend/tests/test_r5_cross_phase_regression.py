"""R5 T8 — cross-phase regression: frozen lifecycles, Technician V2-only rules,
legacy retirement, TEAM_ELAPSED separation, R3 completion scope, vehicle status
independence (RM-13) and the R5 cancellation blockers."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.domain import pm as pm_domain
from app.domain.pm import PmE01ContractAction as A
from app.domain.pm import PmE01ContractState as S
from app.domain.pm import PmWorkOrderStatus
from app.domain.repair import RepairStatus
from app.domain.work_time import WORK_KIND_PM, WORK_KIND_REPAIR
from tests.pm_e01_support import manager as pm_mgr
from tests.test_r5_work_time_api import (
    MANAGER,
    U1,
    pm_job_started,
    record,
    repair_job,
    repair_manager,
    rid,
    svc,
    t,
)
from tests.test_technician_assignment_batch_r2f_h1 import code_of, ctx, http, pm_service, repair_service, repo_with

APP = Path(__file__).resolve().parents[1] / "app"


def test_canonical_lifecycles_are_unchanged() -> None:
    assert {m.value for m in RepairStatus} == {"OPEN", "CLOSED", "CANCELLED"}
    assert {m.value for m in PmWorkOrderStatus} == {"OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CLOSED", "CANCELLED"}
    assert pm_domain._PM_E01_CONTRACT_EDGES == {
        (S.OPEN, A.START): S.IN_PROGRESS, (S.IN_PROGRESS, A.SUBMIT): S.PENDING_REVIEW,
        (S.PENDING_REVIEW, A.RETURN): S.IN_PROGRESS, (S.PENDING_REVIEW, A.CLOSE): S.CLOSED}


def test_actual_man_hours_never_read_the_planned_team_elapsed_duration() -> None:
    for name in ("work_time.py", "work_time_service.py", "vehicle_status_events.py"):
        source = (APP / "domain" / name).read_text(encoding="utf-8")
        assert "planned_team_minutes" not in source
        assert "TEAM_ELAPSED" not in source.replace("planned TEAM_ELAPSED duration of R4", "")
    from app.domain.pm_service import planned_team_minutes

    assert inspect.signature(planned_team_minutes).parameters.keys() == {"raw"}  # R4 helper untouched


def test_no_legacy_assignment_or_on_off_setting_is_reintroduced() -> None:
    for name in ("work_time.py", "work_time_service.py", "vehicle_status_events.py"):
        source = (APP / "domain" / name).read_text(encoding="utf-8")
        assert "primary_technician:" not in source and "TECHNICIAN_ASSIGNMENT_V2_ENABLED" not in source
        assert "assign_repair" not in source and "LEGACY" not in source


@pytest.mark.asyncio
async def test_retired_legacy_routes_still_answer_410() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    for method, path in (("GET", "/api/v1/repairs/my-work"), ("POST", f"/api/v1/repairs/{job}/assign"),
                         ("GET", "/api/v1/repairs/waiting-assignment")):
        response = await http(method, path, repo, json={} if method == "POST" else None)
        assert response.status_code == 410, (path, response.text)


@pytest.mark.asyncio
async def test_repair_completion_stays_limited_to_r3_finding_rounds() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    assert await code_of(repair_service(repo).submit_completion(job, ctx(U1), request_id=rid(), expected_set_id=None,
                                                                note=None)) == "REPAIR_NOT_R3_ROUND"


@pytest.mark.asyncio
async def test_rm13_work_order_activity_never_writes_the_vehicle_status() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    vehicle_id = (await repo.get_repair(job)).repair.asset_id
    before = (await repo.get_vehicle(vehicle_id), await repo.list_vehicle_status_history(vehicle_id))
    entry, _ = await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(2))
    from tests.test_r5_work_time_api import confirm

    await confirm(svc(repo), WORK_KIND_REPAIR, job, repair_manager(), (entry.entry_id, 1))
    await repair_service(repo).close_repair(job, closed_by=MANAGER, close_note=None, context=repair_manager())
    assert (await repo.get_vehicle(vehicle_id), await repo.list_vehicle_status_history(vehicle_id)) == before


@pytest.mark.asyncio
async def test_recorded_work_time_blocks_an_r3_round_cancellation() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    repo._repairs[job] = repo._repairs[job].model_copy(update={"finding_id": "F-SYN-R5"})
    await record(svc(repo), WORK_KIND_REPAIR, job, ctx(U1), t(0), t(1))
    finding_manager = ctx(MANAGER, "can_manage_finding_repair")
    from app.errors import ApiError

    with pytest.raises(ApiError) as refused:
        await repair_service(repo).cancel_repair(job, finding_manager, reason="ยกเลิกทดสอบ")
    assert refused.value.code == "REPAIR_WORK_ALREADY_STARTED"
    assert refused.value.details["recorded_work"] == ["WORK_TIME"]
    assert (await repo.get_repair(job)).repair.status == RepairStatus.OPEN


@pytest.mark.asyncio
async def test_recorded_work_time_blocks_a_pm_cancellation() -> None:
    repo = repo_with()
    job = await pm_job_started(repo)
    await record(svc(repo), WORK_KIND_PM, job, ctx(U1), t(0), t(1))
    from app.errors import ApiError

    with pytest.raises(ApiError) as refused:
        await pm_service(repo).cancel_work_order(job, pm_mgr(), request_id=rid(), reason="ยกเลิกทดสอบ")
    assert refused.value.code == "PM_CANCEL_NOT_ELIGIBLE" and "WORK_TIME" in refused.value.details["blockers"]
    assert (await repo.get_pm_work_order(job)).work_order.status == PmWorkOrderStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_cancellation_without_r5_records_is_unchanged() -> None:
    repo = repo_with()
    job = await repair_job(repo)
    repo._repairs[job] = repo._repairs[job].model_copy(update={"finding_id": "F-SYN-R5"})
    cancelled = await repair_service(repo).cancel_repair(job, ctx(MANAGER, "can_manage_finding_repair"),
                                                         reason="ยกเลิกก่อนเริ่มงาน")
    assert cancelled.repair.status == RepairStatus.CANCELLED
