"""R4 PM Workflow — OPT-IN live Google Sheets TEST suite (matrix column L).

SKIPPED BY DEFAULT. It runs only when ALL of these are set, and only after the
Owner's S-1 approval of the live schema/classification/seed steps (corrected
plan C-4), a dated Drive copy and a single backend worker:

    SHEETS_LIVE_TEST=1
    DATA_REPOSITORY=google_sheets, GOOGLE_SHEET_ID, GOOGLE_APPLICATION_CREDENTIALS
    REGISTRY_DATA_CONTEXT=TEST, REGISTRY_TEST_BATCH_ID=<the TEST batch>
    SHEETS_LIVE_TEST_ACK=<the same TEST batch id>   (deliberate acknowledgement)
    SHEETS_LIVE_TEST_ASSET=<the Owner-designated REAL vehicle id>
    SHEETS_LIVE_TEST_PLAN=<the seeded TEST plan id>
    SHEETS_LIVE_TEST_TECHNICIANS=<PRIMARY,COLLABORATOR seeded TEST technician ids>
    SHEETS_LIVE_TEST_PRIMARY_USER=<the TEST account linked to the PRIMARY technician>

It writes ONLY new TEST-tagged rows (work order, assignment, journal, results /
Outcomes, Outstanding, snapshots) and never deletes, rewrites or reads as REAL
anything else. The read-only checks run first and stop the suite on any
precondition difference. Results are UNVERIFIED until this suite is executed
with credentials; in the code-only phase every case here is NOT RUN."""
from __future__ import annotations

import os

import pytest

from app.domain.asset import AssetType
from app.domain.meter_service import MeterService
from app.domain.pm import PmItemContractDisposition as Disposition
from app.domain.pm import PmWorkOrderStatus as S
from app.domain.pm_service import PmService
from app.domain.technician_assignment import (
    PM,
    TechnicianAssignmentService,
    cutover_from_settings,
    v2_job_marker,
)
from app.repositories.base import REFERENCE_SCOPE_REAL, REFERENCE_SCOPE_TEST
from app.repositories.google_sheets import schemas

ENABLED = os.environ.get("SHEETS_LIVE_TEST") == "1"
pytestmark = pytest.mark.skipif(not ENABLED, reason="opt-in live Google Sheets TEST suite (SHEETS_LIVE_TEST=1)")

REQUIRED_TABS = (schemas.PM_WORK_ORDER_V2_SHEET, schemas.PM_WORK_ASSIGNMENT_V2_SHEET,
                 schemas.PM_WORK_RESULT_OUTCOME_SHEET, schemas.PM_WORK_ORDER_TRANSITION_SHEET,
                 schemas.PM_OUTSTANDING_ITEM_SHEET)


def _live_settings():
    from app.config import DataRepositoryMode, get_settings
    get_settings.cache_clear()
    settings = get_settings()
    batch = (settings.registry_test_batch_id or "").strip()
    problems = []
    if settings.data_repository != DataRepositoryMode.GOOGLE_SHEETS:
        problems.append("DATA_REPOSITORY must be google_sheets")
    if settings.registry_context_effective != REFERENCE_SCOPE_TEST:
        problems.append("REGISTRY_DATA_CONTEXT must be TEST")
    if not batch or os.environ.get("SHEETS_LIVE_TEST_ACK") != batch:
        problems.append("SHEETS_LIVE_TEST_ACK must equal REGISTRY_TEST_BATCH_ID")
    for name in ("SHEETS_LIVE_TEST_ASSET", "SHEETS_LIVE_TEST_PLAN", "SHEETS_LIVE_TEST_TECHNICIANS",
                 "SHEETS_LIVE_TEST_PRIMARY_USER"):
        if not os.environ.get(name):
            problems.append(f"{name} is required")
    if problems:
        pytest.fail("live preconditions not met (nothing was written): " + "; ".join(problems))
    return settings


@pytest.fixture(scope="module")
def live():
    from app.repositories.google_sheets.repository import GoogleSheetsRepository
    settings = _live_settings()
    return settings, GoogleSheetsRepository(settings)


def _fresh(settings):
    from app.repositories.google_sheets.repository import GoogleSheetsRepository
    return GoogleSheetsRepository(settings)  # a new client: nothing cached in memory


# ---------------------------------------------------------------- read-only preconditions (run first)


async def test_live_00_headers_and_classification_preconditions_read_only(live) -> None:
    _, repo = live
    for schema in REQUIRED_TABS:
        read = await repo._client.read_header_and_records(schema)
        assert set(schema.required_headers) <= set(read.header), schema.tab_name
    for read in (await repo.read_technician_master_reference(), await repo.read_user_account_reference()):
        assert read.test_scope_supported is True
        assert {r.scope for r in read.rows} <= {REFERENCE_SCOPE_TEST, REFERENCE_SCOPE_REAL}
    plan = await repo.get_pm_plan(os.environ["SHEETS_LIVE_TEST_PLAN"])
    assert plan is not None  # visible only because it is TEST-scoped to this batch


async def test_live_17_test_rows_are_invisible_in_real_context_read_only(live) -> None:
    settings, _ = live
    from app.config import RegistryDataContext
    from app.repositories.google_sheets.repository import GoogleSheetsRepository
    real = GoogleSheetsRepository(settings.model_copy(update={"registry_data_context": RegistryDataContext.REAL}))
    assert await real.get_pm_plan(os.environ["SHEETS_LIVE_TEST_PLAN"]) is None
    tech = await real.read_technician_master_reference()
    assert all(r.scope == REFERENCE_SCOPE_TEST for r in tech.rows if r.test_batch_id == settings.registry_test_batch_id)


# ---------------------------------------------------------------- TEST writes (new TEST rows only)


async def test_live_01_to_15_lifecycle_and_durable_history(live) -> None:
    settings, repo = live
    cutover = cutover_from_settings(settings)
    plan_id = os.environ["SHEETS_LIVE_TEST_PLAN"]
    revision = (await repo.get_active_pm_task_revision(plan_id)).revision
    tasks = [t.pm_task_id for t in (await repo.get_pm_task_revision(plan_id, revision.revision_id)).tasks]
    marker = await v2_job_marker(repo, PM, cutover)
    assert (marker["is_test_data"], marker["test_batch_id"]) == ("TRUE", settings.registry_test_batch_id)
    work_order = await repo.create_pm_work_order(AssetType.VEHICLE, os.environ["SHEETS_LIVE_TEST_ASSET"], plan_id,
                                                 revision.revision_id, None, "SYN-LIVE-R4", None,
                                                 scope_task_ids=tasks, assignment_marker=marker)
    job = work_order.pm_work_order_id
    primary, collaborator = os.environ["SHEETS_LIVE_TEST_TECHNICIANS"].split(",")
    test_technicians = {r.values["technician_id"] for r in (await repo.read_technician_master_reference()).rows
                        if r.scope == REFERENCE_SCOPE_TEST and r.test_batch_id == settings.registry_test_batch_id}
    assert {primary, collaborator} <= test_technicians  # Owner-designated, never inferred
    import uuid

    from app.context import RequestContext
    from app.domain import authz
    assignment = TechnicianAssignmentService(repo, cutover)
    await assignment.assign(PM, job, {"primary_technician_id": primary, "collaborator_technician_ids": [collaborator],
                                      "expected_current": None}, request_id=str(uuid.uuid4()),
                            user_id="SYN-LIVE-R4")
    state = (await assignment.read(PM, job)).state.current
    primary_user = os.environ["SHEETS_LIVE_TEST_PRIMARY_USER"]

    def context(user, *caps):
        return RequestContext(request_id=str(uuid.uuid4()), user_id=user, is_dev_auth=True,
                              capabilities=frozenset(caps))

    svc = PmService(repo, MeterService(repo), assignment_cutover=cutover)
    reviewer = context("SYN-LIVE-R4-REVIEWER", authz.CAN_MANAGE_PM)
    await svc.start_work_order(job, context(primary_user), request_id=str(uuid.uuid4()))
    import app.domain.pm_service as pm_module
    action = min(pm_module.PM_APPROVED_PERFORMED_ACTIONS)
    reason = min(pm_module.PM_APPROVED_NOT_PERFORMED_REASONS)
    for task in tasks[:-1]:
        await svc.record_item_outcome(job, task, Disposition.PERFORMED, context(primary_user),
                                      performed_actions=(action,))
    await svc.record_item_outcome(job, tasks[-1], Disposition.NOT_PERFORMED, context(primary_user),
                                  reason_code=reason)
    await svc.submit_for_review(job, context(primary_user), request_id=str(uuid.uuid4()), expected_set_id=state.set_id)
    close_id = str(uuid.uuid4())
    done = await svc.close_after_review(job, reviewer, request_id=close_id)
    assert done.work_order.status == S.CLOSED
    replay = await svc.close_after_review(job, reviewer, request_id=close_id)  # SH-10
    assert replay.work_order.closed_snapshot_id == done.work_order.closed_snapshot_id

    fresh = _fresh(settings)  # SH-15
    assert [t.action.value for t in await fresh.list_pm_work_order_transitions(job)] == ["START", "SUBMIT", "CLOSE"]
    assert len(await fresh.list_pm_item_outcomes(job)) == len(tasks)
    [item] = await fresh.list_pm_outstanding_items(job)
    assert item.pm_task_id == tasks[-1]
