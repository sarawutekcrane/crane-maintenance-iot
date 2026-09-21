"""Alert routes (Web/API Phase 6 Batch 5A — Alert Read Foundation).
READ-ONLY: no POST/PATCH/PUT/DELETE endpoint exists here or anywhere in
this batch — Alert is entirely backend-derived by a later generation
batch and mutated by a later lifecycle batch, neither of which exists
yet (see `app.domain.alert` module docstring for the unresolved A07 /
RBAC blockers).

Same open-to-any-authenticated-actor precedent as
`app.api.v1.vehicle_events`/`app.api.v1.daily_summaries` (see those
modules' docstrings): final RBAC remains Phase 10."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.alert_schemas import AlertResponse
from app.dependencies import get_alert_service
from app.domain.alert import Alert
from app.domain.alert_service import AlertService

router = APIRouter(tags=["alerts"])


def _alert_response(alert: Alert) -> AlertResponse:
    return AlertResponse.model_validate(alert.model_dump())


@router.get("/vehicles/{vehicle_id}/alerts", response_model=list[AlertResponse])
async def list_vehicle_alerts(
    vehicle_id: str,
    service: AlertService = Depends(get_alert_service),
) -> list[AlertResponse]:
    alerts = await service.list_for_vehicle(vehicle_id)
    return [_alert_response(a) for a in alerts]


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    service: AlertService = Depends(get_alert_service),
) -> AlertResponse:
    alert = await service.get_alert(alert_id)
    return _alert_response(alert)
