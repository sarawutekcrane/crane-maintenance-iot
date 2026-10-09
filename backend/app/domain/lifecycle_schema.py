"""R2 Batch R2e — frozen schema constants of the personnel / department
lifecycle (pure; no I/O, no service imports, so the Sheets schemas can use it).

The two lifecycle-history tabs are SEPARATE (no shared table) and do not
exist live yet: they are created only by a separately approved live step.
"""
from __future__ import annotations

from app.domain.department import DEPARTMENT_BUSINESS_COLUMNS, DEPARTMENT_TAB
from app.domain.personnel import PERSONNEL_PUBLIC_COLUMNS, PERSONNEL_TAB


def history_columns(entity_id_column: str) -> tuple[str, ...]:
    """The frozen R2e lifecycle-history header (exact order)."""
    return (
        "lifecycle_event_id",
        entity_id_column,
        "event_kind",
        "previous_state",
        "new_state",
        "recorded_at",
        "recorded_by",
        "request_id",
        "request_fingerprint",
        "reason_th",
        "is_test_data",
        "test_batch_id",
        "related_request_id",
    )


PERSONNEL_LIFECYCLE_HISTORY_TAB = "personnel_lifecycle_history"
PERSONNEL_LIFECYCLE_HISTORY_COLUMNS = history_columns("personnel_id")
DEPARTMENT_LIFECYCLE_HISTORY_TAB = "department_lifecycle_history"
DEPARTMENT_LIFECYCLE_HISTORY_COLUMNS = history_columns("department_id")

# The lifecycle locate reads these master columns (all required): identity,
# display, lifecycle state and test scope.
PERSONNEL_LIFECYCLE_MASTER_COLUMNS: tuple[str, ...] = (*PERSONNEL_PUBLIC_COLUMNS, "is_test_data", "test_batch_id")
DEPARTMENT_LIFECYCLE_MASTER_COLUMNS: tuple[str, ...] = (*DEPARTMENT_BUSINESS_COLUMNS, "is_test_data", "test_batch_id")

PERSONNEL_LIFECYCLE_STATE_COLUMN = "active_status"
DEPARTMENT_LIFECYCLE_STATE_COLUMN = "is_active"
__all__ = [
    "DEPARTMENT_LIFECYCLE_HISTORY_COLUMNS", "DEPARTMENT_LIFECYCLE_HISTORY_TAB", "DEPARTMENT_LIFECYCLE_MASTER_COLUMNS",
    "DEPARTMENT_LIFECYCLE_STATE_COLUMN", "DEPARTMENT_TAB", "PERSONNEL_LIFECYCLE_HISTORY_COLUMNS",
    "PERSONNEL_LIFECYCLE_HISTORY_TAB", "PERSONNEL_LIFECYCLE_MASTER_COLUMNS", "PERSONNEL_LIFECYCLE_STATE_COLUMN",
    "PERSONNEL_TAB", "history_columns",
]
