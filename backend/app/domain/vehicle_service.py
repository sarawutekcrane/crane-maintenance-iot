"""Vehicle/model domain service.

Baseline section 3: "Dashboard, Vehicle Detail, alerts, and reports must
use the same domain services. Do not independently reimplement the same
... formula in multiple frontend pages." This module is the single place
that assembles a Vehicle Detail view (vehicle + model + components) and
translates "not found" into the frozen `ApiError` envelope, so later
phases (Dashboard, alerts) can reuse it instead of querying the
repository directly.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import status

from app.domain.common import OperationalStatus, Page, PageParams
from app.domain.fleet_summary import (
    FleetStatusSummary,
    count_fleet_status,
    find_identity_issues,
    sample_vehicle_ids,
)
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import VehicleModel
from app.errors import ApiError
from app.repositories.base import (
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
    RepositorySchemaError,
    RepositoryTabReadError,
    RepositoryWriteError,
)


def vehicle_master_read_error(exc: RepositoryError) -> ApiError:
    """The 7B2 mapping of a failed vehicle-master read, shared by the fleet
    status summary and (Batch 7G2) GET /vehicles: a proven structural
    problem -> 500 VEHICLE_MASTER_SCHEMA_INVALID {tab, problem, headers};
    any other repository failure -> 503 VEHICLE_MASTER_READ_FAILED."""
    if isinstance(exc, RepositorySchemaError):
        return ApiError(
            code="VEHICLE_MASTER_SCHEMA_INVALID",
            message=str(exc),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
        )
    return ApiError(
        code="VEHICLE_MASTER_READ_FAILED",
        message="vehicle_master could not be read",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# Phase 7 Batch 7H2 (DEC-H14a): per-tab error code prefixes on the validated
# VehicleService paths. maintenance_plan is read only to resolve a model's
# assigned PM plan (DEC-H3a), so its failures are reported under the model
# codes with the tab named in the details.
_TAB_CODE_PREFIX = {
    "vehicle_master": "VEHICLE_MASTER",
    "model_master": "MODEL_MASTER",
    "maintenance_plan": "MODEL_MASTER",
    "vehicle_component": "VEHICLE_COMPONENT",
    "vehicle_status_history": "VEHICLE_STATUS_HISTORY",
}


def vehicle_path_error(exc: RepositoryError) -> ApiError | None:
    """Phase 7 Batch 7H2: map a repository failure on the validated
    VehicleService paths (detail, models, components, status history and
    both writes) to its API error, or None when it is not one of the
    expected repository failures (the caller then re-raises it unchanged).
    Write outcomes are reported only as far as the evidence establishes
    (DEC-H6/H7): "rejected" for an HTTP 4xx error response, "unknown" for
    a 5xx or transport failure, after which the write MAY have been
    applied. Nothing is retried, compensated or re-read."""
    if isinstance(exc, RepositoryIdentityAmbiguousError):
        return ApiError(
            code="VEHICLE_ID_AMBIGUOUS",
            message="The vehicle id matches more than one vehicle record; nothing was changed",
            status_code=status.HTTP_409_CONFLICT,
            details={"match_count": exc.match_count},
        )
    if isinstance(exc, RepositoryRecordInvalidError):
        return ApiError(
            code="VEHICLE_MASTER_DATA_INVALID",
            message="The vehicle_master record cannot be used exactly; nothing was changed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"issue_counts": {exc.issue: 1}},
        )
    if isinstance(exc, RepositoryWriteError):
        if exc.tab == "vehicle_status_history":
            # Only attempted after the vehicle write was ACKNOWLEDGED (not
            # re-read). An unknown history outcome may mean the row exists.
            message = (
                "The vehicle status update was acknowledged, but Google Sheets rejected the "
                "status-history write request; nothing was retried"
                if exc.outcome == "rejected"
                else "The vehicle status update was acknowledged, but the status-history write "
                "outcome is unknown (the history row may or may not have been recorded); "
                "nothing was retried"
            )
            return ApiError(
                code="VEHICLE_STATUS_HISTORY_WRITE_FAILED",
                message=message,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"vehicle_status_updated": True, "history_write_outcome": exc.outcome},
            )
        message = (
            "Google Sheets rejected the vehicle update request; nothing was retried"
            if exc.outcome == "rejected"
            else "The vehicle update outcome is unknown (the request may have been applied); "
            "nothing was retried"
        )
        return ApiError(
            code="VEHICLE_MASTER_WRITE_FAILED",
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"vehicle_write_outcome": exc.outcome},
        )
    tab = getattr(exc, "tab", None)
    prefix = _TAB_CODE_PREFIX.get(tab) if isinstance(tab, str) else None
    if prefix is None:
        return None
    if isinstance(exc, RepositorySchemaError):
        return ApiError(
            code=f"{prefix}_SCHEMA_INVALID",
            message=str(exc),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
        )
    if isinstance(exc, RepositoryTabReadError):
        return ApiError(
            code=f"{prefix}_READ_FAILED",
            message=f"{exc.tab} could not be read",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"tab": exc.tab} if exc.tab == "maintenance_plan" else None,
        )
    return None


@dataclass(frozen=True)
class VehicleDetail:
    vehicle: Vehicle
    model: VehicleModel | None
    components: list[VehicleComponent]


class VehicleService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    @staticmethod
    async def _validated(call):
        """Await a validated-path repository call, translating only the
        expected repository failures (vehicle_path_error); anything else —
        including programming errors and the intentionally-unavailable
        feature error — propagates unchanged."""
        try:
            return await call
        except RepositoryFeatureNotImplementedError:
            raise
        except RepositoryError as exc:
            mapped = vehicle_path_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

    async def list_models(self, q: str | None, params: PageParams) -> Page[VehicleModel]:
        items, total = await self._validated(
            self._repository.list_vehicle_models_validated(q=q, params=params)
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def get_model(self, model_id: str) -> VehicleModel:
        model = await self._validated(self._repository.get_vehicle_model_validated(model_id))
        if model is None:
            raise ApiError(
                code="MODEL_NOT_FOUND",
                message=f"Vehicle model '{model_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return model

    async def list_vehicles(
        self,
        q: str | None,
        operational_status: OperationalStatus | None,
        model_id: str | None,
        params: PageParams,
    ) -> Page[Vehicle]:
        """Phase 7 Batch 7G2 (A0) — the vehicle list from the SAME single
        validated vehicle-master read and whole-population gates as the
        fleet status summary, applied before any filter or pagination, so
        one invalid record fails every list request (no partial, defaulted
        or silently misread result). A validation failure raises
        VEHICLE_MASTER_DATA_INVALID with `issue_counts` only: this route is
        not capability-gated, so no vehicle ids are disclosed (DEC-7(b)).
        Repository failures propagate unchanged as `RepositoryError` /
        `RepositorySchemaError`; the GET /vehicles route maps them with
        `vehicle_master_read_error`, exactly as the dashboard does.
        Filters, ordering and paging are those of the legacy list; no
        stored value is trimmed, normalized or written back."""
        vehicles = await self._read_validated_vehicle_master(
            data_invalid_message="vehicle_master contains records that cannot be listed exactly",
            include_sample_vehicle_ids=False,
        )
        if q:
            needle = q.strip().lower()
            vehicles = [
                v
                for v in vehicles
                if needle in v.machine_no.lower() or needle in v.vehicle_id.lower()
            ]
        if operational_status is not None:
            vehicles = [v for v in vehicles if v.operational_status == operational_status]
        if model_id is not None:
            vehicles = [v for v in vehicles if v.model_id == model_id]
        vehicles.sort(key=lambda v: v.vehicle_id)
        start = (params.page - 1) * params.page_size
        return Page(
            items=vehicles[start : start + params.page_size],
            page=params.page,
            page_size=params.page_size,
            total_items=len(vehicles),
        )

    async def get_fleet_status_summary(self) -> FleetStatusSummary:
        """Phase 7 Batch 7B2 — K1 vehicle_total and K2-K6 recorded status
        counts from ONE validated vehicle-master read (no model, component,
        history or per-vehicle reads; no writes). Parity-or-fail: any
        structural, record or identity problem fails the whole summary
        with no counts, so a success agrees with `list_vehicles` totals for
        the same stored state."""
        try:
            vehicles = await self._read_validated_vehicle_master(
                data_invalid_message=(
                    "vehicle_master contains records that cannot be summarized exactly"
                ),
                include_sample_vehicle_ids=True,
            )
        except RepositoryError as exc:
            raise vehicle_master_read_error(exc) from exc
        return count_fleet_status(vehicles)

    async def _read_validated_vehicle_master(
        self, *, data_invalid_message: str, include_sample_vehicle_ids: bool
    ) -> list[Vehicle]:
        """One `read_vehicle_master_for_summary` call, then the 7B2 record
        and identity gates over the WHOLE population. Returns the records
        only when there is no issue; otherwise raises
        VEHICLE_MASTER_DATA_INVALID with `issue_counts` (plus
        `sample_vehicle_ids` only when asked). Repository errors are not
        caught here."""
        read = await self._repository.read_vehicle_master_for_summary()
        issue_counts = dict(read.issue_counts)
        identity_issues, duplicated_ids = find_identity_issues(read.vehicles)
        issue_counts.update(identity_issues)
        if issue_counts:
            details: dict[str, object] = {"issue_counts": dict(sorted(issue_counts.items()))}
            if include_sample_vehicle_ids:
                details["sample_vehicle_ids"] = sample_vehicle_ids(
                    [*read.issue_vehicle_ids, *duplicated_ids]
                )
            raise ApiError(
                code="VEHICLE_MASTER_DATA_INVALID",
                message=data_invalid_message,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details=details,
            )
        return read.vehicles

    @staticmethod
    def _vehicle_not_found(vehicle_id: str) -> ApiError:
        return ApiError(
            code="VEHICLE_NOT_FOUND",
            message=f"Vehicle '{vehicle_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    async def _require_vehicle(self, vehicle_id: str) -> Vehicle:
        """Phase 7 Batch 7H2: exact, validated, text-preserving lookup (one
        validated vehicle_master read). Blank/whitespace ids are not found;
        duplicate ids are 409 VEHICLE_ID_AMBIGUOUS; a record failing the
        7B2 gates is VEHICLE_MASTER_DATA_INVALID."""
        vehicle = await self._validated(self._repository.get_vehicle_validated(vehicle_id))
        if vehicle is None:
            raise self._vehicle_not_found(vehicle_id)
        return vehicle

    async def get_vehicle_detail(self, vehicle_id: str) -> VehicleDetail:
        vehicle = await self._require_vehicle(vehicle_id)
        # A model that no longer resolves is a data-integrity gap, not a
        # reason to fail the whole page: the baseline requires missing
        # source values to stay blank rather than be fabricated.
        model = await self._validated(self._repository.get_vehicle_model_validated(vehicle.model_id))
        components = await self._validated(
            self._repository.list_vehicle_components_validated(vehicle_id)
        )
        return VehicleDetail(vehicle=vehicle, model=model, components=components)

    async def update_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        """Phase 7 Batch 7H2 (Final contract 5.3 A): validated locate and
        intended-model validation before ONE targeted write; no legacy
        pre-write guard and no post-write re-read."""
        vehicle = await self._validated(
            self._repository.update_vehicle_machine_no_validated(vehicle_id, machine_no)
        )
        if vehicle is None:
            raise self._vehicle_not_found(vehicle_id)
        return vehicle

    async def list_components(self, vehicle_id: str) -> list[VehicleComponent]:
        await self._require_vehicle(vehicle_id)
        return await self._validated(self._repository.list_vehicle_components_validated(vehicle_id))

    async def list_status_history(self, vehicle_id: str) -> list[VehicleStatusHistoryEntry]:
        await self._require_vehicle(vehicle_id)
        return await self._validated(
            self._repository.list_vehicle_status_history_validated(vehicle_id)
        )

    async def change_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> tuple[Vehicle, VehicleStatusHistoryEntry]:
        """Phase 7 Batch 7H2 (Final contract 5.3 B): validated locate,
        intended models and history preflight before the vehicle write;
        status before history (not atomic); no re-read (DEC-H17)."""
        result = await self._validated(
            self._repository.change_vehicle_status_validated(
                vehicle_id=vehicle_id, new_status=new_status, changed_by=changed_by, note=note
            )
        )
        if result is None:
            raise self._vehicle_not_found(vehicle_id)
        return result
