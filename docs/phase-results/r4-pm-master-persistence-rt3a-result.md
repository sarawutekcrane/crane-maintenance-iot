# R4 / TASK-010 — RT3-A Scope-Safe Master Identity & Persistence Contract — Result

**Status:** RT3-A **R2** CANDIDATE (RT3-A plus the independent-review correction R2, §2a). UNSTAGED and UNCOMMITTED, local only, waiting for independent review. This is Mock/Fake
evidence only. It is not a PostgreSQL PASS, not Production readiness and not R4 completion. No Git write action was
taken.

**Authorization:** Owner-approved bounded RT3-A implementation on `feature/r4-pm-master-runtime-readiness-b1`, exact
base `e66bdee6263e2bfc6e29b51d2e06993ff1849d44`. The approved 7-path allowlist was later extended by Owner approval to
**8 paths**, adding `backend/app/domain/pm_service.py` for one expression in `_verify_membership_provenance()`. Source:
the RT3 read-only audit (finding F1, verified catalogue collision across scopes; finding F2, the commit contract).

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote HEAD | `origin/feature/r4-pm-master-runtime-readiness-b1` = `e66bdee…9d44` (exact base) |
| Isolated checkout | A fresh local clone in the scratchpad, detached at the base, with push disabled |
| Older worktrees | Untouched: the original (RT1, `9a2929b`, 7 unstaged files) and the RT2 clone (`70d6b40`, 6 unstaged files) |
| Stop gate | Triggered before any edit: `pm_service.py:971` rebuilt the runtime Plan id from `plan_code` alone. `GET /pm/plans/{id}/active-revision` (`mock/repository.py:1410`) returns the newest revision of a Plan id across every scope, so a shared Plan id would leak revisions between scopes. Owner approved the eighth path; nothing else was added. |
| HEAD after work | Unchanged at the base; every change unstaged |

## 2. Defect and fix (BACKEND_CROSS_STORAGE)
**Before.** Three ids carried no scope:
- the revision id, `PMMREV-{plan_code}-{n}`;
- the runtime Plan id, a digest of `plan_code`;
- the runtime task id, derived from the revision id.

The E01 catalogue is stored by these ids in the shared repository. TEST batch B opening the same Plan as batch A
therefore got **409 `PM_MASTER_CATALOGUE_CONFLICT`** (reproduced in RT3). If the catalogues had been identical, they
would have shared rows instead.

**After.**
| Id | Derivation | Where |
|---|---|---|
| Scope token | `MasterDataScope.token` = sha256(`["pm-master-scope", is_test_data, test_batch_id]`)[:12]. Deterministic, and different for TEST A, TEST B and REAL. | `pm_master.py` |
| Revision id | `master_revision_id(scope, plan_code, n)` = `PMMREV-{token}-{plan_code}-{n:04d}`. An unbound store gives `PMMREV-UNBOUND-…`, never REAL's token. | `pm_master.py` (`publish`) |
| Revision scope | `MasterRevision.data_scope` and `MasterWorkOrderSnapshot.data_scope` are set by `publish` / `freeze_selection` from the **bound store** (never from a caller, label or Plan name) | `pm_master.py` |
| Runtime Plan id | `runtime_plan_id(plan_code, scope)` = digest of (`plan`, is_test_data, test_batch_id, plan_code). `runtime_plan_id_of(revision)` uses the revision's own scope. A missing or invalid scope raises `PM_MASTER_SCOPE_UNBOUND`. | `pm_master_runtime.py` |
| Runtime task id | Unchanged formula over the now scope-qualified revision id | `pm_master_runtime.py` |

**Used the same way everywhere:**
- `build_catalogue` refuses an unscoped revision or one whose id is not its scope-qualified id
  (`PM_MASTER_REVISION_SCOPE_MISMATCH`).
- `build_membership` also refuses when the snapshot's scope is not exactly the Work Order's own TEST/REAL cells.
- `frozen_set` verifies the stored membership against its **own stored scope cells** (Plan id and scope-qualified
  revision id). Invalid or disagreeing cells mean the Set is unverified.
- `master_frozen_set` and `_verify_membership_provenance` (`pm_service.py`, the one approved expression) use
  `runtime_plan_id_of(revision)`.

**What happens to older or forged records:**
- Unbound, unscoped or forged revisions never reach the catalogue (`ValueError` → existing 422 mapping).
- A stored membership with an older, unscoped Plan id fails the Fleet read closed (500 `MEMBERSHIP_PROVENANCE_MISMATCH`).
- Nothing is migrated, guessed or treated as REAL. Mock has no persisted history.

## 2a. R2: direct Plan catalogue reads are gated by server scope (independent-review correction)
**Finding (verified; pre-existing, not introduced by RT3-A).** `GET /pm/plans/{pm_plan_id}/active-revision` and
`GET /pm/plans/{pm_plan_id}/revisions/{revision_id}` (`api/v1/pm.py`) take no `RequestContext`. They reach
`PmService.get_active_task_revision` / `get_task_revision` and the Mock repository's id-only reads, and catalogue rows
carry no scope. The router-wide `access_management_write_policy` covers writes only.

A disposable HTTP reproduction used one shared repository with fully populated TEST-A and TEST-B catalogues and a
synthetic REAL one. **Every direction returned 200 with the foreign revision and all 7 tasks, with `can_view` and with
no capability at all.** At base `e66bdee` the routes were equally open (an anonymous seed read returns 200), and
before RT3-A, Master catalogues even shared one id across scopes. Distinct RT3-A ids are not secrecy: they are
derivable from the Plan code and batch. Classification: BACKEND_CROSS_STORAGE.

**Correction (scope isolation only):**
- `PmService._require_master_catalogue_in_scope(pm_plan_id, not_found)` runs first in both read methods.
- It applies only to a **Master** runtime catalogue: the `PMMP-` prefix, `pm_master_runtime.RUNTIME_PLAN_PREFIX`,
  mirrored as `pm_service._MASTER_RUNTIME_PLAN_PREFIX` so seed reads never import the Master modules.
- It resolves the **server's own** TEST/REAL cells through the existing `_pm_read_context()`: 503 when unconfigured,
  never REAL by default.
- It recomputes the Plan id from the **stored** Plan code in the server scope (`runtime_plan_id_in_scope`; invalid
  cells give None). The caller-supplied id is never proof.
- **Foreign scope, an older unscoped Master id, or a missing Plan** → the method's existing 404
  (`PM_PLAN_NOT_FOUND` / `PM_TASK_REVISION_NOT_FOUND`), with no catalogue content disclosed.
- A foreign revision id under an in-scope Plan id stays not-found through the existing repository rule that a
  revision is returned only under its own Plan id.
- Phase-4 seed catalogues (`PMP-…`) are untouched: same behaviour, no new capability, no Master import.

**Residual security limitation (explicitly NOT fixed here).** These two routes still have **no `can_view` check**. An
in-scope Master catalogue, like the seed catalogue, is readable without the Owner-approved `CAN_VIEW` contract.
Closing that needs `api/v1/pm.py` to take `RequestContext` and pass it on, plus migration of the anonymous-read tests
(`test_pm_plan_and_task_revision.py`, `test_pm_repair_part_linkage.py`, possibly `test_pm_assignment_authority.py`).
That is at least three paths outside the approved scope, and it changes seed-catalogue policy, so it is a separate,
explicitly approved batch. **A Master catalogue is not production-safe merely because its Plan id passes this scope
check.** Before any production Master activation, Master direct reads must also satisfy `CAN_VIEW`. Until then the
production Master activation firewall (application wiring never builds a Master: f24, f25, test_23, b1_17) stays the
barrier.

## 3. Commit contract (storage-independent; the PostgreSQL contract in executable Mock form)
`PmMasterMockStore.commit` now refuses, with `MasterCommitConflict(kind)` and **nothing written** (neither the event
nor any record), an append that would:
- reuse a committed **request id** (`REQUEST_ID`);
- reuse a **revision** number or id, or carry a revision whose scope is not the store's (`REVISION` / `SCOPE`);
- reuse an **assignment version** for (vehicle, assembly) (`ASSIGNMENT_VERSION`);
- reuse a **variant-approval version** for (model, Plan), or an approval id (`VARIANT_APPROVAL_VERSION`);
- resolve an already-resolved **(preview, entry)** again, or reuse a resolution id (`REVIEW_ENTRY`);
- reuse a **preview id** (`PREVIEW_ID`).

The service's in-lock checks, authorization and expected-version checks are unchanged. Every commit site maps a
conflict to the operation's **existing** outcome through `_conflict_replay`:

| Operation | Request id committed meanwhile | Other conflict |
|---|---|---|
| publish | replay (same fingerprint) / `REQUEST_ID_REUSED` 409 | `PM_MASTER_STALE_REVISION` 409 (current revision re-read) |
| assignment | replay / `REQUEST_ID_REUSED` | `PM_MASTER_STALE_ASSIGNMENT` 409 |
| approve / correct / revoke | replay / `REQUEST_ID_REUSED` | `PM_MASTER_STALE_VARIANT_APPROVAL` 409 |
| review | replay / `REQUEST_ID_REUSED` | `PM_MASTER_REVIEW_ALREADY_RESOLVED` 409 |
| preview | replay / `REQUEST_ID_REUSED` | `PM_MASTER_PREVIEW_CONFLICT` 409 (the only new code; no conflict path existed before) |

Before RT3-A, uniqueness depended only on the service's in-lock checks and an in-process `asyncio.Lock`. After it,
the append itself enforces uniqueness, so a writer working from a stale read can never create a second record.
`store.lock` is retained for Mock serialization.

## 4. Files (8 allowed; 6 changed incl. this report; R2 touched 4 of them)
| Path | Status | Why |
|---|---|---|
| `backend/app/domain/pm_master.py` | M | Scope token, `master_revision_id`, revision and snapshot scope, commit invariants, conflict mapping, module note |
| `backend/app/domain/pm_master_runtime.py` | M | Scope-safe Plan id, `runtime_plan_id_of`, scope checks in catalogue, membership and frozen Set; R2: `RUNTIME_PLAN_PREFIX`, `runtime_plan_id_in_scope` |
| `backend/app/domain/pm_service.py` | M | The approved expression at line 971 (`runtime.runtime_plan_id_of(revision)`); R2 (approved expansion): `_require_master_catalogue_in_scope` and its use in `get_active_task_revision` / `get_task_revision`, plus the prefix constant |
| `backend/tests/test_pm_master_e01_due_bridge.py` | M | test_01b uses a bound store (catalogues need a scope); test_26 builds revision 2 with `master_revision_id` instead of an unscoped literal |
| `backend/tests/test_pm_master_persistence_contract.py` | A | 11 RT3-A tests + 7 R2 tests (`test_rt3a_r2_01..07`) |
| `docs/phase-results/r4-pm-master-persistence-rt3a-result.md` | A | This report |

`test_pm_master_b1_mock.py` and `test_pm_master_model_variant_approval.py` needed no change. Not touched:
`repositories/*`, Sheets, router, `dependencies.py`, frontend, schema, Due logic.

## 5. Tests
| Run (from `backend/`) | Result |
|---|---|
| `tests/test_pm_master_persistence_contract.py` | 18 passed (11 RT3-A + 7 R2) |
| Master / E01 / Fleet / RT2 / end-to-end focused (6 files) | 152 passed, 1 skipped |
| Affected regression (`test_pm_*`, `test_r4_pm_*`, `test_technician*`, `test_v2_*`, `test_repair_pm_work_authorization`, `test_repair_assignment_and_queues`, `test_r3_*`, `test_rev062_queue_derivation`) | 1293 passed, 4 skipped (R2 final source) |
| Full backend `pytest -q -rs tests` (R2 final source, SHA-256 pinned and re-verified) | **5890 passed, 0 failed, 4 skipped** (19m32s; the RT3-A run was 5883, plus the 7 R2 tests). Skips are the known opt-in ones: the real `MAINTENANCE.xlsx` reconciliation and 3 live Google Sheets tests. |
| Firewall tests `test_23`, `f24`, `f25`, `b1_13`, `b1_17` | unchanged, pass (inside the runs above) |
| R2 mutation checks (7 mutants on the new gate) | **7 / 7 killed**: gate never applies; gate never refuses; unconfigured scope becomes REAL; explicit-revision read ungated; active-revision read ungated; scope helper derives a wrong TEST batch; an older unscoped Master Plan id accepted |
| RT3-A mutation checks (13 mutants, re-run on the R2 source) | **13 / 13 killed**: revision id ignores scope; Plan id ignores scope; catalogue skips the scope check; membership skips scope cells; `frozen_set` skips scope (killed by `test_rt3a_05b`, added after a first run where it survived); and commit allowing request-id reuse, duplicate revision, foreign scope, duplicate assignment, preview, review or variant version; conflict never replays |
| `git diff --check` | clean |
| ruff (`--isolated` defaults, changed files vs. base) | The new test file is clean. One new finding: `TRY004` (2×) in `pm_master_runtime.py` for `ValueError` on a missing scope. **Intentional:** callers already map `ValueError` from the runtime builders to the existing 422 (`pm_service.open_master_work_order`), whereas a `TypeError` would surface as a 500. Otherwise only pre-existing findings. |
| Secret scan | No credentials. Matches are only the word "token" (the scope identity token). |

**What the R2 tests prove** (shared repository with TEST-A, TEST-B and synthetic REAL catalogues; real HTTP routes)
- Each scope reads its own Master catalogue through both routes (`r2_01`).
- No scope reads another's, in all six directions: 404 with the existing code and no catalogue content. A missing
  catalogue answers the same way, so there is no existence oracle (`r2_02`).
- A foreign revision id under a local Plan id is not found (`r2_03`).
- An unconfigured server scope gives 503 for Master catalogues only; seed reads stay 200 (`r2_04`).
- An older unscoped Master catalogue is never served (`r2_05`).
- Reads leave memberships, Work Orders, journal and anchors byte-identical. Seed reads are unchanged with and
  without `can_view` in every scope (`r2_06`).
- In a fresh interpreter, seed reads through the application wiring load no Master module (`r2_07`).

**What the RT3-A tests prove**
- **Identity:** ids differ across TEST A, TEST B and REAL and are deterministic within a scope (`01`). Two TEST batches
  publish and open the same Plan in one repository, each with its own catalogue and membership (`02`; the base got 409
  there).
- **No leakage:** batch A's completion never appears in batch B's Fleet Due. Each runtime Plan id serves only its own
  revision through the plan-level catalogue read. A foreign-scope Master is still refused (`03`).
- **Fail closed:** unbound, unscoped or foreign-scoped revisions never reach the catalogue or a membership (`04`). A
  stored membership with an older unscoped Plan id fails the read closed with no migration (`05`). A membership whose
  scope cells disagree with its identity is unverified (`05b`).
- **Commit contract:** commit refuses every duplicate identity with nothing written (`06`). Competing commits,
  simulated as controlled stale reads, map to the existing stale 409s (`07`). A request committed meanwhile replays,
  or is `REQUEST_ID_REUSED` with a different payload (`08`). A failed commit writes nothing, and a retry after a lost
  response replays without duplicating (`09`).
- **History:** a new revision, a variant correct/revoke, and an assignment change and removal leave the opened Work
  Order, membership, results, outcomes, journal and meter anchors byte-identical. There is no cross-revision credit.
  The partial (NOT_PERFORMED) Set never becomes a completion, and the per-Set historical evaluator still reads exactly
  the frozen revision-1 evidence (`10`).

These are synthetic Mock simulations. They prove the Mock contract only, not multi-process PostgreSQL behaviour.

## 6. PostgreSQL / R11 contract (documented, NOT implemented, NOT PASS)
- **Scope:** every Master table has `is_test_data` and `test_batch_id`, with a CHECK constraint (`TRUE` + non-blank
  batch, or `FALSE` + empty). The store instance filters every query by the scope it was built from, and that is the
  server's own scope.
- **Unique keys:**
  - (scope, plan_code, revision_number) and (revision_id). Ids are now globally unique because they carry the scope
    token.
  - (scope, vehicle_id, assembly, version)
  - (scope, model_id, plan_code, version) and (approval_id)
  - (scope, preview_id, entry_id) and (resolution_id)
  - (scope, preview_id) — opaque preview ids (decision A01) should replace the counter
  - (scope, request_id) on audit events
  - existing: membership (request_id) and (pm_work_order_id)
- **Catalogue keys:** runtime Plan, revision and task ids are scope-qualified. `get_active_pm_task_revision` must
  never read across scopes (now guaranteed by the ids).
- **Foreign keys:** membership → scoped revision (`ON DELETE RESTRICT`); approval → vehicle_model and preview;
  assignment → vehicle. Append-only: no UPDATE or DELETE grants on Master history.
- **Transactions:** each record and its event in one transaction. A unique-key violation maps to the same replay or
  409 outcome as `MasterCommitConflict`. Opening a Work Order reads the Master rows `FOR SHARE` (or runs SERIALIZABLE)
  in the same transaction as the catalogue, Work Order and membership insert. Master and Repository share one
  database and unit of work.
- **Snapshot:** the Fleet Due read runs in one read-only REPEATABLE READ transaction across Master and repository.
- **Durability:** the Master is not durable today (in memory). Activation requires the R11 persistence above.
- **New id format:** `PMMREV-{scope token}-{plan_code}-{n}` and the scope-qualified `PMMP-` / `PMMT-` digests are
  deterministic. A future import of approved Master data must derive them in the target scope, never copy ids across
  scopes.

## 7. Mandatory Cleanup Review
| Item | Class | Evidence / impact |
|---|---|---|
| `runtime_plan_id(plan_code)` (unscoped) | REPLACE | Now `runtime_plan_id(plan_code, scope)` + `runtime_plan_id_of(revision)`. All call sites traced and updated (runtime ×4, `pm_service.py:971`). There is no external caller. |
| Literal revision id `PMMREV-{plan}-{n}` | REPLACE | `master_revision_id(scope, plan, n)`. Test fixtures that commit a literal id directly (Fleet f09, RT2 test_15) still work because they never build a catalogue, and catalogues refuse unscoped ids. |
| `store.lock` | RETAIN | Still serializes Mock writes; uniqueness no longer relies on it |
| In-lock service checks (expected version, already resolved) | RETAIN | They give the precise errors in the normal path; `commit` is the backstop |
| `_conflict_replay` helper | RETAIN (new) | One shared mapping for 5 commit sites; no new event family or ledger |
| `PM_MASTER_PREVIEW_CONFLICT` | RETAIN (new code) | The only conflict with no existing outcome; reachable only by a competing preview id |
| `TRY004` on scope `ValueError` | RETAIN | Deliberate, so callers keep the 422 mapping (§5) |
| Unbound `PmMasterMockStore()` default | RETAIN | Used by B1 pure-contract tests. Its revisions are marked UNBOUND and refused by the runtime. |
| Shared runtime `PmPlan` row across scopes | REMOVED (by design) | Plan ids are now per scope |
| `_require_master_catalogue_in_scope` (R2) | RETAIN (new) | Reuses `_pm_read_context` and the runtime derivation. It is not an authorization service; no new route. |
| `_MASTER_RUNTIME_PLAN_PREFIX` duplicate of `RUNTIME_PLAN_PREFIX` | RETAIN | Avoids loading the Master on seed reads. Equality asserted by `r2_06`. |
| `can_view` on the two catalogue routes | DEFER (separate approval) | Needs `api/v1/pm.py` + anonymous-read test migration and changes seed policy (§2a) |
| Counter-based `preview_id` | DEFER (R11 / A01) | Protected by the commit's preview-id conflict meanwhile |
| Sheets `pm_master_bridge` refusal | RETAIN | SHEETS_ONLY; no Master storage added to Sheets |

## 8. Remaining dependencies
- **CAN_VIEW on direct catalogue reads (R2 residual):** required before any production Master activation (§2a).
- **R11 / PostgreSQL:** durable Master in the same database and unit of work, the constraints and snapshot in §6, and
  real concurrency tests.
- **OPEN-005:** no REAL Publish / Assign / Approve authority. REAL writes stay fail-closed; the TEST personas stay
  test-local.
- **OPEN-016:** the 183 source candidates are still unapproved; the 52 missing-Plan rows stay blocked.
- **OPEN-012:** verified opening meters and previous real PM evidence are still missing (they stay UNKNOWN).
- **E02:** near-due and overdue thresholds, and calendar or multiple-condition triggers, are not decided.
- The real `MAINTENANCE.xlsx` has never been run through the preview.
- **R4 remains PARTIAL.**
