"""Phase 7 Batch 7O2a — read-only vehicle registry histories (contract Final
Rev2 §4.5, §7.4, §7.5): GET /vehicles/{vehicle_id}/branch-history and
GET /vehicles/{vehicle_id}/registration-history (`can_view`). No mutation
route exists in this batch (7O2b/7O2c)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.v1.reference_data import get_registry_read_service
from app.api.v1.registry_schemas import (
    BranchBaselineResponse,
    BranchCurrentResponse,
    BranchEventResponse,
    BranchHistoryResponse,
    BranchRecordResponse,
    RegistrationCurrentResponse,
    RegistrationHistoryItemResponse,
    RegistrationHistoryResponse,
    RegistryFieldResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context
from app.domain.authz import CAN_VIEW, require_capability
from app.domain.registration import optional_text, text
from app.domain.registry_service import RegistryReadService

router = APIRouter(tags=["vehicle-registry"])


def _errors(prefix: str, tab: str) -> dict[int | str, dict[str, Any]]:
    return {
        403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."},
        404: {"description": "VEHICLE_NOT_FOUND — no vehicle_master record has exactly this vehicle_id."},
        409: {"description": "VEHICLE_ID_AMBIGUOUS (details: match_count)."},
        500: {
            "description": (
                "VEHICLE_MASTER_SCHEMA_INVALID / VEHICLE_MASTER_DATA_INVALID for the vehicle; "
                f"{prefix}_SCHEMA_INVALID (details: tab, problem, headers) or "
                f"{prefix}_DATA_INVALID (details: tab, issues) for {tab}. "
                "A failed history read is never answered with an empty list."
            )
        },
        503: {
            "description": (
                f"VEHICLE_MASTER_READ_FAILED; {prefix}_READ_FAILED (details: tab); or "
                "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED."
            )
        },
    }


def _int_or_none(value: object) -> int | None:
    raw = optional_text(value)
    return int(raw) if raw is not None else None  # validated integer text


@router.get(
    "/vehicles/{vehicle_id}/branch-history",
    response_model=BranchHistoryResponse,
    responses=_errors("BRANCH_HISTORY", "asset_branch_history"),
)
async def get_branch_history(
    vehicle_id: str,
    context: RequestContext = Depends(get_current_context),
    service: RegistryReadService = Depends(get_registry_read_service),
) -> BranchHistoryResponse:
    require_capability(context, CAN_VIEW, "ประวัติสาขาที่รับผิดชอบ (branch history)")
    read = await service.branch_history(vehicle_id)
    t = read.timeline
    return BranchHistoryResponse(
        asset_type="VEHICLE",
        asset_id=read.vehicle_id,
        timeline_status=t.status,  # type: ignore[arg-type]
        current=BranchCurrentResponse(branch_id=t.current_branch_id, source=t.current_source),  # type: ignore[arg-type]
        master=RegistryFieldResponse.of(read.master.responsible_branch),
        consistency=t.consistency,  # type: ignore[arg-type]
        history_revision=t.revision,
        baseline=(
            BranchBaselineResponse(branch_id=t.baseline_branch_id, source=t.baseline_source)  # type: ignore[arg-type]
            if t.has_baseline
            else None
        ),
        events=[
            BranchEventResponse(
                event_id=e.event_id,
                in_force=e.in_force,
                head_record_id=e.head_record_id,
                revision_no=int(e.revision_no),
                to_branch_id=e.to_branch_id,
                effective_at=e.effective_at,
                effective_precision=e.effective_precision,
                derived_from_branch_id=e.derived_from_branch_id,
                original_entry_from_branch_id=e.original_entry_from_branch_id,
                original_entry_from_source=e.original_entry_from_source,
                head_entry_from_branch_id=e.head_entry_from_branch_id,
                head_entry_from_source=e.head_entry_from_source,
                derived_end_at=e.derived_end_at,
                notes=list(e.notes),
            )
            for e in t.events
        ],
        records=[
            BranchRecordResponse(
                record_id=text(r.get("assignment_id")),
                record_kind=text(r.get("record_kind")),
                entry_operation=text(r.get("entry_operation")),
                event_id=optional_text(r.get("event_id")),
                revision_no=_int_or_none(r.get("revision_no")),
                supersedes_record_id=optional_text(r.get("supersedes_record_id")),
                branch_id=optional_text(r.get("branch_id")),
                effective_at=optional_text(r.get("start_at")),
                recorded_from_branch_id=optional_text(r.get("recorded_from_branch_id")),
                recorded_from_source=optional_text(r.get("recorded_from_source")),
                recorded_at=text(r.get("recorded_at")),
                recorded_by=text(r.get("recorded_by")),
                request_id=text(r.get("request_id")),
                related_request_id=optional_text(r.get("related_request_id")),
                reason_th=optional_text(r.get("note_th")),
                reconciled_old_master_branch_id=optional_text(r.get("reconciled_old_master_branch_id")),
            )
            for r in t.records
        ],
        excluded_test_rows=0,
        issues={},
    )


@router.get(
    "/vehicles/{vehicle_id}/registration-history",
    response_model=RegistrationHistoryResponse,
    responses=_errors("REGISTRATION_HISTORY", "vehicle_registration_history"),
)
async def get_registration_history(
    vehicle_id: str,
    context: RequestContext = Depends(get_current_context),
    service: RegistryReadService = Depends(get_registry_read_service),
) -> RegistrationHistoryResponse:
    require_capability(context, CAN_VIEW, "ประวัติทะเบียนรถ (registration history)")
    read = await service.registration_history(vehicle_id)
    return RegistrationHistoryResponse(
        vehicle_id=read.vehicle_id,
        current=RegistrationCurrentResponse(
            registration_no=RegistryFieldResponse.of(read.master.registration_no),
            registration_province=RegistryFieldResponse.of(read.master.registration_province),
        ),
        consistency=read.consistency,  # type: ignore[arg-type]
        history_revision=read.revision,
        items=[
            RegistrationHistoryItemResponse(
                change_id=text(r.get("change_id")),
                change_kind=text(r.get("change_kind")),
                old_registration_no=optional_text(r.get("old_registration_no")),
                old_registration_province_code=optional_text(r.get("old_registration_province_code")),
                new_registration_no=optional_text(r.get("new_registration_no")),
                new_registration_province_code=optional_text(r.get("new_registration_province_code")),
                recorded_at=text(r.get("recorded_at")),
                recorded_by=text(r.get("recorded_by")),
                request_id=text(r.get("request_id")),
                related_request_id=optional_text(r.get("related_request_id")),
                accepted_exceptions=[a for a in text(r.get("accepted_exceptions")).split(";") if a],
                note_th=optional_text(r.get("note_th")),
            )
            for r in read.items
        ],
        excluded_test_rows=0,
        issues={},
    )
