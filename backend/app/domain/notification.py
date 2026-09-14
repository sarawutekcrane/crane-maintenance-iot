"""Assignment notification boundary (Core Demo Fixes Delta REV05 section
7) — integration-ready only. No external LINE/Push/Email delivery exists
in this Core branch (Phase 6 remains the place for that); this module
gives a future notification phase a single, already-populated event to
subscribe to instead of re-deriving "what changed" from raw repository
state.

`NotificationPort.notify_assignment` MUST NEVER raise past this module —
assignment persistence has already succeeded by the time it's called, and
REV05 explicitly requires that to remain true "independently of later
external notification delivery." `NoOpNotificationSink` (the default
wired in `app.dependencies`) only logs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

logger = logging.getLogger("app.notification")


@dataclass(frozen=True)
class AssignmentNotificationPayload:
    """Everything REV05 section 7 names as "expose when available" for a
    Repair assignment/reassignment event."""

    repair_id: str
    asset_type: str
    asset_id: str
    symptom: str | None
    priority: str | None
    opened_by: str | None
    """User who opened/accepted the RPR."""
    original_reporter: str | None
    """`reported_by_user_id` of the source Repair Request, when this
    Repair was converted from one — `None` for a directly-opened RPR."""
    opened_at: datetime
    assigned_at: datetime
    meter_snapshot_id: str | None
    location_snapshot_id: str | None
    attachment_ids: list[str] = field(default_factory=list)
    source_type: str | None = None
    source_id: str | None = None
    route: str = ""
    """Application route/reference to the RPR, e.g. `/repairs/RPR-0001`."""
    primary_technician: str | None = None
    collaborators: list[str] = field(default_factory=list)


class NotificationPort(Protocol):
    async def notify_assignment(self, payload: AssignmentNotificationPayload) -> None: ...


class NoOpNotificationSink:
    """Default sink: logs only. Assignment persistence never depends on
    this succeeding — see module docstring."""

    async def notify_assignment(self, payload: AssignmentNotificationPayload) -> None:
        try:
            logger.info(
                "assignment notification: repair_id=%s primary=%s collaborators=%s route=%s",
                payload.repair_id,
                payload.primary_technician,
                payload.collaborators,
                payload.route,
            )
        except Exception:  # noqa: BLE001 - never let a logging failure propagate
            pass


__all__ = ["AssignmentNotificationPayload", "NotificationPort", "NoOpNotificationSink"]
