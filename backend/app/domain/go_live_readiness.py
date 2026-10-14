"""R2 Batch R2f-h3 — Pre-Go-live verification report (Final Contract C1 §26; owner
decisions D1-D4). STRICTLY READ ONLY: no row, master, configuration or audit
write of any kind; the V2 cutover setting is reported, never changed.

The six C1 §26 checks (verbatim requirement text is returned with each result):
  C1-26-1  REAL Personnel <-> Technician links exist, are unique and resolve for
           every intended recipient (owner list, D2).
  C1-26-2  REAL Personnel <-> Account links do the same for every intended My Work
           user (owner list, D2).
  C1-26-3  Personnel and Technician are exactly ACTIVE — for BOTH owner lists (D4).
  C1-26-4  TEST is segregated and no TEST row references a REAL entity (D3).
  C1-26-5  No MISSING, AMBIGUOUS or scope-unproven references in REAL (D3).
  C1-26-6  The authorized live schema additions are present (D3).

Outcomes per check: PASS / FAIL / BLOCKED / UNDETERMINED. PASS needs positive
proof; a missing owner list, an unreadable or incomplete source, or an unproven
reference is never PASS. Overall: READY only when all six checks PASS; NOT_READY
when any check FAILs (or one is UNDETERMINED); otherwise BLOCKED. READY describes
findings only — it is not an authorization to enable the cutover.

Read semantics: every source is read ONCE (bounded / validated readers; no
per-job reads). A proven structural problem is recorded per source (TAB_MISSING
-> ABSENT, anything else -> NOT_ASSESSABLE) and drives the dependent checks to
BLOCKED; any other read failure fails the whole report closed (503) — a source
failure is never turned into an empty result. Scope comes only from each row's
own flags (or, for untagged live masters, the repository's proven scope); never
from an identifier, name or pattern. Matching is exact text.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import status

from app.domain.fleet_summary import SCHEMA_PROBLEM_TAB_MISSING
from app.domain.master_lifecycle import OPERATIONAL_FLAG, TEST_FLAG
from app.domain.personnel_relationship import RESOLVED, resolve_link
from app.domain.registration import DATA_CONTEXT_REAL, text
from app.domain.registry_write_support import data_context_not_configured, error
from app.domain.technician_assignment import (
    ASSIGNMENT_MODEL_LEGACY,
    ASSIGNMENT_MODEL_TECHNICIAN_V2,
    PM,
    REPAIR,
    STATUS_AMBIGUOUS,
    derive_assignment_state,
    is_v2_row,
    tab_issues,
)
from app.repositories.base import (
    LIFECYCLE_ENTITY_DEPARTMENT,
    LIFECYCLE_ENTITY_PERSONNEL,
    PERSONNEL_LINK_ACCOUNT,
    PERSONNEL_LINK_DRIVER,
    PERSONNEL_LINK_TECHNICIAN,
    REFERENCE_SCOPE_REAL,
    REFERENCE_SCOPE_TEST,
    ReferenceMasterRead,
    RegistryTableRead,
    Repository,
    RepositoryError,
    RepositoryFeatureNotImplementedError,
    RepositorySchemaError,
)

PASS, FAIL, BLOCKED, UNDETERMINED = "PASS", "FAIL", "BLOCKED", "UNDETERMINED"
READY, NOT_READY = "READY", "NOT_READY"
ACTIVE = "ACTIVE"

EXAMINED, ABSENT, NOT_ASSESSABLE = "EXAMINED", "ABSENT", "NOT_ASSESSABLE"
EXCLUDED_BY_CONTRACT, UNTAGGED = "EXCLUDED_BY_CONTRACT", "UNTAGGED"

_SCOPE_INVALID = "INVALID"
_SCOPE_LEGACY = "LEGACY"  # an untagged legacy job row: operational by contract (C1 §15)
_TARGET_UNPROVABLE = "TARGET_UNPROVABLE"  # H3-01: target master ABSENT or NOT_ASSESSABLE

REQUIREMENTS = {
    "C1-26-1": "REAL Personnel ↔ Technician links exist, are unique and resolve for every intended recipient",
    "C1-26-2": "REAL Personnel ↔ Account links do the same for every intended My Work user",
    "C1-26-3": "Personnel and Technician are ACTIVE for recipients (owner D4: intended recipients AND intended "
               "My Work users)",
    "C1-26-4": "TEST is segregated and no TEST row references a REAL entity",
    "C1-26-5": "no MISSING, AMBIGUOUS or scope-unproven references in REAL",
    "C1-26-6": "the authorized live schema additions are present",
}

RECIPIENTS = "intended_recipient_personnel_ids"
MY_WORK_USERS = "intended_my_work_personnel_ids"


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    id: str
    status: str
    evidence: dict[str, object] = field(default_factory=dict)
    issues: list[dict[str, object]] = field(default_factory=list)

    @property
    def requirement(self) -> str:
        return REQUIREMENTS[self.id]


@dataclass(frozen=True)
class CoverageEntry:
    source: str
    tab: str
    status: str
    role: str  # TAGGED_SOURCE / REFERENCE_MASTER / REQUIRED_SCHEMA / LEGACY / R1
    rows: int | None = None
    test_rows: int | None = None
    real_rows: int | None = None
    references_verified: tuple[str, ...] = ()
    detail: str = ""


@dataclass
class ReadinessReport:
    generated_at: datetime
    data_context: str
    dev_auth_effective: bool
    overall: str
    checks: list[CheckResult]
    inputs: dict[str, object]
    coverage: list[CoverageEntry]
    gaps: list[str]
    population: list[dict[str, object]] | None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@dataclass
class Source:
    key: str
    tab: str
    table: RegistryTableRead | None = None
    reference: ReferenceMasterRead | None = None
    problem: str | None = None
    headers: tuple[str, ...] = ()

    @property
    def readable(self) -> bool:
        return self.problem is None

    @property
    def status(self) -> str:
        if self.problem is None:
            return EXAMINED
        return ABSENT if self.problem == SCHEMA_PROBLEM_TAB_MISSING else NOT_ASSESSABLE

    @property
    def rows(self) -> list[Mapping[str, object]]:
        if self.table is not None:
            return list(self.table.rows)
        if self.reference is not None:
            return [r.values for r in self.reference.rows]
        return []


async def _read(key: str, tab: str, call) -> Source:
    """ONE read. A proven structural problem is recorded on the source; any
    other failure fails the whole report closed (503)."""
    try:
        result = await call
    except RepositoryFeatureNotImplementedError:
        raise
    except RepositorySchemaError as exc:
        return Source(key, tab, problem=exc.problem, headers=tuple(exc.headers))
    except RepositoryError as exc:
        raise error("GO_LIVE_READINESS_READ_FAILED", f"{tab} could not be read; no report is returned",
                    status.HTTP_503_SERVICE_UNAVAILABLE, {"source": key, "tab": tab}) from exc
    if isinstance(result, ReferenceMasterRead):
        return Source(key, tab, reference=result)
    return Source(key, tab, table=result)


def _flag_scope(row: Mapping[str, object]) -> str:
    flag = text(row.get("is_test_data"))
    if flag == OPERATIONAL_FLAG:
        return REFERENCE_SCOPE_REAL
    if flag == TEST_FLAG:
        return REFERENCE_SCOPE_TEST
    return _SCOPE_INVALID


def _job_scope(row: Mapping[str, object]) -> str:
    model = text(row.get("assignment_model"))
    if model == ASSIGNMENT_MODEL_LEGACY and not text(row.get("is_test_data")):
        return _SCOPE_LEGACY
    return _flag_scope(row)


@dataclass(frozen=True)
class Target:
    """A referenced master: (exact id -> (row scope, row test batch)), and its
    read status. The batch is the one the repository proves (reference masters)
    or the row's own `test_batch_id` (tagged tabs); never derived from an id."""

    name: str
    source: Source
    scopes: dict[str, list[tuple[str, str]]]


def _target(name: str, source: Source, id_column: str, *, by_flags: bool = False, jobs: bool = False) -> Target:
    scopes: dict[str, list[tuple[str, str]]] = {}
    if source.reference is not None:
        for row in source.reference.rows:
            scopes.setdefault(text(row.values.get(id_column)), []).append((row.scope, text(row.test_batch_id)))
    elif source.table is not None:
        for row in source.table.rows:
            scope = _job_scope(row) if jobs else (_flag_scope(row) if by_flags else REFERENCE_SCOPE_REAL)
            batch = text(row.get("test_batch_id")) if (jobs or by_flags) else ""
            scopes.setdefault(text(row.get(id_column)), []).append((scope, batch))
    return Target(name, source, scopes)


@dataclass(frozen=True)
class RefSpec:
    column: str
    target: str  # a target name, or "ASSET" (by the row's asset_type)


@dataclass(frozen=True)
class SourceSpec:
    key: str
    tab: str
    refs: tuple[RefSpec, ...]
    v2_rows_only: bool = False  # V2 assignment tabs: legacy rows are untagged
    job_rows: bool = False  # job tabs: only tagged (V2 / flagged) rows are TEST / REAL rows


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GoLiveReadinessService:
    def __init__(self, repository: Repository, *, data_context: str | None, dev_auth_effective: bool) -> None:
        self._repository = repository
        self._context = data_context
        self._dev_auth_effective = dev_auth_effective

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def _sources(self) -> dict[str, Source]:
        r = self._repository
        reads = [
            ("personnel", "personnel_master", r.read_personnel_relationship_master()),
            ("technicians", "technician_master", r.read_technician_master_reference()),
            ("accounts", "user_account", r.read_user_account_reference()),
            ("drivers", "driver_master", r.read_driver_master_reference()),
            ("vehicles", "vehicle_master", r.read_vehicle_reference()),
            ("equipment", "equipment_master", r.read_equipment_reference()),
            ("departments", "department_master", r.read_department_reference()),
            ("link_technician", "personnel_technician_link_history",
             r.read_personnel_link_history_validated(PERSONNEL_LINK_TECHNICIAN)),
            ("link_account", "personnel_account_link_history",
             r.read_personnel_link_history_validated(PERSONNEL_LINK_ACCOUNT)),
            ("link_driver", "personnel_driver_link_history",
             r.read_personnel_link_history_validated(PERSONNEL_LINK_DRIVER)),
            ("lifecycle_personnel", "personnel_lifecycle_history",
             r.read_lifecycle_history_validated(LIFECYCLE_ENTITY_PERSONNEL)),
            ("lifecycle_department", "department_lifecycle_history",
             r.read_lifecycle_history_validated(LIFECYCLE_ENTITY_DEPARTMENT)),
            ("caretaker", "equipment_caretaker_history", r.read_equipment_caretaker_history_validated()),
            ("crane_driver", "crane_driver_responsibility_history",
             r.read_crane_driver_responsibility_history_validated()),
            ("department_history", "personnel_department_history", r.read_personnel_department_history_validated()),
            ("v2_repair", "repair_assignment", r.read_work_assignment_v2_rows(REPAIR.key)),
            ("v2_pm", "pm_work_assignment", r.read_work_assignment_v2_rows(PM.key)),
            ("jobs_repair", "repair_order", r.read_work_order_v2_rows(REPAIR.key)),
            ("jobs_pm", "pm_work_order", r.read_work_order_v2_rows(PM.key)),
        ]
        sources: dict[str, Source] = {}
        for key, tab, call in reads:
            sources[key] = await _read(key, tab, call)
        return sources

    # ---------------------------------------------------------------- entry

    async def report(self, body: Mapping[str, object], provided: frozenset[str]) -> ReadinessReport:
        if self._context is None:
            raise data_context_not_configured()
        if self._context != DATA_CONTEXT_REAL:
            raise error("GO_LIVE_READINESS_REQUIRES_REAL_CONTEXT", "The pre-Go-live report runs only in the REAL data "
                        "context; a TEST context is never evidence of REAL readiness", status.HTTP_409_CONFLICT,
                        {"data_context": self._context})
        sources = await self._sources()
        targets = {
            "TECHNICIAN": _target("TECHNICIAN", sources["technicians"], "technician_id"),
            "ACCOUNT": _target("ACCOUNT", sources["accounts"], "user_id"),
            "DRIVER": _target("DRIVER", sources["drivers"], "driver_id"),
            "VEHICLE": _target("VEHICLE", sources["vehicles"], "vehicle_id"),
            "EQUIPMENT": _target("EQUIPMENT", sources["equipment"], "equipment_id"),
            "PERSONNEL": _target("PERSONNEL", sources["personnel"], "personnel_id", by_flags=True),
            "DEPARTMENT": _target("DEPARTMENT", sources["departments"], "department_id", by_flags=True),
            "REPAIR_JOB": _target("REPAIR_JOB", sources["jobs_repair"], REPAIR.job_id_column, jobs=True),
            "PM_JOB": _target("PM_JOB", sources["jobs_pm"], PM.job_id_column, jobs=True),
        }
        inputs, lists = self._inputs(body, provided)
        people = _People(sources["personnel"], sources["technicians"], sources["accounts"])
        coverage, gaps, check4, check5 = self._references(sources, targets)
        checks = [
            self._check_link("C1-26-1", lists[RECIPIENTS], inputs[RECIPIENTS], people, "technician_id",
                             sources["technicians"]),
            self._check_link("C1-26-2", lists[MY_WORK_USERS], inputs[MY_WORK_USERS], people, "user_id",
                             sources["accounts"]),
            self._check_active(lists, inputs, people),
            check4,
            check5,
            self._check_schema(sources),
        ]
        for check in checks[:3]:
            if check.status == BLOCKED:
                gaps.append(f"{check.id}: {check.evidence.get('blocked_reason', 'blocked')}")
        statuses = [c.status for c in checks]
        overall = READY if all(s == PASS for s in statuses) else (
            NOT_READY if FAIL in statuses or (BLOCKED not in statuses) else BLOCKED)
        return ReadinessReport(
            generated_at=self._now(), data_context=self._context,
            dev_auth_effective=self._dev_auth_effective, overall=overall, checks=checks,
            inputs={k: v for k, v in inputs.items()}, coverage=coverage, gaps=gaps,
            population=people.population() if people.readable else None,
        )

    # ---------------------------------------------------------------- inputs (D2)

    @staticmethod
    def _inputs(body: Mapping[str, object], provided: frozenset[str]):
        inputs: dict[str, dict[str, object]] = {}
        lists: dict[str, list[str] | None] = {}
        for name in (RECIPIENTS, MY_WORK_USERS):
            value = body.get(name)
            if name not in provided:
                state, ids = "OMITTED", None
            elif value is None:
                state, ids = "NULL", None
            elif not value:
                state, ids = "EMPTY", []
            else:
                state, ids = "SUPPLIED", list(value)  # exact strings, order kept
            seen: set[str] = set()
            duplicates = []
            for pid in ids or []:
                if pid in seen and pid not in duplicates:
                    duplicates.append(pid)
                seen.add(pid)
            inputs[name] = {"state": state, "ids": ids, "duplicates": duplicates}
            lists[name] = ids if state == "SUPPLIED" else None
        return inputs, lists

    # ---------------------------------------------------------------- C1-26-1 / -2

    def _check_link(self, check_id: str, ids: list[str] | None, given: Mapping[str, object], people: "_People",
                    column: str, reference: Source) -> CheckResult:
        result = CheckResult(check_id, PASS)
        if ids is None or not ids:
            result.status = BLOCKED
            result.evidence = {"blocked_reason": f"INPUT_{given['state']}", "input_state": given["state"]}
            return result
        if not people.readable or not reference.readable:
            result.status = BLOCKED
            result.evidence = {"blocked_reason": "SOURCE_NOT_ASSESSABLE"}
            return result
        resolved = 0
        for pid in given["duplicates"]:  # type: ignore[union-attr]
            result.issues.append({"code": "INPUT_DUPLICATE", "personnel_id": pid})
        for pid in dict.fromkeys(ids):
            located = people.locate(pid)
            if located is not None:
                result.issues.append({"code": located, "personnel_id": pid})
                continue
            resolution = people.link(pid, column)
            if resolution.resolution != RESOLVED:
                result.issues.append({"code": f"LINK_{resolution.resolution}", "personnel_id": pid,
                                      column: resolution.linked_id})
                continue
            resolved += 1
        result.status = FAIL if result.issues else PASS
        result.evidence = {"input_state": given["state"], "unique_ids": len(dict.fromkeys(ids)),
                           "resolved": resolved}
        return result

    # ---------------------------------------------------------------- C1-26-3 (D4)

    def _check_active(self, lists, inputs, people: "_People") -> CheckResult:
        result = CheckResult("C1-26-3", PASS)
        missing = [n for n in (RECIPIENTS, MY_WORK_USERS) if not lists[n]]
        if missing:
            result.status = BLOCKED
            result.evidence = {"blocked_reason": "INPUT_" + "_AND_".join(str(inputs[n]["state"]) for n in missing),
                               "lists_missing": missing}
            return result
        if not people.readable:
            result.status = BLOCKED
            result.evidence = {"blocked_reason": "SOURCE_NOT_ASSESSABLE"}
            return result
        groups = {pid: [] for pid in dict.fromkeys([*lists[RECIPIENTS], *lists[MY_WORK_USERS]])}
        for name in (RECIPIENTS, MY_WORK_USERS):
            for pid in dict.fromkeys(lists[name]):
                groups[pid].append(name)
        undetermined = 0
        for pid, membership in groups.items():
            located = people.locate(pid)
            if located is not None:
                result.issues.append({"code": located, "personnel_id": pid, "groups": membership})
                continue
            row = people.real_row(pid)
            if text(row.get("active_status")) != ACTIVE:
                result.issues.append({"code": "PERSONNEL_NOT_ACTIVE", "personnel_id": pid, "groups": membership})
            resolution = people.link(pid, "technician_id")
            if resolution.resolution != RESOLVED or resolution.target is None:
                undetermined += 1
                result.issues.append({"code": "TECHNICIAN_UNRESOLVED", "personnel_id": pid, "groups": membership,
                                      "outcome": UNDETERMINED, "resolution": resolution.resolution})
                continue
            if text(resolution.target.values.get("active_status")) != ACTIVE:
                result.issues.append({"code": "TECHNICIAN_NOT_ACTIVE", "personnel_id": pid, "groups": membership,
                                      "technician_id": resolution.linked_id})
        failing = [i for i in result.issues if i.get("outcome") != UNDETERMINED]
        result.status = FAIL if failing else (UNDETERMINED if undetermined else PASS)
        result.evidence = {"unique_people": len(groups), "undetermined": undetermined}
        return result

    # ---------------------------------------------------------------- C1-26-4 / -5 (D3)

    _SPECS = (
        SourceSpec("personnel", "personnel_master", (RefSpec("technician_id", "TECHNICIAN"),
                                                     RefSpec("user_id", "ACCOUNT"), RefSpec("driver_id", "DRIVER"))),
        SourceSpec("departments", "department_master", ()),
        SourceSpec("link_technician", "personnel_technician_link_history", (
            RefSpec("personnel_id", "PERSONNEL"), RefSpec("previous_technician_id", "TECHNICIAN"),
            RefSpec("new_technician_id", "TECHNICIAN"))),
        SourceSpec("link_account", "personnel_account_link_history", (
            RefSpec("personnel_id", "PERSONNEL"), RefSpec("previous_user_id", "ACCOUNT"),
            RefSpec("new_user_id", "ACCOUNT"))),
        SourceSpec("link_driver", "personnel_driver_link_history", (
            RefSpec("personnel_id", "PERSONNEL"), RefSpec("previous_driver_id", "DRIVER"),
            RefSpec("new_driver_id", "DRIVER"))),
        SourceSpec("lifecycle_personnel", "personnel_lifecycle_history", (RefSpec("personnel_id", "PERSONNEL"),)),
        SourceSpec("lifecycle_department", "department_lifecycle_history", (RefSpec("department_id", "DEPARTMENT"),)),
        SourceSpec("caretaker", "equipment_caretaker_history", (
            RefSpec("equipment_id", "EQUIPMENT"), RefSpec("technician_id", "TECHNICIAN"),
            RefSpec("recorded_from_technician_id", "TECHNICIAN"))),
        SourceSpec("crane_driver", "crane_driver_responsibility_history", (
            RefSpec("vehicle_id", "VEHICLE"), RefSpec("driver_id", "DRIVER"),
            RefSpec("recorded_from_driver_id", "DRIVER"))),
        SourceSpec("department_history", "personnel_department_history", (
            RefSpec("personnel_id", "PERSONNEL"), RefSpec("department_id", "DEPARTMENT"),
            RefSpec("recorded_from_department_id", "DEPARTMENT"))),
        SourceSpec("v2_repair", "repair_assignment", (RefSpec("repair_id", "REPAIR_JOB"),
                                                      RefSpec("assignee_id", "TECHNICIAN")), v2_rows_only=True),
        SourceSpec("v2_pm", "pm_work_assignment", (RefSpec("pm_work_order_id", "PM_JOB"),
                                                   RefSpec("assignee_id", "TECHNICIAN")), v2_rows_only=True),
        SourceSpec("jobs_repair", "repair_order", (RefSpec("asset_id", "ASSET"),), job_rows=True),
        SourceSpec("jobs_pm", "pm_work_order", (RefSpec("asset_id", "ASSET"),), job_rows=True),
    )
    # Sources check C1-26-5 cannot do without (a missing one blocks it).
    _REQUIRED_FOR_5 = ("personnel", "technicians", "accounts", "drivers", "v2_repair", "v2_pm", "jobs_repair",
                       "jobs_pm")
    _STATIC_COVERAGE = (
        CoverageEntry("asset_branch_history", "asset_branch_history", EXCLUDED_BY_CONTRACT, "R1",
                      detail="C1 CC-5: accepted R1 precedent (R1 TEST rows target real vehicles); not reopened, "
                             "not an R2f relationship"),
        CoverageEntry("vehicle_registration_history", "vehicle_registration_history", EXCLUDED_BY_CONTRACT, "R1",
                      detail="C1 CC-5 (R1 registry history); not an R2f relationship"),
        CoverageEntry("vehicle_driver", "vehicle_driver", UNTAGGED, "LEGACY",
                      detail="Phase 6 legacy history; no TEST metadata, operational by contract (C1 §14/§15)"),
    )

    def _references(self, sources: dict[str, Source], targets: dict[str, Target]):
        check4 = CheckResult("C1-26-4", PASS)
        check5 = CheckResult("C1-26-5", PASS)
        coverage: list[CoverageEntry] = []
        gaps: list[str] = []
        blocked4 = blocked5 = False
        for key in ("technicians", "accounts", "drivers", "vehicles", "equipment"):
            src = sources[key]
            coverage.append(CoverageEntry(key, src.tab, src.status, "REFERENCE_MASTER",
                                          rows=len(src.rows) if src.readable else None,
                                          detail=self._problem(src) or "scope as proven by the repository per row "
                                                 "(live: untagged master, every row REAL)"))
            if src.status == NOT_ASSESSABLE:
                gaps.append(f"{src.tab}: {self._problem(src)}")
        for spec in self._SPECS:
            src = sources[spec.key]
            if not src.readable:
                coverage.append(CoverageEntry(spec.key, spec.tab, src.status, "TAGGED_SOURCE",
                                              detail=self._problem(src)))
                # H3-01: neither an unreadable NOR an absent tagged source proves
                # TEST segregation (C1 §15 fail closed; no C1 clause makes an
                # absent R2f tab sufficient evidence — owner decision D5 PENDING).
                blocked4 = True
                if src.status == NOT_ASSESSABLE:
                    gaps.append(f"{spec.tab}: {self._problem(src)} — TEST segregation not provable")
                else:
                    gaps.append(f"{spec.tab}: tab absent ({self._problem(src)}) — TEST segregation not provable")
                if spec.key in self._REQUIRED_FOR_5:
                    blocked5 = True
                    if src.status == ABSENT:
                        gaps.append(f"{spec.tab}: tab absent — REAL reference integrity not provable")
                continue
            rows = src.rows
            legacy_rows = 0
            tagged: list[Mapping[str, object]] = []
            for row in rows:
                if spec.v2_rows_only and not is_v2_row(row):
                    legacy_rows += 1
                    continue
                if spec.job_rows and _job_scope(row) == _SCOPE_LEGACY:
                    legacy_rows += 1
                    continue
                tagged.append(row)
            test_rows = real_rows = 0
            verified: set[str] = set()
            for row in tagged:
                scope = _flag_scope(row)
                if scope == _SCOPE_INVALID:
                    issue = {"code": "TEST_FLAG_INVALID", "tab": spec.tab, "row": self._row_id(spec, row)}
                    check4.issues.append(issue)
                    check5.issues.append(dict(issue))
                    continue
                if scope == REFERENCE_SCOPE_TEST:
                    test_rows += 1
                    if not text(row.get("test_batch_id")).strip():
                        check4.issues.append({"code": "TEST_BATCH_MISSING", "tab": spec.tab,
                                              "row": self._row_id(spec, row)})
                else:
                    real_rows += 1
                    if text(row.get("test_batch_id")):
                        check5.issues.append({"code": "REAL_ROW_HAS_TEST_BATCH", "tab": spec.tab,
                                              "row": self._row_id(spec, row)})
                if spec.job_rows and text(row.get("assignment_model")) not in (ASSIGNMENT_MODEL_LEGACY,
                                                                               ASSIGNMENT_MODEL_TECHNICIAN_V2):
                    check5.issues.append({"code": "JOB_MARKER_INVALID", "tab": spec.tab,
                                          "row": self._row_id(spec, row)})
                for ref in spec.refs:
                    value = text(row.get(ref.column))
                    if not value.strip():
                        continue  # UNSET is not a reference
                    target = self._resolve_target(ref, row, targets)
                    if target is None:
                        issue = {"code": "ASSET_TYPE_INVALID", "tab": spec.tab, "row": self._row_id(spec, row)}
                        (check4 if scope == REFERENCE_SCOPE_TEST else check5).issues.append(issue)
                        continue
                    verified.add(f"{ref.column}->{target.name}")
                    outcome = self._judge(scope, value, target, text(row.get("test_batch_id")))
                    if outcome == _TARGET_UNPROVABLE:
                        # H3-01: an absent or unassessable target master proves
                        # nothing (TEST or REAL) — never clean, never READY.
                        if scope == REFERENCE_SCOPE_TEST:
                            blocked4 = True
                        else:
                            blocked5 = True
                        gap = (f"{spec.tab}.{ref.column}: target {target.source.tab} {target.source.status} "
                               f"({self._problem(target.source)}) — reference not provable")
                        if gap not in gaps:
                            gaps.append(gap)
                    elif outcome is not None:
                        issue = {"code": outcome, "tab": spec.tab, "row": self._row_id(spec, row),
                                 "column": ref.column, "value": value}
                        (check4 if scope == REFERENCE_SCOPE_TEST else check5).issues.append(issue)
            coverage.append(CoverageEntry(spec.key, spec.tab, EXAMINED, "TAGGED_SOURCE", rows=len(rows),
                                          test_rows=test_rows, real_rows=real_rows,
                                          references_verified=tuple(sorted(verified)),
                                          detail=f"{legacy_rows} untagged legacy row(s) not TEST data by contract"
                                          if legacy_rows else ""))
        self._real_link_uniqueness(sources["personnel"], check5)
        self._v2_integrity(sources, targets, check5)
        coverage.extend(self._STATIC_COVERAGE)

        check4.status = FAIL if check4.issues else (BLOCKED if blocked4 else PASS)
        check5.status = FAIL if check5.issues else (BLOCKED if blocked5 else PASS)
        check4.evidence = {"test_reference_violations": len(check4.issues), "coverage_complete": not blocked4}
        check5.evidence = {"real_reference_defects": len(check5.issues), "coverage_complete": not blocked5}
        return coverage, gaps, check4, check5

    @staticmethod
    def _problem(src: Source) -> str:
        if src.problem is None:
            return ""
        return f"{src.problem}" + (f" ({', '.join(src.headers)})" if src.headers else "")

    @staticmethod
    def _row_id(spec: SourceSpec, row: Mapping[str, object]) -> str:
        for column in ("record_id", "link_event_id", "lifecycle_event_id", "repair_assignment_id", "pm_assignment_id",
                       "repair_id", "pm_work_order_id", "personnel_id", "department_id"):
            if text(row.get(column)):
                return text(row.get(column))
        return ""

    @staticmethod
    def _resolve_target(ref: RefSpec, row: Mapping[str, object], targets: dict[str, Target]) -> Target | None:
        if ref.target != "ASSET":
            return targets[ref.target]
        return {"VEHICLE": targets["VEHICLE"], "EQUIPMENT": targets["EQUIPMENT"]}.get(text(row.get("asset_type")))

    @staticmethod
    def _judge(scope: str, value: str, target: Target, batch: str) -> str | None:
        """None = proven clean. Any target that is not a successfully validated
        master (ABSENT or NOT_ASSESSABLE) is _TARGET_UNPROVABLE. TEST rows (C1
        §15): clean only on exactly one match that is TEST-scoped and of the
        row's own batch; a REAL match is a violation, anything else unproven.
        REAL rows: exactly one REAL match."""
        if not target.source.readable:
            return _TARGET_UNPROVABLE
        entries = target.scopes.get(value, [])
        matches = [s for s, _ in entries]
        if scope == REFERENCE_SCOPE_TEST:
            if REFERENCE_SCOPE_REAL in matches or _SCOPE_LEGACY in matches:
                return "TEST_REFERENCES_REAL"
            if _SCOPE_INVALID in matches:
                return "TEST_REFERENCE_SCOPE_UNPROVEN"
            if not matches:
                return "TEST_REFERENCE_MISSING"
            if len(matches) > 1:
                return "TEST_REFERENCE_AMBIGUOUS"
            if batch.strip() and entries[0][1] != batch:
                return "TEST_REFERENCE_BATCH_MISMATCH"  # a missing row batch is TEST_BATCH_MISSING already
            return None
        real = sum(1 for s in matches if s in (REFERENCE_SCOPE_REAL, _SCOPE_LEGACY))
        if real == 1:
            return None
        if real > 1:
            return "REFERENCE_AMBIGUOUS"
        return "REFERENCE_SCOPE_UNPROVEN" if matches else "REFERENCE_MISSING"

    @staticmethod
    def _real_link_uniqueness(personnel: Source, check5: CheckResult) -> None:
        if not personnel.readable:
            return
        real = [r for r in personnel.rows if _flag_scope(r) == REFERENCE_SCOPE_REAL]
        for column, code in (("personnel_id", "PERSONNEL_ID_DUPLICATE"), ("technician_id", "TECHNICIAN_LINK_SHARED"),
                             ("user_id", "ACCOUNT_LINK_SHARED"), ("driver_id", "DRIVER_LINK_SHARED")):
            counts: dict[str, int] = {}
            for row in real:
                value = text(row.get(column))
                if value.strip():
                    counts[value] = counts.get(value, 0) + 1
            for value, count in counts.items():
                if count > 1:
                    check5.issues.append({"code": code, "value": value, "holders": count})

    @staticmethod
    def _v2_integrity(sources: dict[str, Source], targets: dict[str, Target], check5: CheckResult) -> None:
        """R2f-h1 integrity (H1-01 included) of every REAL V2 set, unchanged."""
        for kind, key, jobs_key in ((REPAIR, "v2_repair", "jobs_repair"), (PM, "v2_pm", "jobs_pm")):
            src, jobs = sources[key], sources[jobs_key]
            if not src.readable or not jobs.readable:
                continue
            rows = src.rows
            tab_wide = tab_issues(kind, rows)
            for code, count in tab_wide.items():
                check5.issues.append({"code": f"V2_{code}", "tab": kind.assignment_tab, "count": count})
            job_rows = {text(r.get(kind.job_id_column)): r for r in jobs.rows}
            real_jobs = sorted({text(r.get(kind.job_id_column)) for r in rows
                                if is_v2_row(r) and _flag_scope(r) == REFERENCE_SCOPE_REAL})
            for job_id in real_jobs:
                job = job_rows.get(job_id)
                if job is None or text(job.get("assignment_model")) != ASSIGNMENT_MODEL_TECHNICIAN_V2:
                    check5.issues.append({"code": "V2_ROW_JOB_MISSING" if job is None else "V2_ROW_ON_LEGACY_JOB",
                                          "tab": kind.assignment_tab, "job_id": job_id})
                    continue
                scope = {"is_test_data": text(job.get("is_test_data")), "test_batch_id": text(job.get("test_batch_id"))}
                state = derive_assignment_state(kind, job_id, rows, scope)
                for code, count in state.issues.items():
                    if code in tab_wide:
                        continue  # already reported once for the tab
                    check5.issues.append({"code": f"V2_{code}", "tab": kind.assignment_tab, "job_id": job_id,
                                          "count": count})
                if not state.issues and state.status == STATUS_AMBIGUOUS:
                    check5.issues.append({"code": "V2_CURRENT_SET_AMBIGUOUS", "tab": kind.assignment_tab,
                                          "job_id": job_id})

    # ---------------------------------------------------------------- C1-26-6

    _SCHEMA_REQUIREMENTS = (
        ("jobs_repair", "repair_order (V2 job marker + scope)"),
        ("jobs_pm", "pm_work_order (V2 job marker + scope)"),
        ("v2_repair", "repair_assignment (V2 assignee columns)"),
        ("v2_pm", "pm_work_assignment (V2 assignee columns)"),
        ("personnel", "personnel_master (R2f-a relationship read)"),
        ("technicians", "technician_master (R2f-a bounded read)"),
        ("accounts", "user_account (R2f-a bounded read)"),
        ("drivers", "driver_master (R2f-e bounded read)"),
    )

    def _check_schema(self, sources: dict[str, Source]) -> CheckResult:
        result = CheckResult("C1-26-6", PASS)
        verified = []
        for key, label in self._SCHEMA_REQUIREMENTS:
            src = sources[key]
            if src.readable:
                verified.append(label)
            else:
                result.issues.append({"code": f"SCHEMA_{src.problem}", "tab": src.tab, "requirement": label,
                                      "headers": list(src.headers)})
        result.status = FAIL if result.issues else PASS
        result.evidence = {"requirements": len(self._SCHEMA_REQUIREMENTS), "verified": verified}
        return result


# ---------------------------------------------------------------------------
# Personnel / links (REAL scope, exact text)
# ---------------------------------------------------------------------------


class _People:
    def __init__(self, personnel: Source, technicians: Source, accounts: Source) -> None:
        self._personnel = personnel
        self._references = {"technician_id": technicians, "user_id": accounts}
        self.readable = personnel.readable and technicians.readable and accounts.readable
        self._rows = personnel.rows if personnel.readable else []
        self._real = [r for r in self._rows if _flag_scope(r) == REFERENCE_SCOPE_REAL]

    def locate(self, personnel_id: str) -> str | None:
        """None when exactly one REAL row has this exact personnel_id; else a code."""
        if not personnel_id.strip():
            return "INPUT_ID_BLANK"
        exact = [r for r in self._rows if text(r.get("personnel_id")) == personnel_id]
        real = [r for r in exact if _flag_scope(r) == REFERENCE_SCOPE_REAL]
        if len(real) == 1:
            return None
        if len(real) > 1:
            return "PERSONNEL_AMBIGUOUS"
        if any(_flag_scope(r) == _SCOPE_INVALID for r in exact):
            return "PERSONNEL_SCOPE_INVALID"
        return "PERSONNEL_SCOPE_MISMATCH" if exact else "PERSONNEL_NOT_FOUND"

    def real_row(self, personnel_id: str) -> Mapping[str, object]:
        return next(r for r in self._real if text(r.get("personnel_id")) == personnel_id)

    def link(self, personnel_id: str, column: str):
        row = self.real_row(personnel_id)
        linked = text(row.get(column))
        holders = sum(1 for r in self._real if text(r.get(column)) == linked) if linked.strip() else 0
        reference = self._references[column].reference
        assert reference is not None
        return resolve_link(linked, id_column=column, reference=reference, context=DATA_CONTEXT_REAL, batch_id="",
                            holders=holders)

    def population(self) -> list[dict[str, object]]:
        """Informational only — never a check, never an approved recipient list."""
        out = []
        for row in self._real:
            pid = text(row.get("personnel_id"))
            if self.locate(pid) is not None:
                continue
            technician = self.link(pid, "technician_id")
            account = self.link(pid, "user_id")
            out.append({
                "personnel_id": pid, "active_status": text(row.get("active_status")),
                "technician": {"resolution": technician.resolution, "technician_id": technician.linked_id,
                               "active_status": text(technician.target.values.get("active_status"))
                               if technician.target is not None else None},
                "account": {"resolution": account.resolution, "user_id": account.linked_id},
            })
        return out


__all__ = ["GoLiveReadinessService", "ReadinessReport", "CheckResult", "CoverageEntry", "REQUIREMENTS"]
