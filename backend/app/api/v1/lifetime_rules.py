"""Lifetime-rule routes (Phase 5; R6). G01/G02 remain SOURCE-DATA-REQUIRED:
no real threshold exists; due evaluation lives in
`app.domain.part_lifetime_status_service` (read-only status routes).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.lifetime_rule_schemas import CreateLifetimeRuleRequest, LifetimeRuleResponse
from app.api.v1.repairs import optional_client_request_id
from app.context import RequestContext
from app.dependencies import get_current_context, get_lifetime_rule_service
from app.domain.lifetime_rule import LifetimeRule
from app.domain.lifetime_rule_service import LifetimeRuleService
from app.domain.part_instance_service import apply_replay_header

router = APIRouter(tags=["lifetime-rules"])


def _response(rule: LifetimeRule) -> LifetimeRuleResponse:
    data = rule.model_dump(mode="json")
    return LifetimeRuleResponse.model_validate(data)


@router.post("/lifetime-rules", response_model=LifetimeRuleResponse)
async def create_lifetime_rule(
    response: Response,
    body: CreateLifetimeRuleRequest,
    service: LifetimeRuleService = Depends(get_lifetime_rule_service),
    context: RequestContext = Depends(get_current_context),
    request_id: str | None = Depends(optional_client_request_id),
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
        due_action=body.due_action,
        interval_unit=body.interval_unit,
        condition_group_key=body.condition_group_key,
        combination=body.combination,
        actor=context.user_id,
        request_id=request_id,
        body=body.model_dump(mode="json", exclude_unset=True),
    )
    apply_replay_header(response, rule)
    return _response(rule)


@router.get("/lifetime-rules/{lifetime_rule_id}", response_model=LifetimeRuleResponse)
async def get_lifetime_rule(
    lifetime_rule_id: str, service: LifetimeRuleService = Depends(get_lifetime_rule_service)
) -> LifetimeRuleResponse:
    rule = await service.get(lifetime_rule_id)
    return _response(rule)


@router.get("/lifetime-rules", response_model=list[LifetimeRuleResponse])
async def list_lifetime_rules(
    part_id: str = Query(...), service: LifetimeRuleService = Depends(get_lifetime_rule_service)
) -> list[LifetimeRuleResponse]:
    rules = await service.list_for_part(part_id)
    return [_response(r) for r in rules]
