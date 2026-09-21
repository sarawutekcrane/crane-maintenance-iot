"""Alert response schema (Web/API Phase 6 Batch 5A — Alert Read
Foundation, read-only). No create/update/delete request schema exists
here, and none should be added in this batch — Alert lifecycle mutations
(acknowledge/mute/resolve/reopen) require the still-unresolved A07 and
an explicit alert-write RBAC decision, neither of which this batch
makes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AlertResponse(BaseModel):
    alert_id: str
    vehicle_id: str
    alert_type: str | None
    source_type: str | None
    source_id: str | None
    severity: str | None
    created_at: datetime
    alert_status: str | None
    muted_until: datetime | None
    acknowledged_by_user_id: str | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    message_th: str | None
