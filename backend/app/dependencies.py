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
from app.domain.technician_assignment import AssignmentCutover, cutover_from_settings
from app.domain.vehicle_service import VehicleService
from app.domain.vehicle_status_events import VehicleStatusEventService
from app.domain.work_time_service import WorkTimeService
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
    global _part_test_meter_source
    get_repository.cache_clear()
    get_storage_provider.cache_clear()
    _part_test_meter_source = None


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
    # R7 Whole-Phase (Owner gate 2026-11-17, policy R1 P-1): the four document-master writes
    # (certificate create / renew, model-document create / revise) are no longer listed here;
    # each carries `document_master_write_gate` instead — a TEST-only, grant- and
    # parent-scope-checked route dependency that runs after this policy and before the handler.
    ("POST", "/api/v1/vehicle-events"),
    # R6 (FINAL §7.6; PG-5 unresolved): every NEW part write stays fail-closed
    # in Access Management mode until the Owner approves a capability mapping.
    ("POST", "/api/v1/parts/{part_id}/deactivate"),
    ("POST", "/api/v1/parts/{part_id}/reactivate"),
    ("POST", "/api/v1/part-sets/{part_set_id}/applicability"),
    ("POST", "/api/v1/part-instances/{part_instance_id}/return-from-repair"),
    ("POST", "/api/v1/part-instances/{part_instance_id}/status"),
    ("POST", "/api/v1/part-instances/{part_instance_id}/identifiers"),
    ("POST", "/api/v1/part-instances/{part_instance_id}/maintenance-events"),
    ("POST", "/api/v1/position-lifetime/{position_lifetime_id}/replace"),
    ("POST", "/api/v1/position-lifetime/{position_lifetime_id}/maintenance-events"),
    ("POST", "/api/v1/test-support/part-meter-observations"),
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


# R7 policy R1 P-1 / P-2: the parent each document-master route writes under.
DOCUMENT_PARENT_VEHICLE = "VEHICLE"
DOCUMENT_PARENT_CERTIFICATE = "CERTIFICATE"
DOCUMENT_PARENT_MODEL = "MODEL"
DOCUMENT_PARENT_MODEL_DOCUMENT = "MODEL_DOCUMENT"
_DOCUMENT_MASTER_ACTION_TH = "การบันทึกใบรับรองรถ/เอกสารรุ่นรถ (document master change)"


def document_master_write_gate(parent: str):
    """The ONE shared route dependency of the four document-master writes (policy R1 P-1).
    FastAPI runs it after the router-level D6 write policy and before the handler (and
    before body validation errors), so nothing reaches a repository write unless it passed.

    Legacy mode (Owner choice P-2 = A): a trusted, non-blank server-side `user_id` is
    required; existing role semantics are unchanged. With dev auth off there is no
    trusted actor, so every such write is refused.

    Access Management mode, in order (each refusal before any further read):
      a. the synthetic Mock repository (else 501);
      b. the server's TEST data context (else 403);
      c. a context resolved by Access Management to one verified employee with a user id;
      d. that employee's own `can_manage_test_document_master` grant;
      e. the parent: a certificate's vehicle TEST-scoped; a model TEST-exclusive.
    Nothing is read from a client flag, header or `is_test_data`."""

    async def gate(
        request: Request,
        settings: Settings = Depends(get_settings_dependency),
        repository: Repository = Depends(get_repository),
    ) -> None:
        from app.domain import authz
        from app.domain.attachment_service import (
            require_test_exclusive_model,
            require_test_scoped_document_parent,
            require_test_vehicle_parent,
        )

        context = await get_current_context(request, settings, repository)
        if not settings.access_management_mode:
            if not (context.user_id or "").strip():
                raise ApiError(code="ACCESS_ACTOR_NOT_VERIFIED", status_code=403,
                               message=f"{_DOCUMENT_MASTER_ACTION_TH} requires a trusted, authenticated actor")
            return
        if settings.data_repository != DataRepositoryMode.MOCK:
            raise ApiError(code="FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE", status_code=501,
                           message="Document master changes are available only in the synthetic Mock/TEST repository",
                           details={"feature": "document_master_write"})
        if settings.registry_context_effective != "TEST":
            raise ApiError(code="DOCUMENT_MASTER_TEST_ONLY", status_code=403,
                           message="Document master changes are available only in the TEST data context")
        if getattr(context, "access", None) is None or not context.personnel_id \
                or not (context.user_id or "").strip():
            raise ApiError(code="ACCESS_ACTOR_NOT_VERIFIED", status_code=403,
                           message="This change requires an active TEST employee linked to exactly one account")
        if authz.CAN_MANAGE_TEST_DOCUMENT_MASTER not in context.capabilities:
            raise ApiError(code="DOCUMENT_MASTER_NOT_AUTHORIZED", status_code=403,
                           message=f"{_DOCUMENT_MASTER_ACTION_TH} requires the "
                                   f"'{authz.CAN_MANAGE_TEST_DOCUMENT_MASTER}' grant")
        params = request.path_params
        if parent == DOCUMENT_PARENT_VEHICLE:
            await require_test_vehicle_parent(repository, settings, params["vehicle_id"])
        elif parent == DOCUMENT_PARENT_CERTIFICATE:
            await require_test_scoped_document_parent(repository, settings, "VEHICLE_CERTIFICATE",
                                                      params["certificate_id"])
        elif parent == DOCUMENT_PARENT_MODEL:
            await require_test_exclusive_model(repository, settings, params["model_id"])
        else:
            await require_test_scoped_document_parent(repository, settings, "MODEL_DOCUMENT",
                                                      params["model_document_id"])

    return gate


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


def get_assignment_cutover(settings: Settings = Depends(get_settings_dependency)) -> AssignmentCutover:
    """R5: the server's TEST/REAL data context (and TEST batch), as every V2
    service builds it. The AMB-1 vehicle status guard and the R5 services read it
    here so a test can override the context without touching settings."""
    return cutover_from_settings(settings)


def get_work_time_service(
    repository: Repository = Depends(get_repository),
    cutover: AssignmentCutover = Depends(get_assignment_cutover),
) -> WorkTimeService:
    return WorkTimeService(repository, cutover)


def get_vehicle_status_event_service(
    repository: Repository = Depends(get_repository),
    cutover: AssignmentCutover = Depends(get_assignment_cutover),
) -> VehicleStatusEventService:
    return VehicleStatusEventService(repository, cutover)


_part_test_meter_source = None


def get_part_test_meter_source(settings: Settings = Depends(get_settings_dependency)):
    """R6 A-4: the TEST-only fake meter source singleton, or None when it is
    not effective (then part counters use the R4 source — runtime
    NO_IOT_METER_SOURCE — and stay UNKNOWN)."""
    global _part_test_meter_source
    if not settings.part_test_meter_source_effective:
        return None
    if _part_test_meter_source is None:
        from app.domain.part_lifetime_status_service import TestOnlyPartMeterSource

        _part_test_meter_source = TestOnlyPartMeterSource(settings.registry_context_effective)
    return _part_test_meter_source


def get_part_service(
    repository: Repository = Depends(get_repository),
    cutover: AssignmentCutover = Depends(get_assignment_cutover),
) -> PartService:
    return PartService(repository, cutover.data_context)


def get_part_instance_service(
    repository: Repository = Depends(get_repository),
    meter_service: MeterService = Depends(get_meter_service),
    cutover: AssignmentCutover = Depends(get_assignment_cutover),
    test_source=Depends(get_part_test_meter_source),
) -> PartInstanceService:
    return PartInstanceService(repository, meter_service, cutover, test_source)


def get_position_lifetime_service(
    repository: Repository = Depends(get_repository),
    meter_service: MeterService = Depends(get_meter_service),
    cutover: AssignmentCutover = Depends(get_assignment_cutover),
    test_source=Depends(get_part_test_meter_source),
) -> PositionLifetimeService:
    return PositionLifetimeService(repository, meter_service, cutover, test_source)


def get_part_lifetime_status_service(
    repository: Repository = Depends(get_repository),
    meter_service: MeterService = Depends(get_meter_service),
    cutover: AssignmentCutover = Depends(get_assignment_cutover),
    test_source=Depends(get_part_test_meter_source),
):
    from app.domain.part_lifetime_status_service import PartLifetimeStatusService

    return PartLifetimeStatusService(repository, meter_service, cutover, test_source)


def get_lifetime_rule_service(
    repository: Repository = Depends(get_repository),
    cutover: AssignmentCutover = Depends(get_assignment_cutover),
) -> LifetimeRuleService:
    return LifetimeRuleService(repository, cutover.data_context)


def get_material_request_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> MaterialRequestService:
    # Legacy cancelled: the server's TEST/REAL context proves a new request's V2 source is in scope.
    return MaterialRequestService(repository, cutover_from_settings(settings))


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


def get_r7_alert_service(
    repository: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dependency),
    pm_service: PmService = Depends(get_pm_service),
    part_status_service=Depends(get_part_lifetime_status_service),
):
    """R7 Whole-Phase (policy R1 §5): the TEST alert evaluation / action / read service,
    consuming the existing R4 PM Due and R6 part lifetime read services unchanged."""
    from app.domain.alert_service import R7AlertService

    return R7AlertService(repository, settings, pm_service, part_status_service)
