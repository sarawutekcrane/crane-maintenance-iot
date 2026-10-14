"""GET /me — the current actor's capabilities (Core Demo Fixes Delta
REV05 section 10). No real login exists yet (`DEV_AUTH_MODE`); this
exposes exactly what `app.context.RequestContext` already computed so the
frontend never re-derives a role->capability mapping of its own.

R2 Batch R2f-h4 precondition (owner decision D-H4-1): two additive,
read-only server facts for the frontend — the ACTUAL
`TECHNICIAN_ASSIGNMENT_V2_ENABLED` setting (through the same
`cutover_from_settings` every V2 route uses) and the effective registry data
context (`REAL` / `TEST` / `UNCONFIGURED`, never REAL unless the server's
setting is exactly REAL). Nothing here can change either value; they are
informational and replace neither authorization nor TEST/REAL isolation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.me_schemas import MeResponse
from app.config import Settings
from app.context import RequestContext
from app.dependencies import get_current_context, get_settings_dependency
from app.domain.read_signals import data_context_signal
from app.domain.technician_assignment import cutover_from_settings

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
async def get_me(
    context: RequestContext = Depends(get_current_context),
    settings: Settings = Depends(get_settings_dependency),
) -> MeResponse:
    cutover = cutover_from_settings(settings)
    return MeResponse(
        user_id=context.user_id,
        roles=list(context.roles),
        capabilities=sorted(context.capabilities),
        technician_assignment_v2_enabled=cutover.enabled,
        data_context=data_context_signal(cutover.data_context),  # type: ignore[arg-type]
    )
