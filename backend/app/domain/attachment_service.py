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
from app.domain.asset import AssetType
from app.domain.assignment import active_primary_and_collaborators
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.authz import CAN_MANAGE_PM, CAN_MANAGE_REPAIR, CAN_RECORD_INSPECTION, CAN_VIEW
from app.errors import ApiError
from app.repositories.base import Repository
from app.storage.base import StorageProvider

# REV06.2 delta (independent-audit HIGH finding — attachment download
# authorization gap): every attachment `source_type` this codebase's
# attachment join mechanism backs. REV06/REV06.1 covered REPAIR_REQUEST
# only; every other transactional evidence purpose (repair/PM/inspection)
# used to rely purely on its owner's own `attachment_ids`/
# `evidence_attachment_ids` reverse-link, which `authorize_source` never
# consulted — so an attachment with no `source_type` at all fell through a
# no-op and was downloadable by ID alone. Those purposes now persist their
# own forward `source_type`/`source_id` at upload time too (see
# `_PURPOSES_REQUIRING_SOURCE` below) so this same gate can authorize them.
# An unsupported/unrecognized value is refused rather than silently
# accepted un-validated.
_SUPPORTED_ATTACHMENT_SOURCE_TYPES = frozenset(
    {"REPAIR_REQUEST", "REPAIR", "PM_WORK_ORDER", "INSPECTION_VEHICLE", "INSPECTION_EQUIPMENT"}
)

# REV06.2: these purposes now have a real, durable owning record available
# at upload time (the Repair/PM Work Order the caller is already working
# against, or the asset being inspected) — `source_type`/`source_id` are no
# longer optional for them, so no new source-less/orphaned attachment can
# be created going forward. `CHECKLIST_REFERENCE_IMAGE` (master/reference
# content with no per-instance owner — see `authorize_source`) and
# `REPAIR_REQUEST_EVIDENCE` (already independently fixed and tested in
# REV06.1) are deliberately not in this set.
_PURPOSES_REQUIRING_SOURCE = frozenset(
    {
        AttachmentPurpose.REPAIR_EVIDENCE,
        AttachmentPurpose.PM_EVIDENCE,
        AttachmentPurpose.INSPECTION_EVIDENCE,
    }
)

_INSPECTION_ASSET_TYPE_BY_SOURCE_TYPE = {
    "INSPECTION_VEHICLE": AssetType.VEHICLE,
    "INSPECTION_EQUIPMENT": AssetType.EQUIPMENT,
}

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
        purpose: AttachmentPurpose | None = None,
    ) -> None:
        """REV06 section 14 / REV06.2 delta (independent-audit HIGH
        finding): validate that a named `source_type`/`source_id` refers
        to a REAL record and that `context` is authorized to touch it —
        attachment-id/source-id possession alone is never sufficient (IDs
        are enumerable). `purpose` (the attachment's own recorded purpose
        for a download, or the purpose being uploaded) decides two things
        a bare `source_type`/`source_id` pair cannot: whether master
        reference content should skip the per-instance source join
        entirely (`CHECKLIST_REFERENCE_IMAGE`), and whether a missing
        source is a legacy no-op or a REV06.2 fail-closed refusal (see
        `_PURPOSES_REQUIRING_SOURCE`)."""
        if purpose == AttachmentPurpose.CHECKLIST_REFERENCE_IMAGE:
            # Master/reference content (baseline section 17): shown to
            # every actor performing any inspection regardless of role,
            # with no per-instance owning record to authorize against (see
            # `app.domain.checklist` — `reference_image_attachment_id` is
            # master data, never created through this upload endpoint in
            # practice). "Do not leave it globally downloadable merely
            # because it is a reference image" (REV06.2 section 6) is
            # satisfied by requiring the same base `can_view` capability
            # every recognized role holds — a context with no recognized
            # role/capabilities at all (DEV_AUTH fail-closed) is still
            # refused.
            if CAN_VIEW not in context.capabilities:
                raise ApiError(
                    code="ATTACHMENT_SOURCE_NOT_AUTHORIZED",
                    message=f"{action_description} requires the 'can_view' capability",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            return

        if source_type is None and source_id is None:
            if purpose in _PURPOSES_REQUIRING_SOURCE:
                # REV06.2 section 9: a pre-fix/legacy attachment (or a
                # client that omits the now-required join) must fail
                # closed rather than being guessed at from attachment ID,
                # filename, storage path, or note text.
                raise ApiError(
                    code="ATTACHMENT_SOURCE_REQUIRED",
                    message=(
                        f"{action_description} requires a recorded source_type/source_id "
                        f"for purpose '{purpose.value}' — this attachment predates that "
                        "requirement or omitted it, so it cannot be authorized"
                    ),
                    status_code=status.HTTP_403_FORBIDDEN,
                )
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

        elif source_type == "REPAIR":
            # REV06.2: the exact same active-PRIMARY/COLLABORATOR-or-
            # can_manage_repair gate `add_repair_action`/`add_repair_part`
            # already enforce (RepairService.get_active_assignment) —
            # never the denormalized `Repair.primary_technician`/
            # `.collaborators` fields, and never a second, differently-
            # behaving policy for evidence photos than for the action/part
            # they document.
            detail = await self._repository.get_repair(source_id)
            if detail is None:
                raise ApiError(
                    code="REPAIR_NOT_FOUND",
                    message=f"Repair '{source_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            history = await self._repository.list_repair_assignment_history(source_id)
            primary_technician, collaborators = active_primary_and_collaborators(history)
            is_assigned = context.user_id is not None and (
                context.user_id == primary_technician or context.user_id in collaborators
            )
            if not (is_assigned or CAN_MANAGE_REPAIR in context.capabilities):
                raise ApiError(
                    code="ATTACHMENT_SOURCE_NOT_AUTHORIZED",
                    message=(
                        f"{action_description} requires being this Repair's own active "
                        "PRIMARY/COLLABORATOR technician or holding the 'can_manage_repair' "
                        "capability"
                    ),
                    status_code=status.HTTP_403_FORBIDDEN,
                )

        elif source_type == "PM_WORK_ORDER":
            # REV06.2: mirrors `submit_pm_task_result`'s existing gate
            # exactly (PM Work Order's own `primary_technician`/
            # `collaborators` — PM's assignment-history-vs-denormalized-
            # field consistency is unrelated REV06.1 CONSISTENCY-2 scope,
            # never touched by REV06.2; reusing PM's current policy
            # unchanged is deliberate, not an oversight).
            detail = await self._repository.get_pm_work_order(source_id)
            if detail is None:
                raise ApiError(
                    code="PM_WORK_ORDER_NOT_FOUND",
                    message=f"PM work order '{source_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            work_order = detail.work_order
            is_assigned = context.user_id is not None and (
                context.user_id == work_order.primary_technician
                or context.user_id in work_order.collaborators
            )
            if not (is_assigned or CAN_MANAGE_PM in context.capabilities):
                raise ApiError(
                    code="ATTACHMENT_SOURCE_NOT_AUTHORIZED",
                    message=(
                        f"{action_description} requires being this PM Work Order's own "
                        "assigned PRIMARY/COLLABORATOR technician or holding the "
                        "'can_manage_pm' capability"
                    ),
                    status_code=status.HTTP_403_FORBIDDEN,
                )

        elif source_type in _INSPECTION_ASSET_TYPE_BY_SOURCE_TYPE:
            # REV06.2: an inspection evidence photo is captured before the
            # Inspection record itself exists (the checklist is still
            # being filled in), so there is no Inspection id yet to join
            # against — the asset being inspected is the one real, durable,
            # explicit owner available at upload time (never guessed from
            # filename/attachment id/note). No narrower per-inspection
            # data-scope model exists in this codebase today (`GET
            # /inspections/{id}` itself has no additional access gate), so
            # this uses the narrowest safe current rule: the asset must be
            # real, and the caller must hold `can_record_inspection`.
            asset_type = _INSPECTION_ASSET_TYPE_BY_SOURCE_TYPE[source_type]
            if asset_type == AssetType.VEHICLE:
                asset = await self._repository.get_vehicle(source_id)
                not_found_code = "VEHICLE_NOT_FOUND"
            else:
                asset = await self._repository.get_equipment(source_id)
                not_found_code = "EQUIPMENT_NOT_FOUND"
            if asset is None:
                raise ApiError(
                    code=not_found_code,
                    message=f"{asset_type.value.title()} '{source_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            if CAN_RECORD_INSPECTION not in context.capabilities:
                raise ApiError(
                    code="ATTACHMENT_SOURCE_NOT_AUTHORIZED",
                    message=f"{action_description} requires the 'can_record_inspection' capability",
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
