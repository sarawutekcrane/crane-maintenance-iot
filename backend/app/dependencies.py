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
from app.errors import ApiError
from app.domain.driver_service import DriverService
from app.domain.vehicle_certificate_service import VehicleCertificateService
from app.domain.certificate_expiry_report_service import CertificateExpiryReportService
from app.domain.inspection_finding_report_service import InspectionFindingReportService
from app.domain.model_document_service import ModelDocumentService
from app.domain.vehicle_event_service import VehicleEventService
from app.domain.daily_summary_service import DailySummaryService
from app.domain.alert_service import AlertService
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
from app.domain.technician_assignment import cutover_from_settings
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
        return MockRepository(access_management_seed=settings.access_management_mode)
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


def get_settings_dependency() -> Settings:
    return get_settings()


async def get_current_context(
    request: Request,
    settings: Settings = Depends(get_settings_dependency),
    repository: Repository = Depends(get_repository),
) -> RequestContext:
    """The request's actor. In Access Management mode the capabilities are
    recomputed on EVERY request from the current per-employee grants (so a grant
    or revocation applies to the very next API call, without a new login); the
    development role table grants nothing operational there. Legacy mode is
    unchanged."""
    context = get_request_context(request)
    if not settings.access_management_mode:
        return context
    resolved = getattr(request.state, "access_context", None)
    if resolved is None:
        from app.domain.access_management import AccessService

        cutover = cutover_from_settings(settings)
        resolved = await AccessService(repository, cutover.data_context, cutover.test_batch_id).effective_context(
            context)
        request.state.access_context = resolved
    return resolved


# D6 — mutating routes with NO capability meaning in the approved contract. In
# Access Management mode they fail closed (no capability is guessed or invented);
# each is an Owner-pending mapping. Legacy mode is unchanged.
AM_UNRESOLVED_WRITE_ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("PATCH", "/api/v1/vehicles/{vehicle_id}"),
    ("PATCH", "/api/v1/vehicles/{vehicle_id}/status"),
    ("POST", "/api/v1/equipment/{equipment_id}/status"),
    ("POST", "/api/v1/meter-snapshots"),
    ("POST", "/api/v1/parts"),
    ("POST", "/api/v1/part-sets"),
    ("POST", "/api/v1/part-sets/{part_set_id}/revisions"),
    ("POST", "/api/v1/part-instances"),
    ("POST", "/api/v1/part-instances/{part_instance_id}/install"),
    ("POST", "/api/v1/part-instances/{part_instance_id}/remove"),
    ("POST", "/api/v1/part-instances/{part_instance_id}/transfer"),
    ("POST", "/api/v1/part-instances/{part_instance_id}/start-new-lifecycle"),
    ("POST", "/api/v1/position-lifetime"),
    ("POST", "/api/v1/lifetime-rules"),
    ("POST", "/api/v1/material-requests"),
    ("POST", "/api/v1/drivers"),
    ("PATCH", "/api/v1/drivers/{driver_id}"),
    ("POST", "/api/v1/vehicles/{vehicle_id}/certificates"),
    ("POST", "/api/v1/certificates/{certificate_id}/renew"),
    ("POST", "/api/v1/models/{model_id}/documents"),
    ("POST", "/api/v1/model-documents/{model_document_id}/revise"),
    ("POST", "/api/v1/vehicle-events"),
})
# The one write that may run without a resolved employee: technical recovery of
# the root position while no valid holder exists (re-checked in the service).
AM_RECOVERY_WRITE_ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/api/v1/access/root/appointment"),
})
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def access_management_write_policy(
    request: Request,
    settings: Settings = Depends(get_settings_dependency),
    repository: Repository = Depends(get_repository),
) -> None:
    """D6 — applied to every `/api/v1` route. In Access Management mode a write
    needs a verified, active employee identity (unless it is the recovery route),
    and an unresolved-mapping write is refused outright. Route-specific
    capability checks still apply after this. Reads and legacy mode: unchanged."""
    if not settings.access_management_mode or request.method not in _WRITE_METHODS:
        return
    # The matched route's own template (FastAPI keeps the child router's route, without the v1 prefix).
    template = getattr(request.scope.get("route"), "path", "")
    key = (request.method, template if template.startswith("/api/v1") else f"/api/v1{template}")
    if key in AM_UNRESOLVED_WRITE_ROUTES:
        raise ApiError(code="ACCESS_CAPABILITY_MAPPING_UNRESOLVED", status_code=403,
                       message="This change has no approved permission mapping yet; it is unavailable in "
                               "Access Management mode")
    if key in AM_RECOVERY_WRITE_ROUTES:
        return
    context = await get_current_context(request, settings, repository)
    if not context.personnel_id:
        raise ApiError(code="ACCESS_ACTOR_NOT_VERIFIED", status_code=403,
                       message="This change requires an active employee linked to exactly one account")


def root_protection(operation: str):
    """B1 — a route dependency for every mutation of a personnel record's account
    link (IDENTITY), lifecycle (LIFECYCLE) or department (DEPARTMENT). In Access
    Management mode the employee named by the latest root appointment is protected:
    ordinary capabilities cannot take over or lock out the position, whoever
    granted them. Legacy mode is unchanged."""

    async def guard(
        personnel_id: str,
        request: Request,
        settings: Settings = Depends(get_settings_dependency),
        repository: Repository = Depends(get_repository),
    ) -> None:
        if not settings.access_management_mode:
            return
        from app.domain.access_management import AccessService

        context = await get_current_context(request, settings, repository)
        cutover = cutover_from_settings(settings)
        service = AccessService(repository, cutover.data_context, cutover.test_batch_id)
        service.require_root_protection(await service.state(), context, personnel_id, operation)

    return guard


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
    settings: Settings = Depends(get_settings_dependency),
) -> PmService:
    # R2 Batch R2f-h1: the V2 cutover setting (default OFF) + server context.
    return PmService(repository, meter_service, cutover_from_settings(settings))


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
    settings: Settings = Depends(get_settings_dependency),
) -> RepairService:
    # R2 Batch R2f-h1: the V2 cutover setting (default OFF) + server context.
    return RepairService(repository, meter_service, notification_sink, cutover_from_settings(settings))


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


def get_certificate_expiry_report_service(
    repository: Repository = Depends(get_repository),
) -> CertificateExpiryReportService:
    return CertificateExpiryReportService(repository)


def get_inspection_finding_report_service(
    repository: Repository = Depends(get_repository),
) -> InspectionFindingReportService:
    return InspectionFindingReportService(repository)


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


def get_alert_service(
    repository: Repository = Depends(get_repository),
) -> AlertService:
    return AlertService(repository)
