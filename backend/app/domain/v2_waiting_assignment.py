"""R2 Batch R2f-h4 B3 — U1 V2 waiting-assignment queue (C1 Amendment A1-§24,
owner decision O2). STRICTLY READ ONLY: no row is written, no job is changed.

One queue per work kind (Repair / PM). It lists the OPEN jobs whose PERSISTED
`assignment_model` is exactly `TECHNICIAN_V2`, inside the server-derived scope,
that need assignment attention:

- NONE          no current V2 assignment set;
- AMBIGUOUS     the current set cannot be determined (`STATUS_AMBIGUOUS`);
- DATA_INVALID  a job-attributable defect: that job's set integrity (H1-01
                completeness / digest / duplicate / row scope = job scope) or the
                persisted technician reference proof for that job's stored ids.

A job with a VALID current set is NOT listed; after a successful assignment it
leaves the queue on the next read. It stays in the normal job lists, its
detail page and the assignees' V2 My Work.

Fail closed for the WHOLE queue (never a partial list):
- tab-wide V2 assignment issues (R2f-h1 `tab_issues`), an in-scope V2 row whose
  job does not exist (`V2_ROW_JOB_MISSING`), an in-scope V2 row on a legacy job
  (`V2_ROW_ON_LEGACY_JOB`), or a duplicated job id: 500
  TECHNICIAN_ASSIGNMENT_DATA_INVALID {issues};
- any job with an unknown `assignment_model`: 500 ASSIGNMENT_MODEL_DATA_INVALID
  (never silently dropped);
- B3 integrity fix (I1 / I1b / I2, A1-§24 as clarified): a V2 job whose scope
  flags cannot prove its scope (JOB_SCOPE_FLAG_INVALID — the R2f-h1
  `require_v2_job_in_scope` rule), an in-scope V2 job whose status is neither
  exactly OPEN nor exactly CLOSED (JOB_STATUS_INVALID), or an in-scope OPEN V2
  job without a valid `opened_at` (JOB_OPENED_AT_INVALID): 500
  TECHNICIAN_ASSIGNMENT_JOB_DATA_INVALID {issues} — counts only, never a job
  or asset id. Status OPEN is never fabricated; no such job is silently dropped;
  a job of a provably different scope or batch is skipped unvalidated;
- schema problems: 500 *_SCHEMA_INVALID; read failures: 503 *_READ_FAILED.

Exactly three repository reads per request, whatever the page: the V2 job rows,
the V2 assignment rows and the technician master. The context is proven before
any read (503 REGISTRY_DATA_CONTEXT_NOT_CONFIGURED). The R2f-h1 validators are
reused unchanged. Jobs of the other scope are neither listed nor validated.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import status

from app.domain.common import Page, PageParams
from app.domain.equipment_caretaker import reference_issues
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG, in_scope
from app.domain.pm import PmWorkOrderStatus
from app.domain.reference_read import reference_read
from app.domain.registration import text
from app.domain.registry_write_support import error, require_write_context
from app.domain.repair import RepairStatus
from app.domain.technician import read_technicians
from app.domain.technician_assignment import (
    ASSIGNMENT_MODEL_LEGACY,
    ASSIGNMENT_MODEL_TECHNICIAN_V2,
    ASSIGNMENT_PREFIX,
    JOB_PREFIX,
    REPAIR,
    STATUS_AMBIGUOUS,
    WorkKind,
    derive_assignment_state,
    is_v2_row,
    stored_technician_ids,
    tab_issues,
)
from app.errors import ApiError
from app.repositories.base import Repository

NONE = "NONE"
AMBIGUOUS = "AMBIGUOUS"
DATA_INVALID = "DATA_INVALID"
_OPEN = "OPEN"


@dataclass(frozen=True)
class WaitingItem:
    work_type: str
    job_id: str
    asset_type: str
    asset_id: str
    status: str  # always exactly "OPEN" (B3 integrity fix I1)
    opened_at: datetime  # always a valid timestamp (B3 integrity fix I1b)
    assignment_status: str
    issues: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class WaitingQueue:
    data_context: str
    page: Page[WaitingItem]


def _add(issues: dict[str, int], code: str) -> None:
    issues[code] = issues.get(code, 0) + 1


def _data_invalid(issues: Mapping[str, int]) -> ApiError:
    return error(f"{ASSIGNMENT_PREFIX}_DATA_INVALID", "The V2 assignment data cannot be trusted; no waiting queue is "
                 "returned", status.HTTP_500_INTERNAL_SERVER_ERROR, {"issues": dict(sorted(issues.items()))})


def _opened_at(value: str) -> datetime | None:
    """A valid, timezone-aware ISO timestamp, else None. A naive timestamp cannot
    be ordered against the aware ones every V2 create writes, so it is invalid
    (fail closed) rather than a sort-time crash."""
    try:
        parsed = datetime.fromisoformat(value) if value.strip() else None
    except ValueError:
        return None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


class V2WaitingAssignmentService:
    def __init__(self, repository: Repository, context: str | None, batch_id: str) -> None:
        self._repository = repository
        self._context = context
        self._batch_id = batch_id

    async def queue(self, kind: WorkKind, params: PageParams) -> WaitingQueue:
        context = require_write_context(self._context, self._batch_id)  # 503 before any read
        jobs = await reference_read(self._repository.read_work_order_v2_rows(kind.key), JOB_PREFIX,
                                    "repair_order" if kind is REPAIR else "pm_work_order")
        assignments = await reference_read(self._repository.read_work_assignment_v2_rows(kind.key),
                                           ASSIGNMENT_PREFIX, kind.assignment_tab)
        technicians = await read_technicians(self._repository)
        items = self._classify(kind, jobs.rows, assignments.rows, technicians, context)
        items.sort(key=lambda i: (i.opened_at, i.job_id), reverse=True)
        start = (params.page - 1) * params.page_size
        return WaitingQueue(data_context=context, page=Page(
            items=items[start:start + params.page_size], page=params.page, page_size=params.page_size,
            total_items=len(items)))

    def _classify(self, kind: WorkKind, job_rows: Sequence[Mapping[str, object]],
                  rows: Sequence[Mapping[str, object]], technicians, context: str) -> list[WaitingItem]:
        id_column = kind.job_id_column
        # 1. Whole-queue integrity of the job tab: unknown model, duplicated id.
        by_id: dict[str, Mapping[str, object]] = {}
        duplicate: dict[str, int] = {}
        for job in job_rows:
            if text(job.get("assignment_model")) not in (ASSIGNMENT_MODEL_LEGACY, ASSIGNMENT_MODEL_TECHNICIAN_V2):
                raise error("ASSIGNMENT_MODEL_DATA_INVALID", "A work order's assignment model is not recognized; no "
                            "waiting queue is returned", status.HTTP_500_INTERNAL_SERVER_ERROR,
                            {"issues": {"ASSIGNMENT_MODEL_UNKNOWN": 1}})
            job_id = text(job.get(id_column))
            if not job_id.strip():
                if text(job.get("assignment_model")) == ASSIGNMENT_MODEL_TECHNICIAN_V2:
                    _add(duplicate, "JOB_ID_BLANK")  # a V2 job no queue item could identify
                continue
            if job_id in by_id:
                _add(duplicate, "JOB_ID_DUPLICATE")
            by_id[job_id] = job
        if duplicate:
            raise _data_invalid(duplicate)
        # 2. Whole-queue integrity of the assignment tab (any job, any scope), then
        #    in-scope V2 rows that cannot be attributed to an in-scope V2 job.
        issues = tab_issues(kind, rows)
        for row in rows:
            if not (is_v2_row(row) and in_scope(row, context, self._batch_id)):
                continue
            job = by_id.get(text(row.get(id_column)))
            if job is None:
                _add(issues, "V2_ROW_JOB_MISSING")
            elif text(job.get("assignment_model")) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
                _add(issues, "V2_ROW_ON_LEGACY_JOB")
        if issues:
            raise _data_invalid(issues)
        # 3. Whole-queue integrity of the V2 job rows (B3 integrity fix I1 / I1b / I2):
        #    the scope must be provable (R2f-h1 `require_v2_job_in_scope` rule); a
        #    provably other-scope / other-batch job is skipped unvalidated; an
        #    in-scope job's status must be exactly OPEN or CLOSED; an in-scope OPEN
        #    job needs a valid opened_at. Counts only — never a job or asset id.
        statuses = {s.value for s in (RepairStatus if kind is REPAIR else PmWorkOrderStatus)}
        job_issues: dict[str, int] = {}
        population: list[tuple[str, Mapping[str, object], datetime]] = []
        for job_id, job in by_id.items():
            if text(job.get("assignment_model")) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
                continue
            flag, batch = text(job.get("is_test_data")), text(job.get("test_batch_id"))
            if flag not in (TEST_FLAG, OPERATIONAL_FLAG) or (flag == OPERATIONAL_FLAG and batch):
                _add(job_issues, "JOB_SCOPE_FLAG_INVALID")
                continue
            if not in_scope(job, context, self._batch_id):
                continue  # a provably different scope or batch: neither listed nor validated
            job_status = text(job.get("status"))
            if job_status not in statuses:
                _add(job_issues, "JOB_STATUS_INVALID")
                continue
            if job_status != _OPEN:
                continue  # CLOSED: not waiting (its opened_at is never required)
            opened_at = _opened_at(text(job.get("opened_at")))
            if opened_at is None:
                _add(job_issues, "JOB_OPENED_AT_INVALID")
                continue
            population.append((job_id, job, opened_at))
        if job_issues:
            raise error(f"{JOB_PREFIX}_DATA_INVALID", "A V2 work order record cannot be trusted; no waiting queue is "
                        "returned", status.HTTP_500_INTERNAL_SERVER_ERROR,
                        {"issues": dict(sorted(job_issues.items()))})
        # 4. Per-job classification of the proven OPEN in-scope V2 population.
        items: list[WaitingItem] = []
        for job_id, job, opened_at in population:
            scope = {"is_test_data": text(job.get("is_test_data")), "test_batch_id": text(job.get("test_batch_id"))}
            state = derive_assignment_state(kind, job_id, rows, scope)
            set_issues = dict(state.issues) or reference_issues(
                stored_technician_ids(kind, job_id, rows), technicians, id_column="technician_id",
                label="TECHNICIAN", context=context, batch_id=self._batch_id)
            if set_issues:
                assignment_status = DATA_INVALID
            elif state.status == STATUS_AMBIGUOUS:
                assignment_status = AMBIGUOUS
            elif state.current is None:
                assignment_status = NONE
            else:
                continue  # VALID: not waiting
            items.append(WaitingItem(
                work_type=kind.key, job_id=job_id, asset_type=text(job.get("asset_type")),
                asset_id=text(job.get("asset_id")), status=_OPEN, opened_at=opened_at,
                assignment_status=assignment_status, issues=dict(sorted(set_issues.items())),
            ))
        return items


__all__ = ["AMBIGUOUS", "DATA_INVALID", "NONE", "V2WaitingAssignmentService", "WaitingItem", "WaitingQueue"]
