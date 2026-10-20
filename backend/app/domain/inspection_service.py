"""Checklist / inspection domain service.

R3 (docs/project-governance/r3-implementation-contract.md) supersedes the
Phase 3 submission rules below for every NEW submission: the checklist is
resolved per asset (ASSET override → exact MODEL → MISSING_CHECKLIST), only
the items due today are shown and accepted, both abnormal results need a
remark (photos optional), legacy NA is read-only, one inspection per asset per
Bangkok date, `request_id` idempotency, and abnormal results create or continue
a Finding episode (`app.domain.r3_inspection`). The Phase 3 notes below remain
as history for pre-R3 records.

Owns every business rule Phase 3 is allowed to define without an approved
open decision (OPEN_DECISIONS_REGISTER_EN.txt D01-D04):

- which checklist applies to an asset: "the" currently active revision for
  its `AssetType` (see `app.domain.checklist` module docstring — D01 has
  no approved assignment policy, so there is exactly one checklist family
  per asset type rather than an asset/model matrix),
- a submitted inspection must answer every item in that revision, exactly
  once, with no extra/unknown item IDs,
- a FAIL requires a non-empty remark only when the checklist item's
  `required_remark_on_fail` flag is set, and additionally an evidence
  photo when its `required_photo_on_fail` flag is set — both are
  per-item, source-data-driven flags defaulting to `False` (CORRECTION,
  post-Phase-3 verification: an earlier revision of this service required
  a remark unconditionally for every FAIL; that was an unapproved,
  hardcoded global rule with no authoritative source and has been
  replaced by the same item-level-configuration pattern
  `required_photo_on_fail` already used),
- every FAIL creates an OPEN finding (Phase 3 scope: "normal abnormal
  finding" — no automatic repair order, no severity/alert model, both
  belong to a later, explicitly-approved phase),
- nothing here ever updates, voids, or supersedes a previously submitted
  inspection (D04 is not approved) — only creation and read exist.

Attachment uploads are validated against a size limit and an allowed
content-type list (`Settings.attachment_max_size_bytes` /
`attachment_allowed_content_types_set`) so the endpoint is not completely
unrestricted. These are explicitly LOCAL-DEVELOPMENT DEFAULTS, not a
production policy: OPEN_DECISIONS_REGISTER_EN.txt M07 (file upload
limits/MIME/malware-scanning policy) remains unresolved, and this module
must not be read as having frozen it — the values are configurable via
environment variables precisely so a later, explicitly-approved production
policy can replace them without a code change.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import status

from app.config import Settings
from app.context import RequestContext
from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.attachment_service import AttachmentService
from app.domain.authz import CAN_MANAGE_FINDING_REPAIR, require_capability
from app.domain.checklist import ChecklistRevisionDetail, InspectionResultValue
from app.domain.common import Page, PageParams, bangkok_today
from app.domain.asset_lookup import lookup_equipment
from app.domain.equipment import EquipmentOperationalStatus
from app.domain.equipment_errors import require_equipment_id_usable_for_new_work
from app.domain.inspection import (
    FindingStatus,
    InspectionDetail,
    InspectionFinding,
    InspectionSummary,
    NewInspectionItemInput,
)
from app.domain.r3_inspection import (
    Answer,
    DueItem,
    R3Conflict,
    choose_assignment,
    due_items,
    has_active_repair,
    missing_checklist,
    submission_fingerprint,
    validate_answers,
)
from app.domain.repair import Repair
from app.domain.repair_service import require_round_work_allowed
from app.domain.technician_assignment import cutover_from_settings
from app.domain.meter_service import MeterService
from app.errors import ApiError
from app.repositories.base import Repository
from app.storage.base import StorageProvider


@dataclass(frozen=True)
class InspectionItemAnswer:
    """One item answer as submitted by the client, before validation."""

    item_id: str
    result: InspectionResultValue
    remark: str | None
    evidence_attachment_ids: list[str]


@dataclass(frozen=True)
class InspectionForm:
    """R3: what the inspector must answer today for one asset."""

    checklist: ChecklistRevisionDetail
    items: list[DueItem]
    inspection_date: date
    submitted_inspection_id: str | None


FOLLOWUP_AWAITING_REPAIR_DECISION = "AWAITING_REPAIR_DECISION"
FOLLOWUP_IN_REPAIR = "IN_REPAIR"


@dataclass(frozen=True)
class FindingDetail:
    finding: InspectionFinding
    repairs: list[Repair]
    followup_group: str | None
    """TS-14 derived group of an OPEN Finding; None once ENDED."""


def followup_group(finding: InspectionFinding, repairs: list[Repair]) -> str | None:
    if finding.status != FindingStatus.OPEN:
        return None
    return FOLLOWUP_IN_REPAIR if has_active_repair(repairs) else FOLLOWUP_AWAITING_REPAIR_DECISION


class InspectionService:
    def __init__(
        self,
        repository: Repository,
        storage: StorageProvider,
        settings: Settings,
        meter_service: MeterService | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._settings = settings
        self._attachments = AttachmentService(repository, storage, settings)
        # Optional for backward compatibility with any direct instantiation
        # that predates the Core Demo Fix automatic snapshot mechanism;
        # `app.dependencies.get_inspection_service` always supplies one.
        self._meter = meter_service or MeterService(repository)

    # ---- Checklist ----

    async def get_active_checklist(self, asset_type: AssetType) -> ChecklistRevisionDetail:
        detail = await self._repository.get_active_checklist_revision(asset_type)
        if detail is None:
            raise ApiError(
                code="NO_ACTIVE_CHECKLIST",
                message=f"No active inspection checklist is configured for asset type '{asset_type.value}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def get_checklist_revision(
        self, checklist_id: str, revision_id: str
    ) -> ChecklistRevisionDetail:
        detail = await self._repository.get_checklist_revision(checklist_id, revision_id)
        if detail is None:
            raise ApiError(
                code="CHECKLIST_REVISION_NOT_FOUND",
                message=f"Checklist revision '{revision_id}' was not found for checklist '{checklist_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    # ---- Attachments (reference vs evidence, see app.domain.attachment) ----

    async def upload_attachment(
        self,
        purpose: AttachmentPurpose,
        filename: str,
        content_type: str,
        data: bytes,
        uploaded_by: str | None,
        context: RequestContext,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Attachment:
        # Delegates to the shared `AttachmentService` (extracted post-Phase-3
        # so Phase 4's PM/Repair services reuse the identical boundary) —
        # this method's own signature/behavior is unchanged beyond REV06
        # section 14's added source authorization.
        if purpose == AttachmentPurpose.CHECKLIST_REFERENCE_IMAGE and self._settings.access_management_mode:
            # D6: uploading a checklist reference image has no approved capability (reading it uses
            # can_view); in Access Management mode it fails closed until the Owner maps it.
            raise ApiError(code="ACCESS_CAPABILITY_MAPPING_UNRESOLVED", status_code=status.HTTP_403_FORBIDDEN,
                           message="This change has no approved permission mapping yet; it is unavailable in "
                                   "Access Management mode")
        await self._attachments.authorize_source(
            context, source_type, source_id, "การแนบไฟล์ (attach a file)", purpose=purpose
        )
        if source_type == "REPAIR" and source_id is not None:
            # R3 TS-6 (T3 freeze rule) and L9: no new repair evidence on a frozen
            # order, nor on an R3 round without a VALID lead. Existing files stay.
            repair_detail = await self._repository.get_repair(source_id)
            if repair_detail is not None:
                await require_round_work_allowed(self._repository, cutover_from_settings(self._settings),
                                                 repair_detail.repair)
        if source_type == "INSPECTION_EQUIPMENT" and source_id is not None:
            # Phase 7 Batch 7K2 (DEC-K3(a)): after the (unguarded, shared)
            # source authorization, before storage.save and the attachment row.
            require_equipment_id_usable_for_new_work(source_id)
        return await self._attachments.upload_attachment(
            purpose=purpose,
            filename=filename,
            content_type=content_type,
            data=data,
            uploaded_by=uploaded_by,
            source_type=source_type,
            source_id=source_id,
        )

    async def get_attachment_or_none(self, attachment_id: str) -> Attachment | None:
        return await self._attachments.get_attachment_or_none(attachment_id)

    async def require_attachment(self, attachment_id: str) -> Attachment:
        return await self._attachments.require_attachment(attachment_id)

    async def require_readable_attachment(
        self, attachment_id: str, context: RequestContext
    ) -> Attachment:
        """REV06.1 (independent-audit CRITICAL-1 fix) + REV06.2 (independent-
        audit HIGH fix): `GET /attachments/{attachment_id}/file` used to
        authorize solely by possession of `attachment_id` — REV06 added
        `authorize_source` in front of upload/list-by-source but never
        wired it into the actual file-download route (fixed REV06.1), and
        REV06.1 itself only covered `REPAIR_REQUEST`-sourced attachments,
        leaving every other purpose (checklist reference image,
        inspection/PM/repair evidence) downloadable by ID alone since they
        carried no `source_type`/`source_id` at all. REV06.2 closes that:
        every purpose now either resolves a real owning record and
        authorizes against it, or (`CHECKLIST_REFERENCE_IMAGE`) uses the
        base `can_view` capability as its documented, intentional policy —
        see `AttachmentService.authorize_source` and
        docs/phase-results/core-demo-fixes-result.md "DELTA REV06.2" for
        the exact per-purpose ownership/authorization model."""
        attachment = await self._attachments.require_attachment(attachment_id)
        await self._attachments.authorize_source(
            context,
            attachment.source_type,
            attachment.source_id,
            "การดาวน์โหลดไฟล์แนบ (download an attachment)",
            purpose=attachment.purpose,
        )
        return attachment

    async def list_attachments_for_source(
        self, source_type: str, source_id: str, context: RequestContext
    ) -> list[Attachment]:
        await self._attachments.authorize_source(
            context, source_type, source_id, "การดูไฟล์แนบ (list attachments for a source)"
        )
        return await self._attachments.list_for_source(source_type, source_id)

    async def read_attachment_bytes(self, attachment: Attachment) -> bytes:
        return await self._attachments.read_attachment_bytes(attachment)

    # ---- Asset validation (reuses Phase 2 not-found codes) ----

    async def _require_asset(self, asset_type: AssetType, asset_id: str) -> str | None:
        """Validate the asset; return its vehicle model id (equipment: None —
        its model comes from the R3 equipment model reference)."""
        if asset_type == AssetType.VEHICLE:
            vehicle = await self._repository.get_vehicle(asset_id)
            if vehicle is None:
                raise ApiError(
                    code="VEHICLE_NOT_FOUND",
                    message=f"Vehicle '{asset_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            return vehicle.model_id
        else:
            # Phase 7 Batch 7K2 (DEC-K1(b)): validated, text-preserving exact
            # lookup with the shared equipment error mapping.
            equipment = await lookup_equipment(self._repository, asset_id)
            if equipment is None:
                raise ApiError(
                    code="EQUIPMENT_NOT_FOUND",
                    message=f"Equipment '{asset_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            if equipment.operational_status == EquipmentOperationalStatus.RETIRED:
                # Core Demo Fix, EQUIPMENT STATUS CHANGE — APPROVED: mirrors
                # `app.domain.asset_lookup.require_asset_exists`'s identical
                # RETIRED guard for the one asset-existence check this
                # module keeps as its own copy (see that module's docstring
                # for why it is not simply delegated to the shared helper).
                raise ApiError(
                    code="EQUIPMENT_RETIRED",
                    message=(
                        f"Equipment '{asset_id}' is RETIRED (ปลดระวาง/เลิกใช้งานถาวร) and "
                        "cannot be selected for new operational work"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            # Phase 7 Batch 7K2 (DEC-K3(a)): only submit_inspection calls this
            # method, before create_inspection — refuse an id with a known
            # text hazard before anything is written.
            require_equipment_id_usable_for_new_work(asset_id)
            return None

    # ---- R3 form and submission ----

    async def _resolve_checklist(
        self, asset_type: AssetType, asset_id: str, vehicle_model_id: str | None, today: date
    ) -> ChecklistRevisionDetail:
        model_id = vehicle_model_id
        if asset_type == AssetType.EQUIPMENT:
            model_id = await self._repository.get_equipment_model_id(asset_id, today)
        assignments = await self._repository.list_checklist_assignments(asset_type)
        chosen = choose_assignment(assignments, asset_id, model_id)
        if chosen is None:
            raise missing_checklist(asset_type.value, asset_id, model_id)
        detail = await self._repository.get_effective_checklist_revision(chosen.checklist_id, today)
        if detail is None:
            raise missing_checklist(asset_type.value, asset_id, model_id)
        return detail

    async def get_inspection_form(self, asset_type: AssetType, asset_id: str) -> InspectionForm:
        vehicle_model_id = await self._require_asset(asset_type, asset_id)
        today = bangkok_today()
        submitted = await self._repository.find_r3_inspection_on_date(asset_type, asset_id, today)
        checklist = await self._resolve_checklist(asset_type, asset_id, vehicle_model_id, today)
        last = await self._repository.get_last_result_dates(asset_type, asset_id)
        return InspectionForm(
            checklist=checklist,
            items=due_items(checklist.items, last, today),
            inspection_date=today,
            submitted_inspection_id=submitted.header.inspection_id if submitted else None,
        )

    async def submit_inspection(
        self,
        asset_type: AssetType,
        asset_id: str,
        answers: list[InspectionItemAnswer],
        overall_remark: str | None,
        inspector_user_id: str | None,
        request_id: str,
    ) -> tuple[InspectionDetail, bool]:
        """R3 submission. Returns (inspection, replayed). Order: asset checks
        (no write) → replay → one-per-day → checklist and due items → answer
        validation → evidence check → snapshot → one atomic repository write."""
        vehicle_model_id = await self._require_asset(asset_type, asset_id)
        r3_answers = [
            Answer(a.item_id, a.result, a.remark, tuple(a.evidence_attachment_ids)) for a in answers
        ]
        fingerprint = submission_fingerprint(asset_type.value, asset_id, overall_remark, r3_answers)

        replay = await self._repository.find_r3_inspection_by_request_id(request_id)
        if replay is not None:
            detail, stored = replay
            if stored != fingerprint:
                raise R3Conflict("REQUEST_ID_REUSED", "This request id was already used for a different "
                                 "submission", {"inspection_id": detail.header.inspection_id}).to_api_error()
            return detail, True

        today = bangkok_today()
        existing = await self._repository.find_r3_inspection_on_date(asset_type, asset_id, today)
        if existing is not None:
            raise R3Conflict("INSPECTION_ALREADY_SUBMITTED_TODAY", "This asset already has a submitted "
                             "inspection for this Bangkok date",
                             {"inspection_id": existing.header.inspection_id,
                              "inspection_date": today.isoformat()}).to_api_error()

        checklist = await self._resolve_checklist(asset_type, asset_id, vehicle_model_id, today)
        last = await self._repository.get_last_result_dates(asset_type, asset_id)
        shown = due_items(checklist.items, last, today)
        by_id = validate_answers(shown, r3_answers)

        prepared: list[NewInspectionItemInput] = []
        for due in shown:
            item = due.item
            answer = by_id[item.item_id]
            for attachment_id in answer.evidence_attachment_ids:
                attachment = await self._repository.get_attachment(attachment_id)
                if attachment is None or attachment.purpose != AttachmentPurpose.INSPECTION_EVIDENCE:
                    raise ApiError(
                        code="VALIDATION_ERROR",
                        message=f"Evidence attachment '{attachment_id}' was not found",
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        details={"item_id": item.item_id, "attachment_id": attachment_id},
                    )
            prepared.append(
                NewInspectionItemInput(
                    item_id=item.item_id,
                    sequence=item.sequence,
                    title=item.title,
                    inspection_point=item.inspection_point,
                    method=item.method,
                    standard=item.standard,
                    instruction=item.instruction,
                    is_critical=item.is_critical,
                    result=answer.result,
                    remark=answer.remark,
                    evidence_attachment_ids=list(answer.evidence_attachment_ids),
                    item_key=item.item_key,
                    frequency=item.frequency,
                )
            )

        # Core Demo Fix: automatic machine-state snapshot at submission time
        # — backend-derived from this asset's own history, never from an
        # editable browser field (see MeterService.capture_current_state).
        # A replayed request never reaches this point (no second snapshot).
        snapshot = await self._meter.capture_current_state(
            asset_type=asset_type,
            asset_id=asset_id,
            recorded_by=inspector_user_id,
            source_note="INSPECTION_SUBMISSION",
        )
        try:
            return await self._repository.submit_r3_inspection(
                asset_type=asset_type,
                asset_id=asset_id,
                checklist_id=checklist.checklist.checklist_id,
                revision_id=checklist.revision.revision_id,
                revision_number=checklist.revision.revision_number,
                inspector_user_id=inspector_user_id,
                overall_remark=overall_remark,
                items=prepared,
                machine_state_snapshot_id=snapshot.meter_snapshot_id,
                request_id=request_id,
                fingerprint=fingerprint,
                inspection_date=today,
            )
        except R3Conflict as conflict:
            raise conflict.to_api_error() from conflict

    # ---- R3 Findings ----

    async def get_finding_detail(self, finding_id: str) -> FindingDetail:
        finding = await self._repository.find_inspection_finding(finding_id)
        if finding is None:
            raise ApiError(code="FINDING_NOT_FOUND", message=f"Finding '{finding_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        repairs = await self._repository.list_repairs_for_finding(finding_id) if finding.is_r3 else []
        return FindingDetail(finding=finding, repairs=repairs, followup_group=followup_group(finding, repairs))

    async def list_followup(self, asset_type: AssetType | None, asset_id: str | None) -> list[FindingDetail]:
        """R3-11: every OPEN R3 Finding, with its derived follow-up group."""
        findings = await self._repository.list_r3_findings(asset_type, asset_id, FindingStatus.OPEN)
        out: list[FindingDetail] = []
        for finding in sorted(findings, key=lambda f: f.created_at):
            repairs = await self._repository.list_repairs_for_finding(finding.finding_id)
            out.append(FindingDetail(finding=finding, repairs=repairs,
                                     followup_group=followup_group(finding, repairs)))
        return out

    async def terminate_finding(self, finding_id: str, reason: str | None, context: RequestContext) -> FindingDetail:
        """E4: manual termination by the Maintenance Department Manager or an
        explicitly authorized delegate (O-3), with a mandatory reason."""
        require_capability(context, CAN_MANAGE_FINDING_REPAIR, "การยุติการติดตามรายการผิดปกติ (terminate a Finding)")
        if not reason or not reason.strip():
            raise ApiError(code="FINDING_TERMINATION_REASON_REQUIRED", message="A reason is required",
                           status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        finding = await self._repository.find_inspection_finding(finding_id)
        if finding is None:
            raise ApiError(code="FINDING_NOT_FOUND", message=f"Finding '{finding_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        if not finding.is_r3:
            raise ApiError(code="FINDING_NOT_R3", message="A pre-R3 finding has no R3 episode to terminate",
                           status_code=status.HTTP_409_CONFLICT, details={"finding_id": finding_id})
        try:
            await self._repository.terminate_finding(finding_id, ended_by=context.user_id, note=reason.strip())
        except R3Conflict as conflict:
            raise conflict.to_api_error() from conflict
        return await self.get_finding_detail(finding_id)

    # ---- History ----

    async def get_inspection(self, inspection_id: str) -> InspectionDetail:
        detail = await self._repository.get_inspection(inspection_id)
        if detail is None:
            raise ApiError(
                code="INSPECTION_NOT_FOUND",
                message=f"Inspection '{inspection_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def list_inspections(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
    ) -> Page[InspectionSummary]:
        items, total = await self._repository.list_inspections(
            asset_type=asset_type, asset_id=asset_id, params=params
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def list_findings(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        status: FindingStatus | None,
    ) -> list[InspectionFinding]:
        """Core Demo Fixes, VEHICLE LIST / CORE STATUS SUMMARY: "unresolved
        inspection finding indicator." Uses only data already produced by
        Phase 3 (every FAIL result's OPEN finding) — never fabricates a
        severity/alert model (A06/D03 remain unresolved)."""
        return await self._repository.list_inspection_findings(
            asset_type=asset_type, asset_id=asset_id, status=status
        )
