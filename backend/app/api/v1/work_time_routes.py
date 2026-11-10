"""R5 routes: Repair substates and technician work time (Revision 4 §6.1).

Reads reuse the existing Repair / PM detail read authorization (the same 403 /
404 rules as `GET /repairs/{id}` and `GET /pm/work-orders/{id}`). Every POST
needs a client `X-Request-Id` (UUID) and is idempotent on it."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.v1.request_id_dependency import require_client_request_id
from app.api.v1.work_time_schemas import (
    ConfirmWorkTimeRequest,
    JobWorkTimeResponse,
    JobWorkTimeWriteResponse,
    RecordSubstateRequest,
    RecordWorkTimeRequest,
    RepairSubstatesResponse,
    RepairSubstateWriteResponse,
    ReviseSubstateRequest,
    ReviseWorkTimeRequest,
    TechnicianWorkTimeResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_pm_service, get_repair_service, get_work_time_service
from app.domain.pm_service import PmService
from app.domain.repair_service import RepairService
from app.domain.work_time import WORK_KIND_PM, WORK_KIND_REPAIR, WorkBreak
from app.domain.work_time_service import WorkTimeService

router = APIRouter(tags=["work-time"])

_PREFIX = {WORK_KIND_REPAIR: "/repairs/{job_id}", WORK_KIND_PM: "/pm/work-orders/{job_id}"}


def _breaks(items) -> list[WorkBreak] | None:
    return None if items is None else [WorkBreak(started_at=b.started_at, ended_at=b.ended_at) for b in items]


async def _reader_job(work_kind: str, job_id: str, context: RequestContext, repairs: RepairService, pm: PmService):
    if work_kind == WORK_KIND_REPAIR:
        return (await repairs.get_repair_for_reader(job_id, context)).repair
    return (await pm.get_work_order_for_reader(job_id, context)).work_order


async def _job_after_write(work_kind: str, job_id: str, service: WorkTimeService):
    return await service.locate_job(work_kind, job_id)


# ---------------------------------------------------------------- Repair substates


@router.get("/repairs/{repair_id}/substates", response_model=RepairSubstatesResponse)
async def get_repair_substates(
    repair_id: str,
    context: RequestContext = Depends(get_current_context),
    repairs: RepairService = Depends(get_repair_service),
    service: WorkTimeService = Depends(get_work_time_service),
) -> RepairSubstatesResponse:
    repair = (await repairs.get_repair_for_reader(repair_id, context)).repair
    return RepairSubstatesResponse.model_validate(await service.substate_view(repair))


@router.post("/repairs/{repair_id}/substates", response_model=RepairSubstateWriteResponse)
async def record_repair_substate(
    repair_id: str,
    body: RecordSubstateRequest,
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
    service: WorkTimeService = Depends(get_work_time_service),
) -> RepairSubstateWriteResponse:
    _, replayed = await service.record_substate(
        repair_id, context, body=body.model_dump(mode="json"), substate=body.substate, started_at=body.started_at,
        ended_at=body.ended_at, material_request_id=body.material_request_id, close_ongoing=body.close_ongoing,
        request_id=request_id)
    view = await service.substate_view(await _job_after_write(WORK_KIND_REPAIR, repair_id, service))
    return RepairSubstateWriteResponse.model_validate({**view, "replayed": replayed})


@router.post("/repairs/{repair_id}/substates/{period_id}/revisions", response_model=RepairSubstateWriteResponse)
async def revise_repair_substate(
    repair_id: str,
    period_id: str,
    body: ReviseSubstateRequest,
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
    service: WorkTimeService = Depends(get_work_time_service),
) -> RepairSubstateWriteResponse:
    _, replayed = await service.revise_substate(
        repair_id, period_id, context, body=body.model_dump(mode="json"), action=body.action,
        expected_revision=body.expected_revision, reason=body.reason, substate=body.substate,
        started_at=body.started_at, ended_at=body.ended_at, request_id=request_id)
    view = await service.substate_view(await _job_after_write(WORK_KIND_REPAIR, repair_id, service))
    return RepairSubstateWriteResponse.model_validate({**view, "replayed": replayed})


# ---------------------------------------------------------------- Work time (Repair and PM)


def _register(work_kind: str) -> None:
    prefix = _PREFIX[work_kind]
    label = "repair" if work_kind == WORK_KIND_REPAIR else "pm"

    @router.get(f"{prefix}/work-time", response_model=JobWorkTimeResponse, name=f"get_{label}_work_time")
    async def get_work_time(
        job_id: str,
        context: RequestContext = Depends(get_current_context),
        repairs: RepairService = Depends(get_repair_service),
        pm: PmService = Depends(get_pm_service),
        service: WorkTimeService = Depends(get_work_time_service),
    ) -> JobWorkTimeResponse:
        job = await _reader_job(work_kind, job_id, context, repairs, pm)
        return JobWorkTimeResponse.model_validate(await service.job_view(work_kind, job))

    @router.post(f"{prefix}/work-time", response_model=JobWorkTimeWriteResponse, name=f"record_{label}_work_time")
    async def record_work_time(
        job_id: str,
        body: RecordWorkTimeRequest,
        context: RequestContext = Depends(get_current_context),
        request_id: str = Depends(require_client_request_id),
        service: WorkTimeService = Depends(get_work_time_service),
    ) -> JobWorkTimeWriteResponse:
        _, replayed = await service.record_entry(
            work_kind, job_id, context, body=body.model_dump(mode="json"), technician_id=body.technician_id,
            started_at=body.started_at, ended_at=body.ended_at, breaks=_breaks(body.breaks),
            time_class=body.time_class, description=body.description, request_id=request_id)
        view = await service.job_view(work_kind, await _job_after_write(work_kind, job_id, service))
        return JobWorkTimeWriteResponse.model_validate({**view, "replayed": replayed})

    @router.post(f"{prefix}/work-time/{{entry_id}}/revisions", response_model=JobWorkTimeWriteResponse,
                 name=f"revise_{label}_work_time")
    async def revise_work_time(
        job_id: str,
        entry_id: str,
        body: ReviseWorkTimeRequest,
        context: RequestContext = Depends(get_current_context),
        request_id: str = Depends(require_client_request_id),
        service: WorkTimeService = Depends(get_work_time_service),
    ) -> JobWorkTimeWriteResponse:
        _, replayed = await service.revise_entry(
            work_kind, job_id, entry_id, context, body=body.model_dump(mode="json"), action=body.action,
            expected_revision=body.expected_revision, reason=body.reason, started_at=body.started_at,
            ended_at=body.ended_at, breaks=_breaks(body.breaks), time_class=body.time_class,
            description=body.description, request_id=request_id)
        view = await service.job_view(work_kind, await _job_after_write(work_kind, job_id, service))
        return JobWorkTimeWriteResponse.model_validate({**view, "replayed": replayed})

    @router.post(f"{prefix}/work-time/confirmations", response_model=JobWorkTimeWriteResponse,
                 name=f"confirm_{label}_work_time")
    async def confirm_work_time(
        job_id: str,
        body: ConfirmWorkTimeRequest,
        context: RequestContext = Depends(get_current_context),
        request_id: str = Depends(require_client_request_id),
        service: WorkTimeService = Depends(get_work_time_service),
    ) -> JobWorkTimeWriteResponse:
        _, replayed = await service.confirm(
            work_kind, job_id, context, body=body.model_dump(mode="json"),
            entries=[(e.entry_id, e.revision) for e in body.entries], note=body.note, request_id=request_id)
        view = await service.job_view(work_kind, await _job_after_write(work_kind, job_id, service))
        return JobWorkTimeWriteResponse.model_validate({**view, "replayed": replayed})


_register(WORK_KIND_REPAIR)
_register(WORK_KIND_PM)


@router.get("/work-time/assignees/{assignee_id}", response_model=TechnicianWorkTimeResponse)
async def get_assignee_work_time(
    assignee_id: str,
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    context: RequestContext = Depends(get_current_context),
    service: WorkTimeService = Depends(get_work_time_service),
) -> TechnicianWorkTimeResponse:
    """One V2 assignee (a technician id) across Work Orders: the manager capability or the
    technician themself. (Path chosen so the R2f-a technician route inventory stays unchanged.)"""
    view = await service.technician_view(assignee_id, context, from_, to)
    return TechnicianWorkTimeResponse.model_validate({**view, "from_": view["from"]})
