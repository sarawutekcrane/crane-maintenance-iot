"""R2 Batch R2b — read-only responsible-branch history for workshop equipment.

A thin equipment adapter around the frozen R1 branch-history model
(`validate_branch_row`, `derive_timeline`, BHR1), which is reused unchanged.

Option C (reviewed R2b readiness report): the R1 envelope with the equipment
projection explicitly NOT_IN_SCHEMA. No equipment_master column is read for a
projection and none is assumed, so:

- `master` is always NOT_IN_SCHEMA;
- with history, consistency is UNDETERMINED (never CONSISTENT or
  PROJECTION_MISMATCH: there is nothing to compare against);
- with no history, consistency is NO_HISTORY and current is
  {branch_id: None, source: UNDETERMINED}. R1's "NONE" would claim the
  equipment authoritatively has no branch, which nothing establishes.

A baseline recorded in history is read exactly as recorded; none is derived
from equipment_master.

Order: data context -> accepted 7K2 equipment locate (its errors unchanged)
-> ONE asset_branch_history read -> this equipment's rows -> frozen
validation and derivation -> the no-history adaptation. No branch_master read.
"""
from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TypeVar

from app.domain.branch_timeline import (
    CONSISTENCY_NO_HISTORY,
    CONSISTENCY_UNDETERMINED,
    STATUS_INVALID,
    BranchTimeline,
    derive_timeline,
)
from app.domain.equipment_service import EquipmentService
from app.domain.registration import text
from app.domain.registry_errors import (
    data_context_not_configured,
    data_invalid,
    registry_tab_error,
)
from app.domain.vehicle_registry import STATE_NOT_IN_SCHEMA, RegistryField
from app.repositories.base import (
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
)

T = TypeVar("T")

ASSET_TYPE_EQUIPMENT = "EQUIPMENT"
CURRENT_SOURCE_UNDETERMINED = "UNDETERMINED"
# No equipment projection exists (Option C); never read from equipment_master.
EQUIPMENT_MASTER_PROJECTION = RegistryField(STATE_NOT_IN_SCHEMA)


def equipment_history_rows(rows: Sequence[Mapping[str, object]], equipment_id: str) -> list[Mapping[str, object]]:
    """One equipment's records, physical order: exact asset_id match (no trim
    or case change). VEHICLE rows belong to vehicles; any other asset_type
    (blank or malformed) with this asset_id IS returned, so validation reports
    ASSET_TYPE_INVALID instead of hiding it. Mirrors `vehicle_history_rows`."""
    return [
        r for r in rows
        if text(r.get("asset_id")) == equipment_id and text(r.get("asset_type")) != "VEHICLE"
    ]


def equipment_timeline(rows: Sequence[Mapping[str, object]], *, context: str) -> BranchTimeline:
    """The frozen R1 derivation with no projection, plus the no-history
    adaptation. INVALID timelines are returned unchanged (the caller fails)."""
    timeline = derive_timeline(rows, master_branch_id=None, master_available=False, context=context)
    if timeline.status == STATUS_INVALID:
        return timeline
    if not rows:
        return replace(timeline, current_branch_id=None, current_source=CURRENT_SOURCE_UNDETERMINED)
    assert timeline.consistency == CONSISTENCY_UNDETERMINED  # master_available=False with records
    return timeline


@dataclass(frozen=True)
class EquipmentBranchHistoryRead:
    equipment_id: str
    master: RegistryField
    timeline: BranchTimeline


class EquipmentBranchHistoryService:
    def __init__(self, repository: Repository, data_context: str | None) -> None:
        self._repository = repository
        self._context = data_context
        self._equipment = EquipmentService(repository)

    @staticmethod
    async def _history_tab(call: Awaitable[T]) -> T:
        """asset_branch_history failures -> the R1 BRANCH_HISTORY_* errors."""
        try:
            return await call
        except RepositoryFeatureNotImplementedError:
            raise
        except RepositoryError as exc:
            mapped = registry_tab_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

    async def branch_history(self, equipment_id: str) -> EquipmentBranchHistoryRead:
        if self._context is None:  # before any read (R1 §8.1)
            raise data_context_not_configured()
        equipment = await self._equipment.get_equipment(equipment_id)  # 7K2 locate and errors
        read = await self._history_tab(self._repository.read_asset_branch_history_validated())
        rows = equipment_history_rows(read.rows, equipment.equipment_id)
        timeline = equipment_timeline(rows, context=self._context)
        if timeline.status == STATUS_INVALID:
            raise data_invalid("asset_branch_history", timeline.issue_counts)
        assert timeline.consistency in (CONSISTENCY_NO_HISTORY, CONSISTENCY_UNDETERMINED)
        return EquipmentBranchHistoryRead(
            equipment_id=equipment.equipment_id, master=EQUIPMENT_MASTER_PROJECTION, timeline=timeline
        )
