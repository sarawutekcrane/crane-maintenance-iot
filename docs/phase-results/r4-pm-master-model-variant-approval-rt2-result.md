# R4 / TASK-010 — RT2 OPEN-016 Approved Model Variant Mapping — Result

**Status:** RT2 CANDIDATE. UNSTAGED and UNCOMMITTED, local only, waiting for independent review. This is Mock/Fake
evidence only. It is not a PostgreSQL PASS, not Production readiness and not R4 completion. No Git action was taken:
the Owner withheld stage, commit, push, PR, merge and deploy.

**Authorization:** Owner-approved bounded RT2 implementation within a six-path allowlist. Branch
`feature/r4-pm-master-runtime-readiness-b1`, exact base `70d6b4046afa5a4873029000c3eea42a07ee430b` (RT1 commit).
Controlling decision: `DEC-R4-TASK010-MODEL-VARIANT-MAPPING-OPEN016-20261106`. Source audit: the RT2 read-only audit
of the same base.

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote HEAD | `origin/feature/r4-pm-master-runtime-readiness-b1` = `70d6b40…e430b` (exact base) |
| Isolated checkout | A fresh local clone in the scratchpad, detached at `70d6b40`, with push disabled. No branch was created or moved. |
| Previous worktree | Left as it was: HEAD `9a2929b`, the 7 RT1 files still unstaged (byte-identical to `70d6b40`). Not reset, cleaned or recommitted. |
| HEAD after work | Unchanged at `70d6b40`; every change unstaged |

## 2. What was built
`(VehicleModel.model_id, exact Master plan_code) → MasterSet.model_variant` now holds **only** through an explicit,
evidence-backed approval recorded in the RT1-bound Master store. The system distinguishes:
- a source candidate (`MappingCandidate`, never an approval);
- an approval (version 1, or a re-approval after a revocation);
- a correction (a new version naming another variant);
- a revocation (a new version naming none);
- a missing, conflicting or unverified mapping (refused, or serving nothing).

| Component | Path | Change |
|---|---|---|
| `ModelVariantApproval` (frozen) | `pm_master.py` | Fields: approval_id, model_id, plan_code, model_variant (`""` when revoked), state APPROVED/REVOKED, version per (model, Plan), preview_id, pinned source_digest, source_rows, evidence, reason, recorded_by, recorded_at, request_id |
| Store | `pm_master.py` | `PmMasterMockStore.variant_approvals`: an append-only tuple in the same atomic commit as its audit event. `latest_variant_approval(model_id, plan_code)`. |
| Writes | `pm_master.py` | `approve_model_variant` (APPROVE or CORRECT) and `revoke_model_variant` (REVOKE). One authorizer action, `KIND_VARIANT_APPROVE`, checked before any replay is disclosed. Then request id and reason, the existing fingerprint replay (`REQUEST_ID_REUSED`), and under `store.lock` the `expected_version` check (409 `PM_MASTER_STALE_VARIANT_APPROVAL`). Event kinds: `VARIANT_APPROVE`, `VARIANT_CORRECT`, `VARIANT_REVOKE`, each carrying a `diff_json` (from/to). |
| Reads | `pm_master.py` | `model_variant_source(context)` (`can_view`) is the existing `ModelVariantSource`. It returns the one variant of a pair's latest record when that record is APPROVED, and nothing otherwise. `variant_approval_history(context, model, plan)`. |
| Resolver | `pm_master.py` | `VehicleFacts.model_id` (additive) and `MockVehicleResolver.model_exists`, both on the exact runtime repository object |
| Default variant source | `pm_service.py` | `_variant_source(master, context, explicit)`: the explicit TEST seam if given; otherwise the bound Master's own approvals; otherwise `no_proven_model_variant`. Used by `_vehicle_pm_due` and `open_master_work_order`, only after the RT1 `_master_bound` check. |

**Not changed:** `pm_master_runtime.py` (`ModelVariantSource`, `model_variant_proven`, `no_proven_model_variant`,
`applicable_plans`), DUE01, DUE02A, E01, router, `dependencies.py`, adapters, frontend. There is no route for approval
or variant lookup, and production wiring still answers `MASTER_NOT_ACTIVE` (f24/f25).

### Evidence proof (all checked before any write; refusal = 422 `PM_MASTER_VARIANT_EVIDENCE_INVALID` + `issue`)
1. The model is registered in the resolver's repository (404 `VEHICLE_MODEL_NOT_FOUND`).
2. The Plan has a published head (422 `PM_MASTER_NOT_PUBLISHED`).
3. The head has a Set with exactly this variant, never case-folded (`VARIANT_NOT_IN_PUBLISHED_PLAN`).
4. The preview is registered (`PREVIEW_NOT_FOUND`) and its digest matches (`DIGEST_MISMATCH`).
5. The preview is the current registration of its source file (`PREVIEW_STALE`).
6. Each cited row is an ACCEPTED `MATCHED_PENDING_IMPLEMENTATION` candidate (`SOURCE_ROW_NOT_ACCEPTED_CANDIDATE`). This
   covers `PENDING_PM_PLAN` rows, REVIEW rows and unknown rows.
7. Each cited row names exactly this Plan and variant (`SOURCE_ROW_PLAN_OR_VARIANT_MISMATCH`).
8. Each cited row's `vehicle_ref` resolves to a registered vehicle of exactly this model (`SOURCE_ROW_MODEL_MISMATCH`).
9. No accepted candidate of the same model and Plan names another variant (`EVIDENCE_CONFLICT`).
10. Variant, rows (non-empty, distinct) and evidence are substantive (`VARIANT_REQUIRED`, `SOURCE_ROWS_REQUIRED`,
    `EVIDENCE_INSUFFICIENT`). Reason and request id use the existing validation.
11. `expected_version` equals the current version (409). Re-approving the in-force variant is refused as
    `PM_MASTER_VARIANT_APPROVAL_UNCHANGED`.

Revocation needs no preview, because withdrawing authority is the fail-closed direction. It still needs a reason,
substantive evidence and the current version, and a pair with no in-force approval cannot be revoked
(`PM_MASTER_VARIANT_NOT_APPROVED`).

### Later source changes: the chosen fail-closed handling
- Registering a newer preview **does not** rewrite, revoke or create any approval.
- An approval keeps its original evidence snapshot (preview_id, digest, rows) and stays in force.
- No candidate of the new preview is approved automatically.
- Every **new** decision must cite the current preview, so a superseded one is refused as `PREVIEW_STALE`.
- A source correction takes effect only through an explicit CORRECT or REVOKE (`test_rt2_06`, `test_rt2_11`,
  `test_rt2_14`).
- No broad reconciliation workflow was invented.

### Authority and isolation
- `TEST_PM_MASTER_EDITOR` (test-local `PERSONA_ACTIONS`) may approve, correct and revoke. `TEST_PM_MASTER_ASSIGNER`
  stays assignment-only.
- The application authorizer `deny_unproven_master_authority` refuses everyone, including ADMIN, root (every
  capability) and `can_manage_pm`.
- A REAL store can never carry a TEST authorizer (RT1).
- Approvals live in the scope-bound store, so another TEST batch, REAL, an unbound store or another repository never
  exposes them (Fleet Due `MASTER_NOT_ACTIVE`; opening refused with 409 scope or repository mismatch).

### Historical safety
- Approvals never touch Work Orders, memberships, anchors, outcomes or the journal.
- **Revoke after Work Orders exist:** Fleet Due shows `MODEL_VARIANT_UNVERIFIED` with no Sets, and Master-sourced
  opening is refused. All runtime state is byte-identical. Re-approving restores applicability over the same history.
- **Model change:** only the new model's approval applies. While the source still contradicts it, the approval is
  refused (`EVIDENCE_CONFLICT`) until the source itself is corrected. The old model's completion is not credited, and
  the old membership is unchanged.
- **New revision:** an approved variant missing from the head gives `NO_APPLICABLE_SET`. Its old Sets cannot be
  opened, and a variant not in the head cannot be approved.
- **`evaluate_master_set_due` (internal, no route):** its existing contract is kept unchanged and documented. It
  evaluates one Set's stored, membership-backed historical evidence and does not consult current applicability. After
  a revoke it still reports the historical decision (`test_rt2_13`), while the only PM Due route (Fleet/Vehicle) shows
  the Set as not applicable. It is not exposed as an API.

## 3. Files (6 allowed, 6 changed)
| Path | Status | Purpose |
|---|---|---|
| `backend/app/domain/pm_master.py` | M | Record, store, writes, reads, resolver additions, module note |
| `backend/app/domain/pm_service.py` | M | `_variant_source` default (Fleet/Vehicle Due + opening) |
| `backend/tests/test_pm_master_b1_mock.py` | M | Test-local `PERSONA_ACTIONS`: Editor gets `KIND_VARIANT_APPROVE` (import + 1 line) |
| `backend/tests/test_pm_master_runtime_readiness.py` | M | End-to-end run goes through a real RT2 approval; no synthetic variant dictionary |
| `backend/tests/test_pm_master_model_variant_approval.py` | A | 15 focused RT2 tests |
| `docs/phase-results/r4-pm-master-model-variant-approval-rt2-result.md` | A | This report |

## 4. Tests
| Run (from `backend/`) | Result |
|---|---|
| `tests/test_pm_master_model_variant_approval.py` | 15 passed |
| RT2 + end-to-end | 18 passed |
| Master/E01/Due focused (8 files incl. RT1, B1, bridge, Fleet Due, DUE01/02A, SUBMIT anchor) | 295 passed, 1 skipped |
| Affected regression (`test_pm_*`, `test_r4_pm_*`, `test_technician*`, `test_v2_*`, `test_repair_pm_work_authorization`, `test_repair_assignment_and_queues`, `test_r3_*`, `test_rev062_queue_derivation`) | 1275 passed, 4 skipped |
| Full backend `pytest -q -rs tests` (final source, SHA-256 pinned and re-verified) | **5872 passed, 0 failed, 4 skipped** (18m42s; RT1 base run was 5857, plus the 15 new tests) |
| Firewall tests `test_23`, `f24`, `f25`, `b1_13`, `b1_17` | unchanged, pass (inside the runs above) |
| Mutation checks (10 mutants, each removing one new check) | **10 / 10 killed**: conflict, model, stale preview, revoked-still-served, variant-in-plan, version, MATCHED status, Plan/variant, service ignores the Master source, service ignores the explicit seam |
| `git diff --check` | clean |
| ruff (`--isolated` defaults; no repository config) | The new test file is clean. No new findings in changed files compared with the base (pre-existing I001/UP017/RUF022/RUF059/B017 only). |
| Secret scan | no matches |

**End-to-end, TEST-only:** synthetic source → registered preview and review → publish → **explicit variant approval**
→ assign → open Master Work Order → Technician V2 SUBMIT with FAKE IoT anchor → reviewer CLOSE → HTTP Fleet PM Due.
- 600 h at 650 → 1,250 (DUE at 1,250).
- CARRIER_ENGINE, CRANE_ENGINE and ODOMETER independent.
- Partial, NOT_PERFORMED, RETURNed and unfinished work never advance an anchor.
- No verified meter → UNKNOWN, never 0.
- `can_view` reads derived Due but gets 403 on raw outcomes and history.
- Domain and HTTP results are identical; GET requests write nothing.
- REAL and another batch show `MASTER_NOT_ACTIVE`.

Skips are the known opt-in ones: the real `MAINTENANCE.xlsx` reconciliation and the live Google Sheets tests.

## 5. PostgreSQL contract (documented, NOT implemented, NOT PASS)
- Table `pm_master_model_variant_approval` with `is_test_data` + `test_batch_id`. CHECK constraints: `TRUE` + non-blank
  batch or `FALSE` + empty; APPROVED needs a non-empty variant and evidence references; REVOKED needs an empty variant.
- Foreign keys to `vehicle_model(model_id)` and the registered preview. Every read filtered by the server scope in SQL.
- Unique (scope, model_id, plan_code, version); unique (scope, request_id) across Master writes. Append-only, with no
  UPDATE or DELETE grants.
- The version check plus insert of the record and its audit event in one transaction. The concurrency loser fails on
  the unique key instead of relying on the in-process lock.
- The Fleet Due read sees approvals, assignments, revisions and memberships in one read-only snapshot (REPEATABLE READ).
- REAL decisions stay impossible until an Owner-approved authority exists (OPEN-005 / VAL-AM, R11).

## 6. Cleanup Review
| Item | Class | Evidence |
|---|---|---|
| `synthetic_test_only_variants` / `SYNTHETIC_MODEL_VARIANTS` (bridge test) | RETAIN | Still used by the existing bridge and Fleet tests. The end-to-end test moved to real approvals. |
| Explicit `model_variants` seam (`with_master_reads`, `open_master_work_order`) | RETAIN | Test-only. No app module calls it (`test_23`). The mutation removing it fails 56 tests. |
| `no_proven_model_variant` | RETAIN | Still the fallback when no Master or source exists |
| One authorizer action for approve/correct/revoke | RETAIN | Mirrors `set_assignment` (one action, several event kinds). Keeps the persona map minimal. |
| Separate mapping service or table outside the Master store | REJECTED | Would lose the RT1 scope and repository binding |
| Approving in bulk or from `mapping_basis` | REJECTED | Would be automatic approval of the 183 candidates |
| Re-checking approvals inside `frozen_set` / `evaluate_master_set_due` | DEFER | Internal method with no route. Its contract is documented and tested. Decide if it ever gets a route. |
| `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warnings | DEFER | Pre-existing helper `_unprocessable`, out of scope |

## 7. Limitations and open gates
- Mock only. No persisted Master or approvals; Google Sheets has no Master storage; no PostgreSQL schema. The
  in-process lock is not multi-process atomicity.
- OPEN-005: no REAL approver. The TEST personas stay test-local.
- OPEN-016 real data: the 183 `MATCHED_PENDING_IMPLEMENTATION` candidates (57 model_ids, 29 variants; exact
  (model_id, Plan) pair count UNVERIFIED) are **not** approved. Each needs an explicit decision by a future authorized
  REAL approver against a registered real preview. The 52 `PENDING_PM_PLAN` rows stay blocked.
- The real `MAINTENANCE.xlsx` has never been run through the Python preview (UNVERIFIED).
- OPEN-012 baselines, model `component_roles`, real IoT, E02 thresholds and calendar/multiple-condition triggers stay
  undecided or missing; nothing was invented.
- **R4 remains PARTIAL.**
