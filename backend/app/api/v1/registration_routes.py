"""Phase 7 Batch 7O2b — registration mutations (contract Final Rev2 §3, §4.4,
§4.6; Outcome Classification Addendum):

- PATCH /vehicles/{vehicle_id}/registration
- POST  /vehicles/{vehicle_id}/registration-history/reconciliations

Order: the `can_edit_vehicle_registration` dependency (403), then the client
`X-Request-Id` dependency (422 REQUEST_ID_REQUIRED), then the body — parsed
and validated HERE, after both dependencies, so that even a malformed JSON
body from an unauthorized caller is a 403 (FastAPI would otherwise parse a
declared body parameter before any dependency). All three refusals make zero
repository calls. Branch mutations are not part of this batch (7O2c).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.registry_schemas import (
    RegistrationChangedResponse,
    RegistrationChangeRecordResponse,
    RegistrationChangeRequest,
    RegistrationNoOpResponse,
    RegistrationReconciliationRequest,
    RegistrationReplayResponse,
    VehicleRegistryResponse,
    VehicleWithRegistryResponse,
)
from app.api.v1.registry_mutation_body import effective_test_batch_id, openapi_body, parse_body
from app.api.v1.request_id_dependency import require_capability_dependency, require_client_request_id
from app.api.v1.vehicle_schemas import VehicleResponse
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_repository, get_settings_dependency
from app.domain.authz import CAN_EDIT_VEHICLE_REGISTRATION
from app.domain.registration_write_service import RegistrationWriteService, WriteOutcome
from app.repositories.base import Repository

router = APIRouter(tags=["vehicle-registry"])

_require_editor = require_capability_dependency(
    CAN_EDIT_VEHICLE_REGISTRATION, "การแก้ไขทะเบียนรถ (registration change)"
)


def get_registration_write_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> RegistrationWriteService:
    return RegistrationWriteService(repository, settings.registry_context_effective, effective_test_batch_id(settings))


_body = parse_body
_openapi_body = openapi_body


def _respond(outcome: WriteOutcome) -> JSONResponse:
    if outcome.replayed:
        body: BaseModel = RegistrationReplayResponse(
            request_id=outcome.request_id,
            replayed=True,
            record_ids=outcome.record_ids,
            master_state=outcome.master_state,  # type: ignore[arg-type]
            consistency=outcome.consistency,  # type: ignore[arg-type]
        )
    elif not outcome.changed:
        body = RegistrationNoOpResponse(request_id=outcome.request_id, changed=False, warnings=outcome.warnings)
    else:
        assert outcome.change is not None
        vehicle = None
        if outcome.vehicle is not None and outcome.registry is not None:
            vehicle = VehicleWithRegistryResponse(
                **VehicleResponse.model_validate(outcome.vehicle.model_dump()).model_dump(),
                registry=VehicleRegistryResponse.of(outcome.registry),
            )
        body = RegistrationChangedResponse(
            request_id=outcome.request_id,
            changed=True,
            change=RegistrationChangeRecordResponse(
                change_id=outcome.change.change_id,
                recorded_at=outcome.change.recorded_at,
                request_id=outcome.change.request_id,
            ),
            master_write=outcome.master_write,  # type: ignore[arg-type]
            warnings=outcome.warnings,
            vehicle=vehicle,
        )
    content = body.model_dump(mode="json")
    if content.get("vehicle", "absent") is None:
        del content["vehicle"]
    return JSONResponse(content=content)


_COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"description": "HTTP_ERROR — the caller lacks 'can_edit_vehicle_registration'. Zero repository calls."},
    404: {"description": "VEHICLE_NOT_FOUND."},
    500: {
        "description": "VEHICLE_MASTER_SCHEMA_INVALID (incl. {problem: MISSING_HEADERS}) / VEHICLE_MASTER_DATA_INVALID / "
        "REGISTRATION_HISTORY_SCHEMA_INVALID / REGISTRATION_HISTORY_DATA_INVALID {issues} / "
        "PROVINCE_MASTER_SCHEMA_INVALID / PROVINCE_MASTER_DATA_INVALID. INTERNAL_ERROR proves nothing about writes."
    },
    503: {
        "description": "REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; *_READ_FAILED; REGISTRATION_HISTORY_WRITE_FAILED "
        "{history_write_outcome, master_write: NOT_ATTEMPTED, request_id}; VEHICLE_MASTER_WRITE_FAILED "
        "{history_recorded: true, change_id, master_write_outcome, request_id}."
    },
}


@router.patch(
    "/vehicles/{vehicle_id}/registration",
    response_model=None,
    responses={
        200: {"model": RegistrationChangedResponse, "description": "changed / no-op (changed:false) / replayed"},
        409: {
            "description": "REGISTRATION_PROJECTION_MISMATCH; VEHICLE_REGISTRY_STALE {current_matches_request}; "
            "REGISTRATION_DUPLICATE {conflict_count, conflict_vehicle_ids}; REQUEST_ID_REUSED; VEHICLE_ID_AMBIGUOUS."
        },
        422: {
            "description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; REGISTRATION_TEXT_INVALID; REGISTRATION_TEXT_REQUIRED; "
            "PROVINCE_NOT_FOUND; PROVINCE_INACTIVE."
        },
        **_COMMON_ERRORS,
    },
    openapi_extra=_openapi_body(RegistrationChangeRequest),
)
async def change_registration(
    vehicle_id: str,
    request: Request,
    context: RequestContext = Depends(_require_editor),
    request_id: str = Depends(require_client_request_id),
    service: RegistrationWriteService = Depends(get_registration_write_service),
) -> JSONResponse:
    _parsed, body = await _body(request, RegistrationChangeRequest)
    outcome = await service.change_registration(
        vehicle_id, body, request_id=request_id, user_id=context.user_id or ""
    )
    return _respond(outcome)


@router.post(
    "/vehicles/{vehicle_id}/registration-history/reconciliations",
    response_model=None,
    responses={
        200: {"model": RegistrationChangedResponse, "description": "changed / no-op (changed:false) / replayed"},
        409: {
            "description": "VEHICLE_REGISTRY_STALE; REGISTRATION_HISTORY_STALE; MASTER_PAIR_INVALID; "
            "REGISTRATION_DUPLICATE; REQUEST_ID_REUSED; VEHICLE_ID_AMBIGUOUS."
        },
        422: {
            "description": "REQUEST_ID_REQUIRED; VALIDATION_ERROR; RECONCILIATION_MODE_INVALID; REASON_REQUIRED; "
            "RELATED_REQUEST_NOT_FOUND; PROVINCE_NOT_FOUND; PROVINCE_INACTIVE."
        },
        **_COMMON_ERRORS,
    },
    openapi_extra=_openapi_body(RegistrationReconciliationRequest),
)
async def reconcile_registration(
    vehicle_id: str,
    request: Request,
    context: RequestContext = Depends(_require_editor),
    request_id: str = Depends(require_client_request_id),
    service: RegistrationWriteService = Depends(get_registration_write_service),
) -> JSONResponse:
    _parsed, body = await _body(request, RegistrationReconciliationRequest)
    outcome = await service.reconcile_registration(
        vehicle_id, body, request_id=request_id, user_id=context.user_id or ""
    )
    return _respond(outcome)
