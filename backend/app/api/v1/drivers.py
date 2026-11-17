"""Driver / Operator master routes (Web/API Phase 6 Batch 1): the four
Driver Master routes. R2 Batch R2-C3 (A2-8 / A2-10) retired the three
Phase 6 vehicle<->driver assignment routes (`GET` / `POST
/vehicles/{vehicle_id}/driver-assignments`, `POST
/vehicle-driver-assignments/{assignment_id}/end`); the live
`vehicle_driver` tab is left untouched.

No new capability is introduced here (see the Phase 6 Batch 1 result
report, section 8): driver/operator master data and its vehicle
assignment history are, like `update_vehicle_machine_no`/
`change_equipment_status` before them, outside REV05's explicit
Maintenance-controlled Repair/PM workflow-authority scope, so they follow
that same established precedent (open to any authenticated actor) rather
than inventing a 7th capability not present in the live `role_permission`
sheet's verified 6 columns. Final RBAC remains Phase 10 (M02)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.driver_schemas import CreateDriverRequest, DriverResponse, UpdateDriverRequest
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_driver_service, get_repository, get_settings_dependency
from app.domain.authz import require_trusted_reader
from app.errors import ApiError
from app.repositories.base import Repository
from app.domain.common import Page, PageParams
from app.domain.driver import Driver
from app.domain.driver_service import DriverService

router = APIRouter(tags=["drivers"])


def _driver_response(driver: Driver) -> DriverResponse:
    return DriverResponse.model_validate(driver.model_dump())


_READ_TH = "การดูข้อมูลคนขับ (read drivers)"
_WRITE_TH = "การบันทึกข้อมูลคนขับ (create / update driver)"


async def _trusted_driver_writer(
    request: Request,
    settings: Settings = Depends(get_settings_dependency),
    repository: Repository = Depends(get_repository),
) -> None:
    """R7 Owner decision D2 (APPROVE_TRUSTED_ACTOR, the P-2 = A principle): a driver write
    needs a trusted, non-blank server-derived actor. A route dependency, so it runs after
    the router-level D6 write policy (which still refuses these writes in Access
    Management mode) and before body validation and any repository write. No role
    restriction is added: a trusted legacy actor keeps the previous semantics."""
    context = await get_current_context(request, settings, repository)
    if not (context.user_id or "").strip():
        raise ApiError(code="ACCESS_ACTOR_NOT_VERIFIED", status_code=403,
                       message=f"{_WRITE_TH} requires a trusted, authenticated actor")


@router.post("/drivers", response_model=DriverResponse, dependencies=[Depends(_trusted_driver_writer)])
async def create_driver(
    body: CreateDriverRequest, service: DriverService = Depends(get_driver_service)
) -> DriverResponse:
    driver = await service.create_driver(
        driver_name_th=body.driver_name_th,
        phone=body.phone,
        license_no=body.license_no,
        license_expiry_date=body.license_expiry_date,
        active_status=body.active_status,
        note_th=body.note_th,
    )
    return _driver_response(driver)


@router.get("/drivers", response_model=Page[DriverResponse])
async def list_drivers(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: DriverService = Depends(get_driver_service),
    context: RequestContext = Depends(get_current_context),
) -> Page[DriverResponse]:
    # R7 policy R1 P-3: driver master rows carry phone / license (personal data).
    require_trusted_reader(context, _READ_TH)
    result = await service.list_drivers(q=q, params=PageParams(page=page, page_size=page_size))
    return Page[DriverResponse](
        items=[_driver_response(d) for d in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/drivers/{driver_id}", response_model=DriverResponse)
async def get_driver(
    driver_id: str, service: DriverService = Depends(get_driver_service),
    context: RequestContext = Depends(get_current_context),
) -> DriverResponse:
    require_trusted_reader(context, _READ_TH)
    driver = await service.get_driver(driver_id)
    return _driver_response(driver)


@router.patch("/drivers/{driver_id}", response_model=DriverResponse,
              dependencies=[Depends(_trusted_driver_writer)])
async def update_driver(
    driver_id: str,
    body: UpdateDriverRequest,
    service: DriverService = Depends(get_driver_service),
) -> DriverResponse:
    # LIVE UAT DEFECT FIX: a field omitted from the PATCH request body
    # must not be silently erased. `model_fields_set` is Pydantic's own
    # mechanism for "was this field actually present in the request" —
    # distinct from a field explicitly sent as JSON `null`, which is
    # NOT in this set even though `body.phone` etc. read back as `None`
    # either way. See DriverService.update_driver for how the two cases
    # are resolved differently.
    driver = await service.update_driver(
        driver_id=driver_id,
        driver_name_th=body.driver_name_th,
        phone=body.phone,
        license_no=body.license_no,
        license_expiry_date=body.license_expiry_date,
        active_status=body.active_status,
        note_th=body.note_th,
        fields_set=body.model_fields_set,
    )
    return _driver_response(driver)
