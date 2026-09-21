"""Composition root: wires concrete implementations to interfaces based on
configuration. This is the ONLY place that should decide which
Repository/StorageProvider concrete class is active; domain/service code
and routes must depend on the abstract interfaces only.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Request

from app.config import DataRepositoryMode, FileStorageBackend, Settings, get_settings
from app.context import RequestContext, get_request_context
from app.domain.driver_service import DriverService
from app.domain.vehicle_certificate_service import VehicleCertificateService
from app.domain.model_document_service import ModelDocumentService
from app.domain.vehicle_event_service import VehicleEventService
from app.domain.daily_summary_service import DailySummaryService
from app.domain.equipment_service import EquipmentService
from app.domain.inspection_service import InspectionService
from app.domain.lifetime_rule_service import LifetimeRuleService
from app.domain.location_snapshot import LocationService
from app.domain.material_request_service import MaterialRequestService
from app.domain.meter_service import MeterService
from app.domain.notification import NoOpNotificationSink, NotificationPort
from app.domain.part_instance_service import PartInstanceService
from app.domain.part_service import PartService
from app.domain.pm_service import PmService
from app.domain.position_lifetime_service import PositionLifetimeService
from app.domain.repair_request_service import RepairRequestService
from app.domain.repair_service import RepairService
from app.domain.vehicle_service import VehicleService
from app.repositories.base import Repository
from app.repositories.google_sheets import GoogleSheetsRepository
from app.repositories.mock import MockRepository
from app.storage.base import StorageProvider
from app.storage.local import LocalFileStorageProvider


@lru_cache
def get_repository() -> Repository:
    settings = get_settings()
    if settings.data_repository == DataRepositoryMode.MOCK:
        return MockRepository()
    if settings.data_repository == DataRepositoryMode.GOOGLE_SHEETS:
        return GoogleSheetsRepository(settings)
    raise NotImplementedError(
        f"DATA_REPOSITORY={settings.data_repository.value} is not implemented yet "
        "(PostgreSQL arrives in a later phase)"
    )


@lru_cache
def get_storage_provider() -> StorageProvider:
    settings = get_settings()
    if settings.file_storage_backend == FileStorageBackend.LOCAL:
        return LocalFileStorageProvider(settings.local_upload_dir)
    raise NotImplementedError(
        f"FILE_STORAGE_BACKEND={settings.file_storage_backend.value} is not implemented yet"
    )


def reset_dependency_cache() -> None:
    """Test helper: clears cached singletons so tests can reconfigure settings."""
    get_repository.cache_clear()
    get_storage_provider.cache_clear()


def get_current_context(request: Request) -> RequestContext:
    return get_request_context(request)


def get_settings_dependency() -> Settings:
    return get_settings()


def get_vehicle_service(repository: Repository = Depends(get_repository)) -> VehicleService:
    return VehicleService(repository)


def get_equipment_service(repository: Repository = Depends(get_repository)) -> EquipmentService:
    return EquipmentService(repository)


def get_meter_service(repository: Repository = Depends(get_repository)) -> MeterService:
    return MeterService(repository)


def get_inspection_service(
    repository: Repository = Depends(get_repository),
    storage: StorageProvider = Depends(get_storage_provider),
    settings: Settings = Depends(get_settings_dependency),
    meter_service: MeterService = Depends(get_meter_service),
) -> InspectionService:
    return InspectionService(repository, storage, settings, meter_service)


def get_pm_service(
    repository: Repository = Depends(get_repository),
    meter_service: MeterService = Depends(get_meter_service),
) -> PmService:
    return PmService(repository, meter_service)


def get_notification_sink() -> NotificationPort:
    # Core Demo Fixes Delta REV05 section 7: integration-ready only — no
    # external LINE/Push/Email delivery exists in this Core branch. The
    # sole place a future Phase 6 notification implementation needs to
    # plug in.
    return NoOpNotificationSink()


def get_repair_service(
    repository: Repository = Depends(get_repository),
    meter_service: MeterService = Depends(get_meter_service),
    notification_sink: NotificationPort = Depends(get_notification_sink),
) -> RepairService:
    return RepairService(repository, meter_service, notification_sink)


def get_part_service(repository: Repository = Depends(get_repository)) -> PartService:
    return PartService(repository)


def get_part_instance_service(
    repository: Repository = Depends(get_repository),
    meter_service: MeterService = Depends(get_meter_service),
) -> PartInstanceService:
    return PartInstanceService(repository, meter_service)


def get_position_lifetime_service(
    repository: Repository = Depends(get_repository),
    meter_service: MeterService = Depends(get_meter_service),
) -> PositionLifetimeService:
    return PositionLifetimeService(repository, meter_service)


def get_lifetime_rule_service(
    repository: Repository = Depends(get_repository),
) -> LifetimeRuleService:
    return LifetimeRuleService(repository)


def get_material_request_service(
    repository: Repository = Depends(get_repository),
) -> MaterialRequestService:
    return MaterialRequestService(repository)


def get_location_service(repository: Repository = Depends(get_repository)) -> LocationService:
    return LocationService(repository)


def get_repair_request_service(
    repository: Repository = Depends(get_repository),
    repair_service: RepairService = Depends(get_repair_service),
    meter_service: MeterService = Depends(get_meter_service),
) -> RepairRequestService:
    return RepairRequestService(repository, repair_service, meter_service)


def get_driver_service(repository: Repository = Depends(get_repository)) -> DriverService:
    return DriverService(repository)


def get_vehicle_certificate_service(
    repository: Repository = Depends(get_repository),
) -> VehicleCertificateService:
    return VehicleCertificateService(repository)


def get_model_document_service(
    repository: Repository = Depends(get_repository),
) -> ModelDocumentService:
    return ModelDocumentService(repository)


def get_vehicle_event_service(
    repository: Repository = Depends(get_repository),
) -> VehicleEventService:
    return VehicleEventService(repository)


def get_daily_summary_service(
    repository: Repository = Depends(get_repository),
) -> DailySummaryService:
    return DailySummaryService(repository)
