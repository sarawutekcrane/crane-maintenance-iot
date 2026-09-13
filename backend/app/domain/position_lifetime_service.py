"""POSITION_LIFETIME domain service (Phase 5).

Enrolls asset+position lifetime tracking without requiring a serialized
`PartInstance` (baseline §13). `position_code` is never validated against
a company master list — G03 (Position Code Master) is unresolved; any
value the caller supplies is accepted structurally, exactly as free text.
"""
from __future__ import annotations

from fastapi import status

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists
from app.domain.meter_service import MeterService
from app.domain.part import TrackingMode
from app.domain.part_instance import PriorUsage
from app.domain.part_lookup import require_part_exists
from app.domain.position_lifetime import PositionLifetimeRecord
from app.errors import ApiError
from app.repositories.base import Repository


class PositionLifetimeService:
    def __init__(self, repository: Repository, meter_service: MeterService) -> None:
        self._repository = repository
        self._meter = meter_service

    async def create(
        self,
        asset_type: AssetType,
        asset_id: str,
        position_code: str,
        part_id: str | None,
        lifetime_rule_id: str | None,
        baseline_meter_snapshot_id: str | None,
        prior_usage: PriorUsage,
        started_by: str | None,
        note: str | None,
    ) -> PositionLifetimeRecord:
        await require_asset_exists(self._repository, asset_type, asset_id)
        if part_id is not None:
            part = await require_part_exists(self._repository, part_id)
            if part.tracking_mode != TrackingMode.POSITION_LIFETIME:
                raise ApiError(
                    code="PART_NOT_POSITION_LIFETIME",
                    message=(
                        f"Part '{part_id}' has tracking_mode='{part.tracking_mode.value}' — a "
                        "position-lifetime record may only reference a POSITION_LIFETIME part"
                    ),
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
        if lifetime_rule_id is not None:
            rule = await self._repository.get_lifetime_rule(lifetime_rule_id)
            if rule is None:
                raise ApiError(
                    code="LIFETIME_RULE_NOT_FOUND",
                    message=f"Lifetime rule '{lifetime_rule_id}' was not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        await self._meter.require_snapshot_exists(baseline_meter_snapshot_id)

        return await self._repository.create_position_lifetime(
            asset_type=asset_type,
            asset_id=asset_id,
            position_code=position_code,
            part_id=part_id,
            lifetime_rule_id=lifetime_rule_id,
            baseline_meter_snapshot_id=baseline_meter_snapshot_id,
            prior_usage=prior_usage,
            started_by=started_by,
            note=note,
        )

    async def get(self, position_lifetime_id: str) -> PositionLifetimeRecord:
        record = await self._repository.get_position_lifetime(position_lifetime_id)
        if record is None:
            raise ApiError(
                code="POSITION_LIFETIME_NOT_FOUND",
                message=f"Position lifetime record '{position_lifetime_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return record

    async def list_for_asset(
        self, asset_type: AssetType, asset_id: str
    ) -> list[PositionLifetimeRecord]:
        await require_asset_exists(self._repository, asset_type, asset_id)
        return await self._repository.list_position_lifetime_for_asset(asset_type, asset_id)
