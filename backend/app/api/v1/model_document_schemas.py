"""Model Document request/response schemas (Web/API Phase 6 Batch 3A
create/list/get + Batch 3B revision). See `app.domain.model_document` for
the verified live-sheet field shapes and the NO-GUESSING RULE governing
`document_type`/`document_name_th`/`file_status`/`active_status` (plain
optional strings, never an Enum/fixed vocabulary) and `version` (plain
opaque text, never coerced/validated/ordered).

The client can never supply `model_document_id`, `model_id` (it is a path
parameter, not a body field), or `replaced_by_document_id` — all three
are backend-controlled (see
`app.domain.model_document_service.ModelDocumentService` and the routes
in `app.api.v1.model_documents`). Revision additionally never accepts
`document_type` or `effective_to`: both are backend-derived by the
revision operation itself (inherited from the source document, and
always `None`, respectively — Locked Rules 2/5)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class CreateModelDocumentRequest(BaseModel):
    # Same API-contract correction Batch 2A's CreateVehicleCertificateRequest
    # received: `extra="forbid"` actually enforces the "client can never
    # supply a backend-owned field" rule at the request boundary, instead
    # of relying on pydantic's default silently-ignore-extras behavior.
    model_config = ConfigDict(extra="forbid")

    document_type: str | None = Field(default=None, max_length=100)
    document_name_th: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=100)
    effective_from: date | None = None
    effective_to: date | None = None
    storage_ref: str | None = Field(default=None, max_length=500)
    file_status: str | None = Field(default=None, max_length=50)
    active_status: str | None = Field(default=None, max_length=50)
    note_th: str | None = Field(default=None, max_length=500)


class ReviseModelDocumentRequest(BaseModel):
    """Web/API Phase 6 Batch 3B (Locked Rule 6/7). `version`/
    `effective_from` are required and non-null — pydantic itself rejects
    an omitted key, an explicit `null`, or (via `min_length`) an empty
    string for `version`; a whitespace-only `version` is rejected by the
    service layer instead, since `min_length` alone cannot detect that
    without normalizing the stored value (the original string, not a
    stripped one, is always what gets persisted).

    `document_name_th`/`active_status` inherit from the source document
    when omitted (Locked Rules 3/7); `storage_ref`/`file_status`/
    `note_th` are NEVER inherited — they default to `None` and are never
    auto-copied from the source (Locked Rules 4/7)."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=100)
    effective_from: date
    document_name_th: str | None = Field(default=None, max_length=200)
    storage_ref: str | None = Field(default=None, max_length=500)
    file_status: str | None = Field(default=None, max_length=50)
    active_status: str | None = Field(default=None, max_length=50)
    note_th: str | None = Field(default=None, max_length=500)


class ModelDocumentResponse(BaseModel):
    model_document_id: str
    model_id: str
    document_type: str | None
    document_name_th: str | None
    version: str | None
    effective_from: date | None
    effective_to: date | None
    storage_ref: str | None
    file_status: str | None
    active_status: str | None
    replaced_by_document_id: str | None
    note_th: str | None
