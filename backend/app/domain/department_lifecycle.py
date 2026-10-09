"""R2 Batch R2e — department lifecycle (deactivate / reactivate / reconcile).

The frozen R2c-2 source states: is_active TRUE / FALSE (no third state).
Deactivate TRUE -> FALSE, reactivate FALSE -> TRUE. Only the `is_active` cell
is written: department_id, department_name_th, is_test_data and test_batch_id
never change, and no personnel row (its legacy free-text `department`
included) is ever rewritten. The live department_master tab does not exist
yet: until it does, these operations answer DEPARTMENT_MASTER_SCHEMA_INVALID.
"""
from __future__ import annotations

from app.domain.department import DEPARTMENT_BUSINESS_COLUMNS, DEPARTMENT_TAB
from app.domain.lifecycle_schema import (
    DEPARTMENT_LIFECYCLE_HISTORY_COLUMNS,
    DEPARTMENT_LIFECYCLE_HISTORY_TAB,
)
from app.domain.master_lifecycle import EntitySpec, LifecycleService
from app.repositories.base import LIFECYCLE_ENTITY_DEPARTMENT, Repository

DEPARTMENT_ACTIVE = "TRUE"
DEPARTMENT_INACTIVE = "FALSE"

OP_DEPARTMENT_DEACTIVATE = "department_deactivate"
OP_DEPARTMENT_REACTIVATE = "department_reactivate"
OP_DEPARTMENT_LIFECYCLE_RECONCILE = "department_lifecycle_reconcile"


def _expected(value: object) -> str:
    """The request's boolean as the frozen source text."""
    if value is True:
        return DEPARTMENT_ACTIVE
    if value is False:
        return DEPARTMENT_INACTIVE
    return ""


DEPARTMENT_SPEC = EntitySpec(
    entity=LIFECYCLE_ENTITY_DEPARTMENT,
    label="DEPARTMENT",
    id_column="department_id",
    state_column="is_active",
    record_columns=DEPARTMENT_BUSINESS_COLUMNS,  # the R2c-2 phantom rule
    active_value=DEPARTMENT_ACTIVE,
    inactive_value=DEPARTMENT_INACTIVE,
    expected_field="expected_is_active",
    expected_to_state=_expected,
    master_tab=DEPARTMENT_TAB,
    master_prefix="DEPARTMENT_MASTER",
    history_tab=DEPARTMENT_LIFECYCLE_HISTORY_TAB,
    history_columns=DEPARTMENT_LIFECYCLE_HISTORY_COLUMNS,
    record_id_prefix="DLH",
    op_deactivate=OP_DEPARTMENT_DEACTIVATE,
    op_reactivate=OP_DEPARTMENT_REACTIVATE,
    op_reconcile=OP_DEPARTMENT_LIFECYCLE_RECONCILE,
)


def department_lifecycle_service(repository: Repository, data_context: str | None, test_batch_id: str) -> LifecycleService:
    return LifecycleService(DEPARTMENT_SPEC, repository, data_context, test_batch_id)
