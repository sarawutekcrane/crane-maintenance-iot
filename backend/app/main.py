"""FastAPI application factory.

Also runs `uvicorn app.main:app --reload` for local development.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.config import get_settings
from app.context import RequestContextMiddleware
from app.errors import register_exception_handlers


def create_app() -> FastAPI:
    settings = get_settings()

    logging.basicConfig(level=settings.log_level)
    logger = logging.getLogger("app")

    if settings.dev_auth_mode and not settings.is_recognized_dev_environment:
        # REV06 section 11 (P0 — dev auth must fail closed): refuse to even
        # start, not just when APP_ENV is literally "production" (the old
        # guard) but for ANY unrecognized value — unset, misspelled, or a
        # real environment name this codebase doesn't know about
        # (e.g. "staging"). Relying only on `== "production"` is exactly
        # the gap the independent REV05 audit found.
        from app.config import DEV_AUTH_ALLOWED_ENVIRONMENTS

        raise RuntimeError(
            "DEV_AUTH_MODE=true is only allowed when APP_ENV is one of: "
            f"{', '.join(sorted(DEV_AUTH_ALLOWED_ENVIRONMENTS))}. "
            f"Got APP_ENV='{settings.app_env}'. Set DEV_AUTH_MODE=false and "
            "configure real authentication, or use a recognized local/"
            "development/test environment."
        )

    identity_proxy = None
    docs_kwargs: dict[str, None] = {}
    if settings.identity_proxy_enabled:
        # R8 PRE-UAT H1-DIRECT (Owner source approval Gate A, 2026-11-19): TEST hosted mode behind Cloud
        # Run Direct IAP. Built and validated here, at startup (bad audience / map / unknown synthetic
        # account -> the process refuses to start). The interactive API docs are not served in this mode.
        from app.domain.test_identity_proxy import build_identity_proxy

        identity_proxy = build_identity_proxy(settings.test_iap_audience, settings.test_identity_map)
        docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}

    app = FastAPI(
        title="Crane Fleet Maintenance API",
        version="0.1.0",
        description=(
            "Backend API for the Crane Fleet Maintenance / IoT platform. "
            "Web/business API is versioned under /api/v1."
        ),
        **docs_kwargs,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_base_url, "http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware, settings=settings, identity_proxy=identity_proxy)

    register_exception_handlers(app)

    app.include_router(api_v1_router)
    if settings.pm_master_test_profile:
        # R8 PRE-UAT SG-PM (Owner Consolidated Source Expansion Gate 2026-11-18, path #96): the PM Master
        # TEST profile routes exist ONLY when the TEST-only flag is on (the config validator allows it only
        # with Mock + Access Management + non-production). Imported lazily here so the default application
        # never loads the PM Master (B1 firewall); its default route table is unchanged.
        from fastapi import Depends

        from app.api.v1.pm_master_test_routes import router as pm_master_test_router
        from app.dependencies import access_management_write_policy

        # The same D6 write policy as every other /api/v1 route (verified employee for every write).
        app.include_router(pm_master_test_router, prefix="/api/v1",
                           dependencies=[Depends(access_management_write_policy)])

    if identity_proxy is not None and settings.test_spa_dir:
        _serve_test_spa(app, settings.test_spa_dir)
        logger.warning("TEST_IDENTITY_PROXY=google_iap: TEST hosted mode (Direct IAP identity, synthetic data only).")

    if settings.dev_auth_effective:
        logger.warning(
            "DEV_AUTH_MODE is enabled: requests run as a fixed development "
            "user with ADMIN role. This mode must never be enabled in production."
        )

    return app


def _serve_test_spa(app: FastAPI, spa_dir: str) -> None:
    """R8 PRE-UAT H1-DIRECT: serve the built frontend on the same origin, ONLY as the router's
    no-route fallback, so every API status stays exactly as before (an unknown `/api` path or a
    non-GET/HEAD method keeps the JSON 404; a known path with the wrong method keeps its 405).
    A file is served only when its resolved path stays inside the SPA directory; any other client
    route gets `index.html`. No directory listing."""
    from pathlib import Path

    from starlette.responses import FileResponse

    root = Path(spa_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError("TEST_SPA_DIR must contain the built frontend index.html")
    not_found = app.router.default

    async def spa_fallback(scope, receive, send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or scope.get("method") not in ("GET", "HEAD") \
                or path == "/api" or path.startswith("/api/"):
            await not_found(scope, receive, send)
            return
        relative = path.lstrip("/")
        target = index
        if relative:
            try:
                candidate = (root / relative).resolve()
            except (OSError, ValueError):
                await not_found(scope, receive, send)
                return
            if not candidate.is_relative_to(root):
                await not_found(scope, receive, send)
                return
            if candidate.is_file():
                target = candidate
        headers = {"Cache-Control": "no-cache"} if target == index else None
        await FileResponse(target, headers=headers)(scope, receive, send)

    app.router.default = spa_fallback


app = create_app()
