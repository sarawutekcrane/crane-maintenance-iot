"""Driver / Operator master + vehicle<->driver assignment routes
(Web/API Phase 6 Batch 1).

No new capability is introduced here (see the Phase 6 Batch 1 result
report, section 8): driver/operator master data and its vehicle
assignment history are, like `update_vehicle_machine_no`/
`change_equipment_status` before them, outside REV05's explicit
Maintenance-controlled Repair/PM workflow-authority scope, so they follow
that same established precedent (open to any authenticated actor) rather
than inventing a 7th capability not present in the live `role_permission`
sheet's verified 6 columns. Final RBAC remains Phase 10 (M02)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.driver_schemas import (
    AssignDriverRequest,
    CreateDriverRequest,
    DriverResponse,
    UpdateDriverRequest,
    VehicleDriverAssignmentResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_driver_service
from app.domain.common import Page, PageParams
from app.domain.driver import Driver, VehicleDriverAssignment
from app.domain.driver_service import DriverService

router = APIRouter(tags=["drivers"])


def _driver_response(driver: Driver) -> DriverResponse:
    return DriverResponse.model_validate(driver.model_dump())


def _assignment_response(entry: VehicleDriverAssignment) -> VehicleDriverAssignmentResponse:
    return VehicleDriverAssignmentResponse.model_validate(entry.model_dump())


@router.post("/drivers", response_model=DriverResponse)
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
) -> Page[DriverResponse]:
    result = await service.list_drivers(q=q, params=PageParams(page=page, page_size=page_size))
    return Page[DriverResponse](
        items=[_driver_response(d) for d in result.items],
        page=result.page,
        page_size=result.page_size,
        total_items=result.total_items,
    )


@router.get("/drivers/{driver_id}", response_model=DriverResponse)
async def get_driver(
    driver_id: str, service: DriverService = Depends(get_driver_service)
) -> DriverResponse:
    driver = await service.get_driver(driver_id)
    return _driver_response(driver)


@router.patch("/drivers/{driver_id}", response_model=DriverResponse)
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


@router.get(
    "/vehicles/{vehicle_id}/driver-assignments",
    response_model=list[VehicleDriverAssignmentResponse],
)
async def list_vehicle_driver_assignments(
    vehicle_id: str, service: DriverService = Depends(get_driver_service)
) -> list[VehicleDriverAssignmentResponse]:
    entries = await service.list_vehicle_driver_history(vehicle_id)
    return [_assignment_response(e) for e in entries]


@router.post(
    "/vehicles/{vehicle_id}/driver-assignments",
    response_model=VehicleDriverAssignmentResponse,
)
async def assign_driver(
    vehicle_id: str,
    body: AssignDriverRequest,
    service: DriverService = Depends(get_driver_service),
    context: RequestContext = Depends(get_current_context),
) -> VehicleDriverAssignmentResponse:
    entry = await service.assign_driver(
        vehicle_id=vehicle_id,
        driver_id=body.driver_id,
        is_primary=body.is_primary,
        assignment_status=body.assignment_status,
        note_th=body.note_th,
        changed_by_user_id=context.user_id,
    )
    return _assignment_response(entry)


@router.post(
    "/vehicle-driver-assignments/{assignment_id}/end",
    response_model=VehicleDriverAssignmentResponse,
)
async def end_vehicle_driver_assignment(
    assignment_id: str,
    service: DriverService = Depends(get_driver_service),
    context: RequestContext = Depends(get_current_context),
) -> VehicleDriverAssignmentResponse:
    entry = await service.end_assignment(
        assignment_id=assignment_id, changed_by_user_id=context.user_id
    )
    return _assignment_response(entry)
