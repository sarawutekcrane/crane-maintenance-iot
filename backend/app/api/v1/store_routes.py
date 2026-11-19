"""R8 PRE-UAT Whole-Web Completion — repair material (Store) workflow routes (workstream D).

Owner Decision 1: future stock integration only (no stock ledger). Mock/TEST only;
Google Sheets -> 501; REAL -> 409 STORE_REAL_NOT_ENABLED.

Writes (client X-Request-Id; guard before any repository read):
- POST /repairs/{repair_id}/store-requests                                verified actor + can_view
       (+ current V2 member or can_manage_repair, checked in the service)
- POST /repairs/{repair_id}/store-lines/{line_id}/approvals                can_test_store_approve
- POST /repairs/{repair_id}/store-lines/{line_id}/denials                  can_test_store_approve
- POST /repairs/{repair_id}/store-lines/{line_id}/issues                   can_test_store_issue
- POST /repairs/{repair_id}/store-lines/{line_id}/use-confirmations        verified actor + can_view (V2 member)
- POST /repairs/{repair_id}/store-lines/{line_id}/return-declarations      verified actor + can_view (V2 member)
- POST /repairs/{repair_id}/store-lines/{line_id}/return-acceptances       can_test_store_receive_return
Reads (trusted can_view):
- GET  /repairs/{repair_id}/store-reconciliation
- GET  /store-material-events?after_event_id&limit   (future stock-integration feed, read-only)
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.request_id_dependency import require_client_request_id
from app.api.v1.store_schemas import (
    StoreEventFeedResponse,
    StoreEventResponse,
    StoreLineBalanceResponse,
    StoreReconciliationResponse,
    StoreWriteResponse,
)
from app.config import DataRepositoryMode, Settings
from app.context import RequestContext
from app.dependencies import (
    get_current_context,
    get_material_request_service,
    get_repository,
    get_settings_dependency,
)
from app.domain.authz import (
    CAN_TEST_STORE_APPROVE,
    CAN_TEST_STORE_ISSUE,
    CAN_TEST_STORE_RECEIVE_RETURN,
    CAN_VIEW,
    require_trusted_reader,
)
from app.domain.master_records import api_error, forbidden, require_mock_test, require_preuat_actor
from app.domain.material_request_service import MaterialRequestService
from app.domain.store_workflow import (
    APPROVED,
    DENIED,
    ISSUED,
    JOURNAL_STORE_EVENTS,
    RETURN_ACCEPTED,
    RETURN_DECLARED,
    USE_CONFIRMED,
    StoreOutcome,
    StoreWorkflowService,
)
from app.domain.technician_assignment import cutover_from_settings
from app.repositories.base import Repository

router = APIRouter(tags=["preuat-store-workflow"])

_TH = "การเบิก/จ่าย/คืนอะไหล่ของใบงาน (store workflow)"


def get_store_service(repository: Repository = Depends(get_repository),
                      settings: Settings = Depends(get_settings_dependency)) -> StoreWorkflowService:
    return StoreWorkflowService(repository, cutover_from_settings(settings),
                                mock_repository=settings.data_repository == DataRepositoryMode.MOCK)


def _verified(context: RequestContext) -> None:
    if not (context.user_id or "").strip():
        raise forbidden("ACCESS_ACTOR_NOT_VERIFIED", f"{_TH} requires a trusted, authenticated actor")
    if CAN_VIEW not in context.capabilities:
        raise forbidden("PREUAT_ACTION_NOT_AUTHORIZED", f"{_TH} requires '{CAN_VIEW}'")
    if getattr(context, "access", None) is None or not getattr(context, "personnel_id", None):
        raise forbidden("ACCESS_ACTOR_NOT_VERIFIED", f"{_TH} requires an active TEST employee linked to one account")


async def require_store_member_actor(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    _verified(context)
    return context


async def require_store_approver(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    require_preuat_actor(context, CAN_TEST_STORE_APPROVE, _TH)
    return context


async def require_store_issuer(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    require_preuat_actor(context, CAN_TEST_STORE_ISSUE, _TH)
    return context


async def require_store_receiver(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    require_preuat_actor(context, CAN_TEST_STORE_RECEIVE_RETURN, _TH)
    return context


async def require_store_reader(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    require_trusted_reader(context, _TH)
    return context


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body() or b"null")
    except (ValueError, UnicodeDecodeError) as exc:
        raise api_error("VALIDATION_ERROR", "The body must be a JSON object", 422) from exc
    if not isinstance(body, dict):
        raise api_error("VALIDATION_ERROR", "The body must be a JSON object", 422)
    return body


def _event(row: dict[str, str]) -> StoreEventResponse:
    return StoreEventResponse(**{k: row.get(k, "") for k in StoreEventResponse.model_fields})


def _written(outcome: StoreOutcome) -> StoreWriteResponse:
    return StoreWriteResponse(replayed=outcome.replayed, material_request_id=outcome.material_request_id,
                              events=[_event(e) for e in outcome.events])


_WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "ACCESS_ACTOR_NOT_VERIFIED / PREUAT_ACTION_NOT_AUTHORIZED / STORE_REQUEST_NOT_AUTHORIZED / "
                         "STORE_TECHNICIAN_NOT_ASSIGNED."},
    404: {"description": "REPAIR_NOT_FOUND / STORE_LINE_NOT_FOUND."},
    409: {"description": "STORE_REAL_NOT_ENABLED / STORE_REQUEST_AFTER_CLOSE_NOT_ALLOWED / STORE_LINE_ALREADY_DECIDED / "
                         "STORE_LINE_NOT_APPROVED / STORE_QUANTITY_EXCEEDED / STORE_CONCURRENT_CHANGE / "
                         "REQUEST_ID_REUSED."},
    422: {"description": "REQUEST_ID_REQUIRED / VALIDATION_ERROR / REASON_REQUIRED / PART_NOT_FOUND / "
                         "STORE_UNIT_MISMATCH / STORE_PART_NOT_ISSUED."},
    501: {"description": "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE (Google Sheets)."},
}


@router.get("/repairs/{repair_id}/store-reconciliation", response_model=StoreReconciliationResponse,
            responses={403: {"description": "Not a trusted can_view reader."}})
async def store_reconciliation(repair_id: str, context: RequestContext = Depends(require_store_reader),
                               service: StoreWorkflowService = Depends(get_store_service)
                               ) -> StoreReconciliationResponse:
    rec = await service.reconciliation(repair_id)
    return StoreReconciliationResponse(
        repair_id=repair_id, state=rec.state, blockers=rec.blockers(),
        lines=[StoreLineBalanceResponse(**line.as_dict()) for line in rec.lines], events=[_event(e) for e in rec.events])


@router.get("/store-material-events", response_model=StoreEventFeedResponse,
            responses={403: {"description": "Not a trusted can_view reader."}})
async def store_material_events(after_event_id: str | None = Query(default=None, max_length=40),
                                limit: int = Query(default=100, ge=1, le=500),
                                context: RequestContext = Depends(require_store_reader),
                                repository: Repository = Depends(get_repository),
                                settings: Settings = Depends(get_settings_dependency)) -> StoreEventFeedResponse:
    require_mock_test(settings.data_repository == DataRepositoryMode.MOCK, settings.registry_context_effective,
                      "store_workflow", "STORE_REAL_NOT_ENABLED")
    rows = await repository.read_preuat_journal(JOURNAL_STORE_EVENTS)
    start = 0
    if after_event_id is not None:
        ids = [r.get("event_id") for r in rows]
        if after_event_id not in ids:
            raise api_error("STORE_EVENT_NOT_FOUND", "after_event_id is not a known event", 404)
        start = ids.index(after_event_id) + 1
    page = rows[start:start + limit]
    more = start + limit < len(rows)
    return StoreEventFeedResponse(events=[_event(r) for r in page],
                                  next_after_event_id=page[-1]["event_id"] if page and more else None)


@router.post("/repairs/{repair_id}/store-requests", response_model=StoreWriteResponse, responses=_WRITE_RESPONSES)
async def create_store_request(repair_id: str, request: Request,
                               context: RequestContext = Depends(require_store_member_actor),
                               request_id: str = Depends(require_client_request_id),
                               service: StoreWorkflowService = Depends(get_store_service),
                               material_requests: MaterialRequestService = Depends(get_material_request_service)
                               ) -> StoreWriteResponse:
    return _written(await service.request(repair_id, await _json_object(request), context, request_id=request_id,
                                          material_requests=material_requests))


async def _act(kind: str, repair_id: str, line_id: str, request: Request, context: RequestContext, request_id: str,
               service: StoreWorkflowService) -> StoreWriteResponse:
    return _written(await service.act(repair_id, line_id, kind, await _json_object(request), context,
                                      request_id=request_id))


@router.post("/repairs/{repair_id}/store-lines/{line_id}/approvals", response_model=StoreWriteResponse,
             responses=_WRITE_RESPONSES)
async def approve_store_line(repair_id: str, line_id: str, request: Request,
                             context: RequestContext = Depends(require_store_approver),
                             request_id: str = Depends(require_client_request_id),
                             service: StoreWorkflowService = Depends(get_store_service)) -> StoreWriteResponse:
    return await _act(APPROVED, repair_id, line_id, request, context, request_id, service)


@router.post("/repairs/{repair_id}/store-lines/{line_id}/denials", response_model=StoreWriteResponse,
             responses=_WRITE_RESPONSES)
async def deny_store_line(repair_id: str, line_id: str, request: Request,
                          context: RequestContext = Depends(require_store_approver),
                          request_id: str = Depends(require_client_request_id),
                          service: StoreWorkflowService = Depends(get_store_service)) -> StoreWriteResponse:
    return await _act(DENIED, repair_id, line_id, request, context, request_id, service)


@router.post("/repairs/{repair_id}/store-lines/{line_id}/issues", response_model=StoreWriteResponse,
             responses=_WRITE_RESPONSES)
async def issue_store_line(repair_id: str, line_id: str, request: Request,
                           context: RequestContext = Depends(require_store_issuer),
                           request_id: str = Depends(require_client_request_id),
                           service: StoreWorkflowService = Depends(get_store_service)) -> StoreWriteResponse:
    return await _act(ISSUED, repair_id, line_id, request, context, request_id, service)


@router.post("/repairs/{repair_id}/store-lines/{line_id}/use-confirmations", response_model=StoreWriteResponse,
             responses=_WRITE_RESPONSES)
async def confirm_store_use(repair_id: str, line_id: str, request: Request,
                            context: RequestContext = Depends(require_store_member_actor),
                            request_id: str = Depends(require_client_request_id),
                            service: StoreWorkflowService = Depends(get_store_service)) -> StoreWriteResponse:
    return await _act(USE_CONFIRMED, repair_id, line_id, request, context, request_id, service)


@router.post("/repairs/{repair_id}/store-lines/{line_id}/return-declarations", response_model=StoreWriteResponse,
             responses=_WRITE_RESPONSES)
async def declare_store_return(repair_id: str, line_id: str, request: Request,
                               context: RequestContext = Depends(require_store_member_actor),
                               request_id: str = Depends(require_client_request_id),
                               service: StoreWorkflowService = Depends(get_store_service)) -> StoreWriteResponse:
    return await _act(RETURN_DECLARED, repair_id, line_id, request, context, request_id, service)


@router.post("/repairs/{repair_id}/store-lines/{line_id}/return-acceptances", response_model=StoreWriteResponse,
             responses=_WRITE_RESPONSES)
async def accept_store_return(repair_id: str, line_id: str, request: Request,
                              context: RequestContext = Depends(require_store_receiver),
                              request_id: str = Depends(require_client_request_id),
                              service: StoreWorkflowService = Depends(get_store_service)) -> StoreWriteResponse:
    return await _act(RETURN_ACCEPTED, repair_id, line_id, request, context, request_id, service)
