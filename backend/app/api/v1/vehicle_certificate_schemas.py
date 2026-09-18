"""Vehicle Certificate request/response schemas (Web/API Phase 6 Batch 2A —
create/list/get only). See `app.domain.vehicle_certificate` for the
verified live-sheet field shapes and the NO-GUESSING RULE governing
`certificate_type_code`/`certificate_type_name_th` (plain optional
strings, never an Enum/fixed vocabulary) versus `certificate_status`
(the one approved 3-value vocabulary).

The client can never supply `certificate_id`, `vehicle_id` (it is a path
parameter, not a body field), `replaced_by_certificate_id`,
`created_by_user_id`, or `created_at` — all five are backend-controlled
(see `app.domain.vehicle_certificate_service.VehicleCertificateService`
and the routes in `app.api.v1.vehicle_certificates`)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.vehicle_certificate import CertificateStatus


class CreateVehicleCertificateRequest(BaseModel):
    # API-CONTRACT CORRECTION: the module docstring above already states
    # the client can never supply certificate_id/vehicle_id/
    # replaced_by_certificate_id/created_by_user_id/created_at — this
    # `extra="forbid"` is what actually enforces that at the request
    # boundary (a 422 for any of those, or any other unknown field)
    # instead of relying on pydantic's default silently-ignore-extras
    # behavior, which only happened to look correct because none of
    # those fields exist on this model.
    model_config = ConfigDict(extra="forbid")

    certificate_type_code: str | None = Field(default=None, max_length=100)
    certificate_type_name_th: str | None = Field(default=None, max_length=200)
    document_no: str | None = Field(default=None, max_length=100)
    issue_date: date | None = None
    expiry_date: date | None = None
    alert_lead_days: int | None = None
    certificate_status: CertificateStatus | None = None
    storage_ref: str | None = Field(default=None, max_length=500)
    note_th: str | None = Field(default=None, max_length=500)


class VehicleCertificateResponse(BaseModel):
    certificate_id: str
    vehicle_id: str
    certificate_type_code: str | None
    certificate_type_name_th: str | None
    document_no: str | None
    issue_date: date | None
    expiry_date: date | None
    alert_lead_days: int | None
    certificate_status: CertificateStatus | None
    replaced_by_certificate_id: str | None
    storage_ref: str | None
    created_by_user_id: str | None
    created_at: datetime
    note_th: str | None
