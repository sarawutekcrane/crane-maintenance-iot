"""FUTURE STORE / INVENTORY INTEGRATION BOUNDARY (Core Demo Fixes prompt).

This branch does NOT implement a warehouse/stock-ledger/purchasing/store-
approval system. `RequisitionLine` is only a stable, integration-ready
data shape a future Store/Inventory project can consume without requiring
Repair/PM to be rewritten — every field the prompt lists is present, and
every field this branch cannot yet populate (approved/issued/used/
returned quantity) stays `None` rather than being fabricated or defaulted
to `0`.

Only PM's approved-scope auto-requisition (section F) creates
`RequisitionLine` rows in this branch — approving a PM work order's scope
never decrements any stock balance, never requires a warehouse approval
step, and never assumes a `PmTaskPart`/`part_id` mapping exists (when the
source data has none, zero lines are generated — nothing is invented).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class RequisitionSourceType(str, Enum):
    PM = "PM"
    REPAIR = "REPAIR"


class RequisitionLine(BaseModel):
    requisition_line_id: str
    work_order_reference: str
    """The PM Work Order ID or Repair ID this line was generated from."""
    source_type: RequisitionSourceType
    part_id: str | None = None
    part_instance_id: str | None = None
    part_description: str
    requested_quantity: float | None = None
    unit: str | None = None
    approved_quantity: float | None = None
    """Future/nullable — no store approval workflow exists in this branch."""
    issued_quantity: float | None = None
    """Future/nullable — no goods-issue workflow exists in this branch."""
    used_quantity: float | None = None
    returned_quantity: float | None = None
    created_at: datetime
    created_by: str | None = None


__all__ = ["RequisitionSourceType", "RequisitionLine"]
