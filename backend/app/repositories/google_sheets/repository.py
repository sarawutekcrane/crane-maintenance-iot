"""Google Sheets-backed repository (base adapter).

Implements the same `Repository` interface as `MockRepository`. The
domain/service layer must not know or care which one is active; only
`app.dependencies` (composition root) decides based on `DATA_REPOSITORY`.

Per scope item 14 of the Phase 2 prompt ("Implement repository mappings
first in MockRepository, then GoogleSheetsRepository when local Google
credentials are available"): the domain-entity methods below are wired to
the declared tab schemas (`app.repositories.google_sheets.schemas`) but
raise a controlled `RepositoryError` until real
`GOOGLE_SHEET_ID`/`GOOGLE_APPLICATION_CREDENTIALS` are configured on the
developer's machine, and `NotImplementedError` beyond that point — the
same pattern `validate_schema` already used in Phase 1. This keeps the
Repository contract honest: the interface is fully implemented, but the
Google Sheets I/O itself is completed once it can actually be exercised
against the prototype spreadsheet (this sandboxed environment has no
Google credentials or network path to test it).
"""
from __future__ import annotations

from app.config import Settings
from app.domain.common import OperationalStatus, PageParams
from app.domain.equipment import Equipment, EquipmentCategory
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import VehicleModel
from app.repositories.base import Repository, RepositoryError
from app.repositories.google_sheets.client import GoogleSheetsClient
from app.repositories.google_sheets import schemas


class GoogleSheetsRepository(Repository):
    def __init__(self, settings: Settings) -> None:
        self._client = GoogleSheetsClient(settings)

    @property
    def mode(self) -> str:
        return "google_sheets"

    async def check_ready(self) -> tuple[bool, str | None]:
        return await self._client.verify_connectivity()

    def _require_configured(self, entity: str) -> None:
        if not self._client.is_configured:
            raise RepositoryError(
                f"Cannot read/write '{entity}': GOOGLE_SHEET_ID / "
                "GOOGLE_APPLICATION_CREDENTIALS are not configured. See "
                "docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt "
                "section 6 to connect a local Google Sheets prototype."
            )
        raise NotImplementedError(
            f"Google Sheets read/write for '{entity}' (tab schema declared in "
            "app.repositories.google_sheets.schemas) is implemented once local "
            "credentials are available and the tab/header schema is validated "
            "against the prototype spreadsheet."
        )

    # ---- Vehicle model ----

    async def list_vehicle_models(
        self, q: str | None, params: PageParams
    ) -> tuple[list[VehicleModel], int]:
        self._require_configured(schemas.VEHICLE_MODEL_SHEET.tab_name)

    async def get_vehicle_model(self, model_id: str) -> VehicleModel | None:
        self._require_configured(schemas.VEHICLE_MODEL_SHEET.tab_name)

    # ---- Vehicle ----

    async def list_vehicles(
        self,
        q: str | None,
        operational_status: OperationalStatus | None,
        model_id: str | None,
        params: PageParams,
    ) -> tuple[list[Vehicle], int]:
        self._require_configured(schemas.VEHICLE_SHEET.tab_name)

    async def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        self._require_configured(schemas.VEHICLE_SHEET.tab_name)

    async def update_vehicle_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        self._require_configured(schemas.VEHICLE_SHEET.tab_name)

    async def list_vehicle_components(self, vehicle_id: str) -> list[VehicleComponent]:
        self._require_configured(schemas.VEHICLE_COMPONENT_SHEET.tab_name)

    async def list_vehicle_status_history(
        self, vehicle_id: str
    ) -> list[VehicleStatusHistoryEntry]:
        self._require_configured(schemas.VEHICLE_STATUS_HISTORY_SHEET.tab_name)

    async def change_vehicle_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> VehicleStatusHistoryEntry:
        self._require_configured(schemas.VEHICLE_STATUS_HISTORY_SHEET.tab_name)

    # ---- Workshop equipment ----

    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> tuple[list[Equipment], int]:
        self._require_configured(schemas.EQUIPMENT_SHEET.tab_name)

    async def get_equipment(self, equipment_id: str) -> Equipment | None:
        self._require_configured(schemas.EQUIPMENT_SHEET.tab_name)
