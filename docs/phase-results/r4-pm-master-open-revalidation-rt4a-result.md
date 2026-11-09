# R4 / TASK-010 — RT4-A Master Authority Revalidation at Work Order Open — Result

**Status:** RT4-A CANDIDATE. UNSTAGED and UNCOMMITTED, local only, waiting for independent review. This is Mock/Fake
evidence only. It is not a PostgreSQL PASS, not Production readiness and not R4 completion. No Git write action was
taken.

**Authorization:** Owner-approved bounded RT4-A implementation (3-path allowlist) on
`feature/r4-pm-readiness-reconciliation-b1`, exact base `1f67358856ef6e2726934a4edd72768f0b0f43bd` (RT3-B). Source:
the post-RT3-B read-only reconciliation, defect **D-1**.

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote HEAD | `origin/feature/r4-pm-readiness-reconciliation-b1` = `1f67358…6e2726934a4edd72768f0b0f43bd` (exact base, fetched) |
| Checkout | Fresh session clone, single worktree, clean before work. Older RT1–RT3-B worktrees are not in this container and were not touched. |
| HEAD after work | Unchanged at the base; every change unstaged |

## 2. Root cause (D-1, BACKEND_CROSS_STORAGE)
`PmService.open_master_work_order` checked each selected Set's explicit Plan assignment (`PmMasterService.resolve_plan`)
and the approved model variant (`runtime.model_variant_proven` over the live `model_variant_source`). Then it **awaited**
`MeterService.capture_current_state` and called `MockRepository.create_pm_master_work_order` without checking again.
Master writes (`set_assignment`, `approve_model_variant`, `revoke_model_variant`) serialize on `store.lock`, but the
opening holds no Master lock. A write that landed during the capture await was therefore never seen.

Reproduced at the base by the new tests (§5): a REVOKE, an unassignment, a Plan reassignment or a variant CORRECT
injected in the capture still **opened** the Work Order (`Failed: DID NOT RAISE ApiError` ×4).

## 3. Correction
| Where | Change |
|---|---|
| `PmService._require_master_authority` (new, static, synchronous) | The **existing** per-Set loop, moved unchanged: for EVERY frozen Set, `resolve_plan` must be (`EXPLICIT_ASSIGNED`, the exact `plan_code`), and `model_variant_proven` must hold for the vehicle's registered model, the Plan and the Set's variant. Same 422 codes, messages and details: `PM_MASTER_PLAN_NOT_ASSIGNED` / `PM_MASTER_MODEL_VARIANT_UNVERIFIED`. |
| `open_master_work_order` | Calls the helper (1) where the loop was, before any catalogue, membership or capture, so ordinary refusals still write nothing; and (2) **again right after the capture returns, as the statement immediately before the `try` that awaits `create_pm_master_work_order`.** |

**Why the second call closes the in-process window.**
- Both reads are live:
  - `resolve_plan` reads `store.latest_assignment` at call time;
  - the RT2 source reads `store.latest_variant_approval` at call time.
- Nothing can run between the final check and the write:
  - there is no `await` between the final check and the repository call;
  - `MockRepository.create_pm_master_work_order` contains no `await`, `async for` or `async with` (verified in source, and asserted by `rt4a_09`);
  - `_new_pm_work_order` and `_store_pm_work_order` are plain functions.
- So no other task can run between the final authority read and the commit.

**Unchanged:**
- **Identity:** the exact frozen revision, the selected Set keys, the Item lineage and the membership.
- **Order of checks:** the RT1 scope and repository-identity checks, the replay lookup, `can_manage_pm` and the trusted actor all still run first.
- **Contracts:** request fingerprint, idempotent replay, and multiple Work Orders under different request ids (D3).
- **Nothing new:** no route, lock, table, permission or error code. A caller-supplied scope is never authority: the Master scope still comes from the bound store, checked by RT1.

## 4. Replay and refusal safety
- **A valid replay** returns at the replay lookup, before the capture and both authority checks. It returns the original
  immutable Work Order even after today's approval was revoked. It is never re-authorized against the current Master
  (`rt4a_06`: the capture is replaced by a function that fails if called, and runtime state stays byte-identical).
- **A request refused by the second check** creates no Work Order, membership, catalogue plan, revision or tasks, PM
  outcome, work result, journal event or SUBMIT meter anchor (`rt4a_01..04`, `operational_state`).
- **Known residue (not byte-identical):** the second check necessarily runs after the open-time capture. A refused
  request therefore leaves **exactly one `PM_WORK_ORDER_OPEN` meter snapshot** that no Work Order references. The tests
  assert this explicitly. The refusal message keeps its established wording ("nothing was changed"); that refers to
  Work Order records, not to this snapshot. The same residue already exists on the seed open path and on a refused
  repository create. No cleanup was added. Resolution belongs to R11: one transaction (defect D-3).

## 5. Tests
Nine new RT4-A tests in `test_pm_master_persistence_contract.py`. Each race test runs the competing Master write
**inside** the real `capture_current_state` (`during_capture`). Every Master write goes through the real authorized
`PmMasterService` API (TEST personas, version checks, audit), never by editing the store.

| Test | Proves |
|---|---|
| `rt4a_01` | A REVOKE during the capture → 422 `PM_MASTER_MODEL_VARIANT_UNVERIFIED` (exact details); no operational record; one orphan open snapshot |
| `rt4a_02` | Unassignment (explicit NONE) during the capture → 422 `PM_MASTER_PLAN_NOT_ASSIGNED` (`plan_source` EXPLICIT_NONE) |
| `rt4a_03` | Only the **second** selected Set's assembly (CRANE) reassigned to another Plan → refused naming `CRANE_A` while CARRIER stays valid (every Set is checked). A vehicle-wide reassignment is also refused. |
| `rt4a_04` | The approval CORRECTed to another variant (a real evidenced RT2 correction) → refused. The new variant is never silently used. |
| `rt4a_05` | Unrelated Master writes during the capture (another model's approval, another vehicle's assignment, **a newer revision of the same Plan**) → opens normally, on the exact requested revision 1 and its Set |
| `rt4a_06` | Replay after a revoke returns the original Work Order, with no capture and no state change. A new request is refused before any capture. |
| `rt4a_07` | Two different request ids still open two Work Orders (D3 unchanged) |
| `rt4a_08` | No `can_manage_pm` and an untrusted actor give 403; a foreign TEST batch gives 409 `PM_MASTER_SCOPE_MISMATCH`; another repository object gives 409 `PM_MASTER_REPOSITORY_MISMATCH`. All refuse **before** the capture is reached, with nothing written. |
| `rt4a_09` | Source structure: the final `_require_master_authority` call immediately precedes the `try` whose first await is the create; there is no await in the create's arguments; there are exactly two checks; the Mock create has no await. A race injected in the capture cannot detect a gap added after the check, so this is asserted on the source. |

| Run (from `backend/`) | Result |
|---|---|
| `test_pm_master_persistence_contract.py` | **32 passed** (11 RT3-A + 7 R2 + 5 RT3-B + 9 RT4-A) |
| RT4-A tests against the **base** `pm_service.py` (disposable copy) | 5 failed (`rt4a_01..04` DID NOT RAISE: race reproduced; `rt4a_09` no second check), 4 passed |
| Affected regression (`test_pm_*`, `test_r4_pm_*`, `test_technician*`, `test_v2_*`, `test_r3_*`, `test_access_management*`, `test_repair_pm_work_authorization`, `test_repair_assignment_and_queues`, `test_rev062_queue_derivation`, `test_rev06_identity_and_core_g01_regression`; 52 files) | **1371 passed, 0 failed, 4 skipped**. Run in a disposable `backend/` copy, where it showed 1370 passed and 1 failed: `test_b1_fix_08` reads `docs/phase-results/…`, which the copy does not contain. Re-run in the real checkout, it passes, and it is in the full run below. |
| Full backend `pytest -q -rs tests` (final source, SHA-256 pinned before and re-verified after) | **5904 passed, 0 failed, 4 skipped** (15m37s; RT3-B reported 5895, plus the 9 RT4-A tests). Skips are the known opt-in ones: the real `MAINTENANCE.xlsx` reconciliation and 3 live Google Sheets tests. |
| Firewall tests `test_23`, `f24`, `f25`, `b1_13`, `b1_17`, `r2_07` | unchanged, inside the runs above |
| `git diff --check` | clean |
| ruff (`--isolated` defaults, changed files vs. base) | no new findings in either Python file |
| Secret scan | no matches |

**Mutation checks (disposable copies under the session scratchpad; the repository source was never mutated):**

| Mutant | Killed by |
|---|---|
| M1 second check removed | `rt4a_01..04` (DID NOT RAISE), `rt4a_09` |
| M2 second check re-verifies the variant only (no assignment re-check) | `rt4a_02`, `rt4a_03` (DID NOT RAISE), `rt4a_01` (details), `rt4a_09` |
| M3 second check with an always-proving variant source (no variant re-check) | `rt4a_01`, `rt4a_04` |
| M4 `await asyncio.sleep(0)` between the final check and the create | `rt4a_09` |
| M5a second check always refuses (valid openings rejected) | `rt4a_05`, `rt4a_06`, `rt4a_07` (+ others) |
| M5b a replay re-authorized against today's approval | `rt4a_06` |

**6 / 6 killed.** A first M2 formulation (a proxy Master) failed tests for the wrong reason, so it was replaced by the
faithful variant-only re-check above before counting.

## 6. Remaining Mock / PostgreSQL differences
- **In-process only.** The guarantee rests on cooperative single-process asyncio and a no-await Mock create. Several
  processes, or a database adapter whose create awaits I/O, are **not** covered. PostgreSQL must read the vehicle's
  assignment and variant-approval rows `FOR SHARE` (or run SERIALIZABLE) in the **same transaction** as the catalogue,
  Work Order, membership and open snapshot insert, with the unique keys of the RT3-A §6 contract.
- **Orphan open snapshot** on a race refusal (D-3): R11 same-transaction fix.
- **Vehicle model change during the capture** (a repository write, not a Master write) is not re-read: re-reading it
  would need an `await` after the check. The model id is the one read before the capture. In PostgreSQL it is covered by
  the same transaction. R11.
- The Master is still in memory (not durable); preview ids are still counters (A01).

## 7. Files (3 allowed, 3 changed)
| Path | Status | Change |
|---|---|---|
| `backend/app/domain/pm_service.py` | M | `_require_master_authority` (the existing loop, extracted unchanged) + second call after the capture + comment |
| `backend/tests/test_pm_master_persistence_contract.py` | M | `rt4a_01..09`, helpers `during_capture`, `never_capture`, `operational_state`, `refused_during_capture`; imports |
| `docs/phase-results/r4-pm-master-open-revalidation-rt4a-result.md` | A | This report |

Not touched: `pm_master.py`, `pm_master_runtime.py`, repositories, Sheets, routes, `dependencies.py`, frontend, schema,
Due logic.

## 8. Mandatory Cleanup Review
| Item | Class | Evidence / impact |
|---|---|---|
| Inline per-Set authority loop in `open_master_work_order` | REPLACE | Moved verbatim into `_require_master_authority`; same codes, messages and details. Not redundant: it is the single implementation, called at the two points that need it, so the rule cannot drift between them. |
| `_require_master_authority` | RETAIN (new) | Static and synchronous, so it cannot introduce a yield; no new service or layer |
| Second authority call after the capture | RETAIN (new) | The D-1 fix; mutants M1–M3 prove it is load-bearing |
| `store.lock` | RETAIN | Still serializes Master writes; the opening deliberately takes no Master lock (no new lock layer) |
| Open-time capture before the Work Order write | RETAIN | Core Demo Fix; the race-path orphan snapshot is DEFER (R11, D-3) |
| "nothing was changed" wording on the second-check refusal | RETAIN (documented) | The established 422 contract text; refers to Work Order records. The snapshot residue is documented in §4. |
| `rt4a_09` source-structure assertion | RETAIN (new test) | The only deterministic detector of an await gap after the check (M4) |
| Fleet Due torn Master read (D-2) | DEFER | Separate batch (RT4-B) |
| Vehicle-model re-read after the capture | DEFER (R11) | Would require an await; transactional in PostgreSQL |

No destructive cleanup.

## 9. Restrictions kept
Production Master dormant (application wiring unchanged). OPEN-005 REAL authority fail-closed. OPEN-012 and OPEN-016
data unchanged. No E02 thresholds or alerts. Technician V2 only, no Legacy fallback, no Sheets feature, no schema or
migration. **R4 remains PARTIAL.**
