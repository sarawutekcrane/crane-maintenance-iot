# R4 / TASK-010 — RT3-B Master Catalogue CAN_VIEW Read Safety — Result

**Status:** RT3-B CANDIDATE. UNSTAGED and UNCOMMITTED, local only, waiting for independent review. This is Mock/Fake
evidence only. It is not a PostgreSQL PASS, not Production readiness and not R4 completion. No Git write action was
taken.

**Authorization:** Owner-approved bounded RT3-B implementation (5-path allowlist) on
`feature/r4-pm-master-runtime-readiness-b1`, exact base `e62acb82259794df423ff03eeef94ddccd8bca70` (RT3-A R2). It closes
the residual RT3-A R2 limitation: direct Master runtime catalogue reads had no `CAN_VIEW` check.

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote HEAD | `origin/feature/r4-pm-master-runtime-readiness-b1` = `e62acb8…bca70` (exact base) |
| Base content | Every RT3-A R2 path at `e62acb8` matches the RT3-A R2 delivery manifest byte for byte |
| Isolated checkout | A fresh local clone in the scratchpad, detached at the base, with push disabled |
| Older worktrees | Untouched (RT1 original worktree, RT2 clone, RT3-A clone) |
| HEAD after work | Unchanged at the base; every change unstaged |

## 2. Root cause
`GET /pm/plans/{pm_plan_id}/active-revision` and `GET /pm/plans/{pm_plan_id}/revisions/{revision_id}`
(`api/v1/pm.py`) took no `RequestContext`. `PmService.get_active_task_revision` / `get_task_revision` therefore had no
actor to check: RT3-A R2 added only the server-scope gate. A caller without `CAN_VIEW` could read a Master catalogue of
the server's own scope. The router-wide `access_management_write_policy` covers writes only.

**Internal caller.** `PmService.open_work_order` (Phase-4 seed Plans) calls `get_active_task_revision(pm_plan_id)`
with no actor. The route already requires `can_manage_pm`, and the Plan must be the vehicle model's
`assigned_pm_plan_id` (a seed Plan). This call is unchanged and still works. It could reach a Master id only through a
Phase-4 model assignment naming a `PMMP-` Plan, and it would then be refused (no actor), which fails closed.

## 3. Correction
| Where | Change |
|---|---|
| `PmService.is_master_catalogue_id` (new, static) | `PMMP-` catalogue-class discriminator. It imports nothing and is never proof of identity or authority. |
| `PmService._require_master_catalogue_in_scope(pm_plan_id, not_found, context)` | For a Master catalogue: **(1)** a trusted actor (`_require_trusted`, 403 `PM_OUTCOME_CONTEXT_REQUIRED`), **(2)** `can_view` (`require_capability`, 403), both checked **before** any scope or catalogue read; then the unchanged RT3-A R2 checks: **(3)** the server's own TEST/REAL scope (`_pm_read_context`, 503 when unconfigured, never REAL), **(4)** the Plan id recomputed from the stored Plan code, otherwise the existing 404 |
| `get_active_task_revision(pm_plan_id, context=None)` and `get_task_revision(pm_plan_id, revision_id, context=None)` | Optional trailing `context`, passed to the gate. All callers are traced: the two routes pass the actor, and `open_work_order` keeps the seed-only call. A direct call without an actor on a Master id is refused (no bypass). |
| `api/v1/pm.py` `_catalogue_reader` + both routes | The routes resolve the actor through the existing `get_current_context` **only for a Master catalogue id**, and pass it to the service. Seed reads resolve no actor, keeping the Phase-4 path. |

**Why the router resolves the actor only for Master ids.** In Access Management mode, `get_current_context` runs
`AccessService.effective_context`, which performs several validated repository reads (personnel, departments, history,
events, link history). Resolving an actor on every seed read would add those reads and their failure modes to a
previously anonymous, read-only route. In production the result is identical to `Depends(get_current_context)`, because
the application overrides nothing. The service, not the router, is the authoritative gate. Tests set the actor through
the real development identity headers (`X-Dev-Role` / `X-Dev-User-Id`) and the request-context middleware.

No new permission, authorization service, middleware or framework layer was added. The Phase-4 seed catalogue policy
is unchanged.

## 4. Authorization matrix
**Master catalogue (`PMMP-…`), via both routes and direct service calls:**

| Caller | Before (RT3-A R2) | After (RT3-B) |
|---|---|---|
| Same scope, trusted, `can_view` | 200 | **200** |
| Same scope, no capability, or `can_manage_pm` only | 200 | **403** (nothing disclosed) |
| Untrusted actor (no or blank user), direct call or `context=None` | 200 | **403** |
| Foreign scope (TEST-A↔TEST-B, TEST↔REAL), no `can_view` | 404 | **403** (no existence or ownership oracle) |
| Foreign scope, `can_view` | 404 | 404 (unchanged) |
| Foreign revision id under a local Plan id, `can_view` | 404 | 404 (unchanged) |
| Older unscoped Master id, `can_view` | 404 | 404 (unchanged) |
| Server scope unconfigured, no `can_view` | 503 | **403** (authorization first) |
| Server scope unconfigured, `can_view` | 503 | 503 (never REAL) |

**Seed catalogue (`PMP-…`):** anonymous, capability-less or `can_view` caller, in any or no server scope → **200,
unchanged**. No actor is resolved and no Master module is loaded.

## 5. Tests
**Five new RT3-B tests** in `test_pm_master_persistence_contract.py`, on a shared repository with fully populated
TEST-A, TEST-B and synthetic REAL catalogues:

| Test | Proves |
|---|---|
| `rt3b_01` | Both routes, every scope: `can_view` → 200; a capability-less role → 403 without catalogue data; no GET writes anything (Work Orders, memberships, snapshots, anchors, journal, catalogue, outcomes) |
| `rt3b_02` | A refused actor gets 403 before 404 (foreign or missing) and before 503 (unconfigured). An authorized actor still gets the RT3-A R2 404 / 503. |
| `rt3b_03` | Direct service calls with no actor, a non-context object, no capability, `can_manage_pm`, or an untrusted or blank user are refused (403) with no writes. The internal default call (no actor) on a Master id is refused. `can_view` succeeds. |
| `rt3b_04` | Seed reads stay 200 for anonymous, capability-less and `can_view` callers in every scope, including an unconfigured one, and through internal service calls. With actor resolution forced to fail, seed reads still succeed (no actor is resolved), while Master reads fail (the actor is always resolved). |
| `rt3b_05` | The discriminator is not authority, and importing the routes and service loads no Master module |

**Updated, not weakened:**
- `rt3a_03` now passes a `can_view` actor to its direct service call. Without one, the call is correctly refused.
- The RT3-A R2 helper `http_get` now sets its actor through the real identity headers. Its old context override was
  ignored on Master reads and only passed because the default dev user is ADMIN.

`test_pm_plan_and_task_revision.py` needed **no change**: seed behaviour is unchanged.

| Run (from `backend/`) | Result |
|---|---|
| `tests/test_pm_master_persistence_contract.py` | 23 passed (11 RT3-A + 7 R2 + 5 RT3-B) |
| Affected regression (`test_pm_*`, `test_r4_pm_*`, `test_technician*`, `test_v2_*`, `test_repair_pm_work_authorization`, `test_repair_assignment_and_queues`, `test_r3_*`, `test_rev062_queue_derivation`, `test_access_management*`, `test_rev06_identity_and_core_g01_regression`) | 1362 passed, 4 skipped |
| Full backend `pytest -q -rs tests` (final source, SHA-256 pinned and re-verified) | **5895 passed, 0 failed, 4 skipped** (21m13s; the RT3-A R2 run was 5890, plus the 5 RT3-B tests) |
| Firewall tests `test_23`, `f24`, `f25`, `b1_13`, `b1_17`, RT3-A R2 `r2_07` | unchanged, pass |
| Mutation checks (8 mutants) | **8 / 8 killed**: no trusted-actor check; no `can_view` check; authorization after the scope lookup; discriminator always false; router never resolves the actor; router always resolves the actor; active route drops the actor; explicit route drops the actor |
| `git diff --check` | clean |
| ruff (`--isolated` defaults, changed files vs. base) | The new test file is clean. `api/v1/pm.py` has 4 more `B008` ("Depends in argument defaults"), the FastAPI idiom the file already uses 38 times. No other new finding. |
| Secret scan | no matches |

Skips are the known opt-in ones: the real `MAINTENANCE.xlsx` reconciliation and 3 live Google Sheets tests.

## 6. Mandatory Cleanup Review
| Item | Class | Evidence / impact |
|---|---|---|
| `_require_master_catalogue_in_scope` (RT3-A R2) | REPLACE (extended) | Now also checks the actor and `can_view`. One gate for both reads; no duplicate. |
| `PmService.is_master_catalogue_id` | RETAIN (new) | One discriminator used by the gate and the router; imports nothing. |
| `_MASTER_RUNTIME_PLAN_PREFIX` mirror of `RUNTIME_PLAN_PREFIX` | RETAIN | Avoids loading the Master on seed reads. Equality asserted by `r2_06`. |
| `api/v1/pm.py` `_catalogue_reader` | RETAIN (new) | Keeps seed reads free of actor resolution (§3) |
| Seed catalogue anonymous reads | RETAIN | Approved Phase-4 behaviour; outside this batch |
| `test_pm_plan_and_task_revision.py` | RETAIN, unchanged | No change needed |
| R2 test helper override of `get_current_context` | REPLACE | It was misleading on Master reads; replaced by real identity headers |

No destructive cleanup.

## 7. Remaining blockers and Production restrictions
- **Production Master stays dormant.** Application wiring never builds a Master (f24, f25, test_23, b1_17). This batch
  activates nothing.
- **OPEN-005:** no REAL Publish / Assign / Approve authority (fail-closed).
- **R11 / PostgreSQL:** catalogue rows still carry no scope column. The scoped unique keys, foreign keys,
  single-transaction writes, read snapshot and durable Master are documented in the RT3-A result, not built. The
  actor resolution and capability rules here apply unchanged to a PostgreSQL repository.
- **OPEN-016:** the 183 candidates are unapproved; the 52 missing-Plan rows are blocked. **OPEN-012:** real opening
  meters and past-PM evidence are missing. **E02:** thresholds are undecided.
- **Seed catalogue routes remain anonymous by approved Phase-4 policy.** Changing that is a separate decision.
- **R4 remains PARTIAL.**
