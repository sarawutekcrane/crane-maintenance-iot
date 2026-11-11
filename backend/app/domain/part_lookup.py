"""Shared "does this part/instance exist" checks (Phase 5), mirroring
`app.domain.asset_lookup.require_asset_exists`'s pattern exactly. Used by
`PartInstanceService`, `PositionLifetimeService`, `LifetimeRuleService`,
and — when an actual PM/Repair part record links to a `PartMaster`/
`PartInstance` — by `PmService`/`RepairService`.
"""
from __future__ import annotations

from fastapi import status

from app.domain.part import PartMaster
from app.domain.part_instance import PartInstanceDetail
from app.errors import ApiError
from app.repositories.base import Repository


async def require_part_exists(repository: Repository, part_id: str) -> PartMaster:
    part = await repository.get_part_master(part_id)
    if part is None:
        raise ApiError(
            code="PART_NOT_FOUND",
            message=f"Part '{part_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return part


async def require_part_instance_exists(
    repository: Repository, part_instance_id: str
) -> PartInstanceDetail:
    detail = await repository.get_part_instance(part_instance_id)
    if detail is None:
        raise ApiError(
            code="PART_INSTANCE_NOT_FOUND",
            message=f"Part instance '{part_instance_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return detail


async def require_instance_of_part(repository: Repository, part_id: str | None,
                                   part_instance_id: str | None) -> None:
    """R6 (FINAL §3.2 B1): an actual PM / Repair / Material-request part record
    that names both a Part Master and a Part Instance must name an instance OF
    that part (never an instance of a different specification). Each id is
    still validated on its own by the existing checks."""
    if part_id is None or part_instance_id is None:
        return
    detail = await require_part_instance_exists(repository, part_instance_id)
    if detail.instance.part_id != part_id:
        raise ApiError(
            code="PART_INSTANCE_PART_MISMATCH",
            message=f"Part instance '{part_instance_id}' is an instance of '{detail.instance.part_id}', "
                    f"not '{part_id}'",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"part_id": part_id, "part_instance_id": part_instance_id},
        )
