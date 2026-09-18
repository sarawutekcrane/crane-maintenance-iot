"""Model Document service (Web/API Phase 6 Batch 3A create/list/get +
Batch 3B revision lifecycle; see `app.domain.model_document` module
docstring for scope).

Unlike `VehicleCertificate` (Batch 2A/2B), the verified live
`model_document` schema has no `created_by_user_id`/`created_at`
columns — so, unlike `VehicleCertificateService.create_certificate`,
this service never generates or persists provenance timestamps; nothing
here is guessed/added beyond the 12 verified columns."""
from __future__ import annotations

from datetime import date, timedelta

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
        `replaced_by_document_id` is ever set here; that only ever
        happens as the second write of `revise_document` below."""
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

    # ---- Revision (Web/API Phase 6 Batch 3B) ----

    async def revise_document(
        self,
        model_document_id: str,
        version: str,
        effective_from: date,
        document_name_th: str | None,
        storage_ref: str | None,
        file_status: str | None,
        active_status: str | None,
        note_th: str | None,
        fields_set: frozenset[str] = frozenset(),
    ) -> ModelDocument:
        """Revise a model document (Locked Rules 1-8): creates a brand
        new row (`model_id`/`document_type` inherited from the source
        unconditionally, never client-suppliable), then links the source
        to it via `replaced_by_document_id` and closes the source's
        `effective_to` to the day before the new row's `effective_from`.
        The source row is never deleted or overwritten beyond that one
        link/date change (Locked Rule 1).

        `document_name_th`/`active_status` have LOCKED three-way
        semantics (the same omission-vs-explicit-null distinction Batch
        1's PATCH /drivers/{id} fix and Batch 2B's renewal established):
        omitted from the request -> inherit the source's existing value;
        present with a non-null value -> use it; present as explicit
        JSON `null` -> the new document gets `None` for that field.
        `fields_set` (the route's `body.model_fields_set`) is what makes
        "omitted" distinguishable from "explicit null" here. `file_status`/
        `storage_ref`/`note_th` are NEVER inherited (Locked Rules 4/7) —
        they are passed through exactly as given, `None` if omitted.

        Write ordering mirrors Batch 2B's renewal exactly and for the
        same reason: the new row is created FIRST, the source is linked
        SECOND. Google Sheets provides no true cross-row transaction, and
        retrying after a partial failure is NOT guaranteed to recover the
        original orphan:

        - WRITE 1 may successfully append a new row.
        - WRITE 2 may then fail before `source.replaced_by_document_id`
          is actually stored, leaving that new row an orphan — valid on
          its own, but with nothing pointing at it.
        - On retry, the source still shows no link (Locked Rule 1/8's
          completed-retry check only triggers once that link exists), and
          because this schema has no `source_revision_id`/
          `document_family_id`/idempotency key, the backend has no safe
          way to identify that specific orphan row among any others.
        - The retry therefore runs the normal path again: it creates
          ANOTHER new candidate row (WRITE 1) and, if WRITE 2 succeeds
          this time, links the source to that second candidate — not to
          the original orphan.
        - The original orphan is not deleted, relinked, or otherwise
          touched by that successful retry. It remains in the sheet,
          unlinked, and requires manual reconciliation to resolve or
          remove.

        No heuristic orphan-matching (e.g. scanning for a same-
        document_type/version/effective_from candidate and assuming it is
        the orphan) is used to guess around this, and no transaction
        framework or new schema column was added to close the gap in this
        batch."""
        source = await self._repository.get_model_document(model_document_id)
        if source is None:
            raise ApiError(
                code="MODEL_DOCUMENT_NOT_FOUND",
                message=f"Model document '{model_document_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if source.replaced_by_document_id is not None:
            # Completed-revision retry (Locked Rule 1/8): if this
            # document was already revised (by an earlier, successful
            # call, or an earlier attempt that completed both writes), do
            # not create a second successor — return the existing one.
            # Anything inconsistent about that linkage is a corrupted
            # state this method refuses to silently paper over.
            successor = await self._repository.get_model_document(
                source.replaced_by_document_id
            )
            if (
                successor is None
                or successor.model_id != source.model_id
                or successor.document_type != source.document_type
            ):
                raise ApiError(
                    code="MODEL_DOCUMENT_REVISION_STATE_CONFLICT",
                    message=(
                        f"Model document '{model_document_id}' already has a "
                        "replaced_by_document_id linkage that is missing or inconsistent; "
                        "this requires manual reconciliation."
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            return successor

        # Locked Rule 2: effective-date lifecycle.
        if source.effective_from is None:
            raise ApiError(
                code="MODEL_DOCUMENT_EFFECTIVE_FROM_MISSING",
                message=(
                    f"Model document '{model_document_id}' has no effective_from; a source "
                    "document must have one before it can be revised."
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if effective_from <= source.effective_from:
            raise ApiError(
                code="MODEL_DOCUMENT_EFFECTIVE_FROM_NOT_LATER",
                message=(
                    f"New effective_from ({effective_from.isoformat()}) must be strictly "
                    f"later than the source document's effective_from "
                    f"({source.effective_from.isoformat()})."
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        expected_old_effective_to = effective_from - timedelta(days=1)
        if source.effective_to is not None and source.effective_to != expected_old_effective_to:
            raise ApiError(
                code="MODEL_DOCUMENT_EFFECTIVE_TO_CONFLICT",
                message=(
                    f"Model document '{model_document_id}' already has effective_to="
                    f"{source.effective_to.isoformat()}, which is not the day before the new "
                    f"effective_from ({expected_old_effective_to.isoformat()} expected); "
                    "refusing to silently overwrite an incompatible value."
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Locked Rule 6: version must be non-blank and must not exactly
        # equal the source's version. `.strip()` is used only to detect a
        # whitespace-only value — the original, unstripped string is
        # always what gets stored (never normalized).
        if not version.strip():
            raise ApiError(
                code="MODEL_DOCUMENT_VERSION_REQUIRED",
                message="version must not be empty or whitespace-only.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if version == source.version:
            raise ApiError(
                code="MODEL_DOCUMENT_VERSION_DUPLICATE",
                message=(
                    f"New version ({version!r}) must not exactly equal the source document's "
                    f"version ({source.version!r})."
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Locked Rules 3/4/7: field inheritance resolution.
        resolved_document_name_th = (
            document_name_th if "document_name_th" in fields_set else source.document_name_th
        )
        resolved_active_status = (
            active_status if "active_status" in fields_set else source.active_status
        )
        # file_status/storage_ref/note_th are never inherited — passed
        # through exactly as given (None if omitted).

        # WRITE 1: create the new row first.
        new_document = await self._repository.create_model_document(
            model_id=source.model_id,
            document_type=source.document_type,
            document_name_th=resolved_document_name_th,
            version=version,
            effective_from=effective_from,
            effective_to=None,
            storage_ref=storage_ref,
            file_status=file_status,
            active_status=resolved_active_status,
            note_th=note_th,
        )
        # WRITE 2: link the source to the new row and close its
        # effective_to. Every other column on the source is untouched.
        await self._repository.finalize_model_document_revision(
            model_document_id=source.model_document_id,
            effective_to=expected_old_effective_to,
            replaced_by_document_id=new_document.model_document_id,
        )
        return new_document


__all__ = ["ModelDocumentService"]
