"""Daily Summary response schema (Web/API Phase 6 Batch 4C — read-only).
Daily Summary is backend-derived only (see
`app.domain.daily_summary_service.DailySummaryService.
reconcile_vehicle_component`) — no create/update/delete request schema
exists here, and none should ever be added; a client can never write
`daily_summary` directly."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class DailySummaryResponse(BaseModel):
    daily_summary_id: str
    summary_date: date
    vehicle_id: str
    component_id: str
    metric_type: str
    value: float | None
    unit: str
    data_status: str
    created_at: datetime
