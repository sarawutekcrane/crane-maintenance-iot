from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.lifetime_rule import DueAction, IntervalUnit, LifetimeRuleScope, LifetimeTriggerType
from app.domain.vehicle_model import ComponentRole


class CreateLifetimeRuleRequest(BaseModel):
    part_id: str = Field(min_length=1)
    scope: LifetimeRuleScope
    model_id: str | None = None
    vehicle_id: str | None = None
    trigger_type: LifetimeTriggerType
    component_role: ComponentRole | None = None
    first_due_value: float | None = None
    interval_value: float | None = None
    warning_window_value: float | None = None
    note: str | None = Field(default=None, max_length=500)
    due_action: DueAction | None = None
    interval_unit: IntervalUnit | None = None
    condition_group_key: str | None = Field(default=None, max_length=100)
    # A free string so an unsupported combination is answered 422
    # COMBINATION_UNSUPPORTED by the service (C4), not a generic enum error.
    combination: str | None = Field(default=None, max_length=50)


class LifetimeRuleResponse(BaseModel):
    lifetime_rule_id: str
    part_id: str
    scope: LifetimeRuleScope
    model_id: str | None
    vehicle_id: str | None
    trigger_type: LifetimeTriggerType
    component_role: ComponentRole | None
    first_due_value: float | None
    interval_value: float | None
    warning_window_value: float | None
    note: str | None
    created_at: datetime
    due_action: DueAction | None = None
    interval_unit: IntervalUnit | None = None
    condition_group_key: str | None = None
    combination: str | None = None
