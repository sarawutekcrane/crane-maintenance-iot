"""POSITION_LIFETIME domain service (Phase 5; R6 FINAL §7.1, §7.5, §7.6).

Enrolls position lifetime tracking without requiring a serialized
`PartInstance` (baseline §13). `position_code` is never validated against
a company master list — G03 / PG-4 (Position Code Master) is unresolved; any
value is accepted as free text and matched exactly after trimming.

R6 additions:
- a record is hosted EITHER by an asset position OR by a part instance
  (`host_part_instance_id`, e.g. a seal inside a cylinder). A hosted record
  stores no asset placement: it is always derived from the host's active
  installation segment, so the seal follows its cylinder (O-4);
- `replace` atomically ends the current record and opens its successor (a
  seal replacement resets only the seal's record; the cylinder is untouched);
- every write is idempotent on `X-Request-Id`, atomic, and validated against
  the cross-mode occupancy invariants O-1…O-4.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import status

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists, require_asset_for_new_work
from app.domain.common import utc_now
from app.domain.meter_service import MeterService
from app.domain.part import TrackingMode
from app.domain.part_instance import InstallationSegmentStatus, PriorUsage, position_key
from app.domain.part_instance_service import (
    commit,
    conflict,
    fingerprint,
    invalid,
    replayed_response,
    request_key,
    require_asset_scope,
    require_data_context,
    require_segments_scope,
    resolve_effective,
    to_model,
    validate_declaration,
    validate_maintenance_target,
    verified_anchors,
)
from app.domain.part_lookup import require_part_exists
from app.domain.part_maintenance_event import MaintenanceAction, MaintenanceTargetType, PartMaintenanceEvent
from app.domain.position_lifetime import PositionLifetimeRecord
from app.errors import ApiError
from app.repositories.base import PART_MAINTENANCE, PART_POSITIONS, PartMutation, PartState, Repository

OP_POSITION_CREATE = "POSITION_CREATE"
OP_POSITION_REPLACE = "POSITION_REPLACE"
OP_POSITION_MAINTENANCE = "POSITION_MAINTENANCE_EVENT"


class PositionLifetimeService:
    def __init__(self, repository: Repository, meter_service: MeterService, cutover=None,
                 part_meter_source=None) -> None:
        self._repository = repository
        self._meter = meter_service
        self._data_context = cutover.data_context if cutover is not None else None
        self._batch_id = cutover.test_batch_id if cutover is not None else ""
        self._source = part_meter_source if part_meter_source is not None else meter_service.iot_meter_source

    async def _record_scope(self, state: PartState, record: PositionLifetimeRecord) -> None:
        """CG-1: an asset-hosted record is in scope iff its asset is; an
        instance-hosted record iff every asset its host was ever installed on is."""
        if record.host_part_instance_id:
            await require_segments_scope(self._repository, state.segments.get(record.host_part_instance_id, ()),
                                         self._data_context, self._batch_id)
        else:
            await require_asset_scope(self._repository, record.asset_type, record.asset_id, self._data_context,
                                      self._batch_id)

    async def _anchors_for(self, state: PartState, asset_type, asset_id, host_id, at):
        if host_id:
            for segment in state.segments.get(host_id, ()):
                if segment.status == InstallationSegmentStatus.ACTIVE:
                    asset_type, asset_id = segment.asset_type, segment.asset_id
                    break
            else:
                return []
        if asset_type != AssetType.VEHICLE or not asset_id:
            return []
        return await verified_anchors(self._repository, self._source, asset_id, at)

    async def create(
        self,
        asset_type: AssetType | None,
        asset_id: str | None,
        position_code: str,
        part_id: str | None,
        lifetime_rule_id: str | None,
        baseline_meter_snapshot_id: str | None,
        prior_usage: PriorUsage,
        started_by: str | None,
        note: str | None,
        *,
        host_part_instance_id: str | None = None,
        effective_at: datetime | None = None,
        request_id: str | None = None,
        body: dict | None = None,
    ) -> PositionLifetimeRecord:
        host_id = (host_part_instance_id or "").strip() or None
        if host_id is None:
            if asset_type is None or not (asset_id or "").strip():
                raise invalid("VALIDATION_ERROR", "asset_type and asset_id are required unless host_part_instance_id "
                              "is given")
            await require_asset_for_new_work(self._repository, asset_type, asset_id)
        elif asset_type is not None or asset_id:
            raise invalid("HOSTED_RECORD_ASSET_FORBIDDEN",
                          "An instance-hosted record has no own asset placement (it follows its host instance)")
        data_context = require_data_context(self._data_context, self._batch_id)
        resource = f"NEW:POSITION:{host_id or f'{asset_type.value}:{asset_id}'}:{position_code}"
        key = request_key(data_context, "POSITION", resource, request_id)
        digest = fingerprint(OP_POSITION_CREATE, resource, started_by, body or {})
        state = await self._repository.read_part_state()
        # CG-1: data scope of the placement (the asset, or every asset of the host instance) BEFORE the replay
        # lookup and before any capture or write.
        if host_id is not None:
            host = state.instances.get(host_id)
            if host is None:
                raise ApiError(code="PART_INSTANCE_NOT_FOUND", message=f"Part instance '{host_id}' was not found",
                               status_code=status.HTTP_404_NOT_FOUND)
            await require_segments_scope(self._repository, state.segments.get(host_id, ()), self._data_context,
                                         self._batch_id)
        else:
            await require_asset_scope(self._repository, asset_type, asset_id, self._data_context, self._batch_id)
        replay = replayed_response(state, key, OP_POSITION_CREATE, digest)
        if replay is not None:
            return to_model(PositionLifetimeRecord, replay)
        if part_id is not None:
            part = await require_part_exists(self._repository, part_id)
            if part.tracking_mode == TrackingMode.INSTANCE_TRACKED and host_id is not None:
                raise invalid("NESTED_INSTANCE_UNSUPPORTED",
                              "A part instance inside another part instance is not supported in R6")
            if part.tracking_mode != TrackingMode.POSITION_LIFETIME:
                raise invalid("PART_NOT_POSITION_LIFETIME",
                              f"Part '{part_id}' has tracking_mode='{part.tracking_mode.value}' — a "
                              "position-lifetime record may only reference a POSITION_LIFETIME part")
        if lifetime_rule_id is not None and await self._repository.get_lifetime_rule(lifetime_rule_id) is None:
            raise ApiError(code="LIFETIME_RULE_NOT_FOUND", message=f"Lifetime rule '{lifetime_rule_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        await self._meter.require_snapshot_exists(baseline_meter_snapshot_id)
        now = utc_now()
        prior = await validate_declaration(self._repository, prior_usage, actor=started_by, now=now,
                                           field="prior_usage")
        at = resolve_effective(effective_at, now, None)
        anchors = await self._anchors_for(state, asset_type, asset_id, host_id, at)
        (record_id,) = await self._repository.allocate_part_ids("POSLT")
        record = PositionLifetimeRecord(position_lifetime_id=record_id, asset_type=None if host_id else asset_type,
                                        asset_id=None if host_id else asset_id, position_code=position_code,
                                        part_id=part_id, lifetime_rule_id=lifetime_rule_id,
                                        baseline_meter_snapshot_id=baseline_meter_snapshot_id, prior_usage=prior,
                                        started_at=now, started_effective_at=at, started_by=started_by, note=note,
                                        host_part_instance_id=host_id, baseline_anchors=anchors, request_id=request_id)
        response = await commit(self._repository, PartMutation(
            puts={PART_POSITIONS: {record_id: record}}, request_key=key, operation=OP_POSITION_CREATE,
            fingerprint=digest, response=lambda s: s.positions[record_id].model_dump(mode="json")))
        return to_model(PositionLifetimeRecord, response)

    async def replace(self, position_lifetime_id: str, *, actor: str | None, reason: str | None,
                      part_id: str | None, prior_usage: PriorUsage, effective_at: datetime | None,
                      end_snapshot_id: str | None, note: str | None, request_id: str, body: dict) -> dict:
        """End the current record and open its successor at the same placement
        in ONE commit (O-5). The predecessor is never deleted or rewritten
        beyond its end fields."""
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "POSITION", position_lifetime_id, request_id)
        digest = fingerprint(OP_POSITION_REPLACE, position_lifetime_id, actor, body)
        state = await self._repository.read_part_state()
        if position_lifetime_id in state.positions:
            await self._record_scope(state, state.positions[position_lifetime_id])  # CG-1, before replay
        replay = replayed_response(state, key, OP_POSITION_REPLACE, digest)
        if replay is not None:
            return replay
        record = state.positions.get(position_lifetime_id)
        if record is None:
            raise ApiError(code="POSITION_LIFETIME_NOT_FOUND",
                           message=f"Position lifetime record '{position_lifetime_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        if record.ended_at is not None:
            raise conflict("POSITION_LIFETIME_ALREADY_ENDED", "This record was already replaced",
                           {"superseded_by_id": record.superseded_by_id})
        new_part = part_id if part_id is not None else record.part_id
        if new_part is not None:
            part = await require_part_exists(self._repository, new_part)
            if part.tracking_mode != TrackingMode.POSITION_LIFETIME:
                raise invalid("PART_NOT_POSITION_LIFETIME", "A position-lifetime record needs a POSITION_LIFETIME part")
        await self._meter.require_snapshot_exists(end_snapshot_id)
        now = utc_now()
        prior = await validate_declaration(self._repository, prior_usage, actor=actor, now=now, field="prior_usage")
        at = resolve_effective(effective_at, now, record.effective_start)
        anchors = await self._anchors_for(state, record.asset_type, record.asset_id, record.host_part_instance_id, at)
        (successor_id,) = await self._repository.allocate_part_ids("POSLT")
        ended = record.model_copy(update={"ended_at": now, "ended_effective_at": at, "end_snapshot_id": end_snapshot_id,
                                          "end_reason": reason, "superseded_by_id": successor_id,
                                          "end_anchors": anchors})
        successor = PositionLifetimeRecord(
            position_lifetime_id=successor_id, asset_type=record.asset_type, asset_id=record.asset_id,
            position_code=record.position_code, part_id=new_part, lifetime_rule_id=record.lifetime_rule_id,
            prior_usage=prior, started_at=now, started_effective_at=at, started_by=actor, note=note,
            host_part_instance_id=record.host_part_instance_id, baseline_anchors=anchors, request_id=request_id)
        return await commit(self._repository, PartMutation(
            puts={PART_POSITIONS: {position_lifetime_id: ended, successor_id: successor}}, request_key=key,
            operation=OP_POSITION_REPLACE, fingerprint=digest,
            response=lambda s: {"ended": s.positions[position_lifetime_id].model_dump(mode="json"),
                                "successor": s.positions[successor_id].model_dump(mode="json")}))

    async def add_maintenance_event(self, position_lifetime_id: str, *, actor: str | None,
                                    action: MaintenanceAction, lifetime_rule_id: str | None,
                                    condition_group_key: str | None, outcome: str | None,
                                    effective_at: datetime | None, source_type: str | None, source_id: str | None,
                                    note: str | None, request_id: str, body: dict) -> dict:
        data_context = require_data_context(self._data_context, self._batch_id)
        key = request_key(data_context, "POSITION", position_lifetime_id, request_id)
        digest = fingerprint(OP_POSITION_MAINTENANCE, position_lifetime_id, actor, body)
        state = await self._repository.read_part_state()
        if position_lifetime_id in state.positions:
            await self._record_scope(state, state.positions[position_lifetime_id])  # CG-1, before replay
        replay = replayed_response(state, key, OP_POSITION_MAINTENANCE, digest)
        if replay is not None:
            return replay
        record = state.positions.get(position_lifetime_id)
        if record is None:
            raise ApiError(code="POSITION_LIFETIME_NOT_FOUND",
                           message=f"Position lifetime record '{position_lifetime_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        if record.ended_at is not None:
            raise conflict("POSITION_LIFETIME_ALREADY_ENDED", "This record was already replaced")
        validate_maintenance_target(state, record.part_id, action, lifetime_rule_id, condition_group_key)
        now = utc_now()
        existing = state.maintenance.get(position_lifetime_id, ())
        latest = max([record.effective_start] + [e.effective_at for e in existing])
        at = resolve_effective(effective_at, now, latest)
        anchors = await self._anchors_for(state, record.asset_type, record.asset_id, record.host_part_instance_id, at)
        (event_id,) = await self._repository.allocate_part_ids("PME")
        event = PartMaintenanceEvent(event_id=event_id, target_type=MaintenanceTargetType.POSITION_LIFETIME,
                                     target_id=position_lifetime_id, lifetime_rule_id=lifetime_rule_id,
                                     condition_group_key=condition_group_key, action=action, outcome=outcome,
                                     lifecycle_id=position_lifetime_id, effective_at=at, recorded_at=now, actor=actor,
                                     anchors=anchors, source_type=source_type, source_id=source_id, note=note,
                                     request_id=request_id)
        return await commit(self._repository, PartMutation(
            puts={PART_MAINTENANCE: {position_lifetime_id: existing + (event,)}}, request_key=key,
            operation=OP_POSITION_MAINTENANCE, fingerprint=digest,
            response=lambda s: s.maintenance[position_lifetime_id][-1].model_dump(mode="json")))

    async def get(self, position_lifetime_id: str) -> PositionLifetimeRecord:
        record = await self._repository.get_position_lifetime(position_lifetime_id)
        if record is None:
            raise ApiError(
                code="POSITION_LIFETIME_NOT_FOUND",
                message=f"Position lifetime record '{position_lifetime_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        await self._record_scope(await self._repository.read_part_state(), record)  # CG-1 read isolation
        return record

    async def list_for_asset(self, asset_type: AssetType, asset_id: str) -> list[PositionLifetimeRecord]:
        await require_asset_exists(self._repository, asset_type, asset_id)
        await require_asset_scope(self._repository, asset_type, asset_id, self._data_context, self._batch_id)
        return await self._repository.list_position_lifetime_for_asset(asset_type, asset_id)

    async def list_for_host(self, host_part_instance_id: str) -> list[PositionLifetimeRecord]:
        state = await self._repository.read_part_state()
        await require_segments_scope(self._repository, state.segments.get(host_part_instance_id, ()),
                                     self._data_context, self._batch_id)  # CG-1 read isolation
        records = [r for r in state.positions.values() if r.host_part_instance_id == host_part_instance_id]
        records.sort(key=lambda r: (r.started_at, r.position_lifetime_id))
        return records


__all__ = ["PositionLifetimeService", "position_key"]
