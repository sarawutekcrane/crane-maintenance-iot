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
from app.domain.equipment_service import EquipmentService
from app.domain.inspection_service import InspectionService
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


def get_inspection_service(
    repository: Repository = Depends(get_repository),
    storage: StorageProvider = Depends(get_storage_provider),
    settings: Settings = Depends(get_settings_dependency),
) -> InspectionService:
    return InspectionService(repository, storage, settings)
