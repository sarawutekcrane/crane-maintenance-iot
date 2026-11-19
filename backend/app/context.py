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
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
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
    # Access Management mode only (app.domain.access_management): the acting
    # employee resolved server-side from the account link, and the actor's
    # permission-administration authority. Both stay None in legacy mode.
    personnel_id: str | None = None
    access: object | None = None


# R8 PRE-UAT H1-DIRECT (Owner source approval Gate A, 2026-11-19, path #98): in the TEST hosted
# identity-proxy mode every `/api` request needs a verified, mapped identity, except the data-free
# health probe. Refused before routing, so no handler (and no anonymous read) runs.
IDENTITY_PROXY_OPEN_ROUTES = frozenset({("GET", "/api/v1/health")})
IDENTITY_REQUIRED_CODE = "IAP_IDENTITY_REQUIRED"


def routed_path(scope) -> str:
    """The path the router matches (Starlette strips a configured ``root_path`` prefix before routing), so
    the fence always judges exactly what will be routed, whatever ``--root-path`` the server runs with."""
    path, root = scope.get("path", ""), scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root):]
    return path or "/"


def identity_proxy_requires_identity(method: str, path: str) -> bool:
    if (method.upper(), path) in IDENTITY_PROXY_OPEN_ROUTES:
        return False
    return path == "/api" or path.startswith("/api/")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attaches a request_id and a RequestContext to every request."""

    def __init__(self, app: ASGIApp, settings: Settings, identity_proxy: object | None = None) -> None:
        super().__init__(app)
        self._settings = settings
        # app.domain.test_identity_proxy.IdentityProxy, built and validated at startup by app.main
        # only when settings.identity_proxy_enabled; None in every other mode (unchanged behavior).
        self._identity_proxy = identity_proxy

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        if self._identity_proxy is not None:
            from app.domain.test_identity_proxy import IAP_ASSERTION_HEADER

            # ONLY the signed IAP assertion is read; X-Dev-* and x-goog-authenticated-user-* are
            # ignored. No role is ever granted (so no development-table capability and no technical
            # recovery); Access Management derives capabilities from per-employee grants.
            user_id = await run_in_threadpool(self._identity_proxy.identify,
                                              request.headers.get(IAP_ASSERTION_HEADER))
            if user_id is None and identity_proxy_requires_identity(request.method, routed_path(request.scope)):
                from app.errors import build_error_envelope

                return JSONResponse(
                    status_code=401,
                    content=build_error_envelope(
                        IDENTITY_REQUIRED_CODE,
                        "A verified, approved TEST identity is required for this request",
                        request_id,
                    ),
                    headers={REQUEST_ID_HEADER: request_id},
                )
            context = RequestContext(request_id=request_id, user_id=user_id, roles=())
        elif self._settings.dev_auth_effective:
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
