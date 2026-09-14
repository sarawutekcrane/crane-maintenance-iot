"""Development-safe capability gate shared by routes that need an
"authorized maintenance/supervisory" check without inventing a production
RBAC matrix (OPEN_DECISIONS_REGISTER_EN.txt M02 remains unresolved).

Reuses the existing `RequestContext.roles` abstraction from Phase 1
(`DEV_AUTH_MODE` grants the fixed development user an `ADMIN` role) rather
than adding a new permission system. Used by "งานซ่อมค้าง" (Open Repair
Queue) and PM scope approval/manual-addition — both explicitly called out
in the Core Demo Fixes prompt as needing "authorized...use" /
"appropriate PM scope authority" without a real permission matrix.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.context import RequestContext

SUPERVISORY_ROLES = frozenset({"ADMIN", "SUPERVISOR", "MAINTENANCE_MANAGER"})


def require_supervisory_role(context: RequestContext, action_description: str) -> None:
    if not (set(context.roles) & SUPERVISORY_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{action_description} requires an authorized maintenance/supervisory role",
        )
