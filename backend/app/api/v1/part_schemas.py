from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.part import PartSetItemRequirement, TrackingMode


class CreatePartMasterRequest(BaseModel):
    part_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    specification: str | None = Field(default=None, max_length=300)
    manufacturer: str | None = Field(default=None, max_length=200)
    part_number: str | None = Field(default=None, max_length=200)
    tracking_mode: TrackingMode
    category: str | None = Field(default=None, max_length=100)
    metadata: dict[str, str] = Field(default_factory=dict)


class PartMasterResponse(BaseModel):
    part_id: str
    part_code: str
    name: str
    specification: str | None
    manufacturer: str | None
    part_number: str | None
    tracking_mode: TrackingMode
    category: str | None
    is_active: bool
    metadata: dict[str, str]
    created_at: datetime
    updated_at: datetime


class CreatePartSetRequest(BaseModel):
    set_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)


class PartSetResponse(BaseModel):
    part_set_id: str
    set_code: str
    name: str
    created_at: datetime
    updated_at: datetime


class PartSetRevisionItemRequest(BaseModel):
    part_id: str = Field(min_length=1)
    requirement: PartSetItemRequirement
    quantity: float | None = None
    unit: str | None = None
    note: str | None = Field(default=None, max_length=300)


class CreatePartSetRevisionRequest(BaseModel):
    effective_date: date
    items: list[PartSetRevisionItemRequest] = Field(default_factory=list)


class PartSetItemResponse(BaseModel):
    part_set_item_id: str
    revision_id: str
    part_id: str
    requirement: PartSetItemRequirement
    quantity: float | None
    unit: str | None
    note: str | None


class PartSetRevisionResponse(BaseModel):
    revision_id: str
    part_set_id: str
    revision_number: int
    effective_date: date
    created_at: datetime


class PartSetRevisionDetailResponse(BaseModel):
    part_set: PartSetResponse
    revision: PartSetRevisionResponse
    items: list[PartSetItemResponse]
