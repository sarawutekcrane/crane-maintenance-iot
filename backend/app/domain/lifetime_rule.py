"""Lifetime-rule abstraction (baseline §11 scope item 6/7;
OPEN_DECISIONS_REGISTER_EN.txt G01, G02).

TRIGGER TYPES: structural support for ENGINE_HOUR / PTO_HOUR / ODOMETER /
CYCLE / CALENDAR, per the Phase 5 prompt. A rule must explicitly name its
own trigger/source relationship — `component_role`, when the trigger is a
component-scoped counter (ENGINE_HOUR/PTO_HOUR), states exactly which
component role the rule reads from (`CARRIER_ENGINE`/`CRANE_ENGINE`/`PTO`)
so a rule never silently "guesses" which counter drives it (guardrails
§10: "Do not assume every part uses the Carrier Engine hour... Do not
guess which counter drives a real component").

SOURCE DATA RULE (G01 — "Real Lifetime Rules: SOURCE-DATA-REQUIRED"; G02 —
"Lifetime Warning Windows: SOURCE-DATA-REQUIRED/TBD"): `first_due_value`,
`interval_value`, and `warning_window_value` all default to `None` and are
never populated by seed data with a real number — see
`app.repositories.mock.seed_data` (no `LifetimeRule` is seeded at all).
Any non-`None` value created through the API in this repository is
test-only development data, never a real OEM/company interval; creating
these fields structurally does NOT mark G01/G02 resolved.

MODEL RULE / VEHICLE OVERRIDE (baseline "MODEL RULES AND VEHICLE
OVERRIDES"): `scope=MODEL` + `model_id` is a model-level rule; `scope=
VEHICLE` + `vehicle_id` is a future vehicle-specific override. Both shapes
exist so a later override does not require rewriting historical usage;
this module does not implement override-precedence resolution (no due
calculation exists at all while G01/G02 remain unresolved).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.domain.vehicle_model import ComponentRole


class LifetimeTriggerType(str, Enum):
    ENGINE_HOUR = "ENGINE_HOUR"
    PTO_HOUR = "PTO_HOUR"
    ODOMETER = "ODOMETER"
    CYCLE = "CYCLE"
    CALENDAR = "CALENDAR"


class LifetimeRuleScope(str, Enum):
    MODEL = "MODEL"
    VEHICLE = "VEHICLE"


class LifetimeRule(BaseModel):
    lifetime_rule_id: str
    part_id: str
    scope: LifetimeRuleScope
    model_id: str | None = None
    vehicle_id: str | None = None
    trigger_type: LifetimeTriggerType
    component_role: ComponentRole | None = None
    first_due_value: float | None = None
    interval_value: float | None = None
    warning_window_value: float | None = None
    note: str | None = None
    created_at: datetime


__all__ = ["LifetimeTriggerType", "LifetimeRuleScope", "LifetimeRule"]
