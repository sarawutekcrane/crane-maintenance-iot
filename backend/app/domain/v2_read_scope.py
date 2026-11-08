"""R4 / TASK-010 — the shared Technician V2 read scope of the external job reads.

DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107 (Owner: Technician V2 only). One
contract for every external PM / Repair list, report and detail read:

* the scope comes ONLY from server configuration (`AssignmentCutover`): the
  TEST/REAL context and the TEST batch; an unconfigured context is 503 before
  any record read (`require_v2_write_context`, unchanged);
* a list returns only Technician V2 jobs of exactly that scope, filtered by the
  repository before ordering, counting and paging (`in_v2_read_scope`);
* records that cannot be trusted fail the WHOLE read closed (500, counts only,
  never an id): an unknown assignment model, a blank or duplicated V2 job id,
  or V2 scope cells that cannot prove a scope. Legacy rows are simply never
  readable. Read only: nothing here writes.
"""
from __future__ import annotations

from fastapi import status

from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG
from app.domain.reference_read import reference_read
from app.domain.registration import text
from app.domain.registry_write_support import error
from app.domain.technician_assignment import (
    ASSIGNMENT_MODEL_LEGACY,
    ASSIGNMENT_MODEL_TECHNICIAN_V2,
    JOB_PREFIX,
    AssignmentCutover,
    WorkKind,
    require_v2_write_context,
    scope_cells,
)
from app.repositories.base import Repository


async def server_read_scope(cutover: AssignmentCutover, repository: Repository) -> tuple[str, str]:
    """The server's own `(is_test_data, test_batch_id)` (503 when unconfigured)."""
    context = await require_v2_write_context(cutover, repository)
    cells = scope_cells(context, cutover.test_batch_id)
    return cells["is_test_data"], cells["test_batch_id"]


async def require_job_list_integrity(repository: Repository, kind: WorkKind, noun: str) -> None:
    """Whole-list fail closed (500, counts only, never an id). Same rules as the V2 queues."""
    table = "repair_order" if kind.key == "REPAIR" else "pm_work_order"
    read = await reference_read(repository.read_work_order_v2_rows(kind.key), JOB_PREFIX, table)
    issues: dict[str, int] = {}
    seen: set[str] = set()
    for row in read.rows:
        model = text(row.get("assignment_model"))
        if model not in (ASSIGNMENT_MODEL_LEGACY, ASSIGNMENT_MODEL_TECHNICIAN_V2):
            raise error("ASSIGNMENT_MODEL_DATA_INVALID", f"A work order's assignment model is not recognized; no "
                        f"{noun} list is returned", status.HTTP_500_INTERNAL_SERVER_ERROR,
                        {"issues": {"ASSIGNMENT_MODEL_UNKNOWN": 1}})
        job_id = text(row.get(kind.job_id_column))
        if not job_id.strip():
            if model == ASSIGNMENT_MODEL_TECHNICIAN_V2:
                issues["JOB_ID_BLANK"] = issues.get("JOB_ID_BLANK", 0) + 1
            continue
        if job_id in seen:
            issues["JOB_ID_DUPLICATE"] = issues.get("JOB_ID_DUPLICATE", 0) + 1
        seen.add(job_id)
        flag, batch = text(row.get("is_test_data")), text(row.get("test_batch_id"))
        if model == ASSIGNMENT_MODEL_TECHNICIAN_V2 and (
                flag not in (TEST_FLAG, OPERATIONAL_FLAG) or (flag == OPERATIONAL_FLAG and batch)):
            issues["JOB_SCOPE_FLAG_INVALID"] = issues.get("JOB_SCOPE_FLAG_INVALID", 0) + 1
    if issues:
        raise error(f"{JOB_PREFIX}_DATA_INVALID", f"A {noun} record cannot be trusted; no {noun} list is returned",
                    status.HTTP_500_INTERNAL_SERVER_ERROR, {"issues": dict(sorted(issues.items()))})
