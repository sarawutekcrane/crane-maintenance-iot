"""R8 PRE-UAT Whole-Web Completion — TEST repair classification routes (workstream E).

Owner Decision 2: TEST-CANDIDATE-R1 subset of the Owner workbook; never REAL.
- GET  /repair-classification/catalogue                      trusted can_view
- GET  /repairs/{repair_id}/classification                   trusted can_view
- POST /repairs/{repair_id}/classification-drafts            can_test_classify_repair (X-Request-Id)
- POST /repairs/{repair_id}/classification-finalizations     can_test_classify_repair (X-Request-Id)
Google Sheets -> 501; REAL -> 409 CLASSIFICATION_REAL_NOT_ENABLED.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.v1.registry_mutation_body import effective_test_batch_id
from app.api.v1.repair_classification_schemas import CatalogueResponse, ClassificationResponse
from app.api.v1.request_id_dependency import require_client_request_id
from app.api.v1.store_routes import get_store_service
from app.config import DataRepositoryMode, Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_TEST_CLASSIFY_REPAIR, require_trusted_reader
from app.domain.master_records import api_error, require_mock_test, require_preuat_actor
from app.domain.repair_classification import (
    POSITION_CHOICES,
    ClassificationView,
    RepairClassificationService,
    catalogue_or_error,
    catalogue_tree,
)
from app.domain.store_workflow import StoreWorkflowService
from app.repositories.base import Repository

router = APIRouter(tags=["preuat-repair-classification"])

_WRITE_TH = "การจัดประเภทงานซ่อม (TEST repair classification)"
_READ_TH = "การจัดประเภทงานซ่อม (read)"


def get_classification_service(repository: Repository = Depends(get_repository),
                               settings: Settings = Depends(get_settings_dependency),
                               store: StoreWorkflowService = Depends(get_store_service)
                               ) -> RepairClassificationService:
    return RepairClassificationService(repository, store, settings.registry_context_effective,
                                       effective_test_batch_id(settings),
                                       mock_repository=settings.data_repository == DataRepositoryMode.MOCK)


async def require_classifier(context: RequestContext = Depends(get_current_context)) -> RequestContext:
    require_preuat_actor(context, CAN_TEST_CLASSIFY_REPAIR, _WRITE_TH)
    return context


async def require_reader(context: RequestContext = Depends(get_current_context)) -> RequestContext:
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


def _response(view: ClassificationView, replayed: bool = False) -> ClassificationResponse:
    return ClassificationResponse(repair_id=view.repair_id, state=view.state, blockers=view.blockers,
                                  draft_revision=view.draft_revision, draft_rows=view.draft_rows, final=view.final,
                                  replayed=replayed)


_WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "ACCESS_ACTOR_NOT_VERIFIED / PREUAT_ACTION_NOT_AUTHORIZED. Zero repository calls."},
    404: {"description": "REPAIR_NOT_FOUND."},
    409: {"description": "CLASSIFICATION_REAL_NOT_ENABLED / CLASSIFICATION_NOT_ELIGIBLE / "
                         "CLASSIFICATION_BLOCKED_STORE_UNRECONCILED / REPAIR_ALREADY_CLASSIFIED / "
                         "CLASSIFICATION_DRAFT_STALE / CLASSIFICATION_CONCURRENT_CHANGE / REQUEST_ID_REUSED."},
    422: {"description": "REQUEST_ID_REQUIRED / VALIDATION_ERROR / REPAIR_CODE_UNKNOWN / REPAIR_CODE_HIERARCHY_INVALID "
                         "/ REPAIR_CODE_ENTRY_NOT_IN_TEST_SUBSET / REPAIR_SYMPTOM_NOT_ALLOWED / REPAIR_ACTION_UNKNOWN."},
    500: {"description": "REPAIR_CATALOGUE_INTEGRITY_FAILED."},
    501: {"description": "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE (Google Sheets)."},
}


@router.get("/repair-classification/catalogue", response_model=CatalogueResponse,
            responses={403: {"description": "Not a trusted can_view reader."}})
async def classification_catalogue(context: RequestContext = Depends(require_reader),
                                   settings: Settings = Depends(get_settings_dependency)) -> CatalogueResponse:
    require_mock_test(settings.data_repository == DataRepositoryMode.MOCK, settings.registry_context_effective,
                      "repair_classification", "CLASSIFICATION_REAL_NOT_ENABLED")
    catalogue = catalogue_or_error()
    excluded = [{"code": r.code, "reasons": list(r.exclusion_reasons), "source_row": r.source_row}
                for r in catalogue.relationships.values() if not r.candidate]
    return CatalogueResponse(summary=catalogue.summary(), tree=catalogue_tree(catalogue), symptoms=catalogue.symptoms,
                             actions=catalogue.actions, excluded=excluded,
                             position_fields={k: list(v) if v else None for k, v in POSITION_CHOICES.items()})


@router.get("/repairs/{repair_id}/classification", response_model=ClassificationResponse,
            responses={403: {"description": "Not a trusted can_view reader."}})
async def repair_classification(repair_id: str, context: RequestContext = Depends(require_reader),
                                service: RepairClassificationService = Depends(get_classification_service)
                                ) -> ClassificationResponse:
    return _response(await service.view(repair_id))


@router.post("/repairs/{repair_id}/classification-drafts", response_model=ClassificationResponse,
             responses=_WRITE_RESPONSES)
async def stage_classification(repair_id: str, request: Request, context: RequestContext = Depends(require_classifier),
                               request_id: str = Depends(require_client_request_id),
                               service: RepairClassificationService = Depends(get_classification_service)
                               ) -> ClassificationResponse:
    view, replayed = await service.stage(repair_id, await _json_object(request), context, request_id=request_id)
    return _response(view, replayed)


@router.post("/repairs/{repair_id}/classification-finalizations", response_model=ClassificationResponse,
             responses=_WRITE_RESPONSES)
async def finalize_classification(repair_id: str, request: Request,
                                  context: RequestContext = Depends(require_classifier),
                                  request_id: str = Depends(require_client_request_id),
                                  service: RepairClassificationService = Depends(get_classification_service)
                                  ) -> ClassificationResponse:
    view, replayed = await service.finalize(repair_id, await _json_object(request), context, request_id=request_id)
    return _response(view, replayed)
