"""R2 Batch R2f-b — Personnel ↔ Technician link spec (Final Contract C1 §5).

Authority: `personnel_master.technician_id` (0..1 ↔ 0..1, exact id only).
Durable audit: the SEPARATE append-only `personnel_technician_link_history`
tab with the frozen header below. The tab does NOT exist live yet: it is never
auto-created and a missing tab fails closed
(PERSONNEL_TECHNICIAN_LINK_HISTORY_SCHEMA_INVALID); it is not part of the
global readiness schemas. Existing technician_id values with no history are
valid baseline state (NO_HISTORY); no migration is needed.

Targets are resolved through the R2f-a bounded technician_master read; a TEST
link may target only an explicitly TEST-scoped technician of the same batch
(the live tab is untagged, so a live TEST link fails closed).
"""
from __future__ import annotations

from app.domain.personnel import PERSONNEL_PUBLIC_COLUMNS
from app.domain.personnel_link import LinkSpec, PersonnelLinkService
from app.repositories.base import PERSONNEL_LINK_TECHNICIAN, Repository

PERSONNEL_TECHNICIAN_LINK_HISTORY_TAB = "personnel_technician_link_history"
PERSONNEL_TECHNICIAN_LINK_HISTORY_COLUMNS: tuple[str, ...] = (
    "link_event_id",
    "personnel_id",
    "event_kind",
    "previous_technician_id",
    "new_technician_id",
    "recorded_at",
    "recorded_by",
    "request_id",
    "request_fingerprint",
    "reason_th",
    "is_test_data",
    "test_batch_id",
    "related_request_id",
)
# The bounded personnel_master columns the link write reads: identity and the
# phantom-row display columns, the link cell, and the test scope. Nothing else.
PERSONNEL_TECHNICIAN_LINK_MASTER_COLUMNS: tuple[str, ...] = (
    *PERSONNEL_PUBLIC_COLUMNS, "technician_id", "is_test_data", "test_batch_id",
)


async def _technicians(repository: Repository):
    return await repository.read_technician_master_reference()


PERSONNEL_TECHNICIAN_SPEC = LinkSpec(
    link=PERSONNEL_LINK_TECHNICIAN,
    label="PERSONNEL_TECHNICIAN_LINK",
    link_column="technician_id",
    previous_column="previous_technician_id",
    new_column="new_technician_id",
    record_columns=PERSONNEL_PUBLIC_COLUMNS,
    history_tab=PERSONNEL_TECHNICIAN_LINK_HISTORY_TAB,
    history_columns=PERSONNEL_TECHNICIAN_LINK_HISTORY_COLUMNS,
    record_id_prefix="PTL",
    target_label="TECHNICIAN",
    target_tab="technician_master",
    target_read_prefix="TECHNICIAN_MASTER",
    target_id_column="technician_id",
    read_targets=_technicians,
    op_link="personnel_technician_link",
    op_unlink="personnel_technician_unlink",
    op_relink="personnel_technician_relink",
    op_reconcile="personnel_technician_link_reconcile",
)


def personnel_technician_link_service(
    repository: Repository, data_context: str | None, test_batch_id: str
) -> PersonnelLinkService:
    return PersonnelLinkService(PERSONNEL_TECHNICIAN_SPEC, repository, data_context, test_batch_id)


__all__ = [
    "PERSONNEL_TECHNICIAN_LINK_HISTORY_COLUMNS",
    "PERSONNEL_TECHNICIAN_LINK_HISTORY_TAB",
    "PERSONNEL_TECHNICIAN_LINK_MASTER_COLUMNS",
    "PERSONNEL_TECHNICIAN_SPEC",
    "personnel_technician_link_service",
]
