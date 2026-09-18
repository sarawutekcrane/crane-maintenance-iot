"""Model Document service (Web/API Phase 6 Batch 3A — create/list/get
only; see `app.domain.model_document` module docstring for scope).

Unlike `VehicleCertificate` (Batch 2A/2B), the verified live
`model_document` schema has no `created_by_user_id`/`created_at`
columns — so, unlike `VehicleCertificateService.create_certificate`,
this service never generates or persists provenance timestamps; nothing
here is guessed/added beyond the 12 verified columns."""
from __future__ import annotations

from datetime import date

from fastapi import status

from app.domain.model_document import ModelDocument
from app.errors import ApiError
from app.repositories.base import Repository


class ModelDocumentService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _require_model_exists(self, model_id: str) -> None:
        model = await self._repository.get_vehicle_model(model_id)
        if model is None:
            raise ApiError(
                code="MODEL_NOT_FOUND",
                message=f"Vehicle model '{model_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    async def create_document(
        self,
        model_id: str,
        document_type: str | None,
        document_name_th: str | None,
        version: str | None,
        effective_from: date | None,
        effective_to: date | None,
        storage_ref: str | None,
        file_status: str | None,
        active_status: str | None,
        note_th: str | None,
    ) -> ModelDocument:
        """Batch 3A: a plain append — never touches any other row. No
        `replaced_by_document_id` is ever set here (deferred to Batch
        3B)."""
        await self._require_model_exists(model_id)
        return await self._repository.create_model_document(
            model_id=model_id,
            document_type=document_type,
            document_name_th=document_name_th,
            version=version,
            effective_from=effective_from,
            effective_to=effective_to,
            storage_ref=storage_ref,
            file_status=file_status,
            active_status=active_status,
            note_th=note_th,
        )

    async def get_document(self, model_document_id: str) -> ModelDocument:
        document = await self._repository.get_model_document(model_document_id)
        if document is None:
            raise ApiError(
                code="MODEL_DOCUMENT_NOT_FOUND",
                message=f"Model document '{model_document_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return document

    async def list_for_model(self, model_id: str) -> list[ModelDocument]:
        await self._require_model_exists(model_id)
        return await self._repository.list_model_documents_for_model(model_id)


__all__ = ["ModelDocumentService"]
