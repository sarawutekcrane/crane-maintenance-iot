"""R2 Batch R2f-e — Personnel ↔ Driver identity link spec.

Authority: `personnel_master.driver_id` (0..1 ↔ 0..1, exact id only). Driver
stays a DISTINCT identity (`driver_master.driver_id`); it is never replaced by
Personnel. The link is identity maintenance only: no crane / vehicle
responsibility (R2f-f), no Driver lifecycle, no ACTIVE gate (neither the
Personnel nor the Driver `active_status` is read for linking; the Phase 6 rule
that driver_master.active_status is opaque is preserved). driver_master is READ
ONLY through a bounded `driver_id`-only reader; the Phase 6 Driver master and
`vehicle_driver` assignment history are not read, written or reinterpreted, and
`vehicle_driver` is never a source of the link.

Durable audit: the SEPARATE append-only `personnel_driver_link_history` tab with
the frozen header below. It does NOT exist live: never auto-created, a missing
tab fails closed (PERSONNEL_DRIVER_LINK_HISTORY_SCHEMA_INVALID), not part of the
global readiness schemas. Existing driver_id values with no history are valid
(NO_HISTORY); no migration.

DEPLOYMENT GATE: the live personnel_master has no `driver_id` column yet. Every
read that needs it (the link locate, the R2f-a relationship read) fails honestly
with PERSONNEL_MASTER_SCHEMA_INVALID until a separately authorized live schema
preparation adds the blank column; nothing defaults, guesses or derives it.

A TEST link may target only an explicitly TEST-scoped driver of the same batch;
the live driver_master is untagged, so a live TEST link fails closed
(DRIVER_SCOPE_UNPROVEN) whatever the id text looks like.
"""
from __future__ import annotations

from app.domain.personnel import PERSONNEL_DRIVER_ID_COLUMN
from app.domain.personnel_link import LinkSpec, PersonnelLinkService
from app.repositories.base import PERSONNEL_LINK_DRIVER, Repository

DRIVER_MASTER_TAB = "driver_master"
DRIVER_MASTER_PREFIX = "DRIVER_MASTER"
# Bounded: the identity only. No name, phone, licence, expiry, status or note.
DRIVER_REFERENCE_COLUMNS: tuple[str, ...] = ("driver_id",)

PERSONNEL_DRIVER_LINK_HISTORY_TAB = "personnel_driver_link_history"
PERSONNEL_DRIVER_LINK_HISTORY_COLUMNS: tuple[str, ...] = (
    "link_event_id",
    "personnel_id",
    "event_kind",
    "previous_driver_id",
    "new_driver_id",
    "recorded_at",
    "recorded_by",
    "request_id",
    "request_fingerprint",
    "reason_th",
    "is_test_data",
    "test_batch_id",
    "related_request_id",
)
# The bounded personnel_master columns the driver-link write reads: the
# identity, the link cell and the test scope — nothing else. A row with both
# personnel_id and driver_id blank is a phantom row; any other row is a
# content-bearing relationship row whose test flag must classify exactly.
PERSONNEL_DRIVER_LINK_RECORD_COLUMNS: tuple[str, ...] = ("personnel_id", PERSONNEL_DRIVER_ID_COLUMN)
PERSONNEL_DRIVER_LINK_MASTER_COLUMNS: tuple[str, ...] = (
    *PERSONNEL_DRIVER_LINK_RECORD_COLUMNS, "is_test_data", "test_batch_id",
)


async def _drivers(repository: Repository):
    return await repository.read_driver_master_reference()


PERSONNEL_DRIVER_SPEC = LinkSpec(
    link=PERSONNEL_LINK_DRIVER,
    label="PERSONNEL_DRIVER_LINK",
    link_column=PERSONNEL_DRIVER_ID_COLUMN,
    previous_column="previous_driver_id",
    new_column="new_driver_id",
    record_columns=PERSONNEL_DRIVER_LINK_RECORD_COLUMNS,
    history_tab=PERSONNEL_DRIVER_LINK_HISTORY_TAB,
    history_columns=PERSONNEL_DRIVER_LINK_HISTORY_COLUMNS,
    record_id_prefix="PDL",
    target_label="DRIVER",
    target_tab=DRIVER_MASTER_TAB,
    target_read_prefix=DRIVER_MASTER_PREFIX,
    target_id_column="driver_id",
    read_targets=_drivers,
    op_link="personnel_driver_link",
    op_unlink="personnel_driver_unlink",
    op_relink="personnel_driver_relink",
    op_reconcile="personnel_driver_link_reconcile",
)


def personnel_driver_link_service(
    repository: Repository, data_context: str | None, test_batch_id: str
) -> PersonnelLinkService:
    return PersonnelLinkService(PERSONNEL_DRIVER_SPEC, repository, data_context, test_batch_id)


__all__ = [
    "DRIVER_MASTER_PREFIX",
    "DRIVER_MASTER_TAB",
    "DRIVER_REFERENCE_COLUMNS",
    "PERSONNEL_DRIVER_LINK_HISTORY_COLUMNS",
    "PERSONNEL_DRIVER_LINK_HISTORY_TAB",
    "PERSONNEL_DRIVER_LINK_MASTER_COLUMNS",
    "PERSONNEL_DRIVER_LINK_RECORD_COLUMNS",
    "PERSONNEL_DRIVER_SPEC",
    "personnel_driver_link_service",
]
