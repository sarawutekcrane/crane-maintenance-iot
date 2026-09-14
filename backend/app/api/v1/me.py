"""GET /me — the current actor's capabilities (Core Demo Fixes Delta
REV05 section 10). No real login exists yet (`DEV_AUTH_MODE`); this
exposes exactly what `app.context.RequestContext` already computed so the
frontend never re-derives a role->capability mapping of its own.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.me_schemas import MeResponse
from app.context import RequestContext
from app.dependencies import get_current_context

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
async def get_me(context: RequestContext = Depends(get_current_context)) -> MeResponse:
    return MeResponse(
        user_id=context.user_id,
        roles=list(context.roles),
        capabilities=sorted(context.capabilities),
    )
