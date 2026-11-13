"""Alert routes (Web/API Phase 6 Batch 5A — Alert Read Foundation).
READ-ONLY: no POST/PATCH/PUT/DELETE endpoint exists here or anywhere in
this batch — Alert is entirely backend-derived by a later generation
batch and mutated by a later lifecycle batch, neither of which exists
yet (see `app.domain.alert` module docstring for the unresolved A07 /
RBAC blockers).

R7-B read authorization (replaces the former open-to-any-actor precedent for
these two routes only): both need a trusted actor (a non-blank server-side
`user_id`) holding `can_view` — the same gate as the R4 PM Due reads and the
certificate expiry report — checked BEFORE any repository read, so an
unauthorized or unverified caller receives no alert row, no vehicle-existence
signal and no source fields from an alert id. No per-vehicle/department data
scope is decided here (M02 stays an Owner gate): every `can_view` holder reads
every vehicle's alerts, exactly as before for the authorized actor. Alert rows
carry no TEST/REAL scope cells, so no data-context isolation is claimed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.alert_schemas import AlertResponse
from app.context import RequestContext
from app.dependencies import get_alert_service, get_current_context
from app.domain.alert import Alert
from app.domain.alert_service import AlertService
from app.domain.authz import CAN_VIEW, require_capability

router = APIRouter(tags=["alerts"])


def _alert_response(alert: Alert) -> AlertResponse:
    return AlertResponse.model_validate(alert.model_dump())


_READ_ACTION_TH = "การดูการแจ้งเตือน (read alerts)"


def _require_alert_reader(context: RequestContext) -> None:
    """R7-B: trusted actor + `can_view`, before any repository read (403 HTTP_ERROR)."""
    if not (context.user_id or "").strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{_READ_ACTION_TH} requires a trusted, authenticated actor",
        )
    require_capability(context, CAN_VIEW, _READ_ACTION_TH)


@router.get("/vehicles/{vehicle_id}/alerts", response_model=list[AlertResponse])
async def list_vehicle_alerts(
    vehicle_id: str,
    service: AlertService = Depends(get_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> list[AlertResponse]:
    _require_alert_reader(context)
    alerts = await service.list_for_vehicle(vehicle_id)
    return [_alert_response(a) for a in alerts]


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    service: AlertService = Depends(get_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> AlertResponse:
    _require_alert_reader(context)
    alert = await service.get_alert(alert_id)
    return _alert_response(alert)
