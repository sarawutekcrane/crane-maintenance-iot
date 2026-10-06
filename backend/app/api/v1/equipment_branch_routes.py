"""R2 Batch R2b — GET /equipment/{equipment_id}/branch-history (`can_view`).

Read only. A dedicated response model: the frozen R1 `BranchHistoryResponse`
(asset_type VEHICLE) is not widened. The sub-models are the R1 ones, reused
unchanged, and the baseline/event/record mapping below is the R1 vehicle
mapping (`registry_routes.get_branch_history`), kept separate so the frozen
vehicle route is untouched; parity is pinned by tests.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v1.registry_schemas import (
    BranchBaselineResponse,
    BranchCurrentResponse,
    BranchEventResponse,
    BranchRecordResponse,
    RegistryFieldResponse,
)
from app.config import Settings
from app.context import RequestContext
from app.dependencies import (
    get_current_context,
    get_repository,
    get_settings_dependency,
)
from app.domain.authz import CAN_VIEW, require_capability
from app.domain.branch_timeline import BranchTimeline
from app.domain.equipment_branch_history import EquipmentBranchHistoryService
from app.domain.registration import optional_text, text
from app.repositories.base import Repository

router = APIRouter(tags=["equipment-branch-history"])


class EquipmentBranchHistoryResponse(BaseModel):
    asset_type: Literal["EQUIPMENT"]
    asset_id: str
    timeline_status: Literal["VALID", "AMBIGUOUS_ORDER"]
    current: BranchCurrentResponse
    # Always NOT_IN_SCHEMA: no equipment projection column is approved (R2d).
    master: RegistryFieldResponse
    # Never CONSISTENT / PROJECTION_MISMATCH: there is no projection to compare.
    consistency: Literal["NO_HISTORY", "UNDETERMINED"]
    history_revision: str
    baseline: BranchBaselineResponse | None
    events: list[BranchEventResponse]
    records: list[BranchRecordResponse]
    excluded_test_rows: int
    issues: dict[str, int]


def get_equipment_branch_history_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> EquipmentBranchHistoryService:
    return EquipmentBranchHistoryService(repository, settings.registry_context_effective)


_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."},
    404: {"description": "EQUIPMENT_NOT_FOUND — no equipment_master record has exactly this equipment_id."},
    409: {"description": "EQUIPMENT_ID_AMBIGUOUS (details: match_count)."},
    500: {
        "description": (
            "EQUIPMENT_MASTER_SCHEMA_INVALID / EQUIPMENT_MASTER_DATA_INVALID for the equipment; "
            "BRANCH_HISTORY_SCHEMA_INVALID (details: tab, problem, headers) or "
            "BRANCH_HISTORY_DATA_INVALID (details: tab, issues) for asset_branch_history. "
            "A failed history read is never answered with an empty list."
        )
    },
    503: {
        "description": (
            "EQUIPMENT_MASTER_READ_FAILED; BRANCH_HISTORY_READ_FAILED (details: tab); or "
            "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED."
        )
    },
}


def _int_or_none(value: object) -> int | None:
    raw = optional_text(value)
    return int(raw) if raw is not None else None  # validated integer text


def _baseline(t: BranchTimeline) -> BranchBaselineResponse | None:
    if not t.has_baseline:
        return None
    return BranchBaselineResponse(branch_id=t.baseline_branch_id, source=t.baseline_source)  # type: ignore[arg-type]


def _events(t: BranchTimeline) -> list[BranchEventResponse]:
    return [
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
    ]


def _records(t: BranchTimeline) -> list[BranchRecordResponse]:
    return [
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
    ]


@router.get(
    "/equipment/{equipment_id}/branch-history",
    response_model=EquipmentBranchHistoryResponse,
    responses=_ERRORS,
)
async def get_equipment_branch_history(
    equipment_id: str,
    context: RequestContext = Depends(get_current_context),
    service: EquipmentBranchHistoryService = Depends(get_equipment_branch_history_service),
) -> EquipmentBranchHistoryResponse:
    require_capability(context, CAN_VIEW, "ประวัติสาขาที่รับผิดชอบของเครื่องจักร (equipment branch history)")
    read = await service.branch_history(equipment_id)
    t = read.timeline
    return EquipmentBranchHistoryResponse(
        asset_type="EQUIPMENT",
        asset_id=read.equipment_id,
        timeline_status=t.status,  # type: ignore[arg-type]
        current=BranchCurrentResponse(branch_id=t.current_branch_id, source=t.current_source),  # type: ignore[arg-type]
        master=RegistryFieldResponse.of(read.master),
        consistency=t.consistency,  # type: ignore[arg-type]
        history_revision=t.revision,
        baseline=_baseline(t),
        events=_events(t),
        records=_records(t),
        excluded_test_rows=0,
        issues={},
    )
