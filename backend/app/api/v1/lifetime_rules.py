"""Lifetime-rule routes (Phase 5). Structural only — G01/G02 remain
SOURCE-DATA-REQUIRED; no due/remaining calculation exists here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.lifetime_rule_schemas import CreateLifetimeRuleRequest, LifetimeRuleResponse
from app.dependencies import get_lifetime_rule_service
from app.domain.lifetime_rule import LifetimeRule
from app.domain.lifetime_rule_service import LifetimeRuleService

router = APIRouter(tags=["lifetime-rules"])


def _response(rule: LifetimeRule) -> LifetimeRuleResponse:
    return LifetimeRuleResponse.model_validate(rule.model_dump())


@router.post("/lifetime-rules", response_model=LifetimeRuleResponse)
async def create_lifetime_rule(
    body: CreateLifetimeRuleRequest,
    service: LifetimeRuleService = Depends(get_lifetime_rule_service),
) -> LifetimeRuleResponse:
    rule = await service.create(
        part_id=body.part_id,
        scope=body.scope,
        model_id=body.model_id,
        vehicle_id=body.vehicle_id,
        trigger_type=body.trigger_type,
        component_role=body.component_role,
        first_due_value=body.first_due_value,
        interval_value=body.interval_value,
        warning_window_value=body.warning_window_value,
        note=body.note,
    )
    return _response(rule)


@router.get("/lifetime-rules/{lifetime_rule_id}", response_model=LifetimeRuleResponse)
async def get_lifetime_rule(
    lifetime_rule_id: str, service: LifetimeRuleService = Depends(get_lifetime_rule_service)
) -> LifetimeRuleResponse:
    rule = await service.get(lifetime_rule_id)
    return _response(rule)


@router.get("/lifetime-rules", response_model=list[LifetimeRuleResponse])
async def list_lifetime_rules(
    part_id: str = Query(...),
    service: LifetimeRuleService = Depends(get_lifetime_rule_service),
) -> list[LifetimeRuleResponse]:
    rules = await service.list_for_part(part_id)
    return [_response(r) for r in rules]
