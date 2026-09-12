from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.common import PageParams
from app.domain.vehicle_service import VehicleService
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import GoogleSheetsRepository


@pytest.mark.asyncio
async def test_not_ready_when_unconfigured() -> None:
    settings = Settings(google_sheet_id="", google_application_credentials="")
    repo = GoogleSheetsRepository(settings)
    ready, reason = await repo.check_ready()
    assert ready is False
    assert reason is not None
    assert repo.mode == "google_sheets"


@pytest.mark.asyncio
async def test_vehicle_domain_methods_report_not_configured_until_credentials_exist() -> None:
    """The domain/service layer must not know which repository backs it
    (docs/architecture/API_CONVENTIONS.md). `VehicleService` is exercised
    against `GoogleSheetsRepository` the same way it is against
    `MockRepository`; since no real Google credentials exist in this
    environment, the expected outcome is a controlled `RepositoryError`
    rather than a crash or a silently wrong result.
    """
    settings = Settings(google_sheet_id="", google_application_credentials="")
    service = VehicleService(GoogleSheetsRepository(settings))

    with pytest.raises(RepositoryError):
        await service.list_vehicles(
            q=None, operational_status=None, model_id=None, params=PageParams()
        )


@pytest.mark.asyncio
async def test_equipment_domain_methods_report_not_configured_until_credentials_exist() -> None:
    from app.domain.equipment_service import EquipmentService

    settings = Settings(google_sheet_id="", google_application_credentials="")
    service = EquipmentService(GoogleSheetsRepository(settings))

    with pytest.raises(RepositoryError):
        await service.list_equipment(q=None, category=None, params=PageParams())
