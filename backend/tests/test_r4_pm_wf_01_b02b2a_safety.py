"""R4-PM-WF-01 B02-B2A: safety and isolation of the outcome integration (Mock,
synthetic records): item saves write only the factual result (with its existing
machine-state capture) and the Outcome, no PM Due / history / Store mutation,
exposure only through the approved PM workflow routes, a server-owned
vocabulary, and unsupported adapters failing closed.

R4 PM Workflow (Owner-approved phase) adaptations, intent unchanged: a V2 item
save now also writes its factual `PmWorkResult`; the approved workflow routes
are public; Outstanding records appear only at CLOSE."""
from __future__ import annotations

import copy
import inspect
from pathlib import Path

import pytest

import app.domain.pm_service as pm_service_module
from app.domain import authz
from app.domain.pm import PmItemContractDisposition as Disposition
from app.domain.pm_service import PmService
from app.repositories.base import Repository, RepositoryFeatureNotImplementedError
from tests.test_r4_pm_wf_01_b02b2a_service import CHECK, WAIT_PARTS, code_of, scope_task, v2_job
from tests.test_technician_assignment_batch_r2f_h1 import U1, U3, ctx, new_pm, pm_service, repo_with

BACKEND = Path(__file__).resolve().parents[1]
NEW_NAMES = ("record_item_outcome", "list_item_outcomes", "list_outstanding_items", "_authorize_outcome_access",
             "PmItemOutcomeRecording", "PM_APPROVED_PERFORMED_ACTIONS", "PM_APPROVED_NOT_PERFORMED_REASONS",
             "PM_APPROVED_OTHER_REASON")
APPROVED_CONSUMERS = {"app/domain/pm_service.py", "app/api/v1/pm.py"}
ALLOWED_ITEM_WRITES = {"create_pm_work_result", "create_pm_item_outcome",
                       # the existing machine-state capture of a PM result (MeterService)
                       "create_meter_snapshot", "create_location_snapshot"}
WRITE_PREFIXES = ("create_", "append_", "close_", "assign_", "update_", "add_", "approve_", "delete_",
                  "withdraw", "write_", "set_", "end_", "capture_")


def protected_state(repo):
    """PM Due inputs and every history / Store record an item save must never touch."""
    return copy.deepcopy((repo._pm_work_orders, repo._pm_assignment_history, repo._technician_assignment_rows,
                          repo._material_requests, repo._requisition_lines, repo._attachments,
                          repo._pm_task_revisions, repo._pm_tasks, repo._pm_outstanding, repo._pm_transitions))


async def test_b02b2a_19_only_outcome_records_are_written_no_due_meter_history_or_store_change() -> None:
    repo = repo_with()
    job_id = await v2_job(repo)
    service = pm_service(repo)
    before = protected_state(repo)
    snapshots_before = set(repo._meter_snapshots)
    repo.calls.clear()
    admin = ctx("USR-ADMIN", authz.CAN_MANAGE_PM)
    task1, task2 = await scope_task(repo, job_id, 0), await scope_task(repo, job_id, 1)
    calls = [service.record_item_outcome(job_id, task2, Disposition.PERFORMED, admin, performed_actions=(CHECK,)),
             service.record_item_outcome(job_id, task1, Disposition.NOT_PERFORMED, ctx(U1), reason_code=WAIT_PARTS),
             service.record_item_outcome(job_id, task1, Disposition.NOT_PERFORMED, ctx(U1), reason_code=WAIT_PARTS),
             service.record_item_outcome(job_id, task2, Disposition.PERFORMED, admin, performed_actions=("Y",)),
             service.record_item_outcome(job_id, "PMT-9999", Disposition.PERFORMED, admin),
             service.list_item_outcomes(job_id, ctx(U1)), service.list_outstanding_items(job_id, admin),
             service.list_item_outcomes(job_id, ctx(U3))]
    for call in calls:
        try:
            await call
        except Exception:  # refusals are asserted in the service tests; here only side effects matter
            pass
    writes = {name for name in repo.calls if name.startswith(WRITE_PREFIXES)}
    assert writes == ALLOWED_ITEM_WRITES  # nothing but the item's result, Outcome and its machine state
    assert protected_state(repo) == before  # work orders, assignments, Store, attachments, Outstanding, journal
    assert len(repo._pm_item_outcomes) == 2 and len(repo._pm_work_results[job_id]) == 2
    new = [repo._meter_snapshots[k] for k in set(repo._meter_snapshots) - snapshots_before]
    assert {getattr(s, "source_note", None) for s in new} == {"PM_TASK_RESULT"}


async def test_b02b2a_19_legacy_results_and_close_are_cancelled_for_every_job() -> None:
    """DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107: the Legacy result and direct-close paths no longer
    exist on the service, and a historical Legacy job is refused by the E01 paths and left untouched."""
    repo = repo_with()
    service = pm_service(repo)
    for retired in ("submit_task_result", "close_work_order", "list_assignment_history", "get_active_assignment"):
        assert not hasattr(service, retired), retired
    legacy_id = await new_pm(repo, legacy=True)
    task = (await repo.get_active_pm_task_revision("PMP-0001")).tasks[0].pm_task_id
    repo._pm_work_orders[legacy_id] = repo._pm_work_orders[legacy_id].model_copy(update={"scope_task_ids": [task]})
    before = repo._pm_work_orders[legacy_id]
    manager = ctx("USR-SYN-MANAGER", authz.CAN_MANAGE_PM)
    assert await code_of(service.authorize_recording(legacy_id, manager, authz.CAN_MANAGE_PM, "t")) == (
        409, "ASSIGNMENT_MODEL_MISMATCH")
    assert (await code_of(service.close_after_review(legacy_id, manager, request_id="rid-legacy-close")))[0] == 409
    assert repo._pm_work_orders[legacy_id] == before
    assert repo._pm_work_results.get(legacy_id) in (None, [])
    assert await repo.list_pm_item_outcomes(legacy_id) == [] and await repo.list_pm_outstanding_items(legacy_id) == []
    # A V2 job cannot be closed outside the E01 review either (no bypass).
    job_id = await v2_job(repo)
    status_before = repo._pm_work_orders[job_id].status
    assert (await code_of(service.close_after_review(job_id, manager, request_id="rid-v2-close")))[0] == 409
    assert repo._pm_work_orders[job_id].status == status_before


async def test_b02b2a_21_no_public_api_schema_or_frontend_activation(client) -> None:
    from app.main import create_app
    from tests.test_r4_pm_wf_01_b02a_contract import APPROVED_ROUTE_PATHS, _all_routes
    exposed = {r.path for r in _all_routes(create_app())
               if {"outcome", "outcomes", "outstanding"} & set(getattr(r, "path", "").lower().split("/"))}
    assert exposed == APPROVED_ROUTE_PATHS  # only the approved PM workflow routes
    users = [str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("*.py")
             if str(p.relative_to(BACKEND)) not in APPROVED_CONSUMERS
             and any(n in p.read_text(encoding="utf-8") for n in NEW_NAMES)]
    assert users == []  # no other route module, schema, dependency, adapter or service uses B02-B2A
    frontend = BACKEND.parent / "frontend" / "src"
    if frontend.is_dir():
        assert not [p for p in frontend.rglob("*.ts*")
                    if any(n in p.read_text(encoding="utf-8") for n in NEW_NAMES[:3])]
    opened = await client.post("/api/v1/pm/work-orders", json={"asset_type": "VEHICLE", "asset_id": "VEH-1046",
                                                               "pm_plan_id": "PMP-0001"})
    assert opened.status_code == 200
    assert not {"outcome", "outstanding", "disposition"} & set(str(opened.json()).lower().replace("'", " ").split())


def test_b02b2a_04_vocabulary_is_the_server_owned_fc1_wording() -> None:
    # Owner Agreements, R4 Final Contract FC-1 (Performed / Not Performed), exact wording.
    assert pm_service_module.PM_APPROVED_PERFORMED_ACTIONS == {"ตรวจเช็ค", "ทำความสะอาด", "เปลี่ยน / เติม"}
    assert pm_service_module.PM_APPROVED_NOT_PERFORMED_REASONS == {
        "มีการเปลี่ยนอะไหล่แล้วในการซ่อมครั้งก่อน", "รออะไหล่", "พบความผิดปกติ รอซ่อม", "พื้นที่ไม่เพียงพอ",
        "เวลาไม่เพียงพอ", "อื่น ๆ (ระบุ)"}
    assert pm_service_module.PM_APPROVED_OTHER_REASON == "อื่น ๆ (ระบุ)"
    assert list(inspect.signature(PmService.__init__).parameters) == [
        "self", "repository", "meter_service", "assignment_cutover"]  # no injected vocabulary
    params = set(inspect.signature(PmService.record_item_outcome).parameters)
    assert not {p for p in params if "approved" in p or "vocab" in p}
    source = inspect.getsource(PmService.record_item_outcome)
    builder = inspect.getsource(PmService._build_outcome)
    assert "self._build_outcome(" in source and "**_vocabulary()" in builder  # the only vocabulary binding
    assert all("frozenset(" not in s and "TEST-" not in s for s in (source, builder))


class UnsupportedOutcomeRepository(type(repo_with())):
    """A Mock whose outcome storage behaves like an adapter without it (the
    Repository base implementation, as GoogleSheetsRepository inherits)."""

    get_pm_item_outcome = Repository.get_pm_item_outcome
    create_pm_item_outcome = Repository.create_pm_item_outcome
    list_pm_item_outcomes = Repository.list_pm_item_outcomes
    get_pm_outstanding_item = Repository.get_pm_outstanding_item
    create_pm_outstanding_item = Repository.create_pm_outstanding_item
    list_pm_outstanding_items = Repository.list_pm_outstanding_items


async def test_b02b2a_22_unsupported_adapter_fails_closed() -> None:
    from app.repositories.google_sheets.repository import GoogleSheetsRepository
    for name in ("get_pm_item_outcome", "create_pm_item_outcome", "list_pm_item_outcomes",
                 "get_pm_outstanding_item", "create_pm_outstanding_item", "list_pm_outstanding_items"):
        # R4 Sheets TEST persistence (corrected plan D-3a/a1, D-4a; deliberate evolution): the Sheets adapter now
        # implements this storage on validated tabs and fails closed (parity: test_r4_pm_wf_sheets_parity). The
        # explicit base refusal stays for any adapter without the storage and is still proven here.
        assert getattr(GoogleSheetsRepository, name) is not getattr(Repository, name)
    repo = repo_with()
    job_id = await v2_job(repo)  # started on the Mock; the outcome storage then becomes unsupported
    repo.__class__ = UnsupportedOutcomeRepository
    task = await scope_task(repo, job_id)
    service = pm_service(repo)
    before = protected_state(repo)
    for call in (service.list_item_outcomes(job_id, ctx(U1)),
                 service.record_item_outcome(job_id, task, Disposition.PERFORMED, ctx(U1), performed_actions=(CHECK,))):
        with pytest.raises(RepositoryFeatureNotImplementedError) as refused:
            await call
        assert refused.value.feature in {"pm_item_outcome", "pm_outstanding"}
    assert protected_state(repo) == before and repo._pm_item_outcomes == {}
    assert not repo._pm_work_results.get(job_id)  # refused before the factual result was written
    assert (await code_of(service.list_item_outcomes(job_id, ctx(U3))))[0] == 403  # authorization still first
