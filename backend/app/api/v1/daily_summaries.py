"""Daily Summary routes (Web/API Phase 6 Batch 4C — Daily Summary
Reconciliation). Read-only: Daily Summary is entirely backend-derived
from `vehicle_event` (see `app.domain.daily_summary_service.
DailySummaryService`) — no POST/PATCH/DELETE endpoint exists or should
ever be added; a client can never write `daily_summary` directly.

Same open-to-any-authenticated-actor precedent as
`app.api.v1.vehicle_events`/`app.api.v1.model_documents` (see those
modules' docstrings): final RBAC remains Phase 10."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.daily_summary_schemas import DailySummaryResponse
from app.dependencies import get_daily_summary_service
from app.domain.daily_summary import DailySummary
from app.domain.daily_summary_service import DailySummaryService

router = APIRouter(tags=["daily-summaries"])


def _summary_response(summary: DailySummary) -> DailySummaryResponse:
    return DailySummaryResponse.model_validate(summary.model_dump())


@router.get(
    "/vehicles/{vehicle_id}/daily-summaries",
    response_model=list[DailySummaryResponse],
)
async def list_vehicle_daily_summaries(
    vehicle_id: str,
    service: DailySummaryService = Depends(get_daily_summary_service),
) -> list[DailySummaryResponse]:
    summaries = await service.list_for_vehicle(vehicle_id)
    return [_summary_response(s) for s in summaries]
