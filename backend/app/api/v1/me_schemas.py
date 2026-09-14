from __future__ import annotations

from pydantic import BaseModel


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
