"""R2 Batch R2f-h2 — V2 My Work (Final Contract C1 §4 / §12 / §25).

`GET /api/v1/my-work` answers, for the AUTHENTICATED actor only:

    user_id -> User Account -> Personnel -> Technician -> current TECHNICIAN_V2 assignments

Every step resolves EXACTLY (exact text) and in the server's data scope (the
frozen R2f-a scope proof). Nothing is ever matched by name, email, phone, id
prefix or similarity. A chain that does not resolve returns an explicit
resolution status and NO work list (`items = None`); only a RESOLVED actor gets
a list, which may be empty. A read failure or untrusted data is an error,
never an empty list.

Work is read from the integrated R2f-h1 V2 assignment sets only, through the
R2f-h1 validator unchanged (set completeness H1-01, ambiguity, scope, persisted
reference proof, job existence / model / scope, ambiguity) — through ONE shared
validation path for EVERY in-scope V2 job on the tab, before filtering by this
technician (a lost row of this technician would otherwise hide a job): any
defect fails the whole response closed — My Work never
bypasses set integrity to show a partial list. A job is listed when it is a
TECHNICIAN_V2 job of the request's scope, still OPEN (the legacy My Work rule),
and the technician is a member (PRIMARY or COLLABORATOR) of its CURRENT set.
Superseded sets never list a job. Legacy jobs, legacy rows and legacy `user_id`
values are never read here; the legacy My Work routes are unchanged.

No lifecycle gate applies (inactivation does not hide assigned work). Read
only: no write of any kind.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from fastapi import status

from app.domain.equipment_caretaker import (
    REFERENCE_AMBIGUOUS,
    REFERENCE_MISSING,
    classify_reference,
    reference_issues,
)
from app.domain.master_lifecycle import in_scope
from app.domain.personnel_relationship import (
    PERSONNEL_PREFIX,
    PERSONNEL_TAB,
    USER_ACCOUNT_PREFIX,
    USER_ACCOUNT_TAB,
    scoped_personnel,
)
from app.domain.reference_read import reference_read
from app.domain.registration import text
from app.domain.registry_write_support import error, require_write_context
from app.domain.technician import read_technicians
from app.domain.technician_assignment import (
    ASSIGNMENT_MODEL_TECHNICIAN_V2,
    ASSIGNMENT_PREFIX,
    PM,
    REPAIR,
    ROLE_COLLABORATOR,
    ROLE_PRIMARY,
    STATUS_AMBIGUOUS,
    AssignmentCutover,
    AssignmentSet,
    WorkKind,
    assignment_model_of,
    derive_assignment_state,
    is_v2_row,
    stored_technician_ids,
)
from app.errors import ApiError
from app.repositories.base import ReferenceMasterRead, Repository

RESOLVED = "RESOLVED"
UNAUTHENTICATED = "UNAUTHENTICATED"
ACCOUNT_MISSING = "ACCOUNT_MISSING"
ACCOUNT_AMBIGUOUS = "ACCOUNT_AMBIGUOUS"
ACCOUNT_SCOPE_UNPROVEN = "ACCOUNT_SCOPE_UNPROVEN"
PERSONNEL_UNLINKED = "PERSONNEL_UNLINKED"
PERSONNEL_AMBIGUOUS = "PERSONNEL_AMBIGUOUS"
PERSONNEL_SCOPE_MISMATCH = "PERSONNEL_SCOPE_MISMATCH"
TECHNICIAN_UNLINKED = "TECHNICIAN_UNLINKED"
TECHNICIAN_MISSING = "TECHNICIAN_MISSING"
TECHNICIAN_AMBIGUOUS = "TECHNICIAN_AMBIGUOUS"
TECHNICIAN_SCOPE_UNPROVEN = "TECHNICIAN_SCOPE_UNPROVEN"
RESOLUTIONS = (RESOLVED, UNAUTHENTICATED, ACCOUNT_MISSING, ACCOUNT_AMBIGUOUS, ACCOUNT_SCOPE_UNPROVEN,
               PERSONNEL_UNLINKED, PERSONNEL_AMBIGUOUS, PERSONNEL_SCOPE_MISMATCH, TECHNICIAN_UNLINKED,
               TECHNICIAN_MISSING, TECHNICIAN_AMBIGUOUS, TECHNICIAN_SCOPE_UNPROVEN)

_OPEN = "OPEN"


@dataclass(frozen=True)
class MyWorkItem:
    work_type: str  # REPAIR / PM
    job_id: str
    asset_type: str
    asset_id: str
    status: str
    opened_at: datetime
    assignment_role: str  # PRIMARY / COLLABORATOR in the CURRENT set
    assignment_set_id: str
    assigned_at: datetime


@dataclass(frozen=True)
class MyWork:
    resolution: str
    technician_id: str | None = None
    items: tuple[MyWorkItem, ...] | None = None  # None unless RESOLVED


def _classified(kind: str | None, *, missing: str, ambiguous: str, unproven: str) -> str | None:
    if kind is None:
        return None
    return {REFERENCE_MISSING: missing, REFERENCE_AMBIGUOUS: ambiguous}.get(kind, unproven)


class MyWorkService:
    def __init__(self, repository: Repository, cutover: AssignmentCutover) -> None:
        self._repository = repository
        self._context = cutover.data_context
        self._batch_id = cutover.test_batch_id

    # ---------------------------------------------------------------- chain

    async def _resolve(self, user_id: str, context: str) -> tuple[str, str | None, ReferenceMasterRead | None]:
        """(resolution, technician_id, technician read). Exact text, in scope."""
        accounts = await reference_read(self._repository.read_user_account_reference(), USER_ACCOUNT_PREFIX,
                                        USER_ACCOUNT_TAB)
        account = _classified(classify_reference(user_id, accounts, "user_id", context, self._batch_id),
                              missing=ACCOUNT_MISSING, ambiguous=ACCOUNT_AMBIGUOUS, unproven=ACCOUNT_SCOPE_UNPROVEN)
        if account is not None:
            return account, None, None

        master = await reference_read(self._repository.read_personnel_relationship_master(), PERSONNEL_PREFIX,
                                      PERSONNEL_TAB)
        personnel = scoped_personnel(master.rows, context, self._batch_id)  # bad flags fail closed (500)
        holders = [p for p in personnel if text(p.get("user_id")) == user_id]
        if len(holders) > 1:
            return PERSONNEL_AMBIGUOUS, None, None
        if not holders:
            elsewhere = any(text(r.get("user_id")) == user_id and not in_scope(r, context, self._batch_id)
                            for r in master.rows)
            return (PERSONNEL_SCOPE_MISMATCH if elsewhere else PERSONNEL_UNLINKED), None, None

        technician_id = text(holders[0].get("technician_id"))
        if not technician_id.strip():
            return TECHNICIAN_UNLINKED, None, None
        if sum(1 for p in personnel if text(p.get("technician_id")) == technician_id) > 1:
            return TECHNICIAN_AMBIGUOUS, None, None
        technicians = await read_technicians(self._repository)
        technician = _classified(classify_reference(technician_id, technicians, "technician_id", context,
                                                    self._batch_id),
                                 missing=TECHNICIAN_MISSING, ambiguous=TECHNICIAN_AMBIGUOUS,
                                 unproven=TECHNICIAN_SCOPE_UNPROVEN)
        if technician is not None:
            return technician, None, None
        return RESOLVED, technician_id, technicians

    # ---------------------------------------------------------------- work

    async def _job(self, kind: WorkKind, job_id: str):
        if kind is REPAIR:
            detail = await self._repository.get_repair(job_id)
            return detail.repair if detail else None
        detail = await self._repository.get_pm_work_order(job_id)
        return detail.work_order if detail else None

    @staticmethod
    def _invalid(issues: Mapping[str, int]) -> ApiError:
        return error(f"{ASSIGNMENT_PREFIX}_DATA_INVALID", "The V2 technician assignment history cannot be trusted; "
                     "no work list is returned", status.HTTP_500_INTERNAL_SERVER_ERROR,
                     {"issues": dict(sorted(issues.items()))})

    async def _validated(self, kind: WorkKind, job_id: str, rows: Sequence[Mapping[str, object]], context: str,
                         technicians: ReferenceMasterRead) -> tuple[object, AssignmentSet | None]:
        """The shared fail-closed check of one in-scope V2 job: (job, current set)."""
        job = await self._job(kind, job_id)
        if job is None:
            raise self._invalid({"V2_ROW_JOB_MISSING": 1})
        if assignment_model_of(job) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
            raise self._invalid({"V2_ROW_ON_LEGACY_JOB": 1})
        scope = {"is_test_data": text(job.is_test_data), "test_batch_id": text(job.test_batch_id)}
        state = derive_assignment_state(kind, job_id, rows, scope)  # a job / row scope mismatch is an issue here
        issues = dict(state.issues) or reference_issues(
            stored_technician_ids(kind, job_id, rows), technicians, id_column="technician_id",
            label="TECHNICIAN", context=context, batch_id=self._batch_id)
        if issues:
            raise self._invalid(issues)
        if state.status == STATUS_AMBIGUOUS:
            raise error("TECHNICIAN_ASSIGNMENT_ORDER_AMBIGUOUS", "A work order's current assignment set cannot be "
                        "determined; no work list is returned", status.HTTP_409_CONFLICT,
                        {"work_type": kind.key, "job_id": job_id})
        return job, state.current

    async def _work(self, kind: WorkKind, technician_id: str, context: str,
                    technicians: ReferenceMasterRead) -> list[MyWorkItem]:
        read = await reference_read(self._repository.read_work_assignment_v2_rows(kind.key), ASSIGNMENT_PREFIX,
                                    kind.assignment_tab)
        rows: Sequence[Mapping[str, object]] = read.rows
        in_scope_jobs = sorted({text(r.get(kind.job_id_column)) for r in rows
                                if is_v2_row(r) and in_scope(r, context, self._batch_id)})
        # H2-01: ONE validation path for EVERY in-scope V2 job — job existence,
        # model, job scope, set integrity (H1-01), persisted reference proof and
        # ambiguity — BEFORE any filtering by this technician. A lost row of this
        # technician in another job would otherwise silently hide that job.
        items: list[MyWorkItem] = []
        for job_id in in_scope_jobs:
            job, current = await self._validated(kind, job_id, rows, context, technicians)
            if current is None or technician_id not in current.members or text(job.status.value) != _OPEN:
                continue
            items.append(MyWorkItem(
                work_type=kind.key, job_id=job_id, asset_type=job.asset_type.value, asset_id=job.asset_id,
                status=job.status.value, opened_at=job.opened_at,
                assignment_role=ROLE_PRIMARY if current.primary_technician_id == technician_id else ROLE_COLLABORATOR,
                assignment_set_id=current.set_id, assigned_at=current.assigned_at,
            ))
        return items

    async def my_work(self, user_id: str | None) -> MyWork:
        context = require_write_context(self._context, self._batch_id)
        if not (user_id or "").strip():
            return MyWork(resolution=UNAUTHENTICATED)
        resolution, technician_id, technicians = await self._resolve(user_id or "", context)
        if resolution != RESOLVED or technician_id is None or technicians is None:
            return MyWork(resolution=resolution)
        items = [*await self._work(REPAIR, technician_id, context, technicians),
                 *await self._work(PM, technician_id, context, technicians)]
        items.sort(key=lambda i: (i.opened_at, i.work_type, i.job_id), reverse=True)
        return MyWork(resolution=RESOLVED, technician_id=technician_id, items=tuple(items))


__all__ = ["MyWork", "MyWorkItem", "MyWorkService", "RESOLUTIONS", "RESOLVED", "UNAUTHENTICATED"]
