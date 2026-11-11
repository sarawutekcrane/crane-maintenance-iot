"""R6 part-lifecycle routes (FINAL §8): return from repair, status moves,
set-once identifiers, maintenance events, position replacement, the single
lifetime-status read contract (instance / position / asset), the read-only
expected Part Sets of a PM work order, and the A-4 TEST-ONLY fake meter
observation hook.

Every NEW write requires a client `X-Request-Id` (422 REQUEST_ID_REQUIRED),
is idempotent, atomic, TEST/REAL-bound and listed in the D6 Access-Management
unresolved-route registry (fail-closed until the Owner approves PG-5).
Operational writes apply the PG-5 PROPOSAL (`can_manage_repair` or
`can_manage_pm`) — an existing capability, nothing new is activated.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.part_instance_schemas import PartInstanceDetailResponse
from app.api.v1.part_lifetime_schemas import (
    AssignIdentifiersRequest,
    MaintenanceEventRequest,
    MaintenanceEventResponse,
    PartInstancePageResponse,
    ReplacePositionRequest,
    ReturnFromRepairRequest,
    StatusChangeRequest,
    TestMeterObservationRequest,
)
from app.api.v1.request_id_dependency import require_client_request_id
from app.context import RequestContext
from app.dependencies import (
    get_assignment_cutover,
    get_current_context,
    get_part_instance_service,
    get_part_lifetime_status_service,
    get_part_service,
    get_part_test_meter_source,
    get_position_lifetime_service,
    get_repository,
)
from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.domain.part_instance import PartInstanceStatus
from app.domain.part_instance_service import (
    PartInstanceService,
    apply_replay_header,
    require_operational_capability,
)
from app.domain.part_service import PartService
from app.domain.position_lifetime_service import PositionLifetimeService
from app.errors import ApiError
from app.repositories.base import Repository

router = APIRouter(tags=["part-lifecycle"])


def _actor(context: RequestContext, action: str) -> str:
    require_operational_capability(context, action)
    return context.user_id


# ---- part instance list and writes ----


@router.get("/part-instances", response_model=PartInstancePageResponse)
async def list_part_instances(
    part_id: str | None = Query(default=None),
    status: PartInstanceStatus | None = Query(default=None),
    serial_number: str | None = Query(default=None),
    tag_label: str | None = Query(default=None),
    storage_location: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    service: PartInstanceService = Depends(get_part_instance_service),
) -> PartInstancePageResponse:
    items, total = await service.list_instances(part_id=part_id, status_filter=status, serial_number=serial_number,
                                                tag_label=tag_label, storage_location=storage_location,
                                                params=PageParams(page=page, page_size=page_size))
    return PartInstancePageResponse(items=[PartInstanceDetailResponse.model_validate(d.model_dump(mode="json"))
                                           for d in items], page=page, page_size=page_size, total_items=total)


@router.post("/part-instances/{part_instance_id}/return-from-repair", response_model=PartInstanceDetailResponse)
async def return_from_repair(
    response: Response,
    part_instance_id: str,
    body: ReturnFromRepairRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
) -> PartInstanceDetailResponse:
    _actor(context, "การรับอะไหล่กลับจากซ่อม (return a part from repair)")
    detail = await service.return_from_repair(
        part_instance_id, context=context, outcome=body.outcome, repair_reference=body.repair_reference,
        new_cycle_approved=body.new_cycle_approved, approval_reason_code=body.approval_reason_code,
        storage_location=body.storage_location, effective_at=body.effective_at, note=body.note,
        request_id=request_id, body=body.model_dump(mode="json", exclude_unset=True))
    apply_replay_header(response, detail)
    return PartInstanceDetailResponse.model_validate(detail)


@router.post("/part-instances/{part_instance_id}/status", response_model=PartInstanceDetailResponse)
async def change_part_instance_status(
    response: Response,
    part_instance_id: str,
    body: StatusChangeRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
) -> PartInstanceDetailResponse:
    actor = _actor(context, "การเปลี่ยนสถานะอะไหล่ (change a part's status)")
    detail = await service.change_status(part_instance_id, actor=actor, to_status=body.to_status,
                                         storage_location=body.storage_location, reason=body.reason,
                                         effective_at=body.effective_at, request_id=request_id,
                                         body=body.model_dump(mode="json", exclude_unset=True))
    apply_replay_header(response, detail)
    return PartInstanceDetailResponse.model_validate(detail)


@router.post("/part-instances/{part_instance_id}/identifiers", response_model=PartInstanceDetailResponse)
async def assign_part_instance_identifiers(
    response: Response,
    part_instance_id: str,
    body: AssignIdentifiersRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
) -> PartInstanceDetailResponse:
    actor = _actor(context, "การระบุหมายเลข/ป้ายอะไหล่ (assign a serial or tag)")
    detail = await service.assign_identifiers(part_instance_id, actor=actor, serial_number=body.serial_number,
                                              tag_label=body.tag_label, request_id=request_id,
                                              body=body.model_dump(mode="json", exclude_unset=True))
    apply_replay_header(response, detail)
    return PartInstanceDetailResponse.model_validate(detail)


@router.post("/part-instances/{part_instance_id}/maintenance-events", response_model=MaintenanceEventResponse)
async def add_part_instance_maintenance_event(
    response: Response,
    part_instance_id: str,
    body: MaintenanceEventRequest,
    service: PartInstanceService = Depends(get_part_instance_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
) -> MaintenanceEventResponse:
    actor = _actor(context, "การบันทึกการตรวจ/ซ่อมอะไหล่ (record a part inspection or repair)")
    event = await service.add_maintenance_event(
        part_instance_id, actor=actor, action=body.action, lifetime_rule_id=body.lifetime_rule_id,
        condition_group_key=body.condition_group_key, outcome=body.outcome, effective_at=body.effective_at,
        source_type=body.source_type, source_id=body.source_id, note=body.note, request_id=request_id,
        body=body.model_dump(mode="json", exclude_unset=True))
    apply_replay_header(response, event)
    return MaintenanceEventResponse.model_validate(event)


# ---- position-lifetime writes ----


@router.post("/position-lifetime/{position_lifetime_id}/replace")
async def replace_position_lifetime(
    response: Response,
    position_lifetime_id: str,
    body: ReplacePositionRequest,
    service: PositionLifetimeService = Depends(get_position_lifetime_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
) -> dict:
    actor = _actor(context, "การเปลี่ยนชิ้นส่วนตามตำแหน่ง (replace a position-tracked part)")
    result = await service.replace(position_lifetime_id, actor=actor, reason=body.reason, part_id=body.part_id,
                                   prior_usage=body.prior_usage.to_domain(), effective_at=body.effective_at,
                                   end_snapshot_id=body.end_snapshot_id, note=body.note, request_id=request_id,
                                   body=body.model_dump(mode="json", exclude_unset=True))
    apply_replay_header(response, result)
    return dict(result)


@router.post("/position-lifetime/{position_lifetime_id}/maintenance-events",
             response_model=MaintenanceEventResponse)
async def add_position_maintenance_event(
    response: Response,
    position_lifetime_id: str,
    body: MaintenanceEventRequest,
    service: PositionLifetimeService = Depends(get_position_lifetime_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
) -> MaintenanceEventResponse:
    actor = _actor(context, "การบันทึกการตรวจ/ซ่อมอะไหล่ (record a part inspection or repair)")
    event = await service.add_maintenance_event(
        position_lifetime_id, actor=actor, action=body.action, lifetime_rule_id=body.lifetime_rule_id,
        condition_group_key=body.condition_group_key, outcome=body.outcome, effective_at=body.effective_at,
        source_type=body.source_type, source_id=body.source_id, note=body.note, request_id=request_id,
        body=body.model_dump(mode="json", exclude_unset=True))
    apply_replay_header(response, event)
    return MaintenanceEventResponse.model_validate(event)


@router.get("/position-lifetime/by-host/{part_instance_id}")
async def list_hosted_position_lifetime(
    part_instance_id: str, service: PositionLifetimeService = Depends(get_position_lifetime_service)
) -> list[dict]:
    return [r.model_dump(mode="json") for r in await service.list_for_host(part_instance_id)]


# ---- lifetime status (the one read contract; R7 consumers use the same) ----


@router.get("/part-instances/{part_instance_id}/lifetime-status")
async def part_instance_lifetime_status(part_instance_id: str,
                                        service=Depends(get_part_lifetime_status_service)) -> dict:
    return await service.instance_status(part_instance_id)


@router.get("/position-lifetime/{position_lifetime_id}/lifetime-status")
async def position_lifetime_status(position_lifetime_id: str,
                                   service=Depends(get_part_lifetime_status_service)) -> dict:
    return await service.position_status(position_lifetime_id)


@router.get("/vehicles/{vehicle_id}/part-lifetime")
async def vehicle_part_lifetime(vehicle_id: str, repository: Repository = Depends(get_repository),
                                service=Depends(get_part_lifetime_status_service)) -> dict:
    from app.domain.asset_lookup import require_asset_exists

    await require_asset_exists(repository, AssetType.VEHICLE, vehicle_id)
    return await service.asset_summary(AssetType.VEHICLE, vehicle_id)


@router.get("/equipment/{equipment_id}/part-lifetime")
async def equipment_part_lifetime(equipment_id: str, repository: Repository = Depends(get_repository),
                                  service=Depends(get_part_lifetime_status_service)) -> dict:
    from app.domain.asset_lookup import require_asset_exists

    await require_asset_exists(repository, AssetType.EQUIPMENT, equipment_id)
    return await service.asset_summary(AssetType.EQUIPMENT, equipment_id)


@router.get("/pm/work-orders/{work_order_id}/expected-part-sets")
async def pm_work_order_expected_part_sets(work_order_id: str,
                                           service: PartService = Depends(get_part_service)) -> dict:
    return await service.expected_part_sets(work_order_id)


# ---- A-4 TEST-ONLY fake meter observations ----


@router.post("/test-support/part-meter-observations")
async def record_test_part_meter_observation(
    body: TestMeterObservationRequest,
    repository: Repository = Depends(get_repository),
    source=Depends(get_part_test_meter_source),
    context: RequestContext = Depends(get_current_context),
    request_id: str = Depends(require_client_request_id),
    cutover=Depends(get_assignment_cutover),
) -> dict:
    """A-4 TEST-ONLY: record one explicitly fake verified reading. 404 unless
    the TEST-only source is effective (mock repository, TEST context,
    recognized non-production environment)."""
    if source is None or not source.enabled:
        raise ApiError(code="TEST_SUPPORT_DISABLED", message="This TEST-only hook is not available here",
                       status_code=404)
    _actor(context, "การบันทึกค่ามาตรวัดทดสอบ (record a TEST-only meter reading)")
    vehicle = await repository.get_vehicle(body.vehicle_id)
    if vehicle is None:
        raise ApiError(code="VEHICLE_NOT_FOUND", message="No vehicle record has exactly this id", status_code=404)
    # CG-1: fake evidence may only be attached to a vehicle proven to be in the (TEST) data scope.
    from app.domain.part_instance_service import require_vehicle_scope

    await require_vehicle_scope(repository, body.vehicle_id, cutover.data_context, cutover.test_batch_id)
    roles = {c.component_id: c.component_role.value for c in await repository.list_vehicle_components(body.vehicle_id)}
    if body.counter_type == "ODOMETER":
        if body.component_id is not None:
            raise ApiError(code="VALIDATION_ERROR", message="ODOMETER is vehicle-level", status_code=422)
    elif roles.get(body.component_id or "") not in ("CARRIER_ENGINE", "CRANE_ENGINE"):
        raise ApiError(code="VALIDATION_ERROR", message="ENGINE_HOUR needs a physical engine component of this vehicle",
                       status_code=422)
    observation = source.record(body.vehicle_id, body.component_id, body.counter_type, body.value)
    return {"vehicle_id": observation.vehicle_id, "component_id": observation.component_id,
            "counter_type": observation.counter_type, "value": observation.value,
            "observed_at": observation.observed_at.isoformat(), "device_id": observation.device_id,
            "device_event_id": observation.device_event_id, "test_only": True}
