"""Shared conventions used across all domain modules.

Frozen in Phase 1 (see docs/architecture/API_CONVENTIONS.md):

- Stable IDs: opaque strings, prefixed by entity type (e.g. "VEH-1046",
  "DEV-0001"). IDs are assigned by the backend/repository, never by the
  Google Sheets row number, and never change once assigned.
- Date/time: all timestamps are ISO-8601 UTC strings (Python
  `datetime` with `tzinfo=UTC`, serialized with a trailing "Z").
- Pagination: page-based, 1-indexed, via `PageParams` / `Page[T]` below.
- Search/filter: simple `q` free-text parameter plus explicit typed
  filter fields per endpoint; no ad-hoc query DSL in Phase 1.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Generic, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

T = TypeVar("T")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_BANGKOK_TZ = ZoneInfo("Asia/Bangkok")


def bangkok_today() -> date:
    """Web/API Phase 6 Batch 2B: the current LOCAL calendar date in
    Asia/Bangkok — the live Sheet's own timezone. Deliberately distinct
    from `utc_now().date()`: near the UTC day boundary (Bangkok is
    UTC+7), the UTC calendar date can differ from the Bangkok calendar
    date by up to a day, and certificate expiry is a Bangkok-local
    calendar-date decision (`vehicle_certificate.expiry_date` has no
    time component), never a UTC one. Uses only the Python stdlib
    `zoneinfo` module — no new dependency."""
    return datetime.now(_BANGKOK_TZ).date()


class OperationalStatus(str, Enum):
    """Vehicle operational status (baseline section 4).

    Distinct from IoT connectivity status, which is introduced in a later
    phase. Vehicle-only: workshop equipment uses its own
    `app.domain.equipment.EquipmentOperationalStatus` vocabulary, approved
    separately (see OPEN_DECISIONS_REGISTER_EN.txt, decision C02) rather
    than reusing this enum, which Phase 2 verification found had been done
    incorrectly.
    """

    WORKING = "WORKING"
    READY = "READY"
    MAINTENANCE = "MAINTENANCE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    LONG_TERM_PARKING = "LONG_TERM_PARKING"


class PageParams(BaseModel):
    """Standard pagination query parameters."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class Page(BaseModel, Generic[T]):
    """Standard paginated response envelope."""

    items: list[T]
    page: int
    page_size: int
    total_items: int

    @property
    def total_pages(self) -> int:
        if self.page_size == 0:
            return 0
        return (self.total_items + self.page_size - 1) // self.page_size
