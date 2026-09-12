"""Vehicle model (machine type) master data.

Separate from physical vehicle identity (see `app.domain.vehicle`) per
baseline section 4: "Separate model identity from physical vehicle
identity."
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ComponentRole(str, Enum):
    """Component roles a model may expose (baseline section 4/16).

    "including" in the baseline means this list is not exhaustive; add new
    roles here as future models require them, without changing the API
    shape that carries `ComponentRole` values.
    """

    ENGINE_MAIN = "ENGINE_MAIN"
    ENGINE_SECONDARY = "ENGINE_SECONDARY"
    PTO = "PTO"
    VEHICLE = "VEHICLE"


class VehicleModel(BaseModel):
    model_id: str
    model_code: str
    model_name: str
    brand: str | None = None
    description: str | None = None
    component_roles: list[ComponentRole] = []
    created_at: datetime
    updated_at: datetime
