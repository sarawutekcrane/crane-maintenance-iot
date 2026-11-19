"""R8 PRE-UAT — PM Master TEST profile routes (Owner Consolidated Source Expansion Gate 2026-11-18, SG-PM).

Registered by `app.main` ONLY when `PM_MASTER_TEST_PROFILE=true` (Mock + Access Management + non-production,
enforced by the config validator and again per request). With the profile OFF these paths do not exist and
this module is never imported. The PM Master is reached only through `app.domain.pm_master_test_profile`,
lazily (firewall exception, Owner-approved paths #94 / #95).

Reads (trusted `can_view`):
- GET  /pm-master-test/status                          profile, head revision, assignments, variant decisions
- GET  /pm-master-test/previews/{preview_id}           REVIEW ledger + mapping candidates
- GET  /pm-master-test/vehicles/{vehicle_id}/due       per-Set PM Due from THIS TEST Master
Writes (client X-Request-Id; D6 verified employee; Master authority = per-employee TEST grants):
- POST /pm-master-test/previews                        can_test_pm_master_publish (built-in synthetic source)
- POST /pm-master-test/previews/{preview_id}/reviews   can_test_pm_master_publish
- POST /pm-master-test/publications                    can_test_pm_master_publish
- POST /pm-master-test/variant-approvals               can_test_pm_master_publish
- POST /pm-master-test/assignments                     can_test_pm_master_assign
- POST /pm-master-test/vehicles/{vehicle_id}/work-orders   existing can_manage_pm (PmService.open_master_work_order)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.v1.pm import _work_order_detail_response
from app.api.v1.pm_due_routes import _vehicle_response
from app.api.v1.pm_master_test_schemas import (
    AssignmentRequest,
    OpenWorkOrderRequest,
    PreviewRequest,
    PublishRequest,
    ReviewRequest,
    VariantApprovalRequest,
)
from app.api.v1.pm_schemas import PmWorkOrderDetailResponse, VehiclePmDueResponse
from app.api.v1.request_id_dependency import require_client_request_id
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_pm_service, get_repository, get_settings_dependency
from app.domain import pm_master_test_profile as profile
from app.domain.pm_service import PmService
from app.domain.technician_assignment import cutover_from_settings
from app.repositories.base import Repository

router = APIRouter(prefix="/pm-master-test", tags=["preuat-pm-master-test"])


class _Ctx:
    """Everything one request needs, resolved with the profile guard first."""

    def __init__(self, context: RequestContext, repository: Repository, settings: Settings) -> None:
        profile.require_profile_enabled(settings)
        self.context = context
        self.master = profile.master_for(repository, cutover_from_settings(settings).test_batch_id or "")


def _ctx(context: RequestContext = Depends(get_current_context),
         repository: Repository = Depends(get_repository),
         settings: Settings = Depends(get_settings_dependency)) -> _Ctx:
    return _Ctx(context, repository, settings)


def _store(c: _Ctx) -> Any:
    return c.master._store  # the profile's own TEST store (read-only views)


@router.get("/status")
async def get_status(c: _Ctx = Depends(_ctx)) -> dict[str, object]:
    profile.require_trusted_viewer(c.context)
    return profile.profile_status(c.master, _store(c))


@router.get("/previews/{preview_id}")
async def get_preview(preview_id: str, c: _Ctx = Depends(_ctx)) -> dict[str, object]:
    profile.require_trusted_viewer(c.context)
    registration = _store(c).preview(preview_id)
    if registration is None:
        from app.errors import ApiError

        raise ApiError(code="PM_MASTER_PREVIEW_NOT_FOUND", message="No preview has this id", status_code=404)
    return profile.preview_view(registration, tuple(_store(c).resolutions))


@router.post("/previews")
async def register_preview(body: PreviewRequest, c: _Ctx = Depends(_ctx),
                           request_id: str = Depends(require_client_request_id)) -> dict[str, object]:
    registration = await c.master.register_preview(c.context, workbook=profile.synthetic_workbook(),
                                                   source_file=profile.SOURCE_FILE, reason=body.reason,
                                                   request_id=request_id)
    return profile.preview_view(registration, tuple(_store(c).resolutions))


@router.post("/previews/{preview_id}/reviews")
async def record_review(preview_id: str, body: ReviewRequest, c: _Ctx = Depends(_ctx),
                        request_id: str = Depends(require_client_request_id)) -> dict[str, object]:
    resolution = await c.master.record_review(c.context, preview_id=preview_id,
                                              expected_source_digest=body.expected_source_digest,
                                              entry_id=body.entry_id, outcome=body.outcome, evidence=body.evidence,
                                              values=profile.as_mapping(body.values), request_id=request_id)
    return {"resolution_id": resolution.resolution_id, "entry_id": resolution.entry_id,
            "outcome": resolution.outcome, "preview": profile.preview_view(_store(c).preview(preview_id),
                                                                            tuple(_store(c).resolutions))}


@router.post("/publications")
async def publish(body: PublishRequest, c: _Ctx = Depends(_ctx),
                  request_id: str = Depends(require_client_request_id)) -> dict[str, object]:
    outcome = await c.master.publish(c.context, plan_code=profile.PLAN_CODE, expected_revision=body.expected_revision,
                                     preview_id=body.preview_id, expected_source_digest=body.expected_source_digest,
                                     reason=body.reason, request_id=request_id)
    return {"replayed": outcome.replayed, "revision": profile.revision_view(outcome.revision)}


@router.post("/variant-approvals")
async def approve_variant(body: VariantApprovalRequest, c: _Ctx = Depends(_ctx),
                          request_id: str = Depends(require_client_request_id)) -> dict[str, object]:
    outcome = await c.master.approve_model_variant(
        c.context, model_id=body.model_id, plan_code=profile.PLAN_CODE, model_variant=body.model_variant,
        expected_version=body.expected_version, preview_id=body.preview_id,
        expected_source_digest=body.expected_source_digest, source_rows=body.source_rows, evidence=body.evidence,
        reason=body.reason, request_id=request_id)
    r = outcome.record
    return {"replayed": outcome.replayed, "model_id": r.model_id, "plan_code": r.plan_code,
            "model_variant": r.model_variant, "state": r.state, "version": r.version}


@router.post("/assignments")
async def set_assignment(body: AssignmentRequest, c: _Ctx = Depends(_ctx),
                         request_id: str = Depends(require_client_request_id)) -> dict[str, object]:
    outcome = await c.master.set_assignment(c.context, vehicle_id=body.vehicle_id, assembly=body.assembly,
                                            plan_code=body.plan_code, expected_version=body.expected_version,
                                            reason=body.reason, request_id=request_id)
    r = outcome.record
    return {"replayed": outcome.replayed, "vehicle_id": r.vehicle_id, "assembly": r.assembly, "state": r.state,
            "plan_code": r.plan_code, "version": r.version}


@router.get("/vehicles/{vehicle_id}/due", response_model=VehiclePmDueResponse)
async def vehicle_due(vehicle_id: str, c: _Ctx = Depends(_ctx),
                      pm: PmService = Depends(get_pm_service)) -> VehiclePmDueResponse:
    profile.require_trusted_viewer(c.context)
    service = profile.pm_with_master(pm, c.master, c.context)
    return _vehicle_response(await service.read_vehicle_pm_due(c.context, vehicle_id))


@router.post("/vehicles/{vehicle_id}/work-orders", response_model=PmWorkOrderDetailResponse)
async def open_work_order(vehicle_id: str, body: OpenWorkOrderRequest, c: _Ctx = Depends(_ctx),
                          pm: PmService = Depends(get_pm_service),
                          request_id: str = Depends(require_client_request_id)) -> PmWorkOrderDetailResponse:
    profile.require_trusted_viewer(c.context)
    detail = await pm.open_master_work_order(c.master, c.context, asset_id=vehicle_id,
                                             plan_code=profile.PLAN_CODE, revision_number=body.revision_number,
                                             selected_set_keys=list(body.selected_set_keys), request_id=request_id,
                                             note=body.note)
    return _work_order_detail_response(detail)
