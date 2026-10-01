"""Shared "does this asset exist" check, reused by Phase 4's PM and Repair
services (mirrors `InspectionService._require_asset`'s identical Phase 3
logic/error codes exactly, without touching that frozen Phase 3 module).

Phase 7 Batch 7K2 (DEC-K1(b), DEC-K3(a), DEC-K10(a)): the EQUIPMENT branch
uses the validated, text-preserving exact lookup (`lookup_equipment`). The
known-hazard id guard is NOT part of `require_asset_exists` (read-only
callers use it too); mutating callers use `require_asset_for_new_work`,
which adds the guard after the lookup and before their first write. The
VEHICLE branch is unchanged.
"""
from __future__ import annotations

from fastapi import status

from app.domain.asset import AssetType
from app.domain.equipment import Equipment, EquipmentOperationalStatus
from app.domain.equipment_errors import (
    equipment_lookup_error,
    require_equipment_id_usable_for_new_work,
)
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryError


async def lookup_equipment(repository: Repository, equipment_id: str) -> Equipment | None:
    """Phase 7 Batch 7K2: validated exact equipment lookup with the shared
    equipment error mapping (409 ambiguous, 500 data/schema, 503 read)."""
    try:
        return await repository.get_equipment_validated(equipment_id)
    except RepositoryError as exc:
        mapped = equipment_lookup_error(exc)
        if mapped is None:
            raise
        raise mapped from exc


async def require_asset_exists(repository: Repository, asset_type: AssetType, asset_id: str) -> None:
    if asset_type == AssetType.VEHICLE:
        vehicle = await repository.get_vehicle(asset_id)
        if vehicle is None:
            raise ApiError(
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle '{asset_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
    else:
        equipment = await lookup_equipment(repository, asset_id)
        if equipment is None:
            raise ApiError(
                code="EQUIPMENT_NOT_FOUND",
                message=f"Equipment '{asset_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if equipment.operational_status == EquipmentOperationalStatus.RETIRED:
            # Core Demo Fix, EQUIPMENT STATUS CHANGE — APPROVED: RETIRED
            # equipment preserves all history but must not be selectable
            # for new normal operational work (PM/repair/part-instance).
            raise ApiError(
                code="EQUIPMENT_RETIRED",
                message=(
                    f"Equipment '{asset_id}' is RETIRED (ปลดระวาง/เลิกใช้งานถาวร) and "
                    "cannot be selected for new operational work"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )


async def require_asset_for_new_work(
    repository: Repository, asset_type: AssetType, asset_id: str
) -> None:
    """Phase 7 Batch 7K2 (DEC-K3(a)): `require_asset_exists`, then — for
    equipment only — refuse an id with a KNOWN text hazard (422
    EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK). Callers invoke it before their
    first write. Not detecting a hazard does not make an id safe."""
    await require_asset_exists(repository, asset_type, asset_id)
    if asset_type == AssetType.EQUIPMENT:
        require_equipment_id_usable_for_new_work(asset_id)
