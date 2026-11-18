"""Response schema for the Phase 7 Batch 7B2 fleet status dashboard."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FleetStatusCountsResponse(BaseModel):
    """K2-K6: recorded operational-status counts. All five keys are always
    present, including zero."""

    model_config = ConfigDict(extra="forbid")

    WORKING: int = Field(ge=0)
    READY: int = Field(ge=0)
    MAINTENANCE: int = Field(ge=0)
    OUT_OF_SERVICE: int = Field(ge=0)
    LONG_TERM_PARKING: int = Field(ge=0)


class FleetStatusSummaryResponse(BaseModel):
    """Fleet status summary. `vehicle_total` (K1) is the number of vehicle
    master records (of the applied branch, when `branch_id` is given) and always
    equals the sum of `status_counts`. It says nothing about IoT connectivity or
    physical readiness. R8: `branch_id` echoes the applied exact branch filter
    and is omitted when no filter was given (the unfiltered body is unchanged)."""

    model_config = ConfigDict(extra="forbid")

    branch_id: str | None = None
    population: Literal["VEHICLE_MASTER_VALIDATED_RECORDS"]
    vehicle_total: int = Field(ge=0)
    status_counts: FleetStatusCountsResponse
