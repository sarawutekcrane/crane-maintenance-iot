"""R8 PRE-UAT Whole-Web Completion — TEST master record routes (workstream A).

- GET   /master-records/{entity}                      trusted can_view
- GET   /master-records/{entity}/{record_id}/history  trusted can_view
- POST  /master-records/{entity}                      create (X-Request-Id)
- PATCH /master-records/{entity}/{record_id}          edit editable fields (X-Request-Id)

`entity` is one of: vehicles, models, equipment, branches, departments, personnel,
technicians. Before any repository read, a write needs a trusted Access-Management-
verified employee holding the per-employee TEST grant `can_test_manage_master_records`
and `can_view`. Google Sheets -> 501; REAL -> 409 MASTER_RECORD_REAL_NOT_ENABLED.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.v1.master_record_schemas import (
    MasterRecordHistoryEvent,
    MasterRecordHistoryResponse,
    MasterRecordListResponse,
    MasterRecordOutcomeResponse,
)
from app.api.v1.registry_mutation_body import effective_test_batch_id
from app.api.v1.request_id_dependency import require_client_request_id
from app.config import DataRepositoryMode, Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_TEST_MANAGE_MASTER_RECORDS, require_trusted_reader
from app.domain.master_records import MasterOutcome, MasterRecordService, api_error, entity_of, require_preuat_actor
from app.repositories.base import Repository

router = APIRouter(tags=["preuat-master-records"])

_WRITE_TH = "การเพิ่ม/แก้ไขข้อมูลหลัก (TEST master record)"
_READ_TH = "ข้อมูลหลัก (read master records)"


def get_master_record_service(repository: Repository = Depends(get_repository),
                              settings: Settings = Depends(get_settings_dependency)) -> MasterRecordService:
    return MasterRecordService(repository, settings.registry_context_effective, effective_test_batch_id(settings),
                               mock_repository=settings.data_repository == DataRepositoryMode.MOCK)


async def require_master_writer(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    require_preuat_actor(context, CAN_TEST_MANAGE_MASTER_RECORDS, _WRITE_TH)
    return context


async def require_master_reader(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    require_trusted_reader(context, _READ_TH)
    return context


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body() or b"null")
    except (ValueError, UnicodeDecodeError) as exc:
        raise api_error("VALIDATION_ERROR", "The body must be a JSON object", 422) from exc
    if not isinstance(body, dict):
        raise api_error("VALIDATION_ERROR", "The body must be a JSON object", 422)
    return body


def _outcome(o: MasterOutcome) -> MasterRecordOutcomeResponse:
    return MasterRecordOutcomeResponse(entity=o.entity, record_id=o.record_id, action=o.action, replayed=o.replayed,
                                       event_id=o.event_id, values=o.values)


_WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "ACCESS_ACTOR_NOT_VERIFIED / PREUAT_ACTION_NOT_AUTHORIZED. Zero repository calls."},
    404: {"description": "MASTER_ENTITY_UNKNOWN / MASTER_RECORD_NOT_FOUND."},
    409: {"description": "MASTER_RECORD_REAL_NOT_ENABLED / MASTER_RECORD_DUPLICATE / MASTER_RECORD_NOT_TEST_SCOPED / "
                         "MASTER_RECORD_EDIT_NOT_SUPPORTED / MASTER_RECORD_CONCURRENT_CHANGE / REQUEST_ID_REUSED."},
    422: {"description": "REQUEST_ID_REQUIRED / VALIDATION_ERROR / MODEL_NOT_FOUND."},
    501: {"description": "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE (Google Sheets)."},
}


@router.get("/master-records/{entity}", response_model=MasterRecordListResponse,
            responses={403: {"description": "Not a trusted can_view reader."}})
async def list_master_records(entity: str, context: RequestContext = Depends(require_master_reader),
                              service: MasterRecordService = Depends(get_master_record_service)
                              ) -> MasterRecordListResponse:
    spec = entity_of(entity)
    return MasterRecordListResponse(entity=spec.entity, items=await service.list_records(spec))


@router.get("/master-records/{entity}/{record_id}/history", response_model=MasterRecordHistoryResponse,
            responses={403: {"description": "Not a trusted can_view reader."}})
async def master_record_history(entity: str, record_id: str, context: RequestContext = Depends(require_master_reader),
                                service: MasterRecordService = Depends(get_master_record_service)
                                ) -> MasterRecordHistoryResponse:
    spec = entity_of(entity)
    events = [MasterRecordHistoryEvent(**e) for e in await service.history(spec, record_id)]
    return MasterRecordHistoryResponse(entity=spec.entity, record_id=record_id, events=events)


@router.post("/master-records/{entity}", response_model=MasterRecordOutcomeResponse, responses=_WRITE_RESPONSES)
async def create_master_record(entity: str, request: Request,
                               context: RequestContext = Depends(require_master_writer),
                               request_id: str = Depends(require_client_request_id),
                               service: MasterRecordService = Depends(get_master_record_service)
                               ) -> MasterRecordOutcomeResponse:
    spec = entity_of(entity)
    return _outcome(await service.create(spec, await _json_object(request), context, request_id=request_id))


@router.patch("/master-records/{entity}/{record_id}", response_model=MasterRecordOutcomeResponse,
              responses=_WRITE_RESPONSES)
async def edit_master_record(entity: str, record_id: str, request: Request,
                             context: RequestContext = Depends(require_master_writer),
                             request_id: str = Depends(require_client_request_id),
                             service: MasterRecordService = Depends(get_master_record_service)
                             ) -> MasterRecordOutcomeResponse:
    spec = entity_of(entity)
    return _outcome(await service.edit(spec, record_id, await _json_object(request), context, request_id=request_id))
