"""Part Master and Part Set / Kit revision domain service (Phase 5; R6).

Part Master is created on demand (guardrails §12) — there is no
requirement to pre-load a company parts catalog before the system can
operate; `create_part` simply records a new specification the moment it
is identified. Different specifications always get a different `part_id`
(this service never merges two `create_part` calls just because their
`name` matches).

R6 additions (FINAL §8): `part_code` is unique within the data scope;
deactivate / reactivate keep history (no delete); an ALTERNATIVE set line
must name the line it substitutes (similar text alone never makes an
approved alternative); a Part Set applies to a vehicle model only through
an explicit `PartSetApplicability` row (AP-17); a PM work order's expected
parts are a READ-ONLY view of the set revision effective at the work order's
opening date. No R4 write path is changed and no compatibility is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import status

from app.domain.asset import AssetType
from app.domain.common import Page, PageParams, utc_now
from app.domain.part import (
    PartMaster,
    PartSet,
    PartSetApplicability,
    PartSetItemRequirement,
    PartSetRevisionDetail,
    TrackingMode,
)
from app.domain.part_instance_service import (
    commit,
    conflict,
    fingerprint,
    invalid,
    replayed_response,
    request_key,
    to_model,
)
from app.errors import ApiError
from app.repositories.base import PART_MASTERS, PART_SET_APPLICABILITY, PartMutation, Repository

OP_PART_CREATE = "PART_CREATE"
OP_PART_ACTIVE = "PART_SET_ACTIVE"
OP_APPLICABILITY = "PART_SET_APPLICABILITY_CREATE"


@dataclass(frozen=True)
class PartSetItemInput:
    part_id: str
    requirement: PartSetItemRequirement
    quantity: float | None = None
    unit: str | None = None
    note: str | None = None
    alternative_for_index: int | None = None


class PartService:
    def __init__(self, repository: Repository, data_context: str | None = None) -> None:
        self._repository = repository
        self._data_context = data_context

    async def create_part(
        self,
        part_code: str,
        name: str,
        specification: str | None,
        manufacturer: str | None,
        part_number: str | None,
        tracking_mode: TrackingMode,
        category: str | None,
        metadata: dict[str, str],
        *,
        actor: str | None = None,
        request_id: str | None = None,
        body: dict | None = None,
    ) -> PartMaster:
        key = request_key(self._data_context, "PART", "NEW:PART", request_id)
        digest = fingerprint(OP_PART_CREATE, "NEW:PART", actor, body or {})
        state = await self._repository.read_part_state()
        replay = replayed_response(state, key, OP_PART_CREATE, digest)
        if replay is not None:
            return to_model(PartMaster, replay)
        code = part_code.strip()
        if any(p.part_code.strip() == code for p in state.masters.values()):
            raise conflict("PART_CODE_DUPLICATE", f"Part code '{code}' is already used")
        (part_id,) = await self._repository.allocate_part_ids("PART")
        now = utc_now()
        part = PartMaster(part_id=part_id, part_code=part_code, name=name, specification=specification,
                          manufacturer=manufacturer, part_number=part_number, tracking_mode=tracking_mode,
                          category=category, is_active=True, metadata=dict(metadata), created_at=now, updated_at=now)
        response = await commit(self._repository, PartMutation(
            puts={PART_MASTERS: {part_id: part}}, request_key=key, operation=OP_PART_CREATE, fingerprint=digest,
            response=lambda s: s.masters[part_id].model_dump(mode="json")))
        return to_model(PartMaster, response)

    async def set_active(self, part_id: str, active: bool, *, actor: str | None, reason: str,
                         request_id: str, body: dict) -> PartMaster:
        """Deactivate / reactivate with a reason; history is kept (no delete).
        The reason and actor are recorded in the part's metadata audit keys."""
        if not reason.strip():
            raise invalid("VALIDATION_ERROR", "A reason is required")
        key = request_key(self._data_context, "PART", part_id, request_id)
        digest = fingerprint(OP_PART_ACTIVE, part_id, actor, body)
        state = await self._repository.read_part_state()
        replay = replayed_response(state, key, OP_PART_ACTIVE, digest)
        if replay is not None:
            return to_model(PartMaster, replay)
        part = state.masters.get(part_id)
        if part is None:
            raise ApiError(code="PART_NOT_FOUND", message=f"Part '{part_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        if part.is_active == active:
            raise conflict("PART_ACTIVE_STATE_UNCHANGED", f"Part '{part_id}' is already "
                           f"{'active' if active else 'inactive'}")
        now = utc_now()
        metadata = dict(part.metadata)
        metadata.update({"last_active_change_reason": reason.strip(), "last_active_change_by": actor or "",
                         "last_active_change_at": now.isoformat()})
        updated = part.model_copy(update={"is_active": active, "metadata": metadata, "updated_at": now})
        response = await commit(self._repository, PartMutation(
            puts={PART_MASTERS: {part_id: updated}}, request_key=key, operation=OP_PART_ACTIVE, fingerprint=digest,
            response=lambda s: s.masters[part_id].model_dump(mode="json")))
        return to_model(PartMaster, response)

    async def get_part(self, part_id: str) -> PartMaster:
        part = await self._repository.get_part_master(part_id)
        if part is None:
            raise ApiError(
                code="PART_NOT_FOUND",
                message=f"Part '{part_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return part

    async def list_parts(
        self, q: str | None, tracking_mode: TrackingMode | None, params: PageParams
    ) -> Page[PartMaster]:
        items, total = await self._repository.list_part_masters(
            q=q, tracking_mode=tracking_mode, params=params
        )
        return Page(items=items, page=params.page, page_size=params.page_size, total_items=total)

    # ---- Part Set / Kit revision ----

    async def create_part_set(self, set_code: str, name: str) -> PartSet:
        return await self._repository.create_part_set(set_code=set_code, name=name)

    async def _require_part_set(self, part_set_id: str) -> PartSet:
        part_set = await self._repository.get_part_set(part_set_id)
        if part_set is None:
            raise ApiError(
                code="PART_SET_NOT_FOUND",
                message=f"Part set '{part_set_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return part_set

    async def create_part_set_revision(
        self,
        part_set_id: str,
        effective_date: date,
        items: list[PartSetItemInput],
    ) -> PartSetRevisionDetail:
        await self._require_part_set(part_set_id)
        for item in items:
            await self.get_part(item.part_id)
        # R6: an ALTERNATIVE line must name (by index in this revision) the
        # REQUIRED / OPTIONAL line it may substitute; nothing else may.
        for index, item in enumerate(items):
            target = item.alternative_for_index
            if item.requirement == PartSetItemRequirement.ALTERNATIVE:
                if target is None or not (0 <= target < len(items)) or target == index:
                    raise invalid("PART_SET_ALTERNATIVE_UNLINKED",
                                  "An ALTERNATIVE line must name the line it substitutes (alternative_for_index)",
                                  {"item_index": index})
                if items[target].requirement == PartSetItemRequirement.ALTERNATIVE:
                    raise invalid("PART_SET_ALTERNATIVE_UNLINKED",
                                  "An ALTERNATIVE line must substitute a REQUIRED or OPTIONAL line",
                                  {"item_index": index})
            elif target is not None:
                raise invalid("VALIDATION_ERROR", "Only an ALTERNATIVE line may name alternative_for_index",
                              {"item_index": index})
        detail = await self._repository.create_part_set_revision(
            part_set_id=part_set_id,
            effective_date=effective_date,
            items=[
                {"part_id": i.part_id, "requirement": i.requirement, "quantity": i.quantity, "unit": i.unit,
                 "note": i.note, "alternative_for_index": i.alternative_for_index}
                for i in items
            ],
        )
        return detail

    async def get_active_part_set_revision(self, part_set_id: str) -> PartSetRevisionDetail:
        await self._require_part_set(part_set_id)
        detail = await self._repository.get_active_part_set_revision(part_set_id)
        if detail is None:
            raise ApiError(
                code="NO_ACTIVE_PART_SET_REVISION",
                message=f"No active revision is configured for part set '{part_set_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def get_part_set_revision(
        self, part_set_id: str, revision_id: str
    ) -> PartSetRevisionDetail:
        detail = await self._repository.get_part_set_revision(part_set_id, revision_id)
        if detail is None:
            raise ApiError(
                code="PART_SET_REVISION_NOT_FOUND",
                message=f"Part set revision '{revision_id}' was not found for set '{part_set_id}'",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    # ---- R6 applicability and expected sets ----

    async def add_applicability(self, part_set_id: str, *, model_id: str, pm_set_ref: str | None,
                                effective_from: date, document_ref: str | None, actor: str | None,
                                request_id: str, body: dict) -> PartSetApplicability:
        key = request_key(self._data_context, "PART_SET", part_set_id, request_id)
        digest = fingerprint(OP_APPLICABILITY, part_set_id, actor, body)
        state = await self._repository.read_part_state()
        replay = replayed_response(state, key, OP_APPLICABILITY, digest)
        if replay is not None:
            return to_model(PartSetApplicability, replay)
        await self._require_part_set(part_set_id)
        if await self._repository.get_vehicle_model(model_id) is None:
            raise ApiError(code="MODEL_NOT_FOUND", message=f"Vehicle model '{model_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        ref = (pm_set_ref or "").strip() or None
        if any(a.part_set_id == part_set_id and a.model_id == model_id and a.pm_set_ref == ref
               and a.effective_from == effective_from for a in state.applicability.values()):
            raise conflict("PART_SET_APPLICABILITY_DUPLICATE", "This applicability is already recorded")
        (applicability_id,) = await self._repository.allocate_part_ids("PSAPP")
        row = PartSetApplicability(applicability_id=applicability_id, part_set_id=part_set_id, model_id=model_id,
                                   pm_set_ref=ref, effective_from=effective_from, approved_by=actor,
                                   document_ref=(document_ref or "").strip() or None, created_at=utc_now())
        response = await commit(self._repository, PartMutation(
            puts={PART_SET_APPLICABILITY: {applicability_id: row}}, request_key=key, operation=OP_APPLICABILITY,
            fingerprint=digest, response=lambda s: s.applicability[applicability_id].model_dump(mode="json")))
        return to_model(PartSetApplicability, response)

    async def list_applicability(self, part_set_id: str) -> list[PartSetApplicability]:
        await self._require_part_set(part_set_id)
        state = await self._repository.read_part_state()
        return sorted((a for a in state.applicability.values() if a.part_set_id == part_set_id),
                      key=lambda a: a.applicability_id)

    async def expected_part_sets(self, pm_work_order_id: str) -> dict:
        """READ-ONLY: the Part Set revisions applicable to the work order's
        vehicle model, each at the revision effective on the work order's
        opening date. UNKNOWN when not determinable (no vehicle, no model, no
        applicability); never a guessed set. Actual used parts stay separate."""
        detail = await self._repository.get_pm_work_order(pm_work_order_id)
        if detail is None:
            raise ApiError(code="PM_WORK_ORDER_NOT_FOUND", message=f"PM work order '{pm_work_order_id}' was not found",
                           status_code=status.HTTP_404_NOT_FOUND)
        work_order = detail.work_order
        result = {"pm_work_order_id": pm_work_order_id, "status": "UNKNOWN", "reason": None, "model_id": None,
                  "as_of": work_order.opened_at.date().isoformat() if work_order.opened_at else None, "sets": []}
        if work_order.asset_type != AssetType.VEHICLE:
            result["reason"] = "NOT_A_VEHICLE"
            return result
        vehicle = await self._repository.get_vehicle(work_order.asset_id)
        if vehicle is None or not vehicle.model_id:
            result["reason"] = "VEHICLE_MODEL_UNKNOWN"
            return result
        result["model_id"] = vehicle.model_id
        as_of = work_order.opened_at.date() if work_order.opened_at else utc_now().date()
        state = await self._repository.read_part_state()
        rows = [a for a in state.applicability.values() if a.model_id == vehicle.model_id and a.effective_from <= as_of]
        if not rows:
            result["reason"] = "NO_APPLICABLE_PART_SET"
            return result
        sets = []
        for row in sorted(rows, key=lambda a: (a.part_set_id, a.applicability_id)):
            revisions = [r for r in state.set_revisions.values()
                         if r.part_set_id == row.part_set_id and r.effective_date <= as_of]
            if not revisions:
                sets.append({"part_set_id": row.part_set_id, "applicability_id": row.applicability_id,
                             "pm_set_ref": row.pm_set_ref, "revision": None, "items": [],
                             "reason": "NO_REVISION_EFFECTIVE_AT_OPENING"})
                continue
            revision = max(revisions, key=lambda r: (r.effective_date, r.revision_number))
            items = sorted(state.set_items.get(revision.revision_id, ()), key=lambda i: i.part_set_item_id)
            sets.append({"part_set_id": row.part_set_id, "applicability_id": row.applicability_id,
                         "pm_set_ref": row.pm_set_ref, "revision": revision.model_dump(mode="json"),
                         "items": [i.model_dump(mode="json") for i in items], "reason": None})
        result["status"] = "KNOWN"
        result["sets"] = sets
        return result
