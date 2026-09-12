"""Repository interface.

Frozen in Phase 1: the domain/service layer depends only on this
interface, never on a concrete storage technology. Phase 1 only defined
the readiness/self-check contract; domain-entity repository methods
(vehicles, inspections, PM, parts, ...) are added starting Phase 2 as
extensions of `Repository`, without changing this base shape (see
`check_ready`/`mode`, which remain untouched below).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.asset import AssetType
from app.domain.attachment import Attachment, AttachmentPurpose
from app.domain.checklist import ChecklistRevisionDetail
from app.domain.common import OperationalStatus, PageParams
from app.domain.equipment import Equipment, EquipmentCategory
from app.domain.inspection import (
    InspectionDetail,
    NewInspectionItemInput,
    InspectionSummary,
)
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import VehicleModel


class RepositoryError(Exception):
    """Raised when a repository cannot serve a request (connectivity,
    missing schema, etc.). Domain/service code should translate this into
    an ApiError; it must never leak raw driver exceptions (e.g. Google API
    exceptions) upward.
    """


class Repository(ABC):
    """Base interface every concrete repository (mock, Google Sheets,
    PostgreSQL) must implement.
    """

    @property
    @abstractmethod
    def mode(self) -> str:
        """Short identifier of the backing mode, e.g. "mock", "google_sheets"."""

    @abstractmethod
    async def check_ready(self) -> tuple[bool, str | None]:
        """Return (is_ready, reason_if_not_ready).

        Used by GET /api/v1/readiness. Mock repositories are always ready.
        Google Sheets / PostgreSQL repositories should verify connectivity
        and required schema here.
        """

    # ---- Vehicle model (Phase 2) ----

    @abstractmethod
    async def list_vehicle_models(
        self, q: str | None, params: PageParams
    ) -> tuple[list[VehicleModel], int]:
        """Return (page of models matching `q`, total matching count)."""

    @abstractmethod
    async def get_vehicle_model(self, model_id: str) -> VehicleModel | None:
        """Return the model, or None if `model_id` does not exist."""

    # ---- Vehicle (Phase 2) ----

    @abstractmethod
    async def list_vehicles(
        self,
        q: str | None,
        operational_status: OperationalStatus | None,
        model_id: str | None,
        params: PageParams,
    ) -> tuple[list[Vehicle], int]:
        """Return (page of vehicles matching the filters, total matching count)."""

    @abstractmethod
    async def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        """Return the vehicle, or None if `vehicle_id` does not exist."""

    @abstractmethod
    async def update_vehicle_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        """Update the operational machine number. `vehicle_id` never changes."""

    @abstractmethod
    async def list_vehicle_components(self, vehicle_id: str) -> list[VehicleComponent]:
        """Return the component-role read model for one vehicle."""

    @abstractmethod
    async def list_vehicle_status_history(
        self, vehicle_id: str
    ) -> list[VehicleStatusHistoryEntry]:
        """Return all status-history entries for one vehicle, newest first."""

    @abstractmethod
    async def change_vehicle_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> VehicleStatusHistoryEntry:
        """Append a new status-history entry and update the vehicle's
        current status. Must never overwrite a previous entry."""

    # ---- Workshop equipment (Phase 2) ----

    @abstractmethod
    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> tuple[list[Equipment], int]:
        """Return (page of equipment matching the filters, total matching count)."""

    @abstractmethod
    async def get_equipment(self, equipment_id: str) -> Equipment | None:
        """Return the equipment item, or None if `equipment_id` does not exist."""

    # ---- Checklist / inspection (Phase 3) ----

    @abstractmethod
    async def get_active_checklist_revision(
        self, asset_type: AssetType
    ) -> ChecklistRevisionDetail | None:
        """Return the checklist revision currently effective for
        `asset_type`, with its items, or None if no checklist is configured
        for that asset type. Selection is by `effective_date` within one
        checklist family per asset type (see `app.domain.checklist` module
        docstring for why: OPEN_DECISIONS_REGISTER_EN.txt D01 has no
        approved asset/model assignment policy yet)."""

    @abstractmethod
    async def get_checklist_revision(
        self, checklist_id: str, revision_id: str
    ) -> ChecklistRevisionDetail | None:
        """Return one specific historical revision by ID, or None if it
        does not exist. Proves old revisions remain readable even after a
        newer revision becomes active."""

    @abstractmethod
    async def create_attachment(
        self,
        purpose: AttachmentPurpose,
        storage_ref: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        uploaded_by: str | None,
    ) -> Attachment:
        """Record metadata for a file already saved via StorageProvider."""

    @abstractmethod
    async def get_attachment(self, attachment_id: str) -> Attachment | None:
        """Return attachment metadata, or None if it does not exist."""

    @abstractmethod
    async def create_inspection(
        self,
        asset_type: AssetType,
        asset_id: str,
        checklist_id: str,
        revision_id: str,
        revision_number: int,
        inspector_user_id: str | None,
        overall_remark: str | None,
        items: list[NewInspectionItemInput],
    ) -> InspectionDetail:
        """Persist a new immutable inspection submission: header + item
        results + one OPEN finding per FAIL item. Must never mutate or
        remove any previously stored inspection."""

    @abstractmethod
    async def get_inspection(self, inspection_id: str) -> InspectionDetail | None:
        """Return one inspection submission, or None if it does not exist."""

    @abstractmethod
    async def list_inspections(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        params: PageParams,
    ) -> tuple[list[InspectionSummary], int]:
        """Return (page of inspection summaries newest first, total matching
        count), optionally filtered to one asset."""
