"""Model Document routes (Web/API Phase 6 Batch 3A — create/list/get/
history foundation only; revision/replacement lifecycle is deferred to
Batch 3B).

Same open-to-any-authenticated-actor precedent as `app.api.v1.drivers`/
`app.api.v1.vehicle_certificates` (see those modules' docstrings): model
document master data is, like driver/operator and certificate master
data before it, outside REV05's explicit Maintenance-controlled Repair/
PM workflow-authority scope. Final RBAC remains Phase 10 (M02)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.model_document_schemas import (
    CreateModelDocumentRequest,
    ModelDocumentResponse,
)
from app.dependencies import get_model_document_service
from app.domain.model_document import ModelDocument
from app.domain.model_document_service import ModelDocumentService

router = APIRouter(tags=["model-documents"])


def _document_response(document: ModelDocument) -> ModelDocumentResponse:
    return ModelDocumentResponse.model_validate(document.model_dump())


@router.post(
    "/models/{model_id}/documents",
    response_model=ModelDocumentResponse,
)
async def create_model_document(
    model_id: str,
    body: CreateModelDocumentRequest,
    service: ModelDocumentService = Depends(get_model_document_service),
) -> ModelDocumentResponse:
    document = await service.create_document(
        model_id=model_id,
        document_type=body.document_type,
        document_name_th=body.document_name_th,
        version=body.version,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        storage_ref=body.storage_ref,
        file_status=body.file_status,
        active_status=body.active_status,
        note_th=body.note_th,
    )
    return _document_response(document)


@router.get(
    "/models/{model_id}/documents",
    response_model=list[ModelDocumentResponse],
)
async def list_model_documents(
    model_id: str,
    service: ModelDocumentService = Depends(get_model_document_service),
) -> list[ModelDocumentResponse]:
    documents = await service.list_for_model(model_id)
    return [_document_response(d) for d in documents]


@router.get("/model-documents/{model_document_id}", response_model=ModelDocumentResponse)
async def get_model_document(
    model_document_id: str,
    service: ModelDocumentService = Depends(get_model_document_service),
) -> ModelDocumentResponse:
    document = await service.get_document(model_document_id)
    return _document_response(document)
