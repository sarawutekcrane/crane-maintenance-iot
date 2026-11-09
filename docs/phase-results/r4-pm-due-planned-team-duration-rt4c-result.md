# R4 / TASK-010 — RT4-C Planned Team Duration on PM Due — Result

**Status:** RT4-C CANDIDATE. UNSTAGED and UNCOMMITTED, local only, waiting for independent review. This is Mock/Fake
evidence only. It is not a PostgreSQL PASS, not Production readiness and not R4 completion. No Git write action was
taken.

**This batch made no Master schema, Preview or digest change, no frontend change and no man-hour calculation, and
activated nothing in production. R4 remains PARTIAL.**

**Authorization:** Owner-approved bounded RT4-C implementation on `feature/r4-pm-readiness-reconciliation-b1`, exact
base `0d784d3b492e974f3bb6d68124ec75dbc901629c` (RT4-B). The allowlist has 4 paths:
1. `backend/app/domain/pm_service.py`
2. `backend/app/api/v1/pm_schemas.py`
3. `backend/tests/test_pm_fleet_due.py`
4. this document

Source: the R4 functional exit-criteria reconciliation, criterion #7.

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote HEAD | `origin/feature/r4-pm-readiness-reconciliation-b1` = `0d784d3…629c` (exact base, fetched) |
| Checkout | A fresh clone of the remote branch in the session scratchpad, at the base, with push disabled. Every earlier checkout (RT4-A copy, XR, source-proof, RT4-B and exit-audit clones) was left untouched. |
| Starting hashes | `pm_service.py` `3fa4c213…a7f8`, `pm_schemas.py` `7b8ca937…05ac`, `test_pm_fleet_due.py` `3d1fbdc8…ae43` (the RT4-B final bytes) |
| HEAD after work | Unchanged at the base; every change unstaged |

## 2. Requirement, source evidence and existing provenance path
- **Requirement:** Master Roadmap R4: planned PM time "means the time the team needs to finish the work, not the sum of
  man-hours."
- **Source data:** the real MAINTENANCE `source_pm_cycles` has `team_duration_raw`, `team_duration_minutes` and
  `duration_basis`. The read-only export audit found 260 of 260 cycles with minutes and basis `TEAM_ELAPSED`.
- **Provenance path (already in place, unchanged):**
  - `pm_source_preview._raw_cells` keeps every source column verbatim (`_raw` gives `"150"` for an integral float);
  - `CandidateSet.raw` carries it;
  - `pm_master.build_candidate` copies it into the frozen `MasterSet.raw`;
  - the published revision therefore holds the cells.
- **Confirmed omission:** at the base no code referenced `team_duration_*` / `duration_basis`, and `PmDueSet` /
  `PmDueSetResponse` had no planned-duration field.

## 3. Implementation
| Where | Change |
|---|---|
| `pm_service.planned_team_minutes(raw)` (new, pure) | Reads only `team_duration_minutes` and `duration_basis` from one Set's `raw` cells. Returns a positive `int` only when the basis is **exactly** `TEAM_ELAPSED` and the minutes are a plain whole number above zero (`^[0-9]+(\.0+)?$` after trim, e.g. `"150"`, `"150.0"`). Otherwise `None`. |
| `PmDueSet.planned_team_minutes: int \| None = None` | New field; the default keeps existing constructors valid |
| `_pm_due_set` | `planned_team_minutes=planned_team_minutes(master_set.raw)`, from the Set of the **evaluated** `revision` (the RT4-B page snapshot's head) |
| `PmDueSetResponse.planned_team_minutes: int \| None` | Declared with a description: TEAM_ELAPSED minutes, not technician man-hours, never summed, never used for Due. The route builds `PmDueSetResponse(**vars(s))`, so the field reaches the JSON, as `null` when absent. |

**`None` cases:**
- a missing column, or a missing or other basis (case- and space-exact);
- a duplicated cell (contradictory evidence);
- blank or whitespace;
- `0` / `0.0`, negative, fractional (`1.5`, `150.5`), `NaN`, `inf` / `Infinity`, exponent (`1e2`), signed (`+150`);
- boolean-like (`True`), arbitrary text, or the Thai text.

**What it never does:**
- reads `team_duration_raw`;
- rounds a value;
- defaults (vehicle, model or Plan wide);
- infers from the interval, item count or labor;
- influences DUE / NOT_DUE / UNKNOWN.

Nothing else changed: the Due formula, groups, anchors, membership, RT4-A, RT4-B, approvals, revision selection,
diagnostics, authorization, scope, replay, E01, paging, queue and Repair Request provenance.

## 4. Evidence (`test_pm_fleet_due.py`, 29 new test cases)
**How the duration enters:** through the **real** path. A deep copy of the synthetic source workbook gets
`team_duration_minutes`, `duration_basis` and the Thai `team_duration_raw` on chosen cycle rows; the revision is then
registered, resolved and published. The shared fixture is unchanged, and no field is attached after evaluation.

| Test | Proves |
|---|---|
| `rt4c_01_06` | Revision 2 with CARRIER 150, CRANE 90 and KM `45.0` gives Due Sets 150 / 90 / 45 as `int`, each its own (never summed or shared). `MasterSet.raw` holds the cells. Due status is unchanged (UNKNOWN, no completion). |
| `rt4c_02` | Both HTTP routes (`/pm/due/vehicles/{id}` and the fleet page) include `planned_team_minutes` on every Set: 150, and `null` for an invalid value or no columns, never omitted or 0 |
| `rt4c_03` (20 cases) | Every invalid value or basis gives `None` in the domain and `null` in the JSON |
| `rt4c_03b` | The pure parser contract on raw cells: no columns, basis or minutes missing, duplicated cell, the text column never read; `"150.00"` gives 150 |
| `rt4c_04` | A revision-1 Set without the columns gives `None`, with the same Due result as before (NOT_DUE 1500 from its completion); no exception, migration or default |
| `rt4c_05` | Revision 2 (150) with a completed Work Order frozen on revision 2, then revision 3 (120): Due shows 3 / 120, never 150, and still gives no cross-revision credit; the revision-2 membership is unchanged |
| `rt4c_07_10` | Domain and HTTP fleet and vehicle reads change nothing (Work Orders, memberships, results, snapshots, anchors, assignments, approvals, revisions, journal, audit); `MasterSet.raw`, revision id and `content_digest` (stored and recomputed), membership and catalogue are byte-identical |
| `rt4c_08` | No capability, `can_manage_pm` only, or no actor gives 403 (HTTP 403 carries no field). Unbound, other batch, REAL, another repository, no resolver and a server of another batch give `MASTER_NOT_ACTIVE` with no Sets, so no duration is disclosed. |
| `rt4c_09` (both RT4-B boundaries) | A duration revision published **during** an in-flight Fleet Due read stays out of that page (all `None`, revision 1); the next read shows 150 / 90, so no live Master read was reintroduced |

At the base the RT4-C selection fails 27 of 29, because the field is absent.

## 5. Mutation checks (disposable copies; the repository source was never mutated)
| Mutant | Killed by (assertion) |
|---|---|
| M1 `duration_basis` ignored | `rt4c_03` (5 wrong-basis cases: `150 is None`), `rt4c_03b` |
| M2 zero / negative accepted | `rt4c_03` (`0`, `0.0`, `-150`) |
| M3 the Thai `team_duration_raw` read instead of the minutes | `rt4c_01_06`, `rt4c_02`, `rt4c_05`, `rt4c_09`, `rt4c_03b` (`None != 150`) |
| M4a another Set's duration | `rt4c_01_06`, `rt4c_02`, `rt4c_09` |
| M4b the live Master head instead of the evaluated revision | `rt4c_09` (in-flight page ≠ pre-write page) |
| M5 API field omitted (renamed in the schema) | `rt4c_02` (explicit field-presence assertion); secondary `KeyError` elsewhere |
| M6 zero instead of `None` when evidence is missing | `rt4c_03`, `rt4c_03b`, `rt4c_04`, `rt4c_09` (`0 is None`) |

**7 / 7 killed** by assertion failures. A first M4b formulation called the capability-checked read with no actor and
failed by exception. It was replaced by a direct live store-head read before counting. Re-run on the final bytes with
identical results.

## 6. Results (synthetic Mock / Fake data only; `pytest -q -rs -p no:cacheprovider`, scratch venv)
| Run (from `backend/`) | Result |
|---|---|
| `test_pm_fleet_due.py` (48 existing + 29 new) | **77 passed** |
| Affected (`test_pm_*` incl. manager queue, Master B1, RT1–RT3-B, persistence contract (RT3-A/B, RT4-A), E01 bridge, Due evidence, SUBMIT anchor; `test_r4_pm_*`, `test_technician*`, `test_v2_*`, `test_r3_*`, `test_access_management*` incl. XR-07, `test_repair_request*` incl. XR-04, `test_defect_provenance`, `test_repair_pm_work_authorization`, `test_repair_assignment_and_queues`, `test_rev062_queue_derivation`, `test_rev06_identity_and_core_g01_regression`) | **1458 passed, 0 failed, 4 skipped** (56 files, 4m33s; run in a disposable copy byte-identical to the final source) |
| Full backend `pytest -q -rs tests` (final source, SHA-256 pinned before the run and re-verified after) | **5954 passed, 0 failed, 4 skipped** (16m56s). The RT4-B batch reported 5925; the difference is the 29 new RT4-C test cases. Skips are the known opt-in ones: the real `MAINTENANCE.xlsx` reconciliation and 3 live Google Sheets tests. |
| Firewall tests (`test_23`, `f24`, `f25`, `b1_13`, `b1_17`, `r2_07`) | inside the runs above, unchanged |
| `git diff --check` | clean |
| ruff (`--isolated` defaults; changed files vs. the base file at the same path) | no new findings |
| Secret scan | no matches |

## 7. Files (4 allowed, 4 changed)
| Path | Status | Change |
|---|---|---|
| `backend/app/domain/pm_service.py` | M | `import re`, `TEAM_ELAPSED_BASIS`, `_WHOLE_MINUTES`, `planned_team_minutes()`, `PmDueSet.planned_team_minutes`, set in `_pm_due_set` |
| `backend/app/api/v1/pm_schemas.py` | M | `PmDueSetResponse.planned_team_minutes` with description |
| `backend/tests/test_pm_fleet_due.py` | M | `rt4c_01..10` (29 cases), helpers `duration_workbook`, `publish_durations`, `planned` |
| `docs/phase-results/r4-pm-due-planned-team-duration-rt4c-result.md` | A | This report |

## 8. Mandatory Cleanup Review
| Item | Class | Evidence / impact |
|---|---|---|
| `planned_team_minutes()` | RETAIN (new) | One small pure parser beside `PmDueSet`; no service, cache or model |
| `PmDueSet` / `PmDueSetResponse.planned_team_minutes` | RETAIN (new) | One informational field each; default `None` keeps existing constructors |
| `MasterSet.raw` / `CandidateSet.raw` | RETAIN, unchanged | The authoritative frozen provenance read by RT4-C; no schema or digest change |
| `team_duration_raw` (Thai text) | RETAIN as provenance, never parsed | M3 proves the parser ignores it |
| Frontend display (`PmDueSetTable.tsx`, `types.ts`) | DEFER | Out of the approved allowlist; the API now carries the field |
| Planned duration on a Master-sourced Work Order (from its frozen membership) | DEFER | Needs a decision to add the fact to the frozen membership; `MasterSetMembership` was not changed |
| Technician man-hours / labor | DEFER (R5) | Distinct from planned team elapsed time |

No destructive cleanup.

## 9. Remaining gaps and limitations
- **Frontend:** the Fleet / Vehicle Due UI does not show the field yet (separate small batch).
- **Work Order:** the planned duration is not shown on a Master-sourced Work Order (it would need the frozen membership
  to carry it; DEFER).
- **R4 limits unchanged:**
  - component topology and real meters (SOURCE_DATA, OPEN-012);
  - Master authority (OPEN-005) and a TEST trial authorization;
  - E02 windows and alerts (R7);
  - calendar / multi-condition rules (none in the source).
- **PostgreSQL R11:** the Master (incl. Set `raw` provenance) must be stored durably with its cells unchanged, and the
  Due read needs the full REPEATABLE READ snapshot. Other R11 items (resolver, atomic opening and SUBMIT, Repair Request
  unique source, Access Management log key, concurrency tests) are unchanged.
- No real source activation is authorized; the **Production Master remains dormant**.

## 10. Git state
- `HEAD` is unchanged at `0d784d3b492e974f3bb6d68124ec75dbc901629c`. Nothing is staged; nothing was committed or pushed.
- Working tree: `M backend/app/api/v1/pm_schemas.py`, `M backend/app/domain/pm_service.py`,
  `M backend/tests/test_pm_fleet_due.py`, `?? docs/phase-results/r4-pm-due-planned-team-duration-rt4c-result.md`.

**R4 remains PARTIAL.**
