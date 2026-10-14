from __future__ import annotations

from pydantic import BaseModel

from app.api.v1.read_signal_schemas import DataContextSignal


class MeResponse(BaseModel):
    """Core Demo Fixes Delta REV05 section 10: lets the frontend drive
    navigation/action visibility from the actor's actual capabilities
    instead of a hard-coded role->screen matrix. Backend authorization
    (`app.domain.authz.require_capability`) remains authoritative for
    every write action regardless of what this reports — this endpoint
    only helps the UI decide what to *show*."""

    user_id: str | None
    roles: list[str]
    capabilities: list[str]
    data_context: DataContextSignal
    """R2 Batch R2f-h4 precondition (D-H4-1 / D-H4-6): the server's effective
    registry data context — "REAL" only when the server is configured exactly
    REAL, "TEST" (mock mode is always TEST), otherwise "UNCONFIGURED".
    Informational: never a substitute for server-side authorization or
    TEST/REAL isolation."""
