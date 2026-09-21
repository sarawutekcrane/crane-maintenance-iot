"""Daily Summary (Web/API Phase 6 Batch 4C — Daily Summary Reconciliation).

LIVE GOOGLE SHEETS SCHEMA — VERIFIED (not guessed): the live "MAINTENANCE"
spreadsheet's `daily_summary` tab already exists with exactly these 9
headers (header row only, no data rows):

    daily_summary_id, summary_date, vehicle_id, component_id, metric_type,
    value, unit, data_status, created_at

`DailySummary` below carries exactly those fields, one per verified
header, and no other — no `device_id` (aggregation is per vehicle +
component, never per device — see module docstring below), no
`updated_at`, no `anomaly_code`/`note`/`source_event_id`/`percent`/
`hours`/`minutes`. None of those exist in the live schema.

DAILY SUMMARY IS DERIVED CURRENT STATE, NOT RAW HISTORY: every row here
is backend-computed by
`app.domain.daily_summary_service.DailySummaryService.
reconcile_vehicle_component` from trusted `vehicle_event` rows — it is
never client-created/edited, and a row can legitimately change (value,
data_status) when a later/out-of-order trusted event is ingested and the
whole affected stream is replayed. The raw `vehicle_event` table itself
is never touched by this reconciliation.

METRIC TYPES — exactly two, frozen for Batch 4C: `ENGINE_RUN_DURATION`
(paired from `ENGINE_START`=OPEN/`ENGINE_STOP`=CLOSE) and
`PTO_RUN_DURATION` (paired from `PTO_ON`=OPEN/`PTO_OFF`=CLOSE).
`DEVICE_ONLINE`/`DEVICE_OFFLINE` are never summarized by this batch.

UNIT is always exactly `"s"` (seconds) — `value` is the actual elapsed
`total_seconds()` of provable interval(s), never rounded/converted to
hours, never formatted as a duration string.

DATA_STATUS: `COMPLETE` when every relevant interval for that
`(summary_date, vehicle_id, component_id, metric_type)` key is fully
provable and no anomaly touches that date; `PARTIAL` when at least one
anomaly (repeated OPEN, CLOSE-while-CLOSED, or an OPEN with no matching
CLOSE anywhere in trusted history) affects that date, or when no provable
interval exists at all for that date/metric (in which case `value` is
`None`, never fabricated as `0`) — see
`DailySummaryService.reconcile_vehicle_component`'s docstring for the
full state-machine/anomaly/splitting rules (frozen contract sections 6-9)."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel


class DailySummaryMetricType(str, Enum):
    ENGINE_RUN_DURATION = "ENGINE_RUN_DURATION"
    PTO_RUN_DURATION = "PTO_RUN_DURATION"


class DailySummaryDataStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class DailySummary(BaseModel):
    """One row of `daily_summary` — mirrors the verified live tab 1:1.
    The authoritative uniqueness key is `(summary_date, vehicle_id,
    component_id, metric_type)`; `daily_summary_id` is a backend-
    generated opaque identity (`DSUM-` prefix), never derived from row
    position, and never changes once assigned even when the row's
    derived `value`/`data_status` are later recomputed."""

    daily_summary_id: str
    summary_date: date
    vehicle_id: str
    component_id: str
    metric_type: DailySummaryMetricType
    value: float | None = None
    """Elapsed seconds of provable interval(s) for this key — `None`
    (never `0`) when no complete interval is provable at all. A genuine
    zero-duration complete interval (a START immediately followed by a
    STOP at the exact same instant) legitimately produces `0.0`, which is
    a real, distinct value from unknown/`None`."""
    unit: str = "s"
    data_status: DailySummaryDataStatus
    created_at: datetime
    """Backend UTC creation time of this row, set once and preserved
    across every later recomputation/update of the same key — never
    refreshed to "now" on an update (no `updated_at` column exists in the
    live schema)."""


__all__ = ["DailySummary", "DailySummaryDataStatus", "DailySummaryMetricType"]
