"""Phase 7 Batch 7O2a — effective-time parsing and validation for branch events
(pure; no I/O; `now` is passed in).

Contract: Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2 §3.6 (owner
decision A5). Defined now so 7O2c's transfer, insertion and correction
endpoints share one rule; no 7O2a endpoint accepts an effective time.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BANGKOK = ZoneInfo("Asia/Bangkok")
LOWER_BOUND = datetime(1990, 1, 1, tzinfo=timezone.utc)

MODE_NOW = "NOW"
MODE_DATE = "DATE"
MODE_DATETIME = "DATETIME"
PRECISION_DATE = "DATE"
PRECISION_DATETIME = "DATETIME"
SOURCE_SERVER_NOW = "SERVER_NOW"
SOURCE_CLIENT = "CLIENT"

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class EffectiveTimeError(ValueError):
    """A refused effective time; `code` is the contract's 422 error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EffectiveTime:
    instant: datetime  # aware, UTC, whole seconds
    precision: str
    source: str

    @property
    def stored(self) -> str:
        """The stored `start_at` text: UTC ISO 8601 with +00:00."""
        return self.instant.isoformat()


def resolve_effective(effective: Mapping[str, object], now: datetime, *, allow_now: bool = True) -> EffectiveTime:
    """`{"mode": "NOW"}` -> server time (whole seconds); `{"mode": "DATE",
    "date": "YYYY-MM-DD"}` -> 00:00 Asia/Bangkok; `{"mode": "DATETIME",
    "at": "<ISO with offset>"}`. Future instants are refused, never clamped."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now_utc = now.astimezone(timezone.utc)
    mode = effective.get("mode")
    if mode == MODE_NOW:
        if not allow_now:
            raise EffectiveTimeError("EFFECTIVE_MODE_NOT_ALLOWED")
        return EffectiveTime(now_utc.replace(microsecond=0), PRECISION_DATETIME, SOURCE_SERVER_NOW)
    if mode == MODE_DATE:
        raw = effective.get("date")
        if not isinstance(raw, str) or not _DATE.fullmatch(raw):
            raise EffectiveTimeError("EFFECTIVE_MODE_INVALID")
        try:
            day = date.fromisoformat(raw)
        except ValueError as exc:
            raise EffectiveTimeError("EFFECTIVE_MODE_INVALID") from exc
        instant = datetime(day.year, day.month, day.day, tzinfo=BANGKOK).astimezone(timezone.utc)
        precision = PRECISION_DATE
    elif mode == MODE_DATETIME:
        raw = effective.get("at")
        if not isinstance(raw, str):
            raise EffectiveTimeError("EFFECTIVE_MODE_INVALID")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise EffectiveTimeError("EFFECTIVE_MODE_INVALID") from exc
        if parsed.tzinfo is None:
            raise EffectiveTimeError("EFFECTIVE_TIME_OFFSET_REQUIRED")
        if parsed.microsecond:
            raise EffectiveTimeError("EFFECTIVE_TIME_PRECISION")
        instant = parsed.astimezone(timezone.utc)
        precision = PRECISION_DATETIME
    else:
        raise EffectiveTimeError("EFFECTIVE_MODE_INVALID")
    if instant > now_utc:
        raise EffectiveTimeError("FUTURE_EFFECTIVE_NOT_ALLOWED")
    if instant < LOWER_BOUND:
        raise EffectiveTimeError("EFFECTIVE_TIME_OUT_OF_RANGE")
    return EffectiveTime(instant, precision, SOURCE_CLIENT)
