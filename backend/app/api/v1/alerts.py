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
carry no TEST/REAL scope cells, so no data-context isolation is claimed.

R7 Whole-Phase (Owner gate 2026-11-17, policy R1 §5): adds the central list and
the per-vehicle provenance (same `can_view` gate, GET only, no write), and three
TEST-only POSTs — the explicit evaluation, acknowledge and mute — each needing the
client's `X-Request-Id`, the named TEST grant plus `can_view`, Mock + TEST and a
TEST-scoped vehicle. There is no resolve route: resolution is source-driven only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.alert_schemas import (
    AcknowledgeAlertRequest,
    AlertActionResponse,
    AlertEvaluationRequest,
    AlertEvaluationResponse,
    AlertPageResponse,
    AlertProvenanceResponse,
    AlertResponse,
    MuteAlertRequest,
)
from app.api.v1.request_id_dependency import require_client_request_id
from app.context import RequestContext
from app.dependencies import get_alert_service, get_current_context, get_r7_alert_service
from app.domain.alert import Alert
from app.domain.alert_service import ACTION_ACKNOWLEDGE, ACTION_MUTE, AlertService, R7AlertService, mute_expired
from app.domain.authz import CAN_VIEW, require_capability

router = APIRouter(tags=["alerts"])


def _alert_response(alert: Alert, source_link: str | None = None) -> AlertResponse:
    return AlertResponse.model_validate({**alert.model_dump(), "source_link": source_link,
                                         "mute_expired": mute_expired(alert)})


_READ_ACTION_TH = "การดูการแจ้งเตือน (read alerts)"


def _require_alert_reader(context: RequestContext) -> None:
    """R7-B: trusted actor + `can_view`, before any repository read (403 HTTP_ERROR)."""
    if not (context.user_id or "").strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{_READ_ACTION_TH} requires a trusted, authenticated actor",
        )
    require_capability(context, CAN_VIEW, _READ_ACTION_TH)


@router.get("/alerts", response_model=AlertPageResponse)
async def list_alerts(
    alert_status: str | None = Query(default=None, alias="status", max_length=20),
    alert_type: str | None = Query(default=None, max_length=50),
    vehicle_id: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    service: R7AlertService = Depends(get_r7_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> AlertPageResponse:
    """R7 P-10: the central read (GET only; writes nothing)."""
    _require_alert_reader(context)
    alerts, total = await service.list_alerts(status_filter=alert_status, alert_type=alert_type,
                                              vehicle_id=vehicle_id, page=page, page_size=page_size)
    items = [_alert_response(a, await service.source_link(a)) for a in alerts]
    return AlertPageResponse(items=items, page=page, page_size=page_size, total_items=total)


@router.get("/vehicles/{vehicle_id}/alerts", response_model=list[AlertResponse])
async def list_vehicle_alerts(
    vehicle_id: str,
    service: AlertService = Depends(get_alert_service),
    r7: R7AlertService = Depends(get_r7_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> list[AlertResponse]:
    _require_alert_reader(context)
    alerts = await service.list_for_vehicle(vehicle_id)
    return [_alert_response(a, await r7.source_link(a)) for a in alerts]


@router.get("/vehicles/{vehicle_id}/alert-provenance", response_model=AlertProvenanceResponse)
async def get_vehicle_alert_provenance(
    vehicle_id: str,
    service: AlertService = Depends(get_alert_service),
    r7: R7AlertService = Depends(get_r7_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> AlertProvenanceResponse:
    """R7 P-10: not configured / not evaluated / evaluated-none / alerts, from server
    records only. GET only; writes nothing."""
    _require_alert_reader(context)
    await service.list_for_vehicle(vehicle_id)  # the existing vehicle-existence check (404)
    return AlertProvenanceResponse(vehicle_id=vehicle_id, types=await r7.provenance(vehicle_id))


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    service: AlertService = Depends(get_alert_service),
    r7: R7AlertService = Depends(get_r7_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> AlertResponse:
    _require_alert_reader(context)
    alert = await service.get_alert(alert_id)
    return _alert_response(alert, await r7.source_link(alert))


@router.post("/alerts/test-evaluations", response_model=AlertEvaluationResponse)
async def run_test_alert_evaluation(
    body: AlertEvaluationRequest,
    request_id: str = Depends(require_client_request_id),
    r7: R7AlertService = Depends(get_r7_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> AlertEvaluationResponse:
    """R7 P-7: the explicit, user-triggered TEST evaluation (never scheduled)."""
    return AlertEvaluationResponse.model_validate(await r7.evaluate(context, body.vehicle_id, request_id))


async def _action_response(r7: R7AlertService, result: dict) -> AlertActionResponse:
    alert = result["alert"]
    return AlertActionResponse(alert=_alert_response(alert, await r7.source_link(alert)),
                               replayed=result["replayed"], recovered=result["recovered"], outcome=result["outcome"])


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertActionResponse)
async def acknowledge_test_alert(
    alert_id: str,
    body: AcknowledgeAlertRequest,
    request_id: str = Depends(require_client_request_id),
    r7: R7AlertService = Depends(get_r7_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> AlertActionResponse:
    result = await r7.act(context, alert_id, ACTION_ACKNOWLEDGE, request_id, reason=body.reason_th)
    return await _action_response(r7, result)


@router.post("/alerts/{alert_id}/mute", response_model=AlertActionResponse)
async def mute_test_alert(
    alert_id: str,
    body: MuteAlertRequest,
    request_id: str = Depends(require_client_request_id),
    r7: R7AlertService = Depends(get_r7_alert_service),
    context: RequestContext = Depends(get_current_context),
) -> AlertActionResponse:
    result = await r7.act(context, alert_id, ACTION_MUTE, request_id, reason=body.reason_th,
                          muted_until=body.muted_until)
    return await _action_response(r7, result)
