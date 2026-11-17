"""Alert response schema (Web/API Phase 6 Batch 5A — Alert Read
Foundation). R7 Whole-Phase (Owner gate 2026-11-17, policy R1 §5) adds,
additively: a server-verified `source_link` and a derived `mute_expired`
flag on every alert response, the central page, the per-vehicle
provenance, the TEST evaluation result and the TEST ACK / MUTE request
and result schemas. Existing response fields are unchanged."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    # R7 (P-10 / P-9c): server-verified link to an existing route (null when the source
    # cannot be verified) and a derived read-only flag (no write on GET).
    source_link: str | None = None
    mute_expired: bool = False


class AlertPageResponse(BaseModel):
    items: list[AlertResponse]
    page: int
    page_size: int
    total_items: int


class AlertProvenanceResponse(BaseModel):
    vehicle_id: str
    # alert_type -> NOT_CONFIGURED | SETTING_CONFLICT | NOT_EVALUATED | EVALUATED_NONE | ALERTS |
    # SOURCE_INCOMPLETE | ALERTS_SOURCE_INCOMPLETE | UNAVAILABLE
    types: dict[str, str]
    responsibilities: str = "UNAVAILABLE"  # P-11: no approved recipient mapping exists


class AlertEvaluationRequest(BaseModel):
    vehicle_id: str | None = Field(default=None, min_length=1, max_length=100)


class AlertEvaluationOutcome(BaseModel):
    vehicle_id: str
    alert_type: str
    setting: str
    source: str | None
    source_reason: str | None
    created: int
    reused: int
    resolved: int
    unknown: int
    conflicts: int
    collisions: int
    # D3: certificates whose successor could not be verified — their alert is NOT resolved.
    not_resolved: list[dict[str, str]] = Field(default_factory=list)
    # IR-C7: APPLIED | NOT_APPLICABLE | WITHHELD:<SOURCE_INCOMPLETE | UNKNOWN_OBSERVATION |
    # IDENTITY_CONFLICT | ID_COLLISION | CERTIFICATE_ABSENCE_IS_NOT_PROOF>. `source` is
    # COMPLETE | COMPLETE_WITH_UNKNOWN | INCOMPLETE (None when the setting blocked the type).
    absence_resolution: str = "NOT_APPLICABLE"


class AlertEvaluationResponse(BaseModel):
    request_id: str
    evaluated_at: datetime
    vehicle_ids: list[str]
    settings: dict[str, str]
    outcomes: list[AlertEvaluationOutcome]
    totals: dict[str, int]


class AcknowledgeAlertRequest(BaseModel):
    reason_th: str | None = Field(default=None, max_length=500)


class MuteAlertRequest(BaseModel):
    muted_until: datetime
    reason_th: str = Field(min_length=1, max_length=500)


class AlertActionResponse(BaseModel):
    alert: AlertResponse
    replayed: bool
    recovered: bool
    outcome: str
