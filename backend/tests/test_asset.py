from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.asset import AssetRef, AssetType


def test_asset_ref_holds_vehicle_or_equipment() -> None:
    vehicle_ref = AssetRef(asset_type=AssetType.VEHICLE, asset_id="VEH-1046")
    equipment_ref = AssetRef(asset_type=AssetType.EQUIPMENT, asset_id="EQP-0001")

    assert vehicle_ref.asset_type == AssetType.VEHICLE
    assert equipment_ref.asset_type == AssetType.EQUIPMENT


def test_asset_ref_rejects_empty_asset_id() -> None:
    with pytest.raises(ValidationError):
        AssetRef(asset_type=AssetType.VEHICLE, asset_id="")
