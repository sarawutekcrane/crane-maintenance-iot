from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.lifetime_rule import LifetimeRuleScope, LifetimeTriggerType
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
