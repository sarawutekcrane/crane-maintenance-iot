"""Repair Request — a reported problem waiting for Maintenance review.

Core Demo Fixes Delta REV05 sections 2/3: overrides the earlier behavior
that let a Driver/technician/Inspection/PM flow create a Repair Work
Order (`RPR-xxxx`) directly. A Repair Request is NOT a Repair Work Order:
- Repair Request = reported problem waiting for Maintenance review
  (`request_status="PENDING"`).
- Repair Work Order = the accepted/open occurrence (`Repair`,
  `RPR-xxxx`), created only once an authorized Maintenance actor converts
  a pending request (or opens one directly with no request at all).

Backs the live `repair_request` sheet exactly as REV05 gives it — do not
add or rename columns here. `request_status` stays a plain,
unconstrained string (mirrors `MaterialRequest.request_status`'s own
precedent) rather than a fabricated final state machine: REV05 explicitly
says to leave rejection/cancellation/duplicate states TBD rather than
invent them, so only `PENDING` and `CONVERTED` are given real meaning by
`RepairRequestService` below.

`reporter_type`/`report_channel` stay plain, unconstrained strings for
the same reason — no rigid vocabulary is approved for either.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

REPAIR_REQUEST_STATUS_PENDING = "PENDING"
REPAIR_REQUEST_STATUS_CONVERTED = "CONVERTED"


class RepairRequest(BaseModel):
    """One row of the live `repair_request` sheet — field names match its
    columns exactly."""

    repair_request_id: str
    vehicle_id: str
    reported_at: datetime
    reported_by_user_id: str | None = None
    reporter_type: str | None = None
    reporter_driver_id: str | None = None
    reporter_name_snapshot_th: str | None = None
    report_channel: str | None = None
    symptom_th: str | None = None
    priority: str | None = None
    request_status: str = REPAIR_REQUEST_STATUS_PENDING
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    repair_id: str | None = None
    converted_at: datetime | None = None
    note_th: str | None = None
    meter_snapshot_id: str | None = None
    """CORE-G01 automatic machine-state snapshot captured at report time
    (REV05 section 4) — domain-only convenience field, NOT one of the
    `repair_request` sheet's given 16 columns (it has no reserved column
    for this). `MockRepository` persists it so the demo's Maintenance
    review queue can show it; `GoogleSheetsRepository` honestly returns
    `None` here until a column is approved (documented, reversible gap —
    see docs/phase-results/core-demo-fixes-result.md REV05 section)."""


__all__ = [
    "RepairRequest",
    "REPAIR_REQUEST_STATUS_PENDING",
    "REPAIR_REQUEST_STATUS_CONVERTED",
]
