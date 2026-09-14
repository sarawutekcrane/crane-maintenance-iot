"""Shared attachment upload/download boundary.

Extracted from `InspectionService` (Phase 3) so Phase 4's PM and Repair
services can reuse the exact same StorageProvider boundary, validation,
and filename-sanitization behavior (baseline section 17 / guardrails §17:
"Use StorageProvider... reuse the existing secure/configurable attachment
boundary where appropriate") without duplicating it or changing
`InspectionService`'s own public method signatures — `InspectionService`
now delegates its `upload_attachment`/`get_attachment_or_none`/
`require_attachment`/`read_attachment_bytes` methods to an instance of
this class, so its frozen Phase 3 API contract is unchanged.

Same LOCAL-DEVELOPMENT DEFAULTS caveat as before: `M07` (production file
upload limits/MIME/malware-scanning policy) remains unresolved.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from fastapi import status

from app.config import Settings
from app.context import RequestContext
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.authz import CAN_MANAGE_REPAIR
from app.errors import ApiError
from app.repositories.base import Repository
from app.storage.base import StorageProvider

# Core Demo Fixes Delta REV06 section 14 (P1 — attachment security/source
# validation): the ONLY `source_type` this codebase's attachment join
# mechanism currently backs — every other attachment purpose (checklist
# reference image, inspection/PM/repair evidence) links back to its owner
# via that owner's own `attachment_ids`/`evidence_attachment_ids` field
# instead (see `app.domain.attachment.Attachment.source_type` docstring),
# never this `source_type`/`source_id` pair. An unsupported/unrecognized
# value is refused rather than silently accepted un-validated — this is
# deliberately narrow (REV06 section 22: "use the narrowest existing
# approved behavior") rather than a final data-scope policy for every
# possible future source type.
_SUPPORTED_ATTACHMENT_SOURCE_TYPES = frozenset({"REPAIR_REQUEST"})

_ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_UNSAFE_BASENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(filename: str, content_type: str) -> str:
    """See the original docstring in the pre-extraction `inspection_service.py`
    history: strips any path component/unsafe character from a
    client-supplied filename and normalizes the extension to one implied
    by the validated content type when the client's own extension is not
    a recognized image suffix."""
    basename = PurePosixPath(filename.replace("\\", "/")).name
    suffix = PurePosixPath(basename).suffix.lower()
    if suffix not in _ALLOWED_IMAGE_SUFFIXES:
        suffix = _EXTENSION_BY_CONTENT_TYPE.get(content_type.lower(), "")
    stem = PurePosixPath(basename).stem
    safe_stem = _UNSAFE_BASENAME_CHARS.sub("_", stem).strip("._-")[:80]
    return f"{safe_stem or 'upload'}{suffix}"


class AttachmentService:
    def __init__(
        self, repository: Repository, storage: StorageProvider, settings: Settings
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._settings = settings

    async def authorize_source(
        self,
        context: RequestContext,
        source_type: str | None,
        source_id: str | None,
        action_description: str,
    ) -> None:
        """REV06 section 14 (P1): validate that a named `source_type`/
        `source_id` refers to a REAL record and that `context` is
        authorized to touch it — attachment-id/source-id possession alone
        is never sufficient (IDs are enumerable). No-op when neither is
        given (the normal case for every attachment purpose that does not
        use this join at all). Currently covers REPAIR_REQUEST only — see
        `_SUPPORTED_ATTACHMENT_SOURCE_TYPES`."""
        if source_type is None and source_id is None:
            return
        if not source_type or not source_id:
            raise ApiError(
                code="VALIDATION_ERROR",
                message="source_type and source_id must both be provided together",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if source_type not in _SUPPORTED_ATTACHMENT_SOURCE_TYPES:
            raise ApiError(
                code="ATTACHMENT_SOURCE_TYPE_NOT_SUPPORTED",
                message=(
                    f"Attachment source_type '{source_type}' is not a supported "
                    "source for attachment linking"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"source_type": source_type},
            )

        if source_type == "REPAIR_REQUEST":
            request = await self._repository.get_repair_request(source_id)
            if request is None:
                raise ApiError(
                    code="REPAIR_REQUEST_NOT_FOUND",
                    message=f"Repair request '{source_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            # Minimum safe owner/manager model (REV06 section 14: "if
            # exact visibility is governed by an unresolved decision,
            # enforce the minimum safe owner/manager model") — the
            # request's own reporter, or Maintenance, may attach/read
            # evidence for it. Final data-scope policy remains open
            # (OPEN_DECISIONS_REGISTER_EN.txt — not decided here).
            is_reporter = (
                context.user_id is not None and context.user_id == request.reported_by_user_id
            )
            is_maintenance = CAN_MANAGE_REPAIR in context.capabilities
            if not (is_reporter or is_maintenance):
                raise ApiError(
                    code="ATTACHMENT_SOURCE_NOT_AUTHORIZED",
                    message=(
                        f"{action_description} requires being the Repair Request's own "
                        "reporter or holding the 'can_manage_repair' capability"
                    ),
                    status_code=status.HTTP_403_FORBIDDEN,
                )

    async def upload_attachment(
        self,
        purpose: AttachmentPurpose,
        filename: str,
        content_type: str,
        data: bytes,
        uploaded_by: str | None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Attachment:
        if not data:
            raise ApiError(
                code="VALIDATION_ERROR",
                message="Uploaded file is empty",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        allowed_types = self._settings.attachment_allowed_content_types_set
        if content_type.lower() not in allowed_types:
            raise ApiError(
                code="ATTACHMENT_TYPE_NOT_ALLOWED",
                message=(
                    f"Attachment content type '{content_type}' is not allowed "
                    f"(development default allowlist: {', '.join(sorted(allowed_types))})"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"content_type": content_type},
            )

        max_size = self._settings.attachment_max_size_bytes
        if len(data) > max_size:
            raise ApiError(
                code="ATTACHMENT_TOO_LARGE",
                message=(
                    f"Attachment is larger than the development default limit "
                    f"of {max_size} bytes"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"max_size_bytes": max_size, "size_bytes": len(data)},
            )

        safe_name = safe_filename(filename, content_type)
        stored = await self._storage.save(
            filename=safe_name, content_type=content_type, data=data
        )
        return await self._repository.create_attachment(
            purpose=purpose,
            storage_ref=stored.storage_ref,
            filename=safe_name,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            uploaded_by=uploaded_by,
            source_type=source_type,
            source_id=source_id,
        )

    async def get_attachment_or_none(self, attachment_id: str) -> Attachment | None:
        return await self._repository.get_attachment(attachment_id)

    async def list_for_source(self, source_type: str, source_id: str) -> list[Attachment]:
        return await self._repository.list_attachments_for_source(source_type, source_id)

    async def require_attachment(self, attachment_id: str) -> Attachment:
        attachment = await self._repository.get_attachment(attachment_id)
        if attachment is None:
            raise ApiError(
                code="ATTACHMENT_NOT_FOUND",
                message=f"Attachment '{attachment_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return attachment

    async def read_attachment_bytes(self, attachment: Attachment) -> bytes:
        return await self._storage.read(attachment.storage_ref)
