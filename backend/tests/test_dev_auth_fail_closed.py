"""Core Demo Fixes Delta REV06 section 11 (P0) — dev-header actor spoofing
must fail closed.

The independent REV05 audit found that gating `X-Dev-Role`/`X-Dev-User-Id`
spoofing on `settings.is_production` alone left an unset, misspelled, or
otherwise-unrecognized `APP_ENV` value free to activate `DEV_AUTH_MODE`.
REV06 changes the default to `dev_auth_mode=False` and requires the flag to
ALSO sit inside a recognized local/development/test `APP_ENV`
(`settings.dev_auth_effective` — see `app.config`) before dev headers do
anything at all; `app.main.create_app` additionally refuses to even start
the process when `DEV_AUTH_MODE=true` sits outside a recognized
environment, so no server can ever come up in the vulnerable state the
audit described.

These tests construct `Settings`/`RequestContextMiddleware` directly
(bypassing the `client` fixture's explicit `DEV_AUTH_MODE=true`/
`APP_ENV=development` environment overrides — see `tests/conftest.py`) so
the fail-closed default and the environment gate are proven independently
of the rest of the test suite's own explicit opt-in.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import Settings
from app.context import DEV_ROLE_HEADER, DEV_USER_ID_HEADER, RequestContextMiddleware


@contextmanager
def _without_env_overrides() -> Iterator[None]:
    """`tests/conftest.py` sets `DEV_AUTH_MODE=true`/`APP_ENV=development`
    as *process* environment defaults so the rest of this test suite (via
    the `client` fixture) can exercise dev-header actor simulation.
    `pydantic-settings` reads real environment variables regardless of the
    `_env_file=None` override passed below, so a genuine "what does a
    fresh deployment with NO configuration see" test must temporarily lift
    those two process-wide defaults rather than rely on constructor
    defaults alone."""
    saved = {k: os.environ.get(k) for k in ("DEV_AUTH_MODE", "APP_ENV")}
    for key in saved:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value


def _echo_context_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, settings=settings)

    @app.get("/whoami")
    async def whoami(request: Request) -> JSONResponse:
        context = request.state.context
        return JSONResponse(
            {
                "user_id": context.user_id,
                "roles": list(context.roles),
                "is_dev_auth": context.is_dev_auth,
                "capabilities": sorted(context.capabilities),
            }
        )

    return app


async def _whoami(settings: Settings, headers: dict[str, str] | None = None) -> dict:
    app = _echo_context_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/whoami", headers=headers or {})
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# 1 — default configuration does NOT permit dev spoofing.
# ---------------------------------------------------------------------------


def test_dev_auth_mode_defaults_to_false() -> None:
    with _without_env_overrides():
        settings = Settings(_env_file=None)
        assert settings.dev_auth_mode is False


def test_default_settings_never_grant_dev_auth_even_in_default_app_env() -> None:
    # APP_ENV also defaults to "development" (a recognized dev environment)
    # — proves the fix is the `dev_auth_mode` default, not merely an
    # environment mismatch.
    with _without_env_overrides():
        settings = Settings(_env_file=None)
        assert settings.app_env == "development"
        assert settings.is_recognized_dev_environment is True
        assert settings.dev_auth_effective is False


@pytest.mark.asyncio
async def test_default_settings_ignore_dev_headers_end_to_end() -> None:
    with _without_env_overrides():
        settings = Settings(_env_file=None)
    body = await _whoami(
        settings, headers={DEV_ROLE_HEADER: "ADMIN", DEV_USER_ID_HEADER: "attacker"}
    )
    assert body["is_dev_auth"] is False
    assert body["user_id"] is None
    assert body["roles"] == []
    assert body["capabilities"] == []


# ---------------------------------------------------------------------------
# 2 — explicit development mode allows dev headers.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_development_mode_allows_dev_headers() -> None:
    settings = Settings(_env_file=None, dev_auth_mode=True, app_env="development")
    assert settings.dev_auth_effective is True
    body = await _whoami(
        settings, headers={DEV_ROLE_HEADER: "MAINTENANCE", DEV_USER_ID_HEADER: "user-maint-1"}
    )
    assert body["is_dev_auth"] is True
    assert body["user_id"] == "user-maint-1"
    assert body["roles"] == ["MAINTENANCE"]
    assert "can_manage_repair" in body["capabilities"]


@pytest.mark.asyncio
async def test_explicit_local_and_test_environments_also_allow_dev_headers() -> None:
    for env in ("local", "test", "LOCAL", "Test"):
        settings = Settings(_env_file=None, dev_auth_mode=True, app_env=env)
        assert settings.dev_auth_effective is True, env


# ---------------------------------------------------------------------------
# 3 — unknown/unset production-like environment cannot silently enable
# spoofing: the process refuses to even start.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_env", ["production", "staging", "prod", "Production", "PROD-EU"])
def test_dev_auth_mode_true_outside_recognized_environment_refuses_to_start(bad_env: str) -> None:
    import os

    from app.config import get_settings
    from app.dependencies import reset_dependency_cache
    from app.main import create_app

    original_env = {k: os.environ.get(k) for k in ("DEV_AUTH_MODE", "APP_ENV")}
    os.environ["DEV_AUTH_MODE"] = "true"
    os.environ["APP_ENV"] = bad_env
    get_settings.cache_clear()
    reset_dependency_cache()
    try:
        with pytest.raises(RuntimeError, match="DEV_AUTH_MODE=true is only allowed"):
            create_app()
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        reset_dependency_cache()


def test_settings_object_alone_reports_not_effective_for_unrecognized_env() -> None:
    # Same guarantee at the Settings level, independent of `create_app`'s
    # additional hard-refusal — belt and suspenders (REV06: "no hidden
    # bypass").
    for bad_env in ("production", "staging", "", "  ", "prodution"):  # incl. a plausible typo
        settings = Settings(_env_file=None, dev_auth_mode=True, app_env=bad_env)
        assert settings.dev_auth_effective is False, bad_env


# ---------------------------------------------------------------------------
# 4-5 — disabled dev mode ignores/refuses X-Dev-Role / X-Dev-User-Id.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_dev_mode_ignores_x_dev_role_header() -> None:
    settings = Settings(_env_file=None, dev_auth_mode=False, app_env="development")
    body = await _whoami(settings, headers={DEV_ROLE_HEADER: "ADMIN"})
    assert body["is_dev_auth"] is False
    assert body["roles"] == []
    assert "can_manage_repair" not in body["capabilities"]


@pytest.mark.asyncio
async def test_disabled_dev_mode_ignores_x_dev_user_id_header() -> None:
    settings = Settings(_env_file=None, dev_auth_mode=False, app_env="development")
    body = await _whoami(settings, headers={DEV_USER_ID_HEADER: "someone-else"})
    assert body["is_dev_auth"] is False
    assert body["user_id"] is None


@pytest.mark.asyncio
async def test_disabled_dev_mode_grants_no_capabilities_regardless_of_headers() -> None:
    settings = Settings(_env_file=None, dev_auth_mode=False, app_env="development")
    body = await _whoami(
        settings, headers={DEV_ROLE_HEADER: "ADMIN", DEV_USER_ID_HEADER: "would-be-admin"}
    )
    assert body["capabilities"] == []
    assert body["is_dev_auth"] is False
