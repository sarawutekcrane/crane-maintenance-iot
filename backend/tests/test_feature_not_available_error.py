"""Final Cross-Phase Integration Fix — F3: explicit unsupported-repository
error.

Historically, several Google Sheets repository methods (Inspection/
Finding, most PM, Part/Lifetime) were intentionally still-stubbed (REV05
section 11E), calling `_require_configured` to raise a controlled,
explicit `RepositoryFeatureNotImplementedError` instead of a bare
`NotImplementedError` the global exception handler would otherwise
convert into a generic `INTERNAL_ERROR` indistinguishable from an actual
programming defect.

The Google Sheets repository completion pass (see
`tests/test_google_sheets_repository_completion.py`) implemented every
one of those stubs with real I/O, so no repository method raises this
error in ordinary operation anymore. `_require_configured` itself
remains as the one deliberately-kept escape hatch for a genuinely
unavailable repository-mode feature (and is exercised directly below);
these tests prove the mechanism — the `_require_configured` helper and
`app.errors`'s mapping of `RepositoryFeatureNotImplementedError` to a
distinct, stable `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` API error
(HTTP 501) — still works, using a small stand-in repository rather than
asserting a production method is still unimplemented.
"""
from __future__ import annotations

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.domain.common import PageParams
from app.repositories.base import RepositoryError, RepositoryFeatureNotImplementedError
from app.repositories.google_sheets import GoogleSheetsRepository
from tests.test_google_sheets_real_io import _configured_settings


def _repo() -> GoogleSheetsRepository:
    return GoogleSheetsRepository(_configured_settings())


class _StillUnavailableRepository(GoogleSheetsRepository):
    """Stands in for a genuinely unavailable repository-mode feature —
    mirrors exactly the shape every true stub used to have — without
    relying on any production method remaining unimplemented."""

    async def list_pm_work_orders(self, *args, **kwargs):
        self._require_configured("pm_work_order")


# ---------------------------------------------------------------------------
# Repository-level: `_require_configured` itself raises the explicit type.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_configured_raises_the_explicit_feature_error() -> None:
    repo = _repo()
    with pytest.raises(RepositoryFeatureNotImplementedError) as excinfo:
        repo._require_configured("some_feature")
    assert excinfo.value.feature == "some_feature"
    # Never a coding-defect NotImplementedError masquerading as this.
    assert isinstance(excinfo.value, RepositoryError)


@pytest.mark.asyncio
async def test_require_configured_still_checks_configuration_first() -> None:
    from app.config import Settings

    unconfigured = GoogleSheetsRepository(
        Settings(google_sheet_id="", google_application_credentials="")
    )
    with pytest.raises(RepositoryError) as excinfo:
        unconfigured._require_configured("some_feature")
    # Unconfigured credentials is reported as a plain RepositoryError, not
    # the more specific "known, intentional gap" subclass.
    assert not isinstance(excinfo.value, RepositoryFeatureNotImplementedError)


@pytest.mark.asyncio
async def test_no_true_stub_remains_in_the_google_sheets_repository() -> None:
    """Companion, in-module check to the AST regression test in
    `tests/test_google_sheets_repository_completion.py`: every domain
    entry point on `GoogleSheetsRepository` performs real I/O once
    configured — proven here for a representative method from each
    previously-stubbed group instead of asserting any of them still
    raises `RepositoryFeatureNotImplementedError`."""
    from tests.test_google_sheets_real_io import _repo_with_fake_sheets, _ws
    from app.domain.asset import AssetType
    from app.repositories.google_sheets import schemas

    repo = _repo_with_fake_sheets(
        _ws(schemas.PM_WORK_ORDER_SHEET),
        _ws(schemas.PM_WORK_SCOPE_SHEET),
        _ws(schemas.PM_WORK_ASSIGNMENT_SHEET),
        _ws(schemas.PM_WORK_RESULT_SHEET),
    )
    items, total = await repo.list_pm_work_orders(
        asset_type=AssetType.VEHICLE, asset_id="VEH-1", params=PageParams()
    )
    assert items == []
    assert total == 0


# ---------------------------------------------------------------------------
# API-level: the exception handler maps this to a distinct 501 error code,
# not the generic INTERNAL_ERROR an unrecognized exception gets.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feature_not_available_maps_to_a_distinct_api_error() -> None:
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    def _still_unavailable_repo() -> _StillUnavailableRepository:
        return _StillUnavailableRepository(_configured_settings())

    app = create_app()
    app.dependency_overrides[get_repository] = _still_unavailable_repo
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1/pm/work-orders",
                params={"asset_type": "VEHICLE", "asset_id": "VEH-1"},
                headers={"X-Dev-Role": "MAINTENANCE"},
            )
    finally:
        app.dependency_overrides.clear()
        reset_dependency_cache()

    assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
    body = response.json()
    assert body["error"]["code"] == "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE"
    # User-safe: no Python class names, module paths, or stack traces.
    assert "NotImplementedError" not in body["error"]["message"]
    assert "app.repositories" not in body["error"]["message"]
    assert "Traceback" not in body["error"]["message"]


@pytest.mark.asyncio
async def test_unexpected_exception_still_maps_to_internal_error(client: AsyncClient) -> None:
    """An arbitrary programming defect (never
    `RepositoryFeatureNotImplementedError`) must remain the generic,
    unrecognized-failure `INTERNAL_ERROR` — F3 narrows the one known,
    intentional stub condition; it must not blindly reclassify every
    exception as a friendly "feature not available" message."""
    from app.dependencies import get_pm_service
    from app.main import create_app

    async def _boom():
        class _Boom:
            async def list_applicable_plan_status(self, *args, **kwargs):
                raise ValueError("this is an ordinary, unexpected programming defect")

        return _Boom()

    real_app = create_app()
    real_app.dependency_overrides[get_pm_service] = _boom
    # ServerErrorMiddleware always re-raises the original exception after
    # building the handler's response (so a test client can opt in to
    # seeing it) — raise_app_exceptions=False opts out, so this asserts
    # against the actual HTTP response the client sees.
    transport = ASGITransport(app=real_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get(
            "/api/v1/pm/plans/status",
            params={"asset_type": "VEHICLE", "asset_id": "VEH-1"},
            headers={"X-Dev-Role": "MAINTENANCE"},
        )
    real_app.dependency_overrides.clear()

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
