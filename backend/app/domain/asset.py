"""Shared asset-reference pattern.

Established in Phase 2 (see docs/claude-prompts/web-api/02_PHASE2_VEHICLE_MODEL_EQUIPMENT_QR_EN.txt,
scope item 5) for later phases (inspection, repair, attachments/documents)
to point at "the machine or equipment this record is about" without
duplicating vehicle-vs-equipment branching logic in every domain module.

No Phase 2 endpoint returns `AssetRef` directly yet; it is a domain
building block that Phase 3+ workflows compose into their own records
(e.g. a repair order's target asset), the same way `FormField`/
`ConfirmDialog` were established in Phase 1 ahead of a real form/workflow.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    VEHICLE = "VEHICLE"
    EQUIPMENT = "EQUIPMENT"


class AssetRef(BaseModel):
    """Points at exactly one vehicle or equipment record by stable ID."""

    asset_type: AssetType
    asset_id: str = Field(min_length=1)
