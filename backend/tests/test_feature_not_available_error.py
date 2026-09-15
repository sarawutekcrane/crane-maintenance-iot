"""Final Cross-Phase Integration Fix — F3: explicit unsupported-repository
error.

Several Google Sheets repository methods (Inspection/Finding, most PM,
Part/Lifetime) are intentionally still-stubbed (REV05 section 11E) and
used to raise a bare `NotImplementedError`, which the global exception
handler converted into a generic `INTERNAL_ERROR` indistinguishable from
an actual programming defect. `_require_configured` now raises the
explicit `RepositoryFeatureNotImplementedError`, which `app.errors` maps
to a distinct, stable `FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE` API error
(HTTP 501) — while an arbitrary, unrecognized exception still falls
through to `INTERNAL_ERROR` unchanged.
"""
from __future__ import annotations

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.domain.asset import AssetType
from app.domain.common import PageParams
from app.repositories.base import RepositoryError, RepositoryFeatureNotImplementedError
from app.repositories.google_sheets import GoogleSheetsRepository
from tests.test_google_sheets_real_io import _configured_settings


def _repo() -> GoogleSheetsRepository:
    """A GoogleSheetsRepository whose client reports itself configured but
    is never actually called (every method under test raises before doing
    any I/O), mirroring exactly the "configured, but this operation is
    still a stub" condition these tests exist to prove."""
    return GoogleSheetsRepository(_configured_settings())


# ---------------------------------------------------------------------------
# Repository-level: each still-stubbed domain raises the explicit type.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_pm_sheets_operation_raises_the_explicit_feature_error() -> None:
    repo = _repo()
    with pytest.raises(RepositoryFeatureNotImplementedError) as excinfo:
        await repo.list_pm_work_orders(
            asset_type=AssetType.VEHICLE, asset_id="VEH-1", params=PageParams()
        )
    assert excinfo.value.feature == "pm_work_order"
    # Never a coding-defect NotImplementedError masquerading as this.
    assert isinstance(excinfo.value, RepositoryError)


@pytest.mark.asyncio
async def test_unsupported_inspection_sheets_operation_raises_the_explicit_feature_error() -> None:
    repo = _repo()
    with pytest.raises(RepositoryFeatureNotImplementedError) as excinfo:
        await repo.get_inspection("INS-0001")
    assert excinfo.value.feature == "inspection_header"


@pytest.mark.asyncio
async def test_unsupported_part_lifetime_sheets_operation_raises_the_explicit_feature_error() -> None:
    repo = _repo()
    with pytest.raises(RepositoryFeatureNotImplementedError) as excinfo:
        await repo.get_part_master("PM-0001")
    assert excinfo.value.feature == "part_master"

    with pytest.raises(RepositoryFeatureNotImplementedError) as excinfo2:
        await repo.get_position_lifetime("POSLT-0001")
    assert excinfo2.value.feature == "position_lifetime_records"


# ---------------------------------------------------------------------------
# API-level: the exception handler maps this to a distinct 501 error code,
# not the generic INTERNAL_ERROR an unrecognized exception gets.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feature_not_available_maps_to_a_distinct_api_error() -> None:
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_repository] = _repo
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
