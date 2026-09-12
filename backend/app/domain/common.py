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

from datetime import datetime, timezone
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
