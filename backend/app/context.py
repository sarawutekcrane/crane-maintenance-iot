"""Request / user context boundary.

Frozen in Phase 1: every request carries a request_id (for error envelopes
and future audit logging) and a RequestContext with the acting user. Full
RBAC/authentication is implemented in the hardening phase; for now,
DEV_AUTH_MODE injects a clearly-marked development user so downstream
domain/service code can already depend on `RequestContext` existing.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import Settings

REQUEST_ID_HEADER = "X-Request-Id"
DEV_USER_ID = "dev-user"
DEV_USER_ROLES = ("ADMIN",)


@dataclass(frozen=True)
class RequestContext:
    """Minimal user/request context available to route handlers.

    Later phases (audit log, RBAC) extend this without breaking the shape
    already relied upon: request_id, user_id, roles, is_dev_auth.
    """

    request_id: str
    user_id: str | None
    roles: tuple[str, ...] = field(default_factory=tuple)
    is_dev_auth: bool = False


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attaches a request_id and a RequestContext to every request."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        if self._settings.dev_auth_mode:
            context = RequestContext(
                request_id=request_id,
                user_id=DEV_USER_ID,
                roles=DEV_USER_ROLES,
                is_dev_auth=True,
            )
        else:
            # Real authentication is implemented in the hardening phase.
            context = RequestContext(request_id=request_id, user_id=None, roles=())

        request.state.request_id = request_id
        request.state.context = context

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def get_request_context(request: Request) -> RequestContext:
    return request.state.context
