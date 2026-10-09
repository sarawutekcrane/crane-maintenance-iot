"""R2 Batch R2e — personnel lifecycle (deactivate / reactivate / reconcile).

Owner-approved vocabulary for the lifecycle WRITE logic: ACTIVE / INACTIVE.
The R2c-1 read is unchanged: `active_status` stays raw source text there, and
blank is still null. A lifecycle write refuses a target whose current value is
blank or anything else (422 PERSONNEL_LIFECYCLE_STATE_INVALID) — never
normalised, defaulted or repaired.

A personnel lifecycle write changes `active_status` of the one located row and
appends one personnel_lifecycle_history row. It never changes user_account
(login, role, MFA), technician_master, driver data, responsibility
assignments, PM/repair assignments, branch data, personnel_master.department
or anything else. Personnel identity and login identity stay separate.
"""
from __future__ import annotations

from app.domain.lifecycle_schema import (
    PERSONNEL_LIFECYCLE_HISTORY_COLUMNS,
    PERSONNEL_LIFECYCLE_HISTORY_TAB,
)
from app.domain.master_lifecycle import EntitySpec, LifecycleService
from app.domain.personnel import PERSONNEL_PUBLIC_COLUMNS, PERSONNEL_TAB
from app.repositories.base import LIFECYCLE_ENTITY_PERSONNEL, Repository

PERSONNEL_ACTIVE = "ACTIVE"
PERSONNEL_INACTIVE = "INACTIVE"

OP_PERSONNEL_DEACTIVATE = "personnel_deactivate"
OP_PERSONNEL_REACTIVATE = "personnel_reactivate"
OP_PERSONNEL_LIFECYCLE_RECONCILE = "personnel_lifecycle_reconcile"


def _expected(value: object) -> str:
    return value if isinstance(value, str) else ""


PERSONNEL_SPEC = EntitySpec(
    entity=LIFECYCLE_ENTITY_PERSONNEL,
    label="PERSONNEL",
    id_column="personnel_id",
    state_column="active_status",
    record_columns=PERSONNEL_PUBLIC_COLUMNS,  # the R2c-1 phantom rule
    active_value=PERSONNEL_ACTIVE,
    inactive_value=PERSONNEL_INACTIVE,
    expected_field="expected_active_status",
    expected_to_state=_expected,
    master_tab=PERSONNEL_TAB,
    master_prefix="PERSONNEL_MASTER",
    history_tab=PERSONNEL_LIFECYCLE_HISTORY_TAB,
    history_columns=PERSONNEL_LIFECYCLE_HISTORY_COLUMNS,
    record_id_prefix="PLH",
    op_deactivate=OP_PERSONNEL_DEACTIVATE,
    op_reactivate=OP_PERSONNEL_REACTIVATE,
    op_reconcile=OP_PERSONNEL_LIFECYCLE_RECONCILE,
)


def personnel_lifecycle_service(repository: Repository, data_context: str | None, test_batch_id: str) -> LifecycleService:
    return LifecycleService(PERSONNEL_SPEC, repository, data_context, test_batch_id)
