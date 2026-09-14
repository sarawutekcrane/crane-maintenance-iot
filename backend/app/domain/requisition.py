"""FUTURE STORE / INVENTORY INTEGRATION BOUNDARY (Core Demo Fixes prompt;
Core Demo Fixes Delta REV03 alignment section D).

This branch does NOT implement a warehouse/stock-ledger/purchasing/store-
approval system. `MaterialRequest` (header) + `RequisitionLine` (detail)
are only a stable, integration-ready data shape a future Store/Inventory
project can consume without requiring Repair/PM to be rewritten — backed
by the live prototype's `material_request` / `material_request_line`
sheets. Every field this branch cannot yet populate (approved/issued/used/
returned quantity, and the request's own approved/issued/closed audit
fields) stays `None` rather than being fabricated or defaulted to `0`.
`request_status` is a plain, unconstrained string (default `"OPEN"`) —
never a Store approval/transition lifecycle this branch has no authority
to invent.

PM's approved-scope auto-requisition (PM WORKFLOW REDESIGN section F)
creates exactly one `MaterialRequest` header plus one `RequisitionLine`
per in-scope task's standard `PmTaskPart` — approving a PM work order's
scope never decrements any stock balance, never requires a warehouse
approval step, and never assumes a `PmTaskPart`/`part_id` mapping exists
(when the source data has none, zero lines are generated — nothing is
invented). A Repair may also create a `MaterialRequest` explicitly
(Delta section H, "waiting for parts") — never automatically, and never
by duplicating the Repair record itself.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class RequisitionSourceType(str, Enum):
    PM = "PM"
    REPAIR = "REPAIR"


class MaterialRequest(BaseModel):
    """Requisition header (Delta `material_request` sheet). One header per
    PM scope approval or per explicit Repair parts request — never one row
    per line."""

    material_request_id: str
    source_type: RequisitionSourceType
    source_work_order_id: str
    """The PM Work Order ID or Repair ID this request was raised for."""
    vehicle_id: str | None = None
    """Only populated when the source asset is a VEHICLE; `None` for
    EQUIPMENT (no fabricated equipment identity is substituted)."""
    request_status: str = "OPEN"
    """Plain, unconstrained string — no Store approval/transition lifecycle
    is invented in this branch (Delta section D)."""
    created_at: datetime
    created_by: str | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    issued_at: datetime | None = None
    issued_by: str | None = None
    closed_at: datetime | None = None
    note: str | None = None


class RequisitionLine(BaseModel):
    """Requisition detail line (Delta `material_request_line` sheet)."""

    requisition_line_id: str
    material_request_id: str
    """The `MaterialRequest` header this line belongs to."""
    source_task_revision_id: str | None = None
    """The `PmTaskRevision` a PM-standard line was generated from, when
    applicable — `None` for a Repair-sourced line."""
    part_id: str | None = None
    part_instance_id: str | None = None
    part_code_snapshot: str | None = None
    part_description: str
    """Thai display text snapshot (`part_name_snapshot_th` column) —
    preserved even if the Part Master record is later renamed."""
    requested_quantity: float | None = None
    unit: str | None = None
    approved_quantity: float | None = None
    """Future/nullable — no store approval workflow exists in this branch."""
    issued_quantity: float | None = None
    """Future/nullable — no goods-issue workflow exists in this branch."""
    used_quantity: float | None = None
    returned_quantity: float | None = None
    line_source: str | None = None
    """e.g. "PM_STANDARD" / "REPAIR_PART_MASTER" / "REPAIR_UNREGISTERED" —
    descriptive only, not an enforced enum."""
    created_at: datetime
    created_by: str | None = None


class MaterialRequestDetail(BaseModel):
    request: MaterialRequest
    lines: list[RequisitionLine]


__all__ = [
    "RequisitionSourceType",
    "MaterialRequest",
    "RequisitionLine",
    "MaterialRequestDetail",
]
