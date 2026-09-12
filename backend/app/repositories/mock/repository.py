"""In-memory mock repository.

Runs fully offline with no external services. Used for local development
before Google Sheets credentials exist, and for fast automated tests.
Starting Phase 2, it holds seeded vehicle/model/equipment domain data
(see `seed_data.py`) so the domain/service layer and Web UI can be built
and tested before any Google Sheets schema exists.
"""
from __future__ import annotations

import copy

from app.domain.common import OperationalStatus, PageParams, utc_now
from app.domain.equipment import Equipment, EquipmentCategory
from app.domain.vehicle import Vehicle, VehicleComponent, VehicleStatusHistoryEntry
from app.domain.vehicle_model import VehicleModel
from app.repositories.base import Repository
from app.repositories.mock import seed_data


def _paginate(items: list, params: PageParams) -> tuple[list, int]:
    total = len(items)
    start = (params.page - 1) * params.page_size
    end = start + params.page_size
    return items[start:end], total


class MockRepository(Repository):
    def __init__(self) -> None:
        self._models: dict[str, VehicleModel] = {
            model.model_id: model.model_copy(deep=True) for model in seed_data.SEED_MODELS
        }
        self._vehicles: dict[str, Vehicle] = {
            vehicle.vehicle_id: vehicle.model_copy(deep=True)
            for vehicle in seed_data.SEED_VEHICLES
        }
        self._components: dict[str, list[VehicleComponent]] = copy.deepcopy(
            seed_data.build_seed_components()
        )
        self._status_history: dict[str, list[VehicleStatusHistoryEntry]] = copy.deepcopy(
            seed_data.build_seed_status_history()
        )
        self._equipment: dict[str, Equipment] = {
            item.equipment_id: item.model_copy(deep=True) for item in seed_data.SEED_EQUIPMENT
        }
        self._history_seq = len(self._vehicles)

    @property
    def mode(self) -> str:
        return "mock"

    async def check_ready(self) -> tuple[bool, str | None]:
        # Mock mode has no external dependency, so it is always ready.
        return True, None

    # ---- Vehicle model ----

    async def list_vehicle_models(
        self, q: str | None, params: PageParams
    ) -> tuple[list[VehicleModel], int]:
        models = list(self._models.values())
        if q:
            needle = q.strip().lower()
            models = [
                m
                for m in models
                if needle in m.model_code.lower() or needle in m.model_name.lower()
            ]
        models.sort(key=lambda m: m.model_id)
        page, total = _paginate(models, params)
        return page, total

    async def get_vehicle_model(self, model_id: str) -> VehicleModel | None:
        model = self._models.get(model_id)
        return model.model_copy(deep=True) if model else None

    # ---- Vehicle ----

    async def list_vehicles(
        self,
        q: str | None,
        operational_status: OperationalStatus | None,
        model_id: str | None,
        params: PageParams,
    ) -> tuple[list[Vehicle], int]:
        vehicles = list(self._vehicles.values())
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
        page, total = _paginate(vehicles, params)
        return page, total

    async def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        vehicle = self._vehicles.get(vehicle_id)
        return vehicle.model_copy(deep=True) if vehicle else None

    async def update_vehicle_machine_no(self, vehicle_id: str, machine_no: str) -> Vehicle:
        vehicle = self._vehicles[vehicle_id]
        updated = vehicle.model_copy(update={"machine_no": machine_no, "updated_at": utc_now()})
        self._vehicles[vehicle_id] = updated
        return updated.model_copy(deep=True)

    async def list_vehicle_components(self, vehicle_id: str) -> list[VehicleComponent]:
        return [c.model_copy(deep=True) for c in self._components.get(vehicle_id, [])]

    async def list_vehicle_status_history(
        self, vehicle_id: str
    ) -> list[VehicleStatusHistoryEntry]:
        entries = self._status_history.get(vehicle_id, [])
        ordered = sorted(entries, key=lambda e: e.changed_at, reverse=True)
        return [e.model_copy(deep=True) for e in ordered]

    async def change_vehicle_status(
        self,
        vehicle_id: str,
        new_status: OperationalStatus,
        changed_by: str | None,
        note: str | None,
    ) -> VehicleStatusHistoryEntry:
        vehicle = self._vehicles[vehicle_id]
        self._history_seq += 1
        entry = VehicleStatusHistoryEntry(
            history_id=f"STH-{self._history_seq:04d}",
            vehicle_id=vehicle_id,
            status=new_status,
            changed_at=utc_now(),
            changed_by=changed_by,
            note=note,
        )
        # Append-only: previous entries are never rewritten or removed.
        self._status_history.setdefault(vehicle_id, []).append(entry)
        self._vehicles[vehicle_id] = vehicle.model_copy(
            update={"operational_status": new_status, "updated_at": entry.changed_at}
        )
        return entry.model_copy(deep=True)

    # ---- Workshop equipment ----

    async def list_equipment(
        self, q: str | None, category: EquipmentCategory | None, params: PageParams
    ) -> tuple[list[Equipment], int]:
        items = list(self._equipment.values())
        if q:
            needle = q.strip().lower()
            items = [
                e
                for e in items
                if needle in e.name.lower() or needle in e.equipment_code.lower()
            ]
        if category is not None:
            items = [e for e in items if e.category == category]
        items.sort(key=lambda e: e.equipment_id)
        page, total = _paginate(items, params)
        return page, total

    async def get_equipment(self, equipment_id: str) -> Equipment | None:
        item = self._equipment.get(equipment_id)
        return item.model_copy(deep=True) if item else None
