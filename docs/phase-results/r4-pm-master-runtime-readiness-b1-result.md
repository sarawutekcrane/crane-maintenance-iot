# R4 / TASK-010 — PM Master Runtime Readiness RT1 — Result

**Status:** RT1 CANDIDATE. UNSTAGED and UNCOMMITTED, local only, waiting for independent review. This is Mock/Fake
evidence only. It is not a PostgreSQL PASS, not Production readiness and not R4 completion. No Git action was taken:
the Owner withheld stage, commit, push, PR, merge and deploy for this batch.

**Authorization:** Owner-approved bounded RT1 implementation (G1, G2, G5) within a seven-path allowlist on the existing
branch `feature/r4-pm-master-runtime-readiness-b1`, base `9a2929bc68f300b9852a4b3521f2d34b9e0eeef5`.
Source audit: the RT1 readiness audit of the same base (gaps G1–G8).

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote | `origin` = `sarawutekcrane/crane-maintenance-iot` |
| Branch / HEAD | `feature/r4-pm-master-runtime-readiness-b1` = `origin` = `9a2929bc…eef5` (exact base) |
| Worktree before work | clean, no untracked files; single worktree; nothing overwritten |
| Fleet PM Due B1 R2 | present in the base (`9a2929b`, 19 paths) and not recommitted |
| HEAD after work | unchanged at the base; every change unstaged |

## 2. Defects fixed
| Gap | Class | Defect (reproduced on base) | Fix |
|---|---|---|---|
| G1 | BACKEND_CROSS_STORAGE | The in-memory Master had no TEST/REAL scope. An injected Master's Plans, assignments and Sets were served to every server scope. On the base, `test_f19` showed a TEST batch's synthetic Sets under REAL and under another TEST batch (as UNKNOWN). Any stored Master would leak synthetic TEST Plans into REAL Due. | `MasterDataScope` (canonical `is_test_data` / `test_batch_id` cells) is fixed on `PmMasterMockStore` at creation and validated. It is read-only and never derived from a request. `PmService` reads or opens work only from a Master whose scope equals the server's own scope cells exactly. Otherwise Fleet/Vehicle Due returns `MASTER_NOT_ACTIVE` with no Plan, assignment or Set data, and opening returns 409 `PM_MASTER_SCOPE_MISMATCH`. A REAL-bound `PmMasterService` refuses any authorizer other than the fail-closed `deny_unproven_master_authority` (403 `PM_MASTER_AUTHORITY_UNPROVEN`, gate VAL-AM). |
| G2 | BACKEND_CROSS_STORAGE | Assignments were checked against another repository object than the runtime's. The bridge tests' `world()` used a fresh `MockRepository()`, and nothing tied assignment-time vehicles to the Work Order's repository. | `MockVehicleResolver.repository` and `PmMasterService.vehicle_repository` expose the exact object. `PmService._master_bound` requires identity (`is`) with the service's repository. Opening returns 409 `PM_MASTER_REPOSITORY_MISMATCH` before any replay lookup, read or write. The resolver now accepts the Mock repository or a Mock subclass (test spies) and still refuses every other adapter. |
| G5 | Test gap | No single proof covered source → Master → E01 → HTTP Fleet Due. | New `test_pm_master_runtime_readiness.py`. |

Both runtime checks run before the existing replay lookup in `open_master_work_order`, so an idempotent replay cannot
bypass them. Valid replays and opens behave exactly as before. Refusals carry no details, so no scope, batch or
Work Order id is disclosed. The existing per-request scope replay guard (`TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH`) is
kept, and is still proven reachable by a Master bound to the foreign server's own scope (`test_22`).

The existing 503 for an unconfigured server scope (`_pm_read_context` / `require_v2_write_context`) already fails
closed before any Master read. RT1 reuses it and does not duplicate it (`test_rt1_f27` passes on the base too).

## 3. Files (7 allowed, 6 changed)
| Path | Status | Classification | Change |
|---|---|---|---|
| `backend/app/domain/pm_master.py` | M | RETAIN + extend | `MasterDataScope`; store `data_scope`; REAL authorizer refusal; resolver `repository` (Mock-subclass aware); service `data_scope` / `vehicle_repository`; module note. |
| `backend/app/domain/pm_service.py` | M | RETAIN + extend | `_master_bound` / `_master_scope_is`; Due read gate; opening checks; docstrings. |
| `backend/tests/test_pm_master_b1_mock.py` | M | test | `test_rt1_01..07` (scope validity and immutability, REAL authorizer refusal, REAL default denial for ADMIN/root/`can_manage_pm`/personas, persona separation on a bound store, resolver identity). |
| `backend/tests/test_pm_master_e01_due_bridge.py` | M | test | `world()`, `test_24`, `test_25` and the restart composition bind TEST scope and the same repository. `test_22` / `test_mv_05` expect the earlier scope refusal. New `test_rt1_08`, `test_rt1_09`. |
| `backend/tests/test_pm_fleet_due.py` | M | test | `test_f19` now expects `MASTER_NOT_ACTIVE` (no Plans/Sets) for REAL and another batch. New `test_rt1_f26`, `test_rt1_f27`. |
| `backend/tests/test_pm_master_runtime_readiness.py` | A | test | End-to-end proof (G5), three tests. |
| `docs/phase-results/r4-pm-master-runtime-readiness-b1-result.md` | A | doc | This report. |

Not touched: router, `dependencies.py`, every repository adapter, frontend, migrations, configuration. No path outside
the allowlist was needed.

## 4. Changed test expectations (each one stricter, none weakened)
| Test | Base expectation | RT1 expectation | Why |
|---|---|---|---|
| `test_f19` | Foreign batch / REAL: synthetic Sets listed as UNKNOWN | `MASTER_NOT_ACTIVE`, no assignments, Plans or Sets (vehicle and fleet) | G1 leak closed |
| `test_22` | Foreign server replay → `TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH` | This batch's Master → `PM_MASTER_SCOPE_MISMATCH` first; a Master bound to the foreign scope → still `TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH` | Earlier refusal; old guard still proven |
| `test_mv_05` (REAL leg) | `PM_MASTER_MODEL_VARIANT_UNVERIFIED` | `PM_MASTER_SCOPE_MISMATCH`, nothing written | Refused earlier, same zero-write proof |

Firewall tests `test_23`, `f24`, `f25`, `test_b1_13`, `test_b1_17` are unchanged and pass. The application wiring
still answers `MASTER_NOT_ACTIVE` and never imports `app.domain.pm_master*`.

## 5. Negative proof against the base
The RT1 tests were run in a throwaway export of the base in which only `pm_master.py` was replaced (giving the new
scope type) and the `pm_service.py` checks were absent. Seven tests **fail** there and pass with RT1: `test_f19`,
`test_rt1_f26`, `test_22`, `test_mv_05`, `test_rt1_08`, `test_rt1_09`, `test_rt1_e2e_03`. This shows the checks in
`pm_service.py` are what block the cross-scope and cross-repository paths.

## 6. End-to-end proof (G5), TEST-only
A synthetic source workbook goes through `register_preview` (REVIEW entries present) → `record_review` → `publish`
(TEST_PM_MASTER_EDITOR) → `set_assignment` (TEST_PM_MASTER_ASSIGNER). The store is bound to the server's TEST batch and
the resolver reads the runtime repository. Then: `open_master_work_order` (`can_manage_pm`) → Technician V2 assign,
start, record → PRIMARY SUBMIT with FAKE IoT anchor → reviewer CLOSE. Reads go through the real app routers via
`GET /api/v1/pm/due/vehicles[/{id}]`, with a test-local `dependency_overrides[get_pm_service]`.

Proven:
- With no Work Order, every Set is listed UNKNOWN `NO_VERIFIED_ACTUAL_SET_COMPLETION` with no next Due and no meter.
  A vehicle without an assignment reads `NO_ASSIGNED_PLAN`.
- CARRIER 500 h done at 1000 → 1500. CRANE 600 h done at **650 → 1250** (DUE at 1250). ODOMETER 10,000 km done at
  50,000 → 60,000.
- CRANE completed again at 1300 → 1900, while CARRIER and ODOMETER keep their anchors from the first Work Order.
- CARRIER NOT_PERFORMED with ODOMETER PERFORMED: only ODOMETER advances (65,000).
- A RETURNed submission and an IN_PROGRESS Work Order change nothing.
- No verified current meter gives UNKNOWN with no next Due and no current meter, never 0. Proven completions stay
  visible.
- Domain and HTTP results are identical at every step.
- `can_view` reads the derived Due (200) but gets 403 on `/outcomes` and `/history`. No capability, or
  `can_manage_pm` alone, gets 403 on both Due routes. GETs cause no state change.
- The same Master over HTTP under REAL and under another batch: `MASTER_NOT_ACTIVE`, with no Plan, Set or batch text
  in the body. An unconfigured scope returns 503.

## 7. Tests and checks
Environment: a scratch virtualenv from `backend/pyproject.toml` `[dev]` plus `requirements.txt` (the container had no
pytest; `gspread` is needed by the Sheets-fake suites). Run from `backend/`.

| Run | Result |
|---|---|
| `pytest -q tests/test_pm_master_runtime_readiness.py` | 3 passed |
| RT1 + Due focused (`runtime_readiness`, `b1_mock`, `e01_due_bridge`, `fleet_due`, `pm_due`, `pm_due_evidence`, `pm_submit_meter_anchor`) | 280 passed, 1 skipped |
| Affected regression (`test_pm_*`, `test_r4_pm_*`, `test_technician*`, `test_v2_*`, `test_repair_pm_work_authorization`, `test_repair_assignment_and_queues`, `test_r3_*`, `test_rev062_queue_derivation`) | 1260 passed, 4 skipped (before the final docstring/refactor edit; covered again by the full run) |
| Firewall subset (`test_23`, `f24`, `f25`, `b1_13`, `b1_17`) | 5 passed |
| Full backend `pytest -q -rs tests` (final source, SHA-256 pinned before the run and re-verified after) | **5857 passed, 0 failed, 4 skipped** (17m50s) |
| `git diff --check` | clean |
| ruff (no repository config; `--isolated` defaults, on the six Python files) | No new findings. The findings in changed files are a subset of the same files at the base (pre-existing I001/UP017/RUF022/RUF059/B017). The new test file is clean. |
| Secret scan of the diff and new file | no matches |

Skips: the opt-in real-workbook test `test_r2_real_workbook_read_only_reconciliation` (no `MAINTENANCE_XLSX`) and
the opt-in live Google Sheets tests. These are the same known skips as the base runs. Not run: frontend (no frontend
file changed).

## 8. PostgreSQL contract (documented, NOT implemented, NOT PASS)
- Every Master table (revisions, Sets/Items, previews, review resolutions, assignments, events, and future OPEN-016
  association approvals) carries `is_test_data` + `test_batch_id`, with a CHECK constraint (`TRUE` + non-blank batch,
  or `FALSE` + empty). Every read filters by the server scope in SQL. An unscoped row is invalid, never REAL by
  default.
- Unique keys: (scope, plan_code, revision_number); (scope, request_id) for Master writes; (scope, vehicle_id,
  assembly, version) for assignments; Master membership (request_id) and (pm_work_order_id).
- Foreign keys from membership and Work Order to vehicle, so assignments, Work Orders and Due all refer to one
  database. This is the PostgreSQL equivalent of G2's object identity.
- One transaction for publish (revision + event), for assignment (record + event), and for opening a Work Order
  (catalogue + Work Order + scope + membership). Stale-revision and stale-assignment checks are enforced by unique
  keys or row locks, not the in-process `asyncio.Lock`.
- The Fleet Due read runs in one read-only snapshot transaction (REPEATABLE READ), with membership reads filtered by
  the page's vehicle ids and indexed.
- REAL publish/assign stays unavailable until an Owner-approved authority exists (OPEN-005 / VAL-AM, R11).

## 9. Mandatory Cleanup Review
| Item | Class | Evidence |
|---|---|---|
| Inline duplicate scope comparison in `open_master_work_order` | REMOVE (done) | Replaced by `_master_scope_is`, shared with `_master_bound`. |
| `_master_bound` used by both the Due read and the opening | RETAIN | One check for G1+G2; no duplicate Due logic. |
| Existing replay scope guard (`TECHNICIAN_ASSIGNMENT_SCOPE_MISMATCH`) | RETAIN | Still reachable and proven (`test_22`). Covers a Master bound to the foreign scope. |
| Existing 503 unconfigured-scope gate | RETAIN (reused) | `test_rt1_f27` passes on the base too. No new check added. |
| Exact-type check in `MockVehicleResolver` | REPLACE | Now an MRO check for `MockRepository`, so the runtime's spy repository can be bound. Non-Mock adapters still refused (`test_b1_fix_06`, `test_rt1_07`). |
| Unbound `PmMasterMockStore()` default | RETAIN | Used by about 30 B1 pure-contract tests. The runtime never accepts it (fail closed). Making scope mandatory would churn every B1 test without adding safety. |
| `with_master_reads` TEST-only injection | RETAIN | Still called by no app module (`test_23`). |
| `evaluate_master_set_due` | RETAIN, unchanged | Takes no Master and already filters memberships by server scope. |
| Legacy runtime / Technician V2 toggle | not reintroduced | — |
| Pre-existing ruff findings and long lines in these files | DEFER | Baseline; out of RT1 scope. |

## 10. Remaining limitations and open gates
- Mock only. No persisted Master; Google Sheets has no Master storage (explicit `pm_master_bridge` refusal, kept).
  No PostgreSQL schema.
- The in-process lock is not multi-process atomicity.
- OPEN-005: REAL Publish/Assign authority is still fail-closed. TEST personas remain test-local.
- OPEN-016: no approved association store (RT2). The 183 source candidates stay PENDING and the 52 without a Plan
  fail closed.
- OPEN-012: real opening meters and previous real PM completions are unknown and stay UNKNOWN. There is no real IoT
  source (R9).
- Model `component_roles` are blank in the live Sheet. Real assembly assignments and engine resolution stay blocked
  until supplied.
- The real `MAINTENANCE.xlsx` has never been run through the Python preview (UNVERIFIED).
- E02 near-due / overdue thresholds and calendar / multiple-condition triggers are not decided and not invented.
- R4 overall remains PARTIAL. Next proposed steps (separate authorization): RT2 (OPEN-016 association record and
  source) and RT3 (Master persistence interface and PostgreSQL contract).
