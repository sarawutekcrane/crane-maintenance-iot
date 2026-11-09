# R4 / TASK-010 — RT4-B Fleet Due Master Snapshot Safety — Result

**Status:** RT4-B CANDIDATE. UNSTAGED and UNCOMMITTED, local only, waiting for independent review. This is Mock/Fake
evidence only. It is not a PostgreSQL PASS, not Production readiness and not R4 completion. No Git write action was
taken. **No real source activation is authorized, and the Production Master remains dormant.**

**Authorization:** Owner-approved bounded RT4-B implementation (3-path allowlist) on
`feature/r4-pm-readiness-reconciliation-b1`, exact base `71834f59879b715bb3b425d90ea8f038d9ec3a73` (XR-04/XR-07). Source:
defect **D-2** of the post-RT3-B reconciliation, confirmed by the source-proof / R11 readiness reconciliation.

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote HEAD | `origin/feature/r4-pm-readiness-reconciliation-b1` = `71834f5…9d73a73` (exact base, fetched) |
| Checkout | A fresh clone of the remote branch in the session scratchpad, at the base, with push disabled. Every earlier checkout (RT4-A copy, XR clone, source-proof clone) was left untouched. |
| HEAD after work | Unchanged at the base; every change unstaged |

## 2. Root cause (D-2, BACKEND_CROSS_STORAGE)
`PmService._pm_due_rows` checked `_master_bound` and then awaited `list_pm_master_memberships`. After that,
`_vehicle_pm_due` read the live Master **per vehicle**, with awaited repository and IoT reads in between:
- `resolve_plan` for each assembly;
- `effective_revision`, cached per Plan from the first vehicle that named it;
- `_variant_source(...)`, a closure over `store.latest_variant_approval`.

A Master write landing during any of those awaits was therefore seen by the later vehicles of the same page only.
The same Fleet Due response could mix Master states.

Reproduced at the base by the new tests (§4):
- **First await:** a write during `list_pm_master_memberships` gives a page that is entirely post-write.
- **Per-vehicle read:** a write during `list_vehicle_components` between the two vehicles gives a mixed page, with
  vehicle A pre-write and vehicle B post-write, for revoke, unassignment, reassignment and correction.

## 3. Correction: the snapshot boundary
| Where | Change |
|---|---|
| `PmService._snapshot_master` (new, synchronous) | One pass over the page's vehicles, with **no await**: (1) `resolve_plan` for every vehicle × `PLAN_ASSEMBLIES`; (2) each assigned Plan's `effective_revision`, once; (3) the variant source (the explicit TEST seam if injected, otherwise the bound Master's own approvals) is **called now** for every (vehicle `model_id`, assigned Plan) pair, and the returned `frozenset` is stored. No service, store, mutable collection or live closure is retained. |
| `_PmDueReadCache` | Two request-local fields next to the existing `heads`: `resolutions` (vehicle id → {assembly: PlanResolution}) and `variants` ((model id, Plan) → frozenset). `PlanResolution` and `MasterRevision` are frozen models. |
| `_pm_due_rows` | The request cache is created, and `_snapshot_master` runs, after the unchanged `_master_bound` and empty-page checks and **before the first await** (`list_pm_master_memberships`). The cache's `at` instant therefore moves before the membership read; it is still taken once per request. |
| `_vehicle_pm_due` | Reads only `cache.resolutions` and `cache.heads`, and passes `applicable_plans` a request-local callable backed **only** by `cache.variants`. It calls no live `resolve_plan`, `effective_revision` or `model_variant_source`. |

**Vehicle-model verification is unchanged:**
- `get_vehicle_model` is still awaited, and its `model_id` (or `""`) is the only key used for the variant lookup.
- The frozen table is keyed by the vehicle's `model_id`, but it is consulted only with the **repository-verified** id.
- A model that does not exist verifies to `""`, and `applicable_plans` never asks for a blank model. A verified id with
  no frozen entry finds nothing, which is MODEL_VARIANT_UNVERIFIED (fail-closed).
- Approval is never inferred from the raw `model_id`, a model name, a source Plan name or a mapping candidate.

**Unchanged:**
- **Guards:** `_master_bound` (an unbound, foreign-scope or foreign-repository Master gives `MASTER_NOT_ACTIVE` with
  **no Master read**), the empty page, the trusted actor and `can_view`, the TEST/REAL and batch scope (503 when
  unconfigured) and the PM list integrity check — all before the snapshot.
- **Evaluation:** membership duplicate, provenance and evidence checks; the response shape; applicability; the head
  revision; Set and Item provenance; Due, explanation and UNKNOWN.
- **Nothing new:** no fallback, no route, lock or global cache.

## 4. Deterministic concurrency evidence (`test_pm_fleet_due.py`, 15 new test cases)
- **Fixture:** two vehicles of one model (VEH-1047 and synthetic VEH-SYN-3047) are assigned to one Plan through the real
  RT2 Master, using its own evidenced approval with no explicit variant seam.
- **Injection:** `hook_once` runs one Master write (through the real authorized `PmMasterService` API) **inside** the
  first call of a real awaited repository coroutine. That is either the read's first await,
  `list_pm_master_memberships`, or the per-vehicle `list_vehicle_components` made between the two vehicles. There are
  no sleeps.
- **Assertions:** the in-flight page equals the page read just before the write, for every vehicle, and the next
  request shows the write.

| Test | Proves (both boundaries unless noted) |
|---|---|
| `rt4b_01` revoke | In-flight page = pre-revoke (RESOLVED SYN-M1, Sets listed); next read: MODEL_VARIANT_UNVERIFIED, no Sets, for both vehicles |
| `rt4b_02` unassignment | In-flight page keeps vehicle B's assignment; next read: B NO_ASSIGNED_PLAN (EXPLICIT_NONE); A unchanged |
| `rt4b_03` reassignment | In-flight page keeps B on Plan 1; next read: B on Plan 2; A unchanged |
| `rt4b_04` new revision | In-flight page keeps revision 1 for every Set; next read: revision 2, with no completion carried across revisions |
| `rt4b_05` variant correction | In-flight page keeps SYN-M1; next read: SYN-M3 Plans and Sets for both vehicles |
| `rt4b_06` | The single-vehicle route equals that vehicle's fleet row (one Master state) |
| `rt4b_07` | The fleet and vehicle GETs change nothing: Work Orders, memberships, snapshots, anchors, journal, catalogue, outcomes, results, Master revisions, approvals, previews, resolutions, assignments, audit events |
| `rt4b_08` | No Master, unbound, other TEST batch, REAL, another repository, no resolver, and the bound Master read by a server of another batch: every row `MASTER_NOT_ACTIVE` with no assignment, Plan or Set. The Master's read methods are replaced by failing spies and are **never called**. |
| `rt4b_09` | Unrelated Master writes (another model's approval, another vehicle's assignment) change nothing for these vehicles, in flight or after |
| `rt4b_10` | No capability, `can_manage_pm` only, and no trusted actor give 403 on both routes **before** any Master read (spies never called) |

**Fail-closed evidence paths are unchanged and re-run:** `f14`–`f17` and `r2_01`–`r2_04` (corrupt or foreign
membership and journal evidence give 500/409), `f22` (an adapter without bridge storage gives FEATURE_NOT_AVAILABLE),
and `rt1_f26` / `rt1_f27`.

**Against the base `pm_service.py`** (disposable copy), the RT4-B selection fails **9 of 17**:
- `rt4b_01`, `rt4b_02`, `rt4b_03` and `rt4b_05` at both boundaries;
- `rt4b_04` at the first-await boundary only. At the per-vehicle boundary the base already reused its per-Plan head
  cache, so a new revision could not mix there.

## 5. Mutation checks (disposable copies under the session scratchpad; the repository source was never mutated)
| Mutant | Killed by (in-flight page ≠ pre-write page, or an inactive Master read / disclosed) |
|---|---|
| M1 per-vehicle live `resolve_plan` restored | `rt4b_02`, `rt4b_03` (both boundaries) |
| M2 snapshot taken after the first await | `rt4b_01`–`rt4b_05` at the first-await boundary |
| M3 live variant source instead of frozen values | `rt4b_01`, `rt4b_05` (both boundaries) |
| M4 live `effective_revision` per vehicle | `rt4b_04` (both boundaries) |
| M5 `_master_bound` bypassed (only "a Master exists") | `rt4b_08` (Master read on an inactive Master), `rt1_f26`, `f19` (disclosure) |

**5 / 5 killed**, all by assertion failures on the observable page or on the disclosure and read spies; none by an
import error, a fixture error or a crash. Re-run on the final bytes with identical results.

## 6. Results (synthetic Mock / Fake data only; `pytest -q -rs -p no:cacheprovider`, scratch venv from `pyproject.toml` `[dev]` + `requirements.txt`)
| Run (from `backend/`) | Result |
|---|---|
| `test_pm_fleet_due.py` (33 existing + 15 new) | **48 passed** |
| Affected (`test_pm_*`, `test_r4_pm_*`, `test_technician*`, `test_v2_*`, `test_r3_*`, `test_access_management*`, `test_repair_request*`, `test_defect_provenance`, `test_repair_pm_work_authorization`, `test_repair_assignment_and_queues`, `test_rev062_queue_derivation`, `test_rev06_identity_and_core_g01_regression`) | **1429 passed, 0 failed, 4 skipped** (56 files, 4m33s; run in a disposable copy byte-identical to the final source) |
| Full backend `pytest -q -rs tests` (final source, SHA-256 pinned before the run and re-verified after) | **5925 passed, 0 failed, 4 skipped** (17m25s). The XR-04/XR-07 batch reported 5910; the difference is the 15 new RT4-B test cases. Skips are the known opt-in ones: the real `MAINTENANCE.xlsx` reconciliation and 3 live Google Sheets tests. |
| Firewall tests (`test_23`, `f24`, `f25`, `b1_13`, `b1_17`, `r2_07`); RT1–RT4-A; XR-04 / XR-07 | inside the runs above, unchanged |
| `git diff --check` | clean |
| ruff (`--isolated` defaults; changed files vs. the base file at the same path) | no new findings |
| Secret scan | no matches |

## 7. Files (3 allowed, 3 changed)
| Path | Status | Change |
|---|---|---|
| `backend/app/domain/pm_service.py` | M | `_snapshot_master` (new), two `_PmDueReadCache` fields, cache and snapshot before the first await in `_pm_due_rows`, `_vehicle_pm_due` reads the snapshot; docstring note |
| `backend/tests/test_pm_fleet_due.py` | M | `rt4b_01..10` (15 cases), helpers `two_vehicle_world`, `master_svc`, `fleet_page`, `hook_once`, `one_master_epoch`, `plan_view`, `spy_master` |
| `docs/phase-results/r4-pm-fleet-due-master-snapshot-rt4b-result.md` | A | This report |

Not touched: `pm_master.py`, `pm_master_runtime.py`, repositories, Sheets, routes, `dependencies.py`, frontend, schema.

## 8. Mandatory Cleanup Review
| Item | Class | Evidence / impact |
|---|---|---|
| Per-vehicle live Master reads in `_vehicle_pm_due` | REPLACE | Now read once by `_snapshot_master`; mutants M1, M3 and M4 prove each part is load-bearing |
| `_snapshot_master` | RETAIN (new) | Synchronous by design (cannot yield); a method of the existing service; no new service, store or framework |
| `_PmDueReadCache.resolutions` / `.variants` | RETAIN (new fields) | Request-local, beside the existing `heads`; values only; no global cache |
| `_PmDueReadCache.heads` | RETAIN (now filled by the snapshot) | Same field, now always complete before the first await |
| `_variant_source` | RETAIN | Still the single source selector (TEST seam or the Master's approvals); called once per page |
| `_master_bound` gate | RETAIN | Unchanged and first; M5 proves it |
| `evaluate_master_set_due` (internal, no route) | DEFER | It reads no Master assignment, head or approval (memberships and catalogue only), so D-2 does not apply to it; unchanged |
| Repository read consistency (vehicles, models, components, memberships, journal, IoT, anchors) | DEFER (R11) | Not frozen by RT4-B; it needs one database read-only snapshot |

No destructive cleanup.

## 9. Unresolved PostgreSQL R11 consistency requirements
- **RT4-B is Mock, in-process, Master-only consistency.** It freezes the Master's assignments, heads and approvals for
  one request. It does **not** freeze the vehicle list and paging, vehicle models, components, Work Order evidence, the
  E01 journal, IoT observations or SUBMIT anchors.
- **R11 PostgreSQL still requires a complete read-only transaction snapshot** (REPEATABLE READ) over the Master tables
  and every repository record the Due read uses.
- Also still R11: durable Master storage, a repository-backed vehicle resolver, transactional Work Order + open
  snapshot and SUBMIT + anchor, the Repair Request unique source, the Access Management log key, and real concurrency
  tests.

## 10. Git state
- `HEAD` is unchanged at `71834f59879b715bb3b425d90ea8f038d9ec3a73`. Nothing is staged; nothing was committed or pushed.
- Working tree: `M backend/app/domain/pm_service.py`, `M backend/tests/test_pm_fleet_due.py`,
  `?? docs/phase-results/r4-pm-fleet-due-master-snapshot-rt4b-result.md`.

**R4 remains PARTIAL.** OPEN-005 (REAL authority fail-closed), OPEN-012 (meters and prior PM UNKNOWN), OPEN-016 data
(candidates are not approvals), E02 (no thresholds), the component-topology source gate and R11 are unchanged.
