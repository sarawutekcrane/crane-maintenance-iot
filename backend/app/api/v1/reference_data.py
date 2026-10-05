"""Phase 7 Batch 7O2a — reference lists for registry display (contract Final
Rev2 §7.2): GET /branches and GET /provinces (`can_view`, read-only). The UI
resolves codes against these; a failure here is reported as an error, never
as an empty list, so the UI can say "reference unavailable" instead of
"unknown code"."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.v1.registry_schemas import (
    BranchListResponse,
    BranchResponse,
    ProvinceListResponse,
    ProvinceResponse,
)
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_repository, get_settings_dependency
from app.domain.authz import CAN_VIEW, require_capability
from app.domain.registry_service import RegistryReadService
from app.repositories.base import Repository

router = APIRouter(tags=["reference-data"])


def get_registry_read_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> RegistryReadService:
    return RegistryReadService(repository, settings.registry_context_effective)


def _errors(prefix: str, tab: str) -> dict[int | str, dict[str, Any]]:
    return {
        403: {"description": "HTTP_ERROR — the caller lacks the 'can_view' capability. No data is read."},
        500: {
            "description": (
                f"{prefix}_SCHEMA_INVALID (details: tab, problem, headers) or "
                f"{prefix}_DATA_INVALID (details: tab, issues) — {tab} cannot be read exactly."
            )
        },
        503: {
            "description": (
                f"{prefix}_READ_FAILED (details: tab) — {tab} could not be read; or "
                "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED (google_sheets mode without REGISTRY_DATA_CONTEXT)."
            )
        },
    }


@router.get("/branches", response_model=BranchListResponse, responses=_errors("BRANCH_MASTER", "branch_master"))
async def list_branches(
    context: RequestContext = Depends(get_current_context),
    service: RegistryReadService = Depends(get_registry_read_service),
) -> BranchListResponse:
    # Authorization before any repository read: a denied request reads nothing.
    require_capability(context, CAN_VIEW, "รายชื่อสาขา (branch list)")
    entries = await service.list_branches()
    return BranchListResponse(
        items=[BranchResponse(branch_id=e.code, branch_name=e.name, is_active=e.is_active) for e in entries]
    )


@router.get("/provinces", response_model=ProvinceListResponse, responses=_errors("PROVINCE_MASTER", "province_master"))
async def list_provinces(
    context: RequestContext = Depends(get_current_context),
    service: RegistryReadService = Depends(get_registry_read_service),
) -> ProvinceListResponse:
    require_capability(context, CAN_VIEW, "รายชื่อจังหวัด (province list)")
    entries = await service.list_provinces()
    return ProvinceListResponse(
        items=[
            ProvinceResponse(province_code=e.code, province_name_th=e.name, is_active=e.is_active) for e in entries
        ]
    )
