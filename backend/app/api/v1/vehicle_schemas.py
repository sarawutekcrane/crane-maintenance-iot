from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

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
    machine_no: str = Field(min_length=1, max_length=100)


class ChangeVehicleStatusRequest(BaseModel):
    status: OperationalStatus
    note: str | None = Field(default=None, max_length=500)


class ChangeVehicleStatusResponse(BaseModel):
    vehicle: VehicleResponse
    history_entry: VehicleStatusHistoryResponse
