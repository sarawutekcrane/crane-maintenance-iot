"""Model Document routes (Web/API Phase 6 Batch 3A create/list/get/
history foundation + Batch 3B revision lifecycle).

R7 Whole-Phase (Owner gate 2026-11-17, policy R1 P-1/P-2/P-3): reads need a
trusted actor with `can_view` before any repository read; create / revise carry
the shared `document_master_write_gate` (legacy: a trusted actor; Access
Management: the TEST-only grant, Mock + TEST and a TEST-exclusive model). The
revision records no actor (no column — documented exception E-5). Final RBAC
remains M02."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.model_document_schemas import (
    CreateModelDocumentRequest,
    ModelDocumentResponse,
    ReviseModelDocumentRequest,
)
from app.context import RequestContext
from app.dependencies import (
    DOCUMENT_PARENT_MODEL,
    DOCUMENT_PARENT_MODEL_DOCUMENT,
    document_master_write_gate,
    get_current_context,
    get_model_document_service,
)
from app.domain.authz import require_trusted_reader
from app.domain.model_document import ModelDocument
from app.domain.model_document_service import ModelDocumentService

router = APIRouter(tags=["model-documents"])

_READ_TH = "การดูเอกสารรุ่นรถ (read model documents)"


def _document_response(document: ModelDocument) -> ModelDocumentResponse:
    return ModelDocumentResponse.model_validate(document.model_dump())


@router.post(
    "/models/{model_id}/documents",
    response_model=ModelDocumentResponse,
    dependencies=[Depends(document_master_write_gate(DOCUMENT_PARENT_MODEL))],
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
    context: RequestContext = Depends(get_current_context),
) -> list[ModelDocumentResponse]:
    require_trusted_reader(context, _READ_TH)
    documents = await service.list_for_model(model_id)
    return [_document_response(d) for d in documents]


@router.get("/model-documents/{model_document_id}", response_model=ModelDocumentResponse)
async def get_model_document(
    model_document_id: str,
    service: ModelDocumentService = Depends(get_model_document_service),
    context: RequestContext = Depends(get_current_context),
) -> ModelDocumentResponse:
    require_trusted_reader(context, _READ_TH)
    document = await service.get_document(model_document_id)
    return _document_response(document)


@router.post(
    "/model-documents/{model_document_id}/revise",
    response_model=ModelDocumentResponse,
    dependencies=[Depends(document_master_write_gate(DOCUMENT_PARENT_MODEL_DOCUMENT))],
)
async def revise_model_document(
    model_document_id: str,
    body: ReviseModelDocumentRequest,
    service: ModelDocumentService = Depends(get_model_document_service),
) -> ModelDocumentResponse:
    # LOCKED RULE 3/7: document_name_th/active_status inherit-if-omitted
    # semantics require distinguishing "omitted" from "explicit null" —
    # both otherwise read as a plain None parameter value — so
    # `body.model_fields_set` is threaded through to the service exactly
    # as Batch 2B's certificate renewal does.
    document = await service.revise_document(
        model_document_id=model_document_id,
        version=body.version,
        effective_from=body.effective_from,
        document_name_th=body.document_name_th,
        storage_ref=body.storage_ref,
        file_status=body.file_status,
        active_status=body.active_status,
        note_th=body.note_th,
        fields_set=body.model_fields_set,
    )
    return _document_response(document)
