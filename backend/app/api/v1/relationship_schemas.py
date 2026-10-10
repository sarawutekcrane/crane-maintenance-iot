"""R2 Batch R2f-a — response models of the read-only relationship routes.

Stable ids are separate fields from display names. The account link shows its
resolution state; the raw linked `user_id` is returned ONLY to a holder of
`can_link_personnel_account` (Final Contract C1 §16, introduced in R2f-c). No
other account field (name, email, phone, role, MFA, status) is ever returned.
R2 Batch R2f-e adds the Driver link: its resolution and the exact driver_id only.
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

    resolution: Resolution
    # R2 Batch R2f-c: the exact personnel_master.user_id cell, present ONLY for a
    # holder of can_link_personnel_account (null = UNSET). For every other caller
    # the field is ABSENT (resolution only), as in R2f-a.
    user_id: str | None = None


class DriverLinkResponse(BaseModel):
    """R2 Batch R2f-e: the Driver identity link. The stable driver_id is visible to
    every can_view caller (no redaction rule applies to it); no other Driver field
    (name, phone, licence, expiry, status, note) is ever returned."""

    model_config = ConfigDict(extra="forbid")

    resolution: Resolution
    # The exact personnel_master.driver_id cell; null only when UNSET.
    driver_id: str | None


class PersonnelRelationshipsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personnel_id: str
    technician: TechnicianLinkResponse
    account: AccountLinkResponse
    driver: DriverLinkResponse


class TechnicianPersonnelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technician_id: str
    # RESOLVED: exactly one in-scope personnel; UNSET: none; AMBIGUOUS: more
    # than one (fail closed: no personnel_id is selected).
    resolution: ReverseResolution
    personnel_id: str | None
    match_count: int
