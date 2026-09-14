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

from typing import TYPE_CHECKING

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

ALL_CAPABILITIES = frozenset(
    {
        CAN_VIEW,
        CAN_MANAGE_PM,
        CAN_REPORT_REPAIR,
        CAN_MANAGE_REPAIR,
        CAN_CLOSE_REPAIR,
        CAN_RECORD_INSPECTION,
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
