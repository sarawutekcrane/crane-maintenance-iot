"""Shared technician assignment concepts (Core Demo Fixes Delta REV03
sections A/B, G).

Technician identity always references `user_account.user_id` — this
repository has no separate `technician_master`/`maintenance_staff` table
and this module does not create one. `user_id` here is the same opaque
actor-identifier string already used everywhere else in this codebase
(`RequestContext.user_id`, `Repair.opened_by`, `RepairAction.actor`, ...);
in `DEV_AUTH_MODE` that is the fixed development user, never a fabricated
real-world staff name.

`AssignmentRole` and the two append-only history entry shapes below back
the live prototype's `repair_assignment` / `pm_work_assignment` sheets:
one PRIMARY assignment plus zero or more COLLABORATOR assignments, per
repair or PM work order. A later reassignment ends the previous active
row(s) (`ended_at` set, `active_status=False`) rather than deleting them —
"assignment history must remain non-destructive where practical." This
module implements no RBAC/permission system (M02 remains unresolved); it
is compatible with future role/RBAC work, not a substitute for it.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AssignmentRole(str, Enum):
    PRIMARY = "PRIMARY"
    COLLABORATOR = "COLLABORATOR"


class RepairAssignmentHistoryEntry(BaseModel):
    repair_assignment_id: str
    repair_id: str
    user_id: str
    assignment_role: AssignmentRole
    assigned_at: datetime
    assigned_by_user_id: str | None = None
    ended_at: datetime | None = None
    active_status: bool = True
    note: str | None = None


class PmAssignmentHistoryEntry(BaseModel):
    pm_assignment_id: str
    pm_work_order_id: str
    user_id: str
    assignment_role: AssignmentRole
    assigned_at: datetime
    assigned_by_user_id: str | None = None
    ended_at: datetime | None = None
    active_status: bool = True
    note: str | None = None


__all__ = [
    "AssignmentRole",
    "RepairAssignmentHistoryEntry",
    "PmAssignmentHistoryEntry",
]
