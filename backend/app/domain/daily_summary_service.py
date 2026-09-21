"""Daily Summary reconciliation service (Web/API Phase 6 Batch 4C —
Daily Summary Reconciliation). See `app.domain.daily_summary` for the
`DailySummary` model and the live-schema/derived-state framing.

RECONCILIATION MODEL — frozen contract sections 3-10:

`reconcile_vehicle_component` rebuilds the COMPLETE set of
`ENGINE_RUN_DURATION`/`PTO_RUN_DURATION` daily_summary rows for one
`(vehicle_id, component_id)` from scratch, from trusted raw
`vehicle_event` history, every time it runs — never an incremental patch
of one interval. This is the deliberate, documented tradeoff (section 10:
"correctness is more important than premature optimization in this
Google Sheets prototype") that makes delayed/out-of-order ingestion
deterministic: a late-arriving earlier event can turn a previously
PARTIAL/null summary into COMPLETE, or vice versa, simply by being
present the next time this function runs — never by patching state.
`vehicle_event` itself is only ever read here, never mutated.

PAIRING (section 3): events are paired ONLY within the exact same
`(vehicle_id, device_id, component_id, family)` — `family` is `ENGINE`
(`ENGINE_START`=OPEN/`ENGINE_STOP`=CLOSE) or `PTO` (`PTO_ON`=OPEN/
`PTO_OFF`=CLOSE). A vehicle may carry multiple independent ESP32 devices
on the same component; each device's stream is paired independently and
their provable durations are then SUMMED per Bangkok day (section 21) —
no preferred/hardcoded device, no cross-device pairing.

TRUSTED TIME (D20, section 4): only events with `time_quality` in
(`TIME_SYNCED`, `TIME_ESTIMATED`) AND a non-null `event_time` are used
for pairing/duration/summary_date/status — `TIME_NOT_SYNCED` is excluded
entirely, even if it happens to carry an `event_time`, and `received_at`
is never substituted as occurrence time.

ORDERING (section 5): within one `(device_id, family)` stream, trusted
events sort by `event_time` ascending, then `sequence` ascending, then
`received_at` ascending, then `event_id` as a final deterministic
tie-break.

STATE MACHINE / ANOMALIES (section 6): CLOSED -> OPEN on an OPEN event;
OPEN -> CLOSED (producing one complete interval) on a CLOSE event. An
OPEN while already OPEN is an anomaly — the FIRST open start is kept
(never replaced), and the Bangkok date of the REPEATED open marks that
date PARTIAL. A CLOSE while CLOSED is an anomaly — no duration is
created, and the Bangkok date of that CLOSE marks that date PARTIAL. A
stream left OPEN at the end of known history is an anomaly — no end time
is ever fabricated (never "now", never `received_at`, never 23:59:59),
and the Bangkok date of the unmatched OPEN's own start marks that date
PARTIAL.

CROSS-MIDNIGHT SPLITTING (section 7): a proven (complete) interval is
split into per-Asia/Bangkok-calendar-day segments at each local midnight
boundary — an interval spanning an entire intermediate Bangkok day
legitimately contributes a full 86400-second segment for that day even
though no raw event row falls on it. No maximum interval duration is
enforced.

VALUE/STATUS (D21, section 8): for each `(summary_date, metric_type)`
key, if at least one provable interval segment exists, `value` is the
sum of those segments' seconds (0.0 is a legitimate value for a genuine
zero-duration interval, never confused with unknown) and `data_status`
is `PARTIAL` if any anomaly also touches that date, else `COMPLETE`. If
anomalies exist for that date/metric but zero interval segments are
provable, `value` stays `None` (never fabricated as `0`) and
`data_status` is `PARTIAL`."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from fastapi import status

from app.domain.common import next_bangkok_midnight, to_bangkok_date
from app.domain.daily_summary import DailySummary, DailySummaryDataStatus, DailySummaryMetricType
from app.domain.vehicle_event import TimeQuality, VehicleEvent, VehicleEventType
from app.errors import ApiError
from app.repositories.base import Repository

_FAMILY_METRIC: dict[str, DailySummaryMetricType] = {
    "ENGINE": DailySummaryMetricType.ENGINE_RUN_DURATION,
    "PTO": DailySummaryMetricType.PTO_RUN_DURATION,
}

# event_type -> (family, role); every other VehicleEventType (including
# DEVICE_ONLINE/DEVICE_OFFLINE) is simply not present here and is
# therefore never summarized by this batch (frozen contract section 1/19).
_FAMILY_ROLE: dict[VehicleEventType, tuple[str, str]] = {
    VehicleEventType.ENGINE_START: ("ENGINE", "OPEN"),
    VehicleEventType.ENGINE_STOP: ("ENGINE", "CLOSE"),
    VehicleEventType.PTO_ON: ("PTO", "OPEN"),
    VehicleEventType.PTO_OFF: ("PTO", "CLOSE"),
}


def _is_trusted(event: VehicleEvent) -> bool:
    return (
        event.time_quality in (TimeQuality.TIME_SYNCED, TimeQuality.TIME_ESTIMATED)
        and event.event_time is not None
    )


def _sort_key(event: VehicleEvent) -> tuple:
    return (event.event_time, event.sequence, event.received_at, event.event_id)


def _split_interval_by_bangkok_day(start: datetime, end: datetime) -> list[tuple[date, float]]:
    """One proven interval `[start, end]` -> per-Bangkok-calendar-day
    `(date, seconds)` segments (frozen contract section 7). `start ==
    end` (a genuine zero-duration complete interval) is a special case —
    the loop below never enters for an empty range, but D21 requires a
    real, distinct `0.0` value on that interval's own day, not silent
    omission."""
    if start == end:
        return [(to_bangkok_date(start), 0.0)]
    segments: list[tuple[date, float]] = []
    cursor = start
    while cursor < end:
        day = to_bangkok_date(cursor)
        midnight = next_bangkok_midnight(cursor)
        segment_end = min(end, midnight)
        segments.append((day, (segment_end - cursor).total_seconds()))
        cursor = segment_end
    return segments


class DailySummaryService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _require_vehicle_exists(self, vehicle_id: str) -> None:
        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            raise ApiError(
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle '{vehicle_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    async def reconcile_vehicle_component(self, vehicle_id: str, component_id: str) -> None:
        """Rebuild every ENGINE_RUN_DURATION/PTO_RUN_DURATION
        daily_summary row for this exact `(vehicle_id, component_id)`
        from trusted raw vehicle_event history. See module docstring for
        the full rule set. Idempotent: running this again with no new
        trusted events produces the same result and the same
        `daily_summary_id`s (only `value`/`unit`/`data_status` are ever
        overwritten by `Repository.upsert_daily_summary`)."""
        events = await self._repository.list_vehicle_events_for_vehicle(vehicle_id)
        # Steps 2-5 (frozen contract section 17): exact component, ENGINE/
        # PTO families only, trusted rows only.
        relevant = [
            e
            for e in events
            if e.component_id == component_id and e.event_type in _FAMILY_ROLE
        ]
        trusted = [e for e in relevant if _is_trusted(e)]

        # Step 6: group per exact source stream (device_id) + family.
        streams: dict[tuple[str, str], list[VehicleEvent]] = defaultdict(list)
        for event in trusted:
            family, _role = _FAMILY_ROLE[event.event_type]
            streams[(event.device_id, family)].append(event)

        totals: dict[tuple[date, DailySummaryMetricType], float] = defaultdict(float)
        anomalous_dates: dict[tuple[date, DailySummaryMetricType], bool] = defaultdict(bool)

        for (_device_id, family), stream_events in streams.items():
            metric_type = _FAMILY_METRIC[family]
            # Step 7: deterministic chronological ordering within this
            # exact stream (never Sheet row order, never received_at
            # alone).
            stream_events.sort(key=_sort_key)

            # Step 8: rebuild the OPEN/CLOSE state machine and collect
            # complete intervals + anomaly dates.
            open_start: datetime | None = None
            for event in stream_events:
                _family, role = _FAMILY_ROLE[event.event_type]
                if role == "OPEN":
                    if open_start is None:
                        open_start = event.event_time
                    else:
                        # OPEN while OPEN: keep the first, mark the
                        # REPEATED open's own date PARTIAL.
                        anomalous_dates[
                            (to_bangkok_date(event.event_time), metric_type)
                        ] = True
                else:  # CLOSE
                    if open_start is not None:
                        # Step 9: split this proven interval across any
                        # Bangkok midnights it crosses.
                        for day, seconds in _split_interval_by_bangkok_day(
                            open_start, event.event_time
                        ):
                            totals[(day, metric_type)] += seconds
                        open_start = None
                    else:
                        # CLOSE while CLOSED: mark the CLOSE's own date
                        # PARTIAL; no duration is created.
                        anomalous_dates[
                            (to_bangkok_date(event.event_time), metric_type)
                        ] = True

            if open_start is not None:
                # End of known history while still OPEN: never fabricate
                # an end time — mark the unmatched OPEN's own date
                # PARTIAL.
                anomalous_dates[(to_bangkok_date(open_start), metric_type)] = True

        # Steps 10-11 (D21): aggregate to vehicle + component + date +
        # metric and apply the value/status semantics.
        keys = set(totals.keys()) | set(anomalous_dates.keys())
        for summary_date, metric_type in keys:
            has_provable_value = (summary_date, metric_type) in totals
            value = totals[(summary_date, metric_type)] if has_provable_value else None
            is_anomalous = anomalous_dates.get((summary_date, metric_type), False)
            data_status = (
                DailySummaryDataStatus.COMPLETE
                if (has_provable_value and not is_anomalous)
                else DailySummaryDataStatus.PARTIAL
            )
            # Step 12: upsert (never a second row for the same key).
            await self._repository.upsert_daily_summary(
                summary_date=summary_date,
                vehicle_id=vehicle_id,
                component_id=component_id,
                metric_type=metric_type,
                value=value,
                unit="s",
                data_status=data_status,
            )

    async def list_for_vehicle(self, vehicle_id: str) -> list[DailySummary]:
        """Deterministic read ordering (frozen contract section 20):
        summary_date descending, then component_id ascending, then
        metric_type ascending, then daily_summary_id as a final
        tie-break."""
        await self._require_vehicle_exists(vehicle_id)
        summaries = await self._repository.list_daily_summaries_for_vehicle(vehicle_id)
        return sorted(
            summaries,
            key=lambda s: (
                s.summary_date.toordinal() * -1,
                s.component_id,
                s.metric_type.value,
                s.daily_summary_id,
            ),
        )


__all__ = ["DailySummaryService"]
