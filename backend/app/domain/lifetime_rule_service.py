"""Lifetime-rule domain service (Phase 5). Structural only — see
`app.domain.lifetime_rule` module docstring: G01/G02 remain
SOURCE-DATA-REQUIRED, so no due/remaining calculation is performed here
and no numeric field is ever populated by seed data.
"""
from __future__ import annotations

from fastapi import status

from app.domain.lifetime_rule import LifetimeRule, LifetimeRuleScope, LifetimeTriggerType
from app.domain.part_lookup import require_part_exists
from app.domain.vehicle_model import ComponentRole
from app.errors import ApiError
from app.repositories.base import Repository


class LifetimeRuleService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

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
    ) -> LifetimeRule:
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

        if trigger_type in (LifetimeTriggerType.ENGINE_HOUR, LifetimeTriggerType.PTO_HOUR):
            if component_role is None:
                raise ApiError(
                    code="VALIDATION_ERROR",
                    message=(
                        f"component_role is required when trigger_type='{trigger_type.value}' — "
                        "a lifetime rule must never guess which counter drives it"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

        return await self._repository.create_lifetime_rule(
            part_id=part_id,
            scope=scope,
            model_id=model_id,
            vehicle_id=vehicle_id,
            trigger_type=trigger_type,
            component_role=component_role,
            first_due_value=first_due_value,
            interval_value=interval_value,
            warning_window_value=warning_window_value,
            note=note,
        )

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
