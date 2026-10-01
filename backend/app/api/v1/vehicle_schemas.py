from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from app.domain.common import OperationalStatus
from app.domain.vehicle_model import ComponentRole


class VehicleModelResponse(BaseModel):
    model_id: str
    model_code: str
    model_name: str
    brand: str | None
    description: str | None
    component_roles: list[ComponentRole]
    created_at: datetime
    updated_at: datetime
    assigned_pm_plan_id: str | None = None


class VehicleResponse(BaseModel):
    vehicle_id: str
    machine_no: str
    model_id: str
    serial_number: str | None
    operational_status: OperationalStatus
    created_at: datetime
    updated_at: datetime


class VehicleComponentResponse(BaseModel):
    component_id: str
    vehicle_id: str
    component_role: ComponentRole
    label: str


class VehicleStatusHistoryResponse(BaseModel):
    history_id: str
    vehicle_id: str
    status: OperationalStatus
    changed_at: datetime
    changed_by: str | None
    note: str | None


class VehicleDetailResponse(BaseModel):
    vehicle: VehicleResponse
    model: VehicleModelResponse | None
    components: list[VehicleComponentResponse]


class UpdateMachineNoRequest(BaseModel):
    """`machine_no` is opaque text: it is stored and returned exactly as
    sent (leading zeros, inner/edge spaces, apostrophes and formula-like
    text included) and is never trimmed or normalized. Phase 7 Batch 7H2
    (DEC-H8b): a value consisting only of whitespace is rejected with 422
    before any repository read. The validator raises PydanticCustomError,
    not a plain ValueError, so the 422 envelope stays JSON-serialisable
    (see app/api/v1/vehicle_event_schemas.py for that shared-handler gap)."""

    machine_no: str = Field(min_length=1, max_length=100)

    @field_validator("machine_no")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError(
                "whitespace_only", "machine_no must not consist only of whitespace"
            )
        return value


class ChangeVehicleStatusRequest(BaseModel):
    status: OperationalStatus
    note: str | None = Field(default=None, max_length=500)


class ChangeVehicleStatusResponse(BaseModel):
    vehicle: VehicleResponse
    history_entry: VehicleStatusHistoryResponse
