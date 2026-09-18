"""Vehicle Certificate routes (Web/API Phase 6 Batch 2A create/list/get/
history foundation + Batch 2B renewal/REPLACED/EXPIRED lifecycle).

Same open-to-any-authenticated-actor precedent as
`app.api.v1.drivers` (see that module's docstring): certificate master
data is, like driver/operator master data before it, outside REV05's
explicit Maintenance-controlled Repair/PM workflow-authority scope. Final
RBAC remains Phase 10 (M02)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.vehicle_certificate_schemas import (
    CreateVehicleCertificateRequest,
    RenewVehicleCertificateRequest,
    VehicleCertificateResponse,
)
from app.context import RequestContext
from app.dependencies import get_current_context, get_vehicle_certificate_service
from app.domain.vehicle_certificate import VehicleCertificate
from app.domain.vehicle_certificate_service import VehicleCertificateService

router = APIRouter(tags=["vehicle-certificates"])


def _certificate_response(certificate: VehicleCertificate) -> VehicleCertificateResponse:
    return VehicleCertificateResponse.model_validate(certificate.model_dump())


@router.post(
    "/vehicles/{vehicle_id}/certificates",
    response_model=VehicleCertificateResponse,
)
async def create_vehicle_certificate(
    vehicle_id: str,
    body: CreateVehicleCertificateRequest,
    service: VehicleCertificateService = Depends(get_vehicle_certificate_service),
    context: RequestContext = Depends(get_current_context),
) -> VehicleCertificateResponse:
    certificate = await service.create_certificate(
        vehicle_id=vehicle_id,
        certificate_type_code=body.certificate_type_code,
        certificate_type_name_th=body.certificate_type_name_th,
        document_no=body.document_no,
        issue_date=body.issue_date,
        expiry_date=body.expiry_date,
        alert_lead_days=body.alert_lead_days,
        certificate_status=body.certificate_status,
        storage_ref=body.storage_ref,
        note_th=body.note_th,
        created_by_user_id=context.user_id,
    )
    return _certificate_response(certificate)


@router.get(
    "/vehicles/{vehicle_id}/certificates",
    response_model=list[VehicleCertificateResponse],
)
async def list_vehicle_certificates(
    vehicle_id: str,
    service: VehicleCertificateService = Depends(get_vehicle_certificate_service),
) -> list[VehicleCertificateResponse]:
    certificates = await service.list_for_vehicle(vehicle_id)
    return [_certificate_response(c) for c in certificates]


@router.get("/certificates/{certificate_id}", response_model=VehicleCertificateResponse)
async def get_vehicle_certificate(
    certificate_id: str,
    service: VehicleCertificateService = Depends(get_vehicle_certificate_service),
) -> VehicleCertificateResponse:
    certificate = await service.get_certificate(certificate_id)
    return _certificate_response(certificate)


@router.post("/certificates/{certificate_id}/renew", response_model=VehicleCertificateResponse)
async def renew_vehicle_certificate(
    certificate_id: str,
    body: RenewVehicleCertificateRequest,
    service: VehicleCertificateService = Depends(get_vehicle_certificate_service),
    context: RequestContext = Depends(get_current_context),
) -> VehicleCertificateResponse:
    # LOCKED RENEWAL SEMANTICS correction: certificate_type_name_th/
    # alert_lead_days "inherit if omitted" must distinguish "omitted from
    # the request body" from "present as explicit null" — the same
    # omission-vs-null distinction Batch 1's PATCH /drivers/{id} fix
    # established via `model_fields_set`. A plain `body.field is not
    # None` check cannot make that distinction (both cases read as
    # `None`), so `body.model_fields_set` is threaded through to the
    # service, which is the only layer that knows the source
    # certificate's existing value to inherit from.
    certificate = await service.renew_certificate(
        certificate_id=certificate_id,
        certificate_type_name_th=body.certificate_type_name_th,
        document_no=body.document_no,
        issue_date=body.issue_date,
        expiry_date=body.expiry_date,
        alert_lead_days=body.alert_lead_days,
        storage_ref=body.storage_ref,
        note_th=body.note_th,
        created_by_user_id=context.user_id,
        fields_set=body.model_fields_set,
    )
    return _certificate_response(certificate)
