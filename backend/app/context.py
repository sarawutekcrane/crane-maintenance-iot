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
from app.domain.authz import capabilities_for_roles

REQUEST_ID_HEADER = "X-Request-Id"
DEV_USER_ID = "dev-user"
DEV_USER_ROLES = ("ADMIN",)

# Core Demo Fixes Delta REV05: no real login/`user_account` read exists
# yet, so `DEV_AUTH_MODE` needs a way to simulate distinct actors (a
# reporter without Maintenance authority vs. an authorized Maintenance
# actor) for manual walkthroughs and tests. These headers are honored ONLY
# while `settings.dev_auth_effective` is True (REV06 section 11: fails
# closed — off by default, and even when explicitly enabled only takes
# effect inside a recognized local/development/test APP_ENV) —
# `app.main` additionally refuses to even start the process with
# `DEV_AUTH_MODE=true` outside a recognized environment, so this can
# never reach a real deployment. Absent, behavior is byte-for-byte the
# same as before REV05 (fixed `dev-user` / `ADMIN`), so no prior
# test/behavior changes just from this existing.
DEV_ROLE_HEADER = "X-Dev-Role"
DEV_USER_ID_HEADER = "X-Dev-User-Id"


@dataclass(frozen=True)
class RequestContext:
    """Minimal user/request context available to route handlers.

    Later phases (audit log, RBAC) extend this without breaking the shape
    already relied upon: request_id, user_id, roles, is_dev_auth.

    `capabilities` (REV05) is the set of `role_permission`-style
    capability names (see `app.domain.authz`) this actor holds — derived
    from `roles` today since no real per-user `role_permission` row is
    read anywhere yet; a later phase can populate it from a real lookup
    without changing any call site that already reads
    `context.capabilities`.
    """

    request_id: str
    user_id: str | None
    roles: tuple[str, ...] = field(default_factory=tuple)
    is_dev_auth: bool = False
    capabilities: frozenset[str] = field(default_factory=frozenset)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attaches a request_id and a RequestContext to every request."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        if self._settings.dev_auth_effective:
            dev_role_header = request.headers.get(DEV_ROLE_HEADER)
            roles = (dev_role_header,) if dev_role_header else DEV_USER_ROLES
            user_id = request.headers.get(DEV_USER_ID_HEADER) or DEV_USER_ID
            context = RequestContext(
                request_id=request_id,
                user_id=user_id,
                roles=roles,
                is_dev_auth=True,
                capabilities=capabilities_for_roles(roles),
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
