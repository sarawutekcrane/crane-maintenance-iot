"""INSTANCE_TRACKED part-instance domain service: on-demand enrollment,
install/remove/transfer, and lifecycle (overhaul) boundaries (Phase 5).

Enforces only the minimal technical guards a physical instance's own
consistency requires (see `app.domain.part_instance` module docstring for
the full G04/G05 governance reasoning):

- an instance may only be created for a part whose `tracking_mode` is
  `INSTANCE_TRACKED` (never for CONSUMABLE/POSITION_LIFETIME/NONE),
- an instance can never have two ACTIVE installation segments at once
  (duplicate active installation),
- `install` requires the instance is not currently INSTALLED and not
  SCRAPPED,
- `remove`/`transfer` require the instance is currently INSTALLED,
- `start_new_lifecycle` (overhaul) requires an explicit caller-supplied
  `approved_reason` and requires the instance not be currently INSTALLED
  (so a lifecycle boundary never splits an open usage segment).

Never invents a real overhaul-qualification rule, a real usage-correction
policy, or a real prior-usage value — see the module-level warnings in
`app.domain.part_instance`.
"""
from __future__ import annotations

from fastapi import status

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists
from app.domain.meter_service import MeterService
from app.domain.part import TrackingMode
from app.domain.part_instance import (
    InstallationSegmentStatus,
    LifecycleStartReason,
    PartInstanceDetail,
    PartInstanceStatus,
    PriorUsage,
)
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.errors import ApiError
from app.repositories.base import Repository

_REMOVAL_NEXT_STATUSES = frozenset(
    {
        PartInstanceStatus.REMOVED,
        PartInstanceStatus.IN_REPAIR,
        PartInstanceStatus.STOCK,
        PartInstanceStatus.SCRAPPED,
    }
)


class PartInstanceService:
    def __init__(self, repository: Repository, meter_service: MeterService) -> None:
        self._repository = repository
        self._meter = meter_service

    async def create_instance(
        self,
        part_id: str,
        serial_number: str | None,
        prior_usage: PriorUsage,
        note: str | None,
        created_by: str | None,
    ) -> PartInstanceDetail:
        part = await require_part_exists(self._repository, part_id)
        if part.tracking_mode != TrackingMode.INSTANCE_TRACKED:
            raise ApiError(
                code="PART_NOT_INSTANCE_TRACKED",
                message=(
                    f"Part '{part_id}' has tracking_mode='{part.tracking_mode.value}' — "
                    "a PartInstance may only be created for an INSTANCE_TRACKED part"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return await self._repository.create_part_instance(
            part_id=part_id,
            serial_number=serial_number,
            prior_usage=prior_usage,
            note=note,
            created_by=created_by,
        )

    async def get_instance(self, part_instance_id: str) -> PartInstanceDetail:
        return await require_part_instance_exists(self._repository, part_instance_id)

    async def install(
        self,
        part_instance_id: str,
        asset_type: AssetType,
        asset_id: str,
        position_code: str | None,
        baseline_meter_snapshot_id: str | None,
        installed_by: str | None,
        note: str | None,
    ) -> PartInstanceDetail:
        detail = await self.get_instance(part_instance_id)
        if detail.instance.status == PartInstanceStatus.INSTALLED:
            raise ApiError(
                code="PART_INSTANCE_ALREADY_INSTALLED",
                message=(
                    f"Part instance '{part_instance_id}' is already installed — remove or "
                    "transfer it before installing again (no duplicate active installation)"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if detail.instance.status == PartInstanceStatus.SCRAPPED:
            raise ApiError(
                code="PART_INSTANCE_SCRAPPED",
                message=f"Part instance '{part_instance_id}' is scrapped and cannot be installed",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        await require_asset_exists(self._repository, asset_type, asset_id)
        if baseline_meter_snapshot_id is not None:
            await self._meter.require_snapshot_exists(baseline_meter_snapshot_id)
        else:
            # Normal path: no manual counter/GPS entry on install — the
            # host asset's current machine state is captured automatically.
            snapshot = await self._meter.capture_current_state(
                asset_type=asset_type,
                asset_id=asset_id,
                recorded_by=installed_by,
                source_note="PART_INSTANCE_INSTALL",
            )
            baseline_meter_snapshot_id = snapshot.meter_snapshot_id

        await self._repository.create_installation_segment(
            part_instance_id=part_instance_id,
            lifecycle_id=detail.instance.current_lifecycle_id,
            asset_type=asset_type,
            asset_id=asset_id,
            position_code=position_code,
            installed_by=installed_by,
            baseline_meter_snapshot_id=baseline_meter_snapshot_id,
            install_note=note,
        )
        await self._repository.update_part_instance_status(
            part_instance_id, PartInstanceStatus.INSTALLED
        )
        return await self.get_instance(part_instance_id)

    def _active_segment(self, detail: PartInstanceDetail):
        for segment in detail.segments:
            if segment.status == InstallationSegmentStatus.ACTIVE:
                return segment
        return None

    async def remove(
        self,
        part_instance_id: str,
        next_status: PartInstanceStatus,
        removal_meter_snapshot_id: str | None,
        removal_reason: str | None,
        removed_by: str | None,
    ) -> PartInstanceDetail:
        detail = await self.get_instance(part_instance_id)
        if detail.instance.status != PartInstanceStatus.INSTALLED:
            raise ApiError(
                code="PART_INSTANCE_NOT_INSTALLED",
                message=f"Part instance '{part_instance_id}' is not currently installed",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if next_status not in _REMOVAL_NEXT_STATUSES:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=(
                    f"'{next_status.value}' is not a valid removal outcome — expected one of "
                    f"{sorted(s.value for s in _REMOVAL_NEXT_STATUSES)}"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        segment = self._active_segment(detail)
        if segment is None:
            raise ApiError(
                code="PART_INSTANCE_NOT_INSTALLED",
                message=f"Part instance '{part_instance_id}' has no active installation segment",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if removal_meter_snapshot_id is not None:
            await self._meter.require_snapshot_exists(removal_meter_snapshot_id)
        else:
            snapshot = await self._meter.capture_current_state(
                asset_type=segment.asset_type,
                asset_id=segment.asset_id,
                recorded_by=removed_by,
                source_note="PART_INSTANCE_REMOVE",
            )
            removal_meter_snapshot_id = snapshot.meter_snapshot_id
        await self._repository.close_installation_segment(
            segment.segment_id,
            removed_by=removed_by,
            removal_meter_snapshot_id=removal_meter_snapshot_id,
            removal_reason=removal_reason,
        )
        await self._repository.update_part_instance_status(part_instance_id, next_status)
        return await self.get_instance(part_instance_id)

    async def transfer(
        self,
        part_instance_id: str,
        target_asset_type: AssetType,
        target_asset_id: str,
        position_code: str | None,
        removal_meter_snapshot_id: str | None,
        baseline_meter_snapshot_id: str | None,
        removal_reason: str | None,
        transferred_by: str | None,
        note: str | None,
    ) -> PartInstanceDetail:
        detail = await self.get_instance(part_instance_id)
        if detail.instance.status != PartInstanceStatus.INSTALLED:
            raise ApiError(
                code="PART_INSTANCE_NOT_INSTALLED",
                message=f"Part instance '{part_instance_id}' is not currently installed",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        segment = self._active_segment(detail)
        if segment is None:
            raise ApiError(
                code="PART_INSTANCE_NOT_INSTALLED",
                message=f"Part instance '{part_instance_id}' has no active installation segment",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        await require_asset_exists(self._repository, target_asset_type, target_asset_id)
        if removal_meter_snapshot_id is not None:
            await self._meter.require_snapshot_exists(removal_meter_snapshot_id)
        else:
            removal_snapshot = await self._meter.capture_current_state(
                asset_type=segment.asset_type,
                asset_id=segment.asset_id,
                recorded_by=transferred_by,
                source_note="PART_INSTANCE_TRANSFER_OUT",
            )
            removal_meter_snapshot_id = removal_snapshot.meter_snapshot_id
        if baseline_meter_snapshot_id is not None:
            await self._meter.require_snapshot_exists(baseline_meter_snapshot_id)
        else:
            baseline_snapshot = await self._meter.capture_current_state(
                asset_type=target_asset_type,
                asset_id=target_asset_id,
                recorded_by=transferred_by,
                source_note="PART_INSTANCE_TRANSFER_IN",
            )
            baseline_meter_snapshot_id = baseline_snapshot.meter_snapshot_id

        # Close the current segment first (never edited in place afterward —
        # baseline §13 append-oriented history), then open a new one on the
        # target asset within the SAME lifecycle: a transfer never starts a
        # new lifecycle and never resets accumulated usage.
        await self._repository.close_installation_segment(
            segment.segment_id,
            removed_by=transferred_by,
            removal_meter_snapshot_id=removal_meter_snapshot_id,
            removal_reason=removal_reason or "TRANSFER",
        )
        await self._repository.create_installation_segment(
            part_instance_id=part_instance_id,
            lifecycle_id=detail.instance.current_lifecycle_id,
            asset_type=target_asset_type,
            asset_id=target_asset_id,
            position_code=position_code,
            installed_by=transferred_by,
            baseline_meter_snapshot_id=baseline_meter_snapshot_id,
            install_note=note,
        )
        # Status remains INSTALLED throughout — a transfer is not a removal.
        return await self.get_instance(part_instance_id)

    async def start_new_lifecycle(
        self,
        part_instance_id: str,
        approved_reason: str,
        started_by: str | None,
    ) -> PartInstanceDetail:
        if not approved_reason or not approved_reason.strip():
            raise ApiError(
                code="VALIDATION_ERROR",
                message=(
                    "approved_reason is required to start a new lifecycle — this service "
                    "never decides on its own that a repair qualifies as an overhaul (G04)"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        detail = await self.get_instance(part_instance_id)
        if detail.instance.status == PartInstanceStatus.INSTALLED:
            raise ApiError(
                code="PART_INSTANCE_INSTALLED",
                message=(
                    f"Part instance '{part_instance_id}' is currently installed — remove it "
                    "before starting a new lifecycle, so a lifecycle boundary never splits "
                    "an open installation segment"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        await self._repository.start_new_part_lifecycle(
            part_instance_id=part_instance_id,
            start_reason=LifecycleStartReason.OVERHAUL,
            started_note=approved_reason,
            started_by=started_by,
        )
        return await self.get_instance(part_instance_id)
