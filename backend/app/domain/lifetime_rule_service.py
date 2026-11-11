"""Lifetime-rule domain service (Phase 5; R6 FINAL §7.4).

G01/G02 remain SOURCE-DATA-REQUIRED: no numeric field is ever populated by
seed data, and any number created through the API is test-only development
data, never a real OEM/company interval.

R6 validation at creation:
- PTO_HOUR is refused for part lifetime rules (Owner Agreements §M / AP-18:
  PTO_HOUR has no approved use beyond being retained);
- CYCLE stays creatable for compatibility but always evaluates UNKNOWN;
- `interval_unit`, when given, must suit the trigger (HOUR / KM / MONTH|DAY);
- a condition group declares its combination per rule; EARLIEST is the only
  implemented combination (any other: 422 COMBINATION_UNSUPPORTED) and every
  member must match part, scope, model / vehicle, due action and combination.
"""
from __future__ import annotations

from fastapi import status

from app.domain.common import utc_now
from app.domain.lifetime_rule import (
    DueAction,
    IntervalUnit,
    LifetimeRule,
    LifetimeRuleScope,
    LifetimeTriggerType,
    RuleCombination,
)
from app.domain.part_instance_service import (
    commit,
    fingerprint,
    invalid,
    replayed_response,
    request_key,
    to_model,
)
from app.domain.part_lookup import require_part_exists
from app.domain.vehicle_model import ComponentRole
from app.errors import ApiError
from app.repositories.base import PART_RULES, PartMutation, Repository

_UNITS = {
    LifetimeTriggerType.ENGINE_HOUR: {IntervalUnit.HOUR},
    LifetimeTriggerType.ODOMETER: {IntervalUnit.KM},
    LifetimeTriggerType.CALENDAR: {IntervalUnit.MONTH, IntervalUnit.DAY},
}
OP_RULE_CREATE = "RULE_CREATE"


class LifetimeRuleService:
    def __init__(self, repository: Repository, data_context: str | None = None) -> None:
        self._repository = repository
        self._data_context = data_context

    async def create(
        self,
        part_id: str,
        scope: LifetimeRuleScope,
        model_id: str | None,
        vehicle_id: str | None,
        trigger_type: LifetimeTriggerType,
        component_role: ComponentRole | None,
        first_due_value: float | None,
        interval_value: float | None,
        warning_window_value: float | None,
        note: str | None,
        *,
        due_action: DueAction | None = None,
        interval_unit: IntervalUnit | None = None,
        condition_group_key: str | None = None,
        combination: str | None = None,
        actor: str | None = None,
        request_id: str | None = None,
        body: dict | None = None,
    ) -> LifetimeRule:
        key = request_key(self._data_context, "RULE", "NEW:RULE", request_id)
        digest = fingerprint(OP_RULE_CREATE, "NEW:RULE", actor, body or {})
        if key is not None:
            state = await self._repository.read_part_state()
            replay = replayed_response(state, key, OP_RULE_CREATE, digest)
            if replay is not None:
                return to_model(LifetimeRule, replay)
        await require_part_exists(self._repository, part_id)

        if scope == LifetimeRuleScope.MODEL:
            if not model_id:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message="model_id is required when scope='MODEL'",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            model = await self._repository.get_vehicle_model(model_id)
            if model is None:
                raise ApiError(
                    code="MODEL_NOT_FOUND",
                    message=f"Vehicle model '{model_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        else:
            if not vehicle_id:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message="vehicle_id is required when scope='VEHICLE'",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            vehicle = await self._repository.get_vehicle(vehicle_id)
            if vehicle is None:
                raise ApiError(
                    code="VEHICLE_NOT_FOUND",
                    message=f"Vehicle '{vehicle_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        if trigger_type == LifetimeTriggerType.PTO_HOUR:
            raise invalid("PTO_NOT_APPROVED_FOR_PART_LIFETIME",
                          "PTO_HOUR has no approved use for part lifetime rules (Owner Agreements §M)")
        if trigger_type == LifetimeTriggerType.ENGINE_HOUR:
            if component_role is None:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message=(
                        f"component_role is required when trigger_type='{trigger_type.value}' — "
                        "a lifetime rule must never guess which counter drives it"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            if component_role not in (ComponentRole.CARRIER_ENGINE, ComponentRole.CRANE_ENGINE):
                raise invalid("VALIDATION_ERROR", "ENGINE_HOUR must name a physical engine role "
                              "(CARRIER_ENGINE or CRANE_ENGINE)")
        if interval_unit is not None and interval_unit not in _UNITS.get(trigger_type, set()):
            raise invalid("UNIT_MISMATCH", f"interval_unit '{interval_unit.value}' does not suit '{trigger_type.value}'")
        group = (condition_group_key or "").strip() or None
        if (group is None) != (combination is None):
            raise invalid("VALIDATION_ERROR", "condition_group_key and combination are declared together")
        parsed_combination = None
        if combination is not None:
            if combination != RuleCombination.EARLIEST.value:
                raise invalid("COMBINATION_UNSUPPORTED",
                              f"Combination '{combination}' is not supported (only EARLIEST is implemented)")
            parsed_combination = RuleCombination.EARLIEST
            for other in (await self._repository.read_part_state()).rules.values():
                if other.condition_group_key == group and (
                        other.part_id, other.scope, other.model_id, other.vehicle_id, other.due_action,
                        other.combination) != (part_id, scope, model_id, vehicle_id, due_action, parsed_combination):
                    raise invalid("CONDITION_GROUP_INCOMPATIBLE",
                                  "Every rule in a condition group must match part, scope, model / vehicle, "
                                  "due action and combination")

        (rule_id,) = await self._repository.allocate_part_ids("LTR")
        rule = LifetimeRule(lifetime_rule_id=rule_id, part_id=part_id, scope=scope, model_id=model_id,
                            vehicle_id=vehicle_id, trigger_type=trigger_type, component_role=component_role,
                            first_due_value=first_due_value, interval_value=interval_value,
                            warning_window_value=warning_window_value, note=note, created_at=utc_now(),
                            due_action=due_action, interval_unit=interval_unit, condition_group_key=group,
                            combination=parsed_combination)
        response = await commit(self._repository, PartMutation(
            puts={PART_RULES: {rule_id: rule}}, request_key=key, operation=OP_RULE_CREATE, fingerprint=digest,
            response=lambda s: s.rules[rule_id].model_dump(mode="json")))
        return to_model(LifetimeRule, response)

    async def get(self, lifetime_rule_id: str) -> LifetimeRule:
        rule = await self._repository.get_lifetime_rule(lifetime_rule_id)
        if rule is None:
            raise ApiError(
                code="LIFETIME_RULE_NOT_FOUND",
                message=f"Lifetime rule '{lifetime_rule_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return rule

    async def list_for_part(self, part_id: str) -> list[LifetimeRule]:
        await require_part_exists(self._repository, part_id)
        return await self._repository.list_lifetime_rules_for_part(part_id)
