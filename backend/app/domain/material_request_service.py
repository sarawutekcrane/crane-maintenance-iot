"""Material request (Store/Inventory integration boundary) domain
service — Core Demo Fixes Delta REV03 section D/H.

Shared by PM (automatic scope-approval requisition — see
`PmService.approve_scope`) and Repair (explicit, manual "ขอเบิกอะไหล่"
request — never automatic, never duplicating the Repair record). Never
implements a stock balance, warehouse approval, or purchasing workflow;
`request_status` stays a plain, unconstrained string.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import status

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.domain.requisition import MaterialRequestDetail, RequisitionSourceType
from app.errors import ApiError
from app.repositories.base import Repository

# A request is no longer "waiting" once material has been issued or the
# request itself is closed. Plain string comparison — no Store status
# transition matrix is enforced or invented (Delta section D).
_TERMINAL_REQUEST_STATUSES = frozenset({"ISSUED", "CLOSED"})


@dataclass(frozen=True)
class RequisitionLineInput:
    part_description: str
    quantity: float | None = None
    unit: str | None = None
    part_id: str | None = None
    part_instance_id: str | None = None
    part_code_snapshot: str | None = None
    line_source: str | None = None


class MaterialRequestService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def get(self, material_request_id: str) -> MaterialRequestDetail:
        detail = await self._repository.get_material_request(material_request_id)
        if detail is None:
            raise ApiError(
                code="MATERIAL_REQUEST_NOT_FOUND",
                message=f"Material request '{material_request_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return detail

    async def list_for_work_order(self, source_work_order_id: str):
        return await self._repository.list_material_requests_for_work_order(source_work_order_id)

    async def is_awaiting_parts(self, source_work_order_id: str) -> bool:
        """Core Demo Fixes Delta section H: "งานรออะไหล่" is a derived
        indicator from the open Repair plus related material request
        state — never a separate stored table/lifecycle."""
        requests = await self.list_for_work_order(source_work_order_id)
        return any(r.request_status not in _TERMINAL_REQUEST_STATUSES for r in requests)

    async def create(
        self,
        source_type: RequisitionSourceType,
        source_work_order_id: str,
        asset_type: AssetType,
        asset_id: str,
        lines: list[RequisitionLineInput],
        created_by: str | None,
        note: str | None = None,
    ) -> MaterialRequestDetail:
        """Explicit, manual material request (Delta section H — a repair
        requesting parts never automatically creates this; a caller must
        ask for it). PM's own automatic scope-approval requisition does
        not go through this method — see `PmService.approve_scope`."""
        await require_asset_exists(self._repository, asset_type, asset_id)
        vehicle_id = asset_id if asset_type == AssetType.VEHICLE else None
        for line in lines:
            if line.part_id is not None:
                await require_part_exists(self._repository, line.part_id)
            if line.part_instance_id is not None:
                await require_part_instance_exists(self._repository, line.part_instance_id)

        request = await self._repository.create_material_request(
            source_type=source_type,
            source_work_order_id=source_work_order_id,
            vehicle_id=vehicle_id,
            created_by=created_by,
            note=note,
        )
        for line in lines:
            await self._repository.create_requisition_line(
                material_request_id=request.material_request_id,
                part_id=line.part_id,
                part_instance_id=line.part_instance_id,
                part_code_snapshot=line.part_code_snapshot,
                part_description=line.part_description,
                requested_quantity=line.quantity,
                unit=line.unit,
                source_task_revision_id=None,
                line_source=line.line_source,
                created_by=created_by,
            )
        return await self.get(request.material_request_id)
