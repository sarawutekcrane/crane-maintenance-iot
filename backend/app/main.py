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

    app = FastAPI(
        title="Crane Fleet Maintenance API",
        version="0.1.0",
        description=(
            "Backend API for the Crane Fleet Maintenance / IoT platform. "
            "Web/business API is versioned under /api/v1."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_base_url, "http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware, settings=settings)

    register_exception_handlers(app)

    app.include_router(api_v1_router)

    if settings.dev_auth_effective:
        logger.warning(
            "DEV_AUTH_MODE is enabled: requests run as a fixed development "
            "user with ADMIN role. This mode must never be enabled in production."
        )

    return app


app = create_app()
