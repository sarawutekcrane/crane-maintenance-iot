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
from app.domain.asset_lookup import require_asset_for_new_work
from app.domain.meter_service import MeterService
from app.domain.part_lookup import require_part_exists, require_part_instance_exists
from app.domain.pm import PmWorkOrderStatus
from app.domain.pm_service import PmService
from app.domain.requisition import MaterialRequestDetail, RequisitionSourceType
from app.domain.technician_assignment import (
    PM,
    REPAIR,
    AssignmentCutover,
    require_v2_job_in_scope,
    require_v2_write_context,
)
from app.errors import ApiError
from app.repositories.base import Repository

# A request is no longer "waiting" once material has been issued or the
# request itself is closed. Plain string comparison — no Store status
# transition matrix is enforced or invented (Delta section D).
_TERMINAL_REQUEST_STATUSES = frozenset({"ISSUED", "CLOSED"})


# EV-048: the V2 PM statuses in which a manual Store request may be raised.
_PM_STORE_STATUSES = frozenset({PmWorkOrderStatus.OPEN, PmWorkOrderStatus.IN_PROGRESS})


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
    def __init__(self, repository: Repository, assignment_cutover: AssignmentCutover) -> None:
        self._repository = repository
        # DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107: the server's TEST/REAL context, used to prove that a
        # new request's source work order is a Technician V2 job inside the server's own data scope.
        self._cutover = assignment_cutover

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
        not go through this method — see `PmService.approve_scope`.

        EV-048 (RR-1): a PM-source request needs an existing PM work order; for
        a V2 one it is written only while the authoritative (journal) status is
        OPEN or IN_PROGRESS, under the same work-order lock as every PM
        transition, so none can appear between CANCEL's eligibility check and
        its transition. Who may raise a request is unchanged (D6 is a separate
        Owner decision).

        DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107 (Legacy cancelled): the
        source — PM or Repair — must be an existing Technician V2 work order inside
        the server's TEST/REAL scope (never a client-supplied flag). A missing
        source is 404, a Legacy one 409 ASSIGNMENT_MODEL_MISMATCH, an unknown model
        or invalid scope flags 500, another scope 409, an asset that is not the
        source's own asset 409 MATERIAL_REQUEST_SOURCE_ASSET_MISMATCH; every
        refusal writes nothing (checked after the established input checks and
        before the first write)."""
        if source_type == RequisitionSourceType.REPAIR:
            async def verify_repair_source() -> None:
                repair = await self._repository.get_repair(source_work_order_id)
                if repair is None:
                    raise ApiError(code="REPAIR_NOT_FOUND", message=f"Repair '{source_work_order_id}' was not found",
                                   status_code=status.HTTP_404_NOT_FOUND)
                await self._require_v2_source(REPAIR, repair.repair, asset_type, asset_id)

            return await self._create(source_type, source_work_order_id, asset_type, asset_id, lines, created_by,
                                      note, verify_repair_source)
        if source_type != RequisitionSourceType.PM:
            raise ApiError(code="MATERIAL_REQUEST_SOURCE_INVALID", message="Unsupported material request source",
                           status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        guard = PmService(self._repository, MeterService(self._repository)).linked_write_guard(
            source_work_order_id, _PM_STORE_STATUSES, "PM_STORE_REQUEST_NOT_ALLOWED",
            "A Store request can be raised for a PM work order only while it is OPEN or IN_PROGRESS; nothing was "
            "changed")
        async with guard as work_order:
            if work_order is None:
                raise ApiError(code="PM_WORK_ORDER_NOT_FOUND",
                               message=f"PM work order '{source_work_order_id}' was not found",
                               status_code=status.HTTP_404_NOT_FOUND)
            async def verify_pm_source() -> None:
                await self._require_v2_source(PM, work_order.work_order, asset_type, asset_id)

            return await self._create(source_type, source_work_order_id, asset_type, asset_id, lines, created_by,
                                      note, verify_pm_source)

    async def _require_v2_source(self, kind, job, asset_type: AssetType, asset_id: str) -> None:
        context = await require_v2_write_context(self._cutover, self._repository)
        require_v2_job_in_scope(kind, job, context, self._cutover.test_batch_id)
        # R4 / TASK-010: the request's asset must be the source work order's own asset (never trusted
        # from the client alone). The stored asset is not echoed back.
        if job.asset_type != asset_type or job.asset_id != asset_id:
            raise ApiError(code="MATERIAL_REQUEST_SOURCE_ASSET_MISMATCH",
                           message="The requested asset is not the source work order's asset; nothing was created",
                           status_code=status.HTTP_409_CONFLICT,
                           details={"source_work_order_id": getattr(job, kind.job_id_column)})

    async def _create(self, source_type: RequisitionSourceType, source_work_order_id: str, asset_type: AssetType,
                      asset_id: str, lines: list[RequisitionLineInput], created_by: str | None,
                      note: str | None, verify_source) -> MaterialRequestDetail:
        await require_asset_for_new_work(self._repository, asset_type, asset_id)
        vehicle_id = asset_id if asset_type == AssetType.VEHICLE else None
        for line in lines:
            if line.part_id is not None:
                await require_part_exists(self._repository, line.part_id)
            if line.part_instance_id is not None:
                await require_part_instance_exists(self._repository, line.part_instance_id)
        # The established input checks keep their order; the V2 source proof runs after them and
        # before the first write, so a refused source still writes nothing.
        await verify_source()

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
