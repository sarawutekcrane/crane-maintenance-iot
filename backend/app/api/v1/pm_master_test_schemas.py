"""R8 PRE-UAT — request bodies of the PM Master TEST profile routes (SG-PM, Owner gate 2026-11-18).
Every write also needs a client `X-Request-Id`; the Master's own replay contract applies."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewRequest(_Body):
    reason: str = Field(min_length=1, max_length=300)


class ReviewRequest(_Body):
    expected_source_digest: str = Field(min_length=1, max_length=128)
    entry_id: str = Field(min_length=1, max_length=80)
    outcome: str = Field(min_length=1, max_length=40)
    evidence: str = Field(min_length=1, max_length=500)
    values: dict[str, str] | None = None


class PublishRequest(_Body):
    preview_id: str = Field(min_length=1, max_length=80)
    expected_source_digest: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=300)


class VariantApprovalRequest(_Body):
    model_id: str = Field(min_length=1, max_length=60)
    model_variant: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=0)
    preview_id: str = Field(min_length=1, max_length=80)
    expected_source_digest: str = Field(min_length=1, max_length=128)
    source_rows: list[str] = Field(min_length=1, max_length=20)
    evidence: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=300)


class AssignmentRequest(_Body):
    vehicle_id: str = Field(min_length=1, max_length=60)
    assembly: str = Field(default="", max_length=20)
    plan_code: str | None = Field(default=None, max_length=80)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=300)


class OpenWorkOrderRequest(_Body):
    revision_number: int = Field(ge=1)
    selected_set_keys: list[str] = Field(min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=500)
