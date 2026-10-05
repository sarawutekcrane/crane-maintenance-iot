"""Phase 7 Batch 7O2a — read-only registry service: reference lists and the
two per-vehicle histories (contract Final Rev2 §4.5, §7.2, §7.4, §8.1).

Every method is a read. Failures are whole-response coded errors: a history
or reference read that fails is never answered with an empty list. The
vehicle is located with the same validated path (and errors) as the detail
page. Authorization (`can_view`) is checked by the routes before any call.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar

from app.domain.branch_timeline import STATUS_INVALID, BranchTimeline, derive_timeline, vehicle_history_rows
from app.domain.registration import (
    ordered_rows,
    registration_consistency,
    registration_history_revision,
    text,
    validate_registration_rows,
)
from app.domain.registry_errors import data_context_not_configured, data_invalid, registry_tab_error
from app.domain.vehicle_registry import (
    STATE_NOT_IN_SCHEMA,
    STATE_RECORDED,
    ReferenceEntry,
    VehicleRegistry,
    parse_reference_rows,
)
from app.domain.vehicle_service import VehicleService
from app.repositories.base import (
    RegistryTableRead,
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
)

T = TypeVar("T")


@dataclass(frozen=True)
class BranchHistoryRead:
    vehicle_id: str
    master: VehicleRegistry
    timeline: BranchTimeline


@dataclass(frozen=True)
class RegistrationHistoryRead:
    vehicle_id: str
    master: VehicleRegistry
    consistency: str
    revision: str
    items: list[Mapping[str, object]]  # recorded order


class RegistryReadService:
    def __init__(self, repository: Repository, data_context: str | None) -> None:
        self._repository = repository
        self._context = data_context
        self._vehicles = VehicleService(repository)

    def _require_context(self) -> str:
        """§8.1: in google_sheets mode an unset REGISTRY_DATA_CONTEXT makes
        every registry endpoint 503 before any read; existing routes are not
        affected. Mock mode is always TEST."""
        if self._context is None:
            raise data_context_not_configured()
        return self._context

    @staticmethod
    async def _tab(call: Awaitable[T]) -> T:
        try:
            return await call
        except RepositoryFeatureNotImplementedError:
            raise
        except RepositoryError as exc:
            mapped = registry_tab_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

    async def _reference(
        self, read_tab: Callable[[], Awaitable[RegistryTableRead]], *, tab: str, code: str, name: str,
        active_optional: bool,
    ) -> list[ReferenceEntry]:
        self._require_context()  # before the read is even started
        read = await self._tab(read_tab())
        entries, issues = parse_reference_rows(
            read.rows,
            code_column=code,
            name_column=name,
            active_column_present=(not active_optional) or "is_active" in read.columns,
        )
        if issues:
            raise data_invalid(tab, issues)
        return entries

    async def list_branches(self) -> list[ReferenceEntry]:
        return await self._reference(
            self._repository.read_branch_master_validated,
            tab="branch_master", code="branch_id", name="branch_name", active_optional=True,
        )

    async def list_provinces(self) -> list[ReferenceEntry]:
        return await self._reference(
            self._repository.read_province_master_validated,
            tab="province_master", code="province_code", name="province_name_th", active_optional=False,
        )

    async def branch_history(self, vehicle_id: str) -> BranchHistoryRead:
        """Context -> validated vehicle locate (detail-page errors) -> ONE
        asset_branch_history read -> this vehicle's rows -> validation and
        derivation. INVALID -> 500 BRANCH_HISTORY_DATA_INVALID {issues}."""
        context = self._require_context()
        located = await self._vehicles.require_vehicle_with_registry(vehicle_id)
        read = await self._tab(self._repository.read_asset_branch_history_validated())
        rows = vehicle_history_rows(read.rows, located.vehicle.vehicle_id)
        master = located.registry.responsible_branch
        timeline = derive_timeline(
            rows,
            master_branch_id=master.value if master.state == STATE_RECORDED else None,
            master_available=master.state != STATE_NOT_IN_SCHEMA,
            context=context,
        )
        if timeline.status == STATUS_INVALID:
            raise data_invalid("asset_branch_history", timeline.issue_counts)
        return BranchHistoryRead(vehicle_id=located.vehicle.vehicle_id, master=located.registry, timeline=timeline)

    async def registration_history(self, vehicle_id: str) -> RegistrationHistoryRead:
        """Context -> validated vehicle locate -> ONE
        vehicle_registration_history read -> this vehicle's rows (exact
        vehicle_id) -> validation. Any issue -> 500
        REGISTRATION_HISTORY_DATA_INVALID {issues}."""
        context = self._require_context()
        located = await self._vehicles.require_vehicle_with_registry(vehicle_id)
        read = await self._tab(self._repository.read_vehicle_registration_history_validated())
        own_id = located.vehicle.vehicle_id
        rows = [r for r in read.rows if text(r.get("vehicle_id")) == own_id]
        issues = validate_registration_rows(rows, context)
        if issues:
            raise data_invalid("vehicle_registration_history", issues)
        return RegistrationHistoryRead(
            vehicle_id=own_id,
            master=located.registry,
            consistency=registration_consistency(rows, located.registry.registration_pair),
            revision=registration_history_revision(rows),
            items=ordered_rows(rows),
        )
