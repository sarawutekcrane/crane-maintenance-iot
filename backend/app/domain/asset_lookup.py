"""Shared "does this asset exist" check, reused by Phase 4's PM and Repair
services (mirrors `InspectionService._require_asset`'s identical Phase 3
logic/error codes exactly, without touching that frozen Phase 3 module).
"""
from __future__ import annotations

from fastapi import status

from app.domain.asset import AssetType
from app.domain.equipment import EquipmentOperationalStatus
from app.errors import ApiError
from app.repositories.base import Repository


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
        equipment = await repository.get_equipment(asset_id)
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
