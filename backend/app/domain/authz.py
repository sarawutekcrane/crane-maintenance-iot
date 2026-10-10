"""Capability-based authorization gate.

Core Demo Fixes Delta REV05 section 2/10: a newly-approved authority
model requires distinguishing "may report a problem" from "may
create/accept/close a Repair Work Order" and "may open/scope/assign/close
a PM Work Order" — plain role-name checks (`require_supervisory_role`,
kept below for any caller not yet migrated) are no longer precise enough.

This module intentionally implements ONLY the 6 capability names REV05's
section 10 names as needed for the approved Core authority rules
(`can_view`, `can_manage_pm`, `can_report_repair`, `can_manage_repair`,
`can_close_repair`, `can_record_inspection`) — matching the live
`role_permission` sheet's own column names 1:1 so a later phase can back
this with real per-user rows without renaming anything here. This is
explicitly NOT the final permission matrix (OPEN_DECISIONS_REGISTER_EN.txt
M02 remains TBD-BLOCKING): there is no per-screen/per-menu visibility
matrix, no data-scope model (OWN/ASSIGNED/DEPARTMENT/ALL), and no
specialized role variants here — only the smallest reversible rule this
phase's approved workflow actually requires.

`ROLE_CAPABILITIES` maps a small, clearly-provisional set of Core-phase
role names to these 6 capabilities so `DEV_AUTH_MODE` (no real
login/`user_account`/`role_permission` read exists yet) can simulate
distinct actors for tests and manual walkthroughs — see
`app.context.RequestContextMiddleware` for how a request picks a role.
`ADMIN` always holds every capability so every test/behavior that predates
this capability model (all of it ran as the fixed `dev-user`/`ADMIN`
actor) keeps working unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from fastapi import HTTPException, status

if TYPE_CHECKING:
    # Type-only: avoids a circular import, since `app.context` computes
    # each request's `capabilities` field using `capabilities_for_roles`
    # below.
    from app.context import RequestContext

# ---------------------------------------------------------------------------
# Capabilities (exact `role_permission` sheet column names).
# ---------------------------------------------------------------------------

CAN_VIEW = "can_view"
CAN_MANAGE_PM = "can_manage_pm"
CAN_REPORT_REPAIR = "can_report_repair"
CAN_MANAGE_REPAIR = "can_manage_repair"
CAN_CLOSE_REPAIR = "can_close_repair"
CAN_RECORD_INSPECTION = "can_record_inspection"
# Phase 7 Batch 7O2b (contract Final Rev2 §3.1): edit a vehicle's registration
# and reconcile its registration history. A future `role_permission` column
# name (UNVERIFIED live). The two branch capabilities arrive with 7O2c.
CAN_EDIT_VEHICLE_REGISTRATION = "can_edit_vehicle_registration"
# Phase 7 Batch 7O2c (contract Final Rev2 §3.1, A4): transfer a vehicle's
# responsible branch / reconcile the master projection, and edit branch history
# (insert, correct, cancel). Holding the first never implies the second.
CAN_TRANSFER_VEHICLE_BRANCH = "can_transfer_vehicle_branch"
# R2 Batch R2d: the correction capability also covers EQUIPMENT branch-history
# corrections (backdated insertion, correction, cancellation). Its value is
# unchanged; it never implies an assignment/transfer capability, or vice versa.
CAN_CORRECT_BRANCH_HISTORY = "can_correct_branch_history"
# R2 Batch R2d (owner-approved): assign / transfer an EQUIPMENT's responsible
# branch (history-only). Independent of can_transfer_vehicle_branch: neither
# implies the other. Neither authorizes any Part transfer (a separate future
# Parts decision).
CAN_TRANSFER_EQUIPMENT_BRANCH = "can_transfer_equipment_branch"
# R2 Batch R2e (owner-approved): deactivate / reactivate / reconcile the
# lifecycle of a personnel record and of a department record. Separate and
# independent; neither is login-account management (can_manage_user is not
# reused), and neither implies any account, technician, driver or assignment
# change. A future production-auth cutover must add the approved
# role_permission mapping; today they are DEV_AUTH-backed.
CAN_MANAGE_PERSONNEL = "can_manage_personnel"
CAN_MANAGE_DEPARTMENT = "can_manage_department"
# R2 Batch R2f-b (owner-approved, least privilege): link / unlink / relink /
# reconcile the Personnel ↔ Technician relationship. Separate from the
# lifecycle capabilities: neither implies the other, and it implies no
# account, driver, assignment or responsibility change. DEV_AUTH-backed today.
CAN_LINK_PERSONNEL_TECHNICIAN = "can_link_personnel_technician"
# R2 Batch R2f-c (owner-approved, least privilege): link / unlink / relink /
# reconcile the Personnel ↔ User Account relationship, and see the raw linked
# user_id in the relationship read. Separate from every other capability; it
# never authorizes account provisioning, passwords, MFA, roles or the account's
# own fields (R11). DEV_AUTH-backed today.
CAN_LINK_PERSONNEL_ACCOUNT = "can_link_personnel_account"
# R2 Batch R2f-d (owner-approved, least privilege): record / transfer / insert /
# end / correct / cancel an equipment's caretaker period (equipment_caretaker_history).
# Separate from every other capability (the personnel lifecycle and link
# capabilities are not reused); it never authorizes inspection recording or
# selection, a driver responsibility, or any personnel / technician change.
# DEV_AUTH-backed today.
CAN_ASSIGN_EQUIPMENT_CARETAKER = "can_assign_equipment_caretaker"

ALL_CAPABILITIES = frozenset(
    {
        CAN_VIEW,
        CAN_MANAGE_PM,
        CAN_REPORT_REPAIR,
        CAN_MANAGE_REPAIR,
        CAN_CLOSE_REPAIR,
        CAN_RECORD_INSPECTION,
        CAN_EDIT_VEHICLE_REGISTRATION,
        CAN_TRANSFER_VEHICLE_BRANCH,
        CAN_CORRECT_BRANCH_HISTORY,
        CAN_TRANSFER_EQUIPMENT_BRANCH,
        CAN_MANAGE_PERSONNEL,
        CAN_MANAGE_DEPARTMENT,
        CAN_LINK_PERSONNEL_TECHNICIAN,
        CAN_LINK_PERSONNEL_ACCOUNT,
        CAN_ASSIGN_EQUIPMENT_CARETAKER,
    }
)

# ---------------------------------------------------------------------------
# Core-phase dev role -> capability mapping. PROVISIONAL — see module
# docstring. Role names themselves are not a frozen vocabulary either;
# they exist only so `DEV_AUTH_MODE` can simulate a handful of clearly
# distinct actors (`X-Dev-Role` header — see `app.context`).
# ---------------------------------------------------------------------------

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "ADMIN": ALL_CAPABILITIES,
    "MAINTENANCE": frozenset(
        {
            CAN_VIEW,
            CAN_MANAGE_PM,
            CAN_REPORT_REPAIR,
            CAN_MANAGE_REPAIR,
            CAN_CLOSE_REPAIR,
            CAN_RECORD_INSPECTION,
        }
    ),
    "SUPERVISOR": frozenset(
        {
            CAN_VIEW,
            CAN_MANAGE_PM,
            CAN_REPORT_REPAIR,
            CAN_MANAGE_REPAIR,
            CAN_CLOSE_REPAIR,
            CAN_RECORD_INSPECTION,
        }
    ),
    "TECHNICIAN": frozenset({CAN_VIEW, CAN_REPORT_REPAIR, CAN_RECORD_INSPECTION}),
    "DRIVER": frozenset({CAN_VIEW, CAN_REPORT_REPAIR, CAN_RECORD_INSPECTION}),
    # Phase 7 Batch 7O2b/7O2c (contract Final Rev2 §3.1, E2): the dev role for
    # the registry editors — can_view plus the three registry capabilities.
    # Deliberately none of the PM/repair/inspection capabilities; MAINTENANCE
    # and SUPERVISOR are not widened.
    # R2 Batch R2d: plus the equipment branch-assignment capability (provisional).
    "MAINTENANCE_MANAGER": frozenset(
        {
            CAN_VIEW,
            CAN_EDIT_VEHICLE_REGISTRATION,
            CAN_TRANSFER_VEHICLE_BRANCH,
            CAN_CORRECT_BRANCH_HISTORY,
            CAN_TRANSFER_EQUIPMENT_BRANCH,
            # R2 Batch R2e (provisional): personnel / department lifecycle.
            CAN_MANAGE_PERSONNEL,
            CAN_MANAGE_DEPARTMENT,
            # R2 Batch R2f-b (owner-approved): Personnel ↔ Technician link.
            CAN_LINK_PERSONNEL_TECHNICIAN,
            # R2 Batch R2f-c (owner-approved): Personnel ↔ User Account link.
            CAN_LINK_PERSONNEL_ACCOUNT,
            # R2 Batch R2f-d (owner-approved, provisional): equipment caretaker periods.
            CAN_ASSIGN_EQUIPMENT_CARETAKER,
        }
    ),
}


def capabilities_for_roles(roles: tuple[str, ...]) -> frozenset[str]:
    """Union of every named role's capabilities. An unrecognized role name
    grants nothing (fails closed) rather than raising — a request context
    should never be constructible in a half-broken state."""
    result: set[str] = set()
    for role in roles:
        result |= ROLE_CAPABILITIES.get(role, frozenset())
    return frozenset(result)


def require_capability(
    context: "RequestContext", capability: str, action_description: str
) -> None:
    """Raise 403 unless `context` was granted `capability`. Backend
    authorization is authoritative here — a hidden frontend button is
    never a substitute (REV05 section 10)."""
    if capability not in context.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{action_description} requires the '{capability}' capability",
        )


def require_assignment_or_capability(
    context: "RequestContext",
    capability: str,
    primary_technician: str | None,
    collaborators: Sequence[str],
    action_description: str,
) -> None:
    """Core Demo Fixes Delta REV06 sections 12/13 (P1): recording work
    against a specific Repair/PM Work Order requires either being that
    occurrence's own active PRIMARY technician or an active COLLABORATOR
    (`primary_technician`/`collaborators`, kept in sync by
    `assign_repair`/`assign_pm_work_order` with the append-only assignment
    history — see `app.domain.assignment`), or holding `capability`
    (`can_manage_repair`/`can_manage_pm`) so Maintenance may always record
    on any occurrence. An actor with neither is refused even though they
    may be authenticated and hold other capabilities — being assigned to a
    DIFFERENT repair/work order never grants access to this one."""
    if capability in context.capabilities:
        return
    user_id = context.user_id
    if user_id is not None and (user_id == primary_technician or user_id in collaborators):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"{action_description} requires being the assigned PRIMARY/COLLABORATOR "
            f"or the '{capability}' capability"
        ),
    )


# ---------------------------------------------------------------------------
# Retained for compatibility with existing call sites not yet migrated to a
# specific capability (REV03 and earlier). New code should use
# `require_capability` with one of the 6 named capabilities above instead.
# ---------------------------------------------------------------------------

SUPERVISORY_ROLES = frozenset({"ADMIN", "SUPERVISOR", "MAINTENANCE_MANAGER", "MAINTENANCE"})


def require_supervisory_role(context: "RequestContext", action_description: str) -> None:
    if not (set(context.roles) & SUPERVISORY_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{action_description} requires an authorized maintenance/supervisory role",
        )
