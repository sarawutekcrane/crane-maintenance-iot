"""Alert (Web/API Phase 6 Batch 5A — Alert Read Foundation; baseline
section 23 "ALERTS").

LIVE GOOGLE SHEETS SCHEMA — VERIFIED (not guessed): the live "MAINTENANCE"
spreadsheet's `alert` tab already exists with exactly these 13 headers
(header row only, no data rows yet):

    alert_id, vehicle_id, alert_type, source_type, source_id, severity,
    created_at, alert_status, muted_until, acknowledged_by_user_id,
    acknowledged_at, resolved_at, message_th

`Alert` below carries exactly those fields, one per verified header, and
no other.

BATCH 5A IS READ-ONLY: this module and its service/repository/API
counterparts only ever READ `alert` — no creation, no
acknowledge/mute/resolve/reopen, no generation, no suppression
evaluation. Those all require the still-unresolved A07 (Alert
Deduplication / Auto-Resolve — dedup key, reopen, mute duration,
auto-resolve, acknowledgement behavior all remain TBD-BLOCKING per
`docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`) and an
explicit alert-write RBAC decision (the current live `role_permission`
schema has no dedicated alert-write permission), neither of which this
batch invents.

D24 (APPROVED/FROZEN) resolves ONLY the severity vocabulary — see
`AlertSeverity` below. It does NOT define which `alert_type` receives
which severity; no such mapping exists anywhere in this module, and none
is invented here.

NO-GUESSING RULE: `alert_type` and `source_type` are plain opaque
strings — baseline section 23 lists categories such as `PM_DUE`/
`PM_OVERDUE`/`DEVICE_OFFLINE`/`SENSOR_ERROR` explicitly as examples
("Alert categories MAY include"), never as a closed/authoritative
machine-readable vocabulary, and no `AlertType`/`SourceType` enum is
introduced here — this mirrors the identical precedent already
established for `vehicle_event.event_type`'s opaque cousins
(`document_type`, `certificate_type_code`) before Batch 4A's explicit,
narrowly-scoped exception. `source_id` is a plain opaque text
reference — may legitimately contain leading zeros, never numerically
coerced, never used for ordering/uniqueness.

CONSERVATIVE NULLABILITY: no live data rows exist yet to prove which of
the 13 columns are always populated in practice (the live tab currently
has only its header row). Following the same conservative pattern every
earlier Phase 6 domain model used when live data didn't yet prove
otherwise (e.g. `VehicleCertificate.certificate_status: CertificateStatus
| None`, `ModelDocument.document_type: str | None`), only `alert_id`,
`vehicle_id`, and `created_at` are modeled as required here — every other
field, including `alert_type` and `alert_status`, is optional and stays
honestly `None` when the underlying cell is blank. Nothing here fabricates
a default merely because a cell may be blank."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AlertSeverity(str, Enum):
    """D24 (APPROVED/FROZEN) — the severity vocabulary only, exactly
    these three values. Which `alert_type` receives which severity is
    explicitly NOT defined here or anywhere else in this batch."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    """Baseline section 23's existing frozen state vocabulary. Batch 5A
    declares this enum for READING stored values only — no transition
    matrix, no acknowledge/mute/resolve/reopen behavior exists in this
    batch (those require A07, still TBD-BLOCKING)."""

    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    MUTED = "MUTED"
    RESOLVED = "RESOLVED"


class Alert(BaseModel):
    """One row of `alert` — mirrors the verified live tab 1:1. Read-only
    in Batch 5A: nothing in this repository/service/API layer ever
    creates, updates, or deletes an `Alert`."""

    alert_id: str
    vehicle_id: str
    alert_type: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    """Opaque passthrough string — may legitimately contain leading
    zeros; never numerically coerced, never used for ordering/uniqueness
    (Phase 6 Batch 1 `phone` / Batch 2A `document_no` precedent)."""
    severity: AlertSeverity | None = None
    created_at: datetime
    alert_status: AlertStatus | None = None
    muted_until: datetime | None = None
    acknowledged_by_user_id: str | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    message_th: str | None = None


__all__ = ["Alert", "AlertSeverity", "AlertStatus"]
