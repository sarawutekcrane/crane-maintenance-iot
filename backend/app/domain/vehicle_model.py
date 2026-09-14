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

    CARRIER_ENGINE and CRANE_ENGINE are physical/functional roles (carrier
    / lower-chassis / travelling side vs. crane / superstructure side), not
    first/second engine numbering. A vehicle is not required to have both.
    See OPEN_DECISIONS_REGISTER_EN.txt and
    docs/phase-results/component-role-naming-correction.md.

    `ENGINE_MAIN` / `ENGINE_SECONDARY` are deprecated legacy names and are
    no longer valid authoritative values.
    """

    CARRIER_ENGINE = "CARRIER_ENGINE"
    CRANE_ENGINE = "CRANE_ENGINE"
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
    assigned_pm_plan_id: str | None = None
    """Core Demo Fixes, PM WORKFLOW REDESIGN section A — APPROVED
    CORRECTION: "Each crane model is assigned to exactly one authoritative
    PM plan... one vehicle can operate under only one PM plan at a time."
    `None` means SOURCE-DATA-REQUIRED: no authoritative model->plan
    mapping exists for this model yet — `PmService` must not infer one and
    must return no applicable PM plan for such a model rather than
    guessing. When set, `PmService.open_work_order` rejects any
    `pm_plan_id` other than this exact value for a vehicle of this model
    (a user may never manually switch a vehicle's PM work to another
    plan)."""
