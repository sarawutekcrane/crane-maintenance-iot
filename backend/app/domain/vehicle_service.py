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
from app.repositories.base import Repository, RepositoryError, RepositorySchemaError


@dataclass(frozen=True)
class VehicleDetail:
    vehicle: Vehicle
    model: VehicleModel | None
    components: list[VehicleComponent]


class VehicleService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def list_models(self, q: str | None, params: PageParams) -> Page[VehicleModel]:
        items, total = await self._repository.list_vehicle_models(q=q, params=params)
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def get_model(self, model_id: str) -> VehicleModel:
        model = await self._repository.get_vehicle_model(model_id)
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
        items, total = await self._repository.list_vehicles(
            q=q, operational_status=operational_status, model_id=model_id, params=params
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    async def get_fleet_status_summary(self) -> FleetStatusSummary:
        """Phase 7 Batch 7B2 — K1 vehicle_total and K2-K6 recorded status
        counts from ONE validated vehicle-master read (no model, component,
        history or per-vehicle reads; no writes). Parity-or-fail: any
        structural, record or identity problem fails the whole summary
        with no counts, so a success agrees with `list_vehicles` totals for
        the same stored state."""
        try:
            read = await self._repository.read_vehicle_master_for_summary()
        except RepositorySchemaError as exc:
            raise ApiError(
                code="VEHICLE_MASTER_SCHEMA_INVALID",
                message=str(exc),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"tab": exc.tab, "problem": exc.problem, "headers": list(exc.headers)},
            ) from exc
        except RepositoryError as exc:
            raise ApiError(
                code="VEHICLE_MASTER_READ_FAILED",
                message="vehicle_master could not be read",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        issue_counts = dict(read.issue_counts)
        identity_issues, duplicated_ids = find_identity_issues(read.vehicles)
        issue_counts.update(identity_issues)
        if issue_counts:
            raise ApiError(
                code="VEHICLE_MASTER_DATA_INVALID",
                message="vehicle_master contains records that cannot be summarized exactly",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={
                    "issue_counts": dict(sorted(issue_counts.items())),
                    "sample_vehicle_ids": sample_vehicle_ids(
                        [*read.issue_vehicle_ids, *duplicated_ids]
                    ),
                },
            )
        return count_fleet_status(read.vehicles)

    async def _require_vehicle(self, vehicle_id: str) -> Vehicle:
        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            raise ApiError(
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle '{vehicle_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return vehicle

    async def get_vehicle_detail(self, vehicle_id: str) -> VehicleDetail:
        vehicle = await self._require_vehicle(vehicle_id)
        # A model that no longer resolves is a data-integrity gap, not a
        # reason to fail the whole page: the baseline requires missing
        # source values to stay blank rather than be fabricated.
        model = await self._repository.get_vehicle_model(vehicle.model_id)
        components = await self._repository.list_vehicle_components(vehicle_id)
        return VehicleDetail(vehicle=vehicle, model=model, components=components)

    async def update_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        await self._require_vehicle(vehicle_id)
        return await self._repository.update_vehicle_machine_no(vehicle_id, machine_no)

    async def list_components(self, vehicle_id: str) -> list[VehicleComponent]:
        await self._require_vehicle(vehicle_id)
        return await self._repository.list_vehicle_components(vehicle_id)

    async def list_status_history(self, vehicle_id: str) -> list[VehicleStatusHistoryEntry]:
        await self._require_vehicle(vehicle_id)
        return await self._repository.list_vehicle_status_history(vehicle_id)

    async def change_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> tuple[Vehicle, VehicleStatusHistoryEntry]:
        await self._require_vehicle(vehicle_id)
        entry = await self._repository.change_vehicle_status(
            vehicle_id=vehicle_id, new_status=new_status, changed_by=changed_by, note=note
        )
        vehicle = await self._require_vehicle(vehicle_id)
        return vehicle, entry
