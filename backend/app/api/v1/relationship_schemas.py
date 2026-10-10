"""R2 Batch R2f-a — response models of the read-only relationship routes.

Stable ids are separate fields from display names. The account link shows its
resolution state only: the raw linked `user_id` is deliberately NOT returned
in R2f-a. Final Contract C1 §16 reserves it for the future Personnel ↔ Account
relationship-management capability (R2f-c), which does not exist yet, and no
existing role is widened to stand in for it.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Resolution = Literal["RESOLVED", "UNSET", "MISSING", "AMBIGUOUS", "SCOPE_UNPROVEN"]
ReverseResolution = Literal["RESOLVED", "UNSET", "AMBIGUOUS"]


class TechnicianResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technician_id: str
    # Exact source text; null when the source cell is blank (never substituted).
    first_name: str | None
    last_name: str | None
    # Raw source text, not an enum; null = blank/unknown, never defaulted to ACTIVE.
    active_status: str | None


class TechnicianLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Resolution
    # The exact personnel_master.technician_id cell; null only when UNSET.
    technician_id: str | None
    # Present only when RESOLVED.
    technician: TechnicianResponse | None


class AccountLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Resolution state only; the linked user_id is not exposed in R2f-a.
    resolution: Resolution


class PersonnelRelationshipsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personnel_id: str
    technician: TechnicianLinkResponse
    account: AccountLinkResponse


class TechnicianPersonnelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technician_id: str
    # RESOLVED: exactly one in-scope personnel; UNSET: none; AMBIGUOUS: more
    # than one (fail closed: no personnel_id is selected).
    resolution: ReverseResolution
    personnel_id: str | None
    match_count: int
